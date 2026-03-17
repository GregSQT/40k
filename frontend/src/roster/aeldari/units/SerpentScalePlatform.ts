// frontend/src/roster/spaceMarine/units/SerpentScalePlatform.ts

import { getWeapons } from "../armory";
import { SwarmRangeTroop } from "../classes/SwarmRangeTroop";

export class SerpentScalePlatform extends SwarmRangeTroop {
  static NAME = "SerpentScalePlatform";
  static DISPLAY_NAME = "Serpent Scale Platform";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 0; // Operative Control
  static VALUE = 20; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = [];
  static RNG_WEAPONS = getWeapons(SerpentScalePlatform.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(SerpentScalePlatform.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "guardians"}, { keywordId: "guardian defenders"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // RangedTroop specialist - bolt rifles vs hordes


  static ICON = "/icons/SerpentScalePlatform.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, SerpentScalePlatform.HP_MAX, startPos);
  }
}
