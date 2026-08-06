import { describe, expect, it } from "vitest";
import {
  buildWaaaghFangs,
  PULSE_GROUP_COUNT,
  WAAAGH_CRACKS_SEED,
  type WaaaghFangsGeometry,
} from "./waaaghBorder";

/** Plateau 44x60 au hex_radius de production (cf. config/board/44x60x5). */
const HEX_RADIUS = 8;
const COLS = 44 * 5;
const ROWS = 60 * 5;
const MARGIN = 30;
const BOARD_WIDTH = COLS * 1.5 * HEX_RADIUS + (1.5 * HEX_RADIUS) / 2 + 2 * MARGIN;
const BOARD_HEIGHT =
  ROWS * Math.sqrt(3) * HEX_RADIUS + (Math.sqrt(3) * HEX_RADIUS) / 2 + 2 * MARGIN;

const params = {
  boardWidth: BOARD_WIDTH,
  boardHeight: BOARD_HEIGHT,
  hexRadius: HEX_RADIUS,
  seed: WAAAGH_CRACKS_SEED,
};

/**
 * Les propriétés de sûreté sont vérifiées sur un ÉVENTAIL de graines et de dimensions, jamais sur
 * la seule graine de production : chaque plateau consomme un nombre différent de tirages, donc
 * produit un tirage effectif différent. Une propriété vraie pour `WAAAGH_CRACKS_SEED` sur le
 * 44x60 et fausse ailleurs est un défaut qui attend son plateau.
 */
const GEOMETRY_CASES = (() => {
  const boards = [
    { boardWidth: BOARD_WIDTH, boardHeight: BOARD_HEIGHT, hexRadius: HEX_RADIUS },
    { boardWidth: 900, boardHeight: 1400, hexRadius: 12 },
    { boardWidth: 500, boardHeight: 480, hexRadius: 6 },
  ];
  const cases: Array<{ boardWidth: number; boardHeight: number; hexRadius: number; seed: number }> =
    [];
  for (const board of boards) {
    for (let i = 0; i < 25; i += 1) {
      cases.push({ ...board, seed: WAAAGH_CRACKS_SEED + i * 7919 });
    }
  }
  return cases;
})();

function allPolygons(geometry: WaaaghFangsGeometry): number[][] {
  return geometry.groups.flatMap((group) => group.polygonsByLayer.flat());
}

function pointsOf(polygon: number[]): Array<{ x: number; y: number }> {
  const points: Array<{ x: number; y: number }> = [];
  for (let i = 0; i < polygon.length; i += 2) {
    points.push({ x: polygon[i], y: polygon[i + 1] });
  }
  return points;
}

/** Distance signée au bord le plus proche : positive vers l'intérieur du plateau. */
function depthInside(
  point: { x: number; y: number },
  board: { boardWidth: number; boardHeight: number }
): number {
  return Math.min(point.x, board.boardWidth - point.x, point.y, board.boardHeight - point.y);
}

describe("buildWaaaghFangs", () => {
  it("est déterministe : même graine et mêmes dimensions → géométrie identique", () => {
    // La denture est gravée une fois puis animée par alpha. Si elle variait d'un appel à l'autre,
    // toute reconstruction (zoom, remontage) redistribuerait les crocs sous les yeux du joueur.
    expect(buildWaaaghFangs(params)).toEqual(buildWaaaghFangs(params));
  });

  it("ancre les crocs sur le bord et les fait pointer vers l'intérieur", () => {
    // La forme entière tient dans cette propriété : une base SUR le bord, une pointe DANS le
    // plateau. Des crocs flottants ou tournés vers l'extérieur ne dessineraient pas une gueule.
    for (const geometryCase of GEOMETRY_CASES) {
      const geometry = buildWaaaghFangs(geometryCase);
      expect(geometry.fangCount).toBeGreaterThan(20);
      for (const polygon of allPolygons(geometry)) {
        const depths = pointsOf(polygon).map((point) => depthInside(point, geometryCase));
        // Base au contact du bord : au moins un point à la profondeur zéro, à la dilatation de
        // la couche près (le halo déborde vers l'extérieur, c'est voulu).
        expect(Math.min(...depths)).toBeLessThanOrEqual(geometry.maxOutwardBleed + 1e-9);
        // Pointe franchement à l'intérieur : un croc a une hauteur.
        expect(Math.max(...depths)).toBeGreaterThan(geometryCase.hexRadius);
      }
    }
  });

  it("borne le débordement hors plateau par la dilatation annoncée", () => {
    // `maxOutwardBleed` est ce que la couche la plus large mord au-delà du bord. S'il était
    // dépassé, la lueur baverait sur le cadre sans que rien ne le signale.
    for (const geometryCase of GEOMETRY_CASES) {
      const geometry = buildWaaaghFangs(geometryCase);
      // Un `expect` par point ferait expirer le test sans rien vérifier de plus : on agrège le
      // pire débordement des centaines de milliers de points, puis on l'assertionne une fois.
      let worst = Number.POSITIVE_INFINITY;
      for (const polygon of allPolygons(geometry)) {
        for (const point of pointsOf(polygon)) {
          const depth = depthInside(point, geometryCase);
          if (depth < worst) worst = depth;
        }
      }
      expect(worst).toBeGreaterThanOrEqual(-geometry.maxOutwardBleed - 1e-6);
    }
  });

  it("fait le tour complet : les quatre bords sont dentés, sans trou", () => {
    const geometry = buildWaaaghFangs(params);
    // Centre de chaque croc (couche du corps, la 3e), classé par bord d'appartenance.
    const bases = {
      top: [] as number[],
      bottom: [] as number[],
      left: [] as number[],
      right: [] as number[],
    };
    for (const group of geometry.groups) {
      for (const polygon of group.polygonsByLayer[2]) {
        const points = pointsOf(polygon);
        const anchor = points.reduce((best, point) =>
          depthInside(point, params) < depthInside(best, params) ? point : best
        );
        const distances = [anchor.y, BOARD_HEIGHT - anchor.y, anchor.x, BOARD_WIDTH - anchor.x];
        const nearest = distances.indexOf(Math.min(...distances));
        if (nearest === 0) bases.top.push(anchor.x);
        else if (nearest === 1) bases.bottom.push(anchor.x);
        else if (nearest === 2) bases.left.push(anchor.y);
        else bases.right.push(anchor.y);
      }
    }
    // Aucun bord vide, et aucun intervalle béant : le plus grand écart entre deux crocs voisins
    // reste de l'ordre du pas nominal. Sans ce contrôle, une denture ne couvrant qu'un demi-bord
    // passerait pour complète.
    const maxGap = HEX_RADIUS * 5 * 2.5;
    for (const [edge, positions] of Object.entries(bases)) {
      expect(positions.length, `bord ${edge} sans crocs`).toBeGreaterThan(10);
      const sorted = [...positions].sort((a, b) => a - b);
      const span = edge === "top" || edge === "bottom" ? BOARD_WIDTH : BOARD_HEIGHT;
      let previous = 0;
      for (const position of [...sorted, span]) {
        expect(position - previous, `trou sur le bord ${edge}`).toBeLessThan(maxGap);
        previous = position;
      }
    }
  });

  it("désynchronise les groupes de pulsation et les remplit tous", () => {
    // Une phase unique ferait battre toute la gueule d'un bloc — l'effet guirlande.
    const geometry = buildWaaaghFangs(params);
    expect(geometry.groups).toHaveLength(PULSE_GROUP_COUNT);
    expect(new Set(geometry.groups.map((group) => group.phase)).size).toBe(PULSE_GROUP_COUNT);
    for (const group of geometry.groups) {
      expect(group.polygonsByLayer.every((layer) => layer.length > 0)).toBe(true);
    }
  });

  it("refuse un plateau trop petit ou des dimensions non renseignées", () => {
    expect(() => buildWaaaghFangs({ ...params, boardWidth: 0 })).toThrow(/dimensions invalides/);
    expect(() => buildWaaaghFangs({ ...params, hexRadius: 0 })).toThrow(/dimensions invalides/);
    expect(() =>
      buildWaaaghFangs({ ...params, boardWidth: 50, boardHeight: 50, hexRadius: 8 })
    ).toThrow(/trop court/);
  });
});
