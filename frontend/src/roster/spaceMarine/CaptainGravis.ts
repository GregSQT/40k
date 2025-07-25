// frontend/src/roster/spaceMarine/CaptainGravis.ts

import { SpaceMarineMeleeUnit } from "./SpaceMarineMeleeUnit";

export class CaptainGravis extends SpaceMarineMeleeUnit {
  static NAME = "Captain Gravis";

  // BASE
  static MOVE = 5;             // Move distance
  static T = 6;                // Toughness score
  static ARMOR_SAVE = 3;       // Armor save score
  static INVUL_SAVE = 4;       // Armor invulnerable save score
  static HP_MAX = 6;           // Max hit points
  static LD = 6;               // Leadership score
  static OC = 1;               // Operative Control
  static VALUE = 100;          // Unit value
  // RANGE WEAPON
  static RNG_RNG = 12;         // Range attack : range
  static RNG_NB = 1;           // Range attack : number of attacks - 3
  static RNG_ATK = 2;          // Range attack : To Hit score
  static RNG_STR = 4;          // Range attack Strength
  static RNG_AP = 1;           // Range attack Armor penetration
  static RNG_DMG = 1;          // Range attack : damages
  // MELEE WEAPON
  static CC_NB = 1;            // Melee attack : number of attacks - 5
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 2;           // Melee attack : score
  static CC_STR = 8;           // Melee attack Strength
  static CC_AP = 2;            // Melee attack Armor penetration
  static CC_DMG = 2;           // Melee attack : damages

  static ICON = "/icons/CaptainGravis.webp"; // Path relative to public folder
  static ICON_SCALE = 1.8;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainGravis.HP_MAX, startPos);
  }
}

