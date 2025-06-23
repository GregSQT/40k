// frontend/src/roster/spaceMarine/Intercessor.ts
//
import { SpaceMarineRangedUnit, REWARDS_RANGED } from "./SpaceMarineRangedUnit";
export class Intercessor extends SpaceMarineRangedUnit {
    constructor(name, startPos) {
        super(name, Intercessor.HP_MAX, startPos);
    }
}
Intercessor.NAME = "Intercessor";
Intercessor.MOVE = 4; // Move distance
Intercessor.RNG_NB = 1; // Range attack : number of attacks
Intercessor.RNG_RNG = 8; // Range attack : range
Intercessor.RNG_ATK = 66; // Range attack : pct success
Intercessor.RNG_DMG = 2; // Range attack : damages
Intercessor.CC_NB = 1; // Melee attack : number of attacks
Intercessor.CC_RNG = 1; // Melee attack : range
Intercessor.CC_ATK = 50; // Melee attack : pct success
Intercessor.CC_DMG = 1; // Melee attack : damages
Intercessor.HP_MAX = 3; // Max hit points
Intercessor.ARMOR_SAVE = 66; // Save percentage common to most marines
// Others as needed
Intercessor.ICON = "/icons/Intercessor.webp"; // Path relative to public folder
Intercessor.REWARDS = {
    ...REWARDS_RANGED,
    //move_to_rng: 0.8,    // Custom for Intercessor
    // Others as needed
};
