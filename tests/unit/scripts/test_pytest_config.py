"""Verrous sur `pytest.ini` — la configuration du harnais qui rend des défauts VISIBLES.

Une option retirée de `pytest.ini` ne casse rien : la suite reste verte, elle regarde simplement
moins de choses. C'est le mode de disparition le plus silencieux qui soit, et le seul contrôle
possible est de relire le fichier.
"""

from __future__ import annotations

import configparser
import warnings
from pathlib import Path

import pytest

PYTEST_INI = Path(__file__).resolve().parents[3] / "pytest.ini"


def _pytest_ini_section() -> dict:
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI, encoding="utf-8")
    assert parser.has_section("pytest"), f"{PYTEST_INI} sans section [pytest]"
    return dict(parser["pytest"])


def test_deprecations_are_errors() -> None:
    """Une API dépréciée par une dépendance doit faire ÉCHOUER la suite, pas la commenter.

    Mesuré le 2026-08-12 : `get_schedule_fn()` était dépréciée depuis une version majeure entière
    de SB3 et s'affichait à chaque exécution, sans que rien ne la traite. Le training ne peut pas
    jouer ce rôle (les appels ont lieu au chargement du modèle, la sortie est noyée) : la suite
    est le seul endroit où ces avis sont lus.
    """
    filtres = _pytest_ini_section().get("filterwarnings", "")
    assert "error:.*is deprecated" in filtres, (
        "pytest.ini a perdu son filtre `error:.*is deprecated` : les depreciations des "
        "dependances redeviennent une ligne de resume que personne ne traite."
    )


def test_the_deprecation_filter_matches_a_bare_userwarning() -> None:
    """Le filtre doit porter sur le MESSAGE, pas sur `DeprecationWarning`.

    VERT VACANT : c'est le piège exact de ce réglage. SB3 lève des `UserWarning` nus
    (stable_baselines3/common/utils.py:166), donc un filtre `error::DeprecationWarning` serait
    présent, lisible, et n'attraperait RIEN. Ce test construit l'avertissement tel que SB3
    l'émet et vérifie que la règle configurée le transforme bien en erreur.
    """
    brut = _pytest_ini_section().get("filterwarnings")
    assert brut, "pytest.ini n'a plus de `filterwarnings` : rien ne transforme un avis en echec."
    filtres = [ligne for ligne in brut.splitlines() if ligne.strip()]
    with warnings.catch_warnings():
        warnings.resetwarnings()
        for ligne in filtres:
            action, _, motif = ligne.partition(":")
            warnings.filterwarnings(action.strip(), message=motif)
        with pytest.raises(UserWarning, match="is deprecated"):
            warnings.warn("get_schedule_fn() is deprecated, please use FloatSchedule() instead")
