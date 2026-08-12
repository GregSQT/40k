// @vitest-environment jsdom
/**
 * Verrous de la config plateau résolue. L'enjeu est l'IDENTITÉ : la valeur était déjà juste avant
 * ce hook, c'est la RÉFÉRENCE qui changeait à chaque rendu en replay et sur les plateaux à échelle
 * d'affichage ≠ 1, ce qui rendait inopérante toute mémoïsation accrochée à l'objet.
 */

import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  applyDisplayScale,
  type BoardConfigOverride,
  useResolvedBoardConfig,
} from "./useResolvedBoardConfig";

const BASE = { cols: 10, rows: 8, hex_radius: 4, margin: 2, inches_to_subhex: 1, display: {} };
const SCALED = { ...BASE, display: { display_scale: 5 } };
const OVERRIDE: BoardConfigOverride = {
  cols: 44,
  rows: 60,
  hex_radius: 3,
  margin: 1,
  inches_to_subhex: 5,
};

describe("applyDisplayScale", () => {
  it("multiplie le rayon d'hex par l'échelle", () => {
    expect(applyDisplayScale(SCALED).hex_radius).toBe(20);
  });

  it("échelle absente ou 1 → rend l'objet REÇU, pas une copie", () => {
    expect(Object.is(applyDisplayScale(BASE), BASE)).toBe(true);
    const one = { ...BASE, display: { display_scale: 1 } };
    expect(Object.is(applyDisplayScale(one), one)).toBe(true);
  });
});

describe("useResolvedBoardConfig — identité", () => {
  it("sans surcharge ni échelle → rend l'objet de l'API lui-même", () => {
    const { result } = renderHook(() => useResolvedBoardConfig(BASE, undefined));
    expect(Object.is(result.current, BASE)).toBe(true);
  });

  it("AVEC surcharge de replay, entrées inchangées → MÊME référence entre deux rendus", () => {
    const { result, rerender } = renderHook(() => useResolvedBoardConfig(BASE, OVERRIDE));
    const first = result.current;
    rerender();
    expect(Object.is(result.current, first)).toBe(true);
    expect(result.current?.cols).toBe(44);
  });

  it("AVEC échelle ≠ 1, entrées inchangées → MÊME référence entre deux rendus", () => {
    const { result, rerender } = renderHook(() => useResolvedBoardConfig(SCALED, undefined));
    const first = result.current;
    rerender();
    expect(Object.is(result.current, first)).toBe(true);
    expect(result.current?.hex_radius).toBe(20);
  });

  it("surcharge et échelle CUMULÉES : la surcharge s'applique avant la mise à l'échelle", () => {
    const { result, rerender } = renderHook(() => useResolvedBoardConfig(SCALED, OVERRIDE));
    const first = result.current;
    rerender();
    expect(Object.is(result.current, first)).toBe(true);
    // hex_radius 3 (surcharge) x 5 (échelle), et non 4 x 5.
    expect(result.current?.hex_radius).toBe(15);
  });

  it("surcharge REMPLACÉE → référence différente, valeurs à jour", () => {
    const { result, rerender } = renderHook(
      (props: { ov: BoardConfigOverride | undefined }) => useResolvedBoardConfig(BASE, props.ov),
      { initialProps: { ov: OVERRIDE } }
    );
    const first = result.current;
    rerender({ ov: { ...OVERRIDE, cols: 99 } });
    expect(Object.is(result.current, first)).toBe(false);
    expect(result.current?.cols).toBe(99);
  });

  it("config API absente → null, même avec une surcharge", () => {
    const { result } = renderHook(() => useResolvedBoardConfig(null, OVERRIDE));
    expect(result.current).toBeNull();
  });
});
