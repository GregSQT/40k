// frontend/src/hooks/useGameConfig.ts
import { useState, useEffect } from 'react';

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
  };
}

interface GameConfig {
  boardConfig: BoardConfig | null;
  loading: boolean;
  error: string | null;
}

// Fallback board configuration
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
    current_unit: "0xffd700"
  }
};

export const useGameConfig = (boardConfigName: string = "default"): GameConfig => {
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadConfigs = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // Only load board config - unit definitions come from TypeScript classes
        const boardResponse = await fetch(`/ai/config/board_config.json`);
        
        if (!boardResponse.ok) {
          throw new Error(`Board config HTTP ${boardResponse.status}: ${boardResponse.statusText}`);
        }
        
        const boardResponseText = await boardResponse.text();
        
        // Validate JSON before parsing
        if (!boardResponseText.trim()) {
          throw new Error('Board config file is empty');
        }
        
        let boardData;
        try {
          boardData = JSON.parse(boardResponseText);
        } catch (parseError) {
          throw new Error(`Invalid JSON in board config: ${parseError}`);
        }
        
        if (!boardData[boardConfigName]) {
          console.warn(`Board config '${boardConfigName}' not found, available configs:`, Object.keys(boardData));
          throw new Error(`Board config '${boardConfigName}' not found`);
        }
        
        setBoardConfig(boardData[boardConfigName]);

      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to load configuration';
        setError(errorMessage);
        console.error('Game config loading error:', err);
        
        // Use fallback configuration
        console.log('Using fallback board configuration');
        setBoardConfig(FALLBACK_BOARD_CONFIG);
        
      } finally {
        setLoading(false);
      }
    };

    loadConfigs();
  }, [boardConfigName]);

  return { boardConfig, loading, error };
};

export default useGameConfig;