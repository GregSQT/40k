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

**Déploiement (V11 §0.44, élément L1).** Les ids `4-11` sont à la fois des cellules de move et
les slots de pose : ils tombent dans la plage des cellules (`MOVE_CELL_BASE = 0`), ce qui rend
`TOTAL_ACTION_SIZE` insensible au nombre de slots. Le masque le sait — il n'ouvre jamais les deux
familles dans le même état — mais la policy l'ignorait, et ces logits sortaient donc de la conv
1x1, sur des cellules sans rapport avec les hexes candidats. `deploy_query_net` les produit
désormais par pointeur, et le routage lit le bit `phase_deployment` de `global_bin`, PAR
ÉCHANTILLON : un lot mélange les phases des `n_envs`.

⚠️ **ZONE À RISQUE, identifiée avant écriture** : une tête d'action custom sous `MaskablePPO`
échoue EN SILENCE si `log_prob`, l'entropie ou le masquage sont faux — l'entraînement tourne et
apprend mal. La conception ci-dessous minimise cette surface : on ne touche QUE la valeur des
logits ; la distribution, le masquage, `log_prob` et l'entropie restent ceux de SB3
(`MaskableCategorical`). `tests/unit/ai/test_pointer_head.py` le vérifie contre une tête dense
de référence sur un cas jouet, tir ET move.
"""

from functools import partial
from typing import Any, NamedTuple, Optional, Tuple

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
    CHARGE_PAIR_SLOT_BASE,
    CHARGE_PAIR_SLOT_COUNT,
    CHOICE_BASE,
    CHOICE_COUNT,
    DEPLOY_SLOT_BASE,
    DEPLOY_SLOT_COUNT,
    FIGHT_SLOT_BASE,
    FIGHT_SLOT_COUNT,
    MOVE_CELL_BASE,
    MOVE_CELL_COUNT,
    ACTIVATE_SLOT_BASE,
    ACTIVATE_SLOT_COUNT,
    FIGHT_WEAPON_SLOT_BASE,
    FIGHT_WEAPON_SLOT_COUNT,
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
#: cellules, pointeurs pour les slots de tir, de charge, de mêlée, d'Oath, de déploiement, les
#: candidats de décision et les escouades à ACTIVER). Les paires de charge ont LEUR propre tête
#: dense (`charge_pair_net`), décomptée ici pour ne pas décaler `action_net`.
#: Calculé, jamais écrit en dur : ajouter une famille pointée/dense sans le décompter ici
#: décalerait TOUS les logits qui la suivent.
DENSE_LOGIT_COUNT = (
    TOTAL_ACTION_SIZE
    - MOVE_CELL_COUNT
    - SHOOT_SLOT_COUNT
    - CHARGE_SLOT_COUNT
    - CHARGE_PAIR_SLOT_COUNT
    - FIGHT_SLOT_COUNT
    - CHOICE_COUNT
    - OATH_SLOT_COUNT
    - ACTIVATE_SLOT_COUNT
    - FIGHT_WEAPON_SLOT_COUNT  # §0.69 : arme CC — tête dense séparée (charge_pair_net pattern)
)


class PolicyFeatures(NamedTuple):
    """Ce que `_split_features` extrait du vecteur de l'extracteur, NOMMÉ et non positionnel.

    Chaque famille pointée ajoute un tenseur ici. Les passer en arguments positionnels — ils
    sont cinq — rendrait une permutation possible entre deux appels sans qu'aucune forme ne
    change : les embeddings ennemis et les candidats de décision ont le même rang et, sur un
    scénario où `K_e == K_d`, la même forme. C'est exactement la classe de faute silencieuse
    contre laquelle tout ce fichier est écrit.
    """

    trunk: torch.Tensor
    #: (B, K_e, d) — ennemis par slot : tir, charge, mêlée, Oath.
    enemies: torch.Tensor
    #: (B, C, 32, 32) — carte de move NON aplatie.
    move_map: torch.Tensor
    #: (B, K_d, d) — candidats de `pending_agent_decision`.
    decision: torch.Tensor
    #: (B, K_p, d) — candidats de déploiement, un par id 4-11.
    deploy: torch.Tensor
    #: (B, K_a, d) — MES escouades par slot : quelle activer (V11 §0.48 `L2`). Ligne 0 COMPRISE.
    allies: torch.Tensor
    #: (B,) — bit `phase_deployment` : 1.0 si les ids 4-11 sont des slots de pose.
    is_deploy: torch.Tensor


class PointerMaskablePolicy(MaskableMultiInputActorCriticPolicy):
    """Policy MaskablePPO dont les logits de tir viennent d'un produit scalaire sur les embeddings.

    L'extracteur (`SpatialCombinedExtractor`) sort `[tronc | embeddings ennemis par slot | carte
    de move 32x32 | candidats de décision | candidats de déploiement]`. Cette policy :
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
        # Invariant D1, une entrée par famille pointée : autant d'actions que de slots OBSERVÉS.
        # Écrit en table et non en cascade de `if` — c'est la liste qu'on oublie d'étendre en
        # ajoutant une famille, et une famille non listée ici ne serait vérifiée nulle part.
        for label, action_count in (
            ("de tir", SHOOT_SLOT_COUNT),
            ("de charge (V11 §9 P3-2)", CHARGE_SLOT_COUNT),
            ("de combat (V11 §9 P3-1)", FIGHT_SLOT_COUNT),
            ("d'Oath of Moment (chantier 01)", OATH_SLOT_COUNT),
        ):
            if extractor.n_enemy_slots != action_count:
                raise ValueError(
                    f"Desalignement observation/action : {extractor.n_enemy_slots} slots ennemis "
                    f"observes contre {action_count} actions {label}. C'est l'invariant D1."
                )
        if GRID_CELL_COUNT != MOVE_CELL_COUNT:
            raise ValueError(
                f"Desalignement grille/action : {GRID_CELL_COUNT} cellules de grille contre "
                f"{MOVE_CELL_COUNT} actions de cellule. La tete 1x1 produit UN logit par cellule."
            )
        # HYPOTHÈSE D'ASSEMBLAGE de `_action_logits` — vérifiée ici, où l'erreur est explicite,
        # plutôt que subie sous forme de logits décalés : cellules en tête, `wait`, puis les
        # slots de tir, de charge et de mêlée CONTIGUS, puis le reste dense, puis les CHOICE, les
        # slots d'Oath, les slots d'ACTIVATION (V11 §0.48 `L2`), et enfin les slots d'ARME CC
        # (V11 §0.69), qui ferment l'espace.
        if (
            MOVE_CELL_BASE != 0
            or SHOOT_SLOT_BASE != MOVE_CELL_COUNT + 1
            or CHARGE_SLOT_BASE != SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT
            or CHARGE_PAIR_SLOT_BASE != CHARGE_SLOT_BASE + CHARGE_SLOT_COUNT
            or FIGHT_SLOT_BASE != CHARGE_PAIR_SLOT_BASE + CHARGE_PAIR_SLOT_COUNT
            or OATH_SLOT_BASE != CHOICE_BASE + CHOICE_COUNT
            or ACTIVATE_SLOT_BASE != OATH_SLOT_BASE + OATH_SLOT_COUNT
            or FIGHT_WEAPON_SLOT_BASE != ACTIVATE_SLOT_BASE + ACTIVATE_SLOT_COUNT
            or FIGHT_WEAPON_SLOT_BASE + FIGHT_WEAPON_SLOT_COUNT != TOTAL_ACTION_SIZE
        ):
            raise ValueError(
                "Disposition de l'action space inattendue : l'assemblage des logits suppose "
                f"[cellules | wait | tir | charge | charge-paire | melee | dense | "
                f"CHOICE | Oath | ACTIVATE | FIGHT_WEAPON en fin]. "
                f"Recu MOVE_CELL_BASE={MOVE_CELL_BASE}, "
                f"SHOOT_SLOT_BASE={SHOOT_SLOT_BASE}, CHARGE_SLOT_BASE={CHARGE_SLOT_BASE}, "
                f"CHARGE_PAIR_SLOT_BASE={CHARGE_PAIR_SLOT_BASE}, "
                f"FIGHT_SLOT_BASE={FIGHT_SLOT_BASE}, CHOICE_BASE={CHOICE_BASE}, "
                f"OATH_SLOT_BASE={OATH_SLOT_BASE}, ACTIVATE_SLOT_BASE={ACTIVATE_SLOT_BASE}, "
                f"FIGHT_WEAPON_SLOT_BASE={FIGHT_WEAPON_SLOT_BASE}, "
                f"TOTAL_ACTION_SIZE={TOTAL_ACTION_SIZE}."
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
        # slot par action 4-11. S'ils divergeaient, l'agent lirait la description d'un slot pour
        # en jouer un autre — exactement le désalignement obs ↔ action D1.
        if extractor.n_deploy_slots != DEPLOY_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_deploy_slots} candidats de "
                f"deploiement observes contre {DEPLOY_SLOT_COUNT} slots d'action "
                f"{DEPLOY_SLOT_BASE}-{DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT - 1}."
            )
        # Recouvrement d'ids ASSUMÉ, et vérifié ici : les slots de déploiement 4-11 tombent DANS
        # la plage des cellules de move. C'est ce qui rend `TOTAL_ACTION_SIZE` insensible au
        # nombre de slots de pose — et ce qui oblige la policy à lire la phase pour savoir
        # laquelle des deux têtes alimente ces colonnes (§0.44, élément L1).
        if (
            DEPLOY_SLOT_BASE < MOVE_CELL_BASE
            or DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT > MOVE_CELL_BASE + MOVE_CELL_COUNT
        ):
            raise ValueError(
                f"Les slots de deploiement {DEPLOY_SLOT_BASE}.."
                f"{DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT - 1} ne tombent plus dans la plage des "
                f"cellules de move [{MOVE_CELL_BASE}, {MOVE_CELL_BASE + MOVE_CELL_COUNT - 1}] : "
                "l'assemblage des logits n'est plus un remplacement de colonnes."
            )
        # Même invariant, appliqué à l'ACTIVATION (V11 §0.48 `L2`) : une action `ACTIVATE_SLOT_i`
        # par ligne ALLIÉE observée. Les désolidariser ferait scorer la ligne `i` pour activer
        # l'escouade `j` — invariant D1, côté allié, et rien ne lèverait.
        if extractor.n_ally_slots != ACTIVATE_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_ally_slots} escouades alliees "
                f"observees contre {ACTIVATE_SLOT_COUNT} slots d'action "
                f"{ACTIVATE_SLOT_BASE}-{ACTIVATE_SLOT_BASE + ACTIVATE_SLOT_COUNT - 1}."
            )
        self.n_deploy_slots = extractor.n_deploy_slots
        self.n_ally_slots = extractor.n_ally_slots
        self.enemy_slice = extractor.enemy_embeddings_slice()
        self.move_map_slice = extractor.move_map_slice()
        self.decision_slice = extractor.decision_embeddings_slice()
        self.deploy_slice = extractor.deploy_embeddings_slice()
        self.ally_slice = extractor.ally_embeddings_slice()
        self.deploy_phase_index = extractor.deployment_phase_flag_index()
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
        # Tête DENSE pour les paires de charge (V11 §9 P3 L9) : C(K_e, 2) = 190 logits.
        # Une paire encode DEUX lignes du tenseur ennemi — impossible pour un produit scalaire
        # unique. La tête dense reçoit le même latent que les autres.
        self.charge_pair_net = nn.Linear(self.mlp_extractor.latent_dim_pi, CHARGE_PAIR_SLOT_COUNT)
        # Tête DENSE pour l'arme CC (V11 §0.69) : K_WEAPONS_MELEE = 10 logits.
        # L'arme n'est pas une entité-ligne du tenseur ennemi — un produit scalaire serait mal
        # fondé. Même patron que charge_pair_net : dense sur le latent commun. Slot j correspond
        # à l'obs melee slot j (collect_weapon_profiles order, invariant D1 armes).
        self.fight_weapon_net = nn.Linear(self.mlp_extractor.latent_dim_pi, FIGHT_WEAPON_SLOT_COUNT)
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
        # Requête DISTINCTE pour les SLOTS DE DÉPLOIEMENT (§0.44, élément L1), jumelle exacte de
        # `choice_query_net` : un candidat de pose est une entité déjà encodée
        # (`deploy_cand_encoder`), donc il se score sur son embedding et non sur une ligne de
        # poids indexée par le slot. C'est ce que le lien slot -> stratégie interdit d'apprendre :
        # le masque n'ouvre que `min(DEPLOY_STRATEGY_COUNT, n_hexes)` slots, donc en fin de
        # déploiement ce sont les stratégies d'indices BAS qui survivent — « le slot 3 va à
        # gauche » est faux une partie du temps. Avant cette tête, ces logits sortaient de la
        # conv 1x1 de la carte, aux cellules (0, 4..11) de la fenêtre égocentrique : des cellules
        # sans aucun rapport avec les hexes candidats.
        self.deploy_query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)
        # Requête DISTINCTE pour le CHOIX DE L'ESCOUADE À ACTIVER (V11 §0.48 `L2`). Elle lit les
        # MÊMES embeddings d'entités que le tir ou la mêlée, mais côté ALLIÉ : mes escouades sont
        # des entités déjà encodées, donc « laquelle activer » se score sur leur embedding.
        #
        # Requête à part, et non `query_net` réutilisée : « quel ennemi tirer » et « laquelle de
        # mes escouades doit jouer maintenant » n'ont ni les mêmes entrées ni le même critère —
        # la seconde pèse ce que l'escouade peut encore faire ce tour-ci et ce que l'ordre
        # d'activation coûte aux suivantes. Coût : `entity_dim x latent_dim` paramètres, et ZÉRO
        # par slot — c'est ce qui rend `K_ALLY_SLOTS = 12` gratuit en capacité.
        #
        # Elle REMPLACE 12 colonnes denses d'`action_net` (une par slot), qui étaient la moitié
        # réseau non livrée de `L2` : une colonne par slot ne partage aucun poids, donc n'apprend
        # rien de transférable d'une escouade à l'autre.
        self.activate_query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)

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
    def _extract(self, obs: PyTorchObs) -> torch.Tensor:
        """Vecteur de features BRUT de l'extracteur, dont la nature partagée est vérifiée ici."""
        features = self.extract_features(obs)
        if not isinstance(features, torch.Tensor):
            raise TypeError(
                "PointerMaskablePolicy attend un extracteur PARTAGE (un seul tenseur de "
                "features) : deux extracteurs pi/vf produiraient deux jeux d'embeddings."
            )
        return features

    def _trunk_features(self, obs: PyTorchObs) -> torch.Tensor:
        """La SEULE partie tronc — ni les embeddings ni la carte n'entrent dans le MLP."""
        return self._extract(obs)[:, : self.trunk_dim]

    def _split_features(self, obs: PyTorchObs) -> PolicyFeatures:
        """Découpe le vecteur de l'extracteur — contrat de `SpatialCombinedExtractor`, dont les
        tranches ont été lues au build (jamais recalculées ici)."""
        features = self._extract(obs)
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
        deploy_emb = features[:, self.deploy_slice].reshape(
            batch, self.n_deploy_slots, self.entity_dim
        )
        ally_emb = features[:, self.ally_slice].reshape(
            batch, self.n_ally_slots, self.entity_dim
        )
        # Bit `phase_deployment` du one-hot de phase, recopié tel quel par l'extracteur. Il ne
        # peut valoir QUE 0 ou 1 : sa clé (`global_bin`) est hors `norm_obs_keys`, précisément
        # pour que les valeurs discrètes gardent leur sémantique. S'il cessait de l'être — une
        # clé ajoutée à `VecNormalize`, un index décalé d'un champ — le routage des ids 4-11
        # deviendrait arbitraire et l'agent jouerait des cellules de move pour des poses, sans
        # que rien ne lève. Le contrôle est là pour que ça lève.
        #
        # SON COÛT EST CONNU ET ASSUMÉ — ne pas le « nettoyer » sur la foi d'un avertissement.
        # Le `bool()` force une synchronisation GPU→CPU, et sous `torch.compile` (actif via
        # `config/config.json` → `torch.compile_mode`) il coupe le graphe, ce que torch >= 2.13
        # signale bruyamment : « Graph break from `Tensor.item()` ». Le message est nouveau, le
        # coût ne l'est pas.
        # Mesuré le 2026-08-11, batch=48, minimum de 12 blocs de 50 forwards, A/B alterné pour
        # neutraliser la dérive du GPU portable : ~0,5 ms par forward, soit 5 à 10 % du forward
        # seul — noyé dans le pas d'environnement, qui domine la boucle. Les trois appelants de
        # `_split_features` paient la synchronisation, mais SEUL `forward` est compilé
        # (`ai/train.py`, `_apply_torch_compile`), donc seul lui subit la coupure de graphe.
        # Ce qu'il ne faut PAS faire : supprimer le contrôle (il couvre une panne silencieuse),
        # ni le réduire au premier batch (le scénario nommé plus haut, une clé ajoutée à
        # `VecNormalize`, dérive EN COURS de run et passerait un contrôle initial), ni activer
        # `capture_scalar_outputs` globalement pour un gain de cet ordre.
        is_deploy = features[:, self.deploy_phase_index]
        if not bool(torch.all((is_deploy == 0.0) | (is_deploy == 1.0))):
            raise RuntimeError(
                "Le drapeau `phase_deployment` lu a l'index "
                f"{self.deploy_phase_index} du vecteur de features n'est pas binaire "
                f"(valeurs {torch.unique(is_deploy).tolist()[:5]}) : le routage des ids "
                f"{DEPLOY_SLOT_BASE}-{DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT - 1} entre la tete de "
                "deploiement et la conv de move ne repose plus sur rien."
            )
        return PolicyFeatures(
            trunk, embeddings, move_map, decision_emb, deploy_emb, ally_emb, is_deploy
        )

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

    def _point(
        self, query_net: nn.Linear, latent_pi: torch.Tensor, embeddings: torch.Tensor
    ) -> torch.Tensor:
        """Logits d'UNE famille pointée : `(q · e_i) / sqrt(d)`, (B, K).

        Mise à l'échelle 1/sqrt(d), comme une attention : sans elle la variance des logits croît
        avec la dimension d'embedding et la politique démarre quasi déterministe. Écrite ICI une
        seule fois — recopiée par famille, c'est l'oubli du diviseur sur une SEULE d'entre elles
        qui passerait inaperçu : les logits restent finis, la politique devient juste quasi
        déterministe sur cette famille-là et sur elle seule.

        Les requêtes restent des modules DISTINCTS (cf. leurs déclarations) : ce qui est partagé
        ici est la formule, pas les poids.
        """
        query = query_net(latent_pi).unsqueeze(1)  # (B, 1, d)
        return (query * embeddings).sum(dim=-1) / self.entity_dim ** 0.5

    def _deploy_logits(
        self, latent_pi: torch.Tensor, move: torch.Tensor, feats: PolicyFeatures
    ) -> torch.Tensor:
        """Remplace, EN PHASE DE DÉPLOIEMENT SEULEMENT, les colonnes 4-11 des cellules de move.

        Les ids 4-11 portent deux significations selon la phase : cellule de la grille
        égocentrique, ou slot de pose. Le masque le sait déjà (il n'ouvre jamais les deux
        familles dans le même état) ; la policy, elle, l'ignorait — ces logits sortaient donc de
        la conv 1x1, sur des cellules sans rapport avec les hexes candidats (§0.44).

        Le routage se fait sur le SEUL bit `phase_deployment`, et par `torch.where` — pas par une
        branche `if` : le batch mélange des observations de phases différentes (n_envs) et une
        branche scalaire trancherait pour tout le lot d'après un seul échantillon.

        ⚠️ Hors phase de déploiement, ces colonnes DOIVENT rester celles de la conv. Le bloc
        `deploy_cand_*` y est nul par contrat (§0.40) : router quand même donnerait 8 logits
        rigoureusement identiques (produit scalaire contre des embeddings nuls), donc un choix
        uniforme sur 8 cellules parfaitement jouables en phase de mouvement.
        """
        pointer = self._point(self.deploy_query_net, latent_pi, feats.deploy)
        low, high = DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT
        slots = torch.where(
            (feats.is_deploy > 0.5).unsqueeze(1), pointer, move[:, low:high]
        )
        return torch.cat([move[:, :low], slots, move[:, high:]], dim=1)

    def _action_logits(self, latent_pi: torch.Tensor, feats: PolicyFeatures) -> torch.Tensor:
        """Logits complets, assemblés dans l'ordre des ids d'action.

        Huit têtes à poids partagés — conv 1x1 (cellules), pointeurs de tir, de charge (§9 P3-2),
        de mêlée (§9 P3-1) et d'Oath of Moment (chantier 01 : quatre requêtes, MÊMES embeddings
        d'ennemis), pointeur de décision (candidats `CHOICE_i`, §9.3 P2), pointeur de
        DÉPLOIEMENT (§0.44, qui écrase les colonnes 4-11 des cellules en phase de déploiement) et
        pointeur d'ACTIVATION (V11 §0.48 `L2`, sur les embeddings ALLIÉS) — et UNE tête dense
        réduite à ses colonnes réellement lues (`DENSE_LOGIT_COUNT` = 17) : wait,
        fight-sans-cible, 15 intents de zone.

        ⚠️ L'assemblage suit l'ordre EXACT des ids (`macro_intents`) : 0-1023 cellules, 1024 wait,
        1025-1044 tir, 1045-1064 charge (cible unique), 1065-1254 charge-paires, 1255-1274 mêlée,
        1275 fight-sans-cible, 1276-1295 tir indirect, 1296-1310 zone, 1311-1316 CHOICE,
        1317-1336 Oath, 1337-1348 ACTIVATION. Une permutation ici ferait jouer à l'agent une
        action autre que celle qu'il évalue, sans que rien ne lève — verrouillé par test.
        """
        enemies = feats.enemies
        base = self.action_net(latent_pi)
        move = self._deploy_logits(
            latent_pi, self._move_logits(latent_pi, feats.move_map), feats
        )
        return torch.cat(
            [
                move,
                base[:, :1],        # wait
                self._point(self.query_net, latent_pi, enemies),           # tir
                self._point(self.charge_query_net, latent_pi, enemies),    # charge (cible unique)
                self.charge_pair_net(latent_pi),                           # charge paires (dense)
                self._point(self.fight_query_net, latent_pi, enemies),     # mêlée
                base[:, 1:],        # fight-sans-cible, shoot-indirect, intents de zone
                self._point(self.choice_query_net, latent_pi, feats.decision),
                self._point(self.oath_query_net, latent_pi, enemies),      # Oath
                # Activation : MES escouades par slot (V11 §0.48 `L2`).
                self._point(self.activate_query_net, latent_pi, feats.allies),
                # Arme CC : tête dense (V11 §0.69), slot j = obs melee slot j.
                self.fight_weapon_net(latent_pi),
            ],
            dim=1,
        )

    def _distribution_from(
        self,
        latent_pi: torch.Tensor,
        feats: PolicyFeatures,
        action_masks: Optional[np.ndarray],
    ) -> MaskableDistribution:
        logits = self._action_logits(latent_pi, feats)
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
        # Masquage À LA CONSTRUCTION, en UNE passe : `probs` n'existe pas encore quand torch
        # valide, donc aucun vecteur périmé n'est jugé, et `masks` est posé par le constructeur
        # (`entropy()` / `log_prob()`, qui s'en servent, sont inchangés).
        #
        # Cette forme a d'abord été IMPOSÉE par un défaut d'amont : jusqu'à sb3_contrib 2.8,
        # `apply_masking` réinitialisait la distribution SANS vider le `probs` déjà matérialisé,
        # et torch validait alors contre `Simplex()` (tolérance ABSOLUE, `|sum - 1| < 1e-6`, quel
        # que soit le nombre de catégories) un vecteur calculé sur les logits BRUTS — au-delà de
        # 1e-6 sur ~1100 actions en float32, là où la distribution MASQUÉE sommait à 1e-8 près.
        # Vécu en éval CPU : 25 épisodes perdus sur une passe, run arrêté à 50 000 épisodes.
        # sb3_contrib 2.9.0 (épinglé À L'ÉGAL dans requirements.txt) a corrigé l'amont, et les
        # deux tests qui surveillaient ce défaut ont été retirés le 2026-08-11 : ils ne pouvaient
        # plus rien observer (aucun rejet sur 3000 offsets, tailles d'espace d'action 1107 à 2000).
        # La forme en UNE passe RESTE : une seule initialisation au lieu de deux, et surtout
        # aucune dépendance à ce correctif d'amont.
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
        feats = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(feats.trunk)
        values = self.value_net(latent_vf)
        distribution = self._distribution_from(latent_pi, feats, action_masks)
        actions = distribution.get_actions(deterministic=deterministic)
        log_prob = distribution.log_prob(actions)
        return actions, values, log_prob

    def get_distribution(
        self, obs: PyTorchObs, action_masks: Optional[np.ndarray] = None
    ) -> MaskableDistribution:
        feats = self._split_features(obs)
        latent_pi = self.mlp_extractor.forward_actor(feats.trunk)
        return self._distribution_from(latent_pi, feats, action_masks)

    def predict_values(self, obs: PyTorchObs) -> torch.Tensor:
        """Le critique ne lit QUE le tronc : ne pas passer par `_split_features`.

        Les quatre blocs pointés sont des tranches NON contiguës du vecteur de features ; les
        `reshape` de `_split_features` en font donc des copies réelles — la seule carte de move
        pèse `move_map_channels x 1024` par échantillon — pour des tenseurs qu'aucune tête ne
        lirait ici. Le contrôle du drapeau `phase_deployment` reste sur le chemin ACTEUR, le
        seul qui route sur lui.
        """
        features = self._trunk_features(obs)
        return self.value_net(self.mlp_extractor.forward_critic(features))

    def evaluate_actions(
        self,
        obs: PyTorchObs,
        actions: torch.Tensor,
        action_masks: Optional[Any] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]:
        """⚠️ Ordre de retour SB3 : (values, log_prob, entropy) — l'inverser sabote la mise à
        jour PPO en silence (le ratio et l'avantage seraient calculés sur les mauvaises
        quantités). Verrouillé par `test_pointer_head.py`."""
        feats = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(feats.trunk)
        distribution = self._distribution_from(latent_pi, feats, action_masks)
        return self.value_net(latent_vf), distribution.log_prob(actions), distribution.entropy()
