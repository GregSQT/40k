// frontend/src/roster/spaceMarine/units/CaptainTerminator.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainTerminator extends LeaderEliteMeleeElite {
  static NAME = "CaptainTerminator";
  static DISPLAY_NAME = "Captain (Terminator)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 65; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 6; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 95; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["storm_bolter_wolf_guard"];
  static RNG_WEAPONS = getWeapons(CaptainTerminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["relic_fist"];
  static CC_WEAPONS = getWeapons(CaptainTerminator.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "reroll_charge", displayName: "Unstoppable Valour" }];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "captain terminator"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "LeaderElite"; // LeaderElite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // MeleeElite specialist - hunt elite targets

  static ICON = "/icons/CaptainTerminator.webp"; // Path relative to public folder
  static ICON_SCALE = 1.9; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainTerminator.HP_MAX, startPos);
  }
}
