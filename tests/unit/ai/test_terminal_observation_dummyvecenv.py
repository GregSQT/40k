"""Verrou de l'observation TERMINALE a la frontiere gym/VecEnv (chemin n_envs=1).

Le moteur sert ses observations depuis un buffer scratch reutilise
(`engine/observation_builder.py::_ensure_full_obs_scratch`) : chaque appel rend la MEME
reference. `DummyVecEnv.step_wait` (SB3 2.9) pose `info["terminal_observation"] = obs`, appelle
`env.reset()` — qui reecrit ce scratch — puis `deepcopy` les infos. Sans copie a la sortie du
wrapper, le bootstrap `TimeLimit.truncated` de `ai/patched_ppo.py:513` evalue l'obs INITIALE de
l'episode suivant au lieu de l'obs terminale.

Le chemin `n_envs > 1` (`ai/maskable_subproc_vec_env.py`) fait deja cette copie cote worker ;
ces tests verrouillent le jumeau `n_envs = 1`.
"""

from __future__ import annotations

from typing import Any, Dict, List

import gymnasium as gym
import numpy as np
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper

RESET_MARK = 999.0
TRUNCATE_AFTER = 3


class _ScratchDecoder:
    """Decodeur minimal : une seule action legale, aucun choix d'activation."""

    def get_squad_action_mask_and_eligible_units(self, game_state):
        _ = game_state
        return [True] + [False] * 11, [{"id": "U1", "player": 1}]

    def activation_selection_slots(self, game_state, eligible_units=None):
        _ = (game_state, eligible_units)
        return None

    def normalize_action_input(self, raw_action, phase, source, action_space_size):
        _ = (phase, source, action_space_size)
        return int(raw_action)

    def validate_action_against_mask(self, action_int, action_mask, phase, source, unit_id):
        _ = (action_int, action_mask, phase, source, unit_id)


class _ScratchEngine(gym.Env):
    """Moteur double qui REND TOUJOURS LE MEME dict de tableaux, comme le vrai obs_builder.

    `reset()` reecrit ce scratch avec `RESET_MARK` : c'est ce qui rend l'aliasing observable.
    L'episode est TRONQUE (`truncated`) apres `TRUNCATE_AFTER` steps — la seule branche que
    le bootstrap de `patched_ppo` consomme.
    """

    metadata: Dict[str, Any] = {}

    def __init__(self) -> None:
        super().__init__()
        self.action_space = gym.spaces.Discrete(12)
        self.observation_space = gym.spaces.Dict(
            {"obs": gym.spaces.Box(low=-1e6, high=1e6, shape=(1,), dtype=np.float32)}
        )
        self.action_decoder = _ScratchDecoder()
        self.defer_observation = False
        self._scratch = {"obs": np.zeros((1,), dtype=np.float32)}
        self._steps = 0
        self.game_state = {
            "phase": "move",
            "debug_mode": False,
            "current_player": 1,
            "episode_number": 1,
            "episode_steps": 0,
        }
        self.config: Dict[str, Any] = {}

    def _serve(self, value: float) -> Dict[str, np.ndarray]:
        self._scratch["obs"][0] = value
        return self._scratch

    def reset(self, *, seed=None, options=None):
        _ = (seed, options)
        self._steps = 0
        return self._serve(RESET_MARK), {}

    def step(self, action) -> tuple:
        obs, reward, terminated, truncated, info, _mask = self.step_with_mask(action)
        return obs, reward, terminated, truncated, info

    def step_with_mask(self, action, mask_and_eligible=None) -> tuple:
        _ = action
        self._steps += 1
        truncated = self._steps >= TRUNCATE_AFTER
        # `winner` est REQUIS par SelfPlayWrapper a la fin d'un episode (contrat du moteur).
        info: Dict[str, Any] = {"winner": 1} if truncated else {}
        obs, out_mask = self._step_observation(mask_and_eligible)
        return obs, 0.0, False, truncated, info, out_mask

    def get_action_mask(self):
        mask, _eligible = self.action_decoder.get_squad_action_mask_and_eligible_units(
            self.game_state
        )
        return mask

    def auto_deployment_action(self, action_mask):
        _ = action_mask
        return None

    def _step_observation(self, mask_and_eligible=None):
        if self.defer_observation:
            return None, mask_and_eligible
        return self._build_observation(mask_and_eligible=mask_and_eligible), mask_and_eligible

    def _build_observation(self, mask_and_eligible=None):
        _ = mask_and_eligible
        return self._serve(float(self._steps))

    def _check_game_over(self):
        return False

    def _determine_winner_with_method(self):
        return None, None

    def get_turn_step_limit(self) -> int:
        return 200

    def close(self):
        return None


class _FixedBot:
    def select_action_with_state(
        self, valid_actions: List[int], game_state: Dict[str, Any], active_unit: Dict[str, Any]
    ) -> int:
        _ = (game_state, active_unit)
        return int(valid_actions[0])


def _run_until_done(venv: DummyVecEnv) -> Dict[str, Any]:
    """Joue jusqu'au premier `done` et rend l'`info` du VecEnv (deepcopy SB3 comprise)."""
    venv.reset()
    for _ in range(TRUNCATE_AFTER + 5):
        _obs, _rew, dones, infos = venv.step(np.array([0]))
        if dones[0]:
            return infos[0]
    raise AssertionError("l'episode ne s'est jamais termine : le test n'observe rien")


def _assert_terminal_obs_is_terminal(info: Dict[str, Any]) -> None:
    assert info["TimeLimit.truncated"] is True, (
        "l'episode doit etre TRONQUE : c'est la seule branche que le bootstrap consomme"
    )
    terminal = info["terminal_observation"]["obs"][0]
    assert terminal != RESET_MARK, (
        f"terminal_observation vaut l'obs POST-RESET ({RESET_MARK}) : le wrapper a rendu une "
        "reference au scratch du moteur, mute par env.reset() avant le deepcopy de SB3"
    )
    assert terminal == float(TRUNCATE_AFTER), (
        f"terminal_observation = {terminal}, attendu l'etat terminal {float(TRUNCATE_AFTER)}"
    )


def test_bot_controlled_env_terminal_observation_survives_le_reset() -> None:
    engine = _ScratchEngine()
    venv = DummyVecEnv([lambda: Monitor(BotControlledEnv(engine, bot=_FixedBot()))])
    _assert_terminal_obs_is_terminal(_run_until_done(venv))


def test_self_play_wrapper_terminal_observation_survives_le_reset() -> None:
    engine = _ScratchEngine()
    venv = DummyVecEnv([
        lambda: Monitor(SelfPlayWrapper(engine, frozen_model=None, allow_random_opponent=True))
    ])
    _assert_terminal_obs_is_terminal(_run_until_done(venv))
