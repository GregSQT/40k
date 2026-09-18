"""`objective_secured_invalid` (ai/analyzer_objectives.py, PROJ.2.3.objective_secured, 14.03) —
grammaire 15, journal FABRIQUÉ, roster réel, plateau 100×100 à x1, zone « rect b NW ».

Unit 1 (Boyz P1 : Get da Good Bitz) dans l'aire ; Unit 101 (Boyz P2). Apparition de `Sec=1`
après une ligne SECURES de P1 en phase COMMAND, contrôle à P1 → 0 ; `Sec=1` sans SECURES → 1 ;
SECURES hors phase COMMAND → 1 ; SECURES par une escouade hors de l'aire → 1 ; maintien du contrôle
sur égalité d'OC quand l'objectif est sécurisé → 0, perte sur égalité → 1 ; perte sur niveau adverse
strictement supérieur → 0 ; journal < 15 → abstention.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai.test_analyzer_objective_control import _SETUP, _UNITS, _move, _snapshot

_OBJ = "(50,50);(50,51);(50,52)"
_END = "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"
_BOYZ_IN = _move("1", "1#0@(50,50,z0) 1#1@(50,51,z0)")
_ENEMY_IN = _move("101", "101#0@(50,52,z0) 101#1@(60,60,z0)", sec=3, player=2)


def _secures(unit: str = "1", pos: str = "(50,50)", phase: str = "COMMAND", player: int = 1, sec: int = 4) -> str:
    return (
        f"[10:00:{sec:02d}] E1 T2 P{player} {phase} : Unit {unit}{pos} SECURES rect b NW [GET DA GOOD BITZ]"
        f" [R:+0.0] [SUCCESS]\n"
    )


def _stats(tmp_path, body: str, grammar: int = 15) -> dict:
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _SETUP + body + _END, units=_UNITS, objectives=_OBJ, inches_to_subhex=1,
        board="cols=100 rows=100", hex_radius="1.0", ez_vertical_inches=None,
        rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=ork (ref)", log_grammar=grammar,
    ))
    return an.parse_step_log(str(log))


def _first(stats) -> str:
    first = stats["first_error_lines"]["objective_secured_invalid"]
    return str((first[1] or first[2] or {}).get("detail"))


def test_securisation_apres_la_ligne_secures_en_phase_de_commandement_est_correcte(tmp_path):
    body = (
        _BOYZ_IN + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=none", sec=3)
        + _secures() + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=1", sec=5)
    )
    stats = _stats(tmp_path, body)
    assert stats["objective_secured_invalid"] == {1: 0, 2: 0}, _first(stats)
    assert stats["special_rule_usage"][("secure_objective_on_control", "Boyz")][1] == 1
    assert stats["special_rule_usage_invalid"][("secure_objective_on_control", "Boyz")][1] == 0


def test_securisation_sans_ligne_secures_est_une_faute(tmp_path):
    body = (
        _BOYZ_IN + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=none", sec=3)
        + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=1", sec=5)
    )
    stats = _stats(tmp_path, body)
    assert stats["objective_secured_invalid"] == {1: 1, 2: 0} and "sans ligne SECURES" in _first(stats)


def test_secures_hors_phase_de_commandement_ou_hors_de_l_aire_est_une_faute(tmp_path):
    fight = _stats(tmp_path, _BOYZ_IN + _secures(phase="FIGHT") + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=1", sec=5))
    assert fight["objective_secured_invalid"][1] >= 1 and "phase FIGHT" in _first(fight)
    outside = _stats(tmp_path, _move("1", "1#0@(70,70,z0) 1#1@(71,70,z0)") + _secures(pos="(70,70)")
                     + _snapshot("rect b NW:Ctrl=none:Mthd=default:OC1=0:OC2=0:Sec=1", sec=5))
    assert outside["objective_secured_invalid"][1] >= 1 and "sans aucun socle dans l'aire" in _first(outside)


def test_un_objectif_securise_reste_controle_sur_egalite_et_se_perd_sur_strictement_plus(tmp_path):
    secured = (
        _BOYZ_IN + _secures(sec=3) + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=1", sec=4)
        + _ENEMY_IN
        + "[10:00:05] E1 T2 P2 SHOOT : Unit 1 DEAD model=1#1 reason=combat [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
        + "[10:00:05] E1 T2 P2 SHOOT : Unit 101(50,52) WAIT [MODELS: 101#0@(50,52,z0) 101#1@(60,60,z0)] [R:+0.0] [SUCCESS]\n"
    )
    # Égalité 2 vs 2 : l'objectif sécurisé reste à P1.
    kept = _stats(tmp_path, secured + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=2:OC2=2:Sec=1", sec=6))
    assert kept["objective_secured_invalid"] == {1: 0, 2: 0}, _first(kept)
    assert kept["objective_control_mismatch"] == {1: 0, 2: 0}
    lost_on_tie = _stats(tmp_path, secured + _snapshot("rect b NW:Ctrl=none:Mthd=default:OC1=2:OC2=2:Sec=none", sec=6))
    assert lost_on_tie["objective_secured_invalid"] == {1: 1, 2: 0} and "strictement" in _first(lost_on_tie)
    # Le second Boy P2 entre : 2 vs 4, strictement plus → P2 prend, la sécurisation tombe.
    overrun = (
        secured
        + "[10:00:06] E1 T2 P2 MOVE : Unit 101(50,52) MOVED from (50,52) to (50,52)"
        " [MODELS: 101#0@(50,52,z0) 101#1@(50,51,z0)] [R:+0.0] [SUCCESS]\n"
    )
    taken = _stats(tmp_path, overrun + _snapshot("rect b NW:Ctrl=2:Mthd=default:OC1=2:OC2=4:Sec=none", sec=7))
    assert taken["objective_secured_invalid"] == {1: 0, 2: 0}, _first(taken)
    assert taken["objective_control_mismatch"] == {1: 0, 2: 0}, taken["first_error_lines"]["objective_control_mismatch"]


def test_journal_anterieur_a_la_grammaire_15_est_une_abstention(tmp_path):
    body = _BOYZ_IN + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0", sec=3)
    stats = _stats(tmp_path, body, grammar=14)
    assert stats["objective_secured_invalid"] == {1: 0, 2: 0}
    assert stats["rule_usage"]["PROJ.2.3.objective_secured"] == {1: 0, 2: 0}
