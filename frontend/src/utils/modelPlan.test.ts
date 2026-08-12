import { describe, expect, it } from "vitest";
import { toPlanArray, toPlanArrayWithOrientation } from "./modelPlan";

/**
 * L'encodeur de plan est la SOURCE UNIQUE de l'encodage envoyé au backend. Le dépôt a déjà payé
 * sa duplication : deux dialectes de défaut pour l'étage (`?? 0` contre le niveau de VUE), soit
 * l'étage inventé que la frontière backend rejette. Ces tests fixent le contrat pour que la
 * prochaine copie — si elle a lieu — diverge visiblement au lieu de diverger en silence.
 */
describe("toPlanArray", () => {
  it("envoie TOUJOURS l'étage, même absent du plan (le backend refuse une entrée muette)", () => {
    expect(toPlanArray({ m1: { col: 3, row: 4 } })).toEqual([["m1", 3, 4, 0]]);
  });

  it("respecte l'étage du plan quand il est porté", () => {
    expect(toPlanArray({ m1: { col: 3, row: 4, level: 1 } })).toEqual([["m1", 3, 4, 1]]);
  });

  it("utilise le niveau de repli fourni, et non 0, quand le plan est muet", () => {
    expect(toPlanArray({ m1: { col: 3, row: 4 } }, 2)).toEqual([["m1", 3, 4, 2]]);
  });

  it("n'écrase pas un étage explicite par le niveau de repli", () => {
    expect(toPlanArray({ m1: { col: 3, row: 4, level: 0 } }, 2)).toEqual([["m1", 3, 4, 0]]);
  });

  it("encode toutes les figurines du plan", () => {
    expect(toPlanArray({ a: { col: 1, row: 1, level: 1 }, b: { col: 2, row: 2 } })).toEqual([
      ["a", 1, 1, 1],
      ["b", 2, 2, 0],
    ]);
  });
});

describe("toPlanArrayWithOrientation", () => {
  it("rend `null` quand le plan ne pivote pas — « inchangée », jamais un 0 inventé", () => {
    expect(toPlanArrayWithOrientation({ m1: { col: 3, row: 4, level: 1 } })).toEqual([
      ["m1", 3, 4, 1, null],
    ]);
  });

  it("transporte l'orientation du plan quand elle existe (pivot molette)", () => {
    expect(
      toPlanArrayWithOrientation({ m1: { col: 3, row: 4, level: 0, orientation: 2 } })
    ).toEqual([["m1", 3, 4, 0, 2]]);
  });

  it("conserve une orientation 0 explicite (face nord), qui n'est pas « absente »", () => {
    expect(toPlanArrayWithOrientation({ m1: { col: 3, row: 4, orientation: 0 } })).toEqual([
      ["m1", 3, 4, 0, 0],
    ]);
  });

  it("garde le même encodage des 4 premiers éléments que `toPlanArray`", () => {
    const models = { a: { col: 5, row: 6, level: 1 }, b: { col: 7, row: 8 } };
    const withOrientation = toPlanArrayWithOrientation(models).map(([m, c, r, l]) => [m, c, r, l]);
    expect(withOrientation).toEqual(toPlanArray(models));
  });
});
