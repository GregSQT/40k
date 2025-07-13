// frontend/src/roster/tyranid/Hormagaunt.ts

import { TyranidMeleeUnit, REWARDS_MELEE } from "./TyranidMeleeUnit";

export class Hormagaunt extends TyranidMeleeUnit {
  static NAME = "Hormagaunt";
  static MOVE = 6;                  // Move distance
  static RNG_NB = 0;                // Range attack : number of attacks
  static RNG_RNG = 0;               // Range attack : range
  static RNG_ATK = 0;              // Range attack : pct success
  static RNG_DMG = 0;               // Range attack : damages
  static CC_NB = 2;                 // Melee attack : number of attacks
  static CC_RNG = 1;                // Melee attack : range
  static CC_ATK = 66;               // Melee attack : pct success
  static CC_DMG = 1;                // Melee attack : damages
  static HP_MAX = 1;                // Max hit points
  static ARMOR_SAVE = 66;           // Save percentage common to most marines
  // Others as needed

  static ICON = "/icons/Hormagaunt.webp"; // Path relative to public folder
  
  static REWARDS = {
    ...REWARDS_MELEE,
    //move_to_rng: 0.8,    // Custom for Intercessor

    // Others as needed
  };

  constructor(name: string, startPos: [number, number]) {
    super(name, Hormagaunt.HP_MAX, startPos);
  }
}

