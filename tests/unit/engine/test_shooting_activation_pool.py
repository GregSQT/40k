"""Régression : shooting_build_activation_pool — filtrage joueur, morts, cibles."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shooting_handlers import shooting_build_activation_pool
from engine.phase_handlers.shared_utils import build_units_cache


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 10, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int, hp: int = 2) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": hp,
        "HP_MAX": hp,
        "VALUE": 50,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "BASE_SIZE": 3,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "RNG_WEAPONS": [{"RNG": 24, "SHOTS": "1", "STRENGTH": 4, "AP": 0, "DAMAGE": 1}],
        "CC_WEAPONS": [],
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
        "phase": "shoot",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_fled": set(),
        "units_shot": set(),
        "shoot_activation_pool": [],
        "console_logs": [],
        "debug_logs": [],
        "hex_los_cache": {},
        "weapon_rule": {},
    }
    build_units_cache(gs)
    return gs


def _patch_targets(monkeypatch: pytest.MonkeyPatch, has_targets: bool = True) -> None:
    monkeypatch.setattr(
        "engine.phase_handlers.shooting_handlers._has_valid_shooting_targets",
        lambda gs, unit, player: has_targets,
    )


class TestShootingActivationPool:
    def test_only_current_player_units_in_pool(self, monkeypatch):
        _patch_targets(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        shooting_build_activation_pool(gs)
        assert "1" in gs["shoot_activation_pool"]
        assert "2" not in gs["shoot_activation_pool"]

    def test_dead_unit_hp_none_excluded(self, monkeypatch):
        _patch_targets(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_cache"]["1"]["HP_CUR"] = None
        shooting_build_activation_pool(gs)
        assert "1" not in gs["shoot_activation_pool"]
        assert "2" in gs["shoot_activation_pool"]

    def test_unit_no_valid_targets_excluded(self, monkeypatch):
        _patch_targets(monkeypatch, has_targets=False)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        shooting_build_activation_pool(gs)
        assert gs["shoot_activation_pool"] == []

    def test_unit_with_valid_targets_in_pool(self, monkeypatch):
        _patch_targets(monkeypatch, has_targets=True)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        shooting_build_activation_pool(gs)
        assert "1" in gs["shoot_activation_pool"]

    def test_pool_cleared_before_rebuild(self, monkeypatch):
        _patch_targets(monkeypatch, has_targets=True)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["shoot_activation_pool"] = ["99"]  # stale data
        shooting_build_activation_pool(gs)
        assert "99" not in gs["shoot_activation_pool"]
        assert "1" in gs["shoot_activation_pool"]

    def test_player_switch_returns_correct_units(self, monkeypatch):
        _patch_targets(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=2)
        shooting_build_activation_pool(gs)
        assert "2" in gs["shoot_activation_pool"]
        assert "1" not in gs["shoot_activation_pool"]

    def test_raises_on_missing_current_player(self, monkeypatch):
        _patch_targets(monkeypatch)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["current_player"] = None
        with pytest.raises(ValueError, match="current_player"):
            shooting_build_activation_pool(gs)

    def test_raises_on_invalid_current_player_string(self, monkeypatch):
        """current_player non-convertible en int → ValueError."""
        _patch_targets(monkeypatch)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["current_player"] = "invalid"
        with pytest.raises(ValueError):
            shooting_build_activation_pool(gs)

    def test_dead_unit_hp_zero_not_excluded(self, monkeypatch):
        """HP_CUR=0 n'est pas None : la source exclut uniquement None, pas 0."""
        _patch_targets(monkeypatch)
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_cache"]["1"]["HP_CUR"] = 0
        shooting_build_activation_pool(gs)
        assert "1" in gs["shoot_activation_pool"]

    def test_fled_unit_excluded_no_mock(self):
        """shoot_after_flee : unité en fuite exclue du pool — vérifié sans mock sur _has_valid_shooting_targets."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_fled"] = {"1"}
        # Pas de mock : _has_valid_shooting_targets vérifie units_fled avant l'adjacence
        shooting_build_activation_pool(gs)
        assert "1" not in gs["shoot_activation_pool"]

    def test_fled_unit_with_shoot_after_flee_rule_eligible_no_mock(self):
        """shoot_after_flee avec règle override : l'unité reste éligible au tir."""
        unit = _unit(1, 1, 5, 10)
        unit["UNIT_RULES"] = [{"ruleId": "shoot_after_flee"}]
        units = [unit, _unit(2, 2, 20, 10)]
        gs = _make_game_state(units, current_player=1)
        gs["units_fled"] = {"1"}
        shooting_build_activation_pool(gs)
        assert "1" in gs["shoot_activation_pool"]

    def test_unit_removed_from_cache_not_in_pool(self, monkeypatch):
        """dead_unit : unité retirée du cache (morte) absente du pool de tir."""
        _patch_targets(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1)
        del gs["units_cache"]["1"]
        shooting_build_activation_pool(gs)
        assert "1" not in gs["shoot_activation_pool"]
        assert "2" in gs["shoot_activation_pool"]


# ---------------------------------------------------------------------------
# Multi-hex footprint geometry invariants — shooting
# ---------------------------------------------------------------------------


class TestMultiHexShootingInvariants:
    def test_large_base_adjacent_via_footprint_excluded_without_pistol(self):
        """footprint_adjacency_shooting : grand socle (BASE_SIZE=25) en EZ via empreinte → adjacent
        → arme sans règle PISTOL non utilisable → unité absente du pool de tir.

        euclidean_edge_clearance(5,10, 30,10, r=18.75, r=18.75) = 45 - 37.5 = 7.5 ≤ req(15.0).
        """
        units = [
            {**_unit(1, 1, 5, 10), "BASE_SIZE": 25, "MODEL_HEIGHT": 2.5},
            {**_unit(2, 2, 30, 10), "BASE_SIZE": 25, "MODEL_HEIGHT": 2.5},
        ]
        gs = _make_game_state(units, current_player=1)
        shooting_build_activation_pool(gs)
        assert "1" not in gs["shoot_activation_pool"], (
            "large-base shooter in EZ via footprint must be excluded (no PISTOL weapon)"
        )

    def test_small_base_not_adjacent_in_shoot_pool(self):
        """footprint_adjacency_shooting_small : petit socle (BASE_SIZE=3) aux mêmes positions → hors EZ
        → non adjacent → unité présente dans le pool de tir.

        euclidean_edge_clearance(5,10, 30,10, r=2.25, r=2.25) = 45 - 4.5 = 40.5 > req(15.0).
        """
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 30, 10)]
        gs = _make_game_state(units, current_player=1)
        shooting_build_activation_pool(gs)
        assert "1" in gs["shoot_activation_pool"], (
            "small-base shooter not in EZ must be in shoot pool"
        )
