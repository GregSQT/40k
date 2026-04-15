// frontend/src/roster/spaceMarine/units/WarpSpider.ts

import { getWeapons } from "../armory";
import { SwarmRangeTroop } from "../classes/SwarmRangeTroop";

export class WarpSpider extends SwarmRangeTroop {
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
  

  static ICON = "/icons/WarpSpider.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, WarpSpider.HP_MAX, startPos);
  }
}
