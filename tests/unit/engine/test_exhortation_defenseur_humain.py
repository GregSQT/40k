"""Exhortation of Rage sur un DÉFENSEUR HUMAIN — le choix des pertes lui revient (06.02).

06.02 : « Each time a unit suffers one or more mortal wounds, its controlling player must
resolve the following sequence for each of those mortal wounds … you must select one of those
models ». Avant ce lot, `_apply_exhortation_de_rage` attribuait toujours en AUTO
(`allocate_mortal_wounds(…, True, …)`, `eligibles[0]`), même quand la cible appartenait à un
humain — alors que Desperate Escape et [HAZARDOUS] lui laissaient le choix.

Chemin verrouillé, sur un MOTEUR RÉEL (allocation HAZARD_CTX réelle, pas de stub) :
  _apply_exhortation_de_rage (défenseur humain, 2 BM sur une escouade de 2 figurines intactes)
  → build_manual_hazard_allocation → payload d'attente `squad_hazard_manual_alloc`
  → _process_squad_action (une action de politique pendant l'attente) → même payload, rien ne bouge
  → _handle_hazard_allocate_model × 2 (clics du défenseur)
  → _resume_after_hazard (origine `exhortation`) → _continue_fight_after_exhortation.
"""
from __future__ import annotations

import random
from typing import Any, Dict

from engine.constants import PENDING_HAZARD_ALLOCATION_KEY
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)

_EXHORT_RULE = {
    "ruleId": "mortal_wounds_on_fight_activation",
    "displayName": "Exhortation of Rage",
    "rule_args": {"mw_on_6": 3},
}


def _defender_cfg(uid: int, player: int) -> Dict[str, Any]:
    base = _unit_cfg(uid, player, 21, 20)
    base["HP_CUR"] = 3
    base["HP_MAX"] = 3
    base["models"] = [
        {"col": 21, "row": 20, "VALUE": 50},
        {"col": 22, "row": 20, "VALUE": 50},
    ]
    return base


def _engine(defender_seat: str) -> W40KEngine:
    attacker = _unit_cfg(1, 1, 20, 20)
    attacker["UNIT_RULES"] = [_EXHORT_RULE]
    eng = _make_engine(_base_config([attacker, _defender_cfg(2, 2)]))
    gs = eng.game_state
    # Le helper boote en `gym_training_mode` (tout camp est machine pour `is_programmatic_owner`) ;
    # l'état visé est une partie servie par l'API, attaquant machine, défenseur `defender_seat`.
    gs["gym_training_mode"] = False
    gs["player_types"] = {"1": "ai", "2": defender_seat}
    gs["phase"] = "fight"
    return eng


def _spy_continue(eng: W40KEngine, calls: list) -> None:
    eng._continue_fight_after_exhortation = (  # type: ignore[method-assign]
        lambda squad_id, target_slot, regime: calls.append((squad_id, target_slot, regime))
        or (True, {"action": "squad_fight", "squad_id": squad_id, "resumed": True})
    )


def test_le_defenseur_humain_choisit_puis_le_combat_reprend(monkeypatch):
    """ROUGE avant le fix : `allocate_mortal_wounds` AUTO, aucun payload, aucune attente."""
    eng = _engine("human")
    gs = eng.game_state
    calls: list = []
    _spy_continue(eng, calls)
    # D6 = 4 (déclenche), D3 = 2 : deux blessures mortelles à attribuer.
    rolls = iter([4, 2])
    monkeypatch.setattr(random, "randint", lambda a, b: next(rolls))

    ok, result = eng._apply_exhortation_de_rage("1", "2", 3, auto=True)
    assert ok is True
    assert result.get("waiting_for_player") is True, result
    assert result["action"] == "squad_hazard_manual_alloc", result
    assert result["allocation"]["damage_type"] == "mortal", result["allocation"]
    assert {c["model_id"] for c in result["allocation"]["choices"]} == {"2#0", "2#1"}
    assert calls == [], "le combat ne doit pas reprendre avant la fin de l'attribution"
    assert gs["hazard_origin"] == "exhortation"
    assert gs["_pending_exhortation_resume"] == {"squad_id": "1", "target_slot": 3, "regime": "gym"}
    # La ligne SUFFERS est DÉJÀ émise, sans détail d'attribution pour l'instant.
    mw_logs = [e for e in gs["action_logs"] if e["type"] == "mortal_wounds_ability"]
    assert len(mw_logs) == 1 and mw_logs[0]["hazardousMortalWounds"] == 2, mw_logs
    assert mw_logs[0]["hazardDetails"] == []

    # Une action de POLITIQUE pendant l'attente (le client relance un tour IA) : rien ne bouge,
    # le même payload est rendu. Sans ce garde, `_build_manual_allocation` écraserait
    # l'allocation en cours.
    ok, again = eng._process_squad_action({"action": "squad_wait", "unitId": "1"})
    assert ok is True and again["action"] == "squad_hazard_manual_alloc", again
    assert PENDING_HAZARD_ALLOCATION_KEY in gs
    assert calls == []

    # Le défenseur clique 2#1 : première blessure, puis la seconde est FORCÉE sur la figurine
    # entamée (06.02, « If a non-CHARACTER model in that unit has lost one or more wounds, you
    # must select that model »).
    ok, r1 = eng._handle_hazard_allocate_model({"modelId": "2#1"})
    assert ok is True
    assert r1.get("resumed") is True, r1
    assert calls == [("1", 3, "gym")], "le combat de l'attaquant reprend à la fin de l'attribution"
    assert gs["models_cache"]["2#1"]["HP_CUR"] == 1, "2#1 devait encaisser les deux BM"
    assert gs["models_cache"]["2#0"]["HP_CUR"] == 3, "2#0 n'a pas été choisie"
    assert PENDING_HAZARD_ALLOCATION_KEY not in gs
    assert "hazard_origin" not in gs and "_pending_exhortation_resume" not in gs
    assert [d["modelId"] for d in mw_logs[0]["hazardDetails"]] == ["2#1", "2#1"]


def test_le_defenseur_machine_garde_le_regime_auto(monkeypatch):
    """VERT VACANT : défenseur programmatique → attribution AUTO immédiate, combat repris tout
    de suite, aucune allocation en attente."""
    eng = _engine("ai")
    gs = eng.game_state
    calls: list = []
    _spy_continue(eng, calls)
    rolls = iter([4, 2])
    monkeypatch.setattr(random, "randint", lambda a, b: next(rolls))

    ok, result = eng._apply_exhortation_de_rage("1", "2", None, auto=True)
    assert ok is True and result.get("resumed") is True, result
    assert calls == [("1", None, "gym")]
    assert PENDING_HAZARD_ALLOCATION_KEY not in gs
    assert "hazard_origin" not in gs
    hp = sorted(gs["models_cache"][m]["HP_CUR"] for m in ("2#0", "2#1"))
    assert hp == [1, 3], f"2 BM sur une seule figurine (eligibles[0], puis entamée forcée) : {hp}"


def test_un_jet_rate_ne_rend_pas_la_main(monkeypatch):
    """0 blessure : rien à attribuer, pas d'attente même pour un défenseur humain."""
    eng = _engine("human")
    calls: list = []
    _spy_continue(eng, calls)
    monkeypatch.setattr(random, "randint", lambda a, b: 2)
    ok, result = eng._apply_exhortation_de_rage("1", "2", None, auto=True)
    assert ok is True and result.get("resumed") is True, result
    assert PENDING_HAZARD_ALLOCATION_KEY not in eng.game_state


def test_le_reset_purge_l_etat_de_reprise_en_attente(monkeypatch):
    """Finding /code-review : un reset pendant l'attribution humaine laissait `hazard_origin` à
    `exhortation` — le prochain Desperate Escape aurait repris un combat de l'épisode précédent
    au lieu du preview Fall Back."""
    eng = _engine("human")
    gs = eng.game_state
    _spy_continue(eng, [])
    rolls = iter([4, 2])
    real_randint = random.randint
    # D6 puis D3 forcés ; le reset qui suit tire ses propres dés, rendus au vrai `randint`.
    monkeypatch.setattr(random, "randint", lambda a, b: next(rolls, None) or real_randint(a, b))
    ok, result = eng._apply_exhortation_de_rage("1", "2", None, auto=True)
    assert ok and result.get("waiting_for_player") is True
    assert gs["hazard_origin"] == "exhortation" and "_pending_exhortation_resume" in gs

    eng.reset()
    gs = eng.game_state
    assert "hazard_origin" not in gs
    assert "_pending_exhortation_resume" not in gs
    assert "_pending_exhortation_fight" not in gs
    assert PENDING_HAZARD_ALLOCATION_KEY not in gs
