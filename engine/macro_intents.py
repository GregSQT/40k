#!/usr/bin/env python3
"""engine/macro_intents.py - Zone intent system Phase 2."""

INTENT_INVADE = 0
INTENT_DEFEND = 1
INTENT_ATTACK = 2

MAX_OBJECTIVES = 5
# PR4 4e-v_a : squad pipeline action space (cf. squad.md §"Action space (micro)").
# Decision utilisateur : agent decide direction Advance/Fall Back (aucune valeur par défaut).
# 26 micro actions:
#   0-5   : Normal move direction D (6)
#   6-11  : Advance direction D (6)        [PR4: extension agent-decided]
#   12-17 : Fall Back direction D (6)      [PR4: extension agent-decided]
#   18    : wait / end activation
#   19-23 : shoot slot 0-4 (5)
#   24    : charge
#   25    : fight
BASE_ZONE_INTENT = 26
TOTAL_ACTION_SIZE = BASE_ZONE_INTENT + MAX_OBJECTIVES * 3  # 41

# --- Named squad-action ids (single source of truth for ai/). --------------
# Miroir EXACT de engine/phase_handlers/shared_utils.py (SQUAD_ACTION_*), qui
# reste la source moteur. Interdit tout littéral d'action nu dans ai/ : importer
# ces noms. Aucune valeur par défaut, aucun fallback.
MOVE_DIR_BASE = 0
MOVE_DIR_COUNT = 6            # normal move, directions 0-5
ADVANCE_DIR_BASE = 6
ADVANCE_DIR_COUNT = 6        # advance, directions 6-11
FALL_BACK_DIR_BASE = 12
FALL_BACK_DIR_COUNT = 6      # fall back, directions 12-17
ACTION_WAIT = 18            # wait / end activation
SHOOT_SLOT_BASE = 19
SHOOT_SLOT_COUNT = 5        # shoot enemy slots 0-4 -> 19-23
ACTION_CHARGE = 24
ACTION_FIGHT = 25
DEPLOY_SLOT_BASE = 4
DEPLOY_SLOT_COUNT = 5       # deployment strategy slots 0-4 -> 4-8

MOVE_DIRS = range(MOVE_DIR_BASE, MOVE_DIR_BASE + MOVE_DIR_COUNT)                    # 0-5
ADVANCE_DIRS = range(ADVANCE_DIR_BASE, ADVANCE_DIR_BASE + ADVANCE_DIR_COUNT)        # 6-11
FALL_BACK_DIRS = range(FALL_BACK_DIR_BASE, FALL_BACK_DIR_BASE + FALL_BACK_DIR_COUNT)  # 12-17
SHOOT_SLOTS = range(SHOOT_SLOT_BASE, SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT)            # 19-23
DEPLOY_SLOTS = range(DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT)        # 4-8


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
    return BASE_ZONE_INTENT <= action < TOTAL_ACTION_SIZE


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
