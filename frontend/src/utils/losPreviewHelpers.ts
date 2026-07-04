import {
  computeOccupiedHexes,
  euclideanEdgeDistanceToCellSubhex,
  resolveBaseSizeForUnitDisplay,
  squadFootprintHexKeysFromModelCenters,
  unitFootprintHexKeys,
} from "./hexFootprint";
import { computeVisibleHexes, type VisibleHex } from "./wasmLos";

/** Même cube-odd-r que ``BoardPvp.hexDistOff`` (empreinte / scan). */
export function hexDistOff(c1: number, r1: number, c2: number, r2: number): number {
  const x1 = c1,
    z1 = r1 - ((c1 - (c1 & 1)) >> 1),
    y1 = -x1 - z1;
  const x2 = c2,
    z2 = r2 - ((c2 - (c2 & 1)) >> 1),
    y2 = -x2 - z2;
  return Math.max(Math.abs(x1 - x2), Math.abs(y1 - y2), Math.abs(z1 - z2));
}

export interface MinimalUnitForLos {
  id: number | string;
  player: number;
  col: number;
  row: number;
  BASE_SHAPE?: "round" | "oval" | "square";
  /** Aligné sur ``Unit.BASE_SIZE`` (nombre ou tuple rare). */
  BASE_SIZE?: number | [number, number];
}

/** Map unitId → positions par-figurine (miroir ``units_cache.occupied_hexes_by_model``). */
export type UnitsCacheModelCenters = Record<string, Record<string, [number, number]> | undefined>;

/** Extrait les positions par-figurine de toutes les unités depuis ``gameState.units_cache``. */
export function unitsCacheModelCenters(unitsCache: unknown): UnitsCacheModelCenters | undefined {
  const uc = unitsCache as
    | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
    | null
    | undefined;
  if (!uc) return undefined;
  const out: UnitsCacheModelCenters = {};
  for (const [uid, entry] of Object.entries(uc)) {
    out[uid] = entry?.occupied_hexes_by_model;
  }
  return out;
}

export interface WallHexOverrideForLos {
  col: number;
  row: number;
}

export interface BuildLosPreviewFromSourceParams {
  source: {
    unit: MinimalUnitForLos;
    fromCol: number;
    fromRow: number;
  };
  units: MinimalUnitForLos[];
  boardCols: number;
  boardRows: number;
  wallHexes: Array<[number, number]> | undefined;
  wallHexesOverride?: WallHexOverrideForLos[];
  /** Obscuring terrain areas (rule 13.10). One entry = one area; hexes in subhex board coords. */
  obscuringZones?: Array<{ hexes: Array<[number, number]> }>;
  /** All terrain areas (obscuring or not) — a visible hex inside one is drawn as cover. */
  terrainZones?: Array<{ hexes: Array<[number, number]> }>;
  maxRange: number;
  /** Métrique de portée (sélecteur backend). Défaut "hex" = comportement historique. */
  distanceMetric?: "hex" | "euclidean";
  /** Positions par-figurine du TIREUR (``occupied_hexes_by_model``) — à fournir quand la
   * source est à la position courante de l'unité : empreinte = union des socles de toutes
   * les figurines (miroir backend ``_resolve_unit_anchor_and_footprint``). Absent →
   * socle unique recalculé à fromCol/fromRow (position hypothétique de survol). */
  shooterModelCenters?: Record<string, [number, number]>;
  /** Positions par-figurine par unité — blink cible par modèle (règle 06.01). */
  unitsCacheByModel?: UnitsCacheModelCenters;
}

/** Extrait la métrique de portée tir depuis le game_config brut (défaut "hex"). */
export function rangedPreviewMetric(gameConfig: unknown): "hex" | "euclidean" {
  const dm = (gameConfig as { distance_metric?: { ranged?: string } } | null | undefined)
    ?.distance_metric?.ranged;
  return dm === "euclidean" ? "euclidean" : "hex";
}

export interface LosPreviewFromSource {
  visibleHexes: VisibleHex[];
  clearCells: Array<{ col: number; row: number }>;
  terrainCoverCells: Array<{ col: number; row: number }>;
  visibleHexKeySet: Set<string>;
  blinkIds: number[];
  coverByUnitId: Record<string, boolean>;
  effectiveWallHexes: Array<[number, number]>;
  key: string;
}

function stableBoolRecordJson(m: Record<string, boolean>): string {
  const keys = Object.keys(m).sort();
  const sorted: Record<string, boolean> = {};
  for (const k of keys) {
    sorted[k] = m[k] === true;
  }
  return JSON.stringify(sorted);
}

function stableWallHexKey(wallHexes: Array<[number, number]>): string {
  return wallHexes
    .map(([c, r]) => `${c},${r}`)
    .sort()
    .join(";");
}

/** Memo signature of the static obscuring layout (areaId:col,row per hex). */
function stableObscuringKey(obscuringHexes: Array<[number, number, number]>): string {
  return obscuringHexes
    .map(([c, r, a]) => `${a}:${c},${r}`)
    .sort()
    .join(";");
}

/** Memo signature of the static terrain-area hexes (col,row). */
function stableTerrainKey(terrainHexes: Array<[number, number]>): string {
  return terrainHexes
    .map(([c, r]) => `${c},${r}`)
    .sort()
    .join(";");
}

export function buildEffectiveLosWallHexes(
  boardCols: number,
  boardRows: number,
  wallHexes: Array<[number, number]> | undefined,
  wallHexesOverride?: WallHexOverrideForLos[]
): Array<[number, number]> {
  const effectiveWallHexes: Array<[number, number]> = wallHexesOverride
    ? wallHexesOverride.map((h) => [h.col, h.row] as [number, number])
    : wallHexes
      ? [...wallHexes]
      : [];
  const wallKeySet = new Set(effectiveWallHexes.map(([c, r]) => `${c},${r}`));
  const bottomRow = boardRows - 1;
  for (let col = 0; col < boardCols; col++) {
    if (col % 2 === 1 && !wallKeySet.has(`${col},${bottomRow}`)) {
      effectiveWallHexes.push([col, bottomRow]);
    }
  }
  return effectiveWallHexes;
}

/** Même logique que le survol move (``triggerLosForHex``) : terrain 1/2 + cibles / couverture par empreinte. */
export function buildShootingLosPreviewFromVisibleHexes(
  visibleHexes: VisibleHex[],
  units: MinimalUnitForLos[],
  shooterPlayer: number,
  unitsCacheByModel?: UnitsCacheModelCenters
): {
  clearCells: Array<{ col: number; row: number }>;
  terrainCoverCells: Array<{ col: number; row: number }>;
  visibleHexKeySet: Set<string>;
  blinkIds: number[];
  coverByUnitId: Record<string, boolean>;
} {
  const clearCells: Array<{ col: number; row: number }> = [];
  const terrainCoverCells: Array<{ col: number; row: number }> = [];
  const visibleHexKeySet = new Set<string>();

  for (const hex of visibleHexes) {
    const key = `${hex.col},${hex.row}`;
    visibleHexKeySet.add(key);
    if (hex.state === 1) {
      clearCells.push({ col: hex.col, row: hex.row });
    } else {
      terrainCoverCells.push({ col: hex.col, row: hex.row });
    }
  }

  const blinkIds: number[] = [];
  const coverByUnitId: Record<string, boolean> = {};

  for (const u of units) {
    if (u.player === shooterPlayer) continue;
    // Règle 06.01 (binaire par modèle) : l'unité blinke si >= 1 figurine a >= 1 cellule de
    // son socle visible. Positions par-figurine = units_cache.occupied_hexes_by_model ; sans
    // découpage par figurine (mono-figurine / cache absent), socle unique à l'ancre.
    const byModel = unitsCacheByModel?.[String(u.id)];
    const modelFootprints: Array<Set<string>> = [];
    if (byModel) {
      for (const [mid, pos] of Object.entries(byModel)) {
        const fp = squadFootprintHexKeysFromModelCenters({ [mid]: pos }, u);
        if (fp) modelFootprints.push(fp);
      }
    }
    if (modelFootprints.length === 0) {
      modelFootprints.push(unitFootprintHexKeys(u));
    }
    const isVisible = modelFootprints.some((fp) => {
      for (const k of fp) {
        if (visibleHexKeySet.has(k)) return true;
      }
      return false;
    });
    if (!isVisible) continue;
    const uid = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
    blinkIds.push(uid);
    coverByUnitId[String(u.id)] = false;
  }

  return {
    clearCells,
    terrainCoverCells,
    visibleHexKeySet,
    blinkIds,
    coverByUnitId,
  };
}

export function buildLosPreviewFromSource(
  params: BuildLosPreviewFromSourceParams
): LosPreviewFromSource {
  const effectiveWallHexes = buildEffectiveLosWallHexes(
    params.boardCols,
    params.boardRows,
    params.wallHexes,
    params.wallHexesOverride
  );
  // Flatten obscuring areas into [col,row,areaId] triplets (areaId = zone index + 1, >= 1).
  const obscuringHexes: Array<[number, number, number]> = [];
  if (params.obscuringZones) {
    for (let z = 0; z < params.obscuringZones.length; z++) {
      const areaId = z + 1;
      for (const [c, r] of params.obscuringZones[z].hexes) {
        obscuringHexes.push([c, r, areaId]);
      }
    }
  }
  // Flatten all terrain areas into [col,row] pairs (cover classification).
  const terrainHexes: Array<[number, number]> = [];
  if (params.terrainZones) {
    for (const zone of params.terrainZones) {
      for (const [c, r] of zone.hexes) {
        terrainHexes.push([c, r]);
      }
    }
  }
  // Empreinte tireur — obscuring areas it occupies never block (13.10). Position courante :
  // union des socles par-figurine du cache moteur (miroir backend). Position hypothétique :
  // socle unique recalculé à fromCol/fromRow.
  const shooterSize = resolveBaseSizeForUnitDisplay(params.source.unit);
  const centers = params.shooterModelCenters;
  const cacheFpKeys =
    centers && Object.keys(centers).length > 0
      ? squadFootprintHexKeysFromModelCenters(centers, params.source.unit)
      : null;
  const shooterFootprint: Array<[number, number]> = cacheFpKeys
    ? Array.from(cacheFpKeys).map((k) => {
        const [c, r] = k.split(",").map(Number);
        return [c, r] as [number, number];
      })
    : shooterSize > 1
      ? computeOccupiedHexes(params.source.fromCol, params.source.fromRow, "round", shooterSize)
      : [[params.source.fromCol, params.source.fromRow]];
  // Portée : "hex" = gate hex du WASM (historique) ; "euclidean" = on élargit le scan WASM
  // (padding = étendue hex de l'empreinte + 1) puis on filtre par distance bord-à-bord
  // euclidienne exacte (miroir backend ranged_edge_distance_to_cell). Le WASM reste un pur
  // calculateur de LoS.
  const metric = params.distanceMetric ?? "hex";
  const footprintPad =
    shooterFootprint.reduce(
      (m, [c, r]) => Math.max(m, hexDistOff(params.source.fromCol, params.source.fromRow, c, r)),
      0
    ) + 1;
  const scanRange = metric === "euclidean" ? params.maxRange + footprintPad : params.maxRange;
  const visibleHexesRaw = computeVisibleHexes(
    params.source.fromCol,
    params.source.fromRow,
    scanRange,
    params.boardCols,
    params.boardRows,
    effectiveWallHexes,
    obscuringHexes,
    terrainHexes,
    shooterFootprint
  );
  const visibleHexes =
    metric === "euclidean"
      ? visibleHexesRaw.filter(
          (h) =>
            euclideanEdgeDistanceToCellSubhex(
              params.source.fromCol,
              params.source.fromRow,
              shooterSize,
              h.col,
              h.row
            ) <= params.maxRange
        )
      : visibleHexesRaw;
  const losPreview = buildShootingLosPreviewFromVisibleHexes(
    visibleHexes,
    params.units,
    params.source.unit.player,
    params.unitsCacheByModel
  );
  const shooterCentersKey = centers
    ? Object.entries(centers)
        .map(([mid, [c, r]]) => `${mid}:${c},${r}`)
        .sort()
        .join(";")
    : "";
  const key = [
    params.source.fromCol,
    params.source.fromRow,
    params.maxRange,
    metric,
    shooterCentersKey,
    params.boardCols,
    params.boardRows,
    stableWallHexKey(effectiveWallHexes),
    stableObscuringKey(obscuringHexes),
    stableTerrainKey(terrainHexes),
    [...losPreview.blinkIds].sort((a, b) => a - b).join(","),
    stableBoolRecordJson(losPreview.coverByUnitId),
  ].join("|");
  return {
    visibleHexes,
    clearCells: losPreview.clearCells,
    terrainCoverCells: losPreview.terrainCoverCells,
    visibleHexKeySet: losPreview.visibleHexKeySet,
    blinkIds: losPreview.blinkIds,
    coverByUnitId: losPreview.coverByUnitId,
    effectiveWallHexes,
    key,
  };
}
