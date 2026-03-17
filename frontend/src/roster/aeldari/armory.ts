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

const D6: DiceValue = "D6";
const D6_PLUS_1: DiceValue = "D6+1";
//const D3: DiceValue = "D3";
// ============================================================================
// TYRANID WEAPONS
// ============================================================================

export const AELDARI_ARMORY: Record<string, Weapon> = {
  // Ranged Weapons
  d_scythe: {display_name: "D-Scythe", RNG: 12, NB: D6, ATK: 7, STR: 7, AP: -3, DMG: 1, WEAPON_RULES: ["TORRENT"],},
  death_spinner: {display_name: "Death Spinner", RNG: 12, NB: D6, ATK: 7, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: ["IGNORES_COVER", "TORRENT"],},
  death_spinner_exarch: {display_name: "Exarch Death Spinner", RNG: 12, NB: D6, ATK: 7, STR: 6, AP: -2, DMG: 1, WEAPON_RULES: ["IGNORES_COVER", "TORRENT"],},
  dragon_fusion_gun: {display_name: "Dragon Fusion Gun", RNG: 12, NB: 1, ATK: 3, STR: 9, AP: -4, DMG: D6, WEAPON_RULES: ["ASSAULT", "MELTA:3"],},
  exarch_dragon_fusion_gun: {display_name: "Exarch Dragon Fusion Gun", RNG: 12, NB: 1, ATK: 3, STR: 9, AP: -4, DMG: D6, WEAPON_RULES: ["ASSAULT", "MELTA:6"],},
  firepike: {display_name: "Dragon Fusion Gun", RNG: 18, NB: 1, ATK: 3, STR: 12, AP: -4, DMG: D6, WEAPON_RULES: ["ASSAULT", "MELTA:3"],},
  hawk_talons: {display_name: "Hawk's Talons", RNG: 24, NB: 2, ATK: 3, STR: 6, AP: -2, DMG: 2, WEAPON_RULES: ["LETHAL_HITS"],},
  lasblaster: {display_name: "Lasblaster", RNG: 24, NB: 4, ATK: 3, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["ASSAULT", "LETHAL_HITS"],},
  missile_launcher_starshot: {display_name: "Missile Launcher (Starhot)", COMBI_WEAPON: "missile_launcher", RNG: 48, NB: 1, ATK: 2, STR: 10, AP: -2, DMG: D6, WEAPON_RULES: ["IGNORES_COVER"],},
  missile_launcher_starswarm: {display_name: "Missile Launcher (Starswarm)", COMBI_WEAPON: "missile_launcher", RNG: 48, NB: D6, ATK: 2, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: ["IGNORES_COVER"],},
  reaper_launcher_starshot: {display_name: "Reaper Launcher (Starhot)", COMBI_WEAPON: "reaper_launcher", RNG: 48, NB: 1, ATK: 3, STR: 10, AP: -2, DMG: 3, WEAPON_RULES: ["IGNORES_COVER"],},
  reaper_launcher_starswarm: {display_name: "Reaper Launcher (Starswarm)", COMBI_WEAPON: "reaper_launcher", RNG: 48, NB: 2, ATK: 3, STR: 5, AP: -1, DMG: 2, WEAPON_RULES: ["IGNORES_COVER"],},
  shuriken_cannon: {display_name: "Shuriken Cannon", RNG: 24, NB: 3, ATK: 3, STR: 6, AP: -1, DMG: 2, WEAPON_RULES: ["SUSTAINED_HITS:1"],},
  shuriken_catapult: {display_name: "Shuriken Catapult", RNG: 18, NB: 2, ATK: 3, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: ["ASSAULT"],},
  shuriken_catapult_avenger: {display_name: "Avenger Shuriken Catapult", RNG: 18, NB: 4, ATK: 3, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: ["ASSAULT"],},
  shuriken_pistol: {display_name: "Shuriken Pistol", RNG: 12, NB: 1, ATK: 3, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: ["ASSAULT", "PISTOL"],},
  wraithcannon: {display_name: "Wraith Cannon", RNG: 18, NB: 1, ATK: 4, STR: 14, AP: -4, DMG: D6_PLUS_1, WEAPON_RULES: [],},

  
  // #########################################################################################
  // #################################### Melee Weapons ######################################
  // #########################################################################################
  aeldari_power_weapon: {display_name: "Aeldari Power Weapon", NB: 2, ATK: 3, STR: 4, AP: -2, DMG: 1, WEAPON_RULES: [],},
  banshees_blade: {display_name: "Banshee Blade", NB: 2, ATK: 2, STR: 4, AP: -2, DMG: 2, WEAPON_RULES: [],},
  biting_blade: {display_name: "Biting Blade", NB: 5, ATK: 3, STR: 5, AP: -1, DMG: 2, WEAPON_RULES: ["SUSTAINED_HITS:1"],},
  close_combat_weapon: {display_name: "Close Combat Weapon", NB: 1, ATK: 3, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  close_combat_weapon_aspect_warrior: {display_name: "Close Combat Weapon", NB: 2, ATK: 3, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  close_combat_weapon_wraithguard: {display_name: "Close Combat Weapon", NB: 3, ATK: 4, STR: 5, AP: 0, DMG: 1, WEAPON_RULES: [],},
  mirror_swords: {display_name: "Mirror Swords", NB: 4, ATK: 2, STR: 4, AP: -2, DMG: 2, WEAPON_RULES: [],},
  powerblades_array: {display_name: "Powerblades Array", NB: 10, ATK: 3, STR: 4, AP: -1, DMG: 1, WEAPON_RULES: ["LETHAL_HITS", "TWIN_LINKED"],},
  power_glaive: {display_name: "Power Glaive", NB: 3, ATK: 3, STR: 5, AP: -3, DMG: 1, WEAPON_RULES: [],},
  scorpion_chainsword: {display_name: "Scorpion Chainsword",   NB: 4,  ATK: 3, STR: 4, AP: 0, DMG: 1, WEAPON_RULES: ["SUSTAINED_HITS:1"],},
  scorpion_claws: {display_name: "Scorpion's Claw", NB: 3, ATK: 3, STR: 8, AP: -2, DMG: 2, WEAPON_RULES: [],},
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
  return AELDARI_ARMORY[codeName];
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
      const availableWeapons = Object.keys(AELDARI_ARMORY).join(", ");
      throw new Error(
        `Weapon '${codeName}' not found in Tyranid armory. ` +
          `Available weapons: ${availableWeapons}`
      );
    }
    weapons.push(weapon);
  }
  return weapons;
}
