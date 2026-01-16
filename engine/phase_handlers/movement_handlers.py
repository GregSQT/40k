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


def _normalize_coordinate(coord: Any) -> int:
    """
    Normalize coordinate to int. Raises ValueError if conversion fails.
    
    CRITICAL: All coordinates must be int. This function ensures type consistency
    and raises clear errors if coordinates are invalid.
    """
    if isinstance(coord, int):
        return coord
    elif isinstance(coord, float):
        return int(coord)
    elif isinstance(coord, str):
        try:
            return int(float(coord))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid coordinate string '{coord}': {e}")
    else:
        raise TypeError(f"Invalid coordinate type {type(coord).__name__}: {coord}. Expected int, float, or numeric string.")


def _normalize_coordinates(col: Any, row: Any) -> Tuple[int, int]:
    """
    Normalize both coordinates to int. Raises ValueError if conversion fails.
    """
    return _normalize_coordinate(col), _normalize_coordinate(row)


def _invalidate_all_destination_pools_after_movement(game_state: Dict[str, Any]) -> None:
    """
    CRITICAL: Invalidate all destination pools after any unit movement.
    
    After a unit moves, all destination pools become stale because:
    - Occupied positions have changed
    - Enemy adjacent hexes have changed
    - Friendly adjacent hexes have changed (for future use)
    
    This function clears:
    - valid_move_destinations_pool (for all units)
    - valid_charge_destinations_pool (for all units)
    - valid_target_pool (for all units in shoot phase)
    - _target_pool_cache (global cache in shooting_handlers)
    
    Called after every movement in move, shoot (advance), and charge phases.
    """
    # Clear movement destination pools
    if "valid_move_destinations_pool" in game_state:
        game_state["valid_move_destinations_pool"] = []
    
    # Clear charge destination pools
    if "valid_charge_destinations_pool" in game_state:
        game_state["valid_charge_destinations_pool"] = []
    
    # Clear target pools for all units (shoot phase)
    for unit in game_state.get("units", []):
        if "valid_target_pool" in unit:
            unit["valid_target_pool"] = []
    
    # Clear global target pool cache (shooting_handlers)
    from .shooting_handlers import _target_pool_cache
    _target_pool_cache.clear()
    
    # Log invalidation (only in training context)
    if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        phase = game_state.get("phase", "?")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_message = f"[POOL INVALIDATION] E{episode} T{turn} {phase}: All destination pools invalidated after movement"
        from engine.game_utils import add_console_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)


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
    from engine.game_utils import add_console_log
    from engine.game_utils import safe_print
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)  # Also print to console for immediate visibility


def movement_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_MOVE.md: Initialize movement phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "move"
    
    # CRITICAL: Invalidate all destination pools at the START of the phase
    # This ensures pools are clean and don't contain stale data from previous phases
    _invalidate_all_destination_pools_after_movement(game_state)
    
    # Build activation pool
    movement_build_activation_pool(game_state)
    
    # Console log
    from engine.game_utils import add_console_log
    add_console_log(game_state, "MOVEMENT POOL BUILT")
    
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
    # CRITICAL: Clear pool before rebuilding (defense in depth)
    game_state["move_activation_pool"] = []
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
        from engine.game_utils import add_console_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)  # Also print to console for immediate visibility


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

        # Check if unit has at least one adjacent hex that is not occupied and not adjacent to enemy
        # This ensures the unit can actually move
        unit_col, unit_row = _normalize_coordinates(unit["col"], unit["row"])
        neighbors = _get_hex_neighbors(unit_col, unit_row)
        
        # Pre-compute occupied positions and enemy adjacent hexes for this check
        occupied_positions = set()
        for u in game_state["units"]:
            if u["HP_CUR"] > 0 and u["id"] != unit["id"]:
                col_int, row_int = _normalize_coordinates(u["col"], u["row"])
                occupied_positions.add((col_int, row_int))
        # CRITICAL: Convert player to int for consistent comparison in _build_enemy_adjacent_hexes
        unit_player_int = int(unit["player"]) if unit["player"] is not None else None
        enemy_adjacent_hexes = _build_enemy_adjacent_hexes(game_state, unit_player_int)
        
        has_valid_adjacent_hex = False
        for neighbor_col, neighbor_row in neighbors:
            neighbor_pos = (int(neighbor_col), int(neighbor_row))
            
            # Check bounds
            if (neighbor_col < 0 or neighbor_row < 0 or
                neighbor_col >= game_state["board_cols"] or
                neighbor_row >= game_state["board_rows"]):
                continue
            
            # Check wall
            if neighbor_pos in game_state["wall_hexes"]:
                continue
            
            # Check occupied
            if neighbor_pos in occupied_positions:
                continue
            
            # Check adjacent to enemy
            if neighbor_pos in enemy_adjacent_hexes:
                continue
            
            # Found a valid adjacent hex
            has_valid_adjacent_hex = True
            break
        
        if not has_valid_adjacent_hex:
            continue  # Unit cannot move (no valid adjacent hex)

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
        from engine.game_utils import add_console_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)  # Also print to console for immediate visibility

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
    # AI_TURN.md COMPLIANCE: In gym training, ActionDecoder constructs complete movement with destCol/destRow
    # So we should NOT return waiting_for_player=True if action already has destination
    if not game_state.get("active_movement_unit") and action_type in ["move", "left_click"]:
        if is_gym_training:
            # Gym training: Check if action already has destination (ActionDecoder constructed it)
            if "destCol" in action and "destRow" in action:
                # Action already has destination - execute movement directly, no waiting needed
                # Just ensure unit is activated, then continue to movement_destination_selection_handler
                movement_unit_activation_start(game_state, unit_id)
                # Build valid destinations pool for validation
                movement_build_valid_destinations_pool(game_state, unit_id)
                # Continue to execute movement directly (fall through to movement_destination_selection_handler below)
            else:
                # DIAGNOSTIC: ActionDecoder should always provide destination, but it doesn't
                # This should not happen in gym training - log for debugging
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                from engine.game_utils import add_console_log
                diagnostic_msg = f"[MOVE DIAGNOSTIC] E{episode} T{turn} Unit {unit_id}: ActionDecoder did not provide destCol/destRow. action keys: {list(action.keys())}"
                add_console_log(game_state, diagnostic_msg)
                # No destination yet - return waiting_for_player to get destination selection
                return _handle_unit_activation(game_state, active_unit, config)
        else:
            # Human players: activate but don't return, continue to normal flow
            _handle_unit_activation(game_state, active_unit, config)
    
    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)
    
    elif action_type == "move":
        # AI_TURN.md COMPLIANCE: Execute movement directly (destination already in action for gym training)
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
            # CRITICAL: No default value - require explicit attempted_action
            attempted_action = action.get("attempted_action")
            if attempted_action is None:
                raise ValueError(f"Action missing 'attempted_action' field: {action}")
            result["attempted_action"] = attempted_action
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

    # AI_TURN.md COMPLIANCE: In gym training, ActionDecoder constructs complete movement with destCol/destRow
    # So we should NOT return waiting_for_player=True - the action will have destination when it arrives
    if is_gym_training and isinstance(execution_result, tuple) and execution_result[0]:
        # AI_TURN.md COMPLIANCE: Direct field access
        if "waiting_for_player" not in execution_result[1]:
            waiting_for_player = False
        else:
            waiting_for_player = execution_result[1]["waiting_for_player"]

        # AI_TURN.md: In gym training, ActionDecoder always provides destination in action
        # So we should NOT return waiting_for_player=True or waiting_for_movement_choice
        # Just return activation result without action (activation is not an action to log)
        # The movement will be executed in the same step when action with destCol/destRow is processed
        # Return result without action to skip logging (activation is not logged, only the movement is)
        return True, {
            "unit_activated": True,
            "unitId": unit["id"],
            "valid_destinations": execution_result[1].get("valid_destinations", []),
            # No action field - activation is not an action to log
            # Movement will be logged when action with destCol/destRow is processed
        }

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
    
    # AI_TURN.md COMPLIANCE: In gym training, ActionDecoder constructs complete movement with destCol/destRow
    # So we should NOT return waiting_for_player=True - the action will have destination when it arrives
    is_gym_training = game_state.get("gym_training_mode", False)
    
    if is_gym_training:
        # Gym training: Don't return waiting_for_player=True - ActionDecoder will provide destination in action
        # Return result without waiting_for_player so movement can be executed directly
        return True, {
            "unit_activated": True,
            "unitId": unit_id,
            "valid_destinations": game_state["valid_move_destinations_pool"],
            "preview_data": preview_data,
            "waiting_for_player": False  # AI_TURN.md: AI executes movement directly, no waiting
        }
    else:
        # Human players: return waiting_for_player for destination selection
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
    
    NOTE: Pool is already built in movement_unit_execution_loop() just after activation.
    Since system is sequential, pool is already built and validated.
    However, we still verify critical restrictions here as a safety check.
    """
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    dest_col_int, dest_row_int = _normalize_coordinates(dest_col, dest_row)
    
    # NOTE: Adjacency check is done in build_valid_destinations_pool via enemy_adjacent_hexes.
    # The pool should already exclude all hexes adjacent to enemies, so no redundant check here.
    
    # Store original position - normalize to ensure consistency
    orig_col, orig_row = _normalize_coordinates(unit["col"], unit["row"])
    
    # AI_TURN.md flee detection: was adjacent to enemy before move
    was_adjacent = _is_adjacent_to_enemy(game_state, unit)

    # CRITICAL: Final occupation check IMMEDIATELY before position assignment
    # This prevents race conditions where multiple units select the same destination
    # before any of them have moved. Must check JUST before assignment, not earlier.
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "move")
    
    # Check all units for occupation - CRITICAL: Normalize coordinates, raise error if invalid
    for check_unit in game_state["units"]:
        # CRITICAL: Normalize coordinates - raises clear error if invalid (no defensive try/except)
        check_col, check_row = _normalize_coordinates(check_unit["col"], check_unit["row"])
        
        # CRITICAL: Compare as integers to avoid type mismatch
        if (check_unit["id"] != unit["id"] and
            check_unit["HP_CUR"] > 0 and
            check_col == dest_col_int and
            check_row == dest_row_int):
            # Another unit already occupies this destination - prevent collision
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_msg = f"[MOVE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot move to ({dest_col_int},{dest_row_int}) - occupied by Unit {check_unit['id']}"
            from engine.game_utils import add_console_log, safe_print
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)
            import logging
            logging.basicConfig(filename='step.log', level=logging.INFO, format='%(message)s')
            logging.info(log_msg)
            return False, {
                "error": "destination_occupied",
                "occupant_id": check_unit["id"],
                "destination": (dest_col_int, dest_row_int)
            }

    # Execute movement - position assignment
    # CRITICAL: Log ALL position changes to detect unauthorized modifications
    # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) via MOVE"
    from engine.game_utils import add_console_log
    from engine.game_utils import safe_print
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)
    
    # CRITICAL: Log BEFORE each assignment to catch any modification
    from engine.game_utils import conditional_debug_print
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
    # CRITICAL: Assign normalized int coordinates - dest_col_int and dest_row_int are already int from _normalize_coordinates
    unit["col"] = dest_col_int
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: col set to {unit['col']}")
    unit["row"] = dest_row_int
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")
    
    # Apply AI_TURN.md tracking
    game_state["units_moved"].add(unit["id"])
    if was_adjacent:
        game_state["units_fled"].add(unit["id"])
        # CRITICAL: Units that fled are also marked as moved
        # (units_fled is a subset of units_moved)
    
    # CRITICAL: Invalidate LoS cache when unit moves
    # When a unit moves, all LoS calculations involving that unit are now invalid
    # This prevents "shoot through wall" bugs caused by stale cache
    from .shooting_handlers import _invalidate_los_cache_for_moved_unit
    _invalidate_los_cache_for_moved_unit(game_state, unit["id"])
    
    # Pools are invalidated at the START of the phase, not after each movement
    # This prevents invalidating the "moved" tracking of units that just moved
    
    # Log successful movement
    action_type = "FLEE" if was_adjacent else "MOVE"
    _log_movement_debug(game_state, "attempt_movement", str(unit["id"]), f"({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) SUCCESS {action_type}")
    
    # CRITICAL: Use normalized coordinates (dest_col_int, dest_row_int) in result
    # NOT dest_col/dest_row which might not be normalized
    return True, {
        "action": "flee" if was_adjacent else "move",
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col_int,  # CRITICAL: Use normalized coordinates
        "toRow": dest_row_int    # CRITICAL: Use normalized coordinates
    }


def _is_valid_destination(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any], config: Dict[str, Any],
                          enemy_adjacent_hexes: Set[Tuple[int, int]], occupied_positions: Set[Tuple[int, int]]) -> bool:
    """
    AI_TURN.md destination validation implementation.

    Validates movement destination per AI_TURN.md restrictions.

    PERFORMANCE: Uses pre-computed enemy_adjacent_hexes set for O(1) lookup.
    enemy_adjacent_hexes must be provided (use _build_enemy_adjacent_hexes()).
    """
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    col_int, row_int = _normalize_coordinates(col, row)
    
    # Board bounds check (use converted coordinates)
    if (col_int < 0 or row_int < 0 or
        col_int >= game_state["board_cols"] or
        row_int >= game_state["board_rows"]):
        return False

    # Wall collision check (use converted coordinates)
    if (col_int, row_int) in game_state["wall_hexes"]:
        return False

    # Unit occupation check
    # CRITICAL: Use pre-computed occupied_positions set for O(1) lookup and consistency
    # This ensures we use the same data as _is_traversable_hex
    if (col_int, row_int) in occupied_positions:
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
                    enemy_col, enemy_row = _normalize_coordinates(enemy["col"], enemy["row"])
                    neighbors = _get_hex_neighbors(enemy_col, enemy_row)
                    if (col_int, row_int) in neighbors:
                        adjacent_enemies.append(f"Unit {enemy['id']} at ({enemy_col},{enemy_row})")
            log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} is_valid_destination: hex ({col_int},{row_int}) INVALID - adjacent to enemy (in enemy_adjacent_hexes) enemies={adjacent_enemies}"
            from engine.game_utils import add_console_log, safe_print
            add_console_log(game_state, log_message)
            safe_print(game_state, log_message)
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
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    unit_col, unit_row = _normalize_coordinates(unit["col"], unit["row"])

    # Optimization: For CC_RNG=1 (most common), check 6 neighbors directly
    result = False
    if cc_range == 1:
        hex_neighbors = set(_get_hex_neighbors(unit_col, unit_row))
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                # CRITICAL: Normalize coordinates to int - raises error if invalid
                enemy_col, enemy_row = _normalize_coordinates(enemy["col"], enemy["row"])
                enemy_pos = (enemy_col, enemy_row)
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
    
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    col_int, row_int = _normalize_coordinates(col, row)
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
    # DEBUG: Always log when function is called to diagnose logging issues
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    debug_mode_val = game_state.get("debug_mode", False)
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "?")
    test_log = f"[DEBUG TEST] _build_enemy_adjacent_hexes called: debug_mode={debug_mode_val}, episode={episode}, turn={turn}, phase={phase}, player={player}"
    game_state["console_logs"].append(test_log)
    
    enemy_adjacent_hexes = set()
    enemies_processed = []  # Track enemies for debugging
    all_units_info = []  # Track all units for debugging

    enemies_detailed = []  # Track detailed enemy info for debugging
    for enemy in game_state["units"]:
        # Log all units for debugging
        unit_info = f"Unit {enemy['id']} player={enemy['player']} HP={enemy.get('HP_CUR', 0)} at ({int(enemy['col'])},{int(enemy['row'])})"
        all_units_info.append(unit_info)
        
        # CRITICAL: Convert player to int for consistent comparison
        enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
        player_int = int(player) if player is not None else None
        
        # Build detailed enemy info for debugging
        hp_cur_raw = enemy.get("HP_CUR", 0)
        # CRITICAL: Ensure hp_cur is always an int (handle None and string cases)
        try:
            hp_cur = int(float(hp_cur_raw)) if hp_cur_raw is not None else 0
        except (ValueError, TypeError):
            hp_cur = 0
        hp_max = enemy.get("HP_MAX", "?")
        # CRITICAL: Normalize coordinates to int - raises error if invalid
        enemy_col, enemy_row = _normalize_coordinates(enemy["col"], enemy["row"])
        is_dead = hp_cur <= 0
        is_friendly = enemy_player == player_int
        
        if is_friendly:
            status = "FRIENDLY"
        elif is_dead:
            status = "DEAD"
        else:
            status = "ALIVE_ENEMY"
        
        enemy_detail = f"Unit {enemy['id']} player={enemy_player} HP_CUR={hp_cur} HP_MAX={hp_max} at ({enemy_col},{enemy_row}) status={status}"
        enemies_detailed.append(enemy_detail)
        
        # Debug: Log why units are skipped
        if enemy_player == player_int:
            continue  # Skip friendly units
        if hp_cur <= 0:
            continue  # Skip dead units
        
        # CRITICAL: Convert coordinates to int before calculating neighbors
        # CRITICAL: Normalize coordinates to int - raises error if invalid
        enemy_col, enemy_row = _normalize_coordinates(enemy["col"], enemy["row"])
        
        enemies_processed.append(f"Unit {enemy['id']} at ({enemy_col},{enemy_row})")
        # Add all 6 neighbors of this enemy to the set
        neighbors = _get_hex_neighbors(enemy_col, enemy_row)
        for neighbor in neighbors:
            # CRITICAL: Ensure neighbor coordinates are int tuples for consistent comparison
            neighbor_col, neighbor_row = neighbor
            hex_tuple = (int(neighbor_col), int(neighbor_row))
            enemy_adjacent_hexes.add(hex_tuple)

    # Log enemy adjacent hexes result (only in debug mode to avoid performance impact)
    # Always log for P1 to debug the (4,8) issue
    should_log = game_state.get("debug_mode", False) or player == 1
    if should_log:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        # Convert set to sorted list for readable output
        sorted_hexes = sorted(enemy_adjacent_hexes)
        # CRITICAL: Log the complete list of hexes in enemy_adjacent_hexes
        hexes_list_str = str(sorted_hexes) if len(sorted_hexes) <= 100 else str(sorted_hexes[:100]) + f"... (total {len(sorted_hexes)})"
        log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} build_enemy_adjacent_hexes player={player}: enemy_adjacent_hexes count={len(enemy_adjacent_hexes)} enemies={enemies_processed} enemies_detailed={enemies_detailed} all_units={all_units_info} hexes={hexes_list_str}"
        from engine.game_utils import add_console_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)  # Also print to console for immediate visibility

    return enemy_adjacent_hexes


def _get_hex_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """
    Get all 6 hexagonal neighbors for offset coordinates.
    
    Hex neighbor offsets depend on whether column is even or odd.
    Even columns: NE/SE are (+1, -1) and (+1, 0)
    Odd columns: NE/SE are (+1, 0) and (+1, +1)
    
    CRITICAL: Explicitly ensures all returned tuples are (int, int) for type consistency.
    """
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    col_int, row_int = _normalize_coordinates(col, row)
    
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
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    col_int, row_int = _normalize_coordinates(col, row)
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
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    start_col, start_row = _normalize_coordinates(unit["col"], unit["row"])
    start_pos = (start_col, start_row)

    # PERFORMANCE: Pre-compute enemy adjacent hexes once for this BFS
    # This reduces O(n) per hex check to O(1) set lookup
    # CRITICAL: Convert player to int for consistent comparison in _build_enemy_adjacent_hexes
    unit_player_int = int(unit["player"]) if unit["player"] is not None else None
    enemy_adjacent_hexes = _build_enemy_adjacent_hexes(game_state, unit_player_int)

    # PERFORMANCE: Pre-compute occupied positions once for this BFS
    # This reduces O(n) per-hex unit iteration to O(1) set lookup
    # CRITICAL: Convert coordinates to int to ensure consistent tuple comparison
    # Use int(float(...)) to handle both int and float coordinates correctly
    # CRITICAL: Rebuild occupied_positions at the START of BFS to ensure it's current
    # This is done at the start of unit activation, so no other unit can move during this activation
    occupied_positions = set()
    units_processed = 0
    units_skipped = 0
    for u in game_state["units"]:
        units_processed += 1
        if u["HP_CUR"] > 0 and u["id"] != unit["id"]:
            # CRITICAL: Normalize coordinates - raises clear error if invalid (no defensive try/except)
            col_int, row_int = _normalize_coordinates(u["col"], u["row"])
            occupied_positions.add((col_int, row_int))
    
    # DEBUG: Log all units and their positions for collision debugging
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        total_units = len(game_state["units"])
        active_units = sum(1 for u in game_state["units"] if u["HP_CUR"] > 0)
        occupied_count = len(occupied_positions)
        expected_count = active_units - (1 if unit["HP_CUR"] > 0 else 0)  # Minus the active unit itself
        
        # Log all units and their positions
        units_info = []
        for u in game_state["units"]:
            if u["HP_CUR"] > 0:
                # CRITICAL: Normalize coordinates - raises clear error if invalid (no defensive try/except)
                col_int, row_int = _normalize_coordinates(u["col"], u["row"])
                in_occupied = (col_int, row_int) in occupied_positions
                units_info.append(f"Unit {u['id']}@({col_int},{row_int}){'✓' if in_occupied else '✗'}")
        
        from engine.game_utils import add_console_log, safe_print
        log_msg = f"[OCCUPIED_POSITIONS] E{episode} T{turn} Unit {unit['id']}: total={total_units}, active={active_units}, occupied={occupied_count}, expected={expected_count}, units={','.join(units_info[:10])}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)

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
                    from engine.game_utils import add_console_log
                    from engine.game_utils import safe_print
                    add_console_log(game_state, log_message)
                    safe_print(game_state, log_message)
                continue  # Cannot move through this hex - don't add to queue or destinations

            # Mark as visited AFTER all blocking checks pass
            visited[neighbor_pos] = neighbor_dist

            # Check if this is a valid destination (not wall, not occupied, not adjacent to enemy)
            # PERFORMANCE: Uses pre-computed set for O(1) lookup
            # NOTE: Enemy adjacency already checked at line 996, so this should never be adjacent
            if _is_valid_destination(game_state, neighbor_col_int, neighbor_row_int, unit, {}, enemy_adjacent_hexes, occupied_positions):
                # Don't add start position as a destination
                if neighbor_pos != start_pos:
                    valid_destinations.append(neighbor_pos)
                    # Log when a destination is added (only in training context)
                    # Note: The CRITICAL BUG DETECTION check at line 786 already logs problematic hexes

            # Add to queue for further exploration
            queue.append((neighbor_pos, neighbor_dist))

    game_state["valid_move_destinations_pool"] = valid_destinations

    # DEBUG: Log occupied_positions and valid_destinations for collision debugging
    if "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "move")
        from engine.game_utils import add_console_log, safe_print
        log_msg = f"[POOL DEBUG] E{episode} T{turn} {phase} Unit {unit_id}: occupied_positions={sorted(occupied_positions)[:10]}... (total={len(occupied_positions)}), valid_destinations={len(valid_destinations)}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)

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
    game_state["active_movement_unit"] = None
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
    # CRITICAL: Normalize coordinates to int - raises error if invalid
    dest_col, dest_row = _normalize_coordinates(dest_col, dest_row)
    
    # Pool is already built during activation - no need to rebuild here
    # System is sequential, so pool is still valid
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
    
    # CRITICAL: Rebuild enemy_adjacent_hexes just before execution to catch positions that changed
    # This prevents movements to destinations that became adjacent after the pool was built
    unit_player_int = int(unit["player"]) if unit["player"] is not None else None
    current_enemy_adjacent_hexes = _build_enemy_adjacent_hexes(game_state, unit_player_int)
    if (dest_col, dest_row) in current_enemy_adjacent_hexes:
        # Destination is adjacent to enemy - REJECT even if it's in the pool
        # This can happen if an enemy moved after the pool was built
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        from engine.game_utils import add_console_log, safe_print
        log_msg = f"[MOVE REJECTED] E{episode} T{turn} Unit {unit_id} destination ({dest_col},{dest_row}) is ADJACENT TO ENEMY - REJECTED (was in pool but enemy positions changed)"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        import logging
        logging.basicConfig(filename='step.log', level=logging.INFO, format='%(message)s')
        logging.info(log_msg)
        return False, {"error": "destination_adjacent_to_enemy", "destination": (dest_col, dest_row)}

    # CRITICAL FIX: Use _attempt_movement_to_destination() to validate occupation
    # This function checks if destination is occupied, validates enemy adjacency, etc.
    config = {}  # Empty config for now
    move_success, move_result = _attempt_movement_to_destination(game_state, unit, dest_col, dest_row, config)

    if not move_success:
        # Move was blocked (occupied hex, adjacent to enemy, etc.)
        error_type = move_result.get('error', 'unknown')
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) BLOCKED error={error_type}")
        
        # CRITICAL FIX: If destination is invalid (adjacent to enemy), remove it from pool
        # to prevent infinite loops where agent keeps trying invalid destinations
        if error_type == "destination_adjacent_to_enemy" and "valid_move_destinations_pool" in game_state:
            invalid_dest = (dest_col, dest_row)
            if invalid_dest in game_state["valid_move_destinations_pool"]:
                game_state["valid_move_destinations_pool"].remove(invalid_dest)
                # Also update pending_movement_destinations if it exists
                if "pending_movement_destinations" in game_state and invalid_dest in game_state["pending_movement_destinations"]:
                    game_state["pending_movement_destinations"].remove(invalid_dest)
                
                # If pool is now empty, force skip this unit to prevent infinite loop
                if not game_state["valid_move_destinations_pool"]:
                    _log_movement_debug(game_state, "destination_selection", str(unit_id), "ALL destinations invalid - forcing skip to prevent infinite loop")
                    return _handle_skip_action(game_state, unit)
        
        return False, move_result
    
    # Extract movement info from result
    # Log successful destination selection
    _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) SELECTED")
    was_adjacent = (move_result.get("action") == "flee")
    # CRITICAL: Use fromCol/fromRow from move_result (set by _attempt_movement_to_destination before movement)
    # These are the original coordinates BEFORE the movement
    orig_col = move_result.get("fromCol")
    orig_row = move_result.get("fromRow")
    if orig_col is None or orig_row is None:
        raise ValueError(f"move_result missing fromCol/fromRow: move_result keys={list(move_result.keys())}")

    # Position has already been updated by _attempt_movement_to_destination()
    # Validate it actually changed
    if unit["col"] != dest_col or unit["row"] != dest_row:
        return False, {"error": "position_update_failed"}
    
    # CRITICAL DEBUG: Log exact values before using unit coordinates
    from engine.game_utils import add_console_log, safe_print
    episode = game_state.get('episode_number', '?')
    turn = game_state.get('turn', '?')
    debug_msg = f"[MOVEMENT DEBUG] E{episode} T{turn} Unit {unit_id}: dest_col={dest_col} dest_row={dest_row} unit_col={unit['col']} unit_row={unit['row']} move_result_toCol={move_result.get('toCol')} move_result_toRow={move_result.get('toRow')}"
    add_console_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
    # CRITICAL FIX: Invalidate all destination pools after movement
    # Positions have changed, so all pools (move, charge, shoot) are now stale
    _invalidate_all_destination_pools_after_movement(game_state)
    
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
    
    # CRITICAL: Use unit coordinates AFTER movement - SINGLE SOURCE OF TRUTH
    # NOT move_result.get("toCol")/toRow which comes from action["destCol"]/destRow
    # NOT action["destCol"]/destRow which might be incorrect
    # The unit's position is the ONLY reliable source after movement execution
    result_to_col = unit["col"]
    result_to_row = unit["row"]
    
    # CRITICAL DEBUG: Log exact values being used for result
    from engine.game_utils import add_console_log, safe_print
    episode = game_state.get('episode_number', '?')
    turn = game_state.get('turn', '?')
    debug_msg = f"[MOVEMENT DEBUG] E{episode} T{turn} Unit {unit_id}: Using result_to_col={result_to_col} result_to_row={result_to_row} (unit_col={unit['col']} unit_row={unit['row']} move_result_toCol={move_result.get('toCol')} move_result_toRow={move_result.get('toRow')}) for logging"
    add_console_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
    result.update({
        "action": action_name,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": result_to_col,  # CRITICAL: Use unit coordinates after movement - SINGLE SOURCE OF TRUTH
        "toRow": result_to_row,  # CRITICAL: Use unit coordinates after movement - SINGLE SOURCE OF TRUTH
        "activation_complete": True,
        "waiting_for_player": False  # AI_TURN.md: Movement is complete, no waiting needed
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
    
    from engine.game_utils import add_console_log
    add_console_log(game_state, "MOVEMENT PHASE COMPLETE")
    
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
