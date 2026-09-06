"""Tests pour la sonde d'apprentissage (training_probe_every_n_evals)
de BotEvaluationCallback.

Vérifie :
- training_probe_every_n_evals=0 → sonde désactivée (flag toujours False)
- training_probe_every_n_evals=N → flag True exactement au Nème eval
- Validation : valeur négative lève ValueError
- Logging dans _apply_eval_results : add_scalar appelé iff le champ est présent
"""
import pytest
from unittest.mock import MagicMock, patch, call


def _make_callback(probe_every=0):
    """Construit un BotEvaluationCallback minimal avec training_probe_every_n_evals."""
    from ai.training_callbacks import BotEvaluationCallback

    cb = BotEvaluationCallback.__new__(BotEvaluationCallback)
    # Attributs minimaux pour les méthodes testées
    cb.training_probe_every_n_evals = probe_every
    cb._next_eval_run_training_probe = False
    cb.eval_count = 0
    return cb


def _set_eval_count_and_trigger(cb, eval_count: int) -> None:
    """Simule la logique de _on_step après eval_count = N."""
    cb.eval_count = eval_count
    cb._next_eval_run_training_probe = (
        cb.training_probe_every_n_evals > 0
        and cb.eval_count % cb.training_probe_every_n_evals == 0
    )


class TestTrainingProbeFlag:
    def test_disabled_never_sets_flag(self):
        cb = _make_callback(probe_every=0)
        for n in range(1, 10):
            _set_eval_count_and_trigger(cb, n)
            assert cb._next_eval_run_training_probe is False

    def test_every_3_fires_at_3_6_9(self):
        cb = _make_callback(probe_every=3)
        expected = {3: True, 6: True, 9: True}
        for n in range(1, 12):
            _set_eval_count_and_trigger(cb, n)
            assert cb._next_eval_run_training_probe is expected.get(n, False), (
                f"eval_count={n}: expected {expected.get(n, False)}, "
                f"got {cb._next_eval_run_training_probe}"
            )

    def test_every_1_fires_every_eval(self):
        cb = _make_callback(probe_every=1)
        for n in range(1, 6):
            _set_eval_count_and_trigger(cb, n)
            assert cb._next_eval_run_training_probe is True


class TestTrainingProbeValidation:
    def test_negative_raises(self):
        from ai.training_callbacks import BotEvaluationCallback
        with pytest.raises(ValueError, match="training_probe_every_n_evals"):
            BotEvaluationCallback(
                scenario_pool="holdout",
                eval_freq=1000,
                training_config_name="x1",
                rewards_config_name="x1",
                model_gating_min_vs_control=0.0,
                training_probe_every_n_evals=-1,
            )

    def test_zero_accepted(self):
        from ai.training_callbacks import BotEvaluationCallback
        cb = BotEvaluationCallback(
            scenario_pool="holdout",
            eval_freq=1000,
            training_config_name="x1",
            rewards_config_name="x1",
            model_gating_min_vs_control=0.0,
            training_probe_every_n_evals=0,
        )
        assert cb.training_probe_every_n_evals == 0


class TestTrainingProbeLogging:
    def _make_results(self, with_probe: bool) -> dict:
        r = {
            "combined": 0.6,
            "total_failed_episodes": 0,
            "total_timeout_episodes": 0,
            "total_error_episodes": 0,
            "eval_duration_seconds": 1.0,
            "total_episodes_played": 10,
            "faction_scores": {},
            "faction_bot_win_rates": {},
            "seat_scores": {},
            "seat_gap": None,
            "seat_bot_win_rates": {},
            "agent_roster_bot_win_rates": {},
            "opponent_roster_bot_win_rates": {},
            "scenario_scores": {"s1": {"combined": 0.6, "worst_bot_score": 0.5}},
            "scenario_bot_stats": {},
            "truncations": [],
            "roster_gap": None,
        }
        if with_probe:
            r["_training_probe_combined"] = 0.75
        return r

    def test_add_scalar_called_when_probe_present(self):
        from ai.training_callbacks import BotEvaluationCallback

        cb = BotEvaluationCallback.__new__(BotEvaluationCallback)
        # Attributs minimaux pour _apply_eval_results
        cb.last_eval_results = None
        cb.last_eval_marker = None
        cb.metrics_tracker = MagicMock()
        cb.metrics_tracker.writer = MagicMock()
        cb.model_gating_enabled = False
        cb.model_gating_min_vs_control = 0.0
        cb.last_gate_pass = None
        cb.best_combined_win_rate = 0.0
        cb.best_model_save_path = None
        cb.save_best_robust = False
        cb.robust_penalty_hard = 0.0
        cb.early_stopping_patience = 0
        cb.best_early_stop_score = -float("inf")
        cb.evals_without_improvement = 0
        cb.should_stop_early = False
        cb.combined_history = MagicMock()
        cb.combined_history.__len__ = lambda self: 0
        cb.gating_history = []
        cb.gating_pass_count = 0
        cb.gating_fail_count = 0
        cb.gating_skipped_unreliable_count = 0
        cb.thresholds_ever_passed = False
        cb.best_gating_criteria_mean = None
        cb.model = MagicMock()
        cb.model.logger = None
        cb.gate_display_state = None
        cb._mark_unreliable_eval_skip = MagicMock()
        cb._evaluate_model_gate = MagicMock(return_value=True)
        cb._log_scenario_scores = MagicMock()
        cb._save_model_with_vecnormalize = MagicMock()
        cb._add_blocking_eval_seconds = MagicMock()
        cb.save_best_min_episodes = 0

        # Avec sonde
        results_with = self._make_results(with_probe=True)
        cb._apply_eval_results(results_with, eval_marker=5000)

        calls = [str(c) for c in cb.metrics_tracker.writer.add_scalar.call_args_list]
        matching = [c for c in calls if "training_combined" in c]
        assert matching, (
            f"add_scalar('bot_eval/training_combined') non appelé. Appels: {calls}"
        )
        # Vérifie la valeur
        for c in cb.metrics_tracker.writer.add_scalar.call_args_list:
            if "training_combined" in str(c):
                assert c.args[1] == pytest.approx(0.75)

    def test_add_scalar_not_called_when_probe_absent(self):
        from ai.training_callbacks import BotEvaluationCallback

        cb = BotEvaluationCallback.__new__(BotEvaluationCallback)
        cb.last_eval_results = None
        cb.last_eval_marker = None
        cb.metrics_tracker = MagicMock()
        cb.metrics_tracker.writer = MagicMock()
        cb.model_gating_enabled = False
        cb.model_gating_min_vs_control = 0.0
        cb.last_gate_pass = None
        cb.best_combined_win_rate = 0.0
        cb.best_model_save_path = None
        cb.save_best_robust = False
        cb.robust_penalty_hard = 0.0
        cb.early_stopping_patience = 0
        cb.best_early_stop_score = -float("inf")
        cb.evals_without_improvement = 0
        cb.should_stop_early = False
        cb.combined_history = MagicMock()
        cb.combined_history.__len__ = lambda self: 0
        cb.gating_history = []
        cb.gating_pass_count = 0
        cb.gating_fail_count = 0
        cb.gating_skipped_unreliable_count = 0
        cb.thresholds_ever_passed = False
        cb.best_gating_criteria_mean = None
        cb.model = MagicMock()
        cb.model.logger = None
        cb.gate_display_state = None
        cb._mark_unreliable_eval_skip = MagicMock()
        cb._evaluate_model_gate = MagicMock(return_value=True)
        cb._log_scenario_scores = MagicMock()
        cb._save_model_with_vecnormalize = MagicMock()
        cb._add_blocking_eval_seconds = MagicMock()
        cb.save_best_min_episodes = 0

        # Sans sonde
        results_without = self._make_results(with_probe=False)
        cb._apply_eval_results(results_without, eval_marker=5000)

        calls = [str(c) for c in cb.metrics_tracker.writer.add_scalar.call_args_list]
        matching = [c for c in calls if "training_combined" in c]
        assert not matching, (
            f"add_scalar('bot_eval/training_combined') appelé alors qu'il ne devrait pas. Appels: {calls}"
        )
