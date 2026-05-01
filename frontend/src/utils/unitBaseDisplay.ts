/**
 * Métriques d’affichage token (socle non rond + chrome HP / overlays).
 * Aligné sur UnitRenderer : demi-pas horizontal = 1.5 * HEX_RADIUS par « diamètre hex ».
 */

import type { Unit } from "../types/game";
import { resolveBaseSizeForUnitDisplay } from "./hexFootprint";

/** Réduction légère pour laisser respirer le trait de bordure socle / portrait. */
const ICON_INSET = 0.92;

/** Rayon d’angle du carré (px), purement visuel. */
const SQUARE_CORNER_RADIUS_PX = 4;

export type NonRoundBaseKind = "oval" | "square";

export interface NonRoundBasePixelLayout {
  kind: NonRoundBaseKind;
  /** drawEllipse(cx, cy, halfWidth, halfHeight) — PIXI */
  outerRx: number;
  outerRy: number;
  /** Demi-côté carré (px), centre au jeton */
  squareHalf: number;
  /** Côté carré (px) */
  squareSide: number;
  /** Rayon du disque portrait (rond inscrit dans la dimension étroite) */
  iconRadius: number;
  /** Centre → bord haut du socle (barre PV, icônes action) */
  topExtentY: number;
  /** Anneau éligibilité / encadrement grossier */
  boundingRadius: number;
}

function isOvalUnit(unit: Unit): boolean {
  return unit.BASE_SHAPE === "oval" && Array.isArray(unit.BASE_SIZE) && unit.BASE_SIZE.length >= 2;
}

function isLargeSquareUnit(unit: Unit): boolean {
  return unit.BASE_SHAPE === "square" && typeof unit.BASE_SIZE === "number" && unit.BASE_SIZE > 1;
}

/**
 * Socle ovale ou carré multi-hex : métriques pixel. Sinon ``null`` (rendu rond classique).
 */
export function getNonRoundBasePixelLayout(unit: Unit, HEX_RADIUS: number): NonRoundBasePixelLayout | null {
  if (isOvalUnit(unit)) {
    const bs = unit.BASE_SIZE as [number, number];
    const M = Number(bs[0]);
    const N = Number(bs[1]);
    if (!Number.isFinite(M) || !Number.isFinite(N)) {
      return null;
    }
    const outerRx = (M / 2) * 1.5 * HEX_RADIUS;
    const outerRy = (N / 2) * 1.5 * HEX_RADIUS;
    const iconRadius = Math.min(outerRx, outerRy) * ICON_INSET;
    return {
      kind: "oval",
      outerRx,
      outerRy,
      squareHalf: 0,
      squareSide: 0,
      iconRadius,
      topExtentY: outerRy,
      boundingRadius: Math.max(outerRx, outerRy),
    };
  }
  if (isLargeSquareUnit(unit)) {
    const d = resolveBaseSizeForUnitDisplay(unit);
    const side = d * 1.5 * HEX_RADIUS;
    const half = side / 2;
    const iconRadius = half * ICON_INSET;
    return {
      kind: "square",
      outerRx: half,
      outerRy: half,
      squareHalf: half,
      squareSide: side,
      iconRadius,
      topExtentY: half,
      boundingRadius: half * Math.SQRT2,
    };
  }
  return null;
}

export function getSquareCornerRadiusPx(): number {
  return SQUARE_CORNER_RADIUS_PX;
}

/**
 * Position verticale du haut du token (distance centre → bord haut), pour barre PV / overlays.
 */
export function getUnitTokenTopExtentY(
  unit: Unit,
  HEX_RADIUS: number,
  HEX_HORIZ_SPACING: number,
  UNIT_CIRCLE_RADIUS_RATIO: number,
): number {
  const nr = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
  if (nr) {
    return nr.topExtentY;
  }
  const displayBase = resolveBaseSizeForUnitDisplay(unit);
  if (displayBase > 1) {
    return (displayBase / 2) * HEX_HORIZ_SPACING;
  }
  return HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;
}

/**
 * Base multiplicateur largeur barre PV (même sémantique qu’avant : ``r`` grand rond, ou ``HEX_RADIUS*scale`` petit rond).
 */
export function getHpBarWidthBase(
  unit: Unit,
  HEX_RADIUS: number,
  HEX_HORIZ_SPACING: number,
  unitIconScale: number,
): number {
  const nr = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
  if (nr) {
    return Math.max(nr.outerRx, nr.outerRy);
  }
  const displayBase = resolveBaseSizeForUnitDisplay(unit);
  if (displayBase > 1) {
    return (displayBase / 2) * HEX_HORIZ_SPACING;
  }
  return HEX_RADIUS * unitIconScale;
}

/**
 * Rayon du portrait rond (masque), pour ovale / carré ; ``null`` si rendu rond intégral (logique existante).
 */
export function getNonRoundIconRadius(unit: Unit, HEX_RADIUS: number): number | null {
  const nr = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
  return nr ? nr.iconRadius : null;
}
