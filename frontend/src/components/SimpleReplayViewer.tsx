// frontend/src/components/SimpleReplayViewer.tsx
import React, { useState, useEffect, useCallback } from 'react';
import Board from './Board';
import { Unit } from '../types/game';

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

  // Load scenario and replay data
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // Load scenario
        console.log('Loading scenario from /ai/scenario.json...');
        const scenarioResponse = await fetch('/ai/scenario.json');
        if (!scenarioResponse.ok) {
          throw new Error(`Failed to load scenario: ${scenarioResponse.statusText}`);
        }
        const scenarioData = await scenarioResponse.json();
        setScenario(scenarioData);
        console.log('Scenario loaded:', scenarioData);
        
        // Load replay data
        console.log(`Loading replay from /${replayFile}...`);
        const replayResponse = await fetch(`/${replayFile}`);
        if (!replayResponse.ok) {
          throw new Error(`Failed to load replay file: ${replayResponse.statusText}`);
        }
        const data = await replayResponse.json();
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

    // If event has full unit data, use it
    if (event.units && event.units.length > 0) {
      return event.units.map(unit => ({
        ...unit,
        id: unit.id,
        name: unit.name || `${unit.player === 0 ? 'P' : 'A'}-${unit.type?.charAt(0) || 'U'}`,
        color: unit.color || (unit.player === 0 ? 0x244488 : 0x882222),
        CUR_HP: unit.CUR_HP ?? unit.HP_MAX ?? 3,
        alive: (unit.CUR_HP ?? unit.HP_MAX ?? 3) > 0
      }));
    }

    // Otherwise reconstruct from scenario + event counts
    const aiAlive = event.ai_units_alive ?? 2;
    const playerAlive = event.enemy_units_alive ?? 2;
    
    return scenario.units.map((scenarioUnit, index) => {
      const isPlayer = scenarioUnit.player === 0;
      const isAlive = isPlayer ? 
        (index < playerAlive + 2) : 
        ((index - 2) < aiAlive);

      // Default stats based on unit type
      const isIntercessor = scenarioUnit.unit_type === 'Intercessor';
      const stats = {
        MOVE: isIntercessor ? 4 : 6,
        HP_MAX: isIntercessor ? 3 : 4,
        RNG_RNG: isIntercessor ? 8 : 4,
        RNG_DMG: isIntercessor ? 2 : 1,
        CC_DMG: isIntercessor ? 1 : 2,
        ICON: isIntercessor ? '/icons/Intercessor.webp' : '/icons/AssaultIntercessor.webp'
      };

      return {
        id: scenarioUnit.id,
        name: `${isPlayer ? 'P' : 'A'}-${isIntercessor ? 'I' : 'A'}`,
        type: scenarioUnit.unit_type,
        player: scenarioUnit.player as 0 | 1,
        col: scenarioUnit.col,
        row: scenarioUnit.row,
        color: isPlayer ? 0x244488 : 0x882222,
        CUR_HP: isAlive ? stats.HP_MAX : 0,
        alive: isAlive,
        ...stats
      };
    });
  }, []);

  // Update units when step changes
  useEffect(() => {
    if (replayData && scenario && replayData.events[currentStep]) {
      const event = replayData.events[currentStep];
      const units = convertEventToUnits(event, scenario);
      setCurrentUnits(units);
    }
  }, [currentStep, replayData, scenario, convertEventToUnits]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData && currentStep < replayData.events.length - 1) {
      const timer = setTimeout(() => {
        setCurrentStep(prev => prev + 1);
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
      setCurrentStep(prev => prev + 1);
    }
  };
  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep(prev => prev - 1);
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
          Missing required data: {!replayData ? 'replay data' : ''} {!scenario ? 'scenario configuration' : ''}
        </div>
      </div>
    );
  }

  if (!replayData.events || replayData.events.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-red-500">No replay events found in data</div>
      </div>
    );
  }

  // Get current event
  const currentEvent = replayData.events[currentStep];
  const metadata = replayData.metadata || replayData.game_summary;
  const totalReward = (metadata as any)?.episode_reward ?? (metadata as any)?.final_reward ?? 0;
  const totalTurns = (metadata as any)?.final_turn ?? (metadata as any)?.total_turns ?? replayData.events.length;

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-6 text-center">WH40K Game Replay</h1>
        
        {/* Game board using existing Board component */}
        <div className="mb-6 flex justify-center">
          <div className="border border-gray-700 rounded-lg overflow-hidden bg-gray-800">
            <Board
              units={currentUnits}
              selectedUnitId={currentEvent?.acting_unit_idx ?? null}
              mode="select"
              movePreview={null}
              attackPreview={null}
              onSelectUnit={() => {}} // Disabled for replay
              onStartMovePreview={() => {}} // Disabled for replay
              onStartAttackPreview={() => {}} // Disabled for replay
              onConfirmMove={() => {}} // Disabled for replay
              onCancelMove={() => {}} // Disabled for replay
              onShoot={() => {}} // Disabled for replay
              onCombatAttack={() => {}} // Disabled for replay
              currentPlayer={0}
              unitsMoved={[]}
              unitsCharged={[]}
              unitsAttacked={[]}
              phase="move"
              onCharge={() => {}} // Disabled for replay
              onMoveCharger={() => {}} // Disabled for replay
              onCancelCharge={() => {}} // Disabled for replay
              onValidateCharge={() => {}} // Disabled for replay
            />
          </div>
        </div>

        {/* Controls */}
        <div className="mb-6 flex flex-wrap items-center justify-center gap-4">
          <button 
            onClick={reset}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded transition-colors"
          >
            ⏮️ Reset
          </button>
          <button 
            onClick={prevStep}
            disabled={currentStep === 0}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors"
          >
            ⏪ Previous
          </button>
          <button 
            onClick={isPlaying ? pause : play}
            disabled={currentStep >= replayData.events.length - 1}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors"
          >
            {isPlaying ? '⏸️ Pause' : '▶️ Play'}
          </button>
          <button 
            onClick={nextStep}
            disabled={currentStep >= replayData.events.length - 1}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors"
          >
            Next ⏩
          </button>
        </div>

        {/* Speed control */}
        <div className="mb-6 flex items-center justify-center gap-4">
          <label className="text-sm">Speed:</label>
          <input
            type="range"
            min="100"
            max="2000"
            step="100"
            value={playSpeed}
            onChange={(e) => setPlaySpeed(Number(e.target.value))}
            className="w-32"
          />
          <span className="text-sm text-gray-400">{(2000 / playSpeed).toFixed(1)}x</span>
        </div>

        {/* Info panel */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="bg-gray-800 p-4 rounded-lg">
            <h3 className="text-lg font-semibold mb-2">Progress</h3>
            <div className="text-sm space-y-1">
              <div>Step: {currentStep + 1} / {replayData.events.length}</div>
              <div className="w-full bg-gray-700 rounded-full h-2">
                <div 
                  className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${((currentStep + 1) / replayData.events.length) * 100}%` }}
                ></div>
              </div>
            </div>
          </div>
          
          <div className="bg-gray-800 p-4 rounded-lg">
            <h3 className="text-lg font-semibold mb-2">Game Info</h3>
            <div className="text-sm space-y-1">
              <div>Total Reward: {totalReward.toFixed(2)}</div>
              <div>Total Turns: {totalTurns}</div>
            </div>
          </div>

          <div className="bg-gray-800 p-4 rounded-lg">
            <h3 className="text-lg font-semibold mb-2">Current Event</h3>
            <div className="text-sm space-y-1">
              <div>Turn: {currentEvent?.turn ?? 'N/A'}</div>
              <div>Action: {currentEvent?.action ?? 'N/A'}</div>
              <div>Reward: {currentEvent?.reward?.toFixed(2) ?? 'N/A'}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};