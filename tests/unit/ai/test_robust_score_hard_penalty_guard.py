"""
Verrous du score robuste : penalite hard mesurable, et tag TensorBoard publie.

Le split holdout hard est une feature EN SOMMEIL (pas de scenarios/holdout_hard/ ni de
callback_params.holdout_hard_scenarios aujourd'hui), donc l'evaluation ne produit pas
`holdout_hard_mean`. Tant que `robust_penalty_hard > 0`, la config annonce une penalite
que le score ne porte pas : c'est ce mensonge que ces tests verrouillent, aux DEUX endroits
ou il peut naitre — au demarrage (cas statique) et au calcul du score (filet).
"""

from collections import deque
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple, cast

import pytest

from ai.training_callbacks import BotEvaluationCallback


class _RecordingWriter:
    """Capture les scalaires TensorBoard pour verrouiller tag ET valeur."""

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, tag: str, value: float, step: int) -> None:
        self.scalars.append((tag, float(value), int(step)))


class _FalsyTracker:
    """
    Tracker present mais faux-y.

    `if self.metrics_tracker:` (log_bot_evaluations, log_faction_scores) est saute, tandis
    que `if self.metrics_tracker is not None:` (ecriture du score robuste) s'execute — ces
    tests n'observent ainsi QUE le score robuste.
    """

    def __init__(self, writer: _RecordingWriter) -> None:
        self.writer = writer

    def __bool__(self) -> bool:
        return False


def _callback_with_robust_scoring(
    penalty_hard: float,
) -> Tuple[BotEvaluationCallback, _RecordingWriter]:
    """Instance minimale : `_apply_eval_results` n'utilise que les attributs fixes ici."""
    cb = object.__new__(BotEvaluationCallback)
    cb.last_eval_results = None
    cb.last_eval_marker = None
    cb.model = cast(Any, SimpleNamespace(logger=None))
    cb.save_best_robust = True
    cb.robust_window = 1
    cb.combined_history = deque(maxlen=1)
    cb.robust_drawdown_penalty = 0.5
    cb.robust_penalty_bot = 0.12
    cb.robust_penalty_hard = penalty_hard
    cb.model_gating_min_worst_bot = 0.25
    cb.model_gating_min_worst_scenario_combined = 0.3
    cb.best_combined_win_rate = 1.0
    cb.best_early_stop_score = 1.0
    cb.best_robust_score = 1.0
    cb.early_stopping_patience = 0
    cb.save_best_min_episodes = 10**9
    cb.best_model_save_path = None
    cb.save_best_robust_seed = False

    writer = _RecordingWriter()
    cb.metrics_tracker = cast(Any, _FalsyTracker(writer))
    return cb, writer


def _results() -> Dict[str, Any]:
    """Evaluation saine, SANS `holdout_hard_mean` — l'etat reel du depot."""
    return {
        "total_failed_episodes": 0,
        "total_timeout_episodes": 0,
        "total_error_episodes": 0,
        "truncations": [],
        "eval_duration_seconds": 1.0,
        "total_episodes_played": 600,
        "combined": 0.4,
        "random": 0.5,
        "greedy": 0.4,
        "defensive": 0.35,
        "control": 0.3,
        "adaptive": 0.3,
        "value_trade": 0.3,
        "faction_scores": {},
        "scenario_scores": {},
    }


def _gate_always_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BotEvaluationCallback, "_evaluate_model_gate", lambda self, r, m: True)


def test_configured_hard_penalty_without_measure_skips_the_scoring_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Filet au calcul : la penalite ne tombe pas a 0 en silence, MAIS ne tue pas le run.

    Le cas atteint ici est celui que `_compute_holdout_split_metrics` tolere deliberement
    (couverture incomplete des scenarios hard, "Keep evaluation running"). Le point de
    mesure est saute — ni courbe, ni selection de best robust model — comme le fait le
    chemin timeout. Scorer quand meme comparerait un score a deux termes avec un score a
    trois selon les evaluations.
    """
    cb, writer = _callback_with_robust_scoring(penalty_hard=0.2)
    _gate_always_passes(monkeypatch)
    cb._apply_eval_results(_results(), eval_marker=1000)
    assert writer.scalars == []
    assert cb.best_robust_score == 1.0  # inchange : aucune sauvegarde declenchee
    assert "Score robuste ignoré" in capsys.readouterr().out


def test_zero_hard_penalty_scores_without_hard_term(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A 0.0 la config ne promet rien : le score robuste se calcule, sans terme hard.

    Verifie le TAG et la VALEUR, pas seulement l'absence de levee :
    moving_average(0.4) - drawdown(0) - penalty_bot(0.12 * max(0, 0.25-0.3)^2 = 0) = 0.4.
    """
    cb, writer = _callback_with_robust_scoring(penalty_hard=0.0)
    _gate_always_passes(monkeypatch)
    cb._apply_eval_results(_results(), eval_marker=1000)
    assert list(cb.combined_history) == [0.4]
    assert writer.scalars == [("00_critical/o_robust_current_score", pytest.approx(0.4), 1000)]


def test_worst_bot_below_threshold_subtracts_the_bot_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le terme bot, lui, est bien applique : sans lui le score vaudrait 0.4."""
    cb, writer = _callback_with_robust_scoring(penalty_hard=0.0)
    _gate_always_passes(monkeypatch)
    results = _results()
    results["control"] = 0.05  # worst_bot 0.05 < tau_b 0.25 -> 0.12 * 0.2^2 = 0.0048
    cb._apply_eval_results(results, eval_marker=1000)
    assert writer.scalars[0][1] == pytest.approx(0.4 - 0.0048)


def _callback_for_construction_check(penalty_hard: float) -> BotEvaluationCallback:
    cb = object.__new__(BotEvaluationCallback)
    cb.robust_penalty_hard = penalty_hard
    cb.save_best_robust = True
    cb.training_config_name = "x1"
    cb.rewards_config_name = "ArmageddonAgent"
    cb.scenario_pool = "holdout"
    return cb


def _stub_callback_params(monkeypatch: pytest.MonkeyPatch, callback_params: Dict[str, Any]) -> None:
    monkeypatch.setattr(
        "ai.training_callbacks.get_config_loader",
        lambda: SimpleNamespace(
            load_agent_training_config=lambda agent, cfg: {"callback_params": callback_params}
        ),
    )


def test_hard_penalty_without_declared_split_is_refused_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Detection STATIQUE : refusee au demarrage, pas apres `robust_window` evaluations.

    Le controle au calcul du score n'est atteint qu'au 10 000e episode avec le profil x1
    (bot_eval_freq=2000 x robust_window=5) — trop tard pour une incoherence de config.
    """
    _stub_callback_params(monkeypatch, {})
    with pytest.raises(ValueError, match=r"hard holdout split cannot be measured"):
        _callback_for_construction_check(0.2)._validate_hard_penalty_is_measurable()


def test_declared_hard_split_passes_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_callback_params(monkeypatch, {"holdout_hard_scenarios": ["holdout_hard_bot-1"]})
    _callback_for_construction_check(0.2)._validate_hard_penalty_is_measurable()


def test_declared_hard_split_but_training_pool_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le split hard n'est agrege que sur le pool holdout (_compute_holdout_split_metrics)."""
    _stub_callback_params(monkeypatch, {"holdout_hard_scenarios": ["holdout_hard_bot-1"]})
    cb = _callback_for_construction_check(0.2)
    cb.scenario_pool = "training"
    with pytest.raises(ValueError, match=r"hard holdout split cannot be measured"):
        cb._validate_hard_penalty_is_measurable()


def test_zero_hard_penalty_skips_construction_check() -> None:
    """A 0.0, aucune promesse : pas de lecture de config, pas de levee."""
    # Aucun stub de config_loader : une lecture de config ferait echouer ce test.
    _callback_for_construction_check(0.0)._validate_hard_penalty_is_measurable()
