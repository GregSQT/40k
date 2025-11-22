// frontend/src/roster/spaceMarine/units/AssaultIntercessor.ts

import { SpaceMarineInfantryTroopMeleeTroop } from "../Classes/SpaceMarineInfantryTroopMeleeTroop";

export class AssaultIntercessor extends SpaceMarineInfantryTroopMeleeTroop {
  static NAME = "Assault Intercessor";
  // BASE
  static MOVE = 6;             // Move distance
  static T = 4;                // Toughness score
  static ARMOR_SAVE = 3;       // Armor save score
  static INVUL_SAVE = 0;       // Armor invulnerable save score
  static HP_MAX = 2;           // Max hit points
  static LD = 6;               // Leadership score
  static OC = 2;               // Operative Control
  static VALUE = 18;           // Unit value (W40K points cost)
  // RANGE WEAPON
  static RNG_RNG = 18;         // Range attack : range - 18
  static RNG_NB = 1;           // Range attack : number of attacks - 1
  static RNG_ATK = 3;          // Range attack : To Hit score
  static RNG_STR = 4;          // Range attack Strength
  static RNG_AP = 1;           // Range attack Armor penetration - 1
  static RNG_DMG = 1;          // Range attack : damages - 1
  // MELEE WEAPON
  static CC_NB = 4;            // Melee attack : number of attacks - 4
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 3;           // Melee attack : score
  static CC_STR = 4;           // Melee attack Strength - 4
  static CC_AP = 1;            // Melee attack Armor penetration - 1
  static CC_DMG = 1;           // Melee attack : damages - 1

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop";      // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry";       // Standard infantry movement
  static TARGET_TYPE = "Troop";        // MeleeTroop specialist - backbone melee

  static ICON = "/icons/AssaultIntercessor.webp"; // Path relative to public folder
  static ICON_SCALE = 1.6;     // Size of the icon
 
  constructor(name: string, startPos: [number, number]) {
    super(name, AssaultIntercessor.HP_MAX, startPos);
  }
}

