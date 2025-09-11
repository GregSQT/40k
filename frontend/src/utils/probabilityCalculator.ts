// frontend/src/utils/probabilityCalculator.ts

import type { Unit } from '../types/game';

export function calculateHitProbability(shooter: Unit): number {
  const hitTarget = shooter.RNG_ATK || 4;
  return Math.max(0, (7 - hitTarget) / 6 * 100);
}

export function calculateWoundProbability(shooter: Unit, target: Unit): number {
  const strength = shooter.RNG_STR || 4;
  const toughness = target.T || 4;
  
  let woundTarget: number;
  if (strength >= toughness * 2) woundTarget = 2;
  else if (strength > toughness) woundTarget = 3;
  else if (strength === toughness) woundTarget = 4;
  else if (strength < toughness) woundTarget = 5;
  else woundTarget = 6;
  
  return Math.max(0, (7 - woundTarget) / 6 * 100);
}

export function calculateSaveProbability(shooter: Unit, target: Unit, inCover: boolean = false): number {
  let armorSave = target.ARMOR_SAVE || 5;
  const invulSave = target.INVUL_SAVE || 0;
  const armorPenetration = shooter.RNG_AP || 0;
  
  // Apply cover bonus - +1 to armor save (better save)
  if (inCover) {
    armorSave = Math.max(2, armorSave - 1); // Improve armor save by 1, minimum 2+
    // Note: Invulnerable saves are not affected by cover
  }
  
  const modifiedArmor = armorSave + armorPenetration;
  const saveTarget = (invulSave > 0 && invulSave < modifiedArmor) ? invulSave : modifiedArmor;
  
  const saveProbability = Math.max(0, (7 - saveTarget) / 6 * 100);
  return 100 - saveProbability;
}

export function calculateOverallProbability(shooter: Unit, target: Unit, inCover: boolean = false): number {
  const hitProb = calculateHitProbability(shooter);
  const woundProb = calculateWoundProbability(shooter, target);
  const saveFailProb = calculateSaveProbability(shooter, target, inCover);
  
  return (hitProb / 100) * (woundProb / 100) * (saveFailProb / 100) * 100;
}

// ✅ NEW: Combat-specific probability calculation functions
export function calculateCombatHitProbability(attacker: Unit): number {
  const hitTarget = attacker.CC_ATK || 4;
  return Math.max(0, (7 - hitTarget) / 6 * 100);
}

export function calculateCombatWoundProbability(attacker: Unit, target: Unit): number {
  const strength = attacker.CC_STR || 4;
  const toughness = target.T || 4;
  
  let woundTarget: number;
  if (strength >= toughness * 2) woundTarget = 2;
  else if (strength > toughness) woundTarget = 3;
  else if (strength === toughness) woundTarget = 4;
  else if (strength < toughness) woundTarget = 5;
  else woundTarget = 6;
  
  return Math.max(0, (7 - woundTarget) / 6 * 100);
}

export function calculateCombatSaveProbability(attacker: Unit, target: Unit): number {
  const armorSave = target.ARMOR_SAVE || 5;
  const invulSave = target.INVUL_SAVE || 0;
  const armorPenetration = attacker.CC_AP || 0;
  
  const modifiedArmor = armorSave + armorPenetration;
  const saveTarget = (invulSave > 0 && invulSave < modifiedArmor) ? invulSave : modifiedArmor;
  
  const saveProbability = Math.max(0, (7 - saveTarget) / 6 * 100);
  return 100 - saveProbability;
}

export function calculateCombatOverallProbability(attacker: Unit, target: Unit): number {
  const hitProb = calculateCombatHitProbability(attacker);
  const woundProb = calculateCombatWoundProbability(attacker, target);
  const saveFailProb = calculateCombatSaveProbability(attacker, target);
  
  return (hitProb / 100) * (woundProb / 100) * (saveFailProb / 100) * 100;
}