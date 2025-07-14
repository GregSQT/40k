// frontend/src/roster/spaceMarine/AssaultIntercessor.ts

import { SpaceMarineMeleeUnit } from "./SpaceMarineMeleeUnit";

export class AssaultIntercessor extends SpaceMarineMeleeUnit {
  static NAME = "Assault Intercessor";
  // BASE
  static MOVE = 6;             // Move distance
  static T = 4;                // Toughness score
  static ARMOR_SAVE = 3;       // Armor save score
  static INVUL_SAVE = 0;       // Armor invulnerable save score
  static HP_MAX = 2;           // Max hit points
  static LD = 6;               // Leadership score
  static OC = 2;               // Operative Control
  static VALUE = 20;           // Unit value
  // RANGE WEAPON
  static RNG_RNG = 18;         // Range attack : range
  static RNG_NB = 1;           // Range attack : number of attacks
  static RNG_ATK = 3;          // Range attack : To Hit score
  static RNG_STR = 4;          // Range attack Strength
  static RNG_AP = 1;           // Range attack Armor penetration
  static RNG_DMG = 1;          // Range attack : damages
  // MELEE WEAPON
  static CC_NB = 4;            // Melee attack : number of attacks
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 2;           // Melee attack : score
  static CC_STR = 4;           // Melee attack Strength
  static CC_AP = 1;            // Melee attack Armor penetration
  static CC_DMG = 1;           // Melee attack : damages

  static ICON = "/icons/AssaultIntercessor.webp"; // Path relative to public folder
 
  constructor(name: string, startPos: [number, number]) {
    super(name, AssaultIntercessor.HP_MAX, startPos);
  }
}

