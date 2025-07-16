// frontend/src/data/UnitFactory.ts

// Direct imports instead of dynamic glob
import { Intercessor } from '../roster/spaceMarine/Intercessor';
import { AssaultIntercessor } from '../roster/spaceMarine/AssaultIntercessor';
import { SpaceMarineMeleeUnit } from '../roster/spaceMarine/SpaceMarineMeleeUnit';
import { SpaceMarineRangedUnit } from '../roster/spaceMarine/SpaceMarineRangedUnit';

export type UnitType = 
  | "Intercessor" 
  | "AssaultIntercessor" 
  | "SpaceMarineMeleeUnit" 
  | "SpaceMarineRangedUnit";

export interface Unit {
  id: number;
  name: string;
  type: UnitType;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  BASE: number;
  MOVE: number;
  HP_MAX: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  ICON_SCALE?: number;
  CUR_HP?: number;
  // ✅ ADD: Dice system properties
  RNG_NB?: number;
  RNG_ATK?: number;
  RNG_STR?: number;
  RNG_AP?: number;
  CC_NB?: number;
  CC_ATK?: number;
  CC_STR?: number;
  CC_AP?: number;
  T?: number;
  ARMOR_SAVE?: number;
  INVUL_SAVE?: number;
}

// Unit class registry
const unitClassMap: Record<UnitType, any> = {
  "Intercessor": Intercessor,
  "AssaultIntercessor": AssaultIntercessor,
  "SpaceMarineMeleeUnit": SpaceMarineMeleeUnit,
  "SpaceMarineRangedUnit": SpaceMarineRangedUnit,
};

export function createUnit(params: {
  id: number;
  name: string;
  type: UnitType;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
}): Unit {
  const UnitClass = unitClassMap[params.type];
  
  if (!UnitClass) {
    throw new Error(`Unknown unit type: ${params.type}`);
  }
  
  return {
    ...params,
    BASE: UnitClass.BASE,
    MOVE: UnitClass.MOVE,
    HP_MAX: UnitClass.HP_MAX,
    RNG_RNG: UnitClass.RNG_RNG,
    RNG_DMG: UnitClass.RNG_DMG,
    CC_DMG: UnitClass.CC_DMG,
    ICON: UnitClass.ICON,
    ICON_SCALE: UnitClass.ICON_SCALE,
    CUR_HP: UnitClass.HP_MAX,
    // ✅ ADD: Dice system properties
    RNG_NB: UnitClass.RNG_NB,
    RNG_ATK: UnitClass.RNG_ATK,
    RNG_STR: UnitClass.RNG_STR,
    RNG_AP: UnitClass.RNG_AP,
    CC_NB: UnitClass.CC_NB,
    CC_ATK: UnitClass.CC_ATK,
    CC_STR: UnitClass.CC_STR,
    CC_AP: UnitClass.CC_AP,
    T: UnitClass.T,
    ARMOR_SAVE: UnitClass.ARMOR_SAVE,
    INVUL_SAVE: UnitClass.INVUL_SAVE,
  };
}
