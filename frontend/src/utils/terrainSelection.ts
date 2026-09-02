export interface TerrainEntry {
  id: string;
  label: string;
  preview_image: string;
  modes: string[];
  default_for: string[];
}

export const STORAGE_KEY = "gameprep_terrain";

// Liste chargée depuis /api/config/terrain-list au montage de BoardWithAPI.
let _terrainList: TerrainEntry[] = [];

export function setTerrainList(list: TerrainEntry[]): void {
  _terrainList = list.filter((t) => Array.isArray(t.modes) && Array.isArray(t.default_for));
}

export function getTerrainList(): readonly TerrainEntry[] {
  return _terrainList;
}

export function terrainsForMode(mode: string | null): readonly TerrainEntry[] {
  const m = mode ?? "pvp";
  return _terrainList.filter((t) => t.modes.includes(m));
}

/**
 * Suffixe de scénario pour ce terrain et ce mode.
 * Miroir de `_terrain_scenario_suffix` Python, calculé depuis default_for.
 */
export function terrainSuffix(
  terrainId: string,
  mode: string,
  list: readonly TerrainEntry[]
): string {
  const entry = list.find((t) => t.id === terrainId);
  if (!entry) return `_${terrainId}`;
  return entry.default_for.includes(mode) ? "" : `_${terrainId}`;
}

/**
 * Terrain retenu pour ce mode : paramètre d'URL, sinon configuration gardée par défaut,
 * sinon le premier terrain disponible pour ce mode.
 */
export function resolveSelectedTerrain(mode: string | null, search: string): string {
  const entries = terrainsForMode(mode);

  const accepts = (value: string | null): value is string =>
    value !== null && value.trim() !== "" && entries.some((t) => t.id === value);

  const fromUrl = new URLSearchParams(search).get("terrain");
  if (accepts(fromUrl)) return fromUrl;

  let saved: string | null = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch {
    saved = null;
  }
  if (accepts(saved)) return saved;

  const m = mode ?? "pvp";
  const defaultEntry = entries.find((t) => t.default_for.includes(m));
  return defaultEntry?.id ?? entries[0]?.id ?? "mc2";
}
