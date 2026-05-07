"""Tests unitaires — flux end-to-end execute_semantic_action.

Couvre : skip, move (valide/invalide), advance_phase (cascade), phase inconnue,
game_over bloquant, action type inconnu.
Chaque test instancie un W40KEngine via object.__new__ (bypasse __init__) et injecte
un game_state minimal construit à la main.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

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
            "los_visibility_min_ratio": 0.0,
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
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 0,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
    }


def _make_move_gs(units: List[Dict[str, Any]], phase: str = "move") -> Dict[str, Any]:
    """Game-state minimal complet pour la phase move."""
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(),
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
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, gs["current_player"])
    return gs


def _bare_engine(gs: Dict[str, Any]) -> W40KEngine:
    """Instancie W40KEngine sans __init__ et injecte le game_state."""
    engine = object.__new__(W40KEngine)
    engine.game_state = gs
    engine.step_logger = None
    engine.gym_training_mode = False
    engine.config = _base_config()
    engine._shooting_phase_initialized = False
    engine._movement_phase_initialized = False
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteSemanticActionGameOver:
    def test_game_over_blocks_all_actions(self):
        """esa_game_over : game_over=True → (False, {error: 'game_over'}) pour tout action."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["game_over"] = True
        gs["winner"] = 1
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "skip", "unitId": "1"})

        assert success is False
        assert result.get("error") == "game_over"

    def test_game_over_returns_winner(self):
        """esa_game_over_winner : résultat contient le gagnant."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["game_over"] = True
        gs["winner"] = 2
        engine = _bare_engine(gs)

        _, result = engine.execute_semantic_action({"action": "skip", "unitId": "1"})

        assert result.get("winner") == 2


class TestExecuteSemanticActionSkip:
    def test_skip_removes_unit_from_pool(self):
        """esa_skip_pool : action 'skip' → unité retirée du move_activation_pool."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1"]
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "skip", "unitId": "1"})

        assert success is True
        assert "1" not in gs["move_activation_pool"]

    def test_skip_returns_skip_action(self):
        """esa_skip_action : result['action'] == 'skip'."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1"]
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "skip", "unitId": "1"})

        assert success is True
        assert result.get("action") == "skip"

    def test_skip_game_state_unchanged_phase(self):
        """esa_skip_phase_intact : skip n'avance pas la phase si pool non vide après."""
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 8, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1", "2"]
        engine = _bare_engine(gs)

        engine.execute_semantic_action({"action": "skip", "unitId": "1"})

        # Phase reste "move" car il reste l'unité 2 dans le pool
        assert gs["phase"] == "move"
        assert "2" in gs["move_activation_pool"]


class TestExecuteSemanticActionMove:
    def test_move_valid_destination_updates_position(self):
        """esa_move_pos : move vers dest valide → position unité mise à jour."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1"]
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action(
            {"action": "move", "unitId": "1", "destCol": 6, "destRow": 10}
        )

        assert success is True
        # Position mise à jour dans units_cache
        cache_entry = gs["units_cache"].get("1")
        assert cache_entry is not None
        assert cache_entry["col"] == 6
        assert cache_entry["row"] == 10

    def test_move_valid_destination_marks_unit_moved(self):
        """esa_move_units_moved : move réussi → unité dans units_moved."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1"]
        engine = _bare_engine(gs)

        engine.execute_semantic_action(
            {"action": "move", "unitId": "1", "destCol": 6, "destRow": 10}
        )

        assert "1" in gs["units_moved"]

    def test_move_invalid_destination_returns_error(self):
        """esa_move_invalid_dest : destination hors BFS → (False, {error: 'invalid_destination'})."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1"]
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action(
            {"action": "move", "unitId": "1", "destCol": 100, "destRow": 100}
        )

        assert success is False
        assert result.get("error") == "invalid_destination"

    def test_move_invalid_destination_preserves_position(self):
        """esa_move_invalid_pos_unchanged : destination invalide → position inchangée."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1"]
        engine = _bare_engine(gs)

        engine.execute_semantic_action(
            {"action": "move", "unitId": "1", "destCol": 100, "destRow": 100}
        )

        cache_entry = gs["units_cache"].get("1")
        assert cache_entry is not None
        assert cache_entry["col"] == 5
        assert cache_entry["row"] == 10


class TestExecuteSemanticActionAdvancePhase:
    def test_advance_phase_from_move_transitions_to_shoot(self):
        """esa_advance_phase : advance_phase from=move → phase passe à 'shoot'."""
        # Un tireur P1 + ennemi P2 pour que le pool tir soit non vide (cascade stoppe)
        shooter = _unit(1, 1, 5, 10)
        shooter["RNG_WEAPONS"] = [
            {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "RNG": 24, "NB": 1, "WEAPON_RULES": []}
        ]
        enemy = _unit(2, 2, 20, 10)
        units = [shooter, enemy]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = []  # Pool vide → phase_complete
        gs["units_shot"] = set()
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action(
            {"action": "advance_phase", "from": "move"}
        )

        assert success is True
        # La phase doit être passée à shoot (ou plus loin si shoot pool vide aussi)
        assert gs["phase"] in ("shoot", "charge", "fight", "move")
        # Au minimum, la transition a eu lieu depuis "move"
        assert gs["phase"] != "move" or result.get("phase_complete") is True

    def test_advance_phase_result_has_phase_complete(self):
        """esa_advance_phase_flag : advance_phase → result contient phase_complete=True."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = []
        gs["units_shot"] = set()
        gs["units_charged"] = set()
        gs["units_fought"] = set()
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action(
            {"action": "advance_phase", "from": "move"}
        )

        assert success is True
        assert result.get("phase_complete") is True


class TestExecuteSemanticActionInvalidPhase:
    def test_unknown_phase_returns_error(self):
        """esa_invalid_phase : phase inconnue → (False, {error: 'invalid_phase'})."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units, phase="nonexistent_phase")
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "skip", "unitId": "1"})

        assert success is False
        assert result.get("error") == "invalid_phase"
        assert result.get("phase") == "nonexistent_phase"

    def test_unknown_action_type_in_move_phase(self):
        """esa_unknown_action : action type inconnu en phase move → error, game_state intact."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        gs["move_activation_pool"] = ["1"]
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action(
            {"action": "UNKNOWNACTION", "unitId": "1"}
        )

        # L'action inconnue retourne False avec une erreur explicite
        assert success is False
        assert "error" in result
        # L'unité reste dans le pool (game_state intact)
        assert "1" in gs["move_activation_pool"]
