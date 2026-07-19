// frontend/src/roster/ork/units/BoyzNobKombi.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class BoyzNobKombi extends SwarmRangeSwarm {
  static NAME = "BoyzNobKombi";
  static DISPLAY_NAME = "Boss Nob (Kombi)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 5; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 2; // Max hit points
  static LD = 7; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 9; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["kombi_rokkit", "kombi_shoota", "slugga"];
  static RNG_WEAPONS = getWeapons(BoyzNobKombi.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["big_choppa"];
  static CC_WEAPONS = getWeapons(BoyzNobKombi.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "reroll_charge", displayName: "Unstoppable Valour" }];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "BATTLELINE" },
    { keywordId: "MOB" },
    { keywordId: "EXPLOSIVE" },
    { keywordId: "BOYZ" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ORKS" }];

  static ICON = "/icons/BoyzNobKombi.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 135; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, BoyzNobKombi.HP_MAX, startPos);
  }
}
