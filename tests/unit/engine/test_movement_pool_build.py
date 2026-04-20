"""
Régression : ``movement_build_valid_destinations_pool`` et ``enemy_cache_items`` pour
``_movement_engagement_violates`` (ez > 1) — même résultat qu’un scan complet du cache.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.movement_handlers import (
    _movement_engagement_violates,
    movement_build_valid_destinations_pool,
)
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from shared.data_validation import require_key


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 10},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _make_unit_by_id(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(u["id"]): u for u in units}


def test_movement_engagement_violates_enemy_cache_items_matches_full_scan() -> None:
    """Liste ennemis préfiltrée ≡ filtre inline sur ``units_cache`` (ez > 1)."""
    units = [
        {
            "id": 1,
            "col": 10,
            "row": 10,
            "HP_CUR": 2,
            "player": 0,
            "MOVE": 6,
            "BASE_SIZE": 1,
            "BASE_SHAPE": "round",
        },
        {
            "id": 2,
            "col": 28,
            "row": 10,
            "HP_CUR": 2,
            "player": 1,
            "BASE_SIZE": 1,
            "BASE_SHAPE": "round",
        },
    ]
    game_state: Dict[str, Any] = {
        "config": _board_config(),
        "board_cols": 40,
        "board_rows": 40,
        "current_player": 0,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": _make_unit_by_id(units),
    }
    build_units_cache(game_state)
    units_cache = require_key(game_state, "units_cache")
    mover = require_key(game_state["unit_by_id"], "1")
    candidate_fp = {(10, 10)}

    a = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
    )
    enemy_items = [
        (eid, ce)
        for eid, ce in units_cache.items()
        if str(eid) != "1" and int(require_key(ce, "player")) != 0
    ]
    b = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
        enemy_cache_items=enemy_items,
    )
    assert a == b

    # Cas « violation » : rapprocher l’ennemi pour forcer un échec d’écart (même résultat des deux côtés).
    units[1]["col"] = 12
    units[1]["row"] = 10
    game_state["units"] = units
    game_state["unit_by_id"] = _make_unit_by_id(units)
    build_units_cache(game_state)
    units_cache = require_key(game_state, "units_cache")
    mover = require_key(game_state["unit_by_id"], "1")

    a2 = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
    )
    enemy_items2 = [
        (eid, ce)
        for eid, ce in units_cache.items()
        if str(eid) != "1" and int(require_key(ce, "player")) != 0
    ]
    b2 = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
        enemy_cache_items=enemy_items2,
    )
    assert a2 == b2
    assert a2 is True


def test_movement_build_valid_destinations_pool_deterministic() -> None:
    """Deux appels identiques → mêmes ancres et même zone d’empreinte."""
    units = [
        {
            "id": 1,
            "col": 5,
            "row": 5,
            "HP_CUR": 2,
            "player": 0,
            "MOVE": 4,
            "BASE_SIZE": 1,
            "BASE_SHAPE": "round",
        },
        {
            "id": 2,
            "col": 12,
            "row": 5,
            "HP_CUR": 2,
            "player": 1,
            "BASE_SIZE": 1,
            "BASE_SHAPE": "round",
        },
    ]
    game_state: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 1},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 20,
        "board_rows": 20,
        "current_player": 0,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": _make_unit_by_id(units),
    }
    build_units_cache(game_state)
    build_enemy_adjacent_hexes(game_state, 0)
    assert "enemy_adjacent_hexes_player_0" in game_state

    pool1 = movement_build_valid_destinations_pool(game_state, "1")
    fz1 = set(game_state["move_preview_footprint_zone"])

    pool2 = movement_build_valid_destinations_pool(game_state, "1")
    fz2 = set(game_state["move_preview_footprint_zone"])

    assert sorted(pool1) == sorted(pool2)
    assert fz1 == fz2
    assert (5, 5) in fz1 or (5, 5) in game_state.get("move_preview_footprint_zone", set())
    assert len(pool1) >= 1
