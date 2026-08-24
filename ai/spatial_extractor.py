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

from engine.observation_entities import (
    OBS_ID_PADDING,
    OBS_ID_VOCAB_SIZE,
    global_bin_index,
    self_model_bin_index,
    unit_bin_index,
)
from engine.spatial_grid import GRID_CELL_COUNT, GRID_CHANNELS, GRID_SIZE

#: Familles d'unités partageant le MÊME schéma et le MÊME encodeur.
_UNIT_FAMILIES = ("allies", "enemies")

#: Suffixes du schéma d'unité. Écrits UNE fois : ils servent à la fois à exiger les clés dans
#: l'espace d'observation et à vérifier que les deux camps ont bien les mêmes dimensions. Les
#: recopier laisserait une clé exigée mais jamais comparée — donc un schéma divergent qui passe.
_UNIT_SUFFIXES = (
    "cont", "bin", "ability_ids", "status_ids",
    "wpn_cont", "wpn_bin", "wpn_rule_ids", "types_cont", "types_bin",
)

#: Largeur des embeddings de capacité et de statut (chantier 01). Deux tables de
#: `OBS_ID_VOCAB_SIZE x ABILITY_EMBED_DIM`, PRÉ-DIMENSIONNÉES : c'est ce pré-dimensionnement qui
#: rend l'ajout d'une capacité, d'un statut ou d'une faction entière gratuit — ni `obs_size`, ni
#: le nombre de paramètres du réseau ne bougent, donc aucun retrain.
ABILITY_EMBED_DIM = 16

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

    # Déclarations de type des buffers : `register_buffer` passe par `__getattr__`, dont le
    # type de retour est `Tensor | Module`. Sans ces annotations, toute lecture de statistique
    # est vue comme potentiellement un sous-module.
    running_mean: torch.Tensor
    running_var: torch.Tensor
    count: torch.Tensor

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
        """Mise à jour parallèle (Chan et al.) sur les seules entités valides.

        Le lot VIDE n'est pas court-circuité par un `if` : lire `weights.sum()` côté hôte
        forcerait une synchronisation device->hôte à CHAQUE appel (8 par forward, à chaque
        minibatch de `train()`), pour un cas qui se neutralise tout seul. Avec le dénominateur
        borné, `batch_count = 0` donne `batch_mean = 0`, `batch_var = 0` et un poids de mélange
        `batch_count / tot` nul : moyenne, variance et compte ressortent inchangés à l'identique.
        """
        batch_count = weights.sum()
        w = weights.unsqueeze(-1)
        batch_mean = (flat * w).sum(dim=0) / batch_count.clamp(min=1.0)
        batch_var = (((flat - batch_mean) ** 2) * w).sum(dim=0) / batch_count.clamp(min=1.0)
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
        keep = mask > 0
        # `flat`/`weights` ne servent QU'À l'estimation : les construire hors du `if` allouerait
        # deux tenseurs par appel sur le chemin d'inférence, où les statistiques sont figées
        # (les rollouts SB3 tournent en `training_mode=False`).
        if self.training:
            self._update(
                x.reshape(-1, x.shape[-1]).detach(), keep.reshape(-1).to(x.dtype).detach()
            )
        normed = (x - self.running_mean) / torch.sqrt(self.running_var + self.epsilon)
        normed = torch.clamp(normed, -self.clip, self.clip)
        # Une entité absente ne doit PAS acquérir une valeur non nulle par recentrage : son
        # embedding serait alors indistinguable d'une entité réelle avant même le masquage.
        return normed * keep.to(normed.dtype).unsqueeze(-1)


def _mlp(sizes: Sequence[int]) -> nn.Sequential:
    layers: List[nn.Module] = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        layers.append(nn.ReLU())
    return nn.Sequential(*layers)


def _id_bag() -> nn.EmbeddingBag:
    """UNE table d'ids d'observation. Les hyperparamètres — et l'invariant de `padding_idx`
    documenté au site d'appel — sont écrits ICI une fois, pas recopiés par vocabulaire."""
    return nn.EmbeddingBag(
        OBS_ID_VOCAB_SIZE, ABILITY_EMBED_DIM, mode="sum", padding_idx=OBS_ID_PADDING
    )


def _pool_ids(table: nn.EmbeddingBag, ids: torch.Tensor) -> torch.Tensor:
    """Poole un ENSEMBLE d'ids par entrée : (…, slots) → (…, ABILITY_EMBED_DIM).

    Agnostique au rang : le « sac » est la DERNIÈRE dimension, tout ce qui précède est un lot
    (une entité pour les capacités, un profil d'arme pour les règles). Les ids transitent en
    float32 (l'observation est homogène) et sont reconvertis ici — `EmbeddingBag` exige des
    entiers, et `int32` suffit au vocabulaire tout en évitant le doublement de mémoire d'`int64`
    (mesuré : ~15 % du coût du lookup sur GPU, ~30 % sur CPU).
    """
    *lead, slots = ids.shape
    return table(ids.reshape(-1, slots).int()).reshape(*lead, ABILITY_EMBED_DIM)


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
    keep = mask > 0
    present = keep.to(emb.dtype)
    count = present.sum(dim=1, keepdim=True).clamp(min=1.0)
    mean = (emb * present.unsqueeze(-1)).sum(dim=1) / count
    # `masked_fill` et non `torch.where(..., full_like(...))` : ce dernier matérialise un tenseur
    # de `-inf` de la TAILLE de `emb` (jusqu'à ~10 Mo sur la branche armes) juste pour le lire.
    maxed = emb.masked_fill(~keep.unsqueeze(-1), torch.finfo(emb.dtype).min).max(dim=1).values
    return torch.cat([mean, maxed.masked_fill(~keep.any(dim=1, keepdim=True), 0.0)], dim=1)


def _encode_masked(
    encoder: nn.Module, mask: torch.Tensor, *parts: torch.Tensor
) -> torch.Tensor:
    """Encode `cat(parts)` puis ANNULE les entités absentes : (B, K, …) -> (B, K, D).

    La remise à zéro est la moitié qu'on oublie en recopiant ce motif. Sans elle un slot vide
    sort le BIAIS de l'encodeur — un vecteur constant non nul, donc indistinguable d'une entité
    réelle pour les têtes pointeur qui lisent ces embeddings slot par slot.
    """
    return encoder(torch.cat(parts, dim=-1)) * (mask > 0).to(mask.dtype).unsqueeze(-1)


def _aggregate_subentities(
    encoder: nn.Module, sub_in: torch.Tensor, mask: torch.Tensor
) -> torch.Tensor:
    """Encode puis AGRÈGE un rang de sous-entités par unité : (B, K, S, F) -> (B, K, 2·D).

    `_masked_mean_max` raisonne sur (lot, ensemble, D) : les deux premières dimensions sont
    aplaties le temps de l'agrégation, puis restaurées. Écrit une fois — cette gymnastique de
    `reshape` est exactement ce qui se recopie de travers d'un rang de sous-entités à l'autre,
    et un axe échangé y donnerait des formes valides pour des agrégations fausses.
    """
    emb = encoder(sub_in)
    b, k = emb.shape[0], emb.shape[1]
    return _masked_mean_max(
        emb.reshape(b * k, emb.shape[2], emb.shape[3]),
        mask.reshape(b * k, mask.shape[2]),
    ).reshape(b, k, -1)


class SpatialCombinedExtractor(BaseFeaturesExtractor):
    """CNN sur "grid" + encodeurs d'entités PARTAGÉS + agrégation masquée.

    Sortie (dans cet ordre — contrat consommé par les têtes de `ai/pointer_policy.py`) :

        [ trunk_features (self.trunk_dim)
        | embeddings ennemis PAR SLOT (K_e × entity_dim)          -> tête pointeur de TIR (T-E)
        | carte de move NON aplatie (move_map_channels × 32 × 32) -> tête 1x1 de MOVE (T-G)
        | embeddings de CANDIDATS de décision (K_d × entity_dim)  -> tête pointeur CHOICE (§9.3)
        | embeddings de SLOTS de déploiement (K_p × entity_dim)   -> tête pointeur DEPLOY (§0.44) ]

    `cnn_features` : dimension de la sortie CNN. OBLIGATOIRE, sans défaut — la valeur vient de
    la config JSON de l'agent (`model_params.policy_kwargs.features_extractor_kwargs`).
    `entity_dim` / `weapon_dim` / `type_dim` / `map_channels` : largeurs des encodeurs partagés
    et de la branche carte.
    """

    # Cf. `EntityRunningNorm` : un buffer se déclare aussi côté types, sinon il est vu comme
    # `Tensor | Module`.
    pos_channels: torch.Tensor

    def __init__(
        self,
        observation_space: gym.spaces.Dict,
        cnn_features: int,
        entity_dim: int = 64,
        weapon_dim: int = 32,
        type_dim: int = 16,
        map_channels: int = 16,
        cnn_stem_channels: int = 32,
        cnn_inner_channels: int = 64,
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
            "deploy_cand_cont", "deploy_cand_bin",
        ]
        for family in _UNIT_FAMILIES:
            expected_keys += [f"{family}_{suffix}" for suffix in _UNIT_SUFFIXES]
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
        for suffix in _UNIT_SUFFIXES:
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
        self.n_deploy_slots, self.deploy_cand_cont_dim = _shape("deploy_cand_cont")
        self.deploy_cand_bin_dim = _shape("deploy_cand_bin")[1]

        weapon_agg = 2 * weapon_dim
        type_agg = 2 * type_dim
        trunk_dim = (
            cnn_features
            + global_dim
            + entity_dim              # e_own (unité active)
            + 2 * entity_dim          # agrégation de mes autres escouades
            + 2 * entity_dim          # agrégation des ennemies (contexte)
            + 2 * entity_dim          # sm_agg : mean+max des figurines de l'unité active
            # Contexte de décision : quel type de choix est demandé, et un résumé de ce que les
            # candidats offrent. Le tronc en a besoin pour la VALEUR de l'état et pour scorer
            # les candidats en connaissance du reste de la partie (leurs embeddings par slot, eux,
            # partent directement à la tête pointeur — cf. `decision_embeddings_slice`).
            + self.decision_ctx_dim
            + 2 * entity_dim
            # Candidats de déploiement (§0.40 point 3) : AGRÉGÉS, exactement comme les ennemis et
            # les candidats de décision — le tronc n'en a plus besoin que comme CONTEXTE (« mes
            # poses possibles sont-elles toutes exposées ? », pour la valeur de l'état). Ils y
            # étaient aplatis par slot tant que les logits 4-11 sortaient d'une tête indexée par
            # la cellule ; depuis §0.44 (L1) ils sortent de `deploy_query_net`, qui lit les
            # embeddings PAR SLOT en queue du vecteur (`deploy_embeddings_slice`). Garder
            # l'identité du slot ici la ferait ré-apprendre par des poids denses, ce que la tête
            # pointeur supprime précisément.
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
                + self.n_deploy_slots * entity_dim
                # Escouades ALLIÉES par slot (V11 §0.48 `L2`) : lues par `activate_query_net`.
                + self.n_ally_slots * entity_dim
                # Figurines DE L'UNITÉ ACTIVE par slot (P3-0) : lues par `coherency_query_net`.
                + self.n_self_models * entity_dim
            ),
        )
        self.trunk_dim = trunk_dim
        # Index ABSOLU du bit `phase_deployment` dans le vecteur de features (§0.44 / L1). Il
        # tombe dans la partie tronc, où `global_bin` est recopié TEL QUEL : la clé est hors
        # `norm_obs_keys` (ai/train._vec_norm_obs_keys), donc le bit y vaut exactement 0.0 ou 1.0.
        # C'est LUI qui dit à la policy si les ids 4-11 sont des slots de déploiement ou des
        # cellules de move — les deux familles partagent ces ids et seule la phase les sépare.
        # Calculé ici, à côté de la composition du tronc, et JAMAIS recopié dans la policy : un
        # décalage d'un champ y ferait router sur `is_my_turn` sans que rien ne lève.
        self._deploy_phase_index = (
            cnn_features + _shape("global_cont")[0] + global_bin_index("phase_deployment")
        )
        self.entity_dim = entity_dim
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
            nn.Conv2d(GRID_CHANNELS, cnn_stem_channels, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
        )
        # Branche TRONC : sous-échantillonnée puis aplatie — c'est un résumé GLOBAL de la fenêtre,
        # pas une carte. Elle reste strictement ce qu'elle était.
        self.cnn = nn.Sequential(
            nn.Conv2d(cnn_stem_channels, cnn_inner_channels, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(cnn_inner_channels, cnn_inner_channels, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        with torch.no_grad():
            n_flatten = self.cnn(torch.zeros(1, cnn_stem_channels, GRID_SIZE, GRID_SIZE)).shape[1]
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
                cnn_stem_channels + POSITIONAL_CHANNELS, map_channels, kernel_size=3, stride=1, padding=1
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
            [
                # + ABILITY_EMBED_DIM : les règles du profil, poolées depuis leurs ids
                self.weapon_cont_dim + self.weapon_bin_dim + ABILITY_EMBED_DIM,
                weapon_dim,
                weapon_dim,
            ]
        )
        self.type_encoder = _mlp([self.type_cont_dim + self.type_bin_dim, type_dim])
        self.self_model_encoder = _mlp(
            [self.self_model_cont_dim + self.self_model_bin_dim, entity_dim]
        )
        # --- Capacités et statuts : DEUX `EmbeddingBag` distinctes (chantier 01) --------------
        # `mode="sum"` : invariant par permutation — {A, B} écrit (slot0, slot1) ou (slot1, slot0)
        # donne le même vecteur — et il préserve la MULTIPLICITÉ, là où la moyenne confondrait un
        # ensemble de 1 élément et un de 3.
        #
        # `padding_idx=0` : un slot vide est IGNORÉ par le pooling. Sans lui, « pas de capacité »
        # deviendrait une capacité apprise, répétée autant de fois qu'il reste de slots libres.
        #
        # DEUX tables et pas une : une capacité (« cette unité a Feel No Pain ») et un statut
        # (« cette unité est la cible Oath adverse ») ne sont pas de même nature ; un pooling
        # commun les additionnerait dans le même espace et le réseau ne pourrait plus les
        # distinguer.
        #
        # Le vocabulaire est PRÉ-DIMENSIONNÉ (`OBS_ID_VOCAB_SIZE`) et non ajusté au nombre de
        # capacités existantes : c'est exactement ce qui rend l'ajout d'une capacité gratuit en
        # paramètres. Les lignes inutilisées ne reçoivent aucun gradient.
        #
        # ⚠️ `EmbeddingBag` et NON `nn.Embedding(...).sum(dim=-2)`, alors que la seconde forme est
        # MESURÉE 3x plus rapide sur CPU (11 200 µs contre 3 800 µs à B=1024 × 28 entités ;
        # 193 contre 33 µs à B=1 — `padding_idx` désactive le kernel vectorisé du « sac »). Le
        # gain a été écarté parce que les deux formes ne portent PAS le même invariant :
        # `EmbeddingBag` IGNORE les entrées `padding_idx` au moment de la lecture, donc un slot
        # vide contribue zéro quoi qu'il arrive à la ligne 0 ; `Embedding` + somme, lui, ne
        # contribue zéro que TANT QUE la ligne 0 vaut zéro — `padding_idx` s'y contente de
        # l'initialiser ainsi et de couper son gradient. Toute écriture sur cette ligne (weight
        # decay, chargement partiel, ajustement manuel) ferait alors du padding une capacité
        # fantôme ajoutée à chaque slot libre, silencieusement. Vérifié par test : la
        # perturbation qui laisse `EmbeddingBag` correcte casse la variante `Embedding`.
        self.ability_embedding = _id_bag()
        self.status_embedding = _id_bag()
        # TROISIEME table, meme patron : les REGLES D'ARME d'un profil. Distincte des deux autres
        # pour la meme raison qu'elles le sont entre elles — [DEVASTATING WOUNDS] (une regle
        # d'arme) et « Feel No Pain » (une capacite d'unite) ne vivent pas dans le meme espace, et
        # un pooling commun les additionnerait.
        #
        # ⚠️ COUT RESEAU, et non seulement cout d'observation : ce sac-la est poole PAR PROFIL,
        # donc sur K_WEAPONS fois plus de lignes que les capacites, qui le sont par entite.
        # MESURE (B=512, 4 threads CPU, allies + ennemis) : 217 ms par forward pour les regles
        # d'arme contre 37 ms pour capacites + statuts reunis. C'est paye a chaque passe PPO, et
        # le docstring du cache de profils (`observation_builder._encode_entity_weapons`) ne
        # couvre QUE le cote observation (froid, derriere le cache) — il ne dit rien de celui-ci.
        # La variante `nn.Embedding(...).sum(dim=-2)` est mesuree a 102 ms (2,1x) sur le meme
        # banc ; elle est ecartee ICI pour EXACTEMENT la raison ecrite ci-dessus pour les
        # capacites — elle ne porte pas l'invariant de `padding_idx` —, la penalite etant
        # simplement multipliee par les 20 slots d'arme.
        self.weapon_rule_embedding = _id_bag()
        self.unit_encoder = _mlp(
            [
                self.unit_cont_dim
                + self.unit_bin_dim
                + 2 * ABILITY_EMBED_DIM  # capacités + statuts, concaténés à l'entité
                + weapon_agg
                + type_agg,
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
        # Encodeur de CANDIDAT DE DÉPLOIEMENT (§0.40 point 3) : un seul module pour les 5 slots.
        # Ses features continues sont des distances et des comptages BRUTS (subhex, nombre
        # d'ennemis) : elles passent par une `EntityRunningNorm` à statistiques COMMUNES aux
        # slots, comme les unités — sans quoi le même « exposé à 3 ennemis » n'aurait pas la même
        # échelle selon le slot, et le partage de poids ne voudrait plus rien dire.
        self.deploy_cand_norm = EntityRunningNorm(self.deploy_cand_cont_dim)
        self.deploy_cand_encoder = _mlp(
            [self.deploy_cand_cont_dim + self.deploy_cand_bin_dim, entity_dim, entity_dim]
        )

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

    def deploy_embeddings_slice(self) -> slice:
        """Tranche des embeddings de CANDIDATS DE DÉPLOIEMENT, PAR SLOT (§0.44, élément L1).

        Placée en DERNIER, derrière les candidats de décision, pour la même raison qu'eux : les
        tranches déjà consommées par les têtes de tir, de move et de décision gardent leurs
        bornes. C'est la tranche que lit `deploy_query_net`.
        """
        start = self.decision_embeddings_slice().stop
        return slice(start, start + self.n_deploy_slots * self.entity_dim)

    def ally_embeddings_slice(self) -> slice:
        """Tranche des embeddings d'escouades ALLIÉES, PAR SLOT (V11 §0.48, élément `L2`).

        Placée en DERNIER, derrière les candidats de déploiement, pour la même raison qu'eux : les
        tranches déjà consommées gardent leurs bornes, un ajout en tête les décalerait toutes en
        silence. C'est la tranche que lit `activate_query_net`.

        Elle contient les `K_ALLY_SLOTS` lignes, **ligne 0 comprise** — contrairement au tronc, qui
        sépare `e_own` de l'agrégation des autres. Le slot d'activation 0 désigne l'ancre du pool,
        c'est un candidat comme les autres et c'est même le seul toujours ouvert : l'exclure ferait
        pointer l'action `ACTIVATE_SLOT_i` sur la ligne `i+1`, décalage invisible (invariant D1).
        """
        start = self.deploy_embeddings_slice().stop
        return slice(start, start + self.n_ally_slots * self.entity_dim)

    def self_model_embeddings_slice(self) -> slice:
        """Tranche des embeddings de figurines DE L'UNITE ACTIVE, PAR SLOT (P3-0).

        Placée en DERNIER, derrière les escouades alliées, pour la même raison qu'elles : les
        tranches existantes gardent leurs bornes. C'est la tranche que lit `coherency_query_net`.
        Slot i = ligne i de `_squad_models_for_observation(alive_mids)` — invariant D1.
        """
        start = self.ally_embeddings_slice().stop
        return slice(start, start + self.n_self_models * self.entity_dim)

    def deployment_phase_flag_index(self) -> int:
        """Index du bit `phase_deployment` dans le vecteur de features (§0.44, élément L1).

        La policy le lit pour router les ids 4-11 vers la tête de déploiement plutôt que vers la
        conv 1x1 des cellules de move. Contrat, comme les tranches : il est CALCULÉ à partir de
        la composition réelle du tronc, jamais réécrit côté policy.
        """
        return self._deploy_phase_index

    def _encode_units(self, obs: Dict[str, torch.Tensor], family: str) -> torch.Tensor:
        """Embeddings (B, K, entity_dim) d'une famille d'unités, encodeurs PARTAGÉS."""
        unit_cont = obs[f"{family}_cont"]
        unit_bin = obs[f"{family}_bin"]
        present = unit_bin[..., _UNIT_PRESENT_IDX]  # lu du schéma (dernier champ, §0.37)

        wpn_bin = obs[f"{family}_wpn_bin"]
        wpn_mask = wpn_bin[..., -1]  # dernier drapeau de profil = slot occupé
        # Règles du profil : un « sac » d'ids PAR PROFIL, et non par entité comme les capacités.
        # Un slot vide vaut `padding_idx` et ne contribue rien ; un profil vide n'a que des slots
        # vides, donc un embedding nul — cohérent avec son mask.
        wpn_rule_emb = _pool_ids(self.weapon_rule_embedding, obs[f"{family}_wpn_rule_ids"])
        wpn_agg = _aggregate_subentities(
            self.weapon_encoder,
            torch.cat(
                [
                    self.weapon_norm(obs[f"{family}_wpn_cont"], wpn_mask),
                    wpn_bin,
                    wpn_rule_emb,
                ],
                dim=-1,
            ),
            wpn_mask,
        )

        typ_bin = obs[f"{family}_types_bin"]
        typ_mask = typ_bin[..., -1]  # MODEL_TYPE_BIN_FIELDS[-1] == "present"
        typ_agg = _aggregate_subentities(
            self.type_encoder,
            torch.cat(
                [self.type_norm(obs[f"{family}_types_cont"], typ_mask), typ_bin], dim=-1
            ),
            typ_mask,
        )

        # Capacités et statuts : lecture de ligne, jamais de one-hot matérialisé — un « sac »
        # par entité (cf. `_pool_ids`).
        ability_emb = _pool_ids(self.ability_embedding, obs[f"{family}_ability_ids"])
        status_emb = _pool_ids(self.status_embedding, obs[f"{family}_status_ids"])

        return _encode_masked(
            self.unit_encoder,
            present,
            self.unit_norm(unit_cont, present),
            unit_bin,
            ability_emb,
            status_emb,
            wpn_agg,
            typ_agg,
        )

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
        # sm_emb conservé par slot (P3-0 : `coherency_query_net`) ; sm_agg = contexte pour le tronc.
        sm_emb = _encode_masked(self.self_model_encoder, sm_mask, sm_in)
        sm_agg = _masked_mean_max(sm_emb, sm_mask)

        # Candidats de décision : masque LU sur le bit `present` (dernier champ du registre),
        # jamais déduit de la ligne — un candidat sans effet observé aurait une ligne nulle.
        decision_options = observations["decision_options_bin"]
        decision_mask = decision_options[..., -1]
        decision_emb = _encode_masked(self.decision_encoder, decision_mask, decision_options)
        decision_agg = _masked_mean_max(decision_emb, decision_mask)

        # Candidats de déploiement : masque LU sur le bit `present` (dernier champ), jamais
        # déduit de la ligne — un slot FERMÉ doit rester absent, pas devenir un candidat nul mais
        # plausible. Hors phase de déploiement le bloc entier est nul, `present` compris.
        deploy_cand_bin = observations["deploy_cand_bin"]
        deploy_mask = deploy_cand_bin[..., -1]
        deploy_emb = _encode_masked(
            self.deploy_cand_encoder,
            deploy_mask,
            self.deploy_cand_norm(observations["deploy_cand_cont"], deploy_mask),
            deploy_cand_bin,
        )
        # Le tronc n'en voit que l'AGRÉGATION (contexte) ; les embeddings PAR SLOT partent en
        # queue du vecteur, à la tête pointeur de déploiement — même partage que les ennemis.
        deploy_agg = _masked_mean_max(deploy_emb, deploy_mask)

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
                deploy_agg,
            ],
            dim=1,
        )
        return torch.cat(
            [
                trunk,
                enemy_emb.reshape(enemy_emb.shape[0], -1),
                move_map.reshape(move_map.shape[0], -1),
                decision_emb.reshape(decision_emb.shape[0], -1),
                deploy_emb.reshape(deploy_emb.shape[0], -1),
                # Escouades ALLIÉES par slot (V11 §0.48 `L2`) : `activate_query_net` les score
                # pour choisir QUI activer. Toutes les lignes, ligne 0 COMPRISE — c'est l'ancre du
                # pool, donc un candidat d'activation comme les autres (le slot 0 est même le seul
                # toujours ouvert). Le tronc, lui, garde `e_own` + `allies_agg` : l'agrégation y
                # reste le CONTEXTE, exactement comme pour les ennemis et les candidats de pose.
                ally_emb.reshape(ally_emb.shape[0], -1),
                # Figurines de l'unité active par slot (P3-0) : `coherency_query_net` les score
                # pour choisir quelle figurine retirer. Slot i = ligne i de l'obs.
                sm_emb.reshape(sm_emb.shape[0], -1),
            ],
            dim=1,
        )
