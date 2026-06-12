// frontend/src/roster/spaceMarine/units/WolfGuardTerminatorAssaultCannon.ts

import { getWeapons } from "../armory.ts";
import { EliteMeleeElite } from "../classes/EliteMeleeElite.ts";

export class WolfGuardTerminatorAssaultCannon extends EliteMeleeElite {
  static NAME = "WolfGuardTerminatorAssaultCannon";
  static DISPLAY_NAME = "Wolf Guard Terminator (Assault Cannon)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 33; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["assault_cannon_wolf_guard"];
  static RNG_WEAPONS = getWeapons(WolfGuardTerminatorAssaultCannon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(WolfGuardTerminatorAssaultCannon.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "special_weapon", displayName: "Special Weapon" }];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "imperium" },
    { keywordId: "terminator" },
    { keywordId: "wolf guard terminator squad" },
  ];

  static ICON = "/icons/WolfGuardTerminatorAssaultCannon.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon
  static ILLUSTRATION_RATIO = 100; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, WolfGuardTerminatorAssaultCannon.HP_MAX, startPos);
  }
}
