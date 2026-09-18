import { describe, expect, it } from "vitest";
import { attackLotReticleTargets, drawReticle, type ReticleCanvas } from "./reticle";

/** Enregistreur d'appels : ce que le réticule a dessiné, dans l'ordre. */
function recorder() {
  const calls: Array<[string, ...unknown[]]> = [];
  const canvas: ReticleCanvas = {
    lineStyle: (...a) => calls.push(["lineStyle", ...a]),
    beginFill: (...a) => calls.push(["beginFill", ...a]),
    endFill: () => calls.push(["endFill"]),
    drawCircle: (...a) => calls.push(["drawCircle", ...a]),
    moveTo: (...a) => calls.push(["moveTo", ...a]),
    lineTo: (...a) => calls.push(["lineTo", ...a]),
  };
  return { calls, canvas };
}
const centerOf = (pos: [number, number]): [number, number] => [pos[0] * 10, pos[1] * 10];

describe("drawReticle — réticule sur TOUTES les figurines de l'unité désignée (2026-09-18)", () => {
  it("un cercle rouge + 4 traits par figurine, sans voile", () => {
    const { calls, canvas } = recorder();
    drawReticle(
      canvas,
      10,
      centerOf,
      {},
      { "2#0": [1, 1], "2#1": [2, 1], "2#2": [3, 1] },
      {
        veil: false,
        alpha: 0.8,
      }
    );
    const circles = calls.filter((c) => c[0] === "drawCircle");
    expect(circles).toHaveLength(3);
    expect(circles.map((c) => [c[1], c[2]])).toEqual([
      [10, 10],
      [20, 10],
      [30, 10],
    ]);
    expect(calls.filter((c) => c[0] === "lineTo")).toHaveLength(12);
    expect(calls.filter((c) => c[0] === "beginFill")).toHaveLength(0);
    // Le trait rouge porte l'alpha demandé (cible désignée non active : atténuée).
    expect(
      calls.filter((c) => c[0] === "lineStyle" && c[2] === 0xff2b2b && c[3] === 0.8)
    ).toHaveLength(3);
  });

  it("voile jaune en plus sur la cible active, et rayon calé sur la base large", () => {
    const { calls, canvas } = recorder();
    drawReticle(
      canvas,
      10,
      centerOf,
      { BASE_SIZE: 3 },
      { "9#0": [4, 4] },
      { veil: true, alpha: 1 }
    );
    const fills = calls.filter((c) => c[0] === "beginFill");
    expect(fills).toEqual([["beginFill", 0xf5c518, 0.22]]);
    const circles = calls.filter((c) => c[0] === "drawCircle");
    // voile (rayon base) puis réticule (×1.15) : base 3 → tR = 3*1.5*10/2 = 22.5
    expect(circles.map((c) => c[3])).toEqual([22.5, 22.5 * 1.15]);
  });
});

describe("attackLotReticleTargets — lot en cours", () => {
  const lots = [{ target_unit_id: "2" }, { target_unit_id: "3" }, { target_unit_id: "2" }];

  it("allocation en cours → la seule unité qui encaisse, clignotante", () => {
    expect(attackLotReticleTargets({ locked_target_unit_id: null, lots }, "3")).toEqual({
      targets: ["3"],
      blinking: true,
    });
  });

  it("attente de lot verrouillée sur une unité (04.03) → cette unité, clignotante", () => {
    expect(attackLotReticleTargets({ locked_target_unit_id: "2", lots }, null)).toEqual({
      targets: ["2"],
      blinking: true,
    });
  });

  it("attente de lot ouverte → chaque unité candidate une fois, fixe", () => {
    expect(attackLotReticleTargets({ locked_target_unit_id: null, lots }, null)).toEqual({
      targets: ["2", "3"],
      blinking: false,
    });
  });

  it("rien à résoudre → aucune cible", () => {
    expect(attackLotReticleTargets(null, null)).toEqual({ targets: [], blinking: false });
  });
});
