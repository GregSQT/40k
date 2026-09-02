"""Tests unitaires pour R0b — discover_checkpoint_archives, _NormalizedFrozenModel,
et log_checkpoint_evaluations (compteurs W/L/D)."""

import logging
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from ai.bot_evaluation import discover_checkpoint_archives, write_ckpt_scalars, _NormalizedFrozenModel
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


def test_discover_includes_all_pkl_paired_archives(tmp_path):
    """discover retourne toutes les archives ayant un .pkl, quelle que soit leur architecture.

    La vérification §12.15 (RuntimeError Missing key) a été déplacée dans
    evaluate_against_checkpoints pour éviter un double chargement du modèle.
    """
    agent_dir = tmp_path / "MyAgent"
    agent_dir.mkdir()

    (agent_dir / "MyAgent_12345_robust_0.7185.zip").write_bytes(b"dummy")
    (agent_dir / "MyAgent_12345_robust_0.7185_vec_normalize.pkl").write_bytes(b"dummy")
    (agent_dir / "MyAgent_12345_robust_0.9999.zip").write_bytes(b"dummy")
    (agent_dir / "MyAgent_12345_robust_0.9999_vec_normalize.pkl").write_bytes(b"dummy")

    result = discover_checkpoint_archives(str(tmp_path), "MyAgent")

    assert len(result) == 2
    labels = {label for _, label in result}
    assert labels == {"0.7185", "0.9999"}


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


# ── write_ckpt_scalars — guard sur scores vides ───────────────────────────────


def test_write_ckpt_scalars_counter_only_does_not_crash():
    """Dict contenant uniquement des clés _wins/_losses/_draws/_timeouts → pas de crash."""
    writer = _DummyWriter()
    counter_only = {
        "0.50_wins": 30,
        "0.50_losses": 20,
        "0.50_draws": 0,
        "0.50_timeouts": 0,
    }
    write_ckpt_scalars(writer, counter_only, step=0)
    scalar_keys = {k for k, _, _ in writer.scalars}
    assert "00_critical/ckpt_min" not in scalar_keys
    assert "00_critical/ckpt_mean" not in scalar_keys
    # Les compteurs bruts sont quand même publiés.
    assert "bot_eval/vs_ckpt_0.50_wins" in scalar_keys


def test_write_ckpt_scalars_empty_dict_does_not_crash():
    """Dict vide → rien publié, pas de crash."""
    writer = _DummyWriter()
    write_ckpt_scalars(writer, {}, step=0)
    assert writer.scalars == []


# ── log_checkpoint_evaluations — compteurs W/L/D ──────────────────────────────


def _scalars_dict(tracker: W40KMetricsTracker) -> Dict[str, float]:
    """Retourne {key: value} depuis la liste des scalaires enregistrés."""
    writer = tracker.writer
    assert isinstance(writer, _DummyWriter)
    return {k: v for k, v, _ in writer.scalars}


def test_log_checkpoint_publishes_wld_counters():
    """Les compteurs _wins/_losses/_draws/_timeouts sont publiés sous bot_eval/vs_ckpt_*."""
    t = _ckpt_tracker_stub()
    ckpt_results = {
        "0.50": 0.6,
        "0.50_wins": 30,
        "0.50_losses": 15,
        "0.50_draws": 5,
        "0.50_timeouts": 0,
    }
    t.log_checkpoint_evaluations(ckpt_results, step=100)

    scalars = _scalars_dict(t)
    assert scalars["bot_eval/vs_ckpt_0.50"] == pytest.approx(0.6)
    assert scalars["bot_eval/vs_ckpt_0.50_wins"] == 30
    assert scalars["bot_eval/vs_ckpt_0.50_losses"] == 15
    assert scalars["bot_eval/vs_ckpt_0.50_draws"] == 5
    assert scalars["bot_eval/vs_ckpt_0.50_timeouts"] == 0


def test_log_checkpoint_min_mean_exclude_wld_counters():
    """ckpt_min et ckpt_mean ne portent que sur les ratios, pas sur les compteurs bruts."""
    t = _ckpt_tracker_stub()
    ckpt_results = {
        "0.40": 0.4,
        "0.40_wins": 20,
        "0.40_losses": 25,
        "0.40_draws": 5,
        "0.40_timeouts": 0,
        "0.70": 0.7,
        "0.70_wins": 35,
        "0.70_losses": 10,
        "0.70_draws": 5,
        "0.70_timeouts": 0,
    }
    t.log_checkpoint_evaluations(ckpt_results, step=200)

    scalars = _scalars_dict(t)
    assert scalars["00_critical/ckpt_min"] == pytest.approx(0.4)
    assert scalars["00_critical/ckpt_mean"] == pytest.approx((0.4 + 0.7) / 2)


def test_log_checkpoint_timeouts_excluded_from_min_mean():
    """Un timeout élevé (>1) ne doit pas contaminer ckpt_min/ckpt_mean."""
    t = _ckpt_tracker_stub()
    ckpt_results = {
        "0.50": 0.5,
        "0.50_wins": 25,
        "0.50_losses": 20,
        "0.50_draws": 5,
        "0.50_timeouts": 50,  # valeur intentionnellement > 1 pour détecter une inclusion
    }
    t.log_checkpoint_evaluations(ckpt_results, step=300)

    scalars = _scalars_dict(t)
    assert scalars["00_critical/ckpt_min"] == pytest.approx(0.5)
    assert scalars["00_critical/ckpt_mean"] == pytest.approx(0.5)


def test_log_checkpoint_empty_does_nothing():
    """Avec un dict vide, aucun scalaire n'est publié."""
    t = _ckpt_tracker_stub()
    t.log_checkpoint_evaluations({}, step=0)
    writer = t.writer
    assert isinstance(writer, _DummyWriter)
    assert writer.scalars == []


# ── evaluate_against_checkpoints — self_play_snapshot_label ──────────────────


def test_create_eval_env_passes_snapshot_label():
    """BotControlledEnv doit recevoir self_play_snapshot_label=score_label (correctif P1).

    RÉANCRAGE Phase 4 : l'assemblage de l'env checkpoint appartenait à la boucle interne de
    `evaluate_against_checkpoints`, qui ne joue plus d'épisode. Il vit désormais dans
    `_create_eval_env`, et c'est là que l'invariant se teste — sans dérouler tout le harnais.
    """
    from unittest.mock import MagicMock, patch

    from ai.bot_evaluation import _create_eval_env

    captured_kwargs: dict = {}

    class _FakeBotControlledEnv:
        def __init__(self, env, *args, **kwargs):
            captured_kwargs.update(kwargs)

    fake_base_env = MagicMock()
    fake_engine = MagicMock(return_value=fake_base_env)

    with (
        patch("ai.training_utils.setup_imports", return_value=(fake_engine, None)),
        patch("ai.env_wrappers.BotControlledEnv", _FakeBotControlledEnv),
        patch("sb3_contrib.common.wrappers.ActionMasker", side_effect=lambda env, fn: env),
        patch("ai.unit_registry.UnitRegistry", return_value=MagicMock()),
    ):
        _create_eval_env(
            bot_name="P0",
            bot_type="P0",
            randomness_config={},
            scenario_file="scenario.json",
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            controlled_agent="ArmageddonAgent_x1",
            base_agent_key="ArmageddonAgent_x1",
            debug_mode=False,
            agent_seat_mode="p1",
            agent_seat_seed=None,
            checkpoint_zip="/tmp/ckpt.zip",
            checkpoint_label="P0",
            checkpoint_scenario_episodes=4,
        )

    assert captured_kwargs.get("self_play_snapshot_label") == "P0"
    assert captured_kwargs.get("self_play_snapshot_frozen") is True
    # Dénominateur de rampe = total du SCÉNARIO, pas la taille de la tranche : c'est ce qui rend
    # la construction de l'env invariante au découpage, donc la parité avec le séquentiel tenable.
    assert captured_kwargs.get("self_play_total_episodes") == 4


def test_create_eval_env_without_checkpoint_builds_bot():
    """Sans checkpoint_zip, le chemin historique : un bot construit, aucune clé self-play."""
    from unittest.mock import MagicMock, patch

    from ai.bot_evaluation import _create_eval_env

    captured_kwargs: dict = {}
    captured_bot: list = []

    class _FakeBotControlledEnv:
        def __init__(self, env, bot=None, unit_registry=None, **kwargs):
            captured_bot.append(bot)
            captured_kwargs.update(kwargs)

    sentinel_bot = object()

    with (
        patch("ai.training_utils.setup_imports", return_value=(MagicMock(), None)),
        patch("ai.env_wrappers.BotControlledEnv", _FakeBotControlledEnv),
        patch("sb3_contrib.common.wrappers.ActionMasker", side_effect=lambda env, fn: env),
        patch("ai.unit_registry.UnitRegistry", return_value=MagicMock()),
        patch("ai.bot_registry.build_bot", return_value=sentinel_bot) as build_bot,
    ):
        _create_eval_env(
            bot_name="greedy",
            bot_type="greedy",
            randomness_config={},
            scenario_file="scenario.json",
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            controlled_agent="ArmageddonAgent_x1",
            base_agent_key="ArmageddonAgent_x1",
            debug_mode=False,
            agent_seat_mode="p1",
            agent_seat_seed=None,
        )

    build_bot.assert_called_once()
    assert captured_bot == [sentinel_bot]
    assert "self_play_opponent_enabled" not in captured_kwargs


# ── evaluate_against_checkpoints — sc_eps budget ─────────────────────────────


def test_evaluate_against_checkpoints_respects_n_episodes_budget(tmp_path):
    """Avec n_episodes=2 et 3 scénarios, exactement 2 épisodes doivent être demandés.

    Avant le fix d'origine, max(1, 0)=1 forçait le troisième scénario à tourner même avec
    sc_eps=0, gonflant silencieusement le budget demandé.

    RÉANCRAGE Phase 4 : le budget est désormais une propriété du CONSTRUCTEUR DE TÂCHES, pas
    d'une boucle d'épisodes. On somme donc les `n_episodes` des tâches produites.
    """
    from unittest.mock import MagicMock, patch

    from ai.bot_evaluation import evaluate_against_checkpoints

    zip_path = str(tmp_path / "ArmageddonAgent_12345_robust_0.8741.zip")
    (tmp_path / "ArmageddonAgent_12345_robust_0.8741.zip").touch()

    scenario_files = []
    for i in range(3):
        p = tmp_path / f"scenario_{i}.json"
        p.touch()
        scenario_files.append(str(p))

    seen_tasks: list = []

    def _record_task(task, progress_callback=None):
        seen_tasks.append(task)
        return {
            "wins": int(task["n_episodes"]), "losses": 0, "draws": 0,
            "truncations": [], "failed_episodes": 0,
            "bot_name": task["bot_name"], "scenario_name": task["scenario_name"],
            "faction_stats": {}, "seat_stats": {},
            "roster_stats": {"p1": {}, "p2": {}}, "behavior_stats": {},
        }

    training_cfg = {
        "agent_seat_mode": "p1",
        "vec_normalize": {"enabled": False},
        "vec_normalize_eval": {"enabled": False},
        "callback_params": {
            "bot_eval_use_subprocess": False,
            "bot_eval_task_timeout_seconds": 600,
            "bot_eval_n_workers": 1,
            "bot_eval_worker_device": "cpu",
        },
    }
    fake_config = MagicMock()
    fake_config.load_agent_training_config.return_value = training_cfg

    with (
        patch("config_loader.get_config_loader", return_value=fake_config),
        patch("config_loader.get_max_turns", return_value=10),
        patch(
            "ai.training_utils.get_scenario_list_for_phase",
            return_value=scenario_files,
        ),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation._eval_worker_init"),
        patch("ai.bot_evaluation._eval_worker_task", side_effect=_record_task),
    ):
        evaluate_against_checkpoints(
            model_path=zip_path,
            checkpoint_archives=[(zip_path, "0.8741")],
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=2,
            controlled_agent="ArmageddonAgent_x1",
        )

    total_requested = sum(int(t["n_episodes"]) for t in seen_tasks)
    assert total_requested == 2, (
        f"Attendu 2 épisodes (n_episodes=2 sur 3 scénarios), obtenu {total_requested}"
    )
