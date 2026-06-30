/**
 * Badge-statut de mouvement (board PIXI) — dessin vectoriel, net à n'importe quel zoom et
 * cohérent avec les badges du panneau (UnitStatusBadges.tsx) : mêmes symboles, mêmes couleurs.
 * Un seul badge à la fois, choisi par priorité (charge > fall-back > advance > move > stationary).
 *
 * `(cx, cy)` = centre du badge dans le repère local de `g`. `r` = rayon du cercle de fond.
 */
import type * as PIXI from "pixi.js-legacy";

export type MoveStatusKind = "move" | "advance" | "charge" | "fallback" | "stationary";

/** Chevron rouge pointant vers le bas sur fond jaune — unité démoralisée (battle-shock). */
export function drawBattleShockBadge(g: PIXI.Graphics, cx: number, cy: number, r: number): void {
  const bw = Math.max(1, r * 0.15);
  g.lineStyle(bw, 0x991b1b, 1);
  g.beginFill(0xf4c81f, 1);
  g.drawCircle(cx, cy, r - bw / 2);
  g.endFill();

  const lw = Math.max(1.5, r * 0.28);
  g.lineStyle(lw, 0x991b1b, 1);
  g.moveTo(cx - r * 0.54, cy - r * 0.22);
  g.lineTo(cx, cy + r * 0.34);
  g.lineTo(cx + r * 0.54, cy - r * 0.22);
}

const PALETTE: Record<MoveStatusKind, { fill: number; border: number }> = {
  move: { fill: 0x3fa32a, border: 0x1f5214 },
  advance: { fill: 0xea580c, border: 0x7c2d12 },
  charge: { fill: 0x7c3aed, border: 0x3b1a78 },
  fallback: { fill: 0xf4c81f, border: 0x8a6d00 },
  stationary: { fill: 0x808080, border: 0x3f3f3f },
};

export function drawMoveStatusBadge(
  g: PIXI.Graphics,
  cx: number,
  cy: number,
  r: number,
  kind: MoveStatusKind
): void {
  const { fill, border } = PALETTE[kind];
  const bw = Math.max(1, r * 0.15);
  // Cercle de fond coloré + liseré foncé.
  g.lineStyle(bw, border, 1);
  g.beginFill(fill, 1);
  g.drawCircle(cx, cy, r - bw / 2);
  g.endFill();

  const white = 0xffffff;
  const px = (fx: number) => cx + fx * r;
  const py = (fy: number) => cy + fy * r;

  if (kind === "stationary") {
    // Carré (stop) blanc.
    const h = r * 0.4;
    g.lineStyle(0);
    g.beginFill(white, 1);
    g.drawRoundedRect(cx - h, cy - h, h * 2, h * 2, r * 0.12);
    g.endFill();
    return;
  }

  // Chevron(s) blancs. dir = +1 → pointe à droite ; -1 → pointe à gauche.
  const lw = Math.max(1.5, r * 0.24);
  const drawChevron = (ox: number, dir: 1 | -1): void => {
    g.lineStyle(lw, white, 1);
    g.moveTo(px(ox - dir * 0.22), py(-0.48));
    g.lineTo(px(ox + dir * 0.22), py(0));
    g.lineTo(px(ox - dir * 0.22), py(0.48));
  };

  if (kind === "fallback") {
    drawChevron(0.05, -1);
  } else if (kind === "move") {
    drawChevron(-0.05, 1);
  } else {
    // advance / charge : double chevron vers la droite.
    drawChevron(-0.2, 1);
    drawChevron(0.24, 1);
  }
}
