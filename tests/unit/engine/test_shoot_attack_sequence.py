"""Séquence d'attaque tir — _attack_sequence_rng end-to-end avec dés fixés."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shooting_handlers import _attack_sequence_rng
from engine.phase_handlers.shared_utils import build_units_cache


def _weapon(atk: int = 4, str_: int = 4, ap: int = 0, dmg: int = 1, nb: int = 1) -> Dict[str, Any]:
    return {
        "ATK": atk,
        "STR": str_,
        "AP": ap,
        "DMG": dmg,
        "NB": nb,
        "RNG": 24,
        "WEAPON_RULES": ["IGNORES_COVER"],  # contourne le calcul de couverture
        "display_name": "Test Bolter",
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
        "RNG_WEAPONS": [_weapon()],
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


class TestShootAttackSequenceOutcomes:
    def test_hit_wound_save_fail_returns_damage(self, monkeypatch):
        """shoot_seq_dmg : touche+blesse+save échoue → damage > 0 dans le résultat."""
        # ATK=4 (≥4), STR=4/T=4 → wound 4+, ARMOR_SAVE=4/AP=0 → save 4+
        # dice: hit=5 (≥4), wound=4 (≥4), save=2 (<4 → fail, dmg=1)
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is True
        assert result["wound_success"] is True
        assert result["save_success"] is False
        assert result["damage"] == 1

    def test_miss_returns_no_damage(self, monkeypatch):
        """shoot_seq_miss : jet de touche raté → damage=0, hit_success=False."""
        # ATK=4, hit=2 → miss
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is False
        assert result["damage"] == 0

    def test_wound_fail_returns_no_damage(self, monkeypatch):
        """shoot_seq_wound_fail : touche réussie+blessure ratée → damage=0."""
        # ATK=4, STR=2/T=4 → wound 6+; dice: hit=5, wound=3 (<6)
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=2, ap=0, dmg=1)]
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 3])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is True
        assert result["wound_success"] is False
        assert result["damage"] == 0

    def test_save_success_returns_no_damage(self, monkeypatch):
        """shoot_seq_save : touche+blesse+save réussi → damage=0, save_success=True."""
        # ATK=4, STR=4/T=4 → wound 4+, ARMOR_SAVE=4/AP=0 → save 4+
        # dice: hit=5, wound=4, save=5 (≥4 → success)
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 5])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_success"] is True
        assert result["wound_success"] is True
        assert result["save_success"] is True
        assert result["damage"] == 0


class TestShootAttackSequenceResult:
    def test_result_contains_required_keys(self, monkeypatch):
        """shoot_seq_keys : le dict résultat contient les champs requis."""
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([2])  # miss
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        for key in ("hit_success", "wound_success", "save_success", "damage", "attack_log"):
            assert key in result, f"Champ manquant : {key}"

    def test_full_hit_rolls_recorded(self, monkeypatch):
        """shoot_seq_rolls_recorded : hit_roll et wound_roll présents dans le résultat."""
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 15, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["hit_roll"] == 5
        assert result["wound_roll"] == 4
        assert result["save_roll"] == 2

    def test_ap_modifies_save_target(self, monkeypatch):
        """shoot_seq_ap : AP négatif aggrave le save → save qui aurait réussi devient échec."""
        # ARMOR_SAVE=4, AP=-1 → modified_armor_save = 4 - (-1) = 5 → save 5+
        # dice: hit=5, wound=4, save=4 (< 5 → fail malgré save "naturel" de 4+)
        attacker = _unit(1, 1, 5, 10)
        attacker["RNG_WEAPONS"] = [_weapon(atk=4, str_=4, ap=-1, dmg=1)]
        target = _unit(2, 2, 15, 10)
        target["ARMOR_SAVE"] = 4
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 4])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(attacker, target, gs)
        assert result["save_success"] is False
        assert result["damage"] == 1
