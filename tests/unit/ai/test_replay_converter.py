import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai import replay_converter


def test_extract_scenario_name_for_replay_prioritizes_stored_template_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay_converter.extract_scenario_name_for_replay, "_current_template_name", "my-template", raising=False)
    assert replay_converter.extract_scenario_name_for_replay() == "my-template"


def test_extract_scenario_name_for_replay_falls_back_to_detected_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    if hasattr(replay_converter.extract_scenario_name_for_replay, "_current_template_name"):
        delattr(replay_converter.extract_scenario_name_for_replay, "_current_template_name")
    monkeypatch.setattr(replay_converter.convert_to_replay_format, "_detected_template_name", "detected-template", raising=False)
    assert replay_converter.extract_scenario_name_for_replay() == "detected-template"
    setattr(replay_converter.convert_to_replay_format, "_detected_template_name", None)
    assert replay_converter.extract_scenario_name_for_replay() == "scenario"


def test_parse_action_message_handles_move_shoot_combat_charge_wait() -> None:
    ctx = {"turn": 1, "phase": "move", "player": 1, "timestamp": "t"}

    move = replay_converter.parse_action_message(
        "Unit 1(1, 1) MOVED from (1, 1) to (2, 1)", ctx
    )
    assert move["type"] == "move"
    assert move["startHex"] == "(1, 1)"
    assert move["endHex"] == "(2, 1)"

    shoot = replay_converter.parse_action_message("Unit 1(1, 1) SHOT Unit 2", ctx)
    assert shoot["type"] == "shoot"
    assert shoot["targetUnitId"] == 2

    combat = replay_converter.parse_action_message("Unit 3(3, 3) FOUGHT Unit 4", ctx)
    assert combat["type"] == "combat"

    charge = replay_converter.parse_action_message("Unit 5(4, 4) CHARGED Unit 6", ctx)
    assert charge["type"] == "charge"

    wait = replay_converter.parse_action_message("Unit 7(6, 6) WAIT", ctx)
    assert wait["type"] == "wait"

    assert replay_converter.parse_action_message("unknown message", ctx) is None


def test_calculate_episode_reward_from_actions_bounds_efficiency_bonus() -> None:
    actions = [{"type": "move"}] * 200
    reward = replay_converter.calculate_episode_reward_from_actions(actions, winner=0)
    assert reward == 5.0  # 10 + max(-5, ...)
    assert replay_converter.calculate_episode_reward_from_actions([], winner=None) == 0.0


def test_parse_steplog_file_parses_actions_and_phase_changes(tmp_path: Path) -> None:
    steplog = tmp_path / "step.log"
    steplog.write_text(
        "\n".join(
            [
                "header line",
                "[12:00:00] T1 P1 MOVE : Unit 1(1, 1) MOVED from (1, 1) to (2, 1) [SUCCESS] [STEP: YES]",
                "[12:00:01] T1 P1 SHOOT : Unit 1(2, 1) SHOT Unit 2 [SUCCESS] [STEP: YES]",
                "[12:00:02] T1 P1 MOVE phase Start",
            ]
        ),
        encoding="utf-8",
    )
    parsed = replay_converter.parse_steplog_file(str(steplog))
    assert parsed["max_turn"] == 1
    assert len(parsed["actions"]) >= 2
    assert any(a.get("type") == "phase_change" for a in parsed["actions"])


def test_convert_to_replay_format_builds_initial_state_from_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(
        json.dumps(
            {
                "units": [
                    {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 1, "row": 1},
                    {"id": 2, "unit_type": "Termagant", "player": 2, "col": 2, "row": 1},
                ]
            }
        ),
        encoding="utf-8",
    )

    class DummyRegistry:
        def get_unit_data(self, unit_type):
            if unit_type == "Intercessor":
                return {"HP_MAX": 2, "MOVE": 6}
            return {"HP_MAX": 1, "MOVE": 6}

    class DummyConfig:
        config_dir = str(tmp_path)

        @staticmethod
        def get_board_size():
            return (20, 20)

    monkeypatch.setattr("ai.unit_registry.UnitRegistry", DummyRegistry)
    monkeypatch.setattr("ai.replay_converter.get_config_loader", lambda: DummyConfig())
    monkeypatch.setattr(replay_converter.convert_to_replay_format, "_scenario_file", str(scenario_file), raising=False)

    steplog_data = {
        "actions": [{"type": "move", "unitId": 1}],
        "max_turn": 3,
        "units_positions": {1: {"col": 3, "row": 3}, 2: {"col": 2, "row": 1}},
    }

    replay = replay_converter.convert_to_replay_format(steplog_data)
    assert replay["game_info"]["total_turns"] == 3
    assert replay["initial_state"]["board_size"] == [20, 20]
    assert len(replay["initial_state"]["units"]) == 2
    assert replay["episode_steps"] == 1


def test_convert_to_replay_format_raises_when_units_positions_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class DummyRegistry:
        def get_unit_data(self, unit_type):
            _ = unit_type
            return {"HP_MAX": 2}

    class DummyConfig:
        config_dir = str(tmp_path)

        @staticmethod
        def get_board_size():
            return (10, 10)

    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps({"units": []}), encoding="utf-8")
    monkeypatch.setattr("ai.unit_registry.UnitRegistry", DummyRegistry)
    monkeypatch.setattr("ai.replay_converter.get_config_loader", lambda: DummyConfig())
    monkeypatch.setattr(replay_converter.convert_to_replay_format, "_scenario_file", str(scenario_file), raising=False)

    with pytest.raises(ValueError, match=r"No unit position data found"):
        replay_converter.convert_to_replay_format({"actions": [], "max_turn": 1, "units_positions": {}})


def test_convert_steplog_to_replay_raises_when_input_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"Steplog file not found"):
        replay_converter.convert_steplog_to_replay(str(tmp_path / "missing.log"))


def test_convert_steplog_to_replay_writes_output_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    steplog = tmp_path / "step.log"
    steplog.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(replay_converter, "parse_steplog_file", lambda p: {"actions": [], "max_turn": 1, "units_positions": {1: {"col": 1, "row": 1}}})
    monkeypatch.setattr(
        replay_converter,
        "convert_to_replay_format",
        lambda data: {"combat_log": [], "game_states": [], "game_info": {"total_turns": 1}},
    )
    monkeypatch.setattr(replay_converter, "extract_scenario_name_for_replay", lambda: "unit-test")
    monkeypatch.chdir(tmp_path)
    assert replay_converter.convert_steplog_to_replay(str(steplog)) is True
    out_file = tmp_path / "ai" / "event_log" / "replay_unit-test.json"
    assert out_file.exists()


def test_generate_steplog_and_replay_returns_false_without_agent() -> None:
    args = SimpleNamespace(
        agent=None,
        training_config="default",
        rewards_config="CoreAgent",
        model=None,
        test_episodes=1,
    )
    assert replay_converter.generate_steplog_and_replay(config=SimpleNamespace(), args=args) is False


def test_generate_steplog_and_replay_returns_false_when_model_missing(tmp_path: Path) -> None:
    class _Cfg:
        def load_agent_training_config(self, agent, training_config):
            _ = agent, training_config
            return {"step_log_buffer_size": 1, "max_turns_per_episode": 2}

        def get_models_root(self):
            return str(tmp_path / "models")

    args = SimpleNamespace(
        agent="CoreAgent",
        training_config="default",
        rewards_config="CoreAgent",
        model=None,
        test_episodes=1,
    )
    assert replay_converter.generate_steplog_and_replay(config=_Cfg(), args=args) is False
