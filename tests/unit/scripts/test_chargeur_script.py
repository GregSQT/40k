"""Verrous du chargeur partagé `tests/_chargeur_script.py`.

Trois choses à tenir, et rien d'autre : le module rendu est bien celui du fichier demandé, un
chemin faux ROUGIT ici plutôt que plus loin sur un `None` anonyme, et deux appels rendent le
MÊME objet — c'est ce dernier point qui décide si un `monkeypatch.setattr` posé par un fichier
de test peut fuir sur un autre, donc il se vérifie au lieu de se supposer.
"""

from __future__ import annotations

import sys

import pytest

from tests._chargeur_script import charger_script


def test_le_module_rendu_est_celui_du_fichier_demande() -> None:
    module = charger_script("scripts/check_doc_references.py")
    assert hasattr(module, "resolve"), "le module chargé n'expose pas `resolve`"
    assert module.__file__ is not None and module.__file__.endswith("check_doc_references.py")


def test_le_module_est_inscrit_dans_sys_modules_sous_un_nom_suffixe() -> None:
    """Le suffixe est ce qui empêche un script de `scripts/` de prendre la place d'un module
    importable homonyme — la raison d'être du nom choisi, pas un détail cosmétique."""
    charger_script("scripts/check_roadmap_declared.py")
    assert "check_roadmap_declared_sous_test" in sys.modules
    assert "check_roadmap_declared" not in sys.modules


def test_deux_appels_rendent_le_meme_objet() -> None:
    """Un script est chargé UNE fois par processus, comme le ferait un `import`.

    Deux fichiers de test chargent `roster_matchup_stats.py` : sans cette identité, chacun
    exécuterait le script de son côté, et l'état de module de l'un serait invisible de l'autre.
    """
    assert charger_script("scripts/roster_matchup_stats.py") is charger_script(
        "scripts/roster_matchup_stats.py"
    )


def test_un_chargement_qui_echoue_leve_et_ne_laisse_rien_derriere_lui() -> None:
    """Un chemin faux rougit ici, et ne laisse pas un module à moitié exécuté dans `sys.modules`.

    Les deux moitiés comptent : l'inscription précède forcément l'exécution, donc sans le retrait
    le chargement suivant du même nom rendrait une coquille vide sans rien signaler.
    """
    with pytest.raises(FileNotFoundError) as erreur:
        charger_script("scripts/ce_script_n_existe_pas.py")
    assert "ce_script_n_existe_pas.py" in str(erreur.value)
    assert "ce_script_n_existe_pas_sous_test" not in sys.modules
