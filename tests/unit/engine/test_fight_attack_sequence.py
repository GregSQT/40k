"""Séquence d'attaque combat — _execute_fight_attack_sequence end-to-end avec dés fixés."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.fight_handlers import _execute_fight_attack_sequence
from engine.phase_handlers.shared_utils import build_units_cache, get_hp_from_cache, is_unit_alive


def _weapon(atk: int = 3, str_: int = 4, ap: int = 0, dmg: int = 1) -> Dict[str, Any]:
    return {"ATK": atk, "STR": str_, "AP": ap, "DMG": dmg, "display_name": "Test Blade"}


def _unit(uid: int, player: int, col: int, row: int, hp: int = 4) -> Dict[str, Any]:
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
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 0,
        "CC_WEAPONS": [_weapon()],
        "selectedCcWeaponIndex": 0,
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
        "phase": "fight",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "turn": 1,
        "action_log_seq": 0,
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "shoot_activation_pool": [],
        "move_activation_pool": [],
        "charge_activation_pool": [],
    }
    build_units_cache(gs)
    return gs


class TestFightAttackSequenceHit:
    def test_hit_wound_save_fail_hp_decremented(self, monkeypatch):
        """fight_seq_dmg : touche+blesse+save échoue → HP décrémenté."""
        # ATK=3 (need ≥3), STR=4/T=4 → wound 4+, ARMOR_SAVE=3/AP=0 → save 3+
        # dice: hit=5 (hit), wound=4 (wound), save=2 (fail → dmg=2 applied)
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_weapon(atk=3, str_=4, ap=0, dmg=2)]
        target = _unit(2, 2, 6, 10, hp=5)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert get_hp_from_cache("2", gs) == 3  # 5 - 2

    def test_miss_no_damage(self, monkeypatch):
        """fight_seq_miss : jet de touche raté → HP inchangé."""
        # hit=1 < ATK=3 → miss immediately
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 6, 10, hp=3)
        gs = _make_game_state([attacker, target])
        rolls = iter([1])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert get_hp_from_cache("2", gs) == 3

    def test_wound_fail_no_damage(self, monkeypatch):
        """fight_seq_wound_fail : touche réussie mais blessure ratée → HP inchangé."""
        # ATK=3, STR=2/T=4 → wound 6+; dice: hit=5, wound=3 (<6)
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_weapon(atk=3, str_=2, ap=0, dmg=1)]
        target = _unit(2, 2, 6, 10, hp=3)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 3])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert get_hp_from_cache("2", gs) == 3

    def test_save_success_no_damage(self, monkeypatch):
        """fight_seq_save : touche+blesse+save réussi → HP inchangé."""
        # ATK=3, STR=4/T=4 → wound 4+, ARMOR_SAVE=3/AP=0 → save 3+
        # dice: hit=5, wound=4, save=5 (≥3 → success)
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 6, 10, hp=4)
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 5])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert get_hp_from_cache("2", gs) == 4


class TestFightAttackSequenceKill:
    def test_target_killed_removed_from_cache(self, monkeypatch):
        """fight_seq_kill : dégâts létaux → cible retirée du cache et is_unit_alive=False."""
        # hp=1, DMG=1, ARMOR_SAVE=6 → save on 6+
        # dice: hit=5, wound=4, save=2 (<6 → fail, dmg=1 kills 1HP)
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_weapon(atk=3, str_=4, ap=0, dmg=1)]
        target = _unit(2, 2, 6, 10, hp=1)
        target["ARMOR_SAVE"] = 6
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert is_unit_alive("2", gs) is False
        assert "2" not in gs["units_cache"]

    def test_target_killed_removed_from_fight_pools(self, monkeypatch):
        """fight_seq_kill_pool : mort → unité retirée des pools de combat."""
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_weapon(atk=3, str_=4, ap=0, dmg=1)]
        target = _unit(2, 2, 6, 10, hp=1)
        target["ARMOR_SAVE"] = 6
        gs = _make_game_state([attacker, target])
        gs["charging_activation_pool"] = ["2"]
        gs["active_alternating_activation_pool"] = ["2"]
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert "2" not in gs["charging_activation_pool"]
        assert "2" not in gs["active_alternating_activation_pool"]

    def test_attacker_hp_unchanged_after_kill(self, monkeypatch):
        """fight_seq_kill_attacker_intact : attaquant HP inchangé après avoir tué la cible."""
        attacker = _unit(1, 1, 5, 10, hp=3)
        attacker["CC_WEAPONS"] = [_weapon(atk=3, str_=4, ap=0, dmg=1)]
        target = _unit(2, 2, 6, 10, hp=1)
        target["ARMOR_SAVE"] = 6
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert get_hp_from_cache("1", gs) == 3


class TestFightAttackSequenceLog:
    def test_action_log_appended_on_miss(self, monkeypatch):
        """fight_seq_log_miss : action_log rempli même en cas de raté."""
        attacker = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 6, 10)
        gs = _make_game_state([attacker, target])
        rolls = iter([1])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert len(gs["action_logs"]) >= 1
        assert gs["action_logs"][0]["type"] == "combat"

    def test_action_log_appended_on_hit(self, monkeypatch):
        """fight_seq_log_hit : action_log rempli en cas de touche+dégâts."""
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_weapon(atk=3, str_=4, ap=0, dmg=1)]
        target = _unit(2, 2, 6, 10, hp=3)
        target["ARMOR_SAVE"] = 6
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert any(log["type"] == "combat" for log in gs["action_logs"])

    def test_death_log_on_kill(self, monkeypatch):
        """fight_seq_log_death : log 'death' ajouté si la cible est tuée."""
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_weapon(atk=3, str_=4, ap=0, dmg=1)]
        target = _unit(2, 2, 6, 10, hp=1)
        target["ARMOR_SAVE"] = 6
        gs = _make_game_state([attacker, target])
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert any(log["type"] == "death" for log in gs["action_logs"])
