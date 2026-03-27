from types import SimpleNamespace

import pytest
import json

import ai.game_replay_logger as grl
from ai.game_replay_logger import GameReplayIntegration, GameReplayLogger


def _env_stub() -> SimpleNamespace:
    controller = SimpleNamespace(
        game_state={"current_turn": 1, "phase": "move", "current_player": 0},
        get_units=lambda: [],
    )
    return SimpleNamespace(
        quiet=True,
        is_evaluation_mode=True,
        _force_evaluation_mode=False,
        controller=controller,
        board_size=[20, 20],
    )


def test_get_board_size_from_env_validates_shape_and_values() -> None:
    env = _env_stub()
    logger = GameReplayLogger(env)
    assert logger._get_board_size_from_env() == [20, 20]

    env.board_size = [20]
    with pytest.raises(ValueError, match=r"Environment board_size must be"):
        logger._get_board_size_from_env()

    env.board_size = [20, -1]
    with pytest.raises(ValueError, match=r"positive integers"):
        logger._get_board_size_from_env()


def test_determine_winner_cases() -> None:
    env = _env_stub()
    logger = GameReplayLogger(env)

    env.controller.get_units = lambda: [
        {"player": 0, "alive": True, "CUR_HP": 2},
        {"player": 1, "alive": False, "CUR_HP": 0},
    ]
    assert logger._determine_winner() == 0

    env.controller.get_units = lambda: [
        {"player": 0, "alive": False, "CUR_HP": 0},
        {"player": 1, "alive": True, "CUR_HP": 1},
    ]
    assert logger._determine_winner() == 1

    env.controller.get_units = lambda: [
        {"player": 0, "alive": False, "CUR_HP": 0},
        {"player": 1, "alive": False, "CUR_HP": 0},
    ]
    assert logger._determine_winner() == "draw"

    env.controller.get_units = lambda: [
        {"player": 0, "alive": True, "CUR_HP": 1},
        {"player": 1, "alive": True, "CUR_HP": 1},
    ]
    assert logger._determine_winner() is None


def test_clear_resets_runtime_state() -> None:
    env = _env_stub()
    logger = GameReplayLogger(env)
    logger.combat_log_entries = [{"id": 1}]
    logger.game_states = [{"turn": 1}]
    logger.next_event_id = 99
    logger.initial_game_state = {"units": []}
    logger.clear()
    assert logger.combat_log_entries == []
    assert logger.game_states == []
    assert logger.next_event_id == 1
    assert not hasattr(logger, "initial_game_state")


def test_add_entry_appends_with_incremental_id(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env_stub()
    logger = GameReplayLogger(env)

    class DummyEntry:
        def to_dict(self):
            return {"type": "move"}

    monkeypatch.setattr(grl, "create_training_log_entry", lambda **kwargs: DummyEntry())
    monkeypatch.setattr(logger, "_capture_game_state_snapshot", lambda: logger.game_states.append({"snap": 1}))

    out1 = logger.add_entry("move", acting_unit={"id": 1})
    out2 = logger.add_entry("wait", acting_unit={"id": 1})
    assert out1["id"] == 1
    assert out2["id"] == 2
    assert len(logger.combat_log_entries) == 2
    assert len(logger.game_states) == 2


def test_game_replay_integration_save_episode_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    env = SimpleNamespace(
        replay_logger=SimpleNamespace(save_replay=lambda filename, reward: filename)
    )
    out = GameReplayIntegration.save_episode_replay(env, 1.23, output_dir="/tmp", is_best=True)
    assert out.endswith("train_best_game_replay.json")

    env2 = SimpleNamespace()
    assert GameReplayIntegration.save_episode_replay(env2, 1.0) is None


def test_capture_game_state_snapshot_success_and_missing_fields() -> None:
    env = _env_stub()
    env.controller.get_units = lambda: [
        {"id": 1, "unit_type": "Intercessor", "player": 0, "col": 1, "row": 1, "CUR_HP": 2, "HP_MAX": 2, "alive": True}
    ]
    logger = GameReplayLogger(env)
    logger._capture_game_state_snapshot()
    assert len(logger.game_states) == 1
    assert logger.game_states[0]["units"][0]["id"] == 1

    env.controller.get_units = lambda: [{"id": 1, "unit_type": "Intercessor", "player": 0, "col": 1, "row": 1}]
    with pytest.raises(ValueError, match=r"CUR_HP"):
        logger._capture_game_state_snapshot()


def test_log_action_routes_and_unknown_action_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env_stub()
    logger = GameReplayLogger(env)
    pre = [{"id": 1, "unit_type": "Intercessor", "player": 0, "col": 1, "row": 1, "alive": True}]
    post = [{"id": 1, "unit_type": "Intercessor", "player": 0, "col": 2, "row": 1, "alive": True}]

    called = {"move": 0}
    monkeypatch.setattr(
        logger,
        "log_move",
        lambda *args, **kwargs: called.__setitem__("move", called["move"] + 1),
    )
    logger.log_action(
        action=0,
        reward=0.1,
        pre_action_units=pre,
        post_action_units=post,
        acting_unit_id=1,
    )
    assert called["move"] == 1

    with pytest.raises(ValueError, match=r"Unknown action type"):
        logger.log_action(
            action="unknown_action",
            reward=0.0,
            pre_action_units=pre,
            post_action_units=post,
            acting_unit_id=1,
        )


def test_convert_shoot_details_happy_path_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env_stub()
    logger = GameReplayLogger(env)
    monkeypatch.setattr("engine.combat_utils.calculate_wound_target", lambda s, t: 4)
    monkeypatch.setattr("engine.phase_handlers.shooting_handlers._calculate_save_target", lambda target, ap: 5)

    shooter = {"RNG_ATK": 3, "RNG_STR": 4, "RNG_AP": -1}
    target = {"T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 5}
    details = logger._convert_shoot_details(
        {
            "shots": [
                {
                    "hit_roll": 4,
                    "wound_roll": 5,
                    "hit": True,
                    "wound": True,
                    "hit_target": 3,
                    "save_roll": 2,
                    "save_success": False,
                    "damage": 1,
                    "save_target": 5,
                    "wound_target": 4,
                }
            ]
        },
        shooter=shooter,
        target=target,
    )
    assert details[0]["shotNumber"] == 1
    assert details[0]["hitResult"] == "HIT"

    with pytest.raises(ValueError, match=r"RNG_ATK"):
        logger._convert_shoot_details({"shots": []}, shooter={"RNG_STR": 4, "RNG_AP": -1}, target=target)
    assert logger._convert_shoot_details({}, shooter=shooter, target=target) is None
    with pytest.raises(ValueError, match=r"summary"):
        logger._convert_shoot_details({"unexpected": 1}, shooter=shooter, target=target)


def test_capture_initial_state_and_save_replay(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env_stub()
    env.config = SimpleNamespace(
        initial_units=[
            {
                "id": 1,
                "unit_type": "Intercessor",
                "player": 0,
                "col": 1,
                "row": 1,
                "CUR_HP": 2,
                "HP_MAX": 2,
                "MOVE": 6,
                "RNG_RNG": 24,
                "RNG_DMG": 1,
                "CC_DMG": 1,
                "CC_RNG": 1,
            }
        ]
    )
    logger = GameReplayLogger(env)
    logger.capture_initial_state()
    assert "units" in logger.initial_game_state

    # Force deterministic save path behavior
    monkeypatch.setattr(logger, "_capture_game_state_snapshot", lambda: None)
    monkeypatch.setattr(logger, "_determine_winner", lambda: 0)
    out_file = tmp_path / "replay.json"
    logger.save_replay(str(out_file), episode_reward=1.23)
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["metadata"]["episode_reward"] == 1.23
    assert saved["initial_state"]["units"][0]["id"] == 1
