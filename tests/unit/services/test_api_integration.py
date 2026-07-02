"""Tests d'intégration partielle — API Flask avec engine semi-réel.

Distinct de test_api_endpoints.py qui mocke tout.
Ici : engine instancié via object.__new__ avec game_state minimal réel.
execute_semantic_action et _game_state_for_json ne sont PAS mockés.

Couvre :
- POST /api/game/action avec action 'advance_phase' → réponse 200, game_state sérialisable
- GET /api/game/state → champs attendus présents (phase, current_player, turn, units)
- Aucune clé non-sérialisable (set, objet Python) dans la réponse JSON
- Action 'skip' avec unitId → résultat dans la réponse
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

import services.api_server as api_server
from services.api_server import app
from engine.w40k_core import W40KEngine
from engine.phase_handlers.shared_utils import build_units_cache, build_enemy_adjacent_hexes


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "max_base_size_hex": 35,
            "cover_ratio": 0.0,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        "gym_training_mode": False,
        "pve_mode": False,
    }


def _unit(uid: int, player: int, col: int, row: int, hp: int = 3) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": hp,
        "HP_MAX": hp,
        "VALUE": 100,
        "OC": 1,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [
            {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "RNG": 24, "NB": 1, "WEAPON_RULES": []}
        ],
        "CC_WEAPONS": [],
    }


def _make_full_gs(units: List[Dict[str, Any]], phase: str = "move") -> Dict[str, Any]:
    """Game-state complet compatible avec _game_state_for_json."""
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "episode_number": 1,
        "turn_limit_reached": False,
        "game_over": False,
        "winner": None,
        "victory_points": {1: 0, 2: 0},
        "primary_objective": None,
        "primary_objective_scored_turns": set(),
        "objective_rewarded_turns": set(),
        "units_moved": set(),
        "units_advanced": set(),
        "units_fled": set(),
        "units_shot": set(),
        "units_charged": set(),
        "units_fought": set(),
        "units_cannot_charge": set(),
        "units_attacked": set(),
        "units_reacted_this_enemy_turn": set(),
        "reaction_window_active": False,
        "_unit_move_version": 0,
        "last_move_event_id": 0,
        "last_move_cause": "normal",
        "reactive_mode": "micro",
        "reactive_macro_order_current_window": [],
        "reactive_decision_mode": "auto",
        "reactive_decision_payload": {},
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "valid_move_destinations_pool": [],
        "preview_hexes": [],
        "move_preview_footprint_span": None,
        "active_movement_unit": None,
        "fight_subphase": None,
        "hex_los_cache": {},
        "los_cache": {},
        "player_types": {"1": "human", "2": "ai"},
        "gym_training_mode": False,
        "debug_mode": False,
        "objectives": [{"id": "test_obj", "name": "Alpha", "hexes": [[5, 5]]}],
        "tutorial_fight_no_death_unit_ids": None,
        "macro_target_objective_index": 0,
        "macro_target_objective_id": "test_obj",
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, gs["current_player"])
    return gs


def _make_semi_real_engine(units: List[Dict[str, Any]], phase: str = "move") -> W40KEngine:
    """Engine instancié sans __init__, avec game_state minimal réel.
    execute_semantic_action est la vraie méthode (non mockée).
    """
    gs = _make_full_gs(units, phase)
    engine = object.__new__(W40KEngine)
    engine.game_state = gs
    engine.step_logger = None
    engine.gym_training_mode = False
    engine.config = _base_config()
    engine._shooting_phase_initialized = False
    engine._movement_phase_initialized = False
    engine.current_mode_code = "pvp"
    return engine


def _is_json_serializable(obj: Any) -> bool:
    """Vérifie récursivement qu'un objet est JSON-sérialisable."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Fixture : injecte l'engine semi-réel dans api_server
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def semi_real_engine(monkeypatch):
    units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
    engine = _make_semi_real_engine(units)
    monkeypatch.setattr(api_server, "engine", engine)
    return engine


@pytest.fixture
def semi_real_engine_with_pool(monkeypatch):
    """Engine avec une unité dans le move_activation_pool."""
    units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
    engine = _make_semi_real_engine(units)
    engine.game_state["move_activation_pool"] = ["1"]
    monkeypatch.setattr(api_server, "engine", engine)
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/game/state — flux réel engine → JSON
# ─────────────────────────────────────────────────────────────────────────────

class TestGetGameStateIntegration:
    def test_state_endpoint_returns_200(self, semi_real_engine):
        """api_int_state_200 : GET /api/game/state avec engine réel → 200."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        assert resp.status_code == 200

    def test_state_response_has_success_true(self, semi_real_engine):
        """api_int_state_success : réponse contient success=True."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        data = resp.get_json()
        assert data["success"] is True

    def test_state_response_has_game_state(self, semi_real_engine):
        """api_int_state_game_state : réponse contient clé 'game_state'."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        data = resp.get_json()
        assert "game_state" in data
        assert isinstance(data["game_state"], dict)

    def test_state_has_required_fields(self, semi_real_engine):
        """api_int_state_fields : game_state dans réponse contient phase, current_player, turn, units."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        gs = resp.get_json()["game_state"]
        assert "phase" in gs
        assert "current_player" in gs
        assert "turn" in gs
        assert "units" in gs

    def test_state_is_json_serializable(self, semi_real_engine):
        """api_int_state_serializable : aucune clé non-sérialisable dans game_state (set, objet Python)."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        data = resp.get_json()
        # get_json() a déjà sérialisé/désérialisé → si ça passe sans exception, c'est sérialisable
        assert data is not None
        assert _is_json_serializable(data)

    def test_state_wall_hexes_excluded(self, semi_real_engine):
        """api_int_state_no_wall_hexes : wall_hexes (set Python) est exclu de la réponse."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        gs = resp.get_json()["game_state"]
        # wall_hexes est dans _GAME_STATE_EXCLUDE_KEYS → ne doit pas apparaître
        assert "wall_hexes" not in gs

    def test_state_config_excluded(self, semi_real_engine):
        """api_int_state_no_config : config (lourd) est exclu de la réponse."""
        with app.test_client() as client:
            resp = client.get("/api/game/state")
        gs = resp.get_json()["game_state"]
        assert "config" not in gs


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/game/action — flux réel engine → action → JSON
# ─────────────────────────────────────────────────────────────────────────────

class TestPostActionIntegration:
    def test_advance_phase_returns_200(self, semi_real_engine):
        """api_int_action_200 : POST /api/game/action advance_phase → 200."""
        with app.test_client() as client:
            resp = client.post(
                "/api/game/action",
                json={"action": "advance_phase", "from": "move"},
            )
        assert resp.status_code == 200

    def test_advance_phase_response_has_game_state(self, semi_real_engine):
        """api_int_action_gs : réponse POST /action contient game_state."""
        with app.test_client() as client:
            resp = client.post(
                "/api/game/action",
                json={"action": "advance_phase", "from": "move"},
            )
        data = resp.get_json()
        assert "game_state" in data
        assert isinstance(data["game_state"], dict)

    def test_advance_phase_response_is_json_serializable(self, semi_real_engine):
        """api_int_action_serializable : réponse POST /action entièrement JSON-sérialisable."""
        with app.test_client() as client:
            resp = client.post(
                "/api/game/action",
                json={"action": "advance_phase", "from": "move"},
            )
        data = resp.get_json()
        assert data is not None
        assert _is_json_serializable(data)

    def test_skip_action_returns_success_true(self, semi_real_engine_with_pool):
        """api_int_skip_success : action 'skip' avec unitId → success=True dans réponse."""
        with app.test_client() as client:
            resp = client.post(
                "/api/game/action",
                json={"action": "skip", "unitId": "1"},
            )
        data = resp.get_json()
        assert data["success"] is True

    def test_skip_action_has_result_field(self, semi_real_engine_with_pool):
        """api_int_skip_result : réponse POST /action contient clé 'result'."""
        with app.test_client() as client:
            resp = client.post(
                "/api/game/action",
                json={"action": "skip", "unitId": "1"},
            )
        data = resp.get_json()
        assert "result" in data

    def test_action_logs_cleared_after_response(self, semi_real_engine_with_pool):
        """api_int_logs_cleared : action_logs dans engine.game_state vidé après réponse."""
        engine = semi_real_engine_with_pool
        engine.game_state["action_logs"] = [{"type": "test", "id": 99}]

        with app.test_client() as client:
            client.post(
                "/api/game/action",
                json={"action": "skip", "unitId": "1"},
            )
        # L'API vide action_logs après chaque action (voir ligne 2036 api_server.py)
        assert engine.game_state["action_logs"] == []

    def test_game_state_no_set_leaks_after_action(self, semi_real_engine_with_pool):
        """api_int_no_set_leak : aucun set Python ne fuite dans game_state réponse."""
        with app.test_client() as client:
            resp = client.post(
                "/api/game/action",
                json={"action": "skip", "unitId": "1"},
            )
        gs = resp.get_json()["game_state"]

        def _check_no_sets(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _check_no_sets(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _check_no_sets(v, f"{path}[{i}]")
            elif isinstance(obj, set):
                raise AssertionError(f"Set trouvé dans la réponse JSON à {path}: {obj!r}")

        _check_no_sets(gs)
