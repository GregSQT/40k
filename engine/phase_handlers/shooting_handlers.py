#!/usr/bin/env python3
"""
engine/phase_handlers/shooting_handlers.py - AI_TURN.md EXACT Shooting Phase Implementation
ZERO TOLERANCE architectural compliance with exact specification

References: AI_TURN.md Section 🎯 SHOOTING PHASE LOGIC
Implements: Pool building, two-click confirmation, postpone logic, exact end_activation calls
"""

import random
from typing import Dict, List, Tuple, Set, Optional, Any


def build_shoot_activation_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md EXACT: Pool Building Phase
    For each PLAYER unit → ELIGIBILITY CHECK → Add to shoot_activation_pool
    """
    current_player = game_state["current_player"]
    print(f"🎯 BUILDING SHOOT ACTIVATION POOL:")
    print(f"  - Current player: {current_player}")
    print(f"  - Pool before build: {game_state.get('shoot_activation_pool', [])}")
    shoot_activation_pool = []
    
    for unit in game_state["units"]:
        print(f"  Checking Unit {unit['id']} (Player {unit['player']}):")
        
        # AI_TURN.md eligibility checks in exact order
        
        # unit.HP_CUR > 0?
        print(f"    HP_CUR check: {unit['HP_CUR']} > 0")
        if unit["HP_CUR"] <= 0:
            print(f"    Unit {unit['id']}: EXCLUDED - Dead (HP={unit['HP_CUR']})")
            continue
        
        # unit.player === current_player?
        print(f"    Player check: {unit['player']} === {current_player}")
        if unit["player"] != current_player:
            print(f"    Unit {unit['id']}: EXCLUDED - Wrong player")
            continue
        
        # units_fled.includes(unit.id)?
        units_fled = game_state.get("units_fled", set())
        print(f"    Fled check: {unit['id']} in {units_fled}")
        if unit["id"] in units_fled:
            print(f"    Unit {unit['id']}: EXCLUDED - Fled")
            continue
        
        # Adjacent to enemy unit within CC_RNG?
        print(f"    Adjacency check...")
        if _is_adjacent_to_enemy_within_cc_range(game_state, unit):
            print(f"    Unit {unit['id']}: EXCLUDED - Adjacent to enemy (in fight)")
            continue
        print(f"    Unit {unit['id']}: Not adjacent to enemies")
        
        # unit.RNG_NB > 0?
        rng_nb = unit.get("RNG_NB", 0)
        print(f"    Ranged weapon check: RNG_NB={rng_nb}")
        if rng_nb <= 0:
            print(f"    Unit {unit['id']}: EXCLUDED - No ranged weapon")
            continue
        
        # Has LOS to enemies within RNG_RNG?
        print(f"    Starting LoS validation...")
        has_los = _has_los_to_enemies_within_range(game_state, unit)
        print(f"    Unit {unit['id']}: LoS check result = {has_los}")
        if not has_los:
            print(f"    Unit {unit['id']}: EXCLUDED - No LoS to enemies within range")
            continue
        print(f"    Unit {unit['id']}: LoS validation PASSED")
        
        # ALL conditions met → Add to shoot_activation_pool
        print(f"    Unit {unit['id']}: ALL CHECKS PASSED - Adding to pool")
        shoot_activation_pool.append(unit["id"])
    
    # Update game_state pool
    game_state["shoot_activation_pool"] = shoot_activation_pool
    print(f"  - Pool after build: {shoot_activation_pool}")
    print(f"  - Total eligible units: {len(shoot_activation_pool)}")
    return shoot_activation_pool


def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md EXACT: Check if unit is adjacent to enemy within CC_RNG.
    Uses proper hex distance calculation for accurate adjacency detection.
    """
    cc_range = unit.get("CC_RNG", 1)  # Default CC range if missing
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            # AI_TURN.md: Use proper hex distance calculation
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= cc_range:
                print(f"    Unit {unit['id']}: EXCLUDED - Adjacent to enemy {enemy['id']} (distance={distance}, CC_RNG={cc_range})")
                return True
    return False


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md EXACT: Check if unit has LOS to any enemies within RNG_RNG.
    Enhanced debugging to identify why units without LoS are being included.
    """
    print(f"      LoS check for Unit {unit['id']} at ({unit['col']}, {unit['row']}):")
    
    # Validate required fields first
    rng_rng = unit.get("RNG_RNG", 0)
    print(f"      Unit {unit['id']} RNG_RNG: {rng_rng}")
    if rng_rng <= 0:
        print(f"      Unit {unit['id']}: EXCLUDED - Invalid RNG_RNG={rng_rng}")
        return False
    
    valid_targets = 0
    print(f"      Checking enemies for Unit {unit['id']}:")
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            print(f"        Enemy {enemy['id']} at ({enemy['col']}, {enemy['row']}):")
            
            # Quick range check first using proper hex distance
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            print(f"          Hex distance: {distance}, Max range: {rng_rng}")
            
            if distance > rng_rng:
                print(f"          REJECTED: Out of range")
                continue
            
            # Full target validation with detailed output
            print(f"          Running full target validation...")
            is_valid = _is_valid_shooting_target(game_state, unit, enemy)
            print(f"          Target validation result: {is_valid}")
            
            if is_valid:
                valid_targets += 1
                print(f"          VALID TARGET FOUND: {enemy['id']}")
            else:
                print(f"          Target {enemy['id']} REJECTED by validation")
    
    print(f"      Final result for Unit {unit['id']}: {valid_targets} valid targets")
    los_result = valid_targets > 0
    print(f"      Unit {unit['id']} LoS eligibility: {los_result}")
    return los_result


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    AI_TURN.md EXACT: Target validation with proper hex distance calculations.
    Validates: range + not adjacent + not friendly adjacent + line of sight.
    """
    
    # Validate required fields
    shooter_range = shooter.get("RNG_RNG", 0)
    shooter_cc_range = shooter.get("CC_RNG", 1)
    
    if shooter_range <= 0:
        print(f"          FAILED: Invalid shooter RNG_RNG={shooter_range}")
        return False
    
    # Range check using proper hex distance
    distance = _calculate_hex_distance(shooter["col"], shooter["row"], target["col"], target["row"])
    print(f"          Range check: hex_distance={distance}, RNG_RNG={shooter_range}")
    if distance > shooter_range:
        print(f"          FAILED: Out of range")
        return False
    
    # NOT adjacent to shooter (within CC_RNG) - prevents close combat shooting
    print(f"          Adjacency check: hex_distance={distance}, CC_RNG={shooter_cc_range}")
    if distance <= shooter_cc_range:
        print(f"          FAILED: Too close for shooting (in melee range)")
        return False
    
    # NOT adjacent to any friendly units (prevents friendly fire)
    for friendly in game_state["units"]:
        if (friendly["player"] == shooter["player"] and 
            friendly["HP_CUR"] > 0 and 
            friendly["id"] != shooter["id"]):
            
            friendly_distance = _calculate_hex_distance(friendly["col"], friendly["row"], target["col"], target["row"])
            if friendly_distance <= 1:  # Adjacent to friendly
                print(f"          FAILED: Target adjacent to friendly {friendly['id']} (distance={friendly_distance})")
                return False
    
    # Line of sight check with proper hex pathfinding
    has_los = _has_line_of_sight(game_state, shooter, target)
    print(f"          LoS check: {has_los}")
    return has_los


def _calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """
    Calculate accurate hex distance using cube coordinates.
    Converts offset coordinates to cube coordinates for proper distance calculation.
    """
    # Convert offset coordinates to cube coordinates
    def offset_to_cube(col: int, row: int) -> Tuple[int, int, int]:
        x = col - (row - (row & 1)) // 2
        z = row
        y = -x - z
        return (x, y, z)
    
    # Calculate cube distance
    def cube_distance(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
        return (abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])) // 2
    
    cube1 = offset_to_cube(col1, row1)
    cube2 = offset_to_cube(col2, row2)
    return cube_distance(cube1, cube2)


def _has_line_of_sight(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    AI_TURN.md EXACT: Line of sight check with proper hex pathfinding.
    Fixed to get wall data from multiple possible sources.
    """
    start_col, start_row = shooter["col"], shooter["row"]
    end_col, end_row = target["col"], target["row"]
    
    print(f"            LoS check from ({start_col},{start_row}) to ({end_col},{end_row})")
    
    # Try multiple sources for wall hexes
    wall_hexes_data = []
    
    # Source 1: Direct in game_state
    if "wall_hexes" in game_state:
        wall_hexes_data = game_state["wall_hexes"]
        print(f"            Found wall_hexes in game_state: {wall_hexes_data}")
    
    # Source 2: In board configuration within game_state
    elif "board" in game_state and "wall_hexes" in game_state["board"]:
        wall_hexes_data = game_state["board"]["wall_hexes"]
        print(f"            Found wall_hexes in game_state.board: {wall_hexes_data}")
    
    # Source 3: Check if walls exist in board config (fallback pattern)
    elif hasattr(game_state, 'get') and game_state.get("board_config", {}).get("wall_hexes"):
        wall_hexes_data = game_state["board_config"]["wall_hexes"]
        print(f"            Found wall_hexes in board_config: {wall_hexes_data}")
    
    else:
        print(f"            No wall data found in any location - assuming clear LoS")
        print(f"            Available keys in game_state: {list(game_state.keys()) if isinstance(game_state, dict) else 'not dict'}")
        return True  # No walls = clear line of sight
    
    if not wall_hexes_data:
        print(f"            Wall data empty - clear LoS")
        return True
    
    # Convert wall_hexes to set for fast lookup
    wall_hexes = set()
    for wall_hex in wall_hexes_data:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) >= 2:
            wall_hexes.add((wall_hex[0], wall_hex[1]))
        else:
            print(f"            Invalid wall hex format: {wall_hex}")
    
    print(f"            Processed wall hexes: {wall_hexes}")
    
    try:
        hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
        print(f"            Hex path: {hex_path}")
        
        # Check if any hex in path is a wall (excluding start and end)
        blocked = False
        for i, (col, row) in enumerate(hex_path):
            # Skip start and end hexes
            if i == 0 or i == len(hex_path) - 1:
                continue
            
            print(f"            Checking path hex ({col},{row}) against walls")
            if (col, row) in wall_hexes:
                print(f"            LoS BLOCKED by wall at ({col}, {row})")
                blocked = True
                break
        
        if not blocked:
            print(f"            LoS CLEAR - no wall interference")
        
        return not blocked
        
    except Exception as e:
        print(f"            LoS calculation error: {e}")
        # Default to blocked if calculation fails
        return False
    
    if not game_state["wall_hexes"]:
        return True
    
    hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
    
    # Check if any hex in path is a wall (excluding start and end)
    for col, row in hex_path[1:-1]:
        if (col, row) in game_state["wall_hexes"]:
            return False
    
    return True


def _get_accurate_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
    """Accurate hex line using cube coordinates."""
    start_cube = _offset_to_cube(start_col, start_row)
    end_cube = _offset_to_cube(end_col, end_row)
    
    distance = max(abs(start_cube.x - end_cube.x), abs(start_cube.y - end_cube.y), abs(start_cube.z - end_cube.z))
    path = []
    
    for i in range(distance + 1):
        t = i / distance if distance > 0 else 0
        
        cube_x = start_cube.x + t * (end_cube.x - start_cube.x)
        cube_y = start_cube.y + t * (end_cube.y - start_cube.y)
        cube_z = start_cube.z + t * (end_cube.z - start_cube.z)
        
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
    x = col
    z = row - (col - (col & 1)) // 2
    y = -x - z
    return CubeCoordinate(x, y, z)


def _cube_to_offset(cube: CubeCoordinate) -> Tuple[int, int]:
    col = cube.x
    row = cube.z + (cube.x - (cube.x & 1)) // 2
    return col, row


def _cube_round(x: float, y: float, z: float) -> CubeCoordinate:
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


def start_unit_activation(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Start unit activation from shoot_activation_pool
    Clear valid_target_pool, clear TOTAL_ACTION_LOG, SHOOT_LEFT = RNG_NB
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return {"error": "unit_not_found", "unitId": unit_id}
    
    # AI_TURN.md initialization
    unit["valid_target_pool"] = []
    unit["TOTAL_ATTACK_LOG"] = ""
    unit["SHOOT_LEFT"] = unit["RNG_NB"]
    unit["selected_target_id"] = None  # For two-click confirmation
    
    # Mark unit as currently active
    game_state["active_shooting_unit"] = unit_id
    
    return {"success": True, "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"]}


def build_valid_target_pool(game_state: Dict[str, Any], unit_id: str) -> List[str]:
    """
    Build valid_target_pool and always send blinking data to frontend.
    All enemies within range AND in Line of Sight AND having HP_CUR > 0
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []
    
    valid_target_pool = []
    
    print(f"🔥 BUILDING TARGET POOL for unit {unit_id}")
    
    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and 
            enemy["HP_CUR"] > 0 and
            _is_valid_shooting_target(game_state, unit, enemy)):
            valid_target_pool.append(enemy["id"])
    
    # Update unit's target pool
    unit["valid_target_pool"] = valid_target_pool
    
    return valid_target_pool


def handle_target_selection(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Handle left click on target (first click = blinking, second click = execute)
    """
    unit = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not unit or not target:
        return {"error": "unit_or_target_not_found"}
    
    # Validate target is in valid_target_pool
    if target_id not in unit["valid_target_pool"]:
        return {"error": "target_not_in_valid_pool", "targetId": target_id}
    
    current_selected = unit.get("selected_target_id")
    
    if current_selected == target_id:
        # Second click on same target - execute shot
        return execute_shot(game_state, unit_id, target_id)
    else:
        # First click or different target - start blinking animation
        unit["selected_target_id"] = target_id
        response = {
            "action": "target_selected", 
            "targetId": target_id,
            "startBlinking": True
        }
        print(f"🔥 BLINKING RESPONSE: {response}")
        return response


def execute_shot(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Execute attack_sequence(RNG) with proper tracking
    """
    unit = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not unit or not target:
        return {"error": "unit_or_target_not_found"}
    
    # Execute attack_sequence(RNG)
    shot_result = _execute_attack_sequence_rng(unit, target)
    
    # AI_TURN.md tracking updates - Document 6 simplified
    unit["SHOOT_LEFT"] -= 1
    unit["TOTAL_ATTACK_LOG"] += f"Shot at {target.get('name', target['id'])}; "
    # Document 6: No selected_target_id to clear
    
    # Remove dead targets from valid_target_pool
    if target["HP_CUR"] <= 0:
        if target_id in unit["valid_target_pool"]:
            unit["valid_target_pool"].remove(target_id)
    
    return {
        "action": "shot_executed",
        "result": shot_result,
        "shootLeft": unit["SHOOT_LEFT"],
        "totalAttackLog": unit["TOTAL_ATTACK_LOG"]
    }


def _execute_attack_sequence_rng(shooter: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """AI_TURN.md attack_sequence(RNG) implementation."""
    
    # Hit roll
    hit_roll = random.randint(1, 6)
    hit_target = 7 - shooter["RNG_ATK"]
    
    if hit_roll < hit_target:
        return {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "result": "MISSED",
            "damage": 0
        }
    
    # Wound roll
    wound_roll = random.randint(1, 6)
    wound_target = _calculate_wound_target(shooter["RNG_STR"], target["T"])
    
    if wound_roll < wound_target:
        return {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "result": "FAILED",
            "damage": 0
        }
    
    # Save roll
    save_roll = random.randint(1, 6)
    save_target = target["ARMOR_SAVE"] - shooter["RNG_AP"]
    
    # Check invulnerable save
    if target["INVUL_SAVE"] < save_target:
        save_target = target["INVUL_SAVE"]
    
    if save_roll >= save_target:
        return {
            "hit_roll": hit_roll,
            "wound_roll": wound_roll,
            "save_roll": save_roll,
            "save_target": save_target,
            "result": "SAVED",
            "damage": 0
        }
    
    # Damage dealt
    damage = shooter["RNG_DMG"]
    target["HP_CUR"] = max(0, target["HP_CUR"] - damage)
    
    return {
        "hit_roll": hit_roll,
        "wound_roll": wound_roll,
        "save_roll": save_roll,
        "save_target": save_target,
        "result": "DAMAGE",
        "damage": damage,
        "targetHP": target["HP_CUR"],
        "targetDied": target["HP_CUR"] <= 0
    }


def _calculate_wound_target(strength: int, toughness: int) -> int:
    """Calculate wound target per W40K rules."""
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


def handle_unit_switch_attempt(game_state: Dict[str, Any], current_unit_id: str, new_unit_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Handle left click on another unit in shoot_activation_pool
    Check SHOOT_LEFT = RNG_NB for postpone logic
    """
    current_unit = _get_unit_by_id(game_state, current_unit_id)
    if not current_unit:
        return {"error": "current_unit_not_found"}
    
    # SHOOT_LEFT = RNG_NB?
    if current_unit["SHOOT_LEFT"] == current_unit["RNG_NB"]:
        # YES → Postpone the shooting phase for this unit
        _postpone_unit_activation(game_state, current_unit_id)
        return start_unit_activation(game_state, new_unit_id)
    else:
        # NO → The unit must end its activation when started
        return {"error": "cannot_switch_after_shooting", "shootLeft": current_unit["SHOOT_LEFT"]}


def _postpone_unit_activation(game_state: Dict[str, Any], unit_id: str) -> None:
    """Postpone unit activation - return to pool without marking as shot."""
    unit = _get_unit_by_id(game_state, unit_id)
    if unit:
        # Clean up activation state but don't mark as shot
        unit.pop("valid_target_pool", None)
        unit.pop("TOTAL_ATTACK_LOG", None)
        unit.pop("selected_target_id", None)
        unit["SHOOT_LEFT"] = 0  # Reset for next activation


def handle_right_click_active_unit(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Right click on active_unit logic
    SHOOT_LEFT = RNG_NB → WAIT, else → ACTION
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return {"error": "unit_not_found"}
    
    if unit["SHOOT_LEFT"] == unit["RNG_NB"]:
        # YES → Cancel activation → end_activation(WAIT, 1, PASS, SHOOTING)
        return _end_activation(game_state, unit, "WAIT", 1, "PASS", "SHOOTING")
    else:
        # NO → stop shooting on purpose → end_activation(ACTION, 1, SHOOTING, SHOOTING)
        return _end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")


def check_while_loop_condition(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Check While SHOOT_LEFT > 0 loop continuation
    Build valid_target_pool and check conditions
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return {"error": "unit_not_found"}
    
    # Check SHOOT_LEFT > 0
    if unit["SHOOT_LEFT"] <= 0:
        return _end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
    
    # Build valid_target_pool
    valid_targets = build_valid_target_pool(game_state, unit_id)
    
    # valid_target_pool NOT empty?
    if len(valid_targets) == 0:
        # SHOOT_LEFT = RNG_NB?
        if unit["SHOOT_LEFT"] == unit["RNG_NB"]:
            # YES → no target available at activation → end_activation(PASS, 1, PASS, SHOOTING)
            return _end_activation(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
        else:
            # NO → shot the last target available → end_activation(ACTION, 1, SHOOTING, SHOOTING)
            return _end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
    
    # Valid targets available - continue to PLAYER_ACTION_SELECTION
    return {
        "continue_shooting": True,
        "validTargets": valid_targets,
        "shootLeft": unit["SHOOT_LEFT"]
    }


def _end_activation(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: end_activation procedure with exact arguments
    end_activation(Arg1, Arg2, Arg3, Arg4, Arg5)
    """
    
    # Arg1 logging
    if arg1 == "ACTION":
        print(f"Unit {unit['id']} action logged: {unit.get('TOTAL_ATTACK_LOG', '')}")
    elif arg1 == "WAIT":
        print(f"Unit {unit['id']} wait action logged")
    # arg1 == "PASS" or "NO" → no logging
    
    # Arg2 step increment
    if arg2 == 1:
        game_state["episode_steps"] = game_state.get("episode_steps", 0) + 1
    
    # Arg3 tracking
    if arg3 == "SHOOTING":
        game_state["units_shot"].add(unit["id"])
    # arg3 == "PASS" → no tracking update
    
    # Arg4 pool removal
    if arg4 == "SHOOTING":
        if unit["id"] in game_state["shoot_activation_pool"]:
            game_state["shoot_activation_pool"].remove(unit["id"])
    
    # Clean up unit activation state
    unit.pop("valid_target_pool", None)
    unit.pop("TOTAL_ATTACK_LOG", None)
    unit.pop("selected_target_id", None)
    unit["SHOOT_LEFT"] = 0
    
    # Clear active unit
    game_state.pop("active_shooting_unit", None)
    
    return {
        "activation_ended": True,
        "endType": arg1,
        "unitId": unit["id"]
    }


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
    current_player = game_state["current_player"]
    eligible_units = []
    
    for unit in game_state["units"]:
        # AI_TURN.md eligibility checks in exact order
        
        # unit.HP_CUR > 0?
        if unit["HP_CUR"] <= 0:
            print(f"    Unit {unit['id']}: EXCLUDED - Dead (HP={unit['HP_CUR']})")
            continue
        
        # unit.player === current_player?
        if unit["player"] != current_player:
            print(f"    Unit {unit['id']}: EXCLUDED - Wrong player ({unit['player']} != {current_player})")
            continue
        
        # units_fled.includes(unit.id)?
        if unit["id"] in game_state["units_fled"]:
            print(f"    Unit {unit['id']}: EXCLUDED - Fled")
            continue
        
        # unit.RNG_NB > 0?
        if unit.get("RNG_NB", 0) <= 0:
            print(f"    Unit {unit['id']}: EXCLUDED - No ranged weapon (RNG_NB={unit.get('RNG_NB', 0)})")
            continue
        
        # ALL conditions met - Add to eligible list
        print(f"    Unit {unit['id']}: ELIGIBLE - Adding to pool")
        eligible_units.append(unit["id"])
    
    print(f"  Final eligible units: {eligible_units}")
    return eligible_units


def _get_shooting_context(game_state: Dict[str, Any], unit: Dict[str, Any]) -> str:
    """Determine current shooting context for nested behavior."""
    if unit.get("selected_target_id"):
        return "target_selected"
    else:
        return "no_target_selected"

def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Context-aware action routing with nested state machine
    Implements exact specification with automatic While loop and context awareness
    """
    action_type = action.get("action")
    unit_id = unit["id"]
    
    # Get current context for nested behavior
    current_context = _get_shooting_context(game_state, unit)
    
    if action_type == "activate_unit":
        # Start unit activation from pool
        result = start_unit_activation(game_state, unit_id)
        if result.get("success"):
            # AI_TURN.md: Automatically enter While SHOOT_LEFT > 0 loop
            return _execute_while_loop(game_state, unit_id)
        return True, result
    
    elif action_type == "left_click":
        # AI_TURN.md: Context-aware left click handling
        target_id = action.get("targetId")
        click_target = action.get("clickTarget")  # "enemy", "friendly", "active_unit", "elsewhere"
        
        print(f"🔥 LEFT CLICK ROUTING: context={current_context}, target_id={target_id}, click_target={click_target}")
        
        if current_context == "target_selected":
            # Nested under "Left click on a target" - handle sub-actions
            print(f"🔥 TAKING NESTED PATH")
            return _handle_nested_left_click(game_state, unit, target_id, click_target)
        else:
            # Top-level PLAYER_ACTION_SELECTION
            print(f"🔥 TAKING TOP-LEVEL PATH")
            return _handle_top_level_left_click(game_state, unit, target_id, click_target)
    
    elif action_type == "right_click":
        # AI_TURN.md: Context-aware right click (works in both nested and top-level)
        click_target = action.get("clickTarget")
        
        if click_target == "active_unit":
            return _handle_right_click_active_unit_contextual(game_state, unit, current_context)
        else:
            # Right click anywhere else - return to PLAYER_ACTION_SELECTION
            return {"action": "continue_selection", "context": "anywhere_else_right_click"}
    
    elif action_type == "skip":
        # Manual skip - force end activation
        result = _end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
        return True, {"action": "skip", "unitId": unit["id"], "totalAttackLog": unit.get("TOTAL_ATTACK_LOG", "")}
        
    else:
        return False, {"error": "invalid_action_for_shooting_phase", "action": action_type}

def _execute_while_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Execute While SHOOT_LEFT > 0 loop automatically
    This replaces manual check_loop calls with automatic execution
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # AI_TURN.md: While SHOOT_LEFT > 0
    if unit["SHOOT_LEFT"] <= 0:
        return _end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
    
    # AI_TURN.md: Build valid_target_pool
    valid_targets = build_valid_target_pool(game_state, unit_id)
    
    # AI_TURN.md: valid_target_pool NOT empty?
    if len(valid_targets) == 0:
        # SHOOT_LEFT = RNG_NB?
        if unit["SHOOT_LEFT"] == unit["RNG_NB"]:
            # No targets at activation
            result = _end_activation(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
            return True, result
        else:
            # Shot last target available
            result = _end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
            return True, result
    
    # AI_TURN.md: SHOOTING PHASE ACTIONS AVAILABLE → PLAYER_ACTION_SELECTION
    response = {
        "while_loop_active": True,
        "validTargets": valid_targets,
        "shootLeft": unit["SHOOT_LEFT"],
        "context": "player_action_selection",
        "blinking_units": valid_targets,
        "start_blinking": True
    }
    return True, response


def _handle_nested_left_click(game_state: Dict[str, Any], unit: Dict[str, Any], target_id: str, click_target: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Handle left clicks when target is already selected
    Nested under "Left click on a target in valid_target_pool"
    """
    unit_id = unit["id"]
    current_selected = unit.get("selected_target_id")
    
    if click_target == "enemy" and target_id:
        if target_id == current_selected:
            # AI_TURN.md: Left click a second time on the same selected_target
            result = execute_shot(game_state, unit_id, target_id)
            if result.get("action") == "shot_executed":
                # After shot, automatically continue While loop
                return _execute_while_loop(game_state, unit_id)
            return True, result
        
        elif target_id in unit.get("valid_target_pool", []):
            # AI_TURN.md: Left click on another target in valid_target_pool → Change target
            unit["selected_target_id"] = target_id
            return True, {
                "action": "target_changed",
                "newTargetId": target_id,
                "startBlinking": True,
                "goto": "PLAYER_ACTION_SELECTION"
            }
    
    elif click_target == "friendly" and target_id:
        # AI_TURN.md: Left click on another unit in shoot_activation_pool
        if target_id in game_state.get("shoot_activation_pool", []):
            return _handle_unit_switch_with_context(game_state, unit_id, target_id, "nested")
    
    elif click_target == "active_unit":
        # AI_TURN.md: Left click on the active_unit → GO TO STEP : PLAYER_ACTION_SELECTION
        return True, {"action": "continue_selection", "context": "active_unit_clicked"}
    
    else:
        # AI_TURN.md: Left click anywhere else → GO TO STEP : PLAYER_ACTION_SELECTION
        return True, {"action": "continue_selection", "context": "anywhere_else_clicked"}


def _handle_top_level_left_click(game_state: Dict[str, Any], unit: Dict[str, Any], target_id: str, click_target: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Handle top-level left clicks in PLAYER_ACTION_SELECTION
    Direct top-level options (duplicates of nested options)
    """
    unit_id = unit["id"]
    
    if click_target == "enemy" and target_id:
        # Start target selection process
        if target_id in unit.get("valid_target_pool", []):
            unit["selected_target_id"] = target_id
            return True, {
                "action": "target_selected",
                "targetId": target_id,
                "startBlinking": True,
                "context": "target_selection_started"
            }
    
    elif click_target == "friendly" and target_id:
        # AI_TURN.md: Left click on another unit in shoot_activation_pool (top-level duplicate)
        if target_id in game_state.get("shoot_activation_pool", []):
            return _handle_unit_switch_with_context(game_state, unit_id, target_id, "top_level")
    
    elif click_target == "active_unit":
        # AI_TURN.md: Left click on the active_unit → Build target pool and show blinking
        valid_targets = build_valid_target_pool(game_state, unit_id)
        return True, {
            "while_loop_active": True,
            "validTargets": valid_targets,
            "shootLeft": unit["SHOOT_LEFT"],
            "context": "player_action_selection",
            "blinking_units": valid_targets,
            "start_blinking": True
        }
    
    else:
        # AI_TURN.md: Left click anywhere else → GO TO STEP : PLAYER_ACTION_SELECTION
        return True, {"action": "continue_selection", "context": "anywhere_else_clicked"}


def _handle_unit_switch_with_context(game_state: Dict[str, Any], current_unit_id: str, new_unit_id: str, context: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Handle unit switching with postpone logic
    Works for both nested and top-level contexts
    """
    current_unit = _get_unit_by_id(game_state, current_unit_id)
    if not current_unit:
        return False, {"error": "current_unit_not_found"}
    
    # AI_TURN.md: SHOOT_LEFT = RNG_NB?
    if current_unit["SHOOT_LEFT"] == current_unit["RNG_NB"]:
        # YES → Postpone the shooting phase for this unit
        _postpone_unit_activation(game_state, current_unit_id)
        
        # Start new unit activation
        result = start_unit_activation(game_state, new_unit_id)
        if result.get("success"):
            # Automatically enter While loop for new unit
            return _execute_while_loop(game_state, new_unit_id)
        return True, result
    else:
        # NO → The unit must end its activation when started
        if context == "nested":
            goto_step = "PLAYER_ACTION_SELECTION"
        else:
            goto_step = "PLAYER_ACTION_SELECTION"
        
        return True, {
            "error": "cannot_switch_after_shooting", 
            "shootLeft": current_unit["SHOOT_LEFT"],
            "goto": goto_step,
            "context": context
        }


def _handle_right_click_active_unit_contextual(game_state: Dict[str, Any], unit: Dict[str, Any], context: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Right click on active_unit with context awareness
    Same logic but different GOTO destinations
    """
    unit_id = unit["id"]
    
    if unit["SHOOT_LEFT"] == unit["RNG_NB"]:
        # YES → Cancel activation → end_activation(WAIT, 1, PASS, SHOOTING)
        result = _end_activation(game_state, unit, "WAIT", 1, "PASS", "SHOOTING")
        result["goto"] = "UNIT_ACTIVABLE_CHECK"
        result["context"] = context
        return True, result
    else:
        # NO → stop shooting on purpose → end_activation(ACTION, 1, SHOOTING, SHOOTING)
        result = _end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
        result["goto"] = "UNIT_ACTIVABLE_CHECK"
        result["context"] = context
        return True, result


def auto_execute_shot_sequence(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Execute shot and automatically continue While loop
    Replaces manual shot execution with automatic loop continuation
    """
    # Execute the shot
    result = execute_shot(game_state, unit_id, target_id)
    
    if result.get("action") == "shot_executed":
        # AI_TURN.md: After shot, automatically check While loop continuation
        return _execute_while_loop(game_state, unit_id)
    
    return True, result