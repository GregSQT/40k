// frontend/src/data/UnitFactory.ts
const unitFiles = import.meta.glob("../roster/spaceMarine/*.ts", { eager: true });
const unitClassMap = {};
for (const path in unitFiles) {
    const mod = unitFiles[path];
    for (const key in mod) {
        const UnitClass = mod[key]; // 👈 Type override for static NAME
        if (typeof mod[key] === "function" && UnitClass.NAME) {
            unitClassMap[UnitClass.NAME] = mod[key];
        }
    }
}
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
