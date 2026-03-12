// frontend/src/components/BoardPvp.tsx

import * as PIXI from "pixi.js-legacy";
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  TUTORIAL_STEP_TITLES_INTERCESSOR_HALO,
  useTutorial,
} from "../contexts/TutorialContext";
import { useGameConfig } from "../hooks/useGameConfig";
import type {
  FightSubPhase,
  GameState,
  PlayerId,
  Position,
  PrimaryObjectiveRule,
  ShootingPhaseState,
  TargetPreview,
  Unit,
  Weapon,
  WeaponOption,
} from "../types/game";
// import { SingleShotDisplay } from './SingleShotDisplay';
import { setupBoardClickHandler } from "../utils/boardClickHandler";
import {
  areUnitsAdjacent,
  cubeDistance,
  getHexLine,
  hasLineOfSight,
  offsetToCube,
} from "../utils/gameHelpers";
import { getMaxRangedRange, getMeleeRange } from "../utils/weaponHelpers";
import { drawBoard } from "./BoardDisplay";
import { renderUnit } from "./UnitRenderer";
import { WeaponDropdown } from "./WeaponDropdown";

// Helper functions are now in BoardDisplay.tsx - removed from here

// Objective control map type - tracks which player controls each objective
type ObjectiveControllers = { [objectiveName: string]: number | null };

interface ReplayRules {
  primary_objective: PrimaryObjectiveRule | PrimaryObjectiveRule[] | null;
}

// Calculate objective control with PERSISTENT control rules
// Once a player controls an objective, they keep it until opponent gets strictly higher OC
// Returns a map of "col,row" -> controller (0, 1, or null for contested/uncontrolled)
function calculateObjectiveControl(
  units: Unit[],
  objectives: Array<{ name: string; hexes: Array<{ col: number; row: number }> }> | undefined,
  flatObjectiveHexes: [number, number][] | undefined,
  currentControllers: ObjectiveControllers, // Persistent control state
  usePersistentState: boolean = true, // If false, recalculate control based only on current state
  tieBehavior?: string,
  controlMethod?: string
): { controlMap: { [hexKey: string]: number | null }; updatedControllers: ObjectiveControllers } {
  const controlMap: { [hexKey: string]: number | null } = {};
  const shouldUseSticky = usePersistentState && controlMethod === "sticky";
  const updatedControllers: ObjectiveControllers = shouldUseSticky ? { ...currentControllers } : {};

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
      hexToObjective.set(`${col},${row}`, "unnamed");
    }
  }

  // Group hexes by objective name to calculate control per objective
  const objectiveGroups = new Map<string, Array<{ col: number; row: number }>>();
  for (const [hexKey, objName] of hexToObjective.entries()) {
    const [col, row] = hexKey.split(",").map(Number);
    if (!objectiveGroups.has(objName)) {
      objectiveGroups.set(objName, []);
    }
    objectiveGroups.get(objName)!.push({ col, row });
  }

  // Calculate control for each objective group
  for (const [objName, hexes] of objectiveGroups.entries()) {
    // Build hex set for this objective
    const hexSet = new Set(hexes.map((h) => `${h.col},${h.row}`));

    // Count OC per player for units on this objective's hexes
    let p1_oc = 0;
    let p2_oc = 0;

    for (const unit of units) {
      if (unit.HP_CUR <= 0) continue; // Dead units don't control

      const unitHex = `${unit.col},${unit.row}`;
      if (hexSet.has(unitHex)) {
        const oc = unit.OC ?? 1; // Default OC=1 if not specified
        if (unit.player === 1) {
          p1_oc += oc;
        } else {
          p2_oc += oc;
        }
      }
    }

    // Get current controller from persistent state (only if using sticky control)
    const currentController = shouldUseSticky ? (currentControllers[objName] ?? null) : null;

    // Determine new controller with PERSISTENT control rules (or instant calculation if not using persistent state)
    let newController: number | null = shouldUseSticky ? currentController : null; // Default: keep current if sticky, otherwise null

    if (p1_oc > p2_oc) {
      // P1 has more OC - P1 captures/keeps
      newController = 1;
    } else if (p2_oc > p1_oc) {
      // P2 has more OC - P2 captures/keeps
      newController = 2;
    } else if (!shouldUseSticky) {
      // If equal OC and not using persistent state: no control
      newController = null;
    } else if (currentController === null) {
      if (tieBehavior === "no_control") {
        newController = null;
      } else {
        throw new Error(`Unsupported objective tie behavior: ${tieBehavior}`);
      }
    }
    // If equal OC and using persistent state with existing controller: keep control

    // Update persistent state
    updatedControllers[objName] = newController;

    // Assign control to all hexes in this objective
    for (const hex of hexes) {
      controlMap[`${hex.col},${hex.row}`] = newController;
    }
  }

  return { controlMap, updatedControllers };
}

type Mode =
  | "select"
  | "movePreview"
  | "attackPreview"
  | "targetPreview"
  | "chargePreview"
  | "advancePreview";

type BoardProps = {
  units: Unit[];
  selectedUnitId: number | null;
  ruleChoiceHighlightedUnitId?: number | null;
  eligibleUnitIds: number[];
  showHexCoordinates?: boolean;
  showLosDebugOverlay?: boolean;
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
  blinkingAttackerId?: number | null;
  isBlinkingActive?: boolean;
  blinkVersion?: number;
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
  onDeployUnit?: (unitId: number | string, destCol: number, destRow: number) => void;
  onFightAttack?: (attackerId: number, targetId: number | null) => void;
  onActivateFight?: (fighterId: number) => void;
  current_player: 1 | 2;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  unitsFled?: number[];
  fightSubPhase?: FightSubPhase; // NEW
  fightActivePlayer?: PlayerId; // NEW
  phase: "deployment" | "command" | "move" | "shoot" | "charge" | "fight";
  onCharge?: (chargerId: number, targetId: number) => void;
  onActivateCharge?: (chargerId: number) => void;
  onChargeEnemyUnit?: (chargerId: number, enemyUnitId: number) => void;
  onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
  onCancelCharge?: () => void;
  onValidateCharge?: (chargerId: number) => void;
  onLogChargeRoll?: (unit: Unit, roll: number) => void;
  shootingPhaseState?: ShootingPhaseState;
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
  /** Tutoriel : masquer l’icône Advance au-dessus des unités pendant certains steps. */
  hideAdvanceIconForTutorial?: boolean;
  wallHexesOverride?: Array<{ col: number; row: number }>; // For replay mode: override walls from log
  availableCellsOverride?: Array<{ col: number; row: number }>; // For replay mode: override available cells (green highlights)
  deploymentState?: GameState["deployment_state"];
  objectivesOverride?: Array<{ name: string; hexes: Array<{ col: number; row: number }> }>; // For replay mode: override objectives from log
  replayActionIndex?: number; // For replay mode: detect rollback and reset objective control
  autoSelectWeapon?: boolean;
};

export default function Board({
  units,
  selectedUnitId,
  ruleChoiceHighlightedUnitId = null,
  eligibleUnitIds,
  showHexCoordinates = false,
  showLosDebugOverlay = false,
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
  blinkingAttackerId,
  isBlinkingActive,
  blinkVersion,
  onSelectUnit,
  onSkipUnit,
  onStartMovePreview,
  onDirectMove,
  onStartAttackPreview,
  onConfirmMove,
  onCancelMove,
  current_player,
  unitsMoved,
  phase,
  onShoot,
  onDeployUnit,
  onFightAttack,
  onActivateFight,
  onCharge,
  onActivateCharge,
  onChargeEnemyUnit,
  unitsCharged,
  unitsAttacked,
  unitsFled,
  fightSubPhase,
  fightActivePlayer,
  onMoveCharger,
  onCancelCharge,
  onValidateCharge,
  onLogChargeRoll,
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
  hideAdvanceIconForTutorial = false,
  wallHexesOverride,
  availableCellsOverride,
  deploymentState,
  objectivesOverride,
  replayActionIndex,
  autoSelectWeapon,
}: BoardProps) {
  React.useEffect(() => {}, []);

  React.useEffect(() => {}, []);

  // ✅ HOOK 1: useRef - ALWAYS called first
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);

  // Persistent objective control state - survives re-renders within an episode
  const objectiveControllersRef = useRef<ObjectiveControllers>({});
  // Track last turn to detect episode reset
  const lastTurnRef = useRef<number | null>(null);
  const lastReplayActionIndexRef = useRef<number | null>(null);

  // Persistent container for UI elements (target logos, charge badges) that should never be cleaned up
  const uiElementsContainerRef = useRef<PIXI.Container | null>(null);

  // ✅ HOOK 2: useGameConfig - ALWAYS called second
  const { boardConfig, gameConfig, loading, error } = useGameConfig();
  // ✅ STABLE CALLBACK REFS - Don't change on every render
  const stableCallbacks = useRef<{
    onSelectUnit: (id: number | string | null) => void;
    onSkipUnit?: (unitId: number | string) => void;
    onStartMovePreview: (
      unitId: number | string,
      col: number | string,
      row: number | string
    ) => void;
    onDirectMove: (unitId: number | string, col: number | string, row: number | string) => void;
    onStartAttackPreview: (unitId: number, col: number, row: number) => void;
    onConfirmMove: () => void;
    onCancelMove: () => void;
    onShoot: (shooterId: number, targetId: number) => void;
    onDeployUnit?: (unitId: number | string, destCol: number, destRow: number) => void;
    onFightAttack?: (attackerId: number, targetId: number | null) => void;
    onActivateFight?: (fighterId: number) => void;
    onCharge?: (chargerId: number, targetId: number) => void;
    onActivateCharge?: (chargerId: number) => void;
    onChargeEnemyUnit?: (chargerId: number, enemyUnitId: number) => void;
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
    onDeployUnit,
    onFightAttack,
    onCharge,
    onActivateCharge,
    onChargeEnemyUnit,
    onMoveCharger,
    onCancelCharge,
    onCancelAdvance,
    onAdvanceMove,
    onValidateCharge,
    onLogChargeRoll,
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
    onDeployUnit,
    onFightAttack,
    onActivateFight,
    onCharge,
    onActivateCharge,
    onChargeEnemyUnit,
    onMoveCharger,
    onCancelCharge,
    onCancelAdvance,
    onAdvanceMove,
    onValidateCharge,
    onLogChargeRoll,
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

  // Weapon selection menu state
  const [weaponSelectionMenu, setWeaponSelectionMenu] = useState<{
    unitId: number;
    position: { x: number; y: number };
  } | null>(null);
  const [unitHoverTooltip, setUnitHoverTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);

  // Listen for weapon selection icon click
  useEffect(() => {
    if (!boardConfig) return; // Wait for board config to load

    const weaponClickHandler = (e: Event) => {
      const { unitId } = (e as CustomEvent<{ unitId: number }>).detail;
      const unit = units.find((u) => u.id === unitId);
      if (!unit || !unit.RNG_WEAPONS || unit.RNG_WEAPONS.length === 0) return;

      // Calculate position near the icon (top-right of unit)
      const canvas = canvasContainerRef.current?.querySelector("canvas");
      if (!canvas) return;

      // Calculate constants from boardConfig (same as in main useEffect)
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;

      const rect = canvas.getBoundingClientRect();
      // Position will be calculated relative to canvas, but we need screen coordinates for dropdown
      const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const centerY =
        unit.row * HEX_VERT_SPACING +
        ((unit.col % 2) * HEX_VERT_SPACING) / 2 +
        HEX_HEIGHT / 2 +
        MARGIN;

      setWeaponSelectionMenu({
        unitId,
        position: {
          x: rect.left + centerX + HEX_RADIUS * 0.6,
          y: rect.top + centerY - HEX_RADIUS * 0.6,
        },
      });
      window.dispatchEvent(new CustomEvent("weaponMenuOpened", { detail: { unitId } }));
    };

    window.addEventListener("boardWeaponSelectionClick", weaponClickHandler);
    return () => {
      window.removeEventListener("boardWeaponSelectionClick", weaponClickHandler);
    };
  }, [units, boardConfig]);

  // Tutoriel : halo autour de l'Intercessor quand la popup "Phase de mouvement" est affichée
  const tutorial = useTutorial();
  useLayoutEffect(() => {
    if (!tutorial?.setSpotlightPosition) return;
    const showSpotlight =
      tutorial.popupVisible &&
      tutorial.currentStep?.stepKey &&
      (TUTORIAL_STEP_TITLES_INTERCESSOR_HALO.includes(
        tutorial.currentStep.stepKey as (typeof TUTORIAL_STEP_TITLES_INTERCESSOR_HALO)[number]
      ) ||
        tutorial.currentStep?.stage === "1-4") &&
      boardConfig &&
      units.length > 0;
    if (!showSpotlight) {
      tutorial.setSpotlightPosition(null);
      return;
    }
    const p1Unit = units.find((u) => Number(u.player) === 1);
    if (!p1Unit || p1Unit.col == null || p1Unit.row == null) {
      tutorial.setSpotlightPosition(null);
      return;
    }
    const rect = canvasContainerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;
    const centerX =
      p1Unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const centerY =
      p1Unit.row * HEX_VERT_SPACING +
      ((p1Unit.col % 2) * HEX_VERT_SPACING) / 2 +
      HEX_HEIGHT / 2 +
      MARGIN;
    tutorial.setSpotlightPosition({
      shape: "circle",
      x: rect.left + centerX,
      y: rect.top + centerY,
      radius: 72,
    });
  }, [
    tutorial?.popupVisible,
    tutorial?.currentStep?.stepKey,
    tutorial?.currentStep?.stage,
    tutorial?.setSpotlightPosition,
    boardConfig,
    units,
  ]);

  const stableBlinkingUnits = useMemo(() => {
    if (!blinkingUnits) return undefined;
    const sorted = blinkingUnits.length > 0 ? [...blinkingUnits].sort((a, b) => a - b) : [];
    return sorted;
  }, [blinkingUnits]);

  // ✅ HOOK 3: useEffect - MINIMAL DEPENDENCIES TO PREVENT RE-RENDER LOOPS
  useEffect(() => {
    // Early returns INSIDE useEffect to avoid hooks order violation
    if (!canvasContainerRef.current) return;

    if (loading) {
      canvasContainerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#1f2937;border-radius:8px;color:white;">Loading board configuration...</div>`;
      if (overlayRef.current) {
        overlayRef.current.innerHTML = "";
      }
      return;
    }

    if (error) {
      canvasContainerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#7f1d1d;border-radius:8px;color:#fecaca;">Configuration Error: ${error}</div>`;
      if (overlayRef.current) {
        overlayRef.current.innerHTML = "";
      }
      return;
    }

    if (!boardConfig) {
      canvasContainerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#7f1d1d;border-radius:8px;color:#fecaca;">Board configuration not loaded</div>`;
      if (overlayRef.current) {
        overlayRef.current.innerHTML = "";
      }
      return;
    }
    if (!gameConfig) {
      canvasContainerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#7f1d1d;border-radius:8px;color:#fecaca;">Game configuration not loaded</div>`;
      if (overlayRef.current) {
        overlayRef.current.innerHTML = "";
      }
      return;
    }

    const isNewApp = !appRef.current;
    if (isNewApp) {
      canvasContainerRef.current.innerHTML = "";
    }

    // ✅ AGGRESSIVE TEXTURE CACHE CLEARING for movePreview units
    if (mode === "movePreview" && movePreview) {
      const previewUnit = units.find((u) => u.id === movePreview.unitId);
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
      return parseInt(colorStr.replace("0x", ""), 16);
    };

    // ✅ ALL COLORS FROM CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    const ELIGIBLE_COLOR = parseColor(boardConfig.colors.eligible!);

    // Use wallHexesOverride if provided (from replay), otherwise use config wall_hexes
    const effectiveWallHexes: [number, number][] = wallHexesOverride
      ? wallHexesOverride.map((w) => [w.col, w.row] as [number, number])
      : boardConfig.wall_hexes || [];
    const bottomRow = BOARD_ROWS - 1;
    const wallHexKeySet = new Set<string>(effectiveWallHexes.map(([c, r]) => `${c},${r}`));
    for (let col = 0; col < BOARD_COLS; col++) {
      if (col % 2 === 1) {
        const key = `${col},${bottomRow}`;
        if (!wallHexKeySet.has(key)) {
          wallHexKeySet.add(key);
          effectiveWallHexes.push([col, bottomRow]);
        }
      }
    }

    // ✅ ALL DISPLAY VALUES FROM CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    if (!boardConfig.display) {
      throw new Error("Missing required boardConfig.display configuration");
    }
    const displayConfig = boardConfig.display;

    // ✅ VALIDATE ALL REQUIRED VALUES ARE PRESENT FIRST - DIRECT PROPERTY ACCESS
    if (displayConfig.icon_scale === undefined || displayConfig.icon_scale === null) {
      throw new Error("Missing required configuration value: boardConfig.display.icon_scale");
    }
    if (
      displayConfig.eligible_outline_width === undefined ||
      displayConfig.eligible_outline_width === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.eligible_outline_width"
      );
    }
    if (
      displayConfig.eligible_outline_alpha === undefined ||
      displayConfig.eligible_outline_alpha === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.eligible_outline_alpha"
      );
    }
    if (
      displayConfig.hp_bar_width_ratio === undefined ||
      displayConfig.hp_bar_width_ratio === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.hp_bar_width_ratio"
      );
    }
    if (displayConfig.hp_bar_height === undefined || displayConfig.hp_bar_height === null) {
      throw new Error("Missing required configuration value: boardConfig.display.hp_bar_height");
    }
    if (
      displayConfig.hp_bar_y_offset_ratio === undefined ||
      displayConfig.hp_bar_y_offset_ratio === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.hp_bar_y_offset_ratio"
      );
    }
    if (
      displayConfig.unit_circle_radius_ratio === undefined ||
      displayConfig.unit_circle_radius_ratio === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.unit_circle_radius_ratio"
      );
    }
    if (displayConfig.unit_text_size === undefined || displayConfig.unit_text_size === null) {
      throw new Error("Missing required configuration value: boardConfig.display.unit_text_size");
    }
    if (
      displayConfig.selected_border_width === undefined ||
      displayConfig.selected_border_width === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.selected_border_width"
      );
    }
    if (
      displayConfig.charge_target_border_width === undefined ||
      displayConfig.charge_target_border_width === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.charge_target_border_width"
      );
    }
    if (
      displayConfig.default_border_width === undefined ||
      displayConfig.default_border_width === null
    ) {
      throw new Error(
        "Missing required configuration value: boardConfig.display.default_border_width"
      );
    }
    if (displayConfig.canvas_border === undefined || displayConfig.canvas_border === null) {
      throw new Error("Missing required configuration value: boardConfig.display.canvas_border");
    }

    // ✅ VALIDATE COLOR VALUES ARE PRESENT - DIRECT PROPERTY ACCESS
    if (!boardConfig.colors.attack) {
      throw new Error("Missing required configuration value: boardConfig.colors.attack");
    }
    if (!boardConfig.colors.charge) {
      throw new Error("Missing required configuration value: boardConfig.colors.charge");
    }
    if (!boardConfig.colors.eligible) {
      throw new Error("Missing required configuration value: boardConfig.colors.eligible");
    }
    const gameRules = gameConfig.game_rules;
    if (!gameRules) {
      throw new Error("Missing required configuration value: gameConfig.game_rules");
    }
    if (typeof gameRules.cover_ratio !== "number") {
      throw new Error("Missing required configuration value: gameConfig.game_rules.cover_ratio");
    }
    if (typeof gameRules.los_visibility_min_ratio !== "number") {
      throw new Error(
        "Missing required configuration value: gameConfig.game_rules.los_visibility_min_ratio"
      );
    }
    const coverRatio = gameRules.cover_ratio;
    const losVisibilityMinRatio = gameRules.los_visibility_min_ratio;

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
    const canvasPaddingX = 0;
    const canvasPaddingTop = 0;
    const canvasPaddingBottom = 0;
    const canvasWidth = gridWidth + 2 * MARGIN + 2 * canvasPaddingX;
    const canvasHeight = gridHeight + 2 * MARGIN + canvasPaddingTop + canvasPaddingBottom;

    // ✅ OPTIMIZED PIXI CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    const pixiConfig = {
      width: canvasWidth,
      height: canvasHeight,
      backgroundColor: parseInt(boardConfig.colors.background.replace("0x", ""), 16),
      backgroundAlpha: 1, // Ensure background is opaque
      antialias: displayConfig.antialias!,
      powerPreference: "high-performance" as WebGLPowerPreference,
      resolution:
        String(displayConfig.resolution) === "auto"
          ? window.devicePixelRatio || 1
          : typeof displayConfig.resolution === "number"
            ? displayConfig.resolution
            : 1,
      autoDensity: displayConfig.autoDensity!,
    };

    // ✅ VALIDATE PIXI CONFIG VALUES
    if (pixiConfig.antialias === undefined || pixiConfig.autoDensity === undefined) {
      throw new Error(
        "Missing required PIXI configuration values: antialias, autoDensity, or resolution"
      );
    }

    const app = appRef.current || new PIXI.Application(pixiConfig);
    if (!appRef.current) {
      appRef.current = app;
      app.stage.sortableChildren = true;
    } else {
      app.renderer.resize(canvasWidth, canvasHeight);
    }
    app.stage.position.set(canvasPaddingX, canvasPaddingTop);

    // ✅ CREATE PERSISTENT UI CONTAINER for target logos, charge badges, etc.
    // This container is NEVER cleaned up by drawBoard()
    // Always recreate/re-add to ensure it's on the stage
    if (
      !uiElementsContainerRef.current ||
      !app.stage.children.includes(uiElementsContainerRef.current)
    ) {
      // Remove old container if it exists but is not on stage
      if (
        uiElementsContainerRef.current &&
        !app.stage.children.includes(uiElementsContainerRef.current)
      ) {
        uiElementsContainerRef.current = null;
      }
      // Create new container
      uiElementsContainerRef.current = new PIXI.Container();
      uiElementsContainerRef.current.name = "ui-elements-container";
      uiElementsContainerRef.current.zIndex = 10000; // Very high z-index to be on top
      app.stage.addChild(uiElementsContainerRef.current);
    }

    // ✅ CANVAS STYLING FROM CONFIG - EXACT BOARDREPLAY MATCH
    const canvas = app.view as HTMLCanvasElement;
    canvas.style.display = "block";
    // Removed maxWidth constraint to allow full board size
    canvas.style.height = "auto";
    canvas.style.border = displayConfig?.canvas_border ?? "1px solid #333";

    // Clear container and append canvas - EXACT BOARDREPLAY MATCH
    if (isNewApp) {
      canvasContainerRef.current.innerHTML = "";
      canvasContainerRef.current.appendChild(canvas);
    }

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
        const unit = units.find((u) => u.id === shooterId);
        if (unit) {
          stableCallbacks.current.onStartAttackPreview(shooterId, unit.col, unit.row);
        }
      },
      onShoot: stableCallbacks.current.onShoot,
      onCombatAttack: stableCallbacks.current.onFightAttack || (() => {}),
      onConfirmMove: stableCallbacks.current.onConfirmMove,
      onCancelMove: stableCallbacks.current.onCancelMove,
      onCancelCharge: stableCallbacks.current.onCancelCharge,
      onCancelAdvance: stableCallbacks.current.onCancelAdvance,
      onDeployUnit: stableCallbacks.current.onDeployUnit,
      onActivateCharge: stableCallbacks.current.onActivateCharge,
      onActivateFight: stableCallbacks.current.onActivateFight,
      onMoveCharger: stableCallbacks.current.onMoveCharger,
      onChargeEnemyUnit: stableCallbacks.current.onChargeEnemyUnit || (() => {}),
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
    window.addEventListener("boardAdvanceClick", advanceClickHandler);

    // Right click cancels move/attack preview
    const contextMenuHandler = (e: Event) => {
      e.preventDefault();

      if (phase === "shoot" && mode === "movePreview") {
        onCancelMove?.();
      } else if (phase === "shoot") {
        // During shooting phase, only cancel target preview if one exists
        if (targetPreview) {
          onCancelTargetPreview?.();
        }
        // If no target preview, do nothing (don't cancel the whole shooting)
      } else if (mode === "movePreview" || mode === "attackPreview") {
        onCancelMove?.();
      }
    };
    if (app.view?.addEventListener) {
      app.view.addEventListener("contextmenu", contextMenuHandler);
    }

    // ✅ RESTRUCTURED: Calculate ALL highlight data BEFORE any drawBoard calls
    const availableCells: { col: number; row: number }[] = [];
    const selectedUnit = units.find((u) => u.id === selectedUnitId);

    if (phase === "deployment" && deploymentState) {
      const deployer = deploymentState.current_deployer ?? current_player;
      const pool =
        deploymentState.deployment_pools[String(deployer)] ||
        deploymentState.deployment_pools[
          deployer as unknown as keyof typeof deploymentState.deployment_pools
        ];
      if (pool) {
        pool.forEach((hex) => {
          if (Array.isArray(hex)) {
            availableCells.push({ col: Number(hex[0]), row: Number(hex[1]) });
          } else if (hex && typeof hex === "object" && "col" in hex && "row" in hex) {
            availableCells.push({
              col: Number((hex as { col: number }).col),
              row: Number((hex as { row: number }).row),
            });
          }
        });
      }
    }

    // Charge preview: chargeCells & targets
    let chargeCells: { col: number; row: number }[] = [];
    let chargeTargets: Unit[] = [];

    // Fight preview: fightTargets for red outline on enemies within fight range
    let fightTargets: Unit[] = [];
    const fightPreviewCells: { col: number; row: number }[] = [];
    if (phase === "fight" && mode === "attackPreview" && selectedUnit) {
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);

      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers (imported at top)

      // Check if unit has melee weapons
      if (!selectedUnit.CC_WEAPONS || selectedUnit.CC_WEAPONS.length === 0) {
        throw new Error(
          `Unit ${selectedUnit.id} (${selectedUnit.type || "unknown"}) has no melee weapons for fight phase`
        );
      }

      const fightRange = getMeleeRange(); // Always 1

      // Find all enemies within CC_RNG range
      fightTargets = units.filter(
        (u) =>
          u.player !== selectedUnit.player &&
          u.HP_CUR > 0 &&
          cubeDistance(c1, offsetToCube(u.col, u.row)) <= fightRange
      );

      // Fight preview requirement: show adjacent hexes around active unit in red.
      for (let col = 0; col < BOARD_COLS; col++) {
        for (let row = 0; row < BOARD_ROWS; row++) {
          if (cubeDistance(c1, offsetToCube(col, row)) === 1) {
            fightPreviewCells.push({ col, row });
          }
        }
      }
    }

    // ✅ SIMPLIFIED SHOOTING PREVIEW - No animations to prevent re-render loop
    if (phase === "shoot" && mode === "attackPreview" && selectedUnit && attackPreview) {
      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers (imported at top)

      // Check if unit has ranged weapons
      if (!selectedUnit.RNG_WEAPONS || selectedUnit.RNG_WEAPONS.length === 0) {
        throw new Error(
          `Unit ${selectedUnit.id} (${selectedUnit.type || "unknown"}) has no ranged weapons for shooting phase`
        );
      }

      // Simple target identification - no state changes here
      // Target identification is handled elsewhere
    }

    // ✅ SIMPLIFIED FIGHT PREVIEW - No animations to prevent re-render loop
    if (phase === "fight" && selectedUnit) {
      // Simple target identification - no state changes here
      // Target identification is handled by fightTargets array above
    }

    // Show charge destinations in both select and chargePreview modes
    if (phase === "charge" && (mode === "chargePreview" || mode === "select") && selectedUnit) {
      // Check if this unit is eligible to charge
      const isEligible = eligibleUnitIds.includes(
        typeof selectedUnit.id === "number"
          ? selectedUnit.id
          : parseInt(selectedUnit.id as string, 10)
      );

      if (isEligible) {
        // Get charge destinations from backend (already rolled and calculated)
        const rawChargeCells = getChargeDestinations(selectedUnit.id);

        // CRITICAL FIX: Filter out occupied hexes - occupied hexes should NEVER be valid destinations
        // Even though backend filters these, add defensive check here
        chargeCells = rawChargeCells.filter((dest) => {
          // Check if any unit occupies this hex
          const isOccupied = units.some(
            (u) => u.col === dest.col && u.row === dest.row && u.HP_CUR > 0
          );
          return !isOccupied; // Only include if NOT occupied
        });

        // Red outline: enemy units that can be reached via valid charge movement
        chargeTargets = units.filter((u) => {
          if (u.player === selectedUnit.player) return false;

          // Check if any valid charge destination is adjacent to this enemy
          return chargeCells.some((dest) => {
            const cube1 = offsetToCube(dest.col, dest.row);
            const cube2 = offsetToCube(u.col, u.row);
            return cubeDistance(cube1, cube2) === 1;
          });
        });
      }
    }

    // ✅ CALCULATE MOVEMENT PREVIEW BEFORE MAIN DRAWBOARD CALL
    if (
      selectedUnit &&
      mode === "select" &&
      eligibleUnitIds &&
      eligibleUnitIds.includes(
        typeof selectedUnit.id === "number"
          ? selectedUnit.id
          : parseInt(selectedUnit.id as string, 10)
      )
    ) {
      if (phase === "move") {
        // For Movement Phase, show available move destinations
        if (selectedUnit.MOVE === undefined || selectedUnit.MOVE === null) {
          throw new Error(
            `Unit ${selectedUnit.id} (${selectedUnit.type || "unknown"}) is missing required MOVE property for movement preview`
          );
        }
        if (!gameState) {
          throw new Error("Missing gameState during movement preview calculation");
        }
        if (!gameState.units_cache) {
          throw new Error("Missing units_cache in gameState during movement preview calculation");
        }

        const aliveUnitIds = new Set(Object.keys(gameState.units_cache).map((id) => id.toString()));
        const aliveUnits = units.filter((u) => aliveUnitIds.has(u.id.toString()));

        const centerCol = selectedUnit.col;
        const centerRow = selectedUnit.row;
        const selectedUnitKeywords = selectedUnit.UNIT_KEYWORDS;
        const hasFlyKeyword =
          Array.isArray(selectedUnitKeywords) &&
          selectedUnitKeywords.some((entry) => entry.keywordId === "fly");

        // Use cube coordinate system for proper hex neighbors
        const cubeDirections = [
          [1, -1, 0],
          [1, 0, -1],
          [0, 1, -1],
          [-1, 1, 0],
          [-1, 0, 1],
          [0, -1, 1],
        ];

        // Collect all forbidden hexes (adjacent to any enemy + wall hexes) using cube coordinates
        const forbiddenSet = new Set<string>();

        // Add all wall hexes as forbidden
        const wallHexSet = new Set<string>(
          effectiveWallHexes.map((wall: number[]) => `${wall[0]},${wall[1]}`)
        );
        wallHexSet.forEach((wallHex) => {
          forbiddenSet.add(wallHex);
        });

        for (const enemy of aliveUnits) {
          if (enemy.player === selectedUnit.player) continue;

          // Add enemy position itself
          forbiddenSet.add(`${enemy.col},${enemy.row}`);

          // Use cube coordinates for proper hex adjacency
          const enemyCube = offsetToCube(enemy.col, enemy.row);
          for (const [dx, dy, dz] of cubeDirections) {
            const adjCube = {
              x: enemyCube.x + dx,
              y: enemyCube.y + dy,
              z: enemyCube.z + dz,
            };

            // Convert back to offset coordinates
            const adjCol = adjCube.x;
            const adjRow = adjCube.z + ((adjCube.x - (adjCube.x & 1)) >> 1);

            if (adjCol >= 0 && adjCol < BOARD_COLS && adjRow >= 0 && adjRow < BOARD_ROWS) {
              forbiddenSet.add(`${adjCol},${adjRow}`);
            }
          }
        }

        if (hasFlyKeyword) {
          // FLY: ignore walls/occupancy/enemy-adjacency during traversal.
          // Only destination legality applies (same restriction as engine-side destination checks).
          for (let col = 0; col < BOARD_COLS; col++) {
            for (let row = 0; row < BOARD_ROWS; row++) {
              const key = `${col},${row}`;
              if (col === centerCol && row === centerRow) {
                continue;
              }
              if (cubeDistance(offsetToCube(centerCol, centerRow), offsetToCube(col, row)) > selectedUnit.MOVE) {
                continue;
              }
              const blocked = aliveUnits.some(
                (u) => u.col === col && u.row === row && u.id !== selectedUnit.id
              );
              if (!blocked && !forbiddenSet.has(key)) {
                availableCells.push({ col, row });
              }
            }
          }
        } else {
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

            const blocked = aliveUnits.some(
              (u) => u.col === col && u.row === row && u.id !== selectedUnit.id
            );

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
                z: currentCube.z + dz,
              };

              // Convert back to offset coordinates
              const ncol = neighborCube.x;
              const nrow = neighborCube.z + ((neighborCube.x - (neighborCube.x & 1)) >> 1);

              const nkey = `${ncol},${nrow}`;
              const nextSteps = steps + 1;

              if (
                ncol >= 0 &&
                ncol < BOARD_COLS &&
                nrow >= 0 &&
                nrow < BOARD_ROWS &&
                nextSteps <= selectedUnit.MOVE &&
                !forbiddenSet.has(nkey)
              ) {
                const nblocked = aliveUnits.some(
                  (u) => u.col === ncol && u.row === nrow && u.id !== selectedUnit.id
                );

                if (!nblocked && (!visited.has(nkey) || visited.get(nkey)! > nextSteps)) {
                  queue.push([ncol, nrow, nextSteps]);
                }
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
      eligibleUnitIds.forEach((unitId) => {
        const eligibleUnit = units.find((u) => u.id === unitId);
        // Don't add green highlight for selected unit - it will show orange charge destinations instead
        // CRITICAL: Also check that unit belongs to current player to avoid highlighting enemy units
        if (
          eligibleUnit &&
          eligibleUnit.id !== selectedUnitId &&
          eligibleUnit.player === current_player
        ) {
          availableCells.push({ col: eligibleUnit.col, row: eligibleUnit.row });
        }
      });
    }

    // Attack cells: Different colors for different line of sight conditions
    const attackCells: { col: number; row: number }[] = []; // Blue preview cells
    const coverCells: { col: number; row: number }[] = []; // Orange = targets in cover
    const losVisibilityRatioByHex: Map<string, number> = new Map();
    const blockedTargets: Set<string> = new Set(); // Track targets with no line of sight (no hex shown)
    const coverTargets: Set<string> = new Set(); // Track targets in cover
    let backendShootableEnemyIds: Set<string> | null = null;
    if (phase === "shoot" && selectedUnit) {
      // Single source of truth for ghosting: live backend blinking payload only.
      if (stableBlinkingUnits && stableBlinkingUnits.length > 0) {
        backendShootableEnemyIds = new Set(stableBlinkingUnits.map((id) => String(id)));
      }
    }
    const shootPreviewBackendIds = backendShootableEnemyIds;

    const resolveShootingPreviewSource = (): { unit: Unit; fromCol: number; fromRow: number } | null => {
      if (mode === "advancePreview") {
        return null;
      }

      if (mode === "movePreview" && movePreview) {
        const movePreviewUnit = units.find((u) => u.id === movePreview.unitId);
        if (!movePreviewUnit) {
          return null;
        }
        return {
          unit: movePreviewUnit,
          fromCol: movePreview.destCol,
          fromRow: movePreview.destRow,
        };
      }

      if (phase === "shoot" && mode === "attackPreview" && attackPreview) {
        const attackPreviewUnit = units.find((u) => u.id === attackPreview.unitId);
        if (!attackPreviewUnit || attackPreviewUnit.id !== selectedUnitId) {
          return null;
        }
        return {
          unit: attackPreviewUnit,
          fromCol: attackPreviewUnit.col,
          fromRow: attackPreviewUnit.row,
        };
      }

      if (phase === "shoot" && selectedUnit?.SHOOT_LEFT !== undefined && selectedUnit.SHOOT_LEFT > 0) {
        return {
          unit: selectedUnit,
          fromCol: selectedUnit.col,
          fromRow: selectedUnit.row,
        };
      }

      return null;
    };

    const appendShootingPreviewCells = (source: { unit: Unit; fromCol: number; fromRow: number }) => {
      if (!source.unit.RNG_WEAPONS || source.unit.RNG_WEAPONS.length === 0) {
        return;
      }

      const attackCellSet = new Set<string>();
      const backendRatioByHex = source.unit.los_preview_ratio_by_hex;
      const backendAttackCells = source.unit.los_preview_attack_cells;
      const backendCoverCells = source.unit.los_preview_cover_cells;
      const useBackendLosPreview = false;

      if (useBackendLosPreview) {
        for (const [hexKey, ratio] of Object.entries(backendRatioByHex)) {
          if (typeof ratio !== "number" || Number.isNaN(ratio)) {
            throw new Error(`Invalid los_preview_ratio_by_hex value for key '${hexKey}'`);
          }
          losVisibilityRatioByHex.set(hexKey, ratio);
        }
        for (const cell of backendAttackCells) {
          const key = `${cell.col},${cell.row}`;
          if (!attackCellSet.has(key)) {
            attackCellSet.add(key);
            attackCells.push({ col: cell.col, row: cell.row });
          }
        }
        for (const cell of backendCoverCells) {
          coverCells.push({ col: cell.col, row: cell.row });
        }
        return;
      }

      const wallHexSet = new Set<string>(effectiveWallHexes.map((wall: number[]) => `${wall[0]},${wall[1]}`));
      const centerCube = offsetToCube(source.fromCol, source.fromRow);
      const range = getMaxRangedRange(source.unit);
      if (range <= 0) {
        return;
      }

      const enemyById = new Map<string, Unit>();
      for (const enemy of units) {
        if (enemy.player !== source.unit.player) {
          enemyById.set(String(enemy.id), enemy);
        }
      }

      if (shootPreviewBackendIds) {
        for (const enemyId of shootPreviewBackendIds) {
          const enemy = enemyById.get(String(enemyId));
          if (!enemy) {
            continue;
          }

          const enemyKey = `${enemy.col},${enemy.row}`;
          if (!attackCellSet.has(enemyKey)) {
            attackCellSet.add(enemyKey);
            attackCells.push({ col: enemy.col, row: enemy.row });
          }

          const pathHexes: Position[] = getHexLine(source.fromCol, source.fromRow, enemy.col, enemy.row);
          for (const hex of pathHexes) {
            const isSourceHex = hex.col === source.fromCol && hex.row === source.fromRow;
            if (isSourceHex) {
              continue;
            }
            const hexKey = `${hex.col},${hex.row}`;
            if (wallHexSet.has(hexKey)) {
              continue;
            }
            if (!attackCellSet.has(hexKey)) {
              attackCellSet.add(hexKey);
              attackCells.push({ col: hex.col, row: hex.row });
            }
          }
        }
      }

      // Show all hexes that are geometrically visible from current shooter preview position.
      for (let col = 0; col < BOARD_COLS; col++) {
        for (let row = 0; row < BOARD_ROWS; row++) {
          const targetCube = offsetToCube(col, row);
          const dist = cubeDistance(centerCube, targetCube);
          if (dist <= 0 || dist > range) {
            continue;
          }
          const lineOfSight = hasLineOfSight(
            { col: source.fromCol, row: source.fromRow },
            { col, row },
            effectiveWallHexes,
            coverRatio,
            losVisibilityMinRatio
          );
          const hexKey = `${col},${row}`;
          losVisibilityRatioByHex.set(hexKey, lineOfSight.visibilityRatio);
          if (!lineOfSight.canSee) {
            continue;
          }
          if (lineOfSight.inCover) {
            coverCells.push({ col, row });
            continue;
          }
          if (!attackCellSet.has(hexKey)) {
            attackCellSet.add(hexKey);
            attackCells.push({ col, row });
          }
        }
      }
    };

    const shootingPreviewSource = resolveShootingPreviewSource();
    if (shootingPreviewSource) {
      appendShootingPreviewCells(shootingPreviewSource);
    }
    const coverCellKeySet = new Set(coverCells.map((cell) => `${cell.col},${cell.row}`));
    if (phase === "fight" && mode === "attackPreview" && selectedUnit) {
      attackCells.push(...fightPreviewCells);
    }

    // Unified: movePreview and shoot phase use same backend source of truth (blinking_units)
    const effectiveBlinkingUnits = stableBlinkingUnits ?? [];
    const effectiveBlinkingAttackerId = blinkingAttackerId;
    const effectiveShootTargetsSet: Set<string> | null =
      effectiveBlinkingUnits.length > 0
        ? new Set(effectiveBlinkingUnits.map(String))
        : shootPreviewBackendIds;

    // Populate blockedTargets from unified source (enemies NOT in effective targets)
    if (effectiveShootTargetsSet && shootingPreviewSource) {
      const enemyUnits = units.filter((u) => u.player !== shootingPreviewSource.unit.player);
      for (const enemy of enemyUnits) {
        if (!effectiveShootTargetsSet.has(String(enemy.id))) {
          blockedTargets.add(`${enemy.col},${enemy.row}`);
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

    // Type assertion for boardConfig to match UnitRenderer's expected type
    const boardConfigForRender = boardConfig as unknown as Record<string, unknown> | null;

    interface BoardConfigForDrawBoard {
      cols: number;
      rows: number;
      hex_radius: number;
      margin: number;
      colors: {
        background: string;
        cell_even: string;
        cell_odd: string;
        cell_border: string;
        highlight: string;
        attack: string;
        charge: string;
        eligible: string;
        objective: string;
        objective_zone: string;
        wall: string;
        player_1: string;
        player_2: string;
        hp_full: string;
        hp_damaged: string;
        [key: string]: string;
      };
      display: {
        icon_scale: number;
        eligible_outline_width: number;
        eligible_outline_alpha: number;
        hp_bar_width_ratio: number;
        hp_bar_height: number;
        hp_bar_y_offset_ratio: number;
        unit_circle_radius_ratio: number;
        unit_text_size: number;
        selected_border_width: number;
        charge_target_border_width: number;
        default_border_width: number;
        canvas_border: string;
        antialias: boolean;
        autoDensity: boolean;
        resolution: number | "auto";
      };
      objective_hexes: [number, number][];
      wall_hexes: [number, number][];
      walls?: Array<{
        start: { col: number; row: number };
        end: { col: number; row: number };
        thickness?: number;
      }>;
    }
    const boardConfigWithOverrides: BoardConfigForDrawBoard = {
      ...boardConfig,
      colors: {
        ...boardConfig.colors,
        attack: boardConfig.colors.attack || "#FF0000", // Ensure attack is defined
      },
      wall_hexes: wallHexesOverride ? effectiveWallHexes : boardConfig.wall_hexes || [],
      objective_hexes: effectiveObjectiveHexes,
    } as BoardConfigForDrawBoard;
    // Override availableCells if availableCellsOverride is provided (for replay mode)
    const effectiveAvailableCells = availableCellsOverride || availableCells;

    // Detect episode reset: if turn goes back to 1 (or decreases), reset objective controllers
    const currentTurn = gameState?.turn ?? gameState?.currentTurn ?? 1;
    if (lastTurnRef.current !== null && currentTurn < lastTurnRef.current) {
      // New episode started - reset persistent objective control
      objectiveControllersRef.current = {};
    }
    lastTurnRef.current = currentTurn;

    if (replayActionIndex !== undefined) {
      if (
        lastReplayActionIndexRef.current !== null &&
        replayActionIndex < lastReplayActionIndexRef.current
      ) {
        objectiveControllersRef.current = {};
      }
      lastReplayActionIndexRef.current = replayActionIndex;
    }

    const replayRules = (gameState as { rules?: ReplayRules } | null)?.rules;
    let tieBehavior: string | undefined;
    let controlMethod: string | undefined;
    let objectiveControlStartTurn: number | undefined;
    if (replayActionIndex !== undefined && !replayRules) {
      throw new Error("Replay rules missing: objective control cannot be computed");
    }
    if (replayActionIndex !== undefined && replayRules) {
      const primaryObjective = replayRules.primary_objective;
      const primaryObjectiveConfig = Array.isArray(primaryObjective)
        ? (() => {
            if (primaryObjective.length !== 1) {
              throw new Error("Replay rules primary_objective must contain exactly one config");
            }
            return primaryObjective[0];
          })()
        : primaryObjective;
      if (!primaryObjectiveConfig) {
        throw new Error("Replay rules primary_objective is null");
      }
      if (
        !primaryObjectiveConfig.scoring ||
        primaryObjectiveConfig.scoring.start_turn === undefined ||
        primaryObjectiveConfig.scoring.start_turn === null
      ) {
        throw new Error("Replay rules primary_objective.scoring.start_turn is missing");
      }
      if (
        !primaryObjectiveConfig.control ||
        !primaryObjectiveConfig.control.method ||
        !primaryObjectiveConfig.control.tie_behavior
      ) {
        throw new Error("Replay rules primary_objective.control is missing required fields");
      }
      if (!primaryObjectiveConfig.control.control_method) {
        throw new Error("Replay rules primary_objective.control.control_method is missing");
      }
      if (
        !primaryObjectiveConfig.timing ||
        !primaryObjectiveConfig.timing.default_phase ||
        !primaryObjectiveConfig.timing.round5_second_player_phase
      ) {
        throw new Error("Replay rules primary_objective.timing is missing required fields");
      }
      if (primaryObjectiveConfig.control.method !== "oc_sum_greater") {
        throw new Error(
          `Unsupported objective control method: ${primaryObjectiveConfig.control.method}`
        );
      }
      if (!["sticky", "occupy"].includes(primaryObjectiveConfig.control.control_method)) {
        throw new Error(
          `Unsupported control_method: ${primaryObjectiveConfig.control.control_method}`
        );
      }
      if (primaryObjectiveConfig.control.tie_behavior !== "no_control") {
        throw new Error(
          `Unsupported objective tie behavior: ${primaryObjectiveConfig.control.tie_behavior}`
        );
      }
      tieBehavior = primaryObjectiveConfig.control.tie_behavior;
      controlMethod = primaryObjectiveConfig.control.control_method;
      objectiveControlStartTurn = primaryObjectiveConfig.scoring.start_turn;
    }
    if (replayActionIndex === undefined) {
      const livePrimaryObjective = gameState?.primary_objective as
        | PrimaryObjectiveRule
        | PrimaryObjectiveRule[]
        | null;
      if (!livePrimaryObjective) {
        throw new Error("primary_objective missing from game_state");
      }
      const primaryObjectiveConfig: PrimaryObjectiveRule = Array.isArray(livePrimaryObjective)
        ? (() => {
            if (livePrimaryObjective.length !== 1) {
              throw new Error("primary_objective must contain exactly one config");
            }
            return livePrimaryObjective[0];
          })()
        : livePrimaryObjective;
      if (!primaryObjectiveConfig) {
        throw new Error("primary_objective is null");
      }
      if (
        !primaryObjectiveConfig.scoring ||
        primaryObjectiveConfig.scoring.start_turn === undefined ||
        primaryObjectiveConfig.scoring.start_turn === null
      ) {
        throw new Error("primary_objective.scoring.start_turn is missing");
      }
      if (
        !primaryObjectiveConfig.control ||
        !primaryObjectiveConfig.control.method ||
        !primaryObjectiveConfig.control.tie_behavior
      ) {
        throw new Error("primary_objective.control is missing required fields");
      }
      if (!primaryObjectiveConfig.control.control_method) {
        throw new Error("primary_objective.control.control_method is missing");
      }
      if (
        !primaryObjectiveConfig.timing ||
        !primaryObjectiveConfig.timing.default_phase ||
        !primaryObjectiveConfig.timing.round5_second_player_phase
      ) {
        throw new Error("primary_objective.timing is missing required fields");
      }
      if (primaryObjectiveConfig.control.method !== "oc_sum_greater") {
        throw new Error(
          `Unsupported objective control method: ${primaryObjectiveConfig.control.method}`
        );
      }
      if (!["sticky", "occupy"].includes(primaryObjectiveConfig.control.control_method)) {
        throw new Error(
          `Unsupported control_method: ${primaryObjectiveConfig.control.control_method}`
        );
      }
      if (primaryObjectiveConfig.control.tie_behavior !== "no_control") {
        throw new Error(
          `Unsupported objective tie behavior: ${primaryObjectiveConfig.control.tie_behavior}`
        );
      }
      tieBehavior = primaryObjectiveConfig.control.tie_behavior;
      controlMethod = primaryObjectiveConfig.control.control_method;
      objectiveControlStartTurn = primaryObjectiveConfig.scoring.start_turn;
    }
    if (objectiveControlStartTurn === undefined || objectiveControlStartTurn === null) {
      throw new Error("objective control start_turn is missing");
    }
    let objectiveControl: { [hexKey: string]: number | null } = {};
    if (currentTurn >= objectiveControlStartTurn) {
      const { controlMap, updatedControllers } = calculateObjectiveControl(
        units,
        objectivesOverride,
        effectiveObjectiveHexes,
        objectiveControllersRef.current,
        true,
        tieBehavior,
        controlMethod
      );
      objectiveControl = controlMap;
      // Update persistent state only when objective control is active.
      objectiveControllersRef.current = updatedControllers;
    } else if (objectivesOverride && objectivesOverride.length > 0) {
      for (const obj of objectivesOverride) {
        for (const hex of obj.hexes) {
          objectiveControl[`${hex.col},${hex.row}`] = null;
        }
      }
    } else {
      for (const [col, row] of effectiveObjectiveHexes) {
        objectiveControl[`${col},${row}`] = null;
      }
    }

    // Map unsupported phases for drawBoard/UnitRenderer to closest supported behavior.
    const effectivePhase = phase === "command" || phase === "deployment" ? "move" : phase;

    if (app.stage) {
      app.stage.removeChildren();
      if (uiElementsContainerRef.current) {
        app.stage.addChild(uiElementsContainerRef.current);
        // Replay/PvP: clear stale transient UI markers before rendering current frame.
        // This removes markers for units no longer present (e.g. dead targets).
        const staleTargetMarkers = uiElementsContainerRef.current.children.filter(
          (child: PIXI.DisplayObject) =>
            typeof child.name === "string" &&
            (child.name.startsWith("target-indicator-") || child.name.startsWith("charge-badge-"))
        );
        staleTargetMarkers.forEach((child: PIXI.DisplayObject) => {
          uiElementsContainerRef.current?.removeChild(child);
          if ("destroy" in child && typeof child.destroy === "function") {
            child.destroy();
          }
        });
      }
    }
    drawBoard(app, boardConfigWithOverrides as Parameters<typeof drawBoard>[1], {
      availableCells: effectiveAvailableCells,
      attackCells,
      coverCells,
      chargeCells,
      advanceCells:
        mode === "advancePreview" &&
        selectedUnitId &&
        getAdvanceDestinations &&
        !availableCellsOverride
          ? getAdvanceDestinations(selectedUnitId)
          : [], // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Populated when in advancePreview mode, but skip if availableCellsOverride is provided
      blockedTargets,
      coverTargets,
      phase: effectivePhase,
      interactionPhase: phase,
      selectedUnitId,
      mode,
      showHexCoordinates,
      objectiveControl,
      losDebugShowRatio: showLosDebugOverlay && phase === "shoot" && shootingPreviewSource !== null,
      losDebugRatioByHex: Object.fromEntries(losVisibilityRatioByHex),
      losDebugCoverRatio: coverRatio,
      losDebugVisibilityMinRatio: losVisibilityMinRatio,
    });

    // ✅ SETUP BOARD INTERACTIONS using shared BoardInteractions component
    // setupBoardInteractions is now a stub - no longer needed

    // ✅ UNIFIED UNIT RENDERING USING COMPONENT
    for (const unit of units) {
      const unitsCache = gameState?.units_cache;
      const unitIdStr = String(unit.id);
      const isPresentInUnitsCache =
        unitsCache !== undefined ? Object.hasOwn(unitsCache, unitIdStr) : true;
      const isHazardousDeathGhost =
        phase === "shoot" &&
        selectedUnitId === unit.id &&
        unitsCache !== undefined &&
        !isPresentInUnitsCache;

      // units_cache is the single source of truth for living units.
      // Keep only the hazardous-death ghost visible during the current shooting activation.
      if (!isPresentInUnitsCache && !isHazardousDeathGhost) {
        continue;
      }

      const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const centerY =
        unit.row * HEX_VERT_SPACING +
        ((unit.col % 2) * HEX_VERT_SPACING) / 2 +
        HEX_HEIGHT / 2 +
        MARGIN;

      // Skip units that are being previewed elsewhere
      if (mode === "advancePreview" && movePreview && unit.id === movePreview.unitId) continue;
      if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) continue;

      // Unified: movePreview and shoot phase use same code path for greying non-targetable enemies
      const hasAuthoritativeShootTargets =
        effectiveShootTargetsSet !== null &&
        effectiveShootTargetsSet.size > 0 &&
        ((phase === "shoot" && selectedUnitId !== null) ||
          (mode === "movePreview" && movePreview !== null));

      let isShootable = true;
      if (hasAuthoritativeShootTargets && unit.player !== current_player) {
        isShootable = effectiveShootTargetsSet.has(String(unit.id));
      }

      // Debug only for key units - EXACT UnitRenderer.tsx logic check
      if (unit.id === 8 || unit.id === 9) {
        // Debug code removed - variables were not used
      }
      // Calculate queue-based eligibility during shooting phase
      const isEligibleForRendering = (() => {
        if (phase === "shoot" && shootingActivationQueue && shootingActivationQueue.length > 0) {
          // During active shooting: unit is eligible if in queue OR is active unit
          const inQueue = shootingActivationQueue.some(
            (u: Unit) => String(u.id) === String(unit.id)
          );
          const isActive = activeShootingUnit && String(activeShootingUnit.id) === String(unit.id);
          const result = inQueue || isActive;

          if (unit.id === 8 || unit.id === 9) {
            // Debug key units
            console.log(
              `🟢 ELIGIBILITY DEBUG Unit ${unit.id}: inQueue=${inQueue}, isActive=${isActive}, result=${result}`
            );
            console.log(
              `🟢 Queue IDs:`,
              shootingActivationQueue.map((u) => u.id)
            );
            console.log(`🟢 Active unit:`, activeShootingUnit?.id || "none");
          }

          return result;
        }
        if (phase === "fight") {
          if (!gameState) {
            throw new Error("Missing gameState during fight eligibility calculation");
          }
          const currentFightSubPhase = gameState.fight_subphase;
          if (!currentFightSubPhase) {
            throw new Error("Missing fight_subphase during fight eligibility calculation");
          }
          let fightPool: Array<number | string> | undefined;
          if (currentFightSubPhase === "charging") {
            fightPool = gameState.charging_activation_pool;
          } else if (
            currentFightSubPhase === "alternating_non_active" ||
            currentFightSubPhase === "cleanup_non_active"
          ) {
            fightPool = gameState.non_active_alternating_activation_pool;
          } else if (currentFightSubPhase === "alternating_active" || currentFightSubPhase === "cleanup_active") {
            fightPool = gameState.active_alternating_activation_pool;
          } else {
            throw new Error(`Unknown fight_subphase: ${currentFightSubPhase}`);
          }
          if (!fightPool) {
            throw new Error(`Missing fight activation pool for subphase: ${currentFightSubPhase}`);
          }
          return fightPool.some((id) => String(id) === String(unit.id));
        }
        // All other phases: use standard eligibility
        return eligibleUnitIds.includes(
          typeof unit.id === "number" ? unit.id : parseInt(unit.id as string, 10)
        );
      })();

      // During charge phase, show selected unit as ghost (darkened) at origin
      // This indicates the unit is about to move, similar to movement preview
      // In replay mode, a separate ghost unit is added, so we check if one already exists
      interface UnitWithGhost extends Unit {
        isGhost?: boolean;
      }
      const hasExistingGhost = units.some((u: UnitWithGhost) => u.isGhost && u.id < 0);
      const isChargeOrigin =
        phase === "charge" &&
        mode === "select" &&
        unit.id === selectedUnitId &&
        chargeCells.length > 0 &&
        !hasExistingGhost; // Don't ghost the real unit if replay mode already added a ghost
      const isMoveOriginGhost =
        mode === "movePreview" &&
        (phase === "move" || phase === "shoot") &&
        movePreview !== null &&
        unit.id === movePreview.unitId;

      const isShootingPreviewGhost =
        (phase === "shoot" || mode === "movePreview") &&
        hasAuthoritativeShootTargets &&
        unit.player !== current_player &&
        effectiveShootTargetsSet !== null &&
        !effectiveShootTargetsSet.has(String(unit.id));

      const unitToRender =
        isChargeOrigin || isMoveOriginGhost || isHazardousDeathGhost || isShootingPreviewGhost
          ? ({ ...unit, isGhost: true } as Unit & { isGhost: boolean })
          : unit;

      renderUnit({
        unit: unitToRender,
        centerX,
        centerY,
        app,
        uiElementsContainer: uiElementsContainerRef.current!, // Pass persistent UI container
        useOverlayIcons: true,
        isPreview: false,
        isEligible: isMoveOriginGhost ? false : (isEligibleForRendering || false),
        isShootable,
        boardConfig: boardConfigForRender,
        HEX_RADIUS,
        ICON_SCALE,
        ELIGIBLE_OUTLINE_WIDTH,
        ELIGIBLE_COLOR,
        ELIGIBLE_OUTLINE_ALPHA,
        HP_BAR_WIDTH_RATIO,
        HP_BAR_HEIGHT,
        UNIT_CIRCLE_RADIUS_RATIO,
        UNIT_TEXT_SIZE,
        SELECTED_BORDER_WIDTH,
        CHARGE_TARGET_BORDER_WIDTH,
        DEFAULT_BORDER_WIDTH,
        phase: effectivePhase,
        mode,
        current_player,
        selectedUnitId,
        ruleChoiceHighlightedUnitId,
        unitsMoved,
        unitsCharged,
        unitsAttacked,
        unitsFled,
        fightSubPhase,
        fightActivePlayer,
        gameState,
        units,
        chargeTargets,
        fightTargets,
        targetPreview,
        onConfirmMove,
        parseColor,
        // Pass blinking state (unified: movePreview and attackPreview use same code path)
        blinkingUnits: effectiveBlinkingUnits,
        blinkingAttackerId: effectiveBlinkingAttackerId,
        isBlinkingActive,
        blinkVersion,
        shootingTargetInCover: coverCellKeySet.has(`${unit.col},${unit.row}`),
        // Pass shooting indicators
        shootingTargetId,
        shootingUnitId,
        // Pass movement indicator
        movingUnitId,
        autoSelectWeapon,
        // Pass charge indicators
        chargingUnitId,
        // Calculate chargeTargetId: prioritize props (for failed/successful charges) over chargeTargets (for preview)
        // CRITICAL: chargeTargetId from props takes precedence as it comes from actual charge result
        chargeTargetId: (() => {
          const finalTargetId =
            chargeTargetId ?? (chargeTargets.length > 0 ? chargeTargets[0].id : null);
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
        // Check if unit can advance: eligible, not fled, and hasn't already advanced this turn
        canAdvance: (() => {
          // AI_TURN.md STEP 1: ELIGIBILITY CHECK (lignes 583-599)
          // CAN_ADVANCE = true if unit is NOT adjacent to enemy AND not already advanced
          if (phase !== "shoot") return false;
          if (unit.player !== current_player) return false;
          if (unitsFled?.includes(unit.id)) return false;

          // Check if unit has already advanced (AI_TURN.md ligne 671: After advance, CAN_ADVANCE = false)
          const unitsAdvanced = gameState?.unitsAdvanced || [];
          if (unitsAdvanced.includes(unit.id)) return false;

          // AI_TURN.md ligne 583-590: Check if unit is adjacent to enemy (melee range)
          // CAN_ADVANCE = false if adjacent to enemy (AI_TURN.md ligne 585)
          const isAdjacentToEnemy = units.some(
            (enemy: Unit) =>
              enemy.player !== unit.player && enemy.HP_CUR > 0 && areUnitsAdjacent(unit, enemy)
          );
          if (isAdjacentToEnemy) return false;

          // AI_TURN.md ligne 591: NOT adjacent to enemy -> CAN_ADVANCE = true
          return true;
        })(),
        onAdvance: onAdvance,
        onUnitTooltip: setUnitHoverTooltip,
        debugMode: showHexCoordinates,
      });
    }

    // ✅ MOVE PREVIEW RENDERING
    if (mode === "movePreview" && movePreview) {
      const previewUnit = units.find((u) => u.id === movePreview.unitId);
      if (previewUnit) {
        const centerX = movePreview.destCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY =
          movePreview.destRow * HEX_VERT_SPACING +
          ((movePreview.destCol % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN;

        renderUnit({
          unit: previewUnit,
          centerX,
          centerY,
          app,
          useOverlayIcons: true,
          isPreview: true,
          previewType: "move",
          isEligible: false, // Preview units are not eligible
          boardConfig: boardConfigForRender,
          HEX_RADIUS,
          ICON_SCALE,
          ELIGIBLE_OUTLINE_WIDTH,
          ELIGIBLE_COLOR,
          ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO,
          HP_BAR_HEIGHT,
          UNIT_CIRCLE_RADIUS_RATIO,
          UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH,
          CHARGE_TARGET_BORDER_WIDTH,
          DEFAULT_BORDER_WIDTH,
          phase: effectivePhase,
          mode,
          current_player,
          selectedUnitId,
          unitsMoved,
          unitsCharged,
          unitsAttacked,
          unitsFled,
          fightSubPhase,
          fightActivePlayer,
          units,
          chargeTargets,
          fightTargets,
          targetPreview,
          onConfirmMove,
          parseColor,
          autoSelectWeapon,
          onUnitTooltip: setUnitHoverTooltip,
          debugMode: showHexCoordinates,
        });
      }
    }

    // ✅ ADVANCE PREVIEW RENDERING (same as movePreview)
    if (mode === "advancePreview" && movePreview) {
      const previewUnit = units.find((u) => u.id === movePreview.unitId);
      if (previewUnit) {
        const centerX = movePreview.destCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY =
          movePreview.destRow * HEX_VERT_SPACING +
          ((movePreview.destCol % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN;

        renderUnit({
          unit: previewUnit,
          centerX,
          centerY,
          app,
          useOverlayIcons: true,
          isPreview: true,
          previewType: "move",
          isEligible: false, // Preview units are not eligible
          boardConfig: boardConfigForRender,
          HEX_RADIUS,
          ICON_SCALE,
          ELIGIBLE_OUTLINE_WIDTH,
          ELIGIBLE_COLOR,
          ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO,
          HP_BAR_HEIGHT,
          UNIT_CIRCLE_RADIUS_RATIO,
          UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH,
          CHARGE_TARGET_BORDER_WIDTH,
          DEFAULT_BORDER_WIDTH,
          phase: effectivePhase,
          mode,
          current_player,
          selectedUnitId,
          unitsMoved,
          unitsCharged,
          unitsAttacked,
          unitsFled,
          fightSubPhase,
          fightActivePlayer,
          units,
          chargeTargets,
          fightTargets,
          targetPreview,
          onConfirmMove,
          parseColor,
          autoSelectWeapon,
          // Pass advance roll info for replay mode (use real unit ID, not ghost ID)
          advanceRoll,
          advancingUnitId: movePreview.unitId, // Use real unit ID for preview icon at destination
          onUnitTooltip: setUnitHoverTooltip,
          debugMode: showHexCoordinates,
        });
      }
    }

    // ✅ ATTACK PREVIEW RENDERING
    if (mode === "attackPreview" && attackPreview) {
      const previewUnit = units.find((u) => u.id === attackPreview.unitId);
      if (previewUnit) {
        const centerX = attackPreview.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY =
          attackPreview.row * HEX_VERT_SPACING +
          ((attackPreview.col % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN;

        renderUnit({
          unit: previewUnit,
          centerX,
          centerY,
          app,
          useOverlayIcons: true,
          isPreview: true,
          previewType: "attack",
          isEligible: false, // Preview units are not eligible
          boardConfig: boardConfigForRender,
          HEX_RADIUS,
          ICON_SCALE,
          ELIGIBLE_OUTLINE_WIDTH,
          ELIGIBLE_COLOR,
          ELIGIBLE_OUTLINE_ALPHA,
          HP_BAR_WIDTH_RATIO,
          HP_BAR_HEIGHT,
          UNIT_CIRCLE_RADIUS_RATIO,
          UNIT_TEXT_SIZE,
          SELECTED_BORDER_WIDTH,
          CHARGE_TARGET_BORDER_WIDTH,
          DEFAULT_BORDER_WIDTH,
          phase: effectivePhase,
          mode,
          current_player,
          selectedUnitId,
          unitsMoved,
          unitsCharged,
          unitsAttacked,
          unitsFled,
          fightSubPhase,
          fightActivePlayer,
          units,
          chargeTargets,
          fightTargets,
          targetPreview,
          onConfirmMove,
          parseColor,
          onUnitTooltip: setUnitHoverTooltip,
          autoSelectWeapon,
          debugMode: showHexCoordinates,
        });
      }
    }

    // ✅ CHARGE ROLL POPUP RENDERING
    if (chargeRollPopup) {
      const popupText = chargeRollPopup.tooLow
        ? `Roll : ${chargeRollPopup.roll} : No charge !`
        : `Roll : ${chargeRollPopup.roll} !`;

      const popupContainer = new PIXI.Container();
      popupContainer.name = "charge-roll-popup";
      popupContainer.zIndex = 10000; // Ensure popup is on top

      // Create popup background
      const popupBg = new PIXI.Graphics();
      popupBg.beginFill(0x000000, 0.9);
      popupBg.lineStyle(3, chargeRollPopup.tooLow ? 0xff0000 : 0x00ff00, 1.0);
      popupBg.drawRoundedRect(0, 0, 300, 80, 10);
      popupBg.endFill();

      // Create popup text
      const popupTextObj = new PIXI.Text(popupText, {
        fontSize: 26,
        fill: chargeRollPopup.tooLow ? 0xff4444 : 0x44ff44,
        fontWeight: "bold",
        align: "center",
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
    if (
      showAdvanceWarningPopup &&
      advanceWarningPopup &&
      onConfirmAdvanceWarning &&
      onCancelAdvanceWarning &&
      onSkipAdvanceWarning
    ) {
      const popupContainer = new PIXI.Container();
      popupContainer.name = "advance-warning-popup";
      popupContainer.zIndex = 10001; // Above charge roll popup

      const popupWidth = 450;
      const popupHeight = 200;

      // Create popup background
      const popupBg = new PIXI.Graphics();
      popupBg.beginFill(0x000000, 0.95);
      popupBg.lineStyle(3, 0xffaa00, 1.0); // Orange border for warning
      popupBg.drawRoundedRect(0, 0, popupWidth, popupHeight, 10);
      popupBg.endFill();

      // Create warning text
      const warningText = new PIXI.Text("WARNING !", {
        fontSize: 28,
        fill: 0xffaa00,
        fontWeight: "bold",
        align: "center",
      });
      warningText.anchor.set(0.5);
      warningText.position.set(popupWidth / 2, 35);

      // Create message text
      const messageText = new PIXI.Text(
        "Making an advance move won't allow you to shoot or charge in this turn.",
        {
          fontSize: 18,
          fill: 0xffffff,
          align: "center",
          wordWrap: true,
          wordWrapWidth: popupWidth - 40,
        }
      );
      messageText.anchor.set(0.5);
      messageText.position.set(popupWidth / 2, 85);

      // Create Confirm button
      const buttonWidth = 100;
      const buttonHeight = 36;
      const buttonSpacing = 25;
      const buttonY = popupHeight - 56;
      const confirmButtonX = 50;

      const confirmButtonBg = new PIXI.Graphics();
      confirmButtonBg.beginFill(0x00aa00, 0.9);
      confirmButtonBg.lineStyle(2, 0x00ff00, 1.0);
      confirmButtonBg.drawRoundedRect(0, 0, buttonWidth, buttonHeight, 5);
      confirmButtonBg.endFill();
      confirmButtonBg.position.set(confirmButtonX, buttonY);
      confirmButtonBg.eventMode = "static";
      confirmButtonBg.cursor = "pointer";
      confirmButtonBg.on("pointerdown", () => {
        onConfirmAdvanceWarning();
      });

      const confirmText = new PIXI.Text("Confirm", {
        fontSize: 18,
        fill: 0xffffff,
        fontWeight: "bold",
        align: "center",
      });
      confirmText.anchor.set(0.5);
      confirmText.position.set(confirmButtonX + buttonWidth / 2, buttonY + buttonHeight / 2);
      confirmText.eventMode = "static";
      confirmText.cursor = "pointer";
      confirmText.on("pointerdown", () => {
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
      skipButtonBg.eventMode = "static";
      skipButtonBg.cursor = "pointer";
      skipButtonBg.on("pointerdown", () => {
        onSkipAdvanceWarning();
      });

      const skipText = new PIXI.Text("Skip", {
        fontSize: 18,
        fill: 0xffffff,
        fontWeight: "bold",
        align: "center",
      });
      skipText.anchor.set(0.5);
      skipText.position.set(skipButtonX + buttonWidth / 2, buttonY + buttonHeight / 2);
      skipText.eventMode = "static";
      skipText.cursor = "pointer";
      skipText.on("pointerdown", () => {
        onSkipAdvanceWarning();
      });

      // Create Cancel button
      const cancelButtonX = skipButtonX + buttonWidth + buttonSpacing;
      const cancelButtonBg = new PIXI.Graphics();
      cancelButtonBg.beginFill(0xaa0000, 0.9);
      cancelButtonBg.lineStyle(2, 0xff0000, 1.0);
      cancelButtonBg.drawRoundedRect(0, 0, buttonWidth, buttonHeight, 5);
      cancelButtonBg.endFill();
      cancelButtonBg.position.set(cancelButtonX, buttonY);
      cancelButtonBg.eventMode = "static";
      cancelButtonBg.cursor = "pointer";
      cancelButtonBg.on("pointerdown", () => {
        onCancelAdvanceWarning();
      });

      const cancelText = new PIXI.Text("Cancel", {
        fontSize: 18,
        fill: 0xffffff,
        fontWeight: "bold",
        align: "center",
      });
      cancelText.anchor.set(0.5);
      cancelText.position.set(cancelButtonX + buttonWidth / 2, buttonY + buttonHeight / 2);
      cancelText.eventMode = "static";
      cancelText.cursor = "pointer";
      cancelText.on("pointerdown", () => {
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

    // Render overlay elements (icons + HP bars) above the canvas
    if (overlayRef.current) {
      const overlay = overlayRef.current;
      overlay.innerHTML = "";
      overlay.style.width = `${canvasWidth}px`;
      overlay.style.height = `${canvasHeight}px`;
      overlay.style.pointerEvents = "none";
      overlay.style.overflow = "visible";

      const getRequiredCssNumber = (variableName: string): number => {
        const value = getComputedStyle(document.documentElement)
          .getPropertyValue(variableName)
          .trim();
        if (value === "") {
          throw new Error(`CSS variable ${variableName} not found or empty`);
        }
        const parsed = parseFloat(value);
        if (Number.isNaN(parsed)) {
          throw new Error(`CSS variable ${variableName} is not a number: ${value}`);
        }
        return parsed;
      };

      const addOverlayIcon = (
        iconPath: string,
        positionX: number,
        positionY: number,
        iconSize: number,
        onClick: () => void,
        name: string
      ) => {
        const globalPos = app.stage.toGlobal(new PIXI.Point(positionX, positionY));
        const iconEl = document.createElement("img");
        iconEl.src = iconPath;
        iconEl.alt = name;
        iconEl.style.position = "absolute";
        iconEl.style.left = `${globalPos.x - iconSize / 2}px`;
        iconEl.style.top = `${globalPos.y - iconSize / 2}px`;
        iconEl.style.width = `${iconSize}px`;
        iconEl.style.height = `${iconSize}px`;
        iconEl.style.pointerEvents = "auto";
        iconEl.style.cursor = "pointer";
        iconEl.draggable = false;
        iconEl.addEventListener("pointerdown", (event) => {
          if (event.button === 0) {
            event.stopPropagation();
            onClick();
          }
        });
        overlay.appendChild(iconEl);
      };

      for (const unit of units) {
        if (
          gameState?.units_cache &&
          !Object.hasOwn(gameState.units_cache, String(unit.id))
        ) {
          continue;
        }

        const unitIdNum = typeof unit.id === "number" ? unit.id : parseInt(unit.id as string, 10);
        const overlayCol =
          mode === "movePreview" && movePreview && movePreview.unitId === unitIdNum
            ? movePreview.destCol
            : unit.col;
        const overlayRow =
          mode === "movePreview" && movePreview && movePreview.unitId === unitIdNum
            ? movePreview.destRow
            : unit.row;
        const centerX = overlayCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY =
          overlayRow * HEX_VERT_SPACING +
          ((overlayCol % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN;
        const unitIconScale = unit.ICON_SCALE || ICON_SCALE;
        const scaledYOffset = ((HEX_RADIUS * unitIconScale) / 2) * (0.9 + 0.3 / unitIconScale);
        const barY = centerY - scaledYOffset - HP_BAR_HEIGHT;

        // Icons: advance + weapon selection
        const isActiveShootingFromState =
          gameState?.active_shooting_unit &&
          parseInt(gameState.active_shooting_unit, 10) === unitIdNum;
        const isExplicitlyActivatedInUi =
          selectedUnitId === unitIdNum &&
          (mode === "attackPreview" ||
            mode === "advancePreview" ||
            mode === "movePreview" ||
            mode === "targetPreview");
        const shouldShowShootingActionIcons =
          phase === "shoot" &&
          unit.player === current_player &&
          isActiveShootingFromState &&
          isExplicitlyActivatedInUi;
        if (shouldShowShootingActionIcons) {
          const iconSize = getRequiredCssNumber("--icon-advance-size");
          const iconScale = getRequiredCssNumber("--icon-square-icon-scale");
          const iconDisplaySize = HEX_RADIUS * iconSize * iconScale;
          const squareSizeRatio = getRequiredCssNumber("--icon-square-standard-size");
          const squareSize = HEX_RADIUS * squareSizeRatio;
          const positionY = barY - squareSize / 2 - 5;

          const canAdvance = (() => {
            if (unitsFled?.includes(unitIdNum)) return false;
            const unitsAdvanced = gameState?.unitsAdvanced || [];
            if (unitsAdvanced.includes(unitIdNum)) return false;
            const isAdjacentToEnemy = units.some(
              (enemy: Unit) =>
                enemy.player !== unit.player && enemy.HP_CUR > 0 && areUnitsAdjacent(unit, enemy)
            );
            return !isAdjacentToEnemy;
          })();

          if (canAdvance && onAdvance && !hideAdvanceIconForTutorial) {
            addOverlayIcon(
              "/icons/Action_Logo/3-5 - Advance.png",
              centerX,
              positionY,
              iconDisplaySize,
              () => onAdvance(unitIdNum),
              `advance-${unitIdNum}`
            );
          }

          interface UnitWithAvailableWeapons extends Unit {
            available_weapons?: Array<{ can_use: boolean }>;
          }
          const unitWithWeapons = unit as UnitWithAvailableWeapons;
          const availableWeapons = unitWithWeapons.available_weapons;
          if (availableWeapons?.some((w) => w.can_use)) {
            const spacing = iconDisplaySize * 1.2;
            addOverlayIcon(
              "/icons/Action_Logo/3-1 - Gun_Choice.png",
              centerX + spacing,
              positionY,
              iconDisplaySize,
              () => {
                window.dispatchEvent(
                  new CustomEvent("boardWeaponSelectionClick", {
                    detail: { unitId: unitIdNum },
                  })
                );
              },
              `weapon-${unitIdNum}`
            );
          }
        }
      }
    }

    // Cleanup function
    return () => {
      // Cleanup board interactions
      // cleanupBoardInteractions is now a stub - no longer needed

      if (app.view?.removeEventListener) {
        app.view.removeEventListener("contextmenu", contextMenuHandler);
      }
    };
  }, [
    // Essential dependencies - all values used in the effect
    units.length,
    selectedUnitId,
    ruleChoiceHighlightedUnitId,
    mode,
    phase,
    boardConfig,
    gameConfig,
    gameConfig?.game_rules,
    loading,
    error,
    activeShootingUnit,
    advanceRoll,
    advanceWarningPopup,
    advancingUnitId,
    attackPreview,
    autoSelectWeapon,
    availableCellsOverride,
    isBlinkingActive,
    stableBlinkingUnits,
    blinkingAttackerId,
    chargeRoll,
    chargeRollPopup,
    chargeSuccess,
    chargeTargetId,
    chargingUnitId,
    current_player,
    eligibleUnitIds,
    fightActivePlayer,
    fightSubPhase,
    fightTargetId,
    fightingUnitId,
    gameState,
    getAdvanceDestinations,
    getChargeDestinations,
    movePreview,
    movingUnitId,
    objectivesOverride,
    onAdvance,
    onCancelAdvanceWarning,
    onCancelMove,
    onCancelTargetPreview,
    onConfirmAdvanceWarning,
    onConfirmMove,
    onDirectMove,
    onSkipAdvanceWarning,
    onStartMovePreview,
    shootingActivationQueue,
    showAdvanceWarningPopup,
    hideAdvanceIconForTutorial,
    showHexCoordinates,
    showLosDebugOverlay,
    shootingTargetId,
    shootingUnitId,
    targetPreview,
    units,
    unitsAttacked,
    unitsCharged,
    unitsFled,
    unitsMoved,
    wallHexesOverride,
    blinkVersion,
    deploymentState,
    replayActionIndex,
  ]);

  // Handle weapon selection
  const handleSelectWeapon = async (weaponIndex: number) => {
    if (!weaponSelectionMenu) return;

    const unit = units.find((u) => u.id === weaponSelectionMenu.unitId);
    const weapon = unit?.RNG_WEAPONS?.[weaponIndex];
    const weaponDisplayName = weapon?.display_name ?? undefined;

    // Close menu immediately (optimistic update)
    setWeaponSelectionMenu(null);

    try {
      const API_BASE = "/api";
      const response = await fetch(`${API_BASE}/game/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "select_weapon",
          unitId: weaponSelectionMenu.unitId.toString(),
          weaponIndex: weaponIndex,
          autoSelectWeapon: autoSelectWeapon,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success && data.game_state) {
          window.dispatchEvent(
            new CustomEvent("weaponSelected", {
              detail: { gameState: data.game_state, weaponDisplayName },
            })
          );
        }
      } else {
        console.error("Failed to select weapon: response not OK");
      }
    } catch (error) {
      console.error("🔴 WEAPON SELECT ERROR:", error);
    }
  };

  // Build weapon options
  const weaponOptions: WeaponOption[] = weaponSelectionMenu
    ? (() => {
        const unit = units.find((u) => u.id === weaponSelectionMenu.unitId);
        if (!unit || !unit.RNG_WEAPONS) return [];

        // Try to use available_weapons from unit if available
        interface UnitWithAvailableWeapons extends Unit {
          available_weapons?: Array<{
            index: number;
            weapon: Record<string, unknown>;
            can_use: boolean;
            reason?: string;
          }>;
        }
        const unitWithWeapons = unit as UnitWithAvailableWeapons;
        const availableWeapons = unitWithWeapons?.available_weapons;

        if (availableWeapons && Array.isArray(availableWeapons)) {
          // Use backend-filtered weapons
          return availableWeapons.map(
            (w: {
              index: number;
              weapon: Record<string, unknown>;
              can_use: boolean;
              reason?: string;
            }) => ({
              index: w.index,
              weapon: w.weapon as unknown as Weapon,
              canUse: w.can_use || false,
              reason: w.reason || undefined,
            })
          );
        }

        // Fallback: build from unit weapons (for backward compatibility)
        return unit.RNG_WEAPONS.map((weapon, index) => ({
          index,
          weapon,
          canUse: true, // All weapons can be used during selection
          reason: undefined,
        }));
      })()
    : [];

  // Simple container return - loading/error handled inside useEffect
  return (
    <div>
      <div
        style={{
          position: "relative",
          display: "inline-block",
          lineHeight: 0,
          overflow: "visible",
        }}
      >
        <div ref={canvasContainerRef} />
        <div
          ref={overlayRef}
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: "100%",
            height: "100%",
            pointerEvents: "none",
            overflow: "visible",
          }}
        />
        {unitHoverTooltip?.visible && (
          <div
            className="rule-tooltip unit-icon-tooltip"
            style={{
              position: "fixed",
              left: `${unitHoverTooltip.x}px`,
              top: `${unitHoverTooltip.y}px`,
              marginBottom: 0,
              zIndex: 1300,
              visibility: "visible",
              opacity: 1,
              transform: "translate(12px, -14px)",
              pointerEvents: "none",
            }}
          >
            {unitHoverTooltip.text}
          </div>
        )}
      </div>
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
      {weaponSelectionMenu && (
        <WeaponDropdown
          weapons={weaponOptions}
          position={weaponSelectionMenu.position}
          onSelectWeapon={handleSelectWeapon}
          onClose={() => setWeaponSelectionMenu(null)}
        />
      )}
    </div>
  );
}
