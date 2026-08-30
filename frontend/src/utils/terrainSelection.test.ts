// @vitest-environment jsdom
// Le terrain gardé par « Garder cette configuration par défaut » n'était lu que par le BOUTON du
// popup : le plateau dessiné et la partie démarrée repartaient du défaut. Le popup montrait donc
// pfm2 pendant qu'on jouait mc2. Ce fichier verrouille la résolution partagée.

import { afterEach, describe, expect, it } from "vitest";
import { resolveSelectedTerrain, terrainsForMode } from "./terrainSelection";

afterEach(() => {
  localStorage.clear();
});

describe("resolveSelectedTerrain", () => {
  it("prend le paramètre d'URL avant tout le reste", () => {
    localStorage.setItem("gameprep_terrain", "mc1");
    expect(resolveSelectedTerrain(null, "?terrain=pfm2")).toBe("pfm2");
  });

  it("PvP sans URL : reprend le terrain gardé par défaut", () => {
    localStorage.setItem("gameprep_terrain", "pfm2");
    expect(resolveSelectedTerrain(null, "")).toBe("pfm2");
  });

  it("PvP sans URL ni configuration gardée : mc2, terrain du scénario de base", () => {
    expect(resolveSelectedTerrain(null, "")).toBe("mc2");
  });

  it("PvE sans rien : mc1, terrain de son scénario de base", () => {
    expect(resolveSelectedTerrain("pve", "")).toBe("mc1");
  });

  it("ignore un terrain que le mode ne sait pas charger", () => {
    localStorage.setItem("gameprep_terrain", "pfm2");
    expect(resolveSelectedTerrain("pve_test", "?terrain=pfm2")).toBe("mc1");
  });
});

describe("terrainsForMode", () => {
  it("n'expose pfm2 que dans les modes qui en ont le scénario", () => {
    expect(terrainsForMode(null)).toContain("pfm2");
    expect(terrainsForMode("pve")).toContain("pfm2");
    expect(terrainsForMode("pvp_test")).toContain("pfm2");
    expect(terrainsForMode("pve_test")).not.toContain("pfm2");
  });
});
