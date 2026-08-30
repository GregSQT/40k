"""FIGHTS FIRST (24.13) — aucune violation d'alternance ne doit être comptée.

PROJ.1.4.alternance : le check d'alternance flagguait les unités FIGHTS FIRST comme
violant l'ordre 12.04, car il ne lisait pas le token `[FIGHTS FIRST]` dans la ligne.
Une unité FIGHTS FIRST combat légalement avant l'alternance ordinaire, même si des unités
chargées n'ont pas encore été activées.

Ce test est le pendant du `test_alternation_violation_is_detected_when_the_target_survives`
dans `test_analyzer_fight_alternation_pre_loss.py` : il s'assure que la situation symétrique
(unité non chargée avec FIGHTS FIRST) est exemptée du check.
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

_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{C} DEPLOYED from (-1,-1) to {C} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{OTH} DEPLOYED from (-1,-1) to {OTH} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{C} CHARGED Unit 101{T} from (100,80) to {C}"
    f" [Roll: 8] [Dist: 2.0\" | Nearest: 2.0\"] [R:+0.0] [SUCCESS]\n"
)

# Unit 2 combat en premier grâce à FIGHTS FIRST, alors que unit 1 (chargée) n'a pas encore combattu.
_FIGHT_FIGHTS_FIRST = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 2{OTH} FOUGHT Unit 101{T} with [Close Combat Weapon]"
    " [FIGHTS FIRST] - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0]"
    " [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)

# Même situation, sans le token : doit produire une violation (prémisse du test d'exemption).
_FIGHT_WITHOUT_FIGHTS_FIRST = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 2{OTH} FOUGHT Unit 101{T} with [Close Combat Weapon]"
    " - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0]"
    " [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_fights_first_no_alternation_violation(tmp_path):
    """FIGHTS FIRST : 0 violation d'alternance."""
    stats = _stats(tmp_path, _FIGHT_FIGHTS_FIRST)
    assert stats["fight_alternation_violations"][1] == 0


def test_without_fights_first_alternation_violation_detected(tmp_path):
    """Prémisse : sans FIGHTS FIRST, la violation est bien détectée."""
    stats = _stats(tmp_path, _FIGHT_WITHOUT_FIGHTS_FIRST)
    assert stats["fight_alternation_violations"][1] == 1
