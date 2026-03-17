// frontend/src/roster/spaceMarine/units/Aggressor.ts

import { getWeapons } from "../armory";
import { SwarmRangedElite } from "../classes/SwarmRangedElite";

export class FireDragon extends SwarmRangedElite {
  static NAME = "FireDragon";
  static DISPLAY_NAME = "Fire Dragon";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["dragon_fusion_gun"];
  static RNG_WEAPONS = getWeapons(FireDragon.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon_aspect_warrior"];
  static CC_WEAPONS = getWeapons(FireDragon.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Fire Dragon"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Elite"; // Elite specialist - hunt elite targets


  static ICON = "/icons/FireDragon.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, FireDragon.HP_MAX, startPos);
  }
}
