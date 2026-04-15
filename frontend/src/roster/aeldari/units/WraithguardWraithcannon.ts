// frontend/src/roster/spaceMarine/units/WraithguardWraithcannon.ts

import { getWeapons } from "../armory";
import { SwarmRangeTroop } from "../classes/SwarmRangeTroop";

export class WraithguardWraithcannon extends SwarmRangeTroop {
  static NAME = "WraithguardWraithcannon";
  static DISPLAY_NAME = "WraithguardWraithcannon";

  // BASE
  static MOVE = 6; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 2; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 34; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["wraithcannon"];
  static RNG_WEAPONS = getWeapons(WraithguardWraithcannon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_wraithguard"];
  static CC_WEAPONS = getWeapons(WraithguardWraithcannon.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "wraith construct"}, { keywordId: "wraithguard"}];
  

  static ICON = "/icons/WraithguardWraithcannon.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, WraithguardWraithcannon.HP_MAX, startPos);
  }
}
