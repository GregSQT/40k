// frontend/src/roster/spaceMarine/units/LieutenantPowerFistBolter.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class LieutenantPowerFistBolter extends LeaderEliteMeleeElite {
  static NAME = "LieutenantPowerFistBolter";
  static DISPLAY_NAME = "Lieutenant (Power Fist, Master-crafted Bolter)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 65; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["master_crafted_bolter_lieutenant", "heavy_bolt_pistol_lieutenant"];
  static RNG_WEAPONS = getWeapons(LieutenantPowerFistBolter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_lieutenant"];
  static CC_WEAPONS = getWeapons(LieutenantPowerFistBolter.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "target_priority",
      displayName: "Target Priority",
      grants_rule_ids: ["shoot_after_flee", "charge_after_flee"],
      usage: "and",
    },
  ];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = {
    target_priority: 2,
    shoot_after_flee: 2,
    charge_after_flee: 2,
  };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "lieutenant"}];


  static ICON = "/icons/LieutenantPowerFistBolter.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.9; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, LieutenantPowerFistBolter.HP_MAX, startPos);
  }
}
