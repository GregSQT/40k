"""Fixtures des tests d'IA. Les fabriques partagées vivent dans `_fabriques.py` — un module
ordinaire, parce qu'un `conftest.py` importé en plus d'être collecté existe en DEUX exemplaires
(cf. la docstring de `_fabriques`), et qu'un état de module posé ici divergerait entre les deux.
"""

from __future__ import annotations

import pytest

import ai.analyzer_config as ai_analyzer_config


@pytest.fixture(autouse=True)
def _etat_du_run_analyse_remis_a_zero():
    """L'état du run ANALYSÉ (échelle, règles, plateau) est « non posé » à l'entrée de chaque
    test, et l'est de nouveau à sa sortie.

    Ces trois valeurs vivent dans des globales de module (`ai/analyzer_config.py`) : en
    production `parse_step_log` les repose à chaque passe depuis l'entête du journal, mais un
    test qui les pose à la main les LAISSAIT au module pour tous ses voisins du même worker. Le
    voisin qui avait oublié de les poser passait alors en vert — et rougissait le jour où `-n`
    changeait sa place dans la file (mesuré le 2026-08-12 sur le BFS de chemin).

    Remise à `None`, et non à des valeurs « raisonnables » : les getters LÈVENT sans entête, et
    c'est exactement le garde-fou qu'il faut préserver — un plateau ou une échelle par défaut
    rendrait des verdicts faux en silence, ce que ces globales existent pour empêcher.

    Des DEUX côtés du test : à l'entrée pour ne rien hériter d'un voisin (y compris d'un autre
    dossier partageant le worker), à la sortie pour ne rien lui laisser.
    """
    def _remettre_a_zero() -> None:
        ai_analyzer_config._run_inches_to_subhex = None
        ai_analyzer_config._run_rules = None
        ai_analyzer_config._run_board_dims = None

    _remettre_a_zero()
    yield
    _remettre_a_zero()
