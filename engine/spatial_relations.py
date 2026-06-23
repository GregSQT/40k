"""Shared spatial relation helpers for footprint contact and engagement checks."""

from typing import Any, Dict, List, Optional, Set, Tuple, cast

from engine.hex_utils import (
    _hex_center,
    compute_occupied_hexes,
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
    """Engagement zone en sous-hexes. NB: game_rules['engagement_zone'] est DÉJÀ converti
    (× inches_to_subhex) au chargement dans w40k_core (clé scalée). Ne PAS re-multiplier ici."""
    config = require_key(game_state, "config")
    game_rules = require_key(config, "game_rules")
    return int(require_key(game_rules, "engagement_zone"))


def get_engagement_zone_from_config(config: Dict[str, Any]) -> int:
    """engagement_zone déjà converti au chargement (cf. get_engagement_zone)."""
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


def _cache_entry_round_base_size(cache_entry: Dict[str, Any]) -> float:
    """Return a round base size from a cache entry, raising when the stored value is invalid."""
    base_size = require_key(cache_entry, "BASE_SIZE")
    if not isinstance(base_size, (int, float)):
        raise TypeError(f"round BASE_SIZE must be numeric, got {type(base_size).__name__}")
    return base_size


# Hex count of a single base, memoized by geometry. The COUNT is invariant under
# translation and depends only on (shape, size, orientation, column parity) — see
# precompute_footprint_offsets: only column parity shifts the odd-q footprint.
_SINGLE_BASE_HEX_COUNT_CACHE: Dict[Tuple[Any, ...], int] = {}


def _single_base_hex_count(
    base_shape: str, base_size: Any, orientation: int, col_parity: int
) -> int:
    """Memoized number of hexes occupied by one base of the given geometry."""
    size_key = tuple(base_size) if isinstance(base_size, (list, tuple)) else base_size
    key = (base_shape, size_key, orientation, col_parity)
    cached = _SINGLE_BASE_HEX_COUNT_CACHE.get(key)
    if cached is None:
        # col_parity as the reference column preserves odd-q parity; row 0 is arbitrary
        # (the count is translation-invariant), matching the legacy per-call computation.
        cached = len(compute_occupied_hexes(col_parity, 0, base_shape, cast("int | list[int]", base_size), orientation))
        _SINGLE_BASE_HEX_COUNT_CACHE[key] = cached
    return cached


def _entry_is_multi_figure(cache_entry: Dict[str, Any]) -> bool:
    """True when a cache entry's live footprint spans more than one base (a squad).

    Uses ``occupied_hexes`` (kept live from models_cache, dead figs removed) compared to
    the footprint of a single base — never the stale init-time ``entry["models"]`` snapshot.
    A multi-figure squad cannot be reduced to one round circle at its anchor, so the
    euclidean round-round shortcut is invalid for it and the footprint metric is used.
    """
    occ = cache_entry.get("occupied_hexes")
    if not occ:
        return False
    single_count = _single_base_hex_count(
        require_key(cache_entry, "BASE_SHAPE"),
        require_key(cache_entry, "BASE_SIZE"),
        int(require_key(cache_entry, "orientation")),
        int(require_key(cache_entry, "col")) & 1,
    )
    return len(occ) > single_count


def unit_entries_within_engagement_zone(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
) -> bool:
    """Return True when two unit cache entries are within the shared engagement contract."""
    # Métrique d'engagement unifiée : distance d'empreinte (hex), jamais euclidien.
    # Identique à la légalité de placement move (move_anchor_violates_engagement_clearance).
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

    # Métrique d'engagement unifiée : distance d'empreinte (hex), jamais euclidien.
    # Aligné avec l'éligibilité tir (unit_entries_within_engagement_zone).
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
        if (
            min_distance_between_sets(
                candidate_fp, enemy_fp, max_distance=engagement_zone_ez
            )
            <= engagement_zone_ez
        ):
            return True
    return False
