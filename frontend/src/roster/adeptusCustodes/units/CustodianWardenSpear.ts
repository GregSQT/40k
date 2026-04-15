// frontend/src/roster/tyranid/units/CustodianWardenSpear.ts

import { getWeapons } from "../armory";
import { EliteMeleeTroop } from "../classes/EliteMeleeTroop";

export class CustodianWardenSpear extends EliteMeleeTroop {
  static NAME = "CustodianWardenSpear";
  static DISPLAY_NAME = "CustodianWardenSpear";
  // BASE
  static MOVE = 6; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 65; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["guardian_spear_ranged"];
  static RNG_WEAPONS = getWeapons(CustodianWardenSpear.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["guardian_spear_melee"];
  static CC_WEAPONS = getWeapons(CustodianWardenSpear.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "imperium"}, { keywordId: "custodian warden"}];
  

  static ICON = "/icons/CustodianWardenSpear.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CustodianWardenSpear.HP_MAX, startPos);
  }
}
