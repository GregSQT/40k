import { describe, expect, it } from "vitest";

import { heldObjectiveLabels } from "./heldObjectives";

/**
 * Les données de ces tests sont celles MESURÉES sur le scénario PvE (`terrain-mc1.json`) :
 * ids réels, noms réels, et l'état de contrôle réellement rendu par le moteur au tour 1.
 * Un jeu de données inventé ne prouverait que sa propre cohérence.
 */
const OBJECTIFS_PVE = [
  { id: "rect_b_nw_OK", name: "rect b NW" },
  { id: "rect_b_ne_OK", name: "rect b NE" },
  { id: "ruin_center_OK", name: " tri_2 Centre" },
  { id: "rect_b_sw_OK", name: "rect b SW" },
  { id: "rect_b_se_OK", name: "rect b SE" },
];

const CONTROLE_MESURE = {
  rect_b_nw_OK: null,
  rect_b_ne_OK: null,
  ruin_center_OK: 1,
  rect_b_sw_OK: null,
  rect_b_se_OK: 1,
};

describe("heldObjectiveLabels", () => {
  it("rend les objectifs tenus par le joueur, dans l'ordre du scénario", () => {
    expect(heldObjectiveLabels(CONTROLE_MESURE, OBJECTIFS_PVE, 1)).toEqual([
      "tri_2 Centre",
      "rect b SE",
    ]);
  });

  it("rend une liste vide pour le joueur qui ne tient rien", () => {
    expect(heldObjectiveLabels(CONTROLE_MESURE, OBJECTIFS_PVE, 2)).toEqual([]);
  });

  it("retombe sur l'id quand les noms ne sont pas dans la réponse", () => {
    // L'API omet `objectives` des réponses POST /api/game/action : l'affichage doit rester
    // exact, pas disparaître.
    expect(heldObjectiveLabels(CONTROLE_MESURE, undefined, 1)).toEqual([
      "ruin_center_OK",
      "rect_b_se_OK",
    ]);
  });

  it("ne confond pas « non contrôlé » avec « contrôlé par le joueur 0 »", () => {
    expect(heldObjectiveLabels({ a: null }, [{ id: "a", name: "A" }], 0)).toEqual([]);
  });

  it("rend une liste vide tant que le moteur n'a rien déterminé", () => {
    // Avant la première frontière de phase, `objective_controllers` n'existe pas (14.02 :
    // aucun objectif n'est contrôlé au début de la bataille).
    expect(heldObjectiveLabels(undefined, OBJECTIFS_PVE, 1)).toEqual([]);
  });
});
