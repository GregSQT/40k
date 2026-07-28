"""PvE : la normalisation d'inférence est résolue au CHARGEMENT du modèle (V11 §0.35).

L'ancien `_normalize_obs_for_inference` retournait l'obs BRUTE sous un `except Exception` :
un modèle entraîné normalisé jouait en PvE sur des obs brutes sans aucun signal (décalage de
distribution muet), et un pkl legacy partagé aurait été chargé même s'il appartenait à un
autre modèle. Trois contrats ici :
  1. pkl per-model présent → normalisation stricte avec CES stats ;
  2. pkl LEGACY partagé seul → erreur explicite au chargement (migration = geste manuel) ;
  3. aucun pkl → obs brutes (modèle entraîné sans VecNormalize, cas métier), et un modèle
     jamais résolu au chargement est une erreur de flux, pas un repli.
"""

import pickle
from types import SimpleNamespace

import numpy as np
import pytest

from engine.pve_controller import PvEController


def _controller() -> PvEController:
    return PvEController(config={"quiet": True})


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
        ctrl._normalize_obs_for_inference(np.zeros(2, dtype=np.float32), str(tmp_path / "m.zip"))


def test_inference_normalizes_with_the_resolved_stats(tmp_path) -> None:
    model_path = str(tmp_path / "model_A.zip")
    vec_obj = SimpleNamespace(
        obs_rms=SimpleNamespace(mean=np.array([1.0, 2.0]), var=np.array([1.0, 4.0])),
        epsilon=1e-8,
        clip_obs=10.0,
        norm_obs=True,
    )
    with open(tmp_path / "model_A_vec_normalize.pkl", "wb") as f:
        pickle.dump(vec_obj, f)
    ctrl = _controller()
    ctrl.micro_model_vec_stats[model_path] = ctrl._resolve_vec_stats_path(model_path)
    out = ctrl._normalize_obs_for_inference(np.array([2.0, 6.0], dtype=np.float32), model_path)
    assert np.allclose(out, np.array([1.0, 2.0], dtype=np.float32), atol=1e-5)


def test_inference_serves_raw_obs_for_a_model_without_stats(tmp_path) -> None:
    model_path = str(tmp_path / "model_A.zip")
    ctrl = _controller()
    ctrl.micro_model_vec_stats[model_path] = ctrl._resolve_vec_stats_path(model_path)
    obs = np.array([3.0, 4.0], dtype=np.float32)
    assert np.array_equal(ctrl._normalize_obs_for_inference(obs, model_path), obs)
