import { describe, expect, it } from "vitest";
import {
  OATH_HEX_HIT_TOLERANCE,
  type OathUnitsCache,
  pickOathTargetAtHex,
} from "./oathTargetSelection";

/** Deux escouades ennemies désignables : la 11 autour de (10,10), la 12 autour de (30,10).
 *  L'unité 13 est dans le cache SANS positions par-figurine (rien de dessiné sur le plateau). */
const CACHE: OathUnitsCache = {
  "11": { occupied_hexes_by_model: { "11_1": [10, 10], "11_2": [12, 10] } },
  "12": { occupied_hexes_by_model: { "12_1": [30, 10] } },
  "13": {},
};

describe("pickOathTargetAtHex", () => {
  it("désigne l'unité dont une FIGURINE est sous le clic", () => {
    expect(
      pickOathTargetAtHex({ col: 12, row: 10, targetUnitIds: [11, 12], unitsCache: CACHE })
    ).toBe(11);
  });

  it("départage par la figurine la plus proche, pas par l'ordre de la liste", () => {
    // (29,10) est à 1 de la fig de l'unité 12 et à 17 de la plus proche de l'unité 11 :
    // l'unité 11 est en tête de liste, elle ne doit pas gagner pour autant.
    expect(
      pickOathTargetAtHex({ col: 29, row: 10, targetUnitIds: [11, 12], unitsCache: CACHE })
    ).toBe(12);
  });

  it("BORNE de tolérance : dedans ça désigne, un sous-hex plus loin ça ne désigne plus", () => {
    // À colonne constante, la distance cube vaut exactement l'écart de lignes.
    const onBorder = 10 + OATH_HEX_HIT_TOLERANCE;
    expect(
      pickOathTargetAtHex({ col: 12, row: onBorder, targetUnitIds: [11], unitsCache: CACHE })
    ).toBe(11);
    expect(
      pickOathTargetAtHex({ col: 12, row: onBorder + 1, targetUnitIds: [11], unitsCache: CACHE })
    ).toBe(null);
  });

  it("ignore une unité NON désignable même si le clic tombe dessus", () => {
    // La légalité vient du moteur : une unité absente de targetUnitIds n'existe pas ici.
    expect(pickOathTargetAtHex({ col: 30, row: 10, targetUnitIds: [11], unitsCache: CACHE })).toBe(
      null
    );
  });

  it("ignore une unité sans positions par-figurine (rien de dessiné à cliquer)", () => {
    expect(pickOathTargetAtHex({ col: 10, row: 10, targetUnitIds: [13], unitsCache: CACHE })).toBe(
      null
    );
  });

  it("rend null sans cache d'unités plutôt que de retomber sur l'ancre d'escouade", () => {
    expect(
      pickOathTargetAtHex({ col: 10, row: 10, targetUnitIds: [11], unitsCache: undefined })
    ).toBe(null);
  });
});
