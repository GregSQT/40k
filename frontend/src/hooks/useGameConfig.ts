// frontend/src/hooks/useGameConfig.ts
import { useEffect, useState } from "react";

interface DisplayConfig {
  resolution?: "auto" | number;
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
  wall_texture?: string;
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

interface ObjectiveZone {
  id: string;
  hexes: Array<{ col: number; row: number }>;
}

interface Wall {
  id?: string;
  start: { col: number; row: number };
  end: { col: number; row: number };
  thickness?: number;
}

interface BoardConfig {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
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
  walls?: Wall[];
  display?: DisplayConfig;
}

interface GameRules {
  max_turns: number;
  turn_limit_penalty: number;
  los_visibility_min_ratio: number;
  cover_ratio: number;
  cover_ratio_rule: string;
  los_debug_show_ratio: boolean;
  los_debug_show_ratio_rule: string;
  max_units_per_player: number;
  board_size?: [number, number];
}

interface GameConfig {
  game_rules: GameRules;
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
    typeof value.margin !== "number"
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
  if (typeof value.game_rules.los_visibility_min_ratio !== "number") return false;
  if (typeof value.game_rules.cover_ratio !== "number") return false;
  if (typeof value.game_rules.cover_ratio_rule !== "string") return false;
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

export const useGameConfig = (_boardConfigName: string = "default"): ExtendedGameConfig => {
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [gameConfig, setGameConfig] = useState<GameConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadConfigs = async () => {
      try {
        setLoading(true);
        setError(null);

        const urlParams = new URLSearchParams(window.location.search);
        const mode = urlParams.get("mode");
        const scenarioMap: Record<string, string> = {
          tutorial: "config/tutorial/scenario_etape1.json",
          endless_duty: "config/scenario_endless_duty.json",
          pvp_test: "config/scenario_pvp_test.json",
          pve_test: "config/scenario_pve_test.json",
          pve: "config/scenario_pve.json",
        };
        const scenarioFile = (mode && scenarioMap[mode]) || "config/scenario_pvp.json";
        const boardUrl =
          "/api/config/board?scenario_file=" +
          encodeURIComponent(scenarioFile) +
          "&_t=" + Date.now();
        const [boardResponse, gameResponse] = await Promise.all([
          fetch(boardUrl),
          fetch("/config/game_config.json"),
        ]);

        if (!gameResponse.ok) {
          throw new Error(
            `Game config missing: /config/game_config.json (HTTP ${gameResponse.status})`
          );
        }

        if (!boardResponse.ok) {
          throw new Error(
            `Board config missing: /api/config/board (HTTP ${boardResponse.status})`
          );
        }

        const boardJson = await boardResponse.json();
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

        if (!isRecord(boardJson) || !boardJson.success || !boardJson.config) {
          throw new Error("Invalid board config response from API");
        }
        const configData = boardJson.config;
        if (!isBoardConfig(configData)) {
          throw new Error("Invalid board config: missing required properties");
        }
        if (!isGameConfig(gameDataRaw)) {
          throw new Error("Invalid game config: missing required properties");
        }

        setBoardConfig(configData);
        setGameConfig(gameDataRaw);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Failed to load configuration";
        setError(errorMessage);
        console.error("Game config loading error:", err);

        setBoardConfig(null);
        setGameConfig(null);
      } finally {
        setLoading(false);
      }
    };

    loadConfigs();
  }, []);

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
