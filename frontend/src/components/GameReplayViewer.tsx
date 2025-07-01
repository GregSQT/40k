// frontend/src/components/GameReplayViewer.tsx
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
  action?: number;
  acting_unit_idx?: number;
  units?: Unit[];
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

export const GameReplayViewer: React.FC<GameReplayViewerProps> = ({
  replayFile = "ai/event_log/train_best_game_replay.json"
}) => {
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [scenario, setScenario] = useState<ScenarioConfig | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const boardRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const unitSpritesRef = useRef(new Map<number, PIXI.Container>());
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const isWebGLLostRef = useRef(false);

  // Unit stats mapping
  const getUnitStats = useCallback((unitType: string) => {
    switch (unitType) {
      case 'Intercessor':
        return {
          MOVE: Intercessor.MOVE,
          HP_MAX: Intercessor.HP_MAX,
          RNG_RNG: Intercessor.RNG_RNG,
          RNG_DMG: Intercessor.RNG_DMG,
          CC_DMG: Intercessor.CC_DMG,
          ICON: Intercessor.ICON
        };
      case 'AssaultIntercessor':
        return {
          MOVE: AssaultIntercessor.MOVE,
          HP_MAX: AssaultIntercessor.HP_MAX,
          RNG_RNG: AssaultIntercessor.RNG_RNG,
          RNG_DMG: AssaultIntercessor.RNG_DMG,
          CC_DMG: AssaultIntercessor.CC_DMG,
          ICON: AssaultIntercessor.ICON
        };
      default:
        throw new Error(`Unknown unit type: ${unitType}`);
    }
  }, []);

  // Load scenario configuration
  const loadScenario = useCallback(async (): Promise<ScenarioConfig> => {
    const response = await fetch('/ai/scenario.json');
    if (!response.ok) {
      throw new Error(`Failed to load scenario: ${response.statusText}`);
    }
    const data = await response.json();
    setScenario(data);
    return data;
  }, []);

  // Hex grid calculations
  const getHexCenter = useCallback((col: number, row: number) => {
    if (!scenario) throw new Error('Scenario not loaded');
    
    const { board } = scenario;
    const HEX_WIDTH = 1.5 * board.hex_radius;
    const HEX_HEIGHT = Math.sqrt(3) * board.hex_radius;
    
    const x = board.margin + col * HEX_WIDTH + board.hex_radius;
    const y = board.margin + row * HEX_HEIGHT + (col % 2) * (HEX_HEIGHT / 2) + board.hex_radius;
    
    return { x, y };
  }, [scenario]);

  const getHexPolygonPoints = useCallback((centerX: number, centerY: number, radius: number) => {
    const points: number[] = [];
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i;
      const x = centerX + radius * Math.cos(angle);
      const y = centerY + radius * Math.sin(angle);
      points.push(x, y);
    }
    return points;
  }, []);

  // Convert event data to units
  const convertUnits = useCallback((event: ReplayEvent): Unit[] => {
    if (!scenario) throw new Error('Scenario not loaded');
    
    console.log('Converting units from event:', event);
    
    if (event.units && Array.isArray(event.units)) {
      console.log('Using units from event data');
      return event.units.map(unit => ({
        ...unit,
        alive: (unit.CUR_HP ?? unit.HP_MAX) > 0
      }));
    }
    
    console.log('Reconstructing units from scenario and event data');
    const { ai_units_alive = 2, enemy_units_alive = 2 } = event;
    console.log(`AI units alive: ${ai_units_alive}, Player units alive: ${enemy_units_alive}`);
    
    return scenario.units.map((unitConfig, index) => {
      const stats = getUnitStats(unitConfig.unit_type);
      const isPlayer = unitConfig.player === 0;
      const isAlive = isPlayer ? index < enemy_units_alive + 2 : (index - 2) < ai_units_alive;
      
      const unit: Unit = {
        id: unitConfig.id,
        name: isPlayer ? (unitConfig.unit_type === 'Intercessor' ? 'P-I' : 'P-A') : 
                        (unitConfig.unit_type === 'Intercessor' ? 'A-I' : 'A-A'),
        type: unitConfig.unit_type,
        player: unitConfig.player as 0 | 1,
        col: unitConfig.col,
        row: unitConfig.row,
        color: parseInt(unitConfig.player === 0 ? 
          scenario.colors.player_0 : scenario.colors.player_1),
        MOVE: stats.MOVE,
        HP_MAX: stats.HP_MAX,
        CUR_HP: isAlive ? stats.HP_MAX : 0,
        RNG_RNG: stats.RNG_RNG,
        RNG_DMG: stats.RNG_DMG,
        CC_DMG: stats.CC_DMG,
        ICON: stats.ICON,
        alive: isAlive
      };

      console.log(`Created unit ${unit.name}:`, unit);
      return unit;
    });
  }, [scenario, getUnitStats]);

  // Safe PIXI app checker (simplified for Canvas rendering)
  const isPixiAppValid = useCallback(() => {
    return appRef.current && appRef.current.stage;
  }, []);

  // Draw the game board with Canvas rendering
  const drawBoard = useCallback(async (units: Unit[], activeUnitId?: number) => {
    if (!boardRef.current || !scenario) {
      throw new Error('Missing board reference or scenario data');
    }

    // Check if PIXI app is valid before starting
    if (!isPixiAppValid()) {
      console.log('PIXI app is invalid, skipping draw');
      return;
    }

    console.log(`Drawing board with ${units.length} units:`, units);
    
    const app = appRef.current!;
    const { board, colors } = scenario;
    
    try {
      // Check stage exists before clearing
      if (!app.stage) {
        console.warn('PIXI stage is null, cannot draw');
        return;
      }

      // Clear stage safely
      app.stage.removeChildren();

      // Draw hex grid
      for (let col = 0; col < board.cols; col++) {
        for (let row = 0; row < board.rows; row++) {
          const center = getHexCenter(col, row);
          const points = getHexPolygonPoints(center.x, center.y, board.hex_radius);
          
          const cell = new PIXI.Graphics();
          cell.lineStyle(1, parseInt(colors.cell_border), 0.3);
          cell.beginFill((col + row) % 2 === 0 ? parseInt(colors.cell_even) : parseInt(colors.cell_odd), 0.2);
          cell.drawPolygon(points);
          cell.endFill();
          
          app.stage.addChild(cell);
        }
      }

      // Clear old unit sprites
      unitSpritesRef.current.clear();

      // Draw units
      for (const unit of units) {
        if (!unit.alive || (unit.CUR_HP ?? unit.HP_MAX) <= 0) {
          continue;
        }

        console.log(`Drawing unit ${unit.name} at (${unit.col}, ${unit.row})`);
        const center = getHexCenter(unit.col, unit.row);
        
        const unitContainer = new PIXI.Container();
        
        // Unit background circle
        const unitCircle = new PIXI.Graphics();
        unitCircle.beginFill(unit.color, 0.8);
        unitCircle.lineStyle(3, 0xffffff, 1);
        unitCircle.drawCircle(0, 0, board.hex_radius * 0.6);
        unitCircle.endFill();
        unitContainer.addChild(unitCircle);
        
        // Add active unit highlight
        if (activeUnitId === unit.id) {
          const highlight = new PIXI.Graphics();
          highlight.lineStyle(4, 0xffff00, 0.8);
          highlight.drawCircle(0, 0, board.hex_radius * 0.7);
          highlight.endFill();
          unitContainer.addChild(highlight);
        }
        
        // Unit name text
        const unitText = new PIXI.Text(unit.name, {
          fontSize: 16,
          fill: 0xffffff,
          align: 'center',
          stroke: 0x000000,
          strokeThickness: 3,
          fontWeight: 'bold'
        });
        unitText.anchor.set(0.5);
        unitContainer.addChild(unitText);
        
        // HP text
        const hpText = new PIXI.Text(`${unit.CUR_HP}/${unit.HP_MAX}`, {
          fontSize: 12,
          fill: unit.CUR_HP < unit.HP_MAX ? 0xff4444 : 0x44ff44,
          align: 'center',
          stroke: 0x000000,
          strokeThickness: 2
        });
        hpText.anchor.set(0.5);
        hpText.position.set(0, board.hex_radius * 0.8);
        unitContainer.addChild(hpText);
        
        // Position the unit container
        unitContainer.position.set(center.x, center.y);
        app.stage.addChild(unitContainer);
        unitSpritesRef.current.set(unit.id, unitContainer);
      }
      
      console.log(`Board drawn with ${app.stage.children.length} PIXI objects`);
    } catch (drawError) {
      console.error('Error during board drawing:', drawError);
      throw drawError;
    }
  }, [scenario, getHexCenter, getHexPolygonPoints, isPixiAppValid]);

  // Update the display for current step
  const updateDisplay = useCallback(async () => {
    if (!replayData || !replayData.events || replayData.events.length === 0) {
      console.log('No replay data to display');
      return;
    }
    if (currentStep >= replayData.events.length) {
      console.log('Current step exceeds replay length');
      return;
    }

    const currentEvent = replayData.events[currentStep];
    if (!currentEvent) {
      console.log('No event at current step');
      return;
    }

    if (!isPixiAppValid()) {
      console.log('PIXI app invalid, skipping update');
      return;
    }

    const units = convertUnits(currentEvent);
    await drawBoard(units, currentEvent.acting_unit_idx);
  }, [replayData, currentStep, convertUnits, drawBoard, isPixiAppValid]);

  // Load replay data
  useEffect(() => {
    const loadReplayData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        console.log('Loading scenario from /ai/scenario.json...');
        const scenarioData = await loadScenario();
        console.log('Scenario loaded:', scenarioData);
        
        console.log(`Loading replay from /${replayFile}...`);
        const response = await fetch(`/${replayFile}`);
        if (!response.ok) {
          throw new Error(`Failed to load replay file: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('Replay data loaded:', data);
        setReplayData(data);
        setCurrentStep(0);
        
      } catch (err) {
        console.error('Error loading replay:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    loadReplayData();
  }, [replayFile, loadScenario]);

  // Initialize PIXI application with WebGL protection
  useEffect(() => {
    if (!boardRef.current || !scenario || appRef.current) return;

    // Load board configuration following AI_INSTRUCTIONS.md - NO HARDCODED VALUES
    const boardConfig = await fetch('/config/board_config.json')
      .then(res => res.json())
      .then(data => data.default);
    
    if (!boardConfig) {
      throw new Error('Board configuration not loaded - violates AI_INSTRUCTIONS.md');
    }

    const { board } = scenario;
    const BOARD_COLS = boardConfig.cols;
    const BOARD_ROWS = boardConfig.rows;
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;

    const boardWidth = BOARD_COLS * HEX_HORIZ_SPACING + MARGIN * 2;
    const boardHeight = BOARD_ROWS * HEX_VERT_SPACING + MARGIN * 2;

    console.log('Creating PIXI application with size:', boardWidth, 'x', boardHeight);

    try {
      // Force Canvas renderer to avoid WebGL instability
      const app = new PIXI.Application({
        width: boardWidth,
        height: boardHeight,
        backgroundColor: parseInt(scenario.colors.board_bg),
        antialias: true,
        resolution: window.devicePixelRatio || 1,
        autoDensity: true,
        forceCanvas: true // Force Canvas rendering instead of WebGL
      });

      console.log('PIXI application created with Canvas renderer');

      const appCanvas = app.view as HTMLCanvasElement;
      
      // Ensure canvas fits properly
      appCanvas.style.display = 'block';
      appCanvas.style.maxWidth = '100%';
      appCanvas.style.height = 'auto';
      appCanvas.style.border = '1px solid #333';

      boardRef.current.appendChild(appCanvas);
      appRef.current = app;

      console.log('PIXI application created and added to DOM');

      // Draw immediately without delay since Canvas is more stable
      if (replayData && replayData.events && replayData.events.length > 0) {
        console.log('Drawing initial board with replay data');
        const initialEvent = replayData.events[0];
        const initialUnits = convertUnits(initialEvent);
        drawBoard(initialUnits).catch(err => {
          console.error('Error drawing initial board:', err);
          setError(err instanceof Error ? err.message : 'Unknown board drawing error');
        });
      }

    } catch (initError) {
      console.error('Failed to initialize PIXI application:', initError);
      // Create fallback HTML rendering
      createFallbackRenderer(boardWidth, boardHeight);
    }

    return () => {
      if (appRef.current) {
        try {
          appRef.current.destroy(true);
        } catch (destroyError) {
          console.warn('Error destroying PIXI app:', destroyError);
        }
        appRef.current = null;
      }
      isWebGLLostRef.current = false;
    };
  }, [scenario, replayData, convertUnits, drawBoard, isPixiAppValid]);

  // Fallback renderer when PIXI fails
  const createFallbackRenderer = useCallback((width: number, height: number) => {
    if (!boardRef.current) return;

    boardRef.current.innerHTML = `
      <div style="
        width: ${width}px; 
        height: ${height}px; 
        background: #001122; 
        border: 2px solid #004488;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #ffffff;
        font-family: monospace;
        font-size: 16px;
        text-align: center;
        position: relative;
      ">
        <div>
          <div style="margin-bottom: 20px;">🎮 WH40K Replay Viewer</div>
          <div style="font-size: 12px; color: #aaaaaa;">
            WebGL not available - using fallback mode<br/>
            Step: ${currentStep + 1} / ${replayData?.events.length || 0}<br/>
            <button onclick="window.location.reload()" style="
              margin-top: 10px;
              padding: 8px 16px;
              background: #004488;
              color: white;
              border: 1px solid #0066cc;
              border-radius: 4px;
              cursor: pointer;
            ">Retry with WebGL</button>
          </div>
        </div>
      </div>
    `;
  }, [currentStep, replayData]);

  // Update display when step changes (simplified for Canvas)
  useEffect(() => {
    const handleDisplayUpdate = async () => {
      if (replayData && scenario && isPixiAppValid()) {
        try {
          await updateDisplay();
        } catch (err) {
          console.error('Error updating display:', err);
          setError(err instanceof Error ? err.message : 'Unknown display error');
        }
      }
    };

    handleDisplayUpdate();
  }, [currentStep, replayData, scenario, updateDisplay, isPixiAppValid]);

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

  // Get metadata from either location
  const metadata = replayData.metadata || replayData.game_summary;
  const totalReward = (metadata as any)?.episode_reward ?? (metadata as any)?.final_reward ?? 0;
  const totalTurns = (metadata as any)?.final_turn ?? (metadata as any)?.total_turns ?? replayData.events.length;

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-6 text-center">WH40K Game Replay</h1>
        
        {/* Game board */}
        <div className="mb-6 flex justify-center">
          <div 
            ref={boardRef} 
            className="border border-gray-700 rounded-lg overflow-hidden bg-gray-800"
            style={{ maxWidth: '100%' }}
          />
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
              {replayData.events[currentStep] && (
                <>
                  <div>Turn: {replayData.events[currentStep].turn ?? 'N/A'}</div>
                  <div>Action: {replayData.events[currentStep].action ?? 'N/A'}</div>
                  <div>Reward: {replayData.events[currentStep].reward?.toFixed(2) ?? 'N/A'}</div>
                </>
              )}
            </div>
          </div>
        </div>

        {/* WebGL status indicator */}
        {isWebGLLostRef.current && (
          <div className="bg-yellow-900 border border-yellow-700 rounded-lg p-4 mb-6">
            <div className="flex items-center gap-2">
              <span className="text-yellow-400">⚠️</span>
              <span>WebGL context lost. Some features may not work correctly.</span>
              <button 
                onClick={refreshViewer}
                className="ml-auto px-3 py-1 bg-yellow-600 hover:bg-yellow-700 rounded text-sm transition-colors"
              >
                Refresh
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};