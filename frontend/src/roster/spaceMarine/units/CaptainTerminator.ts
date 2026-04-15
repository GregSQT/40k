// frontend/src/roster/spaceMarine/units/CaptainTerminatorRelicWeaponBolter.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainTerminatorRelicWeaponBolter extends LeaderEliteMeleeElite {
  static NAME = "CaptainTerminatorRelicWeaponBolter";
  static DISPLAY_NAME = "Captain Terminator (Relic Weapon, Storm Bolter)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 6; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 95; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["storm_bolter_captain"];
  static RNG_WEAPONS = getWeapons(CaptainTerminatorRelicWeaponBolter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_captain"];
  static CC_WEAPONS = getWeapons(CaptainTerminatorRelicWeaponBolter.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "reroll_charge", displayName: "Unstoppable Valour" }];

  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { reroll_charge: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "imperium"}, { keywordId: "terminator"}, { keywordId: "captain terminator"}];


  static ICON = "/icons/CaptainTerminatorRelicWeaponBolter.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 20; // Size of the base
  static ICON_SCALE = 1.9; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainTerminatorRelicWeaponBolter.HP_MAX, startPos);
  }
}
