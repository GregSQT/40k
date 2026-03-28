import type React from "react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  getTutorialScenarioRuntimeData,
  tutorialScenarioYamlRevision,
} from "../config/tutorialScenarioRuntime";
import { getTutorialUiBehavior } from "../config/tutorialUiRules";
import type { APIGameState } from "../hooks/useEngineAPI";

const TUTORIAL_SCENARIOS = [
  "config/tutorial/scenario_etape1.json",
  "config/tutorial/scenario_etape2.json",
  "config/tutorial/scenario_etape3.json",
] as const;

/** Titre de l’étape "Phase de mouvement" (halos board + colonnes Name/M). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_ROUNDS = "Rounds";
export const TUTORIAL_STEP_TITLE_TURNS = "Tours";
export const TUTORIAL_STEP_TITLE_PHASES = "Phases";
export const TUTORIAL_STEP_TITLE_PHASE_MOVE = "Phase de mouvement";
/** Ordre 4 : "Phase de Mouvement" (halo Intercessor + bouton move du turn phase tracker). */
export const TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT = "Phase de Mouvement";
/** Titre étape 1-14 (même layout halo Intercessor + bouton Move). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_1_14_PHASE_MOUVEMENT = "1-14 Phase de Mouvement";
/** Titre étape 1-15 (halo colonnes Name et M pour clic Intercessor). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_1_15_PHASE_MOUVEMENT = "1-15 Phase de mouvement";
/** Phase de Tir (halo sur le bouton Shoot du turn phase tracker). */
export const TUTORIAL_STEP_TITLE_PHASE_TIR = "Phase de Tir";
/** Titre étape 1-21 (panneau gauche sans fog, halo colonnes Name/M pour clic Intercessor). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_1_21_PHASE_TIR = "1-21 Phase de Tir";
/** Choix des armes (étape 1-22 : halos Move/Shoot, Intercessor armes, Termagant attributs). */
export const TUTORIAL_STEP_TITLE_WEAPON_CHOICE = "Choix des armes";
/** Titre étape 1-22 (panneau gauche sans fog). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_1_22_MENU_CHOIX_ARMES = "1-22 Menu de choix des armes";
/** Titre étape 1-23 (panneau gauche sans fog, choix Bolt Rifle). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_1_23_CHOIX_ARMES = "1-23 Choix de l'arme";
/** Titre étape 1-24 (panneau gauche sans fog, clic Termagant). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_1_24_CHOIX_CIBLE = "1-24 Choix de la cible";
/** Titre étape 1-25 (panneau gauche sans fog, halo armes + combat log). À garder en sync avec tutorial_scenario.md (bloc tutorial-steps). */
export const TUTORIAL_STEP_TITLE_1_25_MORT_TERMAGANT = "1-25 Mort du termagant";

/** Étapes qui affichent le halo sur l'Intercessor (board). */
export const TUTORIAL_STEP_TITLES_INTERCESSOR_HALO = [
  TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_1_14_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_1_21_PHASE_TIR,
] as const;

/** Étapes qui affichent le halo sur les colonnes Name et M (panneau droit) pour clic sur l’unité (ex. Intercessor). */
export const TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO = [
  TUTORIAL_STEP_TITLE_PHASE_MOVE,
  TUTORIAL_STEP_TITLE_1_14_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_1_15_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_1_21_PHASE_TIR,
] as const;

/** Étapes qui affichent le halo sur le bouton Move du turn phase tracker. */
export const TUTORIAL_STEP_TITLES_MOVE_BUTTON_HALO = [
  TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_1_14_PHASE_MOUVEMENT,
] as const;

/**
 * Étapes où le HALO (zone sans brouillard) est sur le PANNEAU GAUCHE (board).
 * Layout : gauche = game-board-section (board), droite = unit-status-tables (TurnPhaseTracker, etc.)
 */
export const TUTORIAL_STEP_TITLES_HALO_LEFT = [
  TUTORIAL_STEP_TITLE_PHASE_MOVE,
  TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_1_14_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_PHASE_TIR,
  TUTORIAL_STEP_TITLE_1_21_PHASE_TIR,
  TUTORIAL_STEP_TITLE_WEAPON_CHOICE,
  TUTORIAL_STEP_TITLE_1_22_MENU_CHOIX_ARMES,
  TUTORIAL_STEP_TITLE_1_23_CHOIX_ARMES,
  TUTORIAL_STEP_TITLE_1_24_CHOIX_CIBLE,
  TUTORIAL_STEP_TITLE_1_25_MORT_TERMAGANT,
] as const;

export interface TutorialFogConfig {
  global: boolean;
  leftPanel: boolean;
  rightPanel: boolean;
  boardTopBand: boolean;
}

/** Parse "stage" (e.g. "1-14") → etape + order. Accepte aussi etape/order en legacy. */
function normalizeStep(raw: Record<string, unknown>): TutorialStepDef {
  let etape: number;
  let order: number;
  let stageId: string | undefined;
  if (typeof raw.stage === "string") {
    const stageRaw = raw.stage.trim();
    const parts = stageRaw.split("-");
    if (
      parts.length < 2 ||
      !parts.every((p) => /^[0-9]+$/.test(p)) ||
      !Number.isInteger(Number(parts[0])) ||
      !Number.isInteger(Number(parts[1]))
    ) {
      throw new Error(
        `Invalid stage: "${raw.stage}". Expected format "X-Y" or "X-Y-Z" (e.g. "1-14", "1-24-1").`
      );
    }
    etape = Number(parts[0]);
    const baseOrder = Number(parts[1]);
    if (parts.length > 2) {
      const suffix = parts.slice(2).join("");
      const fractional = Number(`0.${suffix}`);
      if (!Number.isFinite(fractional)) {
        throw new Error(`Invalid stage suffix in "${raw.stage}"`);
      }
      order = baseOrder + fractional;
    } else {
      order = baseOrder;
    }
    stageId = stageRaw;
  } else if (typeof raw.etape === "number" && typeof raw.order === "number") {
    etape = raw.etape;
    order = raw.order;
    stageId = `${etape}-${order}`;
  } else {
    throw new Error("Step must have 'stage' (e.g. '1-14') or 'etape' and 'order'.");
  }
  if (typeof raw.fog !== "object" || raw.fog == null) {
    throw new Error(`Step "${stageId ?? `${etape}-${order}`}" must define fog object`);
  }
  const fogRecord = raw.fog as Record<string, unknown>;
  const fogKeys: Array<keyof TutorialFogConfig> = ["global", "leftPanel", "rightPanel", "boardTopBand"];
  for (const key of fogKeys) {
    if (typeof fogRecord[key] !== "boolean") {
      throw new Error(`Step "${stageId ?? `${etape}-${order}`}" fog.${key} must be boolean`);
    }
  }
  if (raw.spotlightIds != null) {
    if (!Array.isArray(raw.spotlightIds) || raw.spotlightIds.some((v) => typeof v !== "string")) {
      throw new Error(`Step "${stageId ?? `${etape}-${order}`}" spotlightIds must be string[]`);
    }
  }
  if (raw.allowedClickSpotlightIds != null) {
    if (
      !Array.isArray(raw.allowedClickSpotlightIds) ||
      raw.allowedClickSpotlightIds.some((v) => typeof v !== "string")
    ) {
      throw new Error(
        `Step "${stageId ?? `${etape}-${order}`}" allowedClickSpotlightIds must be string[]`
      );
    }
  }
  if (raw.title_icon != null && (typeof raw.title_icon !== "string" || raw.title_icon.trim() === "")) {
    throw new Error(`Step "${stageId ?? `${etape}-${order}`}" title_icon must be a non-empty string`);
  }
  if (typeof raw.trigger === "object" && raw.trigger != null) {
    const t = raw.trigger as Record<string, unknown>;
    if (t.type === "fight_subphase_enter") {
      if (typeof t.fight_subphase !== "string" || t.fight_subphase.trim() === "") {
        throw new Error(
          `Step "${stageId ?? `${etape}-${order}`}" trigger fight_subphase_enter requires non-empty fight_subphase`
        );
      }
    }
  }
  const { stage: _s, etape: _e, order: _o, ...rest } = raw;
  return { ...rest, etape, order, stage_id: stageId } as TutorialStepDef;
}

export interface TutorialStepDef {
  etape: number;
  order: number;
  stage_id?: string;
  trigger: { type: string; phase?: string; fight_subphase?: string };
  /** Si true, pas de bouton Suivant ; on avance au clic sur l'unité joueur 1 (ex. Intercessor). */
  advance_on_unit_click?: boolean;
  /** Si true, on avance quand le joueur confirme un déplacement (clic destination puis confirm). */
  advance_on_move_click?: boolean;
  /** Si true, masquer l’icône Advance au-dessus des unités pendant ce step. */
  hide_advance_icon?: boolean;
  /** Si true, pas de bouton Suivant ; on avance quand le joueur choisit une arme (sélection confirmée). */
  advance_on_weapon_click?: boolean;
  advance_on_weapon_name?: string;
  /** URL de l’image à afficher dans le popup (ex. icône d’arme). */
  popup_image?: string;
  /** Si true, afficher un hexagone vert (destination de move) dans le popup. */
  popup_show_move_hex?: boolean;
  /** Si true, afficher popup_image (icône d’unité) entourée du cercle vert (unité activable). */
  popup_show_green_circle?: boolean;
  /** URL de l’icône affichée à gauche du titre du popup. */
  title_icon?: string;
  /** Si true, afficher la première ligne du body sur la même ligne que l’icône (popup_image ou hex). */
  popup_first_line_with_icon?: boolean;
  /**
   * Point d'ancrage du popup (viewport).
   * - "center" ou absent : centré (comportement par défaut)
   * - { left: "5%" | 20, top: "10%" | 30 } : coin haut-gauche en % ou px (bord viewport)
   */
  popup_position?: "center" | { left?: string | number; top?: string | number };
  fog: TutorialFogConfig;
  spotlightIds?: string[];
  allowedClickSpotlightIds?: string[];
  title_fr: string;
  title_en: string;
  body_fr: string;
  body_en: string;
}

function getStageId(step: TutorialStepDef): string {
  return step.stage_id ?? `${step.etape}-${step.order}`;
}

/** Halo circulaire (ex. unité sur le board). */
export interface TutorialSpotlightCircle {
  shape: "circle";
  x: number;
  y: number;
  radius: number;
}

/** Halo rectangulaire (ex. cellules Name+M du panneau). */
export interface TutorialSpotlightRect {
  shape: "rect";
  left: number;
  top: number;
  width: number;
  height: number;
}

export type TutorialSpotlightPosition = TutorialSpotlightCircle | TutorialSpotlightRect;

export type TutorialLang = "fr" | "en";

export interface TutorialStepDisplay {
  title_fr: string;
  title_en: string;
  body_fr: string;
  body_en: string;
  /** Clé pour identifier l'étape (halos, etc.) = title_fr. */
  stepKey: string;
  /** Identifiant d’étape "X-Y" (ex. "1-15", "1-16") pour distinguer les steps au même stepKey. */
  stage: string;
  /** Phase du tour (move, shooting, charge, fight) pour les étapes liées à une phase ; utilisé pour afficher le logo à gauche du titre. */
  phase?: string;
  /** Si true, pas de bouton Suivant ; avancer au clic sur l'unité joueur 1. */
  advanceOnUnitClick?: boolean;
  /** Si true, avancer quand le joueur confirme un déplacement. */
  advanceOnMoveClick?: boolean;
  /** Si true, masquer l’icône Advance au-dessus des unités. */
  hideAdvanceIcon?: boolean;
  /** Si true, pas de bouton Suivant ; avancer au choix d’arme (sélection confirmée). */
  advanceOnWeaponClick?: boolean;
  advanceOnWeaponName?: string;
  /** URL de l’image à afficher dans le popup (ex. icône d’arme). */
  popupImage?: string;
  /** URL de l’icône affichée à gauche du titre du popup. */
  titleIcon?: string;
  /** Si true, afficher un hexagone vert (destination de move) dans le popup. */
  popupShowMoveHex?: boolean;
  /** Si true, afficher l’icône (popupImage) entourée du cercle vert (unité activable). */
  popupShowGreenCircle?: boolean;
  /** Si true, afficher la première ligne du body sur la même ligne que l’icône. */
  popupFirstLineWithIcon?: boolean;
  /** Position initiale du popup : "center" ou { left, top } en % (ex. "5%") ou px. */
  popupPosition?: "center" | { left: string | number; top: string | number };
  fog: TutorialFogConfig;
  spotlightIds?: string[];
  allowedClickSpotlightIds?: string[];
}

interface TutorialContextValue {
  isTutorialMode: boolean;
  currentStep: TutorialStepDisplay | null;
  popupVisible: boolean;
  tutorialLang: TutorialLang;
  setTutorialLang: (lang: TutorialLang) => void;
  onClosePopup: () => void;
  onSkipTutorial: () => void;
  /** À appeler avant une action qui met à jour le gameState et avance l’étape (ex. confirmation déplacement), pour ne pas être écrasé par l’effet phase_enter. */
  prepareSkipNextPhaseTrigger: () => void;
  currentEtape: number;
  /** Phase du jeu (deployment, move, etc.) pour forcer le layout 2-11 quand étape 2 + deployment. */
  gamePhase: string | null;
  /** Position viewport (px) du halo autour de l'unité ciblée ; null si pas de halo. */
  spotlightPosition: TutorialSpotlightPosition | null;
  setSpotlightPosition: (pos: TutorialSpotlightPosition | null) => void;
  /** Halos viewport (px) : [colonne Name, colonne M] pour la ligne Intercessor ; null si pas de halo. */
  spotlightTablePositions: TutorialSpotlightPosition[] | null;
  setSpotlightTablePositions: (pos: TutorialSpotlightPosition[] | null) => void;
  /** Halos viewport (px) : Turn / P1+P2 / phases selon l'étape (Rounds, Tours, Phases). */
  spotlightTurnPhasePositions: TutorialSpotlightPosition[] | null;
  setSpotlightTurnPhasePositions: (pos: TutorialSpotlightPosition[] | null) => void;
  /** Ancrage popups 1-11 / 1-12 / 1-13 : centre du bouton cible + bas de la bande (viewport px). */
  spotlightTutorialPopupAnchor: { centerX: number; bottomY: number } | null;
  setSpotlightTutorialPopupAnchor: (pos: { centerX: number; bottomY: number } | null) => void;
  /** Rect viewport (px) du PANNEAU GAUCHE (board) = halo (zone sans brouillard). */
  spotlightLeftPanel: TutorialSpotlightPosition | null;
  setSpotlightLeftPanel: (pos: TutorialSpotlightPosition | null) => void;
  /** Rect viewport (px) du PANNEAU DROIT (unit-status-tables) = halo. */
  spotlightRightPanel: TutorialSpotlightPosition | null;
  setSpotlightRightPanel: (pos: TutorialSpotlightPosition | null) => void;
  /** Rects viewport (px) des zones de fog sur le panneau gauche (étape 1-15 : 2 bandes pour moins noir). */
  leftPanelFogRects: TutorialSpotlightRect[];
  setLeftPanelFogRects: (r: TutorialSpotlightRect[] | null) => void;
  /** Rects viewport (px) des zones de fog sur le panneau droit (étape 2-11 : fog sur tout le panneau). */
  rightPanelFogRects: TutorialSpotlightRect[];
  setRightPanelFogRects: (r: TutorialSpotlightRect[] | null) => void;
  /** Halos viewport (px) : section RANGED WEAPON(S) du panneau droit (étape 1-16). */
  spotlightRangedWeaponsPositions: TutorialSpotlightPosition[] | null;
  setSpotlightRangedWeaponsPositions: (pos: TutorialSpotlightPosition[] | null) => void;
  /** Rect viewport (px) de la dernière ligne du Game Log (étape 1-21). */
  spotlightGameLogLastEntry: TutorialSpotlightPosition | null;
  setSpotlightGameLogLastEntry: (pos: TutorialSpotlightPosition | null) => void;
  /** Rect viewport (px) du titre du Game Log (étape 1-21). */
  spotlightGameLogHeader: TutorialSpotlightPosition | null;
  setSpotlightGameLogHeader: (pos: TutorialSpotlightPosition | null) => void;
  /** Rects viewport (px) des 2 lignes supérieures du Game Log (entrées les plus récentes). */
  spotlightGameLogTopEntriesPositions: TutorialSpotlightPosition[];
  setSpotlightGameLogTopEntriesPositions: (pos: TutorialSpotlightPosition[] | null) => void;
  /** Rect viewport (px) de la ligne attributs + titre d’une unité ennemie (étape 1-22, ex. Termagant). */
  spotlightEnemyUnitAttributes: TutorialSpotlightPosition | null;
  setSpotlightEnemyUnitAttributes: (pos: TutorialSpotlightPosition | null) => void;
  /** Rects viewport (px) des lignes des unités P2 (étape 2-11/2-12 : halos sur Hormagaunts). */
  spotlightP2UnitRowPositions: TutorialSpotlightPosition[];
  setSpotlightP2UnitRowPositions: (pos: TutorialSpotlightPosition[] | null) => void;
  /** Cercles viewport (px) des icônes sur le board (étape 2-11/2-12 : Intercessor + Hormagaunts). */
  spotlightBoardUnitPositions: TutorialSpotlightPosition[];
  setSpotlightBoardUnitPositions: (pos: TutorialSpotlightPosition[] | null) => void;
  /**
   * Incrémenté après scroll / resize (throttle rAF) quand le popup tutoriel est visible,
   * pour forcer la remesure des halos (coords viewport) afin qu’ils suivent le contenu défilant.
   */
  spotlightLayoutTick: number;
  /** Position (col, row) où l'ennemi est mort (étape 1-25 : afficher icône ghost Termagant sur le board). */
  lastEnemyDeathPosition: { col: number; row: number } | null;
  /** Étape 2-16 : lance le mode PvE (API + navigation). */
  onGoToPveMode?: () => void | Promise<void>;
  /** Étape 2-16 : ferme uniquement le popup sans terminer le tutoriel ni changer de mode. */
  onDismissPopupOnly: () => void;
}

const TutorialContext = createContext<TutorialContextValue | null>(null);

export function useTutorial(): TutorialContextValue | null {
  return useContext(TutorialContext);
}

interface TutorialProviderProps {
  isTutorialMode: boolean;
  /**
   * Mis à jour à chaque rendu avec shouldPauseAI (même logique que onPauseAIChange).
   * Permet au parent (BoardWithAPI) de bloquer l’orchestration IA sans décalage d’une frame
   * (sinon la phase peut passer à charge avant que pauseAIForTutorial soit à jour).
   */
  tutorialPauseAiSyncRef?: React.MutableRefObject<boolean>;
  gameState: {
    phase?: string;
    fight_subphase?: string | null;
    units?: Array<{ id: string | number; player: number; col?: number; row?: number }>;
    units_cache?: Record<string, unknown>;
  } | null;
  /** options.preserveP1PositionsFrom : état de jeu courant pour garder les positions des unités P1 (ex. Intercessor après 1-25). */
  startGameWithScenario: (
    scenarioFile: string,
    options?: { preserveP1PositionsFrom?: APIGameState | null }
  ) => Promise<void>;
  /** Callback appelé quand l'étape tutoriel change (ex. pour mettre l'IA en pause pendant 2-11). */
  onStepChange?: (step: TutorialStepDisplay | null) => void;
  /** Callback appelé quand l'IA doit être mise en pause (transition étape 2 ou popup 2-11/2-12/2-13 visible). */
  onPauseAIChange?: (pause: boolean) => void;
  /** Ref pour indiquer à useEngineAPI d'arrêter la boucle AI après chaque phase (étapes 2-11/2-12/2-13). */
  stopAiAfterPhaseChangeRef?: React.MutableRefObject<boolean>;
  /** Callback appelé quand le tutoriel est terminé (fin complète ou clic "Passer le tutoriel"). */
  onTutorialComplete?: () => void | Promise<void>;
  /** Étape 2-16 : POST /game/start PvE puis navigation (fourni par BoardWithAPI). */
  onGoToPveMode?: () => void | Promise<void>;
  children: React.ReactNode;
}

const STAGES_AI_PAUSED = ["2-11", "2-12", "2-13", "2-14"] as const;

export function TutorialProvider({
  isTutorialMode,
  gameState,
  startGameWithScenario,
  onStepChange,
  onPauseAIChange,
  tutorialPauseAiSyncRef,
  stopAiAfterPhaseChangeRef,
  onTutorialComplete,
  onGoToPveMode,
  children,
}: TutorialProviderProps) {
  const [steps, setSteps] = useState<TutorialStepDef[]>([]);
  const [currentEtape, setCurrentEtape] = useState(1);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [popupVisible, setPopupVisible] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [spotlightPosition, setSpotlightPosition] = useState<TutorialSpotlightPosition | null>(null);
  const [spotlightTablePositions, setSpotlightTablePositions] = useState<TutorialSpotlightPosition[] | null>(null);
  const [spotlightTurnPhasePositions, setSpotlightTurnPhasePositions] = useState<TutorialSpotlightPosition[] | null>(null);
  const [spotlightTutorialPopupAnchor, setSpotlightTutorialPopupAnchor] = useState<{
    centerX: number;
    bottomY: number;
  } | null>(null);
  const [spotlightLeftPanel, setSpotlightLeftPanel] = useState<TutorialSpotlightPosition | null>(null);
  const [spotlightRightPanel, setSpotlightRightPanel] = useState<TutorialSpotlightPosition | null>(null);
  const [leftPanelFogRects, setLeftPanelFogRectsState] = useState<TutorialSpotlightRect[]>([]);
  const setLeftPanelFogRects = useCallback((r: TutorialSpotlightRect[] | null) => {
    setLeftPanelFogRectsState(r ?? []);
  }, []);
  const [rightPanelFogRects, setRightPanelFogRectsState] = useState<TutorialSpotlightRect[]>([]);
  const setRightPanelFogRects = useCallback((r: TutorialSpotlightRect[] | null) => {
    setRightPanelFogRectsState(r ?? []);
  }, []);
  const [spotlightRangedWeaponsPositions, setSpotlightRangedWeaponsPositions] = useState<TutorialSpotlightPosition[] | null>(null);
  const [spotlightGameLogLastEntry, setSpotlightGameLogLastEntry] = useState<TutorialSpotlightPosition | null>(null);
  const [spotlightGameLogHeader, setSpotlightGameLogHeader] = useState<TutorialSpotlightPosition | null>(null);
  const [spotlightGameLogTopEntriesPositions, setSpotlightGameLogTopEntriesPositionsState] = useState<
    TutorialSpotlightPosition[]
  >([]);
  const setSpotlightGameLogTopEntriesPositions = useCallback((pos: TutorialSpotlightPosition[] | null) => {
    setSpotlightGameLogTopEntriesPositionsState(pos ?? []);
  }, []);
  const [spotlightEnemyUnitAttributes, setSpotlightEnemyUnitAttributes] = useState<TutorialSpotlightPosition | null>(null);
  const [spotlightP2UnitRowPositions, setSpotlightP2UnitRowPositionsState] = useState<TutorialSpotlightPosition[]>([]);
  const setSpotlightP2UnitRowPositions = useCallback((pos: TutorialSpotlightPosition[] | null) => {
    setSpotlightP2UnitRowPositionsState((prev) => {
      const next = pos ?? [];
      if (prev.length !== next.length) return next;
      const areEqual = next.every((n, i) => {
        const p = prev[i];
        if (!p || p.shape !== "rect" || n.shape !== "rect") return false;
        return (
          p.left === n.left &&
          p.top === n.top &&
          p.width === n.width &&
          p.height === n.height
        );
      });
      return areEqual ? prev : next;
    });
  }, []);
  const [spotlightBoardUnitPositions, setSpotlightBoardUnitPositionsState] = useState<TutorialSpotlightPosition[]>([]);
  const setSpotlightBoardUnitPositions = useCallback((pos: TutorialSpotlightPosition[] | null) => {
    setSpotlightBoardUnitPositionsState(pos ?? []);
  }, []);
  const [spotlightLayoutTick, setSpotlightLayoutTick] = useState(0);
  const spotlightLayoutRafRef = useRef<number | null>(null);
  const scheduleSpotlightLayoutTickBump = useCallback(() => {
    if (spotlightLayoutRafRef.current != null) return;
    spotlightLayoutRafRef.current = requestAnimationFrame(() => {
      spotlightLayoutRafRef.current = null;
      setSpotlightLayoutTick((n) => n + 1);
    });
  }, []);
  const [lastEnemyDeathPosition, setLastEnemyDeathPosition] = useState<{ col: number; row: number } | null>(null);
  const lastKnownEnemyPositionRef = useRef<{ col: number; row: number } | null>(null);
  const [tutorialLang, setTutorialLang] = useState<TutorialLang>("fr");
  const lastPhaseRef = useRef<string | null>(null);
  const lastFightSubphaseRef = useRef<string | null>(null);
  const onDeployShownForEtapeRef = useRef<Set<number>>(new Set());
  /** Après avancement manuel (onClosePopup → étape suivante), ne pas laisser l’effet phase_enter écraser l’index. */
  const skipNextPhaseTriggerRef = useRef(false);
  /** En cours de chargement scenario 1->2 : ne pas laisser l'effet phase reecrire l'etape (evite fog/popup 1-11). */
  const transitioningToEtape2Ref = useRef(false);
  /** Étapes 2-11/2-12/2-13 : l'utilisateur a cliqué Suivant → IA libérée pour exécuter la phase. */
  const [releasedSteps, setReleasedSteps] = useState<Set<string>>(() => new Set());

  /** Remesure des halos (coords viewport) au scroll / resize pendant que le tutoriel est ouvert. */
  useEffect(() => {
    if (!isTutorialMode || !popupVisible || skipped) return;
    const schedule = scheduleSpotlightLayoutTickBump;
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, { passive: true });
    document.addEventListener("scroll", schedule, { passive: true, capture: true });
    document.addEventListener("wheel", schedule, { passive: true, capture: true });
    window.addEventListener("touchmove", schedule, { passive: true, capture: true });
    const vv = window.visualViewport;
    if (vv) {
      vv.addEventListener("scroll", schedule);
      vv.addEventListener("resize", schedule);
    }
    schedule();
    return () => {
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule);
      document.removeEventListener("scroll", schedule, true);
      document.removeEventListener("wheel", schedule, true);
      window.removeEventListener("touchmove", schedule, true);
      if (vv) {
        vv.removeEventListener("scroll", schedule);
        vv.removeEventListener("resize", schedule);
      }
    };
  }, [isTutorialMode, popupVisible, skipped, scheduleSpotlightLayoutTickBump]);

  const stepsForEtape = useMemo(
    () =>
      steps
        .filter((s) => s.etape === currentEtape)
        .sort((a, b) => a.order - b.order),
    [steps, currentEtape]
  );

  const currentStep = useMemo((): TutorialStepDisplay | null => {
    if (stepsForEtape.length === 0 || currentStepIndex >= stepsForEtape.length) {
      return null;
    }
    const s = stepsForEtape[currentStepIndex];
    if (!s || !("title_fr" in s)) return null;
    const stage = getStageId(s);
    const uiBehavior = getTutorialUiBehavior(stage);
    let phase =
      s.trigger?.type === "phase_enter" && typeof s.trigger.phase === "string" && s.trigger.phase.trim() !== ""
        ? s.trigger.phase
        : s.trigger?.type === "fight_subphase_enter"
          ? "fight"
          : undefined;
    if (uiBehavior.phaseDisplayOverride != null) {
      phase = uiBehavior.phaseDisplayOverride;
    }
    return {
      title_fr: s.title_fr,
      title_en: s.title_en,
      body_fr: s.body_fr,
      body_en: s.body_en,
      stepKey: s.title_fr,
      stage,
      phase,
      advanceOnUnitClick: s.advance_on_unit_click === true,
      advanceOnMoveClick: s.advance_on_move_click === true,
      hideAdvanceIcon: s.hide_advance_icon === true,
      advanceOnWeaponClick:
        uiBehavior.forceAdvanceOnWeaponClick != null
          ? uiBehavior.forceAdvanceOnWeaponClick
          : s.advance_on_weapon_click === true,
      advanceOnWeaponName:
        typeof s.advance_on_weapon_name === "string" && s.advance_on_weapon_name.trim() !== ""
          ? s.advance_on_weapon_name.trim()
          : undefined,
      popupImage: typeof s.popup_image === "string" && s.popup_image.trim() !== "" ? s.popup_image : undefined,
      titleIcon: typeof s.title_icon === "string" && s.title_icon.trim() !== "" ? s.title_icon : undefined,
      popupShowMoveHex: s.popup_show_move_hex === true,
      popupShowGreenCircle: s.popup_show_green_circle === true,
      popupFirstLineWithIcon: s.popup_first_line_with_icon === true,
      popupPosition:
        s.popup_position === "center" || s.popup_position == null
          ? undefined
          : typeof s.popup_position === "object" && (s.popup_position.left != null || s.popup_position.top != null)
            ? {
                left: s.popup_position.left ?? "50%",
                top: s.popup_position.top ?? "50%",
              }
            : undefined,
      fog: s.fog,
      spotlightIds: Array.isArray(s.spotlightIds) ? s.spotlightIds : undefined,
      allowedClickSpotlightIds: Array.isArray(s.allowedClickSpotlightIds)
        ? s.allowedClickSpotlightIds
        : undefined,
    };
  }, [stepsForEtape, currentStepIndex]);
  const hasOnDeployStepForEtape = useMemo(
    () => stepsForEtape.some((s) => s.trigger.type === "on_deploy"),
    [stepsForEtape]
  );

  useLayoutEffect(() => {
    onStepChange?.(currentStep);
  }, [currentStep, onStepChange]);

  /** Pause IA : transition étape 2, ou phase move/shoot/charge/fight (sous-phases) non libérées par Suivant.
   * Basé sur la phase du jeu, pas sur popupVisible (évite que l'IA enchaîne avant affichage du popup). */
  const phase = gameState?.phase ?? null;
  const fightSubphase = gameState?.fight_subphase ?? null;
  const shouldPauseAI =
    transitioningToEtape2Ref.current ||
    (currentEtape === 2 &&
      phase != null &&
      ((phase === "move" && !releasedSteps.has("2-11")) ||
        (phase === "shoot" && !releasedSteps.has("2-12")) ||
        (phase === "charge" && !releasedSteps.has("2-13")) ||
        (phase === "fight" &&
          fightSubphase === "charging" &&
          !releasedSteps.has("2-14"))));
  if (tutorialPauseAiSyncRef) {
    tutorialPauseAiSyncRef.current = shouldPauseAI;
  }
  useLayoutEffect(() => {
    onPauseAIChange?.(shouldPauseAI);
  }, [shouldPauseAI, onPauseAIChange, phase, fightSubphase]);

  useLayoutEffect(() => {
    if (stopAiAfterPhaseChangeRef) {
      stopAiAfterPhaseChangeRef.current = isTutorialMode && currentEtape === 2;
    }
  }, [isTutorialMode, currentEtape, stopAiAfterPhaseChangeRef]);

  /** Reset tous les spotlights quand le popup se ferme. */
  useEffect(() => {
    if (!popupVisible) {
      setSpotlightPosition(null);
      setSpotlightTablePositions(null);
      setSpotlightTurnPhasePositions(null);
      setSpotlightTutorialPopupAnchor(null);
      setSpotlightLeftPanel(null);
      setSpotlightRightPanel(null);
      setLeftPanelFogRects([]);
      setRightPanelFogRects([]);
      setSpotlightRangedWeaponsPositions(null);
      setSpotlightGameLogLastEntry(null);
      setSpotlightGameLogHeader(null);
      setSpotlightGameLogTopEntriesPositions(null);
      setSpotlightEnemyUnitAttributes(null);
      setSpotlightP2UnitRowPositions([]);
      setSpotlightBoardUnitPositions([]);
      setLastEnemyDeathPosition(null);
    }
  }, [
    popupVisible,
    setLeftPanelFogRects,
    setRightPanelFogRects,
    setSpotlightP2UnitRowPositions,
    setSpotlightBoardUnitPositions,
    setSpotlightGameLogTopEntriesPositions,
  ]);

  useEffect(() => {
    if (!isTutorialMode) return;
    try {
      const runtimeData = getTutorialScenarioRuntimeData();
      if (!Array.isArray(runtimeData.steps)) {
        throw new Error("Tutorial runtime data does not contain a valid steps[]");
      }
      setSteps(runtimeData.steps.map((s: Record<string, unknown>) => normalizeStep(s)));
    } catch (err) {
      console.error("Tutorial steps load failed from tutorial_scenario.md:", err);
    }
  }, [isTutorialMode, tutorialScenarioYamlRevision]);

  const showStepForTrigger = useCallback(
    (triggerType: string, phaseOrSubphase?: string) => {
      const idx = stepsForEtape.findIndex((s, index) => {
        if (index < currentStepIndex) return false;
        if (s.trigger.type !== triggerType) return false;
        if (triggerType === "phase_enter" && phaseOrSubphase != null) {
          return s.trigger.phase === phaseOrSubphase;
        }
        if (triggerType === "fight_subphase_enter" && phaseOrSubphase != null) {
          return s.trigger.fight_subphase === phaseOrSubphase;
        }
        return true;
      });
      if (idx >= 0) {
        setCurrentStepIndex(idx);
        setPopupVisible(true);
        return true;
      }
      return false;
    },
    [stepsForEtape, currentStepIndex]
  );

  /** Force étape 2-11 quand on est en étape 2 et phase deployment (évite layout 1-11 après transition). */
  useLayoutEffect(() => {
    if (!isTutorialMode || skipped || steps.length === 0) return;
    const phase = gameState?.phase ?? null;
    if (currentEtape === 2 && phase === "deployment") {
      const stepsForEtape2 = steps.filter((s) => s.etape === 2).sort((a, b) => a.order - b.order);
      const idx211 = stepsForEtape2.findIndex((s) => s.order === 11);
      if (idx211 >= 0 && idx211 !== currentStepIndex) {
        setCurrentStepIndex(idx211);
        setPopupVisible(true);
      }
    }
  }, [isTutorialMode, skipped, currentEtape, currentStepIndex, gameState?.phase, steps]);

  useEffect(() => {
    if (!isTutorialMode || skipped || !gameState || steps.length === 0) return;
    if (transitioningToEtape2Ref.current) return;
    const phase = gameState.phase ?? null;

    if (
      phase !== "deployment" &&
      hasOnDeployStepForEtape &&
      !onDeployShownForEtapeRef.current.has(currentEtape)
    ) {
      if (showStepForTrigger("on_deploy")) {
        onDeployShownForEtapeRef.current.add(currentEtape);
      }
      if (phase != null) lastPhaseRef.current = phase;
      if (!onDeployShownForEtapeRef.current.has(currentEtape)) return;
    }

    if (phase != null && phase !== lastPhaseRef.current) {
      if (skipNextPhaseTriggerRef.current) {
        skipNextPhaseTriggerRef.current = false;
        lastPhaseRef.current = phase;
        return;
      }
      const phaseOrder = ["move", "shoot", "charge", "fight"];
      const lastPhaseIdx = phaseOrder.indexOf(lastPhaseRef.current ?? "");
      const newPhaseIdx = phaseOrder.indexOf(phase);
      // Étape 2 : si cascade (ex. move→charge sans phase shoot), afficher le prochain step (2-12)
      if (
        currentEtape === 2 &&
        stepsForEtape.length > 0 &&
        newPhaseIdx > lastPhaseIdx + 1 &&
        currentStepIndex < stepsForEtape.length - 1
      ) {
        const nextIdx = currentStepIndex + 1;
        if (nextIdx < stepsForEtape.length) {
          lastPhaseRef.current = phase;
          setCurrentStepIndex(nextIdx);
          setPopupVisible(true);
          return;
        }
      }
      lastPhaseRef.current = phase;
      showStepForTrigger("phase_enter", phase);
    }
  }, [
    isTutorialMode,
    skipped,
    gameState,
    gameState?.phase,
    currentEtape,
    currentStepIndex,
    stepsForEtape.length,
    steps.length,
    hasOnDeployStepForEtape,
    showStepForTrigger,
  ]);

  /** Étapes 2-14 / 2-15 : déclenchées par fight_subphase (étape 2 uniquement). */
  useEffect(() => {
    if (!isTutorialMode || skipped || !gameState || steps.length === 0) return;
    if (transitioningToEtape2Ref.current) return;
    if (currentEtape !== 2) {
      lastFightSubphaseRef.current = null;
      return;
    }
    const phase = gameState.phase ?? null;
    if (phase !== "fight") {
      lastFightSubphaseRef.current = null;
      return;
    }
    const fightSubphase = gameState.fight_subphase;
    if (fightSubphase == null || fightSubphase === "") {
      return;
    }
    if (fightSubphase === lastFightSubphaseRef.current) return;
    if (skipNextPhaseTriggerRef.current) {
      skipNextPhaseTriggerRef.current = false;
      lastFightSubphaseRef.current = fightSubphase;
      return;
    }
    lastFightSubphaseRef.current = fightSubphase;
    showStepForTrigger("fight_subphase_enter", fightSubphase);
  }, [
    isTutorialMode,
    skipped,
    gameState,
    gameState?.phase,
    gameState?.fight_subphase,
    steps.length,
    currentStepIndex,
    showStepForTrigger,
    currentEtape,
  ]);

  const hasLivingEnemyUnits = useMemo(() => {
    if (!gameState?.units) return false;
    const player2Units = gameState.units.filter((u) => Number(u.player) === 2);
    if (player2Units.length === 0) return false;
    const cache = gameState.units_cache as Record<string, { HP_CUR?: number }> | undefined;
    return player2Units.some((u) => {
      const id = String(u.id);
      const entry = cache?.[id];
      if (entry != null) {
        return (entry.HP_CUR ?? 0) > 0;
      }
      // Pas d’entrée cache (mort retiré du cache ou désync) : HP_CUR sur l’unité (API le synchronise)
      return typeof u.HP_CUR === "number" && u.HP_CUR > 0;
    });
  }, [gameState?.units, gameState?.units_cache]);

  useEffect(() => {
    const p2Unit = gameState?.units?.find((u) => Number(u.player) === 2);
    if (p2Unit && typeof p2Unit.col === "number" && typeof p2Unit.row === "number") {
      lastKnownEnemyPositionRef.current = { col: p2Unit.col, row: p2Unit.row };
    }
  }, [gameState?.units]);

  const hadEnemiesLastRef = useRef(true);
  useEffect(() => {
    if (!isTutorialMode || skipped || !startGameWithScenario) return;
    // Tant que les étapes ne sont pas chargées, ne pas interpréter « plus d’ennemis » :
    // sinon idx 1-25 introuvable → passage brutal à l’étape 2 sans preserveP1 (Hormagaunts cassés).
    if (steps.length === 0) return;
    if (gameState?.phase === "deployment") return;
    const justLostLastEnemy = hadEnemiesLastRef.current && !hasLivingEnemyUnits;
    hadEnemiesLastRef.current = hasLivingEnemyUnits;

    if (!justLostLastEnemy) return;

    if (currentEtape === 1) {
      // Option configurable: jouer les sous-étapes intermédiaires avant 1-25 même si la cible est déjà morte.
      const currentOrder = stepsForEtape[currentStepIndex]?.order;
      const currentStageId =
        stepsForEtape[currentStepIndex] != null ? getStageId(stepsForEtape[currentStepIndex]) : null;
      const sequentialSubstepsUntilOrder =
        currentStageId != null ? getTutorialUiBehavior(currentStageId).sequentialSubstepsUntilOrder : undefined;
      if (typeof currentOrder === "number" && Number.isFinite(currentOrder)) {
        const next124SubstepIdx = stepsForEtape.findIndex(
          (s, idx) =>
            idx > currentStepIndex &&
            s.order > currentOrder &&
            (typeof sequentialSubstepsUntilOrder === "number"
              ? s.order < sequentialSubstepsUntilOrder
              : false)
        );
        if (next124SubstepIdx >= 0) {
          const p2Unit = gameState?.units?.find((u) => Number(u.player) === 2);
          if (p2Unit && typeof p2Unit.col === "number" && typeof p2Unit.row === "number") {
            setLastEnemyDeathPosition({ col: p2Unit.col, row: p2Unit.row });
          } else if (lastKnownEnemyPositionRef.current != null) {
            setLastEnemyDeathPosition(lastKnownEnemyPositionRef.current);
          }
          setCurrentStepIndex(next124SubstepIdx);
          setPopupVisible(true);
          return;
        }
      }
      // Étape 1-24 → 1-25 : afficher la popup "Mort du termagant" au lieu de passer à l’étape 2
      const idx25 = stepsForEtape.findIndex((s) => getStageId(s) === "1-25");
      if (idx25 >= 0) {
        const p2Unit = gameState?.units?.find((u) => Number(u.player) === 2);
        if (p2Unit && typeof p2Unit.col === "number" && typeof p2Unit.row === "number") {
          setLastEnemyDeathPosition({ col: p2Unit.col, row: p2Unit.row });
        } else if (lastKnownEnemyPositionRef.current != null) {
          setLastEnemyDeathPosition(lastKnownEnemyPositionRef.current);
        }
        setSpotlightGameLogLastEntry(null);
        setCurrentStepIndex(idx25);
        setPopupVisible(true);
        return;
      }
      setLastEnemyDeathPosition(null);
      setCurrentEtape(2);
      setCurrentStepIndex(0);
      onDeployShownForEtapeRef.current.delete(2);
      startGameWithScenario(TUTORIAL_SCENARIOS[1]);
    } else if (currentEtape === 2) {
      // Tous les Hormagaunts morts : même flux que le bouton « Mode PvE » (2-16) — init PvE + navigation.
      if (onGoToPveMode) {
        void onGoToPveMode();
      } else {
        throw new Error(
          "TutorialProvider: onGoToPveMode is required when all P2 units are eliminated in etape 2"
        );
      }
    }
  }, [
    isTutorialMode,
    skipped,
    currentEtape,
    currentStepIndex,
    hasLivingEnemyUnits,
    gameState?.phase,
    gameState?.units,
    startGameWithScenario,
    onGoToPveMode,
    stepsForEtape,
    steps.length,
  ]);

  const prepareSkipNextPhaseTrigger = useCallback(() => {
    skipNextPhaseTriggerRef.current = true;
  }, []);

  const onDismissPopupOnly = useCallback(() => {
    setPopupVisible(false);
  }, []);

  const onClosePopup = useCallback(() => {
    const stage = stepsForEtape[currentStepIndex] ? getStageId(stepsForEtape[currentStepIndex]) : "";
    if (STAGES_AI_PAUSED.includes(stage as (typeof STAGES_AI_PAUSED)[number])) {
      setReleasedSteps((prev) => new Set(prev).add(stage));
      setPopupVisible(false);
      return;
    }
    if (currentStepIndex < stepsForEtape.length - 1) {
      skipNextPhaseTriggerRef.current = true;
      setCurrentStepIndex((i) => i + 1);
      const next = stepsForEtape[currentStepIndex + 1];
      if (next) {
        setPopupVisible(true);
      }
    } else {
      const nextEtape = currentEtape + 1;
      const hasNextEtape = steps.some((s) => s.etape === nextEtape);
      if (hasNextEtape) {
        skipNextPhaseTriggerRef.current = true;
        const advanceToNextEtape = () => {
          setCurrentEtape(nextEtape);
          setCurrentStepIndex(0);
          setPopupVisible(true);
        };
        if (currentEtape === 1 && nextEtape === 2 && startGameWithScenario && gameState) {
          transitioningToEtape2Ref.current = true;
          lastPhaseRef.current = "deployment";
          onPauseAIChange?.(true);
          startGameWithScenario(TUTORIAL_SCENARIOS[1], {
            preserveP1PositionsFrom: gameState as APIGameState,
          })
            .then(() => {
              advanceToNextEtape();
            })
            .catch(() => {
              advanceToNextEtape();
            })
            .finally(() => {
              transitioningToEtape2Ref.current = false;
            });
        } else {
          advanceToNextEtape();
          if (currentEtape === 2 && nextEtape === 3 && startGameWithScenario) {
            startGameWithScenario(TUTORIAL_SCENARIOS[2]);
          }
        }
      } else {
        setPopupVisible(false);
        onTutorialComplete?.();
      }
    }
  }, [
    currentStepIndex,
    stepsForEtape,
    currentEtape,
    steps,
    startGameWithScenario,
    gameState,
    onPauseAIChange,
    onTutorialComplete,
  ]);

  const onSkipTutorial = useCallback(() => {
    setSkipped(true);
    setPopupVisible(false);
    onTutorialComplete?.();
  }, [onTutorialComplete]);

  const value = useMemo<TutorialContextValue>(
    () =>
      isTutorialMode
        ? {
            isTutorialMode: true,
            currentStep: currentStep ?? null,
            popupVisible: popupVisible && !skipped,
            onClosePopup,
            onSkipTutorial,
            prepareSkipNextPhaseTrigger,
            currentEtape,
            gamePhase: gameState?.phase ?? null,
            tutorialLang,
            setTutorialLang,
            spotlightPosition,
            setSpotlightPosition,
            spotlightTablePositions,
            setSpotlightTablePositions,
            spotlightTurnPhasePositions,
            setSpotlightTurnPhasePositions,
            spotlightTutorialPopupAnchor,
            setSpotlightTutorialPopupAnchor,
            spotlightLeftPanel,
            setSpotlightLeftPanel,
            spotlightRightPanel,
            setSpotlightRightPanel,
            leftPanelFogRects,
            setLeftPanelFogRects,
            rightPanelFogRects,
            setRightPanelFogRects,
            spotlightRangedWeaponsPositions,
            setSpotlightRangedWeaponsPositions,
            spotlightGameLogLastEntry,
            setSpotlightGameLogLastEntry,
            spotlightGameLogHeader,
            setSpotlightGameLogHeader,
            spotlightGameLogTopEntriesPositions,
            setSpotlightGameLogTopEntriesPositions,
            spotlightEnemyUnitAttributes,
            setSpotlightEnemyUnitAttributes,
            spotlightP2UnitRowPositions,
            setSpotlightP2UnitRowPositions,
            spotlightBoardUnitPositions,
            setSpotlightBoardUnitPositions,
            spotlightLayoutTick,
            lastEnemyDeathPosition,
            onGoToPveMode,
            onDismissPopupOnly,
          }
        : {
            isTutorialMode: false,
            currentStep: null,
            popupVisible: false,
            onClosePopup: () => {},
            onSkipTutorial: () => {},
            prepareSkipNextPhaseTrigger: () => {},
            currentEtape: 1,
            gamePhase: null,
            tutorialLang: "fr" as const,
            setTutorialLang: () => {},
            spotlightPosition: null,
            setSpotlightPosition: () => {},
            spotlightTablePositions: null,
            setSpotlightTablePositions: () => {},
            spotlightTurnPhasePositions: null,
            setSpotlightTurnPhasePositions: () => {},
            spotlightTutorialPopupAnchor: null,
            setSpotlightTutorialPopupAnchor: () => {},
            spotlightLeftPanel: null,
            setSpotlightLeftPanel: () => {},
            spotlightRightPanel: null,
            setSpotlightRightPanel: () => {},
            leftPanelFogRects: [],
            setLeftPanelFogRects: () => {},
            rightPanelFogRects: [],
            setRightPanelFogRects: () => {},
            spotlightRangedWeaponsPositions: null,
            setSpotlightRangedWeaponsPositions: () => {},
            spotlightGameLogLastEntry: null,
            setSpotlightGameLogLastEntry: () => {},
            spotlightGameLogHeader: null,
            setSpotlightGameLogHeader: () => {},
            spotlightGameLogTopEntriesPositions: [],
            setSpotlightGameLogTopEntriesPositions: () => {},
            spotlightEnemyUnitAttributes: null,
            setSpotlightEnemyUnitAttributes: () => {},
            spotlightP2UnitRowPositions: [],
            setSpotlightP2UnitRowPositions: () => {},
            spotlightBoardUnitPositions: [],
            setSpotlightBoardUnitPositions: () => {},
            spotlightLayoutTick: 0,
            lastEnemyDeathPosition: null,
            onGoToPveMode: undefined,
            onDismissPopupOnly: () => {},
          },
    [
      isTutorialMode,
      currentStep,
      popupVisible,
      gameState?.phase,
      skipped,
      onClosePopup,
      onSkipTutorial,
      onGoToPveMode,
      onDismissPopupOnly,
      prepareSkipNextPhaseTrigger,
      currentEtape,
      tutorialLang,
      spotlightPosition,
      spotlightTablePositions,
      spotlightTurnPhasePositions,
      spotlightTutorialPopupAnchor,
      spotlightLeftPanel,
      spotlightRightPanel,
      leftPanelFogRects,
      setLeftPanelFogRects,
      rightPanelFogRects,
      setRightPanelFogRects,
      spotlightRangedWeaponsPositions,
      spotlightGameLogLastEntry,
      spotlightGameLogHeader,
      spotlightGameLogTopEntriesPositions,
      spotlightEnemyUnitAttributes,
      spotlightP2UnitRowPositions,
      setSpotlightP2UnitRowPositions,
      spotlightBoardUnitPositions,
      setSpotlightBoardUnitPositions,
      setSpotlightGameLogTopEntriesPositions,
      spotlightLayoutTick,
      lastEnemyDeathPosition,
    ]
  );

  return (
    <TutorialContext.Provider value={value}>
      {children}
    </TutorialContext.Provider>
  );
}
