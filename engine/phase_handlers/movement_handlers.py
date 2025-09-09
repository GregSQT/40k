#!/usr/bin/env python3
"""
movement_handlers.py - AI_TURN.md Movement Phase Implementation
Pure stateless functions implementing AI_TURN.md movement specification

References: AI_TURN.md Section 🏃 MOVEMENT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any


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
    AI_TURN.md movement action execution implementation.
    
    Processes semantic movement actions with AI_TURN.md compliance.
    Pure function - modifies game_state in place, no wrapper state.
    """
    action_type = action.get("action")
    
    if action_type == "move":
        dest_col = action.get("destCol")
        dest_row = action.get("destRow")
        
        if dest_col is None or dest_row is None:
            return False, {"error": "missing_destination", "action": action}
        
        return _attempt_movement_to_destination(game_state, unit, dest_col, dest_row, config)
        
    elif action_type == "skip":
        game_state["units_moved"].add(unit["id"])
        return True, {"action": "skip", "unitId": unit["id"]}
        
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "move"}


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
        col >= game_state["board_width"] or 
        row >= game_state["board_height"]):
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