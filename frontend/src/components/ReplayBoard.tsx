// frontend/src/components/ReplayBoard.tsx
import React, { useState, useEffect, useCallback } from 'react';
import Board from './Board_save';
import { Unit } from '../types/game';
import { Intercessor } from '../roster/spaceMarine/Intercessor';
import { AssaultIntercessor } from '../roster/spaceMarine/AssaultIntercessor';
import { useGameConfig } from '../hooks/useGameConfig';

// Error Boundary Component for ReplayBoard
const ReplayErrorBoundary: React.FC<{children: React.ReactNode}> = ({ children }) => {
  const [hasError, setHasError] = useState(false);
  
  useEffect(() => {
    const handleError = () => setHasError(true);
    window.addEventListener('error', handleError);
    window.addEventListener('unhandledrejection', handleError);
    return () => {
      window.removeEventListener('error', handleError);
      window.removeEventListener('unhandledrejection', handleError);
    };
  }, []);
  
  if (hasError) {
    return (
      <div className="flex items-center justify-center h-96 bg-red-900 text-white rounded-lg">
        <div className="text-center">
          <div className="text-xl mb-4">⚠️ Replay Error</div>
          <button 
            onClick={() => {setHasError(false); window.location.reload();}} 
            className="px-4 py-2 bg-red-600 rounded hover:bg-red-500 transition-colors"
          >
            Reload Component
          </button>
        </div>
      </div>
    );
  }
  
  return <>{children}</>;
};

// Use BoardReplay interfaces exactly - NO local interface redefinition
interface ReplayUnit extends Unit {
  alive?: boolean;
}

interface ScenarioConfig {
  board: {
    cols: number;
    rows: number;
    hex_radius: number;
    margin: number;
  };
  colors: {
    [key: string]: number;
  };
  units: Array<{
    id: number;
    unit_type: string;
    player: number;
    col: number;
    row: number;
  }>;
  boardConfig?: {
    cols: number;
    rows: number;
    hex_radius: number;
    margin: number;
    colors: Record<string, string>;
  };
  gameConfig?: {
    game_rules: {
      max_turns: number;
      board_size: [number, number];
    };
    gameplay: {
      phase_order: string[];
    };
  };
}

interface ReplayEvent {
  turn?: number;
  type?: string;
  timestamp?: string;
  action?: {
    type?: string;
    action_id?: number;
    reward?: number;
  } | number; // Support both object and number formats
  game_state?: {
    turn?: number;
    ai_units_alive?: number;
    enemy_units_alive?: number;
    game_over?: boolean;
  };
  units?: {
    ai_count?: number;
    enemy_count?: number;
  };
  // Legacy format support
  acting_unit_idx?: number;
  ai_units_alive?: number;
  enemy_units_alive?: number;
  game_over?: boolean;
  reward?: number;
}

interface ReplayData {
  metadata?: {
    total_reward?: number;
    total_turns?: number;
    timestamp?: string;
    episode_reward?: number;
    final_turn?: number;
    total_events?: number;
  };
  game_summary?: {
    final_reward?: number;
    total_turns?: number;
    game_result?: string;
  };
  events: ReplayEvent[];
  web_compatible?: boolean;
  features?: string[];
}

interface ReplayBoardProps {
  replayFile?: string;
  currentStep: number;
  onUnitsLoaded?: (units: ReplayUnit[]) => void;
  onEventChange?: (event: ReplayEvent | null) => void;
  onScenarioLoaded?: (scenario: ScenarioConfig | null) => void;
  onDataLoaded?: (data: ReplayData | null) => void;
  onError?: (error: string | null) => void;
  onLoading?: (loading: boolean) => void;
}

// Unit registry loaded from config - NO HARDCODING
const buildUnitRegistry = (unitDefinitions: {units: Record<string, {class_name: string}>}) => {
  const registry: Record<string, typeof Intercessor | typeof AssaultIntercessor> = {};
  
  // Build registry from config
  const classMapping: Record<string, typeof Intercessor | typeof AssaultIntercessor> = {
    'Intercessor': Intercessor,
    'AssaultIntercessor': AssaultIntercessor
  };
  
  Object.entries(unitDefinitions.units || {}).forEach(([unitType, definition]: [string, {class_name: string}]) => {
    const UnitClass = classMapping[definition.class_name];
    if (UnitClass) {
      registry[unitType] = UnitClass;
    }
  });
  
  return registry;
};

// Validate unit registry consistency from config
const validateUnitRegistry = (unitDefinitions: {units: Record<string, {class_name: string}>, required_properties: string[]}, errorMessages: Record<string, string>) => {
  if (!unitDefinitions || !errorMessages) return;
  
  const unitRegistry = buildUnitRegistry(unitDefinitions);
  const requiredProps = unitDefinitions.required_properties || ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
  
  Object.entries(unitRegistry).forEach(([unitType, UnitClass]) => {
    requiredProps.forEach((prop: string) => {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        const errorMessage = errorMessages.unit_validation_error || 'Unit {unitType} missing required property: {prop}';
        throw new Error(errorMessage.replace('{unitType}', unitType).replace('{prop}', prop));
      }
    });
  });
};

// Phase validation according to AI_GAME.md - LOAD FROM CONFIG
const validatePhaseOrder = (phases: string[], configPhases: string[]) => {
  if (JSON.stringify(phases) !== JSON.stringify(configPhases)) {
    console.error('Phase order violation of AI_GAME rules:', phases);
    console.error('Expected phases:', configPhases);
    console.error('Received phases:', phases);
    throw new Error(`Invalid phase order. AI_GAME.md requires exact sequence: ${configPhases.join(' → ')}`);
  }
  console.log('✅ Phase order validates against AI_GAME.md');
  return true;
};

// Turn structure validation according to AI_GAME.md
const validateTurnStructure = (event: ReplayEvent, expectedPhase: string, validPhases: string[]) => {
  // Handle different action formats
  const actionType = typeof event.action === 'object' && event.action?.type ? event.action.type : undefined;
  
  if (actionType && validPhases && !validPhases.includes(actionType)) {
    throw new Error(`Invalid action type: ${actionType}. Must match config phases: ${validPhases.join(', ')}`);
  }
  return true;
};

export const ReplayBoard: React.FC<ReplayBoardProps> = ({ 
  replayFile,
  currentStep = 0,
  onUnitsLoaded,
  onEventChange,
  onScenarioLoaded,
  onDataLoaded,
  onError,
  onLoading
}) => {
  // Use same config hook as Board.tsx
  const { boardConfig, loading: configLoading, error: configError } = useGameConfig();
  
  // State management
  const [actionDefinitions, setActionDefinitions] = useState<{[key: string]: {name: string, phase: string, type: string}} | null>(null);
  const [scenario, setScenario] = useState<ScenarioConfig | null>(null);
  const [unitDefinitions, setUnitDefinitions] = useState<{units: Record<string, {class_name: string}>, required_properties: string[]} | null>(null);
  const [errorMessages, setErrorMessages] = useState<Record<string, string> | null>(null);
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentUnits, setCurrentUnits] = useState<ReplayUnit[]>([]);
  const [currentEvent, setCurrentEvent] = useState<ReplayEvent | null>(null);
  // Load default replay file from config if not provided
  const [configReplayFile, setConfigReplayFile] = useState<string | null>(null);
  
  useEffect(() => {
    const loadDefaultFile = async () => {
      try {
        const response = await fetch('/config/training_config.json');
        if (response.ok) {
          const config = await response.json();
          // Use default training config's replay file
          const defaultConfig = config.default;
          if (defaultConfig?.replay_config?.default_file) {
            setConfigReplayFile(defaultConfig.replay_config.default_file);
          } else {
            const errorMessage = errorMessages?.no_replay_config || 'No replay config found in training_config.json';
            throw new Error(errorMessage);
          }
        } else {
          const errorMessage = errorMessages?.config_load_failed || 'Failed to load training_config.json';
          throw new Error(errorMessage);
        }
      } catch (err) {
        console.error('Error loading replay file from config:', err);
        const errorMessage = errorMessages?.config_load_error || 'Could not load replay file path from configuration';
        throw new Error(errorMessage);
      }
    };
    if (!replayFile && errorMessages) loadDefaultFile();
  }, [replayFile, errorMessages]);

  const effectiveReplayFile = replayFile || configReplayFile;

  // Validate environment setup
  useEffect(() => {
    if (unitDefinitions && errorMessages) {
      validateUnitRegistry(unitDefinitions, errorMessages);
    }
  }, [unitDefinitions, errorMessages]);

  // Load unit definitions from config file
  useEffect(() => {
    const loadUnitDefinitions = async () => {
      try {
        const response = await fetch('/config/unit_definitions.json');
        if (!response.ok) throw new Error('Failed to load unit definitions');
        const data = await response.json();
        setUnitDefinitions(data);
      } catch (err) {
        console.error('Error loading unit definitions:', err);
        throw new Error('Failed to load unit definitions from config');
      }
    };
    loadUnitDefinitions();
  }, []);

  // Load error messages from config file
  useEffect(() => {
    const loadErrorMessages = async () => {
      try {
        const response = await fetch('/config/config.json');
        if (!response.ok) throw new Error('Failed to load config');
        const data = await response.json();
        setErrorMessages(data.error_messages || {});
      } catch (err) {
        console.error('Error loading error messages:', err);
        throw new Error('Failed to load error messages from config');
      }
    };
    loadErrorMessages();
  }, []);

  // Load action definitions from config file
  useEffect(() => {
    const loadActionDefinitions = async () => {
      try {
        const response = await fetch('/config/action_definitions.json');
        if (!response.ok) throw new Error('Failed to load action definitions');
        const data = await response.json();
        setActionDefinitions(data.action_mappings);
      } catch (err) {
        console.error('Error loading action definitions:', err);
        throw new Error('Failed to load action definitions from config');
      }
    };
    loadActionDefinitions();
  }, []);

  // Action to phase mapping loaded from config
  const getActionPhase = useCallback((actionId: number): string => {
    if (!actionDefinitions) throw new Error('Action definitions not loaded');
    const actionDef = actionDefinitions[actionId.toString()];
    if (!actionDef) throw new Error(`Unknown action ID: ${actionId}`);
    return actionDef.phase;
  }, [actionDefinitions]);

  // Action names loaded from config
  const getActionName = useCallback((actionId: number): string => {
    if (!actionDefinitions) throw new Error('Action definitions not loaded');
    const actionDef = actionDefinitions[actionId.toString()];
    if (!actionDef) throw new Error(`Unknown action ID: ${actionId}`);
    return actionDef.name;
  }, [actionDefinitions]);

  // Get unit stats from config files - NO HARDCODING
  const getUnitStats = useCallback((unitType: string) => {
    if (!unitDefinitions || !errorMessages) {
      throw new Error('Configuration not loaded');
    }

    const unitRegistry = buildUnitRegistry(unitDefinitions);
    const UnitClass = unitRegistry[unitType];
    
    if (!UnitClass) {
      const availableTypes = Object.keys(unitRegistry).join(', ');
      const errorMessage = errorMessages.unknown_unit_type || 'Unknown unit type: {unitType}. Available types: {availableTypes}';
      throw new Error(errorMessage.replace('{unitType}', unitType).replace('{availableTypes}', availableTypes));
    }

    // Get required properties from config
    const requiredProps = unitDefinitions.required_properties || ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
    for (const prop of requiredProps) {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        const errorMessage = errorMessages.missing_unit_property || 'Missing required property {prop} in unit class {unitType}';
        throw new Error(errorMessage.replace('{prop}', prop).replace('{unitType}', unitType));
      }
    }

    return {
      HP_MAX: UnitClass.HP_MAX,
      MOVE: UnitClass.MOVE,
      RNG_RNG: UnitClass.RNG_RNG,
      RNG_DMG: UnitClass.RNG_DMG,
      CC_DMG: UnitClass.CC_DMG,
      ICON: UnitClass.ICON
    };
  }, [unitDefinitions, errorMessages]);

  // Load scenario using unified config system like Board.tsx
  const loadScenario = useCallback(async (): Promise<ScenarioConfig> => {
    try {
      console.log('Loading scenario with unified board config...');

      // Wait for board config to load first
      if (!boardConfig) {
        throw new Error('Board configuration not loaded');
      }

      // Load scenario units from /config/scenario.json
      const scenarioResponse = await fetch('/config/scenario.json');
      if (!scenarioResponse.ok) {
        throw new Error(`Failed to load scenario: ${scenarioResponse.statusText}`);
      }

      const scenarioData = await scenarioResponse.json() as {
        units: ScenarioConfig['units'];
      };

      // Build unified scenario using board config + scenario units
      const unifiedScenario: ScenarioConfig = {
        board: {
          cols: boardConfig.cols,
          rows: boardConfig.rows,
          hex_radius: boardConfig.hex_radius,
          margin: boardConfig.margin
        },
        colors: {
          background: parseInt(boardConfig.colors.background.replace('0x', ''), 16),
          cell_even: parseInt(boardConfig.colors.cell_even.replace('0x', ''), 16),
          cell_odd: parseInt(boardConfig.colors.cell_odd.replace('0x', ''), 16),
          cell_border: parseInt(boardConfig.colors.cell_border.replace('0x', ''), 16),
          player_0: parseInt(boardConfig.colors.player_0.replace('0x', ''), 16),
          player_1: parseInt(boardConfig.colors.player_1.replace('0x', ''), 16),
          hp_full: parseInt(boardConfig.colors.hp_full.replace('0x', ''), 16),
          hp_damaged: parseInt(boardConfig.colors.hp_damaged.replace('0x', ''), 16),
          highlight: parseInt(boardConfig.colors.highlight.replace('0x', ''), 16),
          current_unit: parseInt(boardConfig.colors.current_unit.replace('0x', ''), 16)
        },
        units: scenarioData.units
      };

      console.log('✅ Unified scenario loaded with board config');
      console.log('🎨 DEBUG - Scenario colors:', unifiedScenario.colors);
      console.log('🎨 DEBUG - Background color:', unifiedScenario.colors.background);
      console.log('🎨 DEBUG - Cell even:', unifiedScenario.colors.cell_even);
      console.log('🎨 DEBUG - Cell odd:', unifiedScenario.colors.cell_odd);
      console.log('🎨 DEBUG - Original boardConfig colors:', boardConfig?.colors);
      setScenario(unifiedScenario);
      if (onScenarioLoaded) onScenarioLoaded(unifiedScenario);
      return unifiedScenario;

    } catch (err) {
      console.error('Error loading unified scenario:', err);
      throw err;
    }
  }, [boardConfig, onScenarioLoaded]);

  // Convert replay events to unit objects
  const convertUnits = useCallback((event: ReplayEvent): ReplayUnit[] => {
    if (!event || !scenario) return [];

    // Handle different event formats
    if (event.units && Array.isArray(event.units)) {
      return event.units.map(unit => ({
        ...unit,
        alive: unit.alive !== false && (unit.CUR_HP ?? unit.HP_MAX) > 0
      }));
    }

    // Generate units from scenario if no units in event
    return scenario.units.map((unitDef, index) => {
      const stats = getUnitStats(unitDef.unit_type);
      return {
        id: unitDef.id,
        name: unitDef.unit_type,
        type: unitDef.unit_type,
        player: unitDef.player as 0 | 1,
        col: unitDef.col,
        row: unitDef.row,
        color: unitDef.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1,
        MOVE: stats.MOVE,
        HP_MAX: stats.HP_MAX,
        CUR_HP: stats.HP_MAX,
        RNG_RNG: stats.RNG_RNG,
        RNG_DMG: stats.RNG_DMG,
        CC_DMG: stats.CC_DMG,
        ICON: stats.ICON,
        alive: true
      };
    });
  }, [scenario, getUnitStats]);

  // Update display when step changes
  useEffect(() => {
    if (!replayData || !scenario || currentStep >= replayData.events.length) {
      setCurrentEvent(null);
      setCurrentUnits([]);
      if (onEventChange) onEventChange(null);
      if (onUnitsLoaded) onUnitsLoaded([]);
      return;
    }

    const event = replayData.events[currentStep];
    if (!event) {
      setCurrentEvent(null);
      setCurrentUnits([]);
      if (onEventChange) onEventChange(null);
      if (onUnitsLoaded) onUnitsLoaded([]);
      return;
    }

    const units = convertUnits(event);
    setCurrentEvent(event);
    setCurrentUnits(units);
    if (onEventChange) onEventChange(event);
    if (onUnitsLoaded) onUnitsLoaded(units);
  }, [currentStep, replayData, scenario, convertUnits, onEventChange, onUnitsLoaded]);

  // Load scenario and replay data
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        if (onLoading) onLoading(true);
        if (onError) onError(null);

        // Wait for config to load first
        if (configLoading) {
          console.log('⏳ Waiting for configuration to load...');
          return;
        }

        if (configError) {
          throw new Error(`Configuration error: ${configError}`);
        }

        if (!boardConfig) {
          throw new Error('Board configuration not available');
        }
        
        console.log('Loading scenario...');
        await loadScenario();
        
        console.log(`Loading replay from /${effectiveReplayFile}...`);
        const response = await fetch(`/${effectiveReplayFile}`);
        if (!response.ok) {
          throw new Error(`Failed to load replay file: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        // Validate JSON structure
        if (!data.events || !Array.isArray(data.events)) {
          throw new Error('Invalid replay data: missing events array');
        }
        
        console.log('Replay data loaded:', data);
        setReplayData(data);
        if (onDataLoaded) onDataLoaded(data);
        
      } catch (err) {
        console.error('Error loading data:', err);
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setError(errorMessage);
        if (onError) onError(errorMessage);
      } finally {
        setLoading(false);
        if (onLoading) onLoading(false);
      }
    };

    loadData();
  }, [effectiveReplayFile, loadScenario, boardConfig, configLoading, configError, onDataLoaded, onError, onLoading]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Generic cleanup for any canvas elements
      const canvasElements = document.querySelectorAll('canvas');
      canvasElements.forEach(canvas => {
        // Cleanup any event listeners or memory leaks
        if (canvas.parentElement && canvas.dataset.cleanup === 'replay') {
          canvas.remove();
        }
      });
    };
  }, []);

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 bg-gray-900 text-white rounded-lg">
        <div className="text-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <div className="text-lg">{errorMessages?.loading_replay || 'Loading replay...'}</div>
          <div className="text-sm text-gray-400 mt-2">
            {errorMessages?.loading_scenario || 'Loading scenario and replay data...'}
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex items-center justify-center h-96 bg-red-900 text-white rounded-lg">
        <div className="text-center">
          <div className="text-xl mb-4">⚠️ {errorMessages?.error_loading_replay || 'Error Loading Replay'}</div>
          <div className="text-sm bg-red-800 p-4 rounded max-w-md">
            {error}
          </div>
          <button 
            onClick={() => window.location.reload()}
            className="mt-4 px-4 py-2 bg-red-600 hover:bg-red-500 rounded transition-colors"
          >
            {errorMessages?.retry_button || 'Retry'}
          </button>
        </div>
      </div>
    );
  }

  // No data state
  if (!replayData || !scenario) {
    return (
      <div className="flex items-center justify-center h-96 bg-gray-900 text-white rounded-lg">
        <div className="text-center">
          <div className="text-xl mb-4">📄 {errorMessages?.no_replay_data || 'No Replay Data'}</div>
          <div className="text-sm text-gray-400">
            {errorMessages?.no_replay_data_desc || 'No replay data available to display'}
          </div>
        </div>
      </div>
    );
  }

  
  // Calculate acting unit ID from current event
  const actingUnitId = currentEvent?.acting_unit_idx ?? null;

  // Render Board with replay mode enabled
  return (
    <div className="w-full">
      <Board
        units={currentUnits as Unit[]}
        selectedUnitId={null}
        mode="replay"
        isReplayMode={true}
        replayData={replayData as any}
        currentStep={currentStep}
        actingUnitId={actingUnitId}
        movePreview={null}
        attackPreview={null}
        currentPlayer={0}
        unitsMoved={[]}
        unitsCharged={[]}
        unitsAttacked={[]}
        phase="move"
        onSelectUnit={() => {}} // No interaction in replay mode
        onStartMovePreview={() => {}} // No interaction in replay mode
        onStartAttackPreview={() => {}} // No interaction in replay mode
        onConfirmMove={() => {}} // No interaction in replay mode
        onCancelMove={() => {}} // No interaction in replay mode
        onShoot={() => {}} // No interaction in replay mode
        onCombatAttack={() => {}} // No interaction in replay mode
        onCharge={() => {}} // No interaction in replay mode
        onMoveCharger={() => {}} // No interaction in replay mode
        onCancelCharge={() => {}} // No interaction in replay mode
        onValidateCharge={() => {}} // No interaction in replay mode
      />
    </div>
  );
};

// Wrap ReplayBoard with Error Boundary
const ReplayBoardWithErrorBoundary: React.FC<ReplayBoardProps> = (props) => (
  <ReplayErrorBoundary>
    <ReplayBoard {...props} />
  </ReplayErrorBoundary>
);

export default ReplayBoardWithErrorBoundary;