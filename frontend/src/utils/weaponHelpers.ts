/**
 * Weapon Helper Functions
 * 
 * MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper functions for accessing weapon data
 */

import type { DiceValue, Unit, Weapon } from '../types/game';

/**
 * Get currently selected ranged weapon.
 * 
 * @param unit Unit to get weapon from
 * @returns Selected ranged weapon or null if no ranged weapons
 */
export function getSelectedRangedWeapon(unit: Unit): Weapon | null {
  if (!unit.RNG_WEAPONS || unit.RNG_WEAPONS.length === 0) {
    return null;
  }
  
  const idx = unit.selectedRngWeaponIndex ?? 0;
  if (idx < 0 || idx >= unit.RNG_WEAPONS.length) {
    throw new Error(`Invalid selectedRngWeaponIndex ${idx} for unit ${unit.id}`);
  }
  
  return unit.RNG_WEAPONS[idx];
}

/**
 * Get currently selected melee weapon.
 * 
 * @param unit Unit to get weapon from
 * @returns Selected melee weapon or null if no melee weapons
 */
export function getSelectedMeleeWeapon(unit: Unit): Weapon | null {
  if (!unit.CC_WEAPONS || unit.CC_WEAPONS.length === 0) {
    return null;
  }
  
  const idx = unit.selectedCcWeaponIndex ?? 0;
  if (idx < 0 || idx >= unit.CC_WEAPONS.length) {
    throw new Error(`Invalid selectedCcWeaponIndex ${idx} for unit ${unit.id}`);
  }
  
  return unit.CC_WEAPONS[idx];
}

/**
 * Melee range is always 1.
 * 
 * @returns Always 1
 */
export function getMeleeRange(): number {
  return 1;
}

/**
 * Get average value for dice-based stats.
 *
 * @param value Dice value or number
 * @returns Average numeric value
 */
export function getDiceAverage(value: DiceValue): number {
  if (typeof value === 'number') {
    return value;
  }
  if (value === 'D3') {
    return 2;
  }
  if (value === 'D6') {
    return 3.5;
  }
  throw new Error(`Unsupported dice value: ${value}`);
}

/**
 * Get maximum range of all ranged weapons.
 * 
 * @param unit Unit to get max range from
 * @returns Maximum range of all ranged weapons, or 0 if no ranged weapons
 */
export function getMaxRangedRange(unit: Unit): number {
  if (!unit.RNG_WEAPONS || unit.RNG_WEAPONS.length === 0) {
    return 0;
  }
  
  return Math.max(...unit.RNG_WEAPONS.map(w => w.RNG || 0));
}
