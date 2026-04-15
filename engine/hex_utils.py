"""
Hex grid primitives — single source of truth (Boardx10-final §2.2, §2.3).

Coordinate system: offset odd-q
  - (col, row) with 0 <= col < COLS, 0 <= row < ROWS
  - Odd columns (col % 2 == 1) are shifted +½ row downward

All functions are O(1) per call unless documented otherwise.
"""

import math
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Neighbor offsets — offset odd-q (§2.2 P2)
# ---------------------------------------------------------------------------

_NEIGHBORS_EVEN_COL: Tuple[Tuple[int, int], ...] = (
    (0, -1),    # N
    (1, -1),    # NE
    (1, 0),     # SE
    (0, 1),     # S
    (-1, 0),    # SW
    (-1, -1),   # NW
)

_NEIGHBORS_ODD_COL: Tuple[Tuple[int, int], ...] = (
    (0, -1),    # N
    (1, 0),     # NE
    (1, 1),     # SE
    (0, 1),     # S
    (-1, 1),    # SW
    (-1, 0),    # NW
)


def get_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """Return the 6 hex neighbors of (col, row) in offset odd-q.

    No bounds checking — caller must filter out-of-bounds if needed.
    """
    offsets = _NEIGHBORS_ODD_COL if (col & 1) else _NEIGHBORS_EVEN_COL
    return [(col + dc, row + dr) for dc, dr in offsets]


def get_neighbors_bounded(
    col: int, row: int, cols: int, rows: int
) -> List[Tuple[int, int]]:
    """Return neighbors of (col, row) that are within [0, cols) × [0, rows)."""
    offsets = _NEIGHBORS_ODD_COL if (col & 1) else _NEIGHBORS_EVEN_COL
    result: List[Tuple[int, int]] = []
    for dc, dr in offsets:
        nc, nr = col + dc, row + dr
        if 0 <= nc < cols and 0 <= nr < rows:
            result.append((nc, nr))
    return result


# ---------------------------------------------------------------------------
# Coordinate conversions — offset odd-q ↔ cube (§2.2 P2)
# ---------------------------------------------------------------------------

def offset_to_cube(col: int, row: int) -> Tuple[int, int, int]:
    """Convert offset odd-q (col, row) to cube (x, y, z).

    x = col
    z = row - (col - (col & 1)) // 2
    y = -x - z
    """
    x = col
    z = row - ((col - (col & 1)) >> 1)
    y = -x - z
    return x, y, z


def cube_to_offset(x: int, y: int, z: int) -> Tuple[int, int]:
    """Convert cube (x, y, z) to offset odd-q (col, row)."""
    col = x
    row = z + ((x - (x & 1)) >> 1)
    return col, row


# ---------------------------------------------------------------------------
# Distance (§2.2 P2)
# ---------------------------------------------------------------------------

def hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Hex distance between two offset odd-q positions (straight line, no walls).

    Uses cube coordinates: distance = max(|dx|, |dy|, |dz|).
    """
    x1, y1, z1 = offset_to_cube(col1, row1)
    x2, y2, z2 = offset_to_cube(col2, row2)
    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


def min_distance_between_sets(
    set_a: Set[Tuple[int, int]], set_b: Set[Tuple[int, int]]
) -> int:
    """Minimum hex distance between any cell in set_a and any cell in set_b (§3.3).

    Used for distance between unit footprints (occupied_hexes).
    Returns 0 if sets overlap. Raises ValueError if either set is empty.
    """
    if not set_a or not set_b:
        raise ValueError("Cannot compute distance between empty sets")
    if set_a & set_b:
        return 0
    best = _UNREACHABLE
    for c1, r1 in set_a:
        x1, y1, z1 = offset_to_cube(c1, r1)
        for c2, r2 in set_b:
            x2, y2, z2 = offset_to_cube(c2, r2)
            d = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
            if d < best:
                best = d
                if best == 1:
                    return 1
    return best


# ---------------------------------------------------------------------------
# Bounds checking
# ---------------------------------------------------------------------------

def is_in_bounds(col: int, row: int, cols: int, rows: int) -> bool:
    """Check if (col, row) is within [0, cols) × [0, rows)."""
    return 0 <= col < cols and 0 <= row < rows


# ---------------------------------------------------------------------------
# Coordinate normalization (moved from combat_utils — kept for compat)
# ---------------------------------------------------------------------------

def normalize_coordinate(coord: Any) -> int:
    """Normalize a single coordinate to int.

    Raises ValueError/TypeError on invalid input.
    """
    if isinstance(coord, int):
        return coord
    if isinstance(coord, float):
        return int(coord)
    if isinstance(coord, str):
        try:
            return int(float(coord))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid coordinate string '{coord}': {e}") from e
    raise TypeError(
        f"Invalid coordinate type {type(coord).__name__}: {coord}. "
        "Expected int, float, or numeric string."
    )


def normalize_coordinates(col: Any, row: Any) -> Tuple[int, int]:
    """Normalize (col, row) to (int, int)."""
    return normalize_coordinate(col), normalize_coordinate(row)


# ---------------------------------------------------------------------------
# Hex line (grid traversal / supercover) — for LoS rays (§7.3)
# ---------------------------------------------------------------------------

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def hex_line(
    col1: int, row1: int, col2: int, row2: int
) -> List[Tuple[int, int]]:
    """Return hex cells along the line from (col1,row1) to (col2,row2).

    Uses cube-space linear interpolation then rounds to nearest hex.
    Includes both endpoints. Order: from start to end.
    """
    if col1 == col2 and row1 == row2:
        return [(col1, row1)]

    x1, y1, z1 = offset_to_cube(col1, row1)
    x2, y2, z2 = offset_to_cube(col2, row2)

    n = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
    results: List[Tuple[int, int]] = []
    seen: Set[Tuple[int, int]] = set()

    for i in range(n + 1):
        t = i / n if n > 0 else 0.0
        fx = _lerp(x1 + 1e-6, x2 + 1e-6, t)
        fy = _lerp(y1 + 1e-6, y2 + 1e-6, t)
        fz = _lerp(z1 - 2e-6, z2 - 2e-6, t)

        rx = round(fx)
        ry = round(fy)
        rz = round(fz)

        dx = abs(rx - fx)
        dy = abs(ry - fy)
        dz = abs(rz - fz)
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy > dz:
            ry = -rx - rz
        else:
            rz = -rx - ry

        c, r = cube_to_offset(rx, ry, rz)
        if (c, r) not in seen:
            seen.add((c, r))
            results.append((c, r))

    return results


def expand_wall_group_to_hex_list(
    group: Dict[str, Any],
    *,
    path_hint: str = "wall group",
) -> List[List[int]]:
    """Expand one wall JSON object into a list of [col, row] (deduplicated, order preserved).

    Supported keys:
    - ``hexes``: optional list of ``[col, row]`` (explicit blocked cells).
    - ``segments``: optional list of segments ``[[c1, r1], [c2, r2]]``; each segment is
      expanded with :func:`hex_line` (offset odd-q), endpoints included.

    At least one of ``hexes`` or ``segments`` must be non-empty after parsing.
    """
    if "hexes" in group and group["hexes"] is not None:
        hexes_raw = group["hexes"]
        if not isinstance(hexes_raw, list):
            raise ValueError(f"{path_hint}: 'hexes' must be a list")
    else:
        hexes_raw = []

    if "segments" in group and group["segments"] is not None:
        segments_raw = group["segments"]
        if not isinstance(segments_raw, list):
            raise ValueError(f"{path_hint}: 'segments' must be a list")
    else:
        segments_raw = []

    if len(hexes_raw) == 0 and len(segments_raw) == 0:
        raise ValueError(
            f"{path_hint}: wall group must define non-empty 'hexes' and/or 'segments'"
        )

    seen: Set[Tuple[int, int]] = set()
    out: List[List[int]] = []

    def _add_cell(c: int, r: int) -> None:
        t = (c, r)
        if t not in seen:
            seen.add(t)
            out.append([c, r])

    for h in hexes_raw:
        if not isinstance(h, (list, tuple)) or len(h) < 2:
            raise ValueError(f"{path_hint}: invalid wall hex {h!r}")
        _add_cell(int(h[0]), int(h[1]))

    for seg_i, seg in enumerate(segments_raw):
        if not isinstance(seg, list) or len(seg) != 2:
            raise ValueError(
                f"{path_hint}: segment {seg_i} must be [[c1,r1],[c2,r2]], got {seg!r}"
            )
        a, b = seg[0], seg[1]
        if (
            not isinstance(a, (list, tuple))
            or not isinstance(b, (list, tuple))
            or len(a) < 2
            or len(b) < 2
        ):
            raise ValueError(f"{path_hint}: segment {seg_i} has invalid endpoints {seg!r}")
        c1, r1 = int(a[0]), int(a[1])
        c2, r2 = int(b[0]), int(b[1])
        for c, r in hex_line(c1, r1, c2, r2):
            _add_cell(c, r)

    return out


def _objective_disc_hexes(
    *,
    center_col: int,
    center_row: int,
    diameter: int,
    cols: int,
    rows: int,
) -> List[List[int]]:
    """Generate objective hexes for a Euclidean disc in odd-q projection.

    Uses the same geometric projection as the frontend board renderer:
    - HEX_HORIZ_SPACING = 1.5
    - HEX_VERT_SPACING = sqrt(3)
    - odd columns shifted by HEX_VERT_SPACING / 2
    """
    if diameter <= 0:
        raise ValueError(f"objective disc diameter must be > 0, got {diameter}")

    hex_horiz_spacing = 1.5
    hex_vert_spacing = math.sqrt(3.0)

    cx = center_col * hex_horiz_spacing
    cy = center_row * hex_vert_spacing + ((center_col % 2) * hex_vert_spacing) / 2.0
    radius_cols = diameter / 2.0
    radius_px = radius_cols * hex_horiz_spacing
    radius_sq = radius_px * radius_px

    scan_cols = int(math.ceil(radius_cols)) + 2
    scan_rows = int(math.ceil(radius_px / hex_vert_spacing)) + 3

    out: List[List[int]] = []
    col_min = max(0, center_col - scan_cols)
    col_max = min(cols - 1, center_col + scan_cols)
    row_min = max(0, center_row - scan_rows)
    row_max = min(rows - 1, center_row + scan_rows)

    for c in range(col_min, col_max + 1):
        for r in range(row_min, row_max + 1):
            hx = c * hex_horiz_spacing
            hy = r * hex_vert_spacing + ((c % 2) * hex_vert_spacing) / 2.0
            dist_sq = (hx - cx) ** 2 + (hy - cy) ** 2
            if dist_sq <= radius_sq:
                out.append([c, r])
    return out


def expand_objectives_to_hex_list(
    objectives_raw: Any,
    *,
    cols: int,
    rows: int,
    path_hint: str = "objectives",
) -> List[Dict[str, Any]]:
    """Expand objective definitions to explicit `hexes`.

    Supported objective formats:
    - Explicit: {"id": ..., "name": ..., "hexes": [[c, r], ...]}
    - Declarative disc:
      {"id": ..., "name": ..., "shape": "disc", "center": [c, r], "diameter": N}
    """
    if not isinstance(objectives_raw, list):
        raise ValueError(f"{path_hint}: objectives must be a list")

    expanded: List[Dict[str, Any]] = []
    for idx, objective in enumerate(objectives_raw):
        if not isinstance(objective, dict):
            raise ValueError(f"{path_hint}: objective[{idx}] must be an object")

        if "id" not in objective:
            raise ValueError(f"{path_hint}: objective[{idx}] missing required 'id'")
        has_hexes = "hexes" in objective and objective["hexes"] is not None
        has_shape = "shape" in objective and objective["shape"] is not None
        if has_hexes and has_shape:
            raise ValueError(
                f"{path_hint}: objective[{idx}] cannot define both 'hexes' and 'shape'"
            )

        objective_out = dict(objective)

        if has_hexes:
            hexes_raw = objective["hexes"]
            if not isinstance(hexes_raw, list):
                raise ValueError(f"{path_hint}: objective[{idx}] field 'hexes' must be a list")
            hexes_out: List[List[int]] = []
            for hi, h in enumerate(hexes_raw):
                if not isinstance(h, (list, tuple)) or len(h) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] invalid hex at index {hi}: {h!r}"
                    )
                hexes_out.append([int(h[0]), int(h[1])])
            objective_out["hexes"] = hexes_out
            expanded.append(objective_out)
            continue

        if not has_shape:
            raise ValueError(
                f"{path_hint}: objective[{idx}] must define either 'hexes' or 'shape'"
            )

        shape = objective["shape"]
        if shape != "disc":
            raise ValueError(
                f"{path_hint}: objective[{idx}] unsupported shape {shape!r} (expected 'disc')"
            )
        center = objective.get("center")
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            raise ValueError(
                f"{path_hint}: objective[{idx}] field 'center' must be [col, row]"
            )
        diameter_raw = objective.get("diameter")
        if not isinstance(diameter_raw, int):
            raise ValueError(
                f"{path_hint}: objective[{idx}] field 'diameter' must be an int"
            )

        center_col = int(center[0])
        center_row = int(center[1])
        if center_col < 0 or center_col >= cols or center_row < 0 or center_row >= rows:
            raise ValueError(
                f"{path_hint}: objective[{idx}] center {(center_col, center_row)} out of bounds "
                f"for board {cols}x{rows}"
            )
        objective_out["hexes"] = _objective_disc_hexes(
            center_col=center_col,
            center_row=center_row,
            diameter=diameter_raw,
            cols=cols,
            rows=rows,
        )
        expanded.append(objective_out)

    return expanded


# ---------------------------------------------------------------------------
# LoS — on-demand computation (§7.1, §7.2, §7.3)
# ---------------------------------------------------------------------------

_UNREACHABLE = 999_999


def compute_los_visibility(
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    wall_set: Set[Tuple[int, int]],
) -> float:
    """Compute LoS visibility ratio between two single hexes.

    Traces a hex line from (from_col, from_row) to (to_col, to_row).
    Returns 1.0 if no wall blocks the line, 0.0 if any intermediate
    cell is a wall.

    For single-hex units (legacy), this is equivalent to the old topology
    lookup. For multi-hex units, the caller should use
    compute_los_visibility_footprint (§7.2).
    """
    if from_col == to_col and from_row == to_row:
        return 1.0

    line = hex_line(from_col, from_row, to_col, to_row)
    for c, r in line[1:-1]:
        if (c, r) in wall_set:
            return 0.0
    return 1.0


def compute_los_state(
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    wall_set: Set[Tuple[int, int]],
    los_visibility_min_ratio: float,
    cover_ratio: float,
) -> Tuple[float, bool, bool]:
    """Compute (visibility_ratio, can_see, in_cover) for a single-hex pair.

    Drop-in replacement for _get_los_visibility_state (shooting_handlers)
    and _has_los_from_topology (observation_builder) without needing the
    n×n topology matrix.

    Args:
        from_col, from_row: Shooter position.
        to_col, to_row: Target position.
        wall_set: Set of (col, row) wall hexes.
        los_visibility_min_ratio: P threshold (§7.2) — from game_rules.
        cover_ratio: C threshold (§7.2) — from game_rules.

    Returns:
        (visibility_ratio, can_see, in_cover)
    """
    v = compute_los_visibility(from_col, from_row, to_col, to_row, wall_set)
    can_see = v >= los_visibility_min_ratio
    in_cover = can_see and v < cover_ratio
    return v, can_see, in_cover


# ---------------------------------------------------------------------------
# Pathfinding — bounded BFS / A* (§8.1–§8.3)
# ---------------------------------------------------------------------------

def pathfinding_distance(
    col1: int,
    row1: int,
    col2: int,
    row2: int,
    cols: int,
    rows: int,
    wall_set: Set[Tuple[int, int]],
    occupied_set: Optional[Set[Tuple[int, int]]] = None,
    max_search_distance: int = 500,
    max_open_nodes: int = 2000,
) -> int:
    """BFS shortest-path distance respecting walls and occupation (§8).

    Args:
        col1, row1: Start.
        col2, row2: End.
        cols, rows: Board dimensions.
        wall_set: Impassable hexes.
        occupied_set: Hexes occupied by other units (non-traversable).
            The destination hex is always allowed even if in occupied_set.
        max_search_distance: Max BFS depth (§9.0 max_search_distance).
        max_open_nodes: Hard cap on open-set size (§8.3 budget).

    Returns:
        Path distance in hex, or max_search_distance + 1 if unreachable.
    """
    if col1 == col2 and row1 == row2:
        return 0

    if not is_in_bounds(col1, row1, cols, rows) or not is_in_bounds(col2, row2, cols, rows):
        return max_search_distance + 1

    end = (col2, row2)
    if end in wall_set:
        return max_search_distance + 1

    occ = occupied_set or set()

    visited: Dict[Tuple[int, int], int] = {(col1, row1): 0}
    queue: List[Tuple[Tuple[int, int], int]] = [((col1, row1), 0)]
    head = 0
    nodes_expanded = 0

    while head < len(queue):
        pos, dist = queue[head]
        head += 1
        nodes_expanded += 1

        if nodes_expanded > max_open_nodes:
            break

        if pos == end:
            return dist

        if dist >= max_search_distance:
            continue

        offsets = _NEIGHBORS_ODD_COL if (pos[0] & 1) else _NEIGHBORS_EVEN_COL
        next_dist = dist + 1
        for dc, dr in offsets:
            nc, nr = pos[0] + dc, pos[1] + dr
            if nc < 0 or nr < 0 or nc >= cols or nr >= rows:
                continue
            npos = (nc, nr)
            if npos in visited:
                continue
            if npos in wall_set:
                continue
            if npos != end and npos in occ:
                continue
            visited[npos] = next_dist
            queue.append((npos, next_dist))

    return max_search_distance + 1


# ---------------------------------------------------------------------------
# Engagement zone — hex set dilation (§9.0, §8.5)
# ---------------------------------------------------------------------------

def dilate_hex_set(
    hexes: Set[Tuple[int, int]],
    radius: int,
    cols: int,
    rows: int,
) -> Set[Tuple[int, int]]:
    """Return all hexes within [1, radius] hex distance of any hex in the input set.

    The input hexes themselves are NOT included in the result (distance 0 excluded).
    Uses multi-source BFS for efficiency: O(output_size).

    Args:
        hexes: Source hex set (e.g. enemy occupied_hexes).
        radius: Max expansion distance (e.g. engagement_zone = 10).
        cols, rows: Board dimensions for bounds checking.

    Returns:
        Set of (col, row) within distance [1, radius] of any source hex, in bounds.
    """
    if not hexes or radius <= 0:
        return set()

    if radius == 1:
        result: Set[Tuple[int, int]] = set()
        for c, r in hexes:
            offsets = _NEIGHBORS_ODD_COL if (c & 1) else _NEIGHBORS_EVEN_COL
            for dc, dr in offsets:
                nc, nr = c + dc, r + dr
                if 0 <= nc < cols and 0 <= nr < rows and (nc, nr) not in hexes:
                    result.add((nc, nr))
        return result

    visited: Set[Tuple[int, int]] = set(hexes)
    frontier = list(hexes)
    result: Set[Tuple[int, int]] = set()

    for _dist in range(radius):
        next_frontier: List[Tuple[int, int]] = []
        for c, r in frontier:
            offsets = _NEIGHBORS_ODD_COL if (c & 1) else _NEIGHBORS_EVEN_COL
            for dc, dr in offsets:
                nc, nr = c + dc, r + dr
                if nc < 0 or nr < 0 or nc >= cols or nr >= rows:
                    continue
                npos = (nc, nr)
                if npos in visited:
                    continue
                visited.add(npos)
                next_frontier.append(npos)
                result.add(npos)
        frontier = next_frontier
        if not frontier:
            break

    return result


# ---------------------------------------------------------------------------
# Footprint / occupied_hexes (§2.5, §9.1)
# ---------------------------------------------------------------------------

# Hex geometry constants for offset odd-q (flat-to-flat = 1 unit).
# For pointy-top hex with flat-to-flat = w:
#   w = sqrt(3) * size  =>  size = w / sqrt(3)
#   h = 2 * size
# We normalize flat-to-flat = 1, so:
_HEX_SIZE: float = 1.0 / math.sqrt(3.0)
_HEX_W: float = 1.0                          # flat-to-flat (horizontal span)
_HEX_H: float = 2.0 * _HEX_SIZE              # point-to-point (vertical span)
_HEX_ROW_H: float = 0.75 * _HEX_H            # vertical distance between row centers


def _hex_center(col: int, row: int) -> Tuple[float, float]:
    """Pixel-space center of hex (col, row) in offset odd-q.

    x-axis: horizontal, y-axis: vertical (down).
    Flat-to-flat width = 1 unit.
    """
    x = col * _HEX_W
    if col & 1:
        y = row * _HEX_H * 0.75 + _HEX_H * 0.5
    else:
        y = row * _HEX_H * 0.75
    return x, y


def compute_occupied_hexes(
    center_col: int,
    center_row: int,
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int = 0,
) -> Set[Tuple[int, int]]:
    """Compute the set of hex cells occupied by a unit's base (§2.5).

    Args:
        center_col, center_row: Center hex of the unit.
        base_shape: "round", "oval", or "square".
        base_size: Diameter in hex for round/square; [major, minor] for oval.
        orientation: Discrete rotation step (0–5 for 60° increments).
            Only affects oval and square shapes.

    Returns:
        Set of (col, row) hex cells forming the footprint.

    Raises:
        ValueError: On unknown base_shape or invalid base_size.
    """
    if base_shape == "round":
        if not isinstance(base_size, int):
            raise ValueError(f"round base_size must be int, got {type(base_size).__name__}")
        return _footprint_round(center_col, center_row, base_size)
    elif base_shape == "oval":
        if not isinstance(base_size, (list, tuple)) or len(base_size) != 2:
            raise ValueError(f"oval base_size must be [major, minor], got {base_size}")
        return _footprint_oval(center_col, center_row, base_size[0], base_size[1], orientation)
    elif base_shape == "square":
        if not isinstance(base_size, int):
            raise ValueError(f"square base_size must be int, got {type(base_size).__name__}")
        return _footprint_square(center_col, center_row, base_size, orientation)
    else:
        raise ValueError(f"Unknown base_shape: {base_shape!r} (expected 'round', 'oval', or 'square')")


def precompute_footprint_offsets(
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int = 0,
) -> Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]:
    """Pre-compute footprint offsets for even-column and odd-column centers.

    On hex grids (offset odd-q), the pixel-space distance between a center
    and its surrounding hexes depends on column parity.  Computing the full
    footprint (via compute_occupied_hexes) is expensive when called per-BFS-step.
    This function computes it ONCE at two reference positions (one even-col,
    one odd-col) and returns relative (dc, dr) offset tuples that can be
    translated to any position in O(|footprint|).

    Args:
        base_shape: "round", "oval", or "square".
        base_size:  Diameter for round/square; [major, minor] for oval.
        orientation: Rotation step (0–5), affects oval/square only.

    Returns:
        (offsets_even, offsets_odd) where each is a tuple of (dc, dr) pairs.
        To reconstruct the footprint at (c, r):
            offsets = offsets_even if c % 2 == 0 else offsets_odd
            footprint = {(c + dc, r + dr) for dc, dr in offsets}
    """
    ref_row = 100
    fp_even = compute_occupied_hexes(0, ref_row, base_shape, base_size, orientation)
    fp_odd = compute_occupied_hexes(1, ref_row, base_shape, base_size, orientation)
    offsets_even = tuple((c - 0, r - ref_row) for c, r in fp_even)
    offsets_odd = tuple((c - 1, r - ref_row) for c, r in fp_odd)
    return offsets_even, offsets_odd


def _footprint_round(center_col: int, center_row: int, diameter: int) -> Set[Tuple[int, int]]:
    """Hex cells within a circle of given diameter (in hex units) centered on (center_col, center_row)."""
    radius_sq = (diameter / 2.0) ** 2
    cx, cy = _hex_center(center_col, center_row)
    scan_r = int(math.ceil(diameter / 2.0)) + 2
    result: Set[Tuple[int, int]] = set()
    for dc in range(-scan_r, scan_r + 1):
        for dr in range(-scan_r, scan_r + 1):
            c, r = center_col + dc, center_row + dr
            hx, hy = _hex_center(c, r)
            dist_sq = (hx - cx) ** 2 + (hy - cy) ** 2
            if dist_sq <= radius_sq:
                result.add((c, r))
    return result


def _footprint_oval(
    center_col: int, center_row: int,
    major: int, minor: int,
    orientation: int,
) -> Set[Tuple[int, int]]:
    """Hex cells within an axis-aligned ellipse, optionally rotated by orientation×60°."""
    a = major / 2.0
    b = minor / 2.0
    angle_rad = orientation * math.pi / 3.0
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    cx, cy = _hex_center(center_col, center_row)
    scan_r = int(math.ceil(max(a, b))) + 2
    result: Set[Tuple[int, int]] = set()
    for dc in range(-scan_r, scan_r + 1):
        for dr in range(-scan_r, scan_r + 1):
            c, r = center_col + dc, center_row + dr
            hx, hy = _hex_center(c, r)
            dx, dy = hx - cx, hy - cy
            lx = dx * cos_a + dy * sin_a
            ly = -dx * sin_a + dy * cos_a
            if a > 0 and b > 0 and (lx / a) ** 2 + (ly / b) ** 2 <= 1.0:
                result.add((c, r))
    return result


def _footprint_square(
    center_col: int, center_row: int,
    side: int,
    orientation: int,
) -> Set[Tuple[int, int]]:
    """Hex cells within a square of given side length, optionally rotated by orientation×60°."""
    half = side / 2.0
    angle_rad = orientation * math.pi / 3.0
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    cx, cy = _hex_center(center_col, center_row)
    scan_r = int(math.ceil(half * 1.5)) + 2
    result: Set[Tuple[int, int]] = set()
    for dc in range(-scan_r, scan_r + 1):
        for dr in range(-scan_r, scan_r + 1):
            c, r = center_col + dc, center_row + dr
            hx, hy = _hex_center(c, r)
            dx, dy = hx - cx, hy - cy
            lx = dx * cos_a + dy * sin_a
            ly = -dx * sin_a + dy * cos_a
            if abs(lx) <= half and abs(ly) <= half:
                result.add((c, r))
    return result


# ---------------------------------------------------------------------------
# Occupation map — cell → unit_id (§9.1, Invariant III §9.2)
# ---------------------------------------------------------------------------

def build_occupation_map(
    units_cache: Dict[str, Any],
    get_footprint: "callable",
) -> Dict[Tuple[int, int], str]:
    """Build sparse cell→unit_id map from all alive units.

    Args:
        units_cache: game_state["units_cache"], keyed by unit_id string.
        get_footprint: Callable(unit_entry) -> Set[(col, row)].

    Returns:
        Dict mapping each occupied cell to its unit_id.

    Raises:
        ValueError: If two units overlap (Invariant III violation).
    """
    occ: Dict[Tuple[int, int], str] = {}
    for uid, entry in units_cache.items():
        footprint = get_footprint(entry)
        for cell in footprint:
            if cell in occ:
                raise ValueError(
                    f"Invariant III violation: cell {cell} occupied by both "
                    f"unit {occ[cell]} and unit {uid}"
                )
            occ[cell] = uid
    return occ


def validate_placement(
    candidate_hexes: Set[Tuple[int, int]],
    unit_id: str,
    occupation_map: Dict[Tuple[int, int], str],
    wall_set: Set[Tuple[int, int]],
    cols: int,
    rows: int,
) -> Optional[str]:
    """Validate that a footprint can be placed without violations.

    Returns None if valid, or an error message string if invalid.
    """
    for c, r in candidate_hexes:
        if not is_in_bounds(c, r, cols, rows):
            return f"Cell ({c},{r}) out of bounds ({cols}x{rows})"
        if (c, r) in wall_set:
            return f"Cell ({c},{r}) is a wall"
        existing = occupation_map.get((c, r))
        if existing is not None and existing != unit_id:
            return f"Cell ({c},{r}) already occupied by unit {existing}"
    return None


# ---------------------------------------------------------------------------
# Wall set helper
# ---------------------------------------------------------------------------

def build_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Extract wall_hexes from game_state as a set of (int, int) tuples."""
    raw = game_state.get("wall_hexes")
    if not raw:
        return set()
    return {
        (int(w[0]), int(w[1])) if isinstance(w, (list, tuple)) else w
        for w in raw
    }
