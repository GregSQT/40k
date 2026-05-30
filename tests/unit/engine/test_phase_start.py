"""Initialisation des phases — movement_phase_start, shooting_phase_start, fight_phase_start."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.movement_handlers import movement_phase_start
from engine.phase_handlers.shooting_handlers import shooting_phase_start
from engine.phase_handlers.fight_handlers import fight_phase_start
from engine.phase_handlers.shared_utils import build_units_cache


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
    }


def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": {"engagement_zone": 1, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _make_movement_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


def _make_shooting_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        "shoot_activation_pool": [],
        "move_activation_pool": [],
        "charge_activation_pool": [],
        "player_types": {"1": "human", "2": "ai"},
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


def _make_fight_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# movement_phase_start
# ─────────────────────────────────────────────────────────────────────────────

class TestMovementPhaseStart:
    def test_phase_set_to_move(self):
        """move_start_phase : movement_phase_start set phase='move'."""
        units = [_unit(1, 1, 10, 10)]
        gs = _make_movement_state(units)
        movement_phase_start(gs)
        assert gs["phase"] == "move"

    def test_units_cache_present(self):
        """move_start_cache : units_cache présent après movement_phase_start."""
        units = [_unit(1, 1, 10, 10)]
        gs = _make_movement_state(units)
        movement_phase_start(gs)
        assert "units_cache" in gs
        assert "1" in gs["units_cache"]

    def test_enemy_adjacent_hexes_built_for_current_player(self):
        """move_start_adj : enemy_adjacent_hexes_player_1 construit à l'initialisation."""
        units = [_unit(1, 1, 10, 10), _unit(2, 2, 20, 10)]
        gs = _make_movement_state(units)
        movement_phase_start(gs)
        assert "enemy_adjacent_hexes_player_1" in gs

    def test_move_activation_pool_initialized(self):
        """move_start_pool : move_activation_pool initialisé après movement_phase_start."""
        units = [_unit(1, 1, 10, 10)]
        gs = _make_movement_state(units)
        movement_phase_start(gs)
        assert "move_activation_pool" in gs

    def test_eligible_unit_in_pool(self):
        """move_start_eligible : unité joueur 1 avec MOVE>0 présente dans le pool."""
        units = [_unit(1, 1, 10, 10), _unit(2, 2, 20, 10)]
        gs = _make_movement_state(units)
        result = movement_phase_start(gs)
        # Si l'unité est eligible, phase_initialized=True et pool non vide
        assert result.get("phase_initialized") is True
        assert "1" in gs["move_activation_pool"]

    def test_wrong_player_unit_not_in_pool(self):
        """move_start_wrong_player : unité joueur 2 non présente dans le pool joueur 1."""
        units = [_unit(2, 2, 10, 10)]  # seul joueur 2
        gs = _make_movement_state(units)
        movement_phase_start(gs)
        assert "2" not in gs["move_activation_pool"]


# ─────────────────────────────────────────────────────────────────────────────
# shooting_phase_start
# ─────────────────────────────────────────────────────────────────────────────

class TestShootingPhaseStart:
    def test_phase_set_to_shoot(self):
        """shoot_start_phase : shooting_phase_start set phase='shoot'."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_shooting_state(units)
        shooting_phase_start(gs)
        assert gs["phase"] == "shoot"

    def test_weapon_rule_initialized(self):
        """shoot_start_weapon_rule : weapon_rule initialisé à 1."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_shooting_state(units)
        shooting_phase_start(gs)
        assert gs["weapon_rule"] == 1

    def test_units_cache_present(self):
        """shoot_start_cache : units_cache présent après shooting_phase_start."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_shooting_state(units)
        shooting_phase_start(gs)
        assert "units_cache" in gs

    def test_enemy_adjacent_hexes_built(self):
        """shoot_start_adj : enemy_adjacent_hexes_player_1 construit à l'initialisation."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_shooting_state(units)
        shooting_phase_start(gs)
        assert "enemy_adjacent_hexes_player_1" in gs

    def test_shoot_activation_pool_initialized(self):
        """shoot_start_pool : shoot_activation_pool initialisé (peut être vide)."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_shooting_state(units)
        shooting_phase_start(gs)
        assert "shoot_activation_pool" in gs

    def test_no_rng_weapons_can_advance(self):
        """shoot_start_advance : unité sans RNG_WEAPONS toujours éligible (can_advance=True)."""
        # Unité joueur 1 sans armes → peut avancer → dans le pool
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_shooting_state(units)
        shooting_phase_start(gs)
        # L'unité joueur 1 est non-adjacente et peut avancer → dans le pool
        assert "1" in gs["shoot_activation_pool"]


# ─────────────────────────────────────────────────────────────────────────────
# fight_phase_start
# ─────────────────────────────────────────────────────────────────────────────

class TestFightPhaseStart:
    def test_phase_set_to_fight(self):
        """fight_start_phase : fight_phase_start set phase='fight'."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_fight_state(units)
        fight_phase_start(gs)
        assert gs["phase"] == "fight"

    def test_pools_initialized_when_no_adjacent_units(self):
        """fight_start_pools_empty : sans unités adjacentes → pools vides."""
        # Unités loin l'une de l'autre (hors engagement zone=1)
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_fight_state(units)
        fight_phase_start(gs)
        assert "charging_activation_pool" in gs
        assert "active_alternating_activation_pool" in gs
        assert "non_active_alternating_activation_pool" in gs

    def test_charging_pool_built(self):
        """fight_start_charging : pool de chargeurs initialisé (vide si aucun chargeur)."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_fight_state(units)
        fight_phase_start(gs)
        assert isinstance(gs["charging_activation_pool"], list)

    def test_fight_subphase_set_when_adjacent(self):
        """fight_start_subphase : fight_subphase défini après initialisation."""
        # Unités adjacentes (col 5 et 6, même row) → EN engagement zone
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_fight_state(units)
        fight_phase_start(gs)
        # fight_subphase doit être défini (non-None car des unités sont éligibles)
        assert gs.get("fight_subphase") is not None

    def test_adjacent_enemy_in_alternating_pool(self):
        """fight_start_adj_pool : unité joueur 1 adjacente à ennemi → dans un pool fight."""
        # col=5 et col=6 → hexes adjacents → engagement zone 1
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_fight_state(units)
        fight_phase_start(gs)
        all_pool_units = (
            gs["charging_activation_pool"]
            + gs["active_alternating_activation_pool"]
            + gs["non_active_alternating_activation_pool"]
        )
        assert "1" in all_pool_units or "2" in all_pool_units

    def test_units_cache_present(self):
        """fight_start_cache : units_cache présent après fight_phase_start."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 20, 10)]
        gs = _make_fight_state(units)
        fight_phase_start(gs)
        assert "units_cache" in gs
