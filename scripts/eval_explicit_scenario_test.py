#!/usr/bin/env python3
"""Verrou : --scenario <fichier> en `--test-only --eval` joue le scénario TEL QUEL.

Contexte : le mode test-only route l'évaluation vers `evaluate_against_bots(scenario_pool=
"holdout")`, qui matérialise chaque scénario via `_materialize_eval_scenario_refs` (réécriture
`wall_ref`). Cette matérialisation EXIGE un scénario sous `agents/.../scenarios/<split>/` et
remplacerait le terrain — elle casserait un scénario explicite autonome (ex. placement fixed
sous `config/board/...`). Le paramètre `materialize_eval_refs=False` la neutralise.

Ce test prouve les deux faces :
  1. ROUGE (raison d'être du flag) : `_materialize_eval_scenario_refs` LÈVE sur le scénario
     explicite (hors `agents/`). Sans le bypass, l'éval planterait.
  2. VERT (le flag est branché) : `evaluate_against_bots(..., materialize_eval_refs=False,
     scenario_list_override=[scenario])` joue le scénario tel quel — aucune exception, et le
     score est indexé sous le nom du scénario fourni (pas un holdout).

Lancement : python3 scripts/eval_explicit_scenario_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json")
AGENT = "ArmageddonAgent"
TRAINING_CONFIG = "x5_debug"


def test_materialize_raises_outside_agents():
    """(1) La matérialisation refuse un scénario hors agents/ — d'où le besoin du flag."""
    from ai.bot_evaluation import _materialize_eval_scenario_refs

    try:
        _materialize_eval_scenario_refs(scenario_path=SCENARIO, wall_ref="terrain-mc1.json")
    except ValueError as exc:
        assert "agents" in str(exc), f"ValueError inattendue : {exc}"
        print("✅ ROUGE confirmé : _materialize_eval_scenario_refs lève hors agents/ "
              f"({str(exc).splitlines()[0]})")
        return
    raise AssertionError(
        "ATTENDU : _materialize_eval_scenario_refs devait lever sur un scénario hors agents/ "
        "(sinon le flag materialize_eval_refs n'aurait pas de raison d'être)."
    )


def test_explicit_scenario_played_as_is():
    """(2) materialize_eval_refs=False → le scénario explicite est joué tel quel."""
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker

    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from ai.bot_evaluation import evaluate_against_bots
    from config_loader import get_config_loader

    W40KEngine, _ = setup_imports()
    cfg = get_config_loader()
    models_root = cfg.get_models_root()
    model_storage_key = cfg._resolve_agent_config_key(AGENT)
    model_path = os.path.join(models_root, model_storage_key, f"model_{model_storage_key}.zip")
    assert os.path.exists(model_path), f"Modèle absent : {model_path}"

    base_env = W40KEngine(
        rewards_config=AGENT,
        training_config_name=TRAINING_CONFIG,
        controlled_agent=AGENT,
        active_agents=None,
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    masked_env = ActionMasker(base_env, lambda env: env.get_action_mask())
    model = MaskablePPO.load(model_path, env=masked_env)

    results = evaluate_against_bots(
        model=model,
        training_config_name=TRAINING_CONFIG,
        rewards_config_name=AGENT,
        n_episodes=1,
        controlled_agent=AGENT,
        show_progress=False,
        deterministic=True,
        model_path=model_path,
        scenario_pool="holdout",
        scenario_list_override=[SCENARIO],
        materialize_eval_refs=False,
    )

    failed = int(results["total_failed_episodes"])
    assert failed == 0, f"Épisodes plantés : {failed}"
    scenario_scores = results["scenario_scores"]
    assert "fixed_brawl_sm_orks" in scenario_scores, (
        f"Le scénario explicite n'a pas été joué ; clés = {list(scenario_scores.keys())}"
    )
    print(f"✅ VERT confirmé : scénario explicite joué tel quel "
          f"(scenario_scores={list(scenario_scores.keys())}, 0 épisode planté)")


if __name__ == "__main__":
    test_materialize_raises_outside_agents()
    test_explicit_scenario_played_as_is()
    print("✅ VERROU OK : --scenario <fichier> en test-only joue le scénario tel quel "
          "(matérialisation neutralisée par materialize_eval_refs=False).")
