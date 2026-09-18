"""`da_jump_invalid` (ai/analyzer_da_jump.py) — Da Jump, grammaire 13, journal FABRIQUÉ.

Escouade 1 (Boyz + WeirdBoy, P1) en (20,20), ennemi 101 (P2) en (60,60), plateau 100×100 à x1
(8" = 8 cases). Journal correct → 0 ; ingress à 8 cases ou moins d'un ennemi → 1 ; second Da
Jump du même tour → 1 ; MISCAST sans SUFFERS avant la phase suivante → 1 ; SUFFERS [DA JUMP] sans
MISCAST → 1 ; action de l'escouade hors table → 1 ; l'ingress au round 1 après REPOSITIONED n'est
PAS `reserves_too_early` ; dés du MISCAST contrôlés (`mw_ability_dice_mismatch`) ; grammaire 12 →
abstention.
"""
from __future__ import annotations

import pytest

from tests.unit.ai._fabriques import analyzer_config as fab_config
from tests.unit.ai._fabriques import entete_step_log

_OBJECTIVES = ";".join(f"(50,{r})" for r in range(50, 53))


class _Registry:
    units = {
        "Boyz": {"HP_MAX": 1, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "WeirdBoy": {"HP_MAX": 4, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "Intercessor": {"HP_MAX": 2, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }


_UNITS = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1"
    " [MODEL_TYPES: 1#0=Boyz 1#1=Boyz 1#2=WeirdBoy]\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (60,60), HP_MAX=2 base=round/1\n"
)
_SETUP = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(20,20) DEPLOYED from (-1,-1) to (20,20)"
    " [R:+0.0] [MODELS: 1#0@(20,20,z0) 1#1@(21,20,z0) 1#2@(22,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(60,60) DEPLOYED from (-1,-1) to (60,60)"
    " [R:+0.0] [MODELS: 101#0@(60,60,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 COMMAND : Unit 1(20,20) WAIT [R:+0.0] [SUCCESS]\n"
)
_MODELS_ON = " [MODELS: 1#0@(20,20,z0) 1#1@(21,20,z0) 1#2@(22,20,z0)]"


def _jump(sec: int, d6: int, outcome: str, turn: int = 1) -> str:
    return (
        f"[10:00:{sec:02d}] E1 T{turn} P1 MOVE : Unit 1(20,20) DA JUMP (D6={d6}) [{outcome}]"
        f"{_MODELS_ON} [R:+0.0] [SUCCESS]\n"
    )


def _ingress(sec: int, col: int, row: int, turn: int = 1) -> str:
    return (
        f"[10:00:{sec:02d}] E1 T{turn} P1 MOVE : Unit 1({col},{row}) DEPLOYED from (-1,-1) to ({col},{row})"
        f" [R:+0.0] [MODELS: 1#0@({col},{row},z0) 1#1@({col + 1},{row},z0) 1#2@({col + 2},{row},z0)] [SUCCESS]\n"
    )


def _suffers(sec: int, n: int, trigger: int = 1, mw: int | None = None) -> str:
    mw = n if mw is None else mw
    return (
        f"[10:00:{sec:02d}] E1 T1 P1 MOVE : Unit 1(20,20) SUFFERS {n} Mortal Wounds [DA JUMP]"
        f" Trigger:{trigger} MW:{mw} [FROM:1]{_MODELS_ON} [ALLOC_MODEL: 1#0] [R:+0.0] [SUCCESS]\n"
    )


def _shoot_phase(sec: int) -> str:
    """Fin de la phase de mouvement du joueur 1 : la phase suivante commence."""
    return f"[10:00:{sec:02d}] E1 T1 P1 CHARGE : Unit 1(20,20) WAIT{_MODELS_ON} [R:+0.0] [SUCCESS]\n"


def _move(sec: int) -> str:
    return (
        f"[10:00:{sec:02d}] E1 T1 P1 MOVE : Unit 1(23,20) MOVED from (20,20) to (23,20)"
        f" [R:+0.0] [MODELS: 1#0@(23,20,z0) 1#1@(24,20,z0) 1#2@(25,20,z0)] [SUCCESS]\n"
    )


def _stats(tmp_path, monkeypatch, body: str, *, log_grammar: int = 13) -> dict:
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_Registry(), unit_weapons_cache={},
        unit_is_monster_or_vehicle_by_type={"Boyz": False, "WeirdBoy": False, "Intercessor": False},
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _SETUP + body, inches_to_subhex=1, board="cols=100 rows=100", objectives=_OBJECTIVES,
        units=_UNITS, log_grammar=log_grammar, ez_vertical_inches=None,
    ))
    return an.parse_step_log(str(log))


def test_journal_correct_repositioned_puis_ingress_a_plus_de_8_pouces(tmp_path, monkeypatch):
    stats = _stats(tmp_path, monkeypatch, _jump(2, 4, "REPOSITIONED") + _ingress(3, 40, 40) + _shoot_phase(4))
    assert stats["da_jump_invalid"] == {1: 0, 2: 0}, stats["first_error_lines"]["da_jump_invalid"]
    assert stats["reserves_too_early"] == {1: 0, 2: 0}, "l'ingress au round 1 après Da Jump est légal"


def test_ingress_a_8_pouces_ou_moins_d_un_ennemi_est_une_erreur(tmp_path, monkeypatch):
    stats = _stats(tmp_path, monkeypatch, _jump(2, 4, "REPOSITIONED") + _ingress(3, 55, 60) + _shoot_phase(4))
    assert stats["da_jump_invalid"] == {1: 1, 2: 0}
    assert "plus de 8" in stats["first_error_lines"]["da_jump_invalid"][1]["detail"]


def test_second_da_jump_du_meme_tour_est_une_erreur(tmp_path, monkeypatch):
    body = _jump(2, 1, "MISCAST") + _suffers(3, 3) + _jump(4, 5, "REPOSITIONED") + _ingress(5, 40, 40) + _shoot_phase(6)
    stats = _stats(tmp_path, monkeypatch, body)
    assert stats["da_jump_invalid"] == {1: 1, 2: 0}
    assert "second Da Jump" in stats["first_error_lines"]["da_jump_invalid"][1]["detail"]


def test_failed_sans_suffers_avant_la_phase_suivante_est_une_erreur(tmp_path, monkeypatch):
    stats = _stats(tmp_path, monkeypatch, _jump(2, 1, "MISCAST") + _shoot_phase(3))
    assert stats["da_jump_invalid"] == {1: 1, 2: 0}
    assert "SUFFERS" in stats["first_error_lines"]["da_jump_invalid"][1]["detail"]


def test_suffers_da_jump_sans_failed_est_une_erreur(tmp_path, monkeypatch):
    stats = _stats(tmp_path, monkeypatch, _suffers(2, 2) + _shoot_phase(3))
    assert stats["da_jump_invalid"] == {1: 1, 2: 0}


def test_issue_incoherente_avec_le_d6_est_une_erreur(tmp_path, monkeypatch):
    stats = _stats(tmp_path, monkeypatch, _jump(2, 1, "REPOSITIONED") + _ingress(3, 40, 40) + _shoot_phase(4))
    assert stats["da_jump_invalid"] == {1: 1, 2: 0}
    assert "D6=1 mais issue" in stats["first_error_lines"]["da_jump_invalid"][1]["detail"]


def test_action_hors_table_avant_l_ingress_est_une_erreur(tmp_path, monkeypatch):
    stats = _stats(tmp_path, monkeypatch, _jump(2, 4, "REPOSITIONED") + _move(3) + _ingress(4, 40, 40) + _shoot_phase(5))
    assert stats["da_jump_invalid"] == {1: 1, 2: 0}
    assert "hors table" in stats["first_error_lines"]["da_jump_invalid"][1]["detail"] or \
        "réserves" in stats["first_error_lines"]["da_jump_invalid"][1]["detail"]


def test_les_des_du_failed_sont_controles(tmp_path, monkeypatch):
    """Trigger:1 + un D6 : `MW:` incohérent → `mw_ability_dice_mismatch` (compteur des dés 06.02)."""
    ok = _stats(tmp_path, monkeypatch, _jump(2, 1, "MISCAST") + _suffers(3, 3) + _shoot_phase(4))
    assert ok["mw_ability_dice_mismatch"] == {1: 0, 2: 0} and ok["da_jump_invalid"] == {1: 0, 2: 0}
    bad = _stats(tmp_path, monkeypatch, _jump(2, 1, "MISCAST") + _suffers(3, 5, mw=3) + _shoot_phase(4))
    assert bad["mw_ability_dice_mismatch"] == {1: 1, 2: 0}


def test_journal_anterieur_abstention(tmp_path, monkeypatch):
    stats = _stats(tmp_path, monkeypatch, _jump(2, 1, "MISCAST") + _shoot_phase(3), log_grammar=12)
    assert stats["da_jump_invalid"] == {1: 0, 2: 0}


def test_le_wait_d_une_escouade_en_reserves_est_le_refus_de_l_ingress_pas_une_faute(tmp_path, monkeypatch):
    """« This unit CAN then make an ingress move » : après REPOSITIONED, un WAIT hors table (ancre
    (-1,-1)) est le refus de l'ingress, et la phase peut se clore sans ingress — 0 faute.
    ROUGE avant le 2026-09-18 : mesuré sur un journal réel (E5 T3), 2 fautes inventées."""
    wait = (
        "[10:00:03] E1 T1 P1 MOVE : Unit 1(-1,-1) WAIT [MODELS: 1#0@(-1,-1,z0) 1#1@(-1,-1,z0) 1#2@(-1,-1,z0)]"
        " [R:+0.0] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, monkeypatch, _jump(2, 4, "REPOSITIONED") + wait + _shoot_phase(4))
    assert stats["da_jump_invalid"] == {1: 0, 2: 0}, stats["first_error_lines"]["da_jump_invalid"]
