// frontend/src/roster/spaceMarine/units/TerminatorCyclone.ts

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop";

export class TerminatorCyclone extends EliteRangeTroop {
  static NAME = "TerminatorCyclone";
  static DISPLAY_NAME = "Terminator (Cyclone)";

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
  static RNG_WEAPON_CODES = ["cyclone_missile_launcher_frag", "cyclone_missile_launcher_krak"];
  static RNG_WEAPONS = getWeapons(TerminatorCyclone.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(TerminatorCyclone.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "terminator squad"}];
 

  static ICON = "/icons/TerminatorCyclone.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TerminatorCyclone.HP_MAX, startPos);
  }
}
