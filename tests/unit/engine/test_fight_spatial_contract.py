"""Tests for fight spatial A/B contracts documented in Distance_functions.md."""

from engine.phase_handlers.fight_handlers import (
    _fight_build_valid_target_pool,
    _fight_enemy_footprint_distances,
    _fight_footprint_has_enemy_hex_contact,
    _fight_fp_has_adjacent_enemy_footprint,
    _is_adjacent_to_enemy_within_cc_range,
)
from engine.spatial_relations import (
    enemy_footprint_distances,
    unit_within_engagement_zone_footprints,
)


def _unit(unit_id: str = "u1") -> dict:
    return {"id": unit_id, "player": 1}


def test_fight_a_contact_helper_uses_hex_contact_only() -> None:
    unit = _unit()
    game_state = {
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}},
            "enemy_contact": {"col": 0, "row": 1, "player": 2, "occupied_hexes": {(0, 1)}},
            "enemy_far": {"col": 0, "row": 3, "player": 2, "occupied_hexes": {(0, 3)}},
            "ally_contact": {"col": 1, "row": 0, "player": 1, "occupied_hexes": {(1, 0)}},
        }
    }

    assert _fight_footprint_has_enemy_hex_contact(game_state, unit, {(0, 0)}) is True
    assert _fight_fp_has_adjacent_enemy_footprint(game_state, unit, {(0, 0)}) is True


def test_fight_a_contact_helper_does_not_treat_engagement_range_as_contact() -> None:
    unit = _unit()
    game_state = {
        "config": {"game_rules": {"engagement_zone": 2}},
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}},
            "enemy_in_engagement": {"col": 0, "row": 2, "player": 2, "occupied_hexes": {(0, 2)}},
        },
    }

    assert _fight_footprint_has_enemy_hex_contact(game_state, unit, {(0, 0)}) is False


def test_fight_b_engagement_pool_uses_full_footprint_distance() -> None:
    unit = _unit()
    game_state = {
        "config": {"game_rules": {"engagement_zone": 2}},
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "enemy_in_engagement": {"col": 0, "row": 2, "player": 2, "occupied_hexes": {(0, 2)}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "enemy_out_of_engagement": {"col": 0, "row": 3, "player": 2, "occupied_hexes": {(0, 3)}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "ally": {"col": 0, "row": 1, "player": 1, "occupied_hexes": {(0, 1)}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
    }

    distances = dict(_fight_enemy_footprint_distances(game_state, unit))

    assert distances == {"enemy_in_engagement": 2, "enemy_out_of_engagement": 3}
    assert _fight_build_valid_target_pool(game_state, unit) == ["enemy_in_engagement"]
    assert _is_adjacent_to_enemy_within_cc_range(game_state, unit) is True


def test_shared_b_engagement_helper_supports_full_and_bounded_distance() -> None:
    unit = _unit()
    game_state = {
        "config": {"game_rules": {"engagement_zone": 2}},
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "enemy_in_engagement": {"col": 0, "row": 2, "player": 2, "occupied_hexes": {(0, 2)}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "enemy_out_of_engagement": {"col": 0, "row": 3, "player": 2, "occupied_hexes": {(0, 3)}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
    }

    full_distances = dict(enemy_footprint_distances(game_state, unit, max_distance=None))
    bounded_distances = dict(enemy_footprint_distances(game_state, unit, max_distance=2))

    assert full_distances == {"enemy_in_engagement": 2, "enemy_out_of_engagement": 3}
    assert bounded_distances == {"enemy_in_engagement": 2, "enemy_out_of_engagement": 3}
    assert unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=2, max_distance=2
    ) is True
