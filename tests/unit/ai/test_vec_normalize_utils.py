import pickle
from types import SimpleNamespace

import numpy as np

from ai import vec_normalize_utils


def test_get_vec_normalize_path_uses_model_directory() -> None:
    model_path = "/tmp/models/agent/model.zip"
    result = vec_normalize_utils.get_vec_normalize_path(model_path)
    assert result.endswith("/tmp/models/agent/model_vec_normalize.pkl")


def test_get_vec_normalize_path_is_per_model_not_per_directory() -> None:
    """V11 §0.35 : deux modeles d'un MEME dossier ne partagent PAS leurs stats.

    Le chemin valait `<dir>/vec_normalize.pkl` pour tous : supprimer les artefacts d'un modele
    detruisait les stats que les workers d'une evaluation ASYNCHRONE en cours allaient charger
    (600/600 episodes en erreur, run de 5 h 30 arrete au marqueur 24 000). Ce test rougit si le
    nom redevient commun.
    """
    snapshot = vec_normalize_utils.get_vec_normalize_path("/tmp/models/agent/eval_snapshot.zip")
    canonical = vec_normalize_utils.get_vec_normalize_path("/tmp/models/agent/model_Agent.zip")
    best = vec_normalize_utils.get_vec_normalize_path("/tmp/models/agent/Agent_robust_0.45.zip")
    assert len({snapshot, canonical, best}) == 3
    assert snapshot.endswith("/eval_snapshot_vec_normalize.pkl")


def test_get_vec_normalize_path_rejects_empty_path() -> None:
    """Aucun repli : un chemin vide donnerait `<cwd>/_vec_normalize.pkl`, partage par tous."""
    import pytest

    with pytest.raises(ValueError):
        vec_normalize_utils.get_vec_normalize_path("")


def test_save_vec_normalize_returns_false_when_no_wrapper() -> None:
    class PlainEnv:
        pass

    saved = vec_normalize_utils.save_vec_normalize(PlainEnv(), "/tmp/model.zip")
    assert saved is False


def test_save_vec_normalize_saves_when_wrapper_found(monkeypatch) -> None:
    calls = []

    class FakeVecNormalize:
        def __init__(self, venv=None):
            self.venv = venv

        def save(self, path):
            calls.append(path)

    monkeypatch.setattr("stable_baselines3.common.vec_env.VecNormalize", FakeVecNormalize)

    leaf = object()
    wrapped = FakeVecNormalize(venv=leaf)
    saved = vec_normalize_utils.save_vec_normalize(wrapped, "/tmp/model.zip")
    assert saved is True
    assert calls and calls[0].endswith("/tmp/model_vec_normalize.pkl")


def test_load_vec_normalize_returns_none_when_stats_missing(tmp_path) -> None:
    model_path = str(tmp_path / "model.zip")
    result = vec_normalize_utils.load_vec_normalize(venv=object(), model_path=model_path)
    assert result is None


def test_load_vec_normalize_loads_and_sets_eval_flags(tmp_path, monkeypatch) -> None:
    class FakeVecNormalize:
        def __init__(self):
            self.training = True
            self.norm_reward = True

        @classmethod
        def load(cls, path, venv):
            _ = venv
            assert path.endswith("model_vec_normalize.pkl")
            return cls()

    monkeypatch.setattr("stable_baselines3.common.vec_env.VecNormalize", FakeVecNormalize)

    model_path = str(tmp_path / "model.zip")
    vec_path = tmp_path / "model_vec_normalize.pkl"
    vec_path.write_bytes(b"placeholder")

    loaded = vec_normalize_utils.load_vec_normalize(venv=object(), model_path=model_path)
    assert loaded is not None
    assert loaded.training is False
    assert loaded.norm_reward is False


def test_normalize_observation_for_inference_returns_original_when_no_file(tmp_path) -> None:
    obs = np.array([1.0, 2.0], dtype=np.float32)
    model_path = str(tmp_path / "model.zip")
    out = vec_normalize_utils.normalize_observation_for_inference(obs, model_path)
    assert np.array_equal(out, obs)


def test_normalize_observation_for_inference_normalizes_with_rms_stats(tmp_path) -> None:
    obs = np.array([2.0, 6.0], dtype=np.float32)
    vec_obj = SimpleNamespace(
        obs_rms=SimpleNamespace(mean=np.array([1.0, 2.0]), var=np.array([1.0, 4.0])),
        epsilon=1e-8,
        clip_obs=10.0,
        norm_obs=True,
    )
    vec_path = tmp_path / "model_vec_normalize.pkl"
    with open(vec_path, "wb") as f:
        pickle.dump(vec_obj, f)

    out = vec_normalize_utils.normalize_observation_for_inference(obs, str(tmp_path / "model.zip"))
    expected = np.array([1.0, 2.0], dtype=np.float32)
    assert np.allclose(out, expected, atol=1e-5)


def test_normalize_observation_for_inference_respects_norm_obs_disabled(tmp_path) -> None:
    obs = np.array([3.0, 4.0], dtype=np.float32)
    vec_obj = SimpleNamespace(
        obs_rms=SimpleNamespace(mean=np.array([1.0, 2.0]), var=np.array([1.0, 1.0])),
        norm_obs=False,
    )
    vec_path = tmp_path / "model_vec_normalize.pkl"
    with open(vec_path, "wb") as f:
        pickle.dump(vec_obj, f)

    out = vec_normalize_utils.normalize_observation_for_inference(obs, str(tmp_path / "model.zip"))
    assert np.array_equal(out, obs)


def test_evaluation_normalizes_with_the_stats_of_the_model_it_evaluates() -> None:
    """V11 §0.35 (2e moitié) : `vec_model_path` EST le modèle évalué, jamais le canonique.

    `evaluate_against_bots` construisait `vec_model_path` en dur depuis
    `<models_root>/<agent>/model_<agent>.zip`, alors que les workers CHARGENT
    `effective_model_path` — un snapshot temporaire en mode async. On évaluait donc un modèle
    avec la normalisation d'un AUTRE, ce qui n'a jamais levé tant qu'un pkl traînait dans le
    dossier des modèles. Ce test rougit si la source diverge à nouveau.
    """
    import inspect

    from ai import bot_evaluation

    src = inspect.getsource(bot_evaluation.evaluate_against_bots)
    assert "vec_model_path = effective_model_path" in src, (
        "les stats de normalisation doivent venir du modele EVALUE (V11 §0.35)"
    )
    assert 'f"model_{base_agent_key}.zip"' not in src, (
        "vec_model_path ne doit plus etre derive du modele canonique (V11 §0.35)"
    )
