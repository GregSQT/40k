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
  /** Niveau vertical (0 = sol). Tireur sur étage (>= 1) → voit par-dessus les murs. */
  level?: number;
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

/** Niveau (étage) par figurine de toutes les unités depuis ``gameState.units_cache`` (level_by_model). */
export function unitsCacheModelLevels(
  unitsCache: unknown
): Record<string, Record<string, number> | undefined> | undefined {
  const uc = unitsCache as
    | Record<string, { level_by_model?: Record<string, number> }>
    | null
    | undefined;
  if (!uc) return undefined;
  const out: Record<string, Record<string, number> | undefined> = {};
  for (const [uid, entry] of Object.entries(uc)) {
    out[uid] = entry?.level_by_model;
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
  /** Niveau (étage) par figurine tireuse (``units_cache[uid].level_by_model``) — permet le cône
   * PAR figurine : une fig au sol reste bloquée par un mur, une fig de la même escouade sur l'étage
   * voit par-dessus les murs de sa ruine. Absent → cône au niveau unité (ancre). */
  shooterModelLevels?: Record<string, number>;
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

/** 6 voisins hex offset odd-q (miroir strict de engine.hex_utils.get_neighbors). */
function hexNeighborsOddQ(col: number, row: number): Array<[number, number]> {
  const odd = (col & 1) === 1;
  const offsets: Array<[number, number]> = odd
    ? [[0, -1], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0]]
    : [[0, -1], [1, -1], [1, 0], [0, 1], [-1, 0], [-1, -1]];
  return offsets.map(([dc, dr]) => [col + dc, row + dr] as [number, number]);
}

/** Retire de ``walls`` les murs situés dans l'empreinte des terrain area(s) intersectant le socle
 * tireur, ou adjacents à elles. Miroir de backend _walls_around_occupied_area (option A). */
function removeWallsAroundOccupiedArea(
  walls: Array<[number, number]>,
  shooterFootprint: Array<[number, number]>,
  terrainZones: Array<{ hexes: Array<[number, number]> }> | undefined
): Array<[number, number]> {
  if (!terrainZones || terrainZones.length === 0) return walls;
  const footprintKeys = new Set(shooterFootprint.map(([c, r]) => `${c},${r}`));
  const occupied = new Set<string>();
  for (const zone of terrainZones) {
    const zoneKeys = zone.hexes.map(([c, r]) => `${c},${r}`);
    if (zoneKeys.some((k) => footprintKeys.has(k))) {
      for (const k of zoneKeys) occupied.add(k);
    }
  }
  if (occupied.size === 0) return walls;
  const halo = new Set(occupied);
  for (const k of occupied) {
    const [c, r] = k.split(",").map(Number);
    for (const [nc, nr] of hexNeighborsOddQ(c, r)) halo.add(`${nc},${nr}`);
  }
  return walls.filter(([c, r]) => !halo.has(`${c},${r}`));
}

export function buildLosPreviewFromSource(
  params: BuildLosPreviewFromSourceParams
): LosPreviewFromSource {
  const baseWallHexes = buildEffectiveLosWallHexes(
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
  // Cône PAR figurine (règle 06.01) : chaque groupe = (empreinte, murs effectifs). Les figs au sol
  // partagent baseWallHexes ; une fig sur un étage (niveau >= 1) retire les murs de SA ruine (miroir
  // backend _walls_around_occupied_area). Une case est visible si AU MOINS une figurine la voit →
  // union des cônes. Ainsi une fig au sol reste bloquée par un mur qu'une coéquipière sur l'étage
  // ne subit plus, et le cône reflète bien la LoS des figurines élevées.
  type ShooterConeGroup = { footprint: Array<[number, number]>; walls: Array<[number, number]> };
  const shooterGroups: ShooterConeGroup[] = [];
  const modelLevels = params.shooterModelLevels;
  if (centers && modelLevels && Object.keys(centers).length > 0) {
    const groundFootprint: Array<[number, number]> = [];
    for (const [mid, center] of Object.entries(centers)) {
      const fpKeys = squadFootprintHexKeysFromModelCenters({ [mid]: center }, params.source.unit);
      const modelFp: Array<[number, number]> = fpKeys
        ? Array.from(fpKeys).map((k) => {
            const [c, r] = k.split(",").map(Number);
            return [c, r] as [number, number];
          })
        : [center];
      if ((modelLevels[mid] ?? 0) >= 1) {
        shooterGroups.push({
          footprint: modelFp,
          walls: removeWallsAroundOccupiedArea(baseWallHexes, modelFp, params.terrainZones),
        });
      } else {
        groundFootprint.push(...modelFp);
      }
    }
    if (groundFootprint.length > 0) {
      shooterGroups.push({ footprint: groundFootprint, walls: baseWallHexes });
    }
  } else {
    // Position hypothétique (survol) ou pas de niveaux par-figurine → cône au niveau unité (ancre).
    const wallsUnit =
      (params.source.unit.level ?? 0) >= 1
        ? removeWallsAroundOccupiedArea(baseWallHexes, shooterFootprint, params.terrainZones)
        : baseWallHexes;
    shooterGroups.push({ footprint: shooterFootprint, walls: wallsUnit });
  }
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
  // Union des cônes par groupe. L'état d'une case (clear=1 / cover=2) ne dépend que du terrain, pas
  // du tireur → dédup par (col,row) sans conflit d'état.
  const rawByKey = new Map<string, VisibleHex>();
  for (const group of shooterGroups) {
    const groupRaw = computeVisibleHexes(
      params.source.fromCol,
      params.source.fromRow,
      scanRange,
      params.boardCols,
      params.boardRows,
      group.walls,
      obscuringHexes,
      terrainHexes,
      group.footprint
    );
    for (const h of groupRaw) rawByKey.set(`${h.col},${h.row}`, h);
  }
  const visibleHexesRaw = Array.from(rawByKey.values());
  const effectiveWallHexes = baseWallHexes;
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
  // Signature des murs effectifs par groupe (varie avec les niveaux par-figurine) → re-mémoïse le
  // cône si un niveau change sans que la position bouge.
  const groupsWallKey = shooterGroups
    .map((g) => stableWallHexKey(g.walls))
    .sort()
    .join("~");
  const key = [
    params.source.fromCol,
    params.source.fromRow,
    params.maxRange,
    metric,
    shooterCentersKey,
    params.boardCols,
    params.boardRows,
    groupsWallKey,
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
