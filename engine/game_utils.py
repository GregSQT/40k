#!/usr/bin/env python3
"""
game_utils.py - Shared utility functions for all engine modules
AI_TURN.md COMPLIANCE: Pure lookup functions, no game logic
"""

import os
from typing import Dict, Any, Optional


def _write_diagnostic_to_debug_log(message: str) -> None:
    """Write diagnostic message directly to debug.log"""
    try:
        # Get project root (parent of engine directory)
        # Use os imported at module level (line 7)
        current_file = os.path.abspath(__file__)
        engine_dir = os.path.dirname(current_file)
        project_root = os.path.dirname(engine_dir)
        debug_log_path = os.path.join(project_root, 'debug.log')
        
        with open(debug_log_path, 'a', encoding='utf-8', errors='replace') as f:
            f.write(message + "\n")
            f.flush()
    except Exception:
        # Silently fail - diagnostics are not critical
        pass


def add_debug_file_log(game_state: Dict[str, Any], message: str) -> None:
    """
    Write debug message to debug.log only if debug_mode is enabled.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key)
        message: Debug message to log
    """
    if not game_state.get("debug_mode", False):
        return
    _write_diagnostic_to_debug_log(message)


def get_unit_by_id(unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    AI_TURN.md COMPLIANCE: Direct lookup from game_state.
    Pure utility function - no dependencies on other modules.

    CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
    Pool unit IDs are integers, but some lookups pass strings.
    """
    for unit in game_state["units"]:
        if str(unit["id"]) == str(unit_id):
            return unit
    return None


def add_console_log(game_state: Dict[str, Any], message: str) -> None:
    """
    Add message to console_logs. Only when debug_mode is True (--debug).
    When debug_mode is False, does nothing to avoid building a large list and slowing training.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key when used in engine)
        message: Message to log
    """
    if not game_state.get("debug_mode", False):
        return
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append(message)


def add_debug_log(game_state: Dict[str, Any], message: str) -> None:
    """
    Add debug message to console_logs ONLY if debug_mode is enabled.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key)
        message: Debug message to log
    """
    if not game_state.get("debug_mode", False):
        return  # Skip logging if debug_mode is not enabled
    
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append(message)


def safe_print(game_state: Dict[str, Any], *args, **kwargs) -> None:
    """
    Conditionally print based on debug mode.
    DISABLED: Logs are written to file only, not printed to console to avoid flooding.
    
    Args:
        game_state: Game state dictionary
        *args, **kwargs: Arguments to pass to print()
    """
    # DISABLED: Do not print to console, logs are written to file only
    return


def conditional_debug_print(game_state: Dict[str, Any], message: str) -> None:
    """
    Conditionally print debug message to console only if debug_mode is enabled.
    DISABLED: Logs are written to file only, not printed to console to avoid flooding.
    
    Args:
        game_state: Game state dictionary (must contain "debug_mode" key)
        message: Message to print
    """
    # DISABLED: Do not print to console, logs are written to file only
    return