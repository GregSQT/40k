#!/usr/bin/env python3
"""
combat_utils.py - Pure utility functions for combat calculations
"""

from typing import Dict, List, Tuple, Any

# ============================================================================
# DISTANCE CALCULATION
# ============================================================================

def calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
        """Calculate hex distance using cube coordinates (matching handlers)."""
        # Convert offset to cube
        x1 = col1
        z1 = row1 - ((col1 - (col1 & 1)) >> 1)
        y1 = -x1 - z1
        
        x2 = col2
        z2 = row2 - ((col2 - (col2 & 1)) >> 1)
        y2 = -x2 - z2
        
        # Cube distance
        return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


def get_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
        """Get hex line using handler delegation."""
        from engine.phase_handlers import shooting_handlers
        return shooting_handlers._get_accurate_hex_line(start_col, start_row, end_col, end_row)


# ============================================================================
# LINE OF SIGHT
# ============================================================================

def has_line_of_sight(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check line of sight between shooter and target using handler delegation."""
        from engine.phase_handlers import shooting_handlers
        return shooting_handlers._has_line_of_sight(game_state, shooter, target)


def check_los_cached(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Check LoS using cache if available, fallback to calculation.
        AI_TURN.md COMPLIANCE: Direct field access, uses game_state cache.
        
        Returns:
        - 1.0 = Clear line of sight
        - 0.0 = Blocked line of sight
        """
        # Use LoS cache if available (Phase 1 implementation)
        if "los_cache" in game_state and game_state["los_cache"]:
            cache_key = (shooter["id"], target["id"])
            if cache_key in game_state["los_cache"]:
                return 1.0 if game_state["los_cache"][cache_key] else 0.0

# ============================================================================
# COMBAT VALIDATION
# ============================================================================

def calculate_wound_target(strength: int, toughness: int) -> int:
        """W40K wound chart - basic calculation without external dependencies"""
        if strength >= toughness * 2:
            return 2  # 2+
        elif strength > toughness:
            return 3  # 3+
        elif strength == toughness:
            return 4  # 4+
        elif strength * 2 <= toughness:
            return 6  # 6+
        else:
            return 5  # 5+


def has_valid_shooting_targets(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if unit has valid shooting targets per AI_TURN.md restrictions."""
        from engine.phase_handlers import shooting_handlers
        for enemy in game_state["units"]:
            if (enemy["player"] != unit["player"] and 
                enemy["HP_CUR"] > 0 and
                shooting_handlers._is_valid_shooting_target(game_state, unit, enemy)):
                return True
        return False


def is_valid_shooting_target(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """REMOVED: Redundant with handler. Use shooting_handlers._is_valid_shooting_target exclusively."""
        # AI_IMPLEMENTATION.md: Complete delegation to handler for consistency
        from engine.phase_handlers import shooting_handlers
        return shooting_handlers._is_valid_shooting_target(game_state, shooter, target)