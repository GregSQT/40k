"""Tests for shared spatial relation primitives."""

from engine.spatial_relations import (
    move_anchor_violates_engagement_clearance,
    unit_entries_within_engagement_zone,
)


def test_move_clearance_legacy_uses_enemy_adjacent_hexes_membership() -> None:
    mover = {"id": "u1", "player": 1}
    game_state = {
        "enemy_adjacent_hexes_player_1": {(2, 2)},
    }

    assert move_anchor_violates_engagement_clearance(
        game_state,
        mover,
        2,
        2,
        {(2, 2)},
        units_cache={},
        enemy_adjacent_hexes=None,
        enemy_cache_items=[],
        engagement_zone_ez=1,
    ) is True

    assert move_anchor_violates_engagement_clearance(
        game_state,
        mover,
        3,
        3,
        {(3, 3)},
        units_cache={},
        enemy_adjacent_hexes={(2, 2)},
        enemy_cache_items=[],
        engagement_zone_ez=1,
    ) is False


def test_move_clearance_round_round_uses_euclidean_gap() -> None:
    mover = {"id": "u1", "player": 1, "BASE_SHAPE": "round", "BASE_SIZE": 2}
    enemy_entry = {
        "col": 10,
        "row": 10,
        "player": 2,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 2,
        "occupied_hexes": {(10, 10)},
    }

    assert move_anchor_violates_engagement_clearance(
        {},
        mover,
        10,
        10,
        {(10, 10)},
        units_cache={"enemy": enemy_entry},
        enemy_adjacent_hexes=None,
        enemy_cache_items=[("enemy", enemy_entry)],
        engagement_zone_ez=10,
    ) is True


def test_move_clearance_round_round_rejects_exact_engagement_boundary(monkeypatch) -> None:
    mover = {"id": "u1", "player": 1, "BASE_SHAPE": "round", "BASE_SIZE": 2}
    enemy_entry = {
        "col": 10,
        "row": 10,
        "player": 2,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 2,
        "occupied_hexes": {(10, 10)},
    }

    monkeypatch.setattr(
        "engine.spatial_relations.euclidean_edge_clearance_round_round",
        lambda *args, **kwargs: 15.0,
    )

    assert move_anchor_violates_engagement_clearance(
        {},
        mover,
        20,
        10,
        {(20, 10)},
        units_cache={"enemy": enemy_entry},
        enemy_adjacent_hexes=None,
        enemy_cache_items=[("enemy", enemy_entry)],
        engagement_zone_ez=10,
    ) is True


def test_round_round_engagement_uses_hex_footprint_not_euclidean_clearance(monkeypatch) -> None:
    first_entry = {
        "col": 20,
        "row": 10,
        "player": 1,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 2,
        "orientation": 0,
        "occupied_hexes": {(20, 10)},
    }
    second_entry = {
        "col": 10,
        "row": 10,
        "player": 2,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 2,
        "orientation": 0,
        "occupied_hexes": {(10, 10)},
    }

    # Métrique unifiée = distance d'empreinte hex (jamais euclidien) : le clearance
    # euclidien, même monkeypatché à une valeur hors zone, doit être ignoré.
    monkeypatch.setattr(
        "engine.spatial_relations.euclidean_edge_clearance_round_round",
        lambda *args, **kwargs: 15.000002,
    )

    # Empreintes distantes de 10 hex exactement.
    assert unit_entries_within_engagement_zone(
        first_entry, second_entry, engagement_zone=10
    ) is True
    assert unit_entries_within_engagement_zone(
        first_entry, second_entry, engagement_zone=9
    ) is False


def test_move_clearance_non_round_uses_hex_footprint_distance() -> None:
    mover = {"id": "u1", "player": 1, "BASE_SHAPE": "oval", "BASE_SIZE": 2}
    enemy_entry = {
        "col": 0,
        "row": 2,
        "player": 2,
        "BASE_SHAPE": "oval",
        "BASE_SIZE": 2,
        "occupied_hexes": {(0, 2)},
    }

    assert move_anchor_violates_engagement_clearance(
        {},
        mover,
        0,
        0,
        {(0, 0)},
        units_cache={"enemy": enemy_entry},
        enemy_adjacent_hexes=None,
        enemy_cache_items=[("enemy", enemy_entry)],
        engagement_zone_ez=2,
    ) is True
