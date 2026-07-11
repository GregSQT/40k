// frontend/src/roster/spaceMarine/units/CaptainRelicShield.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainRelicShield extends LeaderEliteMeleeElite {
  static NAME = "CaptainRelicShield";
  static DISPLAY_NAME = "Captain (Relic Shield)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 6; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["master_crafted_bolter_captain", "bolt_pistol_captain"];
  static RNG_WEAPONS = getWeapons(CaptainRelicShield.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_captain"];
  static CC_WEAPONS = getWeapons(CaptainRelicShield.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    { ruleId: "reroll_charge", displayName: "Unstoppable Valour" },
    { ruleId: "leader", displayName: "Leader" },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2, leader: 0 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = ["ASSAULT INTERCESSOR SQUAD", "BLADEGUARD VETERAN SQUAD", "COMPANY HEROES", "HELLBLASTER SQUAD", "INFERNUS SQUAD", "INTERCESSOR SQUAD", "STERNGUARD VETERAN SQUAD", "TACTICAL SQUAD"];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "CHARACTER" },
    { keywordId: "EXPLOSIVES" },
    { keywordId: "IMPERIUM" },
    { keywordId: "TACTICUS" },
    { keywordId: "CAPTAIN WITH RELIC SHIELD" },
  ];

  static ICON = "/icons/CaptainRelicShield.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 135; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainRelicShield.HP_MAX, startPos);
  }
}
