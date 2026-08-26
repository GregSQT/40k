"""Tests pour le gate benchmark_floor et le détecteur stop_on_no_generalization (§4.D).

Deux invariants :
1. benchmark_floor gate (5e check) — un modèle sous le plancher n'est pas sauvegardé.
2. stop_on_no_generalization counter — incrémente quand benchmark < seuil ET combined améliore ;
   arrête (should_stop_early) quand le compteur atteint le seuil configuré.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from ai.training_callbacks import BotEvaluationCallback


_CFG_WITH_BENCH_KEYS: Dict[str, Any] = {
    "callback_params": {
        "bot_eval_weights": {
            "reference_balanced": 0.34,
            "reference_denial": 0.33,
            "reference_reactive": 0.33,
        },
        "bot_eval_final": 100,
        "eval_deterministic": True,
    }
}

_CFG_WITHOUT_BENCH_KEYS: Dict[str, Any] = {
    "callback_params": {
        "bot_eval_weights": {
            "greedy": 0.5,
            "defensive": 0.5,
        },
        "bot_eval_final": 100,
        "eval_deterministic": True,
    }
}


def _make_loader_mock(cfg: Dict[str, Any]) -> MagicMock:
    loader = MagicMock()
    loader.load_agent_training_config.return_value = cfg
    return loader


def _make_callback(**kwargs) -> BotEvaluationCallback:
    """Construit un BotEvaluationCallback minimal pour tester le gate.

    Patche get_config_loader pour éviter le chargement de configs réelles ;
    la config fictive inclut les clés benchmark afin que la validation
    model_gating_min_benchmark_floor > 0.0 passe à l'initialisation.
    """
    defaults: Dict[str, Any] = {
        "scenario_pool": "holdout",
        "training_config_name": "x1",
        "rewards_config_name": "x1",
        "model_gating_enabled": True,
        "model_gating_min_combined": 0.5,
        "model_gating_min_worst_bot": 0.3,
        "model_gating_min_worst_scenario_combined": 0.3,
        "model_gating_min_vs_control": 0.0,
        "model_gating_min_benchmark_floor": 0.0,
        "stop_on_no_generalization": 0,
    }
    defaults.update(kwargs)
    mock_loader = _make_loader_mock(_CFG_WITH_BENCH_KEYS)
    with patch("ai.training_callbacks.get_config_loader", return_value=mock_loader):
        cb = BotEvaluationCallback(**defaults)
    # Câbler un faux model
    fake_model = MagicMock()
    fake_model.logger = None
    cb.model = fake_model
    return cb


def _base_results(combined: float = 0.7, worst_bot: float = 0.5) -> Dict[str, Any]:
    """Résultats d'évaluation minimaux qui satisfont les 4 checks existants."""
    return {
        "combined": combined,
        # Bots de sélection
        "greedy": worst_bot,
        "defensive": 0.8,
        "control": 0.6,
        "adaptive": 0.7,
        "value_trade": 0.6,
        "racer": 0.7,
        "endgame": 0.7,
        "alpha": 0.7,
        "attrition": 0.7,
        "decapitation": 0.7,
        "scorer": 0.7,
        # Holdout scellé
        "tactical": 0.65,
        # Benchmarks
        "reference_balanced": 0.6,
        "reference_denial": 0.55,
        "reference_reactive": 0.58,
        "scenario_scores": {
            "s1": {"combined": combined},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 1. Paramètres invalides levant au __init__
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_benchmark_floor_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="model_gating_min_benchmark_floor"):
        _make_callback(model_gating_min_benchmark_floor=1.5)


def test_stop_on_no_generalization_negative_raises() -> None:
    with pytest.raises(ValueError, match="stop_on_no_generalization"):
        _make_callback(stop_on_no_generalization=-1)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 2. benchmark_floor gate (5e check)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_gate_passes_when_benchmark_floor_disabled() -> None:
    """0.0 = plancher désarmé : gate passe même si les benchmarks sont faibles."""
    cb = _make_callback(model_gating_min_benchmark_floor=0.0)
    results = _base_results()
    results["reference_balanced"] = 0.1
    results["reference_denial"] = 0.1
    results["reference_reactive"] = 0.1

    gate_pass = cb._evaluate_model_gate(results, eval_marker=1000)
    assert gate_pass is True


def test_gate_fails_when_benchmark_floor_below_threshold() -> None:
    """Plancher armé + au moins un benchmark sous le seuil → gate FAIL."""
    cb = _make_callback(model_gating_min_benchmark_floor=0.5)
    results = _base_results()
    results["reference_balanced"] = 0.4  # < 0.5
    results["reference_denial"] = 0.6
    results["reference_reactive"] = 0.6

    gate_pass = cb._evaluate_model_gate(results, eval_marker=1000)
    assert gate_pass is False


def test_gate_passes_when_all_benchmarks_above_floor() -> None:
    """Tous les benchmarks au-dessus du plancher → le 5e check ne bloque pas."""
    cb = _make_callback(model_gating_min_benchmark_floor=0.4)
    results = _base_results()
    results["reference_balanced"] = 0.5
    results["reference_denial"] = 0.5
    results["reference_reactive"] = 0.5

    gate_pass = cb._evaluate_model_gate(results, eval_marker=1000)
    assert gate_pass is True


def test_gate_benchmark_check_appears_in_history() -> None:
    """Quand le plancher est armé, benchmark_floor apparaît dans l'historique de checks."""
    cb = _make_callback(model_gating_min_benchmark_floor=0.5)
    results = _base_results()
    results["reference_balanced"] = 0.3
    results["reference_denial"] = 0.3
    results["reference_reactive"] = 0.3

    cb._evaluate_model_gate(results, eval_marker=1000)
    assert cb.gating_history, "Aucun historique produit"
    checks = cb.gating_history[-1]["checks"]
    labels = [c["label"] for c in checks]
    assert "benchmark_floor" in labels


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 3. stop_on_no_generalization counter
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_non_generalizing_counter_increments_when_floor_fails_and_combined_improves() -> None:
    """Compteur monte quand benchmark_floor échoue ET combined s'améliore."""
    cb = _make_callback(
        model_gating_min_benchmark_floor=0.6,
        stop_on_no_generalization=5,
    )
    assert cb.non_generalizing_consecutive == 0

    results = _base_results(combined=0.8)
    results["reference_balanced"] = 0.3  # < 0.6 → floor fail
    results["reference_denial"] = 0.3
    results["reference_reactive"] = 0.3

    cb._evaluate_model_gate(results, eval_marker=1000)
    assert cb.non_generalizing_consecutive == 1


def test_non_generalizing_counter_triggers_stop_early() -> None:
    """Quand le compteur atteint stop_on_no_generalization, should_stop_early devient True."""
    cb = _make_callback(
        model_gating_min_benchmark_floor=0.6,
        stop_on_no_generalization=2,
    )
    results = _base_results(combined=0.8)
    results["reference_balanced"] = 0.3
    results["reference_denial"] = 0.3
    results["reference_reactive"] = 0.3

    # Première éval : compteur = 1.
    cb._evaluate_model_gate(results, eval_marker=1000)
    assert cb.non_generalizing_consecutive == 1
    assert not cb.should_stop_early

    # combined_score doit dépasser best_gating_criteria_mean pour déclencher.
    results2 = dict(results)
    results2["combined"] = 0.9  # amélioration
    cb._evaluate_model_gate(results2, eval_marker=2000)
    assert cb.should_stop_early, "should_stop_early attendu après 2 évals non-généralisantes"


def test_non_generalizing_counter_resets_when_floor_passes() -> None:
    """Le compteur se remet à 0 quand le benchmark_floor repasse au-dessus du seuil."""
    cb = _make_callback(
        model_gating_min_benchmark_floor=0.4,
        stop_on_no_generalization=5,
    )
    # Première éval — floor fail.
    results_fail = _base_results(combined=0.8)
    results_fail["reference_balanced"] = 0.2
    results_fail["reference_denial"] = 0.2
    results_fail["reference_reactive"] = 0.2
    cb._evaluate_model_gate(results_fail, eval_marker=1000)
    assert cb.non_generalizing_consecutive == 1

    # Deuxième éval — floor pass.
    results_pass = _base_results(combined=0.7)
    results_pass["reference_balanced"] = 0.5
    results_pass["reference_denial"] = 0.5
    results_pass["reference_reactive"] = 0.5
    cb._evaluate_model_gate(results_pass, eval_marker=2000)
    assert cb.non_generalizing_consecutive == 0


def test_non_generalizing_disabled_by_zero() -> None:
    """stop_on_no_generalization=0 désarme le détecteur : should_stop_early reste False."""
    cb = _make_callback(
        model_gating_min_benchmark_floor=0.9,  # plancher très élevé
        stop_on_no_generalization=0,
    )
    for i in range(10):
        results = _base_results(combined=float(i) * 0.1)
        results["reference_balanced"] = 0.01
        results["reference_denial"] = 0.01
        results["reference_reactive"] = 0.01
        cb._evaluate_model_gate(results, eval_marker=i * 1000)

    assert not cb.should_stop_early


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 4. Validation à l'initialisation (§T1 — configuration incohérente)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_init_raises_when_floor_gt0_and_no_benchmark_keys_in_weights() -> None:
    """Seuil > 0.0 sans aucune clé benchmark dans bot_eval_weights → ValueError au __init__."""
    mock_loader = _make_loader_mock(_CFG_WITHOUT_BENCH_KEYS)
    with patch("ai.training_callbacks.get_config_loader", return_value=mock_loader):
        with pytest.raises(ValueError, match="model_gating_min_benchmark_floor"):
            BotEvaluationCallback(
                scenario_pool="holdout",
                training_config_name="x1",
                rewards_config_name="x1",
                model_gating_enabled=True,
                model_gating_min_combined=0.5,
                model_gating_min_worst_bot=0.3,
                model_gating_min_worst_scenario_combined=0.3,
                model_gating_min_vs_control=0.0,
                model_gating_min_benchmark_floor=0.5,
                stop_on_no_generalization=0,
            )


def test_init_passes_when_floor_zero_and_no_benchmark_keys_in_weights() -> None:
    """Seuil = 0.0 (plancher désarmé) sans clé benchmark → aucune erreur."""
    mock_loader = _make_loader_mock(_CFG_WITHOUT_BENCH_KEYS)
    with patch("ai.training_callbacks.get_config_loader", return_value=mock_loader):
        cb = BotEvaluationCallback(
            scenario_pool="holdout",
            training_config_name="x1",
            rewards_config_name="x1",
            model_gating_enabled=True,
            model_gating_min_combined=0.5,
            model_gating_min_worst_bot=0.3,
            model_gating_min_worst_scenario_combined=0.3,
            model_gating_min_vs_control=0.0,
            model_gating_min_benchmark_floor=0.0,
            stop_on_no_generalization=0,
        )
    assert cb.model_gating_min_benchmark_floor == 0.0


def test_init_passes_when_floor_gt0_and_benchmark_keys_present() -> None:
    """Seuil > 0.0 avec au moins une clé benchmark dans bot_eval_weights → aucune erreur."""
    mock_loader = _make_loader_mock(_CFG_WITH_BENCH_KEYS)
    with patch("ai.training_callbacks.get_config_loader", return_value=mock_loader):
        cb = BotEvaluationCallback(
            scenario_pool="holdout",
            training_config_name="x1",
            rewards_config_name="x1",
            model_gating_enabled=True,
            model_gating_min_combined=0.5,
            model_gating_min_worst_bot=0.3,
            model_gating_min_worst_scenario_combined=0.3,
            model_gating_min_vs_control=0.0,
            model_gating_min_benchmark_floor=0.5,
            stop_on_no_generalization=0,
        )
    assert cb.model_gating_min_benchmark_floor == 0.5
