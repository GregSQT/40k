"""Fixtures des tests d'IA. Les fabriques partagées vivent dans `_fabriques.py` — un module
ordinaire, parce qu'un `conftest.py` importé en plus d'être collecté existe en DEUX exemplaires
(cf. la docstring de `_fabriques`), et qu'un état de module posé ici divergerait entre les deux.
"""

from __future__ import annotations

import os

import pytest

from ai.analyzer_config import reset_run_state


@pytest.fixture(autouse=True)
def _etat_du_run_analyse_remis_a_zero():
    """L'état du run ANALYSÉ (échelle, règles, plateau) est « non posé » à l'entrée de chaque
    test, et l'est de nouveau à sa sortie.

    Le POURQUOI est chez le propriétaire de ces valeurs (`ai.analyzer_config.reset_run_state`) ;
    ici, la seule décision est la PORTÉE. Des deux côtés du test : à l'entrée pour ne rien
    hériter d'un voisin (y compris d'un autre dossier partageant le worker), à la sortie pour ne
    rien lui laisser. Par TEST et non par module : c'est entre deux tests voisins que la fuite a
    été mesurée (2026-08-12, le BFS de chemin passait sur le plateau du test précédent).
    """
    reset_run_state()
    yield
    reset_run_state()


@pytest.fixture(autouse=True)
def _board_path_test_isolation():
    """Isole W40K_BOARD_PATH par test : main() peut poser cette variable via os.environ ;
    sans restauration, les tests moteur suivants héritent d'une résolution de plateau inattendue."""
    previous = os.environ.get("W40K_BOARD_PATH")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous
