// frontend/src/roster/spaceMarine/units/CaptainPowerFistPlasmaPistol.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainPowerFistPlasmaPistol extends LeaderEliteMeleeElite {
  static NAME = "CaptainPowerFistPlasmaPistol";
  static DISPLAY_NAME = "Captain (Power Fist, Plasma Pistol)";

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
  static RNG_WEAPON_CODES = ["plasma_pistol_supercharge_captain","plasma_pistol_standard_captain"];
  static RNG_WEAPONS = getWeapons(CaptainPowerFistPlasmaPistol.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist_captain"];
  static CC_WEAPONS = getWeapons(CaptainPowerFistPlasmaPistol.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainPowerFistPlasmaPistol.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainPowerFistPlasmaPistol.HP_MAX, startPos);
  }
}
