"""Endpoints Flask — /api/game/state et /api/game/action avec test_client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import services.api_server as api_server
from services.api_server import app


@pytest.fixture(autouse=True)
def reset_engine(monkeypatch):
    """Réinitialise le moteur global avant chaque test."""
    monkeypatch.setattr(api_server, "engine", None)
    yield
    monkeypatch.setattr(api_server, "engine", None)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/game/state
# ─────────────────────────────────────────────────────────────────────────────

class TestGetGameState:

    def test_no_engine_returns_400(self):
        """state_no_engine : engine=None → 400 avec message d'erreur."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "error" in data

    def test_engine_initialized_returns_200(self, monkeypatch):
        """state_ok : engine initialisé → 200 + success=True + game_state présent."""
        mock_engine = MagicMock()
        mock_engine.game_state = {
            "phase": "move",
            "current_player": 1,
            "turn": 1,
            "units": [],
            "units_cache": {},
        }
        # _game_state_for_json retire quelques clés lourdes — fournir l'essentiel
        monkeypatch.setattr(api_server, "engine", mock_engine)
        # Stubber les fonctions de sérialisation qui accèdent à engine.game_state
        monkeypatch.setattr(api_server, "_game_state_for_json", lambda eng, **kw: {"phase": "move"})
        monkeypatch.setattr(api_server, "_sync_units_hp_from_cache", lambda s, gs: None)
        monkeypatch.setattr(api_server, "_attach_player_types", lambda s, eng: None)

        with app.test_client() as client:
            resp = client.get("/api/game/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "game_state" in data

    def test_response_content_type_json(self, monkeypatch):
        """state_content_type : réponse de type application/json quand engine absent."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        assert "json" in resp.content_type


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/game/action
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteAction:

    def test_no_engine_returns_400(self):
        """action_no_engine : engine=None → 400."""
        with app.test_client() as client:
            resp = client.post("/api/game/action", json={"action": "skip"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_no_json_body_returns_400(self, monkeypatch):
        """action_no_json : corps JSON null → 400 avec message d'erreur."""
        mock_engine = MagicMock()
        mock_engine.game_state = {"units_cache": {}}
        monkeypatch.setattr(api_server, "engine", mock_engine)
        with app.test_client() as client:
            # Envoyer null comme corps JSON → data = None → "No JSON data provided"
            resp = client.post(
                "/api/game/action",
                data=b"null",
                content_type="application/json",
            )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "error" in data

    def test_no_units_cache_returns_400(self, monkeypatch):
        """action_no_cache : engine présent mais units_cache manquant → 400 avec error_code."""
        mock_engine = MagicMock()
        mock_engine.game_state = {}  # pas de units_cache
        monkeypatch.setattr(api_server, "engine", mock_engine)
        with app.test_client() as client:
            resp = client.post("/api/game/action", json={"action": "skip"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("error_code") == "game_not_started_call_start_first"

    def test_valid_action_returns_200(self, monkeypatch):
        """action_valid : engine + units_cache + action valide → 200 + success=True."""
        mock_engine = MagicMock()
        mock_engine.game_state = {"units_cache": {}, "phase": "move"}
        mock_engine.execute_semantic_action.return_value = (True, {"action": "skip"})
        monkeypatch.setattr(api_server, "engine", mock_engine)
        monkeypatch.setattr(api_server, "is_endless_duty_mode", lambda eng: False)
        monkeypatch.setattr(api_server, "_extract_mask_loops_client_hash_from_request_data", lambda d: None)
        monkeypatch.setattr(api_server, "_game_state_for_json", lambda eng, **kw: {"phase": "move"})
        monkeypatch.setattr(api_server, "_sync_units_hp_from_cache", lambda s, gs: None)
        monkeypatch.setattr(api_server, "_attach_player_types", lambda s, eng: None)

        with app.test_client() as client:
            resp = client.post("/api/game/action", json={"action": "skip", "unitId": "1"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/health
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_health_returns_200(self):
        """health_ok : /api/health retourne toujours 200."""
        with app.test_client() as client:
            resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_status_field(self):
        """health_status : champ 'status' == 'healthy'."""
        with app.test_client() as client:
            resp = client.get("/api/health")
        data = resp.get_json()
        assert data["status"] == "healthy"

    def test_health_engine_initialized_false_when_no_engine(self):
        """health_engine_false : engine=None → engine_initialized=False."""
        with app.test_client() as client:
            resp = client.get("/api/health")
        data = resp.get_json()
        assert data["engine_initialized"] is False

    def test_health_engine_initialized_true_when_engine(self, monkeypatch):
        """health_engine_true : engine présent → engine_initialized=True."""
        monkeypatch.setattr(api_server, "engine", MagicMock())
        with app.test_client() as client:
            resp = client.get("/api/health")
        data = resp.get_json()
        assert data["engine_initialized"] is True


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/game/reset
# ─────────────────────────────────────────────────────────────────────────────

class TestResetGame:

    def test_no_engine_returns_400(self):
        """reset_no_engine : engine=None → 400."""
        with app.test_client() as client:
            resp = client.post("/api/game/reset")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_valid_reset_returns_200(self, monkeypatch):
        """reset_ok : engine présent, reset() réussit → 200 + success=True."""
        mock_engine = MagicMock()
        mock_engine.game_state = {"units_cache": {}, "phase": "move"}
        mock_engine.reset.return_value = (None, {})
        monkeypatch.setattr(api_server, "engine", mock_engine)
        monkeypatch.setattr(api_server, "_game_state_for_json", lambda eng, **kw: {"phase": "move"})
        monkeypatch.setattr(api_server, "_sync_units_hp_from_cache", lambda s, gs: None)
        monkeypatch.setattr(api_server, "_attach_player_types", lambda s, eng: None)

        with app.test_client() as client:
            resp = client.post("/api/game/reset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "game_state" in data

    def test_reset_failure_returns_500(self, monkeypatch):
        """reset_fail : reset() lève exception → 500."""
        mock_engine = MagicMock()
        mock_engine.game_state = {"units_cache": {}}
        mock_engine.reset.side_effect = RuntimeError("Reset broke")
        monkeypatch.setattr(api_server, "engine", mock_engine)
        with app.test_client() as client:
            resp = client.post("/api/game/reset")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["success"] is False
        assert "error" in data


# ─────────────────────────────────────────────────────────────────────────────
# GET / (root endpoint)
# ─────────────────────────────────────────────────────────────────────────────

class TestRootEndpoint:

    def test_root_returns_200(self):
        """root_ok : GET / → 200."""
        with app.test_client() as client:
            resp = client.get("/")
        assert resp.status_code == 200

    def test_root_returns_json_with_api_endpoints(self):
        """root_json : GET / → JSON contenant 'api_endpoints' ou 'message'."""
        with app.test_client() as client:
            resp = client.get("/")
        data = resp.get_json()
        assert data is not None
        # La route racine retourne un objet avec des infos sur l'API
        assert isinstance(data, dict)
        assert len(data) > 0
