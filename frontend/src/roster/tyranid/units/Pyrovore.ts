// frontend/src/roster/tyranid/units/Pyrovore.ts
//

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop.ts";

export class Pyrovore extends EliteRangeTroop {
  static NAME = "Pyrovore";
  static DISPLAY_NAME = "Pyrovore";
  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 5; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 30; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["flamespurt"];
  static RNG_WEAPONS = getWeapons(Pyrovore.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["chitin_barbed_limb"];
  static CC_WEAPONS = getWeapons(Pyrovore.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "harvester"}, { keywordId: "pyrovore"}];


  static ICON = "/icons/Pyrovore.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 32; // Size of the base
  static ICON_SCALE = 2.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Pyrovore.HP_MAX, startPos);
  }
}
