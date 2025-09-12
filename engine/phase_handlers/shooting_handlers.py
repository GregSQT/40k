#!/usr/bin/env python3
"""
engine/phase_handlers/shooting_handlers.py - AI_Shooting_Phase.md Basic Implementation
Only pool building functionality - foundation for complete handler autonomy
"""

from typing import Dict, List, Tuple, Set, Optional, Any


def shooting_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_Shooting_Phase.md EXACT: Initialize shooting phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "shoot"
    
    # Build activation pool
    eligible_units = shooting_build_activation_pool(game_state)
    
    # Console log for web browser visibility
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append(f"SHOOT POOL BUILT: Player {game_state['current_player']} → Units: {eligible_units}")
    
    return {
        "phase_initialized": True,
        "eligible_units": len(eligible_units),
        "phase_complete": len(eligible_units) == 0
    }


def shooting_build_activation_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    EXACT COPY from w40k_engine_save.py working validation logic
    """
    current_player = game_state["current_player"]
    shoot_activation_pool = []
    
    for unit in game_state["units"]:
        # Check if unit has valid shooting targets per AI_TURN.md restrictions
        if not _has_valid_shooting_targets(game_state, unit, current_player):
            continue
            
        # ALL conditions met → Add to shoot_activation_pool
        shoot_activation_pool.append(unit["id"])
    
    # Update game_state pool
    game_state["shoot_activation_pool"] = shoot_activation_pool
    return shoot_activation_pool


def _has_valid_shooting_targets(game_state: Dict[str, Any], unit: Dict[str, Any], current_player: int) -> bool:
    """
    EXACT COPY from w40k_engine_save.py _has_valid_shooting_targets logic
    """
    # unit.HP_CUR > 0?
    if unit["HP_CUR"] <= 0:
        return False
        
    # unit.player === current_player?
    if unit["player"] != current_player:
        return False
        
    # units_fled.includes(unit.id)?
    if unit["id"] in game_state.get("units_fled", set()):
        return False
        
    # unit.RNG_NB > 0?
    if unit.get("RNG_NB", 0) <= 0:
        return False
    
    # Check for valid targets
    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and 
            enemy["HP_CUR"] > 0 and
            _is_valid_shooting_target(game_state, unit, enemy)):
            return True
    return False


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine_save.py working validation with proper LoS
    """
    # Range check using proper hex distance
    distance = _calculate_hex_distance(shooter["col"], shooter["row"], target["col"], target["row"])
    if distance > shooter.get("RNG_RNG", 0):
        return False
        
    # Dead target check
    if target["HP_CUR"] <= 0:
        return False
        
    # Friendly fire check
    if target["player"] == shooter["player"]:
        return False
    
    # Adjacent check - can't shoot at adjacent enemies (melee range)
    if distance <= shooter.get("CC_RNG", 1):
        return False
        
    # Line of sight check
    return _has_line_of_sight(game_state, shooter, target)

def shooting_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
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


def shooting_build_valid_target_pool(game_state: Dict[str, Any], unit_id: str) -> List[str]:
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

def shooting_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_Shooting_Phase.md EXACT: Clean up and end shooting phase
    """
    # Final cleanup
    game_state["shoot_activation_pool"] = []
    
    # Console log
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("SHOOTING PHASE COMPLETE")
    
    return {
        "phase_complete": True,
        "next_phase": "charge",
        "units_processed": len(game_state.get("units_shot", set()))
    }

def _get_shooting_context(game_state: Dict[str, Any], unit: Dict[str, Any]) -> str:
    """Determine current shooting context for nested behavior."""
    if unit.get("selected_target_id"):
        return "target_selected"
    else:
        return "no_target_selected"

def _shooting_activation_end(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: shooting_activation_end procedure with exact arguments
    shooting_activation_end(Arg1, Arg2, Arg3, Arg4, Arg5)
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

def _shooting_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Execute While SHOOT_LEFT > 0 loop automatically
    This replaces manual check_loop calls with automatic execution
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # AI_TURN.md: While SHOOT_LEFT > 0
    if unit["SHOOT_LEFT"] <= 0:
        return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
    
    # AI_TURN.md: Build valid_target_pool
    valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
    
    # AI_TURN.md: valid_target_pool NOT empty?
    if len(valid_targets) == 0:
        # SHOOT_LEFT = RNG_NB?
        if unit["SHOOT_LEFT"] == unit["RNG_NB"]:
            # No targets at activation
            result = _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
            return True, result
        else:
            # Shot last target available
            result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
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

def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md EXACT: Handler manages ALL validation and logic
    """
    
    
    action_type = action.get("action")
    unit_id = unit["id"]
    
    # Get current context for nested behavior
    current_context = _get_shooting_context(game_state, unit)
    
    if action_type == "activate_unit":
        # Start unit activation from pool
        result = shooting_unit_activation_start(game_state, unit_id)
        if result.get("success"):
            # AI_TURN.md: Automatically enter While SHOOT_LEFT > 0 loop
            return _shooting_unit_execution_loop(game_state, unit_id)
        return True, result
    

    
    # Handler validates action format
    if "unitId" not in action:
        return False, {"error": "semantic_action_required", "action": action}
    
    # Handler gets unit from game_state
    unit_id = str(action["unitId"])
    active_unit = None
    for u in game_state["units"]:
        if u["id"] == unit_id:
            active_unit = u
            break
    
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id}
    
    # Handler validates unit eligibility
    if active_unit["id"] not in game_state.get("shoot_activation_pool", []):
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # Check phase completion
    if not game_state.get("shoot_activation_pool"):
        result = shooting_phase_end(game_state)
        return True, result
    
    # Handler removes unit from pool when action succeeds
    if active_unit["id"] in game_state["shoot_activation_pool"]:
        game_state["shoot_activation_pool"].remove(active_unit["id"])
    
    # Check if pool now empty after removal
    if not game_state["shoot_activation_pool"]:
        result = shooting_phase_end(game_state)
        return True, result
    
    # Placeholder for future action implementation
    return True, {"action": "placeholder_success", "unitId": unit_id}


# === HELPER FUNCTIONS (Minimal Implementation) ===

def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate adjacency check"""
    cc_range = unit.get("CC_RNG", 1)
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= cc_range:
                return True
    return False


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate range check"""
    rng_rng = unit.get("RNG_RNG", 0)
    if rng_rng <= 0:
        return False
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= rng_rng:
                return True  # Simplified - assume clear LoS for now
    
    return False

def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state."""
    for unit in game_state["units"]:
        if unit["id"] == unit_id:
            return unit
    return None

def _calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Calculate accurate hex distance using cube coordinates."""
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


# Legacy compatibility
def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """Legacy compatibility - use shooting_build_activation_pool instead"""
    pool = shooting_build_activation_pool(game_state)
    return pool