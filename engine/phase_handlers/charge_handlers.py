#!/usr/bin/env python3
"""
charge_handlers.py - AI_TURN.md Charge Phase Implementation
Pure stateless functions implementing AI_TURN.md charge specification

References: AI_TURN.md Section ⚡ CHARGE PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from .generic_handlers import end_activation


def charge_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_TURN.md: Initialize charge phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "charge"

    # AI_TURN.md: Tracking sets are NOT cleared at charge phase start
    # They persist from movement phase (units_fled, units_moved, units_shot remain)

    # Clear charge preview state
    game_state["valid_charge_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = None
    game_state["charge_roll_values"] = {}  # Store 2d6 rolls per unit

    # Build activation pool
    charge_build_activation_pool(game_state)

    # Console log
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("CHARGE POOL BUILT")

    # Check if phase complete immediately (no eligible units)
    if not game_state["charge_activation_pool"]:
        return charge_phase_end(game_state)

    return {
        "phase_initialized": True,
        "eligible_units": len(game_state["charge_activation_pool"]),
        "phase_complete": False
    }


def charge_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    AI_TURN.md: Build charge activation pool with eligibility checks
    """
    eligible_units = get_eligible_units(game_state)
    game_state["charge_activation_pool"] = eligible_units


def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md charge eligibility decision tree implementation.

    Charge Eligibility Requirements:
    - HP_CUR > 0
    - player === current_player
    - NOT in units_charged
    - NOT adjacent to enemy (distance > CC_RNG to all enemies)
    - NOT in units_fled
    - Has valid charge target (enemy within charge range via pathfinding)

    Returns list of unit IDs eligible for charge activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]

    for unit in game_state["units"]:
        # AI_TURN.md: "unit.HP_CUR > 0?"
        if unit["HP_CUR"] <= 0:
            continue  # Dead unit

        # AI_TURN.md: "unit.player === current_player?"
        if unit["player"] != current_player:
            continue  # Wrong player

        # AI_TURN.md: "unit.id not in units_charged?"
        if unit["id"] in game_state["units_charged"]:
            continue  # Already charged

        # AI_TURN.md: "NOT adjacent to enemy?"
        if _is_adjacent_to_enemy(game_state, unit):
            continue  # Already in melee, cannot charge

        # AI_TURN.md: "NOT in units_fled?"
        if unit["id"] in game_state["units_fled"]:
            continue  # Fled units cannot charge

        # AI_TURN.md: "Has valid charge target?"
        # Must have at least one enemy within charge range (via BFS pathfinding)
        if not _has_valid_charge_target(game_state, unit):
            continue  # No valid charge targets

        # AI_TURN.md: Unit passes all conditions
        eligible_units.append(unit["id"])

    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Charge phase handler action routing with complete autonomy
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

    # Pool empty? → Phase complete
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

    # For gym training, if no unitId specified, use first eligible unit
    if not unit_id:
        if game_state["charge_activation_pool"]:
            unit_id = game_state["charge_activation_pool"][0]
        else:
            return True, charge_phase_end(game_state)

    # Validate unit is eligible (keep for validation, remove only after successful action)
    if unit_id not in game_state["charge_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}

    # Get unit object for processing
    active_unit = _get_unit_by_id(game_state, unit_id)
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id}

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
        # AI_TURN.md: Both gym and human players need activation result
        # Returns charge roll, valid destinations, and preview state
        return _handle_unit_activation(game_state, active_unit, config)

    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)

    elif action_type == "charge":
        # GYM TRAINING: If unit already active and no destCol provided, auto-select destination
        if is_gym_training and "destCol" not in action:
            pending_dests = game_state.get("pending_charge_destinations", [])
            if pending_dests:
                best_dest = pending_dests[0]  # First = closest to target
                # pending_charge_destinations are tuples (col, row)
                action["destCol"], action["destRow"] = best_dest
                # Find adjacent enemy target
                target_id = _find_adjacent_enemy_at_destination(game_state, action["destCol"], action["destRow"], active_unit["player"])
                if not target_id:
                    return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)
                action["targetId"] = target_id
            else:
                # No valid destinations - skip this unit
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)
        return charge_destination_selection_handler(game_state, unit_id, action)

    elif action_type == "skip":
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

            # AI_TURN.md: Invalid action during charge phase
            result = end_activation(
                game_state, active_unit,
                "SKIP",        # Arg1: Skip logging
                1,             # Arg2: +1 step increment
                "PASS",        # Arg3: No tracking
                "CHARGE",      # Arg4: Remove from charge pool
                1              # Arg5: Error logging
            )
            result["invalid_action_penalty"] = True
            result["attempted_action"] = action.get("attempted_action", "unknown")
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}

    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "charge"}


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_TURN.md: Charge unit activation start + execution loop"""
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

    if is_gym_training and isinstance(execution_result, tuple) and execution_result[0]:
        # AI_TURN.md COMPLIANCE: Direct field access
        if "waiting_for_player" not in execution_result[1]:
            waiting_for_player = False
        else:
            waiting_for_player = execution_result[1]["waiting_for_player"]

        if waiting_for_player:
            if "valid_destinations" not in execution_result[1]:
                raise KeyError("Execution result missing required 'valid_destinations' field")
            valid_destinations = execution_result[1]["valid_destinations"]

            if valid_destinations:
                # GYM TRAINING: Auto-select best destination (closest to target)
                # Action space doesn't support destination selection, so handler chooses
                best_dest = valid_destinations[0]  # First destination (closest to target)

                # valid_destinations are tuples (col, row)
                dest_col, dest_row = best_dest

                # Find the adjacent enemy at this destination (target for charge)
                target_id = _find_adjacent_enemy_at_destination(game_state, dest_col, dest_row, unit["player"])
                if not target_id:
                    # No target found - skip
                    return _handle_skip_action(game_state, unit, had_valid_destinations=False)

                # Execute the charge to the selected destination
                charge_action = {
                    "action": "charge",
                    "unitId": unit["id"],
                    "destCol": dest_col,
                    "destRow": dest_row,
                    "targetId": target_id
                }
                return charge_destination_selection_handler(game_state, unit["id"], charge_action)
            else:
                # No valid destinations - auto skip (properly remove from pool)
                # CRITICAL FIX: Call _handle_skip_action to remove from pool and trigger phase transition
                return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # All non-gym players (humans AND PvE AI) get normal waiting_for_player response
    return execution_result


def _ai_select_charge_target_pve(game_state: Dict[str, Any], unit: Dict[str, Any], valid_targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    PvE AI selects charge target using priority logic per AI_TURN.md.

    Priority order:
    1. Enemy closest to death (lowest HP_CUR)
    2. Highest threat (max of CC_STR × CC_NB or RNG_STR × RNG_NB)
    """
    if not valid_targets:
        return None

    # AI_TURN.md COMPLIANCE: Direct field access with validation
    for target in valid_targets:
        if "HP_CUR" not in target:
            raise KeyError(f"Target missing required 'HP_CUR' field: {target}")
        if "CC_STR" not in target:
            raise KeyError(f"Target missing required 'CC_STR' field: {target}")
        if "CC_NB" not in target:
            raise KeyError(f"Target missing required 'CC_NB' field: {target}")
        if "RNG_STR" not in target:
            raise KeyError(f"Target missing required 'RNG_STR' field: {target}")
        if "RNG_NB" not in target:
            raise KeyError(f"Target missing required 'RNG_NB' field: {target}")

    # Calculate priority score for each target
    def priority_score(t):
        # Priority 1: Lowest HP (higher priority = lower HP)
        hp_priority = -t["HP_CUR"]  # Negative so lower HP = higher score

        # Priority 2: Highest threat
        melee_threat = t["CC_STR"] * t["CC_NB"]
        ranged_threat = t["RNG_STR"] * t["RNG_NB"]
        threat = max(melee_threat, ranged_threat)

        return (hp_priority, threat)

    # Select target with highest priority
    best_target = max(valid_targets, key=priority_score)
    return best_target


def charge_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    AI_TURN.md: Charge unit activation initialization with 2d6 roll.

    CRITICAL: Roll 2d6 at activation start and store in charge_roll_values.
    This roll determines the maximum charge distance for this activation.
    """
    import random

    # AI_TURN.md: Roll 2d6 immediately at activation start
    charge_roll = random.randint(1, 6) + random.randint(1, 6)
    game_state["charge_roll_values"][unit_id] = charge_roll

    game_state["valid_charge_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = unit_id


def charge_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Single charge execution.

    Uses 2d6 roll from charge_roll_values to determine charge_range.
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}

    # AI_TURN.md: Get charge roll for this unit (rolled at activation start)
    if unit_id not in game_state["charge_roll_values"]:
        raise KeyError(f"Unit {unit_id} missing charge_roll_values - activation start not called")
    charge_roll = game_state["charge_roll_values"][unit_id]

    # Build valid charge destinations using this roll
    charge_build_valid_destinations_pool(game_state, unit_id, charge_roll)

    # Check if valid destinations exist
    if not game_state["valid_charge_destinations_pool"]:
        # AI_TURN.md Line 518: No valid destinations - pass (no step increment, no tracking)
        return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # Generate preview
    preview_data = charge_preview(game_state["valid_charge_destinations_pool"])
    game_state["preview_hexes"] = game_state["valid_charge_destinations_pool"]

    return True, {
        "unit_activated": True,
        "unitId": unit_id,
        "charge_roll": charge_roll,  # Include roll value in response
        "valid_destinations": game_state["valid_charge_destinations_pool"],
        "preview_data": preview_data,
        "waiting_for_player": True
    }


def _attempt_charge_to_destination(game_state: Dict[str, Any], unit: Dict[str, Any], dest_col: int, dest_row: int, target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md charge execution with destination validation.

    Implements AI_TURN.md charge restrictions:
    - Must end adjacent to target enemy
    - Within charge_range (2d6 roll result)
    - Path must be reachable via BFS pathfinding
    """
    # Validate destination per AI_TURN.md charge rules
    # Get charge roll for this unit
    unit_id = unit["id"]
    if unit_id not in game_state["charge_roll_values"]:
        raise KeyError(f"Unit {unit_id} missing charge_roll_values")
    charge_roll = game_state["charge_roll_values"][unit_id]

    if not _is_valid_charge_destination(game_state, dest_col, dest_row, unit, target_id, charge_roll, config):
        return False, {"error": "invalid_charge_destination", "target": (dest_col, dest_row)}

    # Store original position
    orig_col, orig_row = unit["col"], unit["row"]

    # FINAL SAFETY CHECK: Redundant occupation check
    for check_unit in game_state["units"]:
        if (check_unit["id"] != unit["id"] and
            check_unit["HP_CUR"] > 0 and
            check_unit["col"] == dest_col and
            check_unit["row"] == dest_row):
            return False, {
                "error": "occupation_safety_check_failed",
                "occupant_id": check_unit["id"],
                "destination": (dest_col, dest_row)
            }

    # Execute charge
    unit["col"] = dest_col
    unit["row"] = dest_row

    # AI_TURN.md: Mark as units_charged (NOT units_moved)
    game_state["units_charged"].add(unit["id"])

    # Clear charge roll after use
    del game_state["charge_roll_values"][unit_id]

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
    - Adjacent to target enemy (distance <= CC_RNG from target)
    - Reachable within charge_range (2d6 roll) via BFS pathfinding

    CRITICAL: Unlike movement, charges MUST end adjacent to enemy.
    """
    # Board bounds check
    if (col < 0 or row < 0 or
        col >= game_state["board_cols"] or
        row >= game_state["board_rows"]):
        return False

    # Wall collision check
    if (col, row) in game_state["wall_hexes"]:
        return False

    # Unit occupation check
    for other_unit in game_state["units"]:
        if (other_unit["id"] != unit["id"] and
            other_unit["HP_CUR"] > 0 and
            other_unit["col"] == col and
            other_unit["row"] == row):
            return False

    # AI_TURN.md: MUST be adjacent to target enemy
    target = _get_unit_by_id(game_state, target_id)
    if not target:
        return False

    distance_to_target = _calculate_hex_distance(col, row, target["col"], target["row"])
    if distance_to_target == 0:
        return False  # Cannot stand ON enemy
    if distance_to_target > unit["CC_RNG"]:
        return False  # Not adjacent to target

    # AI_TURN.md: Must be reachable within charge_range via pathfinding
    # This is validated by charge_build_valid_destinations_pool
    # If destination is in valid pool, it's reachable
    return True


def _has_valid_charge_target(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md: Check if unit has at least one valid charge target.

    AI_TURN.md Line 495: "Enemies exist within charge_max_distance hexes?"
    AI_TURN.md Line 562: "Enemy units within charge_max_distance hexes (via pathfinding)"

    CRITICAL: Must use BFS pathfinding distance, not straight-line distance.
    Build reachable hexes within max charge distance and check if any enemy
    is adjacent to those hexes.
    """
    # AI_TURN.md: Maximum possible charge distance is 12 hexes (2d6 max roll)
    CHARGE_MAX_DISTANCE = 12

    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "CC_RNG" not in unit:
        raise KeyError(f"Unit {unit['id']} missing required 'CC_RNG' field")

    try:
        # Build all hexes reachable via BFS within max charge distance
        # Use the existing charge_build_valid_destinations_pool with max roll
        reachable_hexes = charge_build_valid_destinations_pool(game_state, unit["id"], CHARGE_MAX_DISTANCE)
    except Exception as e:
        # If BFS fails, log error and return False (no valid targets)
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        game_state["console_logs"].append(f"ERROR: BFS failed for unit {unit['id']}: {str(e)}")
        return False

    # Check if any enemy is within CC_RNG of any reachable hex
    cc_range = unit["CC_RNG"]

    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            # Check if enemy is within CC_RNG of any reachable hex
            for dest_col, dest_row in reachable_hexes:
                distance_to_enemy = _calculate_hex_distance(dest_col, dest_row, enemy["col"], enemy["row"])
                if 0 < distance_to_enemy <= cc_range:
                    # Found a reachable hex adjacent to this enemy
                    return True

    return False


def _is_adjacent_to_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md adjacency check logic.

    Check if unit is adjacent to enemy (used for charge eligibility).

    CRITICAL: Use proper hexagonal distance, not Chebyshev distance.
    For CC_RNG=1 (typical), this means checking if enemy is in 6 neighbors.
    For CC_RNG>1, use hex distance calculation.
    """
    cc_range = unit["CC_RNG"]
    unit_col, unit_row = unit["col"], unit["row"]

    # Optimization: For CC_RNG=1 (most common), check 6 neighbors directly
    if cc_range == 1:
        hex_neighbors = set(_get_hex_neighbors(unit_col, unit_row))
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                enemy_pos = (enemy["col"], enemy["row"])
                if enemy_pos in hex_neighbors:
                    return True
        return False
    else:
        # For longer ranges, use proper hex distance calculation
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                hex_dist = _calculate_hex_distance(unit_col, unit_row, enemy["col"], enemy["row"])
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

    # Fallback: compute dynamically (original behavior)
    hex_neighbors = set(_get_hex_neighbors(col, row))

    for enemy in game_state["units"]:
        if enemy["player"] != player and enemy["HP_CUR"] > 0:
            enemy_pos = (enemy["col"], enemy["row"])
            # Check if enemy is in our 6 neighbors (true hex adjacency)
            if enemy_pos in hex_neighbors:
                return True
    return False


def _find_adjacent_enemy_at_destination(game_state: Dict[str, Any], col: int, row: int, player: int) -> Optional[str]:
    """
    Find an enemy unit adjacent to the given hex position.

    Used by gym training to auto-select charge target based on destination.
    Returns the ID of the first adjacent enemy, or None if no adjacent enemy.
    """
    hex_neighbors = set(_get_hex_neighbors(col, row))

    for enemy in game_state["units"]:
        if enemy["player"] != player and enemy["HP_CUR"] > 0:
            enemy_pos = (enemy["col"], enemy["row"])
            if enemy_pos in hex_neighbors:
                return enemy["id"]
    return None


def _build_enemy_adjacent_hexes(game_state: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    """
    PERFORMANCE: Pre-compute all hexes adjacent to enemy units.

    Returns a set of (col, row) tuples that are adjacent to at least one enemy.
    This allows O(1) adjacency checks instead of O(n) iteration per hex.

    Args:
        game_state: Game state with units
        player: The player checking adjacency (enemies are units with different player)

    Returns:
        Set of hex coordinates adjacent to any living enemy unit
    """
    enemy_adjacent_hexes = set()

    for enemy in game_state["units"]:
        if enemy["player"] != player and enemy["HP_CUR"] > 0:
            # Add all 6 neighbors of this enemy to the set
            neighbors = _get_hex_neighbors(enemy["col"], enemy["row"])
            for neighbor in neighbors:
                enemy_adjacent_hexes.add(neighbor)

    return enemy_adjacent_hexes


def _get_hex_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """
    Get all 6 hexagonal neighbors for offset coordinates.
    
    Hex neighbor offsets depend on whether column is even or odd.
    Even columns: NE/SE are (+1, -1) and (+1, 0)
    Odd columns: NE/SE are (+1, 0) and (+1, +1)
    """
    # Determine if column is even or odd
    parity = col & 1  # 0 for even, 1 for odd
    
    if parity == 0:  # Even column
        neighbors = [
            (col, row - 1),      # N
            (col + 1, row - 1),  # NE
            (col + 1, row),      # SE
            (col, row + 1),      # S
            (col - 1, row),      # SW
            (col - 1, row - 1)   # NW
        ]
    else:  # Odd column
        neighbors = [
            (col, row - 1),      # N
            (col + 1, row),      # NE
            (col + 1, row + 1),  # SE
            (col, row + 1),      # S
            (col - 1, row + 1),  # SW
            (col - 1, row)       # NW
        ]
    
    return neighbors


def _is_traversable_hex(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any],
                        occupied_positions: set = None) -> bool:
    """
    Check if a hex can be traversed (moved through) during pathfinding.

    AI_TURN.md: A hex is traversable if it's:
    - Within board bounds
    - NOT a wall
    - NOT occupied by another unit

    Note: We check enemy adjacency separately in _is_valid_destination

    PERFORMANCE: Pass occupied_positions set for O(1) occupation check during BFS.
    If not provided, falls back to O(n) unit iteration.
    """
    # Board bounds check
    if (col < 0 or row < 0 or
        col >= game_state["board_cols"] or
        row >= game_state["board_rows"]):
        return False

    # Wall check - CRITICAL: Can't move through walls
    if (col, row) in game_state["wall_hexes"]:
        return False

    # Unit occupation check - CRITICAL: Check ALL units including dead ones with HP check
    # PERFORMANCE: Use pre-computed set if available (O(1) vs O(n))
    if occupied_positions is not None:
        if (col, row) in occupied_positions:
            return False
    else:
        # Fallback to O(n) iteration if no cache provided
        for other_unit in game_state["units"]:
            if (other_unit["id"] != unit["id"] and
                other_unit["HP_CUR"] > 0 and
                other_unit["col"] == col and
                other_unit["row"] == row):
                return False

    return True


def charge_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str, charge_roll: int) -> List[Tuple[int, int]]:
    """
    AI_TURN.md: Build valid charge destinations using BFS pathfinding.

    CRITICAL: Charge destinations must:
    - Be reachable within charge_roll distance (2d6) via BFS
    - End adjacent to at least one enemy (within CC_RNG)
    - Not be blocked by walls or units

    Unlike movement, charges CAN move through hexes adjacent to enemies.
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    charge_range = charge_roll  # 2d6 result
    start_col, start_row = unit["col"], unit["row"]
    start_pos = (start_col, start_row)

    # Get all enemy positions for adjacency checks
    enemies = [u for u in game_state["units"]
               if u["player"] != unit["player"] and u["HP_CUR"] > 0]

    if not enemies:
        return []  # No enemies to charge

    # PERFORMANCE: Pre-compute occupied positions
    occupied_positions = {(u["col"], u["row"]) for u in game_state["units"]
                         if u["HP_CUR"] > 0 and u["id"] != unit["id"]}

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
        neighbors = _get_hex_neighbors(current_col, current_row)

        for neighbor_col, neighbor_row in neighbors:
            neighbor_pos = (neighbor_col, neighbor_row)
            neighbor_dist = current_dist + 1

            # Skip if already visited
            if neighbor_pos in visited:
                continue

            # Check if traversable (not wall, not occupied)
            if not _is_traversable_hex(game_state, neighbor_col, neighbor_row, unit, occupied_positions):
                continue

            # Mark as visited
            visited[neighbor_pos] = neighbor_dist

            # AI_TURN.md: Check if this hex is adjacent to any enemy
            is_adjacent_to_enemy = False
            for enemy in enemies:
                distance_to_enemy = _calculate_hex_distance(neighbor_col, neighbor_row, enemy["col"], enemy["row"])
                if 0 < distance_to_enemy <= unit["CC_RNG"]:
                    is_adjacent_to_enemy = True
                    break

            # CRITICAL: Only add as destination if adjacent to an enemy AND NOT OCCUPIED
            # Double-check occupation against actual game state (not just cached set)
            if is_adjacent_to_enemy and neighbor_pos != start_pos:
                # Verify hex is not occupied by checking actual game state
                hex_is_occupied = False
                for check_unit in game_state["units"]:
                    if (check_unit["id"] != unit["id"] and
                        check_unit["HP_CUR"] > 0 and
                        check_unit["col"] == neighbor_col and
                        check_unit["row"] == neighbor_row):
                        hex_is_occupied = True
                        break
                
                # Only add if NOT occupied
                if not hex_is_occupied:
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

    # AI_TURN.md: Direct field access with validation
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
        return (unit["col"], unit["row"])

    # Get enemy units
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    enemy_units = []
    for u in game_state["units"]:
        if u["player"] != unit["player"]:
            if "HP_CUR" not in u:
                raise KeyError(f"Unit missing required 'HP_CUR' field: {u}")
            if u["HP_CUR"] > 0:
                enemy_units.append(u)

    # If no enemies, just pick first destination
    if not enemy_units:
        return valid_destinations[0]

    # STRATEGY 0: AGGRESSIVE - Move closest to nearest enemy
    if strategy_id == 0:
        best_dest = valid_destinations[0]
        min_dist_to_enemy = float('inf')

        for dest in valid_destinations:
            # Find distance to nearest enemy from this destination
            for enemy in enemy_units:
                dist = _calculate_hex_distance(dest[0], dest[1], enemy["col"], enemy["row"])
                if dist < min_dist_to_enemy:
                    min_dist_to_enemy = dist
                    best_dest = dest

        return best_dest

    # STRATEGY 1: TACTICAL - Move to position with most enemies in shooting range
    elif strategy_id == 1:
        weapon_range = unit["RNG_RNG"]
        best_dest = valid_destinations[0]
        max_targets = 0

        for dest in valid_destinations:
            targets_in_range = 0
            for enemy in enemy_units:
                dist = _calculate_hex_distance(dest[0], dest[1], enemy["col"], enemy["row"])
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
            for enemy in enemy_units:
                dist = _calculate_hex_distance(dest[0], dest[1], enemy["col"], enemy["row"])
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
    """AI_TURN.md: Generate preview data for green hexes (charge destinations)"""
    return {
        "green_hexes": valid_destinations,
        "show_preview": True
    }


def charge_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_TURN.md: Clear charge preview"""
    game_state["preview_hexes"] = []
    game_state["valid_charge_destinations_pool"] = []
    # AI_TURN.md: Clear active_charge_unit to allow next unit activation
    game_state["active_charge_unit"] = None
    return {
        "show_preview": False,
        "clear_hexes": True
    }


def charge_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_TURN.md: Route charge click actions"""
    # AI_TURN.md COMPLIANCE: Direct field access
    if "clickTarget" not in action:
        click_target = "elsewhere"
    else:
        click_target = action["clickTarget"]

    if click_target == "destination_hex":
        return charge_destination_selection_handler(game_state, unit_id, action)
    elif click_target == "friendly_unit":
        return False, {"error": "unit_switch_not_implemented"}
    elif click_target == "active_unit":
        return True, {"action": "no_effect"}
    else:
        return True, {"action": "continue_selection"}

def charge_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_TURN.md: Handle charge destination selection and execute charge"""
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "destCol" not in action:
        raise KeyError(f"Action missing required 'destCol' field: {action}")
    if "destRow" not in action:
        raise KeyError(f"Action missing required 'destRow' field: {action}")
    if "targetId" not in action:
        raise KeyError(f"Action missing required 'targetId' field for charge: {action}")

    dest_col = action["destCol"]
    dest_row = action["destRow"]
    target_id = action["targetId"]

    if dest_col is None or dest_row is None or target_id is None:
        return False, {"error": "missing_destination_or_target"}

    # Get charge roll for validation
    if unit_id not in game_state["charge_roll_values"]:
        raise KeyError(f"Unit {unit_id} missing charge_roll_values")
    charge_roll = game_state["charge_roll_values"][unit_id]

    # Rebuild pool fresh to ensure synchronization
    charge_build_valid_destinations_pool(game_state, unit_id, charge_roll)

    if "valid_charge_destinations_pool" not in game_state:
        raise KeyError("game_state missing required 'valid_charge_destinations_pool' field")
    valid_pool = game_state["valid_charge_destinations_pool"]

    # Validate destination in valid pool
    if (dest_col, dest_row) not in valid_pool:
        return False, {"error": "invalid_charge_destination", "destination": (dest_col, dest_row)}

    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}

    # Execute charge using _attempt_charge_to_destination
    config = {}
    charge_success, charge_result = _attempt_charge_to_destination(game_state, unit, dest_col, dest_row, target_id, config)

    if not charge_success:
        return False, charge_result

    # Extract charge info
    orig_col = charge_result.get("fromCol")
    orig_row = charge_result.get("fromRow")

    # Position already updated by _attempt_charge_to_destination
    if unit["col"] != dest_col or unit["row"] != dest_row:
        return False, {"error": "position_update_failed"}

    # Generate charge log
    if "action_logs" not in game_state:
        game_state["action_logs"] = []

    # Calculate reward (simpler than movement - just charge action)
    action_reward = 0.0
    action_name = "CHARGE"

    try:
        from ai.reward_mapper import RewardMapper

        # AI_TURN.md COMPLIANCE: Direct field access with validation
        if "reward_configs" not in game_state:
            reward_configs = {}
        else:
            reward_configs = game_state["reward_configs"]

        if reward_configs:
            from ai.unit_registry import UnitRegistry
            unit_registry = UnitRegistry()
            scenario_unit_type = unit["unitType"]
            reward_config_key = unit_registry.get_model_key(scenario_unit_type)

            # Check if config exists
            if reward_config_key not in reward_configs:
                unit_reward_config = None
            else:
                unit_reward_config = reward_configs[reward_config_key]

            if not unit_reward_config:
                raise ValueError(f"No reward config found for unit type '{reward_config_key}' in reward_configs")

            reward_mapper = RewardMapper(unit_reward_config)

            # Get base charge reward (if configured)
            unit_rewards = reward_mapper._get_unit_rewards(unit)

            # AI_TURN.md COMPLIANCE: Direct field access
            if "base_actions" not in unit_rewards:
                base_actions = {}
            else:
                base_actions = unit_rewards["base_actions"]

            if "charge" in base_actions:
                action_reward = base_actions["charge"]
    except Exception:
        pass  # Silent fallback

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
        "ACTION",      # Arg1: Log action
        1,             # Arg2: +1 step
        "CHARGE",      # Arg3: CHARGE tracking
        "CHARGE",      # Arg4: Remove from charge_activation_pool
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

    # AI_TURN.md: Check if pool is now empty after removing this unit
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)

    return True, result


def _is_adjacent_to_enemy_simple(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md: Simplified flee detection (distance <= 1, no CC_RNG)

    CRITICAL: Uses proper hex distance, not Chebyshev distance.
    Hexagonal grids require hex distance calculation for accurate adjacency.
    """
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            # AI_TURN.md COMPLIANCE: Use proper hex distance calculation
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= 1:
                return True
    return False


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any], had_valid_destinations: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Handle skip action during charge phase

    Two cases per AI_TURN.md:
    - Line 515: Valid destinations exist, agent chooses wait → end_activation (WAIT, 1, PASS, CHARGE)
    - Line 518/536: No valid destinations OR cancel → end_activation (PASS, 0, PASS, CHARGE)
    """
    # Clear charge roll if unit skips
    if unit["id"] in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit["id"]]

    charge_clear_preview(game_state)

    # AI_TURN.md EXACT: Different parameters based on whether valid destinations existed
    if had_valid_destinations:
        # AI_TURN.md Line 515: Agent actively chose to wait (valid destinations available)
        result = end_activation(
            game_state, unit,
            "WAIT",        # Arg1: Log wait action
            1,             # Arg2: +1 step increment (action was taken)
            "PASS",        # Arg3: NO tracking (wait does not mark as charged)
            "CHARGE",      # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
    else:
        # AI_TURN.md Line 518/536/542: No valid destinations or cancel
        result = end_activation(
            game_state, unit,
            "PASS",        # Arg1: Pass logging (no action taken)
            0,             # Arg2: NO step increment (no valid choice was made)
            "PASS",        # Arg3: NO tracking (no charge happened)
            "CHARGE",      # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )

    result.update({
        "action": "wait",
        "unitId": unit["id"],
        "activation_complete": True
    })

    # AI_TURN.md: Check if pool is now empty after removing this unit
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)

    return True, result


def charge_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_TURN.md: Clean up and end charge phase"""
    charge_clear_preview(game_state)

    # Clear all charge rolls (phase complete)
    game_state["charge_roll_values"] = {}

    # Track phase completion reason
    if 'last_compliance_data' not in game_state:
        game_state['last_compliance_data'] = {}
    game_state['last_compliance_data']['phase_end_reason'] = 'eligibility'

    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("CHARGE PHASE COMPLETE")

    return {
        "phase_complete": True,
        "next_phase": "fight",
        "units_processed": len([u for u in game_state["units"] if u["id"] in game_state["units_charged"]])
    }


def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state.

    CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
    """
    for unit in game_state["units"]:
        if str(unit["id"]) == str(unit_id):
            return unit
    return None