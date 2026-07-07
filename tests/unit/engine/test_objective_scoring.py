"""Tests unitaires — apply_primary_objective_scoring.

Couvre les VP, les conditions de victoire, la déduplication de scoring par tour,
et les conditions: control_at_least_one, control_at_least_two, control_more_than_opponent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from engine.game_state import GameStateManager
from engine.phase_handlers.shared_utils import build_units_cache
from engine.combat_utils import normalize_coordinates


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_manager() -> GameStateManager:
    config = {
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }
    return GameStateManager(config, unit_registry=None)


def _primary_objective(
    obj_id: str = "obj1",
    start_turn: int = 2,
    max_points: int = 5,
    default_phase: str = "command",
    round5_phase: str = "fight",
    conditions: Optional[List[Dict]] = None,
    control_method: str = "secured",
) -> Dict[str, Any]:
    if conditions is None:
        conditions = [
            {"condition": "control_at_least_one", "points": 1},
            {"condition": "control_more_than_opponent", "points": 2},
        ]
    return {
        "id": obj_id,
        "scoring": {
            "start_turn": start_turn,
            "max_points_per_turn": max_points,
            "rules": conditions,
        },
        "timing": {
            "default_phase": default_phase,
            "round5_second_player_phase": round5_phase,
        },
        "control": {
            "method": "oc_sum_greater",
            "control_method": control_method,
            "tie_behavior": "no_control",
        },
        "objective_hexes": [[5, 5]],
    }


def _unit(uid: int, player: int, col: int, row: int, oc: int = 1) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "OC": oc,
        "MOVE": 6,
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
    }


def _make_gs(
    units: List[Dict[str, Any]],
    turn: int = 2,
    current_player: int = 1,
    primary_objective=None,
) -> Dict[str, Any]:
    objectives = [{"id": "obj1", "name": "Alpha", "hexes": [[5, 5]]}]
    gs: Dict[str, Any] = {
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "turn": turn,
        "current_player": current_player,
        "phase": "command",
        "victory_points": {1: 0, 2: 0},
        "primary_objective": primary_objective,
        "primary_objective_scored_turns": set(),
        "objective_rewarded_turns": set(),
        "objective_controllers": {},
        "objectives": objectives,
        "board_cols": 15,
        "board_rows": 13,
        "wall_hexes": set(),
        "turn_limit_reached": False,
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Tests — guard clauses
# ─────────────────────────────────────────────────────────────────────────────

class TestObjectiveScoringGuards:

    def test_none_primary_objective_returns_immediately(self):
        """obj_none : primary_objective=None → aucun VP ajouté."""
        mgr = _make_manager()
        units = [_unit(1, 1, 5, 5)]
        gs = _make_gs(units, turn=2, primary_objective=None)

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"] == {1: 0, 2: 0}

    def test_before_start_turn_no_scoring(self):
        """obj_before_start : turn < start_turn → aucun VP ajouté."""
        mgr = _make_manager()
        obj = _primary_objective(start_turn=2)
        units = [_unit(1, 1, 5, 5)]
        gs = _make_gs(units, turn=1, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == 0

    def test_wrong_phase_no_scoring(self):
        """obj_wrong_phase : scoring_phase != expected_phase → aucun VP."""
        mgr = _make_manager()
        obj = _primary_objective(default_phase="command")
        units = [_unit(1, 1, 5, 5)]
        gs = _make_gs(units, turn=2, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "fight")  # wrong phase

        assert gs["victory_points"][1] == 0

    def test_duplicate_scoring_blocked(self):
        """obj_dedup : scoring déjà effectué ce tour → aucun VP supplémentaire."""
        mgr = _make_manager()
        obj = _primary_objective()
        units = [_unit(1, 1, 5, 5)]
        gs = _make_gs(units, turn=2, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "command")
        vp_after_first = gs["victory_points"][1]

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == vp_after_first


# ─────────────────────────────────────────────────────────────────────────────
# Tests — conditions VP
# ─────────────────────────────────────────────────────────────────────────────

class TestObjectiveScoringConditions:

    def test_control_at_least_one_grants_vp(self):
        """obj_control_one : joueur 1 contrôle 1 objectif → VP accordés."""
        mgr = _make_manager()
        obj = _primary_objective(
            conditions=[{"condition": "control_at_least_one", "points": 3}]
        )
        units = [_unit(1, 1, 5, 5)]  # on objective hex [5,5]
        gs = _make_gs(units, turn=2, current_player=1, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == 3

    def test_control_at_least_one_no_unit_on_obj(self):
        """obj_control_one_fail : aucune unité sur objectif → 0 VP."""
        mgr = _make_manager()
        obj = _primary_objective(
            conditions=[{"condition": "control_at_least_one", "points": 3}]
        )
        units = [_unit(1, 1, 0, 0)]  # NOT on objective
        gs = _make_gs(units, turn=2, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == 0

    def test_control_more_than_opponent_grants_vp(self):
        """obj_control_more : joueur 1 contrôle plus → VP accordés."""
        mgr = _make_manager()
        obj = _primary_objective(
            conditions=[{"condition": "control_more_than_opponent", "points": 2}]
        )
        # Joueur 1 sur objectif, joueur 2 absent
        units = [_unit(1, 1, 5, 5), _unit(2, 2, 0, 0)]
        gs = _make_gs(units, turn=2, current_player=1, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == 2

    def test_control_more_than_opponent_tied_no_vp(self):
        """obj_control_tied : égalité OC → 0 VP pour condition 'more_than'."""
        mgr = _make_manager()
        obj = _primary_objective(
            conditions=[{"condition": "control_more_than_opponent", "points": 2}]
        )
        # OC=1 chacun sur le même objectif → égalité
        units = [_unit(1, 1, 5, 5), _unit(2, 2, 5, 5)]
        gs = _make_gs(units, turn=2, current_player=1, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == 0

    def test_max_points_per_turn_cap_applied(self):
        """obj_cap : points cumulés > max_points_per_turn → cap appliqué."""
        mgr = _make_manager()
        obj = _primary_objective(
            max_points=3,
            conditions=[
                {"condition": "control_at_least_one", "points": 2},
                {"condition": "control_more_than_opponent", "points": 2},
            ]
        )
        units = [_unit(1, 1, 5, 5), _unit(2, 2, 0, 0)]
        gs = _make_gs(units, turn=2, current_player=1, primary_objective=obj)

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == 3  # capped at 3

    def test_round5_player2_uses_special_phase(self):
        """obj_r5_p2 : tour 5 joueur 2 → expected_phase = round5_second_player_phase."""
        mgr = _make_manager()
        obj = _primary_objective(default_phase="command", round5_phase="fight")
        units = [_unit(2, 2, 5, 5)]
        gs = _make_gs(units, turn=5, current_player=2, primary_objective=obj)

        # "command" phase → no scoring car expected_phase="fight" au tour 5 joueur 2
        mgr.apply_primary_objective_scoring(gs, "command")
        assert gs["victory_points"][2] == 0

        # "fight" phase → scoring
        mgr.apply_primary_objective_scoring(gs, "fight")
        assert gs["victory_points"][2] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests — liste d'objectifs multiples
# ─────────────────────────────────────────────────────────────────────────────

class TestObjectiveScoringList:

    def test_list_of_objectives_scored(self):
        """obj_list : primary_objective liste → chaque objectif scoré."""
        mgr = _make_manager()
        obj1 = _primary_objective(obj_id="obj_a", conditions=[{"condition": "control_at_least_one", "points": 1}])
        obj2 = _primary_objective(obj_id="obj_b", conditions=[{"condition": "control_at_least_one", "points": 2}])
        objectives_list = [obj1, obj2]
        units = [_unit(1, 1, 5, 5)]
        gs = _make_gs(units, turn=2, current_player=1, primary_objective=objectives_list)
        # Ajouter les objectifs dans gs pour que le scoring puisse les trouver
        gs["objectives"] = [
            {"id": "obj_a", "name": "A", "hexes": [[5, 5]]},
            {"id": "obj_b", "name": "B", "hexes": [[5, 5]]},
        ]

        mgr.apply_primary_objective_scoring(gs, "command")

        assert gs["victory_points"][1] == 3  # 1 + 2
