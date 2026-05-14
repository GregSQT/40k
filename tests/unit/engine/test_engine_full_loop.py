"""Tests unitaires — boucle complète W40KEngine : reset() → step()×N → terminated.

Valide l'orchestration de bout en bout avec un engine réel (vrai __init__).

Stratégie de terminaison : après quelques steps normaux (qui testent la stabilité),
on force game_state["turn"] = max_turns+1 pour déclencher le retour anticipé
"turn_limit_exceeded" dans step(). Ceci est le seul chemin de terminaison
garanti sans peupler les pools d'activation ni mocker convert_gym_action.

Comportement réel de step() quand turn > max_turns (ligne 1260 w40k_core.py) :
  - game_state["turn_limit_reached"] = True
  - retourne terminated=True, info={"turn_limit_exceeded": True, "winner": ..., "win_method": ...}
  - game_state["game_over"] n'est PAS set dans ce chemin (retour anticipé avant ligne 1283)
"""

from __future__ import annotations

from typing import Any, Dict, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_MAX_TURNS = 3  # doit correspondre à training_config["max_turns_per_episode"]
_TURN_FORCE = _MAX_TURNS + 1  # valeur qui déclenche la terminaison


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
        "action_space_size": 31,
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
            "max_turns_per_episode": _MAX_TURNS,
        },
        "units": [
            _unit_cfg(1, 1, 3, 3),
            _unit_cfg(2, 2, 10, 10),
        ],
    }


@pytest.fixture(autouse=True)
def mock_obs_and_reward(monkeypatch):
    monkeypatch.setattr(W40KEngine, "_build_observation", lambda self: np.zeros(50))
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)


def _make_engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=_minimal_config())


def _run_episode(engine: W40KEngine, max_iters: int = 50) -> Tuple[Dict[str, Any], int]:
    """reset() + step()×N avec terminaison garantie via force-turn après 5 steps.

    Les 5 premiers steps testent la stabilité de l'engine sous actions invalides.
    Au 6e step, turn est forcé à _TURN_FORCE → step() retourne terminated=True
    via le chemin turn_limit (ligne 1260 w40k_core.py).
    """
    engine.reset()
    last_info: Dict[str, Any] = {}
    steps = 0
    for i in range(max_iters):
        if i == 5:
            engine.game_state["turn"] = _TURN_FORCE
        _, _, terminated, _, info = engine.step(0)
        last_info = info
        steps += 1
        if terminated:
            break
    return last_info, steps


# ─────────────────────────────────────────────────────────────────────────────
# Classe 1 — Terminaison
# ─────────────────────────────────────────────────────────────────────────────

class TestFullLoopTermination:

    def test_loop_terminates_before_max_iterations(self):
        """loop_terminates : reset→step×N → terminated=True avant 200 itérations."""
        engine = _make_engine()
        engine.reset()
        terminated = False
        for i in range(200):
            if i == 5:
                engine.game_state["turn"] = _TURN_FORCE
            _, _, terminated, _, _ = engine.step(0)
            if terminated:
                break
        assert terminated is True

    def test_step_returns_5_tuple_throughout_loop(self):
        """loop_tuple : chaque step() retourne un tuple de 5 éléments pendant la boucle."""
        engine = _make_engine()
        engine.reset()
        for i in range(8):
            if i == 5:
                engine.game_state["turn"] = _TURN_FORCE
            result = engine.step(0)
            assert isinstance(result, tuple) and len(result) == 5
            if result[2]:  # terminated
                break

    def test_terminated_info_contains_winner(self):
        """loop_winner : info contient 'winner' quand terminated."""
        engine = _make_engine()
        last_info, _ = _run_episode(engine)
        assert "winner" in last_info

    def test_terminated_info_contains_win_method(self):
        """loop_win_method : info contient 'win_method' quand terminated."""
        engine = _make_engine()
        last_info, _ = _run_episode(engine)
        assert "win_method" in last_info

    def test_terminated_by_turn_limit(self):
        """loop_turn_limit : turn_limit_exceeded=True dans info quand terminé via turn limit."""
        engine = _make_engine()
        last_info, _ = _run_episode(engine)
        assert last_info.get("turn_limit_exceeded") is True


# ─────────────────────────────────────────────────────────────────────────────
# Classe 2 — Cohérence de l'état
# ─────────────────────────────────────────────────────────────────────────────

class TestFullLoopStateCoherence:

    def test_episode_steps_is_int_after_loop(self):
        """loop_episode_steps_type : episode_steps est un int >= 0 après la boucle."""
        engine = _make_engine()
        _run_episode(engine)
        assert isinstance(engine.game_state["episode_steps"], int)
        assert engine.game_state["episode_steps"] >= 0

    def test_turn_at_or_above_max_turns_after_loop(self):
        """loop_turn_reached : turn >= max_turns_per_episode après la boucle forcée."""
        engine = _make_engine()
        _run_episode(engine)
        assert engine.game_state["turn"] >= _MAX_TURNS

    def test_turn_limit_reached_set_after_loop(self):
        """loop_turn_limit_reached : game_state['turn_limit_reached'] = True après terminaison turn_limit.

        Note : le retour anticipé (ligne 1260 w40k_core.py) set turn_limit_reached=True
        mais PAS game_over=True — comportement attendu et documenté.
        """
        engine = _make_engine()
        _run_episode(engine)
        assert engine.game_state.get("turn_limit_reached") is True

    def test_victory_points_contains_both_players(self):
        """loop_vp_players : victory_points contient les clés 1 et 2 (initialisées à 0)."""
        engine = _make_engine()
        _run_episode(engine)
        vp = engine.game_state.get("victory_points", {})
        assert 1 in vp, "joueur 1 absent de victory_points"
        assert 2 in vp, "joueur 2 absent de victory_points"


# ─────────────────────────────────────────────────────────────────────────────
# Classe 3 — Multi-épisodes
# ─────────────────────────────────────────────────────────────────────────────

class TestFullLoopMultiEpisode:

    def test_second_episode_also_terminates(self):
        """loop_ep2_terminates : le 2e épisode se termine aussi (terminated=True)."""
        engine = _make_engine()
        _run_episode(engine)  # épisode 1
        # épisode 2
        engine.reset()
        terminated = False
        for i in range(200):
            if i == 5:
                engine.game_state["turn"] = _TURN_FORCE
            _, _, terminated, _, _ = engine.step(0)
            if terminated:
                break
        assert terminated is True

    def test_episode_number_incremented_after_first_reset(self):
        """loop_ep_number_reset1 : episode_number incrémenté après le premier reset()."""
        engine = _make_engine()
        ep_before = engine.episode_number
        engine.reset()
        assert engine.episode_number == ep_before + 1

    def test_episode_number_incremented_between_two_episodes(self):
        """loop_ep_number_ep2 : episode_number incrémenté entre les deux épisodes."""
        engine = _make_engine()
        _run_episode(engine)
        ep_after_first = engine.episode_number
        engine.reset()
        assert engine.episode_number == ep_after_first + 1
