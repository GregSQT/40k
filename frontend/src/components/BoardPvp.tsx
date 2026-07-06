// frontend/src/components/BoardPvp.tsx

import * as PIXI from "pixi.js-legacy";
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { TUTORIAL_STEP_TITLES_INTERCESSOR_HALO, useTutorial } from "../contexts/TutorialContext";
import { useGameConfig } from "../hooks/useGameConfig";
import { useSingleDoubleClick } from "../hooks/useSingleDoubleClick";
import type {
  FightSubPhase,
  GameState,
  PlayerId,
  PrimaryObjectiveRule,
  ShootingPhaseState,
  TargetPreview,
  Unit,
  UnitId,
  Weapon,
  WeaponOption,
} from "../types/game";
import {
  type BlinkProbHtmlPayload,
  DAMAGE_PROBABILITY_TOOLTIP_HTML_OPACITY,
  DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX,
  type HPBlinkContainer,
  type HpBarHtmlTooltipPayload,
  pixiStagePointToClientScreen,
} from "../utils/blinkingHPBar";
// import { SingleShotDisplay } from './SingleShotDisplay';
import { setupBoardClickHandler } from "../utils/boardClickHandler";
import { areUnitsAdjacent, cubeDistance, offsetToCube } from "../utils/gameHelpers";
import {
  buildOccupiedSet,
  computeOccupiedHexes,
  getContestedObjectives,
  getFightEngagementRingBoardPixels,
  type HexCoord,
  hexToPixel,
  isFootprintInBounds,
  isFootprintInDeployPool,
  isFootprintOnWall,
  isFootprintOverlapping,
  minHexDistanceBetweenFootprintKeySets,
  pixelToHex,
  resolveBaseSizeForUnitDisplay,
  squadFootprintHexKeysFromModelCenters,
  unitFootprintHexKeys,
} from "../utils/hexFootprint";
import type { HexUnionMaskLayout } from "../utils/hexUnionBoundaryPolygon";
import { drawHiddenEyeBadge } from "../utils/hiddenBadgeDraw";
import { mountLosPolarClippedByVisibleUnion } from "../utils/losPolarMaskedByVisibleUnion";
import {
  buildLosPreviewFromSource,
  hexDistOff,
  rangedPreviewMetric,
  unitsCacheModelCenters,
} from "../utils/losPreviewHelpers";
import { syncMoveDestinationPoolRefs } from "../utils/movePoolRefsSync";
import { normalizeMaskLoopsFromApi } from "../utils/movePreviewFootprintMaskLoops";
import { pointInAnyMaskLoop } from "../utils/pointInPolygon";
import {
  getNonRoundBasePixelLayout,
  getNonRoundIconRadius,
  getSquareCornerRadiusPx,
} from "../utils/unitBaseDisplay";
import { ensureWasmLoaded, isWasmReady } from "../utils/wasmLos";
import { getMaxRangedRange } from "../utils/weaponHelpers";
import {
  computeDrawBoardPartialRedrawFingerprint,
  type DrawBoardOptions,
  detachMovePreviewLayerCacheFromStage,
  drawBoard,
  updateMovePreviewPolygonLayerInHighlightContainer,
} from "./BoardDisplay";
import { type ModelVisualMeta, renderUnit } from "./UnitRenderer";
import { WeaponDropdown } from "./WeaponDropdown";

// Helper functions are now in BoardDisplay.tsx - removed from here

/** JSON stable pour l’empreinte unités (ordre des clés sinon ``unitsChanged`` boucle → gel UI). */
function stableBoolRecordJson(m: Record<string, boolean>): string {
  const keys = Object.keys(m).sort();
  const sorted: Record<string, boolean> = {};
  for (const k of keys) {
    sorted[k] = m[k] === true;
  }
  return JSON.stringify(sorted);
}

interface BackendLosPreviewCell {
  col: number;
  row: number;
}

interface BackendMoveLosPreviewPayload {
  blinkIds: number[];
  clearCells: BackendLosPreviewCell[];
  coverCells: BackendLosPreviewCell[];
  coverByUnitId: Record<string, boolean>;
  hiddenTooFarByUnitId: Record<string, boolean>;
  /** Cases visibles des cibles ciblables (backend, règle 06.01/13.10), aplaties+dédupliquées. */
  visibleTargetCells: BackendLosPreviewCell[];
  key: string;
}

const MOVE_PREVIEW_LOS_CACHE_MAX_ENTRIES = 256;

function parseBackendLosPreviewCells(raw: unknown, fieldName: string): BackendLosPreviewCell[] {
  if (!Array.isArray(raw)) {
    throw new Error(`${fieldName} must be an array`);
  }
  return raw.map((cell, index) => {
    if (!cell || typeof cell !== "object" || Array.isArray(cell)) {
      throw new Error(`${fieldName}[${index}] must be an object`);
    }
    const rec = cell as Record<string, unknown>;
    if (typeof rec.col !== "number" || typeof rec.row !== "number") {
      throw new Error(`${fieldName}[${index}] must contain numeric col/row`);
    }
    return { col: rec.col, row: rec.row };
  });
}

function parseBackendMoveLosPreviewPayload(
  raw: unknown,
  key: string
): BackendMoveLosPreviewPayload {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("preview_shoot_from_position result must be an object");
  }
  const result = raw as Record<string, unknown>;
  const blinkingUnits = result.blinking_units;
  if (!Array.isArray(blinkingUnits)) {
    throw new Error("preview_shoot_from_position blinking_units must be an array");
  }
  const blinkIds = blinkingUnits.map((id, index) => {
    const parsed = typeof id === "number" ? id : typeof id === "string" ? parseInt(id, 10) : NaN;
    if (Number.isNaN(parsed)) {
      throw new Error(`preview_shoot_from_position blinking_units[${index}] is invalid`);
    }
    return parsed;
  });
  const coverRaw = result.cover_by_unit_id;
  if (!coverRaw || typeof coverRaw !== "object" || Array.isArray(coverRaw)) {
    throw new Error("preview_shoot_from_position cover_by_unit_id must be an object");
  }
  const coverByUnitId: Record<string, boolean> = {};
  for (const [unitId, inCover] of Object.entries(coverRaw as Record<string, unknown>)) {
    if (typeof inCover !== "boolean") {
      throw new Error(`preview_shoot_from_position cover_by_unit_id.${unitId} must be boolean`);
    }
    coverByUnitId[unitId] = inCover;
  }
  const tooFarRaw = result.hidden_too_far_by_unit_id;
  if (!tooFarRaw || typeof tooFarRaw !== "object" || Array.isArray(tooFarRaw)) {
    throw new Error("preview_shoot_from_position hidden_too_far_by_unit_id must be an object");
  }
  const hiddenTooFarByUnitId: Record<string, boolean> = {};
  for (const [unitId, tooFar] of Object.entries(tooFarRaw as Record<string, unknown>)) {
    if (typeof tooFar !== "boolean") {
      throw new Error(
        `preview_shoot_from_position hidden_too_far_by_unit_id.${unitId} must be boolean`
      );
    }
    hiddenTooFarByUnitId[unitId] = tooFar;
  }
  const visibleByTargetRaw = result.visible_cells_by_target;
  const visibleTargetCells: BackendLosPreviewCell[] = [];
  if (
    visibleByTargetRaw &&
    typeof visibleByTargetRaw === "object" &&
    !Array.isArray(visibleByTargetRaw)
  ) {
    const seen = new Set<string>();
    for (const cells of Object.values(visibleByTargetRaw as Record<string, unknown>)) {
      if (!Array.isArray(cells)) continue;
      for (const cell of cells) {
        if (!Array.isArray(cell) || cell.length < 2) continue;
        const c = Number(cell[0]);
        const r = Number(cell[1]);
        if (!Number.isFinite(c) || !Number.isFinite(r)) continue;
        const k = `${c},${r}`;
        if (seen.has(k)) continue;
        seen.add(k);
        visibleTargetCells.push({ col: c, row: r });
      }
    }
  }
  return {
    blinkIds,
    clearCells: parseBackendLosPreviewCells(
      result.los_preview_attack_cells,
      "los_preview_attack_cells"
    ),
    coverCells: parseBackendLosPreviewCells(
      result.los_preview_cover_cells,
      "los_preview_cover_cells"
    ),
    coverByUnitId,
    hiddenTooFarByUnitId,
    visibleTargetCells,
    key,
  };
}

function parseRequiredUnitId(raw: unknown, context: string): number {
  const parsed = typeof raw === "number" ? raw : typeof raw === "string" ? parseInt(raw, 10) : NaN;
  if (!Number.isInteger(parsed)) {
    throw new Error(`${context} must be a numeric unit id, got ${String(raw)}`);
  }
  return parsed;
}

/** Aplatit ``visible_cells_by_target`` (backend, règle 06.01/13.10) en liste {col,row}, dédupliquée.
 * Optionnellement filtrée aux cibles ciblables (ids). Ces cases sont peintes par-dessus le cône
 * WASM pour garantir la cohérence blink↔visuel (une cible qui blinke a toujours ses cases peintes). */
function flattenVisibleCellsByTarget(
  byTarget: Record<string, Array<[number, number]>> | undefined,
  onlyTargetIds?: Set<string>
): Array<{ col: number; row: number }> {
  if (!byTarget) return [];
  const seen = new Set<string>();
  const out: Array<{ col: number; row: number }> = [];
  for (const [tid, cells] of Object.entries(byTarget)) {
    if (onlyTargetIds && !onlyTargetIds.has(String(tid))) continue;
    for (const [c, r] of cells) {
      const k = `${c},${r}`;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push({ col: c, row: r });
    }
  }
  return out;
}

/** Signature courte d’un pool (longueur + premier + dernier) pour dépendances sans ``JSON.stringify`` massif. */
function poolEdgeSig(pool: unknown): string {
  if (!Array.isArray(pool) || pool.length === 0) return "0";
  const last = pool[pool.length - 1];
  return `${pool.length}:${JSON.stringify(pool[0])}:${JSON.stringify(last)}`;
}

/**
 * Halos de cohésion d'escouade (move/advance/charge/pile-in/consolidation, par-figurine au survol).
 * Tout est calculé en EUCLIDIEN (distance pixel entre centres) pour que les verdicts (couleurs)
 * coïncident exactement avec les cercles dessinés.
 *  - Halo model autour de la SEULE figurine active : rayon = base + ``unit_model_cohesion_range`` ;
 *    blanc par défaut, VERT dès qu'une autre fig touche/pénètre ce cercle (bord-à-bord ≤ portée model).
 *  - Grand cercle centré barycentre, rayon = ``unit_global_cohesion_range`` / 2 (Ø = écart max autorisé) ;
 *    vert clair si toutes les figs tiennent dans le cercle, ROUGE dès qu'une fig en sort.
 * Conversion pouces→pixels : 1 pouce = inches_to_subhex pas, 1 pas ≈ ``√3 · hex_radius``.
 */
function drawCohesionHalos(
  overlay: PIXI.Graphics,
  p: {
    positions: Array<{ mid: string; col: number; row: number }>;
    activeModelId: string | null;
    baseSize: number;
    hexRadius: number;
    margin: number;
    inchesToSubhex: number;
    modelCohesionInches: number;
    globalCohesionInches: number;
  }
): void {
  const n = p.positions.length;
  if (n < 2) return;

  const HEX_WIDTH = 1.5 * p.hexRadius;
  const HEX_HEIGHT = Math.sqrt(3) * p.hexRadius;
  const pxPerStep = HEX_HEIGHT;
  const hexCenter = (c: number, r: number): [number, number] => [
    c * HEX_WIDTH + HEX_WIDTH / 2 + p.margin,
    r * HEX_HEIGHT + ((c % 2) * HEX_HEIGHT) / 2 + HEX_HEIGHT / 2 + p.margin,
  ];

  const baseRadiusPx = p.baseSize > 1 ? (p.baseSize * 1.5 * p.hexRadius) / 2 : p.hexRadius * 0.7;
  const modelRangePx = p.modelCohesionInches * p.inchesToSubhex * pxPerStep;
  const globalRadiusPx = (p.globalCohesionInches * p.inchesToSubhex * pxPerStep) / 2; // Ø = écart max
  const WHITE = 0xffffff;
  const GREEN = 0x22c55e;
  const LIGHT_GREEN = 0x86efac;
  const RED = 0xef4444;
  const lineW = Math.max(1.5, HEX_HEIGHT * 0.18);

  // Centres pixel ; centre du cercle = milieu des 2 figs les plus éloignées (diamètre d'étalement).
  const centers = p.positions.map((m) => hexCenter(m.col, m.row));
  let bx = centers[0][0],
    by = centers[0][1];
  let maxD2 = -1;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dx = centers[i][0] - centers[j][0];
      const dy = centers[i][1] - centers[j][1];
      const d2 = dx * dx + dy * dy;
      if (d2 > maxD2) {
        maxD2 = d2;
        bx = (centers[i][0] + centers[j][0]) / 2;
        by = (centers[i][1] + centers[j][1]) / 2;
      }
    }
  }

  // Grand cercle (2e puce) : vert clair si toutes les figs tiennent dans le cercle, rouge sinon.
  // Mesure depuis le bord de base (hex le plus proche), pas le centre — cohérent avec la 1re puce.
  const globalOk = centers.every(
    ([x, y]) => Math.hypot(x - bx, y - by) - baseRadiusPx <= globalRadiusPx
  );
  overlay.lineStyle(lineW, globalOk ? LIGHT_GREEN : RED, 0.9);
  overlay.drawCircle(bx, by, globalRadiusPx);

  // Halo model : autour de la fig active, vert si une autre fig touche/pénètre le cercle (bord-à-bord).
  const activeIdx = p.positions.findIndex((m) => m.mid === p.activeModelId);
  if (activeIdx < 0) return;
  const [acx, acy] = centers[activeIdx];
  const haloRadiusPx = baseRadiusPx + modelRangePx;
  const cohesionOk = centers.some(
    ([x, y], j) => j !== activeIdx && Math.hypot(x - acx, y - acy) <= haloRadiusPx + baseRadiusPx
  );
  overlay.lineStyle(lineW, cohesionOk ? GREEN : WHITE, 0.95);
  overlay.drawCircle(acx, acy, haloRadiusPx);
}

/**
 * Même liste que le sync ref / ``moveDestinationAnchorsFromState`` (valid_move_destinations_pool ou preview_hexes).
 * Si présente : le draw n’ajoute pas ``move_preview_footprint_zone`` dans ``availableCells`` (évite le double rendu « nid d’abeille »).
 */
function pickMoveDestinationAnchorsFromGameState(
  gameState: GameState | null | undefined
): unknown[] | undefined {
  if (!gameState) return undefined;
  const gs = gameState as GameState & { preview_hexes?: unknown };
  const v = gs.valid_move_destinations_pool;
  const p = gs.preview_hexes;
  const raw = (gameState as unknown as Record<string, unknown>).valid_move_destinations_pool;
  const rawP = (gameState as unknown as Record<string, unknown>).preview_hexes;
  const pool =
    Array.isArray(v) && v.length > 0 ? v : Array.isArray(raw) && raw.length > 0 ? raw : undefined;
  if (pool) return pool;
  if (Array.isArray(p) && p.length > 0) return p;
  if (Array.isArray(rawP) && rawP.length > 0) return rawP;
  return undefined;
}

function validateBoardOrientationStep(rawOrientation: unknown, context: string): number {
  if (
    typeof rawOrientation !== "number" ||
    !Number.isInteger(rawOrientation) ||
    rawOrientation < 0 ||
    rawOrientation > 5
  ) {
    throw new Error(
      `${context}: orientation must be an integer in 0..5, got ${String(rawOrientation)}`
    );
  }
  return rawOrientation;
}

function orientationStepForBoard(
  unit: Unit,
  unitsCache: GameState["units_cache"] | undefined
): number | undefined {
  const cacheOrientation = unitsCache?.[String(unit.id)]?.orientation;
  if (cacheOrientation !== undefined) {
    return validateBoardOrientationStep(cacheOrientation, `Unit ${unit.id} units_cache`);
  }
  if (unit.orientation !== undefined) {
    return validateBoardOrientationStep(unit.orientation, `Unit ${unit.id}`);
  }
  return undefined;
}

// Objective control map type - tracks which player controls each objective
type ObjectiveControllers = { [objectiveName: string]: number | null };

interface ReplayRules {
  primary_objective: PrimaryObjectiveRule | PrimaryObjectiveRule[] | null;
}

type Mode =
  | "select"
  | "movePreview"
  | "squadModelMove"
  | "squadModelShoot"
  | "attackPreview"
  | "targetPreview"
  | "chargeTargetSelect"
  | "chargePreview"
  | "chargeModelMove"
  | "advancePreview"
  | "pileInPreview"
  | "pileInModelMove"
  | "consolidationPreview"
  | "consolidationModelMove"
  | "deploymentMove";

/** État du mode mesure (règle dans la barre). */
export type MeasureModeState =
  | { kind: "off" }
  | { kind: "armed" }
  | {
      kind: "measuring";
      /** Premier point (1er clic gauche). La distance affichée est la somme des segments jusqu’au curseur. */
      originCol: number;
      originRow: number;
      /** Points de jonction (clic droit), dans l’ordre — le segment courant part du dernier point fixé. */
      junctions: Array<{ col: number; row: number }>;
    };

type BoardProps = {
  units: Unit[];
  selectedUnitId: number | null;
  ruleChoiceHighlightedUnitId?: number | null;
  eligibleUnitIds: number[];
  showHexCoordinates?: boolean;
  showLosDebugOverlay?: boolean;
  /** Option : afficher la LoS de tir au survol pendant le déploiement (défaut OFF — impact perf). */
  deployShootLoS?: boolean;
  onUnitIllustrationPreviewChange?: (unitId: UnitId | null) => void;
  onUnitDisplaySelectChange?: (unitId: UnitId | null) => void;
  shootingActivationQueue?: Unit[];
  activeShootingUnit?: Unit | null;
  shootingTargetId?: number | null; // For replay mode: shows explosion icon on target
  shootingUnitId?: number | null; // For replay mode: shows shooting indicator on shooter
  movingUnitId?: number | null; // For replay mode: shows boot icon on moving unit
  chargingUnitId?: number | null; // For replay mode: shows lightning icon on charging unit
  chargeTargetId?: number | null; // Cible charge (replay / après coup) + fusion avec prévisualisation
  chargePreviewTargetIds?: number[]; // V11 multi-cibles : cibles toggleées en mode chargeTargetSelect (voile violet)
  fightingUnitId?: number | null; // For replay mode: shows crossed swords icon on fighting unit
  fightTargetId?: number | null; // For replay mode: shows explosion icon on fight target
  // Charge roll display for replay mode
  chargeRoll?: number | null; // The charge roll value to display
  chargeSuccess?: boolean; // Whether the charge was successful
  // Advance roll display
  advanceRoll?: number | null;
  advancingUnitId?: number | null;
  mode: Mode;
  movePreview: { unitId: number; destCol: number; destRow: number; orientation?: number } | null;
  attackPreview: { unitId: number; col: number; row: number } | null;
  // Blinking state for multi-unit HP bars
  blinkingUnits?: number[];
  blinkingAttackerId?: number | null;
  blinkingCoverByUnitId?: Record<string, boolean>;
  /** Parallèle au cover : cibles cachées hors detection range pendant le blink de tir → œil rouge. */
  blinkingHiddenTooFarByUnitId?: Record<string, boolean>;
  blinkingLosCountByUnitId?: Record<string, number>;
  blinkingSquadAliveCount?: number;
  blinkingLosOverviewUnitId?: number | null;
  isBlinkingActive?: boolean;
  blinkVersion?: number;
  blinkState?: boolean;
  onSelectUnit: (id: number | string | null) => void;
  onSkipUnit?: (unitId: number | string) => void;
  onSkipShoot?: (unitId: number | string) => void;
  /** Phase fight + attackPreview : clic droit (``handleRightClick`` côté API). */
  onSkipFight?: (unitId: number | string) => void;
  onStartTargetPreview?: (shooterId: number | string, targetId: number | string) => void;
  onStartMovePreview: (unitId: number | string, col: number | string, row: number | string) => void;
  onDirectMove: (
    unitId: number | string,
    col: number | string,
    row: number | string,
    orientation?: number
  ) => void;
  onBumpMovePreviewOrientation?: (delta: number) => void;
  /** Move par-figurine (squad.md brique 3) — plan provisoire non committe. */
  squadMovePlan?: {
    unitId: number;
    models: Record<string, { col: number; row: number }>;
    originModels: Record<string, { col: number; row: number }>;
    activeModelId: string | null;
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    canValidate: boolean;
    wouldFlee: boolean;
  } | null;
  /** Unité dont le move en cours est un Fall Back → badge fui sur son ghost de preview. */
  fleePreviewUnitId?: number | null;
  /** Pool BFS (hexes atteignables) de la figurine en cours de repositionnement. */
  squadMoveModelPoolRef?: React.RefObject<Set<string>>;
  /** Mask loops per-fig (polygone lissé) reçus de move_model_destinations. */
  squadMoveModelMaskLoopsRef?: React.RefObject<number[][] | null>;
  onStartSquadModelMove?: (unitId: number | string) => void | Promise<void>;
  onSelectModelForMove?: (modelId: string) => void | Promise<void>;
  onMoveModelInPlan?: (modelId: string, col: number, row: number) => void;
  onResetModelInPlan?: (modelId: string) => void;
  onCommitSquadMovePlan?: () => void | Promise<void>;
  onCancelSquadMove?: () => void;
  /** Déploiement par escouade (PvP "active") — plan provisoire par-figurine. */
  deployPlan?: {
    unitId: number;
    /** ``level`` (étages) : niveau de vue capturé au drop de la fig (voir useEngineAPI). */
    models: Record<string, { col: number; row: number; level?: number }>;
    originModels: Record<string, { col: number; row: number; level?: number }>;
    activeModelId: string | null;
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    canValidate: boolean;
    placed: boolean;
    following: boolean;
  } | null;
  /** Pool de la zone de déploiement (Set "col,row") du déployeur courant. */
  deployPoolRef?: React.RefObject<Set<string>>;
  deployModelPoolRef?: React.RefObject<Set<string>>;
  deploySquadPoolRef?: React.RefObject<Set<string>>;
  onStartDeploySquad?: (unitId: number | string) => void;
  onDeployDropSquad?: (col: number, row: number) => void | Promise<void>;
  onSelectDeployModel?: (modelId: string) => void;
  onMoveDeployModelInPlan?: (modelId: string, col: number, row: number) => void;
  onSquadMoveDeploy?: (col: number, row: number) => void;
  onStartSquadFollowDeploy?: () => void;
  onFreezeSquadDeploy?: () => void;
  onCommitDeploy?: () => void | Promise<void>;
  onCancelDeploy?: () => void;
  /** Étage courant (multi-niveaux), remonté depuis BoardWithAPI. Optionnel : fallback état interne
   *  pour les autres call sites (BoardReplay, tutorial) où le déploiement à l'étage n'est pas piloté. */
  currentLevel?: number;
  onCurrentLevelChange?: (level: number) => void;
  /** Charge par-figurine (V11 11.04, Slice G) — plan provisoire des figs posées. */
  chargeMovePlan?: {
    unitId: number;
    models: Record<string, { col: number; row: number }>;
    eligibleModels: string[];
    unplaced: string[];
    activeModelId: string | null;
    currentPhase: 1 | 2 | 3;
    canValidate: boolean;
    satisfiedTargets: number[];
    unsatisfiedTargets: number[];
    engagedModels: string[];
  } | null;
  /** Pool (hexes "col,row") de la fig de charge active = eligible[activeModelId]. */
  chargeModelPoolRef?: React.RefObject<Set<string>>;
  /** Distance de mouvement (sous-hex) de la fig active vers chaque ancre de son pool "col,row" —
   * path au sol / direct en vol. Source du tooltip de charge par-figurine. */
  // A SUPPRIMER : feature distance charge par-figurine jamais fonctionnelle (lecteur inatteignable, supprimé).
  chargeModelDistancesRef?: React.RefObject<Map<string, number>>;
  /** Mask loops (polygone lissé monde) de la zone de landing de la fig de charge active. */
  chargeModelMaskLoopsRef?: React.RefObject<number[][] | null>;
  onSelectChargeModel?: (modelId: string) => void;
  onMoveModelInChargePlan?: (modelId: string, col: number, row: number) => void;
  onUnplaceChargeModel?: (modelId: string) => void;
  onCommitChargePlan?: () => void | Promise<void>;
  onCancelChargeModelMove?: () => void | Promise<void>;
  /** Mode Focus (chargeModelMove) : voile violet sur les cibles + clic cible → auto-placement. */
  chargeFocusActive?: boolean;
  onChargeFocusTargetClick?: (targetId: number) => void | Promise<void>;
  /** Pile-in par-figurine (V11 12.04, mode fin type charge) — plan provisoire des figs posées. */
  pileInMovePlan?: {
    unitId: number;
    models: Record<string, { col: number; row: number }>;
    eligibleModels: string[];
    unplaced: string[];
    activeModelId: string | null;
    canValidate: boolean;
    /** Légalité par-fig (false = posée hors zone → voile rouge). */
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    unitEngaged: boolean;
    keptEngagements: boolean;
    /** Figs posées en mesure de frapper (≤ EZ d'une cible) → voile vert. */
    engagedModels: string[];
    /** Cibles pile-in (focus) → cercle violet + hit-test. */
    pileInTargets: string[];
  } | null;
  /** Mode Focus pile-in : voile violet sur les cibles + clic cible → auto-placement. */
  pileInFocusActive?: boolean;
  /** Cible pile-in mémorisée (focus) → anneau distinct. */
  pileInFocusTargetId?: string | null;
  onPileInFocusTargetClick?: (targetId: number | string) => void | Promise<void>;
  /** Pool (hexes "col,row") de la fig de pile-in active. */
  pileInModelPoolRef?: React.RefObject<Set<string>>;
  /** Mask loops (polygone lissé monde) de la zone de landing de la fig de pile-in active. */
  pileInModelMaskLoopsRef?: React.RefObject<number[][] | null>;
  onSelectPileInModel?: (modelId: string) => void;
  onMovePileInModel?: (modelId: string, col: number, row: number) => void;
  onUnplacePileInModel?: (modelId: string) => void;
  onCommitPileInPlan?: () => void | Promise<void>;
  onCancelPileInModelMove?: () => void | Promise<void>;
  /** Consolidation par-figurine (V11 12.08, miroir pile-in, cascade 3 modes). */
  consolidationMovePlan?: {
    unitId: number;
    models: Record<string, { col: number; row: number }>;
    eligibleModels: string[];
    unplaced: string[];
    activeModelId: string | null;
    canValidate: boolean;
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    unitEngaged: boolean;
    keptEngagements: boolean;
    engagedWithAllSelected: boolean;
    withinObjectiveRange: boolean;
    engagedModels: string[];
    consolidationMode: string | null;
    engagingCandidates: string[];
    objectiveCandidates: string[];
    consolidationTargets: string[];
    awaitingTargetSelection: boolean;
    awaitingObjectiveSelection: boolean;
  } | null;
  consolidationModelPoolRef?: React.RefObject<Set<string>>;
  consolidationModelMaskLoopsRef?: React.RefObject<number[][] | null>;
  consolidationNewFoes?: string[];
  onSelectConsolidationModel?: (modelId: string) => void;
  onMoveConsolidationModel?: (modelId: string, col: number, row: number) => void;
  onUnplaceConsolidationModel?: (modelId: string) => void;
  onCommitConsolidationPlan?: () => void | Promise<void>;
  onCancelConsolidationModelMove?: () => void | Promise<void>;
  onEndConsolidation?: () => void | Promise<void>;
  onConsolidationSelectTarget?: (targetId: number | string) => void | Promise<void>;
  onConsolidationSelectObjective?: (objectiveId: number | string) => void | Promise<void>;
  /** Tir par-figurine (PvP manuel). */
  squadShootPlan?: {
    unitId: number;
    models: string[];
    targets: Record<string, string>;
    declarations: Array<{ model_id: string; weapon_index: number; target_unit_id: string }>;
    activeModelId: string | null;
    activeWeaponIndex: number | null;
    activeWeaponCode: string | null;
    canValidate: boolean;
  } | null;
  onStartSquadModelShoot?: (
    unitId: number | string,
    initialModelId?: string
  ) => void | Promise<void>;
  onSelectModelForShoot?: (modelId: string) => void | Promise<void>;
  onSquadShootLosOverview?: (unitId: number) => void | Promise<void>;
  onAssignShootTarget?: (targetUnitId: number | string) => void | Promise<void>;
  onAutoAssignAllModels?: (targetUnitId: number | string) => void | Promise<void>;
  onUnassignShootModel?: (modelId: string) => void | Promise<void>;
  onUnassignShootWeapon?: (weaponIndex: number) => void | Promise<void>;
  onCommitSquadShoot?: () => void | Promise<void>;
  onCancelSquadShoot?: () => void | Promise<void>;
  /** Combat par-figurine (PvP manuel). */
  squadFightPlan?: {
    unitId: number;
    models: string[];
    targets: Record<string, string>;
    declarations: Array<{ model_id: string; weapon_index: number; target_unit_id: string }>;
    activeModelId: string | null;
    activeWeaponIndex: number | null;
    canValidate: boolean;
  } | null;
  onSelectModelForFight?: (modelId: string) => void;
  onAssignFightTarget?: (targetUnitId: number | string) => void | Promise<void>;
  onAssignFightWeapon?: (targetUnitId: number | string) => void | Promise<void>;
  /** Flux cible-d'abord combat : Valider/Annuler du menu d'armes (jumeaux tir). */
  onCommitSquadFight?: () => void | Promise<void>;
  onCancelSquadFight?: () => void | Promise<void>;
  /** Remonte le nombre de figs ASSIGNABLES (engagées) de l'unité active → décompte barre. */
  onReportFightAssignable?: (count: number) => void;
  /** Allocation manuelle des pertes au tir (defenseur humain) : figs choisissables. */
  manualAllocation?: {
    kind?: "shoot" | "fight" | "hazard";
    attacker_unit_id: string;
    target_unit_id: string;
    defender_player: number;
    choices: Array<{ model_id: string; col: number; row: number; HP_CUR: number; HP_MAX: number }>;
    wounds_remaining: number;
  } | null;
  onAllocateModel?: (modelId: string) => void | Promise<void>;
  onStartAttackPreview: (unitId: number, col: number, row: number) => void;
  onConfirmMove: () => void;
  onCancelMove: () => void;
  onShoot: (shooterId: number, targetId: number) => void;
  onDeployUnit?: (unitId: number | string, destCol: number, destRow: number) => void;
  onFightAttack?: (attackerId: number, targetId: number | null) => void;
  onActivateFight?: (fighterId: number) => void;
  onPileInMove?: (unitId: number, destCol: number, destRow: number) => void;
  onSkipPileIn?: () => void;
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
  /** TEST/DEBUG : mode « battle-shock test ». Quand ON, un clic DROIT sur n'importe quelle unité
   * (toutes phases, tous players) force un battle-shock roll au lieu de l'action normale. */
  battleShockTestMode?: boolean;
  onForceBattleShock?: (unitId: number | string) => void | Promise<void>;
  /** TEST/DEBUG : mode « a chargé test ». Quand ON, un clic DROIT force le statut « a chargé »
   * (uniquement en phase charge). Cumulable avec le bs test : un clic droit applique les deux. */
  chargedTestMode?: boolean;
  onForceCharged?: (unitId: number | string) => void | Promise<void>;
  shootingPhaseState?: ShootingPhaseState;
  targetPreview?: TargetPreview | null;
  onCancelTargetPreview?: () => void;
  gameState: GameState; // Add gameState prop
  chargeRollPopup?: { unitId: number; roll: number; tooLow: boolean; timestamp: number } | null;
  getChargeDestinations: (unitId: number) => { col: number; row: number }[];
  /** Union empreintes valides (API) — pastilles violettes autour de la zone d’engagement cible. */
  chargePreviewOverlayHexes?: Array<{ col: number; row: number }>;
  /** Hex de référence portée (API ``charge_reference_hex``) — ne pas recalculer côté client. */
  chargeReferenceHex?: { col: number; row: number } | null;
  moveDestPoolRef?: React.RefObject<Set<string>>;
  footprintZoneRef?: React.RefObject<Set<string>>;
  /** Boucles masque monde (API) — hit-test si ``footprintZoneRef`` vide. */
  footprintMaskLoopsRef?: React.RefObject<number[][] | null>;
  /** Sélection déplacement après tir — même sync de pools que phase move (voir charge : refs avant draw). */
  pendingMoveAfterShooting?: boolean;
  /** Requête ``activate_unit`` en cours — curseur attente sur le plateau. */
  activationPendingUnitId?: number | null;
  /** Phase charge : ancres valides + zone violette (empreinte) pour l’icône sous le curseur. */
  chargeDestPoolRef?: React.RefObject<Set<string>>;
  /** Distance de mouvement réelle (sous-hex) par ancre "col,row" — path au sol / direct en vol.
   * Source du tooltip de charge (au lieu de la distance à vol d'oiseau, qui sous-estime les détours). */
  chargeDestDistancesRef?: React.RefObject<Map<string, number>>;
  chargeFootprintZoneRef?: React.RefObject<Set<string>>;
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
  boardConfigOverride?: {
    cols: number;
    rows: number;
    hex_radius: number;
    margin: number;
    inches_to_subhex: number;
  };
  wallHexesOverride?: Array<{ col: number; row: number }>; // For replay mode: override walls from log
  availableCellsOverride?: Array<{ col: number; row: number }>; // Replay / pile in : surbrillance des hexes disponibles
  deploymentState?: GameState["deployment_state"];
  objectivesOverride?: Array<{ name: string; hexes: Array<{ col: number; row: number }> }>; // For replay mode: override objectives from log
  objectiveControlOverride?: Record<string, number | null>; // For replay mode: pre-computed objective control (bypasses sticky-ref heuristic)
  replayActionIndex?: number; // For replay mode: detect rollback and reset objective control
  autoSelectWeapon?: boolean;
  hpBarPerModel?: boolean; // true → barre HP par figurine ; false → une barre par escouade (hors characters)
  hpBarBlinkEnlarged?: boolean; // true → grossit ×1.5 la barre HP des cibles blink / preview ; false → taille normale
  showWoundProbability?: boolean; // true → affiche le % de blessure au-dessus des cibles blink ; false → masqué
  statusBadgePerModel?: boolean; // true → badge de statut (caché/fui/choc) par figurine ; false → un seul badge si toute l'escouade a le statut
  boardDisplayMode?: BoardDisplayMode; // "full" → pleine taille, la page scrolle ; "fit" → réduit pour tenir dans l'écran ; "window" → taille réelle dans une fenêtre limitée à l'écran, navigable (molette/scroll)
  /** Mode mesure (règle) : armed → 1er clic pose l’ancre ; clic droit = jonction ; 2e clic termine la ligne → armed. Sortie : bouton règle uniquement. */
  measureMode?: MeasureModeState;
  onMeasureHexCommit?: (col: number, row: number) => void;
  /** Pendant `measuring` : clic droit sur un hex ajoute une jonction et poursuit la mesure depuis ce hex. */
  onMeasureJunctionCommit?: (col: number, row: number) => void;
  /** true → masque tous les indicateurs autour des icônes (HP, badges, cercle vert, voiles, tooltips). Les icônes restent visibles. */
  hideIndicators?: boolean;
};

/** Échelle affichage tooltip mouvement : nombre de pas hex entre centres pour 1″ (règle plateau). */
const HEX_STEPS_PER_INCH_DISPLAY = 10;
/** Au-dessus de tout le reste du stage (unités 2000, drag 9000, UI / popups ~10000). */
const MEASURE_GUIDE_LINE_Z_INDEX = 15000;
const BOARD_ZOOM_DEFAULT = 1;
// Marge verticale (px) réservée autour du board en mode « adapter à l'écran » — alignée sur le
// ``calc(100vh - 40px)`` du viewport scrollable.
const BOARD_FIT_VERTICAL_MARGIN = 40;
// Mode d'affichage du board : "full" → pleine taille, la page scrolle ; "fit" → réduit pour tenir
// entièrement dans l'écran ; "window" → taille réelle dans une fenêtre limitée à l'écran, navigable.
export type BoardDisplayMode = "full" | "fit" | "window";
const BOARD_ZOOM_MIN = 0.5;
const BOARD_ZOOM_MAX = 2.5;
const BOARD_ZOOM_SLIDER_STEP = 0.05;
const BOARD_ZOOM_WHEEL_IN_FACTOR = 1.1;
const BOARD_ZOOM_WHEEL_OUT_FACTOR = 1 / BOARD_ZOOM_WHEEL_IN_FACTOR;
const UNIT_ILLUSTRATION_HOVER_DELAY_MS = 100;

const WEAPON_COLOR_PALETTE = [
  0x22c55e, // vert
  0xeab308, // jaune
  0x3b82f6, // bleu
  0xf97316, // orange
  0xa855f7, // violet
  0x06b6d4, // cyan
];

/** Couleur d'une arme (pastille/voile/ligne). Les profils d'une même arme combinée
 *  (même COMBI_WEAPON) partagent la couleur du 1er profil du groupe. */
function weaponColorFor(
  rngWeapons: ReadonlyArray<{ COMBI_WEAPON?: string }> | undefined,
  weaponIndex: number
): number {
  let colorKey = weaponIndex;
  const w = rngWeapons?.[weaponIndex];
  if (w?.COMBI_WEAPON) {
    const first = rngWeapons!.findIndex((rw) => rw?.COMBI_WEAPON === w.COMBI_WEAPON);
    if (first >= 0) colorKey = first;
  }
  return WEAPON_COLOR_PALETTE[colorKey % WEAPON_COLOR_PALETTE.length]!;
}

function clampBoardZoom(value: number): number {
  return Math.min(BOARD_ZOOM_MAX, Math.max(BOARD_ZOOM_MIN, value));
}

/** Empreintes depuis ``units_cache`` (API) pour aligner l’UI sur le moteur (charge : hex le plus proche de la cible). */
function parseOccupiedHexesFromCacheEntry(entry: unknown): Array<{ col: number; row: number }> {
  if (!entry || typeof entry !== "object") return [];
  const occ = (entry as { occupied_hexes?: unknown }).occupied_hexes;
  if (!Array.isArray(occ) || occ.length === 0) return [];
  const out: Array<{ col: number; row: number }> = [];
  for (const x of occ) {
    if (Array.isArray(x) && x.length >= 2) {
      out.push({ col: Number(x[0]), row: Number(x[1]) });
    }
  }
  return out;
}

/** Même logique que ``_charge_closest_charger_hex_to_target`` (charge_handlers.py). */
function closestChargerHexToTargetFootprint(
  chargerCacheEntry: unknown,
  targetCacheEntry: unknown,
  fallbackCharger: { col: number; row: number },
  fallbackTarget: { col: number; row: number }
): { col: number; row: number } {
  let ch = parseOccupiedHexesFromCacheEntry(chargerCacheEntry);
  if (ch.length === 0) ch = [{ col: fallbackCharger.col, row: fallbackCharger.row }];
  let ta = parseOccupiedHexesFromCacheEntry(targetCacheEntry);
  if (ta.length === 0) ta = [{ col: fallbackTarget.col, row: fallbackTarget.row }];
  let best = ch[0]!;
  let bestD = Infinity;
  for (const h of ch) {
    for (const t of ta) {
      const d = hexDistOff(h.col, h.row, t.col, t.row);
      if (d < bestD) {
        bestD = d;
        best = h;
      }
    }
  }
  return best;
}

/**
 * Blink / prévisualisation tir : vivant = présent dans units_cache (si fourni) ET HP > 0
 * (units + cache) pour retirer tout de suite une cible tuée même si le state React des ids
 * de blink n’a pas été resynchronisé.
 */
/** PV pour fingerprint / layout : le moteur écrit surtout dans ``units_cache`` (tir, combat). */
function hpCurForBoardFingerprint(
  unit: Unit,
  unitsCache: Record<string, unknown> | undefined
): number {
  if (!unitsCache) {
    if (unit.HP_CUR == null) throw new Error(`Unit ${unit.id} missing HP_CUR`);
    return unit.HP_CUR;
  }
  const raw = unitsCache[String(unit.id)];
  if (raw && typeof raw === "object" && raw !== null && "HP_CUR" in raw) {
    const hp = (raw as { HP_CUR: unknown }).HP_CUR;
    if (typeof hp === "number") return hp;
  }
  if (unit.HP_CUR == null) throw new Error(`Unit ${unit.id} missing HP_CUR`);
  return unit.HP_CUR;
}

/** Fusionne ``HP_CUR`` depuis ``units_cache`` pour l’affichage (barres HP, blink, etc.). */
function mergeUnitHpFromCache(unit: Unit, unitsCache: Record<string, unknown> | undefined): Unit {
  if (!unitsCache) return unit;
  const raw = unitsCache[String(unit.id)];
  if (!raw || typeof raw !== "object" || raw === null || !("HP_CUR" in raw)) {
    return unit;
  }
  const hp = (raw as { HP_CUR: unknown }).HP_CUR;
  if (typeof hp !== "number") return unit;
  if (hp === unit.HP_CUR) return unit;
  return { ...unit, HP_CUR: hp };
}

function filterBlinkIdsToLivingUnitsCache(
  ids: number[],
  unitsCache: Record<string, unknown> | undefined,
  units?: Unit[]
): number[] {
  return ids.filter((id) => {
    const idStr = String(id);
    if (unitsCache !== undefined) {
      if (!Object.hasOwn(unitsCache, idStr)) {
        return false;
      }
      const raw = unitsCache[idStr];
      if (raw && typeof raw === "object" && raw !== null && "HP_CUR" in raw) {
        const hp = (raw as { HP_CUR: unknown }).HP_CUR;
        if (typeof hp === "number" && hp <= 0) {
          return false;
        }
      }
      return true;
    }
    const u = units?.find((unit) => String(unit.id) === idStr);
    if (u !== undefined && (u.HP_CUR ?? 0) <= 0) {
      return false;
    }
    return true;
  });
}

/** Barres blink sur app.stage : sans ça, une cible absente du cache n’est plus rendue mais le container survit au teardown du stage. */
function destroyAndFilterOrphanHpBlinkContainers(
  savedBlinks: PIXI.DisplayObject[],
  unitsCache: Record<string, unknown> | undefined
): PIXI.DisplayObject[] {
  if (unitsCache === undefined) {
    return savedBlinks;
  }
  const kept: PIXI.DisplayObject[] = [];
  for (const blink of savedBlinks) {
    const bc = blink as HPBlinkContainer;
    const uid = bc.unitId;
    if (uid !== undefined && uid !== null && !Object.hasOwn(unitsCache, String(uid))) {
      if (bc.cleanupBlink) bc.cleanupBlink();
      blink.destroy({ children: true });
      continue;
    }
    kept.push(blink);
  }
  return kept;
}

/** Lit une couleur hex (#rrggbb) depuis une variable CSS de :root et la convertit en number PIXI.
 *  Pas de fallback : variable absente/invalide → erreur explicite. */
function cssColorToNumber(variableName: string): number {
  const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
  if (value === "") {
    throw new Error(`CSS variable ${variableName} not found or empty`);
  }
  const parsed = parseInt(value.replace("#", ""), 16);
  if (Number.isNaN(parsed)) {
    throw new Error(`CSS variable ${variableName} is not a hex color: ${value}`);
  }
  return parsed;
}

interface TargetRingCtx {
  units: Unit[];
  unitsCache?: Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>;
  hexCenter: (c: number, r: number) => [number, number];
  hexRadius: number;
  lineW: number;
}

/** Dessine un anneau (contour) autour de chaque figurine d'une unité cible (occupied_hexes_by_model).
 *  Source unique partagée par les cibles blink (tir/charge/fight), pile-in et consolidation. */
function drawUnitTargetRing(
  overlay: PIXI.Graphics,
  uid: number | string,
  color: number,
  ctx: TargetRingCtx,
  fillAlpha?: number
): void {
  const tu = ctx.units.find((u) => String(u.id) === String(uid));
  if (!tu) return;
  const tBase = resolveBaseSizeForUnitDisplay(tu);
  const tR = tBase > 1 ? (tBase * 1.5 * ctx.hexRadius) / 2 : ctx.hexRadius * 0.7;
  const tByModel = ctx.unitsCache?.[String(uid)]?.occupied_hexes_by_model;
  if (!tByModel) return;
  for (const [c, r] of Object.values(tByModel)) {
    const [cx, cy] = ctx.hexCenter(c, r);
    overlay.lineStyle(Math.max(3, ctx.lineW), color, 1);
    if (fillAlpha != null) overlay.beginFill(color, fillAlpha);
    overlay.drawCircle(cx, cy, tR + 3);
    if (fillAlpha != null) overlay.endFill();
  }
}

/**
 * Zone hexes are served as [col,row] tuples (like wall_hexes) though typed as {col,row};
 * normalize both forms (same as BoardWithAPI objective normalization). Module-scope → stable ref.
 */
function normalizeZoneHex(h: unknown): [number, number] {
  return Array.isArray(h)
    ? [h[0] as number, h[1] as number]
    : [(h as { col: number }).col, (h as { row: number }).row];
}

export default function Board({
  units,
  currentLevel: currentLevelProp,
  onCurrentLevelChange,
  selectedUnitId,
  ruleChoiceHighlightedUnitId = null,
  eligibleUnitIds,
  showHexCoordinates = false,
  showLosDebugOverlay = false,
  deployShootLoS = false,
  onUnitIllustrationPreviewChange,
  onUnitDisplaySelectChange,
  shootingActivationQueue,
  activeShootingUnit,
  shootingTargetId,
  shootingUnitId,
  movingUnitId,
  chargingUnitId,
  chargeTargetId,
  chargePreviewTargetIds,
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
  blinkingCoverByUnitId,
  blinkingHiddenTooFarByUnitId,
  blinkingLosCountByUnitId,
  blinkingSquadAliveCount,
  blinkingLosOverviewUnitId,
  isBlinkingActive,
  blinkVersion,
  onSelectUnit,
  onSkipUnit,
  onStartMovePreview,
  onDirectMove,
  onBumpMovePreviewOrientation,
  squadMovePlan = null,
  fleePreviewUnitId = null,
  squadMoveModelPoolRef,
  squadMoveModelMaskLoopsRef,
  onStartSquadModelMove,
  onSelectModelForMove,
  onMoveModelInPlan,
  onResetModelInPlan,
  onCommitSquadMovePlan,
  onCancelSquadMove,
  deployPlan = null,
  deployPoolRef,
  deployModelPoolRef,
  deploySquadPoolRef,
  onDeployDropSquad,
  onSelectDeployModel,
  onMoveDeployModelInPlan,
  onSquadMoveDeploy,
  onStartSquadFollowDeploy,
  onFreezeSquadDeploy,
  chargeMovePlan = null,
  chargeModelPoolRef,
  chargeModelMaskLoopsRef,
  onSelectChargeModel,
  onMoveModelInChargePlan,
  onUnplaceChargeModel,
  onCancelChargeModelMove,
  chargeFocusActive = false,
  onChargeFocusTargetClick,
  pileInMovePlan = null,
  pileInFocusActive = false,
  pileInFocusTargetId = null,
  onPileInFocusTargetClick,
  pileInModelPoolRef,
  pileInModelMaskLoopsRef,
  onSelectPileInModel,
  onMovePileInModel,
  onUnplacePileInModel,
  onCancelPileInModelMove,
  consolidationMovePlan = null,
  consolidationModelPoolRef,
  consolidationModelMaskLoopsRef,
  onSelectConsolidationModel,
  onMoveConsolidationModel,
  onUnplaceConsolidationModel,
  onCancelConsolidationModelMove,
  onConsolidationSelectTarget,
  onConsolidationSelectObjective,
  squadShootPlan = null,
  onStartSquadModelShoot,
  onSelectModelForShoot,
  onSquadShootLosOverview,
  onAssignShootTarget,
  onAutoAssignAllModels,
  onUnassignShootModel,
  onCommitSquadShoot,
  onCancelSquadShoot,
  squadFightPlan = null,
  onSelectModelForFight,
  onAssignFightTarget,
  onAssignFightWeapon,
  onCommitSquadFight,
  onCancelSquadFight,
  onReportFightAssignable,
  manualAllocation = null,
  onAllocateModel,
  onStartAttackPreview,
  onConfirmMove,
  onCancelMove,
  current_player,
  unitsMoved,
  phase,
  onShoot,
  onDeployUnit,
  onFightAttack,
  onSkipFight,
  onActivateFight,
  onPileInMove,
  onSkipPileIn,
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
  battleShockTestMode,
  onForceBattleShock,
  chargedTestMode,
  onForceCharged,
  targetPreview,
  onCancelTargetPreview,
  gameState,
  chargeRollPopup,
  getChargeDestinations,
  chargePreviewOverlayHexes = [],
  chargeReferenceHex = null,
  moveDestPoolRef,
  footprintZoneRef,
  footprintMaskLoopsRef,
  pendingMoveAfterShooting = false,
  activationPendingUnitId = null,
  chargeDestPoolRef,
  chargeDestDistancesRef,
  chargeFootprintZoneRef,
  onAdvance,
  onAdvanceMove,
  onCancelAdvance,
  getAdvanceDestinations,
  advanceWarningPopup: _advanceWarningPopup,
  onConfirmAdvanceWarning: _onConfirmAdvanceWarning,
  onCancelAdvanceWarning: _onCancelAdvanceWarning,
  onSkipAdvanceWarning: _onSkipAdvanceWarning,
  showAdvanceWarningPopup: _showAdvanceWarningPopup = false,
  hideAdvanceIconForTutorial = false,
  boardConfigOverride,
  wallHexesOverride,
  availableCellsOverride,
  deploymentState,
  objectivesOverride,
  objectiveControlOverride,
  replayActionIndex,
  autoSelectWeapon,
  hpBarPerModel,
  hpBarBlinkEnlarged,
  showWoundProbability,
  statusBadgePerModel,
  boardDisplayMode = "full",
  measureMode = { kind: "off" },
  onMeasureHexCommit,
  onMeasureJunctionCommit,
  hideIndicators = false,
}: BoardProps) {
  /** Aligné sur drawBoard / ``boardHexClick`` (command & déploiement → move). */
  const effectivePhase = phase === "command" || phase === "deployment" ? "move" : phase;

  React.useEffect(() => {}, []);

  React.useEffect(() => {}, []);

  /** Recalcul preview tir WASM après chargement du module (``isWasmReady`` n’est pas réactif). */
  const [_wasmLosReadyVersion, setWasmLosReadyVersion] = useState(0);
  useEffect(() => {
    void ensureWasmLoaded().then(() => {
      setWasmLosReadyVersion((v) => v + 1);
    });
  }, []);

  // ✅ HOOK 1: useRef - ALWAYS called first
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const boardViewportRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const boardPanStartRef = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    scrollLeft: number;
    scrollTop: number;
  } | null>(null);
  const boardZoomAnchorClientRef = useRef<{ x: number; y: number } | null>(null);
  /** Replay / Board sans API : même ref que ``moveDestPoolRef`` passée par ``useEngineAPI``. */
  const internalMoveDestPoolRef = useRef<Set<string>>(new Set());
  const resolvedMoveDestPoolRef = moveDestPoolRef ?? internalMoveDestPoolRef;

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
  /** Dernier conteneur ``highlights`` — réutilisé si l’empreinte structure est inchangée (patch move preview ou skip drawBoard). */
  const highlightsLayerRef = useRef<PIXI.Container | null>(null);
  const lastHighlightsStructuralKeyRef = useRef<string>("");
  const lastMovePolygonCacheKeyRef = useRef<string>("");
  const unitsLayerRef = useRef<PIXI.Container | null>(null);
  // Ghost de destination du move preview (collé à la souris) : rendu dans son propre layer
  // au-dessus des barres HP (20000) et des logos (10000) des autres unités.
  const movePreviewGhostLayerRef = useRef<PIXI.Container | null>(null);
  const unitsFingerprintRef = useRef<string>("");
  // Hover preview: imperative PIXI layers (no React re-render)
  const hoverOverlayRef = useRef<PIXI.Container | null>(null);
  const hoverSpriteRef = useRef<PIXI.Container | null>(null);
  const squadMoveVeilOverlayRef = useRef<PIXI.Graphics | null>(null);
  const manualAllocOverlayRef = useRef<PIXI.Graphics | null>(null);
  /** Slice G : overlay voile violet des figs éligibles en chargeModelMove (préservé au redraw). */
  const chargeModelVeilOverlayRef = useRef<PIXI.Graphics | null>(null);
  const shootSubgroupOverlayRef = useRef<PIXI.Graphics | null>(null);
  const blinkTargetRingOverlayRef = useRef<PIXI.Graphics | null>(null);
  /** Halos de cohésion (charge/pile-in/consolidation) redessinés au survol — suivent la fig active. */
  const cohesionHaloOverlayRef = useRef<PIXI.Graphics | null>(null);
  /** Ligne départ → pointeur + libellé distance hex (preview move) */
  const movePreviewGuideLineRef = useRef<PIXI.Graphics | null>(null);
  const hoverMoveOrientationStepRef = useRef<number | null>(null);
  /** Ligne mesure règle (ancre → hex sous curseur) */
  const measureGuideLineRef = useRef<PIXI.Graphics | null>(null);
  /** Timestamp d'entrée en squadModelMove depuis movePreview — bloque onPointerDownSelect pour le clic de confirmation */
  const squadMoveEntryTimeRef = useRef<number | null>(null);
  /** Double-click détecté manuellement dans onEntryPointerDown : { unitId, ts } du dernier clic sur une unité */
  const lastUnitClickRef = useRef<{ unitId: number | string; ts: number } | null>(null);
  /** Timestamp du dernier dispatch de boardUnitDoubleClick depuis onEntryPointerDown — pour supprimer le dblclick natif redondant */
  const dblClickFromEntryRef = useRef<number>(0);
  /** Déploiement : timestamp du dernier clic, pour ignorer le 2e clic d'un double-clic (qui sert à
   *  activer le suivi squad) et éviter une pose/sélection fig parasite. */
  const lastDeployClickTimeRef = useRef<number>(0);
  /** Déploiement : sélection per-fig DIFFÉRÉE (désambiguïsation simple/double clic). Un double-clic
   *  annule ce timer avant qu'il ne sélectionne → pas de flash de LoS per-fig. */
  const deploySelectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Dernier clientX/clientY pendant la mesure — pour redessiner après un setState (ex. jonction) sans attendre mousemove. */
  const measurePointerClientRef = useRef<{ clientX: number; clientY: number } | null>(null);
  /** Toujours à jour : permet aux handlers (effet stable) de lire l’état courant sans redémonter l’effet à chaque jonction. */
  const measureModeRef = useRef(measureMode);
  measureModeRef.current = measureMode;
  /** Redessin ligne mesure — défini tant que l’effet « mesure » est monté (pas de cleanup quand seules les jonctions changent). */
  const measureLineRedrawRef = useRef<((clientX: number, clientY: number) => void) | null>(null);
  const hoveredHexRef = useRef<{ col: number; row: number } | null>(null);
  /** Contexte actif quand hoveredHexRef a été mis à jour — pour invalider la restauration si le contexte change. */
  const hoveredHexContextRef = useRef<{
    mode: string;
    unitId: number | null;
    modelId?: string | null;
  } | null>(null);
  const losHexRef = useRef<{ col: number; row: number } | null>(null);
  const movePreviewBackendLosCacheRef = useRef<Map<string, BackendMoveLosPreviewPayload>>(
    new Map()
  );

  // ✅ HOOK 2: useGameConfig - ALWAYS called second
  const { boardConfig: _boardConfigFromHook, gameConfig, loading, error } = useGameConfig();
  const _rawBoardConfig =
    boardConfigOverride && _boardConfigFromHook
      ? { ..._boardConfigFromHook, ...boardConfigOverride }
      : _boardConfigFromHook;
  const boardConfig = (() => {
    if (!_rawBoardConfig) return _rawBoardConfig;
    const ds = (_rawBoardConfig.display as { display_scale?: number } | undefined)?.display_scale;
    if (!ds || ds === 1) return _rawBoardConfig;
    return { ..._rawBoardConfig, hex_radius: _rawBoardConfig.hex_radius * ds };
  })();
  // LoS cone terrain data (rule 13.10), extracted once from the static board terrain_zones (subhex,
  // same grid as wall_hexes). obscuring → sight-line blockers ; all zones → cover classification.
  // Absent terrain_zones → [] (cone falls back to walls-only, no silent masking of a real error).
  const losObscuringZones = useMemo<Array<{ hexes: Array<[number, number]> }>>(() => {
    const zones = boardConfig?.terrain_zones;
    if (!zones) return [];
    return zones
      .filter((z) => z.obscuring === true)
      .map((z) => ({ hexes: z.hexes.map(normalizeZoneHex) }));
  }, [boardConfig?.terrain_zones]);
  const losTerrainZones = useMemo<Array<{ hexes: Array<[number, number]> }>>(() => {
    const zones = boardConfig?.terrain_zones;
    if (!zones) return [];
    return zones.map((z) => ({ hexes: z.hexes.map(normalizeZoneHex) }));
  }, [boardConfig?.terrain_zones]);
  // ✅ STABLE CALLBACK REFS - Don't change on every render
  const stableCallbacks = useRef<{
    onSelectUnit: (id: number | string | null) => void;
    onSkipUnit?: (unitId: number | string) => void;
    onStartMovePreview: (
      unitId: number | string,
      col: number | string,
      row: number | string
    ) => void;
    onDirectMove: (
      unitId: number | string,
      col: number | string,
      row: number | string,
      orientation?: number
    ) => void;
    onBumpMovePreviewOrientation?: (delta: number) => void;
    onStartAttackPreview: (unitId: number, col: number, row: number) => void;
    onConfirmMove: () => void;
    onCancelMove: () => void;
    onShoot: (shooterId: number, targetId: number) => void;
    onDeployUnit?: (unitId: number | string, destCol: number, destRow: number) => void;
    onFightAttack?: (attackerId: number, targetId: number | null) => void;
    onSkipFight?: (unitId: number | string) => void;
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
    onPileInMove?: (unitId: number, destCol: number, destRow: number) => void;
    onSkipPileIn?: () => void;
  }>({
    onSelectUnit,
    onStartMovePreview,
    onDirectMove,
    onBumpMovePreviewOrientation,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onDeployUnit,
    onFightAttack,
    onSkipFight,
    onCharge,
    onActivateCharge,
    onChargeEnemyUnit,
    onMoveCharger,
    onCancelCharge,
    onCancelAdvance,
    onAdvanceMove,
    onValidateCharge,
    onLogChargeRoll,
    onPileInMove,
    onSkipPileIn,
  });

  /** Callbacks move par-figurine (squad.md brique 3) — ref toujours a jour pour les handlers d'event stables. */
  const squadMoveCallbacksRef = useRef({
    onStartSquadModelMove,
    onSelectModelForMove,
    onMoveModelInPlan,
    onResetModelInPlan,
    onCommitSquadMovePlan,
    onCancelSquadMove,
  });
  squadMoveCallbacksRef.current = {
    onStartSquadModelMove,
    onSelectModelForMove,
    onMoveModelInPlan,
    onResetModelInPlan,
    onCommitSquadMovePlan,
    onCancelSquadMove,
  };
  /** Callbacks charge par-figurine — ref a jour pour les handlers d'event stables (Slice G). */
  const chargeModelCallbacksRef = useRef({
    onMoveModelInChargePlan,
    onCancelChargeModelMove,
    onChargeFocusTargetClick,
  });
  chargeModelCallbacksRef.current = {
    onMoveModelInChargePlan,
    onCancelChargeModelMove,
    onChargeFocusTargetClick,
  };
  /** Callbacks pile-in par-figurine — ref a jour (miroir charge). */
  const pileInModelCallbacksRef = useRef({
    onMovePileInModel,
    onCancelPileInModelMove,
    onPileInFocusTargetClick,
  });
  pileInModelCallbacksRef.current = {
    onMovePileInModel,
    onCancelPileInModelMove,
    onPileInFocusTargetClick,
  };
  /** Callbacks consolidation par-figurine — ref à jour (miroir pile-in). */
  const consolidationModelCallbacksRef = useRef({
    onMoveConsolidationModel,
    onCancelConsolidationModelMove,
    onConsolidationSelectTarget,
    onConsolidationSelectObjective,
  });
  consolidationModelCallbacksRef.current = {
    onMoveConsolidationModel,
    onCancelConsolidationModelMove,
    onConsolidationSelectTarget,
    onConsolidationSelectObjective,
  };
  /** Plan provisoire toujours a jour pour les handlers d'event stables (sans relancer le draw). */
  const squadMovePlanRef = useRef(squadMovePlan);
  squadMovePlanRef.current = squadMovePlan;

  /** Callbacks de déploiement par escouade — ref toujours à jour pour les handlers d'event stables. */
  const deployCallbacksRef = useRef({
    onDeployDropSquad,
    onSelectDeployModel,
    onMoveDeployModelInPlan,
    onSquadMoveDeploy,
    onStartSquadFollowDeploy,
    onFreezeSquadDeploy,
  });
  deployCallbacksRef.current = {
    onDeployDropSquad,
    onSelectDeployModel,
    onMoveDeployModelInPlan,
    onSquadMoveDeploy,
    onStartSquadFollowDeploy,
    onFreezeSquadDeploy,
  };

  // ──────────────────────────────────────────────────────────────────────────
  // Slice G : la machinerie per-modèle (hover/pool/pose/sélection) est partagée entre le move
  // (squadModelMove) et les modes « charge-like » (charge + pile-in : pose/dé-pose/sélection d'une
  // fig dans un pool). On route le plan/pool/mask/callbacks du mode charge-like actif, puis on expose
  // une vue "squad-shaped" + des alias ``effectivePerModel*`` pour réutiliser ces handlers PIXI.
  // ──────────────────────────────────────────────────────────────────────────
  /** Modes « charge-like » : pose/dé-pose d'une fig dans un pool (charge / pile-in / consolidation). */
  const isPileInModelMove = mode === "pileInModelMove";
  const isConsolidationModelMove = mode === "consolidationModelMove";
  const perModelChargeLike =
    mode === "chargeModelMove" || isPileInModelMove || isConsolidationModelMove;
  /** Plan source brut du mode charge-like actif. */
  const activeChargeLikePlan = isPileInModelMove
    ? pileInMovePlan
    : isConsolidationModelMove
      ? consolidationMovePlan
      : chargeMovePlan;
  /** Pool de la fig active du mode charge-like actif. */
  const activeChargeLikePoolRef = isPileInModelMove
    ? pileInModelPoolRef
    : isConsolidationModelMove
      ? consolidationModelPoolRef
      : chargeModelPoolRef;
  /** Mask loops de la zone de landing du mode charge-like actif. */
  const activeChargeLikeMaskLoopsRef = isPileInModelMove
    ? pileInModelMaskLoopsRef
    : isConsolidationModelMove
      ? consolidationModelMaskLoopsRef
      : chargeModelMaskLoopsRef;
  /** Callbacks select/unplace du mode charge-like actif (le move/cancel passent par les refs). */
  const activeChargeLikeSelect = isPileInModelMove
    ? onSelectPileInModel
    : isConsolidationModelMove
      ? onSelectConsolidationModel
      : onSelectChargeModel;
  const activeChargeLikeUnplace = isPileInModelMove
    ? onUnplacePileInModel
    : isConsolidationModelMove
      ? onUnplaceConsolidationModel
      : onUnplaceChargeModel;

  /** Vue squad-shaped du plan charge-like : figs posées = plan, non posées = position d'origine. */
  const perModelPlanView = useMemo(() => {
    if (!perModelChargeLike || !activeChargeLikePlan) return null;
    const uid = activeChargeLikePlan.unitId;
    const occupied = (
      gameState?.units_cache as
        | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
        | undefined
    )?.[String(uid)]?.occupied_hexes_by_model;
    if (!occupied) return null;
    const models: Record<string, { col: number; row: number }> = {};
    const originModels: Record<string, { col: number; row: number }> = {};
    for (const [mid, pos] of Object.entries(occupied)) {
      originModels[mid] = { col: pos[0], row: pos[1] };
      const placed = activeChargeLikePlan.models[mid];
      models[mid] = placed ? { col: placed.col, row: placed.row } : { col: pos[0], row: pos[1] };
    }
    return {
      unitId: uid,
      models,
      originModels,
      activeModelId: activeChargeLikePlan.activeModelId,
      perModelValid: {} as Record<string, boolean>,
      coherencyOk: true,
      canValidate: activeChargeLikePlan.canValidate,
      wouldFlee: false,
    };
  }, [perModelChargeLike, activeChargeLikePlan, gameState?.units_cache]);

  /** Mode déploiement par escouade (PvP "active") : même machinerie per-fig que le move. */
  const isDeploymentMove = mode === "deploymentMove";
  /** Vue squad-shaped du plan de déploiement (ajoute wouldFlee:false pour la forme partagée). */
  const deployPlanView = useMemo(() => {
    if (!isDeploymentMove || !deployPlan) return null;
    return {
      unitId: deployPlan.unitId,
      models: deployPlan.models,
      originModels: deployPlan.originModels,
      activeModelId: deployPlan.activeModelId,
      perModelValid: deployPlan.perModelValid,
      coherencyOk: deployPlan.coherencyOk,
      canValidate: deployPlan.canValidate,
      wouldFlee: false,
    };
  }, [isDeploymentMove, deployPlan]);

  /** true si on est dans un mode plan par-figurine (move OU charge OU pile-in OU déploiement). */
  const isPerModelMove = mode === "squadModelMove" || perModelChargeLike || isDeploymentMove;
  /** Plan per-modèle actif (squad ou charge-like ou déploiement) — même forme partagée. */
  const effectivePerModelPlan = isDeploymentMove
    ? deployPlanView
    : perModelChargeLike
      ? perModelPlanView
      : squadMovePlan;
  /** Ref de pool de la fig active (squad BFS, charge-like eligible, ou zone de déploiement). */
  const effectivePerModelPoolRef = isDeploymentMove
    ? // Fig active → pool FILTRÉ (deploy_model_destinations) ; sinon zone brute (squad/drop).
      deployPlan?.activeModelId
      ? (deployModelPoolRef ?? null)
      : (deployPoolRef ?? null)
    : perModelChargeLike
      ? (activeChargeLikePoolRef ?? null)
      : (squadMoveModelPoolRef ?? null);
  const effectivePerModelPlanRef = useRef(effectivePerModelPlan);
  effectivePerModelPlanRef.current = effectivePerModelPlan;

  /** Tranche 2 : union des pools de déplacement des figs NON POSÉES de l'escouade (move-preview
   *  persistant après pose). Peuplée via l'endpoint batch move_squad_unplaced_destinations et rendue
   *  comme voile violet quand aucune fig n'est active. La version force le redraw du plateau. */
  const squadUnplacedUnionPoolRef = useRef<Set<string>>(new Set());
  const [squadUnplacedUnionVersion, setSquadUnplacedUnionVersion] = useState(0);

  /** Callbacks tir par-figurine — ref toujours a jour pour les handlers d'event stables. */
  const squadShootCallbacksRef = useRef({
    onStartSquadModelShoot,
    onSelectModelForShoot,
    onSquadShootLosOverview,
    onAssignShootTarget,
    onAutoAssignAllModels,
    onUnassignShootModel,
    onCommitSquadShoot,
    onCancelSquadShoot,
  });
  squadShootCallbacksRef.current = {
    onStartSquadModelShoot,
    onSelectModelForShoot,
    onSquadShootLosOverview,
    onAssignShootTarget,
    onAutoAssignAllModels,
    onUnassignShootModel,
    onCommitSquadShoot,
    onCancelSquadShoot,
  };
  /** Plan de tir toujours a jour pour les handlers d'event stables. */
  const squadShootPlanRef = useRef(squadShootPlan);
  squadShootPlanRef.current = squadShootPlan;
  /** Unité en "vue escouade" (double-clic), à jour pour le handler de clic stable. */
  const blinkingLosOverviewUnitIdRef = useRef<number | null>(null);
  blinkingLosOverviewUnitIdRef.current = blinkingLosOverviewUnitId ?? null;
  /** Allocation manuelle des pertes + callback, refs à jour pour le handler de clic. */
  const manualAllocationRef = useRef(manualAllocation);
  manualAllocationRef.current = manualAllocation;
  const onAllocateModelRef = useRef(onAllocateModel);
  onAllocateModelRef.current = onAllocateModel;
  // Persiste entre les re-renders (contrairement à une variable locale dans useEffect).
  // Clic-cible tir : simple/double mutualisés (le simple est différé pour ne pas partir
  // avant un double → évite le doublon d'assign + los_overview coûteux).
  const triggerEnemyShootClick = useSingleDoubleClick(250);
  const triggerEnemyShootClickRef = useRef(triggerEnemyShootClick);
  triggerEnemyShootClickRef.current = triggerEnemyShootClick;
  // Ref vers openWeaponsForTarget (défini plus bas) pour usage dans le handler pointer (flux cible-d'abord).
  const openWeaponsForTargetRef = useRef<
    (targetId: string, position?: { x: number; y: number }) => Promise<void>
  >(async () => {});
  // Ref vers selectShootFig (défini plus bas) — évite un TDZ dans le handler pointer.
  const selectShootFigRef = useRef<(modelId: string | undefined) => void>(() => {});
  const lastOwnFigClickRef = useRef<{ modelId: string; time: number } | null>(null);
  /** Combat par-figurine : callbacks + plan + dernier clic ennemi, refs à jour pour le handler stable. */
  const squadFightCallbacksRef = useRef({
    onSelectModelForFight,
    onAssignFightTarget,
    onAssignFightWeapon,
  });
  squadFightCallbacksRef.current = {
    onSelectModelForFight,
    onAssignFightTarget,
    onAssignFightWeapon,
  };
  const squadFightPlanRef = useRef(squadFightPlan);
  squadFightPlanRef.current = squadFightPlan;

  /** Combat : figs de l'unité active engagées avec >=1 ennemi (règle 04.02). Les autres
   * sont grisées + non sélectionnables à l'attribution. Même métrique que le contour rouge. */
  const fightEngagedModelIds = useMemo(() => {
    const result = new Set<string>();
    if (phase !== "fight" || !squadFightPlan) return result;
    const uc = gameState?.units_cache as
      | Record<
          string,
          { occupied_hexes_by_model?: Record<string, [number, number]>; player?: number }
        >
      | undefined;
    if (!uc) return result;
    const activeEntry = uc[String(squadFightPlan.unitId)];
    const activeUnit = units.find((u) => String(u.id) === String(squadFightPlan.unitId));
    const byModel = activeEntry?.occupied_hexes_by_model;
    if (!byModel || !activeUnit) return result;
    const gsRules = (
      gameState as { config?: { game_rules?: { engagement_zone?: number } } } | null | undefined
    )?.config?.game_rules;
    const cfgRules = gameConfig?.game_rules as { engagement_zone?: number } | undefined;
    const engRules = gsRules?.engagement_zone ?? cfgRules?.engagement_zone ?? 1;
    const i2sRaw = (boardConfig as unknown as { inches_to_subhex?: number } | null)
      ?.inches_to_subhex;
    const i2s = typeof i2sRaw === "number" ? i2sRaw : 10;
    const steps = engRules * i2s;
    const enemyFps: Array<Set<string>> = [];
    for (const [eid, e] of Object.entries(uc)) {
      const eu = units.find((u) => String(u.id) === eid);
      if (!eu || eu.player === activeUnit.player) continue;
      const efp =
        squadFootprintHexKeysFromModelCenters(e.occupied_hexes_by_model, eu) ??
        unitFootprintHexKeys(eu);
      if (efp) enemyFps.push(efp);
    }
    for (const [mid, pos] of Object.entries(byModel)) {
      const figFp = squadFootprintHexKeysFromModelCenters({ [mid]: pos }, activeUnit);
      if (!figFp) continue;
      for (const efp of enemyFps) {
        if (minHexDistanceBetweenFootprintKeySets(figFp, efp, steps) <= steps) {
          result.add(mid);
          break;
        }
      }
    }
    return result;
  }, [phase, squadFightPlan, gameState, gameConfig, boardConfig, units]);
  const fightEngagedModelIdsRef = useRef(fightEngagedModelIds);
  fightEngagedModelIdsRef.current = fightEngagedModelIds;
  /** Remonte le compte de figs assignables au hook (décompte barre = assignables, pas total). */
  const lastReportedFightCountRef = useRef<number>(-1);
  useEffect(() => {
    if (!onReportFightAssignable) return;
    const n = phase === "fight" && squadFightPlan ? fightEngagedModelIds.size : 0;
    if (lastReportedFightCountRef.current !== n) {
      lastReportedFightCountRef.current = n;
      onReportFightAssignable(n);
    }
  }, [phase, squadFightPlan, fightEngagedModelIds, onReportFightAssignable]);

  // Update refs when props change but don't trigger re-render - MOVE THIS BEFORE useEffect
  stableCallbacks.current = {
    onSelectUnit,
    onSkipUnit,
    onStartMovePreview,
    onDirectMove,
    onBumpMovePreviewOrientation,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onDeployUnit,
    onFightAttack,
    onSkipFight,
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
    onPileInMove,
    onSkipPileIn,
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

  // Weapon selection menu state.
  // Flux CIBLE-D'ABORD : quand `targetId` est défini, le menu liste les armes pouvant
  // viser cette cible (`targetWeapons`, chacune avec m=max et x=courant), avec compteur.
  const [weaponSelectionMenu, setWeaponSelectionMenu] = useState<{
    unitId: number;
    position: { x: number; y: number };
    /** Cibles cliquées (ordre) : chacune ajoute une ligne sous chaque profil éligible. */
    openTargets: string[];
    /** weapons_for_target par cible : profils éligibles avec m (max) et x (courant). */
    targetData: Record<string, Array<{ code: string; weapon: Weapon; m: number; x: number }>>;
    /** Cible sélectionnée (réticule + voiles vert/gris des figs de l'unité active). */
    activeTargetId?: string;
    /** État de chaque fig vis-à-vis de la cible : can_shoot (vert/gris) + ses armes. */
    modelsStatus?: Array<{
      model_id: string;
      can_shoot: boolean;
      exhausted: boolean;
      weapon_codes: string[];
    }>;
    /** Armes par figurine (indépendant de la cible) — encart/contour jaune dès le clic-fig. */
    figWeapons?: Record<string, string[]>;
    /** Profils du menu avec can_use (par-fig + exclusion Pistol) — rechargé à chaque attribution. */
    menuWeapons?: Array<{ index: number; weapon: Weapon; can_use: boolean; reason?: string }>;
    /** Fig sélectionnée (contour jaune + ses armes en encart jaune dans le menu). */
    selectedFig?: string;
    /** Arme sélectionnée dans le menu (contour jaune sur les figs qui la portent). */
    selectedWeaponCode?: string;
  } | null>(null);
  const weaponSelectionMenuRef = useRef(weaponSelectionMenu);
  weaponSelectionMenuRef.current = weaponSelectionMenu;
  const prevActiveShootingUnitRef = useRef<string | number | null>(null);
  const [hexCoordTooltip, setHexCoordTooltip] = useState<{
    visible: boolean;
    x: number;
    y: number;
    col: number;
    row: number;
  } | null>(null);
  const [boardZoom, setBoardZoom] = useState(BOARD_ZOOM_DEFAULT);
  const [zoomControlsOpen, setZoomControlsOpen] = useState(false);
  // Étages (multi-niveaux) : niveau d'affichage courant (0 = rez-de-chaussée). Piloté par le parent
  // (BoardWithAPI) quand fourni, sinon état interne (BoardReplay / tutorial). Le nombre d'étages vient
  // des ``floors`` du terrain (source unique). Sans étage → maxFloorLevel = 0, bouton masqué.
  const [internalLevel, setInternalLevel] = useState(0);
  const currentLevel = currentLevelProp ?? internalLevel;
  const setCurrentLevel = useCallback(
    (level: number) => {
      if (onCurrentLevelChange) onCurrentLevelChange(level);
      else setInternalLevel(level);
    },
    [onCurrentLevelChange]
  );
  const maxFloorLevel = useMemo(() => {
    const zones = boardConfig?.terrain_zones;
    if (!Array.isArray(zones)) return 0;
    let max = 0;
    for (const z of zones) {
      const floors = (z as { floors?: Array<{ level?: number }> }).floors;
      if (Array.isArray(floors)) {
        for (const f of floors) {
          if (typeof f?.level === "number" && f.level > max) max = f.level;
        }
      }
    }
    return max;
  }, [boardConfig?.terrain_zones]);
  // Hexes de chaque étage indexés "col,row" → dérivation LIVE du niveau d'une fig pendant le drag
  // (move/déploiement) avant validation. Approximation par hex-ancre (le commit reste autoritaire).
  const floorHexKeysByLevel = useMemo(() => {
    const m = new Map<number, Set<string>>();
    const zones = boardConfig?.terrain_zones;
    if (!Array.isArray(zones)) return m;
    for (const z of zones) {
      const floors = (z as { floors?: Array<{ level?: number; hexes?: unknown[] }> }).floors;
      if (!Array.isArray(floors)) continue;
      for (const f of floors) {
        if (typeof f?.level !== "number" || !Array.isArray(f.hexes)) continue;
        let set = m.get(f.level);
        if (!set) {
          set = new Set<string>();
          m.set(f.level, set);
        }
        for (const h of f.hexes) {
          const [c, r] = normalizeZoneHex(h);
          set.add(`${c},${r}`);
        }
      }
    }
    return m;
  }, [boardConfig?.terrain_zones]);
  // Union des hexes de TOUS les planchers (tous niveaux) → une fig n'est concernée par le masquage
  // mono-niveau que si son empreinte chevauche au moins un plancher (fig « liée à une structure à
  // étages »). Une fig en terrain découvert n'est jamais ghostée en changeant d'étage.
  const allFloorHexKeys = useMemo(() => {
    const u = new Set<string>();
    for (const set of floorHexKeysByLevel.values()) for (const k of set) u.add(k);
    return u;
  }, [floorHexKeysByLevel]);
  // Clamp : si le niveau courant dépasse le max (ex. changement de board), redescendre au sol.
  useEffect(() => {
    if (currentLevel > maxFloorLevel) setCurrentLevel(0);
  }, [currentLevel, maxFloorLevel, setCurrentLevel]);
  // Niveaux d'étage occupés par ≥1 figurine → empreinte blanchie (idée initiale stage.md).
  // Source PAR-FIGURINE (level_by_model) : une escouade dont SEULE une fig non-ancre est à l'étage
  // doit blanchir cet étage (l'ancre peut rester au sol). Fallback niveau d'unité/ancre.
  const occupiedFloorLevels = useMemo(() => {
    const s = new Set<number>();
    const uc = (gameState?.units_cache ?? {}) as Record<
      string,
      { level?: number; level_by_model?: Record<string, number> }
    >;
    for (const entry of Object.values(uc)) {
      if (entry.level_by_model) {
        for (const lv of Object.values(entry.level_by_model)) {
          if (typeof lv === "number" && lv >= 1) s.add(lv);
        }
      }
      if (typeof entry.level === "number" && entry.level >= 1) s.add(entry.level);
    }
    for (const u of units) {
      const lv = (u as { level?: number }).level;
      if (typeof lv === "number" && lv >= 1) s.add(lv);
    }
    return s;
  }, [gameState, units]);
  // Clé STABLE PAR VALEUR pour les deps de l'effet de dessin : dépendre du Set (nouvelle réf à
  // chaque render) relancerait l'effet en boucle et casserait la sélection (clic down/up sur des
  // objets PIXI recréés). Une string identique par valeur est Object.is-stable.
  const occupiedFloorLevelsKey = [...occupiedFloorLevels].sort((a, b) => a - b).join(".");
  const [boardViewportSize, setBoardViewportSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [isBoardPanning, setIsBoardPanning] = useState(false);

  // Mode « adapter à l'écran » : facteur de réduction (≤ 1) pour que le board tienne entièrement dans
  // la hauteur dispo. Vaut 1 quand le mode est OFF → toute la mécanique ci-dessous redevient identique.
  const [fitScale, setFitScale] = useState(1);
  useEffect(() => {
    if (boardDisplayMode !== "fit" || !boardViewportSize) {
      setFitScale(1);
      return;
    }
    const compute = () => {
      const available = window.innerHeight - BOARD_FIT_VERTICAL_MARGIN;
      const s = available / boardViewportSize.height;
      setFitScale(s < 1 ? s : 1);
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [boardDisplayMode, boardViewportSize]);

  // Échelle réellement appliquée au board = réduction « fit » × zoom manuel. Le zoom manuel multiplie
  // toujours par-dessus le fit. ``fitScale === 1`` → ``effectiveScale === boardZoom`` (comportement initial).
  const effectiveScale = fitScale * boardZoom;
  // Board enfermé dans une fenêtre scrollable limitée à l'écran : mode "window" (taille réelle
  // navigable) ou dès qu'on zoome au-delà de 1 (le pan a besoin d'un viewport fixe).
  const isWindowedBoard = boardDisplayMode === "window" || boardZoom > BOARD_ZOOM_DEFAULT;
  const zoomPercent = Math.round(boardZoom * 100);
  // Empreinte « de base » sur la page = board fit-réduit (zoom exclu) ; le zoom scrolle dans cette fenêtre.
  const fitBoardWidth = boardViewportSize ? boardViewportSize.width * fitScale : undefined;
  const fitBoardHeight = boardViewportSize ? boardViewportSize.height * fitScale : undefined;
  const scaledBoardWidth = boardViewportSize ? boardViewportSize.width * effectiveScale : undefined;
  const scaledBoardHeight = boardViewportSize
    ? boardViewportSize.height * effectiveScale
    : undefined;

  const applyBoardZoom = useCallback(
    (resolveZoom: (currentZoom: number) => number, anchorClient?: { x: number; y: number }) => {
      setBoardZoom((currentZoom) => {
        const nextZoom = clampBoardZoom(resolveZoom(currentZoom));
        if (nextZoom === currentZoom) return currentZoom;

        const viewport = boardViewportRef.current;
        if (viewport && anchorClient) {
          const rect = viewport.getBoundingClientRect();
          const anchorX = anchorClient.x - rect.left;
          const anchorY = anchorClient.y - rect.top;
          const contentX = (viewport.scrollLeft + anchorX) / currentZoom;
          const contentY = (viewport.scrollTop + anchorY) / currentZoom;

          requestAnimationFrame(() => {
            viewport.scrollLeft = contentX * nextZoom - anchorX;
            viewport.scrollTop = contentY * nextZoom - anchorY;
          });
        }

        return nextZoom;
      });
    },
    []
  );

  const resolveBoardZoomAnchorClient = useCallback((): { x: number; y: number } | undefined => {
    const lastPointer = boardZoomAnchorClientRef.current;
    if (lastPointer) return lastPointer;

    const viewport = boardViewportRef.current;
    if (!viewport) return undefined;

    const rect = viewport.getBoundingClientRect();
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };
  }, []);

  const handleBoardWheel = useCallback(
    (e: WheelEvent) => {
      if (e.ctrlKey) {
        e.preventDefault();
        const zoomFactor = e.deltaY < 0 ? BOARD_ZOOM_WHEEL_IN_FACTOR : BOARD_ZOOM_WHEEL_OUT_FACTOR;
        applyBoardZoom((currentZoom) => currentZoom * zoomFactor, {
          x: e.clientX,
          y: e.clientY,
        });
        return;
      }
      const delta = e.deltaY < 0 ? 1 : -1;
      if (mode === "movePreview") {
        if (!onBumpMovePreviewOrientation) return;
        e.preventDefault();
        onBumpMovePreviewOrientation(delta);
        return;
      }
      if (
        effectivePhase === "move" &&
        mode === "select" &&
        selectedUnitId !== null &&
        hoveredHexRef.current
      ) {
        const selectedUnit = units.find((u) => String(u.id) === String(selectedUnitId));
        if (!selectedUnit || selectedUnit.BASE_SHAPE === "round") return;
        e.preventDefault();
        const current =
          hoverMoveOrientationStepRef.current ??
          orientationStepForBoard(selectedUnit, gameState?.units_cache);
        if (current === undefined) {
          throw new Error(`Unit ${selectedUnit.id} is missing orientation`);
        }
        hoverMoveOrientationStepRef.current = (current + delta + 6) % 6;
        const baseShape = hoverSpriteRef.current?.getChildByName("hover-base-shape");
        if (baseShape) {
          baseShape.rotation = (hoverMoveOrientationStepRef.current * Math.PI) / 3;
        }
      }
    },
    [
      applyBoardZoom,
      effectivePhase,
      gameState?.units_cache,
      mode,
      onBumpMovePreviewOrientation,
      selectedUnitId,
      units,
    ]
  );

  useEffect(() => {
    const viewport = boardViewportRef.current;
    if (!viewport) return;

    viewport.addEventListener("wheel", handleBoardWheel, { passive: false });
    return () => {
      viewport.removeEventListener("wheel", handleBoardWheel);
    };
  }, [handleBoardWheel]);

  useEffect(() => {
    const viewport = boardViewportRef.current;
    if (!viewport) return;
    const onScroll = () => {
      const app = appRef.current;
      if (!app) return;
      setBlinkProbHtmlByUnitId((prev) => {
        if (Object.keys(prev).length === 0) return prev;
        const next: typeof prev = {};
        for (const [idStr, data] of Object.entries(prev)) {
          const screen = pixiStagePointToClientScreen(app, data.stageX, data.stageY);
          next[Number(idStr)] = { ...data, left: screen.x, top: screen.y };
        }
        return next;
      });
    };
    viewport.addEventListener("scroll", onScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", onScroll);
  }, []);

  const handleBoardPanStart = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const viewport = boardViewportRef.current;
      if (e.button !== 0 || !viewport || boardZoom <= BOARD_ZOOM_DEFAULT) return;

      boardPanStartRef.current = {
        pointerId: e.pointerId,
        clientX: e.clientX,
        clientY: e.clientY,
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
      setIsBoardPanning(true);
    },
    [boardZoom]
  );

  const handleBoardPanMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    boardZoomAnchorClientRef.current = { x: e.clientX, y: e.clientY };
    const panStart = boardPanStartRef.current;
    const viewport = boardViewportRef.current;
    if (!panStart || !viewport || panStart.pointerId !== e.pointerId) return;

    e.preventDefault();
    viewport.scrollLeft = panStart.scrollLeft - (e.clientX - panStart.clientX);
    viewport.scrollTop = panStart.scrollTop - (e.clientY - panStart.clientY);
  }, []);

  const handleBoardPanEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const panStart = boardPanStartRef.current;
    if (!panStart || panStart.pointerId !== e.pointerId) return;

    boardPanStartRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    setIsBoardPanning(false);
  }, []);

  const handleBoardZoomReset = useCallback(() => {
    applyBoardZoom(() => BOARD_ZOOM_DEFAULT, resolveBoardZoomAnchorClient());
    boardViewportRef.current?.scrollTo({ left: 0, top: 0 });
  }, [applyBoardZoom, resolveBoardZoomAnchorClient]);

  const handleCanvasMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      boardZoomAnchorClientRef.current = { x: e.clientX, y: e.clientY };
      if (!boardConfig) {
        setHexCoordTooltip(null);
        return;
      }
      const canvas = e.currentTarget.querySelector("canvas");
      if (!canvas) return;
      const app = appRef.current;
      if (!app) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const HR = boardConfig.hex_radius;
      const M = boardConfig.margin;
      const HW = 1.5 * HR;
      const HH = Math.sqrt(3) * HR;

      // Filet de sécurité : si Pixi n'a pas déclenché pointerout (cercle reconstruit lors de
      // unitsChanged), on détecte ici que la souris a quitté l'unité et on masque le tooltip.
      const hoverTooltip = unitHoverTooltipRef.current;
      if (hoverTooltip?.visible && hoverTooltip.text) {
        const idMatch = hoverTooltip.text.match(/\bID\s+(\d+)/);
        if (idMatch) {
          const hovUnit = unitsRef.current.find((u) => String(u.id) === idMatch[1]);
          if (hovUnit) {
            const stx = app.stage.position.x;
            const sty = app.stage.position.y;
            const ucx = hovUnit.col * HW + HW / 2 + M + stx;
            const ucy = hovUnit.row * HH + ((hovUnit.col % 2) * HH) / 2 + HH / 2 + M + sty;
            const dx = px - ucx;
            const dy = py - ucy;
            if (dx * dx + dy * dy > HR * 2.5 * (HR * 2.5)) {
              setUnitHoverTooltip(null);
            }
          }
        }
      }

      if (!showHexCoordinates) {
        setHexCoordTooltip(null);
        return;
      }
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
        setHexCoordTooltip({
          visible: true,
          x: e.clientX,
          y: e.clientY,
          col: bestCol,
          row: bestRow,
        });
      } else {
        setHexCoordTooltip(null);
      }
    },
    [boardConfig, showHexCoordinates]
  );

  const [unitHoverTooltip, setUnitHoverTooltip] = useState<HpBarHtmlTooltipPayload | null>(null);
  const unitHoverTooltipRef = useRef(unitHoverTooltip);
  unitHoverTooltipRef.current = unitHoverTooltip;
  const unitsRef = useRef(units);
  unitsRef.current = units;
  const unitIllustrationHoverTimerRef = useRef<number | null>(null);

  const clearUnitIllustrationHoverTimer = useCallback(() => {
    if (unitIllustrationHoverTimerRef.current !== null) {
      window.clearTimeout(unitIllustrationHoverTimerRef.current);
      unitIllustrationHoverTimerRef.current = null;
    }
  }, []);

  const handleUnitIconHoverChange = useCallback(
    (unitId: UnitId | null) => {
      clearUnitIllustrationHoverTimer();
      if (!onUnitIllustrationPreviewChange) {
        return;
      }
      if (unitId === null) {
        onUnitIllustrationPreviewChange(null);
        return;
      }
      unitIllustrationHoverTimerRef.current = window.setTimeout(() => {
        onUnitIllustrationPreviewChange(unitId);
        unitIllustrationHoverTimerRef.current = null;
      }, UNIT_ILLUSTRATION_HOVER_DELAY_MS);
    },
    [clearUnitIllustrationHoverTimer, onUnitIllustrationPreviewChange]
  );

  useEffect(() => {
    return () => {
      clearUnitIllustrationHoverTimer();
      onUnitIllustrationPreviewChange?.(null);
    };
  }, [clearUnitIllustrationHoverTimer, onUnitIllustrationPreviewChange]);

  /** Cadre % / bouclier COVER au-dessus de la barre PV clignotante (HTML, aligné `.rule-tooltip`). */
  const [blinkProbHtmlByUnitId, setBlinkProbHtmlByUnitId] = useState<
    Record<
      number,
      {
        left: number;
        top: number;
        stageX: number;
        stageY: number;
        label: string;
        showCoverShield: boolean;
        probabilityHelpText: string;
      }
    >
  >({});

  /** Tooltip distance prévisualisation mouvement (″) : même style que survol unité ; échelle hex → ″ via HEX_STEPS_PER_INCH_DISPLAY. */
  const [movePreviewDistanceTooltip, setMovePreviewDistanceTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);

  const [measureDistanceTooltip, setMeasureDistanceTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);

  /** Preview visuelle move : HP blink et indicateur de couvert affichés au survol ; le backend reste la vérité métier. */
  const [movePreviewLosBlinkIds, setMovePreviewLosBlinkIds] = useState<number[]>([]);
  const [movePreviewLosCoverById, setMovePreviewLosCoverById] = useState<Record<string, boolean>>(
    {}
  );
  /** Parallèle au cover : ennemis "cachés trop loin" (hors detection range) à la destination du move preview → œil rouge. */
  const [movePreviewLosTooFarById, setMovePreviewLosTooFarById] = useState<Record<string, boolean>>(
    {}
  );
  /**
   * Rule 13.09 : model_ids "cachés" à la destination du move preview, calculés PAR LE BACKEND
   * (action preview_hidden_from_position → même fonction compute_unit_hidden_models qu'au drop).
   * Source unique → le badge en preview est identique au statut après pose, pour toute forme de base.
   */
  const [movePreviewHiddenModelIds, setMovePreviewHiddenModelIds] = useState<Set<string>>(
    () => new Set()
  );
  const movePreviewHiddenCacheRef = useRef<Map<string, string[]>>(new Map());

  /**
   * Tir + advance : seule source pour ``fromCol``/``fromRow`` (LoS plateau + WASM blink).
   * Mis à jour uniquement depuis le même chemin souris que l’icône d’ancre ; réinitialisé hors ce mode.
   */
  const [shootAdvanceLosAnchor, setShootAdvanceLosAnchor] = useState<{
    col: number;
    row: number;
  } | null>(null);

  const shootAdvanceLosAnchorKey = useMemo(() => {
    if (phase !== "shoot" || mode !== "advancePreview" || shootAdvanceLosAnchor === null) {
      return "";
    }
    return `${shootAdvanceLosAnchor.col},${shootAdvanceLosAnchor.row}`;
  }, [phase, mode, shootAdvanceLosAnchor]);

  useEffect(() => {
    if (phase === "shoot" && mode === "advancePreview") return;
    setShootAdvanceLosAnchor(null);
  }, [phase, mode]);

  const movePreviewLosCoverKey = useMemo(
    () => stableBoolRecordJson(movePreviewLosCoverById),
    [movePreviewLosCoverById]
  );
  const movePreviewLosTooFarKey = useMemo(
    () => stableBoolRecordJson(movePreviewLosTooFarById),
    [movePreviewLosTooFarById]
  );
  const blinkingCoverByUnitIdKey = useMemo(
    () => stableBoolRecordJson(blinkingCoverByUnitId ?? {}),
    [blinkingCoverByUnitId]
  );
  const blinkingHiddenTooFarByUnitIdKey = useMemo(
    () => stableBoolRecordJson(blinkingHiddenTooFarByUnitId ?? {}),
    [blinkingHiddenTooFarByUnitId]
  );

  const chargePreviewOverlayKey = useMemo(
    () => poolEdgeSig(chargePreviewOverlayHexes),
    [chargePreviewOverlayHexes]
  );

  const chargeReferenceKey = chargeReferenceHex
    ? `${chargeReferenceHex.col},${chargeReferenceHex.row}`
    : "";

  /** Normalise la fermeture : Pixi envoie visible:false mais on garde l’état en null pour le rendu. */
  const handleUnitTooltip = useCallback((payload: HpBarHtmlTooltipPayload) => {
    if (!payload.visible) {
      setUnitHoverTooltip(null);
    } else {
      setUnitHoverTooltip({
        visible: true,
        text: payload.text,
        x: payload.x,
        y: payload.y,
        ...(payload.zIndex !== undefined ? { zIndex: payload.zIndex } : {}),
        ...(payload.opacity !== undefined ? { opacity: payload.opacity } : {}),
      });
    }
  }, []);

  const handleBlinkProbHtml = useCallback((payload: BlinkProbHtmlPayload) => {
    setBlinkProbHtmlByUnitId((prev) => {
      if (payload.action === "hide") {
        if (!(payload.unitId in prev)) return prev;
        const next = { ...prev };
        delete next[payload.unitId];
        return next;
      }
      if (payload.action === "show") {
        return {
          ...prev,
          [payload.unitId]: {
            left: payload.left,
            top: payload.top,
            stageX: payload.stageX,
            stageY: payload.stageY,
            label: payload.label,
            showCoverShield: payload.showCoverShield,
            probabilityHelpText: payload.probabilityHelpText,
          },
        };
      }
      const cur = prev[payload.unitId];
      if (!cur) return prev;
      return {
        ...prev,
        [payload.unitId]: {
          ...cur,
          label: payload.label,
          showCoverShield: payload.showCoverShield,
          probabilityHelpText: payload.probabilityHelpText,
        },
      };
    });
  }, []);

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
      // Combat (mêlée) : unité sans arme à distance possible → ne pas exiger RNG_WEAPONS.
      // Le tir gate déjà en amont sur ≥1 arme utilisable avant de dispatcher.
      if (!unit) return;

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

      const position = {
        x: rect.left + centerX + HEX_RADIUS * 0.6,
        y: rect.top + centerY - HEX_RADIUS * 0.6,
      };
      // Même unité : on préserve TOUT l'état (cible active, voiles, sélections) et on
      // repositionne seulement. Sinon (nouvelle unité) : menu neuf.
      setWeaponSelectionMenu((prev) =>
        prev && prev.unitId === unitId
          ? { ...prev, position }
          : { unitId, position, openTargets: [], targetData: {} }
      );
      window.dispatchEvent(new CustomEvent("weaponMenuOpened", { detail: { unitId } }));
    };

    window.addEventListener("boardWeaponSelectionClick", weaponClickHandler);
    return () => {
      window.removeEventListener("boardWeaponSelectionClick", weaponClickHandler);
    };
  }, [units, boardConfig]);

  // Charge armes par figurine + profils du menu (can_use) dès que le menu s'ouvre.
  useEffect(() => {
    const unitId = weaponSelectionMenu?.unitId;
    if (unitId == null || weaponSelectionMenu?.figWeapons) return;
    let cancelled = false;
    const P = phase === "fight" ? "fight" : "shoot";
    (async () => {
      try {
        const [wRes, mRes] = await Promise.all([
          fetch(`/api/game/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: `squad_${P}_models_weapons`,
              unitId: String(unitId),
            }),
          }),
          fetch(`/api/game/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: `squad_${P}_menu_weapons`,
              unitId: String(unitId),
            }),
          }),
        ]);
        if (!wRes.ok || !mRes.ok) throw new Error("HTTP error");
        const wData = await wRes.json();
        const mData = await mRes.json();
        if (!wData.success || !mData.success || cancelled) return;
        const figWeapons: Record<string, string[]> = {};
        for (const m of (wData.result?.models ?? []) as Array<{
          model_id: string;
          weapon_codes: string[];
        }>)
          figWeapons[m.model_id] = m.weapon_codes;
        const menuWeapons = (mData.result?.weapons ?? []) as Array<{
          index: number;
          weapon: Weapon;
          can_use: boolean;
          reason?: string;
        }>;
        setWeaponSelectionMenu((prev) =>
          prev && prev.unitId === unitId ? { ...prev, figWeapons, menuWeapons } : prev
        );
      } catch (e) {
        console.error("🔴 menu/models_weapons error:", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [weaponSelectionMenu?.unitId, weaponSelectionMenu?.figWeapons, phase]);

  // Auto-open weapon menu when a multi-weapon unit becomes the active shooting unit
  useEffect(() => {
    const activeShootingUnit = gameState?.active_shooting_unit;
    if (phase !== "shoot" || !activeShootingUnit) {
      prevActiveShootingUnitRef.current = activeShootingUnit ?? null;
      return;
    }
    if (activeShootingUnit === prevActiveShootingUnitRef.current) return;
    prevActiveShootingUnitRef.current = activeShootingUnit;

    const unitId =
      typeof activeShootingUnit === "string"
        ? parseInt(activeShootingUnit, 10)
        : activeShootingUnit;
    const unit = units.find((u) => u.id === unitId);
    if (!unit) return;

    // Flux cible-d'abord : le menu doit s'ouvrir dès ≥1 arme utilisable (même mono-profil,
    // ex. escouade toute en Storm Bolter) — sinon addTargetForShoot ne peut rien ouvrir.
    const usableWeapons = unit.available_weapons?.filter((w) => (w.can_use ?? w.canUse) === true);
    if (!usableWeapons || usableWeapons.length < 1) return;

    window.dispatchEvent(new CustomEvent("boardWeaponSelectionClick", { detail: { unitId } }));
  }, [gameState?.active_shooting_unit, phase, units]);

  // Combat (jumeau du tir ci-dessus) : ouvre le MÊME menu cible-d'abord dès qu'une unité fight
  // est activée (étape FIGHT). Le plan fight est posé par useEngineAPI sur activate_unit.
  const prevFightMenuUnitRef = useRef<number | null>(null);
  useEffect(() => {
    if (phase !== "fight" || fightSubPhase !== "fight" || !squadFightPlan) {
      prevFightMenuUnitRef.current = null;
      return;
    }
    if (squadFightPlan.unitId === prevFightMenuUnitRef.current) return;
    prevFightMenuUnitRef.current = squadFightPlan.unitId;
    window.dispatchEvent(
      new CustomEvent("boardWeaponSelectionClick", { detail: { unitId: squadFightPlan.unitId } })
    );
  }, [phase, fightSubPhase, squadFightPlan]);

  // Flux squad : fermer le menu d'armes quand l'activation se termine (Validate/Cancel → sortie du mode).
  // Combat : le menu reste tant qu'un plan fight actif existe ; sa disparition (commit/cancel →
  // squadFightPlan=null) referme le menu via cet effet.
  useEffect(() => {
    const fightMenuActive =
      phase === "fight" && fightSubPhase === "fight" && squadFightPlan != null;
    if (mode !== "squadModelShoot" && !fightMenuActive) {
      setWeaponSelectionMenu(null);
    }
  }, [mode, phase, fightSubPhase, squadFightPlan]);

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
    const centerX = p1Unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
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
        u.row * HEX_VERT_SPACING + ((u.col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
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
    boardConfig,
    units,
  ]);

  const stableBlinkingUnits = useMemo(() => {
    if (!blinkingUnits) return undefined;
    const sorted = blinkingUnits.length > 0 ? [...blinkingUnits].sort((a, b) => a - b) : [];
    return sorted;
  }, [blinkingUnits]);

  const stableBlinkingUnitsRef = useRef<number[] | undefined>(stableBlinkingUnits);
  stableBlinkingUnitsRef.current = stableBlinkingUnits;

  // Dead model ghosts: track model positions that disappear from units_cache during a phase.
  interface DeadModelGhost {
    unit: Unit;
    col: number;
    row: number;
    meta: ModelVisualMeta | null;
  }
  const [deadModelGhosts, setDeadModelGhosts] = useState<DeadModelGhost[]>([]);
  // key: "unitId:modelId" (or "unitId:_" for single-model units) → [col, row]
  const prevModelPosRef = useRef<
    Map<string, { pos: [number, number]; meta: ModelVisualMeta | null }>
  >(new Map());

  // Only expose ghosts to PIXI during shoot phase — prevents false detections during
  // phase transitions from affecting unitsFingerprint / unitsChanged outside of shoot.
  const deadModelGhostsForRender = useMemo(
    () => (effectivePhase === "shoot" ? deadModelGhosts : []),
    [effectivePhase, deadModelGhosts]
  );

  const unitsBoardLayoutKey = useMemo(() => {
    const uc = gameState?.units_cache as Record<string, unknown> | undefined;
    return [...units]
      .sort((a, b) => String(a.id).localeCompare(String(b.id)))
      .map(
        (u) =>
          `${String(u.id)}:${u.col}:${u.row}:${hpCurForBoardFingerprint(u, uc)}:rng${u.selectedRngWeaponIndex ?? 0}`
      )
      .join("|");
  }, [units, gameState?.units_cache]);

  /**
   * Phase tir : même source LoS frontend que le survol move — ``buildLosPreviewFromSource``.
   * Le backend reste la vérité métier pour la validation finale des cibles.
   */
  const shootPreviewWasmLos = useMemo((): {
    blinkIds: number[];
    coverByUnitId: Record<string, boolean>;
    key: string;
  } => {
    const empty = {
      blinkIds: [] as number[],
      coverByUnitId: {} as Record<string, boolean>,
      key: "",
    };
    if (phase !== "shoot") return empty;
    const enginePhase = gameState?.phase ?? phase;
    if (enginePhase !== "shoot") return empty;
    if (!boardConfig || !gameConfig) return empty;
    if (!isWasmReady()) return empty;

    const resolveShootLosSource = (): { unit: Unit; fromCol: number; fromRow: number } | null => {
      if (mode === "advancePreview") {
        if (!shootAdvanceLosAnchor) return null;
        const sel =
          selectedUnitId == null
            ? undefined
            : units.find((u) => String(u.id) === String(selectedUnitId));
        if (!sel?.RNG_WEAPONS?.length) return null;
        return {
          unit: sel,
          fromCol: shootAdvanceLosAnchor.col,
          fromRow: shootAdvanceLosAnchor.row,
        };
      }
      if (mode === "movePreview" && movePreview) {
        const mpUnit = units.find((u) => u.id === movePreview.unitId);
        if (!mpUnit) return null;
        return { unit: mpUnit, fromCol: movePreview.destCol, fromRow: movePreview.destRow };
      }
      if (mode === "attackPreview" && attackPreview) {
        const apUnit = units.find((u) => u.id === attackPreview.unitId);
        if (!apUnit || String(apUnit.id) !== String(selectedUnitId)) return null;
        return { unit: apUnit, fromCol: apUnit.col, fromRow: apUnit.row };
      }
      if (mode === "squadModelShoot") {
        if (!squadShootPlan?.activeModelId) return null;
        const shootUnit = units.find((u) => String(u.id) === String(squadShootPlan.unitId));
        if (!shootUnit) return null;
        const uc = gameState?.units_cache as
          | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
          | undefined;
        const pos =
          uc?.[String(squadShootPlan.unitId)]?.occupied_hexes_by_model?.[
            squadShootPlan.activeModelId
          ];
        if (!pos) return null;
        return { unit: shootUnit, fromCol: pos[0], fromRow: pos[1] };
      }
      const sel =
        selectedUnitId == null
          ? undefined
          : units.find((u) => String(u.id) === String(selectedUnitId));
      if (!sel) return null;
      const activeShoot = (
        gameState as { active_shooting_unit?: string | number } | null | undefined
      )?.active_shooting_unit;
      const isActiveShooter = activeShoot != null && String(activeShoot) === String(selectedUnitId);
      const shootLeft = sel.SHOOT_LEFT;
      if ((shootLeft === undefined || shootLeft <= 0) && !isActiveShooter) {
        return null;
      }
      return { unit: sel, fromCol: sel.col, fromRow: sel.row };
    };

    const source = resolveShootLosSource();
    if (!source?.unit.RNG_WEAPONS?.length) return empty;

    const range = getMaxRangedRange(source.unit);
    if (range <= 0) return empty;

    try {
      const ucByModel = unitsCacheModelCenters(gameState?.units_cache);
      const losPreview = buildLosPreviewFromSource({
        source,
        units,
        boardCols: boardConfig.cols,
        boardRows: boardConfig.rows,
        wallHexes: boardConfig.wall_hexes,
        wallHexesOverride,
        obscuringZones: losObscuringZones,
        terrainZones: losTerrainZones,
        maxRange: range,
        distanceMetric: rangedPreviewMetric(gameConfig),
        unitsCacheByModel: ucByModel,
        shooterModelCenters:
          source.fromCol === source.unit.col && source.fromRow === source.unit.row
            ? ucByModel?.[String(source.unit.id)]
            : undefined,
      });
      const blinkIds = losPreview.blinkIds;
      const coverByUnitId = losPreview.coverByUnitId;
      const key = `${shootAdvanceLosAnchorKey}|${losPreview.key}`;
      return { blinkIds, coverByUnitId, key };
    } catch {
      return empty;
    }
  }, [
    phase,
    mode,
    gameState?.phase,
    gameState?.active_shooting_unit,
    movePreview,
    attackPreview,
    selectedUnitId,
    boardConfig,
    gameConfig,
    wallHexesOverride,
    losObscuringZones,
    losTerrainZones,
    shootAdvanceLosAnchorKey,
    units,
    shootAdvanceLosAnchor?.col,
    shootAdvanceLosAnchor?.row,
    shootAdvanceLosAnchor,
    squadShootPlan?.activeModelId,
    squadShootPlan?.unitId,
    gameState?.units_cache,
  ]);

  const effectiveBlinkingUnitsWithMovePreview = useMemo(() => {
    // LoS preview during squad movePreview is disabled per user requirement:
    // "preview LoS QUE quand UNE figurine est selectionnée" — re-introduce in
    // the per-fig flow only, not during squad-level hover/preview.
    const useMoveLosPreview =
      phase === "move" &&
      (mode === "select" || (mode === "squadModelMove" && squadMovePlan?.activeModelId != null));
    const mergedIds = useMoveLosPreview ? movePreviewLosBlinkIds : (stableBlinkingUnits ?? []);
    const uc = gameState?.units_cache as Record<string, unknown> | undefined;
    return filterBlinkIdsToLivingUnitsCache(mergedIds, uc, units);
  }, [
    stableBlinkingUnits,
    mode,
    phase,
    movePreviewLosBlinkIds,
    squadMovePlan?.activeModelId,
    gameState?.units_cache,
    units,
  ]);

  useEffect(() => {
    const isMoveLosPreviewContext =
      phase === "move" &&
      (mode === "select" || mode === "movePreview") &&
      gameState?.active_movement_unit != null;
    if (isMoveLosPreviewContext) return;
    setMovePreviewLosBlinkIds([]);
    setMovePreviewLosCoverById({});
    setMovePreviewLosTooFarById({});
    movePreviewBackendLosCacheRef.current.clear();
  }, [phase, mode, gameState?.active_movement_unit]);

  // Rule 13.09 : figs cachées à la destination du move preview, calculées PAR LE BACKEND
  // (preview_hidden_from_position = même fonction qu'au drop). Debounce + cache par
  // unitId/destCol/destRow/orientation pour limiter les appels au survol.
  useEffect(() => {
    // Construit la requête selon le mode preview actif : squad entier (translation rigide) ou
    // figurine-par-figurine (positions explicites du plan). Les deux → même fonction backend.
    let req: { key: string; body: Record<string, unknown> } | null = null;
    if (phase === "move" && mode === "movePreview" && movePreview) {
      const { unitId, destCol, destRow, orientation } = movePreview;
      req = {
        key: `pos:${unitId}:${destCol}:${destRow}:${orientation ?? ""}`,
        body: {
          action: "preview_hidden_from_position",
          unitId: String(unitId),
          destCol,
          destRow,
          orientation,
        },
      };
    } else if ((mode === "squadModelMove" || isDeploymentMove) && effectivePerModelPlan) {
      const planForHidden = effectivePerModelPlan;
      const unitId = planForHidden.unitId;
      const occupied = (
        gameState?.units_cache as
          | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
          | undefined
      )?.[String(unitId)]?.occupied_hexes_by_model;
      // Déploiement : escouade provisoire absente de ``units_cache`` → base = positions du plan.
      const baseEntries: Array<[string, [number, number]]> = occupied
        ? Object.entries(occupied)
        : Object.entries(planForHidden.models).map(
            ([m, p]) => [m, [p.col, p.row]] as [string, [number, number]]
          );
      if (baseEntries.length > 0) {
        // Position finale par fig : provisoire (plan) si présente, sinon position actuelle.
        const modelPositions: Record<string, [number, number]> = {};
        for (const [mid, pos] of baseEntries) {
          const planPos = planForHidden.models[mid];
          modelPositions[mid] = planPos ? [planPos.col, planPos.row] : pos;
        }
        req = {
          key:
            `plan:${unitId}:` +
            Object.entries(modelPositions)
              .map(([m, p]) => `${m}@${p[0]},${p[1]}`)
              .join(","),
          body: {
            action: "preview_hidden_from_model_positions",
            unitId: String(unitId),
            modelPositions,
          },
        };
      }
    }

    if (!req) {
      setMovePreviewHiddenModelIds((prev) => (prev.size === 0 ? prev : new Set()));
      return;
    }
    const { key, body } = req;
    const cached = movePreviewHiddenCacheRef.current.get(key);
    if (cached) {
      setMovePreviewHiddenModelIds(new Set(cached));
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      void (async () => {
        const response = await fetch("/api/game/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!response.ok) {
          throw new Error(`hidden preview failed with HTTP ${response.status}`);
        }
        const data = await response.json();
        if (data?.success !== true) {
          throw new Error("hidden preview returned success=false");
        }
        const hiddenModels: string[] = Array.isArray(data.result?.hidden_models)
          ? data.result.hidden_models.map((m: unknown) => String(m))
          : [];
        movePreviewHiddenCacheRef.current.set(key, hiddenModels);
        if (!cancelled) setMovePreviewHiddenModelIds(new Set(hiddenModels));
      })().catch((err) => {
        if (!cancelled) console.error(err);
      });
    }, 25); // debounce survol (ms) avant l'appel backend du hidden preview
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [phase, mode, isDeploymentMove, movePreview, effectivePerModelPlan, gameState?.units_cache]);

  // Prévisualisation LoS (move) : uniquement depuis onMouseMove = position de l’icône, pas l’hex sous le curseur
  useEffect(() => {
    if (!boardConfig || !gameConfig) return;

    // En mode plan par-figurine (move OU charge), un effet dédié gère le preview ; ce gros effet de
    // preview LoS au survol NE doit PAS tourner (coûteux par mouvement + inutile pour la charge,
    // dont la pose se fait au clic sur l'hex).
    if (mode === "squadModelMove" || mode === "chargeModelMove" || isDeploymentMove) return;

    const HEX_RADIUS_H = boardConfig.hex_radius;
    const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
    const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
    const MARGIN_H = boardConfig.margin;
    const BOARD_COLS_H = boardConfig.cols;
    const BOARD_ROWS_H = boardConfig.rows;
    /** Aligné sur BoardDisplay (prévisualisation tir / movePreview) : bleu clair = couvert, bleu moyen = LoS claire */
    const LOS_PREVIEW_CLEAR_HEX = 0x4f8bff;
    const LOS_PREVIEW_COVER_HEX = 0x9ec5ff;

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
      setMovePreviewLosBlinkIds([]);
      setMovePreviewLosCoverById({});
      setMovePreviewLosTooFarById({});
      if (hoverOverlayRef.current) hoverOverlayRef.current.visible = false;
      setShootAdvanceLosAnchor(null);
    };

    // Pre-parse pixel positions for fast nearest-hex lookups
    let zonePixels: { x: number; y: number }[] | null = null;
    let destPixels: { x: number; y: number; col: number; row: number }[] | null = null;
    /** Grille spatiale : évite un scan O(n) sur ~5k ancres à chaque mousemove. */
    let destPixelBuckets: Map<string, { x: number; y: number; col: number; row: number }[]> | null =
      null;
    const DEST_BUCKET_PX = 96;

    const buildZonePixels = () => {
      let pool: Set<string> | undefined | null;
      if (isPerModelMove && effectivePerModelPlan?.activeModelId) {
        // Plan par-figurine (move BFS ou charge eligible) : zone = pool de la fig active.
        pool = effectivePerModelPoolRef?.current;
      } else if (phase === "charge" && mode === "chargePreview") {
        const z = chargeFootprintZoneRef?.current;
        const a = chargeDestPoolRef?.current;
        if (z && z.size > 0) {
          pool = z;
        } else if (a && a.size > 0) {
          pool = a;
        } else {
          zonePixels = null;
          return;
        }
      } else {
        // Avec ``move_preview_footprint_mask_loops`` seul, ``syncMoveDestinationPoolRefs`` vide
        // ``footprintZoneRef`` (pas de liste hex dans le JSON) — un Set vide est truthy : ``??``
        // ne bascule pas. Il faut alors les centres d’ancres comme « zone élargie » pour ne pas
        // masquer l’icône dès que le curseur sort du masque (voir ``!inZone`` + ``inExpandedZone``).
        const fp = footprintZoneRef?.current;
        pool = fp && fp.size > 0 ? fp : resolvedMoveDestPoolRef.current;
      }
      if (!pool || pool.size === 0) {
        zonePixels = null;
        return;
      }
      zonePixels = [];
      for (const k of pool) {
        const sep = k.indexOf(",");
        const c = Number(k.substring(0, sep));
        const r = Number(k.substring(sep + 1));
        zonePixels.push({ x: hxX(c), y: hxY(c, r) });
      }
    };

    const buildDestPixels = () => {
      const pool =
        isPerModelMove && effectivePerModelPlan?.activeModelId
          ? effectivePerModelPoolRef?.current
          : phase === "charge" && mode === "chargePreview"
            ? chargeDestPoolRef?.current
            : resolvedMoveDestPoolRef.current;
      destPixelBuckets = null;
      if (!pool || pool.size === 0) {
        destPixels = null;
        return;
      }
      destPixels = [];
      const buck = new Map<string, { x: number; y: number; col: number; row: number }[]>();
      for (const k of pool) {
        const sep = k.indexOf(",");
        const c = Number(k.substring(0, sep));
        const r = Number(k.substring(sep + 1));
        const x = hxX(c);
        const y = hxY(c, r);
        const dp = { x, y, col: c, row: r };
        destPixels.push(dp);
        const bx = Math.floor(x / DEST_BUCKET_PX);
        const by = Math.floor(y / DEST_BUCKET_PX);
        const bkey = `${bx},${by}`;
        let arr = buck.get(bkey);
        if (!arr) {
          arr = [];
          buck.set(bkey, arr);
        }
        arr.push(dp);
      }
      destPixelBuckets = buck;
    };

    const nearestDestToPixel = (
      px: number,
      py: number
    ): { x: number; y: number; col: number; row: number } | null => {
      if (!destPixels || destPixels.length === 0) return null;
      if (!destPixelBuckets || destPixelBuckets.size === 0) {
        let best = destPixels[0]!;
        let bestD = Infinity;
        for (let i = 0; i < destPixels.length; i++) {
          const dp = destPixels[i]!;
          const d = (dp.x - px) * (dp.x - px) + (dp.y - py) * (dp.y - py);
          if (d < bestD) {
            bestD = d;
            best = dp;
          }
        }
        return best;
      }
      const bx = Math.floor(px / DEST_BUCKET_PX);
      const by = Math.floor(py / DEST_BUCKET_PX);
      let bestD = Infinity;
      let best: { x: number; y: number; col: number; row: number } | null = null;
      const tryBand = (band: number) => {
        for (let dbx = bx - band; dbx <= bx + band; dbx++) {
          for (let dby = by - band; dby <= by + band; dby++) {
            const list = destPixelBuckets!.get(`${dbx},${dby}`);
            if (!list) continue;
            for (const dp of list) {
              const d = (dp.x - px) * (dp.x - px) + (dp.y - py) * (dp.y - py);
              if (d < bestD) {
                bestD = d;
                best = dp;
              }
            }
          }
        }
      };
      tryBand(1);
      if (bestD === Infinity) tryBand(4);
      if (bestD === Infinity) tryBand(12);
      if (bestD === Infinity) {
        for (let i = 0; i < destPixels.length; i++) {
          const dp = destPixels[i]!;
          const d = (dp.x - px) * (dp.x - px) + (dp.y - py) * (dp.y - py);
          if (d < bestD) {
            bestD = d;
            best = dp;
          }
        }
      }
      return best;
    };

    // Même ordre que l’effet drawBoard : cet effet est déclaré **avant** lui — au premier commit,
    // ``buildDestPixels`` voyait souvent un pool encore vide puis ``hideMovePreviewGuides`` effaçait
    // l’ancre advance tir. On synchronise la ref ici avant la première construction de ``destPixels``.
    {
      const enginePhaseForPoolsMs = gameState?.phase ?? phase;
      const keepMovementPickPoolMs =
        ((enginePhaseForPoolsMs === "move" || enginePhaseForPoolsMs === "command") &&
          selectedUnitId !== null) ||
        (mode === "advancePreview" && selectedUnitId !== null) ||
        (phase === "shoot" && pendingMoveAfterShooting && selectedUnitId !== null) ||
        (phase === "fight" &&
          (mode === "pileInPreview" || mode === "consolidationPreview") &&
          selectedUnitId !== null);

      if (keepMovementPickPoolMs && resolvedMoveDestPoolRef.current) {
        const shouldSyncMovePoolsFromStateMs =
          enginePhaseForPoolsMs === "move" ||
          enginePhaseForPoolsMs === "command" ||
          (mode === "advancePreview" && selectedUnitId !== null) ||
          (phase === "shoot" && pendingMoveAfterShooting);
        if (shouldSyncMovePoolsFromStateMs) {
          syncMoveDestinationPoolRefs({
            gameState: gameState ?? null,
            phase: enginePhaseForPoolsMs,
            mode,
            selectedUnitId,
            moveDestPoolRef: resolvedMoveDestPoolRef,
            footprintZoneRef,
            footprintMaskLoopsRef,
            pendingMoveAfterShooting,
          });
        }
      }

      if (
        mode === "advancePreview" &&
        selectedUnitId !== null &&
        resolvedMoveDestPoolRef.current.size === 0
      ) {
        if (typeof getAdvanceDestinations === "function") {
          const dests = getAdvanceDestinations(selectedUnitId);
          const s = new Set<string>();
          for (const d of dests) {
            s.add(`${Number(d.col)},${Number(d.row)}`);
          }
          if (s.size > 0) {
            resolvedMoveDestPoolRef.current = s;
          }
        }
        if (
          resolvedMoveDestPoolRef.current.size === 0 &&
          availableCellsOverride &&
          availableCellsOverride.length > 0
        ) {
          const s = new Set<string>();
          for (const c of availableCellsOverride) {
            s.add(`${Number(c.col)},${Number(c.row)}`);
          }
          resolvedMoveDestPoolRef.current = s;
        }
      }
    }

    buildZonePixels();
    buildDestPixels();

    /** Évite un setState React à chaque pixel de mouvement (coûteux). */
    let lastMovePreviewTooltipKey = "";

    // DOM mousemove: icon follows cursor pixel-perfect (move, advance tir, charge destination)
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    const onMouseMove = (ev: MouseEvent) => {
      // squad.md brique 3 : en mode plan par-figurine, le fantome ne suit le curseur QUE si une
      // fig est active. Des qu'on a pose la fig (deselection), on cache le preview (sinon il "reste").
      if (isPerModelMove && !effectivePerModelPlanRef.current?.activeModelId) {
        if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
          hoverSpriteRef.current.visible = false;
        }
        if (hoverOverlayRef.current) hoverOverlayRef.current.visible = false;
        if (movePreviewGuideLineRef.current && !movePreviewGuideLineRef.current.destroyed) {
          movePreviewGuideLineRef.current.clear();
          movePreviewGuideLineRef.current.visible = false;
        }
        return;
      }
      const activeMovementUnitId =
        phase === "move" && gameState?.active_movement_unit != null
          ? parseRequiredUnitId(gameState.active_movement_unit, "gameState.active_movement_unit")
          : null;
      const movementPreviewUnitId = phase === "move" ? activeMovementUnitId : selectedUnitId;
      const allowIconFollow =
        movementPreviewUnitId !== null &&
        ((effectivePhase === "move" && activeMovementUnitId !== null) ||
          mode === "advancePreview" ||
          (phase === "charge" && mode === "chargePreview") ||
          (phase === "fight" && (mode === "pileInPreview" || mode === "consolidationPreview")));
      if (!allowIconFollow) return;
      const app = appRef.current;
      if (!app || !canvas) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (ev.clientX - rect.left) * scaleX;
      const py = (ev.clientY - rect.top) * scaleY;

      const selectedUnit = units.find((u) => String(u.id) === String(movementPreviewUnitId));
      if (!selectedUnit) return;

      // Build the icon container once per selected unit
      if (
        !hoverSpriteRef.current ||
        hoverSpriteRef.current.destroyed ||
        spriteBuiltForUnitId !== movementPreviewUnitId
      ) {
        if (hoverSpriteRef.current) {
          hoverSpriteRef.current.destroy({ children: true });
          hoverSpriteRef.current = null;
        }
        hoverMoveOrientationStepRef.current = null;
        const container = new PIXI.Container();
        container.zIndex = 2500;
        container.eventMode = "none";
        container.interactiveChildren = false;
        app.stage.addChild(container);

        const HEX_R = HEX_RADIUS_H;
        const nrHover = getNonRoundBasePixelLayout(selectedUnit, HEX_R);
        const bdSel = resolveBaseSizeForUnitDisplay(selectedUnit);
        const baseSizeVal = bdSel > 1 ? bdSel : undefined;
        const defaultIconDiam = baseSizeVal
          ? baseSizeVal * 1.5 * HEX_RADIUS_H
          : HEX_RADIUS_H * (selectedUnit.ICON_SCALE ?? 1.0);

        const baseColor = selectedUnit.player === 1 ? 0x1d4ed8 : 0x882222;
        const baseCircle = new PIXI.Graphics();
        baseCircle.name = "hover-base-shape";
        baseCircle.beginFill(baseColor, 0.7);
        if (nrHover) {
          if (nrHover.kind === "oval") {
            baseCircle.drawEllipse(0, 0, nrHover.outerRx, nrHover.outerRy);
          } else {
            const h = nrHover.squareHalf;
            const s = nrHover.squareSide;
            baseCircle.drawRoundedRect(-h, -h, s, s, getSquareCornerRadiusPx());
          }
        } else {
          baseCircle.drawCircle(0, 0, defaultIconDiam / 2);
        }
        baseCircle.endFill();
        const hoverOrientation =
          hoverMoveOrientationStepRef.current ??
          orientationStepForBoard(selectedUnit, gameState?.units_cache);
        if (nrHover && hoverOrientation !== undefined) {
          baseCircle.rotation = (hoverOrientation * Math.PI) / 3;
          hoverMoveOrientationStepRef.current = hoverOrientation;
        }
        container.addChild(baseCircle);

        if (selectedUnit.ICON) {
          const iconPath =
            selectedUnit.player === 2
              ? selectedUnit.ICON.replace(".webp", "_red.webp")
              : selectedUnit.ICON;
          const texture = PIXI.Texture.from(iconPath);
          const iconSprite = new PIXI.Sprite(texture);
          iconSprite.anchor.set(0.5);
          const nonRoundIconR = getNonRoundIconRadius(selectedUnit, HEX_R);
          const iconDiam = nonRoundIconR != null ? nonRoundIconR * 2 : defaultIconDiam;
          iconSprite.width = iconDiam;
          iconSprite.height = iconDiam;
          if (nonRoundIconR != null) {
            const maskG = new PIXI.Graphics();
            maskG.beginFill(0xffffff);
            maskG.drawCircle(0, 0, nonRoundIconR);
            maskG.endFill();
            iconSprite.mask = maskG;
            container.addChild(maskG);
          }
          container.addChild(iconSprite);
        }
        container.alpha = 0.65;
        hoverSpriteRef.current = container;
        spriteBuiltForUnitId = movementPreviewUnitId;
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

      const best = nearestDestToPixel(px, py);
      if (!best) {
        container.visible = false;
        hideMovePreviewGuides();
        return;
      }

      // Only show the icon if cursor is reasonably close (within footprint zone or nearby)
      const approxCol = Math.round((px - HEX_WIDTH_H / 2 - MARGIN_H) / HEX_WIDTH_H);
      const rowOffset = ((approxCol % 2) * HEX_HEIGHT_H) / 2;
      const approxRow = Math.round((py - HEX_HEIGHT_H / 2 - MARGIN_H - rowOffset) / HEX_HEIGHT_H);
      const curKey = `${approxCol},${approxRow}`;
      const inMaskLoops =
        footprintMaskLoopsRef?.current && footprintMaskLoopsRef.current.length > 0
          ? pointInAnyMaskLoop(px, py, footprintMaskLoopsRef.current)
          : false;
      const inZone =
        phase === "charge" && mode === "chargePreview"
          ? (chargeFootprintZoneRef?.current?.has(curKey) ?? false) ||
            (chargeDestPoolRef?.current?.has(curKey) ?? false)
          : inMaskLoops ||
            (footprintZoneRef?.current?.has(curKey) ?? false) ||
            (resolvedMoveDestPoolRef.current?.has(curKey) ?? false);

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

      // Snap direct sur l’ancre la plus proche (pas de lerp : coût perçu + inutile car positions discrètes).
      container.position.set(best.x, best.y);
      // In move phase + movePreview, the multi-fig ghost (MOVE PREVIEW RENDERING)
      // is the source of truth for the destination preview. Hide the single-fig
      // hover sprite so we don't show two overlapping previews.
      container.visible = !(phase === "move" && mode === "movePreview");
      const hoverBaseShape = container.getChildByName("hover-base-shape");
      if (hoverBaseShape && hoverMoveOrientationStepRef.current !== null) {
        hoverBaseShape.rotation = (hoverMoveOrientationStepRef.current * Math.PI) / 3;
      }
      const iconCol = best.col;
      const iconRow = best.row;

      // Ligne départ → prévisualisation : en charge, départ = hex du chargeur **le plus proche de l’empreinte cible**
      // (aligné sur charge_handlers / Board ×10). Sinon on gardait le centre primaire → faux 7,6″ vs jet 6″.
      let startCol = Number(selectedUnit.col);
      let startRow = Number(selectedUnit.row);
      if (phase === "charge" && mode === "chargePreview" && selectedUnitId != null) {
        if (
          chargeReferenceHex != null &&
          Number.isFinite(chargeReferenceHex.col) &&
          Number.isFinite(chargeReferenceHex.row)
        ) {
          startCol = chargeReferenceHex.col;
          startRow = chargeReferenceHex.row;
        } else {
          const sel = (
            gameState as { charge_target_selections?: Record<string, string> } | undefined
          )?.charge_target_selections;
          const rawTid =
            chargeTargetId != null
              ? String(chargeTargetId)
              : (sel?.[String(selectedUnitId)] ?? null);
          if (rawTid != null) {
            const tidNum = parseInt(String(rawTid), 10);
            const uc = gameState?.units_cache as Record<string, unknown> | undefined;
            const targetUnit = units.find((u) => String(u.id) === String(tidNum));
            if (uc && targetUnit) {
              const chEntry = uc[String(selectedUnitId)];
              const tEntry = uc[String(tidNum)];
              const ref = closestChargerHexToTargetFootprint(
                chEntry,
                tEntry,
                { col: Number(selectedUnit.col), row: Number(selectedUnit.row) },
                { col: Number(targetUnit.col), row: Number(targetUnit.row) }
              );
              startCol = ref.col;
              startRow = ref.row;
            }
          }
        }
      }
      const previewIconX = container.position.x;
      const previewIconY = container.position.y;
      let hexSteps = hexDistOff(startCol, startRow, iconCol, iconRow);
      // En charge, préférer la distance de mouvement RÉELLE (pathfinding du moteur) à la ligne droite :
      // au sol, le détour autour d'un mur/figs compte (la ligne droite sous-estime) ; en vol déclaré,
      // le moteur renvoie la distance directe. Clé = ancre snappée (iconCol,iconRow), dans le pool valide.
      if (phase === "charge" && mode === "chargePreview") {
        const pathDist = chargeDestDistancesRef?.current?.get(`${iconCol},${iconRow}`);
        if (pathDist != null) hexSteps = pathDist;
      }
      const stepsPerInch =
        (boardConfig as unknown as { inches_to_subhex?: number }).inches_to_subhex ||
        HEX_STEPS_PER_INCH_DISPLAY;
      const distanceDisplay = (hexSteps / stepsPerInch).toFixed(1);
      const tooltipCharge =
        phase === "charge" &&
        mode === "chargePreview" &&
        chargeRoll != null &&
        chargeRoll !== undefined
          ? `${distanceDisplay}" / ${chargeRoll}"`
          : `${distanceDisplay}"`;

      if (movePreviewGuideLineRef.current && !movePreviewGuideLineRef.current.destroyed) {
        movePreviewGuideLineRef.current.clear();
        movePreviewGuideLineRef.current.visible = false;
      }

      const tipX = Math.round(rect.left + previewIconX / scaleX);
      const tipY = Math.round(rect.top + previewIconY / scaleY);
      const tipKey = `${tooltipCharge}|${tipX}|${tipY}`;
      if (tipKey !== lastMovePreviewTooltipKey) {
        lastMovePreviewTooltipKey = tipKey;
        setMovePreviewDistanceTooltip({
          visible: true,
          text: tooltipCharge,
          x: tipX,
          y: tipY,
        });
      }

      hoveredHexRef.current = { col: iconCol, row: iconRow };
      hoveredHexContextRef.current = {
        mode,
        unitId: movementPreviewUnitId,
        modelId: isPerModelMove ? (effectivePerModelPlanRef.current?.activeModelId ?? null) : null,
      };

      // Find nearest valid center for LoS (icon may be on a footprint extension hex)
      let losCol = iconCol;
      let losRow = iconRow;
      const anchorPoolForLos =
        isPerModelMove && effectivePerModelPlan?.activeModelId
          ? effectivePerModelPoolRef?.current
          : phase === "charge" && mode === "chargePreview"
            ? chargeDestPoolRef?.current
            : resolvedMoveDestPoolRef.current;
      if (!anchorPoolForLos?.has(`${iconCol},${iconRow}`)) {
        const nearLos = nearestDestToPixel(container.position.x, container.position.y);
        if (nearLos) {
          losCol = nearLos.col;
          losRow = nearLos.row;
        }
      }

      const prevLos = losHexRef.current;
      const losHexChanged = !prevLos || prevLos.col !== losCol || prevLos.row !== losRow;
      losHexRef.current = { col: losCol, row: losRow };

      // Move phase movePreview: track ghost destination on the valid pool.
      // Calls onStartMovePreview which also re-sets mode/pendingPreviewAction (idempotent).
      if (
        phase === "move" &&
        mode === "movePreview" &&
        losHexChanged &&
        movePreview &&
        resolvedMoveDestPoolRef.current?.has(`${losCol},${losRow}`)
      ) {
        onStartMovePreview(movePreview.unitId, losCol, losRow);
      }

      if (phase === "shoot" && mode === "advancePreview") {
        setShootAdvanceLosAnchor((prev) =>
          prev && prev.col === losCol && prev.row === losRow ? prev : { col: losCol, row: losRow }
        );
      }

      if (
        losHexChanged &&
        !(phase === "charge" && mode === "chargePreview") &&
        !(phase === "shoot" && mode === "advancePreview") &&
        !(phase === "move" && mode === "movePreview")
      ) {
        triggerLosForHex(losCol, losRow, LOS_MOUSEMOVE_DEBOUNCE_MS);
      }
    };

    // LoS move preview : visuel WASM coalescé par frame, backend throttlé pour blinks/couvert.
    let losDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    let losEffectActive = true;
    let visualLosFrame: number | null = null;
    let pendingVisualLosRequest: {
      col: number;
      row: number;
      selectedUnit: Unit;
      range: number;
    } | null = null;
    let pendingLosRequest: {
      col: number;
      row: number;
      selectedUnit: Unit | undefined;
    } | null = null;
    let losBackendRequestInFlight = false;
    const LOS_MOUSEMOVE_DEBOUNCE_MS = 25;
    const LOS_INITIAL_PREVIEW_DEBOUNCE_MS = 0;
    // Cases visibles des cibles ciblables renvoyées par le backend (async) pour la position
    // survolée courante. Peintes par-dessus le cône WASM → cohérence blink↔visuel. Rafraîchies
    // par processBackendLosRequest, qui redéclenche ensuite le dessin visuel.
    let movePreviewVisibleTargetCells: Array<{ col: number; row: number }> = [];

    const scheduleVisualLosForHex = (
      col: number,
      row: number,
      selectedUnit: Unit,
      range: number
    ) => {
      pendingVisualLosRequest = { col, row, selectedUnit, range };
      if (visualLosFrame !== null) return;
      visualLosFrame = window.requestAnimationFrame(() => {
        visualLosFrame = null;
        const pending = pendingVisualLosRequest;
        pendingVisualLosRequest = null;
        if (!pending || !losEffectActive || !isWasmReady()) return;

        const app = appRef.current;
        if (!app) return;

        if (!hoverOverlayRef.current || hoverOverlayRef.current.destroyed) {
          const root = new PIXI.Container();
          root.name = "los-hover-polar-masked";
          root.eventMode = "none";
          root.zIndex = 40;
          app.stage.addChild(root);
          hoverOverlayRef.current = root;
        }
        const overlay = hoverOverlayRef.current;
        const ucByModel = unitsCacheModelCenters(gameState?.units_cache);
        const visualPreview = buildLosPreviewFromSource({
          source: {
            unit: pending.selectedUnit,
            fromCol: pending.col,
            fromRow: pending.row,
          },
          units,
          boardCols: BOARD_COLS_H,
          boardRows: BOARD_ROWS_H,
          wallHexes: boardConfig.wall_hexes,
          wallHexesOverride,
          obscuringZones: losObscuringZones,
          terrainZones: losTerrainZones,
          maxRange: pending.range,
          distanceMetric: rangedPreviewMetric(gameConfig),
          unitsCacheByModel: ucByModel,
          shooterModelCenters:
            pending.col === pending.selectedUnit.col && pending.row === pending.selectedUnit.row
              ? ucByModel?.[String(pending.selectedUnit.id)]
              : undefined,
        });
        const losUnionLayout: HexUnionMaskLayout = {
          HEX_HORIZ_SPACING: HEX_WIDTH_H,
          HEX_WIDTH: HEX_WIDTH_H,
          HEX_HEIGHT: HEX_HEIGHT_H,
          HEX_VERT_SPACING: HEX_HEIGHT_H,
          MARGIN: MARGIN_H,
          gridHexRadius: HEX_RADIUS_H,
        };
        const allVisualLosCells = [
          ...visualPreview.terrainCoverCells,
          ...visualPreview.clearCells,
          ...movePreviewVisibleTargetCells,
        ];
        mountLosPolarClippedByVisibleUnion(
          overlay,
          allVisualLosCells,
          visualPreview.terrainCoverCells,
          losUnionLayout,
          LOS_PREVIEW_CLEAR_HEX,
          0.4,
          LOS_PREVIEW_COVER_HEX,
          0.4,
          app.renderer
        );
        overlay.visible = true;
      });
    };

    const scheduleBackendLosRequest = (delayMs: number) => {
      if (losDebounceTimer || losBackendRequestInFlight) return;
      losDebounceTimer = setTimeout(() => {
        losDebounceTimer = null;
        void processBackendLosRequest();
      }, delayMs);
    };

    async function processBackendLosRequest(): Promise<void> {
      if (losBackendRequestInFlight) return;
      losBackendRequestInFlight = true;
      try {
        const pending = pendingLosRequest;
        pendingLosRequest = null;
        if (!pending) return;
        const { col, row, selectedUnit } = pending;
        const app = appRef.current;
        if (!app) {
          return;
        }
        if (!selectedUnit) {
          setMovePreviewLosBlinkIds([]);
          setMovePreviewLosCoverById({});
          setMovePreviewLosTooFarById({});
          return;
        }
        const range = getMaxRangedRange(selectedUnit);
        if (range <= 0 || !selectedUnit.RNG_WEAPONS?.length) {
          setMovePreviewLosBlinkIds([]);
          setMovePreviewLosCoverById({});
          setMovePreviewLosTooFarById({});
          return;
        }

        if (!hoverOverlayRef.current || hoverOverlayRef.current.destroyed) {
          const root = new PIXI.Container();
          root.name = "los-hover-polar-masked";
          root.eventMode = "none";
          root.zIndex = 40;
          app.stage.addChild(root);
          hoverOverlayRef.current = root;
        }
        const overlay = hoverOverlayRef.current;

        const cacheKey = [
          String(selectedUnit.id),
          `${col},${row}`,
          unitsBoardLayoutKey,
          String(gameState?.turn ?? ""),
          String(gameState?.episode_steps ?? ""),
        ].join("|");

        let losPreview = movePreviewBackendLosCacheRef.current.get(cacheKey);
        if (!losPreview) {
          const response = await fetch("/api/game/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "preview_shoot_from_position",
              unitId: String(selectedUnit.id),
              destCol: col,
              destRow: row,
              advancePosition: false,
              includeLosCells: false,
            }),
          });
          if (!response.ok) {
            throw new Error(`preview_shoot_from_position failed with HTTP ${response.status}`);
          }
          const data = await response.json();
          if (data?.success !== true) {
            throw new Error("preview_shoot_from_position returned success=false");
          }
          losPreview = parseBackendMoveLosPreviewPayload(data.result, cacheKey);
          if (movePreviewBackendLosCacheRef.current.size >= MOVE_PREVIEW_LOS_CACHE_MAX_ENTRIES) {
            const oldestKey = movePreviewBackendLosCacheRef.current.keys().next().value;
            if (typeof oldestKey !== "string") {
              throw new Error("Move preview LoS cache oldest key is invalid");
            }
            movePreviewBackendLosCacheRef.current.delete(oldestKey);
          }
          movePreviewBackendLosCacheRef.current.set(cacheKey, losPreview);
        }

        if (!losEffectActive) return;

        const losUnionLayout: HexUnionMaskLayout = {
          HEX_HORIZ_SPACING: HEX_WIDTH_H,
          HEX_WIDTH: HEX_WIDTH_H,
          HEX_HEIGHT: HEX_HEIGHT_H,
          HEX_VERT_SPACING: HEX_HEIGHT_H,
          MARGIN: MARGIN_H,
          gridHexRadius: HEX_RADIUS_H,
        };
        const allLosCells = [...losPreview.coverCells, ...losPreview.clearCells];
        if (allLosCells.length > 0) {
          mountLosPolarClippedByVisibleUnion(
            overlay,
            allLosCells,
            losPreview.coverCells,
            losUnionLayout,
            LOS_PREVIEW_CLEAR_HEX,
            0.4,
            LOS_PREVIEW_COVER_HEX,
            0.4,
            app.renderer
          );
          overlay.visible = true;
        }

        if (!losEffectActive) return;
        const currentLosHex = losHexRef.current;
        if (!currentLosHex || currentLosHex.col !== col || currentLosHex.row !== row) return;
        setMovePreviewLosBlinkIds(losPreview.blinkIds);
        setMovePreviewLosCoverById(losPreview.coverByUnitId);
        setMovePreviewLosTooFarById(losPreview.hiddenTooFarByUnitId);
        // Cases visibles des cibles (backend) pour cette position → redessine le cône WASM
        // en les incluant (cohérence blink↔visuel). Le cône a déjà été tracé au survol sans
        // elles ; ce 2e passage les ajoute une fois la réponse backend arrivée.
        movePreviewVisibleTargetCells = losPreview.visibleTargetCells;
        if (selectedUnit) {
          const visRange = getMaxRangedRange(selectedUnit);
          if (visRange > 0 && selectedUnit.RNG_WEAPONS?.length) {
            scheduleVisualLosForHex(col, row, selectedUnit, visRange);
          }
        }
      } catch (error) {
        if (!losEffectActive) return;
        setMovePreviewLosBlinkIds([]);
        setMovePreviewLosCoverById({});
        setMovePreviewLosTooFarById({});
        console.error("Move preview backend LoS failed:", error);
      } finally {
        losBackendRequestInFlight = false;
        if (losEffectActive && pendingLosRequest) {
          scheduleBackendLosRequest(LOS_INITIAL_PREVIEW_DEBOUNCE_MS);
        }
      }
    }

    const triggerLosForHex = (col: number, row: number, delayMs: number) => {
      if (phase === "move" && gameState?.active_movement_unit == null) {
        setMovePreviewLosBlinkIds([]);
        setMovePreviewLosCoverById({});
        setMovePreviewLosTooFarById({});
        return;
      }
      const sourceUnitId =
        phase === "move"
          ? parseRequiredUnitId(gameState?.active_movement_unit, "gameState.active_movement_unit")
          : mode === "movePreview" && movePreview
            ? movePreview.unitId
            : selectedUnitId;
      const selectedUnit = units.find((u) => String(u.id) === String(sourceUnitId));
      // Nouveau hex survolé → on repart sans les cases cibles de l'hex précédent (le backend
      // les recalculera pour cette position et redessinera). Évite un flash de cases périmées.
      movePreviewVisibleTargetCells = [];
      if (selectedUnit) {
        const range = getMaxRangedRange(selectedUnit);
        if (range > 0 && selectedUnit.RNG_WEAPONS?.length) {
          scheduleVisualLosForHex(col, row, selectedUnit, range);
        }
      }
      pendingLosRequest = {
        col,
        row,
        selectedUnit,
      };
      scheduleBackendLosRequest(delayMs);
    };

    // LoS preview during squad-level movePreview hover is intentionally disabled:
    // user only wants LoS computed when a single figurine is selected post-commit
    // (per-fig preview flow, not group hover). Re-enabling would re-introduce the
    // backend MOVE_LOS_PREVIEW_PERF spam on every hovered hex (300ms per call).

    if (canvas) canvas.addEventListener("mousemove", onMouseMove);
    // Restaure la visibilité du ghost si on était déjà en hover (la cleanup l'a caché sans le déplacer)
    {
      const activeMovIdRestore =
        phase === "move" && gameState?.active_movement_unit != null
          ? parseRequiredUnitId(gameState.active_movement_unit, "gameState.active_movement_unit")
          : null;
      const previewUnitIdRestore = phase === "move" ? activeMovIdRestore : selectedUnitId;
      const allowRestore =
        previewUnitIdRestore !== null &&
        ((effectivePhase === "move" && activeMovIdRestore !== null) ||
          mode === "advancePreview" ||
          (phase === "charge" && mode === "chargePreview") ||
          (phase === "fight" && (mode === "pileInPreview" || mode === "consolidationPreview")));
      const sameContext =
        hoveredHexContextRef.current?.mode === mode &&
        hoveredHexContextRef.current?.unitId === previewUnitIdRestore;
      if (!sameContext) {
        hoveredHexRef.current = null;
        hoveredHexContextRef.current = null;
      }
      if (
        allowRestore &&
        sameContext &&
        hoveredHexRef.current &&
        hoverSpriteRef.current &&
        !hoverSpriteRef.current.destroyed
      ) {
        hoverSpriteRef.current.visible = true;
        // hoverOverlayRef n'est pas rempli en advancePreview (triggerLosForHex y est skippé) :
        // le ghost LoS vient de appendShootingPreviewCells. Restaurer ici afficherait du contenu périmé.
        // En movePreview move-phase : LoS désactivée pendant le hover squad (user requirement).
        const allowOverlayRestore =
          mode !== "advancePreview" && !(phase === "move" && mode === "movePreview");
        if (allowOverlayRestore && hoverOverlayRef.current && !hoverOverlayRef.current.destroyed) {
          hoverOverlayRef.current.visible = true;
        }
      }
    }
    return () => {
      losEffectActive = false;
      if (losDebounceTimer) clearTimeout(losDebounceTimer);
      if (visualLosFrame !== null) window.cancelAnimationFrame(visualLosFrame);
      if (canvas) canvas.removeEventListener("mousemove", onMouseMove);
      if (hoverOverlayRef.current) hoverOverlayRef.current.visible = false;
      if (hoverSpriteRef.current) hoverSpriteRef.current.visible = false;
      if (movePreviewGuideLineRef.current && !movePreviewGuideLineRef.current.destroyed) {
        movePreviewGuideLineRef.current.clear();
        movePreviewGuideLineRef.current.visible = false;
      }
      setMovePreviewDistanceTooltip(null);
      hoverMoveOrientationStepRef.current = null;
      losHexRef.current = null;
    };
  }, [
    boardConfig,
    gameConfig,
    phase,
    effectivePhase,
    mode,
    isDeploymentMove,
    movePreview,
    selectedUnitId,
    units,
    unitsBoardLayoutKey,
    gameState,
    chargeTargetId,
    chargeReferenceHex,
    chargeRoll,
    pendingMoveAfterShooting,
    getAdvanceDestinations,
    availableCellsOverride,
    wallHexesOverride,
    losObscuringZones,
    losTerrainZones,
    footprintZoneRef?.current,
    resolvedMoveDestPoolRef.current?.has,
    effectivePerModelPlan?.activeModelId,
    isPerModelMove,
    effectivePerModelPoolRef?.current,
    footprintMaskLoopsRef?.current,
    footprintZoneRef,
    chargeFootprintZoneRef?.current?.has,
    chargeFootprintZoneRef?.current,
    resolvedMoveDestPoolRef.current.size,
    resolvedMoveDestPoolRef.current,
    chargeDestPoolRef?.current,
    chargeDestDistancesRef?.current?.get,
    chargeDestDistancesRef?.current,
    resolvedMoveDestPoolRef,
    footprintMaskLoopsRef,
    onStartMovePreview,
  ]);

  /**
   * Move / advance / charge / pile-in : clic gauche = valider le déplacement à l’hex de l’icône (``hoveredHexRef``).
   * La hitArea du plateau est sous les unités (zIndex) : ``boardHexClick`` ne recevait souvent pas le clic.
   * Capture sur le canvas avant Pixi — même code que ``boardClickHandler`` via l’événement synthétique.
   */
  useEffect(() => {
    if (measureMode.kind !== "off") return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;

    const poolHasHoveredAnchor = (key: string): boolean => {
      if (isPerModelMove) {
        return effectivePerModelPoolRef?.current?.has(key) ?? false;
      }
      if (phase === "charge" && mode === "chargePreview") {
        return chargeDestPoolRef?.current?.has(key) ?? false;
      }
      return resolvedMoveDestPoolRef.current?.has(key) ?? false;
    };

    const shouldConfirmAtIcon =
      (mode === "squadModelMove" && effectivePerModelPlan?.activeModelId != null) ||
      (perModelChargeLike && effectivePerModelPlan?.activeModelId != null) ||
      (selectedUnitId != null &&
        ((effectivePhase === "move" && mode === "select") ||
          (effectivePhase === "move" && mode === "movePreview") ||
          mode === "advancePreview" ||
          (phase === "charge" && mode === "chargePreview") ||
          (phase === "fight" && (mode === "pileInPreview" || mode === "consolidationPreview"))));

    if (!shouldConfirmAtIcon) return;

    const onPointerDownCapture = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const h = hoveredHexRef.current;
      if (!h) {
        return;
      }
      const key = `${h.col},${h.row}`;
      if (!poolHasHoveredAnchor(key)) {
        return;
      }

      e.preventDefault();
      e.stopImmediatePropagation();

      window.dispatchEvent(
        new CustomEvent("boardHexClick", {
          detail: {
            col: h.col,
            row: h.row,
            phase: effectivePhase,
            mode,
            selectedUnitId,
            orientation: hoverMoveOrientationStepRef.current ?? undefined,
            activeModelId: effectivePerModelPlan?.activeModelId ?? null,
          },
        })
      );
    };

    canvas.addEventListener("pointerdown", onPointerDownCapture, true);
    return () => canvas.removeEventListener("pointerdown", onPointerDownCapture, true);
  }, [
    boardConfig,
    measureMode.kind,
    phase,
    effectivePhase,
    mode,
    selectedUnitId,
    isPerModelMove,
    perModelChargeLike,
    effectivePerModelPlan?.activeModelId,
    effectivePerModelPoolRef?.current?.has,
    chargeDestPoolRef?.current?.has,
    resolvedMoveDestPoolRef.current?.has,
  ]);

  // Native DOM double-click on the canvas: enter movePreview mode for the squad
  // whose footprint contains the clicked hex. Routed via boardUnitDoubleClick so
  // boardClickHandler centralises the move-phase routing.
  // We use the browser's dblclick (OS-level click cadence) rather than PIXI's
  // e.detail, which resets to 1 across React re-renders that recreate unitCircle.
  useEffect(() => {
    if (phase !== "move" && phase !== "deployment") return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;

    const onDoubleClick = (e: MouseEvent) => {
      if (e.button !== 0) return;
      // Déploiement : double-clic sur une escouade posée (plan provisoire) → active le suivi du
      // bloc (squad move). Pas de recherche units_cache (l'escouade n'y est pas avant le commit).
      if (phase === "deployment") {
        if (mode === "deploymentMove" && deployPlan?.placed) {
          e.preventDefault();
          // Préempte la sélection per-fig différée du 1er clic → pas de flash de LoS.
          if (deploySelectTimerRef.current !== null) {
            clearTimeout(deploySelectTimerRef.current);
            deploySelectTimerRef.current = null;
          }
          deployCallbacksRef.current.onStartSquadFollowDeploy?.();
        }
        return;
      }
      // Supprime le dblclick natif si onEntryPointerDown l'a déjà géré (< 500ms),
      // pour éviter de déclencher handleStartMovePreview en double.
      if (performance.now() - dblClickFromEntryRef.current < 500) {
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const { col, row } = pixelToHex(
        px,
        py,
        HEX_RADIUS,
        MARGIN,
        boardConfig.cols,
        boardConfig.rows
      );
      if (col < 0 || col >= boardConfig.cols || row < 0 || row >= boardConfig.rows) {
        return;
      }

      const unitsCache = gameState?.units_cache as
        | Record<
            string,
            {
              occupied_hexes_by_model?: Record<string, [number, number]>;
              col?: number;
              row?: number;
              player?: number;
            }
          >
        | undefined;
      if (!unitsCache) {
        return;
      }
      // Tolerance: model base may span several hexes visually (Terminator
      // BASE_SIZE=16 → ~2-hex radius). Match any model within cube distance 4
      // and pick the nearest. Threshold high enough for large bases without
      // matching a distant squad.
      const HEX_HIT_TOLERANCE = 4;
      const clickCube = offsetToCube(col, row);
      let foundUnitId: number | string | null = null;
      let foundCol = -1;
      let foundRow = -1;
      let bestDistance = Infinity;
      for (const [uid, entry] of Object.entries(unitsCache)) {
        if (entry.player !== current_player) continue;
        const occupied = entry.occupied_hexes_by_model;
        const positions: Array<[number, number]> = occupied
          ? (Object.values(occupied) as Array<[number, number]>)
          : entry.col != null && entry.row != null
            ? [[entry.col, entry.row]]
            : [];
        for (const [mC, mR] of positions) {
          const d = cubeDistance(clickCube, offsetToCube(mC, mR));
          if (d <= HEX_HIT_TOLERANCE && d < bestDistance) {
            bestDistance = d;
            foundUnitId = Number.isNaN(Number(uid)) ? uid : Number(uid);
            foundCol = entry.col ?? mC;
            foundRow = entry.row ?? mR;
          }
        }
      }
      // Fallback : après handleConfirmMove, les unités sont à des positions PROVISOIRES dans
      // squadMovePlan (pas encore commitées backend). Si units_cache échoue, chercher dans le plan.
      if (foundUnitId === null) {
        const plan = squadMovePlanRef.current;
        if (plan) {
          for (const pos of Object.values(plan.models)) {
            const d = cubeDistance(clickCube, offsetToCube(pos.col, pos.row));
            if (d <= HEX_HIT_TOLERANCE && d < bestDistance) {
              bestDistance = d;
              foundUnitId = plan.unitId;
              // Utiliser la position d'ancrage du cache si dispo (position de référence pour le preview)
              const cacheEntry = unitsCache?.[String(plan.unitId)];
              foundCol = cacheEntry?.col ?? pos.col;
              foundRow = cacheEntry?.row ?? pos.row;
            }
          }
        }
      }
      if (foundUnitId === null) {
        return;
      }

      e.preventDefault();
      window.dispatchEvent(
        new CustomEvent("boardUnitDoubleClick", {
          detail: {
            unitId: foundUnitId,
            unitCol: foundCol,
            unitRow: foundRow,
            phase,
            mode,
            selectedUnitId,
          },
        })
      );
    };

    canvas.addEventListener("dblclick", onDoubleClick);
    return () => canvas.removeEventListener("dblclick", onDoubleClick);
  }, [
    phase,
    mode,
    selectedUnitId,
    boardConfig,
    gameState?.units_cache,
    current_player,
    deployPlan?.placed,
  ]);

  // Déploiement — suivi du bloc (mode following) : le bloc entier suit le curseur en continu.
  // On translate le plan (1re fig sous le curseur) à chaque changement d'hex ; le rendu du plan
  // (figs + voile rouge) suit. Réutilise handleSquadMoveDeploy (translation existante). Pas de LoS.
  useEffect(() => {
    if (!isDeploymentMove) return;
    if (!deployPlan?.following || deployPlan.activeModelId) return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;
    let lastKey = "";
    const onMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const { col, row } = pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
      if (col < 0 || col >= boardConfig.cols || row < 0 || row >= boardConfig.rows) return;
      // Snap de l'ancre sur le pool d'ancres valides (toutes les empreintes du bloc ⊆ zone),
      // comme le move snappe sur son pool. Hors zone → ancre figée sur le plus proche valide.
      const pool = deploySquadPoolRef?.current;
      if (!pool || pool.size === 0) return;
      let tCol = col;
      let tRow = row;
      if (!pool.has(`${col},${row}`)) {
        const cur = offsetToCube(col, row);
        let bestD = Infinity;
        let best: [number, number] | null = null;
        for (const k of pool) {
          const sep = k.indexOf(",");
          const pc = Number(k.slice(0, sep));
          const pr = Number(k.slice(sep + 1));
          const d = cubeDistance(cur, offsetToCube(pc, pr));
          if (d < bestD) {
            bestD = d;
            best = [pc, pr];
          }
        }
        if (!best) return;
        tCol = best[0];
        tRow = best[1];
      }
      const key = `${tCol},${tRow}`;
      if (key === lastKey) return;
      lastKey = key;
      deployCallbacksRef.current.onSquadMoveDeploy?.(tCol, tRow);
    };
    canvas.addEventListener("mousemove", onMove);
    return () => canvas.removeEventListener("mousemove", onMove);
  }, [
    isDeploymentMove,
    deployPlan?.following,
    deployPlan?.activeModelId,
    boardConfig,
    deploySquadPoolRef?.current,
  ]);

  // squad.md brique 3 : ENTREE single-clic. En phase move + mode select, un clic gauche sur
  // une fig OWN entre en mode plan par-figurine + selectionne cette fig. Capture-phase +
  // stopImmediatePropagation pour empecher la selection rigide par defaut (PIXI → onSelectUnit).
  useEffect(() => {
    if (phase !== "move" || mode !== "select") return;
    if (measureMode.kind !== "off") return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;

    const onEntryPointerDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      if (e.target !== canvas) return;
      // Allocation manuelle des pertes en cours (Desperate Escape) : NE PAS entrer en
      // mode plan par-figurine. On bail SANS stopImmediatePropagation pour laisser le clic
      // au handler d'allocation move (effet suivant, enregistré après en capture-phase).
      if (manualAllocationRef.current) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const { col, row } = pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
      const unitsCache = gameState?.units_cache as
        | Record<
            string,
            {
              occupied_hexes_by_model?: Record<string, [number, number]>;
              col?: number;
              row?: number;
              player?: number;
            }
          >
        | undefined;
      if (!unitsCache) return;
      const HEX_HIT_TOLERANCE = 4;
      const clickCube = offsetToCube(col, row);
      let foundUnitId: number | string | null = null;
      let foundModelId: string | null = null;
      let foundUnitCol = -1;
      let foundUnitRow = -1;
      let bestDistance = Infinity;
      for (const [uid, entry] of Object.entries(unitsCache)) {
        if (entry.player !== current_player) continue;
        if (!eligibleUnitIds.includes(Number(uid))) continue;
        const byModel = entry.occupied_hexes_by_model;
        if (!byModel) continue;
        for (const [mid, pos] of Object.entries(byModel)) {
          const d = cubeDistance(clickCube, offsetToCube(pos[0], pos[1]));
          if (d <= HEX_HIT_TOLERANCE && d < bestDistance) {
            bestDistance = d;
            foundUnitId = Number.isNaN(Number(uid)) ? uid : Number(uid);
            foundModelId = mid;
            foundUnitCol = entry.col ?? pos[0];
            foundUnitRow = entry.row ?? pos[1];
          }
        }
      }
      if (foundUnitId === null || foundModelId === null) return;
      // stopImmediatePropagation en capture-phase sur document suffit à bloquer PIXI (le canvas ne
      // reçoit jamais l'event). On NE PAS appeler preventDefault() : cela supprimerait la synthèse
      // des events click/dblclick par le navigateur.
      e.stopImmediatePropagation();

      // Détection double-click manuelle : ne pas dépendre du dblclick natif qui peut être supprimé
      // par PIXI (autoPreventDefault) si React re-render a supprimé onEntryPointerDown entre les 2 clics.
      const now = performance.now();
      const lastClick = lastUnitClickRef.current;
      const isDoubleClick =
        lastClick !== null &&
        Number(lastClick.unitId) === Number(foundUnitId) &&
        now - lastClick.ts < 500;
      lastUnitClickRef.current = isDoubleClick ? null : { unitId: foundUnitId, ts: now };

      if (isDoubleClick) {
        dblClickFromEntryRef.current = now;
        window.dispatchEvent(
          new CustomEvent("boardUnitDoubleClick", {
            detail: {
              unitId: foundUnitId,
              unitCol: foundUnitCol,
              unitRow: foundUnitRow,
              phase,
              mode,
              selectedUnitId,
            },
          })
        );
        return;
      }

      const uid = foundUnitId;
      const mid = foundModelId;
      void (async () => {
        // Ce handler est gardé en amont par ``mode === "select"`` (useEffect) : on sélectionne la fig.
        await squadMoveCallbacksRef.current.onStartSquadModelMove?.(uid);
        // Si le plan a été annulé pendant l'await (ex: double-clic → handleStartMovePreview → setSquadMovePlan(null)),
        // ne pas appeler onSelectModelForMove (ça activerait une fig dans un plan obsolète).
        const planAfterStart = squadMovePlanRef.current;
        if (!planAfterStart || Number(planAfterStart.unitId) !== Number(uid)) return;
        await squadMoveCallbacksRef.current.onSelectModelForMove?.(mid);
      })();
    };

    document.addEventListener("pointerdown", onEntryPointerDown, true);
    return () => document.removeEventListener("pointerdown", onEntryPointerDown, true);
  }, [
    phase,
    mode,
    measureMode.kind,
    boardConfig,
    gameState?.units_cache,
    current_player,
    eligibleUnitIds,
    selectedUnitId,
  ]);

  // TEST/DEBUG : modes « battle-shock test » / « a chargé test ». Quand l'un des toggles est ON,
  // un clic DROIT sur n'importe quelle unité (tous players, statut indifférent) force le(s) statut(s)
  // correspondant(s) : battle-shock (toutes phases) et/ou « a chargé » (phase charge uniquement).
  // Les deux ON → applique les deux. Capture-phase + stopImmediatePropagation : coupe avant PIXI
  // (skip/cancel/sélection) et avant le menu contextuel. Le clic gauche n'est jamais touché.
  useEffect(() => {
    if (!battleShockTestMode && !chargedTestMode) return;
    if (measureMode.kind !== "off") return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;

    const onRightClickBattleShock = (e: PointerEvent) => {
      if (e.button !== 2) return;
      if (e.target !== canvas) return;
      // « A chargé » n'est applicable qu'en phase charge (bouton grisé ailleurs).
      const willShock = !!battleShockTestMode;
      const willCharge = !!chargedTestMode && phase === "charge";
      // Aucune action applicable → ne pas couper le clic droit normal (skip/cancel).
      if (!willShock && !willCharge) return;
      const unitsCache = gameState?.units_cache as
        | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
        | undefined;
      if (!unitsCache) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const { col, row } = pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
      const HEX_HIT_TOLERANCE = 4;
      const clickCube = offsetToCube(col, row);
      let foundUnitId: number | string | null = null;
      let bestDistance = Infinity;
      // Toutes les unités, sans filtre de player ni d'éligibilité.
      for (const [uid, entry] of Object.entries(unitsCache)) {
        const byModel = entry.occupied_hexes_by_model;
        if (!byModel) continue;
        for (const pos of Object.values(byModel)) {
          const d = cubeDistance(clickCube, offsetToCube(pos[0], pos[1]));
          if (d <= HEX_HIT_TOLERANCE && d < bestDistance) {
            bestDistance = d;
            foundUnitId = Number.isNaN(Number(uid)) ? uid : Number(uid);
          }
        }
      }
      if (foundUnitId === null) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      if (willShock) void onForceBattleShock?.(foundUnitId);
      if (willCharge) void onForceCharged?.(foundUnitId);
    };

    document.addEventListener("pointerdown", onRightClickBattleShock, true);
    return () => document.removeEventListener("pointerdown", onRightClickBattleShock, true);
  }, [
    battleShockTestMode,
    chargedTestMode,
    phase,
    measureMode.kind,
    boardConfig,
    gameState?.units_cache,
    onForceBattleShock,
    onForceCharged,
  ]);

  // Desperate Escape (phase move) : allocation manuelle des mortal wounds. L'effet tir
  // (gated phase==="shoot") ne traite pas le clic en move ; on reproduit ici son bloc
  // d'allocation. Enregistré APRÈS onEntryPointerDown (qui bail sur manualAllocationRef
  // sans stopImmediate) → ce handler capte le clic et bloque tout traitement aval.
  useEffect(() => {
    if (phase !== "move") return;
    if (measureMode.kind !== "off") return;
    if (!boardConfig) return;

    const HEX_HIT_TOLERANCE = 4;
    const onPointerDown = (e: PointerEvent) => {
      // Canvas/app résolus PARESSEUSEMENT au clic : à l'enregistrement de l'effet, le canvas
      // PIXI peut ne pas encore exister (init asynchrone). Les résoudre ici garantit que le
      // listener est attaché dès la phase move, sans dépendre du timing d'init.
      const canvas = canvasContainerRef.current?.querySelector("canvas");
      const app = appRef.current;
      if (!canvas || !app) return;
      if (e.target !== canvas) return;
      const alloc = manualAllocationRef.current;
      if (!alloc) return;
      if (e.button !== 0) return; // clic droit ignoré pendant l'allocation
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const { col, row } = pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
      // Allocation active : on bloque TOUT clic gauche board (pas seulement les matchs) pour
      // éviter qu'un clic hors figurine confirme/annule un move pendant l'attribution.
      e.stopImmediatePropagation();
      const clickCube = offsetToCube(col, row);
      let chosen: string | null = null;
      let bestD = Infinity;
      for (const c of alloc.choices) {
        const d = cubeDistance(clickCube, offsetToCube(c.col, c.row));
        if (d <= HEX_HIT_TOLERANCE && d < bestD) {
          bestD = d;
          chosen = c.model_id;
        }
      }
      if (chosen) {
        void onAllocateModelRef.current?.(chosen);
      }
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [phase, measureMode.kind, boardConfig]);

  // squad.md brique 3 : en mode plan par-figurine, un clic gauche sur une fig de l'escouade
  // la selectionne (resout model_id depuis les positions provisoires du plan) → onSelectModelForMove.
  // Phase bubble : si le clic a deja servi a POSER la fig active (hex dans son pool, capture-phase
  // stopImmediatePropagation), ce handler ne se declenche pas.
  useEffect(() => {
    if (!isPerModelMove || !effectivePerModelPlan) return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;
    const plan = effectivePerModelPlan;

    const onPointerDownSelect = (e: PointerEvent) => {
      if (e.button !== 0) return;
      // Ignorer le clic qui a confirmé le movePreview (même événement, propagé après la transition)
      if (
        squadMoveEntryTimeRef.current !== null &&
        performance.now() - squadMoveEntryTimeRef.current < 300
      ) {
        squadMoveEntryTimeRef.current = null;
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const { col, row } = pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
      // Resout la fig la plus proche de l'hex clique parmi les positions provisoires du plan.
      const HEX_HIT_TOLERANCE = 4;
      const clickCube = offsetToCube(col, row);
      let foundModelId: string | null = null;
      let bestDistance = Infinity;
      for (const [mid, pos] of Object.entries(plan.models)) {
        const d = cubeDistance(clickCube, offsetToCube(pos.col, pos.row));
        if (d <= HEX_HIT_TOLERANCE && d < bestDistance) {
          bestDistance = d;
          foundModelId = mid;
        }
      }
      if (isDeploymentMove) {
        const dplan = deployPlan;
        if (!dplan) return;
        const pool = deployPoolRef?.current;
        const inPool = pool?.has(`${col},${row}`) ?? false;
        // 1) Escouade pas encore posée : 1er clic dans la zone → formation compacte (backend).
        if (!dplan.placed) {
          if (inPool) {
            void deployCallbacksRef.current.onDeployDropSquad?.(col, row);
          }
          return;
        }
        // Ignorer le 2e clic d'un double-clic (le double-clic active le suivi via onDoubleClick) :
        // sinon il poserait/sélectionnerait une figurine parasitement.
        const nowClick = performance.now();
        const isDoubleClickSecond = nowClick - lastDeployClickTimeRef.current < 350;
        lastDeployClickTimeRef.current = nowClick;
        if (isDoubleClickSecond) return;
        // 2) Mode suivi squad (le bloc suit le curseur) : tout clic pose le bloc (freeze),
        //    miroir du move (clic = pose). Prioritaire sur la sélection fig.
        if (dplan.following) {
          deployCallbacksRef.current.onFreezeSquadDeploy?.();
          return;
        }
        // 3) Fig active sélectionnée → pose à l'ancre SNAPPÉE du ghost (hoveredHexRef), validée
        //    contre le pool filtré empreinte-aware (deployModelPoolRef) — miroir exact de la preview
        //    et du move per-fig (shouldConfirmAtIcon). On n'utilise PAS l'hex brut sous le curseur :
        //    quand le curseur déborde sur une voisine, le ghost a déjà snappé sur l'ancre valide
        //    adjacente ; poser à l'hex brut chevaucherait (l'empreinte y mord la voisine).
        if (dplan.activeModelId) {
          const snapped = hoveredHexRef.current;
          const modelPool = deployModelPoolRef?.current;
          if (snapped && modelPool?.has(`${snapped.col},${snapped.row}`)) {
            deployCallbacksRef.current.onMoveDeployModelInPlan?.(
              dplan.activeModelId,
              snapped.col,
              snapped.row
            );
          }
          return;
        }
        // 4) Clic sur une figurine de l'escouade → sélection per-fig DIFFÉRÉE : on attend ~220 ms
        //    qu'un éventuel double-clic (squad mode) la préempte, sinon pas de flash de LoS per-fig.
        if (foundModelId) {
          if (foundModelId === dplan.activeModelId) return;
          const midToSelect = foundModelId;
          if (deploySelectTimerRef.current !== null) clearTimeout(deploySelectTimerRef.current);
          deploySelectTimerRef.current = setTimeout(() => {
            deploySelectTimerRef.current = null;
            deployCallbacksRef.current.onSelectDeployModel?.(midToSelect);
          }, 220);
          return;
        }
        return;
      }
      if (perModelChargeLike) {
        // Mode Focus : un clic sur une cible déclarée déclenche l'auto-placement (pas la pose de fig).
        // Hit-test sur les positions par-figurine de la cible (occupied_hexes_by_model, source unique).
        if (chargeFocusActive && (chargePreviewTargetIds?.length ?? 0) > 0) {
          const uc = gameState?.units_cache as
            | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
            | undefined;
          const hitTarget = (chargePreviewTargetIds ?? []).find((tid) => {
            const byModel = uc?.[String(tid)]?.occupied_hexes_by_model;
            if (!byModel) return false;
            return Object.values(byModel).some(
              ([oc, orr]) => cubeDistance(clickCube, offsetToCube(oc, orr)) <= HEX_HIT_TOLERANCE
            );
          });
          if (hitTarget != null) {
            void chargeModelCallbacksRef.current.onChargeFocusTargetClick?.(hitTarget);
            return;
          }
        }
        // Idem pile-in : clic sur une cible pile-in → mémorise la cible (+ autoplace si mode actif).
        if (isPileInModelMove && (pileInMovePlan?.pileInTargets?.length ?? 0) > 0) {
          const uc = gameState?.units_cache as
            | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
            | undefined;
          const hitTarget = (pileInMovePlan?.pileInTargets ?? []).find((tid) => {
            const byModel = uc?.[String(tid)]?.occupied_hexes_by_model;
            if (!byModel) return false;
            return Object.values(byModel).some(
              ([oc, orr]) => cubeDistance(clickCube, offsetToCube(oc, orr)) <= HEX_HIT_TOLERANCE
            );
          });
          if (hitTarget != null) {
            void pileInModelCallbacksRef.current.onPileInFocusTargetClick?.(hitTarget);
            return;
          }
        }
        // Consolidation Engaging : clic sur un ennemi candidat (≤3") → (dé)sélection de cible AVANT le move.
        if (
          isConsolidationModelMove &&
          (consolidationMovePlan?.engagingCandidates?.length ?? 0) > 0
        ) {
          const uc = gameState?.units_cache as
            | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
            | undefined;
          const hitFoe = (consolidationMovePlan?.engagingCandidates ?? []).find((tid) => {
            const byModel = uc?.[String(tid)]?.occupied_hexes_by_model;
            if (!byModel) return false;
            return Object.values(byModel).some(
              ([oc, orr]) => cubeDistance(clickCube, offsetToCube(oc, orr)) <= HEX_HIT_TOLERANCE
            );
          });
          if (hitFoe != null) {
            void consolidationModelCallbacksRef.current.onConsolidationSelectTarget?.(hitFoe);
            return;
          }
        }
        const active = plan.activeModelId;
        const poolRef = activeChargeLikePoolRef?.current;
        // 0) Clic sur une fig DÉJÀ POSÉE → la dé-poser (réajustement / cohésion).
        if (foundModelId && activeChargeLikePlan?.models?.[foundModelId]) {
          activeChargeLikeUnplace?.(foundModelId);
          return;
        }
        // 1) Clic dans le pool de la fig active → pose. Match exact, sinon snap à l'ancre la plus
        // proche (≤2 sous-hex) pour tolérer un clic légèrement hors hex.
        let placeC = col;
        let placeR = row;
        let ok = active != null && (poolRef?.has(`${col},${row}`) ?? false);
        if (active && !ok && poolRef && poolRef.size > 0) {
          const clickCube2 = offsetToCube(col, row);
          let bestD = Infinity;
          for (const k of poolRef) {
            const s = k.indexOf(",");
            const kc = Number(k.slice(0, s));
            const kr = Number(k.slice(s + 1));
            const d = cubeDistance(clickCube2, offsetToCube(kc, kr));
            if (d < bestD) {
              bestD = d;
              placeC = kc;
              placeR = kr;
            }
          }
          if (bestD <= 2) ok = true;
        }
        if (active && ok) {
          if (isPileInModelMove) {
            pileInModelCallbacksRef.current.onMovePileInModel?.(active, placeC, placeR);
          } else if (isConsolidationModelMove) {
            consolidationModelCallbacksRef.current.onMoveConsolidationModel?.(
              active,
              placeC,
              placeR
            );
          } else {
            chargeModelCallbacksRef.current.onMoveModelInChargePlan?.(active, placeC, placeR);
          }
          return;
        }
        // 2) Clic sur une AUTRE figurine (non active) → la sélectionne (si éligible, sinon ignoré par le hook).
        if (foundModelId && foundModelId !== active) {
          activeChargeLikeSelect?.(foundModelId);
        }
        return;
      }
      if (foundModelId === null) return;
      // Ne pas re-selectionner la fig deja active (le clic sert alors a la poser, gere ailleurs).
      if (foundModelId === plan.activeModelId) return;
      void squadMoveCallbacksRef.current.onSelectModelForMove?.(foundModelId);
    };

    canvas.addEventListener("pointerdown", onPointerDownSelect);
    return () => canvas.removeEventListener("pointerdown", onPointerDownSelect);
  }, [
    isPerModelMove,
    perModelChargeLike,
    isPileInModelMove,
    effectivePerModelPlan,
    activeChargeLikePlan,
    activeChargeLikeSelect,
    activeChargeLikeUnplace,
    activeChargeLikePoolRef?.current,
    boardConfig,
    chargeFocusActive,
    chargePreviewTargetIds,
    pileInMovePlan?.pileInTargets,
    isConsolidationModelMove,
    consolidationMovePlan?.engagingCandidates,
    gameState?.units_cache,
    isDeploymentMove,
    deployPlan,
    deployPoolRef?.current,
    deployModelPoolRef?.current,
  ]);

  // TIR par-figurine (PvP manuel) : phase shoot. Entrée sur escouade OWN multi-fig →
  // mode squadModelShoot. En mode : clic fig OWN = sélection (blink cibles valides),
  // clic ennemi = assignation cible de la fig active, clic droit fig = unassign.
  // Capture-phase + stopImmediatePropagation pour bloquer la sélection PIXI legacy
  // UNIQUEMENT quand on traite l'event (mono-fig → laisse passer au flux legacy).
  useEffect(() => {
    if (phase !== "shoot") return;
    if (measureMode.kind !== "off") return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;

    const HEX_HIT_TOLERANCE = 4;
    const getUnitsCache = () =>
      gameState?.units_cache as
        | Record<
            string,
            {
              occupied_hexes_by_model?: Record<string, [number, number]>;
              col?: number;
              row?: number;
              player?: number;
            }
          >
        | undefined;

    const resolveHex = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      return pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
    };

    const findOwnFig = (col: number, row: number) => {
      const uc = getUnitsCache();
      if (!uc) return null;
      const clickCube = offsetToCube(col, row);
      let best: { uid: number | string; mid: string; nFigs: number } | null = null;
      let bestD = Infinity;
      for (const [uid, entry] of Object.entries(uc)) {
        if (entry.player !== current_player) continue;
        const byModel = entry.occupied_hexes_by_model;
        if (!byModel) continue;
        const nFigs = Object.keys(byModel).length;
        for (const [mid, pos] of Object.entries(byModel)) {
          const d = cubeDistance(clickCube, offsetToCube(pos[0], pos[1]));
          if (d <= HEX_HIT_TOLERANCE && d < bestD) {
            bestD = d;
            best = { uid: Number.isNaN(Number(uid)) ? uid : Number(uid), mid, nFigs };
          }
        }
      }
      return best;
    };

    const findEnemyUnit = (col: number, row: number): number | string | null => {
      const uc = getUnitsCache();
      if (!uc) return null;
      const clickCube = offsetToCube(col, row);
      let best: number | string | null = null;
      let bestD = Infinity;
      for (const [uid, entry] of Object.entries(uc)) {
        if (entry.player === current_player) continue;
        const byModel = entry.occupied_hexes_by_model;
        const positions: Array<[number, number]> = byModel
          ? Object.values(byModel)
          : entry.col != null && entry.row != null
            ? [[entry.col, entry.row]]
            : [];
        for (const pos of positions) {
          const d = cubeDistance(clickCube, offsetToCube(pos[0], pos[1]));
          if (d <= HEX_HIT_TOLERANCE && d < bestD) {
            bestD = d;
            best = Number.isNaN(Number(uid)) ? uid : Number(uid);
          }
        }
      }
      return best;
    };

    const onPointerDown = (e: PointerEvent) => {
      if (e.target !== canvas) return;
      const { col, row } = resolveHex(e);

      // Allocation manuelle des pertes : priorité absolue tant qu'elle est active.
      // Le défenseur clique une figurine choisissable (cible) → elle encaisse.
      const alloc = manualAllocationRef.current;
      if (alloc) {
        if (e.button !== 0) return; // clic droit ignoré pendant l'allocation
        // Match par tolérance (comme le hit-test cible) : les bases larges débordent de
        // l'hex d'ancre, un match exact col/row raterait le clic sur l'icône.
        const clickCube = offsetToCube(col, row);
        let chosen: string | null = null;
        let bestD = Infinity;
        for (const c of alloc.choices) {
          const d = cubeDistance(clickCube, offsetToCube(c.col, c.row));
          if (d <= HEX_HIT_TOLERANCE && d < bestD) {
            bestD = d;
            chosen = c.model_id;
          }
        }
        if (chosen) {
          e.stopImmediatePropagation();
          void onAllocateModelRef.current?.(chosen);
        }
        return; // bloque tout autre traitement de clic pendant l'allocation
      }

      const plan = squadShootPlanRef.current;
      const cbs = squadShootCallbacksRef.current;

      // Clic droit : unassign d'une fig assignée (mode actif uniquement).
      if (e.button === 2) {
        if (mode !== "squadModelShoot" || !plan) return;
        const own = findOwnFig(col, row);
        if (own && Number(own.uid) === Number(plan.unitId) && plan.targets[own.mid]) {
          e.stopImmediatePropagation();
          void cbs.onUnassignShootModel?.(own.mid);
        }
        return;
      }
      if (e.button !== 0) return;

      if (mode !== "squadModelShoot") {
        // Flux UNIQUE assign+validate pour TOUTE unité éligible (y compris mono-fig mono-arme).
        // Pas de flux de tir legacy direct, pas de fallback : un seul chemin, cohérent.
        const own = findOwnFig(col, row);
        if (own && eligibleUnitIds.includes(Number(own.uid))) {
          e.stopImmediatePropagation();
          const now = e.timeStamp;
          const prevOwn = lastOwnFigClickRef.current;
          if (prevOwn && String(prevOwn.modelId) === String(own.mid) && now - prevOwn.time < 400) {
            // Double-clic direct (escouade pas encore activée) : le 1er clic l'active,
            // l'overview ne dépend pas de la fin de l'activation (armes/SHOOT_LEFT déjà prêts).
            lastOwnFigClickRef.current = null;
            void cbs.onSquadShootLosOverview?.(Number(own.uid));
            return;
          }
          lastOwnFigClickRef.current = { modelId: own.mid, time: now };
          void cbs.onStartSquadModelShoot?.(own.uid, own.mid);
        }
        return;
      }

      if (!plan) return;
      // 1) clic sur une fig de l'escouade active → simple = sélectionner la fig,
      //    double = vue LoS de TOUTE l'escouade (cibles tirables de l'escouade + N/M).
      const own = findOwnFig(col, row);
      if (own && Number(own.uid) === Number(plan.unitId)) {
        e.stopImmediatePropagation();
        const now = e.timeStamp;
        const prevOwn = lastOwnFigClickRef.current;
        // Menu tir ouvert : clic sur une fig = bascule de sélection.
        //  - re-clic sur la fig déjà sélectionnée → désélectionne + cibles de l'ESCOUADE (los_overview) ;
        //  - clic sur une autre fig → la sélectionne (fond jaune + menu = ses armes) + cibles de LA FIG.
        const menuNow = weaponSelectionMenuRef.current;
        if (menuNow) {
          lastOwnFigClickRef.current = { modelId: own.mid, time: now };
          if (menuNow.selectedFig === own.mid) {
            selectShootFigRef.current(undefined);
            void cbs.onSquadShootLosOverview?.(Number(plan.unitId)); // cibles escouade
          } else {
            selectShootFigRef.current(own.mid);
            void cbs.onSelectModelForShoot?.(own.mid); // cibles de la fig (surlignage jaune)
          }
          return;
        }
        if (prevOwn && String(prevOwn.modelId) === String(own.mid) && now - prevOwn.time < 400) {
          lastOwnFigClickRef.current = null;
          void cbs.onSquadShootLosOverview?.(Number(plan.unitId));
          return;
        }
        lastOwnFigClickRef.current = { modelId: own.mid, time: now };
        if (own.mid !== plan.activeModelId) {
          void cbs.onSelectModelForShoot?.(own.mid);
        } else if (blinkingLosOverviewUnitIdRef.current != null) {
          // Re-clic simple sur la fig déjà active pendant la vue escouade → revenir au blink mono-fig.
          void cbs.onSelectModelForShoot?.(own.mid);
        }
        return;
      }
      // 2) clic sur une unité ennemie → flux CIBLE-D'ABORD : ouvre le menu des armes
      // pouvant viser cette cible (compteurs x/m). L'attribution se fait dans le menu.
      const enemy = findEnemyUnit(col, row);
      if (enemy != null) {
        e.stopImmediatePropagation();
        void openWeaponsForTargetRef.current(String(enemy), { x: e.clientX + 12, y: e.clientY });
        return;
      }
      // 3) clic sur le board vide (ni fig, ni ennemi) alors qu'une fig est sélectionnée →
      // désélection : menu complet + retour aux cibles de l'escouade. (Les clics sur le menu
      // ne passent pas ici : e.target !== canvas.)
      if (weaponSelectionMenuRef.current?.selectedFig) {
        selectShootFigRef.current(undefined);
        void cbs.onSquadShootLosOverview?.(Number(plan.unitId));
      }
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [
    phase,
    mode,
    measureMode.kind,
    boardConfig,
    gameState?.units_cache,
    current_player,
    eligibleUnitIds,
  ]);

  // ── COMBAT par-figurine (PvP) : handler capture jumeau du tir ──────────────
  // Quand un plan fight est actif (unité activée) : clic sur une fig de l'unité active =
  // sélection (onSelectModelForFight) ; clic simple sur ennemi = attribution de la fig
  // active (onAssignFightTarget) ; double-clic ennemi = toute l'unité par arme
  // (onAssignFightWeapon). Capture-phase + stopImmediatePropagation pour bloquer la
  // résolution immédiate legacy.
  useEffect(() => {
    if (phase !== "fight") return;
    // Réservé à l'étape FIGHT (attribution par-arme). En move par-figurine (pile-in / consolidation),
    // ``activate_unit`` pose aussi ``squadFightPlan`` ; sans cette garde ce handler capture
    // intercepterait (stopImmediatePropagation) les clics de pose/sélection par-figurine.
    if (mode === "pileInModelMove" || mode === "consolidationModelMove") return;
    if (measureMode.kind !== "off") return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;

    const HEX_HIT_TOLERANCE = 4;
    const getUnitsCache = () =>
      gameState?.units_cache as
        | Record<
            string,
            {
              occupied_hexes_by_model?: Record<string, [number, number]>;
              col?: number;
              row?: number;
              player?: number;
            }
          >
        | undefined;

    const resolveHex = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      return pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
    };

    const findOwnFig = (col: number, row: number, activePlayer: 1 | 2) => {
      const uc = getUnitsCache();
      if (!uc) return null;
      const clickCube = offsetToCube(col, row);
      let best: { uid: number | string; mid: string } | null = null;
      let bestD = Infinity;
      for (const [uid, entry] of Object.entries(uc)) {
        if (entry.player !== activePlayer) continue;
        const byModel = entry.occupied_hexes_by_model;
        if (!byModel) continue;
        for (const [mid, pos] of Object.entries(byModel)) {
          const d = cubeDistance(clickCube, offsetToCube(pos[0], pos[1]));
          if (d <= HEX_HIT_TOLERANCE && d < bestD) {
            bestD = d;
            best = { uid: Number.isNaN(Number(uid)) ? uid : Number(uid), mid };
          }
        }
      }
      return best;
    };

    const findEnemyUnit = (
      col: number,
      row: number,
      activePlayer: 1 | 2
    ): number | string | null => {
      const uc = getUnitsCache();
      if (!uc) return null;
      const clickCube = offsetToCube(col, row);
      let best: number | string | null = null;
      let bestD = Infinity;
      for (const [uid, entry] of Object.entries(uc)) {
        if (entry.player === activePlayer) continue;
        const byModel = entry.occupied_hexes_by_model;
        const positions: Array<[number, number]> = byModel
          ? Object.values(byModel)
          : entry.col != null && entry.row != null
            ? [[entry.col, entry.row]]
            : [];
        for (const pos of positions) {
          const d = cubeDistance(clickCube, offsetToCube(pos[0], pos[1]));
          if (d <= HEX_HIT_TOLERANCE && d < bestD) {
            bestD = d;
            best = Number.isNaN(Number(uid)) ? uid : Number(uid);
          }
        }
      }
      return best;
    };

    const onPointerDown = (e: PointerEvent) => {
      if (e.target !== canvas) return;
      if (manualAllocationRef.current) return; // allocation des pertes : handler dédié (enregistré après)
      if (e.button !== 0) return;
      const plan = squadFightPlanRef.current;
      if (!plan) return; // pas de plan → activation/sélection via le flux normal (onSelectUnit)
      const { col, row } = resolveHex(e);
      const cbs = squadFightCallbacksRef.current;

      // Référence ami/ennemi = player de l'unité ACTIVE (plan.unitId), PAS current_player :
      // en alternance fight (12.04), l'unité active peut appartenir au joueur non actif.
      const activeUnitForOwnership = units.find((u) => String(u.id) === String(plan.unitId));
      if (activeUnitForOwnership == null) return;
      const activePlayer = activeUnitForOwnership.player as 1 | 2;

      // 1) Clic sur une fig de l'unité ACTIVE → sélection de la figurine.
      const own = findOwnFig(col, row, activePlayer);
      if (own && Number(own.uid) === Number(plan.unitId)) {
        e.stopImmediatePropagation();
        // Fig non engagée (ne peut frapper aucun ennemi) : grisée, non sélectionnable.
        if (!fightEngagedModelIdsRef.current.has(String(own.mid))) return;
        void cbs.onSelectModelForFight?.(own.mid);
        return;
      }
      // Clic sur une AUTRE unité amie → laisser passer (switch d'activation via onSelectUnit).
      if (own) return;

      // 2) Clic sur un ennemi → flux CIBLE-D'ABORD (jumeau EXACT du tir) : ouvre le menu des
      // profils de mêlée pouvant frapper cette cible (compteurs x/m). L'attribution se fait
      // dans le menu via les boutons −/x/+/Max (squad_fight_assign_weapon_qty). Le filtre
      // d'engagement (règle 04.02) est appliqué côté backend (weapons_for_target vide si non
      // engagé) — mêmes garanties que le tir. Les callbacks legacy onAssignFightTarget/
      // onAssignFightWeapon restent définis (fallback index-based) mais ne sont plus appelés ici.
      const enemy = findEnemyUnit(col, row, activePlayer);
      if (enemy != null) {
        e.stopImmediatePropagation();
        void openWeaponsForTargetRef.current(String(enemy), { x: e.clientX + 12, y: e.clientY });
        return;
      }
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [phase, mode, measureMode.kind, boardConfig, gameState?.units_cache, gameState, units]);

  // Allocation manuelle des pertes en COMBAT (PvP) : l'effet de tir ci-dessus est gaté
  // sur phase==="shoot" et ne couvre donc pas le fight. Ce handler dédié (phase fight,
  // allocation active) capte le clic du défenseur sur une figurine choisissable de la
  // cible et l'alloue, exactement comme au tir.
  useEffect(() => {
    if (phase !== "fight") return;
    if (!manualAllocation) return;
    if (!boardConfig) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;
    const HEX_HIT_TOLERANCE = 4;
    const resolveHex = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      return pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
    };
    const onAllocPointerDown = (e: PointerEvent) => {
      if (e.target !== canvas) return;
      const alloc = manualAllocationRef.current;
      if (!alloc) return;
      if (e.button !== 0) return;
      const { col, row } = resolveHex(e);
      const clickCube = offsetToCube(col, row);
      let chosen: string | null = null;
      let bestD = Infinity;
      for (const c of alloc.choices) {
        const d = cubeDistance(clickCube, offsetToCube(c.col, c.row));
        if (d <= HEX_HIT_TOLERANCE && d < bestD) {
          bestD = d;
          chosen = c.model_id;
        }
      }
      if (chosen) {
        e.stopImmediatePropagation();
        void onAllocateModelRef.current?.(chosen);
      }
    };
    document.addEventListener("pointerdown", onAllocPointerDown, true);
    return () => document.removeEventListener("pointerdown", onAllocPointerDown, true);
  }, [phase, manualAllocation, boardConfig]);

  // Allocation manuelle des pertes : anneau de surbrillance sur les figurines
  // choisissables (cible). Overlay PIXI dédié sur app.stage (même repère monde que
  // les unités), redessiné à chaque changement d'allocation (donc à chaque mort).
  useEffect(() => {
    const app = appRef.current;
    if (!app) return;
    const overlay = new PIXI.Graphics();
    overlay.zIndex = 2700; // au-dessus des unités (2000) et du veil move (2600)
    overlay.eventMode = "none";
    app.stage.addChild(overlay);
    manualAllocOverlayRef.current = overlay;
    overlay.visible = !hideIndicators;
    overlay.clear();
    if (manualAllocation && manualAllocation.choices.length > 0 && boardConfig) {
      const HEX_RADIUS_H = boardConfig.hex_radius;
      const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
      const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
      const MARGIN_H = boardConfig.margin;
      // Rayon de l'anneau calé sur la base de la fig cible (comme le voile rouge ~3589), + 25 %
      // pour former un halo autour de l'icône (sinon noyé dessous : base >> 0.85*hex_radius).
      const targetUnit = units.find(
        (u) => String(u.id) === String(manualAllocation.target_unit_id)
      );
      const baseSz = targetUnit ? resolveBaseSizeForUnitDisplay(targetUnit) : 1;
      const modelR = baseSz > 1 ? (baseSz * 1.5 * HEX_RADIUS_H) / 2 : HEX_RADIUS_H * 0.7;
      const ringR = modelR * 1.25;
      const lineW = Math.max(1.5, HEX_RADIUS_H * 0.5);
      // Anneau jaune sur TOUTE l'escouade cible (marque la cible en cours d'allocation) ;
      // voile gris EN PLUS sur les figs non choisissables (hors groupe courant). L'anneau
      // les distingue d'une fig morte (ghost gris sans anneau).
      const choiceIds = new Set(manualAllocation.choices.map((c) => c.model_id));
      const tgtCache = (
        gameState as unknown as {
          units_cache?: Record<
            string,
            { occupied_hexes_by_model?: Record<string, [number, number]> }
          >;
        }
      )?.units_cache?.[String(manualAllocation.target_unit_id)];
      const byModel = tgtCache?.occupied_hexes_by_model;
      if (byModel) {
        for (const [mid, pos] of Object.entries(byModel)) {
          const cx = pos[0] * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H;
          const cy =
            pos[1] * HEX_HEIGHT_H + ((pos[0] % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H;
          const selectable = choiceIds.has(mid);
          // 1. voile gris sous l'anneau pour les non-selectionnables.
          if (!selectable) {
            overlay.lineStyle(0);
            overlay.beginFill(0x444444, 0.5);
            overlay.drawCircle(cx, cy, modelR);
            overlay.endFill();
          }
          // 2. anneau jaune sur toutes les figs (fill leger uniquement si selectionnable).
          overlay.lineStyle(lineW, 0xffcc00, 0.95);
          overlay.beginFill(0xffcc00, selectable ? 0.18 : 0.0);
          overlay.drawCircle(cx, cy, ringR);
          overlay.endFill();
        }
      }
    }
    return () => {
      if (!overlay.destroyed) {
        overlay.clear();
        app.stage.removeChild(overlay);
        overlay.destroy();
      }
      if (manualAllocOverlayRef.current === overlay) manualAllocOverlayRef.current = null;
    };
  }, [manualAllocation, boardConfig, units, gameState, hideIndicators]);

  // Flux tir CIBLE-D'ABORD : sous-groupe actif (profil × cible) → voile JAUNE sur la cible
  // active + voile VERT sur les figs de l'unité active éligibles (portée+LoS). Overlay PIXI dédié.
  useEffect(() => {
    const app = appRef.current;
    if (!app) return;
    // Overlay PERSISTANT : créé une seule fois puis vidé/redessiné. Le détruire/recréer à
    // chaque render (deps gameState/units) faisait clignoter le réticule et stressait le GPU.
    let overlay = shootSubgroupOverlayRef.current;
    if (!overlay || overlay.destroyed) {
      overlay = new PIXI.Graphics();
      overlay.zIndex = 2705; // au-dessus du voile move (2600) et de l'anneau alloc (2700)
      overlay.eventMode = "none";
      app.stage.addChild(overlay);
      shootSubgroupOverlayRef.current = overlay;
    }
    overlay.visible = !hideIndicators;
    overlay.clear();
    const menu = weaponSelectionMenu;
    if (
      menu &&
      boardConfig &&
      (menu.activeTargetId || menu.selectedFig || menu.selectedWeaponCode)
    ) {
      const HEX_RADIUS_H = boardConfig.hex_radius;
      const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
      const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
      const MARGIN_H = boardConfig.margin;
      const uc = (
        gameState as unknown as {
          units_cache?: Record<
            string,
            { occupied_hexes_by_model?: Record<string, [number, number]> }
          >;
        }
      )?.units_cache;
      const centerOf = (pos: [number, number]): [number, number] => [
        pos[0] * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H,
        pos[1] * HEX_HEIGHT_H + ((pos[0] % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H,
      ];
      // 1. Voile JAUNE léger + RÉTICULE de visée (crosshair) — seulement si une cible est active.
      const tgt = menu.activeTargetId
        ? units.find((u) => String(u.id) === String(menu.activeTargetId))
        : undefined;
      const tgtByModel = menu.activeTargetId
        ? uc?.[String(menu.activeTargetId)]?.occupied_hexes_by_model
        : undefined;
      if (tgt && tgtByModel) {
        const tR =
          resolveBaseSizeForUnitDisplay(tgt) > 1
            ? (resolveBaseSizeForUnitDisplay(tgt) * 1.5 * HEX_RADIUS_H) / 2
            : HEX_RADIUS_H * 0.7;
        const rr = tR * 1.15; // rayon du réticule
        const tickIn = rr * 0.75; // les traits cardinaux chevauchent le cercle
        const tickOut = rr * 1.35;
        const reticleW = Math.max(3, HEX_RADIUS_H * 0.38);
        for (const pos of Object.values(tgtByModel)) {
          const [cx, cy] = centerOf(pos);
          // voile jaune léger (confirmation de sélection)
          overlay.lineStyle(0);
          overlay.beginFill(0xf5c518, 0.22);
          overlay.drawCircle(cx, cy, tR);
          overlay.endFill();
          // réticule rouge par-dessus l'icône (cercle + 4 traits cardinaux)
          overlay.lineStyle(reticleW, 0xff2b2b, 1);
          overlay.drawCircle(cx, cy, rr);
          overlay.moveTo(cx, cy - tickIn);
          overlay.lineTo(cx, cy - tickOut);
          overlay.moveTo(cx, cy + tickIn);
          overlay.lineTo(cx, cy + tickOut);
          overlay.moveTo(cx - tickIn, cy);
          overlay.lineTo(cx - tickOut, cy);
          overlay.moveTo(cx + tickIn, cy);
          overlay.lineTo(cx + tickOut, cy);
        }
      }
      // 2. FONDS des figs de l'unité active :
      //  - fig sélectionnée → JAUNE plein ;
      //  - sinon (cible active, aucune fig sélectionnée) → VERT (peut viser la cible) /
      //    GRIS (épuisée) / rien (peut tirer ailleurs) ;
      //  - contour jaune sur les figs portant l'arme sélectionnée (exploration inverse).
      const atk = units.find((u) => String(u.id) === String(menu.unitId));
      const atkByModel = uc?.[String(menu.unitId)]?.occupied_hexes_by_model;
      if (atk && atkByModel) {
        const aR =
          resolveBaseSizeForUnitDisplay(atk) > 1
            ? (resolveBaseSizeForUnitDisplay(atk) * 1.5 * HEX_RADIUS_H) / 2
            : HEX_RADIUS_H * 0.7;
        const statusByMid = new Map((menu.modelsStatus ?? []).map((s) => [String(s.model_id), s]));
        const figWeapons = menu.figWeapons ?? {};
        for (const [mid, pos] of Object.entries(atkByModel)) {
          const [cx, cy] = centerOf(pos);
          if (menu.selectedFig === mid) {
            overlay.lineStyle(0);
            overlay.beginFill(0xf5c518, 0.55); // fond jaune plein : fig sélectionnée
            overlay.drawCircle(cx, cy, aR);
            overlay.endFill();
          } else if (menu.activeTargetId && statusByMid.has(mid)) {
            const s = statusByMid.get(mid)!;
            if (s.exhausted) {
              overlay.lineStyle(0);
              overlay.beginFill(0x777777, 0.42); // gris : épuisée
              overlay.drawCircle(cx, cy, aR);
              overlay.endFill();
            } else if (s.can_shoot) {
              overlay.lineStyle(0);
              overlay.beginFill(0x2ecc40, 0.32); // vert : peut viser la cible
              overlay.drawCircle(cx, cy, aR);
              overlay.endFill();
            } else {
              overlay.lineStyle(0);
              overlay.beginFill(0xff4136, 0.32); // rouge : a des attaques mais ne peut pas viser cette cible
              overlay.drawCircle(cx, cy, aR);
              overlay.endFill();
            }
          } else if (
            !menu.selectedFig &&
            menu.selectedWeaponCode &&
            (figWeapons[mid] ?? []).includes(menu.selectedWeaponCode)
          ) {
            overlay.lineStyle(Math.max(2.5, HEX_RADIUS_H * 0.34), 0xf5c518, 1);
            overlay.drawCircle(cx, cy, aR * 1.08);
          }
        }
      }
    }
    // Rendu on-demand : dessiner dans le Graphics ne suffit pas, il faut forcer un repaint
    // (sinon l'overlay n'apparaît qu'au rendu suivant → réticule "en retard d'un cran").
    try {
      app.render();
    } catch {
      /* contexte non prêt : ignoré, le prochain rendu rattrapera */
    }
    // Pas de destruction ici : l'overlay est réutilisé d'un render à l'autre (voir cleanup au démontage).
  }, [weaponSelectionMenu, boardConfig, units, gameState, hideIndicators]);

  // Détruit l'overlay tir uniquement au démontage du composant.
  useEffect(
    () => () => {
      const o = shootSubgroupOverlayRef.current;
      if (o && !o.destroyed) {
        o.clear();
        o.destroy();
      }
      shootSubgroupOverlayRef.current = null;
    },
    []
  );

  // Slice G : voile violet sur les figurines ÉLIGIBLES du chargeur en chargeModelMove (phase
  // courante). La fig active a un anneau plus marqué ; sa zone de landing est dessinée ailleurs.
  // L'utilisateur choisit une fig voilée → sa zone apparaît, puis il la pose.
  useEffect(() => {
    const app = appRef.current;
    if (!app) return;
    const overlay = new PIXI.Graphics();
    overlay.zIndex = 2700;
    overlay.eventMode = "none";
    app.stage.addChild(overlay);
    chargeModelVeilOverlayRef.current = overlay;
    overlay.visible = !hideIndicators;
    overlay.clear();
    if (perModelChargeLike && activeChargeLikePlan && boardConfig) {
      const HEX_RADIUS_H = boardConfig.hex_radius;
      const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
      const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
      const MARGIN_H = boardConfig.margin;
      const hexCenter = (c: number, r: number): [number, number] => [
        c * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H,
        r * HEX_HEIGHT_H + ((c % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H,
      ];
      // Figs ÉLIGIBLES non posées → cercle violet sur le socle : montre les figs qui PEUVENT (et
      // doivent) agir dans la phase courante (1 = ≤1", 2 = ≤2", 3 = se rapprocher). ``eligibleModels``
      // est recalculé en temps réel par le backend (charge_plan_state) → le voile suit l'évolution des
      // phases. Active = remplissage marqué (en plus du ghost) ; posée = exclue.
      const charger = units.find((u) => String(u.id) === String(activeChargeLikePlan.unitId));
      const baseSz = charger ? resolveBaseSizeForUnitDisplay(charger) : 1;
      const modelR = baseSz > 1 ? (baseSz * 1.5 * HEX_RADIUS_H) / 2 : HEX_RADIUS_H * 0.7;
      const ringR = modelR * 1.25;
      const lineW = Math.max(1.5, HEX_RADIUS_H * 0.5);
      // Charge et consolidation : figs activables de l'unité active → voile vert (App.css).
      // (Le pile-in est traité à part plus bas : voile gris, pas de voile vert/violet.)
      const ACTIVE_VEIL = cssColorToNumber("--veil-green");
      const byModel = (
        gameState as unknown as {
          units_cache?: Record<
            string,
            { occupied_hexes_by_model?: Record<string, [number, number]> }
          >;
        }
      )?.units_cache?.[String(activeChargeLikePlan.unitId)]?.occupied_hexes_by_model;
      const eligibleIds = new Set(activeChargeLikePlan.eligibleModels);
      if (byModel) {
        for (const [mid, pos] of Object.entries(byModel)) {
          if (activeChargeLikePlan.models[mid]) continue; // déjà posée → traitée comme ghost déplacé
          const isEligible = eligibleIds.has(mid);
          const [cx, cy] = hexCenter(pos[0], pos[1]);
          const isActive = mid === activeChargeLikePlan.activeModelId;
          if (isPileInModelMove) {
            // Pile-in : pas de voile/cercle violet (le cercle vert d'activation suffit pour les figs
            // activables). Voile gris sur les figs de l'unité active qui ne peuvent pas encore pile-in.
            if (!isEligible) {
              overlay.lineStyle(0);
              overlay.beginFill(0x444444, 0.5);
              overlay.drawCircle(cx, cy, ringR);
              overlay.endFill();
            }
            continue;
          }
          if (!isEligible) continue;
          overlay.lineStyle(lineW, ACTIVE_VEIL, 1);
          overlay.beginFill(ACTIVE_VEIL, isActive ? 0.7 : 0.45);
          overlay.drawCircle(cx, cy, ringR);
          overlay.endFill();
        }
      }
      // Pile-in : voile ROUGE sur les figs POSÉES hors zone valide (per_model_valid false) → leur
      // empreinte/chemin a été bloqué par une fig posée après ; l'utilisateur doit les replacer.
      // En mode Focus : pas de voile rouge (seulement le cercle violet des cibles).
      if (isPileInModelMove && pileInMovePlan && !pileInFocusActive) {
        const RED_INVALID = 0xef4444;
        for (const [mid, pos] of Object.entries(pileInMovePlan.models)) {
          if (pileInMovePlan.perModelValid[mid] !== false) continue;
          const [cx, cy] = hexCenter(pos.col, pos.row);
          overlay.lineStyle(lineW, RED_INVALID, 1);
          overlay.beginFill(RED_INVALID, 0.5);
          overlay.drawCircle(cx, cy, ringR);
          overlay.endFill();
        }
      }
      // 03.04 : voile cible par UNITÉ — uniquement en charge (le pile-in n'a pas de cibles satisfaites).
      // (aucune fig chargeant à ≤ EZ), VIOLET = satisfaite (≥ 1 fig engagée). Backend fournit les
      // deux listes dans chargeMovePlan ; redraw via la dep chargeMovePlan de cet effet.
      const RED = 0xef4444;
      const GREEN = 0x22c55e;
      const ucTargets = (
        gameState as unknown as {
          units_cache?: Record<
            string,
            { occupied_hexes_by_model?: Record<string, [number, number]> }
          >;
        }
      )?.units_cache;
      const drawTargetVeil = (uid: number, color: number) => {
        const tu = units.find((u) => String(u.id) === String(uid));
        if (!tu) return;
        const tBase = resolveBaseSizeForUnitDisplay(tu);
        const tR = tBase > 1 ? (tBase * 1.5 * HEX_RADIUS_H) / 2 : HEX_RADIUS_H * 0.7;
        const tByModel = ucTargets?.[String(uid)]?.occupied_hexes_by_model;
        const positions: Array<[number, number]> = tByModel
          ? Object.values(tByModel)
          : [[tu.col, tu.row]];
        overlay.lineStyle(0);
        for (const [c, r] of positions) {
          const [cx, cy] = hexCenter(c, r);
          overlay.beginFill(color, 0.4);
          overlay.drawCircle(cx, cy, tR);
          overlay.endFill();
        }
      };
      // Mode Focus : pas de voile rouge/vert ; un CERCLE violet (contour) entoure les cibles focusables.
      const ringCtx: TargetRingCtx = {
        units,
        unitsCache: ucTargets,
        hexCenter,
        hexRadius: HEX_RADIUS_H,
        lineW,
      };
      const drawTargetRing = (uid: number | string, color: number, fillAlpha?: number) =>
        drawUnitTargetRing(overlay, uid, color, ringCtx, fillAlpha);
      if (!isPileInModelMove && chargeMovePlan) {
        const YELLOW = cssColorToNumber("--icon-blink-target-ring");
        if (chargeFocusActive) {
          for (const uid of chargePreviewTargetIds ?? []) drawTargetRing(uid, YELLOW, 0.35);
        } else {
          for (const uid of chargeMovePlan.unsatisfiedTargets) drawTargetVeil(uid, RED);
          for (const uid of chargeMovePlan.satisfiedTargets) drawTargetVeil(uid, GREEN);
          // Les cibles désignées gardent leur cercle jaune par-dessus le voile rouge/vert.
          for (const uid of chargePreviewTargetIds ?? []) drawTargetRing(uid, YELLOW);
        }
        // Voile VERT sur les figs POSÉES engagées (≤ EZ d'une cible) → en mesure de frapper.
        const cu = units.find((u) => String(u.id) === String(chargeMovePlan.unitId));
        if (cu) {
          const cBase = resolveBaseSizeForUnitDisplay(cu);
          const cR = cBase > 1 ? (cBase * 1.5 * HEX_RADIUS_H) / 2 : HEX_RADIUS_H * 0.7;
          overlay.lineStyle(0);
          for (const mid of chargeMovePlan.engagedModels) {
            const pos = chargeMovePlan.models[mid];
            if (!pos) continue;
            const [cx, cy] = hexCenter(pos.col, pos.row);
            overlay.beginFill(GREEN, 0.45);
            overlay.drawCircle(cx, cy, cR);
            overlay.endFill();
          }
        }
      }
      // Pile-in : cible potentielle → anneau jaune (contour) ; cible sélectionnée (Focus) → anneau
      // jaune + voile jaune. Voile VERT sur les figs en mesure de frapper (≤ EZ d'une cible),
      // affiché que le Focus soit actif ou non.
      if (isPileInModelMove && pileInMovePlan) {
        const YELLOW = cssColorToNumber("--icon-blink-target-ring");
        for (const uid of pileInMovePlan.pileInTargets) {
          const selected = String(uid) === String(pileInFocusTargetId);
          drawTargetRing(uid, YELLOW, selected ? 0.35 : undefined);
        }
        const pu = units.find((u) => String(u.id) === String(pileInMovePlan.unitId));
        const pByModel = ucTargets?.[String(pileInMovePlan.unitId)]?.occupied_hexes_by_model;
        if (pu) {
          const pBase = resolveBaseSizeForUnitDisplay(pu);
          const pR = pBase > 1 ? (pBase * 1.5 * HEX_RADIUS_H) / 2 : HEX_RADIUS_H * 0.7;
          overlay.lineStyle(0);
          for (const mid of pileInMovePlan.engagedModels) {
            // Position posée (plan) si présente, sinon position d'origine (figs non bougées engagées).
            const placed = pileInMovePlan.models[mid];
            const pos =
              placed ?? (pByModel?.[mid] ? { col: pByModel[mid][0], row: pByModel[mid][1] } : null);
            if (!pos) continue;
            const [cx, cy] = hexCenter(pos.col, pos.row);
            overlay.beginFill(GREEN, 0.45);
            overlay.drawCircle(cx, cy, pR);
            overlay.endFill();
          }
        }
      }
      // Consolidation engaging : cercle JAUNE (contour) autour des unités cibles potentielles (≤3").
      if (isConsolidationModelMove && consolidationMovePlan?.consolidationMode === "engaging") {
        const YELLOW = cssColorToNumber("--icon-blink-target-ring");
        for (const uid of consolidationMovePlan.engagingCandidates) drawTargetRing(uid, YELLOW);
      }
    }
    return () => {
      if (!overlay.destroyed) {
        overlay.clear();
        app.stage.removeChild(overlay);
        overlay.destroy();
      }
      if (chargeModelVeilOverlayRef.current === overlay) chargeModelVeilOverlayRef.current = null;
    };
  }, [
    perModelChargeLike,
    isPileInModelMove,
    activeChargeLikePlan,
    chargeMovePlan,
    pileInMovePlan,
    boardConfig,
    units,
    gameState,
    hideIndicators,
    chargeFocusActive,
    chargePreviewTargetIds,
    pileInFocusActive,
    pileInFocusTargetId,
    isConsolidationModelMove,
    consolidationMovePlan,
  ]);

  // Anneau jaune autour des figurines cibles potentielles (HP clignotant) en phases tir / charge /
  // fight. Mêmes cibles que le blink HP (effectiveBlinkingUnitsWithMovePreview) et même jaune que
  // pile-in / consolidation (centralisé dans App.css → --icon-blink-target-ring). Overlay PIXI dédié
  // sur app.stage, redessiné quand la liste des cibles change.
  useEffect(() => {
    const app = appRef.current;
    if (!app) return;
    const overlay = new PIXI.Graphics();
    overlay.zIndex = 2700;
    overlay.eventMode = "none";
    app.stage.addChild(overlay);
    blinkTargetRingOverlayRef.current = overlay;
    overlay.visible = !hideIndicators;
    overlay.clear();
    const ringPhase =
      phase === "shoot" || phase === "charge" || phase === "fight" || phase === "move";
    if (ringPhase && effectiveBlinkingUnitsWithMovePreview.length > 0 && boardConfig) {
      const HEX_RADIUS_H = boardConfig.hex_radius;
      const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
      const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
      const MARGIN_H = boardConfig.margin;
      const ringCtx: TargetRingCtx = {
        units,
        unitsCache: (
          gameState as unknown as {
            units_cache?: Record<
              string,
              { occupied_hexes_by_model?: Record<string, [number, number]> }
            >;
          }
        )?.units_cache,
        hexCenter: (c, r) => [
          c * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H,
          r * HEX_HEIGHT_H + ((c % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H,
        ],
        hexRadius: HEX_RADIUS_H,
        lineW: Math.max(1.5, HEX_RADIUS_H * 0.5),
      };
      const YELLOW = cssColorToNumber("--icon-blink-target-ring");
      for (const uid of effectiveBlinkingUnitsWithMovePreview) {
        drawUnitTargetRing(overlay, uid, YELLOW, ringCtx);
      }
      // Fight : les cibles déjà sélectionnées (déclarations) ont en plus un voile jaune.
      if (phase === "fight" && squadFightPlan) {
        const selectedIds = new Set(
          squadFightPlan.declarations.map((d) => String(d.target_unit_id))
        );
        for (const uid of selectedIds) drawUnitTargetRing(overlay, uid, YELLOW, ringCtx, 0.35);
      }
    }
    return () => {
      if (!overlay.destroyed) {
        overlay.clear();
        app.stage.removeChild(overlay);
        overlay.destroy();
      }
      if (blinkTargetRingOverlayRef.current === overlay) blinkTargetRingOverlayRef.current = null;
    };
  }, [
    phase,
    effectiveBlinkingUnitsWithMovePreview,
    squadFightPlan,
    boardConfig,
    units,
    gameState,
    hideIndicators,
  ]);

  // Ghost per-figurine (charge model move) : calque exact du ghost move per-fig — le fantôme de la
  // fig active suit le curseur et snappe sur le pool de landing (chargeModelPoolRef), maj
  // hoveredHexRef. Volontairement SANS preview de tir / badge caché / voile cohésion (propres au
  // move). La pose reste gérée par onPointerDownSelect (clic). Actif quand mode === "chargeModelMove"
  // && activeModelId set ; sinon le ghost est caché.
  useEffect(() => {
    if (!perModelChargeLike) return;
    if (!boardConfig) return;
    const activeModelId = activeChargeLikePlan?.activeModelId ?? null;
    if (!activeModelId) {
      if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
        hoverSpriteRef.current.visible = false;
      }
      hoveredHexRef.current = null;
      return;
    }
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;

    const charger = units.find((u) => String(u.id) === String(activeChargeLikePlan?.unitId ?? -1));
    if (!charger) return;

    const pool = activeChargeLikePoolRef?.current;
    if (!pool || pool.size === 0) return;

    const HEX_RADIUS_H = boardConfig.hex_radius;
    const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
    const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
    const MARGIN_H = boardConfig.margin;

    // Cohésion d'escouade pour les halos (mêmes valeurs config que le moteur / squadModelMove).
    const inchesToSubhex =
      (boardConfig as unknown as { inches_to_subhex?: number }).inches_to_subhex ?? 10;
    const cohesionRules = gameConfig?.game_rules as
      | { unit_model_cohesion_range?: number; unit_global_cohesion_range?: number }
      | undefined;
    if (
      typeof cohesionRules?.unit_model_cohesion_range !== "number" ||
      typeof cohesionRules?.unit_global_cohesion_range !== "number"
    ) {
      throw new Error(
        "Missing config: game_rules.unit_model_cohesion_range / unit_global_cohesion_range"
      );
    }
    const modelCohesionInches = cohesionRules.unit_model_cohesion_range;
    const globalCohesionInches = cohesionRules.unit_global_cohesion_range;
    const haloBaseSize = resolveBaseSizeForUnitDisplay(charger);

    const hxX = (col: number) => col * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H;
    const hxY = (col: number, row: number) =>
      row * HEX_HEIGHT_H + ((col % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H;

    // Snapshot pixel positions du pool de landing au moment de la sélection de la fig.
    const destPixels: { x: number; y: number; col: number; row: number }[] = [];
    for (const k of pool) {
      const sep = k.indexOf(",");
      const c = Number(k.substring(0, sep));
      const r = Number(k.substring(sep + 1));
      destPixels.push({ x: hxX(c), y: hxY(c, r), col: c, row: r });
    }
    const nearestDest = (px: number, py: number) => {
      // Cas fréquent : curseur sur un hex valide → snap direct O(1) via Set.has, sans scanner le
      // pool (qui peut faire >10k hex en déploiement → lag du mousemove sinon).
      const { col: hc, row: hr } = pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
      if (pool.has(`${hc},${hr}`)) {
        return { x: hxX(hc), y: hxY(hc, hr), col: hc, row: hr };
      }
      // Hors pool (mur / autre fig / hors zone) → plus proche hex valide par scan (cas rare).
      let best = destPixels[0]!;
      let bestD = Infinity;
      for (const dp of destPixels) {
        const d = (dp.x - px) * (dp.x - px) + (dp.y - py) * (dp.y - py);
        if (d < bestD) {
          bestD = d;
          best = dp;
        }
      }
      return best;
    };

    // Construit le ghost de la fig active (visuel complet de la fig : icône/taille/forme via
    // models_meta_by_model si escouade hétérogène), comme le ghost move.
    if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
      hoverSpriteRef.current.destroy({ children: true });
      hoverSpriteRef.current = null;
    }
    const container = new PIXI.Container();
    container.zIndex = 2500;
    container.eventMode = "none";
    container.interactiveChildren = false;
    app.stage.addChild(container);

    const activeMeta = (
      gameState?.units_cache as
        | Record<string, { models_meta_by_model?: Record<string, ModelVisualMeta> }>
        | undefined
    )?.[String(charger.id)]?.models_meta_by_model?.[activeModelId];
    const effectiveUnit = activeMeta ? { ...charger, ...activeMeta } : charger;

    const HEX_R = HEX_RADIUS_H;
    const nrHover = getNonRoundBasePixelLayout(effectiveUnit, HEX_R);
    const bdSel = resolveBaseSizeForUnitDisplay(effectiveUnit);
    const baseSizeVal = bdSel > 1 ? bdSel : undefined;
    const defaultIconDiam = baseSizeVal
      ? baseSizeVal * 1.5 * HEX_RADIUS_H
      : HEX_RADIUS_H * (effectiveUnit.ICON_SCALE ?? 1.0);

    const baseColor = charger.player === 1 ? 0x1d4ed8 : 0x882222;
    const baseCircle = new PIXI.Graphics();
    baseCircle.name = "hover-base-shape";
    baseCircle.beginFill(baseColor, 0.7);
    if (nrHover) {
      if (nrHover.kind === "oval") {
        baseCircle.drawEllipse(0, 0, nrHover.outerRx, nrHover.outerRy);
      } else {
        const h = nrHover.squareHalf;
        const s = nrHover.squareSide;
        baseCircle.drawRoundedRect(-h, -h, s, s, getSquareCornerRadiusPx());
      }
    } else {
      baseCircle.drawCircle(0, 0, defaultIconDiam / 2);
    }
    baseCircle.endFill();
    container.addChild(baseCircle);

    if (effectiveUnit.ICON) {
      const iconPath =
        charger.player === 2
          ? effectiveUnit.ICON.replace(".webp", "_red.webp")
          : effectiveUnit.ICON;
      const texture = PIXI.Texture.from(iconPath);
      const iconSprite = new PIXI.Sprite(texture);
      iconSprite.anchor.set(0.5);
      const nonRoundIconR = getNonRoundIconRadius(effectiveUnit, HEX_R);
      const iconDiam = nonRoundIconR != null ? nonRoundIconR * 2 : defaultIconDiam;
      iconSprite.width = iconDiam;
      iconSprite.height = iconDiam;
      if (nonRoundIconR != null) {
        const maskG = new PIXI.Graphics();
        maskG.beginFill(0xffffff);
        maskG.drawCircle(0, 0, nonRoundIconR);
        maskG.endFill();
        iconSprite.mask = maskG;
        container.addChild(maskG);
      }
      container.addChild(iconSprite);
    }
    container.alpha = 0.65;
    container.visible = false;
    hoverSpriteRef.current = container;

    // Overlay dédié des halos de cohésion (suivent la fig active au survol).
    const haloOverlay = new PIXI.Graphics();
    haloOverlay.zIndex = 2650;
    haloOverlay.eventMode = "none";
    haloOverlay.visible = !hideIndicators;
    app.stage.addChild(haloOverlay);
    cohesionHaloOverlayRef.current = haloOverlay;

    const onMouseMove = (ev: MouseEvent) => {
      // Guard activeModelId (state via ref synchrone) + pool (ref synchrone) : couvre la race
      // pose-faite / render-pas-encore-arrivé, comme le ghost move.
      if (
        !effectivePerModelPlanRef.current?.activeModelId ||
        !activeChargeLikePoolRef?.current?.size
      ) {
        if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
          hoverSpriteRef.current.visible = false;
        }
        if (!haloOverlay.destroyed) haloOverlay.clear();
        hoveredHexRef.current = null;
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (ev.clientX - rect.left) * scaleX;
      const py = (ev.clientY - rect.top) * scaleY;
      const best = nearestDest(px, py);
      const sprite = hoverSpriteRef.current;
      if (sprite && !sprite.destroyed) {
        sprite.position.set(best.x, best.y);
        sprite.visible = true;
      }
      hoveredHexRef.current = { col: best.col, row: best.row };

      // Halos de cohésion : fig active à la position survolée, autres figs à leur position (posée ou origine).
      const plan = effectivePerModelPlanRef.current;
      if (plan && !haloOverlay.destroyed) {
        haloOverlay.clear();
        const positions = Object.entries(plan.models).map(([mid, pos]) => ({
          mid,
          col: mid === plan.activeModelId ? best.col : pos.col,
          row: mid === plan.activeModelId ? best.row : pos.row,
        }));
        drawCohesionHalos(haloOverlay, {
          positions,
          activeModelId: plan.activeModelId,
          baseSize: haloBaseSize,
          hexRadius: HEX_RADIUS_H,
          margin: MARGIN_H,
          inchesToSubhex,
          modelCohesionInches,
          globalCohesionInches,
        });
      }
    };

    canvas.addEventListener("mousemove", onMouseMove);

    return () => {
      canvas.removeEventListener("mousemove", onMouseMove);
      if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
        hoverSpriteRef.current.visible = false;
      }
      if (!haloOverlay.destroyed) {
        haloOverlay.clear();
        app.stage.removeChild(haloOverlay);
        haloOverlay.destroy();
      }
      if (cohesionHaloOverlayRef.current === haloOverlay) cohesionHaloOverlayRef.current = null;
      hoveredHexRef.current = null;
    };
  }, [
    perModelChargeLike,
    // Objet complet (pas seulement activeModelId) : ``onSelect*Model`` pose activeModelId de façon
    // optimiste AVANT que le backend remplisse le pool. La réponse recrée le plan (charge ou pile-in)
    // → nouvelle identité → l'effet re-tourne et construit le ghost avec le pool désormais rempli.
    activeChargeLikePlan,
    boardConfig,
    gameConfig,
    hideIndicators,
    units,
    gameState?.units_cache,
    activeChargeLikePoolRef,
  ]);

  // squad.md brique 3 : dès qu'AUCUNE fig n'est active en mode plan (fig posée → deselect, ou
  // entrée sans selection), couper TOUT le preview (fantome curseur + LoS + ligne guide + tooltip).
  // Le preview (ghost + LoS) n'existe QUE pendant qu'une fig est en cours de placement.
  useEffect(() => {
    if (mode !== "squadModelMove" && !isDeploymentMove) return;
    // Déploiement : même machinerie per-fig (alias déploiement-aware, = refs squad en mode move).
    const squadMovePlan = effectivePerModelPlan;
    if (squadMovePlan?.activeModelId) return; // une fig active → preview autorisé
    if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
      hoverSpriteRef.current.visible = false;
    }
    if (movePreviewGuideLineRef.current && !movePreviewGuideLineRef.current.destroyed) {
      movePreviewGuideLineRef.current.clear();
      movePreviewGuideLineRef.current.visible = false;
    }
    losHexRef.current = null;
    setMovePreviewDistanceTooltip(null);
    // Tranche 1 : si des figs sont posées dans le plan (non validé), on NE coupe PAS la LoS-preview.
    // L'effet dédié « LoS-preview persistante après pose » ci-dessous garde le cône + blink + cases
    // vues depuis la position de CHAQUE fig posée jusqu'au clic Validate. Sans fig posée (repos /
    // entrée sans sélection) → on coupe toute la LoS comme avant.
    const hasPlacedToPersist =
      !!squadMovePlan && !!squadMovePlan.models && Object.keys(squadMovePlan.models).length > 0;
    if (hasPlacedToPersist) return;
    if (hoverOverlayRef.current && !hoverOverlayRef.current.destroyed) {
      hoverOverlayRef.current.visible = false;
    }
    setMovePreviewLosBlinkIds([]);
    setMovePreviewLosCoverById({});

    // Baseline œil "trop loin" au repos (aucune fig active) : recalculée depuis la position ACTUELLE
    // de l'unité, pour que le badge persiste tant que l'unité est active — pas seulement au survol.
    const restUnit = units.find((u) => String(u.id) === String(squadMovePlan?.unitId ?? -1));
    const restRange =
      restUnit?.RNG_WEAPONS && restUnit.RNG_WEAPONS.length > 0 ? getMaxRangedRange(restUnit) : 0;
    if (!restUnit || restRange <= 0) {
      setMovePreviewLosTooFarById({});
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const cacheKey = [
          String(restUnit.id),
          `${restUnit.col},${restUnit.row}`,
          unitsBoardLayoutKey,
          String(gameState?.turn ?? ""),
          String(gameState?.episode_steps ?? ""),
        ].join("|");
        let losPreview = movePreviewBackendLosCacheRef.current.get(cacheKey);
        if (!losPreview) {
          const response = await fetch("/api/game/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "preview_shoot_from_position",
              unitId: String(restUnit.id),
              destCol: restUnit.col,
              destRow: restUnit.row,
              advancePosition: false,
              includeLosCells: false,
            }),
          });
          if (!response.ok) {
            throw new Error(`preview_shoot_from_position failed with HTTP ${response.status}`);
          }
          const data = await response.json();
          if (data?.success !== true) {
            throw new Error("preview_shoot_from_position returned success=false");
          }
          losPreview = parseBackendMoveLosPreviewPayload(data.result, cacheKey);
          movePreviewBackendLosCacheRef.current.set(cacheKey, losPreview);
        }
        if (cancelled) return;
        setMovePreviewLosTooFarById(losPreview.hiddenTooFarByUnitId);
      } catch (error) {
        if (cancelled) return;
        setMovePreviewLosTooFarById({});
        console.error("Move rest baseline too-far failed:", error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    mode,
    isDeploymentMove,
    effectivePerModelPlan,
    effectivePerModelPlan?.activeModelId,
    effectivePerModelPlan?.unitId,
    units,
    unitsBoardLayoutKey,
    gameState?.turn,
    gameState?.episode_steps,
  ]);

  // Tranche 1 — LoS-preview PERSISTANTE après pose (jusqu'au clic Validate). Quand aucune fig n'est
  // active mais que des figs sont posées dans le plan (non validé), on garde la LoS depuis la position
  // de CHAQUE fig posée : cône WASM (par-fig, socle) + cases réellement vues + blink, en UNION multi-fig.
  // Statique (dessiné une fois par changement de plan, pas par frame → aucun coût de rendu continu).
  // Les positions posées ont été survolées juste avant le drop → preview backend déjà en cache (hit,
  // zéro latence). L'effet « cut preview » ci-dessus délègue à celui-ci quand des figs sont posées.
  useEffect(() => {
    if (mode !== "squadModelMove" && !isDeploymentMove) return;
    if (!boardConfig || !gameConfig) return;
    const app = appRef.current;
    if (!app) return;
    const plan = effectivePerModelPlan;
    if (!plan || plan.activeModelId) return; // fig active → l'effet ghost gère le preview au survol
    const placed = plan.models ? Object.entries(plan.models) : [];
    if (placed.length === 0) return; // rien de posé → repos géré par l'effet cut ci-dessus
    const squadUnit = units.find((u) => String(u.id) === String(plan.unitId));
    if (!squadUnit) return;
    const shootRange =
      squadUnit.RNG_WEAPONS && squadUnit.RNG_WEAPONS.length > 0 ? getMaxRangedRange(squadUnit) : 0;
    if (shootRange <= 0) return;

    const HEX_RADIUS_H = boardConfig.hex_radius;
    const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
    const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
    const losUnionLayout: HexUnionMaskLayout = {
      HEX_HORIZ_SPACING: HEX_WIDTH_H,
      HEX_WIDTH: HEX_WIDTH_H,
      HEX_HEIGHT: HEX_HEIGHT_H,
      HEX_VERT_SPACING: HEX_HEIGHT_H,
      MARGIN: boardConfig.margin,
      gridHexRadius: HEX_RADIUS_H,
    };
    const LOS_PREVIEW_CLEAR_HEX = 0x4f8bff;
    const LOS_PREVIEW_COVER_HEX = 0x9ec5ff;

    if (!hoverOverlayRef.current || hoverOverlayRef.current.destroyed) {
      const root = new PIXI.Container();
      root.name = "los-hover-polar-masked";
      root.eventMode = "none";
      root.zIndex = 40;
      app.stage.addChild(root);
      hoverOverlayRef.current = root;
    }
    const overlay = hoverOverlayRef.current;

    let cancelled = false;
    const ucByModel = unitsCacheModelCenters(gameState?.units_cache);
    const metric = rangedPreviewMetric(gameConfig);

    void (async () => {
      try {
        const clearCells: Array<{ col: number; row: number }> = [];
        const coverCells: Array<{ col: number; row: number }> = [];
        const targetCells: Array<{ col: number; row: number }> = [];
        const blinkSet = new Set<number>();
        const coverById: Record<string, boolean> = {};
        for (const [, pos] of placed) {
          if (cancelled) return;
          // Cône WASM par-fig depuis la position posée (socle recalculé à fromCol/fromRow).
          const conePreview = buildLosPreviewFromSource({
            source: { unit: squadUnit, fromCol: pos.col, fromRow: pos.row },
            units,
            boardCols: boardConfig.cols,
            boardRows: boardConfig.rows,
            wallHexes: boardConfig.wall_hexes,
            wallHexesOverride,
            obscuringZones: losObscuringZones,
            terrainZones: losTerrainZones,
            maxRange: shootRange,
            distanceMetric: metric,
            unitsCacheByModel: ucByModel,
            shooterModelCenters: undefined,
          });
          clearCells.push(...conePreview.clearCells);
          coverCells.push(...conePreview.terrainCoverCells);
          // Blink + cases vues règlementaires (backend) à cette position (cache hit attendu).
          const cacheKey = [
            String(squadUnit.id),
            `${pos.col},${pos.row}`,
            unitsBoardLayoutKey,
            String(gameState?.turn ?? ""),
            String(gameState?.episode_steps ?? ""),
          ].join("|");
          let losPreview = movePreviewBackendLosCacheRef.current.get(cacheKey);
          if (!losPreview) {
            const response = await fetch("/api/game/action", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                action: "preview_shoot_from_position",
                unitId: String(squadUnit.id),
                destCol: pos.col,
                destRow: pos.row,
                advancePosition: false,
                includeLosCells: false,
              }),
            });
            if (!response.ok) {
              throw new Error(`preview_shoot_from_position failed with HTTP ${response.status}`);
            }
            const data = await response.json();
            if (data?.success !== true) {
              throw new Error("preview_shoot_from_position returned success=false");
            }
            losPreview = parseBackendMoveLosPreviewPayload(data.result, cacheKey);
            movePreviewBackendLosCacheRef.current.set(cacheKey, losPreview);
          }
          for (const id of losPreview.blinkIds) blinkSet.add(id);
          for (const [uid, inCover] of Object.entries(losPreview.coverByUnitId)) {
            coverById[uid] = inCover;
          }
          targetCells.push(...losPreview.visibleTargetCells);
        }
        if (cancelled) return;
        const allVisualLosCells = [...coverCells, ...clearCells, ...targetCells];
        mountLosPolarClippedByVisibleUnion(
          overlay,
          allVisualLosCells,
          coverCells,
          losUnionLayout,
          LOS_PREVIEW_CLEAR_HEX,
          0.4,
          LOS_PREVIEW_COVER_HEX,
          0.4,
          app.renderer
        );
        overlay.visible = true;
        setMovePreviewLosBlinkIds([...blinkSet]);
        setMovePreviewLosCoverById(coverById);
      } catch (error) {
        if (cancelled) return;
        console.error("Persist placed-model LoS preview failed:", error);
      }
    })();

    return () => {
      cancelled = true;
      if (hoverOverlayRef.current && !hoverOverlayRef.current.destroyed) {
        hoverOverlayRef.current.visible = false;
      }
      setMovePreviewLosBlinkIds([]);
      setMovePreviewLosCoverById({});
    };
  }, [
    mode,
    isDeploymentMove,
    boardConfig,
    gameConfig,
    effectivePerModelPlan,
    effectivePerModelPlan?.activeModelId,
    effectivePerModelPlan?.models,
    units,
    wallHexesOverride,
    losObscuringZones,
    losTerrainZones,
    unitsBoardLayoutKey,
    gameState?.turn,
    gameState?.episode_steps,
    gameState?.units_cache,
  ]);

  // Tranche 2 — move-preview PERSISTANTE après pose : union des pools de déplacement de TOUTES les
  // figs NON POSÉES de l'escouade, quand aucune fig n'est active (post-pose ou repos). Un seul appel
  // batch (move_squad_unplaced_destinations) au lieu de N. Se recalcule à chaque pose (plan.models
  // change → les figs posées bloquent les autres). Le voile violet se vide au fur et à mesure des
  // poses et disparaît quand tout est posé. Fig active → cet effet se retire (pool de la fig active).
  useEffect(() => {
    if (mode !== "squadModelMove") return;
    const plan = squadMovePlan;
    if (!plan) return;
    if (plan.activeModelId) return;
    let cancelled = false;
    const provisionalPlan: Record<string, [number, number]> = {};
    for (const [mid, p] of Object.entries(plan.models ?? {})) {
      provisionalPlan[mid] = [p.col, p.row];
    }
    void (async () => {
      try {
        const response = await fetch("/api/game/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "move_squad_unplaced_destinations",
            unitId: String(plan.unitId),
            provisional_plan: provisionalPlan,
          }),
        });
        if (!response.ok) {
          throw new Error(`move_squad_unplaced_destinations failed with HTTP ${response.status}`);
        }
        const data = await response.json();
        if (data?.success !== true) {
          throw new Error("move_squad_unplaced_destinations returned success=false");
        }
        const pools = data.result?.pools;
        if (!pools || typeof pools !== "object" || Array.isArray(pools)) {
          throw new Error("move_squad_unplaced_destinations: pools missing/invalid");
        }
        const union = new Set<string>();
        for (const cells of Object.values(pools as Record<string, Array<[number, number]>>)) {
          if (!Array.isArray(cells)) continue;
          for (const cell of cells) {
            if (!Array.isArray(cell) || cell.length < 2) continue;
            union.add(`${cell[0]},${cell[1]}`);
          }
        }
        if (cancelled) return;
        squadUnplacedUnionPoolRef.current = union;
        setSquadUnplacedUnionVersion((v) => v + 1);
      } catch (error) {
        if (cancelled) return;
        squadUnplacedUnionPoolRef.current = new Set();
        setSquadUnplacedUnionVersion((v) => v + 1);
        console.error("Squad unplaced union pool fetch failed:", error);
      }
    })();
    return () => {
      cancelled = true;
      squadUnplacedUnionPoolRef.current = new Set();
      setSquadUnplacedUnionVersion((v) => v + 1);
    };
  }, [
    mode,
    squadMovePlan,
    squadMovePlan?.activeModelId,
    squadMovePlan?.models,
    squadMovePlan?.unitId,
  ]);

  // Ghost per-figurine (squad move plan) : ghost suit le curseur, hoveredHexRef mis à jour pour le
  // click handler (shouldConfirmAtIcon). Complètement indépendant de active_movement_unit.
  // S'active uniquement quand mode === "squadModelMove" && activeModelId est set.
  useEffect(() => {
    if (mode !== "squadModelMove" && !isDeploymentMove) return;
    if (!boardConfig) return;
    // Déploiement PvP "active" : réutilise la même machinerie per-fig que le move (ghost curseur,
    // cohésion, voile, LoS, badge caché). Les alias ``effectivePerModel*`` valent les refs squad en
    // mode move (zéro régression) et basculent sur le plan/pool de déploiement en ``deploymentMove``.
    const squadMovePlan = effectivePerModelPlan;
    const squadMovePlanRef = effectivePerModelPlanRef;
    const squadMoveModelPoolRef = effectivePerModelPoolRef;
    const activeModelId = squadMovePlan?.activeModelId ?? null;
    if (!activeModelId) return; // l'effet "cut preview" au-dessus gère le cas !activeModelId

    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;
    const app = appRef.current;
    if (!app) return;

    const squadUnit = units.find((u) => String(u.id) === String(squadMovePlan?.unitId ?? -1));
    if (!squadUnit) return;
    // TS perd le narrowing de ``squadUnit`` (const) dans les async closures internes : id capturé ici.
    const squadUnitIdStr = String(squadUnit.id);

    const pool = squadMoveModelPoolRef?.current;
    if (!pool || pool.size === 0) {
      return;
    }

    const HEX_RADIUS_H = boardConfig.hex_radius;
    const HEX_WIDTH_H = 1.5 * HEX_RADIUS_H;
    const HEX_HEIGHT_H = Math.sqrt(3) * HEX_RADIUS_H;
    const MARGIN_H = boardConfig.margin;
    const iconScaleCfg = boardConfig.display?.icon_scale;
    if (iconScaleCfg === undefined || iconScaleCfg === null) {
      throw new Error("Missing required configuration value: boardConfig.display.icon_scale");
    }

    const hxX = (col: number) => col * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H;
    const hxY = (col: number, row: number) =>
      row * HEX_HEIGHT_H + ((col % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H;

    // Snapshot pixel positions du pool + grille spatiale (buckets) pour le « plus proche valide »
    // en O(1) amorti — sinon le scan O(n) du pool (>10k en déploiement) lague le mousemove.
    const DEST_BUCKET_PX = 96;
    const destPixels: { x: number; y: number; col: number; row: number }[] = [];
    const destBuckets = new Map<string, { x: number; y: number; col: number; row: number }[]>();
    for (const k of pool) {
      const sep = k.indexOf(",");
      const c = Number(k.substring(0, sep));
      const r = Number(k.substring(sep + 1));
      const x = hxX(c);
      const y = hxY(c, r);
      const dp = { x, y, col: c, row: r };
      destPixels.push(dp);
      const bkey = `${Math.floor(x / DEST_BUCKET_PX)},${Math.floor(y / DEST_BUCKET_PX)}`;
      let arr = destBuckets.get(bkey);
      if (!arr) {
        arr = [];
        destBuckets.set(bkey, arr);
      }
      arr.push(dp);
    }

    const nearestDest = (px: number, py: number) => {
      // Cas fréquent : curseur sur un hex valide → snap direct O(1) via Set.has, sans scanner le
      // pool (qui peut faire >10k hex en déploiement → lag du mousemove sinon).
      const { col: hc, row: hr } = pixelToHex(
        px,
        py,
        boardConfig.hex_radius,
        boardConfig.margin,
        boardConfig.cols,
        boardConfig.rows
      );
      if (pool.has(`${hc},${hr}`)) {
        return { x: hxX(hc), y: hxY(hc, hr), col: hc, row: hr };
      }
      // Hors pool (mur / autre fig / hors zone) → plus proche hex valide via la grille spatiale :
      // on n'explore que le bucket du curseur + anneaux croissants, pas tout le pool.
      const bx = Math.floor(px / DEST_BUCKET_PX);
      const by = Math.floor(py / DEST_BUCKET_PX);
      let best = destPixels[0]!;
      let bestD = Infinity;
      const tryBand = (band: number) => {
        for (let dbx = bx - band; dbx <= bx + band; dbx++) {
          for (let dby = by - band; dby <= by + band; dby++) {
            const list = destBuckets.get(`${dbx},${dby}`);
            if (!list) continue;
            for (const dp of list) {
              const d = (dp.x - px) * (dp.x - px) + (dp.y - py) * (dp.y - py);
              if (d < bestD) {
                bestD = d;
                best = dp;
              }
            }
          }
        }
      };
      tryBand(1);
      if (bestD === Infinity) tryBand(4);
      if (bestD === Infinity) tryBand(12);
      if (bestD === Infinity) {
        for (const dp of destPixels) {
          const d = (dp.x - px) * (dp.x - px) + (dp.y - py) * (dp.y - py);
          if (d < bestD) {
            bestD = d;
            best = dp;
          }
        }
      }
      return best;
    };

    // Badge "œil barré" (caché, rule 13.09) du ghost — enfant du container ghost (suit donc le
    // curseur gratuitement). Visibilité togglée en live par le fetch hidden plus bas.
    let ghostBadge: PIXI.Graphics | null = null;

    // Construit (ou reconstruit) le ghost sprite pour cette fig. On détruit toujours
    // l'existant pour éviter de réutiliser un sprite construit pour une autre unité.
    const buildSprite = () => {
      if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
        hoverSpriteRef.current.destroy({ children: true });
        hoverSpriteRef.current = null;
      }
      const container = new PIXI.Container();
      container.zIndex = 2500;
      container.eventMode = "none";
      container.interactiveChildren = false;
      app.stage.addChild(container);

      // Escouade hétérogène : appliquer le visuel COMPLET (icône, taille, forme, échelle) de la
      // figurine active (models_meta_by_model[activeModelId]) sur l'unité de base, sinon le ghost
      // prend l'apparence d'une figurine de base d'un autre type.
      const activeMeta = activeModelId
        ? (
            gameState?.units_cache as
              | Record<string, { models_meta_by_model?: Record<string, ModelVisualMeta> }>
              | undefined
          )?.[String(squadUnit.id)]?.models_meta_by_model?.[activeModelId]
        : undefined;
      const effectiveUnit = activeMeta ? { ...squadUnit, ...activeMeta } : squadUnit;

      const HEX_R = HEX_RADIUS_H;
      const nrHover = getNonRoundBasePixelLayout(effectiveUnit, HEX_R);
      const bdSel = resolveBaseSizeForUnitDisplay(effectiveUnit);
      const baseSizeVal = bdSel > 1 ? bdSel : undefined;
      const defaultIconDiam = baseSizeVal
        ? baseSizeVal * 1.5 * HEX_RADIUS_H
        : HEX_RADIUS_H * (effectiveUnit.ICON_SCALE ?? 1.0);

      const baseColor = squadUnit.player === 1 ? 0x1d4ed8 : 0x882222;
      const baseCircle = new PIXI.Graphics();
      baseCircle.name = "hover-base-shape";
      baseCircle.beginFill(baseColor, 0.7);
      if (nrHover) {
        if (nrHover.kind === "oval") {
          baseCircle.drawEllipse(0, 0, nrHover.outerRx, nrHover.outerRy);
        } else {
          const h = nrHover.squareHalf;
          const s = nrHover.squareSide;
          baseCircle.drawRoundedRect(-h, -h, s, s, getSquareCornerRadiusPx());
        }
      } else {
        baseCircle.drawCircle(0, 0, defaultIconDiam / 2);
      }
      baseCircle.endFill();
      container.addChild(baseCircle);

      if (effectiveUnit.ICON) {
        const iconPath =
          squadUnit.player === 2
            ? effectiveUnit.ICON.replace(".webp", "_red.webp")
            : effectiveUnit.ICON;
        const texture = PIXI.Texture.from(iconPath);
        const iconSprite = new PIXI.Sprite(texture);
        iconSprite.anchor.set(0.5);
        const nonRoundIconR = getNonRoundIconRadius(effectiveUnit, HEX_R);
        const iconDiam = nonRoundIconR != null ? nonRoundIconR * 2 : defaultIconDiam;
        iconSprite.width = iconDiam;
        iconSprite.height = iconDiam;
        if (nonRoundIconR != null) {
          const maskG = new PIXI.Graphics();
          maskG.beginFill(0xffffff);
          maskG.drawCircle(0, 0, nonRoundIconR);
          maskG.endFill();
          iconSprite.mask = maskG;
          container.addChild(maskG);
        }
        container.addChild(iconSprite);
      }
      // Badge "caché" en bas-gauche de la fig — même géométrie/offset que renderHiddenBadge
      // (util partagé). Fig centrée en (0,0), container placé au curseur → offset local.
      const badgeIconScale = (() => {
        const db = resolveBaseSizeForUnitDisplay(effectiveUnit);
        return db > 1 ? db * 1.5 : effectiveUnit.ICON_SCALE || iconScaleCfg;
      })();
      const badgeR = Math.max(7, HEX_RADIUS_H * 0.32);
      const badgeOffset = ((HEX_RADIUS_H * badgeIconScale) / 2) * 0.8;
      const badgeG = new PIXI.Graphics();
      drawHiddenEyeBadge(badgeG, -badgeOffset, badgeOffset, badgeR);
      badgeG.zIndex = 10001;
      badgeG.visible = false;
      container.sortableChildren = true;
      container.addChild(badgeG);
      ghostBadge = badgeG;
      container.alpha = 0.65;
      container.visible = false;
      hoverSpriteRef.current = container;
    };

    buildSprite();

    // --- Preview de tir per-fig : suit le ghost (même machinerie que le survol move normal) ---
    // Cône bleu/couvert via WASM (instantané) + clignotement ennemis via backend
    // `preview_shoot_from_position`. Tout est gated mode squadModelMove ; ne touche pas le gros effet.
    const LOS_PREVIEW_CLEAR_HEX = 0x4f8bff;
    const LOS_PREVIEW_COVER_HEX = 0x9ec5ff;
    const losUnionLayout: HexUnionMaskLayout = {
      HEX_HORIZ_SPACING: HEX_WIDTH_H,
      HEX_WIDTH: HEX_WIDTH_H,
      HEX_HEIGHT: HEX_HEIGHT_H,
      HEX_VERT_SPACING: HEX_HEIGHT_H,
      MARGIN: MARGIN_H,
      gridHexRadius: HEX_RADIUS_H,
    };
    const shootRange =
      squadUnit.RNG_WEAPONS && squadUnit.RNG_WEAPONS.length > 0 ? getMaxRangedRange(squadUnit) : 0;
    // En déploiement, la LoS de tir au survol est désactivée par défaut (calcul lourd, inutile au
    // placement) — activable via l'option deployShootLoS. Hors déploiement : comportement inchangé.
    const hasRangedPreview = shootRange > 0 && (!isDeploymentMove || deployShootLoS);

    let shootPreviewActive = true;
    let visualLosFrame: number | null = null;
    let pendingVisualLos: { col: number; row: number } | null = null;
    let shootBackendTimer: ReturnType<typeof setTimeout> | null = null;
    let shootBackendInFlight = false;
    let pendingShootBackend: { col: number; row: number } | null = null;
    let lastShootPreviewHexKey: string | null = null;
    let lastValidityHexKey: string | null = null;

    // Overlay PIXI dédié au voile rouge hover — mis à jour directement, pas via React state.
    const veilOverlay = new PIXI.Graphics();
    veilOverlay.zIndex = 2600; // au-dessus du ghost sprite (2500) et des unités (2000)
    app.stage.addChild(veilOverlay);
    squadMoveVeilOverlayRef.current = veilOverlay;
    veilOverlay.visible = !hideIndicators;

    const inchesToSubhex =
      (boardConfig as unknown as { inches_to_subhex?: number }).inches_to_subhex ?? 10;
    const cohesionRules = gameConfig?.game_rules as
      | {
          unit_model_cohesion_range?: number;
          unit_global_cohesion_range?: number;
        }
      | undefined;
    if (
      typeof cohesionRules?.unit_model_cohesion_range !== "number" ||
      typeof cohesionRules?.unit_global_cohesion_range !== "number"
    ) {
      throw new Error(
        "Missing config: game_rules.unit_model_cohesion_range / unit_global_cohesion_range"
      );
    }
    const modelCohesionInches = cohesionRules.unit_model_cohesion_range;
    const globalCohesionInches = cohesionRules.unit_global_cohesion_range;
    const baseSize = resolveBaseSizeForUnitDisplay(squadUnit);
    const veilRadius = baseSize > 1 ? (baseSize * 1.5 * HEX_RADIUS_H) / 2 : HEX_RADIUS_H * 0.7;

    function drawHoverVeil(hoverCol: number, hoverRow: number): void {
      veilOverlay.clear();
      const plan = squadMovePlanRef.current;
      if (!plan) return;
      const mids = Object.keys(plan.models);
      const n = mids.length;
      if (n < 2) return;

      // Positions avec fig active à la position hover
      const positions = mids.map((mid) =>
        mid === plan.activeModelId
          ? ([hoverCol, hoverRow] as [number, number])
          : ([plan.models[mid].col, plan.models[mid].row] as [number, number])
      );

      // Halos de cohésion (halo fig active blanc→vert + grand cercle réactif).
      drawCohesionHalos(veilOverlay, {
        positions: mids.map((mid, i) => ({ mid, col: positions[i][0], row: positions[i][1] })),
        activeModelId: plan.activeModelId,
        baseSize,
        hexRadius: HEX_RADIUS_H,
        margin: MARGIN_H,
        inchesToSubhex,
        modelCohesionInches,
        globalCohesionInches,
      });

      // Voile rouge par-fig, EUCLIDIEN (cohérent avec les cercles dessinés) : une fig est fautive si
      // elle a < minNeighbors voisin à ≤ model (1re puce, bord-à-bord) OU sort du cercle global (2e puce).
      const pxPerStep = HEX_HEIGHT_H;
      const modelRangePx = modelCohesionInches * inchesToSubhex * pxPerStep;
      const globalRadiusPx = (globalCohesionInches * inchesToSubhex * pxPerStep) / 2;
      const neighborMaxPx = modelRangePx + 2 * veilRadius; // bord-à-bord euclidien ≤ portée model
      const centers = positions.map(([col, row]) => ({
        x: col * HEX_WIDTH_H + HEX_WIDTH_H / 2 + MARGIN_H,
        y: row * HEX_HEIGHT_H + ((col % 2) * HEX_HEIGHT_H) / 2 + HEX_HEIGHT_H / 2 + MARGIN_H,
      }));
      // Centre du cercle global = milieu des 2 figs les plus éloignées (diamètre d'étalement).
      let bx = centers[0].x,
        by = centers[0].y;
      let maxD2 = -1;
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const dx = centers[i].x - centers[j].x;
          const dy = centers[i].y - centers[j].y;
          const d2 = dx * dx + dy * dy;
          if (d2 > maxD2) {
            maxD2 = d2;
            bx = (centers[i].x + centers[j].x) / 2;
            by = (centers[i].y + centers[j].y) / 2;
          }
        }
      }
      // 1re puce : CONNEXITÉ — graphe d'adjacence (paires ≤ model bord-à-bord) + composantes connexes.
      // Une fig hors du composant majoritaire (rupture de chaîne) est en violation.
      const comp = new Array<number>(n).fill(-1);
      let numComp = 0;
      for (let s = 0; s < n; s++) {
        if (comp[s] !== -1) continue;
        const stack = [s];
        comp[s] = numComp;
        while (stack.length) {
          const k = stack.pop()!;
          for (let nb = 0; nb < n; nb++) {
            if (
              comp[nb] === -1 &&
              k !== nb &&
              Math.hypot(centers[k].x - centers[nb].x, centers[k].y - centers[nb].y) <=
                neighborMaxPx
            ) {
              comp[nb] = numComp;
              stack.push(nb);
            }
          }
        }
        numComp++;
      }
      const compSize: Record<number, number> = {};
      for (const c of comp) compSize[c] = (compSize[c] ?? 0) + 1;
      for (let i = 0; i < n; i++) {
        const minority = compSize[comp[i]] * 2 <= n; // 1re puce : composant minoritaire
        const outOfGlobal =
          Math.hypot(centers[i].x - bx, centers[i].y - by) - veilRadius > globalRadiusPx; // 2e puce
        if (!minority && !outOfGlobal) continue; // fig cohérente
        veilOverlay.beginFill(0xff0000, 0.45);
        veilOverlay.drawCircle(centers[i].x, centers[i].y, veilRadius);
        veilOverlay.endFill();
      }
    }

    const ensureLosOverlay = (): PIXI.Container => {
      if (!hoverOverlayRef.current || hoverOverlayRef.current.destroyed) {
        const root = new PIXI.Container();
        root.name = "los-hover-polar-masked";
        root.eventMode = "none";
        root.zIndex = 40;
        app.stage.addChild(root);
        hoverOverlayRef.current = root;
      }
      return hoverOverlayRef.current;
    };

    const drawVisualCone = (col: number, row: number) => {
      pendingVisualLos = { col, row };
      if (visualLosFrame !== null) return;
      visualLosFrame = window.requestAnimationFrame(() => {
        visualLosFrame = null;
        const pending = pendingVisualLos;
        pendingVisualLos = null;
        if (!pending || !shootPreviewActive || !isWasmReady()) return;
        if (!boardConfig || !gameConfig) return;
        const overlay = ensureLosOverlay();
        const ucByModel = unitsCacheModelCenters(gameState?.units_cache);
        const visualPreview = buildLosPreviewFromSource({
          source: { unit: squadUnit, fromCol: pending.col, fromRow: pending.row },
          units,
          boardCols: boardConfig.cols,
          boardRows: boardConfig.rows,
          wallHexes: boardConfig.wall_hexes,
          wallHexesOverride,
          obscuringZones: losObscuringZones,
          terrainZones: losTerrainZones,
          maxRange: shootRange,
          distanceMetric: rangedPreviewMetric(gameConfig),
          unitsCacheByModel: ucByModel,
          shooterModelCenters:
            pending.col === squadUnit.col && pending.row === squadUnit.row
              ? ucByModel?.[String(squadUnit.id)]
              : undefined,
        });
        // Cases visibles des cibles ciblables (backend) peintes par-dessus le cône WASM :
        // garantit qu'une unité qui blinke a toujours ses cases visibles affichées, même si le
        // cône générique ne les atteint pas (exclusion obscuring par-figurine, règle 13.10).
        // Source = preview backend À LA CASE SURVOLÉE (cache par-case), pas la valeur périmée
        // stockée sur l'unité (squadUnit.visible_cells_by_target reflète la position réelle, pas
        // le ghost). Cache miss → repeinturage déclenché par runShootBackend à la réponse.
        const coneCacheKey = [
          squadUnitIdStr,
          `${pending.col},${pending.row}`,
          unitsBoardLayoutKey,
          String(gameState?.turn ?? ""),
          String(gameState?.episode_steps ?? ""),
        ].join("|");
        const conePreview = movePreviewBackendLosCacheRef.current.get(coneCacheKey);
        const targetCells = conePreview ? conePreview.visibleTargetCells : [];
        const allVisualLosCells = [
          ...visualPreview.terrainCoverCells,
          ...visualPreview.clearCells,
          ...targetCells,
        ];
        mountLosPolarClippedByVisibleUnion(
          overlay,
          allVisualLosCells,
          visualPreview.terrainCoverCells,
          losUnionLayout,
          LOS_PREVIEW_CLEAR_HEX,
          0.4,
          LOS_PREVIEW_COVER_HEX,
          0.4,
          app.renderer
        );
        overlay.visible = true;
      });
    };

    async function runShootBackend(): Promise<void> {
      if (shootBackendInFlight) return;
      shootBackendInFlight = true;
      try {
        const pending = pendingShootBackend;
        pendingShootBackend = null;
        if (!pending) return;
        const cacheKey = [
          squadUnitIdStr,
          `${pending.col},${pending.row}`,
          unitsBoardLayoutKey,
          String(gameState?.turn ?? ""),
          String(gameState?.episode_steps ?? ""),
        ].join("|");
        let losPreview = movePreviewBackendLosCacheRef.current.get(cacheKey);
        if (!losPreview) {
          const response = await fetch("/api/game/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "preview_shoot_from_position",
              unitId: squadUnitIdStr,
              destCol: pending.col,
              destRow: pending.row,
              advancePosition: false,
              includeLosCells: false,
            }),
          });
          if (!response.ok) {
            throw new Error(`preview_shoot_from_position failed with HTTP ${response.status}`);
          }
          const data = await response.json();
          if (data?.success !== true) {
            throw new Error("preview_shoot_from_position returned success=false");
          }
          losPreview = parseBackendMoveLosPreviewPayload(data.result, cacheKey);
          if (movePreviewBackendLosCacheRef.current.size >= MOVE_PREVIEW_LOS_CACHE_MAX_ENTRIES) {
            const oldestKey = movePreviewBackendLosCacheRef.current.keys().next().value;
            if (typeof oldestKey !== "string") {
              throw new Error("Move preview LoS cache oldest key is invalid");
            }
            movePreviewBackendLosCacheRef.current.delete(oldestKey);
          }
          movePreviewBackendLosCacheRef.current.set(cacheKey, losPreview);
        }
        if (!shootPreviewActive) return;
        // Anti-clignotement périmé : ne peindre que si cette réponse correspond encore à la case
        // courante du ghost. Une réponse en vol pour une case déjà quittée est ignorée (la case
        // courante est re-fetchée via le finally). Sans ça, le blink d'une case en portée persiste
        // sur une case hors portée où l'on valide → cible fantôme au tir.
        if (`${pending.col},${pending.row}` !== lastShootPreviewHexKey) return;
        setMovePreviewLosBlinkIds(losPreview.blinkIds);
        setMovePreviewLosCoverById(losPreview.coverByUnitId);
        setMovePreviewLosTooFarById(losPreview.hiddenTooFarByUnitId);
        // Cône déjà peint au survol (cache miss → sans cases cibles). La réponse backend est
        // maintenant en cache par-case : repeindre pour afficher les cases réellement vues des
        // cibles (règle 06.01/13.10) par-dessus le cône WASM.
        drawVisualCone(pending.col, pending.row);
      } catch (error) {
        if (!shootPreviewActive) return;
        setMovePreviewLosBlinkIds([]);
        setMovePreviewLosCoverById({});
        setMovePreviewLosTooFarById({});
        console.error("Squad per-fig shoot preview backend LoS failed:", error);
      } finally {
        shootBackendInFlight = false;
        if (shootPreviewActive && pendingShootBackend) {
          scheduleShootBackend(pendingShootBackend.col, pendingShootBackend.row);
        }
      }
    }

    const scheduleShootBackend = (col: number, row: number) => {
      pendingShootBackend = { col, row };
      if (shootBackendTimer || shootBackendInFlight) return;
      shootBackendTimer = setTimeout(() => {
        shootBackendTimer = null;
        void runShootBackend();
      }, 25);
    };

    const triggerShootPreview = (col: number, row: number) => {
      if (!hasRangedPreview) return;
      const key = `${col},${row}`;
      if (key === lastShootPreviewHexKey) return;
      lastShootPreviewHexKey = key;
      drawVisualCone(col, row);
      // Le clignotement doit refléter la case courante, jamais une case déjà quittée.
      // Cache par-case (keyé col,row) : hit → application immédiate (pas de flicker sur les cases
      // déjà visitées) ; miss → on efface le blink périmé tout de suite, puis fetch.
      const cacheKey = [
        squadUnitIdStr,
        `${col},${row}`,
        unitsBoardLayoutKey,
        String(gameState?.turn ?? ""),
        String(gameState?.episode_steps ?? ""),
      ].join("|");
      const cached = movePreviewBackendLosCacheRef.current.get(cacheKey);
      if (cached) {
        setMovePreviewLosBlinkIds(cached.blinkIds);
        setMovePreviewLosCoverById(cached.coverByUnitId);
        setMovePreviewLosTooFarById(cached.hiddenTooFarByUnitId);
      } else {
        setMovePreviewLosBlinkIds([]);
        setMovePreviewLosCoverById({});
        setMovePreviewLosTooFarById({});
      }
      scheduleShootBackend(col, row);
    };

    // --- Badge "caché" per-fig (rule 13.09) : statut backend de la fig active à l'hex survolé.
    // Source unique = backend (preview_hidden_from_model_positions), comme le group preview.
    // Debounce + coalescing + cache (movePreviewHiddenCacheRef) partagés, calqués sur le shoot.
    let hiddenInFlight = false;
    let pendingHidden: { col: number; row: number } | null = null;
    let hiddenTimer: ReturnType<typeof setTimeout> | null = null;
    let lastHiddenHexKey: string | null = null;

    const buildHiddenModelPositions = (
      col: number,
      row: number
    ): Record<string, [number, number]> | null => {
      const occ = (
        gameState?.units_cache as
          | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
          | undefined
      )?.[String(squadUnit.id)]?.occupied_hexes_by_model;
      // Déploiement : l'escouade provisoire n'est pas dans ``units_cache`` → base = positions du plan.
      const planModels = squadMovePlanRef.current?.models;
      const baseEntries: Array<[string, [number, number]]> = occ
        ? Object.entries(occ)
        : planModels
          ? Object.entries(planModels).map(
              ([m, p]) => [m, [p.col, p.row]] as [string, [number, number]]
            )
          : [];
      if (baseEntries.length === 0) return null;
      const mp: Record<string, [number, number]> = {};
      for (const [mid, pos] of baseEntries) {
        if (mid === activeModelId) {
          mp[mid] = [col, row];
        } else {
          const planPos = planModels?.[mid];
          mp[mid] = planPos ? [planPos.col, planPos.row] : pos;
        }
      }
      return mp;
    };

    async function runHiddenBackend(): Promise<void> {
      if (hiddenInFlight) return;
      hiddenInFlight = true;
      try {
        const pending = pendingHidden;
        pendingHidden = null;
        if (!pending) return;
        const mp = buildHiddenModelPositions(pending.col, pending.row);
        if (!mp) return;
        const key =
          `plan:${squadUnitIdStr}:` +
          Object.entries(mp)
            .map(([m, p]) => `${m}@${p[0]},${p[1]}`)
            .join(",");
        const cached = movePreviewHiddenCacheRef.current.get(key);
        let hiddenModels: string[];
        if (cached) {
          hiddenModels = cached;
        } else {
          const response = await fetch("/api/game/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "preview_hidden_from_model_positions",
              unitId: squadUnitIdStr,
              modelPositions: mp,
            }),
          });
          if (!response.ok) {
            throw new Error(
              `preview_hidden_from_model_positions failed with HTTP ${response.status}`
            );
          }
          const data = await response.json();
          if (data?.success !== true) {
            throw new Error("preview_hidden_from_model_positions returned success=false");
          }
          hiddenModels = Array.isArray(data.result?.hidden_models)
            ? data.result.hidden_models.map((m: unknown) => String(m))
            : [];
          movePreviewHiddenCacheRef.current.set(key, hiddenModels);
        }
        if (!shootPreviewActive) return;
        if (ghostBadge && !ghostBadge.destroyed) {
          ghostBadge.visible = !hideIndicators && hiddenModels.includes(String(activeModelId));
        }
      } catch (error) {
        if (!shootPreviewActive) return;
        console.error("Squad per-fig hidden preview backend failed:", error);
      } finally {
        hiddenInFlight = false;
        if (shootPreviewActive && pendingHidden) {
          scheduleHidden(pendingHidden.col, pendingHidden.row);
        }
      }
    }

    const scheduleHidden = (col: number, row: number) => {
      pendingHidden = { col, row };
      if (hiddenTimer || hiddenInFlight) return;
      hiddenTimer = setTimeout(() => {
        hiddenTimer = null;
        void runHiddenBackend();
      }, 25);
    };

    const triggerHiddenPreview = (col: number, row: number) => {
      const hexKey = `${col},${row}`;
      if (hexKey === lastHiddenHexKey) return;
      lastHiddenHexKey = hexKey;
      scheduleHidden(col, row);
    };

    // Apparition immédiate à la sélection : preview depuis la position courante de la fig active.
    const activeModelPos = squadMovePlan?.models?.[String(activeModelId)];
    if (hasRangedPreview && activeModelPos) {
      triggerShootPreview(activeModelPos.col, activeModelPos.row);
    }
    if (activeModelPos) {
      triggerHiddenPreview(activeModelPos.col, activeModelPos.row);
    }

    const onMouseMove = (ev: MouseEvent) => {
      // Guard sur activeModelId (state) ET sur la taille du pool (ref synchrone).
      // handleMoveModelInPlan vide le pool AVANT setSquadMovePlan → la race condition
      // (render pas encore arrivé, mais placement déjà fait) est couverte par la 2ème condition.
      if (!squadMovePlanRef.current?.activeModelId || !squadMoveModelPoolRef?.current?.size) {
        if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
          hoverSpriteRef.current.visible = false;
        }
        hoveredHexRef.current = null;
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (ev.clientX - rect.left) * scaleX;
      const py = (ev.clientY - rect.top) * scaleY;

      const best = nearestDest(px, py);

      const sprite = hoverSpriteRef.current;
      if (sprite && !sprite.destroyed) {
        sprite.position.set(best.x, best.y);
        sprite.visible = true;
      }
      hoveredHexRef.current = { col: best.col, row: best.row };
      // Recalculs qui ne dépendent QUE de l'hex destination : seulement quand l'hex snappé change
      // (pas à chaque pixel). Le ghost, lui, suit le curseur en continu ci-dessus.
      const vKey = `${best.col},${best.row}`;
      if (vKey !== lastValidityHexKey) {
        lastValidityHexKey = vKey;
        // Le preview de tir suit le ghost.
        triggerShootPreview(best.col, best.row);
        // Badge "caché" : recalcul backend (debouncé).
        triggerHiddenPreview(best.col, best.row);
        // Voile rouge hover : recalcul côté client.
        drawHoverVeil(best.col, best.row);
      }
    };

    canvas.addEventListener("mousemove", onMouseMove);

    return () => {
      canvas.removeEventListener("mousemove", onMouseMove);
      if (hoverSpriteRef.current && !hoverSpriteRef.current.destroyed) {
        hoverSpriteRef.current.visible = false;
      }
      hoveredHexRef.current = null;
      // Coupe le preview de tir per-fig : stoppe les callbacks en vol, cache le cône, vide le blink.
      shootPreviewActive = false;
      if (visualLosFrame !== null) window.cancelAnimationFrame(visualLosFrame);
      if (shootBackendTimer) clearTimeout(shootBackendTimer);
      if (hiddenTimer) clearTimeout(hiddenTimer);
      if (!veilOverlay.destroyed) veilOverlay.destroy();
      squadMoveVeilOverlayRef.current = null;
      if (hoverOverlayRef.current && !hoverOverlayRef.current.destroyed) {
        hoverOverlayRef.current.visible = false;
      }
      setMovePreviewLosBlinkIds([]);
      setMovePreviewLosCoverById({});
      setMovePreviewLosTooFarById({});
    };
  }, [
    mode,
    isDeploymentMove,
    effectivePerModelPlan,
    effectivePerModelPlan?.activeModelId,
    effectivePerModelPlan?.unitId,
    effectivePerModelPlan?.models,
    boardConfig,
    gameConfig,
    units,
    wallHexesOverride,
    losObscuringZones,
    losTerrainZones,
    unitsBoardLayoutKey,
    gameState?.turn,
    gameState?.episode_steps,
    gameState?.units_cache,
    effectivePerModelPoolRef,
    hideIndicators,
    deployShootLoS,
  ]);

  // Mode mesure : clic gauche = ancre ou fin de ligne (puis armed) ; clic droit = jonction — prioritaire sur les unités.
  useEffect(() => {
    if (!boardConfig || measureMode.kind === "off" || !onMeasureHexCommit) return;
    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;

    const onPointerDownCapture = (e: PointerEvent) => {
      const app = appRef.current;
      if (!app) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (e.clientX - rect.left) * scaleX;
      const py = (e.clientY - rect.top) * scaleY;
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const { col, row } = pixelToHex(
        px,
        py,
        HEX_RADIUS,
        MARGIN,
        boardConfig.cols,
        boardConfig.rows
      );
      if (col < 0 || col >= boardConfig.cols || row < 0 || row >= boardConfig.rows) return;

      if (e.button === 2) {
        const mode = measureModeRef.current;
        if (mode.kind === "measuring" && onMeasureJunctionCommit) {
          const last =
            mode.junctions.length > 0
              ? mode.junctions[mode.junctions.length - 1]!
              : { col: mode.originCol, row: mode.originRow };
          if (last.col === col && last.row === row) return;
          e.preventDefault();
          e.stopPropagation();
          measurePointerClientRef.current = { clientX: e.clientX, clientY: e.clientY };
          onMeasureJunctionCommit(col, row);
        }
        return;
      }

      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      onMeasureHexCommit(col, row);
    };

    const onContextMenu = (e: MouseEvent) => {
      if (measureModeRef.current.kind === "measuring") {
        e.preventDefault();
      }
    };

    canvas.addEventListener("pointerdown", onPointerDownCapture, true);
    canvas.addEventListener("contextmenu", onContextMenu);
    return () => {
      canvas.removeEventListener("pointerdown", onPointerDownCapture, true);
      canvas.removeEventListener("contextmenu", onContextMenu);
    };
  }, [boardConfig, onMeasureHexCommit, onMeasureJunctionCommit, measureMode.kind]);

  const isMeasuring = measureMode.kind === "measuring";

  /** Après chaque mise à jour des jonctions (sans remonter l’effet mesure), redessine la même Graphics sans flash. */
  useLayoutEffect(() => {
    if (measureMode.kind !== "measuring") return;
    const redraw = measureLineRedrawRef.current;
    const last = measurePointerClientRef.current;
    if (!redraw || !last) return;
    redraw(last.clientX, last.clientY);
  }, [measureMode]);

  // Mode mesure : monté une fois par session « measuring » (pas de cleanup quand seules les jonctions changent).
  useEffect(() => {
    if (!boardConfig || !isMeasuring) {
      measurePointerClientRef.current = null;
      measureLineRedrawRef.current = null;
      if (measureGuideLineRef.current && !measureGuideLineRef.current.destroyed) {
        measureGuideLineRef.current.clear();
        measureGuideLineRef.current.visible = false;
      }
      setMeasureDistanceTooltip(null);
      return;
    }

    const canvas = canvasContainerRef.current?.querySelector("canvas");
    if (!canvas) return;

    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const BOARD_COLS = boardConfig.cols;
    const BOARD_ROWS = boardConfig.rows;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;

    const hxX = (col: number) => col * HEX_WIDTH + HEX_WIDTH / 2 + MARGIN;
    const hxY = (col: number, row: number) =>
      row * HEX_HEIGHT + ((col % 2) * HEX_HEIGHT) / 2 + HEX_HEIGHT / 2 + MARGIN;

    const updateMeasureLineFromClient = (clientX: number, clientY: number) => {
      const mode = measureModeRef.current;
      if (mode.kind !== "measuring") return;
      const { originCol, originRow, junctions } = mode;
      const app = appRef.current;
      if (!app) return;
      const rect = canvas.getBoundingClientRect();
      const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
      const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
      const px = (clientX - rect.left) * scaleX;
      const py = (clientY - rect.top) * scaleY;
      const { col: endCol, row: endRow } = pixelToHex(
        px,
        py,
        HEX_RADIUS,
        MARGIN,
        BOARD_COLS,
        BOARD_ROWS
      );
      if (endCol < 0 || endCol >= BOARD_COLS || endRow < 0 || endRow >= BOARD_ROWS) {
        if (measureGuideLineRef.current && !measureGuideLineRef.current.destroyed) {
          measureGuideLineRef.current.clear();
          measureGuideLineRef.current.visible = false;
        }
        setMeasureDistanceTooltip(null);
        return;
      }

      const pathHexes = [
        { col: originCol, row: originRow },
        ...junctions,
        { col: endCol, row: endRow },
      ];
      let hexStepsTotal = 0;
      for (let i = 0; i < pathHexes.length - 1; i++) {
        const a = pathHexes[i]!;
        const b = pathHexes[i + 1]!;
        hexStepsTotal += hexDistOff(a.col, a.row, b.col, b.row);
      }
      const stepsPerInch =
        (boardConfig as unknown as { inches_to_subhex?: number }).inches_to_subhex ||
        HEX_STEPS_PER_INCH_DISPLAY;
      const distanceDisplay = (hexStepsTotal / stepsPerInch).toFixed(1);

      if (!measureGuideLineRef.current || measureGuideLineRef.current.destroyed) {
        const g = new PIXI.Graphics();
        g.zIndex = MEASURE_GUIDE_LINE_Z_INDEX;
        g.eventMode = "none";
        app.stage.addChild(g);
        measureGuideLineRef.current = g;
      }
      const guideLine = measureGuideLineRef.current;
      guideLine.zIndex = MEASURE_GUIDE_LINE_Z_INDEX;
      guideLine.clear();
      guideLine.lineStyle(2, 0xe2e8f0, 0.9);
      const first = pathHexes[0]!;
      guideLine.moveTo(hxX(first.col), hxY(first.col, first.row));
      for (let i = 1; i < pathHexes.length; i++) {
        const h = pathHexes[i]!;
        guideLine.lineTo(hxX(h.col), hxY(h.col, h.row));
      }
      guideLine.visible = true;

      const endX = hxX(endCol);
      const endY = hxY(endCol, endRow);
      setMeasureDistanceTooltip({
        visible: true,
        text: `${distanceDisplay}"`,
        x: rect.left + endX / scaleX,
        y: rect.top + endY / scaleY,
      });
    };

    measureLineRedrawRef.current = updateMeasureLineFromClient;

    const onMouseMove = (ev: MouseEvent) => {
      measurePointerClientRef.current = { clientX: ev.clientX, clientY: ev.clientY };
      updateMeasureLineFromClient(ev.clientX, ev.clientY);
    };

    canvas.addEventListener("mousemove", onMouseMove);
    const last = measurePointerClientRef.current;
    if (last) {
      updateMeasureLineFromClient(last.clientX, last.clientY);
    }
    return () => {
      canvas.removeEventListener("mousemove", onMouseMove);
      measureLineRedrawRef.current = null;
      if (measureGuideLineRef.current && !measureGuideLineRef.current.destroyed) {
        measureGuideLineRef.current.clear();
        measureGuideLineRef.current.visible = false;
      }
      setMeasureDistanceTooltip(null);
    };
  }, [boardConfig, isMeasuring]);

  // Track model positions to detect dead models (disappear from occupied_hexes_by_model).
  // Runs BEFORE the PIXI render effect. Only fires when units_cache changes (shoot actions).
  useEffect(() => {
    const unitsCache = gameState?.units_cache as
      | Record<
          string,
          {
            col?: number;
            row?: number;
            occupied_hexes_by_model?: Record<string, [number, number]>;
            models_meta_by_model?: Record<string, ModelVisualMeta>;
          }
        >
      | undefined;

    const newPosMap = new Map<string, { pos: [number, number]; meta: ModelVisualMeta | null }>();
    if (unitsCache) {
      for (const [unitId, entry] of Object.entries(unitsCache)) {
        if (entry.occupied_hexes_by_model) {
          for (const [modelId, pos] of Object.entries(entry.occupied_hexes_by_model)) {
            const meta = entry.models_meta_by_model?.[modelId] ?? null;
            newPosMap.set(`${unitId}:${modelId}`, { pos: pos as [number, number], meta });
          }
        } else if (entry.col !== undefined && entry.row !== undefined) {
          newPosMap.set(`${unitId}:_`, { pos: [entry.col, entry.row], meta: null });
        }
      }
    }

    const newGhosts: DeadModelGhost[] = [];
    for (const [key, prev] of prevModelPosRef.current) {
      if (!newPosMap.has(key)) {
        const unitId = key.split(":")[0];
        const parentUnit = units.find((u) => String(u.id) === unitId);
        if (parentUnit) {
          newGhosts.push({ unit: parentUnit, col: prev.pos[0], row: prev.pos[1], meta: prev.meta });
        }
      }
    }
    if (newGhosts.length > 0) {
      setDeadModelGhosts((prev) => [...prev, ...newGhosts]);
    }
    prevModelPosRef.current = newPosMap;
  }, [gameState?.units_cache, units]);

  // ✅ HOOK 3: useEffect - MINIMAL DEPENDENCIES TO PREVENT RE-RENDER LOOPS
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentional minimal deps to prevent re-render loops
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

    const enginePhaseForPools = gameState?.phase ?? phase;
    const keepMovementPickPool =
      ((enginePhaseForPools === "move" || enginePhaseForPools === "command") &&
        selectedUnitId !== null) ||
      (mode === "advancePreview" && selectedUnitId !== null) ||
      (phase === "shoot" && pendingMoveAfterShooting && selectedUnitId !== null) ||
      (phase === "fight" &&
        (mode === "pileInPreview" || mode === "consolidationPreview") &&
        selectedUnitId !== null);

    if (!keepMovementPickPool) {
      if (resolvedMoveDestPoolRef.current && resolvedMoveDestPoolRef.current.size > 0) {
        resolvedMoveDestPoolRef.current.clear();
      }
      if (footprintZoneRef?.current && footprintZoneRef.current.size > 0) {
        footprintZoneRef.current.clear();
      }
      if (footprintMaskLoopsRef) {
        footprintMaskLoopsRef.current = null;
      }
    }

    const keepChargePickPool =
      phase === "charge" && mode === "chargePreview" && selectedUnitId !== null;
    if (!keepChargePickPool) {
      if (chargeDestPoolRef?.current && chargeDestPoolRef.current.size > 0) {
        chargeDestPoolRef.current.clear();
      }
      if (chargeFootprintZoneRef?.current && chargeFootprintZoneRef.current.size > 0) {
        chargeFootprintZoneRef.current.clear();
      }
    }

    // Comme la charge (syncChargePoolRefs synchrone dans le handler API) : remplir les refs
    // **dans cet effet**, avant drawBoard. Un useEffect parent sur gameState s’exécute après
    // l’enfant → drawBoard lisait moveDestPoolRef vide et retombait sur les pastilles hex.
    // En squadModelMove : resolvedMoveDestPoolRef est vidé pour ne pas parasite le rendu ;
    // drawBoardOptions utilise squadMoveModelPoolRef directement (pool per-fig toujours frais).
    if (mode === "squadModelMove") {
      if (resolvedMoveDestPoolRef.current.size > 0) {
        resolvedMoveDestPoolRef.current.clear();
      }
    } else {
      const shouldSyncMovePoolsFromState =
        keepMovementPickPool &&
        resolvedMoveDestPoolRef.current &&
        (enginePhaseForPools === "move" ||
          enginePhaseForPools === "command" ||
          (mode === "advancePreview" && selectedUnitId !== null) ||
          (phase === "shoot" && pendingMoveAfterShooting));
      if (shouldSyncMovePoolsFromState) {
        syncMoveDestinationPoolRefs({
          gameState: gameState ?? null,
          phase: enginePhaseForPools,
          mode,
          selectedUnitId,
          moveDestPoolRef: resolvedMoveDestPoolRef,
          footprintZoneRef,
          footprintMaskLoopsRef,
          pendingMoveAfterShooting,
        });
      }
    }

    if (
      mode === "advancePreview" &&
      selectedUnitId !== null &&
      resolvedMoveDestPoolRef.current.size === 0
    ) {
      if (typeof getAdvanceDestinations === "function") {
        const dests = getAdvanceDestinations(selectedUnitId);
        const s = new Set<string>();
        for (const d of dests) {
          s.add(`${Number(d.col)},${Number(d.row)}`);
        }
        if (s.size > 0) {
          resolvedMoveDestPoolRef.current = s;
        }
      }
      if (
        resolvedMoveDestPoolRef.current.size === 0 &&
        availableCellsOverride &&
        availableCellsOverride.length > 0
      ) {
        const s = new Set<string>();
        for (const c of availableCellsOverride) {
          s.add(`${Number(c.col)},${Number(c.row)}`);
        }
        resolvedMoveDestPoolRef.current = s;
      }
    }

    // Replay mode : footprintZoneRef jamais peuplé par l'API → calculer client-side
    // depuis les anchors (resolvedMoveDestPoolRef) + position courante, en expandant
    // chaque anchor via computeOccupiedHexes (identique à movement_handlers.py côté moteur).
    if (
      footprintZoneRef?.current &&
      footprintZoneRef.current.size === 0 &&
      resolvedMoveDestPoolRef.current.size > 0 &&
      selectedUnitId !== null
    ) {
      const selUnit = units.find((u) => String(u.id) === String(selectedUnitId));
      if (selUnit) {
        const baseSize = typeof selUnit.BASE_SIZE === "number" ? selUnit.BASE_SIZE : 1;
        const baseShape = typeof selUnit.BASE_SHAPE === "string" ? selUnit.BASE_SHAPE : "round";
        const fpZone = new Set<string>();
        const anchors = [
          ...resolvedMoveDestPoolRef.current,
          `${Number(selUnit.col)},${Number(selUnit.row)}`,
        ];
        for (const key of anchors) {
          const parts = key.split(",");
          const ac = Number(parts[0]);
          const ar = Number(parts[1]);
          if (baseShape === "round" && baseSize > 1) {
            const occupied = computeOccupiedHexes(ac, ar, baseShape, baseSize);
            for (const hex of occupied) {
              fpZone.add(`${hex[0]},${hex[1]}`);
            }
          } else {
            fpZone.add(key);
          }
        }
        footprintZoneRef.current = fpZone;
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
    setBoardViewportSize((currentSize) => {
      if (currentSize?.width === canvasWidth && currentSize.height === canvasHeight) {
        return currentSize;
      }
      return { width: canvasWidth, height: canvasHeight };
    });
    const configuredResolution = displayConfig.resolution;
    let baseRenderResolution: number;
    if (configuredResolution === "auto") {
      if (
        typeof window.devicePixelRatio !== "number" ||
        !Number.isFinite(window.devicePixelRatio)
      ) {
        throw new Error("Missing required browser value: window.devicePixelRatio");
      }
      baseRenderResolution = window.devicePixelRatio;
    } else if (typeof configuredResolution === "number") {
      baseRenderResolution = configuredResolution;
    } else {
      throw new Error("Missing required configuration value: boardConfig.display.resolution");
    }
    if (!Number.isFinite(baseRenderResolution) || baseRenderResolution <= 0) {
      throw new Error("Invalid configuration value: boardConfig.display.resolution");
    }
    const renderResolution = baseRenderResolution * boardZoom;

    // ✅ OPTIMIZED PIXI CONFIG - NO FALLBACKS, RAISE ERRORS IF MISSING
    const pixiConfig = {
      width: canvasWidth,
      height: canvasHeight,
      backgroundColor: parseInt(boardConfig.colors.background.replace("0x", ""), 16),
      backgroundAlpha: 1, // Ensure background is opaque
      antialias: displayConfig.antialias!,
      powerPreference: "high-performance" as WebGLPowerPreference,
      resolution: renderResolution,
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
      app.renderer.resolution = renderResolution;
      app.renderer.resize(canvasWidth, canvasHeight);
    }
    // PIXI calls nativeEvent.preventDefault() on pointer events by default, which suppresses
    // click/dblclick synthesis by the browser. This breaks double-click → movePreview when
    // React re-renders between the two clicks (removing the document capture handler that
    // previously blocked PIXI). Safe to disable on a game canvas (no text selection needed).
    app.renderer.events.autoPreventDefault = false;
    app.stage.position.set(canvasPaddingX, canvasPaddingTop);

    // Remove previous tutorial death ghost (étape 1-25) if any
    const existingGhost = app.stage.children.find((c) => c.name === "tutorial-death-ghost");
    if (existingGhost) {
      app.stage.removeChild(existingGhost);
      if (
        "destroy" in existingGhost &&
        typeof (existingGhost as PIXI.Container).destroy === "function"
      ) {
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
    canvas.style.width = `${canvasWidth}px`;
    canvas.style.height = `${canvasHeight}px`;
    canvas.style.border = displayConfig?.canvas_border ?? "1px solid #333";

    // Clear container and append canvas - EXACT BOARDREPLAY MATCH
    if (isNewApp) {
      canvasContainerRef.current.innerHTML = "";
      canvasContainerRef.current.appendChild(canvas);
    }

    const clearMovePreviewLos = () => {
      hoveredHexRef.current = null;
      if (hoverOverlayRef.current && !hoverOverlayRef.current.destroyed) {
        hoverOverlayRef.current.visible = false;
      }
    };

    // Set up board click handler IMMEDIATELY after canvas creation
    setupBoardClickHandler({
      onSelectUnit: stableCallbacks.current.onSelectUnit,
      onSkipUnit: stableCallbacks.current.onSkipUnit,
      onSkipShoot: (unitId: number) => {
        if (stableCallbacks.current.onSkipUnit) {
          stableCallbacks.current.onSkipUnit(unitId);
        }
      },
      onSkipFight: (unitId: number) => {
        stableCallbacks.current.onSkipFight?.(unitId);
      },
      onStartAttackPreview: (shooterId: number) => {
        const unit = units.find((u) => u.id === shooterId);
        if (unit) {
          stableCallbacks.current.onStartAttackPreview(shooterId, unit.col, unit.row);
        }
      },
      onShoot: stableCallbacks.current.onShoot,
      onCombatAttack: stableCallbacks.current.onFightAttack || (() => {}),
      onConfirmMove: () => {
        clearMovePreviewLos();
        squadMoveEntryTimeRef.current = performance.now();
        stableCallbacks.current.onConfirmMove();
      },
      onCancelMove: stableCallbacks.current.onCancelMove,
      onCancelCharge: stableCallbacks.current.onCancelCharge,
      onCancelAdvance: stableCallbacks.current.onCancelAdvance,
      onDeployUnit: stableCallbacks.current.onDeployUnit,
      onActivateCharge: stableCallbacks.current.onActivateCharge,
      onActivateFight: stableCallbacks.current.onActivateFight,
      onMoveCharger: (chargerId: number, dc: number, dr: number) => {
        clearMovePreviewLos();
        stableCallbacks.current.onMoveCharger?.(chargerId, dc, dr);
      },
      onChargeEnemyUnit: stableCallbacks.current.onChargeEnemyUnit || (() => {}),
      onAdvanceMove: (uid: number | string, dc: number, dr: number) => {
        clearMovePreviewLos();
        stableCallbacks.current.onAdvanceMove?.(uid, dc, dr);
      },
      onPileInMove: (uid: number, dc: number, dr: number) => {
        clearMovePreviewLos();
        stableCallbacks.current.onPileInMove?.(uid, dc, dr);
      },
      onStartMovePreview: onStartMovePreview,
      onDirectMove: (
        unitId: number | string,
        col: number | string,
        row: number | string,
        orientation?: number
      ) => {
        clearMovePreviewLos();
        onDirectMove(unitId, col, row, orientation);
      },
      onStartSquadModelMove: (unitId: number | string) => {
        void squadMoveCallbacksRef.current.onStartSquadModelMove?.(unitId);
      },
      onMoveModelInPlan: (modelId: string, col: number, row: number) => {
        squadMoveCallbacksRef.current.onMoveModelInPlan?.(modelId, col, row);
      },
      onMoveModelInChargePlan: (modelId: string, col: number, row: number) => {
        chargeModelCallbacksRef.current.onMoveModelInChargePlan?.(modelId, col, row);
      },
      onCancelChargeModelMove: () => {
        void chargeModelCallbacksRef.current.onCancelChargeModelMove?.();
      },
      onChargeFocusTargetClick: (targetId: number) => {
        void chargeModelCallbacksRef.current.onChargeFocusTargetClick?.(targetId);
      },
      onMovePileInModel: (modelId: string, col: number, row: number) => {
        pileInModelCallbacksRef.current.onMovePileInModel?.(modelId, col, row);
      },
      onCancelPileInModelMove: () => {
        void pileInModelCallbacksRef.current.onCancelPileInModelMove?.();
      },
      onMoveConsolidationModel: (modelId: string, col: number, row: number) => {
        consolidationModelCallbacksRef.current.onMoveConsolidationModel?.(modelId, col, row);
      },
      onCancelConsolidationModelMove: () => {
        void consolidationModelCallbacksRef.current.onCancelConsolidationModelMove?.();
      },
    });

    // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Listen for advance button click
    const advanceClickHandler = (e: Event) => {
      const { unitId } = (e as CustomEvent<{ unitId: number }>).detail;
      if (onAdvance) {
        onAdvance(unitId);
      }
    };
    window.addEventListener("boardAdvanceClick", advanceClickHandler);

    // Right click cancels current action
    const contextMenuHandler = (e: Event) => {
      e.preventDefault();

      // squad.md brique 3 : clic droit en mode plan par-figurine = annule le deplacement
      // de la fig ACTIVE → la replace a sa position de debut de phase (ne quitte pas le mode).
      if (mode === "squadModelMove") {
        const activeMid = squadMovePlanRef.current?.activeModelId;
        if (activeMid) {
          squadMoveCallbacksRef.current.onResetModelInPlan?.(activeMid);
        }
        return;
      }

      const isMoveUiPhase = phase === "move" || phase === "command";
      if (isMoveUiPhase && mode === "select") {
        const activeMu = gameState?.active_movement_unit;
        if (activeMu != null && activeMu !== "") {
          if (!onSkipUnit) {
            throw new Error(
              "BoardPvp: onSkipUnit is required when cancelling move-in-progress (active_movement_unit set)"
            );
          }
          const activeId = parseRequiredUnitId(
            activeMu,
            "contextmenu postpone movement active_movement_unit"
          );
          void onSkipUnit(activeId);
          return;
        }
        if (selectedUnitId !== null) {
          onSelectUnit(null);
        }
        return;
      } else if (phase === "shoot" && mode === "advancePreview" && selectedUnitId !== null) {
        onCancelAdvance?.();
      } else if (phase === "shoot" && mode === "movePreview") {
        onCancelMove?.();
      } else if (phase === "shoot") {
        if (targetPreview) {
          onCancelTargetPreview?.();
        }
      } else if (
        phase === "fight" &&
        (mode === "pileInPreview" || mode === "consolidationPreview")
      ) {
        onSkipPileIn?.();
      } else if (mode === "movePreview" || mode === "attackPreview") {
        onCancelMove?.();
      }
    };
    if (app.view?.addEventListener) {
      app.view.addEventListener("contextmenu", contextMenuHandler);
    }

    // ✅ RESTRUCTURED: Calculate ALL highlight data BEFORE any drawBoard calls
    const availableCells: { col: number; row: number }[] = [];
    /** ``===`` sur id casse le match (API string / state number) → pas de zone move / BASE_SIZE = 1. */
    const selectedUnit =
      selectedUnitId == null
        ? undefined
        : units.find((u) => String(u.id) === String(selectedUnitId));

    // Déploiement : la zone est affichée par le polygon rempli (drawBoard, deployment_zones du
    // terrain). On ne surligne plus le pool hex-par-hex ici (doublon visuel). Le drop reste validé
    // par deployPoolRef (clic) et deployment_pools (ghost), indépendamment de availableCells.

    // Surbrillance du pool de la figurine active : move (BFS) OU charge (eligible) par-figurine.
    if (
      isPerModelMove &&
      effectivePerModelPlan?.activeModelId &&
      effectivePerModelPoolRef?.current
    ) {
      for (const key of effectivePerModelPoolRef.current) {
        const sep = key.indexOf(",");
        availableCells.push({
          col: Number(key.slice(0, sep)),
          row: Number(key.slice(sep + 1)),
        });
      }
    }

    // Charge preview: chargeCells & targets
    let chargeCells: { col: number; row: number }[] = [];
    let chargeTargets: Unit[] = [];

    // Fight preview: fightTargets for red outline on enemies within fight range
    let fightTargets: Unit[] = [];
    // Centres des socles (par-figurine) de l'unité combattante : rendus en disques lisses
    // (zone d'engagement) côté board, au lieu de cases hex dures.
    const fightEngagementModelCenters: Array<[number, number]> = [];
    const gsRulesFight = (
      gameState as { config?: { game_rules?: { engagement_zone?: number } } } | null | undefined
    )?.config?.game_rules;
    const cfgRulesFight = gameConfig?.game_rules as { engagement_zone?: number } | undefined;
    const engagementFromRules =
      gsRulesFight?.engagement_zone ?? cfgRulesFight?.engagement_zone ?? 1;
    const inchesToSubhexRaw = (boardConfig as unknown as { inches_to_subhex?: number })
      .inches_to_subhex;
    const inchesToSubhex = typeof inchesToSubhexRaw === "number" ? inchesToSubhexRaw : 10;
    // engagement_zone est en POUCES ; conversion en sous-hexes via inches_to_subhex (miroir backend
    // spatial_relations.get_engagement_zone). Ex. 2" sur board ×5 → 10 sous-hexes.
    const fightEngagementHexSteps = engagementFromRules * inchesToSubhex;

    if (phase === "fight" && selectedUnit && (mode === "select" || mode === "attackPreview")) {
      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers (imported at top)

      if (!selectedUnit.CC_WEAPONS || selectedUnit.CC_WEAPONS.length === 0) {
        if (mode === "attackPreview") {
          throw new Error(
            `Unit ${selectedUnit.id} (${selectedUnit.type || "unknown"}) has no melee weapons for fight phase`
          );
        }
      } else {
        // Aligné sur min_distance_between_sets (empreinte ↔ empreinte), §3.3 moteur.
        // Empreinte = union des figs vivantes (occupied_hexes_by_model), pas l'ancre du squad.
        const ucFight = gameState?.units_cache as
          | Record<
              string,
              { HP_CUR?: number; occupied_hexes_by_model?: Record<string, [number, number]> }
            >
          | undefined;
        const attackerFp =
          squadFootprintHexKeysFromModelCenters(
            ucFight?.[String(selectedUnit.id)]?.occupied_hexes_by_model,
            selectedUnit
          ) ?? unitFootprintHexKeys(selectedUnit);
        fightTargets = units.filter((u) => {
          if (u.player === selectedUnit.player) {
            return false;
          }
          if (u.HP_CUR == null)
            throw new Error(`Unit ${u.id} missing HP_CUR for fight target filter`);
          let hp = u.HP_CUR;
          const ce = ucFight?.[String(u.id)];
          if (ce && typeof ce.HP_CUR === "number") {
            hp = ce.HP_CUR;
          }
          if (hp <= 0) {
            return false;
          }
          const enemyFp =
            squadFootprintHexKeysFromModelCenters(ce?.occupied_hexes_by_model, u) ??
            unitFootprintHexKeys(u);
          return (
            minHexDistanceBetweenFootprintKeySets(attackerFp, enemyFp, fightEngagementHexSteps) <=
            fightEngagementHexSteps
          );
        });

        // Zone d'engagement par FIGURINE (union du squad), pas l'ancre : on collecte les centres
        // de socles ; le board les rend en disques lisses fondus (cf. fightEngagementZone).
        const ringByModel = ucFight?.[String(selectedUnit.id)]?.occupied_hexes_by_model;
        const ringCenters: Array<[number, number]> =
          ringByModel && Object.values(ringByModel).length > 0
            ? Object.values(ringByModel).map(([c, r]) => [Number(c), Number(r)] as [number, number])
            : [[selectedUnit.col, selectedUnit.row]];
        fightEngagementModelCenters.push(...ringCenters);
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
      // Pool membership alone is not enough: once a unit is activated, the backend removes it
      // from charge_activation_pool but keeps active_charge_unit. If we only checked eligibleUnitIds,
      // isEligible would be false during chargePreview and we'd never draw valid destinations (violet
      // hexes near the declared target).
      const sid =
        typeof selectedUnit.id === "number"
          ? selectedUnit.id
          : parseInt(selectedUnit.id as string, 10);
      const inChargePool = eligibleUnitIds.includes(sid);
      const activeChargeRaw = gameState?.active_charge_unit;
      const isActiveCharger = activeChargeRaw != null && String(activeChargeRaw) === String(sid);
      // Pool moteur déjà dans le state React (result.valid_destinations) : afficher même si
      // game_state n’a pas active_charge_unit / charge_activation_pool (sync API partielle).
      const destPreview = getChargeDestinations(selectedUnit.id);
      const hasPendingChargePreview =
        mode === "chargePreview" &&
        destPreview.length > 0 &&
        chargingUnitId != null &&
        chargingUnitId === sid;
      const showChargeDestinationLayer = inChargePool || isActiveCharger || hasPendingChargePreview;

      if (showChargeDestinationLayer) {
        // Ancres BFS = destPreview ; affichage = union des empreintes finales (API) pour couvrir
        // la zone autour de la cible, pas une poignée de points près du chargeur.
        const overlay = chargePreviewOverlayHexes ?? [];
        chargeCells = overlay.length > 0 ? overlay : destPreview;

        // Red outline: enemy units that can be reached via valid charge movement
        chargeTargets = units.filter((u) => {
          if (u.player === selectedUnit.player) return false;

          return destPreview.some((dest) => {
            const dc = Array.isArray(dest) ? dest[0] : dest.col;
            const dr = Array.isArray(dest) ? dest[1] : dest.row;
            const cube1 = offsetToCube(dc, dr);
            const cube2 = offsetToCube(u.col, u.row);
            return cubeDistance(cube1, cube2) === 1;
          });
        });
      }
    }

    // Slice G : charge/pile-in par-figurine — zone de landing = pool eligible de la fig active, rendu
    // en hexes simples (1:1 avec les hexes cliquables, pas en disques d'empreinte).
    if (
      perModelChargeLike &&
      activeChargeLikePlan?.activeModelId &&
      activeChargeLikePoolRef?.current
    ) {
      const cells: { col: number; row: number }[] = [];
      for (const key of activeChargeLikePoolRef.current) {
        const sep = key.indexOf(",");
        cells.push({ col: Number(key.slice(0, sep)), row: Number(key.slice(sep + 1)) });
      }
      chargeCells = cells;
    }

    // ✅ MOVEMENT PREVIEW: Use backend-computed destinations (valid_move_destinations_pool)
    // instead of recalculating client-side. The backend BFS handles walls, footprints,
    // engagement zones, and pathfinding correctly on the ×10 board.
    if (
      selectedUnit &&
      mode === "select" &&
      eligibleUnitIds?.includes(
        typeof selectedUnit.id === "number"
          ? selectedUnit.id
          : parseInt(selectedUnit.id as string, 10)
      )
    ) {
      const enginePhase = gameState?.phase ?? phase;
      // Move : pas de cellules « zone empreinte » dans availableCells (disques d’ancres uniquement).
      if (enginePhase !== "move" && phase !== "charge") {
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

    const resolveShootingPreviewSource = (): {
      unit: Unit;
      fromCol: number;
      fromRow: number;
    } | null => {
      if (mode === "advancePreview" && phase === "shoot") {
        if (!selectedUnit?.RNG_WEAPONS?.length) {
          return null;
        }
        if (!shootAdvanceLosAnchor) {
          return null;
        }
        return {
          unit: selectedUnit,
          fromCol: shootAdvanceLosAnchor.col,
          fromRow: shootAdvanceLosAnchor.row,
        };
      }

      // Shoot-phase movePreview = advance-preview: source LoS depuis la destination
      // pour visualiser le tir post-advance. En move-phase squad movePreview, on ne
      // calcule pas de LoS (user requirement : zero LoS pendant le hover squad).
      if (mode === "movePreview" && movePreview && phase === "shoot") {
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

      if (phase === "shoot" && mode === "squadModelShoot") {
        if (!squadShootPlanRef.current?.activeModelId) return null;
        const plan = squadShootPlanRef.current;
        const shootUnit = units.find((u) => String(u.id) === String(plan.unitId));
        if (!shootUnit) return null;
        const uc = gameState?.units_cache as
          | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
          | undefined;
        const pos =
          plan.activeModelId != null
            ? uc?.[String(plan.unitId)]?.occupied_hexes_by_model?.[plan.activeModelId]
            : undefined;
        if (!pos) return null;
        return { unit: shootUnit, fromCol: pos[0], fromRow: pos[1] };
      }

      if (phase === "shoot" && selectedUnit) {
        const activeShoot = (
          gameState as { active_shooting_unit?: string | number } | null | undefined
        )?.active_shooting_unit;
        const isActiveShooter =
          activeShoot != null && String(activeShoot) === String(selectedUnitId);
        const sl = selectedUnit.SHOOT_LEFT;
        if ((sl === undefined || sl <= 0) && !isActiveShooter) {
          return null;
        }
        return {
          unit: selectedUnit,
          fromCol: selectedUnit.col,
          fromRow: selectedUnit.row,
        };
      }

      return null;
    };

    const appendShootingPreviewCells = (source: {
      unit: Unit;
      fromCol: number;
      fromRow: number;
    }) => {
      if (!source.unit.RNG_WEAPONS || source.unit.RNG_WEAPONS.length === 0) {
        return;
      }

      const attackCellSet = new Set<string>();
      const range = getMaxRangedRange(source.unit);
      if (range <= 0) {
        return;
      }
      const enforceBackendTargetsOnly = phase === "shoot";
      const backendTargetSet = shootPreviewBackendIds;

      if (isWasmReady()) {
        const ucByModel = unitsCacheModelCenters(gameState?.units_cache);
        const losPreview = buildLosPreviewFromSource({
          source,
          units,
          boardCols: BOARD_COLS,
          boardRows: BOARD_ROWS,
          wallHexes: boardConfig.wall_hexes,
          wallHexesOverride,
          obscuringZones: losObscuringZones,
          terrainZones: losTerrainZones,
          maxRange: range,
          distanceMetric: rangedPreviewMetric(gameConfig),
          unitsCacheByModel: ucByModel,
          shooterModelCenters:
            source.fromCol === source.unit.col && source.fromRow === source.unit.row
              ? ucByModel?.[String(source.unit.id)]
              : undefined,
        });
        if (enforceBackendTargetsOnly) {
          // Même cône LoS terrain que le survol move (WASM + pastilles clair/couvert), sans corridor hex tireur→cible.
          const coverKeyDedupe = new Set<string>();
          for (const cell of losPreview.terrainCoverCells) {
            const key = `${cell.col},${cell.row}`;
            coverKeyDedupe.add(key);
            coverCells.push(cell);
            losVisibilityRatioByHex.set(key, 0.5);
          }
          for (const cell of losPreview.clearCells) {
            const key = `${cell.col},${cell.row}`;
            if (!attackCellSet.has(key)) {
              attackCellSet.add(key);
              attackCells.push(cell);
              losVisibilityRatioByHex.set(key, 1.0);
            }
          }
          // Cases visibles des cibles ciblables (backend, règle 06.01/13.10) peintes par-dessus
          // le cône WASM → une unité qui blinke a toujours ses cases visibles affichées, même si
          // le cône générique ne les atteint pas (exclusion obscuring par-figurine).
          for (const cell of flattenVisibleCellsByTarget(
            source.unit.visible_cells_by_target,
            backendTargetSet ?? undefined
          )) {
            const key = `${cell.col},${cell.row}`;
            if (!attackCellSet.has(key)) {
              attackCellSet.add(key);
              attackCells.push(cell);
              losVisibilityRatioByHex.set(key, 1.0);
            }
          }
          if (backendTargetSet && backendTargetSet.size > 0) {
            for (const [id, inCover] of Object.entries(losPreview.coverByUnitId)) {
              if (inCover && backendTargetSet.has(String(id))) {
                coverTargets.add(id);
              }
            }
          }
          return;
        }
        const coverKeyDedupe = new Set<string>();
        for (const cell of losPreview.terrainCoverCells) {
          const key = `${cell.col},${cell.row}`;
          coverKeyDedupe.add(key);
          coverCells.push(cell);
          losVisibilityRatioByHex.set(key, 0.5);
        }
        for (const cell of losPreview.clearCells) {
          const key = `${cell.col},${cell.row}`;
          if (!attackCellSet.has(key)) {
            attackCellSet.add(key);
            attackCells.push(cell);
            losVisibilityRatioByHex.set(key, 1.0);
          }
        }
        for (const [id, inCover] of Object.entries(losPreview.coverByUnitId)) {
          if (inCover) {
            coverTargets.add(id);
          }
        }
      }
    };

    const shootingPreviewSource = resolveShootingPreviewSource();
    if (shootingPreviewSource) {
      const overviewUnitId = blinkingLosOverviewUnitId ?? null;
      const ucOverview = gameState?.units_cache as
        | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
        | undefined;
      const byModel =
        overviewUnitId != null && Number(shootingPreviewSource.unit.id) === Number(overviewUnitId)
          ? ucOverview?.[String(overviewUnitId)]?.occupied_hexes_by_model
          : undefined;
      if (byModel) {
        // Vue escouade : voile LoS depuis CHAQUE fig vivante de l'escouade (union des cellules).
        for (const pos of Object.values(byModel)) {
          appendShootingPreviewCells({
            unit: shootingPreviewSource.unit,
            fromCol: pos[0],
            fromRow: pos[1],
          });
        }
      } else {
        appendShootingPreviewCells(shootingPreviewSource);
      }
    }

    // Les HP blink / unités en LoS viennent uniquement du backend pour éviter toute fausse cible.
    // Le calcul LoS frontend sert seulement au tracé bleu de confort.
    const effectiveBlinkingUnits = effectiveBlinkingUnitsWithMovePreview;
    const effectiveBlinkingAttackerId =
      phase === "move" &&
      (mode === "select" || mode === "movePreview") &&
      movePreviewLosBlinkIds.length > 0 &&
      gameState?.active_movement_unit != null
        ? parseRequiredUnitId(gameState?.active_movement_unit, "gameState.active_movement_unit")
        : blinkingAttackerId;
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
      objective_zones?: Array<{
        id: string;
        hexes: Array<[number, number] | { col: number; row: number }>;
        shape?: string;
        vertices?: [number, number][];
        top_left?: [number, number];
        bottom_right?: [number, number];
      }>;
      wall_hexes: [number, number][];
      walls?: Array<{
        start: { col: number; row: number };
        end: { col: number; row: number };
        thickness?: number;
      }>;
      terrain_zones?: Array<{
        id: string;
        hexes: Array<[number, number] | { col: number; row: number }>;
        shape?: string;
        vertices?: [number, number][];
        top_left?: [number, number];
        bottom_right?: [number, number];
      }>;
    }
    // Objectifs = terrains "objective": true : la géométrie (polygone + vertices) vient de
    // boardConfig.objective_zones (endpoint board) et doit être PRÉFÉRÉE pour le rendu — sinon la
    // forme est perdue et la zone retombe sur un cercle englobant. objectivesOverride (runtime
    // gameState.objectives = {name, hexes} sans shape) ne sert qu'en repli (ex. replay sans board).
    const effectiveObjectiveZones =
      boardConfig.objective_zones && boardConfig.objective_zones.length > 0
        ? boardConfig.objective_zones
        : objectivesOverride && objectivesOverride.length > 0
          ? objectivesOverride.map((obj) => ({ id: obj.name, hexes: obj.hexes }))
          : boardConfig.objective_zones;

    const boardConfigWithOverrides: BoardConfigForDrawBoard = {
      ...boardConfig,
      colors: {
        ...boardConfig.colors,
        attack: boardConfig.colors.attack || "#FF0000", // Ensure attack is defined
      },
      wall_hexes: wallHexesOverride ? effectiveWallHexes : boardConfig.wall_hexes || [],
      objective_hexes: effectiveObjectiveHexes,
      objective_zones: effectiveObjectiveZones,
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
      if (!primaryObjectiveConfig.control?.method || !primaryObjectiveConfig.control.tie_behavior) {
        throw new Error("Replay rules primary_objective.control is missing required fields");
      }
      if (!primaryObjectiveConfig.control.control_method) {
        throw new Error("Replay rules primary_objective.control.control_method is missing");
      }
      if (
        !primaryObjectiveConfig.timing?.default_phase ||
        !primaryObjectiveConfig.timing.round5_second_player_phase
      ) {
        throw new Error("Replay rules primary_objective.timing is missing required fields");
      }
      if (primaryObjectiveConfig.control.method !== "oc_sum_greater") {
        throw new Error(
          `Unsupported objective control method: ${primaryObjectiveConfig.control.method}`
        );
      }
      if (!["secured", "default"].includes(primaryObjectiveConfig.control.control_method)) {
        throw new Error(
          `Unsupported control_method: ${primaryObjectiveConfig.control.control_method}`
        );
      }
      if (primaryObjectiveConfig.control.tie_behavior !== "no_control") {
        throw new Error(
          `Unsupported objective tie behavior: ${primaryObjectiveConfig.control.tie_behavior}`
        );
      }
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
      if (!primaryObjectiveConfig.control?.method || !primaryObjectiveConfig.control.tie_behavior) {
        throw new Error("primary_objective.control is missing required fields");
      }
      if (!primaryObjectiveConfig.control.control_method) {
        throw new Error("primary_objective.control.control_method is missing");
      }
      if (
        !primaryObjectiveConfig.timing?.default_phase ||
        !primaryObjectiveConfig.timing.round5_second_player_phase
      ) {
        throw new Error("primary_objective.timing is missing required fields");
      }
      if (primaryObjectiveConfig.control.method !== "oc_sum_greater") {
        throw new Error(
          `Unsupported objective control method: ${primaryObjectiveConfig.control.method}`
        );
      }
      if (!["secured", "default"].includes(primaryObjectiveConfig.control.control_method)) {
        throw new Error(
          `Unsupported control_method: ${primaryObjectiveConfig.control.control_method}`
        );
      }
      if (primaryObjectiveConfig.control.tie_behavior !== "no_control") {
        throw new Error(
          `Unsupported objective tie behavior: ${primaryObjectiveConfig.control.tie_behavior}`
        );
      }
      objectiveControlStartTurn = primaryObjectiveConfig.scoring.start_turn;
    }
    if (objectiveControlStartTurn === undefined || objectiveControlStartTurn === null) {
      throw new Error("objective control start_turn is missing");
    }
    // Objective control (terrain colouring) follows the authoritative backend state
    // game_state.objective_controllers (Rule 14.02), keyed by objective id and refreshed by
    // the engine at each configured phase/turn boundary (game_config.objective_control_check).
    // We map it onto the objective hexes from the STATIC board config (objective_zones), which
    // is always present — unlike game_state.objectives, which the API omits on post-action
    // responses (that omission is exactly what used to blank the terrain colours).
    let objectiveControl: { [hexKey: string]: number | null } = {};
    const backendObjectiveControllers =
      (
        gameState as unknown as {
          objective_controllers?: Record<string, number | null>;
        } | null
      )?.objective_controllers ?? {};
    const objectiveZonesForControl =
      (
        boardConfig as unknown as {
          objective_zones?: Array<{
            id: string | number;
            hexes: Array<[number, number] | { col: number; row: number }>;
          }>;
        } | null
      )?.objective_zones ?? [];
    for (const zone of objectiveZonesForControl) {
      const controller = backendObjectiveControllers[String(zone.id)] ?? null;
      for (const hex of zone.hexes) {
        const key = Array.isArray(hex) ? `${hex[0]},${hex[1]}` : `${hex.col},${hex.row}`;
        objectiveControl[key] = controller;
      }
    }

    // Replay mode: override with pre-computed snapshot (correct sticky state at exact action index)
    if (objectiveControlOverride !== undefined) {
      objectiveControl = objectiveControlOverride;
    }

    // Compute units fingerprint to determine if unit re-rendering is needed
    const unitsFingerprint = (() => {
      const parts: string[] = [];
      const ucFp = gameState?.units_cache as Record<string, unknown> | undefined;
      for (const u of units) {
        const orientation = orientationStepForBoard(u, gameState?.units_cache);
        parts.push(
          `${u.id},${u.col},${u.row},o${orientation ?? ""},${hpCurForBoardFingerprint(u, ucFp)},rng${u.selectedRngWeaponIndex ?? ""},cc${u.selectedCcWeaponIndex ?? ""},mw${u.manualWeaponSelected ? 1 : 0},bs${u.battle_shocked ? 1 : 0},cg${unitsCharged?.includes(Number(u.id)) ? 1 : 0}`
        );
      }
      const moveLosIds = [...movePreviewLosBlinkIds].sort((a, b) => a - b).join(",");
      const backendBlink = (stableBlinkingUnits ?? [])
        .slice()
        .sort((a, b) => a - b)
        .join(",");
      // squad.md brique 3 : le ghost rend les figs aux positions du PLAN provisoire (pas units_cache).
      // Sans ca dans l'empreinte, un deplacement de fig ne re-render pas (ghost fige) → "move annule".
      const squadPlanFp = squadMovePlan
        ? `${squadMovePlan.unitId}:${squadMovePlan.activeModelId ?? ""}:` +
          Object.entries(squadMovePlan.models)
            .map(([m, p]) => `${m}@${p.col},${p.row}`)
            .join(",") +
          ":" +
          Object.entries(squadMovePlan.perModelValid)
            .map(([m, v]) => `${m}=${v ? 1 : 0}`)
            .join(",")
        : "";
      // Charge/pile-in par-figurine : même logique que squadPlanFp — sans les positions du plan dans
      // l'empreinte, poser/sélectionner une fig ne re-render pas le ghost (fige à l'origine).
      const chargePlanFp = activeChargeLikePlan
        ? `${activeChargeLikePlan.unitId}:${activeChargeLikePlan.activeModelId ?? ""}:` +
          Object.entries(activeChargeLikePlan.models)
            .map(([m, p]) => `${m}@${p.col},${p.row}`)
            .join(",")
        : "";
      // Tir par-arme : empreinte des intents (redraw des voiles/lignes quand ils changent).
      const squadShootFp = squadShootPlan
        ? `${squadShootPlan.unitId}:w${squadShootPlan.activeWeaponIndex ?? ""}:` +
          squadShootPlan.declarations
            .map((d) => `${d.model_id}.${d.weapon_index}>${d.target_unit_id}`)
            .join(",")
        : "";
      // Combat par-figurine : empreinte des intents (redraw voile/lignes vertes quand ils changent).
      const squadFightFp = squadFightPlan
        ? `${squadFightPlan.unitId}:m${squadFightPlan.activeModelId ?? ""}:` +
          squadFightPlan.declarations
            .map((d) => `${d.model_id}.${d.weapon_index}>${d.target_unit_id}`)
            .join(",")
        : "";
      // Déploiement par escouade (PvP "active") : même logique que squadPlanFp — sans les positions
      // du plan dans l'empreinte, le drop/repositionnement ne re-render pas (ghost jamais dessiné).
      const deployPlanFp = deployPlan
        ? `${deployPlan.unitId}:${deployPlan.activeModelId ?? ""}:${deployPlan.placed ? 1 : 0}:` +
          Object.entries(deployPlan.models)
            .map(([m, p]) => `${m}@${p.col},${p.row}`)
            .join(",") +
          ":" +
          Object.entries(deployPlan.perModelValid)
            .map(([m, v]) => `${m}=${v ? 1 : 0}`)
            .join(",")
        : "";
      return `${parts.join("|")}#${selectedUnitId}#${phase}#${mode}#${movePreview?.destCol ?? ""},${movePreview?.destRow ?? ""},o${movePreview?.orientation ?? ""}#${attackPreview?.col ?? ""},${attackPreview?.row ?? ""}#sqshoot:${squadShootFp}#sqfight:${squadFightFp}#${blinkVersion}#${fightSubPhase}#fe:${(gameState?.fight_eligible_units ?? []).join(",")}#${chargeTargetId}#cpti:${chargePreviewTargetIds?.join(",") ?? ""}#chfocus:${chargeFocusActive ? 1 : 0}#pifocus:${pileInFocusActive ? 1 : 0}#pieng:${pileInMovePlan?.engagedModels?.join(",") ?? ""}#pitgt:${pileInMovePlan?.pileInTargets?.join(",") ?? ""}#${shootingTargetId}#${shootingUnitId}#${movingUnitId}#${chargingUnitId}#${chargeRoll ?? ""}#${chargeSuccess === true ? "1" : chargeSuccess === false ? "0" : ""}#${fightingUnitId}#${fightTargetId}#${advancingUnitId}#${ruleChoiceHighlightedUnitId}#${moveLosIds}#${movePreviewLosCoverKey}#mtf:${movePreviewLosTooFarKey}#bc:${blinkingCoverByUnitIdKey}#bttf:${blinkingHiddenTooFarByUnitIdKey}#swlos:${shootPreviewWasmLos.key}#saa:${shootAdvanceLosAnchorKey}#bb:${backendBlink}#chov:${chargePreviewOverlayKey}#cref:${chargeReferenceKey}#sqplan:${squadPlanFp}#chgplan:${chargePlanFp}#dg:${deadModelGhostsForRender.length}#hpbm:${hpBarPerModel ? 1 : 0}#hpbe:${hpBarBlinkEnlarged ? 1 : 0}#swp:${showWoundProbability ? 1 : 0}#sbpm:${statusBadgePerModel ? 1 : 0}#hp13:${[...movePreviewHiddenModelIds].sort().join(",")}#flee:${fleePreviewUnitId ?? ""}#hide:${hideIndicators ? 1 : 0}#dplan:${deployPlanFp}#elig:${[...eligibleUnitIds].sort((a, b) => a - b).join(",")}#lvl:${currentLevel}`;
    })();
    const unitsChanged = unitsFingerprint !== unitsFingerprintRef.current;

    // Reuse cached static board layers when the board config and objective control haven't changed.
    const objControlKey = Object.entries(objectiveControl)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${k}:${v ?? "n"}`)
      .join("|");
    const zonesKey = (boardConfigWithOverrides.objective_zones ?? [])
      .map((z) => `${z.id}:${(z as { shape?: string }).shape ?? "hexes"}`)
      .join(",");
    const bcKey = `${boardConfigWithOverrides.cols}x${boardConfigWithOverrides.rows}|oc:${objControlKey}|oz:${zonesKey}|dep:${phase === "deployment" ? 1 : 0}|lvl:${currentLevel}|ofl:${[...occupiedFloorLevels].sort((a, b) => a - b).join(".")}`;
    const canReuseStatic =
      staticBoardConfigKeyRef.current === bcKey && staticBoardRef.current !== null;

    const gsRules = (
      gameState as { config?: { game_rules?: { engagement_zone?: number } } } | null | undefined
    )?.config?.game_rules;
    const cfgRules = gameConfig?.game_rules as { engagement_zone?: number } | undefined;
    // engagement_zone en POUCES → sous-hexes via inches_to_subhex (miroir backend get_engagement_zone).
    const engagementZoneSteps =
      (gsRules?.engagement_zone ?? cfgRules?.engagement_zone ?? 1) * inchesToSubhex;
    const hasChargeFootprintOverlay = (chargePreviewOverlayHexes?.length ?? 0) > 0;
    const chargeEngagementHalo =
      !hasChargeFootprintOverlay &&
      enginePhaseForPools === "charge" &&
      mode === "chargePreview" &&
      chargeTargetId != null &&
      typeof engagementZoneSteps === "number" &&
      engagementZoneSteps > 1
        ? (() => {
            const tu = units.find((u) => String(u.id) === String(chargeTargetId));
            if (!tu) return undefined;
            return {
              centerCol: tu.col,
              centerRow: tu.row,
              zoneHexSteps: engagementZoneSteps,
            };
          })()
        : undefined;

    // Contour lisse fig seule. Pour un squad multi-figs, le remplissage par disques fondus
    // (fightEngagementZone) tient lieu de zone d'engagement (union propre).
    const fightRingByModel = (
      gameState?.units_cache as
        | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
        | undefined
    )?.[String(selectedUnit?.id)]?.occupied_hexes_by_model;
    const fightRingIsSingleFigure =
      !fightRingByModel || Object.values(fightRingByModel).length <= 1;
    const fightEngagementRing =
      enginePhaseForPools === "fight" &&
      selectedUnit &&
      mode === "attackPreview" &&
      selectedUnit.CC_WEAPONS &&
      selectedUnit.CC_WEAPONS.length > 0 &&
      fightRingIsSingleFigure
        ? getFightEngagementRingBoardPixels(
            selectedUnit,
            fightEngagementHexSteps,
            HEX_RADIUS,
            MARGIN
          )
        : undefined;

    // Zone d'engagement rendue en disques pleins fondus (union par-figurine), même rayon que le
    // contour ci-dessus → rendu lisse identique aux previews move/charge/pile-in.
    const fightEngagementZone =
      enginePhaseForPools === "fight" &&
      selectedUnit &&
      mode === "attackPreview" &&
      selectedUnit.CC_WEAPONS &&
      selectedUnit.CC_WEAPONS.length > 0 &&
      fightEngagementModelCenters.length > 0 &&
      fightEngagementHexSteps > 0
        ? {
            disks: fightEngagementModelCenters.map(([cc, cr]) => {
              const ring = getFightEngagementRingBoardPixels(
                {
                  col: cc,
                  row: cr,
                  BASE_SHAPE: selectedUnit.BASE_SHAPE,
                  BASE_SIZE: selectedUnit.BASE_SIZE,
                },
                fightEngagementHexSteps,
                HEX_RADIUS,
                MARGIN
              );
              return { cx: ring.cx, cy: ring.cy, rOuter: ring.rOuter };
            }),
          }
        : null;

    /**
     * Ancres pour les disques : UI **ou** moteur en move/command (évite désaccord phase affichée / ``game_state``).
     */
    const gsPhaseForMove = gameState?.phase;
    const moveDestinationAnchorsFromState =
      mode !== "squadModelMove" &&
      phase !== "deployment" &&
      (effectivePhase === "move" ||
        gsPhaseForMove === "move" ||
        gsPhaseForMove === "command" ||
        mode === "advancePreview" ||
        pendingMoveAfterShooting)
        ? pickMoveDestinationAnchorsFromGameState(gameState)
        : undefined;

    const activeMovementId = gameState?.active_movement_unit;
    const unitForMoveFootprint =
      phase === "move" && activeMovementId != null
        ? units.find((u) => String(u.id) === String(activeMovementId))
        : undefined;
    const unitForFootprintBase = unitForMoveFootprint ?? selectedUnit;

    /** Pile-in / consolidation : masque uniquement depuis ``footprintZonePoolRef`` (union hex → polygone lissé côté client, comme move sans ``move_preview_footprint_mask_loops``). */
    const activeFootprintMaskLoops = (() => {
      let raw: number[][] | null;
      if (mode === "squadModelMove") {
        raw = squadMovePlan?.activeModelId ? (squadMoveModelMaskLoopsRef?.current ?? null) : null;
      } else {
        raw =
          effectivePhase === "fight" &&
          (mode === "pileInPreview" || mode === "consolidationPreview")
            ? null
            : normalizeMaskLoopsFromApi(
                (gameState as { move_preview_footprint_mask_loops?: unknown })
                  .move_preview_footprint_mask_loops
              );
      }
      if (!raw) return raw;
      const ds =
        (boardConfig?.display as { display_scale?: number } | undefined)?.display_scale ?? 1;
      if (ds === 1) return raw;
      return raw.map((loop) => loop.map((v) => v * ds));
    })();

    // charge/pile-in ModelMove : boucles lissées (monde) de la zone de landing de la fig active,
    // fournies par le backend (charge_plan_state / pile_in_plan_state). Normalisées au format plat +
    // display_scale, comme la branche gameState ci-dessus. Rendu lissé (Chaikin) au lieu de disques.
    const chargeModelMaskLoops = (() => {
      if (!perModelChargeLike) return null;
      const norm = normalizeMaskLoopsFromApi(activeChargeLikeMaskLoopsRef?.current);
      if (!norm) return null;
      const ds =
        (boardConfig?.display as { display_scale?: number } | undefined)?.display_scale ?? 1;
      return ds === 1 ? norm : norm.map((loop) => loop.map((v) => v * ds));
    })();

    const drawBoardOptions: DrawBoardOptions = {
      availableCells: effectiveAvailableCells,
      attackCells,
      coverCells,
      chargeCells,
      // advancePreview : même ancres que move (game_state) — pas de doublon empreinte hex-par-hex
      advanceCells: [],
      blockedTargets,
      coverTargets,
      phase: effectivePhase,
      /** Aligné sur ``effectivePhase`` : avant on passait la phase brute (command/deployment) ici
       * alors que ``phase`` était déjà mappée en ``move`` → ``interactionPhase === "move"`` était faux,
       * pas de couche disques, et ``drawGroup(availableCells)`` avec toute l’empreinte = nid d’abeille. */
      interactionPhase: effectivePhase,
      showDeploymentZones: phase === "deployment",
      selectedUnitId,
      mode,
      showHexCoordinates,
      objectiveControl,
      currentLevel,
      occupiedFloorLevels,
      moveDestPoolRef:
        mode === "squadModelMove"
          ? // Fig active → pool BFS de la fig ; sinon (post-pose/repos) → union des figs non posées.
            squadMovePlan?.activeModelId && squadMoveModelPoolRef
            ? squadMoveModelPoolRef
            : squadUnplacedUnionPoolRef
          : resolvedMoveDestPoolRef,
      footprintZonePoolRef: footprintZoneRef,
      moveDestinationAnchorsFromState,
      movePreviewFootprintSpanFromState: (
        gameState as { move_preview_footprint_span?: number | null }
      ).move_preview_footprint_span,
      movePreviewFootprintMaskLoops: activeFootprintMaskLoops,
      chargeModelMaskLoops,
      pendingMoveAfterShooting,
      chargeDestPoolRef:
        perModelChargeLike && activeChargeLikePoolRef ? activeChargeLikePoolRef : chargeDestPoolRef,
      selectedUnitBaseSize: unitForFootprintBase
        ? resolveBaseSizeForUnitDisplay(unitForFootprintBase)
        : undefined,
      // Ancre de l'unité sélectionnée (col, row) — utilisée par drawBoard pour
      // centrer la preview move / advance / post-shoot en **cercle euclidien**
      // (spec : rayon = M×10 + demi-empreinte, masqué par le BFS). On priorise
      // l'unité en mouvement (unitForMoveFootprint) pour rester aligné sur la
      // post-shoot move, sinon on retombe sur la sélection courante.
      selectedUnitAnchor: unitForFootprintBase
        ? { col: unitForFootprintBase.col, row: unitForFootprintBase.row }
        : null,
      cachedStaticBoard: canReuseStatic ? staticBoardRef.current : null,
      cachedWalls: canReuseStatic ? staticWallsRef.current : null,
      losDebugShowRatio: showLosDebugOverlay && phase === "shoot" && shootingPreviewSource !== null,
      losDebugRatioByHex: Object.fromEntries(losVisibilityRatioByHex),
      chargeEngagementHalo,
      fightEngagementRing,
      fightEngagementZone,
    };

    const partialFp = computeDrawBoardPartialRedrawFingerprint(
      app,
      boardConfigWithOverrides as Parameters<typeof drawBoard>[1],
      drawBoardOptions
    );
    const fingerprintMatchStructural =
      partialFp.structuralKey === lastHighlightsStructuralKeyRef.current;
    const fingerprintMatchMove =
      (partialFp.movePolygonCacheKey ?? "") === (lastMovePolygonCacheKeyRef.current ?? "");

    const canReuseExistingHighlightsThroughDestroy =
      highlightsLayerRef.current != null &&
      !highlightsLayerRef.current.destroyed &&
      highlightsLayerRef.current.parent === app.stage &&
      fingerprintMatchStructural &&
      (fingerprintMatchMove || partialFp.movePolygonCacheKey !== null);

    let savedHighlightsThroughDestroy: PIXI.Container | null = null;

    if (app.stage) {
      // Detach persistent containers before removeChildren so they survive.
      const savedStatic = staticBoardRef.current;
      const savedWalls = staticWallsRef.current;
      const savedUi = uiElementsContainerRef.current;
      const savedDragOverlay = dragOverlayRef.current;
      const savedUnitsLayer = unitsLayerRef.current;
      const savedMovePreviewGhost = movePreviewGhostLayerRef.current;
      const savedBlinks: PIXI.DisplayObject[] = [];
      // Move-preview LoS / icône / ligne / règle : même principe que hp-blink — sinon chaque re-run du
      // useEffect détruit le stage et la preview (ou la ligne mesure) disparaît + les refs sont perdues.
      const savedHoverOverlay = hoverOverlayRef.current;
      const savedHoverSprite = hoverSpriteRef.current;
      const savedVeilOverlay = squadMoveVeilOverlayRef.current;
      const savedMovePreviewGuideLine = movePreviewGuideLineRef.current;
      const savedMeasureGuideLine = measureGuideLineRef.current;
      const savedManualAllocOverlay = manualAllocOverlayRef.current;
      const savedChargeVeilOverlay = chargeModelVeilOverlayRef.current;
      const savedBlinkRingOverlay = blinkTargetRingOverlayRef.current;
      const savedShootOverlay = shootSubgroupOverlayRef.current;
      if (savedStatic?.parent) app.stage.removeChild(savedStatic);
      if (savedWalls?.parent) app.stage.removeChild(savedWalls);
      if (savedUi?.parent) app.stage.removeChild(savedUi);
      if (savedDragOverlay?.parent) app.stage.removeChild(savedDragOverlay);
      if (savedUnitsLayer?.parent) app.stage.removeChild(savedUnitsLayer);
      if (savedMovePreviewGhost?.parent) app.stage.removeChild(savedMovePreviewGhost);
      if (savedHoverOverlay?.parent) app.stage.removeChild(savedHoverOverlay);
      if (savedHoverSprite?.parent) app.stage.removeChild(savedHoverSprite);
      if (savedVeilOverlay?.parent) app.stage.removeChild(savedVeilOverlay);
      if (savedMovePreviewGuideLine?.parent) app.stage.removeChild(savedMovePreviewGuideLine);
      if (savedMeasureGuideLine?.parent) app.stage.removeChild(savedMeasureGuideLine);
      if (savedManualAllocOverlay?.parent) app.stage.removeChild(savedManualAllocOverlay);
      if (savedChargeVeilOverlay?.parent) app.stage.removeChild(savedChargeVeilOverlay);
      if (savedBlinkRingOverlay?.parent) app.stage.removeChild(savedBlinkRingOverlay);
      if (savedShootOverlay?.parent) app.stage.removeChild(savedShootOverlay);
      if (
        canReuseExistingHighlightsThroughDestroy &&
        highlightsLayerRef.current?.parent === app.stage
      ) {
        savedHighlightsThroughDestroy = highlightsLayerRef.current;
        app.stage.removeChild(savedHighlightsThroughDestroy);
      } else {
        detachMovePreviewLayerCacheFromStage();
      }
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
        if (child === savedHighlightsThroughDestroy) continue;
        if (child.destroy) {
          child.destroy({ children: true, texture: false, baseTexture: false });
        }
      }

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
      if (savedHighlightsThroughDestroy) app.stage.addChild(savedHighlightsThroughDestroy);
      if (savedUi) {
        // Indicateurs persistants (logos d'action, badges hidden/move-status/battle-shock) :
        // masqués d'un bloc quand hideIndicators (UnitRenderer saute déjà le redraw, ceci cache les restes).
        savedUi.visible = !hideIndicators;
        app.stage.addChild(savedUi);
      }
      const unitsCacheForBlinkSweep = gameState?.units_cache as Record<string, unknown> | undefined;
      const blinksToReattach = destroyAndFilterOrphanHpBlinkContainers(
        savedBlinks,
        unitsCacheForBlinkSweep
      );
      for (const blink of blinksToReattach) {
        blink.visible = !hideIndicators;
        app.stage.addChild(blink);
      }
      if (savedUnitsLayer) app.stage.addChild(savedUnitsLayer);
      if (savedMovePreviewGhost) app.stage.addChild(savedMovePreviewGhost);
      if (savedDragOverlay) app.stage.addChild(savedDragOverlay);
      if (savedHoverOverlay && !savedHoverOverlay.destroyed) app.stage.addChild(savedHoverOverlay);
      if (savedHoverSprite && !savedHoverSprite.destroyed) app.stage.addChild(savedHoverSprite);
      if (savedVeilOverlay && !savedVeilOverlay.destroyed) app.stage.addChild(savedVeilOverlay);
      if (savedMovePreviewGuideLine && !savedMovePreviewGuideLine.destroyed) {
        app.stage.addChild(savedMovePreviewGuideLine);
      }
      if (savedMeasureGuideLine && !savedMeasureGuideLine.destroyed) {
        savedMeasureGuideLine.zIndex = MEASURE_GUIDE_LINE_Z_INDEX;
        app.stage.addChild(savedMeasureGuideLine);
      }
      if (savedManualAllocOverlay && !savedManualAllocOverlay.destroyed) {
        savedManualAllocOverlay.zIndex = 2700;
        app.stage.addChild(savedManualAllocOverlay);
      }
      if (savedChargeVeilOverlay && !savedChargeVeilOverlay.destroyed) {
        savedChargeVeilOverlay.zIndex = 2700;
        app.stage.addChild(savedChargeVeilOverlay);
      }
      if (savedBlinkRingOverlay && !savedBlinkRingOverlay.destroyed) {
        savedBlinkRingOverlay.zIndex = 2700;
        app.stage.addChild(savedBlinkRingOverlay);
      }
      if (savedShootOverlay && !savedShootOverlay.destroyed) {
        savedShootOverlay.zIndex = 2705;
        app.stage.addChild(savedShootOverlay);
      }

      // Nettoyer pastilles cible / jet de charge seulement quand on reconstruit les unités.
      // Sinon le badge 2D6 est supprimé ici puis jamais redessiné (unitsChanged false).
      if (savedUi && unitsChanged) {
        const staleTargetMarkers = savedUi.children.filter(
          (child: PIXI.DisplayObject) =>
            typeof child.name === "string" &&
            (child.name.startsWith("target-indicator-") ||
              child.name.startsWith("charge-badge-") ||
              child.name.startsWith("hidden-badge-") ||
              child.name.startsWith("fled-badge-") ||
              child.name.startsWith("move-status-") ||
              child.name.startsWith("battle-shocked-"))
        );
        staleTargetMarkers.forEach((child: PIXI.DisplayObject) => {
          savedUi.removeChild(child);
          if ("destroy" in child && typeof child.destroy === "function") {
            child.destroy();
          }
        });
      }
    }

    let drawResult: ReturnType<typeof drawBoard>;
    if (canReuseExistingHighlightsThroughDestroy && savedHighlightsThroughDestroy) {
      const onlyPatchMovePolygon =
        partialFp.movePolygonCacheKey !== null &&
        (partialFp.movePolygonCacheKey ?? "") !== (lastMovePolygonCacheKeyRef.current ?? "");
      if (onlyPatchMovePolygon) {
        updateMovePreviewPolygonLayerInHighlightContainer(
          app,
          boardConfigWithOverrides as Parameters<typeof drawBoard>[1],
          savedHighlightsThroughDestroy,
          drawBoardOptions
        );
        lastMovePolygonCacheKeyRef.current = partialFp.movePolygonCacheKey ?? "";
      }
      highlightsLayerRef.current = savedHighlightsThroughDestroy;
    } else {
      drawResult = drawBoard(
        app,
        boardConfigWithOverrides as Parameters<typeof drawBoard>[1],
        drawBoardOptions
      );
      if (drawResult) {
        lastHighlightsStructuralKeyRef.current = partialFp.structuralKey;
        lastMovePolygonCacheKeyRef.current = partialFp.movePolygonCacheKey ?? "";
        highlightsLayerRef.current = drawResult.highlightContainer;
      }
    }

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
    // Above board highlights + full-screen hex hitArea (zIndex 0): unit clicks must win so
    // chargePreview can select blinking enemies (their hex is rarely in clickableSet). Empty
    // pixels still fall through to the hitArea below. Below drag overlay (9000) and ui (10000).
    unitsLayerRef.current.zIndex = 2000;
    if (!unitsLayerRef.current.parent) {
      app.stage.addChild(unitsLayerRef.current);
    }
    const unitsLayer = unitsLayerRef.current;

    // ✅ Layer dédié au ghost de destination du move preview (collé à la souris).
    // zIndex 25000 → au-dessus des barres HP (hp-blink 20000) et des logos (ui 10000) des
    // autres unités, pour que le ghost ne soit jamais masqué quand il chevauche une unité.
    if (!movePreviewGhostLayerRef.current) {
      movePreviewGhostLayerRef.current = new PIXI.Container();
      movePreviewGhostLayerRef.current.name = "move-preview-ghost-layer";
      movePreviewGhostLayerRef.current.sortableChildren = true;
    }
    movePreviewGhostLayerRef.current.zIndex = 25000;
    if (!movePreviewGhostLayerRef.current.parent) {
      app.stage.addChild(movePreviewGhostLayerRef.current);
    }
    // Vider UNIQUEMENT quand on reconstruit les unités (unitsChanged) : le redraw du ghost est dans
    // la boucle gardée par `if (unitsChanged)`. Vider à chaque render (même sans rebuild) laisse le
    // layer vide sur les renders où unitsChanged=false → le ghost disparaît/réapparaît = clignotement.
    if (unitsChanged) movePreviewGhostLayerRef.current.removeChildren();
    const movePreviewGhostLayer = movePreviewGhostLayerRef.current;

    const chargeMaxDistance = gameConfig?.charge?.charge_max_distance;

    // Wrapper qui enregistre le timestamp d'entrée en squadModelMove avant de confirmer le move.
    // Utilisé pour ignorer le select-click qui suit immédiatement la confirmation du movePreview.
    const onConfirmMoveForRender = () => {
      squadMoveEntryTimeRef.current = performance.now();
      onConfirmMove();
    };

    // Tir par-arme : couleur = arme (profils d'une même combi → couleur partagée).
    // weaponColorsByTarget : pour chaque escouade cible, les couleurs distinctes des armes qui
    // la visent → voile splitté. Au-delà de la palette : blanc.
    const VEIL_WHITE = 0xffffff;
    const weaponColorsByTarget = new Map<string, number[]>();
    if (mode === "squadModelShoot" && squadShootPlan) {
      const shooterUnit = units.find((u) => String(u.id) === String(squadShootPlan.unitId));
      const shooterRngWeapons = shooterUnit?.RNG_WEAPONS;
      const seenColorPerTarget = new Map<string, Set<number>>();
      for (const decl of squadShootPlan.declarations) {
        const key = String(decl.target_unit_id);
        const color = weaponColorFor(shooterRngWeapons, decl.weapon_index);
        let seen = seenColorPerTarget.get(key);
        if (!seen) {
          seen = new Set<number>();
          seenColorPerTarget.set(key, seen);
          weaponColorsByTarget.set(key, []);
        }
        if (!seen.has(color)) {
          seen.add(color);
          weaponColorsByTarget.get(key)!.push(color);
        }
      }
    }
    /** Dessine un voile : 1 couleur = disque plein ; N couleurs = N secteurs ; >6 = blanc. */
    const drawSplitVeil = (
      g: PIXI.Graphics,
      cx: number,
      cy: number,
      radius: number,
      colors: number[],
      alpha: number
    ): void => {
      if (colors.length === 0) return;
      if (colors.length > WEAPON_COLOR_PALETTE.length) {
        g.beginFill(VEIL_WHITE, alpha);
        g.drawCircle(cx, cy, radius);
        g.endFill();
        return;
      }
      if (colors.length === 1) {
        g.beginFill(colors[0]!, alpha);
        g.drawCircle(cx, cy, radius);
        g.endFill();
        return;
      }
      const step = (Math.PI * 2) / colors.length;
      colors.forEach((col, i) => {
        g.beginFill(col, alpha);
        g.moveTo(cx, cy);
        g.arc(cx, cy, radius, i * step, (i + 1) * step);
        g.lineTo(cx, cy);
        g.endFill();
      });
    };

    // ✅ UNIFIED UNIT RENDERING USING COMPONENT — skip if fingerprint unchanged
    if (unitsChanged) {
      unitsFingerprintRef.current = unitsFingerprint;
      for (const unitRow of units) {
        const unitsCache = gameState?.units_cache as Record<string, unknown> | undefined;
        const unit = mergeUnitHpFromCache(unitRow, unitsCache);
        const unitIdStr = String(unit.id);
        const isPresentInUnitsCache =
          unitsCache !== undefined ? Object.hasOwn(unitsCache, unitIdStr) : true;
        const isHazardousDeathGhost =
          enginePhaseForPools === "shoot" &&
          selectedUnitId === unit.id &&
          unitsCache !== undefined &&
          !isPresentInUnitsCache;

        // Dead units killed during shoot phase: keep visible as grey ghosts until phase transition.
        const isDeadGhost =
          !isPresentInUnitsCache &&
          !isHazardousDeathGhost &&
          enginePhaseForPools === "shoot" &&
          (unit.HP_CUR ?? 0) <= 0;

        // Déploiement par escouade : l'escouade en cours de placement n'est pas (encore) dans
        // units_cache. On la rend depuis le plan provisoire (deployPlanView) dès qu'elle est posée.
        const isDeployGhost =
          isDeploymentMove &&
          !!effectivePerModelPlan &&
          String(effectivePerModelPlan.unitId) === unitIdStr &&
          Object.keys(effectivePerModelPlan.models).length > 0;

        // units_cache is the single source of truth for living units.
        // Keep only the hazardous-death ghost and shoot-phase dead ghosts visible.
        if (!isPresentInUnitsCache && !isHazardousDeathGhost && !isDeadGhost && !isDeployGhost) {
          continue;
        }

        // Déploiement : une escouade non encore déployée a son ancre + toutes ses
        // figurines à la sentinelle (-1,-1). Sans ce garde, ses N figurines sont
        // dessinées empilées à l'origine (≈ 1 blob/escouade). On ne la rend QUE
        // si c'est l'escouade en cours de placement (deploy ghost).
        if (
          enginePhaseForPools === "deployment" &&
          (Number(unit.col) < 0 || Number(unit.row) < 0) &&
          !isDeployGhost
        ) {
          continue;
        }

        const cacheEntry = unitsCache?.[unitIdStr] as
          | {
              occupied_hexes_by_model?: Record<string, [number, number]>;
              models_meta_by_model?: Record<string, ModelVisualMeta>;
              models_hp_by_model?: Record<
                string,
                { HP_CUR: number; HP_MAX: number; is_character: boolean }
              >;
              level?: number;
              level_by_model?: Record<string, number>;
            }
          | undefined;
        const occupiedHexesByModel = cacheEntry?.occupied_hexes_by_model;
        const modelMetasByModel = cacheEntry?.models_meta_by_model;
        const modelHpsByModel = cacheEntry?.models_hp_by_model;
        // Niveau (étages) par figurine : source cache (level_by_model), fallback niveau d'ancre / unité.
        const levelByModel = cacheEntry?.level_by_model;
        const unitLevel = cacheEntry?.level ?? (unit as { level?: number }).level ?? 0;
        // squad.md brique 3 : pour l'escouade en mode plan, afficher les figs aux positions
        // PROVISOIRES (ghost) + flag de validite par fig (voile rouge sur les invalides).
        const isSquadGhost =
          isPerModelMove &&
          !!effectivePerModelPlan &&
          String(effectivePerModelPlan.unitId) === unitIdStr;
        let modelPositions: Array<[number, number]>;
        let modelValidFlags: boolean[];
        let modelIds: string[];
        if (isDeployGhost && !occupiedHexesByModel) {
          // Escouade en déploiement non présente dans units_cache : positions = plan provisoire.
          const entries = Object.entries(effectivePerModelPlan!.models);
          modelIds = entries.map(([mid]) => mid);
          modelPositions = entries.map(([, p]) => [p.col, p.row] as [number, number]);
          modelValidFlags = entries.map(
            ([mid]) => effectivePerModelPlan!.perModelValid[mid] !== false
          );
        } else if (occupiedHexesByModel) {
          const entries = Object.entries(occupiedHexesByModel) as Array<[string, [number, number]]>;
          modelIds = entries.map(([mid]) => mid);
          modelPositions = entries.map(([mid, pos]) => {
            const planPos =
              isSquadGhost || isDeployGhost ? effectivePerModelPlan!.models[mid] : undefined;
            return planPos ? ([planPos.col, planPos.row] as [number, number]) : pos;
          });
          modelValidFlags = entries.map(([mid]) =>
            isSquadGhost || isDeployGhost
              ? effectivePerModelPlan!.perModelValid[mid] !== false
              : true
          );
        } else {
          modelIds = [String(unit.id)];
          modelPositions = [[unit.col, unit.row]];
          modelValidFlags = [true];
        }

        const modelCenters: Array<[number, number]> = modelPositions.map(([mCol, mRow]) => [
          mCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN,
          mRow * HEX_VERT_SPACING + ((mCol % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN,
        ]);
        const modelMetas: Array<ModelVisualMeta | null> = modelMetasByModel
          ? modelIds.map((mid) => modelMetasByModel[mid] ?? null)
          : [];
        // Niveau d'étage par figurine (aligné sur modelCenters) → badge coloré.
        // Pendant un drag (move/déploiement preview) : niveau LIVE dérivé de la position provisoire
        // (étage courant si la fig est sur ce plancher, sinon sol) → mise à jour sans attendre le
        // commit. Hors preview : niveau committé (level_by_model, autoritaire).
        const isPreviewLevels = isSquadGhost || isDeployGhost;
        const unitBaseShape = (unit as { BASE_SHAPE?: "round" | "oval" | "square" }).BASE_SHAPE;
        const unitBaseSize = (unit as { BASE_SIZE?: number | [number, number] }).BASE_SIZE;
        const modelLevels: number[] = modelIds.map((mid, idx) => {
          if (isPreviewLevels) {
            // Niveau LIVE aligné sur le backend (resolve_model_floor_level) : niveau DEMANDÉ = celui
            // capturé au drop de la fig dans le plan (models[mid].level), fallback vue courante ;
            // effectif = ce niveau si l'empreinte ENTIÈRE tient sur son plancher (13.06), sinon sol.
            // Évite un badge de drag qui ment (montre 1) puis disparaît au commit (réel 0).
            const planLevel = (
              effectivePerModelPlan?.models[mid] as { level?: number } | undefined
            )?.level;
            const reqLevel = planLevel ?? currentLevel;
            const reqFloorSet = reqLevel >= 1 ? floorHexKeysByLevel.get(reqLevel) : undefined;
            if (reqLevel >= 1 && reqFloorSet) {
              const [pc, pr] = modelPositions[idx];
              const meta = modelMetas[idx];
              const fpKeys = unitFootprintHexKeys({
                col: pc,
                row: pr,
                BASE_SHAPE: meta?.BASE_SHAPE ?? unitBaseShape,
                BASE_SIZE: meta?.BASE_SIZE ?? unitBaseSize,
              });
              let allOnFloor = fpKeys.size > 0;
              for (const k of fpKeys) {
                if (!reqFloorSet.has(k)) {
                  allOnFloor = false;
                  break;
                }
              }
              if (allOnFloor) return reqLevel;
            }
            return 0;
          }
          return levelByModel?.[mid] ?? unitLevel;
        });
        // Vue mono-niveau : une fig est ghostée UNIQUEMENT si (a) elle n'est pas au niveau affiché ET
        // (b) son empreinte chevauche au moins un plancher (fig liée à une structure à étages). Une fig
        // en terrain découvert reste affichée normalement quel que soit l'étage sélectionné.
        const modelLevelGhost: boolean[] = modelLevels.map((lv, idx) => {
          if (lv === currentLevel) return false;
          if (allFloorHexKeys.size === 0) return false;
          const [pc, pr] = modelPositions[idx];
          const meta = modelMetas[idx];
          const fpKeys = unitFootprintHexKeys({
            col: pc,
            row: pr,
            BASE_SHAPE: meta?.BASE_SHAPE ?? unitBaseShape,
            BASE_SIZE: meta?.BASE_SIZE ?? unitBaseSize,
          });
          for (const k of fpKeys) if (allFloorHexKeys.has(k)) return true;
          return false;
        });
        const modelHps: Array<{ HP_CUR: number; HP_MAX: number; is_character: boolean } | null> =
          modelHpsByModel ? modelIds.map((mid) => modelHpsByModel[mid] ?? null) : [];
        // Rule 13.09 : flag "caché" par figurine (aligné sur modelCenters) pour le mode badge par-fig.
        const hiddenModelIds = new Set((unit.hidden_models ?? []).map((m) => String(m)));
        // En plan fig-par-fig (squadModelMove), le statut "caché" est recalculé par le backend pour
        // les positions provisoires (movePreviewHiddenModelIds) ; sinon le badge resterait figé sur la
        // position actuelle (unit.hidden_models) et n'apparaîtrait jamais au survol.
        const modelHidden: boolean[] =
          (isSquadGhost && mode === "squadModelMove") || (isDeployGhost && isDeploymentMove)
            ? modelIds.map((mid) => movePreviewHiddenModelIds.has(String(mid)))
            : modelIds.map((mid) => hiddenModelIds.has(String(mid)));
        // Ghost par-figurine : la fig en cours de placement (active) est rendue atténuée
        // à sa position d'origine pendant le move/déploiement par figurine.
        const modelGhost: boolean[] =
          (isSquadGhost || isDeployGhost) && effectivePerModelPlan?.activeModelId
            ? modelIds.map((mid) => mid === effectivePerModelPlan.activeModelId)
            : [];
        const [anchorCenterX, anchorCenterY] = modelCenters[0];

        // Skip units that are being previewed elsewhere
        if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) continue;

        // Unified: movePreview and shoot phase use same code path for greying non-targetable enemies
        const hasAuthoritativeShootTargets =
          effectiveShootTargetsSet !== null &&
          effectiveShootTargetsSet.size > 0 &&
          ((enginePhaseForPools === "shoot" && selectedUnitId !== null) ||
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
        const isEligibleForRenderingBase = (() => {
          // gameState.phase is authoritative (prop `phase` can lag one frame after API response).
          if (
            enginePhaseForPools === "shoot" &&
            shootingActivationQueue &&
            shootingActivationQueue.length > 0
          ) {
            // During active shooting: unit is eligible if in queue OR is active unit
            const inQueue = shootingActivationQueue.some(
              (u: Unit) => String(u.id) === String(unit.id)
            );
            const isActive =
              activeShootingUnit && String(activeShootingUnit.id) === String(unit.id);
            const result = inQueue || isActive;

            return result;
          }
          if (enginePhaseForPools === "fight") {
            if (!gameState) {
              throw new Error("Missing gameState during fight eligibility calculation");
            }
            const currentFightSubPhase = gameState.fight_subphase;
            if (!currentFightSubPhase) {
              // Engine sets fight_subphase to null when all fight pools are empty until advance_phase
              // completes (fight_handlers._update_fight_subphase). useEngineAPI auto-advances after 100ms,
              // but we still render in between — fall back to standard eligibility instead of crashing.
              return eligibleUnitIds.includes(
                typeof unit.id === "number" ? unit.id : parseInt(unit.id as string, 10)
              );
            }
            // V11 : pool actionnable unique exposé par le moteur (pile_in/fight/consolidate).
            const fightPool: Array<number | string> = gameState.fight_eligible_units ?? [];
            return fightPool.some((id) => String(id) === String(unit.id));
          }
          // All other phases: use standard eligibility
          return eligibleUnitIds.includes(
            typeof unit.id === "number" ? unit.id : parseInt(unit.id as string, 10)
          );
        })();

        // Fight : pas de cercle vert « éligible » sur l'unité active tant qu'on n'est pas en choix de cible
        // (après pile in le cas échéant) — évite l'anneau 1″ avant le pile in.
        const suppressFightActiveEligibleGreen =
          enginePhaseForPools === "fight" &&
          selectedUnitId !== null &&
          String(unit.id) === String(selectedUnitId) &&
          mode !== "attackPreview";
        const isEligibleForRendering =
          isEligibleForRenderingBase && !suppressFightActiveEligibleGreen;

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
          (enginePhaseForPools === "shoot" || mode === "movePreview") &&
          hasAuthoritativeShootTargets &&
          unit.player !== current_player &&
          effectiveShootTargetsSet !== null &&
          !effectiveShootTargetsSet.has(String(unit.id));

        const unitToRender = isDeadGhost
          ? ({ ...unit, isJustKilled: true } as Unit & { isJustKilled: boolean })
          : isChargeOrigin || isMoveOriginGhost || isHazardousDeathGhost || isShootingPreviewGhost
            ? ({
                ...unit,
                isGhost: true,
                // Pendant un move preview, le badge "caché" n'a de sens qu'à la destination (rendu
                // par le bloc preview) : on l'éteint sur le ghost d'origine pour éviter le conflit
                // de nommage PIXI (même `hidden-badge-${id}`) qui faisait clignoter le badge.
                ...(isMoveOriginGhost ? { hidden: false } : {}),
              } as Unit & { isGhost: boolean })
            : isSquadGhost
              ? // Plan fig-par-fig : en mode badge "escouade" (statusBadgePerModel off), renderHiddenBadge
                // lit unit.hidden → le recalculer depuis le hidden des positions PROVISOIRES du plan,
                // cohérent avec le badge par-fig (modelHidden).
                ({
                  ...unit,
                  hidden: modelHidden.length > 0 && modelHidden.every(Boolean),
                } as Unit)
              : unit;

        // Badge "fui" en preview : l'unité dont le move en cours est un Fall Back (état stable
        // fleePreviewUnitId, découplé de squadMovePlan qui churne) → on l'injecte dans unitsFled
        // pour TOUS ses rendus (ghost ou non), même si units_fled backend n'est peuplé qu'au commit.
        const unitsFledForRender =
          fleePreviewUnitId != null &&
          Number(fleePreviewUnitId) === Number(unit.id) &&
          !unitsFled?.includes(Number(unit.id))
            ? [...(unitsFled ?? []), Number(unit.id)]
            : unitsFled;

        renderUnit({
          hideIndicators,
          unit: unitToRender,
          centerX: anchorCenterX,
          centerY: anchorCenterY,
          modelCenters,
          modelMetas,
          modelHps,
          modelLevels,
          modelLevelGhost,
          modelHidden: isMoveOriginGhost ? [] : modelHidden,
          modelGhost,
          hpBarPerModel,
          hpBarBlinkEnlarged,
          showWoundProbability,
          statusBadgePerModel,
          app,
          renderTarget: unitsLayer,
          uiElementsContainer: uiElementsContainerRef.current!,
          useOverlayIcons: true,
          isPreview: false,
          isEligible: isMoveOriginGhost ? false : isEligibleForRendering || false,
          isShootable,
          displayOrientationStep: orientationStepForBoard(unit, gameState?.units_cache),
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
          unitsFled: unitsFledForRender,
          unitsAdvanced: gameState?.unitsAdvanced || [],
          fightSubPhase,
          fightActivePlayer,
          gameState,
          units,
          chargeTargets,
          fightTargets,
          targetPreview,
          onConfirmMove: onConfirmMoveForRender,
          parseColor,
          onUnitIconHoverChange: handleUnitIconHoverChange,
          onUnitDisplaySelect: (unitId: UnitId) => onUnitDisplaySelectChange?.(unitId),
          // Pass blinking state (unified: movePreview and attackPreview use same code path)
          blinkingUnits: effectiveBlinkingUnits,
          blinkingAttackerId: effectiveBlinkingAttackerId,
          isBlinkingActive,
          blinkVersion,
          shootingTargetInCover: coverTargets.has(String(unit.id)),
          movePreviewShootingTargetInCoverByUnitId: (() => {
            if (
              phase === "move" &&
              (mode === "select" || mode === "movePreview" || mode === "squadModelMove")
            ) {
              return movePreviewLosCoverById;
            }
            if (
              phase === "shoot" &&
              (mode === "select" ||
                mode === "attackPreview" ||
                mode === "movePreview" ||
                mode === "squadModelShoot") &&
              blinkingCoverByUnitId !== undefined
            ) {
              return blinkingCoverByUnitId;
            }
            return undefined;
          })(),
          movePreviewHiddenTooFarByUnitId: (() => {
            if (
              phase === "move" &&
              (mode === "select" || mode === "movePreview" || mode === "squadModelMove")
            ) {
              return movePreviewLosTooFarById;
            }
            if (
              phase === "shoot" &&
              (mode === "select" ||
                mode === "attackPreview" ||
                mode === "movePreview" ||
                mode === "squadModelShoot") &&
              blinkingHiddenTooFarByUnitId !== undefined
            ) {
              return blinkingHiddenTooFarByUnitId;
            }
            return undefined;
          })(),
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
          // V11 multi-cibles : voile violet sur les cibles toggleées (mode chargeTargetSelect)
          chargePreviewTargetIds,
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
            if (enginePhaseForPools !== "shoot") return false;
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
          onBlinkProbHtml: handleBlinkProbHtml,
          debugMode: showHexCoordinates,
          chargeMaxDistance,
        });

        // squad.md brique 3 : voile rouge sur les figs invalides (hex interdit OU hors cohesion).
        // Pendant le preview move (fig active en cours), ce voile backend (dry-run, figé) est masqué :
        // drawHoverVeil recalcule la cohésion EN TEMPS RÉEL au survol et fait foi.
        const suppressBackendVeil =
          mode === "squadModelMove" && !!effectivePerModelPlan?.activeModelId;
        if (isSquadGhost && !suppressBackendVeil && modelValidFlags.some((ok) => !ok)) {
          const veil = new PIXI.Graphics();
          const veilDisplayBase = resolveBaseSizeForUnitDisplay(unit);
          const veilRadius =
            veilDisplayBase > 1
              ? (veilDisplayBase * 1.5 * HEX_RADIUS) / 2
              : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;
          modelCenters.forEach(([cx, cy], i) => {
            if (!modelValidFlags[i]) {
              veil.beginFill(0xff0000, 0.45);
              veil.drawCircle(cx, cy, veilRadius);
              veil.endFill();
            }
          });
          veil.zIndex = 3000;
          unitsLayer.addChild(veil);
        }

        // Tir par-arme : voile (splitté par arme) sur les figs tireuses + lignes colorées par arme.
        if (
          mode === "squadModelShoot" &&
          squadShootPlan &&
          String(squadShootPlan.unitId) === unitIdStr
        ) {
          const decls = squadShootPlan.declarations;
          const gvBase = resolveBaseSizeForUnitDisplay(unit);
          const gvRadius =
            gvBase > 1 ? (gvBase * 1.5 * HEX_RADIUS) / 2 : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;

          // Voile tireur : couleurs des armes que CHAQUE fig a assignées (split si plusieurs).
          const veil = new PIXI.Graphics();
          modelCenters.forEach(([cx, cy], i) => {
            const mid = String(modelIds[i]);
            const seen = new Set<number>();
            const colors: number[] = [];
            for (const d of decls) {
              if (String(d.model_id) !== mid) continue;
              const color = weaponColorFor(unit.RNG_WEAPONS, d.weapon_index);
              if (seen.has(color)) continue;
              seen.add(color);
              colors.push(color);
            }
            drawSplitVeil(veil, cx, cy, gvRadius, colors, 0.5);
          });
          veil.zIndex = 3000;
          unitsLayer.addChild(veil);

          // Lignes de visée : 1 par intent (fig → fig cible la plus proche), couleur de l'arme.
          const shootLines = new PIXI.Graphics();
          const shootUc = gameState?.units_cache as
            | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
            | undefined;
          const centerByModel = new Map<string, [number, number]>();
          const posByModel = new Map<string, [number, number]>();
          modelCenters.forEach(([cx, cy], i) => {
            centerByModel.set(String(modelIds[i]), [cx, cy]);
            posByModel.set(String(modelIds[i]), modelPositions[i]);
          });
          for (const d of decls) {
            const origin = centerByModel.get(String(d.model_id));
            const ownPos = posByModel.get(String(d.model_id));
            if (!origin || !ownPos) continue;
            const tgtByModel = shootUc?.[String(d.target_unit_id)]?.occupied_hexes_by_model;
            if (!tgtByModel) continue;
            const ownCube = offsetToCube(ownPos[0], ownPos[1]);
            let nearest: [number, number] | null = null;
            let bestD = Infinity;
            for (const pos of Object.values(tgtByModel)) {
              const dd = cubeDistance(ownCube, offsetToCube(pos[0], pos[1]));
              if (dd < bestD) {
                bestD = dd;
                nearest = pos;
              }
            }
            if (!nearest) continue;
            const tx = nearest[0] * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
            const ty =
              nearest[1] * HEX_VERT_SPACING +
              ((nearest[0] % 2) * HEX_VERT_SPACING) / 2 +
              HEX_HEIGHT / 2 +
              MARGIN;
            const color = weaponColorFor(unit.RNG_WEAPONS, d.weapon_index);
            shootLines.lineStyle(3, color, 0.9);
            shootLines.moveTo(origin[0], origin[1]);
            shootLines.lineTo(tx, ty);
          }
          shootLines.zIndex = 3001;
          unitsLayer.addChild(shootLines);
        }

        // Combat par-figurine : voile VERT sur les figs attribuées + lignes vertes vers la cible.
        if (phase === "fight" && squadFightPlan && String(squadFightPlan.unitId) === unitIdStr) {
          const decls = squadFightPlan.declarations;
          const FIGHT_GREEN = 0x22c55e;
          const fvBase = resolveBaseSizeForUnitDisplay(unit);
          const fvRadius =
            fvBase > 1 ? (fvBase * 1.5 * HEX_RADIUS) / 2 : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;
          const assignedMids = new Set(decls.map((d) => String(d.model_id)));
          // Voile : vert = fig attribuée ; gris = fig non engagée (non sélectionnable, 04.02).
          const veil = new PIXI.Graphics();
          modelCenters.forEach(([cx, cy], i) => {
            const mid = String(modelIds[i]);
            if (assignedMids.has(mid)) {
              veil.beginFill(FIGHT_GREEN, 0.5);
              veil.drawCircle(cx, cy, fvRadius);
              veil.endFill();
            } else if (!fightEngagedModelIds.has(mid)) {
              veil.beginFill(0x111827, 0.5); // gris foncé : figurine non engagée (non éligible)
              veil.drawCircle(cx, cy, fvRadius);
              veil.endFill();
            }
          });
          veil.zIndex = 3000;
          unitsLayer.addChild(veil);

          // Lignes vertes : fig attribuée → fig cible la plus proche.
          const fightLines = new PIXI.Graphics();
          const fightUc = gameState?.units_cache as
            | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
            | undefined;
          const centerByModel = new Map<string, [number, number]>();
          const posByModel = new Map<string, [number, number]>();
          modelCenters.forEach(([cx, cy], i) => {
            centerByModel.set(String(modelIds[i]), [cx, cy]);
            posByModel.set(String(modelIds[i]), modelPositions[i]);
          });
          for (const d of decls) {
            const origin = centerByModel.get(String(d.model_id));
            const ownPos = posByModel.get(String(d.model_id));
            if (!origin || !ownPos) continue;
            const tgtByModel = fightUc?.[String(d.target_unit_id)]?.occupied_hexes_by_model;
            if (!tgtByModel) continue;
            const ownCube = offsetToCube(ownPos[0], ownPos[1]);
            let nearest: [number, number] | null = null;
            let bestD = Infinity;
            for (const pos of Object.values(tgtByModel)) {
              const dd = cubeDistance(ownCube, offsetToCube(pos[0], pos[1]));
              if (dd < bestD) {
                bestD = dd;
                nearest = pos;
              }
            }
            if (!nearest) continue;
            const tx = nearest[0] * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
            const ty =
              nearest[1] * HEX_VERT_SPACING +
              ((nearest[0] % 2) * HEX_VERT_SPACING) / 2 +
              HEX_HEIGHT / 2 +
              MARGIN;
            fightLines.lineStyle(3, FIGHT_GREEN, 0.9);
            fightLines.moveTo(origin[0], origin[1]);
            fightLines.lineTo(tx, ty);
          }
          fightLines.zIndex = 3001;
          unitsLayer.addChild(fightLines);
        }

        // Voile par arme sur les unités cibles (couleurs des armes qui les visent, splitté).
        const tgtColors = weaponColorsByTarget.get(unitIdStr);
        if (tgtColors && tgtColors.length > 0 && modelCenters.length > 0) {
          const tgtVeil = new PIXI.Graphics();
          const tvBase = resolveBaseSizeForUnitDisplay(unit);
          const tvRadius =
            tvBase > 1 ? (tvBase * 1.5 * HEX_RADIUS) / 2 : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;
          modelCenters.forEach(([cx, cy]) => {
            drawSplitVeil(tgtVeil, cx, cy, tvRadius, tgtColors, 0.4);
          });
          tgtVeil.zIndex = 3000;
          unitsLayer.addChild(tgtVeil);
        }
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

          // Multi-fig squad ghost: rigid-body translation in PIXEL space.
          // Hex-coord delta would corrupt vertical positioning whenever the
          // delta col flips column parity (odd-column half-hex offset).
          const previewUnitsCache = gameState?.units_cache as Record<string, unknown> | undefined;
          const previewCacheEntry = previewUnitsCache?.[String(previewUnit.id)] as
            | {
                col?: number;
                row?: number;
                occupied_hexes_by_model?: Record<string, [number, number]>;
                models_meta_by_model?: Record<string, ModelVisualMeta>;
              }
            | undefined;
          const previewOccupied = previewCacheEntry?.occupied_hexes_by_model;
          const previewMetasByModel = previewCacheEntry?.models_meta_by_model;
          const previewModelPositions: Array<[number, number]> = previewOccupied
            ? (Object.values(previewOccupied) as Array<[number, number]>)
            : [[previewUnit.col, previewUnit.row]];
          // Metas alignées sur previewModelPositions (même ordre de clés que occupied_hexes_by_model).
          const previewModelMetas: Array<ModelVisualMeta | null> =
            previewOccupied && previewMetasByModel
              ? Object.keys(previewOccupied).map((mid) => previewMetasByModel[mid] ?? null)
              : [];
          const anchorPixelX = previewUnit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const anchorPixelY =
            previewUnit.row * HEX_VERT_SPACING +
            ((previewUnit.col % 2) * HEX_VERT_SPACING) / 2 +
            HEX_HEIGHT / 2 +
            MARGIN;
          const pixelDeltaX = centerX - anchorPixelX;
          const pixelDeltaY = centerY - anchorPixelY;
          const previewModelCenters: Array<[number, number]> = previewModelPositions.map(
            ([mCol, mRow]) => {
              const mPixelX = mCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
              const mPixelY =
                mRow * HEX_VERT_SPACING +
                ((mCol % 2) * HEX_VERT_SPACING) / 2 +
                HEX_HEIGHT / 2 +
                MARGIN;
              return [mPixelX + pixelDeltaX, mPixelY + pixelDeltaY];
            }
          );

          // Rule 13.09 : statut "caché" À LA DESTINATION = calculé par le BACKEND
          // (movePreviewHiddenModelIds, alimenté par preview_hidden_from_position → même fonction
          // compute_unit_hidden_models qu'au drop). Source unique : identique au statut après pose,
          // pour toute forme de base. Aligné par model_id (même ordre que occupied_hexes_by_model).
          const previewModelIds = previewOccupied
            ? Object.keys(previewOccupied)
            : [String(previewUnit.id)];
          const previewModelHidden: boolean[] = previewModelIds.map((mid) =>
            movePreviewHiddenModelIds.has(String(mid))
          );
          const previewHiddenSquad =
            previewModelHidden.length > 0 && previewModelHidden.every(Boolean);

          // Niveau d'étage LIVE du ghost de destination (bug #2) : translation hex rigide de chaque
          // fig vers la destination, puis empreinte ENTIÈRE sur le plancher courant (aligné backend /
          // dérivation #1). Commit autoritaire. Sans ces flags, le fantôme collé à la souris n'avait
          // jamais de badge d'étage ni d'atténuation mono-niveau.
          const previewFloorSet =
            currentLevel >= 1 ? floorHexKeysByLevel.get(currentLevel) : undefined;
          const previewDeltaCol = movePreview.destCol - previewUnit.col;
          const previewDeltaRow = movePreview.destRow - previewUnit.row;
          const previewUnitBaseShape = (
            previewUnit as { BASE_SHAPE?: "round" | "oval" | "square" }
          ).BASE_SHAPE;
          const previewUnitBaseSize = (previewUnit as { BASE_SIZE?: number | [number, number] })
            .BASE_SIZE;
          const previewModelLevels: number[] = previewModelPositions.map(([mCol, mRow], idx) => {
            if (currentLevel >= 1 && previewFloorSet) {
              const meta = previewModelMetas[idx];
              const fpKeys = unitFootprintHexKeys({
                col: mCol + previewDeltaCol,
                row: mRow + previewDeltaRow,
                BASE_SHAPE: meta?.BASE_SHAPE ?? previewUnitBaseShape,
                BASE_SIZE: meta?.BASE_SIZE ?? previewUnitBaseSize,
              });
              let allOnFloor = fpKeys.size > 0;
              for (const k of fpKeys) {
                if (!previewFloorSet.has(k)) {
                  allOnFloor = false;
                  break;
                }
              }
              if (allOnFloor) return currentLevel;
            }
            return 0;
          });
          const previewModelLevelGhost: boolean[] = previewModelLevels.map(
            (lv) => lv !== currentLevel
          );

          renderUnit({
            hideIndicators,
            unit: { ...previewUnit, hidden: previewHiddenSquad },
            centerX,
            centerY,
            modelCenters: previewModelCenters,
            modelMetas: previewModelMetas,
            modelLevels: previewModelLevels,
            modelLevelGhost: previewModelLevelGhost,
            modelHidden: previewModelHidden,
            statusBadgePerModel,
            app,
            // Ghost de destination (collé à la souris) : corps + badges/logos dans le layer dédié
            // zIndex 25000 → au-dessus des barres HP et logos des autres unités.
            renderTarget: movePreviewGhostLayer,
            uiElementsContainer: movePreviewGhostLayer,
            useOverlayIcons: true,
            isPreview: true,
            previewType: "move",
            isEligible: false,
            displayOrientationStep: movePreview.orientation,
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
            onConfirmMove: onConfirmMoveForRender,
            parseColor,
            autoSelectWeapon,
            onUnitTooltip: handleUnitTooltip,
            onBlinkProbHtml: handleBlinkProbHtml,
            debugMode: showHexCoordinates,
            chargeMaxDistance,
          });
        }
      }

      // ✅ DEAD MODEL GHOSTS — models that died during shoot phase, rendered as grey ghosts
      for (const ghost of deadModelGhostsForRender) {
        const gCenterX = ghost.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const gCenterY =
          ghost.row * HEX_VERT_SPACING +
          ((ghost.col % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN;
        renderUnit({
          hideIndicators,
          unit: { ...ghost.unit, isJustKilled: true } as Unit & { isJustKilled: boolean },
          centerX: gCenterX,
          centerY: gCenterY,
          modelCenters: [[gCenterX, gCenterY]],
          modelMetas: [ghost.meta],
          app,
          renderTarget: unitsLayer,
          boardConfig: boardConfigForRender,
          parseColor,
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
          selectedUnitId: null,
          unitsMoved,
          chargeTargets: [],
          fightTargets: [],
          units,
          isEligible: false,
          isShootable: false,
          useOverlayIcons: false,
        });
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
            hideIndicators,
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
            onConfirmMove: onConfirmMoveForRender,
            parseColor,
            onUnitTooltip: handleUnitTooltip,
            onBlinkProbHtml: handleBlinkProbHtml,
            autoSelectWeapon,
            debugMode: showHexCoordinates,
            chargeMaxDistance,
          });
        }
      }
    } // end if (unitsChanged)

    // ✅ TUTORIAL 1-24-* / 1-25 : ghost Termagant à l'emplacement de mort sur le board
    if (
      tutorial?.currentStep?.stage != null &&
      (tutorial.currentStep.stage === "1-25" || tutorial.currentStep.stage.startsWith("1-24-")) &&
      tutorial?.lastEnemyDeathPosition &&
      boardConfig
    ) {
      const { col, row } = tutorial.lastEnemyDeathPosition;
      const ghostCenterX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const ghostCenterY =
        row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
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

    // Overlay icons (advance / weapon selection) retirés — plus rien à dessiner ici.

    // --- Drag placement overlay (deployment phase ghost + footprint) ---
    let dragPointerMove: ((e: PointerEvent) => void) | null = null;
    let dragPointerUp: ((e: PointerEvent) => void) | null = null;
    let dragPointerLeave: (() => void) | null = null;

    // Le drag de déploiement mono-socle (deploy_unit) ne sert plus en mode "active" :
    // le déploiement par escouade (deploymentMove) gère le placement par-figurine.
    if (
      phase === "deployment" &&
      selectedUnitId !== null &&
      gameState.deployment_type !== "active"
    ) {
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
          BASE_SIZE: resolveBaseSizeForUnitDisplay(u),
          alive: u.HP_CUR > 0,
        })),
        selectedUnitId ?? undefined
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
              deployPool.add(
                `${(entry as { col: number; row: number }).col},${(entry as { col: number; row: number }).row}`
              );
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
        contestedIds: number[]
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
        const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
        const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
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
        const sizeDrag = resolveBaseSizeForUnitDisplay(selectedUnit);
        const fp = computeOccupiedHexes(hex.col, hex.row, "round", sizeDrag);
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
        const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
        const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
        const px = (e.clientX - rect.left) * scaleX;
        const py = (e.clientY - rect.top) * scaleY;
        const hex = pixelToHex(px, py, HEX_RADIUS, MARGIN, BOARD_COLS, BOARD_ROWS);

        if (hex.col < 0 || hex.col >= BOARD_COLS || hex.row < 0 || hex.row >= BOARD_ROWS) return;
        if (!selectedUnit) return;
        const sizeUp = resolveBaseSizeForUnitDisplay(selectedUnit);
        const fp = computeOccupiedHexes(hex.col, hex.row, "round", sizeUp);
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
        const poolRef = resolvedMoveDestPoolRef.current;

        dragPointerMove = (e: PointerEvent) => {
          const rect = canvas.getBoundingClientRect();
          const scaleX = app.renderer.width / app.renderer.resolution / rect.width;
          const scaleY = app.renderer.height / app.renderer.resolution / rect.height;
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
    currentLevel,
    occupiedFloorLevelsKey,
    selectedUnitId,
    ruleChoiceHighlightedUnitId,
    mode,
    phase,
    boardConfig,
    boardZoom,
    gameConfig,
    gameConfig?.game_rules,
    loading,
    error,
    activeShootingUnit,
    advanceRoll,
    advancingUnitId,
    attackPreview,
    autoSelectWeapon,
    hpBarPerModel,
    hpBarBlinkEnlarged,
    showWoundProbability,
    statusBadgePerModel,
    hideIndicators,
    availableCellsOverride,
    isBlinkingActive,
    stableBlinkingUnits,
    blinkingAttackerId,
    chargeRoll,
    chargeRollPopup,
    chargePreviewOverlayKey,
    chargeReferenceKey,
    chargeSuccess,
    chargeTargetId,
    chargingUnitId,
    current_player,
    eligibleUnitIds,
    fightActivePlayer,
    fightSubPhase,
    fightTargetId,
    fightingUnitId,
    pendingMoveAfterShooting,
    getAdvanceDestinations,
    getChargeDestinations,
    movePreview,
    movingUnitId,
    objectivesOverride,
    onAdvance,
    onCancelAdvance,
    onCancelMove,
    onCancelTargetPreview,
    onConfirmMove,
    onDirectMove,
    onSelectUnit,
    onSkipUnit,
    onStartMovePreview,
    shootingActivationQueue,
    hideAdvanceIconForTutorial,
    showHexCoordinates,
    showLosDebugOverlay,
    shootingTargetId,
    shootingUnitId,
    targetPreview,
    unitsAttacked,
    unitsCharged,
    unitsFled,
    unitsMoved,
    wallHexesOverride,
    losObscuringZones,
    losTerrainZones,
    blinkVersion,
    deploymentState,
    replayActionIndex,
    tutorial?.currentStep?.stage,
    tutorial?.lastEnemyDeathPosition,
    movePreviewLosBlinkIds,
    movePreviewHiddenModelIds,
    movePreviewLosCoverKey,
    movePreviewLosTooFarKey,
    blinkingCoverByUnitIdKey,
    blinkingHiddenTooFarByUnitIdKey,
    shootPreviewWasmLos.key,
    shootAdvanceLosAnchorKey,
    handleUnitIconHoverChange,
    chargeDestPoolRef,
    units,
    handleUnitTooltip,
    gameState?.turn,
    resolvedMoveDestPoolRef.current.size,
    onSkipPileIn,
    handleBlinkProbHtml,
    gameState?.units_cache,
    gameState?.primary_objective,
    shootAdvanceLosAnchor,
    movePreviewLosCoverById,
    movePreviewLosTooFarById,
    resolvedMoveDestPoolRef.current,
    resolvedMoveDestPoolRef,
    gameState?.unitsAdvanced,
    gameState?.phase,
    gameState?.currentTurn,
    gameState?.active_shooting_unit,
    gameState?.active_movement_unit,
    gameState?.active_charge_unit,
    gameState.non_active_alternating_activation_pool,
    gameState.charging_activation_pool,
    gameState.active_alternating_activation_pool,
    gameState,
    footprintZoneRef?.current,
    footprintMaskLoopsRef,
    effectivePhase,
    effectiveBlinkingUnitsWithMovePreview,
    chargeFootprintZoneRef?.current,
    chargePreviewOverlayHexes,
    footprintZoneRef,
    blinkingCoverByUnitId,
    blinkingHiddenTooFarByUnitId,
    blinkingLosOverviewUnitId,
    objectiveControlOverride,
    squadMovePlan,
    fleePreviewUnitId,
    squadMoveModelPoolRef,
    squadMoveModelMaskLoopsRef?.current,
    squadShootPlan,
    squadFightPlan,
    fightEngagedModelIds,
    deadModelGhostsForRender,
    // Slice G : redraw du pool/cercles charge/pile-in à chaque pose / sélection de fig.
    chargeMovePlan,
    chargeFocusActive,
    pileInMovePlan,
    effectivePerModelPlan,
    chargeModelPoolRef,
    pileInModelPoolRef,
    squadUnplacedUnionVersion,
  ]);

  // weapons_for_target pour UNE cible (profils éligibles + m/x). Read-only backend.
  const fetchWeaponsForTarget = async (
    unitId: number,
    targetId: string,
    modelId?: string
  ): Promise<Array<{ code: string; weapon: Weapon; m: number; x: number }>> => {
    const res = await fetch(`/api/game/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // Miroir tir/combat : même flux cible-d'abord, action pilotée par la phase.
        action: `squad_${phase === "fight" ? "fight" : "shoot"}_weapons_for_target`,
        unitId: String(unitId),
        targetId,
        // Fig sélectionnée : m/x scopés sur elle (les boutons n'affectent qu'elle).
        ...(modelId ? { modelId } : {}),
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error ?? "weapons_for_target rejected");
    return (data.result?.weapons ?? []) as Array<{
      code: string;
      weapon: Weapon;
      m: number;
      x: number;
    }>;
  };

  // Clic sur un ennemi : AJOUTE une ligne-cible (sous chaque profil éligible). Menu permanent.
  const addTargetForShoot = async (targetId: string) => {
    const plan = phase === "fight" ? squadFightPlanRef.current : squadShootPlanRef.current;
    if (!plan) return;
    // Une fig déjà sélectionnée reste sélectionnée : lui attribuer une cible ne la
    // désélectionne pas — m/x de la nouvelle cible restent scopés sur elle.
    const keepFig = weaponSelectionMenuRef.current?.selectedFig;
    try {
      const [weapons, modelsStatus] = await Promise.all([
        fetchWeaponsForTarget(plan.unitId, targetId, keepFig),
        fetchModelsStatus(plan.unitId, targetId),
      ]);
      setWeaponSelectionMenu((prev) =>
        prev
          ? {
              ...prev,
              openTargets: prev.openTargets.includes(targetId)
                ? prev.openTargets
                : [...prev.openTargets, targetId],
              targetData: { ...prev.targetData, [targetId]: weapons },
              // La cible cliquée devient active : réticule + voiles vert/gris des figs.
              activeTargetId: targetId,
              modelsStatus,
              selectedFig: keepFig,
              selectedWeaponCode: undefined,
            }
          : prev
      );
    } catch (e) {
      console.error("🔴 addTargetForShoot error:", e);
    }
  };
  openWeaponsForTargetRef.current = addTargetForShoot;

  // État vert/gris (+ armes) de chaque fig de l'unité vis-à-vis de la cible.
  const fetchModelsStatus = async (
    unitId: number,
    targetId: string
  ): Promise<
    Array<{ model_id: string; can_shoot: boolean; exhausted: boolean; weapon_codes: string[] }>
  > => {
    const res = await fetch(`/api/game/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: `squad_${phase === "fight" ? "fight" : "shoot"}_models_status`,
        unitId: String(unitId),
        targetId,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error ?? "models_status rejected");
    return (data.result?.models ?? []) as Array<{
      model_id: string;
      can_shoot: boolean;
      exhausted: boolean;
      weapon_codes: string[];
    }>;
  };

  // Rafraîchit m/x de toutes les cibles ouvertes + les voiles vert/gris de la cible active.
  const refreshShootState = async () => {
    const menu = weaponSelectionMenuRef.current;
    const plan = phase === "fight" ? squadFightPlanRef.current : squadShootPlanRef.current;
    if (!menu || !plan) return;
    try {
      // Cible active + fig sélectionnée → m/x scopés sur la fig ; sinon vue escouade.
      const entries = await Promise.all(
        menu.openTargets.map(async (t) => {
          const scoped =
            menu.selectedFig && t === menu.activeTargetId ? menu.selectedFig : undefined;
          return [t, await fetchWeaponsForTarget(plan.unitId, t, scoped)] as const;
        })
      );
      const targetData: Record<
        string,
        Array<{ code: string; weapon: Weapon; m: number; x: number }>
      > = {};
      for (const [t, w] of entries) targetData[t] = w;
      let modelsStatus = menu.modelsStatus;
      if (menu.activeTargetId)
        modelsStatus = await fetchModelsStatus(plan.unitId, menu.activeTargetId);
      // Recharge les profils du menu (can_use) → exclusion Pistol/non-Pistol en temps réel.
      const menuRes = await fetch(`/api/game/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: `squad_${phase === "fight" ? "fight" : "shoot"}_menu_weapons`,
          unitId: String(plan.unitId),
        }),
      });
      const menuData = menuRes.ok ? await menuRes.json() : null;
      const menuWeapons = menuData?.success
        ? (menuData.result?.weapons as typeof menu.menuWeapons)
        : menu.menuWeapons;
      setWeaponSelectionMenu((prev) =>
        prev ? { ...prev, targetData, modelsStatus, menuWeapons } : prev
      );
    } catch (e) {
      console.error("🔴 refreshShootState error:", e);
    }
  };

  // Sélectionne (fond jaune + menu = ses armes) ou désélectionne (undefined) une fig.
  // Recharge la cible active : m/x scopés sur la fig (sélection) ou vue escouade (désélection).
  const selectShootFig = (modelId: string | undefined) => {
    setWeaponSelectionMenu((prev) =>
      prev ? { ...prev, selectedFig: modelId, selectedWeaponCode: undefined } : prev
    );
    const menu = weaponSelectionMenuRef.current;
    const plan = phase === "fight" ? squadFightPlanRef.current : squadShootPlanRef.current;
    if (!menu || !plan || !menu.activeTargetId) return;
    const tid = menu.activeTargetId;
    void fetchWeaponsForTarget(plan.unitId, tid, modelId).then((weapons) => {
      setWeaponSelectionMenu((prev) =>
        prev ? { ...prev, targetData: { ...prev.targetData, [tid]: weapons } } : prev
      );
    });
  };
  selectShootFigRef.current = selectShootFig;

  // Clic sur une ligne d'ARME dans le menu : sélectionne l'arme (contour jaune sur les
  // figs qui la portent). L'attribution des tirs se fait via les boutons −/x/+/Max.
  const onWeaponRowClick = async (code: string) => {
    setWeaponSelectionMenu((prev) =>
      prev ? { ...prev, selectedWeaponCode: code, selectedFig: undefined } : prev
    );
  };

  // -/+/Max/valeur d'une ligne : fixe le nombre de tirs du profil `code` sur la cible.
  const setShootWeaponQty = async (code: string, count: number, targetId: string) => {
    const P = phase === "fight" ? "fight" : "shoot";
    const plan = phase === "fight" ? squadFightPlanRef.current : squadShootPlanRef.current;
    if (!plan) return;
    const fig = weaponSelectionMenuRef.current?.selectedFig;
    const action = count <= 0 ? `squad_${P}_unassign_weapon_qty` : `squad_${P}_assign_weapon_qty`;
    const body: Record<string, unknown> = {
      action,
      unitId: String(plan.unitId),
      weaponCode: code,
      targetId,
      // Fig sélectionnée : l'attribution ne concerne QUE cette figurine.
      ...(fig ? { modelId: fig } : {}),
    };
    if (count > 0) body.count = count;
    try {
      const res = await fetch(`/api/game/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error(b.reason ?? b.error ?? `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data.success) throw new Error(data.error ?? "qty rejected");
      // Rafraîchit compteurs x/m + voile vert.
      await refreshShootState();
      // Propage les déclarations (voile + validation) au plan via événement.
      // Miroir tir/combat : le combat émet vers son propre listener (setSquadFightPlan).
      window.dispatchEvent(
        new CustomEvent(
          phase === "fight" ? "squadFightDeclarationsUpdated" : "squadShootDeclarationsUpdated",
          {
            detail: {
              gameState: data.game_state,
              declarations: data.result?.declarations ?? [],
            },
          }
        )
      );
    } catch (e) {
      console.error("🔴 set qty error:", e);
    }
  };

  // Handle weapon selection
  const handleSelectWeapon = async (weaponIndex: number) => {
    if (!weaponSelectionMenu) return;

    const unit = units.find((u) => u.id === weaponSelectionMenu.unitId);
    // Le menu est l'UNION des armes par-figurine : l'arme se lit dans available_weapons
    // (l'index n'indexe plus unit.RNG_WEAPONS, liste du type d'escouade de base).
    const selWeapon = unit?.available_weapons?.find((w) => w.index === weaponIndex)?.weapon;
    const weaponDisplayName = selWeapon?.display_name ?? undefined;
    const weaponCode = selWeapon?.code;
    // NB : l'exclusivité de profil (Frag/Krak) est désormais garantie côté backend
    // (déclaration quantifiée par groupe) — plus de désassignation de profil frère ici.

    try {
      const API_BASE = "/api";
      const response = await fetch(`${API_BASE}/game/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "squad_select_weapon",
          unitId: weaponSelectionMenu.unitId.toString(),
          weaponIndex: weaponIndex,
          autoSelectWeapon: autoSelectWeapon,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error ?? `HTTP ${response.status}`);
      }
      const data = await response.json();
      if (!data.success || !data.game_state) {
        throw new Error(data.error ?? "weapon selection rejected by engine");
      }
      window.dispatchEvent(
        new CustomEvent("weaponSelected", {
          detail: {
            gameState: data.game_state,
            weaponDisplayName,
            weaponCode,
            availableWeapons: data.result?.available_weapons,
            weaponIndex,
            validTargets: data.result?.valid_targets,
            coverByUnitId: data.result?.cover_by_unit_id,
            hiddenTooFarByUnitId: data.result?.hidden_too_far_by_unit_id,
            isSquadMode: true,
          },
        })
      );
    } catch (error) {
      console.error("🔴 WEAPON SELECT ERROR:", error);
      window.dispatchEvent(
        new CustomEvent("weaponSelectError", {
          detail: { message: error instanceof Error ? error.message : String(error) },
        })
      );
    }
  };

  // Build weapon options
  // Menu cible-d'abord partagé tir/combat : actif en COMBAT quand un plan fight de la
  // MÊME unité est en cours (étape FIGHT). Pilote les actions du menu (Valider/Annuler,
  // source de couleur d'arme, plan des déclarations).
  const isFightMenu =
    phase === "fight" &&
    fightSubPhase === "fight" &&
    squadFightPlan != null &&
    weaponSelectionMenu != null &&
    String(weaponSelectionMenu.unitId) === String(squadFightPlan.unitId);

  const weaponOptions: WeaponOption[] = weaponSelectionMenu
    ? (() => {
        const unit = units.find((u) => u.id === weaponSelectionMenu.unitId);
        if (!unit) return [];
        // Combat mêlée : la source de couleur est CC_WEAPONS (les index du menu fight
        // indexent CC_WEAPONS) ; pas d'exigence de RNG_WEAPONS (unités sans arme à distance).
        if (!isFightMenu && !unit.RNG_WEAPONS) return [];

        const rngWeapons = isFightMenu ? (unit.CC_WEAPONS ?? []) : unit.RNG_WEAPONS;
        const activePlan = isFightMenu ? squadFightPlan : squadShootPlan;
        // Indices d'armes déjà assignés (une cible désignée).
        const assignedWeapons = new Set<number>(
          activePlan && String(activePlan.unitId) === String(weaponSelectionMenu.unitId)
            ? activePlan.declarations.map((d) => d.weapon_index)
            : []
        );
        // assigned = grisé (visuel) si ce profil exact a une cible déclarée.
        // Profil frère d'une combi : reste cliquable (remplacement combi géré dans handleSelectWeapon).
        const weaponFlags = (idx: number): { assigned: boolean; locked: boolean } => {
          return { assigned: assignedWeapons.has(idx), locked: false };
        };

        // Menu tir : profils rechargés en temps réel (can_use par-fig + exclusion Pistol) ;
        // fallback sur unit.available_weapons tant que menuWeapons n'est pas chargé.
        const availableWeapons = weaponSelectionMenu.menuWeapons ?? unit.available_weapons;

        if (availableWeapons && availableWeapons.length > 0) {
          return availableWeapons.map((w) => {
            const canUse =
              (w as { can_use?: boolean; canUse?: boolean }).can_use ??
              (w as { canUse?: boolean }).canUse;
            if (canUse == null)
              throw new Error(`Weapon ${w.index} of unit ${unit.id} missing can_use`);
            const flags = weaponFlags(w.index);
            return {
              index: w.index,
              weapon: w.weapon,
              canUse,
              reason: w.reason,
              color: weaponColorFor(rngWeapons, w.index),
              assigned: flags.assigned,
              locked: flags.locked,
            };
          });
        }
        // Fallback : available_weapons pas encore patchée (ex. squad entre squad_shoot_activate et réponse).
        return rngWeapons.map((w, idx) => {
          const flags = weaponFlags(idx);
          return {
            index: idx,
            weapon: w,
            canUse: true,
            reason: undefined,
            color: weaponColorFor(rngWeapons, idx),
            assigned: flags.assigned,
            locked: flags.locked,
          };
        });
      })()
    : [];

  // Simple container return - loading/error handled inside useEffect
  return (
    <div>
      <div
        style={{
          position: "relative",
          display: "inline-block",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 8,
            right: 8,
            zIndex: 1600,
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: 6,
            lineHeight: 1,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {maxFloorLevel >= 1 && (
              <button
                type="button"
                aria-label={`Étage affiché : niveau ${currentLevel}. Cliquer pour changer d'étage.`}
                title={`Niveau ${currentLevel} / ${maxFloorLevel}`}
                onClick={() =>
                  setCurrentLevel(currentLevel >= maxFloorLevel ? 0 : currentLevel + 1)
                }
                style={{
                  position: "relative",
                  border: "1px solid rgba(255,255,255,0.28)",
                  borderRadius: 6,
                  background: "rgba(17,24,39,0.88)",
                  color: "#e5e7eb",
                  cursor: "pointer",
                  outline: "none",
                  fontSize: 18,
                  height: 32,
                  width: 32,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: 0,
                }}
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke={
                    currentLevel === 0
                      ? "#e5e7eb"
                      : currentLevel === 1
                        ? "#22c55e"
                        : currentLevel === 2
                          ? "#f59e0b"
                          : "#ef4444"
                  }
                  strokeWidth="1.8"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 3 3 8l9 5 9-5-9-5Z" />
                  <path d="M3 12l9 5 9-5" />
                  <path d="M3 16l9 5 9-5" />
                </svg>
                <span
                  style={{
                    position: "absolute",
                    right: 1,
                    bottom: 0,
                    fontSize: 10,
                    fontWeight: 800,
                    lineHeight: 1,
                    color:
                      currentLevel === 0
                        ? "#e5e7eb"
                        : currentLevel === 1
                          ? "#22c55e"
                          : currentLevel === 2
                            ? "#f59e0b"
                            : "#ef4444",
                    textShadow: "0 0 2px rgba(0,0,0,0.9)",
                  }}
                >
                  {currentLevel}
                </span>
              </button>
            )}
            {boardZoom !== BOARD_ZOOM_DEFAULT && (
              <span
                aria-live="polite"
                style={{
                  padding: "5px 7px",
                  border: "1px solid rgba(255,255,255,0.22)",
                  borderRadius: 6,
                  background: "rgba(17,24,39,0.88)",
                  color: "#e5e7eb",
                  fontSize: 12,
                  fontWeight: 700,
                  lineHeight: 1,
                  minWidth: 42,
                  textAlign: "center",
                }}
              >
                {zoomPercent}%
              </span>
            )}
            <button
              type="button"
              aria-label="Regler le zoom du plateau"
              aria-expanded={zoomControlsOpen}
              onClick={() => setZoomControlsOpen((open) => !open)}
              style={{
                border: "1px solid rgba(255,255,255,0.28)",
                borderRadius: 6,
                background: "rgba(17,24,39,0.88)",
                color: "#e5e7eb",
                cursor: "pointer",
                outline: "none",
                fontSize: 18,
                height: 32,
                width: 32,
              }}
            >
              🔍
            </button>
          </div>
          {zoomControlsOpen && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 7,
                padding: "9px 8px",
                border: "1px solid rgba(255,255,255,0.22)",
                borderRadius: 8,
                background: "rgba(17,24,39,0.94)",
                color: "#e5e7eb",
                boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
                lineHeight: 1,
              }}
            >
              <input
                aria-label="Zoom du plateau"
                type="range"
                min={BOARD_ZOOM_MIN}
                max={BOARD_ZOOM_MAX}
                step={BOARD_ZOOM_SLIDER_STEP}
                value={boardZoom}
                onChange={(e) => {
                  const nextZoom = Number(e.currentTarget.value);
                  applyBoardZoom(() => nextZoom, resolveBoardZoomAnchorClient());
                }}
                style={{
                  width: 22,
                  height: 140,
                  writingMode: "vertical-lr",
                  direction: "rtl",
                }}
              />
              <span style={{ minWidth: 42, fontSize: 12, textAlign: "center" }}>
                {zoomPercent}%
              </span>
              <button
                type="button"
                onClick={handleBoardZoomReset}
                style={{
                  border: "1px solid rgba(255,255,255,0.24)",
                  borderRadius: 5,
                  background: "rgba(255,255,255,0.08)",
                  color: "#e5e7eb",
                  cursor: "pointer",
                  fontSize: 12,
                  padding: "4px 7px",
                }}
              >
                Reset
              </button>
            </div>
          )}
        </div>
        <div
          ref={boardViewportRef}
          onPointerDown={handleBoardPanStart}
          onPointerMove={handleBoardPanMove}
          onPointerUp={handleBoardPanEnd}
          onPointerCancel={handleBoardPanEnd}
          style={{
            width: fitBoardWidth ? `${fitBoardWidth}px` : undefined,
            height: fitBoardHeight ? `${fitBoardHeight}px` : undefined,
            maxWidth: "100%",
            // Fenêtre limitée à l'écran avec scroll interne (molette/scrollbar/pan) dans 2 cas : mode
            // "window" (board à taille réelle, navigable) ou dès qu'on zoome (> 1). Sinon (full/fit à
            // zoom 1) : aucune limite → board affiché en entier, c'est la page qui scrolle.
            maxHeight: isWindowedBoard ? "calc(100vh - 40px)" : undefined,
            overflow: isWindowedBoard ? "auto" : "visible",
            lineHeight: 0,
            scrollbarGutter: "stable",
            cursor:
              boardZoom > BOARD_ZOOM_DEFAULT ? (isBoardPanning ? "grabbing" : "grab") : undefined,
          }}
        >
          <div
            style={{
              position: "relative",
              width: scaledBoardWidth ? `${scaledBoardWidth}px` : undefined,
              height: scaledBoardHeight ? `${scaledBoardHeight}px` : undefined,
              minWidth: fitBoardWidth ? `${fitBoardWidth}px` : undefined,
              minHeight: fitBoardHeight ? `${fitBoardHeight}px` : undefined,
              // ``transform: scale()`` rétrécit le board visuellement mais lui laisse son empreinte
              // pleine taille dans le layout → le bas de l'emplacement d'origine resterait visible (fond
              // sombre). En mode fit (fitScale < 1) on clippe cette empreinte à la taille réduite.
              overflow: fitScale < 1 ? "hidden" : undefined,
            }}
          >
            <div
              aria-busy={activationPendingUnitId != null}
              style={{
                position: "relative",
                display: "inline-block",
                lineHeight: 0,
                overflow: "visible",
                transform: `scale(${effectiveScale})`,
                transformOrigin: "top left",
                /* ``progress`` : activité en cours sans le curseur sablier système (``wait``). */
                cursor:
                  activationPendingUnitId != null
                    ? "progress"
                    : isBoardPanning
                      ? "grabbing"
                      : boardZoom > BOARD_ZOOM_DEFAULT
                        ? "grab"
                        : undefined,
              }}
            >
              {/* biome-ignore lint/a11y/noStaticElementInteractions: canvas de jeu — mouse tracking uniquement, pas d'interaction utilisateur */}
              <div
                role="presentation"
                ref={canvasContainerRef}
                onMouseMove={handleCanvasMouseMove}
                onMouseLeave={() => {
                  clearUnitIllustrationHoverTimer();
                  onUnitIllustrationPreviewChange?.(null);
                  setHexCoordTooltip(null);
                  setUnitHoverTooltip(null);
                  setMovePreviewDistanceTooltip(null);
                  setMeasureDistanceTooltip(null);
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
            </div>
          </div>
        </div>
        {unitHoverTooltip?.visible &&
          typeof document !== "undefined" &&
          createPortal(
            <div
              className="rule-tooltip unit-icon-tooltip"
              style={{
                position: "fixed",
                left: `${unitHoverTooltip.x}px`,
                top: `${unitHoverTooltip.y}px`,
                marginBottom: 0,
                zIndex: unitHoverTooltip.zIndex ?? 1300,
                visibility: "visible",
                opacity: unitHoverTooltip.opacity ?? 1,
                transform: "translate(12px, -14px)",
                pointerEvents: "none",
              }}
            >
              {unitHoverTooltip.text}
            </div>,
            document.body
          )}
        {typeof document !== "undefined" &&
          !hideIndicators &&
          Object.keys(blinkProbHtmlByUnitId).length > 0 &&
          createPortal(
            Object.entries(blinkProbHtmlByUnitId).map(([idStr, data]) => {
              // Vue escouade (double-clic) : N figs de l'escouade qui peuvent viser cet ennemi / M vivantes.
              const losN =
                blinkingLosOverviewUnitId != null &&
                blinkingLosCountByUnitId != null &&
                blinkingSquadAliveCount != null
                  ? blinkingLosCountByUnitId[idStr]
                  : undefined;
              const losText = losN != null ? `${losN}/${blinkingSquadAliveCount}` : null;
              // Cadre vide (option % off, pas de vue escouade, pas de couvert) → rien à afficher.
              if (!losText && !data.label && !data.showCoverShield) return null;
              return (
                <div
                  key={`blink-prob-${idStr}`}
                  className="rule-tooltip unit-icon-tooltip"
                  role="presentation"
                  style={{
                    position: "fixed",
                    left: `${data.left}px`,
                    top: `${data.top}px`,
                    marginBottom: 0,
                    zIndex: DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX,
                    visibility: "visible",
                    opacity: 1,
                    transform: "translateX(-50%)",
                    pointerEvents: "auto",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    maxWidth: "min(92vw, var(--tooltip-max-width))",
                  }}
                  onPointerMove={(e) => {
                    const el = e.target as HTMLElement;
                    if (el.closest('[data-blink-prob-shield="1"]')) {
                      setUnitHoverTooltip({
                        visible: true,
                        text: "Couvert (COVER) : +1 au jet de sauvegarde.",
                        x: e.clientX,
                        y: e.clientY,
                        zIndex: DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX,
                        opacity: DAMAGE_PROBABILITY_TOOLTIP_HTML_OPACITY,
                      });
                    } else {
                      setUnitHoverTooltip({
                        visible: true,
                        text: data.probabilityHelpText,
                        x: e.clientX,
                        y: e.clientY,
                        zIndex: DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX,
                        opacity: DAMAGE_PROBABILITY_TOOLTIP_HTML_OPACITY,
                      });
                    }
                  }}
                  onPointerLeave={() => {
                    setUnitHoverTooltip(null);
                  }}
                >
                  {losText ? (
                    <>
                      <span
                        data-blink-prob-los-eye="1"
                        style={{ display: "inline-flex", alignItems: "center" }}
                        aria-hidden
                      >
                        <svg
                          aria-hidden={true}
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          style={{ display: "block" }}
                        >
                          <path
                            fill="currentColor"
                            d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5C21.27 7.61 17 4.5 12 4.5zm0 12a4.5 4.5 0 110-9 4.5 4.5 0 010 9zm0-7a2.5 2.5 0 100 5 2.5 2.5 0 000-5z"
                          />
                        </svg>
                      </span>
                      <span
                        data-blink-prob-los="1"
                        style={{ fontWeight: 700, opacity: 0.9, whiteSpace: "nowrap" }}
                      >
                        {losText}
                      </span>
                    </>
                  ) : null}
                  {data.label ? <span data-blink-prob-label="1">{data.label}</span> : null}
                  {data.showCoverShield ? (
                    <span
                      data-blink-prob-shield="1"
                      style={{ display: "inline-flex", alignItems: "center" }}
                      aria-hidden
                    >
                      <svg
                        aria-hidden={true}
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        style={{ display: "block" }}
                      >
                        <path
                          fill="currentColor"
                          d="M12 2L4 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-8-3z"
                        />
                      </svg>
                    </span>
                  ) : null}
                </div>
              );
            }),
            document.body
          )}
        {!hideIndicators && movePreviewDistanceTooltip?.visible && (
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
        {measureDistanceTooltip?.visible && (
          <div
            className="rule-tooltip unit-icon-tooltip"
            style={{
              position: "fixed",
              left: `${measureDistanceTooltip.x}px`,
              top: `${measureDistanceTooltip.y}px`,
              marginBottom: 0,
              zIndex: 1300,
              visibility: "visible",
              opacity: 1,
              transform: "translate(12px, -14px)",
              pointerEvents: "none",
            }}
          >
            {measureDistanceTooltip.text}
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
          persistent={mode === "squadModelShoot" || isFightMenu}
          showActions={(mode === "squadModelShoot" && !!squadShootPlan) || isFightMenu}
          canValidate={
            isFightMenu
              ? (squadFightPlan?.canValidate ?? false)
              : (squadShootPlan?.canValidate ?? false)
          }
          onCancel={isFightMenu ? onCancelSquadFight : onCancelSquadShoot}
          onFire={isFightMenu ? onCommitSquadFight : onCommitSquadShoot}
          openTargets={weaponSelectionMenu.openTargets}
          targetData={weaponSelectionMenu.targetData}
          targetLabel={(tid) => {
            const u = units.find((x) => String(x.id) === String(tid));
            const type = (u as unknown as { unit_type?: string })?.unit_type ?? u?.name ?? "";
            return `#${tid}${type ? ` ${type}` : ""}`;
          }}
          onSetQty={(code, count, tid) => void setShootWeaponQty(code, count, tid)}
          activeTargetId={weaponSelectionMenu.activeTargetId}
          onWeaponRowClick={(code) => void onWeaponRowClick(code)}
          highlightedCodes={
            weaponSelectionMenu.selectedWeaponCode
              ? [weaponSelectionMenu.selectedWeaponCode]
              : (weaponSelectionMenu.figWeapons?.[weaponSelectionMenu.selectedFig ?? ""] ?? [])
          }
          weaponTotals={(() => {
            const totals: Record<string, number> = {};
            for (const codes of Object.values(weaponSelectionMenu.figWeapons ?? {}))
              for (const c of codes) totals[c] = (totals[c] ?? 0) + 1;
            return totals;
          })()}
          restrictToCodes={
            weaponSelectionMenu.selectedFig
              ? (weaponSelectionMenu.modelsStatus?.find(
                  (s) => s.model_id === weaponSelectionMenu.selectedFig
                )?.weapon_codes ??
                weaponSelectionMenu.figWeapons?.[weaponSelectionMenu.selectedFig] ??
                [])
              : undefined
          }
          inchesToSubhex={
            (boardConfig as unknown as { inches_to_subhex?: number } | null)?.inches_to_subhex ?? 1
          }
        />
      )}
    </div>
  );
}
