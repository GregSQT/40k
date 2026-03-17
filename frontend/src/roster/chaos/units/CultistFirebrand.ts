// frontend/src/roster/tyranid/units/Carnifex.ts

import { getWeapons } from "../armory";
import { SwarmRangedSwarm } from "../classes/SwarmRangedSwarm";

export class CultistFirebrand extends SwarmRangedSwarm {
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
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Swarm: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Monster movement (treated as infantry)
  static TARGET_TYPE = "Swarm"; // RangedSwarm specialist - bolt rifles vs hordes

  static ICON = "/icons/CultistFirebrand.webp"; // Path relative to public folder
  static ICON_SCALE = 1.5; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CultistFirebrand.HP_MAX, startPos);
  }
}
