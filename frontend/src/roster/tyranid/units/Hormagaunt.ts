// frontend/src/roster/tyranid/units/Hormagaunt.ts

import { TyranidInfantrySwarmMeleeSwarm } from "../Classes/TyranidInfantrySwarmMeleeSwarm";

export class Hormagaunt extends TyranidInfantrySwarmMeleeSwarm {
  static NAME = "Hormagaunt";
  // BASE
  static MOVE = 10;             // Move distance
  static T = 3;                // Toughness score
  static ARMOR_SAVE = 5;       // Armor save score
  static INVUL_SAVE = 0;       // Armor invulnerable save score
  static HP_MAX = 1;           // Max hit points
  static LD = 8;               // Leadership score
  static OC = 2;               // Operative Control
  static VALUE = 7;            // Unit value (W40K points cost)
  // RANGE WEAPON
  static RNG_RNG = 0;         // Range attack : range
  static RNG_NB = 0;           // Range attack : number of attacks
  static RNG_ATK = 0;          // Range attack : To Hit score
  static RNG_STR = 0;          // Range attack Strength
  static RNG_AP = 0;           // Range attack Armor penetration
  static RNG_DMG = 0;          // Range attack : damages
  // MELEE WEAPON
  static CC_NB = 3;            // Melee attack : number of attacks - 3
  static CC_RNG = 1;           // Melee attack : range
  static CC_ATK = 4;           // Melee attack : score
  static CC_STR = 3;           // Melee attack Strength
  static CC_AP = 1;            // Melee attack Armor penetration
  static CC_DMG = 1;           // Melee attack : damages

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm";      // Swarm: 1 wound, fragile
  static MOVE_TYPE = "Infantry";       // Fast infantry movement
  static TARGET_TYPE = "Swarm";        // MeleeSwarm specialist - mob assault

  static ICON = "/icons/Hormagaunt.webp"; // Path relative to public folder
  static ICON_SCALE = 1.4;     // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Hormagaunt.HP_MAX, startPos);
  }
}

