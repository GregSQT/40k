"""Régression : fight_build_activation_pools — pools charge/alternating, filtres."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.fight_handlers import (
    fight_build_activation_pools,
    _fight_build_valid_target_pool,
)
from engine.phase_handlers.shared_utils import build_units_cache


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 10, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 2,
        "HP_MAX": 2,
        "VALUE": 50,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": 3,
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

    def test_dead_unit_removed_from_cache_not_in_pools(self, monkeypatch):
        """fight_dead_unit_attacker : unité retirée du cache absente de tous les pools."""
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1)
        del gs["units_cache"]["1"]
        fight_build_activation_pools(gs)
        assert "1" not in gs["charging_activation_pool"]
        assert "1" not in gs["active_alternating_activation_pool"]
        assert "1" not in gs["non_active_alternating_activation_pool"]
        assert "2" in gs["active_alternating_activation_pool"]

    def test_no_unit_in_multiple_pools(self, monkeypatch):
        """double_activation : une unité n'apparaît que dans un seul pool à la fois."""
        _patch_target_pool(monkeypatch)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10), _unit(3, 1, 7, 10)]
        gs = _make_game_state(units, current_player=1, units_charged={"1"})
        fight_build_activation_pools(gs)
        all_pools = (
            gs["charging_activation_pool"]
            + gs["active_alternating_activation_pool"]
            + gs["non_active_alternating_activation_pool"]
        )
        assert len(all_pools) == len(set(all_pools))


class TestFightBuildValidTargetPool:
    def test_friendly_unit_excluded_from_target_pool(self):
        """fight_friendly : _fight_build_valid_target_pool n'inclut pas les alliés."""
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 6, 10), _unit(3, 2, 6, 10)]
        gs = _make_game_state(units, current_player=1)
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" not in targets
        assert "1" not in targets

    def test_dead_attacker_raises(self):
        """fight_dead_unit_attacker : ValueError si l'attaquant n'est plus dans units_cache."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units, current_player=1)
        del gs["units_cache"]["1"]
        with pytest.raises(ValueError, match="not in units_cache"):
            _fight_build_valid_target_pool(gs, units[0])

    def test_dead_target_excluded_from_pool(self):
        """fight_dead_unit_target : cible retirée du cache absente du pool de cibles."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10), _unit(3, 2, 7, 10)]
        gs = _make_game_state(units, current_player=1)
        del gs["units_cache"]["2"]
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" not in targets

    def test_two_enemies_only_one_in_ez(self):
        """fight_two_enemies_one_ez : deux ennemis — seul celui en EZ est dans le pool.

        enemy2 en (6,10) → adjacent, en EZ → inclus.
        enemy3 en (35,10) → loin, hors EZ (edge gap > engagement_zone=10) → exclu.
        """
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10), _unit(3, 2, 35, 10)]
        gs = _make_game_state(units, current_player=1)
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" in targets, "adjacent enemy must be in pool"
        assert "3" not in targets, "far enemy must not be in pool"
        assert len(targets) == 1


# ---------------------------------------------------------------------------
# Multi-hex footprint geometry invariants — fight
# ---------------------------------------------------------------------------


class TestMultiHexFightInvariants:
    def test_large_round_base_distant_centers_in_ez(self):
        """footprint_adjacency_ez : grands socles ronds (BASE_SIZE=25) avec centres éloignés → en EZ.

        euclidean_edge_clearance(5,10, 35,10, r=18.75, r=18.75) = 45 - 37.5 = 7.5 ≤ req(15.0).
        _fight_build_valid_target_pool doit inclure l'ennemi.
        """
        unit_a = {**_unit(1, 1, 5, 10), "BASE_SIZE": 25}
        unit_b = {**_unit(2, 2, 35, 10), "BASE_SIZE": 25}
        gs = _make_game_state([unit_a, unit_b], current_player=1)
        targets = _fight_build_valid_target_pool(gs, unit_a)
        assert "2" in targets, "large-base enemy must be in fight target pool when edge-to-edge gap ≤ req"

    def test_small_round_base_distant_centers_not_in_ez(self):
        """fight_target_pool_footprint : petits socles ronds (BASE_SIZE=3) aux mêmes positions → hors EZ.

        euclidean_edge_clearance(5,10, 35,10, r=2.25, r=2.25) = 45 - 4.5 = 40.5 > req(15.0).
        _fight_build_valid_target_pool ne doit PAS inclure l'ennemi.
        """
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 35, 10)]
        gs = _make_game_state(units, current_player=1)
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" not in targets, "small-base enemy far away must not be in fight target pool"

    def test_large_square_base_footprint_ez_via_min_distance(self):
        """footprint_adjacency_ez_square : socles carrés (BASE_SIZE=5) — chemin min_distance_between_sets.

        min_distance(fp(5,10), fp(16,10)) = 7 ≤ engagement_zone(10) → en EZ.
        """
        unit_a = {**_unit(1, 1, 5, 10), "BASE_SIZE": 5, "BASE_SHAPE": "square"}
        unit_b = {**_unit(2, 2, 16, 10), "BASE_SIZE": 5, "BASE_SHAPE": "square"}
        gs = _make_game_state([unit_a, unit_b], current_player=1)
        targets = _fight_build_valid_target_pool(gs, unit_a)
        assert "2" in targets, "large square-base enemy must be in fight target pool via footprint distance"

    def test_small_square_base_not_in_ez(self):
        """fight_target_pool_footprint_square : petits socles carrés (BASE_SIZE=1) aux mêmes positions → hors EZ.

        min_distance(fp(5,10), fp(16,10)) = 11 > engagement_zone(10) → hors EZ.
        """
        unit_a = {**_unit(1, 1, 5, 10), "BASE_SIZE": 1, "BASE_SHAPE": "square"}
        unit_b = {**_unit(2, 2, 16, 10), "BASE_SIZE": 1, "BASE_SHAPE": "square"}
        gs = _make_game_state([unit_a, unit_b], current_player=1)
        targets = _fight_build_valid_target_pool(gs, unit_a)
        assert "2" not in targets, "small square-base enemy at distance 11 must not be in fight target pool"
