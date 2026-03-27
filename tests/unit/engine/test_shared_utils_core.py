import pytest

from engine.phase_handlers.shared_utils import (
    build_units_cache,
    get_unit_position,
    require_unit_position,
    update_units_cache_position,
    update_units_cache_unit,
)


def test_build_units_cache_normalizes_coordinates_hp_and_player() -> None:
    game_state = {
        "units": [
            {
                "id": 1,
                "col": "3.0",
                "row": 4.0,
                "HP_CUR": "2",
                "player": "1",
            }
        ]
    }

    build_units_cache(game_state)

    assert game_state["units_cache"]["1"] == {
        "col": 3,
        "row": 4,
        "HP_CUR": 2,
        "player": 1,
    }


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
            "u1": {"col": 1, "row": 2, "HP_CUR": 3, "player": 1},
        }
    }

    update_units_cache_position(game_state, "u1", "6.0", 8.0)

    assert game_state["units_cache"]["u1"]["col"] == 6
    assert game_state["units_cache"]["u1"]["row"] == 8
    assert game_state["units_cache"]["u1"]["HP_CUR"] == 3
    assert game_state["units_cache"]["u1"]["player"] == 1


def test_update_units_cache_position_is_noop_when_unit_absent() -> None:
    game_state = {"units_cache": {}}

    update_units_cache_position(game_state, "missing", 4, 5)

    assert game_state["units_cache"] == {}


def test_update_units_cache_unit_inserts_entry_when_hp_positive() -> None:
    game_state = {"units_cache": {}}

    update_units_cache_unit(game_state, "u9", "2", "3.0", 4, 2)

    assert game_state["units_cache"]["u9"] == {
        "col": 2,
        "row": 3,
        "HP_CUR": 4,
        "player": 2,
    }


def test_update_units_cache_unit_raises_when_cache_missing() -> None:
    game_state = {}

    with pytest.raises(KeyError, match=r"units_cache must exist before updating"):
        update_units_cache_unit(game_state, "u1", 1, 1, 1, 1)
