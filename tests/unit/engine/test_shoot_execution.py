"""Couches 5, 7 — Exécution tir, transitions de phase (shoot)."""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.shooting_handlers import _remove_dead_unit_from_pools
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
        "HP_MAX": hp,
        "VALUE": 100,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "_shooting_with_pistol": None,
    }


def _make_game_state(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
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
        "shoot_activation_pool": [],
        "move_activation_pool": [],
        "charge_activation_pool": [],
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Couche 5 — HP management (shoot context)
# ─────────────────────────────────────────────────────────────────────────────

class TestShootHpManagement:
    def test_hp_partial_damage(self):
        """shoot_hp_partial : tir inflige dégâts partiels → HP_CUR mis à jour."""
        units = [_unit(1, 1, 5, 10, hp=4), _unit(2, 2, 15, 10, hp=3)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "2", 1)
        assert get_hp_from_cache("2", gs) == 1

    def test_hp_lethal_removes_from_cache(self):
        """shoot_hp_lethal : dégâts létaux → cible retirée du cache, is_unit_alive=False."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10, hp=2)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "2", 0)
        assert is_unit_alive("2", gs) is False
        assert "2" not in gs["units_cache"]

    def test_shooter_survives_intact(self):
        """shoot_hp_shooter_intact : HP du tireur non modifié après tir standard."""
        units = [_unit(1, 1, 5, 10, hp=5), _unit(2, 2, 15, 10, hp=3)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "2", 0)
        assert is_unit_alive("1", gs) is True
        assert get_hp_from_cache("1", gs) == 5

    def test_hp_update_nonexistent_unit_noop(self):
        """shoot_hp_absent : mise à jour HP sur unité inconnue → pas d'erreur."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "99", 0)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# Couche 7 — Cascade mort shoot (retrait des pools)
# ─────────────────────────────────────────────────────────────────────────────

class TestShootDeathCascade:
    def test_dead_unit_removed_from_shoot_pool(self):
        """shoot_cascade_shoot : unité morte retirée du shoot_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _make_game_state(units)
        gs["shoot_activation_pool"] = ["1", "2", "3"]
        _remove_dead_unit_from_pools(gs, "2")
        assert "2" not in gs["shoot_activation_pool"]
        assert "1" in gs["shoot_activation_pool"]

    def test_dead_unit_removed_from_move_pool(self):
        """shoot_cascade_move : mort en phase tir → retirée aussi du move_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _make_game_state(units)
        gs["move_activation_pool"] = ["1", "2"]
        _remove_dead_unit_from_pools(gs, "2")
        assert "2" not in gs["move_activation_pool"]
        assert "1" in gs["move_activation_pool"]

    def test_dead_unit_removed_from_charge_pool(self):
        """shoot_cascade_charge : mort en phase tir → retirée aussi du charge_activation_pool."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _make_game_state(units)
        gs["charge_activation_pool"] = ["2", "3"]
        _remove_dead_unit_from_pools(gs, "2")
        assert "2" not in gs["charge_activation_pool"]

    def test_active_shooting_unit_cleared_on_death(self):
        """shoot_cascade_active : si l'unité active au tir est tuée → active_shooting_unit supprimé."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _make_game_state(units)
        gs["active_shooting_unit"] = "2"
        _remove_dead_unit_from_pools(gs, "2")
        assert "active_shooting_unit" not in gs

    def test_different_unit_active_shooting_unaffected(self):
        """shoot_cascade_active_other : unité active différente → active_shooting_unit conservé."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _make_game_state(units)
        gs["active_shooting_unit"] = "1"
        _remove_dead_unit_from_pools(gs, "2")
        assert gs.get("active_shooting_unit") == "1"

    def test_absent_unit_cascade_noop(self):
        """shoot_cascade_absent : unité absente des pools → pas d'erreur, pools inchangés."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        gs["shoot_activation_pool"] = ["1"]
        _remove_dead_unit_from_pools(gs, "99")
        assert gs["shoot_activation_pool"] == ["1"]

    def test_multiple_occurrences_removed_from_pool(self):
        """shoot_cascade_multi : unité présente plusieurs fois dans pool → toutes retiées."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 15, 10)]
        gs = _make_game_state(units)
        gs["shoot_activation_pool"] = ["2", "1", "2"]
        _remove_dead_unit_from_pools(gs, "2")
        assert "2" not in gs["shoot_activation_pool"]


# ─────────────────────────────────────────────────────────────────────────────
# HP edge cases supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestShootHpEdgeCases:
    def test_hp_set_to_exact_one(self):
        """shoot_hp_one : HP mis à 1 → unité vivante."""
        units = [_unit(1, 1, 5, 10, hp=5)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "1", 1)
        assert is_unit_alive("1", gs) is True
        assert get_hp_from_cache("1", gs) == 1

    def test_hp_cache_reflects_unit_dict(self):
        """shoot_hp_sync : HP mis à jour dans le cache reflète la valeur passée."""
        units = [_unit(1, 1, 5, 10, hp=10)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "1", 7)
        assert get_hp_from_cache("1", gs) == 7

    def test_is_alive_returns_true_for_existing_unit(self):
        """shoot_alive_existing : unité présente dans le cache → is_unit_alive True."""
        units = [_unit(1, 1, 5, 10, hp=3)]
        gs = _make_game_state(units)
        assert is_unit_alive("1", gs) is True

    def test_is_alive_returns_false_for_unknown_unit(self):
        """shoot_alive_unknown : unité absente du cache → is_unit_alive False."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        assert is_unit_alive("99", gs) is False

    def test_both_units_alive_independent(self):
        """shoot_hp_both_alive : dégâts sur unité 2 n'affectent pas unité 1."""
        units = [_unit(1, 1, 5, 10, hp=4), _unit(2, 2, 15, 10, hp=3)]
        gs = _make_game_state(units)
        update_units_cache_hp(gs, "2", 0)
        assert is_unit_alive("1", gs) is True
        assert is_unit_alive("2", gs) is False
