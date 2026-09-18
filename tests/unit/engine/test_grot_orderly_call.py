"""Grot Orderly (`return_destroyed_models`) en APPEL DE CAPACITÉ — les TROIS sièges, par le moteur.

Datasheet Painboy : « Grot Orderly (Once per battle): In your Command phase, if this unit is
below starting strength, you can return up to D3 destroyed bodyguard models to this unit. »
« You can » : 08.04 POSE l'appel (`_apply_return_destroyed_models` → `push_ability_call`) avant
tout jet de D3 ; la réponse arrive dans `apply_grot_orderly_call`. Ici : gym (`CHOICE_0`/
`CHOICE_1` → `_handle_agent_decision_action`, puis la phase de commandement REPREND et ouvre le
mouvement), bot PvE (`start_command_phase` → `_resolve_faction_decisions_for_ai_seats` →
politique déclarée `_bot_grot_orderly_policy`), humain (`select_rule_choice`, puis reprise).
La chaîne D3 → profil → placement et la clause bodyguard : test_returned_models_placement.py.
"""
from __future__ import annotations

from typing import Any, Dict

from engine.agent_decision import read_pending_agent_decision
from engine.macro_intents import CHOICE_BASE
from engine.phase_handlers.command_handlers import faction_decision_is_pending
from tests.unit.engine.test_agent_decision_mechanism import _engine, _game_state, _unit

_RULE = {"ruleId": "return_destroyed_models", "displayName": "Grot Orderly"}


def _gs(n_dead: int = 2, **overrides: Any) -> Dict[str, Any]:
    """Escouade 1 (P1, Grot Orderly) à (5,10) avec `n_dead` Boyz archivés, ennemi 2 loin."""
    gs = _game_state([_unit(1, 1, 5, 10, [dict(_RULE)]), _unit(2, 2, 20, 10, [])])
    gs["phase"] = "command"
    # Datasheet de l'escouade : la ligne `RETURNED` du journal la lit (`model_datasheet_name`).
    gs["unit_by_id"]["1"]["unitType"] = "Boyz"
    template = dict(gs["models_cache"]["1#0"])
    gs["destroyed_models"] = {
        "1": [{**template, "col": -1, "row": -1, "role": None, "unitType": "Boyz"} for _ in range(n_dead)]
    }
    gs["squad_cache"]["1"]["model_count_at_start"] = int(gs["squad_cache"]["1"]["model_count"]) + n_dead
    gs.update(overrides)
    return gs


def _grot_prompt(gs: Dict[str, Any]) -> Dict[str, Any]:
    from engine.ability_calls import pending_ability_call_prompts

    prompts = pending_ability_call_prompts(gs, squad_id="1", effect_id="return_destroyed_models")
    assert len(prompts) == 1, f"un seul appel Grot Orderly attendu : {prompts}"
    return prompts[0]


def _returned(gs: Dict[str, Any]) -> int:
    return sum(1 for mid in gs["squad_models"]["1"] if "#r" in mid)


def test_gym_command_phase_poses_the_call_and_choice_0_returns_models_then_opens_move():
    """Gym : `start_command_phase` empile l'appel et s'arrête (08.04 en attente) ; la file
    l'émet en décision `rule_choice` ; `CHOICE_0` rend les figurines, dépense le once-per-battle
    et la phase de commandement REPREND jusqu'au mouvement."""
    gs = _gs()
    engine = _engine(gs)
    engine._initialize_rule_choice_runtime_state()

    cmd = engine.start_command_phase()
    assert cmd["phase_complete"] is False and gs["phase"] == "command"
    prompt = _grot_prompt(gs)
    assert prompt["phase"] == "command" and prompt["display_name"] == "Grot Orderly"
    assert faction_decision_is_pending(gs, 1) is True
    assert _returned(gs) == 0, "aucun D3 avant la réponse"

    emitted = engine._emit_next_rule_choice_prompt_if_needed()
    assert emitted is not None and emitted["action"] == "waiting_for_agent_decision"
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "rule_choice"
    assert [o["effect_ids"] for o in decision["options"]] == [("return_destroyed_models",), ()]

    success, result = engine._process_squad_action(
        engine.action_decoder.convert_squad_action(CHOICE_BASE, gs)
    )
    assert success is True and result["waiting_for_player"] is True
    # L'appel accepté a jeté le D3 et ouvert le PLACEMENT (les plans diffèrent : un objectif et
    # un ennemi sur la table) — la chaîne profil → placement est inchangée.
    placement = read_pending_agent_decision(gs)
    assert placement is not None and placement["type"] == "returned_models_placement"
    assert gs["pending_rule_choice_queue"] == [] and gs["phase"] == "command"
    assert _returned(gs) == 0

    success, result = engine._process_squad_action(
        engine.action_decoder.convert_squad_action(CHOICE_BASE, gs)
    )
    assert success is True and read_pending_agent_decision(gs) is None
    assert 1 <= _returned(gs) <= 2
    assert "1" in gs["return_destroyed_models_used"]
    assert result.get("phase_complete") is True and gs["phase"] == "move", (
        "la réponse à un appel de phase de commandement reprend la phase et ouvre le mouvement"
    )


def test_gym_choice_1_declines_consumes_nothing_and_opens_move():
    gs = _gs()
    engine = _engine(gs)
    engine._initialize_rule_choice_runtime_state()
    engine.start_command_phase()
    engine._emit_next_rule_choice_prompt_if_needed()

    success, result = engine._process_squad_action(
        engine.action_decoder.convert_squad_action(CHOICE_BASE + 1, gs)
    )
    assert success is True
    assert _returned(gs) == 0 and len(gs["destroyed_models"]["1"]) == 2
    assert "1" not in gs.get("return_destroyed_models_used", set())
    assert gs["phase"] == "move" and result.get("phase_complete") is True
    assert not [l for l in gs["action_logs"] if l.get("type") == "return_destroyed_models"]
    assert any(
        l.get("type") == "ability_call" and "[DECLINED]" in str(l.get("message", ""))
        for l in gs["action_logs"]
    ), "la ligne ABILITY CALL Grot Orderly [DECLINED] distingue « refusé » de « jamais proposé »"


def test_declined_call_is_reproposed_at_the_next_command_phase():
    """Refus au tour N : `_GROT_ORDERLY_SKIPPED` est vidé à 08.01, l'appel se repose au tour
    N+1 — comme un `waaagh_call` passé."""
    gs = _gs()
    engine = _engine(gs)
    engine._initialize_rule_choice_runtime_state()
    engine.start_command_phase()
    engine._emit_next_rule_choice_prompt_if_needed()
    engine._process_squad_action(engine.action_decoder.convert_squad_action(CHOICE_BASE + 1, gs))
    assert gs["phase"] == "move"

    gs["phase"] = "command"
    gs["turn"] = 2
    cmd = engine.start_command_phase()
    assert cmd["phase_complete"] is False
    assert _grot_prompt(gs)["unit_id"] == "1"


def test_bot_pve_seat_answers_by_the_declared_policy_inside_start_command_phase():
    """Bot PvE : `start_command_phase` sert la file au siège bot (politique déclarée : deux
    bodyguard morts → accepte) et la phase se termine dans la même requête."""
    gs = _gs(player_types={"1": "ai", "2": "human"})
    engine = _engine(gs, gym_training_mode=False)
    engine.is_pve_mode = True

    cmd = engine.start_command_phase()

    assert cmd["phase_complete"] is True
    assert 1 <= _returned(gs) <= 2 and "1" in gs["return_destroyed_models_used"]
    assert gs["pending_rule_choice_queue"] == [] and read_pending_agent_decision(gs) is None


def test_bot_pve_seat_declines_by_the_declared_policy():
    """Un seul bodyguard mort au tour 1 : la politique refuse, rien n'est consommé, la phase
    se termine quand même."""
    gs = _gs(n_dead=1, player_types={"1": "ai", "2": "human"})
    engine = _engine(gs, gym_training_mode=False)
    engine.is_pve_mode = True

    cmd = engine.start_command_phase()

    assert cmd["phase_complete"] is True
    assert _returned(gs) == 0 and "1" not in gs.get("return_destroyed_models_used", set())
    assert "1" in gs["_grot_orderly_skipped_this_phase"]


def test_human_seat_answers_through_select_rule_choice_and_the_phase_resumes():
    gs = _gs(player_types={"1": "human", "2": "ai"})
    engine = _engine(gs, gym_training_mode=False)
    engine._initialize_rule_choice_runtime_state()

    cmd = engine.start_command_phase()
    assert cmd["phase_complete"] is False
    waiting = engine._emit_next_rule_choice_prompt_if_needed()
    assert waiting is not None and waiting["action"] == "waiting_for_rule_choice"
    assert gs["active_rule_choice_prompt"]["rule_id"] == "return_destroyed_models"

    success, result = engine._process_semantic_action({
        "action": "select_rule_choice", "unitId": "1", "player": 1,
        "selectedRuleId": "return_destroyed_models",
    })
    assert success is True and result["waiting_for_player"] is True
    assert gs["active_rule_choice_prompt"] is None and gs["pending_rule_choice_queue"] == []
    placement = read_pending_agent_decision(gs)
    assert placement is not None and placement["type"] == "returned_models_placement"
    assert placement["player"] == 1, "le panneau humain lit le propriétaire de la décision"

    success, result = engine._process_semantic_action({"action": "agent_decision", "option_index": 0})
    assert success is True and 1 <= _returned(gs) <= 2
    assert gs["phase"] == "move" and result.get("phase_complete") is True


def test_human_decline_through_select_rule_choice():
    gs = _gs(player_types={"1": "human", "2": "ai"})
    engine = _engine(gs, gym_training_mode=False)
    engine._initialize_rule_choice_runtime_state()
    engine.start_command_phase()
    engine._emit_next_rule_choice_prompt_if_needed()

    success, result = engine._process_semantic_action({
        "action": "select_rule_choice", "unitId": "1", "player": 1, "selectedRuleId": "decline",
    })
    assert success is True and _returned(gs) == 0
    assert gs["phase"] == "move" and result.get("phase_complete") is True


def test_a_squad_at_full_strength_gets_no_call():
    gs = _gs(n_dead=0)
    gs["destroyed_models"] = {}
    engine = _engine(gs)
    engine._initialize_rule_choice_runtime_state()
    cmd = engine.start_command_phase()
    assert cmd["phase_complete"] is True and gs["pending_rule_choice_queue"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Roster RÉEL (datasheets Boyz + Painboy) : l'appel suit la règle en vigueur 19.04
# ─────────────────────────────────────────────────────────────────────────────


def _real_scenario() -> Dict[str, Any]:
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
                    {"col": 30, "row": 50}, {"col": 31, "row": 50}, {"col": 32, "row": 50},
                    {"unit_type": "PainBoy", "col": 33, "row": 50},
                ],
            },
            {"id": 101, "unit_type": "Intercessor", "player": 2, "col": 110, "row": 290,
             "models": [{"col": 110, "row": 290}]},
        ],
    }


def _real_engine_at_turn_2_command(kill_painboy: bool = False):
    """Reset → deux Boyz (et le Painboy si demandé) détruits → phase de commandement du tour 2."""
    from engine.phase_handlers.shared_utils import destroy_model
    from tests.unit.engine._config_helpers import load_engine_from_scenario

    eng = load_engine_from_scenario(
        _real_scenario(), controlled_agent="ArmageddonAgent_x1", rewards_config="ArmageddonAgent_x1",
    )
    gs = eng.game_state
    waaagh = read_pending_agent_decision(gs)
    assert waaagh is not None and waaagh["type"] == "waaagh_call"
    eng._process_squad_action(eng.action_decoder.convert_squad_action(CHOICE_BASE + 1, gs))
    assert gs["phase"] == "move"
    boyz = [m for m in gs["squad_models"]["1"] if gs["models_cache"][m].get("unitType") != "PainBoy"]
    painboy = [m for m in gs["squad_models"]["1"] if gs["models_cache"][m].get("unitType") == "PainBoy"]
    assert len(boyz) == 3 and len(painboy) == 1
    destroy_model(gs, boyz[0], "combat")
    destroy_model(gs, boyz[1], "combat")
    if kill_painboy:
        destroy_model(gs, painboy[0], "combat")
    gs["phase"] = "command"
    gs["turn"] = 2
    gs["current_player"] = 1
    return eng


def test_real_roster_the_call_is_posed_with_the_datasheet_rule_and_choice_0_returns_boyz():
    eng = _real_engine_at_turn_2_command()
    gs = eng.game_state

    cmd = eng.start_command_phase()
    assert cmd["phase_complete"] is False
    assert _grot_prompt(gs)["display_name"] == "Grot Orderly"
    # Le Waaagh! (non appelé au tour 1) n'est reproposé qu'APRÈS la réponse à l'appel.
    assert read_pending_agent_decision(gs) is None

    eng._emit_next_rule_choice_prompt_if_needed()
    success, result = eng._process_squad_action(eng.action_decoder.convert_squad_action(CHOICE_BASE, gs))
    assert success is True
    for _ in range(3):  # placement éventuel, puis Waaagh! reproposé : candidat 0 partout
        decision = read_pending_agent_decision(gs)
        if decision is None:
            break
        assert decision["type"] in ("returned_models_placement", "waaagh_call"), decision["type"]
        success, result = eng._process_squad_action(eng.action_decoder.convert_squad_action(CHOICE_BASE, gs))
        assert success is True
    assert 1 <= _returned(gs) <= 2
    assert all(gs["models_cache"][m]["unitType"] == "Boyz" for m in gs["squad_models"]["1"] if "#r" in m)
    assert gs["phase"] == "move"
    assert any(
        l.get("type") == "ability_call" and "Grot Orderly [USED]" in str(l.get("message", ""))
        for l in gs["action_logs"]
    )


def test_real_roster_a_dead_painboy_takes_the_ability_with_him():
    """19.04 : la règle appartient au Painboy ; mort, l'escouade ne la porte plus — aucun appel,
    et le Painboy lui-même (personnage) ne serait de toute façon jamais rendu."""
    eng = _real_engine_at_turn_2_command(kill_painboy=True)
    gs = eng.game_state

    cmd = eng.start_command_phase()

    assert gs.get("pending_rule_choice_queue", []) == []
    decision = read_pending_agent_decision(gs)
    assert cmd["phase_complete"] is False and decision is not None and decision["type"] == "waaagh_call", (
        "seule la décision Waaagh! (non appelée au tour 1) arrête 08.04"
    )
