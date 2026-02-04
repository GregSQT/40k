// frontend/src/types/game.ts

export type PlayerId = 1 | 2;
export type UnitId = number;
export type GamePhase = "command" | "move" | "shoot" | "charge" | "fight";
export type GameMode = "select" | "movePreview" | "attackPreview" | "targetPreview" | "chargePreview" | "advancePreview";
// AI_TURN.md COMPLIANCE: Fight subphase names match backend exactly
export type FightSubPhase = "charging" | "alternating_non_active" | "alternating_active" | "cleanup_non_active" | "cleanup_active" | null;

// NEW: Debug reward display fields
export interface ActionReward {
  action_name: string;
  reward: number;
  is_ai_action: boolean;
}

export interface Position {
  col: number;
  row: number;
}

export type DiceValue = number | "D3" | "D6";

export interface Weapon {
  display_name: string;
  COMBI_WEAPON?: string;
  RNG?: number;
  NB: DiceValue;
  ATK: number;
  STR: number;
  AP: number;
  DMG: DiceValue;
  WEAPON_RULES?: string[];
}

export interface WeaponOption {
  index: number;
  weapon: Weapon;
  canUse: boolean;
  reason?: string;
}

export interface WeaponSelectionState {
  isActive: boolean;
  unitId: UnitId;
  weapons: WeaponOption[];
  hasAdvanced: boolean;
  position?: { x: number; y: number };
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
  
  // Multiple weapons system (MULTIPLE_WEAPONS_IMPLEMENTATION.md)
  RNG_WEAPONS: Weapon[];           // Armes à distance (max 3)
  CC_WEAPONS: Weapon[];             // Armes de mêlée (max 2)
  selectedRngWeaponIndex?: number;  // Index de l'arme ranged sélectionnée
  selectedCcWeaponIndex?: number;   // Index de l'arme melee sélectionnée
  
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

export interface FightPhaseState {
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
  
  // AI_TURN.md tracking sets (Frontend format - converted from Engine string[] to UnitId[])
  unitsMoved?: UnitId[];
  unitsFled?: UnitId[];
  units_shot?: string[]; // Not used in frontend, kept for compatibility
  unitsCharged?: UnitId[];
  unitsAttacked?: UnitId[];
  unitsAdvanced?: UnitId[];
  
  // Engine specific
  move_activation_pool?: string[];
  shoot_activation_pool?: string[];
  charge_activation_pool?: string[];
  board_width?: number;
  board_height?: number;
  wall_hexes?: number[][];
  
  // Fight phase pools (AI_TURN.md)
  fight_subphase?: FightSubPhase;
  charging_activation_pool?: string[];
  active_alternating_activation_pool?: string[];
  non_active_alternating_activation_pool?: string[];
  
  // Frontend specific
  mode?: GameMode;
  selectedUnitId?: UnitId | null;
  targetPreview?: TargetPreview | null;
  fightSubPhase?: FightSubPhase;
  fightActivePlayer?: PlayerId;
  unitChargeRolls?: Record<UnitId, number>;
  pve_mode?: boolean; // Add PvE mode flag
  active_movement_unit?: string; // Active unit ID in movement phase
  active_shooting_unit?: string; // Active unit ID in shooting phase
  active_fight_unit?: string; // Active unit ID in fight phase
  active_charge_unit?: string; // Active unit ID in charge phase
}

export interface SemanticAction {
  action: "move" | "skip" | "shoot" | "charge" | "fight";
  unitId: string;
  destCol?: number;
  destRow?: number;
  targetId?: string;
}

export interface ActionResult {
  success: boolean;
  result: unknown;
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