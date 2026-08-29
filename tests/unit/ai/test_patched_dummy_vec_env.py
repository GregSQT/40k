"""Vérifie que PatchedDummyVecEnv copie terminal_observation AVANT env.reset().

Bug original (SB3 DummyVecEnv) : terminal_observation = référence au scratch moteur →
env.reset() écrase le scratch → deepcopy copie l'obs POST-reset, pas l'obs terminale.
"""
import gymnasium
import numpy as np
import pytest
from gymnasium import spaces

from ai.patched_ppo import PatchedDummyVecEnv


class _ScratchEnv(gymnasium.Env):
    """Env factice dont le buffer obs est réutilisé (contrat scratch moteur).

    - step() retourne done=True à chaque appel, avec obs = {"x": [step_count]}.
    - reset() réinitialise le scratch à [0] — simule l'écrasement moteur.
    - Les deux retournent le MÊME objet numpy (réutilisation de buffer).
    """

    def __init__(self):
        super().__init__()
        self.observation_space = spaces.Dict({"x": spaces.Box(0, 255, shape=(1,), dtype=np.float32)})
        self.action_space = spaces.Discrete(2)
        self._buf = np.zeros(1, dtype=np.float32)
        self._step_count = 0

    def reset(self, *, seed=None, options=None):
        self._buf[:] = 0.0
        self._step_count = 0
        return {"x": self._buf}, {}

    def step(self, action):
        self._step_count += 1
        self._buf[:] = float(self._step_count)
        obs = {"x": self._buf}
        return obs, 0.0, True, False, {}  # terminated=True → done immédiat


def _make_env():
    env = _ScratchEnv()
    env.reset()
    return env


def test_terminal_observation_is_pre_reset():
    """terminal_observation doit contenir la valeur terminale, pas la valeur post-reset."""
    venv = PatchedDummyVecEnv([_make_env])
    venv.reset()

    venv.step_async(np.array([0]))
    _, _, dones, infos = venv.step_wait()

    assert dones[0], "l'épisode doit être terminé"
    term_obs = infos[0]["terminal_observation"]
    assert term_obs is not None, "terminal_observation absent"

    # Valeur terminale = 1.0 (premier step) ; valeur post-reset = 0.0
    assert float(term_obs["x"][0]) == 1.0, (
        f"terminal_observation contient la valeur post-reset ({term_obs['x'][0]})"
        " au lieu de la valeur terminale (1.0)"
    )


def test_terminal_observation_is_owned_copy():
    """terminal_observation ne doit pas partager le buffer scratch du moteur."""
    venv = PatchedDummyVecEnv([_make_env])
    venv.reset()

    venv.step_async(np.array([0]))
    _, _, _, infos = venv.step_wait()
    term_obs = infos[0]["terminal_observation"]

    # Faire un second step pour écraser le scratch — term_obs ne doit pas changer.
    venv.step_async(np.array([0]))
    venv.step_wait()

    assert float(term_obs["x"][0]) == 1.0, (
        "terminal_observation partage le buffer scratch : écrasé par le step suivant"
    )
