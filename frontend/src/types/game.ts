// frontend/src/types/game.ts

export type PlayerId = 0 | 1;
export type UnitId = number;
export type GamePhase = "move" | "shoot" | "charge" | "combat";
export type GameMode = "select" | "movePreview" | "attackPreview" | "chargePreview";
export type CombatSubPhase = "charged_units" | "alternating_combat";

export interface Position {
  col: number;
  row: number;
}

export interface Unit {
  id: UnitId;
  name?: string;
  type?: string;
  unitType?: string;
  player: PlayerId;
  col: number;
  row: number;
  color?: number;
  
  // Engine UPPERCASE fields (AI_TURN.md compliance)
  HP_CUR: number;
  HP_MAX?: number;
  MOVE: number;
  T?: number;
  ARMOR_SAVE?: number;
  INVUL_SAVE?: number;
  LD?: number;
  OC?: number;
  VALUE?: number;
  
  // Ranged combat (UPPERCASE per AI_TURN.md)
  RNG_NB?: number;
  RNG_RNG: number;
  RNG_ATK?: number;
  RNG_STR?: number;
  RNG_DMG: number;
  RNG_AP?: number;
  
  // Close combat (UPPERCASE per AI_TURN.md)
  CC_NB?: number;
  CC_RNG?: number;
  CC_ATK?: number;
  CC_STR?: number;
  CC_DMG: number;
  CC_AP?: number;
  
  // Display properties
  ICON: string;
  ICON_SCALE?: number;
  
  // Game state tracking
  SHOOT_LEFT?: number;
  ATTACK_LEFT?: number;
  hasChargedThisTurn?: boolean;
}

export interface SingleShotState {
  isActive: boolean;
  shooterId: UnitId;
  targetId: UnitId | null;
  currentShotNumber: number;
  totalShots: number;
  shotsRemaining: number;
  isSelectingTarget: boolean;
  currentStep: 'target_selection' | 'hit_roll' | 'wound_roll' | 'save_roll' | 'damage_application' | 'complete';
  stepResults: {
    hitRoll?: number;
    hitSuccess?: boolean;
    woundRoll?: number;
    woundSuccess?: boolean;
    saveRoll?: number;
    saveSuccess?: boolean;
    damageDealt?: number;
  };
}

export interface SingleAttackState {
  isActive: boolean;
  attackerId: UnitId;
  targetId: UnitId | null;
  currentAttackNumber: number;
  totalAttacks: number;
  attacksRemaining: number;
  isSelectingTarget: boolean;
  currentStep: 'target_selection' | 'hit_roll' | 'wound_roll' | 'save_roll' | 'damage_application' | 'complete';
  stepResults: {
    hitRoll?: number;
    hitSuccess?: boolean;
    woundRoll?: number;
    woundSuccess?: boolean;
    saveRoll?: number;
    saveSuccess?: boolean;
    damageDealt?: number;
  };
}

export interface ShootingPhaseState {
  activeShooters: UnitId[];
  currentShooter: UnitId | null;
  singleShotState: SingleShotState | null;
}

export interface CombatPhaseState {
  activeAttackers: UnitId[];
  currentAttacker: UnitId | null;
  singleAttackState: SingleAttackState | null;
}

export interface TargetPreview {
  targetId: UnitId;
  shooterId: UnitId;
  currentBlinkStep: number;
  totalBlinkSteps: number;
  blinkTimer: number | null;
  hitProbability: number;
  woundProbability: number;
  saveProbability: number;
  overallProbability: number;
}

export interface GameState {
  // AI_TURN.md required fields
  episode_steps: number;
  units: Unit[];
  current_player?: number; // Engine format
  currentPlayer?: PlayerId; // Frontend format
  phase: GamePhase;
  turn?: number; // Engine format
  currentTurn?: number; // Frontend format
  game_over?: boolean;
  winner?: number | null;
  
  // AI_TURN.md tracking sets
  units_moved?: string[]; // Engine format
  unitsMoved?: UnitId[]; // Frontend format
  units_fled?: string[];
  unitsFled?: UnitId[];
  units_shot?: string[];
  units_charged?: string[];
  unitsCharged?: UnitId[];
  units_attacked?: string[];
  unitsAttacked?: UnitId[];
  
  // Engine specific
  move_activation_pool?: string[];
  board_width?: number;
  board_height?: number;
  wall_hexes?: number[][];
  
  // Frontend specific
  mode?: GameMode;
  selectedUnitId?: UnitId | null;
  targetPreview?: TargetPreview | null;
  combatSubPhase?: CombatSubPhase;
  combatActivePlayer?: PlayerId;
  unitChargeRolls?: Record<UnitId, number>;
}

export interface SemanticAction {
  action: "move" | "skip" | "shoot" | "charge" | "attack";
  unitId: string;
  destCol?: number;
  destRow?: number;
  targetId?: string;
}

export interface ActionResult {
  success: boolean;
  result: any;
  game_state: GameState;
  message?: string;
  error?: string;
}

export interface MovePreview {
  unitId: UnitId;
  destCol: number;
  destRow: number;
}

export interface AttackPreview {
  unitId: UnitId;
  col: number;
  row: number;
}