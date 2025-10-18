// frontend/src/roster/tyranid/units/Genestealer.ts

import { TyranidInfantryTroopMeleeTroop } from "../Classes/TyranidInfantryTroopMeleeTroop";

export class Genestealer extends TyranidInfantryTroopMeleeTroop {
  static NAME = "Genestealer";
  // BASE
  static MOVE = 8;             // Move distance
  static T = 4;                // Toughness score
  static ARMOR_SAVE = 5;       // Armor save score
  static INVUL_SAVE = 5;       // Armor invulnerable save score
  static HP_MAX = 2;           // Max hit points
  static LD = 7;               // Leadership score
  static OC = 1;               // Operative Control
  static VALUE = 10;           // Unit value
  // RANGE WEAPON
  static RNG_RNG = 0;         // Range attack : range
  static RNG_NB = 0;           // Range attack : number of attacks
  static RNG_ATK = 0;          // Range attack : To Hit score
  static RNG_STR = 0;          // Range attack Strength
  static RNG_AP = 0;           // Range attack Armor penetration
  static RNG_DMG = 0;          // Range attack : damages
  // MELEE WEAPON
  static CC_NB = 4;            // Melee attack : number of attacks - 4
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 2;           // Melee attack : score
  static CC_STR = 4;           // Melee attack Strength
  static CC_AP = 2;            // Melee attack Armor penetration
  static CC_DMG = 1;           // Melee attack : damages

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop";      // // Troop: 2 wounds, 3+ save / 5+ Invu
  static MOVE_TYPE = "Infantry";       // Fast infantry movement
  static TARGET_TYPE = "Troop";        // MeleeTroop specialist - mob assault

  static ICON = "/icons/Genestealer.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Genestealer.HP_MAX, startPos);
  }
}

