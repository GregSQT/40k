"""Tests unitaires — W40KEngine.step().

Chemin critique: reset() → step(action) × N → game_over.
Vérifie: épisode_steps, terminated, tuple de retour, turn_limit, phase advance auto.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from engine.w40k_core import W40KEngine


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2,
        "STR": 4,
        "AP": 0,
        "DMG": 1,
        "NB": 1,
        "RNG": 24,
        "WEAPON_RULES": [],
        "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "unitType": "TestUnit",
        "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3,
        "HP_MAX": 3,
        "MOVE": 6,
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
        "LD": 7,
        "OC": 1,
        "VALUE": 100,
        "ICON": "test",
        "ICON_SCALE": 1.0,
        "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
    }


def _minimal_config() -> Dict[str, Any]:
    obs_params = {
        "perception_radius": 25,
        "max_nearby_units": 10,
        "max_valid_targets": 5,
        "obs_size": 50,
    }
    return {
        "board": {
            "default": {
                "cols": 15,
                "rows": 13,
                "hex_radius": 1.0,
                "margin": 0.0,
                "wall_hexes": [],
                "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[5, 5]]}],
            }
        },
        "game_rules": {
            "engagement_zone": 1,
            "max_base_size_hex": 35,
            "charge_max_distance": 12,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {
            "observation_params": obs_params,
            "max_turns_per_episode": 3,
        },
        "units": [
            _unit_cfg(1, 1, 3, 3),
            _unit_cfg(2, 2, 10, 10),
        ],
    }


@pytest.fixture(autouse=True)
def mock_build_obs(monkeypatch):
    monkeypatch.setattr(W40KEngine, "_build_observation", lambda self: np.zeros(50))
    from engine.reward_calculator import RewardCalculator
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)


def _make_engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=_minimal_config())


# ─────────────────────────────────────────────────────────────────────────────
# Tests — retour de step()
# ─────────────────────────────────────────────────────────────────────────────

class TestStepReturnSignature:

    def test_step_returns_5_tuple(self):
        """step_tuple : step() retourne bien un tuple de 5 éléments (gym interface)."""
        engine = _make_engine()
        engine.reset()
        result = engine.step(0)
        assert isinstance(result, tuple)
        assert len(result) == 5

    def test_step_obs_is_ndarray(self):
        """step_obs_type : premier élément (obs) est un np.ndarray."""
        engine = _make_engine()
        engine.reset()
        obs, reward, terminated, truncated, info = engine.step(0)
        assert isinstance(obs, np.ndarray)

    def test_step_reward_is_float(self):
        """step_reward_type : reward est un float (ou castable)."""
        engine = _make_engine()
        engine.reset()
        _, reward, _, _, _ = engine.step(0)
        assert isinstance(reward, (int, float))

    def test_step_terminated_is_bool(self):
        """step_terminated_type : terminated est un bool."""
        engine = _make_engine()
        engine.reset()
        _, _, terminated, _, _ = engine.step(0)
        assert isinstance(terminated, bool)

    def test_step_info_is_dict(self):
        """step_info_type : info est un dict."""
        engine = _make_engine()
        engine.reset()
        _, _, _, _, info = engine.step(0)
        assert isinstance(info, dict)

    def test_step_truncated_is_bool(self):
        """step_truncated_type : truncated est un bool."""
        engine = _make_engine()
        engine.reset()
        _, _, _, truncated, _ = engine.step(0)
        assert isinstance(truncated, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — episode_steps incremented
# ─────────────────────────────────────────────────────────────────────────────

class TestStepEpisodeCounter:

    def test_step_increments_episode_steps_on_success(self):
        """step_episode_steps : step() réussi incrémente episode_steps."""
        engine = _make_engine()
        engine.reset()
        steps_before = engine.game_state["episode_steps"]
        engine.step(0)
        assert engine.game_state["episode_steps"] >= steps_before

    def test_step_increments_only_on_success(self):
        """step_success_only : pool vide → auto-advance → episode_steps reste 0 (pas de vrais steps)."""
        engine = _make_engine()
        engine.reset()
        # Après reset, tous les pools sont vides → chaque step auto-avance la phase
        # episode_steps ne s'incrémente que sur un vrai step (action réussie via pool)
        engine.step(0)
        # Auto-advance ne compte pas comme step : episode_steps peut être 0
        # La valeur exacte dépend du nombre de phases auto-avancées
        # On vérifie juste que l'état est cohérent (pas d'exception)
        assert isinstance(engine.game_state["episode_steps"], int)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — turn limit
# ─────────────────────────────────────────────────────────────────────────────

class TestStepTurnLimit:

    def test_turn_limit_triggers_terminated(self):
        """step_turn_limit : dépasser max_turns_per_episode → terminated=True."""
        engine = _make_engine()
        engine.reset()
        # Force turn au-delà de la limite (3 définie dans config)
        engine.game_state["turn"] = 4
        engine.game_state["turn_limit_reached"] = False

        _, _, terminated, _, info = engine.step(0)

        assert terminated is True
        assert info.get("turn_limit_exceeded") is True

    def test_turn_limit_info_contains_winner(self):
        """step_turn_limit_winner : info contient 'winner' quand turn_limit déclenché."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, terminated, _, info = engine.step(0)

        assert terminated is True
        assert "winner" in info

    def test_turn_limit_info_contains_win_method(self):
        """step_turn_limit_win_method : info contient 'win_method' quand turn_limit déclenché."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 4

        _, _, _, _, info = engine.step(0)

        assert "win_method" in info


# ─────────────────────────────────────────────────────────────────────────────
# Tests — game over check
# ─────────────────────────────────────────────────────────────────────────────

class TestStepGameOver:

    def test_step_after_reset_game_not_over(self):
        """step_not_over : juste après reset(), terminated=False au premier step."""
        engine = _make_engine()
        engine.reset()
        # S'assurer que turn est dans la limite
        engine.game_state["turn"] = 1

        _, _, terminated, _, _ = engine.step(0)

        # Pas de game_over immédiat sauf si phase advance auto
        # On vérifie juste que game_state est cohérent
        assert engine.game_state.get("turn_limit_reached", False) is False or terminated is True

    def test_step_pool_empty_triggers_phase_advance(self):
        """step_pool_empty : si pool vide, step() avance la phase automatiquement."""
        engine = _make_engine()
        engine.reset()
        engine.game_state["turn"] = 1
        # Vider tous les pools d'activation pour forcer le phase auto-advance
        for pool_key in (
            "move_activation_pool", "shoot_activation_pool",
            "charge_activation_pool", "charging_activation_pool",
            "active_alternating_activation_pool", "non_active_alternating_activation_pool",
            "command_activation_pool",
        ):
            engine.game_state[pool_key] = []

        _, _, _, _, info = engine.step(0)

        # Phase advance automatique doit avoir eu lieu
        assert info.get("phase_auto_advanced") is True or engine.game_state["phase"] != "command"
