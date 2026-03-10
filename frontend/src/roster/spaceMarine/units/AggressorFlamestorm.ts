// frontend/src/roster/spaceMarine/units/Aggressor.ts

import { getWeapons } from "../armory";
import { SpaceMarineInfantryEliteRangedSwarm } from "../classes/SpaceMarineInfantryEliteRangedSwarm";

export class AggressorFlamestorm extends SpaceMarineInfantryEliteRangedSwarm {
  static NAME = "AggressorFlamestorm";
  static DISPLAY_NAME = "Aggressor (Flamestorm)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 33; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["auto_boltstorm_gauntlets"];
  static RNG_WEAPONS = getWeapons(AggressorFlamestorm.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(AggressorFlamestorm.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "closest_target_penetration", displayName: "Close-quarter firepower" }];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "aggressor squad"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Elite"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Swarm"; // RangedTroop specialist - bolt rifles vs hordes


  static ICON = "/icons/AggressorFlamestormGauntletFragstormGrenadeLauncher.webp"; // Path relative to public folder
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, AggressorFlamestorm.HP_MAX, startPos);
  }
}
