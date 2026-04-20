// frontend/src/components/BoardDisplay.tsx
import type React from "react";
import * as PIXI from "pixi.js-legacy";
import { addHexKeysToSet } from "../utils/movePoolRefsSync";
import { cubeDistance, offsetToCube } from "../utils/gameHelpers";
import { tryBuildHexUnionMaskPolygons } from "../utils/hexUnionBoundaryPolygon";
import { smoothMaskLoopsForRender } from "../utils/polygonSmooth";

/** Contourne TS2345 : certaines fusions de types sur `.on` attendent `(...args: unknown[]) => void`. */
function asPixiUnknownArgsPointerListener(
  fn: (e: PIXI.FederatedPointerEvent) => void,
): (...args: unknown[]) => void {
  return fn as (...args: unknown[]) => void;
}

/**
 * Passes Chaikin sur les masques move/advance (rendu uniquement).
 * Plus de passes + plafond de sommets relevé (voir ``MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS``) =
 * bord **plus continu**, moins « dentelé » par les micro-segments du contour hex.
 */
const MOVE_ADVANCE_MASK_POLYGON_CHAIKIN_ITERATIONS = 5;
/** Autorise des passes Chaikin supplémentaires sur les très gros contours (défaut global 48k). */
const MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS = 120_000;
/**
 * Suréchantillonnage de la RT masque : plus de pixels sur le contour = moins d’escalier, **sans** flou.
 * (Pas de BlurFilter : contour net ; l’anti-alias vient du rendu haute résolution + Chaikin sur le poly.)
 */
const MOVE_MASK_RT_RESOLUTION_SCALE = 3;

const moveAdvanceMaskSmoothOptions = {
  maxVertsAfterOneChaikinStep: MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS,
} as const;

/** Évite de re-rendre une RT masque identique (même géométrie + résolution) — ex. re-clic unité. */
let moveAdvanceMaskServerLoopsCache: {
  key: string;
  texture: PIXI.RenderTexture;
  maskBounds: PIXI.Rectangle;
} | null = null;

/** Empreinte des boucles **lissées** (contenu réel de la RT masque). */
function fingerprintSmoothedMaskLoops(smoothed: number[][]): string {
  let h = 2166136261 >>> 0;
  for (let li = 0; li < smoothed.length; li++) {
    const L = smoothed[li]!;
    h = (Math.imul(h ^ L.length, 16777619) >>> 0) ^ 0;
    const step = Math.max(2, Math.floor(L.length / 16)) * 2;
    for (let i = 0; i < L.length; i += step) {
      const v = L[i]!;
      h = (Math.imul(h ^ (Number.isFinite(v) ? Math.floor(v * 1e6) : 0), 16777619) >>> 0) ^ 0;
    }
    if (L.length > 0) {
      const last = L[L.length - 1]!;
      h = (Math.imul(h ^ (Number.isFinite(last) ? Math.floor(last * 1e6) : 0), 16777619) >>> 0) ^ 0;
    }
  }
  return String(h);
}

interface BoardConfig {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
  colors: {
    background: string;
    cell_even: string;
    cell_odd: string;
    cell_border: string;
    highlight: string;
    attack: string;
    charge: string;
    eligible: string;
    objective: string;
    objective_zone: string;
    wall: string;
    [key: string]: string;
  };
  display: {
    icon_scale: number;
    eligible_outline_width: number;
    eligible_outline_alpha: number;
    hp_bar_width_ratio: number;
    hp_bar_height: number;
    hp_bar_y_offset_ratio: number;
    unit_circle_radius_ratio: number;
    unit_text_size: number;
    selected_border_width: number;
    charge_target_border_width: number;
    default_border_width: number;
    canvas_border: string;
    antialias: boolean;
    autoDensity: boolean;
    resolution: number | "auto";
    background_image?: string;
    background_image_alpha?: number;
    background_overlay_alpha?: number;
    wall_texture?: string;
    wall_texture_alpha?: number;
    /** Chemin public (ex. /textures/obj1.webp). Teinte = couleur objectif / contrôle. */
    objective_texture?: string;
    objective_texture_alpha?: number;
    objective_smooth_contour?: boolean;
    /** Multiplie le rayon extérieur de la surcouche zone (barycentre → hex le plus éloigné + 1 hex). */
    objective_smooth_radius_ratio?: number;
    /** @deprecated Utiliser objective_zone_ring_alpha. Conservé comme défaut si objective_zone_ring_alpha absent. */
    objective_smooth_alpha?: number;
    /** Alpha des pastilles d’emprise par hex (footprint). */
    objective_hex_fill_alpha?: number;
    /** Cercle extérieur : épaisseur du trait (px). */
    objective_zone_ring_width?: number;
    objective_zone_ring_color?: string;
    objective_zone_ring_alpha?: number;
    /** Rayon du petit disque central, en fraction du rayon extérieur (0–1). */
    objective_zone_center_radius_ratio?: number;
    objective_zone_center_color?: string;
    objective_zone_center_alpha?: number;
  };
  objective_hexes: [number, number][];
  objective_zones?: Array<{
    id: string;
    hexes: Array<[number, number] | { col: number; row: number }>;
  }>;
  wall_hexes: [number, number][];
  walls?: Array<{
    start: { col: number; row: number };
    end: { col: number; row: number };
    thickness?: number;
  }>;
}

interface HighlightCell {
  col: number;
  row: number;
}

// Objective control info - which player controls each hex
interface ObjectiveControlMap {
  [hexKey: string]: number | null; // "col,row" -> 0 (P0), 1 (P1), or null (contested/uncontrolled)
}

export interface DrawBoardOptions {
  availableCells?: HighlightCell[];
  attackCells?: HighlightCell[];
  coverCells?: HighlightCell[];
  chargeCells?: HighlightCell[];
  advanceCells?: HighlightCell[]; // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Orange hexes
  blockedTargets?: Set<string>;
  coverTargets?: Set<string>;
  phase?: "move" | "shoot" | "charge" | "fight";
  interactionPhase?: "deployment" | "command" | "move" | "shoot" | "charge" | "fight";
  selectedUnitId?: number | null;
  mode?: string;
  showHexCoordinates?: boolean;
  objectiveControl?: ObjectiveControlMap;
  moveDestPoolRef?: React.RefObject<Set<string>>;
  /**
   * ``move_preview_footprint_zone`` : chaque sous-hex couvert par la preview — union d’hex **sans lacunes**
   * (contrairement au seul pool d’ancres). Utilisée comme masque du disque pour éviter les « plats »
   * entre disques d’empreinte près des murs / angles concaves.
   */
  footprintZonePoolRef?: React.RefObject<Set<string>>;
  /**
   * Ancres move/advance depuis game_state (repli si ``moveDestPoolRef`` vide). Le dessin des disques
   * privilégie **toujours** ``moveDestPoolRef`` quand elle est non vide — même principe que la charge.
   */
  moveDestinationAnchorsFromState?: unknown;
  /** Prioritaire sur ``selectedUnitBaseSize`` : span moteur (game_state.move_preview_footprint_span). */
  movePreviewFootprintSpanFromState?: number | null;
  /** Voir ``interactionPhase === "shoot"`` + ``movePoolRefsSync`` : pavage disques vs pastilles hex. */
  pendingMoveAfterShooting?: boolean;
  /** Ancres charge (même sémantique que ``moveDestPoolRef``) — preview multi-base comme la phase move. */
  chargeDestPoolRef?: React.RefObject<Set<string>>;
  selectedUnitBaseSize?: number;
  /**
   * (col, row) de l'unité dont on dessine la preview move / advance / post-shoot.
   *
   * Requis pour rendre la zone en **disque euclidien** (rayon calculé depuis le
   * centre de l'unité jusqu'au bord extérieur du BFS + demi-empreinte), masqué
   * par l'union des empreintes du pool — cercle net en terrain libre, tronqué
   * franchement par murs / EZ / pathfinding. Si absent ou si le pool est vide,
   * on retombe sur le pipeline union-de-disques historique.
   */
  selectedUnitAnchor?: { col: number; row: number } | null;
  /** Pre-built static board container (background + wall dots + objectives base). Reused across renders. */
  cachedStaticBoard?: PIXI.Container | null;
  /** Pre-built wall segments container. Reused across renders. */
  cachedWalls?: PIXI.Container | null;
  losDebugShowRatio?: boolean;
  losDebugRatioByHex?: Record<string, number>;
  losDebugCoverRatio?: number;
  losDebugVisibilityMinRatio?: number;
  /** Halo violet (grand plateau) : centre sur la cible de charge, rayon ~ engagement_zone en pas hex. */
  chargeEngagementHalo?: {
    centerCol: number;
    centerRow: number;
    zoneHexSteps: number;
  };
  /** Preview combat : cercle euclidien (bord extérieur lissé par-dessus les pastilles hex). */
  fightEngagementRing?: {
    cx: number;
    cy: number;
    rInner: number;
    rOuter: number;
  };
  /**
   * Contours masque move (coord. monde), envoyés par l’API — prioritaires sur
   * ``footprintZonePoolRef`` (évite un gros JSON de milliers d’hex).
   */
  movePreviewFootprintMaskLoops?: number[][] | null;
}

export interface DrawBoardResult {
  baseHexContainer: PIXI.Container;
  wallsContainer: PIXI.Container | null;
}

type PixelPt = [number, number];

/** Cercle dont [p1,p2] est un diamètre. */
function circleFromDiameter(p1: PixelPt, p2: PixelPt): { cx: number; cy: number; r: number } {
  const cx = (p1[0] + p2[0]) / 2;
  const cy = (p1[1] + p2[1]) / 2;
  const r = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / 2;
  return { cx, cy, r };
}

/** Cercle circonscrit aux trois points (null si alignés). */
function circumcircleThroughThreePoints(
  p1: PixelPt,
  p2: PixelPt,
  p3: PixelPt
): { cx: number; cy: number; r: number } | null {
  const ax = p1[0];
  const ay = p1[1];
  const bx = p2[0];
  const by = p2[1];
  const cx = p3[0];
  const cy = p3[1];
  const d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
  if (Math.abs(d) < 1e-12) return null;
  const a2 = ax * ax + ay * ay;
  const b2 = bx * bx + by * by;
  const c2 = cx * cx + cy * cy;
  const ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d;
  const uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d;
  const r = Math.hypot(ux - ax, uy - ay);
  return { cx: ux, cy: uy, r };
}

/** Énumération paires/triples : gardé pour petits jeux de points uniquement. */
const MEC_BRUTE_MAX_POINTS = 120;

/** Enveloppe convexe (monotone chain). Le MEC d’un ensemble fini du plan est celui de son enveloppe. */
function convexHull2D(points: PixelPt[]): PixelPt[] {
  if (points.length <= 1) return points.slice();
  const sorted = [...points].sort((a, b) => (a[0] === b[0] ? a[1] - b[1] : a[0] - b[0]));
  const cross = (o: PixelPt, a: PixelPt, b: PixelPt) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: PixelPt[] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2]!, lower[lower.length - 1]!, p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }
  const upper: PixelPt[] = [];
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i]!;
    while (upper.length >= 2 && cross(upper[upper.length - 2]!, upper[upper.length - 1]!, p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

/**
 * Plus petit cercle contenant des points, par énumération paires/triples — sans récursion.
 */
function bruteForceSmallestEnclosingCirclePoints(
  points: PixelPt[]
): { cx: number; cy: number; r: number } {
  const n = points.length;
  const EPS = 1e-6;
  if (n === 0) {
    return { cx: 0, cy: 0, r: 0 };
  }
  if (n === 1) {
    const p = points[0]!;
    return { cx: p[0], cy: p[1], r: 0 };
  }

  const containsAll = (c: { cx: number; cy: number; r: number }): boolean => {
    return points.every((p) => Math.hypot(p[0] - c.cx, p[1] - c.cy) <= c.r + EPS);
  };

  let best = { cx: 0, cy: 0, r: Number.POSITIVE_INFINITY };

  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const c = circleFromDiameter(points[i]!, points[j]!);
      if (containsAll(c) && c.r < best.r) {
        best = c;
      }
    }
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      for (let k = j + 1; k < n; k++) {
        const c = circumcircleThroughThreePoints(points[i]!, points[j]!, points[k]!);
        if (c !== null && containsAll(c) && c.r < best.r) {
          best = c;
        }
      }
    }
  }

  if (!Number.isFinite(best.r)) {
    let sx = 0;
    let sy = 0;
    for (const p of points) {
      sx += p[0];
      sy += p[1];
    }
    const cx = sx / n;
    const cy = sy / n;
    let mr = 0;
    for (const p of points) {
      mr = Math.max(mr, Math.hypot(p[0] - cx, p[1] - cy));
    }
    return { cx, cy, r: mr };
  }

  return best;
}

function trivialBoundaryCircle(R: PixelPt[]): { cx: number; cy: number; r: number } {
  if (R.length === 0) {
    return { cx: 0, cy: 0, r: -1 };
  }
  if (R.length === 1) {
    const p = R[0]!;
    return { cx: p[0], cy: p[1], r: 0 };
  }
  if (R.length === 2) {
    return circleFromDiameter(R[0]!, R[1]!);
  }
  const cc = circumcircleThroughThreePoints(R[0]!, R[1]!, R[2]!);
  if (cc !== null) return cc;
  const a = circleFromDiameter(R[0]!, R[1]!);
  const b = circleFromDiameter(R[0]!, R[2]!);
  const c = circleFromDiameter(R[1]!, R[2]!);
  return a.r >= b.r && a.r >= c.r ? a : b.r >= c.r ? b : c;
}

/**
 * Welzl sur `pts` mélangés — uniquement sur l’enveloppe (souvent ≤ quelques centaines de sommets).
 * Profondeur = nombre de points passés ; ne pas appeler avec des milliers de points.
 */
function welzlSmallestEnclosingCirclePoints(pts: PixelPt[]): { cx: number; cy: number; r: number } {
  const shuffled = pts.map((p) => [p[0], p[1]] as PixelPt);
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = (Math.random() * (i + 1)) | 0;
    const t = shuffled[i]!;
    shuffled[i] = shuffled[j]!;
    shuffled[j] = t;
  }
  const EPS = 1e-7;
  const inside = (p: PixelPt, c: { cx: number; cy: number; r: number }) =>
    c.r >= 0 && Math.hypot(p[0] - c.cx, p[1] - c.cy) <= c.r + EPS;

  const sec = (n: number, R: PixelPt[]): { cx: number; cy: number; r: number } => {
    if (n === 0 || R.length === 3) {
      return trivialBoundaryCircle(R);
    }
    const D = sec(n - 1, R);
    if (inside(shuffled[n - 1]!, D)) {
      return D;
    }
    return sec(n - 1, [...R, shuffled[n - 1]!]);
  };

  return sec(shuffled.length, []);
}

/**
 * MEC des centres d’hex, puis +hexRadius pour couvrir les disques comme les pastilles objectif.
 * Enveloppe convexe → même MEC qu’avec tous les centres ; Welzl seulement sur le contour (léger).
 */
function smallestEnclosingCircleForHexDisks(
  hexCenters: PixelPt[],
  hexRadius: number
): { cx: number; cy: number; r: number } {
  const n = hexCenters.length;
  if (n === 0) {
    return { cx: 0, cy: 0, r: 0 };
  }
  if (n === 1) {
    const p = hexCenters[0]!;
    return { cx: p[0], cy: p[1], r: hexRadius };
  }

  const hull = convexHull2D(hexCenters);
  const mecInput = hull.length >= 1 ? hull : hexCenters;

  let core: { cx: number; cy: number; r: number };
  if (mecInput.length <= MEC_BRUTE_MAX_POINTS) {
    core = bruteForceSmallestEnclosingCirclePoints(mecInput);
  } else {
    core = welzlSmallestEnclosingCirclePoints(mecInput);
  }

  return { cx: core.cx, cy: core.cy, r: core.r + hexRadius };
}

// Parse colors from config - same as Board.tsx
const parseColor = (colorStr: string): number => {
  return parseInt(colorStr.replace("0x", ""), 16);
};

/**
 * Phase move / charge : pool → disques d’empreinte → une ou plusieurs `RenderTexture` (tuiles) → sprites.
 *
 * - **Pas de repli** sur un `Graphics` brut : bornes invalides ou erreur → destruction, rien au stage.
 * - **Tuiles** : réponse aux plafonds GPU (4096 px / côté) — rendu nominal pour les grandes zones, pas un plan B graphique.
 *
 * `resolution` + `alphaMode` alignés sur le framebuffer ; **multisample désactivé** sur la RT
 * (MSAA sur RenderTexture = échecs GL fréquents → `catch` → aucun sprite, preview vide).
 */
/** Taille max d’un côté de tuile (limite texture WebGL courante). Au-delà on découpe en plusieurs RT. */
const FOOTPRINT_HIGHLIGHT_RT_MAX_DIM = 4096;
/** Union d’hex pour le masque : chunk pour rester sous la limite d’indices (~65k) par `Graphics`. */
const MOVE_ADVANCE_MASK_HEX_CHUNK = 800;

function addFootprintHighlightSprite(
  app: PIXI.Application,
  highlightContainer: PIXI.Container,
  gfx: PIXI.Graphics,
  alpha: number,
  displayName: string
): void {
  const lb = gfx.getLocalBounds();
  const bounds =
    lb.width > 0 && lb.height > 0 && Number.isFinite(lb.width) && Number.isFinite(lb.height)
      ? lb
      : gfx.getBounds();
  if (
    !Number.isFinite(bounds.width) ||
    !Number.isFinite(bounds.height) ||
    bounds.width <= 0 ||
    bounds.height <= 0
  ) {
    gfx.destroy();
    return;
  }
  const w = Math.ceil(bounds.width);
  const h = Math.ceil(bounds.height);
  const TILE = FOOTPRINT_HIGHLIGHT_RT_MAX_DIM;
  const tilesW = Math.max(1, Math.ceil(w / TILE));
  const tilesH = Math.max(1, Math.ceil(h / TILE));
  const createdSprites: PIXI.Sprite[] = [];
  const resolution = app.renderer.resolution;
  try {
    for (let j = 0; j < tilesH; j++) {
      for (let i = 0; i < tilesW; i++) {
        const tileLeft = i * TILE;
        const tileTop = j * TILE;
        const tw = Math.min(TILE, w - tileLeft);
        const th = Math.min(TILE, h - tileTop);
        const rt = PIXI.RenderTexture.create({
          width: tw,
          height: th,
          resolution,
          multisample: PIXI.MSAA_QUALITY.NONE,
          alphaMode: PIXI.ALPHA_MODES.PMA,
        });
        gfx.position.set(-bounds.x - tileLeft, -bounds.y - tileTop);
        app.renderer.render(gfx, { renderTexture: rt, clear: true });
        const sprite = new PIXI.Sprite(rt);
        sprite.name =
          tilesW === 1 && tilesH === 1 ? displayName : `${displayName}-t${i}-${j}`;
        sprite.position.set(bounds.x + tileLeft, bounds.y + tileTop);
        sprite.alpha = alpha;
        sprite.roundPixels = false;
        highlightContainer.addChild(sprite);
        createdSprites.push(sprite);
      }
    }
    gfx.destroy();
  } catch (err) {
    // Remonte explicitement les échecs silencieux du pipeline RenderTexture
    // (perte de contexte WebGL, dépassement du buffer d'indices, bornes Pixi
    // aberrantes…) uniquement en mode debug — sinon aucun sprite ne sort au
    // stage et la zone de preview disparait sans laisser de trace en console.
    if (typeof window !== "undefined") {
      try {
        if (window.localStorage.getItem("debugMovePool") === "1") {
          const lb = gfx.getLocalBounds?.();
          console.warn(
            "[addFootprintHighlightSprite] RenderTexture pipeline failed",
            {
              spriteName: displayName,
              width: w,
              height: h,
              tilesW,
              tilesH,
              localBounds: lb
                ? { x: lb.x, y: lb.y, width: lb.width, height: lb.height }
                : null,
            },
            err,
          );
        }
      } catch {
        // ignore localStorage/console access errors (SSR, privacy mode)
      }
    }
    for (const s of createdSprites) {
      s.destroy({ texture: true });
    }
    gfx.destroy();
  }
}

/** Contour extérieur lissé pour la preview d’engagement (combat) — plusieurs traits concentriques. */
function createFightEngagementRingSmoothOutline(
  cx: number,
  cy: number,
  rOuter: number,
  color: number,
): PIXI.Graphics {
  const gfx = new PIXI.Graphics();
  gfx.name = "fight-engagement-ring-smooth";
  appendFeatheredCircleOutlineStrokes(gfx, cx, cy, rOuter, color);
  return gfx;
}

type FeatherLayer = { width: number; alpha: number; useHighlightStroke?: boolean };

/**
 * Traits concentriques anti-alias (même logique que halo charge / anneau combat).
 * Réduit le crénelage du bord des disques de preview move/charge.
 */
function appendFeatheredCircleOutlineStrokes(
  gfx: PIXI.Graphics,
  cx: number,
  cy: number,
  r: number,
  color: number,
  layers?: FeatherLayer[],
): void {
  const hi = Math.min(0xffffff, ((color & 0xfefefe) >> 1) + 0x282828);
  const defaultLayers: FeatherLayer[] =
    layers ??
    [
      { width: Math.max(5, Math.min(14, r * 0.018)), alpha: 0.1 },
      { width: 2.6, alpha: 0.34 },
      { width: 1.05, alpha: 0.8, useHighlightStroke: true },
    ];
  for (const layer of defaultLayers) {
    const strokeColor = layer.useHighlightStroke ? hi : color;
    gfx.lineStyle(layer.width, strokeColor, layer.alpha);
    gfx.drawCircle(cx, cy, r);
  }
}

/** Au-delà, pas de contour (coût O(n) traits GPU → trop lent sur Board×10). */
const FOOTPRINT_POOL_OUTLINE_MAX_CENTERS = 160;

/**
 * Plafond strict du nombre de `drawCircle` poussés dans un unique `PIXI.Graphics`
 * pour le remplissage des pools move / charge.
 *
 * Pixi génère ~40 sommets par cercle : au-delà de ~1500 disques, on dépasse la
 * capacité du buffer d'indices 16 bits (65 535) et le rendu `RenderTexture`
 * échoue silencieusement — résultat : aucun sprite lissé, seul un autre layer
 * (contours / hit-areas / cellules hex en fallback) reste visible, d'où la
 * perception d'un "preview en hex" au lieu d'un disque.
 *
 * Le footprint des pools `move` est typiquement `(BASE_SIZE/2) * HEX_HORIZ_SPACING`,
 * soit plusieurs fois l'inter-cellule → la décimation par grille est sans
 * conséquence visuelle (les disques conservés recouvrent largement les sautés).
 */
const FOOTPRINT_POOL_MAX_CIRCLES = 1500;

/**
 * Cellule de bord du pool : au moins un de ses 6 voisins (flat-top avec offset
 * de colonnes impaires vers le bas) est absent du pool.
 *
 * On garde **toutes** les cellules de bord intactes lors de la décimation pour
 * préserver la frontière visible de la zone d'empreinte ; seul l'intérieur est
 * sous-échantillonné.
 */
function isPoolBoundaryCell(c: number, r: number, pool: Set<string>): boolean {
  const neighbours: Array<[number, number]> =
    c % 2 === 0
      ? [
          [c, r - 1],
          [c, r + 1],
          [c - 1, r - 1],
          [c - 1, r],
          [c + 1, r - 1],
          [c + 1, r],
        ]
      : [
          [c, r - 1],
          [c, r + 1],
          [c - 1, r],
          [c - 1, r + 1],
          [c + 1, r],
          [c + 1, r + 1],
        ];
  for (const [nc, nr] of neighbours) {
    if (!pool.has(`${nc},${nr}`)) return true;
  }
  return false;
}

/**
 * Pousse les disques d'empreinte d'un pool dans un `PIXI.Graphics` unique.
 *
 * - **Un seul `beginFill` / `endFill`** pour tous les cercles (≪ 6 000 changements
 *   d'état Pixi sur un pool dense, cause directe de la perte silencieuse du
 *   contexte WebGL / du rendu `RenderTexture` vide observée en phase move).
 * - **Cap `FOOTPRINT_POOL_MAX_CIRCLES`** avec décimation `(c + r) % stride === 0`
 *   + préservation systématique des cellules de bord — couverture strictement
 *   équivalente tant que `footprintRadius ≥ stride · max(HEX_HORIZ_SPACING,
 *   HEX_VERT_SPACING)`, condition toujours vraie pour les pools move / charge
 *   réels où `footprintRadius ≫ spacing`.
 */
function fillFootprintPoolCircles(
  gfx: PIXI.Graphics,
  pool: Set<string>,
  footprintRadius: number,
  fillColor: number,
  HEX_HORIZ_SPACING: number,
  HEX_WIDTH: number,
  HEX_HEIGHT: number,
  HEX_VERT_SPACING: number,
  MARGIN: number,
): number {
  const stride =
    pool.size > FOOTPRINT_POOL_MAX_CIRCLES
      ? Math.max(2, Math.ceil(pool.size / FOOTPRINT_POOL_MAX_CIRCLES))
      : 1;
  gfx.beginFill(fillColor, 1.0);
  let drawn = 0;
  for (const key of pool) {
    const sep = key.indexOf(",");
    const c = Number(key.substring(0, sep));
    const r = Number(key.substring(sep + 1));
    if (stride > 1 && ((c + r) % stride) !== 0 && !isPoolBoundaryCell(c, r, pool)) {
      continue;
    }
    const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const hy =
      r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
    gfx.drawCircle(hx, hy, footprintRadius);
    drawn++;
  }
  gfx.endFill();
  return drawn;
}

/**
 * Contour léger au-dessus du remplissage union des empreintes (move / charge).
 * Un seul trait par centre + seuil : évite 2–3× drawCircle par centre (très lent au redraw).
 */
function addFootprintPoolSmoothOutlines(
  highlightContainer: PIXI.Container,
  pool: Set<string>,
  footprintRadius: number,
  HEX_HORIZ_SPACING: number,
  HEX_WIDTH: number,
  HEX_HEIGHT: number,
  HEX_VERT_SPACING: number,
  MARGIN: number,
  color: number,
): void {
  if (pool.size === 0 || footprintRadius <= 0) return;
  if (pool.size > FOOTPRINT_POOL_OUTLINE_MAX_CENTERS) {
    return;
  }

  const gfx = new PIXI.Graphics();
  gfx.name = "footprint-pool-smooth-outline";
  gfx.eventMode = "none";
  gfx.alpha = 0.32;
  const strokeW = Math.max(1.0, Math.min(2.4, footprintRadius * 0.038));
  gfx.lineStyle(strokeW, color, 0.16);
  for (const key of pool) {
    const sep = key.indexOf(",");
    const c = Number(key.substring(0, sep));
    const r = Number(key.substring(sep + 1));
    const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const hy =
      r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
    gfx.drawCircle(hx, hy, footprintRadius);
  }
  highlightContainer.addChild(gfx);
}

/**
 * Zone de preview **move / advance / post-shoot** rendue comme un **cercle
 * euclidien** centré sur l'unité sélectionnée — pas comme l'union des disques
 * d'empreinte du BFS (qui donne naturellement une forme hexagonale parce que le
 * BFS s'effectue sur grille hex).
 *
 * Principe :
 * - **Rayon** = `max_euclidean_distance(unit_center → cellule du pool) +
 *   demi-empreinte`. Dérivé du BFS, donc aligné sur la portée réelle autorisée
 *   par le moteur (M×10 en phase move, M×10+D6×10 en advance, etc.) sans
 *   dupliquer les règles côté front.
 * - **Masque** : si ``move_preview_footprint_zone`` est disponible (**union d’hex
 *   pleins** par sous-hex), on l’utilise — pas de « plats » bitangents entre
 *   disques d’empreinte près des angles concaves. Sinon repli : union des
 *   disques d’empreinte aux ancres (comportement historique).
 *
 * **Chemin unique, pas de fallback silencieux** : toute condition aberrante
 * (pool vide, empreinte nulle, bornes du masque non finies, RT trop grande,
 * échec du rendu GPU…) lève une erreur explicite. C'est volontaire : on
 * préfère un crash visible qu'un rendu "à peu près" qui masque un vrai bug.
 */
function renderMoveAdvanceDestPoolCircleLayer(
  app: PIXI.Application,
  highlightContainer: PIXI.Container,
  anchorPool: Set<string>,
  footprintMaskHexPool: Set<string> | null,
  gridHexRadius: number,
  footprintRadius: number,
  poolFillColor: number,
  spriteName: string,
  unitCol: number,
  unitRow: number,
  unitCx: number,
  unitCy: number,
  HEX_HORIZ_SPACING: number,
  HEX_WIDTH: number,
  HEX_HEIGHT: number,
  HEX_VERT_SPACING: number,
  MARGIN: number,
  /** Boucles masque monde (API) — prioritaire sur ``footprintMaskHexPool``. */
  precomputedWorldMaskLoops: number[][] | null,
): void {
  if (anchorPool.size === 0) {
    throw new Error(
      `[renderMoveAdvanceDestPoolCircleLayer] anchorPool vide (spriteName=${spriteName})`,
    );
  }
  if (!(footprintRadius > 0) || !Number.isFinite(footprintRadius)) {
    throw new Error(
      `[renderMoveAdvanceDestPoolCircleLayer] footprintRadius invalide (${footprintRadius}, spriteName=${spriteName})`,
    );
  }
  if (!(gridHexRadius > 0) || !Number.isFinite(gridHexRadius)) {
    throw new Error(
      `[renderMoveAdvanceDestPoolCircleLayer] gridHexRadius invalide (${gridHexRadius}, spriteName=${spriteName})`,
    );
  }

  // **Rayon cible** : on veut la distance qui correspond à la règle "M × 10
  // hexes" côté moteur. Pour l'obtenir sans lire ``unit.M`` côté front on prend
  // la **distance hex maximale** (cube distance) entre le centre de l'unité et
  // n'importe quelle cellule du pool — c'est exactement la borne BFS du moteur
  // (= M×10 en phase move, +D6 en advance, etc.).
  //
  // Pourquoi pas la distance euclidienne max ? Parce que sur grille hex, le BFS
  // à distance N forme un hexagone : les cellules les plus lointaines en
  // **euclidien** sont les 6 sommets du polygone (distance ≈ N × HEX_HEIGHT),
  // PAS les bords flat (distance = N × HEX_HORIZ_SPACING). Un cercle centré sur
  // l'unité dont le rayon est la distance vertex DÉPASSE le polygone BFS sur
  // les bords flat → le masque rogne cette zone et le rendu final reprend
  // exactement la forme hex — bug visuel observé en pratique.
  //
  // En prenant ``max_cube × HEX_HORIZ_SPACING + demi-empreinte``, le cercle est
  // strictement **inscrit** dans le polygone BFS (sauf aux 6 coins, où il
  // effleure) → le masque ne le rogne plus qu'aux endroits réellement bloqués
  // par murs / EZ / pathfinding, ce qui est le comportement voulu.
  const unitCube = offsetToCube(unitCol, unitRow);
  let maxCubeDist = 0;
  for (const key of anchorPool) {
    const sep = key.indexOf(",");
    const c = Number(key.substring(0, sep));
    const r = Number(key.substring(sep + 1));
    const d = cubeDistance(unitCube, offsetToCube(c, r));
    if (d > maxCubeDist) maxCubeDist = d;
  }
  const rOuter = maxCubeDist * HEX_HORIZ_SPACING + footprintRadius;
  if (!Number.isFinite(rOuter) || !(rOuter > 0)) {
    throw new Error(
      `[renderMoveAdvanceDestPoolCircleLayer] rOuter invalide (${rOuter}, ` +
        `maxCubeDist=${maxCubeDist}, spriteName=${spriteName})`,
    );
  }

  // Masque : préférence **union d’hex** (``move_preview_footprint_zone``) — suit les bords
  // créneaux / murs sans segments droits parasites entre disques d’empreinte.
  let maskBounds: PIXI.Rectangle;
  let drawnMaskCircles: number | undefined;
  let drawnMaskHexes: number | undefined;
  let maskUnionKind: "server_loops" | "polygon" | "hex_chunks" | undefined;

  const maskRtResolution = app.renderer.resolution * MOVE_MASK_RT_RESOLUTION_SCALE;

  const rt = (() => {
    if (precomputedWorldMaskLoops && precomputedWorldMaskLoops.length > 0) {
      maskUnionKind = "server_loops";
      const prep = smoothMaskLoopsForRender(
        precomputedWorldMaskLoops,
        MOVE_ADVANCE_MASK_POLYGON_CHAIKIN_ITERATIONS,
        moveAdvanceMaskSmoothOptions,
      );
      const { minX, minY, maxX, maxY } = prep;
      const w = Math.ceil(maxX - minX);
      const h = Math.ceil(maxY - minY);
      if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
        throw new Error(
          `[renderMoveAdvanceDestPoolCircleLayer] bornes masque server_loops invalides ` +
            `(w=${w}, h=${h}, spriteName=${spriteName})`,
        );
      }
      if (w > FOOTPRINT_HIGHLIGHT_RT_MAX_DIM || h > FOOTPRINT_HIGHLIGHT_RT_MAX_DIM) {
        throw new Error(
          `[renderMoveAdvanceDestPoolCircleLayer] masque server_loops trop grand (w=${w}, h=${h}, ` +
            `max=${FOOTPRINT_HIGHLIGHT_RT_MAX_DIM}, spriteName=${spriteName})`,
        );
      }
      maskBounds = new PIXI.Rectangle(minX, minY, w, h);

      const maskCacheKey = `${spriteName}|r${maskRtResolution}|${MOVE_ADVANCE_MASK_POLYGON_CHAIKIN_ITERATIONS}|${w}|${h}|${fingerprintSmoothedMaskLoops(prep.smoothed)}`;
      if (
        moveAdvanceMaskServerLoopsCache &&
        moveAdvanceMaskServerLoopsCache.key === maskCacheKey
      ) {
        maskBounds = moveAdvanceMaskServerLoopsCache.maskBounds;
        return moveAdvanceMaskServerLoopsCache.texture;
      }

      const texture = PIXI.RenderTexture.create({
        width: w,
        height: h,
        resolution: maskRtResolution,
        multisample: PIXI.MSAA_QUALITY.NONE,
        alphaMode: PIXI.ALPHA_MODES.PMA,
      });
      const g = new PIXI.Graphics();
      g.name = `${spriteName}-mask-server-loops`;
      g.beginFill(0xffffff, 1.0);
      for (const loop of prep.smoothed) {
        g.drawPolygon(loop);
      }
      g.endFill();
      g.position.set(-minX, -minY);
      app.renderer.render(g, { renderTexture: texture, clear: true });
      g.destroy();
      moveAdvanceMaskServerLoopsCache?.texture.destroy(true);
      moveAdvanceMaskServerLoopsCache = {
        key: maskCacheKey,
        texture,
        maskBounds,
      };
      return texture;
    }

    if (footprintMaskHexPool && footprintMaskHexPool.size > 0) {
      const keys = [...footprintMaskHexPool];
      const layout = {
        HEX_HORIZ_SPACING,
        HEX_WIDTH,
        HEX_HEIGHT,
        HEX_VERT_SPACING,
        MARGIN,
        gridHexRadius,
      };
      const polyMask = tryBuildHexUnionMaskPolygons(footprintMaskHexPool, layout);

      let minX: number;
      let minY: number;
      let maxX: number;
      let maxY: number;
      /** Boucles prêtes pour le draw (lissées) — uniquement si ``polyMask`` présent. */
      let hexUnionSmoothedDraw: number[][] | null = null;

      if (polyMask) {
        const hexPrep = smoothMaskLoopsForRender(
          polyMask.loops,
          MOVE_ADVANCE_MASK_POLYGON_CHAIKIN_ITERATIONS,
          moveAdvanceMaskSmoothOptions,
        );
        hexUnionSmoothedDraw = hexPrep.smoothed;
        maskUnionKind = "polygon";
        minX = hexPrep.minX;
        minY = hexPrep.minY;
        maxX = hexPrep.maxX;
        maxY = hexPrep.maxY;
      } else {
        maskUnionKind = "hex_chunks";
        minX = Infinity;
        minY = Infinity;
        maxX = -Infinity;
        maxY = -Infinity;
        for (const key of footprintMaskHexPool) {
          const sep = key.indexOf(",");
          const c = Number(key.substring(0, sep));
          const r = Number(key.substring(sep + 1));
          const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const hy =
            r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          for (let vi = 0; vi < 6; vi++) {
            const ang = (vi * Math.PI) / 3;
            const vx = hx + gridHexRadius * Math.cos(ang);
            const vy = hy + gridHexRadius * Math.sin(ang);
            if (vx < minX) minX = vx;
            if (vx > maxX) maxX = vx;
            if (vy < minY) minY = vy;
            if (vy > maxY) maxY = vy;
          }
        }
      }

      const w = Math.ceil(maxX - minX);
      const h = Math.ceil(maxY - minY);
      if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
        throw new Error(
          `[renderMoveAdvanceDestPoolCircleLayer] bornes masque hex invalides ` +
            `(w=${w}, h=${h}, spriteName=${spriteName})`,
        );
      }
      if (w > FOOTPRINT_HIGHLIGHT_RT_MAX_DIM || h > FOOTPRINT_HIGHLIGHT_RT_MAX_DIM) {
        throw new Error(
          `[renderMoveAdvanceDestPoolCircleLayer] masque hex trop grand (w=${w}, h=${h}, ` +
            `max=${FOOTPRINT_HIGHLIGHT_RT_MAX_DIM}, spriteName=${spriteName})`,
        );
      }
      maskBounds = new PIXI.Rectangle(minX, minY, w, h);
      drawnMaskHexes = keys.length;

      const texture = PIXI.RenderTexture.create({
        width: w,
        height: h,
        resolution: maskRtResolution,
        multisample: PIXI.MSAA_QUALITY.NONE,
        alphaMode: PIXI.ALPHA_MODES.PMA,
      });
      // Même schéma que le masque « disques » : un `Graphics` décalé de `(-minX,-minY)` vers la RT.
      // Un `Container` hors stage + `render(holder)` peut produire une RT vide (transforms).
      if (polyMask && hexUnionSmoothedDraw) {
        const g = new PIXI.Graphics();
        g.name = `${spriteName}-mask-hex-union-polygon`;
        g.beginFill(0xffffff, 1.0);
        for (const loop of hexUnionSmoothedDraw) {
          g.drawPolygon(loop);
        }
        g.endFill();
        g.position.set(-minX, -minY);
        app.renderer.render(g, { renderTexture: texture, clear: true });
        g.destroy();
      } else {
        for (let i = 0; i < keys.length; i += MOVE_ADVANCE_MASK_HEX_CHUNK) {
          const chunk = keys.slice(i, i + MOVE_ADVANCE_MASK_HEX_CHUNK);
          const g = new PIXI.Graphics();
          g.name = `${spriteName}-mask-hex-chunk-${i}`;
          g.beginFill(0xffffff, 1.0);
          for (const key of chunk) {
            const sep = key.indexOf(",");
            const c = Number(key.substring(0, sep));
            const r = Number(key.substring(sep + 1));
            const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
            const hy =
              r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
            const verts: number[] = [];
            for (let vi = 0; vi < 6; vi++) {
              const ang = (vi * Math.PI) / 3;
              verts.push(hx + gridHexRadius * Math.cos(ang), hy + gridHexRadius * Math.sin(ang));
            }
            g.drawPolygon(verts);
          }
          g.endFill();
          g.position.set(-minX, -minY);
          app.renderer.render(g, { renderTexture: texture, clear: i === 0 });
          g.destroy();
        }
      }
      return texture;
    }

    const maskGfx = new PIXI.Graphics();
    maskGfx.name = `${spriteName}-mask-gfx`;
    drawnMaskCircles = fillFootprintPoolCircles(
      maskGfx,
      anchorPool,
      footprintRadius,
      0xffffff,
      HEX_HORIZ_SPACING,
      HEX_WIDTH,
      HEX_HEIGHT,
      HEX_VERT_SPACING,
      MARGIN,
    );

    const lb = maskGfx.getLocalBounds();
    if (
      !Number.isFinite(lb.width) ||
      !Number.isFinite(lb.height) ||
      !(lb.width > 0) ||
      !(lb.height > 0)
    ) {
      maskGfx.destroy();
      throw new Error(
        `[renderMoveAdvanceDestPoolCircleLayer] bornes du masque disques invalides ` +
          `(w=${lb.width}, h=${lb.height}, spriteName=${spriteName}, ` +
          `drawnMaskCircles=${drawnMaskCircles})`,
      );
    }
    maskBounds = lb;

    const w = Math.ceil(maskBounds.width);
    const h = Math.ceil(maskBounds.height);
    if (w > FOOTPRINT_HIGHLIGHT_RT_MAX_DIM || h > FOOTPRINT_HIGHLIGHT_RT_MAX_DIM) {
      maskGfx.destroy();
      throw new Error(
        `[renderMoveAdvanceDestPoolCircleLayer] masque trop grand pour une RT ` +
          `unique (w=${w}, h=${h}, max=${FOOTPRINT_HIGHLIGHT_RT_MAX_DIM}, ` +
          `spriteName=${spriteName})`,
      );
    }

    const texture = PIXI.RenderTexture.create({
      width: w,
      height: h,
      resolution: maskRtResolution,
      multisample: PIXI.MSAA_QUALITY.NONE,
      alphaMode: PIXI.ALPHA_MODES.PMA,
    });
    maskGfx.position.set(-maskBounds.x, -maskBounds.y);
    app.renderer.render(maskGfx, { renderTexture: texture, clear: true });
    maskGfx.destroy();
    return texture;
  })();

  const w = Math.ceil(maskBounds.width);
  const h = Math.ceil(maskBounds.height);

  const maskSprite = new PIXI.Sprite(rt);
  maskSprite.name = `${spriteName}-mask-sprite`;
  maskSprite.position.set(maskBounds.x, maskBounds.y);
  maskSprite.roundPixels = false;
  /** Évite le voisinage « crénelé » (NEAREST) quand la RT masque est suréchantillonnée. */
  maskSprite.texture.baseTexture.scaleMode = PIXI.SCALE_MODES.LINEAR;

  if (typeof window !== "undefined") {
    try {
      if (window.localStorage.getItem("debugMovePreviewRender") === "1") {
        console.info("[renderMoveAdvanceDestPoolCircleLayer] maskSmooth", {
          chaikinIterations: MOVE_ADVANCE_MASK_POLYGON_CHAIKIN_ITERATIONS,
          chaikinMaxVerts: MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS,
          maskRtResolutionScale: MOVE_MASK_RT_RESOLUTION_SCALE,
          maskRtResolution,
          maskUnionKind,
          spriteName,
        });
      }
    } catch {
      // ignore
    }
  }

  // Grand disque cible. Alpha 0.28 (cohérence avec le halo de charge).
  const diskGfx = new PIXI.Graphics();
  diskGfx.name = spriteName;
  diskGfx.beginFill(poolFillColor, 1.0);
  diskGfx.drawCircle(unitCx, unitCy, rOuter);
  diskGfx.endFill();
  diskGfx.alpha = 0.28;
  diskGfx.mask = maskSprite;

  // Le masque DOIT être présent dans l'arbre d'affichage pour que Pixi calcule
  // sa transform lors du rendu, mais il ne s'affiche pas lui-même (utilisé
  // uniquement comme stencil/alpha). On l'ajoute dans le même container.
  highlightContainer.addChild(maskSprite);
  highlightContainer.addChild(diskGfx);

  if (typeof window !== "undefined") {
    try {
      if (window.localStorage.getItem("debugMovePool") === "1") {
        console.info("[renderMoveAdvanceDestPoolCircleLayer] rendered", {
          spriteName,
          anchorPoolSize: anchorPool.size,
          /** Réel chemin masque RT : sinon le libellé « anchor_disk_union » était affiché même avec ``server_loops``. */
          maskKind:
            drawnMaskHexes != null
              ? "footprint_hex_union"
              : (maskUnionKind ?? "anchor_disk_union"),
          maskUnionKind,
          drawnMaskHexes,
          drawnMaskCircles,
          footprintRadius,
          gridHexRadius,
          unitCol,
          unitRow,
          unitCx,
          unitCy,
          maxCubeDist,
          rOuter,
          maskSize: { w, h },
        });
      }
    } catch {
      // ignore
    }
  }
}

/** Remplissage objectif : texture teintée ou couleur unie (même pipeline que les murs). */
function beginObjectiveFill(
  g: PIXI.Graphics,
  texture: PIXI.Texture | null,
  fillColor: number,
  alpha: number
): void {
  if (texture) {
    g.beginTextureFill({
      texture,
      alpha,
      color: fillColor,
    });
  } else {
    g.beginFill(fillColor, alpha);
  }
}

/**
 * Pure visual board rendering - NO INTERACTIONS
 * Used by both BoardReplay (simple call) and Board.tsx (with highlights)
 */
export const drawBoard = (
  app: PIXI.Application,
  boardConfig: BoardConfig,
  options?: DrawBoardOptions
): DrawBoardResult | void => {
  if (!boardConfig || !app.stage) return;

  try {
    // Extract board configuration values - USE CONFIG VALUES
    const BOARD_COLS = boardConfig.cols;
    const BOARD_ROWS = boardConfig.rows;
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;

    // Parse colors from config
    const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight!);
    const ATTACK_COLOR = parseColor(boardConfig.colors.attack!);
    const WALL_COLOR = parseColor(boardConfig.colors.wall!);
    /** Hex destinations fin de charge (do not use ``colors.charge`` here: that key is orange UI / bordures). */
    const CHARGE_DESTINATION_HEX_FILL = 0x9f7aea;
    /** Advance move destinations (ADVANCE_IMPLEMENTATION_PLAN — same as legacy ``0xff8c00``). */
    const ADVANCE_DESTINATION_HEX_FILL = 0xff8c00;

    // Extract options with defaults for replay viewer compatibility
    const {
      availableCells = [],
      attackCells = [],
      coverCells = [],
      chargeCells = [],
      advanceCells = [], // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4
      phase = "move",
      interactionPhase = phase,
      selectedUnitId = null,
      mode = "select",
      showHexCoordinates: _showHexCoordinates = false,
      objectiveControl = {},
      moveDestPoolRef,
      footprintZonePoolRef,
      moveDestinationAnchorsFromState,
      movePreviewFootprintSpanFromState,
      pendingMoveAfterShooting = false,
      chargeDestPoolRef,
      selectedUnitBaseSize,
      selectedUnitAnchor,
      losDebugShowRatio: _losDebugShowRatio = false,
      losDebugRatioByHex: _losDebugRatioByHex = {},
      losDebugCoverRatio: _losDebugCoverRatio = 0,
      losDebugVisibilityMinRatio: _losDebugVisibilityMinRatio = 0,
      chargeEngagementHalo,
      fightEngagementRing,
      movePreviewFootprintMaskLoops = null,
    } = options || {};

    // Parse objective control colors - use same colors as player units
    if (!boardConfig.colors.player_1) {
      throw new Error("Missing required configuration value: boardConfig.colors.player_1");
    }
    if (!boardConfig.colors.player_2) {
      throw new Error("Missing required configuration value: boardConfig.colors.player_2");
    }
    if (!boardConfig.colors.objective) {
      throw new Error("Missing required configuration value: boardConfig.colors.objective");
    }
    const OBJECTIVE_P0_COLOR = parseColor(boardConfig.colors.player_1);
    const OBJECTIVE_P1_COLOR = parseColor(boardConfig.colors.player_2);
    const OBJECTIVE_NEUTRAL_COLOR = parseColor(boardConfig.colors.objective);

    // Compute all objective hexes - use ONLY hexes from config, no expansion
    const objectiveHexSet = new Set<string>();
    let baseObjectives: Array<[number, number]> = boardConfig.objective_hexes || [];
    if (baseObjectives.length === 0 && Array.isArray(boardConfig.objective_zones)) {
      baseObjectives = boardConfig.objective_zones.flatMap(z =>
        (z.hexes || []).map(h =>
          Array.isArray(h) ? h as [number, number] : [h.col, h.row] as [number, number]
        )
      );
    }

    for (const [objCol, objRow] of baseObjectives) {
      objectiveHexSet.add(`${objCol},${objRow}`);
    }

    /** Même rendu cercle + masque BFS que le move ; ne pas dépendre de ``interactionPhase === "shoot"`` (replay / mapping phase). */
    const useAdvanceMovePoolLikeMove = mode === "advancePreview";
    const usePostShootMovePoolLikeMove =
      interactionPhase === "shoot" && pendingMoveAfterShooting === true;
    const usePileInPoolLikeMoveHoisted =
      interactionPhase === "fight" &&
      (mode === "pileInPreview" || mode === "consolidationPreview");
    const advanceZoneFillColor = ADVANCE_DESTINATION_HEX_FILL;
    const spanFromEngine =
      typeof movePreviewFootprintSpanFromState === "number" &&
      Number.isFinite(movePreviewFootprintSpanFromState) &&
      movePreviewFootprintSpanFromState >= 1
        ? Math.floor(movePreviewFootprintSpanFromState)
        : null;
    const footprintSpanForPool = Math.max(1, spanFromEngine ?? selectedUnitBaseSize ?? 1);

    const anchorsFromStatePool: Set<string> | null = (() => {
      if (moveDestinationAnchorsFromState == null) return null;
      const s = new Set<string>();
      addHexKeysToSet(moveDestinationAnchorsFromState, s);
      return s.size > 0 ? s : null;
    })();

    /** Disques d’ancre : ``moveDestPoolRef`` en priorité (comme ``chargeDestPoolRef``), puis state. */
    const movePoolForDiskDraw: Set<string> | null =
      moveDestPoolRef?.current && moveDestPoolRef.current.size > 0
        ? moveDestPoolRef.current
        : anchorsFromStatePool && anchorsFromStatePool.size > 0
          ? anchorsFromStatePool
          : null;

    const useMoveDestPoolCircleLayer =
      (interactionPhase === "move" ||
        useAdvanceMovePoolLikeMove ||
        usePostShootMovePoolLikeMove) &&
      !!movePoolForDiskDraw &&
      movePoolForDiskDraw.size > 0;

    /** advancePreview sans pool : normal tant que le joueur n'a pas confirmé Advance (jet D6 + BFS) — ``allow_advance`` peut ouvrir l'UI avant toute réponse ``advance_destinations``. */

    const cachedStaticBoard = options?.cachedStaticBoard ?? null;
    const reuseStatic = cachedStaticBoard !== null;
    const baseHexContainer = reuseStatic ? cachedStaticBoard : new PIXI.Container();
    const highlightContainer = new PIXI.Container();
    if (!reuseStatic) {
      baseHexContainer.name = "baseHexes";
    }
    highlightContainer.name = "highlights";
    /** Au-dessus de l’overlay LoS survol (BoardPvp, zIndex ~40), sous les unités (2000) et la ligne/icône de prévisualisation (~848–900). */
    highlightContainer.zIndex = 120;
    const TOTAL_WIDTH = BOARD_COLS * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + 2 * MARGIN;
    const TOTAL_HEIGHT = BOARD_ROWS * HEX_VERT_SPACING + HEX_VERT_SPACING / 2 + 2 * MARGIN;
    const backgroundImagePath = boardConfig.display?.background_image?.trim();
    const backgroundImageAlpha =
      typeof boardConfig.display?.background_image_alpha === "number"
        ? boardConfig.display.background_image_alpha
        : 0.85;
    const backgroundOverlayAlpha =
      typeof boardConfig.display?.background_overlay_alpha === "number"
        ? boardConfig.display.background_overlay_alpha
        : 0.18;
    const objectiveSmoothContour = boardConfig.display?.objective_smooth_contour ?? true;
    const objectiveTexturePath = boardConfig.display?.objective_texture?.trim();
    const objectiveTexture =
      objectiveTexturePath && objectiveTexturePath.length > 0
        ? PIXI.Texture.from(objectiveTexturePath)
        : null;
    const objectiveTextureAlpha =
      typeof boardConfig.display?.objective_texture_alpha === "number"
        ? boardConfig.display.objective_texture_alpha
        : 0.85;

    const objectiveHexFillAlpha =
      typeof boardConfig.display?.objective_hex_fill_alpha === "number"
        ? boardConfig.display.objective_hex_fill_alpha
        : objectiveTexture
          ? objectiveTextureAlpha
          : 0.5;

    const smoothRadiusRatio =
      typeof boardConfig.display?.objective_smooth_radius_ratio === "number"
        ? boardConfig.display.objective_smooth_radius_ratio
        : 1.0;

    if (!reuseStatic) {
      if (backgroundImagePath) {
        const bgSprite = PIXI.Sprite.from(backgroundImagePath);
        bgSprite.x = 0;
        bgSprite.y = 0;
        bgSprite.width = TOTAL_WIDTH;
        bgSprite.height = TOTAL_HEIGHT;
        bgSprite.alpha = backgroundImageAlpha;
        baseHexContainer.addChild(bgSprite);

        const bgOverlay = new PIXI.Graphics();
        bgOverlay.beginFill(parseColor(boardConfig.colors.cell_even), backgroundOverlayAlpha);
        bgOverlay.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
        bgOverlay.endFill();
        baseHexContainer.addChild(bgOverlay);
      } else {
        const bg = new PIXI.Graphics();
        bg.beginFill(parseColor(boardConfig.colors.cell_even), 1.0);
        bg.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
        bg.endFill();
        baseHexContainer.addChild(bg);
      }

      const wallDotRadius = HEX_RADIUS;
      const wallAltColor = (WALL_COLOR & 0xfefefe) + 0x101010;
      for (const [wc, wr] of boardConfig.wall_hexes || []) {
        const wx = wc * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const wy = wr * HEX_VERT_SPACING + ((wc % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        const wallDot = new PIXI.Graphics();
        const fill = wc % 2 === 0 ? WALL_COLOR : wallAltColor;
        wallDot.beginFill(fill, 1.0);
        wallDot.drawCircle(wx, wy, wallDotRadius);
        wallDot.endFill();
        baseHexContainer.addChild(wallDot);
      }

      if (objectiveSmoothContour && Array.isArray(boardConfig.objective_zones)) {
        const displayCfg = boardConfig.display;
        const ringColorStr =
          typeof displayCfg?.objective_zone_ring_color === "string" &&
          displayCfg.objective_zone_ring_color.length > 0
            ? displayCfg.objective_zone_ring_color
            : boardConfig.colors.objective;
        const ringColorParsed = parseColor(ringColorStr);
        const ringAlpha =
          typeof displayCfg?.objective_zone_ring_alpha === "number"
            ? displayCfg.objective_zone_ring_alpha
            : typeof displayCfg?.objective_smooth_alpha === "number"
              ? displayCfg.objective_smooth_alpha
              : 0.35;
        const ringWidth =
          typeof displayCfg?.objective_zone_ring_width === "number"
            ? displayCfg.objective_zone_ring_width
            : Math.max(1.2, HEX_RADIUS * 0.22);
        const centerColorStr =
          typeof displayCfg?.objective_zone_center_color === "string" &&
          displayCfg.objective_zone_center_color.length > 0
            ? displayCfg.objective_zone_center_color
            : boardConfig.colors.objective;
        const centerColorParsed = parseColor(centerColorStr);
        const centerAlpha =
          typeof displayCfg?.objective_zone_center_alpha === "number"
            ? displayCfg.objective_zone_center_alpha
            : 0.5;
        const centerRadiusRatio =
          typeof displayCfg?.objective_zone_center_radius_ratio === "number"
            ? displayCfg.objective_zone_center_radius_ratio
            : 0.14;

        for (const zone of boardConfig.objective_zones) {
          const zoneHexes = zone.hexes || [];
          if (!Array.isArray(zoneHexes) || zoneHexes.length === 0) continue;

          const zoneCells: Array<[number, number]> = [];
          for (const h of zoneHexes) {
            const oc = Array.isArray(h) ? Number(h[0]) : Number((h as { col: number }).col);
            const or_ = Array.isArray(h) ? Number(h[1]) : Number((h as { row: number }).row);
            if (!Number.isFinite(oc) || !Number.isFinite(or_)) continue;
            zoneCells.push([oc, or_]);
          }
          if (zoneCells.length === 0) continue;

          const hexCenters: PixelPt[] = [];
          for (const [col, row] of zoneCells) {
            const hcx = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
            const hcy =
              row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
            hexCenters.push([hcx, hcy]);
          }

          const mec = smallestEnclosingCircleForHexDisks(hexCenters, HEX_RADIUS);
          if (
            Number.isFinite(mec.cx) &&
            Number.isFinite(mec.cy) &&
            Number.isFinite(mec.r) &&
            mec.r >= 0
          ) {
            const outerR = Math.max(0, mec.r * smoothRadiusRatio);
            const innerR = Math.max(0.5, outerR * centerRadiusRatio);

            const smoothZone = new PIXI.Graphics();
            smoothZone.lineStyle(ringWidth, ringColorParsed, ringAlpha);
            smoothZone.drawCircle(mec.cx, mec.cy, outerR);
            smoothZone.lineStyle(0);
            smoothZone.beginFill(centerColorParsed, centerAlpha);
            smoothZone.drawCircle(mec.cx, mec.cy, innerR);
            smoothZone.endFill();
            baseHexContainer.addChild(smoothZone);
          }
        }
      }

      for (const [oc, or_] of baseObjectives) {
        const ox = oc * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const oy = or_ * HEX_VERT_SPACING + ((oc % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        const hexKey = `${oc},${or_}`;
        const controller = objectiveControl[hexKey];
        let objColor = OBJECTIVE_NEUTRAL_COLOR;
        if (controller === 1) objColor = OBJECTIVE_P0_COLOR;
        else if (controller === 2) objColor = OBJECTIVE_P1_COLOR;
        const objDot = new PIXI.Graphics();
        beginObjectiveFill(objDot, objectiveTexture, objColor, objectiveHexFillAlpha);
        objDot.drawCircle(ox, oy, HEX_RADIUS);
        objDot.endFill();
        baseHexContainer.addChild(objDot);
      }
    }

    // Build clickable set for hit detection
    const clickableSet = new Set<string>();
    // Charge (pool selection): activation is unit-driven (boardUnitClick → left_click). Green
    // eligible hex highlights must stay non-interactive: the full-screen hitArea is above unit
    // sprites and would steal clicks while boardHexClick has no charge+select branch.
    if (!(interactionPhase === "charge" && mode === "select")) {
      for (const c of availableCells) clickableSet.add(`${c.col},${c.row}`);
    }
    for (const c of chargeCells) {
      const cc = Array.isArray(c) ? c[0] : (c as { col: number }).col;
      const cr = Array.isArray(c) ? c[1] : (c as { row: number }).row;
      clickableSet.add(`${cc},${cr}`);
    }
    for (const c of advanceCells) clickableSet.add(`${c.col},${c.row}`);

    // Évite les tableaux énormes de surbrillance move ; charge peut dépasser 500 hex (Board×10).
    const LARGE_POOL_THRESHOLD = 500;

    // Pile in : zone rouge (empreinte moteur) — comme move_preview_footprint_zone en forme,
    // pas seulement des disques aux ancres ; on dessine via ``availableCells`` (override).
    // Dès que le moteur fournit valid_move_destinations_pool : un disque par ancre (cercle),
    // pas un remplissage hex-par-hex de move_preview_footprint_zone (blob « hex géant » si BASE_SIZE
    // tuple/oval et selectedUnitBaseSize était undefined).
    const useConsolidationPreview = interactionPhase === "fight" && mode === "consolidationPreview";
    const availableCellsDrawColor = useAdvanceMovePoolLikeMove
      ? advanceZoneFillColor
      : usePileInPoolLikeMoveHoisted
        ? useConsolidationPreview
          ? 0xff8c00
          : ATTACK_COLOR
        : HIGHLIGHT_COLOR;

    const useChargeDestPoolDiskDraw =
      interactionPhase === "charge" &&
      (mode === "select" || mode === "chargePreview") &&
      chargeDestPoolRef?.current &&
      chargeDestPoolRef.current.size > 0;

    /** Move / advance / pile-in / post-shoot move : disques d’empreinte (comme la charge), pas des pastilles rayon hex (= grille « en hex »). */
    const useFootprintDiskRadiusForAvailCells =
      interactionPhase === "move" ||
      useAdvanceMovePoolLikeMove ||
      usePileInPoolLikeMoveHoisted ||
      usePostShootMovePoolLikeMove;
    const availableCellCircleR = useFootprintDiskRadiusForAvailCells
      ? (footprintSpanForPool / 2) * HEX_HORIZ_SPACING
      : HEX_RADIUS;

    const drawGroup = (
      cells: Array<{ col: number; row: number }>,
      color: number,
      alpha: number,
      skipThreshold = true,
      circleRadius: number = HEX_RADIUS,
    ) => {
      if (cells.length === 0) return;
      if (skipThreshold && cells.length > LARGE_POOL_THRESHOLD) return;
      const batch = new PIXI.Graphics();
      // Un beginFill/endFill par cercle : sinon Pixi fusionne les sous-chemins en un seul polygone
      // rempli (« hex géant » / blob au lieu de pastilles distinctes).
      for (const c of cells) {
        const hx = c.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const hy = c.row * HEX_VERT_SPACING + ((c.col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        batch.beginFill(color, alpha);
        batch.drawCircle(hx, hy, circleRadius);
        batch.endFill();
      }
      highlightContainer.addChild(batch);
    };

    if (useMoveDestPoolCircleLayer && movePoolForDiskDraw) {
      const footprintRadius = (footprintSpanForPool / 2) * HEX_HORIZ_SPACING;
      const poolFillColor = useAdvanceMovePoolLikeMove ? advanceZoneFillColor : HIGHLIGHT_COLOR;
      const moveSpriteName = useAdvanceMovePoolLikeMove
        ? "advance-dest-pool"
        : "move-dest-pool";
      // Spec utilisateur : preview = **cercle euclidien net** centré sur l'unité,
      // rayon = M×10 (dérivé du BFS) + demi-empreinte, tronqué par murs / EZ /
      // pathfinding via masque BFS. Pas de fallback : si ``selectedUnitAnchor``
      // n'est pas fourni alors qu'on entre dans le layer move, c'est un bug de
      // câblage côté caller (BoardPvp) et on veut le voir immédiatement.
      if (selectedUnitAnchor == null) {
        throw new Error(
          "[drawBoard] ``selectedUnitAnchor`` requis pour rendre le layer move/advance — " +
            `absent alors que useMoveDestPoolCircleLayer=true (spriteName=${moveSpriteName})`,
        );
      }
      const footprintMaskHexPool =
        footprintZonePoolRef?.current && footprintZonePoolRef.current.size > 0
          ? footprintZonePoolRef.current
          : null;
      renderMoveAdvanceDestPoolCircleLayer(
        app,
        highlightContainer,
        movePoolForDiskDraw,
        footprintMaskHexPool,
        HEX_RADIUS,
        footprintRadius,
        poolFillColor,
        moveSpriteName,
        selectedUnitAnchor.col,
        selectedUnitAnchor.row,
        selectedUnitAnchor.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN,
        selectedUnitAnchor.row * HEX_VERT_SPACING +
          ((selectedUnitAnchor.col % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN,
        HEX_HORIZ_SPACING,
        HEX_WIDTH,
        HEX_HEIGHT,
        HEX_VERT_SPACING,
        MARGIN,
        movePreviewFootprintMaskLoops,
      );
    } else {
      // Short-circuit uniquement si ``availableCells`` est vide côté caller : en phase déploiement
      // (mappée ``interactionPhase === "move"``), le pool de déploiement est légitimement poussé
      // dans ``availableCells`` et doit être dessiné comme des disques (aucune ancre côté moteur).
      const moveOrAdvanceNoAnchors =
        (interactionPhase === "move" ||
          useAdvanceMovePoolLikeMove ||
          usePostShootMovePoolLikeMove) &&
        !movePoolForDiskDraw &&
        availableCells.length === 0;
      const cellsForHighlight = moveOrAdvanceNoAnchors ? [] : availableCells;
      drawGroup(cellsForHighlight, availableCellsDrawColor, 0.4, false, availableCellCircleR);
    }
    {
      const useShootingPreviewPalette = phase === "shoot" || mode === "movePreview";
      if (useShootingPreviewPalette && (attackCells.length > 0 || coverCells.length > 0)) {
        const coverKeySet = new Set(coverCells.map((c) => `${c.col},${c.row}`));
        const attackClearOnly = attackCells.filter((c) => !coverKeySet.has(`${c.col},${c.row}`));
        drawGroup(coverCells, 0x9ec5ff, 0.4, false);
        drawGroup(attackClearOnly, 0x4f8bff, 0.4, false);
      } else {
        drawGroup(attackCells, ATTACK_COLOR, 0.4, false);
      }
    }
    if (useChargeDestPoolDiskDraw && chargeDestPoolRef?.current) {
      const footprintRadius = (footprintSpanForPool / 2) * HEX_HORIZ_SPACING;
      const chargeGfx = new PIXI.Graphics();
      chargeGfx.name = "charge-dest-pool-gfx";
      const chargePool = chargeDestPoolRef.current;
      fillFootprintPoolCircles(
        chargeGfx,
        chargePool,
        footprintRadius,
        CHARGE_DESTINATION_HEX_FILL,
        HEX_HORIZ_SPACING,
        HEX_WIDTH,
        HEX_HEIGHT,
        HEX_VERT_SPACING,
        MARGIN,
      );
      addFootprintHighlightSprite(app, highlightContainer, chargeGfx, 0.28, "charge-dest-pool");
      addFootprintPoolSmoothOutlines(
        highlightContainer,
        chargePool,
        footprintRadius,
        HEX_HORIZ_SPACING,
        HEX_WIDTH,
        HEX_HEIGHT,
        HEX_VERT_SPACING,
        MARGIN,
        CHARGE_DESTINATION_HEX_FILL,
      );
    } else {
      drawGroup(
        chargeCells.map((c: any) => ({
          col: Array.isArray(c) ? c[0] : c.col,
          row: Array.isArray(c) ? c[1] : c.row,
        })),
        CHARGE_DESTINATION_HEX_FILL,
        0.4,
        false,
      );
    }
    if (
      advanceCells.length > 0 &&
      !(mode === "advancePreview" && useMoveDestPoolCircleLayer && movePoolForDiskDraw)
    ) {
      drawGroup(advanceCells, ADVANCE_DESTINATION_HEX_FILL, 0.3, false);
    }

    if (
      chargeEngagementHalo &&
      typeof chargeEngagementHalo.zoneHexSteps === "number" &&
      chargeEngagementHalo.zoneHexSteps > 1 &&
      Number.isFinite(chargeEngagementHalo.centerCol) &&
      Number.isFinite(chargeEngagementHalo.centerRow)
    ) {
      const hcx =
        chargeEngagementHalo.centerCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const hcy =
        chargeEngagementHalo.centerRow * HEX_VERT_SPACING +
        ((chargeEngagementHalo.centerCol % 2) * HEX_VERT_SPACING) / 2 +
        HEX_HEIGHT / 2 +
        MARGIN;
      const ringGfx = new PIXI.Graphics();
      ringGfx.name = "charge-engagement-halo";
      const haloR = chargeEngagementHalo.zoneHexSteps * HEX_HORIZ_SPACING;
      const haloColor = CHARGE_DESTINATION_HEX_FILL;
      // Plusieurs traits superposés (large + léger → fin + opaque) : bord moins crénelé sous CanvasRenderer.
      const haloLayers: Array<{ width: number; alpha: number }> = [
        { width: 14, alpha: 0.06 },
        { width: 7, alpha: 0.14 },
        { width: 3, alpha: 0.32 },
      ];
      for (const layer of haloLayers) {
        ringGfx.lineStyle(layer.width, haloColor, layer.alpha);
        ringGfx.drawCircle(hcx, hcy, haloR);
      }
      highlightContainer.addChild(ringGfx);
    }

    const moveAdvanceOrPileInPickPool: Set<string> | null = (() => {
      if (
        interactionPhase === "move" ||
        useAdvanceMovePoolLikeMove ||
        usePostShootMovePoolLikeMove
      ) {
        return movePoolForDiskDraw && movePoolForDiskDraw.size > 0 ? movePoolForDiskDraw : null;
      }
      if (usePileInPoolLikeMoveHoisted) {
        if (moveDestPoolRef?.current && moveDestPoolRef.current.size > 0) {
          return moveDestPoolRef.current;
        }
        return null;
      }
      return null;
    })();

    // Invisible interactive overlay for click detection (pixelToHex nearest-neighbor)
    const hasClickableContent =
      clickableSet.size > 0 ||
      (moveAdvanceOrPileInPickPool != null && moveAdvanceOrPileInPickPool.size > 0) ||
      (interactionPhase === "charge" &&
        mode === "chargePreview" &&
        chargeDestPoolRef?.current &&
        chargeDestPoolRef.current.size > 0);
    if (hasClickableContent) {
      const hitArea = new PIXI.Graphics();
      hitArea.beginFill(0, 0);
      hitArea.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
      hitArea.endFill();
      hitArea.hitArea = new PIXI.Rectangle(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
      hitArea.eventMode = "static";
      hitArea.cursor = "pointer";

      const resolveHex = (pos: PIXI.IPointData): { col: number; row: number } => {
        const ux = pos.x - MARGIN;
        const uy = pos.y - MARGIN;
        const colApprox = (ux - HEX_WIDTH / 2) / HEX_HORIZ_SPACING;
        const c0 = Math.max(0, Math.floor(colApprox) - 2);
        const c1 = Math.min(BOARD_COLS - 1, Math.ceil(colApprox) + 2);
        let bestCol = 0, bestRow = 0, bestD = Infinity;
        for (let c = c0; c <= c1; c++) {
          const stagger = ((c % 2) * HEX_VERT_SPACING) / 2;
          const rowApprox = (uy - HEX_HEIGHT / 2 - stagger) / HEX_VERT_SPACING;
          const r0 = Math.max(0, Math.floor(rowApprox) - 2);
          const r1 = Math.min(BOARD_ROWS - 1, Math.ceil(rowApprox) + 2);
          for (let r = r0; r <= r1; r++) {
            const cx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2;
            const cy = r * HEX_VERT_SPACING + stagger + HEX_HEIGHT / 2;
            const d = (ux - cx) ** 2 + (uy - cy) ** 2;
            if (d < bestD) { bestD = d; bestCol = c; bestRow = r; }
          }
        }
        return { col: bestCol, row: bestRow };
      };

      hitArea.on(
        "pointerdown",
        asPixiUnknownArgsPointerListener((e: PIXI.FederatedPointerEvent) => {
        if (e.button !== 0) return;
        const { col, row } = resolveHex(e.getLocalPosition(hitArea));
        const key = `${col},${row}`;
        const useMovePoolForPick =
          moveAdvanceOrPileInPickPool != null && moveAdvanceOrPileInPickPool.size > 0;
        const useChargePoolForPick =
          interactionPhase === "charge" &&
          mode === "chargePreview" &&
          chargeDestPoolRef?.current &&
          chargeDestPoolRef.current.size > 0;
        const isValid =
          clickableSet.has(key) ||
          (useMovePoolForPick && (moveAdvanceOrPileInPickPool?.has(key) ?? false)) ||
          (useChargePoolForPick && (chargeDestPoolRef?.current?.has(key) ?? false));
        if (isValid) {
          let destCol = col,
            destRow = row;
          if (
            useMovePoolForPick &&
            moveAdvanceOrPileInPickPool &&
            !moveAdvanceOrPileInPickPool.has(key)
          ) {
            let bestDist = Infinity;
            for (const k of moveAdvanceOrPileInPickPool) {
              const sep = k.indexOf(",");
              const cc = Number(k.substring(0, sep));
              const cr = Number(k.substring(sep + 1));
              const d = (cc - col) * (cc - col) + (cr - row) * (cr - row);
              if (d < bestDist) {
                bestDist = d;
                destCol = cc;
                destRow = cr;
              }
            }
          } else if (
            useChargePoolForPick &&
            chargeDestPoolRef?.current &&
            !chargeDestPoolRef.current.has(key)
          ) {
            let bestDist = Infinity;
            for (const k of chargeDestPoolRef.current) {
              const sep = k.indexOf(",");
              const cc = Number(k.substring(0, sep));
              const cr = Number(k.substring(sep + 1));
              const d = (cc - col) * (cc - col) + (cr - row) * (cr - row);
              if (d < bestDist) {
                bestDist = d;
                destCol = cc;
                destRow = cr;
              }
            }
          }
          window.dispatchEvent(
            new CustomEvent("boardHexClick", {
              detail: { col: destCol, row: destRow, phase: interactionPhase, mode, selectedUnitId },
            })
          );
        }
      }
    ));

      let lastHoverCol = -1, lastHoverRow = -1;
      hitArea.on(
        "pointermove",
        asPixiUnknownArgsPointerListener((e: PIXI.FederatedPointerEvent) => {
        const localPos = e.getLocalPosition(hitArea);
        const { col, row } = resolveHex(localPos);
        const hexChanged = col !== lastHoverCol || row !== lastHoverRow;
        if (hexChanged) {
          lastHoverCol = col;
          lastHoverRow = row;
        }
        window.dispatchEvent(
          new CustomEvent("boardHexHover", {
            detail: { col, row, pixelX: localPos.x, pixelY: localPos.y, hexChanged },
          })
        );
      }
    ));

      highlightContainer.addChild(hitArea);
    }

    if (
      fightEngagementRing &&
      Number.isFinite(fightEngagementRing.rOuter) &&
      fightEngagementRing.rOuter > 1 &&
      Number.isFinite(fightEngagementRing.cx) &&
      Number.isFinite(fightEngagementRing.cy)
    ) {
      highlightContainer.addChild(
        createFightEngagementRingSmoothOutline(
          fightEngagementRing.cx,
          fightEngagementRing.cy,
          fightEngagementRing.rOuter,
          ATTACK_COLOR,
        ),
      );
    }

    // Caller (BoardPvp) handles stage cleanup. drawBoard only adds containers.

    if (!reuseStatic) {
      app.stage.addChildAt(baseHexContainer, 0);
    }
    app.stage.addChild(highlightContainer);

    // Render wall segments as filled polygons.
    // Skip if reusing static layers (walls are already on stage).
    let wallsResult: PIXI.Container | null = null;
    if (!reuseStatic && boardConfig.walls && boardConfig.walls.length > 0) {
      const wallsContainer = new PIXI.Container();
      wallsContainer.name = "walls";

      const halfW = HEX_HEIGHT * 0.8;
      const wallTexturePath = boardConfig.display?.wall_texture?.trim() || "/textures/wall1.webp";
      const wallTextureAlpha =
        typeof boardConfig.display?.wall_texture_alpha === "number"
          ? boardConfig.display.wall_texture_alpha
          : 1.0;
      const wallTexture = PIXI.Texture.from(wallTexturePath);

      const toPixel = (col: number, row: number): [number, number] => [
        col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN,
        row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN,
      ];

      boardConfig.walls.forEach((wall) => {
        const [sx, sy] = toPixel(wall.start.col, wall.start.row);
        const [ex, ey] = toPixel(wall.end.col, wall.end.row);

        const dx = ex - sx, dy = ey - sy;
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len < 0.01) return;
        const nx = (-dy / len) * halfW;
        const ny = (dx / len) * halfW;

        const g = new PIXI.Graphics();
        g.beginTextureFill({
          texture: wallTexture,
          alpha: wallTextureAlpha,
        });
        g.drawCircle(sx, sy, halfW);
        g.drawCircle(ex, ey, halfW);
        g.drawPolygon([
          sx + nx, sy + ny,
          ex + nx, ey + ny,
          ex - nx, ey - ny,
          sx - nx, sy - ny,
        ]);
        g.endFill();
        wallsContainer.addChild(g);
      });

      app.stage.addChild(wallsContainer);
      wallsResult = wallsContainer;
    }

    return { baseHexContainer, wallsContainer: wallsResult };
  } catch (error) {
    console.error("❌ Error drawing board:", error);
    throw error;
  }
};
