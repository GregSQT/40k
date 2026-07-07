from typing import Any, Dict, cast

import pytest

from engine.phase_handlers.shared_utils import (
    build_units_cache,
    get_unit_position,
    require_unit_position,
    update_units_cache_position,
    update_units_cache_unit,
)


def test_build_units_cache_normalizes_coordinates_hp_and_player() -> None:
    game_state: Dict[str, Any] = {
        "units": [
            {
                "id": 1,
                "col": "3.0",
                "row": 4.0,
                "HP_CUR": "2",
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
                "UNIT_RULES": [],
                "player": "1",
                "BASE_SHAPE": "round",
                "BASE_SIZE": 1,
                "MODEL_HEIGHT": 2.5,
            }
        ],
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
    }

    build_units_cache(game_state)

    entry = game_state["units_cache"]["1"]
    assert entry["col"] == 3
    assert entry["row"] == 4
    assert entry["HP_CUR"] == 2
    assert entry["player"] == 1
    assert entry["BASE_SHAPE"] == "round"
    assert entry["BASE_SIZE"] == 1
    assert entry["occupied_hexes"] == {(3, 4)}
    assert game_state["occupation_map"][(3, 4)] == "1"


def test_build_units_cache_raises_value_error_on_invalid_player() -> None:
    game_state = {
        "units": [
            {
                "id": "u1",
                "col": 1,
                "row": 1,
                "HP_CUR": 2,
                "player": "invalid",
            }
        ]
    }

    with pytest.raises(ValueError, match=r"invalid player"):
        build_units_cache(game_state)


def test_get_unit_position_supports_dict_and_int_inputs() -> None:
    game_state = {"units_cache": {"7": {"col": 10, "row": 11, "HP_CUR": 5, "player": 1}}}

    assert get_unit_position({"id": 7}, game_state) == (10, 11)
    assert get_unit_position(7, game_state) == (10, 11)


def test_get_unit_position_raises_when_dict_without_id() -> None:
    game_state = {"units_cache": {}}

    with pytest.raises(ValueError, match=r"dict without 'id'"):
        get_unit_position({"col": 1, "row": 2}, game_state)


def test_require_unit_position_raises_when_unit_absent_from_cache() -> None:
    game_state = {"units_cache": {}}

    with pytest.raises(ValueError, match=r"dead or absent"):
        require_unit_position("missing", game_state)


def test_update_units_cache_position_updates_existing_entry_with_normalization() -> None:
    game_state = {
        "units_cache": {
            "u1": {"col": 1, "row": 2, "HP_CUR": 3, "player": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5},
        },
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "_unit_move_version": 0,
    }

    update_units_cache_position(game_state, "u1", cast(int, "6.0"), cast(int, 8.0))

    assert game_state["units_cache"]["u1"]["col"] == 6
    assert game_state["units_cache"]["u1"]["row"] == 8
    assert game_state["units_cache"]["u1"]["HP_CUR"] == 3
    assert game_state["units_cache"]["u1"]["player"] == 1


def test_update_units_cache_position_is_noop_when_unit_absent() -> None:
    game_state = {"units_cache": {}}

    update_units_cache_position(game_state, "missing", 4, 5)

    assert game_state["units_cache"] == {}


def test_update_units_cache_unit_updates_existing_entry() -> None:
    game_state = {"units_cache": {
        "u9": {"col": 1, "row": 1, "HP_CUR": 10, "player": 2, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5},
    }, "config": {
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }}

    update_units_cache_unit(game_state, "u9", cast(int, "2"), cast(int, "3.0"), 4, 2)

    entry = game_state["units_cache"]["u9"]
    assert entry["col"] == 2
    assert entry["row"] == 3
    assert entry["HP_CUR"] == 4
    assert entry["player"] == 2
    assert entry["BASE_SHAPE"] == "round"
    assert entry["BASE_SIZE"] == 1
    assert entry["occupied_hexes"] == {(2, 3)}


def test_update_units_cache_unit_raises_when_cache_missing() -> None:
    game_state = {}

    with pytest.raises(KeyError, match=r"units_cache must exist before updating"):
        update_units_cache_unit(game_state, "u1", 1, 1, 1, 1)
