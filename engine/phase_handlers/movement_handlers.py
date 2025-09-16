#!/usr/bin/env python3
"""
movement_handlers.py - AI_TURN.md Movement Phase Implementation
Pure stateless functions implementing AI_TURN.md movement specification

References: AI_TURN.md Section 🏃 MOVEMENT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any


def movement_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_MOVE.md: Initialize movement phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "move"
    
    # Clear tracking sets at START OF PHASE
    game_state["units_moved"] = set()
    game_state["units_fled"] = set()
    game_state["units_shot"] = set()
    game_state["units_charged"] = set()
    game_state["units_attacked"] = set()
    
    # Clear movement preview state
    game_state["valid_move_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_movement_unit"] = None
    
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
    eligible_units = get_eligible_units(game_state)
    game_state["move_activation_pool"] = eligible_units
    print(f"MOVEMENT POOL CREATED: Player {game_state['current_player']} -> {eligible_units}")


def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md movement eligibility decision tree implementation.
    
    Returns list of unit IDs eligible for movement activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]
    
    for unit in game_state["units"]:
        # AI_TURN.md: "unit.HP_CUR > 0?"
        if unit["HP_CUR"] <= 0:
            continue  # Dead unit (Skip, no log)
            
        # AI_TURN.md: "unit.player === current_player?"
        if unit["player"] != current_player:
            continue  # Wrong player (Skip, no log)
            
        # AI_TURN.md: "unit.id not in units_moved?"
        if unit["id"] in game_state["units_moved"]:
            continue  # Already moved (Skip, no log)
            
        # AI_TURN.md: Unit passes all conditions
        eligible_units.append(unit["id"])
    
    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_MOVE.md: Handler action routing with complete autonomy
    """
    # Pool empty? → Phase complete
    if not game_state["move_activation_pool"]:
        return True, movement_phase_end(game_state)
    
    # Get unit from action (frontend specifies which unit to move)
    action_type = action.get("action")
    unit_id = action.get("unitId")
    
    # For gym training, if no unitId specified, use first eligible unit
    if not unit_id:
        if game_state["move_activation_pool"]:
            unit_id = game_state["move_activation_pool"][0]
        else:
            return True, movement_phase_end(game_state)
    
    # Validate unit is eligible
    if unit_id not in game_state["move_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    active_unit = _get_unit_by_id(game_state, unit_id)
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id}
    
    # Auto-activate unit if not already activated and preview not shown
    if not game_state.get("active_movement_unit") and action_type in ["move", "left_click"]:
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
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "move"}


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Unit activation start + execution loop"""
    # Unit activation start
    movement_unit_activation_start(game_state, unit["id"])
    
    # Unit execution loop (automatic)
    return movement_unit_execution_loop(game_state, unit["id"])


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
        "valid_destinations": game_state["valid_move_destinations_pool"],
        "preview_data": preview_data,
        "waiting_for_player": True
    }


def _attempt_movement_to_destination(game_state: Dict[str, Any], unit: Dict[str, Any], dest_col: int, dest_row: int, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md movement execution with destination validation.
    
    Implements AI_TURN.md movement restrictions and flee detection.
    """
    # Validate destination per AI_TURN.md rules
    if not _is_valid_destination(game_state, dest_col, dest_row, unit, config):
        return False, {"error": "invalid_destination", "target": (dest_col, dest_row)}
    
    # AI_TURN.md flee detection: was adjacent to enemy before move
    was_adjacent = _is_adjacent_to_enemy(game_state, unit)
    
    # Store original position
    orig_col, orig_row = unit["col"], unit["row"]
    
    # Execute movement
    unit["col"] = dest_col
    unit["row"] = dest_row
    
    # Apply AI_TURN.md tracking
    game_state["units_moved"].add(unit["id"])
    if was_adjacent:
        game_state["units_fled"].add(unit["id"])
    
    return True, {
        "action": "flee" if was_adjacent else "move",
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row
    }


def _is_valid_destination(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any], config: Dict[str, Any]) -> bool:
    """
    AI_TURN.md destination validation implementation.
    
    Validates movement destination per AI_TURN.md restrictions.
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
    
    # AI_TURN.md: Cannot move TO hexes adjacent to enemies
    if _is_hex_adjacent_to_enemy(game_state, col, row, unit["player"]):
        return False
    
    return True


def _is_adjacent_to_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md flee detection logic.
    
    Check if unit is adjacent to enemy for flee marking.
    """
    cc_range = unit["CC_RNG"]
    
    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0):
            distance = max(abs(unit["col"] - enemy["col"]), 
                          abs(unit["row"] - enemy["row"]))
            if distance <= cc_range:
                return True
    return False


def _is_hex_adjacent_to_enemy(game_state: Dict[str, Any], col: int, row: int, player: int) -> bool:
    """
    AI_TURN.md adjacency restriction implementation.
    
    Check if hex position is adjacent to any enemy unit.
    """
    for enemy in game_state["units"]:
        if enemy["player"] != player and enemy["HP_CUR"] > 0:
            distance = max(abs(col - enemy["col"]), abs(row - enemy["row"]))
            if distance <= 1:  # Adjacent check
                return True
    return False


def movement_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str) -> List[Tuple[int, int]]:
    """AI_MOVE.md: Build valid movement destinations for unit"""
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []
    
    valid_destinations = []
    move_range = unit["MOVE"]
    start_col, start_row = unit["col"], unit["row"]
    
    # Check all hexes in a proper hex radius using cube coordinates
    for dest_col in range(start_col - move_range, start_col + move_range + 1):
        for dest_row in range(start_row - move_range, start_row + move_range + 1):
            # Skip current position
            if dest_col == start_col and dest_row == start_row:
                continue
            
            # Calculate actual hex distance using cube coordinates
            hex_distance = _calculate_hex_distance(start_col, start_row, dest_col, dest_row)
            if hex_distance > move_range:
                continue
            
            # Validate destination
            if _is_valid_destination(game_state, dest_col, dest_row, unit, {}):
                valid_destinations.append((dest_col, dest_row))
    
    game_state["valid_move_destinations_pool"] = valid_destinations
    return valid_destinations


def _calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Calculate proper hex distance using cube coordinates"""
    # Convert offset to cube coordinates
    x1 = col1 - (row1 - (row1 & 1)) // 2
    z1 = row1
    y1 = -x1 - z1
    
    x2 = col2 - (row2 - (row2 & 1)) // 2
    z2 = row2
    y2 = -x2 - z2
    
    # Cube distance
    return (abs(x1 - x2) + abs(y1 - y2) + abs(z1 - z2)) // 2


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
    click_target = action.get("clickTarget", "elsewhere")
    
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
    dest_col = action.get("destCol")
    dest_row = action.get("destRow")
    
    if dest_col is None or dest_row is None:
        return False, {"error": "missing_destination"}
    
    # Build valid destinations if not already built
    if not game_state.get("valid_move_destinations_pool"):
        movement_build_valid_destinations_pool(game_state, unit_id)
    
    valid_pool = game_state["valid_move_destinations_pool"]
    
    # Validate destination in valid pool
    if (dest_col, dest_row) not in valid_pool:
        return False, {"error": "invalid_destination", "destination": (dest_col, dest_row)}
    
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}
    
    # Check flee condition (simplified - distance <= 1)
    was_adjacent = _is_adjacent_to_enemy_simple(game_state, unit)
    
    # Execute movement
    orig_col, orig_row = unit["col"], unit["row"]
    unit["col"] = dest_col
    unit["row"] = dest_row
    
    # Generate movement log per requested format
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    game_state["action_logs"].append({
        "type": "move",
        "message": f"Unit {unit['id']} ({orig_col}, {orig_row}) MOVED to ({dest_col}, {dest_row})",
        "turn": game_state.get("current_turn", 1),
        "phase": "move",
        "unitId": unit["id"],
        "player": unit["player"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "was_flee": was_adjacent,
        "timestamp": "server_time"
    })
    
    # Clear preview
    movement_clear_preview(game_state)
    
    # End activation
    return _end_activation(game_state, unit, was_adjacent)


def _is_adjacent_to_enemy_simple(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """AI_MOVE.md: Simplified flee detection (distance <= 1, no CC_RNG)"""
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
            if distance <= 1:
                return True
    return False


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Handle skip action"""
    # Generate WAIT log for cancelled movement
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    game_state["action_logs"].append({
        "type": "wait",
        "message": f"Unit {unit['id']} ({unit['col']}, {unit['row']}) WAIT",
        "turn": game_state.get("current_turn", 1),
        "phase": "move",
        "unitId": unit["id"],
        "player": unit["player"],
        "col": unit["col"],
        "row": unit["row"],
        "timestamp": "server_time"
    })
    
    movement_clear_preview(game_state)
    return _end_activation(game_state, unit, False)


def _end_activation(game_state: Dict[str, Any], unit: Dict[str, Any], was_adjacent: bool) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: End unit activation"""
    # Apply tracking
    game_state["units_moved"].add(unit["id"])
    if was_adjacent:
        game_state["units_fled"].add(unit["id"])
    
    # Remove from activation pool
    if unit["id"] in game_state["move_activation_pool"]:
        game_state["move_activation_pool"].remove(unit["id"])
        print(f"MOVEMENT POOL REMOVAL: Unit {unit['id']} removed. Remaining: {game_state['move_activation_pool']}")
    
    # Clear active unit
    game_state["active_movement_unit"] = None
    
    # Check phase completion
    if not game_state["move_activation_pool"]:
        return True, movement_phase_end(game_state)
    
    return True, {
        "action": "flee" if was_adjacent else "move",
        "unitId": unit["id"],
        "activation_complete": True
    }


def movement_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_MOVE.md: Clean up and end movement phase"""
    movement_clear_preview(game_state)
    
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("MOVEMENT PHASE COMPLETE")
    
    return {
        "phase_complete": True,
        "next_phase": "shoot",
        "units_processed": len([u for u in game_state["units"] if u["id"] in game_state["units_moved"]])
    }


def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state"""
    for unit in game_state["units"]:
        if unit["id"] == unit_id:
            return unit
    return None