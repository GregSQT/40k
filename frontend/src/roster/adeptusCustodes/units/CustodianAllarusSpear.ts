// frontend/src/roster/tyranid/units/CustodianAllarusSpear.ts

import { getWeapons } from "../armory";
import { EliteMeleeTroop } from "../classes/EliteMeleeTroop";

export class CustodianAllarusSpear extends EliteMeleeTroop {
  static NAME = "CustodianAllarusSpear";
  static DISPLAY_NAME = "CustodianAllarusSpear";
  // BASE
  static MOVE = 5; // Move distance
  static T = 7; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["guardian_spear_ranged", "balistus_grenade_launcher"];
  static RNG_WEAPONS = getWeapons(CustodianAllarusSpear.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["guardian_spear_melee"];
  static CC_WEAPONS = getWeapons(CustodianAllarusSpear.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "imperium"}, { keywordId: "custodian allarus"}];
  

  static ICON = "/icons/CustodianAllarusSpear.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CustodianAllarusSpear.HP_MAX, startPos);
  }
}
