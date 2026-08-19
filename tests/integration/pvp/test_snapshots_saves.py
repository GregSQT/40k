"""T7 — Snapshots/rewind, save/load et authentification.

Trois contrats API non couverts par les autres tranches :

1. Snapshots temporels (``GET /api/game/snapshots``, ``POST /api/game/snapshot/restore``) :
   les snapshots sont capturés en MÉMOIRE dès qu'une phase nouvelle est atteinte ; la
   persistance disque (``_SNAPSHOT_PERSIST_ENABLED``) n'est pas nécessaire ici.

2. Save/load (``POST /api/game/save``, ``POST /api/game/save/load``) :
   - sans persistence activée → refus explicite ;
   - avec persistence (``tmp_path``) → round-trip view + resume, égalité JSON champ par champ.

3. Authentification :
   - aucun token → 401 immédiat (ValueError avant toute accès DB) ;
   - partie PvP en cours + profil sans droit PvP → 403.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict

import pytest

import services.api_server as api_server
from services.api_server import app
from services.game_saves import SaveStore
from tests.integration.pvp.conftest import (
    INTEGRATION_SCENARIO,
    GameClient,
    _TEST_AUTH_USER,
    _TEST_PERMISSIONS,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixture spécialisée : isolation disque SANS bypass d'auth
# ---------------------------------------------------------------------------


@pytest.fixture
def api_disk_only_isolated(monkeypatch):
    """Neutralise UNIQUEMENT les effets de bord disque — auth réelle, non bypassée.

    Utilisée uniquement par les tests d'authentification : sans ce patch, ``_get_authenticated_user_or_response``
    tenterait une DB write au login. Ici la ValueError est levée AVANT tout accès DB (pas de
    header), donc le test est propre. On neutralise juste les writes d'auth et la persistance.
    """

    @contextmanager
    def _in_memory_write_cursor(immediate: bool = False):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            yield connection.cursor()
        finally:
            connection.close()

    monkeypatch.setattr(api_server, "auth_db_write_cursor", _in_memory_write_cursor)
    monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", False)
    monkeypatch.setattr(api_server, "_AUTOSAVE_ENABLED", False)
    yield
    api_server.engine = None


# ---------------------------------------------------------------------------
# T7 — Snapshots (en mémoire, pas de disque)
# ---------------------------------------------------------------------------


class TestSnapshots:
    def test_snapshot_list_populated_after_phase_reached(self, game):
        """t7_snap_list : au moins un snapshot est capturé au démarrage (phase command ou move).

        ``_capture_and_autosave`` → ``maybe_capture`` est appelé lors du ``/start`` et après
        chaque transition de phase : l'état courant doit être dans le store.
        """
        resp = game._client.get("/api/game/snapshots")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        snaps = body["snapshots"]
        assert snaps, "aucun snapshot capturé : maybe_capture n'a pas été appelé"
        for snap in snaps:
            assert "turn" in snap and "player" in snap and "phase" in snap, (
                f"metadata snapshot incomplète : {snap}"
            )

    def test_snapshot_view_returns_state_at_captured_phase(self, game):
        """t7_snap_view : mode ``view`` renvoie l'état du snapshot, sans muter la partie.

        Le snapshot est le PREMIER de la liste (le plus ancien : command → move).
        L'état vivant après le view ne doit pas avoir changé.
        """
        snaps = game._client.get("/api/game/snapshots").get_json()["snapshots"]
        assert snaps, "pas de snapshot à tester"
        target = snaps[0]

        state_before = game.refresh()

        resp = game._client.post(
            "/api/game/snapshot/restore",
            json={"turn": target["turn"], "player": target["player"], "phase": target["phase"], "mode": "view"},
        )
        assert resp.status_code == 200, f"restore view a échoué : {resp.get_json()}"
        body = resp.get_json()
        assert body["success"] is True
        assert body["mode"] == "view"
        restored = body["game_state"]
        assert restored["turn"] == target["turn"]
        assert restored["current_player"] == target["player"]
        assert restored["phase"] == target["phase"]

        # Le state vivant ne doit pas avoir bougé.
        state_after = game.refresh()
        differences = sorted(
            k for k in set(state_before) | set(state_after) if state_before.get(k) != state_after.get(k)
        )
        assert not differences, (
            f"mode 'view' a muté l'état vivant, champs modifiés : {differences}"
        )

    def test_snapshot_resume_replaces_live_state(self, game):
        """t7_snap_resume : mode ``resume`` remplace l'état vivant par le snapshot.

        On joue quelques actions, puis on revient au snapshot de départ. L'état résultant
        doit être strictement égal à ce que ``view`` avait retourné.
        """
        snaps = game._client.get("/api/game/snapshots").get_json()["snapshots"]
        assert snaps, "pas de snapshot à tester"
        target = snaps[0]

        # État attendu : lire le snapshot en mode view avant de muter quoi que ce soit.
        view_resp = game._client.post(
            "/api/game/snapshot/restore",
            json={"turn": target["turn"], "player": target["player"], "phase": target["phase"], "mode": "view"},
        )
        expected = view_resp.get_json()["game_state"]

        # Avancer la partie d'au moins une action.
        game.play_nominal(max_actions=5, until=lambda c: c.phase == "move")

        # Resume : remplacer l'état vivant.
        resp = game._client.post(
            "/api/game/snapshot/restore",
            json={"turn": target["turn"], "player": target["player"], "phase": target["phase"], "mode": "resume"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["mode"] == "resume"
        live = body["game_state"]

        assert live["turn"] == expected["turn"]
        assert live["current_player"] == expected["current_player"]
        assert live["phase"] == expected["phase"]

    def test_snapshot_restore_unknown_key_returns_404(self, game):
        """t7_snap_404 : un snapshot inexistant renvoie 404, pas une 500."""
        resp = game._client.post(
            "/api/game/snapshot/restore",
            json={"turn": 9999, "player": 1, "phase": "move", "mode": "view"},
        )
        assert resp.status_code == 404, (
            f"snapshot inconnu aurait dû donner 404, obtenu {resp.status_code}"
        )
        body = resp.get_json()
        assert body["success"] is False

    def test_snapshot_strict_field_equality_after_many_actions(self, game):
        """t7_snap_strict_eq : après plusieurs actions, resume → état STRICTEMENT égal au snapshot.

        Même invariant que _assert_inert (test_invariants.py) : comparaison champ à champ
        de TOUS les champs du game_state entre view (état figé) et resume (état restauré).

        view et resume appellent tous deux _game_state_for_json sur le même game_state
        reconstruit depuis le snapshot (build_game_state) : la sérialisation doit être
        bit-à-bit identique. Toute divergence révèle soit un champ non capturé dans le
        snapshot, soit une dérive de sérialisation entre les deux chemins.
        """
        snaps = game._client.get("/api/game/snapshots").get_json()["snapshots"]
        assert snaps, "pas de snapshot à tester"
        target = snaps[0]

        view_resp = game._client.post(
            "/api/game/snapshot/restore",
            json={"turn": target["turn"], "player": target["player"], "phase": target["phase"], "mode": "view"},
        )
        assert view_resp.status_code == 200
        expected = view_resp.get_json()["game_state"]

        # Diverger significativement du snapshot avant de le restaurer : drainer le pool de
        # move en entier (l'intégration démarre en move, ~21 unités → ~30-50 actions).
        game.play_nominal(max_actions=200, until=lambda c: c.phase != "move")

        resume_resp = game._client.post(
            "/api/game/snapshot/restore",
            json={"turn": target["turn"], "player": target["player"], "phase": target["phase"], "mode": "resume"},
        )
        assert resume_resp.status_code == 200
        live = resume_resp.get_json()["game_state"]

        differences = sorted(k for k in set(expected) | set(live) if expected.get(k) != live.get(k))
        assert not differences, (
            f"état restauré diffère du snapshot (view vs resume) sur : {differences}"
        )


# ---------------------------------------------------------------------------
# T7 — Save / load
# ---------------------------------------------------------------------------


class TestSaveLoad:
    def test_create_save_without_persistence_returns_error(self, game):
        """t7_save_nopersist : sans persistance, /api/game/save renvoie une erreur explicite.

        L'API retourne 400 (pas 200) quand ``_SNAPSHOT_PERSIST_ENABLED=False``.
        """
        resp = game._client.post("/api/game/save", json={"note": "test"})
        assert resp.status_code == 400, (
            f"attendu 400 sans persistance, obtenu {resp.status_code}"
        )
        body = resp.get_json()
        assert body["success"] is False
        assert body.get("error"), "refus sans message d'erreur"

    def test_save_view_roundtrip(self, game, tmp_path, monkeypatch):
        """t7_save_view : save → list → load-view → état identique au moment de la sauvegarde.

        Mode ``view`` : l'état vivant n'est pas remplacé, mais le state retourné doit correspondre
        à ce que le moteur avait lors du save. On vérifie phase, tour, joueur actif.
        """
        store = SaveStore(str(tmp_path / "parties"))
        monkeypatch.setattr(api_server, "_SAVE_STORE", store)
        monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", True)
        monkeypatch.setattr(api_server, "_persist_save_config", lambda: None)

        # Ouvrir la partie de saves (normalement fait au start quand persist=True).
        store.start_party(api_server.engine, "test_party", "20260101-000000")

        # Capturer l'état AVANT le save.
        state_at_save = game.refresh()

        resp_save = game._client.post("/api/game/save", json={"note": "t7"})
        assert resp_save.status_code == 200
        assert resp_save.get_json()["success"] is True
        save_meta = resp_save.get_json()["save"]
        save_id = save_meta["id"]

        # Avancer d'une action.
        action, payload = game.nominal_action()
        game.act(action, **payload)

        # Load view.
        resp_load = game._client.post("/api/game/save/load", json={"id": save_id, "mode": "view"})
        assert resp_load.status_code == 200
        body = resp_load.get_json()
        assert body["success"] is True
        assert body["mode"] == "view"
        view_state = body["game_state"]

        assert view_state["turn"] == state_at_save["turn"]
        assert view_state["current_player"] == state_at_save["current_player"]
        assert view_state["phase"] == state_at_save["phase"]

    def test_save_strict_field_equality_after_resume(self, game, tmp_path, monkeypatch):
        """t7_save_strict_eq : après resume, l'état vivant est STRICTEMENT identique au save.

        Même invariant que _assert_inert (test_invariants.py) : comparaison champ à champ
        de TOUS les champs entre l'état capturé par /state AVANT le save et le game_state
        retourné par le resume. apply_live_state (game_snapshots.py) doit restaurer tous
        les champs mutables ET les attrs engine — une divergence révèle un champ non capturé.
        """
        store = SaveStore(str(tmp_path / "parties_strict"))
        monkeypatch.setattr(api_server, "_SAVE_STORE", store)
        monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", True)
        monkeypatch.setattr(api_server, "_persist_save_config", lambda: None)

        store.start_party(api_server.engine, "test_strict_eq", "20260101-000002")

        # Capturer l'état AVANT le save (via /state — même chemin de sérialisation que le resume).
        state_at_save = game.refresh()

        resp_save = game._client.post("/api/game/save", json={"note": "strict_eq"})
        assert resp_save.get_json()["success"] is True
        save_id = resp_save.get_json()["save"]["id"]

        # Diverger du save : drainer le pool de move puis avancer de phase.
        game.play_nominal(max_actions=200, until=lambda c: c.phase != state_at_save["phase"])

        resp_resume = game._client.post(
            "/api/game/save/load", json={"id": save_id, "mode": "resume", "fork": "overwrite"}
        )
        assert resp_resume.status_code == 200
        assert resp_resume.get_json()["success"] is True
        live = resp_resume.get_json()["game_state"]

        differences = sorted(k for k in set(state_at_save) | set(live) if state_at_save.get(k) != live.get(k))
        assert not differences, (
            f"état après resume diffère de l'état au moment du save sur : {differences}"
        )

    def test_save_resume_restores_state(self, game, tmp_path, monkeypatch):
        """t7_save_resume : après resume, l'état vivant correspond au snapshot au moment du save."""
        store = SaveStore(str(tmp_path / "parties"))
        monkeypatch.setattr(api_server, "_SAVE_STORE", store)
        monkeypatch.setattr(api_server, "_SNAPSHOT_PERSIST_ENABLED", True)
        monkeypatch.setattr(api_server, "_persist_save_config", lambda: None)

        store.start_party(api_server.engine, "test_party", "20260101-000001")

        state_at_save = game.refresh()
        resp_save = game._client.post("/api/game/save", json={"note": "resume_test"})
        assert resp_save.get_json()["success"] is True
        save_id = resp_save.get_json()["save"]["id"]

        # Avancer suffisamment pour changer de phase (la pool move peut avoir >10 unités).
        game.play_nominal(max_actions=50, until=lambda c: c.phase != state_at_save["phase"])

        # Resume avec "fork": "overwrite" : _timeline_capture ajoute des rows après chaque action
        # quand _SNAPSHOT_PERSIST_ENABLED=True, donc il y a des rows postérieures au save-point.
        # Le front afficherait une popup de divergence ; ici on simule la décision "overwrite".
        resp_load = game._client.post(
            "/api/game/save/load", json={"id": save_id, "mode": "resume", "fork": "overwrite"}
        )
        assert resp_load.status_code == 200
        body = resp_load.get_json()
        assert body["success"] is True, f"resume échoué : {body}"
        assert body.get("mode") == "resume", f"champ mode absent ou inattendu : {body}"
        live = body["game_state"]

        assert live["turn"] == state_at_save["turn"]
        assert live["current_player"] == state_at_save["current_player"]
        assert live["phase"] == state_at_save["phase"]


# ---------------------------------------------------------------------------
# T7 — Authentification
# ---------------------------------------------------------------------------


class TestAuth:
    def test_no_token_returns_401(self, api_disk_only_isolated):
        """t7_auth_401 : aucun header Authorization → 401 sans accès à la DB.

        ``_extract_session_token`` lève ``ValueError("Missing Authorization header")`` avant
        tout accès DB ; ``_get_authenticated_user_or_response`` la transforme en 401.
        """
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        assert resp.status_code == 401, (
            f"attendu 401 sans token, obtenu {resp.status_code}"
        )
        body = resp.get_json()
        assert body["success"] is False

    def test_forbidden_mode_returns_403(self, game, monkeypatch):
        """t7_auth_403 : partie PvP en cours + profil sans droit PvP → 403.

        L'invariant RBAC de ``require_authenticated_session`` : si l'engine tourne en mode
        ``pvp`` et que ``_resolve_permissions_for_profile`` ne le retourne pas dans
        ``game_modes``, toute route de jeu doit répondre 403.
        """
        # Vérifier que la partie est bien en mode pvp.
        assert game.state["phase"] in ("move", "shoot", "charge", "fight", "command"), (
            "la partie n'a pas atteint une phase attendue"
        )

        # Restreindre les permissions au seul mode pve — sans pvp.
        monkeypatch.setattr(
            api_server,
            "_resolve_permissions_for_profile",
            lambda _conn, _pid: {"game_modes": ["pve"]},
        )

        resp = game._client.get("/api/game/state")
        assert resp.status_code == 403, (
            f"attendu 403 (profil sans pvp sur partie pvp), obtenu {resp.status_code}"
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "not allowed" in body.get("error", "").lower() or "forbidden" in body.get("error", "").lower() or "403" in str(resp.status_code), (
            f"message d'erreur inattendu : {body.get('error')}"
        )
