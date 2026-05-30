"""Résolution tir — _has_valid_shooting_targets : états réels, pas de mocks."""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.shooting_handlers import _has_valid_shooting_targets
from engine.phase_handlers.shared_utils import build_units_cache


def _weapon(pistol: bool = False, rng: int = 24) -> Dict[str, Any]:
    return {
        "RNG": rng,
        "SHOTS": "1",
        "STRENGTH": 4,
        "AP": 0,
        "DAMAGE": 1,
        "shot": 0,
        "WEAPON_RULES": ["PISTOL"] if pistol else [],
    }


def _unit(uid: int, player: int, col: int, row: int, pistol: bool = False, base_size: int = 3) -> Dict[str, Any]:
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
        "BASE_SIZE": base_size,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "RNG_WEAPONS": [_weapon(pistol=pistol)],
        "CC_WEAPONS": [],
        "_shooting_with_pistol": None,
    }


def _make_game_state(units: List[Dict[str, Any]], units_fled=None) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 10, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 80,
        "board_rows": 60,
        "current_player": 1,
        "phase": "shoot",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_fled": units_fled if units_fled is not None else set(),
        "units_shot": set(),
        "shoot_activation_pool": [],
        "console_logs": [],
        "debug_logs": [],
        "hex_los_cache": {},
        "weapon_rule": {},
    }
    build_units_cache(gs)
    return gs


class TestHasValidShootingTargets:
    def test_not_adjacent_eligible(self):
        """shoot_not_adjacent : unité non adjacente → toujours éligible (peut avancer).

        euclidean_edge_clearance(5,10, 30,10, r=2.25, r=2.25) = 40.5 > engagement_zone=10.
        Branche non-adjacent : can_advance=True → retourne True.
        """
        shooter = _unit(1, 1, 5, 10)
        enemy = _unit(2, 2, 30, 10)
        gs = _make_game_state([shooter, enemy])
        assert _has_valid_shooting_targets(gs, shooter, 1) is True

    def test_adjacent_no_pistol_excluded(self):
        """shoot_adjacent_no_pistol : unité en EZ (grands socles) sans arme PISTOL → exclue.

        euclidean_edge_clearance(5,10, 30,10, r=18.75, r=18.75) = 7.5 ≤ engagement_zone=10.
        → adjacente → weapon_availability_check : aucune arme PISTOL → can_shoot=False → False.
        """
        shooter = {**_unit(1, 1, 5, 10, pistol=False, base_size=25)}
        enemy = {**_unit(2, 2, 30, 10, base_size=25)}
        gs = _make_game_state([shooter, enemy])
        assert _has_valid_shooting_targets(gs, shooter, 1) is False

    def test_adjacent_pistol_eligible(self):
        """shoot_adjacent_pistol : unité en EZ avec arme PISTOL et LOS en cache → éligible.

        Même setup que test_adjacent_no_pistol_excluded, mais arme PISTOL.
        los_cache pré-rempli pour éviter le calcul LOS (qui nécessite les_visibility_min_ratio).
        """
        shooter = {**_unit(1, 1, 5, 10, pistol=True, base_size=25)}
        enemy = {**_unit(2, 2, 30, 10, base_size=25)}
        # Pré-remplir le cache LOS : le shooter voit l'ennemi
        shooter["los_cache"] = {"2": True}
        gs = _make_game_state([shooter, enemy])
        assert _has_valid_shooting_targets(gs, shooter, 1) is True

    def test_fled_unit_excluded(self):
        """shoot_fled : unité en fuite sans règle shoot_after_flee → exclue avant tout autre check."""
        shooter = _unit(1, 1, 5, 10)
        enemy = _unit(2, 2, 30, 10)
        gs = _make_game_state([shooter, enemy], units_fled={"1"})
        assert _has_valid_shooting_targets(gs, shooter, 1) is False
