import { describe, expect, it } from "vitest";
import { boardWorldSize } from "./hexFootprint";
import {
  buildWaaaghFangs,
  type EdgeFrame,
  FANG_BODY_LAYER_INDEX,
  FANG_PITCH_HEX,
  PULSE_GROUP_COUNT,
  type WaaaghFangsGeometry,
  waaaghEdgeFrames,
} from "./waaaghBorder";

/** Plateau 44x60 au hex_radius de production (cf. config/board/44x60x5). Les dimensions passent
 *  par `boardWorldSize`, la même fonction que le rendu : une formule recopiée ici laisserait le
 *  test vérifier la denture d'un plateau qui n'existe plus. */
const HEX_RADIUS = 8;
const { width: BOARD_WIDTH, height: BOARD_HEIGHT } = boardWorldSize(44 * 5, 60 * 5, HEX_RADIUS, 30);

/** Graine arbitraire : la production n'en passe aucune, seuls les tests en font varier. */
const SEED = 0x57414147;

const params = {
  boardWidth: BOARD_WIDTH,
  boardHeight: BOARD_HEIGHT,
  hexRadius: HEX_RADIUS,
  seed: SEED,
};

/**
 * Les propriétés de sûreté sont vérifiées sur un ÉVENTAIL de graines et de dimensions, jamais sur
 * la seule graine de production : chaque plateau consomme un nombre différent de tirages, donc
 * produit un tirage effectif différent. Une propriété vraie pour une graine sur le 44x60 et fausse
 * ailleurs est un défaut qui attend son plateau.
 *
 * Les géométries sont construites UNE fois et partagées : chaque cas coûte plusieurs centaines de
 * crocs × 5 couches, et trois propriétés les reconstruisaient chacune de leur côté.
 */
const GEOMETRY_CASES = (() => {
  const boards = [
    { boardWidth: BOARD_WIDTH, boardHeight: BOARD_HEIGHT, hexRadius: HEX_RADIUS },
    { boardWidth: 900, boardHeight: 1400, hexRadius: 12 },
    { boardWidth: 500, boardHeight: 480, hexRadius: 6 },
  ];
  const cases: Array<{
    boardWidth: number;
    boardHeight: number;
    hexRadius: number;
    seed: number;
    geometry: WaaaghFangsGeometry;
  }> = [];
  for (const board of boards) {
    for (let i = 0; i < 25; i += 1) {
      const geometryCase = { ...board, seed: SEED + i * 7919 };
      cases.push({ ...geometryCase, geometry: buildWaaaghFangs(geometryCase) });
    }
  }
  return cases;
})();

function allPolygons(geometry: WaaaghFangsGeometry): number[][] {
  return geometry.groups.flatMap((group) => group.polygonsByLayer.flat());
}

/**
 * Chaque polygone AVEC le bord qui le porte. C'est une information que la géométrie déclare et
 * qu'on ne peut pas retrouver après coup : près d'un coin, le bord le plus PROCHE d'un croc n'est
 * pas celui qui le porte — et c'est exactement là que les débordements se jouent.
 */
function polygonsWithEdge(
  geometry: WaaaghFangsGeometry
): Array<{ polygon: number[]; edgeIndex: number }> {
  const out: Array<{ polygon: number[]; edgeIndex: number }> = [];
  for (const group of geometry.groups) {
    for (const layer of group.polygonsByLayer) {
      layer.forEach((polygon, fangIndex) => {
        out.push({ polygon, edgeIndex: group.edgeIndexByFang[fangIndex] });
      });
    }
  }
  return out;
}

/** Coordonnées d'un point dans le repère d'un bord : `u` le long du bord, `v` vers l'intérieur. */
function toEdgeLocal(point: { x: number; y: number }, frame: EdgeFrame): { u: number; v: number } {
  const dx = point.x - frame.originX;
  const dy = point.y - frame.originY;
  return { u: dx * frame.ux + dy * frame.uy, v: dx * frame.nx + dy * frame.ny };
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
      const { geometry } = geometryCase;
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

  it("borne le débordement hors plateau, chaque direction contre SA borne", () => {
    // Deux directions indépendantes, mesurées dans le repère du bord PORTEUR :
    //   - `v < 0` : le croc mord au-delà de son propre bord — c'est `maxOutwardBleed` ;
    //   - `u` hors de `[0, length]` : il déborde LE LONG de son bord, donc sort par un bord
    //     perpendiculaire, aux coins — c'est `maxCornerBleed`.
    // Les mesurer en coordonnées monde (`depthInside`, qui prend le min des quatre côtés) les
    // confond, et pas au profit du contrôle : pour un même point le débordement axial y est
    // plafonné par le débordement normal, si bien qu'aucune assertion ne peut plus ATTEINDRE la
    // borne des coins — un contrôle inviolable, donc muet. Le repère du bord est ce qui rend les
    // deux propriétés séparément falsifiables.
    for (const geometryCase of GEOMETRY_CASES) {
      const { geometry } = geometryCase;
      const edges = waaaghEdgeFrames(geometryCase.boardWidth, geometryCase.boardHeight);
      // On agrège le pire des centaines de milliers de points puis on l'assertionne une fois : un
      // `expect` par point ferait expirer le test sans rien vérifier de plus.
      let worstNormal = 0;
      let worstAxial = 0;
      for (const { polygon, edgeIndex } of polygonsWithEdge(geometry)) {
        const { frame, length } = edges[edgeIndex];
        for (const point of pointsOf(polygon)) {
          const { u, v } = toEdgeLocal(point, frame);
          worstNormal = Math.max(worstNormal, -v);
          worstAxial = Math.max(worstAxial, -u, u - length);
        }
      }
      expect(worstNormal).toBeLessThanOrEqual(geometry.maxOutwardBleed + 1e-6);
      expect(worstAxial).toBeLessThanOrEqual(geometry.maxCornerBleed + 1e-6);
      // Chaque contrôle regarde un débordement RÉEL : à zéro, il passerait pour n'importe quelle
      // borne, y compris une borne fausse.
      expect(worstNormal).toBeGreaterThan(0);
      expect(worstAxial).toBeGreaterThan(0);
      // Et les bornes restent utiles : gonflées, elles ne contraindraient plus rien.
      expect(geometry.maxOutwardBleed).toBeLessThan(geometryCase.hexRadius * 4);
      expect(geometry.maxCornerBleed).toBeLessThan(geometryCase.hexRadius * 4);
    }
  });

  it("fait le tour complet : les quatre bords sont dentés, sans trou", () => {
    const geometry = buildWaaaghFangs(params);
    const edges = waaaghEdgeFrames(BOARD_WIDTH, BOARD_HEIGHT);
    // Position de chaque croc (couche du CORPS) LE LONG de son bord porteur — celui que la
    // géométrie déclare, pas le plus proche : aux coins les deux diffèrent, et un croc du bord haut
    // classé « à gauche » creuserait un trou fantôme en haut tout en en bouchant un à gauche.
    const positionsByEdge: number[][] = edges.map(() => []);
    for (const group of geometry.groups) {
      group.polygonsByLayer[FANG_BODY_LAYER_INDEX].forEach((polygon, fangIndex) => {
        const edgeIndex = group.edgeIndexByFang[fangIndex];
        const locals = pointsOf(polygon).map((point) => toEdgeLocal(point, edges[edgeIndex].frame));
        // Ancre = le point le plus proche du bord porteur, donc la base du croc.
        const anchor = locals.reduce((best, local) => (local.v < best.v ? local : best));
        positionsByEdge[edgeIndex].push(anchor.u);
      });
    }
    // Aucun bord vide, et aucun intervalle béant : le plus grand écart entre deux crocs voisins
    // reste de l'ordre du pas nominal. Sans ce contrôle, une denture ne couvrant qu'un demi-bord
    // passerait pour complète.
    const maxGap = HEX_RADIUS * FANG_PITCH_HEX * 2.5;
    positionsByEdge.forEach((positions, edgeIndex) => {
      expect(positions.length, `bord ${edgeIndex} sans crocs`).toBeGreaterThan(10);
      const sorted = [...positions].sort((a, b) => a - b);
      let previous = 0;
      for (const position of [...sorted, edges[edgeIndex].length]) {
        expect(position - previous, `trou sur le bord ${edgeIndex}`).toBeLessThan(maxGap);
        previous = position;
      }
    });
  });

  it("désynchronise les groupes de pulsation et les remplit tous", () => {
    // Une phase unique ferait battre toute la gueule d'un bloc — l'effet guirlande.
    const geometry = buildWaaaghFangs(params);
    expect(geometry.groups).toHaveLength(PULSE_GROUP_COUNT);
    expect(new Set(geometry.groups.map((group) => group.phase)).size).toBe(PULSE_GROUP_COUNT);
    for (const group of geometry.groups) {
      expect(group.polygonsByLayer.every((layer) => layer.length > 0)).toBe(true);
      // Un bord déclaré par croc, sur chaque couche : sans cet alignement les contrôles de
      // débordement liraient `undefined` et indexeraient un bord inexistant, en silence.
      for (const layer of group.polygonsByLayer) {
        expect(group.edgeIndexByFang).toHaveLength(layer.length);
      }
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
