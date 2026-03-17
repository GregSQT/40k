// frontend/src/roster/spaceMarine/units/EradicatorMultiMelta.ts

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop";

export class EradicatorMultiMelta extends EliteRangeTroop {
  static NAME = "EradicatorMultiMelta";
  static DISPLAY_NAME = "Eradicator (Melta Rifle)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 34; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["melta_rifle"];
  static RNG_WEAPONS = getWeapons(EradicatorMultiMelta.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(EradicatorMultiMelta.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "eradicator squad"}];
 
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // RangedElite specialist - hunt elite targets

  static ICON = "/icons/EradicatorMultiMelta.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, EradicatorMultiMelta.HP_MAX, startPos);
  }
}
