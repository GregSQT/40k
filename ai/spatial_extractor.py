#!/usr/bin/env python3
"""ai/spatial_extractor.py — extracteur à ENCODEURS D'ENTITÉS PARTAGÉS (V11 §0.30, tranche T-D).

L'observation squad n'est plus un vecteur plat mais un jeu de tenseurs d'entités
(`engine/observation_builder.py`, en-tête « OBSERVATION SQUAD — TENSEURS D'ENTITÉS ») :

  global_cont / global_bin        contexte (aucune entité)
  allies_*  (K_a, …)              ⚠ LIGNE 0 = l'unité ACTIVE
  enemies_* (K_e, …)              ⚠ ordre CONTRACTUEL = slots d'action de tir (invariant D1)
  self_models_*                   figurines de l'unité active
  grid                            grille égocentrique (CNN)

Ce que l'extracteur apporte, et que le format plat interdisait (V11_entity_encoder_pointer.md
§1.8, mesuré) : **le même petit réseau est appliqué à chaque entité**. Une arme est encodée par
`E_w` qu'elle soit à moi ou à l'ennemi ; une unité par `E_u` qu'elle soit alliée ou ennemie. Le
réseau généralise donc d'un slot à l'autre — au format plat, chaque slot ennemi avait ses
propres poids de première couche (~226 k paramètres par slot) et réapprenait tout de zéro.

Agrégation : elle n'est appliquée QU'À ce qu'aucune action ne désigne (§3.1). Les embeddings
ennemis PAR SLOT sont conservés et concaténés en fin de vecteur de features — c'est l'alignement
obs-slot-i ↔ action-slot-i (fix D1) et le point d'accroche de la tête pointeur (T-E), qui les
lira par `enemy_embeddings_slice()`.

MÊME RAISONNEMENT POUR LA GRILLE (V11 §0.32 T-G) : 1024 des 1082 actions désignent une CELLULE
(1082 depuis §9 P3-1, qui a ajouté les 20 slots de cible de mêlée + le combat à vide).
Aplatir la carte CNN avant la tête, c'est refaire côté move exactement ce que le format plat
faisait côté tir. Une seconde branche CNN, à résolution PLEINE (32x32, aucun stride), est donc
conservée et concaténée elle aussi en fin de vecteur (`move_map_slice()`) : la tête de move
(`ai/pointer_policy.py`) y applique une conv 1x1, une colonne de features par cellule.
La branche aplatie (`self.cnn` -> `cnn_head`) reste : elle alimente le tronc, qui a besoin d'un
resume GLOBAL de la fenetre, pas d'une carte. Les deux branches partagent le STEM (`cnn_stem`),
la premiere convolution pleine resolution : la dupliquer ferait recalculer les memes features de
bas niveau (bords de murs, contours d'EZ) que les deux branches veulent de toute facon
identiques. Mesure ci-dessous.

⚠️ CANAUX POSITIONNELS (amendement §0.32 T-G) : la carte porte 3 canaux fixes (x, y, rayon),
sans quoi la tete 1x1 serait STRICTEMENT PLUS FAIBLE que la tete dense qu'elle remplace. La
grille est egocentrique et normalisee par le budget d'Advance : la semantique d'une cellule
depend de son RAYON (centre = mon bloc, |r| = 1 = limite d'atteignabilite). Une convolution est
invariante par translation, donc incapable d'exprimer « le centre n'est pas le bord » — alors
que la tete dense, elle, sait ou est chaque cellule. Ces canaux sont l'exact jumeau de
`spatial_grid.cell_center_px` en coordonnees normalisees (verrouille par test).

Normalisation (point dur identifié §4 T-D) : `VecNormalize` normalise ÉLÉMENT PAR ÉLÉMENT ;
appliqué aux tenseurs d'entités, chaque slot aurait ses propres statistiques et le même encodeur
verrait des échelles différentes selon le slot — ce qui annulerait le partage de poids. Les clés
d'entités sont donc HORS `norm_obs_keys` (ai/train.py) et normalisées ICI par
`EntityRunningNorm` : une statistique par feature, COMMUNE à tous les slots et aux deux camps.

Aucun repli, aucune valeur par défaut masquant une erreur : les formes viennent de l'espace
d'observation et toute clé manquante lève.
"""

from typing import Dict, List, Sequence, Tuple

import gymnasium as gym
import torch
import torch.nn as nn
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from engine.observation_entities import self_model_bin_index, unit_bin_index
from engine.spatial_grid import GRID_CELL_COUNT, GRID_CHANNELS, GRID_SIZE

#: Familles d'unités partageant le MÊME schéma et le MÊME encodeur.
_UNIT_FAMILIES = ("allies", "enemies")

#: Canaux positionnels FIXES ajoutés à la carte de move : x, y, rayon (V11 §0.32 T-G).
POSITIONAL_CHANNELS = 3

#: Index des masques de présence — LUS depuis le schéma, jamais recopiés. Convention uniforme
#: depuis §0.37 : `present` est le DERNIER champ de chaque registre.
_SELF_MODEL_PRESENT_IDX = self_model_bin_index("present")
_UNIT_PRESENT_IDX = unit_bin_index("present")


class EntityRunningNorm(nn.Module):
    """Normalisation par feature à statistiques GLISSANTES, partagées entre tous les slots.

    Équivalent de `VecNormalize` pour un tenseur d'entités, à une différence essentielle : la
    moyenne et la variance sont estimées sur l'ENSEMBLE des entités valides (tous slots, les
    deux camps puisque le module est partagé), pas slot par slot. C'est ce qui rend le partage
    de poids de l'encodeur légitime — sans quoi le slot 0 et le slot 9 arriveraient au même
    réseau avec deux échelles différentes.

    Les entités absentes (padding) sont exclues de l'estimation par le masque : les compter
    ferait converger toutes les statistiques vers zéro dès qu'un slot est vide.
    """

    def __init__(self, num_features: int, epsilon: float = 1e-8, clip: float = 10.0):
        super().__init__()
        if num_features <= 0:
            raise ValueError(f"EntityRunningNorm : num_features doit etre > 0, recu {num_features}")
        self.epsilon = float(epsilon)
        self.clip = float(clip)
        self.register_buffer("running_mean", torch.zeros(num_features))
        self.register_buffer("running_var", torch.ones(num_features))
        self.register_buffer("count", torch.tensor(1e-4))

    @torch.no_grad()
    def _update(self, flat: torch.Tensor, weights: torch.Tensor) -> None:
        """Mise à jour parallèle (Chan et al.) sur les seules entités valides."""
        batch_count = weights.sum()
        if float(batch_count) < 1.0:
            return
        w = weights.unsqueeze(-1)
        batch_mean = (flat * w).sum(dim=0) / batch_count
        batch_var = (((flat - batch_mean) ** 2) * w).sum(dim=0) / batch_count
        delta = batch_mean - self.running_mean
        tot = self.count + batch_count
        new_mean = self.running_mean + delta * batch_count / tot
        m_a = self.running_var * self.count
        m_b = batch_var * batch_count
        new_var = (m_a + m_b + delta**2 * self.count * batch_count / tot) / tot
        self.running_mean.copy_(new_mean)
        self.running_var.copy_(new_var)
        self.count.copy_(tot)

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """`x` : (…, F). `mask` : (…) à 1 sur les entités présentes.

        Le masque est lu comme une PRÉSENCE (`> 0`), conformément au contrat de l'observation
        (les clés "_bin" sont discrètes). Le prendre comme une pondération quelconque rendrait
        le compte d'entités — donc le dénominateur des statistiques — arbitraire.
        """
        flat = x.reshape(-1, x.shape[-1])
        weights = (mask.reshape(-1) > 0).to(flat.dtype)
        if self.training:
            self._update(flat.detach(), weights.detach())
        normed = (x - self.running_mean) / torch.sqrt(self.running_var + self.epsilon)
        normed = torch.clamp(normed, -self.clip, self.clip)
        # Une entité absente ne doit PAS acquérir une valeur non nulle par recentrage : son
        # embedding serait alors indistinguable d'une entité réelle avant même le masquage.
        return normed * (mask > 0).to(normed.dtype).unsqueeze(-1)


def _mlp(sizes: Sequence[int]) -> nn.Sequential:
    layers: List[nn.Module] = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        layers.append(nn.ReLU())
    return nn.Sequential(*layers)


def positional_channels() -> torch.Tensor:
    """Canaux positionnels FIXES de la grille égocentrique : (1, 3, GRID_SIZE, GRID_SIZE).

    Canal 0 = x, canal 1 = y, canal 2 = rayon — TOUS en unités de demi-étendue de grille, donc
    en unités de **budget d'Advance maximal** de l'escouade (`grid_half_extent_subhex`). Ce sont
    exactement les coordonnées normalisées de `spatial_grid.cell_center_px` :

        x(gx) = ((gx + 0.5) / GRID_SIZE) * 2 - 1        (idem y avec gy)

    donc `rayon = 1.0` est la limite d'atteignabilité, quelle que soit l'unité et quelle que soit
    l'échelle du board. C'est CETTE grandeur qu'une conv 1x1 seule ne pourrait pas reconstruire
    (invariance par translation), et que la tête dense qu'on remplace connaissait par construction.

    Convention d'indexation : dim 1 = `gy`, dim 2 = `gx` — celle de `build_squad_grid`
    (`grid[channel][gy, gx]`) et celle de `cell_index = gy * GRID_SIZE + gx`.
    """
    coord = (torch.arange(GRID_SIZE, dtype=torch.float32) + 0.5) / GRID_SIZE * 2.0 - 1.0
    y, x = torch.meshgrid(coord, coord, indexing="ij")
    radius = torch.sqrt(x * x + y * y)
    return torch.stack([x, y, radius], dim=0).unsqueeze(0)


def _masked_mean_max(emb: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Agrégation MASQUÉE d'un ensemble d'embeddings : concat(moyenne, max).

    `emb` : (B, K, D) ; `mask` : (B, K). Un ensemble vide donne zéro (et non NaN, ni le max de
    valeurs de padding — d'où le `-inf` sur les entités absentes avant le max).
    """
    present = (mask > 0).to(emb.dtype)
    m = present.unsqueeze(-1)
    count = present.sum(dim=1, keepdim=True).clamp(min=1.0)
    mean = (emb * m).sum(dim=1) / count
    neg_inf = torch.finfo(emb.dtype).min
    maxed = torch.where(m.bool(), emb, torch.full_like(emb, neg_inf)).max(dim=1).values
    maxed = torch.where((present > 0).any(dim=1, keepdim=True), maxed, torch.zeros_like(maxed))
    return torch.cat([mean, maxed], dim=1)


class SpatialCombinedExtractor(BaseFeaturesExtractor):
    """CNN sur "grid" + encodeurs d'entités PARTAGÉS + agrégation masquée.

    Sortie (dans cet ordre — contrat consommé par les têtes de `ai/pointer_policy.py`) :

        [ trunk_features (self.trunk_dim)
        | embeddings ennemis PAR SLOT (K_e × entity_dim)          -> tête pointeur de TIR (T-E)
        | carte de move NON aplatie (move_map_channels × 32 × 32) -> tête 1x1 de MOVE (T-G) ]

    `cnn_features` : dimension de la sortie CNN. OBLIGATOIRE, sans défaut — la valeur vient de
    la config JSON de l'agent (`model_params.policy_kwargs.features_extractor_kwargs`).
    `entity_dim` / `weapon_dim` / `type_dim` / `model_dim` / `map_channels` : largeurs des
    encodeurs partagés et de la branche carte.
    """

    def __init__(
        self,
        observation_space: gym.spaces.Dict,
        cnn_features: int,
        entity_dim: int = 64,
        weapon_dim: int = 32,
        type_dim: int = 16,
        model_dim: int = 16,
        map_channels: int = 16,
    ):
        if not isinstance(cnn_features, int) or cnn_features <= 0:
            raise ValueError(
                f"SpatialCombinedExtractor : cnn_features doit etre un entier > 0, recu {cnn_features!r}"
            )
        if not isinstance(map_channels, int) or map_channels <= 0:
            raise ValueError(
                f"SpatialCombinedExtractor : map_channels doit etre un entier > 0, recu {map_channels!r}"
            )
        if not isinstance(observation_space, gym.spaces.Dict):
            raise TypeError(
                f"SpatialCombinedExtractor attend un espace Dict, recu {type(observation_space)}"
            )
        expected_keys = [
            "global_cont", "global_bin", "self_models_cont", "self_models_bin", "grid",
            "decision_ctx_bin", "decision_options_bin",
        ]
        for family in _UNIT_FAMILIES:
            expected_keys += [
                f"{family}_cont", f"{family}_bin",
                f"{family}_wpn_cont", f"{family}_wpn_bin",
                f"{family}_types_cont", f"{family}_types_bin",
            ]
        for key in expected_keys:
            if key not in observation_space.spaces:
                raise KeyError(
                    f"SpatialCombinedExtractor : cle '{key}' absente de l'espace d'observation "
                    f"({sorted(observation_space.spaces.keys())})"
                )

        grid_space = observation_space.spaces["grid"]
        if grid_space.shape != (GRID_CHANNELS, GRID_SIZE, GRID_SIZE):
            raise ValueError(
                f"SpatialCombinedExtractor : forme de grille inattendue {grid_space.shape}, "
                f"attendu {(GRID_CHANNELS, GRID_SIZE, GRID_SIZE)}"
            )

        def _shape(key: str) -> Tuple[int, ...]:
            shape = observation_space.spaces[key].shape
            if shape is None:
                raise ValueError(f"SpatialCombinedExtractor : '{key}' sans forme")
            return tuple(int(d) for d in shape)

        # Le schéma d'unité est UNIFIÉ : allié et ennemi partagent leurs dimensions, sans quoi
        # un encodeur commun n'aurait pas de sens (§3.3).
        for suffix in ("cont", "bin", "wpn_cont", "wpn_bin", "types_cont", "types_bin"):
            ally_shape = _shape(f"allies_{suffix}")[1:]
            enemy_shape = _shape(f"enemies_{suffix}")[1:]
            if ally_shape != enemy_shape:
                raise ValueError(
                    f"SpatialCombinedExtractor : schema d'unite divergent sur '{suffix}' "
                    f"(allies {ally_shape} vs enemies {enemy_shape}) — l'encodeur partage "
                    f"exige un schema unifie."
                )

        self.n_ally_slots, self.unit_cont_dim = _shape("allies_cont")
        self.unit_bin_dim = _shape("allies_bin")[1]
        self.n_enemy_slots = _shape("enemies_cont")[0]
        _, self.n_weapons, self.weapon_cont_dim = _shape("allies_wpn_cont")
        self.weapon_bin_dim = _shape("allies_wpn_bin")[2]
        _, self.n_types, self.type_cont_dim = _shape("allies_types_cont")
        self.type_bin_dim = _shape("allies_types_bin")[2]
        self.n_self_models, self.self_model_cont_dim = _shape("self_models_cont")
        self.self_model_bin_dim = _shape("self_models_bin")[1]
        global_dim = _shape("global_cont")[0] + _shape("global_bin")[0]
        self.decision_ctx_dim = _shape("decision_ctx_bin")[0]
        self.n_decision_options, self.decision_option_dim = _shape("decision_options_bin")

        weapon_agg = 2 * weapon_dim
        type_agg = 2 * type_dim
        model_agg = 2 * model_dim
        trunk_dim = (
            cnn_features
            + global_dim
            + entity_dim              # e_own (unité active)
            + 2 * entity_dim          # agrégation de mes autres escouades
            + 2 * entity_dim          # agrégation des ennemies (contexte)
            + model_agg
            # Contexte de décision : quel type de choix est demandé, et un résumé de ce que les
            # candidats offrent. Le tronc en a besoin pour la VALEUR de l'état et pour scorer
            # les candidats en connaissance du reste de la partie (leurs embeddings par slot, eux,
            # partent directement à la tête pointeur — cf. `decision_embeddings_slice`).
            + self.decision_ctx_dim
            + 2 * entity_dim
        )
        # La carte de move sort du réseau AVEC ses canaux positionnels : la tête 1x1 doit les
        # voir directement, pas seulement à travers la pile conv.
        move_map_channels = map_channels + POSITIONAL_CHANNELS
        super().__init__(
            observation_space,
            features_dim=(
                trunk_dim
                + self.n_enemy_slots * entity_dim
                + move_map_channels * GRID_CELL_COUNT
                + self.n_decision_options * entity_dim
            ),
        )
        self.trunk_dim = trunk_dim
        self.entity_dim = entity_dim
        self.map_channels = map_channels
        self.move_map_channels = move_map_channels

        # --- CNN : un STEM commun à pleine résolution, puis deux branches (V11 §0.32 T-G) ---
        # Le stem est la première convolution, celle qui lit les 9 canaux bruts en 32x32. Elle
        # servait déjà au tronc ; la branche carte la RÉUTILISE au lieu d'en recréer une jumelle.
        # MESURÉ (piles conv isolées, batch 256, 4 threads, 5 mesures alternées) : par rapport au
        # CNN d'avant T-G, la branche carte coûte +58 % en partageant le stem contre +98 % en le
        # dupliquant — 1,7x moins cher, et 3 056 paramètres de moins. Sur le forward COMPLET,
        # l'écart entre les deux variantes est SOUS le bruit de la machine (±10 %) : les encodeurs
        # d'entités dominent. C'est la mesure isolée qui tranche, pas la mesure de bout en bout.
        self.cnn_stem = nn.Sequential(
            nn.Conv2d(GRID_CHANNELS, 32, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
        )
        # Branche TRONC : sous-échantillonnée puis aplatie — c'est un résumé GLOBAL de la fenêtre,
        # pas une carte. Elle reste strictement ce qu'elle était.
        self.cnn = nn.Sequential(
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        with torch.no_grad():
            n_flatten = self.cnn(torch.zeros(1, 32, GRID_SIZE, GRID_SIZE)).shape[1]
        self.cnn_head = nn.Sequential(nn.Linear(n_flatten, cnn_features), nn.ReLU())

        # Branche CARTE : résolution PLEINE, aucun stride, jamais aplatie. Le stride est ce qui
        # détruit la correspondance cellule <-> action : après deux stride 2, une colonne de
        # features couvre 16 cellules et ne peut plus en scorer une seule. Stem 3x3 + cette
        # couche 3x3 -> champ réceptif 5x5 par cellule : de quoi lire son voisinage (murs, EZ,
        # couvert) ; tout ce qui dépasse ce voisinage arrive par le CONDITIONNEMENT de la tête
        # (latent du tronc), pas par cette pile.
        self.register_buffer("pos_channels", positional_channels())
        self.map_net = nn.Sequential(
            nn.Conv2d(
                32 + POSITIONAL_CHANNELS, map_channels, kernel_size=3, stride=1, padding=1
            ),
            nn.ReLU(),
        )

        # --- Normalisations partagées (une par famille de features, PAS une par camp) ---
        self.unit_norm = EntityRunningNorm(self.unit_cont_dim)
        self.weapon_norm = EntityRunningNorm(self.weapon_cont_dim)
        self.type_norm = EntityRunningNorm(self.type_cont_dim)
        self.self_model_norm = EntityRunningNorm(self.self_model_cont_dim)

        # --- Encodeurs PARTAGÉS (un seul module, appliqué aux deux camps) ---
        self.weapon_encoder = _mlp(
            [self.weapon_cont_dim + self.weapon_bin_dim, weapon_dim, weapon_dim]
        )
        self.type_encoder = _mlp([self.type_cont_dim + self.type_bin_dim, type_dim])
        self.self_model_encoder = _mlp(
            [self.self_model_cont_dim + self.self_model_bin_dim, model_dim]
        )
        self.unit_encoder = _mlp(
            [
                self.unit_cont_dim + self.unit_bin_dim + weapon_agg + type_agg,
                2 * entity_dim,
                entity_dim,
            ]
        )
        # Encodeur de CANDIDAT de décision (V11 §9.3 P2) : un seul module pour tous les slots et
        # tous les types de décision — même raison que pour les unités et les armes. Un candidat
        # n'a aucune sémantique de position (l'option 0 d'un prompt n'a rien à voir avec l'option 0
        # d'un autre) : des poids par slot n'auraient RIEN à généraliser. Il sort en `entity_dim`
        # pour que la tête pointeur le score exactement comme un slot ennemi.
        # Aucune `EntityRunningNorm` : le registre de candidat est entièrement DISCRET (§0.32 T-J
        # — une valeur discrète n'est jamais normalisée).
        self.decision_encoder = _mlp([self.decision_option_dim, entity_dim, entity_dim])

    # -- contrat de découpe consommé par les têtes d'action (T-E, T-G) ------------
    def enemy_embeddings_slice(self) -> slice:
        """Tranche des embeddings ennemis PAR SLOT dans le vecteur de features."""
        return slice(self.trunk_dim, self.trunk_dim + self.n_enemy_slots * self.entity_dim)

    def move_map_slice(self) -> slice:
        """Tranche de la carte de move APLATIE dans le vecteur de features.

        Aplatie SEULEMENT pour transiter (le contrat SB3 d'un extracteur est un tenseur 2D) ; la
        tête la remet en (B, C, GRID_SIZE, GRID_SIZE) avant d'y appliquer sa conv 1x1. Rien n'est
        mélangé entre cellules au passage — c'est un `reshape`, pas un `Linear`.
        """
        start = self.enemy_embeddings_slice().stop
        return slice(start, start + self.move_map_channels * GRID_CELL_COUNT)

    def decision_embeddings_slice(self) -> slice:
        """Tranche des embeddings de CANDIDATS de décision, PAR SLOT (V11 §9.3 P2).

        Placée en DERNIER : les tranches déjà consommées par les têtes de tir et de move gardent
        leurs bornes, un ajout en tête les aurait toutes décalées en silence.
        """
        start = self.move_map_slice().stop
        return slice(start, start + self.n_decision_options * self.entity_dim)

    def _encode_units(self, obs: Dict[str, torch.Tensor], family: str) -> torch.Tensor:
        """Embeddings (B, K, entity_dim) d'une famille d'unités, encodeurs PARTAGÉS."""
        unit_cont = obs[f"{family}_cont"]
        unit_bin = obs[f"{family}_bin"]
        present = unit_bin[..., _UNIT_PRESENT_IDX]  # lu du schéma (dernier champ, §0.37)
        b, k = unit_cont.shape[0], unit_cont.shape[1]

        wpn_cont = obs[f"{family}_wpn_cont"]
        wpn_bin = obs[f"{family}_wpn_bin"]
        wpn_mask = wpn_bin[..., -1]  # dernier drapeau de profil = slot occupé
        wpn_in = torch.cat([self.weapon_norm(wpn_cont, wpn_mask), wpn_bin], dim=-1)
        wpn_emb = self.weapon_encoder(wpn_in)
        wpn_agg = _masked_mean_max(
            wpn_emb.reshape(b * k, wpn_emb.shape[2], wpn_emb.shape[3]),
            wpn_mask.reshape(b * k, wpn_mask.shape[2]),
        ).reshape(b, k, -1)

        typ_cont = obs[f"{family}_types_cont"]
        typ_bin = obs[f"{family}_types_bin"]
        typ_mask = typ_bin[..., -1]  # MODEL_TYPE_BIN_FIELDS[-1] == "present"
        typ_in = torch.cat([self.type_norm(typ_cont, typ_mask), typ_bin], dim=-1)
        typ_emb = self.type_encoder(typ_in)
        typ_agg = _masked_mean_max(
            typ_emb.reshape(b * k, typ_emb.shape[2], typ_emb.shape[3]),
            typ_mask.reshape(b * k, typ_mask.shape[2]),
        ).reshape(b, k, -1)

        unit_in = torch.cat(
            [self.unit_norm(unit_cont, present), unit_bin, wpn_agg, typ_agg], dim=-1
        )
        return self.unit_encoder(unit_in) * (present > 0).to(unit_in.dtype).unsqueeze(-1)

    def forward(self, observations: Dict[str, torch.Tensor]) -> torch.Tensor:
        grid = observations["grid"]
        stem = self.cnn_stem(grid)
        cnn_out = self.cnn_head(self.cnn(stem))

        pos = self.pos_channels.expand(grid.shape[0], -1, -1, -1)
        move_map = torch.cat([self.map_net(torch.cat([stem, pos], dim=1)), pos], dim=1)

        ally_emb = self._encode_units(observations, "allies")
        enemy_emb = self._encode_units(observations, "enemies")
        ally_present = observations["allies_bin"][..., _UNIT_PRESENT_IDX]
        enemy_present = observations["enemies_bin"][..., _UNIT_PRESENT_IDX]

        # Ligne 0 = l'unité ACTIVE (contrat de l'observation) : son embedding entre SEUL dans le
        # tronc, il ne doit pas être noyé dans l'agrégation de mes autres escouades.
        e_own = ally_emb[:, 0]
        allies_agg = _masked_mean_max(ally_emb[:, 1:], ally_present[:, 1:])
        # Les ennemis ne sont agrégés qu'en CONTEXTE : leurs embeddings par slot sont conservés
        # tels quels (invariant D1 / tête pointeur T-E).
        enemies_agg = _masked_mean_max(enemy_emb, enemy_present)

        sm_cont = observations["self_models_cont"]
        sm_bin = observations["self_models_bin"]
        # Masque LU sur le bit dédié, comme pour les armes et les types. Il est déduit de rien :
        # une figurine sur le centroïde arrondi et sans drapeau a une ligne entièrement nulle et
        # serait comptée absente (V11 §0.32 T-H).
        sm_mask = sm_bin[..., _SELF_MODEL_PRESENT_IDX]
        sm_in = torch.cat([self.self_model_norm(sm_cont, sm_mask), sm_bin], dim=-1)
        sm_agg = _masked_mean_max(self.self_model_encoder(sm_in), sm_mask)

        # Candidats de décision : masque LU sur le bit `present` (dernier champ du registre),
        # jamais déduit de la ligne — un candidat sans effet observé aurait une ligne nulle.
        decision_options = observations["decision_options_bin"]
        decision_mask = decision_options[..., -1]
        decision_emb = self.decision_encoder(decision_options) * (
            decision_mask > 0
        ).to(decision_options.dtype).unsqueeze(-1)
        decision_agg = _masked_mean_max(decision_emb, decision_mask)

        trunk = torch.cat(
            [
                cnn_out,
                observations["global_cont"],
                observations["global_bin"],
                e_own,
                allies_agg,
                enemies_agg,
                sm_agg,
                observations["decision_ctx_bin"],
                decision_agg,
            ],
            dim=1,
        )
        return torch.cat(
            [
                trunk,
                enemy_emb.reshape(enemy_emb.shape[0], -1),
                move_map.reshape(move_map.shape[0], -1),
                decision_emb.reshape(decision_emb.shape[0], -1),
            ],
            dim=1,
        )
