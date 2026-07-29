"""Verrouille l'alignement de la boucle d'evaluation de scripts/roster_matchup_stats.py
sur la reference vivante ai/bot_evaluation.py.

Le script avait diverge sur quatre points, dont un le rendait totalement inutilisable :
l'observation du pipeline squad est un `gym.spaces.Dict` (engine/w40k_core.py:639) et la
boucle l'aplatissait via `np.asarray(model_obs, dtype=np.float32)`, ce qui levait avant
meme d'atteindre le masque d'actions. La reference traite ce cas a
ai/bot_evaluation.py:526-533.

Ces tests sont STRUCTURELS (analyse AST du source) et non comportementaux : exercer la
boucle demanderait de faire tourner des parties completes (chargement moteur + modele +
episodes), ce qu'un test unitaire ne doit pas faire. Ils verrouillent donc la presence des
constructions exactes de la reference, seul moyen d'empecher les deux boucles de re-diverger
silencieusement.
"""
import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "roster_matchup_stats.py"


def _eval_loop_function() -> ast.FunctionDef:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_matchup_episodes":
            return node
    raise AssertionError("_run_matchup_episodes introuvable dans scripts/roster_matchup_stats.py")


@pytest.fixture(scope="module")
def loop_fn() -> ast.FunctionDef:
    return _eval_loop_function()


@pytest.fixture(scope="module")
def loop_src(loop_fn: ast.FunctionDef) -> str:
    return ast.unparse(loop_fn)


def test_obs_dict_is_not_flattened(loop_fn: ast.FunctionDef, loop_src: str):
    """Divergence n1 — ai/bot_evaluation.py:526-533 : l'obs Dict passe telle quelle a predict."""
    assert "isinstance(model_obs, dict)" in loop_src, (
        "la garde obs Dict a disparu : la boucle re-aplatit l'observation du pipeline squad"
    )
    assert "model_obs = np.asarray(model_obs" not in loop_src, (
        "l'obs est reecrite en float32 hors de toute garde : cela leve sur une obs Dict"
    )
    # La conversion float32 ne doit exister QUE dans la branche `else` de la garde Dict.
    guards = [
        node
        for node in ast.walk(loop_fn)
        if isinstance(node, ast.If) and "isinstance(model_obs, dict)" in ast.unparse(node.test)
    ]
    assert len(guards) == 1, f"attendu 1 garde obs Dict, trouve {len(guards)}"
    guard = guards[0]
    assert "np.asarray(model_obs, dtype=np.float32)" in ast.unparse(guard.orelse), (
        "la conversion float32 du chemin legacy Box a plat a disparu de la branche else"
    )
    assert "np.asarray(model_obs" not in ast.unparse(guard.body), (
        "le chemin Dict convertit l'observation au lieu de la passer telle quelle"
    )


def test_predict_receives_model_input(loop_fn: ast.FunctionDef):
    """L'argument servi a predict est celui issu de la garde Dict, pas l'obs brute."""
    predict_calls = [
        node
        for node in ast.walk(loop_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "predict"
    ]
    assert len(predict_calls) == 1, f"attendu 1 appel a predict, trouve {len(predict_calls)}"
    first_arg = predict_calls[0].args[0]
    assert isinstance(first_arg, ast.Name) and first_arg.id == "model_input", (
        "predict ne recoit pas `model_input` (sortie de la garde obs Dict)"
    )


def test_step_guard_comes_from_game_rules(loop_src: str):
    """Divergence n2 — ai/bot_evaluation.py:520 + :1052 : plafond derive de game_rules.max_turns."""
    assert "max_steps_per_episode = int(get_max_turns()) * 400" in loop_src, (
        "le plafond de pas par episode doit venir de config_loader.get_max_turns(), "
        "jamais d'une constante inventee"
    )
    assert "step_count < max_steps_per_episode" in loop_src, "la garde n'est pas dans la boucle"


def test_winner_uses_controlled_player_from_info(loop_src: str):
    """Divergence n3 — ai/bot_evaluation.py:543 : le siege controle est lu dans info."""
    assert "require_key(info, 'controlled_player')" in loop_src, (
        "le siege controle n'est plus lu dans l'info rendue par l'env"
    )
    assert "controlled_winner_id" not in loop_src, (
        "identifiant de siege recalcule localement : il peut diverger du siege reellement joue"
    )


def test_both_random_generators_are_seeded(loop_src: str):
    """Divergence n4 — ai/bot_evaluation.py:515-516 : random ET numpy sont graines."""
    assert "random.seed(ep_seed)" in loop_src
    assert "np.random.seed(ep_seed)" in loop_src


def test_obs_normalizer_delegates_to_reference():
    """Le normalizer n'est pas reimplemente : c'est celui de ai/bot_evaluation.py:385-440,
    seul a traiter l'obs Dict (:432-433). Une copie locale avait deja re-diverge."""
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build_obs_normalizer"
    )
    builder_src = ast.unparse(builder)
    assert "_build_eval_obs_normalizer_for_worker" in builder_src
    assert "normalize_observation_for_inference" not in builder_src, (
        "normalizer reimplemente localement : il re-divergera de la reference"
    )
