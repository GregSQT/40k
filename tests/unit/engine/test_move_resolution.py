"""Résolution BFS mouvement — movement_build_valid_destinations_pool."""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache

from _config_helpers import build_move_rules


def _unit(uid: int, player: int, col: int, row: int, move: int = 3, fly: bool = False) -> Dict[str, Any]:
    keywords = [{"keywordId": "fly"}] if fly else []
    return {
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
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "UNIT_KEYWORDS": keywords,
        "UNIT_RULES": [],
    }


def _make_game_state(
    units: List[Dict[str, Any]],
    current_player: int = 1,
    wall_hexes=None,
    engagement_zone: int = 1,
) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": engagement_zone, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": wall_hexes if wall_hexes is not None else set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "move_activation_pool": [],
        "units_moved": set(),
        "units_fled": set(),
        "console_logs": [],
        "gym_training_mode": True,  # skip mask_loops polygon computation
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, current_player)
    return gs


class TestMovementBFSResolution:
    def test_bfs_basic_open_board(self):
        """bfs_basic : plateau vide, MOVE=3 depuis (5,10) → 36 destinations accessibles."""
        units = [_unit(1, 1, 5, 10, move=3)]
        gs = _make_game_state(units)
        result = movement_build_valid_destinations_pool(gs, "1")
        assert len(result) == 36, f"expected 36 destinations, got {len(result)}"
        assert (5, 10) not in result, "start position must not be a destination"

    def test_bfs_wall_blocks_destination(self):
        """bfs_wall : mur en (6,10) → hex exclu et non traversable sur ce côté."""
        walls = {(6, 10)}
        units = [_unit(1, 1, 5, 10, move=3)]
        gs = _make_game_state(units, wall_hexes=walls)
        result = movement_build_valid_destinations_pool(gs, "1")
        assert (6, 10) not in result, "(6,10) is a wall — must not be a destination"
        assert len(result) == 34, f"expected 34 destinations (36 - 2 blocked via wall), got {len(result)}"

    def test_bfs_ally_hex_excluded_as_destination(self):
        """bfs_ally : allié en (6,10) → hex exclu comme destination, BFS traverse pour atteindre au-delà."""
        ally = _unit(2, 1, 6, 10, move=3)  # même joueur
        mover = _unit(1, 1, 5, 10, move=3)
        gs = _make_game_state([mover, ally])
        result = movement_build_valid_destinations_pool(gs, "1")
        assert (6, 10) not in result, "ally-occupied hex must not be a valid destination"
        # BFS may still traverse through ally hex to reach (7,10)
        assert len(result) == 35, f"expected 35 destinations (36 - 1 ally hex), got {len(result)}"

    def test_bfs_enemy_ez_blocks_destination(self):
        """bfs_ez : ennemi en (9,10) avec engagement_zone=1 → voisins de l'ennemi exclus.

        Voisins de (9,10) = [(9,9),(10,9),(10,10),(9,11),(8,11),(8,10)].
        (8,10) et (8,11) sont dans le BFS-3 depuis (5,10) et doivent être exclus.
        """
        enemy = _unit(2, 2, 9, 10)
        mover = _unit(1, 1, 5, 10, move=3)
        gs = _make_game_state([mover, enemy], engagement_zone=1)
        result = movement_build_valid_destinations_pool(gs, "1")
        assert (8, 10) not in result, "(8,10) is adjacent to enemy — must be excluded (EZ)"
        assert (8, 11) not in result, "(8,11) is adjacent to enemy — must be excluded (EZ)"
        # 36 destinations - 2 reachable hexes in enemy EZ = 34
        assert len(result) == 34, f"expected 34 destinations, got {len(result)}"

    def test_fly_unit_traverses_wall_ring(self):
        """bfs_fly : anneau de murs autour de (5,10) — unité FLY l'ignore en traversée, sol bloqué.

        Résultats mesurés : FLY=30 destinations (hexes hors de l'anneau), sol=0.
        """
        wall_ring = {(5, 9), (6, 10), (6, 11), (5, 11), (4, 11), (4, 10)}

        units_fly = [_unit(1, 1, 5, 10, move=3, fly=True)]
        gs_fly = _make_game_state(units_fly, wall_hexes=wall_ring)
        result_fly = movement_build_valid_destinations_pool(gs_fly, "1")

        units_ground = [_unit(2, 1, 5, 10, move=3, fly=False)]
        gs_ground = _make_game_state(units_ground, wall_hexes=wall_ring)
        result_ground = movement_build_valid_destinations_pool(gs_ground, "2")

        assert len(result_fly) > 0, "FLY unit must reach destinations beyond wall ring"
        assert len(result_ground) == 0, "ground unit walled-in must have no valid destinations"
        assert len(result_fly) > len(result_ground), "FLY must reach more hexes than ground"
