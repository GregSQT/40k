// frontend/src/roster/spaceMarine/units/CaptainStormShield.ts

import { getWeapons } from "../armory";
import { LeaderEliteMeleeElite } from "../classes/LeaderEliteMeleeElite";

export class CaptainStormShield extends LeaderEliteMeleeElite {
  static NAME = "CaptainStormShield";
  static DISPLAY_NAME = "Captain (Master-crafted Power Weapon, Bolt Pistol, Storm Shield)";

  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 5; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 70; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bolt_pistol_captain"];
  static RNG_WEAPONS = getWeapons(CaptainStormShield.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_captain"];
  static CC_WEAPONS = getWeapons(CaptainStormShield.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "captain"}];


  static ICON = "/icons/CaptainStormShield.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainStormShield.HP_MAX, startPos);
  }
}
