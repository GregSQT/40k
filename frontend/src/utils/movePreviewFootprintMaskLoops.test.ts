/**
 * T9 — movePreviewFootprintMaskLoops : normalisation API → number[][]
 *
 * Fonctions pures, pas de DOM.
 */
import { describe, expect, it } from "vitest";
import { normalizeMaskLoopsFromApi } from "./movePreviewFootprintMaskLoops";

describe("normalizeMaskLoopsFromApi", () => {
  // -------------------------------------------------------------------------
  // Cas null / vides
  // -------------------------------------------------------------------------

  it("retourne null pour null", () => {
    expect(normalizeMaskLoopsFromApi(null)).toBeNull();
  });

  it("retourne null pour [] (tableau vide)", () => {
    expect(normalizeMaskLoopsFromApi([])).toBeNull();
  });

  it("retourne null pour une string", () => {
    expect(normalizeMaskLoopsFromApi("foo")).toBeNull();
  });

  it("retourne null pour un nombre", () => {
    expect(normalizeMaskLoopsFromApi(42)).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Format imbriqué [[x,y], …] — boucle trop courte
  // -------------------------------------------------------------------------

  it("filtre une boucle de moins de 3 points (< 6 valeurs)", () => {
    // 2 points → 4 valeurs < 6 → boucle éliminée
    expect(normalizeMaskLoopsFromApi([[[0, 0], [1, 1]]])).toBeNull();
  });

  it("accepte une boucle de 3 points (6 valeurs exactement)", () => {
    const result = normalizeMaskLoopsFromApi([
      [
        [0, 0],
        [1, 1],
        [2, 0],
      ],
    ]);
    expect(result).toEqual([[0, 0, 1, 1, 2, 0]]);
  });

  it("convertit plusieurs boucles imbriquées", () => {
    const result = normalizeMaskLoopsFromApi([
      [
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 1],
      ],
      [
        [5, 5],
        [6, 5],
        [6, 6],
      ],
    ]);
    expect(result).toEqual([
      [0, 0, 1, 0, 1, 1, 0, 1],
      [5, 5, 6, 5, 6, 6],
    ]);
  });

  // -------------------------------------------------------------------------
  // Format plat [x, y, x, y, …]
  // -------------------------------------------------------------------------

  it("accepte un format plat de 6 nombres", () => {
    expect(normalizeMaskLoopsFromApi([[0, 1, 2, 3, 4, 5]])).toEqual([[0, 1, 2, 3, 4, 5]]);
  });

  it("filtre les valeurs non finies (NaN) dans le format plat", () => {
    // [0, 1, NaN, 3, 4, 5] → 5 valeurs valides < 6 → boucle éliminée
    expect(normalizeMaskLoopsFromApi([[0, 1, Number.NaN, 3, 4, 5]])).toBeNull();
  });

  it("filtre Infinity dans le format plat", () => {
    // 5 valeurs finies après filtrage < 6 → null
    expect(normalizeMaskLoopsFromApi([[0, 1, Number.POSITIVE_INFINITY, 3, 4, 5]])).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Boucles mixtes : certaines valides, d'autres non
  // -------------------------------------------------------------------------

  it("renvoie uniquement les boucles valides (≥ 6 valeurs)", () => {
    const result = normalizeMaskLoopsFromApi([
      [[0, 0], [1, 1]], // 2 points = 4 valeurs → éliminée
      [
        [10, 0],
        [11, 0],
        [11, 1],
      ], // 3 points = 6 valeurs → gardée
    ]);
    expect(result).toEqual([[10, 0, 11, 0, 11, 1]]);
  });

  it("renvoie null si toutes les boucles sont trop courtes", () => {
    expect(
      normalizeMaskLoopsFromApi([
        [[0, 0], [1, 1]],
        [[2, 2]],
      ])
    ).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Sous-éléments malformés
  // -------------------------------------------------------------------------

  it("ignore les sous-éléments qui ne sont pas des tableaux (format imbriqué)", () => {
    // Une boucle avec des points valides entremêlés de non-tableaux
    // [null, [0,0], "bad", [1,1], undefined, [2,0]] → 3 points → [0,0,1,1,2,0]
    const result = normalizeMaskLoopsFromApi([[null, [0, 0], "bad", [1, 1], undefined, [2, 0]]]);
    expect(result).toEqual([[0, 0, 1, 1, 2, 0]]);
  });
});
