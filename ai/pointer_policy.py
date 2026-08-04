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

from functools import partial
from typing import Any, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from sb3_contrib.common.maskable.distributions import (
    MaskableCategorical,
    MaskableCategoricalDistribution,
    MaskableDistribution,
)
from sb3_contrib.common.maskable.policies import MaskableMultiInputActorCriticPolicy
from stable_baselines3.common.torch_layers import MlpExtractor
from stable_baselines3.common.type_aliases import PyTorchObs

from ai.spatial_extractor import SpatialCombinedExtractor
from engine.macro_intents import (
    CHARGE_SLOT_BASE,
    CHARGE_SLOT_COUNT,
    CHOICE_BASE,
    CHOICE_COUNT,
    DEPLOY_SLOT_COUNT,
    FIGHT_SLOT_BASE,
    FIGHT_SLOT_COUNT,
    MOVE_CELL_BASE,
    MOVE_CELL_COUNT,
    OATH_SLOT_BASE,
    OATH_SLOT_COUNT,
    SHOOT_SLOT_BASE,
    SHOOT_SLOT_COUNT,
    TOTAL_ACTION_SIZE,
)
from engine.spatial_grid import GRID_CELL_COUNT, GRID_SIZE

#: Largeur de la couche cachée de la tête de move, par colonne de cellule.
MOVE_HEAD_HIDDEN = 32

#: Actions produites par `action_net`, la SEULE tête dense restante : wait, fight-sans-cible et
#: les 15 intents de zone. Tout le reste vient d'une tête à poids partagés (conv 1x1 pour les
#: cellules, pointeurs pour les slots de tir, de charge, de mêlée et les candidats de décision).
#: Calculé, jamais écrit en dur : ajouter une famille pointée sans le décompter ici décalerait
#: TOUS les logits qui la suivent.
DENSE_LOGIT_COUNT = (
    TOTAL_ACTION_SIZE
    - MOVE_CELL_COUNT
    - SHOOT_SLOT_COUNT
    - CHARGE_SLOT_COUNT
    - FIGHT_SLOT_COUNT
    - CHOICE_COUNT
    - OATH_SLOT_COUNT
)


class PointerMaskablePolicy(MaskableMultiInputActorCriticPolicy):
    """Policy MaskablePPO dont les logits de tir viennent d'un produit scalaire sur les embeddings.

    L'extracteur (`SpatialCombinedExtractor`) sort
    `[tronc | embeddings ennemis par slot | carte de move 32x32]`. Cette policy :
    - n'alimente le tronc MLP qu'avec la partie `tronc` (ni les embeddings ni la carte n'y
      entrent : ils y seraient de nouveau aplatis, exactement ce que le chantier supprime) ;
    - produit les logits de tir, de charge ET de combat par `q · e_i` (trois requêtes, mêmes
      embeddings) et les logits de cellule par une conv 1x1 ;
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
        if extractor.n_enemy_slots != CHARGE_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_enemy_slots} slots ennemis "
                f"observes contre {CHARGE_SLOT_COUNT} actions de charge. C'est l'invariant D1, "
                f"cote charge (V11 §9 P3-2)."
            )
        if extractor.n_enemy_slots != FIGHT_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_enemy_slots} slots ennemis "
                f"observes contre {FIGHT_SLOT_COUNT} actions de combat. C'est l'invariant D1, "
                f"cote melee (V11 §9 P3-1)."
            )
        if extractor.n_enemy_slots != OATH_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_enemy_slots} slots ennemis "
                f"observes contre {OATH_SLOT_COUNT} actions d'Oath of Moment. C'est l'invariant "
                f"D1, cote Oath (chantier 01)."
            )
        if GRID_CELL_COUNT != MOVE_CELL_COUNT:
            raise ValueError(
                f"Desalignement grille/action : {GRID_CELL_COUNT} cellules de grille contre "
                f"{MOVE_CELL_COUNT} actions de cellule. La tete 1x1 produit UN logit par cellule."
            )
        # HYPOTHÈSE D'ASSEMBLAGE de `_action_logits` — vérifiée ici, où l'erreur est explicite,
        # plutôt que subie sous forme de logits décalés : cellules en tête, `wait`, puis les
        # slots de tir, de charge et de mêlée CONTIGUS, puis le reste dense, puis les CHOICE et
        # enfin les slots d'Oath, qui ferment l'action space.
        if (
            MOVE_CELL_BASE != 0
            or SHOOT_SLOT_BASE != MOVE_CELL_COUNT + 1
            or CHARGE_SLOT_BASE != SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT
            or FIGHT_SLOT_BASE != CHARGE_SLOT_BASE + CHARGE_SLOT_COUNT
            or OATH_SLOT_BASE != CHOICE_BASE + CHOICE_COUNT
            or OATH_SLOT_BASE != TOTAL_ACTION_SIZE - OATH_SLOT_COUNT
        ):
            raise ValueError(
                "Disposition de l'action space inattendue : l'assemblage des logits suppose "
                f"[cellules 0..{MOVE_CELL_COUNT - 1} | wait | tir | charge | melee | dense | "
                f"CHOICE | Oath en fin]. Recu MOVE_CELL_BASE={MOVE_CELL_BASE}, "
                f"SHOOT_SLOT_BASE={SHOOT_SLOT_BASE}, CHARGE_SLOT_BASE={CHARGE_SLOT_BASE}, "
                f"FIGHT_SLOT_BASE={FIGHT_SLOT_BASE}, CHOICE_BASE={CHOICE_BASE}, "
                f"OATH_SLOT_BASE={OATH_SLOT_BASE}, TOTAL_ACTION_SIZE={TOTAL_ACTION_SIZE}."
            )
        self.trunk_dim = extractor.trunk_dim
        self.entity_dim = extractor.entity_dim
        self.n_enemy_slots = extractor.n_enemy_slots
        self.move_map_channels = extractor.move_map_channels
        # Tranches LUES sur l'extracteur (jamais recalculées ici : une découpe recopiée pourrait
        # dériver de la disposition réelle sans que rien ne lève, et la tête scorerait des
        # colonnes qui ne sont pas des cellules). L'extracteur n'est pas stocké : le référencer
        # depuis la policy le ferait enregistrer une seconde fois dans le `state_dict`.
        if extractor.n_decision_options != CHOICE_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_decision_options} candidats de "
                f"decision observes contre {CHOICE_COUNT} actions CHOICE. C'est l'invariant D1 "
                "applique au mecanisme de decision (§9.3 P2)."
            )
        self.n_decision_options = extractor.n_decision_options
        # Même invariant, appliqué au déploiement (§0.40 point 3) : le bloc candidat décrit un
        # slot par action 4-8. S'ils divergeaient, l'agent lirait la description d'un slot pour
        # en jouer un autre — exactement le désalignement obs ↔ action D1.
        if extractor.n_deploy_slots != DEPLOY_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_deploy_slots} candidats de "
                f"deploiement observes contre {DEPLOY_SLOT_COUNT} slots d'action 4-8."
            )
        self.enemy_slice = extractor.enemy_embeddings_slice()
        self.move_map_slice = extractor.move_map_slice()
        self.decision_slice = extractor.decision_embeddings_slice()
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
        # Requete DISTINCTE pour la charge (V11 §9 P3-2), pour la MEME raison : « quel ennemi
        # charger » depend de la distance a franchir au 2D6 et de ce que l engagement me coute au
        # tour adverse, pas de la portee ni du couvert. Meme cout marginal, memes embeddings.
        self.charge_query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)
        # Requête DISTINCTE pour les candidats de décision (§9.3 P2) : « quel ennemi frapper » et
        # « quelle option choisir » sont deux questions différentes posées au même latent, et
        # elles ne lisent même pas les mêmes embeddings (ennemis vs candidats).
        self.choice_query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)
        # Requête DISTINCTE pour Oath of Moment (chantier 01), MÊMES embeddings d'ennemis que le
        # tir, la charge et la mêlée. « Quel ennemi jurer » ne se décide ni comme « quel ennemi
        # tirer » (portée, couvert) ni comme « quel ennemi charger » : Oath vaut pour le tour
        # ENTIER et sur toutes mes escouades, donc c'est la valeur globale de la cible qui pèse.
        # Coût : `entity_dim x latent_dim` paramètres, et zéro par slot.
        self.oath_query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)

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

    def _build(self, lr_schedule: Any) -> None:
        """Construit la policy SB3, puis RÉDUIT `action_net` aux seules colonnes qu'elle produit.

        SB3 dimensionne `action_net` sur l'action space entier. Depuis T-E et T-G, 1050 de ses
        1068 colonnes ne sont jamais lues (cellules, slots de tir) et, depuis P2, les 6 colonnes
        CHOICE non plus : ce sont ~336 k paramètres qui ne reçoivent aucun gradient. La couche est
        donc reconstruite ici à sa taille utile (`DENSE_LOGIT_COUNT`), AVANT la création de
        l'optimiseur — sans quoi l'optimiseur référencerait les paramètres de l'ancienne couche.
        L'initialisation orthogonale de SB3 (gain 0,01 sur la tête d'action) est réappliquée à
        l'identique.
        """
        super()._build(lr_schedule)
        self.action_net = nn.Linear(self.mlp_extractor.latent_dim_pi, DENSE_LOGIT_COUNT).to(
            self.device
        )
        if self.ortho_init:
            self.action_net.apply(partial(self.init_weights, gain=0.01))
        # Même construction que `ActorCriticPolicy._build` : mêmes classe, mêmes kwargs, même
        # learning rate initial. `lr` passe par les kwargs (et non en argument nommé) parce que la
        # signature générique de `torch.optim.Optimizer` ne le déclare pas — SB3 y met un
        # `type: ignore`, ici le dict évite l'exception au typage sans rien changer à l'appel.
        optimizer_kwargs = dict(self.optimizer_kwargs)
        optimizer_kwargs["lr"] = lr_schedule(1)
        self.optimizer = self.optimizer_class(self.parameters(), **optimizer_kwargs)

    # -- découpe du vecteur de features ------------------------------------
    def _split_features(
        self, obs: PyTorchObs
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """(tronc, embeddings ennemis (B, K, d), carte de move (B, C, 32, 32),
        embeddings de candidats de décision (B, C_dec, d)).

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
        decision_emb = features[:, self.decision_slice].reshape(
            batch, self.n_decision_options, self.entity_dim
        )
        return trunk, embeddings, move_map, decision_emb

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
        self,
        latent_pi: torch.Tensor,
        embeddings: torch.Tensor,
        move_map: torch.Tensor,
        decision_emb: torch.Tensor,
    ) -> torch.Tensor:
        """Logits complets, assemblés dans l'ordre des ids d'action.

        Six têtes à poids partagés — conv 1x1 (cellules), pointeurs de tir, de charge (§9 P3-2),
        de mêlée (§9 P3-1) et d'Oath of Moment (chantier 01 : quatre requêtes, MÊMES embeddings
        d'ennemis) et pointeur de décision (candidats `CHOICE_i`, §9.3 P2) — et UNE tête dense
        réduite à ses colonnes réellement lues (`DENSE_LOGIT_COUNT` = 17) : wait,
        fight-sans-cible, 15 intents de zone.

        ⚠️ L'assemblage suit l'ordre EXACT des ids (`macro_intents`) : 0-1023 cellules, 1024 wait,
        1025-1044 tir, 1045-1064 charge, 1065-1084 mêlée, 1085 fight-sans-cible, 1086-1100 zone,
        1101-1106 CHOICE, 1107-1126 Oath. Une permutation ici ferait jouer à l'agent une action
        autre que celle qu'il évalue, sans que rien ne lève — verrouillé par test.
        """
        base = self.action_net(latent_pi)
        move = self._move_logits(latent_pi, move_map)
        # Mise à l'échelle 1/sqrt(d), comme une attention : sans elle, la variance des logits
        # croît avec la dimension d'embedding et la politique démarre quasi déterministe.
        scale = self.entity_dim ** 0.5
        query = self.query_net(latent_pi).unsqueeze(1)                 # (B, 1, d)
        pointer = (query * embeddings).sum(dim=-1) / scale              # (B, K) — tir
        charge_query = self.charge_query_net(latent_pi).unsqueeze(1)
        charge_pointer = (charge_query * embeddings).sum(dim=-1) / scale  # (B, K) — charge
        fight_query = self.fight_query_net(latent_pi).unsqueeze(1)
        fight_pointer = (fight_query * embeddings).sum(dim=-1) / scale  # (B, K) — mêlée
        choice_query = self.choice_query_net(latent_pi).unsqueeze(1)
        choice = (choice_query * decision_emb).sum(dim=-1) / scale      # (B, K_candidats)
        oath_query = self.oath_query_net(latent_pi).unsqueeze(1)
        oath_pointer = (oath_query * embeddings).sum(dim=-1) / scale    # (B, K) — Oath
        return torch.cat(
            [
                move,
                base[:, :1],        # wait
                pointer,
                charge_pointer,
                fight_pointer,
                base[:, 1:],        # fight-sans-cible, intents de zone
                choice,
                oath_pointer,
            ],
            dim=1,
        )

    def _distribution_from(
        self,
        latent_pi: torch.Tensor,
        embeddings: torch.Tensor,
        move_map: torch.Tensor,
        decision_emb: torch.Tensor,
        action_masks: Optional[np.ndarray],
    ) -> MaskableDistribution:
        logits = self._action_logits(latent_pi, embeddings, move_map, decision_emb)
        # Garde-fou de divergence. Ne PAS s'en remettre aux contraintes de `torch.distributions` :
        # `Distribution._validate_args` vaut `__debug__`, donc toute cette validation disparaît
        # sous `python -O` (et sb3 peut l'éteindre globalement). Elle ne couvre de toute façon pas
        # le cas dangereux ici : un `-inf` est un logit LICITE pour torch (probabilité 0), mais
        # `MaskableCategorical.entropy` calcule `logits * probs`, donc `-inf * 0.0 = nan` sur un
        # slot non masqué — le terme d'entropie de PPO devient NaN et empoisonne les poids sans
        # que rien ne lève. Coût mesuré sous 2 % du forward (et ~170 appels par rollout, pas un
        # par pas d'env : le forward est batché sur les n_envs) — le prix d'un échec bruyant.
        if not torch.isfinite(logits).all():
            raise RuntimeError(
                "Non-finite action logits (NaN or +/-inf) produced by the pointer heads: "
                "the policy has diverged, refusing to build a distribution from them."
            )
        # ⚠️ Masquage À LA CONSTRUCTION, en UNE passe — ne pas revenir à
        # `proba_distribution(logits)` puis `apply_masking(masks)`, qui fait TOMBER le run.
        #
        # `MaskableCategorical.apply_masking` se termine par `self.probs = logits_to_probs(...)` :
        # `probs` cesse d'être une lazy_property et devient une valeur matérialisée dans
        # `__dict__`, calculée sur les logits BRUTS. Au masquage SUIVANT, `Distribution.__init__`
        # ne saute plus ce paramètre (il ne saute que les lazy NON matérialisés) et le valide
        # contre `Simplex()`, dont la tolérance est ABSOLUE (`|sum - 1| < 1e-6`) quel que soit le
        # nombre de catégories. Torch juge alors un vecteur PÉRIMÉ, qui ne décrit même pas la
        # distribution construite : sur nos 1107 actions en float32, la somme des probas BRUTES
        # dérive au-delà de 1e-6 là où la distribution MASQUÉE, elle, somme à 1e-8 près. Vécu en
        # éval CPU : 25 épisodes perdus sur une passe, run arrêté à 50 000 épisodes.
        #
        # En une passe, `probs` n'existe pas encore quand torch valide : rien de périmé n'est
        # jugé, et `masks` est posé par le constructeur (donc `entropy()`/`log_prob()`, qui s'en
        # servent, sont inchangés — vérifié bit à bit contre la forme en deux temps).
        action_dist = self.action_dist
        if not isinstance(action_dist, MaskableCategoricalDistribution):
            raise TypeError(
                "PointerMaskablePolicy assemble UN logit par action et exige donc un espace "
                f"d'action Discrete (distribution recue : {type(action_dist).__name__})."
            )
        action_dist.distribution = MaskableCategorical(
            logits=logits.view(-1, action_dist.action_dim), masks=action_masks
        )
        return action_dist

    # -- API policy --------------------------------------------------------
    def forward(
        self,
        obs: PyTorchObs,
        deterministic: bool = False,
        action_masks: Optional[np.ndarray] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        trunk, embeddings, move_map, decision_emb = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(trunk)
        values = self.value_net(latent_vf)
        distribution = self._distribution_from(
            latent_pi, embeddings, move_map, decision_emb, action_masks
        )
        actions = distribution.get_actions(deterministic=deterministic)
        log_prob = distribution.log_prob(actions)
        return actions, values, log_prob

    def get_distribution(
        self, obs: PyTorchObs, action_masks: Optional[np.ndarray] = None
    ) -> MaskableDistribution:
        trunk, embeddings, move_map, decision_emb = self._split_features(obs)
        latent_pi = self.mlp_extractor.forward_actor(trunk)
        return self._distribution_from(
            latent_pi, embeddings, move_map, decision_emb, action_masks
        )

    def predict_values(self, obs: PyTorchObs) -> torch.Tensor:
        trunk, _embeddings, _move_map, _decision_emb = self._split_features(obs)
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
        trunk, embeddings, move_map, decision_emb = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(trunk)
        distribution = self._distribution_from(
            latent_pi, embeddings, move_map, decision_emb, action_masks
        )
        return self.value_net(latent_vf), distribution.log_prob(actions), distribution.entropy()
