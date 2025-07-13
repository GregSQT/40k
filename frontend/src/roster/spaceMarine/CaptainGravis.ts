// frontend/src/roster/spaceMarine/CaptainGravis.ts

import { SpaceMarineMeleeUnit, REWARDS_MELEE } from "./SpaceMarineMeleeUnit";

export class CaptainGravis extends SpaceMarineMeleeUnit {
  static NAME = "Captain Gravis";
  static MOVE = 6;                  // Move distance
  static RNG_NB = 1;                // Range attack : number of attacks
  static RNG_RNG = 5;               // Range attack : range
  static RNG_ATK = 66;              // Range attack : pct success
  static RNG_DMG = 2;               // Range attack : damages
  static CC_NB = 2;                 // Melee attack : number of attacks
  static CC_RNG = 1;                // Melee attack : range
  static CC_ATK = 66;               // Melee attack : pct success
  static CC_DMG = 3;                // Melee attack : damages
  static HP_MAX = 6;                // Max hit points
  static ARMOR_SAVE = 66;           // Save percentage common to most marines
  // Others as needed

  static ICON = "/icons/CaptainGravis.webp"; // Path relative to public folder
  
  static REWARDS = {
    ...REWARDS_MELEE,
    //move_to_rng: 0.8,    // Custom for Intercessor

    // Others as needed
  };

  constructor(name: string, startPos: [number, number]) {
    super(name, CaptainGravis.HP_MAX, startPos);
  }
}

