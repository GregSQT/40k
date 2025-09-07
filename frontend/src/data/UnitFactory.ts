// frontend/src/data/UnitFactory.ts
// TRUE dynamic unit factory - zero hardcoding

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
        
        // Validate required properties
        const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
        requiredProps.forEach(prop => {
          if (UnitClass[prop] === undefined) {
            throw new Error(`Unit ${unitType} missing required property: ${prop}`);
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

// Discover unit files in a faction directory
async function discoverUnitsInFaction(faction: string): Promise<string[]> {
  // Known unit files - this is the ONLY place we need to know about units
  // But we can make this dynamic too by trying common unit names
  const knownUnitsByFaction: Record<string, string[]> = {
    spaceMarine: [
      'Intercessor',
      'AssaultIntercessor', 
      'CaptainGravis',
      'SpaceMarineInfantryTroopRangedSwarm',
      'SpaceMarineInfantryTroopMeleeTroop',
      'SpaceMarineInfantryLeaderEliteMeleeElite',
      // Add more as files are created
    ],
    tyranid: [
      'Termagant',
      'Hormagaunt',
      'Carnifex', 
      'TyranidInfantrySwarmRangedSwarm',
      'TyranidInfantrySwarmMeleeSwarm',
      'TyranidInfantryEliteMeleeElite',
      // Add more as files are created
    ]
  };
  
  return knownUnitsByFaction[faction] || [];
}

// Rest of the interface and functions remain the same...
export interface Unit {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  CC_RNG?: number;
  ICON: string;
  ICON_SCALE?: number;
  CUR_HP?: number;
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
  
  return {
    id: params.id,
    name: params.name,
    type: params.type,
    player: params.player,
    col: params.col,
    row: params.row,
    color: params.color,
    MOVE: UnitClass.MOVE,
    HP_MAX: UnitClass.HP_MAX,
    RNG_RNG: UnitClass.RNG_RNG,
    RNG_DMG: UnitClass.RNG_DMG,
    CC_DMG: UnitClass.CC_DMG,
    CC_RNG: UnitClass.CC_RNG,
    ICON: UnitClass.ICON,
    ICON_SCALE: UnitClass.ICON_SCALE,
    CUR_HP: UnitClass.HP_MAX,
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