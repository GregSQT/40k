// frontend/src/roster/spaceMarine/units/LieutenantPowerWeaponPlasmaPistol.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class LieutenantPowerWeaponPlasmaPistol extends LeaderEliteMeleeElite {
  static NAME = "LieutenantPowerWeaponPlasmaPistol";
  static DISPLAY_NAME = "Lieutenant (Master-crafted Power Weapon, Plasma Pistol)";

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
  static RNG_WEAPON_CODES = ["plasma_pistol_standard_lieutenant", "plasma_pistol_supercharge_lieutenant", "heavy_bolt_pistol_lieutenant"];
  static RNG_WEAPONS = getWeapons(LieutenantPowerWeaponPlasmaPistol.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_lieutenant"];
  static CC_WEAPONS = getWeapons(LieutenantPowerWeaponPlasmaPistol.CC_WEAPON_CODES);

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


  static ICON = "/icons/LieutenantPowerWeaponPlasmaPistol.webp"; // Path relative to public folder
  static ICON_SCALE = 1.9; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, LieutenantPowerWeaponPlasmaPistol.HP_MAX, startPos);
  }
}
