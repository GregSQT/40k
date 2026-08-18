"""PROJ.1.4 double_pile_in : un groupe pile-in (12.02) suivi d'un overrun pile-in (12.06)
pour la même unité ne doit PAS être compté comme une violation.

Le garde anti-doublon (pile_in_done) empêche tout double dans l'étape 12.02 — les 8 violations
signalées sont des faux positifs : le gym loguait l'overrun 12.06 avec la même balise "PILED IN"
que le groupe pile-in, et l'analyzer les comptait comme un doublon dans la même étape.
Le fix : l'overrun pile-in est loggué "OVERRUN PILED IN", balise exclue du contrôle 12.02.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

# ── scénario minimal ──────────────────────────────────────────────────────────
# Résolution x5 (inches_to_subhex=5), zone d'engagement = 10 subhex.
# Unité 1 (P1) : charge, puis fait son groupe pile-in, puis overrun pile-in.
# Unité 101 (P2) : cible.

U1 = (100, 100)
U101 = (100, 90)
U1s = f"({U1[0]},{U1[1]})"
U101s = f"({U101[0]},{U101[1]})"

_UNITS = (
    f"[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{U1s} DEPLOYED from (-1,-1) to {U1s} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{U101s} DEPLOYED from (-1,-1) to {U101s} [R:+0.0] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{U1s} CHARGED Unit 101{U101s} from (100,120) to {U1s}"
    f" [Roll: 8] [Dist: 2.0\" | Nearest: 2.0\"] [R:+0.0] [SUCCESS]\n"
)

# Groupe pile-in (12.02) : balise "PILED IN"
_PILE_IN = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 1{U1s} PILED IN from (100,120) to {U1s} [R:+0.0] [SUCCESS]\n"
)

# Overrun pile-in (12.06) — AVANT le fix : même balise "PILED IN" → faux positif
_OVERRUN_OLD = (
    f"[10:00:04] E1 T1 P1 FIGHT : Unit 1{U1s} PILED IN from {U1s} to (100,95) [R:+0.0] [SUCCESS]\n"
)

# Overrun pile-in (12.06) — APRÈS le fix : balise "OVERRUN PILED IN"
_OVERRUN_NEW = (
    f"[10:00:04] E1 T1 P1 FIGHT : Unit 1{U1s} OVERRUN PILED IN from {U1s} to (100,95) [R:+0.0] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(_SETUP + body, units=_UNITS, ez_vertical_inches=None))
    return an.parse_step_log(str(log))


def test_genuine_double_pile_in_is_detected(tmp_path):
    """Prémisse : deux 'PILED IN' pour la même unité = violation détectée. Sinon le test suivant
    ne prouve rien."""
    stats = _stats(tmp_path, _PILE_IN + _OVERRUN_OLD)
    assert stats["fight_double_pile_in"][1] == 1


def test_overrun_pile_in_does_not_trigger_double_violation(tmp_path):
    """Un groupe pile-in suivi d'un overrun pile-in (balise 'OVERRUN PILED IN') ne doit pas
    être compté comme un doublon 12.02."""
    stats = _stats(tmp_path, _PILE_IN + _OVERRUN_NEW)
    assert stats["fight_double_pile_in"][1] == 0
