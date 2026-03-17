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
//const D6: DiceValue = "D6";
const D6_PLUS_1: DiceValue = "D6+1";
// ============================================================================
// TYRANID WEAPONS
// ============================================================================

export const TYRANID_ARMORY: Record<string, Weapon> = {
  // Ranged Weapons
  deathspitter: {display_name: "Deathspitter", RNG: 24, NB: 3, ATK: 4, STR: 5, AP: -1, DMG: 1, WEAPON_RULES: [],},
  flamespurt: {display_name: "Flamespurt", RNG: 12, NB: D6_PLUS_1, ATK: 7, STR: 6, AP: -1, DMG: 1, WEAPON_RULES: ["IGNORES_COVER", "TORRENT", "TWIN_LINKED"],},
  fleshborer: {display_name: "Fleshborer", RNG: 18, NB: 1, ATK: 4, STR: 5, AP: 0, DMG: 1, WEAPON_RULES: ["ASSAULT"],},
  heavy_venom_cannon: {display_name: "Heavy Venom Cannon", RNG: 36, NB: D3, ATK: 4, STR: 9, AP: -2, DMG: 3, WEAPON_RULES: [],},
  impaler_cannon: {display_name: "Impaler Cannon", RNG: 36, NB: 4, ATK: 4, STR: 5, AP: -1, DMG: 1, WEAPON_RULES: ["HEAVY", "INDIRECT_FIRE"],},
  shockcannon: {display_name: "ShockCannon", RNG: 24, NB: 2, ATK: 3, STR: 7, AP: -1, DMG: 3, WEAPON_RULES: ["ANTI_VEHICLE:2"],},
  spinemaws: {display_name: "Spinemaws", RNG: 6, NB: 4, ATK: 5, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: ["PISTOL"],},
  spore_mine_launcher: {display_name: "Spore Mine Launcher", RNG: 48, NB: D3, ATK: 4, STR: 6, AP: -1, DMG: 2, WEAPON_RULES: ["BLAST", "DEVASTATING_WOUNDS", "HEAVY", "INDIRECT_FIRE"],},
  warp_blast_witchfire: {display_name: "Warp Blast (Witchfire)", RNG: 24, NB: D3, ATK: 3, STR: 7, AP: -2, DMG: D3, WEAPON_RULES: ["BLAST", "PSYCHIC"],},
  warp_blast_focused_bolt: {display_name: "Warp Blast (Focused Bolt)", RNG: 24, NB: 1, ATK: 3, STR: 12, AP: -3, DMG: D6_PLUS_1, WEAPON_RULES: ["LETHAL_HITS", "PSYCHIC"],},
  
  // #########################################################################################
  // #################################### Melee Weapons ######################################
  // #########################################################################################

  bio_weapon_warrior: {display_name: "Bio-Weapon", NB: 6, ATK: 3, STR: 5, AP: -2, DMG: 1, WEAPON_RULES: ["TWIN_LINKED"],},
  blinding_venom: {display_name: "Blinding Venom", NB: 1, ATK: 4, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  bone_cleaver: {display_name: "Bone Cleaver", NB: 3, ATK: 3, STR: 5, AP: 1, DMG: 2, WEAPON_RULES: [],},
  chitin_barbed_limb: {display_name: "Chitin-Barbed Limb", NB: 2, ATK: 4, STR: 5, AP: 0, DMG: 1, WEAPON_RULES: [],},
  chitinous_claws_and_teeth_ripper_swarm: {display_name: "Chitinous Claws and Teeth", NB: 6, ATK: 5, STR: 1, AP: 0, DMG: 1, WEAPON_RULES: ["SUSTAINED_HITS:1"],},
  chitinous_claws_and_teeth_zoanthrope: {display_name: "Chitinous Claws and Teeth", NB: 2, ATK: 5, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  chitinous_claws_and_teeth_hive_guard: {display_name: "Chitinous Claws and Teeth", NB: 3, ATK: 4, STR: 5, AP: 0, DMG: 1, WEAPON_RULES: [],},
  crushing_claws: {display_name: "Crushing Claws", NB: 2, ATK: 4, STR: 8, AP: -2, DMG: 2, WEAPON_RULES: ["TWIN_LINKED"],},
  flesh_hooks: {display_name: "Flesh Hooks", NB: 1, ATK: 4, STR: 3, AP: 0, DMG: 1, WEAPON_RULES: [],},
  monstrous_scything_talons: {display_name: "Monstrous Scything Talons", NB: 6, ATK: 4, STR: 9, AP: -2, DMG: 3, WEAPON_RULES: [],},
  rending_claws: {display_name: "Rending Claws", NB: 4, ATK: 2, STR: 4, AP: -2, DMG: 1, WEAPON_RULES: [],},
  rending_claws_prime: {display_name: "Rending Claws", NB: 5, ATK: 2, STR: 6, AP: -2, DMG: 2, WEAPON_RULES: ["DEVASTATING_WOUNDS", "TWIN_LINKED"],},
  bio_weapons: {display_name: "Bio-Weapons", NB: 5, ATK: 3, STR: 5, AP: -1, DMG: 1, WEAPON_RULES: [],},
  scything_talons: {display_name: "Scything Talons", NB: 3, ATK: 4, STR: 3, AP: -1, DMG: 1, WEAPON_RULES: [],},
  scything_talons_tyrant_guard: {display_name: "Scything Talons", NB: 5, ATK: 3, STR: 5, AP: -1, DMG: 1, WEAPON_RULES: [],},
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
