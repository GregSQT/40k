// frontend/src/utils/probabilityCalculator.ts

import type { Unit, Weapon } from "../types/game";
import { getDiceAverage, getSelectedMeleeWeapon, getSelectedRangedWeapon } from "./weaponHelpers";

export function calculateHitProbability(shooter: Unit): number {
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get ATK from selected weapon
  const selectedWeapon = getSelectedRangedWeapon(shooter);
  const hitTarget = selectedWeapon?.ATK || 4;
  return Math.max(0, ((7 - hitTarget) / 6) * 100);
}

export function calculateWoundProbability(shooter: Unit, target: Unit): number {
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get STR from selected weapon
  const selectedWeapon = getSelectedRangedWeapon(shooter);
  const strength = selectedWeapon?.STR || 4;
  const toughness = target.T || 4;

  let woundTarget: number;
  if (strength >= toughness * 2) woundTarget = 2;
  else if (strength > toughness) woundTarget = 3;
  else if (strength === toughness) woundTarget = 4;
  else if (strength < toughness) woundTarget = 5;
  else woundTarget = 6;

  return Math.max(0, ((7 - woundTarget) / 6) * 100);
}

export function calculateSaveProbability(
  shooter: Unit,
  target: Unit,
  inCover: boolean = false
): number {
  let armorSave = target.ARMOR_SAVE || 5;
  const invulSave = target.INVUL_SAVE || 0;
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get AP from selected weapon
  const selectedWeapon = getSelectedRangedWeapon(shooter);
  const armorPenetration = selectedWeapon?.AP || 0;

  // Apply cover bonus - +1 to armor save (better save)
  if (inCover) {
    armorSave = Math.max(2, armorSave - 1); // Improve armor save by 1, minimum 2+
    // Note: Invulnerable saves are not affected by cover
  }

  const modifiedArmor = armorSave + armorPenetration;
  const saveTarget = invulSave > 0 && invulSave < modifiedArmor ? invulSave : modifiedArmor;

  const saveProbability = Math.max(0, ((7 - saveTarget) / 6) * 100);
  return 100 - saveProbability;
}

export function calculateOverallProbability(
  shooter: Unit,
  target: Unit,
  inCover: boolean = false
): number {
  const hitProb = calculateHitProbability(shooter);
  const woundProb = calculateWoundProbability(shooter, target);
  const saveFailProb = calculateSaveProbability(shooter, target, inCover);

  return (hitProb / 100) * (woundProb / 100) * (saveFailProb / 100) * 100;
}

export interface RangedWeaponEffectiveness {
  weapon: Weapon;
  index: number;
  hitProbability: number;
  woundProbability: number;
  saveProbability: number;
  overallProbability: number;
  expectedDamage: number;
  potentialDamage: number;
}

function calculateRangedEffectiveness(
  weapon: Weapon,
  _index: number,
  target: Unit,
  inCover: boolean = false
): Omit<RangedWeaponEffectiveness, "weapon" | "index"> {
  const hitProbability = Math.max(0, (7 - weapon.ATK) / 6);
  const strength = weapon.STR;
  const toughness = target.T || 4;

  let woundTarget: number;
  if (strength >= toughness * 2) woundTarget = 2;
  else if (strength > toughness) woundTarget = 3;
  else if (strength === toughness) woundTarget = 4;
  else if (strength < toughness) woundTarget = 5;
  else woundTarget = 6;

  const woundProbability = Math.max(0, (7 - woundTarget) / 6);

  let armorSave = target.ARMOR_SAVE || 5;
  const invulSave = target.INVUL_SAVE || 0;
  const armorPenetration = weapon.AP;

  if (inCover) {
    armorSave = Math.max(2, armorSave - 1);
  }

  const modifiedArmor = armorSave + armorPenetration;
  const saveTarget = Math.max(
    2,
    invulSave > 0 && invulSave < modifiedArmor ? invulSave : modifiedArmor
  );
  const saveSuccess = Math.max(0, (7 - saveTarget) / 6);
  const saveProbability = saveSuccess;
  const saveFailProbability = 1 - saveSuccess;

  const potentialDamage = getDiceAverage(weapon.DMG);
  const overallProbability = hitProbability * woundProbability * saveFailProbability;
  const expectedDamage = overallProbability * potentialDamage;

  return {
    hitProbability,
    woundProbability,
    saveProbability,
    overallProbability,
    expectedDamage,
    potentialDamage,
  };
}

export function getBestRangedWeaponAgainstTarget(
  shooter: Unit,
  target: Unit,
  inCover: boolean = false
): RangedWeaponEffectiveness | null {
  if (!shooter.RNG_WEAPONS || shooter.RNG_WEAPONS.length === 0) {
    return null;
  }

  let best: RangedWeaponEffectiveness | null = null;
  shooter.RNG_WEAPONS.forEach((weapon, index) => {
    const effectiveness = calculateRangedEffectiveness(weapon, index, target, inCover);
    if (!best || effectiveness.expectedDamage > best.expectedDamage) {
      best = { weapon, index, ...effectiveness };
    }
  });

  return best;
}

export function getPreferredRangedWeaponAgainstTarget(
  shooter: Unit,
  target: Unit,
  inCover: boolean = false
): RangedWeaponEffectiveness | null {
  const best = getBestRangedWeaponAgainstTarget(shooter, target, inCover);
  if (!best) {
    return null;
  }

  const selectedIndex = shooter.selectedRngWeaponIndex;
  const manualSelected = shooter.manualWeaponSelected === true;
  if (!manualSelected || selectedIndex === undefined || selectedIndex === null) {
    return best;
  }
  if (selectedIndex < 0 || selectedIndex >= shooter.RNG_WEAPONS.length) {
    throw new Error(`Invalid selectedRngWeaponIndex ${selectedIndex} for unit ${shooter.id}`);
  }

  const selectedWeapon = shooter.RNG_WEAPONS[selectedIndex];
  const effectiveness = calculateRangedEffectiveness(
    selectedWeapon,
    selectedIndex,
    target,
    inCover
  );
  return { weapon: selectedWeapon, index: selectedIndex, ...effectiveness };
}

// ✅ NEW: Combat-specific probability calculation functions
export function calculateCombatHitProbability(attacker: Unit): number {
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get ATK from selected melee weapon
  const selectedWeapon = getSelectedMeleeWeapon(attacker);
  const hitTarget = selectedWeapon?.ATK || 4;
  return Math.max(0, ((7 - hitTarget) / 6) * 100);
}

export function calculateCombatWoundProbability(attacker: Unit, target: Unit): number {
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get STR from selected melee weapon
  const selectedWeapon = getSelectedMeleeWeapon(attacker);
  const strength = selectedWeapon?.STR || 4;
  const toughness = target.T || 4;

  let woundTarget: number;
  if (strength >= toughness * 2) woundTarget = 2;
  else if (strength > toughness) woundTarget = 3;
  else if (strength === toughness) woundTarget = 4;
  else if (strength < toughness) woundTarget = 5;
  else woundTarget = 6;

  return Math.max(0, ((7 - woundTarget) / 6) * 100);
}

export function calculateCombatSaveProbability(attacker: Unit, target: Unit): number {
  const armorSave = target.ARMOR_SAVE || 5;
  const invulSave = target.INVUL_SAVE || 0;
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get AP from selected melee weapon
  const selectedWeapon = getSelectedMeleeWeapon(attacker);
  const armorPenetration = selectedWeapon?.AP || 0;

  const modifiedArmor = armorSave + armorPenetration;
  const saveTarget = invulSave > 0 && invulSave < modifiedArmor ? invulSave : modifiedArmor;

  const saveProbability = Math.max(0, ((7 - saveTarget) / 6) * 100);
  return 100 - saveProbability;
}

export function calculateCombatOverallProbability(attacker: Unit, target: Unit): number {
  const hitProb = calculateCombatHitProbability(attacker);
  const woundProb = calculateCombatWoundProbability(attacker, target);
  const saveFailProb = calculateCombatSaveProbability(attacker, target);

  return (hitProb / 100) * (woundProb / 100) * (saveFailProb / 100) * 100;
}
