"""Tests unitaires — détermination du gagnant.

Couvre : GameStateManager.determine_winner_with_method() en isolation
ET le chemin turn_limit via W40KEngine.step().
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.game_state import GameStateManager
from engine.phase_handlers.shared_utils import build_units_cache
from engine.w40k_core import W40KEngine
from engine.reward_calculator import RewardCalculator


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _raw_unit(uid: int, player: int, value: int = 100) -> Dict[str, Any]:
    return {"id": uid, "player": player, "col": uid, "row": 0,
            "HP_CUR": 3, "HP_MAX": 3, "VALUE": value, "OC": 1,
            "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
            "RNG_WEAPONS": [], "CC_WEAPONS": [], "UNIT_RULES": [],
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


def _sm() -> GameStateManager:
    return GameStateManager({})


# ─────────────────────────────────────────────────────────────────────────────
# Tests — determine_winner_with_method en isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinnerWithMethod:

    def test_returns_tuple_of_two(self):
        """winner_tuple : retourne bien un tuple de 2 éléments."""
        result = _sm().determine_winner_with_method(_make_gs(3, 1))
        assert isinstance(result, tuple) and len(result) == 2

    def test_winner_is_1_when_p1_more_vp(self):
        """winner_p1_vp : p1 VP > p2 VP → winner=1."""
        winner, _ = _sm().determine_winner_with_method(_make_gs(3, 1))
        assert winner == 1

    def test_winner_is_2_when_p2_more_vp(self):
        """winner_p2_vp : p2 VP > p1 VP → winner=2."""
        winner, _ = _sm().determine_winner_with_method(_make_gs(1, 5))
        assert winner == 2

    def test_win_method_objectives_when_vp_differ(self):
        """winner_method_obj : win_method='objectives' quand VP diffèrent."""
        _, method = _sm().determine_winner_with_method(_make_gs(3, 1))
        assert method == "objectives"

    def test_returns_none_none_when_game_ongoing(self):
        """winner_ongoing : turn_limit_reached=False → (None, None)."""
        result = _sm().determine_winner_with_method(
            _make_gs(3, 1, turn_limit_reached=False))
        assert result == (None, None)

    def test_p1_wins_tiebreaker_by_value(self):
        """winner_tie_p1 : VP égaux, p1_value > p2_value → winner=1, method=value_tiebreaker."""
        winner, method = _sm().determine_winner_with_method(
            _make_gs(2, 2, p1_value=200, p2_value=100))
        assert winner == 1
        assert method == "value_tiebreaker"

    def test_p2_wins_tiebreaker_by_value(self):
        """winner_tie_p2 : VP égaux, p2_value > p1_value → winner=2, method=value_tiebreaker."""
        winner, method = _sm().determine_winner_with_method(
            _make_gs(2, 2, p1_value=100, p2_value=200))
        assert winner == 2
        assert method == "value_tiebreaker"

    def test_draw_when_equal_vp_and_equal_value(self):
        """winner_draw : VP et VALUE égaux → (-1, 'draw')."""
        winner, method = _sm().determine_winner_with_method(
            _make_gs(2, 2, p1_value=100, p2_value=100))
        assert winner == -1
        assert method == "draw"

    def test_win_method_is_non_empty_string_when_terminated(self):
        """winner_method_str : win_method est une str non-vide quand terminé."""
        _, method = _sm().determine_winner_with_method(_make_gs(3, 1))
        assert isinstance(method, str) and len(method) > 0

    def test_winner_type_is_int_when_terminated(self):
        """winner_type : winner est int (pas None) quand terminé."""
        winner, _ = _sm().determine_winner_with_method(_make_gs(3, 1))
        assert isinstance(winner, int)


# ─────────────────────────────────────────────────────────────────────────────
# W40KEngine helpers
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {"id": uid, "player": player, "col": col, "row": row,
            "unitType": "T", "DISPLAY_NAME": f"U{uid}",
            "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
            "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
            "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
            "UNIT_RULES": [], "UNIT_KEYWORDS": [],
            "LD": 7, "OC": 1, "VALUE": 100, "ICON": "t",
            "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
            "BASE_SHAPE": "round", "BASE_SIZE": 1}


def _minimal_config() -> Dict[str, Any]:
    obs = {"perception_radius": 25, "max_nearby_units": 10,
           "max_valid_targets": 5, "obs_size": 50, "action_space_size": 31}
    return {
        "board": {"default": {"cols": 15, "rows": 13, "hex_radius": 1.0,
                               "margin": 0.0, "wall_hexes": [],
                               "objectives": [{"id": "obj1", "name": "Alpha",
                                               "hexes": [[5, 5]]}],
                               "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "max_base_size_hex": 35},
        "charge": {"charge_max_distance": 12},
        "pve_mode": False,
        "observation_params": obs,
        "training_config": {"observation_params": obs, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, 3, 3), _unit_cfg(2, 2, 10, 10)],
    }


@pytest.fixture(autouse=True)
def mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(W40KEngine, "_build_observation", lambda self: np.zeros(50))
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)


def _make_engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=_minimal_config())


# ─────────────────────────────────────────────────────────────────────────────
# Tests — chemin turn_limit via W40KEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestTurnLimitPath:

    def _reach_turn_limit(self, eng: W40KEngine) -> tuple:
        """Force turn au-delà de max_turns_per_episode (3) et step."""
        eng.reset()
        eng.game_state["turn"] = 4
        eng.game_state["turn_limit_reached"] = False
        return eng.step(0)

    def test_turn_limit_sets_game_over(self):
        """tl_gameover : game_over=True quand turn_limit atteint."""
        eng = _make_engine()
        _, _, terminated, _, _ = self._reach_turn_limit(eng)
        assert terminated is True
        assert eng.game_state.get("game_over") is True

    def test_turn_limit_sets_turn_limit_reached(self):
        """tl_flag : turn_limit_reached=True quand terminé par turn_limit."""
        eng = _make_engine()
        self._reach_turn_limit(eng)
        assert eng.game_state.get("turn_limit_reached") is True

    def test_winner_and_method_available_after_termination(self):
        """tl_winner : _determine_winner_with_method() retourne (int, str) non-None."""
        eng = _make_engine()
        self._reach_turn_limit(eng)
        winner, method = eng._determine_winner_with_method()
        assert winner in {1, 2, -1}
        assert isinstance(method, str) and len(method) > 0
