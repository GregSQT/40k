// frontend/src/roster/spaceMarine/units/InceptorPlasma.ts
//

import { getWeapons } from "../armory.ts";
import { EliteRangeTroop } from "../classes/EliteRangeTroop.ts";

export class InceptorPlasma extends EliteRangeTroop {
  static NAME = "InceptorPlasma";
  static DISPLAY_NAME = "Inceptor Plasma";
  // BASE
  static MOVE = 10; // Move distance
  static T = 6; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 24; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_exterminator_standard", "plasma_exterminator_supercharge"];
  static RNG_WEAPONS = getWeapons(InceptorPlasma.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(InceptorPlasma.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "jump pack"}, { keywordId: "fly"}, { keywordId: "imperium"}, { keywordId: "gravis"}, { keywordId: "inceptor squad"}];


  static ICON = "/icons/InceptorPlasma.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, InceptorPlasma.HP_MAX, startPos);
  }
}
