// frontend/src/roster/spaceMarine/units/WolfGuardTerminator.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite.ts";

export class WolfGuardTerminator extends EliteMeleeElite {
  static NAME = "WolfGuardTerminator";
  static DISPLAY_NAME = "Wolf Guard Terminator";

  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 33; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["storm_bolter_wolf_guard"];
  static RNG_WEAPONS = getWeapons(WolfGuardTerminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon"];
  static CC_WEAPONS = getWeapons(WolfGuardTerminator.CC_WEAPON_CODES);

  
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "wolf guard terminator squad"}];
  
  static ICON = "/icons/WolfGuardTerminator.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, WolfGuardTerminator.HP_MAX, startPos);
  }
}
