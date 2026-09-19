"""`save_threshold_mismatch` (ai/analyzer_save.py, PROJ.2.3.save_threshold, 05.04) — journal
FABRIQUÉ, roster réel.

Tireur : Unit 1 (Intercessor, P1, Bolt Rifle AP-1). Cibles P2 : Unit 101 (Boyz Sv 5+ + BannerNob
101#2 : Waaagh! Banner 5++ pour toute l'escouade, 19.04) ; Unit 103 (Boyz seuls, Sv 5+) ; Unit 104
(Intercessor Sv 3+ + Librarian 104#1 : Mental Fortress 4++). Attendu = min(Sv − AP, InSv) :
  - 103 : 5+ AP-1 → 6+ ; imprimé 6+ → 0 ; 5+ (un 5++ sans Waaagh! actif) → 1 ;
  - 101 : 5++ du BannerNob → 5+ ; après sa mort (DEAD à un tour précédent) → 6+, un 5+ → 1 ;
  - Waaagh! actif (`EFFECTS: P2 waaagh=on … waaagh_invul=5+`) : 103 → 5+ ; sans la clé
    `waaagh_invul` (journal antérieur) → abstention ;
  - 104 : 3+ AP-1 = 4+, Mental Fortress 4++ → 4+ ; l'Intercessor sous AP-3 → 4+ (InSv) ;
  - Sv de base imprimée ≠ datasheet → 1.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

_OBJECTIVES = ";".join(f"(50,{r})" for r in range(50, 53))
_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (20,20), HP_MAX=2 base=round/1"
    " [MODELS: 1#0@(20,20,z0)] [MODEL_TYPES: 1#0=Intercessor]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (30,20), HP_MAX=1 base=round/1"
    " [MODELS: 101#0@(30,20,z0) 101#1@(31,20,z0) 101#2@(32,20,z0)]"
    " [MODEL_TYPES: 101#0=Boyz 101#1=Boyz 101#2=BannerNob]\n"
    "[10:00:00] Unit 103 (Boyz) P2: Starting position (30,40), HP_MAX=1 base=round/1"
    " [MODELS: 103#0@(30,40,z0) 103#1@(31,40,z0)] [MODEL_TYPES: 103#0=Boyz 103#1=Boyz]\n"
    "[10:00:00] Unit 104 (Intercessor) P2: Starting position (30,60), HP_MAX=2 base=round/1"
    " [MODELS: 104#0@(30,60,z0) 104#1@(31,60,z0)] [MODEL_TYPES: 104#0=Intercessor 104#1=Librarian]\n"
)
_SETUP = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(20,20) DEPLOYED from (-1,-1) to (20,20)"
    " [R:+0.0] [MODELS: 1#0@(20,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(30,20) DEPLOYED from (-1,-1) to (30,20)"
    " [R:+0.0] [MODELS: 101#0@(30,20,z0) 101#1@(31,20,z0) 101#2@(32,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 103(30,40) DEPLOYED from (-1,-1) to (30,40)"
    " [R:+0.0] [MODELS: 103#0@(30,40,z0) 103#1@(31,40,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 104(30,60) DEPLOYED from (-1,-1) to (30,60)"
    " [R:+0.0] [MODELS: 104#0@(30,60,z0) 104#1@(31,60,z0)] [SUCCESS]\n"
)
_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")


def _shot(target: str, pos: str, mid: str, save: str, sec: int = 3, weapon: str = "Bolt Rifle") -> str:
    return (
        f"[10:00:{sec:02d}] E1 T1 P1 SHOOT : Unit 1(20,20) SHOT [DESIGNATED:{target}] Unit {target}{pos}"
        f" with [{weapon}] - Hit 4(3+) - Wound 5(4+) - → {mid} - Save 2({save}) - Dmg:1HP"
        f" [MODELS: 1#0@(20,20,z0)] [SHOOTER_MODELS: 1#0] [ALLOC_MODEL: {mid}] [TARGET_DECL:1]"
        f" [R:+0.0] [SUCCESS]\n"
    )


def _stats(tmp_path, body: str) -> dict:
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _SETUP + body + _END, units=_UNITS, objectives=_OBJECTIVES, inches_to_subhex=1,
        board="cols=100 rows=100", hex_radius="1.0", ez_vertical_inches=None,
        rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=ork (ref)"
    ))
    return an.parse_step_log(str(log))


def _first(stats) -> str:
    first = stats["first_error_lines"]["save_threshold_mismatch"]
    return str((first[1] or first[2] or {}).get("detail"))


_WAAAGH_ON = "[10:00:02] T1 EFFECTS: P1 none | P2 waaagh=on waaagh_melee_str=+1 waaagh_melee_atk=+1 waaagh_invul=5+\n"
_WAAAGH_ON_OLD = "[10:00:02] T1 EFFECTS: P1 none | P2 waaagh=on waaagh_melee_str=+1 waaagh_melee_atk=+1\n"


def test_sv_degradee_par_l_ap_sans_invulnerable_est_correcte(tmp_path):
    stats = _stats(tmp_path, _shot("103", "(30,40)", "103#0", "5+ AP-1 → 6+"))
    assert stats["save_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)
    assert stats["rule_usage"]["PROJ.2.3.save_threshold"][1] == 1


def test_un_5_plus_sans_waaagh_actif_est_une_faute(tmp_path):
    stats = _stats(tmp_path, _shot("103", "(30,40)", "103#0", "5+ AP-1 → 5+"))
    assert stats["save_threshold_mismatch"] == {1: 0, 2: 1}
    assert "attendu 6+" in _first(stats)


def test_le_5_plus_du_waaagh_actif_est_correct_et_lu_dans_effects(tmp_path):
    stats = _stats(tmp_path, _WAAAGH_ON + _shot("103", "(30,40)", "103#0", "5+ AP-1 → 5+"))
    assert stats["save_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)
    # Et le 6+ imprimé sous Waaagh! actif est la faute inverse.
    bad = _stats(tmp_path, _WAAAGH_ON + _shot("103", "(30,40)", "103#0", "5+ AP-1 → 6+"))
    assert bad["save_threshold_mismatch"] == {1: 0, 2: 1} and "attendu 5+" in _first(bad)


def test_waaagh_actif_sans_cle_waaagh_invul_est_une_abstention(tmp_path):
    stats = _stats(tmp_path, _WAAAGH_ON_OLD + _shot("103", "(30,40)", "103#0", "5+ AP-1 → 5+"))
    assert stats["save_threshold_mismatch"] == {1: 0, 2: 0}
    assert stats["rule_usage"]["PROJ.2.3.save_threshold"][1] == 0, "non jugé, donc non exercé"


def test_le_5_plus_du_waaagh_banner_couvre_les_boyz_tant_que_le_bannernob_vit(tmp_path):
    stats = _stats(tmp_path, _shot("101", "(30,20)", "101#0", "5+ AP-1 → 5+"))
    assert stats["save_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)


def test_le_5_plus_sur_des_boyz_apres_la_mort_du_bannernob_est_une_faute(tmp_path):
    body = (
        "[10:00:02] E1 T1 P2 MOVE : Unit 101 DEAD model=101#2 reason=combat"
        " [MODELS: 101#0@(30,20,z0) 101#1@(31,20,z0)] [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P2 MOVE : Unit 101(30,21) MOVED from (30,20) to (30,21)"
        " [MODELS: 101#0@(30,21,z0) 101#1@(31,21,z0)] [R:+0.0] [SUCCESS]\n"
        + _shot("101", "(30,21)", "101#0", "5+ AP-1 → 5+", sec=4)
    )
    stats = _stats(tmp_path, body)
    assert stats["save_threshold_mismatch"] == {1: 0, 2: 1}, _first(stats)
    assert "attendu 6+" in _first(stats)


def test_mental_fortress_4_plus_couvre_l_intercessor_sous_forte_ap(tmp_path):
    ok = _stats(tmp_path, _shot("104", "(30,60)", "104#0", "3+ AP-3 → 4+"))
    assert ok["save_threshold_mismatch"] == {1: 0, 2: 0}, _first(ok)
    # Sv 3+ AP-1 = 4+ : l'armure vaut l'InSv, 4+ attendu ; un 3+ est une faute.
    bad = _stats(tmp_path, _shot("104", "(30,60)", "104#1", "3+ AP-1 → 3+"))
    assert bad["save_threshold_mismatch"] == {1: 0, 2: 1} and "attendu 4+" in _first(bad)


def test_une_sv_de_base_qui_n_est_pas_celle_de_la_datasheet_est_une_faute(tmp_path):
    stats = _stats(tmp_path, _shot("103", "(30,40)", "103#0", "4+ AP-1 → 5+"))
    assert stats["save_threshold_mismatch"] == {1: 0, 2: 1}
    assert "datasheet Boyz 5+" in _first(stats)
