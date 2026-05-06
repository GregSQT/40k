import { describe, expect, it } from "vitest";
import { addHexKeysToSet, syncMoveDestinationPoolRefs } from "./movePoolRefsSync";

// ─── addHexKeysToSet ──────────────────────────────────────────────────────────

describe("addHexKeysToSet", () => {
  it("parses [col, row] array pairs", () => {
    const out = new Set<string>();
    addHexKeysToSet([[5, 10], [3, 7]], out);
    expect(out.has("5,10")).toBe(true);
    expect(out.has("3,7")).toBe(true);
  });

  it("parses { col, row } objects", () => {
    const out = new Set<string>();
    addHexKeysToSet([{ col: 4, row: 9 }, { col: 12, row: 1 }], out);
    expect(out.has("4,9")).toBe(true);
    expect(out.has("12,1")).toBe(true);
  });

  it("parses 'col,row' strings", () => {
    const out = new Set<string>();
    addHexKeysToSet(["6,11", "0,0"], out);
    expect(out.has("6,11")).toBe(true);
    expect(out.has("0,0")).toBe(true);
  });

  it("handles mixed formats in same array", () => {
    const out = new Set<string>();
    addHexKeysToSet([[1, 2], { col: 3, row: 4 }, "5,6"], out);
    expect(out.size).toBe(3);
    expect(out.has("1,2")).toBe(true);
    expect(out.has("3,4")).toBe(true);
    expect(out.has("5,6")).toBe(true);
  });

  it("does not crash on non-array input", () => {
    const out = new Set<string>();
    expect(() => addHexKeysToSet(null, out)).not.toThrow();
    expect(() => addHexKeysToSet(undefined, out)).not.toThrow();
    expect(() => addHexKeysToSet("not-an-array", out)).not.toThrow();
    expect(out.size).toBe(0);
  });

  it("normalizes numeric strings in [col, row] pairs", () => {
    const out = new Set<string>();
    addHexKeysToSet([["5", "10"]], out);
    expect(out.has("5,10")).toBe(true);
  });

  it("appends to existing set without clearing it", () => {
    const out = new Set<string>(["0,0"]);
    addHexKeysToSet([[1, 1]], out);
    expect(out.has("0,0")).toBe(true);
    expect(out.has("1,1")).toBe(true);
  });

  it("silently ignores array entries with fewer than 2 elements", () => {
    const out = new Set<string>();
    addHexKeysToSet([[5]], out);
    expect(out.size).toBe(0);
  });

  it("produces NaN,10 key for NaN input (documents current behavior)", () => {
    const out = new Set<string>();
    addHexKeysToSet([[Number.NaN, 10]], out);
    expect(out.has("NaN,10")).toBe(true);
  });
});

// ─── syncMoveDestinationPoolRefs ──────────────────────────────────────────────

function makeRef<T>(value: T) {
  return { current: value };
}

describe("syncMoveDestinationPoolRefs", () => {
  it("clears refs when selectedUnitId is null in move phase", () => {
    const moveRef = makeRef(new Set(["5,10", "6,10"]));
    const fpRef = makeRef(new Set(["5,10"]));
    syncMoveDestinationPoolRefs({
      gameState: { valid_move_destinations_pool: [[5, 10]] },
      phase: "move",
      mode: "default",
      selectedUnitId: null,
      moveDestPoolRef: moveRef,
      footprintZoneRef: fpRef,
    });
    expect(moveRef.current.size).toBe(0);
    expect(fpRef.current.size).toBe(0);
  });

  it("fills moveDestPoolRef from valid_move_destinations_pool in move phase", () => {
    const moveRef = makeRef(new Set<string>());
    syncMoveDestinationPoolRefs({
      gameState: { valid_move_destinations_pool: [[5, 10], [6, 10], [7, 10]] },
      phase: "move",
      mode: "default",
      selectedUnitId: 1,
      moveDestPoolRef: moveRef,
    });
    expect(moveRef.current.size).toBe(3);
    expect(moveRef.current.has("5,10")).toBe(true);
  });

  it("falls back to preview_hexes when valid_move_destinations_pool absent", () => {
    const moveRef = makeRef(new Set<string>());
    syncMoveDestinationPoolRefs({
      gameState: { preview_hexes: [[8, 5], [9, 5]] },
      phase: "move",
      mode: "default",
      selectedUnitId: 1,
      moveDestPoolRef: moveRef,
    });
    expect(moveRef.current.has("8,5")).toBe(true);
    expect(moveRef.current.has("9,5")).toBe(true);
  });

  it("fills refs in advancePreview mode regardless of phase", () => {
    const moveRef = makeRef(new Set<string>());
    syncMoveDestinationPoolRefs({
      gameState: { valid_move_destinations_pool: [[3, 4]] },
      phase: "shoot",
      mode: "advancePreview",
      selectedUnitId: 1,
      moveDestPoolRef: moveRef,
    });
    expect(moveRef.current.has("3,4")).toBe(true);
  });

  it("does nothing in shoot phase without pendingMoveAfterShooting", () => {
    const moveRef = makeRef(new Set<string>());
    syncMoveDestinationPoolRefs({
      gameState: { valid_move_destinations_pool: [[5, 5]] },
      phase: "shoot",
      mode: "default",
      selectedUnitId: 1,
      moveDestPoolRef: moveRef,
    });
    expect(moveRef.current.size).toBe(0);
  });

  it("fills refs in shoot phase with pendingMoveAfterShooting and selectedUnitId", () => {
    const moveRef = makeRef(new Set<string>());
    syncMoveDestinationPoolRefs({
      gameState: { valid_move_destinations_pool: [[5, 5], [6, 5]] },
      phase: "shoot",
      mode: "default",
      selectedUnitId: 1,
      moveDestPoolRef: moveRef,
      pendingMoveAfterShooting: true,
    });
    expect(moveRef.current.size).toBe(2);
  });

  it("clears refs in shoot phase with pendingMoveAfterShooting but no selectedUnitId", () => {
    const moveRef = makeRef(new Set(["5,5"]));
    syncMoveDestinationPoolRefs({
      gameState: { valid_move_destinations_pool: [[5, 5]] },
      phase: "shoot",
      mode: "default",
      selectedUnitId: null,
      moveDestPoolRef: moveRef,
      pendingMoveAfterShooting: true,
    });
    expect(moveRef.current.size).toBe(0);
  });

  it("does nothing when moveDestPoolRef is undefined", () => {
    expect(() =>
      syncMoveDestinationPoolRefs({
        gameState: { valid_move_destinations_pool: [[5, 5]] },
        phase: "move",
        mode: "default",
        selectedUnitId: 1,
        moveDestPoolRef: undefined,
      })
    ).not.toThrow();
  });
});
