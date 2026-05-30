"""Tests unitaires — GameStateManager en isolation (engine/game_state.py).

Cible les méthodes publiques sans passer par W40KEngine.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.game_state import GameStateManager
from engine.phase_handlers.shared_utils import build_units_cache


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_MINIMAL_CONFIG = {"board": {"default": {"inches_to_subhex": 1}}}

_FULL_UNIT_CFG: Dict[str, Any] = {
    "id": 1, "player": 1, "col": 3, "row": 3,
    "unitType": "T", "DISPLAY_NAME": "TestUnit",
    "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
    "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
    "RNG_WEAPONS": [], "CC_WEAPONS": [],
    "UNIT_RULES": [], "UNIT_KEYWORDS": [],
    "LD": 7, "OC": 1, "VALUE": 100, "ICON": "t",
    "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
    "BASE_SHAPE": "round", "BASE_SIZE": 1,
}


def _sm(config: Dict[str, Any] | None = None) -> GameStateManager:
    return GameStateManager(config or _MINIMAL_CONFIG)


def _raw_unit(uid: int, player: int, value: int = 100) -> Dict[str, Any]:
    return {"id": uid, "player": player, "col": uid, "row": 0,
            "HP_CUR": 3, "HP_MAX": 3, "VALUE": value, "OC": 1,
            "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
            "RNG_WEAPONS": [], "CC_WEAPONS": [],
            "BASE_SHAPE": "round", "BASE_SIZE": 1}


def _make_gs(p1_vp: int, p2_vp: int,
             p1_value: int = 100, p2_value: int = 100,
             turn_limit_reached: bool = True) -> Dict[str, Any]:
    units = [_raw_unit(1, 1, p1_value), _raw_unit(2, 2, p2_value)]
    gs: Dict[str, Any] = {
        "turn_limit_reached": turn_limit_reached,
        "victory_points": {1: p1_vp, 2: p2_vp},
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "config": {"game_rules": {"engagement_zone": 1}},
    }
    build_units_cache(gs)
    return gs


def _make_gs_with_objectives(controller: int | None = None) -> Dict[str, Any]:
    """Game state avec un objectif, pour count_controlled_objectives."""
    units = [_raw_unit(1, 1), _raw_unit(2, 2)]
    gs: Dict[str, Any] = {
        "turn_limit_reached": False,
        "victory_points": {1: 0, 2: 0},
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "config": {"game_rules": {"engagement_zone": 1}},
        "objectives": [{"id": "obj1", "hexes": [[99, 99]]}],  # hexes inoccupés
        "primary_objective": {
            "id": "obj1",
            "control": {
                "method": "oc_sum_greater",
                "control_method": "sticky",
                "tie_behavior": "no_control",
            },
            "scoring": {"start_turn": 1, "max_points_per_turn": 5, "rules": []},
            "timing": {"default_phase": "command", "round5_second_player_phase": "fight"},
        },
        "objective_controllers": {"obj1": controller},
        "primary_objective_scored_turns": set(),
        "turn": 1,
        "current_player": 1,
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Tests — create_unit
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateUnit:

    def test_create_unit_has_hp_cur(self) -> None:
        """sm_create_hp : create_unit() → champ HP_CUR présent."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        assert "HP_CUR" in unit and unit["HP_CUR"] == 3

    def test_create_unit_has_uppercase_stats(self) -> None:
        """sm_create_upper : create_unit() → tous les champs UPPERCASE requis présents."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        for field in ("HP_CUR", "HP_MAX", "MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE",
                      "LD", "OC", "VALUE", "ICON", "ICON_SCALE"):
            assert field in unit, f"Champ manquant : {field}"

    def test_create_unit_identity_fields(self) -> None:
        """sm_create_id : id, player, col, row correctement copiés."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        assert unit["id"] == 1
        assert unit["player"] == 1
        assert unit["col"] == 3
        assert unit["row"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Tests — validate_uppercase_fields
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateUppercaseFields:

    def test_valid_unit_does_not_raise(self) -> None:
        """sm_valid_ok : unité complète → pas d'exception."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        _sm().validate_uppercase_fields(unit)  # should not raise

    def test_missing_field_raises_value_error(self) -> None:
        """sm_valid_miss : champ manquant → ValueError."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        del unit["HP_CUR"]
        with pytest.raises(ValueError, match=r"missing required UPPERCASE field"):
            _sm().validate_uppercase_fields(unit)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — determine_winner / determine_winner_with_method
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinner:

    def test_returns_none_when_not_reached(self) -> None:
        """sm_win_none : turn_limit_reached=False → None."""
        result = _sm().determine_winner(_make_gs(3, 1, turn_limit_reached=False))
        assert result is None

    def test_p1_wins(self) -> None:
        """sm_win_p1 : p1_vp > p2_vp → 1."""
        assert _sm().determine_winner(_make_gs(5, 2)) == 1

    def test_p2_wins(self) -> None:
        """sm_win_p2 : p2_vp > p1_vp → 2."""
        assert _sm().determine_winner(_make_gs(1, 4)) == 2

    def test_draw_returns_minus_1(self) -> None:
        """sm_win_draw : VP et VALUE égaux → -1."""
        assert _sm().determine_winner(_make_gs(2, 2)) == -1


# ─────────────────────────────────────────────────────────────────────────────
# Tests — check_game_over
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckGameOver:

    def test_false_when_turn_limit_not_reached(self) -> None:
        """sm_cgo_false : turn_limit_reached=False → False."""
        gs = {"turn_limit_reached": False}
        assert _sm().check_game_over(gs) is False

    def test_true_when_turn_limit_reached(self) -> None:
        """sm_cgo_true : turn_limit_reached=True → True."""
        gs = {"turn_limit_reached": True}
        assert _sm().check_game_over(gs) is True


# ─────────────────────────────────────────────────────────────────────────────
# Tests — count_controlled_objectives
# ─────────────────────────────────────────────────────────────────────────────

class TestCountControlledObjectives:

    def test_returns_dict_with_both_players(self) -> None:
        """sm_obj_keys : résultat contient bien les clés 1 et 2."""
        gs = _make_gs_with_objectives()
        counts = _sm().count_controlled_objectives(gs)
        assert 1 in counts and 2 in counts

    def test_no_units_on_objective_uncontrolled(self) -> None:
        """sm_obj_empty : objectif sans unité dessus → controller=None → 0 pour les deux."""
        gs = _make_gs_with_objectives(controller=None)
        counts = _sm().count_controlled_objectives(gs)
        assert counts[1] == 0 and counts[2] == 0

    def test_player1_controller_counts_correctly(self) -> None:
        """sm_obj_p1 : objectif sticky déjà contrôlé par p1 → counts[1]=1."""
        gs = _make_gs_with_objectives(controller=1)
        counts = _sm().count_controlled_objectives(gs)
        assert counts[1] == 1
        assert counts[2] == 0
