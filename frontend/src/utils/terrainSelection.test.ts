// @vitest-environment jsdom
// Le terrain gardé par « Garder cette configuration par défaut » n'était lu que par le BOUTON du
// popup : le plateau dessiné et la partie démarrée repartaient du défaut. Le popup montrait donc
// pfm2 pendant qu'on jouait mc2. Ce fichier verrouille la résolution partagée.

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  resolveSelectedTerrain,
  setTerrainList,
  terrainSuffix,
  type TerrainEntry,
  terrainsForMode,
} from "./terrainSelection";

const MOCK_TERRAIN_LIST: TerrainEntry[] = [
  {
    id: "mc1",
    label: "Terrain 1",
    preview_image: "/icons/Terrain/terrain-mc1.jpg",
    modes: ["pvp", "pvp_test", "pve", "pve_test"],
    default_for: ["pve"],
  },
  {
    id: "mc2",
    label: "Terrain 2",
    preview_image: "/icons/Terrain/terrain-mc2.jpg",
    modes: ["pvp", "pvp_test", "pve"],
    default_for: ["pvp", "pvp_test"],
  },
  {
    id: "pfm2",
    label: "Purge the Foe Mirror 2",
    preview_image: "/icons/Terrain/terrain-pfm2.jpg",
    modes: ["pvp", "pvp_test", "pve"],
    default_for: [],
  },
];

beforeEach(() => {
  setTerrainList(MOCK_TERRAIN_LIST);
});

afterEach(() => {
  localStorage.clear();
  setTerrainList([]);
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

  it("reprend le localStorage valide quand l'URL est invalide", () => {
    localStorage.setItem("gameprep_terrain", "mc1");
    expect(resolveSelectedTerrain(null, "?terrain=nonexistent")).toBe("mc1");
  });

  it("pvp_test sans URL ni localStorage : mc2 via default_for, pas supported[0]", () => {
    expect(resolveSelectedTerrain("pvp_test", "")).toBe("mc2");
  });
});

describe("resolveSelectedTerrain — avant chargement de la liste", () => {
  beforeEach(() => setTerrainList([]));

  it("n'accepte pas un terrain inconnu depuis l'URL", () => {
    expect(resolveSelectedTerrain(null, "?terrain=garbage")).toBe("mc2");
  });

  it("rejette '' (URL ?terrain= vide) même sans liste chargée", () => {
    expect(resolveSelectedTerrain(null, "?terrain=")).toBe("mc2");
  });

  it("rejette une chaîne blanche (%20) depuis l'URL", () => {
    expect(resolveSelectedTerrain(null, "?terrain=%20")).toBe("mc2");
  });
});

describe("terrainsForMode", () => {
  it("n'expose pfm2 que dans les modes qui en ont le scénario", () => {
    expect(terrainsForMode(null).map((t) => t.id)).toContain("pfm2");
    expect(terrainsForMode("pve").map((t) => t.id)).toContain("pfm2");
    expect(terrainsForMode("pvp_test").map((t) => t.id)).toContain("pfm2");
    expect(terrainsForMode("pve_test").map((t) => t.id)).not.toContain("pfm2");
  });

  it("n'expose que mc1 en mode pve_test", () => {
    expect(terrainsForMode("pve_test").map((t) => t.id)).toEqual(["mc1"]);
  });
});

describe("terrainSuffix", () => {
  const suf = (id: string) => terrainSuffix(id, "pvp", MOCK_TERRAIN_LIST);

  it("renvoie _id pour un terrain inconnu", () => {
    expect(suf("xyz")).toBe("_xyz");
  });

  it("renvoie '' pour le terrain par défaut du mode", () => {
    expect(suf("mc2")).toBe("");
  });

  it("renvoie _id pour un terrain connu mais non-défaut du mode", () => {
    expect(suf("mc1")).toBe("_mc1");
  });
});
