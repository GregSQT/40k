"""Ligne `RETURNED` (Grot Orderly, grammaire 10) — lecteur de l'analyzer.

Avant cette ligne, une figurine rendue n'existait pour l'analyzer qu'au détour du `[MODELS:]`
d'une ligne suivante, sous un id `<escouade>#r<n>` d'où aucune datasheet ne se déduisait :
PV pleins de l'ESCOUADE au lieu de la figurine, et abstention de tout verdict 19.04
(`living_datasheets`) pour l'escouade entière.

Ce que ce fichier verrouille :
- la datasheet du socle rendu est absorbée AVANT le recalage des socles vivants, donc le socle
  entre à SES PV pleins (PainBoy : 3, pas 1) ;
- l'usage §1.7 de `return_destroyed_models` est relevé sur l'escouade ;
- la restitution est une mise en place : 03.03 (coherency) s'y juge ;
- en grammaire 10, un id `#r` vu dans `[MODELS:]` sans ligne `RETURNED` est une panne du
  producteur ; en grammaire antérieure, rien n'est inventé ;
- une ligne qui annonce k figurines et en déclare j ≠ k est une erreur de format.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai._fabriques import analyzer_config as fab_config

_OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))


class _Registry:
    units = {
        "Boyz": {"HP_MAX": 1, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "PainBoy": {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "Grunt": {"HP_MAX": 5, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }


_UNITS = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1 "
    "[MODELS: 1#0@(20,20,z0) 1#1@(20,21,z0)] [MODEL_TYPES: 1#0=Boyz 1#1=PainBoy]\n"
    "[10:00:00] Unit 101 (Grunt) P2: Starting position (21,21), HP_MAX=5 base=round/1\n"
)
_PAINBOY_MORT = (
    "[10:00:01] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#1 reason=combat "
    "[MODELS: 1#0@(20,20,z0)] [SUCCESS]\n"
)


def _returned(types: str, models: str, count: int = 1) -> str:
    return (
        f"[10:00:02] E1 T2 P1 COMMAND : Unit 1(20,20) RETURNED {count} models [GROT ORDERLY] (D3=1) "
        f"[MODEL_TYPES: {types}] [MODELS: {models}] [SUCCESS]\n"
    )


#: Blessure mortelle sur l'escouade 1 : la ligne nomme le socle alloué, dont on lit les PV.
def _mw_sur_socle(mid: str, n: int) -> str:
    return (
        f"[10:00:03] E1 T2 P2 FIGHT : Unit 1(20,20) SUFFERS {n} Mortal Wounds [DESPERATE ESCAPE] "
        f"[ALLOC_MODEL: {mid}] [R:+0.0] [SUCCESS]\n"
    )


def _parse(tmp_path, monkeypatch, body: str, *, log_grammar=10):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_Registry(), unit_weapons_cache={},
        rule_to_units={"return_destroyed_models": {"PainBoy"}},
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body, inches_to_subhex=1, board="cols=40 rows=40", objectives=_OBJECTIVES,
        units=_UNITS, log_grammar=log_grammar,
    ))
    return an.parse_step_log(str(log))


def test_la_ligne_est_lue_et_l_usage_releve(tmp_path, monkeypatch):
    """ROUGE avant le fix : la ligne tombait dans `other`, rien n'était compté."""
    stats = _parse(tmp_path, monkeypatch, _PAINBOY_MORT + _returned("1#r0=PainBoy", "1#0@(20,20,z0) 1#r0@(20,21,z0)"))
    assert not stats["parse_errors"], stats["parse_errors"]
    assert stats["returned_models"][1] == 1
    assert stats["actions_by_type"]["returned_models"] == 1
    assert stats["special_rule_usage"][("return_destroyed_models", "Boyz")][1] == 1


def test_le_socle_rendu_entre_a_ses_pv_pleins_de_datasheet(tmp_path, monkeypatch):
    """Le PainBoy rendu a 3 PV (sa datasheet), pas 1 (l'escouade Boyz) : deux blessures
    mortelles allouées sur lui ne le tuent pas."""
    stats = _parse(
        tmp_path, monkeypatch,
        _PAINBOY_MORT + _returned("1#r0=PainBoy", "1#0@(20,20,z0) 1#r0@(20,21,z0)")
        + _mw_sur_socle("1#r0", 2),
    )
    assert not stats["parse_errors"], stats["parse_errors"]
    assert not stats["current_episode_deaths"], "le PainBoy rendu (3 PV) ne meurt pas de 2 BM"


def test_un_socle_rendu_non_declare_est_une_panne_en_grammaire_10(tmp_path, monkeypatch):
    """Sans ligne RETURNED, un `#r` dans [MODELS:] est une panne du producteur — mais seulement
    à partir de la grammaire qui le garantit."""
    body = (
        "[10:00:02] E1 T2 P1 MOVE : Unit 1(20,20) MOVED from (20,20) to (20,20) "
        "[MODELS: 1#0@(20,20,z0) 1#r0@(20,21,z0)] [R:+0.0] [SUCCESS]\n"
    )
    stats = _parse(tmp_path, monkeypatch, body, log_grammar=10)
    assert any("socle rendu 1#r0" in e["error"] for e in stats["parse_errors"]), stats["parse_errors"]
    stats = _parse(tmp_path, monkeypatch, body, log_grammar=9)
    assert not any("socle rendu" in e["error"] for e in stats["parse_errors"]), stats["parse_errors"]


def test_compte_et_datasheets_doivent_concorder(tmp_path, monkeypatch):
    body = _returned("1#r0=PainBoy", "1#0@(20,20,z0) 1#r0@(20,21,z0) 1#r1@(20,22,z0)", count=2)
    stats = _parse(tmp_path, monkeypatch, body)
    assert any("2 figurine(s) annoncee(s), 1 datasheet(s)" in e["error"] for e in stats["parse_errors"]), stats["parse_errors"]


def test_la_restitution_est_jugee_en_coherence(tmp_path, monkeypatch):
    """25 Rules appendix (Revived) : « must be set up … In coherency ». Un socle rendu posé
    loin de l'escouade est une formation fautive, comme après tout déplacement."""
    stats = _parse(tmp_path, monkeypatch, _returned("1#r0=Boyz", "1#0@(20,20,z0) 1#r0@(35,35,z0)"))
    assert stats["squad_coherency_violations"][1] == 1, stats["first_error_lines"]["squad_coherency_violations"]
    stats = _parse(tmp_path, monkeypatch, _returned("1#r0=Boyz", "1#0@(20,20,z0) 1#r0@(20,21,z0)"))
    assert stats["squad_coherency_violations"][1] == 0
