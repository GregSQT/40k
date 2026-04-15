import init, {
  compute_visible_hexes,
  compute_los_single,
} from "../wasm-los-pkg/wasm_los.js";

let wasmReady = false;
let initPromise: Promise<void> | null = null;

export async function ensureWasmLoaded(): Promise<void> {
  if (wasmReady) return;
  if (!initPromise) {
    initPromise = init()
      .then(() => {
        wasmReady = true;
        console.log("[WASM-LOS] Module loaded successfully");
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

export function computeVisibleHexes(
  shooterCol: number,
  shooterRow: number,
  maxRange: number,
  boardCols: number,
  boardRows: number,
  wallHexes: Array<[number, number]> | number[][],
  losVisibilityMinRatio: number,
  coverRatio: number,
): VisibleHex[] {
  if (!wasmReady) {
    throw new Error("WASM not initialized — call ensureWasmLoaded() first");
  }
  const wallData = getWallData(wallHexes);
  const t0 = performance.now();
  const raw = compute_visible_hexes(
    shooterCol, shooterRow, maxRange,
    boardCols, boardRows,
    wallData, losVisibilityMinRatio, coverRatio,
  );
  const t1 = performance.now();
  const results: VisibleHex[] = [];
  for (let i = 0; i < raw.length; i += 3) {
    results.push({
      col: raw[i],
      row: raw[i + 1],
      state: raw[i + 2] as 1 | 2,
    });
  }
  console.log(`[WASM-LOS] compute_visible_hexes: ${results.length} hexes in ${(t1 - t0).toFixed(1)}ms`);
  return results;
}

export function computeLosSingle(
  fromCol: number, fromRow: number,
  toCol: number, toRow: number,
  wallHexes: Array<[number, number]> | number[][],
  losVisibilityMinRatio: number,
  coverRatio: number,
): 0 | 1 | 2 {
  if (!wasmReady) {
    throw new Error("WASM not initialized — call ensureWasmLoaded() first");
  }
  const wallData = getWallData(wallHexes);
  return compute_los_single(
    fromCol, fromRow, toCol, toRow,
    wallData, losVisibilityMinRatio, coverRatio,
  ) as 0 | 1 | 2;
}
