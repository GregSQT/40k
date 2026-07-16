// frontend/src/roster/ork/units/Gretchin.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class Gretchin extends SwarmRangeSwarm {
  static NAME = "Gretchin";
  static DISPLAY_NAME = "Gretchin";

  // BASE
  static MOVE = 6; // Move distance
  static T = 2; // Toughness score
  static ARMOR_SAVE = 7; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 1; // Max hit points
  static LD = 8; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["blasta"];
  static RNG_WEAPONS = getWeapons(Gretchin.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_a1"];
  static CC_WEAPONS = getWeapons(Gretchin.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    { ruleId: "reroll_charge", displayName: "Unstoppable Valour" },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "GROTS" },
    { keywordId: "GRETCHIN" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ORKS" }];

  static ICON = "/icons/Gretchin.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 135; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Gretchin.HP_MAX, startPos);
  }
}
