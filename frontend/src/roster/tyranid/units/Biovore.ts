// frontend/src/roster/tyranid/units/Biovore.ts
//

import { getWeapons } from "../armory";
import { EliteRangeTroop } from "../classes/EliteRangeTroop";

export class Biovore extends EliteRangeTroop {
  static NAME = "Biovore";
  static DISPLAY_NAME = "Biovore";
  // BASE
  static MOVE = 5; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 5; // Max hit points
  static LD = 8; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 45; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["spore_mine_launcher"];
  static RNG_WEAPONS = getWeapons(Biovore.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["chitin_barbed_limb"];
  static CC_WEAPONS = getWeapons(Biovore.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "harvester"}, { keywordId: "biovore"}];


  static ICON = "/icons/Biovore.webp"; // Path relative to public folder
  static ICON_SCALE = 2.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Biovore.HP_MAX, startPos);
  }
}
