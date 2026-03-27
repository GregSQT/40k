from ai import hidden_action_finder as haf
import os
import pytest


def test_parse_position_changes_and_attacks_from_debug() -> None:
    movement_log = """
[POSITION CHANGE] E1 T2 move Unit 7: (1,2)→(3,4) via MOVE
[FIGHT DEBUG] E1 T2 fight attack_executed: Unit 7 -> Unit 8 damage=2 target_died=False
[SHOOT DEBUG] E1 T2 shoot attack_executed: Unit 7 -> Unit 9 damage=1 target_died=True
"""
    positions = haf.parse_position_changes(movement_log)
    attacks = haf.parse_attacks_from_debug(movement_log)
    assert len(positions) == 1
    assert positions[0]["from"] == (1, 2)
    assert len(attacks) == 2
    assert {a["phase"] for a in attacks} == {"fight", "shoot"}


def test_parse_episodes_from_step_with_start_markers() -> None:
    step_log = """=== EPISODE 1 START ===
line a
EPISODE END
line between
=== EPISODE 2 START ===
line b
"""
    mapping = haf.parse_episodes_from_step(step_log)
    assert mapping[1] == 1
    assert mapping[4] == 2


def test_get_episode_with_context_defaults_and_fallback() -> None:
    mapping = {10: 3}
    assert haf._get_episode_with_context(10, mapping) == 3
    assert haf._get_episode_with_context(12, mapping) == 3
    assert haf._get_episode_with_context(1, {}) == 1


def test_parse_moves_charges_advances_attacks_from_step() -> None:
    step_log = """
[t] E1 T1 P1 MOVE : Unit 1(1,1) MOVED from (1,1) to (2,1)
[t] E1 T1 P1 MOVE : Unit 2(2,2) FLED from (2,2) to (3,2)
[t] E1 T1 P1 CHARGE : Unit 3(3,3) CHARGED Unit 9(4,4) from (3,3) to (4,3)
[t] E1 T1 P1 SHOOT : Unit 4(4,4) ADVANCED from (4,4) to (5,4)
[t] E1 T1 P1 SHOOT : Unit 4(5,4) SHOT Unit 8(6,4)
[t] E1 T1 P1 FIGHT : Unit 5(5,5) FOUGHT Unit 6(6,5)
"""
    episode_map = {i: 1 for i, _ in enumerate(step_log.split("\n"), 1)}
    moves = haf.parse_moves_from_step(step_log, episode_map)
    charges = haf.parse_charges_from_step(step_log, episode_map)
    advances = haf.parse_advances_from_step(step_log, episode_map)
    attacks = haf.parse_attacks_from_step(step_log, episode_map)

    assert len(moves) == 2
    assert {m["type"] for m in moves} == {"MOVED", "FLED"}
    assert len(charges) == 1
    assert len(advances) == 1
    assert len(attacks) == 2
    assert {a["phase"] for a in attacks} == {"shoot", "fight"}


def test_check_unlogged_moves_groups_intermediate_changes() -> None:
    position_changes = [
        {"episode": 1, "turn": 1, "unit_id": "u1", "phase": "move", "from": (1, 1), "to": (2, 1), "type": "MOVE", "line": "a"},
        {"episode": 1, "turn": 1, "unit_id": "u1", "phase": "move", "from": (2, 1), "to": (3, 1), "type": "MOVE", "line": "b"},
    ]
    step_moves = [{"episode": 1, "turn": 1, "unit_id": "u1", "from": (1, 1), "to": (3, 1)}]
    unlogged = haf.check_unlogged_moves(position_changes, step_moves, [], [])
    assert unlogged == []


def test_check_unlogged_attacks_and_missing_fight_attacks() -> None:
    debug_attacks = [
        {"episode": 1, "turn": 1, "phase": "fight", "attacker": "1", "target": "2", "damage": 1, "target_died": False, "line": "x"}
    ]
    step_attacks = []
    unlogged = haf.check_unlogged_attacks(debug_attacks, step_attacks)
    assert len(unlogged) == 1

    activations = [{"episode": 1, "turn": 1, "unit_id": "1", "valid_targets": ["2"], "count": 1, "line": "a"}]
    missing = haf.check_missing_fight_attacks(activations, step_attacks, movement_log="")
    assert len(missing) == 1


def test_parse_fight_activation_and_warning_logs() -> None:
    log = """
[FIGHT DEBUG] E2 T3 fight unit_activation: Unit 10 valid_targets=['11','12'] count=2
[FIGHT DEBUG] ⚠️ E2 T3 fight end_activation: Unit 10 ADJACENT to enemy but PASSING with ATTACK_LEFT=1
"""
    activations = haf.parse_fight_activations(log)
    warnings = haf.parse_missing_attacks_warnings(log)
    assert len(activations) == 1
    assert activations[0]["valid_targets"] == ["11", "12"]
    assert len(warnings) == 1
    assert warnings[0]["unit_id"] == "10"


def test_parse_episodes_from_step_without_start_markers_and_no_markers() -> None:
    step_with_end_only = "line1\nEPISODE END\nline2\nEPISODE END\nline3"
    mapping_end_only = haf.parse_episodes_from_step(step_with_end_only)
    assert mapping_end_only[1] == 1
    assert mapping_end_only[3] == 2

    mapping_no_markers = haf.parse_episodes_from_step("a\nb\nc")
    assert mapping_no_markers[1] == 1
    assert mapping_no_markers[3] == 1


def test_parse_old_step_log_formats_use_episode_context() -> None:
    step_log = """
[t] T7 P1 MOVE : Unit 1(1,1) MOVED from (1,1) to (2,1)
[t] T7 P1 MOVE : Unit 1(2,1) FLED from (2,1) to (3,1)
[t] T7 P1 CHARGE : Unit 2(2,2) CHARGED Unit 9(4,4) from (2,2) to (3,2)
[t] T7 P1 SHOOT : Unit 3(3,3) ADVANCED from (3,3) to (4,3)
[t] T7 P1 SHOOT : Unit 3(4,3) SHOT [R:1.0] Unit 8(6,4)
[t] T7 P1 FIGHT : Unit 4(5,5) FOUGHT Unit 6(6,5)
"""
    episode_map = {1: 5}
    moves = haf.parse_moves_from_step(step_log, episode_map)
    charges = haf.parse_charges_from_step(step_log, episode_map)
    advances = haf.parse_advances_from_step(step_log, episode_map)
    attacks = haf.parse_attacks_from_step(step_log, episode_map)

    assert len(moves) == 2
    assert all(m["episode"] == 5 for m in moves)
    assert len(charges) == 1 and charges[0]["episode"] == 5
    assert len(advances) == 1 and advances[0]["episode"] == 5
    assert len(attacks) == 2 and all(a["episode"] == 5 for a in attacks)


def test_check_unlogged_attacks_previous_turn_and_deduplication() -> None:
    debug_attacks = [
        {"episode": 1, "turn": 2, "phase": "fight", "attacker": "7", "target": "8", "damage": 2, "target_died": False, "line": "a"},
        {"episode": 1, "turn": 2, "phase": "fight", "attacker": "7", "target": "8", "damage": 2, "target_died": False, "line": "a-dup"},
    ]
    # Logged once on previous turn while debug has two entries -> one remains missing
    step_attacks_prev_turn = [{"episode": 1, "turn": 1, "phase": "fight", "attacker": "7", "target": "8"}]
    partial = haf.check_unlogged_attacks(debug_attacks, step_attacks_prev_turn)
    assert len(partial) == 1
    assert partial[0]["target"] == "8"

    # No matching logged attack -> one unique missing attack despite duplicate debug lines
    unlogged = haf.check_unlogged_attacks(debug_attacks, [])
    assert len(unlogged) == 1
    assert unlogged[0]["attacker"] == "7"


def test_check_missing_fight_attacks_skips_when_target_was_attacked() -> None:
    activations = [{"episode": 3, "turn": 2, "unit_id": "5", "valid_targets": ["9", "10"], "count": 2, "line": "x"}]
    step_attacks = [{"episode": 3, "turn": 2, "phase": "fight", "attacker": "5", "target": "10"}]
    assert haf.check_missing_fight_attacks(activations, step_attacks, movement_log="") == []


def test_main_reports_missing_debug_log(tmp_path, capsys) -> None:
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        haf.main()
        captured = capsys.readouterr()
        assert "hidden_action_finder.py" in captured.out
        output_text = (tmp_path / "hidden_action_finder_output.log").read_text(encoding="utf-8")
        assert "debug.log introuvable" in output_text
    finally:
        os.chdir(cwd)
