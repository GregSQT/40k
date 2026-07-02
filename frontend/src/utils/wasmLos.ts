import init, { compute_los_single, compute_visible_hexes } from "../wasm-los-pkg/wasm_los.js";

let wasmReady = false;
let initPromise: Promise<void> | null = null;

export async function ensureWasmLoaded(): Promise<void> {
  if (wasmReady) return;
  if (!initPromise) {
    initPromise = init()
      .then(() => {
        wasmReady = true;
      })
      .catch((err) => {
        console.error("[WASM-LOS] Failed to load WASM module:", err);
        initPromise = null;
      });
  }
  return initPromise;
}

export function isWasmReady(): boolean {
  return wasmReady;
}

export interface VisibleHex {
  col: number;
  row: number;
  state: 1 | 2; // 1 = clear, 2 = cover
}

let cachedWallData: Int32Array | null = null;
let cachedWallKey = "";

function getWallData(wallHexes: Array<[number, number]> | number[][]): Int32Array {
  const key = wallHexes.length.toString();
  if (cachedWallData && cachedWallKey === key) {
    return cachedWallData;
  }
  const flat = new Int32Array(wallHexes.length * 2);
  for (let i = 0; i < wallHexes.length; i++) {
    flat[i * 2] = wallHexes[i][0];
    flat[i * 2 + 1] = wallHexes[i][1];
  }
  cachedWallData = flat;
  cachedWallKey = key;
  return flat;
}

let cachedObscuringData: Int32Array | null = null;
let cachedObscuringKey = "";

/** Flatten obscuring hexes (each carrying its areaId >= 1) into [col,row,areaId,...] for WASM. Static → cached. */
function getObscuringData(obscuringHexes: Array<[number, number, number]>): Int32Array {
  const key = obscuringHexes.length.toString();
  if (cachedObscuringData && cachedObscuringKey === key) {
    return cachedObscuringData;
  }
  const flat = new Int32Array(obscuringHexes.length * 3);
  for (let i = 0; i < obscuringHexes.length; i++) {
    flat[i * 3] = obscuringHexes[i][0];
    flat[i * 3 + 1] = obscuringHexes[i][1];
    flat[i * 3 + 2] = obscuringHexes[i][2];
  }
  cachedObscuringData = flat;
  cachedObscuringKey = key;
  return flat;
}

let cachedTerrainData: Int32Array | null = null;
let cachedTerrainKey = "";

/** Flatten all terrain-area hexes into [col,row,...] (cover classification). Static → cached. */
function getTerrainData(terrainHexes: Array<[number, number]>): Int32Array {
  const key = terrainHexes.length.toString();
  if (cachedTerrainData && cachedTerrainKey === key) {
    return cachedTerrainData;
  }
  const flat = new Int32Array(terrainHexes.length * 2);
  for (let i = 0; i < terrainHexes.length; i++) {
    flat[i * 2] = terrainHexes[i][0];
    flat[i * 2 + 1] = terrainHexes[i][1];
  }
  cachedTerrainData = flat;
  cachedTerrainKey = key;
  return flat;
}

/** Flatten [col,row] pairs (shooter footprint) — small & position-dependent, no cache. */
function flattenPairs(pairs: Array<[number, number]>): Int32Array {
  const flat = new Int32Array(pairs.length * 2);
  for (let i = 0; i < pairs.length; i++) {
    flat[i * 2] = pairs[i][0];
    flat[i * 2 + 1] = pairs[i][1];
  }
  return flat;
}

export function computeVisibleHexes(
  shooterCol: number,
  shooterRow: number,
  maxRange: number,
  boardCols: number,
  boardRows: number,
  wallHexes: Array<[number, number]> | number[][],
  obscuringHexes: Array<[number, number, number]>,
  terrainHexes: Array<[number, number]>,
  shooterFootprint: Array<[number, number]>
): VisibleHex[] {
  if (!wasmReady) {
    throw new Error("WASM not initialized — call ensureWasmLoaded() first");
  }
  const wallData = getWallData(wallHexes);
  const obscuringData = getObscuringData(obscuringHexes);
  const terrainData = getTerrainData(terrainHexes);
  const footprintData = flattenPairs(shooterFootprint);
  const raw = compute_visible_hexes(
    shooterCol,
    shooterRow,
    maxRange,
    boardCols,
    boardRows,
    wallData,
    obscuringData,
    terrainData,
    footprintData
  );
  const results: VisibleHex[] = [];
  for (let i = 0; i < raw.length; i += 3) {
    results.push({
      col: raw[i],
      row: raw[i + 1],
      state: raw[i + 2] as 1 | 2,
    });
  }
  return results;
}

export function computeLosSingle(
  fromCol: number,
  fromRow: number,
  toCol: number,
  toRow: number,
  wallHexes: Array<[number, number]> | number[][]
): 0 | 1 | 2 {
  if (!wasmReady) {
    throw new Error("WASM not initialized — call ensureWasmLoaded() first");
  }
  const wallData = getWallData(wallHexes);
  return compute_los_single(fromCol, fromRow, toCol, toRow, wallData) as 0 | 1 | 2;
}
