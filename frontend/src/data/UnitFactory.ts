// frontend/src/data/UnitFactory.ts
// AI_TURN.md compliant dynamic unit factory - zero hardcoding

// Dynamic unit registry - populated by directory scanning  
let unitClassMap: Record<string, any> = {};
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
    const registryResponse = await fetch('/config/unit_registry.json');
    
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
        
        // AI_TURN.md: Validate required UPPERCASE properties
        const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
        requiredProps.forEach(prop => {
          if (UnitClass[prop] === undefined) {
            throw new Error(`Unit ${unitType} missing required UPPERCASE property: ${prop}`);
          }
        });
        
        unitClassMap[unitType] = UnitClass;
        availableUnitTypes.push(unitType);
        
      } catch (importError) {
        console.error(`❌ Failed to import unit ${unitType}:`, importError);
        throw importError;
      }
    }
    
    initialized = true;
    console.log(`✅ Unit registry initialized with ${availableUnitTypes.length} units:`, availableUnitTypes);
    
  } catch (error) {
    console.error('❌ Failed to initialize unit registry:', error);
    throw error;
  }
}

// AI_TURN.md: Unit interface with UPPERCASE field compliance
export interface Unit {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  // AI_TURN.md: Required UPPERCASE fields
  MOVE: number;
  HP_MAX: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  CC_RNG?: number;
  ICON: string;
  ICON_SCALE?: number;
  HP_CUR?: number;
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
  LD?: number;
  OC?: number;
  VALUE?: number;
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
    throw new Error(`Unknown unit type: ${type}. Available: ${getAvailableUnitTypes().join(', ')}`);
  }
  return UnitClass;
}

// AI_TURN.md: Create unit with UPPERCASE field validation
export function createUnit(params: {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
}): Unit {
  if (!initialized) {
    throw new Error('Unit registry not initialized. Call await initializeUnitRegistry() first.');
  }
  
  const UnitClass = getUnitClass(params.type);
  
  // AI_TURN.md: Validate all UPPERCASE fields exist
  const requiredFields = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG'];
  for (const field of requiredFields) {
    if (UnitClass[field] === undefined) {
      throw new Error(`Unit class ${params.type} missing required UPPERCASE field: ${field}`);
    }
  }
  
  return {
    id: params.id,
    name: params.name,
    type: params.type,
    player: params.player,
    col: params.col,
    row: params.row,
    color: params.color,
    // AI_TURN.md: UPPERCASE field compliance
    MOVE: UnitClass.MOVE,
    HP_MAX: UnitClass.HP_MAX,
    RNG_RNG: UnitClass.RNG_RNG,
    RNG_DMG: UnitClass.RNG_DMG,
    CC_DMG: UnitClass.CC_DMG,
    CC_RNG: UnitClass.CC_RNG,
    ICON: UnitClass.ICON,
    ICON_SCALE: UnitClass.ICON_SCALE,
    HP_CUR: UnitClass.HP_MAX, // AI_TURN.md: Start at full health
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
    LD: UnitClass.LD,
    OC: UnitClass.OC,
    VALUE: UnitClass.VALUE,
  };
}

export { initializeUnitRegistry };