#!/usr/bin/env python3
"""
generic_handlers.py - AI_TURN.md Generic Functions
Pure stateless functions implementing AI_TURN.md specification exactly

References: AI_TURN.md END OF ACTIVATION PROCEDURE
ZERO TOLERANCE for deviations from specification
"""

from typing import Dict, List, Tuple, Set, Optional, Any


def end_activation(game_state: Dict[str, Any], unit: Dict[str, Any], 
                  arg1: str, arg2: int, arg3: str, arg4: str, arg5: int) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: END OF ACTIVATION PROCEDURE
    end_activation (Arg1, Arg2, Arg3, Arg4, Arg5)
    
    Args:
        arg1: ACTION/WAIT/NO - logging behavior
        arg2: 1/0 - step increment
        arg3: MOVE/FLED/SHOOTING/CHARGE/FIGHT - tracking sets
        arg4: MOVE/FLED/SHOOTING/CHARGE/FIGHT - pool removal
        arg5: 1/0 - error logging
    """
    unit_id = unit["id"]
    response = {
        "activation_ended": True,
        "unitId": unit_id,
        "endType": arg1
    }
    
    # ├── Arg1 = ?
    # │   ├── CASE Arg1 = ACTION → log the action
    # │   ├── CASE Arg1 = WAIT → log the wait action
    # │   └── CASE Arg1 = NO → do not log the action
    if arg1 == "ACTION":
        # Log the action (action already logged by handlers)
        response["action_logged"] = True
    elif arg1 == "WAIT":
        # Log the wait action
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        game_state["action_logs"].append({
            "type": "wait",
            "message": f"Unit {unit_id} ({unit['col']}, {unit['row']}) WAIT",
            "turn": game_state.get("current_turn", 1),
            "phase": game_state["phase"],
            "unitId": unit_id,
            "col": unit["col"],
            "row": unit["row"],
            "timestamp": "server_time"
        })
        response["wait_logged"] = True
    elif arg1 == "NO":
        # Do not log the action
        response["no_logging"] = True
    
    # ├── Arg2 = 1 ?
    # │   ├── YES → +1 step
    # │   └── NO → No step increase
    if arg2 == 1:
        game_state["episode_steps"] = game_state.get("episode_steps", 0) + 1
        response["step_incremented"] = True
    
    # ├── Arg3 =
    # │ ├── CASE Arg3 = MOVE → Mark as units_moved
    # │ ├── CASE Arg3 = FLED → Mark as units_moved AND Mark as units_fled
    # │ ├── CASE Arg3 = SHOOTING → Mark as units_shot
    # │ ├── CASE Arg3 = CHARGE → Mark as units_charged
    # │ └── CASE Arg3 = FIGHT → Mark as units_fought
    if arg3 == "MOVE":
        if "units_moved" not in game_state:
            game_state["units_moved"] = set()
        game_state["units_moved"].add(unit_id)
    elif arg3 == "FLED":
        if "units_moved" not in game_state:
            game_state["units_moved"] = set()
        if "units_fled" not in game_state:
            game_state["units_fled"] = set()
        game_state["units_moved"].add(unit_id)
        game_state["units_fled"].add(unit_id)
    elif arg3 == "SHOOTING":
        if "units_shot" not in game_state:
            game_state["units_shot"] = set()
        game_state["units_shot"].add(unit_id)
    elif arg3 == "CHARGE":
        if "units_charged" not in game_state:
            game_state["units_charged"] = set()
        game_state["units_charged"].add(unit_id)
    elif arg3 == "FIGHT":
        if "units_fought" not in game_state:
            game_state["units_fought"] = set()
        game_state["units_fought"].add(unit_id)
    
    # ├── Arg4 = ?
    # │ ├── CASE Arg4 = MOVE → Unit removed from move_activation_pool
    # │ ├── CASE Arg4 = FLED → Unit removed from move_activation_pool
    # │ ├── CASE Arg4 = SHOOTING → Unit removed from shoot_activation_pool
    # │ ├── CASE Arg4 = CHARGE → Unit removed from charge_activation_pool
    # │ └── CASE Arg4 = FIGHT → Unit removed from fight_activation_pool
    if arg4 in ["MOVE", "FLED"]:
        if "move_activation_pool" in game_state and unit_id in game_state["move_activation_pool"]:
            game_state["move_activation_pool"].remove(unit_id)
            response["removed_from_move_pool"] = True
    elif arg4 == "SHOOTING":
        if "shoot_activation_pool" in game_state and unit_id in game_state["shoot_activation_pool"]:
            game_state["shoot_activation_pool"].remove(unit_id)
            response["removed_from_shoot_pool"] = True
    elif arg4 == "CHARGE":
        if "charge_activation_pool" in game_state and unit_id in game_state["charge_activation_pool"]:
            game_state["charge_activation_pool"].remove(unit_id)
            response["removed_from_charge_pool"] = True
    elif arg4 == "FIGHT":
        if "fight_activation_pool" in game_state and unit_id in game_state["fight_activation_pool"]:
            game_state["fight_activation_pool"].remove(unit_id)
            response["removed_from_fight_pool"] = True
    
    # ├── Arg5 = 1 ?
    # │   ├── YES → log the error
    # │   └── NO → No action
    if arg5 == 1:
        if "error_logs" not in game_state:
            game_state["error_logs"] = []
        game_state["error_logs"].append({
            "unitId": unit_id,
            "phase": game_state["phase"],
            "timestamp": "server_time"
        })
        response["error_logged"] = True
    
    # └── Remove the green circle around the unit's icon
    response["clear_unit_selection"] = True
    response["clear_green_circle"] = True
    
    # AI_TURN.md COMPLIANCE: Clear shooting phase target selection
    if arg4 == "SHOOTING":
        response["clear_target_selection"] = True
        response["clear_target_blinking"] = True
        # Clear unit's selected target state
        if "selected_target_id" in unit:
            unit["selected_target_id"] = None
        # Clear valid target pool highlighting
        if "valid_target_pool" in unit:
            unit["valid_target_pool"] = []
    
    # Check if activation pool is empty after removal
    current_phase = game_state["phase"]
    pool_empty = False
    
    if current_phase == "move":
        pool_empty = len(game_state.get("move_activation_pool", [])) == 0
    elif current_phase == "shoot":
        pool_empty = len(game_state.get("shoot_activation_pool", [])) == 0
    elif current_phase == "charge":
        pool_empty = len(game_state.get("charge_activation_pool", [])) == 0
    elif current_phase == "fight":
        pool_empty = len(game_state.get("fight_activation_pool", [])) == 0
    
    if pool_empty:
        response["phase_complete"] = True
    
    return response