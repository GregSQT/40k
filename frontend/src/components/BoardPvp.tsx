// frontend/src/components/BoardPvp.tsx
import React, { useEffect, useRef } from "react";
import * as PIXI from "pixi.js-legacy";
import type { Unit, TargetPreview, FightSubPhase, PlayerId, GameState } from "../types/game";
import { useGameConfig } from '../hooks/useGameConfig';
// import { SingleShotDisplay } from './SingleShotDisplay';
import { setupBoardClickHandler } from '../utils/boardClickHandler';
import { drawBoard } from './BoardDisplay';
const setupBoardInteractions = (app: any, boardConfig: any, config: any) => {};
const cleanupBoardInteractions = (app: any) => {};
import { renderUnit } from './UnitRenderer';
import { offsetToCube, cubeDistance, hasLineOfSight, getHexLine, isUnitInRange } from '../utils/gameHelpers';

// Helper functions are now in BoardDisplay.tsx - removed from here

type Mode = "select" | "movePreview" | "attackPreview" | "targetPreview" | "chargePreview";

type BoardProps = {
  units: Unit[];
  selectedUnitId: number | null;
  eligibleUnitIds: number[];
  showHexCoordinates?: boolean;
  shootingActivationQueue?: Unit[];
  activeShootingUnit?: Unit | null;
  mode: Mode;
  movePreview: { unitId: number; destCol: number; destRow: number } | null;
  attackPreview: { unitId: number; col: number; row: number } | null;
  // Blinking state for multi-unit HP bars
  blinkingUnits?: number[];
  isBlinkingActive?: boolean;
  blinkState?: boolean;
  onSelectUnit: (id: number | string | null) => void;
  onSkipUnit?: (unitId: number | string) => void;
  onSkipShoot?: (unitId: number | string) => void;
  onStartTargetPreview?: (shooterId: number | string, targetId: number | string) => void;
  onStartMovePreview: (unitId: number | string, col: number | string, row: number | string) => void;
  onDirectMove: (unitId: number | string, col: number | string, row: number | string) => void;
  onStartAttackPreview: (unitId: number, col: number, row: number) => void;
  onConfirmMove: () => void;
  onCancelMove: () => void;
  onShoot: (shooterId: number, targetId: number) => void;
  onFightAttack?: (attackerId: number, targetId: number | null) => void;
  currentPlayer: 0 | 1;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  unitsFled?: number[];
  fightSubPhase?: FightSubPhase; // NEW
  fightActivePlayer?: PlayerId; // NEW
  phase: "move" | "shoot" | "charge" | "fight";
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
  showHexCoordinates = false,
  shootingActivationQueue,
  activeShootingUnit,
  mode,
  movePreview,
  attackPreview,
  // Blinking props
  blinkingUnits,
  isBlinkingActive,
  blinkState,
  onSelectUnit,
  onSkipUnit,
  onStartTargetPreview,
  onStartMovePreview,
  onDirectMove,
  onStartAttackPreview,
  onConfirmMove,
  onCancelMove,
  currentPlayer,
  unitsMoved,
  phase,
  onShoot,
  onFightAttack,
  onCharge,
  unitsCharged,
  unitsAttacked,
  unitsFled,
  fightSubPhase,
  fightActivePlayer,
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
    onSkipUnit?: (unitId: number | string) => void;
    onStartMovePreview: (unitId: number | string, col: number | string, row: number | string) => void;
    onDirectMove: (unitId: number | string, col: number | string, row: number | string) => void;
    onStartAttackPreview: (unitId: number, col: number, row: number) => void;
    onConfirmMove: () => void;
    onCancelMove: () => void;
    onShoot: (shooterId: number, targetId: number) => void;
    onFightAttack?: (attackerId: number, targetId: number | null) => void;
    onCharge?: (chargerId: number, targetId: number) => void;
    onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
    onCancelCharge?: () => void;
    onValidateCharge?: (chargerId: number) => void;
    onLogChargeRoll?: (unit: Unit, roll: number) => void;
  }>({
    onSelectUnit,
    onStartMovePreview,
    onDirectMove,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onFightAttack,
    onCharge,
    onMoveCharger,
    onCancelCharge,
    onValidateCharge,
    onLogChargeRoll
  });

  // Update refs when props change but don't trigger re-render - MOVE THIS BEFORE useEffect
  stableCallbacks.current = {
    onSelectUnit,
    onSkipUnit,
    onStartMovePreview,
    onDirectMove,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onFightAttack,
    onCharge,
    onMoveCharger,
    onCancelCharge,
    onValidateCharge,
    onLogChargeRoll
  };
  
  // Remove debug log
  
  // ✅ HOOK 2.5: Add shooting preview state management with React state
  // ✅ REMOVE ALL ANIMATION STATE - This is causing the re-render loop
  // const [hpAnimationState, setHpAnimationState] = useState<boolean>(false);
  // const [currentShootingTarget, setCurrentShootingTarget] = useState<number | null>(null);
  // const [selectedShootingTarget, setSelectedShootingTarget] = useState<number | null>(null);
  // const animationIntervalRef = useRef<NodeJS.Timeout | null>(null);
  // const [currentFightTarget, setCurrentFightTarget] = useState<number | null>(null);
  // const [selectedFightTarget, setSelectedFightTarget] = useState<number | null>(null);

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
    const canvasWidth = gridWidth + 2 * MARGIN;
    const canvasHeight = gridHeight + 2 * MARGIN;

    // ✅ OPTIMIZED PIXI CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    const pixiConfig = {
      width: canvasWidth,
      height: canvasHeight,
      backgroundColor: parseInt(boardConfig.colors.background.replace('0x', ''), 16),
      backgroundAlpha: 1, // Ensure background is opaque
      antialias: displayConfig.antialias!,
      powerPreference: "high-performance" as WebGLPowerPreference,
      resolution: String(displayConfig.resolution) === "auto" ? (window.devicePixelRatio || 1) : (typeof displayConfig.resolution === 'number' ? displayConfig.resolution : 1),
      autoDensity: displayConfig.autoDensity!,
    };
    
    // ✅ VALIDATE PIXI CONFIG VALUES
    if (pixiConfig.antialias === undefined || pixiConfig.autoDensity === undefined) {
      throw new Error('Missing required PIXI configuration values: antialias, autoDensity, or resolution');
    }

    const app = new PIXI.Application(pixiConfig);
    app.stage.sortableChildren = true;

    // ✅ CANVAS STYLING FROM CONFIG - EXACT BOARDREPLAY MATCH
    const canvas = app.view as HTMLCanvasElement;
    canvas.style.display = 'block';
    // Removed maxWidth constraint to allow full board size
    canvas.style.height = 'auto';
    canvas.style.border = displayConfig?.canvas_border ?? '1px solid #333';
    
    // Clear container and append canvas - EXACT BOARDREPLAY MATCH
    containerRef.current.innerHTML = '';
    containerRef.current.appendChild(canvas);

    // Set up board click handler IMMEDIATELY after canvas creation
    setupBoardClickHandler({
      onSelectUnit: stableCallbacks.current.onSelectUnit,
      onSkipUnit: stableCallbacks.current.onSkipUnit,
      onSkipShoot: (unitId: number) => {
        if (stableCallbacks.current.onSkipUnit) {
          stableCallbacks.current.onSkipUnit(unitId);
        }
      },
      onStartAttackPreview: (shooterId: number) => {
        const unit = units.find(u => u.id === shooterId);
        if (unit) {
          stableCallbacks.current.onStartAttackPreview(shooterId, unit.col, unit.row);
        }
      },
      onShoot: stableCallbacks.current.onShoot,
      onCombatAttack: stableCallbacks.current.onFightAttack || (() => {}),
      onConfirmMove: stableCallbacks.current.onConfirmMove,
      onCancelCharge: stableCallbacks.current.onCancelCharge,
      onMoveCharger: stableCallbacks.current.onMoveCharger,
      onStartMovePreview: onStartMovePreview,
      onDirectMove: (unitId: number | string, col: number | string, row: number | string) => {
        onDirectMove(unitId, col, row);
      },
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

    // ✅ RESTRUCTURED: Calculate ALL highlight data BEFORE any drawBoard calls
    let availableCells: { col: number; row: number }[] = [];
    const selectedUnit = units.find(u => u.id === selectedUnitId);

    // Charge preview: chargeCells & targets
    let chargeCells: { col: number; row: number }[] = [];
    let chargeTargets: Unit[] = [];

    // Fight preview: fightTargets for red outline on enemies within fight range
    let fightTargets: Unit[] = [];
    if (phase === "fight" && selectedUnit) {
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      
      // Validate CC_RNG is defined
      if (selectedUnit.CC_RNG === undefined || selectedUnit.CC_RNG === null) {
        throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) is missing required CC_RNG property for fight phase`);
      }
      
      const fightRange = selectedUnit.CC_RNG;
      
      // Use stored charge roll from gameState (rolled when unit was first selected)
        const chargeDistance = gameState.unitChargeRolls && gameState.unitChargeRolls[Number(selectedUnit.id)];
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

    // ✅ SIMPLIFIED FIGHT PREVIEW - No animations to prevent re-render loop
    let fightTarget: Unit | null = null;
    if (phase === "fight" && selectedUnit) {
      // Simple target identification - no state changes here
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      const enemiesInRange = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) === 1
      );
      
      // Use the first valid target or null
      fightTarget = enemiesInRange[0] || null;
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
      chargeCells = getChargeDestinations(0); // Stub function returns empty array anyway

          // Red outline: enemy units that can be reached via valid charge movement
          chargeTargets = units.filter(u => {
            if (u.player === selectedUnit.player) return false;
            
            // Check if any valid charge destination is adjacent to this enemy
            return chargeCells.some(dest => {
              const cube1 = offsetToCube(dest.col, dest.row);
              const cube2 = offsetToCube(u.col, u.row);
              return cubeDistance(cube1, cube2) === 1;
            });
          });
          
      }
    }

    // ✅ CALCULATE MOVEMENT PREVIEW BEFORE MAIN DRAWBOARD CALL
    if (selectedUnit && mode === "select" && eligibleUnitIds && eligibleUnitIds.includes(typeof selectedUnit.id === 'number' ? selectedUnit.id : parseInt(selectedUnit.id as string))) {
      if (phase === "move") {
        // For Movement Phase, show available move destinations
        if (selectedUnit.MOVE === undefined || selectedUnit.MOVE === null) {
          throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) is missing required MOVE property for movement preview`);
        }

        const centerCol = selectedUnit.col;
        const centerRow = selectedUnit.row;

        const originCube = offsetToCube(centerCol, centerRow);

        // Use cube coordinate system for proper hex neighbors
        const cubeDirections = [
          [1, -1, 0], [1, 0, -1], [0, 1, -1], 
          [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
        ];

        // Collect all forbidden hexes (adjacent to any enemy + wall hexes) using cube coordinates  
        const forbiddenSet = new Set<string>();
        
        // Add all wall hexes as forbidden
        const wallHexSet = new Set<string>(
          (boardConfig.wall_hexes || []).map((wall: number[]) => `${wall[0]},${wall[1]}`)
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

        const visited = new Map<string, number>();
        const queue: [number, number, number][] = [[centerCol, centerRow, 0]];

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
              
              if (
                !nblocked &&
                (!visited.has(nkey) || visited.get(nkey)! > nextSteps)
              ) {
                queue.push([ncol, nrow, nextSteps]);
              }
            }
          }
        }

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

      // Calculate blockedTargets for ALL enemies during shooting phase (not just preview)
      if (phase === "shoot" && selectedUnit) {
        const enemyUnits = units.filter(u => u.player !== selectedUnit.player);
        const centerCube = offsetToCube(selectedUnit.col, selectedUnit.row);
        
        for (const enemy of enemyUnits) {
          const distance = cubeDistance(centerCube, offsetToCube(enemy.col, enemy.row));
          if (distance <= (selectedUnit.RNG_RNG || 0)) {
            const lineOfSight = hasLineOfSight(
              { col: selectedUnit.col, row: selectedUnit.row },
              { col: enemy.col, row: enemy.row },
              (boardConfig.wall_hexes || []) as [number, number][]
            );
            
            if (!lineOfSight.canSee) {
              blockedTargets.add(`${enemy.col},${enemy.row}`);
            } else if (lineOfSight.inCover) {
              coverTargets.add(`${enemy.col},${enemy.row}`);
            }
          }
        }
      }

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
                  (boardConfig.wall_hexes || []) as [number, number][]
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
          if (phase === "fight") {
            if (previewUnit.CC_RNG === undefined || previewUnit.CC_RNG === null) {
              throw new Error(`Unit ${previewUnit.id} (${previewUnit.type || 'unknown'}) is missing required CC_RNG property for fight phase preview`);
            }
            range = previewUnit.CC_RNG;
            // For fight phase, show all hexes in range (original behavior)
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
            
            // During shooting phase, show different colored hexes based on line of sight
            if (phase === "shoot") {
              // First, find all enemies in range and mark cover paths
              const coverPathHexes = new Set<string>();
              const enemyUnits = units.filter(u => u.player !== previewUnit!.player);
              
              // First process actual enemy units
              for (const enemy of enemyUnits) {
                const distance = cubeDistance(centerCube, offsetToCube(enemy.col, enemy.row));
                if (distance > 0 && distance <= range) {
                  
                  const lineOfSight = hasLineOfSight(
                    { col: attackFromCol!, row: attackFromRow! },
                    { col: enemy.col, row: enemy.row },
                    (boardConfig.wall_hexes || []) as [number, number][]
                  );
                  
                  
                  if (lineOfSight.canSee && lineOfSight.inCover) {
                    // Mark this enemy as in cover
                    coverCells.push({ col: enemy.col, row: enemy.row });
                    coverTargets.add(`${enemy.col},${enemy.row}`);
                    
                    // Mark all hexes in the path that contribute to cover (but exclude wall hexes)
                    const pathHexes: any[] = getHexLine(attackFromCol!, attackFromRow!, enemy.col, enemy.row);
                    const wallHexSet = new Set<string>(
                      (boardConfig.wall_hexes || []).map((wall: number[]) => `${wall[0]},${wall[1]}`)
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
                          { col: attackFromCol!, row: attackFromRow! },
                          { col: col, row: row },
                          (boardConfig.wall_hexes || []) as [number, number][]
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


      // ✅ DRAW BOARD ONCE with populated availableCells
      drawBoard(app, boardConfig as any, {
        availableCells,
        attackCells,
        coverCells,
        chargeCells,
        blockedTargets,
        coverTargets,
        phase,
        selectedUnitId,
        mode,
        showHexCoordinates
      });

      // ✅ SETUP BOARD INTERACTIONS using shared BoardInteractions component
      setupBoardInteractions(app, boardConfig, {
        phase,
        mode,
        selectedUnitId,
        units,
        availableCells,
        attackCells,
        coverCells,
        chargeCells,
        onCancelCharge,
        onCancelMove,
        targetPreview,
        onCancelTargetPreview
      });

      // ✅ UNIFIED UNIT RENDERING USING COMPONENT
      for (const unit of units) {
        const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

        // Skip units that are being previewed elsewhere
        if (mode === "movePreview" && movePreview && unit.id === movePreview.unitId) continue;
        if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) continue;

        // Calculate if this unit is shootable for UnitRenderer (works regardless of phase prop issues)
        let isShootable = true;
        if (unit.player !== currentPlayer && selectedUnit && selectedUnit.RNG_RNG !== undefined) {
          // Check range first
          const cube1 = offsetToCube(selectedUnit.col, selectedUnit.row);
          const cube2 = offsetToCube(unit.col, unit.row);
          const distance = cubeDistance(cube1, cube2);
          if (distance > selectedUnit.RNG_RNG) {
            isShootable = false;
          } else {
            // Check for adjacent friendly units blocking
            const friendlyUnits = units.filter(u => u.player === currentPlayer && u.id !== selectedUnit.id);
            const isAdjacentToFriendly = friendlyUnits.some(friendly => {
              const cube1 = offsetToCube(friendly.col, friendly.row);
              const cube2 = offsetToCube(unit.col, unit.row);
              return cubeDistance(cube1, cube2) === 1;
            });
            if (isAdjacentToFriendly) {
              isShootable = false;
            } else {
              // Check line of sight
              const lineOfSight = hasLineOfSight(
                { col: selectedUnit.col, row: selectedUnit.row },
                { col: unit.col, row: unit.row },
                (boardConfig.wall_hexes || []) as [number, number][]
              );
              if (!lineOfSight.canSee) {
                isShootable = false;
              }
            }
          }
        }
        
        // Debug only for key units - EXACT UnitRenderer.tsx logic check
        if (unit.id === 8 || unit.id === 9) {
          let distance = 0;
          if (selectedUnit) {
            const cube1 = offsetToCube(selectedUnit.col, selectedUnit.row);
            const cube2 = offsetToCube(unit.col, unit.row);
            distance = cubeDistance(cube1, cube2);
          }
          const inRangeResult = selectedUnit && selectedUnit.RNG_RNG 
            ? isUnitInRange(selectedUnit, unit, selectedUnit.RNG_RNG) 
            : false;
        }
        // AI_TURN.md: Calculate queue-based eligibility during shooting phase
        const isEligibleForRendering = (() => {
          if (phase === "shoot" && shootingActivationQueue && shootingActivationQueue.length > 0) {
            // During active shooting: unit is eligible if in queue OR is active unit
            const inQueue = shootingActivationQueue.some((u: Unit) => String(u.id) === String(unit.id));
            const isActive = activeShootingUnit && String(activeShootingUnit.id) === String(unit.id);
            const result = inQueue || isActive;
            
            if (unit.id === 8 || unit.id === 9) { // Debug key units
              console.log(`🟢 ELIGIBILITY DEBUG Unit ${unit.id}: inQueue=${inQueue}, isActive=${isActive}, result=${result}`);
              console.log(`🟢 Queue IDs:`, shootingActivationQueue.map(u => u.id));
              console.log(`🟢 Active unit:`, activeShootingUnit?.id || 'none');
            }
            
            return result;
          }
          // All other phases: use standard eligibility
          const standardResult = eligibleUnitIds.includes(typeof unit.id === 'number' ? unit.id : parseInt(unit.id as string));
          if (unit.id === 8 || unit.id === 9) {
            console.log(`🟢 STANDARD ELIGIBILITY Unit ${unit.id}: ${standardResult}`);
          }
          return standardResult;
        })();
        
        renderUnit({
          unit, centerX, centerY, app,
          isPreview: false,
          isEligible: isEligibleForRendering || false,
          isShootable,
          boardConfig, HEX_RADIUS, ICON_SCALE, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT, UNIT_CIRCLE_RADIUS_RATIO, UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
          phase, mode, currentPlayer, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled,
          fightSubPhase, fightActivePlayer,
          units, chargeTargets, fightTargets, targetPreview,
          onConfirmMove, parseColor,
          // Pass blinking state
          blinkingUnits, isBlinkingActive, blinkState
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
            fightSubPhase, fightActivePlayer,
            units, chargeTargets, fightTargets, targetPreview,
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
            fightSubPhase, fightActivePlayer,
            units, chargeTargets, fightTargets, targetPreview,
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
        popupContainer.position.set((canvasWidth - 300) / 2, (canvasHeight - 80) / 2);
        popupContainer.addChild(popupBg);
        popupContainer.addChild(popupTextObj);
        
        app.stage.addChild(popupContainer);
      }

      // Line of sight indicators are now handled by drawBoard() in BoardDisplay.tsx
      
      // Wall rendering is now handled by drawBoard() in BoardDisplay.tsx

      // Cleanup function
      return () => {
        // Cleanup board interactions
        cleanupBoardInteractions(app);
        
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
        // Essential dependencies only - prevent infinite re-renders
        units.length,
        JSON.stringify(units.map(u => ({ id: u.id, col: u.col, row: u.row, HP_CUR: u.HP_CUR, SHOOT_LEFT: u.SHOOT_LEFT }))), // Track position, HP & shooting changes
        selectedUnitId,
        mode,
        phase,
        boardConfig?.cols,
        loading,
        error,
        // Add blinking state to trigger re-render
        isBlinkingActive,
        JSON.stringify(blinkingUnits),
        // Add showHexCoordinates to trigger re-render when toggle changes
        showHexCoordinates
      ]);

      // Simple container return - loading/error handled inside useEffect
      return (
        <div>
          <div ref={containerRef} style={{ display: 'inline-block', lineHeight: 0 }} />
          {/* SingleShotDisplay temporarily disabled - missing component
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
          */}
        </div>
      );


    }