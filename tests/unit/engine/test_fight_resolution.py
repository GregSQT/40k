"""Résolution fight — _fight_build_valid_target_pool : états réels, pas de mocks."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.fight_handlers import _fight_build_valid_target_pool
from engine.phase_handlers.shared_utils import build_units_cache


def _unit(uid: int, player: int, col: int, row: int, base_size: int = 3) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": 2,
        "HP_MAX": 2,
        "VALUE": 50,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "BASE_SIZE": base_size,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
    }


def _make_game_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 10, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 80,
        "board_rows": 60,
        "current_player": 1,
        "phase": "fight",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(),
        "units_fought": set(),
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "console_logs": [],
    }
    build_units_cache(gs)
    return gs


class TestFightTargetPoolResolution:
    def test_attacker_in_ez_enemy_included(self):
        """fight_in_ez : attaquant en EZ d'un ennemi (hexes contigus, BASE_SIZE=3) → cible incluse.

        euclidean_edge_clearance(5,10, 6,10, r=2.25, r=2.25) < engagement_zone=10.
        """
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units)
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" in targets, "adjacent enemy must be in fight target pool"

    def test_attacker_out_of_ez_pool_empty(self):
        """fight_out_ez : attaquant loin de l'ennemi (BASE_SIZE=3) → pool vide.

        euclidean_edge_clearance(5,10, 35,10, r=2.25, r=2.25) = 45 - 4.5 = 40.5 > 10.
        """
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 35, 10)]
        gs = _make_game_state(units)
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" not in targets, "far enemy must not be in fight target pool"
        assert targets == [], "pool must be empty when no enemy in EZ"

    def test_dead_target_excluded(self):
        """fight_dead_target : cible retirée du cache (morte) exclue du pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units)
        del gs["units_cache"]["2"]
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" not in targets

    def test_ally_excluded(self):
        """fight_ally : allié adjacent (même joueur) exclu du pool de cibles."""
        units = [_unit(1, 1, 5, 10), _unit(2, 1, 6, 10)]  # player=1 pour les deux
        gs = _make_game_state(units)
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" not in targets, "ally must never be a fight target"

    def test_two_enemies_only_one_in_ez(self):
        """fight_two_enemies_one_ez : deux ennemis — seul celui en EZ est dans le pool.

        enemy2 en (6,10) → adjacent, en EZ → inclus.
        enemy3 en (35,10) → loin, hors EZ → exclu.
        """
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10), _unit(3, 2, 35, 10)]
        gs = _make_game_state(units)
        targets = _fight_build_valid_target_pool(gs, units[0])
        assert "2" in targets, "adjacent enemy must be in pool"
        assert "3" not in targets, "far enemy must not be in pool"
        assert len(targets) == 1, "only the adjacent enemy must be in pool"
