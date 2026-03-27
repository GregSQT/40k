// frontend/src/roster/spaceMarine/units/Terminator.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class Terminator extends EliteMeleeElite {
  static NAME = "Terminator";
  static DISPLAY_NAME = "Terminator";

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
  static RNG_WEAPON_CODES = ["storm_bolter"];
  static RNG_WEAPONS = getWeapons(Terminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(Terminator.CC_WEAPON_CODES);

  
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "terminator squad"}];
  
  static ICON = "/icons/TerminatorPowerFist.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Terminator.HP_MAX, startPos);
  }
}
