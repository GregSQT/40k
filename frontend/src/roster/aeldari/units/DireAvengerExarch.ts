// frontend/src/roster/spaceMarine/units/DireAvengerExarch.ts

import { getWeapons } from "../armory";
import { SwarmMeleeTroop } from "../classes/SwarmMeleeTroop";

export class DireAvengerExarch extends SwarmMeleeTroop {
  static NAME = "DireAvengerExarch";
  static DISPLAY_NAME = "Dire Avenger";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shuriken_pistol"];
  static RNG_WEAPONS = getWeapons(DireAvengerExarch.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_glaive"];
  static CC_WEAPONS = getWeapons(DireAvengerExarch.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "dire avenger"}];
  
  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Elite: 6+ wounds, 3+ save + invul
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // Troop specialist - bolt rifles vs hordes


  static ICON = "/icons/DireAvenger.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, DireAvengerExarch.HP_MAX, startPos);
  }
}
