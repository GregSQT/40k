"""Un fichier de test = un module, et les fabriques partagées s'importent par leur chemin.

Ce que coûte le second exemplaire d'un même fichier, et pourquoi les fabriques ont quitté le
`conftest.py` : docstring de `_fabriques`. Ici, quatre contrôles — l'état (un module, un objet),
la règle de nommage qui le garantit, et les deux gestes qui la défont (importer un conftest,
importer un frère par son nom nu).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from tests.unit.ai import _fabriques

_RACINE = Path(__file__).resolve().parents[3]
# L'IMPORT, pas la mention : ce fichier parle de `conftest` en toutes lettres dans ses messages,
# et une recherche de sous-chaîne se serait dénoncée elle-même. Deux formes suffisent à couvrir
# les cinq gestes qui chargent le module — les quatre écritures d'un `import` (dont
# `from … import conftest`, la plus naturelle) tiennent dans la première.
_IMPORT_DE_CONFTEST = re.compile(
    r"""
      ^\s*(?:from|import)\s+.*\bconftest\b   # les quatre écritures d'une ligne d'import
    | import_module\(\s*['"][^'"]*conftest   # chargement par nom de module via importlib
    """,
    re.M | re.X,
)
# Import d'un fichier VOISIN par son nom nu (`from _config_helpers import …`,
# `from test_objective_held_samples import …`). Il marchait tant que le dossier du test était sur
# `sys.path` ; avec le nommage par chemin complet il ne l'est plus, et la collecte du fichier
# fautif échoue. 22 sites étaient dans ce cas le 2026-08-12. `from __future__` est exclu par le
# `(?!_)` — c'est le seul nom à double underscore que ce dépôt importe.
_IMPORT_DE_FRERE_NU = re.compile(r"^\s*from\s+(?:_(?!_)|test_)\w*\s+import\b", re.M)


def test_les_fabriques_ne_sont_chargees_qu_une_fois() -> None:
    """Un seul objet module pour le fichier des fabriques, quel que soit le nom d'import."""
    fichier = _fabriques.__file__
    assert fichier, "module sans fichier : le contrôle ne regarderait rien"
    charges = sorted(
        nom for nom, module in list(sys.modules.items())
        if getattr(module, "__file__", None) == fichier
    )
    assert charges == ["tests.unit.ai._fabriques"], (
        f"le fichier des fabriques est chargé sous plusieurs noms : {charges}"
    )


def test_les_conftest_sont_nommes_par_leur_chemin_complet() -> None:
    """LA CAUSE RACINE, fermée à la racine : `consider_namespace_packages` (`pytest.ini`).

    Sans elle, `tests/` n'étant pas un paquet, le harnais nomme un `conftest.py` d'après son
    dossier seul — `conftest` — pendant qu'un test qui l'importe le nomme
    `tests.unit.ai.conftest`. Deux noms, deux objets module, deux copies de son état.

    Ce contrôle mesure l'EFFET de l'option, pas sa présence dans le fichier de config : retirer
    la ligne le fait rougir, la commenter aussi, et un futur harnais qui changerait de règle de
    nommage également — ce qu'une simple lecture de `pytest.ini` ne verrait pas.
    """
    charges = {
        nom: Path(fichier).name
        for nom, module in list(sys.modules.items())
        if (fichier := getattr(module, "__file__", None))
    }
    conftests = sorted(nom for nom, base in charges.items() if base == "conftest.py")
    assert conftests, "aucun conftest chargé : le contrôle ne regarderait rien"
    nus = [nom for nom in conftests if not nom.startswith("tests.")]
    assert not nus, (
        f"conftest chargé hors de son chemin complet : {nus} — `consider_namespace_packages` "
        "a disparu de pytest.ini, et le même fichier peut de nouveau exister en deux exemplaires"
    )


def test_aucun_test_n_importe_le_conftest_comme_module() -> None:
    """SECONDE LIGNE, derrière la fermeture de la cause racine ci-dessus.

    Importer un `conftest.py` reste un geste à éviter — c'est lui qui fabriquait la seconde
    copie, et il redeviendrait nuisible le jour où l'option de nommage tomberait. Le contrôle
    porte sur le geste, donc il tient même quand aucun des fichiers concernés n'est collecté
    dans la session courante.
    """
    fichiers = sorted((_RACINE / "tests").rglob("*.py"))
    assert fichiers, "aucun fichier de test énuméré : le contrôle ne regarderait rien"
    fautifs = []
    for chemin in fichiers:
        texte = chemin.read_text(encoding="utf-8")
        # Pré-filtre STRICTEMENT équivalent : les deux formes exigent le littéral `conftest`, et
        # 12 fichiers sur 389 le portent. Sans lui, la regex tourne sur 4,7 Mo pour rien (77 ms
        # des 90 ms du test) — le contrôle regarde toujours autant de fichiers, il les lit juste
        # sans dérouler l'alternance sur ceux qui ne peuvent pas correspondre.
        if "conftest" not in texte:
            continue
        if _IMPORT_DE_CONFTEST.search(texte):
            fautifs.append(str(chemin.relative_to(_RACINE)))
    assert not fautifs, (
        "un conftest importé comme module existe en deux exemplaires (cf. la docstring de "
        f"tests/unit/ai/_fabriques.py) — importer depuis `_fabriques` : {fautifs}"
    )


def test_aucun_test_n_importe_un_frere_par_son_nom_nu() -> None:
    """L'autre geste que le nommage par chemin complet interdit.

    Le dossier d'un fichier de test n'est plus sur `sys.path` : `from _config_helpers import …`
    lève à la COLLECTE. Le défaut ne se voit donc que si le fichier fautif est collecté — un
    lot ciblé qui ne le contient pas reste vert, et la panne attend la vérification large.
    Ce contrôle la voit tout de suite, et il dit quoi écrire à la place.
    """
    fichiers = sorted((_RACINE / "tests").rglob("*.py"))
    assert fichiers, "aucun fichier de test énuméré : le contrôle ne regarderait rien"
    fautifs = [
        str(chemin.relative_to(_RACINE))
        for chemin in fichiers
        if _IMPORT_DE_FRERE_NU.search(chemin.read_text(encoding="utf-8"))
    ]
    assert not fautifs, (
        "import d'un fichier voisin par son nom nu : il lèvera à la collecte. Écrire le chemin "
        f"complet (`from tests.unit.<dossier>.<module> import …`) : {fautifs}"
    )
