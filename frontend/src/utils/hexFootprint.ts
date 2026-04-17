/**
 * Hex footprint utilities for Board ×10 micro-grid.
 *
 * Port of engine/hex_utils.py footprint functions to TypeScript.
 * Used for drag-and-drop placement preview (ghost unit + validation).
 */

import { cubeDistance, offsetToCube } from "./gameHelpers";

// Voisins offset odd-q (engine/hex_utils.py)
const NEIGHBORS_EVEN_COL: readonly (readonly [number, number])[] = [
  [0, -1],
  [1, -1],
  [1, 0],
  [0, 1],
  [-1, 0],
  [-1, -1],
];
const NEIGHBORS_ODD_COL: readonly (readonly [number, number])[] = [
  [0, -1],
  [1, 0],
  [1, 1],
  [0, 1],
  [-1, 1],
  [-1, 0],
];

const SMALL_SET_BRUTE_FORCE = 64;

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

function resolveBaseSizeForFootprint(unit: { BASE_SIZE?: number | [number, number] }): number {
  const b = unit.BASE_SIZE;
  if (typeof b === "number" && Number.isFinite(b)) {
    return b;
  }
  if (Array.isArray(b) && b.length > 0 && typeof b[0] === "number") {
    return b[0];
  }
  return 1;
}

/**
 * Empreinte hex de l’unité (clés `"col,row"`), alignée sur computeOccupiedHexes.
 * Formes non rondes : repli sur le centre (col,row) uniquement.
 */
export function unitFootprintHexKeys(unit: {
  col: number;
  row: number;
  BASE_SHAPE?: string;
  BASE_SIZE?: number | [number, number];
}): Set<string> {
  const shape = unit.BASE_SHAPE ?? "round";
  if (shape !== "round") {
    return new Set<string>([`${unit.col},${unit.row}`]);
  }
  const size = resolveBaseSizeForFootprint(unit);
  const hexes = computeOccupiedHexes(unit.col, unit.row, shape, size);
  return new Set(hexes.map(([c, r]) => `${c},${r}`));
}

/**
 * Dilate l’empreinte sur le plateau (voisins 6 — même sémantique que engine.hex_utils.dilate_hex_set_unbounded,
 * mais hexes bornés au plateau pour l’affichage).
 */
export function dilateFootprintHexKeysOnBoard(
  fpKeys: Set<string>,
  radius: number,
  cols: number,
  rows: number,
): Set<string> {
  if (radius < 0) {
    throw new Error("dilateFootprintHexKeysOnBoard: radius must be non-negative");
  }
  if (fpKeys.size === 0) {
    return new Set();
  }
  const result = new Set<string>(fpKeys);
  let frontier: Array<[number, number]> = [];
  for (const k of fpKeys) {
    const [c, r] = k.split(",").map(Number);
    if (c >= 0 && c < cols && r >= 0 && r < rows) {
      frontier.push([c, r]);
    }
  }
  for (let layer = 0; layer < radius; layer++) {
    const next: Array<[number, number]> = [];
    for (const [c, r] of frontier) {
      const offsets = (c & 1) ? NEIGHBORS_ODD_COL : NEIGHBORS_EVEN_COL;
      for (const [dc, dr] of offsets) {
        const nc = c + dc;
        const nr = r + dr;
        if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) {
          continue;
        }
        const nk = `${nc},${nr}`;
        if (!result.has(nk)) {
          result.add(nk);
          next.push([nc, nr]);
        }
      }
    }
    frontier = next;
    if (frontier.length === 0) {
      break;
    }
  }
  return result;
}

/**
 * Anneau de preview d’engagement « rond » : même repère que `footprintRound` (distance euclidienne entre
 * centres d’hex), pas une dilatation 6-voisins (qui donne un contour polygonal / facetté).
 *
 * On colore les hex dont le centre est dans la couronne : hors empreinte (clés `fpKeys`), et à distance
 * ≤ r_footprint + engagementSteps × pas (pas ≈ largeur d’un hex en unités `hexCenter`, aligné sur la grille).
 */
/**
 * Centre et rayons en pixels plateau (échelle `boardHexRadius` / repère interne hexRadius=1).
 * Doit rester aligné sur {@link engagementRoundRingPreviewHexesOnBoard}.
 */
export function getFightEngagementRingBoardPixels(
  unit: {
    col: number;
    row: number;
    BASE_SHAPE?: string;
    BASE_SIZE?: number | [number, number];
  },
  engagementSteps: number,
  boardHexRadius: number,
  margin: number,
): { cx: number; cy: number; rInner: number; rOuter: number } {
  const [cxN, cyN] = hexCenter(unit.col, unit.row);
  const shape = unit.BASE_SHAPE ?? "round";
  const baseSize = shape === "round" ? resolveBaseSizeForFootprint(unit) : 1;
  const rFootprint = (baseSize / 2.0) * FOOTPRINT_SIZE_SCALE;
  const hexWidthNorm = 1.5;
  const rOuterN = rFootprint + engagementSteps * hexWidthNorm;
  const scale = boardHexRadius / 1.0;
  return {
    cx: cxN * scale + margin,
    cy: cyN * scale + margin,
    rInner: rFootprint * scale,
    rOuter: rOuterN * scale,
  };
}

export function engagementRoundRingPreviewHexesOnBoard(
  unit: {
    col: number;
    row: number;
    BASE_SHAPE?: string;
    BASE_SIZE?: number | [number, number];
  },
  engagementSteps: number,
  cols: number,
  rows: number,
): Array<{ col: number; row: number }> {
  const fpKeys = unitFootprintHexKeys(unit);
  const [cx, cy] = hexCenter(unit.col, unit.row);
  const shape = unit.BASE_SHAPE ?? "round";
  const baseSize = shape === "round" ? resolveBaseSizeForFootprint(unit) : 1;
  const rFootprint = (baseSize / 2.0) * FOOTPRINT_SIZE_SCALE;
  const hexRadius = 1.0;
  const hexWidth = 1.5 * hexRadius;
  const rOuter = rFootprint + engagementSteps * hexWidth;

  const scanR = Math.ceil(rOuter / hexWidth) + Math.ceil(baseSize / 2) + 6;
  const out: Array<{ col: number; row: number }> = [];
  for (let dc = -scanR; dc <= scanR; dc++) {
    for (let dr = -scanR; dr <= scanR; dr++) {
      const c = unit.col + dc;
      const r = unit.row + dr;
      if (c < 0 || c >= cols || r < 0 || r >= rows) {
        continue;
      }
      const k = `${c},${r}`;
      if (fpKeys.has(k)) {
        continue;
      }
      const [hx, hy] = hexCenter(c, r);
      const dist = Math.hypot(hx - cx, hy - cy);
      if (dist <= rOuter) {
        out.push({ col: c, row: r });
      }
    }
  }
  return out;
}

/**
 * Distance minimale en pas hex (grille 6-voisins, hors obstacles) entre deux empreintes.
 * Aligné sur engine.hex_utils.min_distance_between_sets (brute cube si petits ensembles, sinon BFS).
 */
export function minHexDistanceBetweenFootprintKeySets(
  setA: Set<string>,
  setB: Set<string>,
  maxDistance: number,
): number {
  if (setA.size === 0 || setB.size === 0) {
    throw new Error("minHexDistanceBetweenFootprintKeySets: empty footprint set");
  }
  for (const k of setA) {
    if (setB.has(k)) {
      return 0;
    }
  }
  if (setA.size <= SMALL_SET_BRUTE_FORCE && setB.size <= SMALL_SET_BRUTE_FORCE) {
    let best = Infinity;
    for (const ka of setA) {
      const [c1, r1] = ka.split(",").map(Number);
      const cu1 = offsetToCube(c1, r1);
      for (const kb of setB) {
        const [c2, r2] = kb.split(",").map(Number);
        const d = cubeDistance(cu1, offsetToCube(c2, r2));
        if (d < best) {
          best = d;
        }
        if (best === 1) {
          return 1;
        }
      }
    }
    return best === Infinity ? maxDistance + 1 : best;
  }

  let a = setA;
  let b = setB;
  if (a.size > b.size) {
    [a, b] = [b, a];
  }

  const visited = new Set<string>(a);
  let frontier: Array<[number, number]> = [];
  for (const k of a) {
    const [c, r] = k.split(",").map(Number);
    frontier.push([c, r]);
  }

  let dist = 0;
  while (frontier.length) {
    dist += 1;
    if (dist > maxDistance) {
      return maxDistance + 1;
    }
    const next: Array<[number, number]> = [];
    for (const [c, r] of frontier) {
      const offsets = (c & 1) ? NEIGHBORS_ODD_COL : NEIGHBORS_EVEN_COL;
      for (const [dc, dr] of offsets) {
        const nc = c + dc;
        const nr = r + dr;
        const nk = `${nc},${nr}`;
        if (b.has(nk)) {
          return dist;
        }
        if (!visited.has(nk)) {
          visited.add(nk);
          next.push([nc, nr]);
        }
      }
    }
    frontier = next;
  }
  return maxDistance + 1;
}

/** Unité source pour {@link minHexDistanceBetweenUnitFootprints}. */
export type UnitFootprintInput = {
  col: number;
  row: number;
  BASE_SHAPE?: string;
  BASE_SIZE?: number | [number, number];
};

/**
 * Distance minimale entre deux empreintes en **pas de grille** (voisins 6), plafonnée par `maxDistance`.
 * Sur plateau Board×10, un pas = un sous-hex ; comparer au budget `jet 2D6 × inches_to_subhex`.
 * Un résultat &gt; `maxDistance` indique une distance strictement supérieure (hors fenêtre de recherche).
 */
export function minHexDistanceBetweenUnitFootprints(
  charger: UnitFootprintInput,
  target: UnitFootprintInput,
  maxDistance: number,
): number {
  const setA = unitFootprintHexKeys(charger);
  const setB = unitFootprintHexKeys(target);
  return minHexDistanceBetweenFootprintKeySets(setA, setB, maxDistance);
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
