// frontend/src/roster/spaceMarine/units/CaptainPowerWeaponPistol.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainPowerWeaponPistol extends LeaderEliteMeleeElite {
  static NAME = "CaptainPowerWeaponPistol";
  static DISPLAY_NAME = "Captain (Master-crafted Power Weapon, Heavy Bolt Pistol)";

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
  static RNG_WEAPON_CODES = ["heavy_bolt_pistol_captain"];
  static RNG_WEAPONS = getWeapons(CaptainPowerWeaponPistol.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_captain"];
  static CC_WEAPONS = getWeapons(CaptainPowerWeaponPistol.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainPowerWeaponPistol.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainPowerWeaponPistol.HP_MAX, startPos);
  }
}
