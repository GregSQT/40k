"""PvE : la normalisation d'inférence est résolue au CHARGEMENT du modèle (V11 §0.35).

L'ancien `_normalize_obs_for_inference` retournait l'obs BRUTE sous un `except Exception` :
un modèle entraîné normalisé jouait en PvE sur des obs brutes sans aucun signal (décalage de
distribution muet), et un pkl legacy partagé aurait été chargé même s'il appartenait à un
autre modèle. Trois contrats ici :
  1. pkl per-model présent → normalisation stricte avec CES stats ;
  2. pkl LEGACY partagé seul → erreur explicite au chargement (migration = geste manuel) ;
  3. aucun pkl → obs brutes (modèle entraîné sans VecNormalize, cas métier), et un modèle
     jamais résolu au chargement est une erreur de flux, pas un repli.

Depuis la suppression du pipeline mono-figurine, l'observation est un Dict de tenseurs : la
normalisation est DÉLÉGUÉE à `VecNormalize.normalize_obs` (comme l'évaluation), donc les tests
utilisent un VRAI objet VecNormalize — un stub laisserait passer une dérive de signature.
"""

import pickle
from typing import Any, Dict, cast

import numpy as np
import pytest

from engine.pve_controller import PvEController


def _controller() -> PvEController:
    return PvEController(config={"quiet": True})


def _dict_obs(value: float = 2.0) -> dict:
    return {"global_cont": np.array([value, value + 4.0], dtype=np.float32)}


def _real_vec_normalize():
    """VecNormalize authentique sur un espace Dict, stats forcées à mean=[1,2], var=[1,4]."""
    import gymnasium as gym
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    class _Stub(gym.Env):
        observation_space = gym.spaces.Dict(
            {"global_cont": gym.spaces.Box(low=-1e6, high=1e6, shape=(2,), dtype=np.float32)}
        )
        action_space = gym.spaces.Discrete(2)

        def reset(self, *, seed=None, options=None):
            return _dict_obs(0.0), {}

        def step(self, action):
            return _dict_obs(0.0), 0.0, True, False, {}

    venv = VecNormalize(
        DummyVecEnv([lambda: _Stub()]), norm_obs=True, norm_reward=False,
        norm_obs_keys=["global_cont"],
    )
    # Espace Dict : `obs_rms` est un dict de RunningMeanStd (le typage sb3 ne le reflete pas).
    obs_rms = cast(Dict[str, Any], venv.obs_rms)
    obs_rms["global_cont"].mean = np.array([1.0, 2.0], dtype=np.float64)
    obs_rms["global_cont"].var = np.array([1.0, 4.0], dtype=np.float64)
    venv.epsilon = 0.0
    return venv


def test_resolve_prefers_the_per_model_pkl(tmp_path) -> None:
    model_path = str(tmp_path / "model_A.zip")
    vec_path = tmp_path / "model_A_vec_normalize.pkl"
    vec_path.write_bytes(b"stats")
    assert _controller()._resolve_vec_stats_path(model_path) == str(vec_path)


def test_resolve_raises_on_legacy_shared_pkl(tmp_path) -> None:
    (tmp_path / "vec_normalize.pkl").write_bytes(b"legacy")
    with pytest.raises(FileNotFoundError, match="LEGACY"):
        _controller()._resolve_vec_stats_path(str(tmp_path / "model_A.zip"))


def test_resolve_returns_none_without_any_stats(tmp_path) -> None:
    assert _controller()._resolve_vec_stats_path(str(tmp_path / "model_A.zip")) is None


def test_inference_raises_for_an_unresolved_model(tmp_path) -> None:
    ctrl = _controller()
    with pytest.raises(RuntimeError, match="non résolu au chargement"):
        ctrl._normalize_obs_for_inference(_dict_obs(), str(tmp_path / "m.zip"))


def test_inference_normalizes_with_the_resolved_stats(tmp_path) -> None:
    """Obs Dict : (2,6) avec mean=(1,2) et var=(1,4) → (1,2)."""
    model_path = str(tmp_path / "model_A.zip")
    with open(tmp_path / "model_A_vec_normalize.pkl", "wb") as f:
        pickle.dump(_real_vec_normalize(), f)
    ctrl = _controller()
    ctrl.micro_model_vec_stats[model_path] = ctrl._resolve_vec_stats_path(model_path)
    out = ctrl._normalize_obs_for_inference(_dict_obs(), model_path)
    assert np.allclose(out["global_cont"], np.array([1.0, 2.0], dtype=np.float32), atol=1e-5)


def test_inference_never_updates_the_stats(tmp_path) -> None:
    """`training` doit être forcé à False : sinon l'inférence PvE dériverait les stats."""
    model_path = str(tmp_path / "model_A.zip")
    with open(tmp_path / "model_A_vec_normalize.pkl", "wb") as f:
        pickle.dump(_real_vec_normalize(), f)
    ctrl = _controller()
    ctrl.micro_model_vec_stats[model_path] = ctrl._resolve_vec_stats_path(model_path)
    ctrl._normalize_obs_for_inference(_dict_obs(), model_path)
    loaded = ctrl._micro_model_vec_normalize[model_path]
    assert loaded.training is False and loaded.norm_reward is False
    assert np.allclose(cast(Dict[str, Any], loaded.obs_rms)["global_cont"].mean, np.array([1.0, 2.0]))


def test_inference_rejects_a_flat_observation(tmp_path) -> None:
    """Le pipeline mono-figurine n'existe plus : une obs à plat est une erreur, pas un repli."""
    model_path = str(tmp_path / "model_A.zip")
    with open(tmp_path / "model_A_vec_normalize.pkl", "wb") as f:
        pickle.dump(_real_vec_normalize(), f)
    ctrl = _controller()
    ctrl.micro_model_vec_stats[model_path] = ctrl._resolve_vec_stats_path(model_path)
    with pytest.raises(TypeError, match="dict"):
        ctrl._normalize_obs_for_inference(cast(Any, np.zeros(2, dtype=np.float32)), model_path)


def test_inference_serves_raw_obs_for_a_model_without_stats(tmp_path) -> None:
    model_path = str(tmp_path / "model_A.zip")
    ctrl = _controller()
    ctrl.micro_model_vec_stats[model_path] = ctrl._resolve_vec_stats_path(model_path)
    obs = _dict_obs()
    assert ctrl._normalize_obs_for_inference(obs, model_path) is obs
