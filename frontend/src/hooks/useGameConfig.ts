// frontend/src/hooks/useGameConfig.ts
import { useState, useEffect } from 'react';

interface GameConfig {
  game_rules: {
    max_turns: number;
    turn_limit_penalty: number;
    charge_max_distance: number;
  };
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
  api: {
    prefix: string;
    action_endpoint: string;
    actions_endpoint: string;
  };
  ui: {
    log_available_height: number;
  };
}

export function useGameConfig() {
  const [config, setConfig] = useState<GameConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        setLoading(true);
        setError(null);

        const response = await fetch('/config/game_config.json');
        
        if (!response.ok) {
          throw new Error(`Failed to load game config: HTTP ${response.status}`);
        }

        const responseText = await response.text();
        
        if (!responseText.trim()) {
          throw new Error('Game config file is empty');
        }

        const gameData = JSON.parse(responseText);
        
        // Validate required sections
        if (!gameData.game_rules) {
          throw new Error('Game config missing required game_rules section');
        }

        if (!gameData.game_rules.max_turns) {
          throw new Error('Game config missing required game_rules.max_turns');
        }

        setConfig(gameData);

      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load configuration';
        setError(errorMessage);
        console.error('Game config loading error:', err);
        setConfig(null);
      } finally {
        setLoading(false);
      }
    };

    loadConfig();
  }, []);

  return { config, loading, error };
}