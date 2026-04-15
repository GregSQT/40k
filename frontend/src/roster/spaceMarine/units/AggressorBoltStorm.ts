// frontend/src/roster/spaceMarine/units/Aggressor.ts

import { getWeapons } from "../armory";
import { EliteRangeSwarm } from "../classes/EliteRangeSwarm";

export class AggressorBoltStorm extends EliteRangeSwarm {
  static NAME = "AggressorBoltStorm";
  static DISPLAY_NAME = "Aggressor (Bolt Storm)";

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
  static RNG_WEAPONS = getWeapons(AggressorBoltStorm.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(AggressorBoltStorm.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "closest_target_penetration", displayName: "Close-quarter firepower" }];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { closest_target_penetration: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "aggressor squad"}];
  

  static ICON = "/icons/AggressorBoltstormGauntletFragstormGrenadeLauncher.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, AggressorBoltStorm.HP_MAX, startPos);
  }
}
