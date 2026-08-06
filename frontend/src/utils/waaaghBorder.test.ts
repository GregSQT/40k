import { describe, expect, it } from "vitest";
import { buildWaaaghCracks, WAAAGH_CRACKS_SEED } from "./waaaghBorder";

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
 * jamais sur la seule graine de production : chaque plateau (dimensions, hex_radius) consomme un
 * nombre différent de tirages, donc produit un tirage effectif différent. Une propriété vraie
 * pour `WAAAGH_CRACKS_SEED` sur le 44x60 et fausse ailleurs est un défaut qui attend son plateau.
 */
const GEOMETRY_CASES = (() => {
  const boards = [
    { boardWidth: BOARD_WIDTH, boardHeight: BOARD_HEIGHT, hexRadius: HEX_RADIUS },
    { boardWidth: 900, boardHeight: 1400, hexRadius: 12 },
    { boardWidth: 400, boardHeight: 380, hexRadius: 6 },
  ];
  const cases: Array<{ boardWidth: number; boardHeight: number; hexRadius: number; seed: number }> =
    [];
  for (const board of boards) {
    for (let i = 0; i < 40; i += 1) {
      cases.push({ ...board, seed: WAAAGH_CRACKS_SEED + i * 7919 });
    }
  }
  return cases;
})();

describe("buildWaaaghCracks", () => {
  it("est déterministe : même graine et mêmes dimensions → géométrie identique", () => {
    // La fissure est REDESSINÉE à chaque frame pendant toute la durée du Waaagh!. Si la
    // géométrie variait d'un appel à l'autre, le pourtour grouillerait au lieu d'être une
    // cassure figée dont seule la lueur respire.
    expect(buildWaaaghCracks(params)).toEqual(buildWaaaghCracks(params));
  });

  it("ne trace jamais hors du plateau", () => {
    // Le VRAI défaut que ce test verrouille : les branches serpentent vers l'intérieur, et une
    // déviation d'angle libre pouvait les faire repartir vers l'extérieur et dessiner dans le
    // vide autour de la table.
    for (const geometryCase of GEOMETRY_CASES) {
      for (const stroke of buildWaaaghCracks(geometryCase).strokes) {
        for (const point of stroke) {
          expect(point.x).toBeGreaterThanOrEqual(0);
          expect(point.x).toBeLessThanOrEqual(geometryCase.boardWidth);
          expect(point.y).toBeGreaterThanOrEqual(0);
          expect(point.y).toBeLessThanOrEqual(geometryCase.boardHeight);
        }
      }
    }
  });

  it("produit un pourtour fermé qui longe les quatre bords, plus des branches", () => {
    const { strokes } = buildWaaaghCracks(params);
    const ring = strokes[0];
    // Fermé : sinon un angle du plateau resterait ouvert.
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    // Le pourtour touche les quatre bords : un tracé qui n'en longerait que deux passerait
    // toutes les autres assertions (VERT VACANT).
    const near = (v: number, edge: number) => Math.abs(v - edge) <= 2 * HEX_RADIUS;
    expect(ring.some((p) => near(p.y, 0))).toBe(true);
    expect(ring.some((p) => near(p.y, BOARD_HEIGHT))).toBe(true);
    expect(ring.some((p) => near(p.x, 0))).toBe(true);
    expect(ring.some((p) => near(p.x, BOARD_WIDTH))).toBe(true);
    // Des branches existent : sans elles l'effet n'est qu'un liseré, pas une fissure.
    expect(strokes.length).toBeGreaterThan(1);
  });

  it("enfonce chaque branche vers l'intérieur, sans jamais revenir vers son bord", () => {
    for (const geometryCase of GEOMETRY_CASES) {
      const { strokes } = buildWaaaghCracks(geometryCase);
      // Profondeur par rapport au bord D'ORIGINE de la branche (déduit de son premier point),
      // et non à « n'importe quel bord » : près d'un angle, une branche du bord haut s'éloigne
      // du haut tout en se rapprochant du bord latéral, ce qui est parfaitement légitime.
      const distancesToEdges = (p: { x: number; y: number }) => [
        p.y,
        geometryCase.boardWidth - p.x,
        geometryCase.boardHeight - p.y,
        p.x,
      ];
      // VERT VACANT : un jeu de cas qui ne produirait aucune branche passerait la boucle sans
      // rien regarder.
      expect(strokes.length).toBeGreaterThan(1);
      for (const branch of strokes.slice(1)) {
        const startDistances = distancesToEdges(branch[0]);
        const originEdge = startDistances.indexOf(Math.min(...startDistances));
        for (let i = 1; i < branch.length; i += 1) {
          expect(distancesToEdges(branch[i])[originEdge]).toBeGreaterThan(
            distancesToEdges(branch[i - 1])[originEdge]
          );
        }
      }
    }
  });

  it("refuse des dimensions de plateau non renseignées", () => {
    expect(() => buildWaaaghCracks({ ...params, boardWidth: 0 })).toThrow(/dimensions invalides/);
    expect(() => buildWaaaghCracks({ ...params, hexRadius: 0 })).toThrow(/dimensions invalides/);
  });
});
