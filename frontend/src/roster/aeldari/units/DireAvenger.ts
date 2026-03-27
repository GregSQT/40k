// frontend/src/roster/spaceMarine/units/DireAvenger.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class DireAvenger extends SwarmRangeSwarm {
  static NAME = "DireAvenger";
  static DISPLAY_NAME = "Dire Avenger";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 14; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shuriken_catapult_avenger"];
  static RNG_WEAPONS = getWeapons(DireAvenger.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(DireAvenger.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "dire avenger"}];
  

  static ICON = "/icons/DireAvenger.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, DireAvenger.HP_MAX, startPos);
  }
}
