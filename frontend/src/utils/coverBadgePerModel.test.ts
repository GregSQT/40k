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
import { modelCoverBadge } from "./coverBadgePerModel";

/** 4 figurines dans le terrain (condition "a"), 1 à découvert — la 3e, volontairement pas la dernière. */
const FOUR_IN_TERRAIN_ONE_EXPOSED: ModelCoverCondition[] = ["a", "a", "", "a", "a"];

describe("modelCoverBadge — escouade 4-dans-terrain / 1-dehors", () => {
  it("n'affiche AUCUN badge sur la figurine à découvert", () => {
    expect(modelCoverBadge(2, FOUR_IN_TERRAIN_ONE_EXPOSED, false)).toBe("none");
  });

  it("distingue les 4 figurines protégées, sans leur promettre le -1 BS que l'unité n'a pas", () => {
    for (const index of [0, 1, 3, 4]) {
      expect(modelCoverBadge(index, FOUR_IN_TERRAIN_ONE_EXPOSED, false)).toBe("cover-unqualified");
    }
  });

  it("ne prétend jamais qu'une figurine individuelle bénéficie du couvert quand l'unité ne qualifie pas", () => {
    // Le critère central : sur toute l'escouade, aucun badge PLEIN — c'est-à-dire aucune
    // affirmation de -1 BS — alors que l'unité n'a pas le couvert.
    const badges = FOUR_IN_TERRAIN_ONE_EXPOSED.map((_c, i) =>
      modelCoverBadge(i, FOUR_IN_TERRAIN_ONE_EXPOSED, false)
    );
    expect(badges).not.toContain("cover");
    expect(badges).toEqual([
      "cover-unqualified",
      "cover-unqualified",
      "none",
      "cover-unqualified",
      "cover-unqualified",
    ]);
  });
});

describe("modelCoverBadge — unité qui qualifie", () => {
  it("affiche le badge plein sur chaque figurine quand toutes remplissent une condition", () => {
    const conditions: ModelCoverCondition[] = ["a", "b", "a", "b", "a"];
    const badges = conditions.map((_c, i) => modelCoverBadge(i, conditions, true));
    expect(badges).toEqual(["cover", "cover", "cover", "cover", "cover"]);
  });

  it("traite (b) — pas entièrement visible — exactement comme (a)", () => {
    expect(modelCoverBadge(0, ["b"], true)).toBe("cover");
    expect(modelCoverBadge(0, ["b"], false)).toBe("cover-unqualified");
  });
});

describe("modelCoverBadge — absence de détail par figurine", () => {
  it("retombe sur le booléen d'unité quand le moteur ne fournit pas les conditions", () => {
    // Couvert calculé côté WASM : pas de détail par figurine. On garde le comportement
    // historique plutôt que de reconstruire un second modèle de couvert côté client.
    expect(modelCoverBadge(0, null, true)).toBe("cover");
    expect(modelCoverBadge(3, null, true)).toBe("cover");
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
