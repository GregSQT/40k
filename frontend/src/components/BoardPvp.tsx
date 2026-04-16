// frontend/src/components/BoardPvp.tsx

import * as PIXI from "pixi.js-legacy";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
  offsetToCube,
} from "../utils/gameHelpers";
import { getMaxRangedRange, getMeleeRange } from "../utils/weaponHelpers";
import { getPreferredRangedWeaponAgainstTarget } from "../utils/probabilityCalculator";
import { drawBoard } from "./BoardDisplay";
import { renderUnit } from "./UnitRenderer";
import {
  computeOccupiedHexes,
  pixelToHex,
  hexToPixel,
  isFootprintInBounds,
  isFootprintOnWall,
  isFootprintOverlapping,
  isFootprintInDeployPool,
  getContestedObjectives,
  buildOccupiedSet,
  type HexCoord,
} from "../utils/hexFootprint";
import { WeaponDropdown } from "./WeaponDropdown";
import { ensureWasmLoaded, isWasmReady, computeVisibleHexes } from "../utils/wasmLos";

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
  moveDestPoolRef?: React.RefObject<Set<string>>;
  footprintZoneRef?: React.RefObject<Set<string>>;
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

/** Hex distance between two offset-coordinate positions. */
function hexDistOff(c1: number, r1: number, c2: number, r2: number): number {
  const x1 = c1, z1 = r1 - ((c1 - (c1 & 1)) >> 1), y1 = -x1 - z1;
  const x2 = c2, z2 = r2 - ((c2 - (c2 & 1)) >> 1), y2 = -x2 - z2;
  return Math.max(Math.abs(x1 - x2), Math.abs(y1 - y2), Math.abs(z1 - z2));
}

/** Échelle affichage tooltip mouvement : nombre de pas hex entre centres pour 1″ (règle plateau). */
const HEX_STEPS_PER_INCH_DISPLAY = 10;

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
  moveDestPoolRef,
  footprintZoneRef,
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

  useEffect(() => {
    ensureWasmLoaded();
  }, []);

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

  // Persistent PIXI containers for static layers (survive re-renders)
  const staticBoardRef = useRef<PIXI.Container | null>(null);
  const staticWallsRef = useRef<PIXI.Container | null>(null);
  const staticBoardConfigKeyRef = useRef<string>("");
  const unitsLayerRef = useRef<PIXI.Container | null>(null);
  const unitsFingerprintRef = useRef<string>("");

  // Hover preview: imperative PIXI layers (no React re-render)
  const hoverOverlayRef = useRef<PIXI.Graphics | null>(null);
  const hoverCoverIconsRef = useRef<PIXI.Container | null>(null);
  const hoverSpriteRef = useRef<PIXI.Container | null>(null);
  /** Ligne départ → pointeur + libellé distance hex (preview move) */
  const movePreviewGuideLineRef = useRef<PIXI.Graphics | null>(null);
  const hoveredHexRef = useRef<{ col: number; row: number } | null>(null);
  const losHexRef = useRef<{ col: number; row: number } | null>(null);
  const losRequestIdRef = useRef(0);

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
  const [hexCoordTooltip, setHexCoordTooltip] = useState<{
    visible: boolean; x: number; y: number; col: number; row: number;
  } | null>(null);

  const handleCanvasMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!boardConfig || !showHexCoordinates) { setHexCoordTooltip(null); return; }
    const canvas = e.currentTarget.querySelector("canvas");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const HR = boardConfig.hex_radius;
    const M = boardConfig.margin;
    const HW = 1.5 * HR;
    const HH = Math.sqrt(3) * HR;
    const ux = px - M;
    const uy = py - M;
    const cols = boardConfig.cols;
    const rows = boardConfig.rows;
    const colApprox = (ux - HW / 2) / HW;
    const c0 = Math.max(0, Math.floor(colApprox) - 2);
    const c1 = Math.min(cols - 1, Math.ceil(colApprox) + 2);
    let bestCol = 0;
    let bestRow = 0;
    let bestD = Number.POSITIVE_INFINITY;
    for (let c = c0; c <= c1; c++) {
      const stagger = ((c % 2) * HH) / 2;
      const rowApprox = (uy - HH / 2 - stagger) / HH;
      const r0 = Math.max(0, Math.floor(rowApprox) - 2);
      const r1 = Math.min(rows - 1, Math.ceil(rowApprox) + 2);
      for (let r = r0; r <= r1; r++) {
        const cx = c * HW + HW / 2;
        const cy = r * HH + stagger + HH / 2;
        const d = (ux - cx) ** 2 + (uy - cy) ** 2;
        if (d < bestD) {
          bestD = d;
          bestCol = c;
          bestRow = r;
        }
      }
    }
    if (bestCol >= 0 && bestCol < cols && bestRow >= 0 && bestRow < rows) {
      setHexCoordTooltip({ visible: true, x: e.clientX, y: e.clientY, col: bestCol, row: bestRow });
    } else {
      setHexCoordTooltip(null);
    }
  }, [boardConfig, showHexCoordinates]);

  const [unitHoverTooltip, setUnitHoverTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);

  /** Tooltip distance prévisualisation mouvement (″) : même style que survol unité ; échelle hex → ″ via HEX_STEPS_PER_INCH_DISPLAY. */
  const [movePreviewDistanceTooltip, setMovePreviewDistanceTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);

  /** Normalise la fermeture : Pixi envoie visible:false mais on garde l’état en null pour le rendu. */
  const handleUnitTooltip = useCallback(
    (payload: { visible: boolean; text: string; x: number; y: number }) => {
      if (!payload.visible) {
        setUnitHoverTooltip(null);
      } else {
        setUnitHoverTooltip({
          visible: true,
          text: payload.text,
          x: payload.x,
          y: payload.y,
        });
      }
    },
    []
  );

  // Persistent container for drag placement overlay (deployment phase)
  const dragOverlayRef = useRef<PIXI.Container | null>(null);

  /**
   * Quand l’unité sous le curseur est retirée du plateau (mort → plus dans units_cache),
   * Pixi ne garantit pas un pointerout : le tooltip HTML restait affiché.
   * On aligne sur la même règle que la boucle de rendu (unités vivantes + ghost tir dangereux).
   */
  useEffect(() => {
    setUnitHoverTooltip((prev) => {
      if (prev == null || !prev.visible) return prev;
      const m = prev.text.match(/\bID\s+(\d+)/);
      if (!m) return prev;
      const idStr = m[1];
      const unit = units.find((u) => String(u.id) === idStr);
      if (!unit) return null;
      const unitsCache = gameState?.units_cache as Record<string, unknown> | undefined;
      const isPresentInUnitsCache =
        unitsCache !== undefined ? Object.hasOwn(unitsCache, idStr) : true;
      const isHazardousDeathGhost =
        phase === "shoot" &&
        selectedUnitId !== null &&
        String(selectedUnitId) === idStr &&
        unitsCache !== undefined &&
        !isPresentInUnitsCache;
      if (!isPresentInUnitsCache && !isHazardousDeathGhost) {
        return null;
      }
      return prev;
    });
  }, [units, gameState?.units_cache, phase, selectedUnitId]);

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
        tutorial.currentStep?.stage === "1-14") &&
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
    tutorial?.spotlightLayoutTick,
    boardConfig,
    units,
  ]);

  // Tutoriel 2-11/2-12 : halos sur les icônes Intercessor + Hormagaunts sur le board
  useLayoutEffect(() => {
    if (!tutorial?.setSpotlightBoardUnitPositions) return;
    const showBoardUnitSpotlights =
      tutorial.popupVisible &&
      (tutorial.currentStep?.stage === "2-11" || tutorial.currentStep?.stage === "2-12") &&
      boardConfig &&
      units.length > 0;
    if (!showBoardUnitSpotlights) {
      tutorial.setSpotlightBoardUnitPositions(null);
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
    const RADIUS = 72;
    const circles: Array<{ shape: "circle"; x: number; y: number; radius: number }> = [];
    for (const u of units) {
      if (u.col == null || u.row == null) continue;
      const centerX = u.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const centerY =
        u.row * HEX_VERT_SPACING +
        ((u.col % 2) * HEX_VERT_SPACING) / 2 +
        HEX_HEIGHT / 2 +
        MARGIN;
      circles.push({
        shape: "circle",
        x: rect.left + centerX,
        y: rect.top + centerY,
        radius: RADIUS,
      });
    }
    tutorial.setSpotlightBoardUnitPositions(circles.length ? circles : null);
  }, [
    tutorial?.popupVisible,
    tutorial?.currentStep?.stage,
    tutorial?.setSpotlightBoardUnitPositions,
    tutorial?.spotlightLayoutTick,
    boardConfig,
    units,
  ]);

  const stableBlinkingUnits = useMemo(() => {
    if (!blinkingUnits) return undefined;
    const sorted = blinkingUnits.length > 0 ? [...blinkingUnits].sort((a, b) => a - b) : [];
    return sorted;
  }, [blinkingUnits]);

  // Hover LoS preview: imperative PIXI update on boardHexHover
  useEffect(() => {
    if (!boardConfig || !gameConfig) return;

    const HEX_RADIUS_H = boardConfig.hex_radius;
    const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
    const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
    const MARGIN_H = boardConfig.margin;
    const BOARD_COLS_H = boardConfig.cols;
    const BOARD_ROWS_H = boardConfig.rows;
    const gameRules = gameConfig.game_rules;
    const losMin = gameRules?.los_visibility_min_ratio ?? 0;
    const coverR = gameRules?.cover_ratio ?? 0;
    const ATTACK_COLOR_H = parseInt((boardConfig.colors.attack || "0xe08080").replace("0x", ""), 16);
    const HP_BAR_H = boardConfig.display?.hp_bar_height ?? 7;

    const wallHexesH: [number, number][] = boardConfig.wall_hexes ? [...boardConfig.wall_hexes] : [];
    const bottomRowH = BOARD_ROWS_H - 1;
    const wallKeySetH = new Set(wallHexesH.map(([c, r]) => `${c},${r}`));
    for (let c = 0; c < BOARD_COLS_H; c++) {
      if (c % 2 === 1 && !wallKeySetH.has(`${c},${bottomRowH}`)) {
        wallHexesH.push([c, bottomRowH]);
      }
    }

    const hxX = (col: number) => col * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H;
    const hxY = (col: number, row: number) =>
      row * HEX_HEIGHT_H + ((col % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H;

    let spriteBuiltForUnitId: number | null = null;

    const hideMovePreviewGuides = () => {
      if (movePreviewGuideLineRef.current && !movePreviewGuideLineRef.current.destroyed) {
        movePreviewGuideLineRef.current.clear();
        movePreviewGuideLineRef.current.visible = false;
      }
      setMovePreviewDistanceTooltip(null);
    };

    // Pre-parse pixel positions for fast nearest-hex lookups
    let zonePixels: { x: number; y: number }[] | null = null;
    let destPixels: { x: number; y: number; col: number; row: number }[] | null = null;

    const buildZonePixels = () => {
      const pool = footprintZoneRef?.current ?? moveDestPoolRef?.current;
      if (!pool || pool.size === 0) { zonePixels = null; return; }
      zonePixels = [];
      for (const k of pool) {
        const sep = k.indexOf(",");
        const c = Number(k.substring(0, sep));
        const r = Number(k.substring(sep + 1));
        zonePixels.push({ x: hxX(c), y: hxY(c, r) });
      }
    };

    const buildDestPixels = () => {
      const pool = moveDestPoolRef?.current;
      if (!pool || pool.size === 0) { destPixels = null; return; }
      destPixels = [];
      for (const k of pool) {
        const sep = k.indexOf(",");
        const c = Number(k.substring(0, sep));
        const r = Number(k.substring(sep + 1));
        destPixels.push({ x: hxX(c), y: hxY(c, r), col: c, row: r });
      }
    };

    buildZonePixels();
    buildDestPixels();

    // DOM mousemove: icon follows cursor pixel-perfect
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    const onMouseMove = (ev: MouseEvent) => {
      if (phase !== "move" || selectedUnitId === null) return;
      const app = appRef.current;
      if (!app || !canvas) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = (app.renderer.width / app.renderer.resolution) / rect.width;
      const scaleY = (app.renderer.height / app.renderer.resolution) / rect.height;
      const px = (ev.clientX - rect.left) * scaleX;
      const py = (ev.clientY - rect.top) * scaleY;

      const selectedUnit = units.find((u) => u.id === selectedUnitId);
      if (!selectedUnit) return;

      // Build the icon container once per selected unit
      if (!hoverSpriteRef.current || hoverSpriteRef.current.destroyed || spriteBuiltForUnitId !== selectedUnitId) {
        if (hoverSpriteRef.current) {
          hoverSpriteRef.current.destroy({ children: true });
          hoverSpriteRef.current = null;
        }
        const container = new PIXI.Container();
        container.zIndex = 900;
        container.eventMode = "none";
        container.interactiveChildren = false;
        app.stage.addChild(container);

        const baseSizeVal = typeof selectedUnit.BASE_SIZE === "number" ? selectedUnit.BASE_SIZE : undefined;
        const iconDiam = baseSizeVal
          ? baseSizeVal * 1.5 * HEX_RADIUS_H
          : HEX_RADIUS_H * (selectedUnit.ICON_SCALE ?? 1.0);
        const circleRadius = iconDiam / 2;

        const baseCircle = new PIXI.Graphics();
        const baseColor = selectedUnit.player === 1 ? 0x1d4ed8 : 0x882222;
        baseCircle.beginFill(baseColor, 0.7);
        baseCircle.drawCircle(0, 0, circleRadius);
        baseCircle.endFill();
        container.addChild(baseCircle);

        if (selectedUnit.ICON) {
          const iconPath = selectedUnit.player === 2
            ? selectedUnit.ICON.replace(".webp", "_red.webp")
            : selectedUnit.ICON;
          const texture = PIXI.Texture.from(iconPath);
          const iconSprite = new PIXI.Sprite(texture);
          iconSprite.anchor.set(0.5);
          iconSprite.width = iconDiam;
          iconSprite.height = iconDiam;
          container.addChild(iconSprite);
        }
        container.alpha = 0.65;
        hoverSpriteRef.current = container;
        spriteBuiltForUnitId = selectedUnitId;
      }

      const container = hoverSpriteRef.current;

      if (container.destroyed) {
        hideMovePreviewGuides();
        return;
      }

      // Always snap the icon to the nearest valid CENTER position (moveDestPool)
      // This ensures the full footprint never overlaps walls
      if (!destPixels) buildDestPixels();
      if (!destPixels || destPixels.length === 0) {
        container.visible = false;
        hideMovePreviewGuides();
        return;
      }

      let bestIdx = 0;
      let bestDist = Infinity;
      for (let i = 0; i < destPixels.length; i++) {
        const dp = destPixels[i];
        const d = (dp.x - px) * (dp.x - px) + (dp.y - py) * (dp.y - py);
        if (d < bestDist) { bestDist = d; bestIdx = i; }
      }
      const best = destPixels[bestIdx];

      // Only show the icon if cursor is reasonably close (within footprint zone or nearby)
      const approxCol = Math.round((px - HEX_WIDTH_H / 2 - MARGIN_H) / HEX_WIDTH_H);
      const rowOffset = (approxCol % 2) * HEX_HEIGHT_H / 2;
      const approxRow = Math.round((py - HEX_HEIGHT_H / 2 - MARGIN_H - rowOffset) / HEX_HEIGHT_H);
      const curKey = `${approxCol},${approxRow}`;
      const inZone = footprintZoneRef?.current?.has(curKey)
        || moveDestPoolRef?.current?.has(curKey);

      if (!inZone) {
        // Cursor outside zone: still snap to nearest center for smooth boundary sliding
        if (!zonePixels) buildZonePixels();
        const inExpandedZone = zonePixels && zonePixels.length > 0;
        if (!inExpandedZone) {
          container.visible = false;
          hideMovePreviewGuides();
          return;
        }
      }

      container.position.set(best.x, best.y);
      container.visible = true;
      const iconCol = best.col;
      const iconRow = best.row;

      // Ligne centre départ → centre icône prévisualisée (best) ; distance = hex entre ces centres (indépendante du curseur)
      const startCol = Number(selectedUnit.col);
      const startRow = Number(selectedUnit.row);
      const startX = hxX(startCol);
      const startY = hxY(startCol, startRow);
      const previewIconX = best.x;
      const previewIconY = best.y;
      const hexSteps = hexDistOff(startCol, startRow, iconCol, iconRow);
      const distanceDisplay = (hexSteps / HEX_STEPS_PER_INCH_DISPLAY).toFixed(1);

      if (!movePreviewGuideLineRef.current || movePreviewGuideLineRef.current.destroyed) {
        const g = new PIXI.Graphics();
        g.zIndex = 848;
        g.eventMode = "none";
        app.stage.addChild(g);
        movePreviewGuideLineRef.current = g;
      }
      const guideLine = movePreviewGuideLineRef.current;
      guideLine.clear();
      guideLine.lineStyle(2, 0xe2e8f0, 0.9);
      guideLine.moveTo(startX, startY);
      guideLine.lineTo(previewIconX, previewIconY);
      guideLine.visible = true;

      setMovePreviewDistanceTooltip({
        visible: true,
        text: `${distanceDisplay}"`,
        x: rect.left + previewIconX / scaleX,
        y: rect.top + previewIconY / scaleY,
      });

      hoveredHexRef.current = { col: iconCol, row: iconRow };

      // Find nearest valid center for LoS (icon may be on a footprint extension hex)
      let losCol = iconCol;
      let losRow = iconRow;
      if (!moveDestPoolRef?.current?.has(`${iconCol},${iconRow}`)) {
        if (!destPixels) buildDestPixels();
        if (destPixels && destPixels.length > 0) {
          const ix = container.position.x;
          const iy = container.position.y;
          let bestDist = Infinity;
          for (let i = 0; i < destPixels.length; i++) {
            const dp = destPixels[i];
            const d = (dp.x - ix) * (dp.x - ix) + (dp.y - iy) * (dp.y - iy);
            if (d < bestDist) { bestDist = d; losCol = dp.col; losRow = dp.row; }
          }
        }
      }

      const prevLos = losHexRef.current;
      const losHexChanged = !prevLos || prevLos.col !== losCol || prevLos.row !== losRow;
      losHexRef.current = { col: losCol, row: losRow };

      if (losHexChanged) {
        triggerLosForHex(losCol, losRow);
      }
    };

    // Debounced LoS computation, shared by mousemove and boardHexHover
    let losDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    const LOS_DEBOUNCE_MS = 60;

    const triggerLosForHex = (col: number, row: number) => {
      if (losDebounceTimer) clearTimeout(losDebounceTimer);
      losDebounceTimer = setTimeout(() => {
        const app = appRef.current;
        if (!app) return;
        const selectedUnit = units.find((u) => u.id === selectedUnitId);
        if (!selectedUnit) return;
        const range = getMaxRangedRange(selectedUnit);
        if (range <= 0 || !selectedUnit.RNG_WEAPONS?.length || !isWasmReady()) return;

        if (!hoverOverlayRef.current || hoverOverlayRef.current.destroyed) {
          hoverOverlayRef.current = new PIXI.Graphics();
          hoverOverlayRef.current.zIndex = 50;
          app.stage.addChild(hoverOverlayRef.current);
        }
        const overlay = hoverOverlayRef.current;
        const requestId = ++losRequestIdRef.current;

        const visibleHexes = computeVisibleHexes(
          col, row, range,
          BOARD_COLS_H, BOARD_ROWS_H,
          wallHexesH,
          losMin, coverR,
        );

        if (losRequestIdRef.current !== requestId) return;

        overlay.clear();
        overlay.beginFill(ATTACK_COLOR_H, 0.3);
        for (const hex of visibleHexes) {
          overlay.drawCircle(hxX(hex.col), hxY(hex.col, hex.row), HEX_RADIUS_H);
        }
        overlay.endFill();
        overlay.visible = true;

        if (hoverCoverIconsRef.current && !hoverCoverIconsRef.current.destroyed) {
          hoverCoverIconsRef.current.removeChildren();
        } else {
          hoverCoverIconsRef.current = new PIXI.Container();
          hoverCoverIconsRef.current.zIndex = 400;
          hoverCoverIconsRef.current.sortableChildren = true;
          app.stage.addChild(hoverCoverIconsRef.current);
        }
        const losVisibleSet = new Set<string>();
        for (const hex of visibleHexes) {
          losVisibleSet.add(`${hex.col},${hex.row}`);
        }
        const selectedPlayer = selectedUnit.player;
        const hpBarWidthRatio = boardConfig.display?.hp_bar_width_ratio ?? 1.4;

        for (const u of units) {
          if (u.player === selectedPlayer) continue;
          const uBaseSize = typeof u.BASE_SIZE === "number" && u.BASE_SIZE > 1 ? u.BASE_SIZE : 0;
          const scanR = uBaseSize > 0 ? Math.ceil(uBaseSize / 2) : 0;
          let totalHexes = 0;
          let visibleCount = 0;
          for (let dc = -scanR; dc <= scanR; dc++) {
            for (let dr = -scanR; dr <= scanR; dr++) {
              if (hexDistOff(u.col, u.row, u.col + dc, u.row + dr) > scanR) continue;
              totalHexes++;
              if (losVisibleSet.has(`${u.col + dc},${u.row + dr}`)) visibleCount++;
            }
          }
          const ratio = totalHexes > 0 ? visibleCount / totalHexes : 0;
          const isVisible = ratio >= losMin;
          if (!isVisible) continue;
          const inCover = ratio < coverR;

          const ux = hxX(u.col);
          const uy = hxY(u.col, u.row);
          const uIconRadius = uBaseSize > 0
            ? (uBaseSize / 2) * (1.5 * HEX_RADIUS_H)
            : (HEX_RADIUS_H * (u.ICON_SCALE ?? 1.2)) / 2;

          // Damage preview bar
          const barW = (uBaseSize > 0 ? uIconRadius : HEX_RADIUS_H * (u.ICON_SCALE ?? 1.2)) * hpBarWidthRatio * 1.5;
          const barH = HP_BAR_H * 1.5;
          const barX = ux - barW / 2;
          const barY = uy - uIconRadius - barH - 1;
          const currentHP = Math.max(0, u.HP_CUR ?? u.HP_MAX ?? 1);
          const hpMax = u.HP_MAX ?? 1;

          // Calculate expected damage (rounded up to at least 1 if any damage expected)
          let expectedDmg = 0;
          const preferred = getPreferredRangedWeaponAgainstTarget(selectedUnit, u, inCover);
          if (preferred && preferred.expectedDamage > 0) {
            expectedDmg = Math.max(1, Math.round(preferred.expectedDamage));
          }

          // Background
          const bg = new PIXI.Graphics();
          bg.beginFill(0x222222, 0.9);
          bg.drawRoundedRect(barX, barY, barW, barH, Math.max(1, barH * 0.3));
          bg.endFill();
          bg.zIndex = 400;
          hoverCoverIconsRef.current.addChild(bg);

          // HP slices
          const sliceW = barW / hpMax;
          const pad = Math.min(Math.max(0.3, barH * 0.1), sliceW * 0.15);
          for (let i = 0; i < hpMax; i++) {
            const slice = new PIXI.Graphics();
            let color: number;
            if (i >= currentHP) {
              color = 0x444444;
            } else if (i >= currentHP - expectedDmg) {
              color = 0xff4444;
            } else {
              color = u.player === 1 ? 0x4da6ff : 0x36e36b;
            }
            slice.beginFill(color, 1);
            slice.drawRoundedRect(
              barX + i * sliceW + pad,
              barY + pad,
              sliceW - pad * 2,
              barH - pad * 2,
              Math.max(0.5, barH * 0.2)
            );
            slice.endFill();
            slice.zIndex = 401;
            hoverCoverIconsRef.current.addChild(slice);
          }

          // Cover shield icon (drawn as graphics for reliable rendering)
          if (inCover) {
            const s = Math.max(6, barH * 1.2);
            const sx = barX + barW + s * 0.7;
            const sy = barY + barH / 2;
            const shieldGfx = new PIXI.Graphics();
            shieldGfx.lineStyle(Math.max(1, s * 0.15), 0xfbbf24, 1);
            shieldGfx.beginFill(0x38bdf8, 0.85);
            shieldGfx.moveTo(sx, sy - s * 0.5);
            shieldGfx.lineTo(sx + s * 0.4, sy - s * 0.25);
            shieldGfx.lineTo(sx + s * 0.4, sy + s * 0.15);
            shieldGfx.lineTo(sx, sy + s * 0.5);
            shieldGfx.lineTo(sx - s * 0.4, sy + s * 0.15);
            shieldGfx.lineTo(sx - s * 0.4, sy - s * 0.25);
            shieldGfx.closePath();
            shieldGfx.endFill();
            shieldGfx.zIndex = 402;
            hoverCoverIconsRef.current.addChild(shieldGfx);
          }
        }
        hoverCoverIconsRef.current.visible = true;
      }, LOS_DEBOUNCE_MS);
    };

    // boardHexHover: also triggers LoS for hex changes inside the zone
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{
        col: number; row: number; hexChanged: boolean;
      }>).detail;
      const { col, row, hexChanged } = detail;
      if (!hexChanged) return;
      if (phase !== "move" || selectedUnitId === null) {
        if (hoverOverlayRef.current) hoverOverlayRef.current.visible = false;
        if (hoverCoverIconsRef.current) hoverCoverIconsRef.current.visible = false;
        return;
      }
      if (!moveDestPoolRef?.current?.has(`${col},${row}`)) return;
      triggerLosForHex(col, row);
    };

    if (canvas) canvas.addEventListener("mousemove", onMouseMove);
    window.addEventListener("boardHexHover", handler);
    return () => {
      if (losDebounceTimer) clearTimeout(losDebounceTimer);
      if (canvas) canvas.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("boardHexHover", handler);
      if (hoverOverlayRef.current) hoverOverlayRef.current.visible = false;
      if (hoverCoverIconsRef.current) hoverCoverIconsRef.current.visible = false;
      if (hoverSpriteRef.current) hoverSpriteRef.current.visible = false;
      if (movePreviewGuideLineRef.current && !movePreviewGuideLineRef.current.destroyed) {
        movePreviewGuideLineRef.current.clear();
        movePreviewGuideLineRef.current.visible = false;
      }
      setMovePreviewDistanceTooltip(null);
      hoveredHexRef.current = null;
      losHexRef.current = null;
    };
  }, [boardConfig, gameConfig, phase, selectedUnitId, units, setMovePreviewDistanceTooltip]);

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

    // PIXI textures are managed by the internal cache — no manual clearing needed.

    if (phase !== "move" || selectedUnitId === null) {
      if (moveDestPoolRef?.current && moveDestPoolRef.current.size > 0) {
        moveDestPoolRef.current.clear();
      }
    }

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

    // Remove previous tutorial death ghost (étape 1-25) if any
    const existingGhost = app.stage.children.find((c) => c.name === "tutorial-death-ghost");
    if (existingGhost) {
      app.stage.removeChild(existingGhost);
      if ("destroy" in existingGhost && typeof (existingGhost as PIXI.Container).destroy === "function") {
        (existingGhost as PIXI.Container).destroy({ children: true });
      }
    }

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

    // Right click cancels current action
    const contextMenuHandler = (e: Event) => {
      e.preventDefault();

      if (phase === "move" && mode === "select" && selectedUnitId !== null) {
        onSelectUnit(null);
      } else if (phase === "shoot" && mode === "movePreview") {
        onCancelMove?.();
      } else if (phase === "shoot") {
        if (targetPreview) {
          onCancelTargetPreview?.();
        }
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

      // Fight preview: show adjacent hexes around active unit in red.
      // Use direct neighbor computation instead of O(cols×rows) scan.
      const cubeNeighborDirs = [[1,-1,0],[1,0,-1],[0,1,-1],[-1,1,0],[-1,0,1],[0,-1,1]];
      for (const [dx, , dz] of cubeNeighborDirs) {
        const nc = c1.x + dx;
        const nr = (c1.z + dz) + ((nc - (nc & 1)) >> 1);
        if (nc >= 0 && nc < BOARD_COLS && nr >= 0 && nr < BOARD_ROWS) {
          fightPreviewCells.push({ col: nc, row: nr });
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

    // ✅ MOVEMENT PREVIEW: Use backend-computed destinations (valid_move_destinations_pool)
    // instead of recalculating client-side. The backend BFS handles walls, footprints,
    // engagement zones, and pathfinding correctly on the ×10 board.
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
        const zone = gameState?.move_preview_footprint_zone ?? gameState?.move_preview_border;
        if (zone && Array.isArray(zone) && zone.length > 0) {
          for (const dest of zone) {
            if (Array.isArray(dest) && dest.length === 2) {
              availableCells.push({ col: Number(dest[0]), row: Number(dest[1]) });
            } else if (dest && typeof dest === "object" && "col" in dest && "row" in dest) {
              availableCells.push({ col: Number(dest.col), row: Number(dest.row) });
            }
          }
        }
      } else if (phase !== "charge") {
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
      const range = getMaxRangedRange(source.unit);
      if (range <= 0) {
        return;
      }

      if (isWasmReady()) {
        const visibleHexes = computeVisibleHexes(
          source.fromCol, source.fromRow, range,
          BOARD_COLS, BOARD_ROWS,
          effectiveWallHexes,
          losVisibilityMinRatio, coverRatio,
        );
        const visibleHexSet = new Set<string>();
        for (const hex of visibleHexes) {
          const key = `${hex.col},${hex.row}`;
          visibleHexSet.add(key);
          if (!attackCellSet.has(key)) {
            attackCellSet.add(key);
            attackCells.push({ col: hex.col, row: hex.row });
          }
          losVisibilityRatioByHex.set(key, 1.0);
        }
        for (const enemy of units) {
          if (enemy.player === source.unit.player) continue;
          const eBase = typeof enemy.BASE_SIZE === "number" && enemy.BASE_SIZE > 1 ? enemy.BASE_SIZE : 0;
          const scanR = eBase > 0 ? Math.ceil(eBase / 2) : 0;
          let totalHexes = 0;
          let visCount = 0;
          for (let dc = -scanR; dc <= scanR; dc++) {
            for (let dr = -scanR; dr <= scanR; dr++) {
              if (hexDistOff(enemy.col, enemy.row, enemy.col + dc, enemy.row + dr) > scanR) continue;
              totalHexes++;
              if (visibleHexSet.has(`${enemy.col + dc},${enemy.row + dr}`)) visCount++;
            }
          }
          const ratio = totalHexes > 0 ? visCount / totalHexes : 0;
          if (ratio >= losVisibilityMinRatio && ratio < coverRatio) {
            for (let dc = -scanR; dc <= scanR; dc++) {
              for (let dr = -scanR; dr <= scanR; dr++) {
                if (hexDistOff(enemy.col, enemy.row, enemy.col + dc, enemy.row + dr) > scanR) continue;
                const ek = `${enemy.col + dc},${enemy.row + dr}`;
                if (visibleHexSet.has(ek)) {
                  coverCells.push({ col: enemy.col + dc, row: enemy.row + dr });
                  losVisibilityRatioByHex.set(ek, ratio);
                }
              }
            }
          }
        }
      } else {
        const enemyById = new Map<string, Unit>();
        for (const enemy of units) {
          if (enemy.player !== source.unit.player) {
            enemyById.set(String(enemy.id), enemy);
          }
        }
        const wallHexSet = new Set<string>(effectiveWallHexes.map((wall: number[]) => `${wall[0]},${wall[1]}`));

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
              if (hex.col === source.fromCol && hex.row === source.fromRow) continue;
              const hexKey = `${hex.col},${hex.row}`;
              if (wallHexSet.has(hexKey)) continue;
              if (!attackCellSet.has(hexKey)) {
                attackCellSet.add(hexKey);
                attackCells.push({ col: hex.col, row: hex.row });
              }
            }
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
      objective_zones?: Array<{ id: string; hexes: [number, number][] }>;
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
    // Compute units fingerprint to determine if unit re-rendering is needed
    const unitsFingerprint = (() => {
      const parts: string[] = [];
      for (const u of units) {
        parts.push(`${u.id},${u.col},${u.row},${u.HP_CUR}`);
      }
      return `${parts.join("|")}#${selectedUnitId}#${phase}#${mode}#${movePreview?.destCol ?? ""},${movePreview?.destRow ?? ""}#${attackPreview?.col ?? ""},${attackPreview?.row ?? ""}#${blinkVersion}#${fightSubPhase}#${chargeTargetId}#${shootingTargetId}#${shootingUnitId}#${movingUnitId}#${chargingUnitId}#${fightingUnitId}#${fightTargetId}#${advancingUnitId}#${ruleChoiceHighlightedUnitId}`;
    })();
    const unitsChanged = unitsFingerprint !== unitsFingerprintRef.current;

    if (app.stage) {
      // Detach persistent containers before removeChildren so they survive.
      const savedStatic = staticBoardRef.current;
      const savedWalls = staticWallsRef.current;
      const savedUi = uiElementsContainerRef.current;
      const savedDragOverlay = dragOverlayRef.current;
      const savedUnitsLayer = unitsLayerRef.current;
      const savedBlinks: PIXI.DisplayObject[] = [];
      if (savedStatic?.parent) app.stage.removeChild(savedStatic);
      if (savedWalls?.parent) app.stage.removeChild(savedWalls);
      if (savedUi?.parent) app.stage.removeChild(savedUi);
      if (savedDragOverlay?.parent) app.stage.removeChild(savedDragOverlay);
      if (savedUnitsLayer?.parent) app.stage.removeChild(savedUnitsLayer);
      for (const child of [...app.stage.children]) {
        if (child.name === "hp-blink-container") {
          app.stage.removeChild(child);
          savedBlinks.push(child);
        }
      }

      // Destroy all remaining children (old highlights, old units, etc.)
      const toDestroy = [...app.stage.children];
      app.stage.removeChildren();
      for (const child of toDestroy) {
        if (child.destroy) {
          child.destroy({ children: true, texture: false, baseTexture: false });
        }
      }
      hoverOverlayRef.current = null;
      hoverSpriteRef.current = null;
      movePreviewGuideLineRef.current = null;

      // If units changed, clear the units layer so it gets rebuilt
      if (unitsChanged && savedUnitsLayer) {
        const unitChildren = [...savedUnitsLayer.children];
        savedUnitsLayer.removeChildren();
        for (const child of unitChildren) {
          if (child.destroy) {
            child.destroy({ children: true, texture: false, baseTexture: false });
          }
        }
      }

      // Re-attach persistent containers in correct z-order
      if (savedStatic) app.stage.addChild(savedStatic);
      if (savedWalls) app.stage.addChild(savedWalls);
      if (savedUi) app.stage.addChild(savedUi);
      for (const blink of savedBlinks) app.stage.addChild(blink);
      if (savedUnitsLayer) app.stage.addChild(savedUnitsLayer);
      if (savedDragOverlay) app.stage.addChild(savedDragOverlay);

      // Clean stale transient UI markers
      if (savedUi) {
        const staleTargetMarkers = savedUi.children.filter(
          (child: PIXI.DisplayObject) =>
            typeof child.name === "string" &&
            (child.name.startsWith("target-indicator-") || child.name.startsWith("charge-badge-"))
        );
        staleTargetMarkers.forEach((child: PIXI.DisplayObject) => {
          savedUi.removeChild(child);
          if ("destroy" in child && typeof child.destroy === "function") {
            child.destroy();
          }
        });
      }
    }
    // Reuse cached static board layers when the board config hasn't changed.
    const bcKey = `${boardConfigWithOverrides.cols}x${boardConfigWithOverrides.rows}`;
    const canReuseStatic = staticBoardConfigKeyRef.current === bcKey && staticBoardRef.current !== null;

    const drawResult = drawBoard(app, boardConfigWithOverrides as Parameters<typeof drawBoard>[1], {
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
          : [],
      blockedTargets,
      coverTargets,
      phase: effectivePhase,
      interactionPhase: phase,
      selectedUnitId,
      mode,
      showHexCoordinates,
      objectiveControl,
      moveDestPoolRef,
      selectedUnitBaseSize: selectedUnit && typeof selectedUnit.BASE_SIZE === "number" ? selectedUnit.BASE_SIZE : undefined,
      cachedStaticBoard: canReuseStatic ? staticBoardRef.current : null,
      cachedWalls: canReuseStatic ? staticWallsRef.current : null,
      losDebugShowRatio: showLosDebugOverlay && phase === "shoot" && shootingPreviewSource !== null,
      losDebugRatioByHex: Object.fromEntries(losVisibilityRatioByHex),
      losDebugCoverRatio: coverRatio,
      losDebugVisibilityMinRatio: losVisibilityMinRatio,
    });

    if (!canReuseStatic && drawResult) {
      staticBoardRef.current = drawResult.baseHexContainer;
      staticWallsRef.current = drawResult.wallsContainer;
      staticBoardConfigKeyRef.current = bcKey;
    }

    // ✅ SETUP BOARD INTERACTIONS using shared BoardInteractions component
    // setupBoardInteractions is now a stub - no longer needed

    // ✅ Create or reuse persistent units layer
    if (!unitsLayerRef.current) {
      unitsLayerRef.current = new PIXI.Container();
      unitsLayerRef.current.name = "units-layer";
      unitsLayerRef.current.sortableChildren = true;
    }
    if (!unitsLayerRef.current.parent) {
      app.stage.addChild(unitsLayerRef.current);
    }
    const unitsLayer = unitsLayerRef.current;

    // ✅ UNIFIED UNIT RENDERING USING COMPONENT — skip if fingerprint unchanged
    if (unitsChanged) {
    unitsFingerprintRef.current = unitsFingerprint;
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
        renderTarget: unitsLayer,
        uiElementsContainer: uiElementsContainerRef.current!,
        useOverlayIcons: true,
        isPreview: false,
        isEligible: isMoveOriginGhost ? false : (isEligibleForRendering || false),
        isShootable,
        boardConfig: boardConfigForRender,
        HEX_RADIUS,
        HEX_HORIZ_SPACING,
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
        onUnitTooltip: handleUnitTooltip,
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
          renderTarget: unitsLayer,
          useOverlayIcons: true,
          isPreview: true,
          previewType: "move",
          isEligible: false,
          boardConfig: boardConfigForRender,
          HEX_RADIUS,
          HEX_HORIZ_SPACING,
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
          onUnitTooltip: handleUnitTooltip,
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
          renderTarget: unitsLayer,
          useOverlayIcons: true,
          isPreview: true,
          previewType: "move",
          isEligible: false,
          boardConfig: boardConfigForRender,
          HEX_RADIUS,
          HEX_HORIZ_SPACING,
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
          onUnitTooltip: handleUnitTooltip,
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
          renderTarget: unitsLayer,
          useOverlayIcons: true,
          isPreview: true,
          previewType: "attack",
          isEligible: false, // Preview units are not eligible
          boardConfig: boardConfigForRender,
          HEX_RADIUS,
          HEX_HORIZ_SPACING,
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
          onUnitTooltip: handleUnitTooltip,
          autoSelectWeapon,
          debugMode: showHexCoordinates,
        });
      }
    }
    } // end if (unitsChanged)

    // ✅ TUTORIAL 1-24-* / 1-25 : ghost Termagant à l'emplacement de mort sur le board
    if (
      tutorial?.currentStep?.stage != null &&
      (tutorial.currentStep.stage === "1-25" ||
        tutorial.currentStep.stage.startsWith("1-24-")) &&
      tutorial?.lastEnemyDeathPosition &&
      boardConfig
    ) {
      const { col, row } = tutorial.lastEnemyDeathPosition;
      const ghostCenterX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const ghostCenterY =
        row * HEX_VERT_SPACING +
        ((col % 2) * HEX_VERT_SPACING) / 2 +
        HEX_HEIGHT / 2 +
        MARGIN;
      const ghostContainer = new PIXI.Container();
      ghostContainer.name = "tutorial-death-ghost";
      const ghostSprite = PIXI.Sprite.from("/icons/Termagant_red.webp");
      ghostSprite.anchor.set(0.5);
      ghostSprite.position.set(ghostCenterX, ghostCenterY);
      ghostSprite.alpha = 0.45;
      const iconScale = boardConfig.display?.icon_scale ?? 1;
      const targetSize = HEX_RADIUS * iconScale;
      const tw = ghostSprite.texture?.width ?? ghostSprite.width ?? 1;
      const th = ghostSprite.texture?.height ?? ghostSprite.height ?? 1;
      const maxDim = Math.max(tw, th, 1);
      const ghostScale = targetSize / maxDim;
      ghostSprite.scale.set(ghostScale, ghostScale);
      ghostSprite.tint = 0x888888;
      ghostContainer.addChild(ghostSprite);
      app.stage.addChild(ghostContainer);
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
        const baseSizeOvl = typeof unit.BASE_SIZE === "number" && unit.BASE_SIZE > 1 ? unit.BASE_SIZE : 0;
        const iconRadiusOvl = baseSizeOvl > 0 ? (baseSizeOvl / 2) * HEX_HORIZ_SPACING : (HEX_RADIUS * unitIconScale) / 2;
        const barY = centerY - iconRadiusOvl - HP_BAR_HEIGHT - 1;

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
          const positionY = barY - squareSize / 2 - Math.max(2, HP_BAR_HEIGHT * 0.7);

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


    // --- Drag placement overlay (deployment phase ghost + footprint) ---
    let dragPointerMove: ((e: PointerEvent) => void) | null = null;
    let dragPointerUp: ((e: PointerEvent) => void) | null = null;
    let dragPointerLeave: (() => void) | null = null;

    if (phase === "deployment" && selectedUnitId !== null) {
      const canvas = app.view as HTMLCanvasElement;

      if (!dragOverlayRef.current) {
        dragOverlayRef.current = new PIXI.Container();
        dragOverlayRef.current.name = "drag-placement-overlay";
        dragOverlayRef.current.zIndex = 9000;
      }
      const dragContainer = dragOverlayRef.current;
      dragContainer.removeChildren();
      if (!dragContainer.parent) {
        app.stage.addChild(dragContainer);
      }

      const selectedUnit = units.find((u) => u.id === selectedUnitId);
      const wallSet = new Set((boardConfig.wall_hexes ?? []).map(([c, r]) => `${c},${r}`));
      const occupiedSet = buildOccupiedSet(
        units.map((u) => ({
          id: u.id,
          col: u.col,
          row: u.row,
          BASE_SHAPE: u.BASE_SHAPE,
          BASE_SIZE: typeof u.BASE_SIZE === "number" ? u.BASE_SIZE : 1,
          alive: u.HP_CUR > 0,
        })),
        selectedUnitId ?? undefined,
      );
      const ds = gameState.deployment_state;
      let deployPool: Set<string> | null = null;
      if (ds) {
        const poolRaw = ds.deployment_pools?.[String(ds.current_deployer)];
        if (poolRaw && Array.isArray(poolRaw)) {
          deployPool = new Set<string>();
          for (const entry of poolRaw) {
            if (Array.isArray(entry)) {
              deployPool.add(`${entry[0]},${entry[1]}`);
            } else if (entry && typeof entry === "object" && "col" in entry && "row" in entry) {
              deployPool.add(`${(entry as { col: number; row: number }).col},${(entry as { col: number; row: number }).row}`);
            }
          }
        }
      }
      const objsForIntersection: Array<{ id: number; hexes: HexCoord[] }> = (
        objectivesOverride ?? []
      ).map((obj, idx) => ({
        id: idx + 1,
        hexes: obj.hexes.map((h) => [h.col, h.row] as HexCoord),
      }));

      let lastHexKey = "";

      const drawDragOverlay = (
        hex: { col: number; row: number } | null,
        footprint: HexCoord[],
        valid: boolean,
        contestedIds: number[],
      ) => {
        dragContainer.removeChildren();
        if (!hex || footprint.length === 0) return;

        const fillColor = valid ? 0x00ff00 : 0xff0000;

        // Batch all footprint circles into one Graphics
        const fpBatch = new PIXI.Graphics();
        fpBatch.beginFill(fillColor, 0.3);
        fpBatch.lineStyle(1, fillColor, 0.6);
        for (const [c, r] of footprint) {
          const pos = hexToPixel(c, r, HEX_RADIUS, MARGIN);
          fpBatch.drawCircle(pos.x, pos.y, HEX_RADIUS);
        }
        fpBatch.endFill();
        dragContainer.addChild(fpBatch);

        if (contestedIds.length > 0) {
          const objBatch = new PIXI.Graphics();
          objBatch.beginFill(0xffcc00, 0.5);
          objBatch.lineStyle(2, 0xffcc00, 0.8);
          for (const objId of contestedIds) {
            const obj = objsForIntersection.find((o) => o.id === objId);
            if (!obj) continue;
            for (const [c, r] of obj.hexes) {
              const pos = hexToPixel(c, r, HEX_RADIUS, MARGIN);
              objBatch.drawCircle(pos.x, pos.y, HEX_RADIUS);
            }
          }
          objBatch.endFill();
          dragContainer.addChild(objBatch);
        }

        if (selectedUnit) {
          const ghostPos = hexToPixel(hex.col, hex.row, HEX_RADIUS, MARGIN);
          const circleR = HEX_RADIUS * (selectedUnit.ICON_SCALE ?? 0.6);
          const ghost = new PIXI.Graphics();
          ghost.beginFill(0xcccccc, 0.45);
          ghost.drawCircle(ghostPos.x, ghostPos.y, circleR);
          ghost.endFill();
          const idText = new PIXI.Text(String(selectedUnit.id), {
            fontSize: Math.max(6, HEX_RADIUS * 0.8),
            fill: valid ? 0x00ff00 : 0xff4444,
            fontWeight: "bold",
          });
          idText.anchor.set(0.5);
          idText.position.set(ghostPos.x, ghostPos.y);
          idText.alpha = 0.7;
          dragContainer.addChild(ghost);
          dragContainer.addChild(idText);
        }
      };

      dragPointerMove = (e: PointerEvent) => {
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const px = (e.clientX - rect.left) * scaleX;
        const py = (e.clientY - rect.top) * scaleY;
        const hex = pixelToHex(px, py, HEX_RADIUS, MARGIN, BOARD_COLS, BOARD_ROWS);

        if (hex.col < 0 || hex.col >= BOARD_COLS || hex.row < 0 || hex.row >= BOARD_ROWS) {
          lastHexKey = "";
          drawDragOverlay(null, [], false, []);
          return;
        }
        const key = `${hex.col},${hex.row}`;
        if (key === lastHexKey) return;
        lastHexKey = key;

        if (!selectedUnit) return;
        const shape = selectedUnit.BASE_SHAPE ?? "round";
        const size = typeof selectedUnit.BASE_SIZE === "number" ? selectedUnit.BASE_SIZE : 1;
        const fp = computeOccupiedHexes(hex.col, hex.row, shape, size);
        const inBounds = isFootprintInBounds(fp, BOARD_COLS, BOARD_ROWS);
        const onWall = isFootprintOnWall(fp, wallSet);
        const overlapping = isFootprintOverlapping(fp, occupiedSet);
        const inPool = deployPool ? isFootprintInDeployPool(fp, deployPool) : true;
        const valid = inBounds && !onWall && !overlapping && inPool;
        const contestedIds = getContestedObjectives(fp, objsForIntersection);
        drawDragOverlay(hex, fp, valid, contestedIds);
      };

      dragPointerUp = (e: PointerEvent) => {
        if (e.button !== 0) return;
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const px = (e.clientX - rect.left) * scaleX;
        const py = (e.clientY - rect.top) * scaleY;
        const hex = pixelToHex(px, py, HEX_RADIUS, MARGIN, BOARD_COLS, BOARD_ROWS);

        if (hex.col < 0 || hex.col >= BOARD_COLS || hex.row < 0 || hex.row >= BOARD_ROWS) return;
        if (!selectedUnit) return;
        const shape = selectedUnit.BASE_SHAPE ?? "round";
        const size = typeof selectedUnit.BASE_SIZE === "number" ? selectedUnit.BASE_SIZE : 1;
        const fp = computeOccupiedHexes(hex.col, hex.row, shape, size);
        const inBounds = isFootprintInBounds(fp, BOARD_COLS, BOARD_ROWS);
        const onWall = isFootprintOnWall(fp, wallSet);
        const overlapping = isFootprintOverlapping(fp, occupiedSet);
        const inPool = deployPool ? isFootprintInDeployPool(fp, deployPool) : true;
        const valid = inBounds && !onWall && !overlapping && inPool;
        if (!valid) return;
        stableCallbacks.current.onDeployUnit?.(selectedUnitId, hex.col, hex.row);
      };

      dragPointerLeave = () => {
        lastHexKey = "";
        drawDragOverlay(null, [], false, []);
      };

      canvas.addEventListener("pointermove", dragPointerMove);
      canvas.addEventListener("pointerup", dragPointerUp);
      canvas.addEventListener("pointerleave", dragPointerLeave);
    }

    // --- Movement drag-and-drop overlay ---
    if (phase === "move" && mode === "select" && selectedUnitId !== null) {
      const canvas = app.view as HTMLCanvasElement;
      const selectedUnit = units.find((u) => u.id === selectedUnitId);
      if (selectedUnit) {
        if (!dragOverlayRef.current) {
          dragOverlayRef.current = new PIXI.Container();
          dragOverlayRef.current.name = "drag-placement-overlay";
          dragOverlayRef.current.zIndex = 9000;
        }
        const dragContainer = dragOverlayRef.current;
        dragContainer.removeChildren();
        if (!dragContainer.parent) {
          app.stage.addChild(dragContainer);
        }

        let lastMoveHexKey = "";
        const poolRef = moveDestPoolRef?.current;

        dragPointerMove = (e: PointerEvent) => {
          const rect = canvas.getBoundingClientRect();
          const scaleX = canvas.width / rect.width;
          const scaleY = canvas.height / rect.height;
          const px = (e.clientX - rect.left) * scaleX;
          const py = (e.clientY - rect.top) * scaleY;
          const hex = pixelToHex(px, py, HEX_RADIUS, MARGIN, BOARD_COLS, BOARD_ROWS);

          if (hex.col < 0 || hex.col >= BOARD_COLS || hex.row < 0 || hex.row >= BOARD_ROWS) {
            lastMoveHexKey = "";
            dragContainer.removeChildren();
            return;
          }
          const key = `${hex.col},${hex.row}`;
          if (key === lastMoveHexKey) return;
          lastMoveHexKey = key;

          dragContainer.removeChildren();
          const valid = poolRef ? poolRef.has(key) : false;
          const ghostPos = hexToPixel(hex.col, hex.row, HEX_RADIUS, MARGIN);
          const circleR = HEX_RADIUS * (selectedUnit.ICON_SCALE ?? 0.6);
          const ghost = new PIXI.Graphics();
          ghost.beginFill(valid ? 0x00ff00 : 0xff0000, 0.35);
          ghost.drawCircle(ghostPos.x, ghostPos.y, circleR);
          ghost.endFill();
          const idText = new PIXI.Text(String(selectedUnit.id), {
            fontSize: Math.max(6, HEX_RADIUS * 0.8),
            fill: valid ? 0x00ff00 : 0xff4444,
            fontWeight: "bold",
          });
          idText.anchor.set(0.5);
          idText.position.set(ghostPos.x, ghostPos.y);
          idText.alpha = 0.7;
          dragContainer.addChild(ghost);
          dragContainer.addChild(idText);
        };

        dragPointerLeave = () => {
          lastMoveHexKey = "";
          dragContainer.removeChildren();
        };

        canvas.addEventListener("pointermove", dragPointerMove);
        canvas.addEventListener("pointerleave", dragPointerLeave);
      }
    }

    // Cleanup function
    return () => {
      // Cleanup board interactions
      // cleanupBoardInteractions is now a stub - no longer needed

      if (app.view?.removeEventListener) {
        app.view.removeEventListener("contextmenu", contextMenuHandler);
      }
      window.removeEventListener("boardAdvanceClick", advanceClickHandler);

      // Cleanup drag placement handlers
      const canvas = app.view as HTMLCanvasElement;
      if (dragPointerMove) canvas.removeEventListener("pointermove", dragPointerMove);
      if (dragPointerUp) canvas.removeEventListener("pointerup", dragPointerUp);
      if (dragPointerLeave) canvas.removeEventListener("pointerleave", dragPointerLeave);
      if (dragOverlayRef.current) dragOverlayRef.current.removeChildren();
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
    tutorial?.currentStep?.stage,
    tutorial?.lastEnemyDeathPosition,
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
        <div
          ref={canvasContainerRef}
          onMouseMove={handleCanvasMouseMove}
          onMouseLeave={() => {
            setHexCoordTooltip(null);
            setUnitHoverTooltip(null);
            setMovePreviewDistanceTooltip(null);
          }}
        />
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
        {movePreviewDistanceTooltip?.visible && (
          <div
            className="rule-tooltip unit-icon-tooltip"
            style={{
              position: "fixed",
              left: `${movePreviewDistanceTooltip.x}px`,
              top: `${movePreviewDistanceTooltip.y}px`,
              marginBottom: 0,
              zIndex: 1300,
              visibility: "visible",
              opacity: 1,
              transform: "translate(12px, -14px)",
              pointerEvents: "none",
            }}
          >
            {movePreviewDistanceTooltip.text}
          </div>
        )}
        {hexCoordTooltip?.visible && (
          <div
            style={{
              position: "fixed",
              left: `${hexCoordTooltip.x + 14}px`,
              top: `${hexCoordTooltip.y - 28}px`,
              background: "rgba(0,0,0,0.85)",
              color: "#0f0",
              fontSize: "12px",
              fontFamily: "monospace",
              lineHeight: 1.35,
              padding: "2px 3px",
              borderRadius: "4px",
              pointerEvents: "none",
              zIndex: 1400,
              whiteSpace: "nowrap",
              boxSizing: "border-box",
            }}
          >
            {hexCoordTooltip.col},{hexCoordTooltip.row}
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
