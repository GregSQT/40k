"""Chargement d'un script de `scripts/` comme module, pour les tests qui verrouillent son
comportement.

Les fichiers de `scripts/` ne sont pas importables : ce ne sont pas des modules d'un paquet, ils
vivent hors des chemins d'import du dépôt. Sept fichiers de test recopiaient donc À L'IDENTIQUE
le même bloc `spec_from_file_location` / garde `spec is None or spec.loader is None` /
`sys.modules[...]` / `exec_module` — dont la garde, qui est la seule ligne du bloc qui décide de
quelque chose : sans elle, un chemin faux ne rougit pas ici mais plus loin, sur un `None` qui ne
dit pas d'où il vient.

POURQUOI UN MODULE ORDINAIRE PLUTÔT QU'UNE FIXTURE DE `conftest.py`. Deux raisons, dans cet
ordre. D'abord, trois des sept appelants chargent leur script au niveau MODULE
(`test_check_doc_references.py`, `test_check_roadmap_declared.py`,
`test_scenario_bank_migration_v11.py`) : une fixture ne s'y consomme pas, il faudrait la
demander en paramètre dans les 117 fonctions de test concernées, sans qu'aucune ne s'en serve
autrement que par le nom de module qu'elle a déjà. Ensuite, c'est la forme que ce dépôt a déjà
retenue pour ses helpers de test partagés (`tests/_state_invariants.py`,
`tests/unit/ai/_fabriques.py`) — précisément parce qu'un `conftest.py` qu'on importe existe en
deux exemplaires (cf. la docstring de `_fabriques`), ce qu'un module ordinaire ne fait pas.

Un appelant qui veut malgré tout une fixture l'écrit chez lui en une ligne : elle appelle
`charger_script`. C'est le cas des quatre autres, qui gardent leur fixture.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

RACINE = Path(__file__).resolve().parent.parent

#: Un script chargé une seule fois par processus, comme le ferait un `import`. Les tests qui
#: modifient un attribut du module passent tous par `monkeypatch`, qui le rétablit — vérifié sur
#: les sept appelants. Un test qui écrirait DIRECTEMENT dans le module fuiterait donc sur ses
#: voisins : c'est déjà vrai d'un `import` ordinaire, et ça reste interdit pour la même raison.
_CHARGES: dict[Path, ModuleType] = {}


def charger_script(chemin_relatif: str) -> ModuleType:
    """Charge `chemin_relatif` (depuis la racine du dépôt) comme module et le rend.

    Le module est inscrit dans `sys.modules` sous `<nom_du_fichier>_sous_test` : le suffixe
    évite qu'un script de `scripts/` prenne la place d'un module importable du même nom, et le
    fait de l'y inscrire est ce qui permet aux dataclasses et aux exceptions qu'il définit de se
    retrouver elles-mêmes.

    Aucune garde d'existence du fichier ici : `exec_module` lève déjà un `FileNotFoundError` qui
    nomme le chemin absolu (vérifié). En ajouter une ne ferait que doubler le même message.
    """
    chemin = (RACINE / chemin_relatif).resolve()
    module = _CHARGES.get(chemin)
    if module is not None:
        return module

    nom = f"{chemin.stem}_sous_test"
    spec = importlib.util.spec_from_file_location(nom, chemin)
    if spec is None or spec.loader is None:
        raise ImportError(f"impossible de construire la spec du module pour {chemin}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # L'inscription précède l'exécution (elle doit : le script peut se référencer lui-même).
        # Un échec laisserait donc sous ce nom un module À MOITIÉ exécuté, que le chargement
        # suivant — ou n'importe quel `import` — prendrait pour un module valide.
        del sys.modules[nom]
        raise
    _CHARGES[chemin] = module
    return module
