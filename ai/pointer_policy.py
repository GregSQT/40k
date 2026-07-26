#!/usr/bin/env python3
"""ai/pointer_policy.py — TÊTE POINTEUR pour le ciblage de tir (V11 §0.30, tranche T-E).

Les logits « tirer sur le slot i » ne sont plus produits par une ligne dédiée d'une couche
dense, mais par un **produit scalaire** entre une requête issue du tronc et l'embedding de
l'ennemi du slot i :

    logit_i = (q · e_i) / sqrt(d)        q = W_q · latent_pi,  e_i = embedding du slot i

Pourquoi (V11_entity_encoder_pointer.md §1.8, mesuré) : au format dense, chaque slot possède sa
propre ligne de poids et n'apprend RIEN des autres — ajouter un slot coûtait ~226 k paramètres
et un slot rarement occupé restait mal appris toute la partie. Avec le pointeur, le nombre de
slots est **gratuit en paramètres** et ce que le réseau apprend sur un slot vaut pour tous.
C'est ce qui a permis de passer les slots ennemis de 5 à 20 et de refermer §1.1 (une escouade
ennemie invisible et intirable dans la majorité des épisodes).

⚠️ **ZONE À RISQUE, identifiée avant écriture** : une tête d'action custom sous `MaskablePPO`
échoue EN SILENCE si `log_prob`, l'entropie ou le masquage sont faux — l'entraînement tourne et
apprend mal. La conception ci-dessous minimise cette surface : on ne touche QUE la valeur des
logits ; la distribution, le masquage, `log_prob` et l'entropie restent ceux de SB3
(`MaskableCategorical`). `tests/unit/ai/test_pointer_head.py` le vérifie contre une tête dense
de référence sur un cas jouet.
"""

from typing import Any, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from sb3_contrib.common.maskable.distributions import MaskableDistribution
from sb3_contrib.common.maskable.policies import MaskableMultiInputActorCriticPolicy
from stable_baselines3.common.torch_layers import MlpExtractor
from stable_baselines3.common.type_aliases import PyTorchObs

from ai.spatial_extractor import SpatialCombinedExtractor
from engine.macro_intents import SHOOT_SLOT_BASE, SHOOT_SLOT_COUNT


class PointerMaskablePolicy(MaskableMultiInputActorCriticPolicy):
    """Policy MaskablePPO dont les logits de tir viennent d'un produit scalaire sur les embeddings.

    L'extracteur (`SpatialCombinedExtractor`) sort `[tronc | embeddings ennemis par slot]`. Cette
    policy :
    - n'alimente le tronc MLP qu'avec la partie `tronc` (les embeddings n'y entrent pas : ils
      seraient de nouveau aplatis, exactement ce que le chantier supprime) ;
    - produit les logits de tir par `q · e_i` ;
    - laisse TOUT le reste à SB3 (distribution masquée, log_prob, entropie, value net).
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        if not self.share_features_extractor:
            raise ValueError(
                "PointerMaskablePolicy exige share_features_extractor=True : la tete pointeur "
                "lit les embeddings ennemis produits par l'extracteur de features."
            )

    # -- construction ------------------------------------------------------
    def _build_mlp_extractor(self) -> None:
        """Tronc MLP alimenté par la SEULE partie tronc des features, + la matrice de requête.

        `query_net` est créé ici (et non dans `_build`) parce que `_build_mlp_extractor` est
        appelé AVANT la construction de l'optimiseur : ses paramètres sont donc bien optimisés.
        """
        extractor = self.features_extractor
        if not isinstance(extractor, SpatialCombinedExtractor):
            raise TypeError(
                "PointerMaskablePolicy exige SpatialCombinedExtractor comme extracteur "
                f"(recu {type(extractor).__name__}) : la tete pointeur a besoin des embeddings "
                "ennemis par slot."
            )
        if extractor.n_enemy_slots != SHOOT_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_enemy_slots} slots ennemis "
                f"observes contre {SHOOT_SLOT_COUNT} actions de tir. C'est l'invariant D1."
            )
        self.trunk_dim = extractor.trunk_dim
        self.entity_dim = extractor.entity_dim
        self.n_enemy_slots = extractor.n_enemy_slots
        self.mlp_extractor = MlpExtractor(
            self.trunk_dim,
            net_arch=self.net_arch,
            activation_fn=self.activation_fn,
            device=self.device,
        )
        self.query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)

    # -- découpe du vecteur de features ------------------------------------
    def _split_features(self, obs: PyTorchObs) -> Tuple[torch.Tensor, torch.Tensor]:
        """(tronc, embeddings ennemis (B, K, d)) — contrat de `SpatialCombinedExtractor`."""
        features = self.extract_features(obs)
        if not isinstance(features, torch.Tensor):
            raise TypeError(
                "PointerMaskablePolicy attend un extracteur PARTAGE (un seul tenseur de "
                "features) : deux extracteurs pi/vf produiraient deux jeux d'embeddings."
            )
        trunk = features[:, : self.trunk_dim]
        embeddings = features[:, self.trunk_dim :].reshape(
            features.shape[0], self.n_enemy_slots, self.entity_dim
        )
        return trunk, embeddings

    def _action_logits(self, latent_pi: torch.Tensor, embeddings: torch.Tensor) -> torch.Tensor:
        """Logits complets, dont le segment de tir est produit par `q · e_i`.

        Le reste des logits sort de `self.action_net` inchangé. Les colonnes de `action_net`
        correspondant aux slots de tir ne sont jamais lues — elles ne reçoivent donc aucun
        gradient et restent à leur initialisation. C'est assumé : conserver `action_net` entier
        laisse intacts l'initialisation orthogonale, la sauvegarde/reprise et le reste de la
        machinerie SB3, pour un coût de quelques milliers de paramètres inertes.
        """
        base = self.action_net(latent_pi)
        query = self.query_net(latent_pi).unsqueeze(1)                 # (B, 1, d)
        # Mise à l'échelle 1/sqrt(d), comme une attention : sans elle, la variance des logits
        # croît avec la dimension d'embedding et la politique démarre quasi déterministe.
        pointer = (query * embeddings).sum(dim=-1) / (self.entity_dim ** 0.5)  # (B, K)
        end = SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT
        return torch.cat([base[:, :SHOOT_SLOT_BASE], pointer, base[:, end:]], dim=1)

    def _distribution_from(
        self,
        latent_pi: torch.Tensor,
        embeddings: torch.Tensor,
        action_masks: Optional[np.ndarray],
    ) -> MaskableDistribution:
        distribution = self.action_dist.proba_distribution(
            action_logits=self._action_logits(latent_pi, embeddings)
        )
        if action_masks is not None:
            distribution.apply_masking(action_masks)
        return distribution

    # -- API policy --------------------------------------------------------
    def forward(
        self,
        obs: PyTorchObs,
        deterministic: bool = False,
        action_masks: Optional[np.ndarray] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        trunk, embeddings = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(trunk)
        values = self.value_net(latent_vf)
        distribution = self._distribution_from(latent_pi, embeddings, action_masks)
        actions = distribution.get_actions(deterministic=deterministic)
        log_prob = distribution.log_prob(actions)
        return actions, values, log_prob

    def get_distribution(
        self, obs: PyTorchObs, action_masks: Optional[np.ndarray] = None
    ) -> MaskableDistribution:
        trunk, embeddings = self._split_features(obs)
        latent_pi = self.mlp_extractor.forward_actor(trunk)
        return self._distribution_from(latent_pi, embeddings, action_masks)

    def predict_values(self, obs: PyTorchObs) -> torch.Tensor:
        trunk, _embeddings = self._split_features(obs)
        return self.value_net(self.mlp_extractor.forward_critic(trunk))

    def evaluate_actions(
        self,
        obs: PyTorchObs,
        actions: torch.Tensor,
        action_masks: Optional[Any] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]:
        """⚠️ Ordre de retour SB3 : (values, log_prob, entropy) — l'inverser sabote la mise à
        jour PPO en silence (le ratio et l'avantage seraient calculés sur les mauvaises
        quantités). Verrouillé par `test_pointer_head.py`."""
        trunk, embeddings = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(trunk)
        distribution = self._distribution_from(latent_pi, embeddings, action_masks)
        return self.value_net(latent_vf), distribution.log_prob(actions), distribution.entropy()
