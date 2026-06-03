"""Terrain area membership helpers (hex-based).

Terrain areas are polygon zones rasterized to board hexes at load time
(see ``game_state._load_terrain_areas_from_ref``). Each area dict holds:
  - ``id``: str
  - ``obscuring``: bool
  - ``polygon_vertices``: list[[col, row]]
  - ``hexes``: list[[col, row]]  (rasterized membership, odd-q projection)

Membership is answered by testing hex appartenance against the precomputed
``hexes`` sets — same odd-q projection as objectives and the frontend renderer,
so a unit "within a terrain area" matches exactly what the player sees on board.
"""
from typing import Any, Dict, List, Set, Tuple

from shared.data_validation import require_key


def _area_hex_set(area: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return the area's rasterized hexes as a set of (col, row).

    Built inline (no mutation of the area dict) so terrain areas stay JSON-serializable.
    """
    return {(int(h[0]), int(h[1])) for h in require_key(area, "hexes")}


def resolve_unit_hexes(unit: Dict[str, Any], game_state: Dict[str, Any]) -> List[Tuple[int, int]]:
    """Return the list of (col, row) hexes occupied by a unit's footprint."""
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(str(require_key(unit, "id")))
    if not isinstance(entry, dict):
        raise KeyError(f"unit {unit.get('id')!r} not present in units_cache")
    occ = entry.get("occupied_hexes")
    if isinstance(occ, (set, list, tuple)) and len(occ) > 0:
        return [(int(h[0]), int(h[1])) for h in occ]
    return [(int(require_key(entry, "col")), int(require_key(entry, "row")))]


def get_terrain_area_ids_for_hexes(
    unit_hexes: List[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
) -> List[str]:
    """IDs of terrain areas containing at least one of the unit's hexes."""
    unit_set = {(int(c), int(r)) for c, r in unit_hexes}
    ids: List[str] = []
    for area in terrain_areas:
        if unit_set & _area_hex_set(area):
            ids.append(str(require_key(area, "id")))
    return ids


def hexes_in_any_terrain(
    unit_hexes: List[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
) -> bool:
    """True if the unit's footprint touches at least one terrain area (any kind)."""
    unit_set = {(int(c), int(r)) for c, r in unit_hexes}
    for area in terrain_areas:
        if unit_set & _area_hex_set(area):
            return True
    return False


def hexes_in_obscuring_terrain(
    unit_hexes: List[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
) -> bool:
    """True if the unit's footprint touches at least one obscuring terrain area."""
    unit_set = {(int(c), int(r)) for c, r in unit_hexes}
    for area in terrain_areas:
        if area.get("obscuring") and (unit_set & _area_hex_set(area)):
            return True
    return False
