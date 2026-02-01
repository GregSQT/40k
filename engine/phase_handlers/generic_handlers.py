#!/usr/bin/env python3
"""
generic_handlers.py - AI_TURN.md Generic Functions
Pure stateless functions implementing AI_TURN.md specification exactly

References: AI_TURN.md END OF ACTIVATION PROCEDURE
ZERO TOLERANCE for deviations from specification
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from shared.data_validation import require_key
from engine.combat_utils import get_unit_by_id
from .shared_utils import (
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
)


def _log_with_context(game_state: Dict[str, Any], prefix: str, message: str) -> None:
    """
    Log message with episode/turn/phase context if available.
    
    Only logs if episode_number, turn, and phase exist in game_state (training mode).
    Silently skips logging if not in training context.
    
    Args:
        game_state: Game state dictionary
        prefix: Log prefix (e.g., "MOVE DEBUG", "POOL DEBUG")
        message: Log message content
    """
    if "episode_number" not in game_state or "turn" not in game_state or "phase" not in game_state:
        return
    
    episode = game_state["episode_number"]
    turn = game_state["turn"]
    phase = game_state.get("phase", "?")
    
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    
    log_message = f"[{prefix}] E{episode} T{turn} {phase} {message}"
    from engine.game_utils import add_console_log, safe_print
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)


def end_activation(game_state: Dict[str, Any], unit: Dict[str, Any], 
                  arg1: str, arg2: int, arg3: str, arg4: str, arg5: int) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: END OF ACTIVATION PROCEDURE
    end_activation (Arg1, Arg2, Arg3, Arg4, Arg5)
    
    Args:
        arg1: ACTION/WAIT/NO - logging behavior
        arg2: 1/0 - step increment
        arg3: MOVE/FLED/SHOOTING/CHARGE/FIGHT - tracking sets
        arg4: MOVE/FLED/SHOOTING/CHARGE/FIGHT - pool removal
        arg5: 1/0 - error logging
    """
    unit_id = unit["id"]
    response = {
        "activation_ended": True,
        "unitId": unit_id,
        "endType": arg1
    }
    
    # ├── Arg1 = ?
    # │   ├── CASE Arg1 = ACTION -> log the action
    # │   ├── CASE Arg1 = WAIT -> log the wait action
    # │   └── CASE Arg1 = NO -> do not log the action
    if arg1 == "ACTION":
        # Log the action (action already logged by handlers)
        response["action_logged"] = True
    elif arg1 == "WAIT":
        # Log the wait action
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        # AI_TURN.md COMPLIANCE: Direct field access with validation
        if "turn" not in game_state:
            raise KeyError("game_state missing required 'turn' field for wait action logging")

        unit_col, unit_row = require_unit_position(unit, game_state)
        game_state["action_logs"].append({
            "type": "wait",
            "message": f"Unit {unit_id} ({unit_col}, {unit_row}) WAIT",
            "turn": game_state["turn"],
            "phase": game_state["phase"],
            "unitId": unit_id,
            "col": unit_col,
            "row": unit_row,
            "timestamp": "server_time"
        })
        response["wait_logged"] = True
    elif arg1 == "NO":
        # Do not log the action
        response["no_logging"] = True
    
    # ├── Arg2 = 1 ?
    # │   ├── YES -> +1 step
    # │   └── NO -> No step increase
    if arg2 == 1:
        if "episode_steps" not in game_state:
            game_state["episode_steps"] = 0
        game_state["episode_steps"] += 1
        response["step_incremented"] = True
    
    # ├── Arg3 =
    # │ ├── CASE Arg3 = MOVE -> Mark as units_moved
    # │ ├── CASE Arg3 = FLED -> Mark as units_moved AND Mark as units_fled
    # │ ├── CASE Arg3 = SHOOTING -> Mark as units_shot
    # │ ├── CASE Arg3 = CHARGE -> Mark as units_charged
    # │ └── CASE Arg3 = FIGHT -> Mark as units_fought
    if arg3 == "MOVE":
        if "units_moved" not in game_state:
            game_state["units_moved"] = set()
        # CRITICAL: Normalize unit ID to string for consistent storage (units_moved stores strings)
        unit_id_str = str(unit_id)
        game_state["units_moved"].add(unit_id_str)
    elif arg3 == "FLED":
        if "units_moved" not in game_state:
            game_state["units_moved"] = set()
        if "units_fled" not in game_state:
            game_state["units_fled"] = set()
        # CRITICAL: Normalize unit ID to string for consistent storage (units_fled stores strings)
        unit_id_str = str(unit_id)
        game_state["units_moved"].add(unit_id_str)
        game_state["units_fled"].add(unit_id_str)
    elif arg3 == "SHOOTING":
        if "units_shot" not in game_state:
            game_state["units_shot"] = set()
        game_state["units_shot"].add(unit_id)
    elif arg3 == "CHARGE":
        if "units_charged" not in game_state:
            game_state["units_charged"] = set()
        game_state["units_charged"].add(unit_id)
    elif arg3 == "FIGHT":
        if "units_fought" not in game_state:
            game_state["units_fought"] = set()
        game_state["units_fought"].add(unit_id)
    
    # ├── Arg4 = ?
    # │ ├── CASE Arg4 = NOT_REMOVED -> Do not remove the unit from an activation pool
    # │ ├── CASE Arg4 = MOVE -> Unit removed from move_activation_pool
    # │ ├── CASE Arg4 = FLED -> Unit removed from move_activation_pool
    # │ ├── CASE Arg4 = SHOOTING -> Unit removed from shoot_activation_pool
    # │ ├── CASE Arg4 = CHARGE -> Unit removed from charge_activation_pool
    # │ └── CASE Arg4 = FIGHT -> Unit removed from fight_activation_pool
    if arg4 == "NOT_REMOVED":
        # AI_TURN.md line 199: Do not remove the unit from an activation pool
        # Unit remains in its current activation pool (no action needed)
        response["not_removed_from_pool"] = True
    elif arg4 in ["MOVE", "FLED"]:
        if "move_activation_pool" in game_state:
            # CRITICAL: Normalize unit ID to string for consistent storage (move_activation_pool stores strings)
            unit_id_str = str(unit_id)
            # Filter instead of remove to handle type mismatches
            # Normalize pool to contain only strings (consistent with pool construction)
            pool_before = list(game_state["move_activation_pool"])
            pool_before_len = len(pool_before)
            game_state["move_activation_pool"] = [str(uid) for uid in game_state["move_activation_pool"] if str(uid) != unit_id_str]
            pool_after = list(game_state["move_activation_pool"])
            pool_after_len = len(pool_after)
            if pool_before_len != pool_after_len:
                response["removed_from_move_pool"] = True
                # DEBUG: Log pool removal
                from engine.game_utils import add_debug_log
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_log(game_state, f"[END_ACTIVATION DEBUG] E{episode} T{turn} end_activation: Unit {unit_id_str} removed from move_activation_pool. Pool before={pool_before} (len={pool_before_len}), pool after={pool_after} (len={pool_after_len}), arg1={arg1}, arg4={arg4}, arg5={arg5}")
            else:
                # DEBUG: Log why unit was NOT removed
                from engine.game_utils import add_debug_log
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_log(game_state, f"[END_ACTIVATION DEBUG] E{episode} T{turn} end_activation: Unit {unit_id_str} NOT removed from move_activation_pool. Pool={pool_before} (len={pool_before_len}), unit_id_str={unit_id_str}, unit_id={unit_id}, arg1={arg1}, arg4={arg4}, arg5={arg5}")
    elif arg4 == "SHOOTING":
        if "shoot_activation_pool" in game_state:
            # PRINCIPLE: "Le Pool DOIT gérer les morts" - Use string comparison to handle int/string ID mismatches
            unit_id_str = str(unit_id)
            # Filter instead of remove to handle type mismatches
            # Normalize pool to contain only strings (consistent with pool construction in shooting_handlers.py line 641)
            pool_before = list(game_state["shoot_activation_pool"])
            pool_before_len = len(pool_before)
            game_state["shoot_activation_pool"] = [str(uid) for uid in game_state["shoot_activation_pool"] if str(uid) != unit_id_str]
            pool_after = list(game_state["shoot_activation_pool"])
            pool_after_len = len(pool_after)
            if pool_before_len != pool_after_len:
                response["removed_from_shoot_pool"] = True
                # DEBUG: Log pool removal
                from engine.game_utils import add_debug_log
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_log(game_state, f"[END_ACTIVATION DEBUG] E{episode} T{turn} end_activation: Unit {unit_id_str} removed from shoot_activation_pool. Pool before={pool_before} (len={pool_before_len}), pool after={pool_after} (len={pool_after_len}), arg1={arg1}, arg4={arg4}, arg5={arg5}")
            else:
                # DEBUG: Log why unit was NOT removed
                from engine.game_utils import add_debug_log
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_log(game_state, f"[END_ACTIVATION DEBUG] E{episode} T{turn} end_activation: Unit {unit_id_str} NOT removed from shoot_activation_pool. Pool={pool_before} (len={pool_before_len}), unit_id_str={unit_id_str}, unit_id={unit_id}, arg1={arg1}, arg4={arg4}, arg5={arg5}")
    elif arg4 == "CHARGE":
        if "charge_activation_pool" in game_state and unit_id in game_state["charge_activation_pool"]:
            game_state["charge_activation_pool"].remove(unit_id)
            response["removed_from_charge_pool"] = True
    elif arg4 == "FIGHT":
        # Fight phase has 3 sub-phase pools - check all 3
        # Units can only be in ONE pool at a time (verified via AI_TURN.md lines 717-718, 730-731)
        removed = False

        # CRITICAL: Normalize unit_id to string for comparison (pools contain strings)
        unit_id_str = str(unit_id)

        # Sub-phase 1: Charging pool (current player's charging units)
        if "charging_activation_pool" in game_state:
            # Convert pool to list of strings for comparison
            pool_str = [str(id) for id in game_state["charging_activation_pool"]]
            if unit_id_str in pool_str:
                game_state["charging_activation_pool"] = [id for id in game_state["charging_activation_pool"] if str(id) != unit_id_str]
                response["removed_from_charging_pool"] = True
                removed = True

        # Sub-phase 2: Active alternating pool (current player's non-charging units)
        if not removed and "active_alternating_activation_pool" in game_state:
            pool_str = [str(id) for id in game_state["active_alternating_activation_pool"]]
            if unit_id_str in pool_str:
                game_state["active_alternating_activation_pool"] = [id for id in game_state["active_alternating_activation_pool"] if str(id) != unit_id_str]
                response["removed_from_active_alternating_pool"] = True
                removed = True

        # Sub-phase 2: Non-active alternating pool (opponent's units)
        if not removed and "non_active_alternating_activation_pool" in game_state:
            pool_str = [str(id) for id in game_state["non_active_alternating_activation_pool"]]
            if unit_id_str in pool_str:
                game_state["non_active_alternating_activation_pool"] = [id for id in game_state["non_active_alternating_activation_pool"] if str(id) != unit_id_str]
                response["removed_from_non_active_alternating_pool"] = True
                removed = True

        if removed:
            response["removed_from_fight_pool"] = True  # Generic flag for compatibility
    
    # ├── Arg5 = 1 ?
    # │   ├── YES -> log the error
    # │   └── NO -> No action
    if arg5 == 1:
        if "error_logs" not in game_state:
            game_state["error_logs"] = []
        game_state["error_logs"].append({
            "unitId": unit_id,
            "phase": game_state["phase"],
            "timestamp": "server_time"
        })
        response["error_logged"] = True
    
    # └── Remove the green circle around the unit's icon
    response["clear_unit_selection"] = True
    response["clear_green_circle"] = True
    
    # AI_TURN.md COMPLIANCE: Clear shooting phase target selection
    if arg4 == "SHOOTING":
        response["clear_target_selection"] = True
        response["clear_target_blinking"] = True
        # Clear unit's selected target state
        if "selected_target_id" in unit:
            unit["selected_target_id"] = None
        # Clear valid target pool highlighting
        if "valid_target_pool" in unit:
            unit["valid_target_pool"] = []
    
    # Check if activation pool is empty after removal
    # CRITICAL: Use arg4 (explicit phase parameter) instead of game_state["phase"]
    # arg4 explicitly indicates which pool to check (MOVE, SHOOTING, CHARGE, FIGHT)
    # This is more reliable than game_state["phase"] which might not be set correctly
    pool_empty = False

    if arg4 in ["MOVE", "FLED"]:
        # Defensive: pool might not exist if phase not started
        if "move_activation_pool" not in game_state:
            pool_empty = True
        else:
            pool_empty = len(game_state["move_activation_pool"]) == 0
    elif arg4 == "SHOOTING":
        if "shoot_activation_pool" not in game_state:
            pool_empty = True
        else:
            pool_empty = len(game_state["shoot_activation_pool"]) == 0
    elif arg4 == "CHARGE":
        if "charge_activation_pool" not in game_state:
            pool_empty = True
        else:
            pool_empty = len(game_state["charge_activation_pool"]) == 0
    elif arg4 == "FIGHT":
        # DEBUG: Check if unit is ending activation without attacking when it should
        if arg3 == "PASS":
            from engine.game_utils import add_console_log, safe_print
            from shared.data_validation import require_key
            attack_left = require_key(unit, "ATTACK_LEFT")
            if attack_left > 0:
                # Unit is passing but has attacks left - check if adjacent to enemy
                from .fight_handlers import _is_adjacent_to_enemy_within_cc_range
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                if is_adjacent:
                    if "episode_number" in game_state and "turn" in game_state:
                        episode = game_state["episode_number"]
                        turn = game_state["turn"]
                        if "console_logs" not in game_state:
                            game_state["console_logs"] = []
                        log_msg = f"[FIGHT DEBUG] ⚠️ E{episode} T{turn} fight end_activation: Unit {unit['id']} ADJACENT to enemy but PASSING with ATTACK_LEFT={attack_left}"
                        add_console_log(game_state, log_msg)
                        safe_print(game_state, log_msg)
        
        # Fight phase complete when ALL 3 pools empty
        if "charging_activation_pool" not in game_state:
            charging_empty = True
        else:
            charging_empty = len(game_state["charging_activation_pool"]) == 0

        # AI_TURN.md line 727: "All charging units processed -> GO TO STEP : ATLERNATE_FIGHT"
        # AI_TURN.md lines 731-755: Build alternating pools ONLY when transitioning from charging to alternating
        # This happens when charging pool becomes empty AND we're removing a unit from charging pool
        # We do NOT rebuild after every activation - only when entering alternating phase
        if charging_empty and response.get("removed_from_charging_pool"):
            # Charging phase just completed - build alternating pools for the first time
            # AI_TURN.md lines 731-755: ACTIVE PLAYER ELIGIBILITY CHECK and NON-ACTIVE PLAYER ELIGIBILITY CHECK
            _rebuild_alternating_pools_for_fight(game_state)

        if "active_alternating_activation_pool" not in game_state:
            active_alt_empty = True
        else:
            active_alt_empty = len(game_state["active_alternating_activation_pool"]) == 0

        if "non_active_alternating_activation_pool" not in game_state:
            non_active_alt_empty = True
        else:
            non_active_alt_empty = len(game_state["non_active_alternating_activation_pool"]) == 0

        pool_empty = charging_empty and active_alt_empty and non_active_alt_empty
    # Note: COMMAND phase doesn't use end_activation, so no need to handle it here
    
    if pool_empty:
        response["phase_complete"] = True

    return response


def _rebuild_alternating_pools_for_fight(game_state: Dict[str, Any]) -> None:
    """
    Rebuild alternating activation pools after each activation in fight phase.

    CRITICAL: This function is called after EVERY activation in the fight phase.
    This ensures all eligible units are captured, even if they weren't in the initial pools
    or became eligible after other units died or changed status.

    This must be called BEFORE checking if the phase is complete.
    """
    current_player = game_state["current_player"]

    # AI_TURN.md COMPLIANCE: Ensure units_fought exists
    if "units_fought" not in game_state:
        game_state["units_fought"] = set()

    # AI_TURN.md COMPLIANCE: units_charged must exist
    if "units_charged" not in game_state:
        game_state["units_charged"] = set()

    # Rebuild alternating pools (units NOT in units_charged, adjacent to enemies)
    active_alternating = []
    non_active_alternating = []
    units_charged_set = {str(uid) for uid in game_state["units_charged"]}
    units_fought_set = {str(uid) for uid in game_state["units_fought"]}

    units_cache = require_key(game_state, "units_cache")
    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        player = cache_entry["player"]

        # Skip units that already charged (they had their turn)
        if str(unit_id) in units_charged_set:
            continue

        # Skip units that already fought
        if str(unit_id) in units_fought_set:
            continue

        is_adjacent = _is_adjacent_to_enemy_for_fight(game_state, unit)

        if is_adjacent:
            if player == current_player:
                active_alternating.append(unit_id)
            else:
                non_active_alternating.append(unit_id)

    game_state["active_alternating_activation_pool"] = active_alternating
    game_state["non_active_alternating_activation_pool"] = non_active_alternating


def _is_adjacent_to_enemy_for_fight(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Check if unit is adjacent to at least one enemy within CC_RNG.

    Used for fight phase eligibility - unit must be within melee range of an enemy.
    """
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of CC_RNG
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    unit_col, unit_row = require_unit_position(unit, game_state)

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy_id, cache_entry in units_cache.items():
        if int(cache_entry["player"]) != unit_player:
            enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
            distance = _calculate_hex_distance_for_fight(unit_col, unit_row, enemy_col, enemy_row)
            if distance <= cc_range:
                return True

    return False


def _calculate_hex_distance_for_fight(col1: int, row1: int, col2: int, row2: int) -> int:
    """
    Calculate hex distance using offset coordinates.
    Converts to cube coordinates for accurate distance calculation.
    """
    # Convert offset to cube coordinates (odd-q layout)
    def offset_to_cube(col: int, row: int) -> tuple:
        x = col
        z = row - (col - (col & 1)) // 2
        y = -x - z
        return (x, y, z)

    cube1 = offset_to_cube(col1, row1)
    cube2 = offset_to_cube(col2, row2)

    # Cube distance
    return max(abs(cube1[0] - cube2[0]), abs(cube1[1] - cube2[1]), abs(cube1[2] - cube2[2]))