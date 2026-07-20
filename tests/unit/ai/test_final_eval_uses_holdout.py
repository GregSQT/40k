"""V11 §0.12 — l'evaluation FINALE doit mesurer le HOLDOUT, jamais le scenario d'entrainement.

Bug d'origine : `MetricsCollectionCallback._run_final_bot_eval` appelait `evaluate_against_bots`
SANS passer `scenario_pool`, alors que la signature a pour defaut `"training"`. L'eval finale
mesurait donc le scenario d'ENTRAINEMENT, silencieusement — mesure a l'appui, la sortie du run
affichait `Scenario ranking (combined): - training_armageddon`.

C'est la famille T6-a / T6-b / T6-e : migration partielle d'un chemin, un site d'appel oublie,
une valeur par defaut qui masque l'oubli, aucun message.

Ces tests verrouillent les DEUX moities de l'invariant :
- le site d'appel transmet bien `holdout` (test comportemental, sur un vrai appel intercepte) ;
- aucun des sites de MESURE ne s'en remet au defaut de signature (test de contrat, qui
  attraperait la reintroduction du bug sur un autre site).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_final_bot_eval_passes_holdout_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_run_final_bot_eval` transmet `scenario_pool='holdout'`. ROUGE avant le fix."""
    from ai import training_callbacks

    captured: Dict[str, Any] = {}

    def _fake_evaluate_against_bots(**kwargs: Any) -> Dict[str, Any]:
        captured.update(kwargs)
        return {"combined": 0.0}

    # `_run_final_bot_eval` importe la fonction en LAZY depuis `ai.bot_evaluation` :
    # c'est donc ce module-la qu'il faut patcher, pas l'espace de noms du callback.
    import ai.bot_evaluation as bot_evaluation

    monkeypatch.setattr(bot_evaluation, "evaluate_against_bots", _fake_evaluate_against_bots)

    callback = training_callbacks.MetricsCollectionCallback.__new__(
        training_callbacks.MetricsCollectionCallback
    )
    callback.controlled_agent = "ArmageddonAgent"

    training_config = {
        "callback_params": {"bot_eval_final": 2, "eval_deterministic": True}
    }
    callback._run_final_bot_eval(
        model=object(),
        training_config=training_config,
        training_config_name="x5_debug",
        rewards_config_name="ArmageddonAgent",
    )

    assert captured, "evaluate_against_bots n'a pas ete appelee"
    assert "scenario_pool" in captured, (
        "scenario_pool absent de l'appel : l'eval finale retombe sur le defaut de signature "
        "('training') et mesure le scenario d'ENTRAINEMENT — bug V11 §0.12"
    )
    assert captured["scenario_pool"] == "holdout", (
        f"l'eval finale doit mesurer le holdout (§10.5), got {captured['scenario_pool']!r}"
    )


def test_evaluate_against_bots_default_pool_is_not_silently_trusted() -> None:
    """Aucun site de MESURE n'omet `scenario_pool`.

    Test de contrat, complementaire du precedent : il attraperait la reintroduction du bug sur
    un site d'appel que le test comportemental ne couvre pas. On verifie d'abord que le defaut
    de signature est bien le piege decrit (si quelqu'un le passe a 'holdout', ce test devient
    sans objet et doit etre revu, pas supprime).
    """
    from ai.bot_evaluation import evaluate_against_bots

    default_pool = inspect.signature(evaluate_against_bots).parameters["scenario_pool"].default
    assert default_pool == "training", (
        "Le defaut de `evaluate_against_bots.scenario_pool` a change. Ce test suppose que le "
        "defaut est le piege ('training'). Reevaluer l'invariant avant de toucher a ce test."
    )

    sources = {
        "ai/train.py": PROJECT_ROOT / "ai" / "train.py",
        "ai/training_callbacks.py": PROJECT_ROOT / "ai" / "training_callbacks.py",
    }

    missing: list[str] = []
    for label, path in sources.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "evaluate_against_bots":
                continue
            if not any(kw.arg == "scenario_pool" for kw in node.keywords):
                missing.append(f"{label}:{node.lineno}")

    assert not missing, (
        "Sites appelant evaluate_against_bots SANS scenario_pool (ils mesureront le scenario "
        f"d'entrainement en silence) : {missing}"
    )
