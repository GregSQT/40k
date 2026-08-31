// frontend/src/roster/ork/units/BannerNob.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class BannerNob extends SwarmRangeSwarm {
  static NAME = "BannerNob";
  static DISPLAY_NAME = "BannerNob";

  // BASE
  static MOVE = 6; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score
  static HP_MAX = 4; // Max hit points
  static LD = 7; // Leadership score
  static OC = 6; // Operative Control
  static VALUE = 50; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shoota"];
  static RNG_WEAPONS = getWeapons(BannerNob.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["choppa_a5"];
  static CC_WEAPONS = getWeapons(BannerNob.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    { ruleId: "support", displayName: "Support" },
    {
      ruleId: "invul_save_override",
      displayName: "Waaagh! Banner (InSv)",
      rule_args: { value: 5 },
    },
    {
      ruleId: "toughness_bonus_while_waaagh",
      displayName: "Waaagh! Banner (T+1)",
      rule_args: { toughness_bonus: 1 },
    },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { support: 2, invul_save_override: 2, toughness_bonus_while_waaagh: 2 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = [
    "BOYZ",
    "BREAKA BOYZ",
    "BURNA BOYZ",
    "FLASH GITZ",
    "LOOTAS",
    "NOBZ",
    "TANKBUSTAS",
  ];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "CHARACTER" },
    { keywordId: "BANNERNOB" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ORKS" }];

  static ICON = "/icons/BannerNob.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 170; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, BannerNob.HP_MAX, startPos);
  }
}
