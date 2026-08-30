"""Charge sur plusieurs cibles — le parser ne doit PAS compter d'erreur de format.

PROJ.2.7 : la regex CHARGE ne gérait pas les charges multi-cibles (`Unit A,Unit B`). Le
`re.search` retournait None → compteur `parsing_errors` incrémenté, position non mise à jour.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

U1 = (100, 100)
U101 = (100, 92)
U102 = (108, 92)

U1s = f"({U1[0]},{U1[1]})"
U101s = f"({U101[0]},{U101[1]})"
U102s = f"({U102[0]},{U102[1]})"

_UNITS = (
    f"[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    f"[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{U1s} DEPLOYED from (-1,-1) to {U1s} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{U101s} DEPLOYED from (-1,-1) to {U101s} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102{U102s} DEPLOYED from (-1,-1) to {U102s} [R:+0.0] [SUCCESS]\n"
)

_CHARGE_MULTI = (
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{U1s} CHARGED Unit 101{U101s},Unit 102{U102s}"
    f" from (100,120) to {U1s} [Roll: 8] [Dist: 2.0\" | Nearest: 2.0\"] [R:+0.0] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_charge_multi_target_no_parsing_error(tmp_path):
    """Charge sur deux cibles : aucune erreur de format."""
    stats = _stats(tmp_path, _CHARGE_MULTI)
    assert len(stats["parse_errors"]) == 0
