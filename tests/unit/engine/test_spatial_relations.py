"""Tests for shared spatial relation primitives."""

from engine.spatial_relations import (
    move_anchor_violates_engagement_clearance,
    unit_entries_within_engagement_zone,
)


def test_move_clearance_hex_geometry_uses_enemy_adjacent_hexes_membership() -> None:
    """Géométrie HEX (`inches_to_subhex <= 1`) → appartenance à l'ensemble pré-dilaté.

    C'est la MÊME source que l'exécution (`build_move_blocked_cells_by_level` →
    `validate_move_plan` / érosion du pool), d'où l'invariant « masque ⊆ exécutable » par
    construction. La branche était choisie par `engagement_zone_ez <= 1`, un proxy de « board x1 »
    devenu faux quand `engagement_zone` est passé de 1" à 2" ; elle l'est désormais par la
    résolution (`spatial_relations.geometry_is_hex`), dont le seul critère est `inches_to_subhex`.
    """
    mover = {"id": "u1", "player": 1}
    game_state = {
        "inches_to_subhex": 1,
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
        engagement_zone_ez=2,
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
        engagement_zone_ez=2,
    ) is False


def test_move_clearance_round_round_uses_euclidean_gap() -> None:
    mover = {"id": "u1", "player": 1, "BASE_SHAPE": "round", "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5}
    enemy_entry = {
        "col": 10,
        "row": 10,
        "player": 2,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 2,
        "MODEL_HEIGHT": 2.5,
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
    mover = {"id": "u1", "player": 1, "BASE_SHAPE": "round", "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5}
    enemy_entry = {
        "col": 10,
        "row": 10,
        "player": 2,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 2,
        "MODEL_HEIGHT": 2.5,
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
        "MODEL_HEIGHT": 2.5,
        "orientation": 0,
        "occupied_hexes": {(20, 10)},
    }
    second_entry = {
        "col": 10,
        "row": 10,
        "player": 2,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 2,
        "MODEL_HEIGHT": 2.5,
        "orientation": 0,
        "occupied_hexes": {(10, 10)},
    }

    # Chemin HEX explicite (metric="hex", encore vivant : observations §10, legacy ez<=1) : la
    # distance d'empreinte hex est utilisée, le clearance euclidien — même monkeypatché à une valeur
    # hors zone — doit être ignoré. (En prod, engagement="euclidean" depuis 7.6 ; couverture euclidienne
    # dans test_move_clearance_round_round_uses_euclidean_gap.)
    monkeypatch.setattr(
        "engine.spatial_relations.euclidean_edge_clearance_round_round",
        lambda *args, **kwargs: 15.000002,
    )

    # Empreintes distantes de 10 hex exactement.
    assert unit_entries_within_engagement_zone(
        first_entry, second_entry, engagement_zone=10, metric="hex"
    ) is True
    assert unit_entries_within_engagement_zone(
        first_entry, second_entry, engagement_zone=9, metric="hex"
    ) is False


def test_move_clearance_hex_metric_ignores_socle_shape(monkeypatch) -> None:
    """Métrique hex épinglée par CONFIG (pas par la résolution) : même routage que le x1.

    En hex, l'EZ est l'ensemble dilaté — la forme du socle n'entre plus dans la décision, puisque
    la dilatation a déjà été faite depuis les empreintes ennemies (`build_enemy_adjacent_hexes`).
    C'est ce qui garantit que le pool et `validate_move_plan` lisent le MÊME ensemble. La distance
    d'empreinte hex pour une paire non-ronde, elle, est couverte au niveau de la primitive
    (`test_round_round_engagement_uses_hex_footprint_not_euclidean_clearance`).
    """
    monkeypatch.setattr(
        "engine.spatial_relations.engagement_distance_metric",
        lambda *args, **kwargs: "hex",
    )
    mover = {"id": "u1", "player": 1, "BASE_SHAPE": "oval", "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5}

    # (0,0) est à distance hex 2 de l'ennemi (0,2) : il est donc dans la dilatation de rayon ez=2.
    assert move_anchor_violates_engagement_clearance(
        {"enemy_adjacent_hexes_player_1": {(0, 0), (0, 1)}},
        mover,
        0,
        0,
        {(0, 0)},
        units_cache={},
        enemy_adjacent_hexes=None,
        enemy_cache_items=[],
        engagement_zone_ez=2,
    ) is True

    assert move_anchor_violates_engagement_clearance(
        {"enemy_adjacent_hexes_player_1": {(0, 1)}},
        mover,
        0,
        0,
        {(0, 0)},
        units_cache={},
        enemy_adjacent_hexes=None,
        enemy_cache_items=[],
        engagement_zone_ez=2,
    ) is False
