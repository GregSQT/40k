// frontend/src/roster/spaceMarine/units/Terminator.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class AssaultTerminator extends EliteMeleeElite {
  static NAME = "AssaultTerminator";
  static DISPLAY_NAME = "Assault Terminator";

  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 36; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = [];
  static RNG_WEAPONS = getWeapons(AssaultTerminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["thunder_hammer_terminator"];
  static CC_WEAPONS = getWeapons(AssaultTerminator.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "terminator assault squad"}];
  

  static ICON = "/icons/AssaultTerminator.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, AssaultTerminator.HP_MAX, startPos);
  }
}
