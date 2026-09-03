// frontend/src/types/game.ts

export type PlayerId = 1 | 2;
export type UnitId = number;
export type GamePhase = "deployment" | "command" | "move" | "shoot" | "charge" | "fight";
export type GameMode =
  | "select"
  | "movePreview"
  | "attackPreview"
  | "targetPreview"
  | "chargePreview"
  | "advancePreview"
  | "pileInModelMove"
  | "consolidationModelMove";
// V11 (PDF 12) : sous-phases fight = pile_in -> fight -> consolidate.
export type FightSubPhase = "pile_in" | "fight" | "consolidate" | null;

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

export type DiceValue = number | "D3" | "D6" | "2D6" | "D6+1" | "D6+2" | "D6+3";

export interface PrimaryObjectiveRule {
  id: string;
  name?: string;
  identifier?: string;
  description?: string;
  scoring: {
    start_turn: number;
    max_points_per_turn: number;
    rules: Array<{ id: string; points: number; condition: string }>;
  };
  timing: {
    default_phase: string;
    round5_second_player_phase: string;
  };
  control: {
    method: string;
    control_method: string;
    tie_behavior: string;
  };
}

export interface Weapon {
  code?: string; // identite stable du profil, injectee par getWeapons (ex. cyclone_missile_launcher_krak)
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
  color?: number;
  /** Tir squad : true si cette arme a déjà une cible désignée (texte grisé dans le menu). */
  assigned?: boolean;
  /** Tir squad : true si un AUTRE profil de la même arme combinée est assigné (clic bloqué). */
  locked?: boolean;
}

export interface WeaponSelectionState {
  isActive: boolean;
  unitId: UnitId;
  weapons: WeaponOption[];
  hasAdvanced: boolean;
  position?: { x: number; y: number };
}

export interface UnitRule {
  ruleId: string;
  displayName: string;
  rule_args?: {
    distance?: number;
    [key: string]: number | undefined;
  };
  grants_rule_ids?: string[];
  usage?: "and" | "or" | "unique" | "always";
  choice_timing?: {
    trigger: "on_deploy" | "turn_start" | "player_turn_start" | "phase_start" | "activation_start";
    phase?: "command" | "move" | "shoot" | "charge" | "fight";
    active_player_scope?: "owner" | "opponent" | "both";
  };
}

export interface UnitKeyword {
  keywordId: string;
}

/** Zones de déploiement, par joueur. Donnée de SCÉNARIO : le backend les publie à la racine du
 * game_state quel que soit le mode de mise en place, alors que `DeploymentState` n'existe qu'en
 * déploiement `active`. Elles vivaient dans `DeploymentState` jusqu'à ce qu'une unité en réserves
 * 20.01 en ait besoin hors phase de déploiement. */
export type DeploymentPools = Record<
  string,
  Array<[number, number] | { col: number; row: number }>
>;

export interface DeploymentState {
  current_deployer: PlayerId;
  deployable_units: Record<string, UnitId[]>;
  deployed_units: UnitId[];
  deployment_complete: boolean;
}

/** Profil par-figurine d'une escouade (source backend ``enhanced_unit["models"]``).
 * Aligné index-pour-index avec le model_id ``<unitId>#<idx>`` (idx = position dans ce tableau).
 * Une figurine SANS override de profil (ex. troupe de base) ne porte que ``col``/``row`` :
 * ses stats sont alors celles de l'unité parente. Une figurine spéciale (leader attaché,
 * sergent, arme spéciale) porte son propre ``unit_type`` + stats + armes. */
export interface UnitModel {
  col?: number;
  row?: number;
  unit_type?: string;
  DISPLAY_NAME?: string;
  ICON?: string;
  ICON_SCALE?: number;
  ILLUSTRATION_RATIO?: number;
  BASE_SHAPE?: "round" | "oval" | "square";
  BASE_SIZE?: number | [number, number];
  T?: number;
  ARMOR_SAVE?: number;
  INVUL_SAVE?: number;
  OC?: number;
  VALUE?: number;
  HP_MAX?: number;
  UNIT_RULES?: UnitRule[];
  RNG_WEAPONS?: Weapon[];
  CC_WEAPONS?: Weapon[];
  selectedRngWeaponIndex?: number | null;
  selectedCcWeaponIndex?: number | null;
}

export interface Unit {
  id: UnitId;
  NAME?: string;
  name?: string;
  DISPLAY_NAME?: string;
  type?: string;
  unitType?: string;
  player: PlayerId;
  col: number;
  row: number;
  /** Niveau vertical (étages). 0 = rez-de-chaussée (défaut). Voir Documentation/Reference/moteur/verticalite.md. */
  level?: number;
  color?: number;

  // Engine UPPERCASE fields (tour_de_jeu.md compliance)
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
  RNG_WEAPONS: Weapon[]; // Armes à distance (max 3)
  CC_WEAPONS: Weapon[]; // Armes de mêlée (max 2)
  selectedRngWeaponIndex?: number; // Index de l'arme ranged sélectionnée
  selectedCcWeaponIndex?: number; // Index de l'arme melee sélectionnée
  manualWeaponSelected?: boolean; // True when user explicitly selected a weapon
  /** Pool moteur (tir) : profil + index ; ``weapon`` peut être la variante active (COMBI, etc.). */
  available_weapons?: Array<{
    index: number;
    weapon: Weapon;
    can_use?: boolean;
    canUse?: boolean;
    reason?: string;
  }>;

  // Display properties
  ICON: string;
  ICON_SCALE?: number;
  ILLUSTRATION_RATIO: number;
  BASE_SIZE?: number | [number, number];
  BASE_SHAPE?: "round" | "oval" | "square";
  orientation?: number;

  // Game state tracking
  SHOOT_LEFT?: number;
  ATTACK_LEFT?: number;
  valid_target_pool?: string[];
  los_preview_attack_cells?: Array<{ col: number; row: number }>;
  los_preview_cover_cells?: Array<{ col: number; row: number }>;
  los_preview_ratio_by_hex?: Record<string, number>;
  /** Cellules visibles par cible ciblable (backend, règle 06.01/13.10) — peintes par-dessus
   * le cône WASM pour garantir la cohérence blink↔visuel. Clé = id cible, valeur = [[col,row],…]. */
  visible_cells_by_target?: Record<string, Array<[number, number]>>;
  currentShootNb?: number;
  currentFightNb?: number;
  hasChargedThisTurn?: boolean;
  UNIT_RULES?: UnitRule[];
  UNIT_KEYWORDS?: UnitKeyword[];
  CAN_LEAD?: string[]; // Attached units (rule 19.01): bodyguard unit-name keywords a leader/support may attach to
  /** Composition par-figurine (escouade mixte / character attaché). Absent = mono-profil.
   * Chaque entrée d'index ``idx`` correspond au model_id ``<id>#<idx>``. */
  models?: UnitModel[];

  // Terrain visibility (rules 13.08-13.09)
  hideable?: boolean; // INFANTRY/BEASTS/SWARM — eligible for cover/hidden
  hidden?: boolean; // True only if ALL models are hidden (rule 13.09)
  hidden_models?: string[]; // model_ids whose footprint touches obscuring terrain
  battle_shocked?: boolean;

  /** 20.01 — l'unité est en réserves stratégiques (hors table tant qu'elle n'a pas fait son
   * ingress move 20.04). Écrit par le moteur ; le client ne fait que le lire. */
  in_strategic_reserves?: boolean;
}

/** Réserves d'UN joueur — 20.01. Toutes les grandeurs viennent du moteur (`strategic_reserves`
 * de l'API) : le client ne recalcule ni le plafond de 50 %, ni l'éligibilité d'un dépôt. */
export interface StrategicReservesPlayerSummary {
  /** Points DÉJÀ engagés en réserves (numérateur du ratio « 120/250 »). */
  used_points: number;
  /** Plafond de 50 % de la taille de bataille (dénominateur). */
  cap_points: number;
  /** Unités que le moteur accepterait MAINTENANT en réserves (plafond + FORTIFICATION + à poser).
   * Le conteneur ne propose le dépôt que pour ces ids. */
  placeable_unit_ids: string[];
}

/** ``strategic_reserves`` du game_state : un résumé par joueur + le round de destruction (20.04). */
export interface StrategicReservesSummary {
  "1"?: StrategicReservesPlayerSummary;
  "2"?: StrategicReservesPlayerSummary;
  /** Round au bout duquel les réserves non arrivées sont détruites (20.04). */
  last_round?: number;
}

/** Detection range effective d'une unité cachée vis-à-vis du tireur actif (règle 13.09 + 13.5). */
export interface HiddenDetectionInfo {
  /** 15 normalement, 12 si TOUTES les figs sont gone to ground (règle 13.5). */
  detection_inches: 15 | 12;
  /** True si le tireur est hors detection range → unité non ciblable. */
  too_far: boolean;
}

/**
 * Condition de couvert (règle 13.08) remplie par UNE figurine, telle que le moteur la calcule
 * (`compute_unit_los(...)["cover_conditions"]`).
 *
 * - "a" → la figurine est within a terrain area (et son unité est hideable) ;
 * - "b" → la figurine n'est pas entièrement visible du tireur ;
 * - ""  → la figurine est à découvert. C'est ELLE qui annule le couvert de toute l'escouade.
 *
 * ⚠️ DIAGNOSTIC D'AFFICHAGE. Le `-1 BS` reste tout-ou-rien au niveau de l'UNITÉ (13.08 :
 * « if EVERY model in that unit meets one or more of the following conditions ») et se lit
 * exclusivement sur `cover_by_unit_id`. Une figurine en "a" dans une escouade qui n'a PAS le
 * couvert ne bénéficie d'aucun bonus : le rendu doit le distinguer, pas l'aplatir.
 */
export type ModelCoverCondition = "a" | "b" | "";

/** Conditions 13.08 par figurine, par unité cible. Index aligné sur les figurines de l'unité. */
export type CoverConditionsByUnitId = Record<string, ModelCoverCondition[]>;

/**
 * Parse `cover_conditions_by_unit_id` d'une réponse moteur.
 *
 * Champ DIAGNOSTIQUE, donc tolérant par conception, à l'inverse de `cover_by_unit_id` qui est
 * contractuel et lève : une réponse d'un backend plus ancien (ou une action qui ne le porte pas)
 * rend simplement `{}`, et l'affichage retombe sur le booléen d'unité au lieu de casser le tour
 * du joueur. Les valeurs inconnues sont écartées plutôt que réinterprétées.
 */
export function parseCoverConditionsByUnitId(raw: unknown): CoverConditionsByUnitId {
  const out: CoverConditionsByUnitId = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [unitId, conditions] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(conditions)) continue;
    out[unitId] = conditions.map((c) => (c === "a" || c === "b" ? c : ""));
  }
  return out;
}

export interface SingleShotState {
  isActive: boolean;
  shooterId: UnitId;
  targetId: UnitId | null;
  currentShotNumber: number;
  totalShots: number;
  shotsRemaining: number;
  isSelectingTarget: boolean;
  currentStep:
    | "target_selection"
    | "hit_roll"
    | "wound_roll"
    | "save_roll"
    | "damage_application"
    | "complete";
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
  currentStep:
    | "target_selection"
    | "hit_roll"
    | "wound_roll"
    | "save_roll"
    | "damage_application"
    | "complete";
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
  // tour_de_jeu.md required fields
  episode_steps: number;
  units: Unit[];
  current_player?: number; // Engine format
  phase: GamePhase;
  turn?: number; // Engine format
  currentTurn?: number; // Frontend format
  game_over?: boolean;
  winner?: number | null;

  // tour_de_jeu.md tracking sets (Frontend format - converted from Engine string[] to UnitId[])
  unitsMoved?: UnitId[];
  unitsFled?: UnitId[];
  units_shot?: string[]; // IDs des unités ayant tiré ce tour (règle 13.09 Hidden)
  units_shot_previous_turn?: string[]; // IDs des unités ayant tiré au tour précédent (règle 13.09 Hidden)
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

  // Fight phase V11 (PDF 12)
  fight_subphase?: FightSubPhase;
  // Unités actionnables dans la sous-phase fight courante (exposé moteur).
  fight_eligible_units?: string[];
  fight_step?: "fights_first" | "remaining" | null;
  fight_selector?: number | null;
  active_fight_unit?: string | null;
  units_cache?: Record<
    string,
    {
      col: number;
      row: number;
      /** Niveau vertical de l'ancre (étages). 0 = sol. */
      level?: number;
      HP_CUR: number;
      player: number;
      orientation?: number;
      /** Niveau vertical par figurine (escouade répartie sur plusieurs étages, §2.5). */
      level_by_model?: Record<string, number>;
    }
  >;

  // Frontend specific
  mode?: GameMode;
  selectedUnitId?: UnitId | null;
  targetPreview?: TargetPreview | null;
  fightSubPhase?: FightSubPhase;
  fightActivePlayer?: PlayerId;
  unitChargeRolls?: Record<UnitId, number>;
  pve_mode?: boolean; // Add PvE mode flag
  player_types?: Record<string, "human" | "ai">;
  deployment_type?: "random" | "fixed" | "active";
  deployment_state?: DeploymentState;
  deployment_pools?: DeploymentPools;
  active_movement_unit?: string; // Active unit ID in movement phase
  /** Ancres BFS valides (une par destination d’empreinte) — affichage disques, pas union hex-par-hex. */
  valid_move_destinations_pool?: Array<[number, number]>;
  /** Rayon disques UI : max dimension d’empreinte en hex (moteur) — si l’unité client n’a pas BASE_SIZE. */
  move_preview_footprint_span?: number | null;
  /** Souvent identique au pool de move (moteur). */
  preview_hexes?: Array<[number, number]>;
  move_preview_border?: Array<[number, number]>;
  move_preview_footprint_zone?: Array<[number, number]>;
  /** Contours masque move (coord. monde) — JSON compact ``[x,y,...]`` par boucle ou legacy ``[[x,y],…]``. */
  move_preview_footprint_mask_loops?: unknown;
  /** Empreinte serveur ; le client la renvoie en ``move_preview_mask_loops_client_hash`` pour omettre les boucles si inchangé. */
  move_preview_footprint_mask_loops_hash?: string;
  move_preview_footprint_mask_loops_unchanged?: boolean;
  active_shooting_unit?: string; // Active unit ID in shooting phase
  active_charge_unit?: string; // Active unit ID in charge phase
  victory_points?: Record<string, number>;
  /** Points de commandement par joueur (règle 08.02). Même forme que `victory_points` :
   *  JSON n'a pas de clé entière, l'API sérialise donc {"1": n, "2": n}. */
  command_points?: Record<string, number>;
  primary_objective?: PrimaryObjectiveRule | PrimaryObjectiveRule[] | null;
  /** Réserves stratégiques (20.01/20.04), par joueur — source unique du ratio affiché et des
   * dépôts proposés. Absent tant qu'aucune partie n'est chargée. */
  strategic_reserves?: StrategicReservesSummary;
  /** Retrait de cohérence en attente (03.03) : escouade dont il faut retirer une figurine. */
  pending_coherency_removal?: { squad_id: string } | null;
}

export interface SemanticAction {
  action: "move" | "skip" | "shoot" | "charge" | "fight";
  unitId: string;
  destCol?: number;
  destRow?: number;
  orientation?: number;
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
  orientation?: number;
}

export interface AttackPreview {
  unitId: UnitId;
  col: number;
  row: number;
}
