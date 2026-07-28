#!/usr/bin/env python3
"""ai/pointer_policy.py — TÊTES D'ACTION À POIDS PARTAGÉS : tir (§0.30 T-E) et move (§0.32 T-G).

**Tir.** Les logits « tirer sur le slot i » ne sont pas produits par une ligne dédiée d'une
couche dense, mais par un **produit scalaire** entre une requête issue du tronc et l'embedding
de l'ennemi du slot i :

    logit_i = (q · e_i) / sqrt(d)        q = W_q · latent_pi,  e_i = embedding du slot i

Pourquoi (V11_entity_encoder_pointer.md §1.8, mesuré) : au format dense, chaque slot possède sa
propre ligne de poids et n'apprend RIEN des autres — ajouter un slot coûtait ~226 k paramètres
et un slot rarement occupé restait mal appris toute la partie. Avec le pointeur, le nombre de
slots est **gratuit en paramètres** et ce que le réseau apprend sur un slot vaut pour tous.
C'est ce qui a permis de passer les slots ennemis de 5 à 20 et de refermer §1.1 (une escouade
ennemie invisible et intirable dans la majorité des épisodes).

**Move (V11 §0.32 T-G).** Le même défaut valait pour les **1024 logits de cellule**, soit 97 %
de l'espace d'action : ils sortaient du `Linear(320 -> TOTAL_ACTION_SIZE)` dense, une ligne par
cellule, aucun partage entre deux cellules voisines, et la carte CNN aplatie avant la tête. Ils
sortent désormais d'une **conv 1x1 sur la colonne de features de la cellule**, prise sur la
carte NON aplatie que `SpatialCombinedExtractor` conserve à résolution 32x32. Le nombre de
cellules redevient gratuit en paramètres et l'alignement `cellule (gx,gy) <-> logit gy*32+gx`
devient STRUCTUREL (un `reshape`) au lieu d'être ré-appris par des poids denses.

⚠️ Deux ajouts SANS LESQUELS le 1x1 serait plus faible que la tête dense (amendement §0.32 T-G) :

1. **Canaux positionnels fixes** (x, y, rayon), portés par la carte de l'extracteur : une conv
   est invariante par translation et ne peut pas exprimer « le centre n'est pas le bord », alors
   que la grille est égocentrique et normalisée par le budget d'Advance.
2. **Conditionnement par le latent du tronc**, diffusé sur les 32x32 : sans lui, un 1x1 sur une
   pile conv peu profonde ne voit ni le tour, ni les VP, ni les objectifs hors fenêtre, ni mes
   autres escouades — rien de ce qui justifie une destination.

⚠️ **ZONE À RISQUE, identifiée avant écriture** : une tête d'action custom sous `MaskablePPO`
échoue EN SILENCE si `log_prob`, l'entropie ou le masquage sont faux — l'entraînement tourne et
apprend mal. La conception ci-dessous minimise cette surface : on ne touche QUE la valeur des
logits ; la distribution, le masquage, `log_prob` et l'entropie restent ceux de SB3
(`MaskableCategorical`). `tests/unit/ai/test_pointer_head.py` le vérifie contre une tête dense
de référence sur un cas jouet, tir ET move.
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
from engine.macro_intents import (
    FIGHT_SLOT_BASE,
    FIGHT_SLOT_COUNT,
    MOVE_CELL_BASE,
    MOVE_CELL_COUNT,
    SHOOT_SLOT_BASE,
    SHOOT_SLOT_COUNT,
)
from engine.spatial_grid import GRID_CELL_COUNT, GRID_SIZE

#: Largeur de la couche cachée de la tête de move, par colonne de cellule.
MOVE_HEAD_HIDDEN = 32


class PointerMaskablePolicy(MaskableMultiInputActorCriticPolicy):
    """Policy MaskablePPO dont les logits de tir viennent d'un produit scalaire sur les embeddings.

    L'extracteur (`SpatialCombinedExtractor`) sort
    `[tronc | embeddings ennemis par slot | carte de move 32x32]`. Cette policy :
    - n'alimente le tronc MLP qu'avec la partie `tronc` (ni les embeddings ni la carte n'y
      entrent : ils y seraient de nouveau aplatis, exactement ce que le chantier supprime) ;
    - produit les logits de tir ET de combat par `q · e_i` (deux requêtes, mêmes embeddings) et
      les logits de cellule par une conv 1x1 ;
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
        if extractor.n_enemy_slots != FIGHT_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_enemy_slots} slots ennemis "
                f"observes contre {FIGHT_SLOT_COUNT} actions de combat. C'est l'invariant D1, "
                f"cote melee (V11 §9 P3-1)."
            )
        if GRID_CELL_COUNT != MOVE_CELL_COUNT:
            raise ValueError(
                f"Desalignement grille/action : {GRID_CELL_COUNT} cellules de grille contre "
                f"{MOVE_CELL_COUNT} actions de cellule. La tete 1x1 produit UN logit par cellule."
            )
        self.trunk_dim = extractor.trunk_dim
        self.entity_dim = extractor.entity_dim
        self.n_enemy_slots = extractor.n_enemy_slots
        self.move_map_channels = extractor.move_map_channels
        # Tranches LUES sur l'extracteur (jamais recalculées ici : une découpe recopiée pourrait
        # dériver de la disposition réelle sans que rien ne lève, et la tête scorerait des
        # colonnes qui ne sont pas des cellules). L'extracteur n'est pas stocké : le référencer
        # depuis la policy le ferait enregistrer une seconde fois dans le `state_dict`.
        self.enemy_slice = extractor.enemy_embeddings_slice()
        self.move_map_slice = extractor.move_map_slice()
        self.mlp_extractor = MlpExtractor(
            self.trunk_dim,
            net_arch=self.net_arch,
            activation_fn=self.activation_fn,
            device=self.device,
        )
        self.query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)
        # Requete DISTINCTE pour la melee (V11 §9 P3-1). Les deux tetes lisent les MEMES
        # embeddings d'ennemis — c'est tout l'interet du pointeur — mais « quel ennemi tirer » et
        # « quel ennemi frapper » ne sont pas la meme question : portee, couvert et LoS pesent
        # pour l'un, la valeur de la cible et sa capacite de riposte pour l'autre. Partager la
        # requete forcerait un seul ordre de preference pour les deux phases ; la dupliquer coute
        # `entity_dim x latent_dim` parametres et rien de plus (les embeddings, eux, restent
        # partages, donc ce que le reseau apprend d'un ennemi sert aux deux tetes).
        self.fight_query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)

        # --- Tête de move : conv 1x1 sur [colonne de la cellule | latent diffusé] -------------
        # `move_cell_net` et `move_ctx_net` sont les DEUX MOITIÉS d'une seule et même conv 1x1
        # appliquée à la concaténation `[carte ; latent broadcast sur les 32x32]` :
        #
        #     conv1x1([m ; l])[gy,gx] = W_m · m[:,gy,gx] + W_l · l + b
        #
        # Le terme du latent ne dépendant PAS de la cellule, le calculer une fois par échantillon
        # (`Linear`) puis l'ajouter est EXACTEMENT le même résultat — et évite de matérialiser un
        # tenseur (B, latent_dim, 32, 32) : à batch 1024 et latent 320, ce serait 1,3 Go rien que
        # pour diffuser une constante, et 1024x plus de MACs pour la moitié « latent » du 1x1.
        # L'équivalence stricte avec la forme naïve est verrouillée par test.
        #
        # DEUX couches, pas une : avec un 1x1 unique, la contribution du latent serait un décalage
        # IDENTIQUE sur les 1024 logits — donc invisible du softmax, et le conditionnement exigé
        # par l'amendement serait un no-op silencieux. La non-linéarité intercalée est ce qui rend
        # le contexte capable de RÉORDONNER les cellules entre elles (verrouillé par test, avec sa
        # mutation : retirer la ReLU rend le décalage uniforme).
        self.move_cell_net = nn.Conv2d(self.move_map_channels, MOVE_HEAD_HIDDEN, kernel_size=1)
        self.move_ctx_net = nn.Linear(self.mlp_extractor.latent_dim_pi, MOVE_HEAD_HIDDEN)
        self.move_out_net = nn.Conv2d(MOVE_HEAD_HIDDEN, 1, kernel_size=1)

    # -- découpe du vecteur de features ------------------------------------
    def _split_features(
        self, obs: PyTorchObs
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """(tronc, embeddings ennemis (B, K, d), carte de move (B, C, 32, 32)).

        Contrat de `SpatialCombinedExtractor`, dont les tranches ont été lues au build.
        """
        features = self.extract_features(obs)
        if not isinstance(features, torch.Tensor):
            raise TypeError(
                "PointerMaskablePolicy attend un extracteur PARTAGE (un seul tenseur de "
                "features) : deux extracteurs pi/vf produiraient deux jeux d'embeddings."
            )
        batch = features.shape[0]
        trunk = features[:, : self.trunk_dim]
        embeddings = features[:, self.enemy_slice].reshape(
            batch, self.n_enemy_slots, self.entity_dim
        )
        move_map = features[:, self.move_map_slice].reshape(
            batch, self.move_map_channels, GRID_SIZE, GRID_SIZE
        )
        return trunk, embeddings, move_map

    def _move_logits(self, latent_pi: torch.Tensor, move_map: torch.Tensor) -> torch.Tensor:
        """Logits de cellule (B, 1024) — une conv 1x1 par colonne, conditionnée par le tronc.

        ⚠️ ALIGNEMENT, c'est le point critique : `move_map` est indexée `[canal, gy, gx]`,
        comme la grille produite par `build_squad_grid`. Le `reshape` final parcourt donc `gy`
        puis `gx`, ce qui donne l'index `gy * GRID_SIZE + gx` — la définition EXACTE de
        `spatial_grid.cell_index`, celle que suivent le masque d'action et le décodeur. Une
        transposition ici ferait viser à l'agent une cellule et en jouer une autre, sans que rien
        ne lève. Verrouillé par `test_move_logit_is_cell_local` (pic injecté dans une cellule).
        """
        hidden = self.move_cell_net(move_map) + self.move_ctx_net(latent_pi)[:, :, None, None]
        return self.move_out_net(torch.relu(hidden)).reshape(latent_pi.shape[0], MOVE_CELL_COUNT)

    def _action_logits(
        self, latent_pi: torch.Tensor, embeddings: torch.Tensor, move_map: torch.Tensor
    ) -> torch.Tensor:
        """Logits complets : cellules par conv 1x1, tir ET combat par `q · e_i`, reste par `action_net`.

        Les colonnes de `action_net` correspondant aux cellules de move, aux slots de tir et aux
        slots de combat ne sont jamais lues — elles ne reçoivent donc aucun gradient et restent à
        leur initialisation. C'est assumé : conserver `action_net` entier laisse intacts
        l'initialisation orthogonale, la sauvegarde/reprise et le reste de la machinerie SB3.
        Coût mesuré : ~334 k paramètres inertes (aucun gradient, donc aucun effet sur
        l'apprentissage) et un produit matrice-vecteur 1082 colonnes au lieu de 18, soit ~3 %
        du coût de la tête de move — sous le seuil qui justifierait de découper `action_net`.
        """
        base = self.action_net(latent_pi)
        move = self._move_logits(latent_pi, move_map)
        # Mise à l'échelle 1/sqrt(d), comme une attention : sans elle, la variance des logits
        # croît avec la dimension d'embedding et la politique démarre quasi déterministe.
        scale = self.entity_dim ** 0.5
        query = self.query_net(latent_pi).unsqueeze(1)                 # (B, 1, d)
        pointer = (query * embeddings).sum(dim=-1) / scale             # (B, K) — tir
        fight_query = self.fight_query_net(latent_pi).unsqueeze(1)
        fight_pointer = (fight_query * embeddings).sum(dim=-1) / scale  # (B, K) — mêlée
        move_end = MOVE_CELL_BASE + MOVE_CELL_COUNT
        shoot_end = SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT
        fight_end = FIGHT_SLOT_BASE + FIGHT_SLOT_COUNT
        return torch.cat(
            [
                base[:, :MOVE_CELL_BASE],
                move,
                base[:, move_end:SHOOT_SLOT_BASE],
                pointer,
                base[:, shoot_end:FIGHT_SLOT_BASE],
                fight_pointer,
                base[:, fight_end:],
            ],
            dim=1,
        )

    def _distribution_from(
        self,
        latent_pi: torch.Tensor,
        embeddings: torch.Tensor,
        move_map: torch.Tensor,
        action_masks: Optional[np.ndarray],
    ) -> MaskableDistribution:
        distribution = self.action_dist.proba_distribution(
            action_logits=self._action_logits(latent_pi, embeddings, move_map)
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
        trunk, embeddings, move_map = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(trunk)
        values = self.value_net(latent_vf)
        distribution = self._distribution_from(latent_pi, embeddings, move_map, action_masks)
        actions = distribution.get_actions(deterministic=deterministic)
        log_prob = distribution.log_prob(actions)
        return actions, values, log_prob

    def get_distribution(
        self, obs: PyTorchObs, action_masks: Optional[np.ndarray] = None
    ) -> MaskableDistribution:
        trunk, embeddings, move_map = self._split_features(obs)
        latent_pi = self.mlp_extractor.forward_actor(trunk)
        return self._distribution_from(latent_pi, embeddings, move_map, action_masks)

    def predict_values(self, obs: PyTorchObs) -> torch.Tensor:
        trunk, _embeddings, _move_map = self._split_features(obs)
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
        trunk, embeddings, move_map = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(trunk)
        distribution = self._distribution_from(latent_pi, embeddings, move_map, action_masks)
        return self.value_net(latent_vf), distribution.log_prob(actions), distribution.entropy()
