#!/usr/bin/env python3
"""Reprise d'entrainement depuis un checkpoint periodique.

Verrouille les deux moities du contrat :
- le callback de checkpoint ecrit les stats VecNormalize A LA CONVENTION du projet
  (`<stem>_vec_normalize.pkl`), faute de quoi le zip est inexploitable pour reprendre ;
- `--resume-from` installe checkpoint + stats au chemin canonique, ecarte (sans ecraser)
  le modele precedent, et refuse un checkpoint sans stats plutot que de servir celles
  d'un autre modele (V11 §0.35).
"""

import json
import os
from typing import Any, cast

import pytest

from ai.train import (
    RotatingCheckpointCallback,
    VecNormalizeCheckpointCallback,
    _promote_checkpoint_for_resume,
)
from ai.vec_normalize_utils import get_vec_normalize_path


class _FakeConfigLoader:
    """Expose uniquement ce que `_promote_checkpoint_for_resume` consomme."""

    def __init__(self, models_root: str):
        self._models_root = models_root

    def get_models_root(self) -> str:
        return self._models_root

    def _resolve_agent_config_key(self, agent_key: str) -> str:
        return agent_key


@pytest.fixture
def models_root(tmp_path, monkeypatch):
    root = tmp_path / "models"
    (root / "TestAgent").mkdir(parents=True)
    monkeypatch.setattr("ai.train.get_config_loader", lambda: _FakeConfigLoader(str(root)))
    return root


def _write_checkpoint(models_root, steps: int, with_stats: bool = True):
    ckpt = models_root / "TestAgent" / f"ppo_checkpoint_{steps}_steps.zip"
    ckpt.write_bytes(b"CHECKPOINT")
    if with_stats:
        # Le pkl jumeau porte le nom du zip : c'est ce chemin que la reprise exige.
        (models_root / "TestAgent" / f"ppo_checkpoint_{steps}_steps_vec_normalize.pkl").write_bytes(b"STATS")
    return str(ckpt)


def test_promote_installs_checkpoint_and_its_stats(models_root):
    ckpt = _write_checkpoint(models_root, 640000)

    model_path = _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    assert model_path == str(models_root / "TestAgent" / "model_TestAgent.zip")
    assert open(model_path, "rb").read() == b"CHECKPOINT"
    assert open(get_vec_normalize_path(model_path), "rb").read() == b"STATS"
    # Le checkpoint source reste en place (copie, pas deplacement).
    assert os.path.exists(ckpt)


def test_promote_resets_tensorboard_run(models_root):
    ckpt = _write_checkpoint(models_root, 640000)

    model_path = _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    # run_dir vide => `_resolve_tensorboard_run_dir` ouvre un run neuf au lieu de prolonger
    # celui qui a produit le checkpoint (dont les steps sont PLUS AVANCES).
    with open(f"{model_path}.tb_run.json", encoding="utf-8") as f:
        assert json.load(f)["run_dir"] == ""


def test_promote_sets_aside_previous_canonical_model(models_root):
    ckpt = _write_checkpoint(models_root, 640000)
    previous = models_root / "TestAgent" / "model_TestAgent.zip"
    previous.write_bytes(b"PREVIOUS")
    (models_root / "TestAgent" / "model_TestAgent_vec_normalize.pkl").write_bytes(b"PREVIOUS_STATS")

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    set_aside = sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*.zip"))
    assert len(set_aside) == 1
    assert set_aside[0].read_bytes() == b"PREVIOUS"
    assert get_vec_normalize_path(str(set_aside[0]))
    assert open(get_vec_normalize_path(str(set_aside[0])), "rb").read() == b"PREVIOUS_STATS"


def test_promote_rejects_checkpoint_without_stats(models_root):
    ckpt = _write_checkpoint(models_root, 480000, with_stats=False)

    with pytest.raises(FileNotFoundError, match="VecNormalize"):
        _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    # Rien n'a ete installe : pas de reprise silencieuse sur des stats etrangeres.
    assert not os.path.exists(models_root / "TestAgent" / "model_TestAgent.zip")


def test_promote_rejects_missing_checkpoint(models_root):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        _promote_checkpoint_for_resume(
            str(models_root / "TestAgent" / "absent.zip"), "TestAgent",
            _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None,
        )


def test_promote_requires_agent(models_root):
    ckpt = _write_checkpoint(models_root, 640000)

    with pytest.raises(ValueError, match="--agent"):
        _promote_checkpoint_for_resume(ckpt, "", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)


class _FakeModel:
    """Modele minimal : le callback n'en consomme que la sauvegarde et l'env normalise."""

    def __init__(self, env, logger):
        self.env = env
        self.logger = logger
        self.num_timesteps = 0

    def get_env(self):
        return self.env

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"MODEL")


def _make_vec_normalize_model():
    import gymnasium as gym
    import numpy as np
    from stable_baselines3.common.logger import Logger
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    class _TrivialEnv(gym.Env):
        observation_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(2,), dtype=np.float32)
        action_space = gym.spaces.Discrete(2)

        def reset(self, *, seed=None, options=None):
            return np.zeros(2, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(2, dtype=np.float32), 0.0, False, False, {}

    venv = VecNormalize(DummyVecEnv([lambda: _TrivialEnv()]))
    return _FakeModel(venv, Logger(folder=None, output_formats=[]))


def _run_checkpoint(callback, model, timesteps: int):
    model.num_timesteps = timesteps
    callback.on_step()


def test_checkpoint_callback_writes_vec_normalize_stats(models_root, tmp_path):
    save_path = str(tmp_path / "ckpts")
    callback = VecNormalizeCheckpointCallback(
        save_freq=1, save_path=save_path, name_prefix="ppo_checkpoint"
    )
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    _run_checkpoint(callback, model, 640000)

    zip_path = os.path.join(save_path, "ppo_checkpoint_640000_steps.zip")
    assert os.path.exists(zip_path)
    # Le pkl doit porter EXACTEMENT le nom attendu par la reprise.
    assert os.path.exists(get_vec_normalize_path(zip_path))


def test_rotating_callback_removes_stats_with_their_zip(models_root, tmp_path):
    save_path = str(tmp_path / "ckpts")
    callback = RotatingCheckpointCallback(
        max_checkpoints=2, save_freq=1, save_path=save_path, name_prefix="ppo_checkpoint"
    )
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    for steps in (100, 200, 300):
        _run_checkpoint(callback, model, steps)

    remaining = sorted(os.path.basename(p) for p in os.listdir(save_path))
    assert remaining == [
        "ppo_checkpoint_200_steps.zip",
        "ppo_checkpoint_200_steps_vec_normalize.pkl",
        "ppo_checkpoint_300_steps.zip",
        "ppo_checkpoint_300_steps_vec_normalize.pkl",
    ]


def test_promote_rejects_canonical_model_as_source(models_root):
    canonical = models_root / "TestAgent" / "model_TestAgent.zip"
    canonical.write_bytes(b"CANONICAL")
    (models_root / "TestAgent" / "model_TestAgent_vec_normalize.pkl").write_bytes(b"STATS")

    with pytest.raises(ValueError, match="canonique"):
        _promote_checkpoint_for_resume(str(canonical), "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
