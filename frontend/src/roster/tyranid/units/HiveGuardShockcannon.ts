// frontend/src/roster/tyranid/units/HiveGuardShockcannon.ts
//

import { getWeapons } from "../armory";
import { TroopRangeElite } from "../classes/TroopRangeElite";

export class HiveGuardShockcannon extends TroopRangeElite {
  static NAME = "HiveGuardShockcannon";
  static DISPLAY_NAME = "HiveGuard (Shock Cannon)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 7; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 4; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 32; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shockcannon"];
  static RNG_WEAPONS = getWeapons(HiveGuardShockcannon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["chitinous_claws_and_teeth_hive_guard"];
  static CC_WEAPONS = getWeapons(HiveGuardShockcannon.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "hiveguard"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 3+ wounds, 4+ save - medium armor
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // RangedElite specialist - anti-elite

  static ICON = "/icons/HiveGuardShockcannon.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, HiveGuardShockcannon.HP_MAX, startPos);
  }
}
