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
const D6_PLUS_1: DiceValue = "D6+1";
const TWO_D6: DiceValue = "2D6";
export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {
  // #########################################################################################
  // #################################### Range Weapons ######################################
  // ########################################################################################
  assault_cannon: {
    display_name: "Assault Cannon",
    RNG: 24,
    NB: 6,
    ATK: 3,
    STR: 6,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["DEVASTATING_WOUNDS"],
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
  auto_boltstorm_gauntlets: {
    display_name: "Auto Boltstorm Gauntlets",
    RNG: 18,
    NB: 3,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["TWIN_LINKED"],
  },
  boltgun: {
    display_name: "Boltgun",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
  bolt_rifle: {
    display_name: "Bolt Rifle",
    RNG: 24,
    NB: 3,
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
  cyclone_missile_launcher_frag: {
    display_name: "Cyclone Missile Launcher (Frag)",
    COMBI_WEAPON: "cyclone_missile_launcher",
    RNG: 36,
    NB: TWO_D6,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["BLAST"],
  },
  cyclone_missile_launcher_krak: {
    display_name: "Cyclone Missile Launcher (Krak)",
    COMBI_WEAPON: "cyclone_missile_launcher",
    RNG: 36,
    NB: 2,
    ATK: 3,
    STR: 9,
    AP: -2,
    DMG: D6,
    WEAPON_RULES: [],
  },
  flamer: {
    display_name: "Flamer",
    RNG: 12,
    NB: D6,
    ATK: 7,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["IGNORES_COVER", "TORRENT"],
  },
  flamestorm_gauntlets: {
    display_name: "Flamestorm Gauntlets",
    RNG: 12,
    NB: D6_PLUS_1,
    ATK: 7,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["IGNORES_COVER", "TORRENT", "TWIN_LINKED"],
  },
  grav_gun: {
    display_name: "Grav-gun",
    RNG: 18,
    NB: 2,
    ATK: 3,
    STR: 5,
    AP: -2,
    DMG: D6,
    WEAPON_RULES: ["ANTI_VEHICLE:2"],
  },
  hand_flamer: {
    display_name: "Hand Flamer",
    RNG: 12,
    NB: D6,
    ATK: 7,
    STR: 5,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["IGNORES_COVER", "TORRENT"],
  },
  heavy_bolt_pistol: {
    display_name: "Bolt Pistol",
    RNG: 18,
    NB: 1,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["PISTOL"],
  },
  heavy_bolt_rifle: {
    display_name: "Heavy Bolt Rifle",
    RNG: 30,
    NB: 2,
    ATK: 3,
    STR: 5,
    AP: -1,
    DMG: 2,
    WEAPON_RULES: ["ASSAULT", "HEAVY"],
  },
  heavy_bolter: {
    display_name: "Heavy Bolter",
    RNG: 36,
    NB: 3,
    ATK: 3,
    STR: 5,
    AP: -1,
    DMG: 2,
    WEAPON_RULES: ["ASSAULT", "HEAVY", "SUSTAINED_HITS:1"],
  },
  heavy_flamer: {
    display_name: "Heavy Flamer",
    RNG: 12,
    NB: D6,
    ATK: 7,
    STR: 5,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["ASSAULT", "HEAVY", "SUSTAINED_HITS:1"],
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
  meltagun: {
    display_name: "Meltagun",
    RNG: 12,
    NB: 1,
    ATK: 3,
    STR: 9,
    AP: -4,
    DMG: D6,
    WEAPON_RULES: ["MELTA:2"],
  },
  melta_rifle: {
    display_name: "Melta Rifle",
    RNG: 18,
    NB: 1,
    ATK: 3,
    STR: 9,
    AP: -4,
    DMG: D6,
    WEAPON_RULES: ["HEAVY", "MELTA:2"],
  },
  multi_melta: {
    display_name: "Multi-Melta",
    RNG: 18,
    NB: 2,
    ATK: 4,
    STR: 9,
    AP: -4,
    DMG: D6,
    WEAPON_RULES: ["HEAVY", "MELTA:2"],
  },
  plasma_gun_standard: {
    display_name: "Plasma Pistol (Standard)",
    COMBI_WEAPON: "plasma_pistol",
    RNG: 24,
    NB: 1,
    ATK: 3,
    STR: 7,
    AP: -2,
    DMG: 1,
    WEAPON_RULES: ["RAPID_FIRE:1"],
  },
  plasma_gun_supercharge: {
    display_name: "Plasma Pistol (Supercharge)",
    COMBI_WEAPON: "plasma_pistol",
    RNG: 24,
    NB: 1,
    ATK: 3,
    STR: 8,
    AP: -3,
    DMG: 2,
    WEAPON_RULES: ["RAPID_FIRE:1", "HAZARDOUS"],
  },
  plasma_incinerator_standard: {
    display_name: "Plasma Incinerator (Standard)",
    COMBI_WEAPON: "plasma_incinerator",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 7,
    AP: -2,
    DMG: 1,
    WEAPON_RULES: ["ASSAULT", "HEAVY", "HAZARDOUS"],
  },
  plasma_incineratorl_supercharge: {
    display_name: "Plasma Incinerator (Supercharge)",
    COMBI_WEAPON: "plasma_incinerator",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 8,
    AP: -3,
    DMG: 2,
    WEAPON_RULES: ["ASSAULT", "HEAVY", "HAZARDOUS"],
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
    WEAPON_RULES: ["PISTOL", "HAZARDOUS"],
  },
  sternguard_bolt_rifle: {
    display_name: "Sternguard Bolt Rifle",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["ASSAULT", "HEAVY", "DEVASTATING_WOUNDS", "RAPID_FIRE:1"],
  },
  sternguard_bolt_pistol: {
    display_name: "Sternguard Bolt Pistol",
    RNG: 12,
    NB: 1,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["PISTOL", "DEVASTATING_WOUNDS"],
  },
  storm_bolter: {
    display_name: "Storm Bolter",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["RAPID_FIRE:2"],
  },
  // #########################################################################################
  // #################################### Melee Weapons ######################################
  // #########################################################################################
  assault_intercessor_chainsword: {
    display_name: "Astartes Chainsword",
    NB: 4,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: [],
  },
  astartes_chainsword: {
    display_name: "Astartes Chainsword",
    NB: 3,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: [],
  },
  close_combat_weapon: {
    display_name: "Close Combat Weapon",
    NB: 3,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
  fenrisian_wolf_teeth_and_claws: {
    display_name: "Fenrisian Wolf Teeth and Claws",
    NB: 3,
    ATK: 4,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },intercessor_sergeant_power_fist: {
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
  power_fist: {
    display_name: "Power Fist",
    NB: 3,
    ATK: 3,
    STR: 8,
    AP: -2,
    DMG: 2,
    WEAPON_RULES: [],
  },
  power_fist_pack_leader: {
    display_name: "Power Fist",
    NB: 2,
    ATK: 3,
    STR: 8,
    AP: -2,
    DMG: 2,
    WEAPON_RULES: [],
  },
  power_weapon_pack_leader: {
    display_name: "Power Weapon",
    NB: 4,
    ATK: 3,
    STR: 5,
    AP: -2,
    DMG: 1,
    WEAPON_RULES: [],
  },
  sternguard_close_combat_weapon: {
    display_name: "Close Combat Weapon",
    NB: 4,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: [],
  },
  thunder_hammer_terminator: {
    display_name: "Thunder Hammer",
    NB: 3,
    ATK: 3,
    STR: 8,
    AP: -2,
    DMG: 2,
    WEAPON_RULES: ["DEVASTATING_WOUNDS"],
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
