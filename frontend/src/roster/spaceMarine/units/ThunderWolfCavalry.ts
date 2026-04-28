// frontend/src/roster/spaceMarine/units/ThunderWolfCavalry.ts

import { getWeapons } from "../armory.ts";
import { EliteMeleeElite } from "../classes/EliteMeleeElite.ts";

export class ThunderWolfCavalry extends EliteMeleeElite {
  static NAME = "ThunderWolfCavalry";
  static DISPLAY_NAME = "Thunder Wolf Cavalry";

  // BASE
  static MOVE = 12; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 4; // Armor invulnerable save score
  static HP_MAX = 4; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 38; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(ThunderWolfCavalry.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["wolf_guard_weapon", "teeth_and_claws"];
  static CC_WEAPONS = getWeapons(ThunderWolfCavalry.CC_WEAPON_CODES);

  
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "mounted"}, { keywordId: "grenade"}, { keywordId: "imperium"}, { keywordId: "thunderwolf cavalry"}];
  
  static ICON = "/icons/ThunderWolfCavalry.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.0; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, ThunderWolfCavalry.HP_MAX, startPos);
  }
}
