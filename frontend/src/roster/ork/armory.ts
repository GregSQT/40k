// frontend/src/roster/ork/armory.ts
//
/**
 * Ork Armory - Centralized weapon definitions.
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
//const D6: DiceValue = "D6";
//const D6_PLUS_1: DiceValue = "D6+1";
const D6_PLUS_3: DiceValue = "D6+3";
//const TWO_D6: DiceValue = "2D6";
export const ORK_ARMORY: Record<string, Weapon> = {
  // #########################################################################################
  // #################################### Range Weapons ######################################
  // ########################################################################################
  blasta: { display_name: "Blasta'", RNG: 12, NB: 1, ATK: 4, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: ["PISTOL"] },
  blitzcannon: { display_name: "Blitzcannon", RNG: 24, NB: 8, ATK: 5, STR: 7, AP: -2, DMG: 2, WEAPON_RULES: ["HEAVY", "SUSTAINED_HITS:1"] },
  eadbanger: { display_name: "'eadbanger'", RNG: 24, NB: 1, ATK: 4, STR: 6, AP: -3, DMG: 1, WEAPON_RULES: ["PRECISION", "PSYCHIC"] },
  kombi_rokkit: { display_name: "Kombi Rokkit", NB: 1, ATK: 5, STR: 10, AP: -2, DMG: 3, WEAPON_RULES: [] },
  kombi_shoota: { display_name: "Kombi Shoota", NB: 2, ATK: 5, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: [] },
  kustom_shoota_a2: { display_name: "Kustom Shoota", RNG: 18, NB: 4, ATK: 5, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["RAPID_FIRE:2"] },
  kustom_shoota_a4: { display_name: "Kustom Shoota", RNG: 18, NB: 4, ATK: 5, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["RAPID_FIRE:2"] },
  rokkit_launcha: { display_name: "Rokkit Launcha", NB: D6_PLUS_3, ATK: 5, STR: 10, AP: -2, DMG: 3, WEAPON_RULES: [] },
  rokkit_launcha_heavy: { display_name: "Rokkit Launcha", NB: 6, ATK: 5, STR: 10, AP: -2, DMG: 3, WEAPON_RULES: ["HEAVY"] },
  shoota: { display_name: "Shoota", RNG: 18, NB: 2, ATK: 5, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["RAPID_FIRE:1"] },
  slugga: { display_name: "Slugga", RNG: 12, NB: 1, ATK: 5, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["PISTOL"] },

  
  // #########################################################################################
  // #################################### Melee Weapons ######################################
  // #########################################################################################
  big_choppa: { display_name: "Big Choppa", NB: 3, ATK: 3, STR: 7, AP: -1, DMG: 2, WEAPON_RULES: [] },
  close_combat_weapon_a1: { display_name: "Close Combat Weapon", NB: 1, ATK: 5, STR: 2, AP: 0, DMG: 1, WEAPON_RULES: [] },
  choppa_a3: { display_name: "Choppa", NB: 3, ATK: 3, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: [] },
  choppa_a5: { display_name: "Choppa", NB: 5, ATK: 3, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: [] },
  dok_tools: { display_name: "Dok's Tools", NB: 3, ATK: 4, STR: 9, AP: -2, DMG: 2, WEAPON_RULES: [] },
  kustom_choppa: { display_name: "Kustom Choppa", NB: 6, ATK: 2, STR: 8, AP: -2, DMG: 2, WEAPON_RULES: ["CLEAVE:1"] },
  stompy_feet: { display_name: "Stompy Feet", NB: 4, ATK: 3, STR: 6, AP: -1, DMG: 1, WEAPON_RULES: [] },
  two_handed_big_choppa: { display_name: "Two-Handed Big Choppa", NB: 5, ATK: 3, STR: 7, AP: -1, DMG: 2, WEAPON_RULES: ["CLEAVE:1"] },
  urty_syringe: { display_name: "'urty Syringe", NB: 1, ATK: 3, STR: 2, AP: 0, DMG: 1, WEAPON_RULES: ["ANTI-INFANTRY", "EXTRA_ATTACK", "PRECISION"] },
  waaagh_staff: { display_name: "'Waaagh! Staff", NB: 3, ATK: 3, STR: 8, AP: -1, DMG: D3, WEAPON_RULES: ["PSYCHIC"] },

  
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
  return ORK_ARMORY[codeName];
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
      const availableWeapons = Object.keys(ORK_ARMORY).join(", ");
      throw new Error(`Weapon '${codeName}' not found in Ork armory. ` + `Available weapons: ${availableWeapons}`);
    }
    weapons.push({ ...weapon, code: codeName }); // injecte l'identite stable (cf. Weapon.code)
  }
  return weapons;
}
