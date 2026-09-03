import type { TerrainEntry } from "../../utils/terrainSelection";

/** Liste de terrains servie par /api/config/terrain-list en production (terrain_list.json).
 *  Les deux consommateurs la reçoivent ensemble : la liste GLOBALE (lue par `terrainsForMode` /
 *  `resolveSelectedTerrain`) et la prop du hook, qui débloque le démarrage de partie. Monter le
 *  hook sans elle, c'est le montage d'AVANT la réponse du fetch : aucune partie ne démarre. */
export const TEST_TERRAIN_LIST: TerrainEntry[] = [
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
    modes: ["pvp", "pvp_test", "pve", "pve_test"],
    default_for: ["pvp", "pvp_test", "pve_test"],
  },
  {
    id: "pfm2",
    label: "Purge the Foe mirror 2",
    preview_image: "/icons/Terrain/terrain-pfm2.jpg",
    modes: ["pvp", "pvp_test", "pve"],
    default_for: [],
  },
];
