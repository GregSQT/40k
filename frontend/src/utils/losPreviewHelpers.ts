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
  /** Niveau (étage) actuellement AFFICHÉ (currentLevel). Si >= 1, les cases vues EN PLUS par les
   * figs sur cet étage (murs de leur ruine ignorés) sont renvoyées dans ``elevatedCells`` (vert).
   * Au niveau 0 (défaut), aucun overlay : cône normal, murs bloquent. */
  viewLevel?: number;
  /** Floors (délimitations d'étage) individuels avec leurs hexes, par niveau — pour retirer les
   * murs bordant le floor précis qu'une fig occupe (granularité floor, pas terrain area sol). */
  terrainFloors?: Array<{ level: number; hexes: Array<[number, number]> }>;
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
  /** Cases vues EN PLUS grâce aux figs sur l'étage AFFICHÉ (murs de leur ruine ignorés), à peindre
   * en VERT. Vide au niveau 0 ou si aucune fig sur l'étage affiché. */
  elevatedCells: Array<{ col: number; row: number }>;
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
    ? [
        [0, -1],
        [1, 0],
        [1, 1],
        [0, 1],
        [-1, 1],
        [-1, 0],
      ]
    : [
        [0, -1],
        [1, -1],
        [1, 0],
        [0, 1],
        [-1, 0],
        [-1, -1],
      ];
  return offsets.map(([dc, dr]) => [col + dc, row + dr] as [number, number]);
}

/** Retire de ``walls`` les murs bordant la délimitation du FLOOR (au niveau ``level``) que le socle
 * tireur occupe. Granularité floor (pas terrain area sol) : une même area peut porter 2 floors au même
 * niveau (décors A/B) → une fig sur A n'ignore que les murs de A. Halo de voisins (les murs bordent le
 * floor, souvent juste à l'extérieur du rasterisé), scoppé au floor → aucun mur d'un autre décor.
 * Miroir backend _walls_around_occupied_floor. */
function removeWallsAroundOccupiedFloor(
  walls: Array<[number, number]>,
  shooterFootprint: Array<[number, number]>,
  terrainFloors: Array<{ level: number; hexes: Array<[number, number]> }> | undefined,
  level: number
): Array<[number, number]> {
  if (!terrainFloors || terrainFloors.length === 0) return walls;
  const footprintKeys = new Set(shooterFootprint.map(([c, r]) => `${c},${r}`));
  const occupied = new Set<string>();
  for (const floor of terrainFloors) {
    if (floor.level !== level) continue;
    const floorKeys = floor.hexes.map(([c, r]) => `${c},${r}`);
    if (floorKeys.some((k) => footprintKeys.has(k))) {
      for (const k of floorKeys) occupied.add(k);
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
  const inMaxRange = (h: { col: number; row: number }): boolean =>
    metric !== "euclidean" ||
    euclideanEdgeDistanceToCellSubhex(
      params.source.fromCol,
      params.source.fromRow,
      shooterSize,
      h.col,
      h.row
    ) <= params.maxRange;
  // Cône « au sol » (BASE, bleu) : TOUS les murs bloquent, empreinte complète de l'unité. C'est le
  // cône normal, indépendant du niveau affiché.
  const effectiveWallHexes = baseWallHexes;
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
  // Overlay VERT « vue par l'étage » : UNIQUEMENT si le niveau AFFICHÉ (viewLevel) >= 1. Pour chaque
  // figurine SUR cet étage (niveau == viewLevel), on retire les murs de sa ruine et on garde les
  // cases vues EN PLUS de la base (celles que la vue au sol ne voit pas). « quand une fig est
  // dessus » = niveau de la fig == niveau affiché. Au niveau 0, aucun mur ignoré → aucun vert.
  const viewLevel = params.viewLevel ?? 0;
  const modelLevels = params.shooterModelLevels;
  const elevatedCells: Array<{ col: number; row: number }> = [];
  if (viewLevel >= 1 && centers && modelLevels) {
    const baseKeys = new Set(visibleHexesRaw.map((h) => `${h.col},${h.row}`));
    const elevByKey = new Map<string, VisibleHex>();
    for (const [mid, center] of Object.entries(centers)) {
      if ((modelLevels[mid] ?? 0) !== viewLevel) continue;
      const fpKeys = squadFootprintHexKeysFromModelCenters({ [mid]: center }, params.source.unit);
      const modelFp: Array<[number, number]> = fpKeys
        ? Array.from(fpKeys).map((k) => {
            const [c, r] = k.split(",").map(Number);
            return [c, r] as [number, number];
          })
        : [center];
      const walls = removeWallsAroundOccupiedFloor(
        baseWallHexes,
        modelFp,
        params.terrainFloors,
        viewLevel
      );
      // Origine du scan = la FIGURINE elle-même (center), pas l'ancre de l'unité : le rayon LoS
      // principal du WASM part de (shooterCol,shooterRow) → le cône vert rayonne bien depuis la fig
      // sur l'étage, et non depuis le socle d'ancre au sol.
      const raw = computeVisibleHexes(
        center[0],
        center[1],
        scanRange,
        params.boardCols,
        params.boardRows,
        walls,
        obscuringHexes,
        terrainHexes,
        modelFp
      );
      for (const h of raw) {
        const k = `${h.col},${h.row}`;
        if (!baseKeys.has(k)) elevByKey.set(k, h);
      }
    }
    for (const h of elevByKey.values()) {
      if (inMaxRange(h)) elevatedCells.push({ col: h.col, row: h.row });
    }
  }
  const visibleHexes =
    metric === "euclidean" ? visibleHexesRaw.filter(inMaxRange) : visibleHexesRaw;
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
  // Signature des niveaux par-figurine + niveau affiché → re-mémoïse quand l'overlay vert change
  // (un niveau change, ou on change d'étage affiché) sans que la position bouge.
  const levelsKey =
    modelLevels && centers
      ? Object.keys(centers)
          .sort()
          .map((mid) => `${mid}:${modelLevels[mid] ?? 0}`)
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
    `v${viewLevel}`,
    levelsKey,
    elevatedCells.length,
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
    elevatedCells,
    key,
  };
}
