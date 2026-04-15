// frontend/src/roster/spaceMarine/units/HeavyIntercessorHeavyBolter.ts
//

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop.ts";

export class HeavyIntercessorHeavyBolter extends EliteRangeTroop {
  static NAME = "HeavyIntercessorHeavyBolter";
  static DISPLAY_NAME = "Heavy Intercessor (Heavy Bolter)";
  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 24; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["heavy_bolter", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(HeavyIntercessorHeavyBolter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(HeavyIntercessorHeavyBolter.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "heavy intercessor squad"}];
  

  static ICON = "/icons/HeavyIntercessor.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, HeavyIntercessorHeavyBolter.HP_MAX, startPos);
  }
}
