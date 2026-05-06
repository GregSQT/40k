import { resolveBaseSizeForUnitDisplay } from "./hexFootprint";
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
  /** Aligné sur ``Unit.BASE_SIZE`` (nombre ou tuple rare). */
  BASE_SIZE?: number | [number, number];
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
  maxRange: number;
  losVisibilityMinRatio: number;
  coverRatio: number;
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
  losVisibilityMinRatio: number,
  coverRatio: number
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
    const uBaseResolved = resolveBaseSizeForUnitDisplay(u);
    const uBaseSize = uBaseResolved > 1 ? uBaseResolved : 0;
    const scanR = uBaseSize > 0 ? Math.ceil(uBaseSize / 2) : 0;
    let totalHexes = 0;
    let visibleCount = 0;
    for (let dc = -scanR; dc <= scanR; dc++) {
      for (let dr = -scanR; dr <= scanR; dr++) {
        if (hexDistOff(u.col, u.row, u.col + dc, u.row + dr) > scanR) continue;
        totalHexes++;
        if (visibleHexKeySet.has(`${u.col + dc},${u.row + dr}`)) visibleCount++;
      }
    }
    const ratio = totalHexes > 0 ? visibleCount / totalHexes : 0;
    const isVisible = ratio >= losVisibilityMinRatio;
    if (!isVisible) continue;
    const inCover = ratio < coverRatio;
    const uid = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
    blinkIds.push(uid);
    coverByUnitId[String(u.id)] = inCover;
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
  const visibleHexes = computeVisibleHexes(
    params.source.fromCol,
    params.source.fromRow,
    params.maxRange,
    params.boardCols,
    params.boardRows,
    effectiveWallHexes,
    params.losVisibilityMinRatio,
    params.coverRatio
  );
  const losPreview = buildShootingLosPreviewFromVisibleHexes(
    visibleHexes,
    params.units,
    params.source.unit.player,
    params.losVisibilityMinRatio,
    params.coverRatio
  );
  const key = [
    params.source.fromCol,
    params.source.fromRow,
    params.maxRange,
    params.boardCols,
    params.boardRows,
    stableWallHexKey(effectiveWallHexes),
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
