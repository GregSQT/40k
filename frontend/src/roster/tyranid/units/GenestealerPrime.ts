// frontend/src/roster/tyranid/units/GenestealerPrime.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class GenestealerPrime extends EliteMeleeElite {
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

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "tyranids"}, { keywordId: "genestealer"}];


  static ICON = "/icons/GenestealerPrime.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, GenestealerPrime.HP_MAX, startPos);
  }
}
