// frontend/src/roster/spaceMarine/units/ApothecaryBiologis.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class ApothecaryBiologis extends LeaderEliteMeleeElite {
  static NAME = "ApothecaryBiologis";
  static DISPLAY_NAME = "Apothecary Biologis";

  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score
  static HP_MAX = 5; // Max hit points
  static LD = 6; // Leadership score
  static OC = 3; // Operative Control
  static VALUE = 55; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["absolvor_pistol"];
  static RNG_WEAPONS = getWeapons(ApothecaryBiologis.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_captain", "relic_blade_captain"];
  static CC_WEAPONS = getWeapons(ApothecaryBiologis.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "character" },
    { keywordId: "imperium" },
    { keywordId: "gravis" },
    { keywordId: "apothecary" },
    { keywordId: "biologis" },
  ];

  static ICON = "/icons/ApothecaryBiologis.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static MODEL_HEIGHT = 2.5;  // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.9; // Size of the icon
  static ILLUSTRATION_RATIO = 130; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, ApothecaryBiologis.HP_MAX, startPos);
  }
}
