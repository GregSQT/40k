/**
 * Remplissage LoS / tir : union d’hex → Chaikin → `Graphics` (même principe que le masque move).
 * **Aucun repli** : si la topologie n’est pas convertible en polygone, on lève une erreur.
 */
import * as PIXI from "pixi.js-legacy";
import {
  tryBuildHexUnionMaskPolygons,
  type HexUnionMaskLayout,
} from "./hexUnionBoundaryPolygon";
import { smoothMaskLoopsForRender } from "./polygonSmooth";

/** Aligné sur le masque move (5) + une passe pour lisser les longs segments de bord LoS. */
export const LOS_PREVIEW_SMOOTH_HEX_UNION_CHAIKIN_ITERATIONS = 6;

const LOS_PREVIEW_CHAIKIN_MAX_VERTS = 180_000;

/** Flou très léger sur tout l’overlay LoS : adoucit le crénelage raster (bords alpha), un peu comme le blur du masque move. */
const LOS_PREVIEW_OVERLAY_BLUR_STRENGTH = 1.55;
const LOS_PREVIEW_OVERLAY_BLUR_QUALITY = 3;
const LOS_PREVIEW_OVERLAY_BLUR_RESOLUTION = 2;

const losPreviewSmoothOpts = {
  maxVertsAfterOneChaikinStep: LOS_PREVIEW_CHAIKIN_MAX_VERTS,
} as const;

function signedPolygonAreaFlat(flat: number[]): number {
  const n = flat.length / 2;
  if (n < 3) return 0;
  let a = 0;
  for (let i = 0; i < n; i++) {
    const i0 = i * 2;
    const i1 = ((i + 1) % n) * 2;
    a += flat[i0]! * flat[i1 + 1]! - flat[i1]! * flat[i0 + 1]!;
  }
  return a / 2;
}

function loopCentroidFlat(flat: number[]): [number, number] {
  let sx = 0;
  let sy = 0;
  const n = flat.length / 2;
  if (n === 0) return [0, 0];
  for (let i = 0; i < flat.length; i += 2) {
    sx += flat[i]!;
    sy += flat[i + 1]!;
  }
  return [sx / n, sy / n];
}

function pointInPolygonFlat(x: number, y: number, flat: number[]): boolean {
  let inside = false;
  const n = flat.length / 2;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = flat[i * 2]!;
    const yi = flat[i * 2 + 1]!;
    const xj = flat[j * 2]!;
    const yj = flat[j * 2 + 1]!;
    if ((yi > y) !== (yj > y)) {
      const xInt = ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi;
      if (x < xInt) inside = !inside;
    }
  }
  return inside;
}

function appendUnionFillFromSmoothedLoops(
  gfx: PIXI.Graphics,
  loops: number[][],
  fillColor: number,
  fillAlpha: number,
): void {
  const valid = loops.filter((l) => l.length >= 6);
  if (valid.length === 0) return;

  const meta = valid.map((flat) => {
    const [cx, cy] = loopCentroidFlat(flat);
    return { flat, cx, cy, absA: Math.abs(signedPolygonAreaFlat(flat)) };
  });

  const used = new Set<number>();
  while (used.size < meta.length) {
    let bestI = -1;
    let bestAbs = -1;
    for (let i = 0; i < meta.length; i++) {
      if (used.has(i)) continue;
      if (meta[i]!.absA > bestAbs) {
        bestAbs = meta[i]!.absA;
        bestI = i;
      }
    }
    if (bestI < 0) break;
    const root = meta[bestI]!;
    used.add(bestI);

    gfx.beginFill(fillColor, fillAlpha);
    gfx.drawPolygon(root.flat);
    for (let j = 0; j < meta.length; j++) {
      if (used.has(j) || j === bestI) continue;
      const o = meta[j]!;
      if (pointInPolygonFlat(o.cx, o.cy, root.flat)) {
        gfx.beginHole();
        gfx.drawPolygon(o.flat);
        gfx.endHole();
        used.add(j);
      }
    }
    gfx.endFill();
  }
}

/**
 * Ajoute sur ``gfx`` le remplissage de l’union lissée des cellules (sans ``clear``).
 * @throws si ``cells`` non vide et union / lissage impossible (pas de repli disque).
 */
export function appendLosPreviewSmoothHexUnionFillOrThrow(
  gfx: PIXI.Graphics,
  cells: ReadonlyArray<{ col: number; row: number }>,
  layout: HexUnionMaskLayout,
  fillColor: number,
  fillAlpha: number,
  chaikinIterations: number = LOS_PREVIEW_SMOOTH_HEX_UNION_CHAIKIN_ITERATIONS,
): void {
  if (cells.length === 0) return;
  const pool = new Set<string>();
  for (const c of cells) pool.add(`${c.col},${c.row}`);
  const poly = tryBuildHexUnionMaskPolygons(pool, layout);
  if (!poly) {
    throw new Error(
      "[appendLosPreviewSmoothHexUnionFillOrThrow] tryBuildHexUnionMaskPolygons a retourné null " +
        `(cellules=${cells.length}). Pas de repli : corriger la topologie ou le layout.`,
    );
  }
  const prep = smoothMaskLoopsForRender(
    poly.loops,
    chaikinIterations,
    losPreviewSmoothOpts,
  );
  const validLoops = prep.smoothed.filter((l) => l.length >= 6);
  if (validLoops.length === 0) {
    throw new Error(
      "[appendLosPreviewSmoothHexUnionFillOrThrow] aucune boucle valide après Chaikin " +
        `(boucles brutes=${poly.loops.length}). Pas de repli.`,
    );
  }
  appendUnionFillFromSmoothedLoops(gfx, validLoops, fillColor, fillAlpha);
}

/**
 * Applique un léger ``BlurFilter`` + ``filterArea`` plein écran pour éviter la coupe des bords,
 * et ``roundPixels = false`` pour le sous-pixel sur les contours lissés.
 */
export function configureLosPreviewOverlaySoftEdges(
  obj: PIXI.DisplayObject,
  renderer: PIXI.IRenderer | PIXI.Renderer | null,
): void {
  obj.roundPixels = false;
  const blur = new PIXI.BlurFilter(
    LOS_PREVIEW_OVERLAY_BLUR_STRENGTH,
    LOS_PREVIEW_OVERLAY_BLUR_QUALITY,
  );
  blur.resolution = LOS_PREVIEW_OVERLAY_BLUR_RESOLUTION;
  blur.autoFit = true;
  obj.filters = [blur];
  const w = renderer && "width" in renderer && Number.isFinite(renderer.width) ? renderer.width : 4096;
  const h = renderer && "height" in renderer && Number.isFinite(renderer.height) ? renderer.height : 4096;
  obj.filterArea = new PIXI.Rectangle(0, 0, w, h);
}
