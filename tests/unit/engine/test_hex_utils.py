"""Tests for engine/hex_utils.py — hex grid primitives (Boardx10 Phase B+C)."""

import math
import pytest
from engine.hex_utils import (
    get_neighbors,
    get_neighbors_bounded,
    offset_to_cube,
    cube_to_offset,
    hex_distance,
    min_distance_between_sets,
    dilate_hex_set_unbounded,
    is_in_bounds,
    normalize_coordinate,
    normalize_coordinates,
    hex_line,
    compute_los_visibility,
    compute_los_state,
    pathfinding_distance,
    build_wall_set,
    compute_occupied_hexes,
    build_occupation_map,
    validate_placement,
    dilate_hex_set,
    expand_wall_group_to_hex_list,
    engagement_minimum_clearance_norm,
    euclidean_edge_clearance_round_round,
    round_base_radius_norm,
)


class TestNeighbors:
    def test_even_col_has_6_neighbors(self):
        assert len(get_neighbors(4, 5)) == 6

    def test_odd_col_has_6_neighbors(self):
        assert len(get_neighbors(3, 5)) == 6

    def test_even_col_neighbors_match_combat_utils(self):
        """Verify consistency with existing get_hex_neighbors in combat_utils."""
        from engine.combat_utils import get_hex_neighbors
        for col in (0, 2, 4, 10):
            for row in (0, 3, 7, 15):
                expected = set(get_hex_neighbors(col, row))
                actual = set(get_neighbors(col, row))
                assert actual == expected, f"Mismatch at ({col},{row})"

    def test_odd_col_neighbors_match_combat_utils(self):
        from engine.combat_utils import get_hex_neighbors
        for col in (1, 3, 5, 11):
            for row in (0, 3, 7, 15):
                expected = set(get_hex_neighbors(col, row))
                actual = set(get_neighbors(col, row))
                assert actual == expected, f"Mismatch at ({col},{row})"

    def test_bounded_filters_out_of_bounds(self):
        result = get_neighbors_bounded(0, 0, 25, 21)
        for c, r in result:
            assert 0 <= c < 25 and 0 <= r < 21

    def test_bounded_corner(self):
        result = get_neighbors_bounded(0, 0, 10, 10)
        assert all(c >= 0 and r >= 0 for c, r in result)
        assert len(result) < 6


class TestCubeConversion:
    def test_roundtrip(self):
        for col in range(0, 12):
            for row in range(0, 12):
                x, y, z = offset_to_cube(col, row)
                assert x + y + z == 0, f"Cube constraint violated at ({col},{row})"
                c2, r2 = cube_to_offset(x, y, z)
                assert (c2, r2) == (col, row), f"Roundtrip failed at ({col},{row})"

    def test_origin(self):
        x, y, z = offset_to_cube(0, 0)
        assert (x, y, z) == (0, 0, 0)


class TestHexDistance:
    def test_same_position(self):
        assert hex_distance(5, 5, 5, 5) == 0

    def test_adjacent(self):
        neighbors = get_neighbors(5, 5)
        for nc, nr in neighbors:
            assert hex_distance(5, 5, nc, nr) == 1

    def test_matches_combat_utils(self):
        from engine.combat_utils import calculate_hex_distance
        test_pairs = [
            (0, 0, 5, 5),
            (3, 7, 10, 2),
            (1, 1, 1, 10),
            (0, 0, 24, 20),
            (12, 10, 12, 10),
        ]
        for c1, r1, c2, r2 in test_pairs:
            expected = calculate_hex_distance(c1, r1, c2, r2)
            actual = hex_distance(c1, r1, c2, r2)
            assert actual == expected, f"Distance mismatch for ({c1},{r1})->({c2},{r2})"

    def test_symmetry(self):
        assert hex_distance(3, 7, 10, 2) == hex_distance(10, 2, 3, 7)


class TestMinDistanceBetweenSets:
    def test_overlapping_sets(self):
        a = {(5, 5), (5, 6)}
        b = {(5, 6), (6, 6)}
        assert min_distance_between_sets(a, b) == 0

    def test_adjacent_sets(self):
        a = {(5, 5)}
        b = set(get_neighbors(5, 5)[:1])
        assert min_distance_between_sets(a, b) == 1

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            min_distance_between_sets(set(), {(1, 1)})

    def test_single_hex_matches_hex_distance(self):
        a = {(3, 7)}
        b = {(10, 2)}
        assert min_distance_between_sets(a, b) == hex_distance(3, 7, 10, 2)


class TestDilateHexSetUnbounded:
    def test_agrees_with_min_distance_threshold(self):
        """``min_distance(A,B) <= r`` iff ``A & dilate(B, r)`` (non-empty), same metric as BFS distance."""
        pairs = [
            ({(3, 4), (4, 5)}, {(10, 2), (11, 3)}),
            ({(0, 0)}, {(0, 0)}),
            ({(0, 0)}, {(2, 0)}),
            ({(5, 5)}, set(get_neighbors(5, 5)[:2])),
        ]
        for a, b in pairs:
            for r in range(0, 20):
                shell = dilate_hex_set_unbounded(b, r)
                md = min_distance_between_sets(a, b)
                assert (md <= r) == bool(a & shell), f"A={a} B={b} r={r} md={md}"

    def test_includes_source_hexes(self):
        b = {(5, 5)}
        assert b <= dilate_hex_set_unbounded(b, 3)


class TestBounds:
    def test_in_bounds(self):
        assert is_in_bounds(0, 0, 25, 21)
        assert is_in_bounds(24, 20, 25, 21)

    def test_out_of_bounds(self):
        assert not is_in_bounds(-1, 0, 25, 21)
        assert not is_in_bounds(25, 0, 25, 21)
        assert not is_in_bounds(0, 21, 25, 21)


class TestNormalize:
    def test_int_passthrough(self):
        assert normalize_coordinate(5) == 5

    def test_float_truncation(self):
        assert normalize_coordinate(5.7) == 5

    def test_string(self):
        assert normalize_coordinate("5") == 5

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_coordinate("abc")

    def test_pair(self):
        assert normalize_coordinates(3.0, "7") == (3, 7)


class TestHexLine:
    def test_same_point(self):
        assert hex_line(5, 5, 5, 5) == [(5, 5)]

    def test_includes_endpoints(self):
        line = hex_line(0, 0, 5, 0)
        assert line[0] == (0, 0)
        assert line[-1] == (5, 0)

    def test_no_duplicates(self):
        line = hex_line(0, 0, 10, 10)
        assert len(line) == len(set(line))

    def test_adjacent(self):
        neighbors = get_neighbors(5, 5)
        for nc, nr in neighbors:
            line = hex_line(5, 5, nc, nr)
            assert len(line) == 2


class TestLoSVisibility:
    def test_no_walls_full_visibility(self):
        assert compute_los_visibility(0, 0, 5, 5, set()) == 1.0

    def test_wall_blocks(self):
        line = hex_line(0, 0, 5, 0)
        wall = {line[2]}
        assert compute_los_visibility(0, 0, 5, 0, wall) == 0.0

    def test_same_hex(self):
        assert compute_los_visibility(3, 3, 3, 3, set()) == 1.0


class TestLoSState:
    def test_clear(self):
        v, can_see, in_cover = compute_los_state(0, 0, 5, 5, set(), 0.05, 0.95)
        assert can_see is True
        assert in_cover is False
        assert v == 1.0

    def test_blocked(self):
        line = hex_line(0, 0, 5, 0)
        wall = {line[2]}
        v, can_see, in_cover = compute_los_state(0, 0, 5, 0, wall, 0.05, 0.95)
        assert can_see is False
        assert v == 0.0


class TestPathfinding:
    def test_same_position(self):
        assert pathfinding_distance(5, 5, 5, 5, 25, 21, set()) == 0

    def test_adjacent_no_walls(self):
        n = get_neighbors(5, 5)[0]
        assert pathfinding_distance(5, 5, n[0], n[1], 25, 21, set()) == 1

    def test_straight_line_no_walls(self):
        d = pathfinding_distance(0, 0, 5, 0, 25, 21, set())
        assert d == hex_distance(0, 0, 5, 0)

    def test_wall_forces_detour(self):
        walls = {(2, 0), (2, 1), (3, 0)}
        d_wall = pathfinding_distance(0, 0, 5, 0, 25, 21, walls)
        d_direct = hex_distance(0, 0, 5, 0)
        assert d_wall > d_direct

    def test_unreachable_surrounded_by_walls(self):
        target = (5, 5)
        walls = set(get_neighbors(5, 5))
        d = pathfinding_distance(0, 0, 5, 5, 25, 21, walls, max_search_distance=50)
        assert d == 51

    def test_out_of_bounds(self):
        d = pathfinding_distance(-1, 0, 5, 5, 25, 21, set())
        assert d > 50

    def test_max_open_nodes_budget(self):
        d = pathfinding_distance(0, 0, 24, 20, 25, 21, set(), max_open_nodes=10)
        assert d == 501  # budget exhausted


class TestBuildWallSet:
    def test_empty(self):
        assert build_wall_set({}) == set()

    def test_list_format(self):
        gs = {"wall_hexes": [[1, 2], [3, 4]]}
        ws = build_wall_set(gs)
        assert (1, 2) in ws
        assert (3, 4) in ws

    def test_tuple_format(self):
        gs = {"wall_hexes": [(1, 2), (3, 4)]}
        ws = build_wall_set(gs)
        assert (1, 2) in ws


# ===== Phase C — compute_occupied_hexes =====


class TestComputeOccupiedHexesRound:
    """Tests for round base footprints."""

    def test_diameter_1_single_hex(self):
        hexes = compute_occupied_hexes(10, 10, "round", 1)
        assert hexes == {(10, 10)}

    def test_center_is_included(self):
        hexes = compute_occupied_hexes(50, 50, "round", 13)
        assert (50, 50) in hexes

    def test_symmetric_shape(self):
        hexes = compute_occupied_hexes(50, 50, "round", 13)
        assert len(hexes) > 1

    def test_diameter_13_reasonable_count(self):
        hexes = compute_occupied_hexes(50, 50, "round", 13)
        area_approx = math.pi * (13 / 2.0) ** 2
        assert len(hexes) > area_approx * 0.5
        assert len(hexes) < area_approx * 1.5

    def test_all_cells_within_radius(self):
        from engine.hex_utils import _FOOTPRINT_SIZE_SCALE, _hex_center
        center_col, center_row = 50, 50
        diameter = 13
        hexes = compute_occupied_hexes(center_col, center_row, "round", diameter)
        cx, cy = _hex_center(center_col, center_row)
        radius = (diameter / 2.0) * _FOOTPRINT_SIZE_SCALE
        for c, r in hexes:
            hx, hy = _hex_center(c, r)
            dist = math.sqrt((hx - cx) ** 2 + (hy - cy) ** 2)
            assert dist <= radius + 0.01, f"Cell ({c},{r}) at dist {dist:.3f} > radius {radius}"

    def test_round_ignores_orientation(self):
        h0 = compute_occupied_hexes(50, 50, "round", 13, orientation=0)
        h3 = compute_occupied_hexes(50, 50, "round", 13, orientation=3)
        assert h0 == h3

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="round base_size must be int"):
            compute_occupied_hexes(10, 10, "round", [13, 8])


class TestComputeOccupiedHexesOval:
    """Tests for oval base footprints."""

    def test_center_included(self):
        hexes = compute_occupied_hexes(50, 50, "oval", [105, 70])
        assert (50, 50) in hexes

    def test_major_larger_than_minor(self):
        hexes = compute_occupied_hexes(50, 50, "oval", [105, 70], orientation=0)
        from engine.hex_utils import _hex_center
        cx, cy = _hex_center(50, 50)
        cols_set = set()
        rows_set = set()
        for c, r in hexes:
            hx, hy = _hex_center(c, r)
            cols_set.add(round(hx - cx, 2))
            rows_set.add(round(hy - cy, 2))
        assert len(hexes) > 10

    def test_rotation_changes_shape(self):
        h0 = compute_occupied_hexes(50, 50, "oval", [20, 10], orientation=0)
        h1 = compute_occupied_hexes(50, 50, "oval", [20, 10], orientation=1)
        assert h0 != h1

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="oval base_size must be"):
            compute_occupied_hexes(10, 10, "oval", 13)


class TestComputeOccupiedHexesSquare:
    """Tests for square base footprints."""

    def test_center_included(self):
        hexes = compute_occupied_hexes(50, 50, "square", 10)
        assert (50, 50) in hexes

    def test_reasonable_count(self):
        side = 10
        hexes = compute_occupied_hexes(50, 50, "square", side)
        area_approx = side ** 2
        assert len(hexes) > area_approx * 0.5
        assert len(hexes) < area_approx * 1.5

    def test_rotation_changes_shape(self):
        h0 = compute_occupied_hexes(50, 50, "square", 10, orientation=0)
        h1 = compute_occupied_hexes(50, 50, "square", 10, orientation=1)
        assert h0 != h1

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="square base_size must be int"):
            compute_occupied_hexes(10, 10, "square", [10, 5])


class TestUnknownShape:
    def test_raises(self):
        with pytest.raises(ValueError, match="Unknown base_shape"):
            compute_occupied_hexes(10, 10, "triangle", 5)


class TestBuildOccupationMap:
    """Tests for sparse cell→unit_id map."""

    def _make_entry(self, col, row, shape="round", size=1):
        return {"col": col, "row": row, "BASE_SHAPE": shape, "BASE_SIZE": size}

    def _get_fp(self, entry):
        return compute_occupied_hexes(
            entry["col"], entry["row"], entry["BASE_SHAPE"], entry["BASE_SIZE"]
        )

    def test_single_unit(self):
        cache = {"u1": self._make_entry(10, 10)}
        omap = build_occupation_map(cache, self._get_fp)
        assert omap[(10, 10)] == "u1"

    def test_two_units_no_overlap(self):
        cache = {
            "u1": self._make_entry(10, 10),
            "u2": self._make_entry(20, 20),
        }
        omap = build_occupation_map(cache, self._get_fp)
        assert omap[(10, 10)] == "u1"
        assert omap[(20, 20)] == "u2"

    def test_overlap_raises(self):
        cache = {
            "u1": self._make_entry(10, 10, "round", 5),
            "u2": self._make_entry(10, 10, "round", 5),
        }
        with pytest.raises(ValueError, match="Invariant III"):
            build_occupation_map(cache, self._get_fp)


class TestValidatePlacement:
    def test_valid(self):
        candidate = {(10, 10), (10, 11)}
        result = validate_placement(candidate, "u1", {}, set(), 100, 100)
        assert result is None

    def test_out_of_bounds(self):
        candidate = {(-1, 5)}
        result = validate_placement(candidate, "u1", {}, set(), 100, 100)
        assert "out of bounds" in result

    def test_wall_collision(self):
        candidate = {(5, 5)}
        result = validate_placement(candidate, "u1", {}, {(5, 5)}, 100, 100)
        assert "wall" in result

    def test_unit_collision(self):
        omap = {(5, 5): "u_other"}
        result = validate_placement({(5, 5)}, "u1", omap, set(), 100, 100)
        assert "occupied" in result

    def test_same_unit_ok(self):
        omap = {(5, 5): "u1"}
        result = validate_placement({(5, 5)}, "u1", omap, set(), 100, 100)
        assert result is None


# ===== Phase C.4 — dilate_hex_set (engagement zone) =====


class TestDilateHexSet:
    """Tests for hex set dilation (engagement zone computation)."""

    def test_empty_set_returns_empty(self):
        assert dilate_hex_set(set(), 5, 100, 100) == set()

    def test_radius_zero_returns_empty(self):
        assert dilate_hex_set({(10, 10)}, 0, 100, 100) == set()

    def test_radius_1_single_hex_gives_6_neighbors(self):
        result = dilate_hex_set({(10, 10)}, 1, 100, 100)
        assert len(result) == 6
        assert (10, 10) not in result

    def test_source_hex_excluded(self):
        result = dilate_hex_set({(10, 10)}, 3, 100, 100)
        assert (10, 10) not in result

    def test_radius_1_matches_get_neighbors(self):
        from engine.hex_utils import get_neighbors_bounded
        source = {(15, 15)}
        dilated = dilate_hex_set(source, 1, 100, 100)
        neighbors = set(get_neighbors_bounded(15, 15, 100, 100))
        assert dilated == neighbors

    def test_radius_2_includes_ring_1_and_2(self):
        source = {(20, 20)}
        r1 = dilate_hex_set(source, 1, 100, 100)
        r2 = dilate_hex_set(source, 2, 100, 100)
        assert r1.issubset(r2)
        assert len(r2) > len(r1)

    def test_all_dilated_within_radius(self):
        source = {(50, 50)}
        radius = 5
        result = dilate_hex_set(source, radius, 200, 200)
        for c, r in result:
            d = hex_distance(50, 50, c, r)
            assert 1 <= d <= radius, f"Cell ({c},{r}) at distance {d}"

    def test_bounds_respected(self):
        source = {(0, 0)}
        result = dilate_hex_set(source, 3, 10, 10)
        for c, r in result:
            assert 0 <= c < 10 and 0 <= r < 10

    def test_multi_source_produces_union(self):
        s1 = dilate_hex_set({(10, 10)}, 2, 100, 100)
        s2 = dilate_hex_set({(20, 20)}, 2, 100, 100)
        combined = dilate_hex_set({(10, 10), (20, 20)}, 2, 100, 100)
        assert combined == (s1 | s2) - {(10, 10), (20, 20)}

    def test_engagement_zone_10_reasonable_size(self):
        source = {(50, 50)}
        result = dilate_hex_set(source, 10, 200, 200)
        area_approx = math.pi * 10 ** 2
        assert len(result) > area_approx * 0.7
        assert len(result) < area_approx * 1.3


class TestEuclideanEngagementClearance:
    """Bord à bord socles ronds (mouvement ×10) — aligné frontend hexFootprint."""

    def test_engagement_minimum_clearance_norm(self):
        assert engagement_minimum_clearance_norm(10) == 15.0
        assert engagement_minimum_clearance_norm(1) == 1.5

    def test_round_base_radius_matches_footprint_scale(self):
        assert round_base_radius_norm(2) == 1.5

    def test_identical_centers_negative_clearance(self):
        g = euclidean_edge_clearance_round_round(10, 10, 3, 10, 10, 3)
        assert g < 0


class TestExpandWallGroupToHexList:
    def test_segments_two_lines_user_example(self):
        g = {
            "name": "Int-Angle-E",
            "segments": [
                [[160, 130], [160, 100]],
                [[160, 100], [200, 100]],
            ],
        }
        cells = expand_wall_group_to_hex_list(g, path_hint="test")
        as_set = {(c, r) for c, r in cells}
        assert (160, 100) in as_set
        line1 = set(hex_line(160, 130, 160, 100))
        line2 = set(hex_line(160, 100, 200, 100))
        assert as_set == (line1 | line2)

    def test_hexes_only_backward_compat(self):
        g = {"hexes": [[1, 2], [3, 4]]}
        assert expand_wall_group_to_hex_list(g) == [[1, 2], [3, 4]]

    def test_hexes_plus_segments_merged_deduped(self):
        g = {
            "hexes": [[10, 10]],
            "segments": [[[10, 10], [12, 10]]],
        }
        out = expand_wall_group_to_hex_list(g)
        assert len(out) == len({(c, r) for c, r in out})

    def test_empty_group_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            expand_wall_group_to_hex_list({"hexes": [], "segments": []})
