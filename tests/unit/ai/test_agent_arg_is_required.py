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
- CHAINON : le nom passe a `type=` est bien la fabrique dont on verifie le comportement ;
- COMPORTEMENT : le validateur refuse la chaine vide et nettoie les espaces ;
- JUMEAU : `--rewards-config`, qui nomme les memes dossiers, porte le meme garde ;
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


def _add_argument(flag: str) -> ast.Call:
    """Le `parser.add_argument(flag, ...)` de `main()`, ou echec explicite."""
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == flag:
            return node
    pytest.fail(f"aucun add_argument({flag!r}) trouve dans ai/train.py")


def _agent_add_argument() -> ast.Call:
    return _add_argument("--agent")


def _compiled_non_empty_key():
    """La fabrique `_non_empty_key` de `ai/train.py`, extraite et compilee seule.

    Elle ne depend d'aucun import lourd, d'ou l'extraction par AST plutot que `import ai.train`
    (qui tire torch et stable_baselines3).
    """
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    func = next(
        (node for node in ast.walk(tree)
         if isinstance(node, ast.FunctionDef) and node.name == "_non_empty_key"),
        None,
    )
    if func is None:
        pytest.fail("aucune fonction `_non_empty_key` trouvee dans ai/train.py")
    namespace: dict = {"argparse": argparse}
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(TRAIN_PY), "exec"), namespace)
    return namespace["_non_empty_key"]


def _module_assignment(name: str) -> ast.expr:
    """La valeur affectee a `name` au niveau MODULE de `ai/train.py`, ou echec explicite."""
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return node.value
    pytest.fail(f"aucune affectation de module `{name} = ...` trouvee dans ai/train.py")


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

    # CHAINON : `_non_empty_agent` n'est plus un `def` mais l'APPLICATION de la fabrique commune
    # `_non_empty_key(flag)`. Le test comportemental ci-dessous execute cette fabrique ; sans
    # l'assertion qui suit, rien ne relierait ce qu'il execute a ce que `type=` recoit vraiment, et
    # `_non_empty_agent = str` laisserait ce fichier VERT en rouvrant `--agent ""`.
    binding = _module_assignment("_non_empty_agent")
    assert (
        isinstance(binding, ast.Call)
        and isinstance(binding.func, ast.Name)
        and binding.func.id == "_non_empty_key"
        and len(binding.args) == 1
        and isinstance(binding.args[0], ast.Constant)
        and binding.args[0].value == "--agent"
    ), (
        "`_non_empty_agent` doit rester `_non_empty_key(\"--agent\")` : c'est la fabrique dont ce "
        "test verifie le comportement juste en dessous. La relier a autre chose (str, une variante "
        "sans strip) rouvrirait `--agent \"\"` sans rougir."
    )

    # Le validateur lui-meme, execute (il ne depend d'aucun import lourd).
    non_empty_agent = _compiled_non_empty_key()("--agent")

    assert non_empty_agent("CoreAgent") == "CoreAgent"
    # La valeur rendue est NETTOYEE, pas la brute : `" CoreAgent"` se propageait tel quel dans
    # `config/agents/ CoreAgent/` et `ai/models/ CoreAgent/`, l'espace inclus dans le chemin.
    assert non_empty_agent("  CoreAgent  ") == "CoreAgent"
    for empty in ("", "   "):
        with pytest.raises(argparse.ArgumentTypeError):
            non_empty_agent(empty)


def test_rewards_config_rejects_the_empty_string() -> None:
    """JUMEAU de `--agent` : `--rewards-config` nomme les MEMES dossiers, il porte le meme garde.

    « Applique aux DEUX drapeaux qui nomment un dossier de config » (docstring de `_non_empty_key`) :
    ne le poser que sur `--agent` laissait la porte grande ouverte, `--rewards-config " CoreAgent"`
    atteignant `config/agents/ CoreAgent/` et `ai/models/ CoreAgent/`, l'espace inclus dans le
    chemin. Sans ce test, retirer le `type=` de la ligne `--rewards-config` laissait la suite verte.

    La forme differe de `--agent` et c'est voulu : ici la fabrique est appliquee EN PLACE
    (`type=_non_empty_key("--rewards-config")`), donc un `ast.Call` et non un `ast.Name` — le
    drapeau passe a la fabrique doit etre le sien, sans quoi le message d'erreur nommerait
    `--agent` pour une faute portant sur `--rewards-config`.
    """
    keywords = {kw.arg: kw.value for kw in _add_argument("--rewards-config").keywords}
    validator = keywords.get("type")
    assert (
        isinstance(validator, ast.Call)
        and isinstance(validator.func, ast.Name)
        and validator.func.id == "_non_empty_key"
        and len(validator.args) == 1
        and isinstance(validator.args[0], ast.Constant)
        and validator.args[0].value == "--rewards-config"
    ), (
        "--rewards-config doit passer par _non_empty_key(\"--rewards-config\") : sans lui, "
        "`--rewards-config \"\"` traverse argparse et une valeur non nettoyee se propage dans "
        "les chemins `config/agents/` et `ai/models/`."
    )

    non_empty_rewards = _compiled_non_empty_key()("--rewards-config")
    assert non_empty_rewards("  CoreAgent  ") == "CoreAgent"
    for empty in ("", "   "):
        with pytest.raises(argparse.ArgumentTypeError, match="--rewards-config"):
            non_empty_rewards(empty)


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
