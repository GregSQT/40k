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

import hashlib
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


def _nom_de_module(chemin: Path) -> str:
    """Nom d'inscription dans `sys.modules`, unique pour un chemin résolu donné.

    Les composants du chemin donnent la partie LISIBLE, l'empreinte donne l'UNICITÉ, et elle
    seule : aucun assemblage des composants n'est injectif, puisque le `_` qui les joint apparaît
    aussi À L'INTÉRIEUR d'un composant (`scripts/a_b/outil` et `scripts/a/b_outil` se rejoignent),
    et que le `.` d'un dossier doit disparaître — un point ferait de la partie gauche un paquet
    parent aux yeux de l'import. Deux chemins de même partie lisible se distinguent donc par leur
    empreinte, ce dont dépend la garantie de `charger_script` : un nom aussi unique que la clé de
    cache, sinon l'échec de l'un retire de `sys.modules` l'inscription de l'autre.

    Un chemin hors du dépôt garde ses composants absolus : le nom reste laid, mais lisible et
    unique aux mêmes conditions.
    """
    relatif = chemin.relative_to(RACINE) if chemin.is_relative_to(RACINE) else chemin
    composants = [partie for partie in relatif.with_suffix("").parts if partie not in ("/", "")]
    empreinte = hashlib.blake2s(chemin.as_posix().encode("utf-8"), digest_size=4).hexdigest()
    lisible = "_".join([*composants, "sous_test"]).replace(".", "_").replace(" ", "_")
    return f"{lisible}_{empreinte}"


def charger_script(chemin_relatif: str) -> ModuleType:
    """Charge `chemin_relatif` (depuis la racine du dépôt) comme module et le rend.

    Le module est inscrit dans `sys.modules` sous un nom dérivé du CHEMIN entier
    (`scripts_check_doc_references_sous_test_<empreinte>`), pas du seul nom de fichier. Deux
    raisons, et la seconde est la vraie : le suffixe évite qu'un script prenne la place d'un
    module importable homonyme, et l'empreinte du chemin garantit que le nom d'inscription est
    aussi unique que la clé du cache (cf. `_nom_de_module`). Sinon deux scripts de même nom dans
    deux dossiers partageraient une inscription, et l'échec du second RETIRERAIT de `sys.modules`
    le module du premier — que `_CHARGES` continuerait pourtant de rendre.

    Aucune garde d'existence du fichier ici : `exec_module` lève déjà un `FileNotFoundError` qui
    nomme le chemin absolu (vérifié). En ajouter une ne ferait que doubler le même message.
    """
    chemin = (RACINE / chemin_relatif).resolve()
    module = _CHARGES.get(chemin)
    if module is not None:
        return module

    nom = _nom_de_module(chemin)
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
