// frontend/src/roster/spaceMarine/units/CaptainGravisChainSwordBoltstorm.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainGravisChainSwordBoltstorm extends LeaderEliteMeleeElite {
  static NAME = "CaptainGravisChainSwordBoltstorm";
  static DISPLAY_NAME = "Captain Gravis (Chain Sword, Boltstorm Gauntlet)";

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
  static RNG_WEAPONS = getWeapons(CaptainGravisChainSwordBoltstorm.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_captain", "relic_chainsword_captain"];
  static CC_WEAPONS = getWeapons(CaptainGravisChainSwordBoltstorm.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainGravisChainSwordBoltstorm.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.9; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainGravisChainSwordBoltstorm.HP_MAX, startPos);
  }
}
