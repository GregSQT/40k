#!/usr/bin/env python3
"""
Build topology cache for a board configuration (LoS + pathfinding).

Usage:
  python scripts/los_topology_builder.py 25x21
  python scripts/los_topology_builder.py --cols 25 --rows 21

Creates config/board/{cols}x{rows}/topology_{cols}x{rows}-{XX}.npz for each
walls-XX.json found in that directory (or in config/agents/_walls/ as fallback).

topology.npz (single file):
  los          (n, n)      float16  visibility_ratio 0-1 (~3 decimal digits)
  pathfinding  (n, n)      float16  hex distance 0-51
  wall_edge    (n, 8, 2)   float32  wall_dist + edge_dist per direction

Index: arr[from_row*cols+from_col, to_row*cols+to_col, channel]

Wall set (must match engine/w40k_core.py):
- Terrain walls from walls-XX.json (wall_hexes)
- Board boundary: (col, bottom_row) for col odd — invalid hexes at last row
  in pointy-top offset layout; treated as walls for LoS consistency.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Set, Tuple

import numpy as np


def _format_progress_time(seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _print_progress(completed: int, total: int, start_time: float, label: str = "pairs") -> None:
    """Print progress bar with elapsed time and ETA (training-style)."""
    if total <= 0:
        return
    progress_pct = (completed / total) * 100
    bar_length = 50
    filled = int(bar_length * completed / total)
    bar = "█" * filled + "░" * (bar_length - filled)

    elapsed = time.time() - start_time
    avg_time = elapsed / completed if completed > 0 else 0
    remaining = total - completed
    eta = avg_time * remaining

    elapsed_str = _format_progress_time(elapsed)
    eta_str = _format_progress_time(eta)
    speed = completed / elapsed if elapsed > 0 else 0
    speed_str = f"{speed:.1f}/s" if speed >= 1 else f"{speed * 60:.1f}/m"

    sys.stdout.write(
        f"\r{progress_pct:5.1f}% {bar} {completed}/{total} {label} "
        f"[{elapsed_str}<{eta_str}, {speed_str}]"
    )
    sys.stdout.flush()

# Project root
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _parse_dimensions(s: str) -> Tuple[int, int]:
    """Parse '25x21' or '25x11' into (cols, rows)."""
    parts = s.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid dimensions '{s}', expected COLSxROWS (e.g. 25x21)")
    return int(parts[0]), int(parts[1])


def _load_wall_hexes(wall_path: Path) -> Set[Tuple[int, int]]:
    """Load wall_hexes from a walls-XX.json file."""
    with open(wall_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    raw = data.get("wall_hexes")
    if not isinstance(raw, list):
        raise ValueError(f"{wall_path}: wall_hexes must be a list")
    result: Set[Tuple[int, int]] = set()
    for h in raw:
        if not isinstance(h, (list, tuple)) or len(h) < 2:
            raise ValueError(f"{wall_path}: invalid wall hex {h}")
        result.add((int(h[0]), int(h[1])))
    return result


def _add_board_boundary_hexes(
    wall_hexes: Set[Tuple[int, int]], cols: int, rows: int
) -> Set[Tuple[int, int]]:
    """
    Add board boundary hexes (bottom_row) to match engine/w40k_core.py.

    In pointy-top offset layout, the last row has no hexes for odd columns.
    These positions are treated as walls for LoS and movement consistency.
    """
    result = set(wall_hexes)
    bottom_row = rows - 1
    for col in range(cols):
        if col % 2 == 1:
            result.add((col, bottom_row))
    return result


def _compute_visibility_ratio(
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    wall_hexes: Set[Tuple[int, int]],
) -> float:
    """Compute LoS visibility ratio (0-1) between two hexes. Reuses engine logic."""
    from engine.phase_handlers.shooting_handlers import _compute_los_visibility_ratio

    # Dummy thresholds - we only need the ratio
    ratio, _, _ = _compute_los_visibility_ratio(
        from_col, from_row, to_col, to_row,
        wall_hexes,
        los_visibility_min_ratio=0.12,
        cover_ratio=0.75,
    )
    return float(ratio)


# 8 directions: N, NE, E, SE, S, SW, W, NW (must match observation_builder._encode_directional_terrain)
_DIRECTIONS = [
    (0, -1),   # N
    (1, -1),   # NE
    (1, 0),    # E
    (1, 1),    # SE
    (0, 1),    # S
    (-1, 1),   # SW
    (-1, 0),   # W
    (-1, -1),  # NW
]

# Perception radius used when no wall/edge found (matches observation_builder default)
_PERCEPTION_RADIUS = 25.0


def _is_in_direction(
    from_col: int, from_row: int, target_col: int, target_row: int, dx: int, dy: int
) -> bool:
    """Check if target is roughly in the specified direction (45-degree cone). Matches observation_builder._is_in_direction."""
    delta_col = target_col - from_col
    delta_row = target_row - from_row
    if dx == 0:  # North/South
        return abs(delta_col) <= abs(delta_row) and (delta_row * dy > 0)
    if dy == 0:  # East/West
        return abs(delta_row) <= abs(delta_col) and (delta_col * dx > 0)
    # Diagonal
    return (delta_col * dx > 0) and (delta_row * dy > 0)


def _hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Hex distance (cube coords). Matches combat_utils.calculate_hex_distance."""
    z1 = row1 - ((col1 - (col1 & 1)) >> 1)
    z2 = row2 - ((col2 - (col2 & 1)) >> 1)
    y1 = -col1 - z1
    y2 = -col2 - z2
    return max(abs(col1 - col2), abs(y1 - y2), abs(z1 - z2))


def _get_hex_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """Hex neighbors (offset coords). Matches combat_utils.get_hex_neighbors."""
    parity = col & 1
    if parity == 0:
        return [
            (col, row - 1), (col + 1, row - 1), (col + 1, row),
            (col, row + 1), (col - 1, row), (col - 1, row - 1),
        ]
    return [
        (col, row - 1), (col + 1, row), (col + 1, row + 1),
        (col, row + 1), (col - 1, row + 1), (col - 1, row),
    ]


_MAX_PATHFINDING = 51  # max_search_distance+1 for unreachable, fits uint8


def _compute_pathfinding_distance(
    from_col: int, from_row: int, to_col: int, to_row: int,
    wall_set: Set[Tuple[int, int]], cols: int, rows: int,
) -> int:
    """BFS pathfinding distance. Matches combat_utils.calculate_pathfinding_distance."""
    if from_col == to_col and from_row == to_row:
        return 0
    start = (from_col, from_row)
    end = (to_col, to_row)
    visited: dict = {start: 0}
    queue: list = [(start, 0)]
    while queue:
        pos, dist = queue.pop(0)
        if pos == end:
            return dist
        if dist >= _MAX_PATHFINDING - 1:
            continue
        for nc, nr in _get_hex_neighbors(pos[0], pos[1]):
            if nc < 0 or nr < 0 or nc >= cols or nr >= rows:
                continue
            npos = (nc, nr)
            if npos in visited or npos in wall_set:
                continue
            visited[npos] = dist + 1
            queue.append((npos, dist + 1))
    return _MAX_PATHFINDING - 1


def _compute_edge_dist(col: int, row: int, dx: int, dy: int, cols: int, rows: int) -> float:
    """Distance to board edge in direction (dx, dy). Matches observation_builder._find_edge_distance."""
    if dx > 0:
        edge_dist = cols - col - 1
    elif dx < 0:
        edge_dist = float(col)
    else:
        edge_dist = _PERCEPTION_RADIUS
    if dy > 0:
        edge_dist = min(edge_dist, rows - row - 1)
    elif dy < 0:
        edge_dist = min(edge_dist, float(row))
    return edge_dist


def _build_wall_edge_topology(
    cols: int, rows: int, wall_hexes: Set[Tuple[int, int]]
) -> np.ndarray:
    """
    Build wall and edge distance topology per hex per direction.
    Shape: (cols*rows, 8, 2) where [hex_idx, dir_idx, 0]=wall_dist, [hex_idx, dir_idx, 1]=edge_dist.
    """
    n = cols * rows
    arr = np.zeros((n, 8, 2), dtype=np.float32)
    valid_walls = {(c, r) for c, r in wall_hexes if 0 <= c < cols and 0 <= r < rows}

    total = n * 8
    done = 0
    start_time = time.time()
    last_update_pct = -1.0

    for row in range(rows):
        for col in range(cols):
            hex_idx = row * cols + col
            for dir_idx, (dx, dy) in enumerate(_DIRECTIONS):
                # Wall distance: nearest wall in direction
                min_wall_dist = _PERCEPTION_RADIUS
                for wc, wr in valid_walls:
                    if _is_in_direction(col, row, wc, wr, dx, dy):
                        d = _hex_distance(col, row, wc, wr)
                        if d < min_wall_dist:
                            min_wall_dist = float(d)
                arr[hex_idx, dir_idx, 0] = min_wall_dist

                # Edge distance
                arr[hex_idx, dir_idx, 1] = _compute_edge_dist(col, row, dx, dy, cols, rows)

                done += 1

            pct = (done / total) * 100
            if pct - last_update_pct >= 1.0 or done == total:
                last_update_pct = pct
                _print_progress(done, total, start_time, "wall/edge")

    print()
    return arr


def _build_full_topology(
    cols: int, rows: int, wall_hexes: Set[Tuple[int, int]]
) -> np.ndarray:
    """
    Build full topology: LoS + pathfinding. Shape (n, n, 2).
    [:, :, 0] = visibility_ratio (float16), [:, :, 1] = pathfinding_distance (uint8).
    """
    n = cols * rows
    valid_walls = {(c, r) for c, r in wall_hexes if 0 <= c < cols and 0 <= r < rows}

    # Combined array: visibility (float16) + pathfinding (uint8)
    arr = np.zeros((n, n, 2), dtype=np.float32)  # build as float32, cast at end
    total_pairs = n * n
    done = 0
    start_time = time.time()
    last_update_pct = -1.0

    for from_row in range(rows):
        for from_col in range(cols):
            from_idx = from_row * cols + from_col
            for to_row in range(rows):
                for to_col in range(cols):
                    to_idx = to_row * cols + to_col
                    if from_idx == to_idx:
                        arr[from_idx, to_idx, 0] = 1.0
                        arr[from_idx, to_idx, 1] = 0
                        done += 1
                        continue
                    arr[from_idx, to_idx, 0] = _compute_visibility_ratio(
                        from_col, from_row, to_col, to_row, valid_walls
                    )
                    arr[from_idx, to_idx, 1] = _compute_pathfinding_distance(
                        from_col, from_row, to_col, to_row, valid_walls, cols, rows
                    )
                    done += 1

            pct = (done / total_pairs) * 100
            if pct - last_update_pct >= 1.0 or done == total_pairs:
                last_update_pct = pct
                _print_progress(done, total_pairs, start_time, "pairs")

    print()
    # Both channels as float16 (pathfinding 0-51 fits; visibility 0-1)
    out = np.empty((n, n, 2), dtype=np.float16)
    out[:, :, 0] = arr[:, :, 0].astype(np.float16)
    out[:, :, 1] = np.clip(arr[:, :, 1], 0, 255).astype(np.float16)
    return out


def _find_wall_files(board_dir: Path, fallback_walls_dir: Path) -> List[Tuple[Path, str]]:
    """Find walls-XX.json files. Returns [(path, XX), ...]."""
    results: List[Tuple[Path, str]] = []
    for candidate in [board_dir, fallback_walls_dir]:
        if not candidate.exists():
            continue
        for p in sorted(candidate.glob("walls-*.json")):
            stem = p.stem  # walls-01
            if stem.startswith("walls-"):
                suffix = stem[6:]  # 01
                if suffix.isdigit():
                    results.append((p, suffix))
    # Deduplicate by suffix (prefer board_dir)
    seen: set[str] = set()
    unique: List[Tuple[Path, str]] = []
    for path, suffix in results:
        if suffix not in seen:
            seen.add(suffix)
            unique.append((path, suffix))
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LoS topology cache for a board")
    parser.add_argument(
        "dimensions",
        nargs="?",
        help="Board dimensions as COLSxROWS (e.g. 25x21)",
    )
    parser.add_argument("--cols", type=int, help="Board columns")
    parser.add_argument("--rows", type=int, help="Board rows")
    args = parser.parse_args()

    if args.dimensions:
        cols, rows = _parse_dimensions(args.dimensions)
    elif args.cols is not None and args.rows is not None:
        cols, rows = args.cols, args.rows
    else:
        parser.error("Provide dimensions as COLSxROWS or --cols and --rows")
        return 1

    config_dir = _PROJECT_ROOT / "config"
    board_dir = config_dir / "board" / f"{cols}x{rows}"
    fallback_walls = config_dir / "agents" / "_walls"

    wall_files = _find_wall_files(board_dir, fallback_walls)
    if not wall_files:
        print(
            f"No walls-*.json found in {board_dir} or {fallback_walls}",
            file=sys.stderr,
        )
        return 1

    board_dir.mkdir(parents=True, exist_ok=True)

    for wall_path, wall_id in wall_files:
        print(f"Building topology for {cols}x{rows} + {wall_path.name}...")
        terrain_walls = _load_wall_hexes(wall_path)
        wall_hexes = _add_board_boundary_hexes(terrain_walls, cols, rows)
        print(f"  Terrain walls: {len(terrain_walls)}, + boundary: {len(wall_hexes)} total")

        # Single topology file: LoS + pathfinding + wall_edge
        full = _build_full_topology(cols, rows, wall_hexes)
        wall_edge = _build_wall_edge_topology(cols, rows, wall_hexes)
        out_name = f"topology_{cols}x{rows}-{wall_id}.npz"
        out_path = board_dir / out_name
        np.savez(
            out_path,
            los=full[:, :, 0].astype(np.float16),
            pathfinding=full[:, :, 1].astype(np.float16),
            wall_edge=wall_edge,
        )
        size_kb = out_path.stat().st_size / 1024
        print(f"  Saved {out_path} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
