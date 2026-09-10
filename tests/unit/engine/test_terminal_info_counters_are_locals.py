"""`W40KEngine._build_terminal_info` n'accumule JAMAIS dans `self.episode_tactical_data`.

L'INVARIANT, tel que la docstring de la méthode l'énonce (`engine/w40k_core.py`) : le bilan de
fin d'épisode est un RECALCUL PUR à partir de `action_logs` + `game_state`, parce que deux steps
moteur rendent `terminated` dans le même épisode (mesure citée là-bas : 24 terminaisons moteur
pour 12 épisodes gym) et que la méthode est donc appelée DEUX FOIS. Tous les compteurs de la
passe sur `action_logs` sont des variables locales, affectées une seule fois APRÈS la boucle. Un
compteur accumulé directement dans l'attribut doublerait sur le second appel.

POURQUOI UN TEST STRUCTUREL, et pas seulement le test de comportement jumeau
(`tests/unit/engine/test_engine_step.py::TestStepTurnLimit`, qui appelle la méthode deux fois et
compare `episode_tactical_data`) : ce dernier ne peut verrouiller que les compteurs que son
`action_logs` fait vivre. Un compteur ajouté demain sur une branche que ce scénario n'émet pas
resterait à zéro des deux côtés et passerait vert en doublant en production. L'invariant, lui,
porte sur TOUS les compteurs de la méthode — c'est une propriété du code, et c'est le code qu'on
lit ici. Même motif, même module et même technique que
`tests/unit/engine/test_scenario_attrs_both_init_branches.py`.

DEUX FORMES INTERDITES, et la seconde est celle qui a réellement cassé :

1. `self.episode_tactical_data['x'] += …` — l'accumulation directe.
2. `local = self.episode_tactical_data['x']` puis `local['y'] += …` — l'accumulation par ALIAS.

La forme 2 n'est pas une hypothèse : la méthode lie déjà `_cd = charge_distance_local[camp]` puis
fait `_cd['long'] += 1`. Le jour où quelqu'un remplace `charge_distance_local` par
`self.episode_tactical_data['charge_distance']` à cet endroit, le défaut d'origine de
`charge_distance` est rétabli à l'identique — sans produire le moindre `+=` sur l'attribut, donc
sans que la règle 1 ne voie rien. Les deux règles ne ferment que prises ensemble.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import List

import engine.w40k_core as w40k_core


_ATTR = "episode_tactical_data"

_REMEDE = (
    "Un compteur de `_build_terminal_info` doit être une variable LOCALE, accumulée dans la "
    "boucle puis affectée une seule fois à `self.episode_tactical_data[...]` APRÈS la boucle. "
    "La méthode est appelée deux fois par épisode : toute accumulation portée par l'attribut "
    "double au second appel."
)


def _method_ast() -> ast.FunctionDef:
    """AST du corps de `_build_terminal_info`.

    `inspect.getsource` lève de lui-même si la méthode est renommée ou déplacée : le test doit
    suivre le renommage, pas disparaître.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(w40k_core.W40KEngine._build_terminal_info)))
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef), (
        "le source de _build_terminal_info ne parse pas en une définition de fonction"
    )
    return func


def _reaches_attribute(node: ast.expr) -> bool:
    """True si `node` est `self.episode_tactical_data` ou un indexage (à toute profondeur) de lui.

    Remonte les `Subscript` : `self.episode_tactical_data['charge_distance']['agent']['long']`
    rend True, ce qui est exactement la forme du défaut d'origine.
    """
    while isinstance(node, ast.Subscript):
        node = node.value
    return (
        isinstance(node, ast.Attribute)
        and node.attr == _ATTR
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def test_no_augmented_assignment_on_episode_tactical_data() -> None:
    """Forme 1 : aucun `+=` (ni autre opérateur augmenté) ne cible l'attribut."""
    offenders: List[int] = [
        node.lineno
        for node in ast.walk(_method_ast())
        if isinstance(node, ast.AugAssign) and _reaches_attribute(node.target)
    ]
    assert not offenders, (
        f"accumulation directe sur `self.{_ATTR}` dans _build_terminal_info "
        f"(lignes relatives {offenders}). {_REMEDE}"
    )


def test_no_local_alias_bound_to_episode_tactical_data() -> None:
    """Forme 2 : aucun nom local n'est lié à un indexage de l'attribut.

    C'est l'alias mutable : le nom local ne fait que déguiser l'accumulation sur l'attribut.
    `self.episode_tactical_data.copy()` n'est pas concerné — la valeur est un appel, pas un
    indexage, et la copie est justement ce que la méthode doit faire pour remplir `info`.
    """
    offenders: List[int] = []
    for node in ast.walk(_method_ast()):
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        if not _reaches_attribute(value):
            continue
        for target in targets:
            names = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]
            if any(isinstance(name, ast.Name) for name in names):
                offenders.append(node.lineno)
    assert not offenders, (
        f"nom local lié à un indexage de `self.{_ATTR}` dans _build_terminal_info "
        f"(lignes relatives {offenders}) : accumuler à travers cet alias double aussi. {_REMEDE}"
    )


def test_walker_reaches_the_counting_loop() -> None:
    """Garde anti-VERT VACANT : les deux verrous ci-dessus lisent bien un corps de méthode peuplé.

    Sans elle, un `_method_ast()` qui rendrait un corps vide — méthode déplacée, source
    tronquée, dedent raté — laisserait les deux tests verts en n'ayant rien inspecté.
    """
    func = _method_ast()
    aug_assigns = [n for n in ast.walk(func) if isinstance(n, ast.AugAssign)]
    attribute_writes = [
        n for n in ast.walk(func)
        if isinstance(n, ast.Assign)
        and any(_reaches_attribute(t) for t in n.targets)
    ]
    assert len(aug_assigns) > 10, (
        f"_build_terminal_info ne porte que {len(aug_assigns)} accumulations : les compteurs "
        "locaux de la boucle action_logs ne sont pas dans le source inspecté"
    )
    assert len(attribute_writes) > 10, (
        f"_build_terminal_info ne porte que {len(attribute_writes)} affectations vers "
        f"`self.{_ATTR}` : le source inspecté n'est pas celui du bilan d'épisode"
    )
