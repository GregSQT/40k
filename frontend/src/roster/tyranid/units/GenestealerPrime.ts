// frontend/src/roster/tyranid/units/GenestealerPrime.ts

import { getWeapons } from "../armory";
import { TyranidInfantryEliteMeleeElite } from "../classes/TyranidInfantryEliteMeleeElite";

export class GenestealerPrime extends TyranidInfantryEliteMeleeElite {
  static NAME = "GenestealerPrime";
  static DISPLAY_NAME = "Genestealer (Prime)";
  // BASE
  static MOVE = 8; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 6; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 90; // Unit value

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(GenestealerPrime.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["rending_claws_prime"];
  static CC_WEAPONS = getWeapons(GenestealerPrime.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // // Troop: 2 wounds, 3+ save / 5+ Invu
  static MOVE_TYPE = "Infantry"; // Fast infantry movement
  static TARGET_TYPE = "Elite"; // MeleeTroop specialist - mob assault

  static ICON = "/icons/GenestealerPrime.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, GenestealerPrime.HP_MAX, startPos);
  }
}
