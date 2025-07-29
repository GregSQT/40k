// frontend/src/data/UnitRegistry.ts
// Loads unit registry from config file

interface UnitRegistryConfig {
  units: Record<string, string>;
}

export async function loadUnitRegistry(): Promise<UnitRegistryConfig> {
  console.log('🔍 loadUnitRegistry() called');
  try {
    // Try to load from config
    console.log('🔍 Attempting to fetch: /config/unit_registry.json');
    const response = await fetch('/config/unit_registry.json');
    console.log('🔍 Response status:', response.status, response.statusText);
    console.log('🔍 Response headers:', Object.fromEntries(response.headers.entries()));
    
    if (!response.ok) {
      console.log('🔍 Response not OK, throwing error');
      throw new Error(`Failed to load unit registry: ${response.status} ${response.statusText}`);
    }
    
    // Debug: log the raw response first
    const text = await response.text();
    console.log('🔍 Raw unit_registry.json response (first 200 chars):', text.substring(0, 200));
    console.log('🔍 Response content-type:', response.headers.get('content-type'));
    
    console.log('🔍 About to parse JSON...');
    const registry: UnitRegistryConfig = JSON.parse(text);
    console.log('🔍 JSON parsed successfully:', registry);
    
    if (!registry.units || typeof registry.units !== 'object') {
      throw new Error('Invalid unit registry format: missing units object');
    }
    
    return registry;
    
  } catch (error) {
    console.error('❌ Failed to load unit registry from config:', error);
    console.error('❌ Error stack:', error instanceof Error ? error.stack : 'No stack trace');
    
    // Fallback to discovered roster structure
    console.log('🔄 Attempting to discover units from roster structure...');
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
    "SpaceMarineMeleeUnit": "spaceMarine/SpaceMarineMeleeUnit",
    "SpaceMarineRangedUnit": "spaceMarine/SpaceMarineRangedUnit",
    "CaptainGravis": "spaceMarine/CaptainGravis",
    
    // Tyranids  
    "Termagant": "tyranid/Termagant",
    "Hormagaunt": "tyranid/Hormagaunt",
    "Carnifex": "tyranid/Carnifex",
    
    // Add more as they become available
    
    
  };
  
  return { units: knownUnits };
}