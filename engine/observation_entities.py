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
    # ⚠ Entités ENNEMIES uniquement (comme `los_can_see` / `cover_vs_observer`) : c'est une
    # grandeur de PAIRE (mon escouade → cette cible), pas une propriété de la cible.
    #
    # Combien de MES figurines vivantes sont engagées avec cette escouade (04.02), donc
    # combien peuvent réellement porter des attaques contre elle. V11 §9 P3-1 a fait de la
    # cible de mêlée une décision de l'agent ; sans ce champ, la tête pointeur choisirait
    # une cible sans savoir avec quelle FORCE elle serait frappée — or c'est le premier
    # facteur du choix : engagée par 8 figurines ou par 1, la même cible ne vaut pas la même
    # chose. `n_fight_eligible` ne le dit pas : il agrège sur toutes les cibles à la fois.
    # `edge_distance` non plus : la distance à l'escouade ne dit rien du nombre de figurines
    # qui atteignent l'ennemi (05.03/04.02 s'évaluent par figurine, pas par ancre).
    "n_models_engaging",
)

#: Règles d'UNITÉ (`config/unit_rules.json`) exposées à l'agent.
#:
#: Ne figurent ici que les règles à EFFET RÉEL — même critère que les règles d'armes, qui
#: exclut délibérément [INDIRECT FIRE] : exposer une règle inerte est du bruit pur.
#: Vérifié par lecture le 2026-07-27 : chacune est consultée dans un handler vif.
#:
#: Ce sont les EFFETS, pas les capacités nommées. `unit_has_rule_effect` résout les règles
#: SOURCES vers eux, donc ces 13 entrées couvrent aussi les capacités composites des datasheets —
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
#: produit aujourd'hui aucun effet — candidate à une tranche P3, pas à une capacité observée.
#:
#: Elles décrivent l'union EN VIGUEUR (19.04) : une escouade menée par un character porte les
#: règles de son leader et les perd à sa mort. C'était le sens même du trou fermé ici —
#: l'agent subissait ces règles, chez lui comme chez l'ennemi, sans jamais les percevoir : le
#: pipeline squad n'avait aucun champ de règle d'unité, et `unit_has_rule_effect` n'était
#: appelée que par le pipeline mono-figurine legacy (359-d), supprimé depuis.
#:
#: ⚠️ Ce tuple n'ordonne PLUS rien dans l'observation (chantier 01) : les capacités y sont
#: écrites en `obs_id` triés croissant (`UNIT_ABILITY_SLOTS` ci-dessous), pas en bits positionnels.
#: Il reste le VOCABULAIRE — la liste de ce qui est observable — et il sert tel quel au
#: registre de candidats de décision (`DECISION_OPTION_BIN_FIELDS`), où le nombre de types
#: reste petit et fixe.
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
#: CONVENTION (uniforme depuis §0.37) : le masque `present` est le DERNIER champ de CHAQUE
#: registre (unités, figurines self, armes, types) — il était ici en premier, seule exception,
#: et les lecteurs positionnels (`[..., 0]` vs `[..., -1]`) portaient deux conventions.
UNIT_BIN_FIELDS: Tuple[str, ...] = (
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
    # ⚠ Entités ENNEMIES uniquement (masque = `present` ET NON `is_ally`) : ces deux bits
    # décrivent une PAIRE (l'unité observatrice → cette entité), pas l'entité seule. Ils n'ont
    # aucun sens pour une alliée, et pour l'unité active la question n'est pas définie (contre
    # quel tireur ?) — son couvert intrinsèque, lui, reste porté par `in_cover`.
    #
    # Source : `compute_unit_los(observateur, cible)`, la source AUTORITATIVE du moteur — la
    # même que la résolution du `-1 BS` (`_cover_worsened_bs`) et que l'affichage frontend.
    # Ne PAS réimplémenter ici la branche « toutes mes figurines dans une terrain area » de
    # 13.08 : elle ne couvre qu'une des deux conditions alternatives, donc un bit à 0 voudrait
    # dire « indéterminé » au lieu de « pas de couvert ».
    "los_can_see",          # 06.01 : ≥ 1 figurine de la cible visible depuis l'observateur
    "cover_vs_observer",    # 13.08 EXACT : la cible a le bénéfice du couvert contre mon tir
    # ⚠ Entité ENNEMIE et phase de CHARGE uniquement (masque = `phase_charge` du contexte
    # global). V11 §9 P3-2 a fait de la cible de charge une décision de l'agent ; la tête
    # pointeur scorerait sinon des cibles sans savoir laquelle est ATTEIGNABLE.
    #
    # 1 ssi il existe un plan de charge LÉGAL vers cette cible au jet MAXIMAL (11.02 : 2D6, donc
    # 12"). À 0, déclarer la charge est perdu d'avance quel que soit le jet — l'unité perd son
    # activation entière. Rien d'autre ne le dit : `edge_distance` mesure une distance à vol
    # d'oiseau et ignore les trois causes réelles d'échec structurel — aucune case libre au
    # contact (cible encerclée ou collée à un mur), ER d'une escouade NON ciblée qui interdit le
    # placement (11.04 AFTER MOVING), et surtout la pénalité de descente 13.06, qui retranche du
    # jet une hauteur que l'observation n'expose nulle part.
    #
    # L'oracle est `charge_build_valid_plan`, la fonction MOTEUR qu'exécute le commit : une
    # réimplémentation annoncerait une atteignabilité que la résolution ne produirait pas.
    "charge_reachable_max_roll",
    "present",             # masque d'entité (0 = slot vide / unité morte) — DERNIER, cf. ci-dessus
)

UNIT_CONT_SIZE = len(UNIT_CONT_FIELDS)
UNIT_BIN_SIZE = len(UNIT_BIN_FIELDS)

# ---------------------------------------------------------------------------
# Capacités et statuts d'une unité — ENSEMBLES D'IDENTIFIANTS (chantier 01)
# ---------------------------------------------------------------------------
#
# Les 13 bits `rule_<id>` ont vécu dans `UNIT_BIN_FIELDS` jusqu'au chantier 01. Le schéma
# grossissait LINÉAIREMENT avec le nombre de capacités du jeu : chaque capacité ajoutée changeait
# `UNIT_BIN_SIZE`, donc `obs_size`, donc invalidait tout modèle entraîné (`retrain --new`). Les
# 17 capacités Armageddon auraient coûté 17 × 28 = 476 scalaires et un retrain, et chaque faction
# ultérieure un retrain de plus.
#
# Une unité porte désormais deux ENSEMBLES D'ENTIERS (`obs_id`, registres `config/unit_rules.json`
# et `config/unit_statuses.json`), lus comme des lignes de deux `EmbeddingBag` distinctes
# (`ai/spatial_extractor.py`). Ajouter une capacité, un statut ou une faction entière ne change
# alors NI `obs_size`, NI le nombre de paramètres du réseau.
#
# ⚠️ Aucun one-hot n'est jamais matérialisé : un `EmbeddingBag` fait une LECTURE DE LIGNE. C'est
# ce qui rend la longueur du vecteur indépendante du nombre de capacités existantes.
#
# DEUX tables, pas une : « cette unité a Feel No Pain » et « cette unité est la cible Oath
# adverse » ne sont pas de même nature. Un pooling commun les additionnerait dans le même espace
# et le réseau ne pourrait plus les distinguer.
#
# Pooling SOMME (côté réseau) : invariant par permutation — {A, B} écrit (slot0, slot1) ou
# (slot1, slot0) donne le même vecteur, la propriété qui disqualifiait les slots naïfs — et il
# préserve la MULTIPLICITÉ, là où la moyenne confondrait un ensemble de 1 et un de 3.
#
# Les ids sont malgré tout écrits TRIÉS CROISSANT : le pooling rend l'ordre indifférent au
# réseau, pas au debug. Sans tri, l'observation ne serait plus reproductible bit à bit d'un run
# à l'autre et les diffs de replay deviendraient illisibles.

#: Capacités EN VIGUEUR (19.04) portées par une unité.
#:
#: DEUX chiffres, et il faut les distinguer — ce slot garde un chemin de crash dur (débordement
#: = `raise`), donc sa marge doit être lue sur la MESURE, pas sur la projection :
#:
#: - **Mesuré le 2026-08-04 sur le dépôt réel** (`UnitRegistry` + `unit_has_rule_effect` sur les
#:   13 effets, 179 datasheets, puis les unions 19.04 légales — 70 paires et 50 trios
#:   bodyguard + leader + support validés par les règles d'attachement 19.01/24.22/24.34) :
#:   **2** effets au maximum par datasheet, **3** au maximum en vigueur sur une entité
#:   (`AssaultIntercessor + CaptainPowerWeaponBolter [+ Ancient]` → `reroll_1_towound`,
#:   `reroll_charge`, `reroll_towound_target_on_objective`). Marge actuelle : 5 slots.
#: - **Projeté** une fois les 17 capacités Armageddon livrées (chantier 06) : 6 en vigueur sur
#:   une même entité (`Boyz + Warboss + Painboy` → Get da Good Bitz, Might Is Right, Da Biggest
#:   and da Best, Dok's Toolz, Hold Still and Say Aargh, Grot Orderly ;
#:   `Intercessor + Captain Relic Shield + Ancient` → Objective Secured, Hail of Bolts, Finest
#:   Hour, Rites of Battle, Relic Banner, Unbreakable Resolve). Ces capacités N'EXISTENT PAS
#:   encore dans le moteur : c'est une projection de la conception du chantier 06, pas une mesure.
#:
#: 8 et non 6 : dimensionner sur la projection laisserait ZÉRO marge le jour où elle se réalise —
#: une seule capacité ajoutée à une figurine rattachée ferait déborder. 8 coûte 2 × 28 = 56
#: scalaires (0,3 % de l'observation) pour supprimer un mode de défaillance dur.
#: ⚠️ À rouvrir au chantier 06 : c'est lui qui rendra la projection mesurable.
#:
#: ⚠️ Débordement = ERREUR, jamais troncature (`observation_builder`) : tronquer ferait subir à
#: l'agent des règles qu'il ne perçoit pas — exactement le trou que V11 §0.30 avait fermé.
#:
#: ⚠️ Les effets de FACTION n'entrent PAS ici (chantier 03) : Waaagh! accorde quatre effets
#: identiques à TOUTES les unités orkes. Les inscrire par unité, c'est répéter 4 ids sur 28
#: entités et faire déborder les slots pour zéro information — le réseau reconstitue l'effet à
#: partir de « cette unité est orke » + « Waaagh! actif », deux informations GLOBALES. Ils vont
#: donc dans `GLOBAL_BIN_FIELDS`.
UNIT_ABILITY_SLOTS = 8

#: Statuts EN VIGUEUR portés par une unité (`battle_shock`, `oath_target`, `suppressed`).
#: Déclarés ici AVANT leurs chantiers respectifs (02, 03, 06) : c'est ce qui garantit qu'aucun
#: d'eux ne retouchera `obs_size`, donc qu'un SEUL retrain clôt la séquence.
UNIT_STATUS_SLOTS = 4

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

#: ⚠️ `col_rel` / `row_rel` sont exprimés dans la projection `_hex_center` — la MÊME que la
#: grille égocentrique et que les directions d'objectif (V11 §0.32 T-I). Ce ne sont PAS des
#: différences de coordonnées offset : en offset, deux voisins hexagonaux de parités de ligne
#: différentes n'ont pas la même norme, et l'observation portait alors deux géométries.
SELF_MODEL_CONT_FIELDS: Tuple[str, ...] = ("col_rel", "row_rel")
#: `present` est le masque de ce bloc, et il est EXPLICITE (V11 §0.32 T-H) : une figurine posée
#: sur le centroïde arrondi et sans aucun drapeau a une ligne entièrement nulle, donc un masque
#: déduit de la ligne (`(|cont| + |bin|) > 0`) la comptait ABSENTE — effectif faux servi sans
#: erreur, dans l'agrégation comme dans le dénominateur de `EntityRunningNorm`. Il est en DERNIÈRE
#: position, comme les masques des registres d'armes et de types (`[..., -1]`).
SELF_MODEL_BIN_FIELDS: Tuple[str, ...] = (
    "fight_eligible", "in_enemy_ez", "present",
)
SELF_MODEL_CONT_SIZE = len(SELF_MODEL_CONT_FIELDS)
SELF_MODEL_BIN_SIZE = len(SELF_MODEL_BIN_FIELDS)

_SELF_MODEL_CONT_INDEX: Dict[str, int] = {n: i for i, n in enumerate(SELF_MODEL_CONT_FIELDS)}
_SELF_MODEL_BIN_INDEX: Dict[str, int] = {n: i for i, n in enumerate(SELF_MODEL_BIN_FIELDS)}


def self_model_cont_index(field: str) -> int:
    """Index d'une feature continue de figurine. Nom inconnu -> KeyError explicite."""
    if field not in _SELF_MODEL_CONT_INDEX:
        raise KeyError(
            f"Feature continue de figurine inconnue : {field!r}. "
            f"Champs : {SELF_MODEL_CONT_FIELDS}"
        )
    return _SELF_MODEL_CONT_INDEX[field]


def self_model_bin_index(field: str) -> int:
    """Index d'un drapeau de figurine. Nom inconnu -> KeyError explicite."""
    if field not in _SELF_MODEL_BIN_INDEX:
        raise KeyError(
            f"Drapeau de figurine inconnu : {field!r}. Champs : {SELF_MODEL_BIN_FIELDS}"
        )
    return _SELF_MODEL_BIN_INDEX[field]


# ---------------------------------------------------------------------------
# Décision agent (V11 §9.3 — P2, mécanisme générique « décision agent »)
# ---------------------------------------------------------------------------

#: Types de points de décision exposés à l'agent, ordre FIGÉ du one-hot de contexte.
#: Une seule entrée aujourd'hui (`rule_choice`, le pilote P3 point 0) ; les tranches P3
#: suivantes (cible de mêlée, allocation de pertes…) s'ajoutent ICI, jamais en dupliquant le
#: mécanisme. Ajouter un type change `DECISION_CTX_BIN_SIZE`, donc `obs_size` : retrain `--new`.
AGENT_DECISION_TYPE_IDS: Tuple[str, ...] = ("rule_choice",)

#: Nombre MAXIMAL de candidats exposés à l'agent — le K de `CHOICE_0..K-1`
#: (`macro_intents.CHOICE_SLOTS`). Il vaut 6, l'alignement retenu par §9.3 sur les 6 slots
#: figurines. ⚠️ Ce n'est PAS une troncature silencieuse : une décision qui présenterait plus de
#: K candidats LÈVE (`agent_decision.set_pending_agent_decision`), conformément à la réserve 2 de
#: §9.0bis — une décision à grand espace se paramètre en INTENTIONS scorées, pas en top-K tronqué.
MAX_DECISION_OPTIONS = 6

#: Contexte de la décision (ce qui n'appartient à aucun candidat). Discret : jamais normalisé.
#: `decision_pending` vaut 0 tant qu'aucune décision n'est en attente POUR L'OBSERVATEUR — c'est
#: le masque du bloc entier, et l'unique bit qui distingue « pas de décision » de « décision de
#: type 0 ». Le nombre de candidats n'y figure pas : il est porté, candidat par candidat, par le
#: masque `present` du registre ci-dessous.
DECISION_CTX_BIN_FIELDS: Tuple[str, ...] = ("decision_pending",) + tuple(
    f"decision_type_{decision_type}" for decision_type in AGENT_DECISION_TYPE_IDS
)

#: Un CANDIDAT de décision, MÊME schéma pour tous les types (comme une unité, cf. §3.3) : c'est
#: ce qui permet à un encodeur PARTAGÉ de le lire et à la tête pointeur de le scorer, donc au
#: réseau de généraliser d'un slot de candidat à l'autre.
#:
#: Pour `rule_choice`, un candidat EST la règle qu'il accorde : le décrire par le one-hot de son
#: effet (le MÊME vocabulaire `UNIT_RULE_EFFECT_IDS` que les capacités d'unité, §0.31) dit à
#: l'agent CE QU'IL GAGNE. Un index de candidat, lui, ne dit rien : l'ordre des options dépend
#: du prompt.
#:
#: ⚠️ Ce bloc reste POSITIONNEL — un bit par effet — là où les capacités d'unité sont passées aux
#: ensembles d'`obs_id` (chantier 01). Ce n'est PAS un oubli de migration : un candidat de
#: décision accorde UN effet, jamais un ensemble, et il n'y a que `MAX_DECISION_OPTIONS = 6`
#: candidats — le registre coûte 14 bits UNE fois, pas 14 par entité, et il ne grossit que si un
#: type de décision nouveau élargit le vocabulaire. Le migrer aux ids ferait bouger `obs_size`
#: pour ~0 scalaire gagné, donc coûterait le retrain `--new` que le gel de §01 existe pour éviter.
#:
#: Aucun champ CONTINU n'existe aujourd'hui : `rule_choice` n'a aucune grandeur continue à
#: décrire, et en inventer une, remplie de zéros, serait une valeur par défaut sans signifiant.
#: Les tranches P3 qui en auront besoin (distance d'une destination, dégâts attendus sur une
#: cible) ouvriront un registre `DECISION_OPTION_CONT_FIELDS` à ce moment-là.
DECISION_OPTION_BIN_FIELDS: Tuple[str, ...] = tuple(
    f"grants_{rule_id}" for rule_id in UNIT_RULE_EFFECT_IDS
) + (
    "present",  # masque de candidat (0 = slot vide) — DERNIER, convention uniforme §0.37
)

DECISION_CTX_BIN_SIZE = len(DECISION_CTX_BIN_FIELDS)
DECISION_OPTION_BIN_SIZE = len(DECISION_OPTION_BIN_FIELDS)

_DECISION_CTX_BIN_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(DECISION_CTX_BIN_FIELDS)
}
_DECISION_OPTION_BIN_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(DECISION_OPTION_BIN_FIELDS)
}


def decision_ctx_bin_index(field: str) -> int:
    """Index d'un drapeau de contexte de décision. Nom inconnu -> KeyError explicite."""
    if field not in _DECISION_CTX_BIN_INDEX:
        raise KeyError(
            f"Drapeau de contexte de décision inconnu : {field!r}. "
            f"Champs : {DECISION_CTX_BIN_FIELDS}"
        )
    return _DECISION_CTX_BIN_INDEX[field]


def decision_option_bin_index(field: str) -> int:
    """Index d'un drapeau de candidat de décision. Nom inconnu -> KeyError explicite."""
    if field not in _DECISION_OPTION_BIN_INDEX:
        raise KeyError(
            f"Drapeau de candidat de décision inconnu : {field!r}. "
            f"Champs : {DECISION_OPTION_BIN_FIELDS}"
        )
    return _DECISION_OPTION_BIN_INDEX[field]


# ---------------------------------------------------------------------------
# Décision de DÉPLOIEMENT (V11 §0.40 point 3)
# ---------------------------------------------------------------------------

#: Nombre de slots de déploiement décrits. DOIT valoir `macro_intents.DEPLOY_SLOT_COUNT` (une
#: action 4-8 par slot) — verrouillé par test de contrat, comme `N_OBJECTIVE_SLOTS` ↔
#: `MAX_OBJECTIVES`. La constante est recopiée ici et non importée parce que ce module est une
#: FEUILLE (cf. `OBS_PHASE_IDS`).
N_DEPLOY_SLOTS = 5

#: Ce que le slot `i` (action `DEPLOY_SLOT_BASE + i`) POSERAIT s'il était joué.
#:
#: Le défaut fermé ici : les 5 actions du déploiement ne sont pas « les 5 premiers hexes
#: valides » mais 5 STRATÉGIES (front agressif, pression sur objectif, sûr/cohésion, flanc
#: gauche, flanc droit) évaluées sur TOUS les hexes valides — et l'observation n'en décrivait
#: AUCUN. L'agent choisissait entre cinq boîtes noires : ni position, ni distance aux objectifs,
#: ni couvert, ni exposition. Depuis §0.40 points 1/2/4 il sait où est sa zone et voit le terrain
#: autour ; il ne savait toujours pas ce que chaque slot en ferait.
#:
#: DOCTRINE (la même que les candidats de décision §9.3 et que les slots ennemis) : un candidat
#: se décrit par L'EFFET qu'il accorde, jamais par son index. Deux raisons ici, et la seconde est
#: décisive : le masque n'ouvre que `min(5, n_hexes)` slots, donc en fin de déploiement ce sont
#: les stratégies d'INDICES BAS qui survivent — le lien slot ↔ stratégie n'est pas stable, et un
#: réseau qui aurait appris « le slot 7 va à gauche » se tromperait précisément là.
#:
#: SOURCE : `ActionDecoder.deployment_slot_candidates`, celle-là même que le commit exécute.
#: Aucune géométrie n'est recalculée — décrire les candidats depuis un second calcul aurait
#: laissé l'agent choisir d'après un hexe que le moteur n'aurait pas posé (motif D1).
DEPLOY_CAND_CONT_FIELDS: Tuple[str, ...] = (
    # Position de l'hexe candidat RELATIVEMENT à l'origine de mesure de l'observation
    # (`ObservationBuilder.squad_grid_anchor`, l'ancre de la zone tant que l'unité n'est pas
    # posée), dans la projection `_hex_center` — le repère UNIQUE de §0.32 T-I, celui de la
    # grille et des directions d'objectif. C'est ce qui rend les candidats comparables à la
    # fenêtre égocentrique : un candidat de flanc extrême tombe hors de la grille (limite
    # assumée du point 2), et ces deux nombres sont alors la SEULE chose qui le situe.
    "col_rel",
    "row_rel",
    # Grandeurs qui ont PRODUIT le choix de la stratégie, telles quelles (entiers, subhex) —
    # elles sortent du cache de scoring du décodeur, pas d'un second calcul.
    "objective_distance",       # hex le plus proche d'un CENTRE d'objectif
    "enemy_distance",           # … d'une référence ennemie (unités posées, sinon zone ennemie)
    "ally_distance",            # … d'un allié déjà posé (masque : `has_deployed_ally`)
    "los_exposure",             # nb d'ennemis DÉJÀ POSÉS qui voient cet hexe (06.01)
    "potential_los_exposure",   # nb d'ancres de la zone ennemie qui le voient (menace à venir)
    "ally_col_count",           # nb d'alliés déjà posés sur la même colonne (étalement)
)

DEPLOY_CAND_BIN_FIELDS: Tuple[str, ...] = (
    # Masque d'`ally_distance` : sans lui, 0 voudrait dire à la fois « collé à un allié » et
    # « aucun allié posé », deux situations opposées pour une stratégie de cohésion.
    "has_deployed_ally",
    # 14.02 : l'hexe est un hexe d'objectif. 13.08 : il donne le bénéfice du couvert. Les deux
    # viennent des MÊMES ensembles que les canaux « objectifs » et « couvert » de la grille
    # (`_grid_static_hex_arrays`) : une lecture, pas une géométrie.
    "on_objective",
    "in_cover",
    "present",  # slot OUVERT par le masque (0 = fermé) — DERNIER, convention uniforme §0.37
)

DEPLOY_CAND_CONT_SIZE = len(DEPLOY_CAND_CONT_FIELDS)
DEPLOY_CAND_BIN_SIZE = len(DEPLOY_CAND_BIN_FIELDS)

_DEPLOY_CAND_CONT_INDEX: Dict[str, int] = {n: i for i, n in enumerate(DEPLOY_CAND_CONT_FIELDS)}
_DEPLOY_CAND_BIN_INDEX: Dict[str, int] = {n: i for i, n in enumerate(DEPLOY_CAND_BIN_FIELDS)}


def deploy_cand_cont_index(field: str) -> int:
    """Index d'une feature continue de candidat de déploiement. Nom inconnu -> KeyError."""
    if field not in _DEPLOY_CAND_CONT_INDEX:
        raise KeyError(
            f"Feature continue de candidat de deploiement inconnue : {field!r}. "
            f"Champs : {DEPLOY_CAND_CONT_FIELDS}"
        )
    return _DEPLOY_CAND_CONT_INDEX[field]


def deploy_cand_bin_index(field: str) -> int:
    """Index d'un drapeau de candidat de déploiement. Nom inconnu -> KeyError."""
    if field not in _DEPLOY_CAND_BIN_INDEX:
        raise KeyError(
            f"Drapeau de candidat de deploiement inconnu : {field!r}. "
            f"Champs : {DEPLOY_CAND_BIN_FIELDS}"
        )
    return _DEPLOY_CAND_BIN_INDEX[field]


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
#: Phases du moteur, dans l'ordre FIGÉ du one-hot `phase_*` de `GLOBAL_BIN_FIELDS`. DOIT valoir
#: `engine.action_decoder.GAME_PHASES` — verrouillé par test de contrat, comme
#: `N_OBJECTIVE_SLOTS` ↔ `macro_intents.MAX_OBJECTIVES`. La constante est recopiée ici et non
#: importée parce que ce module est une FEUILLE (aucune dépendance) : importer `action_decoder`,
#: qui tire tout le moteur, créerait un cycle.
OBS_PHASE_IDS: Tuple[str, ...] = (
    "deployment", "command", "move", "shoot", "charge", "fight",
)

#: La phase est un ONE-HOT de 6 bits (V11 §0.32 T-J). Elle vit avec les drapeaux car elle ne doit
#: JAMAIS être normalisée par des statistiques glissantes (V11 §9.5). L'encodage ordinal précédent
#: (0 / .25 / .5 / .75 / 1) avait deux défauts : il imposait une métrique entre phases qui n'a
#: aucun sens, et il donnait la MÊME valeur 0.0 à `deployment` et `command` — deux phases où les
#: ids d'action 4–8 signifient l'un « slot de déploiement », l'autre « cellule de move ».
#: Les sin/cos de direction d'objectif sont ici pour la MÊME raison de non-normalisation : déjà
#: bornés dans [-1,1] et centrés, les passer à `VecNormalize` ne ferait qu'amplifier leur bruit.
GLOBAL_BIN_FIELDS: Tuple[str, ...] = (
    "is_my_turn",
) + tuple(f"phase_{phase}" for phase in OBS_PHASE_IDS) + (
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
