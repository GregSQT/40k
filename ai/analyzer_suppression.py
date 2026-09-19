"""Suppression (Primitive F, Indiscriminate Detonations) — le contrôle `suppression_without_hit`.

Datasheet WarTrakk : « when this unit has resolved its attacks, select one enemy unit HIT by one
or more of those attacks. That enemy unit is suppressed until the start of your next Command
phase. (While a unit is suppressed, it has -1 to hit rolls.) »

Trois faces d'UN invariant — suppression ⇔ touche ⇔ malus —, un seul compteur, rattaché à
l'entrée `PROJ.1.2.suppression` du corpus (bucket §1.2) :
  1. une ligne `Unit N(c,r) SUPPRESSES Unit M(c,r) [SUPPRESSED→M]` (grammaire 12) sans tir de N
     ayant TOUCHÉ M depuis la dernière phase de commandement du joueur de N → erreur ;
  2. un tir ou une mêlée de X portant le malus `[SUPPRESSED]` alors qu'aucune suppression de X
     n'est en vigueur → erreur ;
  3. un tir ou une mêlée de X sans le malus alors qu'une suppression de X est en vigueur → erreur
     (le « -1 contrôlé au TIR comme en mêlée » : au tir, le seuil imprimé n'est pas recalculé —
     couvert, HEAVY, 10.06, 22.05 — mais la PRÉSENCE du malus, elle, se juge).

Ce que « en vigueur » veut dire : posée par une ligne SUPPRESSES, levée à la première phase de
commandement du joueur SUPPRESSEUR (`command_handlers.command_phase_start` purge
`suppressed_squads` pour ce joueur). Une escouade est suppressée par UN joueur à la fois.

Journal antérieur (grammaire < 12) : aucune ligne SUPPRESSES n'est garantie → abstention totale,
jamais une faute inventée. Les touches, elles, sont relevées quelle que soit la grammaire.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ai.analyzer_hit import WOUND_SEGMENT_PRESENT_RE
from ai.analyzer_rules import note_rule_usage
from engine.phase_handlers.shared_utils import SUPPRESSED_MALUS_DISPLAY_NAME

#: « Unit N(c,r) SUPPRESSES Unit M(c,r) [SUPPRESSED→M] » (`shooting_handlers.suppress_squad`).
SUPPRESSES_LINE_RE = re.compile(
    r"Unit (\d+)\((\d+),\s*(\d+)\) SUPPRESSES Unit (\d+)\((\d+),\s*(\d+)\) \[SUPPRESSED→(\d+)\]"
)

#: Token de malus posé par le moteur sur les lignes d'attaque de l'unité supprimée (Primitive A).
_SUPPRESSED_TOKEN = f"[{SUPPRESSED_MALUS_DISPLAY_NAME.upper()}]"

COUNTER = "suppression_without_hit"


def _error(state: Any, stats: Dict[str, Any], player: int, line: str, detail: str) -> None:
    stats[COUNTER][player] += 1
    first = stats["first_error_lines"][COUNTER]
    if first[player] is None:
        first[player] = {"episode": state.current_episode_num, "line": line.strip(), "detail": detail}


def record_shot(state: Any, shooter_player: int, shooter_id: str, target_id: str, action_desc: str) -> None:
    """Relève une TOUCHE de tir (verdict = présence du segment `Wound`, comme `check_hit_result`)
    pour le joueur tireur, jusqu'à sa prochaine phase de commandement."""
    if WOUND_SEGMENT_PRESENT_RE.search(action_desc):
        state.shoot_hits_since_command.setdefault(int(shooter_player), set()).add(
            (str(shooter_id), str(target_id))
        )


def on_command_phase(state: Any, player: int) -> None:
    """Début de la phase de commandement de `player` : ses suppressions expirent et son relevé de
    touches repart de zéro (le moteur purge `suppressed_squads` au même instant)."""
    player = int(player)
    state.shoot_hits_since_command[player] = set()
    state.suppressions_in_force = {
        suppressed: (suppressor, sp)
        for suppressed, (suppressor, sp) in state.suppressions_in_force.items()
        if sp != player
    }


def handle_suppresses_line(
    state: Any, stats: Dict[str, Any], line: str, action_desc: str, player: int
) -> bool:
    """Branche de la ligne SUPPRESSES. Rend False si la ligne n'en est pas une."""
    m = SUPPRESSES_LINE_RE.search(action_desc)
    if m is None:
        return False
    suppressor_id, suppressed_id, token_id = m.group(1), m.group(4), m.group(7)
    player = int(player)
    note_rule_usage(stats, "PROJ.1.2.suppression", player)
    if token_id != suppressed_id:
        _error(state, stats, player, line,
               f"[SUPPRESSED→{token_id}] ne nomme pas l'escouade supprimée {suppressed_id}")
    elif (suppressor_id, suppressed_id) not in state.shoot_hits_since_command.get(player, set()):
        _error(state, stats, player, line,
               f"Unit {suppressor_id} supprime Unit {suppressed_id} sans l'avoir TOUCHÉE "
               f"depuis sa dernière phase de commandement")
    state.suppressions_in_force[suppressed_id] = (suppressor_id, player)
    return True


def check_attack_malus(
    state: Any, stats: Dict[str, Any], line: str, action_desc: str,
    attacker_id: str, attacker_player: int,
) -> None:
    """Faces 2 et 3 : le malus `[SUPPRESSED]` d'une ligne d'attaque (tir OU mêlée) doit
    correspondre exactement à une suppression en vigueur sur l'attaquant."""
    has_token = _SUPPRESSED_TOKEN in action_desc.upper()
    in_force: Optional[tuple] = state.suppressions_in_force.get(str(attacker_id))
    if has_token and in_force is None:
        _error(state, stats, int(attacker_player), line,
               f"Unit {attacker_id} attaque avec le malus [SUPPRESSED] sans suppression en vigueur")
    elif not has_token and in_force is not None:
        _error(state, stats, int(attacker_player), line,
               f"Unit {attacker_id} est supprimée par Unit {in_force[0]} et attaque SANS le malus "
               f"[SUPPRESSED]")
