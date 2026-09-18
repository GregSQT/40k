"""Da Jump (WeirdBoy) — le contrôle `da_jump_invalid` (corpus `PROJ.1.1.da_jump`, bucket §1.1).

Datasheet (Datasheets - Orks p5) : « Da Jump (Psychic, once per turn, per army): In your Movement
phase, you can roll 1 D6 and on a result of: 1: This unit suffers D6 mortal wounds. 2-6: Place this
unit in strategic reserves and it gains Deep Strike until the end of the phase. This unit can then
make an ingress move (Including during the first battle round). »

Grammaire 13 : la ligne « Unit N(c,r) DA JUMP (D6=n) [REPOSITIONED|MISCAST] ». Ce qui est jugé :
  - once per turn, per army : une seconde ligne DA JUMP du même joueur dans le même tour ;
  - la ligne est en phase MOVE ;
  - REPOSITIONED ⇔ D6 ≥ 2, MISCAST ⇔ D6 = 1 ;
  - après REPOSITIONED, l'escouade est HORS TABLE jusqu'à sa ligne d'ingress (DEPLOYED en phase
    MOVE) du MÊME tour : toute action de l'escouade entre les deux, ou aucun ingress avant la fin
    de la phase, est une faute ; à l'ingress, chaque socle du `[MODELS:]` est à PLUS de 8"
    (`inches_to_subhex`) de tout socle ennemi vivant — métrique hex (le run à x1 est hex ; en
    euclidien le contrôle s'abstient, la clearance moteur y est bord de socle, non reconstructible
    depuis l'ancre) ; la zone adverse est permise et le round 1 aussi (l'exemption de
    `reserves_too_early` est portée par `analyzer_core`) ;
  - après MISCAST, une ligne « SUFFERS n Mortal Wounds [DA JUMP] Trigger:1 MW:n » sur la MÊME
    escouade avant la fin de la phase, n ≤ 6 ; ses dés sont contrôlés par `mw_ability_dice_error`
    (`MW_ABILITY_DICE_CHECKS["da_jump"]`, `mw_ability_dice_mismatch`) ; une ligne [DA JUMP] sans
    MISCAST en attente est une faute.
Journal antérieur (grammaire < 13) : abstention totale.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ai.analyzer_rules import note_rule_usage

DA_JUMP_LINE_RE = re.compile(r"Unit (\d+)\((\d+),\s*(\d+)\) DA JUMP \(D6=(\d)\) \[(REPOSITIONED|MISCAST)\]")
DA_JUMP_GRAMMAR = 13
COUNTER = "da_jump_invalid"


def _error(state: Any, stats: Dict[str, Any], player: int, line: str, detail: str) -> None:
    stats[COUNTER][player] += 1
    first = stats["first_error_lines"][COUNTER]
    if first[player] is None:
        first[player] = {"episode": state.current_episode_num, "line": line.strip(), "detail": detail}


def mw_dice_error_da_jump(brut: int, dice: Optional[List[int]], trigger: Optional[int]) -> Optional[str]:
    """`MW_ABILITY_DICE_CHECKS["da_jump"]` : Trigger:1 (le D6 raté) puis UN D6 de blessures."""
    if trigger != 1:
        return f"Trigger:{trigger} — un Da Jump ne blesse que sur 1"
    if dice is None or len(dice) != 1 or not (1 <= dice[0] <= 6):
        return f"MW:{dice} — un seul D6 de blessures mortelles attendu"
    if brut != dice[0]:
        return f"compte {brut} ≠ D6 MW:{dice[0]}"
    return None


def handle_da_jump_line(
    state: Any, stats: Dict[str, Any], line: str, action_desc: str, player: int, turn: int, phase: str
) -> bool:
    """Branche de la ligne DA JUMP. Rend False si la ligne n'en est pas une."""
    m = DA_JUMP_LINE_RE.search(action_desc)
    if m is None:
        return False
    unit_id, d6, outcome = m.group(1), int(m.group(4)), m.group(5)
    player = int(player)
    if state.log_grammar < DA_JUMP_GRAMMAR:
        return True
    note_rule_usage(stats, "PROJ.1.1.da_jump", player)
    key = (state.current_episode_num, int(turn), player)
    if key in state.da_jump_rolled:
        _error(state, stats, player, line, f"second Da Jump du joueur {player} au tour {turn} — once per turn, per army")
    state.da_jump_rolled.add(key)
    if phase != "MOVE":
        _error(state, stats, player, line, f"Da Jump en phase {phase} — « In your Movement phase »")
    if (outcome == "MISCAST") != (d6 == 1):
        _error(state, stats, player, line, f"D6={d6} mais issue {outcome}")
    # Une attente précédente non soldée est une faute (l'effet n'a pas laissé sa trace).
    _settle_pending(state, stats, line, player, reason="nouveau Da Jump")
    if outcome == "REPOSITIONED":
        state.da_jump_pending = {"kind": "ingress", "unit_id": unit_id, "turn": int(turn),
                                 "player": player, "episode": state.current_episode_num}
    else:
        state.da_jump_pending = {"kind": "suffers", "unit_id": unit_id, "turn": int(turn),
                                 "player": player, "episode": state.current_episode_num}
    return True


def _settle_pending(state: Any, stats: Dict[str, Any], line: str, player: int, *, reason: str) -> None:
    pending = state.da_jump_pending
    if pending is None:
        return
    what = "ingress" if pending["kind"] == "ingress" else "ligne SUFFERS [DA JUMP]"
    _error(state, stats, int(pending["player"]), line,
           f"Da Jump de Unit {pending['unit_id']} (tour {pending['turn']}) sans {what} avant : {reason}")
    state.da_jump_pending = None


def on_phase_change(state: Any, stats: Dict[str, Any], line: str, new_phase: str, player: int) -> None:
    """Fin de la phase de mouvement : une attente encore ouverte est une faute."""
    if state.da_jump_pending is not None and new_phase != "MOVE":
        _settle_pending(state, stats, line, int(player), reason=f"la phase {new_phase} a commencé")


def unit_repositioned_this_turn(state: Any, unit_id: str, turn: int) -> bool:
    """L'escouade a-t-elle été repositionnée par Da Jump CE tour (exemption 20.03 / round 1) ?"""
    pending = state.da_jump_pending
    return (
        pending is not None and pending["kind"] == "ingress"
        and pending["unit_id"] == str(unit_id) and int(pending["turn"]) == int(turn)
    )


def check_unit_action_while_off_table(
    state: Any, stats: Dict[str, Any], line: str, unit_id: str, player: int
) -> None:
    """Une escouade repositionnée n'agit pas avant son ingress (elle est hors table)."""
    pending = state.da_jump_pending
    if pending is None or pending["kind"] != "ingress" or pending["unit_id"] != str(unit_id):
        return
    _error(state, stats, int(player), line,
           f"Unit {unit_id} agit alors qu'elle est en réserves après Da Jump (avant son ingress)")


def handle_ingress_after_da_jump(
    state: Any, stats: Dict[str, Any], config: Any, line: str, unit_id: str, player: int, turn: int,
    models: Dict[str, Tuple[int, int]],
) -> None:
    """Ligne DEPLOYED (ingress) de l'escouade repositionnée : chaque socle à plus de 8" de tout
    socle ennemi vivant (24.09 accordé), puis l'attente est soldée."""
    from ai.analyzer import calculate_hex_distance, _analyzer_engagement_metric, _get_inches_to_subhex_for_analyzer

    pending = state.da_jump_pending
    if pending is None or pending["kind"] != "ingress" or pending["unit_id"] != str(unit_id):
        return
    state.da_jump_pending = None
    if int(pending["turn"]) != int(turn):
        _error(state, stats, int(player), line,
               f"ingress de Unit {unit_id} au tour {turn} après un Da Jump du tour {pending['turn']} — même phase attendue")
        return
    if _analyzer_engagement_metric() != "hex":
        return
    clearance = 8 * int(_get_inches_to_subhex_for_analyzer())
    enemy_cells: List[Tuple[int, int]] = []
    for other_id, other_models in state.positions_by_model.items():
        if state.unit_player.get(other_id) == int(player):
            continue
        if state.unit_hp.get(other_id, 0) <= 0:
            continue
        enemy_cells.extend(other_models.values())
    if not models:
        _error(state, stats, int(player), line, f"ingress de Unit {unit_id} sans segment [MODELS:]")
        return
    for mid, (col, row) in models.items():
        too_close = min(
            (calculate_hex_distance(col, row, ec, er) for ec, er in enemy_cells), default=None
        )
        if too_close is not None and too_close <= clearance:
            _error(state, stats, int(player), line,
                   f"socle {mid} posé à {too_close} cases d'un ennemi après Da Jump — plus de 8\" "
                   f"({clearance} cases) exigé")
            return


def handle_suffers_da_jump(state: Any, stats: Dict[str, Any], line: str, unit_id: str, player: int, brut: int) -> None:
    """Ligne « SUFFERS n Mortal Wounds [DA JUMP] » : solde l'attente MISCAST de la même escouade."""
    if state.log_grammar < DA_JUMP_GRAMMAR:
        return
    pending = state.da_jump_pending
    if pending is None or pending["kind"] != "suffers" or pending["unit_id"] != str(unit_id):
        _error(state, stats, int(player), line,
               f"SUFFERS [DA JUMP] de Unit {unit_id} sans DA JUMP [MISCAST] en attente")
        return
    state.da_jump_pending = None
    if brut > 6:
        _error(state, stats, int(player), line, f"{brut} blessures mortelles — au plus D6")
