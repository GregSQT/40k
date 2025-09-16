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
    
    # AI_TURN.md COMPLIANCE: Reset SHOOT_LEFT for all units at phase start
    current_player = game_state["current_player"]
    for unit in game_state["units"]:
        if unit["player"] == current_player and unit["HP_CUR"] > 0:
            unit["SHOOT_LEFT"] = unit["RNG_NB"]
            # print(f"RESET SHOOT_LEFT: Unit {unit['id']} -> {unit['SHOOT_LEFT']}")
    
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
    # print(f"SHOOTING POOL CREATED: Player {current_player} -> {shoot_activation_pool}")
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
    
    # CRITICAL: Capture unit's current location for shooting phase tracking
    unit["activation_position"] = {"col": unit["col"], "row": unit["row"]}
    
    # Mark unit as currently active
    game_state["active_shooting_unit"] = unit_id
    
    return {"success": True, "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"], 
            "position": {"col": unit["col"], "row": unit["row"]}}


def shooting_build_valid_target_pool(game_state: Dict[str, Any], unit_id: str) -> List[str]:
    """
    Build valid_target_pool and always send blinking data to frontend.
    All enemies within range AND in Line of Sight AND having HP_CUR > 0
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []
    
    valid_target_pool = []
    
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
    
    # Try multiple sources for wall hexes
    wall_hexes_data = []
    
    # Source 1: Direct in game_state
    if "wall_hexes" in game_state:
        wall_hexes_data = game_state["wall_hexes"]
    
    # Source 2: In board configuration within game_state
    elif "board" in game_state and "wall_hexes" in game_state["board"]:
        wall_hexes_data = game_state["board"]["wall_hexes"]
    
    # Source 3: Check if walls exist in board config (fallback pattern)
    elif hasattr(game_state, 'get') and game_state.get("board_config", {}).get("wall_hexes"):
        wall_hexes_data = game_state["board_config"]["wall_hexes"]
    
    else:
        return True  # No walls = clear line of sight
    
    if not wall_hexes_data:
        return True
    
    # Convert wall_hexes to set for fast lookup
    wall_hexes = set()
    for wall_hex in wall_hexes_data:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) >= 2:
            wall_hexes.add((wall_hex[0], wall_hex[1]))
        else:
            print(f"            Invalid wall hex format: {wall_hex}")
    
    try:
        hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
        
        # Check if any hex in path is a wall (excluding start and end)
        blocked = False
        for i, (col, row) in enumerate(hex_path):
            # Skip start and end hexes
            if i == 0 or i == len(hex_path) - 1:
                continue
            
            if (col, row) in wall_hexes:
                blocked = True
                break
        
        return not blocked
        
    except Exception as e:
        print(f"            LoS calculation error: {e}")
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

def _shooting_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete shooting phase with player progression and turn management
    """
    # Final cleanup
    game_state["shoot_activation_pool"] = []
    
    # Console log
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("SHOOTING PHASE COMPLETE")
    
    # AI_TURN.md: Player progression logic
    if game_state["current_player"] == 0:
        # Player 0 complete → Player 1 movement phase
        print(f"SHOOTING COMPLETE: Player 0 -> Player 1 movement phase")
        game_state["current_player"] = 1
        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "move",
            "current_player": 1,
            "units_processed": len(game_state.get("units_shot", set())),
            # CRITICAL: Add missing frontend cleanup signals
            "clear_blinking_gentle": True,
            "reset_mode": "select",
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }
    elif game_state["current_player"] == 1:
        # Player 1 complete → Increment turn, Player 0 movement phase
        game_state["turn"] += 1
        game_state["current_player"] = 0
        print(f"SHOOTING COMPLETE: Player 1 -> Turn {game_state['turn']}, Player 0 movement phase")
        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "move",
            "current_player": 0,
            "new_turn": game_state["turn"],
            "units_processed": len(game_state.get("units_shot", set())),
            # CRITICAL: Add missing frontend cleanup signals
            "clear_blinking_gentle": True,
            "reset_mode": "select", 
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }

def shooting_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy function - redirects to new complete function"""
    return _shooting_phase_complete(game_state)

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
    
    # Arg2 step increment
    if arg2 == 1:
        game_state["episode_steps"] = game_state.get("episode_steps", 0) + 1
    
    # Arg3 tracking
    if arg3 == "SHOOTING":
        if "units_shot" not in game_state:
            game_state["units_shot"] = set()
        game_state["units_shot"].add(unit["id"])
    # arg3 == "PASS" → no tracking update
    
    # Arg4 pool removal
    if arg4 == "SHOOTING":
        pool_before = game_state.get("shoot_activation_pool", []).copy()
        print(f"🔍 END_ACTIVATION DEBUG: Pool before removal: {pool_before}")
        print(f"🔍 END_ACTIVATION DEBUG: Removing unit {unit['id']}, args: {arg1}, {arg2}, {arg3}, {arg4}")
        if "shoot_activation_pool" in game_state and unit["id"] in game_state["shoot_activation_pool"]:
            game_state["shoot_activation_pool"].remove(unit["id"])
            pool_after = game_state["shoot_activation_pool"]
            print(f"🔍 END_ACTIVATION DEBUG: Pool after removal: {pool_after}")
            print(f"SHOOTING POOL REMOVAL: Unit {unit['id']} removed. Remaining: {pool_after}")
        else:
            print(f"🔍 END_ACTIVATION DEBUG: Unit {unit['id']} not found in pool {game_state.get('shoot_activation_pool', [])}")
    
    # Clean up unit activation state including position tracking
    if "valid_target_pool" in unit:
        del unit["valid_target_pool"]
    if "TOTAL_ATTACK_LOG" in unit:
        del unit["TOTAL_ATTACK_LOG"]
    if "selected_target_id" in unit:
        del unit["selected_target_id"]
    if "activation_position" in unit:
        del unit["activation_position"]  # Clear position tracking
    unit["SHOOT_LEFT"] = 0
    
    # Clear active unit
    if "active_shooting_unit" in game_state:
        del game_state["active_shooting_unit"]
    
    # Check if shooting pool is now empty after removing this unit
    pool_empty = len(game_state.get("shoot_activation_pool", [])) == 0
    
    response = {
        "activation_ended": True,
        "endType": arg1,
        "unitId": unit["id"],
        "clear_blinking_gentle": True,
        "reset_mode": "select",
        "clear_selected_unit": True
    }
    
    # Signal phase completion if pool is empty - delegate to proper phase end function
    if pool_empty:
        # Don't just set a flag - call the complete phase transition function
        return _shooting_phase_complete(game_state)
    
    return response

def _shooting_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Execute While SHOOT_LEFT > 0 loop automatically
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # AI_TURN.md: While SHOOT_LEFT > 0
    print(f"DEBUG EXECUTION LOOP: Unit {unit_id} SHOOT_LEFT={unit['SHOOT_LEFT']}, RNG_NB={unit.get('RNG_NB', 'MISSING')}")
    if unit["SHOOT_LEFT"] <= 0:
        print(f"DEBUG: Unit {unit_id} has no shots left - ending activation")
        result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
        return True, result  # Ensure consistent (bool, dict) format
    
    # AI_TURN.md: Build valid_target_pool
    valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
    print(f"DEBUG: Unit {unit_id} found {len(valid_targets)} valid targets: {valid_targets}")
    
    # AI_TURN.md: valid_target_pool NOT empty?
    if len(valid_targets) == 0:
        print(f"DEBUG: Unit {unit_id} has no valid targets - ending activation (SHOOT_LEFT={unit['SHOOT_LEFT']}, RNG_NB={unit['RNG_NB']})")
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
    AI_SHOOT.md EXACT: Complete action routing with full phase lifecycle management
    """
    
    # Phase initialization on first call
    if not game_state.get("_shooting_phase_initialized"):
        print(f"SHOOTING PHASE INIT: Player {game_state['current_player']} - initializing shooting phase")
        shooting_phase_start(game_state)
        game_state["_shooting_phase_initialized"] = True
    
    # Debug logging
    current_pool = game_state.get("shoot_activation_pool", [])
    print(f"SHOOTING PHASE DEBUG: Pool {current_pool}, Action received: {action}")
    
    # CRITICAL: Remove depleted units from activation pool
    print(f"DEBUG POOL CLEANUP: Initial pool: {current_pool}")
    if current_pool:
        # Remove units with no shots remaining
        updated_pool = []
        for unit_id in current_pool:
            unit_check = _get_unit_by_id(game_state, unit_id)
            shots_left = unit_check.get("SHOOT_LEFT", 0) if unit_check else 0
            print(f"DEBUG POOL CLEANUP: Unit {unit_id} has SHOOT_LEFT={shots_left}")
            if unit_check and shots_left > 0:
                updated_pool.append(unit_id)
            else:
                print(f"DEBUG POOL CLEANUP: Removing unit {unit_id} (SHOOT_LEFT={shots_left})")
        
        game_state["shoot_activation_pool"] = updated_pool
        current_pool = updated_pool
        print(f"SHOOTING POOL CLEANUP: Removed depleted units. Remaining: {current_pool}")
    
    # Check if shooting phase should complete after cleanup
    if not current_pool:
        game_state["_shooting_phase_initialized"] = False
        print(f"DEBUG: Pool empty after cleanup - ending shooting phase")
        return True, _shooting_phase_complete(game_state)
    
    # Extract unit from action if not provided (engine passes None now)
    if unit is None:
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        unit_id = str(action["unitId"])
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found", "unitId": unit_id}
    
    action_type = action.get("action")
    unit_id = unit["id"]
    
    # CRITICAL FIX: Validate unit is current player's unit to prevent self-targeting
    if unit["player"] != game_state["current_player"]:
        return False, {"error": "wrong_player_unit", "unitId": unit_id, "unit_player": unit["player"], "current_player": game_state["current_player"]}
    
    # Handler validates unit eligibility for all actions
    if unit_id not in game_state.get("shoot_activation_pool", []):
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # AI_SHOOT.md action routing
    if action_type == "activate_unit":
        result = shooting_unit_activation_start(game_state, unit_id)
        if result.get("success"):
            return _shooting_unit_execution_loop(game_state, unit_id)
        return True, result
    
    elif action_type == "shoot":
        # Handle gym-style shoot action with targetId
        target_id = action.get("targetId")
        if not target_id:
            return False, {"error": "missing_target", "action": action}
        
        # CRITICAL: Activate unit first if not already active
        if unit_id not in game_state.get("shoot_activation_pool", []):
            return False, {"error": "unit_not_eligible", "unitId": unit_id}
        
        # Initialize unit for shooting if needed (only if not already activated)
        if (game_state.get("active_shooting_unit") != unit_id and 
            unit.get("SHOOT_LEFT", 0) == unit.get("RNG_NB", 0)):
            # Only initialize if unit hasn't started shooting yet
            shooting_unit_activation_start(game_state, unit_id)
        
        # Execute shooting directly without UI loops
        return shooting_target_selection_handler(game_state, unit_id, str(target_id))
    
    elif action_type == "wait" or action_type == "skip":
        # Handle gym wait/skip actions - unit chooses not to shoot
        current_pool = game_state.get("shoot_activation_pool", [])
        print(f"🔍 SHOOT DEBUG: Unit {unit_id} wait action, pool before: {current_pool}")
        if unit_id in current_pool:
            result = _shooting_activation_end(game_state, unit, "SKIP", 1, "PASS", "SHOOTING")
            post_pool = game_state.get("shoot_activation_pool", [])
            print(f"🔍 SHOOT DEBUG: After end_activation, pool: {post_pool}")
            return result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    elif action_type == "left_click":
        target_id = action.get("targetId")
        return shooting_click_handler(game_state, unit_id, action)
    
    elif action_type == "right_click":
        return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
    
    elif action_type == "skip":
        return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}


def shooting_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Route click actions to appropriate handlers
    """
    target_id = action.get("targetId")
    click_target = action.get("clickTarget", "target")
    
    if click_target in ["target", "enemy"] and target_id:
        return shooting_target_selection_handler(game_state, unit_id, target_id)
    
    elif click_target == "friendly_unit" and target_id:
        # Left click on another unit in pool - switch units
        if target_id in game_state.get("shoot_activation_pool", []):
            return _handle_unit_switch_with_context(game_state, unit_id, target_id)
        return False, {"error": "unit_not_in_pool", "targetId": target_id}
    
    elif click_target == "active_unit":
        # Left click on active unit - no effect or show targets again
        return _shooting_unit_execution_loop(game_state, unit_id)
    
    else:
        # Left click elsewhere - continue selection
        return True, {"action": "continue_selection", "context": "elsewhere_clicked"}


def shooting_target_selection_handler(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle target selection and shooting execution
    """
    
    unit = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not unit or not target:
        return False, {"error": "unit_or_target_not_found"}
    
    print(f"DEBUG SHOOT: Unit {unit_id} SHOOT_LEFT before: {unit['SHOOT_LEFT']}")
    
    # CRITICAL: Validate unit has shots remaining
    if unit.get("SHOOT_LEFT", 0) <= 0:
        print(f"DEBUG SHOOT: Unit {unit_id} has no shots remaining - rejecting shoot action")
        return False, {"error": "no_shots_remaining", "unitId": unit_id, "shootLeft": unit.get("SHOOT_LEFT", 0)}
    
    # Validate target is in valid pool
    valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
    
    if target_id not in valid_targets:
        return False, {"error": "target_not_valid", "targetId": target_id}
    
    # Execute shooting attack
    attack_result = shooting_attack_controller(game_state, unit_id, target_id)
    print(f"DEBUG SHOOT: Attack executed, result: {attack_result.get('action', 'unknown')}")
    
    # Update SHOOT_LEFT and continue loop per AI_TURN.md
    unit["SHOOT_LEFT"] -= 1
    print(f"DEBUG SHOOT: Unit {unit_id} SHOOT_LEFT after: {unit['SHOOT_LEFT']}")
    
    # Continue execution loop to check for more shots or end activation
    result = _shooting_unit_execution_loop(game_state, unit_id)
    print(f"DEBUG SHOOT: Execution loop returned: {result}")
    return result


def shooting_attack_controller(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: attack_sequence(RNG) implementation with proper logging
    """
    shooter = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not shooter or not target:
        return {"error": "unit_or_target_not_found"}
    
    # Execute single attack_sequence(RNG) per AI_TURN.md
    attack_result = _attack_sequence_rng(shooter, target)
    
    # Apply damage immediately per AI_TURN.md
    if attack_result["damage"] > 0:
        target["HP_CUR"] = max(0, target["HP_CUR"] - attack_result["damage"])
        # Check if target died
        if target["HP_CUR"] <= 0:
            attack_result["target_died"] = True
    
    # CRITICAL: Store detailed log for frontend display with location data
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # Enhanced message format including shooter position per movement phase integration
    enhanced_message = f"Unit {unit_id} ({shooter['col']}, {shooter['row']}) SHOT Unit {target_id} ({target['col']}, {target['row']}) : {attack_result['attack_log'].split(' : ', 1)[1] if ' : ' in attack_result['attack_log'] else attack_result['attack_log']}"
    
    game_state["action_logs"].append({
        "type": "shoot",
        "message": enhanced_message,  # Enhanced with position data
        "turn": game_state.get("current_turn", 1),
        "phase": "shoot",
        "shooterId": unit_id,
        "targetId": target_id,
        "player": shooter["player"],
        "shooterCol": shooter["col"],  # Shooter current position
        "shooterRow": shooter["row"],
        "targetCol": target["col"],    # Target current position  
        "targetRow": target["row"],
        "damage": attack_result["damage"],
        "target_died": attack_result.get("target_died", False),
        "hitRoll": attack_result.get("hit_roll"),
        "woundRoll": attack_result.get("wound_roll"),
        "saveRoll": attack_result.get("save_roll"),
        "saveTarget": attack_result.get("save_target"),
        "timestamp": "server_time"
    })
    
    return {
        "action": "shot_executed",
        "shooterId": unit_id,
        "targetId": target_id,
        "attack_result": attack_result,
        "target_hp_remaining": target["HP_CUR"],
        "target_died": target["HP_CUR"] <= 0
    }


def _attack_sequence_rng(attacker: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: attack_sequence(RNG) with proper <OFF> replacement
    """
    import random
    
    attacker_id = attacker["id"] 
    target_id = target["id"]
    
    # Hit roll → hit_roll >= attacker.RNG_ATK
    hit_roll = random.randint(1, 6)
    hit_target = attacker["RNG_ATK"]
    hit_success = hit_roll >= hit_target
    
    if not hit_success:
        # MISS case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) : MISSED !"
        return {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "hit_success": False,
            "damage": 0,
            "attack_log": attack_log
        }
    
    # HIT → Continue to wound roll
    wound_roll = random.randint(1, 6)
    wound_target = _calculate_wound_target(attacker["RNG_STR"], target["T"])
    wound_success = wound_roll >= wound_target
    
    if not wound_success:
        # FAIL case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) : FAILED !"
        return {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "wound_success": False,
            "damage": 0,
            "attack_log": attack_log
        }
    
    # WOUND → Continue to save roll
    save_roll = random.randint(1, 6)
    save_target = _calculate_save_target(target, attacker["RNG_AP"])
    save_success = save_roll >= save_target
    
    if save_success:
        # SAVE case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) : SAVED !"
        return {
            "hit_roll": hit_roll,
            "wound_roll": wound_roll,
            "save_roll": save_roll,
            "save_target": save_target,
            "save_success": True,
            "damage": 0,
            "attack_log": attack_log
        }
    
    # FAIL → Continue to damage
    damage_dealt = attacker["RNG_DMG"]
    new_hp = max(0, target["HP_CUR"] - damage_dealt)
    
    if new_hp <= 0:
        # Target dies
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} delt : Unit {target_id} DIED !"
    else:
        # Target survives
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} DAMAGE DELT !"
    
    return {
        "hit_roll": hit_roll,
        "wound_roll": wound_roll,
        "save_roll": save_roll,
        "save_target": save_target,
        "damage": damage_dealt,
        "attack_log": attack_log
    }


def _calculate_save_target(target: Dict[str, Any], ap: int) -> int:
    """Calculate save target with AP modifier and invulnerable save"""
    armor_save = target.get("ARMOR_SAVE")
    invul_save = target.get("INVUL_SAVE", 0)
    
    # Apply AP to armor save (AP makes saves worse, so add to target number)
    modified_armor_save = armor_save + ap
    
    # Handle invulnerable saves: 0 means no invul save, use 7 (impossible)
    effective_invul = invul_save if invul_save > 0 else 7
    
    # Use best available save (lower target number is better)
    best_save = min(modified_armor_save, effective_invul)
    
    # Cap impossible saves at 7, minimum save is 2+
    return max(2, min(best_save, 6))


def _calculate_wound_target(strength: int, toughness: int) -> int:
    """EXACT COPY from 40k_OLD w40k_engine.py wound calculation"""
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


def _handle_unit_switch_with_context(game_state: Dict[str, Any], current_unit_id: str, new_unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle switching between units in activation pool
    """
    # End current unit activation
    current_unit = _get_unit_by_id(game_state, current_unit_id)
    if current_unit:
        _shooting_activation_end(game_state, current_unit, "WAIT", 1, "PASS", "SHOOTING")
    
    # Start new unit activation
    new_unit = _get_unit_by_id(game_state, new_unit_id)
    if new_unit:
        result = shooting_unit_activation_start(game_state, new_unit_id)
        if result.get("success"):
            return _shooting_unit_execution_loop(game_state, new_unit_id)
    
    return False, {"error": "unit_switch_failed"}


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
    """Calculate hex distance using consistent cube coordinates."""
    # Use same calculation across all handlers
    def offset_to_cube(col: int, row: int) -> Tuple[int, int, int]:
        x = col
        z = row - (col - (col & 1)) // 2
        y = -x - z
        return (x, y, z)
    
    def cube_distance(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
    
    cube1 = offset_to_cube(col1, row1)
    cube2 = offset_to_cube(col2, row2)
    return cube_distance(cube1, cube2)


# Legacy compatibility
def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """Legacy compatibility - use shooting_build_activation_pool instead"""
    pool = shooting_build_activation_pool(game_state)
    return pool