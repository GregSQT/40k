"""Tests e2e — activation complète via execute_semantic_action.

Chemin testé : activation → résolution → décompte HP → mort → cleanup pool.
Utilise _bare_engine (bypass __init__) avec un game_state minimal injecté,
comme dans test_execute_semantic_action.py.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.w40k_core import W40KEngine
from engine.phase_handlers.shared_utils import build_units_cache, build_enemy_adjacent_hexes

from _config_helpers import build_game_rules


@pytest.fixture(autouse=True)
def mock_reward_systems(monkeypatch):
    """Mocke les systèmes de reward pour éviter les lookups dans unit_registry et RewardMapper."""
    from ai import unit_registry as ur
    monkeypatch.setattr(ur.UnitRegistry, "__init__", lambda self: None)
    monkeypatch.setattr(ur.UnitRegistry, "get_model_key", lambda self, unit_type: "default")

    from ai import reward_mapper as rm
    monkeypatch.setattr(rm.RewardMapper, "__init__", lambda self, config: None)
    monkeypatch.setattr(rm.RewardMapper, "_get_unit_rewards", lambda self, unit: {
        "base_actions": {"ranged_attack": 0.0, "melee_attack": 0.0, "charge_success": 0.0},
        "result_bonuses": {"kill_target": 0.0, "damage_dealt": 0.0},
    })


# ─────────────────────────────────────────────────────────────────────────────
# Helpers partagés
# ─────────────────────────────────────────────────────────────────────────────

def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": build_game_rules(
            engagement_zone=1,
            max_base_size_hex=35,
            
            cover_ratio=0.0,
        ),
        "charge": {
            "charge_max_distance": 12,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        "gym_training_mode": False,
        "pve_mode": False,
        "controlled_player": 1,
    }


def _weapon(atk=4, str_=4, ap=0, dmg=3) -> Dict[str, Any]:
    return {
        "ATK": atk,
        "STR": str_,
        "AP": ap,
        "DMG": dmg,
        "NB": 1,
        "RNG": 24,
        "WEAPON_RULES": ["IGNORES_COVER"],
        "display_name": "Test Bolter",
    }


def _unit(uid: int, player: int, col: int, row: int, hp: int = 3) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": hp,
        "HP_MAX": hp,
        "VALUE": 100,
        "OC": 1,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [_weapon()],
        "CC_WEAPONS": [],
        "selectedRngWeaponIndex": 0,
        "_rapid_fire_rule_value": 0,
        "_rapid_fire_bonus_shot_current": False,
        "unitType": "TestUnit",
        "DISPLAY_NAME": f"Unit {uid}",
    }


def _make_shoot_gs(attacker: Dict, target: Dict) -> Dict[str, Any]:
    """Game-state minimal pour la phase shoot avec un attaquant et une cible."""
    units = [attacker, target]
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "shoot",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "episode_number": 1,
        "debug_mode": False,
        "turn_limit_reached": False,
        "game_over": False,
        "winner": None,
        "units_moved": set(),
        "units_advanced": set(),
        "units_fled": set(),
        "units_shot": set(),
        "units_charged": set(),
        "units_fought": set(),
        "units_cannot_charge": set(),
        "units_attacked": set(),
        "units_reacted_this_enemy_turn": set(),
        "reaction_window_active": False,
        "_unit_move_version": 0,
        "last_move_event_id": 0,
        "last_move_cause": "normal",
        "reactive_mode": "micro",
        "reactive_macro_order_current_window": [],
        "reactive_decision_mode": "auto",
        "reactive_decision_payload": {},
        "move_activation_pool": [],
        "shoot_activation_pool": [str(attacker["id"])],
        "charge_activation_pool": [],
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "command_activation_pool": [],
        "valid_move_destinations_pool": [],
        "preview_hexes": [],
        "move_preview_footprint_span": None,
        "active_movement_unit": None,
        "fight_subphase": None,
        "hex_los_cache": {},
        "los_cache": {},
        "player_types": {"1": "human", "2": "ai"},
        "gym_training_mode": False,
        "weapon_rule": 1,
        "victory_points": {1: 0, 2: 0},
        "primary_objective": None,
        "primary_objective_scored_turns": set(),
        "objective_rewarded_turns": set(),
        "objective_controllers": {},
        "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[5, 5]]}],
        "pending_shooting_phase_init": False,
        "charge_range_rolls": {},
        "inches_to_subhex": 1,
        "rewards_configs": {
            "default": {
                "base_actions": {
                    "ranged_attack": 0.0,
                    "melee_attack": 0.0,
                    "charge_success": 0.0,
                    "move_to_los": 0.0,
                    "move_away": 0.0,
                    "advance": 0.0,
                },
                "result_bonuses": {
                    "kill_target": 0.0,
                    "damage_dealt": 0.0,
                },
            }
        },
        "reward_configs": {
            "default": {
                "base_actions": {
                    "ranged_attack": 0.0,
                    "melee_attack": 0.0,
                    "charge_success": 0.0,
                    "move_to_los": 0.0,
                    "move_away": 0.0,
                    "advance": 0.0,
                },
                "result_bonuses": {
                    "kill_target": 0.0,
                    "damage_dealt": 0.0,
                },
            }
        },
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    return gs


def _bare_engine(gs: Dict[str, Any]) -> W40KEngine:
    engine = object.__new__(W40KEngine)
    engine.game_state = gs
    engine.step_logger = None
    engine.gym_training_mode = False
    engine.config = _base_config()
    engine._shooting_phase_initialized = False
    engine._movement_phase_initialized = False
    engine.is_pve_mode = False
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# Tests — routing et pool management
# ─────────────────────────────────────────────────────────────────────────────

class TestActivationPoolRouting:

    def test_skip_removes_unit_from_shoot_pool(self):
        """act_e2e_skip : skip → unité retirée du pool shoot."""
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 15, 10)
        gs = _make_shoot_gs(attacker, target)
        gs["shoot_activation_pool"] = ["1"]

        engine = _bare_engine(gs)
        success, result = engine.execute_semantic_action({
            "action": "skip",
            "unitId": "1",
        })

        assert success is True
        assert "1" not in gs["shoot_activation_pool"]

    def test_game_over_blocks_activation(self):
        """act_e2e_game_over : game_over bloque toute activation."""
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 15, 10)
        gs = _make_shoot_gs(attacker, target)
        gs["game_over"] = True
        gs["winner"] = 1

        engine = _bare_engine(gs)
        success, result = engine.execute_semantic_action({
            "action": "shoot",
            "unitId": "1",
            "targetId": "2",
        })

        assert success is False
        assert result.get("error") == "game_over"
