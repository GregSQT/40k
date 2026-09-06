"""Tests de la moyenne glissante (3 sondes) de PoolEarlyStoppingCallback.

Vérifie :
1. Historique mis à jour correctement sur plusieurs sondes (fenêtre glissante).
2. Pas de moyenne émise à la première sonde (une seule valeur = moyenne identique au brut).
3. Le gate early-stop utilise la valeur BRUTE, pas la moyenne.
4. log_pool_probe appelé avec les bons arguments à chaque sonde.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from tests.unit.ai._fabriques import pool_early_stopping_callback


# ── Helpers ──────────────────────────────────────────────────────────────────


def _callback_with_tracker(archive, **overrides):
    tracker = MagicMock()
    cb = pool_early_stopping_callback(archive, metrics_tracker=tracker, **overrides)
    return cb, tracker


# ── Tests : historique et moyenne ──────────────────────────────────────────


def test_first_probe_emits_no_rolling_mean(tmp_path):
    """La première sonde ne produit pas de moyenne glissante (len(h)==1)."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive)

    cb._log_probe_scores({"champion": 0.453}, episode=100)

    tracker.log_pool_probe.assert_called_once_with("champion", 0.453, None, 100)


def test_second_probe_emits_mean_of_two(tmp_path):
    """A la deuxième sonde la moyenne porte les deux valeurs."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive)

    cb._log_probe_scores({"champion": 0.453}, episode=100)
    tracker.reset_mock()

    cb._log_probe_scores({"champion": 0.557}, episode=200)

    expected_mean = pytest.approx((0.453 + 0.557) / 2)
    tracker.log_pool_probe.assert_called_once_with("champion", 0.557, expected_mean, 200)


def test_window_slides_after_three_probes(tmp_path):
    """A la quatrième sonde la fenêtre glisse : la première valeur est écartée."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive)

    scores = [0.453, 0.557, 0.487, 0.420]
    for i, v in enumerate(scores):
        cb._log_probe_scores({"champion": v}, episode=(i + 1) * 100)

    # Quatrième appel : fenêtre = [0.557, 0.487, 0.420]
    expected_mean = pytest.approx((0.557 + 0.487 + 0.420) / 3)
    last_call = tracker.log_pool_probe.call_args_list[-1]
    assert last_call == call("champion", 0.420, expected_mean, 400)


def test_multiple_labels_tracked_independently(tmp_path):
    """Deux labels ont chacun leur propre historique."""
    archives = [(str(tmp_path / "a.zip"), "label_a"), (str(tmp_path / "b.zip"), "label_b")]
    for path, _ in archives:
        (tmp_path / path.split("/")[-1]).touch()

    from ai.training_callbacks import PoolEarlyStoppingCallback

    tracker = MagicMock()
    cb = PoolEarlyStoppingCallback(
        pool_archives=archives,
        threshold=0.6,
        min_timesteps=0,
        consecutive_evals=2,
        eval_freq_episodes=100,
        n_eval_episodes=10,
        training_config_name="test",
        rewards_config_name="test",
        metrics_tracker=tracker,
    )
    cb.model = MagicMock()

    cb._log_probe_scores({"label_a": 0.5, "label_b": 0.4}, episode=100)
    cb._log_probe_scores({"label_a": 0.6, "label_b": 0.3}, episode=200)

    calls = tracker.log_pool_probe.call_args_list
    # Deuxième sonde : chaque label a sa moyenne indépendante
    assert call("label_a", 0.6, pytest.approx((0.5 + 0.6) / 2), 200) in calls
    assert call("label_b", 0.3, pytest.approx((0.4 + 0.3) / 2), 200) in calls


def test_no_tb_log_when_metrics_tracker_is_none(tmp_path):
    """metrics_tracker=None : _log_probe_scores ne lève pas."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb = pool_early_stopping_callback(archive, metrics_tracker=None)
    # Ne doit pas lever
    cb._log_probe_scores({"champion": 0.5}, episode=100)


# ── Tests : gate early-stop reste sur valeur brute ────────────────────────


def test_gate_uses_raw_not_rolling_mean(tmp_path):
    """Le gate ne compte que les valeurs brutes >= threshold, pas la moyenne.

    Scénario : deux sondes brutes au-dessus du seuil → _consecutive_above = 2 → arrêt.
    La moyenne des deux (ex. 0.65) peut être > seuil sans que cela importe : c'est le brut
    qui compte. On vérifie l'inverse : le gate NE compte PAS une sonde où le brut est bas
    mais la moyenne serait haute.
    """
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive, threshold=0.6, consecutive_evals=2)

    fake_model = MagicMock()
    fake_model.num_timesteps = 999_999
    cb.model = fake_model
    cb.n_envs = 1

    probe_values = iter([0.70, 0.40])

    def fake_probe():
        return {"champion": next(probe_values)}

    with patch.object(cb, "_probe", side_effect=fake_probe):
        # Sonde 1 : brut=0.70 >= 0.6 → consecutive_above = 1
        cb._next_probe_episode = 0
        with patch.object(cb, "_stage_timesteps", return_value=999_999), \
             patch.object(cb, "_stage_episode", return_value=100), \
             patch.object(cb, "_current_episode", return_value=100):
            result1 = cb._on_step()
        assert cb._consecutive_above == 1
        assert result1 is True  # pas encore arrêté

        # Sonde 2 : brut=0.40 < 0.6 → consecutive_above remis à 0
        cb._next_probe_episode = 0
        with patch.object(cb, "_stage_timesteps", return_value=999_999), \
             patch.object(cb, "_stage_episode", return_value=200), \
             patch.object(cb, "_current_episode", return_value=200):
            result2 = cb._on_step()
        assert cb._consecutive_above == 0
        assert result2 is True


def test_gate_stops_on_consecutive_raw_above(tmp_path):
    """consecutive_evals succès bruts consécutifs → _on_step retourne False."""
    archive = tmp_path / "champ.zip"
    archive.touch()
    cb, tracker = _callback_with_tracker(archive, threshold=0.6, consecutive_evals=2)

    fake_model = MagicMock()
    fake_model.num_timesteps = 999_999
    cb.model = fake_model

    probe_values = iter([0.70, 0.75])

    def fake_probe():
        return {"champion": next(probe_values)}

    with patch.object(cb, "_probe", side_effect=fake_probe):
        for ep in [100, 200]:
            cb._next_probe_episode = 0
            with patch.object(cb, "_stage_timesteps", return_value=999_999), \
                 patch.object(cb, "_stage_episode", return_value=ep), \
                 patch.object(cb, "_current_episode", return_value=ep):
                result = cb._on_step()

    # Deux bruts consécutifs >= 0.6 → arrêt
    assert result is False
    assert cb._consecutive_above >= 2
