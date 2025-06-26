// frontend/src/components/GameReplayViewer.tsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import * as PIXI from 'pixi.js';

// Board configuration from your game
const BOARD_COLS = 24;
const BOARD_ROWS = 18;
const HEX_RADIUS = 24;
const MARGIN = 32;
const HEX_WIDTH = 1.5 * HEX_RADIUS;
const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
const HEX_HORIZ_SPACING = HEX_WIDTH;
const HEX_VERT_SPACING = HEX_HEIGHT;

// Colors from your game
const COLORS = {
  BOARD_BG: 0x002200,
  CELL_EVEN: 0x002200,
  CELL_ODD: 0x001a00,
  CELL_BORDER: 0x00ff00,
  PLAYER_0: 0x244488,
  PLAYER_1: 0x882222,
  HP_FULL: 0x36e36b,
  HP_DAMAGED: 0x444444,
  HIGHLIGHT: 0x80ff80,
  CURRENT_UNIT: 0xffd700
};

// Unit types from your scenario
const UNIT_TYPES = {
  'Intercessor': {
    HP_MAX: 3,
    MOVE: 4,
    RNG_RNG: 8,
    RNG_DMG: 2,
    CC_DMG: 1,
    ICON: '/icons/Intercessor.webp',
    SYMBOL: 'I'
  },
  'AssaultIntercessor': {
    HP_MAX: 4,
    MOVE: 6,
    RNG_RNG: 4,
    RNG_DMG: 1,
    CC_DMG: 2,
    ICON: '/icons/AssaultIntercessor.webp',
    SYMBOL: 'A'
  }
};

// Default unit positions from your scenario
const DEFAULT_POSITIONS = [
  { col: 23, row: 12 }, // Player 0 Intercessor
  { col: 1, row: 12 },  // Player 0 Assault Intercessor
  { col: 0, row: 5 },   // Player 1 Intercessor
  { col: 22, row: 3 }   // Player 1 Assault Intercessor
];

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
  action?: number;
  acting_unit_idx?: number;
  units?: Unit[];
  ai_units_alive?: number;
  enemy_units_alive?: number;
  game_over?: boolean;
  reward?: number;
}

interface GameReplayViewerProps {
  replayFile?: string;
}

export const GameReplayViewer: React.FC<GameReplayViewerProps> = ({ 
  replayFile = 'ai/event_log/train_best_game_replay.json' 
}) => {
  const [replayData, setReplayData] = useState<ReplayEvent[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const boardRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Load scenario parameters
  const loadScenarioData = useCallback(async () => {
    try {
      const response = await fetch('/ai/scenario.json');
      if (response.ok) {
        const scenarioData = await response.json();
        return scenarioData;
      }
    } catch (error) {
      console.warn('Could not load scenario.json, using defaults');
    }
    
    // Return default scenario if file not found
    return [
      {
        id: 1,
        unit_type: "Intercessor",
        player: 0,
        col: 23,
        row: 12,
        cur_hp: 3,
        hp_max: 3,
        move: 4,
        rng_rng: 8,
        rng_dmg: 2,
        cc_dmg: 1,
        is_ranged: true,
        is_melee: false,
        alive: true
      },
      {
        id: 2,
        unit_type: "AssaultIntercessor",
        player: 0,
        col: 1,
        row: 12,
        cur_hp: 4,
        hp_max: 4,
        move: 6,
        rng_rng: 4,
        rng_dmg: 1,
        cc_dmg: 2,
        is_ranged: false,
        is_melee: true,
        alive: true
      },
      {
        id: 3,
        unit_type: "Intercessor",
        player: 1,
        col: 0,
        row: 5,
        cur_hp: 3,
        hp_max: 3,
        move: 4,
        rng_rng: 8,
        rng_dmg: 2,
        cc_dmg: 1,
        is_ranged: true,
        is_melee: false,
        alive: true
      },
      {
        id: 4,
        unit_type: "AssaultIntercessor",
        player: 1,
        col: 22,
        row: 3,
        cur_hp: 4,
        hp_max: 4,
        move: 6,
        rng_rng: 4,
        rng_dmg: 1,
        cc_dmg: 2,
        is_ranged: false,
        is_melee: true,
        alive: true
      }
    ];
  }, []);

  // Load replay data
  const loadReplayData = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(replayFile);
      if (!response.ok) {
        throw new Error(`Failed to load replay file: ${response.statusText}`);
      }
      
      const data = await response.json();
      
      // Handle different replay formats
      let events: ReplayEvent[] = [];
      
      if (Array.isArray(data)) {
        events = data;
      } else if (data.events && Array.isArray(data.events)) {
        events = data.events;
      } else if (data.log && Array.isArray(data.log)) {
        events = data.log;
      } else {
        events = [data];
      }
      
      setReplayData(events);
      setCurrentStep(0);
      console.log(`Loaded ${events.length} replay events`);
      
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error loading replay';
      setError(errorMsg);
      console.error('Error loading replay:', err);
    } finally {
      setLoading(false);
    }
  }, [replayFile]);

  // Create units from event data
  const createUnitsFromEvent = useCallback(async (event: ReplayEvent): Promise<Unit[]> => {
    // If event has full unit data, use it
    if (event.units && Array.isArray(event.units)) {
      return event.units.map(unit => ({
        ...unit,
        CUR_HP: unit.CUR_HP ?? unit.HP_MAX,
        alive: (unit.CUR_HP ?? unit.HP_MAX) > 0
      }));
    }

    // Otherwise, reconstruct from scenario and event data
    const scenarioData = await loadScenarioData();
    const aiAlive = event.ai_units_alive ?? 2;
    const playerAlive = event.enemy_units_alive ?? 2;

    return scenarioData.map((scenarioUnit: any, index: number) => {
      const unitType = UNIT_TYPES[scenarioUnit.unit_type as keyof typeof UNIT_TYPES];
      const isAlive = scenarioUnit.player === 1 ? 
        (index - 2 < aiAlive) : 
        (index < playerAlive);

      return {
        id: scenarioUnit.id,
        name: `${scenarioUnit.player === 0 ? 'P' : 'A'}-${unitType?.SYMBOL || 'U'}`,
        type: scenarioUnit.unit_type,
        player: scenarioUnit.player,
        col: scenarioUnit.col,
        row: scenarioUnit.row,
        color: scenarioUnit.player === 0 ? COLORS.PLAYER_0 : COLORS.PLAYER_1,
        MOVE: scenarioUnit.move,
        HP_MAX: scenarioUnit.hp_max,
        CUR_HP: isAlive ? scenarioUnit.cur_hp : 0,
        RNG_RNG: scenarioUnit.rng_rng,
        RNG_DMG: scenarioUnit.rng_dmg,
        CC_DMG: scenarioUnit.cc_dmg,
        ICON: unitType?.ICON || '/icons/default.webp',
        alive: isAlive
      };
    });
  }, [loadScenarioData]);

  // Hex utility functions (same as your Board.tsx)
  const getHexCenter = useCallback((col: number, row: number) => {
    const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
    return { x: centerX, y: centerY };
  }, []);

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

  // Draw the game board
  const drawBoard = useCallback(async (units: Unit[], activeUnitId?: number) => {
    if (!boardRef.current || !appRef.current) return;

    const app = appRef.current;
    app.stage.removeChildren();

    // Draw hex grid
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        const center = getHexCenter(col, row);
        const points = getHexPolygonPoints(center.x, center.y, HEX_RADIUS);
        
        const cell = new PIXI.Graphics();
        cell.lineStyle(1, COLORS.CELL_BORDER, 0.3);
        cell.beginFill((col + row) % 2 === 0 ? COLORS.CELL_EVEN : COLORS.CELL_ODD, 0.2);
        cell.drawPolygon(points);
        cell.endFill();
        
        app.stage.addChild(cell);
      }
    }

    // Draw units
    for (const unit of units) {
      if (!unit.alive || (unit.CUR_HP ?? 0) <= 0) continue;

      const center = getHexCenter(unit.col, unit.row);
      const isActiveUnit = activeUnitId === unit.id;

      // Unit circle
      const unitCircle = new PIXI.Graphics();
      unitCircle.lineStyle(2, isActiveUnit ? COLORS.CURRENT_UNIT : 0xffffff, 1);
      unitCircle.beginFill(unit.color, 0.8);
      unitCircle.drawCircle(center.x, center.y, HEX_RADIUS * 0.6);
      unitCircle.endFill();
      app.stage.addChild(unitCircle);

      // Unit symbol
      const unitText = new PIXI.Text(UNIT_TYPES[unit.type as keyof typeof UNIT_TYPES]?.SYMBOL || 'U', {
        fontFamily: 'Arial',
        fontSize: 16,
        fill: 0xffffff,
        fontWeight: 'bold'
      });
      unitText.anchor.set(0.5);
      unitText.x = center.x;
      unitText.y = center.y;
      app.stage.addChild(unitText);

      // HP Bar
      const HP_BAR_WIDTH = HEX_RADIUS * 1.4;
      const HP_BAR_HEIGHT = 7;
      const HP_BAR_Y_OFFSET = HEX_RADIUS * 0.85;

      const barX = center.x - HP_BAR_WIDTH / 2;
      const barY = center.y - HP_BAR_Y_OFFSET - HP_BAR_HEIGHT;

      // HP background
      const barBg = new PIXI.Graphics();
      barBg.beginFill(0x222222, 1);
      barBg.drawRoundedRect(barX, barY, HP_BAR_WIDTH, HP_BAR_HEIGHT, 3);
      barBg.endFill();
      app.stage.addChild(barBg);

      // HP segments
      const hp = Math.max(0, unit.CUR_HP || 0);
      for (let i = 0; i < unit.HP_MAX; i++) {
        const sliceWidth = (HP_BAR_WIDTH - (unit.HP_MAX - 1)) / unit.HP_MAX;
        const sliceX = barX + i * (sliceWidth + 1);
        const color = i < hp ? COLORS.HP_FULL : COLORS.HP_DAMAGED;
        
        const slice = new PIXI.Graphics();
        slice.beginFill(color, 1);
        slice.drawRoundedRect(sliceX, barY + 1, sliceWidth, HP_BAR_HEIGHT - 2, 2);
        slice.endFill();
        app.stage.addChild(slice);
      }

      // Unit name
      const nameText = new PIXI.Text(unit.name, {
        fontFamily: 'Arial',
        fontSize: 12,
        fill: 0xffffff
      });
      nameText.anchor.set(0.5);
      nameText.x = center.x;
      nameText.y = center.y + HEX_RADIUS * 0.8;
      app.stage.addChild(nameText);
    }
  }, [getHexCenter, getHexPolygonPoints]);

  // Initialize PIXI application
  useEffect(() => {
    if (!boardRef.current || appRef.current) return;

    const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
    const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
    const width = Math.min(gridWidth + 2 * MARGIN, window.innerWidth - 40);
    const height = Math.min(gridHeight + 2 * MARGIN, window.innerHeight - 300);

    const app = new PIXI.Application({
      width,
      height,
      backgroundColor: COLORS.BOARD_BG,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });

    boardRef.current.appendChild(app.view as unknown as HTMLCanvasElement);
    appRef.current = app;

    return () => {
      if (appRef.current) {
        appRef.current.destroy(true);
        appRef.current = null;
      }
    };
  }, []);

  // Update board when current step changes
  useEffect(() => {
    if (!replayData.length || !appRef.current) return;

    const currentEvent = replayData[currentStep];
    if (!currentEvent) return;

    createUnitsFromEvent(currentEvent).then(units => {
      drawBoard(units, currentEvent.acting_unit_idx);
    });
  }, [currentStep, replayData, createUnitsFromEvent, drawBoard]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData.length > 0) {
      playIntervalRef.current = setInterval(() => {
        setCurrentStep(prev => {
          if (prev >= replayData.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, playSpeed);
    } else if (playIntervalRef.current) {
      clearInterval(playIntervalRef.current);
      playIntervalRef.current = null;
    }

    return () => {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
      }
    };
  }, [isPlaying, playSpeed, replayData.length]);

  // Load replay on mount
  useEffect(() => {
    loadReplayData();
  }, [loadReplayData]);

  const handlePlayPause = () => {
    setIsPlaying(!isPlaying);
  };

  const handleStepForward = () => {
    if (currentStep < replayData.length - 1) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleStepBackward = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleReset = () => {
    setCurrentStep(0);
    setIsPlaying(false);
  };

  const currentEvent = replayData[currentStep];

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-blue-500 mx-auto"></div>
          <p className="mt-4 text-lg">Loading replay data...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center text-red-500">
          <h2 className="text-2xl font-bold mb-4">Error Loading Replay</h2>
          <p className="mb-4">{error}</p>
          <button 
            onClick={loadReplayData}
            className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold mb-2">Game Replay Viewer</h1>
          <p className="text-gray-400">Watching: {replayFile}</p>
        </div>

        {/* Controls */}
        <div className="mb-6 p-4 bg-gray-800 rounded-lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-4">
              <button
                onClick={handleReset}
                className="px-3 py-1 bg-gray-600 rounded hover:bg-gray-500"
              >
                ⏮ Reset
              </button>
              <button
                onClick={handleStepBackward}
                disabled={currentStep === 0}
                className="px-3 py-1 bg-gray-600 rounded hover:bg-gray-500 disabled:opacity-50"
              >
                ⏪ Step Back
              </button>
              <button
                onClick={handlePlayPause}
                className="px-4 py-2 bg-blue-600 rounded hover:bg-blue-500"
              >
                {isPlaying ? '⏸ Pause' : '▶ Play'}
              </button>
              <button
                onClick={handleStepForward}
                disabled={currentStep >= replayData.length - 1}
                className="px-3 py-1 bg-gray-600 rounded hover:bg-gray-500 disabled:opacity-50"
              >
                Step Forward ⏩
              </button>
            </div>
            
            <div className="flex items-center space-x-4">
              <label className="text-sm">
                Speed:
                <select 
                  value={playSpeed} 
                  onChange={(e) => setPlaySpeed(Number(e.target.value))}
                  className="ml-2 bg-gray-700 rounded px-2 py-1"
                >
                  <option value={2000}>0.5x</option>
                  <option value={1000}>1x</option>
                  <option value={500}>2x</option>
                  <option value={250}>4x</option>
                </select>
              </label>
            </div>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-gray-700 rounded-full h-2">
            <div 
              className="bg-blue-500 h-2 rounded-full transition-all duration-200"
              style={{ width: `${(currentStep / Math.max(replayData.length - 1, 1)) * 100}%` }}
            />
          </div>
          
          <div className="flex justify-between text-sm mt-2">
            <span>Step {currentStep + 1} of {replayData.length}</span>
            {currentEvent && (
              <span>
                Turn: {currentEvent.turn || '?'} | 
                Action: {currentEvent.action || '?'} | 
                Reward: {currentEvent.reward?.toFixed(2) || '?'}
              </span>
            )}
          </div>
        </div>

        {/* Game Board */}
        <div className="flex justify-center">
          <div 
            ref={boardRef} 
            className="border border-gray-600 rounded-lg overflow-hidden"
            style={{ backgroundColor: '#002200' }}
          />
        </div>

        {/* Event Info */}
        {currentEvent && (
          <div className="mt-6 p-4 bg-gray-800 rounded-lg">
            <h3 className="text-lg font-bold mb-2">Current Event</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <span className="text-gray-400">Turn:</span> {currentEvent.turn || 'N/A'}
              </div>
              <div>
                <span className="text-gray-400">Action:</span> {currentEvent.action || 'N/A'}
              </div>
              <div>
                <span className="text-gray-400">Acting Unit:</span> {currentEvent.acting_unit_idx || 'N/A'}
              </div>
              <div>
                <span className="text-gray-400">Reward:</span> {currentEvent.reward?.toFixed(2) || 'N/A'}
              </div>
              <div>
                <span className="text-gray-400">AI Units:</span> {currentEvent.ai_units_alive || 'N/A'}
              </div>
              <div>
                <span className="text-gray-400">Player Units:</span> {currentEvent.enemy_units_alive || 'N/A'}
              </div>
              <div>
                <span className="text-gray-400">Game Over:</span> {currentEvent.game_over ? 'Yes' : 'No'}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};