from engine.phase_handlers.generic_handlers import end_activation


def test_end_activation_wait_adds_wait_log_with_position() -> None:
    unit = {"id": "u1"}
    game_state = {
        "turn": 3,
        "phase": "MOVEMENT",
        "action_log_seq": 0,
        "units_cache": {
            "u1": {"col": 7, "row": 9, "HP_CUR": 5, "player": 1},
        },
    }

    end_activation(game_state, unit, "WAIT", 0, "MOVE", "NOT_REMOVED", 0)

    assert len(game_state["action_logs"]) == 1
    wait_log = game_state["action_logs"][0]
    assert wait_log["type"] == "wait"
    assert wait_log["turn"] == 3
    assert wait_log["phase"] == "MOVEMENT"
    assert wait_log["unitId"] == "u1"
    assert wait_log["col"] == 7
    assert wait_log["row"] == 9
    assert "(7, 9) WAIT" in wait_log["message"]
    assert wait_log["logSeq"] == 1


def test_end_activation_arg2_increments_episode_steps() -> None:
    unit = {"id": "u2"}
    game_state = {"phase": "MOVEMENT"}

    response = end_activation(game_state, unit, "NO", 1, "MOVE", "NOT_REMOVED", 0)

    assert game_state["episode_steps"] == 1
    assert response["step_incremented"] is True


def test_end_activation_arg3_fled_marks_units_moved_and_units_fled() -> None:
    unit = {"id": 42}
    game_state = {"phase": "MOVEMENT"}

    end_activation(game_state, unit, "NO", 0, "FLED", "NOT_REMOVED", 0)

    assert "42" in game_state["units_moved"]
    assert "42" in game_state["units_fled"]


def test_end_activation_removes_unit_from_move_pool_and_marks_phase_complete() -> None:
    unit = {"id": "u3"}
    game_state = {
        "phase": "MOVEMENT",
        "move_activation_pool": ["u3"],
    }

    response = end_activation(game_state, unit, "NO", 0, "MOVE", "MOVE", 0)

    assert game_state["move_activation_pool"] == []
    assert response["removed_from_move_pool"] is True
    assert response["phase_complete"] is True


def test_end_activation_arg5_logs_error_entry() -> None:
    unit = {"id": "u4"}
    game_state = {"phase": "SHOOTING"}

    response = end_activation(game_state, unit, "NO", 0, "SHOOTING", "NOT_REMOVED", 1)

    assert response["error_logged"] is True
    assert len(game_state["error_logs"]) == 1
    assert game_state["error_logs"][0]["unitId"] == "u4"
    assert game_state["error_logs"][0]["phase"] == "SHOOTING"


def test_end_activation_shooting_clears_target_selection_state() -> None:
    unit = {
        "id": "u5",
        "selected_target_id": "enemy-1",
        "valid_target_pool": ["enemy-1", "enemy-2"],
    }
    game_state = {
        "phase": "SHOOTING",
        "shoot_activation_pool": ["u5"],
    }

    response = end_activation(game_state, unit, "NO", 0, "SHOOTING", "SHOOTING", 0)

    assert response["clear_target_selection"] is True
    assert response["clear_target_blinking"] is True
    assert unit["selected_target_id"] is None
    assert unit["valid_target_pool"] == []
