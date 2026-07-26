#!/usr/bin/env python3
"""ai/spatial_extractor.py - Extracteur de features pour l'obs Dict {"vec_cont", "vec_bin", "grid"}.

Refonte spatiale du move (Documentation/Implementation/A_faire/move_action_space_spatial_rework.md,
T1b/T5) + refonte de l'observation V11 (V11_audit_observation.md §9.5). L'obs de l'agent est un
`Dict` :
  - "vec_cont" : grandeurs CONTINUES brutes (normalisees par VecNormalize)
  - "vec_bin"  : valeurs DISCRETES (drapeaux, phase, controle d'objectif) JAMAIS normalisees
  - "grid"     : grille egocentrique (GRID_CHANNELS, GRID_SIZE, GRID_SIZE) = perception du terrain

Les deux vecteurs sont concatenes tels quels apres le CNN : le split n'existe que pour la
normalisation (VecNormalize agit par cle), pas pour le reseau.

`CombinedExtractor` (le defaut de `MultiInputPolicy`) applique `NatureCNN` uniquement aux sous-espaces
reconnus comme images (`is_image_space` : 3D + canaux dans {1,3}). La grille a GRID_CHANNELS canaux (>3) :
elle serait donc APLATIE (GRID_CHANNELS x 1024 floats), ce qui detruit le biais inductif spatial vise par la refonte
(spec §6.2). D'ou cet extracteur : CNN sur la grille, passthrough du vecteur, concatenation.

Aucun repli, aucune valeur par defaut masquant une erreur : la forme de la grille vient des
constantes de `engine.spatial_grid` (source unique), et la presence des cles est verifiee.
"""

from typing import Dict

import gymnasium as gym
import torch
import torch.nn as nn
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE


class SpatialCombinedExtractor(BaseFeaturesExtractor):
    """CNN sur "grid" + passthrough de "vec_cont"/"vec_bin", concatenes en un vecteur de features.

    `cnn_features` : dimension de la sortie CNN avant concatenation avec les vecteurs.
    OBLIGATOIRE, sans defaut : la valeur vient de la config JSON de l'agent
    (`model_params.policy_kwargs.features_extractor_kwargs.cnn_features`), transmise par sb3.
    `features_dim` (attribut sb3) = cnn_features + dim("vec_cont") + dim("vec_bin").
    """

    def __init__(self, observation_space: gym.spaces.Dict, cnn_features: int):
        if not isinstance(cnn_features, int) or cnn_features <= 0:
            raise ValueError(
                f"SpatialCombinedExtractor : cnn_features doit etre un entier > 0, recu {cnn_features!r}"
            )
        if not isinstance(observation_space, gym.spaces.Dict):
            raise TypeError(
                f"SpatialCombinedExtractor attend un espace Dict, recu {type(observation_space)}"
            )
        for key in ("vec_cont", "vec_bin", "grid"):
            if key not in observation_space.spaces:
                raise KeyError(
                    f"SpatialCombinedExtractor : cle '{key}' absente de l'espace d'observation "
                    f"({list(observation_space.spaces.keys())})"
                )

        grid_space = observation_space.spaces["grid"]
        if grid_space.shape != (GRID_CHANNELS, GRID_SIZE, GRID_SIZE):
            raise ValueError(
                f"SpatialCombinedExtractor : forme de grille inattendue {grid_space.shape}, "
                f"attendu {(GRID_CHANNELS, GRID_SIZE, GRID_SIZE)}"
            )
        vec_dim = 0
        for key in ("vec_cont", "vec_bin"):
            vec_shape = observation_space.spaces[key].shape
            if vec_shape is None or len(vec_shape) != 1:
                raise ValueError(
                    f"SpatialCombinedExtractor : '{key}' doit etre 1D, recu shape {vec_shape}"
                )
            vec_dim += int(vec_shape[0])

        super().__init__(observation_space, features_dim=cnn_features + vec_dim)

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
        self._vec_dim = vec_dim

    def forward(self, observations: Dict[str, torch.Tensor]) -> torch.Tensor:
        grid = observations["grid"]
        cnn_out = self.cnn_head(self.cnn(grid))
        return torch.cat([cnn_out, observations["vec_cont"], observations["vec_bin"]], dim=1)
