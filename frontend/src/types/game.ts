// frontend/src/types/game.ts

export type PlayerId = 0 | 1;
export type UnitId = number;
export type GamePhase = "move" | "shoot" | "charge" | "combat";
export type GameMode = "select" | "movePreview" | "attackPreview" | "chargePreview";

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
  ICON: string;
  // Dice system properties
  RNG_NB?: number;    // Number of shots
  RNG_ATK?: number;   // Hit skill (percentage)
  RNG_STR?: number;   // Strength for wounding
  RNG_AP?: number;    // Armor penetration
  T?: number;         // Toughness
  ARMOR_SAVE?: number; // Armor save (D6 target)
  INVUL_SAVE?: number; // Invulnerable save (D6 target)
  SHOOT_LEFT?: number; // Shots remaining this phase
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

export interface ShootingPhaseState {
  activeShooters: UnitId[];
  currentShooter: UnitId | null;
  singleShotState: SingleShotState | null;
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