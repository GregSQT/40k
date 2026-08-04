import { describe, expect, it } from "vitest";
import { pointInAnyMaskLoop, pointInMaskLoopsEvenOdd, pointInPolygon } from "./pointInPolygon";

describe("pointInPolygon", () => {
  it("detects interior of axis-aligned square", () => {
    const square = [0, 0, 10, 0, 10, 10, 0, 10];
    expect(pointInPolygon(5, 5, square)).toBe(true);
    expect(pointInPolygon(50, 50, square)).toBe(false);
  });

  it("union of two loops", () => {
    const loops = [
      [0, 0, 2, 0, 2, 2, 0, 2],
      [10, 10, 12, 10, 12, 12, 10, 12],
    ];
    expect(pointInAnyMaskLoop(1, 1, loops)).toBe(true);
    expect(pointInAnyMaskLoop(11, 11, loops)).toBe(true);
    expect(pointInAnyMaskLoop(5, 5, loops)).toBe(false);
  });
});

describe("pointInMaskLoopsEvenOdd", () => {
  // Forme exacte de l'aire d'arrivée des réserves (20.04) : une bande, et dedans une bulle
  // d'exclusion de 9" autour d'un ennemi. Le rendu la creuse (`beginHole`) ; le test de clic doit
  // dire « dehors », sinon on pose l'escouade sur une zone visiblement non peinte.
  const bandWithHole = [
    [0, 0, 20, 0, 20, 20, 0, 20],
    [8, 8, 12, 8, 12, 12, 8, 12],
  ];

  it("un point dans un trou est DEHORS (l'union le croyait dedans)", () => {
    expect(pointInMaskLoopsEvenOdd(10, 10, bandWithHole)).toBe(false);
    expect(pointInAnyMaskLoop(10, 10, bandWithHole)).toBe(true);
  });

  it("un point dans la bande hors du trou reste dedans", () => {
    expect(pointInMaskLoopsEvenOdd(2, 2, bandWithHole)).toBe(true);
  });

  it("un point hors de tout reste dehors", () => {
    expect(pointInMaskLoopsEvenOdd(50, 50, bandWithHole)).toBe(false);
  });

  it("un ilot au milieu d'un trou redevient dedans", () => {
    const island = [...bandWithHole, [9, 9, 11, 9, 11, 11, 9, 11]];
    expect(pointInMaskLoopsEvenOdd(10, 10, island)).toBe(true);
  });

  it("deux boucles DISJOINTES restent une union (aucun trou)", () => {
    const disjoint = [
      [0, 0, 2, 0, 2, 2, 0, 2],
      [10, 10, 12, 10, 12, 12, 10, 12],
    ];
    expect(pointInMaskLoopsEvenOdd(1, 1, disjoint)).toBe(true);
    expect(pointInMaskLoopsEvenOdd(11, 11, disjoint)).toBe(true);
  });
});
