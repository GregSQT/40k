"""Le COUT d'une evaluation bot doit etre affiche sur le chemin NORMAL, pas seulement en echec.

Bug d'origine : `evaluate_against_bots` calcule `results["eval_duration_seconds"]`
(bot_evaluation.py), mais `_apply_eval_results` ne le lisait que pour construire ses messages
d'echec — `RuntimeError` sur crash de worker, avertissement sur timeout. Sur un run sain la
valeur etait calculee puis jetee.

Et la barre de progression de l'evaluation ne comblait pas le trou : elle est desactivee des
que l'eval est asynchrone (`effective_show_eval_progress = show_eval_progress and not
async_eval_enabled`, training_callbacks.py), ce qui est le cas par DEFAUT puisque rien ne
surcharge `async_eval_enabled=True`. Resultat : une evaluation pouvait peser des dizaines de
minutes par marqueur sans qu'aucune sortie ne le dise, et la seule facon d'estimer son cout
etait de multiplier `bot_eval_intermediate` par le nombre de bots actifs — un calcul de tete
que rien ne verifiait.

Famille « code teste mais jamais appele », version affichage : la mesure existait, personne ne
la montrait.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _results(duration: float = 125.0, played: int = 600) -> Dict[str, Any]:
    """Un resultat d'evaluation SAIN : ni crash, ni timeout."""
    return {
        "total_failed_episodes": 0,
        "total_timeout_episodes": 0,
        "total_error_episodes": 0,
        # Pose par evaluate_against_bots a chaque eval (V11 §0.61).
        "truncations": [],
        "eval_duration_seconds": duration,
        "total_episodes_played": played,
        "combined": 0.42,
        "faction_scores": {},
        "scenario_scores": {},
        "scenario_split_scores": {},
    }


def test_bot_evaluation_publishes_the_episode_count() -> None:
    """`total_episodes_played` doit etre pose par evaluate_against_bots. ROUGE avant le fix.

    Contrat de source : sans cette cle, `_apply_eval_results` leve sur son `require_key`.
    """
    source = (PROJECT_ROOT / "ai" / "bot_evaluation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    published = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name) and node.value.id == "results"
        and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
    }
    for key in ("eval_duration_seconds", "total_episodes_played"):
        assert key in published, f"ai/bot_evaluation.py ne publie plus results[{key!r}]"


def test_healthy_path_reaches_gate(monkeypatch) -> None:
    """Une eval SANS crash ni timeout atteint _evaluate_model_gate sans lever d'exception."""
    from ai import training_callbacks as tc

    cb = object.__new__(tc.BotEvaluationCallback)
    cb.metrics_tracker = None
    cb.last_eval_results = None
    cb.last_eval_marker = None
    # On coupe juste avant _evaluate_model_gate pour eviter d'initialiser les attributs
    # de checkpoint/logs non necessaires ici.
    gate_sentinel = RuntimeError("stop-at-gate")

    def _stop(*_a: Any, **_k: Any) -> None:
        raise gate_sentinel

    monkeypatch.setattr(tc.BotEvaluationCallback, "_evaluate_model_gate", _stop)

    with pytest.raises(RuntimeError) as excinfo:
        tc.BotEvaluationCallback._apply_eval_results(cb, _results(125.0, 600), 2000)
    assert excinfo.value is gate_sentinel, "l'echec doit venir du sentinelle, pas d'une autre erreur"


def test_crash_still_stops_training(capsys) -> None:
    """Contrepartie : l'ajout d'un affichage ne doit pas avaler le chemin d'echec dur."""
    from ai import training_callbacks as tc

    cb = object.__new__(tc.BotEvaluationCallback)
    cb.last_eval_results = None
    cb.last_eval_marker = None
    broken = _results()
    broken["total_failed_episodes"] = 5
    broken["total_error_episodes"] = 5
    with pytest.raises(RuntimeError, match="crashed episodes"):
        tc.BotEvaluationCallback._apply_eval_results(cb, broken, 2000)


