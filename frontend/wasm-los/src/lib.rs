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

/// Inline LoS check: traces hex line from→to, returns false if any intermediate hex is a wall.
/// Zero allocations.
#[inline]
fn has_los_fast(
    from_col: i32, from_row: i32,
    to_col: i32, to_row: i32,
    wall_grid: &[bool], rows: i32, grid_len: usize,
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

    // Only check intermediate hexes (i=1..n-1), skip source and target
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
    }
    true
}

/// Compute visible hexes from a shooter position within a given range.
/// Returns a flat array: [col0, row0, state0, col1, row1, state1, ...]
/// state: 1 = visible (clear), 2 = visible (cover)
#[wasm_bindgen]
pub fn compute_visible_hexes(
    shooter_col: i32,
    shooter_row: i32,
    max_range: i32,
    board_cols: i32,
    board_rows: i32,
    wall_data: &[i32],
    _los_visibility_min_ratio: f64,
    _cover_ratio: f64,
) -> Vec<i32> {
    let wall_grid = build_wall_grid(wall_data, board_cols, board_rows);
    let grid_len = wall_grid.len();

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
            if has_los_fast(shooter_col, shooter_row, col, row, &wall_grid, board_rows, grid_len) {
                result.push(col);
                result.push(row);
                result.push(1); // clear (cover detection requires multi-path, keeping simple for now)
            }
        }
    }

    result
}

/// Single-pair LoS check. Returns: 0 = blocked, 1 = visible clear, 2 = visible cover.
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
    if has_los_fast(from_col, from_row, to_col, to_row, &wall_grid, board_rows, grid_len) {
        1
    } else {
        0
    }
}

/// Hex distance between two positions.
#[wasm_bindgen]
pub fn wasm_hex_distance(col1: i32, row1: i32, col2: i32, row2: i32) -> i32 {
    let (x1, y1, z1) = offset_to_cube(col1, row1);
    let (x2, y2, z2) = offset_to_cube(col2, row2);
    hex_distance_cube(x1, y1, z1, x2, y2, z2)
}
