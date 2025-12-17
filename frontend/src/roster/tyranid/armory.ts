/**
 * Tyranid Armory - Centralized weapon definitions.
 * 
 * SINGLE SOURCE OF TRUTH: This is the ONLY place where weapons are declared.
 * Python parses this file dynamically using engine/armory_parser.py
 * 
 * AI_IMPLEMENTATION.md COMPLIANCE:
 * - NO DEFAULT: getWeapon() raises error if weapon missing (pas de fallback)
 * - Validation stricte: toutes les armes référencées doivent exister
 * - No duplicate Python armory needed - parsed at runtime
 */

import type { Weapon } from '../../types/game';

// ============================================================================
// TYRANID WEAPONS
// ============================================================================

export const TYRANID_ARMORY: Record<string, Weapon> = {
  // Ranged Weapons
  fleshborer: {
    code_name: "fleshborer",
    display_name: "Fleshborer",
    RNG: 18,
    NB: 1,
    ATK: 4,
    STR: 5,
    AP: 0,
    DMG: 1,
  },
  venom_cannon: {
    code_name: "venom_cannon",
    display_name: "Venom Cannon",
    RNG: 24,
    NB: 6,
    ATK: 4,
    STR: 7,
    AP: -2,
    DMG: 1,
  },
  
  // Melee Weapons
  rending_claws: {
    code_name: "rending_claws",
    display_name: "Rending Claws",
    NB: 4,
    ATK: 2,
    STR: 4,
    AP: -2,
    DMG: 1,
  },
  rending_claws_prime: {
    code_name: "rending_claws_prime",
    display_name: "Rending Claws",
    NB: 5,
    ATK: 2,
    STR: 6,
    AP: -2,
    DMG: 2,
  },
  scything_talons: {
    code_name: "scything_talons",
    display_name: "Scything Talons",
    NB: 3,
    ATK: 4,
    STR: 3,
    AP: -1,
    DMG: 1,
  },
  flesh_hooks: {
    code_name: "flesh_hooks",
    display_name: "Flesh Hooks",
    NB: 1,
    ATK: 4,
    STR: 3,
    AP: 0,
    DMG: 1,
  },
  monstrous_scything_talons: {
    code_name: "monstrous_scything_talons",
    display_name: "Monstrous Scything Talons",
    NB: 6,
    ATK: 4,
    STR: 9,
    AP: -2,
    DMG: 3,
  },
};

/**
 * Get a weapon by code name.
 * 
 * AI_IMPLEMENTATION.md COMPLIANCE: NO DEFAULT - returns undefined if missing.
 * Caller must check and raise error if weapon is required.
 * 
 * @param codeName Weapon code name (e.g., "fleshborer")
 * @returns Weapon or undefined if not found
 */
export function getWeapon(codeName: string): Weapon | undefined {
  return TYRANID_ARMORY[codeName];
}

/**
 * Get multiple weapons by code names.
 * 
 * AI_IMPLEMENTATION.md COMPLIANCE: NO DEFAULT - raises Error if any weapon missing.
 * 
 * @param codeNames List of weapon code names
 * @returns List of weapons
 * @throws Error If any weapon codeName is missing from armory
 */
export function getWeapons(codeNames: string[]): Weapon[] {
  const weapons: Weapon[] = [];
  for (const codeName of codeNames) {
    const weapon = getWeapon(codeName);
    if (!weapon) {
      const availableWeapons = Object.keys(TYRANID_ARMORY).join(", ");
      throw new Error(
        `Weapon '${codeName}' not found in Tyranid armory. ` +
        `Available weapons: ${availableWeapons}`
      );
    }
    weapons.push(weapon);
  }
  return weapons;
}
