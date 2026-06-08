/**
 * Dessin du badge "a fui" (units_fled) en VECTORIEL — une silhouette de coureur,
 * nette à n'importe quelle taille (contrairement à l'emoji 🏃 qui ne se rend pas en petit).
 * Même principe que drawHiddenEyeBadge : cercle de fond + icône dessinée dans un PIXI.Graphics.
 *
 * `(cx, cy)` = centre du badge dans le repère local de `g`. `r` = rayon du cercle de fond.
 * Repère écran : y vers le bas. Le coureur est penché et court vers la droite.
 */
import type * as PIXI from "pixi.js-legacy";

export function drawFledRunnerBadge(
  g: PIXI.Graphics,
  cx: number,
  cy: number,
  r: number
): void {
  // Cercle de fond vert avec liseré noir (tracé centré sur le bord → on
  // réduit le rayon de la moitié de l'épaisseur pour tout garder dans r).
  const bw = Math.max(1.0, r * 0.12);
  g.lineStyle(bw, 0x000000, 1);
  g.beginFill(0x3fa32a, 1);
  g.drawCircle(cx, cy, r - bw / 2);
  g.endFill();

  const white = 0xffffff;
  // Helpers : points relatifs au centre, exprimés en fraction de r.
  const px = (fx: number) => cx + fx * r;
  const py = (fy: number) => cy + fy * r;

  // Flèche bloc pleine pointant vers la gauche (repli). Contour parcouru
  // depuis la pointe : tête triangulaire (gauche) puis tige rectangulaire (droite).
  g.lineStyle(0);
  g.beginFill(white, 1);
  g.drawPolygon([
    px(-0.62), py(0.0),    // pointe (gauche)
    px(-0.16), py(-0.46),  // coin haut de la tête
    px(-0.16), py(-0.2),   // épaule haute (début tige)
    px(0.56), py(-0.2),    // coin haut-droit de la tige
    px(0.56), py(0.2),     // coin bas-droit de la tige
    px(-0.16), py(0.2),    // épaule basse
    px(-0.16), py(0.46),   // coin bas de la tête
  ]);
  g.endFill();
}
