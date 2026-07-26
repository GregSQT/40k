"""Verrou : `--scenario <fichier>` en `--test-only --eval` joue le scénario TEL QUEL.

Contexte : le mode test-only route l'évaluation vers `evaluate_against_bots(scenario_pool="holdout")`,
qui matérialise chaque scénario via `_materialize_eval_scenario_refs` (réécriture `wall_ref`). Cette
matérialisation EXIGE un scénario sous `agents/.../scenarios/<split>/` et remplacerait le terrain —
elle casserait un scénario explicite autonome (ex. placement fixed sous `config/board/...`). Le
paramètre `materialize_eval_refs=False` la neutralise.

Les deux faces sont prouvées :
  1. ROUGE (raison d'être du flag) : `_materialize_eval_scenario_refs` LÈVE sur le scénario explicite
     (hors `agents/`). Sans le bypass, l'éval planterait.
  2. VERT (le flag est branché) : `evaluate_against_bots(..., materialize_eval_refs=False,
     scenario_list_override=[scenario])` joue le scénario tel quel — aucune exception, et le score
     est indexé sous le nom du scénario fourni (pas un holdout).

Rapatrié de `scripts/eval_explicit_scenario_test.py` (2026-07-26) : ce fichier vivait hors de
`tests/` et n'était jamais collecté par la suite.
"""

from __future__ import annotations

import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCENARIO = os.path.join(PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json")
AGENT = "ArmageddonAgent"
TRAINING_CONFIG = "x5_debug"


def _model_path() -> str:
    from config_loader import get_config_loader

    cfg = get_config_loader()
    key = cfg._resolve_agent_config_key(AGENT)
    return os.path.join(cfg.get_models_root(), key, f"model_{key}.zip")


def test_materialize_raises_outside_agents():
    """(1) La matérialisation refuse un scénario hors `agents/` — d'où le besoin du flag."""
    from ai.bot_evaluation import _materialize_eval_scenario_refs

    with pytest.raises(ValueError) as exc:
        _materialize_eval_scenario_refs(scenario_path=SCENARIO, wall_ref="terrain-mc1.json")
    assert "agents" in str(exc.value), f"ValueError inattendue : {exc.value}"


def test_explicit_scenario_played_as_is():
    """(2) `materialize_eval_refs=False` → le scénario explicite est joué tel quel."""
    model_path = _model_path()
    if not os.path.exists(model_path):
        # Les modèles entraînés ne sont pas versionnés (.gitignore `ai/models/**`) : hors poste de
        # travail (CI, clone neuf) ce verrou n'a pas de politique à charger. Précondition
        # d'environnement, pas un contournement d'erreur.
        pytest.skip(f"modèle entraîné absent : {model_path}")

    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker
    from stable_baselines3.common.save_util import load_from_zip_file

    from ai.bot_evaluation import evaluate_against_bots
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

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
    # Même mask_fn qu'en évaluation réelle (ai/bot_evaluation) : le masque vient du moteur wrappé.
    masked_env = ActionMasker(base_env, lambda _env: base_env.get_action_mask())

    # Lecture des MÉTADONNÉES du zip avant tout chargement de politique : la politique sur disque peut
    # précéder la refonte d'observation V11 (obs_size 108 → 199, 6 → 7 canaux), auquel cas ni
    # `MaskablePPO.load` ni l'extracteur spatial ne peuvent la reconstruire. Dans ce cas le verrou est
    # dormant jusqu'au retrain — on le dit, on ne masque pas.
    saved_data = load_from_zip_file(model_path, load_data=True, device="cpu")[0]
    if saved_data is None:
        raise ValueError(f"Modèle {model_path} sans métadonnées (observation_space illisible)")
    saved_obs_space = saved_data["observation_space"]
    if saved_obs_space != masked_env.observation_space:
        pytest.skip(
            f"politique sur disque incompatible avec l'observation courante "
            f"({saved_obs_space} != {masked_env.observation_space}) — retrain V11 en attente"
        )

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

    assert int(results["total_failed_episodes"]) == 0, "épisode(s) planté(s) sur le scénario explicite"
    scenario_scores = results["scenario_scores"]
    assert "fixed_brawl_sm_orks" in scenario_scores, (
        f"le scénario explicite n'a pas été joué ; clés = {list(scenario_scores.keys())}"
    )
