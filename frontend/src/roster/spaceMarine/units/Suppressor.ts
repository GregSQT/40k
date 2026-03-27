// frontend/src/roster/spaceMarine/units/Suppressor.ts
//

import { getWeapons } from "../armory.ts";
import { EliteRangeTroop } from "../classes/EliteRangeTroop.ts";

export class Suppressor extends EliteRangeTroop {
  static NAME = "Suppressor";
  static DISPLAY_NAME = "Suppressor";
  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 15; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["accelerator_autocannon", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(Suppressor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(Suppressor.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "smoke"}, { keywordId: "jump pack"}, { keywordId: "fly"}, { keywordId: "imperium"}, { keywordId: "suppressor squad"}];


  static ICON = "/icons/Suppressor.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Suppressor.HP_MAX, startPos);
  }
}
