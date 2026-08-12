"""Les fabriques partagées des tests d'IA n'existent qu'en UN exemplaire.

Elles ont vécu dans `conftest.py`, importé à la fois par le harnais (sous le nom `conftest`) et
par sept fichiers de test (sous `tests.unit.ai.conftest`). `tests/` n'ayant pas d'`__init__.py`,
les deux chemins ne se rejoignent pas dans `sys.modules` : deux objets module, deux caches
`lru_cache`, et surtout deux copies de tout état de module — celle que voient les fixtures et
celle qu'importent les tests. Rien ne l'aurait signalé le jour où un état y serait apparu.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from tests.unit.ai import _fabriques

_RACINE = Path(__file__).resolve().parents[3]
# L'IMPORT, pas la mention : ce fichier parle de `conftest` en toutes lettres dans ses messages,
# et une recherche de sous-chaîne se serait dénoncée elle-même.
_IMPORT_DE_CONFTEST = re.compile(r"^\s*(?:from\s+\S*conftest\s+import|import\s+\S*conftest)", re.M)


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

    Le contrôle porte donc sur le geste, et pas sur le symptôme : un `from ....conftest import`
    ajouté demain rouvrirait exactement le même trou, et le test ci-dessus ne le verrait que si
    ce fichier-là est collecté dans la même session.
    """
    fichiers = sorted((_RACINE / "tests").rglob("*.py"))
    assert fichiers, "aucun fichier de test énuméré : le contrôle ne regarderait rien"
    fautifs = [
        str(chemin.relative_to(_RACINE))
        for chemin in fichiers
        if _IMPORT_DE_CONFTEST.search(chemin.read_text(encoding="utf-8"))
    ]
    assert not fautifs, (
        "un conftest importé comme module existe en deux exemplaires (cf. la docstring de "
        f"tests/unit/ai/_fabriques.py) — importer depuis `_fabriques` : {fautifs}"
    )
