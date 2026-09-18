import { describe, expect, it } from "vitest";
import { assertValidBaseSize, resolveBaseSizeForUnitDisplay } from "./hexFootprint";

describe("assertValidBaseSize — frontière T1 du socle", () => {
  it("laisse passer l'absence (cas métier : replay sans base=), un nombre fini > 0 et un couple", () => {
    expect(assertValidBaseSize(undefined, "u")).toBeUndefined();
    expect(assertValidBaseSize(null, "u")).toBeUndefined();
    expect(assertValidBaseSize(3, "u")).toBe(3);
    expect(assertValidBaseSize([41, 27], "u")).toEqual([41, 27]);
  });

  it("lève, avec le contexte, sur toute valeur non finie, non positive ou mal formée", () => {
    expect(() => assertValidBaseSize(Number.NaN, "API unit 7")).toThrow(
      /API unit 7: BASE_SIZE invalide/
    );
    expect(() => assertValidBaseSize(Number.POSITIVE_INFINITY, "u")).toThrow(/BASE_SIZE invalide/);
    expect(() => assertValidBaseSize(0, "u")).toThrow(/BASE_SIZE invalide/);
    expect(() => assertValidBaseSize(-2, "u")).toThrow(/BASE_SIZE invalide/);
    expect(() => assertValidBaseSize("3", "u")).toThrow(/BASE_SIZE invalide/);
    expect(() => assertValidBaseSize(["x", 2], "u")).toThrow(/BASE_SIZE invalide/);
    expect(() => assertValidBaseSize([3], "u")).toThrow(/BASE_SIZE invalide/);
    expect(() => assertValidBaseSize([3, 2, 1], "u")).toThrow(/BASE_SIZE invalide/);
    expect(() => assertValidBaseSize([3, Number.NaN], "u")).toThrow(/BASE_SIZE invalide/);
  });
});

describe("resolveBaseSizeForUnitDisplay — diamètre hex effectif", () => {
  it("absent → 1, nombre → lui-même (plancher 1), ovale → grand axe", () => {
    expect(resolveBaseSizeForUnitDisplay({})).toBe(1);
    expect(resolveBaseSizeForUnitDisplay({ BASE_SIZE: 6 })).toBe(6);
    expect(resolveBaseSizeForUnitDisplay({ BASE_SIZE: [27, 41] })).toBe(41);
  });

  it("ne rend plus 1 par défaut sur une dimension non finie : levée nommant l'unité", () => {
    expect(() => resolveBaseSizeForUnitDisplay({ id: 9, BASE_SIZE: Number.NaN })).toThrow(
      /unité 9: BASE_SIZE invalide/
    );
    expect(() =>
      resolveBaseSizeForUnitDisplay({
        id: 9,
        BASE_SIZE: ["x", 2] as unknown as [number, number],
      })
    ).toThrow(/unité 9: BASE_SIZE invalide/);
  });
});
