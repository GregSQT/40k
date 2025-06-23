// frontend/src/data/UnitFactory.ts
import { Intercessor } from "../roster/spaceMarine/Intercessor";
import { AssaultIntercessor } from "../roster/spaceMarine/AssaultIntercessor";
const unitClassMap = {
    "Intercessor": Intercessor,
    "Assault Intercessor": AssaultIntercessor,
};
export function createUnit(params) {
    const UnitClass = unitClassMap[params.type];
    return {
        ...params,
        MOVE: UnitClass.MOVE,
        HP_MAX: UnitClass.HP_MAX,
        RNG_RNG: UnitClass.RNG_RNG,
        RNG_DMG: UnitClass.RNG_DMG,
        CC_DMG: UnitClass.CC_DMG,
        ICON: UnitClass.ICON,
        // ...add other stats as needed
    };
}
