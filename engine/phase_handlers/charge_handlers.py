#!/usr/bin/env python3
"""
charge_handlers.py - AI_TURN.md Charge Phase Implementation
Pure stateless functions implementing AI_TURN.md charge specification

References: AI_TURN.md Section ⚡ CHARGE PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from .generic_handlers import end_activation
from shared.data_validation import require_key
from engine.game_utils import add_console_log, safe_print
from engine.combat_utils import (
    normalize_coordinates,
    get_unit_by_id,
    get_hex_neighbors,
    expected_dice_value
)
from .shared_utils import (
    ACTION, WAIT, NO, ERROR, PASS, CHARGE,
    update_units_cache_position, is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
)

def _unit_has_rule(unit: Dict[str, Any], rule_id: str) -> bool:
    """Check if unit has a specific rule by ruleId."""
    unit_rules = require_key(unit, "UNIT_RULES")
    for rule in unit_rules:
        if require_key(rule, "ruleId") == rule_id:
            return True
    return False

def charge_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize charge phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "charge"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} charge units_cache={units_cache}")

    # Tracking sets are NOT cleared at charge phase start
    # They persist from movement phase (units_fled, units_moved, units_shot remain)

    # Clear charge preview state
    game_state["valid_charge_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = None
    game_state["charge_roll_values"] = {}  # Store 2d6 rolls per unit
    game_state["charge_target_selections"] = {}  # Store target selections per unit
    game_state["pending_charge_targets"] = []  # Store targets for gym training target selection
    game_state["pending_charge_unit_id"] = None  # Store unit ID waiting for target selection

    # PERFORMANCE: Pre-compute enemy_adjacent_hexes once at phase start for current player
    # Cache will be reused throughout the phase for all units (invalidated after each charge)
    current_player = require_key(game_state, "current_player")
    from .shared_utils import build_enemy_adjacent_hexes
    build_enemy_adjacent_hexes(game_state, current_player)

    # Build activation pool
    charge_build_activation_pool(game_state)

    # Console log (disabled in training mode for performance)
    add_console_log(game_state, "CHARGE POOL BUILT")

    # Check if phase complete immediately (no eligible units)
    pool_after_build = game_state["charge_activation_pool"]
    if not pool_after_build:
        return charge_phase_end(game_state)

    return {
        "phase_initialized": True,
        "eligible_units": len(pool_after_build),
        "phase_complete": False
    }


def charge_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build charge activation pool with eligibility checks
    """
    # CRITICAL: Clear pool before rebuilding (defense in depth)
    game_state["charge_activation_pool"] = []
    eligible_units = get_eligible_units(game_state)
    game_state["charge_activation_pool"] = list(eligible_units)  # Ensure it's a new list, not a reference

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} charge charge_activation_pool={eligible_units}")

def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md charge eligibility decision tree implementation.

    Charge Eligibility Requirements:
    - Alive (in units_cache)
    - player === current_player
    - NOT in units_charged
    - NOT adjacent to enemy (distance > melee_range to all enemies)
    - NOT in units_fled
    - Has valid charge target (enemy within charge range via pathfinding)

    Returns list of unit IDs eligible for charge activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]

    units_cache = require_key(game_state, "units_cache")
    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        unit_id_str = str(unit_id)

        # "unit.player === current_player?"
        if cache_entry["player"] != current_player:
            continue  # Wrong player

        # "NOT adjacent to enemy?"
        # CRITICAL FIX: Use direct hex distance calculation for reliable adjacency detection
        # Normalize coordinates to int to ensure consistent calculation
        unit_col_int, unit_row_int = require_unit_position(unit_id, game_state)
        adjacent_found = False
        for enemy_id, enemy_entry in units_cache.items():
            if enemy_entry["player"] != cache_entry["player"]:
                enemy_col_int, enemy_row_int = require_unit_position(enemy_id, game_state)
                hex_dist = _calculate_hex_distance(unit_col_int, unit_row_int, enemy_col_int, enemy_row_int)
                if hex_dist <= 1:  # Distance 1 = adjacent (melee range is always 1)
                    adjacent_found = True
                    break  # Stop checking other enemies - this unit is adjacent
        
        if adjacent_found:
            continue  # Already in melee, cannot charge

        # "NOT in units_fled?"
        # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
        if unit_id_str in game_state["units_fled"]:
            continue  # Fled units cannot charge

        # ADVANCE_IMPLEMENTATION: Units that advanced cannot charge
        units_advanced = require_key(game_state, "units_advanced")
        if unit_id_str in units_advanced:
            if not _unit_has_rule(unit, "charge_after_advance"):
                continue  # Advanced units cannot charge without rule

        # "Has valid charge target?"
        # Must have at least one enemy within charge range (via BFS pathfinding)
        if not _has_valid_charge_target(game_state, unit):
            continue  # No valid charge targets

        # Unit passes all conditions - add to pool
        eligible_units.append(unit_id_str)

    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Charge phase handler action routing with complete autonomy
    """
    # Handler self-initialization on first action
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "phase" not in game_state:
        game_state_phase = None
    else:
        game_state_phase = game_state["phase"]

    if "charge_activation_pool" not in game_state:
        charge_pool_exists = False
    else:
        charge_pool_exists = bool(game_state["charge_activation_pool"])

    if game_state_phase != "charge" or not charge_pool_exists:
        charge_phase_start(game_state)

    # Pool empty? -> Phase complete
    if not game_state["charge_activation_pool"]:
        return True, charge_phase_end(game_state)
    
    # Get unit from action (frontend specifies which unit to charge)
    # AI_TURN.md COMPLIANCE: Direct field access - no defaults
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = None  # Allow None for gym training auto-selection
    else:
        action_type = action["action"]
        unit_id = action["unitId"]

    # For gym training or PvE AI, if no unitId specified, use first eligible unit
    if not unit_id:
        config_gym_mode = config["gym_training_mode"] if "gym_training_mode" in config else False
        state_gym_mode = game_state["gym_training_mode"] if "gym_training_mode" in game_state else False
        is_gym_training = config_gym_mode or state_gym_mode
        current_player = require_key(game_state, "current_player")
        is_pve_ai = config.get("pve_mode", False) and current_player == 2
        if not is_gym_training and not is_pve_ai:
            return False, {
                "error": "unit_id_required",
                "action": action_type,
                "message": "unitId is required for human-controlled charge activation"
            }
        if game_state["charge_activation_pool"]:
            unit_id = game_state["charge_activation_pool"][0]
        else:
            return True, charge_phase_end(game_state)

    # Validate unit is eligible (keep for validation, remove only after successful action)
    if unit_id not in game_state["charge_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id, "action": action_type}

    # Get unit object for processing
    active_unit = get_unit_by_id(game_state, unit_id)
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id, "action": action_type}

    # Flag detection for consistent behavior
    # AI_TURN.md COMPLIANCE: Direct field access with explicit validation
    if "gym_training_mode" not in config:
        config_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        config_gym_mode = config["gym_training_mode"]

    if "gym_training_mode" not in game_state:
        state_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        state_gym_mode = game_state["gym_training_mode"]

    is_gym_training = config_gym_mode or state_gym_mode

    # Auto-activate unit if not already activated and preview not shown
    # AI_TURN.md COMPLIANCE: Direct field access with explicit check
    if "active_charge_unit" not in game_state:
        active_charge_unit_exists = False
    else:
        active_charge_unit_exists = bool(game_state["active_charge_unit"])

    if not active_charge_unit_exists and action_type in ["charge", "left_click"]:
        if is_gym_training:
            # AI_TURN.md COMPLIANCE: In gym training, ActionDecoder may construct complete charge action
            # Check if action already has targetId and destCol/destRow (complete charge action)
            if "targetId" in action and "destCol" in action and "destRow" in action:
                # Action already has target and destination - execute charge directly, no waiting needed
                # Just ensure unit is activated, then execute charge via destination selection handler
                charge_unit_activation_start(game_state, unit_id)
                # Roll 2d6 and build destinations for validation (needed for charge execution)
                execution_result = charge_unit_execution_loop(game_state, unit_id)
                # Execute charge directly via destination selection handler
                return charge_destination_selection_handler(game_state, unit_id, action)
            else:
                # No target/destination yet - activate unit to get targets (will auto-select and execute)
                return _handle_unit_activation(game_state, active_unit, config)
        else:
            # Human players: activate and return waiting_for_player
            return _handle_unit_activation(game_state, active_unit, config)

    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)

    elif action_type == "charge":
        # Route based on what's in the action:
        # - If targetId but no destCol/destRow -> target selection (roll, build pool, preview)
        # - If destCol/destRow -> destination selection (execute charge)
        if "targetId" in action and "destCol" not in action:
            # Target selection step
            return charge_target_selection_handler(game_state, unit_id, action)
        elif "destCol" in action and "destRow" in action:
            # Destination selection step
            return charge_destination_selection_handler(game_state, unit_id, action)
        else:
            return False, {"error": "invalid_charge_action", "action": action}

    elif action_type == "skip":
        # Ignore skip action if unit is not active in charge phase
        # This prevents skip actions from shooting phase being processed in charge phase
        active_charge_unit = game_state.get("active_charge_unit")
        if active_charge_unit != unit_id:
            # CRITICAL: In gym training mode, skip must NOT trigger activation or movement.
            # Determine had_valid_destinations without executing charge logic.
            if is_gym_training:
                valid_targets = charge_build_valid_targets(game_state, unit_id)
                had_valid_destinations = len(valid_targets) > 0
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=had_valid_destinations)
            # Unit is in pool but not active - return no effect (don't remove from pool)
            return True, {"action": "no_effect", "unitId": unit_id, "reason": "unit_not_active_in_charge_phase"}
        # AI_TURN.md Line 515: Agent chooses wait (has valid destinations, chooses to skip)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=True)

    elif action_type == "left_click":
        return charge_click_handler(game_state, unit_id, action)

    elif action_type == "right_click":
        # AI_TURN.md Line 536: Human cancels (right-click on active unit)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)

    elif action_type == "invalid":
        # Handle invalid actions with training penalty
        if unit_id in game_state["charge_activation_pool"]:
            # Clear preview first
            charge_clear_preview(game_state)

            # Invalid action during charge phase
            result = end_activation(
                game_state, active_unit,
                ERROR,       # Arg1: Error logging (invalid action)
                1,           # Arg2: +1 step increment
                PASS,        # Arg3: No tracking
                CHARGE,      # Arg4: Remove from charge pool
                1            # Arg5: Error logging
            )
            result["invalid_action_penalty"] = True
            # CRITICAL: No default value - require explicit attempted_action
            attempted_action = action.get("attempted_action")
            if attempted_action is None:
                raise ValueError(f"Action missing 'attempted_action' field: {action}")
            result["attempted_action"] = attempted_action
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id, "action": action_type}

    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "charge"}


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Charge unit activation start + execution loop"""
    # Unit activation start
    charge_unit_activation_start(game_state, unit["id"])

    # Unit execution loop (automatic)
    execution_result = charge_unit_execution_loop(game_state, unit["id"])

    # Clean flag detection
    # AI_TURN.md COMPLIANCE: Direct field access with explicit validation
    if "gym_training_mode" not in config:
        config_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        config_gym_mode = config["gym_training_mode"]

    if "gym_training_mode" not in game_state:
        state_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        state_gym_mode = game_state["gym_training_mode"]

    is_gym_training = config_gym_mode or state_gym_mode

    # AI_TURN.md COMPLIANCE: In gym training, AI executes charge directly without waiting_for_player
    # AI_TURN.md lines 1375-1402: AI selects target, builds destinations, selects destination, executes charge - all in one sequence
    if is_gym_training and isinstance(execution_result, tuple) and execution_result[0]:
        # AI_TURN.md COMPLIANCE: Direct field access
        if "waiting_for_player" not in execution_result[1]:
            waiting_for_player = False
        else:
            waiting_for_player = execution_result[1]["waiting_for_player"]

        if waiting_for_player:
            if "valid_targets" not in execution_result[1]:
                raise KeyError("Execution result missing required 'valid_targets' field")
            valid_targets = execution_result[1]["valid_targets"]

            if valid_targets:
                # AI_TURN.md: AI selects best target automatically and executes charge directly
                # Do NOT return waiting_for_player=True - execute charge automatically
                # Select best target (first target for now, can be improved with strategic selection)
                selected_target = valid_targets[0]
                target_id = selected_target["id"]
                
                # Execute target selection handler which will roll 2d6, build destinations, and execute charge
                # This follows AI_TURN.md: roll → select target → build destinations → select destination → execute
                from engine.phase_handlers.charge_handlers import charge_target_selection_handler
                target_action = {
                    "action": "charge",
                    "unitId": unit["id"],
                    "targetId": target_id
                }
                return charge_target_selection_handler(game_state, unit["id"], target_action)
            else:
                # No valid targets - auto skip
                return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # All non-gym players (humans AND PvE AI) get normal waiting_for_player response
    return execution_result


def _ai_select_charge_target_pve(game_state: Dict[str, Any], unit: Dict[str, Any], valid_targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    PvE AI selects charge target using priority logic per AI_TURN.md.

    Priority order:
    1. Enemy closest to death (lowest HP_CUR)
    2. Highest threat (max of all weapons: STR × NB)
    """
    if not valid_targets:
        return None

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate threat from all weapons
    # Calculate priority score for each target
    def priority_score(t):
        # Priority 1: Lowest HP (higher priority = lower HP) (Phase 2: HP from cache)
        hp_cur = require_hp_from_cache(str(t["id"]), game_state)
        hp_priority = -hp_cur  # Negative so lower HP = higher score

        # Priority 2: Highest threat
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate threat from all weapons
        melee_threat = 0.0
        if t.get("CC_WEAPONS"):
            # Calculate max threat from all melee weapons
            for weapon in t["CC_WEAPONS"]:
                threat = require_key(weapon, "STR") * expected_dice_value(require_key(weapon, "NB"), "charge_melee_nb")
                melee_threat = max(melee_threat, threat)
        
        ranged_threat = 0.0
        if t.get("RNG_WEAPONS"):
            # Calculate max threat from all ranged weapons
            for weapon in t["RNG_WEAPONS"]:
                threat = require_key(weapon, "STR") * expected_dice_value(require_key(weapon, "NB"), "charge_ranged_nb")
                ranged_threat = max(ranged_threat, threat)
        
        threat = max(melee_threat, ranged_threat)

        return (hp_priority, threat)

    # Select target with highest priority
    best_target = max(valid_targets, key=priority_score)
    return best_target


def charge_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Charge unit activation initialization - NO ROLL YET.
    
    NEW RULE: At activation, unit can wait or choose a target.
    The charge roll is performed ONLY AFTER target selection.
    """
    game_state["valid_charge_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = unit_id
    # Do NOT roll 2d6 here - roll happens after target selection


def charge_build_valid_targets(game_state: Dict[str, Any], unit_id: str) -> List[Dict[str, Any]]:
    """
    Build list of valid charge targets for unit activation.
    
    Valid target criteria:
    - Enemy unit
    - within charge_max_distance hexes (via BFS pathfinding)
    - having non occupied adjacent hex(es) at 12 hexes or less from the active unit
    
    Returns list of target dicts with unit info.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return []
    
    CHARGE_MAX_DISTANCE = 12
    valid_targets = []
    
    # Build all hexes reachable via BFS within max charge distance
    try:
        reachable_hexes = charge_build_valid_destinations_pool(game_state, unit_id, CHARGE_MAX_DISTANCE)
    except Exception as e:
        add_console_log(game_state, f"ERROR: BFS failed for unit {unit_id}: {str(e)}")
        return []
    
    if not reachable_hexes:
        return []  # No reachable hexes
    
    # Get all enemies - CRITICAL: is_unit_alive so dead units never enter pool
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
               if int(cache_entry["player"]) != unit_player]
    
    from engine.utils.weapon_helpers import get_melee_range
    melee_range = get_melee_range()  # Always 1
    
    # For each enemy, check if:
    # 1. Unit is NOT already adjacent to this enemy (CRITICAL: cannot charge from adjacent hex)
    # 2. Enemy is within charge_max_distance (via BFS - at least one reachable hex is adjacent to enemy)
    # 3. Enemy has at least one non-occupied adjacent hex that is reachable
    unit_col_int, unit_row_int = require_unit_position(unit, game_state)
    
    for enemy_id in enemies:
        enemy_col_int, enemy_row_int = require_unit_position(enemy_id, game_state)
        
        # CRITICAL: Check if unit is already adjacent to this enemy
        # RULE: Cannot charge from adjacent hex (must be at distance > melee_range)
        distance_from_unit_to_enemy = _calculate_hex_distance(unit_col_int, unit_row_int, enemy_col_int, enemy_row_int)
        if distance_from_unit_to_enemy <= melee_range:
            # Unit is already adjacent to this enemy - cannot charge
            continue
        
        # Check if any reachable hex is adjacent to this enemy
        has_adjacent_reachable_hex = False
        non_occupied_adjacent_hexes = []
        
        for dest_col, dest_row in reachable_hexes:
            distance_to_enemy = _calculate_hex_distance(dest_col, dest_row, enemy_col_int, enemy_row_int)
            if 0 < distance_to_enemy <= melee_range:
                # This reachable hex is adjacent to enemy
                has_adjacent_reachable_hex = True
                
                # Check if this hex is not occupied
                is_occupied = False
                for check_id in units_cache.keys():
                    if check_id != str(unit["id"]):
                        check_pos = get_unit_position(check_id, game_state)
                        if check_pos is None:
                            continue
                        check_col, check_row = check_pos
                        if check_col == dest_col and check_row == dest_row:
                            is_occupied = True
                            break
                
                if not is_occupied:
                    non_occupied_adjacent_hexes.append((dest_col, dest_row))
        
        # Target is valid if it has at least one non-occupied adjacent hex reachable
        if has_adjacent_reachable_hex and non_occupied_adjacent_hexes:
            enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
            valid_targets.append({
                "id": enemy_id,
                "col": enemy_col,
                "row": enemy_row,
                "HP_CUR": require_hp_from_cache(str(enemy_id), game_state),
                "player": units_cache[enemy_id]["player"]
            })
    
    return valid_targets


def charge_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Charge unit execution loop - build and return valid charge targets.
    
    NEW RULE: At activation, show all possible charge targets without rolling.
    The roll happens AFTER target selection.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Build valid targets (enemies with non-occupied adjacent hexes reachable within 12 hexes)
    valid_targets = charge_build_valid_targets(game_state, unit_id)

    # Check if valid targets exist
    if not valid_targets:
        # No valid targets - pass (no step increment, no tracking)
        return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # Extract target IDs for blinking effect (PvP and PvE modes only)
    target_ids = [str(target["id"]) for target in valid_targets]
    
    # Check if PvP or PvE mode (not gym training)
    is_pve = game_state.get("pve_mode", False) or game_state.get("is_pve_mode", False)
    is_gym = game_state.get("gym_training_mode", False)
    should_blink = not is_gym  # Blink in PvP and PvE, not in gym training
    
    result = {
        "unit_activated": True,
        "unitId": unit_id,
        "charge_roll": None,  # No roll yet - will be rolled after target selection
        "valid_targets": valid_targets,  # List of target dicts
        "waiting_for_player": True
    }
    
    # Add blinking effect for PvP and PvE modes
    if should_blink:
        result["blinking_units"] = target_ids
        result["start_blinking"] = True
    
    return True, result


def _attempt_charge_to_destination(game_state: Dict[str, Any], unit: Dict[str, Any], dest_col: int, dest_row: int, target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md charge execution with destination validation.

    Implements AI_TURN.md charge restrictions:
    - Must end adjacent to target enemy
    - Within charge_range (2d6 roll result)
    - Path must be reachable via BFS pathfinding
    """
    # CRITICAL: Check units_fled just before execution (may have changed during phase)
    # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
    if str(unit["id"]) in require_key(game_state, "units_fled"):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        log_msg = f"[CHARGE ERROR] E{episode} T{turn} Unit {unit['id']} attempted to charge but has fled - REJECTED"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        import logging
        logging.basicConfig(filename='step.log', level=logging.INFO, format='%(message)s')
        logging.info(log_msg)
        return False, {"error": "unit_has_fled", "unitId": unit["id"], "action": "charge"}
    
    # NOTE: Pool is already built in charge_destination_selection_handler() after roll.
    # Since system is sequential, no need to rebuild here. Only verify destination is in pool.
    unit_id = unit["id"]
    if unit_id not in game_state["charge_roll_values"]:
        raise KeyError(f"Unit {unit_id} missing charge_roll_values")
    charge_roll = game_state["charge_roll_values"][unit_id]
    
    # Check if destination is in the pool (built after roll in charge_destination_selection_handler)
    dest_tuple = (int(dest_col), int(dest_row))
    pool = require_key(game_state, "valid_charge_destinations_pool")
    if dest_tuple not in pool:
        return False, {"error": "destination_not_in_pool", "target": (dest_col, dest_row), "action": "charge"}
    
    # Validate destination per AI_TURN.md charge rules
    if not _is_valid_charge_destination(game_state, dest_col, dest_row, unit, target_id, charge_roll, config):
        return False, {"error": "invalid_charge_destination", "target": (dest_col, dest_row), "action": "charge"}

    # Store original position
    orig_col, orig_row = require_unit_position(unit, game_state)

    # CRITICAL: Final occupation check IMMEDIATELY before position assignment
    # This prevents race conditions where multiple units select the same destination
    # before any of them have moved. Must check JUST before assignment, not earlier.
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "charge")
    # CRITICAL: Normalize destination coordinates to int for consistent comparison
    dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)
    
    # Check all units for occupation - CRITICAL: Normalize all coordinates for comparison
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    for check_id in units_cache.keys():
        # CRITICAL: Normalize coordinates for consistent comparison
        try:
            check_pos = get_unit_position(check_id, game_state)
            if check_pos is None:
                continue
            check_col, check_row = check_pos
        except (ValueError, TypeError, KeyError):
            # Skip units with invalid positions (should not happen, but defensive)
            continue
        
        # CRITICAL: Compare as normalized integers to avoid type mismatch
        if (check_id != unit_id_str and
            check_col == dest_col_int and
            check_row == dest_row_int):
            # Another unit already occupies this destination - prevent collision
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_msg = f"[CHARGE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot charge to ({dest_col_int},{dest_row_int}) - occupied by Unit {check_id}"
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)
            import logging
            logging.basicConfig(filename='step.log', level=logging.INFO, format='%(message)s')
            logging.info(log_msg)
            return False, {
                "error": "charge_destination_occupied",
                "occupant_id": check_id,
                "destination": (dest_col_int, dest_row_int)
            }

    # Execute charge - position assignment happens immediately after occupation check
    # CRITICAL: Log ALL position changes to detect unauthorized modifications
    # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
    log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) via CHARGE"
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)
    
    # CRITICAL: Normalize coordinates before assignment
    from engine.combat_utils import set_unit_coordinates
    set_unit_coordinates(unit, dest_col_int, dest_row_int)
    from engine.game_utils import conditional_debug_print
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: col set to {unit['col']}")
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")

    # Update units_cache after position change
    update_units_cache_position(game_state, str(unit["id"]), dest_col_int, dest_row_int)

    # AI_TURN_SHOOTING_UPDATE.md: No need to invalidate los_cache here
    # The new architecture uses unit["los_cache"] which is built at unit activation in shooting phase
    # When a unit charges, los_cache doesn't exist yet (built at shooting activation)
    # Old code: _invalidate_los_cache_for_moved_unit(game_state, unit["id"]) - OBSOLETE

    # Mark as units_charged (NOT units_moved)
    game_state["units_charged"].add(unit["id"])

    # PERFORMANCE: Invalidate enemy_adjacent_hexes cache after charge movement
    # Unit positions have changed, so adjacent hexes need recalculation
    # Remove cache for both players (positions affect adjacency for both sides)
    current_player = require_key(game_state, "current_player")
    enemy_player = 3 - current_player  # Player 1 <-> Player 2
    cache_key_current = f"enemy_adjacent_hexes_player_{current_player}"
    cache_key_enemy = f"enemy_adjacent_hexes_player_{enemy_player}"
    if cache_key_current in game_state:
        del game_state[cache_key_current]
    if cache_key_enemy in game_state:
        del game_state[cache_key_enemy]

    # CRITICAL: Invalidate all destination pools after charge movement
    # Positions have changed, so all pools (move, charge, shoot) are now stale
    from .movement_handlers import _invalidate_all_destination_pools_after_movement
    _invalidate_all_destination_pools_after_movement(game_state)

    # Clear charge roll, target selection, and pending targets after use
    if "charge_roll_values" in game_state and unit_id in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit_id]
    if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
        del game_state["charge_target_selections"][unit_id]
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    return True, {
        "action": "charge",
        "unitId": unit["id"],
        "targetId": target_id,
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "charge_roll": charge_roll
    }


def _is_valid_charge_destination(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any],
                                 target_id: str, charge_roll: int, config: Dict[str, Any]) -> bool:
    """
    AI_TURN.md charge destination validation.

    Charge destination requirements:
    - Within board bounds
    - NOT a wall
    - NOT occupied by another unit
    - Adjacent to target enemy (distance <= melee_range from target) - GUARANTEED by pool
    - Reachable within charge_range (2d6 roll) via BFS pathfinding - GUARANTEED by pool

    NOTE: Pool already guarantees adjacency and reachability. This function only does defensive checks.
    """
    # CRITICAL: Convert coordinates to int for consistent comparison
    col_int, row_int = int(col), int(row)
    
    # Board bounds check
    if (col_int < 0 or row_int < 0 or
        col_int >= game_state["board_cols"] or
        row_int >= game_state["board_rows"]):
        return False

    # Wall collision check
    if (col_int, row_int) in game_state["wall_hexes"]:
        return False

    # Unit occupation check (defensive - pool already filters occupied hexes)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    for other_id in units_cache.keys():
        if other_id != unit_id_str:
            other_col, other_row = require_unit_position(other_id, game_state)
            if other_col == col_int and other_row == row_int:
                return False

    # CRITICAL: Verify destination is in the valid pool
    # The pool guarantees: adjacent to enemy, not occupied, reachable with charge_roll
    if "valid_charge_destinations_pool" not in game_state:
        return False  # Pool not built - invalid destination
    
    valid_pool = game_state["valid_charge_destinations_pool"]
    if (col_int, row_int) not in valid_pool:
        return False  # Destination not in valid pool - not reachable with this charge_roll or not adjacent to enemy
    
    return True


def _has_valid_charge_target(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Check if unit has at least one valid charge target.

    AI_TURN.md Line 495: "Enemies exist within charge_max_distance hexes?"
    AI_TURN.md Line 562: "Enemy units within charge_max_distance hexes (via pathfinding)"

    CRITICAL: Must use BFS pathfinding distance, not straight-line distance.
    Build reachable hexes within max charge distance and check if any enemy
    is adjacent to those hexes.
    
    NOTE: Target can be at distance 13 because charge of 12 can reach adjacent to target at 13.
    """
    # Maximum possible charge distance is 12 hexes (2d6 max roll)
    # But target can be at distance 13 because charge ends adjacent to target
    CHARGE_MAX_DISTANCE = 12
    TARGET_MAX_DISTANCE = 13  # Target can be 1 hex further (charge ends adjacent)

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
    from engine.utils.weapon_helpers import get_melee_range
    
    try:
        # Build all hexes reachable via BFS within max charge distance
        # Use the existing charge_build_valid_destinations_pool with max roll
        reachable_hexes = charge_build_valid_destinations_pool(game_state, unit["id"], CHARGE_MAX_DISTANCE)
    except Exception as e:
        # If BFS fails, log error and return False (no valid targets)
        add_console_log(game_state, f"ERROR: BFS failed for unit {unit['id']}: {str(e)}")
        return False

    # Check if any enemy is within melee range of any reachable hex
    cc_range = get_melee_range()  # Always 1

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy_id, enemy_entry in units_cache.items():
        if int(enemy_entry["player"]) != unit_player:
            # Check if enemy is within CC_RNG of any reachable hex
            enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
            for dest_col, dest_row in reachable_hexes:
                distance_to_enemy = _calculate_hex_distance(dest_col, dest_row, enemy_col, enemy_row)
                if 0 < distance_to_enemy <= cc_range:
                    # Found a reachable hex adjacent to this enemy
                    return True
            
            # NEW: Also check if enemy is at distance 13 (charge of 12 can reach adjacent to target at 13)
            # Calculate distance from unit to enemy
            unit_col, unit_row = require_unit_position(unit, game_state)
            distance_to_enemy = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
            if distance_to_enemy == TARGET_MAX_DISTANCE:
                # Check if there's a path of 12 hexes that can reach adjacent to this enemy
                # This means we need to check if any hex adjacent to enemy is reachable in 12 moves
                enemy_neighbors = get_hex_neighbors(enemy_col, enemy_row)
                for neighbor_col, neighbor_row in enemy_neighbors:
                    # Check if this neighbor is reachable in 12 moves from unit
                    neighbor_distance = _calculate_hex_distance(unit_col, unit_row, neighbor_col, neighbor_row)
                    if neighbor_distance <= CHARGE_MAX_DISTANCE:
                        # Check if this neighbor is in reachable hexes (pathfinding check)
                        if (neighbor_col, neighbor_row) in reachable_hexes:
                            return True

    return False


def _is_adjacent_to_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md adjacency check logic.

    Check if unit is adjacent to enemy (used for charge eligibility).

    CRITICAL: Use proper hexagonal adjacency check for consistency.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    # CRITICAL: Normalize coordinates BEFORE any calculations to ensure proper tuple comparison
    unit_col, unit_row = require_unit_position(unit, game_state)

    # CRITICAL FIX: Use hex distance calculation directly
    # This is more reliable than get_hex_neighbors() which may have bugs
    # Distance <= cc_range = adjacent (cc_range is always 1 for melee)
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy_id, enemy_entry in units_cache.items():
        if int(enemy_entry["player"]) != unit_player:
            # CRITICAL: Normalize enemy coordinates before distance calculation
            enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
            hex_dist = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
            if hex_dist <= cc_range:
                return True
    return False


def _is_hex_adjacent_to_enemy(game_state: Dict[str, Any], col: int, row: int, player: int,
                               enemy_adjacent_hexes: Set[Tuple[int, int]] = None) -> bool:
    """
    AI_TURN.md adjacency restriction implementation.

    Check if hex position is adjacent to any enemy unit.

    CRITICAL FIX: Use proper hexagonal adjacency, not Chebyshev distance.
    Hexagonal grids require checking if enemy position is in the list of 6 neighbors.

    PERFORMANCE: If enemy_adjacent_hexes set is provided, uses O(1) set lookup
    instead of O(n) iteration through all units.
    """
    # PERFORMANCE: Use pre-computed set if available (5-10x speedup)
    if enemy_adjacent_hexes is not None:
        return (col, row) in enemy_adjacent_hexes

    # Calcul dynamique si aucun cache n'est fourni (comportement historique)
    hex_neighbors = set(get_hex_neighbors(col, row))

    units_cache = require_key(game_state, "units_cache")
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = require_unit_position(enemy_id, game_state)
            # Check if enemy is in our 6 neighbors (true hex adjacency)
            if enemy_pos in hex_neighbors:
                return True
    return False


def _find_adjacent_enemy_at_destination(game_state: Dict[str, Any], col: int, row: int, player: int) -> Optional[str]:
    """
    Find an enemy unit adjacent to the given hex position.

    Used by gym training to auto-select charge target based on destination.
    Returns the ID of the first adjacent enemy, or None if no adjacent enemy.
    
    CRITICAL FIX: Also checks if enemy is ON the destination (distance == 0) and
    verifies that the destination is not occupied before returning target_id.
    """
    # First check if destination itself is occupied by an enemy (distance == 0)
    units_cache = require_key(game_state, "units_cache")
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = require_unit_position(enemy_id, game_state)
            if enemy_pos == (col, row):
                # Enemy is ON the destination - this is invalid for charge
                return None
    
    # Then check neighbors (adjacent enemies, distance == 1)
    hex_neighbors = set(get_hex_neighbors(col, row))
    adjacent_enemies = []
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = require_unit_position(enemy_id, game_state)
            if enemy_pos in hex_neighbors:
                adjacent_enemies.append(enemy_id)
    
    if adjacent_enemies:
        result_id = adjacent_enemies[0]
        return result_id
    else:
        return None


def _is_traversable_hex(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any],
                        occupied_positions: set) -> bool:
    """
    Check if a hex can be traversed (moved through) during pathfinding.

    A hex is traversable if it's:
    - Within board bounds
    - NOT a wall
    - NOT occupied by another unit

    Note: We check enemy adjacency separately in _is_valid_destination

    PERFORMANCE: Uses pre-computed occupied_positions set for O(1) lookup.
    occupied_positions must be provided (use pre-computed set from BFS).
    """
    # Board bounds check
    if (col < 0 or row < 0 or
        col >= game_state["board_cols"] or
        row >= game_state["board_rows"]):
        return False

    # Wall check - CRITICAL: Can't move through walls
    if (col, row) in game_state["wall_hexes"]:
        return False

    # Unit occupation check - CRITICAL: Use pre-computed set for O(1) lookup
    # CRITICAL: Convert coordinates to int for consistent tuple comparison
    # Use int(float(...)) to match the conversion used in occupied_positions construction
    col_int, row_int = int(float(col)), int(float(row))
    if (col_int, row_int) in occupied_positions:
        return False

    return True


def charge_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str, charge_roll: int, target_id: Optional[str] = None) -> List[Tuple[int, int]]:
    """
    Build valid charge destinations using BFS pathfinding.

    CRITICAL: Charge destinations must:
    - Be reachable within charge_roll distance (2d6) via BFS
    - End adjacent to target enemy (within melee range) if target_id provided, or any enemy if not
    - Not be blocked by walls or units

    Unlike movement, charges CAN move through hexes adjacent to enemies.
    
    Args:
        target_id: Optional target unit ID. If provided, only hexes adjacent to this target are included.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    charge_range = charge_roll  # 2d6 result
    # CRITICAL: Normalize coordinates to int for consistent tuple comparison
    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)

    # Get target enemy if specified, otherwise all enemies
    if target_id:
        target = get_unit_by_id(game_state, target_id)
        if not target or target["player"] == unit["player"] or not is_unit_alive(str(target["id"]), game_state):
            return []  # Invalid target
        enemies = [target]
    else:
        # Get all enemy positions for adjacency checks (used during activation preview)
        units_cache = require_key(game_state, "units_cache")
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]
        if not enemies:
            return []  # No enemies to charge

    # PERFORMANCE: Pre-compute occupied positions
    # CRITICAL: Normalize coordinates to int to ensure consistent tuple comparison
    # CRITICAL: Use try-except to handle invalid coordinates gracefully
    occupied_positions = set()
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    for u_id in units_cache.keys():
        if u_id != unit_id_str:
            try:
                col_int, row_int = require_unit_position(u_id, game_state)
                occupied_positions.add((col_int, row_int))
            except (ValueError, TypeError, KeyError) as e:
                # Skip units with invalid positions (should not happen, but defensive)
                # Log this as it indicates a data integrity issue
                if "episode_number" in game_state and "turn" in game_state:
                    episode = game_state.get("episode_number", "?")
                    turn = game_state.get("turn", "?")
                    # CRITICAL: Use actual values if available, otherwise indicate missing
                    unit_id_log = u_id
                    unit_col_log = "MISSING_COL"
                    unit_row_log = "MISSING_ROW"
                    log_msg = f"[CHARGE OCCUPIED_POSITIONS] E{episode} T{turn} SKIPPED Unit {unit_id_log} at ({unit_col_log},{unit_row_log}) - Error: {e}"
                    add_console_log(game_state, log_msg)
                    safe_print(game_state, log_msg)
                continue
    
    # CRITICAL: Log occupied positions and all units for debugging position bugs
    if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        phase = game_state.get("phase", "charge")
        def _hp_display(uid, gs):
            h = get_hp_from_cache(str(uid), gs)
            return h if h is not None else "dead"
        all_units_info = []
        for u_id in units_cache.keys():
            u_col, u_row = require_unit_position(u_id, game_state)
            all_units_info.append(f"Unit {u_id} at ({int(u_col)},{int(u_row)}) HP={_hp_display(u_id, game_state)}")
        log_message = f"[CHARGE DEBUG] E{episode} T{turn} {phase} charge_build_valid_destinations Unit {unit_id}: occupied_positions={occupied_positions} all_units={all_units_info}"
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)

    # BFS pathfinding to find all reachable hexes within charge_range
    visited = {start_pos: 0}
    queue = [(start_pos, 0)]
    valid_destinations = []

    while queue:
        current_pos, current_dist = queue.pop(0)
        current_col, current_row = current_pos

        # If we've reached max charge range, don't explore further
        if current_dist >= charge_range:
            continue

        # Explore all 6 hex neighbors
        neighbors = get_hex_neighbors(current_col, current_row)

        for neighbor_col, neighbor_row in neighbors:
            # CRITICAL: Convert coordinates to int IMMEDIATELY to ensure all tuples are (int, int)
            # This prevents type mismatch bugs in visited dict, valid_destinations list, and queue
            neighbor_col_int, neighbor_row_int = int(neighbor_col), int(neighbor_row)
            neighbor_pos = (neighbor_col_int, neighbor_row_int)
            neighbor_dist = current_dist + 1

            # Skip if already visited
            if neighbor_pos in visited:
                continue

            # Check if traversable (not wall, not occupied)
            if not _is_traversable_hex(game_state, neighbor_col_int, neighbor_row_int, unit, occupied_positions):
                continue

            # Mark as visited
            visited[neighbor_pos] = neighbor_dist

            # Check if this hex is adjacent to target enemy (or any enemy if no target specified)
            # CRITICAL: If target_id provided, only check adjacency to that specific target
            is_adjacent_to_enemy = False
            hex_is_occupied_by_enemy = False
            from engine.utils.weapon_helpers import get_melee_range
            melee_range = get_melee_range()  # Always 1
            for enemy_id in enemies:
                # CRITICAL: Normalize enemy coordinates for consistent distance calculation
                enemy_col_int, enemy_row_int = require_unit_position(enemy_id, game_state)
                distance_to_enemy = _calculate_hex_distance(neighbor_col_int, neighbor_row_int, enemy_col_int, enemy_row_int)
                if distance_to_enemy == 0:
                    # Enemy is ON this hex - mark as occupied and skip
                    hex_is_occupied_by_enemy = True
                    break
                elif 0 < distance_to_enemy <= melee_range:
                    is_adjacent_to_enemy = True
                    # If target_id specified, we only need to check this one target
                    if target_id:
                        break
                    # Otherwise continue checking other enemies to ensure no enemy is ON the hex

            # CRITICAL: Only add as destination if adjacent to an enemy AND NOT OCCUPIED
            # Use pre-computed occupied_positions set for O(1) lookup (no redundant loop)
            if is_adjacent_to_enemy and not hex_is_occupied_by_enemy and neighbor_pos != start_pos:
                # CRITICAL: Use pre-computed occupied_positions set for O(1) lookup
                # This is consistent with movement_handlers.py and avoids redundant loops
                if neighbor_pos not in occupied_positions:
                    valid_destinations.append(neighbor_pos)

            # Continue exploring (charges can move through enemy-adjacent hexes)
            queue.append((neighbor_pos, neighbor_dist))

    game_state["valid_charge_destinations_pool"] = valid_destinations

    return valid_destinations


def _calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Calculate proper hex distance using cube coordinates - SYNCHRONIZED WITH FRONTEND"""
    # CRITICAL FIX: Use EXACT same formula as frontend/src/utils/gameHelpers.ts offsetToCube()
    # Frontend formula: x = col, z = row - ((col - (col & 1)) >> 1), y = -x - z

    # Convert offset to cube coordinates (FRONTEND-COMPATIBLE)
    x1 = col1
    z1 = row1 - ((col1 - (col1 & 1)) >> 1)
    y1 = -x1 - z1

    x2 = col2
    z2 = row2 - ((col2 - (col2 & 1)) >> 1)
    y2 = -x2 - z2

    # Cube distance (max of absolute differences)
    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


def _select_strategic_destination(
    strategy_id: int,
    valid_destinations: List[Tuple[int, int]],
    unit: Dict[str, Any],
    game_state: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Select movement destination based on strategic heuristic.
    AI_TURN.md COMPLIANCE: Pure stateless function with direct field access.

    Args:
        strategy_id: 0=aggressive, 1=tactical, 2=defensive, 3=random
        valid_destinations: List of valid (col, row) tuples from BFS
        unit: Unit dict with position and stats
        game_state: Full game state for enemy detection

    Returns:
        Selected destination (col, row)
    """
    from engine.combat_utils import has_line_of_sight

    # Direct field access with validation
    if "units" not in game_state:
        raise KeyError("game_state missing required 'units' field")
    if "col" not in unit or "row" not in unit:
        raise KeyError(f"Unit missing required position fields: {unit}")
    if "player" not in unit:
        raise KeyError(f"Unit missing required 'player' field: {unit}")
    if "RNG_RNG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")

    # If no destinations, return current position
    if not valid_destinations:
        return require_unit_position(unit, game_state)

    # Get enemy units
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemy_units = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]

    # If no enemies, just pick first destination
    if not enemy_units:
        return valid_destinations[0]

    # STRATEGY 0: AGGRESSIVE - Move closest to nearest enemy
    if strategy_id == 0:
        best_dest = valid_destinations[0]
        min_dist_to_enemy = float('inf')

        for dest in valid_destinations:
            # Find distance to nearest enemy from this destination
            for enemy_id in enemy_units:
                enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_enemy:
                    min_dist_to_enemy = dist
                    best_dest = dest

        return best_dest

    # STRATEGY 1: TACTICAL - Move to position with most enemies in shooting range
    elif strategy_id == 1:
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range
        weapon_range = get_max_ranged_range(unit)
        best_dest = valid_destinations[0]
        max_targets = 0

        for dest in valid_destinations:
            targets_in_range = 0
            for enemy_id in enemy_units:
                enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist <= weapon_range:
                    # Check LoS (simplified - assumes LoS if in range for now)
                    targets_in_range += 1

            if targets_in_range > max_targets:
                max_targets = targets_in_range
                best_dest = dest

        return best_dest

    # STRATEGY 2: DEFENSIVE - Move farthest from all enemies
    elif strategy_id == 2:
        best_dest = valid_destinations[0]
        max_min_dist = 0

        for dest in valid_destinations:
            # Find distance to nearest enemy (we want to maximize this)
            min_dist_to_any_enemy = float('inf')
            for enemy_id in enemy_units:
                enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_any_enemy:
                    min_dist_to_any_enemy = dist

            if min_dist_to_any_enemy > max_min_dist:
                max_min_dist = min_dist_to_any_enemy
                best_dest = dest

        return best_dest

    # STRATEGY 3: RANDOM - Pick random destination for exploration
    else:
        import random
        return random.choice(valid_destinations)


def charge_preview(valid_destinations: List[Tuple[int, int]]) -> Dict[str, Any]:
    """Generate preview data for violet hexes (charge destinations)"""
    return {
        "violet_hexes": valid_destinations,  # Changed from green_hexes to violet_hexes
        "show_preview": True
    }


def charge_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Clear charge preview"""
    game_state["preview_hexes"] = []
    game_state["valid_charge_destinations_pool"] = []
    # Clear active_charge_unit to allow next unit activation
    game_state["active_charge_unit"] = None
    return {
        "show_preview": False,
        "clear_hexes": True
    }


def charge_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Route charge click actions"""
    # AI_TURN.md COMPLIANCE: Direct field access
    if "clickTarget" not in action:
        click_target = "elsewhere"
    else:
        click_target = action["clickTarget"]

    if click_target == "destination_hex":
        return charge_destination_selection_handler(game_state, unit_id, action)
    elif click_target == "enemy" and "targetId" in action:
        # Click on enemy unit -> target selection (roll 2d6, build destinations)
        return charge_target_selection_handler(game_state, unit_id, action)
    elif click_target == "friendly_unit":
        return False, {"error": "unit_switch_not_implemented", "action": "charge"}
    elif click_target == "active_unit":
        # AI_TURN.md Line 1409: Left click on active_unit -> Charge postponed
        # Clear preview but keep unit in pool (different from skip which removes from pool)
        charge_clear_preview(game_state)
        # Clear charge roll and target selection if exists (postpone discards the roll)
        if "charge_roll_values" in game_state and unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
            del game_state["charge_target_selections"][unit_id]
        return True, {
            "action": "postpone",
            "unitId": unit_id,
            "charge_postponed": True
        }
    else:
        return True, {"action": "continue_selection"}

def charge_target_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle charge target selection: roll 2d6, build pool, display preview.
    
    Flow:
    1. Agent chooses a target
    2. Roll 2d6
    3. Build pool of destinations for this target with the roll
    4. Display preview (violet hexes) for PvP/PvE modes
    5. Return waiting_for_player for destination selection
    """
    if "targetId" not in action:
        raise KeyError(f"Action missing required 'targetId' field: {action}")
    
    target_id = action["targetId"]
    if target_id is None:
        return False, {"error": "missing_target", "action": "charge"}

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Roll 2d6 AFTER target selection
    import random
    charge_roll = random.randint(1, 6) + random.randint(1, 6)
    game_state["charge_roll_values"][unit_id] = charge_roll
    # Store target_id for destination selection
    if "charge_target_selections" not in game_state:
        game_state["charge_target_selections"] = {}
    game_state["charge_target_selections"][unit_id] = target_id
    
    # Clear pending targets after selection
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    # Build pool with actual roll for THIS SPECIFIC TARGET
    charge_build_valid_destinations_pool(game_state, unit_id, charge_roll, target_id=target_id)
    
    if "valid_charge_destinations_pool" not in game_state:
        raise KeyError("game_state missing required 'valid_charge_destinations_pool' field")
    valid_pool = game_state["valid_charge_destinations_pool"]

    # Check if pool is empty (roll too low)
    if not valid_pool:
        # Charge roll too low - charge failed
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        if "current_turn" not in game_state:
            current_turn = 1
        else:
            current_turn = game_state["current_turn"]
        
        game_state["action_logs"].append({
            "type": "charge_fail",
            "message": f"Unit {unit['id']} ({unit['col']}, {unit['row']}) FAILED charge to target {target_id} (Roll: {charge_roll} too low)",
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "player": unit["player"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "timestamp": "server_time"
        })
        
        # Clear charge roll after use
        if unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
            del game_state["charge_target_selections"][unit_id]
        
        # Clear preview
        charge_clear_preview(game_state)
        
        # End activation with failure
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (charge failed)
            1,             # Arg2: +1 step increment (action was attempted)
            PASS,          # Arg3: NO tracking (charge didn't happen)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
        
        # CRITICAL: Add start_pos and end_pos for proper logging (unit didn't move, so both are current position)
        # For failed charges with roll too low, there's no destination, so end_pos equals start_pos
        current_pos = require_unit_position(unit, game_state)
        action_logs = game_state["action_logs"] if "action_logs" in game_state else []
        result.update({
            "action": "charge_fail",
            "unitId": unit["id"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "charge_failed_reason": "roll_too_low",
            "start_pos": current_pos,  # Position actuelle (from) - unit didn't move
            "end_pos": current_pos,  # No destination (roll too low), so equals start_pos
            "activation_complete": True,
            "action_logs": action_logs
        })
        
        # Check if pool is now empty after removing this unit
        if not game_state["charge_activation_pool"]:
            phase_end_result = charge_phase_end(game_state)
            result.update(phase_end_result)
        
        return True, result

    # Pool is valid - display preview (violet hexes) for PvP/PvE modes
    # Check if PvP or PvE mode
    is_pve = game_state.get("pve_mode", False) or game_state.get("is_pve_mode", False)
    is_gym = game_state.get("gym_training_mode", False)
    
    if not is_gym:  # PvP or PvE mode
        # Generate preview with violet hexes (charge destinations)
        preview_data = charge_preview(valid_pool)
        game_state["preview_hexes"] = valid_pool
        
        # Human players: return waiting_for_player for destination selection
        return True, {
            "action": "charge_target_selected",
            "unitId": unit_id,
            "targetId": target_id,
            "charge_roll": charge_roll,
            "valid_destinations": valid_pool,
            "preview_data": preview_data,
            "clear_blinking_gentle": True,  # Stop blinking when target is selected
            "waiting_for_player": True  # Wait for destination selection
        }
    else:
        # AI_TURN.md COMPLIANCE: In gym training, AI selects destination automatically and executes charge
        # AI_TURN.md lines 1393-1396: Select destination hex → Move unit → end_activation
        # No preview needed, auto-select first valid destination
        preview_data = {}
        game_state["preview_hexes"] = []
        
        # Select first valid destination (AI chooses best destination automatically)
        if valid_pool:
            dest_col, dest_row = valid_pool[0]
            # Execute charge directly with selected destination
            destination_action = {
                "action": "charge",
                "unitId": unit_id,
                "targetId": target_id,
                "destCol": dest_col,
                "destRow": dest_row
            }
            return charge_destination_selection_handler(game_state, unit_id, destination_action)
        else:
            # No valid destinations (should not happen after pool check, but defensive)
            return False, {"error": "no_valid_destinations_after_target_selection", "action": "charge"}


def charge_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle charge destination selection and execute charge.
    
    This is called AFTER target selection and roll (charge_target_selection_handler).
    """
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "destCol" not in action:
        raise KeyError(f"Action missing required 'destCol' field: {action}")
    if "destRow" not in action:
        raise KeyError(f"Action missing required 'destRow' field: {action}")

    dest_col = action["destCol"]
    dest_row = action["destRow"]

    if dest_col is None or dest_row is None:
        return False, {"error": "missing_destination", "action": "charge"}
    
    # CRITICAL FIX: Normalize destination coordinates to int to ensure type consistency
    # This prevents type mismatch bugs (int vs float vs string) in position comparison
    try:
        dest_col, dest_row = normalize_coordinates(dest_col, dest_row)
    except (ValueError, TypeError):
        return False, {"error": "invalid_destination_type", "destCol": dest_col, "destRow": dest_row, "action": "charge"}

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Get target_id and charge_roll from previous step
    if "charge_target_selections" not in game_state or unit_id not in game_state["charge_target_selections"]:
        return False, {"error": "target_not_selected", "unit_id": unit_id, "action": "charge"}
    if "charge_roll_values" not in game_state or unit_id not in game_state["charge_roll_values"]:
        return False, {"error": "charge_roll_missing", "unit_id": unit_id, "action": "charge"}
    
    target_id = game_state["charge_target_selections"][unit_id]
    charge_roll = game_state["charge_roll_values"][unit_id]

    # Verify pool exists and destination is in it
    if "valid_charge_destinations_pool" not in game_state:
        return False, {"error": "destination_pool_not_built", "action": "charge"}
    
    valid_pool = game_state["valid_charge_destinations_pool"]

    # Check if destination is in valid pool (reachable with this roll)
    if (dest_col, dest_row) not in valid_pool:
        # Charge roll too low - charge failed
        # Calculate distance for logging
        unit_col, unit_row = require_unit_position(unit, game_state)
        distance_to_dest = _calculate_hex_distance(unit_col, unit_row, dest_col, dest_row)
        
        # Log failure in action_logs
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        if "current_turn" not in game_state:
            current_turn = 1
        else:
            current_turn = game_state["current_turn"]
        
        game_state["action_logs"].append({
            "type": "charge_fail",
            "message": f"Unit {unit['id']} ({unit['col']}, {unit['row']}) FAILED charge to target {target_id} (Roll: {charge_roll}, needed: {distance_to_dest}+)",
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "player": unit["player"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "timestamp": "server_time"
        })
        
        # Clear charge roll after use
        if unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        
        # Clear preview
        charge_clear_preview(game_state)
        
        # End activation with failure
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (charge failed)
            1,             # Arg2: +1 step increment (action was attempted)
            PASS,          # Arg3: NO tracking (charge didn't happen)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
        
        action_logs_val = game_state["action_logs"] if "action_logs" in game_state else []
        result.update({
            "action": "charge_fail",
            "unitId": unit["id"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "charge_failed_reason": "roll_too_low",
            "start_pos": require_unit_position(unit, game_state),  # Position actuelle (from)
            "end_pos": (dest_col, dest_row),  # Destination prévue (to)
            "activation_complete": True,
            # CRITICAL: Include action_logs in result so they're sent to frontend
            "action_logs": action_logs_val
        })
        
        # Check if pool is now empty after removing this unit
        if not game_state["charge_activation_pool"]:
            phase_end_result = charge_phase_end(game_state)
            result.update(phase_end_result)
        
        return True, result

    # Charge roll is sufficient - execute charge
    # Execute charge using _attempt_charge_to_destination
    config = {}
    charge_success, charge_result = _attempt_charge_to_destination(game_state, unit, dest_col, dest_row, target_id, config)

    if not charge_success:
        # CRITICAL FIX: When charge fails, FORCE action type to charge_fail and add missing fields for proper logging
        # This prevents charge_fail actions from being logged as successful charges
        charge_result["action"] = "charge_fail"
        charge_result.setdefault("unitId", unit["id"])
        charge_result.setdefault("targetId", target_id)  # May be None, but needed for logging
        charge_result.setdefault("charge_failed_reason", charge_result.get("error", "unknown_error"))
        # CRITICAL: Add start_pos and end_pos for proper logging
        if "start_pos" not in charge_result:
            charge_result["start_pos"] = require_unit_position(unit, game_state)  # Position actuelle (from) - unit didn't move
        if "end_pos" not in charge_result:
            charge_result["end_pos"] = (dest_col, dest_row)  # Destination prévue (to) - even though charge failed
        return False, charge_result

    # Extract charge info
    orig_col = charge_result.get("fromCol")
    orig_row = charge_result.get("fromRow")

    # Position already updated by _attempt_charge_to_destination
    # CRITICAL FIX: Normalize types before comparison to prevent false negatives
    unit_col_int, unit_row_int = require_unit_position(unit, game_state)
    if unit_col_int != dest_col or unit_row_int != dest_row:
        return False, {
            "error": "position_update_failed", 
            "action": "charge",
            "expected": (dest_col, dest_row),
            "actual": require_unit_position(unit, game_state),
            "toCol": dest_col,
            "toRow": dest_row,
            "fromCol": orig_col,
            "fromRow": orig_row,
            "unitId": unit["id"]
        }

    # Generate charge log
    if "action_logs" not in game_state:
        game_state["action_logs"] = []

    # Calculate reward (simpler than movement - just charge action)
    action_reward = 0.0
    action_name = "CHARGE"

    # AI_TURN.md COMPLIANCE: Direct field access with validation
    reward_configs = require_key(game_state, "reward_configs")
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    scenario_unit_type = require_key(unit, "unitType")
    reward_config_key = unit_registry.get_model_key(scenario_unit_type)

    unit_reward_config = require_key(reward_configs, reward_config_key)

    # Base charge reward is required in rewards config
    base_actions = require_key(unit_reward_config, "base_actions")
    action_reward = require_key(base_actions, "charge_success")

    # AI_TURN.md COMPLIANCE: Direct field access for current_turn
    if "current_turn" not in game_state:
        current_turn = 1  # Explicit default for turn counter
    else:
        current_turn = game_state["current_turn"]

    game_state["action_logs"].append({
        "type": "charge",
        "message": f"Unit {unit['id']} ({orig_col}, {orig_row}) CHARGED to ({dest_col}, {dest_row}) (Roll: {charge_roll})",
        "turn": current_turn,
        "phase": "charge",
        "unitId": unit["id"],
        "player": unit["player"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "targetId": target_id,
        "charge_roll": charge_roll,
        "timestamp": "server_time",
        "action_name": action_name,
        "reward": round(action_reward, 2),
        "is_ai_action": unit["player"] == 1
    })

    # Clear preview
    charge_clear_preview(game_state)

    # AI_TURN.md EXACT: end_activation(Arg1, Arg2, Arg3, Arg4, Arg5)
    result = end_activation(
        game_state, unit,
        ACTION,        # Arg1: Log action
        1,             # Arg2: +1 step
        CHARGE,        # Arg3: CHARGE tracking
        CHARGE,        # Arg4: Remove from charge_activation_pool
        0              # Arg5: No error logging
    )
    
    # Update result with charge details
    result.update({
        "action": "charge",
        "phase": "charge",  # For metrics tracking
        "unitId": unit["id"],
        "targetId": target_id,
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "charge_roll": charge_roll,
        "charge_succeeded": True,  # For metrics tracking - successful charge
        "activation_complete": True
    })

    # Check if pool is now empty after removing this unit
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)

    return True, result


def _is_adjacent_to_enemy_simple(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Simplified flee detection (distance <= 1, no CC_RNG)

    CRITICAL: Uses proper hex distance, not Chebyshev distance.
    Hexagonal grids require hex distance calculation for accurate adjacency.
    """
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy_id, enemy_entry in units_cache.items():
        if int(enemy_entry["player"]) != unit_player:
            # AI_TURN.md COMPLIANCE: Use proper hex distance calculation
            unit_col, unit_row = require_unit_position(unit, game_state)
            enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
            distance = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
            if distance <= 1:
                return True
    return False


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any], had_valid_destinations: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle skip action during charge phase

    Two cases per AI_TURN.md:
    - Line 515: Valid destinations exist, agent chooses wait -> end_activation (WAIT, 1, PASS, CHARGE)
    - Line 518/536: No valid destinations OR cancel -> end_activation (PASS, 0, PASS, CHARGE)
    """
    # Clear charge roll, target selection, and pending targets if unit skips
    if "charge_roll_values" in game_state and unit["id"] in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit["id"]]
    if "charge_target_selections" in game_state and unit["id"] in game_state["charge_target_selections"]:
        del game_state["charge_target_selections"][unit["id"]]
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    charge_clear_preview(game_state)

    # AI_TURN.md EXACT: Different parameters based on whether valid destinations existed
    if had_valid_destinations:
        # AI_TURN.md Line 515: Agent actively chose to wait (valid destinations available)
        result = end_activation(
            game_state, unit,
            WAIT,          # Arg1: Log wait action
            1,             # Arg2: +1 step increment (action was taken)
            PASS,          # Arg3: NO tracking (wait does not mark as charged)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
    else:
        # AI_TURN.md Line 518/536/542: No valid destinations or cancel
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (no action taken)
            0,             # Arg2: NO step increment (no valid choice was made)
            PASS,          # Arg3: NO tracking (no charge happened)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )

    result.update({
        "action": "wait",
        "unitId": unit["id"],
        "activation_complete": True
    })

    # Check if pool is now empty after removing this unit
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)

    return True, result


def charge_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Clean up and end charge phase"""
    charge_clear_preview(game_state)

    # Clear all charge rolls (phase complete)
    game_state["charge_roll_values"] = {}

    # Track phase completion reason
    if 'last_compliance_data' not in game_state:
        game_state['last_compliance_data'] = {}
    game_state['last_compliance_data']['phase_end_reason'] = 'eligibility'

    add_console_log(game_state, "CHARGE PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    charge_pool = require_key(game_state, "charge_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} charge charge_activation_pool={charge_pool}")

    return {
        "phase_complete": True,
        "next_phase": "fight",
        "units_processed": len([uid for uid in require_key(game_state, "units_cache").keys() if uid in game_state["units_charged"]])
    }


