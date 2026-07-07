"""Tests unitaires — phase command.

Couvre : command_phase_start() en isolation ET via W40KEngine.reset().
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.phase_handlers import command_handlers
from engine.phase_handlers.shared_utils import build_units_cache
from engine.w40k_core import W40KEngine
from engine.reward_calculator import RewardCalculator


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {"id": uid, "player": player, "col": col, "row": row,
            "HP_CUR": 3, "HP_MAX": 3, "VALUE": 100, "OC": 1,
            "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
            "RNG_WEAPONS": [], "CC_WEAPONS": [], "UNIT_RULES": [],
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5}


def _make_cmd_gs() -> Dict[str, Any]:
    units = [_cmd_unit(1, 1, 3, 3), _cmd_unit(2, 2, 10, 10)]
    gs: Dict[str, Any] = {
        "turn": 1,
        "current_player": 1,
        "episode_steps": 0,
        "game_over": False,
        "turn_limit_reached": False,
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "primary_objective": None,
        "objectives": [{"id": "obj1", "hexes": [[5, 5]]}],
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# W40KEngine helpers (same pattern que test_engine_step.py)
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {"id": uid, "player": player, "col": col, "row": row,
            "unitType": "T", "DISPLAY_NAME": f"U{uid}",
            "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
            "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
            "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
            "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
            "UNIT_RULES": [], "UNIT_KEYWORDS": [],
            "LD": 7, "OC": 1, "VALUE": 100, "ICON": "t",
            "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5}


def _minimal_config() -> Dict[str, Any]:
    obs = {"perception_radius": 25, "max_nearby_units": 10,
           "max_valid_targets": 5, "obs_size": 50, "action_space_size": 31}
    return {
        "board": {"default": {"cols": 15, "rows": 13, "hex_radius": 1.0,
                               "margin": 0.0, "wall_hexes": [],
                               "objectives": [{"id": "obj1", "name": "Alpha",
                                               "hexes": [[5, 5]]}],
                               "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
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
# Tests — command_phase_start() en isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestCommandPhaseHandlerIsolation:

    def test_phase_set_to_command(self):
        """cmd_iso_phase : command_phase_start() positionne phase='command' avant cascade."""
        gs = _make_cmd_gs()
        command_handlers.command_phase_start(gs)
        assert gs["phase"] == "command"

    def test_command_activation_pool_is_empty_list(self):
        """cmd_iso_pool : command_activation_pool est [] après command_phase_start."""
        gs = _make_cmd_gs()
        command_handlers.command_phase_start(gs)
        assert gs["command_activation_pool"] == []

    def test_units_moved_reset_to_empty_set(self):
        """cmd_iso_moved : units_moved est set() après command_phase_start."""
        gs = _make_cmd_gs()
        gs["units_moved"] = {"1"}  # pré-polluer
        command_handlers.command_phase_start(gs)
        assert gs["units_moved"] == set()

    def test_units_shot_reset_to_empty_set(self):
        """cmd_iso_shot : units_shot est set() après command_phase_start."""
        gs = _make_cmd_gs()
        gs["units_shot"] = {"1"}
        command_handlers.command_phase_start(gs)
        assert gs["units_shot"] == set()

    def test_units_charged_reset_to_empty_set(self):
        """cmd_iso_charged : units_charged est set() après command_phase_start."""
        gs = _make_cmd_gs()
        gs["units_charged"] = {"2"}
        command_handlers.command_phase_start(gs)
        assert gs["units_charged"] == set()

    def test_units_fought_reset_to_empty_set(self):
        """cmd_iso_fought : units_fought est set() après command_phase_start."""
        gs = _make_cmd_gs()
        gs["units_fought"] = {"1", "2"}
        command_handlers.command_phase_start(gs)
        assert gs["units_fought"] == set()

    def test_return_signals_phase_complete(self):
        """cmd_iso_complete : valeur de retour a phase_complete=True."""
        gs = _make_cmd_gs()
        result = command_handlers.command_phase_start(gs)
        assert result.get("phase_complete") is True

    def test_return_signals_next_phase_move(self):
        """cmd_iso_next : valeur de retour a next_phase='move'."""
        gs = _make_cmd_gs()
        result = command_handlers.command_phase_start(gs)
        assert result.get("next_phase") == "move"


# ─────────────────────────────────────────────────────────────────────────────
# Tests — via W40KEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestCommandPhaseViaEngine:

    def test_after_reset_phase_is_not_command_cascade_advanced(self):
        """cmd_eng_phase : après reset(), la phase cascade a avancé au-delà de 'command'."""
        eng = _make_engine()
        eng.reset()
        # La phase ne doit PAS rester 'command' (pool vide → cascade vers 'move')
        assert eng.game_state["phase"] != "command"

    def test_after_reset_phase_is_move_or_beyond(self):
        """cmd_eng_move : après reset(), la phase est 'move' (ou plus loin si déploiement)."""
        eng = _make_engine()
        eng.reset()
        assert eng.game_state["phase"] in {"move", "shoot", "charge", "fight", "deployment"}

    def test_after_reset_current_player_is_1(self):
        """cmd_eng_player : current_player vaut 1 après reset()."""
        eng = _make_engine()
        eng.reset()
        assert eng.game_state["current_player"] == 1

    def test_after_reset_episode_steps_is_0(self):
        """cmd_eng_steps : episode_steps est 0 après reset()."""
        eng = _make_engine()
        eng.reset()
        assert eng.game_state["episode_steps"] == 0

    def test_after_reset_game_over_is_false(self):
        """cmd_eng_gameover : game_over est False après reset()."""
        eng = _make_engine()
        eng.reset()
        assert eng.game_state["game_over"] is False

    def test_after_reset_tracking_sets_are_empty(self):
        """cmd_eng_sets : sets de suivi sont vides après reset()."""
        eng = _make_engine()
        eng.reset()
        for field in ("units_moved", "units_shot", "units_charged", "units_fought"):
            assert eng.game_state[field] == set(), f"{field} non vide après reset"
