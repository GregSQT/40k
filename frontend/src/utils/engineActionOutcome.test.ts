import { describe, expect, it } from "vitest";
import { readEngineActionOutcome } from "./engineActionOutcome";

describe("readEngineActionOutcome", () => {
  it("un résultat sans refus est un succès", () => {
    expect(readEngineActionOutcome({ success: true })).toEqual({ kind: "ok" });
    // `executeAction` peut rendre une enveloppe sans `success` (réponse déjà traitée en amont).
    expect(readEngineActionOutcome({})).toEqual({ kind: "ok" });
  });

  it("un refus moteur porte le message du moteur", () => {
    expect(readEngineActionOutcome({ success: false, error: "unit already deployed" })).toEqual({
      kind: "refused",
      message: "unit already deployed",
    });
  });

  it("un refus sans raison ne fabrique pas de diagnostic", () => {
    expect(readEngineActionOutcome({ success: false })).toEqual({
      kind: "refused",
      message: "unknown",
    });
  });

  // Le cœur du sujet : `undefined` n'est NI un succès NI un refus. Le prendre pour un succès fait
  // appliquer les effets de bord d'une action qui n'a pas eu lieu ; le prendre pour un refus
  // ouvre le panneau d'erreur fatal sur une non-action délibérée (aperçu de sauvegarde actif,
  // `game_over`) et écrase le vrai message réseau.
  it("undefined est une NON-ACTION, ni succès ni refus", () => {
    expect(readEngineActionOutcome(undefined)).toEqual({ kind: "noop" });
  });

  it("null aussi", () => {
    expect(readEngineActionOutcome(null)).toEqual({ kind: "noop" });
  });
});
