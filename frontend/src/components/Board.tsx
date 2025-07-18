// frontend/src/components/Board.tsx
import React, { useEffect, useRef, useState } from "react";
import * as PIXI from "pixi.js-legacy";
import type { Unit, TargetPreview } from "../types/game";
import { useGameConfig } from '../hooks/useGameConfig';
import { SingleShotDisplay } from './SingleShotDisplay';
import { setupBoardClickHandler } from '../utils/boardClickHandler';
import { renderUnit } from './UnitRenderer';

// For flat-topped hex, even-q offset (col, row)
function offsetToCube(col: number, row: number) {
  const x = col;
  const z = row - ((col - (col & 1)) >> 1);
  const y = -x - z;
  return { x, y, z };
}

function cubeDistance(a: { x: number, y: number, z: number }, b: { x: number, y: number, z: number }) {
  return Math.max(
    Math.abs(a.x - b.x),
    Math.abs(a.y - b.y),
    Math.abs(a.z - b.z)
  );
}

function hexCorner(cx: number, cy: number, size: number, i: number) {
  const angle_deg = 60 * i;
  const angle_rad = Math.PI / 180 * angle_deg;
  return [
    cx + size * Math.cos(angle_rad),
    cy + size * Math.sin(angle_rad),
  ];
}

function getHexPolygonPoints(cx: number, cy: number, size: number) {
  return Array.from({ length: 6 }, (_, i) => hexCorner(cx, cy, size, i)).flat();
}

type Mode = "select" | "movePreview" | "attackPreview" | "chargePreview";

type BoardProps = {
  units: Unit[];
  selectedUnitId: number | null;
  mode: Mode;
  movePreview: { unitId: number; destCol: number; destRow: number } | null;
  attackPreview: { unitId: number; col: number; row: number } | null;
  onSelectUnit: (id: number | string | null) => void;
  onStartMovePreview: (unitId: number | string, col: number | string, row: number | string) => void;
  onStartAttackPreview: (unitId: number, col: number, row: number) => void;
  onConfirmMove: () => void;
  onCancelMove: () => void;
  onShoot: (shooterId: number, targetId: number) => void;
  onCombatAttack?: (attackerId: number, targetId: number | null) => void;
  currentPlayer: 0 | 1;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  unitsFled?: number[];
  phase: "move" | "shoot" | "charge" | "combat";
  onCharge?: (chargerId: number, targetId: number) => void;
  onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
  onCancelCharge?: () => void;
  onValidateCharge?: (chargerId: number) => void;
  shootingPhaseState?: any;
  targetPreview?: TargetPreview | null;
  onCancelTargetPreview?: () => void;
};

export default function Board({
  units,
  selectedUnitId,
  mode,
  movePreview,
  attackPreview,
  onSelectUnit,
  onStartMovePreview,
  onStartAttackPreview,
  onConfirmMove,
  onCancelMove,
  currentPlayer,
  unitsMoved,
  phase,
  onShoot,
  onCombatAttack,
  onCharge,
  unitsCharged,
  unitsAttacked,
  unitsFled,
  onMoveCharger,
  onCancelCharge,
  onValidateCharge,
  shootingPhaseState,
  targetPreview,
  onCancelTargetPreview,
}: BoardProps) {
  React.useEffect(() => {
  }, [phase, mode, selectedUnitId]);
  
  React.useEffect(() => {
  }, [phase, mode, selectedUnitId]);

  // ✅ HOOK 1: useRef - ALWAYS called first
  const containerRef = useRef<HTMLDivElement>(null);
  
  // ✅ HOOK 2: useGameConfig - ALWAYS called second
  const { boardConfig, loading, error } = useGameConfig();
  // ✅ STABLE CALLBACK REFS - Don't change on every render
  const stableCallbacks = useRef({
    onSelectUnit,
    onStartMovePreview,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onCombatAttack,
    onCharge,
    onMoveCharger,
    onCancelCharge,
    onValidateCharge
  });

  // Update refs when props change but don't trigger re-render
  stableCallbacks.current = {
    onSelectUnit,
    onStartMovePreview,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onCombatAttack,
    onCharge,
    onMoveCharger,
    onCancelCharge,
    onValidateCharge
  };
  // ✅ HOOK 2.5: Add shooting preview state management with React state
  // ✅ REMOVE ALL ANIMATION STATE - This is causing the re-render loop
  // const [hpAnimationState, setHpAnimationState] = useState<boolean>(false);
  // const [currentShootingTarget, setCurrentShootingTarget] = useState<number | null>(null);
  // const [selectedShootingTarget, setSelectedShootingTarget] = useState<number | null>(null);
  // const animationIntervalRef = useRef<NodeJS.Timeout | null>(null);
  // const [currentCombatTarget, setCurrentCombatTarget] = useState<number | null>(null);
  // const [selectedCombatTarget, setSelectedCombatTarget] = useState<number | null>(null);

  // ✅ HOOK 3: useEffect - MINIMAL DEPENDENCIES TO PREVENT RE-RENDER LOOPS
  useEffect(() => {
    // Early returns INSIDE useEffect to avoid hooks order violation
    if (!containerRef.current) return;

    if (loading) {
      containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#1f2937;border-radius:8px;color:white;">Loading board configuration...</div>`;
      return;
    }

    if (error) {
      containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#7f1d1d;border-radius:8px;color:#fecaca;">Configuration Error: ${error}</div>`;
      return;
    }

    if (!boardConfig) {
      containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#7f1d1d;border-radius:8px;color:#fecaca;">Board configuration not loaded</div>`;
      return;
    }

    containerRef.current.innerHTML = "";

    // ✅ AGGRESSIVE TEXTURE CACHE CLEARING for movePreview units
    if (mode === "movePreview" && movePreview) {
      const previewUnit = units.find(u => u.id === movePreview.unitId);
      if (previewUnit?.ICON) {
        PIXI.Texture.removeFromCache(previewUnit.ICON);
        // Clear all cached textures to force fresh loading
        PIXI.utils.clearTextureCache();
      }
    }

    // ✅ CLEAR COMMON TEXTURE CACHE
    //PIXI.Texture.removeFromCache('/icons/AssaultIntercessor.webp');
    //PIXI.Texture.removeFromCache('/icons/AssaultIntercessor_red.webp');
    //PIXI.Texture.removeFromCache('/icons/Intercessor.webp');

    // Extract board configuration values - USE CONFIG VALUES
    const BOARD_COLS = boardConfig.cols;
    const BOARD_ROWS = boardConfig.rows;
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;

    // Parse colors from config
    const parseColor = (colorStr: string): number => {
      return parseInt(colorStr.replace('0x', ''), 16);
    };

    // ✅ ALL COLORS FROM CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight);
    const ATTACK_COLOR = parseColor(boardConfig.colors.attack!);
    const CHARGE_COLOR = parseColor(boardConfig.colors.charge!);
    const ELIGIBLE_COLOR = parseColor(boardConfig.colors.eligible!);
    console.log('🎨 BOARD.TSX DEBUG - Board colors:', {
      background: parseColor(boardConfig.colors.background),
      cell_even: parseColor(boardConfig.colors.cell_even),
      cell_odd: parseColor(boardConfig.colors.cell_odd),
      highlight: HIGHLIGHT_COLOR,
      attack: ATTACK_COLOR
    });

    // ✅ ALL DISPLAY VALUES FROM CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    if (!boardConfig.display) {
      throw new Error('Missing required boardConfig.display configuration');
    }
    const displayConfig = boardConfig.display;
    
    // ✅ VALIDATE ALL REQUIRED VALUES ARE PRESENT FIRST - DIRECT PROPERTY ACCESS
    if (displayConfig.icon_scale === undefined || displayConfig.icon_scale === null) {
      throw new Error('Missing required configuration value: boardConfig.display.icon_scale');
    }
    if (displayConfig.eligible_outline_width === undefined || displayConfig.eligible_outline_width === null) {
      throw new Error('Missing required configuration value: boardConfig.display.eligible_outline_width');
    }
    if (displayConfig.eligible_outline_alpha === undefined || displayConfig.eligible_outline_alpha === null) {
      throw new Error('Missing required configuration value: boardConfig.display.eligible_outline_alpha');
    }
    if (displayConfig.hp_bar_width_ratio === undefined || displayConfig.hp_bar_width_ratio === null) {
      throw new Error('Missing required configuration value: boardConfig.display.hp_bar_width_ratio');
    }
    if (displayConfig.hp_bar_height === undefined || displayConfig.hp_bar_height === null) {
      throw new Error('Missing required configuration value: boardConfig.display.hp_bar_height');
    }
    if (displayConfig.hp_bar_y_offset_ratio === undefined || displayConfig.hp_bar_y_offset_ratio === null) {
      throw new Error('Missing required configuration value: boardConfig.display.hp_bar_y_offset_ratio');
    }
    if (displayConfig.unit_circle_radius_ratio === undefined || displayConfig.unit_circle_radius_ratio === null) {
      throw new Error('Missing required configuration value: boardConfig.display.unit_circle_radius_ratio');
    }
    if (displayConfig.unit_text_size === undefined || displayConfig.unit_text_size === null) {
      throw new Error('Missing required configuration value: boardConfig.display.unit_text_size');
    }
    if (displayConfig.selected_border_width === undefined || displayConfig.selected_border_width === null) {
      throw new Error('Missing required configuration value: boardConfig.display.selected_border_width');
    }
    if (displayConfig.charge_target_border_width === undefined || displayConfig.charge_target_border_width === null) {
      throw new Error('Missing required configuration value: boardConfig.display.charge_target_border_width');
    }
    if (displayConfig.default_border_width === undefined || displayConfig.default_border_width === null) {
      throw new Error('Missing required configuration value: boardConfig.display.default_border_width');
    }
    if (displayConfig.canvas_border === undefined || displayConfig.canvas_border === null) {
      throw new Error('Missing required configuration value: boardConfig.display.canvas_border');
    }
    
    // ✅ VALIDATE COLOR VALUES ARE PRESENT - DIRECT PROPERTY ACCESS
    if (!boardConfig.colors.attack) {
      throw new Error('Missing required configuration value: boardConfig.colors.attack');
    }
    if (!boardConfig.colors.charge) {
      throw new Error('Missing required configuration value: boardConfig.colors.charge');
    }
    if (!boardConfig.colors.eligible) {
      throw new Error('Missing required configuration value: boardConfig.colors.eligible');
    }
    
    // ✅ NOW SAFE TO ASSIGN WITH TYPE ASSERTIONS
    const ICON_SCALE = displayConfig.icon_scale!;
    const ELIGIBLE_OUTLINE_WIDTH = displayConfig.eligible_outline_width!;
    const ELIGIBLE_OUTLINE_ALPHA = displayConfig.eligible_outline_alpha!;
    const HP_BAR_WIDTH_RATIO = displayConfig.hp_bar_width_ratio!;
    const HP_BAR_HEIGHT = displayConfig.hp_bar_height!;
    const HP_BAR_Y_OFFSET_RATIO = displayConfig.hp_bar_y_offset_ratio!;
    const UNIT_CIRCLE_RADIUS_RATIO = displayConfig.unit_circle_radius_ratio!;
    const UNIT_TEXT_SIZE = displayConfig.unit_text_size!;
    const SELECTED_BORDER_WIDTH = displayConfig.selected_border_width!;
    const CHARGE_TARGET_BORDER_WIDTH = displayConfig.charge_target_border_width!;
    const DEFAULT_BORDER_WIDTH = displayConfig.default_border_width!;
    const CANVAS_BORDER = displayConfig.canvas_border!;

    const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
    const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
    const width = gridWidth + 2 * MARGIN;
    const height = gridHeight + 2 * MARGIN;

    // ✅ OPTIMIZED PIXI CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    const pixiConfig = {
      width,
      height,
      backgroundColor: parseColor(boardConfig.colors.background),
      antialias: displayConfig.antialias!,
      powerPreference: "high-performance" as WebGLPowerPreference,
      resolution: displayConfig.resolution === "auto" ? (window.devicePixelRatio || 1) : displayConfig.resolution!,
      autoDensity: displayConfig.autoDensity!,
    };
    
    // ✅ VALIDATE PIXI CONFIG VALUES
    if (pixiConfig.antialias === undefined || pixiConfig.autoDensity === undefined) {
      throw new Error('Missing required PIXI configuration values: antialias, autoDensity, or resolution');
    }

    const app = new PIXI.Application(pixiConfig);
    app.stage.sortableChildren = true;

    // ✅ CANVAS STYLING FROM CONFIG
    const canvas = app.view as HTMLCanvasElement;
    canvas.style.display = 'block';
    canvas.style.maxWidth = '100%';
    canvas.style.height = 'auto';
    canvas.style.border = CANVAS_BORDER;
    
    containerRef.current.appendChild(canvas);

    // Right click cancels move/attack preview
    if (app.view && app.view.addEventListener) {
      app.view.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        
        if (phase === "shoot") {
          // During shooting phase, only cancel target preview if one exists
          if (targetPreview) {
            onCancelTargetPreview?.();
          }
          // If no target preview, do nothing (don't cancel the whole shooting)
        } else if (mode === "movePreview" || mode === "attackPreview") {
          onCancelMove?.();
        }
      });
    }

    // Logic for green (move) and red (attack) highlights
    let availableCells: { col: number; row: number }[] = [];
    const selectedUnit = units.find(u => u.id === selectedUnitId);

    // Charge preview: chargeCells & targets
    let chargeCells: { col: number; row: number }[] = [];
    let chargeTargets: Unit[] = [];

    // Combat preview: combatTargets for red outline on enemies within combat range
    let combatTargets: Unit[] = [];
    if (phase === "combat" && selectedUnit) {
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      
      // Validate CC_RNG is defined
      if (selectedUnit.CC_RNG === undefined || selectedUnit.CC_RNG === null) {
        throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) is missing required CC_RNG property for combat phase`);
      }
      
      const combatRange = selectedUnit.CC_RNG;
      
      // Red outline: all enemy units within combat range of the selected unit
      combatTargets = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) <= combatRange
      );
    }

    // ✅ SIMPLIFIED SHOOTING PREVIEW - No animations to prevent re-render loop
    let shootingTarget: Unit | null = null;
    if (phase === "shoot" && mode === "attackPreview" && selectedUnit && attackPreview) {
      // Validate RNG_RNG is defined
      if (selectedUnit.RNG_RNG === undefined || selectedUnit.RNG_RNG === null) {
        throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) is missing required RNG_RNG property for shooting phase`);
      }
      
      // Simple target identification - no state changes here
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      const enemiesInRange = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) <= selectedUnit.RNG_RNG
      );
      
      // Use the first valid target or null
      shootingTarget = enemiesInRange[0] || null;
    }

    // ✅ SIMPLIFIED COMBAT PREVIEW - No animations to prevent re-render loop
    let combatTarget: Unit | null = null;
    if (phase === "combat" && selectedUnit) {
      // Simple target identification - no state changes here
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      const enemiesInRange = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) === 1
      );
      
      // Use the first valid target or null
      combatTarget = enemiesInRange[0] || null;
    }

    if (phase === "charge" && mode === "chargePreview" && selectedUnit) {
      // Validate MOVE is defined first
      if (selectedUnit.MOVE === undefined || selectedUnit.MOVE === null) {
        throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) is missing required MOVE property for charge preview`);
      }
      
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);

      // Orange cells: within MOVE, not blocked, AND adjacent to at least one enemy (within MOVE)
      for (let col = 0; col < BOARD_COLS; col++) {
        for (let row = 0; row < BOARD_ROWS; row++) {
          const c2 = offsetToCube(col, row);
          const dist = cubeDistance(c1, c2);
          const blocked = units.some(u => u.col === col && u.row === row && u.id !== selectedUnit.id);
          if (
            !blocked &&
            dist > 0 && dist <= selectedUnit.MOVE
          ) {
            // Only allow if adjacent to an enemy that is also within MOVE
            const adjEnemy = units.find(u =>
              u.player !== selectedUnit.player &&
              cubeDistance(c1, offsetToCube(u.col, u.row)) <= selectedUnit.MOVE &&
              cubeDistance(offsetToCube(col, row), offsetToCube(u.col, u.row)) === 1
            );
            if (adjEnemy) {
              chargeCells.push({ col, row });
            }
          }
        }
      }

      // Red outline: all enemy units within the selected unit's MOVE
      chargeTargets = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) <= selectedUnit.MOVE
      );
    }

      // Green move cells (mode: 'select' or 'movePreview')
      if (selectedUnit && (mode === "select" || mode === "movePreview") && phase === "move") {

        const runMovementBFS = () => {
          if (selectedUnit.MOVE === undefined || selectedUnit.MOVE === null) {
            throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) is missing required MOVE property for movement preview`);
          }
          
          console.log(`🏃 Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) MOVE: ${selectedUnit.MOVE}`);

          const centerCol = selectedUnit.col;
          const centerRow = selectedUnit.row;

          const visited = new Map<string, number>();
          const queue: [number, number, number][] = [[centerCol, centerRow, 0]];

          // Use cube coordinate system for proper hex neighbors
          const cubeDirections = [
            [1, -1, 0], [1, 0, -1], [0, 1, -1], 
            [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
          ];

          // Collect all forbidden hexes (adjacent to any enemy) using cube coordinates
          const forbiddenSet = new Set<string>();
          for (const enemy of units) {
            if (enemy.player === selectedUnit.player) continue;

            // Add enemy position itself
            forbiddenSet.add(`${enemy.col},${enemy.row}`);
            console.log(`🚫 Enemy at (${enemy.col},${enemy.row}) - position forbidden`);

            // Use cube coordinates for proper hex adjacency
            const enemyCube = offsetToCube(enemy.col, enemy.row);
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
                console.log(`🚫 Hex (${adjCol},${adjRow}) forbidden - adjacent to enemy at (${enemy.col},${enemy.row})`);
              }
            }
          }

          const forbiddenList = Array.from(forbiddenSet);
          console.log("🚫 Forbidden hexes:", forbiddenList.join(" | "));


          while (queue.length > 0) {
            const next = queue.shift();
            if (!next) continue;
            const [col, row, steps] = next;
            const key = `${col},${row}`;
            console.log(`🔍 BFS processing: (${col},${row}) at step ${steps}`);
            
            if (visited.has(key) && steps >= visited.get(key)!) {
              console.log(`❌ Already visited (${col},${row}) with better/equal steps`);
              continue;
            }

            visited.set(key, steps);

            // ⛔ Skip forbidden positions completely - don't expand from them
            if (forbiddenSet.has(key) && steps > 0) {
              console.log(`❌ Skipping forbidden position (${col},${row})`);
              continue;
            }

            const blocked = units.some(u => u.col === col && u.row === row && u.id !== selectedUnit.id);

              if (steps > 0 && steps <= selectedUnit.MOVE && !blocked && !forbiddenSet.has(key)) {
                // Validate actual distance using cube coordinates
                const actualDistance = cubeDistance(offsetToCube(centerCol, centerRow), offsetToCube(col, row));
                console.log(`✅ Reachable tile: ${key} at BFS step ${steps}, actual distance ${actualDistance}`);
                availableCells.push({ col, row });
              }

              if (steps >= selectedUnit.MOVE) {
                console.log(`❌ Max steps reached at (${col},${row}) - not expanding further`);
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
                  nextSteps <= selectedUnit.MOVE &&
                  !forbiddenSet.has(nkey)
                ) {
                  const nblocked = units.some(u => u.col === ncol && u.row === nrow && u.id !== selectedUnit.id);
                  if (
                    !nblocked &&
                    (!visited.has(nkey) || visited.get(nkey)! > nextSteps)
                  ) {
                    queue.push([ncol, nrow, nextSteps]);
                  }
                }
              }

          }
        };

        runMovementBFS();
        
        console.log(`🎯 Available cells found: ${availableCells.length}`);
        console.log(`🎯 Available cells: ${availableCells.map(c => `(${c.col},${c.row})`).join(', ')}`);
      }

      // Red attack cells: Either after move (movePreview) or attackPreview
      let attackCells: { col: number; row: number }[] = [];
      let previewUnit: Unit | undefined = undefined;
      let attackFromCol: number | null = null;
      let attackFromRow: number | null = null;

      if (mode === "movePreview" && movePreview) {
        previewUnit = units.find(u => u.id === movePreview.unitId);
        attackFromCol = movePreview.destCol;
        attackFromRow = movePreview.destRow;
      } else if (mode === "attackPreview" && attackPreview) {
          const clickedUnit = units.find(u => u.id === attackPreview.unitId);
          if (clickedUnit && clickedUnit.id === selectedUnitId) {
            previewUnit = clickedUnit;
            attackFromCol = clickedUnit.col;
            attackFromRow = clickedUnit.row;
          } else {
            previewUnit = undefined;
            attackFromCol = null;
            attackFromRow = null;
          }
        } else if (phase === "shoot" && selectedUnit?.SHOOT_LEFT !== undefined && selectedUnit.SHOOT_LEFT > 0) {
          previewUnit = selectedUnit;
          attackFromCol = selectedUnit.col;
          attackFromRow = selectedUnit.row;
        }

        if (
          previewUnit &&
          attackFromCol !== null &&
          attackFromRow !== null &&
          (
            mode === "movePreview" ||
            mode === "attackPreview" ||
            (phase === "shoot" && selectedUnit?.SHOOT_LEFT !== undefined && selectedUnit.SHOOT_LEFT > 0)
          )
        ) {
          const centerCube = offsetToCube(attackFromCol, attackFromRow);
          
          // Validate required range properties are defined and get range
          let range: number;
          if (phase === "combat") {
            if (previewUnit.CC_RNG === undefined || previewUnit.CC_RNG === null) {
              throw new Error(`Unit ${previewUnit.id} (${previewUnit.type || 'unknown'}) is missing required CC_RNG property for combat phase preview`);
            }
            range = previewUnit.CC_RNG;
          } else {
            if (previewUnit.RNG_RNG === undefined || previewUnit.RNG_RNG === null) {
              throw new Error(`Unit ${previewUnit.id} (${previewUnit.type || 'unknown'}) is missing required RNG_RNG property for shooting phase preview`);
            }
            range = previewUnit.RNG_RNG;
          }
          for (let col = 0; col < BOARD_COLS; col++) {
            for (let row = 0; row < BOARD_ROWS; row++) {
              const targetCube = offsetToCube(col, row);
              const dist = cubeDistance(centerCube, targetCube);
              if (dist > 0 && dist <= range) {
                attackCells.push({ col, row });
              }
            }
          }
        }


      // ✅ OPTIMIZED: Create containers for hex batching
      const baseHexContainer = new PIXI.Container();
      const highlightContainer = new PIXI.Container();
      baseHexContainer.name = 'baseHexes';
      highlightContainer.name = 'highlights';

      // Draw grid cells with container batching
      for (let col = 0; col < BOARD_COLS; col++) {
        for (let row = 0; row < BOARD_ROWS; row++) {
          const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);
          
          // Check highlight states
          const isAvailable = availableCells.some(cell => cell.col === col && cell.row === row);
          const isAttackable = attackCells.some(cell => cell.col === col && cell.row === row);
          const isChargeable = chargeCells.some(cell => cell.col === col && cell.row === row);
          
          if (isAvailable) {
            console.log(`🟢 Highlighting available cell: (${col},${row})`);
          }

          // Create base hex (always present)
          const baseCell = new PIXI.Graphics();
          const isEven = (col + row) % 2 === 0;
          const cellColor = isEven ? parseColor(boardConfig.colors.cell_even) : parseColor(boardConfig.colors.cell_odd);
          baseCell.beginFill(cellColor, 1.0);
          baseCell.lineStyle(1, parseColor(boardConfig.colors.cell_border), 0.8);
          baseCell.drawPolygon(points);
          baseCell.endFill();
          baseHexContainer.addChild(baseCell);
          
          // Add coordinate text for debugging
          const coordText = new PIXI.Text(`${col},${row}`, {
            fontSize: 8,
            fill: 0xFFFFFF,
            align: 'center'
          });
          coordText.anchor.set(0.5);
          coordText.position.set(centerX, centerY);
          baseHexContainer.addChild(coordText);

          // Cancel charge on re-click of active unit during charge preview
            if (mode === "chargePreview" && selectedUnitId !== null) {
              const unit = units.find(u => u.id === selectedUnitId);
              if (unit && col === unit.col && row === unit.row) {
                baseCell.eventMode = 'static';
                baseCell.cursor    = "pointer";
                baseCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                  if (e.button === 0) onCancelCharge?.();
                });
              }
            }

            // Create highlight hex (only if needed)
            if (isChargeable || isAttackable || isAvailable) {
              const highlightCell = new PIXI.Graphics();

            
            if (isChargeable) {
              highlightCell.beginFill(CHARGE_COLOR, 0.5);
            } else if (isAttackable) {
              highlightCell.beginFill(ATTACK_COLOR, 0.5);
            } else if (isAvailable) {
              highlightCell.beginFill(HIGHLIGHT_COLOR, 0.5);
            }
            
            highlightCell.drawPolygon(points);
            highlightCell.endFill();

            // Make interactive (disable during charge preview)
            if (mode === "chargePreview") {
              highlightCell.eventMode = 'none';
            } else {
              highlightCell.eventMode = 'static';
            }
            highlightCell.cursor = "pointer";

            // Make base hex interactive for move confirmation
            baseCell.eventMode = 'static';

            highlightCell.cursor = "pointer";

            // Make base hex interactive for move confirmation
            baseCell.eventMode = 'static';
            baseCell.cursor = "pointer";
            
            // Add click handlers to base hexes
            if (mode === "movePreview" || mode === "attackPreview") {
              baseCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                if (e.button === 0) onConfirmMove();
                if (e.button === 2) onCancelMove();
              });
            } else if (mode === "chargePreview" && selectedUnitId !== null) {
              baseCell.eventMode = 'static';
              baseCell.cursor    = "pointer";
              baseCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                if (e.button !== 0) return;
                const unit = units.find(u => u.id === selectedUnitId);
                if (unit?.col === col && unit.row === row) {
                  onCancelCharge?.();
                } else if (isChargeable) {
                  onMoveCharger?.(selectedUnitId, Number(col), Number(row));
                }
              });
            } else if (mode === "select" && selectedUnitId !== null && isAvailable) {
              highlightCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                if (e.button === 0) {
                  onStartMovePreview(Number(selectedUnitId), Number(col), Number(row));
                }
              });
            }
            
            highlightContainer.addChild(highlightCell);
          }
        }
      }

      // ✅ AGGRESSIVE STAGE CLEANUP - Destroy everything first, then clear
      const childrenToDestroy = [...app.stage.children];
      app.stage.removeChildren();
      childrenToDestroy.forEach(child => {
        if (child.destroy) {
          child.destroy({ children: true, texture: false, baseTexture: false });
        }
      });

      // ✅ ADD CONTAINERS TO STAGE (2 objects instead of 432)
      app.stage.addChild(baseHexContainer);
      app.stage.addChild(highlightContainer);

      // ✅ UNIFIED UNIT RENDERING USING COMPONENT
      for (const unit of units) {
        const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

        // Skip units that are being previewed elsewhere
        if (mode === "movePreview" && movePreview && unit.id === movePreview.unitId) continue;
        if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) continue;

        renderUnit({
          unit, centerX, centerY, app,
          isPreview: false,
          boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
          phase, mode, currentPlayer, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled,
          units, chargeTargets, combatTargets, targetPreview,
          onConfirmMove, parseColor
        });
      }

      // ✅ MOVE PREVIEW RENDERING
      if (mode === "movePreview" && movePreview) {
        const previewUnit = units.find(u => u.id === movePreview.unitId);
        if (previewUnit) {
          const centerX = movePreview.destCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const centerY = movePreview.destRow * HEX_VERT_SPACING + ((movePreview.destCol % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          
          renderUnit({
            unit: previewUnit, centerX, centerY, app,
            isPreview: true, previewType: 'move',
            boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
            HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
            SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
            phase, mode, currentPlayer, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled,
            units, chargeTargets, combatTargets, targetPreview,
            onConfirmMove, parseColor
          });
        }
      }

      // ✅ ATTACK PREVIEW RENDERING
      if (mode === "attackPreview" && attackPreview) {
        const previewUnit = units.find(u => u.id === attackPreview.unitId);
        if (previewUnit) {
          const centerX = attackPreview.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const centerY = attackPreview.row * HEX_VERT_SPACING + ((attackPreview.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          
          renderUnit({
            unit: previewUnit, centerX, centerY, app,
            isPreview: true, previewType: 'attack',
            boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
            HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
            SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
            phase, mode, currentPlayer, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled,
            units, chargeTargets, combatTargets, targetPreview,
            onConfirmMove, parseColor
          });
        }
      }

      // Cleanup function
      return () => {
        if (app && app.stage) {
          // Destroy all sprites completely
          app.stage.children.forEach(child => {
            if (child.destroy) {
              child.destroy({ children: true, texture: true, baseTexture: true });
            }
          });
          app.stage.removeChildren();
        }
        app.destroy(true, { children: true, texture: true, baseTexture: true });
      };

      }, [
        // ✅ FIXED DEPENDENCIES - Prevent board re-render but allow HP animations
        units.length, // Only re-render when units count changes
        units.map(u => `${u.id}-${u.col}-${u.row}-${u.CUR_HP}`).join(','), // Only essential unit changes
        selectedUnitId,
        mode,
        phase,
        boardConfig?.cols, // Only re-render if board structure changes
        loading,
        error,
        movePreview?.unitId, // Add this to ensure preview changes trigger re-render
        movePreview?.destCol, // Add this too
        movePreview?.destRow,  // And this
        targetPreview // Keep full targetPreview for HP bar blinking
      ]);

      // Simple container return - loading/error handled inside useEffect
      return (
        <div>
          <div ref={containerRef} />
          {shootingPhaseState?.singleShotState && (
            <SingleShotDisplay
              singleShotState={shootingPhaseState.singleShotState}
              shooterName={
                units.find(u => u.id === shootingPhaseState.singleShotState?.shooterId)?.name || 
                `Unit ${shootingPhaseState.singleShotState?.shooterId}`
              }
              targetName={
                shootingPhaseState.singleShotState.targetId
                  ? units.find(u => u.id === shootingPhaseState.singleShotState?.targetId)?.name || 
                    `Unit ${shootingPhaseState.singleShotState?.targetId}`
                  : undefined
              }
            />
          )}
        </div>
      );
    }