"""Couches 5, 6, 7 — Exécution combat, résolution dés, transitions de phase (fight)."""

from __future__ import annotations

from typing import Any, Dict, List, cast

import pytest

from engine.combat_utils import resolve_dice_value
from engine.phase_handlers.fight_handlers import _remove_dead_unit_from_fight_pools
from engine.phase_handlers.shared_utils import (
    build_units_cache,
    get_hp_from_cache,
    is_unit_alive,
    update_units_cache_hp,
)


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
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "shoot_activation_pool": [],
        "move_activation_pool": [],
        "charge_activation_pool": [],
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Couche 5 — HP management
# ─────────────────────────────────────────────────────────────────────────────

class TestHpManagement:
    def test_hp_decremented_partial_damage(self):
        """fight_hp_partial : dégâts inférieurs aux PV → HP_CUR décrémenté dans le cache."""
        units = [_unit(1, 1, 5, 10, hp=4)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "1", 2)
        assert get_hp_from_cache("1", gs) == 2

    def test_hp_zero_removes_unit_from_cache(self):
        """fight_hp_zero : PV tombent à 0 → unité retirée du cache, is_unit_alive=False."""
        units = [_unit(1, 1, 5, 10, hp=2)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "1", 0)
        assert is_unit_alive("1", gs) is False
        assert "1" not in gs["units_cache"]

    def test_hp_negative_also_removes_unit(self):
        """fight_hp_neg : HP négatif traité comme 0 → unité retirée du cache."""
        units = [_unit(1, 1, 5, 10, hp=2)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "1", -5)
        assert is_unit_alive("1", gs) is False

    def test_hp_update_on_absent_unit_is_noop(self):
        """fight_hp_absent : mise à jour HP sur unité absente du cache → pas d'erreur."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        del gs["units_cache"]["1"]
        update_units_cache_hp(gs, "1", 0)  # must not raise

    def test_surviving_unit_remains_alive(self):
        """fight_hp_survive : unité vivante avec PV restants → toujours présente dans le cache."""
        units = [_unit(1, 1, 5, 10, hp=5), _unit(2, 2, 6, 10, hp=3)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "2", 0)  # unit 2 dies
        assert is_unit_alive("1", gs) is True
        assert get_hp_from_cache("1", gs) == 5


# ─────────────────────────────────────────────────────────────────────────────
# Couche 7 — Cascade mort fight (retrait des pools)
# ─────────────────────────────────────────────────────────────────────────────

class TestFightDeathCascade:
    def test_dead_unit_removed_from_charging_pool(self):
        """fight_cascade_charging : unité morte retirée du charging_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units)
        gs["charging_activation_pool"] = ["1", "2", "3"]
        _remove_dead_unit_from_fight_pools(gs, "2")
        assert "2" not in gs["charging_activation_pool"]
        assert "1" in gs["charging_activation_pool"]

    def test_dead_unit_removed_from_active_alternating_pool(self):
        """fight_cascade_active : unité morte retirée de active_alternating_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units)
        gs["active_alternating_activation_pool"] = ["1", "2"]
        _remove_dead_unit_from_fight_pools(gs, "2")
        assert "2" not in gs["active_alternating_activation_pool"]
        assert "1" in gs["active_alternating_activation_pool"]

    def test_dead_unit_removed_from_non_active_alternating_pool(self):
        """fight_cascade_nonactive : unité morte retirée de non_active_alternating_activation_pool.

        L'unité doit d'abord être retirée du units_cache (HP→0), sinon le lazy rebuild
        la réinsère dans le pool depuis units_cache.
        """
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units)
        gs["non_active_alternating_activation_pool"] = ["2", "3"]
        update_units_cache_hp(gs, "2", 0)  # mort → retrait du units_cache
        _remove_dead_unit_from_fight_pools(gs, "2")
        assert "2" not in gs["non_active_alternating_activation_pool"]

    def test_dead_unit_removed_from_shoot_pool_via_fight_cascade(self):
        """fight_cascade_shoot : mort en fight → retirée aussi du shoot_activation_pool (cross-phase)."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]
        gs = _make_game_state(units)
        gs["shoot_activation_pool"] = ["1", "2"]
        _remove_dead_unit_from_fight_pools(gs, "2")
        assert "2" not in gs["shoot_activation_pool"]

    def test_absent_unit_cascade_is_noop(self):
        """fight_cascade_absent : unité absente des pools → pas d'erreur, pools inchangés."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        gs["charging_activation_pool"] = ["1"]
        _remove_dead_unit_from_fight_pools(gs, "99")
        assert gs["charging_activation_pool"] == ["1"]


# ─────────────────────────────────────────────────────────────────────────────
# Couche 6 — Résolution dés (resolve_dice_value)
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveDiceValue:
    def test_integer_passthrough(self):
        """dice_int : valeur entière retournée telle quelle."""
        assert resolve_dice_value(3, "test") == 3
        assert resolve_dice_value(0, "test") == 0
        assert resolve_dice_value(10, "test") == 10

    def test_d6_in_range(self):
        """dice_d6 : 'D6' produit un résultat dans [1, 6]."""
        result = resolve_dice_value("D6", "fight_test")
        assert 1 <= result <= 6

    def test_d3_in_range(self):
        """dice_d3 : 'D3' produit un résultat dans [1, 3]."""
        result = resolve_dice_value("D3", "fight_test")
        assert 1 <= result <= 3

    def test_d6_plus_1_in_range(self):
        """dice_d6p1 : 'D6+1' produit un résultat dans [2, 7]."""
        result = resolve_dice_value("D6+1", "fight_test")
        assert 2 <= result <= 7

    def test_d6_plus_2_in_range(self):
        """dice_d6p2 : 'D6+2' produit un résultat dans [3, 8]."""
        result = resolve_dice_value("D6+2", "fight_test")
        assert 3 <= result <= 8

    def test_d6_plus_3_in_range(self):
        """dice_d6p3 : 'D6+3' produit un résultat dans [4, 9]."""
        result = resolve_dice_value("D6+3", "fight_test")
        assert 4 <= result <= 9

    def test_2d6_in_range(self):
        """dice_2d6 : '2D6' produit un résultat dans [2, 12]."""
        result = resolve_dice_value("2D6", "fight_test")
        assert 2 <= result <= 12

    def test_invalid_float_raises_type_error(self):
        """dice_float : type float → TypeError."""
        with pytest.raises(TypeError):
            resolve_dice_value(cast(int, 3.5), "fight_test")

    def test_invalid_string_raises_value_error(self):
        """dice_invalid_str : expression non supportée → ValueError."""
        with pytest.raises(ValueError):
            resolve_dice_value("D4", "fight_test")

    def test_invalid_string_d6_minus_raises(self):
        """dice_d6_minus : 'D6-1' non supporté → ValueError."""
        with pytest.raises(ValueError):
            resolve_dice_value("D6-1", "fight_test")
