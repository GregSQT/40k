// frontend/src/roster/spaceMarine/units/LieutenantCombiWeapon  .ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class LieutenantCombiWeapon extends LeaderEliteMeleeElite {
  static NAME = "LieutenantCombiWeapon";
  static DISPLAY_NAME = "Lieutenant (Combi-Weapon)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 85; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["combi_weapon_lieutenant"];
  static RNG_WEAPONS = getWeapons(LieutenantCombiWeapon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["paired_combat_blade_lieutenant"];
  static CC_WEAPONS = getWeapons(LieutenantCombiWeapon.CC_WEAPON_CODES);


  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "character" },
    { keywordId: "grenade" },
    { keywordId: "imperium" },
    { keywordId: "phobos" },
    { keywordId: "lieutenant" },
    { keywordId: "lieutenant with combi-weapon" },
  ];

  static ICON = "/icons/LieutenantCombiWeapon.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.9; // Size of the icon
  static ILLUSTRATION_RATIO = 110; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, LieutenantCombiWeapon.HP_MAX, startPos);
  }
}
