"""`objective_control_mismatch` (ai/analyzer_objectives.py, PROJ.2.3.objective_control, 14.02) —
journal FABRIQUÉ, roster réel, plateau 100×100 à x1, zone « rect b NW » = (50,50)-(50,52).

Unit 1 (Boyz P1, OC 2 par figurine, 2 socles), Unit 2 (Intercessor P1 + Ancient 2#1 : Relic
Banner, +1 OC par figurine), Unit 101 (Boyz P2, 2 socles). L'OC est resommé depuis les socles dans
l'aire ; l'instantané doit dire la même chose : OC faux → 1 ; battle-shock oublié → 1 ; Relic
Banner oublié → 1 ; Relic Banner sans l'Ancient (mort) → 1 ; contrôleur sur égalité → 1 ;
journal antérieur (sans OC1=/OC2=) → abstention.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

# La fabrique nomme la zone « rect b NW » (un nom AVEC espaces — c'est ce que `|` sépare).
_OBJ = "(50,50);(50,51);(50,52)"
_UNITS = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1"
    " [MODELS: 1#0@(20,20,z0) 1#1@(21,20,z0)] [MODEL_TYPES: 1#0=Boyz 1#1=Boyz]\n"
    "[10:00:00] Unit 2 (Intercessor) P1: Starting position (20,30), HP_MAX=2 base=round/1"
    " [MODELS: 2#0@(20,30,z0) 2#1@(21,30,z0)] [MODEL_TYPES: 2#0=Intercessor 2#1=Ancient]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (80,80), HP_MAX=1 base=round/1"
    " [MODELS: 101#0@(80,80,z0) 101#1@(81,80,z0)] [MODEL_TYPES: 101#0=Boyz 101#1=Boyz]\n"
)
_SETUP = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(20,20) DEPLOYED from (-1,-1) to (20,20)"
    " [R:+0.0] [MODELS: 1#0@(20,20,z0) 1#1@(21,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2(20,30) DEPLOYED from (-1,-1) to (20,30)"
    " [R:+0.0] [MODELS: 2#0@(20,30,z0) 2#1@(21,30,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(80,80) DEPLOYED from (-1,-1) to (80,80)"
    " [R:+0.0] [MODELS: 101#0@(80,80,z0) 101#1@(81,80,z0)] [SUCCESS]\n"
)
_END = "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s\n"


def _move(unit: str, models: str, sec: int = 2, player: int = 1) -> str:
    anchor = models.split("@")[1].split(",z")[0].strip("(")
    return (
        f"[10:00:{sec:02d}] E1 T1 P{player} MOVE : Unit {unit}({anchor}) MOVED from (20,20) to ({anchor})"
        f" [MODELS: {models}] [R:+0.0] [SUCCESS]\n"
    )


def _snapshot(zones: str, turn: int = 2, sec: int = 5) -> str:
    return f"[10:00:{sec:02d}] T{turn} OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES={zones}\n"


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
    first = stats["first_error_lines"]["objective_control_mismatch"]
    return str((first[1] or first[2] or {}).get("detail"))


_BOYZ_IN = _move("1", "1#0@(50,50,z0) 1#1@(50,51,z0)")


def test_l_oc_resomme_depuis_les_socles_est_correct(tmp_path):
    stats = _stats(tmp_path, _BOYZ_IN + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=none"))
    assert stats["objective_control_mismatch"] == {1: 0, 2: 0}, _first(stats)
    assert stats["rule_usage"]["PROJ.2.3.objective_control"][1] == 1


def test_un_oc_imprime_faux_est_une_faute(tmp_path):
    stats = _stats(tmp_path, _BOYZ_IN + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=2:OC2=0:Sec=none"))
    assert stats["objective_control_mismatch"] == {1: 1, 2: 0}
    assert "resommés P1=4" in _first(stats)


def test_un_socle_hors_de_l_aire_ne_compte_pas(tmp_path):
    body = _move("1", "1#0@(50,50,z0) 1#1@(60,60,z0)") + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=2:OC2=0:Sec=none")
    assert _stats(tmp_path, body)["objective_control_mismatch"] == {1: 0, 2: 0}


def test_une_escouade_battle_shocked_n_apporte_rien(tmp_path):
    shock = "[10:00:03] E1 T2 P1 COMMAND : Unit 1(50,50) BATTLE-SHOCK Roll:2D6=3 vs Ld7+ → SHOCKED [R:+0.0] [SUCCESS]\n"
    ok = _stats(tmp_path, _BOYZ_IN + shock + _snapshot("rect b NW:Ctrl=none:Mthd=default:OC1=0:OC2=0:Sec=none"))
    assert ok["objective_control_mismatch"] == {1: 0, 2: 0}, _first(ok)
    bad = _stats(tmp_path, _BOYZ_IN + shock + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=0:Sec=none"))
    assert bad["objective_control_mismatch"] == {1: 1, 2: 0}


def test_relic_banner_ajoute_un_oc_a_chaque_figurine_tant_que_l_ancient_vit(tmp_path):
    intercessors_in = _move("2", "2#0@(50,50,z0) 2#1@(50,51,z0)")
    # Intercessor 2 + 1, Ancient 1 + 1 = 5.
    ok = _stats(tmp_path, intercessors_in + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=5:OC2=0:Sec=none"))
    assert ok["objective_control_mismatch"] == {1: 0, 2: 0}, _first(ok)
    bad = _stats(tmp_path, intercessors_in + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=3:OC2=0:Sec=none"))
    assert bad["objective_control_mismatch"] == {1: 1, 2: 0}
    # L'Ancient mort : plus de bonus, l'Intercessor seul vaut 2.
    dead = (
        intercessors_in
        + "[10:00:03] E1 T1 P2 SHOOT : Unit 2 DEAD model=2#1 reason=combat [MODELS: 2#0@(50,50,z0)] [SUCCESS]\n"
        + "[10:00:04] E1 T1 P2 SHOOT : Unit 2(50,50) WAIT [MODELS: 2#0@(50,50,z0)] [R:+0.0] [SUCCESS]\n"
    )
    after = _stats(tmp_path, dead + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=2:OC2=0:Sec=none"))
    assert after["objective_control_mismatch"] == {1: 0, 2: 0}, _first(after)
    stale = _stats(tmp_path, dead + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=3:OC2=0:Sec=none"))
    assert stale["objective_control_mismatch"] == {1: 1, 2: 0}


def test_egalite_sans_securisation_ne_donne_le_controle_a_personne(tmp_path):
    body = _BOYZ_IN + _move("101", "101#0@(50,52,z0) 101#1@(60,60,z0)", sec=3, player=2)
    # 4 (deux Boyz P1) vs 2 (un Boy P2) : P1 ; puis un Boy P1 meurt → 2 vs 2 → personne.
    ok = _stats(tmp_path, body + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=4:OC2=2:Sec=none"))
    assert ok["objective_control_mismatch"] == {1: 0, 2: 0}, _first(ok)
    tie = (
        body + "[10:00:04] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#1 reason=combat [MODELS: 1#0@(50,50,z0)] [SUCCESS]\n"
        + "[10:00:04] E1 T1 P2 SHOOT : Unit 101(50,52) WAIT [MODELS: 101#0@(50,52,z0) 101#1@(60,60,z0)] [R:+0.0] [SUCCESS]\n"
    )
    none = _stats(tmp_path, tie + _snapshot("rect b NW:Ctrl=none:Mthd=default:OC1=2:OC2=2:Sec=none"))
    assert none["objective_control_mismatch"] == {1: 0, 2: 0}, _first(none)
    # Le contrôleur n'est jugé qu'à son CHANGEMENT (entre deux frontières il peut être d'avant
    # le dernier mouvement) : ici il passe de « personne » (instantané d'avant les mouvements) à
    # P1 sur une égalité 2 vs 2 sans sécurisation — une détermination fausse.
    first = _snapshot("rect b NW:Ctrl=none:Mthd=default:OC1=0:OC2=0:Sec=none", turn=1, sec=1)
    kept = _stats(tmp_path, first + tie + _snapshot("rect b NW:Ctrl=1:Mthd=default:OC1=2:OC2=2:Sec=none"))
    assert kept["objective_control_mismatch"] == {1: 1, 2: 0} and "contrôleur imprimé 1" in _first(kept)


def test_un_controleur_inchange_entre_deux_frontieres_n_est_pas_juge(tmp_path):
    """Instantané de VP/CP entre deux frontières : l'OC est vivant, le contrôleur d'avant le
    mouvement — pas une faute (mesuré sur le journal réel du 2026-09-18)."""
    first = _snapshot("rect b NW:Ctrl=none:Mthd=default:OC1=0:OC2=0:Sec=none", turn=1, sec=1)
    stale = _stats(tmp_path, first + _BOYZ_IN + _snapshot("rect b NW:Ctrl=none:Mthd=default:OC1=4:OC2=0:Sec=none"))
    assert stale["objective_control_mismatch"] == {1: 0, 2: 0}, _first(stale)


def test_journal_sans_oc_par_zone_est_une_abstention(tmp_path):
    stats = _stats(tmp_path, _BOYZ_IN + _snapshot("rect b NW:Ctrl=1"), grammar=10)
    assert stats["objective_control_mismatch"] == {1: 0, 2: 0}
    assert stats["rule_usage"]["PROJ.2.3.objective_control"][1] == 0
