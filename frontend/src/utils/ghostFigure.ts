// Fantôme d'une figurine (socle coloré + portrait), centré en (0,0) — la SEULE construction
// des figurines qui suivent le curseur : move preview d'escouade, ghost per-fig move, ghost
// per-fig charge, bloc de sélection rectangle. Le socle porte le nom ``hover-base-shape`` pour
// que le pivot molette le retrouve (getChildByName) sans reconstruire le container.
import * as PIXI from "pixi.js-legacy";
import { orientationStepToRadians } from "../constants/gameConfig";
import type { Unit } from "../types/game";
import { resolveBaseSizeForUnitDisplay } from "./hexFootprint";
import {
  getNonRoundBasePixelLayout,
  getNonRoundIconRadius,
  getSquareCornerRadiusPx,
} from "./unitBaseDisplay";

export const GHOST_BASE_SHAPE_NAME = "hover-base-shape";

export type GhostFigure = {
  container: PIXI.Container;
  /** Socle (nommé ``hover-base-shape``) — pivotable par le caller. */
  base: PIXI.Graphics;
};

/**
 * Construit le fantôme d'une figurine dans un container neuf (non attaché, alpha 1).
 *
 * @param effectiveUnit unité portant le visuel de LA figurine (escouade hétérogène : unité de base
 *   fusionnée avec ``models_meta_by_model[mid]``) — forme/taille de socle, icône, échelle.
 * @param player joueur propriétaire (couleur du socle, variante ``_red`` de l'icône).
 * @param hexRadius rayon d'hex en pixels.
 * @param orientationStep pas d'orientation du socle ; appliqué seulement aux socles non ronds.
 */
export function buildGhostFigure(
  effectiveUnit: Unit,
  player: number,
  hexRadius: number,
  orientationStep: number | undefined
): GhostFigure {
  const container = new PIXI.Container();
  const nr = getNonRoundBasePixelLayout(effectiveUnit, hexRadius);
  const bd = resolveBaseSizeForUnitDisplay(effectiveUnit);
  const defaultIconDiam =
    bd > 1 ? bd * 1.5 * hexRadius : hexRadius * (effectiveUnit.ICON_SCALE ?? 1.0);

  const base = new PIXI.Graphics();
  base.name = GHOST_BASE_SHAPE_NAME;
  base.beginFill(player === 1 ? 0x1d4ed8 : 0x882222, 0.7);
  if (nr) {
    if (nr.kind === "oval") base.drawEllipse(0, 0, nr.outerRx, nr.outerRy);
    else
      base.drawRoundedRect(
        -nr.squareHalf,
        -nr.squareHalf,
        nr.squareSide,
        nr.squareSide,
        getSquareCornerRadiusPx()
      );
    if (orientationStep !== undefined) base.rotation = orientationStepToRadians(orientationStep);
  } else {
    base.drawCircle(0, 0, defaultIconDiam / 2);
  }
  base.endFill();
  container.addChild(base);

  if (effectiveUnit.ICON) {
    const iconPath =
      player === 2 ? effectiveUnit.ICON.replace(".webp", "_red.webp") : effectiveUnit.ICON;
    const sprite = new PIXI.Sprite(PIXI.Texture.from(iconPath));
    sprite.anchor.set(0.5);
    const nonRoundIconR = getNonRoundIconRadius(effectiveUnit, hexRadius);
    const iconDiam = nonRoundIconR != null ? nonRoundIconR * 2 : defaultIconDiam;
    sprite.width = iconDiam;
    sprite.height = iconDiam;
    if (nonRoundIconR != null) {
      const maskG = new PIXI.Graphics();
      maskG.beginFill(0xffffff);
      maskG.drawCircle(0, 0, nonRoundIconR);
      maskG.endFill();
      sprite.mask = maskG;
      container.addChild(maskG);
    }
    container.addChild(sprite);
  }
  return { container, base };
}
