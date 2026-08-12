import { describe, expect, it } from "vitest";

import { planBoardRedraw } from "./boardRedrawDecision";

const CAS = [
  { highlightsReusable: true, staticLayerReusable: true },
  { highlightsReusable: true, staticLayerReusable: false },
  { highlightsReusable: false, staticLayerReusable: true },
  { highlightsReusable: false, staticLayerReusable: false },
];

describe("planBoardRedraw", () => {
  it("REDESSINE quand seul le calque statique a changé", () => {
    // Défaut n°1 : une capture d'objectif ne touche QUE le calque statique. Les surbrillances
    // restent identiques (même unité sélectionnée, même phase, même preview), donc l'ancien
    // chemin sautait `drawBoard` et la zone ne changeait jamais de couleur.
    const plan = planBoardRedraw({ highlightsReusable: true, staticLayerReusable: false });
    expect(plan.callDrawBoard).toBe(true);
  });

  it("ne saute le redessin que si les DEUX calques sont réutilisables", () => {
    expect(
      planBoardRedraw({ highlightsReusable: true, staticLayerReusable: true }).callDrawBoard
    ).toBe(false);
    expect(
      planBoardRedraw({ highlightsReusable: false, staticLayerReusable: true }).callDrawBoard
    ).toBe(true);
    expect(
      planBoardRedraw({ highlightsReusable: false, staticLayerReusable: false }).callDrawBoard
    ).toBe(true);
  });

  it("ne conserve JAMAIS un calque que drawBoard va recréer", () => {
    // Défaut n°2, les deux moitiés. `drawBoard` ajoute toujours un nouveau conteneur de
    // surbrillances et de contours d'étage : en garder un pendant qu'elle tourne le laisse
    // orphelin ET visible (previews en double, alpha doublée).
    for (const cas of CAS) {
      const plan = planBoardRedraw(cas);
      if (plan.callDrawBoard) {
        expect(plan.keepHighlightLayers).toBe(false);
      }
    }
  });

  it("ne conserve le calque statique QUE s'il est encore valide", () => {
    // L'autre moitié du défaut n°2 : un statique périmé ré-attaché reste AU-DESSUS du neuf
    // (`addChildAt(_, 0)` + zIndex égaux + tri stable), donc l'ancienne couleur masque la
    // nouvelle. Le conserver ne doit dépendre QUE de sa propre validité.
    for (const cas of CAS) {
      expect(planBoardRedraw(cas).keepStaticLayer).toBe(cas.staticLayerReusable);
    }
  });

  it("garde les deux calques quand rien n'a changé", () => {
    expect(planBoardRedraw({ highlightsReusable: true, staticLayerReusable: true })).toEqual({
      callDrawBoard: false,
      keepStaticLayer: true,
      keepHighlightLayers: true,
    });
  });
});
