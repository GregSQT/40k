// frontend/src/roster/spaceMarine/armory.ts
//
/**
 * Space Marine Armory - Centralized weapon definitions.
 *
 * SINGLE SOURCE OF TRUTH: This is the ONLY place where weapons are declared.
 * Python parses this file dynamically using engine/armory_parser.py
 *
 * AI_IMPLEMENTATION.md COMPLIANCE:
 * - NO DEFAULT: getWeapon() raises error if weapon missing (pas de fallback)
 * - Validation stricte: toutes les armes référencées doivent exister
 * - No duplicate Python armory needed - parsed at runtime
 */

import type { DiceValue, Weapon } from "../../types/game";

const D3: DiceValue = "D3";
const D6: DiceValue = "D6";
export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {
  // #########################################################################################
  // #################################### Range Weapons ######################################
  // #########################################################################################
  bolt_rifle: {
    display_name: "Bolt Rifle",
    RNG: 24,
    NB: 4,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["ASSAULT", "HEAVY"],
  },
  bolt_pistol: {
    display_name: "Bolt Pistol",
    RNG: 12,
    NB: 1,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["PISTOL"],
  },
  storm_bolter: {
    display_name: "Storm Bolter",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
  astartes_grenade_launcher_frag: {
    display_name: "Astartes Grenade Launcher (Frag)",
    COMBI_WEAPON: "astartes_grenade_launcher",
    RNG: 24,
    NB: D3,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
  astartes_grenade_launcher_krak: {
    display_name: "Astartes Grenade Launcher (Krak)",
    COMBI_WEAPON: "astartes_grenade_launcher",
    RNG: 24,
    NB: 1,
    ATK: 3,
    STR: 9,
    AP: -2,
    DMG: D3,
    WEAPON_RULES: [],
  },
  plasma_pistol_standard: {
    display_name: "Plasma Pistol (Standard)",
    COMBI_WEAPON: "plasma_pistol",
    RNG: 12,
    NB: 1,
    ATK: 3,
    STR: 7,
    AP: -2,
    DMG: 1,
    WEAPON_RULES: ["PISTOL"],
  },
  plasma_pistol_supercharge: {
    display_name: "Plasma Pistol (Supercharge)",
    COMBI_WEAPON: "plasma_pistol",
    RNG: 12,
    NB: 1,
    ATK: 3,
    STR: 8,
    AP: -3,
    DMG: 2,
    WEAPON_RULES: ["PISTOL"],
  },
  master_crafted_boltgun: {
    display_name: "Master-crafted Boltgun",
    RNG: 12,
    NB: 3,
    ATK: 2,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: [],
  },
  // #########################################################################################
  // #################################### Melee Weapons ######################################
  // #########################################################################################
  close_combat_weapon: {
    display_name: "Close Combat Weapon",
    NB: 3,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
  intercessor_sergeant_power_fist: {
    display_name: "Power Fist",
    NB: 3,
    ATK: 3,
    STR: 8,
    AP: -2,
    DMG: 2,
    WEAPON_RULES: [],
  },
  intercessor_sergeant_power_weapon: {
    display_name: "Power Weapon",
    NB: 4,
    ATK: 3,
    STR: 5,
    AP: -2,
    DMG: 1,
    WEAPON_RULES: [],
  },
  intercessor_sergeant_chainsword: {
    display_name: "Astartes Chainsword",
    NB: 5,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: [],
  },
  assault_intercessor_chainsword: {
    display_name: "Astartes Chainsword",
    NB: 4,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: [],
  },
  power_fist: {
    display_name: "Power Fist",
    NB: 5,
    ATK: 2,
    STR: 8,
    AP: -2,
    DMG: 2,
    WEAPON_RULES: [],
  },
  power_fist_terminator: {
    display_name: "Power Fist",
    NB: 3,
    ATK: 3,
    STR: 8,
    AP: -2,
    DMG: 2,
    WEAPON_RULES: [],
  },
  // #########################################################################################
  // #################################### Debug Weapons ######################################
  // #########################################################################################
  SM_RNG_killer: {
    display_name: "SM_RNG_killer",
    RNG: 24,
    NB: 1,
    ATK: 3,
    STR: 5,
    AP: -3,
    DMG: 2,
    WEAPON_RULES: [],
  },
  Termagant_RNG_killer: {
    display_name: "Termagant_RNG_killer",
    RNG: 24,
    NB: 5,
    ATK: 3,
    STR: 3,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
  SM_CC_killer: {
    display_name: "SM_CC_killer",
    NB: 1,
    ATK: 3,
    STR: 5,
    AP: -3,
    DMG: D6,
    WEAPON_RULES: [],
  },
  Termagant_CC_killer: {
    display_name: "Termagant_CC_killer",
    NB: 5,
    ATK: 3,
    STR: 3,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
};

/**
 * Get a weapon by code name.
 *
 * AI_IMPLEMENTATION.md COMPLIANCE: NO DEFAULT - returns undefined if missing.
 * Caller must check and raise error if weapon is required.
 *
 * @param codeName Weapon code name (e.g., "bolt_rifle")
 * @returns Weapon or undefined if not found
 */
export function getWeapon(codeName: string): Weapon | undefined {
  return SPACE_MARINE_ARMORY[codeName];
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
      const availableWeapons = Object.keys(SPACE_MARINE_ARMORY).join(", ");
      throw new Error(
        `Weapon '${codeName}' not found in Space Marine armory. ` +
          `Available weapons: ${availableWeapons}`
      );
    }
    weapons.push(weapon);
  }
  return weapons;
}
