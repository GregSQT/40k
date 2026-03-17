// frontend/src/roster/spaceMarine/units/Aggressor.ts

import { getWeapons } from "../armory";
import { SwarmRangedTroop } from "../classes/SwarmRangedTroop";

export class WarpSpider extends SwarmRangedTroop {
  static NAME = "WarpSpider";
  static DISPLAY_NAME = "Dark Reaper";

  // BASE
  static MOVE = 12; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 16; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["death_spinner"];
  static RNG_WEAPONS = getWeapons(WarpSpider.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(WarpSpider.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Warp Spider"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // Troop specialist - bolt rifles vs hordes


  static ICON = "/icons/WarpSpider.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, WarpSpider.HP_MAX, startPos);
  }
}
