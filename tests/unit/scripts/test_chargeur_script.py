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
    module = charger_script("scripts/check_roadmap_declared.py")
    assert module.__name__.startswith("scripts_check_roadmap_declared_sous_test_")
    assert sys.modules.get(module.__name__) is module
    assert "check_roadmap_declared" not in sys.modules


def test_deux_scripts_de_meme_nom_ne_partagent_pas_leur_inscription(tmp_path) -> None:
    """Le nom d'inscription est en bijection avec le CHEMIN, pas avec le nom de fichier.

    Sans ça, deux `outil.py` de deux dossiers s'écrasent l'un l'autre dans `sys.modules` — et
    surtout, l'échec du second retire l'inscription du PREMIER, que le cache continue de rendre.
    Le second est ici volontairement illisible pour exercer exactement ce chemin d'échec.
    """
    premier = tmp_path / "a" / "outil.py"
    premier.parent.mkdir(parents=True)
    premier.write_text("VALEUR = 1\n", encoding="utf-8")
    second = tmp_path / "b" / "outil.py"
    second.parent.mkdir(parents=True)
    second.write_text("raise RuntimeError('boum')\n", encoding="utf-8")

    module = charger_script(str(premier))
    nom = module.__name__
    with pytest.raises(RuntimeError):
        charger_script(str(second))

    assert sys.modules.get(nom) is module
    assert charger_script(str(premier)) is module


def test_deux_chemins_de_meme_partie_lisible_ne_partagent_pas_leur_inscription(tmp_path) -> None:
    """Le `_` qui joint les composants apparaît AUSSI dedans : `a_b/outil` et `a/b_outil` ont la
    même partie lisible. C'est l'empreinte du chemin, et elle seule, qui les sépare — sans elle,
    l'échec du second retire l'inscription du premier, que le cache continue de rendre.
    """
    premier = tmp_path / "a_b" / "outil.py"
    premier.parent.mkdir(parents=True)
    premier.write_text("VALEUR = 1\n", encoding="utf-8")
    second = tmp_path / "a" / "b_outil.py"
    second.parent.mkdir(parents=True)
    second.write_text("raise RuntimeError('boum')\n", encoding="utf-8")

    module = charger_script(str(premier))
    with pytest.raises(RuntimeError):
        charger_script(str(second))

    assert sys.modules.get(module.__name__) is module
    assert charger_script(str(premier)) is module


def test_un_dossier_pointe_ne_collisionne_pas_avec_le_dossier_de_meme_nom(tmp_path) -> None:
    """`a.b/outil` et `a/b/outil` : le point doit disparaître du nom (il ferait de la partie
    gauche un paquet parent), ce qui rendait les deux chemins indiscernables avant l'empreinte."""
    pointe = tmp_path / "a.b" / "outil.py"
    pointe.parent.mkdir(parents=True)
    pointe.write_text("VALEUR = 'pointe'\n", encoding="utf-8")
    imbrique = tmp_path / "a" / "b" / "outil.py"
    imbrique.parent.mkdir(parents=True)
    imbrique.write_text("VALEUR = 'imbrique'\n", encoding="utf-8")

    un = charger_script(str(pointe))
    deux = charger_script(str(imbrique))

    assert un.__name__ != deux.__name__
    assert "." not in un.__name__
    assert un.VALEUR == "pointe" and deux.VALEUR == "imbrique"


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
    # Balayage plutôt qu'un nom écrit en clair : le littéral d'origine désignait un nom que le
    # chargeur n'inscrit plus depuis qu'il préfixe par le chemin, et l'assertion passait donc
    # sans rien regarder. Cette forme-ci ne peut pas se périmer sur un changement de nommage.
    restes = [nom for nom in sys.modules if "ce_script_n_existe_pas" in nom]
    assert restes == [], f"module à moitié exécuté laissé dans sys.modules : {restes}"
