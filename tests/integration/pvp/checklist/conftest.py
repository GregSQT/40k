"""Fixtures de la checklist mouvement : une partie DÉDIÉE, jouée en x5 puis en x1.

Le ``conftest.py`` parent (``tests/integration/pvp/``) reste hérité : ``api_isolated`` en
vient. Ce qui est propre à ce sous-dossier :

  - ``scenario_pvp_checklist.json`` : scénario FIGÉ, positions mesurées par ``test_move.py``.
    ``scenario_pvp_integration.json`` n'est pas retouché — ses tests localisent leurs unités par
    recherche et son en-tête porte « Ne PAS retoucher ».
  - la paramétrisation x5/x1 par ``W40K_BOARD_PATH`` (même geste que ``game_x1`` du parent :
    ``monkeypatch.setenv``, jamais ``os.environ`` posé à la main — la variable est globale au
    process et doit être restaurée avant le test suivant du même worker). Le mode ``pvp`` garde
    le ``scenario_file`` demandé ; ``pvp_test`` le réécrirait.
  - ``check=None`` : les invariants du parent exigent toute figurine vivante SUR le plateau, et
    ce scénario porte deux escouades en réserves stratégiques (20.01) à la sentinelle (-1,-1),
    exactement comme les unités non posées de ``deploy_game``. Les assertions de position sont
    faites par chaque test sur ce qu'il mesure.
"""

from __future__ import annotations

import pytest

from services.api_server import app
from tests.integration.pvp._shared import GameClient

CHECKLIST_SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_checklist.json"
CHECKLIST_DEPLOY_SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_checklist_deploy.json"

#: Plateaux joués, par identifiant de paramètre. Le scénario est écrit en x5 ; le chargeur le
#: convertit en x1 (positions, murs, planchers) parce qu'il vit dans ``44x60x5/scenario/``.
BOARD_BY_RESOLUTION = {"x5": "board/44x60x5", "x1": "board/44x60x1"}


class ChecklistClient(GameClient):
    """``GameClient`` qui connaît la résolution jouée — pour les xfail propres à UNE résolution."""

    resolution: str = ""


def _start(monkeypatch, resolution: str, scenario_file: str, drain: str | None) -> ChecklistClient:
    monkeypatch.setenv("W40K_BOARD_PATH", BOARD_BY_RESOLUTION[resolution])
    flask_client = app.test_client()
    client = ChecklistClient(flask_client, check=None)
    client.resolution = resolution
    client.start(mode_code="pvp", scenario_file=scenario_file)
    if drain is not None:
        client.drain_to(drain)
    return client


@pytest.fixture(params=["x5", "x1"])
def checklist_game(request, api_isolated, monkeypatch):
    """Partie ``scenario_pvp_checklist.json`` rendue en phase de MOUVEMENT du joueur 1, round 1.

    08.04 (Oath of Moment, camp 1 ADEPTUS ASTARTES) est joué par ``drain_to`` comme le fait le
    front, exactement comme la fixture ``game`` du parent.
    """
    yield _start(monkeypatch, request.param, CHECKLIST_SCENARIO, "move")


@pytest.fixture(params=["x5", "x1"])
def declaration_game(request, api_isolated, monkeypatch):
    """Partie ``scenario_pvp_checklist_deploy.json`` ARRÊTÉE sur la première question 20.01.

    Déploiement ACTIF : c'est l'étape Declare Battle Formations, et elle seule, qui applique le
    plafond de 50 % au siège humain (option B retenue le 2026-09-17 contre un scénario refusé au
    chargement, qui n'aurait testé que le chargeur).
    """
    yield _start(monkeypatch, request.param, CHECKLIST_DEPLOY_SCENARIO, None)
