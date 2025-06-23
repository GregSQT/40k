declare const units: {
    MOVE: any;
    HP_MAX: any;
    RNG_RNG: any;
    RNG_DMG: any;
    CC_DMG: any;
    ICON: any;
    id: number;
    name: string;
    type: import("./UnitFactory.js").UnitType;
    player: 0 | 1;
    col: number;
    row: number;
    color: number;
}[];
export default units;
