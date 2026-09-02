"""Pile-in invalide (budget dépassé) ne doit pas masquer une violation d'alternance 12.04.

Scénario :
  - Unit 1 (chargée) effectue un PILED IN hors-budget (20 subhex > 3" × 5 = 15 subhex) :
    fight_move_invalid doit être incrémenté.
  - Unit 2 (non chargée) combat ensuite : fight_alternation_violations doit être incrémenté,
    car unit 1 ne doit PAS être marquée comme ayant combattu quand son pile-in est invalide.

AVANT fix : handle_fight_move ajoutait unit 1 à charged_units_fought AVANT le contrôle de
            budget → la violation d'alternance était masquée.
APRÈS fix : charged_units_fought n'est alimenté que si pile_in_move_valid = True.

Positions (échelle x5, zone d'engagement = 10 subhex) :
  - CHARGER (100,92) : à 8 subhex de TARGET → engagée (8 ≤ 10)
  - OTHER   (100,108) : à 8 subhex de TARGET → engagée (8 ≤ 10)
  - INVALID_DEST (100,72) : à 20 subhex de CHARGER → dépasse le budget pile-in de 15 subhex
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

TARGET = (100, 100)
CHARGER = (100, 92)
OTHER = (100, 108)
INVALID_DEST = (100, 72)   # (100,92)→(100,72) = 20 subhex > budget 15

T = f"({TARGET[0]},{TARGET[1]})"
C = f"({CHARGER[0]},{CHARGER[1]})"
OTH = f"({OTHER[0]},{OTHER[1]})"
INV = f"({INVALID_DEST[0]},{INVALID_DEST[1]})"

_UNITS = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{C} DEPLOYED from (-1,-1) to {C} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{OTH} DEPLOYED from (-1,-1) to {OTH} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{C} CHARGED Unit 101{T} "
    f'from (100,80) to {C} [Roll: 8] [Dist: 2.0" | Nearest: 2.0"] [R:+0.0] [SUCCESS]\n'
)

# Pile-in invalide : déplacement de 20 subhex, budget = 15 (3" × 5).
_UNIT1_PILE_IN_INVALID = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 1{C} PILED IN from {C} to {INV} [R:+0.0] [SUCCESS]\n"
)

# Unité 2 (non-chargée) combat l'unité 101.
_UNIT2_FIGHTS = (
    f"[10:00:04] E1 T1 P1 FIGHT : Unit 2{OTH} FOUGHT Unit 101{T} with [Close Combat Weapon]"
    " - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_invalid_pilein_flagged_as_fight_move_invalid(tmp_path):
    """Prémisse : le pile-in hors-budget est bien comptabilisé dans fight_move_invalid."""
    stats = _stats(tmp_path, _UNIT1_PILE_IN_INVALID)
    assert stats["fight_move_invalid"]["pile_in"][1] == 1


def test_invalid_pilein_does_not_mask_alternation_violation(tmp_path):
    """Pile-in invalide + combat d'une unité non-chargée = violation d'alternance 12.04.

    AVANT fix : unit 1 ajoutée à charged_units_fought avant le contrôle → violation masquée.
    APRÈS fix : pile_in_move_valid = False → unit 1 non marquée → violation détectée.
    """
    stats = _stats(tmp_path, _UNIT1_PILE_IN_INVALID + _UNIT2_FIGHTS)
    assert stats["fight_move_invalid"]["pile_in"][1] == 1
    assert stats["fight_alternation_violations"][1] == 1
