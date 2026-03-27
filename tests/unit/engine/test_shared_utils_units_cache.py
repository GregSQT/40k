from engine.phase_handlers.shared_utils import get_hp_from_cache, update_units_cache_hp


def test_update_units_cache_hp_updates_entry_when_hp_positive() -> None:
    game_state = {
        "units_cache": {
            "u1": {"HP_CUR": 5, "col": 1, "row": 2, "player": 1},
        }
    }

    update_units_cache_hp(game_state, "u1", 3)

    assert game_state["units_cache"]["u1"]["HP_CUR"] == 3


def test_update_units_cache_hp_removes_unit_when_hp_zero_or_less() -> None:
    game_state = {
        "board_cols": 20,
        "board_rows": 20,
        "enemy_adjacent_counts_player_1": {},
        "enemy_adjacent_hexes_player_1": set(),
        "units_cache": {
            "u1": {"HP_CUR": 5, "col": 1, "row": 2, "player": 1},
        }
    }

    update_units_cache_hp(game_state, "u1", 0)

    assert "u1" not in game_state["units_cache"]


def test_get_hp_from_cache_returns_none_when_unit_absent() -> None:
    game_state = {"units_cache": {}}
    assert get_hp_from_cache("missing", game_state) is None
