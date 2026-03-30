// frontend/src/roster/spaceMarine/units/CaptainPowerWeaponBolter.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainPowerWeaponBolter extends LeaderEliteMeleeElite {
  static NAME = "CaptainPowerWeaponBolter";
  static DISPLAY_NAME = "Captain (Master-crafted Power Weapon, Master-crafted Bolter)";

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
  static RNG_WEAPONS = getWeapons(CaptainPowerWeaponBolter.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_captain"];
  static CC_WEAPONS = getWeapons(CaptainPowerWeaponBolter.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainPowerWeaponBolter.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainPowerWeaponBolter.HP_MAX, startPos);
  }
}
