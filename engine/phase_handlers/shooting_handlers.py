#!/usr/bin/env python3
"""
shooting_handlers.py - AI_TURN.md Shooting Phase Implementation
Pure stateless functions implementing AI_TURN.md shooting specification

References: AI_TURN.md Section 🎯 SHOOTING PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

import random
from typing import Dict, List, Tuple, Set, Optional, Any


def _has_valid_shooting_targets(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Check if unit has valid shooting targets per AI_TURN.md restrictions."""
    valid_targets = 0
    
    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and 
            enemy["HP_CUR"] > 0):
            
            if _is_valid_shooting_target(game_state, unit, enemy):
                valid_targets += 1
    
    # Debug: Log units with no valid targets
    if valid_targets == 0:
        print(f"DEBUG: Unit {unit['id']} has no valid shooting targets")
    
    return valid_targets > 0


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Validate shooting target per AI_TURN.md restrictions."""
    
    # Range check
    distance = max(abs(shooter["col"] - target["col"]), abs(shooter["row"] - target["row"]))
    if distance > shooter["RNG_RNG"]:
        return False
    
    # Combat exclusion: target NOT adjacent to shooter
    if distance <= shooter["CC_RNG"]:
        return False
    
    # Friendly fire prevention: target NOT adjacent to any friendly units
    for friendly in game_state["units"]:
        if (friendly["player"] == shooter["player"] and 
            friendly["HP_CUR"] > 0 and 
            friendly["id"] != shooter["id"]):
            
            friendly_distance = max(abs(friendly["col"] - target["col"]), 
                                  abs(friendly["row"] - target["row"]))
            if friendly_distance <= 1:  # Adjacent to friendly
                return False
    
    # Line of sight check
    return _has_line_of_sight(game_state, shooter, target)


def _has_line_of_sight(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Check line of sight between shooter and target."""
    start_col, start_row = shooter["col"], shooter["row"]
    end_col, end_row = target["col"], target["row"]
    
    # Direct line check - if no walls exist, always have LOS
    if not game_state["wall_hexes"]:
        return True
    
    # Use more accurate hex line algorithm
    hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
    
    # Check if any hex in path is a wall (excluding start and end)
    for col, row in hex_path[1:-1]:  # Skip start and end positions
        if (col, row) in game_state["wall_hexes"]:
            return False
    
    return True


def _get_accurate_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
    """Get accurate hex line using proper hex coordinate system."""
    # Convert to cube coordinates for accurate hex pathfinding
    start_cube = _offset_to_cube(start_col, start_row)
    end_cube = _offset_to_cube(end_col, end_row)
    
    # Lerp through cube coordinates
    distance = max(abs(start_cube.x - end_cube.x), abs(start_cube.y - end_cube.y), abs(start_cube.z - end_cube.z))
    path = []
    
    for i in range(distance + 1):
        t = i / distance if distance > 0 else 0
        
        # Linear interpolation in cube space
        cube_x = start_cube.x + t * (end_cube.x - start_cube.x)
        cube_y = start_cube.y + t * (end_cube.y - start_cube.y)
        cube_z = start_cube.z + t * (end_cube.z - start_cube.z)
        
        # Round to nearest hex and convert back to offset
        rounded_cube = _cube_round(cube_x, cube_y, cube_z)
        offset_col, offset_row = _cube_to_offset(rounded_cube)
        path.append((offset_col, offset_row))
    
    return path


class CubeCoordinate:
    def __init__(self, x: int, y: int, z: int):
        self.x = x
        self.y = y
        self.z = z


def _offset_to_cube(col: int, row: int) -> CubeCoordinate:
    """Convert offset coordinates to cube coordinates."""
    x = col
    z = row - (col - (col & 1)) // 2
    y = -x - z
    return CubeCoordinate(x, y, z)


def _cube_to_offset(cube: CubeCoordinate) -> Tuple[int, int]:
    """Convert cube coordinates to offset coordinates."""
    col = cube.x
    row = cube.z + (cube.x - (cube.x & 1)) // 2
    return col, row


def _cube_round(x: float, y: float, z: float) -> CubeCoordinate:
    """Round fractional cube coordinates to nearest hex."""
    rx = round(x)
    ry = round(y)
    rz = round(z)
    
    x_diff = abs(rx - x)
    y_diff = abs(ry - y)
    z_diff = abs(rz - z)
    
    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry
    
    return CubeCoordinate(rx, ry, rz)


def _get_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
    """Get hex line between two points (simplified implementation)."""
    path = []
    
    # Simple linear interpolation for now
    steps = max(abs(end_col - start_col), abs(end_row - start_row))
    if steps == 0:
        return [(start_col, start_row)]
    
    for i in range(steps + 1):
        t = i / steps
        col = round(start_col + t * (end_col - start_col))
        row = round(start_row + t * (end_row - start_row))
        path.append((col, row))
    
    return path


def _attempt_shooting(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Attempt shooting with AI_TURN.md damage resolution."""
    
    # Validate target
    if not _is_valid_shooting_target(game_state, shooter, target):
        return False, {"error": "invalid_target", "targetId": target["id"]}
    
    # Execute shots (RNG_NB shots per activation)
    total_damage = 0
    shots_fired = shooter["RNG_NB"]
    
    for shot in range(shots_fired):
        # Hit roll
        hit_roll = random.randint(1, 6)
        hit_target = 7 - shooter["RNG_ATK"]  # Convert attack stat to target number
        
        if hit_roll >= hit_target:
            # Wound roll
            wound_roll = random.randint(1, 6)
            wound_target = _calculate_wound_target(shooter["RNG_STR"], target["T"])
            
            if wound_roll >= wound_target:
                # Save roll
                save_roll = random.randint(1, 6)
                save_target = target["ARMOR_SAVE"] - shooter["RNG_AP"]
                
                # Check invulnerable save
                if target["INVUL_SAVE"] < save_target:
                    save_target = target["INVUL_SAVE"]
                
                if save_roll < save_target:
                    # Damage dealt
                    damage = shooter["RNG_DMG"]
                    total_damage += damage
                    target["HP_CUR"] -= damage
                    
                    # Check if target dies
                    if target["HP_CUR"] <= 0:
                        target["HP_CUR"] = 0
                        break  # Stop shooting at dead target
    
    # Apply tracking
    game_state["units_shot"].add(shooter["id"])
    
    return True, {
        "action": "shoot",
        "shooterId": shooter["id"],
        "targetId": target["id"],
        "shotsFired": shots_fired,
        "totalDamage": total_damage,
        "targetHP": target["HP_CUR"]
    }


def _calculate_wound_target(strength: int, toughness: int) -> int:
    """Calculate wound target number per W40K rules."""
    if strength >= toughness * 2:
        return 2
    elif strength > toughness:
        return 3
    elif strength == toughness:
        return 4
    elif strength * 2 <= toughness:
        return 6
    else:
        return 5


def _is_adjacent_to_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Check if unit is adjacent to enemy (AI_TURN.md eligibility check)."""
    cc_range = unit["CC_RNG"]
    
    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0):
            distance = max(abs(unit["col"] - enemy["col"]), 
                          abs(unit["row"] - enemy["row"]))
            if distance <= cc_range:
                return True
    return False


def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state."""
    for unit in game_state["units"]:
        if unit["id"] == unit_id:
            return unit
    return None


def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md shooting eligibility decision tree implementation.
    
    Returns list of unit IDs eligible for shooting activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]
    
    for unit in game_state["units"]:
        # AI_TURN.md eligibility: alive + current_player + not fled + not adjacent + has weapon + has ammo + has targets
        if (unit["HP_CUR"] > 0 and 
            unit["player"] == current_player and
            unit["id"] not in game_state["units_fled"] and
            not _is_adjacent_to_enemy(game_state, unit) and
            unit["RNG_NB"] > 0 and
            unit.get("SHOOT_LEFT", 0) > 0 and
            _has_valid_shooting_targets(game_state, unit)):
            
            eligible_units.append(unit["id"])
    
    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md shooting action execution implementation.
    
    Processes semantic shooting actions with AI_TURN.md compliance.
    Pure function - modifies game_state in place, no wrapper state.
    """
    action_type = action.get("action")
    
    # AI_TURN.md: Initialize SHOOT_LEFT = RNG_NB when unit first activated
    if "first_activation" not in unit or unit["first_activation"]:
        unit["SHOOT_LEFT"] = unit["RNG_NB"]
        unit["first_activation"] = False
    
    if action_type == "shoot":
        target_id = action.get("targetId")
        if not target_id:
            return False, {"error": "missing_target", "action": action}
        
        target = _get_unit_by_id(game_state, str(target_id))
        if not target:
            return False, {"error": "target_not_found", "targetId": target_id}
        
        return _attempt_shooting(game_state, unit, target)
        
    elif action_type == "skip":
        game_state["units_shot"].add(unit["id"])
        return True, {"action": "skip", "unitId": unit["id"]}
        
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}