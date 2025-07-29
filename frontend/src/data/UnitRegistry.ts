// frontend/src/data/UnitRegistry.ts
// Loads unit registry from config file

interface UnitRegistryConfig {
  units: Record<string, string>;
}

export async function loadUnitRegistry(): Promise<UnitRegistryConfig> {
  try {
    // Try to load from config
    const response = await fetch('/config/unit_registry.json');
    
    if (!response.ok) {
      throw new Error(`Failed to load unit registry: ${response.status} ${response.statusText}`);
    }
    
    // Debug: log the raw response first
    const text = await response.text();
    const registry: UnitRegistryConfig = JSON.parse(text);
    
    if (!registry.units || typeof registry.units !== 'object') {
      throw new Error('Invalid unit registry format: missing units object');
    }
    
    return registry;
    
  } catch (error) {
    console.error('❌ Failed to load unit registry from config:', error);
    console.error('❌ Error stack:', error instanceof Error ? error.stack : 'No stack trace');
    
    // Fallback to discovered roster structure
    return discoverUnitsFromRoster();
  }
}

// Fallback: discover units from known roster structure
async function discoverUnitsFromRoster(): Promise<UnitRegistryConfig> {
  // Define known roster structure based on your existing files
  const knownUnits = {
    // Space Marines
    "Intercessor": "spaceMarine/Intercessor",
    "AssaultIntercessor": "spaceMarine/AssaultIntercessor", 
    "CaptainGravis": "spaceMarine/CaptainGravis",
    
    // Tyranids  
    "Termagant": "tyranid/Termagant",
    "Hormagaunt": "tyranid/Hormagaunt",
    "Carnifex": "tyranid/Carnifex",
    
    // Add more as they become available
  };
  
  return { units: knownUnits };
}