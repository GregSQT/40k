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
    AI_TURN.md: Build activation pool with comprehensive debug logging
    """
    current_player = game_state["current_player"]
    shoot_activation_pool = []
    
    for unit in game_state["units"]:
        if _has_valid_shooting_targets(game_state, unit, current_player):
            shoot_activation_pool.append(unit["id"])
    
    # Update game_state pool
    game_state["shoot_activation_pool"] = shoot_activation_pool
    return shoot_activation_pool

def _ai_select_shooting_target(game_state: Dict[str, Any], unit_id: str, valid_targets: List[str]) -> str:
    """AI target selection using RewardMapper system"""
    if not valid_targets:
        return ""
    
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return valid_targets[0]
    
    try:
        from ai.reward_mapper import RewardMapper
        
        rewards_config = game_state.get("rewards_config")
        if not rewards_config:
            return valid_targets[0]
        
        reward_mapper = RewardMapper(rewards_config)
        
        # Build target list for reward mapper
        all_targets = [_get_unit_by_id(game_state, tid) for tid in valid_targets if _get_unit_by_id(game_state, tid)]
        
        best_target = valid_targets[0]
        best_reward = -999999
        
        for target_id in valid_targets:
            target = _get_unit_by_id(game_state, target_id)
            if not target:
                continue
            
            can_melee_charge = False  # TODO: implement melee charge check
            
            reward = reward_mapper.get_shooting_priority_reward(unit, target, all_targets, can_melee_charge)
            
            if reward > best_reward:
                best_reward = reward
                best_target = target_id
        
        print(f"AI SHOOTING: Unit {unit_id} selected target {best_target} (reward: {best_reward})")
        return best_target
        
    except Exception as e:
        print(f"AI target selection error: {e}")
        return valid_targets[0]

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
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "units_fled" not in game_state:
        raise KeyError("game_state missing required 'units_fled' field")
    if unit["id"] in game_state["units_fled"]:
        return False
        
    # CRITICAL FIX: Add missing adjacency check - units in melee cannot shoot
    # This matches the frontend logic: hasAdjacentEnemyShoot check
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if "CC_RNG" not in unit:
                raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
            if distance <= unit["CC_RNG"]:
                return False
        
    # unit.RNG_NB > 0?
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_NB" not in unit:
        raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
    if unit["RNG_NB"] <= 0:
        return False
    
    # Check for valid targets with detailed debugging
    valid_targets_found = []
    print(f"SHOOT DEBUG: Unit {unit['id']} checking {len([u for u in game_state['units'] if u['player'] != unit['player'] and u['HP_CUR'] > 0])} potential targets")
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            is_valid = _is_valid_shooting_target(game_state, unit, enemy)
            print(f"SHOOT DEBUG: Unit {unit['id']} -> Target {enemy['id']} at ({enemy['col']},{enemy['row']}): {'VALID' if is_valid else 'INVALID'}")
            if is_valid:
                valid_targets_found.append(enemy["id"])
    
    print(f"SHOOT DEBUG: Unit {unit['id']} final valid targets: {valid_targets_found}")
    return len(valid_targets_found) > 0


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine_save.py working validation with proper LoS
    """
    # Range check using proper hex distance
    distance = _calculate_hex_distance(shooter["col"], shooter["row"], target["col"], target["row"])
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_RNG" not in shooter:
        raise KeyError(f"Shooter missing required 'RNG_RNG' field: {shooter}")
    if distance > shooter["RNG_RNG"]:
        print(f"TARGET DEBUG: {shooter['id']} -> {target['id']}: RANGE FAIL (distance={distance}, max={shooter['RNG_RNG']})")
        return False
        
    # Dead target check
    if target["HP_CUR"] <= 0:
        print(f"TARGET DEBUG: {shooter['id']} -> {target['id']}: DEAD TARGET (HP={target['HP_CUR']})")
        return False
        
    # Friendly fire check
    if target["player"] == shooter["player"]:
        print(f"TARGET DEBUG: {shooter['id']} -> {target['id']}: FRIENDLY FIRE")
        return False
    
    # Adjacent check - can't shoot at adjacent enemies (melee range)
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "CC_RNG" not in shooter:
        raise KeyError(f"Shooter missing required 'CC_RNG' field: {shooter}")
    if distance <= shooter["CC_RNG"]:
        print(f"TARGET DEBUG: {shooter['id']} -> {target['id']}: TOO CLOSE (distance={distance}, CC_RNG={shooter['CC_RNG']})")
        return False
        
    # Line of sight check
    has_los = _has_line_of_sight(game_state, shooter, target)
    if not has_los:
        print(f"TARGET DEBUG: {shooter['id']} -> {target['id']}: NO LINE OF SIGHT")
        return False
    
    print(f"TARGET DEBUG: {shooter['id']} -> {target['id']}: VALID TARGET")
    return True

def shooting_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Start unit activation from shoot_activation_pool
    Clear valid_target_pool, clear TOTAL_ACTION_LOG, SHOOT_LEFT = RNG_NB
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return {"error": "unit_not_found", "unitId": unit_id}
    
    # CRITICAL: Clear accumulated action logs for fresh unit activation
    game_state["action_logs"] = []
    
    # AI_TURN.md initialization
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_NB" not in unit:
        raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
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
            enemy["HP_CUR"] > 0):
            
            # Check if target is valid with detailed logging for training debug
            is_valid = _is_valid_shooting_target(game_state, unit, enemy)
            if not is_valid:
                # Add specific failure reason debugging
                distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            else:
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
    # AI_TURN.md COMPLIANCE: Direct field access chain
    elif "board_config" in game_state and "wall_hexes" in game_state["board_config"]:
        wall_hexes_data = game_state["board_config"]["wall_hexes"]
    
    else:
        return True  # No walls = clear line of sight
    
    if not wall_hexes_data:
        print(f"LOS DEBUG: No wall data found - allowing shot")
        return True
    
    # Convert wall_hexes to set for fast lookup
    wall_hexes = set()
    for wall_hex in wall_hexes_data:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) >= 2:
            wall_hexes.add((wall_hex[0], wall_hex[1]))
        else:
            print(f"LOS DEBUG: Invalid wall hex format: {wall_hex}")
    
    try:
        hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
        
        # Check if any hex in path is a wall (excluding start and end)
        blocked = False
        blocking_hex = None
        for i, (col, row) in enumerate(hex_path):
            # Skip start and end hexes
            if i == 0 or i == len(hex_path) - 1:
                continue
            
            if (col, row) in wall_hexes:
                blocked = True
                blocking_hex = (col, row)
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
        game_state["current_player"] = 1
        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "move",
            "current_player": 1,
            # AI_TURN.md COMPLIANCE: Direct field access
            "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
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
            # AI_TURN.md COMPLIANCE: Direct field access
            "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
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
    # AI_TURN.md COMPLIANCE: Direct field access
    if "selected_target_id" in unit and unit["selected_target_id"]:
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
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if arg2 == 1:
        if "episode_steps" not in game_state:
            game_state["episode_steps"] = 0
        game_state["episode_steps"] += 1
    
    # Arg3 tracking
    if arg3 == "SHOOTING":
        if "units_shot" not in game_state:
            game_state["units_shot"] = set()
        game_state["units_shot"].add(unit["id"])
    # arg3 == "PASS" → no tracking update
    
    # Arg4 pool removal
    if arg4 == "SHOOTING":
        # AI_TURN.md COMPLIANCE: Direct field access
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        pool_before = game_state["shoot_activation_pool"].copy()
        if "shoot_activation_pool" in game_state and unit["id"] in game_state["shoot_activation_pool"]:
            game_state["shoot_activation_pool"].remove(unit["id"])
            pool_after = game_state["shoot_activation_pool"]
            print(f"SHOOTING POOL REMOVAL: Unit {unit['id']} removed. Remaining: {pool_after}")
        else:
            current_pool = game_state["shoot_activation_pool"] if "shoot_activation_pool" in game_state else []
            print(f"🔴 END_ACTIVATION DEBUG: Unit {unit['id']} not found in pool {current_pool}")
    
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
    # AI_TURN.md COMPLIANCE: Direct field access
    if "shoot_activation_pool" not in game_state:
        pool_empty = True
    else:
        pool_empty = len(game_state["shoot_activation_pool"]) == 0
    
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

def _shooting_unit_execution_loop(game_state: Dict[str, Any], unit_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Execute While SHOOT_LEFT > 0 loop automatically
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # AI_TURN.md: While SHOOT_LEFT > 0
    if unit["SHOOT_LEFT"] <= 0:
        result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
        return True, result  # Ensure consistent (bool, dict) format
    
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
    
    # CLEAN FLAG DETECTION: Use config parameter like movement handlers
    is_gym_training = config.get("gym_training_mode", False)
    # Fix: Check if unit belongs to AI player (player 1) instead of relying on current_player
    unit = _get_unit_by_id(game_state, unit_id)
    is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 1
    # CRITICAL FIX: Also trigger auto-shooting for AI units in training mode
    is_training_ai = is_gym_training and unit is not None  # Proper boolean evaluation
    
    if (is_gym_training or is_pve_ai or is_training_ai) and valid_targets:
        # AUTO-SHOOT: Select target and execute shooting automatically
        target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
        
        # Execute shooting directly and return result
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    # Only humans get waiting_for_player response
    response = {
        "while_loop_active": True,
        "validTargets": valid_targets,
        "shootLeft": unit["SHOOT_LEFT"],
        "context": "player_action_selection",
        "blinking_units": valid_targets,
        "start_blinking": True,
        "waiting_for_player": True
    }
    return True, response

def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md EXACT: Complete action routing with full phase lifecycle management
    """
    
    # Phase initialization on first call
    # AI_TURN.md COMPLIANCE: Direct field access
    if "_shooting_phase_initialized" not in game_state or not game_state["_shooting_phase_initialized"]:
        shooting_phase_start(game_state)
        game_state["_shooting_phase_initialized"] = True
    
    # Clean execution logging
    if "shoot_activation_pool" not in game_state:
        current_pool = []
    else:
        current_pool = game_state["shoot_activation_pool"]
    
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = "none"  # Allow missing for some action types
    else:
        action_type = action["action"]
        unit_id = action["unitId"]
    if current_pool:
        # Remove units with no shots remaining
        updated_pool = []
        for unit_id in current_pool:
            unit_check = _get_unit_by_id(game_state, unit_id)
            if unit_check and "SHOOT_LEFT" in unit_check:
                shots_left = unit_check["SHOOT_LEFT"]
            else:
                shots_left = 0
            if unit_check and shots_left > 0:
                updated_pool.append(unit_id)
        
        game_state["shoot_activation_pool"] = updated_pool
        current_pool = updated_pool
    
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
    
    # AI_TURN.md COMPLIANCE: Direct field access
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]
    unit_id = unit["id"]
    
    # CRITICAL FIX: Validate unit is current player's unit to prevent self-targeting
    if unit["player"] != game_state["current_player"]:
        return False, {"error": "wrong_player_unit", "unitId": unit_id, "unit_player": unit["player"], "current_player": game_state["current_player"]}
    
    # Handler validates unit eligibility for all actions
    if "shoot_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'shoot_activation_pool' field")
    if unit_id not in game_state["shoot_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # AI_SHOOT.md action routing
    if action_type == "activate_unit":
        print(f"🔍 ACTIVATE_UNIT_ENTRY: unit={unit_id}, phase={game_state.get('phase')}, player={unit['player'] if unit else 'NO_UNIT'}")
        result = shooting_unit_activation_start(game_state, unit_id)
        print(f"🔍 ACTIVATION_START_RESULT: {result}")
        if result.get("success"):
            print(f"🔍 CALLING_EXECUTION_LOOP: unit={unit_id}")
            execution_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            print(f"🔍 EXECUTION_LOOP_RESULT: success={execution_result[0] if isinstance(execution_result, tuple) else 'NOT_TUPLE'}")
            print(f"🔍 EXECUTION_LOOP_DATA: {execution_result[1] if isinstance(execution_result, tuple) and len(execution_result) > 1 else 'NO_DATA'}")
            return execution_result
        print(f"🔍 ACTIVATION_FAILED: unit={unit_id}, returning={result}")
        return True, result
    
    elif action_type == "shoot":
        # Handle gym-style shoot action with optional targetId
        # AI_TURN.md COMPLIANCE: Direct field access
        if "targetId" not in action:
            target_id = None
        else:
            target_id = action["targetId"]
        
        # CRITICAL: Validate unit eligibility
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        if unit_id not in game_state["shoot_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": unit_id}
        
        # Initialize unit for shooting if needed (only if not already activated)
        active_shooting_unit = game_state["active_shooting_unit"] if "active_shooting_unit" in game_state else None
        if "SHOOT_LEFT" not in unit:
            raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
        if "RNG_NB" not in unit:
            raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
        
        if (active_shooting_unit != unit_id and unit["SHOOT_LEFT"] == unit["RNG_NB"]):
            # Only initialize if unit hasn't started shooting yet
            shooting_unit_activation_start(game_state, unit_id)
        
        # Auto-select target if not provided (AI mode)
        if not target_id:
            valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
            print(f"EXECUTE DEBUG: Auto-target selection found {len(valid_targets)} targets: {valid_targets}")
            if not valid_targets:
                # No valid targets - end activation with wait
                print(f"EXECUTE DEBUG: No valid targets found, ending activation with PASS")
                result = _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
                return True, result
            target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
            print(f"EXECUTE DEBUG: AI selected target: {target_id}")
        
        # Execute shooting directly without UI loops
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    elif action_type == "wait" or action_type == "skip":
        # Handle gym wait/skip actions - unit chooses not to shoot
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        current_pool = game_state["shoot_activation_pool"]
        if unit_id in current_pool:
            result = _shooting_activation_end(game_state, unit, "SKIP", 1, "PASS", "SHOOTING")
            post_pool = game_state["shoot_activation_pool"] if "shoot_activation_pool" in game_state else []
            return result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    elif action_type == "left_click":
        target_id = action.get("targetId")
        return shooting_click_handler(game_state, unit_id, action, config)
    
    elif action_type == "right_click":
        return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
    
    elif action_type == "skip":
        return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
    
    elif action_type == "invalid":
        # Handle invalid actions with training penalty - convert to skip behavior
        print(f"SHOOTING: Invalid action penalty for unit {unit_id}")
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        current_pool = game_state["shoot_activation_pool"]
        if unit_id in current_pool:
            # Process as skip but flag for penalty reward
            result = _shooting_activation_end(game_state, unit, "SKIP", 1, "PASS", "SHOOTING")
            result["invalid_action_penalty"] = True
            result["attempted_action"] = action.get("attempted_action", "unknown")
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}


def shooting_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Route click actions to appropriate handlers
    """
    # AI_TURN.md COMPLIANCE: Direct field access
    if "targetId" not in action:
        target_id = None
    else:
        target_id = action["targetId"]
    
    if "clickTarget" not in action:
        click_target = "target"
    else:
        click_target = action["clickTarget"]
    
    if click_target in ["target", "enemy"] and target_id:
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    elif click_target == "friendly_unit" and target_id:
        # Left click on another unit in pool - switch units
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        if target_id in game_state["shoot_activation_pool"]:
            return _handle_unit_switch_with_context(game_state, unit_id, target_id, config)
        return False, {"error": "unit_not_in_pool", "targetId": target_id}
    
    elif click_target == "active_unit":
        # Left click on active unit - no effect or show targets again
        return _shooting_unit_execution_loop(game_state, unit_id, config)
    
    else:
        # Left click elsewhere - continue selection
        return True, {"action": "continue_selection", "context": "elsewhere_clicked"}


def shooting_target_selection_handler(game_state: Dict[str, Any], unit_id: str, target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle target selection and shooting execution
    """    
    unit = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not unit or not target:
        return False, {"error": "unit_or_target_not_found"}
    
    # CRITICAL: Validate unit has shots remaining
    if "SHOOT_LEFT" not in unit:
        raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
    if unit["SHOOT_LEFT"] <= 0:
        return False, {"error": "no_shots_remaining", "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"]}
    
    # Validate target is in valid pool
    valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
    
    if target_id not in valid_targets:
        return False, {"error": "target_not_valid", "targetId": target_id}
    
    # Execute shooting attack
    attack_result = shooting_attack_controller(game_state, unit_id, target_id)
    
    # Update SHOOT_LEFT and continue loop per AI_TURN.md
    unit["SHOOT_LEFT"] -= 1
    
    # Continue execution loop to check for more shots or end activation
    result = _shooting_unit_execution_loop(game_state, unit_id, config)
    return result


def shooting_attack_controller(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: attack_sequence(RNG) implementation with proper logging
    """
    print(f"SHOOTING_ATTACK_CONTROLLER CALLED: Unit {unit_id} targeting {target_id}")
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
    print(f"SHOOTING_ATTACK_CONTROLLER: Creating action log for {unit_id} -> {target_id}")
    
    # Enhanced message format including shooter position per movement phase integration
    enhanced_message = f"Unit {unit_id} ({shooter['col']}, {shooter['row']}) SHOT Unit {target_id} ({target['col']}, {target['row']}) : {attack_result['attack_log'].split(' : ', 1)[1] if ' : ' in attack_result['attack_log'] else attack_result['attack_log']}"
    
    game_state["action_logs"].append({
        "type": "shoot",
        "message": enhanced_message,  # Enhanced with position data
        "turn": game_state["current_turn"] if "current_turn" in game_state else 1,
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
    
    print(f"ACTION LOG CREATED: {enhanced_message}")
    print(f"TOTAL ACTION LOGS IN GAME_STATE: {len(game_state['action_logs'])}")
    
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
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "ARMOR_SAVE" not in target:
        raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
    if "INVUL_SAVE" not in target:
        raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target}")
    armor_save = target["ARMOR_SAVE"]
    invul_save = target["INVUL_SAVE"]
    
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


def _handle_unit_switch_with_context(game_state: Dict[str, Any], current_unit_id: str, new_unit_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
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
            return _shooting_unit_execution_loop(game_state, new_unit_id, config)
    
    return False, {"error": "unit_switch_failed"}


# === HELPER FUNCTIONS (Minimal Implementation) ===

def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate adjacency check"""
    if "CC_RNG" not in unit:
        raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
    cc_range = unit["CC_RNG"]
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= cc_range:
                return True
    return False


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate range check"""
    if "RNG_RNG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
    rng_rng = unit["RNG_RNG"]
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

def _calculate_target_priority_score(unit: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """Calculate target priority score using AI_GAME_OVERVIEW.md logic."""
    
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_DMG" not in target:
        raise KeyError(f"Target missing required 'RNG_DMG' field: {target}")
    if "CC_DMG" not in target:
        raise KeyError(f"Target missing required 'CC_DMG' field: {target}")
    if "RNG_DMG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_DMG' field: {unit}")
    
    threat_level = max(target["RNG_DMG"], target["CC_DMG"])
    can_kill_1_phase = target["HP_CUR"] <= unit["RNG_DMG"]
    
    # Priority 1: High threat that melee can charge but won't kill (score: 1000)
    if threat_level >= 3:  # High threat threshold
        melee_can_charge = _check_if_melee_can_charge(target, game_state)
        if melee_can_charge and target["HP_CUR"] > 2:  # Won't die to melee in 1 phase
            return 1000 + threat_level
    
    # Priority 2: High threat that can be killed in 1 shooting phase (score: 800) 
    if can_kill_1_phase and threat_level >= 3:
        return 800 + threat_level
    
    # Priority 3: High threat, lowest HP that can be killed (score: 600)
    if can_kill_1_phase and threat_level >= 2:
        return 600 + threat_level + (10 - target["HP_CUR"])  # Prefer lower HP
    
    # Default: threat level only
    return threat_level

def _enrich_unit_for_reward_mapper(unit: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich unit data for reward mapper compatibility (matches engine format)."""
    if not unit:
        return {}
    
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "agent_mapping" not in game_state:
        agent_mapping = {}
    else:
        agent_mapping = game_state["agent_mapping"]
    
    unit_id_key = str(unit["id"])
    if unit_id_key in agent_mapping:
        controlled_agent = agent_mapping[unit_id_key]
    elif "unitType" in unit:
        controlled_agent = unit["unitType"]
    elif "unit_type" in unit:
        controlled_agent = unit["unit_type"]
    else:
        controlled_agent = "default"
    
    enriched = unit.copy()
    
    # AI_TURN.md COMPLIANCE: All required fields must be present
    if "CC_DMG" not in unit:
        raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
    if "RNG_DMG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_DMG' field: {unit}")
    if "HP_CUR" not in unit:
        raise KeyError(f"Unit missing required 'HP_CUR' field: {unit}")
    
    enriched.update({
        "controlled_agent": controlled_agent,
        "unitType": controlled_agent,  # Use controlled_agent as unitType
        "name": unit["name"] if "name" in unit else f"Unit_{unit['id']}",
        "cc_dmg": unit["CC_DMG"],
        "rng_dmg": unit["RNG_DMG"],
        "CUR_HP": unit["HP_CUR"]
    })
    
    return enriched

def _check_if_melee_can_charge(target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Check if any friendly melee unit can charge this target."""
    current_player = game_state["current_player"]
    
    for unit in game_state["units"]:
        if (unit["player"] == current_player and 
            unit["HP_CUR"] > 0):
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "CC_DMG" not in unit:
                raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
            if unit["CC_DMG"] > 0:  # Has melee capability
                
                # Estimate charge range (unit move + average 2d6)
                distance = _calculate_hex_distance(unit["col"], unit["row"], target["col"], target["row"])
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge = unit["MOVE"] + 7  # Average 2d6 = 7
            
            if distance <= max_charge:
                return True
    
    return False