// frontend/src/components/ReplayViewer.tsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import * as PIXI from "pixi.js-legacy";
import { Intercessor } from '../roster/spaceMarine/Intercessor';
import { AssaultIntercessor } from '../roster/spaceMarine/AssaultIntercessor';

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

interface Unit {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  alive?: boolean;
}

interface ReplayEvent {
  turn?: number;
  type?: string;
  timestamp?: string;
  action?: {
    type?: string;
    action_id?: number;
    reward?: number;
  };
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

interface GameReplayViewerProps {
  replayFile?: string;
}

// Unit type registry - imports the actual unit classes to get their static properties
const UNIT_REGISTRY = {
  'Intercessor': Intercessor,
  'AssaultIntercessor': AssaultIntercessor
};

// Action mapping for display
const ACTION_NAMES: { [key: number]: string } = {
  0: "Move Closer",
  1: "Move Away", 
  2: "Move to Safety",
  3: "Shoot Closest",
  4: "Shoot Weakest",
  5: "Charge Closest",
  6: "Wait",
  7: "Attack Adjacent"
};

export const GameReplayViewer: React.FC<GameReplayViewerProps> = ({ 
  replayFile = 'ai/event_log/train_best_game_replay.json' 
}) => {
  const [scenario, setScenario] = useState<ScenarioConfig | null>(null);
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentUnits, setCurrentUnits] = useState<Unit[]>([]);
  const [useHtmlFallback, setUseHtmlFallback] = useState(false);
  
  const boardRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const unitSpritesRef = useRef<Map<number, PIXI.Container>>(new Map());

  // Load scenario configuration
  const loadScenario = useCallback(async () => {
    try {
      console.log('Loading scenario from /ai/scenario.json...');
      const response = await fetch('/ai/scenario.json');
      if (!response.ok) {
        throw new Error(`Failed to load scenario: ${response.statusText}`);
      }
      const data = await response.json();
      console.log('Scenario loaded:', data);
      setScenario(data);
      return data;
    } catch (err) {
      console.error('Error loading scenario:', err);
      throw err;
    }
  }, []);

  // Load replay data
  const loadReplayData = useCallback(async () => {
    try {
      console.log(`Loading replay from /${replayFile}...`);
      const response = await fetch(`/${replayFile}`);
      if (!response.ok) {
        throw new Error(`Failed to load replay: ${response.statusText}`);
      }
      const data = await response.json();
      console.log('Replay data loaded:', data);
      setReplayData(data);
      return data;
    } catch (err) {
      console.error('Error loading replay data:', err);
      throw err;
    }
  }, [replayFile]);

  // Load all data on component mount
  useEffect(() => {
    let isMounted = true;
    
    const loadAllData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        await loadScenario();
        await loadReplayData();
        
        if (isMounted) {
          setCurrentStep(0);
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to load data');
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    loadAllData();

    return () => {
      isMounted = false;
    };
  }, [loadScenario, loadReplayData]);

  // Hex utility functions
  const getHexCenter = useCallback((col: number, row: number) => {
    if (!scenario) return { x: 0, y: 0 };
    
    const { board } = scenario;
    const HEX_WIDTH = 1.5 * board.hex_radius;
    const HEX_HEIGHT = Math.sqrt(3) * board.hex_radius;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;
    
    const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + board.margin;
    const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + board.margin;
    return { x: centerX, y: centerY };
  }, [scenario]);

  const getHexPolygonPoints = useCallback((cx: number, cy: number, size: number) => {
    const points = [];
    for (let i = 0; i < 6; i++) {
      const angle_deg = 60 * i;
      const angle_rad = Math.PI / 180 * angle_deg;
      points.push(cx + size * Math.cos(angle_rad));
      points.push(cy + size * Math.sin(angle_rad));
    }
    return points;
  }, []);

  // Get unit stats from the actual unit classes
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

  // Convert units from scenario/replay format to display format with simulated movement
  const convertUnits = useCallback((event: ReplayEvent): Unit[] => {
    if (!scenario) {
      throw new Error('Scenario not loaded');
    }

    console.log('Converting units from event:', event);

    // If the event has full unit data, use it
    if (event.units && Array.isArray(event.units) && event.units.length > 0) {
      console.log('Using units from event data');
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
          name: `${unit.player === 0 ? 'P' : 'A'}-${unit.type.charAt(0)}`,
          color: parseInt(unit.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1),
          ICON: stats.ICON,
          alive: (unit.CUR_HP ?? unit.HP_MAX) > 0
        };
      });
    }

    // Otherwise, simulate from scenario and event data
    if (!scenario.units || scenario.units.length === 0) {
      throw new Error('No units defined in scenario');
    }

    console.log('Simulating units from scenario and event data');
    
    // Extract event data
    const turn = event.turn || event.game_state?.turn || 1;
    const actionId = event.action?.action_id || 0;
    const aiAlive = event.game_state?.ai_units_alive || event.units?.ai_count || event.ai_units_alive || 2;
    const enemyAlive = event.game_state?.enemy_units_alive || event.units?.enemy_count || event.enemy_units_alive || 2;

    return scenario.units.map((scenarioUnit, index) => {
      const isPlayer = scenarioUnit.player === 0;
      const isAlive = isPlayer ? (index < enemyAlive) : (index - 2 < aiAlive);
      
      // Simulate movement based on turn and action
      let col = scenarioUnit.col;
      let row = scenarioUnit.row;
      
      if (isAlive && turn > 1) {
        // Movement simulation based on action
        const movementFactor = Math.floor(turn / 3);
        
        if (actionId === 0) { // Move Closer
          if (isPlayer) {
            col = Math.max(1, scenarioUnit.col - movementFactor);
          } else {
            col = Math.min(22, scenarioUnit.col + movementFactor);
          }
        } else if (actionId === 1) { // Move Away
          if (isPlayer) {
            col = Math.min(22, scenarioUnit.col + movementFactor);
          } else {
            col = Math.max(1, scenarioUnit.col - movementFactor);
          }
        } else if (actionId === 2) { // Move to Safety
          row = Math.max(1, Math.min(16, scenarioUnit.row + (movementFactor % 3 - 1)));
        }
        
        // Add variation to make movement visible
        col += Math.floor((turn + index) % 3) - 1;
        row += Math.floor((turn * 2 + index) % 3) - 1;
        
        // Clamp to bounds
        col = Math.max(0, Math.min(scenario.board.cols - 1, col));
        row = Math.max(0, Math.min(scenario.board.rows - 1, row));
      }

      const stats = getUnitStats(scenarioUnit.unit_type);
      
      return {
        id: scenarioUnit.id,
        name: `${isPlayer ? 'P' : 'A'}-${scenarioUnit.unit_type.charAt(0)}`,
        type: scenarioUnit.unit_type,
        player: scenarioUnit.player as 0 | 1,
        col,
        row,
        color: parseInt(isPlayer ? scenario.colors.player_0 : scenario.colors.player_1),
        CUR_HP: isAlive ? Math.max(1, stats.HP_MAX - Math.floor(turn / 5)) : 0,
        alive: isAlive,
        ...stats
      };
    });
  }, [scenario, getUnitStats]);

  // Draw hex board
  const drawBoard = useCallback((app: PIXI.Application) => {
    if (!scenario) {
      throw new Error('Scenario not loaded for board drawing');
    }

    const { board } = scenario;
    console.log('Drawing board with PIXI.js...');

    // Clear any existing board elements
    app.stage.removeChildren();

    // Create board graphics
    for (let col = 0; col < board.cols; col++) {
      for (let row = 0; row < board.rows; row++) {
        const center = getHexCenter(col, row);
        const hexagon = new PIXI.Graphics();
        
        // Draw hex background
        hexagon.beginFill(0x2d2d44);
        hexagon.lineStyle(1, 0x444466);
        
        const points = getHexPolygonPoints(center.x, center.y, board.hex_radius);
        hexagon.drawPolygon(points);
        hexagon.endFill();
        
        app.stage.addChild(hexagon);
      }
    }

    console.log(`Board drawn with ${board.cols}x${board.rows} hexagons`);
  }, [scenario, getHexCenter, getHexPolygonPoints]);

  // Draw units on the board
  const drawUnits = useCallback((app: PIXI.Application, units: Unit[]) => {
    if (!scenario) return;

    // Remove existing unit sprites
    unitSpritesRef.current.forEach(sprite => {
      app.stage.removeChild(sprite);
      sprite.destroy();
    });
    unitSpritesRef.current.clear();

    // Draw each unit
    units.forEach(unit => {
      if (!unit.alive) return;

      const center = getHexCenter(unit.col, unit.row);
      const unitContainer = new PIXI.Container();

      // Unit circle
      const circle = new PIXI.Graphics();
      circle.beginFill(unit.color);
      circle.lineStyle(2, 0xffffff);
      circle.drawCircle(0, 0, scenario.board.hex_radius * 0.6);
      circle.endFill();
      unitContainer.addChild(circle);

      // Unit name text
      const nameText = new PIXI.Text(unit.name, {
        fontFamily: 'Arial',
        fontSize: 12,
        fill: 0xffffff,
        align: 'center',
        stroke: 0x000000,
        strokeThickness: 1
      });
      nameText.anchor.set(0.5);
      nameText.position.set(0, 0);
      unitContainer.addChild(nameText);

      // HP indicator
      const hpText = new PIXI.Text(`${unit.CUR_HP}/${unit.HP_MAX}`, {
        fontFamily: 'Arial',
        fontSize: 10,
        fill: unit.CUR_HP <= unit.HP_MAX / 2 ? 0xff4444 : 0x44ff44,
        align: 'center'
      });
      hpText.anchor.set(0.5);
      hpText.position.set(0, scenario.board.hex_radius * 0.8);
      unitContainer.addChild(hpText);
      
      // Position the unit container
      unitContainer.position.set(center.x, center.y);
      app.stage.addChild(unitContainer);
      
      // Store reference for future updates
      unitSpritesRef.current.set(unit.id, unitContainer);
    });
    
    console.log(`Drew ${units.filter(u => u.alive).length} units on board`);
  }, [scenario, getHexCenter]);

  // Initialize PIXI application with Canvas renderer (no WebGL)
  useEffect(() => {
    if (!boardRef.current || !scenario || !replayData || useHtmlFallback) return;

    try {
      // Always use Canvas renderer (no WebGL as per instructions)
      const app = new PIXI.Application({
        width: scenario.board.cols * scenario.board.hex_radius * 1.5 + scenario.board.margin * 2,
        height: scenario.board.rows * scenario.board.hex_radius * 1.75 + scenario.board.margin * 2,
        backgroundColor: 0x1a1a2e,
        antialias: true,
        forceCanvas: true, // Always use Canvas renderer, never WebGL
      });

      boardRef.current.appendChild(app.view as HTMLCanvasElement);
      appRef.current = app;

      // Draw initial board
      drawBoard(app);
      
      // Draw initial units
      if (replayData.events[0]) {
        const initialUnits = convertUnits(replayData.events[0]);
        setCurrentUnits(initialUnits);
        drawUnits(app, initialUnits);
      }

    } catch (err) {
      console.error('Error initializing PIXI Canvas:', err);
      console.log('PIXI Canvas failed, using HTML fallback...');
      setUseHtmlFallback(true);
      setError(null); // Clear error, we have HTML fallback
    }

    return () => {
      if (appRef.current) {
        appRef.current.destroy(true);
        appRef.current = null;
      }
    };
  }, [scenario, replayData, convertUnits, drawBoard, drawUnits, useHtmlFallback]);

  // HTML Fallback Renderer
  const renderHTMLBoard = useCallback(() => {
    if (!scenario || !currentUnits) return null;

    return (
      <div 
        className="relative bg-gray-800 border border-gray-600 rounded"
        style={{
          width: scenario.board.cols * 32 + 'px',
          height: scenario.board.rows * 32 + 'px',
          maxWidth: '100%',
          aspectRatio: `${scenario.board.cols} / ${scenario.board.rows}`
        }}
      >
        {/* Grid background */}
        <div className="absolute inset-0 opacity-20">
          {Array.from({ length: scenario.board.rows }, (_, row) =>
            Array.from({ length: scenario.board.cols }, (_, col) => (
              <div
                key={`${col}-${row}`}
                className="absolute border border-gray-600"
                style={{
                  left: `${(col / scenario.board.cols) * 100}%`,
                  top: `${(row / scenario.board.rows) * 100}%`,
                  width: `${100 / scenario.board.cols}%`,
                  height: `${100 / scenario.board.rows}%`
                }}
              />
            ))
          )}
        </div>

        {/* Units */}
        {currentUnits.map(unit => (
          unit.alive && (
            <div
              key={unit.id}
              className="absolute rounded-full border-2 border-white flex items-center justify-center text-xs font-bold text-white shadow-lg"
              style={{
                left: `${(unit.col / scenario.board.cols) * 100}%`,
                top: `${(unit.row / scenario.board.rows) * 100}%`,
                width: '24px',
                height: '24px',
                backgroundColor: `#${unit.color.toString(16).padStart(6, '0')}`,
                transform: 'translate(-50%, -50%)',
                zIndex: 10
              }}
              title={`${unit.name} (${unit.CUR_HP}/${unit.HP_MAX} HP)`}
            >
              {unit.name}
            </div>
          )
        ))}
      </div>
    );
  }, [scenario, currentUnits]);

  // THE CRITICAL MISSING PIECE: updateDisplay function
  const updateDisplay = useCallback(() => {
    if (!replayData || !scenario || !appRef.current) {
      console.warn('updateDisplay called but missing data or app');
      return;
    }
    
    if (currentStep >= replayData.events.length) {
      console.warn(`updateDisplay: currentStep ${currentStep} >= events.length ${replayData.events.length}`);
      return;
    }

    const event = replayData.events[currentStep];
    if (!event) {
      console.warn(`updateDisplay: no event at step ${currentStep}`);
      return;
    }

    try {
      // Convert event to units with current positions
      const units = convertUnits(event);
      setCurrentUnits(units);
      
      // Redraw units at new positions
      drawUnits(appRef.current, units);
      
      const turn = event.turn || event.game_state?.turn || 1;
      const actionId = event.action?.action_id || 0;
      console.log(`Updated display for step ${currentStep}, turn ${turn}, action ${actionId}`);
      
    } catch (err) {
      console.error('Error in updateDisplay:', err);
      throw err;
    }
  }, [currentStep, replayData, scenario, convertUnits, drawUnits]);

  // Update display when step changes
  useEffect(() => {
    if (replayData && scenario && appRef.current) {
      try {
        updateDisplay();
      } catch (err) {
        console.error('Error updating display:', err);
        setError(err instanceof Error ? err.message : 'Unknown display error');
      }
    }
  }, [currentStep, replayData, scenario, updateDisplay]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData && currentStep < replayData.events.length - 1) {
      playIntervalRef.current = setTimeout(() => {
        setCurrentStep((prev: number) => prev + 1);
      }, playSpeed);
    } else {
      setIsPlaying(false);
    }

    return () => {
      if (playIntervalRef.current) {
        clearTimeout(playIntervalRef.current);
      }
    };
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

  // Refresh function for WebGL issues
  const refreshViewer = () => {
    window.location.reload();
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
            onClick={refreshViewer}
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

  // Get current event info for display
  const currentEvent = replayData.events[currentStep];
  const metadata = replayData.metadata || replayData.game_summary || {};
  const totalReward = (metadata as any)?.episode_reward ?? (metadata as any)?.final_reward ?? 0;
  const totalTurns = (metadata as any)?.final_turn ?? (metadata as any)?.total_turns ?? replayData.events.length;
  const currentTurn = currentEvent?.turn || currentEvent?.game_state?.turn || currentStep + 1;
  const currentAction = currentEvent?.action?.action_id || 0;
  const currentReward = currentEvent?.action?.reward || currentEvent?.reward || 0;
  const aiAlive = currentEvent?.game_state?.ai_units_alive || currentEvent?.units?.ai_count || currentEvent?.ai_units_alive || 2;
  const enemyAlive = currentEvent?.game_state?.enemy_units_alive || currentEvent?.units?.enemy_count || currentEvent?.enemy_units_alive || 2;

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold mb-2">🎮 WH40K Replay Viewer</h1>
          <div className="text-gray-400 flex flex-wrap gap-4">
            <span>Step {currentStep + 1} of {replayData.events.length}</span>
            <span>Turn {currentTurn}</span>
            <span>Action: {ACTION_NAMES[currentAction] || `Unknown (${currentAction})`}</span>
            <span>Reward: {typeof currentReward === 'number' ? currentReward.toFixed(2) : '0.00'}</span>
            <span>Total: {typeof totalReward === 'number' ? totalReward.toFixed(2) : '0.00'}</span>
            <span>AI: {aiAlive}</span>
            <span>Enemy: {enemyAlive}</span>
          </div>
        </div>

        {/* Game Board */}
        <div className="flex flex-col lg:flex-row gap-6">
          <div className="flex-1">
            {useHtmlFallback ? (
              <div className="p-4 bg-gray-800 rounded-lg">
                <div className="mb-2 text-sm text-yellow-400">
                  ⚠️ Using HTML fallback (PIXI Canvas unavailable)
                </div>
                {renderHTMLBoard()}
              </div>
            ) : (
              <div 
                ref={boardRef} 
                className="border border-gray-700 rounded-lg overflow-hidden bg-gray-800"
              />
            )}
          </div>

          {/* Controls Panel */}
          <div className="lg:w-80 space-y-4">
            {/* Playback Controls */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Playback Controls</h3>
              
              <div className="flex gap-2 mb-4">
                <button
                  onClick={reset}
                  className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors"
                  title="Reset to beginning"
                >
                  ⏮️
                </button>
                <button
                  onClick={prevStep}
                  disabled={currentStep === 0}
                  className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
                  title="Previous step"
                >
                  ⏪
                </button>
                <button
                  onClick={isPlaying ? pause : play}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded transition-colors"
                  title={isPlaying ? 'Pause' : 'Play'}
                >
                  {isPlaying ? '⏸️' : '▶️'}
                </button>
                <button
                  onClick={nextStep}
                  disabled={currentStep >= replayData.events.length - 1}
                  className="px-3 py-2 bg-gray-600 hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
                  title="Next step"
                >
                  ⏩
                </button>
              </div>

              {/* Speed Control */}
              <div className="mb-4">
                <label className="block text-sm font-medium mb-2">Playback Speed</label>
                <select
                  value={playSpeed}
                  onChange={(e) => setPlaySpeed(Number(e.target.value))}
                  className="w-full p-2 bg-gray-700 border border-gray-600 rounded"
                >
                  <option value={2000}>0.5x (2000ms)</option>
                  <option value={1000}>1x (1000ms)</option>
                  <option value={500}>2x (500ms)</option>
                  <option value={250}>4x (250ms)</option>
                  <option value={100}>10x (100ms)</option>
                </select>
              </div>

              {/* Progress Bar */}
              <div className="mb-2">
                <label className="block text-sm font-medium mb-1">Progress</label>
                <input
                  type="range"
                  min={0}
                  max={replayData.events.length - 1}
                  value={currentStep}
                  onChange={(e) => setCurrentStep(Number(e.target.value))}
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>0</span>
                  <span>{replayData.events.length - 1}</span>
                </div>
              </div>
            </div>

            {/* Unit Status */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Unit Status</h3>
              <div className="space-y-2">
                {currentUnits.map(unit => (
                  <div key={unit.id} className="flex justify-between items-center p-2 bg-gray-700 rounded">
                    <div>
                      <div className="font-medium" style={{color: `#${unit.color.toString(16).padStart(6, '0')}`}}>
                        {unit.name}
                      </div>
                      <div className="text-sm text-gray-400">
                        ({unit.col}, {unit.row})
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`font-medium ${unit.CUR_HP <= unit.HP_MAX / 2 ? 'text-red-400' : 'text-green-400'}`}>
                        {unit.CUR_HP}/{unit.HP_MAX} HP
                      </div>
                      <div className="text-sm text-gray-400">
                        {unit.alive ? 'Alive' : 'Dead'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Event Details */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Event Details</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Turn:</span>
                  <span>{currentTurn}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Action:</span>
                  <span>{ACTION_NAMES[currentAction] || `Unknown (${currentAction})`}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Reward:</span>
                  <span className={currentReward >= 0 ? 'text-green-400' : 'text-red-400'}>
                    {typeof currentReward === 'number' ? currentReward.toFixed(3) : '0.000'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">AI Units:</span>
                  <span className="text-blue-400">{aiAlive}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Enemy Units:</span>
                  <span className="text-red-400">{enemyAlive}</span>
                </div>
                {currentEvent?.game_state?.game_over && (
                  <div className="mt-2 p-2 bg-red-900 rounded text-center">
                    <span className="text-red-200 font-medium">GAME OVER</span>
                  </div>
                )}
              </div>
            </div>

            {/* Replay Metadata */}
            <div className="bg-gray-800 p-4 rounded-lg">
              <h3 className="text-lg font-semibold mb-3">Replay Info</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Events:</span>
                  <span>{replayData.events.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Turns:</span>
                  <span>{totalTurns}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Final Reward:</span>
                  <span className={totalReward >= 0 ? 'text-green-400' : 'text-red-400'}>
                    {typeof totalReward === 'number' ? totalReward.toFixed(2) : '0.00'}
                  </span>
                </div>
                {(metadata as any)?.timestamp && (
                  <div className="flex justify-between">
                    <span className="text-gray-400">Recorded:</span>
                    <span className="text-xs">{new Date((metadata as any).timestamp).toLocaleDateString()}</span>
                  </div>
                )}
                {replayData.web_compatible && (
                  <div className="mt-2 p-2 bg-green-900 rounded text-center">
                    <span className="text-green-200 text-xs">✅ Web Compatible</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Action Legend */}
        <div className="mt-6 bg-gray-800 p-4 rounded-lg">
          <h3 className="text-lg font-semibold mb-3">Action Legend</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
            {Object.entries(ACTION_NAMES).map(([id, name]) => (
              <div 
                key={id} 
                className={`p-2 rounded ${currentAction === parseInt(id) ? 'bg-blue-900 border border-blue-500' : 'bg-gray-700'}`}
              >
                <span className="text-gray-400">{id}:</span> {name}
              </div>
            ))}
          </div>
        </div>

        {/* Debug Info (Development Only) */}
        {process.env.NODE_ENV === 'development' && (
          <div className="mt-6 bg-gray-800 p-4 rounded-lg">
            <h3 className="text-lg font-semibold mb-3">Debug Info</h3>
            <div className="text-xs font-mono bg-gray-900 p-3 rounded overflow-auto max-h-40">
              <div>Current Event:</div>
              <pre>{JSON.stringify(currentEvent, null, 2)}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Default export for the replay viewer
export default GameReplayViewer;