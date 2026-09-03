/**
 * Verrou de la sémantique du badge de couvert par figurine (règle 13.08).
 *
 * Le cas qui motive tout le fichier : une escouade de 5 Terminators, 4 figurines dans une terrain
 * area et 1 à découvert. 13.08 exige que CHAQUE figurine remplisse une condition, donc l'unité
 * perd le couvert. L'affichage répliquait ce booléen d'unité sur chaque figurine, si bien
 * qu'AUCUNE des 4 figurines visiblement à l'abri n'affichait de badge — le joueur y lisait une
 * inversion.
 */
import { describe, expect, it } from "vitest";
import type { ModelCoverCondition } from "../types/game";
import { coverConditionsFingerprint, modelCoverBadge } from "./coverBadgePerModel";

/** 4 figurines dans le terrain (condition "a"), 1 à découvert — la 3e, volontairement pas la dernière. */
const FOUR_IN_TERRAIN_ONE_EXPOSED: ModelCoverCondition[] = ["a", "a", "", "a", "a"];

describe("modelCoverBadge — escouade 4-dans-terrain / 1-dehors", () => {
  it("n'affiche AUCUN badge sur la figurine à découvert", () => {
    expect(modelCoverBadge(2, FOUR_IN_TERRAIN_ONE_EXPOSED, false)).toBe("none");
  });

  it("distingue les 4 figurines protégées (condition a), sans leur promettre le -1 BS que l'unité n'a pas", () => {
    for (const index of [0, 1, 3, 4]) {
      expect(modelCoverBadge(index, FOUR_IN_TERRAIN_ONE_EXPOSED, false)).toBe(
        "cover-unqualified-a"
      );
    }
  });

  it("ne prétend jamais qu'une figurine individuelle bénéficie du couvert quand l'unité ne qualifie pas", () => {
    // Le critère central : sur toute l'escouade, aucun badge PLEIN — c'est-à-dire aucune
    // affirmation de -1 BS — alors que l'unité n'a pas le couvert.
    const badges = FOUR_IN_TERRAIN_ONE_EXPOSED.map((_c, i) =>
      modelCoverBadge(i, FOUR_IN_TERRAIN_ONE_EXPOSED, false)
    );
    expect(badges).not.toContain("cover-a");
    expect(badges).not.toContain("cover-b");
    expect(badges).toEqual([
      "cover-unqualified-a",
      "cover-unqualified-a",
      "none",
      "cover-unqualified-a",
      "cover-unqualified-a",
    ]);
  });
});

describe("modelCoverBadge — unité qui qualifie", () => {
  it("préserve la condition (a/b) dans le badge quand l'unité qualifie", () => {
    const conditions: ModelCoverCondition[] = ["a", "b", "a", "b", "a"];
    const badges = conditions.map((_c, i) => modelCoverBadge(i, conditions, true));
    expect(badges).toEqual(["cover-a", "cover-b", "cover-a", "cover-b", "cover-a"]);
  });

  it("distingue (a) terrain de (b) visibilité dans le badge — condition portée dans le type", () => {
    expect(modelCoverBadge(0, ["a"], true)).toBe("cover-a");
    expect(modelCoverBadge(0, ["b"], true)).toBe("cover-b");
    expect(modelCoverBadge(0, ["a"], false)).toBe("cover-unqualified-a");
    expect(modelCoverBadge(0, ["b"], false)).toBe("cover-unqualified-b");
  });
});

describe("modelCoverBadge — absence de détail par figurine", () => {
  it("retombe sur le booléen d'unité quand le moteur ne fournit pas les conditions (glyphe œil par défaut)", () => {
    // Couvert calculé côté WASM : pas de détail par figurine. On garde le comportement
    // historique (œil) plutôt que de reconstruire un second modèle de couvert côté client.
    expect(modelCoverBadge(0, null, true)).toBe("cover-b");
    expect(modelCoverBadge(3, null, true)).toBe("cover-b");
    expect(modelCoverBadge(0, null, false)).toBe("none");
  });

  it("n'invente pas de couvert pour une figurine que le moteur n'a pas décrite", () => {
    // Liste plus courte que l'escouade rendue (cible non vue, rendu en retard d'un tick).
    expect(modelCoverBadge(4, ["a", "a"], true)).toBe("none");
    expect(modelCoverBadge(4, [], true)).toBe("none");
  });
});

describe("modelCoverBadge — escouade entièrement à découvert", () => {
  it("n'affiche aucun badge", () => {
    const conditions: ModelCoverCondition[] = ["", "", ""];
    const badges = conditions.map((_c, i) => modelCoverBadge(i, conditions, false));
    expect(badges).toEqual(["none", "none", "none"]);
  });
});

describe("coverConditionsFingerprint", () => {
  it("distingue deux escouades où ce n'est pas la même figurine qui est exposée", () => {
    // `""` est une valeur, pas une absence : une concaténation sans séparateur rendait ces deux
    // états identiques, donc aucun redraw — le badge restait sur la mauvaise figurine.
    expect(coverConditionsFingerprint({ "7": ["b", ""] })).not.toBe(
      coverConditionsFingerprint({ "7": ["", "b"] })
    );
    expect(coverConditionsFingerprint({ "7": ["a", "a", "", "a", "a"] })).not.toBe(
      coverConditionsFingerprint({ "7": ["a", "a", "a", "a", ""] })
    );
  });

  it("distingue une escouade de celle obtenue après la mort d'une figurine", () => {
    // Deux figurines exposées, une meurt : le couvert d'unité reste false et le jeu de cibles
    // ne bouge pas, mais tous les index suivants ont glissé.
    expect(coverConditionsFingerprint({ "7": ["a", "", "a", ""] })).not.toBe(
      coverConditionsFingerprint({ "7": ["a", "", "a"] })
    );
    expect(coverConditionsFingerprint({ "7": ["a", "a"] })).not.toBe(
      coverConditionsFingerprint({ "7": ["a", "a", ""] })
    );
  });

  it("est stable quel que soit l'ordre d'insertion des unités", () => {
    const a: Record<string, ModelCoverCondition[]> = { "3": ["a"], "11": ["b", ""] };
    const b: Record<string, ModelCoverCondition[]> = { "11": ["b", ""], "3": ["a"] };
    expect(coverConditionsFingerprint(a)).toBe(coverConditionsFingerprint(b));
  });

  it("distingue deux unités différentes portant les mêmes conditions", () => {
    expect(coverConditionsFingerprint({ "3": ["a", ""] })).not.toBe(
      coverConditionsFingerprint({ "4": ["a", ""] })
    );
  });

  it("rend la même empreinte pour un état inchangé (pas de redraw parasite)", () => {
    const state: Record<string, ModelCoverCondition[]> = { "7": ["a", "a", "", "a", "a"] };
    expect(coverConditionsFingerprint(state)).toBe(
      coverConditionsFingerprint({ "7": ["a", "a", "", "a", "a"] })
    );
    expect(coverConditionsFingerprint({})).toBe(coverConditionsFingerprint({}));
  });
});
