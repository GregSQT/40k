from shared.gameLogUtils import (
    format_charge_cancel_message,
    format_charge_message,
    format_combat_message,
    format_death_message,
    format_move_cancel_message,
    format_move_message,
    format_no_move_message,
    format_phase_change_message,
    format_shooting_message,
    format_turn_start_message,
)


def test_format_shooting_message_matches_expected_short_format() -> None:
    assert format_shooting_message(1, 11) == "Unit 1 SHOT Unit 11"


def test_format_move_message_includes_start_and_end_hex() -> None:
    assert format_move_message(3, 1, 2, 3, 4) == "Unit 3 MOVED from (1, 2) to (3, 4)"


def test_format_no_move_message() -> None:
    assert format_no_move_message(7) == "Unit 7 NO MOVE"


def test_format_combat_message_matches_expected_short_format() -> None:
    assert format_combat_message(2, 9) == "Unit 2 FOUGHT Unit 9"


def test_format_charge_message_contains_names_ids_and_positions() -> None:
    expected = "Unit Intercessor 4 CHARGED Unit Hormagaunt 8 from (5, 6) to (6, 6)"
    assert format_charge_message("Intercessor", 4, "Hormagaunt", 8, 5, 6, 6, 6) == expected


def test_format_death_message() -> None:
    assert format_death_message(10, "Zoanthrope") == "Unit 10 (Zoanthrope) DIED !"


def test_format_cancel_and_phase_messages() -> None:
    assert format_move_cancel_message("Intercessor", 1) == "Unit Intercessor 1 cancelled its move action"
    assert format_charge_cancel_message("Termagant", 2) == "Unit Termagant 2 cancelled its charge action"
    assert format_turn_start_message(4) == "Start of Turn 4"
    assert format_phase_change_message("Player 1", "shooting") == "Start Player 1's SHOOTING phase"
