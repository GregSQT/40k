// @vitest-environment node
// Contrat front/back : terrainSuffix doit produire le même suffixe que
// _load_terrain_list_constants() (services/api_server.py:272-321) pour chaque
// (mode, terrain) déclaré dans le vrai terrain_list.json.
// Aucun mock — les deux côtés partent de la même source de données.

import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";
import { terrainSuffix, type TerrainEntry } from "./terrainSelection";

const __dirname = dirname(fileURLToPath(import.meta.url));
const TERRAIN_LIST_PATH = resolve(
  __dirname,
  "../../../config/board/44x60x5/terrain/terrain_list.json"
);

/**
 * Réplique exacte de _load_terrain_list_constants() (api_server.py:272-321).
 * Construit suffix_table[mode][terrainId] → "" | "_<id>".
 */
function buildBackendSuffixTable(
  entries: TerrainEntry[]
): Record<string, Record<string, string>> {
  const defaultFor: Record<string, string> = {};
  const allModes = new Set<string>();

  for (const e of entries) {
    for (const m of e.modes) allModes.add(m);
    for (const m of e.default_for) {
      if (m in defaultFor) {
        throw new Error(
          `terrain_list.json: deux terrains déclarent default_for=${m} ` +
            `(${defaultFor[m]} et ${e.id})`
        );
      }
      defaultFor[m] = e.id;
    }
  }

  const suffixTable: Record<string, Record<string, string>> = {};
  for (const mode of allModes) {
    const modeTerrains = entries
      .filter((e) => e.modes.includes(mode))
      .map((e) => e.id);
    const defaultTid = defaultFor[mode];
    suffixTable[mode] = Object.fromEntries(
      modeTerrains.map((tid) => [tid, tid === defaultTid ? "" : `_${tid}`])
    );
  }

  // Cas spécial pve_test (api_server.py:306-307) : mc2 désigne le scénario de
  // base sans décor même quand il n'est pas dans les modes UI de pve_test.
  if ("pve_test" in suffixTable && !("mc2" in suffixTable["pve_test"])) {
    suffixTable["pve_test"]["mc2"] = "";
  }

  return suffixTable;
}

describe("terrainSuffix — contrat front/back (terrain_list.json réel)", () => {
  const realList: TerrainEntry[] = JSON.parse(
    readFileSync(TERRAIN_LIST_PATH, "utf-8")
  );
  const suffixTable = buildBackendSuffixTable(realList);

  for (const [mode, terrains] of Object.entries(suffixTable)) {
    for (const [tid, expected] of Object.entries(terrains)) {
      it(`mode=${mode} terrain=${tid} → "${expected}"`, () => {
        expect(terrainSuffix(tid, mode, realList)).toBe(expected);
      });
    }
  }
});
