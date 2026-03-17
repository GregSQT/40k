// frontend/src/roster/spaceMarine/units/HowlingBansheeExarch.ts

import { getWeapons } from "../armory";
import { SwarmMeleeTroop } from "../classes/SwarmMeleeTroop";

export class HowlingBansheeExarch extends SwarmMeleeTroop {
  static NAME = "HowlingBansheeExarch";
  static DISPLAY_NAME = "HowlingBansheeExarch Banshee";

  // BASE
  static MOVE = 8; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 21; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shuriken_pistol"];
  static RNG_WEAPONS = getWeapons(HowlingBansheeExarch.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["mirror_swords"];
  static CC_WEAPONS = getWeapons(HowlingBansheeExarch.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "howling banshee"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // Troop specialist - bolt rifles vs hordes


  static ICON = "/icons/HowlingBansheeExarch.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, HowlingBansheeExarch.HP_MAX, startPos);
  }
}
