/* tslint:disable */
/* eslint-disable */

/**
 * Single-pair LoS check. Returns: 0 = blocked, 1 = visible.
 */
export function compute_los_single(from_col: number, from_row: number, to_col: number, to_row: number, wall_data: Int32Array): number;

/**
 * Compute visible hexes from a shooter position within a given range.
 * Returns a flat array: [col0, row0, state0, col1, row1, state1, ...]
 * state: 1 = clear (open), 2 = cover (hex inside a terrain area).
 *
 * Faithful mirror of `_update_unit_los_preview_data` / `_los_hex_visible` (shooting_handlers.py):
 * anchor + lateral-vantage → hex sight line (LoS from any part of the model, peek de coin),
 * blocked by walls or by obscuring areas that neither the shooter nor the destination hex occupies
 * (rule 13.10). MUST be resynced if that backend primitive changes.
 * - `obscuring_data`: flat triplets [col,row,areaId,...] (areaId >= 1) for every obscuring hex.
 * - `terrain_data`: flat pairs [col,row,...] for every hex inside any terrain area (cover).
 * - `shooter_footprint`: flat pairs [col,row,...] of the shooter's occupied hexes; areas it
 *   touches are excluded from blocking (a shooter inside/at the edge of its own terrain still sees out).
 */
export function compute_visible_hexes(shooter_col: number, shooter_row: number, max_range: number, board_cols: number, board_rows: number, wall_data: Int32Array, obscuring_data: Int32Array, terrain_data: Int32Array, shooter_footprint: Int32Array): Int32Array;

/**
 * Hex distance between two positions.
 */
export function wasm_hex_distance(col1: number, row1: number, col2: number, row2: number): number;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly compute_los_single: (a: number, b: number, c: number, d: number, e: number, f: number) => number;
    readonly compute_visible_hexes: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number, i: number, j: number, k: number, l: number, m: number) => [number, number];
    readonly wasm_hex_distance: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
