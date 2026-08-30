"""Consolidation ancre invariante — aucune violation de budget ne doit être comptée.

PROJ.1.4.consolidation : `moved = bool(prev_models and new_models) or anchor_from != anchor_to`
déclenchait `_per_model_move_violation` même quand l'ancre ne bougeait pas (from == to).
En mode [ONGOING] la baseline `prev_models` pouvait être périmée (mise à jour par l'action
FOUGHT précédente), produisant un faux écart per-figurine > 3".

Fix : `moved = anchor_from != anchor_to` — seul le déplacement d'ancre déclenche le check.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

U1 = (100, 100)
U101 = (100, 92)

U1s = f"({U1[0]},{U1[1]})"
U101s = f"({U101[0]},{U101[1]})"

_UNITS = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
)

_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{U1s} DEPLOYED from (-1,-1) to {U1s}"
    f" [R:+0.0] [MODELS: 1#0@({U1[0]},{U1[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{U101s} DEPLOYED from (-1,-1) to {U101s}"
    f" [R:+0.0] [MODELS: 101#0@({U101[0]},{U101[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{U1s} CHARGED Unit 101{U101s} from (100,120) to {U1s}"
    f" [Roll: 8] [Dist: 2.0\" | Nearest: 2.0\"] [R:+0.0] [MODELS: 1#0@({U1[0]},{U1[1]},z0)] [SUCCESS]\n"
)

# Combat suivi d'une consolidation qui ne déplace pas l'ancre (from == to).
_FIGHT_THEN_CONSOLIDATE_ZERO = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 1{U1s} FOUGHT Unit 101{U101s} with [Close Combat Weapon]"
    f" - Hit 3(3+) - Wound 2(4+) - Save 1(3+) - Dmg:1HP [R:+0.0]"
    f" [FIGHT_SUBPHASE:fight] [MODELS: 1#0@({U1[0]},{U1[1]},z0)] [SHOOTER_MODELS: 1#0]"
    f" [ALLOC_MODEL: 101#0] [SUCCESS]\n"
    f"[10:00:04] E1 T1 P1 FIGHT : Unit 1{U1s} CONSOLIDATED from {U1s} to {U1s} [ONGOING]"
    f" [R:+0.0] [MODELS: 1#0@({U1[0]},{U1[1]},z0)] [SUCCESS]\n"
)

# Consolidation qui dépasse réellement le budget (16 subhex > 15 à x5 = 3").
_CONSOLIDATE_OVER_BUDGET = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 1{U1s} CONSOLIDATED from {U1s} to (100,116)"
    f" [R:+0.0] [MODELS: 1#0@(100,116,z0)] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS))
    return an.parse_step_log(str(log))


def test_consolidation_zero_distance_no_violation(tmp_path):
    """Consolidation from == to : 0 violation de budget."""
    stats = _stats(tmp_path, _FIGHT_THEN_CONSOLIDATE_ZERO)
    assert stats["fight_move_invalid"]["consolidation"][1] == 0


def test_consolidation_over_budget_detected(tmp_path):
    """Prémisse : une consolidation qui dépasse le budget est bien détectée."""
    stats = _stats(tmp_path, _CONSOLIDATE_OVER_BUDGET)
    assert stats["fight_move_invalid"]["consolidation"][1] == 1
