/**
 * Hex footprint utilities for Board ×10 micro-grid.
 *
 * Port of engine/hex_utils.py footprint functions to TypeScript.
 * Used for drag-and-drop placement preview (ghost unit + validation).
 */

// --- Internal hex geometry (offset odd-q, flat-top — same centers as hexToPixel, R=1) ---

function hexCenter(col: number, row: number): [number, number] {
  const hexRadius = 1.0;
  const hexWidth = 1.5 * hexRadius;
  const hexHeight = Math.sqrt(3) * hexRadius;
  const x = col * hexWidth + hexWidth / 2;
  const y =
    row * hexHeight + ((col % 2) * hexHeight) / 2 + hexHeight / 2;
  return [x, y];
}

/** Same as engine/hex_utils._FOOTPRINT_SIZE_SCALE — legacy diameter vs flat-top center units. */
const FOOTPRINT_SIZE_SCALE = 1.5;

// --- Footprint computation ---

function footprintRound(
  centerCol: number,
  centerRow: number,
  diameter: number,
): Set<string> {
  const radius = (diameter / 2.0) * FOOTPRINT_SIZE_SCALE;
  const radiusSq = radius ** 2;
  const [cx, cy] = hexCenter(centerCol, centerRow);
  const scanR = Math.ceil(diameter / 2.0) + 2;
  const result = new Set<string>();
  for (let dc = -scanR; dc <= scanR; dc++) {
    for (let dr = -scanR; dr <= scanR; dr++) {
      const c = centerCol + dc;
      const r = centerRow + dr;
      const [hx, hy] = hexCenter(c, r);
      const distSq = (hx - cx) ** 2 + (hy - cy) ** 2;
      if (distSq <= radiusSq) {
        result.add(`${c},${r}`);
      }
    }
  }
  return result;
}

export type HexCoord = [number, number];

/**
 * Compute the set of hex cells occupied by a unit's base.
 * Currently supports "round" shape only.
 */
export function computeOccupiedHexes(
  centerCol: number,
  centerRow: number,
  baseShape: string,
  baseSize: number,
): HexCoord[] {
  if (baseShape !== "round") {
    throw new Error(`Unsupported base_shape: ${baseShape} (only 'round' for now)`);
  }
  const keySet = footprintRound(centerCol, centerRow, baseSize);
  return Array.from(keySet).map((key) => {
    const [c, r] = key.split(",").map(Number);
    return [c, r] as HexCoord;
  });
}

// --- Pixel ↔ Hex conversion ---

/**
 * Convert hex grid coordinates to pixel coordinates.
 * Uses the same formula as BoardPvp.tsx rendering.
 */
export function hexToPixel(
  col: number,
  row: number,
  hexRadius: number,
  margin: number,
): { x: number; y: number } {
  const hexWidth = 1.5 * hexRadius;
  const hexHeight = Math.sqrt(3) * hexRadius;
  const x = col * hexWidth + hexWidth / 2 + margin;
  const y =
    row * hexHeight + ((col % 2) * hexHeight) / 2 + hexHeight / 2 + margin;
  return { x, y };
}

/**
 * Convert pixel coordinates back to the nearest hex grid (col, row).
 * Nearest-neighbor search over candidate hexes (same algorithm as BoardPvp).
 */
export function pixelToHex(
  px: number,
  py: number,
  hexRadius: number,
  margin: number,
  boardCols?: number,
  boardRows?: number,
): { col: number; row: number } {
  const hexWidth = 1.5 * hexRadius;
  const hexHeight = Math.sqrt(3) * hexRadius;
  const ux = px - margin;
  const uy = py - margin;

  const colApprox = (ux - hexWidth / 2) / hexWidth;
  const c0 = Math.max(0, Math.floor(colApprox) - 2);
  const c1 = boardCols != null
    ? Math.min(boardCols - 1, Math.ceil(colApprox) + 2)
    : Math.ceil(colApprox) + 2;

  let bestCol = 0;
  let bestRow = 0;
  let bestD = Number.POSITIVE_INFINITY;

  for (let c = c0; c <= c1; c++) {
    const stagger = ((c % 2) * hexHeight) / 2;
    const rowApprox = (uy - hexHeight / 2 - stagger) / hexHeight;
    const r0 = Math.max(0, Math.floor(rowApprox) - 2);
    const r1 = boardRows != null
      ? Math.min(boardRows - 1, Math.ceil(rowApprox) + 2)
      : Math.ceil(rowApprox) + 2;
    for (let r = r0; r <= r1; r++) {
      const cx = c * hexWidth + hexWidth / 2;
      const cy = r * hexHeight + stagger + hexHeight / 2;
      const d = (ux - cx) ** 2 + (uy - cy) ** 2;
      if (d < bestD) {
        bestD = d;
        bestCol = c;
        bestRow = r;
      }
    }
  }
  return { col: bestCol, row: bestRow };
}

// --- Validation helpers ---

/**
 * Check if all hexes in a footprint are within board bounds.
 */
export function isFootprintInBounds(
  hexes: HexCoord[],
  boardCols: number,
  boardRows: number,
): boolean {
  return hexes.every(
    ([c, r]) => c >= 0 && c < boardCols && r >= 0 && r < boardRows,
  );
}

/**
 * Check if any hex in a footprint overlaps a wall.
 */
export function isFootprintOnWall(
  hexes: HexCoord[],
  wallSet: Set<string>,
): boolean {
  return hexes.some(([c, r]) => wallSet.has(`${c},${r}`));
}

/**
 * Check if any hex in a footprint overlaps with occupied positions (other units).
 */
export function isFootprintOverlapping(
  hexes: HexCoord[],
  occupiedSet: Set<string>,
): boolean {
  return hexes.some(([c, r]) => occupiedSet.has(`${c},${r}`));
}

/**
 * Check if any hex in a footprint intersects a deployment pool.
 * Returns true if ALL hexes are in the pool (valid for deployment).
 */
export function isFootprintInDeployPool(
  hexes: HexCoord[],
  deployPool: Set<string>,
): boolean {
  return hexes.every(([c, r]) => deployPool.has(`${c},${r}`));
}

/**
 * Check if the footprint intersects any objective hex set.
 * Returns the IDs of objectives being contested.
 */
export function getContestedObjectives(
  hexes: HexCoord[],
  objectives: Array<{ id: number; hexes: HexCoord[] }>,
): number[] {
  const fpSet = new Set(hexes.map(([c, r]) => `${c},${r}`));
  return objectives
    .filter((obj) =>
      obj.hexes.some(([c, r]) => fpSet.has(`${c},${r}`)),
    )
    .map((obj) => obj.id);
}

/**
 * Build a set of occupied hex keys from units, excluding a specific unit.
 */
export function buildOccupiedSet(
  units: Array<{
    id: number;
    col: number;
    row: number;
    BASE_SHAPE?: string;
    BASE_SIZE?: number;
    alive?: boolean;
  }>,
  excludeId?: number,
): Set<string> {
  const set = new Set<string>();
  for (const u of units) {
    if (u.id === excludeId) continue;
    if (u.alive === false) continue;
    const shape = u.BASE_SHAPE ?? "round";
    const size = u.BASE_SIZE ?? 1;
    const hexes = computeOccupiedHexes(u.col, u.row, shape, size);
    for (const [c, r] of hexes) {
      set.add(`${c},${r}`);
    }
  }
  return set;
}
