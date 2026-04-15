// frontend/src/roster/spaceMarine/units/FireDragonExarch.ts

import { getWeapons } from "../armory";
import { SwarmRangeElite } from "../classes/SwarmRangeElite";

export class FireDragonExarch extends SwarmRangeElite {
  static NAME = "FireDragonExarch";
  static DISPLAY_NAME = "Fire Dragon Exarch";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 24; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["firepike"];
  static RNG_WEAPONS = getWeapons(FireDragonExarch.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(FireDragonExarch.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Fire Dragon"}];
  

  static ICON = "/icons/FireDragonExarch.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, FireDragonExarch.HP_MAX, startPos);
  }
}
