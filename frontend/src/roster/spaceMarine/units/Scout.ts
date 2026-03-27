// frontend/src/roster/spaceMarine/units/Scout.ts
//

import { getWeapons } from "../armory";
import { TroopRangeSwarm } from "../classes/TroopRangeSwarm";

export class Scout extends TroopRangeSwarm {
  static NAME = "Scout";
  static DISPLAY_NAME = "Scout";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 14; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["boltgun", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(Scout.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_scout"];
  static CC_WEAPONS = getWeapons(Scout.CC_WEAPON_CODES);

    // UNIT KEYWORDS
    static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "smoke"}, { keywordId: "imperium"}, { keywordId: "Scout squad"}];


  static ICON = "/icons/Scout.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Scout.HP_MAX, startPos);
  }
}
