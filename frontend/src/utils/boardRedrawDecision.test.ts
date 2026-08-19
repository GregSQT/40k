import { describe, expect, it } from "vitest";

import {
  buildBoardControlKey,
  buildBoardGeomKey,
  computeStaticLayerReusable,
  planBoardRedraw,
} from "./boardRedrawDecision";

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

const GEOM_BASE = {
  cols: 44,
  rows: 30,
  objectiveZonesGeomKey: "5:45:1234567",
  wallsFp: "12:98765432",
  isDeployment: false,
};

describe("buildBoardGeomKey / buildBoardControlKey / computeStaticLayerReusable", () => {
  it("la clé géométrie ne contient pas le contrôle d'objectif (capture simulée)", () => {
    const ocAfter = "ruin_center=1/1|rect_nw=n/n";
    const geomKey = buildBoardGeomKey(GEOM_BASE);
    // La valeur de contrôle est absente de la clé géom : les deux dimensions sont bien séparées
    expect(geomKey).not.toContain("ruin_center");
    expect(geomKey).not.toContain(ocAfter);
    // La clé contrôle, elle, encode bien la capture
    expect(buildBoardControlKey({ objectiveControlKeyForBoard: ocAfter })).toContain(
      "ruin_center=1/1"
    );
  });

  it("la clé contrôle change lors d'une capture d'objectif", () => {
    const ocBefore = "ruin_center=n/n|rect_nw=n/n";
    const ocAfter = "ruin_center=1/1|rect_nw=n/n";
    expect(buildBoardControlKey({ objectiveControlKeyForBoard: ocAfter })).not.toBe(
      buildBoardControlKey({ objectiveControlKeyForBoard: ocBefore })
    );
  });

  it("la clé géométrie change si les dimensions changent", () => {
    const a = buildBoardGeomKey(GEOM_BASE);
    const b = buildBoardGeomKey({ ...GEOM_BASE, cols: 55 });
    expect(b).not.toBe(a);
  });

  it("la clé géométrie change si les murs changent", () => {
    const a = buildBoardGeomKey(GEOM_BASE);
    const b = buildBoardGeomKey({ ...GEOM_BASE, wallsFp: "0:0" });
    expect(b).not.toBe(a);
  });

  it("computeStaticLayerReusable : faux si geomKey a changé", () => {
    const ctrl = buildBoardControlKey({ objectiveControlKeyForBoard: "oc" });
    expect(
      computeStaticLayerReusable({
        prevGeomKey: buildBoardGeomKey(GEOM_BASE),
        currGeomKey: buildBoardGeomKey({ ...GEOM_BASE, cols: 55 }),
        prevControlKey: ctrl,
        currControlKey: ctrl,
        staticLayerExists: true,
      })
    ).toBe(false);
  });

  it("computeStaticLayerReusable : faux si controlKey a changé (capture d'objectif)", () => {
    const geom = buildBoardGeomKey(GEOM_BASE);
    expect(
      computeStaticLayerReusable({
        prevGeomKey: geom,
        currGeomKey: geom,
        prevControlKey: buildBoardControlKey({ objectiveControlKeyForBoard: "ruin_center=n/n" }),
        currControlKey: buildBoardControlKey({ objectiveControlKeyForBoard: "ruin_center=1/1" }),
        staticLayerExists: true,
      })
    ).toBe(false);
  });

  it("computeStaticLayerReusable : faux si le conteneur n'existe pas", () => {
    const geom = buildBoardGeomKey(GEOM_BASE);
    const ctrl = buildBoardControlKey({ objectiveControlKeyForBoard: "oc" });
    expect(
      computeStaticLayerReusable({
        prevGeomKey: geom,
        currGeomKey: geom,
        prevControlKey: ctrl,
        currControlKey: ctrl,
        staticLayerExists: false,
      })
    ).toBe(false);
  });

  it("computeStaticLayerReusable : vrai si geom, contrôle et conteneur inchangés", () => {
    const geom = buildBoardGeomKey(GEOM_BASE);
    const ctrl = buildBoardControlKey({ objectiveControlKeyForBoard: "oc" });
    expect(
      computeStaticLayerReusable({
        prevGeomKey: geom,
        currGeomKey: geom,
        prevControlKey: ctrl,
        currControlKey: ctrl,
        staticLayerExists: true,
      })
    ).toBe(true);
  });
});
