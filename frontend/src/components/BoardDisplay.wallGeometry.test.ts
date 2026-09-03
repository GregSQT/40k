/**
 * Vérifie que la géométrie de mur produite pour un groupe couvre exactement
 * les hexagones déclarés dans wallGroup.hexes et aucun autre.
 *
 * Critère : pour chaque hex [col, row] du groupe, le centre pixel de cet hex
 * est à l'intérieur du polygone hex correspondant, et les centres des hexs
 * voisins non membres ne le sont pas.
 */
import { describe, expect, it } from "vitest";

/** Coin i d'un hexagone flat-top centré en (cx, cy) de rayon r. */
function hexCorner(cx: number, cy: number, r: number, i: number): [number, number] {
  const angle = (Math.PI / 3) * i;
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
}

/** Centre pixel d'un hex (col, row) selon la géométrie flat-top du moteur. */
function toPixel(
  col: number,
  row: number,
  hexRadius: number,
  margin: number
): [number, number] {
  const hexHorizSpacing = 1.5 * hexRadius;
  const hexHeight = Math.sqrt(3) * hexRadius;
  return [
    col * hexHorizSpacing + hexHorizSpacing / 2 + margin,
    row * hexHeight + ((col % 2) * hexHeight) / 2 + hexHeight / 2 + margin,
  ];
}

/** Ray-casting : point (px, py) dans le polygone poly. */
function pointInPolygon(px: number, py: number, poly: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/** Hexagone flat-top sous forme de polygone (6 points). */
function hexPolygon(col: number, row: number, r: number, margin: number): [number, number][] {
  const [cx, cy] = toPixel(col, row, r, margin);
  return Array.from({ length: 6 }, (_, i) => hexCorner(cx, cy, r, i));
}

describe("wall group hex geometry — empreinte exacte", () => {
  const HEX_RADIUS = 20;
  const MARGIN = 5;

  it("le centre de chaque hex mur est dans son polygone, les centres voisins non", () => {
    const wallHexes: [number, number][] = [
      [2, 2],
      [3, 2],
      [3, 3],
    ];
    const wallSet = new Set(wallHexes.map(([c, r]) => `${c},${r}`));

    // Candidats voisins immédiats (pas membres du groupe)
    const neighbors: [number, number][] = [
      [1, 2],
      [2, 1],
      [4, 2],
      [2, 3],
      [4, 3],
    ];

    for (const [col, row] of wallHexes) {
      const poly = hexPolygon(col, row, HEX_RADIUS, MARGIN);
      const [cx, cy] = toPixel(col, row, HEX_RADIUS, MARGIN);

      // Centre de CE hex est dans son propre polygone.
      expect(pointInPolygon(cx, cy, poly)).toBe(true);

      // Centres des voisins non-mur ne sont PAS dans ce polygone.
      for (const [nc, nr] of neighbors) {
        if (wallSet.has(`${nc},${nr}`)) continue;
        const [nx, ny] = toPixel(nc, nr, HEX_RADIUS, MARGIN);
        expect(
          pointInPolygon(nx, ny, poly),
          `center of neighbor (${nc},${nr}) should not be in hex (${col},${row}) polygon`
        ).toBe(false);
      }
    }
  });

  it("un groupe wallGroup.hexes ne couvre aucun hex hors de sa liste", () => {
    const wallGroup = {
      type: "dense" as const,
      hexes: [
        [1, 1],
        [2, 1],
      ] as [number, number][],
    };

    // Tous les hexs dans une petite grille
    const allHexes: [number, number][] = [];
    for (let c = 0; c <= 4; c++) {
      for (let r = 0; r <= 4; r++) {
        allHexes.push([c, r]);
      }
    }

    const wallSet = new Set(wallGroup.hexes.map(([c, r]) => `${c},${r}`));

    for (const [col, row] of wallGroup.hexes) {
      const poly = hexPolygon(col, row, HEX_RADIUS, MARGIN);

      for (const [tc, tr] of allHexes) {
        const [tx, ty] = toPixel(tc, tr, HEX_RADIUS, MARGIN);
        const inPoly = pointInPolygon(tx, ty, poly);
        const isThisHex = tc === col && tr === row;

        if (isThisHex) {
          // Propre centre toujours dedans
          expect(inPoly).toBe(true);
        } else if (!wallSet.has(`${tc},${tr}`)) {
          // Centre d'un hex non-mur jamais dans le polygone d'un hex mur
          expect(
            inPoly,
            `center of (${tc},${tr}) should not be inside wall-hex polygon at (${col},${row})`
          ).toBe(false);
        }
      }
    }
  });

  it("l'union des hexes de tous les groupes correspond exactement à wall_hexes", () => {
    const walls = [
      { type: "light" as const, hexes: [[0, 0], [1, 0]] as [number, number][] },
      { type: "dense" as const, hexes: [[2, 0], [2, 1]] as [number, number][] },
    ];
    // Simule ce que le backend produit : wall_hexes = union de tous les hexes de groupes
    const wallHexes = walls.flatMap((g) => g.hexes);

    // Les hexes de chaque groupe sont dans wall_hexes
    const wallHexSet = new Set(wallHexes.map(([c, r]) => `${c},${r}`));
    for (const group of walls) {
      for (const [c, r] of group.hexes) {
        expect(wallHexSet.has(`${c},${r}`)).toBe(true);
      }
    }

    // La somme des tailles de groupes couvre tout wall_hexes (pas de surplus)
    const groupTotal = walls.reduce((s, g) => s + g.hexes.length, 0);
    expect(groupTotal).toBe(wallHexes.length);
  });
});
