"""Bloc 0 — Fondations V11 de la phase de combat (Documentation/phase_fight_v11.md).

Tests unitaires des helpers/primitives ADDITIFS (non branchés sur le flux V10) :
- is_fights_first (grant 24.13 via charge / units_charged, 11.04)
- fight_ensure_v11_state (sets de suivi)
- fight_compute_engaged_snapshot (snapshot engaged_at_fight_step_start, 12.04/12.06)
- pile_in_targets_within_range / pile_in_select_targets_12_03 (BEFORE MOVING 12.03)
- pile_in_move_destinations_12_03 (WHILE/AFTER MOVING, contraintes dures 12.03)

Plateau single-hex (engagement_zone=1, scale=1) : « engagé » = distance empreinte ≤ 1,
« collé » = contact à distance 1 (identiques quand ez=1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from engine.phase_handlers.fight_handlers import (
    is_fights_first,
    fight_ensure_v11_state,
    fight_compute_engaged_snapshot,
    pile_in_targets_within_range,
    pile_in_select_targets_12_03,
    pile_in_move_destinations_12_03,
)


def _make_gs(
    units: List[Dict[str, Any]],
    *,
    scale: int = 1,
    board_cols: int = 20,
    board_rows: int = 20,
    units_charged: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Construit un game_state single-hex minimal cohérent (units + units_cache)."""
    units_cache: Dict[str, Any] = {}
    norm_units: List[Dict[str, Any]] = []
    for u in units:
        uid = str(u["id"])
        full = {
            "id": uid,
            "player": u["player"],
            "col": u["col"],
            "row": u["row"],
            "BASE_SIZE": 1,
            "BASE_SHAPE": "round",
            "orientation": 0,
            "HP_CUR": u.get("HP_CUR", 1),
            "HP_MAX": u.get("HP_MAX", 1),
        }
        norm_units.append(full)
        units_cache[uid] = {
            "col": u["col"],
            "row": u["row"],
            "player": u["player"],
            "BASE_SIZE": 1,
            "BASE_SHAPE": "round",
            "orientation": 0,
            "HP_CUR": u.get("HP_CUR", 1),
        }
    gs: Dict[str, Any] = {
        "inches_to_subhex": scale,
        "board_cols": board_cols,
        "board_rows": board_rows,
        "config": {"game_rules": {
            "engagement_zone": 1,
            "pile_in_target_range": 5,
            "consolidation_trigger_range": 3,
        }},
        "units": norm_units,
        "units_cache": units_cache,
        "wall_hexes": set(),
        "units_charged": set(units_charged or []),
    }
    return gs


def _unit(gs: Dict[str, Any], uid: str) -> Dict[str, Any]:
    for u in gs["units"]:
        if str(u["id"]) == uid:
            return u
    raise KeyError(uid)


# --------------------------------------------------------------------- is_fights_first

class TestIsFightsFirst:
    def test_charged_unit_is_fights_first(self):
        gs = _make_gs([{"id": "u1", "player": 1, "col": 5, "row": 5}], units_charged=["u1"])
        assert is_fights_first(_unit(gs, "u1"), gs) is True

    def test_non_charged_unit_is_not_fights_first(self):
        gs = _make_gs([{"id": "u1", "player": 1, "col": 5, "row": 5}], units_charged=[])
        assert is_fights_first(_unit(gs, "u1"), gs) is False

    def test_missing_units_charged_raises(self):
        gs = _make_gs([{"id": "u1", "player": 1, "col": 5, "row": 5}])
        del gs["units_charged"]
        with pytest.raises(KeyError):
            is_fights_first(_unit(gs, "u1"), gs)


# --------------------------------------------------------------------- fight_ensure_v11_state

class TestEnsureV11State:
    def test_creates_sets(self):
        gs = _make_gs([{"id": "u1", "player": 1, "col": 5, "row": 5}])
        fight_ensure_v11_state(gs)
        assert gs["units_selected_to_fight"] == set()
        assert gs["pile_in_done"] == set()
        assert gs["consolidation_done"] == set()

    def test_idempotent_preserves_existing(self):
        gs = _make_gs([{"id": "u1", "player": 1, "col": 5, "row": 5}])
        gs["units_selected_to_fight"] = {"u1"}
        fight_ensure_v11_state(gs)
        assert gs["units_selected_to_fight"] == {"u1"}


# --------------------------------------------------------------------- snapshot

class TestEngagedSnapshot:
    def test_engaged_true_far_false(self):
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},   # engagé avec e1 (dist 1)
            {"id": "e1", "player": 2, "col": 5, "row": 4},
            {"id": "u2", "player": 1, "col": 15, "row": 15},  # loin
        ])
        snap = fight_compute_engaged_snapshot(gs)
        assert snap["u1"] is True
        assert snap["e1"] is True
        assert snap["u2"] is False


# --------------------------------------------------------------------- targets within range / selection

class TestPileInTargetSelection:
    def test_within_range_filters_by_5_inches(self):
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},
            {"id": "e_near", "player": 2, "col": 5, "row": 9},   # dist 4 ≤ 5
            {"id": "e_far", "player": 2, "col": 5, "row": 12},   # dist 7 > 5
        ])
        within = set(pile_in_targets_within_range(gs, _unit(gs, "u1")))
        assert "e_near" in within
        assert "e_far" not in within

    def test_engaged_unit_returns_all_engaged(self):
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},  # engagé
            {"id": "e2", "player": 2, "col": 6, "row": 5},  # engagé
        ])
        targets = set(pile_in_select_targets_12_03(gs, _unit(gs, "u1")))
        assert targets == {"e1", "e2"}

    def test_unengaged_requires_chosen_targets(self):
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 9},  # dist 4, non engagé
        ])
        with pytest.raises(ValueError):
            pile_in_select_targets_12_03(gs, _unit(gs, "u1"))

    def test_unengaged_rejects_out_of_range_choice(self):
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},
            {"id": "e_far", "player": 2, "col": 5, "row": 12},  # dist 7 > 5
        ])
        with pytest.raises(ValueError):
            pile_in_select_targets_12_03(gs, _unit(gs, "u1"), chosen_target_ids=["e_far"])

    def test_unengaged_accepts_in_range_choice(self):
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},
            {"id": "e_near", "player": 2, "col": 5, "row": 9},  # dist 4 ≤ 5
        ])
        assert pile_in_select_targets_12_03(
            gs, _unit(gs, "u1"), chosen_target_ids=["e_near"]
        ) == ["e_near"]


# --------------------------------------------------------------------- destinations (12.03 hard constraints)

class TestPileInDestinations:
    def test_glued_unit_cannot_move(self):
        """Figurine en contact socle (collée) → aucune destination."""
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},  # dist 1 = collé
        ])
        dests = pile_in_move_destinations_12_03(gs, _unit(gs, "u1"), ["e1"])
        assert dests == []

    def test_reachable_anchors_all_end_engaged_and_closer(self):
        """Unité à 3 hex de l'ennemi : destinations = ancres engagées (dist ≤1) et plus proches."""
        from engine.hex_utils import min_distance_between_sets
        gs = _make_gs([
            {"id": "u1", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 2},  # dist 3
        ])
        unit = _unit(gs, "u1")
        dests = pile_in_move_destinations_12_03(gs, unit, ["e1"])
        assert dests, "au moins une ancre de pile-in attendue"
        enemy_fp = {(5, 2)}
        for ac, ar in dests:
            # AFTER : engagé (ez=1 → distance ≤ 1)
            assert min_distance_between_sets({(ac, ar)}, enemy_fp, max_distance=1) <= 1
            # WHILE : strictement plus proche que la distance de départ (3)
            assert min_distance_between_sets({(ac, ar)}, enemy_fp) < 3

    def test_empty_targets_raises(self):
        gs = _make_gs([{"id": "u1", "player": 1, "col": 5, "row": 5}])
        with pytest.raises(ValueError):
            pile_in_move_destinations_12_03(gs, _unit(gs, "u1"), [])
