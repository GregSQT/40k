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
désormais par pointeur, et le routage lit le bit `present` des candidats de pose
(`deploy_cand_bin[..., -1]`), PAR ÉCHANTILLON : un lot mélange les phases des `n_envs`.

⚠️ **ZONE À RISQUE, identifiée avant écriture** : une tête d'action custom sous `MaskablePPO`
échoue EN SILENCE si `log_prob`, l'entropie ou le masquage sont faux — l'entraînement tourne et
apprend mal. La conception ci-dessous minimise cette surface : on ne touche QUE la valeur des
logits ; la distribution, le masquage, `log_prob` et l'entropie restent ceux de SB3
(`MaskableCategorical`). `tests/unit/ai/test_pointer_head.py` le vérifie contre une tête dense
de référence sur un cas jouet, tir ET move.
"""

from functools import partial
from typing import Any, Dict, Mapping, NamedTuple, Optional, Protocol, Tuple, Type

import numpy as np
import torch
import torch.nn as nn
from sb3_contrib.common.maskable.distributions import (
    MaskableCategorical,
    MaskableCategoricalDistribution,
    MaskableDistribution,
    make_masked_proba_distribution,
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
    COHERENCY_SLOT_BASE,
    COHERENCY_SLOT_COUNT,
    FIGHT_WEAPON_SLOT_BASE,
    FIGHT_WEAPON_SLOT_COUNT,
    OATH_SLOT_BASE,
    OATH_SLOT_COUNT,
    SHOOT_SLOT_BASE,
    SHOOT_SLOT_COUNT,
    SHOOT_WEAPON_SEL_SLOT_BASE,
    SHOOT_WEAPON_SEL_SLOT_COUNT,
    TOTAL_ACTION_SIZE,
)
from engine.observation_entities import unit_bin_index
from engine.spatial_grid import GRID_CELL_COUNT, GRID_SIZE

#: Index LUS sur le schéma d'entité, jamais recopiés (convention §0.37 : `present` est le dernier
#: champ). `fight_target_selected` n'est écrit QUE sur les entités ENNEMIES
#: (`observation_builder`, branche `if not is_ally`), donc il ne se lit que là.
_ENEMY_PRESENT_IDX = unit_bin_index("present")
_FIGHT_TARGET_IDX = unit_bin_index("fight_target_selected")

#: Largeur de la couche cachée de la tête de move, par colonne de cellule.
MOVE_HEAD_HIDDEN = 32

#: Préfixe des paramètres de la tête Q dans le `state_dict` de la politique. Une archive
#: antérieure à S14 ne les porte pas ; elle reste JOUABLE (la tête Q ne participe à aucune
#: décision), donc tout ce qui compare ou charge des state_dicts la tolère sur ce seul préfixe.
ADV_HEADS_PREFIX = "adv_heads."


def is_adv_heads_key(name: str) -> bool:
    """Vrai pour une clé de `state_dict` de la tête Q — la seule absence qu'un chargement tolère."""
    return name.startswith(ADV_HEADS_PREFIX)


def extend_optimizer_state(saved: Mapping[str, Any], n_params: int) -> Dict[str, Any]:
    """État d'optimiseur sauvé pour `n` paramètres, étendu à `n_params >= n` paramètres.

    Torch identifie les paramètres d'un groupe par leur RANG dans `param_groups[0]["params"]`
    et indexe `state` par ce rang. Les `n` premiers rangs restent les mêmes — la tête Q est
    enregistrée EN DERNIER (`PointerMaskablePolicy._build`) — et les rangs ajoutés n'ont pas
    d'état : Adam les initialise à zéro au premier pas. Un seul groupe attendu
    (`ActorCriticPolicy._build` n'en crée qu'un) ; plus de rangs que de paramètres, ou des rangs
    qui ne sont pas `0..n-1` : l'état ne vient pas d'une politique alignée, lever.
    """
    groups = saved.get("param_groups")
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError(
            f"Etat d'optimiseur inattendu : {0 if not isinstance(groups, list) else len(groups)} "
            "groupe(s) de parametres, 1 attendu."
        )
    saved_ranks = list(groups[0]["params"])
    if len(saved_ranks) > n_params or saved_ranks != list(range(len(saved_ranks))):
        raise ValueError(
            f"Etat d'optimiseur inaligne : {len(saved_ranks)} rangs sauves "
            f"({saved_ranks[:3]}...) pour {n_params} parametres."
        )
    extended: Dict[str, Any] = {"state": dict(saved["state"]), "param_groups": [dict(groups[0])]}
    extended["param_groups"][0]["params"] = list(range(n_params))
    return extended


def center_under_policy(
    adv_all: torch.Tensor, probs: torch.Tensor
) -> Tuple[torch.Tensor, torch.Tensor]:
    """`(A_c, offset)` : avantages CENTRÉS sous la politique, et l'offset par état retiré.

    `adv_all` (B, n_actions) : la sortie BRUTE de la tête Q ; `probs` (B, n_actions) : π(·|s)
    masquée — nulle hors actions légales, DÉTACHÉE par l'appelant. `offset` (B,) = Σ_a π·A,
    `A_c = A − offset`, donc Σ_a π·A_c = 0 pour chaque état par construction.

    POURQUOI (mesuré le 2026-09-15 sur 978 états du run S14 non centré,
    ppo_checkpoint_20260915-134841_5767944_steps.zip) : 98 % de Var(A(s, a_jouée)) était une
    constante par état — écart-type 0,222 pour l'offset contre 0,027 entre actions d'un même
    état. Sans contrainte, rien ne distingue `V + A` de `(V − c) + (A + c)` : la tête absorbait
    le biais de V dans un terme qui ne dépend que de s. Pour l'acteur, un tel terme est un
    gradient NUL en espérance (baseline) mais, après `normalize_advantage`, c'est lui qui fixe
    l'écart-type du mini-lot : le signal entre actions sortait à ~0,12 d'écart-type, noyé.

    POURQUOI π et non la moyenne uniforme : `a_t ~ π`, donc `V(s) = E_π[Q(s, ·)]` exactement
    et le biais de V est orthogonal au sous-espace de moyenne nulle sous π — il reste à la
    charge de V et ne peut pas fuir dans `A_c`. Sous la moyenne uniforme, les actions légales
    jamais jouées porteraient l'offset et la contrainte ne dirait rien de l'action jouée.
    π DÉTACHÉE : la perte Q ne doit pas déplacer la politique par le centrage.
    """
    if adv_all.shape != probs.shape:
        raise ValueError(
            f"center_under_policy : avantages {tuple(adv_all.shape)} et probabilités "
            f"{tuple(probs.shape)} de formes differentes."
        )
    offset = (probs * adv_all).sum(dim=1)
    return adv_all - offset.unsqueeze(1), offset


def masked_probs(distribution: MaskableCategoricalDistribution) -> torch.Tensor:
    """π(·|s) (B, n_actions) de la distribution MASQUÉE construite par `_distribution_from`.

    `MaskableCategorical` pose −1e8 sur les logits masqués : probs EXACTEMENT nulles hors
    actions légales en float32. Reliée au graphe : l'appelant détache s'il le faut.
    """
    return distribution.distribution.probs


_LENIENT_OPTIMIZERS: Dict[type, type] = {}


def lenient_optimizer_class(base: Type[torch.optim.Optimizer]) -> Type[torch.optim.Optimizer]:
    """Sous-classe de `base` dont `load_state_dict` accepte l'état d'une politique SANS tête Q.

    C'est `set_parameters` (SB3) qui charge l'optimiseur, par `attr.load_state_dict(state)` et
    sans option : pour qu'un zip antérieur à S14 charge par TOUS les chemins — `MaskablePPO.load`
    nu compris (PvE, workers d'évaluation, snapshots du pool, replay) — la tolérance doit vivre
    dans l'objet optimiseur lui-même. Un état déjà complet passe tel quel. Une classe par base,
    mémorisée : `deepcopy` et la sérialisation SB3 (qui ne stocke que `state_dict()`) n'y voient
    qu'un optimiseur ordinaire.
    """
    cached = _LENIENT_OPTIMIZERS.get(base)
    if cached is not None:
        return cached

    class _LenientOptimizer(base):  # type: ignore[valid-type, misc]
        def load_state_dict(self, state_dict: Mapping[str, Any]) -> None:
            n_params = sum(len(group["params"]) for group in self.param_groups)
            groups = state_dict.get("param_groups")
            n_saved = (
                sum(len(g["params"]) for g in groups) if isinstance(groups, list) else n_params
            )
            if n_saved < n_params:
                state_dict = extend_optimizer_state(state_dict, n_params)
            super().load_state_dict(state_dict)  # type: ignore[arg-type]

    _LenientOptimizer.__name__ = f"Lenient{base.__name__}"
    _LenientOptimizer.__qualname__ = _LenientOptimizer.__name__
    _LENIENT_OPTIMIZERS[base] = _LenientOptimizer
    return _LenientOptimizer


class HeadNets(Protocol):
    """Ce que l'assemblage des logits LIT : un jeu de têtes nommées, poids seuls.

    Satisfait structurellement par la politique elle-même (ses attributs, créés dans
    `_build_mlp_extractor` et `_build`) et par `PointerHeadNets` (la tête Q). Le typage force
    les deux jeux à porter les mêmes noms — c'est le contrat qu'un assemblage unique exige.
    """

    query_net: nn.Linear
    fight_query_net: nn.Linear
    charge_query_net: nn.Linear
    charge_pair_net: nn.Linear
    fight_weapon_query_net: nn.Linear
    shoot_weapon_sel_query_net: nn.Linear
    fight_weapon_target_net: nn.Linear
    shoot_weapon_target_net: nn.Linear
    choice_query_net: nn.Linear
    oath_query_net: nn.Linear
    deploy_query_net: nn.Linear
    activate_query_net: nn.Linear
    coherency_query_net: nn.Linear
    move_cell_net: nn.Conv2d
    move_ctx_net: nn.Linear
    move_out_net: nn.Conv2d
    action_net: nn.Linear


class PointerHeadNets(nn.Module):
    """Un JEU de têtes d'action (les poids seuls), lu par `PointerMaskablePolicy._action_logits`.

    La politique possède son jeu sous forme d'attributs directs (`query_net`, `move_out_net`,
    `action_net`, …, clés du `state_dict` inchangées depuis T-E). Ce module en porte un SECOND,
    de structure identique, sous `adv_heads.*` : la TÊTE Q (S14, dossier plafonnement_p1.md
    §9.5). Lue sur le tronc CRITIC (`latent_vf`), elle rend pour chaque action non pas un logit
    mais un AVANTAGE attendu `A(s, a) = E[retour | s, a] − V(s)` : Q(s, a) = V(s) + A_c(s, a)
    (forme duelling, V détaché, `A_c` CENTRÉ sous π par `center_under_policy` — sans quoi la
    tête absorbait le biais de V dans une constante par état, 98 % de sa variance le
    2026-09-15), régressée sur le même retour λ que V. L'acteur PPO reçoit alors
    `A_c(s, a_jouée)` à la place de l'avantage GAE : une différence de deux espérances apprises
    sur des milliers de jets de dés, là où le GAE porte le jet de CE tir (mesuré le 2026-09-13 :
    86 % de Var(δ) est Var(r), 96 % sur le tir).

    Pourquoi la MÊME structure que les têtes de politique : un avantage par action a exactement
    les mêmes entrées qu'un logit par action — l'entité pointée pour un slot, la colonne de
    cellule pour un move — et `_assemble_logits` ne lit que des noms d'attributs, donc un seul
    assemblage sert aux deux (verrouillé : `adv_heads` porte les mêmes noms). Pourquoi un
    module SÉPARÉ et non des attributs sur la policy : ses paramètres doivent être enregistrés
    APRÈS tous ceux de la politique pour qu'un zip antérieur (sans tête) charge avec ses états
    Adam alignés sur les MÊMES indices (`PatchedMaskablePPO.set_parameters`).

    INITIALISATION À ZÉRO de toute couche qui PRODUIT une sortie (requêtes, projections
    arme x cible, tête dense, paires de charge, `move_out_net`) : une tête fraîche rend
    `A(s, a) = 0` pour toute action, donc un acteur qui la lit ne bouge pas tant qu'elle n'a
    pas appris — c'est l'échauffement (`value_warmup_updates`) qui la fait apprendre d'abord,
    politique figée. `move_cell_net` et `move_ctx_net` (couche cachée) gardent l'init par défaut :
    à zéro, la ReLU rendrait un gradient nul en aval et la tête de move n'apprendrait jamais.
    """

    query_net: nn.Linear
    fight_query_net: nn.Linear
    charge_query_net: nn.Linear
    charge_pair_net: nn.Linear
    fight_weapon_query_net: nn.Linear
    shoot_weapon_sel_query_net: nn.Linear
    fight_weapon_target_net: nn.Linear
    shoot_weapon_target_net: nn.Linear
    choice_query_net: nn.Linear
    oath_query_net: nn.Linear
    deploy_query_net: nn.Linear
    activate_query_net: nn.Linear
    coherency_query_net: nn.Linear
    move_cell_net: nn.Conv2d
    move_ctx_net: nn.Linear
    move_out_net: nn.Conv2d
    action_net: nn.Linear

    OUTPUT_LAYERS: Tuple[str, ...] = (
        "query_net", "fight_query_net", "charge_query_net", "charge_pair_net",
        "fight_weapon_query_net", "shoot_weapon_sel_query_net",
        "fight_weapon_target_net", "shoot_weapon_target_net",
        "choice_query_net", "oath_query_net", "deploy_query_net", "activate_query_net",
        "coherency_query_net", "move_out_net", "action_net",
    )

    def __init__(
        self, latent_dim: int, entity_dim: int, weapon_dim: int, move_map_channels: int
    ) -> None:
        super().__init__()
        _build_head_nets(self, latent_dim, entity_dim, weapon_dim, move_map_channels)
        self.action_net = nn.Linear(latent_dim, DENSE_LOGIT_COUNT)
        for name in self.OUTPUT_LAYERS:
            layer = getattr(self, name)
            nn.init.zeros_(layer.weight)
            nn.init.zeros_(layer.bias)

    def is_untrained(self) -> bool:
        """Vrai tant qu'aucun gradient n'a jamais atteint la tête : ses couches de sortie sont
        EXACTEMENT à zéro, l'état de l'initialisation.

        C'est la définition de « tête fraîche », par le CONTENU et non par la provenance : un zip
        chargé sans la tête (clés absentes, tête construite à zéro) et un zip entraîné en `gae`
        après S14 (tête présente, jamais touchée — sous `gae` elle ne reçoit aucun gradient et
        Adam saute un paramètre sans gradient) sont dans le même état, et tous deux exigent
        l'échauffement avant qu'un acteur lise leurs avantages, qui valent zéro partout. Une
        tête qui a reçu un seul pas d'Adam n'a plus aucune couche de sortie exactement nulle.
        """
        with torch.no_grad():
            return all(
                not bool(getattr(self, name).weight.any()) and not bool(getattr(self, name).bias.any())
                for name in self.OUTPUT_LAYERS
            )


def _build_head_nets(
    target: "PointerHeadNets", latent_dim: int, entity_dim: int, weapon_dim: int,
    move_map_channels: int,
) -> None:
    """Crée sur `target` les têtes à poids partagés de la tête Q — SAUF `action_net`, que
    `PointerHeadNets` crée lui-même.

    MIROIR de la construction des têtes de la politique (`_build_mlp_extractor`), qui garde
    ses créations en place avec les raisons de chaque tête ; ici ce ne sont que des formes.
    Les deux jeux DOIVENT rester identiques nom pour nom et forme pour forme (à `latent_dim`
    près, tronc pi d'un côté, tronc vf de l'autre) : `_assemble_logits` lit des noms
    d'attributs, un nom absent lève, une forme différente scorerait des tenseurs qui ne
    s'alignent pas. Verrouillé par `tests/unit/ai/test_q_head.py` (mêmes noms, mêmes formes).
    """
    target.query_net = nn.Linear(latent_dim, entity_dim)
    target.fight_query_net = nn.Linear(latent_dim, entity_dim)
    target.charge_query_net = nn.Linear(latent_dim, entity_dim)
    target.charge_pair_net = nn.Linear(latent_dim, CHARGE_PAIR_SLOT_COUNT)
    target.fight_weapon_query_net = nn.Linear(latent_dim, weapon_dim)
    target.shoot_weapon_sel_query_net = nn.Linear(latent_dim, weapon_dim)
    target.fight_weapon_target_net = nn.Linear(entity_dim, weapon_dim)
    target.shoot_weapon_target_net = nn.Linear(entity_dim, weapon_dim)
    target.choice_query_net = nn.Linear(latent_dim, entity_dim)
    target.oath_query_net = nn.Linear(latent_dim, entity_dim)
    target.deploy_query_net = nn.Linear(latent_dim, entity_dim)
    target.activate_query_net = nn.Linear(latent_dim, entity_dim)
    target.coherency_query_net = nn.Linear(latent_dim, entity_dim)
    target.move_cell_net = nn.Conv2d(move_map_channels, MOVE_HEAD_HIDDEN, kernel_size=1)
    target.move_ctx_net = nn.Linear(latent_dim, MOVE_HEAD_HIDDEN)
    target.move_out_net = nn.Conv2d(MOVE_HEAD_HIDDEN, 1, kernel_size=1)

#: Actions produites par `action_net`, la SEULE tête dense restante : wait, fight-sans-cible,
#: tir indirect (20 slots, même compte D1 que le pointeur SHOOT) et les 15 intents de zone. Tout le
#: reste vient d'une tête à poids partagés (conv 1x1 pour les
#: cellules, pointeurs pour les slots de tir, de charge, de mêlée, d'Oath, de déploiement, les
#: candidats de décision, les escouades à ACTIVER, les figurines à retirer et les EMPLACEMENTS
#: D'ARME). Les paires de charge ont LEUR propre tête
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
    - FIGHT_WEAPON_SLOT_COUNT        # §0.69 : arme CC — tête pointeur sur les profils de mêlée
    - COHERENCY_SLOT_COUNT           # P3-0 : retrait cohérence — tête pointeur sur figurines actives
    - SHOOT_WEAPON_SEL_SLOT_COUNT    # P3-8 : split-fire tir — tête pointeur sur les profils de tir
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
    #: (B,) — 1.0 si les ids 4-11 sont des slots de pose sur cet échantillon, c'est-à-dire si au
    #: moins un candidat est `present` (déploiement ou ingress move 20.04).
    is_deploy: torch.Tensor
    #: (B, N_sm, d) — figurines de l'unité active par slot : quelle retirer hors cohérence (P3-0).
    self_models: torch.Tensor
    #: (B, K_w, d_w) — EMPLACEMENTS d'arme de l'unité active : tir d'abord, mêlée ensuite.
    #: Largeur `weapon_dim`, celle de l'encodeur d'armes partagé — pas `entity_dim`.
    weapons: torch.Tensor
    #: (B, K_e) — bit `present` des slots ennemis, LU sur le schéma. Il borne le `max` de la
    #: compatibilité arme x cible : un slot absent a un embedding NUL, mais la projection qui le
    #: lit a un BIAIS, donc sa compatibilité vaut `(w_j · b) / sqrt(d_w)` — une valeur arbitraire,
    #: pas zéro, qui remporterait le `max` aussi souvent que le hasard le veut.
    enemies_present: torch.Tensor
    #: (B, K_e) — bit `fight_target_selected` : la cible DÉJÀ désignée du choix d'arme de mêlée.
    #: Exactement une ligne à 1 pendant `pending_fight_weapon_select` (le moteur lève si la cible
    #: n'occupe aucun slot observé), zéro ligne partout ailleurs.
    fight_target: torch.Tensor


class PointerMaskablePolicy(MaskableMultiInputActorCriticPolicy):
    """Policy MaskablePPO dont les logits de tir viennent d'un produit scalaire sur les embeddings.

    L'extracteur (`SpatialCombinedExtractor`) sort `[tronc | embeddings ennemis par slot | carte
    de move 32x32 | candidats de décision | candidats de déploiement | escouades alliées | mes
    figurines | emplacements d'arme de l'unité active]`. Cette policy :
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
            or COHERENCY_SLOT_BASE != FIGHT_WEAPON_SLOT_BASE + FIGHT_WEAPON_SLOT_COUNT
            or SHOOT_WEAPON_SEL_SLOT_BASE != COHERENCY_SLOT_BASE + COHERENCY_SLOT_COUNT
            or SHOOT_WEAPON_SEL_SLOT_BASE + SHOOT_WEAPON_SEL_SLOT_COUNT != TOTAL_ACTION_SIZE
        ):
            raise ValueError(
                "Disposition de l'action space inattendue : l'assemblage des logits suppose "
                f"[cellules | wait | tir | charge | charge-paire | melee | dense | "
                f"CHOICE | Oath | ACTIVATE | FIGHT_WEAPON | COHERENCY | SHOOT_WEAPON_SEL en fin]. "
                f"Recu MOVE_CELL_BASE={MOVE_CELL_BASE}, "
                f"SHOOT_SLOT_BASE={SHOOT_SLOT_BASE}, CHARGE_SLOT_BASE={CHARGE_SLOT_BASE}, "
                f"CHARGE_PAIR_SLOT_BASE={CHARGE_PAIR_SLOT_BASE}, "
                f"FIGHT_SLOT_BASE={FIGHT_SLOT_BASE}, CHOICE_BASE={CHOICE_BASE}, "
                f"OATH_SLOT_BASE={OATH_SLOT_BASE}, ACTIVATE_SLOT_BASE={ACTIVATE_SLOT_BASE}, "
                f"FIGHT_WEAPON_SLOT_BASE={FIGHT_WEAPON_SLOT_BASE}, "
                f"SHOOT_WEAPON_SEL_SLOT_BASE={SHOOT_WEAPON_SEL_SLOT_BASE}, "
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
        # Même invariant D1, côté propre (P3-0 retrait cohérence) : un slot COHERENCY_i par
        # figurine propre observée. Les désolidariser ferait pointer la requête vers la figurine
        # `j` pour jouer le slot `i` — rien ne lèverait.
        if extractor.n_self_models != COHERENCY_SLOT_COUNT:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_self_models} figurines propres "
                f"observees contre {COHERENCY_SLOT_COUNT} slots d'action "
                f"{COHERENCY_SLOT_BASE}-{COHERENCY_SLOT_BASE + COHERENCY_SLOT_COUNT - 1}."
            )
        self.n_self_models = extractor.n_self_models
        # Même invariant D1, appliqué aux EMPLACEMENTS D'ARME de l'unité active : le bloc d'armes
        # observé porte un emplacement par action de choix d'arme, les profils de TIR d'abord
        # (`SHOOT_WEAPON_SEL_SLOT_j`) puis ceux de MÊLÉE (`FIGHT_WEAPON_SLOT_j`) — c'est l'ordre
        # d'émission de `encode_squad_weapon_profiles`, et c'est lui que les deux têtes découpent
        # ci-dessous. Les désolidariser ferait scorer le profil `j` pour déclarer le profil `k`,
        # et rien ne lèverait : les deux blocs resteraient des rangs de formes valides.
        _weapon_slot_total = SHOOT_WEAPON_SEL_SLOT_COUNT + FIGHT_WEAPON_SLOT_COUNT
        if extractor.n_weapons != _weapon_slot_total:
            raise ValueError(
                f"Desalignement observation/action : {extractor.n_weapons} emplacements d'arme "
                f"observes contre {SHOOT_WEAPON_SEL_SLOT_COUNT} actions de choix d'arme de tir "
                f"+ {FIGHT_WEAPON_SLOT_COUNT} de melee ({_weapon_slot_total})."
            )
        self.n_weapons = extractor.n_weapons
        self.weapon_dim = extractor.weapon_dim
        self.enemy_slice = extractor.enemy_embeddings_slice()
        self.move_map_slice = extractor.move_map_slice()
        self.decision_slice = extractor.decision_embeddings_slice()
        self.deploy_slice = extractor.deploy_embeddings_slice()
        self.ally_slice = extractor.ally_embeddings_slice()
        self.self_model_slice = extractor.self_model_embeddings_slice()
        self.active_weapon_slice = extractor.active_weapon_embeddings_slice()
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
        # Requêtes DISTINCTES pour les EMPLACEMENTS D'ARME de l'unité active, mêlée et tir.
        #
        # Elles REMPLACENT deux têtes denses (`fight_weapon_net`, `shoot_weapon_sel_net`), qui
        # tenaient une prémisse fausse : « l'arme n'est pas une entité-ligne du tenseur ennemi,
        # un produit scalaire serait mal fondé ». Elle ne l'est pas du tenseur ENNEMI, mais elle
        # est une entité-ligne du bloc d'armes de l'unité ACTIVE — le même encodeur partagé
        # (`weapon_encoder`) la décrit des deux côtés du plateau, et l'extracteur expose désormais
        # ces lignes par emplacement (`active_weapon_embeddings_slice`).
        #
        # CE QUE LA TÊTE DENSE NE POUVAIT PAS APPRENDRE : l'ordre des emplacements n'est pas
        # stable. `collect_weapon_profiles` trie par nombre de PORTEURS VIVANTS décroissant, donc
        # une perte suffit à échanger deux emplacements sans qu'aucune action ait été jouée
        # (mesuré : 3 bolters + 2 lascannons donnent `[bolter, lascannon]` à effectif plein et
        # `[lascannon, bolter]` après deux pertes de bolter). Une ligne de poids indexée par le
        # rang apprenait donc une position dont le contenu bouge — et d'autant plus mal que les
        # pertes s'accumulent en fin de partie. Le produit scalaire, lui, score l'ARME qui occupe
        # l'emplacement : le score suit le profil quand il change de rang.
        #
        # Deux requêtes et non une, même doctrine que tir/charge/mêlée sur les ennemis : « avec
        # quelle arme frapper » (l'ennemi est déjà désigné, seule la table de blessure compte) et
        # « quel groupe d'armes envoyer, et sur qui » ne sont pas la même question. Coût :
        # `weapon_dim x latent_dim` chacune, et ZÉRO par emplacement.
        self.fight_weapon_query_net = nn.Linear(
            self.mlp_extractor.latent_dim_pi, self.weapon_dim
        )
        self.shoot_weapon_sel_query_net = nn.Linear(
            self.mlp_extractor.latent_dim_pi, self.weapon_dim
        )
        # PROJECTIONS ennemi -> espace des armes : elles portent la COMPATIBILITÉ arme x cible,
        # c'est-à-dire la question que le choix d'arme pose vraiment. Choisir une arme, c'est
        # confronter S/PA/D à E/Sv/PV (04.01/05.02/05.04) : sans la cible, la requête ne dispose
        # que du latent, où les 20 ennemis arrivent noyés dans une moyenne et un max
        # (`enemies_agg`). Le réseau devrait y ré-extraire une ligne parmi vingt — exactement le
        # travail que l'architecture pointeur existe pour lui épargner.
        #
        # Deux projections et non une, pour la raison qui sépare déjà les requêtes : les deux
        # points d'arrêt ne savent PAS la même chose de la cible (cf. `_weapon_target_bonus`).
        #
        # Le terme est ADDITIF sur le logit et vaut algébriquement une requête conditionnée :
        # `(P e) · w_j` est le second terme de `(W_q l + P e) · w_j`. L'écrire comme une matrice
        # arme x ennemi est ce qui permet au tir, qui n'a pas de cible désignée, de réduire par un
        # `max` là où la mêlée réduit par la ligne marquée.
        self.fight_weapon_target_net = nn.Linear(self.entity_dim, self.weapon_dim)
        self.shoot_weapon_target_net = nn.Linear(self.entity_dim, self.weapon_dim)
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
        # Requête DISTINCTE pour le retrait hors cohérence (P3-0) : quelle figurine de l'escouade
        # active retirer. Elle lit les embeddings par slot de `self_models_*` (invariant D1 : slot i
        # = ligne i de `_squad_models_for_observation`). « Quelle figurine sacrifier » n'est ni
        # « quel ennemi tirer » ni « quelle escouade activer » — la figurine à retirer est la moins
        # exposée, la moins armée, ou la plus éloignée de l'ennemi, critère propre à ce contexte.
        self.coherency_query_net = nn.Linear(self.mlp_extractor.latent_dim_pi, self.entity_dim)

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

        SB3 dimensionne `action_net` sur l'action space entier. Depuis T-E, T-G et les extensions
        P3, 1352 de ses 1389 colonnes ne sont jamais lues (cellules, pointeurs) : ce sont ~360 k
        paramètres qui ne reçoivent aucun gradient. La couche est
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
        # TÊTE Q (S14), enregistrée EN DERNIER — après `value_net`, dernier module que SB3 crée.
        # `nn.Module` énumère ses paramètres dans l'ordre d'enregistrement des sous-modules, et
        # l'optimiseur construit juste après suit `self.parameters()` : les paramètres de la tête
        # Q occupent donc les DERNIERS indices, et un zip sauvé sans elle charge ses états Adam
        # sur les mêmes indices qu'avant (`PatchedMaskablePPO.set_parameters`). Réassigner
        # `action_net` ci-dessus ne change pas SA position : `nn.Module.__setattr__` réécrit la
        # clé existante de `_modules`, qui garde son rang d'insertion. Verrouillé par test.
        self.adv_heads = PointerHeadNets(
            self.mlp_extractor.latent_dim_vf, self.entity_dim, self.weapon_dim,
            self.move_map_channels,
        ).to(self.device)
        # Même construction que `ActorCriticPolicy._build` : mêmes classe, mêmes kwargs, même
        # learning rate initial. `lr` passe par les kwargs (et non en argument nommé) parce que la
        # signature générique de `torch.optim.Optimizer` ne le déclare pas — SB3 y met un
        # `type: ignore`, ici le dict évite l'exception au typage sans rien changer à l'appel.
        optimizer_kwargs = dict(self.optimizer_kwargs)
        optimizer_kwargs["lr"] = lr_schedule(1)
        self.optimizer = lenient_optimizer_class(self.optimizer_class)(
            self.parameters(), **optimizer_kwargs
        )

    def load_state_dict(self, state_dict: Mapping[str, Any], strict: bool = True, assign: bool = False) -> Any:  # type: ignore[override]
        """Charge un `state_dict` SANS tête Q (antérieur à S14) comme s'il était complet.

        Le seul écart toléré : toutes les clés `adv_heads.*` absentes, aucune autre différence.
        La tête reste alors à son initialisation (zéro), donc `adv_heads.is_untrained()` — c'est
        ce que lisent `PatchedMaskablePPO.train` et `ai/train.py::arm_value_warmup` pour exiger
        l'échauffement avant qu'un acteur la lise. Tout autre écart suit le chemin strict de
        torch et lève comme avant : une clé de politique manquante n'est pas une antériorité,
        c'est une archive abîmée. Vaut pour TOUS les chemins de chargement (`set_parameters` de
        SB3 appelle cette méthode, en `strict=True`, depuis `MaskablePPO.load` nu comme depuis
        `PatchedMaskablePPO.load`).
        """
        if strict:
            expected = set(self.state_dict())
            got = set(state_dict)
            missing = expected - got
            if missing and all(is_adv_heads_key(k) for k in missing) and got <= expected:
                return super().load_state_dict(state_dict, strict=False, assign=assign)
        return super().load_state_dict(state_dict, strict=strict, assign=assign)

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
        # L'assemblage lit des CLÉS de l'observation en plus des features (bits de présence, de
        # cible désignée, de candidats de pose). Contrôlé AVANT l'extraction, sans quoi le
        # message ne serait jamais émis : `preprocess_obs` (SB3) tombe d'abord sur un `assert`,
        # qui disparaît sous `python -O` — et l'échec ressortirait alors trois appels plus loin,
        # en indexation de tenseur par une chaîne.
        if not isinstance(obs, dict):
            raise TypeError(
                "PointerMaskablePolicy lit des cles de l'observation et exige donc un espace "
                f"Dict (recu {type(obs).__name__})."
            )
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
        self_model_emb = features[:, self.self_model_slice].reshape(
            batch, self.n_self_models, self.entity_dim
        )
        # Emplacements d'arme de l'unité active. Largeur `weapon_dim` : c'est l'encodeur d'armes
        # partagé qui les produit, pas l'encodeur d'entités.
        weapon_emb = features[:, self.active_weapon_slice].reshape(
            batch, self.n_weapons, self.weapon_dim
        )
        # Y A-T-IL DES SLOTS DE POSE OUVERTS ? Lu sur le bit `present` des candidats — le MÊME
        # que l'extracteur prend pour masque (`deploy_cand_bin[..., -1]`), donc la question posée
        # ici et l'entité encodée là-bas ne peuvent pas diverger.
        #
        # C'ÉTAIT le bit `phase_deployment`, et c'était trop étroit : les ids 4-11 portent des
        # slots de pose dans DEUX situations, la phase de déploiement et l'ingress move d'une
        # escouade en réserves (20.04), qui est une mise en place et non un mouvement (03.02).
        # Router sur la phase laissait la seconde aux mains de la conv 1x1 des cellules de move,
        # aux cellules (0, 4..11) de la fenêtre égocentrique — des cellules sans aucun rapport
        # avec les hexes candidats, c'est-à-dire le défaut même que §0.44 avait corrigé pour le
        # déploiement seul. Le bit `present`, lui, dit exactement ce que le routage demande :
        # « le masque ouvre-t-il ici des slots de pose ? », sans nommer la phase qui les ouvre.
        #
        # Il ne peut valoir QUE 0 ou 1 : sa clé (`deploy_cand_bin`) est hors `norm_obs_keys`
        # (`ai/train._vec_norm_obs_keys` ne normalise que `global_cont`), précisément pour que
        # les valeurs discrètes gardent leur sémantique. S'il cessait de l'être — une clé ajoutée
        # à `VecNormalize`, un index décalé d'un champ — le routage des ids 4-11 deviendrait
        # arbitraire et l'agent jouerait des cellules de move pour des poses, sans que rien ne
        # lève. Le contrôle est là pour que ça lève.
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
        deploy_present = obs["deploy_cand_bin"][..., -1]
        if not bool(torch.all((deploy_present == 0.0) | (deploy_present == 1.0))):
            raise RuntimeError(
                "Le bit `present` des candidats de pose (`deploy_cand_bin[..., -1]`) n'est pas "
                f"binaire (valeurs {torch.unique(deploy_present).tolist()[:5]}) : le routage des "
                f"ids {DEPLOY_SLOT_BASE}-{DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT - 1} entre la tete "
                "de pose et la conv de move ne repose plus sur rien."
            )
        is_deploy = deploy_present.amax(dim=-1)
        # Deux bits LUS sur le tenseur ennemi, à leur index de schéma. Ils ne sont pas contrôlés
        # binaires comme l'est celui des candidats de pose : celui-là ROUTE (il choisit laquelle
        # de deux têtes alimente huit colonnes), et son contrôle coûte une synchronisation
        # GPU->hôte par forward. Ceux-ci PONDÈRENT, exactement comme les masques de présence que
        # l'extracteur applique déjà sans contrôle sur les six familles d'entités ; en ajouter
        # deux ici paierait deux synchronisations de plus par forward pour un mode de défaillance
        # que le reste du réseau ne surveille pas non plus.
        enemies_bin = obs["enemies_bin"]
        enemies_present = enemies_bin[..., _ENEMY_PRESENT_IDX]
        fight_target = enemies_bin[..., _FIGHT_TARGET_IDX]
        return PolicyFeatures(
            trunk, embeddings, move_map, decision_emb, deploy_emb, ally_emb, is_deploy,
            self_model_emb, weapon_emb, enemies_present, fight_target,
        )

    def _move_logits(
        self, latent_pi: torch.Tensor, move_map: torch.Tensor, nets: Optional[HeadNets] = None
    ) -> torch.Tensor:
        """Logits de cellule (B, 1024) — une conv 1x1 par colonne, conditionnée par le tronc.

        `nets` : le jeu de têtes lu (la politique elle-même par défaut, `adv_heads` pour la
        tête Q) ; la formule est la même, seuls les poids changent.

        ⚠️ ALIGNEMENT, c'est le point critique : `move_map` est indexée `[canal, gy, gx]`,
        comme la grille produite par `build_squad_grid`. Le `reshape` final parcourt donc `gy`
        puis `gx`, ce qui donne l'index `gy * GRID_SIZE + gx` — la définition EXACTE de
        `spatial_grid.cell_index`, celle que suivent le masque d'action et le décodeur. Une
        transposition ici ferait viser à l'agent une cellule et en jouer une autre, sans que rien
        ne lève. Verrouillé par `test_move_logit_is_cell_local` (pic injecté dans une cellule).
        """
        heads: HeadNets = self if nets is None else nets
        hidden = heads.move_cell_net(move_map) + heads.move_ctx_net(latent_pi)[:, :, None, None]
        return heads.move_out_net(torch.relu(hidden)).reshape(latent_pi.shape[0], MOVE_CELL_COUNT)

    def _point(
        self, query_net: nn.Linear, latent_pi: torch.Tensor, embeddings: torch.Tensor
    ) -> torch.Tensor:
        """Logits d'UNE famille pointée : `(q · e_i) / sqrt(d)`, (B, K).

        Mise à l'échelle 1/sqrt(d), comme une attention : sans elle la variance des logits croît
        avec la dimension d'embedding et la politique démarre quasi déterministe. Écrite ICI une
        seule fois — recopiée par famille, c'est l'oubli du diviseur sur une SEULE d'entre elles
        qui passerait inaperçu : les logits restent finis, la politique devient juste quasi
        déterministe sur cette famille-là et sur elle seule.

        `d` est LU sur les embeddings et non pris sur `entity_dim` : les emplacements d'arme sont
        pointés sur leurs embeddings d'encodeur d'ARMES, plus étroits (`weapon_dim`). Les six
        familles d'entités, elles, sortent en `entity_dim` — pour elles la valeur est la même
        qu'avant, au bit près.

        Les requêtes restent des modules DISTINCTS (cf. leurs déclarations) : ce qui est partagé
        ici est la formule, pas les poids.
        """
        return self._score(query_net(latent_pi), embeddings)

    @staticmethod
    def _score(query: torch.Tensor, embeddings: torch.Tensor) -> torch.Tensor:
        """`(q · e_i) / sqrt(d)` pour une requête DÉJÀ composée : (B, d) x (B, K, d) -> (B, K).

        Séparée de `_point` pour que la compatibilité arme x cible passe par le MÊME diviseur :
        le terme additif de `_weapon_target_bonus` est homogène à un logit de pointeur, et lui
        donner sa propre échelle rendrait le poids relatif des deux termes arbitraire.
        """
        return (query.unsqueeze(1) * embeddings).sum(dim=-1) / embeddings.shape[-1] ** 0.5

    def _weapon_target_bonus(
        self,
        proj_net: nn.Module,
        weapons: torch.Tensor,
        enemies: torch.Tensor,
        select: torch.Tensor,
        reduce_max: bool,
    ) -> torch.Tensor:
        """Terme de COMPATIBILITÉ arme x cible ajouté aux logits d'emplacement : (B, K_w).

        `compat[j, i] = (w_j · P e_i) / sqrt(d_w)` — la même forme et le même diviseur qu'un
        logit de pointeur, puisque c'en est le second terme (cf. la déclaration des projections).
        `select` (B, K_e) désigne les colonnes admissibles ; la réduction diffère selon ce que
        l'état SAIT de la cible, et c'est le seul point où les deux familles divergent :

        - **mêlée (`reduce_max=False`)** : la cible est DÉJÀ désignée (`squad_fight` a joué le
          `FIGHT_SLOT` avant d'armer `pending_fight_weapon_select`). `select` est le bit
          `fight_target_selected`, à 1 sur exactement une ligne, et la somme pondérée EXTRAIT
          cette ligne. Hors de ce point d'arrêt aucune ligne n'est marquée : le terme vaut zéro et
          le logit se réduit à la requête, sans branche ni garde de phase.
        - **tir (`reduce_max=True`)** : le split-fire choisit l'ARME AVANT la cible
          (`pending_weapon` est `None` quand le masque ouvre ces slots), donc aucune cible n'est
          désignée. La question devient « cette arme a-t-elle une bonne cible disponible ? », et
          c'est un `max` sur les ennemis PRÉSENTS. Le masque n'est pas décoratif : un slot absent
          a bien un embedding nul (`_encode_masked`), mais `proj_net` a un BIAIS — mesuré non nul
          à l'initialisation — donc sa compatibilité vaut `(w_j · b) / sqrt(d_w)`, une valeur
          arbitraire et non zéro. Sans le masque, des slots vides disputeraient le `max` aux
          vraies cibles.

        Ce que ce terme apporte et que le latent ne porte pas : le tronc ne voit les ennemis
        qu'agrégés (`enemies_agg`, moyenne + max sur 20 slots). Une compatibilité par PAIRE
        (arme, ennemi) n'est pas reconstructible depuis cette agrégation.
        """
        compat = torch.einsum(
            "bjd,bid->bji", weapons, proj_net(enemies)
        ) / weapons.shape[-1] ** 0.5
        keep = select > 0
        if not reduce_max:
            return (compat * keep.to(compat.dtype).unsqueeze(1)).sum(dim=2)
        best = compat.masked_fill(
            ~keep.unsqueeze(1), torch.finfo(compat.dtype).min
        ).max(dim=2).values
        # Aucun ennemi présent : le `max` rendrait la valeur de remplissage. Zéro est ici la
        # lecture exacte — « aucune cible ne recommande cette arme » —, et non un repli d'erreur.
        return best.masked_fill(~keep.any(dim=1, keepdim=True), 0.0)

    def _deploy_logits(
        self,
        latent_pi: torch.Tensor,
        move: torch.Tensor,
        feats: PolicyFeatures,
        nets: Optional[HeadNets] = None,
    ) -> torch.Tensor:
        """Remplace, QUAND LES IDS 4-11 SONT DES SLOTS DE POSE, les colonnes de cellules de move.

        `nets` : le jeu de têtes lu (la politique par défaut, `adv_heads` pour la tête Q).

        Les ids 4-11 portent deux significations : cellule de la grille égocentrique, ou slot de
        pose. Le masque le sait déjà (il n'ouvre jamais les deux familles dans le même état) ; la
        policy, elle, l'ignorait — ces logits sortaient donc de la conv 1x1, sur des cellules sans
        rapport avec les hexes candidats (§0.44).

        Le routage se fait sur la PRÉSENCE DE CANDIDATS et non sur la phase, et par `torch.where`
        — pas par une branche `if` : le batch mélange des observations d'états différents (n_envs)
        et une branche scalaire trancherait pour tout le lot d'après un seul échantillon. Router
        sur la phase de déploiement laissait dehors l'ingress move d'une escouade en réserves
        (20.04), qui est une mise en place et ouvre les mêmes slots en phase de MOUVEMENT.

        ⚠️ Quand aucun candidat n'est présent, ces colonnes DOIVENT rester celles de la conv : le
        bloc `deploy_cand_*` est alors nul, et router quand même donnerait 8 logits rigoureusement
        identiques (produit scalaire contre des embeddings nuls), donc un choix uniforme sur 8
        cellules parfaitement jouables en phase de mouvement.
        """
        heads: HeadNets = self if nets is None else nets
        pointer = self._point(heads.deploy_query_net, latent_pi, feats.deploy)
        low, high = DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT
        slots = torch.where(
            (feats.is_deploy > 0.5).unsqueeze(1), pointer, move[:, low:high]
        )
        return torch.cat([move[:, :low], slots, move[:, high:]], dim=1)

    def _action_logits(
        self, latent_pi: torch.Tensor, feats: PolicyFeatures, nets: Optional[HeadNets] = None
    ) -> torch.Tensor:
        """Logits complets, assemblés dans l'ordre des ids d'action.

        `nets` : le jeu de têtes lu — la politique elle-même par défaut (logits), `adv_heads`
        pour la tête Q (avantages attendus, sur `latent_vf`). Un seul assemblage pour les deux :
        c'est ce qui garantit qu'un avantage et un logit d'une même action lisent les mêmes
        entrées (entité pointée, colonne de cellule, compatibilité arme x cible).

        Onze têtes à poids partagés — conv 1x1 (cellules), pointeurs de tir, de charge (§9 P3-2),
        de mêlée (§9 P3-1) et d'Oath of Moment (chantier 01 : quatre requêtes, MÊMES embeddings
        d'ennemis), pointeur de décision (candidats `CHOICE_i`, §9.3 P2), pointeur de
        DÉPLOIEMENT (§0.44, qui écrase les colonnes 4-11 des cellules en phase de déploiement),
        pointeur d'ACTIVATION (V11 §0.48 `L2`, sur les embeddings ALLIÉS), pointeur de retrait de
        COHÉRENCE (P3-0, sur mes figurines) et les deux pointeurs d'EMPLACEMENT D'ARME (mêlée
        §0.69, tir P3-8, sur les profils de l'unité active, chacun augmenté de sa compatibilité
        arme x cible — cf. `_weapon_target_bonus`) — et UNE tête dense
        réduite à ses colonnes réellement lues (`DENSE_LOGIT_COUNT` = 37) : wait,
        fight-sans-cible, 20 slots de tir indirect et 15 intents de zone.

        ⚠️ L'assemblage suit l'ordre EXACT des ids (`macro_intents`) : 0-1023 cellules, 1024 wait,
        1025-1044 tir, 1045-1064 charge (cible unique), 1065-1254 charge-paires, 1255-1274 mêlée,
        1275 fight-sans-cible, 1276-1295 tir indirect, 1296-1310 zone, 1311-1316 CHOICE,
        1317-1336 Oath, 1337-1348 ACTIVATION, 1349-1358 arme CC, 1359-1378 cohérence,
        1379-1388 split-fire tir. Une permutation ici ferait jouer à l'agent une action autre que
        celle qu'il évalue, sans que rien ne lève — verrouillé par test.
        """
        heads: HeadNets = self if nets is None else nets
        enemies = feats.enemies
        ranged_weapons = feats.weapons[:, :SHOOT_WEAPON_SEL_SLOT_COUNT]
        melee_weapons = feats.weapons[:, SHOOT_WEAPON_SEL_SLOT_COUNT:]
        base = heads.action_net(latent_pi)
        move = self._deploy_logits(
            latent_pi, self._move_logits(latent_pi, feats.move_map, heads), feats, heads
        )
        return torch.cat(
            [
                move,
                base[:, :1],        # wait
                self._point(heads.query_net, latent_pi, enemies),           # tir
                self._point(heads.charge_query_net, latent_pi, enemies),    # charge (cible unique)
                heads.charge_pair_net(latent_pi),                           # charge paires (dense)
                self._point(heads.fight_query_net, latent_pi, enemies),     # mêlée
                base[:, 1:],        # fight-sans-cible, shoot-indirect, intents de zone
                self._point(heads.choice_query_net, latent_pi, feats.decision),
                self._point(heads.oath_query_net, latent_pi, enemies),      # Oath
                # Activation : MES escouades par slot (V11 §0.48 `L2`).
                self._point(heads.activate_query_net, latent_pi, feats.allies),
                # Arme CC (V11 §0.69) : emplacements de MÊLÉE de l'unité active, second bloc
                # du tenseur d'armes — les profils de tir occupent le premier. Le second terme
                # confronte chaque arme à la cible DÉJÀ désignée.
                self._point(
                    heads.fight_weapon_query_net, latent_pi, melee_weapons
                ) + self._weapon_target_bonus(
                    heads.fight_weapon_target_net,
                    melee_weapons,
                    enemies,
                    feats.fight_target,
                    reduce_max=False,
                ),
                # Retrait cohérence : figurines de l'unité active par slot (P3-0).
                self._point(heads.coherency_query_net, latent_pi, feats.self_models),
                # Split-fire tir (P3-8) : emplacements de TIR, premier bloc du tenseur d'armes.
                # Le second terme confronte chaque arme à la MEILLEURE cible encore présente —
                # aucune n'est désignée à ce point d'arrêt.
                self._point(
                    heads.shoot_weapon_sel_query_net, latent_pi, ranged_weapons
                ) + self._weapon_target_bonus(
                    heads.shoot_weapon_target_net,
                    ranged_weapons,
                    enemies,
                    feats.enemies_present,
                    reduce_max=True,
                ),
            ],
            dim=1,
        )

    def expected_advantages(self, latent_vf: torch.Tensor, feats: PolicyFeatures) -> torch.Tensor:
        """Avantages attendus `A(s, ·)` de la tête Q, (B, TOTAL_ACTION_SIZE), sur le tronc CRITIC.

        Même assemblage que les logits, autres poids, autre tronc : la tête Q lit `latent_vf`
        et non `latent_pi`, comme `value_net` — c'est une quantité de VALEUR, pas de décision,
        et l'acteur ne doit pas pouvoir la déformer par son propre tronc.
        """
        return self._action_logits(latent_vf, feats, self.adv_heads)

    def _distribution_from(
        self,
        latent_pi: torch.Tensor,
        feats: PolicyFeatures,
        action_masks: Optional[np.ndarray],
    ) -> MaskableCategoricalDistribution:
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
        if not hasattr(self, 'action_dist'):
            # Worker Phase 3 : action_dist retiré du dict avant sérialisation (patched_ppo.py)
            # pour éviter les tenseurs non-leaf. On le recrée ici depuis l'action_space.
            self.action_dist = make_masked_proba_distribution(self.action_space)
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
        lirait ici. Le contrôle du bit `present` des candidats de pose reste sur le chemin
        ACTEUR, le seul qui route sur lui.
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

    def evaluate_actions_q(
        self,
        obs: PyTorchObs,
        actions: torch.Tensor,
        action_masks: Optional[Any] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor], torch.Tensor, torch.Tensor]:
        """`evaluate_actions` + l'avantage attendu CENTRÉ de l'action JOUÉE :
        (values, log_prob, entropy, adv, offset).

        `adv` (B,) = `A_c(s_t, a_t)` = `A(s_t, a_t) − Σ_a π(a|s_t)·A(s_t, a)` (voir
        `center_under_policy` : cause mesurée, pourquoi π), relié au graphe :
        `PatchedMaskablePPO.train` en fait la cible de régression `Q = V.detach() + adv` contre
        le retour λ, et le DÉTACHE avant de le donner à l'acteur. `offset` (B,) : la constante
        par état retirée, DÉTACHÉE, pour le tag `train/adv_q_offset_abs_mean`. Les probabilités
        sont celles de la politique COURANTE (recalculées à chaque mini-lot) alors que `a_t` a
        été tirée sous celle du rollout : le buffer ne garde que `old_log_prob` de l'action
        jouée, et l'écart entre les deux est borné par le clip et la coupure KL. Une seule passe
        avant pour les deux têtes : `feats` et les deux troncs sont calculés une fois.
        `actions` : ids d'action (B,), entiers.
        """
        feats = self._split_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(feats.trunk)
        distribution = self._distribution_from(latent_pi, feats, action_masks)
        adv_all = self.expected_advantages(latent_vf, feats)
        adv_centered, offset = center_under_policy(adv_all, masked_probs(distribution).detach())
        adv = adv_centered.gather(1, actions.long().view(-1, 1)).squeeze(1)
        return (
            self.value_net(latent_vf),
            distribution.log_prob(actions),
            distribution.entropy(),
            adv,
            offset.detach(),
        )
