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
from tests._state_invariants import turn_state_invariants


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
            # Données verticales (03.04) : une entrée-cache réelle les porte TOUJOURS
            # (build_units_cache). Sans elles l'engagement 3D lève « câblage incomplet » —
            # c'est un défaut de fixture, pas une tolérance à ajouter au moteur.
            "occupied_hexes_by_model": {f"{uid}#0": (u["col"], u["row"])},
            "floor_height_by_model": {f"{uid}#0": 0.0},
        }
    return {**turn_state_invariants(),
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


class TestFreezeNewFoes:
    def test_selector_is_opponent_of_consolidating_unit_owner(self):
        """12.08 AFTER : « YOUR OPPONENT must select each of those units ». En seconde moitié de
        12.07 c'est l'unité du joueur NON actif qui consolide : son adversaire EST le joueur
        courant. L'ancien calcul `3 - current_player` désignait alors le mauvais joueur."""
        from engine.phase_handlers.fight_handlers import fight_v11_consolidation_freeze_new_foes

        gs = _make_gs([
            {"id": "a", "player": 2, "col": 5, "row": 5},
            {"id": "e1", "player": 1, "col": 5, "row": 4},  # engagé, non sélectionné
        ])
        gs["current_player"] = 1
        assert fight_v11_consolidation_freeze_new_foes(gs, _u(gs, "a")) == ["e1"]
        assert gs["consolidation_new_foes_pending"] == ["e1"]
        assert gs["consolidation_new_foes_for_unit"] == "a"
        assert gs["consolidation_new_foes_selector"] == 1

    def test_no_new_foe_poses_no_key(self):
        from engine.phase_handlers.fight_handlers import fight_v11_consolidation_freeze_new_foes

        gs = _make_gs([
            {"id": "a", "player": 1, "col": 5, "row": 5},
            {"id": "e1", "player": 2, "col": 5, "row": 4},
        ], units_selected_to_fight=["e1"])
        gs["current_player"] = 1
        assert fight_v11_consolidation_freeze_new_foes(gs, _u(gs, "a")) == []
        assert "consolidation_new_foes_pending" not in gs
