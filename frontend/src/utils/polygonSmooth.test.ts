import { describe, expect, it } from "vitest";
import { chaikinSmoothClosedPolygonFlat, smoothMaskLoopsForRender } from "./polygonSmooth";

describe("chaikinSmoothClosedPolygonFlat", () => {
  it("returns input unchanged when iterations is 0", () => {
    const sq = [0, 0, 10, 0, 10, 10, 0, 10];
    expect(chaikinSmoothClosedPolygonFlat(sq, 0)).toEqual(sq);
  });

  it("doubles vertex count after one iteration for a square", () => {
    const sq = [0, 0, 10, 0, 10, 10, 0, 10];
    const out = chaikinSmoothClosedPolygonFlat(sq, 1);
    expect(out.length).toBe(16);
  });

  it("quadruples vertex count after two iterations for a square", () => {
    const sq = [0, 0, 10, 0, 10, 10, 0, 10];
    const out = chaikinSmoothClosedPolygonFlat(sq, 2);
    expect(out.length).toBe(32);
  });

  it("keeps polygon roughly centered (square)", () => {
    const sq = [0, 0, 100, 0, 100, 100, 0, 100];
    const out = chaikinSmoothClosedPolygonFlat(sq, 1);
    let sx = 0;
    let sy = 0;
    const n = out.length / 2;
    for (let i = 0; i < n; i++) {
      sx += out[i * 2]!;
      sy += out[i * 2 + 1]!;
    }
    expect(sx / n).toBeCloseTo(50, 0);
    expect(sy / n).toBeCloseTo(50, 0);
  });
});

describe("smoothMaskLoopsForRender", () => {
  it("bounds match smoothed geometry (square loop)", () => {
    const loops = [[0, 0, 10, 0, 10, 10, 0, 10]];
    const { smoothed, minX, minY, maxX, maxY } = smoothMaskLoopsForRender(loops, 1);
    expect(smoothed.length).toBe(1);
    let bx0 = Infinity;
    let bx1 = -Infinity;
    let by0 = Infinity;
    let by1 = -Infinity;
    const f = smoothed[0]!;
    for (let i = 0; i < f.length; i += 2) {
      const x = f[i]!;
      const y = f[i + 1]!;
      if (x < bx0) bx0 = x;
      if (x > bx1) bx1 = x;
      if (y < by0) by0 = y;
      if (y > by1) by1 = y;
    }
    expect(minX).toBe(bx0);
    expect(maxX).toBe(bx1);
    expect(minY).toBe(by0);
    expect(maxY).toBe(by1);
  });
});
