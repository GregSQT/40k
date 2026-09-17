import { describe, expect, it } from "vitest";
import {
  circleTouchesRect,
  cubeAdd,
  cubeSub,
  modelsTouchingRect,
  normalizeRect,
  parseBlockDestinations,
  selectBlockInRect,
  snapBlockAnchor,
} from "./blockSelection";
import { offsetToCube } from "./gameHelpers";

describe("parseBlockDestinations", () => {
  it("lit la réponse moteur en pool 'col,row' → placements par figurine", () => {
    const pool = parseBlockDestinations([
      [
        5,
        11,
        [
          ["S#0", 5, 11, 0],
          ["S#2", 10, 11, 1],
        ],
      ],
    ]);
    expect([...pool.keys()]).toEqual(["5,11"]);
    expect(pool.get("5,11")).toEqual({ "S#0": [5, 11, 0], "S#2": [10, 11, 1] });
  });

  it("lève sur une réponse malformée (jamais de pool partiel)", () => {
    expect(() => parseBlockDestinations(undefined)).toThrow(/destinations/);
    expect(() => parseBlockDestinations([[5, 11]])).toThrow(/malformée/);
    expect(() => parseBlockDestinations([[5, 11, [["S#0", 5, 11]]]])).toThrow(/malformé/);
    expect(() => parseBlockDestinations([[5, 11, [["S#0", "a", 11, 0]]]])).toThrow(/non entier/);
  });
});

describe("snapBlockAnchor", () => {
  const pool = parseBlockDestinations([
    [5, 11, [["S#0", 5, 11, 0]]],
    [5, 12, [["S#0", 5, 12, 0]]],
    [8, 10, [["S#0", 8, 10, 0]]],
  ]);

  it("rend l'ancre voulue quand elle est dans le pool", () => {
    expect(snapBlockAnchor(pool, offsetToCube(5, 12))).toBe("5,12");
  });

  it("snappe sur l'ancre la plus proche en distance cube hors pool", () => {
    // (7,10) : distance 1 de (8,10), 2 de (5,11)… → (8,10).
    expect(snapBlockAnchor(pool, offsetToCube(7, 10))).toBe("8,10");
  });

  it("rend null sur pool vide", () => {
    expect(snapBlockAnchor(new Map(), offsetToCube(0, 0))).toBeNull();
  });

  it("le vecteur de prise (grab) ramène le bloc sous le curseur", () => {
    // Origine de l'ancre (5,10), rectangle relâché en (6,12) → grab = origine − relâchement.
    const grab = cubeSub(offsetToCube(5, 10), offsetToCube(6, 12));
    // Curseur revenu exactement au point de relâchement → ancre voulue = origine.
    const desired = cubeAdd(offsetToCube(6, 12), grab);
    expect(desired).toEqual(offsetToCube(5, 10));
  });
});

describe("hit-test socle / rectangle", () => {
  it("compte un socle partiellement dedans et exclut un socle à côté", () => {
    const rect = normalizeRect(100, 100, 50, 50); // coins dans le désordre → normalisé
    expect(rect).toEqual({ x0: 50, y0: 50, x1: 100, y1: 100 });
    expect(circleTouchesRect(rect, 45, 75, 10)).toBe(true); // mord le bord gauche
    expect(circleTouchesRect(rect, 30, 75, 10)).toBe(false); // à 10 px du bord
    expect(circleTouchesRect(rect, 110, 110, 10)).toBe(false); // coin : distance √200 > 10
    expect(circleTouchesRect(rect, 107, 107, 10)).toBe(true); // coin : distance √98 < 10
  });

  it("selectBlockInRect : une seule escouade, sinon rien", () => {
    const rect = normalizeRect(0, 0, 40, 40);
    const a0 = { modelId: "A#0", cx: 10, cy: 10, radius: 5, unitId: 1 };
    const a1 = { modelId: "A#1", cx: 20, cy: 10, radius: 5, unitId: 1 };
    const b0 = { modelId: "B#0", cx: 30, cy: 30, radius: 5, unitId: 2 };
    const far = { modelId: "B#1", cx: 90, cy: 90, radius: 5, unitId: 2 };
    expect(selectBlockInRect([a0, a1, far], rect)).toEqual(["A#0", "A#1"]);
    expect(selectBlockInRect([a0, a1, b0], rect)).toEqual([]);
    expect(selectBlockInRect([far], rect)).toEqual([]);
  });

  it("modelsTouchingRect garde l'ordre d'escouade et ne rend que les socles touchés", () => {
    const rect = normalizeRect(0, 0, 40, 40);
    const ids = modelsTouchingRect(
      [
        { modelId: "S#2", cx: 60, cy: 60, radius: 5 },
        { modelId: "S#0", cx: 10, cy: 10, radius: 5 },
        { modelId: "S#1", cx: 44, cy: 20, radius: 5 },
      ],
      rect
    );
    expect(ids).toEqual(["S#0", "S#1"]);
  });
});
