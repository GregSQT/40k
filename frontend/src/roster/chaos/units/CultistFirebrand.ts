// frontend/src/roster/tyranid/units/CultistFirebrand.ts

import { getWeapons } from "../armory";
import { SwarmRangeSwarm } from "../classes/SwarmRangeSwarm";

export class CultistFirebrand extends SwarmRangeSwarm {
  static NAME = "CultistFirebrand";
  static DISPLAY_NAME = "CultistFirebrand";
  // BASE
  static MOVE = 6; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 60; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["balefire_pike"];
  static RNG_WEAPONS = getWeapons(CultistFirebrand.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_firebrand"];
  static CC_WEAPONS = getWeapons(CultistFirebrand.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "character"}, { keywordId: "grenades"}, { keywordId: "chaos"}, { keywordId: "damned"}, { keywordId: "cultist firebrand"}];
  

  static ICON = "/icons/CultistFirebrand.webp"; // Path relative to public folder
  static ICON_SCALE = 1.5; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CultistFirebrand.HP_MAX, startPos);
  }
}
