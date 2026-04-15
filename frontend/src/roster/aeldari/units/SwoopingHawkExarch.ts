// frontend/src/roster/spaceMarine/units/SwoopingHawkExarch.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class SwoopingHawkExarch extends SwarmRangeSwarm {
  static NAME = "SwoopingHawkExarch";
  static DISPLAY_NAME = "Swooping Hawk";

  // BASE
  static MOVE = 14; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["hawk_talons"];
  static RNG_WEAPONS = getWeapons(SwoopingHawkExarch.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(SwoopingHawkExarch.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "swooping hawk"}];
  

  static ICON = "/icons/SwoopingHawkExarch.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, SwoopingHawkExarch.HP_MAX, startPos);
  }
}
