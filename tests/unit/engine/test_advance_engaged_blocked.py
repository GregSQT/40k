"""09.03 / 09.06 : une unité engagée ne peut pas avancer (Advance).

Avant le fix, `movement_set_advance_mode_handler` ne vérifiait pas `_squad_is_in_enemy_er`.
Un agent pouvait declarer un Advance alors que l'escouade était dans l'Engagement Range
d'un ennemi → `advance_engage` dans l'analyzer.

Fix : le handler retourne `(False, {"error": "unit_engaged"})` si engagé.
"""
from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.movement_handlers import movement_set_advance_mode_handler
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 2,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
    }


def _unit(uid: int, player: int, col: int, row: int, move: int = 6) -> Dict[str, Any]:
    return {
        **unit_invariants(),
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "MOVE": move,
        "HP_CUR": 2,
        "HP_MAX": 2,
        "VALUE": 50,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": 3,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "UNIT_KEYWORDS": [],
        "UNIT_RULES": [],
    }


def _gs(units: List[Dict[str, Any]], current_player: int = 1) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": _board_config(),
        "board_cols": 50,
        "board_rows": 50,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "move_activation_pool": [],
        "units_moved": set(),
        "units_fled": set(),
        "console_logs": [],
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, current_player)
    return gs


def test_advance_refuse_si_engage():
    """Escouade à 1 hex d'un ennemi (EZ=2) → Advance refusé."""
    units = [
        _unit(1, 1, 10, 10),   # P1 — 0 hex du voisin
        _unit(2, 2, 11, 10),   # P2 — adjacent
    ]
    gs = _gs(units, current_player=1)
    ok, result = movement_set_advance_mode_handler(gs, "1", {})
    assert not ok
    assert result.get("error") == "unit_engaged"


def test_advance_autorise_si_non_engage():
    """Escouade loin de tout ennemi → Advance accordé."""
    units = [
        _unit(1, 1, 10, 10),   # P1
        _unit(2, 2, 40, 40),   # P2 — loin
    ]
    gs = _gs(units, current_player=1)
    ok, result = movement_set_advance_mode_handler(gs, "1", {})
    assert ok
    assert result.get("action") == "advance_mode_set"
