// frontend/src/roster/spaceMarine/units/IntercessorSergeant.ts
//

import { getWeapons } from "../armory";
import { TroopMeleeElite } from "../classes/TroopMeleeElite.ts";

export class IntercessorSergeant extends TroopMeleeElite {
  static NAME = "IntercessorSergeant";
  static DISPLAY_NAME = "Intercessor (Sergeant)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 21; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(IntercessorSergeant.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["intercessor_sergeant_power_fist"];
  static CC_WEAPONS = getWeapons(IntercessorSergeant.CC_WEAPON_CODES);

    // UNIT KEYWORDS
    static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "intercessor squad"}];


  static ICON = "/icons/IntercessorSergeant.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, IntercessorSergeant.HP_MAX, startPos);
  }
}
