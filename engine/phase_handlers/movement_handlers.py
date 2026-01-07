#!/usr/bin/env python3
"""
movement_handlers.py - AI_TURN.md Movement Phase Implementation
Pure stateless functions implementing AI_TURN.md movement specification

References: AI_TURN.md Section 🏃 MOVEMENT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from .generic_handlers import end_activation
from engine.combat_utils import calculate_hex_distance


def _log_movement_debug(game_state: Dict[str, Any], function_name: str, unit_id: str, message: str) -> None:
    """Helper function to log movement debug information with episode/turn/phase context."""
    # Only log if episode_number exists (training mode), otherwise skip silently
    if "episode_number" not in game_state or "turn" not in game_state or "phase" not in game_state:
        return  # Skip logging if not in training context
    
    episode = game_state["episode_number"]
    turn = game_state["turn"]
    phase = game_state["phase"]
    
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    
    log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} {function_name} Unit {unit_id}: {message}"
    game_state["console_logs"].append(log_message)
    print(log_message)  # Also print to console for immediate visibility


def movement_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_MOVE.md: Initialize movement phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "move"
    
    # Build activation pool
    movement_build_activation_pool(game_state)
    
    # Console log
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("MOVEMENT POOL BUILT")
    
    # Check if phase complete immediately (no eligible units)
    if not game_state["move_activation_pool"]:
        return movement_phase_end(game_state)
    
    return {
        "phase_initialized": True,
        "eligible_units": len(game_state["move_activation_pool"]),
        "phase_complete": False
    }


def movement_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    AI_MOVE.md: Build activation pool with eligibility checks
    """
    current_player = game_state.get("current_player", "N/A")
    eligible_units = get_eligible_units(game_state)
    game_state["move_activation_pool"] = eligible_units
    
    # Log pool build result
    if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        phase = game_state.get("phase", "move")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} movement_build_activation_pool: pool_size={len(eligible_units)} units={eligible_units}"
        game_state["console_logs"].append(log_message)
        print(log_message)  # Also print to console for immediate visibility


def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md movement eligibility decision tree implementation.

    Returns list of unit IDs eligible for movement activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]

    for unit in game_state["units"]:
        unit_id = unit["id"]
        
        # "unit.HP_CUR > 0?"
        if unit["HP_CUR"] <= 0:
            continue  # Dead unit (Skip, no log)

        # "unit.player === current_player?"
        if unit["player"] != current_player:
            continue  # Wrong player (Skip, no log)

        # "unit.id not in units_moved?"
        if unit["id"] in game_state["units_moved"]:
            continue  # Already moved (Skip, no log)

        # Unit passes all conditions
        eligible_units.append(unit["id"])

    # Log eligible units result
    if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        phase = game_state.get("phase", "move")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} get_eligible_units: eligible={eligible_units} count={len(eligible_units)}"
        game_state["console_logs"].append(log_message)
        print(log_message)  # Also print to console for immediate visibility

    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_MOVE.md: Handler action routing with complete autonomy
    """
    
    # Handler self-initialization on first action
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "phase" not in game_state:
        game_state_phase = None
    else:
        game_state_phase = game_state["phase"]
    
    if "move_activation_pool" not in game_state:
        move_pool_exists = False
    else:
        move_pool_exists = bool(game_state["move_activation_pool"])
    
    if game_state_phase != "move" or not move_pool_exists:
        movement_phase_start(game_state)
    
    # Pool empty? -> Phase complete
    if not game_state["move_activation_pool"]:
        return True, movement_phase_end(game_state)
    
    # Get unit from action (frontend specifies which unit to move)
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
        if game_state["move_activation_pool"]:
            unit_id = game_state["move_activation_pool"][0]
        else:
            return True, movement_phase_end(game_state)
    
    # Validate unit is eligible (keep for validation, remove only after successful action)
    if unit_id not in game_state["move_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # Get unit object for processing
    active_unit = _get_unit_by_id(game_state, unit_id)
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id}
    
    # Log action routing
    _log_movement_debug(game_state, "execute_action", str(unit_id), f"action={action_type}")
    
    # Flag detection for consistent behavior
    # AI_TURN.md COMPLIANCE: Check both config and game_state for gym_training_mode
    is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)
    
    # Auto-activate unit if not already activated and preview not shown
    if not game_state.get("active_movement_unit") and action_type in ["move", "left_click"]:
        if is_gym_training:
            # Gym training: return immediately to trigger auto-movement
            return _handle_unit_activation(game_state, active_unit, config)
        else:
            # Human players: activate but don't return, continue to normal flow
            _handle_unit_activation(game_state, active_unit, config)
    
    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)
    
    elif action_type == "move":
        return movement_destination_selection_handler(game_state, unit_id, action)
    
    elif action_type == "skip":
        return _handle_skip_action(game_state, active_unit)
    
    elif action_type == "left_click":
        return movement_click_handler(game_state, unit_id, action)
    
    elif action_type == "right_click":
        return _handle_skip_action(game_state, active_unit)
    
    elif action_type == "invalid":
        # Handle invalid actions with training penalty - same as shooting handler
        if unit_id in game_state["move_activation_pool"]:
            # Clear preview first
            movement_clear_preview(game_state)
            
            # Use same end_activation parameters as shooting handler
            result = end_activation(
                game_state, active_unit,
                "SKIP",        # Arg1: Same as shooting (SKIP, not WAIT)
                1,             # Arg2: Same step increment  
                "PASS",        # Arg3: Same as shooting (no tracking)
                "MOVE",        # Arg4: Remove from move pool
                1              # Arg5: Same error logging as shooting
            )
            result["invalid_action_penalty"] = True
            result["attempted_action"] = action.get("attempted_action", "unknown")
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "move"}


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Unit activation start + execution loop"""
    # Unit activation start
    movement_unit_activation_start(game_state, unit["id"])

    # Unit execution loop (automatic)
    execution_result = movement_unit_execution_loop(game_state, unit["id"])

    # Clean flag detection
    # AI_TURN.md COMPLIANCE: Check both config and game_state for gym_training_mode
    is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)

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
                # ✅ FIX: Store destinations in game_state for agent's action to reference
                # Agent will choose destination via action 0-3, converted by ActionDecoder
                game_state["pending_movement_destinations"] = valid_destinations
                game_state["pending_movement_unit_id"] = unit["id"]

                # Return waiting_for_player=True - agent must now choose destination
                return True, {
                    "waiting_for_player": True,
                    "unitId": unit["id"],
                    "valid_destinations": valid_destinations,
                    "action": "waiting_for_movement_choice"
                }
            else:
                # No valid destinations - auto skip
                return True, {"action": "skip", "unitId": unit["id"], "reason": "no_valid_destinations"}

    # All non-gym players (humans AND PvE AI) get normal waiting_for_player response
    return execution_result


def _ai_select_movement_destination_pve(game_state: Dict[str, Any], unit: Dict[str, Any], valid_destinations: List[Tuple[int, int]]) -> Tuple[int, int]:
    """PvE AI selects movement destination using strategic logic."""
    current_pos = (unit["col"], unit["row"])
    
    # Filter out current position to force actual movement
    actual_moves = [dest for dest in valid_destinations if dest != current_pos]
    
    if not actual_moves:
        # No valid moves available - return current position (will trigger skip)
        return current_pos
    
    # Strategy: Move toward nearest enemy for aggressive positioning
    enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]

    if enemies:
        # Find nearest enemy using hex distance
        nearest_enemy = min(enemies, key=lambda e: calculate_hex_distance(unit["col"], unit["row"], e["col"], e["row"]))
        enemy_pos = (nearest_enemy["col"], nearest_enemy["row"])
        nearest_dist = calculate_hex_distance(unit["col"], unit["row"], nearest_enemy["col"], nearest_enemy["row"])

        # Select move that gets closest to nearest enemy using hex distance
        best_move = min(actual_moves,
                       key=lambda dest: calculate_hex_distance(dest[0], dest[1], enemy_pos[0], enemy_pos[1]))

        return best_move
    else:
        # No enemies - just take first available move
        return actual_moves[0]


def movement_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> None:
    """AI_MOVE.md: Unit activation initialization"""
    game_state["valid_move_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_movement_unit"] = unit_id


def movement_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Single movement execution (no loop like shooting)"""
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}
    
    # Build valid destinations
    movement_build_valid_destinations_pool(game_state, unit_id)
    
    # Check if valid destinations exist
    if not game_state["valid_move_destinations_pool"]:
        # No valid moves - auto skip
        return _handle_skip_action(game_state, unit)
    
    # Generate preview
    preview_data = movement_preview(game_state["valid_move_destinations_pool"])
    game_state["preview_hexes"] = game_state["valid_move_destinations_pool"]
    
    return True, {
        "unit_activated": True,
        "unitId": unit_id,  # ADDED: Required for reward calculation
        "valid_destinations": game_state["valid_move_destinations_pool"],
        "preview_data": preview_data,
        "waiting_for_player": True
    }


def _attempt_movement_to_destination(game_state: Dict[str, Any], unit: Dict[str, Any], dest_col: int, dest_row: int, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md movement execution with destination validation.

    Implements AI_TURN.md movement restrictions and flee detection.
    """
    # Pre-compute enemy adjacent hexes for validation (required for _is_valid_destination)
    enemy_adjacent_hexes = _build_enemy_adjacent_hexes(game_state, unit["player"])
    
    # Log specific destination check for debugging
    if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        dest_tuple = (int(dest_col), int(dest_row))
        is_in_set = dest_tuple in enemy_adjacent_hexes
        # Check if destination is adjacent to any enemy by checking all enemies
        adjacent_enemies = []
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                enemy_col, enemy_row = int(enemy["col"]), int(enemy["row"])
                neighbors = _get_hex_neighbors(enemy_col, enemy_row)
                if dest_tuple in neighbors:
                    adjacent_enemies.append(f"Unit {enemy['id']} at ({enemy_col},{enemy_row})")
        
        if adjacent_enemies:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            phase = game_state.get("phase", "move")
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_message = f"[MOVE DEBUG] ⚠️ E{episode} T{turn} {phase} attempt_movement: dest ({dest_col},{dest_row}) NOT in enemy_adjacent_hexes={is_in_set} but IS adjacent to: {adjacent_enemies}"
            game_state["console_logs"].append(log_message)
            print(log_message)
    
    # Validate destination per AI_TURN.md rules
    if not _is_valid_destination(game_state, dest_col, dest_row, unit, config, enemy_adjacent_hexes):
        _log_movement_debug(game_state, "attempt_movement", str(unit["id"]), f"({unit['col']},{unit['row']})→({dest_col},{dest_row}) FAILED: invalid_destination")
        return False, {"error": "invalid_destination", "target": (dest_col, dest_row)}
    
    # AI_TURN.md flee detection: was adjacent to enemy before move
    was_adjacent = _is_adjacent_to_enemy(game_state, unit)
    
    # Store original position
    orig_col, orig_row = unit["col"], unit["row"]

    # FINAL SAFETY CHECK: Redundant occupation check right before position update
    # This catches occupation bugs that somehow bypass the validation above
    # CRITICAL: Convert coordinates to int for consistent comparison
    dest_col_int, dest_row_int = int(dest_col), int(dest_row)
    for check_unit in game_state["units"]:
        if (check_unit["id"] != unit["id"] and
            check_unit["HP_CUR"] > 0 and
            int(check_unit["col"]) == dest_col_int and
            int(check_unit["row"]) == dest_row_int):
            # Occupation detected - this should NEVER happen if validation worked correctly
            _log_movement_debug(game_state, "attempt_movement", str(unit["id"]), f"({orig_col},{orig_row})→({dest_col},{dest_row}) FAILED: occupation_safety_check_failed occupant={check_unit['id']}")
            return False, {
                "error": "occupation_safety_check_failed",
                "occupant_id": check_unit["id"],
                "destination": (dest_col, dest_row)
            }

    # Execute movement
    # CRITICAL: Log ALL position changes to detect unauthorized modifications
    # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "move")
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col},{dest_row}) via MOVE"
    game_state["console_logs"].append(log_message)
    print(log_message)
    
    # CRITICAL: Log BEFORE each assignment to catch any modification
    print(f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col} row={dest_row}")
    unit["col"] = dest_col
    print(f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: col set to {unit['col']}")
    unit["row"] = dest_row
    print(f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")
    
    # Apply AI_TURN.md tracking
    game_state["units_moved"].add(unit["id"])
    if was_adjacent:
        game_state["units_fled"].add(unit["id"])
    
    # Log successful movement
    action_type = "FLEE" if was_adjacent else "MOVE"
    _log_movement_debug(game_state, "attempt_movement", str(unit["id"]), f"({orig_col},{orig_row})→({dest_col},{dest_row}) SUCCESS {action_type}")
    
    return True, {
        "action": "flee" if was_adjacent else "move",
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row
    }


def _is_valid_destination(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any], config: Dict[str, Any],
                          enemy_adjacent_hexes: Set[Tuple[int, int]]) -> bool:
    """
    AI_TURN.md destination validation implementation.

    Validates movement destination per AI_TURN.md restrictions.

    PERFORMANCE: Uses pre-computed enemy_adjacent_hexes set for O(1) lookup.
    enemy_adjacent_hexes must be provided (use _build_enemy_adjacent_hexes()).
    """
    # CRITICAL: Convert coordinates to int for consistent comparison
    col_int, row_int = int(col), int(row)
    
    # Board bounds check (use converted coordinates)
    if (col_int < 0 or row_int < 0 or
        col_int >= game_state["board_cols"] or
        row_int >= game_state["board_rows"]):
        return False

    # Wall collision check (use converted coordinates)
    if (col_int, row_int) in game_state["wall_hexes"]:
        return False

    # Unit occupation check
    for other_unit in game_state["units"]:
        if (other_unit["id"] != unit["id"] and
            other_unit["HP_CUR"] > 0 and
            int(other_unit["col"]) == col_int and
            int(other_unit["row"]) == row_int):
            return False

    # Cannot move TO hexes adjacent to enemies
    # CRITICAL: Direct check in enemy_adjacent_hexes set for consistent comparison
    if (col_int, row_int) in enemy_adjacent_hexes:
        # Log why destination is invalid (only in training context)
        if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            phase = game_state.get("phase", "move")
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            # Also check which enemies make this hex adjacent
            adjacent_enemies = []
            for enemy in game_state["units"]:
                if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                    enemy_col, enemy_row = int(enemy["col"]), int(enemy["row"])
                    neighbors = _get_hex_neighbors(enemy_col, enemy_row)
                    if (col_int, row_int) in neighbors:
                        adjacent_enemies.append(f"Unit {enemy['id']} at ({enemy_col},{enemy_row})")
            log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} is_valid_destination: hex ({col_int},{row_int}) INVALID - adjacent to enemy (in enemy_adjacent_hexes) enemies={adjacent_enemies}"
            game_state["console_logs"].append(log_message)
            print(log_message)
        return False

    return True


def _is_adjacent_to_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md flee detection logic.

    Check if unit is adjacent to enemy for flee marking.

    CRITICAL FIX: Use proper hexagonal distance, not Chebyshev distance.
    For CC_RNG=1 (typical), this means checking if enemy is in 6 neighbors.
    For CC_RNG>1, use hex distance calculation.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1.
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    # CRITICAL: Convert coordinates to int for consistent tuple comparison
    unit_col, unit_row = int(unit["col"]), int(unit["row"])

    # Optimization: For CC_RNG=1 (most common), check 6 neighbors directly
    result = False
    if cc_range == 1:
        hex_neighbors = set(_get_hex_neighbors(unit_col, unit_row))
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                # CRITICAL: Convert coordinates to int for consistent tuple comparison
                enemy_pos = (int(enemy["col"]), int(enemy["row"]))
                if enemy_pos in hex_neighbors:
                    result = True
                    break
    else:
        # For longer ranges, use proper hex distance calculation
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                hex_dist = _calculate_hex_distance(unit_col, unit_row, int(enemy["col"]), int(enemy["row"]))
                if hex_dist <= cc_range:
                    result = True
                    break
    
    # Log adjacency check result
    _log_movement_debug(game_state, "is_adjacent_to_enemy", str(unit["id"]), f"ADJACENT" if result else "NOT_ADJACENT")
    
    return result


def _is_hex_adjacent_to_enemy(game_state: Dict[str, Any], col: int, row: int, player: int,
                               enemy_adjacent_hexes: Set[Tuple[int, int]] = None) -> bool:
    """
    AI_TURN.md adjacency restriction implementation.

    Check if hex position is adjacent to any enemy unit.

    CRITICAL FIX: Use proper hexagonal adjacency, not Chebyshev distance.
    Hexagonal grids require checking if enemy position is in the list of 6 neighbors.

    PERFORMANCE: If enemy_adjacent_hexes set is provided, uses O(1) set lookup
    instead of O(n) iteration through all units.
    
    CRITICAL: enemy_adjacent_hexes must always be provided (no fallback).
    """
    if enemy_adjacent_hexes is None:
        raise ValueError("enemy_adjacent_hexes must be provided - use _build_enemy_adjacent_hexes() first")
    
    # CRITICAL: Convert coordinates to int for consistent tuple comparison
    col_int, row_int = int(col), int(row)
    return (col_int, row_int) in enemy_adjacent_hexes


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
    enemies_processed = []  # Track enemies for debugging
    all_units_info = []  # Track all units for debugging

    for enemy in game_state["units"]:
        # Log all units for debugging
        unit_info = f"Unit {enemy['id']} player={enemy['player']} HP={enemy.get('HP_CUR', 0)} at ({int(enemy['col'])},{int(enemy['row'])})"
        all_units_info.append(unit_info)
        
        if enemy["player"] != player and enemy["HP_CUR"] > 0:
            # CRITICAL: Convert coordinates to int before calculating neighbors
            enemy_col, enemy_row = int(enemy["col"]), int(enemy["row"])
            enemies_processed.append(f"Unit {enemy['id']} at ({enemy_col},{enemy_row})")
            # Log neighbors for specific enemies to debug adjacency issues
            if enemy["id"] == "6" or enemy["id"] == "5":
                neighbors = _get_hex_neighbors(enemy_col, enemy_row)
                if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
                    episode = game_state["episode_number"]
                    turn = game_state["turn"]
                    phase = game_state.get("phase", "move")
                    if "console_logs" not in game_state:
                        game_state["console_logs"] = []
                    log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} build_enemy_adjacent_hexes: Unit {enemy['id']} at ({enemy_col},{enemy_row}) neighbors={neighbors}"
                    game_state["console_logs"].append(log_message)
                    print(log_message)
            # Add all 6 neighbors of this enemy to the set
            neighbors = _get_hex_neighbors(enemy_col, enemy_row)
            for neighbor in neighbors:
                # CRITICAL: Ensure neighbor coordinates are int tuples for consistent comparison
                neighbor_col, neighbor_row = neighbor
                hex_tuple = (int(neighbor_col), int(neighbor_row))
                enemy_adjacent_hexes.add(hex_tuple)

    # Log enemy adjacent hexes result (only if episode_number exists to avoid errors in non-episode contexts)
    if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        phase = game_state.get("phase", "move")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        # Convert set to sorted list for readable output
        sorted_hexes = sorted(enemy_adjacent_hexes)
        log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} build_enemy_adjacent_hexes: enemy_adjacent_hexes count={len(enemy_adjacent_hexes)} enemies={enemies_processed} all_units={all_units_info}"
        game_state["console_logs"].append(log_message)
        print(log_message)  # Also print to console for immediate visibility
        # Log the full set content for debugging
        log_message_hexes = f"[MOVE DEBUG] E{episode} T{turn} {phase} build_enemy_adjacent_hexes: full_set={sorted_hexes}"
        game_state["console_logs"].append(log_message_hexes)
        print(log_message_hexes)

    return enemy_adjacent_hexes


def _get_hex_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """
    Get all 6 hexagonal neighbors for offset coordinates.
    
    Hex neighbor offsets depend on whether column is even or odd.
    Even columns: NE/SE are (+1, -1) and (+1, 0)
    Odd columns: NE/SE are (+1, 0) and (+1, +1)
    
    CRITICAL: Explicitly ensures all returned tuples are (int, int) for type consistency.
    """
    # CRITICAL: Convert to int to guarantee type consistency (handles edge cases)
    col_int, row_int = int(col), int(row)
    
    # Determine if column is even or odd
    parity = col_int & 1  # 0 for even, 1 for odd
    
    if parity == 0:  # Even column
        neighbors = [
            (int(col_int), int(row_int - 1)),      # N
            (int(col_int + 1), int(row_int - 1)),  # NE
            (int(col_int + 1), int(row_int)),      # SE
            (int(col_int), int(row_int + 1)),      # S
            (int(col_int - 1), int(row_int)),      # SW
            (int(col_int - 1), int(row_int - 1))   # NW
        ]
    else:  # Odd column
        neighbors = [
            (int(col_int), int(row_int - 1)),      # N
            (int(col_int + 1), int(row_int)),      # NE
            (int(col_int + 1), int(row_int + 1)),  # SE
            (int(col_int), int(row_int + 1)),      # S
            (int(col_int - 1), int(row_int + 1)),  # SW
            (int(col_int - 1), int(row_int))       # NW
        ]
    
    return neighbors


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
    col_int, row_int = int(col), int(row)
    if (col_int, row_int) in occupied_positions:
        return False

    return True


def movement_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str) -> List[Tuple[int, int]]:
    """
    Build valid movement destinations using BFS pathfinding.

    CRITICAL FIX: Uses BFS to find REACHABLE hexes, not just hexes within distance.
    This prevents movement through walls (AI_TURN.md compliance).

    PERFORMANCE: Pre-computes enemy adjacent hexes and occupied positions once at BFS start for O(1) lookups.
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    move_range = unit["MOVE"]
    # CRITICAL: Convert coordinates to int for consistent tuple comparison
    start_col, start_row = int(unit["col"]), int(unit["row"])
    start_pos = (start_col, start_row)

    # PERFORMANCE: Pre-compute enemy adjacent hexes once for this BFS
    # This reduces O(n) per hex check to O(1) set lookup
    enemy_adjacent_hexes = _build_enemy_adjacent_hexes(game_state, unit["player"])

    # PERFORMANCE: Pre-compute occupied positions once for this BFS
    # This reduces O(n) per-hex unit iteration to O(1) set lookup
    # CRITICAL: Convert coordinates to int to ensure consistent tuple comparison
    occupied_positions = {(int(u["col"]), int(u["row"])) for u in game_state["units"]
                         if u["HP_CUR"] > 0 and u["id"] != unit["id"]}

    # BFS pathfinding to find all reachable hexes
    visited = {start_pos: 0}  # {(col, row): distance_from_start}
    queue = [(start_pos, 0)]  # [(position, distance)]
    valid_destinations = []

    while queue:
        current_pos, current_dist = queue.pop(0)
        current_col, current_row = current_pos

        # If we've reached max movement, don't explore further from this hex
        if current_dist >= move_range:
            continue

        # Explore all 6 hex neighbors
        neighbors = _get_hex_neighbors(current_col, current_row)

        for neighbor_col, neighbor_row in neighbors:
            # CRITICAL: Convert coordinates to int IMMEDIATELY to ensure all tuples are (int, int)
            # This prevents type mismatch bugs in visited dict, valid_destinations list, and queue
            neighbor_col_int, neighbor_row_int = int(neighbor_col), int(neighbor_row)
            neighbor_pos = (neighbor_col_int, neighbor_row_int)
            neighbor_dist = current_dist + 1

            # Skip if already visited with a shorter path
            if neighbor_pos in visited:
                continue

            # Check if this neighbor is traversable (not a wall, not occupied)
            # PERFORMANCE: Pass pre-computed occupied_positions for O(1) lookup
            if not _is_traversable_hex(game_state, neighbor_col_int, neighbor_row_int, unit, occupied_positions):
                continue  # Can't move through this hex

            # CRITICAL: Cannot move THROUGH hexes adjacent to enemies (per movement rules)
            # Check enemy adjacency BEFORE marking as visited
            # PERFORMANCE: Uses pre-computed set for O(1) lookup
            # CRITICAL: Direct check with already-converted coordinates
            if (neighbor_col_int, neighbor_row_int) in enemy_adjacent_hexes:
                # Log why this hex is blocked (only in training context)
                if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
                    episode = game_state["episode_number"]
                    turn = game_state["turn"]
                    phase = game_state.get("phase", "move")
                    if "console_logs" not in game_state:
                        game_state["console_logs"] = []
                    log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} build_valid_destinations: hex ({neighbor_col_int},{neighbor_row_int}) BLOCKED - in enemy_adjacent_hexes"
                    game_state["console_logs"].append(log_message)
                    print(log_message)
                continue  # Cannot move through this hex - don't add to queue or destinations

            # Mark as visited AFTER all blocking checks pass
            visited[neighbor_pos] = neighbor_dist

            # Check if this is a valid destination (not wall, not occupied, not adjacent to enemy)
            # PERFORMANCE: Uses pre-computed set for O(1) lookup
            if _is_valid_destination(game_state, neighbor_col_int, neighbor_row_int, unit, {}, enemy_adjacent_hexes):
                # Don't add start position as a destination
                if neighbor_pos != start_pos:
                    # CRITICAL BUG DETECTION: Check if hex is in enemy_adjacent_hexes (should never happen)
                    if neighbor_pos in enemy_adjacent_hexes:
                        # This is a BUG - hex adjacent to enemy should not be in valid_destinations
                        if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
                            episode = game_state["episode_number"]
                            turn = game_state["turn"]
                            phase = game_state.get("phase", "move")
                            if "console_logs" not in game_state:
                                game_state["console_logs"] = []
                            log_message = f"[MOVE DEBUG] ⚠️ BUG DETECTED E{episode} T{turn} {phase} build_valid_destinations: hex ({neighbor_col_int},{neighbor_row_int}) is BOTH in valid_destinations AND enemy_adjacent_hexes! enemy_adjacent_hexes sample: {list(enemy_adjacent_hexes)[:5]}"
                            game_state["console_logs"].append(log_message)
                            print(log_message)
                        # DO NOT ADD - this is a bug, skip this hex
                        continue
                    valid_destinations.append(neighbor_pos)
                    # Log when a destination is added (only in training context)
                    # Note: The CRITICAL BUG DETECTION check at line 786 already logs problematic hexes

            # Add to queue for further exploration
            queue.append((neighbor_pos, neighbor_dist))

    game_state["valid_move_destinations_pool"] = valid_destinations

    # Log valid destinations result
    _log_movement_debug(game_state, "build_valid_destinations", str(unit_id), f"valid_destinations={valid_destinations} count={len(valid_destinations)}")

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
    from engine.utils.weapon_helpers import get_max_ranged_range

    # Direct field access with validation
    if "units" not in game_state:
        raise KeyError("game_state missing required 'units' field")
    if "col" not in unit or "row" not in unit:
        raise KeyError(f"Unit missing required position fields: {unit}")
    if "player" not in unit:
        raise KeyError(f"Unit missing required 'player' field: {unit}")
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_RNG
    if not unit.get("RNG_WEAPONS") and not unit.get("CC_WEAPONS"):
        raise KeyError(f"Unit missing required 'RNG_WEAPONS' or 'CC_WEAPONS' field: {unit}")

    # If no destinations, return current position
    if not valid_destinations:
        return (unit["col"], unit["row"])

    # Get enemy units
    enemy_units = [u for u in game_state["units"]
                   if u["player"] != unit["player"] and u.get("HP_CUR", 0) > 0]

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
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max ranged range from weapons
        weapon_range = get_max_ranged_range(unit)
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


def movement_preview(valid_destinations: List[Tuple[int, int]]) -> Dict[str, Any]:
    """AI_MOVE.md: Generate preview data for green hexes"""
    return {
        "green_hexes": valid_destinations,
        "show_preview": True
    }


def movement_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_MOVE.md: Clear movement preview"""
    game_state["preview_hexes"] = []
    game_state["valid_move_destinations_pool"] = []
    return {
        "show_preview": False,
        "clear_hexes": True
    }


def movement_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Route click actions"""
    # AI_TURN.md COMPLIANCE: Direct field access
    if "clickTarget" not in action:
        click_target = "elsewhere"  # Default behavior for missing field
    else:
        click_target = action["clickTarget"]
    
    if click_target == "destination_hex":
        return movement_destination_selection_handler(game_state, unit_id, action)
    elif click_target == "friendly_unit":
        return False, {"error": "unit_switch_not_implemented"}
    elif click_target == "active_unit":
        return True, {"action": "no_effect"}
    else:
        return True, {"action": "continue_selection"}

def movement_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Handle destination selection and execute movement"""
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "destCol" not in action:
        raise KeyError(f"Action missing required 'destCol' field: {action}")
    if "destRow" not in action:
        raise KeyError(f"Action missing required 'destRow' field: {action}")
    dest_col = action["destCol"]
    dest_row = action["destRow"]

    if dest_col is None or dest_row is None:
        return False, {"error": "missing_destination"}
    
    # CRITICAL: Convert coordinates to int for consistent tuple comparison
    dest_col, dest_row = int(dest_col), int(dest_row)
    
    # CRITICAL FIX: ALWAYS rebuild pool fresh on validation to prevent stale data
    # This ensures frontend/backend pathfinding stay synchronized even if game state changed
    movement_build_valid_destinations_pool(game_state, unit_id)
    
    if "valid_move_destinations_pool" not in game_state:
        raise KeyError("game_state missing required 'valid_move_destinations_pool' field")
    valid_pool = game_state["valid_move_destinations_pool"]
    
    # Validate destination in valid pool
    if (dest_col, dest_row) not in valid_pool:
        # Destination not reachable via BFS pathfinding
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) NOT_IN_POOL pool_size={len(valid_pool)}")
        return False, {"error": "invalid_destination", "destination": (dest_col, dest_row)}
    
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}

    # CRITICAL FIX: Use _attempt_movement_to_destination() to validate occupation
    # This function checks if destination is occupied, validates enemy adjacency, etc.
    config = {}  # Empty config for now
    move_success, move_result = _attempt_movement_to_destination(game_state, unit, dest_col, dest_row, config)

    if not move_success:
        # Move was blocked (occupied hex, adjacent to enemy, etc.)
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) BLOCKED error={move_result.get('error', 'unknown')}")
        return False, move_result
    
    # Extract movement info from result
    # Log successful destination selection
    _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) SELECTED")
    was_adjacent = (move_result.get("action") == "flee")
    orig_col = move_result.get("fromCol")
    orig_row = move_result.get("fromRow")

    # Position has already been updated by _attempt_movement_to_destination()
    # Validate it actually changed
    if unit["col"] != dest_col or unit["row"] != dest_row:
        return False, {"error": "position_update_failed"}
    
    # Generate movement log per requested format
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # Calculate reward for this action using RewardMapper
    action_reward = 0.0
    action_name = "FLEE" if was_adjacent else "MOVE"
    
    try:
        from ai.reward_mapper import RewardMapper
        reward_configs = game_state.get("reward_configs", {})
        
        if reward_configs:
            # Map scenario unit type to reward config key
            from ai.unit_registry import UnitRegistry
            unit_registry = UnitRegistry()
            scenario_unit_type = unit["unitType"]
            reward_config_key = unit_registry.get_model_key(scenario_unit_type)
            
            # Get unit-specific config or fallback to default
            unit_reward_config = reward_configs.get(reward_config_key)
            if not unit_reward_config:
                raise ValueError(f"No reward config found for unit type '{reward_config_key}' in reward_configs")

            reward_mapper = RewardMapper(unit_reward_config)
            unit_registry = UnitRegistry()
            scenario_unit_type = unit["unitType"]
            reward_config_key = unit_registry.get_model_key(scenario_unit_type)
            
            # Create enriched unit with correct key for reward lookup
            enriched_unit = unit.copy()
            enriched_unit["unitType"] = reward_config_key
            
            # Build tactical context for movement
            tactical_context = {
                "moved_closer": True,  # Default - improve with actual logic if needed
                "moved_away": False,
                "moved_to_optimal_range": False,
                "moved_to_charge_range": False,
                "moved_to_safety": False
            }
            
            # CRITICAL FIX: get_movement_reward now returns (reward_value, action_name) tuple
            reward_result = reward_mapper.get_movement_reward(
                enriched_unit, 
                (orig_col, orig_row), 
                (dest_col, dest_row),
                tactical_context
            )
            
            # Unpack tuple: (reward_value, action_name)
            if isinstance(reward_result, tuple) and len(reward_result) == 2:
                action_reward, action_name = reward_result
            else:
                # Backward compatibility: if returns float only
                action_reward = reward_result
                action_name = "FLEE" if was_adjacent else "MOVE"
    except Exception as e:
        # Silent fallback - don't break game if reward calculation fails
        pass
    
    game_state["action_logs"].append({
        "type": "move",
        "message": f"Unit {unit['id']} ({orig_col}, {orig_row}) MOVED to ({dest_col}, {dest_row})",
        "turn": game_state["current_turn"] if "current_turn" in game_state else 1,
        "phase": "move",
        "unitId": unit["id"],
        "player": unit["player"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "was_flee": was_adjacent,
        "timestamp": "server_time",
        "action_name": action_name,  # NEW: For debug display
        "reward": round(action_reward, 2),  # NEW: Calculated reward
        "is_ai_action": unit["player"] == 2  # FIXED: PvE AI is player 2 (was P0/P1, now P1/P2)
    })
    
    # Clear preview
    movement_clear_preview(game_state)
    
    # End activation with position data for reward calculation
    # AI_TURN.md EXACT: end_activation(Arg1, Arg2, Arg3, Arg4, Arg5)
    action_type = "FLED" if was_adjacent else "MOVE"
    result = end_activation(
        game_state, unit,
        "ACTION",      # Arg1: Log the action (movement already logged)
        1,             # Arg2: +1 step increment  
        action_type,   # Arg3: MOVE or FLED tracking
        "MOVE",        # Arg4: Remove from move_activation_pool
        0              # Arg5: No error logging
    )
    
    # Add position data for reward calculation
    # CHANGE 8: Detect same-position moves (unit didn't actually move)
    actually_moved = (orig_col != dest_col) or (orig_row != dest_row)
    
    if not actually_moved:
        # Unit stayed in same position - treat as wait, not move
        action_name = "wait"
    elif was_adjacent:
        action_name = "flee"
    else:
        action_name = "move"
    
    result.update({
        "action": action_name,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "activation_complete": True
    })
    
    return True, result


def _is_adjacent_to_enemy_simple(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """AI_MOVE.md: Simplified flee detection (distance <= 1, no CC_RNG)
    
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


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Handle skip action"""
    # REMOVED: Duplicate logging - AI_TURN.md end_activation handles ALL logging
    # AI_TURN.md PRINCIPLE: end_activation is SINGLE SOURCE for action logging
    
    movement_clear_preview(game_state)
    
    # AI_TURN.md EXACT: end_activation for skip action
    result = end_activation(
        game_state, unit,
        "WAIT",        # Arg1: Log wait action (SINGLE SOURCE)
        1,             # Arg2: +1 step increment
        "MOVE",        # Arg3: Mark as moved (even for skip)
        "MOVE",        # Arg4: Remove from move_activation_pool
        0              # Arg5: No error logging
    )
    
    result.update({
        "action": "wait",  # CHANGE 7: Return 'wait' not 'skip' for StepLogger whitelist
        "unitId": unit["id"],
        "activation_complete": True
    })
    
    return True, result


def movement_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_MOVE.md: Clean up and end movement phase"""
    movement_clear_preview(game_state)
    
    # NEW: Track phase completion reason (AI_TURN.md compliance)
    if 'last_compliance_data' not in game_state:
        game_state['last_compliance_data'] = {}
    game_state['last_compliance_data']['phase_end_reason'] = 'eligibility'
    
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("MOVEMENT PHASE COMPLETE")
    
    return {
        "phase_complete": True,
        "next_phase": "shoot",
        "units_processed": len([u for u in game_state["units"] if u["id"] in game_state["units_moved"]])
    }


def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state.

    CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
    """
    for unit in game_state["units"]:
        if str(unit["id"]) == str(unit_id):
            return unit
    return None
