from collections import deque

import pytest

import ai.metrics_tracker as mt
from ai.metrics_tracker import TrainingMonitor, W40KMetricsTracker, create_metrics_tracker


class _DummyWriter:
    def __init__(self):
        self.scalars = []
        self.flushed = 0
        self.closed = 0

    def add_scalar(self, key, value, step):
        self.scalars.append((key, value, step))

    def flush(self):
        self.flushed += 1

    def close(self):
        self.closed += 1


def _tracker_stub() -> W40KMetricsTracker:
    t = W40KMetricsTracker.__new__(W40KMetricsTracker)
    t.writer = _DummyWriter()
    t.episode_count = 12
    t.step_count = 0
    t.win_rate_window = deque([1.0] * 12, maxlen=100)
    t.episode_reward_winner_pairs = deque(maxlen=200)
    t.all_episode_rewards = [1.0] * 12
    t.all_episode_wins = [1.0] * 12
    t.all_episode_lengths = [10] * 12
    t.hyperparameter_tracking = {
        "learning_rates": [3e-4] * 12,
        "entropy_losses": [0.1] * 12,
        "policy_losses": [],
        "value_losses": [],
        "clip_fractions": [0.2] * 12,
        "approx_kls": [0.01] * 12,
        "explained_variances": [],
    }
    t.reward_components = {
        "base_actions": [],
        "result_bonuses": [],
        "tactical_bonuses": [],
        "situational": [],
        "penalties": [],
    }
    t.position_scores = []
    t.compliance_data = {
        "units_per_step": [],
        "phase_end_reasons": [],
        "tracking_violations": [],
    }
    t.reward_mapper_stats = {
        "shooting_priority_correct": 0,
        "shooting_priority_total": 0,
        "movement_tactical_bonuses": 0,
        "movement_actions": 0,
        "mapper_failures": 0,
    }
    t.phase_stats = {
        "movement": {"moved": 0, "waited": 0, "fled": 0},
        "shooting": {"shot": 0, "skipped": 0},
        "charge": {"charged": 0, "skipped": 0},
        "fight": {"fought": 0, "skipped": 0},
    }
    t.combat_effectiveness = {
        "shoot_kills": 0,
        "melee_kills": 0,
        "charge_successes": 0,
        "victory_points_cumulative": 0.0,
    }
    t.combat_history = {
        "shoot_kills": [],
        "melee_kills": [],
        "charge_successes": [],
        "victory_points_cumulative": [],
    }
    t.forcing_tracking = {
        "episodes_total": 0,
        "episodes_with_forced_unit": 0,
        "forced_unit_instances_total": 0,
        "per_unit_episode_counts": {},
        "per_unit_instance_counts": {},
        "baseline_combined": None,
        "baseline_worst_bot": None,
    }
    t.latest_gradient_norm = None
    t.bot_eval_combined = None
    t.latest_value_trade_ratio = None
    t.value_trade_ratio_history = []
    t.episode_tactical_data = {"total_actions": 0, "invalid_actions": 0, "valid_actions": 0}
    t.seat_aware = {
        "episodes_agent_p1": 0,
        "episodes_agent_p2": 0,
        "wins_agent_p1": 0.0,
        "wins_agent_p2": 0.0,
    }
    return t


def test_metric_slug_and_smoothed_metric() -> None:
    assert W40KMetricsTracker._metric_slug("My Unit#1") == "my_unit_1"
    with pytest.raises(ValueError, match=r"empty unit name"):
        W40KMetricsTracker._metric_slug("___")

    t = _tracker_stub()
    assert t._calculate_smoothed_metric([]) == 0.0
    assert t._calculate_smoothed_metric([1, 3], window_size=20) == 2.0
    assert t._calculate_smoothed_metric([1, 2, 3, 4], window_size=2) == 3.5


def test_performance_summary_contains_expected_keys() -> None:
    t = _tracker_stub()
    summary = t.get_performance_summary()
    assert summary["win_rate_100ep"] == 1.0
    assert summary["avg_reward_overall"] == 1.0
    assert summary["total_episodes"] == 12
    assert summary["win_rate_overall"] == 1.0
    assert summary["current_learning_rate"] == 3e-4
    assert abs(summary["avg_entropy_loss"] - 0.1) < 1e-9
    assert abs(summary["avg_clip_fraction"] - 0.2) < 1e-9
    assert abs(summary["avg_approx_kl"] - 0.01) < 1e-9


def test_training_monitor_health_alerts() -> None:
    monitor = TrainingMonitor({"min_win_rate": 0.6})
    alerts = monitor.check_training_health(
        {"win_rate_100ep": 0.4, "win_rate_overall": 0.3, "total_episodes": 50}
    )
    assert any("Win rate" in a for a in alerts)
    assert any("Overall win rate low" in a for a in alerts)
    assert any("Early training stage" in a for a in alerts)


def test_log_holdout_and_scenario_split_scores() -> None:
    t = _tracker_stub()
    t.log_holdout_split_metrics(
        {"holdout_regular_mean": 0.5, "holdout_hard_mean": 0.4, "holdout_overall_mean": 0.45}
    )
    keys = [k for k, _, _ in t.writer.scalars]
    assert "bot_eval/holdout_regular_mean" in keys
    assert "bot_eval/holdout_hard_mean" in keys
    assert "bot_eval/holdout_overall_mean" in keys

    t.log_scenario_split_scores({"training_bot_1": 0.9, "hard_bot_1": 0.2})
    keys2 = [k for k, _, _ in t.writer.scalars]
    assert "bot_split/training_bot_1" in keys2
    assert "bot_split/hard_bot_1" in keys2


def test_log_reward_decomposition_validation_and_trimming() -> None:
    t = _tracker_stub()
    with pytest.raises(KeyError, match=r"Missing required field"):
        t.log_reward_decomposition({"base_actions": 1})

    with pytest.raises(TypeError, match=r"must be numeric"):
        t.log_reward_decomposition(
            {
                "base_actions": "x",
                "result_bonuses": 1,
                "tactical_bonuses": 1,
                "situational": 1,
                "penalties": 1,
            }
        )

    for _ in range(105):
        t.log_reward_decomposition(
            {
                "base_actions": 1.0,
                "result_bonuses": 0.5,
                "tactical_bonuses": 0.2,
                "situational": 0.1,
                "penalties": -0.1,
            }
        )
    assert len(t.reward_components["base_actions"]) == 100


def test_log_position_score_and_close() -> None:
    t = _tracker_stub()
    t.log_position_score(None)
    assert t.position_scores == []
    for i in range(10):
        t.log_position_score(float(i))
    assert len(t.position_scores) == 10
    assert any(k == "game_tactical/avg_position_score" for k, _, _ in t.writer.scalars)
    t.close()
    assert t.writer.closed == 1


def test_create_metrics_tracker_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class DummyTracker:
        def __init__(self, agent_key, log_dir):
            created["agent_key"] = agent_key
            created["log_dir"] = log_dir

    monkeypatch.setattr(mt, "W40KMetricsTracker", DummyTracker)
    tracker = create_metrics_tracker("CoreAgent", {"tensorboard_log": "/tmp/tb"})
    assert created["agent_key"] == "CoreAgent"
    assert created["log_dir"] == "/tmp/tb"
    assert isinstance(tracker, DummyTracker)


def test_log_episode_end_and_tactical_metrics_runtime_paths() -> None:
    t = _tracker_stub()
    t.compute_and_log_phase_metrics = lambda: None
    t.log_critical_dashboard = lambda: None
    t.log_episode_end(
        {
            "total_reward": 3.0,
            "winner": 1,
            "episode_length": 20,
            "controlled_player": 1,
        }
    )
    assert t.episode_count == 13
    assert t.writer.flushed == 1
    assert t.seat_aware["episodes_agent_p1"] == 1

    t.log_tactical_metrics(
        {
            "shots_fired": 4,
            "hits": 2,
            "total_enemies": 2,
            "units_killed": 1,
            "damage_dealt": 3,
            "damage_received": 1,
            "units_lost": 1,
            "enemy_value_destroyed": 8.0,
            "ally_value_lost": 4.0,
            "valid_actions": 8,
            "invalid_actions": 2,
            "wait_actions": 1,
            "forced_unit_episode_has_controlled": 1,
            "forced_unit_instances_controlled": 2,
            "forced_unit_counts_controlled": {"My Unit": 2},
            "victory_points_diff_controlled_minus_opponent": 1.0,
        }
    )
    keys = [k for k, _, _ in t.writer.scalars]
    assert "game_tactical/shooting_accuracy" in keys
    assert "combat/h_value_trade_ratio" in keys
    assert "forcing/episodes_with_forced_unit_ratio" in keys


def test_compliance_mapper_phase_and_training_metrics_paths() -> None:
    t = _tracker_stub()
    t.log_aiturn_compliance(
        {
            "units_activated_this_step": 1,
            "phase_end_reason": "eligibility",
            "duplicate_activation_attempts": 0,
            "pool_corruption_detected": 0,
        }
    )
    t.log_reward_mapper_effectiveness(
        {
            "shooting_priority_correct": 1,
            "movement_had_tactical_bonus": True,
            "mapper_failed": False,
        }
    )
    t.log_phase_performance({"phase": "move", "action": "move", "was_flee": True})
    t.log_phase_performance({"phase": "shoot", "action": "shoot"})
    t.log_phase_performance({"phase": "charge", "action": "charge"})
    t.log_phase_performance({"phase": "fight", "action": "combat"})
    t.log_combat_kill("shoot")
    t.log_combat_kill("melee")
    t.log_combat_kill("charge")
    t.log_victory_points_cumulative(12.0)
    t.compute_and_log_phase_metrics()

    t.log_training_metrics(
        {
            "train/learning_rate": 3e-4,
            "train/policy_gradient_loss": -0.2,
            "train/value_loss": 0.3,
            "train/entropy_loss": 0.05,
            "train/ent_coef": 0.01,
            "train/clip_fraction": 0.2,
            "train/approx_kl": 0.01,
            "train/explained_variance": 0.4,
            "train/n_updates": 10,
            "train/gradient_norm": 1.2,
            "time/fps": 100,
        }
    )
    assert t.step_count == 1

    t.forcing_tracking["episodes_total"] = 1
    t.log_bot_evaluations(
        {"random": 0.5, "greedy": 0.6, "defensive": 0.4, "combined": 0.5, "holdout_hard_mean": 0.3},
        step=99,
    )
    keys = [k for k, _, _ in t.writer.scalars]
    assert "0_critical/b_worst_bot_score" in keys
    assert "0_critical/a_bot_eval_combined" in keys


def test_log_episode_end_rejects_invalid_controlled_player() -> None:
    t = _tracker_stub()
    with pytest.raises(ValueError, match=r"controlled_player must be 1 or 2"):
        t.log_episode_end(
            {
                "total_reward": 1.0,
                "winner": 1,
                "episode_length": 10,
                "controlled_player": 3,
            }
        )


def test_log_tactical_metrics_forcing_validation_errors() -> None:
    t = _tracker_stub()
    base = {
        "shots_fired": 1,
        "hits": 1,
        "total_enemies": 1,
        "units_killed": 1,
        "damage_dealt": 1,
        "damage_received": 1,
        "units_lost": 1,
        "enemy_value_destroyed": 1.0,
        "ally_value_lost": 1.0,
        "valid_actions": 1,
        "invalid_actions": 0,
        "wait_actions": 0,
        "victory_points_diff_controlled_minus_opponent": 0.0,
    }

    with pytest.raises(TypeError, match=r"forced_unit_counts_controlled.*dict"):
        t.log_tactical_metrics(
            {
                **base,
                "forced_unit_episode_has_controlled": 1,
                "forced_unit_instances_controlled": 1,
                "forced_unit_counts_controlled": [],
            }
        )

    with pytest.raises(ValueError, match=r"must be 0 or 1"):
        t.log_tactical_metrics(
            {
                **base,
                "forced_unit_episode_has_controlled": 2,
                "forced_unit_instances_controlled": 1,
                "forced_unit_counts_controlled": {"UnitA": 1},
            }
        )

    with pytest.raises(ValueError, match=r"must be > 0"):
        t.log_tactical_metrics(
            {
                **base,
                "forced_unit_episode_has_controlled": 1,
                "forced_unit_instances_controlled": 1,
                "forced_unit_counts_controlled": {"UnitA": 0},
            }
        )


def test_log_training_step_records_optional_fields() -> None:
    t = _tracker_stub()
    t.log_training_step({"exploration_rate": 0.2, "loss": 1.3, "learning_rate": 3e-4})
    keys = [k for k, _, _ in t.writer.scalars]
    assert "training_diagnostic/exploration_rate" in keys
    assert "training_detailed/loss" in keys
    assert "training_diagnostic/learning_rate" in keys
    assert t.step_count == 1
