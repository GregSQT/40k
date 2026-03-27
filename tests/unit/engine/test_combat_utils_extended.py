import pytest

from engine.combat_utils import (
    calculate_hex_distance,
    calculate_pathfinding_distance,
    calculate_wound_target,
    check_los_cached,
    expected_dice_value,
    get_hex_neighbors,
    get_unit_by_id,
    is_hex_adjacent_to_enemy,
    normalize_coordinate,
    normalize_coordinates,
    resolve_dice_value,
    set_unit_coordinates,
)


def test_resolve_dice_value_returns_int_unchanged() -> None:
    assert resolve_dice_value(4, "ctx") == 4


def test_resolve_dice_value_raises_on_unsupported_expression() -> None:
    with pytest.raises(ValueError, match=r"Unsupported dice expression"):
        resolve_dice_value("D8", "ctx")


def test_resolve_dice_value_rolls_2d6(monkeypatch: pytest.MonkeyPatch) -> None:
    rolls = iter([2, 5])
    monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
    assert resolve_dice_value("2D6", "ctx") == 7


def test_expected_dice_value_known_mappings_and_invalid() -> None:
    assert expected_dice_value("D3", "ctx") == 2.0
    assert expected_dice_value("D6+3", "ctx") == 6.5
    assert expected_dice_value(9, "ctx") == 9.0
    with pytest.raises(ValueError, match=r"Unsupported dice expression"):
        expected_dice_value("3D6", "ctx")


def test_get_unit_by_id_requires_index_and_handles_string_lookup() -> None:
    game_state = {"unit_by_id": {"12": {"id": 12}}}
    assert get_unit_by_id(game_state, 12) == {"id": 12}
    with pytest.raises(Exception):
        get_unit_by_id({}, "12")


def test_is_hex_adjacent_to_enemy_normalizes_and_checks_membership() -> None:
    enemy_adjacent_hexes = {(3, 4)}
    assert is_hex_adjacent_to_enemy("3.0", 4.0, 1, enemy_adjacent_hexes) is True
    assert is_hex_adjacent_to_enemy(1, 1, 1, enemy_adjacent_hexes) is False


def test_get_hex_neighbors_even_and_odd_columns() -> None:
    even_neighbors = get_hex_neighbors(2, 3)
    odd_neighbors = get_hex_neighbors(3, 3)
    assert len(even_neighbors) == 6
    assert len(odd_neighbors) == 6
    assert (3, 2) in even_neighbors  # even NE
    assert (4, 3) in odd_neighbors   # odd NE


def test_normalize_coordinate_and_coordinates_error_paths() -> None:
    assert normalize_coordinate("5.0") == 5
    assert normalize_coordinates("7", 8.0) == (7, 8)
    with pytest.raises(TypeError, match=r"Invalid coordinate type"):
        normalize_coordinate({"x": 1})
    with pytest.raises(ValueError, match=r"Invalid coordinate string"):
        normalize_coordinate("abc")


def test_set_unit_coordinates_updates_unit_with_normalized_values() -> None:
    unit = {"id": "u1", "col": 0, "row": 0}
    set_unit_coordinates(unit, "6.0", 9.0)
    assert unit["col"] == 6
    assert unit["row"] == 9


def test_calculate_hex_distance_basic_cases() -> None:
    assert calculate_hex_distance(0, 0, 0, 0) == 0
    assert calculate_hex_distance(0, 0, 1, 0) == 1
    assert calculate_hex_distance(0, 0, 2, 0) >= 1


def test_calculate_pathfinding_distance_uses_cache_and_walls() -> None:
    game_state = {"wall_hexes": {(1, 0)}, "board_cols": 4, "board_rows": 4}
    first = calculate_pathfinding_distance(0, 0, 2, 0, game_state, max_search_distance=10)
    assert first > 0
    assert "pathfinding_distance_cache" in game_state
    second = calculate_pathfinding_distance(0, 0, 2, 0, game_state, max_search_distance=10)
    assert second == first


def test_calculate_pathfinding_distance_returns_unreachable_when_blocked() -> None:
    # Block all neighbors around start (0,0) for odd-q neighborhood.
    game_state = {
        "wall_hexes": {(0, 1), (1, 0), (-1, 0), (-1, -1), (1, -1), (0, -1)},
        "board_cols": 3,
        "board_rows": 3,
    }
    unreachable = calculate_pathfinding_distance(0, 0, 2, 2, game_state, max_search_distance=3)
    assert unreachable == 4


def test_check_los_cached_returns_float_and_validates_inputs() -> None:
    shooter = {"id": "s1", "los_cache": {"t1": True}}
    target = {"id": "t1"}
    assert check_los_cached(shooter, target, {}) == 1.0

    with pytest.raises(KeyError, match=r"Target missing required 'id'"):
        check_los_cached(shooter, {}, {})
    with pytest.raises(ValueError, match=r"los_cache missing for shooter"):
        check_los_cached({"id": "s2"}, target, {})


def test_calculate_wound_target_w40k_thresholds() -> None:
    assert calculate_wound_target(8, 4) == 2
    assert calculate_wound_target(5, 4) == 3
    assert calculate_wound_target(4, 4) == 4
    assert calculate_wound_target(2, 5) == 6
    assert calculate_wound_target(3, 5) == 5
