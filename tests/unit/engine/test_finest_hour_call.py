"""Finest Hour (`once_per_battle_melee_buff`) en APPEL DE CAPACITÉ à la sélection 12.04 — les
TROIS sièges, sur un MOTEUR RÉEL (`_fall_back_make_engine`, machine V11 en étape FIGHT).

Datasheet (Captain with Relic Shield) : « Finest Hour (Once per battle): In the Fight phase, when
this unit is selected to fight, this model's melee weapons have the following until the end of
the phase: +3 A, [DEVASTATING WOUNDS]. » « Once per battle » : c'est un CHOIX, posé par
`fight_arm_finest_hour_call` aux deux sites de sélection — gym/bot (`squad_fight`,
`_process_squad_action`) et flux manuel (`_fight_v11_manual_activate`) —, répondu par `CHOICE_0/1`
(gym), la politique déclarée `_bot_finest_hour_policy` (bot PvE) ou `select_rule_choice`
(humain), puis le combat REPREND (`_resume_fight_after_finest_hour`). Les sites de résolution
(roller, sélecteur d'armes, 04.02) ne lisent plus que `finest_hour_active_this_phase`.
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

import pytest

from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY
from engine.agent_decision import clear_pending_agent_decision, read_pending_agent_decision
from engine.macro_intents import CHOICE_BASE
from engine.phase_handlers.fight_handlers import (
    FIGHT_SELECTION_FINEST_HOUR_KEY,
    fight_arm_finest_hour_call,
    fight_v11_enter_fight_step,
    fight_v11_start,
)
from engine.phase_handlers.shared_utils import get_enemy_slot_mapping
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)
from tests.unit.engine.test_fight_pve_par_siege import _ScriptedController

_FINEST_HOUR = {
    "ruleId": "once_per_battle_melee_buff", "displayName": "Finest Hour",
    "rule_args": {"attacks_bonus": 3},
}
_EXHORTATION = {
    "ruleId": "mortal_wounds_on_fight_activation", "displayName": "Exhortation of Rage",
    "rule_args": {"mw_on_6": 3},
}


def _captain(uid: int, player: int, col: int, row: int, extra_rules: Optional[List[Dict[str, Any]]] = None):
    cfg = _unit_cfg(uid, player, col, row)
    cfg["UNIT_RULES"] = [dict(_FINEST_HOUR), *(extra_rules or [])]
    return cfg


def _character(uid: int, player: int, col: int, row: int):
    cfg = _unit_cfg(uid, player, col, row)
    cfg["UNIT_KEYWORDS"] = [{"keywordId": "CHARACTER"}]
    return cfg


def _engine(units, *, gym: bool, current_player: int = 1, player_types=None, actions=None) -> W40KEngine:
    eng = _make_engine(_base_config(units))
    gs = eng.game_state
    gs["gym_training_mode"] = gym
    eng.gym_training_mode = gym
    if not gym:
        gs["player_types"] = player_types or {"1": "human", "2": "ai"}
        gs["current_mode_code"] = "pve"
        eng.current_mode_code = "pve"
        eng.is_pve_mode = True
        eng.pve_controller = _ScriptedController(actions or [])  # type: ignore[assignment]
    gs["current_player"] = current_player
    # Le reset ouvre la phase de MOUVEMENT sur des escouades déjà au contact : une décision
    # `fall_back_mode` y reste posée. Le fixture saute en phase de combat ; cette décision
    # n'appartient pas à l'état visé.
    clear_pending_agent_decision(gs)
    gs["phase"] = "fight"
    fight_v11_start(gs)
    fight_v11_enter_fight_step(gs)
    return eng


def _combat_attacks(gs: Dict[str, Any], attacker: str) -> List[Dict[str, Any]]:
    """Lignes `combat` (une par groupe d'armes) de l'attaquant."""
    return [l for l in gs["action_logs"] if l.get("type") == "combat" and str(l.get("shooterId")) == attacker]


def _shots(gs: Dict[str, Any], attacker: str) -> int:
    """Attaques jetées par l'attaquant : la somme des `Shots:N` de ses lignes `combat`."""
    return sum(int(m.group(1)) for l in _combat_attacks(gs, attacker)
               for m in [re.search(r"Shots:(\d+)", str(l.get("message")))] if m)


def _fight_after_call(eng: W40KEngine, out: Dict[str, Any]) -> Dict[str, Any]:
    """Chemin gym/bot après la réponse : le combat repris demande l'arme (V11 §0.69)."""
    if not out.get("waiting_for_weapon_select"):
        return out
    pending = eng.game_state[PENDING_FIGHT_WEAPON_KEY]
    ok, out = eng._process_squad_action(
        {"action": "squad_fight_weapon", "weapon_slot": next(iter(pending["slot_to_code"]))}
    )
    assert ok is True, out
    return out


def _squad_fight(eng: W40KEngine, squad_id: str, target_id: str):
    gs = eng.game_state
    player = int(gs["units_cache"][squad_id]["player"])
    slot = get_enemy_slot_mapping(gs, player).index(target_id)
    return eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id, "target_slot": slot})


def _choice(eng: W40KEngine, slot: int):
    return eng._process_squad_action(eng.action_decoder.convert_squad_action(CHOICE_BASE + slot, eng.game_state))


# ─────────────────────────────────────────────────────────────────────────────
# Gym : la sélection pose la décision, CHOICE_0 active, CHOICE_1 passe
# ─────────────────────────────────────────────────────────────────────────────


def test_gym_selection_poses_the_call_and_choice_0_fights_with_plus_3_and_devastating(monkeypatch):
    eng = _engine([_captain(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], gym=True)
    gs = eng.game_state
    monkeypatch.setattr(random, "randint", lambda a, b: 6)  # touche, blesse (crit), pas de save

    ok, out = _squad_fight(eng, "1", "2")
    assert ok is True and out["action"] == "waiting_for_agent_decision", out
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "rule_choice" and decision["unit_id"] == "1"
    assert [o["effect_ids"] for o in decision["options"]] == [("once_per_battle_melee_buff",), ()]
    assert "1" in gs["units_selected_to_fight"], "sélectionnée AVANT la question (12.04)"
    assert gs.get("finest_hour_used", set()) == set() and _combat_attacks(gs, "1") == []
    assert gs[FIGHT_SELECTION_FINEST_HOUR_KEY]["squad_id"] == "1"

    ok, out = _choice(eng, 0)
    assert ok is True and out["action"] == "squad_fight", out
    assert FIGHT_SELECTION_FINEST_HOUR_KEY not in gs and read_pending_agent_decision(gs) is None
    assert gs["finest_hour_used"] == {"1"} and gs["finest_hour_active_this_phase"] == {"1"}
    assert any(l.get("type") == "ability_call" and "Finest Hour [USED]" in str(l.get("message")) for l in gs["action_logs"])
    _fight_after_call(eng, out)
    attacks = _combat_attacks(gs, "1")
    assert _shots(gs, "1") == 4, f"A1 + 3 (Finest Hour) : {attacks}"
    assert all(a["finestHour"] is True and "[DEVASTATING WOUNDS]" in str(a["message"]) for a in attacks)


def test_gym_choice_1_declines_fights_without_bonus_and_keeps_the_once_per_battle(monkeypatch):
    from engine.phase_handlers.fight_handlers import fight_finest_hour_available

    eng = _engine([_captain(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], gym=True)
    gs = eng.game_state
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    _squad_fight(eng, "1", "2")

    ok, out = _choice(eng, 1)
    assert ok is True and out["action"] == "squad_fight", out
    _fight_after_call(eng, out)
    attacks = _combat_attacks(gs, "1")
    assert _shots(gs, "1") == 1 and attacks[0]["finestHour"] is False
    assert "1" not in gs.get("finest_hour_used", set())
    assert fight_finest_hour_available(gs, "1") is True, "reproposable à une sélection suivante"
    assert any("Finest Hour [DECLINED]" in str(l.get("message")) for l in gs["action_logs"])


def test_a_squad_without_the_rule_or_already_spent_gets_no_call(monkeypatch):
    eng = _engine([_captain(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], gym=True)
    gs = eng.game_state
    gs["finest_hour_used"] = {"1"}
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    ok, out = _squad_fight(eng, "1", "2")
    assert ok is True and out["action"] == "squad_fight" and read_pending_agent_decision(gs) is None
    _fight_after_call(eng, out)
    assert _shots(gs, "1") == 1


# ─────────────────────────────────────────────────────────────────────────────
# Bot PvE : la politique déclarée répond dans la file, le combat reprend dans la même requête
# ─────────────────────────────────────────────────────────────────────────────


def _bot_fights(enemy_cfg, monkeypatch):
    """Tour du bot (joueur 2, Captain) : `squad_fight` par la politique scriptée, puis l'arme.
    Rend le moteur une fois le combat résolu."""
    eng = _engine(
        [enemy_cfg, _captain(2, 2, 21, 20)], gym=False, current_player=2,
        actions=[{"action": "squad_fight", "squad_id": "2", "target_slot": None}],
    )
    gs = eng.game_state
    eng.pve_controller.actions[0]["target_slot"] = get_enemy_slot_mapping(gs, 2).index("1")  # type: ignore[attr-defined]
    monkeypatch.setattr(random, "randint", lambda a, b: 1)  # rien ne touche : le défenseur humain n'alloue pas
    ok, out = eng.execute_ai_turn()
    assert ok is True and out.get("waiting_for_weapon_select") is True, out
    assert "2" in gs["units_selected_to_fight"]
    assert gs["pending_rule_choice_queue"] == [] and FIGHT_SELECTION_FINEST_HOUR_KEY not in gs, (
        "l'appel a été répondu par la politique DANS la requête de sélection"
    )
    slot = next(iter(gs[PENDING_FIGHT_WEAPON_KEY]["slot_to_code"]))
    eng.pve_controller.actions = [{"action": "squad_fight_weapon", "weapon_slot": slot}]  # type: ignore[attr-defined]
    ok, out = eng.execute_ai_turn()
    assert ok is True, out
    return eng


def test_bot_pve_accepts_against_a_character_by_the_declared_policy(monkeypatch):
    eng = _bot_fights(_character(1, 1, 20, 20), monkeypatch)
    gs = eng.game_state
    assert gs["finest_hour_used"] == {"2"}
    assert _shots(gs, "2") == 4
    assert any("Finest Hour [USED]" in str(l.get("message")) for l in gs["action_logs"])


def test_bot_pve_declines_against_a_lone_grunt_by_the_declared_policy(monkeypatch):
    eng = _bot_fights(_unit_cfg(1, 1, 20, 20), monkeypatch)
    gs = eng.game_state
    assert "2" not in gs.get("finest_hour_used", set())
    assert _shots(gs, "2") == 1
    assert any("Finest Hour [DECLINED]" in str(l.get("message")) for l in gs["action_logs"])


# ─────────────────────────────────────────────────────────────────────────────
# Humain : l'activation pose le prompt, tout autre verbe attend, la réponse reprend l'unité active
# ─────────────────────────────────────────────────────────────────────────────


def test_human_activation_serves_the_prompt_and_select_rule_choice_resumes_the_active_unit(monkeypatch):
    eng = _engine(
        [_captain(1, 1, 20, 20), _unit_cfg(3, 1, 22, 20), _unit_cfg(2, 2, 21, 20)],
        gym=False, player_types={"1": "human", "2": "ai"},
    )
    gs = eng.game_state
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["action"] == "waiting_for_rule_choice", out
    prompt = gs["active_rule_choice_prompt"]
    assert prompt["rule_id"] == "once_per_battle_melee_buff" and prompt["unit_id"] == "1"
    assert gs["active_fight_unit"] == "1" and "1" not in gs["units_selected_to_fight"]

    # Tout autre verbe attend la réponse (garde `active_rule_choice_prompt`) : rien n'est joué.
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "2"})
    assert ok is True and out["action"] == "waiting_for_rule_choice" and _combat_attacks(gs, "1") == []

    ok, out = eng.execute_semantic_action({
        "action": "select_rule_choice", "unitId": "1", "player": 1, "selectedRuleId": "once_per_battle_melee_buff",
    })
    assert ok is True, out
    assert gs["active_rule_choice_prompt"] is None and FIGHT_SELECTION_FINEST_HOUR_KEY not in gs
    assert gs["finest_hour_used"] == {"1"}
    assert out["active_fight_unit"] == "1", "l'unité reste ACTIVE : le joueur déclare ses attaques"

    # 12.04 : l'unité qui a répondu EST sélectionnée — une autre ne peut pas lui être préférée.
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "3"})
    assert ok is True and gs["active_fight_unit"] == "1", out

    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "2"})
    assert ok is True, out
    attacks = _combat_attacks(gs, "1")
    assert _shots(gs, "1") == 4 and all(a["finestHour"] is True for a in attacks)


def test_human_decline_keeps_the_unit_active_and_the_once_per_battle(monkeypatch):
    eng = _engine([_captain(1, 1, 20, 20), _unit_cfg(2, 2, 21, 20)], gym=False)
    gs = eng.game_state
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    ok, out = eng.execute_semantic_action({
        "action": "select_rule_choice", "unitId": "1", "player": 1, "selectedRuleId": "decline",
    })
    assert ok is True and out["active_fight_unit"] == "1", out
    assert "1" not in gs.get("finest_hour_used", set())
    # Ré-activation du même clic : la question ne se repose pas dans la phase.
    ok, out = eng.execute_semantic_action({"action": "activate_unit", "unitId": "1"})
    assert ok is True and out["action"] != "waiting_for_rule_choice" and gs["active_rule_choice_prompt"] is None
    ok, out = eng.execute_semantic_action({"action": "fight", "unitId": "1", "targetId": "2"})
    assert ok is True and _shots(gs, "1") == 1


# ─────────────────────────────────────────────────────────────────────────────
# Exhortation + Finest Hour sur la même escouade : deux leaders (19.01), état impossible
# ─────────────────────────────────────────────────────────────────────────────


def test_exhortation_and_finest_hour_on_the_same_squad_raise():
    eng = _engine([_captain(1, 1, 20, 20, [dict(_EXHORTATION)]), _unit_cfg(2, 2, 21, 20)], gym=True)
    with pytest.raises(ValueError, match="19.01"):
        fight_arm_finest_hour_call(eng.game_state, "1", None, "gym")
