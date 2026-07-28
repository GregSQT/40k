#!/usr/bin/env python3
"""engine/macro_intents.py - Zone intent system Phase 2."""

from engine.observation_entities import MAX_DECISION_OPTIONS

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
DEPLOY_SLOT_COUNT = 5       # deployment strategy slots 0-4 -> 4-8

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
TOTAL_ACTION_SIZE = CHOICE_BASE + CHOICE_COUNT                 # 1107

MOVE_CELLS = range(MOVE_CELL_BASE, MOVE_CELL_BASE + MOVE_CELL_COUNT)                # 0-1023
SHOOT_SLOTS = range(SHOOT_SLOT_BASE, SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT)            # 1025-1044
CHARGE_SLOTS = range(CHARGE_SLOT_BASE, CHARGE_SLOT_BASE + CHARGE_SLOT_COUNT)        # 1045-1064
FIGHT_SLOTS = range(FIGHT_SLOT_BASE, FIGHT_SLOT_BASE + FIGHT_SLOT_COUNT)            # 1065-1084
DEPLOY_SLOTS = range(DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT)        # 4-8
CHOICE_SLOTS = range(CHOICE_BASE, CHOICE_BASE + CHOICE_COUNT)                       # 1101-1106


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


def get_best_enemy_global(game_state: dict, zone_idx: int):
    """Return (col, row) of best enemy (highest damage_ratio). Falls back to zone objective if no enemy alive."""
    cache = game_state.get("_cached_best_enemy_global")
    if cache is not None and zone_idx in cache:
        return cache[zone_idx]

    from engine.phase_handlers.shared_utils import is_unit_alive
    current_player = game_state["current_player"]
    fallback_col, fallback_row = get_objective_center(game_state["objectives"][zone_idx])

    best_unit = None
    best_score = -1.0
    for unit in game_state["units"]:
        if unit.get("player") == current_player:
            continue
        if not is_unit_alive(str(unit["id"]), game_state):
            continue
        score = get_best_enemy_score_for_unit(unit, game_state)
        if score > best_score:
            best_score = score
            best_unit = unit

    result = (best_unit["col"], best_unit["row"]) if best_unit is not None else (fallback_col, fallback_row)
    if "_cached_best_enemy_global" not in game_state:
        game_state["_cached_best_enemy_global"] = {}
    game_state["_cached_best_enemy_global"][zone_idx] = result
    return result


def get_best_enemy_score(game_state: dict) -> float:
    """Return damage_ratio of best enemy. Returns 0.0 if no enemy alive."""
    cached = game_state.get("_cached_best_enemy_score")
    if cached is not None:
        return cached

    from engine.phase_handlers.shared_utils import is_unit_alive
    current_player = game_state["current_player"]
    best_score = 0.0
    for unit in game_state["units"]:
        if unit.get("player") == current_player:
            continue
        if not is_unit_alive(str(unit["id"]), game_state):
            continue
        score = get_best_enemy_score_for_unit(unit, game_state)
        if score > best_score:
            best_score = score
    game_state["_cached_best_enemy_score"] = best_score
    return best_score


def get_best_enemy_score_for_unit(unit: dict, game_state: dict) -> float:
    """Compute damage_ratio = expected_damage / hp_remaining for a unit."""
    from engine.weapon_damage_cache import lookup_best_weapon
    from engine.phase_handlers.shared_utils import get_hp_from_cache, is_unit_alive
    hp = get_hp_from_cache(str(unit["id"]), game_state)
    if not hp or hp <= 0:
        return 0.0
    cache = game_state.get("_best_weapon_cache")
    if not cache:
        return 0.0
    unit_id = str(unit["id"])
    current_player = game_state.get("current_player")
    max_dmg = 0.0
    for target in game_state["units"]:
        if target.get("player") != current_player:
            continue
        if not is_unit_alive(str(target["id"]), game_state):
            continue
        target_id = str(target["id"])
        _, ranged_dmg = lookup_best_weapon(cache, unit_id, target_id, True)
        _, melee_dmg = lookup_best_weapon(cache, unit_id, target_id, False)
        max_dmg = max(max_dmg, ranged_dmg, melee_dmg)
    return max_dmg / hp


def get_objective_control(zone_idx: int, game_state: dict) -> float:
    """Return 1.0 if objective controlled by current_player, -1.0 if by opponent, 0.0 if neutral/contested."""
    objectives = game_state["objectives"]
    if zone_idx >= len(objectives):
        return 0.0
    obj = objectives[zone_idx]
    obj_id = str(obj["id"])
    controllers = game_state["objective_controllers"]
    controller = controllers.get(obj_id)
    current_player = game_state.get("current_player")
    if controller is None:
        return 0.0
    if controller == current_player:
        return 1.0
    return -1.0
