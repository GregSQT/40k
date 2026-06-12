"""Bloc 1/2/5 (orchestration) — Drivers de séquence V11 (PDF 12.01→12.09).

Fonctions ADDITIVES pures (non branchées sur execute_action). Vérifient :
- fight_v11_start : entrée en PILE IN + reset des états de suivi
- transitions (enter_fight_step prend le snapshot ; enter_consolidate)
- fight_v11_grouped_next : ordre actif→adverse, tracking *_done, skip

Plateau single-hex (engagement_zone=1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine.phase_handlers.fight_handlers import (
    fight_v11_start,
    fight_v11_enter_fight_step,
    fight_v11_enter_consolidate,
    fight_v11_grouped_next,
)


def _make_gs(
    units: List[Dict[str, Any]],
    *,
    current_player: int = 1,
    units_charged: Optional[List[str]] = None,
    units_selected_to_fight: Optional[List[str]] = None,
) -> Dict[str, Any]:
    units_cache: Dict[str, Any] = {}
    norm_units: List[Dict[str, Any]] = []
    for u in units:
        uid = str(u["id"])
        norm_units.append({
            "id": uid, "player": u["player"], "col": u["col"], "row": u["row"],
            "BASE_SIZE": 1, "BASE_SHAPE": "round", "orientation": 0, "HP_CUR": 1,
        })
        units_cache[uid] = {
            "col": u["col"], "row": u["row"], "player": u["player"],
            "BASE_SIZE": 1, "BASE_SHAPE": "round", "orientation": 0, "HP_CUR": 1,
        }
    return {
        "inches_to_subhex": 1, "board_cols": 40, "board_rows": 40,
        "config": {"game_rules": {"engagement_zone": 1, "consolidation_trigger_range": 3}},
        "units": norm_units, "units_cache": units_cache, "wall_hexes": set(),
        "current_player": current_player,
        "units_charged": set(units_charged or []),
        "units_selected_to_fight": set(units_selected_to_fight or []),
    }


class TestStartAndTransitions:
    def test_start_enters_pile_in_and_resets(self):
        gs = _make_gs([{"id": "a", "player": 1, "col": 5, "row": 5}], units_charged=["a"])
        gs["units_selected_to_fight"] = {"x"}
        gs["pile_in_done"] = {"y"}
        fight_v11_start(gs)
        assert gs["fight_subphase"] == "pile_in"
        assert gs["units_selected_to_fight"] == set()
        assert gs["pile_in_done"] == set()
        assert gs["consolidation_done"] == set()
        assert gs["fight_step"] is None

    def test_enter_fight_step_takes_snapshot(self):
        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},
            {"id": "e", "player": 2, "col": 5, "row": 4},  # engagé avec a
            {"id": "far", "player": 1, "col": 20, "row": 20},
        ], current_player=1)
        fight_v11_enter_fight_step(gs)
        assert gs["fight_subphase"] == "fight"
        assert gs["fight_step"] == "fights_first"
        assert gs["fight_selector"] == 1
        snap = gs["engaged_at_fight_step_start"]
        assert snap["a"] is True and snap["e"] is True and snap["far"] is False

    def test_enter_consolidate(self):
        gs = _make_gs([{"id": "a", "player": 1, "col": 5, "row": 5}])
        fight_v11_enter_consolidate(gs)
        assert gs["fight_subphase"] == "consolidate"
        assert gs["fight_step"] is None


class TestGroupedNext:
    def test_pile_in_active_first_then_opponent(self):
        gs = _make_gs([
            {"id": "p1", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},  # engagés ensemble
        ], current_player=1)
        gs["pile_in_done"] = set()
        # actif d'abord
        nxt = fight_v11_grouped_next(gs, "pile_in")
        assert nxt is not None
        player, units = nxt
        assert player == 1 and units == ["p1"]
        # p1 traité (skip = done)
        gs["pile_in_done"].add("p1")
        nxt = fight_v11_grouped_next(gs, "pile_in")
        assert nxt is not None
        player, units = nxt
        assert player == 2 and units == ["e1"]
        gs["pile_in_done"].add("e1")
        assert fight_v11_grouped_next(gs, "pile_in") is None

    def test_consolidate_uses_selected_to_fight(self):
        gs = _make_gs([
            {"id": "p1", "player": 1, "col": 5, "row": 5},
            {"id": "p2", "player": 2, "col": 9, "row": 9},
        ], current_player=1, units_selected_to_fight=["p1", "p2"])
        gs["consolidation_done"] = set()
        nxt = fight_v11_grouped_next(gs, "consolidate")
        assert nxt is not None
        player, units = nxt
        assert player == 1 and units == ["p1"]
        gs["consolidation_done"].add("p1")
        nxt = fight_v11_grouped_next(gs, "consolidate")
        assert nxt is not None
        player, units = nxt
        assert player == 2 and units == ["p2"]
        gs["consolidation_done"].add("p2")
        assert fight_v11_grouped_next(gs, "consolidate") is None

    def test_pile_in_skips_ineligible(self):
        gs = _make_gs([
            {"id": "idle", "player": 1, "col": 20, "row": 20},  # ni engagé ni chargé
        ], current_player=1)
        gs["pile_in_done"] = set()
        assert fight_v11_grouped_next(gs, "pile_in") is None
