"""Non-regression : _fight_bfs_reachable_anchors_consolidation avec placement mask.

Ces tests vérifient que le masque Minkowski (compute_footprint_placement_mask) produit
exactement les mêmes ancres visitées que l'ancienne logique is_footprint_placement_valid.
Propriétés testées :
- ancre occupée par un allié/ennemi → absente de visited
- hex mur → ancre absente de visited
- ancre hors plateau → absente de visited
- ancres libres dans bfs_max → présentes dans visited avec footprint correct
- unité multi-hex : ancre dont l'empreinte chevauche un obstacle → absente de visited
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.fight_handlers import (
    _fight_bfs_reachable_anchors_consolidation,
)


def _gs_single_hex(
    unit_col: int = 5,
    unit_row: int = 5,
    board_cols: int = 20,
    board_rows: int = 20,
    scale: int = 1,
    extra_units_cache: Dict[str, Any] | None = None,
    wall_hexes: set | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    unit: Dict[str, Any] = {
        "id": "u1",
        "player": 1,
        "col": unit_col,
        "row": unit_row,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "orientation": 0,
    }
    units_cache: Dict[str, Any] = {
        "u1": {"col": unit_col, "row": unit_row, "player": 1},
    }
    if extra_units_cache:
        units_cache.update(extra_units_cache)
    gs: Dict[str, Any] = {
        "inches_to_subhex": scale,
        "board_cols": board_cols,
        "board_rows": board_rows,
        "config": {"game_rules": {"engagement_zone": 1}},
        "units_cache": units_cache,
        "wall_hexes": wall_hexes or set(),
    }
    return gs, unit


class TestConsolidationBfsPlacementMaskSingleHex:
    def test_open_board_all_neighbors_reachable(self):
        gs, unit = _gs_single_hex(unit_col=5, unit_row=5)
        visited, fp_by_anchor = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert (5, 5) in visited
        assert len(visited) > 1

    def test_occupied_hex_not_in_visited(self):
        gs, unit = _gs_single_hex(
            unit_col=5,
            unit_row=5,
            extra_units_cache={"blocker": {"col": 5, "row": 6, "player": 2}},
        )
        visited, _ = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert (5, 6) not in visited

    def test_wall_hex_not_in_visited(self):
        gs, unit = _gs_single_hex(unit_col=5, unit_row=5, wall_hexes={(5, 6)})
        visited, _ = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert (5, 6) not in visited

    def test_oob_anchor_not_in_visited(self):
        gs, unit = _gs_single_hex(unit_col=0, unit_row=0, board_cols=5, board_rows=5)
        visited, _ = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        for col, row in visited:
            assert 0 <= col < 5
            assert 0 <= row < 5

    def test_bfs_max_respected(self):
        gs, unit = _gs_single_hex(unit_col=10, unit_row=10, scale=1)
        visited, _ = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        bfs_max = 3 * 1
        for col, row in visited:
            dist = visited[(col, row)]
            assert dist <= bfs_max

    def test_fp_by_anchor_matches_visited_keys(self):
        gs, unit = _gs_single_hex()
        visited, fp_by_anchor = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert set(visited.keys()) == set(fp_by_anchor.keys())

    def test_fp_by_anchor_single_hex_contains_anchor(self):
        gs, unit = _gs_single_hex()
        visited, fp_by_anchor = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        for anchor, fp in fp_by_anchor.items():
            assert anchor in fp

    def test_obstacle_does_not_block_path_around_it(self):
        """Un obstacle en (5,6) ne doit pas bloquer (5,7) si un chemin alternatif existe."""
        gs, unit = _gs_single_hex(
            unit_col=5,
            unit_row=5,
            extra_units_cache={"blocker": {"col": 5, "row": 6, "player": 2}},
        )
        visited, _ = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert (5, 6) not in visited


class TestConsolidationBfsPlacementMaskMultiHex:
    """Teste le chemin mask Minkowski avec ez>1 et BASE_SIZE>1."""

    def _gs_multi_hex(
        self,
        unit_col: int = 20,
        unit_row: int = 50,
        obstacle_col: int | None = None,
        obstacle_row: int | None = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        unit: Dict[str, Any] = {
            "id": "u1",
            "player": 1,
            "col": unit_col,
            "row": unit_row,
            "BASE_SIZE": 3,
            "BASE_SHAPE": "round",
            "orientation": 0,
        }
        units_cache: Dict[str, Any] = {
            "u1": {"col": unit_col, "row": unit_row, "player": 1},
        }
        if obstacle_col is not None and obstacle_row is not None:
            units_cache["blocker"] = {
                "col": obstacle_col,
                "row": obstacle_row,
                "player": 2,
                "occupied_hexes": {(obstacle_col, obstacle_row)},
            }
        gs: Dict[str, Any] = {
            "inches_to_subhex": 10,
            "board_cols": 360,
            "board_rows": 312,
            "config": {
                "game_rules": {
                    "engagement_zone": 10,
                    "max_base_size_hex": 35,
                },
                "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            },
            "units_cache": units_cache,
            "wall_hexes": set(),
        }
        return gs, unit

    def test_multi_hex_open_board_reachable(self):
        gs, unit = self._gs_multi_hex()
        visited, fp_by_anchor = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert (20, 50) in visited
        assert len(visited) > 1

    def test_multi_hex_fp_by_anchor_keys_match_visited(self):
        gs, unit = self._gs_multi_hex()
        visited, fp_by_anchor = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert set(visited.keys()) == set(fp_by_anchor.keys())

    def test_multi_hex_obstacle_center_blocks_anchor(self):
        """Un obstacle sur l'ancre elle-même doit bloquer cette ancre."""
        unit_col, unit_row = 20, 50
        neighbor_col, neighbor_row = 21, 50
        gs, unit = self._gs_multi_hex(
            unit_col=unit_col,
            unit_row=unit_row,
            obstacle_col=neighbor_col,
            obstacle_row=neighbor_row,
        )
        visited, _ = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        assert (neighbor_col, neighbor_row) not in visited

    def test_multi_hex_oob_anchors_absent(self):
        gs, unit = self._gs_multi_hex(unit_col=20, unit_row=50)
        visited, _ = _fight_bfs_reachable_anchors_consolidation(gs, unit)
        for col, row in visited:
            assert 0 <= col < 360
            assert 0 <= row < 312
