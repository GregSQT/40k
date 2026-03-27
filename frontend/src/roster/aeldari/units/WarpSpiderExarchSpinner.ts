// frontend/src/roster/spaceMarine/units/Aggressor.ts

import { getWeapons } from "../armory";
import { SwarmRangeTroop } from "../classes/SwarmRangeTroop";

export class WarpSpiderExarchSpinner extends SwarmRangeTroop {
  static NAME = "WarpSpiderExarchSpinner";
  static DISPLAY_NAME = "Warp Spider Exarch";

  // BASE
  static MOVE = 12; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 21; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["death_spinner_exarch"];
  static RNG_WEAPONS = getWeapons(WarpSpiderExarchSpinner.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(WarpSpiderExarchSpinner.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Warp Spider"}];
  

  static ICON = "/icons/WarpSpiderExarchSpinner.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, WarpSpiderExarchSpinner.HP_MAX, startPos);
  }
}
