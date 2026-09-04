"""Verrouille la séparation workers intermédiaires / finals.

Problème d'origine : `bot_eval_n_workers` passait de 4 à 16 pour toutes les évals,
intermédiaires comprises. Chaque vague d'éval intermédiaire spawnait 16 workers en plus
des 48 envs d'entraînement, causant un pic de RAM qui tuait WSL2 (~40 ko épisodes).

Contrat :
- `bot_eval_n_workers_intermediate` dans callback_params → stocké sur le callback.
- `_evaluate_against_bots` passe `n_workers_override=self.intermediate_n_workers`
  à `evaluate_against_bots`.
- `evaluate_against_bots` lève sur une valeur invalide.
- `BotEvaluationCallback.__init__` rejette les valeurs invalides pour intermediate_n_workers.
- Les evals finales et `--test-only` ne passent JAMAIS n_workers_override
  (elles restent sur bot_eval_n_workers).
- TOUS les profils déclarent la clé : elle est exigée par `require_key` au démarrage de
  tout run `--etape` sur une étape à pool (ai/train.py, branches sonde exploiteur et
  `PoolEarlyStoppingCallback`).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, cast
from unittest.mock import MagicMock, patch

import pytest

import ai.bot_evaluation
from ai.training_callbacks import BotEvaluationCallback

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Seule la config de `ArmageddonAgent_x1` est verrouillée ici : c'est la seule que le config
# loader sache atteindre. `config/agents/ArmageddonAgent_old/ArmageddonAgent_training_config.json`
# porte les mêmes six profils, mais son nom de fichier ne correspond plus à celui de son dossier
# (`_resolve_agent_config_key` construit `<dossier>/<clé>_training_config.json`), donc aucun run ne
# peut le charger — lui poser un contrat affirmerait une exigence qu'aucun chemin n'a.
AGENT_CONFIG = (
    PROJECT_ROOT / "config/agents/ArmageddonAgent_x1/ArmageddonAgent_x1_training_config.json"
)


def _profiles() -> Dict[str, Dict[str, Any]]:
    with open(AGENT_CONFIG, encoding="utf-8-sig") as fh:
        return {k: v for k, v in json.load(fh).items() if isinstance(v, dict)}


PROFILE_NAMES = sorted(_profiles())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bare_callback(intermediate_n_workers=None) -> BotEvaluationCallback:
    """Instance minimale construite via __new__ pour éviter les imports lourds de __init__."""
    cb = BotEvaluationCallback.__new__(BotEvaluationCallback)
    cb.training_config_name = "x1"
    cb.rewards_config_name = "CoreAgent"
    cb.scenario_pool = "training"
    cb.n_eval_episodes = 20
    cb.eval_deterministic = True
    cb.show_eval_progress = False
    cb.async_eval_enabled = True
    cb.eval_count = 1
    cb.model = cast(Any, object())
    cb.gate_display_state = None
    cb.metrics_tracker = None
    cb.intermediate_n_workers = intermediate_n_workers
    return cb


# ---------------------------------------------------------------------------
# 1. BotEvaluationCallback.__init__ valide intermediate_n_workers
# ---------------------------------------------------------------------------

def _make_init_kwargs(**overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "scenario_pool": "training",
        "training_config_name": "x1",
        "rewards_config_name": "CoreAgent",
        "model_gating_min_vs_control": 0.0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("value", [None, 1, 4, 16])
def test_init_accepte_intermediate_n_workers_valide(value):
    """None et entiers positifs sont acceptés."""
    cb = BotEvaluationCallback(**_make_init_kwargs(intermediate_n_workers=value))
    assert cb.intermediate_n_workers == value


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "4"])
def test_init_rejette_intermediate_n_workers_invalide(bad):
    """0, négatifs, bool, float et string lèvent ValueError."""
    with pytest.raises((ValueError, TypeError)):
        BotEvaluationCallback(**_make_init_kwargs(intermediate_n_workers=bad))


# ---------------------------------------------------------------------------
# 2. _evaluate_against_bots passe n_workers_override quand intermediate_n_workers est posé
# ---------------------------------------------------------------------------

def test_evaluate_against_bots_recoit_n_workers_override(monkeypatch):
    """n_workers_override=4 passe dans evaluate_against_bots lorsque intermediate_n_workers=4."""
    captured: Dict[str, Any] = {}

    def _fake_eval(**kwargs):
        captured.update(kwargs)
        return {"win_rate": 0.5, "truncations": 0}

    monkeypatch.setattr(ai.bot_evaluation, "evaluate_against_bots", _fake_eval)

    cb = _bare_callback(intermediate_n_workers=4)
    cb._evaluate_against_bots(eval_marker=2000)

    assert "n_workers_override" in captured, (
        "_evaluate_against_bots ne transmet pas n_workers_override à evaluate_against_bots"
    )
    assert captured["n_workers_override"] == 4


def test_evaluate_against_bots_sans_override_quand_none(monkeypatch):
    """n_workers_override=None laisse evaluate_against_bots utiliser bot_eval_n_workers."""
    captured: Dict[str, Any] = {}

    def _fake_eval(**kwargs):
        captured.update(kwargs)
        return {"win_rate": 0.5, "truncations": 0}

    monkeypatch.setattr(ai.bot_evaluation, "evaluate_against_bots", _fake_eval)

    cb = _bare_callback(intermediate_n_workers=None)
    cb._evaluate_against_bots(eval_marker=2000)

    # None signifie « pas d'override » → evaluate_against_bots doit le recevoir tel quel
    # (ou recevoir un kwarg absent — les deux sont acceptables, on vérifie None/absent)
    assert captured.get("n_workers_override") is None


# ---------------------------------------------------------------------------
# 3. evaluate_against_bots valide n_workers_override à l'intérieur de la fonction
# ---------------------------------------------------------------------------

def test_evaluate_against_bots_contient_validation_n_workers_override():
    """evaluate_against_bots contient un bloc de validation pour n_workers_override.

    Défense en profondeur pour les appels programmatiques directs (sans BotEvaluationCallback).
    On vérifie la PRÉSENCE du code de validation via AST plutôt qu'un test d'intégration
    lourd, cohérent avec test_bot_eval_worker_config.py.
    """
    source = (PROJECT_ROOT / "ai" / "bot_evaluation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Trouver la fonction evaluate_against_bots et chercher "n_workers_override" dans son corps.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_against_bots":
            func_source = ast.get_source_segment(source, node) or ""
            assert "n_workers_override" in func_source, (
                "evaluate_against_bots ne contient pas de logique pour n_workers_override"
            )
            # Vérifier qu'une ValueError est levée (pas un repli silencieux)
            raises = [
                n for n in ast.walk(node)
                if isinstance(n, ast.Raise)
            ]
            assert raises, (
                "evaluate_against_bots ne contient aucun raise — la validation de "
                "n_workers_override doit lever ValueError sur valeur invalide"
            )
            return

    pytest.fail("Fonction evaluate_against_bots introuvable dans ai/bot_evaluation.py")


# ---------------------------------------------------------------------------
# 4. Contrat de CONFIG : les profils déclarent tous la clé, à la même valeur
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_every_profile_declares_the_intermediate_workers_key(profile_name: str) -> None:
    """La clé est OBLIGATOIRE dans chaque profil, sans défaut ni valeur implicite.

    `ai/train.py` la lit avec `require_key` au DÉMARRAGE de tout run `--etape` dont l'étape a un
    pool : sonde exploiteur d'un côté, `PoolEarlyStoppingCallback` de l'autre. Un profil qui ne la
    porte pas fait donc refuser le run, et c'est exactement ainsi que `x1_debug` et `x5_debug` sont
    restés inutilisables pour les étapes P1 à P10 — ils déclaraient pourtant déjà
    `bot_eval_n_workers_gate`, clé que SEUL un run d'étape consomme.
    """
    callback_params = _profiles()[profile_name]["callback_params"]
    assert "bot_eval_n_workers_intermediate" in callback_params, (
        f"{profile_name} ne déclare pas bot_eval_n_workers_intermediate"
    )
    value = callback_params["bot_eval_n_workers_intermediate"]
    assert isinstance(value, int) and not isinstance(value, bool), profile_name
    assert value > 0, profile_name


def test_the_profiles_do_not_silently_diverge_on_intermediate_workers() -> None:
    """Tous les profils partagent la MÊME valeur, `x1` faisant référence.

    Ce compte décrit un RÉGIME — combien de workers d'évaluation tournent EN CONCURRENCE des envs
    de collecte pendant l'entraînement — et non une longueur de run. La contrainte qui l'a fixé à 4
    est identique dans un profil de debug et dans un profil de mesure, puisque `n_envs` y vaut 24
    des deux côtés ; le laisser diverger rendrait un run de mise au point non représentatif du run
    qu'il prépare. Même règle que `agent_seat_p2_ratio` et `deployment_mode_schedule`.
    """
    profiles = _profiles()
    reference = profiles["x1"]["callback_params"]["bot_eval_n_workers_intermediate"]
    diverging = {
        name: profile["callback_params"].get("bot_eval_n_workers_intermediate")
        for name, profile in profiles.items()
        if profile["callback_params"].get("bot_eval_n_workers_intermediate") != reference
    }
    assert not diverging, f"profils divergents (référence x1={reference}) : {diverging}"
