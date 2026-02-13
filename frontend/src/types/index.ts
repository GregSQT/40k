// frontend/src/types/index.ts
// Game types

// Type guards
export { createPhaseValidator, isValidMode, isValidPlayerId } from "../constants/gameConfig";

// API types
export type {
  AIActionRequest,
  AIActionResponse,
  APIError,
  APIResponse,
  RequestConfig,
} from "./api";
export type {
  ActionResult,
  AttackPreview,
  FightPhaseState,
  FightSubPhase,
  GameMode,
  GamePhase,
  GameState,
  MovePreview,
  PlayerId,
  Position,
  SemanticAction,
  ShootingPhaseState,
  SingleAttackState,
  SingleShotState,
  TargetPreview,
  Unit,
  UnitId,
} from "./game";

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
