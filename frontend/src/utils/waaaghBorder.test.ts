import { describe, expect, it } from "vitest";
import {
  buildWaaaghCracks,
  PULSE_GROUP_COUNT,
  WAAAGH_CRACKS_SEED,
  type WaaaghCracksGeometry,
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
 * Les propriétés de sûreté du tracé sont vérifiées sur un ÉVENTAIL de graines et de dimensions,
 * jamais sur la seule graine de production : chaque plateau consomme un nombre différent de
 * tirages, donc produit un tirage effectif différent. Une propriété vraie pour
 * `WAAAGH_CRACKS_SEED` sur le 44x60 et fausse ailleurs est un défaut qui attend son plateau.
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

/** Tous les polygones de la géométrie, toutes couches et tous groupes confondus. */
function allPolygons(geometry: WaaaghCracksGeometry): number[][] {
  return geometry.groups.flatMap((group) => group.polygonsByLayer.flat());
}

/** Les points d'un polygone plat `[x0, y0, x1, y1, …]`. */
function pointsOf(polygon: number[]): Array<{ x: number; y: number }> {
  const points: Array<{ x: number; y: number }> = [];
  for (let i = 0; i < polygon.length; i += 2) {
    points.push({ x: polygon[i], y: polygon[i + 1] });
  }
  return points;
}

describe("buildWaaaghCracks", () => {
  it("est déterministe : même graine et mêmes dimensions → géométrie identique", () => {
    // La géométrie est gravée une fois puis animée par alpha. Si elle variait d'un appel à
    // l'autre, toute reconstruction (zoom, remontage) redistribuerait les failles sous les yeux
    // du joueur.
    expect(buildWaaaghCracks(params)).toEqual(buildWaaaghCracks(params));
  });

  it("ne trace jamais hors du plateau, halo de la couche la plus large compris", () => {
    for (const geometryCase of GEOMETRY_CASES) {
      const geometry = buildWaaaghCracks(geometryCase);
      // VERT VACANT : une géométrie vide passerait la boucle sans rien regarder.
      expect(geometry.crackCount).toBeGreaterThan(10);
      // Bbox de TOUS les points, puis quatre assertions : un `expect` par coordonnée sur des
      // centaines de milliers de points fait expirer le test sans rien vérifier de plus.
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      for (const polygon of allPolygons(geometry)) {
        for (let i = 0; i < polygon.length; i += 2) {
          if (polygon[i] < minX) minX = polygon[i];
          if (polygon[i] > maxX) maxX = polygon[i];
          if (polygon[i + 1] < minY) minY = polygon[i + 1];
          if (polygon[i + 1] > maxY) maxY = polygon[i + 1];
        }
      }
      expect(minX).toBeGreaterThanOrEqual(0);
      expect(maxX).toBeLessThanOrEqual(geometryCase.boardWidth);
      expect(minY).toBeGreaterThanOrEqual(0);
      expect(maxY).toBeLessThanOrEqual(geometryCase.boardHeight);
    }
  });

  it("effile chaque faille : les deux rives se rejoignent aux pointes", () => {
    // C'est LE défaut visuel corrigé par cette version : une demi-largeur constante donne un
    // ruban d'épaisseur uniforme, que l'œil lit comme une corde et non comme une cassure.
    for (const geometryCase of GEOMETRY_CASES.slice(0, 10)) {
      const geometry = buildWaaaghCracks(geometryCase);
      const polygons = allPolygons(geometry);
      expect(polygons.length).toBeGreaterThan(0);
      for (const polygon of polygons) {
        const points = pointsOf(polygon);
        const half = points.length / 2;
        // Rive gauche = première moitié dans le sens du squelette, rive droite = seconde moitié
        // en sens inverse. Les deux extrémités du squelette sont donc les points qui se font face
        // au début et au milieu du contour.
        const startGap = Math.hypot(
          points[0].x - points[points.length - 1].x,
          points[0].y - points[points.length - 1].y
        );
        const endGap = Math.hypot(
          points[half - 1].x - points[half].x,
          points[half - 1].y - points[half].y
        );
        expect(startGap).toBeLessThan(1e-9);
        expect(endGap).toBeLessThan(1e-9);
      }
    }
  });

  it("garde chaque faille locale : aucune ne fait le tour d'un bord", () => {
    // Une faille est un accident local. La version précédente traçait un anneau continu tout
    // autour du plateau — c'est ce qui la faisait lire comme un liseré posé sur le bord.
    for (const geometryCase of GEOMETRY_CASES.slice(0, 10)) {
      const geometry = buildWaaaghCracks(geometryCase);
      const maxExtent = Math.max(geometryCase.boardWidth, geometryCase.boardHeight) / 3;
      for (const polygon of allPolygons(geometry)) {
        const points = pointsOf(polygon);
        const xs = points.map((point) => point.x);
        const ys = points.map((point) => point.y);
        expect(Math.max(...xs) - Math.min(...xs)).toBeLessThan(maxExtent);
        expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(maxExtent);
      }
    }
  });

  it("répartit les failles sur les quatre bords", () => {
    // Un générateur qui n'aurait traité qu'un bord passerait toutes les autres assertions.
    const geometry = buildWaaaghCracks(params);
    const near = (value: number, edge: number) => Math.abs(value - edge) <= HEX_RADIUS * 20;
    const centers = allPolygons(geometry).map((polygon) => {
      const points = pointsOf(polygon);
      const sum = points.reduce((acc, point) => ({ x: acc.x + point.x, y: acc.y + point.y }), {
        x: 0,
        y: 0,
      });
      return { x: sum.x / points.length, y: sum.y / points.length };
    });
    expect(centers.some((c) => near(c.y, 0))).toBe(true);
    expect(centers.some((c) => near(c.y, BOARD_HEIGHT))).toBe(true);
    expect(centers.some((c) => near(c.x, 0))).toBe(true);
    expect(centers.some((c) => near(c.x, BOARD_WIDTH))).toBe(true);
  });

  it("désynchronise les groupes de pulsation et les remplit tous", () => {
    // Une phase unique ferait battre tout le pourtour d'un bloc — l'effet guirlande.
    const geometry = buildWaaaghCracks(params);
    expect(geometry.groups).toHaveLength(PULSE_GROUP_COUNT);
    const phases = geometry.groups.map((group) => group.phase);
    expect(new Set(phases).size).toBe(PULSE_GROUP_COUNT);
    for (const group of geometry.groups) {
      expect(group.polygonsByLayer.every((layer) => layer.length > 0)).toBe(true);
    }
  });

  it("refuse un plateau trop petit ou des dimensions non renseignées", () => {
    expect(() => buildWaaaghCracks({ ...params, boardWidth: 0 })).toThrow(/dimensions invalides/);
    expect(() => buildWaaaghCracks({ ...params, hexRadius: 0 })).toThrow(/dimensions invalides/);
    // Bande de failles impossible : mieux vaut lever que rendre un pourtour vide sans raison.
    expect(() =>
      buildWaaaghCracks({ ...params, boardWidth: 40, boardHeight: 40, hexRadius: 8 })
    ).toThrow(/trop petit/);
  });
});
