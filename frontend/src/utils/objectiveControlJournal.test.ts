import { describe, expect, it } from "vitest";
import { diffObjectiveControllers, objectiveControlMessage } from "./objectiveControlJournal";

describe("diffObjectiveControllers", () => {
  it("ne journalise rien sur le premier instantané quand toutes les zones sont contestées", () => {
    expect(diffObjectiveControllers({}, { West: null, North: null })).toEqual([]);
  });

  it("journalise une zone DÉJÀ contrôlée sur le premier instantané", () => {
    expect(diffObjectiveControllers({}, { West: 1, North: null })).toEqual([
      { zoneName: "West", controller: 1 },
    ]);
  });

  it("ne journalise rien quand l'instantané est identique au précédent", () => {
    expect(diffObjectiveControllers({ West: 1, North: 2 }, { West: 1, North: 2 })).toEqual([]);
  });

  it("journalise une prise, un changement de main et une perte de contrôle", () => {
    expect(
      diffObjectiveControllers(
        { West: null, North: 1, South: 2 },
        { West: 1, North: 2, South: null }
      )
    ).toEqual([
      { zoneName: "West", controller: 1 },
      { zoneName: "North", controller: 2 },
      { zoneName: "South", controller: null },
    ]);
  });

  it("traite une zone jamais vue comme non contrôlée, pas comme un changement fantôme", () => {
    expect(diffObjectiveControllers({ West: 1 }, { West: 1, North: null })).toEqual([]);
    expect(diffObjectiveControllers({ West: 1 }, { West: 1, North: 2 })).toEqual([
      { zoneName: "North", controller: 2 },
    ]);
  });

  it("ne se laisse pas piéger par le joueur 0 ni par une zone au nom numérique", () => {
    expect(diffObjectiveControllers({ "1": null }, { "1": 0 })).toEqual([
      { zoneName: "1", controller: 0 },
    ]);
  });
});

describe("objectiveControlMessage", () => {
  it("nomme le joueur qui contrôle", () => {
    expect(objectiveControlMessage({ zoneName: "West", controller: 2 })).toBe(
      "P2 controls objective West"
    );
  });

  it("dit « contested » quand personne ne contrôle", () => {
    expect(objectiveControlMessage({ zoneName: "West", controller: null })).toBe(
      "Objective West contested"
    );
  });
});
