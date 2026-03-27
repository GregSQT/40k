// frontend/src/roster/tyranid/units/Prosecutor.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class Prosecutor extends SwarmRangeSwarm {
  static NAME = "Prosecutor";
  static DISPLAY_NAME = "Prosecutor";
  // BASE
  static MOVE = 6; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 11; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bolter"];
  static RNG_WEAPONS = getWeapons(Prosecutor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(Prosecutor.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "imperium"}, { keywordId: "anathema psykana"}, { keywordId: "prosecutor"}];
  

  static ICON = "/icons/Prosecutor.webp"; // Path relative to public folder
  static ICON_SCALE = 1.5; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Prosecutor.HP_MAX, startPos);
  }
}
