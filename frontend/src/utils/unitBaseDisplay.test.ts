import { describe, expect, it } from "vitest";
import type { Unit } from "../types/game";
import { getIconDiameterRatio, getUnitInitial } from "./unitBaseDisplay";

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
