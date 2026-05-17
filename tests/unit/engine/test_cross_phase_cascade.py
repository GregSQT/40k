"""Tests unitaires — cascade inter-phases : mort d'unité et filtres de pool cross-phase.

Couvre :
- Unité tuée en combat → retirée de tous les pools fight (charging, alternating, non-active)
- Unité tuée en tir → retirée de shoot, move, charge pools
- Unité ayant fui (units_fled) → exclue du pool de charge ET vérifiée dans le shoot pool
- Unité avancée (units_advanced) → exclue du pool de charge
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.fight_handlers import _remove_dead_unit_from_fight_pools
from engine.phase_handlers.shooting_handlers import _remove_dead_unit_from_pools
from engine.phase_handlers.charge_handlers import get_eligible_units as charge_get_eligible_units
from engine.phase_handlers.shooting_handlers import shooting_build_activation_pool
from engine.phase_handlers.shared_utils import (
    build_units_cache,
    build_enemy_adjacent_hexes,
    is_unit_alive,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "max_base_size_hex": 35,
            "los_visibility_min_ratio": 0.0,
            "cover_ratio": 0.0,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int, hp: int = 3) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": hp,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 0,
        "RNG_WEAPONS": [
            {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "RNG": 24, "NB": 1, "WEAPON_RULES": []}
        ],
        "CC_WEAPONS": [],
    }


def _make_gs(units: List[Dict[str, Any]], phase: str = "fight") -> Dict[str, Any]:
    """Game-state minimal avec tous les pools d'activation."""
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "units_moved": set(),
        "units_advanced": set(),
        "units_fled": set(),
        "units_shot": set(),
        "units_charged": set(),
        "units_fought": set(),
        "units_cannot_charge": set(),
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "hex_los_cache": {},
        "los_cache": {},
        "_unit_move_version": 0,
        "player_types": {"1": "human", "2": "ai"},
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, gs["current_player"])
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# P2-A : mort en phase fight → retrait des pools fight
# ─────────────────────────────────────────────────────────────────────────────

class TestFightDeathCascade:
    def test_dead_unit_removed_from_charging_pool(self):
        """cascade_fight_charging : unité tuée → retirée du charging_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_gs(units)
        gs["charging_activation_pool"] = ["1", "2"]
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []
        # Simuler la mort : HP_CUR → 0 + retirer de units_cache
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_fight_pools(gs, "1")

        assert "1" not in gs["charging_activation_pool"]
        assert "2" in gs["charging_activation_pool"]

    def test_dead_unit_removed_from_active_alternating_pool(self):
        """cascade_fight_active_alt : mort → retirée du active_alternating_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_gs(units)
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = ["1", "2"]
        gs["non_active_alternating_activation_pool"] = []
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_fight_pools(gs, "1")

        assert "1" not in gs["active_alternating_activation_pool"]

    def test_dead_unit_removed_from_non_active_alternating_pool(self):
        """cascade_fight_non_active : mort → retirée du non_active_alternating_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_gs(units)
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = ["1", "2"]
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_fight_pools(gs, "1")

        assert "1" not in gs["non_active_alternating_activation_pool"]

    def test_dead_unit_removed_from_shoot_pool_via_fight_cascade(self):
        """cascade_fight_also_shoot : _remove_dead_unit_from_fight_pools retire aussi du shoot pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_gs(units)
        gs["shoot_activation_pool"] = ["1", "2"]
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_fight_pools(gs, "1")

        assert "1" not in gs["shoot_activation_pool"]

    def test_dead_unit_removed_from_move_pool_via_fight_cascade(self):
        """cascade_fight_also_move : mort en fight → retirée du move_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_gs(units)
        gs["move_activation_pool"] = ["1", "2"]
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_fight_pools(gs, "1")

        assert "1" not in gs["move_activation_pool"]

    def test_fight_death_survivor_intact(self):
        """cascade_fight_survivor : unité survivante reste dans tous les pools."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_gs(units)
        gs["charging_activation_pool"] = ["1", "2"]
        gs["active_alternating_activation_pool"] = ["1", "2"]
        gs["non_active_alternating_activation_pool"] = ["1", "2"]
        gs["shoot_activation_pool"] = ["1", "2"]
        gs["move_activation_pool"] = ["1", "2"]
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_fight_pools(gs, "1")

        assert "2" in gs["charging_activation_pool"]
        assert "2" in gs["active_alternating_activation_pool"]
        assert "2" in gs["non_active_alternating_activation_pool"]
        assert "2" in gs["shoot_activation_pool"]
        assert "2" in gs["move_activation_pool"]


# ─────────────────────────────────────────────────────────────────────────────
# P2-B : mort en phase tir → retrait des pools tir/move/charge
# ─────────────────────────────────────────────────────────────────────────────

class TestShootDeathCascade:
    def test_shoot_death_removes_from_shoot_pool(self):
        """cascade_shoot_pool : unité tuée en tir → retirée du shoot_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units, phase="shoot")
        gs["shoot_activation_pool"] = ["1", "2"]
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_pools(gs, "1")

        assert "1" not in gs["shoot_activation_pool"]
        assert "2" in gs["shoot_activation_pool"]

    def test_shoot_death_removes_from_move_pool(self):
        """cascade_shoot_move : mort en tir → retirée du move_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units, phase="shoot")
        gs["move_activation_pool"] = ["1", "2"]
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_pools(gs, "1")

        assert "1" not in gs["move_activation_pool"]

    def test_shoot_death_removes_from_charge_pool(self):
        """cascade_shoot_charge : mort en tir → retirée du charge_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units, phase="shoot")
        gs["charge_activation_pool"] = ["1", "2"]
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_pools(gs, "1")

        assert "1" not in gs["charge_activation_pool"]

    def test_shoot_death_clears_active_shooting_unit(self):
        """cascade_shoot_active : si l'unité morte était active_shooting_unit → champ supprimé."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units, phase="shoot")
        gs["active_shooting_unit"] = "1"
        units[0]["HP_CUR"] = 0
        gs["units_cache"].pop("1", None)

        _remove_dead_unit_from_pools(gs, "1")

        assert "active_shooting_unit" not in gs


# ─────────────────────────────────────────────────────────────────────────────
# P2-C : unité ayant fui → exclue du pool de charge et de tir
# ─────────────────────────────────────────────────────────────────────────────

class TestFledUnitExclusion:
    def test_fled_unit_excluded_from_charge_pool(self, monkeypatch):
        """cascade_fled_charge : unité dans units_fled → exclue de charge_get_eligible_units."""
        # Unité 1 (P1) à distance de charge de l'ennemi 2 (P2)
        unit1 = _unit(1, 1, 5, 10)
        unit2 = _unit(2, 2, 7, 10)
        units = [unit1, unit2]
        gs = _make_gs(units, phase="charge")
        gs["units_charged"] = set()
        gs["units_fled"] = {"1"}
        gs["units_cannot_charge"] = set()
        gs["units_advanced"] = set()

        # Monkeypatch _has_valid_charge_target pour isoler le filtre fled
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._has_valid_charge_target",
            lambda gs, unit, occupied=None: True,
        )
        # Monkeypatch _charge_unit_within_engagement_zone → False (pas en EZ)
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._charge_unit_within_engagement_zone",
            lambda gs, unit: False,
        )

        eligible = charge_get_eligible_units(gs)

        assert "1" not in eligible

    def test_non_fled_unit_eligible_for_charge(self, monkeypatch):
        """cascade_non_fled_charge : unité sans fuite → éligible à la charge."""
        unit1 = _unit(1, 1, 5, 10)
        unit2 = _unit(2, 2, 7, 10)
        units = [unit1, unit2]
        gs = _make_gs(units, phase="charge")
        gs["units_charged"] = set()
        gs["units_fled"] = set()  # Pas de fuite
        gs["units_cannot_charge"] = set()
        gs["units_advanced"] = set()

        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._has_valid_charge_target",
            lambda gs, unit, occupied=None: True,
        )
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._charge_unit_within_engagement_zone",
            lambda gs, unit: False,
        )

        eligible = charge_get_eligible_units(gs)

        assert "1" in eligible

    def test_fled_unit_excluded_from_shoot_pool(self):
        """cascade_fled_shoot : unité dans units_fled → exclue du shoot_activation_pool."""
        unit1 = _unit(1, 1, 5, 10)
        unit2 = _unit(2, 2, 20, 10)
        units = [unit1, unit2]
        gs = _make_gs(units, phase="shoot")
        gs["units_fled"] = {"1"}
        gs["units_shot"] = set()

        pool = shooting_build_activation_pool(gs)

        assert "1" not in pool


# ─────────────────────────────────────────────────────────────────────────────
# P2-D : unité avancée → exclue du pool de charge
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvancedUnitExclusion:
    def test_advanced_unit_excluded_from_charge_pool(self, monkeypatch):
        """cascade_advanced_charge : unité dans units_advanced → exclue de charge_get_eligible_units."""
        unit1 = _unit(1, 1, 5, 10)
        unit2 = _unit(2, 2, 7, 10)
        units = [unit1, unit2]
        gs = _make_gs(units, phase="charge")
        gs["units_charged"] = set()
        gs["units_fled"] = set()
        gs["units_cannot_charge"] = set()
        gs["units_advanced"] = {"1"}  # Unité 1 a avancé

        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._has_valid_charge_target",
            lambda gs, unit, occupied=None: True,
        )
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._charge_unit_within_engagement_zone",
            lambda gs, unit: False,
        )

        eligible = charge_get_eligible_units(gs)

        assert "1" not in eligible

    def test_non_advanced_unit_eligible_for_charge(self, monkeypatch):
        """cascade_non_advanced_charge : unité non avancée → éligible à la charge."""
        unit1 = _unit(1, 1, 5, 10)
        unit2 = _unit(2, 2, 7, 10)
        units = [unit1, unit2]
        gs = _make_gs(units, phase="charge")
        gs["units_charged"] = set()
        gs["units_fled"] = set()
        gs["units_cannot_charge"] = set()
        gs["units_advanced"] = set()  # Pas avancé

        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._has_valid_charge_target",
            lambda gs, unit, occupied=None: True,
        )
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers._charge_unit_within_engagement_zone",
            lambda gs, unit: False,
        )

        eligible = charge_get_eligible_units(gs)

        assert "1" in eligible
