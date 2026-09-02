"""Sandbox free-move : invariants état post-commit."""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers import movement_handlers as mh
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants


def _cfg() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 10,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2,
            "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1,
            "cohesion_distance_mode": "euclidean",
        },
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _unit(uid: str, player: int, col: int, row: int) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": 1, "HP_MAX": 1, "VALUE": 50, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "MOVE": 6, "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round",
        "UNIT_RULES": [],
        "models": [{"col": col, "row": row, "VALUE": 50, "orientation": 0}],
    }


def _make_gs(units: List[Dict[str, Any]], sandbox: bool = False) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": _cfg(),
        "board_cols": 30,
        "board_rows": 25,
        "current_player": 1,
        "phase": "move",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "move_activation_pool": ["1"],
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
        "sandbox_free_move": sandbox,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    return gs


class TestSandboxFreeMove:
    def test_sandbox_engaged_unit_not_marked_fled_after_commit(self):
        """VERROU : unité engagée déplacée en sandbox → units_fled vidé après re-pool.

        Sans le discard(squad_id_str) sur units_fled, l'unité resterait marquée
        FLED pour le reste du tour et ne pourrait pas combattre.
        """
        # Unit "1" (player 1) at (5,10), unit "2" (enemy) at (6,10) — adjacent
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 6, 10)]
        gs = _make_gs(units, sandbox=True)

        # Prémisse : les deux unités doivent être engagées (ER = 10 > distance bord-à-bord ~2)
        from engine.phase_handlers.shared_utils import _squad_is_in_enemy_er
        assert _squad_is_in_enemy_er(gs, "1"), (
            "prémisse : unit 1 doit être engagée pour que le test soit valide"
        )

        # Déplacement sandbox vers (20,10) — loin de l'ennemi
        plan = [["1#0", 20, 10, 0, 0]]
        ok, res = mh.movement_commit_move_plan_handler(gs, "1", {"plan": plan})

        assert ok is True, f"commit échoué en sandbox : {res}"
        assert "1" not in gs["units_fled"], (
            "units_fled doit être vide après sandbox move d'une unité engagée"
        )
        assert "1" in gs["move_activation_pool"], (
            "l'unité doit être re-poolée après sandbox move"
        )

    def test_normal_finalize_flee_marking_stays(self):
        """Contrôle : finalize_flee_marking marque units_fled hors sandbox, sans sandbox bypass."""
        from engine.phase_handlers.movement_handlers import finalize_flee_marking
        gs: dict = {"units_fled": set(), "sandbox_free_move": False}
        finalize_flee_marking(gs, "1", was_engaged=True)
        assert "1" in gs["units_fled"], (
            "hors sandbox, finalize_flee_marking doit ajouter l'unité à units_fled"
        )
