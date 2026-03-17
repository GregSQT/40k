// frontend/src/roster/tyranid/units/TyrantGuardBoneCleaver.ts
//

import { getWeapons } from "../armory";
import { EliteMeleeTroop } from "../classes/EliteMeleeTroop.ts";

export class TyrantGuardBoneCleaver extends EliteMeleeTroop {
  static NAME = "TyrantGuardBoneCleaver";
  static DISPLAY_NAME = "Tyrant Guard (Bone Cleaver)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 8; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 4; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 32; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(TyrantGuardBoneCleaver.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["bone_cleaver"];
  static CC_WEAPONS = getWeapons(TyrantGuardBoneCleaver.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "tyrant guard"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 3+ wounds, 4+ save - medium armor
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // RangedElite specialist - anti-elite

  static ICON = "/icons/TyrantGuardBoneCleaver.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TyrantGuardBoneCleaver.HP_MAX, startPos);
  }
}
