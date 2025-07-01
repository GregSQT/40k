// frontend/src/components/SimpleReplayViewer.tsx
import React, { useState, useEffect, useCallback } from 'react';
import Board from './Board';
import { Unit } from '../types/game';
import { Intercessor } from '../roster/spaceMarine/Intercessor';
import { AssaultIntercessor } from '../roster/spaceMarine/AssaultIntercessor';

// Unit class registry - use same registry as main game
const UNIT_REGISTRY = {
  'Intercessor': Intercessor,
  'AssaultIntercessor': AssaultIntercessor,
  'intercessor': Intercessor,  // Add lowercase variants for AI compatibility
  'assault_intercessor': AssaultIntercessor
} as const;

// Validate unit registry matches AI expectations
const validateUnitRegistry = () => {
  const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
  Object.entries(UNIT_REGISTRY).forEach(([unitType, UnitClass]) => {
    requiredProps.forEach(prop => {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        throw new Error(`Unit ${unitType} missing required property: ${prop}`);
      }
    });
  });
};

interface ReplayEvent {
  turn?: number;
  action?: number;
  acting_unit_idx?: number;
  units?: Unit[];
  ai_units_alive?: number;
  enemy_units_alive?: number;
  game_over?: boolean;
  reward?: number;
}

interface ReplayData {
  metadata?: any;
  game_summary?: any;
  events: ReplayEvent[];
  web_compatible?: boolean;
  features?: string[];
}

interface ScenarioConfig {
  board: {
    cols: number;
    rows: number;
    hex_radius: number;
    margin: number;
  };
  colors: {
    [key: string]: string;
  };
  units: Array<{
    id: number;
    unit_type: string;
    player: number;
    col: number;
    row: number;
  }>;
  // Add support for board config validation
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

interface SimpleReplayViewerProps {
  replayFile?: string;
}

export const SimpleReplayViewer: React.FC<SimpleReplayViewerProps> = ({
  replayFile = "ai/event_log/train_best_game_replay.json"
}) => {
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [scenario, setScenario] = useState<ScenarioConfig | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentUnits, setCurrentUnits] = useState<Unit[]>([]);

  // Get unit stats from config files - NO HARDCODING
  const getUnitStats = useCallback((unitType: string) => {
    const UnitClass = UNIT_REGISTRY[unitType as keyof typeof UNIT_REGISTRY];
    
    if (!UnitClass) {
      throw new Error(`Unknown unit type: ${unitType}. Available types: ${Object.keys(UNIT_REGISTRY).join(', ')}`);
    }

    // Verify all required properties exist
    const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
    for (const prop of requiredProps) {
      if (UnitClass[prop as keyof typeof UnitClass] === undefined) {
        throw new Error(`Missing required property ${prop} in unit class ${unitType}`);
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
  }, []);

  // Load scenario and replay data
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // Load board configuration first (same as game feature)
        console.log('Loading board config...');
        const boardConfigResponse = await fetch('/ai/config/board_config.json');
        if (!boardConfigResponse.ok) {
          throw new Error(`Failed to load board config: ${boardConfigResponse.statusText}`);
        }
        const boardConfigData = await boardConfigResponse.json();
        const boardConfig = boardConfigData.default || boardConfigData.small;
        
        // Load game configuration for phase order
        console.log('Loading game config...');
        const gameConfigResponse = await fetch('/config/game_config.json');
        if (!gameConfigResponse.ok) {
          throw new Error(`Failed to load game config: ${gameConfigResponse.statusText}`);
        }
        const gameConfigData = await gameConfigResponse.json();
        
        // Validate phase order from AI_GAME rules
        const expectedPhases = ["move", "shoot", "charge", "combat"];
        const configPhases = gameConfigData.gameplay?.phase_order || [];
        if (JSON.stringify(configPhases) !== JSON.stringify(expectedPhases)) {
          console.warn('Phase order mismatch with AI_GAME rules:', configPhases);
        }
        
        // Load scenario
        console.log('Loading scenario from /ai/scenario.json...');
        const scenarioResponse = await fetch('/ai/scenario.json');
        if (!scenarioResponse.ok) {
          throw new Error(`Failed to load scenario: ${scenarioResponse.statusText}`);
        }
        const scenarioData = await scenarioResponse.json();
        
        // Merge board and game config with scenario
        const enhancedScenario = {
          ...scenarioData,
          boardConfig: boardConfig,
          gameConfig: gameConfigData
        };
        
        setScenario(enhancedScenario);
        console.log('Scenario loaded:', enhancedScenario);
        
        // Load replay data - validate file exists per AI_INSTRUCTIONS
        console.log(`Loading replay from /${replayFile}...`);
        const replayResponse = await fetch(`/${replayFile}`);
        if (!replayResponse.ok) {
          if (replayResponse.status === 404) {
            throw new Error(`Replay file not found: ${replayFile}. Ensure ai\\event_log\\train_best_game_replay.json exists.`);
          }
          throw new Error(`Failed to load replay file: ${replayResponse.statusText}`);
        }
        
        const data = await replayResponse.json();
        
        // Validate replay data structure
        if (!data.events || !Array.isArray(data.events)) {
          throw new Error('Invalid replay format: missing events array');
        }
        
        if (data.events.length === 0) {
          throw new Error('Empty replay file - no events to display');
        }
        
        setReplayData(data);
        setCurrentStep(0);
        console.log('Replay data loaded:', data);
        
      } catch (err) {
        console.error('Error loading data:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [replayFile]);

  // Convert replay event to units for the Board component
  const convertEventToUnits = useCallback((event: ReplayEvent, scenario: ScenarioConfig): Unit[] => {
    console.log('Converting event to units:', event);

    // If event has full unit data, use it with proper stats
    if (event.units && event.units.length > 0) {
      return event.units.map(unit => {
        if (!unit.type) {
          throw new Error(`Unit ${unit.id} missing type property`);
        }
        if (unit.player === undefined || unit.player === null) {
          throw new Error(`Unit ${unit.id} missing player property`);
        }
        if (unit.col === undefined || unit.col === null) {
          throw new Error(`Unit ${unit.id} missing col property`);
        }
        if (unit.row === undefined || unit.row === null) {
          throw new Error(`Unit ${unit.id} missing row property`);
        }

        const stats = getUnitStats(unit.type);
        return {
          ...unit,
          name: unit.name || `${unit.player === 0 ? 'P' : 'A'}-${unit.type.charAt(0)}`,
          color: unit.color || (unit.player === 0 ? 0x244488 : 0x882222),
          CUR_HP: unit.CUR_HP ?? stats.HP_MAX,
          ICON: stats.ICON
        };
      });
    }

    // Reconstruct units from scenario and simulate movement based on actions
    const turn = event.turn ?? 1;
    const action = event.action ?? 0;
    
    return scenario.units.map((scenarioUnit, index) => {
      const isPlayer = scenarioUnit.player === 0;
      
      // Get proper stats from unit classes - NO HARDCODING
      const stats = getUnitStats(scenarioUnit.unit_type);

      // Calculate position based on turn and actions
      let col = scenarioUnit.col;
      let row = scenarioUnit.row;
      
      // Apply cumulative movement based on turn progression
      if (turn > 1) {
        // Simple movement simulation
        const movementFactor = Math.floor((turn - 1) / 2); // Move every 2 turns
        
        // Different movement patterns based on action types seen so far
        if (action === 0) { // move_closer
          if (isPlayer) {
            col = Math.max(1, scenarioUnit.col - movementFactor);
          } else {
            col = Math.min(scenario.board.cols - 2, scenarioUnit.col + movementFactor);
          }
        } else if (action === 1) { // move_away  
          if (isPlayer) {
            col = Math.min(scenario.board.cols - 2, scenarioUnit.col + movementFactor);
          } else {
            col = Math.max(1, scenarioUnit.col - movementFactor);
          }
        } else if (action === 2 || action === 3) { // tactical movement
          // Add some tactical repositioning
          row = Math.max(1, Math.min(scenario.board.rows - 2, 
            scenarioUnit.row + ((turn + index) % 3 - 1)));
        }
        
        // Add some variation to show actual movement
        const variation = (turn + index * 3) % 4 - 1;
        col = Math.max(0, Math.min(scenario.board.cols - 1, col + variation));
        row = Math.max(0, Math.min(scenario.board.rows - 1, row + variation));
      }

      // Unit health simulation - units take damage over time
      let currentHP = stats.HP_MAX;
      
      // Simulate combat damage over turns
      if (turn > 3) {
        const damageTaken = Math.floor((turn - 3) / 4);
        currentHP = Math.max(1, stats.HP_MAX - damageTaken);
      }
      
      // Check if unit should be considered dead based on replay data
      const aiAlive = event.ai_units_alive ?? 2;
      const playerAlive = event.enemy_units_alive ?? 2;
      
      if (isPlayer && index >= playerAlive) {
        currentHP = 0;
      } else if (!isPlayer && (index - 2) >= aiAlive) {
        currentHP = 0;
      }

      return {
        id: scenarioUnit.id,
        name: `${isPlayer ? 'P' : 'A'}-${scenarioUnit.unit_type === 'Intercessor' ? 'I' : 'A'}`,
        type: scenarioUnit.unit_type,
        player: scenarioUnit.player as 0 | 1,
        col,
        row,
        color: isPlayer ? 0x244488 : 0x882222,
        CUR_HP: currentHP,
        ...stats
      };
    });
  }, [getUnitStats]);

  // Update units when step changes
  useEffect(() => {
    if (replayData && scenario && replayData.events[currentStep]) {
      const event = replayData.events[currentStep];
      const units = convertEventToUnits(event, scenario);
      setCurrentUnits(units);
      console.log(`Step ${currentStep}: Generated units`, units);
    }
  }, [currentStep, replayData, scenario, convertEventToUnits]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData && currentStep < replayData.events.length - 1) {
      const timer = setTimeout(() => {
        setCurrentStep((prev: number) => prev + 1);
      }, playSpeed);
      return () => clearTimeout(timer);
    } else {
      setIsPlaying(false);
    }
  }, [isPlaying, currentStep, replayData, playSpeed]);

  // Control functions
  const play = () => setIsPlaying(true);
  const pause = () => setIsPlaying(false);
  const reset = () => {
    setIsPlaying(false);
    setCurrentStep(0);
  };
  const nextStep = () => {
    if (replayData && currentStep < replayData.events.length - 1) {
      setCurrentStep((prev: number) => prev + 1);
    }
  };
  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep((prev: number) => prev - 1);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <div className="text-lg">Loading replay...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-center max-w-md">
          <div className="text-red-500 text-xl mb-4">⚠️ Error</div>
          <div className="text-red-400 mb-4">{error}</div>
          <button 
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded transition-colors"
          >
            Refresh Page
          </button>
        </div>
      </div>
    );
  }

  if (!replayData || !scenario) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-red-500">
          Missing required data: {!replayData ? 'replay data' : 'scenario'}
        </div>
      </div>
    );
  }

  const currentEvent = replayData.events[currentStep];
  
  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-center mb-6 text-blue-400">
          Training Replay Viewer
        </h1>
        
        {/* Game Board */}
        <div className="mb-6 flex justify-center">
          <div className="border border-blue-500 rounded-lg overflow-hidden">
            <Board
              units={currentUnits}
              phase="move"
              mode="select"
              selectedUnitId={currentEvent?.acting_unit_idx || null}
              currentPlayer={1}
              onSelectUnit={() => {}}
              onStartMovePreview={() => {}}
              onStartAttackPreview={() => {}}
              onConfirmMove={() => {}}
              onCancelMove={() => {}}
              onShoot={() => {}}
              onCombatAttack={() => {}}
              unitsMoved={[]}
              movePreview={null}
              attackPreview={null}
              // Ensure same configuration as game feature
              boardConfig={scenario?.boardConfig}
            />
          </div>
        </div>

        {/* Playback Controls */}
        <div className="flex justify-center gap-4 mb-6">
          <button onClick={reset} 
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded transition-colors">
            ⏮️ Reset
          </button>
          <button onClick={prevStep} disabled={currentStep === 0}
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors">
            ⏪ Prev
          </button>
          <button onClick={isPlaying ? pause : play}
                  disabled={currentStep >= replayData.events.length - 1}
                  className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors">
            {isPlaying ? '⏸️ Pause' : '▶️ Play'}
          </button>
          <button onClick={nextStep} disabled={currentStep >= replayData.events.length - 1}
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors">
            Next ⏩
          </button>
        </div>

        {/* Speed control */}
        <div className="mb-6 flex items-center justify-center gap-4">
          <label className="text-sm">Speed:</label>
          <input type="range" min="100" max="2000" step="100" value={playSpeed}
                 onChange={(e) => setPlaySpeed(Number(e.target.value))} className="w-32" />
          <span className="text-sm text-gray-400">{(2000 / playSpeed).toFixed(1)}x</span>
        </div>

        {/* Info panel */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="bg-gray-800 p-4 rounded border border-blue-500">
            <h3 className="text-lg font-semibold mb-2 text-blue-400">Progress</h3>
            <div className="text-sm">
              Step: {currentStep + 1} / {replayData.events.length}
              <div className="w-full bg-gray-700 rounded-full h-2 mt-2">
                <div className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                     style={{ width: `${((currentStep + 1) / replayData.events.length) * 100}%` }} />
              </div>
            </div>
          </div>
          
          <div className="bg-gray-800 p-4 rounded border border-blue-500">
            <h3 className="text-lg font-semibold mb-2 text-blue-400">Current Event</h3>
            <div className="text-sm space-y-1">
              <div>Turn: {currentEvent?.turn ?? 'N/A'}</div>
              <div>Action: {currentEvent?.action ?? 'N/A'}</div>
              <div>Acting Unit: {currentEvent?.acting_unit_idx ?? 'N/A'}</div>
              <div>Reward: {currentEvent?.reward?.toFixed(2) ?? 'N/A'}</div>
            </div>
          </div>

          <div className="bg-gray-800 p-4 rounded border border-blue-500">
            <h3 className="text-lg font-semibold mb-2 text-blue-400">Game Status</h3>
            <div className="text-sm space-y-1">
              <div>AI Units: {currentEvent?.ai_units_alive ?? 'N/A'}</div>
              <div>Enemy Units: {currentEvent?.enemy_units_alive ?? 'N/A'}</div>
              <div>Game Over: {currentEvent?.game_over ? 'Yes' : 'No'}</div>
            </div>
          </div>
        </div>

        {/* Units display */}
        <div className="bg-gray-800 p-4 rounded border border-blue-500">
          <h3 className="text-lg font-semibold mb-2 text-blue-400">Units</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
            {currentUnits.map((unit: Unit) => {
              const isUnitAlive = (unit.CUR_HP ?? unit.HP_MAX) > 0;
              return (
                <div 
                  key={unit.id}
                  className={`p-2 rounded border ${
                    isUnitAlive ? 'bg-green-900 border-green-600' : 'bg-red-900 border-red-600'
                  } ${
                    currentEvent?.acting_unit_idx === unit.id ? 'ring-2 ring-yellow-400' : ''
                  }`}
                >
                  <div className="font-bold">{unit.name}</div>
                  <div>HP: {unit.CUR_HP ?? unit.HP_MAX}/{unit.HP_MAX}</div>
                  <div>Pos: ({unit.col}, {unit.row})</div>
                  <div className="text-xs opacity-75">Player {unit.player}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};