import { describe, expect, it } from "vitest";
import type { Unit } from "../types/game";
import {
  getIconDiameterRatio,
  getNonRoundBasePixelLayout,
  getNonRoundIconRadius,
  getUnitInitial,
} from "./unitBaseDisplay";

function makeUnit(overrides: Partial<Unit> & Record<string, unknown>): Unit {
  return {
    id: 1,
    player: 1,
    col: 0,
    row: 0,
    HP_CUR: 1,
    MOVE: 6,
    RNG_WEAPONS: [],
    CC_WEAPONS: [],
    ...overrides,
  } as Unit;
}

describe("getUnitInitial", () => {
  it("prend l'initiale du unit_type PAR FIGURINE en priorité", () => {
    const unit = makeUnit({ unit_type: "Zoanthrope", type: "Termagant", unitType: "Boyz" });
    expect(getUnitInitial(unit)).toBe("Z");
  });

  it("retombe sur type puis unitType quand la figurine n'a pas de profil propre", () => {
    expect(getUnitInitial(makeUnit({ type: "Termagant", unitType: "Boyz" }))).toBe("T");
    expect(getUnitInitial(makeUnit({ unitType: "boyz" }))).toBe("B");
  });

  it("lève au lieu de retomber silencieusement sur le nom", () => {
    expect(() => getUnitInitial(makeUnit({ name: "Squad Alpha", DISPLAY_NAME: "Alpha" }))).toThrow(
      /no unit_type\/type/
    );
    expect(() => getUnitInitial(makeUnit({ type: "   " }))).toThrow(/no unit_type\/type/);
  });
});

describe("getIconDiameterRatio — taille de l'initiale dérivée du socle", () => {
  it("croît avec BASE_SIZE (socle rond multi-hex)", () => {
    const small = getIconDiameterRatio(makeUnit({ BASE_SIZE: 1, ICON_SCALE: 1.2 }), 1);
    const big = getIconDiameterRatio(makeUnit({ BASE_SIZE: 3, BASE_SHAPE: "round" }), 1);
    expect(big).toBeGreaterThan(small);
    expect(big).toBe(3 * 1.5);
  });

  it("s'inscrit dans la dimension étroite d'un socle ovale", () => {
    const oval = makeUnit({ BASE_SHAPE: "oval", BASE_SIZE: [4, 2] });
    // rayon inscrit = min(4, 2)/2 * 1.5 * 0.92 → diamètre = 2 * ce rayon
    expect(getIconDiameterRatio(oval, 1)).toBeCloseTo(2 * ((2 / 2) * 1.5 * 0.92), 6);
  });

  it("utilise ICON_SCALE quand le socle tient dans une case", () => {
    expect(getIconDiameterRatio(makeUnit({ BASE_SIZE: 1, ICON_SCALE: 1.4 }), 0.9)).toBe(1.4);
    expect(getIconDiameterRatio(makeUnit({ BASE_SIZE: 1 }), 0.9)).toBe(0.9);
  });
});

describe("getNonRoundBasePixelLayout — métriques pixel des socles ovale / carré", () => {
  const HEX_RADIUS = 20;
  // ICON_INSET = 0.92 : rayon inscrit × 0.92 → 30 × 0.92
  const EXPECTED_ICON_RADIUS = 27.6;

  it("ovale [4,2] : demi-axes 60/30, portrait inscrit dans la dimension étroite", () => {
    const layout = getNonRoundBasePixelLayout(
      makeUnit({ BASE_SHAPE: "oval", BASE_SIZE: [4, 2] }),
      HEX_RADIUS
    );
    expect(layout).not.toBeNull();
    expect(layout?.kind).toBe("oval");
    expect(layout?.outerRx).toBe(60);
    expect(layout?.outerRy).toBe(30);
    expect(layout?.iconRadius).toBeCloseTo(EXPECTED_ICON_RADIUS, 6);
    expect(layout?.squareHalf).toBe(0);
    expect(layout?.squareSide).toBe(0);
    expect(layout?.boundingRadius).toBe(60);
    expect(layout?.topExtentY).toBe(30);
  });

  it("carré 2 : côté 60, demi-côté 30, anneau englobant = demi-côté × √2", () => {
    const layout = getNonRoundBasePixelLayout(
      makeUnit({ BASE_SHAPE: "square", BASE_SIZE: 2 }),
      HEX_RADIUS
    );
    expect(layout).not.toBeNull();
    expect(layout?.kind).toBe("square");
    expect(layout?.squareHalf).toBe(30);
    expect(layout?.squareSide).toBe(60);
    expect(layout?.outerRx).toBe(30);
    expect(layout?.outerRy).toBe(30);
    expect(layout?.iconRadius).toBeCloseTo(EXPECTED_ICON_RADIUS, 6);
    expect(layout?.topExtentY).toBe(30);
    expect(layout?.boundingRadius).toBeCloseTo(30 * Math.SQRT2, 6);
  });

  it("null pour un socle rond et pour un carré d'une seule case", () => {
    expect(
      getNonRoundBasePixelLayout(makeUnit({ BASE_SHAPE: "round", BASE_SIZE: 3 }), HEX_RADIUS)
    ).toBeNull();
    expect(
      getNonRoundBasePixelLayout(makeUnit({ BASE_SHAPE: "square", BASE_SIZE: 1 }), HEX_RADIUS)
    ).toBeNull();
  });

  it("lève, en nommant l'unité, pour un ovale dont une dimension n'est pas numérique (T1)", () => {
    // Le type promet `[number, number]` ; on met en scène un payload API qui le viole. Rendre
    // `null` (socle rond) masquait la donnée corrompue : la levée est explicite et nomme l'unité.
    const malformed = ["x", 2] as unknown as [number, number];
    expect(() =>
      getNonRoundBasePixelLayout(
        makeUnit({ id: 42, BASE_SHAPE: "oval", BASE_SIZE: malformed }),
        HEX_RADIUS
      )
    ).toThrow(/unité 42: BASE_SIZE invalide/);
  });
});

describe("getNonRoundIconRadius — rayon du portrait rond", () => {
  const HEX_RADIUS = 20;

  it("renvoie le rayon inscrit × ICON_INSET pour ovale et carré", () => {
    expect(
      getNonRoundIconRadius(makeUnit({ BASE_SHAPE: "oval", BASE_SIZE: [4, 2] }), HEX_RADIUS)
    ).toBeCloseTo(27.6, 6);
    expect(
      getNonRoundIconRadius(makeUnit({ BASE_SHAPE: "square", BASE_SIZE: 2 }), HEX_RADIUS)
    ).toBeCloseTo(27.6, 6);
  });

  it("null pour un socle rond (rendu rond intégral)", () => {
    expect(
      getNonRoundIconRadius(makeUnit({ BASE_SHAPE: "round", BASE_SIZE: 3 }), HEX_RADIUS)
    ).toBeNull();
  });
});
