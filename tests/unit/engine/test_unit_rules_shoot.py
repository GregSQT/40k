"""Tests unitaires — UNIT_RULES dynamiques en shooting.

Couvre les règles non testées jusqu'ici :
- reroll_1_towound : reroll d'un 1 au jet de blessure
- reroll_towound_target_on_objective : reroll de blessure si cible sur objectif
- closest_target_penetration : AP amélioré contre la cible la plus proche

Stratégie : utiliser _attack_sequence_rng avec dés fixés par monkeypatch,
unités portant les bonnes UNIT_RULES.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from engine.phase_handlers.shooting_handlers import _attack_sequence_rng
from engine.phase_handlers.shared_utils import build_units_cache


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _weapon(atk=4, str_=4, ap=0, dmg=1) -> Dict[str, Any]:
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


def _unit_rule(rule_id: str, display_name: str = "Test Rule") -> Dict[str, Any]:
    """Entrée UNIT_RULES directe (ruleId = effect_id, pas de grants)."""
    return {
        "ruleId": rule_id,
        "displayName": display_name,
    }


def _attacker(uid: int, col: int, row: int, rules: Optional[List[Dict]] = None, ap: int = 0) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": 1,
        "col": col,
        "row": row,
        "HP_CUR": 4,
        "HP_MAX": 4,
        "VALUE": 100,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": rules or [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [_weapon(ap=ap)],
        "CC_WEAPONS": [],
        "selectedRngWeaponIndex": 0,
        "_rapid_fire_rule_value": 0,
        "_rapid_fire_bonus_shot_current": False,
        "OC": 1,
        "unitType": "TestUnit",
        "DISPLAY_NAME": f"Attacker {uid}",
    }


def _target(uid: int, col: int, row: int, t: int = 4, save: int = 4) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": 2,
        "col": col,
        "row": row,
        "HP_CUR": 4,
        "HP_MAX": 4,
        "VALUE": 100,
        "BASE_SIZE": 1,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": t,
        "ARMOR_SAVE": save,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 0,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "OC": 1,
    }


def _make_gs(units: List[Dict[str, Any]], obj_hex=(5, 5)) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "max_base_size_hex": 35,
                "cover_ratio": 0.0,
                "los_visibility_min_ratio": 0.0,
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
        "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [list(obj_hex)]}],
        "weapon_rule": 1,  # requis par les handlers de tir
        "episode_number": 1,
        "debug_mode": False,
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_attacked": set(),
        "units_charged": set(),
        "units_shot": set(),
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Tests — reroll_1_towound
# ─────────────────────────────────────────────────────────────────────────────

class TestReroll1ToWound:

    def test_reroll_1_towound_activated_on_wound_roll_1(self, monkeypatch):
        """rule_reroll1_wound : wound_roll=1 déclenche le reroll via reroll_1_towound."""
        rule = _unit_rule("reroll_1_towound", "Lethal Hits")
        attacker = _attacker(1, 5, 10, rules=[rule])
        # STR=4/T=4 → wound 4+; save=6 (toujours fail avec save=6+)
        target = _target(2, 15, 10, t=4, save=6)
        gs = _make_gs([attacker, target])

        # Séquence: hit=5 (OK), wound=1 (FAIL → reroll), wound_reroll=4 (SUCCESS), save=2 (FAIL)
        rolls = iter([5, 1, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, target, gs)

        assert result["wound_success"] is True
        assert result["wound_ability_display_name"] == "LETHAL HITS"

    def test_reroll_1_towound_not_activated_on_wound_roll_2(self, monkeypatch):
        """rule_reroll1_wound_no_trigger : wound_roll=2 → pas de reroll (règle inactive)."""
        rule = _unit_rule("reroll_1_towound", "Lethal Hits")
        attacker = _attacker(1, 5, 10, rules=[rule])
        # STR=2/T=4 → wound 6+
        attacker["RNG_WEAPONS"] = [_weapon(str_=2)]
        target = _target(2, 15, 10, t=4, save=4)
        gs = _make_gs([attacker, target])

        # hit=5 (OK), wound=2 (FAIL, mais 2 != 1 → pas de reroll)
        rolls = iter([5, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, target, gs)

        assert result["wound_success"] is False
        assert result["wound_ability_display_name"] is None

    def test_no_reroll_1_towound_rule_no_reroll(self, monkeypatch):
        """rule_no_reroll1 : sans la règle, wound_roll=1 ne reroll pas."""
        attacker = _attacker(1, 5, 10, rules=[])  # pas de règle
        target = _target(2, 15, 10, t=4, save=6)
        gs = _make_gs([attacker, target])

        # hit=5 (OK), wound=1 (FAIL, pas de reroll)
        rolls = iter([5, 1])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, target, gs)

        assert result["wound_success"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests — reroll_towound_target_on_objective
# ─────────────────────────────────────────────────────────────────────────────

class TestRerollWoundTargetOnObjective:

    def test_reroll_wound_on_objective_triggers_when_target_on_obj(self, monkeypatch):
        """rule_reroll_obj : cible sur objectif → reroll de blessure déclenché."""
        rule = _unit_rule("reroll_towound_target_on_objective", "Objective Mastery")
        attacker = _attacker(1, 3, 3, rules=[rule])
        # Cible SUR l'objectif hex (5,5), STR=4/T=5 → wound 5+
        target = _target(2, 5, 5, t=5, save=4)
        gs = _make_gs([attacker, target], obj_hex=(5, 5))

        # hit=5 (OK), wound=3 (FAIL < 5+), reroll wound=5 (SUCCESS), save=2 (FAIL)
        rolls = iter([5, 3, 5, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, target, gs)

        assert result["wound_success"] is True
        assert result["wound_ability_display_name"] == "OBJECTIVE MASTERY"

    def test_reroll_wound_on_objective_no_trigger_when_target_off_obj(self, monkeypatch):
        """rule_reroll_obj_off : cible hors objectif → pas de reroll."""
        rule = _unit_rule("reroll_towound_target_on_objective", "Objective Mastery")
        attacker = _attacker(1, 3, 3, rules=[rule])
        # Cible HORS de l'objectif (0,0), STR=4/T=5 → wound 5+
        target = _target(2, 0, 0, t=5, save=4)
        gs = _make_gs([attacker, target], obj_hex=(5, 5))

        # hit=5 (OK), wound=3 (FAIL) → pas de reroll car cible hors obj
        rolls = iter([5, 3])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, target, gs)

        assert result["wound_success"] is False
        assert result["wound_ability_display_name"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Tests — closest_target_penetration
# ─────────────────────────────────────────────────────────────────────────────

class TestClosestTargetPenetration:

    def test_closest_target_penetration_improves_ap_when_closest(self, monkeypatch):
        """rule_ctp : closest_target_penetration améliore AP contre la cible la plus proche.

        On mocke shooting_build_valid_target_pool pour retourner uniquement la cible.
        """
        import engine.phase_handlers.shooting_handlers as sh

        rule = _unit_rule("closest_target_penetration", "Armour-Piercing Rounds")
        attacker = _attacker(1, 5, 10, rules=[rule], ap=0)
        target = _target(2, 6, 10, t=4, save=4)
        gs = _make_gs([attacker, target])

        # Mock : seule la cible (uid=2) est dans le pool → elle est la plus proche par définition
        monkeypatch.setattr(sh, "shooting_build_valid_target_pool", lambda gs, uid, **kw: ["2"])

        # hit=5 (OK), wound=4 (SUCCESS), save=2 (FAIL même AP=0)
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, target, gs)

        assert result["ap_modifier_ability_display_name"] == "ARMOUR-PIERCING ROUNDS"

    def test_closest_target_penetration_no_effect_when_pool_empty(self, monkeypatch):
        """rule_ctp_empty_pool : pool vide → AP non amélioré (rule inactive)."""
        import engine.phase_handlers.shooting_handlers as sh

        rule = _unit_rule("closest_target_penetration", "Armour-Piercing Rounds")
        attacker = _attacker(1, 5, 10, rules=[rule], ap=0)
        target = _target(2, 15, 10, t=4, save=4)
        gs = _make_gs([attacker, target])

        # Mock : pool vide → la règle CTP ne s'applique pas
        monkeypatch.setattr(sh, "shooting_build_valid_target_pool", lambda gs, uid, **kw: [])

        rolls = iter([5, 4, 4])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, target, gs)

        assert result["ap_modifier_ability_display_name"] is None

    def test_closest_target_penetration_no_effect_on_non_closest(self, monkeypatch):
        """rule_ctp_not_closest : cible pas la plus proche → AP non amélioré."""
        import engine.phase_handlers.shooting_handlers as sh

        rule = _unit_rule("closest_target_penetration", "Armour-Piercing Rounds")
        attacker = _attacker(1, 5, 10, rules=[rule], ap=0)
        close_enemy = _target(2, 6, 10, t=4, save=4)    # uid=2, plus proche
        far_target = _target(3, 15, 10, t=4, save=4)    # uid=3, cible plus loin
        gs = _make_gs([attacker, close_enemy, far_target])

        # Mock : les deux ennemis dans le pool, mais uid=2 est le plus proche
        monkeypatch.setattr(sh, "shooting_build_valid_target_pool", lambda gs, uid, **kw: ["2", "3"])

        rolls = iter([5, 4, 4])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))

        result = _attack_sequence_rng(attacker, far_target, gs)

        # cible uid=3 n'est pas la plus proche (uid=2 est à distance 1, uid=3 à distance 10)
        assert result["ap_modifier_ability_display_name"] is None
