// frontend/src/hooks/useGameConfig.ts
import { useState, useEffect } from 'react';

interface GameConfig {
  board: {
    width: number;
    height: number;
    wall_hexes: any[];
  };
  // Add other config properties as needed
}

export function useGameConfig() {
  const [config, setConfig] = useState<GameConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        // Placeholder - will load from actual config files
        const defaultConfig: GameConfig = {
          board: {
            width: 24,
            height: 18,
            wall_hexes: []
          }
        };
        setConfig(defaultConfig);
        setLoading(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Config load error');
        setLoading(false);
      }
    };

    loadConfig();
  }, []);

  return { config, loading, error };
}