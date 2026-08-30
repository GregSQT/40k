export type TerrainRef = "mc1" | "mc2" | "pfm2";

export const TERRAIN_REFS: readonly TerrainRef[] = ["mc1", "mc2", "pfm2"];

const STORAGE_KEY = "gameprep_terrain";

export const TERRAIN_LABELS: Record<TerrainRef, string> = {
  mc1: "Terrain 1",
  mc2: "Terrain 2",
  pfm2: "Purge the Foe Mirror 2",
};

/**
 * Terrains qu'un mode sait charger : il lui faut un scénario par terrain proposé.
 * `pve_test` n'a pas de scénario `pfm2`, il ne l'expose donc pas.
 */
const TERRAINS_BY_MODE: Record<string, readonly TerrainRef[]> = {
  pvp: ["mc1", "mc2", "pfm2"],
  pvp_test: ["mc1", "mc2", "pfm2"],
  pve: ["mc1", "mc2", "pfm2"],
  pve_test: ["mc1", "mc2"],
};

/** Terrain du scénario NON suffixé du mode. */
const DEFAULT_BY_MODE: Record<string, TerrainRef> = {
  pvp: "mc2",
  pvp_test: "mc2",
  pve: "mc1",
  pve_test: "mc1",
};

/** Le mode PvP est celui de `/game` SANS paramètre `mode`. */
const normalizeMode = (mode: string | null): string => (mode === null ? "pvp" : mode);

export function terrainsForMode(mode: string | null): readonly TerrainRef[] {
  return TERRAINS_BY_MODE[normalizeMode(mode)] ?? [];
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

  return DEFAULT_BY_MODE[normalizeMode(mode)] ?? "mc2";
}
