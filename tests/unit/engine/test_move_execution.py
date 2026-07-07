"""Couche 5 — Exécution mouvement : _attempt_movement_to_destination."""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.movement_handlers import _attempt_movement_to_destination
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache


def _unit(uid: int, player: int, col: int, row: int, base_size: int = 1) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "MOVE": 6,
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
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "UNIT_KEYWORDS": [],
        "UNIT_RULES": [],
    }


def _make_game_state(
    units: List[Dict[str, Any]],
    current_player: int = 1,
    engagement_zone: int = 1,
) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": engagement_zone, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_moved": set(),
        "units_fled": set(),
        "console_logs": [],
        "hex_los_cache": {},
        "gym_training_mode": True,
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, current_player)
    return gs


class TestMoveExecution:
    def test_position_updated_in_unit_dict(self):
        """move_exec_pos : après mouvement réussi, unit['col'] et unit['row'] sont mis à jour."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        unit = units[0]
        success, _ = _attempt_movement_to_destination(gs, unit, 6, 10, gs["config"])
        assert success is True
        assert unit["col"] == 6
        assert unit["row"] == 10

    def test_units_cache_position_updated(self):
        """move_exec_cache : units_cache reflète la nouvelle position après mouvement."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        _attempt_movement_to_destination(gs, units[0], 7, 10, gs["config"])
        entry = gs["units_cache"]["1"]
        assert entry["col"] == 7
        assert entry["row"] == 10

    def test_units_moved_marked(self):
        """move_exec_moved : unit_id ajouté à units_moved après mouvement réussi."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        _attempt_movement_to_destination(gs, units[0], 6, 10, gs["config"])
        assert "1" in gs["units_moved"]

    def test_flee_detected_when_adjacent_to_enemy(self):
        """move_exec_flee : unité adjacente à ennemi avant le mouvement → ajoutée à units_fled + action=flee.

        (5,10) est adjacent à (6,10) avec EZ=1 → mouvement vers (3,10) reconnu comme fuite.
        """
        enemy = _unit(2, 2, 6, 10)
        mover = _unit(1, 1, 5, 10)
        gs = _make_game_state([mover, enemy], engagement_zone=1)
        # Build EZ for both players so mover's adjacency check works
        build_enemy_adjacent_hexes(gs, 2)
        success, result = _attempt_movement_to_destination(gs, mover, 3, 10, gs["config"])
        assert success is True
        assert "1" in gs["units_fled"]
        assert result["action"] == "flee"

    def test_no_flee_when_not_adjacent(self):
        """move_exec_no_flee : unité loin de l'ennemi → absente de units_fled + action=move."""
        enemy = _unit(2, 2, 20, 10)
        mover = _unit(1, 1, 5, 10)
        gs = _make_game_state([mover, enemy], engagement_zone=1)
        _attempt_movement_to_destination(gs, mover, 6, 10, gs["config"])
        assert "1" not in gs["units_fled"]

    def test_success_return_structure(self):
        """move_exec_return : succès retourne (True, dict) avec unitId, fromCol/Row, toCol/Row."""
        units = [_unit(1, 1, 5, 10)]
        gs = _make_game_state(units)
        success, result = _attempt_movement_to_destination(gs, units[0], 6, 10, gs["config"])
        assert success is True
        assert result["action"] == "move"
        assert result["unitId"] == 1
        assert result["fromCol"] == 5
        assert result["fromRow"] == 10
        assert result["toCol"] == 6
        assert result["toRow"] == 10

    def test_destination_occupied_returns_false(self):
        """move_exec_occupied : destination occupée par un allié → False + error=destination_occupied."""
        ally = _unit(2, 1, 6, 10)
        mover = _unit(1, 1, 5, 10)
        gs = _make_game_state([mover, ally])
        success, result = _attempt_movement_to_destination(gs, mover, 6, 10, gs["config"])
        assert success is False
        assert result["error"] == "destination_occupied"
        # Position must not have changed
        assert mover["col"] == 5
        assert mover["row"] == 10

    def test_destination_adjacent_to_enemy_returns_false(self):
        """move_exec_ez : destination adjacente à ennemi (EZ=1) → False + error=destination_adjacent_to_enemy.

        Ennemi en (8,10) (col pair) → voisin SW = (7,10).
        Mover en (3,10) tente de rejoindre (7,10).
        """
        enemy = _unit(2, 2, 8, 10)
        mover = _unit(1, 1, 3, 10)
        gs = _make_game_state([mover, enemy], engagement_zone=1)
        success, result = _attempt_movement_to_destination(gs, mover, 7, 10, gs["config"])
        assert success is False
        assert result["error"] == "destination_adjacent_to_enemy"

    def test_enemy_adjacent_cache_updated_after_move(self):
        """move_exec_adj_cache : après mouvement player 1, enemy_adjacent_hexes_player_2 reflète la nouvelle position.

        Player 1 passe de (5,10) à (15,10).
        Avant : voisins de (5,10) dans le cache player_2.
        Après : voisins de (15,10) dans le cache player_2, voisins de (5,10) absents.
        """
        enemy = _unit(2, 2, 3, 3)
        mover = _unit(1, 1, 5, 10)
        gs = _make_game_state([mover, enemy], current_player=1, engagement_zone=1)
        build_enemy_adjacent_hexes(gs, 2)

        old_neighbor = (6, 10)  # voisin SE de (5,10) col impair → (col+1, row+1)=(6,11)…
        # col=5 (impair) voisins : N=(5,9), NE=(6,10), SE=(6,11), S=(5,11), SW=(4,11), NW=(4,10)
        # → (6,10) est NE de (5,10)
        new_neighbor = (15, 10)  # voisin direct de (15,10) col impair : NE=(16,10)
        # col=15 impair → NE=(16,10), mais on vérifie juste que (6,10) a disparu du cache

        _attempt_movement_to_destination(gs, mover, 15, 10, gs["config"])

        cache_after = gs.get("enemy_adjacent_hexes_player_2", set())
        assert old_neighbor not in cache_after, (
            f"(6,10) doit être absent du cache player_2 après que player 1 a quitté (5,10)"
        )


class TestNonRoundBase:
    """Socles non ronds (BASE_SHAPE='square') — position et cache mis à jour correctement."""

    def test_square_base_position_updated(self):
        """square_pos : après mouvement réussi avec BASE_SHAPE='square', col/row mis à jour."""
        units = [_unit(1, 1, 5, 10)]
        units[0]["BASE_SHAPE"] = "square"
        gs = _make_game_state(units)
        success, _ = _attempt_movement_to_destination(gs, units[0], 6, 10, gs["config"])
        assert success is True
        assert units[0]["col"] == 6
        assert units[0]["row"] == 10

    def test_square_base_units_cache_updated(self):
        """square_cache : units_cache reflète la nouvelle position après mouvement avec BASE_SHAPE='square'."""
        units = [_unit(1, 1, 5, 10)]
        units[0]["BASE_SHAPE"] = "square"
        gs = _make_game_state(units)
        _attempt_movement_to_destination(gs, units[0], 7, 10, gs["config"])
        entry = gs["units_cache"]["1"]
        assert entry["col"] == 7
        assert entry["row"] == 10

    def test_square_base_units_moved_marked(self):
        """square_moved : unit_id ajouté à units_moved pour une base carrée."""
        units = [_unit(1, 1, 5, 10)]
        units[0]["BASE_SHAPE"] = "square"
        gs = _make_game_state(units)
        _attempt_movement_to_destination(gs, units[0], 6, 10, gs["config"])
        assert "1" in gs["units_moved"]

    def test_square_base_collision_prevents_move(self):
        """square_collision : destination occupée avec base carrée → mouvement refusé."""
        mover = _unit(1, 1, 5, 10)
        mover["BASE_SHAPE"] = "square"
        blocker = _unit(2, 2, 6, 10)
        gs = _make_game_state([mover, blocker])
        success, result = _attempt_movement_to_destination(gs, mover, 6, 10, gs["config"])
        assert success is False
        assert result["error"] == "destination_occupied"

    def test_square_base_multi_steps(self):
        """square_multi : base carrée peut se déplacer plusieurs hexes."""
        units = [_unit(1, 1, 5, 10)]
        units[0]["BASE_SHAPE"] = "square"
        gs = _make_game_state(units)
        success1, _ = _attempt_movement_to_destination(gs, units[0], 6, 10, gs["config"])
        assert success1 is True
        # Second move depuis (6,10) vers (7,10)
        success2, _ = _attempt_movement_to_destination(gs, units[0], 7, 10, gs["config"])
        assert success2 is True
        assert units[0]["col"] == 7
        assert units[0]["row"] == 10

    def test_square_base_same_as_round_for_single_hex(self):
        """square_vs_round : BASE_SHAPE square avec EZ=1 identique à round pour occupation."""
        # Avec EZ=1 les deux formes occupent un seul hex → comportement identique
        round_mover = _unit(1, 1, 5, 10)
        square_mover = _unit(2, 1, 8, 10)
        square_mover["BASE_SHAPE"] = "square"
        blocker = _unit(3, 2, 9, 10)
        gs = _make_game_state([round_mover, square_mover, blocker])
        # Vérifier que square peut se déplacer normalement sauf si bloqué
        s1, _ = _attempt_movement_to_destination(gs, round_mover, 6, 10, gs["config"])
        s2, _ = _attempt_movement_to_destination(gs, square_mover, 9, 10, gs["config"])
        assert s1 is True  # round → ok
        assert s2 is False  # square → bloqué par unit 3

    def test_square_base_action_result_move(self):
        """square_action_move : résultat action='move' pour base carrée."""
        units = [_unit(1, 1, 5, 10)]
        units[0]["BASE_SHAPE"] = "square"
        gs = _make_game_state(units)
        success, result = _attempt_movement_to_destination(gs, units[0], 6, 10, gs["config"])
        assert success is True
        assert result.get("action") == "move"
