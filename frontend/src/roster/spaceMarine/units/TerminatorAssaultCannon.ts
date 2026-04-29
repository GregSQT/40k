// frontend/src/roster/spaceMarine/units/TerminatorAssaultCannon.ts

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop";

export class TerminatorAssaultCannon extends EliteRangeTroop {
  static NAME = "TerminatorAssaultCannon";
  static DISPLAY_NAME = "Terminator (Assault Cannon)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 38; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["assault_cannon"];
  static RNG_WEAPONS = getWeapons(TerminatorAssaultCannon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(TerminatorAssaultCannon.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "terminator squad"}];
 

  static ICON = "/icons/TerminatorAssaultCannon.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon
  static ILLUSTRATION_RATIO = 123; // Illustration size ratio in percent
  
  constructor(name: string, startPos: [number, number]) {
    super(name, TerminatorAssaultCannon.HP_MAX, startPos);
  }
}
