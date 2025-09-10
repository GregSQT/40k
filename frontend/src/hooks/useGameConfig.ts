// frontend/src/hooks/useGameConfig.ts
import { useState, useEffect } from 'react';

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
}

interface ObjectiveZone {
  id: string;
  hexes: Array<{ col: number; row: number }>;
}

interface Wall {
  id: string;
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
  objective_hexes: [number, number][];
  colors: {
    background: string;
    cell_even: string;
    cell_odd: string;
    cell_border: string;
    player_0: string;
    player_1: string;
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
  max_units_per_player: number;
  board_size: [number, number];
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
  scoring: {
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

export const useGameConfig = (boardConfigName: string = "default"): ExtendedGameConfig => {
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [gameConfig, setGameConfig] = useState<GameConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadConfigs = async () => {
      try {
        setLoading(true);
        setError(null);

        const [boardResponse, gameResponse] = await Promise.all([
          fetch('/config/board_config.json'),
          fetch('/config/game_config.json')
        ]);

        if (!gameResponse.ok) {
          throw new Error(`Game config missing: /config/game_config.json (HTTP ${gameResponse.status})`);
        }

        if (!boardResponse.ok) {
          throw new Error(`Board config missing: /config/board_config.json (HTTP ${boardResponse.status})`);
        }

        const [boardResponseText, gameResponseText] = await Promise.all([
          boardResponse.text(),
          gameResponse.text()
        ]);

        if (!boardResponseText.trim()) {
          throw new Error('Board config file is empty');
        }

        if (!gameResponseText.trim()) {
          throw new Error('Game config file is empty');
        }

        let boardData, gameData;
        try {
          boardData = JSON.parse(boardResponseText);
          gameData = JSON.parse(gameResponseText);
        } catch (parseError) {
          throw new Error(`Invalid JSON in config files: ${parseError}`);
        }

        if (!boardData[boardConfigName]) {
          console.warn(`Board config '${boardConfigName}' not found, available configs:`, Object.keys(boardData));
          throw new Error(`Board config '${boardConfigName}' not found`);
        }

        const configData = boardData[boardConfigName];
        const mergedBoardConfig: BoardConfig = configData;

        // Validate required properties
        if (!configData.cols || !configData.rows || !configData.hex_radius) {
          throw new Error(`Invalid board config: missing required properties`);
        }

        setBoardConfig(mergedBoardConfig);
        setGameConfig(gameData);

      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load configuration';
        setError(errorMessage);
        console.error('Game config loading error:', err);

        setBoardConfig(null);
        setGameConfig(null);

      } finally {
        setLoading(false);
      }
    };

    loadConfigs();
  }, [boardConfigName]);

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
    turnPenalty
  };
};

export default useGameConfig;