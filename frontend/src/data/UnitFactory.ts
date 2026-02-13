// frontend/src/data/UnitFactory.ts
// AI_TURN.md compliant dynamic unit factory - zero hardcoding

import type { Unit, Weapon } from "../types/game";

// Dynamic unit registry - populated by directory scanning
interface UnitClass {
  HP_MAX: number;
  MOVE: number;
  ICON: string;
  ICON_SCALE?: number;
  T?: number;
  ARMOR_SAVE?: number;
  INVUL_SAVE?: number;
  LD?: number;
  OC?: number;
  VALUE?: number;
  RNG_WEAPONS?: Array<Record<string, unknown>>;
  CC_WEAPONS?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}
let unitClassMap: Record<string, UnitClass> = {};
let availableUnitTypes: string[] = [];
let initialized = false;

// Load units from config file (same approach as BoardReplay.tsx)
async function initializeUnitRegistry(): Promise<void> {
  if (initialized) return;

  try {
    // Clear existing registry
    unitClassMap = {};
    availableUnitTypes = [];

    // Load unit registry from config file
    const registryResponse = await fetch("/config/unit_registry.json");

    if (!registryResponse.ok) {
      throw new Error(`Failed to load unit registry: ${registryResponse.statusText}`);
    }

    const text = await registryResponse.text();
    const unitConfig = JSON.parse(text);

    // Dynamically import each unit class using config paths
    for (const [unitType, unitPath] of Object.entries(unitConfig.units) as [string, string][]) {
      try {
        const module = await import(/* @vite-ignore */ `../roster/${unitPath}.ts`);
        const UnitClass = module[unitType] || module.default;

        if (!UnitClass) {
          throw new Error(`Unit class ${unitType} not found in ${unitPath}`);
        }

        // Validate required UPPERCASE properties
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: At least one weapon required (RNG_WEAPONS or CC_WEAPONS)
        const requiredProps = ["HP_MAX", "MOVE", "ICON"];
        requiredProps.forEach((prop) => {
          if (UnitClass[prop] === undefined) {
            throw new Error(`Unit ${unitType} missing required UPPERCASE property: ${prop}`);
          }
        });

        // Validate at least one weapon type exists
        if (
          (!UnitClass.RNG_WEAPONS || UnitClass.RNG_WEAPONS.length === 0) &&
          (!UnitClass.CC_WEAPONS || UnitClass.CC_WEAPONS.length === 0)
        ) {
          throw new Error(`Unit ${unitType} must have at least RNG_WEAPONS or CC_WEAPONS`);
        }

        unitClassMap[unitType] = UnitClass;
        availableUnitTypes.push(unitType);
      } catch (importError) {
        console.error(`❌ Failed to import unit ${unitType}:`, importError);
        throw importError;
      }
    }

    initialized = true;
  } catch (error) {
    console.error("❌ Failed to initialize unit registry:", error);
    throw error;
  }
}

export function getAvailableUnitTypes(): string[] {
  return [...availableUnitTypes];
}

export function isValidUnitType(type: string): boolean {
  return type in unitClassMap;
}

export function getUnitClass(type: string) {
  const UnitClass = unitClassMap[type];
  if (!UnitClass) {
    throw new Error(`Unknown unit type: ${type}. Available: ${getAvailableUnitTypes().join(", ")}`);
  }
  return UnitClass;
}

// Create unit with UPPERCASE field validation
export function createUnit(params: {
  id: number;
  name: string;
  type: string;
  player: 1 | 2;
  col: number;
  row: number;
  color: number;
}): Unit {
  if (!initialized) {
    throw new Error("Unit registry not initialized. Call await initializeUnitRegistry() first.");
  }

  const UnitClass = getUnitClass(params.type);

  // Validate all UPPERCASE fields exist
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: At least one weapon required
  const requiredFields = ["HP_MAX", "MOVE", "ICON"];
  for (const field of requiredFields) {
    if (UnitClass[field] === undefined) {
      throw new Error(`Unit class ${params.type} missing required UPPERCASE field: ${field}`);
    }
  }

  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate at least one weapon type exists
  const rngWeapons = UnitClass.RNG_WEAPONS || [];
  const ccWeapons = UnitClass.CC_WEAPONS || [];

  if (rngWeapons.length === 0 && ccWeapons.length === 0) {
    throw new Error(`Unit class ${params.type} must have at least RNG_WEAPONS or CC_WEAPONS`);
  }

  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Initialize selected weapon indices
  const selectedRngWeaponIndex = rngWeapons.length > 0 ? 0 : undefined;
  const selectedCcWeaponIndex = ccWeapons.length > 0 ? 0 : undefined;

  return {
    id: params.id,
    name: params.name,
    type: params.type,
    player: params.player,
    col: params.col,
    row: params.row,
    color: params.color,
    // UPPERCASE field compliance
    MOVE: UnitClass.MOVE,
    HP_MAX: UnitClass.HP_MAX,
    ICON: UnitClass.ICON,
    ICON_SCALE: UnitClass.ICON_SCALE,
    HP_CUR: UnitClass.HP_MAX, // Start at full health
    T: UnitClass.T,
    ARMOR_SAVE: UnitClass.ARMOR_SAVE,
    INVUL_SAVE: UnitClass.INVUL_SAVE,
    LD: UnitClass.LD,
    OC: UnitClass.OC,
    VALUE: UnitClass.VALUE,
    // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Multiple weapons system
    RNG_WEAPONS: rngWeapons as unknown as Weapon[],
    CC_WEAPONS: ccWeapons as unknown as Weapon[],
    selectedRngWeaponIndex,
    selectedCcWeaponIndex,
  };
}

export { initializeUnitRegistry };
