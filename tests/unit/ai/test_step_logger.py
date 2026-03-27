from pathlib import Path

import pytest

from ai.step_logger import StepLogger


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_init_requires_buffer_size_when_enabled(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    with pytest.raises(ValueError, match=r"buffer_size is required"):
        StepLogger(output_file=str(output_file), enabled=True, buffer_size=None)


def test_init_writes_header_when_enabled(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    StepLogger(output_file=str(output_file), enabled=True, buffer_size=2)
    content = _read_text(output_file)
    assert "=== STEP-BY-STEP ACTION LOG ===" in content
    assert "AI_TURN.md COMPLIANCE" in content


def test_format_display_name_suffix_handles_empty_and_valid_values() -> None:
    logger = StepLogger(enabled=False)
    assert logger._format_display_name_suffix(None, "name") == ""
    assert logger._format_display_name_suffix({"name": "   "}, "name") == ""
    assert logger._format_display_name_suffix({"name": "Alpha"}, "name") == " [Alpha]"


def test_format_replay_style_message_move_wait_skip_rule_choice() -> None:
    logger = StepLogger(enabled=False)
    move_message = logger._format_replay_style_message(
        1,
        "move",
        {
            "unit_with_coords": "1(4, 5)",
            "start_pos": (1, 1),
            "end_pos": (2, 2),
            "reward": 1.5,
        },
    )
    assert move_message == "Unit 1(4, 5) MOVED from (1,1) to (2,2)[R:+1.5]"
    assert logger._format_replay_style_message(1, "wait", {"unit_with_coords": "1(4, 5)"}) == "Unit 1(4, 5) WAIT"
    assert logger._format_replay_style_message(
        1, "skip", {"unit_with_coords": "1(4, 5)", "skip_reason": "no target"}
    ) == "Unit 1(4, 5) SKIP (no target)"
    assert logger._format_replay_style_message(
        1, "rule_choice", {"unit_with_coords": "1(4, 5)", "selected_rule_name": "sustained hits"}
    ) == "Unit 1(4, 5) chose [SUSTAINED HITS]"


def test_format_replay_style_message_rule_choice_requires_name() -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises(KeyError, match=r"selected_rule_name"):
        logger._format_replay_style_message(1, "rule_choice", {"unit_with_coords": "1(2, 3)"})


def test_log_episode_start_writes_units_and_metadata(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=10)
    units = [
        {
            "id": 1,
            "col": 2,
            "row": 3,
            "player": 1,
            "HP_MAX": 2,
            "unitType": "Intercessor",
            "DISPLAY_NAME": "Alpha",
        }
    ]
    logger.log_episode_start(
        units_data=units,
        scenario_info="demo-scenario",
        bot_name="random",
        walls=[{"col": 7, "row": 8}],
        objectives=[{"id": 1, "hexes": [(4, 4)]}],
        primary_objective_config={"mode": "control"},
        roster_info={
            "agent_roster_id": "A1",
            "opponent_roster_id": "B2",
            "agent_roster_ref": "space_marines",
            "opponent_roster_ref": "tyranids",
            "scale": 2000,
        },
    )
    content = _read_text(output_file)
    assert "=== EPISODE 1 START ===" in content
    assert "Scenario: demo-scenario" in content
    assert "Opponent: RandomBot" in content
    assert "Walls: (7,8)" in content
    assert "Objectives: Obj1:(4,4)" in content
    assert 'Rules: {"primary_objective":{"mode":"control"}}' in content
    assert "Unit 1 (Intercessor) [Alpha] P1: Starting position (2,3), HP_MAX=2" in content
    assert logger.episode_number == 1
    assert logger.episode_step_count == 0
    assert logger.episode_action_count == 0


def test_log_action_increments_counters_and_flushes_on_threshold(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=1)
    logger.log_episode_start(
        units_data=[{"id": 1, "col": 1, "row": 1, "player": 1, "HP_MAX": 1, "unitType": "Intercessor"}]
    )
    logger.log_action(
        unit_id=1,
        action_type="wait",
        phase="move",
        player=1,
        success=True,
        step_increment=True,
        action_details={"current_turn": 2, "unit_with_coords": "1(1, 1)"},
    )
    content = _read_text(output_file)
    assert "E1 T2 P1 MOVE : Unit 1(1, 1) WAIT [SUCCESS]" in content
    assert logger.action_count == 1
    assert logger.step_count == 1
    assert logger.episode_action_count == 1
    assert logger.episode_step_count == 1


def test_log_episode_end_flushes_buffer_and_logs_objective_control(tmp_path: Path) -> None:
    output_file = tmp_path / "step.log"
    logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)
    logger.log_episode_start(
        units_data=[{"id": 1, "col": 1, "row": 1, "player": 1, "HP_MAX": 1, "unitType": "Intercessor"}]
    )
    logger.log_action(
        unit_id=1,
        action_type="wait",
        phase="move",
        player=1,
        success=True,
        step_increment=True,
        action_details={"current_turn": 1, "unit_with_coords": "1(1, 1)"},
    )

    # Buffered line must be flushed by log_episode_end().
    logger.log_episode_end(
        total_episodes_steps=42,
        winner=1,
        win_method="objectives",
        objective_control={1: {"player_1_oc": 3, "player_2_oc": 0, "controller": 1}},
    )
    content = _read_text(output_file)
    assert "E1 T1 P1 MOVE : Unit 1(1, 1) WAIT [SUCCESS]" in content
    assert "EPISODE END: Winner=1, Method=objectives" in content
    assert "OBJECTIVE CONTROL: Obj1:P1_OC=3,P2_OC=0,Ctrl=1" in content


def test_format_replay_style_message_reactive_move_and_validations() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        4,
        "reactive_move",
        {
            "unit_with_coords": "4(5, 6)",
            "start_pos": (5, 6),
            "end_pos": (6, 6),
            "triggered_by_unit_id": 9,
            "trigger_to_pos": (6, 5),
            "range_roll": 4,
            "ability_display_name": "Heroic Intervention",
            "reward": 0.2,
        },
    )
    assert "REACTIVE MOVED [HEROIC INTERVENTION]" in msg
    assert "[R:+0.2]" in msg

    with pytest.raises(ValueError, match=r"range_roll must be int"):
        logger._format_replay_style_message(
            4,
            "reactive_move",
            {
                "unit_with_coords": "4(5, 6)",
                "start_pos": (5, 6),
                "end_pos": (6, 6),
                "triggered_by_unit_id": 9,
                "trigger_to_pos": (6, 5),
                "range_roll": True,
                "ability_display_name": "Heroic Intervention",
            },
        )


def test_format_replay_style_message_charge_fail_and_impact() -> None:
    logger = StepLogger(enabled=False)
    fail_msg = logger._format_replay_style_message(
        2,
        "charge_fail",
        {
            "unit_with_coords": "2(3, 3)",
            "target_id": 7,
            "charge_roll": 5,
            "charge_failed_reason": "distance_too_far",
            "target_coords": (6, 3),
        },
    )
    assert "FAILED CHARGE to unit 7(6,3) [Roll: 5]" in fail_msg

    impact_msg = logger._format_replay_style_message(
        2,
        "charge_impact",
        {
            "unit_with_coords": "2(3, 3)",
            "target_id": 7,
            "impact_roll": 6,
            "impact_threshold": 4,
            "impact_hit_result": "HIT",
            "mortal_wounds": 2,
            "ability_display_name": "Hammer of Wrath",
            "target_coords": (6, 3),
            "reward": 1.0,
        },
    )
    assert "IMPACTED [HAMMER OF WRATH]" in impact_msg
    assert "Dmg:2HP" in impact_msg
    assert "[R:+1.0]" in impact_msg


def test_format_replay_style_message_combat_requires_replay_contract_fields() -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises(KeyError, match=r"fight_subphase"):
        logger._format_replay_style_message(
            3,
            "combat",
            {
                "unit_with_coords": "3(4, 4)",
                "target_id": 8,
                "hit_roll": 5,
                "wound_roll": 4,
                "save_roll": 2,
                "damage_dealt": 1,
                "hit_result": "HIT",
                "wound_result": "WOUND",
                "save_result": "FAIL",
                "hit_target": 3,
                "wound_target": 4,
                "save_target": 3,
                "charging_activation_pool": [],
                "active_alternating_activation_pool": [],
                "non_active_alternating_activation_pool": [],
            },
        )


def test_unknown_action_type_raises_and_phase_transition_logs(tmp_path: Path) -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises(ValueError, match=r"Unknown action_type"):
        logger._format_replay_style_message(1, "unknown_action", {})

    output_file = tmp_path / "step.log"
    enabled_logger = StepLogger(output_file=str(output_file), enabled=True, buffer_size=2)
    enabled_logger.log_phase_transition("move", "shoot", player=1, turn_number=3)
    content = _read_text(output_file)
    assert "T3 P1 SHOOT phase Start" in content
