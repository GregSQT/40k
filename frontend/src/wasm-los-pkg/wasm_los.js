/* @ts-self-types="./wasm_los.d.ts" */

/**
 * Single-pair LoS check. Returns: 0 = blocked, 1 = visible.
 * @param {number} from_col
 * @param {number} from_row
 * @param {number} to_col
 * @param {number} to_row
 * @param {Int32Array} wall_data
 * @returns {number}
 */
export function compute_los_single(from_col, from_row, to_col, to_row, wall_data) {
    const ptr0 = passArray32ToWasm0(wall_data, wasm.__wbindgen_malloc);
    const len0 = WASM_VECTOR_LEN;
    const ret = wasm.compute_los_single(from_col, from_row, to_col, to_row, ptr0, len0);
    return ret;
}

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
 * @param {number} shooter_col
 * @param {number} shooter_row
 * @param {number} max_range
 * @param {number} board_cols
 * @param {number} board_rows
 * @param {Int32Array} wall_data
 * @param {Int32Array} obscuring_data
 * @param {Int32Array} terrain_data
 * @param {Int32Array} shooter_footprint
 * @returns {Int32Array}
 */
export function compute_visible_hexes(shooter_col, shooter_row, max_range, board_cols, board_rows, wall_data, obscuring_data, terrain_data, shooter_footprint) {
    const ptr0 = passArray32ToWasm0(wall_data, wasm.__wbindgen_malloc);
    const len0 = WASM_VECTOR_LEN;
    const ptr1 = passArray32ToWasm0(obscuring_data, wasm.__wbindgen_malloc);
    const len1 = WASM_VECTOR_LEN;
    const ptr2 = passArray32ToWasm0(terrain_data, wasm.__wbindgen_malloc);
    const len2 = WASM_VECTOR_LEN;
    const ptr3 = passArray32ToWasm0(shooter_footprint, wasm.__wbindgen_malloc);
    const len3 = WASM_VECTOR_LEN;
    const ret = wasm.compute_visible_hexes(shooter_col, shooter_row, max_range, board_cols, board_rows, ptr0, len0, ptr1, len1, ptr2, len2, ptr3, len3);
    var v5 = getArrayI32FromWasm0(ret[0], ret[1]).slice();
    wasm.__wbindgen_free(ret[0], ret[1] * 4, 4);
    return v5;
}

/**
 * Hex distance between two positions.
 * @param {number} col1
 * @param {number} row1
 * @param {number} col2
 * @param {number} row2
 * @returns {number}
 */
export function wasm_hex_distance(col1, row1, col2, row2) {
    const ret = wasm.wasm_hex_distance(col1, row1, col2, row2);
    return ret;
}
function __wbg_get_imports() {
    const import0 = {
        __proto__: null,
        __wbindgen_init_externref_table: function() {
            const table = wasm.__wbindgen_externrefs;
            const offset = table.grow(4);
            table.set(0, undefined);
            table.set(offset + 0, undefined);
            table.set(offset + 1, null);
            table.set(offset + 2, true);
            table.set(offset + 3, false);
        },
    };
    return {
        __proto__: null,
        "./wasm_los_bg.js": import0,
    };
}

function getArrayI32FromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    return getInt32ArrayMemory0().subarray(ptr / 4, ptr / 4 + len);
}

let cachedInt32ArrayMemory0 = null;
function getInt32ArrayMemory0() {
    if (cachedInt32ArrayMemory0 === null || cachedInt32ArrayMemory0.byteLength === 0) {
        cachedInt32ArrayMemory0 = new Int32Array(wasm.memory.buffer);
    }
    return cachedInt32ArrayMemory0;
}

let cachedUint32ArrayMemory0 = null;
function getUint32ArrayMemory0() {
    if (cachedUint32ArrayMemory0 === null || cachedUint32ArrayMemory0.byteLength === 0) {
        cachedUint32ArrayMemory0 = new Uint32Array(wasm.memory.buffer);
    }
    return cachedUint32ArrayMemory0;
}

function passArray32ToWasm0(arg, malloc) {
    const ptr = malloc(arg.length * 4, 4) >>> 0;
    getUint32ArrayMemory0().set(arg, ptr / 4);
    WASM_VECTOR_LEN = arg.length;
    return ptr;
}

let WASM_VECTOR_LEN = 0;

let wasmModule, wasm;
function __wbg_finalize_init(instance, module) {
    wasm = instance.exports;
    wasmModule = module;
    cachedInt32ArrayMemory0 = null;
    cachedUint32ArrayMemory0 = null;
    wasm.__wbindgen_start();
    return wasm;
}

async function __wbg_load(module, imports) {
    if (typeof Response === 'function' && module instanceof Response) {
        if (typeof WebAssembly.instantiateStreaming === 'function') {
            try {
                return await WebAssembly.instantiateStreaming(module, imports);
            } catch (e) {
                const validResponse = module.ok && expectedResponseType(module.type);

                if (validResponse && module.headers.get('Content-Type') !== 'application/wasm') {
                    console.warn("`WebAssembly.instantiateStreaming` failed because your server does not serve Wasm with `application/wasm` MIME type. Falling back to `WebAssembly.instantiate` which is slower. Original error:\n", e);

                } else { throw e; }
            }
        }

        const bytes = await module.arrayBuffer();
        return await WebAssembly.instantiate(bytes, imports);
    } else {
        const instance = await WebAssembly.instantiate(module, imports);

        if (instance instanceof WebAssembly.Instance) {
            return { instance, module };
        } else {
            return instance;
        }
    }

    function expectedResponseType(type) {
        switch (type) {
            case 'basic': case 'cors': case 'default': return true;
        }
        return false;
    }
}

function initSync(module) {
    if (wasm !== undefined) return wasm;


    if (module !== undefined) {
        if (Object.getPrototypeOf(module) === Object.prototype) {
            ({module} = module)
        } else {
            console.warn('using deprecated parameters for `initSync()`; pass a single object instead')
        }
    }

    const imports = __wbg_get_imports();
    if (!(module instanceof WebAssembly.Module)) {
        module = new WebAssembly.Module(module);
    }
    const instance = new WebAssembly.Instance(module, imports);
    return __wbg_finalize_init(instance, module);
}

async function __wbg_init(module_or_path) {
    if (wasm !== undefined) return wasm;


    if (module_or_path !== undefined) {
        if (Object.getPrototypeOf(module_or_path) === Object.prototype) {
            ({module_or_path} = module_or_path)
        } else {
            console.warn('using deprecated parameters for the initialization function; pass a single object instead')
        }
    }

    if (module_or_path === undefined) {
        module_or_path = new URL('wasm_los_bg.wasm', import.meta.url);
    }
    const imports = __wbg_get_imports();

    if (typeof module_or_path === 'string' || (typeof Request === 'function' && module_or_path instanceof Request) || (typeof URL === 'function' && module_or_path instanceof URL)) {
        module_or_path = fetch(module_or_path);
    }

    const { instance, module } = await __wbg_load(await module_or_path, imports);

    return __wbg_finalize_init(instance, module);
}

export { initSync, __wbg_init as default };
