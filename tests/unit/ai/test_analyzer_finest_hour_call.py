"""Grammaire 14 — `[FINEST HOUR]` n'élève le plafond de mêlée qu'après « ABILITY CALL Finest Hour
[USED] » de la MÊME escouade, ce tour, en FIGHT (journal FABRIQUÉ, roster réel : Captain with
Relic Shield, Master-crafted Power Weapon A6, +3 par `once_per_battle_melee_buff`).

  - appel USED puis 9 lignes `[FINEST HOUR]` → 0 `fight_over_cc_nb`, 0 `parse_errors` ;
  - PAS d'appel → plafond non levé (6) : 3 dépassements + une `parse_error` qui nomme l'appel ;
  - appel DECLINED → idem « pas d'appel » ;
  - grammaire 13 sans appel → abstention (plafond levé, 0 erreur) ;
  - l'acteur de l'appel est le préfixe « Unit N( » de la ligne, pas le dernier `DEPLOYED` : ici
    Unit 101 est déployée EN DERNIER, et l'appel de Unit 1 doit quand même couvrir ses lignes.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

CAPTAIN = "CaptainRelicShield"
WEAPON = "Master-crafted Power Weapon"
NB = 6
FH_BONUS = 3
A = (50, 50)
T = (50, 51)
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

_UNITS = (
    f"[10:00:00] Unit 1 ({CAPTAIN}) P1: Starting position ({A[0]},{A[1]}), HP_MAX=6 base=round/16"
    f" [MODELS: 1#0@({A[0]},{A[1]},z0)] [MODEL_TYPES: 1#0={CAPTAIN}]\n"
    f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position ({T[0]},{T[1]}), HP_MAX=2 base=round/6"
    f" [MODELS: 101#0@({T[0]},{T[1]},z0)]\n"
)
_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({A[0]},{A[1]}) DEPLOYED from (-1,-1) to ({A[0]},{A[1]})"
    f" [R:+0.0] [MODELS: 1#0@({A[0]},{A[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({T[0]},{T[1]}) DEPLOYED from (-1,-1) to ({T[0]},{T[1]})"
    f" [R:+0.0] [MODELS: 101#0@({T[0]},{T[1]},z0)] [SUCCESS]\n"
)
_MODELS = f"[MODELS: 1#0@({A[0]},{A[1]},z0)]"
_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")


def _call(verdict: str) -> str:
    return (
        f"[10:00:02] E1 T1 P1 FIGHT : Unit 1({A[0]},{A[1]}) ABILITY CALL Finest Hour [{verdict}]"
        f" {_MODELS} [R:+0.0] [SUCCESS]\n"
    )


def _blow() -> str:
    return (
        f"[10:00:04] E1 T1 P1 FIGHT : Unit 1({A[0]},{A[1]}) FOUGHT Unit 101({T[0]},{T[1]})"
        f" with [{WEAPON}] - Hit 4(3+) [FINEST HOUR] - Wound 5(4+) - Save 2(3+) - Dmg:0HP"
        f" [FIGHT_SUBPHASE:fight] {_MODELS} [SHOOTER_MODELS: 1#0] [ALLOC_MODEL: 101#0] [TARGET_DECL:1]"
        f" [R:+0.0] [SUCCESS]\n"
    )


def _parse(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _SETUP + body + _END, units=_UNITS, objectives=OBJECTIVES,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    ))
    return an.parse_step_log(str(log))


def _fh_errors(stats) -> list:
    return [e for e in stats["parse_errors"] if "FINEST HOUR" in str(e.get("error"))]


def test_used_call_covers_the_nine_attacks(tmp_path):
    stats = _parse(tmp_path, _call("USED") + _blow() * (NB + FH_BONUS))
    assert stats["fight_over_cc_nb"][1] == 0, stats["first_error_lines"]["fight_over_cc_nb"][1]
    assert _fh_errors(stats) == []


def test_without_a_call_the_cap_is_not_raised(tmp_path):
    stats = _parse(tmp_path, _blow() * (NB + FH_BONUS))
    assert stats["fight_over_cc_nb"][1] == FH_BONUS
    assert _fh_errors(stats) and "ABILITY CALL Finest Hour [USED]" in _fh_errors(stats)[0]["error"]


def test_a_declined_call_does_not_raise_the_cap(tmp_path):
    stats = _parse(tmp_path, _call("DECLINED") + _blow() * (NB + FH_BONUS))
    assert stats["fight_over_cc_nb"][1] == FH_BONUS and _fh_errors(stats)

