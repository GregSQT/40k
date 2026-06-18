// frontend/src/hooks/useEngineAPI.ts
import type { MutableRefObject } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getAuthSession } from "../auth/authStorage";
import type { GameMode, PlayerId, Unit } from "../types";
import type { DiceValue, Weapon } from "../types/game";
import {
  CROSS_ACTION_LOG_SUPPRESS_MS,
  dedupeActionLogBatch,
  isActionLogTraceEnabled,
  logActionLogBatchTrace,
  logActionLogEmitTrace,
  logClientDebugConsoleNotifyIfEnabled,
  shouldEmitActionLogEvent,
} from "../utils/actionLogClient";
import type { ActivationPointerGameState } from "../utils/activationClickTarget";
import {
  buildActivationPointerPayload,
  getActiveFightUnitIdString,
  getFightActivationPoolUnitIds,
  getFightAttackerAttackLeft,
  isFightAttackSelectionUiOpen,
} from "../utils/activationClickTarget";
import { logFightClick } from "../utils/fightClickDebug";
import { cubeDistance, cubeToOffset, offsetToCube } from "../utils/gameHelpers";
import { addHexKeysToSet } from "../utils/movePoolRefsSync";
import { normalizeMaskLoopsFromApi } from "../utils/movePreviewFootprintMaskLoops";
import { getSelectedRangedWeaponAgainstTarget } from "../utils/probabilityCalculator";

// Get max_turns from config instead of hardcoded fallback
const getMaxTurnsFromConfig = async (): Promise<number> => {
  try {
    const response = await fetch("/config/game_config.json");
    if (!response.ok) {
      throw new Error(`Config fetch failed: ${response.status}`);
    }
    const config = await response.json();
    if (!config.game_rules?.max_turns) {
      throw new Error(`Missing required max_turns in game config`);
    }
    return config.game_rules.max_turns;
  } catch (error) {
    throw new Error(`CRITICAL CONFIG ERROR: Failed to load max_turns from config: ${error}`);
  }
};

const API_BASE = "/api";

function validateOrientationStepValue(rawOrientation: unknown, context: string): number {
  if (
    typeof rawOrientation !== "number" ||
    !Number.isInteger(rawOrientation) ||
    rawOrientation < 0 ||
    rawOrientation > 5
  ) {
    throw new Error(
      `${context}: orientation must be an integer in 0..5, got ${String(rawOrientation)}`
    );
  }
  return rawOrientation;
}

/** fetch échoué (API arrêtée, mauvaise origine sans proxy Vite, etc.). */
function formatApiConnectionError(err: unknown): string {
  const raw = err instanceof Error ? err.message : typeof err === "string" ? err : String(err);
  const isNetworkish =
    /networkerror|failed to fetch|load failed|network request failed/i.test(raw) ||
    (err instanceof TypeError && /fetch|network/i.test(raw));
  if (isNetworkish) {
    return (
      "Impossible de joindre l'API (réseau). Démarrez le backend : `python services/api_server.py` " +
      "(http://localhost:5001), puis le frontend avec `npm run dev` dans `frontend/` (port 5175, proxy /api). " +
      `Détail technique : ${raw}`
    );
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Unknown error";
}

const RETREAT_ALERT_STORAGE_KEY = "retreatAlertEnabled";

// Prevent duplicate AI turn calls
let aiTurnInProgress = false;

function readRequiredBooleanSetting(key: string, defaultValue: boolean): boolean {
  const rawValue = localStorage.getItem(key);
  if (rawValue == null) {
    return defaultValue;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawValue);
  } catch (error) {
    throw new Error(`Invalid JSON value for localStorage key "${key}": ${String(error)}`);
  }
  if (typeof parsed !== "boolean") {
    throw new Error(`localStorage key "${key}" must be a boolean`);
  }
  return parsed;
}

/** Backend renvoie souvent des couples [col, row] ; le state React attend { col, row }. */
function normalizeChargeDestinationsFromApi(raw: unknown): Array<{ col: number; row: number }> {
  if (!Array.isArray(raw)) {
    return [];
  }
  const out: Array<{ col: number; row: number }> = [];
  for (const d of raw) {
    if (Array.isArray(d) && d.length >= 2) {
      out.push({ col: Number(d[0]), row: Number(d[1]) });
    } else if (d && typeof d === "object" && "col" in d && "row" in d) {
      const o = d as { col: unknown; row: unknown };
      out.push({ col: Number(o.col), row: Number(o.row) });
    }
  }
  return out;
}

export interface APIGameState {
  units: Array<{
    id: string | number;
    player: number;
    DISPLAY_NAME?: string;
    col: number;
    row: number;
    HP_CUR: number;
    HP_MAX: number;
    MOVE: number;
    T: number;
    ARMOR_SAVE: number;
    INVUL_SAVE: number;
    // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Replace single weapon fields with arrays
    RNG_WEAPONS: Array<{
      code_name: string;
      display_name: string;
      RNG?: number;
      NB: DiceValue;
      ATK: number;
      STR: number;
      AP: number;
      DMG: DiceValue;
      WEAPON_RULES?: string[];
    }>;
    available_weapons?: Array<{
      index: number;
      weapon: Weapon;
      can_use?: boolean;
      reason?: string;
    }>;
    CC_WEAPONS: Array<{
      code_name: string;
      display_name: string;
      NB: DiceValue;
      ATK: number;
      STR: number;
      AP: number;
      DMG: DiceValue;
      WEAPON_RULES?: string[];
    }>;
    selectedRngWeaponIndex?: number;
    selectedCcWeaponIndex?: number;
    manualWeaponSelected?: boolean;
    LD: number;
    OC: number;
    VALUE: number;
    ICON: string;
    ICON_SCALE?: number;
    ILLUSTRATION_RATIO: number;
    BASE_SIZE?: number | [number, number];
    BASE_SHAPE?: "round" | "oval" | "square";
    orientation?: number;
    unitType: string;
    SHOOT_LEFT?: number;
    ATTACK_LEFT?: number;
    _current_shoot_nb?: number;
    _current_fight_nb?: number;
    // AI_TURN.md shooting state fields
    valid_target_pool?: string[];
    los_preview_attack_cells?: Array<{ col: number; row: number }>;
    los_preview_cover_cells?: Array<{ col: number; row: number }>;
    los_preview_ratio_by_hex?: Record<string, number>;
    selected_target_id?: string;
    // Règle 13.09 Hidden / battle-shock (exposé moteur)
    hideable?: boolean;
    hidden?: boolean;
    hidden_models?: string[];
    battle_shocked?: boolean;
    TOTAL_ATTACK_LOG?: string;
    UNIT_RULES: Array<{
      ruleId: string;
      displayName: string;
      grants_rule_ids?: string[];
      usage?: "and" | "or" | "unique" | "always";
      choice_timing?: {
        trigger:
          | "on_deploy"
          | "turn_start"
          | "player_turn_start"
          | "phase_start"
          | "activation_start";
        phase?: "command" | "move" | "shoot" | "charge" | "fight";
        active_player_scope?: "owner" | "opponent" | "both";
      };
    }>;
    UNIT_KEYWORDS: Array<{
      keywordId: string;
    }>;
  }>;
  current_player: number;
  phase: string;
  turn: number;
  episode_steps: number;
  max_turns: number;
  units_moved: string[];
  units_fled: string[];
  units_shot: string[];
  units_shot_previous_turn?: string[]; // Règle 13.09 Hidden
  units_charged: string[];
  units_attacked: string[];
  units_advanced?: string[]; // Units that have advanced this turn
  units_took_to_skies?: string[]; // Units FLY ayant déclaré le vol en phase MOVE ce tour (Règles 21.03)
  units_took_to_skies_charge?: string[]; // Units FLY ayant déclaré le vol en phase CHARGE ce tour (Règles 21.03)
  move_activation_pool: string[];
  shoot_activation_pool: string[];
  charge_activation_pool: string[];
  charging_activation_pool: string[];
  active_alternating_activation_pool: string[];
  non_active_alternating_activation_pool: string[];
  fight_subphase: string | null;
  // Unités actionnables dans la sous-phase fight courante (moteur : List[str]).
  fight_eligible_units?: string[];
  units_cache?: Record<
    string,
    { col: number; row: number; HP_CUR: number; player: number; orientation?: number }
  >;
  active_movement_unit?: string;
  valid_move_destinations_pool?: Array<[number, number]>;
  move_preview_footprint_span?: number | null;
  move_preview_border?: Array<[number, number]>;
  move_preview_footprint_zone?: Array<[number, number]>;
  /** Boucles masque (format compact ``[x,y,...]`` ou legacy ``[[x,y],...]``) + métadonnées API. */
  move_preview_footprint_mask_loops?: unknown;
  move_preview_footprint_mask_loops_hash?: string;
  move_preview_footprint_mask_loops_unchanged?: boolean;
  fight_pile_in_footprint_zone?: Array<[number, number]>;
  fight_pile_in_footprint_mask_loops?: Array<Array<[number, number]>>;
  fight_consolidation_footprint_zone?: Array<[number, number]>;
  fight_consolidation_footprint_mask_loops?: Array<Array<[number, number]>>;
  active_shooting_unit?: string;
  active_fight_unit?: string;
  pve_mode?: boolean;
  player_types?: Record<string, "human" | "ai">;
  deployment_type?: "random" | "fixed" | "active";
  deployment_state?: {
    current_deployer: number;
    deployable_units: Record<string, string[]>;
    deployed_units: string[];
    deployment_pools: Record<string, Array<[number, number] | { col: number; row: number }>>;
    deployment_complete: boolean;
  };
  victory_points?: Record<string, number>;
  primary_objective?: Record<string, unknown> | Array<Record<string, unknown>> | null;
  objectives?: Array<{
    name: string;
    hexes: Array<{ col: number; row: number } | [number, number]>;
  }>;
  wall_hexes?: Array<{ col: number; row: number } | [number, number]>;
  game_over?: boolean;
  winner?: number | null;
  pending_rule_choice_queue?: RuleChoicePrompt[];
  active_rule_choice_prompt?: RuleChoicePrompt | null;
}

/** Cache dernier payload ``move_preview_footprint_mask_loops`` + hash pour omission JSON (POST /action). */
const _movePreviewMaskLoopsTransport = {
  lastPayload: undefined as unknown,
  clientHash: "",
};

function restoreMovePreviewMaskLoopsIfUnchanged(inc: Record<string, unknown>): void {
  if (inc.move_preview_footprint_mask_loops_unchanged !== true) return;
  const h = inc.move_preview_footprint_mask_loops_hash;
  const snap = _movePreviewMaskLoopsTransport.lastPayload;
  const ok =
    typeof h === "string" &&
    h.length > 0 &&
    h === _movePreviewMaskLoopsTransport.clientHash &&
    snap !== undefined;
  if (ok) {
    inc.move_preview_footprint_mask_loops = snap;
    delete inc.move_preview_footprint_mask_loops_unchanged;
  } else {
    delete inc.move_preview_footprint_mask_loops_unchanged;
    _movePreviewMaskLoopsTransport.lastPayload = undefined;
    _movePreviewMaskLoopsTransport.clientHash = "";
  }
}

function recordMovePreviewMaskLoopsTransportFromIncoming(inc: Record<string, unknown>): void {
  if (!("move_preview_footprint_mask_loops" in inc)) return;
  const loops = inc.move_preview_footprint_mask_loops;
  const h = inc.move_preview_footprint_mask_loops_hash;
  if (loops === null) {
    _movePreviewMaskLoopsTransport.lastPayload = undefined;
    _movePreviewMaskLoopsTransport.clientHash = "";
    return;
  }
  if (loops === undefined) return;
  _movePreviewMaskLoopsTransport.lastPayload = loops;
  if (typeof h === "string" && h.length > 0) {
    _movePreviewMaskLoopsTransport.clientHash = h;
  }
}

function hydrateApiGameStateMovePreviewTransport(gs: APIGameState | null): APIGameState | null {
  if (gs == null) return null;
  const inc = gs as unknown as Record<string, unknown>;
  restoreMovePreviewMaskLoopsIfUnchanged(inc);
  recordMovePreviewMaskLoopsTransportFromIncoming(inc);
  return gs;
}

/**
 * L’API peut omettre ``objectives`` sur les réponses POST /action pour alléger le JSON.
 * Réinjecte la liste déjà connue côté client (issue du ``/start`` ou d’un état complet).
 */
export function mergeGameStatePreservingOmittedObjectives(
  prev: APIGameState | null,
  incoming: APIGameState
): APIGameState {
  const inc = incoming as unknown as Record<string, unknown>;
  restoreMovePreviewMaskLoopsIfUnchanged(inc);
  if (prev !== null && prev.objectives !== undefined && incoming.objectives === undefined) {
    const out = { ...incoming, objectives: prev.objectives };
    recordMovePreviewMaskLoopsTransportFromIncoming(out as unknown as Record<string, unknown>);
    return out;
  }
  recordMovePreviewMaskLoopsTransportFromIncoming(inc);
  return incoming;
}

export interface EndlessDutyState {
  enabled: boolean;
  wave_index: number;
  inter_wave_pending: boolean;
  objective_lost_counter: number;
  requisition_capital_total: number;
  requisition_invested_total: number;
  requisition_available: number;
  slot_profiles: {
    leader: string | null;
    melee: string | null;
    range: string | null;
  };
  slot_picks: {
    leader: Record<string, string | null> | null;
    melee: Record<string, string | null> | null;
    range: Record<string, string | null> | null;
  };
}

interface ArmyListItem {
  file: string;
  name: string;
  display_name: string;
  faction: string;
  faction_display_name: string;
  description: string;
}

interface RuleChoiceOption {
  display_rule_id: string;
  technical_rule_id: string;
  label: string;
}

interface RuleChoicePrompt {
  trigger: "on_deploy" | "turn_start" | "player_turn_start" | "phase_start" | "activation_start";
  phase?: "command" | "move" | "shoot" | "charge" | "fight";
  player: number;
  unit_id: string;
  rule_id: string;
  display_name: string;
  usage: "or" | "unique";
  options: RuleChoiceOption[];
}

/** Allocation manuelle des pertes au tir (defenseur humain) : le backend renvoie ce
 * payload tant qu'une figurine doit etre choisie pour encaisser (regle 05.04). */
export interface ManualAllocation {
  /** "shoot" = pertes du tir (défaut) ; "fight" = pertes du combat ; "hazard" = mortal wounds Desperate Escape (06.02). */
  kind?: "shoot" | "fight" | "hazard";
  attacker_unit_id: string;
  target_unit_id: string;
  defender_player: number;
  choices: Array<{ model_id: string; col: number; row: number; HP_CUR: number; HP_MAX: number }>;
  current_group_id?: number | null;
  wounds_remaining: number;
}

export interface ManualOrderGroup {
  group_id: number;
  is_character: boolean;
  role: string | null;
  unit_type: string | null;
  W: number;
  Sv: number;
  InSv: number;
  model_ids: string[];
  has_wounded: boolean;
}

export interface ManualOrderRequest {
  /** "shoot" = ordre d'allocation du tir (défaut) ; "fight" = du combat. */
  kind?: "shoot" | "fight";
  attacker_unit_id: string;
  target_unit_id: string;
  defender_player: number;
  weapon_name: string;
  /** Noms distincts des armes de profil identique fusionnées dans ce lot (04.03). */
  weapon_names?: string[];
  weapon_ap: number;
  weapon_damage: number | string;
  wounds_to_save: number;
  groups: ManualOrderGroup[];
}

export interface UseEngineAPIOptions {
  /** Ref à un getter appelé avant envoi d'un tir (left_click enemy) ; si forceKill, le backend force la mort de la cible (tutoriel 1-24, 2e tir). */
  getTutorialShootOptionsRef?: MutableRefObject<() => { forceKill?: boolean; forceMiss?: boolean }>;
  /** Tutoriel étape 2 (2-11/2-12/2-13) : arrêter la boucle AI après chaque phase pour permettre pause entre move/shoot/charge. */
  stopAiAfterPhaseChangeRef?: MutableRefObject<boolean>;
  /** Appelé immédiatement quand on break pour changement de phase ; permet de mettre pauseAI à true avant que le useEffect ne re-déclenche l'IA. */
  onStopAfterPhaseChange?: () => void;
}

/** Props blink passées au plateau : même forme en chargement et en jeu pour stabiliser l’inférence d’union (BoardWithAPI). */
export type UseEngineAPIBlinkBoardProps = {
  blinkingUnits: number[];
  blinkingAttackerId: number | null;
  blinkingCoverByUnitId: Record<string, boolean> | undefined;
  blinkingHiddenTooFarByUnitId: Record<string, boolean> | undefined;
  blinkingLosCountByUnitId: Record<string, number> | undefined;
  blinkingSquadAliveCount: number | undefined;
  blinkingLosOverviewUnitId: number | null;
  isBlinkingActive: boolean;
  blinkVersion: number;
};

/** Dérive targets (model_id -> une de ses cibles) depuis les intents backend. */
const deriveShootTargets = (
  decls: Array<{ model_id: string; weapon_index: number; target_unit_id: string }>
): Record<string, string> => {
  const t: Record<string, string> = {};
  for (const d of decls) t[String(d.model_id)] = String(d.target_unit_id);
  return t;
};

export const useEngineAPI = (options?: UseEngineAPIOptions) => {
  const stopAiAfterPhaseChangeRef = options?.stopAiAfterPhaseChangeRef;
  const onStopAfterPhaseChange = options?.onStopAfterPhaseChange;
  const [gameState, setGameState] = useState<APIGameState | null>(null);
  const [endlessDutyState, setEndlessDutyState] = useState<EndlessDutyState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [maxTurnsFromConfig, setMaxTurnsFromConfig] = useState<number | null>(null);
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [mode, setMode] = useState<
    | "select"
    | "movePreview"
    | "squadModelMove"
    | "squadModelShoot"
    | "attackPreview"
    | "targetPreview"
    | "chargeTargetSelect"
    | "chargePreview"
    | "chargeModelMove"
    | "advancePreview"
    | "pileInPreview"
    | "pileInModelMove"
    | "consolidationPreview"
    | "consolidationModelMove"
  >("select");
  const [movePreview, setMovePreview] = useState<{
    unitId: number;
    destCol: number;
    destRow: number;
    orientation?: number;
  } | null>(null);
  const [pendingPreviewAction, setPendingPreviewAction] = useState<
    "move" | "move_after_shooting" | null
  >(null);
  /**
   * Move par-figurine (squad.md brique 3) — plan provisoire NON committe au backend.
   * ``models`` : position provisoire de chaque figurine (model_id -> {col,row}).
   * ``perModelValid`` : voile rouge (false = position interdite ou hors cohesion).
   * ``canValidate`` : toutes les figs valides + cohesion OK (bouton Validate actif).
   */
  const [squadMovePlan, setSquadMovePlan] = useState<{
    unitId: number;
    /** Positions provisoires courantes (model_id -> {col,row}). */
    models: Record<string, { col: number; row: number }>;
    /** Positions de DEBUT de mode (pour reset par-fig clic droit + cancel escouade). */
    originModels: Record<string, { col: number; row: number }>;
    activeModelId: string | null;
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    canValidate: boolean;
    /** Escouade actuellement engagée → tout commit = Fall Back (badge fui en preview). */
    wouldFlee: boolean;
  } | null>(null);
  /** Ref miroir de squadMovePlan pour accès synchrone dans les callbacks. */
  const squadMovePlanRef = useRef<typeof squadMovePlan>(null);
  squadMovePlanRef.current = squadMovePlan;
  /**
   * Unité dont le move en cours est un Fall Back (badge fui en preview). État STABLE,
   * découplé de squadMovePlan (qui churne et effacerait le badge entre deux rendus).
   * Posé quand le dry-run renvoie would_flee=true ; effacé à la sortie du mode move.
   */
  const [fleePreviewUnitId, setFleePreviewUnitId] = useState<number | null>(null);
  // Le badge "fui" en preview ne vit que pendant le mode plan de move : clear à la sortie.
  useEffect(() => {
    if (mode !== "squadModelMove") setFleePreviewUnitId(null);
  }, [mode]);
  /** Pool BFS (hexes atteignables) de la figurine en cours de repositionnement. */
  const squadMoveModelPoolRef = useRef<Set<string>>(new Set());
  /** Incrémenté à chaque nouvelle session squad move. Invalide les callbacks onSelectModelForMove obsolètes. */
  const squadMoveSessionRef = useRef(0);
  /** Mask loops per-fig (polygone lissé) reçus de move_model_destinations. */
  const squadMoveModelMaskLoopsRef = useRef<number[][] | null>(null);
  /**
   * Charge par-figurine (V11 11.04, Slice G) — plan provisoire des figs POSÉES, NON committé.
   * ``models`` : figs déjà posées (model_id -> {col,row}) ; les autres sont dans ``unplaced``.
   * ``eligible`` : destinations valides par fig non posée pour la phase courante (cercle violet).
   * ``satisfied/unsatisfiedTargets`` : voile par UNITÉ cible (violet = engagée, rouge = pas encore).
   * ``canValidate`` : toutes les figs posées + config finale légale (bouton Charger actif).
   */
  const [chargeMovePlan, setChargeMovePlan] = useState<{
    unitId: number;
    models: Record<string, { col: number; row: number }>;
    /** Figs non posées pouvant agir dans la phase courante (voile violet). Pool calculé à la demande. */
    eligibleModels: string[];
    unplaced: string[];
    activeModelId: string | null;
    currentPhase: 1 | 2 | 3;
    canValidate: boolean;
    satisfiedTargets: number[];
    unsatisfiedTargets: number[];
    /** Figs POSÉES engagées (≤ EZ) avec une cible déclarée → voile vert (en mesure de frapper). */
    engagedModels: string[];
    /** Sous-conditions de non-validation (bouton « Check charge ») : légalité par-fig (budget/closer),
     * cohésion d'unité, cibles déclarées non encore engagées. */
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    missingTargets: number[];
  } | null>(null);
  const chargeMovePlanRef = useRef<typeof chargeMovePlan>(null);
  chargeMovePlanRef.current = chargeMovePlan;
  /** Mode Focus (bouton) en chargeModelMove : voile violet sur les cibles déclarées, clic sur une
   * cible → auto-placement optimal de toutes les figs (charge_autoplace). */
  const [chargeFocusActive, setChargeFocusActive] = useState(false);
  const chargeFocusActiveRef = useRef(false);
  chargeFocusActiveRef.current = chargeFocusActive;
  /** Dernier mode Focus charge déclenché (surbrillance des boutons off./déf.). */
  const [chargeFocusMode, setChargeFocusMode] = useState<null | "offensive" | "defensive">(null);
  /** Pool (hexes "col,row") de la fig active = eligible[activeModelId]. */
  const chargeModelPoolRef = useRef<Set<string>>(new Set());
  /** Distance de mouvement (sous-hex) de la fig active vers chaque ancre de son pool "col,row" →
   * path réel au sol, distance directe en vol. Source du tooltip de charge par-figurine. */
  // A SUPPRIMER : feature distance charge par-figurine jamais fonctionnelle (lecteur inatteignable, supprimé côté BoardPvp).
  const chargeModelDistancesRef = useRef<Map<string, number>>(new Map());
  /** Mask loops (polygone lissé monde) de la zone de landing de la fig active — même contrat que
   * ``squadMoveModelMaskLoopsRef`` pour le move per-fig. Rendu lissé au lieu de disques bruts. */
  const chargeModelMaskLoopsRef = useRef<number[][] | null>(null);
  /**
   * Pile-in par-figurine (V11 12.04, mode fin type charge) — plan provisoire NON committé.
   * ``models`` : figs déjà posées (model_id -> {col,row}) ; les non-posées restent à l'origine.
   * ``eligibleModels`` : figs non posées pouvant finir plus proche du palier ennemi (voile violet).
   * ``activeModelId`` : fig sélectionnée dont le pool (≤3") est affiché. ``canValidate`` : plan légal.
   * Contrat backend simplifié vs charge : pas de phases, ni distances, ni cibles satisfaites.
   */
  const [pileInMovePlan, setPileInMovePlan] = useState<{
    unitId: number;
    models: Record<string, { col: number; row: number }>;
    eligibleModels: string[];
    unplaced: string[];
    activeModelId: string | null;
    canValidate: boolean;
    /** Sous-conditions de légalité (bouton « Check pile-in » + voile rouge par-fig). */
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    unitEngaged: boolean;
    keptEngagements: boolean;
    /** Figs posées en mesure de frapper (≤ EZ d'une cible) → voile vert. */
    engagedModels: string[];
    /** Cibles pile-in (focus) → cercle violet + hit-test. */
    pileInTargets: string[];
  } | null>(null);
  const pileInMovePlanRef = useRef<typeof pileInMovePlan>(null);
  pileInMovePlanRef.current = pileInMovePlan;
  /** Mode Focus pile-in : null = inactif, sinon stratégie d'auto-placement (ILP). */
  const [pileInFocusMode, setPileInFocusMode] = useState<null | "defensive" | "offensive">(null);
  const pileInFocusModeRef = useRef<null | "defensive" | "offensive">(null);
  pileInFocusModeRef.current = pileInFocusMode;
  /** Cible pile-in mémorisée (focus) : relance l'autoplace quand un mode est (re)choisi. */
  const [pileInFocusTargetId, setPileInFocusTargetId] = useState<string | null>(null);
  const pileInFocusTargetIdRef = useRef<string | null>(null);
  pileInFocusTargetIdRef.current = pileInFocusTargetId;
  /** Pool (hexes "col,row") de la fig pile-in active. */
  const pileInModelPoolRef = useRef<Set<string>>(new Set());
  /** Mask loops (polygone lissé monde) de la zone de landing de la fig pile-in active. */
  const pileInModelMaskLoopsRef = useRef<number[][] | null>(null);

  // ──────────────────────────────────────────────────────────────────────────
  // CONSOLIDATION PAR-FIGURINE (V11 12.08, miroir pile-in). Cascade 3 modes :
  // ongoing / engaging (sélection de cibles d'abord) / objective (sélection objectif si >1).
  // ──────────────────────────────────────────────────────────────────────────
  const [consolidationMovePlan, setConsolidationMovePlan] = useState<{
    unitId: number;
    models: Record<string, { col: number; row: number }>;
    eligibleModels: string[];
    unplaced: string[];
    activeModelId: string | null;
    canValidate: boolean;
    perModelValid: Record<string, boolean>;
    coherencyOk: boolean;
    unitEngaged: boolean;
    keptEngagements: boolean;
    engagedWithAllSelected: boolean;
    withinObjectiveRange: boolean;
    engagedModels: string[];
    /** Mode imposé par la cascade 12.08 (ongoing|engaging|objective). */
    consolidationMode: string | null;
    /** Engaging : ennemis candidats (≤3") cliquables ; sélectionnés = consolidation_targets. */
    engagingCandidates: string[];
    /** Objective : objectifs candidats (≤3") cliquables. */
    objectiveCandidates: string[];
    /** Cibles ennemies du palier (info). */
    consolidationTargets: string[];
    /** Sélection préalable requise (Engaging) / objectif requis (Objective >1 candidat). */
    awaitingTargetSelection: boolean;
    awaitingObjectiveSelection: boolean;
  } | null>(null);
  const consolidationMovePlanRef = useRef<typeof consolidationMovePlan>(null);
  consolidationMovePlanRef.current = consolidationMovePlan;
  /** Pool (hexes "col,row") de la fig de consolidation active. */
  const consolidationModelPoolRef = useRef<Set<string>>(new Set());
  /** Mask loops (polygone lissé monde) de la zone de la fig de consolidation active. */
  const consolidationModelMaskLoopsRef = useRef<number[][] | null>(null);
  /** New Foes to Face (12.08 engaging AFTER) présentés à l'adversaire (sélecteur). */
  const [consolidationNewFoes, setConsolidationNewFoes] = useState<string[]>([]);
  const consolidationNewFoesRef = useRef<string[]>([]);
  consolidationNewFoesRef.current = consolidationNewFoes;
  /** Mode Focus consolidation (Défensif / Offensif) ; null = aucun (miroir pile-in). */
  const [consolidationFocusMode, setConsolidationFocusMode] = useState<
    null | "defensive" | "offensive"
  >(null);
  const consolidationFocusModeRef = useRef<null | "defensive" | "offensive">(null);
  consolidationFocusModeRef.current = consolidationFocusMode;
  /**
   * Tir par-figurine (PvP manuel) — plan provisoire de cibles assignées par fig.
   * ``targets`` : model_id -> squad_id ennemi assigné (cible de cette fig pour la phase).
   * ``activeModelId`` : fig sélectionnée dont on assigne la cible au prochain clic ennemi.
   * ``canValidate`` : au moins une fig a une cible → bouton Valider actif (figs non
   * assignées = skip au tir, décision utilisateur).
   * Les cibles valides de la fig active clignotent (blinkingUnits), les autres grisées.
   */
  const [squadShootPlan, setSquadShootPlan] = useState<{
    unitId: number;
    models: string[];
    /** Dérivé de declarations : model_id -> une de ses cibles (count, fingerprint, clic-droit). */
    targets: Record<string, string>;
    /** Source de vérité du rendu (voile/ligne par arme) : intents backend. */
    declarations: Array<{ model_id: string; weapon_index: number; target_unit_id: string }>;
    activeModelId: string | null;
    /** Arme active (pilotée par le menu d'armes) pour l'assignation par simple/double clic. */
    activeWeaponIndex: number | null;
    canValidate: boolean;
  } | null>(null);
  /** Ref miroir de squadShootPlan pour accès synchrone dans les callbacks. */
  const squadShootPlanRef = useRef<typeof squadShootPlan>(null);
  squadShootPlanRef.current = squadShootPlan;
  /**
   * Combat par-figurine (PvP manuel) — calque allégé de squadShootPlan. La mêlée n'a
   * ni portée ni LoS : les cibles valides (unité engagée) viennent de gameState.valid_targets,
   * et la validité par-figurine (règle 04.02) est tranchée côté backend à l'assignation.
   */
  const [squadFightPlan, setSquadFightPlan] = useState<{
    unitId: number;
    models: string[];
    /** Dérivé de declarations : model_id -> sa cible (count / clic-droit). */
    targets: Record<string, string>;
    /** Source de vérité : intents backend (pending_squad_fight_intents). */
    declarations: Array<{ model_id: string; weapon_index: number; target_unit_id: string }>;
    activeModelId: string | null;
    activeWeaponIndex: number | null;
    canValidate: boolean;
  } | null>(null);
  /** Ref miroir de squadFightPlan pour accès synchrone dans les callbacks. */
  const squadFightPlanRef = useRef<typeof squadFightPlan>(null);
  squadFightPlanRef.current = squadFightPlan;
  /** Nombre de figs ASSIGNABLES (engagées) de l'unité fight active, remonté par BoardPvp
   * (qui a la géométrie + boardConfig). Sert de dénominateur au décompte de la barre. */
  const [fightAssignableCount, setFightAssignableCount] = useState(0);
  const handleReportFightAssignable = useCallback((n: number) => {
    setFightAssignableCount(n);
  }, []);
  /** Incrémenté à chaque session de tir squad. Invalide les select_model obsolètes. */
  const squadShootSessionRef = useRef(0);
  /** Guard contre le double-clic : bloque un second squad_shoot_activate concurrent. */
  const squadShootActivatingRef = useRef(false);
  const [attackPreview, setAttackPreview] = useState<{
    unitId: number;
    col: number;
    row: number;
  } | null>(null);
  /**
   * Snapshot synchrone du plateau pour la CC : évite les closures périmées dans
   * ``executeAction`` (réponses async) tout en restant une seule source pour mode + attackPreview.
   */
  const fightTargetUiRef = useRef<{ mode: typeof mode; attackPreview: typeof attackPreview }>({
    mode: "select",
    attackPreview: null,
  });
  fightTargetUiRef.current = { mode, attackPreview };
  const [chargeDestinations, setChargeDestinations] = useState<Array<{ col: number; row: number }>>(
    []
  );
  /** Fight phase : ancres valides pour pile in (moteur) */
  const [pileInDestinations, setPileInDestinations] = useState<Array<{ col: number; row: number }>>(
    []
  );
  /** Union des hexes d'empreinte finales (moteur) — affichage violet autour de la cible, pas seulement les ancres. */
  const [chargePreviewOverlayHexes, setChargePreviewOverlayHexes] = useState<
    Array<{ col: number; row: number }>
  >([]);
  /** Hex de référence portée charge (moteur) — même point que ``charge_reference_hex`` API. */
  const [chargeReferenceHex, setChargeReferenceHex] = useState<{
    col: number;
    row: number;
  } | null>(null);
  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Advance state management
  const [advanceDestinations, setAdvanceDestinations] = useState<
    Array<{ col: number; row: number }>
  >([]);
  const [advancingUnitId, setAdvancingUnitId] = useState<number | null>(null);
  const [advanceRoll, setAdvanceRoll] = useState<number | null>(null);
  /** V11 : engagement de l'unité active (posé à l'activation via would_flee). Pilote l'UI des
   *  modes de déplacement (engagée → Fall-back/Stationary ; non engagée → Move/Advance). */
  const [activeUnitEngaged, setActiveUnitEngaged] = useState<number | null>(null);
  const moveDestPoolRef = useRef<Set<string>>(new Set());
  const footprintZoneRef = useRef<Set<string>>(new Set());
  /** Boucles masque monde (API) — hit-test quand ``move_preview_footprint_zone`` est absent du JSON. */
  const footprintMaskLoopsRef = useRef<number[][] | null>(null);
  /** Ancres charge valides + zone violette (empreintes) — même usage que moveDestPoolRef pour l’icône sous le curseur. */
  const chargeDestPoolRef = useRef<Set<string>>(new Set());
  const chargeFootprintZoneRef = useRef<Set<string>>(new Set());
  /** Distance de mouvement réelle (sous-hex) par ancre de charge "col,row" → respecte le pathfinding
   * (détours autour des murs/figs au sol ; distance directe en vol déclaré). Source du tooltip charge. */
  const chargeDestDistancesRef = useRef<Map<string, number>>(new Map());

  const syncChargePoolRefs = useCallback(
    (
      anchors: Array<{ col: number; row: number }>,
      overlay: Array<{ col: number; row: number }>
    ) => {
      const a = new Set<string>();
      for (const h of anchors) {
        a.add(`${h.col},${h.row}`);
      }
      chargeDestPoolRef.current = a;
      const z = new Set<string>();
      const zoneSource = overlay.length > 0 ? overlay : anchors;
      for (const h of zoneSource) {
        z.add(`${h.col},${h.row}`);
      }
      chargeFootprintZoneRef.current = z;
    },
    []
  );

  const clearChargePoolRefs = useCallback(() => {
    chargeDestPoolRef.current = new Set();
    chargeFootprintZoneRef.current = new Set();
    chargeDestDistancesRef.current = new Map();
  }, []);

  const [advanceWarningPopup, setAdvanceWarningPopup] = useState<{
    unitId: number;
    timestamp: number;
  } | null>(null);
  const [fleeWarningPopup, setFleeWarningPopup] = useState<{
    unitId: number;
    destCol: number;
    destRow: number;
    dontRemind: boolean;
    timestamp: number;
  } | null>(null);
  // Desperate Escape (09.07) : popup d'avertissement hazard affiché à l'activation d'une
  // unité engagée ET battle-shocked. Confirmer = rouler le hazard (06.03) avant de bouger.
  const [hazardWarningPopup, setHazardWarningPopup] = useState<{ unitId: number } | null>(null);
  // Ref miroir pour lecture synchrone juste après un await (ex. gate d'entrée du move preview).
  const hazardWarningPopupRef = useRef<{ unitId: number } | null>(null);
  hazardWarningPopupRef.current = hazardWarningPopup;
  // Desperate Escape : id de l'unité dont le hazard vient d'être résolu (vivante) → l'effet
  // dédié auto-entre dans le plan Fall Back par-figurine (squadModelMove), comblant le trou
  // mode select laissé par le resume (le clic d'activation a été consommé par le popup hazard).
  const [fallBackResumeUnitId, setFallBackResumeUnitId] = useState<number | null>(null);
  // TEST/DEBUG : mode toggle « battle-shock test ». Quand actif, cliquer une unité (non activée)
  // lui fait un battle-shock test au lieu de la sélectionner → l'unité est shockée AVANT son
  // activation, donc le Desperate Escape se déclenche dès l'activation (avant le move preview).
  const [battleShockTestMode, setBattleShockTestMode] = useState(false);
  const [chargedTestMode, setChargedTestMode] = useState(false);
  const [postShootMoveDestinations, setPostShootMoveDestinations] = useState<
    Array<{ col: number; row: number }>
  >([]);
  const [targetPreview, setTargetPreview] = useState<{
    shooterId: number;
    targetId: number;
    currentBlinkStep?: number;
    totalBlinkSteps?: number;
    blinkTimer?: number | null;
    hitProbability: number;
    woundProbability: number;
    saveProbability: number;
    overallProbability: number;
    potentialDamage: number;
    expectedDamage: number;
    lastUpdate?: number;
  } | null>(null);

  // State for multi-unit HP bar blinking
  const [blinkingUnits, setBlinkingUnits] = useState<{
    unitIds: number[];
    blinkTimer: number | null;
    attackerId?: number | null;
    coverByUnitId?: Record<string, boolean>;
    hiddenTooFarByUnitId?: Record<string, boolean>;
    // Mode "vue escouade" (double-clic sur une fig) : N figs qui voient chaque
    // ennemi + M figs vivantes. Absents = mode mono-fig classique.
    losCountByUnitId?: Record<string, number>;
    squadAliveCount?: number;
    losOverviewUnitId?: number | null;
  }>({ unitIds: [], blinkTimer: null, attackerId: null });
  const [blinkVersion, setBlinkVersion] = useState(0);

  // State for failed charge roll display
  const [failedChargeRoll, setFailedChargeRoll] = useState<{
    unitId: number;
    roll: number;
    targetId?: number;
  } | null>(null);
  /** Jet 2D6 après choix de cible (charge possible) — badge vert sur l'unité active */
  const [pendingChargeRollDisplay, setPendingChargeRollDisplay] = useState<{
    unitId: number;
    roll: number;
  } | null>(null);
  /** Cible déclarée pour la charge en cours (icône + halo d’engagement) — post-jet (sélection destination) */
  const [chargePreviewTargetId, setChargePreviewTargetId] = useState<number | null>(null);
  /**
   * V11 multi-cibles : ensemble des cibles toggleées en mode `chargeTargetSelect` (pré-validation).
   * Le clic ennemi ajoute/retire une cible ; le bouton « Charge » envoie cette liste au backend.
   */
  const [chargePreviewTargetIds, setChargePreviewTargetIds] = useState<number[]>([]);
  const chargePreviewTargetIdsRef = useRef<number[]>([]);
  chargePreviewTargetIdsRef.current = chargePreviewTargetIds;
  // State for successful charge target display
  const [successfulChargeTarget, setSuccessfulChargeTarget] = useState<{
    unitId: number;
    targetId: number;
  } | null>(null);
  const [ruleChoicePrompt, setRuleChoicePrompt] = useState<RuleChoicePrompt | null>(null);
  /** Allocation manuelle des pertes en cours (defenseur humain) ; null hors allocation. */
  const [manualAllocation, setManualAllocation] = useState<ManualAllocation | null>(null);
  /** Ref miroir pour accès synchrone dans executeAction / callbacks de clic. */
  const manualAllocationRef = useRef<ManualAllocation | null>(null);
  manualAllocationRef.current = manualAllocation;
  /** Déclaration de l'ordre des groupes d'allocation (cible hétérogène / CHARACTER). */
  const [manualOrderRequest, setManualOrderRequest] = useState<ManualOrderRequest | null>(null);
  const manualOrderRequestRef = useRef<ManualOrderRequest | null>(null);
  manualOrderRequestRef.current = manualOrderRequest;

  // Track last action to detect activate_unit in shoot phase
  const lastActionRef = useRef<{ action: string; phase: string; unitId?: string } | null>(null);
  const ruleChoicePreviousSelectedUnitIdRef = useRef<number | null>(null);
  /** Bloque les doubles clics d’activation (move / tir / fight) pendant la requête API. */
  const activationInProgressRef = useRef(false);
  /**
   * Une seule requête ``fight`` à la fois : clics rapides sur la cible envoyaient plusieurs POST
   * en parallèle ; la N+1 peut recevoir ``no_attacks_remaining`` (ATTACK_LEFT déjà à 0) alors que
   * l’UI n’a pas encore reçu la réponse précédente.
   */
  const fightRequestChainRef = useRef(Promise.resolve());
  /** File des clics cible CC en attente (left click) pour exécution séquentielle. */
  const queuedFightTargetClicksRef = useRef<number[]>([]);
  /** Exécuteur de file CC actif (évite deux boucles concurrentes). */
  const fightClickQueueProcessingRef = useRef(false);
  /** Sérialise les interactions CC (``left_click`` / ``right_click`` / report) comme l’ancien filet ``fight``. */
  const enqueueFightRequest = useCallback((run: () => Promise<unknown> | unknown) => {
    const next = fightRequestChainRef.current.then(() => Promise.resolve(run()));
    fightRequestChainRef.current = next.then(() => undefined).catch(() => undefined);
    return next;
  }, []);
  /** Dernier ``gameState`` connu (pour gardes client avant envoi ``fight``). */
  const latestGameStateRef = useRef<APIGameState | null>(null);
  /** Unité en cours d’activation — curseur attente sur le plateau (A / perfs ressenti). */
  const [activationPendingUnitId, setActivationPendingUnitId] = useState<number | null>(null);

  // Load config values
  useEffect(() => {
    getMaxTurnsFromConfig().then(setMaxTurnsFromConfig);
  }, []);

  const activeRuleChoicePromptFromState = gameState?.active_rule_choice_prompt ?? null;

  // Keep rule choice popup state synchronized with backend game_state.
  // This is required in PvE when phase transitions/AI processing update game_state
  // without going through the "waiting_for_rule_choice" executeAction branch.
  useEffect(() => {
    if (activeRuleChoicePromptFromState) {
      if (ruleChoicePreviousSelectedUnitIdRef.current === null) {
        ruleChoicePreviousSelectedUnitIdRef.current = selectedUnitId;
      }
      setRuleChoicePrompt(activeRuleChoicePromptFromState);
      const promptUnitId = Number.parseInt(activeRuleChoicePromptFromState.unit_id, 10);
      if (!Number.isNaN(promptUnitId)) {
        setSelectedUnitId(promptUnitId);
      }
      return;
    }

    setRuleChoicePrompt(null);
    if (ruleChoicePreviousSelectedUnitIdRef.current !== null) {
      setSelectedUnitId(ruleChoicePreviousSelectedUnitIdRef.current);
      ruleChoicePreviousSelectedUnitIdRef.current = null;
    }
  }, [activeRuleChoicePromptFromState, selectedUnitId]);

  // Initialize game - FIXED: Added ref to prevent multiple calls
  const gameInitialized = useRef(false);

  useEffect(() => {
    if (gameInitialized.current) {
      return;
    }

    const startGame = async () => {
      try {
        gameInitialized.current = true;
        setLoading(true);

        // Detect active game mode from URL
        const urlParams = new URLSearchParams(window.location.search);
        const mode = urlParams.get("mode");
        const isPvEMode = mode === "pve";
        const isEndlessDutyMode = mode === "endless_duty";
        const isPvETestMode = mode === "pve_test";
        const isPvPTestMode = mode === "pvp_test";
        const isTutorialMode = mode === "tutorial";
        const requestedModeCode = isTutorialMode
          ? "pve"
          : isEndlessDutyMode
            ? "endless_duty"
            : isPvETestMode
              ? "pve_test"
              : isPvEMode
                ? "pve"
                : isPvPTestMode
                  ? "pvp_test"
                  : "pvp";

        const requestPayload: Record<string, unknown> = {
          pve_mode: isPvEMode || isPvETestMode || isTutorialMode || isEndlessDutyMode,
          mode_code: requestedModeCode,
        };
        if (isTutorialMode) {
          requestPayload.scenario_file = "config/tutorial/scenario_etape1.json";
        } else if (isEndlessDutyMode) {
          requestPayload.scenario_file = "config/scenario_endless_duty.json";
        } else if (isPvPTestMode) {
          requestPayload.scenario_file = "config/scenario_pvp_test.json";
        } else if (isPvETestMode) {
          requestPayload.scenario_file = "config/scenario_pve_test.json";
        } else if (isPvEMode) {
          requestPayload.scenario_file = "config/scenario_pve.json";
        }
        if (isPvPTestMode || isPvETestMode) {
          const boardParam = new URLSearchParams(window.location.search).get("board") ?? "x5_44x60";
          requestPayload.board_path = boardParam;
        }

        const authSession = getAuthSession();
        if (!authSession?.token) {
          throw new Error("Session utilisateur manquante. Merci de vous reconnecter.");
        }

        const response = await fetch(`${API_BASE}/game/start`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authSession.token}`,
          },
          body: JSON.stringify(requestPayload),
        });

        const data = (await response.json()) as {
          success?: boolean;
          error?: string;
          game_state?: APIGameState;
          endless_duty_state?: unknown;
        };
        if (!response.ok) {
          throw new Error(data.error ?? `Failed to start game: HTTP ${response.status}`);
        }
        if (data.success) {
          const expectedPlayer2Type: "human" | "ai" =
            requestedModeCode === "pve" ||
            requestedModeCode === "pve_test" ||
            requestedModeCode === "endless_duty"
              ? "ai"
              : "human";
          const player2Type = data.game_state?.player_types?.["2"];
          if (player2Type !== expectedPlayer2Type) {
            throw new Error(
              `Game mode mismatch: expected player 2 type '${expectedPlayer2Type}', got '${String(player2Type)}'`
            );
          }
          setGameState(hydrateApiGameStateMovePreviewTransport(data.game_state ?? null));
          setEndlessDutyState((data.endless_duty_state as EndlessDutyState | undefined) ?? null);
        } else {
          throw new Error(data.error || "Failed to start game");
        }
      } catch (err) {
        setError(formatApiConnectionError(err));
        gameInitialized.current = false; // Reset on error
      } finally {
        setLoading(false);
      }
    };

    startGame();
  }, []);

  /** Relance une partie avec le scénario donné (utilisé par le tutoriel pour etape2/etape3). options.preserveP1PositionsFrom : état de jeu à partir duquel garder les positions des unités P1. skipLoading : ne pas afficher l'écran de chargement (évite de démonter TutorialProvider pendant la transition). */
  const startGameWithScenario = useCallback(
    async (
      scenarioFile: string,
      options?: { preserveP1PositionsFrom?: APIGameState | null; skipLoading?: boolean }
    ) => {
      const authSession = getAuthSession();
      if (!authSession?.token) {
        setError("Session utilisateur manquante. Merci de vous reconnecter.");
        return;
      }
      const skipLoading = options?.skipLoading ?? options?.preserveP1PositionsFrom != null;
      if (!skipLoading) {
        setLoading(true);
      }
      try {
        const body: Record<string, unknown> = {
          pve_mode: true,
          mode_code: "pve",
          scenario_file: scenarioFile,
        };
        if (options?.preserveP1PositionsFrom != null) {
          body.preserve_p1_positions_from = options.preserveP1PositionsFrom;
        }
        const response = await fetch(`${API_BASE}/game/start`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authSession.token}`,
          },
          body: JSON.stringify(body),
        });
        if (!response.ok) {
          throw new Error(`Failed to start game: ${response.status}`);
        }
        const data = await response.json();
        if (data.success && data.game_state) {
          setGameState(hydrateApiGameStateMovePreviewTransport(data.game_state ?? null));
          setEndlessDutyState((data.endless_duty_state as EndlessDutyState | undefined) ?? null);
        } else {
          throw new Error(data.error || "Failed to start game");
        }
      } catch (err) {
        setError(formatApiConnectionError(err));
      } finally {
        if (!skipLoading) {
          setLoading(false);
        }
      }
    },
    []
  );

  /** POST /api/game/start pour le scénario PvE standard (fin tutoriel → mode PvE). */
  const startPveGame = useCallback(async () => {
    const authSession = getAuthSession();
    if (!authSession?.token) {
      setError("Session utilisateur manquante. Merci de vous reconnecter.");
      return;
    }
    setLoading(true);
    try {
      const requestPayload = {
        pve_mode: true,
        mode_code: "pve",
        scenario_file: "config/scenario_pve.json",
      };
      const response = await fetch(`${API_BASE}/game/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authSession.token}`,
        },
        body: JSON.stringify(requestPayload),
      });
      if (!response.ok) {
        throw new Error(`Failed to start game: ${response.status}`);
      }
      const data = await response.json();
      if (!data.success || !data.game_state) {
        throw new Error(data.error || "Failed to start game");
      }
      const expectedPlayer2Type: "human" | "ai" = "ai";
      const player2Type = data.game_state?.player_types?.["2"];
      if (player2Type !== expectedPlayer2Type) {
        throw new Error(
          `Game mode mismatch: expected player 2 type '${expectedPlayer2Type}', got '${String(player2Type)}'`
        );
      }
      setGameState(hydrateApiGameStateMovePreviewTransport(data.game_state ?? null));
      setEndlessDutyState((data.endless_duty_state as EndlessDutyState | undefined) ?? null);
    } catch (err) {
      setError(formatApiConnectionError(err));
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  /** POST /api/game/start pour une partie PvP locale (Continuer sans PvE). */
  const startPvpGame = useCallback(async () => {
    const authSession = getAuthSession();
    if (!authSession?.token) {
      setError("Session utilisateur manquante. Merci de vous reconnecter.");
      return;
    }
    setLoading(true);
    try {
      const requestPayload = {
        pve_mode: false,
        mode_code: "pvp",
        scenario_file: "config/scenario_pvp.json",
      };
      const response = await fetch(`${API_BASE}/game/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authSession.token}`,
        },
        body: JSON.stringify(requestPayload),
      });
      if (!response.ok) {
        throw new Error(`Failed to start game: ${response.status}`);
      }
      const data = await response.json();
      if (!data.success || !data.game_state) {
        throw new Error(data.error || "Failed to start game");
      }
      const expectedPlayer2Type: "human" | "ai" = "human";
      const player2Type = data.game_state?.player_types?.["2"];
      if (player2Type !== expectedPlayer2Type) {
        throw new Error(
          `Game mode mismatch: expected player 2 type '${expectedPlayer2Type}', got '${String(player2Type)}'`
        );
      }
      setGameState(hydrateApiGameStateMovePreviewTransport(data.game_state ?? null));
      setEndlessDutyState((data.endless_duty_state as EndlessDutyState | undefined) ?? null);
    } catch (err) {
      setError(formatApiConnectionError(err));
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // Listen for weapon selection events to update gameState
  useEffect(() => {
    const weaponSelectedHandler = (e: Event) => {
      interface WeaponSelectedEventDetail {
        gameState: APIGameState;
        availableWeapons?: Array<{
          index: number;
          weapon: Weapon;
          can_use?: boolean;
          canUse?: boolean;
          reason?: string;
        }>;
        weaponIndex?: number;
        validTargets?: Array<string | number>;
        coverByUnitId?: Record<string, boolean>;
        hiddenTooFarByUnitId?: Record<string, boolean>;
        isSquadMode?: boolean;
      }
      const {
        gameState: newGameState,
        availableWeapons,
        weaponIndex: selectedWeaponIndex,
        validTargets: weaponValidTargets,
        coverByUnitId: weaponCoverByUnitId,
        hiddenTooFarByUnitId: weaponHiddenTooFarByUnitId,
        isSquadMode: weaponIsSquadMode,
      } = (e as CustomEvent<WeaponSelectedEventDetail>).detail;

      // Mode squad : l'arme choisie devient l'arme active du plan + blink des cibles valides de cette arme.
      if (weaponIsSquadMode && selectedWeaponIndex !== undefined && squadShootPlanRef.current) {
        // Ne PAS désélectionner la fig active : sinon le simple clic per-fig (1 clic = désignation)
        // ne marcherait plus et il faudrait double-cliquer. La fig reste active après le choix d'arme.
        setSquadShootPlan((prev) =>
          prev ? { ...prev, activeWeaponIndex: selectedWeaponIndex } : prev
        );
        const blinkIds = Array.isArray(weaponValidTargets)
          ? weaponValidTargets.map((x) => (typeof x === "string" ? parseInt(x, 10) : x))
          : [];
        if (
          !weaponCoverByUnitId ||
          typeof weaponCoverByUnitId !== "object" ||
          Array.isArray(weaponCoverByUnitId)
        ) {
          throw new Error("squad_select_weapon: cover_by_unit_id absent/invalid in response");
        }
        const coverByUnitId: Record<string, boolean> = {};
        for (const [tid, inCover] of Object.entries(weaponCoverByUnitId)) {
          if (typeof inCover !== "boolean") {
            throw new Error(`squad_select_weapon: cover_by_unit_id.${tid} must be boolean`);
          }
          coverByUnitId[tid] = inCover;
        }
        if (
          !weaponHiddenTooFarByUnitId ||
          typeof weaponHiddenTooFarByUnitId !== "object" ||
          Array.isArray(weaponHiddenTooFarByUnitId)
        ) {
          throw new Error(
            "squad_select_weapon: hidden_too_far_by_unit_id absent/invalid in response"
          );
        }
        const hiddenTooFarByUnitId: Record<string, boolean> = {};
        for (const [tid, tooFar] of Object.entries(weaponHiddenTooFarByUnitId)) {
          if (typeof tooFar !== "boolean") {
            throw new Error(
              `squad_select_weapon: hidden_too_far_by_unit_id.${tid} must be boolean`
            );
          }
          hiddenTooFarByUnitId[tid] = tooFar;
        }
        setBlinkingUnits((prev) => {
          if (prev.blinkTimer) clearInterval(prev.blinkTimer);
          const timer = blinkIds.length ? window.setInterval(() => {}, 500) : null;
          return {
            unitIds: blinkIds,
            blinkTimer: timer,
            attackerId: squadShootPlanRef.current?.unitId ?? null,
            coverByUnitId,
            hiddenTooFarByUnitId,
          };
        });
      }
      if (newGameState) {
        if (newGameState.units && newGameState.active_shooting_unit) {
          const activeId = newGameState.active_shooting_unit.toString();
          const updatedUnits = [...newGameState.units];
          const unitIndex = updatedUnits.findIndex(
            (u: { id: string | number }) => u.id.toString() === activeId
          );
          if (unitIndex >= 0) {
            updatedUnits[unitIndex] = {
              ...updatedUnits[unitIndex],
              manualWeaponSelected: true,
              ...(availableWeapons ? { available_weapons: availableWeapons } : {}),
            };
            newGameState.units = updatedUnits;
          }
        }
        setGameState(hydrateApiGameStateMovePreviewTransport(newGameState));
        setBlinkVersion((prev) => prev + 1);
        if (newGameState.phase === "shoot" && targetPreview) {
          const shooter = newGameState.units.find((u) => {
            const unitId = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
            return unitId === targetPreview.shooterId;
          });
          const target = newGameState.units.find((u) => {
            const unitId = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
            return unitId === targetPreview.targetId;
          });
          if (!shooter || !target) {
            throw new Error(
              "Missing shooter or target when updating target preview after weapon selection"
            );
          }
          const shooterUnit: Unit = {
            ...shooter,
            id: typeof shooter.id === "string" ? parseInt(shooter.id, 10) : shooter.id,
            player: shooter.player as PlayerId,
          };
          const targetUnit: Unit = {
            ...target,
            id: typeof target.id === "string" ? parseInt(target.id, 10) : target.id,
            player: target.player as PlayerId,
          };
          const rangedEff = getSelectedRangedWeaponAgainstTarget(shooterUnit, targetUnit);
          if (!rangedEff) {
            throw new Error(
              `No ranged weapon available for unit ${shooterUnit.id} after weapon selection`
            );
          }
          if (blinkingUnits.blinkTimer) {
            clearInterval(blinkingUnits.blinkTimer);
          }
          setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
          setTargetPreview((prevPreview) => {
            if (!prevPreview) return null;
            return {
              ...prevPreview,
              hitProbability: rangedEff.hitProbability,
              woundProbability: rangedEff.woundProbability,
              saveProbability: rangedEff.saveProbability,
              overallProbability: rangedEff.overallProbability,
              potentialDamage: rangedEff.potentialDamage,
              expectedDamage: rangedEff.expectedDamage,
            };
          });
        }
      }
    };

    const weaponSelectErrorHandler = (e: Event) => {
      const detail = (e as CustomEvent<{ message?: string }>).detail;
      setError(`Weapon selection failed: ${detail?.message ?? "unknown error"}`);
    };

    window.addEventListener("weaponSelected", weaponSelectedHandler);
    window.addEventListener("weaponSelectError", weaponSelectErrorHandler);
    return () => {
      window.removeEventListener("weaponSelected", weaponSelectedHandler);
      window.removeEventListener("weaponSelectError", weaponSelectErrorHandler);
    };
  }, [targetPreview, blinkingUnits.blinkTimer]);

  // Reset mode to "select" when phase changes only (not when targetPreview blink timer clears).
  // If targetPreview?.blinkTimer is in the dependency array, clearing targetPreview when entering
  // advancePreview re-runs this effect and wipes advanceDestinations / mode — no orange preview.
  useEffect(() => {
    if (gameState?.phase) {
      if (targetPreview?.blinkTimer) {
        clearInterval(targetPreview.blinkTimer);
      }
      setTargetPreview(null);
      // Reset mode when phase changes (except if we're already in the correct mode for the phase)
      // This ensures mode is reset after fight phase ends
      setMode("select");
      setSelectedUnitId(null);
      setMovePreview(null);
      setPendingPreviewAction(null);
      setAttackPreview(null);
      setChargeDestinations([]);
      setChargePreviewOverlayHexes([]);
      setChargeReferenceHex(null);
      clearChargePoolRefs();
      setPendingChargeRollDisplay(null);
      setChargePreviewTargetId(null);
      setPileInDestinations([]);
      setAdvanceDestinations([]);
      setPostShootMoveDestinations([]);
      setAdvancingUnitId(null);
      setAdvanceRoll(null);
      setActiveUnitEngaged(null);
    }
  }, [gameState?.phase, targetPreview?.blinkTimer, clearChargePoolRefs]);

  useEffect(() => {
    latestGameStateRef.current = gameState;
  }, [gameState]);

  /** Quitter la prévisualisation CC (phase fight) après fin d’activation ou erreur ``no_attacks_remaining``. */
  const clearFightAttackActivationUi = useCallback(() => {
    queuedFightTargetClicksRef.current = [];
    setBlinkingUnits((prev) => {
      if (prev.blinkTimer) {
        clearInterval(prev.blinkTimer);
      }
      return { unitIds: [], blinkTimer: null, attackerId: null };
    });
    setAttackPreview(null);
    setPileInDestinations([]);
    moveDestPoolRef.current = new Set();
    footprintZoneRef.current = new Set();
    footprintMaskLoopsRef.current = null;
    setMode("select");
    setSelectedUnitId(null);
  }, []);

  // Execute action via API
  // biome-ignore lint/correctness/useExhaustiveDependencies: handleStartChargeModelMove and readSquadModelPositions are declared later in the file — adding them to deps would cause noInvalidUseBeforeDeclaration
  const executeAction = useCallback(
    async (action: Record<string, unknown>) => {
      logClientDebugConsoleNotifyIfEnabled();
      const isFightCombatClientTrace =
        action.action === "fight" ||
        (gameState?.phase === "fight" &&
          (action.action === "left_click" || action.action === "right_click"));
      if (isFightCombatClientTrace) {
        logFightClick("executeAction: envoi action fight / pointeur CC", {
          action: action.action,
          unitId: action.unitId,
          targetId: action.targetId,
          phase: gameState?.phase,
          active_fight_unit: gameState?.active_fight_unit,
        });
      }
      if (!gameState) {
        if (isFightCombatClientTrace) {
          logFightClick("executeAction: abandon (gameState null)");
        }
        return;
      }
      if (!gameState.units_cache) {
        if (isFightCombatClientTrace) {
          logFightClick("executeAction: abandon (units_cache manquant)");
        }
        setError(
          "Partie non demarree: units_cache manquant. Lance d'abord /api/game/start avec succes."
        );
        return;
      }
      if (gameState.game_over) {
        if (isFightCombatClientTrace) {
          logFightClick("executeAction: abandon (game_over)");
        }
        return;
      }

      // Track last action for auto-advance detection
      lastActionRef.current = {
        action: action.action as string,
        phase: gameState.phase,
        unitId:
          typeof action.unitId === "string" || typeof action.unitId === "number"
            ? String(action.unitId)
            : undefined,
      };

      try {
        const requestId = Date.now();
        const body: Record<string, unknown> = { ...action, requestId };
        if (_movePreviewMaskLoopsTransport.clientHash.length > 0) {
          body.move_preview_mask_loops_client_hash = _movePreviewMaskLoopsTransport.clientHash;
        }
        const requestBody = JSON.stringify(body);
        const response = await fetch(`${API_BASE}/game/action`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: requestBody,
        });

        if (!response.ok) {
          throw new Error(`Action failed: ${response.status}`);
        }

        const serverTimingHeader = response.headers.get("Server-Timing");
        const payloadBytesHeader = response.headers.get("X-W40k-Payload-Bytes");
        if (
          isActionLogTraceEnabled() &&
          (serverTimingHeader !== null || payloadBytesHeader !== null)
        ) {
          console.info("[SERVER_PERF] /game/action (serveur ; Network → en-têtes / Timing)", {
            "Server-Timing": serverTimingHeader,
            "X-W40k-Payload-Bytes": payloadBytesHeader,
            hint:
              "dur en ms : engine = moteur (handlers, end_phase, …), serialize = préparation état, " +
              "json_encode = sérialisation du corps. Sous-découpe moteur (END_PHASE, CHARGE_*, …) : " +
              "variable W40K_PERF_TIMING=1 sur le process Python + fichier perf_timing.log à la racine du dépôt.",
          });
        }

        const data = await response.json();
        if (isFightCombatClientTrace) {
          const r = data.result as Record<string, unknown> | undefined;
          logFightClick("executeAction: réponse JSON (fight)", {
            success: data.success,
            error: data.error,
            phase: (data.game_state as { phase?: string } | undefined)?.phase,
            active_fight_unit: (
              data.game_state as { active_fight_unit?: string | null } | undefined
            )?.active_fight_unit,
            resultAction: r?.action,
            waiting_for_player: r?.waiting_for_player,
            attack_executed: r?.attack_executed,
            activation_ended: r?.activation_ended,
            resultKeys: r ? Object.keys(r) : [],
          });
        }
        setEndlessDutyState((data.endless_duty_state as EndlessDutyState | undefined) ?? null);

        const responsePhaseForLog = (data.game_state as { phase?: string } | undefined)?.phase;
        const rawActionLogs = Array.isArray(data.action_logs)
          ? (data.action_logs as Record<string, unknown>[])
          : [];
        const incomingPhaseFromPayload =
          data.game_state != null &&
          typeof (data.game_state as { phase?: unknown }).phase === "string"
            ? String((data.game_state as { phase: string }).phase)
            : undefined;
        const resultActivationEnded =
          (data.result as { activation_ended?: boolean } | undefined)?.activation_ended === true;
        /**
         * Fin d’activation CC ou sortie de la phase fight dans la même réponse : après les
         * ``backendLogEvent``, céder un macrotask (comme ``pending_shooting_phase_init`` plus bas)
         * pour que le Game Log committe avant ``setGameState`` / nettoyage preview — évite l’effet
         * « freeze » sur la dernière attaque alors que le serveur a déjà répondu.
         */
        const yieldAfterFightCombatLogsBeforeStateSuite =
          Boolean(data.success) &&
          gameState?.phase === "fight" &&
          (action.action === "left_click" || action.action === "right_click") &&
          rawActionLogs.length > 0 &&
          rawActionLogs.some(
            (e) =>
              e.type === "combat" &&
              e.phase === "fight" &&
              typeof e.message === "string" &&
              e.message.trim().length > 0
          ) &&
          (resultActivationEnded ||
            (incomingPhaseFromPayload !== undefined && incomingPhaseFromPayload !== "fight"));
        if (rawActionLogs.length > 0) {
          logActionLogBatchTrace("executeAction /game/action", rawActionLogs, {
            requestAction: action.action,
            success: data.success,
            responsePhase: responsePhaseForLog,
          });
        } else if (isActionLogTraceEnabled()) {
          logActionLogBatchTrace("executeAction /game/action", [], {
            requestAction: action.action,
            success: data.success,
            responsePhase: responsePhaseForLog,
            note:
              responsePhaseForLog === "fight"
                ? "aucune entrée action_logs (phase fight)"
                : `aucune entrée action_logs (phase ${responsePhaseForLog ?? "?"})`,
          });
        }

        // Process detailed backend action logs FIRST
        if (data.action_logs && data.action_logs.length > 0) {
          interface ActionLogEntry {
            message?: string;
            shootDetails?: Array<Record<string, unknown>>;
            [key: string]: unknown;
          }
          const actionLogsBatch = dedupeActionLogBatch(data.action_logs as ActionLogEntry[]);
          actionLogsBatch.forEach((logEntry: ActionLogEntry) => {
            if (!shouldEmitActionLogEvent(logEntry as Record<string, unknown>)) {
              logActionLogEmitTrace(
                "executeAction /game/action",
                logEntry as Record<string, unknown>,
                false,
                `cross_request_dedupe_<${CROSS_ACTION_LOG_SUPPRESS_MS}ms`
              );
              return;
            }
            logActionLogEmitTrace(
              "executeAction /game/action",
              logEntry as Record<string, unknown>,
              true
            );
            const shootDetail = logEntry.shootDetails?.[0];

            window.dispatchEvent(
              new CustomEvent("backendLogEvent", {
                detail: {
                  type: logEntry.type,
                  message: logEntry.message,
                  turn: logEntry.turn,
                  phase: logEntry.phase,
                  shooterId: logEntry.shooterId || logEntry.attackerId || logEntry.unitId, // shooting/fight/other events
                  targetId: logEntry.targetId,
                  player: logEntry.player,
                  // Extract damage/target_died from shootDetails if present (fight), otherwise use flat fields (shooting)
                  damage: logEntry.damage ?? shootDetail?.damageDealt,
                  target_died: logEntry.target_died ?? shootDetail?.targetDied,
                  // Extract roll data from shootDetails if present (fight), otherwise use flat fields (shooting)
                  hitRoll: logEntry.hitRoll || logEntry.hit_roll || shootDetail?.attackRoll,
                  woundRoll: logEntry.woundRoll || logEntry.wound_roll || shootDetail?.strengthRoll,
                  saveRoll: logEntry.saveRoll || logEntry.save_roll || shootDetail?.saveRoll,
                  saveTarget:
                    logEntry.saveTarget || logEntry.save_target || shootDetail?.saveTarget,
                  saveSkipped: logEntry.saveSkipped ?? logEntry.save_skipped,
                  saveSkipReason: logEntry.saveSkipReason || logEntry.save_skip_reason,
                  devastatingWoundsApplied:
                    logEntry.devastatingWoundsApplied ||
                    logEntry.devastating_wounds_applied ||
                    false,
                  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Pass through weapon name
                  weaponName: logEntry.weaponName,
                  targetUnitType: logEntry.targetUnitType,
                  // Pass through shootDetails for direct use by getEventTypeClass color logic
                  shootDetails: logEntry.shootDetails,
                  result: logEntry.result,
                  timestamp: new Date(),
                },
              })
            );
          });
        }

        if (yieldAfterFightCombatLogsBeforeStateSuite) {
          await new Promise<void>((resolve) => {
            setTimeout(resolve, 0);
          });
        }

        // DEBUG: Log full response structure to understand blinking data location

        if (!data.success && isFightCombatClientTrace) {
          const r = data.result as Record<string, unknown> | undefined;
          logFightClick("executeAction: success=false (fight), état non mis à jour par ce chemin", {
            error: data.error,
            resultError: r?.error,
            result: r,
          });
        }

        // Réponses fight en échec : appliquer quand même ``game_state`` (sinon l’UI reste en attackPreview
        // avec ATTACK_LEFT / active_fight_unit obsolètes) et sortir du mode cible si plus d’attaques.
        if (!data.success && isFightCombatClientTrace && data.game_state) {
          setGameState((p) => {
            const merged = mergeGameStatePreservingOmittedObjectives(
              p,
              data.game_state as APIGameState
            );
            latestGameStateRef.current = merged;
            return merged;
          });
          const r = data.result as Record<string, unknown> | undefined;
          const err = r?.error;
          if (err === "no_attacks_remaining" || err === "no_weapons_available") {
            clearFightAttackActivationUi();
          }
        }

        if (data.success) {
          // TEST/DEBUG : force_battle_shock est une action de côté qui ne touche QUE le flag
          // battle_shocked de l'unité. On merge le game_state pour le refléter et on sort, sans
          // passer par la machine d'état d'activation (qui sinon déselectionne l'unité active et
          // casse le rendu du move en cours).
          if (
            data.result?.action === "force_battle_shock" ||
            data.result?.action === "force_charged"
          ) {
            setGameState((p) => {
              const merged = mergeGameStatePreservingOmittedObjectives(
                p,
                data.game_state as APIGameState
              );
              latestGameStateRef.current = merged;
              return merged;
            });
            return;
          }
          if (
            data.result?.action === "waiting_for_rule_choice" &&
            data.result?.waiting_for_player === true &&
            data.result?.rule_choice_prompt
          ) {
            if (ruleChoicePreviousSelectedUnitIdRef.current === null) {
              ruleChoicePreviousSelectedUnitIdRef.current = selectedUnitId;
            }
            setRuleChoicePrompt(data.result.rule_choice_prompt as RuleChoicePrompt);
            if (data.result?.unitId) {
              setSelectedUnitId(parseInt(data.result.unitId, 10));
            }
            setGameState((p) => {
              const merged = mergeGameStatePreservingOmittedObjectives(
                p,
                data.game_state as APIGameState
              );
              latestGameStateRef.current = merged;
              return merged;
            });
            return;
          }
          if (data.result?.action === "select_rule_choice") {
            setRuleChoicePrompt(null);
            if (data.game_state?.active_rule_choice_prompt == null) {
              setSelectedUnitId(ruleChoicePreviousSelectedUnitIdRef.current);
              ruleChoicePreviousSelectedUnitIdRef.current = null;
            }
          }
          if (
            data.result?.action !== "waiting_for_rule_choice" &&
            data.game_state?.active_rule_choice_prompt == null
          ) {
            setRuleChoicePrompt(null);
            if (ruleChoicePreviousSelectedUnitIdRef.current !== null) {
              setSelectedUnitId(ruleChoicePreviousSelectedUnitIdRef.current);
              ruleChoicePreviousSelectedUnitIdRef.current = null;
            }
          }

          // Déclaration de l'ordre des groupes d'allocation (cible hétérogène / CHARACTER) :
          // le backend attend l'ordre avant l'allocation fig par fig.
          if (
            (data.result?.action === "squad_shoot_declare_order" ||
              data.result?.action === "squad_fight_declare_order") &&
            data.result?.waiting_for_player === true &&
            data.result?.order_request
          ) {
            const isFightOrder = data.result.action === "squad_fight_declare_order";
            setManualOrderRequest({
              ...(data.result.order_request as ManualOrderRequest),
              kind: isFightOrder ? "fight" : "shoot",
            });
            if (manualAllocationRef.current !== null) setManualAllocation(null);
            setGameState((p) => {
              const merged = mergeGameStatePreservingOmittedObjectives(
                p,
                data.game_state as APIGameState
              );
              latestGameStateRef.current = merged;
              return merged;
            });
            return;
          }

          // Allocation manuelle des pertes (defenseur humain) : le backend attend un
          // choix de figurine. Capté ici comme rule_choice ; le garde-fou backend renvoie
          // le même payload tant que l'allocation n'est pas terminée → l'état se ré-arme.
          if (
            (data.result?.action === "squad_shoot_manual_alloc" ||
              data.result?.action === "squad_fight_manual_alloc") &&
            data.result?.waiting_for_player === true &&
            data.result?.allocation
          ) {
            const isFightAlloc = data.result.action === "squad_fight_manual_alloc";
            setManualAllocation({
              ...(data.result.allocation as ManualAllocation),
              kind: isFightAlloc ? "fight" : "shoot",
            });
            if (manualOrderRequestRef.current !== null) setManualOrderRequest(null);
            setGameState((p) => {
              const merged = mergeGameStatePreservingOmittedObjectives(
                p,
                data.game_state as APIGameState
              );
              latestGameStateRef.current = merged;
              return merged;
            });
            return;
          }

          // Desperate Escape (09.07) : popup hazard à l'activation (engagée + battle-shocked).
          // Le move est suspendu côté backend ; le joueur confirme pour rouler le hazard.
          if (data.result?.action === "requires_hazard" && data.result?.requires_hazard === true) {
            const huid = data.result?.unitId ?? data.game_state?.active_movement_unit;
            if (huid != null) {
              const hp = { unitId: parseInt(String(huid), 10) };
              setHazardWarningPopup(hp);
              hazardWarningPopupRef.current = hp; // synchro immédiate pour le gate post-await
            }
            setGameState((p) => {
              const merged = mergeGameStatePreservingOmittedObjectives(
                p,
                data.game_state as APIGameState
              );
              latestGameStateRef.current = merged;
              return merged;
            });
            return;
          }

          // Desperate Escape : attribution manuelle des mortal wounds (06.02). Même rendu que
          // l'allocation du tir (anneaux + clic figurine) via le flag kind:"hazard".
          if (
            data.result?.action === "squad_hazard_manual_alloc" &&
            data.result?.waiting_for_player === true &&
            data.result?.allocation
          ) {
            const ha = data.result.allocation as {
              squad_id: string;
              controlling_player: number;
              choices: ManualAllocation["choices"];
              wounds_remaining: number;
            };
            setManualAllocation({
              kind: "hazard",
              attacker_unit_id: String(ha.squad_id),
              target_unit_id: String(ha.squad_id),
              defender_player: ha.controlling_player,
              choices: ha.choices,
              wounds_remaining: ha.wounds_remaining,
            });
            setGameState((p) => {
              const merged = mergeGameStatePreservingOmittedObjectives(
                p,
                data.game_state as APIGameState
              );
              latestGameStateRef.current = merged;
              return merged;
            });
            return;
          }

          // Desperate Escape : l'unité est détruite par le hazard → fin d'activation sans move.
          if (data.result?.action === "desperate_escape_died") {
            if (manualAllocationRef.current !== null) setManualAllocation(null);
            setHazardWarningPopup(null);
            hazardWarningPopupRef.current = null;
            setActiveUnitEngaged(null);
            setSelectedUnitId(null);
            setMode("select");
            setGameState((p) => {
              const merged = mergeGameStatePreservingOmittedObjectives(
                p,
                data.game_state as APIGameState
              );
              latestGameStateRef.current = merged;
              return merged;
            });
            return;
          }

          // Toute autre réponse alors qu'une allocation/déclaration était en cours = terminée
          // (done) → on libère les états manuels.
          if (manualAllocationRef.current !== null) {
            setManualAllocation(null);
          }
          if (manualOrderRequestRef.current !== null) {
            setManualOrderRequest(null);
          }

          // Last move emptied move pool: PvP defers shooting init to a second request — chain it.
          if (data.result?.pending_shooting_phase_init === true) {
            setTimeout(() => {
              void executeAction({ action: "advance_phase", from: "move" });
            }, 0);
          }

          // CRITICAL: Handle empty activation pools before other processing
          if (
            data.game_state?.phase === "shoot" &&
            Array.isArray(data.game_state.shoot_activation_pool) &&
            data.game_state.shoot_activation_pool.length === 0
          ) {
            setTimeout(async () => {
              await executeAction({ action: "advance_phase", from: "shoot" });
            }, 100);
          }

          // V11 : avancer la phase fight quand aucune unité n'est actionnable
          // (fight_eligible_units vide ; le moteur gère les transitions de sous-phase).
          if (data.game_state?.phase === "fight") {
            const fightPool = Array.isArray(data.game_state.fight_eligible_units)
              ? data.game_state.fight_eligible_units
              : [];

            const allPoolsEmpty = fightPool.length === 0;

            const fightActivePending =
              (data.game_state as { fight_consolidation_pending?: boolean })
                .fight_consolidation_pending === true ||
              Boolean(
                (data.game_state as { fight_pile_in_pending?: boolean }).fight_pile_in_pending
              );

            if (allPoolsEmpty && !fightActivePending) {
              setTimeout(async () => {
                await executeAction({ action: "advance_phase", from: "fight" });
              }, 100);
            }
          }

          // Après advance *commis* (toCol/toRow) : badge + fin du preview orange. Pas sur advance_range seul.
          const advanceMoveCommitted =
            lastActionRef.current?.action === "advance" &&
            data.result &&
            typeof data.result.toCol === "number" &&
            typeof data.result.toRow === "number";
          if (advanceMoveCommitted) {
            const unitId = parseInt(
              String(data.result.unitId ?? lastActionRef.current?.unitId),
              10
            );
            const advanceRollValue = data.result.advance_range ?? data.result.advance_roll;
            if (advanceRollValue !== undefined && advanceRollValue !== null) {
              setAdvanceRoll(advanceRollValue);
            }
            setAdvancingUnitId(unitId);
            // Keep selected unit to show badge
            setSelectedUnitId(unitId);
            // Clear advance preview (destinations and mode) since advance is complete
            setAdvanceDestinations([]);
            // AI_TURN.md COMPLIANCE: Don't reset mode to "select" if unit can shoot after advance
            // If blinking_units is present, unit has valid targets and can shoot - mode will be set to "attackPreview" by blinking_units handler
            if (!data.result?.blinking_units || !data.result?.start_blinking) {
              setMode("select");
            }
          }

          // Backend returns allow_advance: true when active unit has no valid shooting targets.
          // Trust backend signal regardless of the initiating UI action (activate_unit or friendly_unit switch).
          // Ne pas passer en ``advancePreview`` ici : le moteur n’envoie ni ``advance_destinations`` ni
          // ``valid_move_destinations_pool`` sur ce signal (seulement après ``action: "advance"``).
          // ``advancePreview`` sans pool → moveDestPoolSize 0, icône/LoS advance cassés, WebGL surchargé.
          // L’icône Advance (overlay) suit ``canAdvance`` + ``active_shooting_unit`` ; pas de réécriture de mode ici.
          if (
            data.game_state?.phase === "shoot" &&
            data.result?.unitId &&
            data.result?.allow_advance === true
          ) {
            const hasValidBlinkTargets =
              data.result?.start_blinking === true &&
              Array.isArray(data.result.blinking_units) &&
              data.result.blinking_units.length > 0;
            // Ne pas interférer avec l’activation tir normale : si le moteur envoie déjà des cibles
            // clignotantes, STEP 1 / STEP 3 gèrent ``selectedUnitId`` et ``attackPreview``.
            if (!hasValidBlinkTargets) {
              const unitId = parseInt(data.result.unitId, 10);
              setSelectedUnitId(unitId);
            }
          }

          // Process backend cleanup signals
          if (data.result?.clear_preview) {
            setTargetPreview(null);
          }

          if (data.result?.clear_blinking_gentle) {
            // Clear central timers only - don't destroy renderer
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });

            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
          }

          if (
            lastActionRef.current?.phase === "shoot" &&
            (data.result?.activation_ended || data.result?.phase_complete)
          ) {
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });

            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
            if (data.game_state?.units && lastActionRef.current?.unitId) {
              const unitIndex = data.game_state.units.findIndex(
                (u: { id: string | number }) => u.id.toString() === lastActionRef.current?.unitId
              );
              if (unitIndex >= 0) {
                const updatedUnits = [...data.game_state.units];
                updatedUnits[unitIndex] = {
                  ...updatedUnits[unitIndex],
                  manualWeaponSelected: false,
                };
                data.game_state = {
                  ...data.game_state,
                  units: updatedUnits,
                };
              }
            }
          }

          if (data.result?.reset_mode) {
            setMode("select");
            // Clear advance state when mode resets
            setAdvanceDestinations([]);
            setPostShootMoveDestinations([]);
            setAdvancingUnitId(null);
            setAdvanceRoll(null);
          }

          if (data.result?.clear_selected_unit) {
            setSelectedUnitId(null);
            // Clear advance state when selected unit is cleared
            setAdvanceDestinations([]);
            setPostShootMoveDestinations([]);
            setAdvancingUnitId(null);
            setAdvanceRoll(null);
          }

          if (data.result?.clear_attack_preview && !advanceWarningPopup) {
            setMode("select");
          }

          // Auto-display Python console logs in browser (only during actions)
          if (data.game_state?.console_logs && data.game_state.console_logs.length > 0) {
            data.game_state.console_logs = [];
          }

          // Process blinking data and available_weapons from backend
          // Handle both cases: with and without empty_target_pool

          // STEP 1: Start blinking if blinking_units is present (regardless of empty_target_pool)
          if (data.result?.blinking_units && data.result?.start_blinking) {
            const newUnitIds = data.result.blinking_units.map((id: string) => parseInt(id, 10));
            const parseOptionalId = (
              rawId: string | number | null | undefined,
              label: string
            ): number | null => {
              if (rawId === null || rawId === undefined) {
                return null;
              }
              const parsedId = typeof rawId === "string" ? parseInt(rawId, 10) : rawId;
              if (!Number.isFinite(parsedId)) {
                throw new Error(`Invalid ${label}: ${String(rawId)}`);
              }
              return parsedId;
            };
            const phase = data.game_state?.phase;
            const newAttackerId =
              parseOptionalId(data.result?.unitId, "result.unitId") ??
              parseOptionalId(
                phase === "shoot"
                  ? data.game_state?.active_shooting_unit
                  : phase === "fight"
                    ? data.game_state?.active_fight_unit
                    : phase === "charge"
                      ? data.game_state?.active_charge_unit
                      : null,
                "active attacker unit id"
              );
            let coverByUnitId: Record<string, boolean> | undefined;
            if (phase === "shoot") {
              const rawCoverByUnitId = data.result.cover_by_unit_id;
              if (
                !rawCoverByUnitId ||
                typeof rawCoverByUnitId !== "object" ||
                Array.isArray(rawCoverByUnitId)
              ) {
                throw new Error("shoot blinking response missing required cover_by_unit_id");
              }
              coverByUnitId = {};
              for (const [unitId, inCover] of Object.entries(
                rawCoverByUnitId as Record<string, unknown>
              )) {
                if (typeof inCover !== "boolean") {
                  throw new Error(
                    `shoot blinking response cover_by_unit_id.${unitId} must be boolean`
                  );
                }
                coverByUnitId[unitId] = inCover;
              }
            }
            let hiddenTooFarByUnitId: Record<string, boolean> | undefined;
            if (phase === "shoot") {
              const rawTooFar = data.result.hidden_too_far_by_unit_id;
              if (!rawTooFar || typeof rawTooFar !== "object" || Array.isArray(rawTooFar)) {
                throw new Error(
                  "shoot blinking response missing required hidden_too_far_by_unit_id"
                );
              }
              hiddenTooFarByUnitId = {};
              for (const [unitId, tooFar] of Object.entries(rawTooFar as Record<string, unknown>)) {
                if (typeof tooFar !== "boolean") {
                  throw new Error(
                    `shoot blinking response hidden_too_far_by_unit_id.${unitId} must be boolean`
                  );
                }
                hiddenTooFarByUnitId[unitId] = tooFar;
              }
            }
            const coverKey = JSON.stringify(
              Object.entries(coverByUnitId ?? {}).sort(([a], [b]) => a.localeCompare(b))
            );
            const previousCoverKey = JSON.stringify(
              Object.entries(blinkingUnits.coverByUnitId ?? {}).sort(([a], [b]) =>
                a.localeCompare(b)
              )
            );
            const tooFarKey = JSON.stringify(
              Object.entries(hiddenTooFarByUnitId ?? {}).sort(([a], [b]) => a.localeCompare(b))
            );
            const previousTooFarKey = JSON.stringify(
              Object.entries(blinkingUnits.hiddenTooFarByUnitId ?? {}).sort(([a], [b]) =>
                a.localeCompare(b)
              )
            );

            // Check if we need to update: different unitIds, different attackerId, or no timer
            const unitIdsChanged =
              newUnitIds.length !== blinkingUnits.unitIds.length ||
              !newUnitIds.every((id: number) => blinkingUnits.unitIds.includes(id));
            const attackerIdChanged = newAttackerId !== blinkingUnits.attackerId;
            const coverByUnitIdChanged = coverKey !== previousCoverKey;
            const tooFarByUnitIdChanged = tooFarKey !== previousTooFarKey;
            const needsUpdate =
              !blinkingUnits.blinkTimer ||
              unitIdsChanged ||
              attackerIdChanged ||
              coverByUnitIdChanged ||
              tooFarByUnitIdChanged;

            if (needsUpdate) {
              // Clear any existing blinking timer
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }

              // Start blinking for all valid targets
              // Note: Actual blinking animation is handled locally in UnitRenderer
              // We only track which units should blink, not the blink state itself
              const timer = window.setInterval(() => {
                // Empty interval - blinking is handled locally in UnitRenderer
                // This timer is kept for cleanup purposes only
              }, 500);

              // Also update gameState and selectedUnitId for consistency
              if (data.game_state?.phase === "charge" && data.result?.unitId) {
                data.game_state = {
                  ...data.game_state,
                  active_charge_unit: data.result.unitId,
                };
                setSelectedUnitId(parseInt(data.result.unitId, 10));
              }

              setBlinkingUnits({
                unitIds: newUnitIds,
                blinkTimer: timer,
                attackerId: newAttackerId,
                coverByUnitId,
                hiddenTooFarByUnitId,
              });
              setBlinkVersion((prev) => prev + 1);
            }
          } else if (data.result?.blinking_units && !data.result?.start_blinking) {
            console.warn("💫 WARNING: blinking_units present but start_blinking is false");
          }

          // STEP 2: Propagate available_weapons to unit in game_state (required for weapon icon)
          // CRITICAL: This must happen BEFORE setGameState to ensure React detects the change
          if (data.result?.available_weapons && Array.isArray(data.result.available_weapons)) {
            const activeUnitId = data.game_state.active_shooting_unit ?? data.result.unitId;
            if (activeUnitId == null) {
              throw new Error(
                "available_weapons: active_shooting_unit and result.unitId both absent"
              );
            }
            if (data.game_state.units) {
              const unitIndex = data.game_state.units.findIndex(
                (u: { id: string | number }) => u.id.toString() === activeUnitId.toString()
              );
              if (unitIndex >= 0) {
                // Create new array to ensure React detects the change
                const updatedUnits = [...data.game_state.units];
                updatedUnits[unitIndex] = {
                  ...updatedUnits[unitIndex],
                  available_weapons: data.result.available_weapons,
                };
                // Also update selectedRngWeaponIndex if provided in result
                if (data.result.selectedRngWeaponIndex !== undefined) {
                  updatedUnits[unitIndex].selectedRngWeaponIndex =
                    data.result.selectedRngWeaponIndex;
                  updatedUnits[unitIndex].manualWeaponSelected = true;
                }
                data.game_state = {
                  ...data.game_state,
                  units: updatedUnits,
                };
              } else {
                console.warn(
                  "🔫 WARNING: Could not find unit",
                  activeUnitId,
                  "in game_state.units"
                );
              }
            } else {
              console.warn("🔫 WARNING: No active_shooting_unit or unitId in response", {
                active_shooting_unit: data.game_state.active_shooting_unit,
                unitId: data.result.unitId,
                has_available_weapons: !!data.result.available_weapons,
              });
            }
          }
          // Also handle selectedRngWeaponIndex even if available_weapons is not present
          else if (data.result?.selectedRngWeaponIndex !== undefined) {
            const activeUnitId = data.game_state.active_shooting_unit || data.result.unitId;
            if (activeUnitId && data.game_state.units) {
              const unitIndex = data.game_state.units.findIndex(
                (u: { id: string | number }) => u.id.toString() === activeUnitId.toString()
              );
              if (unitIndex >= 0) {
                const updatedUnits = [...data.game_state.units];
                updatedUnits[unitIndex] = {
                  ...updatedUnits[unitIndex],
                  selectedRngWeaponIndex: data.result.selectedRngWeaponIndex,
                  manualWeaponSelected: true,
                };
                data.game_state = {
                  ...data.game_state,
                  units: updatedUnits,
                };
              }
            }
          }

          // STEP 3: Tir uniquement — ne pas forcer attackPreview en phase charge (cibles de charge clignotantes).
          if (
            data.game_state?.phase === "shoot" &&
            data.result?.blinking_units &&
            data.result?.start_blinking
          ) {
            const hasValidTargets =
              Array.isArray(data.result.blinking_units) && data.result.blinking_units.length > 0;

            if (hasValidTargets) {
              setAttackPreview(null);
              setMode("attackPreview");

              const activeUnitId = data.game_state?.active_shooting_unit || data.result?.unitId;
              if (activeUnitId) {
                setSelectedUnitId(parseInt(activeUnitId, 10));
              }
            }
          }

          // Charge : après sélection de cible + jet OK, le moteur garde l’unité active mais la
          // réponse JSON peut omettre active_charge_unit — le réinjecter avant setGameState pour
          // l’UI (pastilles violettes, isActiveCharger).
          if (
            data.game_state?.phase === "charge" &&
            data.result?.action === "charge_target_selected" &&
            data.result.unitId != null
          ) {
            data.game_state = {
              ...data.game_state,
              active_charge_unit: data.result.unitId,
            };
          }

          setGameState((p) => {
            const merged = mergeGameStatePreservingOmittedObjectives(
              p,
              data.game_state as APIGameState
            );
            latestGameStateRef.current = merged;
            return merged;
          });

          // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Handle advance activation response (jet D6 + pool sous-hex)
          const advanceDests = data.result?.advance_destinations;
          const advanceRollOrRange =
            data.result?.advance_roll ?? (data.result as { advance_range?: number })?.advance_range;
          if (
            Array.isArray(advanceDests) &&
            advanceRollOrRange !== undefined &&
            advanceRollOrRange !== null
          ) {
            // Clear shooting preview when entering advancePreview mode (from either advance button click or unit activation)
            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
            setAttackPreview(null);

            setAdvanceDestinations(advanceDests);
            setPostShootMoveDestinations([]);
            setAdvanceRoll(advanceRollOrRange);
            setAdvancingUnitId(parseInt(String(data.result.unitId), 10));
            setSelectedUnitId(parseInt(String(data.result.unitId), 10));
            setMovePreview(null);
            setPendingPreviewAction(null);
            setMode("advancePreview" as GameMode);
            // Même source que la phase move : BFS remplit valid_move_destinations_pool + move_preview_footprint_zone.
            // Fallback ``result.advance_destinations`` : le moteur renvoie toujours cette liste, alors que le JSON
            // ``game_state`` peut omettre ou vider ``valid_move_destinations_pool`` selon le chemin d’exécution —
            // sans ce repli la couche cercle reste vide alors que le move (phase dédiée) lit bien le pool.
            const gsAdv = data.game_state;
            if (gsAdv) {
              const poolSet = new Set<string>();
              addHexKeysToSet(gsAdv.valid_move_destinations_pool, poolSet);
              if (poolSet.size === 0) {
                addHexKeysToSet((gsAdv as { preview_hexes?: unknown }).preview_hexes, poolSet);
              }
              if (poolSet.size === 0) {
                addHexKeysToSet(advanceDests, poolSet);
              }
              moveDestPoolRef.current = poolSet;

              const loopsAdv = normalizeMaskLoopsFromApi(
                (gsAdv as { move_preview_footprint_mask_loops?: unknown })
                  .move_preview_footprint_mask_loops
              );
              footprintMaskLoopsRef.current = loopsAdv;
              const fpSet = new Set<string>();
              if (!loopsAdv?.length) {
                addHexKeysToSet(gsAdv.move_preview_footprint_zone, fpSet);
              }
              footprintZoneRef.current = fpSet;
            }
          }
          // Handle post-shoot optional move (move_after_shooting) destination selection for human players
          else if (
            data.game_state?.phase === "shoot" &&
            data.result?.waiting_for_player === true &&
            data.result?.action === "move_after_shooting_select_destination" &&
            Array.isArray(data.result?.move_after_shooting_destinations)
          ) {
            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
            setAttackPreview(null);
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });

            const unitId = parseInt(data.result.unitId, 10);
            setPostShootMoveDestinations(data.result.move_after_shooting_destinations);
            setAdvanceDestinations([]);
            setAdvanceRoll(null);
            setAdvancingUnitId(null);
            setMovePreview(null);
            setSelectedUnitId(unitId);
            setPendingPreviewAction("move_after_shooting");
            setMode("select");
          }
          // Handle movement activation response with valid destinations
          else if (
            data.game_state?.phase === "move" &&
            data.result?.waiting_for_player === true &&
            (Array.isArray(data.result?.valid_destinations) ||
              (Array.isArray(data.game_state.valid_move_destinations_pool) &&
                data.game_state.valid_move_destinations_pool.length > 0))
          ) {
            const uid = data.result?.unitId ?? data.game_state.active_movement_unit;
            if (uid != null) {
              const uidNum = parseInt(String(uid), 10);
              setSelectedUnitId(uidNum);
              setActiveUnitEngaged(data.result?.would_flee === true ? uidNum : null);
              // Desperate Escape : reprise après hazard → auto-entrer dans le plan Fall Back
              // par-figurine (consommé par un effet, une fois manualAllocation/render à jour).
              if (data.result?.fall_back_resume === true) {
                setFallBackResumeUnitId(uidNum);
              }
              // V11 : restaure l'état Advance figé du squad (badge + bouton sélectionné) à la
              // (ré-)activation. advance_roll non-null = squad déjà advancé ce tour.
              const advRoll = (data.result as { advance_roll?: number | null })?.advance_roll;
              if (advRoll != null) {
                setAdvancingUnitId(uidNum);
                setAdvanceRoll(advRoll);
              } else {
                setAdvancingUnitId(null);
                setAdvanceRoll(null);
              }
            }
            const poolSet = new Set<string>();
            const anchorSrc =
              data.game_state.valid_move_destinations_pool ??
              data.result?.valid_destinations ??
              (data.game_state as { preview_hexes?: unknown }).preview_hexes;
            addHexKeysToSet(anchorSrc, poolSet);
            moveDestPoolRef.current = poolSet;

            const loopsAct = normalizeMaskLoopsFromApi(
              (data.game_state as { move_preview_footprint_mask_loops?: unknown })
                .move_preview_footprint_mask_loops
            );
            footprintMaskLoopsRef.current = loopsAct;
            const fpSet = new Set<string>();
            if (!loopsAct?.length) {
              addHexKeysToSet(data.game_state.move_preview_footprint_zone, fpSet);
            }
            footprintZoneRef.current = fpSet;
          }
          // Handle charge activation response - can have blinking_units without valid_destinations yet
          // After handleActivateCharge, backend returns blinking_units (targets) but not destinations yet
          // Destinations are calculated after clicking on a target (handleChargeEnemyUnit)
          else if (
            data.game_state?.phase === "charge" &&
            data.result?.waiting_for_player &&
            data.result?.blinking_units &&
            data.result?.start_blinking &&
            !data.result?.valid_destinations
          ) {
            // Charge activation: blinking_units present but no destinations yet - set mode to chargePreview
            const newUnitIds = data.result.blinking_units.map((id: string) => parseInt(id, 10));
            const needsNewTimer =
              !blinkingUnits.blinkTimer ||
              !blinkingUnits.unitIds.some((id) => newUnitIds.includes(id));

            if (needsNewTimer) {
              // Clear any existing blinking timer
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }

              // Start blinking for all valid targets
              const timer = window.setInterval(() => {
                // Empty interval - blinking is handled locally in UnitRenderer
              }, 500);

              const attackerId = data.result?.unitId ? parseInt(data.result.unitId, 10) : null;

              if (data.result?.unitId) {
                data.game_state = {
                  ...data.game_state,
                  active_charge_unit: data.result.unitId,
                };
                setSelectedUnitId(parseInt(data.result.unitId, 10));
              }

              setBlinkingUnits({ unitIds: newUnitIds, blinkTimer: timer, attackerId });
            }

            setSelectedUnitId(parseInt(data.result.unitId, 10));
            // V11 RAW : le jet 2D6 est fait à l'activation côté backend. On entre en sous-mode
            // « sélection des cibles » (pré-validation) ; le badge du jet s'affiche dès maintenant.
            setChargePreviewTargetIds([]);
            const actRoll = (data.result as { charge_roll?: number | null }).charge_roll;
            if (actRoll != null && data.result.unitId != null) {
              setPendingChargeRollDisplay({
                unitId: parseInt(String(data.result.unitId), 10),
                roll: actRoll,
              });
            }
            setMode("chargeTargetSelect");
          }
          // Charge : cible validée → jet 2D6 + zone violette (pool). Ne pas dépendre seulement de
          // waiting_for_player (sinon la branche "shoot" plus bas effaçait selectedUnitId).
          else if (
            data.game_state?.phase === "charge" &&
            data.result?.action === "charge_target_selected"
          ) {
            const chargerUid = parseInt(String(data.result.unitId), 10);
            // V11 11.04 (Slice G) : escouade chargeuse multi-fig → mouvement par-figurine (plan 3
            // phases backend). Mono-fig → flux rigide actuel (preview → clic destination), inchangé.
            const figCount = Object.keys(readSquadModelPositions(chargerUid)).length;
            if (figCount > 1) {
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }
              setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
              void handleStartChargeModelMove(chargerUid);
            } else {
              const pd = data.result.preview_data as { violet_hexes?: unknown } | undefined;
              const raw = data.result.valid_destinations ?? pd?.violet_hexes;
              if (raw == null) {
                throw new Error(
                  "charge_target_selected: valid_destinations and preview_data.violet_hexes both absent"
                );
              }
              const anchorsNorm = normalizeChargeDestinationsFromApi(raw);
              const displayRaw = (data.result as { charge_preview_display_hexes?: unknown })
                .charge_preview_display_hexes;
              const overlayNorm = normalizeChargeDestinationsFromApi(displayRaw ?? []);
              setChargeDestinations(anchorsNorm);
              setChargePreviewOverlayHexes(overlayNorm);
              syncChargePoolRefs(anchorsNorm, overlayNorm);
              // Map distance réelle par ancre (sous-hex) pour le tooltip de charge (path au sol / direct en vol).
              const distMap = new Map<string, number>();
              const distRaw = (data.result as { charge_dest_distances?: unknown })
                .charge_dest_distances;
              if (Array.isArray(distRaw)) {
                for (const e of distRaw) {
                  if (Array.isArray(e) && e.length >= 3) {
                    distMap.set(`${Number(e[0])},${Number(e[1])}`, Number(e[2]));
                  }
                }
              }
              chargeDestDistancesRef.current = distMap;
              const refH = (data.result as { charge_reference_hex?: unknown }).charge_reference_hex;
              if (Array.isArray(refH) && refH.length >= 2) {
                setChargeReferenceHex({ col: Number(refH[0]), row: Number(refH[1]) });
              } else {
                setChargeReferenceHex(null);
              }
              if (data.result.targetId != null) {
                setChargePreviewTargetId(parseInt(String(data.result.targetId), 10));
              }
              if (data.result.unitId != null && data.result.charge_roll != null) {
                setPendingChargeRollDisplay({
                  unitId: parseInt(String(data.result.unitId), 10),
                  roll: data.result.charge_roll as number,
                });
              }
              setSelectedUnitId(chargerUid);
              setMode("chargePreview");
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }
              setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
            }
          }
          // Fallback : anciennes réponses sans action === charge_target_selected
          else if (
            data.game_state?.phase === "charge" &&
            data.result?.valid_destinations &&
            data.result?.waiting_for_player === true
          ) {
            const anchorsNormFb = normalizeChargeDestinationsFromApi(
              data.result.valid_destinations
            );
            const displayRawFb = (data.result as { charge_preview_display_hexes?: unknown })
              .charge_preview_display_hexes;
            const overlayNormFb = normalizeChargeDestinationsFromApi(displayRawFb ?? []);
            setChargeDestinations(anchorsNormFb);
            setChargePreviewOverlayHexes(overlayNormFb);
            syncChargePoolRefs(anchorsNormFb, overlayNormFb);
            const refFb = (data.result as { charge_reference_hex?: unknown }).charge_reference_hex;
            if (Array.isArray(refFb) && refFb.length >= 2) {
              setChargeReferenceHex({ col: Number(refFb[0]), row: Number(refFb[1]) });
            } else {
              setChargeReferenceHex(null);
            }
            if (data.result.targetId != null) {
              setChargePreviewTargetId(parseInt(String(data.result.targetId), 10));
            }
            if (data.result.unitId != null && data.result.charge_roll != null) {
              setPendingChargeRollDisplay({
                unitId: parseInt(String(data.result.unitId), 10),
                roll: data.result.charge_roll as number,
              });
            }
            setSelectedUnitId(parseInt(String(data.result.unitId), 10));
            setMode("chargePreview");
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
          }
          // NEW RULE: Handle charge failure - show failed roll badge
          // Use EXACT same logic as successful charges: reset mode immediately, store targetId
          else if (data.result?.charge_failed && data.result?.charge_roll !== undefined) {
            if (data.result.unitId == null) {
              throw new Error("charge_failed result missing unitId");
            }
            const failedUnitId = parseInt(String(data.result.unitId), 10);
            const targetId = data.result.targetId ? parseInt(data.result.targetId, 10) : undefined;
            setPendingChargeRollDisplay(null);
            setChargePreviewTargetId(null);
            // Store failed charge info for badge display
            setFailedChargeRoll({ unitId: failedUnitId, roll: data.result.charge_roll });
            // Store target separately (EXACT same as successful charges) for target icon display
            if (targetId) {
              setSuccessfulChargeTarget({ unitId: failedUnitId, targetId });
              // Clear after a delay to show target icon (EXACT same as successful charges)
              setTimeout(() => {
                setSuccessfulChargeTarget(null);
              }, 2000);
            }
            // CRITICAL: Reset mode immediately (EXACT same as successful charges) so logo renders in stable state
            setChargeDestinations([]);
            setChargePreviewOverlayHexes([]);
            setChargeReferenceHex(null);
            clearChargePoolRefs();
            setPendingChargeRollDisplay(null);
            setSelectedUnitId(null);
            setMode("select");
            // Clear blinking from charge preview to avoid stale attacker stats
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
            // Clear failedChargeRoll after delay to show badge
            setTimeout(() => {
              setFailedChargeRoll(null); // Clear after display
            }, 2000); // Show badge for 2 seconds
          }
          // Handle charge completion - reset to select mode
          // CRITICAL FIX: When phase_complete=true, backend has already transitioned to next phase
          // So we check activation_complete AND (current phase is charge OR phase just completed)
          else if (
            data.result?.activation_complete &&
            (data.game_state?.phase === "charge" || data.result?.phase_complete)
          ) {
            // Store successful charge target for target icon display
            if (data.result?.targetId && data.result?.unitId) {
              const chargerId = parseInt(data.result.unitId, 10);
              const targetId = parseInt(data.result.targetId, 10);
              setSuccessfulChargeTarget({ unitId: chargerId, targetId });
              // Clear after a delay to show target icon
              setTimeout(() => {
                setSuccessfulChargeTarget(null);
              }, 2000);
            }
            setChargeDestinations([]);
            setChargePreviewOverlayHexes([]);
            setChargeReferenceHex(null);
            clearChargePoolRefs();
            setPendingChargeRollDisplay(null);
            setChargePreviewTargetId(null);
            setSelectedUnitId(null);
            setMode("select");
            // Clear blinking from charge preview when charge resolves
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
          }
          // Fight phase : pile-in PAR-FIGURINE (mode fin type charge). La réponse d'activate_unit
          // (et des refresh suivants) porte ``pile_in_model_move:true`` → on entre/maintient le mode
          // et on applique le plan_state. Doit précéder les branches V10 (waiting_for_pile_in) et
          // la réinitialisation paresseuse (fight_subphase pile_in sans waiting).
          else if (data.game_state?.phase === "fight" && data.result?.pile_in_model_move === true) {
            const uid = parseInt(
              String(data.result.unitId ?? data.game_state.active_fight_unit),
              10
            );
            // Purge des artefacts du pile-in rigide V10 (disques + empreinte) pour éviter un rendu fantôme.
            setPileInDestinations([]);
            moveDestPoolRef.current = new Set();
            footprintZoneRef.current = new Set();
            footprintMaskLoopsRef.current = null;
            setSelectedUnitId(uid);
            setMode("pileInModelMove");
            applyPileInPlanState(data.result as Record<string, unknown>);
          }
          // Fight phase : CONSOLIDATION PAR-FIGURINE (V11 12.08, miroir pile-in). La réponse
          // d'activate_unit / des refresh porte ``consolidation_model_move:true`` → on entre/maintient
          // le mode et on applique le plan_state (cascade ongoing/engaging/objective).
          else if (
            data.game_state?.phase === "fight" &&
            data.result?.consolidation_model_move === true
          ) {
            const uid = parseInt(
              String(data.result.unitId ?? data.game_state.active_fight_unit),
              10
            );
            setPileInDestinations([]);
            moveDestPoolRef.current = new Set();
            footprintZoneRef.current = new Set();
            footprintMaskLoopsRef.current = null;
            setConsolidationNewFoes([]);
            setSelectedUnitId(uid);
            setMode("consolidationModelMove");
            applyConsolidationPlanState(data.result as Record<string, unknown>);
          }
          // Fight phase : « New Foes to Face » (12.08 engaging AFTER) — l'adversaire doit faire
          // combattre les ennemis nouvellement engagés. Pool = consolidation_new_foes ; on réutilise
          // le flux FIGHT (sélection pool → activate_unit ; cible → résolution + allocation).
          else if (
            data.game_state?.phase === "fight" &&
            Array.isArray(data.result?.consolidation_new_foes)
          ) {
            const foes = (data.result.consolidation_new_foes as unknown[]).map((m) => String(m));
            setConsolidationNewFoes(foes);
            setConsolidationMovePlan(null);
            consolidationModelPoolRef.current = new Set();
            consolidationModelMaskLoopsRef.current = null;
            setPileInDestinations([]);
            moveDestPoolRef.current = new Set();
            footprintZoneRef.current = new Set();
            footprintMaskLoopsRef.current = null;
            const af = data.result.active_fight_unit ?? data.game_state.active_fight_unit;
            setSelectedUnitId(af != null ? parseInt(String(af), 10) : null);
            setMode("select");
          }
          // Fight phase : pile in avant sélection de cible CC
          else if (
            data.game_state?.phase === "fight" &&
            data.result?.waiting_for_pile_in &&
            data.result?.valid_pile_in_destinations
          ) {
            const raw = data.result.valid_pile_in_destinations as Array<
              [number, number] | { col: number; row: number }
            >;
            const norm = raw.map((h) =>
              Array.isArray(h)
                ? { col: Number(h[0]), row: Number(h[1]) }
                : { col: Number(h.col), row: Number(h.row) }
            );
            setPileInDestinations(norm);
            const poolSet = new Set<string>();
            for (const h of norm) {
              poolSet.add(`${h.col},${h.row}`);
            }
            moveDestPoolRef.current = poolSet;
            const gsPi = data.game_state;
            const fpZone = gsPi?.fight_pile_in_footprint_zone as unknown;
            const fpSet = new Set<string>();
            if (Array.isArray(fpZone)) {
              for (const d of fpZone) {
                if (Array.isArray(d) && d.length === 2) {
                  fpSet.add(`${d[0]},${d[1]}`);
                }
              }
            }
            footprintZoneRef.current = fpSet;
            footprintMaskLoopsRef.current = null;
            const uid = parseInt(
              String(data.result.unitId ?? data.game_state.active_fight_unit),
              10
            );
            setSelectedUnitId(uid);
            setMode("pileInPreview");
          }
          // Fight : sous-phase pile_in SANS unité active (présentation paresseuse).
          // Le moteur expose seulement le pool éligible (sélection libre) ; on nettoie
          // tout aperçu résiduel d'une unité précédente et on reste en sélection.
          else if (
            data.game_state?.phase === "fight" &&
            data.game_state?.fight_subphase === "pile_in" &&
            !data.result?.waiting_for_pile_in
          ) {
            setPileInDestinations([]);
            moveDestPoolRef.current = new Set();
            footprintZoneRef.current = new Set();
            footprintMaskLoopsRef.current = null;
            setSelectedUnitId(null);
            setMode("select");
          }
          // Fight : sous-phase consolidate SANS unité active (présentation paresseuse, miroir pile_in).
          // Pool éligible exposé par le moteur (sélection libre → activate_unit). On nettoie les
          // aperçus résiduels et on reste en sélection.
          else if (
            data.game_state?.phase === "fight" &&
            data.game_state?.fight_subphase === "consolidate" &&
            data.result?.consolidation_model_move !== true &&
            !Array.isArray(data.result?.consolidation_new_foes) &&
            !data.result?.waiting_for_consolidation
          ) {
            setConsolidationMovePlan(null);
            consolidationModelPoolRef.current = new Set();
            consolidationModelMaskLoopsRef.current = null;
            setConsolidationNewFoes([]);
            setPileInDestinations([]);
            moveDestPoolRef.current = new Set();
            footprintZoneRef.current = new Set();
            footprintMaskLoopsRef.current = null;
            setSelectedUnitId(null);
            setMode("select");
          }
          // Fight : consolidation après attaques (≤ 3") — sans destination valide = fin d'activation (comme le moteur)
          else if (data.game_state?.phase === "fight" && data.result?.waiting_for_consolidation) {
            const raw = data.result.valid_consolidation_destinations as
              | Array<[number, number] | { col: number; row: number }>
              | undefined;
            const hasDests = Array.isArray(raw) && raw.length > 0;
            if (hasDests) {
              const norm = raw.map((h) =>
                Array.isArray(h)
                  ? { col: Number(h[0]), row: Number(h[1]) }
                  : { col: Number(h.col), row: Number(h.row) }
              );
              setPileInDestinations(norm);
              const poolSet = new Set<string>();
              for (const h of norm) {
                poolSet.add(`${h.col},${h.row}`);
              }
              moveDestPoolRef.current = poolSet;
              const gsC = data.game_state;
              const fpZone = gsC?.fight_consolidation_footprint_zone as unknown;
              const fpSet = new Set<string>();
              if (Array.isArray(fpZone)) {
                for (const d of fpZone) {
                  if (Array.isArray(d) && d.length === 2) {
                    fpSet.add(`${d[0]},${d[1]}`);
                  }
                }
              }
              footprintZoneRef.current = fpSet;
              footprintMaskLoopsRef.current = null;
              const uid = parseInt(
                String(data.result.unitId ?? data.game_state.active_fight_unit),
                10
              );
              setSelectedUnitId(uid);
              setMode("consolidationPreview");
            } else {
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }
              setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
              setAttackPreview(null);
              setPileInDestinations([]);
              moveDestPoolRef.current = new Set();
              footprintZoneRef.current = new Set();
              footprintMaskLoopsRef.current = null;
              setSelectedUnitId(null);
              setMode("select");
            }
          }
          // Handle fight phase multi-attack (ATTACK_LEFT > 0, waiting_for_player)
          // ``[]`` est truthy en JS : exiger au moins une cible, sinon on retombe sur fin d'activation / filet.
          // Si le moteur annonce ``waiting_for_player`` mais ATTACK_LEFT déjà à 0, ne pas rouvrir l’UI CC.
          else if (
            (() => {
              if (data.game_state?.phase !== "fight" || !data.result?.waiting_for_player) {
                return false;
              }
              if (
                !Array.isArray(data.result.valid_targets) ||
                data.result.valid_targets.length === 0
              ) {
                return false;
              }
              const waitUid = parseInt(
                String(
                  (() => {
                    const uid = data.result.unitId ?? data.game_state.active_fight_unit;
                    if (uid == null)
                      throw new Error("fight wait: unitId and active_fight_unit both absent");
                    return uid;
                  })()
                ),
                10
              );
              if (!Number.isFinite(waitUid)) {
                return false;
              }
              const waitAttacker = data.game_state.units?.find(
                (u: { id: string | number; ATTACK_LEFT?: number }) =>
                  parseInt(String(u.id), 10) === waitUid
              );
              const wl = waitAttacker?.ATTACK_LEFT;
              if (typeof wl === "number" && wl <= 0) {
                return false;
              }
              return true;
            })()
          ) {
            setPileInDestinations([]);
            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
            // Keep the attacking unit selected and show valid targets
            const unitId = parseInt(data.result.unitId || data.game_state.active_fight_unit, 10);
            setSelectedUnitId(unitId);
            setMode("attackPreview");

            // L'EZ rouge du combat dépend du MODE "attackPreview", pas de l'OBJET attackPreview
            // (concept TIR : tireur à sa position de preview). En fight l'unité n'a pas bougé et a
            // plusieurs figurines → poser l'objet la ferait sauter du rendu principal (BoardPvp
            // continue 7204) puis redessiner en figurine unique à l'ancre. On le laisse donc null.
            setAttackPreview(null);

            // Start/update blinking for valid fight targets (keep attacker in sync)
            if (data.result.valid_targets.length > 0) {
              const unitIds = data.result.valid_targets.map((id: string) => parseInt(id, 10));
              const attackerId = unitId;
              const unitIdsChanged =
                unitIds.length !== blinkingUnits.unitIds.length ||
                !unitIds.every((id: number) => blinkingUnits.unitIds.includes(id));
              const attackerIdChanged = attackerId !== blinkingUnits.attackerId;
              let timer = blinkingUnits.blinkTimer;
              if (!timer) {
                // Note: Actual blinking animation is handled locally in UnitRenderer
                // We only track which units should blink, not the blink state itself
                timer = window.setInterval(() => {
                  // Empty interval - blinking is handled locally in UnitRenderer
                  // This timer is kept for cleanup purposes only
                }, 500);
              }
              if (unitIdsChanged || attackerIdChanged || !blinkingUnits.blinkTimer) {
                setBlinkingUnits({ unitIds, blinkTimer: timer, attackerId });
              }
            } else {
              // Empty valid_targets: clear stale blink IDs (e.g. last enemy killed) — previously skipped
              if (blinkingUnits.blinkTimer) {
                clearInterval(blinkingUnits.blinkTimer);
              }
              setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
            }
          }
          // Unité fight activée SANS cible (ex: a chargé, cible morte avant son activation) :
          // on entre quand même en attackPreview pour permettre de la PASSER (clic droit →
          // skip backend gardé). Sans ce cas, l'unité reste active sans aucun mode → cul-de-sac
          // (cercle vert persistant, impossible à traiter).
          else if (
            data.game_state?.phase === "fight" &&
            data.result?.waiting_for_player === true &&
            data.game_state?.active_fight_unit != null &&
            Array.isArray(data.result.valid_targets) &&
            data.result.valid_targets.length === 0 &&
            !data.result.activation_ended
          ) {
            setPileInDestinations([]);
            if (targetPreview?.blinkTimer) {
              clearInterval(targetPreview.blinkTimer);
            }
            setTargetPreview(null);
            setSelectedUnitId(parseInt(String(data.game_state.active_fight_unit), 10));
            setMode("attackPreview");
            setAttackPreview(null);
            if (blinkingUnits.blinkTimer) {
              clearInterval(blinkingUnits.blinkTimer);
            }
            setBlinkingUnits({ unitIds: [], blinkTimer: null, attackerId: null });
          }
          // Handle fight phase completion (ATTACK_LEFT = 0, activation_ended)
          else if (data.game_state?.phase === "fight" && data.result?.activation_ended) {
            clearFightAttackActivationUi();
          }
          // Set visual state based on shooting activation
          // AI_TURN.md COMPLIANCE: Clear stale attackPreview from previous fight phases
          // This prevents Unit 3 (fled) from rendering at old position when Unit 4 (shooter) is activated
          // Root cause: attackPreview was set during fight phase and never cleared when shooting started
          // Don't set mode to attackPreview here - wait for backend response (blinking_units or allow_advance)
          else if (data.game_state?.phase === "shoot" && data.game_state?.active_shooting_unit) {
            setSelectedUnitId(parseInt(data.game_state.active_shooting_unit, 10));
            if (!data.result?.allow_advance) {
              setAttackPreview(null); // Clear stale attackPreview to prevent ghost rendering
            }
            // Mode will be set by blinking_units handler (attackPreview) or rester en select si advance seul
          } else {
            // Ne pas effacer la sélection en phase charge (réponses partielles / clés manquantes).
            if (data.game_state?.phase !== "charge") {
              setSelectedUnitId(null);
            }
            // Fight : fin d’activation CC (active libérée ou ATTACK_LEFT à 0 dans ``game_state``), y compris si
            // ``waiting_for_player`` est resté incohérent — éviter de rester en attackPreview.
            const inactiveFight =
              data.game_state?.active_fight_unit == null ||
              data.game_state.active_fight_unit === "";
            const filetFightUid =
              selectedUnitId ??
              (data.result?.unitId != null ? parseInt(String(data.result.unitId), 10) : null);
            const filetFightUnit =
              filetFightUid != null && data.game_state?.units
                ? data.game_state.units.find(
                    (u: { id: string | number; ATTACK_LEFT?: number }) =>
                      parseInt(String(u.id), 10) === filetFightUid
                  )
                : undefined;
            const fightNoAttacksLeft =
              typeof filetFightUnit?.ATTACK_LEFT === "number" && filetFightUnit.ATTACK_LEFT <= 0;
            const snap = fightTargetUiRef.current;
            const fightPreviewUiActive = isFightAttackSelectionUiOpen(
              snap.mode,
              snap.attackPreview
            );
            if (
              data.game_state?.phase === "fight" &&
              fightPreviewUiActive &&
              (inactiveFight || fightNoAttacksLeft) &&
              !data.result?.waiting_for_pile_in &&
              !data.result?.waiting_for_consolidation
            ) {
              clearFightAttackActivationUi();
            }
          }

          // CRITICAL FIX: Propagate available_weapons independently of allow_advance condition
          // This ensures weapon icons appear after advance when unit has ASSAULT weapon and LoS
          // Must happen after setSelectedUnitId to ensure active_shooting_unit is set
          if (data.game_state?.phase === "shoot" && data.game_state?.active_shooting_unit) {
            // Propagate available_weapons from API response to unit if present
            // Update the unit in game_state before setGameState is called later
            if (
              data.result?.available_weapons &&
              Array.isArray(data.result.available_weapons) &&
              data.game_state.units
            ) {
              const activeUnitId = data.game_state.active_shooting_unit;
              const unitIndex = data.game_state.units.findIndex(
                (u: { id: string | number }) => u.id.toString() === activeUnitId.toString()
              );
              if (unitIndex >= 0) {
                data.game_state.units[unitIndex] = {
                  ...data.game_state.units[unitIndex],
                  available_weapons: data.result.available_weapons,
                };
              }
            }
          }

          // Filet : le pool d’ancres vit surtout dans game_state ; result.valid_destinations peut être absent
          // (taille JSON / évolution API) alors que valid_move_destinations_pool est présent.
          if (data.game_state?.phase === "move") {
            const raw =
              data.game_state.valid_move_destinations_pool ??
              (data.game_state as { preview_hexes?: unknown }).preview_hexes;
            if (Array.isArray(raw) && raw.length > 0) {
              const poolSet = new Set<string>();
              addHexKeysToSet(raw, poolSet);
              if (poolSet.size > 0) {
                moveDestPoolRef.current = poolSet;
              }
            }
            const loopsMv = normalizeMaskLoopsFromApi(
              (data.game_state as { move_preview_footprint_mask_loops?: unknown })
                .move_preview_footprint_mask_loops
            );
            footprintMaskLoopsRef.current = loopsMv;
            if (!loopsMv?.length) {
              const fp = data.game_state.move_preview_footprint_zone;
              if (Array.isArray(fp) && fp.length > 0) {
                const fpSet = new Set<string>();
                addHexKeysToSet(fp, fpSet);
                if (fpSet.size > 0) {
                  footprintZoneRef.current = fpSet;
                }
              }
            } else {
              footprintZoneRef.current = new Set();
            }
          }
        }
        return data as {
          success?: boolean;
          error?: unknown;
          result?: Record<string, unknown>;
          game_state?: APIGameState;
        };
      } catch (err) {
        if (isFightCombatClientTrace) {
          logFightClick("executeAction: exception réseau / parse", {
            message: formatApiConnectionError(err),
          });
        }
        console.error("Action error:", err);
        setError(formatApiConnectionError(err));
        return undefined;
      }
    },
    [
      gameState,
      selectedUnitId,
      advanceWarningPopup,
      blinkingUnits.blinkTimer,
      blinkingUnits.unitIds,
      blinkingUnits.attackerId,
      targetPreview?.blinkTimer,
      clearFightAttackActivationUi,
      clearChargePoolRefs,
      syncChargePoolRefs,
      blinkingUnits.coverByUnitId,
    ]
  );

  // Convert API units to frontend format
  const convertUnits = useCallback((apiUnits: APIGameState["units"]): Unit[] => {
    return apiUnits.map((unit) => {
      // NEVER create defaults - raise errors for missing data
      // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate weapons arrays exist
      if (!unit.RNG_WEAPONS || !Array.isArray(unit.RNG_WEAPONS)) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required RNG_WEAPONS array`);
      }
      if (!unit.CC_WEAPONS || !Array.isArray(unit.CC_WEAPONS)) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required CC_WEAPONS array`);
      }
      if (unit.ICON_SCALE === undefined || unit.ICON_SCALE === null) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required ICON_SCALE field`);
      }
      if (
        typeof unit.ILLUSTRATION_RATIO !== "number" ||
        !Number.isFinite(unit.ILLUSTRATION_RATIO) ||
        unit.ILLUSTRATION_RATIO < 0
      ) {
        throw new Error(`API ERROR: Unit ${unit.id} missing non-negative ILLUSTRATION_RATIO field`);
      }
      if (unit.SHOOT_LEFT === undefined || unit.SHOOT_LEFT === null) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required SHOOT_LEFT field`);
      }
      if (unit.ATTACK_LEFT === undefined || unit.ATTACK_LEFT === null) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required ATTACK_LEFT field`);
      }
      if (!unit.UNIT_RULES || !Array.isArray(unit.UNIT_RULES)) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required UNIT_RULES array`);
      }
      if (!unit.UNIT_KEYWORDS || !Array.isArray(unit.UNIT_KEYWORDS)) {
        throw new Error(`API ERROR: Unit ${unit.id} missing required UNIT_KEYWORDS array`);
      }
      for (const rule of unit.UNIT_RULES) {
        if (!rule || typeof rule !== "object") {
          throw new Error(`API ERROR: Unit ${unit.id} has invalid UNIT_RULES entry`);
        }
        if (!("ruleId" in rule) || !("displayName" in rule)) {
          throw new Error(
            `API ERROR: Unit ${unit.id} has UNIT_RULES entry missing ruleId/displayName`
          );
        }
        if (
          "grants_rule_ids" in rule &&
          rule.grants_rule_ids !== undefined &&
          !Array.isArray(rule.grants_rule_ids)
        ) {
          throw new Error(`API ERROR: Unit ${unit.id} has invalid grants_rule_ids in UNIT_RULES`);
        }
        if ("usage" in rule && rule.usage !== undefined) {
          if (!["and", "or", "unique", "always"].includes(String(rule.usage))) {
            throw new Error(`API ERROR: Unit ${unit.id} has invalid usage in UNIT_RULES`);
          }
        }
        if ("choice_timing" in rule && rule.choice_timing !== undefined) {
          const timing = rule.choice_timing;
          if (!timing || typeof timing !== "object") {
            throw new Error(`API ERROR: Unit ${unit.id} has invalid choice_timing in UNIT_RULES`);
          }
          const trigger = (timing as { trigger?: unknown }).trigger;
          if (
            typeof trigger !== "string" ||
            ![
              "on_deploy",
              "turn_start",
              "player_turn_start",
              "phase_start",
              "activation_start",
            ].includes(trigger)
          ) {
            throw new Error(
              `API ERROR: Unit ${unit.id} has invalid choice_timing.trigger in UNIT_RULES`
            );
          }
          const phase = (timing as { phase?: unknown }).phase;
          if (
            phase !== undefined &&
            (typeof phase !== "string" ||
              !["command", "move", "shoot", "charge", "fight"].includes(phase))
          ) {
            throw new Error(
              `API ERROR: Unit ${unit.id} has invalid choice_timing.phase in UNIT_RULES`
            );
          }
          const activePlayerScope = (timing as { active_player_scope?: unknown })
            .active_player_scope;
          if (
            activePlayerScope !== undefined &&
            (typeof activePlayerScope !== "string" ||
              !["owner", "opponent", "both"].includes(activePlayerScope))
          ) {
            throw new Error(
              `API ERROR: Unit ${unit.id} has invalid choice_timing.active_player_scope in UNIT_RULES`
            );
          }
          if (trigger === "phase_start" && activePlayerScope === undefined) {
            throw new Error(
              `API ERROR: Unit ${unit.id} choice_timing.active_player_scope is required for trigger '${trigger}'`
            );
          }
          if (["phase_start", "activation_start"].includes(trigger) && phase === undefined) {
            throw new Error(
              `API ERROR: Unit ${unit.id} choice_timing.phase is required for trigger '${trigger}'`
            );
          }
        }
      }
      for (const keyword of unit.UNIT_KEYWORDS) {
        if (!keyword || typeof keyword !== "object" || typeof keyword.keywordId !== "string") {
          throw new Error(`API ERROR: Unit ${unit.id} has invalid UNIT_KEYWORDS entry`);
        }
      }

      const displayName =
        typeof unit.DISPLAY_NAME === "string" && unit.DISPLAY_NAME.trim().length > 0
          ? unit.DISPLAY_NAME
          : unit.unitType;

      const rawUnit = unit as Record<string, unknown>;
      const readIntField = (keys: string[]): number | undefined => {
        for (const k of keys) {
          const v = rawUnit[k];
          if (v === undefined || v === null) continue;
          if (typeof v === "number" && Number.isFinite(v)) {
            return Math.trunc(v);
          }
          if (typeof v === "string" && v.trim() !== "") {
            const n = parseInt(v, 10);
            if (!Number.isNaN(n)) return n;
          }
        }
        return undefined;
      };
      const manualWeaponSelected =
        unit.manualWeaponSelected === true ||
        rawUnit._manual_weapon_selected === true ||
        rawUnit.manual_weapon_selected === true;

      const selectedRngWeaponIndex =
        readIntField(["selectedRngWeaponIndex", "selected_rng_weapon_index"]) ??
        unit.selectedRngWeaponIndex;
      const selectedCcWeaponIndex =
        readIntField(["selectedCcWeaponIndex", "selected_cc_weapon_index"]) ??
        unit.selectedCcWeaponIndex;
      const orientation =
        unit.orientation === undefined
          ? undefined
          : validateOrientationStepValue(unit.orientation, `API unit ${unit.id}`);

      return {
        id: typeof unit.id === "number" ? unit.id : parseInt(unit.id, 10),
        name: displayName,
        DISPLAY_NAME: displayName,
        type: unit.unitType,
        player: unit.player as PlayerId,
        col: unit.col,
        row: unit.row,
        color: unit.player === 1 ? 0x244488 : 0x882222,
        MOVE: unit.MOVE,
        HP_MAX: unit.HP_MAX,
        HP_CUR: unit.HP_CUR,
        T: unit.T,
        ARMOR_SAVE: unit.ARMOR_SAVE,
        INVUL_SAVE: unit.INVUL_SAVE,
        LD: unit.LD,
        OC: unit.OC,
        VALUE: unit.VALUE,
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Map weapons arrays
        RNG_WEAPONS: unit.RNG_WEAPONS,
        CC_WEAPONS: unit.CC_WEAPONS,
        selectedRngWeaponIndex,
        selectedCcWeaponIndex,
        manualWeaponSelected,
        ICON: unit.ICON,
        ICON_SCALE: unit.ICON_SCALE,
        ILLUSTRATION_RATIO: unit.ILLUSTRATION_RATIO,
        BASE_SIZE: unit.BASE_SIZE,
        BASE_SHAPE: unit.BASE_SHAPE,
        orientation,
        SHOOT_LEFT: unit.SHOOT_LEFT,
        ATTACK_LEFT: unit.ATTACK_LEFT,
        valid_target_pool: unit.valid_target_pool,
        los_preview_attack_cells: unit.los_preview_attack_cells,
        los_preview_cover_cells: unit.los_preview_cover_cells,
        los_preview_ratio_by_hex: unit.los_preview_ratio_by_hex,
        currentShootNb: unit._current_shoot_nb,
        currentFightNb: unit._current_fight_nb,
        available_weapons: unit.available_weapons,
        UNIT_RULES: unit.UNIT_RULES,
        UNIT_KEYWORDS: unit.UNIT_KEYWORDS,
        battle_shocked: unit.battle_shocked === true ? true : undefined,
        hideable: unit.hideable,
        hidden: unit.hidden,
        hidden_models: unit.hidden_models,
      };
    });
  }, []);

  const fetchEndlessDutyStatus = useCallback(async (): Promise<EndlessDutyState | null> => {
    const response = await fetch(`${API_BASE}/game/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "endless_duty_status" }),
    });
    if (!response.ok) {
      throw new Error(`Endless Duty status failed: ${response.status}`);
    }
    const data = await response.json();
    if (!data.success) {
      throw new Error(String(data.error || "Failed to fetch Endless Duty status"));
    }
    if (data.game_state) {
      setGameState((p) =>
        mergeGameStatePreservingOmittedObjectives(p, data.game_state as APIGameState)
      );
    }
    const nextState = (data.endless_duty_state as EndlessDutyState | undefined) ?? null;
    setEndlessDutyState(nextState);
    return nextState;
  }, []);

  const commitEndlessDuty = useCallback(
    async (
      slotProfiles: { leader: string | null; melee: string | null; range: string | null },
      slotPicks: {
        leader: Record<string, string | null> | null;
        melee: Record<string, string | null> | null;
        range: Record<string, string | null> | null;
      }
    ) => {
      const response = await fetch(`${API_BASE}/game/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "endless_duty_commit",
          slot_profiles: slotProfiles,
          slot_picks: slotPicks,
        }),
      });
      if (!response.ok) {
        throw new Error(`Endless Duty commit failed: ${response.status}`);
      }
      const data = await response.json();
      if (!data.success) {
        throw new Error(String(data.error || "Failed to commit Endless Duty requisition"));
      }
      if (data.game_state) {
        setGameState((p) =>
          mergeGameStatePreservingOmittedObjectives(p, data.game_state as APIGameState)
        );
      }
      setEndlessDutyState((data.endless_duty_state as EndlessDutyState | undefined) ?? null);
    },
    []
  );

  // Backend-driven shooting phase management
  const handleShootingPhaseClick = useCallback(
    async (unitId: number, clickType: "left" | "right") => {
      if (!gameState) return;
      await executeAction(
        buildActivationPointerPayload("shoot", unitId, clickType, gameState, selectedUnitId)
      );
    },
    [gameState, selectedUnitId, executeAction]
  );

  const processQueuedFightTargetClicks = useCallback(async () => {
    if (fightClickQueueProcessingRef.current) {
      return;
    }
    fightClickQueueProcessingRef.current = true;
    try {
      while (queuedFightTargetClicksRef.current.length > 0) {
        const gsNow = (latestGameStateRef.current ??
          gameState) as ActivationPointerGameState | null;
        if (!gsNow || gsNow.phase !== "fight") {
          queuedFightTargetClicksRef.current = [];
          break;
        }
        const activeFightStr = getActiveFightUnitIdString(
          latestGameStateRef.current as ActivationPointerGameState | null,
          gsNow
        );
        if (!activeFightStr) {
          queuedFightTargetClicksRef.current = [];
          clearFightAttackActivationUi();
          break;
        }
        const aid = parseInt(activeFightStr, 10);
        const al = getFightAttackerAttackLeft(gsNow, aid);
        if (typeof al === "number" && al <= 0) {
          queuedFightTargetClicksRef.current = [];
          clearFightAttackActivationUi();
          break;
        }
        const targetId = queuedFightTargetClicksRef.current.shift();
        if (targetId == null) {
          break;
        }
        const gsForPayload = {
          ...gsNow,
          active_fight_unit: activeFightStr,
        } as ActivationPointerGameState;
        const response = (await enqueueFightRequest(() =>
          executeAction(
            buildActivationPointerPayload("fight", targetId, "left", gsForPayload, selectedUnitId)
          )
        )) as
          | {
              success?: boolean;
              result?: Record<string, unknown>;
              game_state?: APIGameState;
            }
          | undefined;

        const gsAfter = (response?.game_state ?? latestGameStateRef.current) as
          | APIGameState
          | null
          | undefined;
        if (!gsAfter || gsAfter.phase !== "fight" || !gsAfter.active_fight_unit) {
          queuedFightTargetClicksRef.current = [];
          break;
        }
        const result = response?.result as Record<string, unknown> | undefined;
        if (result?.waiting_for_player !== true) {
          queuedFightTargetClicksRef.current = [];
          break;
        }

        const attackResult = result?.attack_result as Record<string, unknown> | undefined;
        const targetDied =
          (attackResult?.target_died === true || result?.target_died === true) &&
          String(attackResult?.targetId ?? result?.targetId ?? "") === String(targetId);
        if (targetDied) {
          const activeAfter = parseInt(String(gsAfter.active_fight_unit), 10);
          const alAfter = getFightAttackerAttackLeft(
            gsAfter as unknown as ActivationPointerGameState,
            activeAfter
          );
          const validTargets =
            Array.isArray(result?.valid_targets) && result?.valid_targets.length > 0
              ? result.valid_targets.map((x) => String(x))
              : [];
          const hasOtherTarget = validTargets.some((x) => x !== String(targetId));
          if (typeof alAfter === "number" && alAfter > 0 && hasOtherTarget) {
            // Cible morte + autres cibles possibles: rendre la main au joueur.
            queuedFightTargetClicksRef.current = [];
            break;
          }
        }
      }
    } finally {
      fightClickQueueProcessingRef.current = false;
    }
  }, [gameState, selectedUnitId, enqueueFightRequest, executeAction, clearFightAttackActivationUi]);

  /** Clics plateau en phase fight : même contrat API que le tir (``left_click`` / ``right_click``). */
  const handleFightPhaseClick = useCallback(
    async (unitId: number, clickType: "left" | "right") => {
      if (!gameState || gameState.phase !== "fight") return;
      if (clickType === "left") {
        const gsNow = (latestGameStateRef.current ?? gameState) as ActivationPointerGameState;
        const activeFightStr = getActiveFightUnitIdString(
          latestGameStateRef.current as ActivationPointerGameState | null,
          gsNow
        );
        if (!activeFightStr) {
          clearFightAttackActivationUi();
          return;
        }
        const aid = parseInt(activeFightStr, 10);
        const al = getFightAttackerAttackLeft(gsNow, aid);
        if (typeof al === "number") {
          const inFlightEstimate = fightClickQueueProcessingRef.current ? 1 : 0;
          const maxQueued = Math.max(0, al - inFlightEstimate);
          if (queuedFightTargetClicksRef.current.length >= maxQueued) {
            logFightClick(
              "handleFightPhaseClick: left_click ignoré (file pleine vs attaques restantes)",
              {
                unitId,
                attackLeft: al,
                queuedCount: queuedFightTargetClicksRef.current.length,
                inFlightEstimate,
              }
            );
            return;
          }
        }
        queuedFightTargetClicksRef.current.push(unitId);
        logFightClick("handleFightPhaseClick: left_click en file", {
          unitId,
          queuedCount: queuedFightTargetClicksRef.current.length,
        });
        await processQueuedFightTargetClicks();
        return;
      }
      queuedFightTargetClicksRef.current = [];
      await enqueueFightRequest(async () => {
        const gsNow = (latestGameStateRef.current ?? gameState) as ActivationPointerGameState;
        if (gsNow.phase !== "fight") {
          return;
        }
        const activeFightStr = getActiveFightUnitIdString(
          latestGameStateRef.current as ActivationPointerGameState | null,
          gsNow
        );
        if (!activeFightStr) {
          clearFightAttackActivationUi();
          return;
        }
        const gsForPayload = {
          ...gsNow,
          active_fight_unit: activeFightStr,
        } as ActivationPointerGameState;
        await executeAction(
          buildActivationPointerPayload("fight", unitId, clickType, gsForPayload, selectedUnitId)
        );
      });
    },
    [
      gameState,
      selectedUnitId,
      executeAction,
      enqueueFightRequest,
      clearFightAttackActivationUi,
      processQueuedFightTargetClicks,
    ]
  );

  // Event handlers aligned with backend
  const handleSelectUnit = useCallback(
    async (unitId: number | string | null) => {
      // Allocation manuelle des pertes en cours (Desperate Escape) : aucun changement de
      // sélection/activation tant que les mortal wounds ne sont pas attribuées.
      if (manualAllocationRef.current && unitId !== null) return;
      const numericUnitId = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;

      // Block unit selection when in advancePreview, chargeTargetSelect or chargePreview mode
      // (but allow deselection with null)
      if (
        (mode === "advancePreview" || mode === "chargeTargetSelect" || mode === "chargePreview") &&
        numericUnitId !== null
      ) {
        return;
      }
      // En mode plan par-figurine, bloquer les clics PIXI (onSelectUnit) pour éviter que
      // handleSelectUnit remette mode="select" (l'unité n'est plus dans moveActivationPool
      // après activate_unit). La sélection est gérée par onPointerDownSelect (positions provisoires).
      if (mode === "squadModelMove" && numericUnitId !== null) {
        return;
      }
      // En mode tir par-figurine, bloquer les clics sur d'autres unités pour éviter
      // un friendly_unit_switch involontaire vers une autre escouade.
      if (mode === "squadModelShoot" && numericUnitId !== null) {
        return;
      }

      // Shooting phase: all activations go through squad path (onStartSquadModelShoot).
      if (gameState && gameState.phase === "shoot") {
        return;
      }

      // Fight phase : aligné sur le tir (sélection pool → activate_unit ; prévisualisation → left_click)
      if (gameState && gameState.phase === "fight") {
        if (
          numericUnitId === null &&
          isFightAttackSelectionUiOpen(
            fightTargetUiRef.current.mode,
            fightTargetUiRef.current.attackPreview
          ) &&
          selectedUnitId !== null
        ) {
          await enqueueFightRequest(async () => {
            const gsNow = (latestGameStateRef.current ?? gameState) as ActivationPointerGameState;
            const activeFightId = getActiveFightUnitIdString(
              latestGameStateRef.current as ActivationPointerGameState | null,
              gsNow
            );
            if (!activeFightId) {
              return;
            }
            await executeAction({
              action: "right_click",
              unitId: activeFightId.toString(),
              targetId: selectedUnitId != null ? String(selectedUnitId) : activeFightId.toString(),
              clickTarget: "active_unit",
            });
          });
          setSelectedUnitId(null);
          setMode("select");
          return;
        }
        if (numericUnitId !== null) {
          const gsFight = (latestGameStateRef.current ?? gameState) as ActivationPointerGameState;
          const fightPool = getFightActivationPoolUnitIds(gsFight);
          if (fightPool.includes(numericUnitId)) {
            if (activationInProgressRef.current) {
              return;
            }
            activationInProgressRef.current = true;
            setSelectedUnitId(numericUnitId);
            setActivationPendingUnitId(numericUnitId);
            try {
              await executeAction({
                action: "activate_unit",
                unitId: numericUnitId.toString(),
              });
              // Flux manuel par arme/figurine : initialise le plan local UNIQUEMENT en étape FIGHT.
              // En pile_in / consolidate (move par-figurine), ne PAS poser squadFightPlan — sinon le
              // handler capture fight intercepterait les clics de pose. Figs lues depuis le cache.
              const gsModels = (latestGameStateRef.current ?? gameState) as {
                fight_subphase?: string | null;
                units_cache?: Record<string, { occupied_hexes_by_model?: Record<string, unknown> }>;
              };
              if (gsModels.fight_subphase === "fight") {
                const fightModels = Object.keys(
                  gsModels.units_cache?.[String(numericUnitId)]?.occupied_hexes_by_model ?? {}
                );
                setSquadFightPlan({
                  unitId: numericUnitId,
                  models: fightModels,
                  targets: {},
                  declarations: [],
                  activeModelId: null,
                  activeWeaponIndex: null,
                  canValidate: false,
                });
              }
            } finally {
              activationInProgressRef.current = false;
              setActivationPendingUnitId(null);
            }
            return;
          }
          const gsPtr = (latestGameStateRef.current ?? gameState) as ActivationPointerGameState;
          const activeFightStr = getActiveFightUnitIdString(
            latestGameStateRef.current as ActivationPointerGameState | null,
            gameState as ActivationPointerGameState
          );
          if (activeFightStr) {
            // Flux manuel par arme/figurine : les clics sur figurines/ennemis sont
            // interceptés par le handler capture de BoardPvp (sélection fig + attribution).
            // Ici, si un plan est actif, on ignore le flux de résolution immédiate legacy.
            if (squadFightPlanRef.current) {
              return;
            }
            const aid = parseInt(activeFightStr, 10);
            const al = getFightAttackerAttackLeft(gsPtr, aid);
            if (typeof al === "number" && al <= 0) {
              clearFightAttackActivationUi();
              return;
            }
            await handleFightPhaseClick(numericUnitId, "left");
            return;
          }
          if (
            isFightAttackSelectionUiOpen(
              fightTargetUiRef.current.mode,
              fightTargetUiRef.current.attackPreview
            )
          ) {
            clearFightAttackActivationUi();
            return;
          }
        }
        return;
      }

      // Movement phase click handling
      if (gameState && gameState.phase === "move" && numericUnitId !== null) {
        if (!gameState.move_activation_pool) {
          console.error("❌ MOVEMENT SELECT ERROR: Missing move_activation_pool");
          throw new Error(`API ERROR: Missing required move_activation_pool during movement phase`);
        }
        const moveActivationPool = gameState.move_activation_pool.map((id) => parseInt(id, 10));

        if (moveActivationPool.includes(numericUnitId)) {
          if (activationInProgressRef.current) {
            return;
          }
          activationInProgressRef.current = true;
          setSelectedUnitId(numericUnitId);
          setActivationPendingUnitId(numericUnitId);
          try {
            await executeAction({
              action: "activate_unit",
              unitId: numericUnitId.toString(),
            });
          } finally {
            activationInProgressRef.current = false;
            setActivationPendingUnitId(null);
          }
          return;
        }
      }

      // Normal unit selection for other phases
      // If deselecting in chargePreview mode, send postpone action to backend
      if (numericUnitId === null && mode === "chargePreview" && selectedUnitId !== null) {
        await executeAction({
          action: "left_click",
          unitId: selectedUnitId.toString(),
          clickTarget: "active_unit",
        });
        setChargeDestinations([]);
        setChargePreviewOverlayHexes([]);
        setChargeReferenceHex(null);
        clearChargePoolRefs();
        setPendingChargeRollDisplay(null);
        setChargePreviewTargetId(null);
      } else if (numericUnitId === null && mode === "advancePreview") {
        setAdvanceDestinations([]);
        setPostShootMoveDestinations([]);
        setAdvancingUnitId(null);
        setAdvanceRoll(null);
      }
      setSelectedUnitId(numericUnitId);
      setMode("select");
      setMovePreview(null);
      setTargetPreview(null);
      // Remove all frontend shooting state - backend manages everything
    },
    [
      gameState,
      executeAction,
      mode,
      selectedUnitId,
      clearChargePoolRefs,
      clearFightAttackActivationUi,
      enqueueFightRequest,
      handleFightPhaseClick,
    ]
  );

  // Right-click : tir ou CC (report / annulation côté moteur)
  const handleRightClick = useCallback(
    async (unitId: number) => {
      if (gameState?.phase === "shoot") {
        await handleShootingPhaseClick(unitId, "right");
      } else if (gameState?.phase === "fight") {
        await handleFightPhaseClick(unitId, "right");
      }
    },
    [gameState, handleShootingPhaseClick, handleFightPhaseClick]
  );

  const handleSkipUnit = useCallback(
    async (unitId: number | string) => {
      const uid = typeof unitId === "string" ? unitId : unitId.toString();
      const gsPhase = gameState?.phase;
      const isMoveLikePhase = gsPhase === "move" || gsPhase === "command";
      const activeMu = gameState?.active_movement_unit;
      if (isMoveLikePhase && activeMu != null && activeMu !== "") {
        if (String(activeMu) !== String(uid)) {
          console.error("handleSkipUnit: refuse skip — une autre unité a le mouvement en cours", {
            active_movement_unit: activeMu,
            requestedUnitId: uid,
          });
          return;
        }
        try {
          await executeAction({
            action: "right_click",
            unitId: uid,
          });
          setSelectedUnitId(null);
          setMode("select");
          setMovePreview(null);
          setPendingPreviewAction(null);
        } catch (error) {
          console.error("Postpone movement (right_click) failed:", error);
          setError(`Postpone movement failed: ${formatApiConnectionError(error)}`);
        }
        return;
      }

      const action = {
        action: "skip",
        unitId: uid,
      };

      try {
        await executeAction(action);
        setSelectedUnitId(null);
        setMode("select");
      } catch (error) {
        console.error("Skip unit failed:", error);
        setError(`Skip unit failed: ${formatApiConnectionError(error)}`);
      }
    },
    [executeAction, gameState?.phase, gameState?.active_movement_unit]
  );

  const handleEndPhase = useCallback(
    async (player: number) => {
      if (!gameState) {
        throw new Error("Cannot end phase: gameState is not available");
      }
      if (gameState.current_player !== player) {
        throw new Error(
          `Cannot end phase for player ${player}: current player is ${gameState.current_player}`
        );
      }
      if (
        gameState.phase !== "move" &&
        gameState.phase !== "shoot" &&
        gameState.phase !== "charge" &&
        gameState.phase !== "fight"
      ) {
        throw new Error(
          `end_phase is only supported in move/shoot/charge/fight phases, got '${gameState.phase}'`
        );
      }

      await executeAction({
        action: "end_phase",
        player: player,
      });
    },
    [executeAction, gameState]
  );

  const validateOrientationStep = useCallback(
    (rawOrientation: unknown, context: string): number => {
      return validateOrientationStepValue(rawOrientation, context);
    },
    []
  );

  const readEngineOrientationStepFromGameState = useCallback(
    (unitId: number | string): number | undefined => {
      const unitKey = String(unitId);
      const cacheOrientation = gameState?.units_cache?.[unitKey]?.orientation;
      if (cacheOrientation !== undefined) {
        return validateOrientationStep(cacheOrientation, `Unit ${unitKey} units_cache`);
      }
      const unitOrientation = gameState?.units.find(
        (unit) => String(unit.id) === unitKey
      )?.orientation;
      if (unitOrientation !== undefined) {
        return validateOrientationStep(unitOrientation, `Unit ${unitKey}`);
      }
      return undefined;
    },
    [gameState?.units, gameState?.units_cache, validateOrientationStep]
  );

  /**
   * Active l'unité si besoin et indique s'il faut SUSPENDRE l'entrée dans le move preview/plan
   * parce qu'un Desperate Escape (hazard) doit être résolu d'abord. Retourne false = ne pas
   * entrer (le popup ☢️ est affiché ; après résolution le backend renvoie le pool de move).
   */
  const ensureActivatedNoHazard = useCallback(
    async (unitId: number | string): Promise<boolean> => {
      const sid = String(typeof unitId === "string" ? parseInt(unitId, 10) : unitId);
      if (String(latestGameStateRef.current?.active_movement_unit) !== sid) {
        await executeAction({ action: "activate_unit", unitId: sid });
      }
      return hazardWarningPopupRef.current === null;
    },
    [executeAction]
  );

  const handleStartMovePreview = useCallback(
    async (unitId: number | string, col: number | string, row: number | string) => {
      // Desperate Escape : allocation des mortal wounds en cours → ne pas entrer en preview.
      if (manualAllocationRef.current) return;
      // Double-clic depuis squadModelMove : nettoyer le plan provisoire avant d'entrer en movePreview.
      squadMoveSessionRef.current += 1;
      squadMoveModelPoolRef.current = new Set();
      // NE PAS nuller le plan ici : à cause de l'``await activate_unit`` plus bas, un setSquadMovePlan(null)
      // précoce est commité dans un render AVANT setMode → frame où mode=squadModelMove mais plan=null →
      // l'escouade saute à sa position d'origine = clignotement. On nulle juste avant chaque setMode
      // ("movePreview"), batché avec, pour un switch atomique sans frame intermédiaire.
      const parsedUnitId = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      const orientation = readEngineOrientationStepFromGameState(unitId);
      if (gameState?.phase === "shoot") {
        if (pendingPreviewAction !== "move_after_shooting") {
          return;
        }
        setMovePreview({
          unitId: parsedUnitId,
          destCol: typeof col === "string" ? parseInt(col, 10) : col,
          destRow: typeof row === "string" ? parseInt(row, 10) : row,
          orientation,
        });
        setSquadMovePlan(null);
        setMode("movePreview");
        return;
      }
      // Phase move : activer l'unité (calcule valid_move_destinations_pool). Si l'unité est
      // engagée ET battle-shocked, l'activation déclenche le popup Desperate Escape → on
      // SUSPEND l'entrée en preview (le hazard doit être résolu avant de bouger).
      if (gameState?.phase === "move") {
        setSelectedUnitId(parsedUnitId);
        const ok = await ensureActivatedNoHazard(parsedUnitId);
        if (!ok) return;
      }
      const latestOrientation = readEngineOrientationStepFromGameState(unitId);
      setMovePreview({
        unitId: parsedUnitId,
        destCol: typeof col === "string" ? parseInt(col, 10) : col,
        destRow: typeof row === "string" ? parseInt(row, 10) : row,
        orientation: latestOrientation,
      });
      setSquadMovePlan(null);
      setPendingPreviewAction("move");
      setMode("movePreview");
    },
    [
      gameState?.phase,
      pendingPreviewAction,
      readEngineOrientationStepFromGameState,
      ensureActivatedNoHazard,
    ]
  );

  const handleBumpMovePreviewOrientation = useCallback(
    (delta: number) => {
      if (!Number.isInteger(delta)) {
        throw new Error(`Move preview orientation delta must be an integer, got ${String(delta)}`);
      }
      setMovePreview((current) => {
        if (!current) {
          return current;
        }
        if (current.orientation === undefined) {
          throw new Error(`Move preview for unit ${current.unitId} is missing orientation`);
        }
        const currentOrientation = validateOrientationStep(
          current.orientation,
          `Move preview unit ${current.unitId}`
        );
        return {
          ...current,
          orientation: (currentOrientation + delta + 6) % 6,
        };
      });
    },
    [validateOrientationStep]
  );

  /**
   * Requete read-only vers le moteur (pool BFS fig / dry-run plan provisoire).
   * Ne passe PAS par executeAction : la reponse n'a pas de game_state et ne doit
   * pas declencher le traitement d'etat principal. Retourne ``data.result``.
   */
  const postEngineQuery = useCallback(
    async (action: Record<string, unknown>): Promise<Record<string, unknown> | null> => {
      const response = await fetch(`${API_BASE}/game/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action),
      });
      if (!response.ok) {
        console.warn("[SQUAD-MOVE] query HTTP error", action.action, response.status);
        throw new Error(`Engine query failed: ${response.status}`);
      }
      const data = await response.json();
      if (data?.success === false) {
        console.warn("[SQUAD-MOVE] query backend error", action.action, data?.error);
        throw new Error(typeof data?.error === "string" ? data.error : "engine query failed");
      }
      return (data?.result ?? null) as Record<string, unknown> | null;
    },
    []
  );

  /** Positions par-figurine actuelles d'une escouade (depuis units_cache.occupied_hexes_by_model). */
  const readSquadModelPositions = useCallback(
    (unitId: number | string): Record<string, { col: number; row: number }> => {
      const entry = (
        gameState?.units_cache as
          | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
          | undefined
      )?.[String(unitId)];
      const byModel = entry?.occupied_hexes_by_model;
      const out: Record<string, { col: number; row: number }> = {};
      if (byModel) {
        for (const [mid, pos] of Object.entries(byModel)) {
          out[mid] = { col: pos[0], row: pos[1] };
        }
      }
      return out;
    },
    [gameState?.units_cache]
  );

  /** Dry-run du plan provisoire → maj voile rouge / cohesion / can_validate. */
  const refreshSquadMovePlanValidity = useCallback(
    async (unitId: number, models: Record<string, { col: number; row: number }>) => {
      const plan = Object.entries(models).map(([mid, p]) => [mid, p.col, p.row]);
      let result: Record<string, unknown> | null = null;
      try {
        result = await postEngineQuery({
          action: "preview_move_plan",
          unitId: String(unitId),
          plan,
        });
      } catch (err) {
        console.error(`[SQUAD-MOVE] validity ERROR unit=${unitId}`, err, { plan });
        return;
      }
      const perModelValid = (result?.per_model ?? {}) as Record<string, boolean>;
      const coherencyOk = result?.coherency_ok === true;
      const canValidate = result?.can_validate === true;
      const wouldFlee = result?.would_flee === true;
      // État stable découplé : posé dès que le backend détecte l'engagement, jamais
      // remis à null ici (le clear est fait à la sortie du mode move) → pas de clignotement.
      if (wouldFlee) setFleePreviewUnitId(unitId);
      setActiveUnitEngaged(wouldFlee ? unitId : null);
      setSquadMovePlan((prev) =>
        prev && prev.unitId === unitId
          ? { ...prev, perModelValid, coherencyOk, canValidate, wouldFlee }
          : prev
      );
    },
    [postEngineQuery]
  );

  /** Double-clic escouade / simple-clic fig : entre en mode plan provisoire par-figurine. */
  const handleStartSquadModelMove = useCallback(
    async (unitId: number | string) => {
      // Desperate Escape : allocation des mortal wounds en cours → ne pas entrer dans le plan.
      if (manualAllocationRef.current) return;
      const uid = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      // Desperate Escape : activer d'abord ; si hazard requis, ne PAS entrer dans le plan
      // par-figurine (le popup ☢️ doit être résolu avant tout déplacement).
      if (!(await ensureActivatedNoHazard(uid))) return;
      const models = readSquadModelPositions(uid);
      if (Object.keys(models).length === 0) {
        console.warn(
          `[SQUAD-MOVE] startSquadModelMove ABORT unit=${uid} (aucune fig dans occupied_hexes_by_model)`
        );
        return;
      }
      squadMoveSessionRef.current += 1;
      squadMoveModelPoolRef.current = new Set();
      setSquadMovePlan((prev) => ({
        unitId: uid,
        models,
        originModels: { ...models },
        activeModelId: null,
        perModelValid: {},
        coherencyOk: true,
        canValidate: false,
        // Préserver wouldFlee sur ré-init de la même unité (sinon clignotement → badge effacé).
        wouldFlee: prev?.unitId === uid ? prev.wouldFlee : false,
      }));
      setMode("squadModelMove");
      setSelectedUnitId(uid);
      await refreshSquadMovePlanValidity(uid, models);
    },
    [readSquadModelPositions, refreshSquadMovePlanValidity, ensureActivatedNoHazard]
  );

  // Desperate Escape : après résolution du hazard (resume), auto-entrer dans le plan Fall Back
  // par-figurine. Exécuté APRÈS le render qui a clearé manualAllocation (sinon le top-guard de
  // handleStartSquadModelMove bail). L'unité est déjà active (active_movement_unit posé par le
  // resume) → ensureActivatedNoHazard skippe l'activation → aucun re-déclenchement du hazard.
  useEffect(() => {
    if (fallBackResumeUnitId === null) return;
    if (manualAllocation !== null) return; // attendre le clear de l'allocation (re-run via dep)
    const uid = fallBackResumeUnitId;
    setFallBackResumeUnitId(null);
    void handleStartSquadModelMove(uid);
  }, [fallBackResumeUnitId, manualAllocation, handleStartSquadModelMove]);

  /** Selectionne la figurine a repositionner : recupere sa BFS (move_model_destinations). */
  const handleSelectModelForMove = useCallback(
    async (modelId: string) => {
      const sessionAtCall = squadMoveSessionRef.current;
      const currentPlan = squadMovePlanRef.current;
      const provisionalPlan: Record<string, [number, number]> = {};
      if (currentPlan) {
        for (const [mid, pos] of Object.entries(currentPlan.models)) {
          if (mid !== modelId) {
            provisionalPlan[mid] = [pos.col, pos.row];
          }
        }
      }
      const result = await postEngineQuery({
        action: "move_model_destinations",
        model_id: modelId,
        provisional_plan: provisionalPlan,
      });
      if (squadMoveSessionRef.current !== sessionAtCall) return;
      if (!result?.destinations) {
        throw new Error("move_model_destinations: destinations absent in response");
      }
      const dests = result.destinations as Array<[number, number]>;
      const set = new Set<string>();
      for (const [c, r] of dests) {
        set.add(`${c},${r}`);
      }
      squadMoveModelPoolRef.current = set;
      const rawLoops = result?.footprint_mask_loops;
      squadMoveModelMaskLoopsRef.current = Array.isArray(rawLoops)
        ? (rawLoops as number[][])
        : null;
      setSquadMovePlan((prev) => (prev ? { ...prev, activeModelId: modelId } : prev));
    },
    [postEngineQuery]
  );

  /** Pose la figurine active a (col,row) dans le plan provisoire + refresh validite. */
  const handleMoveModelInPlan = useCallback(
    (modelId: string, col: number, row: number) => {
      // Fig posee → on la deselectionne (vide le pool + loops, sort du preview de cette fig).
      squadMoveModelPoolRef.current = new Set();
      squadMoveModelMaskLoopsRef.current = null;
      setSquadMovePlan((prev) => {
        if (!prev) return prev;
        const models = { ...prev.models, [modelId]: { col, row } };
        void refreshSquadMovePlanValidity(prev.unitId, models);
        return { ...prev, models, activeModelId: null };
      });
    },
    [refreshSquadMovePlanValidity]
  );

  /** Clic droit sur la fig active : annule SON deplacement → retour position de debut de phase. */
  const handleResetModelInPlan = useCallback(
    (modelId: string) => {
      setSquadMovePlan((prev) => {
        if (!prev) return prev;
        const origin = prev.originModels[modelId];
        if (!origin) return prev;
        const models = { ...prev.models, [modelId]: { ...origin } };
        void refreshSquadMovePlanValidity(prev.unitId, models);
        return { ...prev, models };
      });
    },
    [refreshSquadMovePlanValidity]
  );

  const handleDirectMove = useCallback(
    async (
      unitId: number | string,
      col: number | string,
      row: number | string,
      orientation?: number
    ) => {
      const action: {
        action: "move";
        unitId: string;
        destCol: number;
        destRow: number;
        orientation?: number;
      } = {
        action: "move",
        unitId: typeof unitId === "string" ? unitId : unitId.toString(),
        destCol: typeof col === "string" ? parseInt(col, 10) : col,
        destRow: typeof row === "string" ? parseInt(row, 10) : row,
      };
      if (orientation !== undefined) {
        action.orientation = validateOrientationStep(
          orientation,
          `Move action unit ${action.unitId}`
        );
      }

      try {
        await executeAction(action);
        setMovePreview(null);
        setPendingPreviewAction(null);
        setSelectedUnitId(null);
        setMode("select");
      } catch (error) {
        console.error("❌ DIRECT MOVE FAILED:", error);
        console.error("Move failed:", error);
        setError(`Move failed: ${formatApiConnectionError(error)}`);
      }
    },
    [executeAction, validateOrientationStep]
  );

  /** Bouton Validate : commit atomique du plan complet (commit_move_plan). */
  const handleCommitSquadMovePlan = useCallback(async () => {
    if (!squadMovePlan) {
      console.warn("[SQUAD-MOVE] commit ABORT (pas de plan)");
      return;
    }
    if (!squadMovePlan.canValidate) {
      console.warn("[SQUAD-MOVE] commit ABORT (canValidate=false, il reste du rouge)");
      return;
    }
    const plan = Object.entries(squadMovePlan.models).map(([mid, p]) => [mid, p.col, p.row]);
    try {
      await executeAction({
        action: "commit_move_plan",
        unitId: String(squadMovePlan.unitId),
        plan,
      });
      squadMoveModelPoolRef.current = new Set();
      setSquadMovePlan(null);
      setMode("select");
      setSelectedUnitId(null);
      setAdvancingUnitId(null);
      setAdvanceRoll(null);
      setActiveUnitEngaged(null);
    } catch (e) {
      console.error("[SQUAD-MOVE] commit FAILED", e);
      setError(`Squad move failed: ${formatApiConnectionError(e)}`);
    }
  }, [squadMovePlan, executeAction]);

  /** Annule le plan provisoire (aucune ecriture backend). */
  const handleCancelSquadMove = useCallback(async () => {
    squadMoveSessionRef.current += 1;
    squadMoveModelPoolRef.current = new Set();
    // Désactiver l'unité côté moteur (postpone : clear active_movement_unit sans la retirer du
    // pool d'activation). Sinon le bloc de boutons reste affiché car gaté par active_movement_unit.
    const activeMu = latestGameStateRef.current?.active_movement_unit;
    if (activeMu != null && activeMu !== "") {
      await executeAction({
        action: "left_click",
        unitId: String(activeMu),
        clickTarget: "active_unit",
      });
    }
    setSquadMovePlan(null);
    setMode("select");
    setSelectedUnitId(null);
    setAdvancingUnitId(null);
    setAdvanceRoll(null);
    setActiveUnitEngaged(null);
  }, [executeAction]);

  /** Bouton Advance (phase move) : bascule l'activation squad en mode Advance (jet D6 backend). */
  const handleSetAdvanceMode = useCallback(
    async (unitId: number | string) => {
      const uid = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      const data = await executeAction({ action: "advance", unitId: String(uid) });
      const roll = (data as { result?: { advance_roll?: number } })?.result?.advance_roll;
      if (roll === undefined || roll === null) {
        throw new Error(`[ADVANCE] réponse sans advance_roll pour unit=${uid}`);
      }
      setAdvanceRoll(roll);
      setAdvancingUnitId(uid);
      // Plan par-figurine actif : re-valide au nouveau budget (M+jet). En preview rigide,
      // le pool d'ancre gonflé est re-synchronisé depuis game_state (phase move).
      const plan = squadMovePlanRef.current;
      if (plan && plan.unitId === uid) {
        await refreshSquadMovePlanValidity(uid, plan.models);
        // Fig active déjà sélectionnée : reconstruire SON pool atteignable au budget gonflé
        // (M+jet). Sinon la zone reste à M tant qu'on ne re-sélectionne pas la figurine.
        if (plan.activeModelId) {
          await handleSelectModelForMove(plan.activeModelId);
        }
      }
    },
    [executeAction, refreshSquadMovePlanValidity, handleSelectModelForMove]
  );

  // handleTakeToSkies est défini plus bas (après refreshChargePlanState dont il dépend en phase charge).

  /** Bouton Stationary (phase move) : termine l'activation sans bouger (log WAIT backend). */
  const handleStationary = useCallback(
    async (unitId: number | string) => {
      const uid = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      squadMoveSessionRef.current += 1;
      squadMoveModelPoolRef.current = new Set();
      setSquadMovePlan(null);
      setMode("select");
      setSelectedUnitId(null);
      setAdvancingUnitId(null);
      setAdvanceRoll(null);
      setActiveUnitEngaged(null);
      await executeAction({ action: "wait", unitId: String(uid) });
    },
    [executeAction]
  );

  /** TEST/DEBUG : force un battle-shock roll (01.07) sur l'unité — pour tester le Desperate Escape. */
  const handleForceBattleShock = useCallback(
    async (unitId: number | string) => {
      const uid = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      await executeAction({ action: "force_battle_shock", unitId: String(uid) });
    },
    [executeAction]
  );

  /** TEST/DEBUG : toggle du mode « battle-shock test » (cliquer une unité la shocke). */
  const handleToggleBattleShockTestMode = useCallback(() => {
    setBattleShockTestMode((v) => !v);
  }, []);

  /** TEST/DEBUG : force le statut « a chargé » sur l'unité — pour tester l'ordre Fights First. */
  const handleForceCharged = useCallback(
    async (unitId: number | string) => {
      const uid = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      await executeAction({ action: "force_charged", unitId: String(uid) });
    },
    [executeAction]
  );

  /** TEST/DEBUG : toggle du mode « a chargé test » (clic droit sur une unité la marque chargée). */
  const handleToggleChargedTestMode = useCallback(() => {
    setChargedTestMode((v) => !v);
  }, []);

  // ──────────────────────────────────────────────────────────────────────────
  // TIR PAR FIGURINE (PvP manuel) — calque squadModelMove, pipeline squad backend
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Coeur de la sélection d une fig : query cibles valides → HP blink + activeModelId.
   * Prend ``unitId`` explicitement (pas via ref) pour être utilisable juste après
   * setSquadShootPlan (ref pas encore rafraîchie par un re-render).
   */
  const selectShootModelForUnit = useCallback(
    async (unitId: number, modelId: string) => {
      const sessionAtCall = squadShootSessionRef.current;
      let result: Record<string, unknown> | null = null;
      try {
        result = await postEngineQuery({
          action: "squad_shoot_select_model",
          unitId: String(unitId),
          modelId,
        });
      } catch (e) {
        console.error(`[SQUAD-SHOOT] select model=${modelId} ERROR`, e);
        return;
      }
      if (squadShootSessionRef.current !== sessionAtCall) return;
      if (!result?.valid_targets) {
        throw new Error("squad_shoot select_model: valid_targets absent in response");
      }
      const rawCover = result.cover_by_unit_id;
      if (!rawCover || typeof rawCover !== "object" || Array.isArray(rawCover)) {
        throw new Error("squad_shoot select_model: cover_by_unit_id absent/invalid in response");
      }
      const coverByUnitId: Record<string, boolean> = {};
      for (const [tid, inCover] of Object.entries(rawCover as Record<string, unknown>)) {
        if (typeof inCover !== "boolean") {
          throw new Error(`squad_shoot select_model: cover_by_unit_id.${tid} must be boolean`);
        }
        coverByUnitId[tid] = inCover;
      }
      const rawTooFar = result.hidden_too_far_by_unit_id;
      if (!rawTooFar || typeof rawTooFar !== "object" || Array.isArray(rawTooFar)) {
        throw new Error(
          "squad_shoot select_model: hidden_too_far_by_unit_id absent/invalid in response"
        );
      }
      const hiddenTooFarByUnitId: Record<string, boolean> = {};
      for (const [tid, tooFar] of Object.entries(rawTooFar as Record<string, unknown>)) {
        if (typeof tooFar !== "boolean") {
          throw new Error(
            `squad_shoot select_model: hidden_too_far_by_unit_id.${tid} must be boolean`
          );
        }
        hiddenTooFarByUnitId[tid] = tooFar;
      }
      const validTargets = (result.valid_targets as string[]).map((id) => parseInt(id, 10));
      setBlinkingUnits((prev) => {
        if (prev.blinkTimer) clearInterval(prev.blinkTimer);
        const timer = validTargets.length ? window.setInterval(() => {}, 500) : null;
        return {
          unitIds: validTargets,
          blinkTimer: timer,
          attackerId: unitId,
          coverByUnitId,
          hiddenTooFarByUnitId,
        };
      });
      setSquadShootPlan((prev) =>
        prev && prev.unitId === unitId ? { ...prev, activeModelId: modelId } : prev
      );
      console.log(`[SQUAD-SHOOT] select model=${modelId} validTargets=[${validTargets.join(",")}]`);
    },
    [postEngineQuery]
  );

  /**
   * Vue escouade (double-clic sur une fig) : cibles tirables de TOUTE l escouade
   * (union) + nombre N de figs qui peuvent viser chaque ennemi (compteur N/M).
   * Read-only backend. Alimente le blink (union) et le compteur N/M frontend.
   */
  const handleSquadShootLosOverview = useCallback(
    async (unitId: number) => {
      const sessionAtCall = squadShootSessionRef.current;
      let result: Record<string, unknown> | null = null;
      try {
        result = await postEngineQuery({
          action: "squad_shoot_los_overview",
          unitId: String(unitId),
        });
      } catch (e) {
        console.error(`[SQUAD-SHOOT] los_overview unit=${unitId} ERROR`, e);
        return;
      }
      if (squadShootSessionRef.current !== sessionAtCall) return;
      if (!result?.valid_targets) {
        throw new Error("squad_shoot_los_overview: valid_targets absent in response");
      }
      const rawCover = result.cover_by_unit_id;
      if (!rawCover || typeof rawCover !== "object" || Array.isArray(rawCover)) {
        throw new Error("squad_shoot_los_overview: cover_by_unit_id absent/invalid in response");
      }
      const coverByUnitId: Record<string, boolean> = {};
      for (const [tid, inCover] of Object.entries(rawCover as Record<string, unknown>)) {
        if (typeof inCover !== "boolean") {
          throw new Error(`squad_shoot_los_overview: cover_by_unit_id.${tid} must be boolean`);
        }
        coverByUnitId[tid] = inCover;
      }
      const rawTooFar = result.hidden_too_far_by_unit_id;
      if (!rawTooFar || typeof rawTooFar !== "object" || Array.isArray(rawTooFar)) {
        throw new Error(
          "squad_shoot_los_overview: hidden_too_far_by_unit_id absent/invalid in response"
        );
      }
      const hiddenTooFarByUnitId: Record<string, boolean> = {};
      for (const [tid, tooFar] of Object.entries(rawTooFar as Record<string, unknown>)) {
        if (typeof tooFar !== "boolean") {
          throw new Error(
            `squad_shoot_los_overview: hidden_too_far_by_unit_id.${tid} must be boolean`
          );
        }
        hiddenTooFarByUnitId[tid] = tooFar;
      }
      const rawCount = result.count_by_unit_id;
      if (!rawCount || typeof rawCount !== "object" || Array.isArray(rawCount)) {
        throw new Error("squad_shoot_los_overview: count_by_unit_id absent/invalid in response");
      }
      const losCountByUnitId: Record<string, number> = {};
      for (const [tid, n] of Object.entries(rawCount as Record<string, unknown>)) {
        if (typeof n !== "number") {
          throw new Error(`squad_shoot_los_overview: count_by_unit_id.${tid} must be number`);
        }
        losCountByUnitId[tid] = n;
      }
      const aliveRaw = result.squad_alive_count;
      if (typeof aliveRaw !== "number") {
        throw new Error("squad_shoot_los_overview: squad_alive_count absent/invalid in response");
      }
      const validTargets = (result.valid_targets as string[]).map((id) => parseInt(id, 10));
      setBlinkingUnits((prev) => {
        if (prev.blinkTimer) clearInterval(prev.blinkTimer);
        const timer = validTargets.length ? window.setInterval(() => {}, 500) : null;
        return {
          unitIds: validTargets,
          blinkTimer: timer,
          attackerId: unitId,
          coverByUnitId,
          hiddenTooFarByUnitId,
          losCountByUnitId,
          squadAliveCount: aliveRaw,
          losOverviewUnitId: unitId,
        };
      });
      console.log(
        `[SQUAD-SHOOT] los_overview unit=${unitId} targets=[${validTargets.join(",")}] alive=${aliveRaw}`
      );
    },
    [postEngineQuery]
  );

  /** Entre en mode tir par-figurine : active l escouade + sélectionne la fig cliquée. */
  const handleStartSquadModelShoot = useCallback(
    async (unitId: number | string, initialModelId?: string) => {
      if (squadShootActivatingRef.current) return;
      squadShootActivatingRef.current = true;
      const uid = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      const models = Object.keys(readSquadModelPositions(uid));
      if (models.length === 0) {
        // No silent fallback: every eligible unit must expose its models (occupied_hexes_by_model).
        // If this ever fires, it is a state-sync bug to surface loudly, not to swallow.
        squadShootActivatingRef.current = false;
        setError(
          `Squad shoot: aucune figurine pour l'unité ${uid} (occupied_hexes_by_model manquant dans units_cache)`
        );
        return;
      }
      try {
        await executeAction({ action: "squad_shoot_activate", unitId: String(uid) });
      } catch (e) {
        console.error("[SQUAD-SHOOT] activate FAILED", e);
        setError(`Squad shoot activate failed: ${formatApiConnectionError(e)}`);
        squadShootActivatingRef.current = false;
        return;
      }
      squadShootSessionRef.current += 1;
      setSquadShootPlan({
        unitId: uid,
        models,
        targets: {},
        declarations: [],
        activeModelId: initialModelId ?? null,
        activeWeaponIndex: null,
        canValidate: false,
      });
      setMode("squadModelShoot");
      setSelectedUnitId(uid);
      console.log(`[SQUAD-SHOOT] start unit=${uid} models=${models.length}`);
      if (initialModelId) {
        await selectShootModelForUnit(uid, initialModelId);
      }
      squadShootActivatingRef.current = false;
    },
    [readSquadModelPositions, executeAction, selectShootModelForUnit]
  );

  /** Sélectionne une fig (clic en mode actif) : délègue au coeur via l unité du plan. */
  const handleSelectModelForShoot = useCallback(
    async (modelId: string) => {
      const plan = squadShootPlanRef.current;
      if (!plan) return;
      await selectShootModelForUnit(plan.unitId, modelId);
    },
    [selectShootModelForUnit]
  );

  /** Clic sur une unité ennemie valide : la fig active tire l'arme active sur la cible (per-fig). */
  const handleAssignShootTarget = useCallback(
    async (targetUnitId: number | string) => {
      const plan = squadShootPlanRef.current;
      if (!plan?.activeModelId) return;
      const modelId = plan.activeModelId;
      let result: Awaited<ReturnType<typeof executeAction>>;
      try {
        result = await executeAction({
          action: "squad_shoot_assign",
          unitId: String(plan.unitId),
          modelId,
          targetId: String(targetUnitId),
        });
      } catch (e) {
        console.error(`[SQUAD-SHOOT] assign model=${modelId} target=${targetUnitId} FAILED`, e);
        setError(`Cible refusée: ${formatApiConnectionError(e)}`);
        return;
      }
      if (!result || result.success === false) {
        console.log(`[SQUAD-SHOOT] assign model=${modelId} rejeté par backend`);
        return;
      }
      const decls = (result.result?.declarations ?? []) as Array<{
        model_id: string;
        weapon_index: number;
        target_unit_id: string;
      }>;
      // Fig assignée → vide le blink et déselectionne.
      setBlinkingUnits((prev) => {
        if (prev.blinkTimer) clearInterval(prev.blinkTimer);
        return { unitIds: [], blinkTimer: null, attackerId: null };
      });
      const isMono = plan.models.length === 1;
      setSquadShootPlan((prev) =>
        prev
          ? {
              ...prev,
              declarations: decls,
              targets: deriveShootTargets(decls),
              // Mono-fig : on garde la fig active (split fire arme A→X puis arme B→Y sans re-clic fig).
              // Multi-fig : on déselectionne (l'utilisateur re-sélectionne explicitement une fig).
              activeModelId: isMono ? prev.activeModelId : null,
              canValidate: decls.length > 0,
            }
          : prev
      );
      // Mono-fig : re-query les cibles valides pour que le prochain simple-clic fonctionne sans re-clic fig.
      if (isMono) {
        await selectShootModelForUnit(plan.unitId, modelId);
      }
      console.log(
        `[SQUAD-SHOOT] assign model=${modelId} → target=${targetUnitId} (${decls.length} intents)`
      );
    },
    [executeAction, selectShootModelForUnit]
  );

  /** Double-clic sur une unité ennemie : toutes les figs ayant l'arme active + LoS tirent dessus
   *  (squad_shoot_assign_weapon — assignation par arme au niveau escouade). */
  const handleAutoAssignAllModels = useCallback(
    async (targetUnitId: number | string) => {
      const plan = squadShootPlanRef.current;
      if (!plan) return;
      const weaponIndex = plan.activeWeaponIndex ?? 0;
      console.log(`[SQUAD-SHOOT][weapon] START target=${targetUnitId} weapon=${weaponIndex}`);
      let result: Awaited<ReturnType<typeof executeAction>>;
      try {
        result = await executeAction({
          action: "squad_shoot_assign_weapon",
          unitId: String(plan.unitId),
          weaponIndex,
          targetId: String(targetUnitId),
        });
      } catch (e) {
        console.error(
          `[SQUAD-SHOOT][weapon] assign weapon=${weaponIndex} target=${targetUnitId} FAILED`,
          e
        );
        setError(`Cible refusée: ${formatApiConnectionError(e)}`);
        return;
      }
      if (!result || result.success === false) {
        console.log(`[SQUAD-SHOOT][weapon] weapon=${weaponIndex} rejeté par backend`);
        return;
      }
      const decls = (result.result?.declarations ?? []) as Array<{
        model_id: string;
        weapon_index: number;
        target_unit_id: string;
      }>;
      setBlinkingUnits((prev) => {
        if (prev.blinkTimer) clearInterval(prev.blinkTimer);
        return { unitIds: [], blinkTimer: null, attackerId: null };
      });
      setSquadShootPlan((prev) =>
        prev
          ? {
              ...prev,
              declarations: decls,
              targets: deriveShootTargets(decls),
              activeModelId: null,
              canValidate: decls.length > 0,
            }
          : prev
      );
      console.log(
        `[SQUAD-SHOOT][weapon] terminé weapon=${weaponIndex} → ${targetUnitId} (${decls.length} intents)`
      );
    },
    [executeAction]
  );

  /** Clic droit sur une fig assignée : retire toutes ses armes (squad_shoot_unassign). */
  const handleUnassignShootModel = useCallback(
    async (modelId: string) => {
      const plan = squadShootPlanRef.current;
      if (!plan) return;
      let result: Awaited<ReturnType<typeof executeAction>>;
      try {
        result = await executeAction({
          action: "squad_shoot_unassign",
          unitId: String(plan.unitId),
          modelId,
        });
      } catch (e) {
        console.error(`[SQUAD-SHOOT] unassign model=${modelId} FAILED`, e);
        return;
      }
      if (!result || result.success === false) return;
      const decls = (result.result?.declarations ?? []) as Array<{
        model_id: string;
        weapon_index: number;
        target_unit_id: string;
      }>;
      setSquadShootPlan((prev) =>
        prev
          ? {
              ...prev,
              declarations: decls,
              targets: deriveShootTargets(decls),
              canValidate: decls.length > 0,
            }
          : prev
      );
      console.log(`[SQUAD-SHOOT] unassign model=${modelId} (${decls.length} intents restants)`);
    },
    [executeAction]
  );

  /** Remplacement combi : retire la déclaration d'une arme donnée (squad_shoot_unassign_weapon). */
  const handleUnassignShootWeapon = useCallback(
    async (weaponIndex: number) => {
      const plan = squadShootPlanRef.current;
      if (!plan) return;
      let result: Awaited<ReturnType<typeof executeAction>>;
      try {
        result = await executeAction({
          action: "squad_shoot_unassign_weapon",
          unitId: String(plan.unitId),
          weaponIndex,
        });
      } catch (e) {
        console.error(`[SQUAD-SHOOT] unassign weapon=${weaponIndex} FAILED`, e);
        return;
      }
      if (!result || result.success === false) return;
      const decls = (result.result?.declarations ?? []) as Array<{
        model_id: string;
        weapon_index: number;
        target_unit_id: string;
      }>;
      setSquadShootPlan((prev) =>
        prev
          ? {
              ...prev,
              declarations: decls,
              targets: deriveShootTargets(decls),
              canValidate: decls.length > 0,
            }
          : prev
      );
      console.log(
        `[SQUAD-SHOOT] unassign weapon=${weaponIndex} (${decls.length} intents restants)`
      );
    },
    [executeAction]
  );

  /** Bouton Valider : lock + résolution simultanée (squad_shoot_validate). */
  const handleCommitSquadShoot = useCallback(async () => {
    const plan = squadShootPlanRef.current;
    if (!plan) return;
    if (!plan.canValidate) {
      console.warn("[SQUAD-SHOOT] commit ABORT (aucune cible assignée)");
      return;
    }
    try {
      await executeAction({ action: "squad_shoot_validate", unitId: String(plan.unitId) });
    } catch (e) {
      console.error("[SQUAD-SHOOT] validate FAILED", e);
      setError(`Squad shoot failed: ${formatApiConnectionError(e)}`);
      return;
    }
    squadShootSessionRef.current += 1;
    setBlinkingUnits((prev) => {
      if (prev.blinkTimer) clearInterval(prev.blinkTimer);
      return { unitIds: [], blinkTimer: null, attackerId: null };
    });
    setSquadShootPlan(null);
    setMode("select");
    setSelectedUnitId(null);
    console.log(`[SQUAD-SHOOT] commit unit=${plan.unitId}`);
  }, [executeAction]);

  /** Annule le tir : nettoie l état backend (pending + active), garde l unité dans le pool. */
  const handleCancelSquadShoot = useCallback(async () => {
    const plan = squadShootPlanRef.current;
    squadShootSessionRef.current += 1;
    if (plan) {
      try {
        await executeAction({ action: "squad_shoot_cancel", unitId: String(plan.unitId) });
      } catch (e) {
        console.error("[SQUAD-SHOOT] cancel FAILED", e);
      }
    }
    setBlinkingUnits((prev) => {
      if (prev.blinkTimer) clearInterval(prev.blinkTimer);
      return { unitIds: [], blinkTimer: null, attackerId: null };
    });
    setSquadShootPlan(null);
    setMode("select");
    setSelectedUnitId(null);
    console.log("[SQUAD-SHOOT] cancel");
  }, [executeAction]);

  // ──────────────────────────────────────────────────────────────────────────
  // COMBAT par-figurine (PvP manuel) — attribution par arme/figurine (calque tir).
  // ──────────────────────────────────────────────────────────────────────────

  /** Sélectionne une fig de l'unité active : son prochain clic ennemi l'assignera. */
  const handleSelectModelForFight = useCallback((modelId: string) => {
    setSquadFightPlan((prev) => (prev ? { ...prev, activeModelId: modelId } : prev));
  }, []);

  /** Clic sur une unité ennemie engagée : la fig active l'attaque (squad_fight_assign, per-fig). */
  const handleAssignFightTarget = useCallback(
    async (targetUnitId: number | string) => {
      const plan = squadFightPlanRef.current;
      if (!plan?.activeModelId) return;
      const modelId = plan.activeModelId;
      let result: Awaited<ReturnType<typeof executeAction>>;
      try {
        const payload: Record<string, unknown> = {
          action: "squad_fight_assign",
          unitId: String(plan.unitId),
          modelId,
          targetId: String(targetUnitId),
        };
        if (plan.activeWeaponIndex != null) payload.weaponIndex = plan.activeWeaponIndex;
        result = await executeAction(payload);
      } catch (e) {
        console.error(`[SQUAD-FIGHT] assign model=${modelId} target=${targetUnitId} FAILED`, e);
        setError(`Cible refusée: ${formatApiConnectionError(e)}`);
        return;
      }
      if (!result || result.success === false) return;
      const decls = (result.result?.declarations ?? []) as Array<{
        model_id: string;
        weapon_index: number;
        target_unit_id: string;
      }>;
      const isMono = plan.models.length === 1;
      setSquadFightPlan((prev) =>
        prev
          ? {
              ...prev,
              declarations: decls,
              targets: deriveShootTargets(decls),
              activeModelId: isMono ? prev.activeModelId : null,
              canValidate: decls.length > 0,
            }
          : prev
      );
      console.log(
        `[SQUAD-FIGHT] assign model=${modelId} → ${targetUnitId} (${decls.length} intents)`
      );
    },
    [executeAction]
  );

  /** Double-clic sur une unité ennemie : toutes les figs portant l'arme active l'attaquent
   *  (squad_fight_assign_weapon — attribution par arme au niveau escouade). */
  const handleAssignFightWeapon = useCallback(
    async (targetUnitId: number | string) => {
      const plan = squadFightPlanRef.current;
      if (!plan) return;
      const weaponIndex = plan.activeWeaponIndex ?? 0;
      let result: Awaited<ReturnType<typeof executeAction>>;
      try {
        result = await executeAction({
          action: "squad_fight_assign_weapon",
          unitId: String(plan.unitId),
          weaponIndex,
          targetId: String(targetUnitId),
        });
      } catch (e) {
        console.error(
          `[SQUAD-FIGHT] assign weapon=${weaponIndex} target=${targetUnitId} FAILED`,
          e
        );
        setError(`Cible refusée: ${formatApiConnectionError(e)}`);
        return;
      }
      if (!result || result.success === false) return;
      const decls = (result.result?.declarations ?? []) as Array<{
        model_id: string;
        weapon_index: number;
        target_unit_id: string;
      }>;
      setSquadFightPlan((prev) =>
        prev
          ? {
              ...prev,
              declarations: decls,
              targets: deriveShootTargets(decls),
              activeModelId: null,
              canValidate: decls.length > 0,
            }
          : prev
      );
      console.log(
        `[SQUAD-FIGHT] assign weapon=${weaponIndex} → ${targetUnitId} (${decls.length} intents)`
      );
    },
    [executeAction]
  );

  /** Bouton Valider : résout les attaques déclarées (squad_fight_validate → allocation des pertes). */
  const handleCommitSquadFight = useCallback(async () => {
    const plan = squadFightPlanRef.current;
    if (!plan || !plan.canValidate) return;
    try {
      await executeAction({ action: "squad_fight_validate", unitId: String(plan.unitId) });
    } catch (e) {
      console.error("[SQUAD-FIGHT] validate FAILED", e);
      setError(`Combat échoué: ${formatApiConnectionError(e)}`);
      return;
    }
    setSquadFightPlan(null);
    console.log(`[SQUAD-FIGHT] commit unit=${plan.unitId}`);
  }, [executeAction]);

  /** Annule l'attribution en cours (plan local). Les déclarations pending backend seront
   *  écrasées à la prochaine activation/assignation (declare_attack_* remplace par arme/fig). */
  const handleCancelSquadFight = useCallback(async () => {
    setSquadFightPlan(null);
    console.log("[SQUAD-FIGHT] cancel");
  }, []);

  /** Allocation manuelle des pertes : le défenseur a cliqué la figurine qui encaisse. */
  const handleAllocateModel = useCallback(
    async (modelId: string) => {
      const alloc = manualAllocationRef.current;
      if (!alloc) return;
      try {
        if (alloc.kind === "hazard") {
          // Desperate Escape (06.02) : clic figurine pour attribuer une mortal wound du hazard.
          await executeAction({
            action: "squad_hazard_allocate_model",
            unitId: String(alloc.target_unit_id),
            modelId: String(modelId),
          });
          return;
        }
        if (alloc.kind === "fight") {
          // Combat (05.04) : clic figurine pour allouer une perte de mêlée.
          await executeAction({
            action: "squad_fight_manual_alloc",
            unitId: String(alloc.attacker_unit_id),
            modelId: String(modelId),
          });
          return;
        }
        await executeAction({
          action: "squad_shoot_allocate_model",
          unitId: String(alloc.attacker_unit_id),
          modelId: String(modelId),
        });
      } catch (e) {
        console.error("[MANUAL-ALLOC] allocate FAILED", e);
        setError(`Allocation failed: ${formatApiConnectionError(e)}`);
      }
    },
    [executeAction]
  );

  /** Desperate Escape : le joueur confirme le popup hazard → roule le hazard avant de bouger. */
  const handleConfirmHazardWarning = useCallback(async () => {
    const popup = hazardWarningPopup;
    if (!popup) return;
    setHazardWarningPopup(null);
    hazardWarningPopupRef.current = null;
    try {
      await executeAction({ action: "hazard_confirm", unitId: String(popup.unitId) });
    } catch (e) {
      console.error("[HAZARD] confirm FAILED", e);
      setError(`Hazard confirm failed: ${formatApiConnectionError(e)}`);
    }
  }, [hazardWarningPopup, executeAction]);

  /** Desperate Escape : le joueur annule → l'unité reste sélectionnée mais non déplacée. */
  const handleCancelHazardWarning = useCallback(() => {
    setHazardWarningPopup(null);
    hazardWarningPopupRef.current = null;
    setMode("select");
  }, []);

  /** Allocation manuelle : le défenseur a déclaré l'ordre des groupes (cible hétérogène). */
  const handleDeclareOrder = useCallback(
    async (order: number[]) => {
      const req = manualOrderRequestRef.current;
      if (!req) return;
      try {
        await executeAction({
          action: req.kind === "fight" ? "squad_fight_declare_order" : "squad_shoot_declare_order",
          unitId: String(req.attacker_unit_id),
          order,
        });
      } catch (e) {
        console.error("[MANUAL-ALLOC] declare_order FAILED", e);
        setError(`Declare order failed: ${formatApiConnectionError(e)}`);
      }
    },
    [executeAction]
  );

  const shouldShowRetreatAlert = useCallback((): boolean => {
    return readRequiredBooleanSetting(RETREAT_ALERT_STORAGE_KEY, true);
  }, []);

  const isFleeMovePreview = useCallback(
    (unitId: number, destCol: number, destRow: number): boolean => {
      if (!gameState || gameState.phase !== "move") {
        return false;
      }
      const movingUnit = gameState.units.find((unit) => parseInt(String(unit.id), 10) === unitId);
      if (!movingUnit) {
        throw new Error(`Cannot evaluate flee preview: unit ${unitId} not found`);
      }
      const enemyUnits = gameState.units.filter(
        (unit) => unit.player !== movingUnit.player && unit.HP_CUR > 0
      );
      const wasAdjacentToEnemy = enemyUnits.some(
        (enemy) =>
          cubeDistance(
            offsetToCube(movingUnit.col, movingUnit.row),
            offsetToCube(enemy.col, enemy.row)
          ) === 1
      );
      if (!wasAdjacentToEnemy) {
        return false;
      }
      const willBeAdjacentToEnemy = enemyUnits.some(
        (enemy) =>
          cubeDistance(offsetToCube(destCol, destRow), offsetToCube(enemy.col, enemy.row)) === 1
      );
      return !willBeAdjacentToEnemy;
    },
    [gameState]
  );

  const handleDeployUnit = useCallback(
    async (unitId: number | string, col: number | string, row: number | string) => {
      if (!gameState || gameState.phase !== "deployment") {
        return;
      }
      const action = {
        action: "deploy_unit",
        unitId: typeof unitId === "string" ? unitId : unitId.toString(),
        destCol: typeof col === "string" ? parseInt(col, 10) : col,
        destRow: typeof row === "string" ? parseInt(row, 10) : row,
      };
      try {
        await executeAction(action);
        setSelectedUnitId(null);
        setMode("select");
      } catch (error) {
        console.error("❌ DEPLOY FAILED:", error);
        setError(`Deploy failed: ${formatApiConnectionError(error)}`);
      }
    },
    [executeAction, gameState]
  );

  const listArmies = useCallback(async (): Promise<ArmyListItem[]> => {
    const response = await fetch(`${API_BASE}/armies`);
    if (!response.ok) {
      throw new Error(`Failed to load armies: HTTP ${response.status}`);
    }
    const data = await response.json();
    if (!data?.success) {
      throw new Error(`Failed to load armies: ${String(data?.error || "unknown error")}`);
    }
    if (!Array.isArray(data.armies)) {
      throw new Error("Invalid /api/armies response: armies must be an array");
    }
    return data.armies as ArmyListItem[];
  }, []);

  const changeRoster = useCallback(
    async (armyFile: string, player?: number) => {
      if (!gameState || gameState.phase !== "deployment") {
        throw new Error("changeRoster is only available during deployment phase");
      }
      const actionPayload: Record<string, unknown> = {
        action: "change_roster",
        army_file: armyFile,
      };
      if (player !== undefined) {
        actionPayload.player = player;
      }
      await executeAction(actionPayload);
      setSelectedUnitId(null);
      setMode("select");
    },
    [executeAction, gameState]
  );

  const handleSelectRuleChoice = useCallback(
    async (prompt: RuleChoicePrompt, selectedDisplayRuleId: string) => {
      await executeAction({
        action: "select_rule_choice",
        unitId: prompt.unit_id,
        player: prompt.player,
        selectedRuleId: selectedDisplayRuleId,
      });
    },
    [executeAction]
  );

  const confirmMoveInFlightRef = useRef(false);
  const handleConfirmMove = useCallback(async () => {
    if (confirmMoveInFlightRef.current) {
      return;
    }
    if (!movePreview) {
      return;
    }
    confirmMoveInFlightRef.current = true;

    try {
      if (pendingPreviewAction === "move_after_shooting") {
        await executeAction({
          action: "move_after_shooting",
          unitId: movePreview.unitId.toString(),
          destCol: movePreview.destCol,
          destRow: movePreview.destRow,
        });
        setMovePreview(null);
        setPendingPreviewAction(null);
        setPostShootMoveDestinations([]);
        setMode("select");
        return;
      }

      if (pendingPreviewAction === "move" || pendingPreviewAction == null) {
        const willFlee = isFleeMovePreview(
          movePreview.unitId,
          movePreview.destCol,
          movePreview.destRow
        );
        if (willFlee && shouldShowRetreatAlert()) {
          setFleeWarningPopup({
            unitId: movePreview.unitId,
            destCol: movePreview.destCol,
            destRow: movePreview.destRow,
            dontRemind: false,
            timestamp: Date.now(),
          });
          return;
        }
        if (!willFlee) {
          // Mouvement normal (non-flee) : calcul des positions rigides de chaque fig par delta cube,
          // puis entrée en squad move pour affiner. Seul Validate (commit_move_plan) finalise côté backend.
          const uid = movePreview.unitId;
          const unitEntry = (
            latestGameStateRef.current?.units_cache as
              | Record<
                  string,
                  {
                    col?: number;
                    row?: number;
                    occupied_hexes_by_model?: Record<string, [number, number]>;
                  }
                >
              | undefined
          )?.[String(uid)];
          const anchorCube = offsetToCube(
            unitEntry?.col ?? movePreview.destCol,
            unitEntry?.row ?? movePreview.destRow
          );
          const destCube = offsetToCube(movePreview.destCol, movePreview.destRow);
          const dx = destCube.x - anchorCube.x;
          const dy = destCube.y - anchorCube.y;
          const dz = destCube.z - anchorCube.z;
          const byModel = unitEntry?.occupied_hexes_by_model;
          const models: Record<string, { col: number; row: number }> = {};
          if (byModel) {
            for (const [mid, pos] of Object.entries(byModel)) {
              const fc = offsetToCube(pos[0], pos[1]);
              models[mid] = cubeToOffset({ x: fc.x + dx, y: fc.y + dy, z: fc.z + dz });
            }
          }
          setMovePreview(null);
          setPendingPreviewAction(null);
          if (Object.keys(models).length > 0) {
            squadMoveSessionRef.current += 1;
            squadMoveModelPoolRef.current = new Set();
            setSquadMovePlan((prev) => ({
              unitId: uid,
              models,
              originModels: { ...models },
              activeModelId: null,
              perModelValid: {},
              coherencyOk: true,
              canValidate: false,
              // Préserver wouldFlee sur ré-init de la même unité (sinon clignotement → badge effacé).
              wouldFlee: prev?.unitId === uid ? prev.wouldFlee : false,
            }));
            setSelectedUnitId(uid);
            setMode("squadModelMove");
            void refreshSquadMovePlanValidity(uid, models);
          } else {
            setSelectedUnitId(null);
            setMode("select");
          }
          return;
        }
      }

      await handleDirectMove(
        movePreview.unitId,
        movePreview.destCol,
        movePreview.destRow,
        movePreview.orientation
      );
      setPendingPreviewAction(null);
    } finally {
      confirmMoveInFlightRef.current = false;
    }
  }, [
    movePreview,
    pendingPreviewAction,
    executeAction,
    handleDirectMove,
    isFleeMovePreview,
    shouldShowRetreatAlert,
    refreshSquadMovePlanValidity,
  ]);

  const handleCancelMove = useCallback(async () => {
    if (pendingPreviewAction === "move_after_shooting") {
      // In confirmation sub-step: go back to destination selection.
      if (mode === "movePreview") {
        setMovePreview(null);
        setMode("select");
        return;
      }

      // In destination-selection step: explicitly skip post-shoot move in backend.
      if (mode === "select" && gameState?.phase === "shoot") {
        const activeShooterId = gameState.active_shooting_unit ?? selectedUnitId?.toString();
        if (!activeShooterId) {
          throw new Error(
            "Cannot skip move_after_shooting: missing active_shooting_unit and selectedUnitId"
          );
        }
        await executeAction({
          action: "move_after_shooting",
          unitId: activeShooterId.toString(),
          skip_move_after_shooting: true,
        });
        setPostShootMoveDestinations([]);
        setMovePreview(null);
        setPendingPreviewAction(null);
        setSelectedUnitId(null);
        setMode("select");
        return;
      }
    }

    setMovePreview(null);
    setPendingPreviewAction(null);
    setMode("select");
  }, [pendingPreviewAction, mode, gameState, selectedUnitId, executeAction]);

  const handleToggleFleeWarningDontRemind = useCallback((value: boolean) => {
    setFleeWarningPopup((prev) => {
      if (!prev) {
        return prev;
      }
      return { ...prev, dontRemind: value };
    });
  }, []);

  const applyRetreatAlertPreferenceFromPopup = useCallback((dontRemind: boolean) => {
    if (!dontRemind) {
      return;
    }
    localStorage.setItem(RETREAT_ALERT_STORAGE_KEY, JSON.stringify(false));
  }, []);

  const handleConfirmFleeWarning = useCallback(async () => {
    if (!fleeWarningPopup) return;
    const { unitId, destCol, destRow, dontRemind } = fleeWarningPopup;
    setFleeWarningPopup(null);
    applyRetreatAlertPreferenceFromPopup(dontRemind);
    await handleDirectMove(unitId, destCol, destRow);
    setPendingPreviewAction(null);
  }, [fleeWarningPopup, applyRetreatAlertPreferenceFromPopup, handleDirectMove]);

  const handleCancelFleeWarning = useCallback(async () => {
    if (!fleeWarningPopup) return;
    const { dontRemind } = fleeWarningPopup;
    setFleeWarningPopup(null);
    applyRetreatAlertPreferenceFromPopup(dontRemind);
    await handleCancelMove();
  }, [fleeWarningPopup, applyRetreatAlertPreferenceFromPopup, handleCancelMove]);

  // Backend handles all shooting logic - frontend just sends clicks
  const handleShoot = useCallback(
    async (_shooterId: number | string, targetId: number | string) => {
      // Convert to left_click action that backend understands
      await handleShootingPhaseClick(
        typeof targetId === "string" ? parseInt(targetId, 10) : targetId,
        "left"
      );
    },
    [handleShootingPhaseClick]
  );

  const handleSkipShoot = useCallback(
    async (unitId: number | string, actionType: "wait" | "action" = "action") => {
      // Check if we're still in shooting phase - if phase changed, don't send skip action
      if (gameState?.phase !== "shoot") {
        return;
      }
      if (pendingPreviewAction === "move_after_shooting" && actionType === "action") {
        await handleCancelMove();
        return;
      }
      // Convert to right_click or skip action
      if (actionType === "wait") {
        await handleRightClick(typeof unitId === "string" ? parseInt(unitId, 10) : unitId);
      } else {
        await executeAction({
          action: "skip",
          unitId: typeof unitId === "string" ? unitId : unitId.toString(),
        });
      }
    },
    [handleRightClick, executeAction, gameState, pendingPreviewAction, handleCancelMove]
  );

  // Charge activation - sends left_click to trigger 2d6 roll and destination building
  const handleActivateCharge = useCallback(
    async (chargerId: number | string) => {
      const numericChargerId = typeof chargerId === "string" ? parseInt(chargerId, 10) : chargerId;

      // Send left_click action to backend
      // Backend will call _handle_unit_activation which:
      // 1. Rolls 2d6 for charge_range
      // 2. Builds valid_charge_destinations_pool via BFS pathfinding
      // 3. Returns destinations for orange highlighting
      await executeAction({
        action: "left_click",
        unitId: numericChargerId.toString(),
      });
    },
    [executeAction]
  );

  // Fight activation - sends activate_unit to activate unit and get valid targets
  const handleActivateFight = useCallback(
    async (fighterId: number | string) => {
      const numericFighterId = typeof fighterId === "string" ? parseInt(fighterId, 10) : fighterId;

      if (activationInProgressRef.current) {
        return;
      }
      activationInProgressRef.current = true;
      setSelectedUnitId(numericFighterId);
      setActivationPendingUnitId(numericFighterId);
      try {
        await executeAction({
          action: "activate_unit",
          unitId: numericFighterId.toString(),
        });
        // Flux manuel par arme/figurine : initialise le plan local (cibles via gameState).
        const fightModels = Object.keys(readSquadModelPositions(numericFighterId));
        setSquadFightPlan({
          unitId: numericFighterId,
          models: fightModels,
          targets: {},
          declarations: [],
          activeModelId: null,
          activeWeaponIndex: null,
          canValidate: false,
        });
      } finally {
        activationInProgressRef.current = false;
        setActivationPendingUnitId(null);
      }
    },
    [executeAction, readSquadModelPositions]
  );

  const handlePileInMove = useCallback(
    async (unitId: number, destCol: number, destRow: number) => {
      const isConsolidation = mode === "consolidationPreview";
      await executeAction({
        action: isConsolidation ? "consolidation" : "pile_in",
        unitId: String(unitId),
        destCol,
        destRow,
      });
    },
    [executeAction, mode]
  );

  const handleSkipPileIn = useCallback(async () => {
    const uid = selectedUnitId;
    if (uid === null) {
      return;
    }
    const isConsolidation = mode === "consolidationPreview";
    await executeAction({
      action: isConsolidation ? "consolidation" : "pile_in",
      unitId: String(uid),
      skip: true,
    });
  }, [executeAction, selectedUnitId, mode]);

  // Bouton « Terminer le pile-in » : clôt l'étape pile-in groupée du joueur actif
  // (les unités non pilées sont passées) → le moteur enchaîne sur le groupe adverse
  // puis la sous-phase FIGHT.
  const handleEndPileIn = useCallback(async () => {
    await executeAction({ action: "end_pile_in" });
  }, [executeAction]);

  // Bouton « Skip » (sous-phase fight) : abandonne toutes les attaques restantes des 2
  // joueurs et passe directement à la consolidation.
  const handleSkipFight = useCallback(async () => {
    await executeAction({ action: "skip_fight" });
  }, [executeAction]);

  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Handle advance action
  const handleAdvance = useCallback(
    async (unitId: number) => {
      // Cancel target preview IMMEDIATELY (replace shooting preview with advance preview)
      // Clear blinking timer if it exists
      if (targetPreview?.blinkTimer) {
        clearInterval(targetPreview.blinkTimer);
      }
      setTargetPreview(null);
      // Also clear attackPreview if it exists
      setAttackPreview(null);
      // Change mode immediately to prevent shooting preview from showing
      setMode("select");

      // Check if advance warning popup is enabled (from localStorage)
      const showAdvanceWarningStr = localStorage.getItem("showAdvanceWarning");
      const showAdvanceWarning = showAdvanceWarningStr ? JSON.parse(showAdvanceWarningStr) : true;

      if (showAdvanceWarning) {
        // Show warning popup
        setAdvanceWarningPopup({
          unitId: unitId,
          timestamp: Date.now(),
        });
      } else {
        // Auto-confirm: execute advance directly (bypass popup)
        await executeAction({
          action: "advance",
          unitId: unitId.toString(),
        });
      }

      // Backend will return valid_destinations and advance_roll
      // State will be updated in executeAction response handler (will set mode to advancePreview)
    },
    [executeAction, targetPreview]
  );

  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Cancel advance action
  const handleCancelAdvance = useCallback(async () => {
    // Get the advancing unit ID before clearing state
    const unitIdToSkip = advancingUnitId;
    if (unitIdToSkip === null) {
      throw new Error(
        "Invariant violation: advancingUnitId is required to cancel advance activation"
      );
    }

    // Clear advance state
    setAdvanceDestinations([]);
    setPostShootMoveDestinations([]);
    setAdvancingUnitId(null);
    setAdvanceRoll(null);
    setMovePreview(null);
    setPendingPreviewAction(null);
    setMode("select");
    setSelectedUnitId(null);

    // Send skip action to backend to remove unit from activation pool
    await executeAction({
      action: "skip",
      unitId: unitIdToSkip.toString(),
    });
  }, [executeAction, advancingUnitId]);

  // Handle advance warning popup confirmation
  const handleConfirmAdvanceWarning = useCallback(async () => {
    if (!advanceWarningPopup) return;

    const unitId = advanceWarningPopup.unitId;

    // Clear popup
    setAdvanceWarningPopup(null);

    // Cancel target preview IMMEDIATELY (replace shooting preview with advance preview)
    if (targetPreview?.blinkTimer) {
      clearInterval(targetPreview.blinkTimer);
    }
    setTargetPreview(null);
    setAttackPreview(null);
    setMode("select");

    // Send advance action to backend to trigger 1D6 roll and get destinations
    await executeAction({
      action: "advance",
      unitId: unitId.toString(),
    });
  }, [advanceWarningPopup, executeAction, targetPreview]);

  // Handle advance warning popup cancellation
  const handleCancelAdvanceWarning = useCallback(() => {
    // Clear popup
    setAdvanceWarningPopup(null);
    // Clear all advance-related state and reset to selection mode
    // Don't send skip - keep unit in pool for re-activation
    setAdvanceDestinations([]);
    setPostShootMoveDestinations([]);
    setAdvancingUnitId(null);
    setAdvanceRoll(null);
    setMovePreview(null);
    setPendingPreviewAction(null);
    setMode("select");
    setSelectedUnitId(null);
  }, []);

  // Handle skip from advance warning popup
  const handleSkipAdvanceWarning = useCallback(async () => {
    if (!advanceWarningPopup) return;

    const unitIdToSkip = advanceWarningPopup.unitId;

    // Clear popup
    setAdvanceWarningPopup(null);

    // Clear all advance-related state
    setAdvanceDestinations([]);
    setAdvancingUnitId(null);
    setAdvanceRoll(null);
    setMovePreview(null);
    setPendingPreviewAction(null);
    setMode("select");
    setSelectedUnitId(null);

    // Send skip action to backend to remove unit from activation pool
    await executeAction({
      action: "skip",
      unitId: unitIdToSkip.toString(),
    });
  }, [advanceWarningPopup, executeAction]);

  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Clic sur hex valide = envoi immédiat (comme handleDirectMove en phase move)
  const handleAdvanceMove = useCallback(
    async (unitId: number | string, destCol: number, destRow: number) => {
      const numericUnitId = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;

      if (!gameState || gameState.phase !== "shoot") {
        throw new Error("Advance preview is only supported during shoot phase");
      }

      if (pendingPreviewAction === "move_after_shooting") {
        setMovePreview({
          unitId: numericUnitId,
          destCol,
          destRow,
          orientation: readEngineOrientationStepFromGameState(numericUnitId),
        });
        setSelectedUnitId(numericUnitId);
        setMode("movePreview");
        return;
      }

      try {
        await executeAction({
          action: "advance",
          unitId: numericUnitId.toString(),
          destCol,
          destRow,
        });
      } catch (error) {
        console.error("❌ ADVANCE MOVE FAILED:", error);
        throw error;
      }
    },
    [executeAction, gameState, pendingPreviewAction, readEngineOrientationStepFromGameState]
  );

  /** Compat : anciens appels ``onCombatAttack`` → même flux que le tir (``left_click`` + ``clickTarget``). */
  const handleFightAttack = useCallback(
    async (_attackerId: number | string, targetId: number | string | null) => {
      if (targetId === null) {
        logFightClick("handleFightAttack: ignoré (targetId null, ex. clic sur soi)", {
          attackerId: _attackerId,
        });
        return;
      }
      const numericTargetId = typeof targetId === "string" ? parseInt(targetId, 10) : targetId;
      logFightClick("handleFightAttack → handleFightPhaseClick (left_click)", {
        targetId: numericTargetId,
      });
      await handleFightPhaseClick(numericTargetId, "left");
    },
    [handleFightPhaseClick]
  );

  // Handle clicking on enemy unit in chargePreview mode - triggers charge roll and destination building
  const handleChargeEnemyUnit = useCallback(
    async (_chargerId: number | string, enemyUnitId: number | string) => {
      const numericEnemyId =
        typeof enemyUnitId === "string" ? parseInt(enemyUnitId, 10) : enemyUnitId;
      // V11 RAW multi-cibles : le clic ennemi TOGGLE la cible (aucun jet ici — déjà fait à
      // l'activation). Seules les cibles éligibles (clignotantes = dans la distance jetée) sont
      // toggle-ables ; un clic sur un ennemi hors portée est ignoré.
      if (!blinkingUnits.unitIds.some((id) => id === numericEnemyId)) {
        return;
      }
      setChargePreviewTargetIds((prev) =>
        prev.includes(numericEnemyId)
          ? prev.filter((id) => id !== numericEnemyId)
          : [...prev, numericEnemyId]
      );
    },
    [blinkingUnits]
  );

  // V11 multi-cibles : bouton « Charge » → envoie la liste des cibles déclarées. Le backend
  // réutilise le jet fait à l'activation, bâtit le pool (intersection eng==declared) et bascule
  // en sélection de destination (mode chargePreview).
  const handleValidateCharge = useCallback(
    async (chargerId: number | string) => {
      const numericChargerId = typeof chargerId === "string" ? parseInt(chargerId, 10) : chargerId;
      if (chargePreviewTargetIds.length === 0) {
        return; // aucune cible déclarée : le bouton ne doit pas être actif
      }
      await executeAction({
        action: "charge",
        unitId: numericChargerId.toString(),
        targetIds: chargePreviewTargetIds.map((id) => id.toString()),
      });
    },
    [executeAction, chargePreviewTargetIds]
  );

  // V11 RAW : le jet ayant déjà eu lieu à l'activation, annuler = résoudre la charge sans
  // mouvement (l'unité est consommée via « skip »). On nettoie la sélection locale de cibles.
  const handleCancelCharge = useCallback(async () => {
    const activeId = selectedUnitId;
    setChargePreviewTargetIds([]);
    setPendingChargeRollDisplay(null);
    if (activeId == null) {
      setMode("select");
      return;
    }
    try {
      await executeAction({ action: "skip", unitId: activeId.toString() });
    } catch (error) {
      console.error("Cancel charge (skip) failed:", error);
    }
    setSelectedUnitId(null);
    setMode("select");
  }, [executeAction, selectedUnitId]);

  const handleMoveCharger = useCallback(
    async (chargerId: number | string, destCol: number, destRow: number) => {
      const numericChargerId = typeof chargerId === "string" ? parseInt(chargerId, 10) : chargerId;

      if (!gameState) return;

      const charger = gameState.units.find((u) => parseInt(String(u.id), 10) === numericChargerId);
      if (!charger) {
        console.error("🟠 Charger unit not found:", numericChargerId);
        return;
      }

      // La cible a déjà été choisie (clic sur l’ennemi → jet + zone violette). Ne pas la deviner
      // par « adjacent à l’hex cliqué » : sur Board ×10 / empreintes larges, l’ancre de fin n’est
      // pas à distance 1 du centre primaire ennemi — le backend résout l’ancre depuis l’hex cliqué.
      let targetIdStr: string | null =
        chargePreviewTargetId != null ? String(chargePreviewTargetId) : null;
      if (targetIdStr == null) {
        const sel = (gameState as { charge_target_selections?: Record<string, string> })
          .charge_target_selections;
        if (sel?.[String(numericChargerId)]) {
          targetIdStr = String(sel[String(numericChargerId)]);
        }
      }
      if (!targetIdStr) {
        console.error(
          "🟠 handleMoveCharger: no charge target (chargePreviewTargetId / game_state)"
        );
        return;
      }

      await executeAction({
        action: "charge",
        unitId: numericChargerId.toString(),
        destCol,
        destRow,
        targetId: targetIdStr,
      });
    },
    [executeAction, gameState, chargePreviewTargetId]
  );

  // ──────────────────────────────────────────────────────────────────────────
  // CHARGE PAR FIGURINE (V11 11.04, Slice G) — calque squadModelMove, contrat backend
  // charge_plan_state (lecture pure) + commit_charge_plan.
  // ──────────────────────────────────────────────────────────────────────────

  /** Applique une réponse charge_plan_state : voile (eligible_models) + pool de la fig sélectionnée. */
  const applyChargePlanState = useCallback(
    (result: Record<string, unknown>, selectedModel: string | null) => {
      const eligibleModels = ((result.eligible_models ?? []) as unknown[]).map((m) => String(m));
      const poolArr = (result.pool ?? []) as Array<[number, number]>;
      const poolDistArr = (result.pool_distances ?? []) as Array<[number, number, number]>;
      const maskLoopsRaw = result.footprint_mask_loops;
      const unplaced = ((result.unplaced ?? []) as unknown[]).map((m) => String(m));
      const currentPhase = (Number(result.current_phase) || 3) as 1 | 2 | 3;
      const canValidate = result.can_validate === true;
      const satisfiedTargets = ((result.satisfied_targets ?? []) as unknown[]).map((t) =>
        parseInt(String(t), 10)
      );
      const unsatisfiedTargets = ((result.unsatisfied_targets ?? []) as unknown[]).map((t) =>
        parseInt(String(t), 10)
      );
      const engagedModels = ((result.engaged_models ?? []) as unknown[]).map((m) => String(m));
      const perModelValid = (result.per_model ?? {}) as Record<string, boolean>;
      const coherencyOk = result.coherency_ok !== false;
      const missingTargets = ((result.missing_targets ?? []) as unknown[]).map((t) =>
        parseInt(String(t), 10)
      );
      setChargeMovePlan((prev) => {
        if (!prev) return prev;
        // Fig active = celle sélectionnée si encore éligible, sinon l'ancienne si toujours éligible,
        // sinon aucune (ex: fig posée → sort de eligible_models). Le pool ne vaut que pour elle.
        const active =
          selectedModel != null && eligibleModels.includes(selectedModel)
            ? selectedModel
            : prev.activeModelId && eligibleModels.includes(prev.activeModelId)
              ? prev.activeModelId
              : null;
        const pool = new Set<string>();
        // A SUPPRIMER : distMap alimente chargeModelDistancesRef (feature charge par-fig morte).
        const distMap = new Map<string, number>();
        if (active != null && active === selectedModel) {
          for (const [c, r] of poolArr) pool.add(`${Number(c)},${Number(r)}`);
          for (const e of poolDistArr) {
            if (Array.isArray(e) && e.length >= 3) {
              distMap.set(`${Number(e[0])},${Number(e[1])}`, Number(e[2]));
            }
          }
        }
        chargeModelPoolRef.current = pool;
        chargeModelDistancesRef.current = distMap;
        // Mask loops valides uniquement pour la fig active sélectionnée (le backend ne les calcule
        // que pour son pool). Sinon null → pas de rendu lissé fantôme d'une autre fig.
        chargeModelMaskLoopsRef.current =
          active != null && active === selectedModel && Array.isArray(maskLoopsRaw)
            ? (maskLoopsRaw as number[][])
            : null;
        return {
          ...prev,
          eligibleModels,
          unplaced,
          currentPhase,
          canValidate,
          satisfiedTargets,
          unsatisfiedTargets,
          engagedModels,
          perModelValid,
          coherencyOk,
          missingTargets,
          activeModelId: active,
        };
      });
    },
    []
  );

  /** Lecture pure : recalcule l'état du plan de charge depuis le backend. ``selectedModel`` → le
   * backend renvoie le pool (zone) de CETTE fig uniquement (la part chère n'est faite que pour elle). */
  const refreshChargePlanState = useCallback(
    async (
      unitId: number,
      models: Record<string, { col: number; row: number }>,
      selectedModel: string | null = null
    ) => {
      const plan = Object.entries(models).map(([mid, p]) => [mid, p.col, p.row]);
      const action: Record<string, unknown> = {
        action: "charge_plan_state",
        unitId: String(unitId),
        plan,
      };
      if (selectedModel != null) action.selected_model = selectedModel;
      const result = await postEngineQuery(action);
      if (!result) throw new Error("charge_plan_state: réponse vide");
      applyChargePlanState(result, selectedModel);
    },
    [postEngineQuery, applyChargePlanState]
  );

  /** Bouton Take to the sky (unités FLY) : (dé)clare le vol (-2" + traversée, Règles 21.03).
   * Phase charge (plan par-fig actif) → re-calcule les pools ; phase move → re-valide le plan move. */
  const handleTakeToSkies = useCallback(
    async (unitId: number | string) => {
      const uid = typeof unitId === "string" ? parseInt(unitId, 10) : unitId;
      const data = await executeAction({ action: "take_to_skies", unitId: String(uid) });
      // Phase charge, plan par-fig actif (sécurité) : le toggle change budget (-2") + traversée → recalcul.
      const chargePlan = chargeMovePlanRef.current;
      if (chargePlan && chargePlan.unitId === uid) {
        await refreshChargePlanState(uid, chargePlan.models, chargePlan.activeModelId);
        return;
      }
      // Phase charge, étape sélection de cible : le backend renvoie les cibles éligibles re-bornées par
      // la distance -2" (blinking_units). On force le surlignage (la logique needsNewTimer ne rafraîchit
      // pas un ensemble qui rétrécit) et on purge les cibles pré-déclarées devenues hors portée.
      if (data?.game_state?.phase === "charge") {
        const res = data.result as Record<string, unknown> | undefined;
        const blink = Array.isArray(res?.blinking_units)
          ? (res.blinking_units as string[]).map((id) => parseInt(id, 10))
          : [];
        setBlinkingUnits((prev) => ({ ...prev, unitIds: blink }));
        setChargePreviewTargetIds((prev) => prev.filter((id) => blink.includes(id)));
        return;
      }
      // Phase move : re-valide le plan et reconstruit le pool de la figurine active, comme l'Advance.
      const plan = squadMovePlanRef.current;
      if (plan && plan.unitId === uid) {
        await refreshSquadMovePlanValidity(uid, plan.models);
        if (plan.activeModelId) {
          await handleSelectModelForMove(plan.activeModelId);
        }
      }
    },
    [executeAction, refreshSquadMovePlanValidity, handleSelectModelForMove, refreshChargePlanState]
  );

  /** Entrée en mode chargeModelMove (escouade chargeuse multi-fig). Plan provisoire vide au départ. */
  const handleStartChargeModelMove = useCallback(
    async (unitId: number) => {
      const models = readSquadModelPositions(unitId);
      if (Object.keys(models).length === 0) {
        throw new Error(
          `charge model move: aucune fig pour l'unité ${unitId} (occupied_hexes_by_model)`
        );
      }
      chargeModelPoolRef.current = new Set();
      chargeModelMaskLoopsRef.current = null;
      setChargeMovePlan({
        unitId,
        models: {},
        eligibleModels: [],
        unplaced: Object.keys(models),
        activeModelId: null,
        currentPhase: 1,
        canValidate: false,
        satisfiedTargets: [],
        unsatisfiedTargets: [],
        engagedModels: [],
        perModelValid: {},
        coherencyOk: true,
        missingTargets: [],
      });
      setChargeFocusActive(false);
      setChargeFocusMode(null);
      setSelectedUnitId(unitId);
      setMode("chargeModelMove");
      await refreshChargePlanState(unitId, {});
    },
    [readSquadModelPositions, refreshChargePlanState]
  );

  /** Bouton Focus : (dé)active le mode focus en chargeModelMove (voile violet sur les cibles). */
  const handleToggleChargeFocus = useCallback(() => {
    setChargeFocusActive((v) => !v);
  }, []);

  /** Clic sur une cible déclarée en mode focus : demande le plan d'auto-placement optimal au backend
   * (charge_autoplace), charge ce plan dans le plan provisoire, puis revalide (refreshChargePlanState).
   * L'ajustement manuel reste ensuite possible (positions non verrouillées). */
  const handleChargeFocusTargetClick = useCallback(
    async (targetId: number | string) => {
      const plan = chargeMovePlanRef.current;
      if (!plan || !chargeFocusActiveRef.current) return;
      const tid = typeof targetId === "string" ? parseInt(targetId, 10) : targetId;
      // Garde : seule une cible déclarée de la charge est focusable.
      if (!chargePreviewTargetIdsRef.current.includes(tid)) return;
      const result = await postEngineQuery({
        action: "charge_autoplace",
        unitId: String(plan.unitId),
        targetId: String(tid),
      });
      if (!result) throw new Error("charge_autoplace: réponse vide");
      const planArr = (result.plan ?? []) as Array<[string, number, number]>;
      const models: Record<string, { col: number; row: number }> = {};
      for (const [mid, c, r] of planArr) {
        models[String(mid)] = { col: Number(c), row: Number(r) };
      }
      chargeModelPoolRef.current = new Set();
      chargeModelMaskLoopsRef.current = null;
      setChargeFocusActive(false);
      setChargeMovePlan((prev) => (prev ? { ...prev, models, activeModelId: null } : prev));
      await refreshChargePlanState(plan.unitId, models, null);
    },
    [postEngineQuery, refreshChargePlanState]
  );

  /** Bouton Focus off./déf. : auto-placement de TOUTES les figs vers TOUTES les cibles déclarées
   * (charge_autoplace, ILP), dans le mode choisi. Pas de re-sélection de cible. Charge le plan dans le
   * plan provisoire puis revalide ; l'ajustement manuel reste possible ensuite. */
  const handleChargeAutoplace = useCallback(
    async (mode: "offensive" | "defensive") => {
      const plan = chargeMovePlanRef.current;
      if (!plan) return;
      setChargeFocusMode(mode);
      const result = await postEngineQuery({
        action: "charge_autoplace",
        unitId: String(plan.unitId),
        mode,
      });
      if (!result) throw new Error("charge_autoplace: réponse vide");
      const planArr = (result.plan ?? []) as Array<[string, number, number]>;
      const models: Record<string, { col: number; row: number }> = {};
      for (const [mid, c, r] of planArr) {
        models[String(mid)] = { col: Number(c), row: Number(r) };
      }
      chargeModelPoolRef.current = new Set();
      chargeModelMaskLoopsRef.current = null;
      setChargeFocusActive(false);
      setChargeMovePlan((prev) => (prev ? { ...prev, models, activeModelId: null } : prev));
      await refreshChargePlanState(plan.unitId, models, null);
    },
    [postEngineQuery, refreshChargePlanState]
  );

  /** Clic sur une fig éligible : la rend active + demande SON pool au backend (calcul ciblé). */
  const handleSelectChargeModel = useCallback(
    (modelId: string) => {
      const plan = chargeMovePlanRef.current;
      if (!plan?.eligibleModels.includes(modelId)) return; // non éligible → ignore
      chargeModelPoolRef.current = new Set();
      chargeModelMaskLoopsRef.current = null;
      setChargeMovePlan((prev) => (prev ? { ...prev, activeModelId: modelId } : prev));
      void refreshChargePlanState(plan.unitId, plan.models, modelId);
    },
    [refreshChargePlanState]
  );

  /** Pose la fig active à (col,row) (dans son pool) → MAJ plan + re-charge_plan_state. */
  const handleMoveModelInChargePlan = useCallback(
    (modelId: string, col: number, row: number) => {
      if (!chargeModelPoolRef.current.has(`${col},${row}`)) return;
      chargeModelPoolRef.current = new Set();
      chargeModelMaskLoopsRef.current = null;
      setChargeMovePlan((prev) => {
        if (!prev) return prev;
        const models = { ...prev.models, [modelId]: { col, row } };
        // Pose → fig désélectionnée ; refresh sans selected (juste le voile des figs restantes).
        void refreshChargePlanState(prev.unitId, models, null);
        return { ...prev, models, activeModelId: null };
      });
    },
    [refreshChargePlanState]
  );

  /** Clic sur une fig DÉJÀ POSÉE : la retire du plan (redevient éligible) pour la repositionner. */
  const handleUnplaceChargeModel = useCallback(
    (modelId: string) => {
      setChargeMovePlan((prev) => {
        if (!prev?.models[modelId]) return prev;
        const models = { ...prev.models };
        delete models[modelId];
        // Re-sélectionne la fig dé-posée (selected) → sa zone réapparaît directement.
        void refreshChargePlanState(prev.unitId, models, modelId);
        return { ...prev, models, activeModelId: modelId };
      });
    },
    [refreshChargePlanState]
  );

  /** Bouton Charger : commit atomique du plan complet (commit_charge_plan). */
  const handleCommitChargePlan = useCallback(async () => {
    const plan = chargeMovePlanRef.current;
    if (!plan?.canValidate) return;
    const planArr = Object.entries(plan.models).map(([mid, p]) => [mid, p.col, p.row]);
    try {
      await executeAction({
        action: "commit_charge_plan",
        unitId: String(plan.unitId),
        plan: planArr,
      });
      chargeModelPoolRef.current = new Set();
      chargeModelMaskLoopsRef.current = null;
      setChargeFocusActive(false);
      setChargeFocusMode(null);
      setChargeMovePlan(null);
      setChargePreviewTargetIds([]);
      setPendingChargeRollDisplay(null);
      setSelectedUnitId(null);
      setMode("select");
    } catch (e) {
      console.error("[CHARGE-MOVE] commit FAILED", e);
      setError(`Charge move failed: ${formatApiConnectionError(e)}`);
    }
  }, [executeAction]);

  /** Bouton Cancel : forfait charge (skip, consomme l'unité), nettoie le plan local. */
  const handleCancelChargeModelMove = useCallback(async () => {
    const plan = chargeMovePlanRef.current;
    const uid = plan?.unitId ?? selectedUnitId;
    chargeModelPoolRef.current = new Set();
    chargeModelMaskLoopsRef.current = null;
    setChargeFocusActive(false);
    setChargeFocusMode(null);
    setChargeMovePlan(null);
    setChargePreviewTargetIds([]);
    setPendingChargeRollDisplay(null);
    if (uid == null) {
      setMode("select");
      return;
    }
    try {
      await executeAction({ action: "skip", unitId: String(uid) });
    } catch (e) {
      console.error("Cancel charge model move (skip) failed:", e);
    }
    setSelectedUnitId(null);
    setMode("select");
  }, [executeAction, selectedUnitId]);

  // ──────────────────────────────────────────────────────────────────────────
  // PILE-IN PAR FIGURINE (V11 12.04, mode fin type charge) — contrat backend
  // pile_in_plan_state (lecture pure) + commit_pile_in_plan. L'unité active vient
  // de game_state.active_fight_unit (posée par activate_unit) → pas d'unitId dans l'action.
  // ──────────────────────────────────────────────────────────────────────────

  /** Applique une réponse pile_in_model_move (plan_state) : voile (eligible_models) + pool de la
   * fig sélectionnée. Initialise le plan local depuis ``provisional`` au premier appel (prev null). */
  const applyPileInPlanState = useCallback((result: Record<string, unknown>) => {
    const eligibleModels = ((result.eligible_models ?? []) as unknown[]).map((m) => String(m));
    const poolArr = (result.pool ?? []) as Array<[number, number]>;
    const maskLoopsRaw = result.footprint_mask_loops;
    const unplaced = ((result.unplaced ?? []) as unknown[]).map((m) => String(m));
    const canValidate = result.can_validate === true;
    const selectedModel = result.selected_model != null ? String(result.selected_model) : null;
    // Sous-conditions de légalité (alimentent le bouton « Check pile-in » + voile rouge par-fig).
    const perModelValid = (result.per_model_valid ?? {}) as Record<string, boolean>;
    const coherencyOk = result.coherency_ok === true;
    const unitEngaged = result.unit_engaged === true;
    const keptEngagements = result.kept_engagements === true;
    const engagedModels = ((result.engaged_models ?? []) as unknown[]).map((m) => String(m));
    const pileInTargets = ((result.pile_in_targets ?? []) as unknown[]).map((m) => String(m));
    setPileInMovePlan((prev) => {
      const base = prev ?? {
        unitId: parseInt(String(result.unitId), 10),
        models: Object.fromEntries(
          Object.entries((result.provisional ?? {}) as Record<string, [number, number]>).map(
            ([m, p]) => [m, { col: Number(p[0]), row: Number(p[1]) }]
          )
        ),
        eligibleModels: [],
        unplaced: [],
        activeModelId: null,
        canValidate: false,
        perModelValid: {} as Record<string, boolean>,
        coherencyOk: false,
        unitEngaged: false,
        keptEngagements: false,
        engagedModels: [] as string[],
        pileInTargets: [] as string[],
      };
      // Fig active = celle échoée par le backend si encore éligible, sinon l'ancienne si toujours
      // éligible, sinon aucune. Le pool ne vaut que pour elle (calcul ciblé backend).
      const active =
        selectedModel != null && eligibleModels.includes(selectedModel)
          ? selectedModel
          : base.activeModelId && eligibleModels.includes(base.activeModelId)
            ? base.activeModelId
            : null;
      const pool = new Set<string>();
      if (active != null && active === selectedModel) {
        for (const [c, r] of poolArr) pool.add(`${Number(c)},${Number(r)}`);
      }
      pileInModelPoolRef.current = pool;
      pileInModelMaskLoopsRef.current =
        active != null && active === selectedModel && Array.isArray(maskLoopsRaw)
          ? (maskLoopsRaw as number[][])
          : null;
      return {
        ...base,
        eligibleModels,
        unplaced,
        canValidate,
        activeModelId: active,
        perModelValid,
        coherencyOk,
        unitEngaged,
        keptEngagements,
        engagedModels,
        pileInTargets,
      };
    });
  }, []);

  /** Lecture pure : recalcule l'état du plan pile-in depuis le backend (active_fight_unit). */
  const refreshPileInPlanState = useCallback(
    async (
      models: Record<string, { col: number; row: number }>,
      selectedModel: string | null = null
    ) => {
      const plan = Object.entries(models).map(([mid, p]) => [mid, p.col, p.row]);
      const action: Record<string, unknown> = { action: "pile_in_plan_state", plan };
      if (selectedModel != null) action.selected_model = selectedModel;
      const result = await postEngineQuery(action);
      if (!result) throw new Error("pile_in_plan_state: réponse vide");
      applyPileInPlanState(result);
    },
    [postEngineQuery, applyPileInPlanState]
  );

  /** Lance pile_in_autoplace pour (cible, mode) et charge le plan optimal dans le plan provisoire,
   * puis revalide. Ne reset NI le mode NI la cible mémorisés : on peut enchaîner les changements. */
  const runPileInAutoplace = useCallback(
    async (targetId: string, mode: "defensive" | "offensive") => {
      const result = await postEngineQuery({ action: "pile_in_autoplace", targetId, mode });
      if (!result) throw new Error("pile_in_autoplace: réponse vide");
      const planArr = (result.plan ?? []) as Array<[string, number, number]>;
      const models: Record<string, { col: number; row: number }> = {};
      for (const [mid, c, r] of planArr) {
        models[String(mid)] = { col: Number(c), row: Number(r) };
      }
      pileInModelPoolRef.current = new Set();
      pileInModelMaskLoopsRef.current = null;
      setPileInMovePlan((prev) => (prev ? { ...prev, models, activeModelId: null } : prev));
      await refreshPileInPlanState(models, null);
    },
    [postEngineQuery, refreshPileInPlanState]
  );

  /** Boutons Focus pile-in (Défensif / Offensif) : (dé)active le mode (re-clic même mode = off).
   * Si une cible est déjà mémorisée, (re)lance l'autoplace avec ce mode. */
  const handleSetPileInFocus = useCallback(
    (mode: "defensive" | "offensive") => {
      const next = pileInFocusModeRef.current === mode ? null : mode;
      setPileInFocusMode(next);
      const tid = pileInFocusTargetIdRef.current;
      if (next && tid) void runPileInAutoplace(tid, next);
    },
    [runPileInAutoplace]
  );

  /** Clic sur une cible pile-in : la mémorise (focus). Si un mode est déjà actif, (re)lance
   * l'auto-placement optimal pour cette cible. Ajustement manuel possible ensuite. */
  const handlePileInFocusTargetClick = useCallback(
    async (targetId: number | string) => {
      const plan = pileInMovePlanRef.current;
      if (!plan) return;
      const tid = String(targetId);
      if (!plan.pileInTargets.includes(tid)) return; // seule une cible pile-in est focusable
      setPileInFocusTargetId(tid);
      const mode = pileInFocusModeRef.current;
      if (mode) await runPileInAutoplace(tid, mode);
    },
    [runPileInAutoplace]
  );

  /** Clic sur une fig éligible : la rend active + demande SON pool au backend (calcul ciblé). */
  const handleSelectPileInModel = useCallback(
    (modelId: string) => {
      const plan = pileInMovePlanRef.current;
      if (!plan?.eligibleModels.includes(modelId)) return; // non éligible → ignore
      pileInModelPoolRef.current = new Set();
      pileInModelMaskLoopsRef.current = null;
      setPileInMovePlan((prev) => (prev ? { ...prev, activeModelId: modelId } : prev));
      void refreshPileInPlanState(plan.models, modelId);
    },
    [refreshPileInPlanState]
  );

  /** Pose la fig active à (col,row) (dans son pool) → MAJ plan + re-pile_in_plan_state. */
  const handleMovePileInModel = useCallback(
    (modelId: string, col: number, row: number) => {
      if (!pileInModelPoolRef.current.has(`${col},${row}`)) return;
      pileInModelPoolRef.current = new Set();
      pileInModelMaskLoopsRef.current = null;
      setPileInMovePlan((prev) => {
        if (!prev) return prev;
        const models = { ...prev.models, [modelId]: { col, row } };
        // Pose → fig désélectionnée ; refresh sans selected (juste le voile des figs restantes).
        void refreshPileInPlanState(models, null);
        return { ...prev, models, activeModelId: null };
      });
    },
    [refreshPileInPlanState]
  );

  /** Clic sur une fig DÉJÀ POSÉE : la retire du plan (redevient éligible) pour la repositionner. */
  const handleUnplacePileInModel = useCallback(
    (modelId: string) => {
      setPileInMovePlan((prev) => {
        if (!prev?.models[modelId]) return prev;
        const models = { ...prev.models };
        delete models[modelId];
        void refreshPileInPlanState(models, modelId);
        return { ...prev, models, activeModelId: modelId };
      });
    },
    [refreshPileInPlanState]
  );

  /** Bouton Valider le pile-in : commit atomique du plan complet (commit_pile_in_plan). */
  const handleCommitPileInPlan = useCallback(async () => {
    const plan = pileInMovePlanRef.current;
    if (!plan?.canValidate) return;
    const planArr = Object.entries(plan.models).map(([mid, p]) => [mid, p.col, p.row]);
    try {
      await executeAction({ action: "commit_pile_in_plan", plan: planArr });
      pileInModelPoolRef.current = new Set();
      pileInModelMaskLoopsRef.current = null;
      setPileInFocusMode(null);
      setPileInFocusTargetId(null);
      setPileInMovePlan(null);
      setSelectedUnitId(null);
      setMode("select");
    } catch (e) {
      console.error("[PILE-IN] commit FAILED", e);
      setError(`Pile-in failed: ${formatApiConnectionError(e)}`);
    }
  }, [executeAction]);

  /** Bouton Annuler : renonce à piler l'unité active (skip, la consomme), nettoie le plan local. */
  const handleCancelPileInModelMove = useCallback(async () => {
    pileInModelPoolRef.current = new Set();
    pileInModelMaskLoopsRef.current = null;
    setPileInFocusMode(null);
    setPileInFocusTargetId(null);
    setPileInMovePlan(null);
    try {
      await executeAction({ action: "skip" });
    } catch (e) {
      console.error("Cancel pile-in model move (skip) failed:", e);
    }
    setSelectedUnitId(null);
    setMode("select");
  }, [executeAction]);

  // ──────────────────────────────────────────────────────────────────────────
  // CONSOLIDATION PAR-FIGURINE (V11 12.08, miroir pile-in). active_fight_unit posée
  // par activate_unit → pas d'unitId dans les actions de plan. Sélection préalable
  // (engaging/objective) via consolidation_select_target / consolidation_select_objective.
  // ──────────────────────────────────────────────────────────────────────────

  /** Applique une réponse consolidation_model_move (plan_state) : voile + pool fig + état cascade. */
  const applyConsolidationPlanState = useCallback((result: Record<string, unknown>) => {
    const eligibleModels = ((result.eligible_models ?? []) as unknown[]).map((m) => String(m));
    const poolArr = (result.pool ?? []) as Array<[number, number]>;
    const maskLoopsRaw = result.footprint_mask_loops;
    const unplaced = ((result.unplaced ?? []) as unknown[]).map((m) => String(m));
    const canValidate = result.can_validate === true;
    const selectedModel = result.selected_model != null ? String(result.selected_model) : null;
    const perModelValid = (result.per_model_valid ?? {}) as Record<string, boolean>;
    const coherencyOk = result.coherency_ok === true;
    const unitEngaged = result.unit_engaged === true;
    const keptEngagements = result.kept_engagements === true;
    const engagedWithAllSelected = result.engaged_with_all_selected === true;
    const withinObjectiveRange = result.within_objective_range === true;
    const engagedModels = ((result.engaged_models ?? []) as unknown[]).map((m) => String(m));
    const consolidationMode =
      result.consolidation_mode != null ? String(result.consolidation_mode) : null;
    const engagingCandidates = ((result.engaging_candidates ?? []) as unknown[]).map((m) =>
      String(m)
    );
    const objectiveCandidates = ((result.objective_candidates ?? []) as unknown[]).map((m) =>
      String(m)
    );
    const consolidationTargets = ((result.consolidation_targets ?? []) as unknown[]).map((m) =>
      String(m)
    );
    const awaitingTargetSelection = result.awaiting_target_selection === true;
    const awaitingObjectiveSelection = result.awaiting_objective_selection === true;
    setConsolidationMovePlan((prev) => {
      const base = prev ?? {
        unitId: parseInt(String(result.unitId), 10),
        models: Object.fromEntries(
          Object.entries((result.provisional ?? {}) as Record<string, [number, number]>).map(
            ([m, p]) => [m, { col: Number(p[0]), row: Number(p[1]) }]
          )
        ),
        eligibleModels: [],
        unplaced: [],
        activeModelId: null,
        canValidate: false,
        perModelValid: {} as Record<string, boolean>,
        coherencyOk: false,
        unitEngaged: false,
        keptEngagements: false,
        engagedWithAllSelected: false,
        withinObjectiveRange: false,
        engagedModels: [] as string[],
        consolidationMode: null as string | null,
        engagingCandidates: [] as string[],
        objectiveCandidates: [] as string[],
        consolidationTargets: [] as string[],
        awaitingTargetSelection: false,
        awaitingObjectiveSelection: false,
      };
      const active =
        selectedModel != null && eligibleModels.includes(selectedModel)
          ? selectedModel
          : base.activeModelId && eligibleModels.includes(base.activeModelId)
            ? base.activeModelId
            : null;
      const pool = new Set<string>();
      if (active != null && active === selectedModel) {
        for (const [c, r] of poolArr) pool.add(`${Number(c)},${Number(r)}`);
      }
      consolidationModelPoolRef.current = pool;
      consolidationModelMaskLoopsRef.current =
        active != null && active === selectedModel && Array.isArray(maskLoopsRaw)
          ? (maskLoopsRaw as number[][])
          : null;
      return {
        ...base,
        eligibleModels,
        unplaced,
        canValidate,
        activeModelId: active,
        perModelValid,
        coherencyOk,
        unitEngaged,
        keptEngagements,
        engagedWithAllSelected,
        withinObjectiveRange,
        engagedModels,
        consolidationMode,
        engagingCandidates,
        objectiveCandidates,
        consolidationTargets,
        awaitingTargetSelection,
        awaitingObjectiveSelection,
      };
    });
  }, []);

  /** Lecture pure : recalcule l'état du plan de consolidation depuis le backend. */
  const refreshConsolidationPlanState = useCallback(
    async (
      models: Record<string, { col: number; row: number }>,
      selectedModel: string | null = null
    ) => {
      const plan = Object.entries(models).map(([mid, p]) => [mid, p.col, p.row]);
      const action: Record<string, unknown> = { action: "consolidation_plan_state", plan };
      if (selectedModel != null) action.selected_model = selectedModel;
      const result = await postEngineQuery(action);
      if (!result) throw new Error("consolidation_plan_state: réponse vide");
      applyConsolidationPlanState(result);
    },
    [postEngineQuery, applyConsolidationPlanState]
  );

  /** Lance consolidate_autoplace (12.08) pour le mode courant et charge le plan optimal dans le plan
   * provisoire, puis revalide. Le backend route ongoing → pile-in, engaging → charge ; objective non
   * supporté (les boutons sont masqués pour ce mode côté UI). Ajustement manuel possible ensuite. */
  const runConsolidationAutoplace = useCallback(
    async (mode: "defensive" | "offensive") => {
      const result = await postEngineQuery({ action: "consolidate_autoplace", mode });
      if (!result) throw new Error("consolidate_autoplace: réponse vide");
      const planArr = (result.plan ?? []) as Array<[string, number, number]>;
      const models: Record<string, { col: number; row: number }> = {};
      for (const [mid, c, r] of planArr) {
        models[String(mid)] = { col: Number(c), row: Number(r) };
      }
      consolidationModelPoolRef.current = new Set();
      consolidationModelMaskLoopsRef.current = null;
      setConsolidationMovePlan((prev) => (prev ? { ...prev, models, activeModelId: null } : prev));
      await refreshConsolidationPlanState(models, null);
    },
    [postEngineQuery, refreshConsolidationPlanState]
  );

  /** Boutons Focus consolidation (Défensif / Offensif) : (dé)active le mode (re-clic même mode = off).
   * Si actif, (re)lance l'auto-placement optimal pour le mode de consolidation courant. */
  const handleSetConsolidationFocus = useCallback(
    (mode: "defensive" | "offensive") => {
      const next = consolidationFocusModeRef.current === mode ? null : mode;
      setConsolidationFocusMode(next);
      if (next) void runConsolidationAutoplace(next);
    },
    [runConsolidationAutoplace]
  );

  /** Engaging : toggle d'un ennemi candidat (≤3") avant le move (consolidation_select_target). */
  const handleConsolidationSelectTarget = useCallback(
    async (targetId: number | string) => {
      const plan = consolidationMovePlanRef.current;
      if (!plan) return;
      const tid = String(targetId);
      if (!plan.engagingCandidates.includes(tid)) return;
      const planArr = Object.entries(plan.models).map(([mid, p]) => [mid, p.col, p.row]);
      const result = await postEngineQuery({
        action: "consolidation_select_target",
        targetId: tid,
        plan: planArr,
        selected_model: plan.activeModelId,
      });
      if (!result) throw new Error("consolidation_select_target: réponse vide");
      applyConsolidationPlanState(result);
    },
    [postEngineQuery, applyConsolidationPlanState]
  );

  /** Objective : single-select d'un objectif candidat (consolidation_select_objective). */
  const handleConsolidationSelectObjective = useCallback(
    async (objectiveId: number | string) => {
      const plan = consolidationMovePlanRef.current;
      if (!plan) return;
      const oid = String(objectiveId);
      if (!plan.objectiveCandidates.includes(oid)) return;
      const planArr = Object.entries(plan.models).map(([mid, p]) => [mid, p.col, p.row]);
      const result = await postEngineQuery({
        action: "consolidation_select_objective",
        objectiveId: oid,
        plan: planArr,
        selected_model: plan.activeModelId,
      });
      if (!result) throw new Error("consolidation_select_objective: réponse vide");
      applyConsolidationPlanState(result);
    },
    [postEngineQuery, applyConsolidationPlanState]
  );

  /** Clic sur une fig éligible : la rend active + demande SON pool au backend. */
  const handleSelectConsolidationModel = useCallback(
    (modelId: string) => {
      const plan = consolidationMovePlanRef.current;
      if (!plan?.eligibleModels.includes(modelId)) return;
      consolidationModelPoolRef.current = new Set();
      consolidationModelMaskLoopsRef.current = null;
      setConsolidationMovePlan((prev) => (prev ? { ...prev, activeModelId: modelId } : prev));
      void refreshConsolidationPlanState(plan.models, modelId);
    },
    [refreshConsolidationPlanState]
  );

  /** Pose la fig active à (col,row) (dans son pool) → MAJ plan + re-plan_state. */
  const handleMoveConsolidationModel = useCallback(
    (modelId: string, col: number, row: number) => {
      if (!consolidationModelPoolRef.current.has(`${col},${row}`)) return;
      consolidationModelPoolRef.current = new Set();
      consolidationModelMaskLoopsRef.current = null;
      setConsolidationMovePlan((prev) => {
        if (!prev) return prev;
        const models = { ...prev.models, [modelId]: { col, row } };
        void refreshConsolidationPlanState(models, null);
        return { ...prev, models, activeModelId: null };
      });
    },
    [refreshConsolidationPlanState]
  );

  /** Clic sur une fig DÉJÀ POSÉE : la retire du plan pour la repositionner. */
  const handleUnplaceConsolidationModel = useCallback(
    (modelId: string) => {
      setConsolidationMovePlan((prev) => {
        if (!prev?.models[modelId]) return prev;
        const models = { ...prev.models };
        delete models[modelId];
        void refreshConsolidationPlanState(models, modelId);
        return { ...prev, models, activeModelId: modelId };
      });
    },
    [refreshConsolidationPlanState]
  );

  /** Bouton Valider la consolidation : commit atomique (commit_consolidation_plan). */
  const handleCommitConsolidationPlan = useCallback(async () => {
    const plan = consolidationMovePlanRef.current;
    if (!plan?.canValidate) return;
    const planArr = Object.entries(plan.models).map(([mid, p]) => [mid, p.col, p.row]);
    try {
      await executeAction({ action: "commit_consolidation_plan", plan: planArr });
      consolidationModelPoolRef.current = new Set();
      consolidationModelMaskLoopsRef.current = null;
      setConsolidationFocusMode(null);
      setConsolidationMovePlan(null);
      setSelectedUnitId(null);
      setMode("select");
    } catch (e) {
      console.error("[CONSOLIDATION] commit FAILED", e);
      setError(`Consolidation failed: ${formatApiConnectionError(e)}`);
    }
  }, [executeAction]);

  /** Bouton Annuler : annule le plan de consolidation en cours SANS consommer l'unité — elle
   * redevient sélectionnable (cancel_consolidation côté moteur), nettoie le plan local. */
  const handleCancelConsolidationModelMove = useCallback(async () => {
    consolidationModelPoolRef.current = new Set();
    consolidationModelMaskLoopsRef.current = null;
    setConsolidationFocusMode(null);
    setConsolidationMovePlan(null);
    try {
      await executeAction({ action: "cancel_consolidation" });
    } catch (e) {
      console.error("Cancel consolidation model move failed:", e);
    }
    setSelectedUnitId(null);
    setMode("select");
  }, [executeAction]);

  /** Bouton « Terminer la consolidation » : marque le groupe traité (end_consolidation). */
  const handleEndConsolidation = useCallback(async () => {
    consolidationModelPoolRef.current = new Set();
    consolidationModelMaskLoopsRef.current = null;
    setConsolidationFocusMode(null);
    setConsolidationMovePlan(null);
    try {
      await executeAction({ action: "end_consolidation" });
    } catch (e) {
      console.error("End consolidation failed:", e);
    }
    setSelectedUnitId(null);
    setMode("select");
  }, [executeAction]);

  const handleStartTargetPreview = useCallback(
    async (shooterId: number | string, targetId: number | string) => {
      const numericShooterId = typeof shooterId === "number" ? shooterId : parseInt(shooterId, 10);
      const numericTargetId = typeof targetId === "number" ? targetId : parseInt(targetId, 10);

      // Send backend action to trigger target selection and blinking response
      await executeAction({
        action: "left_click",
        unitId: numericShooterId.toString(),
        targetId: numericTargetId.toString(),
        clickTarget: "enemy",
      });

      // Calculate actual probabilities using game units
      // Handle both string and number IDs
      const shooter = gameState?.units.find((u) => {
        const unitId = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
        return unitId === numericShooterId;
      });
      const target = gameState?.units.find((u) => {
        const unitId = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
        return unitId === numericTargetId;
      });

      if (!shooter || !target) {
        throw new Error(
          `Cannot build target preview: shooter (${numericShooterId}) or target (${numericTargetId}) not found in game_state`
        );
      }
      // Arme à feu sélectionnée (alignée sur HP blink / tir effectif)
      // Convert shooter to proper Unit type (id as number, player as PlayerId)
      const shooterUnit: Unit = {
        ...shooter,
        id: typeof shooter.id === "string" ? parseInt(shooter.id, 10) : shooter.id,
        player: shooter.player as PlayerId,
      };
      const targetUnit: Unit = {
        ...target,
        id: typeof target.id === "string" ? parseInt(target.id, 10) : target.id,
        player: target.player as PlayerId,
      };
      const rangedEff = getSelectedRangedWeaponAgainstTarget(shooterUnit, targetUnit);
      if (!rangedEff) {
        throw new Error(
          `No ranged weapon available for unit ${shooterUnit.id} when starting target preview`
        );
      }

      const hitProbability = rangedEff.hitProbability;
      const woundProbability = rangedEff.woundProbability;
      const saveProbability = rangedEff.saveProbability;
      const potentialDamage = rangedEff.potentialDamage;

      const overallProbability = hitProbability * woundProbability * (1 - saveProbability);
      const expectedDamage = overallProbability * potentialDamage;

      // Create target preview with blinking animation
      const preview = {
        shooterId: numericShooterId,
        targetId: numericTargetId,
        currentBlinkStep: 0,
        totalBlinkSteps: 2,
        blinkTimer: null as number | null,
        hitProbability,
        woundProbability,
        saveProbability,
        overallProbability,
        potentialDamage,
        expectedDamage,
      };

      // Start blinking animation with functional state updates
      preview.blinkTimer = window.setInterval(() => {
        setTargetPreview((prevPreview) => {
          if (!prevPreview) return null;
          const newStep =
            ((prevPreview.currentBlinkStep || 0) + 1) % (prevPreview.totalBlinkSteps || 2);
          return {
            ...prevPreview,
            currentBlinkStep: newStep,
            lastUpdate: Date.now(),
          };
        });
      }, 500);

      setTargetPreview(preview);
      setMode("targetPreview");
    },
    [gameState, executeAction]
  );

  // Cleanup interval when targetPreview changes or component unmounts
  useEffect(() => {
    return () => {
      if (targetPreview?.blinkTimer) {
        clearInterval(targetPreview.blinkTimer);
      }
    };
  }, [targetPreview?.blinkTimer]);

  // Get eligible units
  const getEligibleUnitIds = useCallback((): number[] => {
    if (!gameState) {
      throw new Error(`API ERROR: gameState is null when getting eligible units`);
    }

    if (gameState.phase === "deployment") {
      if (!gameState.deployment_state) {
        throw new Error(`API ERROR: Missing deployment_state in deployment phase`);
      }
      const currentDeployer = gameState.deployment_state.current_deployer;
      const pool = gameState.deployment_state.deployable_units[String(currentDeployer)];
      if (!pool) {
        return [];
      }
      return pool.map((id) => parseInt(id, 10)).filter((id) => !Number.isNaN(id));
    } else if (gameState.phase === "command") {
      // Command phase: empty pool for now, ready for future
      return [];
    } else if (gameState.phase === "move") {
      if (!gameState.move_activation_pool) {
        throw new Error(`API ERROR: Missing move_activation_pool in move phase`);
      }
      return gameState.move_activation_pool
        .map((id) => parseInt(id, 10))
        .filter((id) => !Number.isNaN(id));
    } else if (gameState.phase === "shoot") {
      if (!gameState.shoot_activation_pool || gameState.shoot_activation_pool.length === 0) {
        return []; // Empty pool is valid - let backend handle phase advancement
      }
      return gameState.shoot_activation_pool
        .map((id) => parseInt(id, 10))
        .filter((id) => !Number.isNaN(id));
    } else if (gameState.phase === "charge") {
      if (!gameState.charge_activation_pool || gameState.charge_activation_pool.length === 0) {
        return []; // Empty pool is valid - phase will auto-advance
      }
      const eligible = gameState.charge_activation_pool
        .map((id) => parseInt(id, 10))
        .filter((id) => !Number.isNaN(id));
      return eligible;
    } else if (gameState.phase === "fight") {
      // V11 : pool actionnable unique exposé par le moteur (pile_in/fight/consolidate).
      const pool = gameState.fight_eligible_units;
      if (!pool) {
        return [];
      }
      return pool.map((id) => parseInt(String(id), 10)).filter((id) => !Number.isNaN(id));
    }

    throw new Error(`API ERROR: Unsupported phase for eligible units: ${gameState.phase}`);
  }, [gameState]);

  const getChargeDestinations = useCallback(() => {
    return chargeDestinations;
  }, [chargeDestinations]);

  // Return props compatible with BoardPvp
  if (error) {
    throw new Error(`API ERROR: ${error}`);
  }

  // Memoize blinkingUnits from activation responses; move hover LoS is owned by BoardPvp.
  const blinkingUnitsIds = useMemo(() => {
    return [...blinkingUnits.unitIds].sort((a, b) => a - b);
  }, [blinkingUnits.unitIds]);

  const moveSelectionCellsOverride = useMemo(() => {
    if (
      gameState?.phase === "shoot" &&
      mode === "select" &&
      pendingPreviewAction === "move_after_shooting" &&
      postShootMoveDestinations.length > 0
    ) {
      return postShootMoveDestinations;
    }
    return undefined;
  }, [gameState?.phase, mode, pendingPreviewAction, postShootMoveDestinations]);

  const pileInCellsOverride = useMemo(() => {
    if (gameState?.phase === "fight" && mode === "pileInPreview") {
      if (pileInDestinations.length > 0) {
        return pileInDestinations;
      }
    }
    if (gameState?.phase === "fight" && mode === "consolidationPreview") {
      if (pileInDestinations.length > 0) {
        return pileInDestinations;
      }
    }
    return undefined;
  }, [gameState?.phase, mode, pileInDestinations]);

  const combinedAvailableCellsOverride = useMemo(() => {
    return pileInCellsOverride ?? moveSelectionCellsOverride;
  }, [pileInCellsOverride, moveSelectionCellsOverride]);

  // Memoize isBlinkingActive to prevent re-renders when only blinkState toggles
  const isBlinkingActiveMemo = useMemo(() => {
    return blinkingUnits.blinkTimer !== null;
  }, [blinkingUnits.blinkTimer]);

  // Memoize units conversion to prevent unnecessary re-renders
  const memoizedUnits = useMemo(() => {
    return convertUnits(gameState?.units || []);
  }, [gameState?.units, convertUnits]);

  // Memoize derived arrays to prevent unnecessary re-renders
  const memoizedUnitsMoved = useMemo(() => {
    return gameState?.units_moved ? gameState.units_moved.map((id) => parseInt(id, 10)) : [];
  }, [gameState?.units_moved]);

  const memoizedUnitsCharged = useMemo(() => {
    return gameState?.units_charged ? gameState.units_charged.map((id) => parseInt(id, 10)) : [];
  }, [gameState?.units_charged]);

  const memoizedUnitsAttacked = useMemo(() => {
    return gameState?.units_attacked ? gameState.units_attacked.map((id) => parseInt(id, 10)) : [];
  }, [gameState?.units_attacked]);

  const memoizedUnitsFled = useMemo(() => {
    return gameState?.units_fled ? gameState.units_fled.map((id) => parseInt(id, 10)) : [];
  }, [gameState?.units_fled]);

  const memoizedUnitsAdvanced = useMemo((): number[] => {
    return gameState?.units_advanced ? gameState.units_advanced.map((id) => parseInt(id, 10)) : [];
  }, [gameState?.units_advanced]);

  const memoizedUnitsTookToSkies = useMemo((): number[] => {
    return gameState?.units_took_to_skies
      ? gameState.units_took_to_skies.map((id) => parseInt(id, 10))
      : [];
  }, [gameState?.units_took_to_skies]);

  const memoizedUnitsTookToSkiesCharge = useMemo((): number[] => {
    return gameState?.units_took_to_skies_charge
      ? gameState.units_took_to_skies_charge.map((id) => parseInt(id, 10))
      : [];
  }, [gameState?.units_took_to_skies_charge]);

  const memoizedDeploymentState = useMemo(() => {
    if (!gameState?.deployment_state) {
      return undefined;
    }

    const rawDeployer = Number(gameState.deployment_state.current_deployer);
    if (rawDeployer !== 1 && rawDeployer !== 2) {
      throw new Error(
        `Invalid deployment current_deployer: ${gameState.deployment_state.current_deployer}`
      );
    }
    const currentDeployer = rawDeployer as PlayerId;

    const deployableUnits = Object.fromEntries(
      Object.entries(gameState.deployment_state.deployable_units).map(([playerKey, unitIds]) => {
        const parsedUnitIds = unitIds.map((id) => {
          const parsed = parseInt(String(id), 10);
          if (Number.isNaN(parsed)) {
            throw new Error(`Invalid deployable unit id in deployment_state: ${id}`);
          }
          return parsed;
        });
        return [playerKey, parsedUnitIds];
      })
    );

    const deployedUnits = gameState.deployment_state.deployed_units.map((id) => {
      const parsed = parseInt(String(id), 10);
      if (Number.isNaN(parsed)) {
        throw new Error(`Invalid deployed unit id in deployment_state: ${id}`);
      }
      return parsed;
    });

    return {
      current_deployer: currentDeployer,
      deployable_units: deployableUnits,
      deployed_units: deployedUnits,
      deployment_pools: gameState.deployment_state.deployment_pools,
      deployment_complete: gameState.deployment_state.deployment_complete,
    };
  }, [gameState?.deployment_state]);

  // Memoize inline callbacks to prevent re-renders
  const onStartAttackPreviewMemo = useCallback((unitId: number) => {
    setSelectedUnitId(typeof unitId === "string" ? parseInt(unitId, 10) : unitId);
    setAttackPreview(null);
    setMode("attackPreview");
  }, []);

  const emptyCallback = useCallback(() => {}, []);
  const getAdvanceDestinationsMemo = useCallback(
    (_unitId: number) => advanceDestinations,
    [advanceDestinations]
  );

  // Memoize gameState to prevent re-renders when content hasn't changed
  const memoizedGameState = useMemo(() => {
    if (!gameState) return null;
    return {
      episode_steps: gameState.episode_steps,
      units: memoizedUnits,
      current_player: gameState.current_player as PlayerId,
      phase: gameState.phase as "deployment" | "move" | "shoot" | "charge" | "fight",
      mode,
      selectedUnitId,
      unitsMoved: memoizedUnitsMoved,
      unitsCharged: memoizedUnitsCharged,
      unitsAttacked: memoizedUnitsAttacked,
      unitsFled: memoizedUnitsFled,
      unitsAdvanced: memoizedUnitsAdvanced,
      unitsTookToSkies: memoizedUnitsTookToSkies,
      unitsTookToSkiesCharge: memoizedUnitsTookToSkiesCharge,
      targetPreview: null,
      currentTurn: gameState.turn,
      maxTurns: maxTurnsFromConfig as number,
      unitChargeRolls: {},
      pve_mode: gameState.pve_mode,
      player_types: gameState.player_types,
      deployment_type: gameState.deployment_type,
      deployment_state: memoizedDeploymentState,
      move_activation_pool: gameState.move_activation_pool,
      shoot_activation_pool: gameState.shoot_activation_pool,
      charge_activation_pool: gameState.charge_activation_pool,
      fight_subphase: gameState.fight_subphase as
        | "pile_in"
        | "fight"
        | "consolidate"
        | null
        | undefined,
      fight_eligible_units: gameState.fight_eligible_units,
      active_movement_unit: gameState.active_movement_unit,
      /** Requis pour sync moveDestPoolRef / cercles d’ancre (sinon seul move_preview_footprint_zone → « hex géant »). */
      valid_move_destinations_pool: gameState.valid_move_destinations_pool,
      move_preview_footprint_span: (gameState as { move_preview_footprint_span?: number | null })
        .move_preview_footprint_span,
      preview_hexes: (gameState as { preview_hexes?: unknown }).preview_hexes,
      move_preview_border: gameState.move_preview_border,
      move_preview_footprint_zone: gameState.move_preview_footprint_zone,
      move_preview_footprint_mask_loops: (
        gameState as { move_preview_footprint_mask_loops?: unknown }
      ).move_preview_footprint_mask_loops,
      fight_pile_in_footprint_zone: gameState.fight_pile_in_footprint_zone,
      fight_pile_in_footprint_mask_loops: gameState.fight_pile_in_footprint_mask_loops,
      fight_consolidation_footprint_zone: gameState.fight_consolidation_footprint_zone,
      fight_consolidation_footprint_mask_loops: gameState.fight_consolidation_footprint_mask_loops,
      active_shooting_unit: gameState.active_shooting_unit,
      active_fight_unit: gameState.active_fight_unit,
      units_cache: gameState.units_cache,
      victory_points: gameState.victory_points,
      primary_objective: gameState.primary_objective,
      objectives: gameState.objectives,
      game_over: gameState.game_over,
      winner: gameState.winner,
      pending_rule_choice_queue: gameState.pending_rule_choice_queue,
      active_rule_choice_prompt: gameState.active_rule_choice_prompt,
    };
  }, [
    gameState,
    memoizedUnits,
    mode,
    selectedUnitId,
    memoizedUnitsMoved,
    memoizedUnitsCharged,
    memoizedUnitsAttacked,
    memoizedUnitsFled,
    memoizedUnitsAdvanced,
    memoizedUnitsTookToSkies,
    memoizedUnitsTookToSkiesCharge,
    memoizedDeploymentState,
    maxTurnsFromConfig,
  ]);

  if (loading || !gameState || maxTurnsFromConfig === null) {
    const blinkBoardPropsIdle: UseEngineAPIBlinkBoardProps = {
      blinkingUnits: [],
      blinkingAttackerId: null,
      blinkingCoverByUnitId: undefined,
      blinkingHiddenTooFarByUnitId: undefined,
      blinkingLosCountByUnitId: undefined,
      blinkingSquadAliveCount: undefined,
      blinkingLosOverviewUnitId: null,
      isBlinkingActive: false,
      blinkVersion: 0,
    };
    return {
      loading: true,
      error: null,
      units: [],
      selectedUnitId: null,
      eligibleUnitIds: [],
      mode: "select" as const,
      movePreview: null,
      attackPreview: null,
      targetPreview: null,
      current_player: null,
      maxTurns: null,
      unitsMoved: [],
      unitsCharged: [],
      unitsAttacked: [],
      unitsFled: [],
      unitsAdvanced: [] as number[],
      unitsTookToSkies: [] as number[],
      unitsTookToSkiesCharge: [] as number[],
      phase: null,
      gameState: null,
      onSelectUnit: () => {},
      onSkipUnit: () => {},
      onEndPhase: async () => {},
      onStartMovePreview: () => {},
      onDirectMove: () => {},
      onBumpMovePreviewOrientation: () => {},
      squadMovePlan: null,
      fleePreviewUnitId: null,
      squadMoveModelPoolRef,
      squadMoveModelMaskLoopsRef,
      onStartSquadModelMove: async () => {},
      onSelectModelForMove: async () => {},
      onMoveModelInPlan: () => {},
      onResetModelInPlan: () => {},
      onCommitSquadMovePlan: async () => {},
      onCancelSquadMove: () => {},
      chargeMovePlan: null,
      chargeFocusActive: false,
      chargeModelPoolRef,
      chargeModelDistancesRef, // A SUPPRIMER (feature charge par-fig morte)
      chargeModelMaskLoopsRef,
      onSelectChargeModel: () => {},
      onMoveModelInChargePlan: () => {},
      onUnplaceChargeModel: () => {},
      onCommitChargePlan: async () => {},
      onCancelChargeModelMove: async () => {},
      onToggleChargeFocus: () => {},
      onChargeFocusTargetClick: async () => {},
      chargeFocusMode: null as null | "offensive" | "defensive",
      onChargeAutoplace: async (_mode: "offensive" | "defensive") => {},
      pileInMovePlan: null,
      pileInFocusActive: false,
      pileInFocusMode: null as null | "defensive" | "offensive",
      pileInFocusTargetId: null as string | null,
      pileInModelPoolRef,
      pileInModelMaskLoopsRef,
      onSelectPileInModel: () => {},
      onMovePileInModel: () => {},
      onUnplacePileInModel: () => {},
      onEndPileIn: () => {},
      onSkipFight: () => {},
      onCommitPileInPlan: async () => {},
      onCancelPileInModelMove: async () => {},
      onSetPileInFocus: (_mode: "defensive" | "offensive") => {},
      onPileInFocusTargetClick: async () => {},
      consolidationMovePlan: null,
      consolidationModelPoolRef,
      consolidationModelMaskLoopsRef,
      consolidationNewFoes: [] as string[],
      consolidationFocusMode: null as null | "defensive" | "offensive",
      onSetConsolidationFocus: (_mode: "defensive" | "offensive") => {},
      onSelectConsolidationModel: () => {},
      onMoveConsolidationModel: () => {},
      onUnplaceConsolidationModel: () => {},
      onCommitConsolidationPlan: async () => {},
      onCancelConsolidationModelMove: async () => {},
      onEndConsolidation: async () => {},
      onConsolidationSelectTarget: async () => {},
      onConsolidationSelectObjective: async () => {},
      onSetAdvanceMode: async () => {},
      onTakeToSkies: async () => {},
      onStationary: async () => {},
      onForceBattleShock: async () => {},
      onForceCharged: async () => {},
      activeUnitEngaged: null,
      squadShootPlan: null,
      onStartSquadModelShoot: async () => {},
      onSelectModelForShoot: async () => {},
      onSquadShootLosOverview: async () => {},
      onAssignShootTarget: async () => {},
      onAutoAssignAllModels: async () => {},
      onUnassignShootModel: async () => {},
      onUnassignShootWeapon: async () => {},
      onCommitSquadShoot: async () => {},
      onCancelSquadShoot: async () => {},
      squadFightPlan: null,
      onSelectModelForFight: () => {},
      onAssignFightTarget: async () => {},
      onAssignFightWeapon: async () => {},
      onCommitSquadFight: async () => {},
      onCancelSquadFight: async () => {},
      fightAssignableCount: 0,
      onReportFightAssignable: () => {},
      manualAllocation: null,
      onAllocateModel: async () => {},
      manualOrderRequest: null,
      onDeclareOrder: async () => {},
      onStartAttackPreview: () => {},
      onConfirmMove: () => {},
      onCancelMove: () => {},
      onCancelAdvance: () => {},
      onAdvanceMove: async () => {},
      onShoot: () => {},
      onSkipShoot: () => {},
      onDeployUnit: async () => {},
      listArmies: async () => [],
      changeRoster: async () => {},
      onStartTargetPreview: () => {},
      onFightAttack: () => {},
      onFightPhaseRightClick: async () => {},
      onActivateFight: () => {},
      onPileInMove: async () => {},
      onSkipPileIn: async () => {},
      onCharge: () => {},
      onActivateCharge: () => {},
      onMoveCharger: () => {},
      onChargeEnemyUnit: async () => {},
      onCancelCharge: () => {},
      onValidateCharge: () => {},
      onLogChargeRoll: () => {},
      getChargeDestinations: () => [],
      chargePreviewOverlayHexes: [],
      chargeReferenceHex: null,
      moveDestPoolRef,
      footprintZoneRef,
      footprintMaskLoopsRef,
      chargeDestPoolRef,
      chargeDestDistancesRef,
      chargeFootprintZoneRef,
      pendingMoveAfterShooting: false,
      activationPendingUnitId: null,
      chargingUnitId: null,
      chargeTargetId: null,
      chargeRoll: null,
      chargeSuccess: undefined,
      onAdvance: async () => {},
      getAdvanceDestinations: () => [],
      advancingUnitId: null,
      advanceRoll: null,
      advanceWarningPopup: null,
      onConfirmAdvanceWarning: async () => {},
      onCancelAdvanceWarning: () => {},
      onSkipAdvanceWarning: async () => {},
      fleeWarningPopup: null,
      onConfirmFleeWarning: async () => {},
      onCancelFleeWarning: async () => {},
      onToggleFleeWarningDontRemind: () => {},
      hazardWarningPopup: null,
      onConfirmHazardWarning: async () => {},
      onCancelHazardWarning: () => {},
      battleShockTestMode: false,
      onToggleBattleShockTestMode: () => {},
      chargedTestMode: false,
      onToggleChargedTestMode: () => {},
      availableCellsOverride: undefined,
      chargePreviewTargetIds: [],
      ...blinkBoardPropsIdle,
      ruleChoicePrompt: null,
      onSelectRuleChoice: async (_prompt: RuleChoicePrompt, _selectedDisplayRuleId: string) => {},
      // blinkState removed - blinking is handled locally in UnitRenderer
      fightSubPhase: null,
      executeAITurn: async () => {},
      startGameWithScenario: async () => {},
      startPveGame: async () => {},
      startPvpGame: async () => {},
      endlessDutyState: null,
      fetchEndlessDutyStatus: async () => null,
      commitEndlessDuty: async () => {},
    };
  }

  // Normal case
  const blinkBoardPropsReady: UseEngineAPIBlinkBoardProps = {
    blinkingUnits: blinkingUnitsIds,
    blinkingAttackerId: blinkingUnits.attackerId ?? null,
    blinkingCoverByUnitId: blinkingUnits.coverByUnitId,
    blinkingHiddenTooFarByUnitId: blinkingUnits.hiddenTooFarByUnitId,
    blinkingLosCountByUnitId: blinkingUnits.losCountByUnitId,
    blinkingSquadAliveCount: blinkingUnits.squadAliveCount,
    blinkingLosOverviewUnitId: blinkingUnits.losOverviewUnitId ?? null,
    isBlinkingActive: isBlinkingActiveMemo,
    blinkVersion,
  };
  const returnObject = {
    loading: false,
    error: null,
    units: memoizedUnits,
    selectedUnitId,
    eligibleUnitIds: getEligibleUnitIds(),
    mode,
    movePreview,
    attackPreview,
    targetPreview,
    current_player: gameState.current_player as PlayerId,
    maxTurns: maxTurnsFromConfig as number,
    unitsMoved: memoizedUnitsMoved,
    unitsCharged: memoizedUnitsCharged,
    unitsAttacked: memoizedUnitsAttacked,
    unitsFled: memoizedUnitsFled,
    unitsAdvanced: memoizedUnitsAdvanced,
    unitsTookToSkies: memoizedUnitsTookToSkies,
    unitsTookToSkiesCharge: memoizedUnitsTookToSkiesCharge,
    phase: gameState.phase as "deployment" | "move" | "shoot" | "charge" | "fight",
    // Expose fight_subphase for UnitRenderer click handling
    fightSubPhase: gameState.fight_subphase as "pile_in" | "fight" | "consolidate" | null,
    gameState: memoizedGameState,
    onSelectUnit: handleSelectUnit,
    onSkipUnit: handleSkipUnit,
    onEndPhase: handleEndPhase,
    onStartMovePreview: handleStartMovePreview,
    onDirectMove: handleDirectMove,
    onBumpMovePreviewOrientation: handleBumpMovePreviewOrientation,
    // Move par-figurine (squad.md brique 3)
    squadMovePlan,
    fleePreviewUnitId,
    squadMoveModelPoolRef,
    squadMoveModelMaskLoopsRef,
    onStartSquadModelMove: handleStartSquadModelMove,
    onSelectModelForMove: handleSelectModelForMove,
    onMoveModelInPlan: handleMoveModelInPlan,
    onResetModelInPlan: handleResetModelInPlan,
    onCommitSquadMovePlan: handleCommitSquadMovePlan,
    onCancelSquadMove: handleCancelSquadMove,
    // Charge par-figurine (V11 11.04, Slice G)
    chargeMovePlan,
    chargeFocusActive,
    chargeModelPoolRef,
    chargeModelDistancesRef, // A SUPPRIMER (feature charge par-fig morte)
    chargeModelMaskLoopsRef,
    onSelectChargeModel: handleSelectChargeModel,
    onMoveModelInChargePlan: handleMoveModelInChargePlan,
    onUnplaceChargeModel: handleUnplaceChargeModel,
    onCommitChargePlan: handleCommitChargePlan,
    onCancelChargeModelMove: handleCancelChargeModelMove,
    onToggleChargeFocus: handleToggleChargeFocus,
    onChargeFocusTargetClick: handleChargeFocusTargetClick,
    chargeFocusMode,
    onChargeAutoplace: handleChargeAutoplace,
    // Pile-in par-figurine (V11 12.04, mode fin type charge)
    pileInMovePlan,
    pileInFocusActive: pileInFocusMode != null,
    pileInFocusMode,
    pileInFocusTargetId,
    pileInModelPoolRef,
    pileInModelMaskLoopsRef,
    onSelectPileInModel: handleSelectPileInModel,
    onMovePileInModel: handleMovePileInModel,
    onUnplacePileInModel: handleUnplacePileInModel,
    onCommitPileInPlan: handleCommitPileInPlan,
    onCancelPileInModelMove: handleCancelPileInModelMove,
    onSetPileInFocus: handleSetPileInFocus,
    onPileInFocusTargetClick: handlePileInFocusTargetClick,
    // Consolidation par-figurine (V11 12.08, miroir pile-in)
    consolidationMovePlan,
    consolidationModelPoolRef,
    consolidationModelMaskLoopsRef,
    consolidationNewFoes,
    consolidationFocusMode,
    onSetConsolidationFocus: handleSetConsolidationFocus,
    onSelectConsolidationModel: handleSelectConsolidationModel,
    onMoveConsolidationModel: handleMoveConsolidationModel,
    onUnplaceConsolidationModel: handleUnplaceConsolidationModel,
    onCommitConsolidationPlan: handleCommitConsolidationPlan,
    onCancelConsolidationModelMove: handleCancelConsolidationModelMove,
    onEndConsolidation: handleEndConsolidation,
    onConsolidationSelectTarget: handleConsolidationSelectTarget,
    onConsolidationSelectObjective: handleConsolidationSelectObjective,
    onSetAdvanceMode: handleSetAdvanceMode,
    onTakeToSkies: handleTakeToSkies,
    onStationary: handleStationary,
    onForceBattleShock: handleForceBattleShock,
    onForceCharged: handleForceCharged,
    activeUnitEngaged,
    squadShootPlan,
    onStartSquadModelShoot: handleStartSquadModelShoot,
    onSelectModelForShoot: handleSelectModelForShoot,
    onSquadShootLosOverview: handleSquadShootLosOverview,
    onAssignShootTarget: handleAssignShootTarget,
    onAutoAssignAllModels: handleAutoAssignAllModels,
    onUnassignShootModel: handleUnassignShootModel,
    onUnassignShootWeapon: handleUnassignShootWeapon,
    onCommitSquadShoot: handleCommitSquadShoot,
    onCancelSquadShoot: handleCancelSquadShoot,
    squadFightPlan,
    onSelectModelForFight: handleSelectModelForFight,
    onAssignFightTarget: handleAssignFightTarget,
    onAssignFightWeapon: handleAssignFightWeapon,
    onCommitSquadFight: handleCommitSquadFight,
    onCancelSquadFight: handleCancelSquadFight,
    fightAssignableCount,
    onReportFightAssignable: handleReportFightAssignable,
    manualAllocation,
    onAllocateModel: handleAllocateModel,
    manualOrderRequest,
    onDeclareOrder: handleDeclareOrder,
    onStartAttackPreview: onStartAttackPreviewMemo,
    onConfirmMove: handleConfirmMove,
    onCancelMove: handleCancelMove,
    onShoot: handleShoot,
    onSkipShoot: handleSkipShoot,
    onDeployUnit: handleDeployUnit,
    listArmies,
    changeRoster,
    onStartTargetPreview: handleStartTargetPreview,
    onFightAttack: handleFightAttack,
    onFightPhaseRightClick: handleRightClick,
    onActivateFight: handleActivateFight,
    onPileInMove: handlePileInMove,
    onSkipPileIn: handleSkipPileIn,
    onEndPileIn: handleEndPileIn,
    onSkipFight: handleSkipFight,
    onCharge: emptyCallback,
    onActivateCharge: handleActivateCharge,
    onChargeEnemyUnit: handleChargeEnemyUnit,
    onMoveCharger: handleMoveCharger,
    onAdvanceMove: handleAdvanceMove,
    onCancelCharge: handleCancelCharge,
    onValidateCharge: handleValidateCharge,
    onLogChargeRoll: emptyCallback,
    getChargeDestinations,
    chargePreviewOverlayHexes,
    chargeReferenceHex,
    moveDestPoolRef,
    footprintZoneRef,
    footprintMaskLoopsRef,
    chargeDestDistancesRef,
    chargeDestPoolRef,
    chargeFootprintZoneRef,
    pendingMoveAfterShooting: pendingPreviewAction === "move_after_shooting",
    activationPendingUnitId,
    // ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Export advance state and handler
    getAdvanceDestinations: getAdvanceDestinationsMemo,
    advancingUnitId,
    advanceRoll,
    onAdvance: handleAdvance,
    onCancelAdvance: handleCancelAdvance,
    advanceWarningPopup,
    onConfirmAdvanceWarning: handleConfirmAdvanceWarning,
    onCancelAdvanceWarning: handleCancelAdvanceWarning,
    onSkipAdvanceWarning: handleSkipAdvanceWarning,
    fleeWarningPopup,
    onConfirmFleeWarning: handleConfirmFleeWarning,
    onCancelFleeWarning: handleCancelFleeWarning,
    onToggleFleeWarningDontRemind: handleToggleFleeWarningDontRemind,
    hazardWarningPopup,
    onConfirmHazardWarning: handleConfirmHazardWarning,
    onCancelHazardWarning: handleCancelHazardWarning,
    battleShockTestMode,
    onToggleBattleShockTestMode: handleToggleBattleShockTestMode,
    chargedTestMode,
    onToggleChargedTestMode: handleToggleChargedTestMode,
    availableCellsOverride: combinedAvailableCellsOverride,
    // Export blinking state for HP bar components
    ...blinkBoardPropsReady,
    ruleChoicePrompt,
    onSelectRuleChoice: handleSelectRuleChoice,
    // blinkState removed - blinking is handled locally in UnitRenderer
    // Export charge roll info for failed charge display
    chargingUnitId: failedChargeRoll
      ? failedChargeRoll.unitId
      : pendingChargeRollDisplay
        ? pendingChargeRollDisplay.unitId
        : null,
    chargeRoll: failedChargeRoll
      ? failedChargeRoll.roll
      : pendingChargeRollDisplay
        ? pendingChargeRollDisplay.roll
        : null,
    chargeSuccess: failedChargeRoll ? false : pendingChargeRollDisplay ? true : undefined,
    // Export charge target ID for target icon display (for both successful and failed charges)
    chargeTargetId: (() => {
      const targetId =
        chargePreviewTargetId ??
        failedChargeRoll?.targetId ??
        successfulChargeTarget?.targetId ??
        null;
      return targetId;
    })(),
    // V11 multi-cibles : cibles toggleées en mode chargeTargetSelect (voile violet + activation bouton Charge)
    chargePreviewTargetIds,
    // Add AI turn execution for PvE mode
    executeAITurn: async (options?: { stopAfterPhaseChange?: boolean }) => {
      if (aiTurnInProgress) {
        return;
      }
      aiTurnInProgress = true;

      const stopAfterPhase =
        options?.stopAfterPhaseChange ?? stopAiAfterPhaseChangeRef?.current ?? false;

      // Check if AI has eligible units in current phase FIRST
      const phaseCheck = gameState.phase;

      if (!gameState) {
        aiTurnInProgress = false;
        return;
      }
      const playerTypes = gameState.player_types;
      if (!playerTypes) {
        throw new Error("Missing player_types in gameState");
      }
      const getPlayerType = (playerId: number): "human" | "ai" => {
        const playerType = playerTypes[String(playerId)];
        if (!playerType) {
          throw new Error(`Missing player type for player ${playerId}`);
        }
        return playerType;
      };
      const isAiUnitInState = (state: APIGameState, unitId: string | number): boolean => {
        const statePlayerTypes = state.player_types;
        if (!statePlayerTypes) {
          throw new Error("Missing player_types in state while evaluating AI unit");
        }
        const unit = state.units.find((u) => String(u.id) === String(unitId));
        if (!unit) {
          throw new Error(`Missing unit ${String(unitId)} in state while evaluating AI unit`);
        }
        const unitPlayerType = statePlayerTypes[String(unit.player)];
        if (!unitPlayerType) {
          throw new Error(`Missing player type for player ${unit.player}`);
        }
        return unitPlayerType === "ai";
      };
      const isAiUnitId = (unitId: string | number): boolean => {
        return isAiUnitInState(gameState, unitId);
      };

      // CRITICAL: In fight phase, current_player can be 1 but AI can still act in alternating phase
      // Only check current_player for non-fight phases
      if (phaseCheck !== "fight" && getPlayerType(gameState.current_player) !== "ai") {
        aiTurnInProgress = false;
        return;
      }
      let eligibleAICount = 0;

      if (phaseCheck === "deployment") {
        const deploymentState = gameState.deployment_state;
        if (!deploymentState) {
          aiTurnInProgress = false;
          return;
        }
        const deployer = deploymentState.current_deployer;
        const pool = deploymentState.deployable_units?.[String(deployer)];
        if (!pool) {
          throw new Error(`deployment: deployable_units missing for deployer ${String(deployer)}`);
        }
        eligibleAICount = getPlayerType(deployer) === "ai" ? pool.length : 0;
      } else if (phaseCheck === "shoot" && gameState.shoot_activation_pool) {
        const shootPool = gameState.shoot_activation_pool || [];
        eligibleAICount = shootPool.filter((unitId) => isAiUnitId(unitId)).length;
      } else if (phaseCheck === "move" && gameState.move_activation_pool) {
        eligibleAICount = gameState.move_activation_pool.filter((unitId) =>
          isAiUnitId(unitId)
        ).length;
      } else if (phaseCheck === "charge" && gameState.charge_activation_pool) {
        eligibleAICount = gameState.charge_activation_pool.filter((unitId) =>
          isAiUnitId(unitId)
        ).length;
      } else if (phaseCheck === "fight") {
        // V11 : pool actionnable unique exposé par le moteur (pile_in/fight/consolidate).
        const fightPool: string[] = (gameState.fight_eligible_units ?? []).map((id) => String(id));
        eligibleAICount = fightPool.filter((unitId) => isAiUnitId(unitId)).length;
      }

      if (eligibleAICount === 0) {
        aiTurnInProgress = false;
        return;
      }

      // Check if AI has eligible units in current phase (already checked above, but keeping for clarity)
      const currentPhase = gameState.phase;
      let aiEligibleUnits = 0;

      if (currentPhase === "deployment") {
        const deploymentState = gameState.deployment_state;
        if (!deploymentState) {
          aiEligibleUnits = 0;
        } else {
          const deployer = deploymentState.current_deployer;
          const pool = deploymentState.deployable_units?.[String(deployer)];
          if (!pool) {
            throw new Error(
              `deployment: deployable_units missing for deployer ${String(deployer)}`
            );
          }
          aiEligibleUnits = getPlayerType(deployer) === "ai" ? pool.length : 0;
        }
      } else if (currentPhase === "move" && gameState.move_activation_pool) {
        aiEligibleUnits = gameState.move_activation_pool.filter((unitId) =>
          isAiUnitId(unitId)
        ).length;
      } else if (currentPhase === "shoot" && gameState.shoot_activation_pool) {
        const shootPool = gameState.shoot_activation_pool || [];
        aiEligibleUnits = shootPool.filter((unitId) => isAiUnitId(unitId)).length;
      } else if (currentPhase === "charge" && gameState.charge_activation_pool) {
        aiEligibleUnits = gameState.charge_activation_pool.filter((unitId) =>
          isAiUnitId(unitId)
        ).length;
      } else if (currentPhase === "fight") {
        // V11 : pool actionnable unique exposé par le moteur (pile_in/fight/consolidate).
        const fightPool: string[] = (gameState.fight_eligible_units ?? []).map((id) => String(id));
        aiEligibleUnits = fightPool.filter((unitId) => isAiUnitId(unitId)).length;
      }

      if (aiEligibleUnits === 0) {
        aiTurnInProgress = false;
        return;
      }

      // Helper function to make AI movement decision
      const makeMovementDecision = (
        validDestinations: number[][],
        unitId: string,
        currentGameState: APIGameState
      ) => {
        if (!validDestinations || validDestinations.length === 0) {
          return { action: "skip", unitId };
        }

        // Find nearest enemy using fresh unit positions
        const currentUnit = currentGameState?.units.find((u) => u.id.toString() === unitId);
        if (!currentUnit) {
          const dest = validDestinations[0];
          return {
            action: "move",
            unitId,
            destCol: dest[0],
            destRow: dest[1],
          };
        }
        // Strategy: Move toward nearest enemy using FRESH game state
        const enemies = currentGameState.units.filter(
          (u) => u.player !== currentUnit.player && u.HP_CUR > 0
        );
        if (enemies.length === 0) {
          const dest = validDestinations[0];
          return {
            action: "move",
            unitId,
            destCol: dest[0],
            destRow: dest[1],
          };
        }

        // CRITICAL FIX: Use proper hex distance calculation (cubeDistance from gameHelpers)
        const nearestEnemy = enemies.reduce((nearest, enemy) => {
          const distToCurrent = cubeDistance(
            offsetToCube(currentUnit.col, currentUnit.row),
            offsetToCube(enemy.col, enemy.row)
          );
          const distToNearest = cubeDistance(
            offsetToCube(currentUnit.col, currentUnit.row),
            offsetToCube(nearest.col, nearest.row)
          );
          return distToCurrent < distToNearest ? enemy : nearest;
        });

        // Pick destination closest to nearest enemy FROM VALID DESTINATIONS ONLY
        const bestDestination = validDestinations.reduce((best, dest) => {
          const distToEnemy = cubeDistance(
            offsetToCube(dest[0], dest[1]),
            offsetToCube(nearestEnemy.col, nearestEnemy.row)
          );
          const bestDistToEnemy = cubeDistance(
            offsetToCube(best[0], best[1]),
            offsetToCube(nearestEnemy.col, nearestEnemy.row)
          );
          return distToEnemy < bestDistToEnemy ? dest : best;
        });

        return {
          action: "move",
          unitId,
          destCol: bestDestination[0],
          destRow: bestDestination[1],
        };
      };

      // Helper function to make AI shooting decision
      const makeShootingDecision = (
        validTargets: string[],
        unitId: string,
        currentGameState: APIGameState
      ) => {
        if (!validTargets || validTargets.length === 0) {
          return { action: "skip", unitId };
        }

        // Strategy: Shoot nearest/most threatening target using fresh game state
        const shooter = currentGameState?.units.find((u) => u.id.toString() === unitId);
        if (!shooter) {
          return {
            action: "shoot",
            unitId,
            targetId: validTargets[0],
          };
        }

        // Find nearest target
        const nearestTarget = validTargets.reduce((nearest, targetId) => {
          const target = currentGameState?.units.find((u) => u.id.toString() === targetId);
          const nearestTargetUnit = currentGameState?.units.find(
            (u) => u.id.toString() === nearest
          );

          if (!target || !nearestTargetUnit) return nearest;

          const distToCurrent = cubeDistance(
            offsetToCube(target.col, target.row),
            offsetToCube(shooter.col, shooter.row)
          );
          const distToNearest = cubeDistance(
            offsetToCube(nearestTargetUnit.col, nearestTargetUnit.row),
            offsetToCube(shooter.col, shooter.row)
          );

          return distToCurrent < distToNearest ? targetId : nearest;
        });

        return {
          action: "shoot",
          unitId,
          targetId: nearestTarget,
        };
      };

      // Helper function to make AI fight decision
      const makeFightDecision = (
        validTargets: Array<{ id: string | number }> | string[],
        unitId: string,
        currentGameState: APIGameState
      ) => {
        if (!validTargets || validTargets.length === 0) {
          return { action: "skip", unitId };
        }

        // Strategy: Attack nearest/most threatening target using fresh game state
        const attacker = currentGameState?.units.find((u) => u.id.toString() === unitId);
        if (!attacker) {
          // Extract target ID from first target (could be object or string)
          const firstTarget = validTargets[0];
          const targetId = typeof firstTarget === "object" ? firstTarget.id : firstTarget;
          return {
            action: "fight",
            unitId,
            targetId: targetId.toString(),
          };
        }

        // Find nearest target
        const nearestTarget = validTargets.reduce((nearest, target) => {
          const targetId = typeof target === "object" ? target.id : target;
          const targetUnit = currentGameState?.units.find(
            (u) => u.id.toString() === targetId.toString()
          );
          const nearestTargetId = typeof nearest === "object" ? nearest.id : nearest;
          const nearestTargetUnit = currentGameState?.units.find(
            (u) => u.id.toString() === nearestTargetId.toString()
          );

          if (!targetUnit || !nearestTargetUnit) return nearest;

          const distToCurrent = cubeDistance(
            offsetToCube(targetUnit.col, targetUnit.row),
            offsetToCube(attacker.col, attacker.row)
          );
          const distToNearest = cubeDistance(
            offsetToCube(nearestTargetUnit.col, nearestTargetUnit.row),
            offsetToCube(attacker.col, attacker.row)
          );

          return distToCurrent < distToNearest ? target : nearest;
        });

        const finalTargetId = typeof nearestTarget === "object" ? nearestTarget.id : nearestTarget;
        return {
          action: "fight",
          unitId,
          targetId: finalTargetId.toString(),
        };
      };

      let totalUnitsProcessed = 0;
      let iteration = 0;
      try {
        const maxIterations = 25; // Allow larger armies (e.g. 12+ units in move phase)
        let lastPoolSize = -1;
        let samePoolSizeCount = 0;
        const initialPhase = gameState.phase;
        if (initialPhase === "fight") {
          const fs = gameState.fight_subphase;
          if (fs == null || fs === "") {
            throw new Error("Missing fight_subphase at executeAITurn start while phase is fight");
          }
        }
        const initialFightSubphase = initialPhase === "fight" ? gameState.fight_subphase : null;

        const shouldStopTutorialBoundary = (gs: APIGameState | undefined): boolean => {
          if (!stopAfterPhase || !gs) return false;
          if (gs.phase !== initialPhase) return true;
          if (initialPhase === "fight" && gs.phase === "fight") {
            const ns = gs.fight_subphase;
            if (ns == null || ns === "") {
              throw new Error(
                "Missing fight_subphase in fight phase during AI turn (tutorial boundary)"
              );
            }
            if (initialFightSubphase == null || initialFightSubphase === "") {
              throw new Error("Missing initial fight_subphase for tutorial boundary");
            }
            return ns !== initialFightSubphase;
          }
          return false;
        };

        while (iteration < maxIterations) {
          iteration++;

          const canCallAiTurn = (() => {
            if (!gameState) {
              throw new Error("Missing gameState during AI turn check");
            }
            if (gameState.current_player === undefined || gameState.current_player === null) {
              throw new Error("Missing current_player in gameState during AI turn check");
            }
            if (gameState.phase === "fight") {
              const fightSubphase = gameState.fight_subphase;
              if (!fightSubphase) {
                throw new Error("Missing fight_subphase in gameState during AI turn check");
              }
              // V11 : pool actionnable unique exposé par le moteur.
              const pool: string[] = gameState.fight_eligible_units ?? [];
              return pool.some((id) => isAiUnitId(id));
            }
            return getPlayerType(gameState.current_player) === "ai";
          })();

          if (!canCallAiTurn) {
            break;
          }

          // Step 1: Call backend to activate next AI unit
          const aiResponse = await fetch(`${API_BASE}/game/ai-turn`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          });

          if (!aiResponse.ok) {
            const errorData = await aiResponse.json().catch(() => ({}));
            const errorInfo = errorData.error || errorData;

            // Handle expected errors gracefully (AI not eligible or turn already advanced)
            if (errorInfo.error === "not_ai_player_turn") {
              // No more eligible AI units - fetch current game state and exit gracefully
              try {
                const stateResponse = await fetch(`${API_BASE}/game/state`);
                if (stateResponse.ok) {
                  const stateData = await stateResponse.json();
                  if (stateData.game_state) {
                    setGameState((p) =>
                      mergeGameStatePreservingOmittedObjectives(
                        p,
                        stateData.game_state as APIGameState
                      )
                    );
                    setEndlessDutyState(
                      (stateData.endless_duty_state as EndlessDutyState | undefined) ?? null
                    );
                  }
                }
              } catch (stateErr) {
                console.error("AI auto-play: game-state refresh failed:", stateErr);
              }
              // Exit loop - no more AI units eligible
              break;
            }
            // For other errors, log and throw
            throw new Error(
              `AI activation failed: ${aiResponse.status} - ${JSON.stringify(errorData)}`
            );
          }

          const activationData = await aiResponse.json();

          if (activationData.result?.action === "ai_turn_skipped") {
            if (activationData.game_state) {
              setGameState((p) =>
                mergeGameStatePreservingOmittedObjectives(
                  p,
                  activationData.game_state as APIGameState
                )
              );
              setEndlessDutyState(
                (activationData.endless_duty_state as EndlessDutyState | undefined) ?? null
              );
            }
            break;
          }

          // Process AI activation logs immediately
          const activationGsPhase = (activationData.game_state as { phase?: string } | undefined)
            ?.phase;
          const rawActivationLogs = Array.isArray(activationData.action_logs)
            ? (activationData.action_logs as Record<string, unknown>[])
            : [];
          if (rawActivationLogs.length > 0) {
            logActionLogBatchTrace("ai-turn /game/ai-turn", rawActivationLogs, {
              responsePhase: activationGsPhase,
              success: activationData.success,
            });
          } else if (isActionLogTraceEnabled() && activationGsPhase === "fight") {
            logActionLogBatchTrace("ai-turn /game/ai-turn", [], {
              responsePhase: activationGsPhase,
              success: activationData.success,
              note: "aucune entrée action_logs (phase fight)",
            });
          }
          if (activationData.action_logs && activationData.action_logs.length > 0) {
            interface ActivationLogEntry {
              message?: string;
              type?: string;
              turn?: number;
              phase?: string;
              shooterId?: string;
              attackerId?: string;
              unitId?: string;
              targetId?: string;
              player?: number;
              damage?: number;
              target_died?: boolean;
              hitRoll?: number;
              hit_roll?: number;
              woundRoll?: number;
              wound_roll?: number;
              saveRoll?: number;
              save_roll?: number;
              saveTarget?: number;
              save_target?: number;
              saveSkipped?: boolean;
              save_skipped?: boolean;
              saveSkipReason?: string;
              save_skip_reason?: string;
              devastatingWoundsApplied?: boolean;
              devastating_wounds_applied?: boolean;
              weaponName?: string;
              shootDetails?: Array<Record<string, unknown>>;
              action_name?: string;
              reward?: number;
              is_ai_action?: boolean;
              [key: string]: unknown;
            }
            const activationLogsBatch = dedupeActionLogBatch(
              activationData.action_logs as ActivationLogEntry[]
            );
            activationLogsBatch.forEach((logEntry: ActivationLogEntry) => {
              if (!shouldEmitActionLogEvent(logEntry as Record<string, unknown>)) {
                logActionLogEmitTrace(
                  "ai-turn /game/ai-turn",
                  logEntry as Record<string, unknown>,
                  false,
                  `cross_request_dedupe_<${CROSS_ACTION_LOG_SUPPRESS_MS}ms`
                );
                return;
              }
              logActionLogEmitTrace(
                "ai-turn /game/ai-turn",
                logEntry as Record<string, unknown>,
                true
              );
              const shootDetail = logEntry.shootDetails?.[0];
              window.dispatchEvent(
                new CustomEvent("backendLogEvent", {
                  detail: {
                    type: logEntry.type,
                    message: logEntry.message,
                    turn: gameState?.turn || logEntry.turn, // Use live turn
                    phase: logEntry.phase,
                    shooterId: logEntry.shooterId || logEntry.attackerId || logEntry.unitId,
                    targetId: logEntry.targetId,
                    player: logEntry.player,
                    damage: logEntry.damage ?? shootDetail?.damageDealt,
                    target_died: logEntry.target_died ?? shootDetail?.targetDied,
                    hitRoll: logEntry.hitRoll || logEntry.hit_roll || shootDetail?.attackRoll,
                    woundRoll:
                      logEntry.woundRoll || logEntry.wound_roll || shootDetail?.strengthRoll,
                    saveRoll: logEntry.saveRoll || logEntry.save_roll || shootDetail?.saveRoll,
                    saveTarget:
                      logEntry.saveTarget || logEntry.save_target || shootDetail?.saveTarget,
                    saveSkipped: logEntry.saveSkipped ?? logEntry.save_skipped,
                    saveSkipReason: logEntry.saveSkipReason || logEntry.save_skip_reason,
                    devastatingWoundsApplied:
                      logEntry.devastatingWoundsApplied ||
                      logEntry.devastating_wounds_applied ||
                      false,
                    weaponName: logEntry.weaponName, // MULTIPLE_WEAPONS_IMPLEMENTATION.md
                    targetUnitType: logEntry.targetUnitType,
                    shootDetails: logEntry.shootDetails,
                    result: logEntry.result,
                    action_name: logEntry.action_name,
                    reward: logEntry.reward,
                    is_ai_action: logEntry.is_ai_action,
                    timestamp: new Date(),
                  },
                })
              );
            });
          }

          if (!activationData.success) {
            break;
          }

          // Update game state from activation
          if (activationData.game_state) {
            setGameState((p) =>
              mergeGameStatePreservingOmittedObjectives(
                p,
                activationData.game_state as APIGameState
              )
            );
            setEndlessDutyState(
              (activationData.endless_duty_state as EndlessDutyState | undefined) ?? null
            );
            // Tutoriel étape 2 : arrêter après chaque phase ou changement de fight_subphase (2-14 / 2-15)
            if (stopAfterPhase && shouldStopTutorialBoundary(activationData.game_state)) {
              onStopAfterPhaseChange?.();
              break;
            }
          }

          // Step 2: Check if we got a preview response requiring decision
          if (activationData.result?.waiting_for_player) {
            let aiDecision:
              | {
                  action: string;
                  unitId?: string | number;
                  targetId?: string | number;
                  clickTarget?: string;
                  destCol?: number;
                  destRow?: number;
                }
              | undefined;
            const unitId =
              activationData.result?.unitId ||
              activationData.game_state?.active_movement_unit ||
              activationData.game_state?.active_shooting_unit;

            // Step 3: Make AI decision based on preview data using FRESH game state
            const currentPhase = activationData.game_state?.phase;

            if (activationData.result.valid_destinations) {
              if (currentPhase === "charge") {
                // Charge phase - we have destinations after target selection and roll
                // Pick best destination and execute charge
                const validDestinations = activationData.result.valid_destinations;

                if (!validDestinations || validDestinations.length === 0) {
                  aiDecision = { action: "skip", unitId };
                } else {
                  interface ChargeUnit {
                    id: string | number;
                    player: number;
                    HP_CUR: number;
                    col: number;
                    row: number;
                  }
                  const currentUnit = activationData.game_state?.units.find(
                    (u: ChargeUnit) => String(u.id) === String(unitId)
                  );

                  if (!currentUnit) {
                    aiDecision = { action: "skip", unitId };
                  } else {
                    // Find enemies
                    const enemies =
                      activationData.game_state?.units.filter(
                        (u: ChargeUnit) => u.player !== currentUnit.player && u.HP_CUR > 0
                      ) || [];

                    if (enemies.length === 0) {
                      aiDecision = { action: "skip", unitId };
                    } else {
                      // Find nearest enemy
                      const nearestEnemy = enemies.reduce(
                        (nearest: ChargeUnit, enemy: ChargeUnit) => {
                          const distToCurrent = cubeDistance(
                            offsetToCube(enemy.col, enemy.row),
                            offsetToCube(currentUnit.col, currentUnit.row)
                          );
                          const distToNearest = cubeDistance(
                            offsetToCube(nearest.col, nearest.row),
                            offsetToCube(currentUnit.col, currentUnit.row)
                          );
                          return distToCurrent < distToNearest ? enemy : nearest;
                        }
                      );

                      // Pick destination closest to nearest enemy
                      const bestDestination = validDestinations.reduce(
                        (best: number[], dest: number[]) => {
                          const distToEnemy = cubeDistance(
                            offsetToCube(dest[0], dest[1]),
                            offsetToCube(nearestEnemy.col, nearestEnemy.row)
                          );
                          const bestDistToEnemy = cubeDistance(
                            offsetToCube(best[0], best[1]),
                            offsetToCube(nearestEnemy.col, nearestEnemy.row)
                          );
                          return distToEnemy < bestDistToEnemy ? dest : best;
                        }
                      );

                      // Execute charge with destination (targetId is already stored in game_state from previous step)
                      aiDecision = {
                        action: "charge",
                        unitId,
                        destCol: bestDestination[0],
                        destRow: bestDestination[1],
                        // Note: targetId is NOT needed here - it's stored in game_state from target selection step
                      };
                    }
                  }
                }
              } else {
                // Movement phase - pick destination using fresh backend state
                const moveAnchors =
                  activationData.result.valid_destinations ??
                  activationData.game_state?.valid_move_destinations_pool;
                aiDecision = makeMovementDecision(moveAnchors, unitId, activationData.game_state);
              }
            } else if (
              currentPhase === "charge" &&
              (activationData.result.blinking_units || activationData.result.valid_targets) &&
              (activationData.result.start_blinking !== false ||
                activationData.result.valid_targets)
            ) {
              // Charge phase - we have blinking_units or valid_targets (potential targets) but no destinations yet
              // Step 1: Select target (this will trigger roll and build destinations)
              const blinkingUnits = activationData.result.blinking_units as string[] | undefined;
              const validTargets = activationData.result.valid_targets as
                | Array<{ id: string | number }>
                | undefined;
              const targetIds = blinkingUnits?.length
                ? blinkingUnits
                : (validTargets?.map((t) => String(t.id)) ?? []);

              if (!targetIds.length) {
                aiDecision = { action: "skip", unitId };
              } else {
                interface ChargeUnit {
                  id: string | number;
                  player: number;
                  HP_CUR: number;
                  col: number;
                  row: number;
                }
                const currentUnit = activationData.game_state?.units.find(
                  (u: ChargeUnit) => String(u.id) === String(unitId)
                );

                if (!currentUnit) {
                  aiDecision = { action: "skip", unitId };
                } else {
                  // Find nearest enemy from target IDs
                  const enemies =
                    activationData.game_state?.units.filter(
                      (u: ChargeUnit) =>
                        u.player !== currentUnit.player &&
                        u.HP_CUR > 0 &&
                        targetIds.includes(String(u.id))
                    ) || [];

                  if (enemies.length === 0) {
                    aiDecision = { action: "skip", unitId };
                  } else {
                    // Find nearest enemy
                    const nearestEnemy = enemies.reduce(
                      (nearest: ChargeUnit, enemy: ChargeUnit) => {
                        const distToCurrent = cubeDistance(
                          offsetToCube(enemy.col, enemy.row),
                          offsetToCube(currentUnit.col, currentUnit.row)
                        );
                        const distToNearest = cubeDistance(
                          offsetToCube(nearest.col, nearest.row),
                          offsetToCube(currentUnit.col, currentUnit.row)
                        );
                        return distToCurrent < distToNearest ? enemy : nearest;
                      }
                    );

                    // Step 1: Select target (this will roll 2d6 and build destinations)
                    aiDecision = {
                      action: "charge",
                      unitId,
                      targetId: nearestEnemy.id,
                      // Note: NO destCol/destRow here - that's step 2
                    };
                  }
                }
              }
            } else if (
              activationData.result?.action === "empty_target_advance_available" &&
              activationData.result?.allow_advance
            ) {
              const advanceUnitId =
                activationData.result?.unitId ?? activationData.game_state?.active_shooting_unit;
              if (!advanceUnitId) {
                throw new Error("Missing unitId for empty_target_advance_available AI decision");
              }
              aiDecision = {
                action: "advance",
                unitId: advanceUnitId,
              };
            } else if (activationData.result.valid_targets && currentPhase !== "charge") {
              // Handle valid targets (uniformized to snake_case in backend)
              // Charge phase is handled above via blinking_units/valid_targets block
              const targets = activationData.result.valid_targets;

              if (currentPhase === "fight") {
                // Fight phase - pick target using fresh backend state
                aiDecision = makeFightDecision(targets, unitId, activationData.game_state);
              } else {
                // Shooting phase - pick target using fresh backend state
                aiDecision = makeShootingDecision(targets, unitId, activationData.game_state);
              }
            } else if (currentPhase === "charge" && activationData.result.waiting_for_player) {
              // Charge phase waiting but no targets/destinations - skip to avoid infinite loop
              aiDecision = { action: "skip", unitId };
            } else {
              break;
            }

            // Step 4: Send AI decision immediately
            const decisionResponse = await fetch(`${API_BASE}/game/action`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(aiDecision),
            });

            if (!decisionResponse.ok) {
              throw new Error(`AI decision failed: ${decisionResponse.status}`);
            }

            const decisionData = await decisionResponse.json();

            if (decisionData.success) {
              const decisionGsPhase = (decisionData.game_state as { phase?: string } | undefined)
                ?.phase;
              const rawDecisionLogs = Array.isArray(decisionData.action_logs)
                ? (decisionData.action_logs as Record<string, unknown>[])
                : [];
              if (rawDecisionLogs.length > 0) {
                logActionLogBatchTrace("ai-decision /game/action", rawDecisionLogs, {
                  responsePhase: decisionGsPhase,
                  success: decisionData.success,
                  afterAiTurn: true,
                });
              } else if (isActionLogTraceEnabled() && decisionGsPhase === "fight") {
                logActionLogBatchTrace("ai-decision /game/action", [], {
                  responsePhase: decisionGsPhase,
                  success: decisionData.success,
                  afterAiTurn: true,
                  note: "aucune entrée action_logs (phase fight)",
                });
              }
              // Process action logs
              if (decisionData.action_logs && decisionData.action_logs.length > 0) {
                interface DecisionLogEntry {
                  message?: string;
                  type?: string;
                  turn?: number;
                  phase?: string;
                  shooterId?: string;
                  attackerId?: string;
                  unitId?: string;
                  targetId?: string;
                  player?: number;
                  damage?: number;
                  target_died?: boolean;
                  hitRoll?: number;
                  hit_roll?: number;
                  woundRoll?: number;
                  wound_roll?: number;
                  saveRoll?: number;
                  save_roll?: number;
                  saveTarget?: number;
                  save_target?: number;
                  saveSkipped?: boolean;
                  save_skipped?: boolean;
                  saveSkipReason?: string;
                  save_skip_reason?: string;
                  devastatingWoundsApplied?: boolean;
                  devastating_wounds_applied?: boolean;
                  weaponName?: string;
                  shootDetails?: Array<Record<string, unknown>>;
                  action_name?: string;
                  reward?: number;
                  is_ai_action?: boolean;
                  [key: string]: unknown;
                }
                const decisionLogsBatch = dedupeActionLogBatch(
                  decisionData.action_logs as DecisionLogEntry[]
                );
                decisionLogsBatch.forEach((logEntry: DecisionLogEntry) => {
                  if (!shouldEmitActionLogEvent(logEntry as Record<string, unknown>)) {
                    logActionLogEmitTrace(
                      "ai-decision /game/action",
                      logEntry as Record<string, unknown>,
                      false,
                      `cross_request_dedupe_<${CROSS_ACTION_LOG_SUPPRESS_MS}ms`
                    );
                    return;
                  }
                  logActionLogEmitTrace(
                    "ai-decision /game/action",
                    logEntry as Record<string, unknown>,
                    true
                  );
                  const shootDetail = logEntry.shootDetails?.[0];
                  window.dispatchEvent(
                    new CustomEvent("backendLogEvent", {
                      detail: {
                        type: logEntry.type,
                        message: logEntry.message,
                        turn: logEntry.turn,
                        phase: logEntry.phase,
                        shooterId: logEntry.shooterId || logEntry.attackerId || logEntry.unitId,
                        targetId: logEntry.targetId,
                        player: logEntry.player,
                        damage: logEntry.damage ?? shootDetail?.damageDealt,
                        target_died: logEntry.target_died ?? shootDetail?.targetDied,
                        hitRoll: logEntry.hitRoll || logEntry.hit_roll || shootDetail?.attackRoll,
                        woundRoll:
                          logEntry.woundRoll || logEntry.wound_roll || shootDetail?.strengthRoll,
                        saveRoll: logEntry.saveRoll || logEntry.save_roll || shootDetail?.saveRoll,
                        saveTarget:
                          logEntry.saveTarget || logEntry.save_target || shootDetail?.saveTarget,
                        saveSkipped: logEntry.saveSkipped ?? logEntry.save_skipped,
                        saveSkipReason: logEntry.saveSkipReason || logEntry.save_skip_reason,
                        devastatingWoundsApplied:
                          logEntry.devastatingWoundsApplied ||
                          logEntry.devastating_wounds_applied ||
                          false,
                        weaponName: logEntry.weaponName, // MULTIPLE_WEAPONS_IMPLEMENTATION.md
                        targetUnitType: logEntry.targetUnitType,
                        shootDetails: logEntry.shootDetails,
                        result: logEntry.result,
                        action_name: logEntry.action_name,
                        reward: logEntry.reward,
                        is_ai_action: logEntry.is_ai_action,
                        timestamp: new Date(),
                      },
                    })
                  );
                });
              }

              // Update game state from decision
              setGameState((p) =>
                mergeGameStatePreservingOmittedObjectives(
                  p,
                  decisionData.game_state as APIGameState
                )
              );
              setEndlessDutyState(
                (decisionData.endless_duty_state as EndlessDutyState | undefined) ?? null
              );
              totalUnitsProcessed++;

              // Check if phase complete
              if (decisionData.result?.phase_complete) {
                break;
              }
              // Tutoriel étape 2 : arrêter après chaque phase ou changement de fight_subphase
              if (stopAfterPhase && shouldStopTutorialBoundary(decisionData.game_state)) {
                onStopAfterPhaseChange?.();
                break;
              }
            } else {
              break;
            }
          } else if (
            activationData.result?.activation_ended ||
            activationData.result?.activation_complete
          ) {
            // Unit completed activation (move, skip, wait, etc.)
            // Backend uses activation_ended (generic) or activation_complete (movement handler)
            totalUnitsProcessed++;

            // Check if phase complete after unit completion
            if (activationData.result?.phase_complete) {
              break;
            }
            // Tutoriel étape 2 : arrêter après chaque phase ou changement de fight_subphase
            if (stopAfterPhase && shouldStopTutorialBoundary(activationData.game_state)) {
              onStopAfterPhaseChange?.();
              break;
            }
          } else if (
            !activationData.result?.waiting_for_player &&
            !activationData.result?.valid_targets &&
            !activationData.result?.valid_destinations
          ) {
            // No valid action available - skip this unit
            // This can happen when unit has no valid targets in shoot phase
            const unitId =
              activationData.result?.unitId ||
              activationData.game_state?.active_shooting_unit ||
              activationData.game_state?.active_movement_unit;

            if (unitId) {
              // Send skip action to backend
              try {
                const skipResponse = await fetch(`${API_BASE}/game/action`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ action: "skip", unitId: String(unitId) }),
                });

                if (skipResponse.ok) {
                  const skipData = await skipResponse.json();
                  setGameState((p) =>
                    mergeGameStatePreservingOmittedObjectives(
                      p,
                      skipData.game_state as APIGameState
                    )
                  );
                  setEndlessDutyState(
                    (skipData.endless_duty_state as EndlessDutyState | undefined) ?? null
                  );
                  totalUnitsProcessed++;

                  if (skipData.result?.phase_complete) {
                    break;
                  }
                  // Tutoriel étape 2 : arrêter après chaque phase ou changement de fight_subphase
                  if (stopAfterPhase && shouldStopTutorialBoundary(skipData.game_state)) {
                    onStopAfterPhaseChange?.();
                    break;
                  }
                }
              } catch (err) {
                console.error("AI auto-play: activation loop error:", err);
                break; // Exit loop on error
              }
            } else {
              // No unit ID available - exit loop to prevent infinite loop
              break;
            }

            // CRITICAL: Check if pool size changed (unit was removed)
            const updatedGameState = activationData.game_state;
            const currentPhase = updatedGameState?.phase;
            let currentPoolSize = 0;

            if (currentPhase === "fight") {
              const fightSubphase = updatedGameState?.fight_subphase;
              if (fightSubphase === "charging" && updatedGameState?.charging_activation_pool) {
                currentPoolSize = updatedGameState.charging_activation_pool.length;
              } else if (
                fightSubphase === "alternating_non_active" &&
                updatedGameState?.non_active_alternating_activation_pool
              ) {
                currentPoolSize = updatedGameState.non_active_alternating_activation_pool.length;
              } else if (
                fightSubphase === "alternating_active" &&
                updatedGameState?.active_alternating_activation_pool
              ) {
                currentPoolSize = updatedGameState.active_alternating_activation_pool.length;
              } else if (
                fightSubphase === "cleanup_non_active" &&
                updatedGameState?.non_active_alternating_activation_pool
              ) {
                currentPoolSize = updatedGameState.non_active_alternating_activation_pool.length;
              } else if (
                fightSubphase === "cleanup_active" &&
                updatedGameState?.active_alternating_activation_pool
              ) {
                currentPoolSize = updatedGameState.active_alternating_activation_pool.length;
              }
            } else if (currentPhase === "move" && updatedGameState?.move_activation_pool) {
              currentPoolSize = updatedGameState.move_activation_pool.length;
            } else if (currentPhase === "charge" && updatedGameState?.charge_activation_pool) {
              currentPoolSize = updatedGameState.charge_activation_pool.length;
            }

            // If pool is empty, break
            if (currentPoolSize === 0) {
              break;
            }

            // Safety: If pool size hasn't changed after multiple skips, break
            if (currentPoolSize === lastPoolSize) {
              samePoolSizeCount++;
              if (samePoolSizeCount >= 3) {
                break;
              }
            } else {
              samePoolSizeCount = 0;
              lastPoolSize = currentPoolSize;
            }

            // Check if there are still eligible AI units in the pool
            let hasMoreEligibleUnits = false;
            if (currentPhase === "fight") {
              const fightSubphase = updatedGameState?.fight_subphase;
              let fightPool: string[] = [];
              if (fightSubphase === "charging" && updatedGameState?.charging_activation_pool) {
                fightPool = updatedGameState.charging_activation_pool;
              } else if (
                fightSubphase === "alternating_non_active" &&
                updatedGameState?.non_active_alternating_activation_pool
              ) {
                fightPool = updatedGameState.non_active_alternating_activation_pool;
              } else if (
                fightSubphase === "alternating_active" &&
                updatedGameState?.active_alternating_activation_pool
              ) {
                fightPool = updatedGameState.active_alternating_activation_pool;
              } else if (
                fightSubphase === "cleanup_non_active" &&
                updatedGameState?.non_active_alternating_activation_pool
              ) {
                fightPool = updatedGameState.non_active_alternating_activation_pool;
              } else if (
                fightSubphase === "cleanup_active" &&
                updatedGameState?.active_alternating_activation_pool
              ) {
                fightPool = updatedGameState.active_alternating_activation_pool;
              }

              hasMoreEligibleUnits = fightPool.some((unitId) => {
                const unit = updatedGameState?.units?.find(
                  (u: APIGameState["units"][0]) => String(u.id) === String(unitId)
                );
                return (
                  !!unit &&
                  unit.HP_CUR > 0 &&
                  isAiUnitInState(updatedGameState as APIGameState, unitId)
                );
              });
            } else if (currentPhase === "move" && updatedGameState?.move_activation_pool) {
              hasMoreEligibleUnits = updatedGameState.move_activation_pool.some(
                (unitId: string) => {
                  const unit = updatedGameState?.units?.find(
                    (u: APIGameState["units"][0]) => String(u.id) === String(unitId)
                  );
                  return (
                    !!unit &&
                    unit.HP_CUR > 0 &&
                    isAiUnitInState(updatedGameState as APIGameState, unitId)
                  );
                }
              );
            } else if (currentPhase === "charge" && updatedGameState?.charge_activation_pool) {
              hasMoreEligibleUnits = updatedGameState.charge_activation_pool.some(
                (unitId: string) => {
                  const unit = updatedGameState?.units?.find(
                    (u: APIGameState["units"][0]) => String(u.id) === String(unitId)
                  );
                  return (
                    !!unit &&
                    unit.HP_CUR > 0 &&
                    isAiUnitInState(updatedGameState as APIGameState, unitId)
                  );
                }
              );
            }

            if (!hasMoreEligibleUnits) {
              break;
            }

            // Safety: If we've processed many units without progress, break
            if (totalUnitsProcessed >= 5 && iteration >= 10) {
              break;
            }
          } else if (activationData.result?.phase_complete) {
            // Phase already complete
            break;
          } else {
            // Unexpected response format - continue
          }

          // Small delay for UX
          await new Promise((resolve) => setTimeout(resolve, 150));
        }
      } catch (err) {
        setError(`AI turn failed: ${formatApiConnectionError(err)}`);
      } finally {
        aiTurnInProgress = false;
      }
    },
    startGameWithScenario,
    startPveGame,
    startPvpGame,
    endlessDutyState,
    fetchEndlessDutyStatus,
    commitEndlessDuty,
  };

  return returnObject;
};
