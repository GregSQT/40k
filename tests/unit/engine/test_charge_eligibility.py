"""Régression : get_eligible_units pour la phase charge."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.charge_handlers import get_eligible_units
from engine.phase_handlers.shared_utils import build_units_cache


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "charge_max_distance": 12,
            "max_base_size_hex": 35,
        },
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
) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _board_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "charge",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_advanced": set(),
        "console_logs": [],
    }
    build_units_cache(gs)
    return gs


def _patch_ez_and_target(monkeypatch: pytest.MonkeyPatch, in_ez: bool = False, has_target: bool = True) -> None:
    """Monkeypatch les deux fonctions complexes pour tester uniquement les filtres."""
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers._charge_unit_within_engagement_zone",
        lambda gs, unit: in_ez,
    )
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers._has_valid_charge_target",
        lambda gs, unit, occupied=None: has_target,
    )


class TestChargeEligibleUnits:
    def test_only_current_player_units_eligible(self, monkeypatch):
        _patch_ez_and_target(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        result = get_eligible_units(gs)
        assert "1" in result
        assert "2" not in result

    def test_units_charged_flag_does_not_exclude(self, monkeypatch):
        """units_charged ne filtre PAS l'éligibilité — c'est le pool qui se vide après activation."""
        _patch_ez_and_target(monkeypatch)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_charged"] = {"1"}
        result = get_eligible_units(gs)
        assert "1" in result

    def test_unit_fled_excluded(self, monkeypatch):
        _patch_ez_and_target(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_fled"] = {"1"}
        result = get_eligible_units(gs)
        assert "1" not in result
        assert "2" in result

    def test_unit_cannot_charge_excluded(self, monkeypatch):
        _patch_ez_and_target(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_cannot_charge"] = {"1"}
        result = get_eligible_units(gs)
        assert "1" not in result
        assert "2" in result

    def test_unit_advanced_excluded(self, monkeypatch):
        _patch_ez_and_target(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_advanced"] = {"1"}
        result = get_eligible_units(gs)
        assert "1" not in result
        assert "2" in result

    def test_unit_in_engagement_zone_excluded(self, monkeypatch):
        _patch_ez_and_target(monkeypatch, in_ez=True)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        result = get_eligible_units(gs)
        assert "1" not in result

    def test_unit_no_valid_charge_target_excluded(self, monkeypatch):
        _patch_ez_and_target(monkeypatch, in_ez=False, has_target=False)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        result = get_eligible_units(gs)
        assert "1" not in result

    def test_unit_passes_all_filters_included(self, monkeypatch):
        _patch_ez_and_target(monkeypatch, in_ez=False, has_target=True)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        result = get_eligible_units(gs)
        assert "1" in result

    def test_player_switch(self, monkeypatch):
        _patch_ez_and_target(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=2)
        result = get_eligible_units(gs)
        assert "2" in result
        assert "1" not in result

    def test_fled_unit_with_charge_after_flee_rule_included(self, monkeypatch):
        """Unité en fuite mais avec la règle charge_after_flee → reste éligible."""
        _patch_ez_and_target(monkeypatch)
        unit = _unit(1, 1, 5, 10)
        unit["UNIT_RULES"] = [{"ruleId": "charge_after_flee"}]
        gs = _make_game_state([unit, _unit(2, 2, 20, 10)], current_player=1)
        gs["units_fled"] = {"1"}
        result = get_eligible_units(gs)
        assert "1" in result

    def test_advanced_unit_with_charge_after_advance_rule_included(self, monkeypatch):
        """Unité qui a avancé mais avec la règle charge_after_advance → reste éligible."""
        _patch_ez_and_target(monkeypatch)
        unit = _unit(1, 1, 5, 10)
        unit["UNIT_RULES"] = [{"ruleId": "charge_after_advance"}]
        gs = _make_game_state([unit, _unit(2, 2, 20, 10)], current_player=1)
        gs["units_advanced"] = {"1"}
        result = get_eligible_units(gs)
        assert "1" in result

    def test_fled_unit_without_rule_excluded(self, monkeypatch):
        """Unité en fuite sans règle d'override → exclue (régression des anciens tests)."""
        _patch_ez_and_target(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_fled"] = {"1"}
        result = get_eligible_units(gs)
        assert "1" not in result
