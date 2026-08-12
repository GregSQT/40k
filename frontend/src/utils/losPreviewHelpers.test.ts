import { describe, expect, it } from "vitest";
import {
  buildEffectiveLosWallHexes,
  buildShootingLosPreviewFromVisibleHexes,
} from "./losPreviewHelpers";
import type { VisibleHex } from "./wasmLos";

describe("buildEffectiveLosWallHexes", () => {
  // VERROU : cette fonction est la SOURCE UNIQUE des murs — dessin, glisser de déploiement, clé
  // d'invalidation du calque statique et LoS en dépendent. Si elle mutait son entrée, le contenu de
  // `boardConfig.wall_hexes` dépendrait de l'ordre des appels, et toute mémoïsation sur sa
  // référence servirait un état périmé. C'est le défaut qui vivait dans BoardPvp avant ce chantier.
  it("ne mute PAS le tableau reçu", () => {
    const walls: [number, number][] = [[0, 0]];
    buildEffectiveLosWallHexes(4, 3, walls);
    expect(walls).toEqual([[0, 0]]);
  });

  it("complète la rangée du bas sur les colonnes IMPAIRES, sans doublon", () => {
    const out = buildEffectiveLosWallHexes(4, 3, [
      [0, 0],
      [1, 2],
    ] as [number, number][]);
    expect(out).toEqual([
      [0, 0],
      [1, 2],
      [3, 2],
    ]);
  });

  it("l'override de replay REMPLACE les murs du plateau", () => {
    const out = buildEffectiveLosWallHexes(2, 2, [[0, 0]] as [number, number][], [
      { col: 0, row: 1 },
    ]);
    expect(out).toEqual([
      [0, 1],
      [1, 1],
    ]);
  });
});

describe("buildShootingLosPreviewFromVisibleHexes", () => {
  it("splits terrain clear vs cover like WASM states", () => {
    const visibleHexes: VisibleHex[] = [
      { col: 0, row: 0, state: 1 },
      { col: 1, row: 0, state: 2 },
    ];
    const out = buildShootingLosPreviewFromVisibleHexes(
      visibleHexes,
      [{ id: 1, player: 0, col: 5, row: 5 }],
      0
    );
    expect(out.clearCells).toEqual([{ col: 0, row: 0 }]);
    expect(out.terrainCoverCells).toEqual([{ col: 1, row: 0 }]);
    expect(out.visibleHexKeySet.has("0,0")).toBe(true);
    expect(out.visibleHexKeySet.has("1,0")).toBe(true);
  });
});
