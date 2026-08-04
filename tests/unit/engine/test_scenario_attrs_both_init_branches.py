"""Les deux branches de `W40KEngine.__init__` posent le MÊME jeu d'attributs `_scenario_*`.

Pourquoi un test structurel plutôt qu'un test de comportement : la divergence ne se voit à
l'exécution que sur les rares chemins qui LISENT l'attribut manquant (le steplog pour
`_scenario_roster_info`), et ces chemins-là ne sont pas atteints par un moteur construit avec
`config=...`. La branche API pouvait donc omettre un attribut pendant longtemps sans qu'aucun
test ne rougisse — jusqu'à ce qu'un lecteur direct le trouve absent. C'est exactement le trou
qui rendait obligatoire un `getattr(self, "_scenario_...", None)` par point de lecture, chacun
masquant l'absence à sa manière. Le contrat vérifié ici est ce qui autorise l'accès direct
(cf. `ai/bot_evaluation.py::_episode_roster_ids`).

Construire réellement les deux branches demanderait un profil d'agent complet et un scénario sur
disque d'un côté, un config d'entrée de l'autre : on comparerait alors deux environnements, pas
deux listes d'affectations. L'AST compare exactement ce que le contrat énonce.
"""

import ast
import inspect
import textwrap

import engine.w40k_core as w40k_core


def _init_branches() -> tuple[ast.If, list[ast.stmt], list[ast.stmt]]:
    """Le `if config is None: ... else: ...` de `__init__`, avec ses deux corps."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(w40k_core.W40KEngine.__init__)))
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    for node in func.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "config"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Is)
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value is None
        ):
            return node, node.body, node.orelse
    raise AssertionError(
        "branche `if config is None:` introuvable dans W40KEngine.__init__ — le test doit "
        "suivre le renommage/déplacement, pas être supprimé"
    )


def _scenario_attrs(body: list[ast.stmt]) -> set[str]:
    """Attributs `self._scenario_*` affectés quelque part dans ce corps."""
    found: set[str] = set()
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr.startswith("_scenario_")
                ):
                    found.add(target.attr)
    return found


def test_les_deux_branches_posent_les_memes_attributs_scenario():
    _, training_body, api_body = _init_branches()
    training_attrs = _scenario_attrs(training_body)
    api_attrs = _scenario_attrs(api_body)

    # VERT VACANT : sans ceci, un parseur qui ne trouve rien ferait passer le test.
    assert "_scenario_roster_info" in training_attrs
    assert len(training_attrs) >= 8

    manquants_cote_api = training_attrs - api_attrs
    assert not manquants_cote_api, (
        "attributs posés par la branche entraînement et absents de la branche API/PvP : "
        f"{sorted(manquants_cote_api)}. Un lecteur direct de ces attributs lèverait "
        "AttributeError sur un moteur construit avec config=... ; poser la valeur métier "
        "(souvent None) dans la branche API, pas un getattr par point de lecture."
    )
    manquants_cote_training = api_attrs - training_attrs
    assert not manquants_cote_training, (
        "attributs posés par la branche API/PvP seule : " f"{sorted(manquants_cote_training)}"
    )


def test_aucune_lecture_defensive_des_attributs_scenario():
    """Aucun `getattr(self, "_scenario_...", <defaut>)` ne subsiste dans le moteur.

    Corollaire du test précédent : si l'attribut existe toujours, un défaut au point de lecture
    ne peut plus couvrir que le renommage silencieux de l'attribut.
    """
    tree = ast.parse(inspect.getsource(w40k_core))
    coupables = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) == 3
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value.startswith("_scenario_")
        ):
            coupables.append((node.lineno, node.args[1].value))
    assert not coupables, f"lectures défensives restantes : {coupables}"
