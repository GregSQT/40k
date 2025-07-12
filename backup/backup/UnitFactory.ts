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
  MOVE: number;
  HP_MAX: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  CUR_HP?: number;
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
    MOVE: UnitClass.MOVE || 6,
    HP_MAX: UnitClass.HP_MAX || 4,
    RNG_RNG: UnitClass.RNG_RNG || 4,
    RNG_DMG: UnitClass.RNG_DMG || 1,
    CC_DMG: UnitClass.CC_DMG || 1,
    ICON: UnitClass.ICON || "default",
    CUR_HP: UnitClass.HP_MAX || 4,
  };
}
