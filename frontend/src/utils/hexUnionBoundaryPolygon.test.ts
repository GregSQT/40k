import { describe, expect, it } from "vitest";
import { tryBuildHexUnionMaskPolygons, type HexUnionMaskLayout } from "./hexUnionBoundaryPolygon";

/** Même contraintes que BoardDisplay (drawBoard) : espacement = 1.5R, hauteur = √3 R. */
const HEX_RADIUS = 10;
const LAYOUT: HexUnionMaskLayout = {
  HEX_HORIZ_SPACING: 1.5 * HEX_RADIUS,
  HEX_WIDTH: 1.5 * HEX_RADIUS,
  HEX_HEIGHT: Math.sqrt(3) * HEX_RADIUS,
  HEX_VERT_SPACING: Math.sqrt(3) * HEX_RADIUS,
  MARGIN: 5,
  gridHexRadius: HEX_RADIUS,
};

describe("tryBuildHexUnionMaskPolygons", () => {
  it("returns null for empty set", () => {
    expect(tryBuildHexUnionMaskPolygons(new Set(), LAYOUT)).toBeNull();
  });

  it("builds a single hex loop (6 corners)", () => {
    const r = tryBuildHexUnionMaskPolygons(new Set(["0,0"]), LAYOUT);
    expect(r).not.toBeNull();
    expect(r!.loops.length).toBe(1);
    expect(r!.loops[0]!.length).toBe(12);
  });

  it("merges two adjacent hexes into one boundary loop", () => {
    const r = tryBuildHexUnionMaskPolygons(new Set(["0,0", "1,0"]), LAYOUT);
    expect(r).not.toBeNull();
    expect(r!.loops.length).toBe(1);
    expect(r!.loops[0]!.length / 2).toBe(10);
  });

  it("produces two loops for two disjoint hexes", () => {
    const r = tryBuildHexUnionMaskPolygons(new Set(["0,0", "5,5"]), LAYOUT);
    expect(r).not.toBeNull();
    expect(r!.loops.length).toBe(2);
    for (const loop of r!.loops) {
      expect(loop.length / 2).toBe(6);
    }
  });

  it("returns null on invalid key", () => {
    expect(tryBuildHexUnionMaskPolygons(new Set(["0,0", "bogus"]), LAYOUT)).toBeNull();
  });
});
