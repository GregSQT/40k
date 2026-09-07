from typing import Dict, Optional, Tuple

from shared.data_validation import require_key

PHASE_ORDER: dict[str, int] = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}


def claim_kill_context(
    unit_kill_context: Dict[str, Tuple[Optional[str], int, str]],
    target_id: str,
    actor_id: Optional[str],
    turn: int,
    phase: str,
) -> bool:
    """Retourne True si actor_id est le tueur de la même activation que target_id.

    Gère l'artefact DEAD-before-SHOT/FOUGHT : `unit_kill_context` est écrit avec actor=None
    quand la ligne DEAD est vue (avant la ligne d'attaque qui l'a causée). La première ligne
    d'attaque correspondante revendique la mort et met à jour le contexte.
    """
    ctx = unit_kill_context.get(target_id)
    if ctx is not None and ctx[0] is None and ctx[1] == turn and ctx[2] == phase:
        unit_kill_context[target_id] = (actor_id, turn, phase)
        return True
    return ctx == (actor_id, turn, phase)


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
