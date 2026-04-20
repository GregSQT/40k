import { describe, expect, it } from "vitest";
import { pointInAnyMaskLoop, pointInPolygon } from "./pointInPolygon";

describe("pointInPolygon", () => {
  it("detects interior of axis-aligned square", () => {
    const square = [0, 0, 10, 0, 10, 10, 0, 10];
    expect(pointInPolygon(5, 5, square)).toBe(true);
    expect(pointInPolygon(50, 50, square)).toBe(false);
  });

  it("union of two loops", () => {
    const loops = [
      [0, 0, 2, 0, 2, 2, 0, 2],
      [10, 10, 12, 10, 12, 12, 10, 12],
    ];
    expect(pointInAnyMaskLoop(1, 1, loops)).toBe(true);
    expect(pointInAnyMaskLoop(11, 11, loops)).toBe(true);
    expect(pointInAnyMaskLoop(5, 5, loops)).toBe(false);
  });
});
