// frontend/src/roster/spaceMarine/AssaultIntercessor.ts
import { SpaceMarineMeleeUnit, REWARDS_MELEE } from "./SpaceMarineMeleeUnit";
export class AssaultIntercessor extends SpaceMarineMeleeUnit {
    constructor(name, startPos) {
        super(name, AssaultIntercessor.HP_MAX, startPos);
    }
}
AssaultIntercessor.NAME = "Assault Intercessor";
AssaultIntercessor.MOVE = 6; // Move distance
AssaultIntercessor.RNG_NB = 1; // Range attack : number of attacks
AssaultIntercessor.RNG_RNG = 4; // Range attack : range
AssaultIntercessor.RNG_ATK = 66; // Range attack : pct success
AssaultIntercessor.RNG_DMG = 1; // Range attack : damages
AssaultIntercessor.CC_NB = 2; // Melee attack : number of attacks
AssaultIntercessor.CC_RNG = 1; // Melee attack : range
AssaultIntercessor.CC_ATK = 66; // Melee attack : pct success
AssaultIntercessor.CC_DMG = 2; // Melee attack : damages
AssaultIntercessor.HP_MAX = 4; // Max hit points
AssaultIntercessor.ARMOR_SAVE = 66; // Save percentage common to most marines
// Others as needed
AssaultIntercessor.ICON = "/icons/AssaultIntercessor.webp"; // Path relative to public folder
AssaultIntercessor.REWARDS = {
    ...REWARDS_MELEE,
    //move_to_rng: 0.8,    // Custom for Intercessor
    // Others as needed
};
