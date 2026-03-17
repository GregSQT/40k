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
import type { DiceValue, Weapon } from "../../types/game";

//const D3: DiceValue = "D3";
const D6: DiceValue = "D6";
// ============================================================================
// TYRANID WEAPONS
// ============================================================================

export const ADEPTUS_CUSTODES_ARMORY: Record<string, Weapon> = {
  // Ranged Weapons
  balistus_grenade_launcher: {display_name: "Balistus Grenade Launcher", RNG: 18, NB: D6, ATK: 2, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: ["BLAST"],},
  bolter: {display_name: "Bolter", RNG: 24, NB: 1, ATK: 3, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["RAPID_FIRE:1"],},
  castellan_axe_ranged: {display_name: "Castellan Axe", RNG: 24, NB: 2, ATK: 2, STR: 4, AP: -1, DMG: 2, WEAPON_RULES: ["ASSAULT"],},
  guardian_spear_ranged: {display_name: "Guardian Spear", RNG: 24, NB: 2, ATK: 2, STR: 4, AP: -1, DMG: 2, WEAPON_RULES: ["ASSAULT"],},
  sentinel_blade_ranged: {display_name: "Sentinel Blade", RNG: 12, NB: 2, ATK: 2, STR: 4, AP: -1, DMG: 2, WEAPON_RULES: ["ASSAULT", "PISTOL"],},
  whitchseeker_flamer: {display_name: "Whitchseeker Flamer", RNG: 12, NB: D6, ATK: 7, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["IGNORES_COVER", "TORRENT"],},
  

  // #########################################################################################
  // #################################### Melee Weapons ######################################
  // #########################################################################################

  castellan_axe_melee: {display_name: "Castellan Axe", NB: 4, ATK: 2, STR: 9, AP: -1, DMG: 3, WEAPON_RULES: [],},
  guardian_spear_melee: {display_name: "Guardian Spear", NB: 5, ATK: 2, STR: 7, AP: -2, DMG: 2, WEAPON_RULES: [],},
  close_combat_weapon: {display_name: "Close Combat Weapon", NB: 2, ATK: 3, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  sentinel_blade_melee: {display_name: "Sentinel Blade", NB: 5, ATK: 2, STR: 6, AP: -2, DMG: 1, WEAPON_RULES: [],},
  
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
  return ADEPTUS_CUSTODES_ARMORY[codeName];
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
      const availableWeapons = Object.keys(ADEPTUS_CUSTODES_ARMORY).join(", ");
      throw new Error(
        `Weapon '${codeName}' not found in Tyranid armory. ` +
          `Available weapons: ${availableWeapons}`
      );
    }
    weapons.push(weapon);
  }
  return weapons;
}
