"""Régression : fight_build_activation_pools — pools charge/alternating, filtres."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.fight_handlers import fight_build_activation_pools
from engine.phase_handlers.shared_utils import build_units_cache


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 1, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 2,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
    }


def _make_game_state(
    units: List[Dict[str, Any]],
    current_player: int = 1,
    units_charged=None,
    units_fought=None,
) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _board_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "fight",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": units_charged or set(),
        "units_fought": units_fought or set(),
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "console_logs": [],
    }
    build_units_cache(gs)
    return gs


def _patch_target_pool(monkeypatch: pytest.MonkeyPatch, has_targets: bool = True) -> None:
    monkeypatch.setattr(
        "engine.phase_handlers.fight_handlers._fight_build_valid_target_pool",
        lambda gs, unit: ["enemy"] if has_targets else [],
    )


class TestFightActivationPools:
    def test_raises_without_units_charged_key(self, monkeypatch):
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        del gs["units_charged"]
        with pytest.raises(KeyError, match="units_charged"):
            fight_build_activation_pools(gs)

    def test_raises_on_invalid_current_player(self, monkeypatch):
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["current_player"] = 99
        with pytest.raises(ValueError, match="current_player"):
            fight_build_activation_pools(gs)

    def test_charging_unit_in_charging_pool(self, monkeypatch):
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1, units_charged={"1"})
        fight_build_activation_pools(gs)
        assert "1" in gs["charging_activation_pool"]

    def test_charging_unit_not_in_alternating_pool(self, monkeypatch):
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1, units_charged={"1"})
        fight_build_activation_pools(gs)
        assert "1" not in gs["active_alternating_activation_pool"]
        assert "1" not in gs["non_active_alternating_activation_pool"]

    def test_non_charging_current_player_in_active_pool(self, monkeypatch):
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        fight_build_activation_pools(gs)
        assert "1" in gs["active_alternating_activation_pool"]

    def test_non_charging_other_player_in_non_active_pool(self, monkeypatch):
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        fight_build_activation_pools(gs)
        assert "2" in gs["non_active_alternating_activation_pool"]

    def test_already_fought_unit_excluded_from_all_pools(self, monkeypatch):
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1, units_fought={"1"})
        fight_build_activation_pools(gs)
        assert "1" not in gs["charging_activation_pool"]
        assert "1" not in gs["active_alternating_activation_pool"]
        assert "1" not in gs["non_active_alternating_activation_pool"]

    def test_unit_no_valid_targets_excluded(self, monkeypatch):
        _patch_target_pool(monkeypatch, has_targets=False)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        fight_build_activation_pools(gs)
        assert "1" not in gs["active_alternating_activation_pool"]
        assert "2" not in gs["non_active_alternating_activation_pool"]

    def test_pools_cleared_before_rebuild(self, monkeypatch):
        _patch_target_pool(monkeypatch, has_targets=False)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["charging_activation_pool"] = ["99"]
        gs["active_alternating_activation_pool"] = ["99"]
        gs["non_active_alternating_activation_pool"] = ["99"]
        fight_build_activation_pools(gs)
        assert "99" not in gs["charging_activation_pool"]
        assert "99" not in gs["active_alternating_activation_pool"]
        assert "99" not in gs["non_active_alternating_activation_pool"]

    def test_unit_in_charged_and_fought_excluded(self, monkeypatch):
        """units_fought prend la priorité sur units_charged."""
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units, current_player=1, units_charged={"1"}, units_fought={"1"})
        fight_build_activation_pools(gs)
        assert "1" not in gs["charging_activation_pool"]
        assert "1" not in gs["active_alternating_activation_pool"]
        assert "1" not in gs["non_active_alternating_activation_pool"]

    def test_current_player_string_normalized(self, monkeypatch):
        """current_player="1" est normalisé en int sans erreur."""
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["current_player"] = "1"
        fight_build_activation_pools(gs)
        assert gs["current_player"] == 1
        assert "1" in gs["active_alternating_activation_pool"]

    def test_current_player_invalid_string_raises(self, monkeypatch):
        """current_player non-convertible en int → ValueError."""
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["current_player"] = "invalid"
        with pytest.raises(ValueError, match="current_player"):
            fight_build_activation_pools(gs)

    def test_real_adjacent_units_in_pools(self):
        """Sans mock : unités adjacentes (hexes contigus) → incluses dans les pools."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units, current_player=1)
        fight_build_activation_pools(gs)
        assert "1" in gs["active_alternating_activation_pool"]
        assert "2" in gs["non_active_alternating_activation_pool"]

    def test_real_distant_units_excluded_from_pools(self):
        """Sans mock : unités éloignées → exclues des pools (pas de cibles valides)."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        fight_build_activation_pools(gs)
        assert "1" not in gs["active_alternating_activation_pool"]
        assert "2" not in gs["non_active_alternating_activation_pool"]
