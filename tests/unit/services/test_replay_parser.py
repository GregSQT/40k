from pathlib import Path

from services.replay_parser import (
    episode_to_replay_format,
    parse_log_file,
    parse_train_log_to_episodes,
)


def _write_log(tmp_path: Path, content: str) -> str:
    log_path = tmp_path / "train_step.log"
    log_path.write_text(content, encoding="utf-8")
    return str(log_path)


def test_parse_train_log_to_episodes_parses_move_and_shoot_actions(tmp_path: Path) -> None:
    log_content = """
=== EPISODE 1 START ===
Scenario: bot
Unit 1 (Intercessor) P1: Starting position (1, 1)
Unit 2 (Termagant) P2: Starting position (2, 1)
=== ACTIONS START ===
[12:00:00] T1 P1 MOVE : Unit 1(2,1) MOVED from (1,1)
[12:00:01] T1 P1 SHOOT : Unit 1(2, 1) SHOT Unit 2 - Hit 4(3+) - Wound 5(5+) - Save 4(5+) - Dmg:1HP
Episode result: WIN
=== EPISODE END ===
"""
    log_path = _write_log(tmp_path, log_content)

    episodes = parse_train_log_to_episodes(log_path)

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["scenario"] == "bot"
    assert len(episode["actions"]) == 2
    assert episode["actions"][0]["type"] == "move"
    assert episode["actions"][1]["type"] == "shoot"
    assert episode["final_result"] == "win"


def test_parse_train_log_to_episodes_handles_wait_and_loss(tmp_path: Path) -> None:
    log_content = """
=== EPISODE START ===
Scenario: demo
=== ACTIONS START ===
[12:00:00] T1 P1 MOVE : Unit 9(3,3) WAIT
[12:00:01] T1 P1 SHOOT : Unit 9(3, 3) WAIT
Episode result: LOSS
=== EPISODE END ===
"""
    log_path = _write_log(tmp_path, log_content)
    episodes = parse_train_log_to_episodes(log_path)

    assert len(episodes) == 1
    actions = episodes[0]["actions"]
    assert actions[0]["type"] == "move_wait"
    assert actions[1]["type"] == "wait"
    assert episodes[0]["final_result"] == "loss"


def test_parse_train_log_to_episodes_infers_from_position_when_missing(tmp_path: Path) -> None:
    log_content = """
=== EPISODE START ===
=== ACTIONS START ===
[12:00:00] T1 P1 MOVE : Unit 5(4,4) MOVED
Episode result: DRAW
=== EPISODE END ===
"""
    log_path = _write_log(tmp_path, log_content)
    episodes = parse_train_log_to_episodes(log_path)

    move_action = episodes[0]["actions"][0]
    assert move_action["from"] == {"col": 4, "row": 4}
    assert move_action["to"] == {"col": 4, "row": 4}
    assert episodes[0]["final_result"] == "draw"


def test_episode_to_replay_format_builds_states_and_clamps_hp() -> None:
    episode = {
        "episode_num": 3,
        "scenario": "scenario-x",
        "units": {
            1: {"id": 1, "type": "A", "player": 1, "col": 1, "row": 1, "HP_CUR": 2, "HP_MAX": 2},
            2: {"id": 2, "type": "B", "player": 2, "col": 2, "row": 1, "HP_CUR": 1, "HP_MAX": 2},
        },
        "actions": [
            {"type": "move", "unit_id": 1, "to": {"col": 3, "row": 3}},
            {"type": "shoot", "target_id": 2, "damage": 3},
        ],
        "final_result": "win",
    }

    replay = episode_to_replay_format(episode)

    assert replay["episode_num"] == 3
    assert replay["total_actions"] == 2
    assert replay["states"][0]["units"][0]["col"] == 3
    target_state = next(u for u in replay["states"][1]["units"] if u["id"] == 2)
    assert target_state["HP_CUR"] == 0


def test_parse_log_file_returns_episodes_in_replay_format(tmp_path: Path) -> None:
    log_content = """
=== EPISODE START ===
Scenario: alpha
=== ACTIONS START ===
[12:00:00] T1 P1 MOVE : Unit 1(1,1) WAIT
Episode result: WIN
=== EPISODE END ===
"""
    log_path = _write_log(tmp_path, log_content)
    result = parse_log_file(log_path)

    assert result["total_episodes"] == 1
    assert len(result["episodes"]) == 1
    assert result["episodes"][0]["scenario"] == "alpha"
