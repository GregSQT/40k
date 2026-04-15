// frontend/src/roster/spaceMarine/units/CaptainPowerFistBolter.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainPowerFistBolter extends LeaderEliteMeleeElite {
  static NAME = "CaptainPowerFistBolter";
  static DISPLAY_NAME = "Captain (Power Fist, Master-crafted Bolter)";

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
  static RNG_WEAPONS = getWeapons(CaptainPowerFistBolter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_captain"];
  static CC_WEAPONS = getWeapons(CaptainPowerFistBolter.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainPowerFistBolter.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainPowerFistBolter.HP_MAX, startPos);
  }
}
