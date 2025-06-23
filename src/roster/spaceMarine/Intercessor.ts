// frontend/src/roster/spaceMarine/Intercessor.ts
//
import { SpaceMarineRangedUnit, REWARDS_RANGED } from "./SpaceMarineRangedUnit";

export class Intercessor extends SpaceMarineRangedUnit {
  static NAME = "Intercessor";
  static MOVE = 4;                  // Move distance
  static RNG_NB = 1;                // Range attack : number of attacks
  static RNG_RNG = 8;               // Range attack : range
  static RNG_ATK = 66;              // Range attack : pct success
  static RNG_DMG = 2;               // Range attack : damages
  static CC_NB = 1;                 // Melee attack : number of attacks
  static CC_RNG = 1;                // Melee attack : range
  static CC_ATK = 50;               // Melee attack : pct success
  static CC_DMG = 1;                // Melee attack : damages
  static HP_MAX = 3;                // Max hit points
  static ARMOR_SAVE = 66;           // Save percentage common to most marines
  // Others as needed

  static ICON = "/icons/Intercessor.webp"; // Path relative to public folder
  
  static REWARDS = {
      ...REWARDS_RANGED,
    //move_to_rng: 0.8,    // Custom for Intercessor

    // Others as needed
  };

  constructor(name: string, startPos: [number, number]) {
    super(name, Intercessor.HP_MAX, startPos);
  }
}
