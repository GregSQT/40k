import { describe, expect, it } from "vitest";

import type { Unit } from "../types/game";
import {
  HP_BLINK_STAGE_Z_INDEX,
  buildChargeMinRollOverlay,
  buildWeaponSignature,
  calculateDamagePerAttack,
  calculateWoundProbability,
} from "./blinkingHPBar";

// ─── buildChargeMinRollOverlay ────────────────────────────────────────────────

describe("buildChargeMinRollOverlay", () => {
  const MAX_INCHES = 12;
  const SUBHEX = 10;

  it("returns — when distance is zero (adjacent)", () => {
    const r = buildChargeMinRollOverlay(0, MAX_INCHES, SUBHEX);
    expect(r.primaryText).toBe("—");
    expect(r.tooltipText).toMatch(/adjacent/i);
  });

  it("returns — when distance is negative", () => {
    const r = buildChargeMinRollOverlay(-5, MAX_INCHES, SUBHEX);
    expect(r.primaryText).toBe("—");
  });

  it("returns — when distance exceeds max range", () => {
    const r = buildChargeMinRollOverlay(130, MAX_INCHES, SUBHEX); // 130 sous-hex > 12*10=120
    expect(r.primaryText).toBe("—");
    expect(r.tooltipText).toMatch(/au-delà/i);
  });

  it("returns minimum roll for normal distance", () => {
    const r = buildChargeMinRollOverlay(50, MAX_INCHES, SUBHEX); // 50/10 = 5 pouces → 5+
    expect(r.primaryText).toBe("5+");
    expect(r.tooltipText).toContain("5");
  });

  it("enforces minimum roll of 2+ (2D6 minimum)", () => {
    const r = buildChargeMinRollOverlay(5, MAX_INCHES, SUBHEX); // 5/10 = 0.5 → ceil = 1 → max(2,1) = 2
    expect(r.primaryText).toBe("2+");
  });

  it("returns 12+ at maximum range", () => {
    const r = buildChargeMinRollOverlay(120, MAX_INCHES, SUBHEX); // 120/10 = 12 → 12+
    expect(r.primaryText).toBe("12+");
  });

  it("handles inchesToSubhex=1 (Board standard)", () => {
    const r = buildChargeMinRollOverlay(8, 12, 1); // 8/1 = 8 → 8+
    expect(r.primaryText).toBe("8+");
  });
});

// ─── buildWeaponSignature ─────────────────────────────────────────────────────

describe("buildWeaponSignature", () => {
  it("builds deterministic signature from weapon fields", () => {
    const sig = buildWeaponSignature({
      display_name: "Bolter",
      ATK: 4,
      STR: 4,
      AP: 0,
      DMG: 1,
      NB: 2,
    });
    expect(sig).toBe("Bolter|4|4|0|1|2");
  });

  it("two identical weapons produce identical signatures", () => {
    const weapon = { display_name: "Lascannon", ATK: 1, STR: 9, AP: 3, DMG: "D6" as const, NB: 1 };
    expect(buildWeaponSignature(weapon)).toBe(buildWeaponSignature(weapon));
  });

  it("different weapons produce different signatures", () => {
    const a = buildWeaponSignature({ display_name: "A", ATK: 3, STR: 4, AP: 0, DMG: 1, NB: 1 });
    const b = buildWeaponSignature({ display_name: "B", ATK: 3, STR: 4, AP: 0, DMG: 1, NB: 1 });
    expect(a).not.toBe(b);
  });
});

// ─── calculateWoundProbability ────────────────────────────────────────────────

describe("calculateWoundProbability", () => {
  const target = {
    id: 2,
    player: 2,
    HP_CUR: 3,
    HP_MAX: 3,
    T: 4,
    ARMOR_SAVE: 3,
    INVUL_SAVE: undefined,
    RNG_WEAPONS: [],
    MEL_WEAPONS: [],
  } as unknown as Unit;

  it("returns 0 when attacker has no melee weapon (fight phase)", () => {
    const attacker = {
      id: 1,
      player: 1,
      CC_WEAPONS: [],
    } as unknown as Unit;
    expect(calculateWoundProbability(attacker, target, "fight")).toBe(0);
  });

  it("returns 0 when attacker has no ranged weapon (shoot phase)", () => {
    const attacker = {
      id: 1,
      player: 1,
      RNG_WEAPONS: [],
      MEL_WEAPONS: [],
    } as unknown as Unit;
    expect(calculateWoundProbability(attacker, target, "shoot")).toBe(0);
  });

  it("returns value between 0 and 1 for valid melee attacker", () => {
    const attacker = {
      id: 1,
      player: 1,
      CC_WEAPONS: [{ id: "m1", display_name: "Fists", ATK: 4, STR: 4, AP: 0, DMG: 1, NB: 1 }],
    } as unknown as Unit;
    const prob = calculateWoundProbability(attacker, target, "fight");
    expect(prob).toBeGreaterThanOrEqual(0);
    expect(prob).toBeLessThanOrEqual(1);
  });

  it("melee equal STR/T, normal save → hit 3/6 × wound 3/6 × fail 2/6 = 1/12", () => {
    // ATK=4 → hit=(7-4)/6=0.5 | STR=T=4 → wound=3/6 | ARMOR=3 AP=0 → save=3 → fail=2/6
    const attacker = {
      id: 1, player: 1,
      CC_WEAPONS: [{ id: "m1", display_name: "Fists", ATK: 4, STR: 4, AP: 0, DMG: 1, NB: 1 }],
    } as unknown as Unit;
    expect(calculateWoundProbability(attacker, target, "fight")).toBeCloseTo(1 / 12, 5);
  });

  it("melee STR double T, AP strips save → hit 5/6 × wound 5/6 × fail 1/6 = 25/216", () => {
    // ATK=2 → hit=5/6 | STR=8 >= T*2=8 → wound=5/6 | ARMOR=5 AP=3 → save=max(2,2)=2 → fail=1/6
    const attacker = {
      id: 1, player: 1,
      CC_WEAPONS: [{ id: "m2", display_name: "Power Fist", ATK: 2, STR: 8, AP: 3, DMG: 2, NB: 1 }],
    } as unknown as Unit;
    const toughTarget = { ...target, ARMOR_SAVE: 5 } as unknown as Unit;
    expect(calculateWoundProbability(attacker, toughTarget, "fight")).toBeCloseTo(25 / 216, 5);
  });

  it("melee STR < T, invuln save active → hit 4/6 × wound 2/6 × fail 2/6 = 16/216", () => {
    // ATK=3 → hit=4/6 | STR=3 < T=5 → wound=2/6 | ARMOR=3 AP=0 INVUL=5 → save=max(2,min(3,5))=3 → fail=2/6
    const attacker = {
      id: 1, player: 1,
      CC_WEAPONS: [{ id: "m3", display_name: "Scratch", ATK: 3, STR: 3, AP: 0, DMG: 1, NB: 1 }],
    } as unknown as Unit;
    const invulTarget = { ...target, T: 5, ARMOR_SAVE: 3, INVUL_SAVE: 5 } as unknown as Unit;
    expect(calculateWoundProbability(attacker, invulTarget, "fight")).toBeCloseTo(16 / 216, 5);
  });
});

// ─── calculateDamagePerAttack ─────────────────────────────────────────────────

describe("calculateDamagePerAttack", () => {
  const target = { id: 2, player: 2, HP_CUR: 3, HP_MAX: 3, T: 4, ARMOR_SAVE: 3, RNG_WEAPONS: [], MEL_WEAPONS: [] } as unknown as Unit;

  it("returns 0 when attacker has no melee weapon (fight phase)", () => {
    const attacker = { id: 1, player: 1, CC_WEAPONS: [] } as unknown as Unit;
    expect(calculateDamagePerAttack(attacker, target, "fight")).toBe(0);
  });

  it("returns numeric damage for fixed DMG melee weapon", () => {
    const attacker = {
      id: 1,
      player: 1,
      CC_WEAPONS: [{ id: "m1", display_name: "Sword", ATK: 4, STR: 4, AP: 0, DMG: 2, NB: 1 }],
    } as unknown as Unit;
    expect(calculateDamagePerAttack(attacker, target, "fight")).toBe(2);
  });
});

// ─── HP_BLINK_STAGE_Z_INDEX ───────────────────────────────────────────────────

describe("HP_BLINK_STAGE_Z_INDEX", () => {
  it("is above units layer (2000) and drag layer (9000)", () => {
    expect(HP_BLINK_STAGE_Z_INDEX).toBeGreaterThan(9000);
  });
});
