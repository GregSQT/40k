// @vitest-environment jsdom
/**
 * Verrous des trois dérivations mémoïsées du chemin de rendu.
 *
 * Une mémoïsation ne se prouve PAS par la valeur : mémoïsée ou non, la dérivation rend le même
 * contenu. Elle se prouve par l'IDENTITÉ — `Object.is` entre deux rendus de même source, et une
 * référence DIFFÉRENTE dès que la source change. C'est ce que testent les cas ci-dessous.
 */

import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  buildHexKeySet,
  flattenObjectiveHexes,
  type NormalizedObjective,
  normalizeObjectives,
  type RawObjective,
  useEffectiveObjectiveHexes,
  useNormalizedObjectives,
  useWallHexKeySet,
} from "./useBoardHexMemos";

const OBJECTIVES: RawObjective[] = [
  { name: "obj_a", hexes: [{ col: 1, row: 2 }, [3, 4]] },
  { name: "obj_b", hexes: [{ col: 5, row: 6 }] },
];

describe("normalizeObjectives", () => {
  it("normalise couples et objets vers {col,row}", () => {
    expect(normalizeObjectives(OBJECTIVES)).toEqual([
      {
        name: "obj_a",
        hexes: [
          { col: 1, row: 2 },
          { col: 3, row: 4 },
        ],
      },
      { name: "obj_b", hexes: [{ col: 5, row: 6 }] },
    ]);
  });

  // Les trois `throw` sont VOULUS (aucun repli qui masquerait une réponse API malformée).
  it("lève sur un objectif sans nom", () => {
    expect(() => normalizeObjectives([{ name: "", hexes: [] }])).toThrow(
      "Objective missing required name field"
    );
  });

  it("lève sur un objectif sans hexes", () => {
    expect(() => normalizeObjectives([{ name: "obj" } as unknown as RawObjective])).toThrow(
      "Objective obj missing required hexes"
    );
  });

  it("lève sur un couple de mauvaise arité", () => {
    expect(() =>
      normalizeObjectives([{ name: "obj", hexes: [[1, 2, 3] as unknown as [number, number]] }])
    ).toThrow(/invalid hex tuple/);
  });

  it("lève sur un hex qui n'est ni couple ni {col,row}", () => {
    expect(() =>
      normalizeObjectives([{ name: "obj", hexes: [{ x: 1 } as unknown as RawObjectiveHexLike] }])
    ).toThrow(/invalid hex format/);
  });
});

// Type local : un hex volontairement HORS contrat, pour le cas d'erreur ci-dessus.
type RawObjectiveHexLike = { col: number; row: number };

describe("useNormalizedObjectives — identité", () => {
  it("même référence de source → MÊME référence de sortie", () => {
    const { result, rerender } = renderHook(
      (props: { objectives: RawObjective[] | undefined }) =>
        useNormalizedObjectives(props.objectives),
      { initialProps: { objectives: OBJECTIVES } }
    );
    const first = result.current;
    rerender({ objectives: OBJECTIVES });
    expect(Object.is(result.current, first)).toBe(true);
  });

  it("source différente (même contenu) → référence DIFFÉRENTE", () => {
    const { result, rerender } = renderHook(
      (props: { objectives: RawObjective[] | undefined }) =>
        useNormalizedObjectives(props.objectives),
      { initialProps: { objectives: OBJECTIVES } }
    );
    const first = result.current;
    rerender({ objectives: [...OBJECTIVES] });
    expect(Object.is(result.current, first)).toBe(false);
    expect(result.current).toEqual(first);
  });

  it("source absente → undefined, sans lever", () => {
    const { result } = renderHook(() => useNormalizedObjectives(undefined));
    expect(result.current).toBeUndefined();
  });
});

describe("flattenObjectiveHexes / useEffectiveObjectiveHexes", () => {
  const normalized: NormalizedObjective[] = normalizeObjectives(OBJECTIVES);
  const boardHexes: [number, number][] = [[9, 9]];

  it("aplatit en couples dans l'ordre des zones", () => {
    expect(flattenObjectiveHexes(normalized)).toEqual([
      [1, 2],
      [3, 4],
      [5, 6],
    ]);
  });

  it("mêmes références → MÊME référence de sortie", () => {
    const { result, rerender } = renderHook(
      (props: { ov: NormalizedObjective[] | undefined }) =>
        useEffectiveObjectiveHexes(props.ov, boardHexes),
      { initialProps: { ov: normalized } }
    );
    const first = result.current;
    rerender({ ov: normalized });
    expect(Object.is(result.current, first)).toBe(true);
  });

  it("override différent → référence DIFFÉRENTE", () => {
    const { result, rerender } = renderHook(
      (props: { ov: NormalizedObjective[] | undefined }) =>
        useEffectiveObjectiveHexes(props.ov, boardHexes),
      { initialProps: { ov: normalized } }
    );
    const first = result.current;
    rerender({ ov: [normalized[0]!] });
    expect(Object.is(result.current, first)).toBe(false);
    expect(result.current).toEqual([
      [1, 2],
      [3, 4],
    ]);
  });

  it("override vide → la liste STATIQUE du plateau, telle quelle", () => {
    const { result } = renderHook(() => useEffectiveObjectiveHexes([], boardHexes));
    expect(Object.is(result.current, boardHexes)).toBe(true);
  });

  it("override vide ET plateau sans objectifs → référence stable, pas un `[]` neuf", () => {
    const { result, rerender } = renderHook(() => useEffectiveObjectiveHexes(undefined, undefined));
    const first = result.current;
    rerender();
    expect(result.current).toEqual([]);
    expect(Object.is(result.current, first)).toBe(true);
  });
});

describe("useWallHexKeySet", () => {
  it("construit les clés `col,row`", () => {
    expect(buildHexKeySet([[1, 2]])).toEqual(new Set(["1,2"]));
  });

  it("même tableau → MÊME référence de Set", () => {
    const walls: [number, number][] = [[1, 2]];
    const { result, rerender } = renderHook(() => useWallHexKeySet(walls));
    const first = result.current;
    rerender();
    expect(Object.is(result.current, first)).toBe(true);
  });

  // La mémoïsation se fie à la RÉFÉRENCE : la non-mutation de la source est verrouillée à sa
  // source, sur `buildEffectiveLosWallHexes` (cf. losPreviewHelpers.test.ts).
  it("tableau REMPLACÉ → Set recalculé, la case ajoutée est vue", () => {
    const walls: [number, number][] = [[1, 2]];
    const { result, rerender } = renderHook(
      (props: { walls: [number, number][] }) => useWallHexKeySet(props.walls),
      { initialProps: { walls } }
    );
    const first = result.current;
    rerender({ walls: [...walls, [7, 8]] });
    expect(Object.is(result.current, first)).toBe(false);
    expect(result.current.has("7,8")).toBe(true);
  });

  it("tableau absent → Set vide stable", () => {
    const { result, rerender } = renderHook(() => useWallHexKeySet(undefined));
    const first = result.current;
    rerender();
    expect(result.current.size).toBe(0);
    expect(Object.is(result.current, first)).toBe(true);
  });
});
