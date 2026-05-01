// frontend/src/roster/tyranid/units/Mucolid.ts

import { getWeapons } from "../armory";
import { EliteMeleeElite } from "../classes/EliteMeleeElite";

export class Mucolid extends EliteMeleeElite {
  static NAME = "Mucolid";
  static DISPLAY_NAME = "Mucolid";
  // BASE
  static MOVE = 4; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 7; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 8; // Leadership score
  static OC = 0; // Operative Control
  static VALUE = 40; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(Mucolid.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES: string[] = [];
  static CC_WEAPONS = getWeapons(Mucolid.CC_WEAPON_CODES);
    
  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "beast"}, { keywordId: "fly"}, { keywordId: "great devourer"}, { keywordId: "mucolid"}];
  

  static ICON = "/icons/Mucolid.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 2.6; // Size of the icon
  static ILLUSTRATION_RATIO = 100; // Illustration size ratio in percent
  
  constructor(name: string, startPos: [number, number]) {
    super(name, Mucolid.HP_MAX, startPos);
  }
}
