// frontend/src/data/UnitFactory.ts

const unitFiles = import.meta.glob<{
  [key: string]: { [exported: string]: any }
}>("../roster/spaceMarine/*.ts", { eager: true });

const unitClassMap: Record<string, any> = {};

for (const path in unitFiles) {
  const mod = unitFiles[path];
  for (const key in mod) {
    const UnitClass = mod[key] as { NAME: string }; // 👈 Type override for static NAME
    if (typeof mod[key] === "function" && UnitClass.NAME) {
      unitClassMap[UnitClass.NAME] = mod[key];
    }
  }
}

// ...add other units as needed

export type UnitType = keyof typeof unitClassMap;

export type Unit = {
  id: number;
  name: string;
  type: UnitType;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP?: number; // Ourrent HP
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
};

export function createUnit(params: {
  id: number;
  name: string;
  type: UnitType;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
}) {
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
