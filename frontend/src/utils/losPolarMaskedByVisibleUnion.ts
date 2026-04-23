/**
 * Preview LoS / tir sur le plateau : **uniquement** l’union hex lissée (Chaikin),
 * sans enveloppe polaire ni traits internes — bord = contour métier des hex visibles.
 */
import * as PIXI from "pixi.js-legacy";
import type { HexUnionMaskLayout } from "./hexUnionBoundaryPolygon";
import {
  appendLosPreviewSmoothHexUnionFillOrThrow,
  configureLosPreviewOverlaySoftEdges,
} from "./smoothHexLosUnionFill";

function destroyAllChildren(root: PIXI.Container): void {
  const n = root.children.length;
  for (let i = n - 1; i >= 0; i--) {
    const c = root.removeChildAt(i);
    c.destroy({ children: true });
  }
}

/**
 * Remplace le contenu de ``root`` : remplissage union lissée « tout visible » puis couvert par-dessus.
 */
export function mountLosPolarClippedByVisibleUnion(
  root: PIXI.Container,
  allVisibleCells: ReadonlyArray<{ col: number; row: number }>,
  coverCells: ReadonlyArray<{ col: number; row: number }>,
  layout: HexUnionMaskLayout,
  clearColor: number,
  clearAlpha: number,
  coverColor: number,
  coverAlpha: number,
  /** Pour ``filterArea`` + flou léger sur les bords alpha (même principe que le masque move). */
  renderer?: PIXI.IRenderer | PIXI.Renderer | null,
): void {
  destroyAllChildren(root);

  const base = new PIXI.Graphics();
  base.name = "los-smooth-union-all";
  appendLosPreviewSmoothHexUnionFillOrThrow(base, allVisibleCells, layout, clearColor, clearAlpha);
  root.addChild(base);

  if (coverCells.length > 0) {
    const cov = new PIXI.Graphics();
    cov.name = "los-smooth-union-cover";
    appendLosPreviewSmoothHexUnionFillOrThrow(cov, coverCells, layout, coverColor, coverAlpha);
    root.addChild(cov);
  }

  configureLosPreviewOverlaySoftEdges(root, renderer ?? null);
}
