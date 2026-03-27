// frontend/src/roster/spaceMarine/units/Incursor.ts
//

import { getWeapons } from "../armory";
import { TroopRangeSwarm } from "../classes/TroopRangeSwarm";

export class Incursor extends TroopRangeSwarm {
  static NAME = "Incursor";
  static DISPLAY_NAME = "Incursor";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 16; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["occulus_bolt_carabine", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(Incursor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(Incursor.CC_WEAPON_CODES);

    // UNIT KEYWORDS
    static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "smoke"}, { keywordId: "imperium"}, { keywordId: "phobos"}, { keywordId: "incursor squad"}];


  static ICON = "/icons/Incursor.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Incursor.HP_MAX, startPos);
  }
}
