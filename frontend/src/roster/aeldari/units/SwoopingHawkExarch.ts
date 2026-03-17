// frontend/src/roster/spaceMarine/units/Aggressor.ts

import { getWeapons } from "../armory";
import { SwarmRangedSwarm } from "../classes/SwarmRangedSwarm";

export class SwoopingHawkExarch extends SwarmRangedSwarm {
  static NAME = "SwoopingHawkExarch";
  static DISPLAY_NAME = "Swooping Hawk";

  // BASE
  static MOVE = 14; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["hawk_talons"];
  static RNG_WEAPONS = getWeapons(SwoopingHawkExarch.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(SwoopingHawkExarch.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "swooping hawk"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Swarm"; // Swarm specialist - bolt rifles vs hordes


  static ICON = "/icons/SwoopingHawkExarch.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, SwoopingHawkExarch.HP_MAX, startPos);
  }
}
