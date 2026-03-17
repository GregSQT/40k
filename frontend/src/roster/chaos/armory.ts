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

const D3: DiceValue = "D3";
const D6: DiceValue = "D6";
const D6_PLUS_3: DiceValue = "D6+3";
// ============================================================================
// TYRANID WEAPONS
// ============================================================================

export const CHAOS_ARMORY: Record<string, Weapon> = {
  // Ranged Weapons
  autopistol: {display_name: "Autopistol", RNG: 12, NB: 1, ATK: 4, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: ["PISTOL"],},
  balefire_pike: {display_name: "Balefire Pike", RNG: 12, NB: D6_PLUS_3, ATK: 7, STR: 5, AP: -1, DMG: 1, WEAPON_RULES: ["IGNORES_COVER", "TORRENT"],},
  bolt_pistol: {display_name: "Bolt Pistol", RNG: 12, NB: 1, ATK: 4, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["PISTOL"],},
  boltgun: {display_name: "Boltgun", RNG: 24, NB: 2, ATK: 3, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: [],},
  fleshmetal_guns_focused_malice: {display_name: "Fleshmetal Guns (Focused Malice)", RNG: 24, NB: D3, ATK: 3, STR: 12, AP: -3, DMG: 4, WEAPON_RULES: ["MELTA:2"],},
  fleshmetal_guns_ruinous_salvo: {display_name: "Fleshmetal Guns (Ruinous Salvo)", RNG: 24, NB: D6, ATK: 3, STR: 8, AP: -2, DMG: 2, WEAPON_RULES: ["BLAST"],},
  fleshmetal_guns_warp_hail: {display_name: "Fleshmetal Guns (Warp Hail)", RNG: 24, NB: D6_PLUS_3, ATK: 3, STR: 5, AP: -1, DMG: 1, WEAPON_RULES: ["SUSTAINED_HITS:1"],},
  lasgun: {display_name: "Lasgun", RNG: 24, NB: 1, ATK: 4, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: ["RAPID_FIRE:1"],},
  meltagun: {display_name: "Meltagun", RNG: 12, NB: 1, ATK: 3, STR: 9, AP: -4, DMG: D6, WEAPON_RULES: ["MELTA:2"],},
  plasma_gun_standard: {display_name: "Plasma Gun (Standard)", COMBI_WEAPON: "plasma_gun", RNG: 24, NB: 1, ATK: 3, STR: 7, AP: -2, DMG: 1, WEAPON_RULES: ["RAPID_FIRE:1"],},
  plasma_gun_supercharge: {display_name: "Plasma Gun (Supercharge)", COMBI_WEAPON: "plasma_gun", RNG: 24, NB: 1, ATK: 3, STR: 8, AP: -3, DMG: 2, WEAPON_RULES: ["RAPID_FIRE:1", "HAZARDOUS"],},
  plasma_pistol_standard: {display_name: "Plasma Pistol (Standard)", COMBI_WEAPON: "plasma_pistol", RNG: 12, NB: 1, ATK: 3, STR: 7, AP: -2, DMG: 1, WEAPON_RULES: ["PISTOL"],},
  plasma_pistol_supercharge: {display_name: "Plasma Pistol (Supercharge)", COMBI_WEAPON: "plasma_pistol", RNG: 12, NB: 1, ATK: 3, STR: 8, AP: -3, DMG: 2, WEAPON_RULES: ["PISTOL", "HAZARDOUS"],},

  // #########################################################################################
  // #################################### Melee Weapons ######################################
  // #########################################################################################

  accursed_weapon: {display_name: "Accursed Weapon", NB: 4, ATK: 3, STR: 8, AP: -2, DMG: 1, WEAPON_RULES: [],},
  brutal_assault_weapon: {display_name: "Brutal Assault Weapon", NB: 2, ATK: 4, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  close_combat_weapon_firebrand: {display_name: "Close Combat Weapon", NB: 4, ATK: 4, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: [],},
  close_combat_weapon: {display_name: "Close Combat Weapon", NB: 1, ATK: 4, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  close_combat_weapon_a3: {display_name: "Close Combat Weapon", NB: 3, ATK: 3, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: [],},
  crushing_fists: {display_name: "Crushing Fists", NB: 4, ATK: 3, STR: 9, AP: -2, DMG: 2, WEAPON_RULES: [],},
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
  return CHAOS_ARMORY[codeName];
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
      const availableWeapons = Object.keys(CHAOS_ARMORY).join(", ");
      throw new Error(
        `Weapon '${codeName}' not found in Chaos armory. ` +
          `Available weapons: ${availableWeapons}`
      );
    }
    weapons.push(weapon);
  }
  return weapons;
}
