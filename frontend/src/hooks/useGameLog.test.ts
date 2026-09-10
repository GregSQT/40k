import { describe, expect, it } from "vitest";

import { baseEntryFromLogData } from "./useGameLog";

/**
 * Une sauvegarde SAUTÉE l'est quel que soit le motif.
 *
 * Le filtre n'acceptait que `DEVASTATING_WOUNDS` : tout autre motif retombait sur le calcul
 * normal, qui dérive `saveSuccess` d'un `saveRoll` ne décidant de rien. Le moteur pose les deux
 * champs ensemble — c'est le drapeau qui fait foi, pas la valeur du motif.
 */
describe("baseEntryFromLogData — sauvegarde sautée", () => {
  const base = {
    hitRoll: 4,
    woundRoll: 6,
    // Un jet qui PASSERAIT le seuil : sans la correction, la sauvegarde est comptée réussie.
    saveRoll: 6,
    saveTarget: 3,
    damage: 2,
  };

  it("ne compte pas de sauvegarde réussie quand le moteur l'a sautée", () => {
    const entry = baseEntryFromLogData({
      ...base,
      saveSkipped: true,
      saveSkipReason: "DEVASTATING_WOUNDS",
    });
    const shot = (entry.shootDetails as Array<Record<string, unknown>>)[0];
    expect(shot.saveSuccess).toBe(false);
  });

  it("vaut pour tout motif, pas seulement DEVASTATING_WOUNDS", () => {
    const entry = baseEntryFromLogData({
      ...base,
      saveSkipped: true,
      saveSkipReason: "UN_AUTRE_MOTIF",
    });
    const shot = (entry.shootDetails as Array<Record<string, unknown>>)[0];
    expect(shot.saveSuccess).toBe(false);
  });

  it("laisse le calcul normal opérer quand aucune sauvegarde n'est sautée", () => {
    const entry = baseEntryFromLogData({ ...base, saveSkipped: false });
    const shot = (entry.shootDetails as Array<Record<string, unknown>>)[0];
    expect(shot.saveSuccess).toBe(true);
  });
});
