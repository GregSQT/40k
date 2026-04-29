// frontend/src/roster/spaceMarine/units/Intercessor.ts
//

import { getWeapons } from "../armory";
import { TroopRangeSwarm } from "../classes/TroopRangeSwarm";

export class Intercessor extends TroopRangeSwarm {
  static NAME = "Intercessor";
  static DISPLAY_NAME = "Intercessor";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 18; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(Intercessor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(Intercessor.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "intercessor squad"}];


  static ICON = "/icons/Intercessor.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static ICON_SCALE = 1.7; // Scale of the icon
  static ILLUSTRATION_RATIO = 10; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Intercessor.HP_MAX, startPos);
  }
}
