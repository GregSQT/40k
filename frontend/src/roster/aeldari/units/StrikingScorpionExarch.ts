// frontend/src/roster/spaceMarine/units/StrikingScorpion.ts

import { getWeapons } from "../armory";
import { SwarmMeleeTroop } from "../classes/SwarmMeleeTroop";

export class StrikingScorpionExarch extends SwarmMeleeTroop {
  static NAME = "StrikingScorpionExarch";
  static DISPLAY_NAME = "Striking Scorpion Exarch";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shuriken_pistol"];
  static RNG_WEAPONS = getWeapons(StrikingScorpionExarch.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["scorpion_claws"];
  static CC_WEAPONS = getWeapons(StrikingScorpionExarch.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Striking Scorpion"}];
  

  static ICON = "/icons/StrikingScorpion.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, StrikingScorpionExarch.HP_MAX, startPos);
  }
}
