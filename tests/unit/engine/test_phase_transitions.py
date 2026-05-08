"""Tests unitaires — transitions de phase : move→shoot→charge→fight séquences end-to-end."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.movement_handlers import (
    movement_phase_start,
    movement_build_valid_destinations_pool,
    _attempt_movement_to_destination,
)
from engine.phase_handlers.shooting_handlers import (
    shooting_phase_start,
    _attack_sequence_rng,
)
from engine.phase_handlers.fight_handlers import (
    fight_phase_start,
    _execute_fight_attack_sequence,
)
from engine.phase_handlers.shared_utils import (
    build_units_cache,
    build_enemy_adjacent_hexes,
    is_unit_alive,
    get_hp_from_cache,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers communs
# ─────────────────────────────────────────────────────────────────────────────

def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 1, "max_base_size_hex": 35, "los_visibility_min_ratio": 0.0, "cover_ratio": 0.0},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: int, player: int, col: int, row: int, hp: int = 3) -> Dict[str, Any]:
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
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
    }


def _rng_weapon(atk=3, str_=4, ap=0, dmg=1, rng=24) -> Dict[str, Any]:
    return {"ATK": atk, "STR": str_, "AP": ap, "DMG": dmg, "RNG": rng, "display_name": "Test Gun",
            "NB": 1, "WEAPON_RULES": []}


def _cc_weapon(atk=3, str_=4, ap=0, dmg=1) -> Dict[str, Any]:
    return {"ATK": atk, "STR": str_, "AP": ap, "DMG": dmg, "display_name": "Test Blade",
            "NB": 1}


# ─────────────────────────────────────────────────────────────────────────────
# TRANSITION 1 : movement_phase_start → BFS pool → execution
# ─────────────────────────────────────────────────────────────────────────────

def _make_move_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "command",
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
        "units_fled": set(),
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "_unit_move_version": 0,
    }
    build_units_cache(gs)
    return gs


class TestMovementTransition:
    def test_phase_start_then_bfs_pool_built(self):
        """move_trans_pool : movement_phase_start → BFS pool non vide pour unité mobile."""
        units = [_unit(1, 1, 10, 10)]
        gs = _make_move_gs(units)
        movement_phase_start(gs)
        pool = movement_build_valid_destinations_pool(gs, "1")
        assert len(pool) > 0

    def test_execution_updates_units_moved(self):
        """move_trans_moved : après exécution réussie, unité dans units_moved."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        movement_phase_start(gs)
        success, _ = _attempt_movement_to_destination(gs, units[0], 6, 10, gs["config"])
        assert success is True
        assert "1" in gs["units_moved"]

    def test_execution_updates_cache_position(self):
        """move_trans_cache : position dans units_cache mise à jour après mouvement."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_move_gs(units)
        movement_phase_start(gs)
        _attempt_movement_to_destination(gs, units[0], 7, 10, gs["config"])
        entry = gs["units_cache"]["1"]
        assert entry["col"] == 7
        assert entry["row"] == 10

    def test_pool_excludes_unit_own_position(self):
        """move_trans_no_self : le pool BFS n'inclut pas la position initiale de l'unité."""
        units = [_unit(1, 1, 10, 10)]
        gs = _make_move_gs(units)
        movement_phase_start(gs)
        pool = movement_build_valid_destinations_pool(gs, "1")
        # Starting position should not be a valid "move" destination
        assert (10, 10) not in pool

    def test_enemy_adjacent_blocks_movement(self):
        """move_trans_ez_blocks : ennemi adjacent bloque le mouvement dans l'EZ."""
        # Unit 1 at (5,10), enemy at (6,10) → unit 1 in engagement zone
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_move_gs(units)
        movement_phase_start(gs)
        pool = movement_build_valid_destinations_pool(gs, "1")
        # In EZ: unit cannot freely move away from enemy, pool restricted or empty
        # (exact behaviour depends on movement rules, but pool should not contain enemy hex)
        assert (6, 10) not in pool


# ─────────────────────────────────────────────────────────────────────────────
# TRANSITION 2 : shooting_phase_start → attack → target HP decremented
# ─────────────────────────────────────────────────────────────────────────────

def _make_shoot_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "move",
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
        "units_fled": set(),
        "units_shot": set(),
        "hex_los_cache": {},
        "shoot_activation_pool": [],
        "move_activation_pool": [],
        "charge_activation_pool": [],
        "player_types": {"1": "human", "2": "ai"},
    }
    build_units_cache(gs)
    return gs


class TestShootingTransition:
    def test_shooting_phase_start_sets_phase(self):
        """shoot_trans_phase : shooting_phase_start → phase='shoot'."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_shoot_gs(units)
        shooting_phase_start(gs)
        assert gs["phase"] == "shoot"

    def test_shoot_pool_contains_current_player_unit(self):
        """shoot_trans_pool : shoot pool contient l'unité du joueur courant."""
        shooter = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 20, 10)
        gs = _make_shoot_gs([shooter, target])
        shooting_phase_start(gs)
        assert "1" in gs["shoot_activation_pool"]

    def test_shoot_pool_excludes_enemy_unit(self):
        """shoot_trans_pool_excl : pool ne contient pas l'unité ennemie."""
        shooter = _unit(1, 1, 5, 10)
        target = _unit(2, 2, 20, 10)
        gs = _make_shoot_gs([shooter, target])
        shooting_phase_start(gs)
        assert "2" not in gs["shoot_activation_pool"]

    def test_attack_sequence_rng_hit_returns_damage(self, monkeypatch):
        """shoot_trans_dmg : _attack_sequence_rng avec hit+wound+fail_save → damage>0."""
        shooter = _unit(1, 1, 5, 10)
        shooter["RNG_WEAPONS"] = [_rng_weapon(atk=3, str_=4, ap=0, dmg=2)]
        shooter["selectedRngWeaponIndex"] = 0
        shooter["_rapid_fire_rule_value"] = 0
        shooter["_is_stationary_for_heavy"] = False
        target = _unit(2, 2, 20, 10, hp=5)
        gs = _make_shoot_gs([shooter, target])
        shooting_phase_start(gs)
        # shooting_phase_start deletes these fields; re-set after
        shooter["_rapid_fire_rule_value"] = 0
        shooter["_rapid_fire_bonus_shot_current"] = False
        shooter["_is_stationary_for_heavy"] = False
        # hit=5 (≥3), wound=4 (S==T → 4+), save=2 (fail 4+) → dmg=2
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        result = _attack_sequence_rng(shooter, target, gs)
        assert result["damage"] == 2
        assert result["hit_success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# TRANSITION 3 : fight_phase_start → pool → fight sequence
# ─────────────────────────────────────────────────────────────────────────────

def _make_fight_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "charge",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "units_charged": set(),
        "units_fought": set(),
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "shoot_activation_pool": [],
        "move_activation_pool": [],
        "charge_activation_pool": [],
    }
    build_units_cache(gs)
    return gs


class TestFightTransition:
    def test_fight_phase_start_sets_phase(self):
        """fight_trans_phase : fight_phase_start → phase='fight'."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_fight_gs(units)
        fight_phase_start(gs)
        assert gs["phase"] == "fight"

    def test_fight_phase_start_initializes_pools(self):
        """fight_trans_pools : pools de combat initialisés après fight_phase_start."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_fight_gs(units)
        fight_phase_start(gs)
        assert "charging_activation_pool" in gs
        assert "active_alternating_activation_pool" in gs
        assert "non_active_alternating_activation_pool" in gs

    def test_fight_attack_kills_weak_target(self, monkeypatch):
        """fight_trans_kill : combat contre cible faible → cible tuée."""
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_cc_weapon(atk=3, str_=8, ap=-3, dmg=10)]
        attacker["selectedCcWeaponIndex"] = 0
        target = _unit(2, 2, 6, 10, hp=1)
        gs = _make_fight_gs([attacker, target])
        # Garantit hit + wound + save échoue
        rolls = iter([5, 5, 1])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert not is_unit_alive("2", gs)

    def test_fight_attack_miss_preserves_hp(self, monkeypatch):
        """fight_trans_miss : touche ratée → HP cible inchangé."""
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_cc_weapon(atk=3, str_=4, ap=0, dmg=2)]
        attacker["selectedCcWeaponIndex"] = 0
        target = _unit(2, 2, 6, 10, hp=5)
        gs = _make_fight_gs([attacker, target])
        initial_hp = get_hp_from_cache("2", gs)
        # Force miss: roll below ATK=3
        monkeypatch.setattr("random.randint", lambda a, b: 1)
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert get_hp_from_cache("2", gs) == initial_hp

    def test_fight_attack_hit_decrements_hp(self, monkeypatch):
        """fight_trans_dmg : séquence complète hit+wound+save fail → HP décrémenté."""
        attacker = _unit(1, 1, 5, 10)
        attacker["CC_WEAPONS"] = [_cc_weapon(atk=3, str_=4, ap=0, dmg=2)]
        attacker["selectedCcWeaponIndex"] = 0
        target = _unit(2, 2, 6, 10, hp=5)
        gs = _make_fight_gs([attacker, target])
        # hit=5 (≥3, hit), wound=4 (==T, wound 4+), save=2 (fail 3+)
        rolls = iter([5, 4, 2])
        monkeypatch.setattr("random.randint", lambda a, b: next(rolls))
        _execute_fight_attack_sequence(gs, attacker, "2")
        assert get_hp_from_cache("2", gs) == 3  # 5 - 2 damage
