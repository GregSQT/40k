export type TerrainRef = "mc1" | "mc2" | "pfm2";

export const TERRAIN_REFS: readonly TerrainRef[] = ["mc1", "mc2", "pfm2"];

const STORAGE_KEY = "gameprep_terrain";

export const TERRAIN_LABELS: Record<TerrainRef, string> = {
  mc1: "Terrain 1",
  mc2: "Terrain 2",
  pfm2: "Purge the Foe Mirror 2",
};

const PVP_TERRAINS: readonly TerrainRef[] = ["mc1", "mc2", "pfm2"];

/**
 * Terrains qu'un mode sait charger : il lui faut un scénario par terrain proposé.
 * `pve_test` n'a pas de scénario `pfm2`, il ne l'expose donc pas.
 */
const TERRAINS_BY_MODE: Record<string, readonly TerrainRef[]> = {
  pvp: PVP_TERRAINS,
  pvp_test: PVP_TERRAINS,
  pve: PVP_TERRAINS,
  pve_test: ["mc1", "mc2"],
};

/** Terrain du scénario NON suffixé du mode. */
const DEFAULT_BY_MODE: Record<string, TerrainRef> = {
  pvp: "mc2",
  pvp_test: "mc2",
  pve: "mc1",
  pve_test: "mc1",
};

/** Miroir client de `TERRAIN_SCENARIO_SUFFIX_BY_MODE` du backend. */
const TERRAIN_SUFFIX_BY_MODE: Record<string, Partial<Record<TerrainRef, string>>> = {
  pvp: { mc1: "_mc1", mc2: "", pfm2: "_pfm2" },
  pvp_test: { mc1: "_mc1", mc2: "", pfm2: "_pfm2" },
  pve: { mc1: "", mc2: "_mc2", pfm2: "_pfm2" },
  pve_test: { mc1: "_mc1", mc2: "" },
};

export function terrainsForMode(mode: string | null): readonly TerrainRef[] {
  return TERRAINS_BY_MODE[mode ?? "pvp"] ?? [];
}

/** Suffixe de scénario du terrain pour ce mode — miroir de `_terrain_scenario_suffix` Python. */
export function clientTerrainSuffix(mode: string | null, terrain: TerrainRef): string {
  return TERRAIN_SUFFIX_BY_MODE[mode ?? "pvp"]?.[terrain] ?? "";
}

/**
 * Terrain retenu pour ce mode : paramètre d'URL, sinon configuration gardée par défaut,
 * sinon le terrain du scénario non suffixé du mode. Une valeur que ce mode ne sait pas charger
 * est ignorée au profit de son défaut.
 *
 * UNE seule résolution pour les trois lecteurs (bouton du popup, plateau dessiné, partie
 * démarrée) : quand ils divergeaient, le popup montrait le terrain gardé en mémoire pendant
 * que le plateau dessiné et le plateau joué restaient sur le défaut.
 */
export function resolveSelectedTerrain(mode: string | null, search: string): TerrainRef {
  const supported = terrainsForMode(mode);
  const accepts = (value: string | null): value is TerrainRef =>
    value !== null && (supported as readonly string[]).includes(value);

  const fromUrl = new URLSearchParams(search).get("terrain");
  if (accepts(fromUrl)) return fromUrl;

  let saved: string | null = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch {
    saved = null;
  }
  if (accepts(saved)) return saved;

  return DEFAULT_BY_MODE[mode ?? "pvp"] ?? "mc2";
}
