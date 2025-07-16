// frontend/src/roster/spaceMarine/CaptainGravis.ts

import { TyranidMeleeUnit } from "./TyranidMeleeUnit";

export class Carnifex extends TyranidMeleeUnit {
  static NAME = "Carnifex";
  // BASE
  static MOVE = 8;             // Move distance
  static T = 9;                // Toughness score
  static ARMOR_SAVE = 2;       // Armor save score
  static INVUL_SAVE = 0;       // Armor invulnerable save score
  static HP_MAX = 8;           // Max hit points
  static LD = 8;               // Leadership score
  static OC = 3;               // Operative Control
  static VALUE = 100;          // Unit value
  // RANGE WEAPON
  static RNG_RNG = 24;         // Range attack : range
  static RNG_NB = 6;           // Range attack : number of attacks
  static RNG_ATK = 4;          // Range attack : To Hit score
  static RNG_STR = 7;          // Range attack Strength
  static RNG_AP = 2;           // Range attack Armor penetration
  static RNG_DMG = 1;          // Range attack : damages
  // MELEE WEAPON
  static CC_NB = 6;            // Melee attack : number of attacks
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 4;           // Melee attack : score
  static CC_STR = 9;           // Melee attack Strength
  static CC_AP = 2;            // Melee attack Armor penetration
  static CC_DMG = 3;           // Melee attack : damages

  static ICON = "/icons/Carnifex.webp"; // Path relative to public folder
  static ICON_SCALE = 2.2;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Carnifex.HP_MAX, startPos);
  }
}

