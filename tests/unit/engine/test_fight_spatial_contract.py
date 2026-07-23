"""Tests for fight spatial A/B contracts documented in Distance_functions.md."""

from engine.phase_handlers.fight_handlers import (
    _fight_build_valid_target_pool,
    _fight_footprint_has_enemy_hex_contact,
    _fight_fp_has_adjacent_enemy_footprint,
    _is_adjacent_to_enemy_within_cc_range,
)
from engine.spatial_relations import (
    unit_within_engagement_zone_footprints,
)


def _unit(unit_id: str = "u1") -> dict:
    return {"id": unit_id, "player": 1}


def test_fight_a_contact_helper_uses_hex_contact_only() -> None:
    unit = _unit()
    game_state = {
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}},
            "enemy_contact": {"col": 0, "row": 1, "player": 2, "occupied_hexes": {(0, 1)}},
            "enemy_far": {"col": 0, "row": 3, "player": 2, "occupied_hexes": {(0, 3)}},
            "ally_contact": {"col": 1, "row": 0, "player": 1, "occupied_hexes": {(1, 0)}},
        }
    }

    assert _fight_footprint_has_enemy_hex_contact(game_state, unit, {(0, 0)}) is True
    assert _fight_fp_has_adjacent_enemy_footprint(game_state, unit, {(0, 0)}) is True


def test_fight_a_contact_helper_does_not_treat_engagement_range_as_contact() -> None:
    unit = _unit()
    game_state = {
        "config": {"game_rules": {"engagement_zone": 2, "engagement_zone_vertical": 5}},
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}},
            "enemy_in_engagement": {"col": 0, "row": 2, "player": 2, "occupied_hexes": {(0, 2)}},
        },
    }

    assert _fight_footprint_has_enemy_hex_contact(game_state, unit, {(0, 0)}) is False


def test_fight_b_engagement_pool_uses_full_footprint_distance() -> None:
    unit = _unit()
    game_state = {
        "config": {"game_rules": {"engagement_zone": 2, "engagement_zone_vertical": 5}},
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "orientation": 0},
            "enemy_in_engagement": {"col": 0, "row": 2, "player": 2, "occupied_hexes": {(0, 2)}, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "orientation": 0},
            "enemy_out_of_engagement": {"col": 0, "row": 3, "player": 2, "occupied_hexes": {(0, 3)}, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "orientation": 0},
            "ally": {"col": 0, "row": 1, "player": 1, "occupied_hexes": {(0, 1)}, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "orientation": 0},
        },
    }

    assert _fight_build_valid_target_pool(game_state, unit) == ["enemy_in_engagement"]
    assert _is_adjacent_to_enemy_within_cc_range(game_state, unit) is True


def test_fight_b_engagement_pool_large_base_euclidean_not_hex() -> None:
    """Régression du faux positif analyzer « Fight from non-adjacent » (2026-07-24).

    Le gate combat mesure l'engagement en EUCLIDIEN (config distance_metric.engagement).
    Sur socles à grand diamètre, la distance bord-à-bord HEX sur-estime : une cible à
    hexEdge=11 (> ez=10) peut être euclidien-engagée (≤ ez×1,5=15) → combat LÉGAL. L'ancien
    contrôle analyzer, en hex, la flaggait faussement. Ce test fige que le pool moteur suit
    bien l'euclidien : il ACCEPTE la cible hex-non-adjacente mais euclidien-engagée, et
    REJETTE une cible réellement hors zone d'engagement.

    Attaquant round/18 @(100,100) ; cible IN round/6 @(105,81) : hexEdge=11, euclidien=14,9 ;
    cible OUT round/6 @(105,74) : hexEdge=18, euclidien=26,8. Seuil euclidien = 10×1,5 = 15.
    """
    from engine.hex_utils import compute_occupied_hexes, min_distance_between_sets

    def _entry(col: int, row: int, size: int, player: int) -> dict:
        occ = set(compute_occupied_hexes(col, row, "round", size, 0))
        return {
            "col": col, "row": row, "player": player, "occupied_hexes": occ,
            "occupied_hexes_by_model": {f"m{col}_{row}": (col, row)},
            "BASE_SHAPE": "round", "BASE_SIZE": size, "MODEL_HEIGHT": 2.5, "orientation": 0,
        }

    attacker = _entry(100, 100, 18, player=1)
    target_in = _entry(105, 81, 6, player=2)
    target_out = _entry(105, 74, 6, player=2)

    # Prémisse : la cible IN est bien HEX-non-adjacente (hexEdge > ez=10) — c'est ce qui
    # déclenchait le faux positif hex — mais le moteur (euclidien) la considère engagée.
    hex_in = min_distance_between_sets(attacker["occupied_hexes"], target_in["occupied_hexes"], max_distance=99)
    assert hex_in > 10, f"prémisse : hexEdge IN={hex_in} devrait être > ez=10"

    unit = _unit("attacker")
    game_state = {
        "config": {"game_rules": {"engagement_zone": 10, "engagement_zone_vertical": 5}},
        "units_cache": {"attacker": attacker, "t_in": target_in, "t_out": target_out},
    }

    assert _fight_build_valid_target_pool(game_state, unit) == ["t_in"]


def test_shared_b_engagement_helper_supports_full_and_bounded_distance() -> None:
    unit = _unit()
    game_state = {
        "config": {"game_rules": {"engagement_zone": 2, "engagement_zone_vertical": 5}},
        "units_cache": {
            "u1": {"col": 0, "row": 0, "player": 1, "occupied_hexes": {(0, 0)}, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "orientation": 0},
            "enemy_in_engagement": {"col": 0, "row": 2, "player": 2, "occupied_hexes": {(0, 2)}, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "orientation": 0},
            "enemy_out_of_engagement": {"col": 0, "row": 3, "player": 2, "occupied_hexes": {(0, 3)}, "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "orientation": 0},
        },
    }

    assert unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=2, max_distance=2
    ) is True
