/**
 * Adoucit un contour polygonal fermé (liste plate [x0,y0,x1,y1,…]) pour le rendu
 * Pixi — réduit l’aspect « crénelé » des unions d’hex sans changer la logique métier.
 *
 * Algorithme de Chaikin (corner cutting) : 2 passes donnent un bord nettement plus doux
 * sur les unions d’hex (la 1ʳᵉ seule laisse encore des angles marqués).
 */

/** Plafond par défaut : si le prochain sous-division dépasserait ce nombre de sommets, on s’arrête. */
export const DEFAULT_MAX_VERTS_AFTER_ONE_CHAIKIN_STEP = 48_000;

/**
 * @param flat Coordonnées monde, polygone fermé (pas besoin de dupliquer le premier point en fin).
 * @param iterations Nombre de passes Chaikin (1 = léger, 2 = bien arrondi sur gros contours).
 * @param maxVertsAfterOneChaikinStep Plafond de sommets (après une subdivision) avant d’arrêter les passes suivantes.
 */
export function chaikinSmoothClosedPolygonFlat(
  flat: number[],
  iterations: number,
  maxVertsAfterOneChaikinStep: number = DEFAULT_MAX_VERTS_AFTER_ONE_CHAIKIN_STEP,
): number[] {
  if (flat.length < 6 || iterations <= 0) {
    return flat;
  }
  let cur = flat;

  for (let it = 0; it < iterations; it++) {
    const m = cur.length / 2;
    if (m < 3) {
      break;
    }
    if (it > 0 && m * 2 > maxVertsAfterOneChaikinStep) {
      break;
    }
    const next: number[] = [];
    next.length = m * 4;
    let w = 0;
    for (let i = 0; i < m; i++) {
      const i0 = i * 2;
      const i1 = ((i + 1) % m) * 2;
      const p0x = cur[i0]!;
      const p0y = cur[i0 + 1]!;
      const p1x = cur[i1]!;
      const p1y = cur[i1 + 1]!;
      next[w++] = 0.75 * p0x + 0.25 * p1x;
      next[w++] = 0.75 * p0y + 0.25 * p1y;
      next[w++] = 0.25 * p0x + 0.75 * p1x;
      next[w++] = 0.25 * p0y + 0.75 * p1y;
    }
    cur = next;
  }

  return cur;
}

/** AABB monde couvrant toutes les boucles (listes plates [x,y,…]). */
export function computeBoundsFromFlatPolygonLoops(loops: number[][]): {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
} {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const flat of loops) {
    for (let i = 0; i < flat.length; i += 2) {
      const vx = flat[i]!;
      const vy = flat[i + 1]!;
      if (vx < minX) minX = vx;
      if (vx > maxX) maxX = vx;
      if (vy < minY) minY = vy;
      if (vy > maxY) maxY = vy;
    }
  }
  return { minX, minY, maxX, maxY };
}

export type SmoothMaskLoopsForRenderOptions = {
  /** Défaut ``DEFAULT_MAX_VERTS_AFTER_ONE_CHAIKIN_STEP`` ; augmenter pour les gros contours move/advance. */
  maxVertsAfterOneChaikinStep?: number;
};

/**
 * Une passe Chaikin par boucle puis AABB — à utiliser pour le masque Pixi : les bornes doivent suivre
 * le contour **lissé**, sinon le rendu peut rogner les bords ; on évite aussi d’appeler Chaikin deux fois.
 */
export function smoothMaskLoopsForRender(
  loops: number[][],
  chaikinIterations: number,
  options?: SmoothMaskLoopsForRenderOptions,
): {
  smoothed: number[][];
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
} {
  const cap = options?.maxVertsAfterOneChaikinStep ?? DEFAULT_MAX_VERTS_AFTER_ONE_CHAIKIN_STEP;
  const smoothed =
    chaikinIterations > 0
      ? loops.map((loop) => chaikinSmoothClosedPolygonFlat(loop, chaikinIterations, cap))
      : loops;
  const b = computeBoundsFromFlatPolygonLoops(smoothed);
  return { smoothed, ...b };
}
