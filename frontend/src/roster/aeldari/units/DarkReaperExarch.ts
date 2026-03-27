// frontend/src/roster/spaceMarine/units/DarkReaperExarch.ts

import { getWeapons } from "../armory";
import { SwarmRangeTroop } from "../classes/SwarmRangeTroop";

export class DarkReaperExarch extends SwarmRangeTroop {
  static NAME = "DarkReaperExarch";
  static DISPLAY_NAME = "Dark Reaper Exarch";

  // BASE
  static MOVE = 6; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 21; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["missile_launcher_starshot", "missile_launcher_starswarm"];
  static RNG_WEAPONS = getWeapons(DarkReaperExarch.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(DarkReaperExarch.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Dark Reaper"}];
  

  static ICON = "/icons/DarkReaperExarch.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, DarkReaperExarch.HP_MAX, startPos);
  }
}
