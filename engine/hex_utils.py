"""
Hex grid primitives — single source of truth (Boardx10-final §2.2, §2.3).

Coordinate system: offset odd-q
  - (col, row) with 0 <= col < COLS, 0 <= row < ROWS
  - Odd columns (col % 2 == 1) are shifted +½ row downward

All functions are O(1) per call unless documented otherwise.
"""

import heapq
import math
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple, cast

import numpy as np


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
    set_a: Set[Tuple[int, int]], set_b: Set[Tuple[int, int]],
    max_distance: int = 0,
) -> int:
    """Minimum hex distance between any cell in set_a and any cell in set_b (§3.3).

    Used for distance between unit footprints (occupied_hexes).
    Returns 0 if sets overlap. Raises ValueError if either set is empty.

    Args:
        max_distance: If > 0, the result is only guaranteed exact while it is
            <= max_distance. When the sets are farther apart, a value strictly
            greater than max_distance is returned (a cube bounding-box lower
            bound, not necessarily max_distance + 1) — sufficient for the
            threshold tests (<= / >) every caller performs. With max_distance == 0
            the exact distance is always returned.

    Computes a cube bounding-box lower bound in O(|A|+|B|); if that already
    exceeds max_distance the bound is returned without pairwise work. Otherwise
    the cells of A are scanned nearest-first (by cube distance to B's bounding-box
    centre) against B with early-exit, avoiding the O(|A|*|B|) worst case on large
    overlapping footprints (base_size=18 ≈ 211 hexes, base_size=35 ≈ 1113 hexes).
    """
    if not set_a or not set_b:
        raise ValueError("Cannot compute distance between empty sets")
    if set_a & set_b:
        return 0

    cubes_a = [offset_to_cube(c, r) for c, r in set_a]
    cubes_b = [offset_to_cube(c, r) for c, r in set_b]
    bxs = [c[0] for c in cubes_b]
    bys = [c[1] for c in cubes_b]
    bzs = [c[2] for c in cubes_b]
    bxmin, bxmax = min(bxs), max(bxs)
    bymin, bymax = min(bys), max(bys)
    bzmin, bzmax = min(bzs), max(bzs)
    axs = [c[0] for c in cubes_a]
    ays = [c[1] for c in cubes_a]
    azs = [c[2] for c in cubes_a]

    def _axis_gap(lo1: int, hi1: int, lo2: int, hi2: int) -> int:
        if hi1 < lo2:
            return lo2 - hi1
        if hi2 < lo1:
            return lo1 - hi2
        return 0

    lower = max(
        _axis_gap(min(axs), max(axs), bxmin, bxmax),
        _axis_gap(min(ays), max(ays), bymin, bymax),
        _axis_gap(min(azs), max(azs), bzmin, bzmax),
    )
    if max_distance > 0 and lower > max_distance:
        return lower

    # Scan A nearest-first so a near-optimal `best` appears early, then early-exit
    # as soon as `best` cannot be beaten (best <= 1, or best already hits `lower`).
    cbx = (bxmin + bxmax) / 2.0
    cby = (bymin + bymax) / 2.0
    cbz = (bzmin + bzmax) / 2.0
    cubes_a.sort(key=lambda p: max(abs(p[0] - cbx), abs(p[1] - cby), abs(p[2] - cbz)))

    best = _UNREACHABLE
    for x1, y1, z1 in cubes_a:
        for x2, y2, z2 in cubes_b:
            d = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
            if d < best:
                best = d
                if best <= 1 or best == lower:
                    return best
    return best


def dilate_hex_set_unbounded(
    fp: Set[Tuple[int, int]],
    radius: int,
) -> Set[Tuple[int, int]]:
    """All hexes on the infinite odd-q grid within ``radius`` steps of ``fp`` (inclusive).

    Uses the 6-neighbor odd-q expansion (multi-source unbounded BFS). Consistent
    with the cube hex metric of ``min_distance_between_sets``: for disjoint
    non-empty footprints A and B, ``min_distance_between_sets(A, B) <= radius``
    iff ``A & dilate_hex_set_unbounded(B, radius)`` is non-empty (and same symmetrically).

    Args:
        fp: Non-empty set of (col, row) cells; empty input returns empty set.
        radius: Number of expansion layers (must be >= 0).

    Raises:
        ValueError: if ``radius`` is negative.
    """
    if radius < 0:
        raise ValueError("radius must be non-negative")
    if not fp:
        return set()
    result: Set[Tuple[int, int]] = set(fp)
    frontier = list(fp)
    for _ in range(radius):
        next_frontier: List[Tuple[int, int]] = []
        for c, r in frontier:
            offsets = _NEIGHBORS_ODD_COL if (c & 1) else _NEIGHBORS_EVEN_COL
            for dc, dr in offsets:
                nc, nr = c + dc, r + dr
                npos = (nc, nr)
                if npos not in result:
                    result.add(npos)
                    next_frontier.append(npos)
        frontier = next_frontier
        if not frontier:
            break
    return result


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


def batch_has_los_from_source(
    from_col: int,
    from_row: int,
    to_arr: np.ndarray,
    wall_grid: np.ndarray,
) -> np.ndarray:
    """Vectorized LoS from one source to N targets using the hex-line algorithm.

    Traces intermediate hexes (excluding endpoints) for each ray and checks
    them against ``wall_grid``. Equivalent to calling :func:`hex_line` + wall
    check on each target, but vectorized via numpy.

    Args:
        from_col, from_row: Source hex in offset odd-q.
        to_arr: int array shape (N, 2) — columns [col, row] of targets.
        wall_grid: bool array shape (board_cols, board_rows), True = wall.

    Returns:
        bool array shape (N,) — True = has LoS, False = blocked.
    """
    n_targets = len(to_arr)
    if n_targets == 0:
        return np.empty(0, dtype=bool)

    to_cols = to_arr[:, 0].astype(np.int64)
    to_rows = to_arr[:, 1].astype(np.int64)

    # offset_to_cube for source
    x1 = np.int64(from_col)
    z1 = np.int64(from_row) - np.int64((from_col - (from_col & 1)) >> 1)
    y1 = -x1 - z1

    # offset_to_cube vectorized for all targets
    x2 = to_cols
    z2 = to_rows - ((to_cols - (to_cols & 1)) >> 1)
    y2 = -x2 - z2

    n_arr = np.maximum(np.maximum(np.abs(x2 - x1), np.abs(y2 - y1)), np.abs(z2 - z1))

    result = np.ones(n_targets, dtype=bool)
    max_n = int(n_arr.max())
    if max_n <= 1:
        return result  # 0 or 1 steps: no intermediate hexes possible

    # Nudged float source coords (same tiebreak nudge as hex_line)
    fx1 = float(from_col) + 1e-6
    fy1 = float(y1) + 1e-6
    fz1 = float(z1) - 2e-6

    fx2 = x2.astype(np.float64) + 1e-6
    fy2 = y2.astype(np.float64) + 1e-6
    fz2 = z2.astype(np.float64) - 2e-6

    board_cols, board_rows = wall_grid.shape

    for i in range(1, max_n):
        # Active rays: not yet blocked and step i is intermediate (i < n_j)
        active = result & (n_arr > i)
        if not active.any():
            break

        idx_active = np.where(active)[0]
        n_active = n_arr[idx_active].astype(np.float64)
        t = float(i) / n_active

        fx = fx1 + (fx2[idx_active] - fx1) * t
        fy = fy1 + (fy2[idx_active] - fy1) * t
        fz = fz1 + (fz2[idx_active] - fz1) * t

        rx = np.round(fx).astype(np.int64)
        ry = np.round(fy).astype(np.int64)
        rz = np.round(fz).astype(np.int64)

        dx = np.abs(rx.astype(np.float64) - fx)
        dy = np.abs(ry.astype(np.float64) - fy)
        dz = np.abs(rz.astype(np.float64) - fz)

        # Tiebreak: recompute the coordinate with the largest rounding error
        mask_x = (dx > dy) & (dx > dz)
        mask_y = (~mask_x) & (dy > dz)
        mask_z = (~mask_x) & (~mask_y)

        # Masks are mutually exclusive — use original rx/ry/rz in each formula
        rx_f = np.where(mask_x, -ry - rz, rx)
        ry_f = np.where(mask_y, -rx - rz, ry)
        rz_f = np.where(mask_z, -rx - ry, rz)

        # cube_to_offset: col = x, row = z + ((x - (x & 1)) >> 1)
        c_off = rx_f
        r_off = rz_f + ((rx_f - (rx_f & 1)) >> 1)

        in_bounds = (
            (c_off >= 0) & (c_off < board_cols) & (r_off >= 0) & (r_off < board_rows)
        )
        is_wall = np.zeros(len(idx_active), dtype=bool)
        if in_bounds.any():
            c_v = c_off[in_bounds]
            r_v = r_off[in_bounds]
            is_wall[in_bounds] = wall_grid[c_v, r_v]

        result[idx_active[is_wall]] = False

    return result


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


def _hex_projected(c: int, r: int) -> tuple:
    hex_horiz_spacing = 1.5
    hex_vert_spacing = math.sqrt(3.0)
    hx = c * hex_horiz_spacing
    hy = r * hex_vert_spacing + ((c % 2) * hex_vert_spacing) / 2.0
    return hx, hy


def _objective_rect_hexes(
    *,
    top_left: Sequence,
    bottom_right: Sequence,
    cols: int,
    rows: int,
) -> List[List[int]]:
    px_min, py_min = _hex_projected(int(top_left[0]), int(top_left[1]))
    px_max, py_max = _hex_projected(int(bottom_right[0]), int(bottom_right[1]))
    if px_min > px_max:
        px_min, px_max = px_max, px_min
    if py_min > py_max:
        py_min, py_max = py_max, py_min

    c1 = max(0, min(int(top_left[0]), int(bottom_right[0])))
    c2 = min(cols - 1, max(int(top_left[0]), int(bottom_right[0])))
    r1 = max(0, min(int(top_left[1]), int(bottom_right[1])))
    r2 = min(rows - 1, max(int(top_left[1]), int(bottom_right[1])))

    out: List[List[int]] = []
    for c in range(c1, c2 + 1):
        for r in range(r1, r2 + 1):
            hx, hy = _hex_projected(c, r)
            if px_min <= hx <= px_max and py_min <= hy <= py_max:
                out.append([c, r])
    return out


def _objective_triangle_hexes(
    *,
    vertices: Sequence,
    cols: int,
    rows: int,
) -> List[List[int]]:
    (ax, ay) = _hex_projected(int(vertices[0][0]), int(vertices[0][1]))
    (bx, by) = _hex_projected(int(vertices[1][0]), int(vertices[1][1]))
    (cx, cy) = _hex_projected(int(vertices[2][0]), int(vertices[2][1]))

    col_min = max(0, min(int(v[0]) for v in vertices) - 1)
    col_max = min(cols - 1, max(int(v[0]) for v in vertices) + 1)
    row_min = max(0, min(int(v[1]) for v in vertices) - 1)
    row_max = min(rows - 1, max(int(v[1]) for v in vertices) + 1)

    def _sign(px, py, x1, y1, x2, y2) -> float:
        return (px - x2) * (y1 - y2) - (x1 - x2) * (py - y2)

    out: List[List[int]] = []
    for c in range(col_min, col_max + 1):
        for r in range(row_min, row_max + 1):
            px, py = _hex_projected(c, r)
            d1 = _sign(px, py, ax, ay, bx, by)
            d2 = _sign(px, py, bx, by, cx, cy)
            d3 = _sign(px, py, cx, cy, ax, ay)
            has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
            has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
            if not (has_neg and has_pos):
                out.append([c, r])
    return out


def _objective_polygon_hexes(
    *,
    vertices: Sequence,
    cols: int,
    rows: int,
) -> List[List[int]]:
    """Generate hexes inside an arbitrary polygon (3+ vertices) via ray-casting.

    Uses the same odd-q projection as rect/triangle so tilted (rotated)
    footprints are captured exactly from their corner coordinates.
    """
    pts = [_hex_projected(int(v[0]), int(v[1])) for v in vertices]
    n = len(pts)
    col_min = max(0, min(int(v[0]) for v in vertices) - 1)
    col_max = min(cols - 1, max(int(v[0]) for v in vertices) + 1)
    row_min = max(0, min(int(v[1]) for v in vertices) - 1)
    row_max = min(rows - 1, max(int(v[1]) for v in vertices) + 1)

    def _inside(px: float, py: float) -> bool:
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if ((yi > py) != (yj > py)) and (
                px < (xj - xi) * (py - yi) / (yj - yi) + xi
            ):
                inside = not inside
            j = i
        return inside

    out: List[List[int]] = []
    for c in range(col_min, col_max + 1):
        for r in range(row_min, row_max + 1):
            px, py = _hex_projected(c, r)
            if _inside(px, py):
                out.append([c, r])
    return out


def polygon_to_hex_list(vertices: list, cols: int, rows: int) -> List[List[int]]:
    """Rasterize an arbitrary polygon (3+ [col, row] vertices) to the list of board hexes
    whose centers fall inside it, using the same odd-q projection as objectives/terrain rendering.

    Public wrapper around the objective polygon rasterizer so terrain areas share the exact
    same hex membership semantics as objective zones and the frontend board renderer.
    """
    if not isinstance(vertices, (list, tuple)) or len(vertices) < 3:
        raise ValueError(f"polygon_to_hex_list: need >= 3 vertices, got {vertices!r}")
    return _objective_polygon_hexes(vertices=vertices, cols=cols, rows=rows)


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


def _objective_line_hexes(
    p1: Sequence[int],
    p2: Sequence[int],
    cols: int,
    rows: int,
) -> List[List[int]]:
    c0, r0 = int(p1[0]), int(p1[1])
    c1, r1 = int(p2[0]), int(p2[1])
    dc = abs(c1 - c0)
    dr = abs(r1 - r0)
    sc = 1 if c1 > c0 else -1
    sr = 1 if r1 > r0 else -1
    err = dc - dr
    c, r = c0, r0
    out: List[List[int]] = []
    while True:
        if 0 <= c < cols and 0 <= r < rows:
            out.append([c, r])
        if c == c1 and r == r1:
            break
        e2 = 2 * err
        if e2 > -dr:
            err -= dr
            c += sc
        if e2 < dc:
            err += dc
            r += sr
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
    - Explicit:  {"id": ..., "name": ..., "hexes": [[c, r], ...]}
    - Disc:      {"id": ..., "name": ..., "shape": "disc", "center": [c, r], "diameter": N}
    - Rectangle: {"id": ..., "name": ..., "shape": "rect", "top_left": [c, r], "bottom_right": [c, r]}
    - Triangle:  {"id": ..., "name": ..., "shape": "triangle", "vertices": [[c,r],[c,r],[c,r]]}
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
        if shape == "disc":
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
        elif shape == "rect":
            top_left = objective.get("top_left")
            bottom_right = objective.get("bottom_right")
            if not isinstance(top_left, (list, tuple)) or len(top_left) < 2:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'top_left' must be [col, row]"
                )
            if not isinstance(bottom_right, (list, tuple)) or len(bottom_right) < 2:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'bottom_right' must be [col, row]"
                )
            objective_out["hexes"] = _objective_rect_hexes(
                top_left=top_left,
                bottom_right=bottom_right,
                cols=cols,
                rows=rows,
            )
        elif shape == "triangle":
            vertices = objective.get("vertices")
            if not isinstance(vertices, (list, tuple)) or len(vertices) != 3:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'vertices' must be a list of 3 [col, row]"
                )
            for vi, v in enumerate(vertices):
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] vertices[{vi}] must be [col, row]"
                    )
            objective_out["hexes"] = _objective_triangle_hexes(
                vertices=vertices,
                cols=cols,
                rows=rows,
            )
        elif shape == "line":
            vertices = objective.get("vertices")
            if not isinstance(vertices, (list, tuple)) or len(vertices) != 2:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'vertices' must be a list of 2 [col, row]"
                )
            for vi, v in enumerate(vertices):
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] vertices[{vi}] must be [col, row]"
                    )
            objective_out["hexes"] = _objective_line_hexes(
                p1=vertices[0],
                p2=vertices[1],
                cols=cols,
                rows=rows,
            )
        elif shape == "polygon":
            vertices = objective.get("vertices")
            if not isinstance(vertices, (list, tuple)) or len(vertices) < 3:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'vertices' must be a list of >= 3 [col, row]"
                )
            for vi, v in enumerate(vertices):
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] vertices[{vi}] must be [col, row]"
                    )
            objective_out["hexes"] = _objective_polygon_hexes(
                vertices=vertices,
                cols=cols,
                rows=rows,
            )
        else:
            raise ValueError(
                f"{path_hint}: objective[{idx}] unsupported shape {shape!r} (expected 'disc', 'rect', 'triangle', or 'polygon')"
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
) -> Tuple[float, bool]:
    """Compute (visibility_ratio, can_see) for a single-hex pair.

    Drop-in replacement for _get_los_visibility_state (shooting_handlers)
    and _has_los_from_topology (observation_builder) without needing the
    n×n topology matrix.

    Binary visibility (rule 06.01): can_see = ratio > 0 (no threshold).

    Args:
        from_col, from_row: Shooter position.
        to_col, to_row: Target position.
        wall_set: Set of (col, row) wall hexes.

    Returns:
        (visibility_ratio, can_see)
    """
    v = compute_los_visibility(from_col, from_row, to_col, to_row, wall_set)
    return v, v > 0.0


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

# Flat-top odd-q pixel embedding (same layout as frontend BoardDisplay / hexToPixel).
# Normalized with hex_radius = 1 (center to vertex):
#   hex_width  = 1.5   — horizontal distance between column centers
#   hex_height = sqrt(3) — vertical distance between row centers
# Odd columns are staggered down by hex_height / 2.
#
# Footprint diameters (round/square/oval) are expressed in hex-cell counts. The legacy
# embedding used horizontal column pitch 1.0; flat-top centers use pitch ``hex_width``.
# Scale footprint semi-axes so a given diameter still spans the same approximate number
# of cells as before.
_FOOTPRINT_SIZE_SCALE: float = 1.5


def _hex_center(col: int, row: int) -> Tuple[float, float]:
    """Pixel-space center of hex (col, row) in offset odd-q, flat-top layout.

    Matches ``frontend/src/utils/hexFootprint.ts`` (and ``hexToPixel`` there) up to
    ``hex_radius`` and margin. x-axis horizontal, y-axis vertical (down).
    """
    hex_radius = 1.0
    hex_width = 1.5 * hex_radius
    hex_height = math.sqrt(3.0) * hex_radius
    x = col * hex_width + hex_width / 2.0
    y = row * hex_height + ((col & 1) * hex_height) / 2.0 + hex_height / 2.0
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
        if not isinstance(base_size, (int, float)):
            raise ValueError(f"round base_size must be numeric, got {type(base_size).__name__}")
        return _footprint_round(center_col, center_row, base_size)
    elif base_shape == "oval":
        if not isinstance(base_size, (list, tuple)) or len(base_size) != 2:
            raise ValueError(f"oval base_size must be [major, minor], got {base_size}")
        return _footprint_oval(center_col, center_row, base_size[0], base_size[1], orientation)
    elif base_shape == "square":
        if not isinstance(base_size, (int, float)):
            raise ValueError(f"square base_size must be numeric, got {type(base_size).__name__}")
        return _footprint_square(center_col, center_row, base_size, orientation)
    else:
        raise ValueError(f"Unknown base_shape: {base_shape!r} (expected 'round', 'oval', or 'square')")


def compute_footprint_placement_mask(
    board_cols: int,
    board_rows: int,
    offsets_even: Tuple[Tuple[int, int], ...],
    offsets_odd: Tuple[Tuple[int, int], ...],
    obstacles: Set[Tuple[int, int]],
) -> bytearray:
    """Masque O(1) « placement invalide » par ancre (utilisé par le BFS multi-hex).

    Retourne un ``bytearray`` de taille ``board_cols * board_rows`` indexé
    ``col + row * board_cols``. Une ancre vaut ``1`` si le socle centré dessus
    **sort du plateau** ou **chevauche un obstacle** (``obstacles`` = union
    murs ∪ ennemis, ou murs ∪ toutes les occupations selon le contexte d'appel).

    Minkowski inverse : pour chaque cellule obstacle, on marque en ``1`` tous
    les ancres qui la couvriraient. Complexité ``O(|obstacles| × |offsets|)``
    + ``O(cols × rows)`` pour les bornes. Aligné sur la reconstruction décrite
    par ``precompute_footprint_offsets``.
    """
    n_cells = board_cols * board_rows
    bad = bytearray(n_cells)

    min_dc_e = min((dc for dc, _ in offsets_even), default=0)
    max_dc_e = max((dc for dc, _ in offsets_even), default=0)
    min_dr_e = min((dr for _, dr in offsets_even), default=0)
    max_dr_e = max((dr for _, dr in offsets_even), default=0)
    min_dc_o = min((dc for dc, _ in offsets_odd), default=0)
    max_dc_o = max((dc for dc, _ in offsets_odd), default=0)
    min_dr_o = min((dr for _, dr in offsets_odd), default=0)
    max_dr_o = max((dr for _, dr in offsets_odd), default=0)

    for col in range(board_cols):
        if (col & 1) == 0:
            min_dc, max_dc, min_dr, max_dr = min_dc_e, max_dc_e, min_dr_e, max_dr_e
        else:
            min_dc, max_dc, min_dr, max_dr = min_dc_o, max_dc_o, min_dr_o, max_dr_o
        col_oob = (col + min_dc < 0) or (col + max_dc >= board_cols)
        if col_oob:
            base = col
            for row in range(board_rows):
                bad[base + row * board_cols] = 1
            continue
        for row in range(board_rows):
            if (row + min_dr < 0) or (row + max_dr >= board_rows):
                bad[col + row * board_cols] = 1

    for fc, fr in obstacles:
        for dc, dr in offsets_even:
            nc = fc - dc
            if (nc & 1) != 0:
                continue
            nr = fr - dr
            if 0 <= nc < board_cols and 0 <= nr < board_rows:
                bad[nc + nr * board_cols] = 1
        for dc, dr in offsets_odd:
            nc = fc - dc
            if (nc & 1) != 1:
                continue
            nr = fr - dr
            if 0 <= nc < board_cols and 0 <= nr < board_rows:
                bad[nc + nr * board_cols] = 1

    return bad


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
    radius = (diameter / 2.0) * _FOOTPRINT_SIZE_SCALE
    radius_sq = radius**2
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
    a = (major / 2.0) * _FOOTPRINT_SIZE_SCALE
    b = (minor / 2.0) * _FOOTPRINT_SIZE_SCALE
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
    half = (side / 2.0) * _FOOTPRINT_SIZE_SCALE
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
    get_footprint: Callable[..., Set[Tuple[int, int]]],
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


def build_dense_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Extract dense_wall_hexes (murs issus de terrains Solid/dense, rule 13.11) as a hex set.

    Sous-ensemble de wall_hexes limité aux murs typés ``"dense"`` à la source. Sert la règle
    13.5 (Gone to Ground) : seul un terrain Solid intervenant peut rendre un modèle "gone to
    ground", pas une simple obscuring area. Les murs sans type (forme brute ``wall_hexes`` sans
    classification) ne sont PAS Solid-prouvables → absents de ce set (aucun repli : on ne
    déclenche GtG que derrière un terrain dense avéré)."""
    raw = game_state.get("dense_wall_hexes")
    if not raw:
        return set()
    return {
        (int(w[0]), int(w[1])) if isinstance(w, (list, tuple)) else w
        for w in raw
    }


# ---------------------------------------------------------------------------
# Euclidean clearance — round bases (Board ×10), aligné sur frontend hexFootprint
# ---------------------------------------------------------------------------

# Pas horizontal entre centres de cases (repère _hex_center, hex_radius = 1).
ENGAGEMENT_NORM_HEX_WIDTH: float = 1.5


def round_base_radius_norm(base_size: float) -> float:
    """Rayon d'un socle rond en unités _hex_center (identique à ``_footprint_round``)."""
    if base_size < 1:
        base_size = 1
    return (base_size / 2.0) * _FOOTPRINT_SIZE_SCALE


def euclidean_edge_clearance_round_round(
    center_col_a: int,
    center_row_a: int,
    base_size_a: float,
    center_col_b: int,
    center_row_b: int,
    base_size_b: float,
    *,
    mover_center_xy: Optional[Tuple[float, float]] = None,
) -> float:
    """Écart bord à bord entre deux socles ronds (négatif si chevauchement).

    ``mover_center_xy`` : optionnel, centre déjà calculé pour ``(center_col_a, center_row_a)``
    (évite des milliers de ``_hex_center`` identiques dans les boucles d’engagement).
    """
    if mover_center_xy is not None:
        cxa, cya = mover_center_xy
    else:
        cxa, cya = _hex_center(center_col_a, center_row_a)
    cxb, cyb = _hex_center(center_col_b, center_row_b)
    d = math.hypot(cxb - cxa, cyb - cya)
    return d - round_base_radius_norm(base_size_a) - round_base_radius_norm(base_size_b)


def engagement_minimum_clearance_norm(engagement_zone: int) -> float:
    """Écart bord à bord minimal d'engagement, en unités ``_hex_center``.

    ``engagement_zone`` : portée d'engagement exprimée en SOUS-HEX, soit
    ``game_rules['engagement_zone']`` (en pouces) × ``inches_to_subhex``, déjà convertie au
    chargement. Le seuil renvoyé = ``engagement_zone`` × pas horizontal normalisé — aligné
    ``getFightEngagementRingBoardPixels`` / ``engagementRoundRingPreviewHexesOnBoard``.
    """
    if engagement_zone <= 0:
        return 0.0
    return float(engagement_zone) * ENGAGEMENT_NORM_HEX_WIDTH


# ---------------------------------------------------------------------------
# Chevauchement de socles — test unifié (plan collision continue, étape 0)
# ---------------------------------------------------------------------------

# Tolérance flottante : un écart bord-à-bord >= -_OVERLAP_TOL est considéré « sans
# chevauchement » (tangence/contact toléré, superposition interdite). Même ordre de
# grandeur que le 1e-6 du test d'engagement.
_OVERLAP_TOL: float = 1e-6


class Socle(NamedTuple):
    """Socle d'une figurine (ou empreinte d'une escouade) pour les tests de distance.

    ``fp`` (empreinte = cellules occupées) n'est nécessaire que pour la méthode
    empreinte (toute paire impliquant une base non ronde). Pour une paire ronde↔ronde
    MONO-figurine, le test est purement géométrique (centre + base_size) et ``fp`` peut
    rester None. ``base_size`` : diamètre (round/square) ou [major, minor] (oval).

    ``model_centers`` : centres (col,row) de CHAQUE figurine vivante de l'escouade
    (source : ``occupied_hexes_by_model``). Requis pour mesurer une distance bord-à-bord
    ronde correcte vers une escouade multi-figurines : sans lui, le raccourci round↔round
    mesurerait jusqu'à la seule figurine-ancre (règle 01.04 : point le plus proche des
    socles). ``None`` ou liste à 1 élément → mono-figurine, comportement historique.
    """
    shape: str
    base_size: "int | list[int]"
    col: int
    row: int
    fp: Optional[Set[Tuple[int, int]]] = None
    model_centers: Optional[List[Tuple[int, int]]] = None
    orientation: int = 0


def bounding_radius_norm(shape: str, base_size: "int | list[int]") -> float:
    """Rayon englobant (unités ``_hex_center``), toutes formes — pour la broad-phase.

    Conservateur : pour oval/square on prend la plus grande dimension. Aligné sur
    ``_FOOTPRINT_SIZE_SCALE`` comme ``round_base_radius_norm``.
    """
    dim = max(base_size) if isinstance(base_size, (list, tuple)) else base_size
    if dim < 1:
        dim = 1
    return (dim / 2.0) * _FOOTPRINT_SIZE_SCALE


def footprints_overlap(a: Socle, b: Socle) -> bool:
    """True si les deux socles se chevauchent (superposition interdite ; contact toléré).

    - Paire ronde↔ronde : clearance euclidien **continu** (exact). Chevauchement si l'écart
      bord-à-bord est strictement négatif (``< -_OVERLAP_TOL``) ; tangence (gap≈0) autorisée.
    - Toute paire impliquant une base non ronde : **méthode empreinte** (intersection des
      cellules). ``a.fp`` et ``b.fp`` doivent alors être fournis.

    Broad-phase (distance des centres vs rayons englobants) appliquée UNIQUEMENT devant le
    méthode empreinte : pour une paire ronde le test précis est déjà O(1), une broad-phase
    y serait redondante.
    """
    if a.shape == "round" and b.shape == "round":
        gap = euclidean_edge_clearance_round_round(
            a.col, a.row, cast(float, a.base_size), b.col, b.row, cast(float, b.base_size)
        )
        return gap < -_OVERLAP_TOL
    # Méthode empreinte (au moins une base non ronde) : broad-phase, puis intersection.
    cxa, cya = _hex_center(a.col, a.row)
    cxb, cyb = _hex_center(b.col, b.row)
    d = math.hypot(cxb - cxa, cyb - cya)
    reach = bounding_radius_norm(a.shape, a.base_size) + bounding_radius_norm(b.shape, b.base_size)
    if d > reach + _OVERLAP_TOL:
        return False
    if a.fp is None or b.fp is None:
        raise ValueError("footprints_overlap: empreinte (fp) requise pour une paire non ronde")
    return bool(a.fp & b.fp)


# Échantillonnage du contour d'un socle oval en polygone convexe pour la distance
# bord-à-bord continue. 32 sommets : l'erreur d'inscription max (corde vs arc) est
# < 0,5 % du demi-grand axe — négligeable devant la précision de portée requise.
_OVAL_EDGE_SAMPLES: int = 32


def _socle_edge_primitives(s: Socle) -> List[Tuple]:
    """Primitives géométriques continues (repère ``_hex_center``) d'un socle, une par figurine.

    Retourne une liste de primitives : ``('c', cx, cy, r)`` pour un socle rond (cercle
    analytique), ``('p', [(x, y), ...])`` pour oval/carré (polygone convexe orienté).
    ``model_centers`` (escouade multi-figurines) → une primitive par figurine ; sinon une
    seule primitive à l'ancre ``(col, row)``. L'orientation (oval/carré) vient de ``s.orientation``.
    """
    centers = s.model_centers if s.model_centers else [(s.col, s.row)]
    prims: List[Tuple] = []
    if s.shape == "round":
        r = round_base_radius_norm(cast(float, s.base_size))
        for c, rr in centers:
            cx, cy = _hex_center(int(c), int(rr))
            prims.append(("c", cx, cy, r))
        return prims
    ang = s.orientation * math.pi / 3.0
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    if s.shape == "oval":
        size = cast(list, s.base_size)
        aa = (size[0] / 2.0) * _FOOTPRINT_SIZE_SCALE
        bb = (size[1] / 2.0) * _FOOTPRINT_SIZE_SCALE
        local = [
            (aa * math.cos(2.0 * math.pi * k / _OVAL_EDGE_SAMPLES),
             bb * math.sin(2.0 * math.pi * k / _OVAL_EDGE_SAMPLES))
            for k in range(_OVAL_EDGE_SAMPLES)
        ]
    elif s.shape == "square":
        half = (cast(float, s.base_size) / 2.0) * _FOOTPRINT_SIZE_SCALE
        local = [(-half, -half), (half, -half), (half, half), (-half, half)]
    else:
        raise ValueError(f"euclidean_edge_distance: forme de socle inconnue {s.shape!r}")
    for c, rr in centers:
        cx, cy = _hex_center(int(c), int(rr))
        prims.append(("p", [
            (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)
            for lx, ly in local
        ]))
    return prims


def _circle_poly_edge_dist(cx: float, cy: float, r: float, poly: List[Tuple[float, float]]) -> float:
    """Distance bord-à-bord entre un cercle (centre, rayon) et un polygone convexe. 0 si chevauchement."""
    if _point_in_polygon(cx, cy, poly):
        return 0.0
    best = math.inf
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        d2 = _point_segment_dist_sq(cx, cy, ax, ay, bx, by)
        if d2 < best:
            best = d2
    d = math.sqrt(best) - r
    return d if d > 0.0 else 0.0


def _poly_poly_edge_dist(pa: List[Tuple[float, float]], pb: List[Tuple[float, float]]) -> float:
    """Distance bord-à-bord entre deux polygones convexes. 0 si containment ou arêtes sécantes."""
    for x, y in pa:
        if _point_in_polygon(x, y, pb):
            return 0.0
    for x, y in pb:
        if _point_in_polygon(x, y, pa):
            return 0.0
    best = math.inf
    na, nb = len(pa), len(pb)
    for i in range(na):
        ax, ay = pa[i]
        bx, by = pa[(i + 1) % na]
        for j in range(nb):
            cx, cy = pb[j]
            dx, dy = pb[(j + 1) % nb]
            d2 = _seg_seg_dist_sq(ax, ay, bx, by, cx, cy, dx, dy)
            if d2 < best:
                best = d2
                if best <= 0.0:
                    return 0.0
    return math.sqrt(best)


def _primitive_edge_dist(pa: Tuple, pb: Tuple) -> float:
    """Distance bord-à-bord entre deux primitives (``'c'`` cercle / ``'p'`` polygone)."""
    if pa[0] == "c" and pb[0] == "c":
        gap = math.hypot(pb[1] - pa[1], pb[2] - pa[2]) - pa[3] - pb[3]
        return gap if gap > 0.0 else 0.0
    if pa[0] == "c":
        return _circle_poly_edge_dist(pa[1], pa[2], pa[3], pb[1])
    if pb[0] == "c":
        return _circle_poly_edge_dist(pb[1], pb[2], pb[3], pa[1])
    return _poly_poly_edge_dist(pa[1], pb[1])


def euclidean_edge_distance(a: Socle, b: Socle) -> float:
    """Distance euclidienne **bord-à-bord** entre deux socles, en unités ``_hex_center``.

    Équivalent euclidien de ``min_distance_between_sets`` (règle 01.04 : on mesure au
    point le plus proche des socles). Même dispatch que ``footprints_overlap``, mais
    renvoie la distance au lieu d'un booléen de chevauchement.

    - Paire ronde↔ronde : clearance euclidien continu (exact), O(1), via
      ``euclidean_edge_clearance_round_round``. Borné à 0 (socles tangents/chevauchants).
    - Toute paire impliquant une base non ronde : distance bord-à-bord **continue** entre les
      contours géométriques réels (cercle analytique / polygone convexe oval ou carré orienté),
      via ``_socle_edge_primitives`` — plus l'approximation centre-de-cellule. Escouade
      multi-figurines : min sur chaque paire de figurines. 0 si les socles se chevauchent.

    ÉCHELLE : résultat en unités ``_hex_center`` (1 subhex = ``_FOOTPRINT_SIZE_SCALE`` = 1,5).
    Pour comparer à une portée en subhexes, l'appelant convertit le seuil :
    ``distance <= rng_subhex * ENGAGEMENT_NORM_HEX_WIDTH``.
    """
    if a.shape == "round" and b.shape == "round":
        # Règle 01.04 : distance au point le plus proche des socles. Pour une escouade
        # multi-figurines, on prend le min du clearance bord-à-bord sur chaque paire de
        # figurines (centres réels), pas seulement l'ancre. Mono-figurine → une seule paire
        # = comportement historique.
        centers_a = a.model_centers if a.model_centers else [(a.col, a.row)]
        centers_b = b.model_centers if b.model_centers else [(b.col, b.row)]
        base_a = cast(float, a.base_size)
        base_b = cast(float, b.base_size)
        best = math.inf
        for ca, ra in centers_a:
            for cb, rb in centers_b:
                gap = euclidean_edge_clearance_round_round(ca, ra, base_a, cb, rb, base_b)
                if gap < best:
                    best = gap
                    if best <= 0.0:
                        return 0.0
        return best if best > 0.0 else 0.0
    # Au moins une base non ronde : distance bord-à-bord continue entre contours géométriques.
    prims_a = _socle_edge_primitives(a)
    prims_b = _socle_edge_primitives(b)
    best = math.inf
    for pa in prims_a:
        for pb in prims_b:
            d = _primitive_edge_dist(pa, pb)
            if d < best:
                best = d
                if best <= 0.0:
                    return 0.0
    return best if best > 0.0 else 0.0


def _point_in_polygon(px: float, py: float, poly: Sequence[Tuple[float, float]]) -> bool:
    """Ray casting : True si (px,py) est à l'intérieur du polygone (mêmes semantiques que
    le rasterizer ``_objective_polygon_hexes``)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_segment_dist_sq(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Distance au carré minimale du point (px,py) au segment [a,b]."""
    dx, dy = bx - ax, by - ay
    seg_sq = dx * dx + dy * dy
    if seg_sq <= 0.0:
        return (px - ax) ** 2 + (py - ay) ** 2  # segment dégénéré -> distance au point a
    t = ((px - ax) * dx + (py - ay) * dy) / seg_sq
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    qx, qy = ax + t * dx, ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


# ---------------------------------------------------------------------------
# Champ de distance géodésique any-angle (lazy Theta* en flood) — Étape 4.0.
#
# Porté du spike `spikes/geodesic_field_spike.py` sur la VRAIE géométrie moteur :
#   - centres via `_hex_center` (pas hex_width/hex_height locaux) ;
#   - voisins via `get_neighbors` (odd-q autoritaire, = listes inline du BFS move).
# Résultat en unités `_hex_center` (1 subhex = ENGAGEMENT_NORM_HEX_WIDTH = 1,5).
#
# Deux généralisations vs le spike :
#   - `clearance` : le test de visibilité devient un test de CAPSULE (segment épaissi
#     du rayon de socle). À `clearance=0` → LoS-ray (tangence à un coin convexe permise,
#     comme le spike, pour serrer un angle isolé) ; à `clearance>0` → un disque de rayon
#     `clearance` ne peut passer à moins de `clearance` d'un mur (règle 03 : mesurer le
#     point le plus éloigné du socle revient à mesurer le CENTRE avec obstacles gonflés,
#     puisqu'en translation tout point du socle parcourt la distance du centre).
#   - `obstacles` : ensemble générique de cellules bloquantes (murs, et selon les toggles
#     de traversée : ennemis / amis / bande d'EZ) — pas seulement les murs.
#
# GRAZING / SQUEEZE (2026-07-04) : à `clearance=0` la règle « deux murs jointifs bloquent
# le passage par leur coin partagé » n'est PAS gérée (LoS-ray, tangence permise) — assumé
# pour le point/oval (l'oval est géré en amont par dilatation d'empreinte). À `clearance>0`
# elle EST gérée, mais PAS « de fait » : le rattachement (plus bas) teste le pas adjacent
# `cur→nb` à la capsule et écarte `nb` si le socle y chevaucherait un mur → un socle rond ne
# peut ni traverser ni se centrer sur un goulot plus étroit que son diamètre. Sans ce test,
# le flood cellule-par-cellule se faufilait partout (la clearance ne bornait que le raccourci
# any-angle). Cf. « 4.0-bis » de Documentation/Distance management.md.
# ---------------------------------------------------------------------------

_SEG_TOL: float = 1e-9
_HEX_CIRCUMRADIUS: float = 1.0  # centre→sommet dans le repère `_hex_center`
# Décalages des 6 sommets flat-top (précalculés une fois : évite 6 cos/sin par test d'obstacle).
_HEX_CORNER_OFFSETS: Tuple[Tuple[float, float], ...] = tuple(
    (_HEX_CIRCUMRADIUS * math.cos(math.radians(60 * k)),
     _HEX_CIRCUMRADIUS * math.sin(math.radians(60 * k)))
    for k in range(6)
)


def _hex_corners_at(cx: float, cy: float) -> List[Tuple[float, float]]:
    """6 sommets d'une cellule flat-top centrée en (cx, cy) (circumradius 1)."""
    return [(cx + ox, cy + oy) for ox, oy in _HEX_CORNER_OFFSETS]


def build_hex_center_index(
    hexes: "set[tuple[int, int]] | Sequence[Tuple[int, int]]", bucket_size: float
) -> Dict[Tuple[int, int], List[Tuple[float, float]]]:
    """Index spatial des centres ``_hex_center`` des ``hexes``, groupés par bucket de côté
    ``bucket_size``. Construit UNE fois, réutilisé par ``disc_overlaps_indexed_hexes`` pour un test
    O(1) amorti par case (au lieu de re-parcourir tout ``hexes``). ``bucket_size`` doit valoir la
    portée de contact (``r + circumradius``) pour qu'un hexagone chevauchant soit dans le bucket de la
    case testée ou l'un de ses 8 voisins."""
    idx: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    for hc, hr in hexes:
        cx, cy = _hex_center(int(hc), int(hr))
        idx.setdefault((int(cx // bucket_size), int(cy // bucket_size)), []).append((cx, cy))
    return idx


def disc_overlaps_indexed_hexes(
    cx: float, cy: float, r: float,
    index: Dict[Tuple[int, int], List[Tuple[float, float]]], bucket_size: float,
) -> bool:
    """True si le disque ``((cx,cy), r)`` chevauche l'un des hexagones indexés par
    ``build_hex_center_index`` (même ``bucket_size``). Pendant STATIONNAIRE de la clairance capsule du
    champ géodésique du move (un socle rond « heurte » un hex-obstacle ssi son disque le chevauche) →
    réplique EXACTEMENT, hors BFS, la clairance ``_low_clear`` du move. Ne teste que le bucket de la case
    et ses 8 voisins (portée = ``r + circumradius`` = ``bucket_size``)."""
    if not index:
        return False
    reach_sq = (r + _HEX_CIRCUMRADIUS) ** 2
    gx, gy = int(cx // bucket_size), int(cy // bucket_size)
    for bgx in (gx - 1, gx, gx + 1):
        for bgy in (gy - 1, gy, gy + 1):
            for (hx, hy) in index.get((bgx, bgy), ()):  # get allowed
                if (hx - cx) ** 2 + (hy - cy) ** 2 > reach_sq:
                    continue
                if disc_overlaps_polygon(cx, cy, r, _hex_corners_at(hx, hy)):
                    return True
    return False


def _obstacle_bucket_size(clearance: float) -> float:
    """Taille de bucket de l'index spatial d'obstacles (unités ``_hex_center``)."""
    return max(2.0, _HEX_CIRCUMRADIUS + (clearance if clearance > 0.0 else 0.0))


def _build_obstacle_index(
    obstacles: Set[Tuple[int, int]], bucket_size: float,
    center: Optional[Tuple[float, float]] = None, reach_sq: Optional[float] = None,
) -> Dict[Tuple[int, int], List[Tuple[float, float]]]:
    """Index spatial : bucket (grille pixel) → centres des obstacles. Chaque obstacle est inscrit
    dans SON bucket ET ses 8 voisins (la marge circumradius+clearance ≤ bucket_size est ainsi
    absorbée à la construction). Un segment n'a donc qu'à visiter les buckets qu'il TRAVERSE
    (DDA), sans balayage latéral par segment. Centres précalculés une fois.

    ``center``/``reach_sq`` (optionnels) : élagage à la source — un obstacle dont le centre est
    au-delà de ``reach_sq`` du départ ne peut affecter aucune cellule atteignable (voir
    ``geodesic_field``), il est donc omis de l'index. Sans ces params : aucun élagage (comportement
    d'origine, utilisé par le multi-source)."""
    idx: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    _cx, _cy = center if center is not None else (0.0, 0.0)
    for (wc, wr) in obstacles:
        ocx, ocy = _hex_center(wc, wr)
        if reach_sq is not None and (ocx - _cx) * (ocx - _cx) + (ocy - _cy) * (ocy - _cy) > reach_sq:
            continue
        bgx, bgy = int(ocx // bucket_size), int(ocy // bucket_size)
        for gx in range(bgx - 1, bgx + 2):
            for gy in range(bgy - 1, bgy + 2):
                idx.setdefault((gx, gy), []).append((ocx, ocy))
    return idx


def _segment_clear_indexed(
    ax: float, ay: float, bx: float, by: float,
    bucket_size: float, idx: Dict[Tuple[int, int], List[Tuple[float, float]]], clearance: float,
) -> bool:
    """``segment_clear`` sur index pré-bâti : DDA (Amanatides-Woo) le long du segment — ne visite
    que les buckets réellement traversés (chacun une fois). La marge est déjà dans l'index."""
    if not idx:
        return True
    gx, gy = int(ax // bucket_size), int(ay // bucket_size)
    gxe, gye = int(bx // bucket_size), int(by // bucket_size)
    # Rejet rapide : l'hexagone tient dans le disque circumradius autour de son centre ; si ce
    # centre est plus loin que circumradius+clearance du segment, aucun contact possible → on
    # évite `_hex_corners_at` (alloc) + le test capsule (12 arêtes) pour la plupart des obstacles.
    _reach = _HEX_CIRCUMRADIUS + (clearance if clearance > 0.0 else 0.0) + _SEG_TOL
    _reach_sq = _reach * _reach

    def _hit(bgx: int, bgy: int) -> bool:
        bucket = idx.get((bgx, bgy))
        if bucket:
            for (ocx, ocy) in bucket:
                if _point_segment_dist_sq(ocx, ocy, ax, ay, bx, by) > _reach_sq:
                    continue
                if _segment_hits_hex(ax, ay, bx, by, _hex_corners_at(ocx, ocy), ocx, ocy, clearance):
                    return True
        return False

    if _hit(gx, gy):
        return False
    if gx == gxe and gy == gye:
        return True
    dx, dy = bx - ax, by - ay
    step_x = 1 if dx > 0 else -1
    step_y = 1 if dy > 0 else -1
    t_delta_x = bucket_size / abs(dx) if dx != 0 else math.inf
    t_delta_y = bucket_size / abs(dy) if dy != 0 else math.inf
    if dx > 0:
        t_max_x = ((gx + 1) * bucket_size - ax) / dx
    elif dx < 0:
        t_max_x = (gx * bucket_size - ax) / dx
    else:
        t_max_x = math.inf
    if dy > 0:
        t_max_y = ((gy + 1) * bucket_size - ay) / dy
    elif dy < 0:
        t_max_y = (gy * bucket_size - ay) / dy
    else:
        t_max_y = math.inf
    while True:
        if t_max_x < t_max_y:
            if t_max_x > 1.0:
                break
            gx += step_x
            t_max_x += t_delta_x
        else:
            if t_max_y > 1.0:
                break
            gy += step_y
            t_max_y += t_delta_y
        if _hit(gx, gy):
            return False
        if gx == gxe and gy == gye:
            break
    return True


def _segment_crosses_hex_interior(
    ax: float, ay: float, bx: float, by: float,
    corners: Sequence[Tuple[float, float]], cx: float, cy: float,
) -> bool:
    """True si [A,B] traverse l'INTÉRIEUR de la cellule (longueur d'intersection > 0).

    Cyrus-Beck sur l'hexagone convexe. La simple tangence à un sommet/arête ne bloque
    PAS (on peut serrer l'angle convexe d'un mur isolé = plus court chemin). Identique
    au `_segment_hits_hex` du spike.
    """
    dx, dy = bx - ax, by - ay
    t_enter, t_exit = 0.0, 1.0
    for i in range(6):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 6]
        ex, ey = x2 - x1, y2 - y1
        nx, ny = ey, -ex  # normale de l'arête
        if (nx * (cx - x1) + ny * (cy - y1)) > 0:  # oriente vers l'extérieur
            nx, ny = -nx, -ny
        denom = nx * dx + ny * dy
        num = nx * (ax - x1) + ny * (ay - y1)
        if abs(denom) < 1e-12:
            if num > 1e-12:
                return False  # parallèle et hors du demi-plan
            continue
        t = -num / denom
        if denom < 0:
            t_enter = max(t_enter, t)
        else:
            t_exit = min(t_exit, t)
        if t_enter > t_exit:
            return False
    return (t_exit - t_enter) > _SEG_TOL


def _seg_seg_dist_sq(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> float:
    """Distance au carré minimale entre les segments [A,B] et [C,D] (0 s'ils se coupent)."""
    r0x, r0y = bx - ax, by - ay
    s0x, s0y = dx - cx, dy - cy
    denom = r0x * s0y - r0y * s0x
    if abs(denom) > 1e-12:  # non parallèles : test d'intersection propre
        t = ((cx - ax) * s0y - (cy - ay) * s0x) / denom
        u = ((cx - ax) * r0y - (cy - ay) * r0x) / denom
        if -1e-12 <= t <= 1.0 + 1e-12 and -1e-12 <= u <= 1.0 + 1e-12:
            return 0.0
    return min(
        _point_segment_dist_sq(cx, cy, ax, ay, bx, by),
        _point_segment_dist_sq(dx, dy, ax, ay, bx, by),
        _point_segment_dist_sq(ax, ay, cx, cy, dx, dy),
        _point_segment_dist_sq(bx, by, cx, cy, dx, dy),
    )


def _segment_hits_hex(
    ax: float, ay: float, bx: float, by: float,
    corners: Sequence[Tuple[float, float]], cx: float, cy: float, clearance: float,
) -> bool:
    """True si le segment [A,B] épaissi de `clearance` heurte la cellule.

    `clearance <= 0` : intérieur strict (LoS-ray). `clearance > 0` : capsule — bloqué
    si la distance segment↔hexagone est < clearance.
    """
    if clearance <= _SEG_TOL:
        return _segment_crosses_hex_interior(ax, ay, bx, by, corners, cx, cy)
    if _segment_crosses_hex_interior(ax, ay, bx, by, corners, cx, cy):
        return True
    thr_sq = (clearance - _SEG_TOL) ** 2
    for i in range(6):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 6]
        if _seg_seg_dist_sq(ax, ay, bx, by, x1, y1, x2, y2) < thr_sq:
            return True
    return False


def segment_clear(
    ax: float, ay: float, bx: float, by: float,
    obstacles: Set[Tuple[int, int]], clearance: float = 0.0,
) -> bool:
    """True si aucune cellule bloquante ne coupe le segment [A,B] (épaissi de `clearance`).

    `obstacles` : cellules (col,row) bloquantes (murs + ennemis/amis/EZ selon toggles).
    Bâtit un index spatial à la volée ; pour des appels répétés (le champ), préférer
    `_build_obstacle_index` + `_segment_clear_indexed` (index bâti une seule fois).
    """
    if not obstacles:
        return True
    bs = _obstacle_bucket_size(clearance)
    return _segment_clear_indexed(ax, ay, bx, by, bs, _build_obstacle_index(obstacles, bs), clearance)


def geodesic_field(
    start: Tuple[int, int],
    board_cols: int,
    board_rows: int,
    obstacles: Set[Tuple[int, int]],
    budget: float,
    clearance: float = 0.0,
) -> Dict[Tuple[int, int], float]:
    """Distance géodésique any-angle de `start` à chaque cellule atteignable dans `budget`.

    Lazy Theta* en flood (Dijkstra + rattachement d'un nœud à l'ANCÊTRE de son voisin si
    la ligne de vue est dégagée → coût = vraie distance euclidienne, chemins à angle libre).

    - `board_cols`/`board_rows` : bornes du plateau (une cellule est libre si dans les bornes
      et pas dans `obstacles` — pas de set plein board à matérialiser).
    - `obstacles` : cellules bloquantes (voir `segment_clear`).
    - `budget` : distance max en unités `_hex_center` (= MOVE_subhex × ENGAGEMENT_NORM_HEX_WIDTH).
    - `clearance` : rayon de socle (règle 03). 0 = robot-point.

    Retourne {cellule: distance}. Une seule passe (champ complet), pas point-à-point.
    Sur-estime légèrement (lazy Theta* quasi-optimal) → ne triche jamais vs la règle 03.
    """
    if start in obstacles:
        raise ValueError(f"geodesic_field: start {start} est un obstacle")
    bs = _obstacle_bucket_size(clearance)
    # Élagage lossless : un obstacle dont le centre est au-delà de ``budget + clearance + 4·circumradius``
    # du départ ne peut bloquer aucun segment testé. Preuve : tout point d'un segment (ancre→voisin) est
    # à ≤ budget + pas_hex du départ (norme convexe, max aux extrémités ; ancre/voisin atteignables donc
    # à ≤ budget euclidien ≤ budget géodésique) ; un mur bloque à ≤ clearance + circumradius de ce point.
    # 4·circumradius couvre pas_hex (≤ 2·circ) + extent mur (circ) + marge. Retire les murs hors zone
    # atteignable → index plus petit, résultat identique.
    _gf_sx, _gf_sy = _hex_center(*start)
    _gf_reach = budget + (clearance if clearance > 0.0 else 0.0) + 4.0 * _HEX_CIRCUMRADIUS
    idx = _build_obstacle_index(obstacles, bs, center=(_gf_sx, _gf_sy), reach_sq=_gf_reach * _gf_reach)
    g: Dict[Tuple[int, int], float] = {start: 0.0}
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {start: start}
    pq: List[Tuple[float, Tuple[int, int]]] = [(0.0, start)]
    closed: Set[Tuple[int, int]] = set()

    while pq:
        d, cur = heapq.heappop(pq)
        if cur in closed:
            continue
        closed.add(cur)
        cx, cy = _hex_center(*cur)
        par = parent[cur]
        px, py = _hex_center(*par)
        g_par, g_cur = g[par], g[cur]
        for nb in get_neighbors(*cur):
            nc, nr = nb
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            if nb in obstacles or nb in closed:
                continue
            nx, ny = _hex_center(nc, nr)
            # Rattachement à l'ancêtre si LoS dégagé (cœur de Theta*).
            if _segment_clear_indexed(px, py, nx, ny, bs, idx, clearance):
                anchor, axr, ayr, base = par, px, py, g_par
            elif clearance <= _SEG_TOL or _segment_clear_indexed(cx, cy, nx, ny, bs, idx, clearance):
                # Raccourci ancêtre bloqué → pas adjacent cur→nb, testé à la CAPSULE : à
                # `clearance>0` un socle ne peut ni transiter ni se centrer sur `nb` s'il
                # chevauche un mur (couvre goulot + corner-cutting). Court-circuit à
                # `clearance<=0` : le gate est prouvé no-op (oval/point/gym-hex) → zéro surcoût.
                anchor, axr, ayr, base = cur, cx, cy, g_cur
            else:
                continue  # nb inatteignable via cur (mur trop proche) ; re-proposé par un autre voisin
            cand = base + math.hypot(nx - axr, ny - ayr)
            if cand <= budget + _SEG_TOL and cand < g.get(nb, math.inf):
                g[nb] = cand
                parent[nb] = anchor
                heapq.heappush(pq, (cand, nb))
    return g


def geodesic_field_multi_source(
    starts: Dict[Tuple[int, int], float],
    board_cols: int,
    board_rows: int,
    obstacles: Set[Tuple[int, int]],
    budget: float,
    clearance: float = 0.0,
) -> Dict[Tuple[int, int], float]:
    """Variante MULTI-SOURCE de ``geodesic_field`` : plusieurs départs, chacun avec sa distance
    initiale ``starts[cell]``. Une seule passe couvre toutes les sources (Dijkstra classique à
    fronts multiples) → évite de relancer un champ single-source par source (perf : O(1) passe au
    lieu de O(sources) passes). Utilisé pour le mouvement multi-niveaux (entrées d'étage seedées
    en bloc). ``budget`` borne la distance TOTALE (init + trajet). Sources dans ``obstacles`` ignorées.

    Retourne ``{cellule: distance_totale}`` — chaque source est sa propre ancre (any-angle depuis elle).
    """
    bs = _obstacle_bucket_size(clearance)
    idx = _build_obstacle_index(obstacles, bs)
    g: Dict[Tuple[int, int], float] = {}
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}
    pq: List[Tuple[float, Tuple[int, int]]] = []
    for s, d0 in starts.items():
        if s in obstacles or d0 > budget + _SEG_TOL:
            continue
        if d0 < g.get(s, math.inf):
            g[s] = d0
            parent[s] = s
            heapq.heappush(pq, (d0, s))
    closed: Set[Tuple[int, int]] = set()

    while pq:
        d, cur = heapq.heappop(pq)
        if cur in closed:
            continue
        closed.add(cur)
        cx, cy = _hex_center(*cur)
        par = parent[cur]
        px, py = _hex_center(*par)
        g_par, g_cur = g[par], g[cur]
        for nb in get_neighbors(*cur):
            nc, nr = nb
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            if nb in obstacles or nb in closed:
                continue
            nx, ny = _hex_center(nc, nr)
            if _segment_clear_indexed(px, py, nx, ny, bs, idx, clearance):
                anchor, axr, ayr, base = par, px, py, g_par
            elif clearance <= _SEG_TOL or _segment_clear_indexed(cx, cy, nx, ny, bs, idx, clearance):
                anchor, axr, ayr, base = cur, cx, cy, g_cur
            else:
                continue
            cand = base + math.hypot(nx - axr, ny - ayr)
            if cand <= budget + _SEG_TOL and cand < g.get(nb, math.inf):
                g[nb] = cand
                parent[nb] = anchor
                heapq.heappush(pq, (cand, nb))
    return g


def disc_overlaps_polygon(
    cx: float, cy: float, r: float, poly: Sequence[Tuple[float, float]]
) -> bool:
    """True si un disque (centre (cx,cy), rayon r) chevauche ou touche un polygone.

    Repère ``_hex_center`` : (cx,cy) ET les sommets ``poly`` doivent y être exprimés, cohérent
    avec ``round_base_radius_norm`` (le rayon) et avec le rendu terrain (vertices projetés par
    ``toPixelT`` côté frontend, même projection que ``_hex_center``). Pendant fig↔terrain de
    ``euclidean_edge_clearance_round_round`` (fig↔fig) : sert au test « within a terrain area »
    (règles 13.08 cover / 13.09 hidden) pour les bases rondes.

    Overlap si le centre est dans le polygone, OU si une arête est à distance <= r (contact /
    tangence compté comme « within », cohérent avec la base qui touche la zone)."""
    if len(poly) < 3:
        raise ValueError(f"disc_overlaps_polygon: polygone invalide ({len(poly)} sommets)")
    if _point_in_polygon(cx, cy, poly):
        return True
    r_sq = r * r
    n = len(poly)
    j = n - 1
    for i in range(n):
        if _point_segment_dist_sq(cx, cy, poly[j][0], poly[j][1], poly[i][0], poly[i][1]) <= r_sq:
            return True
        j = i
    return False


def disc_within_polygon(
    cx: float, cy: float, r: float, poly: Sequence[Tuple[float, float]]
) -> bool:
    """True si un disque (centre (cx,cy), rayon r) est ENTIÈREMENT inclus dans un polygone simple.

    Pendant strict de ``disc_overlaps_polygon`` : ici on exige l'inclusion totale (aucun débordement
    du bord), pour le confinement « socle rond entièrement sur l'étage » (13.06). Exact pour tout
    polygone simple (convexe OU concave) : le disque est inclus ssi son centre est dans le polygone ET
    la distance du centre à chaque arête est >= r (le bord n'entre alors jamais dans le disque).
    Tangence (distance == r) tolérée = socle qui affleure le bord sans le dépasser."""
    if len(poly) < 3:
        raise ValueError(f"disc_within_polygon: polygone invalide ({len(poly)} sommets)")
    if not _point_in_polygon(cx, cy, poly):
        return False
    r_sq = r * r
    n = len(poly)
    j = n - 1
    for i in range(n):
        if _point_segment_dist_sq(cx, cy, poly[j][0], poly[j][1], poly[i][0], poly[i][1]) < r_sq:
            return False
        j = i
    return True


def disc_within_any_polygon(
    cx: float, cy: float, r: float, polys: Sequence[Sequence[Tuple[float, float]]]
) -> bool:
    """True si le disque est entièrement inclus dans AU MOINS UN des polygones.

    Conservateur sur une union de polygones adjacents (un socle à cheval sur la frontière commune de
    deux étages distincts serait rejeté) : côté sûr, jamais de débordement autorisé. En pratique un
    étage de ruine = un seul polygone, donc exact. ``polys`` vide → False (aucune surface où tenir)."""
    return any(disc_within_polygon(cx, cy, r, p) for p in polys)
