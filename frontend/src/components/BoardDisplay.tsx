// frontend/src/components/BoardDisplay.tsx
import type React from "react";
import * as PIXI from "pixi.js-legacy";

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
  /** Ancres charge (même sémantique que ``moveDestPoolRef``) — preview multi-base comme la phase move. */
  chargeDestPoolRef?: React.RefObject<Set<string>>;
  selectedUnitBaseSize?: number;
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
}

export interface DrawBoardResult {
  baseHexContainer: PIXI.Container;
  wallsContainer: PIXI.Container | null;
}

// Helper functions from Board.tsx
function hexCorner(cx: number, cy: number, size: number, i: number) {
  const angle_deg = 60 * i;
  const angle_rad = (Math.PI / 180) * angle_deg;
  return [cx + size * Math.cos(angle_rad), cy + size * Math.sin(angle_rad)];
}

function getHexPolygonPoints(cx: number, cy: number, size: number) {
  return Array.from({ length: 6 }, (_, i) => hexCorner(cx, cy, size, i)).flat();
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
    if (inside(shuffled[n - 1]!, D, EPS)) {
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
 * Phase move, unité multi-base sur grand plateau : pool de centres → disques d’empreinte →
 * `RenderTexture` 1:1 → sprite (même code qu’historiquement).
 */
function addFootprintHighlightSprite(
  app: PIXI.Application,
  highlightContainer: PIXI.Container,
  gfx: PIXI.Graphics,
  alpha: number,
  displayName: string
): void {
  const bounds = gfx.getBounds();
  if (bounds.width <= 0 || bounds.height <= 0) {
    gfx.destroy();
    return;
  }
  const rt = PIXI.RenderTexture.create({ width: bounds.width, height: bounds.height });
  gfx.position.set(-bounds.x, -bounds.y);
  app.renderer.render(gfx, { renderTexture: rt });
  gfx.destroy();
  const sprite = new PIXI.Sprite(rt);
  sprite.name = displayName;
  sprite.position.set(bounds.x, bounds.y);
  sprite.alpha = alpha;
  highlightContainer.addChild(sprite);
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
    const CHARGE_COLOR = parseColor(boardConfig.colors.charge!);
    const WALL_COLOR = parseColor(boardConfig.colors.wall!);
    /** Hex destinations fin de charge (legacy small board uses 0x9f7aea — do not use ``colors.charge`` here: that key is orange UI / bordures). */
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
      showHexCoordinates = false,
      objectiveControl = {},
      moveDestPoolRef,
      chargeDestPoolRef,
      selectedUnitBaseSize,
      losDebugShowRatio = false,
      losDebugRatioByHex = {},
      losDebugCoverRatio = 0,
      losDebugVisibilityMinRatio = 0,
      chargeEngagementHalo,
      fightEngagementRing,
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

    // Pre-compute wallHexSet
    const wallHexSet = new Set<string>(
      (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
    );

    const IS_LARGE_BOARD = BOARD_COLS * BOARD_ROWS > 10000;

    const cachedStaticBoard = options?.cachedStaticBoard ?? null;
    const reuseStatic = IS_LARGE_BOARD && cachedStaticBoard !== null;
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

    if (IS_LARGE_BOARD) {
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

      // On large boards, skip drawing huge *move* highlight arrays (solid blob); hover validates.
      // Charge destination pools can exceed 500 on Board×10 (max charge roll in sub-hex) — still draw.
      const LARGE_POOL_THRESHOLD = 500;

      const useAdvanceMovePoolLikeMove =
        interactionPhase === "shoot" && mode === "advancePreview";
      const usePileInPoolLikeMove =
        interactionPhase === "fight" &&
        (mode === "pileInPreview" || mode === "consolidationPreview");
      // Pile in : zone rouge (empreinte moteur) — comme move_preview_footprint_zone en forme,
      // pas seulement des disques aux ancres ; on dessine via ``availableCells`` (override).
      const useLargeBoardMoveDestPoolDraw =
        (interactionPhase === "move" || useAdvanceMovePoolLikeMove) &&
        selectedUnitBaseSize &&
        selectedUnitBaseSize > 1 &&
        moveDestPoolRef?.current &&
        moveDestPoolRef.current.size > 0;

      const advanceZoneFillColor = ADVANCE_DESTINATION_HEX_FILL;
      const useConsolidationPreview = interactionPhase === "fight" && mode === "consolidationPreview";
      const availableCellsDrawColor = useAdvanceMovePoolLikeMove
        ? advanceZoneFillColor
        : usePileInPoolLikeMove
          ? useConsolidationPreview
            ? 0xff8c00
            : ATTACK_COLOR
          : HIGHLIGHT_COLOR;

      const useLargeBoardChargeDestPoolDraw =
        interactionPhase === "charge" &&
        (mode === "select" || mode === "chargePreview") &&
        selectedUnitBaseSize &&
        selectedUnitBaseSize > 1 &&
        chargeDestPoolRef?.current &&
        chargeDestPoolRef.current.size > 0;

      const drawGroup = (cells: Array<{ col: number; row: number }>, color: number, alpha: number, skipThreshold = true) => {
        if (cells.length === 0) return;
        if (skipThreshold && cells.length > LARGE_POOL_THRESHOLD) return;
        const batch = new PIXI.Graphics();
        batch.beginFill(color, alpha);
        for (const c of cells) {
          const hx = c.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const hy = c.row * HEX_VERT_SPACING + ((c.col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          batch.drawCircle(hx, hy, HEX_RADIUS);
        }
        batch.endFill();
        highlightContainer.addChild(batch);
      };

      if (useLargeBoardMoveDestPoolDraw) {
        // Draw icon-sized circles at valid CENTER positions only.
        // Each center was validated by BFS (full footprint clear of walls),
        // so the visual circles won't overlap walls.
        const footprintRadius = (selectedUnitBaseSize / 2) * HEX_HORIZ_SPACING;
        const gfx = new PIXI.Graphics();
        const poolFillColor = useAdvanceMovePoolLikeMove ? advanceZoneFillColor : HIGHLIGHT_COLOR;
        gfx.beginFill(poolFillColor, 1.0);
        for (const key of moveDestPoolRef.current) {
          const sep = key.indexOf(",");
          const c = Number(key.substring(0, sep));
          const r = Number(key.substring(sep + 1));
          const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const hy = r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          gfx.drawCircle(hx, hy, footprintRadius);
        }
        gfx.endFill();
        addFootprintHighlightSprite(
          app,
          highlightContainer,
          gfx,
          0.28,
          useAdvanceMovePoolLikeMove ? "advance-dest-pool" : "move-dest-pool",
        );
        addFootprintPoolSmoothOutlines(
          highlightContainer,
          moveDestPoolRef.current,
          footprintRadius,
          HEX_HORIZ_SPACING,
          HEX_WIDTH,
          HEX_HEIGHT,
          HEX_VERT_SPACING,
          MARGIN,
          poolFillColor,
        );
      } else {
        drawGroup(availableCells, availableCellsDrawColor, 0.4, false);
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
      if (useLargeBoardChargeDestPoolDraw && chargeDestPoolRef?.current) {
        const footprintRadius = (selectedUnitBaseSize / 2) * HEX_HORIZ_SPACING;
        const chargeGfx = new PIXI.Graphics();
        chargeGfx.beginFill(CHARGE_DESTINATION_HEX_FILL, 1.0);
        const chargePool = chargeDestPoolRef.current;
        for (const key of chargePool) {
          const sep = key.indexOf(",");
          const c = Number(key.substring(0, sep));
          const r = Number(key.substring(sep + 1));
          const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const hy = r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          chargeGfx.drawCircle(hx, hy, footprintRadius);
        }
        chargeGfx.endFill();
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
      drawGroup(advanceCells, ADVANCE_DESTINATION_HEX_FILL, 0.3, false);

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

      // Invisible interactive overlay for click detection (pixelToHex nearest-neighbor)
      const hasClickableContent =
        clickableSet.size > 0 ||
        ((interactionPhase === "move" ||
          useAdvanceMovePoolLikeMove ||
          usePileInPoolLikeMove) &&
          moveDestPoolRef?.current &&
          moveDestPoolRef.current.size > 0) ||
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

        hitArea.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
          if (e.button !== 0) return;
          const { col, row } = resolveHex(e.getLocalPosition(hitArea));
          const key = `${col},${row}`;
          const useMovePoolForPick =
            (interactionPhase === "move" ||
              useAdvanceMovePoolLikeMove ||
              usePileInPoolLikeMove) &&
            moveDestPoolRef?.current &&
            moveDestPoolRef.current.size > 0;
          const useChargePoolForPick =
            interactionPhase === "charge" &&
            mode === "chargePreview" &&
            chargeDestPoolRef?.current &&
            chargeDestPoolRef.current.size > 0;
          const isValid =
            clickableSet.has(key) ||
            (useMovePoolForPick && (moveDestPoolRef?.current?.has(key) ?? false)) ||
            (useChargePoolForPick && (chargeDestPoolRef?.current?.has(key) ?? false));
          if (isValid) {
            let destCol = col,
              destRow = row;
            if (useMovePoolForPick && moveDestPoolRef?.current && !moveDestPoolRef.current.has(key)) {
              let bestDist = Infinity;
              for (const k of moveDestPoolRef.current) {
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
        });

        let lastHoverCol = -1, lastHoverRow = -1;
        hitArea.on("pointermove", (e: PIXI.FederatedPointerEvent) => {
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
        });

        highlightContainer.addChild(hitArea);
      }
    } else {

    // Legacy small board: draw individual hex polygons
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        if (row === BOARD_ROWS - 1 && col % 2 === 1) {
          continue;
        }
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY =
          row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);

        // Check highlight states
        const isAvailable = availableCells.some((cell) => cell.col === col && cell.row === row);
        const isAttackable = attackCells.some((cell) => cell.col === col && cell.row === row);
        const isInCover = coverCells.some((cell) => cell.col === col && cell.row === row);
        // chargeCells come as [col, row] arrays from backend, not {col, row} objects
        const isChargeable = chargeCells.some((cell) => {
          if (Array.isArray(cell)) {
            return cell[0] === col && cell[1] === row;
          }
          return cell.col === col && cell.row === row;
        });

        // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Advance destinations (orange)
        const isAdvanceDestination = advanceCells.some(
          (cell) => cell.col === col && cell.row === row
        );

        // Check if this is a wall hex
        const isWallHex = wallHexSet.has(`${col},${row}`);

        // Create base hex (always present)
        const baseCell = new PIXI.Graphics();
        const isEven = (col + row) % 2 === 0;
        let cellColor = isEven
          ? parseColor(boardConfig.colors.cell_even)
          : parseColor(boardConfig.colors.cell_odd);

        // Override color for walls and objective zones
        if (isWallHex) {
          cellColor = WALL_COLOR;
        } else if (objectiveHexSet.has(`${col},${row}`)) {
          // Check if this objective hex is controlled by a player
          const hexKey = `${col},${row}`;
          const controller = objectiveControl[hexKey];
          if (controller === 1) {
            cellColor = OBJECTIVE_P0_COLOR; // Blue for Player 1
          } else if (controller === 2) {
            cellColor = OBJECTIVE_P1_COLOR; // Red for Player 2
          } else {
            cellColor = OBJECTIVE_NEUTRAL_COLOR; // Yellow/Orange for neutral/contested
          }
        }

        const isObjectiveHex = objectiveHexSet.has(`${col},${row}`);
        if (objectiveTexture && isObjectiveHex) {
          beginObjectiveFill(baseCell, objectiveTexture, cellColor, objectiveTextureAlpha);
        } else {
          baseCell.beginFill(cellColor, 1.0);
        }
        baseCell.lineStyle(1, parseColor(boardConfig.colors.cell_border), 0.8);
        baseCell.drawPolygon(points);
        baseCell.endFill();
        baseHexContainer.addChild(baseCell);

        if (losDebugShowRatio) {
          const losRatioValue = losDebugRatioByHex[`${col},${row}`];
          if (losRatioValue !== undefined) {
            if (typeof losRatioValue !== "number" || Number.isNaN(losRatioValue)) {
              throw new Error(`Invalid LoS debug ratio at ${col},${row}`);
            }
            if (
              typeof losDebugCoverRatio !== "number" ||
              Number.isNaN(losDebugCoverRatio) ||
              typeof losDebugVisibilityMinRatio !== "number" ||
              Number.isNaN(losDebugVisibilityMinRatio)
            ) {
              throw new Error("Invalid LoS debug thresholds in drawBoard options");
            }
            const ratioPercent = Math.round(losRatioValue * 100);
            const ratioColor =
              losRatioValue < losDebugVisibilityMinRatio
                ? 0x9ca3af
                : losRatioValue < losDebugCoverRatio
                  ? 0xf59e0b
                  : 0x86efac;
            const losRatioText = new PIXI.Text(`${ratioPercent}%`, {
              fontSize: 8,
              fill: ratioColor,
              fontWeight: "bold",
              stroke: 0x000000,
              strokeThickness: 2,
              align: "center",
            });
            losRatioText.anchor.set(0.5);
            losRatioText.position.set(centerX, centerY + (showHexCoordinates ? 13 : 0));
            baseHexContainer.addChild(losRatioText);
          }
        }

        // Add coordinate text when toggle is enabled
        if (showHexCoordinates) {
          const coordText = new PIXI.Text(`${col},${row}`, {
            fontSize: 8,
            fill: 0xffffff,
            align: "center",
          });
          coordText.anchor.set(0.5);
          coordText.position.set(centerX, centerY);
          baseHexContainer.addChild(coordText);
        }

        // Create highlight hex (only if needed) - NO INTERACTIONS
        if (isAdvanceDestination || isChargeable || isAttackable || isInCover || isAvailable) {
          const highlightCell = new PIXI.Graphics();

          // Shooting preview palette: used in shoot phase and movePreview confirm step
          const useShootingPreviewPalette = phase === "shoot" || mode === "movePreview";
          if (useShootingPreviewPalette) {
            if (
              (mode === "advancePreview" && isAvailable) ||
              isAdvanceDestination
            ) {
              highlightCell.beginFill(ADVANCE_DESTINATION_HEX_FILL, 0.5);
            } else if (isInCover) {
              // Vivid light blue for targets in cover
              highlightCell.beginFill(0x9ec5ff, 0.4);
            } else if (isAttackable) {
              // Vivid medium blue for clear line of sight (plus bleu, même luminosité)
              highlightCell.beginFill(0x4f8bff, 0.4);
            } else if (isChargeable) {
              // Charge destinations: use violet
              highlightCell.beginFill(0x9f7aea, 0.4);
            } else if (isAvailable) {
              highlightCell.beginFill(HIGHLIGHT_COLOR, 0.4);
            }
          } else {
            // Other phases keep existing colors
            if (isChargeable) {
              // Charge destinations: use violet
              highlightCell.beginFill(0x9f7aea, 0.5);
            } else if (isInCover) {
              highlightCell.beginFill(CHARGE_COLOR, 0.5);
            } else if (isAttackable) {
              highlightCell.beginFill(ATTACK_COLOR, 0.5);
            } else if (
              interactionPhase === "fight" &&
              mode === "consolidationPreview" &&
              isAvailable
            ) {
              highlightCell.beginFill(0xff8c00, 0.5);
            } else if (
              interactionPhase === "fight" &&
              mode === "pileInPreview" &&
              isAvailable
            ) {
              highlightCell.beginFill(ATTACK_COLOR, 0.5);
            } else if (isAvailable) {
              highlightCell.beginFill(HIGHLIGHT_COLOR, 0.5);
            }
          }

          highlightCell.drawPolygon(points);
          highlightCell.endFill();

          // Add click handlers for movement, charge, and advance hexes
          if (isAvailable || isChargeable || isAdvanceDestination) {
            highlightCell.eventMode = "static";
            highlightCell.cursor = "pointer";
            highlightCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) {
                // Left click only
                window.dispatchEvent(
                  new CustomEvent("boardHexClick", {
                    detail: { col, row, phase: interactionPhase, mode, selectedUnitId },
                  })
                );
              }
            });
          }

          highlightContainer.addChild(highlightCell);
        }
      }
    }
    } // end else (legacy small board)

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

      const halfW = IS_LARGE_BOARD ? HEX_HEIGHT * 0.8 : 1.5;
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
