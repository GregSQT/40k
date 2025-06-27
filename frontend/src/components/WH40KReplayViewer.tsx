import React, { useState, useEffect, useCallback, useRef } from 'react';

// Types matching your existing codebase
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
  CUR_HP?: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON?: string;
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

// WH40K Replay Viewer with PIXI.js Canvas + HTML Fallback
export default function WH40KReplayViewer() {
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [scenario, setScenario] = useState<ScenarioConfig | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentUnits, setCurrentUnits] = useState<Unit[]>([]);
  const [renderMode, setRenderMode] = useState<'pixi-canvas' | 'html-fallback'>('pixi-canvas');
  
  const boardRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<any>(null);

  // Load actual data from your project files
  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Load scenario from your actual file
      console.log('Loading scenario from /ai/scenario.json...');
      const scenarioResponse = await fetch('/ai/scenario.json');
      if (!scenarioResponse.ok) {
        throw new Error(`Failed to load scenario: ${scenarioResponse.statusText}`);
      }
      const scenarioData = await scenarioResponse.json();
      setScenario(scenarioData);
      console.log('Scenario loaded:', scenarioData);
      
      // Load replay data from your actual file
      console.log('Loading replay from /ai/event_log/train_best_game_replay.json...');
      const replayResponse = await fetch('/ai/event_log/train_best_game_replay.json');
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
  }, []);

  // Convert replay event to units (matching your existing logic)
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

    // Otherwise reconstruct from scenario + event counts (your existing logic)
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

  // PIXI.js Canvas Renderer (NO WebGL) - uses your scenario configuration
  const renderWithPixiCanvas = useCallback(() => {
    if (!boardRef.current || !scenario) return false;

    try {
      // Clear previous content
      boardRef.current.innerHTML = '';

      const { board, colors } = scenario;
      const HEX_WIDTH = 1.5 * board.hex_radius;
      const HEX_HEIGHT = Math.sqrt(3) * board.hex_radius;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;

      const boardWidth = board.cols * HEX_HORIZ_SPACING + board.margin * 2;
      const boardHeight = board.rows * HEX_VERT_SPACING + board.margin * 2;

      // Check if PIXI is available
      const PIXI = (window as any).PIXI;
      if (!PIXI) {
        throw new Error('PIXI.js not available');
      }

      // Create PIXI app with FORCED Canvas rendering (no WebGL)
      const app = new PIXI.Application({
        width: boardWidth,
        height: boardHeight,
        backgroundColor: parseInt(colors.board_bg),
        antialias: true,
        resolution: window.devicePixelRatio || 1,
        autoDensity: true,
        forceCanvas: true, // 🔥 FORCE Canvas mode - NO WebGL!
        powerPreference: 'low-power' // Additional WebGL avoidance
      });

      console.log('PIXI Canvas renderer initialized successfully');

      // Ensure canvas styling
      const canvas = app.view as HTMLCanvasElement;
      canvas.style.display = 'block';
      canvas.style.maxWidth = '100%';
      canvas.style.height = 'auto';
      canvas.style.border = '2px solid #00ff00';

      boardRef.current.appendChild(canvas);
      pixiAppRef.current = app;

      // Helper functions for hex grid (using your scenario config)
      const getHexCenter = (col: number, row: number) => {
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + board.margin;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + board.margin;
        return { x: centerX, y: centerY };
      };

      const getHexPolygonPoints = (cx: number, cy: number, radius: number) => {
        const points = [];
        for (let i = 0; i < 6; i++) {
          const angle_deg = 60 * i;
          const angle_rad = Math.PI / 180 * angle_deg;
          points.push(cx + radius * Math.cos(angle_rad));
          points.push(cy + radius * Math.sin(angle_rad));
        }
        return points;
      };

      // Draw hex grid background using your board configuration
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

      // Draw units using your current units state
      currentUnits.forEach(unit => {
        if (!unit.alive || (unit.CUR_HP ?? 0) <= 0) return;

        const center = getHexCenter(unit.col, unit.row);
        const isSelected = replayData?.events[currentStep]?.acting_unit_idx === unit.id;

        // Unit circle
        const unitCircle = new PIXI.Graphics();
        unitCircle.lineStyle(2, unit.color);
        unitCircle.beginFill(unit.color, 0.8);
        unitCircle.drawCircle(center.x, center.y, board.hex_radius * 0.6);
        unitCircle.endFill();

        // Selection highlight
        if (isSelected) {
          unitCircle.lineStyle(3, parseInt(colors.current_unit));
          unitCircle.drawCircle(center.x, center.y, board.hex_radius * 0.8);
        }
        
        app.stage.addChild(unitCircle);

        // Unit label
        const label = new PIXI.Text(unit.name, {
          fontSize: 12,
          fill: 0xffffff,
          fontWeight: 'bold',
          align: 'center'
        });
        label.anchor.set(0.5);
        label.position.set(center.x, center.y);
        app.stage.addChild(label);

        // HP bar using your color scheme
        const hpWidth = board.hex_radius * 1.2;
        const hpRatio = (unit.CUR_HP ?? unit.HP_MAX) / unit.HP_MAX;
        
        const hpBg = new PIXI.Graphics();
        hpBg.beginFill(parseInt(colors.hp_damaged));
        hpBg.drawRect(center.x - hpWidth/2, center.y + board.hex_radius * 0.8, hpWidth, 4);
        hpBg.endFill();
        app.stage.addChild(hpBg);
        
        const hpFill = new PIXI.Graphics();
        hpFill.beginFill(parseInt(colors.hp_full));
        hpFill.drawRect(center.x - hpWidth/2, center.y + board.hex_radius * 0.8, hpWidth * hpRatio, 4);
        hpFill.endFill();
        app.stage.addChild(hpFill);

        // HP text
        const hpText = new PIXI.Text(`${unit.CUR_HP ?? unit.HP_MAX}/${unit.HP_MAX}`, {
          fontSize: 8,
          fill: 0xffffff,
          align: 'center'
        });
        hpText.anchor.set(0.5);
        hpText.position.set(center.x, center.y + board.hex_radius * 1.1);
        app.stage.addChild(hpText);
      });

      console.log(`PIXI Canvas board rendered with ${currentUnits.length} units`);
      return true;
    } catch (error) {
      console.error('PIXI Canvas rendering failed:', error);
      return false;
    }
  }, [scenario, currentUnits, replayData, currentStep]);

  // HTML/CSS Fallback Renderer (uses your scenario configuration)
  const renderWithHTML = useCallback(() => {
    if (!boardRef.current || !scenario) return false;

    try {
      const { board } = scenario;
      const cellSize = board.hex_radius * 1.5;
      const boardWidth = board.cols * cellSize * 0.75 + cellSize;
      const boardHeight = board.rows * cellSize * 0.87 + cellSize;
      
      boardRef.current.innerHTML = `
        <div style="
          position: relative;
          width: ${boardWidth}px;
          height: ${boardHeight}px;
          background: #002200;
          border: 2px solid #00ff00;
          overflow: hidden;
          margin: 0 auto;
        ">
          <!-- Hex grid background -->
          <svg width="100%" height="100%" style="position: absolute; z-index: 1;">
            <defs>
              <pattern id="hexGrid" x="0" y="0" width="${cellSize * 0.75}" height="${cellSize * 0.87}" patternUnits="userSpaceOnUse">
                <polygon
                  points="${board.hex_radius/2},0 ${board.hex_radius},${board.hex_radius/4} ${board.hex_radius},${board.hex_radius*3/4} ${board.hex_radius/2},${board.hex_radius} 0,${board.hex_radius*3/4} 0,${board.hex_radius/4}"
                  fill="none"
                  stroke="#004400"
                  stroke-width="1"
                  opacity="0.3"
                />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#hexGrid)" />
          </svg>
          
          <!-- Units -->
          ${currentUnits.filter(unit => unit.alive && (unit.CUR_HP ?? 0) > 0).map(unit => {
            const x = unit.col * cellSize * 0.75;
            const y = unit.row * cellSize * 0.87 + (unit.col % 2) * cellSize * 0.43;
            const color = unit.player === 0 ? '#244488' : '#882222';
            const isSelected = replayData?.events[currentStep]?.acting_unit_idx === unit.id;
            
            return `
              <div style="
                position: absolute;
                left: ${x}px;
                top: ${y}px;
                width: ${cellSize}px;
                height: ${cellSize}px;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.5s ease;
                z-index: 10;
              ">
                <div style="
                  width: ${board.hex_radius * 1.2}px;
                  height: ${board.hex_radius * 1.2}px;
                  background: ${color};
                  border-radius: 50%;
                  display: flex;
                  flex-direction: column;
                  align-items: center;
                  justify-content: center;
                  color: white;
                  font-weight: bold;
                  font-size: 10px;
                  border: ${isSelected ? '3px solid #ffd700' : '2px solid ' + color};
                  box-shadow: ${isSelected ? '0 0 10px #ffd700' : 'none'};
                ">
                  <div>${unit.name}</div>
                  <div style="font-size: 8px;">${unit.CUR_HP ?? unit.HP_MAX}/${unit.HP_MAX}</div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;

      console.log(`HTML fallback board rendered with ${currentUnits.length} units`);
      return true;
    } catch (error) {
      console.error('HTML rendering failed:', error);
      return false;
    }
  }, [scenario, currentUnits, replayData, currentStep]);

  // Smart rendering with automatic fallback
  useEffect(() => {
    let success = false;
    
    if (renderMode === 'pixi-canvas') {
      success = renderWithPixiCanvas();
      if (!success) {
        console.log('PIXI Canvas failed, falling back to HTML');
        setRenderMode('html-fallback');
      }
    }
    
    if (renderMode === 'html-fallback' || !success) {
      renderWithHTML();
    }

    return () => {
      if (pixiAppRef.current) {
        try {
          pixiAppRef.current.destroy();
          pixiAppRef.current = null;
        } catch (e) {
          console.warn('Error destroying PIXI app:', e);
        }
      }
    };
  }, [currentUnits, renderMode, renderWithPixiCanvas, renderWithHTML]);

  // Update units when step changes (using your existing logic)
  useEffect(() => {
    if (replayData && scenario && replayData.events[currentStep]) {
      const event = replayData.events[currentStep];
      const units = convertEventToUnits(event, scenario);
      setCurrentUnits(units);
      console.log(`Step ${currentStep + 1}: Updated units`, units);
    }
  }, [currentStep, replayData, scenario, convertEventToUnits]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData && currentStep < replayData.events.length - 1) {
      const timer = setTimeout(() => {
        setCurrentStep(prev => prev + 1);
      }, playSpeed);
      return () => clearTimeout(timer);
    } else if (isPlaying) {
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

  // Initialize data loading
  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-center">
          <div className="animate-spin rounded-full h-16 w-16 border-b-2 border-green-500 mx-auto mb-4"></div>
          <div className="text-lg">Loading WH40K replay data...</div>
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
            onClick={() => loadData()}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded transition-colors"
          >
            Retry Loading
          </button>
        </div>
      </div>
    );
  }

  if (!replayData || !scenario) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900 text-white">
        <div className="text-red-500">Missing required data</div>
      </div>
    );
  }

  const currentEvent = replayData.events[currentStep];
  const metadata = replayData.metadata || replayData.game_summary;
  const totalReward = metadata?.episode_reward ?? metadata?.final_reward ?? 0;
  const totalTurns = metadata?.final_turn ?? metadata?.total_turns ?? replayData.events.length;

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-6 text-center text-green-400">
          ⚔️ WH40K Replay Viewer
        </h1>

        {/* Render mode indicator */}
        <div className="mb-4 text-center">
          <span className={`px-3 py-1 rounded text-sm ${
            renderMode === 'pixi-canvas' ? 'bg-green-600' : 'bg-yellow-600'
          }`}>
            {renderMode === 'pixi-canvas' ? '🎨 PIXI.js Canvas' : '📄 HTML Fallback'}
          </span>
          <div className="text-xs text-gray-400 mt-1">
            Automatic WebGL-free rendering • Board: {scenario.board.cols}×{scenario.board.rows}
          </div>
        </div>
        
        {/* Game board */}
        <div className="mb-6 flex justify-center">
          <div ref={boardRef} className="rounded" />
        </div>

        {/* Controls */}
        <div className="mb-6 flex flex-wrap items-center justify-center gap-4">
          <button onClick={reset} className="px-4 py-2 bg-gray-600 hover:bg-gray-700 rounded transition-colors">
            ⏮️ Reset
          </button>
          <button onClick={prevStep} disabled={currentStep === 0} 
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors">
            ⏪ Previous
          </button>
          <button onClick={isPlaying ? pause : play}
                  disabled={currentStep >= replayData.events.length - 1}
                  className="px-6 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-800 disabled:cursor-not-allowed rounded transition-colors">
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
          <div className="bg-gray-800 p-4 rounded border border-green-500">
            <h3 className="text-lg font-semibold mb-2 text-green-400">Progress</h3>
            <div className="text-sm">
              Step: {currentStep + 1} / {replayData.events.length}
              <div className="w-full bg-gray-700 rounded-full h-2 mt-2">
                <div className="bg-green-600 h-2 rounded-full transition-all duration-300"
                     style={{ width: `${((currentStep + 1) / replayData.events.length) * 100}%` }} />
              </div>
            </div>
          </div>
          
          <div className="bg-gray-800 p-4 rounded border border-green-500">
            <h3 className="text-lg font-semibold mb-2 text-green-400">Game Info</h3>
            <div className="text-sm space-y-1">
              <div>Total Reward: {totalReward.toFixed(2)}</div>
              <div>Total Turns: {totalTurns}</div>
            </div>
          </div>

          <div className="bg-gray-800 p-4 rounded border border-green-500">
            <h3 className="text-lg font-semibold mb-2 text-green-400">Current Event</h3>
            <div className="text-sm space-y-1">
              <div>Turn: {currentEvent?.turn ?? 'N/A'}</div>
              <div>Action: {currentEvent?.action ?? 'N/A'}</div>
              <div>Reward: {currentEvent?.reward?.toFixed(2) ?? 'N/A'}</div>
            </div>
          </div>
        </div>

        {/* Units status */}
        <div className="bg-gray-800 p-4 rounded border border-green-500">
          <h3 className="text-lg font-semibold mb-2 text-green-400">Units Status</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
            {currentUnits.map((unit) => (
              <div 
                key={unit.id}
                className={`p-2 rounded ${
                  unit.alive ? 'bg-green-900 border border-green-600' : 'bg-red-900 border border-red-600'
                } ${
                  currentEvent?.acting_unit_idx === unit.id ? 'ring-2 ring-yellow-400' : ''
                }`}
              >
                <div className="font-bold">{unit.name}</div>
                <div>HP: {unit.CUR_HP}/{unit.HP_MAX}</div>
                <div>Pos: ({unit.col}, {unit.row})</div>
                <div className="text-xs opacity-75">{unit.type}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}