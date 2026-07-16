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
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shoota"];
  static RNG_WEAPONS = getWeapons(BannerNob.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["choppa_a5"];
  static CC_WEAPONS = getWeapons(BannerNob.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    { ruleId: "reroll_charge", displayName: "Unstoppable Valour" },
    { ruleId: "support", displayName: "Support" },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2, support: 0 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = [
    "BOYZ",
    "BREAKA BOYZ",
    "BURNA BOYZ",
    "FLASH GITZ",
    "LOOTAS",
    "NOBZ",
    "TANKBUSTAS"
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
  static ILLUSTRATION_RATIO = 135; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, BannerNob.HP_MAX, startPos);
  }
}
