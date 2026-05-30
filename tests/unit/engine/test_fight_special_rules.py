"""Règles spéciales d'armes — DEVASTATING_WOUNDS et HAZARDOUS dans _attack_sequence_rng."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shooting_handlers import _attack_sequence_rng
from engine.phase_handlers.shared_utils import build_units_cache


def _weapon(
    atk: int = 4,
    str_: int = 4,
    ap: int = 0,
    dmg: int = 1,
    rules: List[str] | None = None,
) -> Dict[str, Any]:
    return {
        "ATK": atk,
        "STR": str_,
        "AP": ap,
        "DMG": dmg,
        "NB": 1,
        "RNG": 24,
        "WEAPON_RULES": rules if rules is not None else ["IGNORES_COVER"],
        "display_name": "Test Cannon",
    }


def _unit(uid: int, player: int, col: int, row: int, hp: int = 4) -> Dict[str, Any]:
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
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "selectedRngWeaponIndex": 0,
        "_rapid_fire_rule_value": 0,
        "_rapid_fire_bonus_shot_current": False,
    }


def _make_game_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 1, "max_base_size_hex": 35},
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

class TestDevastatingWoundsShoot:
    """DEVASTATING_WOUNDS : wound critique (6) saute la sauvegarde."""

    def test_wound6_save_skipped_damage_applied(self, monkeypatch):
        """devwound_skip : wound_roll=6 + DEVASTATING_WOUNDS → save_skipped=True, dégâts appliqués."""
        # Dice order: hit_roll, wound_roll (no HAZARDOUS → no hazardous_roll)
        # ATK=4, hit_roll=4 → hit; wound_roll=6 → critical wound → devastating applied, save skipped
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=2, rules=["IGNORES_COVER", "DEVASTATING_WOUNDS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 6])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is True
        assert result["save_skipped"] is True
        assert result["save_skip_reason"] == "DEVASTATING_WOUNDS"
        assert result["damage"] == 2

    def test_wound5_no_devastating(self, monkeypatch):
        """devwound_no_crit : wound_roll=5 → pas critique → pas de devastating wounds."""
        # ATK=4, hit_roll=4, wound_roll=5 (STR=4/T=4 → wound 4+, success but not 6), save_roll=2 (fail)
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=1, rules=["IGNORES_COVER", "DEVASTATING_WOUNDS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 5, 2])  # hit=4, wound=5, save=2
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is False
        assert result["save_skipped"] is False
        assert result["damage"] == 1

    def test_miss_no_devastating(self, monkeypatch):
        """devwound_miss : miss → devastating_wounds_applied=False même avec la règle."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, dmg=1, rules=["IGNORES_COVER", "DEVASTATING_WOUNDS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([1])  # miss
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is False
        assert result["devastating_wounds_applied"] is False


# ─────────────────────────────────────────────────────────────────────────────
# HAZARDOUS
# ─────────────────────────────────────────────────────────────────────────────

class TestHazardousShoot:
    """HAZARDOUS : test obligatoire sur le tireur, roll=1 → triggered."""

    def test_roll1_triggered(self, monkeypatch):
        """hazardous_trigger : hazardous_roll=1 → hazardous_triggered=True."""
        # Dice order: hit_roll, hazardous_roll, wound_roll, save_roll
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=1, rules=["IGNORES_COVER", "HAZARDOUS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 1, 4, 2])  # hit, hazardous=1(trigger), wound, save
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_test_required"] is True
        assert result["hazardous_test_roll"] == 1
        assert result["hazardous_triggered"] is True

    def test_roll2_not_triggered(self, monkeypatch):
        """hazardous_no_trigger : hazardous_roll=2 → hazardous_triggered=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=1, rules=["IGNORES_COVER", "HAZARDOUS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 2, 4, 2])  # hit, hazardous=2(safe), wound, save
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_test_required"] is True
        assert result["hazardous_test_roll"] == 2
        assert result["hazardous_triggered"] is False

    def test_no_hazardous_rule_no_test(self, monkeypatch):
        """hazardous_absent : arme sans HAZARDOUS → hazardous_test_required=False."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=1, rules=["IGNORES_COVER"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 4, 2])  # hit, wound, save
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hazardous_test_required"] is False
        assert result["hazardous_test_roll"] is None
        assert result["hazardous_triggered"] is False

    def test_hazardous_on_miss_still_requires_test(self, monkeypatch):
        """hazardous_miss : miss + HAZARDOUS → hazardous_test_required=True (risque même sans toucher)."""
        # Dice order on miss with HAZARDOUS: hit_roll, hazardous_roll
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=1, rules=["IGNORES_COVER", "HAZARDOUS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([1, 3])  # miss, hazardous_roll=3(safe)
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is False
        assert result["hazardous_test_required"] is True
        assert result["hazardous_triggered"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Combinaison DEVASTATING_WOUNDS + HAZARDOUS
# ─────────────────────────────────────────────────────────────────────────────

class TestDevastatingWoundsAndHazardousCombined:
    """Règles combinées sur la même arme."""

    def test_devastating_and_hazardous_wound6_triggered(self, monkeypatch):
        """combo_both : DEVASTATING+HAZARDOUS, hazardous_roll=1, wound_roll=6 → les deux actifs."""
        # Dice order: hit_roll, hazardous_roll, wound_roll (devastating → pas de save_roll)
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=2,
                                           rules=["IGNORES_COVER", "DEVASTATING_WOUNDS", "HAZARDOUS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 1, 6])  # hit, hazardous=1(trigger), wound=6(devastating)
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is True
        assert result["hazardous_triggered"] is True
        assert result["save_skipped"] is True

    def test_devastating_and_hazardous_hazardous_safe(self, monkeypatch):
        """combo_hazardous_safe : DEVASTATING+HAZARDOUS, hazardous_roll=3, wound_roll=6 → devastating mais pas hazardous."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=1,
                                           rules=["IGNORES_COVER", "DEVASTATING_WOUNDS", "HAZARDOUS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 3, 6])  # hit, hazardous=3(safe), wound=6(devastating)
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is True
        assert result["hazardous_triggered"] is False

    def test_devastating_and_hazardous_no_critical_wound(self, monkeypatch):
        """combo_no_crit : DEVASTATING+HAZARDOUS, wound_roll=5 → pas de devastating, save normal."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, dmg=1,
                                           rules=["IGNORES_COVER", "DEVASTATING_WOUNDS", "HAZARDOUS"])]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 2, 5, 2])  # hit, hazardous_roll=2, wound=5, save=2(fail)
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["devastating_wounds_applied"] is False
        assert result["save_skipped"] is False
        assert result["damage"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Résultats retournés — structure de la réponse
# ─────────────────────────────────────────────────────────────────────────────

class TestAttackSequenceResultStructure:
    """Vérification de la structure complète du résultat de _attack_sequence_rng."""

    def test_hit_success_fields_present(self, monkeypatch):
        """result_fields_hit : touche réussie → tous les champs attendus présents."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon()]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        for field in ("hit_roll", "hit_target", "hit_success", "wound_roll", "wound_target",
                      "wound_success", "save_roll", "save_target", "save_success",
                      "damage", "attack_log", "weapon_name"):
            assert field in result, f"Champ manquant : {field}"

    def test_miss_result_fields_present(self, monkeypatch):
        """result_fields_miss : miss → champs obligatoires présents."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon()]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([1])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is False
        assert result["damage"] == 0
        assert "attack_log" in result

    def test_wound_fail_damage_is_zero(self, monkeypatch):
        """result_wound_fail : touche mais blessure ratée → damage=0."""
        # ATK=4, STR=2/T=4 → wound 6+, dice: hit=4(ok), wound=3(<6, fail)
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=2, dmg=3)]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 3])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is True
        assert result["wound_success"] is False
        assert result["damage"] == 0

    def test_save_success_damage_is_zero(self, monkeypatch):
        """result_save_success : save réussi → damage=0."""
        # ATK=4, wound 4+, ARMOR_SAVE=2 (très bon) → save facile
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, ap=0, dmg=3)]
        target = _unit(2, 2, 15, 10)
        target["ARMOR_SAVE"] = 2  # save 2+
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 4, 5])  # hit, wound, save=5(≥2 → succeed)
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["save_success"] is True
        assert result["damage"] == 0

    def test_attack_log_not_empty(self, monkeypatch):
        """result_log_nonempty : attack_log toujours rempli."""
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon()]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([4, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert isinstance(result["attack_log"], str)
        assert len(result["attack_log"]) > 0

    def test_weapon_name_in_result(self, monkeypatch):
        """result_weapon_name : weapon_name correspond au display_name de l'arme."""
        attacker = _unit(1, 1, 5, 10)
        weapon = _weapon()
        weapon["display_name"] = "Plasma Gun"
        attacker["RNG_WEAPONS"] = [weapon]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([1])  # miss
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["weapon_name"] == "Plasma Gun"
