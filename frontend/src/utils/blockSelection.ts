// frontend/src/utils/blockSelection.ts
//
// Sélection rectangle + bloc partiel de figurines (move / charge). Logique PURE, partagée par
// useEngineAPI (pool + snap) et BoardPvp (hit-test socle/rectangle) — testée dans
// blockSelection.test.ts. Le pool d'ancres vient TOUJOURS du moteur (move_block_destinations /
// charge_block_destinations) : ce module ne juge aucune légalité, il ne fait que parser, snapper
// et tester des rectangles.

import { cubeDistance, offsetToCube } from "./gameHelpers";

export type Cube = { x: number; y: number; z: number };

/** Destination (col, row, level) de chaque figurine du bloc pour une ancre donnée. */
export type BlockPlacements = Record<string, [number, number, number]>;

/** Pool d'ancres du bloc : clé ``"col,row"`` de l'ancre → placements. */
export type BlockPool = Map<string, BlockPlacements>;

function cubeKey(col: number, row: number): string {
  return `${col},${row}`;
}

/**
 * Parse la réponse moteur ``destinations: [[anchorCol, anchorRow, [[mid, col, row, level], …]], …]``.
 * Toute entrée malformée lève : un pool partiellement lu poserait des figurines hors moteur.
 */
export function parseBlockDestinations(raw: unknown): BlockPool {
  if (!Array.isArray(raw)) {
    throw new Error("block destinations: 'destinations' absent ou non-liste");
  }
  const pool: BlockPool = new Map();
  for (const entry of raw) {
    if (!Array.isArray(entry) || entry.length !== 3 || !Array.isArray(entry[2])) {
      throw new Error(`block destinations: entrée d'ancre malformée ${JSON.stringify(entry)}`);
    }
    const ac = Number(entry[0]);
    const ar = Number(entry[1]);
    if (!Number.isInteger(ac) || !Number.isInteger(ar)) {
      throw new Error(`block destinations: ancre non entière ${JSON.stringify(entry)}`);
    }
    const placements: BlockPlacements = {};
    for (const p of entry[2] as unknown[]) {
      if (!Array.isArray(p) || p.length !== 4) {
        throw new Error(`block destinations: placement malformé ${JSON.stringify(p)}`);
      }
      const [mid, c, r, lv] = p as [unknown, unknown, unknown, unknown];
      const col = Number(c);
      const row = Number(r);
      const level = Number(lv);
      if (
        typeof mid !== "string" ||
        !Number.isInteger(col) ||
        !Number.isInteger(row) ||
        !Number.isInteger(level)
      ) {
        throw new Error(`block destinations: placement non entier ${JSON.stringify(p)}`);
      }
      placements[mid] = [col, row, level];
    }
    pool.set(cubeKey(ac, ar), placements);
  }
  return pool;
}

/** Vecteur cube ``a − b``. */
export function cubeSub(a: Cube, b: Cube): Cube {
  return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
}

/** Vecteur cube ``a + b``. */
export function cubeAdd(a: Cube, b: Cube): Cube {
  return { x: a.x + b.x, y: a.y + b.y, z: a.z + b.z };
}

/**
 * Ancre du pool la plus proche (distance cube) de l'ancre VOULUE — miroir du snap du
 * déploiement en mode suivi. ``null`` sur pool vide. Égalité de distance → première clé du pool
 * (ordre d'insertion = ordre moteur), déterministe.
 */
export function snapBlockAnchor(pool: BlockPool, desired: Cube): string | null {
  let bestKey: string | null = null;
  let bestD = Number.POSITIVE_INFINITY;
  for (const key of pool.keys()) {
    const sep = key.indexOf(",");
    const c = Number(key.slice(0, sep));
    const r = Number(key.slice(sep + 1));
    const d = cubeDistance(desired, offsetToCube(c, r));
    if (d < bestD) {
      bestD = d;
      bestKey = key;
      if (d === 0) break;
    }
  }
  return bestKey;
}

export type PixelRect = { x0: number; y0: number; x1: number; y1: number };

/** Rectangle normalisé (coins dans n'importe quel ordre → x0 ≤ x1, y0 ≤ y1). */
export function normalizeRect(ax: number, ay: number, bx: number, by: number): PixelRect {
  return {
    x0: Math.min(ax, bx),
    y0: Math.min(ay, by),
    x1: Math.max(ax, bx),
    y1: Math.max(ay, by),
  };
}

/**
 * Le disque (socle) de centre ``(cx, cy)`` et rayon ``r`` touche-t-il le rectangle (tout ou
 * partie dedans) ? Test exact disque/rectangle axé : distance du centre au point le plus proche du
 * rectangle ≤ rayon. Tangence comptée comme contact.
 */
export function circleTouchesRect(rect: PixelRect, cx: number, cy: number, r: number): boolean {
  const nx = Math.max(rect.x0, Math.min(cx, rect.x1));
  const ny = Math.max(rect.y0, Math.min(cy, rect.y1));
  const dx = cx - nx;
  const dy = cy - ny;
  return dx * dx + dy * dy <= r * r;
}

export type SelectableModel = { modelId: string; cx: number; cy: number; radius: number };

/** Figurines dont le socle touche le rectangle, dans l'ordre donné (ordre d'escouade). */
export function modelsTouchingRect(models: SelectableModel[], rect: PixelRect): string[] {
  return models.filter((m) => circleTouchesRect(rect, m.cx, m.cy, m.radius)).map((m) => m.modelId);
}

/**
 * Sélection effective du rectangle : socles touchés ET une seule escouade. Un rectangle à cheval
 * sur deux escouades ne sélectionne RIEN (le bloc appartient à l'escouade activée) — même règle
 * pour le voile vert en direct et pour la sélection au relâchement.
 */
export function selectBlockInRect(
  candidates: Array<SelectableModel & { unitId: number }>,
  rect: PixelRect
): string[] {
  const ids = new Set(modelsTouchingRect(candidates, rect));
  const hit = candidates.filter((m) => ids.has(m.modelId));
  const squads = new Set(hit.map((m) => m.unitId));
  return squads.size === 1 ? hit.map((m) => m.modelId) : [];
}
