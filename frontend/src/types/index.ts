// frontend/src/types/index.ts
// Game types
export type {
  PlayerId,
  UnitId,
  GamePhase,
  GameMode,
  Position,
  Unit,
  GameState,
  MovePreview,
  AttackPreview,
  AIGameState,
  AIAction,
  GameActions,
} from './game';

// API types
export type {
  APIResponse,
  APIError,
  AIActionRequest,
  AIActionResponse,
  RequestConfig,
} from './api';

// Type guards
export { isValidMode, isValidPlayerId, createPhaseValidator } from '../constants/gameConfig';

// Re-export commonly used types for easier imports
export type GameConfig = {
  boardCols: number;
  boardRows: number;
  hexRadius: number;
  enableAI: boolean;
  enableSound: boolean;
  enableAnimations: boolean;
};

export type ComponentProps<T = Record<string, unknown>> = T & {
  className?: string;
  children?: React.ReactNode;
};