import pytest

from shared.gameLogStructure import (
    BaseLogEntry,
    TrainingLogEntry,
    convert_legacy_event,
    create_log_entry,
    create_training_log_entry,
    get_event_icon,
    get_event_type_class,
    log_unified_action,
)


def test_base_log_entry_to_dict_includes_optional_fields_when_set() -> None:
    entry = BaseLogEntry(
        entry_type="shoot",
        message="msg",
        turn_number=2,
        phase="shooting",
        unit_type="Intercessor",
        unit_id=1,
    )

    as_dict = entry.to_dict()

    assert as_dict["type"] == "shoot"
    assert as_dict["message"] == "msg"
    assert as_dict["turnNumber"] == 2
    assert as_dict["phase"] == "shooting"
    assert as_dict["unitType"] == "Intercessor"
    assert as_dict["unitId"] == 1


def test_training_log_entry_to_dict_contains_training_fields() -> None:
    entry = TrainingLogEntry(
        entry_type="move",
        message="moved",
        reward=1.5,
        action_name="move",
        timestamp="2026-01-01T00:00:00",
        entry_id="entry-1",
    )

    as_dict = entry.to_dict()

    assert as_dict["reward"] == 1.5
    assert as_dict["actionName"] == "move"
    assert as_dict["timestamp"] == "2026-01-01T00:00:00"
    assert as_dict["id"] == "entry-1"


def test_create_log_entry_shoot_generates_expected_message() -> None:
    entry = create_log_entry(
        entry_type="shoot",
        acting_unit={"id": 1, "unit_type": "Intercessor", "player": 0},
        target_unit={"id": 2, "unit_type": "Termagant"},
        turn_number=1,
        phase="shoot",
    )

    assert entry.message == "Unit 1 SHOT Unit 2"
    assert entry.type == "shoot"


def test_create_log_entry_move_rejects_invalid_hex_format() -> None:
    with pytest.raises(ValueError, match=r"Invalid hex format"):
        create_log_entry(
            entry_type="move",
            acting_unit={"id": 1, "unit_type": "Intercessor", "player": 0},
            start_hex="(1,2)",
            end_hex="(2, 2)",
        )


def test_create_log_entry_turn_change_requires_valid_turn_number() -> None:
    with pytest.raises(ValueError, match=r"turn_number is required"):
        create_log_entry(entry_type="turn_change", turn_number=0)


def test_create_log_entry_phase_change_requires_phase() -> None:
    with pytest.raises(ValueError, match=r"phase is required"):
        create_log_entry(entry_type="phase_change", acting_unit={"player": 0})


def test_create_log_entry_training_skip_when_not_evaluation_mode() -> None:
    class DummyReplayLogger:
        is_evaluation_mode = False

    class DummyEnv:
        replay_logger = DummyReplayLogger()
        is_evaluation_mode = False
        _force_evaluation_mode = False

    entry = create_log_entry(
        entry_type="shoot",
        acting_unit={"id": 1},
        target_unit={"id": 2},
        env=DummyEnv(),
    )

    assert entry.message == "training_skipped"


def test_create_training_log_entry_wraps_base_entry() -> None:
    entry = create_training_log_entry(
        entry_type="combat",
        acting_unit={"id": 1, "unit_type": "Intercessor", "player": 0},
        target_unit={"id": 2, "unit_type": "Hormagaunt"},
        reward=2.0,
        action_name="combat",
    )

    assert entry.type == "combat"
    assert entry.message == "Unit 1 FOUGHT Unit 2"
    assert entry.reward == 2.0
    assert entry.actionName == "combat"


def test_convert_legacy_event_maps_core_fields() -> None:
    legacy = {"type": "shoot", "message": "m", "turnNumber": 3, "unitId": 9}
    entry = convert_legacy_event(legacy)
    as_dict = entry.to_dict()
    assert as_dict["type"] == "shoot"
    assert as_dict["turnNumber"] == 3
    assert as_dict["unitId"] == 9


def test_get_event_icon_and_type_class_cover_supported_branches() -> None:
    assert get_event_icon("shoot") == "🎯"
    assert get_event_type_class({"type": "shoot", "message": "Saved!"}) == "game-log-entry--shoot-saved"
    assert get_event_type_class({"type": "shoot", "message": "HP -1"}) == "game-log-entry--shoot-damage"
    assert get_event_type_class({"type": "move", "message": "x"}) == "game-log-entry--move"


def test_get_event_icon_raises_on_unsupported_type() -> None:
    with pytest.raises(ValueError, match=r"Unsupported event_type"):
        get_event_icon("unknown")


def test_log_unified_action_calls_replay_logger_add_entry() -> None:
    class DummyReplayLogger:
        def __init__(self) -> None:
            self.calls = []

        def add_entry(self, **kwargs) -> None:
            self.calls.append(kwargs)

    class DummyEnv:
        def __init__(self) -> None:
            self.replay_logger = DummyReplayLogger()

    env = DummyEnv()
    acting = {"id": 1, "col": 1, "row": 1, "unit_type": "Intercessor", "player": 0}
    target = {"id": 2, "col": 2, "row": 2, "unit_type": "Termagant", "player": 1}

    log_unified_action(
        env=env,
        action_type="shoot",
        acting_unit=acting,
        target_unit=target,
        reward=0.5,
        phase="shoot",
        turn_number=1,
    )

    assert len(env.replay_logger.calls) == 1
    assert env.replay_logger.calls[0]["entry_type"] == "shoot"


def test_log_unified_action_rejects_unknown_action_type() -> None:
    class DummyReplayLogger:
        pass

    class DummyEnv:
        replay_logger = DummyReplayLogger()

    with pytest.raises(ValueError, match=r"Unknown action_type"):
        log_unified_action(
            env=DummyEnv(),
            action_type="invalid",
            acting_unit={"id": 1, "col": 1, "row": 1},
            target_unit=None,
            reward=0.0,
            phase="move",
            turn_number=1,
        )
