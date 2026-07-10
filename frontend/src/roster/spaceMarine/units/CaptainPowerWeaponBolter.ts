// frontend/src/roster/spaceMarine/units/CaptainPowerWeaponBolter.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainPowerWeaponBolter extends LeaderEliteMeleeElite {
  static NAME = "CaptainPowerWeaponBolter";
  static DISPLAY_NAME = "Captain (Master-crafted Power Weapon, Master-crafted Bolter)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 5; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["master_crafted_bolter_captain", "bolt_pistol_captain"];
  static RNG_WEAPONS = getWeapons(CaptainPowerWeaponBolter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_captain"];
  static CC_WEAPONS = getWeapons(CaptainPowerWeaponBolter.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    { ruleId: "reroll_charge", displayName: "Unstoppable Valour" },
    { ruleId: "leader", displayName: "Leader" },
  ];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2, leader: 0 };

  // CAN LEAD (bodyguard unit-name keywords this leader may attach to — rule 19.01)
  static CAN_LEAD = ["assault intercessor squad", "intercessor squad"];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "character" },
    { keywordId: "grenade" },
    { keywordId: "imperium" },
    { keywordId: "tacticus" },
    { keywordId: "captain" },
  ];

  static ICON = "/icons/CaptainPowerWeaponBolter.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Size of the icon
  static ILLUSTRATION_RATIO = 135; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainPowerWeaponBolter.HP_MAX, startPos);
  }
}
