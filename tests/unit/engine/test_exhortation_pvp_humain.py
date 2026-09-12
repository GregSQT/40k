"""Exhortation of Rage pour un Chaplain HUMAIN — PvP hot-seat et siège humain PvE.

Datasheet (`Datasheets - Space Marines.pdf`, Chaplain with Jump Pack) : « In the Fight phase,
when this unit is selected to fight, you can select one enemy unit it is engaged with and roll
one D6, and on a result of: 4-5: That enemy unit suffers D3 mortal wounds. 6: That enemy unit
suffers 3 mortal wounds. »

Avant ce lot, le seul site qui jouait ce dé était `_process_squad_action` (gym / politique) :
le flux manuel (`_fight_v11_manual_step`) enregistrait la sélection 12.04 sans jamais rouler
le D6 — un Chaplain humain ne l'appliquait jamais. Et `_continue_fight_after_exhortation` ne connaissait que la reprise gym, qui lève
« combat à vide … pool non vide » sans slot de cible.

Chemins verrouillés, sur un MOTEUR RÉEL, par `execute_semantic_action` (LE point d'entrée du
frontend) :
  PvP, ≥ 2 ennemis engagés : activate_unit → décision `mortal_wounds_target` posée AVANT tout
    dé → toute autre action refusée (inerte) → agent_decision → D6 → attribution par le
    DÉFENSEUR humain (HAZARD_CTX) → reprise MANUELLE : l'unité reste active, non enregistrée,
    et déclare ses attaques contre les survivants ; verrou d'activation ; un seul dé par phase.
  PvP, 1 ennemi engagé : jet immédiat à l'activation, sans décision.
  PvE, siège humain : MÊME machine manuelle (décision, dé, reprise) ; le défenseur bot se voit
    attribuer les blessures mortelles headless (06.02, siège machine).
"""
from __future__ import annotations

import random
from typing import Any, Dict, List

from engine.phase_handlers.fight_handlers import (
    EXHORTATION_REGIME_GYM,
    FIGHT_SELECTION_EXHORTATION_KEY,
    fight_v11_enter_fight_step,
    fight_v11_start,
)
from engine.game_utils import require_unit_by_id
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


def _two_model_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    base = _unit_cfg(uid, player, col, row)
    base["HP_CUR"] = 3
    base["HP_MAX"] = 3
    base["models"] = [
        {"col": col, "row": row, "VALUE": 50},
        {"col": col + 1, "row": row, "VALUE": 50},
    ]
    return base


def _engine(mode: str, seat2: str, units: List[Dict[str, Any]]) -> W40KEngine:
    eng = _make_engine(_base_config(units))
    gs = eng.game_state
    # Le helper boote en `gym_training_mode` ; l'état visé est une partie servie par l'API.
    gs["gym_training_mode"] = False
    gs["player_types"] = {"1": "human", "2": seat2}
    gs["current_mode_code"] = mode
    eng.current_mode_code = mode
    gs["current_player"] = 1
    gs["phase"] = "fight"
    fight_v11_start(gs)
    fight_v11_enter_fight_step(gs)
    return eng


def _mw_lines(gs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e for e in gs["action_logs"] if e["type"] == "mortal_wounds_ability"]


def _chaplain(uid: int = 1, col: int = 20, row: int = 20) -> Dict[str, Any]:
    chap = _unit_cfg(uid, 1, col, row)
    chap["UNIT_RULES"] = [_EXHORT_RULE]
    return chap


# ---------------------------------------------------------------------------
# PvP hot-seat, deux ennemis engagés : décision, refus, dé, attribution, reprise manuelle
# ---------------------------------------------------------------------------

def test_pvp_deux_ennemis_le_joueur_choisit_puis_le_defenseur_attribue(monkeypatch):
    """ROUGE avant le fix : aucune décision, aucune ligne `mortal_wounds_ability`."""
    eng = _engine("pvp", "human", [
        _chaplain(),
        _two_model_cfg(2, 2, 21, 20),   # engagé (adjacent), 2 figurines de 3 PV
        _two_model_cfg(3, 2, 20, 21),   # engagé aussi
        _unit_cfg(4, 1, 40, 40),        # autre unité de P1, loin de tout
    ])
    gs = eng.game_state

    def _no_roll(a, b):
        raise AssertionError("aucun dé avant le choix de la cible")
    monkeypatch.setattr(random, "randint", _no_roll)

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True, out
    assert out.get("waiting_for_agent_decision") is True, out
    assert out.get("decision_type") == "mortal_wounds_target", out
    pending = gs["pending_agent_decision"]
    assert pending is not None and pending["type"] == "mortal_wounds_target", pending
    assert pending["player"] == 1 and pending["unit_id"] == "1"
    assert {o["payload"]["target_eid"] for o in pending["options"]} == {"2", "3"}
    assert gs["_pending_exhortation_fight"]["regime"] == "manual"
    assert FIGHT_SELECTION_EXHORTATION_KEY not in gs, "l'armement doit être consommé dans la requête"
    assert gs["active_fight_unit"] == "1"
    assert "1" not in gs["units_selected_to_fight"], "sélectionnée mais n'a pas encore combattu"
    assert _mw_lines(gs) == []

    # Décision posée → toute autre action est refusée, INERTE (advance_phase compris : il est
    # intercepté avant le dispatch de phase et terminerait la phase avec la décision posée).
    for blocked in (
        {"action": "advance_phase", "from": "fight"},
        {"action": "squad_fight_validate", "unitId": "1"},
        {"action": "activate_unit", "unitId": "4"},
    ):
        ok, out = eng.execute_semantic_action(blocked)
        assert ok is False and out["error"] == "mortal_wounds_target_pending", (blocked, out)
    assert gs["phase"] == "fight" and gs["active_fight_unit"] == "1"
    assert gs["pending_agent_decision"]["type"] == "mortal_wounds_target"

    # Cible 2 choisie ; D6 = 4 (déclenche), D3 = 2 : deux blessures mortelles.
    rolls = iter([4, 2])
    monkeypatch.setattr(random, "randint", lambda a, b: next(rolls))
    ok, out = eng.execute_semantic_action({"action": "agent_decision", "option_index": 0})
    assert ok is True, out
    assert gs["pending_agent_decision"] is None
    assert gs.get("_pending_exhortation_fight") is None
    lines = _mw_lines(gs)
    assert len(lines) == 1 and lines[0]["hazardousMortalWounds"] == 2, lines
    assert lines[0]["unitId"] == "2" and lines[0]["mortalWoundSourceId"] == "1"
    # Défenseur HUMAIN (06.02) : c'est lui qui choisit la figurine, par l'attribution HAZARD_CTX.
    assert out.get("waiting_for_player") is True and out["action"] == "squad_hazard_manual_alloc", out
    assert {c["model_id"] for c in out["allocation"]["choices"]} == {"2#0", "2#1"}
    assert gs["hazard_origin"] == "exhortation"
    assert gs["_pending_exhortation_resume"]["regime"] == "manual"

    # Clic du défenseur sur 2#0 ; la seconde blessure va d'office à la figurine déjà entamée
    # (06.02), donc l'attribution se termine sur ce seul clic.
    ok, out = eng.execute_semantic_action({"action": "squad_hazard_allocate_model", "unitId": "2", "modelId": "2#0"})
    assert ok is True, out
    assert gs["models_cache"]["2#0"]["HP_CUR"] == 1
    assert gs.get("hazard_origin") is None and gs.get("_pending_exhortation_resume") is None

    # Reprise MANUELLE : le Chaplain est toujours l'unité active, ses cibles lui sont présentées,
    # il n'est pas enregistré (il n'a pas encore combattu) — pas la continuation gym.
    assert out["action"] == "wait" and out["fight_subphase"] == "fight", out
    assert out["active_fight_unit"] == "1"
    assert set(out["valid_targets"]) == {"2", "3"}
    assert "1" not in gs["units_selected_to_fight"]
    assert gs["fight_exhortation_done"] == {"1"}

    # Verrou 12.04 : le dé joué, le joueur ne peut plus lui préférer une autre unité.
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "4"})
    assert ok is True and gs["active_fight_unit"] == "1", out
    # Une ré-activation du Chaplain ne rejoue pas le dé.
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and gs["pending_agent_decision"] is None and len(_mw_lines(gs)) == 1

    # Il combat : clic-cible → allocation manuelle des pertes par le défenseur (flux existant),
    # et c'est LÀ qu'il est enregistré « selected to fight ».
    real_randint = random.Random(7).randint
    monkeypatch.setattr(random, "randint", real_randint)
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "3"})
    assert ok is True, out
    assert "1" in gs["units_selected_to_fight"]
    assert len(_mw_lines(gs)) == 1


# ---------------------------------------------------------------------------
# PvP hot-seat, un seul ennemi engagé : jet immédiat, figurine forcée, reprise manuelle
# ---------------------------------------------------------------------------

def test_pvp_un_seul_ennemi_jet_immediat_a_l_activation(monkeypatch):
    eng = _engine("pvp", "human", [
        _chaplain(),
        _unit_cfg(2, 2, 21, 20),  # mono-figurine, 5 PV
    ])
    gs = eng.game_state
    monkeypatch.setattr(random, "randint", lambda a, b: 6)  # 6 : 3 blessures mortelles

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True, out
    assert gs["pending_agent_decision"] is None, "cible unique : aucune décision à poser"
    lines = _mw_lines(gs)
    assert len(lines) == 1 and lines[0]["hazardousMortalWounds"] == 3, lines
    assert lines[0]["unitId"] == "2" and lines[0]["abilityTriggerRoll"] == 6
    # Défenseur humain : premier clic sur l'unique figurine, les deux autres blessures vont
    # d'office à la figurine entamée (06.02).
    assert out["action"] == "squad_hazard_manual_alloc" and out["waiting_for_player"] is True, out
    ok, out = eng.execute_semantic_action({"action": "squad_hazard_allocate_model", "unitId": "2", "modelId": "2#0"})
    assert ok is True, out
    assert gs["models_cache"]["2#0"]["HP_CUR"] == 2
    assert out["action"] == "wait" and out["active_fight_unit"] == "1", out
    assert out["valid_targets"] == ["2"]
    assert "1" not in gs["units_selected_to_fight"]


def test_pvp_sans_regle_rien_ne_change(monkeypatch):
    eng = _engine("pvp", "human", [_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)])
    gs = eng.game_state
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["active_fight_unit"] == "1", out
    assert _mw_lines(gs) == [] and gs["pending_agent_decision"] is None
    assert gs["fight_exhortation_done"] == set()


# ---------------------------------------------------------------------------
# PvE, siège HUMAIN : même machine manuelle qu'en PvP (12.04 : c'est le joueur qui sélectionne).
# Le défenseur est le bot : les blessures mortelles lui sont attribuées headless (06.02, siège
# machine), puis le Chaplain reste actif et déclare ses attaques comme en PvP.
# ---------------------------------------------------------------------------

def test_pve_siege_humain_meme_decision_et_meme_reprise_qu_en_pvp(monkeypatch):
    """ROUGE si le siège humain PvE est résolu en auto : aucune décision posée, cible et attaques
    tranchées par le moteur dans la même requête."""
    eng = _engine("pve", "ai", [
        _chaplain(),
        _two_model_cfg(2, 2, 21, 20),
        _unit_cfg(3, 2, 20, 21),
    ])
    gs = eng.game_state

    def _no_roll(a, b):
        raise AssertionError("aucun dé avant le choix de la cible")
    monkeypatch.setattr(random, "randint", _no_roll)

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True, out
    assert out.get("waiting_for_agent_decision") is True and out.get("decision_type") == "mortal_wounds_target", out
    pending = gs["pending_agent_decision"]
    assert pending is not None and pending["player"] == 1 and pending["unit_id"] == "1", pending
    assert gs["_pending_exhortation_fight"]["regime"] == "manual"
    assert gs["active_fight_unit"] == "1" and "1" not in gs["units_selected_to_fight"]
    assert _mw_lines(gs) == []

    # Cible 2 (deux figurines de 3 PV) ; D6 = 6 : trois blessures mortelles, attribuées par le
    # défenseur MACHINE sans rendre la main (figurine forcée, 06.02 siège programmatique).
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    ok, out = eng.execute_semantic_action({"action": "agent_decision", "option_index": 0})
    assert ok is True, out
    assert gs["pending_agent_decision"] is None
    lines = _mw_lines(gs)
    assert len(lines) == 1 and lines[0]["hazardousMortalWounds"] == 3, lines
    assert lines[0]["unitId"] == "2" and lines[0]["mortalWoundSourceId"] == "1"
    assert out.get("waiting_for_player") is True and out["action"] == "wait", out
    assert gs.get("hazard_origin") is None and gs.get("_pending_exhortation_resume") is None
    # 3 blessures sur 2 figurines de 3 PV : une détruite, l'autre intacte.
    hp = sorted(gs["models_cache"][m]["HP_CUR"] for m in ("2#0", "2#1") if m in gs["models_cache"])
    assert hp == [3], hp

    # Reprise MANUELLE : le Chaplain reste actif, ses cibles lui sont présentées, il n'est pas
    # enregistré — il n'a pas encore combattu.
    assert out["fight_subphase"] == "fight" and out["active_fight_unit"] == "1"
    # La figurine survivante de 2 (col 22) n'est plus au contact : seule 3 reste engagée.
    assert out["valid_targets"] == ["3"]
    assert "1" not in gs["units_selected_to_fight"]
    assert gs["fight_exhortation_done"] == {"1"}
    assert FIGHT_SELECTION_EXHORTATION_KEY not in gs

    # Il combat par clic-cible : défenseur machine → pertes allouées headless dans la requête,
    # et c'est LÀ qu'il est enregistré « selected to fight ».
    monkeypatch.setattr(random, "randint", random.Random(7).randint)
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "3"})
    assert ok is True, out
    assert out.get("waiting_for_player") is True and out["action"] == "wait", out
    assert "1" in gs["units_selected_to_fight"]
    assert len(_mw_lines(gs)) == 1


# ---------------------------------------------------------------------------
# PvE, Chaplain du siège IA (régime gym, `_process_squad_action`) : personne ne répondrait à la
# décision — le sélecteur 12.04 est déjà passé à l'humain, `execute_ai_turn` refuse et le front
# ne relance pas le bot. Tranchée immédiatement, comme le mouvement réactif.
# ---------------------------------------------------------------------------

def test_pve_siege_ia_la_decision_est_tranchee_sur_le_champ(monkeypatch):
    """ROUGE avant le fix : `pending_agent_decision` posée au siège IA et jamais résolue ; toute
    action humaine refusée (`mortal_wounds_target_pending`)."""
    chap = _unit_cfg(5, 2, 20, 20)
    chap["UNIT_RULES"] = [_EXHORT_RULE]
    eng = _engine("pve", "ai", [
        chap,
        _unit_cfg(2, 1, 21, 20),
        _unit_cfg(3, 1, 20, 21),
    ])
    gs = eng.game_state
    eng.gym_training_mode = False
    import engine.phase_handlers.fight_handlers as fh
    monkeypatch.setattr(fh, "_ai_select_fight_target", lambda gs_, uid, targets: "3")
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    resumed: List[Any] = []
    eng._continue_fight_after_exhortation = (  # type: ignore[method-assign]
        lambda squad_id, target_slot, regime: resumed.append((squad_id, target_slot, regime))
        or (True, {"action": "squad_fight", "squad_id": squad_id})
    )

    result = eng._check_and_trigger_exhortation_de_rage(
        "5", require_unit_by_id(gs, "5"), 1, regime=EXHORTATION_REGIME_GYM
    )
    assert result is not None
    ok, out = result
    assert ok is True, out
    assert gs["pending_agent_decision"] is None, "siège IA hors gym : rien ne doit rester posé"
    assert gs.get("_pending_exhortation_fight") is None
    lines = _mw_lines(gs)
    assert len(lines) == 1 and lines[0]["unitId"] == "3" and lines[0]["hazardousMortalWounds"] == 3
    # Défenseur HUMAIN : l'attribution lui revient (HAZARD_CTX), puis la reprise GYM du bot.
    assert out["action"] == "squad_hazard_manual_alloc" and out["waiting_for_player"] is True, out
    ok, out = eng.execute_semantic_action({"action": "squad_hazard_allocate_model", "unitId": "3", "modelId": "3#0"})
    assert ok is True, out
    assert resumed == [("5", 1, "gym")]
    # Une action humaine n'est plus refusée : la décision n'existe plus.
    assert eng._reject_action_while_exhortation_pending({"action": "activate_unit"}) is None
