"""Da Jump (WeirdBoy, Datasheets - Orks p5) — appel de capacité de la phase de mouvement.

« Da Jump (Psychic, once per turn, per army): In your Movement phase, you can roll 1 D6 and on a
result of: 1: This unit suffers D6 mortal wounds. 2-6: Place this unit in strategic reserves and it
gains Deep Strike until the end of the phase. This unit can then make an ingress move (Including
during the first battle round). »

Moteur RÉEL (`load_engine_from_scenario`, datasheets Armageddon) : une escouade de Boyz menée par
un WeirdBoy inline (19.04), un Intercessor adverse. Ce que ces tests verrouillent :
  - l'appel est posé au début de la phase de mouvement, seulement si le WeirdBoy vit et si l'armée
    n'a pas encore jeté ce tour ; passer ne consomme rien ;
  - 1 → D6 blessures mortelles PSYCHIC sur l'escouade elle-même (Psychic Hood 4+ joue sur un
    porteur fabriqué de `feel_no_pain_vs_psychic`) ;
  - 2-6 → hors table, Deep Strike accordé (registre, pas les UNIT_RULES), ingress dans la MÊME
    phase dès le round 1, à plus de 8" de tout ennemi, zone adverse permise ; grant éteint à la
    phase suivante ; pas de destruction en fin de round 3 ; second Da Jump du tour refusé ; 20.02
    clause 2 : une escouade qui avait Advance ne charge pas après l'ingress ;
  - obs_size et TOTAL_ACTION_SIZE inchangés (la capacité n'ouvre ni colonne ni action).
"""
from __future__ import annotations

import random
from typing import Any, Dict, List

import pytest

from engine.agent_decision import read_pending_agent_decision
from engine.macro_intents import CHOICE_BASE, DEPLOY_SLOTS, TOTAL_ACTION_SIZE
from engine.phase_handlers import movement_handlers as mh
from engine.phase_handlers.shared_utils import destroy_model, unit_is_in_strategic_reserves
from tests.unit.engine._config_helpers import load_engine_from_scenario

_OVERRIDES = {"controlled_agent": "ArmageddonAgent_x1", "rewards_config": "ArmageddonAgent_x1"}

#: Plateau 44x60 à x5 = 220 × 300 cases, terrain mc1 (objectifs + zones de déploiement de la
#: carte de mission : joueur 1 en haut, joueur 2 en bas). Boyz en (30,50) dans la zone du joueur
#: 1, Intercessor en (110,290) dans celle du joueur 2 — à plus de 12" (60 cases) l'un de l'autre ;
#: l'ingress exige > 8" = 40 cases de tout ennemi.
def _scenario() -> Dict[str, Any]:
    return {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "terrain_ref": "terrain-mc1.json",
        "army_faction": {"1": "ORKS", "2": "ADEPTUS ASTARTES"},
        "uses_codex_detachment": {"1": False, "2": False},
        "units": [
            {
                "id": 1, "unit_type": "Boyz", "player": 1, "col": 30, "row": 50,
                "models": [
                    {"col": 30, "row": 50}, {"col": 31, "row": 50},
                    {"unit_type": "WeirdBoy", "col": 32, "row": 50},
                ],
            },
            {"id": 101, "unit_type": "Intercessor", "player": 2, "col": 110, "row": 290,
             "models": [{"col": 110, "row": 290}]},
        ],
    }


def _engine(gym: bool = True):
    eng = load_engine_from_scenario(_scenario(), **_OVERRIDES)
    gs = eng.game_state
    if not gym:
        eng.gym_training_mode = False
        gs["gym_training_mode"] = False
        gs["config"]["gym_training_mode"] = False
    return eng


def _weirdboy_mid(gs) -> str:
    return next(m for m in gs["squad_models"]["1"] if gs["models_cache"][m].get("unitType") == "WeirdBoy")


def _start_move_phase(eng) -> Dict[str, Any]:
    """Du reset à la phase de mouvement du joueur 1, comme en partie : le Waaagh! (08.04) est
    décliné, la phase de commandement reprend, la phase de mouvement s'ouvre et l'appel Da Jump
    est posé puis SERVI dans la même réponse (`_serve_queued_prompts_after_decision`)."""
    gs = eng.game_state
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "waaagh_call", decision
    ok, result = _answer(eng, 1)  # ne pas appeler le Waaagh!
    assert ok is True and gs["phase"] == "move", (result, gs["phase"])
    return result


def _answer(eng, slot: int):
    return eng._process_squad_action(eng.action_decoder.convert_squad_action(CHOICE_BASE + slot, eng.game_state))


# ─────────────────────────────────────────────────────────────────────────────
# Pose de l'appel
# ─────────────────────────────────────────────────────────────────────────────


def test_l_appel_est_pose_au_debut_de_la_phase_si_le_weirdboy_vit():
    eng = _engine()
    result = _start_move_phase(eng)
    assert result.get("action") == "waiting_for_agent_decision"
    decision = read_pending_agent_decision(eng.game_state)
    assert decision is not None and decision["type"] == "rule_choice" and decision["unit_id"] == "1"
    assert [o["effect_ids"] for o in decision["options"]] == [("da_jump",), ()]
    assert eng.game_state["pending_rule_choice_queue"][0]["kind"] == "ability_call"


def test_aucun_appel_si_le_weirdboy_est_mort():
    """19.04 : la source morte, l'escouade ne porte plus Da Jump — rien n'est proposé."""
    eng = _engine()
    destroy_model(eng.game_state, _weirdboy_mid(eng.game_state), "combat")
    result = _start_move_phase(eng)
    assert not result.get("waiting_for_player") and read_pending_agent_decision(eng.game_state) is None
    assert eng.game_state["pending_rule_choice_queue"] == []


def test_passer_ne_consomme_rien_et_repropose_au_tour_suivant():
    eng = _engine()
    gs = eng.game_state
    _start_move_phase(eng)
    _answer(eng, 1)  # passer
    assert read_pending_agent_decision(gs) is None
    assert not mh.da_jump_claimed_this_turn(gs, 1)
    assert unit_is_in_strategic_reserves(gs, "1") is False
    assert gs["pending_rule_choice_queue"] == [], "aucune autre escouade candidate : chaîne finie"
    # Tour suivant : reproposé (la réclamation est par (tour, joueur)).
    gs["turn"] = 2
    assert mh.push_next_da_jump_call(gs) == "1"


# ─────────────────────────────────────────────────────────────────────────────
# 1 → D6 blessures mortelles psychiques
# ─────────────────────────────────────────────────────────────────────────────


def test_un_sur_le_de_inflige_d6_mw_psychiques_a_l_escouade(monkeypatch):
    seq = [1, 3]  # D6 = 1 (raté), puis D6 = 3 blessures mortelles
    monkeypatch.setattr(random, "randint", lambda a, b: seq.pop(0) if seq else 6)
    eng = _engine()
    gs = eng.game_state
    hp_before = sum(gs["models_cache"][m]["HP_CUR"] for m in gs["squad_models"]["1"])
    _start_move_phase(eng)
    ok, result = _answer(eng, 0)
    assert ok is True and result.get("daJumpOutcome") == "MISCAST"
    hp_after = sum(gs["models_cache"][m]["HP_CUR"] for m in gs["squad_models"]["1"])
    assert hp_before - hp_after == 3, "3 blessures mortelles allouées (défenseur programmatique)"
    assert unit_is_in_strategic_reserves(gs, "1") is False, "un 1 ne repositionne pas"
    assert mh.da_jump_claimed_this_turn(gs, 1), "le jet est l'usage"
    logs = [l for l in gs["action_logs"] if l["type"] in ("da_jump", "mortal_wounds_ability")]
    assert logs[0]["message"] == "Unit 1(30,50) DA JUMP (D6=1) [MISCAST]"
    assert "SUFFERS 3 Mortal Wounds [DA JUMP] Trigger:1 MW:3 [FROM:1]" in logs[1]["message"]


def test_les_mw_de_da_jump_sont_psychiques_psychic_hood_joue(monkeypatch):
    """Porteur FABRIQUÉ de `feel_no_pain_vs_psychic` 4+ sur l'escouade : les FNP sauvent."""
    seq = [1, 4, 5, 5, 5, 5]  # D6=1 ; 4 MW ; 4 jets de FNP réussis (4+)
    monkeypatch.setattr(random, "randint", lambda a, b: seq.pop(0) if seq else 6)
    eng = _engine()
    gs = eng.game_state
    gs["unit_by_id"]["1"]["UNIT_RULES"].append({
        "ruleId": "feel_no_pain_vs_psychic", "displayName": "Psychic Hood (fabriqué)",
        "rule_args": {"threshold": 4},
    })
    hp_before = sum(gs["models_cache"][m]["HP_CUR"] for m in gs["squad_models"]["1"])
    _start_move_phase(eng)
    _answer(eng, 0)
    hp_after = sum(gs["models_cache"][m]["HP_CUR"] for m in gs["squad_models"]["1"])
    assert hp_before == hp_after, "quatre 5 sur FNP 4+ : aucune blessure ne passe"


# ─────────────────────────────────────────────────────────────────────────────
# 2-6 → hors table, Deep Strike accordé, ingress la même phase
# ─────────────────────────────────────────────────────────────────────────────


def _jump(eng, monkeypatch, d6: int = 4):
    monkeypatch.setattr(random, "randint", lambda a, b: d6)
    _start_move_phase(eng)
    ok, result = _answer(eng, 0)
    assert ok is True and result.get("daJumpOutcome") == "REPOSITIONED", result
    return result


def test_deux_a_six_place_en_reserves_avec_deep_strike_accorde(monkeypatch):
    eng = _engine()
    gs = eng.game_state
    _jump(eng, monkeypatch)
    assert unit_is_in_strategic_reserves(gs, "1") is True
    assert gs["unit_by_id"]["1"]["reserves_repositioned"] is True
    assert mh.unit_has_deep_strike(gs, "1") is True
    assert "1" in gs[mh.DEEP_STRIKE_GRANTED_SQUADS_KEY]
    # T1 : le grant est un REGISTRE, jamais une règle écrite sur les figurines.
    for mid in gs["squad_models"]["1"]:
        assert "deep_strike" not in {r["ruleId"] for r in gs["models_cache"][mid]["UNIT_RULES"]}
    assert "1" in mh.ingress_eligible_units(gs), "ingress ouvert dès ce round (round 1)"
    assert "1" in gs["move_activation_pool"]
    da_jump_logs = [l for l in gs["action_logs"] if l["type"] == "da_jump"]
    assert [l["message"] for l in da_jump_logs] == ["Unit 1(30,50) DA JUMP (D6=4) [REPOSITIONED]"]


def test_l_ingress_se_fait_dans_la_meme_phase_a_plus_de_8_pouces_zone_adverse_permise(monkeypatch):
    from engine.hex_utils import min_distance_between_sets

    eng = _engine()
    gs = eng.game_state
    _jump(eng, monkeypatch)
    # L'escouade repositionnée est la seule du pool : le masque ouvre directement ses slots
    # d'ingress (mise en place 03.02, ids 4-11) — même phase, round 1.
    mask, _ = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    open_slots = [a for a in DEPLOY_SLOTS if bool(mask[a])]
    assert open_slots, "aucun slot d'ingress ouvert après Da Jump"
    ok, result = eng._process_squad_action(eng.action_decoder.convert_squad_action(open_slots[0], gs))
    assert ok is True and result.get("action") == "ingress_move", result
    assert unit_is_in_strategic_reserves(gs, "1") is False
    clearance = 8 * int(gs["inches_to_subhex"])
    enemy_cells = set(gs["units_cache"]["101"]["occupied_hexes"])
    for mid in gs["squad_models"]["1"]:
        m = gs["models_cache"][mid]
        assert m["col"] >= 0 and m["row"] >= 0, "figurine encore hors table après l'ingress"
        assert min_distance_between_sets({(m["col"], m["row"])}, enemy_cells, clearance) > clearance
    assert "1" in gs["units_moved"] or mh.unit_ingress_move_locked(gs, "1"), (
        "20.04 AFTER MOVING : plus aucun autre mouvement ce tour"
    )


def test_le_pool_d_ingress_apres_da_jump_ouvre_la_zone_adverse_des_le_round_1(monkeypatch):
    eng = _engine()
    gs = eng.game_state
    _jump(eng, monkeypatch)
    edge, clearance, opponent_zone_open = mh.ingress_pool_signature(gs, "1")
    assert edge is None and clearance == 8 and opponent_zone_open is True
    pool = mh.ingress_setup_pool(gs, "1")
    assert pool, "pool d'ingress vide après Da Jump"
    enemy_zone = mh._opponent_deployment_zone_cells(gs, 1)
    assert pool & enemy_zone, "la zone de déploiement adverse doit être ouverte (24.09)"


def test_deep_strike_accorde_s_eteint_a_la_fin_de_la_phase(monkeypatch):
    eng = _engine()
    gs = eng.game_state
    _jump(eng, monkeypatch)
    mh.movement_phase_end(gs)
    assert mh.DEEP_STRIKE_GRANTED_SQUADS_KEY not in gs
    assert mh.unit_has_deep_strike(gs, "1") is False


def test_pas_de_destruction_en_fin_de_round_3(monkeypatch):
    """`reserves_repositioned` exempte l'escouade repositionnée (w40k_core, fin de round 3)."""
    eng = _engine()
    gs = eng.game_state
    _jump(eng, monkeypatch)
    from engine.w40k_core import destroy_unarrived_strategic_reserves

    gs["turn"] = 3
    destroyed = destroy_unarrived_strategic_reserves(gs)
    assert destroyed == [] and "1" in gs["units_cache"] and gs["squad_models"]["1"]


def test_second_da_jump_du_meme_tour_refuse(monkeypatch):
    eng = _engine()
    gs = eng.game_state
    _jump(eng, monkeypatch)
    assert mh.da_jump_candidate_squads(gs) == []
    assert mh.push_next_da_jump_call(gs) is None
    with pytest.raises(RuntimeError, match="second jet"):
        mh.apply_da_jump(gs, "1", True)


def test_une_escouade_qui_avait_avance_ne_charge_pas_apres_l_ingress(monkeypatch):
    """20.02 clause 2 : « has still made an advance move that turn » — `units_advanced` intact."""
    eng = _engine()
    gs = eng.game_state
    gs["units_advanced"].add("1")
    gs["units_moved"].add("1")
    _jump(eng, monkeypatch)
    assert "1" in gs["units_advanced"] and "1" in gs["units_moved"]


# ─────────────────────────────────────────────────────────────────────────────
# Sièges et forme
# ─────────────────────────────────────────────────────────────────────────────


def test_politique_bot_declaree():
    """Accepte ssi aucun ennemi à 12" ou moins ET un objectif non contrôlé à plus de 12"."""
    from engine.hex_utils import hex_distance

    eng = _engine()
    gs = eng.game_state
    twelve = 12 * gs["inches_to_subhex"]
    assert hex_distance(30, 50, 110, 290) > twelve
    gs["objective_controllers"] = {}
    assert mh._bot_da_jump_policy(gs, "1") is True, "ennemi loin, objectifs libres loin → saut"
    # Tous les objectifs contrôlés par le joueur 1 → rien à gagner → refus.
    gs["objective_controllers"] = {str(o["id"]): 1 for o in gs["objectives"]}
    assert mh._bot_da_jump_policy(gs, "1") is False
    # Ennemi ramené à 12" ou moins → refus, même avec un objectif libre.
    gs["objective_controllers"] = {}
    gs["units_cache"]["101"]["occupied_hexes"] = {(30, 90)}
    assert mh._bot_da_jump_policy(gs, "1") is False


def test_obs_size_et_action_space_inchanges():
    from engine.observation_builder import ObservationBuilder
    from engine.observation_entities import UNIT_RULE_EFFECT_IDS

    assert "da_jump" in UNIT_RULE_EFFECT_IDS
    assert ObservationBuilder.SQUAD_OBS_SIZE_TARGET == 18241
    assert TOTAL_ACTION_SIZE == 1389
