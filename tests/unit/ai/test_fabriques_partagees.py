"""Les fabriques partagées des tests d'IA n'existent qu'en UN exemplaire.

Ce que coûte le second exemplaire, et pourquoi ces fabriques ont quitté le `conftest.py` :
docstring de `_fabriques`. Ici, deux contrôles seulement — l'état (un module, un objet) et le
geste qui le défait (un conftest importé).
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


def test_aucun_test_n_importe_le_conftest_comme_module() -> None:
    """C'est l'import qui fabrique la seconde copie — pas le conftest lui-même.

    Le contrôle porte donc sur le geste, et pas sur le symptôme : un import ajouté demain
    rouvrirait exactement le même trou, et le test ci-dessus ne le verrait que si ce fichier-là
    est collecté dans la même session.
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
