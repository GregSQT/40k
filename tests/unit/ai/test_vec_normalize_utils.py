import pickle
from types import SimpleNamespace

import numpy as np

from ai import vec_normalize_utils


class _FakeVN:
    """VecNormalize stub picklable pour tests non-dict normalizer."""

    def __init__(self, mean, var, epsilon=1e-8, clip_obs=10.0):
        self.mean = mean
        self.var = var
        self.epsilon = epsilon
        self.clip_obs = clip_obs

    def normalize_obs(self, obs):
        return np.clip(
            (obs - self.mean) / np.sqrt(self.var + self.epsilon),
            -self.clip_obs,
            self.clip_obs,
        )


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


def test_normalize_observation_for_inference_raises_when_no_file(tmp_path) -> None:
    """Pkl absent = erreur explicite : retourner l'obs brute en silence faisait jouer un modèle
    normalisé sur des obs brutes (décalage de distribution muet, V11 §0.35)."""
    import pytest

    obs = np.array([1.0, 2.0], dtype=np.float32)
    model_path = str(tmp_path / "model.zip")
    with pytest.raises(FileNotFoundError, match=r"model_vec_normalize\.pkl"):
        vec_normalize_utils.normalize_observation_for_inference(obs, model_path)


def test_normalize_observation_for_inference_raises_on_stats_without_obs_rms(tmp_path) -> None:
    """Un pkl sans `obs_rms` est corrompu ou d'une autre version : erreur, pas d'obs brute."""
    import pytest

    with open(tmp_path / "model_vec_normalize.pkl", "wb") as f:
        pickle.dump(SimpleNamespace(norm_obs=True), f)
    with pytest.raises(ValueError, match="obs_rms"):
        vec_normalize_utils.normalize_observation_for_inference(
            np.array([1.0], dtype=np.float32), str(tmp_path / "model.zip")
        )


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


def test_worker_normalizer_derives_its_stats_from_the_evaluated_model(tmp_path) -> None:
    """V11 §0.35 (2e moitié) : les stats de normalisation viennent du zip que le worker charge.

    `evaluate_against_bots` construisait un `vec_model_path` séparé, en dur depuis
    `<models_root>/<agent>/model_<agent>.zip`, alors que les workers chargeaient
    `effective_model_path` — un snapshot temporaire en mode async : on évaluait un modèle avec
    la normalisation d'un AUTRE. Le canal séparé a été SUPPRIMÉ : ce test prouve (1) qu'il
    n'existe plus, (2) que le normalizer worker lit bien le pkl dérivé du zip du modèle, et
    (3) qu'une obs Dict sans ce pkl lève en nommant le fichier attendu.
    """
    import inspect

    import pytest

    from ai import bot_evaluation

    # (1) Plus de chemin de stats séparé dans la chaîne worker : la divergence est
    # irreprésentable, pas seulement corrigée.
    assert "vec_model_path" not in inspect.signature(bot_evaluation._eval_worker_init).parameters
    assert "vec_model_path" not in inspect.signature(
        bot_evaluation._build_eval_obs_normalizer_for_worker
    ).parameters

    # (2) Chemin Box : le pkl lu est celui dérivé du ZIP du modèle évalué.
    model_path = str(tmp_path / "eval_snapshot.zip")

    with open(tmp_path / "eval_snapshot_vec_normalize.pkl", "wb") as f:
        pickle.dump(_FakeVN(np.array([1.0, 2.0]), np.array([1.0, 4.0])), f)
    normalizer = bot_evaluation._build_eval_obs_normalizer_for_worker(
        None, model_path, True, True
    )
    assert normalizer is not None
    out = normalizer(np.array([2.0, 6.0], dtype=np.float32))
    assert np.allclose(out, np.array([1.0, 2.0], dtype=np.float32), atol=1e-5)

    # (3) Chemin Dict : pkl absent = erreur explicite nommant le fichier DU modèle évalué.
    missing = bot_evaluation._build_eval_obs_normalizer_for_worker(
        None, str(tmp_path / "other_model.zip"), True, True
    )
    assert missing is not None
    with pytest.raises(RuntimeError, match=r"other_model_vec_normalize\.pkl"):
        missing({"global_cont": np.zeros(3, dtype=np.float32)})


def test_build_snapshot_normalizer_uses_cached_vn_for_array_obs(tmp_path) -> None:
    """build_snapshot_normalizer ne recharge pas le pkl à chaque appel (non-dict path).

    Avant le fix, la branche non-dict appelait normalize_observation_for_inference qui
    ouvre et dépickle le pkl à chaque inférence, ignorant le vn mis en cache.
    Après le fix, les deux chemins passent par vn.normalize_obs() sur l'objet déjà chargé.
    """
    load_count = [0]
    real_load = pickle.load

    def counting_load(f):
        load_count[0] += 1
        return real_load(f)

    snapshot_path = str(tmp_path / "snapshot.zip")
    pkl_path = tmp_path / "snapshot_vec_normalize.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(_FakeVN(np.array([1.0, 2.0]), np.array([1.0, 4.0])), f)

    import unittest.mock as mock

    with mock.patch("pickle.load", side_effect=counting_load):
        normalizer = vec_normalize_utils.build_snapshot_normalizer(
            snapshot_path, vec_normalize_enabled=True, vec_normalize_eval_enabled=True
        )
        assert normalizer is not None
        obs = np.array([2.0, 6.0], dtype=np.float32)
        out1 = normalizer(obs)
        out2 = normalizer(obs)

    assert load_count[0] == 1, f"pkl chargé {load_count[0]} fois au lieu de 1"
    assert np.allclose(out1, np.array([1.0, 2.0], dtype=np.float32), atol=1e-5)
    assert np.array_equal(out1, out2)
