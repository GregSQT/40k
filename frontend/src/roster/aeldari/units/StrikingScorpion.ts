// frontend/src/roster/spaceMarine/units/StrikingScorpion.ts

import { getWeapons } from "../armory";
import { SwarmMeleeTroop } from "../classes/SwarmMeleeTroop";

export class StrikingScorpion extends SwarmMeleeTroop {
  static NAME = "StrikingScorpion";
  static DISPLAY_NAME = "Striking Scorpion";

  // BASE
  static MOVE = 7; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 14; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["shuriken_pistol"];
  static RNG_WEAPONS = getWeapons(StrikingScorpion.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["scorpion_chainsword"];
  static CC_WEAPONS = getWeapons(StrikingScorpion.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "aeldari"}, { keywordId: "aspect warrior"}, { keywordId: "Striking Scorpion"}];
  

  static ICON = "/icons/StrikingScorpion.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 11; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, StrikingScorpion.HP_MAX, startPos);
  }
}
