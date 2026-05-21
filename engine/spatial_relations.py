"""Shared spatial relation helpers for footprint contact and engagement checks."""

from typing import Any, Dict, List, Optional, Set, Tuple

from engine.hex_utils import (
    _hex_center,
    engagement_minimum_clearance_norm,
    euclidean_edge_clearance_round_round,
    min_distance_between_sets,
)
from shared.data_validation import require_key


def _require_unit_position_from_cache(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[int, int]:
    """Return unit position from units_cache, raising if the unit is absent."""
    units_cache = require_key(game_state, "units_cache")
    unit_id = str(require_key(unit, "id"))
    unit_entry = units_cache.get(unit_id)
    if unit_entry is None:
        raise ValueError(f"Unit {unit_id} not in units_cache (dead or absent); cannot read position")
    return int(require_key(unit_entry, "col")), int(require_key(unit_entry, "row"))


def get_engagement_zone(game_state: Dict[str, Any]) -> int:
    """Read the canonical engagement_zone from game_state config."""
    config = require_key(game_state, "config")
    game_rules = require_key(config, "game_rules")
    return int(require_key(game_rules, "engagement_zone"))


def get_engagement_zone_from_config(config: Dict[str, Any]) -> int:
    """Read the canonical engagement_zone from a config dictionary."""
    game_rules = require_key(config, "game_rules")
    return int(require_key(game_rules, "engagement_zone"))


def enemy_footprint_distances(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    max_distance: Optional[int],
) -> List[Tuple[Any, int]]:
    """Return footprint distances from unit to enemy units using the B/engagement metric."""
    unit_col, unit_row = _require_unit_position_from_cache(game_state, unit)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    unit_player = int(unit["player"]) if unit["player"] is not None else None
    distances: List[Tuple[Any, int]] = []
    for enemy_id, cache_entry in units_cache.items():
        enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
        if enemy_player == unit_player:
            continue
        enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
        if max_distance is None:
            distance = min_distance_between_sets(unit_fp, enemy_fp)
        else:
            distance = min_distance_between_sets(unit_fp, enemy_fp, max_distance=max_distance)
        distances.append((enemy_id, distance))
    return distances


def _cache_entry_footprint(cache_entry: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return a unit cache entry footprint, using its anchor only when no footprint is stored."""
    footprint = cache_entry.get("occupied_hexes")
    if footprint:
        return footprint
    return {(require_key(cache_entry, "col"), require_key(cache_entry, "row"))}


def _cache_entry_round_base_size(cache_entry: Dict[str, Any]) -> int:
    """Return a round base size from a cache entry, raising when the stored value is invalid."""
    base_size = require_key(cache_entry, "BASE_SIZE")
    if not isinstance(base_size, int):
        raise TypeError(f"round BASE_SIZE must be int, got {type(base_size).__name__}")
    return base_size


def unit_entries_within_engagement_zone(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
) -> bool:
    """Return True when two unit cache entries are within the shared engagement contract."""
    first_shape = first_entry.get("BASE_SHAPE")
    second_shape = second_entry.get("BASE_SHAPE")
    # Euclidean round-base check is only meaningful on micro-grid boards (engagement_zone > 1).
    # On legacy boards (engagement_zone == 1, 1 hex = 1 inch), hex footprint adjacency is used.
    if engagement_zone > 1 and first_shape == "round" and second_shape == "round":
        req = engagement_minimum_clearance_norm(engagement_zone)
        gap = euclidean_edge_clearance_round_round(
            require_key(first_entry, "col"),
            require_key(first_entry, "row"),
            _cache_entry_round_base_size(first_entry),
            require_key(second_entry, "col"),
            require_key(second_entry, "row"),
            _cache_entry_round_base_size(second_entry),
        )
        return gap <= req + 1e-6

    first_fp = _cache_entry_footprint(first_entry)
    second_fp = _cache_entry_footprint(second_entry)
    return min_distance_between_sets(
        first_fp, second_fp, max_distance=engagement_zone
    ) <= engagement_zone


def unit_within_engagement_zone_footprints(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    engagement_zone: int,
    max_distance: Optional[int],
) -> bool:
    """Return True when unit is within B/engagement range of at least one enemy footprint."""
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    unit_entry = units_cache.get(unit_id_str)
    if unit_entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache (dead or absent); cannot read engagement")

    unit_player = int(require_key(unit, "player"))
    for enemy_id, cache_entry in units_cache.items():
        if str(enemy_id) == unit_id_str:
            continue
        enemy_player = int(require_key(cache_entry, "player"))
        if enemy_player == unit_player:
            continue
        if unit_entries_within_engagement_zone(unit_entry, cache_entry, engagement_zone):
            return True
    return False


def move_anchor_violates_engagement_clearance(
    game_state: Dict[str, Any],
    mover: Dict[str, Any],
    center_col: int,
    center_row: int,
    candidate_fp: Set[Tuple[int, int]],
    units_cache: Dict[str, Any],
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]],
    *,
    enemy_cache_items: Optional[List[Tuple[Any, Any]]],
    engagement_zone_ez: int,
) -> bool:
    """Return True when a move anchor violates the C/clearance engagement contract."""
    mover_id = str(require_key(mover, "id"))
    mover_player = int(require_key(mover, "player"))

    if engagement_zone_ez <= 1:
        if enemy_adjacent_hexes is None:
            ck = f"enemy_adjacent_hexes_player_{mover_player}"
            adjacent_hexes: Set[Tuple[int, int]] = require_key(game_state, ck)
        else:
            adjacent_hexes = enemy_adjacent_hexes
        for c, r in candidate_fp:
            if (c, r) in adjacent_hexes:
                return True
        return False

    req = engagement_minimum_clearance_norm(engagement_zone_ez)
    mover_shape = mover.get("BASE_SHAPE", "round")
    mover_bs = mover.get("BASE_SIZE", 1)
    mover_bs_i = mover_bs if isinstance(mover_bs, int) else 1
    mover_center_xy_rr: Optional[Tuple[float, float]] = None
    if mover_shape == "round":
        mover_center_xy_rr = _hex_center(center_col, center_row)

    if enemy_cache_items is not None:
        enemy_iter: Any = enemy_cache_items
    else:
        enemy_iter = (
            (eid, ce)
            for eid, ce in units_cache.items()
            if str(eid) != mover_id and int(require_key(ce, "player")) != mover_player
        )

    for _, cache_entry in enemy_iter:
        enemy_fp = cache_entry.get("occupied_hexes")
        if not enemy_fp:
            ec = require_key(cache_entry, "col")
            er = require_key(cache_entry, "row")
            enemy_fp = {(ec, er)}
        e_shape = cache_entry.get("BASE_SHAPE", "round")
        e_bs_raw = cache_entry.get("BASE_SIZE", 1)
        e_bs_i = e_bs_raw if isinstance(e_bs_raw, int) else 1
        e_col = require_key(cache_entry, "col")
        e_row = require_key(cache_entry, "row")

        if mover_shape == "round" and e_shape == "round":
            gap = euclidean_edge_clearance_round_round(
                center_col,
                center_row,
                mover_bs_i,
                e_col,
                e_row,
                e_bs_i,
                mover_center_xy=mover_center_xy_rr,
            )
            if gap <= req + 1e-6:
                return True
        else:
            if (
                min_distance_between_sets(
                    candidate_fp, enemy_fp, max_distance=engagement_zone_ez
                )
                <= engagement_zone_ez
            ):
                return True
    return False
