// frontend/src/constants/gameConfig.ts

// Derived board calculations
export const calculateHexConfig = (hexRadius: number) => ({
  WIDTH: 1.5 * hexRadius,
  HEIGHT: Math.sqrt(3) * hexRadius,
  HORIZ_SPACING: 1.5 * hexRadius,
  VERT_SPACING: Math.sqrt(3) * hexRadius,
});

// Colors
export const COLORS = {
  HIGHLIGHT: 0x90d090,     // Light green for movement (less intense)
  ATTACK: 0xd0b0b0,        // Very light pink-gray for attacks (much less intense, lighter for dark background)
  CHARGE: 0xff9900,        // Orange for charges
  SELECTION: 0xffd700,     // Gold for selection
  ELIGIBLE: 0x00ff00,      // Green for eligible units
  BACKGROUND: 0x002200,    // Dark green for board
  PLAYER_1: 0x244488,      // Blue for player 1
  PLAYER_2: 0x882222,      // Red for player 2
} as const;

// Game Timing
export const TIMING = {
  PHASE_TRANSITION_DELAY: 2000,
  AI_ACTION_DELAY: 180,
  ANIMATION_DURATION: 250,
} as const;

// AI Configuration
export const AI_CONFIG = {
  DEFAULT_TIMEOUT: 5000,
  DEFAULT_RETRIES: 3,
  RETRY_DELAY_BASE: 500,
  FALLBACK_TO_SKIP: true,
} as const;

// Dynamic phase labels based on loaded config
export const getPhaseLabelMap = (phases: string[]) => {
  const labelMap: Record<string, string> = {};
  phases.forEach(phase => {
    labelMap[phase] = phase.charAt(0).toUpperCase() + phase.slice(1);
  });
  return labelMap;
};

// Player Configuration
export const PLAYERS = {
  HUMAN: 0,
  AI: 1,
} as const;

export const PLAYER_LABELS = {
  [PLAYERS.HUMAN]: 'Player 1',
  [PLAYERS.AI]: 'Player 2 (AI)',
} as const;

// Game Modes
export const MODES = {
  SELECT: 'select',
  MOVE_PREVIEW: 'movePreview',
  ATTACK_PREVIEW: 'attackPreview',
  CHARGE_PREVIEW: 'chargePreview',
} as const;

// API Configuration
export const API_CONFIG = {
  BASE_URL: (() => {
    const apiUrl = import.meta.env?.VITE_API_URL;
    if (!apiUrl) {
      console.warn('VITE_API_URL not set, defaulting to http://localhost:5000');
      return 'http://localhost:5000';
    }
    return apiUrl;
  })(),
  ENDPOINTS: {
    AI_ACTION: '/ai/action',
  },
  HEADERS: {
    'Content-Type': 'application/json',
  },
} as const;

// Validation Rules
export const VALIDATION = {
  MIN_UNIT_HP: 1,
  MAX_UNIT_HP: 10,
  MIN_MOVE_DISTANCE: 1,
  MAX_MOVE_DISTANCE: 12,
  MIN_ATTACK_RANGE: 1,
  MAX_ATTACK_RANGE: 20,
} as const;

// Error Messages
export const ERROR_MESSAGES = {
  UNIT_NOT_FOUND: 'Unit not found',
  INVALID_MOVE: 'Invalid move',
  INVALID_ATTACK: 'Invalid attack',
  UNIT_NOT_ELIGIBLE: 'Unit is not eligible for this action',
  AI_SERVICE_ERROR: 'AI service is unavailable',
  NETWORK_ERROR: 'Network connection failed',
  TIMEOUT_ERROR: 'Request timed out',
} as const;

// Success Messages
export const SUCCESS_MESSAGES = {
  MOVE_COMPLETED: 'Move completed successfully',
  ATTACK_COMPLETED: 'Attack completed successfully',
  CHARGE_COMPLETED: 'Charge completed successfully',
  PHASE_COMPLETED: 'Phase completed',
  TURN_COMPLETED: 'Turn completed',
} as const;

// Feature Flags
export const FEATURES = {
  ENABLE_AI: true,
  ENABLE_SOUND: false,
  ENABLE_ANIMATIONS: true,
  ENABLE_TOOLTIPS: true,
  ENABLE_KEYBOARD_SHORTCUTS: false,
  ENABLE_REPLAY_SYSTEM: true,
  ENABLE_DEBUG_MODE: import.meta.env?.MODE === 'development',
} as const;

// Performance Configuration
export const PERFORMANCE = {
  MAX_UNITS_PER_PLAYER: 20,
  MAX_BOARD_SIZE: 50,
  RENDER_THROTTLE_MS: 16, // 60fps
  STATE_UPDATE_THROTTLE_MS: 10,
} as const;

// Accessibility Configuration
export const A11Y = {
  ENABLE_SCREEN_READER: true,
  ENABLE_HIGH_CONTRAST: false,
  ENABLE_REDUCED_MOTION: false,
  FOCUS_OUTLINE_WIDTH: 2,
  MIN_TOUCH_TARGET_SIZE: 44,
} as const;

// Development Configuration
export const DEV_CONFIG = {
  ENABLE_LOGGING: import.meta.env?.MODE === 'development',
  LOG_LEVEL: (() => {
    const logLevel = import.meta.env?.VITE_LOG_LEVEL;
    if (logLevel === undefined) {
      return 'info';
    }
    return logLevel;
  })(),
  ENABLE_PERFORMANCE_MONITORING: false,
  ENABLE_ERROR_REPORTING: import.meta.env?.MODE === 'production',
} as const;

// Dynamic types based on loaded config
export type GamePhase = string; // Dynamic from config
export type GameMode = typeof MODES[keyof typeof MODES];
export type PlayerId = typeof PLAYERS[keyof typeof PLAYERS];

// Helper functions with dynamic phase checking
export const createPhaseValidator = (validPhases: string[]) => {
  return (phase: string): phase is GamePhase => {
    return validPhases.includes(phase);
  };
};

export const isValidMode = (mode: string): mode is GameMode => {
  return Object.values(MODES).includes(mode as GameMode);
};

export const isValidPlayerId = (id: number): id is PlayerId => {
  return Object.values(PLAYERS).includes(id as PlayerId);
};

// Dynamic configuration validator
export const validateDynamicConfig = (boardConfig: any, _gameConfig: any) => {
  const errors: string[] = [];

  if (!boardConfig?.cols || boardConfig.cols <= 0) errors.push('Board columns must be positive');
  if (!boardConfig?.rows || boardConfig.rows <= 0) errors.push('Board rows must be positive');
  if (!boardConfig?.hex_radius || boardConfig.hex_radius <= 0) errors.push('Hex radius must be positive');
  if (TIMING.AI_ACTION_DELAY < 0) errors.push('AI action delay cannot be negative');
  if (AI_CONFIG.DEFAULT_RETRIES < 0) errors.push('AI retries cannot be negative');

  if (errors.length > 0) {
    throw new Error(`Configuration validation failed:\n${errors.join('\n')}`);
  }

  return true;
};
