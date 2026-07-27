#!/usr/bin/env python3
"""Schéma UNIFIÉ d'entité pour l'observation squad (V11 §0.30 — tranche T-D).

L'observation n'est plus un vecteur PLAT où chaque slot ennemi possède ses propres poids de
première couche (`V11_entity_encoder_pointer.md` §1.8 : 640 paramètres par dimension). Elle est
un jeu de **tenseurs d'entités** : chaque unité — la mienne, mes alliées, les ennemies — est
décrite par le **MÊME** schéma de features, encodée par le **MÊME** réseau, et le réseau
généralise donc d'un slot à l'autre (§3.3).

Ce module est la SOURCE UNIQUE du schéma :
- `UNIT_CONT_FIELDS` / `UNIT_BIN_FIELDS` : l'ordre des features d'une unité ;
- `MODEL_TYPE_*` : le sous-registre « types de figurines » d'une unité ;
- `SELF_MODEL_*` : le sous-registre « mes figurines » (positions et engagement individuels) ;
- les profils d'armes viennent de `observation_weapon_profiles` (déjà partagé §9.2.5).

Le code de lecture (tests, outillage) passe par `unit_cont_index("nom")` plutôt que par des
index recopiés : c'est ce qui a permis aux tests d'observation de survivre à §9.2.5 sans
modification, et l'équivalent doit exister pour le format entité (§4 T-D).

⚠️ **Features propres à l'unité ACTIVE** (§3.3 : « les features propres à un camp sont à zéro
pour l'autre, avec leur masque ») : les compteurs d'engagement et les drapeaux de terrain ne
sont émis que pour l'unité observée ; leur masque est le bit `is_active`. Les remplir pour les
25 autres entités exigerait un test d'empreinte par figurine et par entité à chaque step — le
poste dominant du coût d'observation (§1.8) — pour une information que la grille égocentrique
porte déjà en partie.
"""

from __future__ import annotations

from typing import Dict, Tuple

#: Clé du cache des sous-tenseurs d'armes dans le `game_state`
#: (posée par `ObservationBuilder._encode_entity_weapons`, vidée par `build_units_cache`).
#: Elle vit ici — module feuille, sans dépendance — pour que les deux côtés lisent la MÊME
#: constante : en deux littéraux, une renommée d'un seul côté laisserait un cache jamais
#: invalidé, donc des armes du roster précédent observées après une rotation.
WEAPON_PROFILE_CACHE_KEY = "_obs_weapon_profiles_cache"

# ---------------------------------------------------------------------------
# Unité (ami ou ennemi — MÊME schéma, cf. §3.3)
# ---------------------------------------------------------------------------

#: Features CONTINUES d'une unité, dans l'ordre d'émission.
UNIT_CONT_FIELDS: Tuple[str, ...] = (
    "alive_models",        # effectif vivant
    "hp_total",            # PV cumulés vivants
    "value_alive",         # VALUE cumulée vivante (somme par figurine)
    "oc_total",            # OC cumulé
    "model_count_ratio",   # effectif vivant / effectif de départ
    "wounded_hp_ratio",    # PV de la figurine entamée / son HP_MAX (1.0 si aucune)
    "col_rel",             # figurine la plus proche du centroïde OBSERVATEUR (subhex bruts)
    "row_rel",
    "edge_distance",       # distance bord-à-bord escouade↔escouade depuis l'unité active
    "move",                # profil de datasheet
    "hp_max",
    "toughness",
    "armor_save",
    "invul_save",
    "moved_max",           # distance géodésique parcourue ce tour : max sur l'escouade
    "moved_sum",           # … et somme
    "n_fight_eligible",    # ⚠ unité ACTIVE uniquement (masque = is_active)
    "n_in_enemy_ez",       # ⚠ unité ACTIVE uniquement
    "n_relayed_ez",        # ⚠ unité ACTIVE uniquement
)

#: Règles d'UNITÉ (`config/unit_rules.json`) exposées à l'agent, dans l'ordre d'émission.
#:
#: Ne figurent ici que les règles à EFFET RÉEL — même critère que les règles d'armes, qui
#: exclut délibérément [INDIRECT FIRE] : un bit pour une règle inerte est du bruit pur.
#: Vérifié par lecture le 2026-07-27 : chacune est consultée dans un handler vif.
#:
#: Ce sont les EFFETS, pas les capacités nommées. `unit_has_rule_effect` résout les règles
#: SOURCES vers eux, donc les 13 bits couvrent aussi les capacités composites des datasheets —
#: vérifié sur les unités réelles : `cunning_hunters` → shoot_after_advance + shoot_after_flee,
#: `targeted_intercession` → les deux rerolls to-wound, `adaptable_predators` et
#: `target_priority` → charge_after_flee + shoot_after_flee, `aggression_imperative` →
#: reroll_1_tohit_fight, `preservation_imperative` → reroll_1_save_fight. Exposer les sources
#: EN PLUS serait redondant ; n'exposer que les sources manquerait les règles directes.
#:
#: Absents : les marqueurs de RÔLE (`leader`, `sergeant`, `support`, `special_weapon`) — le
#: sous-registre « types de figurines » les porte déjà en one-hot ; et `adrenalised_onslaught`,
#: qui n'est pas une règle mais un CHOIX de joueur (Aggression OU Preservation Imperative, au
#: début de la phase de combat) : sans le mécanisme générique de décision agent (P2), elle ne
#: produit aujourd'hui aucun effet — candidate à une tranche P3, pas à un bit d'observation.
#:
#: Ces bits décrivent l'union EN VIGUEUR (19.04) : une escouade menée par un character porte
#: les règles de son leader et les perd à sa mort. C'était le sens même du trou fermé ici —
#: l'agent subissait ces règles, chez lui comme chez l'ennemi, sans jamais les percevoir : le
#: pipeline squad n'avait aucun champ de règle d'unité, et `unit_has_rule_effect` n'était
#: appelée que par `build_observation`, le pipeline mono-figurine legacy.
UNIT_RULE_EFFECT_IDS: Tuple[str, ...] = (
    "charge_after_advance",
    "charge_after_flee",
    "charge_impact",
    "closest_target_penetration",
    "move_after_shooting",
    "reactive_move",
    "reroll_1_save_fight",
    "reroll_1_tohit_fight",
    "reroll_1_towound",
    "reroll_charge",
    "reroll_towound_target_on_objective",
    "shoot_after_advance",
    "shoot_after_flee",
)

#: Drapeaux d'une unité, dans l'ordre d'émission.
UNIT_BIN_FIELDS: Tuple[str, ...] = (
    "present",             # masque d'entité (0 = slot vide / unité morte)
    "is_ally",             # 1 = mon camp, 0 = ennemi
    "is_active",           # 1 = l'unité observée (masque des features ci-dessus)
    "moved",
    "shot",
    "fought",
    "advanced",
    "fled",
    "coherent",
    "engaged",             # dans la zone d'engagement d'une unité ADVERSE de cette unité
    "hidden",              # ⚠ unité ACTIVE uniquement (13.09)
    "gone_to_ground",      # ⚠ unité ACTIVE uniquement (13.5)
    "in_cover",            # ⚠ unité ACTIVE uniquement (13.08)
    "deploy_not_on_board",  # one-hot mise en place (source `deployed_on_turn`)
    "deploy_pre_battle",
    "deploy_in_battle",
    "deployed_this_turn",  # clause 2 de [HEAVY] 24.16
) + tuple(f"rule_{rule_id}" for rule_id in UNIT_RULE_EFFECT_IDS)

UNIT_CONT_SIZE = len(UNIT_CONT_FIELDS)
UNIT_BIN_SIZE = len(UNIT_BIN_FIELDS)

_UNIT_CONT_INDEX: Dict[str, int] = {name: i for i, name in enumerate(UNIT_CONT_FIELDS)}
_UNIT_BIN_INDEX: Dict[str, int] = {name: i for i, name in enumerate(UNIT_BIN_FIELDS)}


def unit_cont_index(field: str) -> int:
    """Index d'une feature continue d'unité. Nom inconnu -> KeyError explicite."""
    if field not in _UNIT_CONT_INDEX:
        raise KeyError(
            f"Feature continue d'unité inconnue : {field!r}. Champs : {UNIT_CONT_FIELDS}"
        )
    return _UNIT_CONT_INDEX[field]


def unit_bin_index(field: str) -> int:
    """Index d'un drapeau d'unité. Nom inconnu -> KeyError explicite."""
    if field not in _UNIT_BIN_INDEX:
        raise KeyError(
            f"Drapeau d'unité inconnu : {field!r}. Champs : {UNIT_BIN_FIELDS}"
        )
    return _UNIT_BIN_INDEX[field]


# ---------------------------------------------------------------------------
# Sous-registre « types de figurines » d'une unité
# ---------------------------------------------------------------------------

MODEL_TYPE_CONT_FIELDS: Tuple[str, ...] = (
    "hp_max", "toughness", "armor_save", "invul_save", "alive_count",
)
#: 4 rôles d'allocation (règle 19) en one-hot + le masque de slot. Aucun bit = figurine de base.
MODEL_TYPE_BIN_FIELDS: Tuple[str, ...] = (
    "role_special_weapon", "role_sergeant", "role_support", "role_leader", "present",
)
MODEL_TYPE_CONT_SIZE = len(MODEL_TYPE_CONT_FIELDS)
MODEL_TYPE_BIN_SIZE = len(MODEL_TYPE_BIN_FIELDS)


# ---------------------------------------------------------------------------
# Sous-registre « mes figurines » (irréductiblement individuel, unité active seule)
# ---------------------------------------------------------------------------

SELF_MODEL_CONT_FIELDS: Tuple[str, ...] = ("col_rel", "row_rel")
SELF_MODEL_BIN_FIELDS: Tuple[str, ...] = ("fight_eligible", "in_enemy_ez", "ez_relayed_by_ally")
SELF_MODEL_CONT_SIZE = len(SELF_MODEL_CONT_FIELDS)
SELF_MODEL_BIN_SIZE = len(SELF_MODEL_BIN_FIELDS)


# ---------------------------------------------------------------------------
# Contexte global (ce qui n'appartient à aucune entité)
# ---------------------------------------------------------------------------

#: Nombre d'objectifs décrits par le contexte global. DOIT valoir `macro_intents.MAX_OBJECTIVES`
#: (l'action space offre 3 intents de zone par objectif) — verrouillé par test de contrat.
N_OBJECTIVE_SLOTS = 5

GLOBAL_CONT_FIELDS: Tuple[str, ...] = (
    "turn", "episode_steps", "my_victory_points", "enemy_victory_points",
    "my_value_ratio", "enemy_value_ratio",
    # Distance de l'escouade OBSERVATRICE à chaque objectif, en subhex bruts (hex le plus proche
    # de la zone). Sans elle, un objectif hors de la grille égocentrique — dont la demi-étendue
    # vaut le budget d'Advance, soit 12" mesuré sur le board x5 — n'existe nulle part dans
    # l'observation, alors que 15 actions de zone le désignent : mesuré au reset, 1 à 2
    # objectifs sur 5 seulement tombent dans la fenêtre. L'agent choisissait une destination
    # qu'il ne percevait pas.
    "objective_distance_0", "objective_distance_1", "objective_distance_2",
    "objective_distance_3", "objective_distance_4",
)
#: `phase` est un scalaire ordonné dans [0,1] : il vit avec les drapeaux car il ne doit JAMAIS
#: être normalisé par des statistiques glissantes (V11 §9.5). Les sin/cos de direction
#: d'objectif sont ici pour la MÊME raison : déjà bornés dans [-1,1] et centrés, les passer à
#: `VecNormalize` ne ferait qu'amplifier leur bruit.
GLOBAL_BIN_FIELDS: Tuple[str, ...] = (
    "is_my_turn", "phase",
    "objective_control_0", "objective_control_1", "objective_control_2",
    "objective_control_3", "objective_control_4",
    "objective_present_0", "objective_present_1", "objective_present_2",
    "objective_present_3", "objective_present_4",
    # Direction de l'escouade observatrice vers l'objectif (vecteur unitaire dans l'espace
    # projeté `_hex_center`, celui de la grille et du rendu). La distance seule ne dit pas où
    # aller ; c'est le couple des deux qui rend un objectif hors fenêtre navigable.
    "objective_dir_cos_0", "objective_dir_sin_0",
    "objective_dir_cos_1", "objective_dir_sin_1",
    "objective_dir_cos_2", "objective_dir_sin_2",
    "objective_dir_cos_3", "objective_dir_sin_3",
    "objective_dir_cos_4", "objective_dir_sin_4",
)
GLOBAL_CONT_SIZE = len(GLOBAL_CONT_FIELDS)
GLOBAL_BIN_SIZE = len(GLOBAL_BIN_FIELDS)

_GLOBAL_CONT_INDEX: Dict[str, int] = {name: i for i, name in enumerate(GLOBAL_CONT_FIELDS)}
_GLOBAL_BIN_INDEX: Dict[str, int] = {name: i for i, name in enumerate(GLOBAL_BIN_FIELDS)}


def global_cont_index(field: str) -> int:
    """Index d'une feature continue globale. Nom inconnu -> KeyError explicite."""
    if field not in _GLOBAL_CONT_INDEX:
        raise KeyError(
            f"Feature continue globale inconnue : {field!r}. Champs : {GLOBAL_CONT_FIELDS}"
        )
    return _GLOBAL_CONT_INDEX[field]


def global_bin_index(field: str) -> int:
    """Index d'un drapeau global. Nom inconnu -> KeyError explicite."""
    if field not in _GLOBAL_BIN_INDEX:
        raise KeyError(
            f"Drapeau global inconnu : {field!r}. Champs : {GLOBAL_BIN_FIELDS}"
        )
    return _GLOBAL_BIN_INDEX[field]
