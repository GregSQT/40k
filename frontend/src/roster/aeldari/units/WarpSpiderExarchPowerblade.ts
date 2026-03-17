// frontend/src/roster/spaceMarine/units/Aggressor.ts

import { getWeapons } from "../armory";
import { SwarmMeleeTroop } from "../classes/SwarmMeleeTroop.ts";

export class WarpSpiderExarchPowerblade extends SwarmMeleeTroop {
  static NAME = "WarpSpiderExarchPowerblade";
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
  static RNG_WEAPON_CODES = [];
  static RNG_WEAPONS = getWeapons(WarpSpiderExarchPowerblade.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["powerblades_array"];
  static CC_WEAPONS = getWeapons(WarpSpiderExarchPowerblade.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Warp Spider"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // Troop specialist - bolt rifles vs hordes


  static ICON = "/icons/WarpSpiderExarchSpinner.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, WarpSpiderExarchPowerblade.HP_MAX, startPos);
  }
}
