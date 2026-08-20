"""Socle des tests d'intégration PvP : une vraie partie pilotée en in-process.

Pourquoi in-process et pas un script HTTP externe (``scripts/pvp_smoke_test.py``) :
tous les jets de dés du moteur passent par le ``random`` global du stdlib
(``combat_utils.resolve_dice_value``, ``charge_handlers`` 2D6, ``roll_d6`` injecté dans
``attack_sequence``). Le ``deterministic_seed`` autouse de ``tests/conftest.py`` pose donc
la seed du moteur lui-même : les résultats de tir/charge/mêlée sont reproductibles, ce
qu'un client HTTP dans un autre process ne peut pas obtenir.

Le script HTTP reste le smoke test de la vraie stack (réseau + auth + serveur réel) ;
ces tests-ci couvrent le contrat de données que le front consomme.

Isolation exigée (aucune écriture hors de la mémoire du test) :
  - ``config/users.db`` n'est JAMAIS ouverte (auth et permissions injectées) ;
  - la persistance des snapshots/saves est coupée : à l'import, ``api_server`` charge
    ``logs/save_config.json`` qui active la persistance disque en usage normal.
"""

from __future__ import annotations

import pytest

import services.api_server as api_server
from services.api_server import app
from tests.integration.pvp._shared import (
    ActionRejected,
    GameClient,
    INTEGRATION_SCENARIO,
    _TEST_AUTH_USER,
    _TEST_PERMISSIONS,
    _in_memory_write_cursor,
    assert_game_states_equal,
)

__all__ = [
    "ActionRejected",
    "GameClient",
    "INTEGRATION_SCENARIO",
    "_TEST_AUTH_USER",
    "_TEST_PERMISSIONS",
    "assert_game_states_equal",
]


@pytest.fixture
def api_isolated(monkeypatch):
    """Neutralise les effets de bord hors mémoire : users.db et persistance disque."""
    monkeypatch.setattr(api_server, "_get_authenticated_user_or_response", lambda: (_TEST_AUTH_USER, None))
    monkeypatch.setattr(api_server, "_resolve_permissions_for_profile", lambda _conn, _pid: _TEST_PERMISSIONS)
    monkeypatch.setattr(api_server, "auth_db_write_cursor", _in_memory_write_cursor)
    # api_server charge logs/save_config.json à l'import : en usage normal la persistance
    # des snapshots et l'autosave sont actifs et écriraient sur le disque de l'utilisateur.
    monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
    monkeypatch.setattr(api_server, "_AUTOSAVE_ENABLED", False)
    yield
    # Le moteur est une globale de module : ne pas laisser la partie d'un test au suivant.
    api_server.engine = None


@pytest.fixture
def api_disk_only_isolated(monkeypatch):
    """Neutralise UNIQUEMENT les effets de bord disque — auth réelle, non bypassée.

    Utilisée uniquement par les tests d'authentification : sans ce patch, ``_get_authenticated_user_or_response``
    tenterait une DB write au login. Ici la ValueError est levée AVANT tout accès DB (pas de
    header), donc le test est propre. On neutralise juste les writes d'auth et la persistance.
    """
    monkeypatch.setattr(api_server, "auth_db_write_cursor", _in_memory_write_cursor)
    monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
    monkeypatch.setattr(api_server, "_AUTOSAVE_ENABLED", False)
    yield
    api_server.engine = None


@pytest.fixture
def game(api_isolated):
    """Partie ``INTEGRATION_SCENARIO`` démarrée, invariants armés, rendue en phase de MOUVEMENT.

    ``/start`` rend la main en phase de COMMANDEMENT depuis le chantier des capacités de faction :
    08.04 y arrête le moteur sur la désignation d'Oath of Moment (le camp 1 de la fixture est
    ADEPTUS ASTARTES), et cet arrêt est opposable — toute autre action y est refusée
    (``faction_decision_pending``). La fixture joue donc ce que le front joue : la désignation,
    puis la sortie de phase. Les tests qui mesurent le mouvement, le tir, la charge ou la mêlée
    reprennent ainsi là où ils l'ont toujours fait.

    La phase de commandement elle-même est vérifiée par ``TestStartState``, sur ``game_unchecked``
    qui, lui, ne joue rien.
    """
    from tests.integration.pvp.invariants import assert_state_invariants

    with app.test_client() as flask_client:
        client = GameClient(flask_client, check=assert_state_invariants)
        client.start()
        client.drain_to("move")
        yield client


@pytest.fixture
def game_unchecked(api_isolated):
    """Même partie, SANS revalidation automatique.

    Réservé aux tests qui vérifient les invariants eux-mêmes (sinon un échec d'invariant
    ferait échouer le test avant son assertion propre, en masquant ce qu'il mesurait).
    """
    with app.test_client() as flask_client:
        client = GameClient(flask_client)
        client.start()
        yield client
