/**
 * Dessin de l'icône "œil barré" (badge "caché", rule 13.09) dans un PIXI.Graphics.
 * Source unique partagée par UnitRenderer.renderHiddenBadge (figs au repos / plan) et le
 * ghost per-fig de BoardPvp (fig en cours de déplacement) → un seul endroit à maintenir.
 *
 * `(badgeX, badgeY)` = centre du badge dans le repère local de `g`. `r` = rayon du corps.
 */
import type * as PIXI from "pixi.js-legacy";

/**
 * Fond circulaire du badge numérique de detection range (15" ou 12").
 * Dessine uniquement l'anneau + disque fond — le texte est ajouté par l'appelant
 * (UnitRenderer) qui dispose d'un import PIXI runtime pour `new PIXI.Text`.
 */
export function drawDetectionNumberBadgeBackground(
  g: PIXI.Graphics,
  badgeX: number,
  badgeY: number,
  r: number
): void {
  g.lineStyle(0);
  g.beginFill(0x000000, 1);
  g.drawCircle(badgeX, badgeY, r + 1);
  g.endFill();
  g.beginFill(0x000000, 0.9);
  g.lineStyle(1, 0xb0b0b0, 1);
  g.drawCircle(badgeX, badgeY, r);
  g.endFill();
  g.lineStyle(0);
}

export function drawHiddenEyeBadge(
  g: PIXI.Graphics,
  badgeX: number,
  badgeY: number,
  r: number,
  eyeColor: number = 0xc8c8c8
): void {
  // Anneau noir externe pour détacher le badge du plateau.
  g.lineStyle(0);
  g.beginFill(0x000000, 1);
  g.drawCircle(badgeX, badgeY, r + 1);
  g.endFill();
  // Corps du badge (noir, bord gris clair).
  g.beginFill(0x000000, 0.9);
  g.lineStyle(1, 0xb0b0b0, 1);
  g.drawCircle(badgeX, badgeY, r);
  g.endFill();
  // Icône "visibility off" → gris clair = couvert ; rouge = caché trop loin (hors detection range).
  const ew = r * 0.82;
  const eh = r * 0.52;
  const lw = Math.max(0.8, r * 0.15);
  // Contour de l'œil en amande.
  g.lineStyle(lw, eyeColor, 1);
  g.moveTo(badgeX - ew, badgeY);
  g.quadraticCurveTo(badgeX, badgeY - eh, badgeX + ew, badgeY);
  g.quadraticCurveTo(badgeX, badgeY + eh, badgeX - ew, badgeY);
  // Anneau de l'iris.
  g.drawCircle(badgeX, badgeY, r * 0.26);
  // Barre diagonale : sous-trait noir pour créer le creux, trait clair par-dessus.
  const s = r * 0.82;
  g.lineStyle(lw * 2, 0x000000, 1);
  g.moveTo(badgeX - s, badgeY - s);
  g.lineTo(badgeX + s, badgeY + s);
  g.lineStyle(lw, eyeColor, 1);
  g.moveTo(badgeX - s, badgeY - s);
  g.lineTo(badgeX + s, badgeY + s);
}
