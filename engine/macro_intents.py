#!/usr/bin/env python3
"""engine/macro_intents.py - Zone intent system Phase 2."""

from engine.observation_entities import K_ALLY_SLOTS, MAX_DECISION_OPTIONS
from shared.data_validation import require_key

INTENT_INVADE = 0
INTENT_DEFEND = 1
INTENT_ATTACK = 2

MAX_OBJECTIVES = 5
# Refonte spatiale du move (move_action_space_spatial_rework.md §6.2) : une action de mouvement
# designe une CELLULE de la grille egocentrique 32x32, plus une direction 0-5. Le TYPE de move
# (normal/advance/fall_back) n'est PAS une dimension d'action : il est infere du cout geodesique
# de la cellule (cf. shared_utils.infer_squad_move_type).
# 1086 micro actions (V11 §0.30 T-E : 20 slots de tir ; §9 P3-1 : 20 slots de combat ;
# §9 P3-2 : 20 slots de charge) :
#   0-1023   : destination = cellule (gx,gy) de la grille egocentrique  [cell_index = gy*32+gx]
#   1024     : wait / end activation
#   1025-1044: shoot slot 0-19 (20)
#   1045-1064: charge slot 0-19 (20) — MEME mapping de slots ennemis que le tir
#   1065-1084: fight slot 0-19 (20) — MEME mapping de slots ennemis que le tir
#   1085     : fight sans cible eligible (12.04/12.06 : selectionne pour combattre, 0 attaque)
#   1086-1100: zone intents (5 objectifs x 3 intentions)
#   1101-1106: CHOICE_0..5 — candidats de `pending_agent_decision` (V11 §9.3 P2)
#   1107-1126: oath slot 0-19 — cible d'Oath of Moment (chantier 01, consomme au chantier 03)
#   1127-1138: activate slot 0-11 — escouade a ACTIVER (V11 §0.48 L2), un par ligne alliee

# --- Named squad-action ids (single source of truth for ai/). --------------
# Miroir EXACT de engine/phase_handlers/shared_utils.py (SQUAD_ACTION_*), qui reste la source
# moteur (§4.5 : les deux DOIVENT rester synchronises — verrouille par test). Interdit tout
# littéral d'action nu dans ai/ : importer ces noms. Aucune valeur par défaut, aucun fallback.
# Les ids sont DERIVES les uns des autres (et non recopies en litteraux) : le miroir avec
# shared_utils.SQUAD_ACTION_* ne peut plus se desynchroniser que sur UNE valeur, le nombre de
# slots de tir — que `test_action_space_mirror.py` verrouille.
MOVE_CELL_BASE = 0
MOVE_CELL_COUNT = 1024       # 32x32, cf. engine.spatial_grid.GRID_CELL_COUNT
ACTION_WAIT = MOVE_CELL_BASE + MOVE_CELL_COUNT   # 1024 — wait / end activation
SHOOT_SLOT_BASE = ACTION_WAIT + 1                # 1025
SHOOT_SLOT_COUNT = 20        # shoot enemy slots 0-19 -> 1025-1044 (V11 T-E)
# V11 §9 P3-2 — la CIBLE DE CHARGE est une dimension d'action (11.02 « Declare Charge » /
# 11.04 « BEFORE MOVING: select one or more enemy units » : la cible est un choix de JOUEUR).
# Avant, `charge` etait une action sans cible et le decodeur tranchait par `damage_ratio` :
# l'agent declarait « je charge » sans jamais dire QUI. Meme derivation que les slots de melee.
CHARGE_SLOT_BASE = SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT  # 1045
CHARGE_SLOT_COUNT = SHOOT_SLOT_COUNT                   # 20 -> 1045-1064
# V11 §9 P3-1 — la CIBLE DE MELEE est une dimension d'action, plus une heuristique interne.
# `FIGHT_SLOT_COUNT` est DERIVE de `SHOOT_SLOT_COUNT` : les deux familles indexent le MEME
# mapping `get_enemy_slot_mapping` (et donc la meme ligne du tenseur ennemi de l'observation,
# invariant D1). Les desolidariser ferait pointer l'action de combat i et l'observation i sur
# deux escouades differentes, sans que rien ne leve.
FIGHT_SLOT_BASE = CHARGE_SLOT_BASE + CHARGE_SLOT_COUNT  # 1065
FIGHT_SLOT_COUNT = SHOOT_SLOT_COUNT                 # 20 -> 1065-1084
# 12.04/12.06 : une escouade selectionnee pour combattre SANS cible eligible (sa cible est
# morte, overrun) resout un combat a vide. C'est un etat legal du jeu, pas un cas d'erreur :
# il lui faut donc une action propre. Fusionner ce cas avec un slot rendrait « frapper le
# slot i » ambigu (frapper i, ou ne frapper personne ?).
ACTION_FIGHT_NO_TARGET = FIGHT_SLOT_BASE + FIGHT_SLOT_COUNT   # 1085
DEPLOY_SLOT_BASE = 4
# Slots de deploiement DECRITS par l'observation et adressables par une action : 8 -> ids 4-11.
# Ils tombent dans la plage des cellules de move (`MOVE_CELL_BASE = 0`), donc `TOTAL_ACTION_SIZE`
# ne bouge pas ; l'invariant est `DEPLOY_SLOT_COUNT == observation_entities.N_DEPLOY_SLOTS`
# (verrouille par test).
DEPLOY_SLOT_COUNT = 8       # deployment slots 0-7 -> 4-11
# Nombre de STRATEGIES de deploiement reellement definies (`_deployment_slot_order`). C'est LUI
# que le masque borne (`action_decoder.open_deploy_slot_count`) : les slots au-dela sont
# RESERVES et ne s'ouvrent jamais. Separer les deux constantes est ce qui rend l'ajout d'une
# strategie gratuit en `obs_size` (V11 §0.48, arbitrage 2 / element L11) : une strategie de plus
# = cette constante +1, aucune forme d'observation touchee, aucun retrain.
# ⚠️ `DEPLOY_STRATEGY_COUNT <= DEPLOY_SLOT_COUNT` — l'inverse ouvrirait une action sans strategie.
DEPLOY_STRATEGY_COUNT = 5

BASE_ZONE_INTENT = ACTION_FIGHT_NO_TARGET + 1                  # 1086
# Decision agent generique (V11 §9.3 P2) : K actions `CHOICE_i` qui designent le candidat i de
# `game_state["pending_agent_decision"]`. Elles sont EXCLUSIVES des autres (quand une decision
# est en attente, le masque n'expose qu'elles) et communes a TOUS les types de decision : c'est
# ce qui evite une action ad hoc par point de choix, donc l'explosion de l'action space.
# ⚠️ Elles ne concernent QUE les decisions dont les candidats ne sont PAS des entites deja
# observees : une decision « quelle escouade ennemie » se parametre en dimension d'action +
# pointeur (§9 P3-1, les slots de combat ci-dessus), pas en CHOICE_k.
CHOICE_BASE = BASE_ZONE_INTENT + MAX_OBJECTIVES * 3            # 1101
CHOICE_COUNT = MAX_DECISION_OPTIONS                            # 6
# Oath of Moment (chantier 03) : « select one unit from your opponent's army ». Les candidats
# sont des ENTITES DEJA OBSERVEES, donc la decision se parametre en DIMENSION D'ACTION + pointeur
# et non en `CHOICE_k` (cf. l'avertissement ci-dessus). Meme derivation que le tir, la charge et
# la melee : `OATH_SLOT_COUNT = SHOOT_SLOT_COUNT`, parce que ces slots indexent le MEME
# `get_enemy_slot_mapping`, donc la MEME ligne du tenseur ennemi (invariant D1). Les desolidariser
# ferait pointer l'action et l'observation sur deux escouades differentes sans que rien ne leve.
#
# Declares ICI et pas au chantier 03 : `TOTAL_ACTION_SIZE` est GELE apres le chantier 01, comme
# `obs_size`. Aucun consommateur avant le chantier 03 — le masque n'ouvre jamais ces ids, donc
# l'agent ne peut pas les jouer (`ActionDecoder` part d'un masque tout a zero et n'ouvre que ce
# qu'une phase autorise).
OATH_SLOT_BASE = CHOICE_BASE + CHOICE_COUNT                    # 1107
OATH_SLOT_COUNT = SHOOT_SLOT_COUNT                             # 20 -> 1107-1126
# V11 §0.48 element L2 / §9 P3-3 — CHOIX DE L'ESCOUADE A ACTIVER. Jusqu'ici l'unite activee etait
# TOUJOURS `eligible_units[0]` : l'ORDRE d'activation, c'est-a-dire la premiere decision de chaque
# phase, echappait entierement a l'agent.
#
# Les candidats sont MES escouades, donc des ENTITES DEJA OBSERVEES : la decision se parametre en
# DIMENSION D'ACTION + tete pointeur, jamais en `CHOICE_k` (cf. l'avertissement de CHOICE_BASE).
# `MAX_DECISION_OPTIONS = 6` serait de toute facon depasse par `K_ALLY_SLOTS = 12`, et
# `agent_decision.set_pending_agent_decision` leverait.
#
# `ACTIVATE_SLOT_COUNT` est DERIVE de `K_ALLY_SLOTS` — le nombre de lignes du tenseur ALLIE de
# l'observation — pour la MEME raison que les slots de tir/charge/melee/Oath derivent de
# `SHOOT_SLOT_COUNT` : le slot `i` designe la ligne `i`. Les desolidariser ferait pointer l'action
# et l'observation sur deux escouades differentes sans que rien ne leve (invariant D1, cote allie).
ACTIVATE_SLOT_BASE = OATH_SLOT_BASE + OATH_SLOT_COUNT          # 1127
ACTIVATE_SLOT_COUNT = K_ALLY_SLOTS                             # 12 -> 1127-1138
TOTAL_ACTION_SIZE = ACTIVATE_SLOT_BASE + ACTIVATE_SLOT_COUNT   # 1139

MOVE_CELLS = range(MOVE_CELL_BASE, MOVE_CELL_BASE + MOVE_CELL_COUNT)                # 0-1023
SHOOT_SLOTS = range(SHOOT_SLOT_BASE, SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT)            # 1025-1044
CHARGE_SLOTS = range(CHARGE_SLOT_BASE, CHARGE_SLOT_BASE + CHARGE_SLOT_COUNT)        # 1045-1064
FIGHT_SLOTS = range(FIGHT_SLOT_BASE, FIGHT_SLOT_BASE + FIGHT_SLOT_COUNT)            # 1065-1084
DEPLOY_SLOTS = range(DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT)        # 4-11
# Slots reellement JOUABLES : ceux qui portent une strategie definie. `DEPLOY_SLOTS` decrit ce que
# l'observation expose et ce que le decodeur reconnait comme un id de deploiement ; c'est CELUI-CI
# qu'il faut prendre des qu'on enumere « les poses possibles » (poids des bots, tirages, tests).
# Confondre les deux, c'est proposer une action que le masque n'ouvre jamais.
DEPLOY_STRATEGY_SLOTS = range(DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_STRATEGY_COUNT)  # 4-8
CHOICE_SLOTS = range(CHOICE_BASE, CHOICE_BASE + CHOICE_COUNT)                       # 1101-1106
OATH_SLOTS = range(OATH_SLOT_BASE, OATH_SLOT_BASE + OATH_SLOT_COUNT)                # 1107-1126
ACTIVATE_SLOTS = range(ACTIVATE_SLOT_BASE, ACTIVATE_SLOT_BASE + ACTIVATE_SLOT_COUNT)  # 1127-1138


def get_objective_center(obj: dict) -> tuple:
    """Return (col, row) center of an objective. Uses 'center' key if present, else centroid of 'hexes'."""
    if "center" in obj:
        c = obj["center"]
        return int(c[0]), int(c[1])
    hexes = obj["hexes"]
    if not hexes:
        raise ValueError(f"Objective {obj.get('id')} has no center and no hexes")
    def _hex_col(h):
        return int(h[0]) if isinstance(h, (list, tuple)) else int(h["col"])
    def _hex_row(h):
        return int(h[1]) if isinstance(h, (list, tuple)) else int(h["row"])
    return sum(_hex_col(h) for h in hexes) // len(hexes), sum(_hex_row(h) for h in hexes) // len(hexes)


def is_zone_intent_action(action: int) -> bool:
    # Borne haute = CHOICE_BASE, PAS TOTAL_ACTION_SIZE : depuis P2 (§9.3) l'action space se
    # termine par les CHOICE_i, qui ne sont pas des zone intents. La borne `TOTAL_ACTION_SIZE`
    # les aurait avalés en silence et `decode_zone_intent_action` aurait rendu une zone 5.
    return BASE_ZONE_INTENT <= action < CHOICE_BASE


def is_agent_decision_action(action: int) -> bool:
    """True si `action` designe un candidat de `pending_agent_decision` (CHOICE_i)."""
    return CHOICE_BASE <= action < CHOICE_BASE + CHOICE_COUNT


def decode_agent_decision_action(action: int) -> int:
    """Index du candidat designe par une action CHOICE. Hors plage -> ValueError explicite."""
    if not is_agent_decision_action(action):
        raise ValueError(
            f"decode_agent_decision_action: action {action} hors de la plage CHOICE "
            f"[{CHOICE_BASE}, {CHOICE_BASE + CHOICE_COUNT - 1}]"
        )
    return action - CHOICE_BASE


def decode_zone_intent_action(action: int):
    offset = action - BASE_ZONE_INTENT
    zone_idx = offset // 3
    intent_value = offset % 3
    return zone_idx, intent_value


def get_nearest_objective_zone(active_unit: dict, game_state: dict) -> int:
    """Return index of the closest objective to active_unit. Called once per command phase."""
    from engine.combat_utils import calculate_hex_distance
    objectives = game_state["objectives"]
    if not objectives:
        return 0
    unit_col, unit_row = active_unit["col"], active_unit["row"]
    best_idx, best_dist = 0, float("inf")
    for i, obj in enumerate(objectives):
        obj_col, obj_row = get_objective_center(obj)
        d = calculate_hex_distance(unit_col, unit_row, obj_col, obj_row)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


# V11 §0.43 — les heuristiques de menace par `damage_ratio` (`get_best_enemy_global`,
# `get_best_enemy_score`, `get_best_enemy_score_for_unit`) ont ete SUPPRIMEES : elles
# tranchaient la cible (de charge, de melee) a la place de l'agent. Depuis §9 P3-1/P3-2, la
# cible est une DIMENSION D'ACTION (un slot ennemi, cf. CHARGE_SLOTS / FIGHT_SLOTS ci-dessus)
# scoree par la tete pointeur. Aucune heuristique de repli ne doit revenir ici.


def get_objective_control_for_player(zone_idx: int, game_state: dict, player: int) -> float:
    """Controle de l'objectif `zone_idx` DU POINT DE VUE de `player`.

    1.0 s'il le controle, -1.0 si l'adversaire le controle, 0.0 si neutre/conteste.

    Version explicite, a utiliser des que le point de vue n'est PAS celui du joueur dont c'est
    le tour. Cas vecu : le solde terminal des zone-intents porte sur le joueur controle, alors
    que la partie se termine pendant le tour du bot — mesure sur le harnais moteur : 6
    terminaisons sur 6 avec `current_player=2` pour `controlled_player=1`. Passer par la version
    relative y inversait le signe de TOUS les objectifs, donc payait le bonus DEFEND quand
    l'agent avait PERDU la zone.
    """
    objectives = game_state["objectives"]
    if zone_idx >= len(objectives):
        return 0.0
    obj = objectives[zone_idx]
    obj_id = str(obj["id"])
    controllers = game_state["objective_controllers"]
    controller = controllers.get(obj_id)
    if controller is None:
        return 0.0
    if controller == player:
        return 1.0
    return -1.0


def get_objective_control(zone_idx: int, game_state: dict) -> float:
    """Return 1.0 if objective controlled by current_player, -1.0 if by opponent, 0.0 if neutral/contested."""
    # `current_player` est pose a la construction du game_state ET a chaque reset : sa lecture
    # est stricte. Le `.get()` tolerant d'avant rendait -1.0 quand la cle manquait, c'est-a-dire
    # "objectif adverse" pour un etat incomplet — un silence qui se lisait comme une donnee.
    return get_objective_control_for_player(
        zone_idx, game_state, int(require_key(game_state, "current_player"))
    )

#: Familles d'actions, pour l'instrumentation d'USAGE (quelle DECISION l'agent exerce).
#: Vit ici parce que la decoupe DERIVE du layout : la recopier ailleurs la desynchroniserait
#: au premier slot ajoute.
ACTION_FAMILIES = (
    "deploy_slot", "move_cell", "wait", "shoot_slot", "charge_slot",
    "fight_slot", "fight_no_target", "zone_intent", "choice", "oath_slot",
    "activate_slot",
)


def action_family(action_int: int, phase: str, *, setting_up: bool = False) -> str:
    """Famille de `action_int`, sachant la PHASE ou il a ete joue.

    La phase est indispensable, elle n'est pas un confort : les ids 4-8 sont a la fois les
    5 strategies de deploiement (`DEPLOY_SLOTS`) et des cellules de move (`MOVE_CELL_BASE = 0`).
    Sans elle, tout deploiement serait compte comme un deplacement — et c'est precisement le
    recouvrement que V11 §0.44 doit lever cote policy.

    `setting_up` : l'escouade active est HORS TABLE et joue une MISE EN PLACE (ingress move
    20.04, en phase de mouvement). La phase ne suffit alors plus a lever le recouvrement — les
    ids 4-8 y designent des strategies de pose, pas des cellules — et sans ce drapeau une arrivee
    de reserves serait comptee comme un deplacement dans `action_family_counts`. C'est l'appelant
    qui le sait : lui seul connait l'unite active.
    """
    a = int(action_int)
    if a < 0 or a >= TOTAL_ACTION_SIZE:
        raise ValueError(f"action_int hors espace d'action : {a} (taille {TOTAL_ACTION_SIZE})")
    # Les CHOICE_k PREEMPTENT la phase : quand une decision d'agent est en attente, le masque
    # n'expose qu'elles, y compris pendant le deploiement (`trigger="on_deploy"`). Les tester
    # AVANT la branche deployment, sinon une regle de datasheet declenchee au deploiement ferait
    # lever cette fonction — donc planter le step, pour une simple statistique.
    if a in CHOICE_SLOTS:
        return "choice"
    # Oath slots : APRES les CHOICE et AVANT la branche deployment, comme elles — Oath se declare
    # au debut du tour de son controleur, pas dans une phase de mouvement. Sans cette branche,
    # ces ids tomberaient dans le `return "zone_intent"` terminal, qui est un fourre-tout : ils
    # seraient comptes comme des intentions de zone sans que rien ne leve.
    if a in OATH_SLOTS:
        return "oath_slot"
    # Slots d'activation : meme rang que les CHOICE et Oath, et pour la meme raison — le masque
    # est EXCLUSIF quand le choix est pose, donc l'id ne depend pas de la phase. Les tester ici
    # et non plus bas : sans cette branche ils tomberaient dans le `return "zone_intent"` final,
    # qui est un fourre-tout, et seraient comptes comme des intentions de zone sans que rien ne leve.
    if a in ACTIVATE_SLOTS:
        return "activate_slot"
    if phase == "deployment":
        if a in DEPLOY_SLOTS:
            return "deploy_slot"
        # 20.01 — mettre l'unite en RESERVES au lieu de la deployer. La decision emprunte
        # `ACTION_WAIT`, id libre en phase de deploiement (cf. le masque) : c'est bien une
        # decision de deploiement, comptee comme telle.
        if a == ACTION_WAIT:
            return "deploy_slot"
        raise ValueError(
            f"action {a} jouee en phase deployment hors des slots {DEPLOY_SLOTS}, hors "
            f"ACTION_WAIT (reserves 20.01) et hors CHOICE_SLOTS — le masque de deploiement "
            f"n'ouvre que ces ids."
        )
    if a == ACTION_WAIT:
        return "wait"
    # Mise en place d'une unite hors table (ingress move 20.04) : les ids 4-8 y sont des
    # strategies de POSE, exactement comme en phase de deploiement, et non des cellules.
    if setting_up and a in DEPLOY_SLOTS:
        return "deploy_slot"
    if a in MOVE_CELLS:
        return "move_cell"
    if a in SHOOT_SLOTS:
        return "shoot_slot"
    if a in CHARGE_SLOTS:
        return "charge_slot"
    if a in FIGHT_SLOTS:
        return "fight_slot"
    if a == ACTION_FIGHT_NO_TARGET:
        return "fight_no_target"
    if a in CHOICE_SLOTS:
        return "choice"
    return "zone_intent"

