"""Verrou findings 1&2 — Desperate Escape dans le chemin gym fall_back.

Le chemin gym `squad_fall_back` passait par `execute_squad_move` sans appeler
`desperate_escape_pre_move`, donc `_flee_mode` n'était jamais posé : step.log émettait
toujours [ORDERED RETREAT] même pour une unité battle-shocked + engagée, et les jets
hazard (06.03) n'étaient pas résolus.

Chaîne exercée :
  _process_squad_action(squad_fall_back)
  → si battle_shocked + engagée → desperate_escape_pre_move(auto_resolve=True)
  → game_state["_flee_mode"] = "desperate_escape"
  → action_log["fleeMode"] = "desperate_escape"

Cycle rouge→vert : supprimer le bloc d'injection `if move_type == "fall_back":`
dans la branche `squad_normal_move / squad_advance / squad_fall_back` de
`_process_squad_action` fait passer `test_gym_fall_back_battleshocked_sets_desperate_escape`
en rouge.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

_OBS_SIZE = ObservationBuilder.SQUAD_OBS_SIZE_TARGET


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 0,
            "WEAPON_RULES": [], "display_name": "Test CC"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 5, "HP_MAX": 5, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _engine_engaged() -> W40KEngine:
    """Moteur avec unités en engagement range (col 20/21, même row)."""
    obs_params = {"obs_size": _OBS_SIZE}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35, "max_turns": 5},
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "controlled_player": 1,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, 20, 20),  # J1 — sera battle-shocked
            _unit_cfg(2, 2, 21, 20),  # J2 — adjacent (ER 1 hex)
        ],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(config), gym_training_mode=True)
    eng.reset()
    return eng


def _engine_battle_shocked() -> tuple:
    """Moteur prêt pour un fall_back avec unité 1 battle-shocked et engagée."""
    eng = _engine_engaged()
    gs = eng.game_state
    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]
    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = True
    return eng, gs


def test_gym_fall_back_battleshocked_sets_desperate_escape() -> None:
    """fall_back avec battle_shocked + engagée → fleeMode=desperate_escape dans action_log."""
    eng, gs = _engine_battle_shocked()

    # Destination de fall_back : case (18, 20) — loin de l'ennemi en (21,20).
    before = len(gs.get("action_logs", []))
    ok, result = eng._process_squad_action(
        {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
    )

    assert ok, f"squad_fall_back a échoué : {result}"

    move_logs = [
        e for e in gs["action_logs"][before:]
        if e.get("type") == "move"
    ]
    assert len(move_logs) == 1, (
        f"attendu 1 action_log move, obtenu {len(move_logs)}: {gs['action_logs'][before:]}"
    )
    assert move_logs[0]["fleeMode"] == "desperate_escape", (
        f"fleeMode attendu 'desperate_escape', obtenu {move_logs[0].get('fleeMode')!r}"
    )


def test_gym_desperate_escape_died_clears_game_state_keys() -> None:
    """Hazard détruit l'unité → _flee_mode et _desperate_escape_rolls absents du game_state.

    Régression : l'ancien chemin retournait sans purger ces clés ; le prochain fall_back
    dans le même épisode héritait de _flee_mode="desperate_escape" même pour une unité
    non-battle-shocked.
    """
    eng, gs = _engine_battle_shocked()

    # Simuler desperate_escape_pre_move qui pose les clés PUIS retourne is_alive=False.
    def _fake_pre_move(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        game_state["_flee_mode"] = "desperate_escape"
        game_state["_desperate_escape_rolls"] = [1, 2]
        return True, False, 2  # is_desperate, is_alive=False, wounds

    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_fake_pre_move,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
        )

    assert ok, f"desperate_escape_died a échoué : {result}"
    assert result.get("action") == "desperate_escape_died"
    assert "_flee_mode" not in gs, (
        f"_flee_mode stale dans game_state : {gs['_flee_mode']!r}"
    )
    assert "_desperate_escape_rolls" not in gs, (
        "_desperate_escape_rolls stale dans game_state"
    )


def test_gym_fall_back_not_battleshocked_keeps_ordered_retreat() -> None:
    """fall_back sans battle_shock → fleeMode=ordered_retreat (comportement normal préservé)."""
    eng = _engine_engaged()
    gs = eng.game_state

    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]

    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = False

    before = len(gs.get("action_logs", []))
    ok, result = eng._process_squad_action(
        {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
    )

    assert ok, f"squad_fall_back a échoué : {result}"

    move_logs = [
        e for e in gs["action_logs"][before:]
        if e.get("type") == "move"
    ]
    assert len(move_logs) == 1
    assert move_logs[0]["fleeMode"] == "ordered_retreat", (
        f"fleeMode attendu 'ordered_retreat', obtenu {move_logs[0].get('fleeMode')!r}"
    )
