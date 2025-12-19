// frontend/src/components/BoardPvp.tsx
import React, { useEffect, useRef } from "react";
import * as PIXI from "pixi.js-legacy";
import type { Unit, TargetPreview, FightSubPhase, PlayerId, GameState } from "../types/game";
import { useGameConfig } from '../hooks/useGameConfig';
// import { SingleShotDisplay } from './SingleShotDisplay';
import { setupBoardClickHandler } from '../utils/boardClickHandler';
import { drawBoard } from './BoardDisplay';
const setupBoardInteractions = (_app: any, _boardConfig: any, _config: any) => {};
const cleanupBoardInteractions = (_app: any) => {};
import { renderUnit } from './UnitRenderer';
import { offsetToCube, cubeDistance, hasLineOfSight, getHexLine } from '../utils/gameHelpers';
import { getMaxRangedRange, getMeleeRange } from '../utils/weaponHelpers';

// Helper functions are now in BoardDisplay.tsx - removed from here

// Objective control map type - tracks which player controls each objective
type ObjectiveControllers = { [objectiveName: string]: number | null };

// Calculate objective control with PERSISTENT control rules
// Once a player controls an objective, they keep it until opponent gets strictly higher OC
// Returns a map of "col,row" -> controller (0, 1, or null for contested/uncontrolled)
function calculateObjectiveControl(
  units: Unit[],
  objectives: Array<{ name: string; hexes: Array<{ col: number; row: number }> }> | undefined,
  flatObjectiveHexes: [number, number][] | undefined,
  currentControllers: ObjectiveControllers  // Persistent control state
): { controlMap: { [hexKey: string]: number | null }, updatedControllers: ObjectiveControllers } {
  const controlMap: { [hexKey: string]: number | null } = {};
  const updatedControllers: ObjectiveControllers = { ...currentControllers };

  // Build a map of hex -> objective for grouped objectives
  const hexToObjective = new Map<string, string>();

  if (objectives && objectives.length > 0) {
    // Grouped format: [{name, hexes: [{col, row}]}]
    for (const obj of objectives) {
      for (const hex of obj.hexes) {
        hexToObjective.set(`${hex.col},${hex.row}`, obj.name);
      }
    }
  } else if (flatObjectiveHexes && flatObjectiveHexes.length > 0) {
    // Flat format: [[col, row], ...]
    for (const [col, row] of flatObjectiveHexes) {
      hexToObjective.set(`${col},${row}`, 'unnamed');
    }
  }

  // Group hexes by objective name to calculate control per objective
  const objectiveGroups = new Map<string, Array<{ col: number; row: number }>>();
  for (const [hexKey, objName] of hexToObjective.entries()) {
    const [col, row] = hexKey.split(',').map(Number);
    if (!objectiveGroups.has(objName)) {
      objectiveGroups.set(objName, []);
    }
    objectiveGroups.get(objName)!.push({ col, row });
  }

  // Calculate control for each objective group
  for (const [objName, hexes] of objectiveGroups.entries()) {
    // Build hex set for this objective
    const hexSet = new Set(hexes.map(h => `${h.col},${h.row}`));

    // Count OC per player for units on this objective's hexes
    let p0_oc = 0;
    let p1_oc = 0;

    for (const unit of units) {
      if (unit.HP_CUR <= 0) continue; // Dead units don't control

      const unitHex = `${unit.col},${unit.row}`;
      if (hexSet.has(unitHex)) {
        const oc = unit.OC ?? 1; // Default OC=1 if not specified
        if (unit.player === 0) {
          p0_oc += oc;
        } else {
          p1_oc += oc;
        }
      }
    }

    // Get current controller from persistent state
    const currentController = currentControllers[objName] ?? null;

    // Determine new controller with PERSISTENT control rules
    let newController: number | null = currentController;  // Default: keep current

    if (p0_oc > p1_oc) {
      // P0 has more OC - P0 captures/keeps
      newController = 0;
    } else if (p1_oc > p0_oc) {
      // P1 has more OC - P1 captures/keeps
      newController = 1;
    }
    // If equal OC: current controller keeps control (no change)

    // Update persistent state
    updatedControllers[objName] = newController;

    // Assign control to all hexes in this objective
    for (const hex of hexes) {
      controlMap[`${hex.col},${hex.row}`] = newController;
    }
  }

  return { controlMap, updatedControllers };
}

type Mode = "select" | "movePreview" | "attackPreview" | "targetPreview" | "chargePreview" | "advancePreview";

type BoardProps = {
  units: Unit[];
  selectedUnitId: number | null;
  eligibleUnitIds: number[];
  showHexCoordinates?: boolean;
  shootingActivationQueue?: Unit[];
  activeShootingUnit?: Unit | null;
  shootingTargetId?: number | null; // For replay mode: shows explosion icon on target
  shootingUnitId?: number | null; // For replay mode: shows shooting indicator on shooter
  movingUnitId?: number | null; // For replay mode: shows boot icon on moving unit
  chargingUnitId?: number | null; // For replay mode: shows lightning icon on charging unit
  chargeTargetId?: number | null; // For replay mode: shows lightning icon on charge target
  fightingUnitId?: number | null; // For replay mode: shows crossed swords icon on fighting unit
  fightTargetId?: number | null; // For replay mode: shows explosion icon on fight target
  // Charge roll display for replay mode
  chargeRoll?: number | null; // The charge roll value to display
  chargeSuccess?: boolean; // Whether the charge was successful
  // Advance roll display
  advanceRoll?: number | null;
  advancingUnitId?: number | null;
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
  onActivateFight?: (fighterId: number) => void;
  currentPlayer: 0 | 1;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  unitsFled?: number[];
  fightSubPhase?: FightSubPhase; // NEW
  fightActivePlayer?: PlayerId; // NEW
  phase: "move" | "shoot" | "charge" | "fight";
  onCharge?: (chargerId: number, targetId: number) => void;
  onActivateCharge?: (chargerId: number) => void;
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
  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Advance action callback
  onAdvance?: (unitId: number) => void;
  onAdvanceMove?: (unitId: number | string, destCol: number, destRow: number) => void;
  onCancelAdvance?: () => void;
  getAdvanceDestinations?: (unitId: number) => { col: number; row: number }[];
  advanceWarningPopup?: { unitId: number; timestamp: number } | null;
  onConfirmAdvanceWarning?: () => void;
  onCancelAdvanceWarning?: () => void;
  onSkipAdvanceWarning?: () => void;
  showAdvanceWarningPopup?: boolean; // If false, skip advance warning popup
  wallHexesOverride?: Array<{ col: number; row: number }>; // For replay mode: override walls from log
  availableCellsOverride?: Array<{ col: number; row: number }>; // For replay mode: override available cells (green highlights)
  objectivesOverride?: Array<{ name: string; hexes: Array<{ col: number; row: number }> }>; // For replay mode: override objectives from log
};

export default function Board({
  units,
  selectedUnitId,
  eligibleUnitIds,
  showHexCoordinates = false,
  shootingActivationQueue,
  activeShootingUnit,
  shootingTargetId,
  shootingUnitId,
  movingUnitId,
  chargingUnitId,
  chargeTargetId,
  fightingUnitId,
  fightTargetId,
  chargeRoll,
  chargeSuccess,
  advanceRoll,
  advancingUnitId,
  mode,
  movePreview,
  attackPreview,
  // Blinking props
  blinkingUnits,
  isBlinkingActive,
  blinkState,
  onSelectUnit,
  onSkipUnit,
  onStartTargetPreview: _onStartTargetPreview,
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
  onActivateFight,
  onCharge,
  onActivateCharge,
  unitsCharged,
  unitsAttacked,
  unitsFled,
  fightSubPhase,
  fightActivePlayer,
  onMoveCharger,
  onCancelCharge,
  onValidateCharge,
  onLogChargeRoll,
  shootingPhaseState: _shootingPhaseState,
  targetPreview,
  onCancelTargetPreview,
  gameState,
  chargeRollPopup,
  getChargeDestinations,
  onAdvance,
  onAdvanceMove,
  onCancelAdvance,
  getAdvanceDestinations,
  advanceWarningPopup,
  onConfirmAdvanceWarning,
  onCancelAdvanceWarning,
  onSkipAdvanceWarning,
  showAdvanceWarningPopup = false,
  wallHexesOverride,
  availableCellsOverride,
  objectivesOverride,
}: BoardProps) {
  React.useEffect(() => {
  }, [phase, mode, selectedUnitId]);
  
  React.useEffect(() => {
  }, [phase, mode, selectedUnitId]);

  // ✅ HOOK 1: useRef - ALWAYS called first
  const containerRef = useRef<HTMLDivElement>(null);

  // Persistent objective control state - survives re-renders within an episode
  const objectiveControllersRef = useRef<ObjectiveControllers>({});
  // Track last turn to detect episode reset
  const lastTurnRef = useRef<number | null>(null);
  
  // Persistent container for UI elements (target logos, charge badges) that should never be cleaned up
  const uiElementsContainerRef = useRef<PIXI.Container | null>(null);

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
    onActivateFight?: (fighterId: number) => void;
    onCharge?: (chargerId: number, targetId: number) => void;
    onActivateCharge?: (chargerId: number) => void;
    onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
    onCancelCharge?: () => void;
    onCancelAdvance?: () => void;
    onAdvanceMove?: (unitId: number | string, destCol: number, destRow: number) => void;
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
    onActivateCharge,
    onMoveCharger,
    onCancelCharge,
    onCancelAdvance,
    onAdvanceMove,
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
    onActivateFight,
    onCharge,
    onActivateCharge,
    onMoveCharger,
    onCancelCharge,
    onCancelAdvance,
    onAdvanceMove,
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
    const ELIGIBLE_COLOR = parseColor(boardConfig.colors.eligible!);

    // Use wallHexesOverride if provided (from replay), otherwise use config wall_hexes
    const effectiveWallHexes: [number, number][] = wallHexesOverride
      ? wallHexesOverride.map(w => [w.col, w.row] as [number, number])
      : (boardConfig.wall_hexes || []);

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
    const UNIT_CIRCLE_RADIUS_RATIO = displayConfig.unit_circle_radius_ratio!;
    const UNIT_TEXT_SIZE = displayConfig.unit_text_size!;
    const SELECTED_BORDER_WIDTH = displayConfig.selected_border_width!;
    const CHARGE_TARGET_BORDER_WIDTH = displayConfig.charge_target_border_width!;
    const DEFAULT_BORDER_WIDTH = displayConfig.default_border_width!;

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

    // ✅ CREATE PERSISTENT UI CONTAINER for target logos, charge badges, etc.
    // This container is NEVER cleaned up by drawBoard()
    // Always recreate/re-add to ensure it's on the stage
    if (!uiElementsContainerRef.current || !app.stage.children.includes(uiElementsContainerRef.current)) {
      // Remove old container if it exists but is not on stage
      if (uiElementsContainerRef.current && !app.stage.children.includes(uiElementsContainerRef.current)) {
        uiElementsContainerRef.current = null;
      }
      // Create new container
      uiElementsContainerRef.current = new PIXI.Container();
      uiElementsContainerRef.current.name = 'ui-elements-container';
      uiElementsContainerRef.current.zIndex = 10000; // Very high z-index to be on top
      app.stage.addChild(uiElementsContainerRef.current);
      console.log(`🟢 BoardPvp: Created UI container and added to stage. Stage now has ${app.stage.children.length} children`);
    }

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
      onCancelAdvance: stableCallbacks.current.onCancelAdvance,
      onActivateCharge: stableCallbacks.current.onActivateCharge,
      onActivateFight: stableCallbacks.current.onActivateFight,
      onMoveCharger: stableCallbacks.current.onMoveCharger,
      onAdvanceMove: stableCallbacks.current.onAdvanceMove,
      onStartMovePreview: onStartMovePreview,
      onDirectMove: (unitId: number | string, col: number | string, row: number | string) => {
        onDirectMove(unitId, col, row);
      },
    });

    // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Listen for advance button click
    const advanceClickHandler = (e: Event) => {
      const { unitId } = (e as CustomEvent<{ unitId: number }>).detail;
      console.log("🟠 ADVANCE CLICK: unitId =", unitId);
      if (onAdvance) {
        onAdvance(unitId);
      }
    };
    window.addEventListener('boardAdvanceClick', advanceClickHandler);

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
    if (phase === "fight" && mode === "attackPreview" && selectedUnit) {
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);

      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers (imported at top)
      
      // Check if unit has melee weapons
      if (!selectedUnit.CC_WEAPONS || selectedUnit.CC_WEAPONS.length === 0) {
        throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) has no melee weapons for fight phase`);
      }

      const fightRange = getMeleeRange(); // Always 1

      // Find all enemies within CC_RNG range
      fightTargets = units.filter(u =>
        u.player !== selectedUnit.player &&
        u.HP_CUR > 0 &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) <= fightRange
      );
    }

    // ✅ SIMPLIFIED SHOOTING PREVIEW - No animations to prevent re-render loop
    if (phase === "shoot" && mode === "attackPreview" && selectedUnit && attackPreview) {
      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers (imported at top)
      
      // Check if unit has ranged weapons
      if (!selectedUnit.RNG_WEAPONS || selectedUnit.RNG_WEAPONS.length === 0) {
        throw new Error(`Unit ${selectedUnit.id} (${selectedUnit.type || 'unknown'}) has no ranged weapons for shooting phase`);
      }
      
      // Simple target identification - no state changes here
      // Target identification is handled elsewhere
    }

    // ✅ SIMPLIFIED FIGHT PREVIEW - No animations to prevent re-render loop
    if (phase === "fight" && selectedUnit) {
      // Simple target identification - no state changes here
      // Target identification is handled by fightTargets array above
    }

    // AI_TURN.md: Show charge destinations in both select and chargePreview modes
    if (phase === "charge" && (mode === "chargePreview" || mode === "select") && selectedUnit) {
      // Check if this unit is eligible to charge
      const isEligible = eligibleUnitIds.includes(typeof selectedUnit.id === 'number' ? selectedUnit.id : parseInt(selectedUnit.id as string));

      if (isEligible) {
        // AI_TURN.md: Get charge destinations from backend (already rolled and calculated)
        const rawChargeCells = getChargeDestinations(selectedUnit.id);
        
        // CRITICAL FIX: Filter out occupied hexes - occupied hexes should NEVER be valid destinations
        // Even though backend filters these, add defensive check here
        chargeCells = rawChargeCells.filter(dest => {
          // Check if any unit occupies this hex
          const isOccupied = units.some(u => 
            u.col === dest.col && 
            u.row === dest.row && 
            u.HP_CUR > 0
          );
          if (isOccupied) {
            console.log(`🛡️ CHARGE FIX: Filtered out occupied hex at (${dest.col}, ${dest.row})`);
          }
          return !isOccupied;  // Only include if NOT occupied
        });

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

        // Use cube coordinate system for proper hex neighbors
        const cubeDirections = [
          [1, -1, 0], [1, 0, -1], [0, 1, -1], 
          [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
        ];

        // Collect all forbidden hexes (adjacent to any enemy + wall hexes) using cube coordinates  
        const forbiddenSet = new Set<string>();
        
        // Add all wall hexes as forbidden
        const wallHexSet = new Set<string>(
          effectiveWallHexes.map((wall: number[]) => `${wall[0]},${wall[1]}`)
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

      } else if (phase !== "charge") {
        // For other phases (except charge), just show green circle on unit's hex
        // Charge phase uses chargeCells (orange) for destinations instead
        availableCells.push({ col: selectedUnit.col, row: selectedUnit.row });
      }
    }

    // Green circles for all eligible charge units (except the selected one which shows orange destinations)
    // CRITICAL: Only add units from the current player to avoid highlighting enemy units
    if (phase === "charge" && mode === "select") {
      eligibleUnitIds.forEach(unitId => {
        const eligibleUnit = units.find(u => u.id === unitId);
        // Don't add green highlight for selected unit - it will show orange charge destinations instead
        // CRITICAL: Also check that unit belongs to current player to avoid highlighting enemy units
        if (eligibleUnit && eligibleUnit.id !== selectedUnitId && eligibleUnit.player === currentPlayer) {
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
          if (distance <= (getMaxRangedRange(selectedUnit) || 0)) {
            const lineOfSight = hasLineOfSight(
              { col: selectedUnit.col, row: selectedUnit.row },
              { col: enemy.col, row: enemy.row },
              effectiveWallHexes
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
          mode !== "advancePreview" &&
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
              if (distance <= (getMaxRangedRange(previewUnit) || 0)) {
                const lineOfSight = hasLineOfSight(
                  { col: attackFromCol, row: attackFromRow },
                  { col: enemy.col, row: enemy.row },
                  effectiveWallHexes
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
          // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers (imported at top)
          
          let range: number;
          if (phase === "fight") {
            // Check if unit has melee weapons
            if (!previewUnit.CC_WEAPONS || previewUnit.CC_WEAPONS.length === 0) {
              throw new Error(`Unit ${previewUnit.id} (${previewUnit.type || 'unknown'}) has no melee weapons for fight phase preview`);
            }
            range = getMeleeRange(); // Always 1
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
            // Check if unit has ranged weapons
            if (!previewUnit.RNG_WEAPONS || previewUnit.RNG_WEAPONS.length === 0) {
              throw new Error(`Unit ${previewUnit.id} (${previewUnit.type || 'unknown'}) has no ranged weapons for shooting phase preview`);
            }
            range = getMaxRangedRange(previewUnit);
            
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
                    effectiveWallHexes
                  );
                  
                  
                  if (lineOfSight.canSee && lineOfSight.inCover) {
                    // Mark this enemy as in cover
                    coverCells.push({ col: enemy.col, row: enemy.row });
                    coverTargets.add(`${enemy.col},${enemy.row}`);
                    
                    // Mark all hexes in the path that contribute to cover (but exclude wall hexes)
                    const pathHexes: any[] = getHexLine(attackFromCol!, attackFromRow!, enemy.col, enemy.row);
                    const wallHexSet = new Set<string>(
                      effectiveWallHexes.map((wall: number[]) => `${wall[0]},${wall[1]}`)
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
                          effectiveWallHexes
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
      // Override wall_hexes if wallHexesOverride is provided (for replay mode)
      // Override objective_hexes if objectivesOverride is provided (for replay mode)
      // Convert grouped objectives format to flat hex list for BoardDisplay
      let effectiveObjectiveHexes: [number, number][] = boardConfig.objective_hexes || [];
      if (objectivesOverride && objectivesOverride.length > 0) {
        // Flatten grouped objectives: [{name, hexes: [{col,row}]}] -> [[col,row], ...]
        effectiveObjectiveHexes = [];
        for (const obj of objectivesOverride) {
          for (const hex of obj.hexes) {
            effectiveObjectiveHexes.push([hex.col, hex.row]);
          }
        }
      }

      const boardConfigWithOverrides = {
        ...boardConfig,
        wall_hexes: wallHexesOverride ? effectiveWallHexes : boardConfig.wall_hexes,
        objective_hexes: effectiveObjectiveHexes
      };
      // Override availableCells if availableCellsOverride is provided (for replay mode)
      const effectiveAvailableCells = availableCellsOverride || availableCells;

      // Detect episode reset: if turn goes back to 1 (or decreases), reset objective controllers
      const currentTurn = gameState?.turn ?? gameState?.currentTurn ?? 1;
      if (lastTurnRef.current !== null && currentTurn < lastTurnRef.current) {
        // New episode started - reset persistent objective control
        objectiveControllersRef.current = {};
      }
      lastTurnRef.current = currentTurn;

      // Calculate objective control based on unit positions with PERSISTENT control
      const { controlMap: objectiveControl, updatedControllers } = calculateObjectiveControl(
        units,
        objectivesOverride,
        effectiveObjectiveHexes,
        objectiveControllersRef.current
      );
      // Update persistent state
      objectiveControllersRef.current = updatedControllers;

      drawBoard(app, boardConfigWithOverrides as any, {
        availableCells: effectiveAvailableCells,
        attackCells,
        coverCells,
        chargeCells,
        advanceCells: (mode === "advancePreview" && selectedUnitId && getAdvanceDestinations) 
          ? getAdvanceDestinations(selectedUnitId) 
          : [],  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Populated when in advancePreview mode
        blockedTargets,
        coverTargets,
        phase,
        selectedUnitId,
        mode,
        showHexCoordinates,
        objectiveControl
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
        console.log(`🟢 BoardPvp: Rendering unit ${unit.id} (HP: ${unit.HP_CUR}, player: ${unit.player})`);
        const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

        // Skip units that are being previewed elsewhere
        if (mode === "movePreview" && movePreview && unit.id === movePreview.unitId) continue;
        if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) continue;

        // AI_TURN.md: Use backend's blinkingUnits list for shootability (authoritative LoS calculation)
        // Backend has already calculated valid targets with proper LoS checks
        let isShootable = true;
        // ONLY apply greying in PvP mode when we have actual blinking data
        // - Replay mode: blinkingUnits is undefined → skip greying
        // - PvP mode before backend responds: blinkingUnits is [] → skip greying (prevents grey flash)
        // - PvP mode with targets: blinkingUnits has IDs → apply greying
        if (phase === "shoot" && unit.player !== currentPlayer && selectedUnitId !== null && blinkingUnits && blinkingUnits.length > 0) {
          // Only grey out units that are NOT in the blinkingUnits list
          isShootable = blinkingUnits.includes(unit.id);
        }
        
        // Debug only for key units - EXACT UnitRenderer.tsx logic check
        if (unit.id === 8 || unit.id === 9) {
          // Debug code removed - variables were not used
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
          return eligibleUnitIds.includes(typeof unit.id === 'number' ? unit.id : parseInt(unit.id as string));
        })();
        
        // AI_TURN.md: During charge phase, show selected unit as ghost (darkened) at origin
        // This indicates the unit is about to move, similar to movement preview
        // In replay mode, a separate ghost unit is added, so we check if one already exists
        const hasExistingGhost = units.some((u: any) => u.isGhost && u.id < 0);
        const isChargeOrigin = phase === "charge" &&
          mode === "select" &&
          unit.id === selectedUnitId &&
          chargeCells.length > 0 &&
          !hasExistingGhost;  // Don't ghost the real unit if replay mode already added a ghost

        const unitToRender = isChargeOrigin
          ? { ...unit, isGhost: true } as Unit & { isGhost: boolean }
          : unit;

        renderUnit({
          unit: unitToRender, centerX, centerY, app,
          uiElementsContainer: uiElementsContainerRef.current!, // Pass persistent UI container
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
          blinkingUnits, isBlinkingActive, blinkState,
          // Pass shooting indicators
          shootingTargetId,
          shootingUnitId,
          // Pass movement indicator
          movingUnitId,
          // Pass charge indicators
          chargingUnitId,
          // Calculate chargeTargetId: prioritize props (for failed/successful charges) over chargeTargets (for preview)
          // CRITICAL: chargeTargetId from props takes precedence as it comes from actual charge result
          chargeTargetId: (() => {
            const finalTargetId = chargeTargetId ?? (chargeTargets.length > 0 ? chargeTargets[0].id : null);
            if (finalTargetId) {
              console.log("🎯 BoardPvp: Passing chargeTargetId to UnitRenderer:", finalTargetId, "for unit:", unitToRender.id);
            }
            return finalTargetId;
          })(),
          // Pass fight indicators
          fightingUnitId,
          fightTargetId,
          // Pass charge roll info for replay mode
          chargeRoll,
          chargeSuccess,
          // Advance roll display
          advanceRoll,
          advancingUnitId,
          // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Advance action props
          canAdvance: (phase === 'shoot' && isEligibleForRendering && !unitsFled?.includes(unit.id)) ?? false,
          onAdvance: (unitId: number) => {
            window.dispatchEvent(new CustomEvent('boardAdvanceClick', { detail: { unitId } }));
          }
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

      // ✅ ADVANCE WARNING POPUP RENDERING
      if (showAdvanceWarningPopup && advanceWarningPopup && onConfirmAdvanceWarning && onCancelAdvanceWarning && onSkipAdvanceWarning) {
        const popupContainer = new PIXI.Container();
        popupContainer.name = 'advance-warning-popup';
        popupContainer.zIndex = 10001; // Above charge roll popup
        
        const popupWidth = 450;
        const popupHeight = 200;
        
        // Create popup background
        const popupBg = new PIXI.Graphics();
        popupBg.beginFill(0x000000, 0.95);
        popupBg.lineStyle(3, 0xFFAA00, 1.0); // Orange border for warning
        popupBg.drawRoundedRect(0, 0, popupWidth, popupHeight, 10);
        popupBg.endFill();
        
        // Create warning text
        const warningText = new PIXI.Text('WARNING !', {
          fontSize: 28,
          fill: 0xFFAA00,
          fontWeight: 'bold',
          align: 'center'
        });
        warningText.anchor.set(0.5);
        warningText.position.set(popupWidth / 2, 35);
        
        // Create message text
        const messageText = new PIXI.Text('Making an advance move won\'t allow you to shoot or charge in this turn.', {
          fontSize: 18,
          fill: 0xFFFFFF,
          align: 'center',
          wordWrap: true,
          wordWrapWidth: popupWidth - 40
        });
        messageText.anchor.set(0.5);
        messageText.position.set(popupWidth / 2, 85);
        
        // Create Confirm button
        const buttonWidth = 100;
        const buttonHeight = 36;
        const buttonSpacing = 25;
        const buttonY = popupHeight - 56;
        const confirmButtonX = 50;
        
        const confirmButtonBg = new PIXI.Graphics();
        confirmButtonBg.beginFill(0x00AA00, 0.9);
        confirmButtonBg.lineStyle(2, 0x00FF00, 1.0);
        confirmButtonBg.drawRoundedRect(0, 0, buttonWidth, buttonHeight, 5);
        confirmButtonBg.endFill();
        confirmButtonBg.position.set(confirmButtonX, buttonY);
        confirmButtonBg.eventMode = 'static';
        confirmButtonBg.cursor = 'pointer';
        confirmButtonBg.on('pointerdown', () => {
          onConfirmAdvanceWarning();
        });
        
        const confirmText = new PIXI.Text('Confirm', {
          fontSize: 18,
          fill: 0xFFFFFF,
          fontWeight: 'bold',
          align: 'center'
        });
        confirmText.anchor.set(0.5);
        confirmText.position.set(confirmButtonX + buttonWidth / 2, buttonY + buttonHeight / 2);
        confirmText.eventMode = 'static';
        confirmText.cursor = 'pointer';
        confirmText.on('pointerdown', () => {
          onConfirmAdvanceWarning();
        });
        
        // Create Skip button (in the middle)
        const skipButtonX = confirmButtonX + buttonWidth + buttonSpacing;
        const skipButtonBg = new PIXI.Graphics();
        skipButtonBg.beginFill(0x666666, 0.9);
        skipButtonBg.lineStyle(2, 0x888888, 1.0);
        skipButtonBg.drawRoundedRect(0, 0, buttonWidth, buttonHeight, 5);
        skipButtonBg.endFill();
        skipButtonBg.position.set(skipButtonX, buttonY);
        skipButtonBg.eventMode = 'static';
        skipButtonBg.cursor = 'pointer';
        skipButtonBg.on('pointerdown', () => {
          onSkipAdvanceWarning();
        });
        
        const skipText = new PIXI.Text('Skip', {
          fontSize: 18,
          fill: 0xFFFFFF,
          fontWeight: 'bold',
          align: 'center'
        });
        skipText.anchor.set(0.5);
        skipText.position.set(skipButtonX + buttonWidth / 2, buttonY + buttonHeight / 2);
        skipText.eventMode = 'static';
        skipText.cursor = 'pointer';
        skipText.on('pointerdown', () => {
          onSkipAdvanceWarning();
        });
        
        // Create Cancel button
        const cancelButtonX = skipButtonX + buttonWidth + buttonSpacing;
        const cancelButtonBg = new PIXI.Graphics();
        cancelButtonBg.beginFill(0xAA0000, 0.9);
        cancelButtonBg.lineStyle(2, 0xFF0000, 1.0);
        cancelButtonBg.drawRoundedRect(0, 0, buttonWidth, buttonHeight, 5);
        cancelButtonBg.endFill();
        cancelButtonBg.position.set(cancelButtonX, buttonY);
        cancelButtonBg.eventMode = 'static';
        cancelButtonBg.cursor = 'pointer';
        cancelButtonBg.on('pointerdown', () => {
          onCancelAdvanceWarning();
        });
        
        const cancelText = new PIXI.Text('Cancel', {
          fontSize: 18,
          fill: 0xFFFFFF,
          fontWeight: 'bold',
          align: 'center'
        });
        cancelText.anchor.set(0.5);
        cancelText.position.set(cancelButtonX + buttonWidth / 2, buttonY + buttonHeight / 2);
        cancelText.eventMode = 'static';
        cancelText.cursor = 'pointer';
        cancelText.on('pointerdown', () => {
          onCancelAdvanceWarning();
        });
        
        // Position popup in center of screen
        popupContainer.position.set((canvasWidth - popupWidth) / 2, (canvasHeight - popupHeight) / 2);
        popupContainer.addChild(popupBg);
        popupContainer.addChild(warningText);
        popupContainer.addChild(messageText);
        popupContainer.addChild(confirmButtonBg);
        popupContainer.addChild(confirmText);
        popupContainer.addChild(skipButtonBg);
        popupContainer.addChild(skipText);
        popupContainer.addChild(cancelButtonBg);
        popupContainer.addChild(cancelText);
        
        app.stage.addChild(popupContainer);
      }

      // Line of sight indicators are now handled by drawBoard() in BoardDisplay.tsx
      
      // Wall rendering is now handled by drawBoard() in BoardDisplay.tsx

      // Cleanup function
      return () => {
        // Cleanup board interactions
        cleanupBoardInteractions(app);
        
        if (app && app.stage) {
          // Destroy all sprites but preserve textures in cache to prevent black flashing
          // Textures will be reused from cache on next render
          app.stage.children.forEach(child => {
            if (child.destroy) {
              // Don't destroy textures - they should remain in cache for reuse
              child.destroy({ children: true, texture: false, baseTexture: false });
            }
          });
          app.stage.removeChildren();
        }
        // Don't destroy textures when destroying app - preserve cache
        app.destroy(true, { children: true, texture: false, baseTexture: false });
      };

      }, [
        // Essential dependencies only - prevent infinite re-renders
        units.length,
        JSON.stringify(units.map(u => ({ id: u.id, col: u.col, row: u.row, HP_CUR: u.HP_CUR, SHOOT_LEFT: u.SHOOT_LEFT, ATTACK_LEFT: u.ATTACK_LEFT }))), // Track position, HP, shooting & fight changes
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
        showHexCoordinates,
        // Add shooting indicators to trigger re-render
        shootingTargetId,
        shootingUnitId,
        // Add charge indicators to trigger re-render when charge target changes
        chargeTargetId,
        chargingUnitId,
        // Add wall override for replay mode
        JSON.stringify(wallHexesOverride),
        // AI_TURN.md: Add charge destinations to trigger re-render when backend returns valid destinations
        getChargeDestinations
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