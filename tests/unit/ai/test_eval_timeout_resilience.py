"""V11 §0.27 — le garde-fou d'evaluation distingue TIMEOUT (lenteur) et CRASH (bug moteur).

Bug d'origine (run `x5_new`, 2026-07-22) : a l'eval intermediaire du marker 2000, un task d'eval
a depasse `bot_eval_task_timeout_seconds` (3675 s mesures pour 3600 s de deadline). Les 500
episodes du pool ont ete marques `failed`, et `_apply_eval_results` levait `RuntimeError` sur
`total_failed_episodes > 0` — un run de 10 000 episodes tue par de la LENTEUR, alors qu'aucun
episode n'avait plante.

Invariant verrouille ici :
- un CRASH (exception worker) arrete toujours le training — c'est un bug, il ne doit pas etre absorbe ;
- un TIMEOUT n'arrete pas le training, mais la mesure tronquee ne doit alimenter AUCUN signal
  (gate de selection, best model, metrique de win-rate, early stopping, historique robuste) ;
- le gate de CURRICULUM refuse de valider une phase sur une eval non fiable.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _make_callback(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Instance minimale de BotEvaluationCallback, sans __init__ (pas de modele SB3 requis)."""
    from ai import training_callbacks

    callback = training_callbacks.BotEvaluationCallback.__new__(
        training_callbacks.BotEvaluationCallback
    )
    callback.last_eval_results = None
    callback.last_eval_marker = None
    callback.metrics_tracker = None
    return callback


def _results(
    *,
    failed: int,
    timeout: int,
    error: int,
    duration: float = 3675.0,
) -> Dict[str, Any]:
    return {
        "total_failed_episodes": failed,
        "total_timeout_episodes": timeout,
        "total_error_episodes": error,
        "eval_duration_seconds": duration,
        "total_episodes_played": 600,
        "combined": 0.42,
        "eval_reliable": failed == 0,
    }


def test_crash_still_stops_training(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un episode plante (exception worker) leve toujours — aucun assouplissement."""
    callback = _make_callback(monkeypatch)

    def _must_not_run(*_a: Any, **_k: Any) -> bool:
        raise AssertionError("le gate ne doit pas etre atteint quand un episode a plante")

    callback._evaluate_model_gate = _must_not_run

    with pytest.raises(RuntimeError, match="crashed episodes"):
        callback._apply_eval_results(_results(failed=100, timeout=0, error=100), eval_marker=2000)


def test_crash_stops_even_when_mixed_with_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout + crash simultanes : le crash prime, le training s'arrete."""
    callback = _make_callback(monkeypatch)
    callback._evaluate_model_gate = lambda *_a, **_k: True

    with pytest.raises(RuntimeError, match="crashed episodes"):
        callback._apply_eval_results(_results(failed=500, timeout=400, error=100), eval_marker=2000)


def test_timeout_does_not_stop_training(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Le cas du run reel : 500 episodes perdus sur timeout, ZERO crash → le training continue."""
    callback = _make_callback(monkeypatch)

    def _must_not_run(*_a: Any, **_k: Any) -> bool:
        raise AssertionError("une eval non fiable ne doit alimenter aucun gate")

    callback._evaluate_model_gate = _must_not_run

    callback._apply_eval_results(_results(failed=500, timeout=500, error=0), eval_marker=2000)

    out = capsys.readouterr().out
    assert "NON FIABLE" in out
    assert "TIMEOUT" in out
    # Le marker reste synchronise : le gate de curriculum ne doit pas se croire desynchronise.
    assert callback.last_eval_marker == 2000


def test_timeout_logs_a_counter_and_no_win_rate_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sur timeout : un compteur de diagnostic est loggue, mais AUCUN win-rate ne l'est."""
    callback = _make_callback(monkeypatch)
    callback._evaluate_model_gate = lambda *_a, **_k: True

    scalars: List[Any] = []

    class _Writer:
        def add_scalar(self, tag: str, value: float, step: int) -> None:
            scalars.append((tag, value, step))

    class _Tracker:
        writer = _Writer()

        def log_bot_evaluations(self, *_a: Any, **_k: Any) -> None:
            raise AssertionError("aucun win-rate tronque ne doit etre publie en metrique")

    callback.metrics_tracker = _Tracker()

    callback._apply_eval_results(_results(failed=500, timeout=500, error=0), eval_marker=2000)

    assert scalars == [("00_critical/0_eval_timeout_episodes", 500.0, 2000)]


def test_clean_eval_still_reaches_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-regression : une eval sans echec traverse le garde-fou et atteint le gate."""
    callback = _make_callback(monkeypatch)
    reached: Dict[str, Any] = {}

    def _gate(results: Dict[str, Any], eval_marker: int) -> bool:
        reached["marker"] = eval_marker
        # On coupe la suite du traitement ici : le reste du pipeline (best model, early
        # stopping) exige un vrai modele SB3, hors perimetre de ce verrou.
        raise _GateReached()

    class _GateReached(Exception):
        pass

    callback._evaluate_model_gate = _gate

    with pytest.raises(_GateReached):
        callback._apply_eval_results(_results(failed=0, timeout=0, error=0), eval_marker=2000)

    assert reached["marker"] == 2000


def test_aggregation_splits_timeout_and_error_causes() -> None:
    """`evaluate_against_bots` publie les deux causes separement (contrat de sortie).

    Verrou de CONTRAT lu sur le source : l'agregation vit au milieu d'une fonction de ~700
    lignes qui ouvre un ProcessPool et charge un modele — l'executer ici n'est pas possible.
    On verifie donc que les trois cles coexistent et que `total_error_episodes` est bien
    derive de la difference, pas recompte independamment (source unique).
    """
    from ai import bot_evaluation

    source = inspect.getsource(bot_evaluation.evaluate_against_bots)
    assert 'results["total_timeout_episodes"] = total_timeout_episodes' in source
    assert 'results["total_error_episodes"] = total_error_episodes' in source
    assert "total_error_episodes = total_failed_episodes - total_timeout_episodes" in source
    assert 'if r.get("timeout")' in source


def test_curriculum_gate_refuses_an_unreliable_eval() -> None:
    """Le gate de curriculum (train.py) exige `eval_reliable` avant de valider une phase.

    Verrou STRUCTUREL (AST) : la conjonction du gate doit contenir le nom `eval_reliable`.
    Sans lui, une eval tronquee pourrait faire franchir une phase de curriculum.
    """
    train_source = (PROJECT_ROOT / "ai" / "train.py").read_text(encoding="utf-8")
    tree = ast.parse(train_source)

    gate_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "gate_now" for t in node.targets
        )
    ]
    assert gate_assignments, "aucune affectation `gate_now` trouvee dans train.py"

    for assign in gate_assignments:
        names = {n.id for n in ast.walk(assign.value) if isinstance(n, ast.Name)}
        assert "eval_reliable" in names, (
            "le gate de curriculum ne consulte pas `eval_reliable` : une evaluation "
            "abandonnee sur timeout pourrait valider une transition de phase"
        )
