import { describe, expect, it } from "vitest";

import { canSkipBoardRedraw } from "./boardRedrawDecision";

describe("canSkipBoardRedraw", () => {
  it("REFUSE de sauter le redessin quand seul le calque statique a changé", () => {
    // C'est le défaut corrigé : une capture d'objectif ne touche QUE le calque statique.
    // Les surbrillances restent identiques (même unité sélectionnée, même phase, même preview),
    // donc l'ancien chemin sautait `drawBoard` et la zone ne changeait jamais de couleur.
    expect(canSkipBoardRedraw({ highlightsReusable: true, staticLayerReusable: false })).toBe(
      false
    );
  });

  it("saute le redessin seulement quand les DEUX calques sont réutilisables", () => {
    expect(canSkipBoardRedraw({ highlightsReusable: true, staticLayerReusable: true })).toBe(true);
  });

  it("REFUSE de sauter le redessin quand les surbrillances ont changé", () => {
    expect(canSkipBoardRedraw({ highlightsReusable: false, staticLayerReusable: true })).toBe(
      false
    );
    expect(canSkipBoardRedraw({ highlightsReusable: false, staticLayerReusable: false })).toBe(
      false
    );
  });
});
