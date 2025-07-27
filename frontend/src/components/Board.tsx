// frontend/src/components/Board.tsx
import React, { useEffect, useRef, useState } from "react";
import * as PIXI from "pixi.js-legacy";
import type { Unit, TargetPreview, CombatSubPhase, PlayerId, GameState } from "../types/game";
import { useGameConfig } from '../hooks/useGameConfig';
import { SingleShotDisplay } from './SingleShotDisplay';
import { setupBoardClickHandler } from '../utils/boardClickHandler';
import { renderUnit } from './UnitRenderer';
import { isMovementBlocked, hasLineOfSight, isChargeBlocked, offsetToCube, cubeDistance, getHexLine } from '../utils/gameHelpers';

// Import hex coordinate functions from gameHelpers (no duplication)

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
  eligibleUnitIds: number[];
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
  combatSubPhase?: CombatSubPhase; // NEW
  combatActivePlayer?: PlayerId; // NEW
  phase: "move" | "shoot" | "charge" | "combat";
  onCharge?: (chargerId: number, targetId: number) => void;
  onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
  onCancelCharge?: () => void;
  onValidateCharge?: (chargerId: number) => void;
  onLogChargeRoll?: (unit: Unit, roll: number) => void;
  shootingPhaseState?: any;
  targetPreview?: TargetPreview | null;
  onCancelTargetPreview?: () => void;
  gameState: GameState; // Add gameState prop
  chargeRollPopup?: { unitId: number; roll: number; tooLow: boolean; timestamp: number } | null;
  getChargeDestinations: (unitId: number) => { col: number; row: number }[];
};

export default function Board({
  units,
  selectedUnitId,
  eligibleUnitIds,
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
  combatSubPhase,
  combatActivePlayer,
  onMoveCharger,
  onCancelCharge,
  onValidateCharge,
  onLogChargeRoll,
  shootingPhaseState,
  targetPreview,
  onCancelTargetPreview,
  gameState,
  chargeRollPopup,
  getChargeDestinations,
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
  const stableCallbacks = useRef<{
    onSelectUnit: (id: number | string | null) => void;
    onStartMovePreview: (unitId: number | string, col: number | string, row: number | string) => void;
    onStartAttackPreview: (unitId: number, col: number, row: number) => void;
    onConfirmMove: () => void;
    onCancelMove: () => void;
    onShoot: (shooterId: number, targetId: number) => void;
    onCombatAttack?: (attackerId: number, targetId: number | null) => void;
    onCharge?: (chargerId: number, targetId: number) => void;
    onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
    onCancelCharge?: () => void;
    onValidateCharge?: (chargerId: number) => void;
    onLogChargeRoll?: (unit: Unit, roll: number) => void;
  }>({
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
    onValidateCharge,
    onLogChargeRoll
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
    onValidateCharge,
    onLogChargeRoll
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
    const OBJECTIVE_ZONE_COLOR = parseColor(boardConfig.colors.objective_zone!);
    const WALL_COLOR = parseColor(boardConfig.colors.wall!);

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

    // Set up board click handler to prevent event conflicts
    setupBoardClickHandler({
      onSelectUnit: stableCallbacks.current.onSelectUnit,
      onStartAttackPreview: (shooterId: number) => {
        const unit = units.find(u => u.id === shooterId);
        if (unit) {
          stableCallbacks.current.onStartAttackPreview(shooterId, unit.col, unit.row);
        }
      },
      onShoot: stableCallbacks.current.onShoot,
      onCombatAttack: stableCallbacks.current.onCombatAttack || (() => {}),
      onConfirmMove: stableCallbacks.current.onConfirmMove,
      onCancelCharge: stableCallbacks.current.onCancelCharge,
      onMoveCharger: stableCallbacks.current.onMoveCharger,
      onStartMovePreview: stableCallbacks.current.onStartMovePreview,
    });

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
      // Use stored charge roll from gameState (rolled when unit was first selected)
      const chargeDistance = gameState.unitChargeRolls && gameState.unitChargeRolls[selectedUnit.id];
      
      if (!chargeDistance) {
        console.warn(`⚠️ No charge roll found for unit ${selectedUnit.id}, skipping charge preview`);
        chargeCells = [];
        chargeTargets = [];
      } else {
      // Use authoritative getChargeDestinations function (single source of truth)
      chargeCells = getChargeDestinations(selectedUnit.id);

          // Red outline: enemy units that can be reached via valid charge movement
          chargeTargets = units.filter(u => {
            if (u.player === selectedUnit.player) return false;
            
            // Check if any valid charge destination is adjacent to this enemy
            return chargeCells.some(dest =>
              Math.max(Math.abs(dest.col - u.col), Math.abs(dest.row - u.row)) === 1
            );
          });
          
      }
    }
    

      // Green circles for eligible units (single source of truth)
      if (selectedUnit && mode === "select" && eligibleUnitIds && eligibleUnitIds.includes(selectedUnit.id)) {
        if (phase === "move") {
          // For move phase, show available move destinations
          const runMovementBFS = () => {
            if (selectedUnit.MOVE === undefined || selectedUnit.MOVE === null) {
              throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) is missing required MOVE property for movement preview`);
            }

            const centerCol = selectedUnit.col;
            const centerRow = selectedUnit.row;

            const visited = new Map<string, number>();
            const queue: [number, number, number][] = [[centerCol, centerRow, 0]];

            // Use cube coordinate system for proper hex neighbors
            const cubeDirections = [
              [1, -1, 0], [1, 0, -1], [0, 1, -1], 
              [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
            ];

            // Collect all forbidden hexes (adjacent to any enemy + wall hexes) using cube coordinates  
            const forbiddenSet = new Set<string>();
            
            // Add all wall hexes as forbidden
            const wallHexSet = new Set<string>(
              (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
            );
            wallHexSet.forEach(wallHex => forbiddenSet.add(wallHex));
            
            for (const enemy of units) {
              if (enemy.player === selectedUnit.player) continue;

              // Add enemy position itself
              forbiddenSet.add(`${enemy.col},${enemy.row}`);

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
                }
              }
            }

            while (queue.length > 0) {
              const next = queue.shift();
              if (!next) continue;
              const [col, row, steps] = next;
              const key = `${col},${row}`;
              
              if (visited.has(key) && steps >= visited.get(key)!) {
                continue;
              }

              visited.set(key, steps);

              // ⛔ Skip forbidden positions completely - don't expand from them
              if (forbiddenSet.has(key) && steps > 0) {
                continue;
              }

              const blocked = units.some(u => u.col === col && u.row === row && u.id !== selectedUnit.id);

                if (steps > 0 && steps <= selectedUnit.MOVE && !blocked && !forbiddenSet.has(key)) {
                  availableCells.push({ col, row });
                }

                if (steps >= selectedUnit.MOVE) {
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
          };

          runMovementBFS();
        } else {
          // For other phases (charge, etc), just show green circle on unit's hex
          availableCells.push({ col: selectedUnit.col, row: selectedUnit.row });
        }
      }

      // Green circles for all eligible charge units (not just selected)
      if (phase === "charge" && mode === "select") {
        eligibleUnitIds.forEach(unitId => {
          const eligibleUnit = units.find(u => u.id === unitId);
          if (eligibleUnit) {
            availableCells.push({ col: eligibleUnit.col, row: eligibleUnit.row });
          }
        });
      }

      // Attack cells: Different colors for different line of sight conditions
      let attackCells: { col: number; row: number }[] = []; // Red = clear line of sight
      let coverCells: { col: number; row: number }[] = []; // Orange = targets in cover
      let blockedTargets: Set<string> = new Set(); // Track targets with no line of sight (no hex shown)
      let coverTargets: Set<string> = new Set(); // Track targets in cover
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
          
          // Check line of sight for each potential target during shooting
          if (phase === "shoot") {
            const enemyUnits = units.filter(u => u.player !== previewUnit!.player);
            for (const enemy of enemyUnits) {
              const distance = cubeDistance(centerCube, offsetToCube(enemy.col, enemy.row));
              if (distance <= (previewUnit.RNG_RNG || 0)) {
                const lineOfSight = hasLineOfSight(
                  { col: attackFromCol, row: attackFromRow },
                  { col: enemy.col, row: enemy.row },
                  boardConfig.wall_hexes || []
                );
                
                if (!lineOfSight.canSee) {
                  blockedTargets.add(`${enemy.col},${enemy.row}`);
                } else if (lineOfSight.inCover) {
                  coverTargets.add(`${enemy.col},${enemy.row}`);
                }
              }
            }
          }
          
          // Validate required range properties are defined and get range
          let range: number;
          if (phase === "combat") {
            if (previewUnit.CC_RNG === undefined || previewUnit.CC_RNG === null) {
              throw new Error(`Unit ${previewUnit.id} (${previewUnit.type || 'unknown'}) is missing required CC_RNG property for combat phase preview`);
            }
            range = previewUnit.CC_RNG;
            // For combat phase, show all hexes in range (original behavior)
            for (let col = 0; col < BOARD_COLS; col++) {
              for (let row = 0; row < BOARD_ROWS; row++) {
                const targetCube = offsetToCube(col, row);
                const dist = cubeDistance(centerCube, targetCube);
                if (dist > 0 && dist <= range) {
                  attackCells.push({ col, row });
                }
              }
            }
          } else {
            if (previewUnit.RNG_RNG === undefined || previewUnit.RNG_RNG === null) {
              throw new Error(`Unit ${previewUnit.id} (${previewUnit.type || 'unknown'}) is missing required RNG_RNG property for shooting phase preview`);
            }
            range = previewUnit.RNG_RNG;
            
            // During move phase with movePreview, show red RNG_RNG hexes around new position
            if (phase === "move" && mode === "movePreview") {
              // Show all hexes within RNG_RNG range of the preview position
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
            // During shooting phase, show different colored hexes based on line of sight
            else if (phase === "shoot") {
              // First, find all enemies in range and mark cover paths
              const coverPathHexes = new Set<string>();
              const enemyUnits = units.filter(u => u.player !== previewUnit!.player);
              
              // First process actual enemy units
              for (const enemy of enemyUnits) {
                const distance = cubeDistance(centerCube, offsetToCube(enemy.col, enemy.row));
                if (distance > 0 && distance <= range) {
                  
                  const lineOfSight = hasLineOfSight(
                    { col: attackFromCol, row: attackFromRow },
                    { col: enemy.col, row: enemy.row },
                    boardConfig.wall_hexes || []
                  );
                  
                  
                  if (lineOfSight.canSee && lineOfSight.inCover) {
                    // Mark this enemy as in cover
                    coverCells.push({ col: enemy.col, row: enemy.row });
                    coverTargets.add(`${enemy.col},${enemy.row}`);
                    
                    // Mark all hexes in the path that contribute to cover (but exclude wall hexes)
                    const pathHexes = getHexLine(attackFromCol, attackFromRow, enemy.col, enemy.row);
                    const wallHexSet = new Set<string>(
                      (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
                    );
                    pathHexes.forEach(hex => {
                      const hexKey = `${hex.col},${hex.row}`;
                      if (!wallHexSet.has(hexKey)) {
                        coverPathHexes.add(hexKey);
                      }
                    });
                  } else if (lineOfSight.canSee) {
                    // Clear line of sight enemy
                    attackCells.push({ col: enemy.col, row: enemy.row });
                  } else {
                    // Blocked enemy
                    blockedTargets.add(`${enemy.col},${enemy.row}`);
                  }
                }
              }
              
              // Now show all hexes in range with appropriate colors
              for (let col = 0; col < BOARD_COLS; col++) {
                for (let row = 0; row < BOARD_ROWS; row++) {
                  const targetCube = offsetToCube(col, row);
                  const dist = cubeDistance(centerCube, targetCube);
                  if (dist > 0 && dist <= range) {
                    const hexKey = `${col},${row}`;
                    const hasEnemy = units.some(u => 
                      u.player !== previewUnit!.player && 
                      u.col === col && 
                      u.row === row
                    );
                    
                    if (!hasEnemy) {
                      // For empty hexes, show orange if part of cover path, red if clear
                      if (coverPathHexes.has(hexKey)) {
                        coverCells.push({ col, row });
                      } else {
                        const lineOfSight = hasLineOfSight(
                          { col: attackFromCol, row: attackFromRow },
                          { col, row },
                          boardConfig.wall_hexes || []
                        );
                        
                        if (lineOfSight.canSee && !lineOfSight.inCover) {
                          attackCells.push({ col, row });
                        } else if (lineOfSight.canSee && lineOfSight.inCover) {
                          coverCells.push({ col, row });
                        }
                      }
                    }
                  }
                }
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
          const isInCover = coverCells.some(cell => cell.col === col && cell.row === row);
          const isChargeable = chargeCells.some(cell => cell.col === col && cell.row === row);

          // Check if this hex is in an objective zone
          const isObjectiveZone = false;

          // Check if this is a wall hex
          const wallHexSet = new Set<string>(
            (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
          );
          const isWallHex = wallHexSet.has(`${col},${row}`);

          // New: Compute all objective hexes and their adjacent hexes
          // ✅ Compute objectiveHexSet (base + adjacent), run once
          const objectiveHexSet = new Set<string>();
          const baseObjectives = boardConfig.objective_hexes || [];

          const cubeDirections = [
            [1, -1, 0], [1, 0, -1], [0, 1, -1],
            [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
          ];

          for (const [col, row] of baseObjectives) {
            objectiveHexSet.add(`${col},${row}`);

            const cube = offsetToCube(col, row);
            for (const [dx, dy, dz] of cubeDirections) {
              const neighborCube = {
                x: cube.x + dx,
                y: cube.y + dy,
                z: cube.z + dz
              };

              const adjCol = neighborCube.x;
              const adjRow = neighborCube.z + ((adjCol - (adjCol & 1)) >> 1);

              if (
                adjCol >= 0 && adjCol < BOARD_COLS &&
                adjRow >= 0 && adjRow < BOARD_ROWS
              ) {
                objectiveHexSet.add(`${adjCol},${adjRow}`);
              }
            }
          }


          // Create base hex (always present)
          const baseCell = new PIXI.Graphics();
          const isEven = (col + row) % 2 === 0;
          let cellColor = isEven ? parseColor(boardConfig.colors.cell_even) : parseColor(boardConfig.colors.cell_odd);

          // Override color for walls and objective zones
          if (isWallHex) {
            cellColor = WALL_COLOR;
          } else if (objectiveHexSet.has(`${col},${row}`)) {
            cellColor = parseColor(boardConfig.colors.objective);
          }
          
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
                baseCell.eventMode = isWallHex ? 'none' : 'static';
                baseCell.cursor    = "pointer";
                baseCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                  if (e.button === 0) onCancelCharge?.();
                });
              }
            }

            // Create highlight hex (only if needed)
            if (isChargeable || isAttackable || isInCover || isAvailable) {
              const highlightCell = new PIXI.Graphics();

            
            if (isChargeable) {
              highlightCell.beginFill(CHARGE_COLOR, 0.5);
            } else if (isAttackable) {
              highlightCell.beginFill(ATTACK_COLOR, 0.5); // Red for clear line of sight
            } else if (isInCover) {
              highlightCell.beginFill(CHARGE_COLOR, 0.5); // Orange for targets in cover (reuse CHARGE_COLOR)
            } else if (isAvailable) {
              highlightCell.beginFill(HIGHLIGHT_COLOR, 0.5);
            }
            
            highlightCell.drawPolygon(points);
            highlightCell.endFill();

            // Make interactive for hex clicks
            highlightCell.eventMode = isWallHex ? 'none' : 'static';
            highlightCell.cursor = "pointer";
            baseCell.eventMode = 'static';
            baseCell.cursor = "pointer";
            
            // Use global event system for all hex clicks
            if (isChargeable || isAttackable || isInCover || isAvailable) {
              highlightCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                if (e.button === 0) {
                  window.dispatchEvent(new CustomEvent('boardHexClick', {
                    detail: { col, row, phase, mode, selectedUnitId }
                  }));
                }
              });
            }
            
            // Base cell clicks for unit position (charge cancel)
            baseCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) {
                const unit = units.find(u => u.id === selectedUnitId);
                if (mode === "chargePreview" && unit?.col === col && unit.row === row) {
                  onCancelCharge?.();
                } else {
                  window.dispatchEvent(new CustomEvent('boardHexClick', {
                    detail: { col, row, phase, mode, selectedUnitId }
                  }));
                }
              }
              if (e.button === 2) {
                onCancelMove?.();
              }
            });
            
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
          isEligible: eligibleUnitIds.includes(unit.id), // Add eligibility from GameController
          boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
          phase, mode, currentPlayer, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled,
          combatSubPhase, combatActivePlayer,
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
            isEligible: false, // Preview units are not eligible
            boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
            HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
            SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
            phase, mode, currentPlayer, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled,
            combatSubPhase, combatActivePlayer,
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
            isEligible: false, // Preview units are not eligible
            boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
            HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
            SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
            phase, mode, currentPlayer, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled,
            combatSubPhase, combatActivePlayer,
            units, chargeTargets, combatTargets, targetPreview,
            onConfirmMove, parseColor
          });
        }
      }

      // ✅ CHARGE ROLL POPUP RENDERING
      if (chargeRollPopup) {
        const popupText = chargeRollPopup.tooLow 
          ? `Roll : ${chargeRollPopup.roll} : No charge !`
          : `Roll : ${chargeRollPopup.roll} !`;
        
        const popupContainer = new PIXI.Container();
        popupContainer.name = 'charge-roll-popup';
        popupContainer.zIndex = 10000; // Ensure popup is on top
        
        // Create popup background
        const popupBg = new PIXI.Graphics();
        popupBg.beginFill(0x000000, 0.9);
        popupBg.lineStyle(3, chargeRollPopup.tooLow ? 0xFF0000 : 0x00FF00, 1.0);
        popupBg.drawRoundedRect(0, 0, 300, 80, 10);
        popupBg.endFill();
        
        // Create popup text
        const popupTextObj = new PIXI.Text(popupText, {
          fontSize: 26,
          fill: chargeRollPopup.tooLow ? 0xFF4444 : 0x44FF44,
          fontWeight: 'bold',
          align: 'center'
        });
        popupTextObj.anchor.set(0.5);
        popupTextObj.position.set(150, 40);
        
        // Position popup in center of screen
        popupContainer.position.set((width - 300) / 2, (height - 80) / 2);
        popupContainer.addChild(popupBg);
        popupContainer.addChild(popupTextObj);
        
        app.stage.addChild(popupContainer);
      }

      // ✅ RENDER LINE OF SIGHT INDICATORS - Add after unit rendering
      if (phase === "shoot" && selectedUnit && (blockedTargets.size > 0 || coverTargets.size > 0)) {
        const losContainer = new PIXI.Container();
        losContainer.name = 'line-of-sight-indicators';
        
        // Show blocked targets with red X
        blockedTargets.forEach(targetKey => {
          const [col, row] = targetKey.split(',').map(Number);
          const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          
          const blockedIndicator = new PIXI.Graphics();
          blockedIndicator.lineStyle(3, 0xFF0000, 1.0);
          // Draw X
          blockedIndicator.moveTo(centerX - HEX_RADIUS/2, centerY - HEX_RADIUS/2);
          blockedIndicator.lineTo(centerX + HEX_RADIUS/2, centerY + HEX_RADIUS/2);
          blockedIndicator.moveTo(centerX + HEX_RADIUS/2, centerY - HEX_RADIUS/2);
          blockedIndicator.lineTo(centerX - HEX_RADIUS/2, centerY + HEX_RADIUS/2);
          
          losContainer.addChild(blockedIndicator);
        });
        
        // Show targets in cover with yellow shield icon
        coverTargets.forEach(targetKey => {
          const [col, row] = targetKey.split(',').map(Number);
          const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          
          const coverIndicator = new PIXI.Graphics();
          coverIndicator.lineStyle(2, 0xFFFF00, 1.0);
          coverIndicator.beginFill(0xFFFF00, 0.3);
          // Draw shield shape
          coverIndicator.drawCircle(centerX, centerY - HEX_RADIUS/3, HEX_RADIUS/4);
          coverIndicator.endFill();
          
          losContainer.addChild(coverIndicator);
        });
        
        app.stage.addChild(losContainer);
      }
      
      // ✅ RENDER WALLS - Add after unit rendering
      if (boardConfig.walls && boardConfig.walls.length > 0) {
        const wallsContainer = new PIXI.Container();
        wallsContainer.name = 'walls';
        
        boardConfig.walls.forEach(wall => {
          const wallGraphics = new PIXI.Graphics();
          
          // Calculate start and end positions
          const startX = wall.start.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const startY = wall.start.row * HEX_VERT_SPACING + ((wall.start.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          const endX = wall.end.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const endY = wall.end.row * HEX_VERT_SPACING + ((wall.end.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
          
          // Draw wall as thick line
          wallGraphics.lineStyle(wall.thickness || 3, WALL_COLOR, 1.0);
          wallGraphics.moveTo(startX, startY);
          wallGraphics.lineTo(endX, endY);
          
          wallsContainer.addChild(wallGraphics);
        });
        
        app.stage.addChild(wallsContainer);
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
        units.map(u => `${u.id}-${u.col}-${u.row}-${u.CUR_HP}-${u.ATTACK_LEFT}-${u.SHOOT_LEFT}`).join(','), // Only essential unit changes
        selectedUnitId,
        mode,
        phase,
        combatSubPhase, // NEW: Trigger re-render when combat sub-phase changes
        combatActivePlayer, // NEW: Trigger re-render when combat active player changes
        boardConfig?.cols, // Only re-render if board structure changes
        loading,
        error,
        movePreview?.unitId, // Add this to ensure preview changes trigger re-render
        movePreview?.destCol, // Add this too
        movePreview?.destRow,  // And this
        targetPreview, // Keep full targetPreview for HP bar blinking
        eligibleUnitIds.join(','), // Add eligibleUnitIds to trigger re-render when eligibility changes
        chargeRollPopup // Add chargeRollPopup to trigger re-render when popup state changes
      ]);

      // Simple container return - loading/error handled inside useEffect
      return (
        <div className="w-full">
          <div ref={containerRef} className="w-full" />
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
                    `Unit ${shootingPhaseState.singleShotState.targetId}`
                  : undefined
              }
            />
          )}
        </div>
      );


    }