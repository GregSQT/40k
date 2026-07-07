"""Bloc 5 (cœur) — Cascade des modes de consolidation V11 (PDF 12.08).

Fonctions ADDITIVES pures. Plateau single-hex (engagement_zone=1, scale=1,
consolidation_trigger_range=3) : engagé = dist ≤ 1 ; gate 3 modes = dist ≤ 3.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine.phase_handlers.fight_handlers import (
    fight_v11_consolidation_mode,
    fight_v11_engaging_triggered_unit_ids,
)


def _make_gs(
    units: List[Dict[str, Any]],
    *,
    objectives: Optional[List[Dict[str, Any]]] = None,
    units_selected_to_fight: Optional[List[str]] = None,
) -> Dict[str, Any]:
    units_cache: Dict[str, Any] = {}
    norm_units: List[Dict[str, Any]] = []
    for u in units:
        uid = str(u["id"])
        norm_units.append({
            "id": uid, "player": u["player"], "col": u["col"], "row": u["row"],
            "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round", "orientation": 0, "HP_CUR": 1,
        })
        units_cache[uid] = {
            "col": u["col"], "row": u["row"], "player": u["player"],
            "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round", "orientation": 0, "HP_CUR": 1,
        }
    return {
        "inches_to_subhex": 1, "board_cols": 40, "board_rows": 40,
        "config": {"game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "consolidation_trigger_range": 3}},
        "units": norm_units, "units_cache": units_cache, "wall_hexes": set(),
        "objectives": objectives or [],
        "units_selected_to_fight": set(units_selected_to_fight or []),
    }


def _u(gs, uid):
    for u in gs["units"]:
        if str(u["id"]) == uid:
            return u
    raise KeyError(uid)


class TestConsolidationModeCascade:
    def test_ongoing_when_engaged(self):
        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},
            {"id": "e", "player": 2, "col": 5, "row": 4},  # dist 1 = engagé
        ])
        assert fight_v11_consolidation_mode(gs, _u(gs, "a")) == "ongoing"

    def test_engaging_when_enemy_within_3_not_engaged(self):
        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},
            {"id": "e", "player": 2, "col": 5, "row": 7},  # dist 2 : non engagé, dans 3
        ])
        assert fight_v11_consolidation_mode(gs, _u(gs, "a")) == "engaging"

    def test_objective_when_only_objective_within_3(self):
        gs = _make_gs(
            [
                {"id": "a", "player": 1, "col": 5, "row": 5},
                {"id": "e", "player": 2, "col": 30, "row": 30},  # loin
            ],
            objectives=[{"id": 1, "name": "O", "hexes": [[5, 7]]}],  # dist 2 ≤ 3
        )
        assert fight_v11_consolidation_mode(gs, _u(gs, "a")) == "objective"

    def test_none_when_nothing_in_range(self):
        gs = _make_gs(
            [
                {"id": "a", "player": 1, "col": 5, "row": 5},
                {"id": "e", "player": 2, "col": 30, "row": 30},
            ],
            objectives=[{"id": 1, "name": "O", "hexes": [[30, 5]]}],  # dist >3
        )
        assert fight_v11_consolidation_mode(gs, _u(gs, "a")) is None

    def test_engaging_takes_priority_over_objective(self):
        gs = _make_gs(
            [
                {"id": "a", "player": 1, "col": 5, "row": 5},
                {"id": "e", "player": 2, "col": 5, "row": 7},  # enemy dans 3
            ],
            objectives=[{"id": 1, "name": "O", "hexes": [[5, 8]]}],  # objectif aussi dans 3
        )
        assert fight_v11_consolidation_mode(gs, _u(gs, "a")) == "engaging"


class TestEngagingTriggeredUnits:
    def test_engaged_enemies_not_yet_selected_are_triggered(self):
        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},  # engagé, non sélectionné
            {"id": "e2", "player": 2, "col": 6, "row": 5},  # engagé, déjà sélectionné
        ], units_selected_to_fight=["e2"])
        trig = fight_v11_engaging_triggered_unit_ids(gs, _u(gs, "a"))
        assert "e1" in trig
        assert "e2" not in trig

    def test_no_trigger_when_all_selected(self):
        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},
        ], units_selected_to_fight=["e1"])
        assert fight_v11_engaging_triggered_unit_ids(gs, _u(gs, "a")) == []
