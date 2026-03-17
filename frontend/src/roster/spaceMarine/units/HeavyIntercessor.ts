// frontend/src/roster/spaceMarine/units/HeavyIntercessor.ts
//

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop.ts";

export class HeavyIntercessor extends EliteRangeTroop {
  static NAME = "HeavyIntercessor";
  static DISPLAY_NAME = "Heavy Intercessor";
  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["heavy_bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(HeavyIntercessor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(HeavyIntercessor.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "heavy intercessor squad"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 3+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // RangedTroop specialist - bolt rifles vs hordes

  static ICON = "/icons/HeavyIntercessor.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, HeavyIntercessor.HP_MAX, startPos);
  }
}
