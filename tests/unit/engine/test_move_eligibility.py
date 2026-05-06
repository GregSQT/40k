"""Régression : get_eligible_units, movement_phase_start, movement_preview."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.movement_handlers import (
    get_eligible_units,
    movement_build_activation_pool,
    movement_phase_start,
    movement_preview,
    movement_clear_preview,
)
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "max_base_size_hex": 35,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int, move: int = 6) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "MOVE": move,
        "HP_CUR": 2,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
    }


def _make_game_state(
    units: List[Dict[str, Any]],
    current_player: int = 1,
    wall_hexes=None,
    board_cols: int = 25,
    board_rows: int = 21,
) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _board_config(),
        "board_cols": board_cols,
        "board_rows": board_rows,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": wall_hexes if wall_hexes is not None else set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "move_activation_pool": [],
        "units_moved": set(),
        "units_fled": set(),
        "console_logs": [],
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, current_player)
    return gs


# ---------------------------------------------------------------------------
# get_eligible_units
# ---------------------------------------------------------------------------


class TestGetEligibleUnits:
    def test_only_current_player_units_eligible(self):
        units = [
            _unit(1, 1, 5, 10),
            _unit(2, 2, 20, 10),
        ]
        gs = _make_game_state(units, current_player=1)
        result = get_eligible_units(gs)
        assert "1" in result
        assert "2" not in result

    def test_unit_with_move_zero_excluded(self):
        units = [
            _unit(1, 1, 5, 10, move=0),
            _unit(2, 1, 7, 10, move=6),
        ]
        gs = _make_game_state(units, current_player=1)
        result = get_eligible_units(gs)
        assert "1" not in result
        assert "2" in result

    def test_unit_completely_surrounded_by_walls_excluded(self):
        col, row = 5, 10
        # Actual neighbors of (5,10): get_hex_neighbors(5,10) = [(5,9),(6,10),(6,11),(5,11),(4,11),(4,10)]
        walls = {(5, 9), (6, 10), (6, 11), (5, 11), (4, 11), (4, 10)}
        units = [_unit(1, 1, col, row, move=1)]
        gs = _make_game_state(units, current_player=1, wall_hexes=walls)
        result = get_eligible_units(gs)
        assert "1" not in result

    def test_unit_in_open_space_eligible(self):
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        result = get_eligible_units(gs)
        assert "1" in result

    def test_player_switch_returns_correct_units(self):
        units = [
            _unit(1, 1, 5, 10),
            _unit(2, 2, 20, 10),
        ]
        gs = _make_game_state(units, current_player=2)
        result = get_eligible_units(gs)
        assert "2" in result
        assert "1" not in result

    def test_raises_on_missing_enemy_adjacent_cache(self):
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        del gs["enemy_adjacent_hexes_player_1"]
        with pytest.raises(KeyError, match="enemy_adjacent_hexes"):
            get_eligible_units(gs)

    def test_raises_on_invalid_move_value(self):
        units = [_unit(1, 1, 5, 10)]
        units[0]["MOVE"] = "invalid"
        gs = _make_game_state(units, current_player=1)
        with pytest.raises(ValueError, match="Invalid MOVE value"):
            get_eligible_units(gs)


# ---------------------------------------------------------------------------
# movement_build_activation_pool
# ---------------------------------------------------------------------------


class TestMovementBuildActivationPool:
    def test_pool_contains_eligible_units(self):
        units = [
            _unit(1, 1, 5, 10),
            _unit(2, 2, 20, 10),
        ]
        gs = _make_game_state(units, current_player=1)
        movement_build_activation_pool(gs)
        assert "1" in gs["move_activation_pool"]
        assert "2" not in gs["move_activation_pool"]

    def test_pool_empty_when_no_eligible_units(self):
        units = [
            _unit(1, 1, 5, 10, move=0),
        ]
        gs = _make_game_state(units, current_player=1)
        movement_build_activation_pool(gs)
        assert gs["move_activation_pool"] == []


# ---------------------------------------------------------------------------
# movement_preview / movement_clear_preview
# ---------------------------------------------------------------------------


class TestMovementPreview:
    def test_preview_returns_green_hexes_and_show_flag(self):
        destinations = [(5, 10), (6, 10), (7, 10)]
        result = movement_preview(destinations)
        assert result["show_preview"] is True
        assert result["green_hexes"] == destinations

    def test_preview_empty_destinations(self):
        result = movement_preview([])
        assert result["show_preview"] is True
        assert result["green_hexes"] == []

    def test_clear_preview_resets_state(self):
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["preview_hexes"] = [(5, 10)]
        gs["valid_move_destinations_pool"] = [(5, 10)]
        gs["active_movement_unit"] = "1"
        gs["move_preview_footprint_zone"] = {(5, 10)}
        gs["move_preview_border"] = [(5, 10)]
        gs["move_preview_footprint_mask_loops"] = "something"
        gs["move_preview_footprint_span"] = 3

        result = movement_clear_preview(gs)

        assert result["show_preview"] is False
        assert result["clear_hexes"] is True
        assert gs["preview_hexes"] == []
        assert gs["valid_move_destinations_pool"] == []
        assert gs["active_movement_unit"] is None
        assert gs["move_preview_footprint_zone"] == set()
        assert gs["move_preview_border"] == []
        assert gs["move_preview_footprint_mask_loops"] is None
        assert gs["move_preview_footprint_span"] is None
