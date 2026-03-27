// frontend/src/roster/tyranid/units/CultistMob.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class CultistMob extends SwarmRangeSwarm {
  static NAME = "CultistMob";
  static DISPLAY_NAME = "CultistMob";
  // BASE
  static MOVE = 6; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 6; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 5; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["autopistol"];
  static RNG_WEAPONS = getWeapons(CultistMob.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["brutal_assault_weapon"];
  static CC_WEAPONS = getWeapons(CultistMob.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "chaos"}, { keywordId: "damned"}, { keywordId: "cultist mob"}];
  

  static ICON = "/icons/CultistMob.webp"; // Path relative to public folder
  static ICON_SCALE = 1.5; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CultistMob.HP_MAX, startPos);
  }
}
