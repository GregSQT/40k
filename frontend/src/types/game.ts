// frontend/src/types/game.ts

export type PlayerId = 0 | 1;
export type UnitId = number;
export type GamePhase = "move" | "shoot" | "charge" | "combat";
export type GameMode = "select" | "movePreview" | "attackPreview" | "chargePreview";
export type CombatSubPhase = "charged_units" | "alternating_combat"; // NEW: Combat sub-phases

export interface Position {
  col: number;
  row: number;
}

export interface Unit {
  id: UnitId;
  name: string;
  type: string;
  player: PlayerId;
  col: number;
  row: number;
  color: number;
  BASE: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP?: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  CC_RNG?: number;    // ✅ ADD: Close combat range
  ICON: string;
  ICON_SCALE?: number;  // ✅ NEW: Per-unit icon scaling
  // Dice system properties
  RNG_NB?: number;    // Number of shots
  RNG_ATK?: number;   // Hit skill (percentage)
  RNG_STR?: number;   // Strength for wounding
  RNG_AP?: number;    // Armor penetration
  CC_NB?: number;     // Number of melee attacks
  CC_ATK?: number;    // Melee hit skill
  CC_STR?: number;    // Melee strength for wounding
  CC_AP?: number;     // Melee armor penetration
  T?: number;         // Toughness
  ARMOR_SAVE?: number; // Armor save (D6 target)
  INVUL_SAVE?: number; // Invulnerable save (D6 target)
  SHOOT_LEFT?: number; // Shots remaining this phase
  ATTACK_LEFT?: number; // Attacks remaining this phase
  hasChargedThisTurn?: boolean; // NEW: Track if unit charged this turn
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
  blinkTimer: NodeJS.Timeout | null;
  hitProbability: number;
  woundProbability: number;
  saveProbability: number;
  overallProbability: number;
}

export interface GameState {
  units: Unit[];
  currentPlayer: PlayerId;
  phase: GamePhase;
  mode: GameMode;
  selectedUnitId: UnitId | null;
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
  unitsFled: UnitId[];  // Track units that fled (moved away from adjacent enemies)
  targetPreview: TargetPreview | null;
  currentTurn: number;  // Track current turn (1-based)
  combatSubPhase?: CombatSubPhase; // NEW: Track combat sub-phase
  combatActivePlayer?: PlayerId; // NEW: Track who's turn it is in alternating combat
  unitChargeRolls: Record<UnitId, number>; // Store 2d6 charge rolls for each unit
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

// AI Types
export interface AIGameState {
  units: Array<{
    id: UnitId;
    player: PlayerId;
    col: number;
    row: number;
    CUR_HP: number;
    MOVE: number;
    RNG_RNG: number;
    RNG_DMG: number;
    CC_DMG: number;
  }>;
}

export interface AIAction {
  action: "move" | "moveAwayToRngRng" | "shoot" | "charge" | "attack" | "skip";
  unitId: UnitId;
  destCol?: number;
  destRow?: number;
  targetId?: UnitId;
}

export interface GameActions {
  selectUnit: (unitId: UnitId | null) => void;
  startMovePreview: (unitId: UnitId, col: number, row: number) => void;
  startAttackPreview: (unitId: UnitId, col: number, row: number) => void;
  confirmMove: () => void;
  cancelMove: () => void;
  handleShoot: (shooterId: UnitId, targetId: UnitId) => void;
  handleCombatAttack: (attackerId: UnitId, targetId: UnitId | null) => void;
  handleCharge: (chargerId: UnitId, targetId: UnitId) => void;
  moveCharger: (chargerId: UnitId, destCol: number, destRow: number) => void;
  cancelCharge: () => void;
  validateCharge: (chargerId: UnitId) => void;
}