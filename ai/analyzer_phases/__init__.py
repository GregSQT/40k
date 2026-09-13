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


def died_in_own_activation(
    unit_id: str,
    turn: int,
    phase: str,
    deadly_demise_deaths: Dict[str, Tuple[int, str, int]],
    last_attack_line_by_actor: Dict[str, int],
) -> bool:
    """True si la mort de ``unit_id`` appartient à l'activation dont on lit une ligne d'attaque.

    Le moteur écrit les ``DEAD`` PENDANT l'allocation et les lignes d'attaque APRÈS
    (`_finalize_manual_allocation`) : une unité qui détruit un porteur de Deadly Demise (24.08) et
    meurt de l'explosion voit son ``DEAD … reason=hazard`` PRÉCÉDER ses propres lignes FOUGHT/SHOT,
    alors que ses attaques sont résolues avant (« First, any unresolved attacks made by the
    attacking unit are resolved. Then … Deadly Demise »). C'est la SEULE cause de mort de l'unité
    qui agit avant ses lignes : l'Exhortation frappe l'ennemi, [HAZARDOUS] se jette après les
    attaques et sa ligne suit les leurs.

    Deux conditions, toutes deux nécessaires :
      1. la cause est NOMMÉE Deadly Demise, même tour et même phase — un ``hazard`` sans ligne
         ``DEADLY DEMISE`` (jet [HAZARDOUS] d'une activation précédente) ne passe pas ;
      2. aucune ligne d'attaque d'une AUTRE unité entre le DEAD et la ligne lue — sinon l'explosion
         a eu lieu pendant l'activation d'une tierce unité, et ce combattant est un vrai cadavre.
    Journal antérieur à la ligne ``DEADLY DEMISE`` : aucune cause n'est connue, la faute est
    comptée telle quelle — le journal ne porte pas l'information, on ne l'invente pas.
    """
    death = deadly_demise_deaths.get(unit_id)
    if death is None or death[:2] != (turn, phase):
        return False
    last_foreign_attack_line = max(
        (ln for actor, ln in last_attack_line_by_actor.items() if actor != unit_id), default=0
    )
    return death[2] > last_foreign_attack_line
