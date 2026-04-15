// frontend/src/roster/spaceMarine/units/CaptainGravisFistBoltstorm.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainGravisFistBoltstorm extends LeaderEliteMeleeElite {
  static NAME = "CaptainGravisFistBoltstorm";
  static DISPLAY_NAME = "Captain Gravis (Relic Fist, Boltstorm Gauntlet)";

  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 6; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 80; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["boltstorm_gauntlet_captain"];
  static RNG_WEAPONS = getWeapons(CaptainGravisFistBoltstorm.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_captain", "relic_fist_captain"];
  static CC_WEAPONS = getWeapons(CaptainGravisFistBoltstorm.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainGravisFistBoltstorm.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.9; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainGravisFistBoltstorm.HP_MAX, startPos);
  }
}
