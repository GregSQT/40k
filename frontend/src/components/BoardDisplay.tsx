// frontend/src/components/BoardDisplay.tsx

import * as PIXI from "pixi.js-legacy";
import type React from "react";
import {
  type HexUnionMaskLayout,
  tryBuildHexUnionMaskPolygons,
} from "../utils/hexUnionBoundaryPolygon";
import { mountLosPolarClippedByVisibleUnion } from "../utils/losPolarMaskedByVisibleUnion";
import { addHexKeysToSet } from "../utils/movePoolRefsSync";
import { smoothMaskLoopsForRender } from "../utils/polygonSmooth";

/** Contourne TS2345 : certaines fusions de types sur `.on` attendent `(...args: unknown[]) => void`. */
function asPixiUnknownArgsPointerListener(
  fn: (e: PIXI.FederatedPointerEvent) => void
): (...args: unknown[]) => void {
  return fn as (...args: unknown[]) => void;
}

/**
 * Passes Chaikin sur les masques move/advance (rendu uniquement).
 * Plafond de sommets : ``MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS`` — bord plus continu sur petites zones.
 * Sur gros contours, le nombre de passes est réduit (voir ``resolveMoveAdvanceMaskChaikinIterations``).
 */
const MOVE_ADVANCE_MASK_CHAIKIN_ITERS_SMALL_ZONE = 5;
const MOVE_ADVANCE_MASK_CHAIKIN_ITERS_MEDIUM_ZONE = 4;
const MOVE_ADVANCE_MASK_CHAIKIN_ITERS_ENORMOUS_ZONE = 3;
/**
 * Somme des sommets (points) de toutes les boucles **avant** Chaikin ; seuils inclus côté « petit » / « moyen ».
 */
const MOVE_ADVANCE_MASK_CHAIKIN_VERTS_SMALL_MAX = 400;
const MOVE_ADVANCE_MASK_CHAIKIN_VERTS_MEDIUM_MAX = 3000;
/** Autorise des passes Chaikin supplémentaires sur les très gros contours (défaut global 48k). */
const MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS = 120_000;
/**
 * Blur alpha du masque : fort sur petites zones (historique), plus léger sur moyennes / énormes
 * (``BlurFilter`` sur une grande RT est coûteux).
 */
const MOVE_ADVANCE_MASK_ALPHA_BLUR_STRENGTH_SMALL_ZONE = 1.4;
const MOVE_ADVANCE_MASK_ALPHA_BLUR_QUALITY_SMALL_ZONE = 3;
const MOVE_ADVANCE_MASK_ALPHA_BLUR_RESOLUTION_SMALL_ZONE = 2;

const MOVE_ADVANCE_MASK_ALPHA_BLUR_STRENGTH_MEDIUM_ZONE = 1.25;
const MOVE_ADVANCE_MASK_ALPHA_BLUR_QUALITY_MEDIUM_ZONE = 2;
const MOVE_ADVANCE_MASK_ALPHA_BLUR_RESOLUTION_MEDIUM_ZONE = 1;

const MOVE_ADVANCE_MASK_ALPHA_BLUR_STRENGTH_ENORMOUS_ZONE = 1.0;
const MOVE_ADVANCE_MASK_ALPHA_BLUR_QUALITY_ENORMOUS_ZONE = 1;
const MOVE_ADVANCE_MASK_ALPHA_BLUR_RESOLUTION_ENORMOUS_ZONE = 1;

const moveAdvanceMaskSmoothOptions = {
  maxVertsAfterOneChaikinStep: MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS,
} as const;

/** Incrémenter si le pipeline d’assemblage layer (clé « full ») change. */
const MOVE_PREVIEW_LAYER_RENDER_CACHE_VERSION = 5;
/** Incrémenter si Chaikin / blur / format RT masque doux / tuilage change. */
const MOVE_PREVIEW_SOFT_MASK_CACHE_VERSION = 4;

/** Alpha du rectangle de couverture (identique au rendu historique). */
const MOVE_PREVIEW_COVERAGE_FILL_ALPHA = 0.28;

interface MovePreviewLayerRenderCacheEntry {
  key: string;
  root: PIXI.Container;
}

interface MovePreviewSoftMaskBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface MovePreviewSoftMaskCacheEntry {
  key: string;
  /** Une ou plusieurs RT (tuiles ≤ ``FOOTPRINT_HIGHLIGHT_RT_MAX_DIM``), ordre row-major ``ti`` puis ``tj``. */
  softTileRts: PIXI.RenderTexture[];
  maskBounds: MovePreviewSoftMaskBounds;
  tilesW: number;
  tilesH: number;
}

let movePreviewLayerRenderCache: MovePreviewLayerRenderCacheEntry | null = null;
let movePreviewSoftMaskCache: MovePreviewSoftMaskCacheEntry | null = null;

function disposeMovePreviewSoftMaskCache(): void {
  if (!movePreviewSoftMaskCache) return;
  const { softTileRts } = movePreviewSoftMaskCache;
  movePreviewSoftMaskCache = null;
  for (const rt of softTileRts) {
    if (!rt.destroyed) {
      rt.destroy(true);
    }
  }
}

/** Détruit le root du layer sans détruire la RT masque doux (référence partagée). */
function disposeMovePreviewLayerRootCache(): void {
  if (!movePreviewLayerRenderCache) return;
  const { root } = movePreviewLayerRenderCache;
  movePreviewLayerRenderCache = null;
  if (root.destroyed) return;
  const kids = [...root.children];
  for (const c of kids) {
    root.removeChild(c);
    if (c instanceof PIXI.Sprite) {
      c.destroy({ children: false, texture: false, baseTexture: false });
    } else if (c instanceof PIXI.Container) {
      const inner = [...c.children];
      for (const cc of inner) {
        c.removeChild(cc);
        if (cc instanceof PIXI.Sprite) {
          cc.destroy({ children: false, texture: false, baseTexture: false });
        } else {
          cc.destroy();
        }
      }
      c.destroy({ children: false, texture: false, baseTexture: false });
    } else {
      c.destroy();
    }
  }
  root.destroy({ children: false, texture: false, baseTexture: false });
}

/** Layer + RT masque doux (hors preview move ou reset complet). */
function disposeMovePreviewRenderCachesFull(): void {
  disposeMovePreviewLayerRootCache();
  disposeMovePreviewSoftMaskCache();
}

/**
 * Retire le cache du layer move preview de son parent pour qu'il ne soit pas
 * détruit avec l'ancien ``highlightContainer`` lors du ``removeChildren`` du stage.
 * Même principe que les conteneurs persistants détachés dans BoardPvp avant destroy.
 */
export function detachMovePreviewLayerCacheFromStage(): void {
  const root = movePreviewLayerRenderCache?.root;
  if (root?.parent) {
    root.parent.removeChild(root);
  }
}

/** Bump when la définition de l’empreinte « structure highlights » change (hors clé polygone move). */
const BOARD_DISPLAY_HIGHLIGHT_STRUCTURAL_FP_V = 1;

function digestHighlightCellList(cells: Array<{ col: number; row: number }> | undefined): number {
  const s = new Set<string>();
  for (const c of cells ?? []) {
    s.add(`${c.col},${c.row}`);
  }
  return hashStringSetStable(s);
}

function digestChargeCellList(
  cells: Array<HighlightCell | [number, number] | { col: number; row: number }> | undefined
): number {
  const s = new Set<string>();
  for (const c of cells ?? []) {
    const cc = Array.isArray(c) ? c[0] : c.col;
    const cr = Array.isArray(c) ? c[1] : c.row;
    s.add(`${cc},${cr}`);
  }
  return hashStringSetStable(s);
}

export interface DrawBoardPartialRedrawFingerprint {
  structuralKey: string;
  /** Même sémantique que ``movePreviewCacheKey`` dans ``drawBoard`` ; ``null`` si pas de calque polygone move. */
  movePolygonCacheKey: string | null;
}

/**
 * Empreintes pour éviter un ``drawBoard`` complet quand seuls les highlights move-polygone changent
 * (ou quand rien ne change — réutilisation du conteneur ``highlights`` à travers le destroy stage BoardPvp).
 */
export function computeDrawBoardPartialRedrawFingerprint(
  app: PIXI.Application,
  boardConfig: BoardConfig,
  options?: DrawBoardOptions
): DrawBoardPartialRedrawFingerprint {
  const {
    availableCells = [],
    attackCells = [],
    coverCells = [],
    chargeCells = [],
    advanceCells = [],
    phase = "move",
    interactionPhase = phase,
    selectedUnitId = null,
    mode = "select",
    moveDestPoolRef,
    footprintZonePoolRef,
    moveDestinationAnchorsFromState,
    movePreviewFootprintSpanFromState,
    pendingMoveAfterShooting = false,
    chargeDestPoolRef,
    selectedUnitBaseSize,
    selectedUnitAnchor,
    movePreviewFootprintMaskLoops = null,
    chargeEngagementHalo,
    fightEngagementRing,
  } = options || {};

  const useAdvanceMovePoolLikeMove = mode === "advancePreview";
  const usePostShootMovePoolLikeMove =
    interactionPhase === "shoot" && pendingMoveAfterShooting === true;
  const usePileInPoolLikeMoveHoisted =
    interactionPhase === "fight" && (mode === "pileInPreview" || mode === "consolidationPreview");
  const useConsolidationPreview = interactionPhase === "fight" && mode === "consolidationPreview";

  const spanFromEngine =
    typeof movePreviewFootprintSpanFromState === "number" &&
    Number.isFinite(movePreviewFootprintSpanFromState) &&
    movePreviewFootprintSpanFromState >= 1
      ? Math.floor(movePreviewFootprintSpanFromState)
      : null;
  const footprintSpanForPool = Math.max(1, spanFromEngine ?? selectedUnitBaseSize ?? 1);

  const anchorsFromStatePool: Set<string> | null = (() => {
    if (moveDestinationAnchorsFromState == null) return null;
    const s = new Set<string>();
    addHexKeysToSet(moveDestinationAnchorsFromState, s);
    return s.size > 0 ? s : null;
  })();

  const allowMovePoolFallbackFromGameState =
    selectedUnitId != null ||
    mode === "advancePreview" ||
    (interactionPhase === "shoot" && pendingMoveAfterShooting) ||
    ((interactionPhase === "move" || interactionPhase === "command") && mode === "movePreview");

  const movePoolForDiskDraw: Set<string> | null =
    moveDestPoolRef?.current && moveDestPoolRef.current.size > 0
      ? moveDestPoolRef.current
      : allowMovePoolFallbackFromGameState && anchorsFromStatePool && anchorsFromStatePool.size > 0
        ? anchorsFromStatePool
        : null;

  const useMoveDestPoolCircleLayer =
    (interactionPhase === "move" ||
      useAdvanceMovePoolLikeMove ||
      usePostShootMovePoolLikeMove ||
      usePileInPoolLikeMoveHoisted) &&
    !!movePoolForDiskDraw &&
    movePoolForDiskDraw.size > 0;

  const useChargeDestPoolDiskDraw =
    interactionPhase === "charge" &&
    (mode === "select" || mode === "chargePreview") &&
    !!chargeDestPoolRef?.current &&
    chargeDestPoolRef.current.size > 0;

  const moveAdvanceOrPileInPickPool: Set<string> | null = (() => {
    if (interactionPhase === "move" || useAdvanceMovePoolLikeMove || usePostShootMovePoolLikeMove) {
      return movePoolForDiskDraw && movePoolForDiskDraw.size > 0 ? movePoolForDiskDraw : null;
    }
    if (usePileInPoolLikeMoveHoisted) {
      if (moveDestPoolRef?.current && moveDestPoolRef.current.size > 0) {
        return moveDestPoolRef.current;
      }
      return null;
    }
    return null;
  })();

  const clickableBranchExcluded = interactionPhase === "charge" && mode === "select" ? 1 : 0;
  const clickableAvailDigest =
    interactionPhase === "charge" && mode === "select"
      ? 0
      : digestHighlightCellList(availableCells);

  const structuralPayload = {
    v: BOARD_DISPLAY_HIGHLIGHT_STRUCTURAL_FP_V,
    cols: boardConfig.cols,
    rows: boardConfig.rows,
    hex_radius: boardConfig.hex_radius,
    margin: boardConfig.margin,
    res: app.renderer.resolution,
    phase,
    interactionPhase,
    mode,
    selectedUnitId,
    pendingMoveAfterShooting,
    footprintSpanForPool,
    selectedUnitBaseSize: selectedUnitBaseSize ?? null,
    spanFromEngine,
    useMoveDestPoolCircleLayer,
    useConsolidationPreview,
    useChargeDestPoolDiskDraw,
    chargeDestPoolHash:
      useChargeDestPoolDiskDraw && chargeDestPoolRef?.current
        ? hashStringSetStable(chargeDestPoolRef.current)
        : null,
    digestAvail: clickableAvailDigest,
    digestAtk: digestHighlightCellList(attackCells),
    digestCov: digestHighlightCellList(coverCells),
    digestChg: digestChargeCellList(chargeCells),
    digestAdv: digestHighlightCellList(advanceCells),
    clickableBranchExcluded,
    movePickPoolHash:
      moveAdvanceOrPileInPickPool != null && moveAdvanceOrPileInPickPool.size > 0
        ? hashStringSetStable(moveAdvanceOrPileInPickPool)
        : null,
    moveRefPoolHash:
      moveDestPoolRef?.current && moveDestPoolRef.current.size > 0
        ? hashStringSetStable(moveDestPoolRef.current)
        : null,
    anchorsDigest:
      anchorsFromStatePool != null && anchorsFromStatePool.size > 0
        ? hashStringSetStable(anchorsFromStatePool)
        : null,
    chargeEngagementHalo: chargeEngagementHalo ?? null,
    fightEngagementRing: fightEngagementRing ?? null,
  };

  const structuralKey = JSON.stringify(structuralPayload);

  let movePolygonCacheKey: string | null = null;
  if (useMoveDestPoolCircleLayer && movePoolForDiskDraw) {
    if (selectedUnitAnchor == null) {
      movePolygonCacheKey = null;
    } else {
      const HEX_RADIUS = boardConfig.hex_radius;
      const MARGIN = boardConfig.margin;
      const HEX_WIDTH = 1.5 * HEX_RADIUS;
      const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
      const HEX_HORIZ_SPACING = HEX_WIDTH;
      const HEX_VERT_SPACING = HEX_HEIGHT;
      const footprintRadius = (footprintSpanForPool / 2) * HEX_HORIZ_SPACING;
      const ADVANCE_DESTINATION_HEX_FILL = 0xff8c00;
      const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight!);
      const advanceZoneFillColor = ADVANCE_DESTINATION_HEX_FILL;
      const poolFillColor = useAdvanceMovePoolLikeMove ? advanceZoneFillColor : HIGHLIGHT_COLOR;
      const moveSpriteName = useAdvanceMovePoolLikeMove
        ? "advance-dest-pool"
        : usePileInPoolLikeMoveHoisted
          ? "fight-pile-in-dest-pool"
          : "move-dest-pool";
      const footprintMaskHexPool =
        footprintZonePoolRef?.current && footprintZonePoolRef.current.size > 0
          ? footprintZonePoolRef.current
          : null;
      const poolHash = hashStringSetStable(movePoolForDiskDraw);
      const footprintPoolHash =
        footprintMaskHexPool && footprintMaskHexPool.size > 0
          ? hashStringSetStable(footprintMaskHexPool)
          : null;
      const loopsFp = fingerprintPrecomputedMaskLoops(movePreviewFootprintMaskLoops ?? null);
      movePolygonCacheKey = JSON.stringify({
        v: MOVE_PREVIEW_LAYER_RENDER_CACHE_VERSION,
        res: app.renderer.resolution,
        ip: interactionPhase,
        mo: mode,
        pms: pendingMoveAfterShooting,
        sn: moveSpriteName,
        ph: poolHash,
        psz: movePoolForDiskDraw.size,
        fph: footprintPoolHash,
        fpsz: footprintMaskHexPool?.size ?? 0,
        lf: loopsFp,
        ghr: HEX_RADIUS,
        fr: footprintRadius,
        pfc: poolFillColor,
        ac: selectedUnitAnchor.col,
        ar: selectedUnitAnchor.row,
        fsp: footprintSpanForPool,
        sp: {
          hhs: HEX_HORIZ_SPACING,
          hw: HEX_WIDTH,
          hh: HEX_HEIGHT,
          hvs: HEX_VERT_SPACING,
          mg: MARGIN,
        },
        mvmax: MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS,
        covA: MOVE_PREVIEW_COVERAGE_FILL_ALPHA,
      });
    }
  }

  return { structuralKey, movePolygonCacheKey };
}

/**
 * Met à jour uniquement le sous-arbre ``move-preview-layer-cache-root`` dans un conteneur
 * ``highlights`` existant (même logique que le bloc correspondant dans ``drawBoard``).
 */
export function updateMovePreviewPolygonLayerInHighlightContainer(
  app: PIXI.Application,
  boardConfig: BoardConfig,
  highlightContainer: PIXI.Container,
  options?: DrawBoardOptions
): void {
  if (!boardConfig || !app.stage) {
    throw new Error(
      "[updateMovePreviewPolygonLayerInHighlightContainer] boardConfig et app.stage sont requis"
    );
  }

  detachMovePreviewLayerCacheFromStage();

  const orphan = highlightContainer.children.find(
    (c) => c.name === "move-preview-layer-cache-root"
  );
  if (orphan) {
    highlightContainer.removeChild(orphan);
    orphan.destroy({ children: true, texture: false, baseTexture: false });
  }
  disposeMovePreviewLayerRootCache();

  const {
    interactionPhase = "move",
    mode = "select",
    pendingMoveAfterShooting = false,
    moveDestPoolRef,
    footprintZonePoolRef,
    moveDestinationAnchorsFromState,
    movePreviewFootprintSpanFromState,
    selectedUnitId = null,
    selectedUnitBaseSize,
    selectedUnitAnchor,
    movePreviewFootprintMaskLoops = null,
  } = options || {};

  const useAdvanceMovePoolLikeMove = mode === "advancePreview";
  const usePostShootMovePoolLikeMove =
    interactionPhase === "shoot" && pendingMoveAfterShooting === true;
  const usePileInPoolLikeMoveHoisted =
    interactionPhase === "fight" && (mode === "pileInPreview" || mode === "consolidationPreview");

  const spanFromEngine =
    typeof movePreviewFootprintSpanFromState === "number" &&
    Number.isFinite(movePreviewFootprintSpanFromState) &&
    movePreviewFootprintSpanFromState >= 1
      ? Math.floor(movePreviewFootprintSpanFromState)
      : null;
  const footprintSpanForPool = Math.max(1, spanFromEngine ?? selectedUnitBaseSize ?? 1);

  const anchorsFromStatePool: Set<string> | null = (() => {
    if (moveDestinationAnchorsFromState == null) return null;
    const s = new Set<string>();
    addHexKeysToSet(moveDestinationAnchorsFromState, s);
    return s.size > 0 ? s : null;
  })();

  const allowMovePoolFallbackFromGameState =
    selectedUnitId != null ||
    mode === "advancePreview" ||
    (interactionPhase === "shoot" && pendingMoveAfterShooting) ||
    ((interactionPhase === "move" || interactionPhase === "command") && mode === "movePreview");

  const movePoolForDiskDraw: Set<string> | null =
    moveDestPoolRef?.current && moveDestPoolRef.current.size > 0
      ? moveDestPoolRef.current
      : allowMovePoolFallbackFromGameState && anchorsFromStatePool && anchorsFromStatePool.size > 0
        ? anchorsFromStatePool
        : null;

  const useMoveDestPoolCircleLayer =
    (interactionPhase === "move" ||
      useAdvanceMovePoolLikeMove ||
      usePostShootMovePoolLikeMove ||
      usePileInPoolLikeMoveHoisted) &&
    !!movePoolForDiskDraw &&
    movePoolForDiskDraw.size > 0;

  if (!useMoveDestPoolCircleLayer) {
    disposeMovePreviewRenderCachesFull();
    return;
  }

  const HEX_RADIUS = boardConfig.hex_radius;
  const MARGIN = boardConfig.margin;
  const HEX_WIDTH = 1.5 * HEX_RADIUS;
  const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
  const HEX_HORIZ_SPACING = HEX_WIDTH;
  const HEX_VERT_SPACING = HEX_HEIGHT;
  const ADVANCE_DESTINATION_HEX_FILL = 0xff8c00;
  const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight!);
  const advanceZoneFillColor = ADVANCE_DESTINATION_HEX_FILL;
  const poolFillColor = useAdvanceMovePoolLikeMove ? advanceZoneFillColor : HIGHLIGHT_COLOR;
  const moveSpriteName = useAdvanceMovePoolLikeMove
    ? "advance-dest-pool"
    : usePileInPoolLikeMoveHoisted
      ? "fight-pile-in-dest-pool"
      : "move-dest-pool";

  if (selectedUnitAnchor == null) {
    throw new Error(
      "[updateMovePreviewPolygonLayerInHighlightContainer] ``selectedUnitAnchor`` requis — " +
        `spriteName=${moveSpriteName}`
    );
  }

  const footprintRadius = (footprintSpanForPool / 2) * HEX_HORIZ_SPACING;
  const footprintMaskHexPool =
    footprintZonePoolRef?.current && footprintZonePoolRef.current.size > 0
      ? footprintZonePoolRef.current
      : null;
  const poolHash = hashStringSetStable(movePoolForDiskDraw);
  const footprintPoolHash =
    footprintMaskHexPool && footprintMaskHexPool.size > 0
      ? hashStringSetStable(footprintMaskHexPool)
      : null;
  const loopsFp = fingerprintPrecomputedMaskLoops(movePreviewFootprintMaskLoops ?? null);

  const movePreviewCacheKey = JSON.stringify({
    v: MOVE_PREVIEW_LAYER_RENDER_CACHE_VERSION,
    res: app.renderer.resolution,
    ip: interactionPhase,
    mo: mode,
    pms: pendingMoveAfterShooting,
    sn: moveSpriteName,
    ph: poolHash,
    psz: movePoolForDiskDraw.size,
    fph: footprintPoolHash,
    fpsz: footprintMaskHexPool?.size ?? 0,
    lf: loopsFp,
    ghr: HEX_RADIUS,
    fr: footprintRadius,
    pfc: poolFillColor,
    ac: selectedUnitAnchor.col,
    ar: selectedUnitAnchor.row,
    fsp: footprintSpanForPool,
    sp: {
      hhs: HEX_HORIZ_SPACING,
      hw: HEX_WIDTH,
      hh: HEX_HEIGHT,
      hvs: HEX_VERT_SPACING,
      mg: MARGIN,
    },
    mvmax: MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS,
    covA: MOVE_PREVIEW_COVERAGE_FILL_ALPHA,
  });

  const cachedEntry = movePreviewLayerRenderCache;
  const canReuse =
    cachedEntry != null && !cachedEntry.root.destroyed && cachedEntry.key === movePreviewCacheKey;

  if (canReuse) {
    highlightContainer.addChild(cachedEntry.root);
    return;
  }

  disposeMovePreviewLayerRootCache();
  const preNorm =
    movePreviewFootprintMaskLoops != null && movePreviewFootprintMaskLoops.length > 0
      ? movePreviewFootprintMaskLoops
      : null;
  const maskGeom = resolveMovePreviewMaskLoopsBeforeSmooth(
    preNorm,
    footprintMaskHexPool,
    HEX_RADIUS,
    HEX_HORIZ_SPACING,
    HEX_WIDTH,
    HEX_HEIGHT,
    HEX_VERT_SPACING,
    MARGIN,
    moveSpriteName,
    movePoolForDiskDraw.size
  );
  const cacheRoot = new PIXI.Container();
  cacheRoot.name = "move-preview-layer-cache-root";
  cacheRoot.eventMode = "none";
  renderMoveAdvanceDestPoolCircleLayer(
    cacheRoot,
    app,
    movePoolForDiskDraw,
    footprintRadius,
    poolFillColor,
    moveSpriteName,
    maskGeom
  );
  movePreviewLayerRenderCache = { key: movePreviewCacheKey, root: cacheRoot };
  highlightContainer.addChild(cacheRoot);
}

function hashStringSetStable(pool: Set<string>): number {
  const keys = [...pool].sort();
  let h = 5381 >>> 0;
  for (const k of keys) {
    for (let i = 0; i < k.length; i++) {
      h = Math.imul(33, h) ^ k.charCodeAt(i)!;
    }
    h = Math.imul(33, h) ^ 58;
  }
  return h | 0;
}

/** Empreinte légère des boucles monde (évite un stringify complet des milliers de nombres). */
function fingerprintPrecomputedMaskLoops(loops: number[][] | null): string {
  if (loops == null || loops.length === 0) return "∅";
  let h = 5381 >>> 0;
  let totalVerts = 0;
  for (let li = 0; li < loops.length; li++) {
    const flat = loops[li]!;
    const n = flat.length;
    totalVerts += n;
    h = Math.imul(33, h) ^ n;
    const stride = Math.max(1, Math.floor(n / 400));
    for (let i = 0; i < n; i += stride) {
      const v = flat[i]!;
      const bits =
        typeof v === "number" && Number.isFinite(v) ? (v * 131071) | 0 : 0x7bad0000 ^ li ^ i;
      h = Math.imul(33, h) ^ bits;
    }
  }
  return `L${loops.length}|V${totalVerts}|${h >>> 0}`;
}

function buildMovePreviewSoftMaskCacheKey(params: {
  v: number;
  res: number;
  rw: number;
  rh: number;
  kind: "server_loops" | "polygon";
  loopsFp: string;
  bs: number;
  bq: number;
  br: number;
  chai: number;
  mvmax: number;
}): string {
  return JSON.stringify(params);
}

/**
 * Une tuile = masque ``Sprite`` (alpha soft) + ``Graphics`` même rectangle monde avec ``.mask`` sur le sprite.
 * Pixi n’applique pas un masque alpha fiable via ``Graphics.mask = Container`` multi-sprites — d’où le rectangle plein (forme « carrée ») si on regroupait les tuiles dans un seul conteneur masque.
 */
function appendMovePreviewMaskTilesAndCoverageToParent(
  parentContainer: PIXI.Container,
  spriteName: string,
  smc: MovePreviewSoftMaskCacheEntry,
  tileMaxDim: number,
  poolFillColor: number
): void {
  const mb = smc.maskBounds;
  const wTot = Math.ceil(mb.width);
  const hTot = Math.ceil(mb.height);
  const expected = smc.tilesW * smc.tilesH;
  if (smc.softTileRts.length !== expected) {
    throw new Error(
      `[appendMovePreviewMaskTilesAndCoverageToParent] nombre de RT (${smc.softTileRts.length}) ≠ tuiles ` +
        `(${smc.tilesW}×${smc.tilesH}=${expected}, spriteName=${spriteName})`
    );
  }
  let idx = 0;
  for (let tj = 0; tj < smc.tilesH; tj++) {
    for (let ti = 0; ti < smc.tilesW; ti++) {
      const tileLeft = ti * tileMaxDim;
      const tileTop = tj * tileMaxDim;
      const tw = Math.min(tileMaxDim, wTot - tileLeft);
      const th = Math.min(tileMaxDim, hTot - tileTop);
      const sx = mb.x + tileLeft;
      const sy = mb.y + tileTop;

      const maskSprite = new PIXI.Sprite(smc.softTileRts[idx]!);
      maskSprite.name =
        smc.tilesW === 1 && smc.tilesH === 1
          ? `${spriteName}-mask-sprite`
          : `${spriteName}-mask-tile-${ti}-${tj}`;
      maskSprite.eventMode = "none";
      maskSprite.position.set(sx, sy);
      maskSprite.roundPixels = false;

      const tileCoverage = new PIXI.Graphics();
      tileCoverage.name =
        smc.tilesW === 1 && smc.tilesH === 1
          ? spriteName
          : `${spriteName}-coverage-tile-${ti}-${tj}`;
      tileCoverage.eventMode = "none";
      tileCoverage.beginFill(poolFillColor, 1.0);
      tileCoverage.drawRect(sx, sy, tw, th);
      tileCoverage.endFill();
      tileCoverage.alpha = MOVE_PREVIEW_COVERAGE_FILL_ALPHA;
      tileCoverage.mask = maskSprite;

      parentContainer.addChild(maskSprite);
      parentContainer.addChild(tileCoverage);
      idx++;
    }
  }
}

interface BoardConfig {
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
    background_image?: string;
    background_image_alpha?: number;
    background_overlay_alpha?: number;
    wall_texture?: string;
    wall_texture_alpha?: number;
    /** Chemin public (ex. /textures/obj1.webp). Teinte = couleur objectif / contrôle. */
    objective_texture?: string;
    objective_texture_alpha?: number;
    objective_smooth_contour?: boolean;
    /** Multiplie le rayon extérieur de la surcouche zone (barycentre → hex le plus éloigné + 1 hex). */
    objective_smooth_radius_ratio?: number;
    /** @deprecated Utiliser objective_zone_ring_alpha. Conservé comme défaut si objective_zone_ring_alpha absent. */
    objective_smooth_alpha?: number;
    /** Alpha des pastilles d’emprise par hex (footprint). */
    objective_hex_fill_alpha?: number;
    /** Cercle extérieur : épaisseur du trait (px). */
    objective_zone_ring_width?: number;
    objective_zone_ring_color?: string;
    objective_zone_ring_alpha?: number;
    /** Rayon du petit disque central, en fraction du rayon extérieur (0–1). */
    objective_zone_center_radius_ratio?: number;
    objective_zone_center_color?: string;
    objective_zone_center_alpha?: number;
  };
  objective_hexes: [number, number][];
  objective_zones?: Array<{
    id: string;
    hexes: Array<[number, number] | { col: number; row: number }>;
  }>;
  wall_hexes: [number, number][];
  walls?: Array<{
    start: { col: number; row: number };
    end: { col: number; row: number };
    thickness?: number;
  }>;
}

interface HighlightCell {
  col: number;
  row: number;
}

// Objective control info - which player controls each hex
interface ObjectiveControlMap {
  [hexKey: string]: number | null; // "col,row" -> 0 (P0), 1 (P1), or null (contested/uncontrolled)
}

export interface DrawBoardOptions {
  availableCells?: HighlightCell[];
  attackCells?: HighlightCell[];
  coverCells?: HighlightCell[];
  chargeCells?: HighlightCell[];
  advanceCells?: HighlightCell[]; // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Orange hexes
  blockedTargets?: Set<string>;
  coverTargets?: Set<string>;
  phase?: "move" | "shoot" | "charge" | "fight";
  interactionPhase?: "deployment" | "command" | "move" | "shoot" | "charge" | "fight";
  selectedUnitId?: number | null;
  mode?: string;
  showHexCoordinates?: boolean;
  objectiveControl?: ObjectiveControlMap;
  moveDestPoolRef?: React.RefObject<Set<string>>;
  /**
   * ``move_preview_footprint_zone`` : chaque sous-hex couvert par la preview — union d’hex **sans lacunes**
   * (contrairement au seul pool d’ancres). Utilisée comme masque du disque pour éviter les « plats »
   * entre disques d’empreinte près des murs / angles concaves.
   */
  footprintZonePoolRef?: React.RefObject<Set<string>>;
  /**
   * Ancres move/advance depuis game_state (repli si ``moveDestPoolRef`` vide). Le dessin des disques
   * privilégie **toujours** ``moveDestPoolRef`` quand elle est non vide — même principe que la charge.
   */
  moveDestinationAnchorsFromState?: unknown;
  /** Prioritaire sur ``selectedUnitBaseSize`` : span moteur (game_state.move_preview_footprint_span). */
  movePreviewFootprintSpanFromState?: number | null;
  /** Voir ``interactionPhase === "shoot"`` + ``movePoolRefsSync`` : pavage disques vs pastilles hex. */
  pendingMoveAfterShooting?: boolean;
  /** Ancres charge (même sémantique que ``moveDestPoolRef``) — preview multi-base comme la phase move. */
  chargeDestPoolRef?: React.RefObject<Set<string>>;
  selectedUnitBaseSize?: number;
  /**
   * (col, row) de l'unité dont on dessine la preview move / advance / post-shoot.
   *
   * Requis pour rendre la zone en **disque euclidien** (rayon calculé depuis le
   * centre de l'unité jusqu'au bord extérieur du BFS + demi-empreinte), masqué
   * par l'union des empreintes du pool — cercle net en terrain libre, tronqué
   * franchement par murs / EZ / pathfinding. Si absent ou si le pool est vide,
   * on retombe sur le pipeline union-de-disques historique.
   */
  selectedUnitAnchor?: { col: number; row: number } | null;
  /** Pre-built static board container (background + wall dots + objectives base). Reused across renders. */
  cachedStaticBoard?: PIXI.Container | null;
  /** Pre-built wall segments container. Reused across renders. */
  cachedWalls?: PIXI.Container | null;
  losDebugShowRatio?: boolean;
  losDebugRatioByHex?: Record<string, number>;
  losDebugCoverRatio?: number;
  losDebugVisibilityMinRatio?: number;
  /** Halo violet (grand plateau) : centre sur la cible de charge, rayon ~ engagement_zone en pas hex. */
  chargeEngagementHalo?: {
    centerCol: number;
    centerRow: number;
    zoneHexSteps: number;
  };
  /** Preview combat : cercle euclidien (bord extérieur lissé par-dessus les pastilles hex). */
  fightEngagementRing?: {
    cx: number;
    cy: number;
    rInner: number;
    rOuter: number;
  };
  /**
   * Contours masque move (coord. monde), envoyés par l’API — prioritaires sur
   * ``footprintZonePoolRef`` (évite un gros JSON de milliers d’hex).
   */
  movePreviewFootprintMaskLoops?: number[][] | null;
}

export interface DrawBoardResult {
  baseHexContainer: PIXI.Container;
  wallsContainer: PIXI.Container | null;
  /** Conteneur ``name === "highlights"`` (hitArea, surbrillances, move preview, etc.). */
  highlightContainer: PIXI.Container;
}

type PixelPt = [number, number];

/** Cercle dont [p1,p2] est un diamètre. */
function circleFromDiameter(p1: PixelPt, p2: PixelPt): { cx: number; cy: number; r: number } {
  const cx = (p1[0] + p2[0]) / 2;
  const cy = (p1[1] + p2[1]) / 2;
  const r = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / 2;
  return { cx, cy, r };
}

/** Cercle circonscrit aux trois points (null si alignés). */
function circumcircleThroughThreePoints(
  p1: PixelPt,
  p2: PixelPt,
  p3: PixelPt
): { cx: number; cy: number; r: number } | null {
  const ax = p1[0];
  const ay = p1[1];
  const bx = p2[0];
  const by = p2[1];
  const cx = p3[0];
  const cy = p3[1];
  const d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
  if (Math.abs(d) < 1e-12) return null;
  const a2 = ax * ax + ay * ay;
  const b2 = bx * bx + by * by;
  const c2 = cx * cx + cy * cy;
  const ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d;
  const uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d;
  const r = Math.hypot(ux - ax, uy - ay);
  return { cx: ux, cy: uy, r };
}

/** Énumération paires/triples : gardé pour petits jeux de points uniquement. */
const MEC_BRUTE_MAX_POINTS = 120;

/** Enveloppe convexe (monotone chain). Le MEC d’un ensemble fini du plan est celui de son enveloppe. */
function convexHull2D(points: PixelPt[]): PixelPt[] {
  if (points.length <= 1) return points.slice();
  const sorted = [...points].sort((a, b) => (a[0] === b[0] ? a[1] - b[1] : a[0] - b[0]));
  const cross = (o: PixelPt, a: PixelPt, b: PixelPt) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: PixelPt[] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2]!, lower[lower.length - 1]!, p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }
  const upper: PixelPt[] = [];
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i]!;
    while (upper.length >= 2 && cross(upper[upper.length - 2]!, upper[upper.length - 1]!, p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

/**
 * Plus petit cercle contenant des points, par énumération paires/triples — sans récursion.
 */
function bruteForceSmallestEnclosingCirclePoints(points: PixelPt[]): {
  cx: number;
  cy: number;
  r: number;
} {
  const n = points.length;
  const EPS = 1e-6;
  if (n === 0) {
    return { cx: 0, cy: 0, r: 0 };
  }
  if (n === 1) {
    const p = points[0]!;
    return { cx: p[0], cy: p[1], r: 0 };
  }

  const containsAll = (c: { cx: number; cy: number; r: number }): boolean => {
    return points.every((p) => Math.hypot(p[0] - c.cx, p[1] - c.cy) <= c.r + EPS);
  };

  let best = { cx: 0, cy: 0, r: Number.POSITIVE_INFINITY };

  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const c = circleFromDiameter(points[i]!, points[j]!);
      if (containsAll(c) && c.r < best.r) {
        best = c;
      }
    }
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      for (let k = j + 1; k < n; k++) {
        const c = circumcircleThroughThreePoints(points[i]!, points[j]!, points[k]!);
        if (c !== null && containsAll(c) && c.r < best.r) {
          best = c;
        }
      }
    }
  }

  if (!Number.isFinite(best.r)) {
    let sx = 0;
    let sy = 0;
    for (const p of points) {
      sx += p[0];
      sy += p[1];
    }
    const cx = sx / n;
    const cy = sy / n;
    let mr = 0;
    for (const p of points) {
      mr = Math.max(mr, Math.hypot(p[0] - cx, p[1] - cy));
    }
    return { cx, cy, r: mr };
  }

  return best;
}

function trivialBoundaryCircle(R: PixelPt[]): { cx: number; cy: number; r: number } {
  if (R.length === 0) {
    return { cx: 0, cy: 0, r: -1 };
  }
  if (R.length === 1) {
    const p = R[0]!;
    return { cx: p[0], cy: p[1], r: 0 };
  }
  if (R.length === 2) {
    return circleFromDiameter(R[0]!, R[1]!);
  }
  const cc = circumcircleThroughThreePoints(R[0]!, R[1]!, R[2]!);
  if (cc !== null) return cc;
  const a = circleFromDiameter(R[0]!, R[1]!);
  const b = circleFromDiameter(R[0]!, R[2]!);
  const c = circleFromDiameter(R[1]!, R[2]!);
  return a.r >= b.r && a.r >= c.r ? a : b.r >= c.r ? b : c;
}

/**
 * Welzl sur `pts` mélangés — uniquement sur l’enveloppe (souvent ≤ quelques centaines de sommets).
 * Profondeur = nombre de points passés ; ne pas appeler avec des milliers de points.
 */
function welzlSmallestEnclosingCirclePoints(pts: PixelPt[]): { cx: number; cy: number; r: number } {
  const shuffled = pts.map((p) => [p[0], p[1]] as PixelPt);
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = (Math.random() * (i + 1)) | 0;
    const t = shuffled[i]!;
    shuffled[i] = shuffled[j]!;
    shuffled[j] = t;
  }
  const EPS = 1e-7;
  const inside = (p: PixelPt, c: { cx: number; cy: number; r: number }) =>
    c.r >= 0 && Math.hypot(p[0] - c.cx, p[1] - c.cy) <= c.r + EPS;

  const sec = (n: number, R: PixelPt[]): { cx: number; cy: number; r: number } => {
    if (n === 0 || R.length === 3) {
      return trivialBoundaryCircle(R);
    }
    const D = sec(n - 1, R);
    if (inside(shuffled[n - 1]!, D)) {
      return D;
    }
    return sec(n - 1, [...R, shuffled[n - 1]!]);
  };

  return sec(shuffled.length, []);
}

/**
 * MEC des centres d’hex, puis +hexRadius pour couvrir les disques comme les pastilles objectif.
 * Enveloppe convexe → même MEC qu’avec tous les centres ; Welzl seulement sur le contour (léger).
 */
function smallestEnclosingCircleForHexDisks(
  hexCenters: PixelPt[],
  hexRadius: number
): { cx: number; cy: number; r: number } {
  const n = hexCenters.length;
  if (n === 0) {
    return { cx: 0, cy: 0, r: 0 };
  }
  if (n === 1) {
    const p = hexCenters[0]!;
    return { cx: p[0], cy: p[1], r: hexRadius };
  }

  const hull = convexHull2D(hexCenters);
  const mecInput = hull.length >= 1 ? hull : hexCenters;

  let core: { cx: number; cy: number; r: number };
  if (mecInput.length <= MEC_BRUTE_MAX_POINTS) {
    core = bruteForceSmallestEnclosingCirclePoints(mecInput);
  } else {
    core = welzlSmallestEnclosingCirclePoints(mecInput);
  }

  return { cx: core.cx, cy: core.cy, r: core.r + hexRadius };
}

// Parse colors from config - same as Board.tsx
const parseColor = (colorStr: string): number => {
  return parseInt(colorStr.replace("0x", ""), 16);
};

/**
 * Phase move / charge : pool → disques d’empreinte → une ou plusieurs `RenderTexture` (tuiles) → sprites.
 *
 * - **Pas de repli** sur un `Graphics` brut : bornes invalides ou erreur → destruction, rien au stage.
 * - **Tuiles** : réponse aux plafonds GPU (4096 px / côté) — rendu nominal pour les grandes zones, pas un plan B graphique.
 *
 * `resolution` + `alphaMode` alignés sur le framebuffer ; **multisample désactivé** sur la RT
 * (MSAA sur RenderTexture = échecs GL fréquents → `catch` → aucun sprite, preview vide).
 */
/** Taille max d’un côté de tuile (limite texture WebGL courante). Au-delà on découpe en plusieurs RT. */
const FOOTPRINT_HIGHLIGHT_RT_MAX_DIM = 4096;

function addFootprintHighlightSprite(
  app: PIXI.Application,
  highlightContainer: PIXI.Container,
  gfx: PIXI.Graphics,
  alpha: number,
  displayName: string
): void {
  const lb = gfx.getLocalBounds();
  const bounds =
    lb.width > 0 && lb.height > 0 && Number.isFinite(lb.width) && Number.isFinite(lb.height)
      ? lb
      : gfx.getBounds();
  if (
    !Number.isFinite(bounds.width) ||
    !Number.isFinite(bounds.height) ||
    bounds.width <= 0 ||
    bounds.height <= 0
  ) {
    gfx.destroy();
    return;
  }
  const w = Math.ceil(bounds.width);
  const h = Math.ceil(bounds.height);
  const TILE = FOOTPRINT_HIGHLIGHT_RT_MAX_DIM;
  const tilesW = Math.max(1, Math.ceil(w / TILE));
  const tilesH = Math.max(1, Math.ceil(h / TILE));
  const createdSprites: PIXI.Sprite[] = [];
  const resolution = app.renderer.resolution;
  try {
    for (let j = 0; j < tilesH; j++) {
      for (let i = 0; i < tilesW; i++) {
        const tileLeft = i * TILE;
        const tileTop = j * TILE;
        const tw = Math.min(TILE, w - tileLeft);
        const th = Math.min(TILE, h - tileTop);
        const rt = PIXI.RenderTexture.create({
          width: tw,
          height: th,
          resolution,
          multisample: PIXI.MSAA_QUALITY.NONE,
          alphaMode: PIXI.ALPHA_MODES.PMA,
        });
        gfx.position.set(-bounds.x - tileLeft, -bounds.y - tileTop);
        app.renderer.render(gfx, { renderTexture: rt, clear: true });
        const sprite = new PIXI.Sprite(rt);
        sprite.name = tilesW === 1 && tilesH === 1 ? displayName : `${displayName}-t${i}-${j}`;
        sprite.position.set(bounds.x + tileLeft, bounds.y + tileTop);
        sprite.alpha = alpha;
        sprite.roundPixels = false;
        highlightContainer.addChild(sprite);
        createdSprites.push(sprite);
      }
    }
    gfx.destroy();
  } catch {
    // Échec silencieux du pipeline RT (contexte WebGL perdu, buffer, etc.) :
    // nettoyage des sprites partiels — pas de console (les erreurs « dures »
    // passent par throw ailleurs dans le flux move preview).
    for (const s of createdSprites) {
      s.destroy({ texture: true });
    }
    gfx.destroy();
  }
}

/** Contour extérieur lissé pour la preview d’engagement (combat) — plusieurs traits concentriques. */
function createFightEngagementRingSmoothOutline(
  cx: number,
  cy: number,
  rOuter: number,
  color: number
): PIXI.Graphics {
  const gfx = new PIXI.Graphics();
  gfx.name = "fight-engagement-ring-smooth";
  appendFeatheredCircleOutlineStrokes(gfx, cx, cy, rOuter, color);
  return gfx;
}

type FeatherLayer = { width: number; alpha: number; useHighlightStroke?: boolean };

/**
 * Traits concentriques anti-alias (même logique que halo charge / anneau combat).
 * Réduit le crénelage du bord des disques de preview move/charge.
 */
function appendFeatheredCircleOutlineStrokes(
  gfx: PIXI.Graphics,
  cx: number,
  cy: number,
  r: number,
  color: number,
  layers?: FeatherLayer[]
): void {
  const hi = Math.min(0xffffff, ((color & 0xfefefe) >> 1) + 0x282828);
  const defaultLayers: FeatherLayer[] = layers ?? [
    { width: Math.max(5, Math.min(14, r * 0.018)), alpha: 0.1 },
    { width: 2.6, alpha: 0.34 },
    { width: 1.05, alpha: 0.8, useHighlightStroke: true },
  ];
  for (const layer of defaultLayers) {
    const strokeColor = layer.useHighlightStroke ? hi : color;
    gfx.lineStyle(layer.width, strokeColor, layer.alpha);
    gfx.drawCircle(cx, cy, r);
  }
}

/** Au-delà, pas de contour (coût O(n) traits GPU → trop lent sur Board×10). */
const FOOTPRINT_POOL_OUTLINE_MAX_CENTERS = 160;

/**
 * Plafond strict du nombre de `drawCircle` poussés dans un unique `PIXI.Graphics`
 * pour le remplissage des pools move / charge.
 *
 * Pixi génère ~40 sommets par cercle : au-delà de ~1500 disques, on dépasse la
 * capacité du buffer d'indices 16 bits (65 535) et le rendu `RenderTexture`
 * échoue silencieusement — résultat : aucun sprite lissé, seul un autre layer
 * (contours / hit-areas / cellules hex en fallback) reste visible, d'où la
 * perception d'un "preview en hex" au lieu d'un disque.
 *
 * Le footprint des pools `move` est typiquement `(BASE_SIZE/2) * HEX_HORIZ_SPACING`,
 * soit plusieurs fois l'inter-cellule → la décimation par grille est sans
 * conséquence visuelle (les disques conservés recouvrent largement les sautés).
 */
const FOOTPRINT_POOL_MAX_CIRCLES = 1500;

/**
 * Cellule de bord du pool : au moins un de ses 6 voisins (flat-top avec offset
 * de colonnes impaires vers le bas) est absent du pool.
 *
 * On garde **toutes** les cellules de bord intactes lors de la décimation pour
 * préserver la frontière visible de la zone d'empreinte ; seul l'intérieur est
 * sous-échantillonné.
 */
function isPoolBoundaryCell(c: number, r: number, pool: Set<string>): boolean {
  const neighbours: Array<[number, number]> =
    c % 2 === 0
      ? [
          [c, r - 1],
          [c, r + 1],
          [c - 1, r - 1],
          [c - 1, r],
          [c + 1, r - 1],
          [c + 1, r],
        ]
      : [
          [c, r - 1],
          [c, r + 1],
          [c - 1, r],
          [c - 1, r + 1],
          [c + 1, r],
          [c + 1, r + 1],
        ];
  for (const [nc, nr] of neighbours) {
    if (!pool.has(`${nc},${nr}`)) return true;
  }
  return false;
}

/**
 * Pousse les disques d'empreinte d'un pool dans un `PIXI.Graphics` unique.
 *
 * - **Un seul `beginFill` / `endFill`** pour tous les cercles (≪ 6 000 changements
 *   d'état Pixi sur un pool dense, cause directe de la perte silencieuse du
 *   contexte WebGL / du rendu `RenderTexture` vide observée en phase move).
 * - **Cap `FOOTPRINT_POOL_MAX_CIRCLES`** avec décimation `(c + r) % stride === 0`
 *   + préservation systématique des cellules de bord — couverture strictement
 *   équivalente tant que `footprintRadius ≥ stride · max(HEX_HORIZ_SPACING,
 *   HEX_VERT_SPACING)`, condition toujours vraie pour les pools move / charge
 *   réels où `footprintRadius ≫ spacing`.
 */
function fillFootprintPoolCircles(
  gfx: PIXI.Graphics,
  pool: Set<string>,
  footprintRadius: number,
  fillColor: number,
  HEX_HORIZ_SPACING: number,
  HEX_WIDTH: number,
  HEX_HEIGHT: number,
  HEX_VERT_SPACING: number,
  MARGIN: number
): number {
  const stride =
    pool.size > FOOTPRINT_POOL_MAX_CIRCLES
      ? Math.max(2, Math.ceil(pool.size / FOOTPRINT_POOL_MAX_CIRCLES))
      : 1;
  gfx.beginFill(fillColor, 1.0);
  let drawn = 0;
  for (const key of pool) {
    const sep = key.indexOf(",");
    const c = Number(key.substring(0, sep));
    const r = Number(key.substring(sep + 1));
    if (stride > 1 && (c + r) % stride !== 0 && !isPoolBoundaryCell(c, r, pool)) {
      continue;
    }
    const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const hy = r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
    gfx.drawCircle(hx, hy, footprintRadius);
    drawn++;
  }
  gfx.endFill();
  return drawn;
}

/**
 * Contour léger au-dessus du remplissage union des empreintes (move / charge).
 * Un seul trait par centre + seuil : évite 2–3× drawCircle par centre (très lent au redraw).
 */
function addFootprintPoolSmoothOutlines(
  highlightContainer: PIXI.Container,
  pool: Set<string>,
  footprintRadius: number,
  HEX_HORIZ_SPACING: number,
  HEX_WIDTH: number,
  HEX_HEIGHT: number,
  HEX_VERT_SPACING: number,
  MARGIN: number,
  color: number
): void {
  if (pool.size === 0 || footprintRadius <= 0) return;
  if (pool.size > FOOTPRINT_POOL_OUTLINE_MAX_CENTERS) {
    return;
  }

  const gfx = new PIXI.Graphics();
  gfx.name = "footprint-pool-smooth-outline";
  gfx.eventMode = "none";
  gfx.alpha = 0.32;
  const strokeW = Math.max(1.0, Math.min(2.4, footprintRadius * 0.038));
  gfx.lineStyle(strokeW, color, 0.16);
  for (const key of pool) {
    const sep = key.indexOf(",");
    const c = Number(key.substring(0, sep));
    const r = Number(key.substring(sep + 1));
    const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
    const hy = r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
    gfx.drawCircle(hx, hy, footprintRadius);
  }
  highlightContainer.addChild(gfx);
}

/** Aire signée d'un polygone fermé plat ``[x0,y0,…]`` (coords écran, y bas). */
function signedPolygonAreaFlat(flat: number[]): number {
  const n = flat.length / 2;
  if (n < 3) return 0;
  let a = 0;
  for (let i = 0; i < n; i++) {
    const i0 = i * 2;
    const i1 = ((i + 1) % n) * 2;
    a += flat[i0]! * flat[i1 + 1]! - flat[i1]! * flat[i0 + 1]!;
  }
  return a / 2;
}

function loopCentroidFlat(flat: number[]): [number, number] {
  let sx = 0;
  let sy = 0;
  const n = flat.length / 2;
  if (n === 0) return [0, 0];
  for (let i = 0; i < flat.length; i += 2) {
    sx += flat[i]!;
    sy += flat[i + 1]!;
  }
  return [sx / n, sy / n];
}

/** Test point dans polygone fermé (ray casting). */
function pointInPolygonFlat(x: number, y: number, flat: number[]): boolean {
  let inside = false;
  const n = flat.length / 2;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = flat[i * 2]!;
    const yi = flat[i * 2 + 1]!;
    const xj = flat[j * 2]!;
    const yj = flat[j * 2 + 1]!;
    if (yi > y !== yj > y) {
      const xInt = ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi;
      if (x < xInt) inside = !inside;
    }
  }
  return inside;
}

/**
 * Remplissage blanc opacité 1 pour masque alpha : union de composantes,
 * trous Pixi (``beginHole``) lorsque le centroïde d'une boucle est strictement
 * inclus dans une boucle plus grande (donut / lacune).
 */
function appendWhiteReachableMaskFromSmoothedLoops(
  maskGfx: PIXI.Graphics,
  loops: number[][]
): void {
  const valid = loops.filter((l) => l.length >= 6);
  if (valid.length === 0) return;

  const meta = valid.map((flat) => {
    const [cx, cy] = loopCentroidFlat(flat);
    return { flat, cx, cy, absA: Math.abs(signedPolygonAreaFlat(flat)) };
  });

  const used = new Set<number>();
  while (used.size < meta.length) {
    let bestI = -1;
    let bestAbs = -1;
    for (let i = 0; i < meta.length; i++) {
      if (used.has(i)) continue;
      if (meta[i]!.absA > bestAbs) {
        bestAbs = meta[i]!.absA;
        bestI = i;
      }
    }
    if (bestI < 0) break;
    const root = meta[bestI]!;
    used.add(bestI);

    maskGfx.beginFill(0xffffff, 1.0);
    maskGfx.drawPolygon(root.flat);
    for (let j = 0; j < meta.length; j++) {
      if (used.has(j) || j === bestI) continue;
      const o = meta[j]!;
      if (pointInPolygonFlat(o.cx, o.cy, root.flat)) {
        maskGfx.beginHole();
        maskGfx.drawPolygon(o.flat);
        maskGfx.endHole();
        used.add(j);
      }
    }
    maskGfx.endFill();
  }
}

/** Boucles masque monde ou union hex — résolues une fois (drawBoard + rendu) pour éviter un double ``tryBuild``. */
interface MovePreviewMaskGeometryResolved {
  kind: "server_loops" | "polygon";
  loopsBeforeSmooth: number[][];
}

function countMoveAdvanceMaskPreSmoothVertices(loopsBeforeSmooth: number[][]): number {
  let n = 0;
  for (const flat of loopsBeforeSmooth) {
    n += flat.length >> 1;
  }
  return n;
}

type MoveAdvanceMaskSmoothingTier = "small" | "medium" | "enormous";

/**
 * Même découpe que Chaikin / blur : somme des sommets avant Chaikin
 * (``MOVE_ADVANCE_MASK_CHAIKIN_VERTS_SMALL_MAX`` / ``MEDIUM_MAX``).
 */
function resolveMoveAdvanceMaskSmoothingTier(
  loopsBeforeSmooth: number[][]
): MoveAdvanceMaskSmoothingTier {
  const v = countMoveAdvanceMaskPreSmoothVertices(loopsBeforeSmooth);
  if (v <= MOVE_ADVANCE_MASK_CHAIKIN_VERTS_SMALL_MAX) {
    return "small";
  }
  if (v <= MOVE_ADVANCE_MASK_CHAIKIN_VERTS_MEDIUM_MAX) {
    return "medium";
  }
  return "enormous";
}

interface MoveAdvanceMaskAlphaBlurProfile {
  strength: number;
  quality: number;
  resolution: number;
}

function resolveMoveAdvanceMaskAlphaBlurProfileForTier(
  tier: MoveAdvanceMaskSmoothingTier
): MoveAdvanceMaskAlphaBlurProfile {
  switch (tier) {
    case "small":
      return {
        strength: MOVE_ADVANCE_MASK_ALPHA_BLUR_STRENGTH_SMALL_ZONE,
        quality: MOVE_ADVANCE_MASK_ALPHA_BLUR_QUALITY_SMALL_ZONE,
        resolution: MOVE_ADVANCE_MASK_ALPHA_BLUR_RESOLUTION_SMALL_ZONE,
      };
    case "medium":
      return {
        strength: MOVE_ADVANCE_MASK_ALPHA_BLUR_STRENGTH_MEDIUM_ZONE,
        quality: MOVE_ADVANCE_MASK_ALPHA_BLUR_QUALITY_MEDIUM_ZONE,
        resolution: MOVE_ADVANCE_MASK_ALPHA_BLUR_RESOLUTION_MEDIUM_ZONE,
      };
    default:
      return {
        strength: MOVE_ADVANCE_MASK_ALPHA_BLUR_STRENGTH_ENORMOUS_ZONE,
        quality: MOVE_ADVANCE_MASK_ALPHA_BLUR_QUALITY_ENORMOUS_ZONE,
        resolution: MOVE_ADVANCE_MASK_ALPHA_BLUR_RESOLUTION_ENORMOUS_ZONE,
      };
  }
}

/**
 * Petites zones → 5 passes (historique), moyennes → 4, énormes → 3 (moins de sommets, bord encore lisse).
 * Basé sur la somme des sommets des boucles **avant** Chaikin (seuils nommés ``MOVE_ADVANCE_MASK_CHAIKIN_VERTS_*``).
 */
function resolveMoveAdvanceMaskChaikinIterations(loopsBeforeSmooth: number[][]): number {
  const tier = resolveMoveAdvanceMaskSmoothingTier(loopsBeforeSmooth);
  if (tier === "small") {
    return MOVE_ADVANCE_MASK_CHAIKIN_ITERS_SMALL_ZONE;
  }
  if (tier === "medium") {
    return MOVE_ADVANCE_MASK_CHAIKIN_ITERS_MEDIUM_ZONE;
  }
  return MOVE_ADVANCE_MASK_CHAIKIN_ITERS_ENORMOUS_ZONE;
}

/**
 * Priorité API (boucles monde), sinon ``tryBuildHexUnionMaskPolygons`` depuis le pool d’hex empreinte.
 * Mêmes erreurs explicites que l’ancien chemin dans ``renderMoveAdvanceDestPoolCircleLayer``.
 */
function resolveMovePreviewMaskLoopsBeforeSmooth(
  precomputedWorldMaskLoops: number[][] | null,
  footprintMaskHexPool: Set<string> | null,
  gridHexRadius: number,
  HEX_HORIZ_SPACING: number,
  HEX_WIDTH: number,
  HEX_HEIGHT: number,
  HEX_VERT_SPACING: number,
  MARGIN: number,
  spriteName: string,
  anchorPoolSize: number
): MovePreviewMaskGeometryResolved {
  if (precomputedWorldMaskLoops && precomputedWorldMaskLoops.length > 0) {
    return { kind: "server_loops", loopsBeforeSmooth: precomputedWorldMaskLoops };
  }
  if (footprintMaskHexPool && footprintMaskHexPool.size > 0) {
    const layout = {
      HEX_HORIZ_SPACING,
      HEX_WIDTH,
      HEX_HEIGHT,
      HEX_VERT_SPACING,
      MARGIN,
      gridHexRadius,
    };
    const polyMask = tryBuildHexUnionMaskPolygons(footprintMaskHexPool, layout);
    if (!polyMask) {
      throw new Error(
        `[resolveMovePreviewMaskLoopsBeforeSmooth] tryBuildHexUnionMaskPolygons a échoué ` +
          `(spriteName=${spriteName}, footprintMaskHexPool.size=${footprintMaskHexPool.size})`
      );
    }
    return { kind: "polygon", loopsBeforeSmooth: polyMask.loops };
  }
  throw new Error(
    `[resolveMovePreviewMaskLoopsBeforeSmooth] aucune source de masque empreinte disponible ` +
      `(spriteName=${spriteName}, anchorPool.size=${anchorPoolSize})`
  );
}

/**
 * Preview **move / advance / post-shoot** : même **lissage** qu'avant (masque
 * blanc → RT → ``BlurFilter`` sur l'alpha → ``Sprite`` masque).
 * Le calque coloré n'est plus un **disque** euclidien mais un **rectangle** qui
 * couvre exactement les bornes du masque : la silhouette visible suit le
 * polygone d'union (BFS / empreinte), pas un arc de cercle sur les côtés plats.
 *
 * **Pas de repli silencieux** : sources invalides, échec render → ``throw``.
 * Au-delà de ``FOOTPRINT_HIGHLIGHT_RT_MAX_DIM`` sur un côté : tuiles (même principe que
 * ``addFootprintHighlightSprite``) : plusieurs RT ≤ 4096 + ``BlurFilter`` par tuile.
 * Couverture : une paire ``Sprite`` masque + ``Graphics`` par tuile (masque alpha fiable Pixi).
 * Jointures : léger risque de couture d’alpha aux bords de tuile (blur sans recouvrement).
 */
function renderMoveAdvanceDestPoolCircleLayer(
  parentContainer: PIXI.Container,
  app: PIXI.Application,
  anchorPool: Set<string>,
  footprintRadius: number,
  poolFillColor: number,
  spriteName: string,
  maskGeometry: MovePreviewMaskGeometryResolved
): void {
  if (anchorPool.size === 0) {
    throw new Error(
      `[renderMoveAdvanceDestPoolCircleLayer] anchorPool vide (spriteName=${spriteName})`
    );
  }
  if (!(footprintRadius > 0) || !Number.isFinite(footprintRadius)) {
    throw new Error(
      `[renderMoveAdvanceDestPoolCircleLayer] footprintRadius invalide (${footprintRadius}, spriteName=${spriteName})`
    );
  }

  const maskUnionKind = maskGeometry.kind;
  const loopsBeforeSmooth = maskGeometry.loopsBeforeSmooth;
  const smoothingTier = resolveMoveAdvanceMaskSmoothingTier(loopsBeforeSmooth);
  const chaikinIterations = resolveMoveAdvanceMaskChaikinIterations(loopsBeforeSmooth);
  const alphaBlurProfile = resolveMoveAdvanceMaskAlphaBlurProfileForTier(smoothingTier);

  const loopsFpPreSmooth = fingerprintPrecomputedMaskLoops(loopsBeforeSmooth);
  const TILE_DIM = FOOTPRINT_HIGHLIGHT_RT_MAX_DIM;

  const softMaskKey = buildMovePreviewSoftMaskCacheKey({
    v: MOVE_PREVIEW_SOFT_MASK_CACHE_VERSION,
    res: app.renderer.resolution,
    rw: app.renderer.width,
    rh: app.renderer.height,
    kind: maskUnionKind,
    loopsFp: loopsFpPreSmooth,
    bs: alphaBlurProfile.strength,
    bq: alphaBlurProfile.quality,
    br: alphaBlurProfile.resolution,
    chai: chaikinIterations,
    mvmax: MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS,
  });

  const softHitBase =
    movePreviewSoftMaskCache != null &&
    movePreviewSoftMaskCache.key === softMaskKey &&
    movePreviewSoftMaskCache.softTileRts.length > 0 &&
    !movePreviewSoftMaskCache.softTileRts.some((r) => r.destroyed);

  const softHitGridOk =
    softHitBase &&
    movePreviewSoftMaskCache != null &&
    (() => {
      const c = movePreviewSoftMaskCache;
      const mb = c.maskBounds;
      const iw = Math.ceil(mb.width);
      const ih = Math.ceil(mb.height);
      const needW = Math.max(1, Math.ceil(iw / TILE_DIM));
      const needH = Math.max(1, Math.ceil(ih / TILE_DIM));
      return (
        needW === c.tilesW && needH === c.tilesH && c.softTileRts.length === c.tilesW * c.tilesH
      );
    })();

  const softHit = Boolean(softHitBase && softHitGridOk);

  if (!softHit || !movePreviewSoftMaskCache) {
    disposeMovePreviewSoftMaskCache();

    const prep = smoothMaskLoopsForRender(
      loopsBeforeSmooth,
      chaikinIterations,
      moveAdvanceMaskSmoothOptions
    );
    const smoothedLoops = prep.smoothed;
    const validLoops = smoothedLoops.filter((loop) => loop.length >= 6);
    if (validLoops.length === 0) {
      throw new Error(
        `[renderMoveAdvanceDestPoolCircleLayer] polygone lissé vide ` +
          `(spriteName=${spriteName}, maskUnionKind=${maskUnionKind}, ` +
          `loopsCount=${smoothedLoops.length})`
      );
    }

    const maskGfx = new PIXI.Graphics();
    maskGfx.name = `${spriteName}-mask-gfx`;
    maskGfx.eventMode = "none";
    appendWhiteReachableMaskFromSmoothedLoops(maskGfx, validLoops);

    const maskBounds = maskGfx.getLocalBounds();
    if (
      !Number.isFinite(maskBounds.width) ||
      !Number.isFinite(maskBounds.height) ||
      !(maskBounds.width > 0) ||
      !(maskBounds.height > 0)
    ) {
      maskGfx.destroy();
      throw new Error(
        `[renderMoveAdvanceDestPoolCircleLayer] bornes du masque invalides ` +
          `(w=${maskBounds.width}, h=${maskBounds.height}, spriteName=${spriteName}, ` +
          `maskUnionKind=${maskUnionKind})`
      );
    }

    const w = Math.ceil(maskBounds.width);
    const h = Math.ceil(maskBounds.height);
    const tilesW = Math.max(1, Math.ceil(w / TILE_DIM));
    const tilesH = Math.max(1, Math.ceil(h / TILE_DIM));
    const resolution = app.renderer.resolution;

    const softTileRts: PIXI.RenderTexture[] = [];
    try {
      for (let tj = 0; tj < tilesH; tj++) {
        for (let ti = 0; ti < tilesW; ti++) {
          const tileLeft = ti * TILE_DIM;
          const tileTop = tj * TILE_DIM;
          const tw = Math.min(TILE_DIM, w - tileLeft);
          const th = Math.min(TILE_DIM, h - tileTop);

          let rt: PIXI.RenderTexture;
          try {
            rt = PIXI.RenderTexture.create({
              width: tw,
              height: th,
              resolution,
              multisample: PIXI.MSAA_QUALITY.NONE,
              alphaMode: PIXI.ALPHA_MODES.PMA,
            });
          } catch (e) {
            throw new Error(
              `[renderMoveAdvanceDestPoolCircleLayer] création RenderTexture masque tuile échouée ` +
                `(spriteName=${spriteName}, tw=${tw}, th=${th}): ${String(e)}`
            );
          }

          maskGfx.position.set(-maskBounds.x - tileLeft, -maskBounds.y - tileTop);
          try {
            app.renderer.render(maskGfx, { renderTexture: rt, clear: true });
          } catch (e) {
            rt.destroy(true);
            throw new Error(
              `[renderMoveAdvanceDestPoolCircleLayer] render masque tuile → RT échoué ` +
                `(spriteName=${spriteName}, ti=${ti}, tj=${tj}): ${String(e)}`
            );
          }

          let rtSoft: PIXI.RenderTexture;
          try {
            rtSoft = PIXI.RenderTexture.create({
              width: tw,
              height: th,
              resolution,
              multisample: PIXI.MSAA_QUALITY.NONE,
              alphaMode: PIXI.ALPHA_MODES.PMA,
            });
          } catch (e) {
            rt.destroy(true);
            throw new Error(
              `[renderMoveAdvanceDestPoolCircleLayer] création RenderTexture masque lissé tuile échouée ` +
                `(spriteName=${spriteName}, tw=${tw}, th=${th}): ${String(e)}`
            );
          }

          const maskSourceSprite = new PIXI.Sprite(rt);
          maskSourceSprite.eventMode = "none";
          const maskAlphaBlur = new PIXI.BlurFilter(
            alphaBlurProfile.strength,
            alphaBlurProfile.quality
          );
          maskAlphaBlur.resolution = alphaBlurProfile.resolution;
          maskAlphaBlur.autoFit = true;
          maskSourceSprite.filters = [maskAlphaBlur];
          try {
            app.renderer.render(maskSourceSprite, { renderTexture: rtSoft, clear: true });
          } catch (e) {
            maskSourceSprite.destroy();
            rt.destroy(true);
            rtSoft.destroy(true);
            throw new Error(
              `[renderMoveAdvanceDestPoolCircleLayer] render masque lissé tuile → RT échoué ` +
                `(spriteName=${spriteName}, ti=${ti}, tj=${tj}): ${String(e)}`
            );
          }
          maskSourceSprite.destroy();
          rt.destroy(true);
          softTileRts.push(rtSoft);
        }
      }
    } catch (e) {
      for (const r of softTileRts) {
        if (!r.destroyed) {
          r.destroy(true);
        }
      }
      if (!maskGfx.destroyed) {
        maskGfx.destroy();
      }
      throw e instanceof Error ? e : new Error(String(e));
    }
    maskGfx.destroy();

    movePreviewSoftMaskCache = {
      key: softMaskKey,
      softTileRts,
      maskBounds: {
        x: maskBounds.x,
        y: maskBounds.y,
        width: maskBounds.width,
        height: maskBounds.height,
      },
      tilesW,
      tilesH,
    };
  }

  const smc = movePreviewSoftMaskCache;
  if (!smc) {
    throw new Error(
      `[renderMoveAdvanceDestPoolCircleLayer] cache soft masque absent après pipeline ` +
        `(spriteName=${spriteName})`
    );
  }

  appendMovePreviewMaskTilesAndCoverageToParent(
    parentContainer,
    spriteName,
    smc,
    TILE_DIM,
    poolFillColor
  );
}

/** Remplissage objectif : texture teintée ou couleur unie (même pipeline que les murs). */
function beginObjectiveFill(
  g: PIXI.Graphics,
  texture: PIXI.Texture | null,
  fillColor: number,
  alpha: number
): void {
  if (texture) {
    g.beginTextureFill({
      texture,
      alpha,
      color: fillColor,
    });
  } else {
    g.beginFill(fillColor, alpha);
  }
}

/**
 * Pure visual board rendering - NO INTERACTIONS
 * Used by both BoardReplay (simple call) and Board.tsx (with highlights)
 */
export const drawBoard = (
  app: PIXI.Application,
  boardConfig: BoardConfig,
  options?: DrawBoardOptions
): DrawBoardResult | undefined => {
  if (!boardConfig || !app.stage) return;

  try {
    detachMovePreviewLayerCacheFromStage();

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
    const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight!);
    const ATTACK_COLOR = parseColor(boardConfig.colors.attack!);
    const WALL_COLOR = parseColor(boardConfig.colors.wall!);
    /** Hex destinations fin de charge (do not use ``colors.charge`` here: that key is orange UI / bordures). */
    const CHARGE_DESTINATION_HEX_FILL = 0x9f7aea;
    /** Advance move destinations (ADVANCE_IMPLEMENTATION_PLAN — same as legacy ``0xff8c00``). */
    const ADVANCE_DESTINATION_HEX_FILL = 0xff8c00;

    // Extract options with defaults for replay viewer compatibility
    const {
      availableCells = [],
      attackCells = [],
      coverCells = [],
      chargeCells = [],
      advanceCells = [], // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4
      phase = "move",
      interactionPhase = phase,
      selectedUnitId = null,
      mode = "select",
      showHexCoordinates: _showHexCoordinates = false,
      objectiveControl = {},
      moveDestPoolRef,
      footprintZonePoolRef,
      moveDestinationAnchorsFromState,
      movePreviewFootprintSpanFromState,
      pendingMoveAfterShooting = false,
      chargeDestPoolRef,
      selectedUnitBaseSize,
      selectedUnitAnchor,
      losDebugShowRatio: _losDebugShowRatio = false,
      losDebugRatioByHex: _losDebugRatioByHex = {},
      losDebugCoverRatio: _losDebugCoverRatio = 0,
      losDebugVisibilityMinRatio: _losDebugVisibilityMinRatio = 0,
      chargeEngagementHalo,
      fightEngagementRing,
      movePreviewFootprintMaskLoops = null,
    } = options || {};

    // Parse objective control colors - use same colors as player units
    if (!boardConfig.colors.player_1) {
      throw new Error("Missing required configuration value: boardConfig.colors.player_1");
    }
    if (!boardConfig.colors.player_2) {
      throw new Error("Missing required configuration value: boardConfig.colors.player_2");
    }
    if (!boardConfig.colors.objective) {
      throw new Error("Missing required configuration value: boardConfig.colors.objective");
    }
    const OBJECTIVE_P0_COLOR = parseColor(boardConfig.colors.player_1);
    const OBJECTIVE_P1_COLOR = parseColor(boardConfig.colors.player_2);
    const OBJECTIVE_NEUTRAL_COLOR = parseColor(boardConfig.colors.objective);

    // Compute all objective hexes - use ONLY hexes from config, no expansion
    const objectiveHexSet = new Set<string>();
    let baseObjectives: Array<[number, number]> = boardConfig.objective_hexes || [];
    if (baseObjectives.length === 0 && Array.isArray(boardConfig.objective_zones)) {
      baseObjectives = boardConfig.objective_zones.flatMap((z) =>
        (z.hexes || []).map((h) =>
          Array.isArray(h) ? (h as [number, number]) : ([h.col, h.row] as [number, number])
        )
      );
    }

    for (const [objCol, objRow] of baseObjectives) {
      objectiveHexSet.add(`${objCol},${objRow}`);
    }

    /** Même rendu cercle + masque BFS que le move ; ne pas dépendre de ``interactionPhase === "shoot"`` (replay / mapping phase). */
    const useAdvanceMovePoolLikeMove = mode === "advancePreview";
    const usePostShootMovePoolLikeMove =
      interactionPhase === "shoot" && pendingMoveAfterShooting === true;
    const usePileInPoolLikeMoveHoisted =
      interactionPhase === "fight" && (mode === "pileInPreview" || mode === "consolidationPreview");
    const advanceZoneFillColor = ADVANCE_DESTINATION_HEX_FILL;
    const spanFromEngine =
      typeof movePreviewFootprintSpanFromState === "number" &&
      Number.isFinite(movePreviewFootprintSpanFromState) &&
      movePreviewFootprintSpanFromState >= 1
        ? Math.floor(movePreviewFootprintSpanFromState)
        : null;
    const footprintSpanForPool = Math.max(1, spanFromEngine ?? selectedUnitBaseSize ?? 1);

    const anchorsFromStatePool: Set<string> | null = (() => {
      if (moveDestinationAnchorsFromState == null) return null;
      const s = new Set<string>();
      addHexKeysToSet(moveDestinationAnchorsFromState, s);
      return s.size > 0 ? s : null;
    })();

    /**
     * Clic droit / désélection : ``syncMoveDestinationPoolRefs`` vide la ref tout de suite,
     * mais ``valid_move_destinations_pool`` peut rester dans le JSON jusqu’à la réponse API.
     * Sans ce garde-fou, ``movePoolForDiskDraw`` retombait sur le pool state → preview fantôme.
     */
    const allowMovePoolFallbackFromGameState =
      selectedUnitId != null ||
      mode === "advancePreview" ||
      (interactionPhase === "shoot" && pendingMoveAfterShooting) ||
      ((interactionPhase === "move" || interactionPhase === "command") && mode === "movePreview");

    /** Disques d’ancre : ``moveDestPoolRef`` en priorité (comme ``chargeDestPoolRef``), puis state si autorisé. */
    const movePoolForDiskDraw: Set<string> | null =
      moveDestPoolRef?.current && moveDestPoolRef.current.size > 0
        ? moveDestPoolRef.current
        : allowMovePoolFallbackFromGameState &&
            anchorsFromStatePool &&
            anchorsFromStatePool.size > 0
          ? anchorsFromStatePool
          : null;

    const useMoveDestPoolCircleLayer =
      (interactionPhase === "move" ||
        useAdvanceMovePoolLikeMove ||
        usePostShootMovePoolLikeMove ||
        usePileInPoolLikeMoveHoisted) &&
      !!movePoolForDiskDraw &&
      movePoolForDiskDraw.size > 0;

    if (!useMoveDestPoolCircleLayer) {
      disposeMovePreviewRenderCachesFull();
    }

    /** advancePreview sans pool : éviter — le pool vient de ``advance_destinations`` / ``valid_move_destinations_pool`` après ``action: "advance"``. */

    const cachedStaticBoard = options?.cachedStaticBoard ?? null;
    const reuseStatic = cachedStaticBoard !== null;
    const baseHexContainer = reuseStatic ? cachedStaticBoard : new PIXI.Container();
    const highlightContainer = new PIXI.Container();
    if (!reuseStatic) {
      baseHexContainer.name = "baseHexes";
    }
    highlightContainer.name = "highlights";
    /** Au-dessus de l’overlay LoS survol (BoardPvp, zIndex ~40), sous les unités (2000) et la ligne/icône de prévisualisation (~848–900). */
    highlightContainer.zIndex = 120;
    const TOTAL_WIDTH = BOARD_COLS * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + 2 * MARGIN;
    const TOTAL_HEIGHT = BOARD_ROWS * HEX_VERT_SPACING + HEX_VERT_SPACING / 2 + 2 * MARGIN;
    const backgroundImagePath = boardConfig.display?.background_image?.trim();
    const backgroundImageAlpha =
      typeof boardConfig.display?.background_image_alpha === "number"
        ? boardConfig.display.background_image_alpha
        : 0.85;
    const backgroundOverlayAlpha =
      typeof boardConfig.display?.background_overlay_alpha === "number"
        ? boardConfig.display.background_overlay_alpha
        : 0.18;
    const objectiveSmoothContour = boardConfig.display?.objective_smooth_contour ?? true;
    const objectiveTexturePath = boardConfig.display?.objective_texture?.trim();
    const objectiveTexture =
      objectiveTexturePath && objectiveTexturePath.length > 0
        ? PIXI.Texture.from(objectiveTexturePath)
        : null;
    const objectiveTextureAlpha =
      typeof boardConfig.display?.objective_texture_alpha === "number"
        ? boardConfig.display.objective_texture_alpha
        : 0.85;

    const objectiveHexFillAlpha =
      typeof boardConfig.display?.objective_hex_fill_alpha === "number"
        ? boardConfig.display.objective_hex_fill_alpha
        : objectiveTexture
          ? objectiveTextureAlpha
          : 0.5;

    const smoothRadiusRatio =
      typeof boardConfig.display?.objective_smooth_radius_ratio === "number"
        ? boardConfig.display.objective_smooth_radius_ratio
        : 1.0;

    if (!reuseStatic) {
      if (backgroundImagePath) {
        const bgSprite = PIXI.Sprite.from(backgroundImagePath);
        bgSprite.x = 0;
        bgSprite.y = 0;
        bgSprite.width = TOTAL_WIDTH;
        bgSprite.height = TOTAL_HEIGHT;
        bgSprite.alpha = backgroundImageAlpha;
        baseHexContainer.addChild(bgSprite);

        const bgOverlay = new PIXI.Graphics();
        bgOverlay.beginFill(parseColor(boardConfig.colors.cell_even), backgroundOverlayAlpha);
        bgOverlay.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
        bgOverlay.endFill();
        baseHexContainer.addChild(bgOverlay);
      } else {
        const bg = new PIXI.Graphics();
        bg.beginFill(parseColor(boardConfig.colors.cell_even), 1.0);
        bg.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
        bg.endFill();
        baseHexContainer.addChild(bg);
      }

      const wallDotRadius = HEX_RADIUS;
      const wallAltColor = (WALL_COLOR & 0xfefefe) + 0x101010;
      for (const [wc, wr] of boardConfig.wall_hexes || []) {
        const wx = wc * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const wy =
          wr * HEX_VERT_SPACING + ((wc % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        const wallDot = new PIXI.Graphics();
        const fill = wc % 2 === 0 ? WALL_COLOR : wallAltColor;
        wallDot.beginFill(fill, 1.0);
        wallDot.drawCircle(wx, wy, wallDotRadius);
        wallDot.endFill();
        baseHexContainer.addChild(wallDot);
      }

      if (objectiveSmoothContour && Array.isArray(boardConfig.objective_zones)) {
        const displayCfg = boardConfig.display;
        const ringColorStr =
          typeof displayCfg?.objective_zone_ring_color === "string" &&
          displayCfg.objective_zone_ring_color.length > 0
            ? displayCfg.objective_zone_ring_color
            : boardConfig.colors.objective;
        const ringColorParsed = parseColor(ringColorStr);
        const ringAlpha =
          typeof displayCfg?.objective_zone_ring_alpha === "number"
            ? displayCfg.objective_zone_ring_alpha
            : typeof displayCfg?.objective_smooth_alpha === "number"
              ? displayCfg.objective_smooth_alpha
              : 0.35;
        const ringWidth =
          typeof displayCfg?.objective_zone_ring_width === "number"
            ? displayCfg.objective_zone_ring_width
            : Math.max(1.2, HEX_RADIUS * 0.22);
        const centerColorStr =
          typeof displayCfg?.objective_zone_center_color === "string" &&
          displayCfg.objective_zone_center_color.length > 0
            ? displayCfg.objective_zone_center_color
            : boardConfig.colors.objective;
        const centerColorParsed = parseColor(centerColorStr);
        const centerAlpha =
          typeof displayCfg?.objective_zone_center_alpha === "number"
            ? displayCfg.objective_zone_center_alpha
            : 0.5;
        const centerRadiusRatio =
          typeof displayCfg?.objective_zone_center_radius_ratio === "number"
            ? displayCfg.objective_zone_center_radius_ratio
            : 0.14;

        for (const zone of boardConfig.objective_zones) {
          const zoneHexes = zone.hexes || [];
          if (!Array.isArray(zoneHexes) || zoneHexes.length === 0) continue;

          const zoneCells: Array<[number, number]> = [];
          for (const h of zoneHexes) {
            const oc = Array.isArray(h) ? Number(h[0]) : Number((h as { col: number }).col);
            const or_ = Array.isArray(h) ? Number(h[1]) : Number((h as { row: number }).row);
            if (!Number.isFinite(oc) || !Number.isFinite(or_)) continue;
            zoneCells.push([oc, or_]);
          }
          if (zoneCells.length === 0) continue;

          const hexCenters: PixelPt[] = [];
          for (const [col, row] of zoneCells) {
            const hcx = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
            const hcy =
              row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
            hexCenters.push([hcx, hcy]);
          }

          const mec = smallestEnclosingCircleForHexDisks(hexCenters, HEX_RADIUS);
          if (
            Number.isFinite(mec.cx) &&
            Number.isFinite(mec.cy) &&
            Number.isFinite(mec.r) &&
            mec.r >= 0
          ) {
            const outerR = Math.max(0, mec.r * smoothRadiusRatio);
            const innerR = Math.max(0.5, outerR * centerRadiusRatio);

            const smoothZone = new PIXI.Graphics();
            smoothZone.lineStyle(ringWidth, ringColorParsed, ringAlpha);
            smoothZone.drawCircle(mec.cx, mec.cy, outerR);
            smoothZone.lineStyle(0);
            smoothZone.beginFill(centerColorParsed, centerAlpha);
            smoothZone.drawCircle(mec.cx, mec.cy, innerR);
            smoothZone.endFill();
            baseHexContainer.addChild(smoothZone);
          }
        }
      }

      for (const [oc, or_] of baseObjectives) {
        const ox = oc * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const oy =
          or_ * HEX_VERT_SPACING + ((oc % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        const hexKey = `${oc},${or_}`;
        const controller = objectiveControl[hexKey];
        let objColor = OBJECTIVE_NEUTRAL_COLOR;
        if (controller === 1) objColor = OBJECTIVE_P0_COLOR;
        else if (controller === 2) objColor = OBJECTIVE_P1_COLOR;
        const objDot = new PIXI.Graphics();
        beginObjectiveFill(objDot, objectiveTexture, objColor, objectiveHexFillAlpha);
        objDot.drawCircle(ox, oy, HEX_RADIUS);
        objDot.endFill();
        baseHexContainer.addChild(objDot);
      }
    }

    // Build clickable set for hit detection
    const clickableSet = new Set<string>();
    // Charge (pool selection): activation is unit-driven (boardUnitClick → left_click). Green
    // eligible hex highlights must stay non-interactive: the full-screen hitArea is above unit
    // sprites and would steal clicks while boardHexClick has no charge+select branch.
    if (!(interactionPhase === "charge" && mode === "select")) {
      for (const c of availableCells) clickableSet.add(`${c.col},${c.row}`);
    }
    for (const c of chargeCells) {
      const cc = Array.isArray(c) ? c[0] : (c as { col: number }).col;
      const cr = Array.isArray(c) ? c[1] : (c as { row: number }).row;
      clickableSet.add(`${cc},${cr}`);
    }
    for (const c of advanceCells) clickableSet.add(`${c.col},${c.row}`);

    // Évite les tableaux énormes de surbrillance move ; charge peut dépasser 500 hex (Board×10).
    const LARGE_POOL_THRESHOLD = 500;

    // Pile in : zone rouge (empreinte moteur) — comme move_preview_footprint_zone en forme,
    // pas seulement des disques aux ancres ; on dessine via ``availableCells`` (override).
    // Dès que le moteur fournit valid_move_destinations_pool : un disque par ancre (cercle),
    // pas un remplissage hex-par-hex de move_preview_footprint_zone (blob « hex géant » si BASE_SIZE
    // tuple/oval et selectedUnitBaseSize était undefined).
    const useConsolidationPreview = interactionPhase === "fight" && mode === "consolidationPreview";
    const availableCellsDrawColor = useAdvanceMovePoolLikeMove
      ? advanceZoneFillColor
      : usePileInPoolLikeMoveHoisted
        ? useConsolidationPreview
          ? 0xff8c00
          : ATTACK_COLOR
        : HIGHLIGHT_COLOR;

    const useChargeDestPoolDiskDraw =
      interactionPhase === "charge" &&
      (mode === "select" || mode === "chargePreview") &&
      chargeDestPoolRef?.current &&
      chargeDestPoolRef.current.size > 0;

    /** Move / advance / pile-in / post-shoot move : disques d’empreinte (comme la charge), pas des pastilles rayon hex (= grille « en hex »). */
    const useFootprintDiskRadiusForAvailCells =
      interactionPhase === "move" ||
      useAdvanceMovePoolLikeMove ||
      usePileInPoolLikeMoveHoisted ||
      usePostShootMovePoolLikeMove;
    const availableCellCircleR = useFootprintDiskRadiusForAvailCells
      ? (footprintSpanForPool / 2) * HEX_HORIZ_SPACING
      : HEX_RADIUS;

    const drawGroup = (
      cells: Array<{ col: number; row: number }>,
      color: number,
      alpha: number,
      skipThreshold = true,
      circleRadius: number = HEX_RADIUS
    ) => {
      if (cells.length === 0) return;
      if (skipThreshold && cells.length > LARGE_POOL_THRESHOLD) return;
      const batch = new PIXI.Graphics();
      // Un beginFill/endFill par cercle : sinon Pixi fusionne les sous-chemins en un seul polygone
      // rempli (« hex géant » / blob au lieu de pastilles distinctes).
      for (const c of cells) {
        const hx = c.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const hy =
          c.row * HEX_VERT_SPACING + ((c.col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        batch.beginFill(color, alpha);
        batch.drawCircle(hx, hy, circleRadius);
        batch.endFill();
      }
      highlightContainer.addChild(batch);
    };

    if (useMoveDestPoolCircleLayer && movePoolForDiskDraw) {
      const footprintRadius = (footprintSpanForPool / 2) * HEX_HORIZ_SPACING;
      const poolFillColor = useAdvanceMovePoolLikeMove ? advanceZoneFillColor : HIGHLIGHT_COLOR;
      const moveSpriteName = useAdvanceMovePoolLikeMove
        ? "advance-dest-pool"
        : usePileInPoolLikeMoveHoisted
          ? "fight-pile-in-dest-pool"
          : "move-dest-pool";
      // Preview move/advance : masque polygone (Chaikin) + blur alpha comme avant ;
      // calque coloré = rectangle sur les bornes du masque (plus de disque).
      // Pas de fallback : si ``selectedUnitAnchor`` absent, bug côté caller (BoardPvp).
      if (selectedUnitAnchor == null) {
        throw new Error(
          "[drawBoard] ``selectedUnitAnchor`` requis pour rendre le layer move/advance — " +
            `absent alors que useMoveDestPoolCircleLayer=true (spriteName=${moveSpriteName})`
        );
      }
      const footprintMaskHexPool =
        footprintZonePoolRef?.current && footprintZonePoolRef.current.size > 0
          ? footprintZonePoolRef.current
          : null;

      const poolHash = hashStringSetStable(movePoolForDiskDraw);
      const footprintPoolHash =
        footprintMaskHexPool && footprintMaskHexPool.size > 0
          ? hashStringSetStable(footprintMaskHexPool)
          : null;
      const loopsFp = fingerprintPrecomputedMaskLoops(movePreviewFootprintMaskLoops ?? null);

      const movePreviewCacheKey = JSON.stringify({
        v: MOVE_PREVIEW_LAYER_RENDER_CACHE_VERSION,
        res: app.renderer.resolution,
        ip: interactionPhase,
        mo: mode,
        pms: pendingMoveAfterShooting,
        sn: moveSpriteName,
        ph: poolHash,
        psz: movePoolForDiskDraw.size,
        fph: footprintPoolHash,
        fpsz: footprintMaskHexPool?.size ?? 0,
        lf: loopsFp,
        ghr: HEX_RADIUS,
        fr: footprintRadius,
        pfc: poolFillColor,
        ac: selectedUnitAnchor.col,
        ar: selectedUnitAnchor.row,
        fsp: footprintSpanForPool,
        sp: {
          hhs: HEX_HORIZ_SPACING,
          hw: HEX_WIDTH,
          hh: HEX_HEIGHT,
          hvs: HEX_VERT_SPACING,
          mg: MARGIN,
        },
        mvmax: MOVE_ADVANCE_MASK_CHAIKIN_MAX_VERTS,
        covA: MOVE_PREVIEW_COVERAGE_FILL_ALPHA,
      });

      const cachedEntry = movePreviewLayerRenderCache;
      const canReuse =
        cachedEntry != null &&
        !cachedEntry.root.destroyed &&
        cachedEntry.key === movePreviewCacheKey;

      if (canReuse) {
        highlightContainer.addChild(cachedEntry.root);
      } else {
        disposeMovePreviewLayerRootCache();
        const preNorm =
          movePreviewFootprintMaskLoops != null && movePreviewFootprintMaskLoops.length > 0
            ? movePreviewFootprintMaskLoops
            : null;
        const maskGeom = resolveMovePreviewMaskLoopsBeforeSmooth(
          preNorm,
          footprintMaskHexPool,
          HEX_RADIUS,
          HEX_HORIZ_SPACING,
          HEX_WIDTH,
          HEX_HEIGHT,
          HEX_VERT_SPACING,
          MARGIN,
          moveSpriteName,
          movePoolForDiskDraw.size
        );
        const cacheRoot = new PIXI.Container();
        cacheRoot.name = "move-preview-layer-cache-root";
        cacheRoot.eventMode = "none";
        renderMoveAdvanceDestPoolCircleLayer(
          cacheRoot,
          app,
          movePoolForDiskDraw,
          footprintRadius,
          poolFillColor,
          moveSpriteName,
          maskGeom
        );
        movePreviewLayerRenderCache = { key: movePreviewCacheKey, root: cacheRoot };
        highlightContainer.addChild(cacheRoot);
      }
    } else {
      // Short-circuit uniquement si ``availableCells`` est vide côté caller : en phase déploiement
      // (mappée ``interactionPhase === "move"``), le pool de déploiement est légitimement poussé
      // dans ``availableCells`` et doit être dessiné comme des disques (aucune ancre côté moteur).
      const moveOrAdvanceNoAnchors =
        (interactionPhase === "move" ||
          useAdvanceMovePoolLikeMove ||
          usePostShootMovePoolLikeMove) &&
        !movePoolForDiskDraw &&
        availableCells.length === 0;
      const cellsForHighlight = moveOrAdvanceNoAnchors ? [] : availableCells;
      drawGroup(cellsForHighlight, availableCellsDrawColor, 0.4, false, availableCellCircleR);
    }
    {
      const useShootingPreviewPalette = interactionPhase === "shoot" || mode === "movePreview";
      if (useShootingPreviewPalette && (attackCells.length > 0 || coverCells.length > 0)) {
        const coverKeySet = new Set(coverCells.map((c) => `${c.col},${c.row}`));
        const attackClearOnly = attackCells.filter((c) => !coverKeySet.has(`${c.col},${c.row}`));
        const losUnionLayout: HexUnionMaskLayout = {
          HEX_HORIZ_SPACING,
          HEX_WIDTH,
          HEX_HEIGHT,
          HEX_VERT_SPACING,
          MARGIN,
          gridHexRadius: HEX_RADIUS,
        };
        const losRoot = new PIXI.Container();
        losRoot.name = "los-preview-smooth-hex-union";
        losRoot.eventMode = "none";
        const allLosCells = [...coverCells, ...attackClearOnly];
        mountLosPolarClippedByVisibleUnion(
          losRoot,
          allLosCells,
          coverCells,
          losUnionLayout,
          0x4f8bff,
          0.4,
          0x9ec5ff,
          0.4,
          app.renderer
        );
        highlightContainer.addChild(losRoot);
      } else {
        drawGroup(attackCells, ATTACK_COLOR, 0.4, false);
      }
    }
    if (useChargeDestPoolDiskDraw && chargeDestPoolRef?.current) {
      const footprintRadius = (footprintSpanForPool / 2) * HEX_HORIZ_SPACING;
      const chargeGfx = new PIXI.Graphics();
      chargeGfx.name = "charge-dest-pool-gfx";
      const chargePool = chargeDestPoolRef.current;
      fillFootprintPoolCircles(
        chargeGfx,
        chargePool,
        footprintRadius,
        CHARGE_DESTINATION_HEX_FILL,
        HEX_HORIZ_SPACING,
        HEX_WIDTH,
        HEX_HEIGHT,
        HEX_VERT_SPACING,
        MARGIN
      );
      addFootprintHighlightSprite(app, highlightContainer, chargeGfx, 0.28, "charge-dest-pool");
      addFootprintPoolSmoothOutlines(
        highlightContainer,
        chargePool,
        footprintRadius,
        HEX_HORIZ_SPACING,
        HEX_WIDTH,
        HEX_HEIGHT,
        HEX_VERT_SPACING,
        MARGIN,
        CHARGE_DESTINATION_HEX_FILL
      );
    } else {
      drawGroup(
        chargeCells.map((c: HighlightCell | [number, number]) => ({
          col: Array.isArray(c) ? c[0] : c.col,
          row: Array.isArray(c) ? c[1] : c.row,
        })),
        CHARGE_DESTINATION_HEX_FILL,
        0.4,
        false
      );
    }
    if (
      advanceCells.length > 0 &&
      !(mode === "advancePreview" && useMoveDestPoolCircleLayer && movePoolForDiskDraw)
    ) {
      drawGroup(advanceCells, ADVANCE_DESTINATION_HEX_FILL, 0.3, false);
    }

    if (
      chargeEngagementHalo &&
      typeof chargeEngagementHalo.zoneHexSteps === "number" &&
      chargeEngagementHalo.zoneHexSteps > 1 &&
      Number.isFinite(chargeEngagementHalo.centerCol) &&
      Number.isFinite(chargeEngagementHalo.centerRow)
    ) {
      const hcx = chargeEngagementHalo.centerCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const hcy =
        chargeEngagementHalo.centerRow * HEX_VERT_SPACING +
        ((chargeEngagementHalo.centerCol % 2) * HEX_VERT_SPACING) / 2 +
        HEX_HEIGHT / 2 +
        MARGIN;
      const ringGfx = new PIXI.Graphics();
      ringGfx.name = "charge-engagement-halo";
      const haloR = chargeEngagementHalo.zoneHexSteps * HEX_HORIZ_SPACING;
      const haloColor = CHARGE_DESTINATION_HEX_FILL;
      // Plusieurs traits superposés (large + léger → fin + opaque) : bord moins crénelé sous CanvasRenderer.
      const haloLayers: Array<{ width: number; alpha: number }> = [
        { width: 14, alpha: 0.06 },
        { width: 7, alpha: 0.14 },
        { width: 3, alpha: 0.32 },
      ];
      for (const layer of haloLayers) {
        ringGfx.lineStyle(layer.width, haloColor, layer.alpha);
        ringGfx.drawCircle(hcx, hcy, haloR);
      }
      highlightContainer.addChild(ringGfx);
    }

    const moveAdvanceOrPileInPickPool: Set<string> | null = (() => {
      if (
        interactionPhase === "move" ||
        useAdvanceMovePoolLikeMove ||
        usePostShootMovePoolLikeMove
      ) {
        return movePoolForDiskDraw && movePoolForDiskDraw.size > 0 ? movePoolForDiskDraw : null;
      }
      if (usePileInPoolLikeMoveHoisted) {
        if (moveDestPoolRef?.current && moveDestPoolRef.current.size > 0) {
          return moveDestPoolRef.current;
        }
        return null;
      }
      return null;
    })();

    // Invisible interactive overlay for click detection (pixelToHex nearest-neighbor)
    const hasClickableContent =
      clickableSet.size > 0 ||
      (moveAdvanceOrPileInPickPool != null && moveAdvanceOrPileInPickPool.size > 0) ||
      (interactionPhase === "charge" &&
        mode === "chargePreview" &&
        chargeDestPoolRef?.current &&
        chargeDestPoolRef.current.size > 0);
    if (hasClickableContent) {
      const hitArea = new PIXI.Graphics();
      hitArea.beginFill(0, 0);
      hitArea.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
      hitArea.endFill();
      hitArea.hitArea = new PIXI.Rectangle(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
      hitArea.eventMode = "static";
      hitArea.cursor = "pointer";

      const resolveHex = (pos: PIXI.IPointData): { col: number; row: number } => {
        const ux = pos.x - MARGIN;
        const uy = pos.y - MARGIN;
        const colApprox = (ux - HEX_WIDTH / 2) / HEX_HORIZ_SPACING;
        const c0 = Math.max(0, Math.floor(colApprox) - 2);
        const c1 = Math.min(BOARD_COLS - 1, Math.ceil(colApprox) + 2);
        let bestCol = 0,
          bestRow = 0,
          bestD = Infinity;
        for (let c = c0; c <= c1; c++) {
          const stagger = ((c % 2) * HEX_VERT_SPACING) / 2;
          const rowApprox = (uy - HEX_HEIGHT / 2 - stagger) / HEX_VERT_SPACING;
          const r0 = Math.max(0, Math.floor(rowApprox) - 2);
          const r1 = Math.min(BOARD_ROWS - 1, Math.ceil(rowApprox) + 2);
          for (let r = r0; r <= r1; r++) {
            const cx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2;
            const cy = r * HEX_VERT_SPACING + stagger + HEX_HEIGHT / 2;
            const d = (ux - cx) ** 2 + (uy - cy) ** 2;
            if (d < bestD) {
              bestD = d;
              bestCol = c;
              bestRow = r;
            }
          }
        }
        return { col: bestCol, row: bestRow };
      };

      hitArea.on(
        "pointerdown",
        asPixiUnknownArgsPointerListener((e: PIXI.FederatedPointerEvent) => {
          if (e.button !== 0) return;
          const { col, row } = resolveHex(e.getLocalPosition(hitArea));
          const key = `${col},${row}`;
          const useMovePoolForPick =
            moveAdvanceOrPileInPickPool != null && moveAdvanceOrPileInPickPool.size > 0;
          const useChargePoolForPick =
            interactionPhase === "charge" &&
            mode === "chargePreview" &&
            chargeDestPoolRef?.current &&
            chargeDestPoolRef.current.size > 0;
          const isValid =
            clickableSet.has(key) ||
            (useMovePoolForPick && (moveAdvanceOrPileInPickPool?.has(key) ?? false)) ||
            (useChargePoolForPick && (chargeDestPoolRef?.current?.has(key) ?? false));
          if (isValid) {
            const isHandledByBoardPvpCapture =
              selectedUnitId !== null &&
              ((interactionPhase === "move" && mode === "select") ||
                mode === "advancePreview" ||
                (interactionPhase === "charge" && mode === "chargePreview") ||
                (interactionPhase === "fight" &&
                  (mode === "pileInPreview" || mode === "consolidationPreview")));
            if (isHandledByBoardPvpCapture) {
              return;
            }

            let destCol = col,
              destRow = row;
            if (
              useMovePoolForPick &&
              moveAdvanceOrPileInPickPool &&
              !moveAdvanceOrPileInPickPool.has(key)
            ) {
              let bestDist = Infinity;
              for (const k of moveAdvanceOrPileInPickPool) {
                const sep = k.indexOf(",");
                const cc = Number(k.substring(0, sep));
                const cr = Number(k.substring(sep + 1));
                const d = (cc - col) * (cc - col) + (cr - row) * (cr - row);
                if (d < bestDist) {
                  bestDist = d;
                  destCol = cc;
                  destRow = cr;
                }
              }
            } else if (
              useChargePoolForPick &&
              chargeDestPoolRef?.current &&
              !chargeDestPoolRef.current.has(key)
            ) {
              let bestDist = Infinity;
              for (const k of chargeDestPoolRef.current) {
                const sep = k.indexOf(",");
                const cc = Number(k.substring(0, sep));
                const cr = Number(k.substring(sep + 1));
                const d = (cc - col) * (cc - col) + (cr - row) * (cr - row);
                if (d < bestDist) {
                  bestDist = d;
                  destCol = cc;
                  destRow = cr;
                }
              }
            }
            window.dispatchEvent(
              new CustomEvent("boardHexClick", {
                detail: {
                  col: destCol,
                  row: destRow,
                  phase: interactionPhase,
                  mode,
                  selectedUnitId,
                },
              })
            );
          }
        })
      );

      let lastHoverCol = -1,
        lastHoverRow = -1;
      hitArea.on(
        "pointermove",
        asPixiUnknownArgsPointerListener((e: PIXI.FederatedPointerEvent) => {
          const localPos = e.getLocalPosition(hitArea);
          const { col, row } = resolveHex(localPos);
          const hexChanged = col !== lastHoverCol || row !== lastHoverRow;
          if (hexChanged) {
            lastHoverCol = col;
            lastHoverRow = row;
          }
          window.dispatchEvent(
            new CustomEvent("boardHexHover", {
              detail: { col, row, pixelX: localPos.x, pixelY: localPos.y, hexChanged },
            })
          );
        })
      );

      highlightContainer.addChild(hitArea);
    }

    if (
      fightEngagementRing &&
      Number.isFinite(fightEngagementRing.rOuter) &&
      fightEngagementRing.rOuter > 1 &&
      Number.isFinite(fightEngagementRing.cx) &&
      Number.isFinite(fightEngagementRing.cy)
    ) {
      highlightContainer.addChild(
        createFightEngagementRingSmoothOutline(
          fightEngagementRing.cx,
          fightEngagementRing.cy,
          fightEngagementRing.rOuter,
          ATTACK_COLOR
        )
      );
    }

    // Caller (BoardPvp) handles stage cleanup. drawBoard only adds containers.

    if (!reuseStatic) {
      app.stage.addChildAt(baseHexContainer, 0);
    }
    app.stage.addChild(highlightContainer);

    // Render wall segments as filled polygons.
    // Skip if reusing static layers (walls are already on stage).
    let wallsResult: PIXI.Container | null = null;
    if (!reuseStatic && boardConfig.walls && boardConfig.walls.length > 0) {
      const wallsContainer = new PIXI.Container();
      wallsContainer.name = "walls";

      const halfW = HEX_HEIGHT * 0.8;
      const wallTexturePath = boardConfig.display?.wall_texture?.trim() || "/textures/wall1.webp";
      const wallTextureAlpha =
        typeof boardConfig.display?.wall_texture_alpha === "number"
          ? boardConfig.display.wall_texture_alpha
          : 1.0;
      const wallTexture = PIXI.Texture.from(wallTexturePath);

      const toPixel = (col: number, row: number): [number, number] => [
        col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN,
        row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN,
      ];

      boardConfig.walls.forEach((wall) => {
        const [sx, sy] = toPixel(wall.start.col, wall.start.row);
        const [ex, ey] = toPixel(wall.end.col, wall.end.row);

        const dx = ex - sx,
          dy = ey - sy;
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len < 0.01) return;
        const nx = (-dy / len) * halfW;
        const ny = (dx / len) * halfW;

        const g = new PIXI.Graphics();
        g.beginTextureFill({
          texture: wallTexture,
          alpha: wallTextureAlpha,
        });
        g.drawCircle(sx, sy, halfW);
        g.drawCircle(ex, ey, halfW);
        g.drawPolygon([sx + nx, sy + ny, ex + nx, ey + ny, ex - nx, ey - ny, sx - nx, sy - ny]);
        g.endFill();
        wallsContainer.addChild(g);
      });

      app.stage.addChild(wallsContainer);
      wallsResult = wallsContainer;
    }

    return { baseHexContainer, wallsContainer: wallsResult, highlightContainer };
  } catch (error) {
    console.error("❌ Error drawing board:", error);
    throw error;
  }
};
