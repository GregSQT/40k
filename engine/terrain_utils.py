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


def model_within_terrain(
    col: int,
    row: int,
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int,
    terrain_areas: List[Dict[str, Any]],
    obscuring_only: bool,
) -> bool:
    """True si le socle d'un modèle est « within a terrain area » (règles 13.08 / 13.09).

    Base RONDE : test euclidien continu disque↔polygone (``disc_overlaps_polygon`` sur les
    ``polygon_vertices``), pendant fig↔terrain de ``euclidean_edge_clearance_round_round``
    (fig↔fig) — aligné pixel-pour-pixel sur le rendu (disque d'icône + polygone terrain),
    contrairement à l'intersection de hexes rasterisés qui rogne ~½ hex de chaque côté.
    Base OVAL/SQUARE : fallback empreinte hex (intersection cellules), exactement la même
    convention hybride que l'engagement (round=euclidien, autres=hex).

    ``obscuring_only=True`` restreint aux zones obscurantes (hidden 13.09) ; ``False`` = toute
    zone de terrain (cover 13.08, volet « within terrain area »)."""
    areas = [a for a in terrain_areas if (not obscuring_only or a.get("obscuring"))]
    if not areas:
        return False
    if base_shape == "round":
        from engine.hex_utils import _hex_center, round_base_radius_norm, disc_overlaps_polygon
        cx, cy = _hex_center(int(col), int(row))
        r = round_base_radius_norm(base_size)
        for area in areas:
            poly = [_hex_center(int(v[0]), int(v[1])) for v in require_key(area, "polygon_vertices")]
            if disc_overlaps_polygon(cx, cy, r, poly):
                return True
        return False
    # Base non ronde (oval/square) : empreinte hex, comme l'engagement.
    from engine.hex_utils import compute_occupied_hexes
    fp = {
        (int(c), int(r))
        for c, r in compute_occupied_hexes(int(col), int(row), base_shape, base_size, int(orientation))
    }
    for area in areas:
        if fp & _area_hex_set(area):
            return True
    return False
