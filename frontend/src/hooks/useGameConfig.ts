// frontend/src/hooks/useGameConfig.ts
import { useEffect, useState } from "react";
import { apiFetch } from "../services/apiFetch";
import { resolveSelectedTerrain } from "../utils/terrainSelection";

export interface DisplayConfig {
  resolution?: "auto" | number;
  display_scale?: number;
  autoDensity?: boolean;
  antialias?: boolean;
  forceCanvas?: boolean;
  icon_scale?: number;
  eligible_outline_width?: number;
  eligible_outline_alpha?: number;
  hp_bar_width_ratio?: number;
  hp_bar_height?: number;
  hp_bar_y_offset_ratio?: number;
  unit_circle_radius_ratio?: number;
  unit_text_size?: number;
  selected_border_width?: number;
  charge_target_border_width?: number;
  default_border_width?: number;
  canvas_border?: string;
  right_column_bottom_offset?: number;
  background_image?: string;
  background_image_alpha?: number;
  background_overlay_alpha?: number;
  wall_texture_light?: string;
  wall_texture_dense?: string;
  wall_texture_alpha?: number;
  objective_texture?: string;
  objective_texture_alpha?: number;
  objective_smooth_contour?: boolean;
  objective_smooth_radius_ratio?: number;
  objective_smooth_alpha?: number;
  objective_hex_fill_alpha?: number;
  objective_zone_ring_width?: number;
  objective_zone_ring_color?: string;
  objective_zone_ring_alpha?: number;
  objective_zone_center_radius_ratio?: number;
  objective_zone_center_color?: string;
  objective_zone_center_alpha?: number;
}

/** Étage d'une ruine (format B, multi-niveaux). Empreinte propre rasterisée. */
interface TerrainFloor {
  level: number;
  height_inches: number;
  vertices: [number, number][];
  hexes: Array<[number, number]> | Array<{ col: number; row: number }>;
}

interface ObjectiveZone {
  id: string;
  hexes: Array<{ col: number; row: number }>;
  shape?: string;
  vertices?: [number, number][];
  top_left?: [number, number];
  bottom_right?: [number, number];
  objective?: boolean;
  obscuring?: boolean;
  /** Étages (ruines multi-niveaux). Absent = terrain plain-pied. */
  floors?: TerrainFloor[];
}

interface Wall {
  id?: string;
  start: { col: number; row: number };
  end: { col: number; row: number };
  thickness?: number;
  type?: "dense" | "light";
}

interface BoardConfig {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
  /** Cases par pouce. Requis : sert aux conversions pouces↔cases et aux épaisseurs de rendu. */
  inches_to_subhex: number;
  wall_hexes: [number, number][];
  objective_hexes?: [number, number][];
  colors: {
    background: string;
    cell_even: string;
    cell_odd: string;
    cell_border: string;
    player_1: string;
    player_2: string;
    hp_full: string;
    hp_damaged: string;
    highlight: string;
    current_unit: string;
    eligible?: string;
    attack?: string;
    charge?: string;
    objective_zone?: string;
    wall?: string;
    objective: string;
  };
  objective_zones?: ObjectiveZone[];
  terrain_zones?: ObjectiveZone[];
  deployment_zones?: Array<{
    id: string;
    name?: string;
    shape?: string;
    vertices?: [number, number][];
    objective?: boolean;
  }>;
  terrain_icons?: Array<{
    id: number | string;
    name: string;
    path: string;
    center: [number, number];
    size?: number;
    alpha?: number;
  }>;
  walls?: Wall[];
  display?: DisplayConfig;
}

interface GameRules {
  max_turns: number;
  turn_limit_penalty: number;
  los_debug_show_ratio: boolean;
  los_debug_show_ratio_rule: string;
  max_units_per_player: number;
  board_size?: [number, number];
  engagement_zone?: number;
  /** Plafond diamètre hex (prune engagement moteur, défaut côté JSON). */
  max_base_size_hex?: number;
}

interface ChargeConfig {
  charge_max_distance: number;
  select_target_before_roll: boolean;
}

interface GameConfig {
  game_rules: GameRules;
  charge: ChargeConfig;
  gameplay: {
    phase_order: string[];
    simultaneous_actions: boolean;
    auto_end_turn: boolean;
  };
  ai_behavior: {
    timeout_ms: number;
    retries: number;
    fallback_action: string;
  };
  scoring?: {
    win_bonus: number;
    lose_penalty: number;
    survival_bonus_per_turn: number;
  };
}

interface ExtendedGameConfig {
  boardConfig: BoardConfig | null;
  gameConfig: GameConfig | null;
  loading: boolean;
  error: string | null;
  maxTurns: number;
  boardSize: [number, number];
  turnPenalty: number;
}

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === "object" && value !== null;
};

const isBoardConfig = (value: unknown): value is BoardConfig => {
  if (!isRecord(value)) return false;
  if (
    typeof value.cols !== "number" ||
    typeof value.rows !== "number" ||
    typeof value.hex_radius !== "number" ||
    typeof value.margin !== "number" ||
    typeof value.inches_to_subhex !== "number"
  ) {
    return false;
  }
  if (!Array.isArray(value.wall_hexes)) {
    return false;
  }
  if (value.objective_hexes !== undefined && !Array.isArray(value.objective_hexes)) {
    return false;
  }
  if (!isRecord(value.colors)) {
    return false;
  }
  return true;
};

const isGameConfig = (value: unknown): value is GameConfig => {
  if (!isRecord(value)) return false;
  if (!isRecord(value.game_rules)) return false;
  if (!isRecord(value.gameplay)) return false;
  if (!isRecord(value.ai_behavior)) return false;
  if (typeof value.game_rules.max_turns !== "number") return false;
  if (typeof value.game_rules.los_debug_show_ratio !== "boolean") return false;
  if (typeof value.game_rules.los_debug_show_ratio_rule !== "string") return false;
  if (value.game_rules.board_size !== undefined && !Array.isArray(value.game_rules.board_size)) {
    return false;
  }
  if (value.scoring !== undefined && !isRecord(value.scoring)) {
    return false;
  }
  return true;
};

/**
 * Règles de jeu seules (`/config/game_config.json`). Asset statique : ne dépend ni de la
 * résolution du plateau ni du scénario, donc chargé une fois pour toutes.
 *
 * À préférer à `useGameConfig` quand le plateau n'est pas consommé — sinon la page paie une
 * requête `/api/config/board` (lecture et conversion du terrain côté serveur) dont le résultat
 * est jeté. C'est le cas de `BoardReplay`, qui n'a besoin que des règles.
 */
export const useStaticGameConfig = (): {
  gameConfig: GameConfig | null;
  error: string | null;
} => {
  const [gameConfig, setGameConfig] = useState<GameConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // biome-ignore lint/style/noRestrictedGlobals: asset statique servi par Vite, pas une route API
        const gameResponse = await fetch("/config/game_config.json");
        if (!gameResponse.ok) {
          throw new Error(
            `Game config missing: /config/game_config.json (HTTP ${gameResponse.status})`
          );
        }
        const gameResponseText = await gameResponse.text();
        if (!gameResponseText.trim()) {
          throw new Error("Game config file is empty");
        }
        let gameDataRaw: unknown;
        try {
          gameDataRaw = JSON.parse(gameResponseText);
        } catch (parseError) {
          throw new Error(`Invalid JSON in game config: ${parseError}`);
        }
        if (!isGameConfig(gameDataRaw)) {
          throw new Error("Invalid game config: missing required properties");
        }
        if (cancelled) return;
        setGameConfig(gameDataRaw);
      } catch (err) {
        if (cancelled) return;
        const errorMessage = err instanceof Error ? err.message : "Failed to load configuration";
        setError(errorMessage);
        console.error("Game config loading error:", err);
        setGameConfig(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { gameConfig, error };
};

/**
 * `inchesToSubhexOverride` (cases par pouce : 1, 5 ou 10) et `scenarioFileOverride` (chemin de
 * scénario relatif à la racine du dépôt) laissent l'appelant désigner le plateau à charger quand
 * il ne se déduit pas de l'URL. C'est le cas du replay, qui les tient de son journal :
 * cf. Documentation/Chantiers/Replay.md §2.4. La résolution est transmise TELLE QUELLE au
 * serveur, qui seul connaît les dossiers de plateau — le navigateur n'a aucune table à tenir.
 */
export const useGameConfig = (options?: {
  inchesToSubhexOverride?: number;
  scenarioFileOverride?: string;
}): ExtendedGameConfig => {
  const inchesToSubhexOverride = options?.inchesToSubhexOverride;
  const scenarioFileOverride = options?.scenarioFileOverride;
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [boardError, setBoardError] = useState<string | null>(null);
  const { gameConfig, error: gameError } = useStaticGameConfig();

  useEffect(() => {
    // Cet effet re-tourne à chaque changement de résolution ou de scénario, donc deux chargements
    // peuvent être en vol. `AbortController` coupe la requête périmée à la source — sans lui, elle
    // irait au bout du travail serveur (lecture et downscale du terrain) pour être jetée ensuite —
    // et `cancelled` empêche l'écriture d'état si la réponse est déjà partie. Sans ces deux gardes,
    // c'est le chargement le plus LENT qui gagne, pas le plus récent.
    const controller = new AbortController();
    let cancelled = false;
    const loadBoardConfig = async () => {
      try {
        const urlParams = new URLSearchParams(window.location.search);
        const mode = urlParams.get("mode");
        const isTestMode = mode === "pvp_test" || mode === "pve_test";
        const DEFAULT_TEST_BOARD = "x5_44x60";
        const boardParam = isTestMode ? (urlParams.get("board") ?? DEFAULT_TEST_BOARD) : null;
        const terrainParam = resolveSelectedTerrain(mode, window.location.search);
        const terrainSuffix =
          terrainParam === "mc1" ? "_mc1" : terrainParam === "pfm2" ? "_pfm2" : "";
        const scenarioName =
          mode === "pve_test"
            ? `scenario_pve_test${terrainSuffix}.json`
            : `scenario_pvp_test${terrainSuffix}.json`;
        // Dossier qui PORTE les scénarios de test : il ne suit pas la résolution jouée. `x1` et
        // `x5_44x60` sont le même plateau 44×60 à deux résolutions, et le moteur convertit les
        // coordonnées (cf. Documentation/Reference/moteur/geometrie_et_distances.md). Les entrées
        // `x5` -> board/180x156 et `x10` -> board/360x312 ont été retirées : dossiers inexistants.
        const boardDirMap: Record<string, string> = {
          x1: "board/44x60x5",
          x5_44x60: "board/44x60x5",
        };
        // Le PvE a sa propre table de suffixes : son scénario NON suffixé est celui de mc1.
        const pveSuffix = terrainParam === "mc2" ? "_mc2" : terrainParam === "pfm2" ? "_pfm2" : "";
        const pveScenario = `config/board/44x60x5/scenario/scenario_pve${pveSuffix}.json`;
        const scenarioMap: Record<string, string> = {
          endless_duty: "config/scenario_endless_duty.json",
          pve: pveScenario,
        };
        // Le sélecteur de terrain agit aussi en PvP : le scénario suffixé doit être celui que
        // `POST /api/game/start` résout côté serveur, sinon le plateau dessiné et le plateau
        // joué divergeraient.
        const pvpScenario = `config/board/44x60x5/scenario/scenario_pvp${terrainSuffix}.json`;
        const scenarioFile =
          scenarioFileOverride ??
          (isTestMode && boardParam && boardDirMap[boardParam]
            ? `config/${boardDirMap[boardParam]}/scenario/${scenarioName}`
            : (mode && scenarioMap[mode]) || pvpScenario);
        let boardUrl =
          "/api/config/board?scenario_file=" +
          encodeURIComponent(scenarioFile) +
          "&_t=" +
          Date.now();
        if (inchesToSubhexOverride !== undefined) {
          boardUrl += `&inches_to_subhex=${inchesToSubhexOverride}`;
        } else if (boardParam) {
          boardUrl += `&board_path=${encodeURIComponent(boardParam)}`;
        }
        const boardResponse = await apiFetch(boardUrl, { signal: controller.signal });

        if (!boardResponse.ok) {
          throw new Error(`Board config missing: /api/config/board (HTTP ${boardResponse.status})`);
        }

        const boardJson = await boardResponse.json();

        if (!isRecord(boardJson) || !boardJson.success || !boardJson.config) {
          throw new Error("Invalid board config response from API");
        }
        const configData = boardJson.config;
        if (!isBoardConfig(configData)) {
          throw new Error("Invalid board config: missing required properties");
        }
        // La résolution SERVIE doit être celle DEMANDÉE. C'est ici, et nulle part ailleurs, que la
        // requête et sa réponse coexistent : le consommateur, lui, ne verrait qu'une config sans
        // savoir pour quelle demande elle a été produite. Sans ce contrôle, un `inches_to_subhex`
        // qui n'atteint pas l'API fait servir le plateau par DÉFAUT, et le replay fusionne un décor
        // x5 avec la grille x1 du journal : décor cinq fois trop grand, murs et unités justes,
        // aucune erreur. C'est le mode de panne décrit en Documentation/Chantiers/Replay.md
        // §2.4 — il ne se voyait qu'à l'œil, sur un plateau déjà dessiné.
        if (
          inchesToSubhexOverride !== undefined &&
          configData.inches_to_subhex !== inchesToSubhexOverride
        ) {
          throw new Error(
            `Board served at inches_to_subhex=${configData.inches_to_subhex} ` +
              `(${configData.cols}x${configData.rows}) but ${inchesToSubhexOverride} was requested ` +
              `for ${scenarioFile}`
          );
        }

        if (cancelled) return;
        setBoardError(null);
        setBoardConfig(configData);
      } catch (err) {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        const errorMessage = err instanceof Error ? err.message : "Failed to load configuration";
        setBoardError(errorMessage);
        console.error("Board config loading error:", err);

        setBoardConfig(null);
      }
    };

    loadBoardConfig();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [inchesToSubhexOverride, scenarioFileOverride]);

  const error = boardError ?? gameError;
  // `loading` est DÉRIVÉ, il n'est plus un état posé au début de chaque chargement. Un
  // rafraîchissement (changement d'épisode en replay) garde donc la config précédente affichée au
  // lieu de repasser par un écran « Loading… » qui, chez les consommateurs PIXI, détruit et
  // reconstruit tout le plateau alors que seul le décor a changé.
  const loading = error === null && (boardConfig === null || gameConfig === null);

  const maxTurns = gameConfig?.game_rules.max_turns ?? 100;
  const boardSize: [number, number] = gameConfig?.game_rules.board_size ?? [24, 18];
  const turnPenalty = gameConfig?.game_rules.turn_limit_penalty ?? -1;

  return {
    boardConfig,
    gameConfig,
    loading,
    error,
    maxTurns,
    boardSize,
    turnPenalty,
  };
};

export default useGameConfig;
