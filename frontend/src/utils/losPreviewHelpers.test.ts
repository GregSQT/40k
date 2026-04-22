import { describe, expect, it } from "vitest";
import { buildShootingLosPreviewFromVisibleHexes } from "./losPreviewHelpers";
import type { VisibleHex } from "./wasmLos";

describe("buildShootingLosPreviewFromVisibleHexes", () => {
  it("splits terrain clear vs cover like WASM states", () => {
    const visibleHexes: VisibleHex[] = [
      { col: 0, row: 0, state: 1 },
      { col: 1, row: 0, state: 2 },
    ];
    const out = buildShootingLosPreviewFromVisibleHexes(
      visibleHexes,
      [{ id: 1, player: 0, col: 5, row: 5 }],
      0,
      0,
      0.5,
    );
    expect(out.clearCells).toEqual([{ col: 0, row: 0 }]);
    expect(out.terrainCoverCells).toEqual([{ col: 1, row: 0 }]);
    expect(out.visibleHexKeySet.has("0,0")).toBe(true);
    expect(out.visibleHexKeySet.has("1,0")).toBe(true);
  });
});
