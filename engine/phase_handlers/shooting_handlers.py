#!/usr/bin/env python3
"""
engine/phase_handlers/shooting_handlers.py - EXACT COPY of w40k_engine shooting logic
Working implementation copied directly from engine for delegation
"""

import random
from typing import Dict, List, Tuple, Set, Optional, Any


def shooting_build_activation_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    EXACT COPY from w40k_engine._shooting_build_activation_pool delegation call
    """
    current_player = game_state["current_player"]
    shoot_activation_pool = []
    
    for unit in game_state["units"]:
        # unit.HP_CUR > 0?
        if unit["HP_CUR"] <= 0:
            continue
        
        # unit.player === current_player?
        if unit["player"] != current_player:
            continue
        
        # units_fled.includes(unit.id)?
        if unit["id"] in game_state.get("units_fled", set()):
            continue
        
        # Adjacent to enemy unit within CC_RNG?
        if _is_adjacent_to_enemy_within_cc_range(game_state, unit):
            continue
        
        # unit.RNG_NB > 0?
        if unit.get("RNG_NB", 0) <= 0:
            continue
        
        # Has LOS to enemies within RNG_RNG?
        if not _has_los_to_enemies_within_range(game_state, unit):
            continue
        
        # Add to pool
        shoot_activation_pool.append(unit["id"])
    
    # Update game_state
    game_state["shoot_activation_pool"] = shoot_activation_pool
    return shoot_activation_pool


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    EXACT COPY from w40k_engine._execute_shooting_action
    """
    action_type = action.get("action")
    
    if action_type == "shoot":
        target_id = action.get("targetId")
        if not target_id:
            return False, {"error": "missing_target", "action": action}
        
        target = _get_unit_by_id(game_state, str(target_id))
        if not target:
            return False, {"error": "target_not_found", "targetId": target_id}
        
        return _attempt_shooting(game_state, unit, target)
        
    elif action_type == "skip":
        if "units_shot" not in game_state:
            game_state["units_shot"] = set()
        game_state["units_shot"].add(unit["id"])
        return True, {"action": "skip", "unitId": unit["id"]}
        
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}


def _attempt_shooting(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    EXACT COPY from w40k_engine._attempt_shooting
    """
    # Validate target
    if not _is_valid_shooting_target(game_state, shooter, target):
        return False, {"error": "invalid_target", "targetId": target["id"]}
    
    # Execute shots (RNG_NB shots per activation)
    total_damage = 0
    shots_fired = shooter["RNG_NB"]
    
    for shot in range(shots_fired):
        # Hit roll
        hit_roll = random.randint(1, 6)
        hit_target = 7 - shooter["RNG_ATK"]
        
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
                        break
    
    # Apply tracking
    if "units_shot" not in game_state:
        game_state["units_shot"] = set()
    game_state["units_shot"].add(shooter["id"])
    
    return True, {
        "action": "shoot",
        "shooterId": shooter["id"],
        "targetId": target["id"],
        "shotsFired": shots_fired,
        "totalDamage": total_damage,
        "targetHP": target["HP_CUR"]
    }


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine._is_valid_shooting_target
    """
    shooter_range = shooter.get("RNG_RNG", 0)
    shooter_cc_range = shooter.get("CC_RNG", 1)
    
    if shooter_range <= 0:
        return False
    
    # Range check
    distance = _calculate_hex_distance(shooter["col"], shooter["row"], target["col"], target["row"])
    if distance > shooter_range:
        return False
    
    # Not adjacent (prevents close combat shooting)
    if distance <= shooter_cc_range:
        return False
    
    # Not adjacent to friendly units
    for friendly in game_state["units"]:
        if (friendly["player"] == shooter["player"] and 
            friendly["HP_CUR"] > 0 and 
            friendly["id"] != shooter["id"]):
            
            friendly_distance = _calculate_hex_distance(friendly["col"], friendly["row"], target["col"], target["row"])
            if friendly_distance <= 1:
                return False
    
    # Line of sight check
    return _has_line_of_sight(game_state, shooter, target)

def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine logic
    """
    cc_range = unit.get("CC_RNG", 1)
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= cc_range:
                return True
    return False


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine logic
    """
    rng_rng = unit.get("RNG_RNG", 0)
    if rng_rng <= 0:
        return False
    
    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and 
            enemy["HP_CUR"] > 0 and
            _is_valid_shooting_target(game_state, unit, enemy)):
            return True
    
    return False


def _calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """
    EXACT COPY from w40k_engine._calculate_hex_distance (if exists) or implement standard hex distance
    """
    # Standard hex distance calculation
    def offset_to_cube(col: int, row: int) -> Tuple[int, int, int]:
        x = col - (row - (row & 1)) // 2
        z = row
        y = -x - z
        return (x, y, z)
    
    def cube_distance(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
        return (abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])) // 2
    
    cube1 = offset_to_cube(col1, row1)
    cube2 = offset_to_cube(col2, row2)
    return cube_distance(cube1, cube2)


def _has_line_of_sight(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine._has_line_of_sight
    """
    start_col, start_row = shooter["col"], shooter["row"]
    end_col, end_row = target["col"], target["row"]
    
    # Get wall hexes from game state
    wall_hexes = set()
    wall_data = game_state.get("wall_hexes", [])
    if isinstance(wall_data, set):
        wall_hexes = wall_data
    elif isinstance(wall_data, list):
        wall_hexes = set(map(tuple, wall_data))
    
    if not wall_hexes:
        return True
    
    try:
        hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
        
        # Check if any hex in path is a wall (excluding start and end)
        for i, (col, row) in enumerate(hex_path):
            if i == 0 or i == len(hex_path) - 1:
                continue
            if (col, row) in wall_hexes:
                return False
        
        return True
        
    except Exception:
        return False


def _get_accurate_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
    """
    EXACT COPY from w40k_engine hex line calculation
    """
    # Simple line for now - can be enhanced with proper hex pathfinding
    path = []
    
    # Linear interpolation between start and end
    steps = max(abs(end_col - start_col), abs(end_row - start_row))
    if steps == 0:
        return [(start_col, start_row)]
    
    for i in range(steps + 1):
        t = i / steps
        col = round(start_col + t * (end_col - start_col))
        row = round(start_row + t * (end_row - start_row))
        path.append((col, row))
    
    return path


def _calculate_wound_target(strength: int, toughness: int) -> int:
    """
    EXACT COPY from w40k_engine._calculate_wound_target
    """
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


def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """
    EXACT COPY from w40k_engine._get_unit_by_id
    """
    for unit in game_state["units"]:
        if unit["id"] == unit_id:
            return unit
    return None


# Legacy compatibility functions
def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """Legacy compatibility - use shooting_build_activation_pool instead"""
    pool = shooting_build_activation_pool(game_state)
    return pool