// frontend/src/components/GameReplayViewer.tsx
import React, { useState, useEffect, useRef, useCallback } from 'react';
import * as PIXI from 'pixi.js';
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

// Unit type registry - imports the actual unit classes to get their static properties
const UNIT_REGISTRY = {
  'Intercessor': Intercessor,
  'AssaultIntercessor': AssaultIntercessor
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

  // Convert units from scenario/replay format to display format
  const convertUnits = useCallback((event: ReplayEvent): Unit[] => {
    if (!scenario) {
      throw new Error('Scenario not loaded');
    }

    console.log('Converting units from event:', event);

    // If the event has full unit data, use it
    if (event.units && event.units.length > 0) {
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

    // Otherwise, reconstruct from scenario and event data
    if (!scenario.units || scenario.units.length === 0) {
      throw new Error('No units defined in scenario');
    }

    console.log('Reconstructing units from scenario and event data');
    
    // Use provided alive counts, or assume all alive if not provided
    const aiAlive = event.ai_units_alive ?? 2;
    const playerAlive = event.enemy_units_alive ?? 2;

    console.log(`AI units alive: ${aiAlive}, Player units alive: ${playerAlive}`);

    return scenario.units.map((scenarioUnit, index) => {
      if (!scenarioUnit.unit_type) {
        throw new Error(`Scenario unit ${scenarioUnit.id} missing unit_type`);
      }
      if (scenarioUnit.player === undefined || scenarioUnit.player === null) {
        throw new Error(`Scenario unit ${scenarioUnit.id} missing player`);
      }
      if (scenarioUnit.col === undefined || scenarioUnit.col === null) {
        throw new Error(`Scenario unit ${scenarioUnit.id} missing col`);
      }
      if (scenarioUnit.row === undefined || scenarioUnit.row === null) {
        throw new Error(`Scenario unit ${scenarioUnit.id} missing row`);
      }

      const stats = getUnitStats(scenarioUnit.unit_type);
      const isAlive = scenarioUnit.player === 1 ? 
        (index - 2 < aiAlive) : 
        (index < playerAlive);

      const unit = {
        id: scenarioUnit.id,
        name: `${scenarioUnit.player === 0 ? 'P' : 'A'}-${scenarioUnit.unit_type.charAt(0)}`,
        type: scenarioUnit.unit_type,
        player: scenarioUnit.player as 0 | 1,
        col: scenarioUnit.col,
        row: scenarioUnit.row,
        color: parseInt(scenarioUnit.player === 0 ? scenario.colors.player_0 : scenario.colors.player_1),
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

  // Draw the game board
  const drawBoard = useCallback(async (units: Unit[], activeUnitId?: number) => {
    if (!boardRef.current || !appRef.current || !scenario) {
      throw new Error('Missing board reference, PIXI app, or scenario data');
    }

    console.log(`Drawing board with ${units.length} units:`, units);
    
    const app = appRef.current;
    const { board, colors } = scenario;
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
        console.log(`Skipping dead unit:`, unit);
        continue;
      }

      console.log(`Drawing unit ${unit.name} at (${unit.col}, ${unit.row})`);
      
      const center = getHexCenter(unit.col, unit.row);
      const unitContainer = new PIXI.Container();
      
      // Unit background circle
      const background = new PIXI.Graphics();
      background.lineStyle(2, unit.color, 1);
      background.beginFill(unit.color, 0.3);
      background.drawCircle(0, 0, board.hex_radius * 0.8);
      background.endFill();
      
      // Highlight active unit
      if (activeUnitId === unit.id) {
        background.lineStyle(3, parseInt(colors.current_unit), 1);
        background.beginFill(parseInt(colors.current_unit), 0.2);
        background.drawCircle(0, 0, board.hex_radius * 0.9);
        background.endFill();
      }
      
      unitContainer.addChild(background);
      
      // Unit icon/sprite - try to load icon, fallback to text
      try {
        const texture = await PIXI.Assets.load(unit.ICON);
        const sprite = new PIXI.Sprite(texture);
        sprite.anchor.set(0.5);
        sprite.width = board.hex_radius * 1.2;
        sprite.height = board.hex_radius * 1.2;
        sprite.position.set(0, -5);
        unitContainer.addChild(sprite);
        console.log(`Loaded icon for unit ${unit.name}`);
      } catch (iconError) {
        console.warn(`Failed to load icon for unit ${unit.name}, using fallback text`);
        // Fallback to text if icon fails to load
        const nameText = new PIXI.Text(unit.name, {
          fontSize: 12,
          fill: 0xffffff,
          align: 'center'
        });
        nameText.anchor.set(0.5);
        nameText.position.set(0, -8);
        unitContainer.addChild(nameText);
      }
      
      // HP bar background
      const hpBarWidth = board.hex_radius * 1.4;
      const hpBarHeight = 6;
      const hpRatio = unit.CUR_HP / unit.HP_MAX;
      
      // HP background
      const hpBg = new PIXI.Graphics();
      hpBg.beginFill(parseInt(colors.hp_damaged));
      hpBg.drawRect(-hpBarWidth / 2, board.hex_radius * 0.6, hpBarWidth, hpBarHeight);
      hpBg.endFill();
      unitContainer.addChild(hpBg);
      
      // HP fill
      const hpFill = new PIXI.Graphics();
      hpFill.beginFill(parseInt(colors.hp_full));
      hpFill.drawRect(-hpBarWidth / 2, board.hex_radius * 0.6, hpBarWidth * hpRatio, hpBarHeight);
      hpFill.endFill();
      unitContainer.addChild(hpFill);
      
      // HP text
      const hpText = new PIXI.Text(`${unit.CUR_HP}/${unit.HP_MAX}`, {
        fontSize: 10,
        fill: 0xffffff,
        align: 'center',
        stroke: 0x000000,
        strokeThickness: 2
      });
      hpText.anchor.set(0.5);
      hpText.position.set(0, board.hex_radius * 0.8);
      unitContainer.addChild(hpText);
      
      // Unit name below HP
      const nameText = new PIXI.Text(unit.name, {
        fontSize: 8,
        fill: 0xffffff,
        align: 'center',
        stroke: 0x000000,
        strokeThickness: 1
      });
      nameText.anchor.set(0.5);
      nameText.position.set(0, board.hex_radius * 1.0);
      unitContainer.addChild(nameText);
      
      // Position the unit container
      unitContainer.position.set(center.x, center.y);
      app.stage.addChild(unitContainer);
      
      // Store reference for animations
      unitSpritesRef.current.set(unit.id, unitContainer);
    }
    
    console.log(`Board drawn with ${app.stage.children.length} PIXI objects`);
  }, [scenario, getHexCenter, getHexPolygonPoints]);

  // Animate unit movement
  const animateUnitMovement = useCallback((unitId: number, fromCol: number, fromRow: number, toCol: number, toRow: number) => {
    const unitSprite = unitSpritesRef.current.get(unitId);
    if (!unitSprite || !scenario) {
      throw new Error(`Cannot animate unit ${unitId}: missing sprite or scenario`);
    }

    const fromCenter = getHexCenter(fromCol, fromRow);
    const toCenter = getHexCenter(toCol, toRow);
    
    return new Promise<void>((resolve) => {
      const duration = 800; // milliseconds for smooth movement
      const startTime = Date.now();
      
      const animate = () => {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        // Smooth easing function (ease-in-out)
        const eased = progress < 0.5 
          ? 2 * progress * progress 
          : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        
        // Update position
        unitSprite.position.x = fromCenter.x + (toCenter.x - fromCenter.x) * eased;
        unitSprite.position.y = fromCenter.y + (toCenter.y - fromCenter.y) * eased;
        
        // Add slight bounce effect
        const bounceHeight = Math.sin(progress * Math.PI) * 10;
        unitSprite.position.y -= bounceHeight;
        
        if (progress < 1) {
          requestAnimationFrame(animate);
        } else {
          // Ensure final position is exact
          unitSprite.position.x = toCenter.x;
          unitSprite.position.y = toCenter.y;
          resolve();
        }
      };
      
      animate();
    });
  }, [scenario, getHexCenter]);

  // Update the display for current step
  const updateDisplay = useCallback(async () => {
    if (!replayData) {
      throw new Error('No replay data loaded');
    }
    if (!replayData.events || replayData.events.length === 0) {
      throw new Error('Replay data contains no events');
    }
    if (currentStep >= replayData.events.length) {
      throw new Error(`Current step ${currentStep} exceeds replay events length ${replayData.events.length}`);
    }

    const currentEvent = replayData.events[currentStep];
    if (!currentEvent) {
      throw new Error(`No event found at step ${currentStep}`);
    }

    const units = convertUnits(currentEvent);
    
    // Check if this is a movement action by comparing with previous step
    let animationPromise = Promise.resolve();
    if (currentStep > 0) {
      const prevEvent = replayData.events[currentStep - 1];
      if (!prevEvent) {
        throw new Error(`No previous event found at step ${currentStep - 1}`);
      }
      const prevUnits = convertUnits(prevEvent);
      
      // Find units that moved
      for (const unit of units) {
        const prevUnit = prevUnits.find((u: Unit) => u.id === unit.id);
        if (prevUnit && (prevUnit.col !== unit.col || prevUnit.row !== unit.row)) {
          animationPromise = animateUnitMovement(unit.id, prevUnit.col, prevUnit.row, unit.col, unit.row);
        }
      }
    }
    
    await animationPromise;
    await drawBoard(units, currentEvent.acting_unit_idx);
  }, [replayData, currentStep, convertUnits, drawBoard, animateUnitMovement]);

  // Load replay data
  useEffect(() => {
    const loadReplayData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        console.log('Loading scenario from /ai/scenario.json...');
        // Load scenario first
        const scenarioData = await loadScenario();
        console.log('Scenario loaded:', scenarioData);
        
        console.log(`Loading replay from /${replayFile}...`);
        // Load replay data
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

  // Initialize PIXI application and draw initial board
  useEffect(() => {
    if (!boardRef.current || !scenario || appRef.current) return;

    const { board } = scenario;
    const HEX_WIDTH = 1.5 * board.hex_radius;
    const HEX_HEIGHT = Math.sqrt(3) * board.hex_radius;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;

    const boardWidth = board.cols * HEX_HORIZ_SPACING + board.margin * 2;
    const boardHeight = board.rows * HEX_VERT_SPACING + board.margin * 2;

    if (!scenario.colors.board_bg) {
      throw new Error('Missing board_bg color in scenario colors');
    }

    const app = new PIXI.Application({
      width: boardWidth,
      height: boardHeight,
      backgroundColor: parseInt(scenario.colors.board_bg),
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true
    });

    // Ensure canvas fits properly
    const canvas = app.view as HTMLCanvasElement;
    canvas.style.display = 'block';
    canvas.style.maxWidth = '100%';
    canvas.style.height = 'auto';

    boardRef.current.appendChild(canvas);
    appRef.current = app;

    // Draw initial board if we have replay data
    if (replayData && replayData.events && replayData.events.length > 0) {
      const initialEvent = replayData.events[0];
      const initialUnits = convertUnits(initialEvent);
      drawBoard(initialUnits).catch(err => {
        console.error('Error drawing initial board:', err);
        setError(err instanceof Error ? err.message : 'Unknown board drawing error');
      });
    }

    return () => {
      if (appRef.current) {
        appRef.current.destroy(true);
        appRef.current = null;
      }
    };
  }, [scenario, replayData, convertUnits, drawBoard]);

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

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">Loading replay...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-500">Error: {error}</div>
      </div>
    );
  }

  if (!replayData || !scenario) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-500">
          Missing required data: {!replayData ? 'replay data' : ''} {!scenario ? 'scenario configuration' : ''}
        </div>
      </div>
    );
  }

  if (!replayData.events || replayData.events.length === 0) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-500">No replay events found in data</div>
      </div>
    );
  }

  // Get metadata from either location
  const metadata = replayData.metadata || replayData.game_summary;
  const totalReward = (metadata as any)?.episode_reward ?? (metadata as any)?.final_reward ?? 0;
  const totalTurns = (metadata as any)?.final_turn ?? (metadata as any)?.total_turns ?? replayData.events.length;

  const currentEvent = replayData.events[currentStep];

  return (
    <div className="flex flex-col items-center p-4 bg-gray-900 min-h-screen">
      <h1 className="text-2xl font-bold text-white mb-4">Training Replay Viewer</h1>
      
      {/* Replay info */}
      <div className="text-white mb-4 text-center">
        <div>Total Reward: {totalReward.toFixed(2)}</div>
        <div>Total Turns: {totalTurns}</div>
        <div>Step: {currentStep + 1} / {replayData.events.length}</div>
        {currentEvent && (
          <div>
            Turn: {currentEvent.turn ?? 'N/A'} | 
            Action: {currentEvent.action ?? 'N/A'} | 
            Reward: {currentEvent.reward?.toFixed(2) ?? 'N/A'}
          </div>
        )}
      </div>

      {/* Game board */}
      <div ref={boardRef} className="border border-gray-600 mb-4" />

      {/* Controls */}
      <div className="flex items-center gap-4 bg-gray-800 p-4 rounded">
        <button
          onClick={reset}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Reset
        </button>
        <button
          onClick={prevStep}
          disabled={currentStep === 0}
          className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
        >
          Previous
        </button>
        <button
          onClick={isPlaying ? pause : play}
          className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
        >
          {isPlaying ? 'Pause' : 'Play'}
        </button>
        <button
          onClick={nextStep}
          disabled={currentStep === replayData.events.length - 1}
          className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50"
        >
          Next
        </button>
        
        <div className="flex items-center gap-2 text-white">
          <label>Speed:</label>
          <select
            value={playSpeed}
            onChange={(e) => setPlaySpeed(Number(e.target.value))}
            className="bg-gray-700 text-white rounded px-2 py-1"
          >
            <option value={2000}>Slow</option>
            <option value={1000}>Normal</option>
            <option value={500}>Fast</option>
            <option value={200}>Very Fast</option>
          </select>
        </div>
      </div>
    </div>
  );
};