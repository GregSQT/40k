from shared.data_validation import require_key

PHASE_ORDER: dict[str, int] = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}


def died_before_phase(
    unit_id: str,
    turn: int,
    phase: str,
    current_line: int,
    unit_deaths: list[tuple[int, str, str, int]],
) -> bool:
    """Returns True if unit_id died before (turn, phase, current_line) in PHASE_ORDER ordering."""
    current_phase_order = require_key(PHASE_ORDER, phase)
    for death_turn, death_phase, dead_unit_id, death_line_num in unit_deaths:
        if dead_unit_id == unit_id:
            if death_turn < turn:
                return True
            if death_turn == turn:
                death_phase_order = require_key(PHASE_ORDER, death_phase)
                if death_phase_order < current_phase_order:
                    return True
                if death_phase_order == current_phase_order and death_line_num < current_line:
                    return True
    return False
