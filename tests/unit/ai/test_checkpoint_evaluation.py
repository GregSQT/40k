"""Tests unitaires pour R0b — discover_checkpoint_archives, _NormalizedFrozenModel,
et log_checkpoint_evaluations (compteurs W/L/D)."""

import logging
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from ai.bot_evaluation import discover_checkpoint_archives, _NormalizedFrozenModel
from ai.metrics_tracker import W40KMetricsTracker


# ── helpers ───────────────────────────────────────────────────────────────────


class _DummyWriter:
    """Stub TensorBoard writer pour test_checkpoint_evaluation."""

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, key: str, value: float, step: int, /) -> None:
        self.scalars.append((key, value, step))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:  # noqa: ARG002
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def _ckpt_tracker_stub() -> W40KMetricsTracker:
    t = W40KMetricsTracker.__new__(W40KMetricsTracker)
    t.writer = _DummyWriter()
    t.episode_count = 42
    return t


# ── discover_checkpoint_archives ──────────────────────────────────────────


def test_discover_finds_compatible_archives(tmp_path):
    """Archives avec .zip + .pkl compagnon sont retournées, triées par score croissant."""
    agent_dir = tmp_path / "MyAgent"
    agent_dir.mkdir()

    for score in ("0.8000", "0.7500", "0.9000"):
        (agent_dir / f"MyAgent_12345_robust_{score}.zip").write_bytes(b"dummy")
        (agent_dir / f"MyAgent_12345_robust_{score}_vec_normalize.pkl").write_bytes(b"dummy")

    result = discover_checkpoint_archives(str(tmp_path), "MyAgent")

    assert len(result) == 3
    # Tri croissant par score
    assert [label for _, label in result] == ["0.7500", "0.8000", "0.9000"]
    # Chemins absolus pointant vers les bons fichiers
    for zip_path, label in result:
        assert os.path.isfile(zip_path)
        assert zip_path.endswith(f"_robust_{label}.zip")


def test_discover_skips_incompatible_no_pkl(tmp_path, caplog):
    """Archive sans .pkl → skippée avec message INFO nommant le commit de rupture."""
    agent_dir = tmp_path / "MyAgent"
    agent_dir.mkdir()

    # Compatible
    (agent_dir / "MyAgent_12345_robust_0.8000.zip").write_bytes(b"dummy")
    (agent_dir / "MyAgent_12345_robust_0.8000_vec_normalize.pkl").write_bytes(b"dummy")
    # Incompatible : pas de pkl
    (agent_dir / "MyAgent_12345_robust_0.7000.zip").write_bytes(b"dummy")

    with caplog.at_level(logging.INFO):
        result = discover_checkpoint_archives(str(tmp_path), "MyAgent")

    assert len(result) == 1
    assert result[0][1] == "0.8000"
    # Le message de skip mentionne le commit de rupture
    messages = [r.getMessage() for r in caplog.records]
    assert any("d5ddffb5" in m for m in messages)
    assert any("MyAgent_12345_robust_0.7000.zip" in m for m in messages)


def test_discover_skips_non_matching_filenames(tmp_path):
    """Fichiers avec OLD_BOTS/NEW_BOTS ou autres labels extra ne matchent pas le pattern."""
    agent_dir = tmp_path / "MyAgent"
    agent_dir.mkdir()

    # Ne doit PAS matcher (label extra)
    (agent_dir / "MyAgent_OLD_BOTS_12345_robust_0.8000.zip").write_bytes(b"dummy")
    (agent_dir / "MyAgent_OLD_BOTS_12345_robust_0.8000_vec_normalize.pkl").write_bytes(b"dummy")
    (agent_dir / "MyAgent_NEW_BOTS_12345_robust_0.8000.zip").write_bytes(b"dummy")
    (agent_dir / "MyAgent_NEW_BOTS_12345_robust_0.8000_vec_normalize.pkl").write_bytes(b"dummy")

    # Doit matcher
    (agent_dir / "MyAgent_12345_robust_0.7500.zip").write_bytes(b"dummy")
    (agent_dir / "MyAgent_12345_robust_0.7500_vec_normalize.pkl").write_bytes(b"dummy")

    result = discover_checkpoint_archives(str(tmp_path), "MyAgent")
    assert len(result) == 1
    assert result[0][1] == "0.7500"


def test_discover_returns_empty_when_no_agent_dir(tmp_path):
    """Dossier agent absent → liste vide, pas d'erreur."""
    result = discover_checkpoint_archives(str(tmp_path), "NonExistentAgent")
    assert result == []


def test_discover_returns_empty_when_no_robust_archives(tmp_path):
    """Dossier agent existant mais sans archives robust → liste vide."""
    agent_dir = tmp_path / "MyAgent"
    agent_dir.mkdir()
    (agent_dir / "model_MyAgent.zip").write_bytes(b"dummy")

    result = discover_checkpoint_archives(str(tmp_path), "MyAgent")
    assert result == []


# ── _NormalizedFrozenModel ────────────────────────────────────────────────


class _FakeModel:
    """Stub MaskablePPO.predict() — retourne (obs_received, None)."""

    def __init__(self):
        self.last_obs = None

    def predict(self, obs, **kwargs):
        self.last_obs = obs
        return (obs, None)


def test_normalized_frozen_model_applies_normalizer():
    """Le normalizer est appelé avant predict(), et predict reçoit l'obs normalisée."""
    fake = _FakeModel()
    calls = []

    def normalizer(obs):
        calls.append(obs.copy())
        return obs * 2.0

    nfm = _NormalizedFrozenModel(fake, normalizer)
    raw_obs = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    action, _ = nfm.predict(raw_obs, deterministic=True)

    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], raw_obs)
    np.testing.assert_array_equal(fake.last_obs, raw_obs * 2.0)


def test_normalized_frozen_model_no_normalizer_passes_raw():
    """Sans normalizer (None), l'obs est transmise telle quelle."""
    fake = _FakeModel()
    nfm = _NormalizedFrozenModel(fake, None)
    raw_obs = np.array([1.0, 2.0], dtype=np.float32)
    nfm.predict(raw_obs)
    np.testing.assert_array_equal(fake.last_obs, raw_obs)


def test_normalized_frozen_model_passes_kwargs():
    """Les kwargs (deterministic, action_masks) sont transmis au modèle sous-jacent."""
    received_kwargs = {}

    class _KwargCapture:
        def predict(self, obs, **kwargs):
            received_kwargs.update(kwargs)
            return (obs, None)

    nfm = _NormalizedFrozenModel(_KwargCapture(), None)
    mask = np.ones((1, 10), dtype=bool)
    nfm.predict(np.zeros(5), deterministic=True, action_masks=mask)

    assert received_kwargs.get("deterministic") is True
    assert "action_masks" in received_kwargs


# ── log_checkpoint_evaluations — compteurs W/L/D ──────────────────────────────


def _scalars_dict(tracker: W40KMetricsTracker) -> Dict[str, float]:
    """Retourne {key: value} depuis la liste des scalaires enregistrés."""
    writer = tracker.writer
    assert isinstance(writer, _DummyWriter)
    return {k: v for k, v, _ in writer.scalars}


def test_log_checkpoint_publishes_wld_counters():
    """Les compteurs _wins/_losses/_draws sont publiés sous bot_eval/vs_ckpt_*."""
    t = _ckpt_tracker_stub()
    ckpt_results = {
        "0.50": 0.6,
        "0.50_wins": 30,
        "0.50_losses": 15,
        "0.50_draws": 5,
    }
    t.log_checkpoint_evaluations(ckpt_results, step=100)

    scalars = _scalars_dict(t)
    assert scalars["bot_eval/vs_ckpt_0.50"] == pytest.approx(0.6)
    assert scalars["bot_eval/vs_ckpt_0.50_wins"] == 30
    assert scalars["bot_eval/vs_ckpt_0.50_losses"] == 15
    assert scalars["bot_eval/vs_ckpt_0.50_draws"] == 5


def test_log_checkpoint_min_mean_exclude_wld_counters():
    """ckpt_min et ckpt_mean ne portent que sur les ratios, pas sur les compteurs bruts."""
    t = _ckpt_tracker_stub()
    ckpt_results = {
        "0.40": 0.4,
        "0.40_wins": 20,
        "0.40_losses": 25,
        "0.40_draws": 5,
        "0.70": 0.7,
        "0.70_wins": 35,
        "0.70_losses": 10,
        "0.70_draws": 5,
    }
    t.log_checkpoint_evaluations(ckpt_results, step=200)

    scalars = _scalars_dict(t)
    assert scalars["00_critical/ckpt_min"] == pytest.approx(0.4)
    assert scalars["00_critical/ckpt_mean"] == pytest.approx((0.4 + 0.7) / 2)


def test_log_checkpoint_empty_does_nothing():
    """Avec un dict vide, aucun scalaire n'est publié."""
    t = _ckpt_tracker_stub()
    t.log_checkpoint_evaluations({}, step=0)
    writer = t.writer
    assert isinstance(writer, _DummyWriter)
    assert writer.scalars == []
