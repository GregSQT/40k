// frontend/src/roster/ork/units/BigMekDakkarig.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class BigMekDakkarig extends SwarmRangeSwarm {
  static NAME = "BigMekDakkarig";
  static DISPLAY_NAME = "BigMekDakkarig";

  // BASE
  static MOVE = 8; // Move distance
  static T = 8; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score
  static HP_MAX = 11; // Max hit points
  static LD = 7; // Leadership score
  static OC = 3; // Operative Control
  static VALUE = 115; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["blitzcannon", "rokkit_launcha_heavy"];
  static RNG_WEAPONS = getWeapons(BigMekDakkarig.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["stompy_feet"];
  static CC_WEAPONS = getWeapons(BigMekDakkarig.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    // Dakkablitz : « In your Shooting phase, while making attacks with this unit, if its
    // blitzcannon targeted a non-MONSTER/VEHICLE unit, that weapon has +6 A. »
    {
      ruleId: "weapon_attacks_bonus_vs_keyword",
      displayName: "Dakkablitz",
      rule_args: { weapon_code: "blitzcannon", attacks_bonus: 6, excluded_keywords: ["MONSTER", "VEHICLE"] },
    },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { weapon_attacks_bonus_vs_keyword: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "VEHICLE" },
    { keywordId: "WALKER" },
    { keywordId: "BIG MEK" },
    { keywordId: "DAKKARIG" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ORKS" }];

  static ICON = "/icons/BigMekDakkarig.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 35; // Size of the base
  static MODEL_HEIGHT = 5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 170; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, BigMekDakkarig.HP_MAX, startPos);
  }
}
