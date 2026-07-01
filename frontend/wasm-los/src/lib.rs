use wasm_bindgen::prelude::*;

#[inline(always)]
fn offset_to_cube(col: i32, row: i32) -> (i32, i32, i32) {
    let x = col;
    let z = row - ((col - (col & 1)) >> 1);
    let y = -x - z;
    (x, y, z)
}

#[inline(always)]
fn cube_to_offset(x: i32, _y: i32, z: i32) -> (i32, i32) {
    let col = x;
    let row = z + ((x - (x & 1)) >> 1);
    (col, row)
}

#[inline(always)]
fn hex_distance_cube(sx: i32, sy: i32, sz: i32, tx: i32, ty: i32, tz: i32) -> i32 {
    (sx - tx).abs().max((sy - ty).abs()).max((sz - tz).abs())
}

#[inline(always)]
fn wall_grid_idx(col: i32, row: i32, rows: i32) -> usize {
    (col * rows + row) as usize
}

fn build_wall_grid(wall_data: &[i32], cols: i32, rows: i32) -> Vec<bool> {
    let size = (cols * rows) as usize;
    let mut grid = vec![false; size];
    let mut i = 0;
    while i + 1 < wall_data.len() {
        let c = wall_data[i];
        let r = wall_data[i + 1];
        if c >= 0 && c < cols && r >= 0 && r < rows {
            grid[wall_grid_idx(c, r, rows)] = true;
        }
        i += 2;
    }
    grid
}

/// Per-hex obscuring area id (0 = not obscuring). Input: flat triplets [col,row,areaId,...], areaId >= 1.
/// Mirror of `_get_obscuring_hex_to_area` in shooting_handlers.py.
fn build_obscuring_grid(obscuring_data: &[i32], cols: i32, rows: i32) -> Vec<i32> {
    let size = (cols * rows) as usize;
    let mut grid = vec![0i32; size];
    let mut i = 0;
    while i + 2 < obscuring_data.len() {
        let c = obscuring_data[i];
        let r = obscuring_data[i + 1];
        let a = obscuring_data[i + 2];
        if c >= 0 && c < cols && r >= 0 && r < rows {
            grid[wall_grid_idx(c, r, rows)] = a;
        }
        i += 3;
    }
    grid
}

/// Per-hex "belongs to any terrain area" (cover classification). Input: flat pairs [col,row,...].
/// Mirror of `terrain_hex_set` in `_update_unit_los_preview_data`.
fn build_terrain_grid(terrain_data: &[i32], cols: i32, rows: i32) -> Vec<bool> {
    let size = (cols * rows) as usize;
    let mut grid = vec![false; size];
    let mut i = 0;
    while i + 1 < terrain_data.len() {
        let c = terrain_data[i];
        let r = terrain_data[i + 1];
        if c >= 0 && c < cols && r >= 0 && r < rows {
            grid[wall_grid_idx(c, r, rows)] = true;
        }
        i += 2;
    }
    grid
}

/// Inline LoS check: traces hex line from→to (same cube-lerp as engine.hex_utils.hex_line).
/// Returns true if the sight line is clear. Blocked by a wall, or by an obscuring intermediate
/// hex whose area differs from the destination hex's area (rule 13.10). Shooter-occupied areas
/// must already be zeroed out of `obscuring_grid` by the caller. Pass an empty `obscuring_grid`
/// (dest_area = 0) for a walls-only check.
#[inline]
fn has_los_fast(
    from_col: i32, from_row: i32,
    to_col: i32, to_row: i32,
    wall_grid: &[bool],
    obscuring_grid: &[i32], dest_area: i32,
    rows: i32, grid_len: usize,
) -> bool {
    let (x1, y1, z1) = offset_to_cube(from_col, from_row);
    let (x2, y2, z2) = offset_to_cube(to_col, to_row);
    let n = hex_distance_cube(x1, y1, z1, x2, y2, z2);
    if n <= 1 {
        return true;
    }
    let nf = n as f64;
    let fx1 = x1 as f64 + 1e-6;
    let fy1 = y1 as f64 + 1e-6;
    let fz1 = z1 as f64 - 2e-6;
    let fx2 = x2 as f64 + 1e-6;
    let fy2 = y2 as f64 + 1e-6;
    let fz2 = z2 as f64 - 2e-6;

    for i in 1..n {
        let t = i as f64 / nf;
        let fx = fx1 + (fx2 - fx1) * t;
        let fy = fy1 + (fy2 - fy1) * t;
        let fz = fz1 + (fz2 - fz1) * t;

        let mut rx = fx.round() as i32;
        let mut ry = fy.round() as i32;
        let mut rz = fz.round() as i32;

        let dx = (rx as f64 - fx).abs();
        let dy = (ry as f64 - fy).abs();
        let dz = (rz as f64 - fz).abs();
        if dx > dy && dx > dz {
            rx = -ry - rz;
        } else if dy > dz {
            ry = -rx - rz;
        } else {
            rz = -rx - ry;
        }

        let (c, r) = cube_to_offset(rx, ry, rz);
        let idx = wall_grid_idx(c, r, rows);
        if idx < grid_len && wall_grid[idx] {
            return false;
        }
        if idx < obscuring_grid.len() {
            let area = obscuring_grid[idx];
            if area != 0 && area != dest_area {
                return false;
            }
        }
    }
    true
}

/// Compute visible hexes from a shooter position within a given range.
/// Returns a flat array: [col0, row0, state0, col1, row1, state1, ...]
/// state: 1 = clear (open), 2 = cover (hex inside a terrain area).
///
/// Faithful mirror of `_update_unit_los_preview_data` (shooting_handlers.py): anchor→hex sight
/// line, blocked by walls or by obscuring areas that neither the shooter nor the destination hex
/// occupies (rule 13.10). MUST be resynced if that backend function changes.
/// - `obscuring_data`: flat triplets [col,row,areaId,...] (areaId >= 1) for every obscuring hex.
/// - `terrain_data`: flat pairs [col,row,...] for every hex inside any terrain area (cover).
/// - `shooter_footprint`: flat pairs [col,row,...] of the shooter's occupied hexes; areas it
///   touches are excluded from blocking (a shooter inside/at the edge of its own terrain still sees out).
#[wasm_bindgen]
pub fn compute_visible_hexes(
    shooter_col: i32,
    shooter_row: i32,
    max_range: i32,
    board_cols: i32,
    board_rows: i32,
    wall_data: &[i32],
    obscuring_data: &[i32],
    terrain_data: &[i32],
    shooter_footprint: &[i32],
    _los_visibility_min_ratio: f64,
    _cover_ratio: f64,
) -> Vec<i32> {
    let wall_grid = build_wall_grid(wall_data, board_cols, board_rows);
    let grid_len = wall_grid.len();
    let mut obscuring_grid = build_obscuring_grid(obscuring_data, board_cols, board_rows);
    let terrain_grid = build_terrain_grid(terrain_data, board_cols, board_rows);

    // Rule 13.10: obscuring areas the shooter's footprint occupies never block for this shooter.
    // Collect those area ids, then zero them out of the grid so the sight-line test ignores them.
    let mut excluded: Vec<i32> = Vec::new();
    let push_excluded = |grid: &[i32], c: i32, r: i32, acc: &mut Vec<i32>| {
        if c >= 0 && c < board_cols && r >= 0 && r < board_rows {
            let a = grid[wall_grid_idx(c, r, board_rows)];
            if a != 0 && !acc.contains(&a) {
                acc.push(a);
            }
        }
    };
    push_excluded(&obscuring_grid, shooter_col, shooter_row, &mut excluded);
    let mut fi = 0;
    while fi + 1 < shooter_footprint.len() {
        push_excluded(
            &obscuring_grid,
            shooter_footprint[fi],
            shooter_footprint[fi + 1],
            &mut excluded,
        );
        fi += 2;
    }
    if !excluded.is_empty() {
        for v in obscuring_grid.iter_mut() {
            if *v != 0 && excluded.contains(v) {
                *v = 0;
            }
        }
    }

    let (sx, sy, sz) = offset_to_cube(shooter_col, shooter_row);

    let col_min = (shooter_col - max_range).max(0);
    let col_max = (shooter_col + max_range).min(board_cols - 1);
    let row_min = (shooter_row - max_range).max(0);
    let row_max = (shooter_row + max_range).min(board_rows - 1);

    let capacity = ((col_max - col_min + 1) * (row_max - row_min + 1)) as usize;
    let mut result = Vec::with_capacity(capacity * 3);

    for col in col_min..=col_max {
        for row in row_min..=row_max {
            let (tx, ty, tz) = offset_to_cube(col, row);
            let dist = hex_distance_cube(sx, sy, sz, tx, ty, tz);
            if dist <= 0 || dist > max_range {
                continue;
            }
            let idx = wall_grid_idx(col, row, board_rows);
            let dest_area = if idx < obscuring_grid.len() { obscuring_grid[idx] } else { 0 };
            if has_los_fast(
                shooter_col, shooter_row, col, row,
                &wall_grid, &obscuring_grid, dest_area,
                board_rows, grid_len,
            ) {
                let state = if idx < terrain_grid.len() && terrain_grid[idx] { 2 } else { 1 };
                result.push(col);
                result.push(row);
                result.push(state);
            }
        }
    }

    result
}

/// Single-pair LoS check. Returns: 0 = blocked, 1 = visible.
#[wasm_bindgen]
pub fn compute_los_single(
    from_col: i32, from_row: i32,
    to_col: i32, to_row: i32,
    wall_data: &[i32],
    _los_visibility_min_ratio: f64,
    _cover_ratio: f64,
) -> i32 {
    let board_cols = wall_data.iter().step_by(2).copied().max().unwrap_or(0) + 1;
    let board_rows = wall_data.iter().skip(1).step_by(2).copied().max().unwrap_or(0) + 1;
    let wall_grid = build_wall_grid(wall_data, board_cols, board_rows);
    let grid_len = wall_grid.len();
    if has_los_fast(from_col, from_row, to_col, to_row, &wall_grid, &[], 0, board_rows, grid_len) { 1 } else { 0 }
}

/// Hex distance between two positions.
#[wasm_bindgen]
pub fn wasm_hex_distance(col1: i32, row1: i32, col2: i32, row2: i32) -> i32 {
    let (x1, y1, z1) = offset_to_cube(col1, row1);
    let (x2, y2, z2) = offset_to_cube(col2, row2);
    hex_distance_cube(x1, y1, z1, x2, y2, z2)
}
