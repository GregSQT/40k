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
}

interface BoardConfig {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
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
  };
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

const FALLBACK_BOARD_CONFIG: BoardConfig = {
  cols: 24,
  rows: 18,
  hex_radius: 24,
  margin: 32,
  colors: {
    background: "0x002200",
    cell_even: "0x002200", 
    cell_odd: "0x001a00",
    cell_border: "0x00ff00",
    player_0: "0x244488",
    player_1: "0x882222",
    hp_full: "0x36e36b",
    hp_damaged: "0x444444",
    highlight: "0x80ff80",
    current_unit: "0xffd700",
    eligible: "0x00ff00",
    attack: "0xff4444",
    charge: "0xff9900"
  },
  display: {
    resolution: "auto",
    autoDensity: true,
    antialias: true,
    forceCanvas: true,
    icon_scale: 1.2,
    eligible_outline_width: 3,
    eligible_outline_alpha: 0.8,
    hp_bar_width_ratio: 1.4,
    hp_bar_height: 7,
    hp_bar_y_offset_ratio: 0.85,
    unit_circle_radius_ratio: 0.6,
    unit_text_size: 10,
    selected_border_width: 4,
    charge_target_border_width: 3,
    default_border_width: 2,
    canvas_border: "1px solid #333"
  }
};

const FALLBACK_GAME_CONFIG: GameConfig = {
  game_rules: {
    max_turns: 100,
    turn_limit_penalty: -1,
    max_units_per_player: 4,
    board_size: [24, 18]
  },
  gameplay: {
    phase_order: ["move", "shoot", "charge", "combat"],
    simultaneous_actions: false,
    auto_end_turn: true
  },
  ai_behavior: {
    timeout_ms: 5000,
    retries: 3,
    fallback_action: "wait"
  },
  scoring: {
    win_bonus: 1000,
    lose_penalty: -1000,
    survival_bonus_per_turn: 1
  }
};

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
        const mergedBoardConfig: BoardConfig = {
          ...FALLBACK_BOARD_CONFIG,
          ...configData,
          colors: {
            ...FALLBACK_BOARD_CONFIG.colors,
            ...configData.colors
          },
          display: {
            ...FALLBACK_BOARD_CONFIG.display,
            ...configData.display
          }
        };

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