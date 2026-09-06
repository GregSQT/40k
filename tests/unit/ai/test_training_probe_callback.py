"""Tests pour la sonde d'apprentissage (training_probe_every_n_evals)
de BotEvaluationCallback.

Vérifie :
- training_probe_every_n_evals=0 → sonde désactivée (run_training_probe toujours False)
- training_probe_every_n_evals=N → run_training_probe True exactement au Nème eval
- Validation : valeur négative lève ValueError
- Logging dans _apply_eval_results : add_scalar appelé iff le champ est présent
- _evaluate_against_bots : log_eval_truncations NON appelé pour la sonde (pas holdout)
"""
import pytest
from unittest.mock import MagicMock, patch


def _compute_probe_flag(training_probe_every_n_evals: int, eval_count: int) -> bool:
    """Réplique la logique de _on_step pour run_training_probe."""
    return (
        training_probe_every_n_evals > 0
        and eval_count % training_probe_every_n_evals == 0
    )


class TestTrainingProbeFlag:
    def test_disabled_never_sets_flag(self):
        for n in range(1, 10):
            assert _compute_probe_flag(0, n) is False

    def test_every_3_fires_at_3_6_9(self):
        expected = {3: True, 6: True, 9: True}
        for n in range(1, 12):
            result = _compute_probe_flag(3, n)
            assert result is expected.get(n, False), (
                f"eval_count={n}: expected {expected.get(n, False)}, got {result}"
            )

    def test_every_1_fires_every_eval(self):
        for n in range(1, 6):
            assert _compute_probe_flag(1, n) is True


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


def _make_apply_cb():
    """Construit un BotEvaluationCallback.__new__ minimal pour appeler _apply_eval_results."""
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
    return cb


def _base_results(with_probe: bool) -> dict:
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


class TestTrainingProbeLogging:
    def test_add_scalar_called_when_probe_present(self):
        cb = _make_apply_cb()
        cb._apply_eval_results(_base_results(with_probe=True), eval_marker=5000)

        calls = cb.metrics_tracker.writer.add_scalar.call_args_list
        matching = [c for c in calls if "training_combined" in str(c)]
        assert matching, (
            f"add_scalar('bot_eval/training_combined') non appelé. Appels: {calls}"
        )
        for c in calls:
            if "training_combined" in str(c):
                assert c.args[1] == pytest.approx(0.75)

    def test_add_scalar_not_called_when_probe_absent(self):
        cb = _make_apply_cb()
        cb._apply_eval_results(_base_results(with_probe=False), eval_marker=5000)

        calls = cb.metrics_tracker.writer.add_scalar.call_args_list
        matching = [c for c in calls if "training_combined" in c]
        assert not matching, (
            f"add_scalar('bot_eval/training_combined') appelé alors qu'il ne devrait pas. Appels: {calls}"
        )


class TestTrainingProbeNoTruncationLog:
    """La sonde ne doit PAS appeler log_eval_truncations (diagnostic seul, pas holdout)."""

    def test_truncations_not_logged_for_training_probe(self):
        """evaluate_against_bots appelé avec scenario_pool='training' ne logue pas ses troncatures."""
        import ai.bot_evaluation
        from ai.training_callbacks import BotEvaluationCallback
        from typing import Any, cast

        probe_truncations: list = ["t1", "t2"]

        call_count: dict = {"holdout": 0, "training": 0}

        def _fake_eval(**kwargs):
            pool = kwargs.get("scenario_pool", "holdout")
            truncations = probe_truncations if pool == "training" else []
            return {
                "win_rate": 0.5, "combined": 0.6,
                "truncations": truncations,
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
                "scenario_scores": {},
                "scenario_bot_stats": {},
                "roster_gap": None,
            }

        cb = BotEvaluationCallback.__new__(BotEvaluationCallback)
        cb.training_config_name = "x1"
        cb.rewards_config_name = "CoreAgent"
        cb.scenario_pool = "holdout"
        cb.n_eval_episodes = 10
        cb.eval_deterministic = True
        cb.show_eval_progress = False
        cb.async_eval_enabled = False
        cb.eval_count = 3
        cb.model = cast(Any, object())
        cb.gate_display_state = None
        cb.intermediate_n_workers = None
        cb.metrics_tracker = MagicMock()

        logged_truncations: list = []
        cb.metrics_tracker.log_eval_truncations.side_effect = logged_truncations.extend

        with patch.object(ai.bot_evaluation, "evaluate_against_bots", side_effect=_fake_eval):
            results = cb._evaluate_against_bots(eval_marker=3000, run_training_probe=True)

        # La sonde a bien tourné
        assert "_training_probe_combined" in results, "sonde absente du résultat"

        # log_eval_truncations a été appelé UNE seule fois, pour le holdout (truncations=[])
        assert cb.metrics_tracker.log_eval_truncations.call_count == 1, (
            f"log_eval_truncations appelé {cb.metrics_tracker.log_eval_truncations.call_count} fois "
            f"(attendu 1 — holdout uniquement, pas la sonde)"
        )
        # et ce call portait les troncatures du holdout (vide), pas celles de la sonde
        first_call_arg = cb.metrics_tracker.log_eval_truncations.call_args_list[0].args[0]
        assert first_call_arg == [], (
            f"log_eval_truncations a reçu {first_call_arg!r} au lieu de [] (troncatures holdout)"
        )
