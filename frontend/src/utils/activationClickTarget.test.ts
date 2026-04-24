import { describe, expect, it } from "vitest";
import {
  getActiveFightUnitIdString,
  getFightAttackerAttackLeft,
  isFightAttackSelectionUiOpen,
} from "./activationClickTarget";

describe("isFightAttackSelectionUiOpen", () => {
  it("ouvre si mode attackPreview", () => {
    expect(isFightAttackSelectionUiOpen("attackPreview", null)).toBe(true);
  });
  it("ouvre si attackPreview défini même en mode select", () => {
    expect(isFightAttackSelectionUiOpen("select", { unitId: 1, col: 0, row: 0 })).toBe(true);
  });
  it("fermé si select et pas de preview", () => {
    expect(isFightAttackSelectionUiOpen("select", null)).toBe(false);
  });
});

describe("getActiveFightUnitIdString", () => {
  const base = {
    current_player: 1,
    phase: "fight" as const,
    units: [],
    active_fight_unit: "7",
  };

  it("préfère preferred quand présent", () => {
    const preferred = { ...base, active_fight_unit: "9" };
    expect(getActiveFightUnitIdString(preferred, base)).toBe("9");
  });
  it("retombe sur base si preferred sans active", () => {
    expect(getActiveFightUnitIdString({ ...base, active_fight_unit: undefined }, base)).toBe("7");
  });
  it("null si vide", () => {
    expect(getActiveFightUnitIdString(null, { ...base, active_fight_unit: "" })).toBe(null);
  });
  it("ignore preferred vide et retombe sur base", () => {
    expect(
      getActiveFightUnitIdString(
        { ...base, active_fight_unit: "" },
        base
      )
    ).toBe("7");
  });
  it("ignore preferred chaîne blanche", () => {
    expect(
      getActiveFightUnitIdString(
        { ...base, active_fight_unit: "  " },
        base
      )
    ).toBe("7");
  });
});

describe("getFightAttackerAttackLeft", () => {
  const gs = {
    current_player: 1,
    units: [
      { id: 1, player: 1, ATTACK_LEFT: 2 },
      { id: "2", player: 2, ATTACK_LEFT: 0 },
    ],
  };

  it("lit ATTACK_LEFT par id numérique", () => {
    expect(getFightAttackerAttackLeft(gs, 1)).toBe(2);
  });
  it("lit par id string", () => {
    expect(getFightAttackerAttackLeft(gs, 2)).toBe(0);
  });
  it("undefined si inconnu", () => {
    expect(getFightAttackerAttackLeft(gs, 99)).toBeUndefined();
  });
});
