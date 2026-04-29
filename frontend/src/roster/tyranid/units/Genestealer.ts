// frontend/src/roster/tyranid/units/Genestealer.ts

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class Genestealer extends TroopMeleeTroop {
  static NAME = "Genestealer";
  static DISPLAY_NAME = "Genestealer";
  // BASE
  static MOVE = 8; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 5; // Armor save score
  static INVUL_SAVE = 5; // Armor invulnerable save score
  static HP_MAX = 2; // Max hit points
  static LD = 7; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(Genestealer.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["rending_claws"];
  static CC_WEAPONS = getWeapons(Genestealer.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "tyranids"}, { keywordId: "genestealer"}];


  static ICON = "/icons/Genestealer.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static ICON_SCALE = 1.6; // Size of the icon
  static ILLUSTRATION_RATIO = 100; // Illustration size ratio in percent
  
  constructor(name: string, startPos: [number, number]) {
    super(name, Genestealer.HP_MAX, startPos);
  }
}
