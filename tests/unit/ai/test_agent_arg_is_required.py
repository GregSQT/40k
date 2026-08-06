"""`--agent` est exige par argparse, et non vide : le mode generique sans agent n'existe plus.

Ce mode resolvait l'agent controle en cherchant les unites `"player": 0` du scenario, et il a
ete supprime avec la fonction `create_model` qui le portait. La contrepartie est que TOUT le
reste de `ai/train.py` suppose desormais `args.agent` renseigne : quatre gardes `if not
args.agent: raise` ont ete retirees de `main()` parce qu'`argparse` les rend inatteignables.

Sans ce fichier, rien ne verrouillait cette bascule. Retirer `required=True` laissait la suite
verte et faisait resurgir la panne d'origine, en pire : la commande echouait des dizaines de
lignes plus bas, apres la construction du StepLogger et apres `node scripts/copy-configs.js`.

Verrous :
- ARGPARSE : la declaration porte `required=True` ET un validateur de non-vacuite ;
- COMPORTEMENT : le validateur refuse la chaine vide ;
- DELETION : aucune garde `not args.agent` ne repousse dans `main()`.

Lecture par AST du source, sans importer `ai.train` : l'import tire torch et
stable_baselines3 (~2,7 s), pour une question qui ne porte que sur la declaration.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRAIN_PY = PROJECT_ROOT / "ai" / "train.py"


def _agent_add_argument() -> ast.Call:
    """Le `parser.add_argument("--agent", ...)` de `main()`, ou echec explicite."""
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == "--agent":
            return node
    pytest.fail("aucun add_argument(\"--agent\") trouve dans ai/train.py")


def test_agent_is_required_at_parse_time() -> None:
    """`required=True` : la commande est refusee AVANT tout effet de bord."""
    keywords = {kw.arg: kw.value for kw in _agent_add_argument().keywords}
    required = keywords.get("required")
    assert isinstance(required, ast.Constant) and required.value is True, (
        "--agent doit porter required=True : sans lui, l'absence d'agent n'est plus "
        "detectee qu'apres le StepLogger et la resynchronisation des configs frontend."
    )


def test_agent_rejects_the_empty_string() -> None:
    """`required` n'exige que la PRESENCE : la non-vacuite passe par un validateur `type=`."""
    keywords = {kw.arg: kw.value for kw in _agent_add_argument().keywords}
    validator = keywords.get("type")
    assert isinstance(validator, ast.Name) and validator.id == "_non_empty_agent", (
        "--agent doit passer par _non_empty_agent : `--agent \"\"` traverserait argparse "
        "et desamorcerait les gardes ecrites en `if agent_key:`."
    )

    # Le validateur lui-meme, execute (il ne depend d'aucun import lourd).
    source = TRAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_non_empty_agent"
    )
    namespace: dict = {"argparse": argparse}
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(TRAIN_PY), "exec"), namespace)
    non_empty_agent = namespace["_non_empty_agent"]

    assert non_empty_agent("CoreAgent") == "CoreAgent"
    for empty in ("", "   "):
        with pytest.raises(argparse.ArgumentTypeError):
            non_empty_agent(empty)


def test_no_not_args_agent_guard_survives_in_main() -> None:
    """La contrepartie de la suppression : aucune garde `not args.agent` ne repousse.

    Elles etaient quatre (`--step`, `--test-only`, `ensure_scenario`, le `else` terminal).
    Argparse les rend inatteignables ; une nouvelle occurrence signalerait que quelqu'un a
    recommence a defendre un etat que la ligne de commande ne peut plus produire.
    """
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.UnaryOp) or not isinstance(node.op, ast.Not):
            continue
        operand = node.operand
        if (
            isinstance(operand, ast.Attribute)
            and operand.attr == "agent"
            and isinstance(operand.value, ast.Name)
            and operand.value.id == "args"
        ):
            offenders.append(node.lineno)
    assert not offenders, f"gardes `not args.agent` inatteignables, lignes {offenders}"
