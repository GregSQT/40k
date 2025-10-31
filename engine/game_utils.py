#!/usr/bin/env python3
"""
game_utils.py - Shared utility functions for all engine modules
AI_TURN.md COMPLIANCE: Pure lookup functions, no game logic
"""

from typing import Dict, Any, Optional


def get_unit_by_id(unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    AI_TURN.md COMPLIANCE: Direct lookup from game_state.
    Pure utility function - no dependencies on other modules.
    """
    for unit in game_state["units"]:
        if unit["id"] == str(unit_id):
            return unit
    return None