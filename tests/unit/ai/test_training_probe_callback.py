"""Tests pour la sonde d'apprentissage (training_probe_every_n_evals)
de BotEvaluationCallback.

Vérifie :
- training_probe_every_n_evals=N → _evaluate_against_bots reçoit run_training_probe=True
  exactement aux évaluations 3, 6 et 9 — argument RÉEL transmis par _on_step, jamais une
  valeur recalculée par le test
- Validation : valeur négative lève ValueError
- Logging dans _apply_eval_results : add_scalar appelé iff le champ est présent
- _evaluate_against_bots : log_eval_truncations NON appelé pour la sonde (pas holdout)
"""
import pytest
from unittest.mock import MagicMock, patch


class _NullTimer:
    """Substitut du chronomètre de blocage : aucune éval réelle à mesurer ici."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> bool:
        return False


class TestTrainingProbeFlagFromOnStep:
    """run_training_probe vient du calcul RÉEL de _on_step, jamais d'une réplique.

    Inverser la condition en production (`!= 0` au lieu de `== 0`) doit faire rougir ce test.
    """

    def _make_callback(self):
        from ai.training_callbacks import BotEvaluationCallback

        cb = BotEvaluationCallback.__new__(BotEvaluationCallback)
        cb.use_episode_freq = False
        cb.eval_freq = 10
        cb.eval_count = 0
        cb.num_timesteps = 0
        cb.async_eval_enabled = False
        cb.early_stopping_patience = 0
        cb.should_stop_early = False
        cb.training_probe_every_n_evals = 3
        return cb

    def _collect_probe_flags(self, n_evals: int = 3, steps: int = 9) -> list:
        """Retourne les flags run_training_probe transmis par _on_step sur <steps> évaluations."""
        cb = self._make_callback()
        cb.training_probe_every_n_evals = n_evals
        flags: list = []

        def _fake_eval(marker, run_training_probe: bool = False, **_):
            flags.append(run_training_probe)
            return {}

        cb._evaluate_against_bots = _fake_eval  # type: ignore[method-assign]
        cb._apply_eval_results = lambda r, m: None  # type: ignore[method-assign]
        cb._blocking_eval_timer = _NullTimer  # type: ignore[method-assign]

        for step in range(1, steps + 1):
            cb.num_timesteps = step * 10
            cb._on_step()
        return flags

    def test_probe_never_fires_when_n_is_zero(self):
        """n=0 → sonde désactivée ; run_training_probe doit être False à chaque eval."""
        flags = self._collect_probe_flags(n_evals=0, steps=9)
        assert len(flags) == 9, f"9 évals attendues, obtenues : {len(flags)}"
        assert not any(flags), (
            f"run_training_probe=True inattendu avec n=0 : {flags}"
        )

    def test_probe_fires_at_every_eval_when_n_is_1(self):
        """n=1 → sonde déclenchée à chaque eval (eval_count % 1 == 0 toujours vrai)."""
        flags = self._collect_probe_flags(n_evals=1, steps=9)
        assert len(flags) == 9, f"9 évals attendues, obtenues : {len(flags)}"
        assert all(flags), (
            f"run_training_probe=False inattendu avec n=1 : {flags}"
        )

    def test_probe_fires_at_evals_3_6_9_and_nowhere_else(self):
        """_on_step transmet run_training_probe=True à _evaluate_against_bots exactement
        aux évaluations 3, 6 et 9 ; False partout ailleurs."""
        probe_flags = self._collect_probe_flags(n_evals=3, steps=9)

        assert len(probe_flags) == 9, f"9 évals attendues, obtenues : {len(probe_flags)}"
        expected = {3: True, 6: True, 9: True}
        for i, flag in enumerate(probe_flags, start=1):
            wanted = expected.get(i, False)
            assert flag is wanted, (
                f"eval {i}: run_training_probe attendu {wanted}, reçu {flag}"
            )


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
        matching = [c for c in calls if "training_combined" in str(c)]
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
