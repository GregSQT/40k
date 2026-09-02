"""Sandbox free-move : invariants état post-commit."""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers import movement_handlers as mh
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache, _squad_is_in_enemy_er
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

    def test_sandbox_does_not_inflate_unit_activation_count(self):
        """VERROU : N commits sandbox ne doivent pas incrémenter unit_activation_count.

        end_activation incrémente ; le bloc sandbox décrémente immédiatement — bilan net 0.
        Valeur attendue : 0 après chaque commit sandbox (pas d'enregistrement d'activation).
        """
        units = [_unit("1", 1, 5, 10)]
        gs = _make_gs(units, sandbox=True)

        plan1 = [["1#0", 10, 10, 0, 0]]
        ok1, _ = mh.movement_commit_move_plan_handler(gs, "1", {"plan": plan1})
        assert ok1 is True
        assert gs.get("unit_activation_count", 0) == 0, (
            "premier commit sandbox : compteur doit rester à 0"
        )

        plan2 = [["1#0", 15, 10, 0, 0]]
        ok2, _ = mh.movement_commit_move_plan_handler(gs, "1", {"plan": plan2})
        assert ok2 is True
        assert gs.get("unit_activation_count", 0) == 0, (
            "deuxième commit sandbox : compteur doit rester à 0"
        )

    def test_normal_finalize_flee_marking_stays(self):
        """Contrôle : finalize_flee_marking marque units_fled hors sandbox, sans sandbox bypass."""
        from engine.phase_handlers.movement_handlers import finalize_flee_marking
        gs: dict = {"units_fled": set(), "sandbox_free_move": False}
        finalize_flee_marking(gs, "1", was_engaged=True)
        assert "1" in gs["units_fled"], (
            "hors sandbox, finalize_flee_marking doit ajouter l'unité à units_fled"
        )

    def test_sandbox_advance_cleared_after_commit(self):
        """VERROU : unité ayant avancé → units_advanced et advance_rolls purgés après re-pool sandbox.

        Sans le purge, _advance_roll_for renvoie le jet figé à la re-activation suivante
        et le pool de destinations applique M+D6 au lieu de M.
        """
        units = [_unit("1", 1, 5, 10)]
        gs = _make_gs(units, sandbox=True)
        # Marquer manuellement l'advance (équivalent à movement_set_advance_mode_handler)
        gs.setdefault("units_advanced", set()).add("1")
        gs.setdefault("advance_rolls", {})["1"] = 4

        plan = [["1#0", 8, 10, 0, 0]]
        ok, res = mh.movement_commit_move_plan_handler(gs, "1", {"plan": plan})

        assert ok is True, f"commit échoué en sandbox : {res}"
        assert "1" not in gs.get("units_advanced", set()), (
            "units_advanced doit être purgé après sandbox move d'une unité advance"
        )
        assert "1" not in gs.get("advance_rolls", {}), (
            "advance_rolls doit être purgé après sandbox move d'une unité advance"
        )
        assert "1" in gs["move_activation_pool"], (
            "l'unité doit être re-poolée après sandbox move"
        )

    def test_sandbox_advance_mode_allowed_on_engaged_unit(self):
        """VERROU : sandbox_free_move bypass le garde engagement de movement_set_advance_mode_handler.

        Sans le bypass, un opérateur sandbox ne peut pas tester le marquage advance
        sur une unité engagée, alors que le pool de destinations et la liste éligible
        ne vérifient pas l'engagement en sandbox.
        """
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 6, 10)]
        gs = _make_gs(units, sandbox=True)

        assert _squad_is_in_enemy_er(gs, "1"), (
            "prémisse : unit 1 doit être engagée"
        )

        ok, result = mh.movement_set_advance_mode_handler(gs, "1", {})

        assert ok is True, (
            f"sandbox doit autoriser le mode advance sur une unité engagée, refusé : {result}"
        )
        assert "1" in gs["units_advanced"], (
            "units_advanced doit contenir l'unité après set_advance_mode en sandbox"
        )

    def test_sandbox_advance_engaged_flags_cleared_after_commit(self):
        """VERROU : unité engagée advance-mode (sandbox) → flags purgés après commit.

        set_advance_mode_handler écrit units_advanced + advance_rolls ; le bloc sandbox
        du commit doit les effacer inconditionnellement, même si l'unité était engagée.
        Sans ce purge, la re-activation suivante hérite du jet advance et restreint
        tir/charge alors que l'unité s'est juste re-poolée.
        """
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 6, 10)]
        gs = _make_gs(units, sandbox=True)

        assert _squad_is_in_enemy_er(gs, "1"), (
            "prémisse : unit 1 doit être engagée"
        )

        ok_adv, _ = mh.movement_set_advance_mode_handler(gs, "1", {})
        assert ok_adv is True
        assert "1" in gs["units_advanced"], "prémisse : flag advance posé"
        assert "1" in gs["advance_rolls"], "prémisse : roll advance enregistré"

        plan = [["1#0", 20, 10, 0, 0]]
        ok, _ = mh.movement_commit_move_plan_handler(gs, "1", {"plan": plan})

        assert ok is True
        assert "1" not in gs.get("units_advanced", set()), (
            "units_advanced doit être purgé après commit sandbox (unité engagée)"
        )
        assert "1" not in gs.get("advance_rolls", {}), (
            "advance_rolls doit être purgé après commit sandbox (unité engagée)"
        )

    def test_sandbox_flee_result_action_is_move(self):
        """VERROU : result['action'] est 'move' (pas 'flee') après re-pool sandbox sur fuite.

        Sans l'override, le front reçoit action='flee' alors que units_fled est vide
        — discordance moteur/front qui peut bloquer les actions tir/mêlée au tour suivant.
        """
        units = [_unit("1", 1, 5, 10), _unit("2", 2, 6, 10)]
        gs = _make_gs(units, sandbox=True)

        assert _squad_is_in_enemy_er(gs, "1"), (
            "prémisse : unit 1 doit être engagée pour déclencher le flee"
        )

        plan = [["1#0", 20, 10, 0, 0]]
        ok, res = mh.movement_commit_move_plan_handler(gs, "1", {"plan": plan})

        assert ok is True, f"commit échoué en sandbox : {res}"
        assert res["action"] == "move", (
            f"result['action'] doit être 'move' en sandbox après fuite re-poolée, obtenu '{res['action']}'"
        )


class TestSandboxFreeMoveDestinations:
    """VERROU : sandbox_free_move génère toutes les cellules sol + cellules terrain aux niveaux réels."""

    def _terrain_with_floor(self) -> list:
        """Terrain avec un étage niveau 1 en (2,2) et (3,2)."""
        return [
            {
                "floors": [
                    {
                        "level": 1,
                        "height_inches": 4.0,
                        "hexes": [[2, 2], [3, 2]],
                    }
                ]
            }
        ]

    def _gs_for_pool(self, terrain_areas: list) -> dict:
        gs = _make_gs([_unit("1", 1, 0, 0)], sandbox=True)
        gs["board_cols"] = 5
        gs["board_rows"] = 5
        gs["terrain_areas"] = terrain_areas
        return gs

    def _level1_set(self) -> set:
        gs = self._gs_for_pool(self._terrain_with_floor())
        model_id = next(iter(gs["models_cache"]))
        result = mh.movement_build_model_destinations_pool(gs, model_id)
        return {(d[0], d[1]) for d in result["destinations"] if d[2] == 1}

    def test_all_ground_cells_present(self):
        """Toutes les 25 cellules au niveau 0 doivent être dans le pool."""
        gs = self._gs_for_pool(self._terrain_with_floor())
        model_id = next(iter(gs["models_cache"]))
        result = mh.movement_build_model_destinations_pool(gs, model_id)
        level0 = {(d[0], d[1]) for d in result["destinations"] if d[2] == 0}
        assert len(level0) == 25, f"attendu 25 cellules sol, obtenu {len(level0)}"

    def test_floor_cells_present_at_level1(self):
        """Les cellules (2,2) et (3,2) au niveau 1 doivent être dans le pool."""
        level1 = self._level1_set()
        assert (2, 2) in level1, "cellule (2,2) level 1 absente du pool sandbox"
        assert (3, 2) in level1, "cellule (3,2) level 1 absente du pool sandbox"

    def test_non_floor_cell_absent_at_level1(self):
        """Une cellule sans plancher (0,0) ne doit pas apparaître au niveau 1."""
        assert (0, 0) not in self._level1_set(), "cellule (0,0) sans plancher ne doit pas apparaître au niveau 1"

    def test_no_floor_terrain_yields_only_level0(self):
        """Sans terrain à étage, le pool ne contient que le niveau 0."""
        gs = self._gs_for_pool([])
        model_id = next(iter(gs["models_cache"]))
        result = mh.movement_build_model_destinations_pool(gs, model_id)
        levels = {d[2] for d in result["destinations"]}
        assert levels == {0}, f"sans étage, seul le niveau 0 attendu, obtenu : {levels}"
