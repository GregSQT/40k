/**
 * T9 — probabilityCalculator : invariants des formules de probabilité de dégâts.
 *
 * Fonctions pures (pas de DOM) : pas besoin de jsdom.
 */
import { describe, expect, it } from "vitest";
import type { Unit } from "../types/game";
import {
  calculateCombatHitProbability,
  calculateCombatOverallProbability,
  calculateCombatSaveProbability,
  calculateCombatWoundProbability,
  calculateHitProbability,
  calculateOverallProbability,
  calculateSaveProbability,
  calculateWoundProbability,
} from "./probabilityCalculator";

function pct(n: number, d: number) {
  return Math.max(0, ((7 - n) / d) * 100);
}

function makeShooter(atk: number, str: number, ap: number): Unit {
  return {
    id: 1,
    player: 1,
    RNG_WEAPONS: [{ display_name: "gun", NB: 1, ATK: atk, STR: str, AP: ap, DMG: 1 }],
    CC_WEAPONS: [],
    selectedRngWeaponIndex: 0,
    selectedCcWeaponIndex: 0,
  } as unknown as Unit;
}

function makeMeleeAtk(atk: number, str: number, ap: number): Unit {
  return {
    id: 1,
    player: 1,
    RNG_WEAPONS: [],
    CC_WEAPONS: [{ display_name: "sword", NB: 1, ATK: atk, STR: str, AP: ap, DMG: 1 }],
    selectedRngWeaponIndex: 0,
    selectedCcWeaponIndex: 0,
  } as unknown as Unit;
}

function makeTarget(t: number, armor: number, invul = 0): Unit {
  return {
    id: 2,
    player: 2,
    T: t,
    ARMOR_SAVE: armor,
    INVUL_SAVE: invul,
    RNG_WEAPONS: [],
    CC_WEAPONS: [],
  } as unknown as Unit;
}

// ---------------------------------------------------------------------------
// Hit probability
// ---------------------------------------------------------------------------

describe("calculateHitProbability (tir)", () => {
  it("ATK 3+ → (7-3)/6 × 100", () => {
    expect(calculateHitProbability(makeShooter(3, 4, 0))).toBeCloseTo(pct(3, 6), 5);
  });

  it("ATK 4+ → (7-4)/6 × 100 = 50 %", () => {
    expect(calculateHitProbability(makeShooter(4, 4, 0))).toBeCloseTo(50, 5);
  });

  it("ATK 7+ → 0 % (clamped)", () => {
    expect(calculateHitProbability(makeShooter(7, 4, 0))).toBe(0);
  });

  it("sans arme : repli sur ATK=4 (défaut arme manquante)", () => {
    const noWeapon: Unit = { id: 1, RNG_WEAPONS: [], CC_WEAPONS: [] } as unknown as Unit;
    expect(calculateHitProbability(noWeapon)).toBeCloseTo(50, 5);
  });
});

// ---------------------------------------------------------------------------
// Wound probability
// ---------------------------------------------------------------------------

describe("calculateWoundProbability (tir)", () => {
  it("STR ≥ T×2 → 2+ (5/6)", () => {
    expect(calculateWoundProbability(makeShooter(4, 8, 0), makeTarget(4, 5))).toBeCloseTo(
      pct(2, 6),
      5
    );
  });

  it("STR > T → 3+", () => {
    expect(calculateWoundProbability(makeShooter(4, 5, 0), makeTarget(4, 5))).toBeCloseTo(
      pct(3, 6),
      5
    );
  });

  it("STR == T → 4+ (50 %)", () => {
    expect(calculateWoundProbability(makeShooter(4, 4, 0), makeTarget(4, 5))).toBeCloseTo(50, 5);
  });

  it("STR < T → 5+", () => {
    expect(calculateWoundProbability(makeShooter(4, 3, 0), makeTarget(4, 5))).toBeCloseTo(
      pct(5, 6),
      5
    );
  });
});

// ---------------------------------------------------------------------------
// Save probability (retourne la probabilité d'ÉCHEC de sauvegarde)
// ---------------------------------------------------------------------------

describe("calculateSaveProbability (tir) — retourne P(save échoue)", () => {
  it("armor=3, AP=0 → modifiedArmor=3 → P(save réussit)=66.67 → P(échec)=33.33 %", () => {
    const failProb = calculateSaveProbability(makeShooter(4, 4, 0), makeTarget(4, 3));
    expect(failProb).toBeCloseTo(100 - pct(3, 6), 4);
  });

  it("armor=5, AP=2 → modifiedArmor=7 → P(réussit)=0 → P(échec)=100 %", () => {
    expect(calculateSaveProbability(makeShooter(4, 4, 2), makeTarget(4, 5))).toBeCloseTo(100, 4);
  });

  it("cover améliore la sauvegarde de 1 (armorSave-1, min 2)", () => {
    // armor=4, AP=0 sans couvert → modifiedArmor=4 → échec= 100-pct(4,6)
    // armor=3 avec couvert → modifiedArmor=3 → échec= 100-pct(3,6)
    const noCover = calculateSaveProbability(makeShooter(4, 4, 0), makeTarget(4, 4), false);
    const inCover = calculateSaveProbability(makeShooter(4, 4, 0), makeTarget(4, 4), true);
    expect(inCover).toBeLessThan(noCover);
    expect(inCover).toBeCloseTo(100 - pct(3, 6), 4);
  });

  it("invulnerable save utilisée si meilleure que l'armor+AP", () => {
    // armor=5, AP=3 → modifiedArmor=8 ; invul=3 < 8 → saveTarget=3
    const failProb = calculateSaveProbability(makeShooter(4, 4, 3), makeTarget(4, 5, 3));
    expect(failProb).toBeCloseTo(100 - pct(3, 6), 4);
  });

  it("invulnerable ignoré si armor+AP meilleur", () => {
    // armor=3, AP=0 → modifiedArmor=3 ; invul=4 > 3 → saveTarget=3 (l'armor gagne)
    const withInvul = calculateSaveProbability(makeShooter(4, 4, 0), makeTarget(4, 3, 4));
    const withoutInvul = calculateSaveProbability(makeShooter(4, 4, 0), makeTarget(4, 3, 0));
    expect(withInvul).toBeCloseTo(withoutInvul, 4);
  });
});

// ---------------------------------------------------------------------------
// Overall probability
// ---------------------------------------------------------------------------

describe("calculateOverallProbability (tir)", () => {
  it("est le produit hit × wound × saveFailProb", () => {
    const shooter = makeShooter(3, 4, 0);
    const target = makeTarget(4, 5);
    const hit = calculateHitProbability(shooter) / 100;
    const wound = calculateWoundProbability(shooter, target) / 100;
    const saveFail = calculateSaveProbability(shooter, target) / 100;
    const expected = hit * wound * saveFail * 100;
    expect(calculateOverallProbability(shooter, target)).toBeCloseTo(expected, 4);
  });

  it("est ≤ min(hit, wound, saveFailProb)", () => {
    const shooter = makeShooter(4, 4, 0);
    const target = makeTarget(4, 5);
    const overall = calculateOverallProbability(shooter, target);
    expect(overall).toBeLessThanOrEqual(calculateHitProbability(shooter));
    expect(overall).toBeLessThanOrEqual(calculateWoundProbability(shooter, target));
    expect(overall).toBeLessThanOrEqual(calculateSaveProbability(shooter, target));
  });
});

// ---------------------------------------------------------------------------
// Combat (mêlée) — symétrie attendue avec les formules de tir
// ---------------------------------------------------------------------------

describe("calculateCombatHitProbability / Wound / Save / Overall (mêlée)", () => {
  it("hit mêlée identique au tir pour le même ATK", () => {
    const meleeAtkr = makeMeleeAtk(3, 4, 0);
    const shootAtkr = makeShooter(3, 4, 0);
    expect(calculateCombatHitProbability(meleeAtkr)).toBeCloseTo(
      calculateHitProbability(shootAtkr),
      4
    );
  });

  it("wound mêlée identique au tir pour STR/T identiques", () => {
    const meleeAtkr = makeMeleeAtk(3, 5, 0);
    const shootAtkr = makeShooter(3, 5, 0);
    const target = makeTarget(4, 5);
    expect(calculateCombatWoundProbability(meleeAtkr, target)).toBeCloseTo(
      calculateWoundProbability(shootAtkr, target),
      4
    );
  });

  it("overall mêlée = hit × wound × saveFailProb", () => {
    const atk = makeMeleeAtk(4, 4, 1);
    const def = makeTarget(4, 4);
    const hit = calculateCombatHitProbability(atk) / 100;
    const wound = calculateCombatWoundProbability(atk, def) / 100;
    const fail = calculateCombatSaveProbability(atk, def) / 100;
    expect(calculateCombatOverallProbability(atk, def)).toBeCloseTo(hit * wound * fail * 100, 4);
  });
});
