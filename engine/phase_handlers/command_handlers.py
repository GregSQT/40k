#!/usr/bin/env python3
"""
command_handlers.py - Command Phase Implementation
Pure stateless functions implementing command phase specification

The command phase handles all administrative tasks (reset marks, clear caches, etc.)
before the movement phase. It auto-advances to the movement phase.
"""

from typing import Dict, List, Tuple, Set, Optional, Any


def command_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize command phase - do all maintenance/resets, then transition to move.
    
    This function:
    - Sets phase to "command"
    - Resets all tracking sets (units_moved, units_fled, etc.)
    - Clears all preview pools (valid_move_destinations_pool, preview_hexes, etc.)
    - Clears enemy_reachable_cache
    - Builds activation pool (empty for now, structure ready for future)
    - Auto-advances to move phase
    """
    # Set phase
    game_state["phase"] = "command"
    
    # Reset ALL tracking sets (moved from movement_phase_start)
    game_state["units_moved"] = set()
    game_state["units_fled"] = set()
    game_state["units_shot"] = set()
    game_state["units_charged"] = set()
    game_state["units_fought"] = set()
    game_state["units_attacked"] = set()
    game_state["units_advanced"] = set()
    
    # Clear movement preview state
    game_state["valid_move_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_movement_unit"] = None
    
    # Clear enemy reachable positions cache (enemy positions may have changed)
    # Used by RewardCalculator._get_enemy_reachable_positions for defensive threat calculation
    game_state["enemy_reachable_cache"] = {}
    
    # Build activation pool (empty for now, structure ready for future)
    command_build_activation_pool(game_state)
    
    # Console log
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("COMMAND PHASE START")
    
    # Auto-advance: transition directly to move (pool is empty)
    return command_phase_end(game_state)


def command_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build command activation pool (empty for now, structure ready for future).
    """
    game_state["command_activation_pool"] = []


def command_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    End command phase and transition to move phase.
    
    CRITICAL: Returns ONLY the dict, does NOT call movement_phase_start() directly.
    The cascade loop in w40k_core.py handles the transition automatically.
    """
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("COMMAND PHASE COMPLETE")
    
    # Return only the dict - cascade loop will call movement_phase_start()
    return {
        "phase_complete": True,
        "next_phase": "move",
        "phase_transition": True,
        "clear_blinking_gentle": True
    }


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute action for command phase (structure ready for future).
    
    For now, no actions - phase auto-advances.
    Structure ready for future unit actions in command phase.
    """
    # For now, no actions - phase auto-advances
    # Structure ready for future unit actions in command phase
    return True, command_phase_end(game_state)




