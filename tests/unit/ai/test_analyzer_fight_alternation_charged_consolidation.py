"""Faux positif alternance 12.04 : unité chargée sans cible viable → PILED IN sans FOUGHT.

12.04 : tant qu'une unité chargée n'a pas combattu, c'est elle qui doit être activée.
Si l'unité chargée est sélectionnée en fights-first mais n'a aucune cible atteignable,
le moteur émet uniquement un PILED IN (pas de FOUGHT). Sans le fix, handle_fight_move
ne marque pas l'unité comme «  ayant combattu » → quand une unité non-chargée combat
ensuite, le contrôle voit l'unité chargée «  non activée » et encore engagée → faux positif.

Positions (échelle x5, zone d'engagement = 10 subhex) :
  - CHARGER (100,92) : à 8 subhex de TARGET → engagée
  - OTHER   (100,108) : à 8 subhex de TARGET → engagée
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

TARGET = (100, 100)
CHARGER = (100, 92)
OTHER = (100, 108)

T = f"({TARGET[0]},{TARGET[1]})"
C = f"({CHARGER[0]},{CHARGER[1]})"
OTH = f"({OTHER[0]},{OTHER[1]})"

_UNITS = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

# Déploiement + charge de l'unité 1 → ajout à charged_units_current_fight.
_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{C} DEPLOYED from (-1,-1) to {C} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{OTH} DEPLOYED from (-1,-1) to {OTH} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{C} CHARGED Unit 101{T} "
    f'from (100,80) to {C} [Roll: 8] [Dist: 2.0" | Nearest: 2.0"] [R:+0.0] [SUCCESS]\n'
)

# Unité 1 chargée sélectionnée sans cible vivante → PILED IN sans FOUGHT.
# L'ancre ne bouge pas (anchor_from == anchor_to) : aucun contrôle de budget.
_UNIT1_PILE_IN_NO_FIGHT = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 1{C} PILED IN from {C} to {C} [R:+0.0] [SUCCESS]\n"
)

# Unité 2 (non-chargée) combat l'unité 101.
_UNIT2_FIGHTS = (
    f"[10:00:04] E1 T1 P1 FIGHT : Unit 2{OTH} FOUGHT Unit 101{T} with [Close Combat Weapon]"
    " - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)

# Prémisse : sans PILED IN, unit 2 combat alors que unit 1 (chargée) n'a pas été activée → violation.
_UNIT2_FIGHTS_BEFORE_UNIT1 = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 2{OTH} FOUGHT Unit 101{T} with [Close Combat Weapon]"
    " - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_premise_fight_without_piled_in_is_violation(tmp_path):
    """Prémisse : unit 2 combat sans que unit 1 (chargée) n'ait été activée → violation.

    Sans ce test, le suivant ne prouve rien : si la violation n'est jamais détectée,
    l'absence de violation avec PILED IN ne confirme pas le fix.
    """
    stats = _stats(tmp_path, _UNIT2_FIGHTS_BEFORE_UNIT1)
    assert stats["fight_alternation_violations"][1] == 1


def test_charged_unit_pile_in_without_fight_not_alternation_violation(tmp_path):
    """PILED IN sans FOUGHT : unit 1 marquée comme activée → pas de violation pour unit 2.

    AVANT fix : handle_fight_move n'ajoutait pas unit 1 à charged_units_fought →
                unit 2 flaggée en alternance violation (unit 1 chargée et non activée).
    APRÈS fix : handle_fight_move ajoute unit 1 à charged_units_fought via
                `if unit_id in state.charged_units_current_fight: state.charged_units_fought.add(unit_id)`.
    """
    stats = _stats(tmp_path, _UNIT1_PILE_IN_NO_FIGHT + _UNIT2_FIGHTS)
    assert stats["fight_alternation_violations"][1] == 0
