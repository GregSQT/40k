// frontend/src/roster/spaceMarine/units/WraithguardDScythe.ts

import { getWeapons } from "../armory";
import { SwarmRangeTroop } from "../classes/SwarmRangeTroop";

export class WraithguardDScythe extends SwarmRangeTroop {
  static NAME = "WraithguardDScythe";
  static DISPLAY_NAME = "WraithguardDScythe";

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
  static RNG_WEAPON_CODES = ["d_scythe"];
  static RNG_WEAPONS = getWeapons(WraithguardDScythe.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_wraithguard"];
  static CC_WEAPONS = getWeapons(WraithguardDScythe.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "wraith construct"}, { keywordId: "wraithguard"}];
  

  static ICON = "/icons/WraithguardDScythe.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, WraithguardDScythe.HP_MAX, startPos);
  }
}
