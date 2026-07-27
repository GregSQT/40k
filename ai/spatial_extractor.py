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

from engine.observation_entities import self_model_bin_index
from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE

#: Familles d'unités partageant le MÊME schéma et le MÊME encodeur.
_UNIT_FAMILIES = ("allies", "enemies")

#: Index du masque de présence des figurines — LU depuis le schéma, jamais recopié.
_SELF_MODEL_PRESENT_IDX = self_model_bin_index("present")


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

    Sortie (dans cet ordre — contrat consommé par la tête pointeur de T-E) :

        [ trunk_features (self.trunk_dim) | embeddings ennemis PAR SLOT (K_e × entity_dim) ]

    `cnn_features` : dimension de la sortie CNN. OBLIGATOIRE, sans défaut — la valeur vient de
    la config JSON de l'agent (`model_params.policy_kwargs.features_extractor_kwargs`).
    `entity_dim` / `weapon_dim` / `type_dim` / `model_dim` : largeurs des encodeurs partagés.
    """

    def __init__(
        self,
        observation_space: gym.spaces.Dict,
        cnn_features: int,
        entity_dim: int = 64,
        weapon_dim: int = 32,
        type_dim: int = 16,
        model_dim: int = 16,
    ):
        if not isinstance(cnn_features, int) or cnn_features <= 0:
            raise ValueError(
                f"SpatialCombinedExtractor : cnn_features doit etre un entier > 0, recu {cnn_features!r}"
            )
        if not isinstance(observation_space, gym.spaces.Dict):
            raise TypeError(
                f"SpatialCombinedExtractor attend un espace Dict, recu {type(observation_space)}"
            )
        expected_keys = ["global_cont", "global_bin", "self_models_cont", "self_models_bin", "grid"]
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
        )
        super().__init__(
            observation_space,
            features_dim=trunk_dim + self.n_enemy_slots * entity_dim,
        )
        self.trunk_dim = trunk_dim
        self.entity_dim = entity_dim

        self.cnn = nn.Sequential(
            nn.Conv2d(GRID_CHANNELS, 32, kernel_size=3, stride=1, padding=1),
            nn.ReLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        with torch.no_grad():
            n_flatten = self.cnn(torch.zeros(1, GRID_CHANNELS, GRID_SIZE, GRID_SIZE)).shape[1]
        self.cnn_head = nn.Sequential(nn.Linear(n_flatten, cnn_features), nn.ReLU())

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

    # -- contrat de découpe consommé par la tête pointeur (T-E) ------------------
    def enemy_embeddings_slice(self) -> slice:
        """Tranche des embeddings ennemis PAR SLOT dans le vecteur de features."""
        return slice(self.trunk_dim, self.trunk_dim + self.n_enemy_slots * self.entity_dim)

    def _encode_units(self, obs: Dict[str, torch.Tensor], family: str) -> torch.Tensor:
        """Embeddings (B, K, entity_dim) d'une famille d'unités, encodeurs PARTAGÉS."""
        unit_cont = obs[f"{family}_cont"]
        unit_bin = obs[f"{family}_bin"]
        present = unit_bin[..., 0]  # UNIT_BIN_FIELDS[0] == "present"
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
        cnn_out = self.cnn_head(self.cnn(observations["grid"]))

        ally_emb = self._encode_units(observations, "allies")
        enemy_emb = self._encode_units(observations, "enemies")
        ally_present = observations["allies_bin"][..., 0]
        enemy_present = observations["enemies_bin"][..., 0]

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

        trunk = torch.cat(
            [
                cnn_out,
                observations["global_cont"],
                observations["global_bin"],
                e_own,
                allies_agg,
                enemies_agg,
                sm_agg,
            ],
            dim=1,
        )
        return torch.cat([trunk, enemy_emb.reshape(enemy_emb.shape[0], -1)], dim=1)
