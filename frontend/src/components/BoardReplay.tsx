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
import { hasLineOfSight, offsetToCube, cubeDistance, getHexLine } from '../utils/gameHelpers';
import { getEventIcon, getEventTypeClass } from '../../../shared/gameLogStructure';
import { GameLog } from './GameLog';

// Pathfinding utilities now imported from gameHelpers (same as BoardPvp.tsx)

const calculateAvailableMoveCells = (unitCol: number, unitRow: number, maxMove: number, boardConfig: any, units: ReplayUnit[], currentPlayer: number): { col: number; row: number }[] => {
  if (!boardConfig) return [];
  
  const BOARD_COLS = boardConfig.cols;
  const BOARD_ROWS = boardConfig.rows;
  
  const visited = new Map<string, number>();
  const queue: [number, number, number][] = [[unitCol, unitRow, 0]];
  
  // Use cube coordinate system for proper hex neighbors
  const cubeDirections = [
    [1, -1, 0], [1, 0, -1], [0, 1, -1], 
    [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
  ];
  
  // Collect all forbidden hexes (adjacent to any enemy + wall hexes + dead units) using cube coordinates  
  const forbiddenSet = new Set<string>();
  
  // Add all wall hexes as forbidden
  const wallHexSet = new Set<string>(
    (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
  );
  wallHexSet.forEach(wallHex => forbiddenSet.add(wallHex));
  
  // Add dead unit positions as forbidden
  units.filter(unit => !unit.alive).forEach(deadUnit => {
    forbiddenSet.add(`${deadUnit.col},${deadUnit.row}`);
  });
  
  // Use the provided current player instead of guessing from position
  const movingUnitPlayer = currentPlayer;
  
  // Only forbid hexes adjacent to ENEMY units, not friendly units
  for (const unit of units) {
    // Skip dead units
    if (!unit.alive) continue;
    
    // Skip friendly units - only enemy units create forbidden zones
    if (unit.player === movingUnitPlayer) continue;
    
    // Add enemy position itself as forbidden destination
    forbiddenSet.add(`${unit.col},${unit.row}`);

    // Add hexes adjacent to enemies as forbidden DESTINATIONS only
    const enemyCube = offsetToCube(unit.col, unit.row);
    for (const [dx, dy, dz] of cubeDirections) {
      const adjCube = {
        x: enemyCube.x + dx,
        y: enemyCube.y + dy,
        z: enemyCube.z + dz
      };
      
      // Convert back to offset coordinates
      const adjCol = adjCube.x;
      const adjRow = adjCube.z + ((adjCube.x - (adjCube.x & 1)) >> 1);
      
      if (
        adjCol >= 0 && adjCol < BOARD_COLS &&
        adjRow >= 0 && adjRow < BOARD_ROWS
      ) {
        forbiddenSet.add(`${adjCol},${adjRow}`);
      }
    }
  }

  const availableCells: { col: number; row: number }[] = [];

  while (queue.length > 0) {
    const next = queue.shift();
    if (!next) continue;
    const [col, row, steps] = next;
    const key = `${col},${row}`;
    
    if (visited.has(key) && steps >= visited.get(key)!) {
      continue;
    }

    visited.set(key, steps);

    // ⛔ Allow units to move FROM forbidden positions (flee mechanic) - expansion check removed

    const blocked = units.some(u => u.col === col && u.row === row && !(u.col === unitCol && u.row === unitRow));

    if (steps > 0 && steps <= maxMove && !blocked && !forbiddenSet.has(key)) {
      availableCells.push({ col, row });
    }

    if (steps >= maxMove) {
      continue;
    }

    // Use cube coordinates for proper hex neighbors
    const currentCube = offsetToCube(col, row);
    for (const [dx, dy, dz] of cubeDirections) {
      const neighborCube = {
        x: currentCube.x + dx,
        y: currentCube.y + dy,
        z: currentCube.z + dz
      };
      
      // Convert back to offset coordinates
      const ncol = neighborCube.x;
      const nrow = neighborCube.z + ((neighborCube.x - (neighborCube.x & 1)) >> 1);
      
      const nkey = `${ncol},${nrow}`;
      const nextSteps = steps + 1;

      if (
        ncol >= 0 && ncol < BOARD_COLS &&
        nrow >= 0 && nrow < BOARD_ROWS &&
        nextSteps <= maxMove &&
        !forbiddenSet.has(nkey)
      ) {
        const nblocked = units.some(u => u.col === ncol && u.row === nrow && !(u.col === unitCol && u.row === unitRow));
        // Wall hexes are already handled by forbiddenSet above
        
        if (
          !nblocked &&
          (!visited.has(nkey) || visited.get(nkey)! > nextSteps)
        ) {
          queue.push([ncol, nrow, nextSteps]);
        }
      }
    }
  }
  
  return availableCells;
};

// Import line of sight utilities from gameHelpers (same as BoardPvp.tsx)

// hasLineOfSight now imported from gameHelpers (same as BoardPvp.tsx)

const calculateChargeTargets = (
  chargerCol: number,
  chargerRow: number,
  chargeRoll: number,
  boardConfig: any,
  units: ReplayUnit[]
): {
  chargeCells: { col: number; row: number }[];
  adjacentToEnemyCells: { col: number; row: number }[];
} => {
  const chargeCells: { col: number; row: number }[] = [];
  const adjacentToEnemyCells: { col: number; row: number }[] = [];
  
  if (!boardConfig) return { chargeCells, adjacentToEnemyCells };
  
  const BOARD_COLS = boardConfig.cols;
  const BOARD_ROWS = boardConfig.rows;
  
  const visited = new Map<string, number>();
  const queue: [number, number, number][] = [[chargerCol, chargerRow, 0]];
  
  // Use cube coordinate system for proper hex neighbors
  const cubeDirections = [
    [1, -1, 0], [1, 0, -1], [0, 1, -1], 
    [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
  ];
  
  // CRITICAL FIX: Add wall hexes to forbidden set for charge pathfinding
  const forbiddenSet = new Set<string>();
  
  // Add wall hexes as forbidden (EXACT from useGameActions.ts)
  const wallHexSet = new Set<string>(
    (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
  );
  wallHexSet.forEach(wallHex => forbiddenSet.add(wallHex));
  
  // Add occupied unit positions as forbidden (including dead units)
  units.forEach(unit => {
    forbiddenSet.add(`${unit.col},${unit.row}`);
  });
  
  // Find the charging unit to determine which player we're calculating for
  const chargingUnit = units.find(u => u.col === chargerCol && u.row === chargerRow);
  if (!chargingUnit) return { chargeCells, adjacentToEnemyCells };

  const availableCells: { col: number; row: number }[] = [];

  while (queue.length > 0) {
    const next = queue.shift();
    if (!next) continue;
    const [col, row, steps] = next;
    const key = `${col},${row}`;
    
    if (visited.has(key) && steps >= visited.get(key)!) {
      continue;
    }

    visited.set(key, steps);

    // For charges, units can move FROM any position (including adjacent to enemies)
    const blocked = units.some(u => u.col === col && u.row === row && !(u.col === chargerCol && u.row === chargerRow));

    // Check if this position is adjacent to a chargeable enemy and within charge range
    if (steps > 0 && steps <= chargeRoll && !blocked && !forbiddenSet.has(key)) {
      availableCells.push({ col, row });
    }

    if (steps >= chargeRoll) {
      continue;
    }

    // Use cube coordinates for proper hex neighbors
    const currentCube = offsetToCube(col, row);
    for (const [dx, dy, dz] of cubeDirections) {
      const neighborCube = {
        x: currentCube.x + dx,
        y: currentCube.y + dy,
        z: currentCube.z + dz
      };
      
      // Convert back to offset coordinates
      const ncol = neighborCube.x;
      const nrow = neighborCube.z + ((neighborCube.x - (neighborCube.x & 1)) >> 1);
      
      const nkey = `${ncol},${nrow}`;
      const nextSteps = steps + 1;

      if (
        ncol >= 0 && ncol < BOARD_COLS &&
        nrow >= 0 && nrow < BOARD_ROWS &&
        nextSteps <= chargeRoll &&
        (!visited.has(nkey) || visited.get(nkey)! > nextSteps)
      ) {
        queue.push([ncol, nrow, nextSteps]);
      }
    }
  }
  
  // Find enemy units for this charging unit - only consider enemies within charge roll range
  const enemyUnits = units.filter(u => u.player !== chargingUnit.player && u.alive);
  const enemiesInChargeRange = enemyUnits.filter(enemy => {
    const distanceToEnemy = Math.max(Math.abs(chargerCol - enemy.col), Math.abs(chargerRow - enemy.row));
    return distanceToEnemy <= Math.min(chargeRoll, 12); // Respect both charge roll and 12-hex limit
  });
  
  // Check each available cell to see if it's adjacent to an enemy WITHIN CHARGE RANGE
  availableCells.forEach(cell => {
    const isAdjacentToEnemyInRange = enemiesInChargeRange.some(enemy => {
      const distance = Math.max(Math.abs(cell.col - enemy.col), Math.abs(cell.row - enemy.row));
      return distance === 1; // Adjacent means distance of 1
    });
    
    if (isAdjacentToEnemyInRange) {
      adjacentToEnemyCells.push(cell);
    } else {
      chargeCells.push(cell);
    }
  });
  
  return { chargeCells, adjacentToEnemyCells };
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
  const BOARD_COLS = boardConfig.cols;
  const BOARD_ROWS = boardConfig.rows;
  
  // EXACT COPY of BoardPvP.tsx shooting logic
  // First, find all enemies in range and mark cover paths
  const coverPathHexes = new Set<string>();
  const enemyUnits = units.filter(u => u.alive);
  const shootingUnit = units.find(u => u.col === shooterCol && u.row === shooterRow);
  if (!shootingUnit) return { clearTargets, coverTargets, blockedTargets };
  
  // First process actual enemy units
  for (const enemy of enemyUnits) {
    if (enemy.player === shootingUnit.player) continue;
    
    const distance = cubeDistance(shooterCube, offsetToCube(enemy.col, enemy.row));
    if (distance > 0 && distance <= range) {
      const lineOfSight = hasLineOfSight(
        { col: shooterCol, row: shooterRow },
        { col: enemy.col, row: enemy.row },
        wallHexes
      );
      
      if (lineOfSight.canSee && lineOfSight.inCover) {
        // Mark this enemy as in cover
        coverTargets.push({ col: enemy.col, row: enemy.row });
        
        // Mark all hexes in the path that contribute to cover (but exclude wall hexes)
        const pathHexes = getHexLine(shooterCol, shooterRow, enemy.col, enemy.row);
        const wallHexSet = new Set<string>(wallHexes.map(([c, r]: [number, number]) => `${c},${r}`));
        pathHexes.forEach(hex => {
          const hexKey = `${hex.col},${hex.row}`;
          if (!wallHexSet.has(hexKey)) {
            coverPathHexes.add(hexKey);
          }
        });
      } else if (lineOfSight.canSee) {
        // Clear line of sight enemy
        clearTargets.push({ col: enemy.col, row: enemy.row });
      } else {
        // Blocked enemy
        blockedTargets.add(`${enemy.col},${enemy.row}`);
      }
    }
  }
  
  // Now show all hexes in range with appropriate colors (exact PvP logic)
  for (let col = 0; col < BOARD_COLS; col++) {
    for (let row = 0; row < BOARD_ROWS; row++) {
      const targetCube = offsetToCube(col, row);
      const dist = cubeDistance(shooterCube, targetCube);
      if (dist > 0 && dist <= range) {
        const hexKey = `${col},${row}`;
        const hasEnemy = units.some(u => 
          u.player !== shootingUnit.player && 
          u.col === col && 
          u.row === row
        );
        
        if (!hasEnemy) {
          // For empty hexes, show orange if part of cover path, red if clear
          if (coverPathHexes.has(hexKey)) {
            coverTargets.push({ col, row });
          } else {
            const lineOfSight = hasLineOfSight(
              { col: shooterCol, row: shooterRow },
              { col, row },
              wallHexes
            );
            
            if (lineOfSight.canSee && !lineOfSight.inCover) {
              clearTargets.push({ col, row });
            } else if (lineOfSight.canSee && lineOfSight.inCover) {
              coverTargets.push({ col, row });
            }
          }
        }
      }
    }
  }
  
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
  
  // Track UnitStatusTable collapse states for Training Log height adjustment
  const [player0Collapsed, setPlayer0Collapsed] = useState(false);
  const [player1Collapsed, setPlayer1Collapsed] = useState(false);
  
  // Calculate available height for Training Log dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(0);
  
  // Extract log height calculation into reusable function
  const calculateAndApplyLogHeight = useCallback(() => {
    try {
      // Dynamically measure actual DOM element heights using more robust selectors
      const replayControls = document.querySelector('.replay-controls');
      const allTables = document.querySelectorAll('.unit-status-table-container');
      const gameLogHeader = document.querySelector('.game-log__header');
      const rightColumn = document.querySelector('.unit-status-tables');
      const gameLogContainer = document.querySelector('.game-log');
      
      // Handle tables that may be dynamically shown/hidden
      const player0Table = allTables[0];
      const player1Table = allTables[1];
      
      // Early return if critical elements not found (instead of throwing)
      if (!replayControls || !gameLogHeader || !rightColumn || !gameLogContainer || allTables.length < 2) {
        console.warn('Some elements not found for log height calculation, skipping...');
        return;
      }
      
      // Get actual heights from DOM measurements
      const controlsHeight = replayControls.getBoundingClientRect().height;
      const player0Height = player0Table.getBoundingClientRect().height;
      const player1Height = player1Table.getBoundingClientRect().height;
      const gameLogHeaderHeight = gameLogHeader.getBoundingClientRect().height;
      
      // Calculate log space using proven GameController.tsx approach
      const player1Rect = player1Table.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      
      // Current log start position = bottom of player 1 table + log header
      const logStartY = player1Rect.bottom + gameLogHeaderHeight;
      
      // Use configurable right column bottom position for target bottom  
      if (!boardConfig?.display?.right_column_bottom_offset) {
        console.warn('boardConfig.display.right_column_bottom_offset not found, using fallback');
        return;
      }
      
      const fixedBottomPosition = boardConfig.display.right_column_bottom_offset;
      
      // ALWAYS expand log to reach the hardcoded bottom position (250px from top)
      // Calculate how much space we need to reach exactly that position
      const targetLogBottom = fixedBottomPosition;
      const availableForLog = Math.max(100, targetLogBottom - logStartY);
      
      const logContainer = document.querySelector('.game-log__events') as HTMLElement;
      const gameLogContent = document.querySelector('.game-log__content') as HTMLElement;
      const gameLogWrapper = document.querySelector('.game-log') as HTMLElement;
      const sampleLogEntry = document.querySelector('.game-log-entry');
      
      if (logContainer && gameLogContent && gameLogWrapper && sampleLogEntry) {
        const entryHeight = sampleLogEntry.getBoundingClientRect().height;
        if (entryHeight > 0) {
          // Apply height to all log components to ensure proper expansion
          gameLogWrapper.style.height = 'auto';
          gameLogWrapper.style.maxHeight = 'none';
          gameLogWrapper.style.minHeight = `${availableForLog + 50}px`; // +50 for header
          gameLogContent.style.height = `${availableForLog}px`;
          gameLogContent.style.maxHeight = `${availableForLog}px`;
          gameLogContent.style.flex = 'none';
          logContainer.style.height = `${availableForLog}px`;
          logContainer.style.maxHeight = `${availableForLog}px`;
          logContainer.style.overflowY = 'auto';
        }
      }
      
      setLogAvailableHeight(availableForLog);
    } catch (error) {
      console.error('Error calculating log height:', error);
    }
  }, [boardConfig]);

  // Effect for initial calculation and when layout changes
  React.useEffect(() => {
    // Multiple recalculations to handle DOM timing issues
    const timer1 = setTimeout(calculateAndApplyLogHeight, 50);
    const timer2 = setTimeout(calculateAndApplyLogHeight, 150);
    const timer3 = setTimeout(calculateAndApplyLogHeight, 300);
    
    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
    };
  }, [player0Collapsed, player1Collapsed, currentUnits.length, battleLog.length, calculateAndApplyLogHeight]);

  // Additional effect for immediate recalculation when units die
  React.useEffect(() => {
    // Immediate recalculation when alive unit count changes
    const aliveUnits = currentUnits.filter(unit => unit.alive);
    if (aliveUnits.length !== currentUnits.length) {
      // Units have died, recalculate immediately and with delays
      setTimeout(calculateAndApplyLogHeight, 25);
      setTimeout(calculateAndApplyLogHeight, 100);
    }
  }, [currentUnits, calculateAndApplyLogHeight]);
  
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
  
  // Charge preview state for charge range visualization
  const [chargePreview, setChargePreview] = useState<{
    chargerCol: number;
    chargerRow: number;
    chargeCells: { col: number; row: number }[];
    adjacentToEnemyCells: { col: number; row: number }[];
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

// Transform battleLog entries to GameLogEvent format for shared GameLog component
const transformToGameLogEvents = useCallback(() => {
  return battleLog.map((event: any) => ({
    id: event.id || `event_${event.turn}_${event.unitId || 0}`,
    timestamp: new Date(event.timestamp || Date.now()),
    type: event.type,
    message: event.message,
    turnNumber: event.turnNumber || event.turn,
    phase: event.phase,
    unitType: event.unitType,
    unitId: event.unitId,
    targetUnitType: event.targetUnitType,
    targetUnitId: event.targetUnitId,
    player: event.player,
    startHex: event.startHex,
    endHex: event.endHex,
    shootDetails: event.shootDetails
  }));
}, [battleLog]);

// Helper for elapsed time calculation (same as PvP)
const getElapsedTime = useCallback((timestamp: Date): string => {
  const start = battleLog.length > 0 ? new Date(battleLog[0].timestamp || Date.now()) : new Date();
  const elapsed = (timestamp.getTime() - start.getTime()) / 1000;
  
  const minutes = Math.floor(elapsed / 60);
  const seconds = Math.floor(elapsed % 60);
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}, [battleLog]);

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
        
        setBattleLog(mappedBattleLog);
        
        // Process initial units with proper mapping - handle both formats
        let initialUnits: any[] = [];
        if (replay.initial_state?.units) {
          initialUnits = replay.initial_state.units;
        } else if (replay.game_states?.[0]?.units) {
          initialUnits = replay.game_states[0].units;
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

  // Draw charge preview hexes (light orange for movement + darker orange for adjacent to enemies)
  const drawChargePreview = useCallback((app: PIXI.Application) => {
    if (!chargePreview || !boardConfig) return;
    
    const HEX_RADIUS = boardConfig.hex_radius;
    
    // Remove existing charge preview graphics
    const existingPreview = app.stage.children.find(child => child.name === 'chargePreview');
    if (existingPreview) {
      app.stage.removeChild(existingPreview);
      existingPreview.destroy();
    }
    
    const previewContainer = new PIXI.Container();
    previewContainer.name = 'chargePreview';
    previewContainer.zIndex = 1; // Below units but above board
    
    // Draw light orange hexes for charge movement cells
    const lightOrangeColor = 0xFFB366; // Light orange
    chargePreview.chargeCells.forEach(cell => {
      const center = getHexCenter(cell.col, cell.row);
      const cellHex = new PIXI.Graphics();
      const points = getHexPolygonPoints(center.x, center.y, HEX_RADIUS * 0.8);
      cellHex.beginFill(lightOrangeColor, 0.5); // Light orange with transparency
      cellHex.drawPolygon(points);
      cellHex.endFill();
      previewContainer.addChild(cellHex);
    });
    
    // Draw darker orange hexes for cells adjacent to enemies
    const darkOrangeColor = 0xFF8000; // Darker orange
    chargePreview.adjacentToEnemyCells.forEach(cell => {
      const center = getHexCenter(cell.col, cell.row);
      const cellHex = new PIXI.Graphics();
      const points = getHexPolygonPoints(center.x, center.y, HEX_RADIUS * 0.8);
      cellHex.beginFill(darkOrangeColor, 0.7); // Darker orange with more opacity
      cellHex.drawPolygon(points);
      cellHex.endFill();
      previewContainer.addChild(cellHex);
    });
    
    app.stage.addChild(previewContainer);
  }, [chargePreview, boardConfig, getHexCenter, getHexPolygonPoints]);

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
      
      console.log('🟢 movePreview state in main useEffect:', movePreview);
      
      // Generate move preview cells like BoardPvp.tsx
      let availableCells: { col: number; row: number }[] = [];
      if (movePreview && movePreview.path) {
        availableCells = movePreview.path;
        console.log('🟢 availableCells generated:', availableCells);
      }
      
      // Calculate dead unit positions to exclude from previews
      const deadUnitPositions = new Set(
        currentUnits.filter(unit => !unit.alive).map(unit => `${unit.col},${unit.row}`)
      );

      // Draw initial board and units using shared BoardRenderer with previews
      drawBoard(app, boardConfig as any, {
        availableCells: availableCells.filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        attackCells: (shootingPreview?.clearTargets || []).filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        coverCells: (shootingPreview?.coverTargets || []).filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        chargeCells: (chargePreview?.chargeCells || []).filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        blockedTargets: shootingPreview?.blockedTargets || new Set(),
        coverTargets: new Set(),
        phase: chargePreview ? 'charge' : (shootingPreview ? 'shoot' : 'move')
      });
      drawUnits(app, currentUnits, actingUnitId);
      drawChargePreview(app); // Add charge preview drawing
      drawUnits(app, currentUnits, actingUnitId);
      
      // Draw darkened origin unit for move preview
      if (movePreview) {
        const movingUnit = currentUnits.find(u => u.id === movePreview.unitId);
        if (movingUnit && movingUnit.ICON) {
          const HEX_RADIUS = boardConfig!.hex_radius;
          const MARGIN = boardConfig!.margin;
          const HEX_WIDTH = 1.5 * HEX_RADIUS;
          const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
          const HEX_HORIZ_SPACING = HEX_WIDTH;
          const HEX_VERT_SPACING = HEX_HEIGHT;
          
          const originCenterX = movePreview.fromCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const originCenterY = movePreview.fromRow * HEX_VERT_SPACING + ((movePreview.fromCol % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          
          const iconPath = movingUnit.player === 1 ? movingUnit.ICON.replace('.webp', '_red.webp') : movingUnit.ICON;
          const texture = PIXI.Texture.from(iconPath);
          const originSprite = new PIXI.Sprite(texture);
          originSprite.anchor.set(0.5);
          originSprite.position.set(originCenterX, originCenterY);
          const unitIconScale = movingUnit.ICON_SCALE || (displayConfig?.icon_scale || 1.2);
          originSprite.width = HEX_RADIUS * unitIconScale;
          originSprite.height = HEX_RADIUS * unitIconScale;
          originSprite.alpha = 0.6; // More visible darkened origin
          originSprite.zIndex = 200; // Higher than normal units to ensure visibility
          app.stage.addChild(originSprite);
        }
      }
      
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
  }, [scenario, replayData, drawUnits, drawMovePreview, drawShootingPreview, drawChargePreview, currentUnits, actingUnitId, movePreview, shootingPreview, chargePreview]);

  // Update previews when they change
  useEffect(() => {
    if (pixiAppRef.current && boardConfig) {
      // Generate move preview cells like BoardPvp.tsx
      let availableCells: { col: number; row: number }[] = [];
      if (movePreview && movePreview.path) {
        availableCells = movePreview.path;
      }
      
      // Calculate dead unit positions to exclude from previews
      const deadUnitPositions = new Set(
        currentUnits.filter(unit => !unit.alive).map(unit => `${unit.col},${unit.row}`)
      );

      // Redraw board with preview hexes
      drawBoard(pixiAppRef.current, boardConfig as any, {
        availableCells: availableCells.filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        attackCells: (shootingPreview?.clearTargets || []).filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        coverCells: (shootingPreview?.coverTargets || []).filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        chargeCells: (chargePreview?.chargeCells || []).filter(cell => !deadUnitPositions.has(`${cell.col},${cell.row}`)),
        blockedTargets: shootingPreview?.blockedTargets || new Set(),
        coverTargets: new Set(),
        phase: chargePreview ? 'charge' : (shootingPreview ? 'shoot' : 'move')
      });
      drawUnits(pixiAppRef.current, currentUnits, actingUnitId);
      drawChargePreview(pixiAppRef.current); // Add charge preview drawing
      
      // Also add darkened origin unit in update effect
      if (movePreview) {
        const movingUnit = currentUnits.find(u => u.id === movePreview.unitId);
        if (movingUnit && movingUnit.ICON) {
          const displayConfig = boardConfig?.display;
          const HEX_RADIUS = boardConfig!.hex_radius;
          const MARGIN = boardConfig!.margin;
          const HEX_WIDTH = 1.5 * HEX_RADIUS;
          const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
          const HEX_HORIZ_SPACING = HEX_WIDTH;
          const HEX_VERT_SPACING = HEX_HEIGHT;
          
          const originCenterX = movePreview.fromCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const originCenterY = movePreview.fromRow * HEX_VERT_SPACING + ((movePreview.fromCol % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          
          const iconPath = movingUnit.player === 1 ? movingUnit.ICON.replace('.webp', '_red.webp') : movingUnit.ICON;
          const texture = PIXI.Texture.from(iconPath);
          const originSprite = new PIXI.Sprite(texture);
          originSprite.anchor.set(0.5);
          originSprite.position.set(originCenterX, originCenterY);
          const unitIconScale = movingUnit.ICON_SCALE || (displayConfig?.icon_scale || 1.2);
          originSprite.width = HEX_RADIUS * unitIconScale;
          originSprite.height = HEX_RADIUS * unitIconScale;
          originSprite.alpha = 0.6;
          originSprite.zIndex = 400; // Even higher z-index
          pixiAppRef.current.stage.addChild(originSprite);
        }
      }
    }
  }, [movePreview, shootingPreview, chargePreview, currentUnits, actingUnitId, boardConfig, drawUnits]);

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
          HP_MAX: stats.HP_MAX ?? unit.hp_max,
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
            // CRITICAL FIX: Parse coordinates properly from "(col, row)" format
            const endMatch = event.endHex.match(/\((\d+),\s*(\d+)\)/);
            if (endMatch) {
              const newCol = parseInt(endMatch[1]);
              const newRow = parseInt(endMatch[2]);
              unit.col = newCol;
              unit.row = newRow;
            console.log(`📍 Unit ${unit.id} moved to (${newCol}, ${newRow}) from endHex: ${event.endHex}`);
            } else {
              console.error(`❌ Failed to parse endHex coordinates: ${event.endHex}`);
            }
          }
        }
        
        // Process charge events
        if (event.type === 'charge' && event.unitId !== undefined) {
          const unit = newUnits.find(u => u.id === event.unitId);
          if (unit && event.endHex) {
            // CRITICAL FIX: Parse coordinates properly from "(col, row)" format for charges
            const endMatch = event.endHex.match(/\((\d+),\s*(\d+)\)/);
            if (endMatch) {
              const newCol = parseInt(endMatch[1]);
              const newRow = parseInt(endMatch[2]);
              unit.col = newCol;
              unit.row = newRow;
              console.log(`⚡ Unit ${unit.id} charged to (${newCol}, ${newRow}) from endHex: ${event.endHex}`);
            } else {
              console.error(`❌ Failed to parse charge endHex coordinates: ${event.endHex}`);
            }
          }
        }
        
        // Process damage events (shoot/combat)
        if ((event.type === 'shoot' || event.type === 'combat') && event.targetUnitId !== undefined) {
          const targetUnit = newUnits.find(u => u.id === event.targetUnitId);
          if (targetUnit && event.shootDetails && Array.isArray(event.shootDetails)) {
            const totalDamage = event.shootDetails.reduce((sum: number, shot: any) => {
              if (shot.damageDealt === undefined) {
                throw new Error(`Shot missing required 'damageDealt' field: ${JSON.stringify(shot)}`);
              }
              return sum + shot.damageDealt;
            }, 0);
            if (totalDamage > 0) {
              targetUnit.hp_current = Math.max(0, targetUnit.hp_current - totalDamage);
              
              // CRITICAL FIX: Only mark as dead if HP actually reaches 0
              if (targetUnit.hp_current <= 0) {
                targetUnit.alive = false;
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
      console.log('🔍 currentLogEntry:', currentLogEntry);
      if (currentLogEntry && (currentLogEntry as any).type === 'move') {
        const logEntry = currentLogEntry as any;
        console.log('🔍 Move detected! logEntry:', logEntry);
        const movingUnit = newUnits.find(u => u.id === logEntry.unitId);
        console.log('🔍 movingUnit found:', movingUnit);
        console.log('🔍 logEntry.startHex:', logEntry.startHex);
        console.log('🔍 logEntry.endHex:', logEntry.endHex);
        
        if (movingUnit && logEntry.startHex && logEntry.endHex) {
          // Parse hex coordinates from "(col, row)" format
          const startMatch = logEntry.startHex.match(/\((\d+),\s*(\d+)\)/);
          const endMatch = logEntry.endHex.match(/\((\d+),\s*(\d+)\)/);
          console.log('🔍 startMatch:', startMatch);
          console.log('🔍 endMatch:', endMatch);
          
          if (startMatch && endMatch) {
            const fromCol = parseInt(startMatch[1]);
            const fromRow = parseInt(startMatch[2]);
            const toCol = parseInt(endMatch[1]);
            const toRow = parseInt(endMatch[2]);
            console.log('🔍 Move coordinates:', { fromCol, fromRow, toCol, toRow });
            
            // Calculate path using pathfinding
            console.log('🔍 Unit MOVE value:', movingUnit.MOVE);
            console.log('🔍 Current units for pathfinding:', newUnits.map(u => ({ id: u.id, col: u.col, row: u.row, alive: u.alive })));
            const availableCells = calculateAvailableMoveCells(fromCol, fromRow, movingUnit.MOVE, boardConfig, newUnits, logEntry.player || 0);
            console.log('🔍 Available move cells:', availableCells);
            
            if (availableCells.length > 0) {
              console.log('🟢 Setting movePreview with available cells!');
              setMovePreview({
                fromCol,
                fromRow,
                toCol,
                toRow,
                path: availableCells,
                unitId: logEntry.unitId
              });
            } else {
              console.log('❌ No available cells, setting movePreview to null');
              setMovePreview(null);
            }
          } else {
            console.log('❌ Failed to parse hex coordinates, setting movePreview to null');
            setMovePreview(null);
          }
        } else {
          console.log('❌ Missing movingUnit or hex data, setting movePreview to null');
          setMovePreview(null);
        }
        setShootingPreview(null); // Clear shooting preview during moves
      } 
      // Detect shooting actions and set up shooting preview (following BoardPvp.tsx pattern)
      else if (currentLogEntry && (currentLogEntry as any).type === 'shoot') {
        const logEntry = currentLogEntry as any;
        const shootingUnit = newUnits.find(u => u.id === logEntry.unitId);
        
        if (shootingUnit && shootingUnit.RNG_RNG) {
          const shooterCube = offsetToCube(shootingUnit.col, shootingUnit.row);
          const wallHexes = boardConfig?.wall_hexes || [];
          const range = shootingUnit.RNG_RNG;
          
          const clearTargets: { col: number; row: number }[] = [];
          const coverTargets: { col: number; row: number }[] = [];
          const blockedTargets = new Set<string>();
          const coverTargetsSet = new Set<string>();
          
          // First, find all enemies in range and mark cover paths (exact PvP logic)
          const coverPathHexes = new Set<string>();
          const enemyUnits = newUnits.filter(u => u.player !== shootingUnit.player && u.alive);
          
          // Process actual enemy units first
          for (const enemy of enemyUnits) {
            const distance = cubeDistance(shooterCube, offsetToCube(enemy.col, enemy.row));
            if (distance > 0 && distance <= range) {
              const lineOfSight = hasLineOfSight(
                { col: shootingUnit.col, row: shootingUnit.row },
                { col: enemy.col, row: enemy.row },
                wallHexes
              );
              
              if (lineOfSight.canSee && lineOfSight.inCover) {
                // Mark this enemy as in cover
                coverTargets.push({ col: enemy.col, row: enemy.row });
                coverTargetsSet.add(`${enemy.col},${enemy.row}`);
                
                // Mark all hexes in the path that contribute to cover (but exclude wall hexes)
                const pathHexes = getHexLine(shootingUnit.col, shootingUnit.row, enemy.col, enemy.row);
                const wallHexSet = new Set<string>(wallHexes.map(([c, r]: [number, number]) => `${c},${r}`));
                pathHexes.forEach(hex => {
                  const hexKey = `${hex.col},${hex.row}`;
                  if (!wallHexSet.has(hexKey)) {
                    coverPathHexes.add(hexKey);
                  }
                });
              } else if (lineOfSight.canSee) {
                // Clear line of sight enemy
                clearTargets.push({ col: enemy.col, row: enemy.row });
              } else {
                // Blocked enemy
                blockedTargets.add(`${enemy.col},${enemy.row}`);
              }
            }
          }
          
          // Now show all hexes in range with appropriate colors (exact PvP logic)
          for (let col = 0; col < (boardConfig?.cols || 0); col++) {
            for (let row = 0; row < (boardConfig?.rows || 0); row++) {
              const targetCube = offsetToCube(col, row);
              const dist = cubeDistance(shooterCube, targetCube);
              if (dist > 0 && dist <= range) {
                const hexKey = `${col},${row}`;
                const hasEnemy = newUnits.some(u => 
                  u.player !== shootingUnit.player && 
                  u.col === col && 
                  u.row === row
                );
                
                if (!hasEnemy) {
                  // For empty hexes, show orange if part of cover path, red if clear
                  if (coverPathHexes.has(hexKey)) {
                    coverTargets.push({ col, row });
                  } else {
                    const lineOfSight = hasLineOfSight(
                      { col: shootingUnit.col, row: shootingUnit.row },
                      { col, row },
                      wallHexes
                    );
                    
                    if (lineOfSight.canSee && !lineOfSight.inCover) {
                      clearTargets.push({ col, row });
                    } else if (lineOfSight.canSee && lineOfSight.inCover) {
                      coverTargets.push({ col, row });
                    }
                  }
                }
              }
            }
          }
          
          setShootingPreview({
            shooterCol: shootingUnit.col,
            shooterRow: shootingUnit.row,
            clearTargets,
            coverTargets,
            blockedTargets,
            unitId: logEntry.unitId,
            range: shootingUnit.RNG_RNG
          });
        } else {
          setShootingPreview(null);
        }
        setMovePreview(null); // Clear move preview during shooting
        setChargePreview(null); // Clear charge preview during shooting
      }
      // Detect charge actions and set up charge preview
      else if (currentLogEntry && (currentLogEntry as any).type === 'charge') {
        const logEntry = currentLogEntry as any;
        const chargingUnit = newUnits.find(u => u.id === logEntry.unitId);
        
        if (chargingUnit && chargingUnit.MOVE) {
          // Calculate charge preview using same pathfinding as moves
          const { chargeCells, adjacentToEnemyCells } = calculateChargeTargets(
            chargingUnit.col, 
            chargingUnit.row, 
            chargingUnit.MOVE, 
            boardConfig, 
            newUnits
          );
          
          setChargePreview({
            chargerCol: chargingUnit.col,
            chargerRow: chargingUnit.row,
            chargeCells,
            adjacentToEnemyCells,
            unitId: logEntry.unitId,
            range: chargingUnit.MOVE
          });
        } else {
          setChargePreview(null);
        }
        setMovePreview(null); // Clear move preview during charges
        setShootingPreview(null); // Clear shooting preview during charges
      } else {
        setMovePreview(null);
        setShootingPreview(null);
        setChargePreview(null);
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
              gameMode="training"
              onCollapseChange={setPlayer0Collapsed}
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
              gameMode="training"
              onCollapseChange={setPlayer1Collapsed}
            />
          </ErrorBoundary>
        </>
      )}

      {/* Use shared GameLog component - exactly like PvP mode */}
      <GameLog
        events={transformToGameLogEvents().slice(0, currentStep + 1)}
        maxEvents={Math.floor(logAvailableHeight / 40)}
        getElapsedTime={getElapsedTime}
        availableHeight={logAvailableHeight}
        useStepNumbers={true}
      />
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