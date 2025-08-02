// frontend/src/components/BoardReplay.tsx
import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as PIXI from 'pixi.js-legacy';
import { useGameConfig } from '../hooks/useGameConfig';
import type { Unit } from '../types/game';
import SharedLayout from './SharedLayout';
import { TurnPhaseTracker } from './TurnPhaseTracker';
import { UnitStatusTable } from './UnitStatusTable';
import { ErrorBoundary } from './ErrorBoundary';
import { renderUnit } from './UnitRenderer';
import { drawBoard } from './BoardDisplay';

// Pathfinding utilities for move preview (adapted from BoardPvp.tsx)
const offsetToCube = (col: number, row: number) => {
  const x = col;
  const z = row - ((col - (col & 1)) >> 1);
  const y = -x - z;
  return { x, y, z };
};

const cubeDistance = (a: { x: number; y: number; z: number }, b: { x: number; y: number; z: number }) => {
  return Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y), Math.abs(a.z - b.z));
};

const calculateMovePath = (fromCol: number, fromRow: number, toCol: number, toRow: number, maxMove: number, boardConfig: any, units: ReplayUnit[]): { col: number; row: number }[] => {
  if (!boardConfig) return [];
  
  const BOARD_COLS = boardConfig.cols;
  const BOARD_ROWS = boardConfig.rows;
  
  const visited = new Map<string, number>();
  const parent = new Map<string, string | null>();
  const queue: [number, number, number][] = [[fromCol, fromRow, 0]];
  
  // Use cube coordinate system for proper hex neighbors
  const cubeDirections = [
    [1, -1, 0], [1, 0, -1], [0, 1, -1], 
    [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
  ];
  
  // Collect forbidden hexes (walls + units)
  const forbiddenSet = new Set<string>();
  
  // Add wall hexes
  if (boardConfig.wall_hexes) {
    boardConfig.wall_hexes.forEach(([col, row]: [number, number]) => {
      forbiddenSet.add(`${col},${row}`);
    });
  }
  
  // Add unit positions (except the moving unit)
  units.forEach(unit => {
    if (unit.alive && !(unit.col === fromCol && unit.row === fromRow)) {
      forbiddenSet.add(`${unit.col},${unit.row}`);
    }
  });
  
  visited.set(`${fromCol},${fromRow}`, 0);
  parent.set(`${fromCol},${fromRow}`, null);
  
  while (queue.length > 0) {
    const [col, row, steps] = queue.shift()!;
    const key = `${col},${row}`;
    
    // Found destination
    if (col === toCol && row === toRow) {
      // Reconstruct path
      const path: { col: number; row: number }[] = [];
      let current: string | null = key;
      
      while (current !== null) {
        const [c, r] = current.split(',').map(Number);
        path.unshift({ col: c, row: r });
        current = parent.get(current) || null;
      }
      
      return path;
    }
    
    if (steps >= maxMove) continue;
    
    // Explore neighbors
    const currentCube = offsetToCube(col, row);
    for (const [dx, dy, dz] of cubeDirections) {
      const neighborCube = {
        x: currentCube.x + dx,
        y: currentCube.y + dy,
        z: currentCube.z + dz
      };
      
      const ncol = neighborCube.x;
      const nrow = neighborCube.z + ((neighborCube.x - (neighborCube.x & 1)) >> 1);
      const nkey = `${ncol},${nrow}`;
      const nextSteps = steps + 1;
      
      if (
        ncol >= 0 && ncol < BOARD_COLS &&
        nrow >= 0 && nrow < BOARD_ROWS &&
        nextSteps <= maxMove &&
        !forbiddenSet.has(nkey) &&
        (!visited.has(nkey) || visited.get(nkey)! > nextSteps)
      ) {
        visited.set(nkey, nextSteps);
        parent.set(nkey, key);
        queue.push([ncol, nrow, nextSteps]);
      }
    }
  }
  
  return []; // No path found
};

// Line of sight utilities for shooting preview (adapted from BoardPvp.tsx)
const getHexLine = (x0: number, y0: number, x1: number, y1: number) => {
  const hexes: { col: number; row: number }[] = [];
  const dx = Math.abs(x1 - x0);
  const dy = Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1;
  const sy = y0 < y1 ? 1 : -1;
  let err = dx - dy;
  let x = x0;
  let y = y0;

  while (true) {
    hexes.push({ col: x, row: y });
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 > -dy) {
      err -= dy;
      x += sx;
    }
    if (e2 < dx) {
      err += dx;
      y += sy;
    }
  }
  return hexes;
};

const hasLineOfSight = (
  from: { col: number; row: number },
  to: { col: number; row: number },
  wallHexes: [number, number][]
): { canSee: boolean; inCover: boolean } => {
  if (from.col === to.col && from.row === to.row) {
    return { canSee: true, inCover: false };
  }

  const lineHexes = getHexLine(from.col, from.row, to.col, to.row);
  const wallHexSet = new Set<string>(wallHexes.map(([c, r]) => `${c},${r}`));
  
  let hasWallInPath = false;
  let hasCover = false;

  // Check each hex in the line (excluding start and end)
  for (let i = 1; i < lineHexes.length - 1; i++) {
    const hex = lineHexes[i];
    const hexKey = `${hex.col},${hex.row}`;
    
    if (wallHexSet.has(hexKey)) {
      hasWallInPath = true;
      break;
    }
    
    // Check for units that could provide cover (would need unit positions)
    // For now, just check walls for cover detection
  }

  if (hasWallInPath) {
    return { canSee: false, inCover: false };
  }

  // Simple cover detection - if there are walls near the line but not blocking
  const pathLength = lineHexes.length;
  if (pathLength > 2) {
    // Check if there are walls adjacent to the path
    for (let i = 1; i < lineHexes.length - 1; i++) {
      const hex = lineHexes[i];
      // Check adjacent hexes for walls
      const adjacentOffsets = [[-1, 0], [1, 0], [0, -1], [0, 1], [-1, -1], [1, 1]];
      for (const [dx, dy] of adjacentOffsets) {
        const adjKey = `${hex.col + dx},${hex.row + dy}`;
        if (wallHexSet.has(adjKey)) {
          hasCover = true;
          break;
        }
      }
      if (hasCover) break;
    }
  }

  return { canSee: true, inCover: hasCover };
};

const calculateShootingTargets = (
  shooterCol: number,
  shooterRow: number,
  range: number,
  boardConfig: any,
  units: ReplayUnit[]
): {
  clearTargets: { col: number; row: number }[];
  coverTargets: { col: number; row: number }[];
  blockedTargets: Set<string>;
} => {
  const clearTargets: { col: number; row: number }[] = [];
  const coverTargets: { col: number; row: number }[] = [];
  const blockedTargets = new Set<string>();
  
  if (!boardConfig) return { clearTargets, coverTargets, blockedTargets };
  
  const shooterCube = offsetToCube(shooterCol, shooterRow);
  const wallHexes = boardConfig.wall_hexes || [];
  
  // Check all enemy units within range
  units.filter(unit => unit.alive).forEach(target => {
    const targetCube = offsetToCube(target.col, target.row);
    const distance = cubeDistance(shooterCube, targetCube);
    
    if (distance > 0 && distance <= range) {
      const lineOfSight = hasLineOfSight(
        { col: shooterCol, row: shooterRow },
        { col: target.col, row: target.row },
        wallHexes
      );
      
      if (!lineOfSight.canSee) {
        blockedTargets.add(`${target.col},${target.row}`);
      } else if (lineOfSight.inCover) {
        coverTargets.push({ col: target.col, row: target.row });
      } else {
        clearTargets.push({ col: target.col, row: target.row });
      }
    }
  });
  
  return { clearTargets, coverTargets, blockedTargets };
};

// AI_GAME.md: Strict type definitions following game mechanisms
interface ReplayEvent {
  turn: number;
  phase: 'move' | 'shoot' | 'charge' | 'combat';
  player: 0 | 1;
  action: {
    type: string;
    unit_id?: number;
    from_pos?: [number, number];
    to_pos?: [number, number];
    target_id?: number;
    damage?: number;
    result?: string;
  };
  description: string;
  timestamp?: string;
}

interface ReplayUnit {
  id: number;
  unit_type: string;
  player: 0 | 1;
  col: number;
  row: number;
  hp_max: number;
  hp_current: number;
  move: number;
  rng_rng: number;
  rng_dmg: number;
  cc_dmg: number;
  is_ranged: boolean;
  is_melee: boolean;
  alive: boolean;
  COLOR: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP: number;
  cur_hp: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  ICON: string;
  ICON_SCALE?: number;
}

interface ReplayData {
  game_info: {
    scenario: string;
    ai_behavior: string;
    total_turns: number;
    winner: 0 | 1;
    ai_units_final: number;
    enemy_units_final: number;
  };
  metadata?: {
    template?: string;
    player_0_agent?: string;
    player_1_agent?: string;
    [key: string]: any;
  };
  initial_state?: {
    units: ReplayUnit[];
    board_size: [number, number];
  };
  game_states?: {
    units: any[];
    [key: string]: any;
  }[];
  actions?: ReplayEvent[]; // Optional - legacy format
  combat_log: any[]; // Required - our shared format
}

// Removed ScenarioConfig interface - using BoardConfig directly

interface ReplayViewerProps {
  replayFile?: string;
}

export const BoardReplay: React.FC<ReplayViewerProps> = ({ 
  replayFile: propReplayFile = null
}) => {
  // AI_INSTRUCTIONS.md: Use same config hook as Board.tsx
  const { boardConfig, loading: configLoading, error: configError } = useGameConfig();
  
  // File selection state
  const [replayFile, setReplayFile] = useState<string | null>(propReplayFile);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // State management
  const [replayData, setReplayData] = useState<ReplayData | null>(null);
  const [scenario, setScenario] = useState<typeof boardConfig | null>(null);
  const [loading, setLoading] = useState(!!propReplayFile);
  const [error, setError] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [currentUnits, setCurrentUnits] = useState<ReplayUnit[]>([]);
  const [currentEvent, setCurrentEvent] = useState<ReplayEvent | null>(null);
  const [battleLog, setBattleLog] = useState<ReplayEvent[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1000); // ms per step
  const [registryInitialized, setRegistryInitialized] = useState(false);
  
  // Acting unit ID for automatic highlighting
  const [actingUnitId, setActingUnitId] = useState<number | null>(null);
  
  // Move preview state for pathfinding visualization
  const [movePreview, setMovePreview] = useState<{
    fromCol: number;
    fromRow: number;
    toCol: number;
    toRow: number;
    path: { col: number; row: number }[];
    unitId: number;
  } | null>(null);
  
  // Shooting preview state for line of sight visualization
  const [shootingPreview, setShootingPreview] = useState<{
    shooterCol: number;
    shooterRow: number;
    clearTargets: { col: number; row: number }[];
    coverTargets: { col: number; row: number }[];
    blockedTargets: Set<string>;
    unitId: number;
    range: number;
  } | null>(null);
  
  // PIXI.js refs - AI_INSTRUCTIONS.md: Use PIXI.js Canvas
  const boardRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<PIXI.Application | null>(null);
  const unitSpritesRef = useRef<Map<number, PIXI.Container>>(new Map());
  
  // Auto-play interval
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

// Action type mapping from the replay file format
const ACTION_TYPE_MAPPING: Record<string, { name: string; type: string }> = {
  "0": { name: "Move North", type: "move" },
  "1": { name: "Move South", type: "move" },
  "2": { name: "Move East", type: "move" },
  "3": { name: "Move West", type: "move" },
  "4": { name: "Ranged Attack", type: "shoot" },
  "5": { name: "Charge Enemy", type: "charge" },
  "6": { name: "Melee Attack", type: "combat" },
  "7": { name: "Wait/End turn", type: "move" },
  "-1": { name: "Phase Penalty", type: "penalty" }
};
const UNIT_REGISTRY: Record<string, any> = {};

// Component to show board preview without replay data
const EmptyBoardPreview: React.FC<{ boardConfig: any }> = ({ boardConfig }) => {
  const boardRef = useRef<HTMLDivElement>(null);
  const pixiAppRef = useRef<PIXI.Application | null>(null);

  useEffect(() => {
    if (!boardRef.current || !boardConfig) return;

    try {
      // Calculate canvas dimensions - same as main board
      const BOARD_COLS = boardConfig.cols;
      const BOARD_ROWS = boardConfig.rows;
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;
      
      const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
      const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
      const canvasWidth = gridWidth + 2 * MARGIN;
      const canvasHeight = gridHeight + 2 * MARGIN;
      
      // Create PIXI app
      const displayConfig = boardConfig?.display;
      const pixiConfig = {
        width: canvasWidth,
        height: canvasHeight,
        backgroundColor: parseInt(boardConfig.colors.background.replace('0x', ''), 16),
        antialias: displayConfig?.antialias ?? true,
        powerPreference: "high-performance" as WebGLPowerPreference,
        resolution: displayConfig?.resolution === "auto" ? 
          (window.devicePixelRatio || 1) : (displayConfig?.resolution ?? 1),
        autoDensity: displayConfig?.autoDensity ?? true,
      };
      
      const app = new PIXI.Application(pixiConfig);
      app.stage.sortableChildren = true;
      
      // Setup canvas styling
      const canvas = app.view as HTMLCanvasElement;
      canvas.style.display = 'block';
      canvas.style.maxWidth = '100%';
      canvas.style.height = 'auto';
      canvas.style.border = displayConfig?.canvas_border ?? '1px solid #333';
      
      // Clear container and append canvas
      boardRef.current.innerHTML = '';
      boardRef.current.appendChild(canvas);
      
      // Store app reference
      pixiAppRef.current = app;
      
      // Draw board using shared BoardRenderer
      drawBoard(app, boardConfig as any);
      
      // Cleanup function
      return () => {
        if (pixiAppRef.current) {
          pixiAppRef.current.destroy(true);
          pixiAppRef.current = null;
        }
      };
      
    } catch (error) {
      console.error('❌ Error initializing board preview:', error);
    }
  }, [boardConfig]);

  if (!boardConfig) {
    return (
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center', 
        height: '400px',
        color: '#888'
      }}>
        Loading board...
      </div>
    );
  }

  return <div ref={boardRef} className="board" />;
};

// File selection handlers
const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
  const file = event.target.files?.[0];
  if (file) {
    // Validate file type
    if (!file.name.endsWith('.json')) {
      setFileError('Please select a JSON file');
      return;
    }

    // Check if it's a replay file based on naming patterns
    const isReplayFile = file.name.startsWith('training_replay_') ||
                        file.name.startsWith('phase_based_replay_') ||
                        file.name.includes('_vs_') ||
                        file.name.startsWith('replay_') ||
                        file.name.startsWith('training_') ||
                        file.name.startsWith('game_replay_');

    if (!isReplayFile) {
      setFileError('Please select a valid replay JSON file');
      return;
    }

    // Create file URL for local file access
    const fileUrl = URL.createObjectURL(file);
    setReplayFile(fileUrl);
    setSelectedFileName(file.name);
    setFileError(null);
    setCurrentStep(0);
  }
};

const openFileBrowser = () => {
  fileInputRef.current?.click();
};

// Dynamic unit registry initialization
const initializeUnitRegistry = async () => {
  try {
    // Load unit registry configuration
    const registryResponse = await fetch('/config/unit_registry.json');
    
    if (!registryResponse.ok) {
      throw new Error(`Failed to load unit registry: ${registryResponse.statusText}`);
    }
    
    const text = await registryResponse.text();
    
    const unitConfig = JSON.parse(text);
    
    // Dynamically import each unit class
    for (const [unitType, unitPath] of Object.entries(unitConfig.units)) {
      try {
        console.log(`🔄 Importing unit: ${unitType} from path: ../roster/${unitPath}`);
        const module = await import(/* @vite-ignore */ `../roster/${unitPath}`);
        console.log(`✅ Module loaded for ${unitType}:`, Object.keys(module));
        
        const UnitClass = module[unitType] || module.default;
        console.log(`🔍 UnitClass for ${unitType}:`, UnitClass ? 'Found' : 'Not found');
        
        if (!UnitClass) {
          throw new Error(`Unit class ${unitType} not found in ${unitPath}. Available exports: ${Object.keys(module).join(', ')}`);
        }
        
        // Validate required properties
        const requiredProps = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'ICON'];
        requiredProps.forEach(prop => {
          if (UnitClass[prop] === undefined) {
            throw new Error(`Unit ${unitType} missing required property: ${prop}`);
          }
        });
        
        UNIT_REGISTRY[unitType] = UnitClass;
        console.log(`✅ Successfully registered unit: ${unitType}`);
        
      } catch (importError) {
        console.error(`❌ Failed to import unit ${unitType} from ${unitPath}:`, importError);
        throw importError;
      }
    }
  } catch (error) {
    console.error('❌ Failed to initialize unit registry:', error);
    throw error;
  }
};

const validateUnitRegistry = () => {
  if (Object.keys(UNIT_REGISTRY).length === 0) {
    throw new Error('Unit registry not initialized');
  }
};

    // AI_INSTRUCTIONS.md: Initialize unit registry first
  useEffect(() => {
    const initRegistry = async () => {
      try {
        await initializeUnitRegistry();
        validateUnitRegistry();
        console.log('✅ Unit registry initialized for replay');
        // Trigger replay loading with registry state
        setRegistryInitialized(true);
      } catch (error) {
        console.error('❌ Failed to initialize unit registry:', error);
        setError('Failed to initialize unit registry');
      }
    };
    initRegistry();
  }, []);

  // Get unit stats from registry like UnitFactory.ts
  const getUnitStats = useCallback((unitType: string) => {
    const UnitClass = UNIT_REGISTRY[unitType];
    if (!UnitClass) {
      console.error(`❌ Unknown unit type: ${unitType}. Available units:`, Object.keys(UNIT_REGISTRY));
      console.error(`❌ This indicates the unit registry failed to load Tyranid units properly.`);
      console.error(`❌ Check /config/unit_registry.json file and ensure it includes paths to Tyranid units.`);
      throw new Error(`Unknown unit type: ${unitType}. Available types: ${Object.keys(UNIT_REGISTRY).join(', ')}`);
    }
    
    return {
      MOVE: UnitClass.MOVE,
      HP_MAX: UnitClass.HP_MAX,
      RNG_RNG: UnitClass.RNG_RNG,
      RNG_DMG: UnitClass.RNG_DMG,
      RNG_NB: UnitClass.RNG_NB,
      RNG_ATK: UnitClass.RNG_ATK,
      RNG_STR: UnitClass.RNG_STR,
      RNG_AP: UnitClass.RNG_AP,
      CC_DMG: UnitClass.CC_DMG,
      CC_NB: UnitClass.CC_NB,
      CC_ATK: UnitClass.CC_ATK,
      CC_STR: UnitClass.CC_STR,
      CC_AP: UnitClass.CC_AP,
      CC_RNG: UnitClass.CC_RNG,
      T: UnitClass.T,
      ARMOR_SAVE: UnitClass.ARMOR_SAVE,
      ICON: UnitClass.ICON,
      ICON_SCALE: UnitClass.ICON_SCALE
    };
  }, []);
  useEffect(() => {
    const loadReplayData = async () => {
      if (configLoading) return;
      if (configError) {
        setError(`Config error: ${configError}`);
        setLoading(false);
        return;
      }
      
      // Wait for unit registry to be initialized before loading replay
      if (!registryInitialized) {
        console.log('⏳ Waiting for unit registry to initialize...');
        setLoading(false); // Important: set loading to false when waiting
        return;
      }
      
      // Reset state when file changes
      setCurrentStep(0);
      setCurrentEvent(null);
      // Don't reset battleLog here - it will be set during replay processing
      
      // Skip loading if no file selected
      if (!replayFile) {
        setLoading(false);
        return;
      }
      
      console.log(`🔄 Loading new replay file: ${replayFile}`);
      
      try {
        setLoading(true);
        
        // Use boardConfig directly - same as Board.tsx for perfect consistency
        setScenario(boardConfig);
        
        // Load replay file - handle both blob URLs and file paths
        let replay;
        if (replayFile.startsWith('blob:')) {
          // Handle blob URL from file selection
          console.log('🔄 Loading blob URL:', replayFile);
          const replayResponse = await fetch(replayFile);
          if (!replayResponse.ok) {
            throw new Error(`Failed to load replay file: ${replayResponse.statusText}`);
          }
          const text = await replayResponse.text();
          console.log('📦 Raw blob text (first 200 chars):', text.substring(0, 200));
          replay = JSON.parse(text);
        } else {
          // Handle regular file path
          console.log('🔄 Loading file path:', replayFile);
          const replayResponse = await fetch(`/${replayFile}`);
          if (!replayResponse.ok) {
            throw new Error(`Failed to load replay file: ${replayResponse.statusText}`);
          }
          replay = await replayResponse.json();
        };
        
        setReplayData(replay);
        
        // ENFORCE: All replays must have combat_log (new format)
        if (!replay.combat_log || !Array.isArray(replay.combat_log)) {
          throw new Error('Invalid replay format: Missing combat_log. Please use training replays generated with the new combat log system.');
        }
        
        console.log('🎯 Using combat_log format with', replay.combat_log.length, 'entries');
        console.log('🔍 First 3 combat_log entries:', replay.combat_log.slice(0, 3));
        
        // Set the battle log directly from the training logger's combat_log
        const mappedBattleLog = replay.combat_log.map((entry: any) => ({
          turn: entry.turnNumber || 1,
          phase: entry.phase || 'move',
          player: entry.player || 0,
          action: {
            type: entry.type,
            unit_id: entry.unitId,
            target_id: entry.targetUnitId
          },
          description: entry.message,
          // Include all the training-specific data
          ...entry
        }));
        
        console.log('🔍 Mapped battleLog length:', mappedBattleLog.length);
        console.log('🔍 First mapped entry:', mappedBattleLog[0]);
        setBattleLog(mappedBattleLog);
        
        // Debug: Check if battleLog state is being reset
        setTimeout(() => {
          console.log('🔍 battleLog state after 100ms:', battleLog.length);
        }, 100);
        
        // Process initial units with proper mapping - handle both formats
        let initialUnits: any[] = [];
        if (replay.initial_state?.units) {
          initialUnits = replay.initial_state.units;
          console.log('🔍 Using initial_state.units format');
        } else if (replay.game_states?.[0]?.units) {
          initialUnits = replay.game_states[0].units;
          console.log('🔍 Using game_states[0].units format');
        } else {
          console.error('❌ No initial units found in replay data. Available keys:', Object.keys(replay));
          return;
        }

        if (initialUnits.length > 0) {
          const processedUnits: ReplayUnit[] = initialUnits.map((unit: any) => {
            const stats = getUnitStats(unit.unit_type);
            return {
              id: unit.id,
              name: unit.unit_type,
              type: unit.unit_type,
              unit_type: unit.unit_type,
              player: unit.player,
              col: unit.col,
              row: unit.row,
              color: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
              alive: true,
              hp_max: unit.hp_max,
              hp_current: unit.hp_max,
              move: stats.MOVE,
              rng_rng: stats.RNG_RNG,
              rng_dmg: stats.RNG_DMG,
              cc_dmg: stats.CC_DMG,
              is_ranged: unit.is_ranged || false,
              is_melee: unit.is_melee || false,
              CUR_HP: unit.hp_max,
              cur_hp: unit.hp_max,
              COLOR: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
              MOVE: stats.MOVE,
              HP_MAX: stats.HP_MAX,
              RNG_RNG: stats.RNG_RNG,
              RNG_DMG: stats.RNG_DMG,
              CC_DMG: stats.CC_DMG,
              ICON: stats.ICON,
              ICON_SCALE: stats.ICON_SCALE
            };
          });
          
          // Check for initial position conflicts in scenario
          const initialPositions = new Map<string, any[]>();
          processedUnits.forEach(unit => {
            const key = `${unit.col},${unit.row}`;
            if (!initialPositions.has(key)) initialPositions.set(key, []);
            initialPositions.get(key)!.push({id: unit.id, type: unit.unit_type});
          });
          
          initialPositions.forEach((unitsAtPos, pos) => {
            if (unitsAtPos.length > 1) {
              console.error(`❌ SCENARIO BUG: Multiple units spawned at initial position ${pos}:`, unitsAtPos);
            }
          });
          
          console.log(`✅ Processed ${processedUnits.length} initial units`);
          setCurrentUnits(processedUnits);
        } else {
          console.error('❌ No initial units found in replay data');
        }
        
        // Don't reset battleLog here - it's set by combat_log processing
        setCurrentStep(0);
      } catch (err) {
        console.error('❌ Error loading replay:', err);
        setError(err instanceof Error ? err.message : 'Failed to load replay');
      } finally {
        setLoading(false);
      }
    };
    
    loadReplayData();
  }, [replayFile, configLoading, configError, getUnitStats, registryInitialized, boardConfig]);

  // Same hex calculations as Board.tsx
  const getHexCenter = useCallback((col: number, row: number): { x: number, y: number } => {
    if (!boardConfig) return { x: 0, y: 0 };
    
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;
    
    const x = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const y = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
    
    return { x, y };
  }, [scenario]);

  // Removed duplicate getHexPolygonPoints function

  // Parse colors from config - same as Board.tsx
  const parseColor = useCallback((colorStr: string): number => {
    return parseInt(colorStr.replace('0x', ''), 16);
  }, []);

  // Helper to get hex polygon points
  const getHexPolygonPoints = useCallback((centerX: number, centerY: number, radius: number): number[] => {
    const points: number[] = [];
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i;
      points.push(centerX + radius * Math.cos(angle), centerY + radius * Math.sin(angle));
    }
    return points;
  }, []);

  // Using shared BoardRenderer - no duplicate code!

  // Draw move preview hexes (black origin + green path)
  const drawMovePreview = useCallback((app: PIXI.Application) => {
    if (!movePreview || !boardConfig) return;
    
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;
    
    // Remove existing preview graphics
    const existingPreview = app.stage.children.find(child => child.name === 'movePreview');
    if (existingPreview) {
      app.stage.removeChild(existingPreview);
      existingPreview.destroy();
    }
    
    const previewContainer = new PIXI.Container();
    previewContainer.name = 'movePreview';
    previewContainer.zIndex = 1; // Below units but above board
    
    // Draw black origin hex
    const originCenter = getHexCenter(movePreview.fromCol, movePreview.fromRow);
    const originHex = new PIXI.Graphics();
    const originPoints = getHexPolygonPoints(originCenter.x, originCenter.y, HEX_RADIUS * 0.9);
    originHex.beginFill(0x000000, 0.7); // Black with transparency
    originHex.drawPolygon(originPoints);
    originHex.endFill();
    previewContainer.addChild(originHex);
    
    // Draw green path hexes (excluding origin)
    const pathColor = parseInt(boardConfig.colors.eligible?.replace('0x', '') || '00FF00', 16);
    movePreview.path.forEach((pathHex, index) => {
      if (index === 0) return; // Skip origin hex
      
      const center = getHexCenter(pathHex.col, pathHex.row);
      const pathHexGraphic = new PIXI.Graphics();
      const points = getHexPolygonPoints(center.x, center.y, HEX_RADIUS * 0.8);
      pathHexGraphic.beginFill(pathColor, 0.5); // Green with transparency
      pathHexGraphic.drawPolygon(points);
      pathHexGraphic.endFill();
      previewContainer.addChild(pathHexGraphic);
    });
    
    app.stage.addChild(previewContainer);
  }, [movePreview, boardConfig, getHexCenter, getHexPolygonPoints]);

  // Draw shooting preview hexes (red clear sight + orange cover)
  const drawShootingPreview = useCallback((app: PIXI.Application) => {
    if (!shootingPreview || !boardConfig) return;
    
    const HEX_RADIUS = boardConfig.hex_radius;
    
    // Remove existing shooting preview graphics
    const existingPreview = app.stage.children.find(child => child.name === 'shootingPreview');
    if (existingPreview) {
      app.stage.removeChild(existingPreview);
      existingPreview.destroy();
    }
    
    const previewContainer = new PIXI.Container();
    previewContainer.name = 'shootingPreview';
    previewContainer.zIndex = 1; // Below units but above board
    
    // Draw red hexes for clear line of sight targets
    const clearColor = parseInt(boardConfig.colors.attack?.replace('0x', '') || 'FF0000', 16);
    shootingPreview.clearTargets.forEach(target => {
      const center = getHexCenter(target.col, target.row);
      const targetHex = new PIXI.Graphics();
      const points = getHexPolygonPoints(center.x, center.y, HEX_RADIUS * 0.8);
      targetHex.beginFill(clearColor, 0.6); // Red with transparency
      targetHex.drawPolygon(points);
      targetHex.endFill();
      previewContainer.addChild(targetHex);
    });
    
    // Draw orange hexes for targets in cover
    const coverColor = parseInt((boardConfig.colors.charge || '0xFFA500').replace('0x', ''), 16);
    shootingPreview.coverTargets.forEach(target => {
      const center = getHexCenter(target.col, target.row);
      const targetHex = new PIXI.Graphics();
      const points = getHexPolygonPoints(center.x, center.y, HEX_RADIUS * 0.8);
      targetHex.beginFill(coverColor, 0.6); // Orange with transparency
      targetHex.drawPolygon(points);
      targetHex.endFill();
      previewContainer.addChild(targetHex);
    });
    
    // Draw range indicator circle around shooter
    const shooterCenter = getHexCenter(shootingPreview.shooterCol, shootingPreview.shooterRow);
    const rangeCircle = new PIXI.Graphics();
    const hexSize = HEX_RADIUS * 1.5; // Approximate hex spacing
    const rangeRadius = shootingPreview.range * hexSize;
    rangeCircle.lineStyle(2, 0xFFFFFF, 0.3); // White circle with transparency
    rangeCircle.drawCircle(shooterCenter.x, shooterCenter.y, rangeRadius);
    previewContainer.addChild(rangeCircle);
    
    app.stage.addChild(previewContainer);
  }, [shootingPreview, boardConfig, getHexCenter, getHexPolygonPoints]);

  // Draw units using UnitRenderer - same as Board.tsx
  const drawUnits = useCallback((app: PIXI.Application, units: ReplayUnit[], highlightUnitId: number | null = null) => {
    if (!scenario || !app.stage || !boardConfig?.display) return;
    
    try {
      // Clear previous unit sprites
      unitSpritesRef.current.forEach(sprite => {
        app.stage.removeChild(sprite);
        sprite.destroy();
      });
      unitSpritesRef.current.clear();
      
      const displayConfig = boardConfig.display;
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;
      
      // Extract all needed constants like Board.tsx
      const ICON_SCALE = displayConfig.icon_scale || 1;
      const ELIGIBLE_OUTLINE_WIDTH = displayConfig.eligible_outline_width || 2;
      const ELIGIBLE_COLOR = parseColor(boardConfig.colors.eligible || '0x00FF00');
      const ELIGIBLE_OUTLINE_ALPHA = displayConfig.eligible_outline_alpha || 0.8;
      const HP_BAR_WIDTH_RATIO = displayConfig.hp_bar_width_ratio || 1.4;
      const HP_BAR_HEIGHT = displayConfig.hp_bar_height || 7;
      const UNIT_CIRCLE_RADIUS_RATIO = displayConfig.unit_circle_radius_ratio || 0.6;
      const UNIT_TEXT_SIZE = displayConfig.unit_text_size || 8;
      const SELECTED_BORDER_WIDTH = displayConfig.selected_border_width || 3;
      const CHARGE_TARGET_BORDER_WIDTH = displayConfig.charge_target_border_width || 2;
      const DEFAULT_BORDER_WIDTH = displayConfig.default_border_width || 1;
      
      // Draw each alive unit using UnitRenderer
      units.filter(unit => unit.alive).forEach(unit => {
        const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        
        const unitForRenderer = {
          id: unit.id,
          name: unit.unit_type,
          type: unit.unit_type,
          unit_type: unit.unit_type,
          player: unit.player,
          col: unit.col,
          row: unit.row,
          color: unit.COLOR,
          alive: unit.alive,
          CUR_HP: unit.CUR_HP,
          HP_MAX: unit.HP_MAX,
          MOVE: unit.MOVE,
          RNG_RNG: unit.RNG_RNG,
          RNG_DMG: unit.RNG_DMG,
          CC_DMG: unit.CC_DMG,
          ICON: unit.ICON, // Use the ICON from stats (should be correct)
          ICON_SCALE: unit.ICON_SCALE
        };

        renderUnit({
          unit: unitForRenderer, centerX, centerY, app,
          isPreview: false,
          previewType: undefined,
          isEligible: unit.id === highlightUnitId, // Highlight acting unit with green circle
          boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
          phase: 'move', mode: 'select', currentPlayer: 0, selectedUnitId: null, 
          unitsMoved: [], unitsCharged: [], unitsAttacked: [], unitsFled: [],
          combatSubPhase: undefined, combatActivePlayer: undefined,
          units: units.map(u => ({
            ...u,
            name: u.unit_type,
            type: u.unit_type,
            color: u.COLOR
          })), chargeTargets: [], combatTargets: [], targetPreview: null,
          onConfirmMove: () => {}, parseColor
        });
      });
    } catch (error) {
      console.error('❌ Error drawing units:', error);
      throw error;
    }
  }, [scenario, boardConfig, parseColor]);

  // Initialize PIXI application - AI_INSTRUCTIONS.md: PIXI.js Canvas renderer
  useEffect(() => {
    if (!boardRef.current || !boardConfig || !replayData) return;
    
    try {
      // Calculate canvas dimensions - same as Board.tsx
      const BOARD_COLS = boardConfig!.cols;
      const BOARD_ROWS = boardConfig!.rows;
      const HEX_RADIUS = boardConfig!.hex_radius;
      const MARGIN = boardConfig!.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;
      
      const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
      const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
      const canvasWidth = gridWidth + 2 * MARGIN;
      const canvasHeight = gridHeight + 2 * MARGIN;
      
      // Use same PIXI config as Board.tsx for consistent appearance
      const displayConfig = boardConfig?.display;
      const pixiConfig = {
        width: canvasWidth,
        height: canvasHeight,
        backgroundColor: parseInt(boardConfig!.colors.background.replace('0x', ''), 16),
        antialias: displayConfig?.antialias ?? true,
        powerPreference: "high-performance" as WebGLPowerPreference,
        resolution: displayConfig?.resolution === "auto" ? 
          (window.devicePixelRatio || 1) : (displayConfig?.resolution ?? 1),
        autoDensity: displayConfig?.autoDensity ?? true,
      };
      
      const app = new PIXI.Application(pixiConfig);
      app.stage.sortableChildren = true;
      
      // Setup canvas styling - same as Board.tsx
      const canvas = app.view as HTMLCanvasElement;
      canvas.style.display = 'block';
      canvas.style.maxWidth = '100%';
      canvas.style.height = 'auto';
      canvas.style.border = displayConfig?.canvas_border ?? '1px solid #333';
      
      // Clear container and append canvas
      boardRef.current.innerHTML = '';
      boardRef.current.appendChild(canvas);
      
      // Store app reference
      pixiAppRef.current = app;
      
      // Draw initial board and units using shared BoardRenderer
      drawBoard(app, boardConfig! as any);
      drawMovePreview(app);
      drawShootingPreview(app);
      drawUnits(app, currentUnits, actingUnitId);
      
      // Cleanup function
      return () => {
        if (pixiAppRef.current) {
          pixiAppRef.current.destroy(true);
          pixiAppRef.current = null;
        }
        unitSpritesRef.current.clear();
      };
      
    } catch (error) {
      console.error('❌ Error initializing PIXI application:', error);
      setError('Failed to initialize board display');
    }
  }, [scenario, replayData, drawUnits, drawMovePreview, drawShootingPreview, currentUnits, actingUnitId, movePreview, shootingPreview]);

  // Update previews when they change
  useEffect(() => {
    if (pixiAppRef.current) {
      drawMovePreview(pixiAppRef.current);
      drawShootingPreview(pixiAppRef.current);
    }
  }, [movePreview, shootingPreview, drawMovePreview, drawShootingPreview]);

  // Update game state based on current step
  useEffect(() => {
    if (!replayData || currentStep < 0 || !battleLog || battleLog.length === 0) return;
    
    try {
      // Get initial units from either format
      let initialUnits: any[] = [];
      if (replayData.initial_state?.units) {
        initialUnits = replayData.initial_state.units;
      } else if (replayData.game_states?.[0]?.units) {
        initialUnits = replayData.game_states[0].units;
      } else {
        console.error('❌ No initial state units available');
        return;
      }
      
      // Start with initial state
      let newUnits: ReplayUnit[] = initialUnits.map((unit: any) => {
        const stats = getUnitStats(unit.unit_type);
        return {
          id: unit.id,
          name: unit.unit_type,
          type: unit.unit_type,
          unit_type: unit.unit_type,
          player: unit.player,
          col: unit.col,
          row: unit.row,
          color: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
          alive: true,
          hp_max: unit.hp_max,
          hp_current: unit.hp_max,
          move: stats.MOVE,
          rng_rng: stats.RNG_RNG,
          rng_dmg: stats.RNG_DMG,
          cc_dmg: stats.CC_DMG,
          is_ranged: unit.is_ranged || false,
          is_melee: unit.is_melee || false,
          CUR_HP: unit.hp_max,
          cur_hp: unit.hp_max,
          COLOR: unit.player === 0 ? parseInt(boardConfig!.colors.player_0.replace('0x', ''), 16) : parseInt(boardConfig!.colors.player_1.replace('0x', ''), 16),
          MOVE: stats.MOVE,
          HP_MAX: stats.HP_MAX,
          RNG_RNG: stats.RNG_RNG,
          RNG_DMG: stats.RNG_DMG,
          CC_DMG: stats.CC_DMG,
          ICON: stats.ICON,
          ICON_SCALE: stats.ICON_SCALE
        };
      });
      
      // Process combat log events up to current step to update unit state
      console.log(`🔄 Processing ${currentStep + 1} combat log events to update unit state`);
      for (let i = 0; i <= currentStep && i < battleLog.length; i++) {
        const event = battleLog[i] as any;
        
        // Process move events
        if (event.type === 'move' && event.unitId !== undefined) {
          const unit = newUnits.find(u => u.id === event.unitId);
          if (unit && event.endHex) {
            const [newCol, newRow] = event.endHex.match(/\d+/g)?.map(Number) || [unit.col, unit.row];
            unit.col = newCol;
            unit.row = newRow;
            console.log(`📍 Unit ${unit.id} moved to (${newCol}, ${newRow})`);
          }
        }
        
        // Process damage events (shoot/combat)
        if ((event.type === 'shoot' || event.type === 'combat') && event.targetUnitId !== undefined) {
          const targetUnit = newUnits.find(u => u.id === event.targetUnitId);
          if (targetUnit && event.shootDetails && Array.isArray(event.shootDetails)) {
            const totalDamage = event.shootDetails.reduce((sum: number, shot: any) => sum + (shot.damageDealt || 0), 0);
            if (totalDamage > 0) {
              targetUnit.hp_current = Math.max(0, targetUnit.hp_current - totalDamage);
              targetUnit.cur_hp = targetUnit.hp_current;
              targetUnit.CUR_HP = targetUnit.hp_current;
              console.log(`💥 Unit ${targetUnit.id} took ${totalDamage} damage, HP: ${targetUnit.hp_current}/${targetUnit.hp_max}`);
              
              if (targetUnit.hp_current <= 0) {
                targetUnit.alive = false;
                console.log(`💀 Unit ${targetUnit.id} died`);
              }
            }
          }
        }
      }
      
      setCurrentUnits(newUnits);
      
      // Set acting unit ID from combat_log for highlighting
      const currentLogEntry = battleLog[currentStep];
      const currentActingUnitId = currentLogEntry ? (currentLogEntry as any).unitId : null;
      setActingUnitId(currentActingUnitId);
      
      // Set current event
      setCurrentEvent(currentLogEntry);
      
      // Detect move actions and set up move preview
      if (currentLogEntry && (currentLogEntry as any).type === 'move') {
        const logEntry = currentLogEntry as any;
        const movingUnit = newUnits.find(u => u.id === logEntry.unitId);
        
        if (movingUnit && logEntry.startHex && logEntry.endHex) {
          // Parse hex coordinates from "(col, row)" format
          const startMatch = logEntry.startHex.match(/\((\d+),\s*(\d+)\)/);
          const endMatch = logEntry.endHex.match(/\((\d+),\s*(\d+)\)/);
          
          if (startMatch && endMatch) {
            const fromCol = parseInt(startMatch[1]);
            const fromRow = parseInt(startMatch[2]);
            const toCol = parseInt(endMatch[1]);
            const toRow = parseInt(endMatch[2]);
            
            // Calculate path using pathfinding
            const path = calculateMovePath(fromCol, fromRow, toCol, toRow, movingUnit.MOVE, boardConfig, newUnits);
            
            if (path.length > 0) {
              setMovePreview({
                fromCol,
                fromRow,
                toCol,
                toRow,
                path,
                unitId: logEntry.unitId
              });
            } else {
              setMovePreview(null);
            }
          } else {
            setMovePreview(null);
          }
        } else {
          setMovePreview(null);
        }
        setShootingPreview(null); // Clear shooting preview during moves
      } 
      // Detect shooting actions and set up shooting preview
      else if (currentLogEntry && (currentLogEntry as any).type === 'shoot') {
        const logEntry = currentLogEntry as any;
        const shootingUnit = newUnits.find(u => u.id === logEntry.unitId);
        
        if (shootingUnit) {
          // Calculate shooting targets and line of sight
          const shootingTargets = calculateShootingTargets(
            shootingUnit.col,
            shootingUnit.row,
            shootingUnit.RNG_RNG,
            boardConfig,
            newUnits.filter(u => u.player !== shootingUnit.player) // Only enemy units
          );
          
          setShootingPreview({
            shooterCol: shootingUnit.col,
            shooterRow: shootingUnit.row,
            clearTargets: shootingTargets.clearTargets,
            coverTargets: shootingTargets.coverTargets,
            blockedTargets: shootingTargets.blockedTargets,
            unitId: logEntry.unitId,
            range: shootingUnit.RNG_RNG
          });
        } else {
          setShootingPreview(null);
        }
        setMovePreview(null); // Clear move preview during shooting
      } else {
        setMovePreview(null);
        setShootingPreview(null);
      }
      
      // Update PIXI display
      if (pixiAppRef.current) {
        drawMovePreview(pixiAppRef.current);
        drawShootingPreview(pixiAppRef.current);
        drawUnits(pixiAppRef.current, newUnits, currentActingUnitId);
      }
      
    } catch (error) {
      console.error('❌ Error updating game state:', error);
      setError('Failed to update game state');
    }
  }, [currentStep, replayData, drawUnits, scenario, getUnitStats, battleLog, boardConfig]);

  // Debug: Track battleLog changes
  useEffect(() => {
    console.log('🔍 battleLog state changed, new length:', battleLog.length);
  }, [battleLog]);

  // Auto-play functionality
  useEffect(() => {
    if (isPlaying && replayData) {
      intervalRef.current = setInterval(() => {
        setCurrentStep(prev => {
          if (prev >= battleLog.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, playSpeed);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [isPlaying, playSpeed, replayData]);

  // Navigation functions
  const goToStep = (step: number) => {
    if (step >= 0 && step < battleLog.length) {
      setCurrentStep(step);
      setIsPlaying(false);
    }
  };


  const nextStep = () => {
    if (currentStep < battleLog.length - 1) {
      setCurrentStep(prev => prev + 1);
    }
  };

  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep(prev => prev - 1);
    }
  };

  const togglePlay = () => {
    setIsPlaying(prev => !prev);
  };

  const goToTurn = (targetTurn: number) => {
    if (!battleLog || battleLog.length === 0) return;
    
    // Find the first action of the target turn using battleLog (combat_log)
    const actionIndex = battleLog.findIndex(action => action.turn === targetTurn);
    if (actionIndex !== -1) {
      setCurrentStep(actionIndex);
      setIsPlaying(false);
    }
  };

  const goToStart = () => {
    setCurrentStep(0);
    setIsPlaying(false);
  };

  const goToEnd = () => {
    if (battleLog.length > 0) {
      setCurrentStep(battleLog.length - 1);
      setIsPlaying(false);
    }
  };

  const getCurrentPhase = (): string => {
    if (!currentEvent) return 'move';
    return currentEvent.phase || 'move';
  };

  const getCurrentTurn = (): number => {
    if (!currentEvent) return 1;
    return currentEvent.turn || 1;
  };

  // Remove these unused functions

  // No file selected state - show board preview
  if (!replayFile) {
    const noFileRightContent = (
      <div className="unit-status-table-container">
        <div style={{ padding: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
            <button
              onClick={openFileBrowser}
              style={{
                padding: '8px 16px',
                backgroundColor: '#1e40af',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: 'bold'
              }}
            >
              📁 Replay Files
            </button>
            {selectedFileName && (
              <span className="file-browser-filename">
                {selectedFileName}
                {replayData?.metadata?.template && (
                  <span className="file-browser-template">
                    [{replayData.metadata.template}]
                  </span>
                )}
              </span>
            )}
          </div>
          {fileError && (
            <div className="file-browser-error">
              {fileError}
            </div>
          )}
          <div style={{ marginTop: '8px', padding: '8px', backgroundColor: '#333', borderRadius: '6px' }}>
            <div style={{ fontSize: '12px', color: '#888', marginBottom: '4px' }}>Board Preview</div>
            <div style={{ fontSize: '11px', color: '#666' }}>
              Select a replay file to see AI training in action on this board
            </div>
          </div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
      </div>
    );

    // Show board preview when no file is selected
    return (
      <SharedLayout rightColumnContent={noFileRightContent}>
        <EmptyBoardPreview boardConfig={boardConfig} />
      </SharedLayout>
    );
  }

  // Loading state
  if (loading) {
    return (
      <SharedLayout rightColumnContent={
        <div className="flex items-center justify-center h-96">
          <div className="text-lg">Loading replay...</div>
        </div>
      }>
        <div className="flex items-center justify-center h-96">
          <div className="text-lg">Loading replay...</div>
        </div>
      </SharedLayout>
    );
  }

  // Error state
  if (error) {
    return (
      <SharedLayout rightColumnContent={
        <div className="flex items-center justify-center h-96">
          <div className="text-red-600">Error: {error}</div>
        </div>
      }>
        <div className="flex items-center justify-center h-96">
          <div className="text-red-600">Error: {error}</div>
        </div>
      </SharedLayout>
    );
  }

  // Merge all controls into a single column like the right side version
  const rightColumnContent = (
    <>
      {/* File Browser Controls */}
      <div className="unit-status-table-container" style={{ marginBottom: '8px' }}>
        <div className="file-browser-container">
          <div className="file-browser-controls">
            <button
              onClick={openFileBrowser}
              className="file-browser-button"
            >
              📁 Replay Files
            </button>
            {selectedFileName && (
              <span className="file-browser-filename">
                {selectedFileName}
                {replayData?.metadata?.template && (
                  <span className="file-browser-template">
                    [{replayData.metadata.template}]
                  </span>
                )}
              </span>
            )}
          </div>
          {fileError && (
            <div className="file-browser-error">
              {fileError}
            </div>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
      </div>

      {/* Combined Replay Controls with Turn/Phase Navigation */}
      <div className="replay-controls">
        {/* Top row with buttons and step info */}
        <div className="replay-controls__top-row">
          <div className="replay-controls__buttons">
            <button 
              className="btn btn--secondary" 
              onClick={goToStart} 
              disabled={currentStep === 0}
              title="Back to the start"
            >
              ⏮⏮
            </button>
            <button 
              className="btn btn--secondary" 
              onClick={prevStep} 
              disabled={currentStep === 0}
              title="Previous step"
            >
              ⏮
            </button>
            <button 
              className="btn btn--primary" 
              onClick={togglePlay}
              title={isPlaying ? 'Pause' : 'Play'}
            >
              {isPlaying ? '⏸' : '▶'}
            </button>
            <button 
              className="btn btn--secondary" 
              onClick={nextStep} 
              disabled={!replayData || currentStep >= battleLog.length - 1}
              title="Next step"
            >
              ⏭
            </button>
            <button 
              className="btn btn--secondary" 
              onClick={goToEnd} 
              disabled={!replayData || currentStep >= battleLog.length - 1}
              title="Last step"
            >
              ⏭⏭
            </button>
          </div>
          
          {/* Progress Info */}
          <div className="replay-controls__info">
            Step {currentStep + 1} of {battleLog.length}
          </div>
        </div>
        
        {/* Progress Bar */}
        <div 
          className="replay-controls__progress-bar"
          onClick={(e) => {
            if (battleLog.length > 0) {
              const rect = e.currentTarget.getBoundingClientRect();
              const clickX = e.clientX - rect.left;
              const progressPercent = clickX / rect.width;
              const targetStep = Math.floor(progressPercent * battleLog.length);
              const clampedStep = Math.max(0, Math.min(targetStep, battleLog.length - 1));
              goToStep(clampedStep);
            }
          }}
          style={{ cursor: 'pointer' }}
          title="Click to jump to step"
        >
          <div
            className="replay-controls__progress-fill"
            style={{
              width: battleLog.length > 0 ? `${((currentStep + 1) / battleLog.length) * 100}%` : '0%'
            }}
          />
        </div>
      </div>

      {/* Turn and Phase Tracker - Same as main game */}
      <TurnPhaseTracker 
        currentTurn={getCurrentTurn()} 
        currentPhase={getCurrentPhase()}
        className="turn-phase-tracker-right"
        maxTurns={5}
      />

      {/* Unit Status Tables for both players - only render when registry is initialized */}
      {registryInitialized && (
        <>
          <ErrorBoundary fallback={<div>Failed to load player 0 status</div>}>
            <UnitStatusTable
              units={currentUnits.map(unit => {
                const stats = getUnitStats(unit.unit_type);
                return {
                  ...unit,
                  name: unit.unit_type,
                  type: unit.unit_type,
                  color: unit.COLOR,
                  // Use getUnitStats which works correctly - NO DEFAULTS
                  MOVE: stats.MOVE,
                  HP_MAX: stats.HP_MAX,
                  RNG_RNG: stats.RNG_RNG,
                  RNG_DMG: stats.RNG_DMG,
                  RNG_NB: stats.RNG_NB,
                  RNG_ATK: stats.RNG_ATK,
                  RNG_STR: stats.RNG_STR,
                  RNG_AP: stats.RNG_AP,
                  CC_DMG: stats.CC_DMG,
                  CC_NB: stats.CC_NB,
                  CC_ATK: stats.CC_ATK,
                  CC_STR: stats.CC_STR,
                  CC_AP: stats.CC_AP,
                  CC_RNG: stats.CC_RNG,
                  T: stats.T,
                  ARMOR_SAVE: stats.ARMOR_SAVE,
                  SHOOT_LEFT: stats.RNG_NB
                };
              })}
              player={0}
              selectedUnitId={actingUnitId}
              clickedUnitId={actingUnitId}
              onSelectUnit={() => {}} // No manual selection in replay mode
            />
          </ErrorBoundary>

          <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
            <UnitStatusTable
              units={currentUnits.map(unit => {
                const stats = getUnitStats(unit.unit_type);
                return {
                  ...unit,
                  name: unit.unit_type,
                  type: unit.unit_type,
                  color: unit.COLOR,
                  // Use getUnitStats which works correctly - NO DEFAULTS
                  MOVE: stats.MOVE,
                  HP_MAX: stats.HP_MAX,
                  RNG_RNG: stats.RNG_RNG,
                  RNG_DMG: stats.RNG_DMG,
                  RNG_NB: stats.RNG_NB,
                  RNG_ATK: stats.RNG_ATK,
                  RNG_STR: stats.RNG_STR,
                  RNG_AP: stats.RNG_AP,
                  CC_DMG: stats.CC_DMG,
                  CC_NB: stats.CC_NB,
                  CC_ATK: stats.CC_ATK,
                  CC_STR: stats.CC_STR,
                  CC_AP: stats.CC_AP,
                  CC_RNG: stats.CC_RNG,
                  T: stats.T,
                  ARMOR_SAVE: stats.ARMOR_SAVE,
                  SHOOT_LEFT: stats.RNG_NB
                };
              })}
              player={1}
              selectedUnitId={actingUnitId}
              clickedUnitId={actingUnitId}
              onSelectUnit={() => {}} // No manual selection in replay mode
            />
          </ErrorBoundary>
        </>
      )}

      {/* Training Log - Same format as PvP Game Log */}
      <div className="game-log">
        <div className="game-log__header">
          <h3 className="game-log__title">Training Log</h3>
          <div className="game-log__count">
            {battleLog.length} actions
          </div>
        </div>
        <div className="game-log__content">
          {battleLog.length === 0 ? (
            <div className="game-log__empty">No actions yet...</div>
          ) : (
            <div className="game-log__events">
              {(() => {
                // First sort the entire battleLog by ID, then slice
                const sortedBattleLog = [...battleLog].sort((a: any, b: any) => {
                  const aId = parseInt(a.id) || 0;
                  const bId = parseInt(b.id) || 0;
                  return aId - bId; // Ascending order (chronological)
                });
                
                // Then slice to get events up to current step, and reverse for display (newest first)
                const eventsToDisplay = sortedBattleLog.slice(0, currentStep + 1).reverse();
                
                return eventsToDisplay;
              })().map((event: any, index: number) => {
                const originalIndex = battleLog.indexOf(event);
                const rawEvent = event as any;
                
                // Only new format (combat_log) is supported
                const eventType = rawEvent.type;
                
                // Determine event type for proper icon and styling
                const getEventIcon = (eventType: string): string => {
                  const iconMap: Record<string, string> = {
                    'move': '👟',
                    'shoot': '🎯', 
                    'charge': '⚡',
                    'combat': '⚔️',
                    'death': '💀',
                    'turn_change': '🔄',
                    'phase_change': '📋'
                  };
                  return iconMap[eventType] || '📝';
                };
                
                const getEventTypeClass = (eventType: string, rawEvent: any): string => {
                  if (eventType === 'shoot') {
                    // Check shootDetails for actual damage dealt
                    if (rawEvent.shootDetails && Array.isArray(rawEvent.shootDetails)) {
                      const hasWounds = rawEvent.shootDetails.some((shot: any) => shot.damageDealt && shot.damageDealt > 0);
                      const hasSaves = rawEvent.shootDetails.some((shot: any) => shot.saveSuccess === true);
                      
                      if (hasWounds) {
                        return 'game-log-entry--shoot-damage'; // Red - damage dealt
                      } else if (hasSaves) {
                        return 'game-log-entry--shoot-saved'; // Orange - armor saved
                      }
                    }
                    return 'game-log-entry--shoot-failed'; // Yellow - missed
                  }
                  
                  if (eventType === 'combat') {
                    // Check shootDetails for actual combat damage dealt (same structure as shooting)
                    if (rawEvent.shootDetails && Array.isArray(rawEvent.shootDetails)) {
                      const hasWounds = rawEvent.shootDetails.some((shot: any) => shot.damageDealt && shot.damageDealt > 0);
                      const hasSaves = rawEvent.shootDetails.some((shot: any) => shot.saveSuccess === true);
                      const hasHits = rawEvent.shootDetails.some((shot: any) => shot.hitResult === 'HIT');
                      
                      if (hasWounds) {
                        return 'game-log-entry--combat'; // Red - damage dealt
                      } else if (hasSaves || hasHits) {
                        return 'game-log-entry--combat-no-damage'; // Gray - hit but no damage
                      }
                    }
                    return 'game-log-entry--combat-failed'; // Orange - complete miss
                  }
                  
                  const classMap: Record<string, string> = {
                    'move': 'game-log-entry--move',
                    'charge': 'game-log-entry--charge', 
                    'death': 'game-log-entry--death',
                    'turn_change': 'game-log-entry--turn',
                    'phase_change': 'game-log-entry--phase'
                  };
                  return classMap[eventType] || 'game-log-entry--default';
                };
                
                return (
                  <div 
                    key={originalIndex}
                    className={`game-log-entry ${getEventTypeClass(eventType, rawEvent)} ${originalIndex === currentStep ? 'game-log-entry--active' : ''}`}
                    onClick={() => setCurrentStep(originalIndex)}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="game-log-entry__single-line">
                      <span className="game-log-entry__icon">{getEventIcon(eventType)}</span>
                      <span className="game-log-entry__id" style={{ fontSize: '10px', color: '#666', marginRight: '4px' }}>#{rawEvent.id}</span>
                      <span className="game-log-entry__turn">T{rawEvent.turnNumber || event.turn}</span>
                      <span className={`game-log-entry__player ${(rawEvent.player || event.player) === 0 ? 'game-log-entry__player--blue' : 'game-log-entry__player--red'}`}>
                        P{rawEvent.player || event.player}
                      </span>
                      <span className="game-log-entry__message">
                        {rawEvent.message}
                        {/* Add dice details for shooting and combat actions */}
                        {(eventType === 'shoot' || eventType === 'combat') && rawEvent.shootDetails && Array.isArray(rawEvent.shootDetails) && (
                          <span className="game-log-entry__dice-details">
                            {rawEvent.shootDetails.map((shot: any, shotIndex: number) => (
                              <span key={shotIndex} className="game-log-entry__shot-detail">
                                {rawEvent.shootDetails.length > 1 && ` - Shot ${shot.shotNumber || shotIndex + 1}:`}
                                {shot.hitTarget > 0 && (
                                  <span className={`game-log-entry__dice-roll ${shot.hitResult === 'HIT' ? 'game-log-entry__dice-roll--success' : 'game-log-entry__dice-roll--failure'}`}>
                                    {` Hit (${shot.hitTarget}+) ${shot.attackRoll}: ${shot.hitResult === 'HIT' ? 'Success!' : 'Failed!'}`}
                                  </span>
                                )}
                                {shot.hitResult === 'HIT' && shot.woundTarget > 0 && (
                                  <span className={`game-log-entry__dice-roll ${shot.strengthResult === 'SUCCESS' ? 'game-log-entry__dice-roll--success' : 'game-log-entry__dice-roll--failure'}`}>
                                    {` - Wound (${shot.woundTarget}+) ${shot.strengthRoll}: ${shot.strengthResult === 'SUCCESS' ? 'Success!' : 'Failed!'}`}
                                  </span>
                                )}
                                {shot.strengthResult === 'SUCCESS' && shot.saveTarget > 0 && (
                                  <span className={`game-log-entry__dice-roll ${shot.saveSuccess ? 'game-log-entry__dice-roll--failure' : 'game-log-entry__dice-roll--success'}`}>
                                    {` - Armor (${shot.saveTarget}+) ${shot.saveRoll}: ${shot.saveSuccess ? 'Saved!' : 'Failed!'}`}
                                  </span>
                                )}
                                {shot.damageDealt > 0 && (
                                  <span className="game-log-entry__damage">
                                    {` : -${shot.damageDealt} HP`}
                                  </span>
                                )}
                              </span>
                            ))}
                          </span>
                        )}
                      </span>
                      <span className="game-log-entry__reward">
                        {(rawEvent.reward !== undefined) ? (
                          <span 
                            className={`game-log-entry__reward-value ${(rawEvent.reward || 0) >= 0 ? 'game-log-entry__reward-value--positive' : 'game-log-entry__reward-value--negative'}`}
                          >
                            {(rawEvent.reward || 0) >= 0 ? '+' : ''}{(rawEvent.reward || 0)?.toFixed(1)}
                          </span>
                        ) : (
                          <span className="game-log-entry__reward-value--none">-</span>
                        )}
                      </span>
                      <span style={{ fontSize: '11px', color: '#888', marginLeft: '8px' }}>
                        {rawEvent.actionName || eventType}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );

  return (
    <SharedLayout rightColumnContent={rightColumnContent}>
      <div 
        ref={boardRef} 
        className="board"
      />
    </SharedLayout>
  );
};