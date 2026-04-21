/**
 * Contour de l’union d’hex (flat-top, même géométrie que BoardDisplay) pour masques Pixi.
 * Arêtes internes ×2 → annulées ; bord ×1 → boucle(s) fermée(s).
 */

export type HexUnionMaskLayout = {
  HEX_HORIZ_SPACING: number;
  HEX_WIDTH: number;
  HEX_HEIGHT: number;
  HEX_VERT_SPACING: number;
  MARGIN: number;
  gridHexRadius: number;
};

/** Aligné sur la précision typique du rendu Pixi ; évite les doubles arêtes sur hex voisins (float). */
const Q = 1e4;

function q(n: number): number {
  return Math.round(n * Q) / Q;
}

function vertexKey(x: number, y: number): string {
  return `${q(x)},${q(y)}`;
}

function canonicalEdgeKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

/** Centre hex identique à BoardDisplay / fillFootprintPoolCircles. */
function hexCenterWorld(
  col: number,
  row: number,
  layout: HexUnionMaskLayout,
): [number, number] {
  const { HEX_HORIZ_SPACING, HEX_WIDTH, HEX_HEIGHT, HEX_VERT_SPACING, MARGIN } = layout;
  const hx = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
  const hy =
    row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
  return [hx, hy];
}

/** 6 sommets (flat-top), même ordre que le masque historique (vi * π/3). */
function hexCornerWorld(
  col: number,
  row: number,
  layout: HexUnionMaskLayout,
): Array<[number, number]> {
  const [hx, hy] = hexCenterWorld(col, row, layout);
  const R = layout.gridHexRadius;
  const out: Array<[number, number]> = [];
  for (let vi = 0; vi < 6; vi++) {
    const ang = (vi * Math.PI) / 3;
    out.push([hx + R * Math.cos(ang), hy + R * Math.sin(ang)]);
  }
  return out;
}

function parseHexKey(key: string): [number, number] | null {
  const sep = key.indexOf(",");
  if (sep <= 0) return null;
  const c = Number(key.substring(0, sep));
  const r = Number(key.substring(sep + 1));
  if (!Number.isFinite(c) || !Number.isFinite(r)) return null;
  return [c, r];
}

export type HexUnionMaskPolygonResult = {
  /** Une ou plusieurs boucles ; chaque boucle est [x0,y0,x1,y1,…] (fermée implicitement). */
  loops: number[][];
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

/**
 * Construit le remplissage du masque comme union de polygones de bord (O(arêtes)).
 * Retourne `null` si la topologie n’est pas un 2-régulier fiable (repli chunk hex).
 */
export function tryBuildHexUnionMaskPolygons(
  hexKeys: Set<string>,
  layout: HexUnionMaskLayout,
): HexUnionMaskPolygonResult | null {
  if (hexKeys.size === 0) return null;

  const edgeCount = new Map<string, number>();

  for (const key of hexKeys) {
    const parsed = parseHexKey(key);
    if (parsed === null) return null;
    const [col, row] = parsed;
    const corners = hexCornerWorld(col, row, layout);
    for (let i = 0; i < 6; i++) {
      const [x0, y0] = corners[i]!;
      const [x1, y1] = corners[(i + 1) % 6]!;
      const k0 = vertexKey(x0, y0);
      const k1 = vertexKey(x1, y1);
      const ek = canonicalEdgeKey(k0, k1);
      edgeCount.set(ek, (edgeCount.get(ek) ?? 0) + 1);
    }
  }

  const boundaryEdges: Array<[string, string]> = [];
  for (const [ek, c] of edgeCount) {
    if (c === 1) {
      const sep = ek.indexOf("|");
      if (sep <= 0) return null;
      boundaryEdges.push([ek.slice(0, sep), ek.slice(sep + 1)]);
    } else if (c !== 2) {
      return null;
    }
  }

  if (boundaryEdges.length === 0) return null;

  const pos = new Map<string, [number, number]>();
  for (const [ka, kb] of boundaryEdges) {
    const [ax, ay] = ka.split(",").map(Number);
    const [bx, by] = kb.split(",").map(Number);
    if (![ax, ay, bx, by].every((n) => Number.isFinite(n))) return null;
    pos.set(ka, [ax, ay]);
    pos.set(kb, [bx, by]);
  }

  const adj = new Map<string, string[]>();
  const addAdj = (a: string, b: string) => {
    let la = adj.get(a);
    if (!la) {
      la = [];
      adj.set(a, la);
    }
    la.push(b);
  };
  for (const [ka, kb] of boundaryEdges) {
    addAdj(ka, kb);
    addAdj(kb, ka);
  }

  // Tous les vertices doivent avoir un degré **pair** (Handshake lemma appliqué aux
  // boundary edges dans un graphe planaire : chaque face ferme ses edges). Les
  // vertices à 4 (ou 6) voisins correspondent à des **coins partagés** entre deux
  // sous-blobs du pool qui ne se touchent que par un seul sommet — cas fréquent
  // sur les BFS tronqués par des murs. On va disambiguïser via tri angulaire
  // des voisins (« turn right » en coordonnées écran Y-bas = continuation du
  // contour externe cohérent).
  for (const [, peers] of adj) {
    if (peers.length < 2 || peers.length % 2 !== 0) return null;
  }

  /**
   * Au vertex ``curr``, venant de ``prev``, choisit le voisin suivant cohérent
   * avec une traversée de contour planaire (« turn right » à l'écran).
   *
   * - Si degré === 2 : trivial (le seul voisin ≠ prev).
   * - Si degré > 2 : parmi les voisins ≠ prev **encore disponibles** (dirigé
   *   ``curr→p`` non encore consommé), on prend celui qui minimise l'angle
   *   signé ``angle(curr→p) - angle(curr→prev)`` dans [-π, π] — le plus négatif
   *   = virage le plus à droite à l'écran.
   */
  const pickNextNeighbor = (
    curr: string,
    prev: string,
    directedUsed: Set<string>,
  ): string | null => {
    const peers = adj.get(curr);
    if (!peers || peers.length === 0) return null;
    const [cx, cy] = pos.get(curr)!;
    const [px, py] = pos.get(prev)!;
    const angleIn = Math.atan2(py - cy, px - cx);
    let best: string | null = null;
    let bestTurn = Infinity;
    for (const p of peers) {
      if (directedUsed.has(`${curr}>${p}`)) continue;
      if (p === prev && peers.length > 2) continue;
      const [nx, ny] = pos.get(p)!;
      const angleOut = Math.atan2(ny - cy, nx - cx);
      let turn = angleOut - angleIn;
      while (turn > Math.PI) turn -= 2 * Math.PI;
      while (turn <= -Math.PI) turn += 2 * Math.PI;
      if (turn < bestTurn) {
        bestTurn = turn;
        best = p;
      }
    }
    if (best === null && peers.length === 2) {
      best = peers[0] === prev ? peers[1]! : peers[0]!;
    }
    return best;
  };

  const undirectedRemaining = new Set<string>();
  for (const [ka, kb] of boundaryEdges) {
    undirectedRemaining.add(canonicalEdgeKey(ka, kb));
  }

  const loops: number[][] = [];

  while (undirectedRemaining.size > 0) {
    const pick = undirectedRemaining.values().next().value;
    if (pick === undefined) break;
    const sep = pick.indexOf("|");
    if (sep <= 0) return null;
    const ka = pick.slice(0, sep);
    const kb = pick.slice(sep + 1);
    if (!adj.get(ka)?.includes(kb)) return null;

    const start = ka;
    let prev = ka;
    let curr = kb;
    const ringKeys: string[] = [start];

    const directedUsed = new Set<string>();
    const consume = (a: string, b: string) => {
      directedUsed.add(`${a}>${b}`);
      directedUsed.add(`${b}>${a}`);
      undirectedRemaining.delete(canonicalEdgeKey(a, b));
    };
    consume(prev, curr);

    let guard = 0;
    const maxGuard = boundaryEdges.length * 4 + 64;

    while (curr !== start) {
      guard++;
      if (guard > maxGuard) return null;

      ringKeys.push(curr);
      const next = pickNextNeighbor(curr, prev, directedUsed);
      if (next === null) return null;
      consume(curr, next);
      prev = curr;
      curr = next;
    }

    if (ringKeys.length < 3) {
      continue;
    }

    const flat: number[] = [];
    for (const vk of ringKeys) {
      const p = pos.get(vk);
      if (!p) return null;
      const [x, y] = p;
      flat.push(x, y);
    }
    loops.push(flat);
  }

  if (loops.length === 0) return null;

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const loop of loops) {
    for (let i = 0; i < loop.length; i += 2) {
      const x = loop[i]!;
      const y = loop[i + 1]!;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  if (
    !Number.isFinite(minX) ||
    !Number.isFinite(minY) ||
    !Number.isFinite(maxX) ||
    !Number.isFinite(maxY)
  ) {
    return null;
  }

  return { loops, minX, minY, maxX, maxY };
}
