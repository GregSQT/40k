"""Tests unitaires — règles spéciales de tir : DEVASTATING_WOUNDS et HAZARDOUS.

Couvre via _attack_sequence_rng avec dés fixés par monkeypatch :
- DEVASTATING_WOUNDS : blessure critique (6) → save sauté, devastating_wounds_applied=True, dmg infligé
- DEVASTATING_WOUNDS : blessure non-critique → chemin normal (save requis)
- HAZARDOUS : roll=1 → hazardous_triggered=True (même sur miss)
- HAZARDOUS : roll≥2 → hazardous_triggered=False
- Combinaison : arme sans règles → aucun flag spécial
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shooting_handlers import _attack_sequence_rng
from engine.phase_handlers.shared_utils import build_units_cache


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _weapon(rules: list = None, atk: int = 4, str_: int = 4, ap: int = 0, dmg: int = 2) -> Dict[str, Any]:
    return {
        "ATK": atk,
        "STR": str_,
        "AP": ap,
        "DMG": dmg,
        "NB": 1,
        "RNG": 24,
        "WEAPON_RULES": rules or [],
        "display_name": "Test Weapon",
    }


def _unit(uid: int, player: int, col: int, row: int, hp: int = 5) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": hp,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon()],
        "selectedRngWeaponIndex": 0,
        "_rapid_fire_rule_value": 0,
        "_rapid_fire_bonus_shot_current": False,
    }


def _make_game_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "max_base_size_hex": 35,
                "los_visibility_min_ratio": 0.0,
                "cover_ratio": 0.0,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "shoot",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "units_moved": set(),
        "units_advanced": set(),
        "shoot_activation_pool": [],
        "move_activation_pool": [],
        "charge_activation_pool": [],
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# DEVASTATING_WOUNDS
# ─────────────────────────────────────────────────────────────────────────────

class TestDevastatingWounds:

    def test_critical_wound_skips_save(self, monkeypatch):
        """dev_wounds_skip_save : blessure critique (wound=6) → save sauté."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"], dmg=2)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # dice: hit=5 (≥4 → success), wound=6 (critical)
        rolls = iter([5, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["save_skipped"] is True
        assert result["save_skip_reason"] == "DEVASTATING_WOUNDS"

    def test_critical_wound_applies_devastating_wounds_flag(self, monkeypatch):
        """dev_wounds_flag : wound=6 → devastating_wounds_applied=True."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"], dmg=2)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is True
        assert result["devastating_wounds_flag"] is True
        assert result["critical_wound_unmodified"] is True

    def test_critical_wound_deals_damage(self, monkeypatch):
        """dev_wounds_dmg : wound critique → damage = DMG (sans save)."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"], dmg=2)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["damage"] == 2

    def test_non_critical_wound_does_not_apply_devastating(self, monkeypatch):
        """dev_wounds_no_crit : wound=4 (non-crit) → devastating_wounds_applied=False, save requis."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"], dmg=2)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=5, wound=4 (non-crit), save=2 (fail)
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is False
        assert result["save_skipped"] is False

    def test_wound_fail_no_devastating(self, monkeypatch):
        """dev_wounds_wound_fail : wound raté → devastating_wounds_applied=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"], str_=1, dmg=2)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)  # T=4, STR=1 → wound 6+
        gs = _make_game_state([attacker, target])
        # hit=5, wound=3 (<6 → fail)
        rolls = iter([5, 3])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is False
        assert result["damage"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# HAZARDOUS
# ─────────────────────────────────────────────────────────────────────────────

class TestHazardous:

    def test_hazardous_roll_1_triggers(self, monkeypatch):
        """hazardous_triggered : roll=1 → hazardous_triggered=True."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HAZARDOUS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # dice order: hit=5, hazardous_roll=1, wound=4, save=2
        rolls = iter([5, 1, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_triggered"] is True
        assert result["hazardous_test_required"] is True
        assert result["hazardous_test_roll"] == 1

    def test_hazardous_roll_2_does_not_trigger(self, monkeypatch):
        """hazardous_safe : roll=3 → hazardous_triggered=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HAZARDOUS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=5, hazardous_roll=3, wound=4, save=2
        rolls = iter([5, 3, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_triggered"] is False
        assert result["hazardous_test_required"] is True

    def test_hazardous_triggered_on_miss(self, monkeypatch):
        """hazardous_miss_trigger : hit=2 (miss) + hazardous_roll=1 → hazardous_triggered=True."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HAZARDOUS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=2 (miss), hazardous_roll=1
        rolls = iter([2, 1])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is False
        assert result["hazardous_triggered"] is True

    def test_no_hazardous_rule_does_not_set_test_required(self, monkeypatch):
        """hazardous_none : arme sans HAZARDOUS → hazardous_test_required=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=[])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_test_required"] is False
        assert result["hazardous_triggered"] is False
        assert result["hazardous_test_roll"] is None

    def test_hazardous_roll_6_does_not_trigger(self, monkeypatch):
        """hazardous_roll6 : roll=6 → hazardous_triggered=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HAZARDOUS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=2 (miss), hazardous_roll=6
        rolls = iter([2, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_triggered"] is False
        assert result["hazardous_test_roll"] == 6

    def test_hazardous_test_roll_preserved_in_result(self, monkeypatch):
        """hazardous_roll_value : hazardous_test_roll retourné dans le résultat."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HAZARDOUS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=2 (miss), hazardous_roll=3
        rolls = iter([2, 3])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_test_roll"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# HEAVY rule
# ─────────────────────────────────────────────────────────────────────────────

class TestHeavyRule:

    def test_heavy_stationary_improves_hit_target(self, monkeypatch):
        """heavy_stationary : unité stationnaire → hit_target = ATK - 1."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=5)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # units_moved vide → stationnaire; hit=3 (<5 but ≥4 → success with HEAVY)
        rolls = iter([4, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_target"] == 4  # ATK=5 - 1 = 4

    def test_heavy_stationary_sets_hit_rule_modifier(self, monkeypatch):
        """heavy_modifier : stationnaire → hit_rule_modifier='HEAVY'."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=5)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])  # miss
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_rule_modifier"] == "HEAVY"

    def test_heavy_moved_no_improvement(self, monkeypatch):
        """heavy_moved : unité ayant bougé → hit_target = ATK (non amélioré)."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=5)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        gs["units_moved"] = {"1"}  # attacker a bougé
        rolls = iter([2])  # miss
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_target"] == 5  # ATK=5, pas d'amélioration

    def test_heavy_moved_no_modifier(self, monkeypatch):
        """heavy_moved_no_mod : unité ayant bougé → hit_rule_modifier=None."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=5)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        gs["units_moved"] = {"1"}
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_rule_modifier"] is None

    def test_heavy_advanced_no_improvement(self, monkeypatch):
        """heavy_advanced : unité avancée → hit_target = ATK (non amélioré)."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=5)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        gs["units_advanced"] = {"1"}  # attacker a avancé
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_target"] == 5

    def test_heavy_stationary_atk2_floor_at_2(self, monkeypatch):
        """heavy_floor : ATK=2, stationnaire → hit_target=max(2,1)=2 (pas 1)."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=2)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([1])  # miss (1 < 2)
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_target"] == 2  # floor: max(2, 2-1) = max(2,1) = 2

    def test_heavy_stationary_hit_target_base_preserved(self, monkeypatch):
        """heavy_base_preserved : hit_target_base = ATK original (non modifié)."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=5)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_target_base"] == 5  # base non modifié
        assert result["hit_target"] == 4       # effective avec HEAVY


# ─────────────────────────────────────────────────────────────────────────────
# Interactions multi-règles
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleInteractions:

    def test_devastating_wounds_no_hazardous_flag(self, monkeypatch):
        """dev_no_hazardous : arme DEV_WOUNDS sans HAZARDOUS → hazardous_test_required=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 6])  # hit + critical wound
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_test_required"] is False
        assert result["hazardous_triggered"] is False

    def test_hazardous_no_devastating_flag(self, monkeypatch):
        """haz_no_devastating : arme HAZARDOUS sans DEV_WOUNDS → devastating_wounds_applied=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HAZARDOUS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=5, hazardous_roll=1, wound=6 (critical but no DEVASTATING_WOUNDS)
        rolls = iter([5, 1, 6, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is False
        assert result["hazardous_triggered"] is True

    def test_heavy_and_devastating_wounds_stationary_critical(self, monkeypatch):
        """heavy_dev : HEAVY+DEV_WOUNDS, stationnaire, wound critique → skips save."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY", "DEVASTATING_WOUNDS"], atk=5, dmg=3)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # stationnaire (units_moved vide), hit=4 (≥4 avec HEAVY), wound=6 (crit)
        rolls = iter([4, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is True
        assert result["devastating_wounds_applied"] is True
        assert result["damage"] == 3

    def test_no_rules_weapon_all_flags_false(self, monkeypatch):
        """no_rules : arme sans règles spéciales → tous les flags spéciaux à False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=[])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is False
        assert result["hazardous_test_required"] is False
        assert result["hit_rule_modifier"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Structure du résultat — clés garanties par contrat
# ─────────────────────────────────────────────────────────────────────────────

class TestAttackResultStructure:

    def test_devastating_wound_result_has_wound_roll(self, monkeypatch):
        """struct_dev_wound_roll : wound=6 (devastating) → wound_roll=6 dans le résultat."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["wound_roll"] == 6
        assert result["wound_success"] is True

    def test_devastating_wound_result_save_roll_zero(self, monkeypatch):
        """struct_dev_save_zero : devastating → save_roll=0 (non lancé)."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["save_roll"] == 0
        assert result["save_skipped"] is True

    def test_result_has_weapon_name(self, monkeypatch):
        """struct_weapon_name : weapon_name retourné dans le résultat."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=[])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert "weapon_name" in result

    def test_miss_result_save_roll_zero(self, monkeypatch):
        """struct_miss_save_zero : miss → save_roll=0, save_skipped=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=[])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["save_roll"] == 0
        assert result["save_skipped"] is False

    def test_wound_fail_result_save_roll_zero(self, monkeypatch):
        """struct_wound_fail_save_zero : wound raté → save_roll=0."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(str_=1, rules=[])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)  # T=4, STR=1 → wound 6+
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 3])  # hit=5, wound=3 (<6 → fail)
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["save_roll"] == 0
        assert result["wound_success"] is False

    def test_hazardous_result_always_has_test_roll_when_rule_present(self, monkeypatch):
        """struct_haz_roll : HAZARDOUS toujours présent → hazardous_test_roll non-None."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HAZARDOUS"])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2, 4])  # miss, hazardous=4
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_test_roll"] is not None
        assert result["hazardous_test_required"] is True

    def test_heavy_result_hit_target_base_is_atk(self, monkeypatch):
        """struct_heavy_base : hit_target_base = ATK même avec HEAVY."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=4)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_target_base"] == 4

    def test_critical_wound_unmodified_only_on_wound_6(self, monkeypatch):
        """struct_crit_wound : critical_wound_unmodified=True uniquement si wound_roll=6."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=[])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=5, wound=4 (success, non-critical), save=2 (fail)
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["critical_wound_unmodified"] is False
        assert result["wound_roll"] == 4

    def test_critical_wound_6_sets_unmodified_flag(self, monkeypatch):
        """struct_crit_wound6 : wound_roll=6 → critical_wound_unmodified=True."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=[])]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # hit=5, wound=6 (critical, no DEVASTATING_WOUNDS), save=2 (fail)
        rolls = iter([5, 6, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["critical_wound_unmodified"] is True
        assert result["devastating_wounds_applied"] is False  # no rule


# ─────────────────────────────────────────────────────────────────────────────
# Règle HEAVY — cas limites supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestHeavyRuleEdgeCases:

    def test_heavy_allows_hit_where_non_heavy_would_miss(self, monkeypatch):
        """heavy_borderline : ATK=4, HEAVY stationnaire → hit_target=3, roll=3 réussit."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=4)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        # roll=3: <4 sans HEAVY (miss) mais ≥3 avec HEAVY (success)
        rolls = iter([3, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is True
        assert result["hit_target"] == 3

    def test_no_heavy_rule_hit_target_equals_atk(self, monkeypatch):
        """no_heavy : sans HEAVY → hit_target = ATK."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=[], atk=4)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_target"] == 4
        assert result["hit_rule_modifier"] is None

    def test_heavy_moved_allows_miss_that_heavy_would_hit(self, monkeypatch):
        """heavy_moved_miss : ATK=4, bougé, roll=3 → miss (HEAVY non appliqué)."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["HEAVY"], atk=4)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        gs["units_moved"] = {"1"}
        # roll=3: ≥3 si HEAVY mais <4 → miss car bougé
        rolls = iter([3])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is False
        assert result["hit_target"] == 4

    def test_devastating_wounds_wound_target_preserved_in_result(self, monkeypatch):
        """dev_wound_target : wound_target retourné dans le résultat même si save sauté."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(rules=["DEVASTATING_WOUNDS"], atk=4, str_=4)]
        attacker["selectedRngWeaponIndex"] = 0
        target = _unit(2, 2, 15, 10)  # T=4
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["wound_target"] == 4  # STR=4 vs T=4 → wound 4+
