"""Tests unitaires — charge_handlers : phase_start, _has_valid_charge_target, pool builder."""

from __future__ import annotations

from typing import Any, Dict, List, cast

import pytest

from engine.phase_handlers.charge_handlers import (
    charge_phase_start,
    _has_valid_charge_target,
    charge_build_valid_destinations_pool,
)
from engine.phase_handlers.shared_utils import build_units_cache


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
    }


def _config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "max_base_size_hex": 35,
        },
        "charge": {
            "charge_max_distance": 12,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _make_gs(units: List[Dict[str, Any]], current_player: int = 1) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "shoot",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_advanced": set(),
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# charge_phase_start
# ─────────────────────────────────────────────────────────────────────────────

class TestChargePhaseStart:
    def _mock_pool(self, pool_content: List[str]):
        """Retourne un lambda pour monkeypatching charge_build_activation_pool."""
        def _mock(gs: Dict[str, Any]) -> None:
            gs["charge_activation_pool"] = pool_content
        return _mock

    def test_phase_set_to_charge(self, monkeypatch):
        """charge_start_phase : phase devient 'charge'."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        charge_phase_start(gs)
        assert gs["phase"] == "charge"

    def test_valid_destinations_pool_reset(self, monkeypatch):
        """charge_start_dest_reset : valid_charge_destinations_pool vidé."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        gs["valid_charge_destinations_pool"] = [(1, 2), (3, 4)]
        charge_phase_start(gs)
        assert gs["valid_charge_destinations_pool"] == []

    def test_active_charge_unit_set_to_none(self, monkeypatch):
        """charge_start_active_reset : active_charge_unit = None."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        gs["active_charge_unit"] = "1"
        charge_phase_start(gs)
        assert gs["active_charge_unit"] is None

    def test_charge_roll_values_initialized_empty(self, monkeypatch):
        """charge_start_roll_init : charge_roll_values = {}."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        charge_phase_start(gs)
        assert gs["charge_roll_values"] == {}

    def test_pending_charge_targets_reset(self, monkeypatch):
        """charge_start_pending_reset : pending_charge_targets = []."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        gs["pending_charge_targets"] = [{"id": "2"}]
        charge_phase_start(gs)
        assert gs["pending_charge_targets"] == []

    def test_enemy_adjacent_hexes_built(self, monkeypatch):
        """charge_start_adj : enemy_adjacent_hexes_player_1 construit au démarrage."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        charge_phase_start(gs)
        assert "enemy_adjacent_hexes_player_1" in gs

    def test_nonempty_pool_returns_phase_initialized_true(self, monkeypatch):
        """charge_start_ok : pool non vide → result["phase_initialized"]=True."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        result = charge_phase_start(gs)
        assert result.get("phase_initialized") is True
        assert result.get("phase_complete") is False

    def test_empty_pool_calls_charge_phase_end(self, monkeypatch):
        """charge_start_empty_pool : pool vide → charge_phase_end appelé → phase_complete."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool([]),
        )
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_phase_end",
            lambda gs: {"phase_complete": True, "next_phase": "fight"},
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_gs(units)
        result = charge_phase_start(gs)
        assert result.get("phase_complete") is True

    def test_eligible_count_in_result(self, monkeypatch):
        """charge_start_count : eligible_units dans le résultat."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
            self._mock_pool(["1", "2"]),
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 8, 10), _unit(3, 2, 20, 10)]
        gs = _make_gs(units)
        result = charge_phase_start(gs)
        assert result.get("eligible_units") == 2


# ─────────────────────────────────────────────────────────────────────────────
# _has_valid_charge_target
# ─────────────────────────────────────────────────────────────────────────────

class TestHasValidChargeTarget:
    # Depuis Étape 5, la branche BFS/pool de _has_valid_charge_target n'existe plus que pour
    # le gym/hex (distance_metric["charge_gym"]="hex"). En PvP/euclidien, l'éligibilité est un
    # pré-gate 12" ligne droite (ranged_in_range), sans pool ni BFS. Ces 3 tests ciblent la
    # branche BFS → forcer gym_training_mode pour l'exercer réellement (cf. test_charge_eligibility
    # pour la couverture euclidienne).
    def test_nonempty_bfs_returns_true(self, monkeypatch):
        """charge_target_yes (gym/hex) : BFS trouve au moins une destination → True."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_valid_destinations_pool",
            lambda gs, uid, roll, **kwargs: [(5, 11)],
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 8, 10)]
        gs = _make_gs(units)
        gs["gym_training_mode"] = True
        assert _has_valid_charge_target(gs, units[0]) is True

    def test_empty_bfs_returns_false(self, monkeypatch):
        """charge_target_no (gym/hex) : ennemi à portée mais BFS vide → False."""
        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_valid_destinations_pool",
            lambda gs, uid, roll, **kwargs: [],
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 8, 10)]
        gs = _make_gs(units)
        gs["gym_training_mode"] = True
        assert _has_valid_charge_target(gs, units[0]) is False

    def test_bfs_exception_returns_false(self, monkeypatch):
        """charge_target_err (gym/hex) : exception dans BFS → False (résilience)."""
        def raise_err(*args, **kwargs):
            raise RuntimeError("BFS failure")

        monkeypatch.setattr(
            "engine.phase_handlers.charge_handlers.charge_build_valid_destinations_pool",
            raise_err,
        )
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 8, 10)]
        gs = _make_gs(units)
        gs["gym_training_mode"] = True
        assert _has_valid_charge_target(gs, units[0]) is False


# ─────────────────────────────────────────────────────────────────────────────
# charge_build_valid_destinations_pool (cas simples sans mock)
# ─────────────────────────────────────────────────────────────────────────────

class TestChargeBuildValidDestinationsPool:
    def _make_pool_gs(self, units):
        gs = _make_gs(units)
        gs["_charge_dest_bfs_cache"] = {}
        gs["_charge_fp_offset_pair_cache"] = {}
        return gs

    def test_unit_not_found_returns_empty(self):
        """charge_pool_no_unit : unité inconnue → pool vide."""
        units = [_unit(1, 1, 5, 10)]
        gs = self._make_pool_gs(units)
        result = charge_build_valid_destinations_pool(gs, cast(str, 99), 12)
        assert result == []

    def test_no_enemies_returns_empty(self):
        """charge_pool_no_enemies : aucun ennemi → pool vide."""
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 8, 10)]  # both player 1
        gs = self._make_pool_gs(units)
        result = charge_build_valid_destinations_pool(gs, cast(str, 1), 12)
        assert result == []

    def test_enemy_far_beyond_roll_returns_empty(self):
        """charge_pool_oob : ennemi très loin + roll=2 → pool vide."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 24, 10)]  # far right of 25-col board
        gs = self._make_pool_gs(units)
        result = charge_build_valid_destinations_pool(gs, cast(str, 1), 2)
        assert result == []

    def test_close_enemy_large_roll_nonempty_pool(self):
        """charge_pool_hit : ennemi proche + roll=12 → destinations valides trouvées."""
        # Charger at (5,10), enemy at (9,10) — distance ~4 hexes, roll=12 ample
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 9, 10)]
        gs = self._make_pool_gs(units)
        result = charge_build_valid_destinations_pool(gs, cast(str, 1), 12)
        assert len(result) > 0

    def test_result_is_list_of_tuples(self):
        """charge_pool_type : résultat est une liste de tuples (col, row)."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 9, 10)]
        gs = self._make_pool_gs(units)
        result = charge_build_valid_destinations_pool(gs, cast(str, 1), 12)
        if result:
            assert all(isinstance(d, tuple) and len(d) == 2 for d in result)
