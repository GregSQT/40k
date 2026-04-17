// frontend/src/components/BoardWithAPI.tsx
import type React from "react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import leaderEvolutionConfig from "../../../config/endless_duty/leader_evolution.json";
import meleeEvolutionConfig from "../../../config/endless_duty/melee_evolution.json";
import rangeEvolutionConfig from "../../../config/endless_duty/range_evolution.json";
import endlessDutyScenarioConfig from "../../../config/scenario_endless_duty.json";
import unitRulesConfig from "../../../config/unit_rules.json";
import "../App.css";
import type { MutableRefObject } from "react";
import { clearAuthSession, getAuthSession, markTutorialComplete } from "../auth/authStorage";
import {
  getTutorialUiBehavior,
  isTutorialUiDebugModeEnabled,
  matchesTutorialStagePattern,
  type TutorialSpotlightId,
} from "../config/tutorialUiRules";
import {
  TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT,
  TUTORIAL_STEP_TITLE_PHASE_TIR,
  TUTORIAL_STEP_TITLE_PHASES,
  TUTORIAL_STEP_TITLE_ROUNDS,
  TUTORIAL_STEP_TITLE_TURNS,
  TUTORIAL_STEP_TITLE_WEAPON_CHOICE,
  TUTORIAL_STEP_TITLES_HALO_LEFT,
  TUTORIAL_STEP_TITLES_MOVE_BUTTON_HALO,
  TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO,
  TutorialProvider,
  type TutorialSpotlightPosition,
  type TutorialSpotlightRect,
  useTutorial,
} from "../contexts/TutorialContext";
import { useEngineAPI } from "../hooks/useEngineAPI";
import { useGameConfig } from "../hooks/useGameConfig";
import { useGameLog } from "../hooks/useGameLog";
import type { GamePhase, GameState, PlayerId, TargetPreview, Unit } from "../types";
import type { DeploymentState } from "../types/game";
import BoardPvp, { type MeasureModeState } from "./BoardPvp";
import { ErrorBoundary } from "./ErrorBoundary";
import { GameLog } from "./GameLog";
import { SettingsMenu } from "./SettingsMenu";
import SharedLayout from "./SharedLayout";
import TooltipWrapper from "./TooltipWrapper";
import { TurnPhaseTracker } from "./TurnPhaseTracker";
import TutorialOverlay from "./TutorialOverlay";
import { UnitStatusTable } from "./UnitStatusTable";

type RuleChoicePrompt = {
  trigger: "on_deploy" | "turn_start" | "player_turn_start" | "phase_start" | "activation_start";
  phase?: "command" | "move" | "shoot" | "charge" | "fight";
  player: number;
  unit_id: string;
  rule_id: string;
  display_name: string;
  usage: "or" | "unique";
  options: Array<{
    display_rule_id: string;
    technical_rule_id: string;
    label: string;
  }>;
};

type EndlessDutySlotProfiles = {
  leader: string | null;
  melee: string | null;
  range: string | null;
};

type EndlessDutyPickState = {
  package: string | null;
  melee: string | null;
  ranged: string | null;
  secondary: string | null;
  special: string | null;
};

type EndlessDutySlotPicks = {
  leader: EndlessDutyPickState | null;
  melee: EndlessDutyPickState | null;
  range: EndlessDutyPickState | null;
};

type EvolutionCatalogConfig = {
  loadouts?: Array<{
    id?: string;
    profile?: string;
    picks?: Record<string, unknown>;
  }>;
  catalog?: Record<
    string,
    {
      base?: number;
      rows?: Array<{ slot?: string; pick?: string; cost?: number; implemented?: boolean }>;
      packages?: Array<{ id?: string; cost?: number; implemented?: boolean }>;
    }
  >;
};

function getProfileOptions(config: EvolutionCatalogConfig): string[] {
  if (!config.catalog || typeof config.catalog !== "object") {
    return [];
  }
  return Object.keys(config.catalog).sort((a, b) => a.localeCompare(b));
}

type PickOption = {
  id: string;
  cost: number;
  label: string;
};

type ProfilePickMenuData = {
  baseCost: number;
  primaryPackages: PickOption[];
  primaryMelee: PickOption[];
  ranged: PickOption[];
  secondary: PickOption[];
  special: PickOption[];
};

function buildPickMenusByProfile(config: EvolutionCatalogConfig): Map<string, ProfilePickMenuData> {
  const result = new Map<string, ProfilePickMenuData>();
  const catalog = config.catalog ?? {};
  for (const [profile, profileCatalog] of Object.entries(catalog)) {
    if (!profileCatalog) {
      continue;
    }
    const baseCost = Number(profileCatalog.base ?? 0);
    const rows = profileCatalog.rows ?? [];
    const packages = profileCatalog.packages ?? [];
    const data: ProfilePickMenuData = {
      baseCost,
      primaryPackages: [],
      primaryMelee: [],
      ranged: [],
      secondary: [],
      special: [],
    };
    for (const pkg of packages) {
      if (pkg.implemented === false) {
        continue;
      }
      if (typeof pkg.id !== "string") {
        continue;
      }
      const cost = Number(pkg.cost ?? 0);
      data.primaryPackages.push({
        id: pkg.id,
        cost,
        label: `${pkg.id} (+${cost})`,
      });
    }
    for (const row of rows) {
      if (row.implemented === false) {
        continue;
      }
      if (typeof row.slot !== "string" || typeof row.pick !== "string") {
        continue;
      }
      const cost = Number(row.cost ?? 0);
      const option: PickOption = {
        id: row.pick,
        cost,
        label: `${row.pick} (+${cost})`,
      };
      if (row.slot === "melee") {
        data.primaryMelee.push(option);
      } else if (row.slot === "ranged") {
        data.ranged.push(option);
      } else if (row.slot === "secondary") {
        data.secondary.push(option);
      } else if (row.slot === "equipment" || row.slot === "special") {
        data.special.push(option);
      }
    }
    result.set(profile, data);
  }
  return result;
}

function buildDefaultPicksByProfile(config: EvolutionCatalogConfig): Map<string, EndlessDutyPickState> {
  const defaults = new Map<string, EndlessDutyPickState>();
  const loadouts = config.loadouts ?? [];
  for (const loadout of loadouts) {
    const profile = typeof loadout.profile === "string" ? loadout.profile : null;
    if (!profile || defaults.has(profile)) {
      continue;
    }
    const picks = loadout.picks ?? {};
    defaults.set(profile, {
      package: typeof picks.package === "string" && picks.package !== "none" ? picks.package : null,
      melee: typeof picks.melee === "string" && picks.melee !== "none" ? picks.melee : null,
      ranged: typeof picks.ranged === "string" && picks.ranged !== "none" ? picks.ranged : null,
      secondary:
        typeof picks.secondary === "string" && picks.secondary !== "none" ? picks.secondary : null,
      special:
        (typeof picks.special === "string" && picks.special !== "none"
          ? picks.special
          : typeof picks.equipment === "string" && picks.equipment !== "none"
            ? picks.equipment
            : null),
    });
  }
  return defaults;
}

/** Étapes avec halo sur le turn phase tracker : Rounds=tour, Tours=P1/P2, Phases=phases. */
const TURN_PHASE_STEP_TITLES = [
  TUTORIAL_STEP_TITLE_ROUNDS,
  TUTORIAL_STEP_TITLE_TURNS,
  TUTORIAL_STEP_TITLE_PHASES,
] as const;
const RETREAT_ALERT_STORAGE_KEY = "retreatAlertEnabled";
const MODE_GUIDE_SEEN_PVE_STORAGE_KEY = "modeGuideSeen:pve";
const MODE_GUIDE_SEEN_PVP_STORAGE_KEY = "modeGuideSeen:pvp";
const MODE_GUIDES_ACTIVATED_STORAGE_KEY = "modeGuidesActivated";

function TutorialOverlayGate(): React.ReactNode {
  const tutorial = useTutorial();
  const popupVisible = tutorial?.popupVisible === true;
  const currentStep = tutorial?.currentStep ?? null;
  const title = currentStep?.stepKey ?? "";
  const stage = currentStep?.stage ?? "";
  const stepFog = currentStep?.fog;
  const forceLayout2_11 = tutorial?.currentEtape === 2 && tutorial?.gamePhase === "deployment";
  const isStage2_11Or12 = forceLayout2_11 || stage === "2-11" || stage === "2-12";
  const isStep1_6 = stage === "1-16";
  const isPhaseMoveStep = TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO.includes(
    title as (typeof TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO)[number]
  );
  const isTurnPhaseStep = TURN_PHASE_STEP_TITLES.includes(
    title as (typeof TURN_PHASE_STEP_TITLES)[number]
  );
  const isMoveButtonStep = TUTORIAL_STEP_TITLES_MOVE_BUTTON_HALO.includes(
    title as (typeof TUTORIAL_STEP_TITLES_MOVE_BUTTON_HALO)[number]
  );
  const stageMajor = parseInt((stage ?? "").split("-")[0] ?? "", 10);
  const isFrom2_1Onwards = !Number.isNaN(stageMajor) && stageMajor >= 2;
  const isStage124Family = stage === "1-24" || matchesTutorialStagePattern(stage, "1-24-*");
  const isHaloLeft =
    (TUTORIAL_STEP_TITLES_HALO_LEFT.includes(
      title as (typeof TUTORIAL_STEP_TITLES_HALO_LEFT)[number]
    ) ||
      stage === "1-15" || stage === "1-16" || stage === "1-23" || isStage124Family ||
      (isFrom2_1Onwards && !isStage2_11Or12)) &&
    stage !== "1-14";
  const isStep2_1 = stage === "1-21";
  const isStep2_2 = stage === "1-22";
  const isStep2_3 = stage === "1-23";
  const isStep2_4 =
    matchesTutorialStagePattern(stage, "1-24") || matchesTutorialStagePattern(stage, "1-24-*");
  const isStep1_25 = stage === "1-25";
  const stageUiBehavior = stage !== "" ? getTutorialUiBehavior(stage) : {};
  const configuredSpotlightIds = currentStep?.spotlightIds;
  const hasConfiguredSpotlights = configuredSpotlightIds != null;
  const hasSpotlight = (id: TutorialSpotlightId): boolean =>
    configuredSpotlightIds?.includes(id) === true;
  const debugMode = isTutorialUiDebugModeEnabled();
  const lastDebugStageRef = useRef<string | null>(null);
  useEffect(() => {
    if (!debugMode) return;
    if (!popupVisible || currentStep == null) return;
    if (lastDebugStageRef.current === stage) return;
    lastDebugStageRef.current = stage;
    console.info("[tutorial-ui-debug]", {
      stage,
      spotlightIds: configuredSpotlightIds ?? null,
      allowedClickSpotlightIds: currentStep.allowedClickSpotlightIds ?? null,
      forceNoFog: stageUiBehavior.forceNoFog ?? false,
      forceRightPanelFog: stageUiBehavior.forceRightPanelFog ?? false,
      overlayBackdropOpacity: stageUiBehavior.overlayBackdropOpacity ?? null,
    });
  }, [debugMode, popupVisible, currentStep, stage, stageUiBehavior, configuredSpotlightIds]);
  if (!popupVisible || currentStep == null) return null;
  const isStep2_2Or3Or4 = isStep2_2 || isStep2_3 || isStep2_4;
  const isShootButtonStep =
    title === TUTORIAL_STEP_TITLE_PHASE_TIR || title === TUTORIAL_STEP_TITLE_WEAPON_CHOICE;
  const needsTurnPhaseHalo =
    isTurnPhaseStep ||
    isMoveButtonStep ||
    isShootButtonStep ||
    stage === "1-14" ||
    stage === "1-14" ||
    stage === "1-15" ||
    stage === "1-16" ||
    stage === "1-21" ||
    stage === "1-22" ||
    stage === "1-23" ||
    stage === "1-24" ||
    matchesTutorialStagePattern(stage, "1-24-*") ||
    stage === "1-25" ||
    stage === "2-11" ||
    stage === "2-12" ||
    stage === "3-1";
  const turnPhaseSpotlights = (
    hasConfiguredSpotlights
      ? hasSpotlight("turnPhase.all")
      : needsTurnPhaseHalo
  )
    ? tutorial.spotlightTurnPhasePositions
    : null;
  const leftPanelSpotlight = (
    hasConfiguredSpotlights
      ? hasSpotlight("panel.left")
      : isHaloLeft || isStage2_11Or12
  )
    ? tutorial.spotlightLeftPanel
    : null;
  const gameLogLastEntrySpotlight = (
    hasConfiguredSpotlights
      ? hasSpotlight("gamelog.lastEntry")
      : isStep2_1 || isStep2_4
  )
    ? tutorial.spotlightGameLogLastEntry
    : null;
  const gameLogHeaderSpotlight = (
    hasConfiguredSpotlights
      ? hasSpotlight("gamelog.header")
      : isStep2_1 || isStep2_4 || isStep1_25
  )
    ? tutorial.spotlightGameLogHeader
    : null;
  const gameLogTopEntriesSpotlights = (
    hasConfiguredSpotlights
      ? hasSpotlight("gamelog.last2Entries")
      : isStep2_1 || isStep2_4 || isStep1_25
  )
    ? tutorial.spotlightGameLogTopEntriesPositions
    : [];
  /** En 1-25 : uniquement le header (ligne du haut), jamais la dernière ligne. */
  const gameLogSpotlights =
    stage === "1-25"
      ? gameLogHeaderSpotlight
        ? [gameLogHeaderSpotlight]
        : []
      : [
          ...((isStep2_1 || isStep2_4) && gameLogLastEntrySpotlight
            ? [gameLogLastEntrySpotlight]
            : []),
          ...((isStep2_1 || isStep2_4 || isStep1_25) && gameLogHeaderSpotlight
            ? [gameLogHeaderSpotlight]
            : []),
        ];
  const tableSpotlights = (
    hasConfiguredSpotlights
      ? hasSpotlight("table.p1.rangedWeapons") || hasSpotlight("table.p2.attributes")
      : isStep2_2Or3Or4
  )
    ? [
        ...(hasConfiguredSpotlights
          ? hasSpotlight("table.p1.rangedWeapons")
            ? (tutorial.spotlightRangedWeaponsPositions ?? [])
            : []
          : (tutorial.spotlightRangedWeaponsPositions ?? [])),
        ...(hasConfiguredSpotlights
          ? hasSpotlight("table.p2.attributes") && tutorial.spotlightEnemyUnitAttributes
            ? [tutorial.spotlightEnemyUnitAttributes]
            : []
          : tutorial.spotlightEnemyUnitAttributes
            ? [tutorial.spotlightEnemyUnitAttributes]
            : []),
      ]
    : isStep1_25
      ? (tutorial.spotlightRangedWeaponsPositions ?? [])
      : isStep1_6
        ? (tutorial.spotlightRangedWeaponsPositions ?? [])
        : isPhaseMoveStep
          ? (tutorial.spotlightTablePositions ?? [])
          : [];
  const p2UnitSpotlights = (
    hasConfiguredSpotlights
      ? hasSpotlight("table.p2.unitRows")
      : isStage2_11Or12
  )
    ? (tutorial.spotlightP2UnitRowPositions ?? [])
    : [];
  const boardUnitSpotlights = (
    hasConfiguredSpotlights
      ? hasSpotlight("board.unitRows")
      : isStage2_11Or12
  )
    ? (tutorial.spotlightBoardUnitPositions ?? [])
    : [];
  const toSpotlightRect = (element: Element | null): TutorialSpotlightRect[] => {
    if (!(element instanceof HTMLElement)) return [];
    const rect = element.getBoundingClientRect();
    if (!Number.isFinite(rect.width) || !Number.isFinite(rect.height) || rect.width <= 0 || rect.height <= 0) {
      return [];
    }
    return [
      {
        shape: "rect",
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      },
    ];
  };
  const guideP1ChangeRosterSpotlight = toSpotlightRect(
    document.querySelector(".deployment-panel__change-roster--player1")
  );
  const guideP2ChangeRosterSpotlight = toSpotlightRect(
    document.querySelector(".deployment-panel__change-roster--player2")
  );
  const guideStartDeploymentSpotlight = toSpotlightRect(document.querySelector(".test-start-bar__button"));
  const guideP1RosterSpotlight = toSpotlightRect(document.querySelector(".deployment-panel__roster--player1"));
  const guideP1DeploymentZoneSpotlight =
    leftPanelSpotlight != null
      ? [leftPanelSpotlight]
      : toSpotlightRect(document.querySelector(".game-board-section"));
  const spotlightCatalog: Record<TutorialSpotlightId, TutorialSpotlightPosition[]> = {
    "board.activeUnit": tutorial.spotlightPosition ? [tutorial.spotlightPosition] : [],
    "table.p1.nameM": (hasConfiguredSpotlights ? hasSpotlight("table.p1.nameM") : isPhaseMoveStep)
      ? (tutorial.spotlightTablePositions ?? [])
      : [],
    "table.p1.rangedWeapons": tutorial.spotlightRangedWeaponsPositions ?? [],
    "table.p2.attributes": tutorial.spotlightEnemyUnitAttributes
      ? [tutorial.spotlightEnemyUnitAttributes]
      : [],
    "table.p2.unitRows": p2UnitSpotlights,
    "board.unitRows": boardUnitSpotlights,
    "turnPhase.all":
      (hasConfiguredSpotlights ? hasSpotlight("turnPhase.all") : needsTurnPhaseHalo) &&
      turnPhaseSpotlights
        ? turnPhaseSpotlights
        : [],
    "panel.left":
      (hasConfiguredSpotlights ? hasSpotlight("panel.left") : isHaloLeft || isStage2_11Or12) &&
      leftPanelSpotlight
        ? [leftPanelSpotlight]
        : [],
    "gamelog.lastEntry":
      (isStep2_1 || isStep2_4) && gameLogLastEntrySpotlight ? [gameLogLastEntrySpotlight] : [],
    "gamelog.header":
      (isStep2_1 || isStep2_4 || isStep1_25) && gameLogHeaderSpotlight
        ? [gameLogHeaderSpotlight]
        : [],
    "gamelog.last2Entries": gameLogTopEntriesSpotlights ?? [],
    "guide.p1.changeRoster": guideP1ChangeRosterSpotlight,
    "guide.p2.changeRoster": guideP2ChangeRosterSpotlight,
    "guide.startDeployment": guideStartDeploymentSpotlight,
    "guide.p1.deploymentZone": guideP1DeploymentZoneSpotlight,
    "guide.p1.roster": guideP1RosterSpotlight,
  };
  const getSpotlightPositionsById = (id: string): TutorialSpotlightPosition[] => {
    if (!(id in spotlightCatalog)) {
      throw new Error(`Unknown tutorial spotlight id: ${id}`);
    }
    return spotlightCatalog[id as TutorialSpotlightId];
  };
  const legacySpotlights = [
    tutorial.spotlightPosition ?? null,
    ...tableSpotlights,
    ...p2UnitSpotlights,
    ...boardUnitSpotlights,
    ...(needsTurnPhaseHalo && turnPhaseSpotlights ? turnPhaseSpotlights : []),
    ...((isHaloLeft || isStage2_11Or12) && leftPanelSpotlight ? [leftPanelSpotlight] : []),
    ...gameLogSpotlights,
  ].filter(Boolean) as TutorialSpotlightPosition[];
  const spotlights =
    configuredSpotlightIds != null
      ? configuredSpotlightIds.flatMap((id) => getSpotlightPositionsById(id))
      : legacySpotlights;
  const configuredAllowedClickIds = currentStep.allowedClickSpotlightIds;
  const allowedClickSpotlights =
    configuredAllowedClickIds != null
      ? configuredAllowedClickIds.flatMap((id) => getSpotlightPositionsById(id))
      : configuredSpotlightIds != null
        ? spotlights
        : isStep2_2
          ? ([
              tutorial.spotlightPosition ?? null,
              ...(tutorial.spotlightRangedWeaponsPositions ?? []),
              ...(needsTurnPhaseHalo && turnPhaseSpotlights ? turnPhaseSpotlights : []),
              ...((isHaloLeft || isStage2_11Or12) && leftPanelSpotlight
                ? [leftPanelSpotlight]
                : []),
              ...((isStep2_1 || isStep2_4) && gameLogLastEntrySpotlight
                ? [gameLogLastEntrySpotlight]
                : []),
              ...((isStep2_1 || isStep2_4) && gameLogHeaderSpotlight
                ? [gameLogHeaderSpotlight]
                : []),
            ].filter(Boolean) as TutorialSpotlightPosition[])
          : spotlights;
  const debugSpotlightLabels =
    debugMode && configuredSpotlightIds != null
      ? configuredSpotlightIds.flatMap((id) => {
          const positions = getSpotlightPositionsById(id);
          return positions.map((position, idx) => ({
            id: positions.length > 1 ? `${id}[${idx}]` : id,
            position,
          }));
        })
      : [];

  // 1-15 : fog rects 2 bandes. 2-11 : pas de fog rect (l'overlay masque déjà tout sauf le halo board bas).
  // Éviter double fog en partie supérieure droite (overlay + fog droit se superposaient).
  const fogLeft = stepFog?.leftPanel === true ? tutorial.leftPanelFogRects : null;
  const fogRight = stepFog?.rightPanel === true ? tutorial.rightPanelFogRects : null;
  return (
    <TutorialOverlay
      step={currentStep}
      lang={tutorial.tutorialLang}
      onLangChange={tutorial.setTutorialLang}
      onClose={tutorial.onClosePopup}
      onSkipTutorial={tutorial.onSkipTutorial}
      onGoToPveMode={tutorial.onGoToPveMode}
      onDismissPopupOnly={tutorial.onDismissPopupOnly}
      spotlights={spotlights}
      allowedClickSpotlights={allowedClickSpotlights}
      fogLeftPanelRects={fogLeft}
      fogRightPanelRects={fogRight}
      debugSpotlightLabels={debugSpotlightLabels}
      tutorialPopupAnchor={tutorial.spotlightTutorialPopupAnchor}
      panelLeftSpotlightForLayout={
        tutorial.spotlightLeftPanel?.shape === "rect" ? tutorial.spotlightLeftPanel : null
      }
      tableNameMSpotlightRectsForLayout={
        stage === "1-15" && Array.isArray(tutorial.spotlightTablePositions)
          ? tutorial.spotlightTablePositions.filter((s): s is TutorialSpotlightRect => s.shape === "rect")
          : null
      }
    />
  );
}

/** TurnPhaseTracker avec halos tutoriel (Rounds / Tours / Phases / bouton Move). */
function TurnPhaseTrackerWithTutorial(
  props: React.ComponentProps<typeof TurnPhaseTracker>
): React.ReactElement {
  const tutorial = useTutorial();
  const title = tutorial?.popupVisible ? (tutorial?.currentStep?.stepKey ?? null) : null;
  const stage = tutorial?.currentStep?.stage ?? "";
  const showTurnPhaseRects =
    tutorial?.currentStep?.spotlightIds?.includes("turnPhase.all") === true;
  const forceLayout2_11 = tutorial?.currentEtape === 2 && tutorial?.gamePhase === "deployment";
  const effectiveTitleForRects = showTurnPhaseRects
    ? stage === "1-11"
      ? TUTORIAL_STEP_TITLE_ROUNDS
      : stage === "1-12"
        ? TUTORIAL_STEP_TITLE_TURNS
        : stage === "1-13"
          ? TUTORIAL_STEP_TITLE_PHASES
          : stage === "1-14" || stage === "1-15" || stage === "1-16"
            ? TUTORIAL_STEP_TITLE_PHASE_MOUVEMENT
            : forceLayout2_11 || stage === "2-11" || stage === "2-12"
              ? stage
              : stage === "1-21" ||
                  stage === "1-22" ||
                  stage === "1-23" ||
                  stage === "1-24" ||
                  matchesTutorialStagePattern(stage, "1-24-*") ||
                  stage === "1-25" ||
                  stage === "3-1"
                ? TUTORIAL_STEP_TITLE_PHASE_TIR
                : (title ?? undefined)
    : undefined;
  useEffect(() => {
    if (!showTurnPhaseRects && tutorial?.setSpotlightTurnPhasePositions) {
      tutorial.setSpotlightTurnPhasePositions(null);
    }
    if (!showTurnPhaseRects && tutorial?.setSpotlightTutorialPopupAnchor) {
      tutorial.setSpotlightTutorialPopupAnchor(null);
    }
  }, [showTurnPhaseRects, tutorial?.setSpotlightTurnPhasePositions, tutorial?.setSpotlightTutorialPopupAnchor]);
  return (
    <TurnPhaseTracker
      {...props}
      tutorialStepTitle={showTurnPhaseRects ? effectiveTitleForRects : undefined}
      onTutorialRects={tutorial?.setSpotlightTurnPhasePositions}
      onTutorialPopupAnchor={tutorial?.setSpotlightTutorialPopupAnchor}
    />
  );
}

/** Wrapper du PANNEAU GAUCHE (board) : rapporte son rect pour le halo (zone sans brouillard) et, en 1-15, la moitié haute pour le fog. En 2-11/2-12 : fog rect rows 0-11 (partie haute), partie basse sans fog. */
function BoardColumnWithTutorial({
  children,
  boardRows = 21,
}: {
  children: React.ReactNode;
  boardCols?: number;
  boardRows?: number;
}): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const tutorial = useTutorial();
  const stage = tutorial?.currentStep?.stage ?? "";
  const stepFog = tutorial?.currentStep?.fog;
  const stageUiBehavior = stage !== "" ? getTutorialUiBehavior(stage) : null;
  const forceNoFog = stageUiBehavior?.forceNoFog === true;
  const forceLayout2_11 = tutorial?.currentEtape === 2 && tutorial?.gamePhase === "deployment";
  const isStage2_11Or12 = forceLayout2_11 || stage === "2-11" || stage === "2-12";
  const hasLeftPanelFog = stepFog?.leftPanel === true;
  const hasBoardTopBandFog = stepFog?.boardTopBand === true;
  const wantsPanelLeftSpotlight =
    tutorial?.currentStep?.spotlightIds?.includes("panel.left") === true;
  const isPhaseMoveStep = Boolean(
    tutorial?.popupVisible &&
      tutorial?.currentStep?.stepKey &&
      TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO.includes(
        tutorial.currentStep.stepKey as (typeof TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO)[number]
      )
  );
  const needsMeasure =
    wantsPanelLeftSpotlight ||
    isPhaseMoveStep ||
    isStage2_11Or12 ||
    hasLeftPanelFog ||
    hasBoardTopBandFog;
  useLayoutEffect(() => {
    if (!tutorial?.setSpotlightLeftPanel) return;
    if (!needsMeasure) {
      tutorial.setSpotlightLeftPanel(null);
      tutorial?.setLeftPanelFogRects?.(null);
      return;
    }
    let cancelled = false;
    const measure = () => {
      if (cancelled) return;
      const el = ref.current?.parentElement ?? ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      const viewportWidth = typeof window !== "undefined" ? window.innerWidth : 1920;
      if (r.left > viewportWidth * 0.6) return;
      if (hasLeftPanelFog && !forceNoFog) {
        const bandHeight = r.height / 4;
        tutorial.setSpotlightLeftPanel({
          shape: "rect",
          left: r.left,
          top: r.top + r.height / 2,
          width: r.width,
          height: r.height / 2,
        });
        tutorial.setLeftPanelFogRects?.([
          { shape: "rect", left: r.left, top: r.top, width: r.width, height: bandHeight },
          {
            shape: "rect",
            left: r.left,
            top: r.top + bandHeight,
            width: r.width,
            height: bandHeight,
          },
        ]);
      } else if (hasBoardTopBandFog) {
        // 2-11 uniquement : fog partie haute (rows 0-11). À partir de 2-12, plus de fog.
        const fogRows = 12;
        const fogHeight = r.height * Math.min(1, fogRows / Math.max(1, boardRows));
        tutorial.setSpotlightLeftPanel({
          shape: "rect",
          left: r.left,
          top: r.top + fogHeight,
          width: r.width,
          height: r.height - fogHeight,
        });
        tutorial.setLeftPanelFogRects?.(null);
      } else if (isStage2_11Or12) {
        // 2-12+ : plus de fog nulle part, panneau entier visible.
        tutorial.setSpotlightLeftPanel({
          shape: "rect",
          left: r.left,
          top: r.top,
          width: r.width,
          height: r.height,
        });
        tutorial.setLeftPanelFogRects?.(null);
      } else {
        tutorial.setSpotlightLeftPanel(
          wantsPanelLeftSpotlight
            ? { shape: "rect", left: r.left, top: r.top, width: r.width, height: r.height }
            : null
        );
        tutorial.setLeftPanelFogRects?.(null);
      }
    };
    measure();
    const raf = requestAnimationFrame(() => {
      if (cancelled) return;
      measure();
      requestAnimationFrame(() => {
        if (!cancelled) measure();
      });
    });
    const t = setTimeout(() => {
      if (!cancelled) measure();
    }, 30);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      clearTimeout(t);
      tutorial.setSpotlightLeftPanel(null);
      tutorial.setLeftPanelFogRects?.(null);
    };
  }, [
    needsMeasure,
    wantsPanelLeftSpotlight,
    hasLeftPanelFog,
    hasBoardTopBandFog,
    forceNoFog,
    isStage2_11Or12,
    boardRows,
    tutorial?.setSpotlightLeftPanel,
    tutorial?.setLeftPanelFogRects,
    tutorial?.spotlightLayoutTick,
  ]);
  return (
    <div ref={ref} className="board-column-overlay-anchor">
      {children}
    </div>
  );
}

const GAME_LOG_LINE_HEIGHT_PX = 28;

/** GameLog avec rappel du rect de la dernière ligne pour halo tutoriel 1-21 ; en 1-24 agrandit d'une ligne par tir. En 1-25 halo sur la ligne du haut (header) uniquement. */
function GameLogWithTutorialSpotlight(
  props: React.ComponentProps<typeof GameLog>
): React.ReactElement {
  const tutorial = useTutorial();
  const stage = tutorial?.currentStep?.stage ?? "";
  const isStep2_4 =
    tutorial?.popupVisible &&
    (matchesTutorialStagePattern(stage, "1-24") || matchesTutorialStagePattern(stage, "1-24-*"));
  const isStep1_25 = tutorial?.popupVisible && stage === "1-25";
  const shootEventCount = (props.events ?? []).filter((e) => e.type === "shoot").length;
  const baseHeight = props.availableHeight ?? 220;
  const availableHeight = isStep2_4
    ? baseHeight + shootEventCount * GAME_LOG_LINE_HEIGHT_PX
    : baseHeight;
  const reportGameLogHeaderRect =
    tutorial?.currentStep?.spotlightIds?.includes("gamelog.header") === true;
  const reportGameLogLastEntryRect =
    tutorial?.currentStep?.spotlightIds?.includes("gamelog.lastEntry") === true;
  const reportGameLogTopTwoEntriesRects =
    tutorial?.currentStep?.spotlightIds?.includes("gamelog.last2Entries") === true;
  // En 1-25 : ne pas utiliser le rect "dernière ligne", pour que le halo reste sur la ligne du haut (header) uniquement
  useEffect(() => {
    if (isStep1_25 && tutorial?.setSpotlightGameLogLastEntry) {
      tutorial.setSpotlightGameLogLastEntry(null);
    }
  }, [isStep1_25, tutorial?.setSpotlightGameLogLastEntry]);
  useEffect(() => {
    if (!reportGameLogTopTwoEntriesRects && tutorial?.setSpotlightGameLogTopEntriesPositions) {
      tutorial.setSpotlightGameLogTopEntriesPositions(null);
    }
  }, [reportGameLogTopTwoEntriesRects, tutorial?.setSpotlightGameLogTopEntriesPositions]);
  return (
    <GameLog
      {...props}
      availableHeight={availableHeight}
      onLastEntryRect={
        reportGameLogLastEntryRect
          ? (tutorial?.setSpotlightGameLogLastEntry ?? undefined)
          : undefined
      }
      onHeaderRect={
        reportGameLogHeaderRect ? (tutorial?.setSpotlightGameLogHeader ?? undefined) : undefined
      }
      onTopTwoEntriesRects={
        reportGameLogTopTwoEntriesRects
          ? (tutorial?.setSpotlightGameLogTopEntriesPositions ?? undefined)
          : undefined
      }
    />
  );
}

/** Wrapper du PANNEAU DROIT (unit-status-tables) : rapporte son rect pour le halo étape 5 ou fog 2-11. */
function RightColumnTutorialSpotlight({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const tutorial = useTutorial();
  const stage = tutorial?.currentStep?.stage ?? "";
  const stepFog = tutorial?.currentStep?.fog;
  const stageUiBehavior = stage !== "" ? getTutorialUiBehavior(stage) : null;
  const forceNoFog = stageUiBehavior?.forceNoFog === true;
  const forceLayout2_11 = tutorial?.currentEtape === 2 && tutorial?.gamePhase === "deployment";
  const isStage2_11Only = forceLayout2_11 || stage === "2-11";
  const isStage2_12Only = stage === "2-12";
  const isStage2_13Only = stage === "2-13";
  const forceRightPanelFog = stageUiBehavior?.forceRightPanelFog === true;
  const shouldShowRightFog =
    stepFog?.rightPanel === true || forceRightPanelFog || (isStage2_11Only && !forceNoFog);
  const isPhaseMoveStep = Boolean(
    tutorial?.popupVisible &&
      tutorial?.currentStep?.stepKey &&
      TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO.includes(
        tutorial.currentStep.stepKey as (typeof TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO)[number]
      )
  );
  useLayoutEffect(() => {
    if (!tutorial?.setSpotlightRightPanel) return;
    if (!isPhaseMoveStep && !isStage2_12Only && !isStage2_13Only) {
      tutorial.setSpotlightRightPanel(null);
    }
    if (!tutorial?.setRightPanelFogRects) return;
    if (!shouldShowRightFog) {
      tutorial.setRightPanelFogRects(null);
    }
  }, [
    isPhaseMoveStep,
    isStage2_12Only,
    isStage2_13Only,
    shouldShowRightFog,
    tutorial?.setSpotlightRightPanel,
    tutorial?.setRightPanelFogRects,
  ]);
  useLayoutEffect(() => {
    if (!tutorial?.setSpotlightRightPanel || !tutorial?.setRightPanelFogRects) return;
    if (
      !isPhaseMoveStep &&
      !isStage2_11Only &&
      !isStage2_12Only &&
      !isStage2_13Only &&
      !shouldShowRightFog
    )
      return;
    let cancelled = false;
    const measure = () => {
      if (cancelled) return;
      const el = ref.current?.parentElement ?? ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      if (isPhaseMoveStep || isStage2_12Only || isStage2_13Only) {
        tutorial.setSpotlightRightPanel({
          shape: "rect",
          left: r.left,
          top: r.top,
          width: r.width,
          height: r.height,
        });
      } else {
        tutorial.setSpotlightRightPanel(null);
      }
      if (shouldShowRightFog) {
        tutorial.setRightPanelFogRects([
          { shape: "rect", left: r.left, top: r.top, width: r.width, height: r.height },
        ]);
      }
    };
    measure();
    const raf = requestAnimationFrame(() => {
      if (cancelled) return;
      measure();
      requestAnimationFrame(() => {
        if (!cancelled) measure();
      });
    });
    const t = setTimeout(() => {
      if (!cancelled) measure();
    }, 30);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      clearTimeout(t);
      tutorial.setSpotlightRightPanel(null);
      tutorial.setRightPanelFogRects?.(null);
    };
  }, [
    isPhaseMoveStep,
    isStage2_11Only,
    isStage2_12Only,
    isStage2_13Only,
    shouldShowRightFog,
    tutorial?.setSpotlightRightPanel,
    tutorial?.setRightPanelFogRects,
    tutorial?.spotlightLayoutTick,
  ]);
  return (
    <div ref={ref} style={{ display: "contents" }}>
      {children}
    </div>
  );
}

/** BoardPvp avec interception clic Intercessor (advance_on_unit_click) et confirmation déplacement (advance_on_move_click). */
function BoardPvpWithTutorialAdvance(
  props: React.ComponentProps<typeof BoardPvp>
): React.ReactElement {
  const tutorial = useTutorial();
  const wrappedOnSelectUnit = useCallback(
    (unitId: number | string | null) => {
      if (unitId != null) {
        const unit = props.units.find((u) => u.id === unitId || u.id === Number(unitId));
        if (
          unit &&
          Number(unit.player) === 2 &&
          (tutorial?.currentStep?.stage === "1-22" || tutorial?.currentStep?.stage === "1-23")
        ) {
          return;
        }
        if (
          tutorial?.currentStep?.advanceOnUnitClick &&
          tutorial?.onClosePopup &&
          Number(unit?.player) === 1
        ) {
          tutorial.onClosePopup();
        }
      }
      props.onSelectUnit(unitId);
    },
    [
      tutorial?.currentStep?.advanceOnUnitClick,
      tutorial?.currentStep?.stage,
      tutorial?.onClosePopup,
      props.onSelectUnit,
      props.units,
    ]
  );
  /** Avance (1-16 → suite) à la confirmation du move (clic sur l’icône unité). */
  const wrappedOnConfirmMove = useCallback(async () => {
    const isStep1_6 = tutorial?.currentStep?.stage === "1-16";
    if (isStep1_6 && tutorial?.prepareSkipNextPhaseTrigger) {
      tutorial.prepareSkipNextPhaseTrigger();
    }
    await props.onConfirmMove?.();
    if (isStep1_6 && tutorial?.onClosePopup) {
      tutorial.onClosePopup();
    }
  }, [
    props.onConfirmMove,
    tutorial?.currentStep?.stage,
    tutorial?.onClosePopup,
    tutorial?.prepareSkipNextPhaseTrigger,
  ]);

  /** Avance (1-15 → 1-16) au choix de la case verte (destination), avant la confirmation. */
  const wrappedOnStartMovePreview = useCallback(
    (unitId: number | string, col: number | string, row: number | string) => {
      const isStep1_5 = tutorial?.currentStep?.stage === "1-15";
      if (isStep1_5 && tutorial?.prepareSkipNextPhaseTrigger) {
        tutorial.prepareSkipNextPhaseTrigger();
      }
      props.onStartMovePreview?.(unitId, col, row);
      if (isStep1_5 && tutorial?.onClosePopup) {
        tutorial.onClosePopup();
      }
    },
    [
      props.onStartMovePreview,
      tutorial?.currentStep?.stage,
      tutorial?.onClosePopup,
      tutorial?.prepareSkipNextPhaseTrigger,
    ]
  );

  const wrappedOnDirectMove = useCallback(
    async (unitId: number | string, col: number | string, row: number | string) => {
      if (tutorial?.currentStep?.advanceOnMoveClick && tutorial?.prepareSkipNextPhaseTrigger) {
        tutorial.prepareSkipNextPhaseTrigger();
      }
      await props.onDirectMove?.(unitId, col, row);
      if (tutorial?.currentStep?.advanceOnMoveClick && tutorial?.onClosePopup) {
        tutorial.onClosePopup();
      }
    },
    [
      props.onDirectMove,
      tutorial?.currentStep?.advanceOnMoveClick,
      tutorial?.onClosePopup,
      tutorial?.prepareSkipNextPhaseTrigger,
    ]
  );

  // Avancer 1-22 → 1-23 quand le joueur ouvre le menu de sélection d’arme (clic sur l’icône)
  const stage = tutorial?.currentStep?.stage ?? "";
  useEffect(() => {
    if (stage !== "1-22" || !tutorial?.currentStep?.advanceOnWeaponClick || !tutorial?.onClosePopup)
      return;
    const handler = () => tutorial.onClosePopup();
    window.addEventListener("weaponMenuOpened", handler);
    return () => window.removeEventListener("weaponMenuOpened", handler);
  }, [stage, tutorial?.currentStep?.advanceOnWeaponClick, tutorial?.onClosePopup]);

  // Avancer 1-23 → 1-24 (etc.) quand le joueur a choisi une arme dans le menu (sélection confirmée)
  // En 1-23, n’avancer que si l’arme sélectionnée correspond à advanceOnWeaponName (ex. Bolt Rifle)
  useEffect(() => {
    if (stage === "1-22" || !tutorial?.currentStep?.advanceOnWeaponClick || !tutorial?.onClosePopup)
      return;
    const expectedWeaponName = tutorial.currentStep.advanceOnWeaponName;
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ gameState?: unknown; weaponDisplayName?: string }>).detail;
      if (expectedWeaponName != null && expectedWeaponName !== "") {
        const selected = (detail?.weaponDisplayName ?? "").trim();
        if (selected !== expectedWeaponName.trim()) return;
      }
      tutorial.onClosePopup();
    };
    window.addEventListener("weaponSelected", handler);
    return () => window.removeEventListener("weaponSelected", handler);
  }, [
    stage,
    tutorial?.currentStep?.advanceOnWeaponClick,
    tutorial?.currentStep?.advanceOnWeaponName,
    tutorial?.onClosePopup,
  ]);

  return (
    <BoardPvp
      {...props}
      onSelectUnit={wrappedOnSelectUnit}
      onConfirmMove={
        props.onConfirmMove != null
          ? () => {
              void wrappedOnConfirmMove();
            }
          : () => {}
      }
      onStartMovePreview={
        props.onStartMovePreview != null
          ? wrappedOnStartMovePreview
          : (_unitId: string | number, _col: string | number, _row: string | number) => {}
      }
      onDirectMove={
        props.onDirectMove != null
          ? (unitId: string | number, col: string | number, row: string | number) => {
              void wrappedOnDirectMove(unitId, col, row);
            }
          : (_unitId: string | number, _col: string | number, _row: string | number) => {}
      }
      hideAdvanceIconForTutorial={tutorial?.currentStep?.hideAdvanceIcon ?? false}
    />
  );
}

/** Table joueur 1 : rendu *dans* TutorialProvider, donc useTutorial() fournit le contexte et on peut forcer expand + halo. */
function UnitStatusTablePlayer1WithTutorial(
  props: React.ComponentProps<typeof UnitStatusTable>
): React.ReactElement {
  const tutorial = useTutorial();
  const stage = tutorial?.currentStep?.stage ?? "";
  const wantsNameMSpotlight =
    tutorial?.currentStep?.spotlightIds?.includes("table.p1.nameM") === true;
  const wantsRangedWeaponsSpotlight =
    tutorial?.currentStep?.spotlightIds?.includes("table.p1.rangedWeapons") === true;
  const isPhaseMoveStep = Boolean(
    tutorial?.popupVisible &&
      tutorial?.currentStep?.stepKey &&
      TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO.includes(
        tutorial.currentStep.stepKey as (typeof TUTORIAL_STEP_TITLES_PHASE_MOVE_HALO)[number]
      )
  );
  const isStep1_6 = tutorial?.currentStep?.stage === "1-16";
  const isStep2_2Or3Or4 =
    stage === "1-22" ||
    stage === "1-23" ||
    matchesTutorialStagePattern(stage, "1-24") ||
    matchesTutorialStagePattern(stage, "1-24-*");
  const isStep1_25 = stage === "1-25";
  const isStep2_2Or3Or4Or5 = isStep2_2Or3Or4 || isStep1_25;
  const wrappedOnSelectUnit = useCallback(
    (unitId: number) => {
      if (
        tutorial?.currentStep?.advanceOnUnitClick &&
        tutorial?.onClosePopup &&
        props.units.some(
          (u) => (u.id === unitId || u.id === Number(unitId)) && Number(u.player) === 1
        )
      ) {
        tutorial.onClosePopup();
      }
      props.onSelectUnit(unitId);
    },
    [
      tutorial?.currentStep?.advanceOnUnitClick,
      tutorial?.onClosePopup,
      props.onSelectUnit,
      props.units,
    ]
  );
  useEffect(() => {
    if (!wantsNameMSpotlight && tutorial?.setSpotlightTablePositions) {
      tutorial.setSpotlightTablePositions(null);
    }
  }, [wantsNameMSpotlight, tutorial?.setSpotlightTablePositions]);
  useEffect(() => {
    if (!wantsRangedWeaponsSpotlight && tutorial?.setSpotlightRangedWeaponsPositions) {
      tutorial.setSpotlightRangedWeaponsPositions(null);
    }
  }, [wantsRangedWeaponsSpotlight, tutorial?.setSpotlightRangedWeaponsPositions]);
  return (
    <UnitStatusTable
      {...props}
      onSelectUnit={wrappedOnSelectUnit}
      tutorialForceTableExpanded={isPhaseMoveStep || isStep2_2Or3Or4Or5}
      tutorialForceUnitIdsExpanded={isPhaseMoveStep || isStep2_2Or3Or4Or5 ? [1] : undefined}
      onNameMColumnsRect={wantsNameMSpotlight ? tutorial?.setSpotlightTablePositions : undefined}
      tutorialForceRangedExpandedForUnitIds={isStep1_6 || isStep2_2Or3Or4Or5 ? [1] : undefined}
      onRangedWeaponsSectionRect={
        wantsRangedWeaponsSpotlight ? tutorial?.setSpotlightRangedWeaponsPositions : undefined
      }
    />
  );
}

/** Compare deux rects (ou null) pour éviter des setState en boucle. */
function rectEquals(
  a: { left: number; top: number; width: number; height: number } | null,
  b: { left: number; top: number; width: number; height: number } | null
): boolean {
  if (a === b) return true;
  if (a == null || b == null) return false;
  return a.left === b.left && a.top === b.top && a.width === b.width && a.height === b.height;
}

/** Table joueur 2 : en étapes 1-22/1-23/1-24*, force expand première unité ennemie (ex. id 2) et rapporte son rect titre + attributs pour halo. */
function UnitStatusTablePlayer2WithTutorial(
  props: React.ComponentProps<typeof UnitStatusTable>
): React.ReactElement {
  const tutorial = useTutorial();
  const stage = tutorial?.currentStep?.stage ?? "";
  const wantsEnemyAttributesSpotlight =
    tutorial?.currentStep?.spotlightIds?.includes("table.p2.attributes") === true;
  const wantsP2UnitRowsSpotlight =
    tutorial?.currentStep?.spotlightIds?.includes("table.p2.unitRows") === true;
  const forceLayout2_11 =
    tutorial?.popupVisible && tutorial?.currentEtape === 2 && tutorial?.gamePhase === "deployment";
  const isStage2_11Or12 = forceLayout2_11 || wantsP2UnitRowsSpotlight;
  const lastRectRef = useRef<{ left: number; top: number; width: number; height: number } | null>(
    null
  );
  const onUnitAttributesSectionRect = useCallback(
    (
      positions: Array<{
        shape: "rect";
        left: number;
        top: number;
        width: number;
        height: number;
      }> | null
    ) => {
      if (!tutorial?.setSpotlightEnemyUnitAttributes) return;
      const next = positions?.[0] ?? null;
      if (next && lastRectRef.current && rectEquals(next, lastRectRef.current)) return;
      if (!next && lastRectRef.current === null) return;
      lastRectRef.current = next;
      tutorial.setSpotlightEnemyUnitAttributes(next);
    },
    [tutorial?.setSpotlightEnemyUnitAttributes]
  );
  useEffect(() => {
    if (!wantsEnemyAttributesSpotlight && tutorial?.setSpotlightEnemyUnitAttributes) {
      lastRectRef.current = null;
      tutorial.setSpotlightEnemyUnitAttributes(null);
    }
  }, [wantsEnemyAttributesSpotlight, tutorial?.setSpotlightEnemyUnitAttributes]);
  const onP2UnitRowRects = useCallback(
    (
      positions: Array<{
        shape: "rect";
        left: number;
        top: number;
        width: number;
        height: number;
      }> | null
    ) => {
      tutorial?.setSpotlightP2UnitRowPositions?.(positions ?? null);
    },
    [tutorial?.setSpotlightP2UnitRowPositions]
  );

  return (
    <UnitStatusTable
      {...props}
      tutorialForceTableExpanded={wantsEnemyAttributesSpotlight || isStage2_11Or12}
      tutorialForceUnitIdsExpanded={wantsEnemyAttributesSpotlight ? [2] : undefined}
      tutorialForceUnitIdsCollapsed={stage === "2-11" ? [2, 3] : undefined}
      onUnitAttributesSectionRect={
        wantsEnemyAttributesSpotlight ? onUnitAttributesSectionRect : undefined
      }
      tutorialReportAttributesForUnitIds={wantsEnemyAttributesSpotlight ? [2] : undefined}
      onP2UnitRowRects={wantsP2UnitRowsSpotlight ? onP2UnitRowRects : undefined}
      tutorialReportP2UnitRowRects={wantsP2UnitRowsSpotlight}
    />
  );
}

/** Met à jour le ref des options de tir tutoriel (1-24 : 1er tir raté, puis kill forcé). */
function TutorialShootOptionsSync({
  getTutorialShootOptionsRef,
}: {
  getTutorialShootOptionsRef: MutableRefObject<() => { forceKill?: boolean; forceMiss?: boolean }>;
}) {
  const tutorial = useTutorial();
  const [tutorial124FirstShotDone, setTutorial124FirstShotDone] = useState(false);
  const stage = tutorial?.currentStep?.stage ?? "";
  const isStage124Family =
    matchesTutorialStagePattern(stage, "1-24") || matchesTutorialStagePattern(stage, "1-24-*");

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d?.type === "shoot" && d?.target_died === false && isStage124Family) {
        setTutorial124FirstShotDone(true);
      }
    };
    window.addEventListener("backendLogEvent", handler);
    return () => window.removeEventListener("backendLogEvent", handler);
  }, [isStage124Family]);

  useEffect(() => {
    if (!isStage124Family) {
      setTutorial124FirstShotDone(false);
    }
  }, [isStage124Family]);

  useEffect(() => {
    getTutorialShootOptionsRef.current = () => {
      if (stage === "1-24" && !tutorial124FirstShotDone) {
        return { forceMiss: true };
      }
      if (
        (stage === "1-24" && tutorial124FirstShotDone) ||
        (stage !== "1-24" && isStage124Family)
      ) {
        return { forceKill: true };
      }
      return {};
    };
  }, [getTutorialShootOptionsRef, isStage124Family, stage, tutorial124FirstShotDone]);
  return null;
}

export const BoardWithAPI: React.FC = () => {
  const authSession = getAuthSession();
  if (!authSession) {
    throw new Error("Session utilisateur introuvable dans BoardWithAPI");
  }

  const canUseAdvanceWarning = authSession.permissions.options.show_advance_warning;
  const canUseAutoWeaponSelection = authSession.permissions.options.auto_weapon_selection;

  const getTutorialShootOptionsRef = useRef<() => { forceKill?: boolean; forceMiss?: boolean }>(
    () => ({})
  );
  const stopAiAfterPhaseChangeRef = useRef(false);
  const [pauseAIForTutorial, setPauseAIForTutorial] = useState(false);
  /** Synchrone avec shouldPauseAI du TutorialProvider (évite course : phase charge avant pause state). */
  const tutorialPauseAiSyncRef = useRef(false);
  const apiProps = useEngineAPI({
    getTutorialShootOptionsRef,
    stopAiAfterPhaseChangeRef,
    onStopAfterPhaseChange: () => setPauseAIForTutorial(true),
  });
  const gameLog = useGameLog(apiProps.gameState?.currentTurn ?? 1);

  // Detect game mode from URL
  const location = useLocation();
  const navigate = useNavigate();
  const isTutorialMode = location.pathname === "/game" && location.search.includes("mode=tutorial");
  const handleTutorialComplete = useCallback(async () => {
    try {
      await markTutorialComplete();
      navigate("/game?mode=pve", { replace: true });
    } catch (err) {
      console.error("Failed to mark tutorial complete:", err);
    }
  }, [navigate]);
  const handleGoToPveMode = useCallback(async () => {
    try {
      await apiProps.startPveGame();
      await markTutorialComplete();
      navigate("/game?mode=pve", { replace: true });
    } catch (err) {
      console.error("Failed to go to PvE mode:", err);
    }
  }, [apiProps.startPveGame, navigate]);
  const gameMode = location.pathname.includes("/replay")
    ? "training"
    : isTutorialMode
      ? "tutorial"
      : location.pathname === "/game" && location.search.includes("mode=endless_duty")
        ? "endless_duty"
      : location.pathname === "/game" && location.search.includes("mode=pvp_test")
        ? "pvp_test"
        : location.pathname === "/game" && location.search.includes("mode=pve_test")
          ? "pve"
          : location.pathname === "/game" && location.search.includes("mode=pve")
            ? "pve"
            : "pvp";
  const modeGuideMode: "pve" | "pvp" | null =
    !isTutorialMode && gameMode === "pve"
      ? "pve"
      : !isTutorialMode && gameMode === "pvp"
        ? "pvp"
        : null;
  const [isModeGuideActive, setIsModeGuideActive] = useState(false);
  const isAiMode = (() => {
    const playerTypes = apiProps.gameState?.player_types;
    if (!playerTypes) {
      return false;
    }
    // AI orchestration: PvE et tutoriel (P2 contrôlé par IA).
    if (gameMode !== "pve" && gameMode !== "tutorial" && gameMode !== "endless_duty") {
      return false;
    }
    return Object.values(playerTypes).some((playerType) => playerType === "ai");
  })();
  const victoryPoints = apiProps.gameState?.victory_points;
  const objectivesOverride = (() => {
    const objectives = apiProps.gameState?.objectives as
      | Array<{ name: string; hexes: Array<{ col: number; row: number } | [number, number]> }>
      | undefined;
    if (!objectives) {
      return undefined;
    }
    return objectives.map((objective) => {
      if (!objective || !objective.name) {
        throw new Error("Objective missing required name field");
      }
      if (!objective.hexes) {
        throw new Error(`Objective ${objective.name} missing required hexes`);
      }
      const normalizedHexes = objective.hexes.map((hex) => {
        if (Array.isArray(hex)) {
          if (hex.length !== 2) {
            throw new Error(
              `Objective ${objective.name} has invalid hex tuple: ${JSON.stringify(hex)}`
            );
          }
          return { col: hex[0], row: hex[1] };
        }
        if (typeof hex === "object" && hex !== null && "col" in hex && "row" in hex) {
          return { col: (hex as { col: number }).col, row: (hex as { row: number }).row };
        }
        throw new Error(
          `Objective ${objective.name} has invalid hex format: ${JSON.stringify(hex)}`
        );
      });
      return {
        name: objective.name,
        hexes: normalizedHexes,
      };
    });
  })();

  // Get board configuration for line of sight calculations
  const { gameConfig, boardConfig } = useGameConfig();

  // Track clicked (but not selected) units for blue highlighting
  const [clickedUnitId, setClickedUnitId] = useState<number | null>(null);

  // Track UnitStatusTable collapse states
  const [, setPlayer1Collapsed] = useState(false);
  const [, setPlayer2Collapsed] = useState(false);
  const [deploymentRosterCollapsed, setDeploymentRosterCollapsed] = useState<
    Record<PlayerId, boolean>
  >({
    1: false,
    2: false,
  });
  const [deploymentTooltip, setDeploymentTooltip] = useState<{
    visible: boolean;
    text: string;
    x: number;
    y: number;
  } | null>(null);
  const [rosterPickerPlayer, setRosterPickerPlayer] = useState<PlayerId | null>(null);
  const [rosterPickerArmies, setRosterPickerArmies] = useState<
    Array<{
      file: string;
      name: string;
      display_name: string;
      faction: string;
      faction_display_name: string;
      description: string;
    }>
  >([]);
  const [rosterPickerSelectedFaction, setRosterPickerSelectedFaction] = useState<string>("");
  const [rosterPickerHoveredDescription, setRosterPickerHoveredDescription] = useState<string>("");
  const [rosterPickerLoading, setRosterPickerLoading] = useState(false);
  const [rosterPickerError, setRosterPickerError] = useState<string | null>(null);
  const [ruleChoiceHoveredDescription, setRuleChoiceHoveredDescription] = useState<string>("");
  const [ruleChoiceFocusedUnitId, setRuleChoiceFocusedUnitId] = useState<string | null>(null);
  const [ruleChoicePopupPosition, setRuleChoicePopupPosition] = useState({ x: 140, y: 120 });
  const [isDraggingRuleChoicePopup, setIsDraggingRuleChoicePopup] = useState(false);
  const ruleChoiceDragOffsetRef = useRef({ x: 0, y: 0 });
  const [showGameOverPopup, setShowGameOverPopup] = useState(false);
  const [isEndlessDutyModalOpen, setIsEndlessDutyModalOpen] = useState(false);
  const [endlessDutyFormError, setEndlessDutyFormError] = useState<string | null>(null);
  const [isSubmittingEndlessDuty, setIsSubmittingEndlessDuty] = useState(false);
  const [endlessDutyDraft, setEndlessDutyDraft] = useState<EndlessDutySlotProfiles>({
    leader: null,
    melee: null,
    range: null,
  });
  const [endlessDutyDraftPicks, setEndlessDutyDraftPicks] = useState<EndlessDutySlotPicks>({
    leader: null,
    melee: null,
    range: null,
  });
  const isRosterSetupMode = gameMode === "pvp_test" || gameMode === "pvp" || gameMode === "pve";
  const [testDeploymentStarted, setTestDeploymentStarted] = useState(!isRosterSetupMode);

  const endlessDutyProfileOptions = useMemo(
    () => ({
      leader: getProfileOptions(leaderEvolutionConfig as EvolutionCatalogConfig),
      melee: getProfileOptions(meleeEvolutionConfig as EvolutionCatalogConfig),
      range: getProfileOptions(rangeEvolutionConfig as EvolutionCatalogConfig),
    }),
    []
  );

  const endlessDutyUnlockRules = useMemo(() => {
    const endlessCfg = (endlessDutyScenarioConfig as { endless_duty?: { wave_unlock_rules?: Record<string, number> } })
      .endless_duty;
    const waveUnlockRules = endlessCfg?.wave_unlock_rules ?? {};
    return {
      leader: Number(waveUnlockRules.leader ?? 1),
      melee: Number(waveUnlockRules.melee ?? 15),
      range: Number(waveUnlockRules.range ?? 10),
    };
  }, []);
  const endlessDutyPickMenus = useMemo(
    () => ({
      leader: buildPickMenusByProfile(leaderEvolutionConfig as EvolutionCatalogConfig),
      melee: buildPickMenusByProfile(meleeEvolutionConfig as EvolutionCatalogConfig),
      range: buildPickMenusByProfile(rangeEvolutionConfig as EvolutionCatalogConfig),
    }),
    []
  );
  const endlessDutyDefaultPicks = useMemo(
    () => ({
      leader: buildDefaultPicksByProfile(leaderEvolutionConfig as EvolutionCatalogConfig),
      melee: buildDefaultPicksByProfile(meleeEvolutionConfig as EvolutionCatalogConfig),
      range: buildDefaultPicksByProfile(rangeEvolutionConfig as EvolutionCatalogConfig),
    }),
    []
  );
  const getDefaultPicksForProfile = useCallback(
    (slot: keyof EndlessDutySlotProfiles, profile: string | null): EndlessDutyPickState | null => {
      if (!profile) {
        return null;
      }
      const defaults = endlessDutyDefaultPicks[slot].get(profile);
      return defaults ? { ...defaults } : null;
    },
    [endlessDutyDefaultPicks]
  );

  useEffect(() => {
    if (gameMode !== "endless_duty") {
      setIsEndlessDutyModalOpen(false);
      setEndlessDutyFormError(null);
      return;
    }
    if (!apiProps.endlessDutyState?.inter_wave_pending) {
      setIsEndlessDutyModalOpen(false);
      setEndlessDutyFormError(null);
      return;
    }
    const slotProfiles = apiProps.endlessDutyState.slot_profiles;
    const slotPicks = apiProps.endlessDutyState.slot_picks;
    const resolvedPicks: EndlessDutySlotPicks = {
      leader:
        slotProfiles.leader == null
          ? null
          : ((slotPicks?.leader as EndlessDutyPickState | null) ??
            getDefaultPicksForProfile("leader", slotProfiles.leader)),
      melee:
        slotProfiles.melee == null
          ? null
          : ((slotPicks?.melee as EndlessDutyPickState | null) ??
            getDefaultPicksForProfile("melee", slotProfiles.melee)),
      range:
        slotProfiles.range == null
          ? null
          : ((slotPicks?.range as EndlessDutyPickState | null) ??
            getDefaultPicksForProfile("range", slotProfiles.range)),
    };
    setEndlessDutyDraft({
      leader: slotProfiles.leader ?? null,
      melee: slotProfiles.melee ?? null,
      range: slotProfiles.range ?? null,
    });
    setEndlessDutyDraftPicks(resolvedPicks);
    setIsEndlessDutyModalOpen(true);
    setEndlessDutyFormError(null);
  }, [gameMode, apiProps.endlessDutyState, getDefaultPicksForProfile]);

  useEffect(() => {
    if (gameMode !== "endless_duty") {
      return;
    }
    if (!apiProps.fetchEndlessDutyStatus) {
      return;
    }
    void apiProps.fetchEndlessDutyStatus().catch(() => {
      // The regular game loop will refresh state on next action.
    });
  }, [gameMode, apiProps.fetchEndlessDutyStatus]);

  const handleEndlessDutyDraftChange = useCallback(
    (slot: keyof EndlessDutySlotProfiles, profile: string | null) => {
      setEndlessDutyDraft((prev) => ({ ...prev, [slot]: profile }));
      setEndlessDutyDraftPicks((prev) => {
        if (profile == null) {
          return { ...prev, [slot]: null };
        }
        return { ...prev, [slot]: getDefaultPicksForProfile(slot, profile) };
      });
      setEndlessDutyFormError(null);
    },
    [getDefaultPicksForProfile]
  );
  const handleEndlessDutyPickChange = useCallback(
    (slot: keyof EndlessDutySlotProfiles, pickKey: keyof EndlessDutyPickState, pickValue: string | null) => {
      setEndlessDutyDraftPicks((prev) => {
        const current = prev[slot];
        if (!current) {
          return prev;
        }
        return {
          ...prev,
          [slot]: { ...current, [pickKey]: pickValue },
        };
      });
      setEndlessDutyFormError(null);
    },
    []
  );

  const handleEndlessDutyCommit = useCallback(async () => {
    if (gameMode !== "endless_duty") {
      return;
    }
    setIsSubmittingEndlessDuty(true);
    setEndlessDutyFormError(null);
    try {
      await apiProps.commitEndlessDuty(endlessDutyDraft, endlessDutyDraftPicks);
      setIsEndlessDutyModalOpen(false);
    } catch (error) {
      setEndlessDutyFormError(error instanceof Error ? error.message : "Commit requisition impossible");
    } finally {
      setIsSubmittingEndlessDuty(false);
    }
  }, [gameMode, apiProps.commitEndlessDuty, endlessDutyDraft, endlessDutyDraftPicks]);

  const closeRosterPicker = () => {
    setRosterPickerPlayer(null);
    setRosterPickerSelectedFaction("");
    setRosterPickerHoveredDescription("");
    setRosterPickerError(null);
  };

  const openRosterPicker = async (player: PlayerId) => {
    if (!apiProps.listArmies) {
      throw new Error("listArmies API is not available");
    }
    setRosterPickerPlayer(player);
    setRosterPickerLoading(true);
    setRosterPickerError(null);
    try {
      const armies = await apiProps.listArmies();
      setRosterPickerArmies(armies);
      const availableFactions = Array.from(new Set(armies.map((army) => army.faction))).sort();
      setRosterPickerSelectedFaction(availableFactions[0] ?? "");
    } catch (err) {
      setRosterPickerError(err instanceof Error ? err.message : "Failed to load armies");
    } finally {
      setRosterPickerLoading(false);
    }
  };

  const rosterPickerFactions = useMemo(() => {
    return Array.from(new Set(rosterPickerArmies.map((army) => army.faction))).sort();
  }, [rosterPickerArmies]);

  const rosterPickerFactionDisplayNameById = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const army of rosterPickerArmies) {
      if (labels[army.faction] && labels[army.faction] !== army.faction_display_name) {
        throw new Error(
          `Conflicting faction_display_name for faction '${army.faction}': ` +
            `'${labels[army.faction]}' vs '${army.faction_display_name}'`
        );
      }
      labels[army.faction] = army.faction_display_name;
    }
    return labels;
  }, [rosterPickerArmies]);

  const effectiveRosterPickerFaction = useMemo(() => {
    if (rosterPickerSelectedFaction && rosterPickerFactions.includes(rosterPickerSelectedFaction)) {
      return rosterPickerSelectedFaction;
    }
    return rosterPickerFactions[0] ?? "";
  }, [rosterPickerSelectedFaction, rosterPickerFactions]);

  const filteredRosterPickerArmies = useMemo(() => {
    if (!effectiveRosterPickerFaction) {
      return rosterPickerArmies;
    }
    return rosterPickerArmies.filter((army) => army.faction === effectiveRosterPickerFaction);
  }, [rosterPickerArmies, effectiveRosterPickerFaction]);

  const handleSelectRoster = async (armyFile: string) => {
    if (!apiProps.changeRoster) {
      throw new Error("changeRoster API is not available");
    }
    if (rosterPickerPlayer === null) {
      throw new Error("No roster picker player selected");
    }
    try {
      const targetPlayer = isRosterSetupMode ? rosterPickerPlayer : undefined;
      await apiProps.changeRoster(armyFile, targetPlayer);
      closeRosterPicker();
    } catch (err) {
      setRosterPickerError(err instanceof Error ? err.message : "Failed to change roster");
    }
  };

  const isGameOver = apiProps.gameState?.game_over === true;
  const activeRuleChoicePrompt = (apiProps.ruleChoicePrompt as RuleChoicePrompt | null) ?? null;
  const pendingRuleChoiceQueue = (
    (apiProps.gameState as (GameState & { pending_rule_choice_queue?: RuleChoicePrompt[] }) | null)
      ?.pending_rule_choice_queue ?? []
  ).filter((entry): entry is RuleChoicePrompt => {
    return (
      typeof entry?.unit_id === "string" &&
      typeof entry?.display_name === "string" &&
      Array.isArray(entry?.options)
    );
  });
  const ruleChoicePrompts = (() => {
    const map = new Map<string, RuleChoicePrompt>();
    if (activeRuleChoicePrompt) {
      map.set(
        `${activeRuleChoicePrompt.unit_id}:${activeRuleChoicePrompt.rule_id}`,
        activeRuleChoicePrompt
      );
    }
    for (const queueEntry of pendingRuleChoiceQueue) {
      map.set(`${queueEntry.unit_id}:${queueEntry.rule_id}`, queueEntry);
    }
    return Array.from(map.values());
  })();
  const focusedRuleChoicePrompt =
    (ruleChoiceFocusedUnitId
      ? ruleChoicePrompts.find((prompt) => prompt.unit_id === ruleChoiceFocusedUnitId)
      : null) ?? activeRuleChoicePrompt;
  const ruleDescriptionById = useMemo(() => {
    const rawConfig = unitRulesConfig as Record<string, unknown>;
    const descriptions: Record<string, string> = {};
    for (const [entryKey, entryValue] of Object.entries(rawConfig)) {
      if (typeof entryValue !== "object" || entryValue === null) {
        throw new Error(`Invalid unit_rules.json entry '${entryKey}': expected an object`);
      }
      const record = entryValue as Record<string, unknown>;
      const id = record.id;
      const description = record.description;
      if (typeof id !== "string" || id.trim() === "") {
        throw new Error(`Invalid unit_rules.json entry '${entryKey}': missing non-empty 'id'`);
      }
      if (typeof description !== "string" || description.trim() === "") {
        throw new Error(
          `Invalid unit_rules.json entry '${entryKey}': missing non-empty 'description'`
        );
      }
      descriptions[id] = description;
    }
    return descriptions;
  }, []);
  const getRuleDescription = (ruleId: string): string => {
    const description = ruleDescriptionById[ruleId];
    if (typeof description !== "string" || description.trim() === "") {
      throw new Error(`Missing description for rule id '${ruleId}' in config/unit_rules.json`);
    }
    return description;
  };

  useEffect(() => {
    if (!activeRuleChoicePrompt) {
      setRuleChoiceFocusedUnitId(null);
      setRuleChoiceHoveredDescription("");
      return;
    }
    setRuleChoiceFocusedUnitId(activeRuleChoicePrompt.unit_id);
  }, [activeRuleChoicePrompt]);

  useEffect(() => {
    if (!isDraggingRuleChoicePopup) {
      return;
    }
    const onMouseMove = (event: MouseEvent) => {
      setRuleChoicePopupPosition({
        x: event.clientX - ruleChoiceDragOffsetRef.current.x,
        y: event.clientY - ruleChoiceDragOffsetRef.current.y,
      });
    };
    const onMouseUp = () => {
      setIsDraggingRuleChoicePopup(false);
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isDraggingRuleChoicePopup]);

  useEffect(() => {
    if (isGameOver) {
      setShowGameOverPopup(true);
    }
  }, [isGameOver]);

  useEffect(() => {
    const isActiveSetupDeployment =
      isRosterSetupMode &&
      apiProps.gameState?.phase === "deployment" &&
      apiProps.gameState?.deployment_type === "active";
    if (isActiveSetupDeployment) {
      setTestDeploymentStarted(false);
    }
  }, [isRosterSetupMode, apiProps.gameState?.phase, apiProps.gameState?.deployment_type]);

  const getVictoryPointsForPlayer = (player: 1 | 2): number | undefined => {
    if (!apiProps.gameState) {
      return undefined;
    }
    if (!victoryPoints) {
      throw new Error("victory_points missing from game_state");
    }
    const numericValue = victoryPoints[player];
    if (numericValue !== undefined) {
      return numericValue;
    }
    const stringValue = victoryPoints[String(player)];
    if (stringValue === undefined) {
      throw new Error(`victory_points missing for player ${player}`);
    }
    return stringValue;
  };

  // Settings menu state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const handleOpenSettings = () => setIsSettingsOpen(true);

  const [measureMode, setMeasureMode] = useState<MeasureModeState>({ kind: "off" });
  const handleToggleMeasureMode = useCallback(() => {
    setMeasureMode((prev) => (prev.kind === "off" ? { kind: "armed" } : { kind: "off" }));
  }, []);
  const handleMeasureHexCommit = useCallback((col: number, row: number) => {
    setMeasureMode((prev) => {
      if (prev.kind === "armed") {
        return { kind: "measuring", startCol: col, startRow: row };
      }
      if (prev.kind === "measuring") {
        return { kind: "off" };
      }
      return prev;
    });
  }, []);
  const measureModeActive = measureMode.kind !== "off";
  const [advanceWarningDontRemind, setAdvanceWarningDontRemind] = useState(false);

  // Settings preferences (from localStorage)
  const [settings, setSettings] = useState(() => {
    const showAdvanceWarningStr = localStorage.getItem("showAdvanceWarning");
    const showDebugStr = localStorage.getItem("showDebug");
    const showDebugLoSStr = localStorage.getItem("showDebugLoS");
    const autoSelectWeaponStr = localStorage.getItem("autoSelectWeapon");
    const retreatAlertEnabledStr = localStorage.getItem(RETREAT_ALERT_STORAGE_KEY);
    const modeGuidesActivatedStr = localStorage.getItem(MODE_GUIDES_ACTIVATED_STORAGE_KEY);
    const pveGuideSeen = localStorage.getItem(MODE_GUIDE_SEEN_PVE_STORAGE_KEY) === "true";
    const pvpGuideSeen = localStorage.getItem(MODE_GUIDE_SEEN_PVP_STORAGE_KEY) === "true";
    const guidesSeenAtLeastOnce = pveGuideSeen || pvpGuideSeen;
    return {
      showAdvanceWarning:
        canUseAdvanceWarning && (showAdvanceWarningStr ? JSON.parse(showAdvanceWarningStr) : true),
      showDebug: showDebugStr ? JSON.parse(showDebugStr) : false,
      showDebugLoS: showDebugLoSStr ? JSON.parse(showDebugLoSStr) : false,
      autoSelectWeapon:
        canUseAutoWeaponSelection && (autoSelectWeaponStr ? JSON.parse(autoSelectWeaponStr) : true),
      retreatAlertEnabled: retreatAlertEnabledStr ? JSON.parse(retreatAlertEnabledStr) : true,
      modeGuidesActivated:
        modeGuidesActivatedStr != null ? JSON.parse(modeGuidesActivatedStr) : !guidesSeenAtLeastOnce,
    };
  });

  const updateRetreatAlertSetting = useCallback((value: boolean) => {
    localStorage.setItem(RETREAT_ALERT_STORAGE_KEY, JSON.stringify(value));
    setSettings((prev) => ({ ...prev, retreatAlertEnabled: value }));
  }, []);

  const handleToggleAdvanceWarning = (value: boolean) => {
    if (!canUseAdvanceWarning) {
      return;
    }
    setSettings((prev) => ({ ...prev, showAdvanceWarning: value }));
    localStorage.setItem("showAdvanceWarning", JSON.stringify(value));
  };

  const handleToggleDebug = (value: boolean) => {
    setSettings((prev) => ({ ...prev, showDebug: value }));
    localStorage.setItem("showDebug", JSON.stringify(value));
  };

  const handleToggleDebugLoS = (value: boolean) => {
    setSettings((prev) => ({ ...prev, showDebugLoS: value }));
    localStorage.setItem("showDebugLoS", JSON.stringify(value));
  };

  const handleToggleAutoSelectWeapon = (value: boolean) => {
    if (!canUseAutoWeaponSelection) {
      return;
    }
    setSettings((prev) => ({ ...prev, autoSelectWeapon: value }));
    localStorage.setItem("autoSelectWeapon", JSON.stringify(value));
  };

  const handleToggleRetreatAlert = (value: boolean) => {
    updateRetreatAlertSetting(value);
  };

  const handleToggleModeGuidesActivated = (value: boolean) => {
    localStorage.setItem(MODE_GUIDES_ACTIVATED_STORAGE_KEY, JSON.stringify(value));
    if (value) {
      localStorage.removeItem(MODE_GUIDE_SEEN_PVE_STORAGE_KEY);
      localStorage.removeItem(MODE_GUIDE_SEEN_PVP_STORAGE_KEY);
    }
    setSettings((prev) => ({ ...prev, modeGuidesActivated: value }));
    if (!value) {
      setIsModeGuideActive(false);
      return;
    }
    if (modeGuideMode != null) {
      setIsModeGuideActive(true);
    }
  };

  useEffect(() => {
    if (!settings.modeGuidesActivated || modeGuideMode == null) {
      setIsModeGuideActive(false);
      return;
    }
    const key =
      modeGuideMode === "pve" ? MODE_GUIDE_SEEN_PVE_STORAGE_KEY : MODE_GUIDE_SEEN_PVP_STORAGE_KEY;
    const raw = localStorage.getItem(key);
    const alreadySeen = raw != null && raw === "true";
    setIsModeGuideActive(!alreadySeen);
  }, [modeGuideMode, settings.modeGuidesActivated]);

  const activeTutorialMode = isTutorialMode || isModeGuideActive;
  const tutorialScenarioType: "tutorial" | "mode_guide" = isTutorialMode ? "tutorial" : "mode_guide";
  const handleModeGuideComplete = useCallback(() => {
    if (modeGuideMode == null) {
      setIsModeGuideActive(false);
      return;
    }
    const key =
      modeGuideMode === "pve" ? MODE_GUIDE_SEEN_PVE_STORAGE_KEY : MODE_GUIDE_SEEN_PVP_STORAGE_KEY;
    localStorage.setItem(key, "true");
    localStorage.setItem(MODE_GUIDES_ACTIVATED_STORAGE_KEY, JSON.stringify(false));
    setSettings((prev) => ({ ...prev, modeGuidesActivated: false }));
    setIsModeGuideActive(false);
  }, [modeGuideMode]);

  useEffect(() => {
    if (apiProps.advanceWarningPopup) {
      setAdvanceWarningDontRemind(false);
    }
  }, [apiProps.advanceWarningPopup]);

  // Calculate available height for GameLog dynamically
  const [logAvailableHeight, setLogAvailableHeight] = useState(220);

  // Track AI processing with ref to avoid re-render loops
  const isAIProcessingRef = useRef(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [lastProcessedTurn, setLastProcessedTurn] = useState<string>("");

  // Track previous values to prevent console flooding during animations
  const prevAICheckRef = useRef<{
    currentPhase: string;
    current_player: number;
    isAITurn: boolean;
    shouldTriggerAI: boolean;
    turnKey: string;
  } | null>(null);

  const clearAIError = () => setAiError(null);

  // AI Turn Processing Effect - Trigger AI when it's AI player's turn and has eligible units
  useEffect(() => {
    if (!apiProps.gameState) return;

    const playerTypes = apiProps.gameState.player_types;
    if (!playerTypes) {
      throw new Error("Missing player_types in gameState for AI turn orchestration");
    }
    const getPlayerType = (playerId: number): "human" | "ai" => {
      const playerType = playerTypes[String(playerId)];
      if (!playerType) {
        throw new Error(`Missing player type for player ${playerId}`);
      }
      return playerType;
    };
    const isAiUnit = (unit: Unit): boolean => getPlayerType(unit.player) === "ai";
    const hasAiUnitsInPool = (pool: Array<string | number>, state: { units: Unit[] }): boolean =>
      pool.some((unitId) => {
        const unit = state.units.find((u: Unit) => String(u.id) === String(unitId));
        return !!unit && isAiUnit(unit) && (unit.HP_CUR ?? unit.HP_MAX) > 0;
      });

    const isAiEnabled = isAiMode;

    // Check if game is over by examining unit health
    const player1Alive = apiProps.gameState.units.some(
      (u) => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0
    );
    const player2Alive = apiProps.gameState.units.some(
      (u) => u.player === 2 && (u.HP_CUR ?? u.HP_MAX) > 0
    );
    const gameNotOver = player1Alive && player2Alive;

    // CRITICAL: Check if AI has eligible units in current phase
    // Use simple heuristic instead of missing activation pools
    const currentPhase = apiProps.gameState.phase as GamePhase;
    let hasEligibleAIUnits = false;

    if (currentPhase === "deployment") {
      const deploymentState = apiProps.gameState?.deployment_state;
      if (!deploymentState) {
        hasEligibleAIUnits = false;
      } else {
        const deployer = deploymentState.current_deployer;
        const pool = deploymentState.deployable_units?.[String(deployer)] || [];
        hasEligibleAIUnits = getPlayerType(deployer) === "ai" && pool.length > 0;
      }
    } else if (currentPhase === "move") {
      // Move phase: Check move activation pool for AI eligibility
      if (apiProps.gameState.move_activation_pool) {
        hasEligibleAIUnits = hasAiUnitsInPool(
          apiProps.gameState.move_activation_pool,
          apiProps.gameState
        );
      }
    } else if (currentPhase === "shoot") {
      hasEligibleAIUnits = apiProps.gameState.shoot_activation_pool
        ? hasAiUnitsInPool(apiProps.gameState.shoot_activation_pool, apiProps.gameState)
        : false;
    } else if (currentPhase === "charge") {
      // Charge phase: Check charge activation pool for AI eligibility
      if (apiProps.gameState.charge_activation_pool) {
        hasEligibleAIUnits = hasAiUnitsInPool(
          apiProps.gameState.charge_activation_pool,
          apiProps.gameState
        );
      }
    } else if (currentPhase === "fight") {
      // Fight phase: Check fight subphase pools for AI eligibility
      // Try both apiProps.fightSubPhase and apiProps.gameState.fight_subphase
      const fightSubphase = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase;

      let fightPool: string[] = [];
      if (fightSubphase === "charging" && apiProps.gameState.charging_activation_pool) {
        fightPool = apiProps.gameState.charging_activation_pool;
      } else if (
        fightSubphase === "alternating_non_active" &&
        apiProps.gameState.non_active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.non_active_alternating_activation_pool;
      } else if (
        fightSubphase === "alternating_active" &&
        apiProps.gameState.active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.active_alternating_activation_pool;
      } else if (
        fightSubphase === "cleanup_non_active" &&
        apiProps.gameState.non_active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.non_active_alternating_activation_pool;
      } else if (
        fightSubphase === "cleanup_active" &&
        apiProps.gameState.active_alternating_activation_pool
      ) {
        fightPool = apiProps.gameState.active_alternating_activation_pool;
      }

      hasEligibleAIUnits = hasAiUnitsInPool(fightPool, apiProps.gameState);
    }

    const current_player = apiProps.gameState?.current_player;
    if (current_player === undefined || current_player === null) {
      throw new Error("Missing current_player in gameState");
    }
    const isAITurn =
      currentPhase === "fight" ? hasEligibleAIUnits : getPlayerType(current_player) === "ai";

    // Removed duplicate log - now handled below with change detection

    const fightSubphaseForKey = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase || "";
    const turnKey = `${apiProps.gameState?.current_player}-${currentPhase}-${fightSubphaseForKey}-${apiProps.gameState?.currentTurn || 1}`;

    // Reset lastProcessedTurn if turn/phase has changed (prevents blocking on failed AI turns)
    // Extract turn/phase from lastProcessedTurn to compare
    if (lastProcessedTurn) {
      const lastParts = lastProcessedTurn.split("-");
      const currentTurn = apiProps.gameState?.currentTurn || 1;
      const lastTurn = lastParts.length >= 4 ? parseInt(lastParts[3], 10) : null;
      const lastPhase = lastParts.length >= 2 ? lastParts[1] : null;

      // If turn or phase changed, reset lastProcessedTurn
      if (lastTurn !== currentTurn || lastPhase !== currentPhase) {
        setLastProcessedTurn("");
      }
    }

    // Allow multiple AI activations in same phase if there are still eligible units
    // Don't use lastProcessedTurn to block - rely on isAIProcessingRef and hasEligibleAIUnits
    // lastProcessedTurn is only used to detect turn/phase changes for reset
    // Tutoriel 2-11/2-12/2-13 : pause IA tant que le popup est visible (Hormagaunts immobiles jusqu'au clic Suivant)
    const tutorialPauseFromSync =
      isTutorialMode && tutorialPauseAiSyncRef.current;
    const shouldTriggerAI =
      isAiEnabled &&
      isAITurn &&
      !isAIProcessingRef.current &&
      gameNotOver &&
      hasEligibleAIUnits &&
      !pauseAIForTutorial &&
      !tutorialPauseFromSync;

    // Only log when values actually change (prevents console flooding during animations)
    const currentAICheck = {
      currentPhase,
      current_player: apiProps.gameState.current_player,
      isAITurn,
      shouldTriggerAI,
      turnKey,
    };

    const prevCheck = prevAICheckRef.current;
    const hasChanged =
      !prevCheck ||
      prevCheck.currentPhase !== currentAICheck.currentPhase ||
      prevCheck.current_player !== currentAICheck.current_player ||
      prevCheck.isAITurn !== currentAICheck.isAITurn ||
      prevCheck.shouldTriggerAI !== currentAICheck.shouldTriggerAI ||
      prevCheck.turnKey !== currentAICheck.turnKey;

    if (hasChanged) {
      prevAICheckRef.current = currentAICheck;
    }

    if (shouldTriggerAI) {
      isAIProcessingRef.current = true;
      // Don't set lastProcessedTurn here - wait until AI completes successfully

      // Small delay to ensure UI updates are complete
      setTimeout(async () => {
        try {
          const latestState = apiProps.gameState;
          if (!latestState) {
            throw new Error("Missing gameState before AI turn");
          }
          const latestPhase = latestState.phase;
          const latestPlayer = latestState.current_player;
          if (latestPlayer === undefined || latestPlayer === null) {
            throw new Error("Missing current_player before AI turn");
          }
          if (latestPhase !== "fight" && getPlayerType(latestPlayer) !== "ai") {
            return;
          }
          if (latestPhase === "fight") {
            const latestFightSubphase = apiProps.fightSubPhase || latestState.fight_subphase;
            let latestFightPool: string[] = [];
            if (latestFightSubphase === "charging" && latestState.charging_activation_pool) {
              latestFightPool = latestState.charging_activation_pool;
            } else if (
              latestFightSubphase === "alternating_non_active" &&
              latestState.non_active_alternating_activation_pool
            ) {
              latestFightPool = latestState.non_active_alternating_activation_pool;
            } else if (
              latestFightSubphase === "alternating_active" &&
              latestState.active_alternating_activation_pool
            ) {
              latestFightPool = latestState.active_alternating_activation_pool;
            } else if (
              latestFightSubphase === "cleanup_non_active" &&
              latestState.non_active_alternating_activation_pool
            ) {
              latestFightPool = latestState.non_active_alternating_activation_pool;
            } else if (
              latestFightSubphase === "cleanup_active" &&
              latestState.active_alternating_activation_pool
            ) {
              latestFightPool = latestState.active_alternating_activation_pool;
            }
            const isAITurnNow = hasAiUnitsInPool(latestFightPool, latestState);
            if (!isAITurnNow) {
              return;
            }
          }
          if (apiProps.executeAITurn) {
            // Tutorial flow must always pause after each phase transition
            // so the next phase popup can be displayed deterministically.
            const mustStopAfterPhaseChange =
              gameMode === "tutorial" ? true : stopAiAfterPhaseChangeRef.current;
            await apiProps.executeAITurn({
              stopAfterPhaseChange: mustStopAfterPhaseChange,
            });
            // Don't set lastProcessedTurn here - allow multiple activations in same phase
            // lastProcessedTurn will be set when phase actually changes (via useEffect dependency)
          } else {
            console.error(
              "❌ [BOARD_WITH_API] executeAITurn function not available, type:",
              typeof apiProps.executeAITurn
            );
            setAiError("AI function not available");
          }
        } catch (error) {
          console.error("❌ [BOARD_WITH_API] AI turn failed:", error);
          setAiError(error instanceof Error ? error.message : "AI turn failed");
        } finally {
          isAIProcessingRef.current = false;
        }
      }, 1500);
    } else if (isAiEnabled && isAITurn && !hasEligibleAIUnits) {
      // AI turn skipped - no eligible units
    } else if (isAiEnabled && !shouldTriggerAI && hasChanged) {
      // Only log when values change, and only in debug scenarios
      // Suppress the "NOT triggered" warning to reduce console noise
      // Uncomment below if you need to debug AI triggering issues
      // console.log(`⚠️ [BOARD_WITH_API] AI turn NOT triggered. Reasons:`, {
      //   isPvEMode,
      //   isAITurn,
      //   isAIProcessing: isAIProcessingRef.current,
      //   gameNotOver,
      //   hasEligibleAIUnits,
      //   lastProcessedTurn,
      //   turnKey,
      //   turnKeyMatches: lastProcessedTurn === turnKey
      // });
    }
  }, [
    isAiMode,
    apiProps,
    gameMode,
    lastProcessedTurn,
    pauseAIForTutorial,
    isTutorialMode,
    tutorialPauseAiSyncRef,
  ]);

  // Update lastProcessedTurn when phase/turn changes (to track phase transitions)
  useEffect(() => {
    if (!apiProps.gameState) return;
    const fightSubphaseForKey = apiProps.fightSubPhase || apiProps.gameState?.fight_subphase || "";
    const currentTurnKey = `${apiProps.gameState?.current_player}-${apiProps.gameState?.phase}-${fightSubphaseForKey}-${apiProps.gameState?.currentTurn || 1}`;

    // Only update if phase/turn actually changed (not just on every render)
    if (lastProcessedTurn && lastProcessedTurn !== currentTurnKey) {
      // Phase/turn changed - reset to allow new AI activations
      const lastParts = lastProcessedTurn.split("-");
      const currentTurn = apiProps.gameState?.currentTurn || 1;
      const lastTurn = lastParts.length >= 4 ? parseInt(lastParts[3], 10) : null;
      const lastPhase = lastParts.length >= 2 ? lastParts[1] : null;

      if (lastTurn !== currentTurn || lastPhase !== apiProps.gameState?.phase) {
        setLastProcessedTurn("");
      }
    }
  }, [apiProps.gameState, apiProps.fightSubPhase, lastProcessedTurn]);

  // Calculate available height for GameLog dynamically
  useEffect(() => {
    // Wait for DOM to be fully rendered before measuring
    setTimeout(() => {
      const turnPhaseTracker = document.querySelector(".turn-phase-tracker-right");
      const allTables = document.querySelectorAll(".unit-status-table-container");
      const gameLogHeader =
        document.querySelector(".game-log__header") ||
        document.querySelector('[class*="game-log"]');

      if (!turnPhaseTracker || allTables.length < 2 || !gameLogHeader) {
        setLogAvailableHeight(220);
        return;
      }

      const player1Table = allTables[0];
      const player2Table = allTables[1];

      // Get actual heights from DOM measurements
      const turnPhaseHeight = turnPhaseTracker.getBoundingClientRect().height;
      const player1Height = player1Table.getBoundingClientRect().height;
      const player2Height = player2Table.getBoundingClientRect().height;
      const gameLogHeaderHeight = gameLogHeader.getBoundingClientRect().height;

      // Calculate available space based purely on actual measurements
      const viewportHeight = window.innerHeight;
      const appContainer = document.querySelector(".app-container") || document.body;
      const appMargins = viewportHeight - appContainer.getBoundingClientRect().height;
      const usedSpace = turnPhaseHeight + player1Height + player2Height + gameLogHeaderHeight;
      const availableForLogEntries = viewportHeight - usedSpace - appMargins;

      const sampleLogEntry = document.querySelector(".game-log-entry");
      if (!sampleLogEntry) {
        setLogAvailableHeight(220);
        return;
      }
      setLogAvailableHeight(availableForLogEntries);
    }, 100); // Wait 100ms for DOM to render
  }, []);

  if (apiProps.loading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "600px",
          background: "#1f2937",
          borderRadius: "8px",
          color: "white",
          fontSize: "18px",
        }}
      >
        Starting W40K Engine Game...
      </div>
    );
  }

  if (apiProps.error) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "600px",
          background: "#7f1d1d",
          borderRadius: "8px",
          color: "#fecaca",
          fontSize: "18px",
          padding: "20px",
        }}
      >
        <div>Error: {apiProps.error}</div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            marginTop: "10px",
            padding: "10px 20px",
            backgroundColor: "#dc2626",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: "pointer",
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  const deploymentPanel = (() => {
    if (!apiProps.gameState) {
      return null;
    }
    const phase = apiProps.gameState.phase as GamePhase;
    if (phase !== "deployment" || apiProps.gameState.deployment_type !== "active") {
      return null;
    }
    const deploymentState = apiProps.gameState.deployment_state;
    if (!deploymentState) {
      return null;
    }

    const currentDeployer = Number(deploymentState.current_deployer) as PlayerId;
    const players: PlayerId[] = [1, 2];
    const getIconBorderColor = (player: PlayerId): string =>
      player === 2 ? "var(--hp-bar-player2)" : "var(--hp-bar-player1)";

    const isTestDeploymentMode = isRosterSetupMode;
    const isTestSetupLocked = isTestDeploymentMode && !testDeploymentStarted;
    return (
      <div className="deployment-panel deployment-panel--dual">
        {players.map((player) => {
          const deployableIdsRaw = deploymentState.deployable_units?.[String(player)] || [];
          const deployableUnits = deployableIdsRaw
            .map((id) => apiProps.gameState!.units.find((u) => String(u.id) === String(id)))
            .filter((u): u is Unit => Boolean(u));
          const getDeploymentGroupKey = (unit: Unit): string => {
            const displayName = unit.DISPLAY_NAME || unit.name || unit.type || unit.unitType;
            if (!displayName) {
              throw new Error(`Deployment unit ${unit.id} missing display name`);
            }
            const marker = " (";
            const markerIndex = displayName.indexOf(marker);
            if (markerIndex > 0 && displayName.endsWith(")")) {
              return displayName.slice(0, markerIndex).trim();
            }
            return displayName.trim();
          };
          const deployableByType: Record<string, Unit[]> = {};
          deployableUnits.forEach((unit) => {
            const typeKey = getDeploymentGroupKey(unit);
            if (!deployableByType[typeKey]) {
              deployableByType[typeKey] = [];
            }
            deployableByType[typeKey].push(unit);
          });
          Object.values(deployableByType).forEach((unitsOfType) => {
            unitsOfType.sort((a, b) => {
              if (typeof a.VALUE !== "number" || typeof b.VALUE !== "number") {
                throw new Error(
                  `Deployment sorting requires numeric VALUE (units ${a.id}=${String(a.VALUE)}, ${b.id}=${String(b.VALUE)})`
                );
              }
              if (b.VALUE !== a.VALUE) {
                return b.VALUE - a.VALUE;
              }
              const aName = a.DISPLAY_NAME || a.name || a.type || a.unitType || "";
              const bName = b.DISPLAY_NAME || b.name || b.type || b.unitType || "";
              return aName.localeCompare(bName);
            });
          });
          const isCurrentDeployer = player === currentDeployer;
          const isCollapsed = deploymentRosterCollapsed[player];
          const deployedUnitIds = deploymentState.deployed_units.map((id) => String(id));
          const hasDeployedByPlayer = deployedUnitIds.some((deployedId) => {
            const deployedUnit = apiProps.gameState!.units.find((u) => String(u.id) === deployedId);
            return deployedUnit ? Number(deployedUnit.player) === player : false;
          });
          const canChangeRoster = isTestDeploymentMode
            ? !testDeploymentStarted
            : isCurrentDeployer && !hasDeployedByPlayer;
          const canInteractDeployment = isCurrentDeployer && !isTestSetupLocked;

          return (
            <div
              key={`deployment-roster-${player}`}
              className={`deployment-panel__roster deployment-panel__roster--player${player}`}
            >
              <div
                className={`deployment-panel__player-banner ${
                  player === 2
                    ? "deployment-panel__player-banner--player2"
                    : "deployment-panel__player-banner--player1"
                }`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "8px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "flex-start",
                    gap: "8px",
                  }}
                >
                  <button
                    type="button"
                    className="deployment-panel__toggle"
                    onClick={() =>
                      setDeploymentRosterCollapsed((prev) => ({
                        ...prev,
                        [player]: !prev[player],
                      }))
                    }
                    aria-label={
                      isCollapsed
                        ? `Etendre roster player ${player}`
                        : `Reduire roster player ${player}`
                    }
                  >
                    {isCollapsed ? "+" : "−"}
                  </button>
                  <span>
                    Player {player} - Deployment {isCurrentDeployer ? "(Active)" : "(Waiting)"}
                  </span>
                </div>
                {canChangeRoster && (
                  <button
                    type="button"
                    className={`deployment-panel__change-roster deployment-panel__change-roster--player${player}`}
                    onClick={() => openRosterPicker(player)}
                  >
                    change roster
                  </button>
                )}
              </div>

              {!isCollapsed && (
                <div className="deployment-panel__type-list">
                  {Object.keys(deployableByType).length === 0 && (
                    <div className="deployment-panel__empty">Aucune unite deployable restante</div>
                  )}
                  {Object.entries(deployableByType).map(([typeKey, unitsOfType]) => (
                    <div
                      key={`deploy-type-${player}-${typeKey}`}
                      className={`deployment-panel__type-group deployment-panel__type-group--player${player}`}
                    >
                      <div className="deployment-panel__type-label">{typeKey} :</div>
                      <div className="deployment-panel__type-icons">
                        {unitsOfType.map((unit) => {
                          const isSelected = apiProps.selectedUnitId === unit.id;
                          const displayName = unit.DISPLAY_NAME || unit.name || typeKey;
                          const tooltipText = `${displayName} - ID ${unit.id}${isCurrentDeployer ? "" : " (inactive this turn)"}`;
                          return (
                            <button
                              type="button"
                              className="deployment-panel__unit-icon"
                              key={`deploy-unit-${player}-${unit.id}`}
                              onMouseEnter={(e) => {
                                setDeploymentTooltip({
                                  visible: true,
                                  text: tooltipText,
                                  x: e.clientX,
                                  y: e.clientY,
                                });
                              }}
                              onMouseMove={(e) => {
                                setDeploymentTooltip((prev) => ({
                                  visible: true,
                                  text: prev?.text ?? tooltipText,
                                  x: e.clientX,
                                  y: e.clientY,
                                }));
                              }}
                              onMouseLeave={() => {
                                setDeploymentTooltip(null);
                              }}
                              onClick={() => {
                                if (!canInteractDeployment) {
                                  return;
                                }
                                apiProps.onSelectUnit(unit.id);
                                setClickedUnitId(null);
                              }}
                              aria-disabled={!canInteractDeployment}
                              tabIndex={canInteractDeployment ? 0 : -1}
                              style={{
                                width: "42px",
                                height: "42px",
                                borderRadius: "6px",
                                border: isSelected
                                  ? "2px solid #7CFF7C"
                                  : `1px solid ${getIconBorderColor(player)}`,
                                background: isSelected
                                  ? "rgba(124, 255, 124, 0.2)"
                                  : "rgba(0, 0, 0, 0.35)",
                                color: "white",
                                cursor: canInteractDeployment ? "pointer" : "not-allowed",
                                opacity: canInteractDeployment ? 1 : 0.55,
                                padding: "0",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                overflow: "hidden",
                                position: "relative",
                              }}
                            >
                              <img
                                src={unit.ICON}
                                alt={displayName}
                                style={{
                                  width: "100%",
                                  height: "100%",
                                  objectFit: "contain",
                                  pointerEvents: "none",
                                }}
                              />
                              <span
                                style={{
                                  position: "absolute",
                                  right: "2px",
                                  bottom: "1px",
                                  fontSize: "9px",
                                  lineHeight: "1",
                                  background: "rgba(0, 0, 0, 0.65)",
                                  padding: "1px 2px",
                                  borderRadius: "3px",
                                }}
                              >
                                {unit.id}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  })();

  const unitsById = new Map(
    (apiProps.gameState?.units ?? []).map((unit) => [String(unit.id), unit])
  );
  const getRulePromptUnitLabel = (prompt: RuleChoicePrompt): string => {
    const unit = unitsById.get(prompt.unit_id);
    if (!unit) {
      return `Unite #${prompt.unit_id} - ${prompt.display_name}`;
    }
    return `${unit.DISPLAY_NAME || unit.id} #${unit.id} - ${prompt.display_name}`;
  };
  const getRulePromptPlayerClass = (prompt: RuleChoicePrompt): string => {
    const unit = unitsById.get(prompt.unit_id);
    if (!unit) {
      return "";
    }
    if (unit.player === 1) {
      return "rule-choice-group__unit-btn--player1";
    }
    if (unit.player === 2) {
      return "rule-choice-group__unit-btn--player2";
    }
    return "";
  };
  const getRulePromptDescription = (): string => {
    if (ruleChoiceHoveredDescription) {
      return ruleChoiceHoveredDescription;
    }
    return "";
  };
  const getRuleChoiceMomentLabel = (prompt: RuleChoicePrompt): string => {
    if (prompt.phase === "command") return "Command Phase";
    if (prompt.phase === "move") return "Move Phase";
    if (prompt.phase === "shoot") return "Shoot Phase";
    if (prompt.phase === "charge") return "Charge Phase";
    if (prompt.phase === "fight") return "Fight Phase";
    if (prompt.trigger === "on_deploy") return "On Deploy";
    if (prompt.trigger === "turn_start") return "Turn Start";
    if (prompt.trigger === "player_turn_start") return "Player Turn Start";
    if (prompt.trigger === "phase_start") return "Phase Start";
    if (prompt.trigger === "activation_start") return "Activation Start";
    throw new Error(`Unknown rule choice trigger context: ${JSON.stringify(prompt)}`);
  };
  const onRuleChoiceTitleMouseDown = (event: React.MouseEvent<HTMLButtonElement>) => {
    ruleChoiceDragOffsetRef.current = {
      x: event.clientX - ruleChoicePopupPosition.x,
      y: event.clientY - ruleChoicePopupPosition.y,
    };
    setIsDraggingRuleChoicePopup(true);
  };
  const highlightedRuleChoiceUnitId = (() => {
    if (ruleChoiceFocusedUnitId === null) {
      return null;
    }
    const parsed = parseInt(ruleChoiceFocusedUnitId, 10);
    if (!Number.isFinite(parsed)) {
      return null;
    }
    return parsed;
  })();

  const rightColumnContent = (
    <RightColumnTutorialSpotlight>
      {gameConfig ? (
        <div className="turn-phase-tracker-right">
          <TurnPhaseTrackerWithTutorial
            currentTurn={apiProps.gameState?.currentTurn ?? 1}
            currentPhase={apiProps.gameState?.phase ?? "move"}
            phases={
              apiProps.gameState?.deployment_type === "active"
                ? ["deployment", "move", "shoot", "charge", "fight"]
                : ["move", "shoot", "charge", "fight"]
            }
            current_player={apiProps.gameState?.current_player}
            onEndPhaseClick={isGameOver ? undefined : apiProps.onEndPhase}
            maxTurns={(() => {
              if (!gameConfig?.game_rules?.max_turns) {
                throw new Error(
                  `max_turns not found in game configuration. Config structure: ${JSON.stringify(Object.keys(gameConfig || {}))}. Expected: gameConfig.game_rules.max_turns`
                );
              }
              return gameConfig.game_rules.max_turns;
            })()}
            className=""
          />
        </div>
      ) : (
        <div className="turn-phase-tracker-right">Loading game configuration...</div>
      )}

      {/* AI Status Display */}
      {isAiMode &&
        (() => {
          const currentPlayer = apiProps.gameState?.current_player;
          const currentPlayerType =
            currentPlayer !== undefined && currentPlayer !== null
              ? apiProps.gameState?.player_types?.[String(currentPlayer)]
              : null;
          const isCurrentPlayerAI = currentPlayerType === "ai";
          return (
            <div
              className={`flex items-center gap-2 px-3 py-2 rounded mb-2 ${
                isCurrentPlayerAI
                  ? isAIProcessingRef.current
                    ? "bg-purple-900 border border-purple-700"
                    : "bg-purple-800 border border-purple-600"
                  : "bg-gray-800 border border-gray-600"
              }`}
            >
              <span className="text-sm font-medium text-white">
                {isCurrentPlayerAI ? "🤖 AI Turn" : "👤 Your Turn"}
              </span>
              {isCurrentPlayerAI && isAIProcessingRef.current && (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-purple-300"></div>
                  <span className="text-purple-200 text-sm">AI thinking...</span>
                </>
              )}
            </div>
          );
        })()}

      <div className="scoring-panel">
        {(() => {
          const p1Score = victoryPoints ? (victoryPoints[1] ?? victoryPoints["1"] ?? 0) : 0;
          const p2Score = victoryPoints ? (victoryPoints[2] ?? victoryPoints["2"] ?? 0) : 0;
          const total = p1Score + p2Score;
          const p1Percent = total > 0 ? (p1Score / total) * 100 : 50;
          const p2Percent = 100 - p1Percent;
          return (
            <div
              className="scoring-panel__bar"
              role="img"
              aria-label={`Scoring P1 ${p1Score} points, P2 ${p2Score} points`}
            >
              <div
                className="scoring-panel__segment scoring-panel__segment--p1"
                style={{ width: `${p1Percent}%` }}
              />
              <div
                className="scoring-panel__segment scoring-panel__segment--p2"
                style={{ width: `${p2Percent}%` }}
              />
              <div className="scoring-panel__divider" />
              <div className="scoring-panel__labels">
                <span className="scoring-panel__score">P1 - Primary: {p1Score}</span>
                <span className="scoring-panel__score">P2 - Primary: {p2Score}</span>
              </div>
            </div>
          );
        })()}
      </div>

      {deploymentPanel}
      {deploymentTooltip?.visible && (
        <div
          className="rule-tooltip unit-icon-tooltip"
          style={{
            left: `${deploymentTooltip.x}px`,
            top: `${deploymentTooltip.y}px`,
          }}
        >
          {deploymentTooltip.text}
        </div>
      )}
      {showGameOverPopup && apiProps.gameState && (
        <div className="deployment-panel__picker-backdrop">
          <div className="deployment-panel__picker">
            <div className="deployment-panel__picker-title">Game Over</div>
            <div className="deployment-panel__picker-content" style={{ display: "block" }}>
              <div className="deployment-panel__picker-tooltip">
                {(() => {
                  const p1 = victoryPoints ? (victoryPoints[1] ?? victoryPoints["1"] ?? 0) : 0;
                  const p2 = victoryPoints ? (victoryPoints[2] ?? victoryPoints["2"] ?? 0) : 0;
                  const winner = apiProps.gameState?.winner;
                  const winnerText =
                    winner === 1 ? "Winner: Player 1" : winner === 2 ? "Winner: Player 2" : "Draw";
                  return `Final score:\nP1: ${p1}\nP2: ${p2}\n${winnerText}`;
                })()}
              </div>
            </div>
            <div className="deployment-panel__picker-actions">
              <button
                type="button"
                className="deployment-panel__picker-close"
                onClick={() => setShowGameOverPopup(false)}
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      {rosterPickerPlayer !== null && (
        <div className="deployment-panel__picker-backdrop">
          <button
            type="button"
            className="deployment-panel__picker-dismiss"
            aria-label="Close roster picker"
            onClick={closeRosterPicker}
          />
          <div className="deployment-panel__picker">
            <div className="deployment-panel__picker-title">
              Change roster - Player {rosterPickerPlayer}
            </div>
            {rosterPickerLoading && (
              <div className="deployment-panel__picker-loading">Loading armies...</div>
            )}
            {rosterPickerError && (
              <div className="deployment-panel__picker-error">{rosterPickerError}</div>
            )}
            {!rosterPickerLoading && !rosterPickerError && (
              <div className="deployment-panel__picker-content">
                <div className="deployment-panel__picker-factions">
                  {rosterPickerFactions.map((faction) => (
                    <button
                      type="button"
                      key={faction}
                      className={`deployment-panel__picker-item ${effectiveRosterPickerFaction === faction ? "deployment-panel__picker-item--active" : ""}`}
                      onClick={() => {
                        setRosterPickerSelectedFaction(faction);
                        setRosterPickerHoveredDescription("");
                      }}
                    >
                      {rosterPickerFactionDisplayNameById[faction]}
                    </button>
                  ))}
                </div>
                <div className="deployment-panel__picker-list">
                  {filteredRosterPickerArmies.map((army) => (
                    <button
                      type="button"
                      key={army.file}
                      className="deployment-panel__picker-item"
                      onMouseEnter={() => setRosterPickerHoveredDescription(army.description)}
                      onClick={() => handleSelectRoster(army.file)}
                    >
                      {army.display_name}
                    </button>
                  ))}
                  {filteredRosterPickerArmies.length === 0 && (
                    <div className="deployment-panel__picker-loading">
                      Aucun roster pour cette faction.
                    </div>
                  )}
                </div>
                <div className="deployment-panel__picker-tooltip">
                  {rosterPickerHoveredDescription || "Survolez une armee pour voir sa description"}
                </div>
              </div>
            )}
            <div className="deployment-panel__picker-actions">
              <button
                type="button"
                className="deployment-panel__picker-close"
                onClick={closeRosterPicker}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
      {activeRuleChoicePrompt && (
        <div className="rule-choice-overlay">
          <div
            className="deployment-panel__picker deployment-panel__picker--draggable deployment-panel__picker--rule-choice"
            style={{
              left: `${ruleChoicePopupPosition.x}px`,
              top: `${ruleChoicePopupPosition.y}px`,
            }}
          >
            <button
              type="button"
              className="deployment-panel__picker-title deployment-panel__picker-title--draggable"
              onMouseDown={onRuleChoiceTitleMouseDown}
            >
              {`Capacity choice - ${getRuleChoiceMomentLabel(activeRuleChoicePrompt)}${isDraggingRuleChoicePopup ? " (drag...)" : ""}`}
            </button>
            <div className="deployment-panel__picker-content deployment-panel__picker-content--rule-choice">
              <div className="deployment-panel__picker-list deployment-panel__picker-list--rule-choice">
                {ruleChoicePrompts.map((prompt) => {
                  const isFocused = focusedRuleChoicePrompt?.unit_id === prompt.unit_id;
                  return (
                    <div key={`${prompt.unit_id}:${prompt.rule_id}`} className="rule-choice-group">
                      <div className="rule-choice-group__row">
                        <div className="rule-choice-group__unit-col">
                          <button
                            type="button"
                            className={`deployment-panel__picker-item rule-choice-group__unit-btn ${getRulePromptPlayerClass(prompt)} ${isFocused ? "deployment-panel__picker-item--active" : ""}`}
                            onMouseEnter={() =>
                              setRuleChoiceHoveredDescription(getRuleDescription(prompt.rule_id))
                            }
                            onMouseLeave={() => setRuleChoiceHoveredDescription("")}
                            onClick={() => {
                              setRuleChoiceFocusedUnitId(prompt.unit_id);
                            }}
                          >
                            {getRulePromptUnitLabel(prompt)}
                          </button>
                        </div>
                        <div className="rule-choice-group__options-col">
                          <div className="rule-choice-group__options">
                            {prompt.options.map((option) => (
                              <TooltipWrapper
                                text={`Selectionner ${option.label}`}
                                key={option.display_rule_id}
                              >
                                <button
                                  type="button"
                                  className="deployment-panel__picker-item rule-choice-group__option"
                                  onMouseEnter={() =>
                                    setRuleChoiceHoveredDescription(
                                      getRuleDescription(option.display_rule_id)
                                    )
                                  }
                                  onMouseLeave={() => setRuleChoiceHoveredDescription("")}
                                  onBlur={() => setRuleChoiceHoveredDescription("")}
                                  onClick={() => {
                                    apiProps.onSelectRuleChoice(prompt, option.display_rule_id);
                                  }}
                                >
                                  {option.label}
                                </button>
                              </TooltipWrapper>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="deployment-panel__picker-tooltip deployment-panel__picker-tooltip--rule-choice">
                {focusedRuleChoicePrompt
                  ? getRulePromptDescription()
                  : "Aucun choix de regle actif"}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* AI Error Display */}
      {aiError && (
        <div className="bg-red-900 border border-red-700 rounded p-3 mb-2">
          <div className="flex items-center justify-between">
            <div className="text-red-100 text-sm">
              <strong>🤖 AI Error:</strong> {aiError}
            </div>
            <button
              type="button"
              onClick={clearAIError}
              className="text-red-300 hover:text-red-100 ml-2"
            ></button>
          </div>
        </div>
      )}

      <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
        <UnitStatusTablePlayer1WithTutorial
          units={apiProps.gameState?.units ?? []}
          player={1}
          playerTypes={apiProps.gameState?.player_types}
          selectedUnitId={highlightedRuleChoiceUnitId ?? apiProps.selectedUnitId ?? null}
          guidedFocusUnitId={activeRuleChoicePrompt ? highlightedRuleChoiceUnitId : null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          victoryPoints={getVictoryPointsForPlayer(1)}
          onCollapseChange={setPlayer1Collapsed}
        />
      </ErrorBoundary>

      <ErrorBoundary fallback={<div>Failed to load player 2 status</div>}>
        <UnitStatusTablePlayer2WithTutorial
          units={apiProps.gameState?.units ?? []}
          player={2}
          playerTypes={apiProps.gameState?.player_types}
          selectedUnitId={highlightedRuleChoiceUnitId ?? apiProps.selectedUnitId ?? null}
          guidedFocusUnitId={activeRuleChoicePrompt ? highlightedRuleChoiceUnitId : null}
          clickedUnitId={clickedUnitId}
          onSelectUnit={(unitId) => {
            apiProps.onSelectUnit(unitId);
            setClickedUnitId(null);
          }}
          gameMode={gameMode}
          victoryPoints={getVictoryPointsForPlayer(2)}
          onCollapseChange={setPlayer2Collapsed}
        />
      </ErrorBoundary>

      {/* Game Log Component */}
      <ErrorBoundary fallback={<div>Failed to load game log</div>}>
        <GameLogWithTutorialSpotlight
          events={gameLog.events}
          availableHeight={logAvailableHeight}
          currentTurn={apiProps.gameState?.currentTurn ?? 1}
          debugMode={settings.showDebug}
        />
      </ErrorBoundary>
    </RightColumnTutorialSpotlight>
  );

  const endlessDutyState = apiProps.endlessDutyState;
  const isEndlessDutyInterWave =
    gameMode === "endless_duty" && endlessDutyState?.inter_wave_pending === true;
  const currentWave = endlessDutyState?.wave_index ?? 1;
  const slotUnlockStatus = {
    leader: currentWave >= endlessDutyUnlockRules.leader,
    melee: currentWave >= endlessDutyUnlockRules.melee,
    range: currentWave >= endlessDutyUnlockRules.range,
  };
  const requisitionCapitalTotal = endlessDutyState?.requisition_capital_total ?? 0;
  const resolveSlotCost = (
    slot: keyof EndlessDutySlotProfiles,
    profile: string,
    picks: EndlessDutyPickState | null
  ): number | null => {
    if (!picks) {
      return null;
    }
    const menu = endlessDutyPickMenus[slot].get(profile);
    if (!menu) {
      return null;
    }
    let total = menu.baseCost;
    const findCost = (options: PickOption[], id: string | null): number | null => {
      if (!id) {
        return 0;
      }
      const option = options.find((opt) => opt.id === id);
      return option ? option.cost : null;
    };
    const packageCost = findCost(menu.primaryPackages, picks.package);
    const meleeCost = findCost(menu.primaryMelee, picks.melee);
    const rangedCost = findCost(menu.ranged, picks.ranged);
    const secondaryCost = findCost(menu.secondary, picks.secondary);
    const specialCost = findCost(menu.special, picks.special);
    if (
      packageCost == null ||
      meleeCost == null ||
      rangedCost == null ||
      secondaryCost == null ||
      specialCost == null
    ) {
      return null;
    }
    total += packageCost + meleeCost + rangedCost + secondaryCost + specialCost;
    return total;
  };
  const resolveDraftInvestedTotal = (
    draftProfiles: EndlessDutySlotProfiles,
    draftPicks: EndlessDutySlotPicks
  ): number | null => {
    const slotEntries: Array<keyof EndlessDutySlotProfiles> = ["leader", "melee", "range"];
    let total = 0;
    for (const slot of slotEntries) {
      const profile = draftProfiles[slot];
      if (profile == null) {
        continue;
      }
      const slotCost = resolveSlotCost(slot, profile, draftPicks[slot]);
      if (slotCost == null) {
        return null;
      }
      total += slotCost;
    }
    return total;
  };
  const projectedInvestedTotal = resolveDraftInvestedTotal(endlessDutyDraft, endlessDutyDraftPicks);
  const projectedAvailable =
    projectedInvestedTotal == null ? null : requisitionCapitalTotal - projectedInvestedTotal;
  const isProjectedDraftAffordable = projectedAvailable != null && projectedAvailable >= 0;
  const isOptionDraftAffordable = (
    slot: keyof EndlessDutySlotProfiles,
    profile: string | null,
    picks: EndlessDutyPickState | null
  ): boolean => {
    const candidateProfiles: EndlessDutySlotProfiles = {
      ...endlessDutyDraft,
      [slot]: profile,
    };
    const candidatePicks: EndlessDutySlotPicks = {
      ...endlessDutyDraftPicks,
      [slot]: picks,
    };
    const candidateInvested = resolveDraftInvestedTotal(candidateProfiles, candidatePicks);
    const candidateAvailable = candidateInvested == null ? null : requisitionCapitalTotal - candidateInvested;
    return candidateAvailable != null && candidateAvailable >= 0;
  };
  const getProfileLabel = (slot: keyof EndlessDutySlotProfiles, profile: string): string => {
    const defaultPicks = getDefaultPicksForProfile(slot, profile);
    const cost = resolveSlotCost(slot, profile, defaultPicks);
    if (typeof cost !== "number" || Number.isNaN(cost)) {
      return `${profile} (cout inconnu)`;
    }
    return `${profile} (a partir de ${cost})`;
  };
  const getPickMenuForSlot = (slot: keyof EndlessDutySlotProfiles): ProfilePickMenuData | null => {
    const profile = endlessDutyDraft[slot];
    if (!profile) {
      return null;
    }
    return endlessDutyPickMenus[slot].get(profile) ?? null;
  };

  return (
    <TutorialProvider
      isTutorialMode={activeTutorialMode}
      scenarioType={tutorialScenarioType}
      guideMode={isModeGuideActive ? modeGuideMode : null}
      gameState={apiProps.gameState ?? null}
      startGameWithScenario={apiProps.startGameWithScenario}
      onPauseAIChange={setPauseAIForTutorial}
      tutorialPauseAiSyncRef={tutorialPauseAiSyncRef}
      stopAiAfterPhaseChangeRef={stopAiAfterPhaseChangeRef}
      onTutorialComplete={isTutorialMode ? handleTutorialComplete : handleModeGuideComplete}
      onGoToPveMode={handleGoToPveMode}
    >
      <TutorialShootOptionsSync getTutorialShootOptionsRef={getTutorialShootOptionsRef} />
      <SharedLayout
        rightColumnContent={rightColumnContent}
        onOpenSettings={handleOpenSettings}
        onToggleMeasureMode={handleToggleMeasureMode}
        measureModeActive={measureModeActive}
      >
        {/*
        In test deployment setup, lock gameplay interactions until Start Game! is clicked.
      */}
        <BoardColumnWithTutorial boardRows={boardConfig?.rows ?? 21}>
          <BoardPvpWithTutorialAdvance
            units={apiProps.units}
            selectedUnitId={highlightedRuleChoiceUnitId ?? apiProps.selectedUnitId}
            ruleChoiceHighlightedUnitId={highlightedRuleChoiceUnitId}
            showHexCoordinates={settings.showDebug}
            showLosDebugOverlay={settings.showDebugLoS}
            eligibleUnitIds={apiProps.eligibleUnitIds}
            mode={apiProps.mode}
            movePreview={apiProps.movePreview}
            attackPreview={apiProps.attackPreview || null}
            wallHexesOverride={undefined}
            targetPreview={
              apiProps.targetPreview
                ? {
                    targetId: apiProps.targetPreview.targetId,
                    shooterId: apiProps.targetPreview.shooterId,
                    currentBlinkStep: apiProps.targetPreview.currentBlinkStep ?? 0,
                    totalBlinkSteps: apiProps.targetPreview.totalBlinkSteps ?? 2,
                    blinkTimer: apiProps.targetPreview.blinkTimer ?? null,
                    hitProbability: apiProps.targetPreview.hitProbability ?? 0.5,
                    woundProbability: apiProps.targetPreview.woundProbability ?? 0.5,
                    saveProbability: apiProps.targetPreview.saveProbability ?? 0.5,
                    overallProbability: apiProps.targetPreview.overallProbability ?? 0.25,
                  }
                : null
            }
            blinkingUnits={apiProps.blinkingUnits}
            blinkingAttackerId={apiProps.blinkingAttackerId}
            isBlinkingActive={apiProps.isBlinkingActive}
            onSelectUnit={
              isGameOver ||
              (isRosterSetupMode &&
                apiProps.gameState?.phase === "deployment" &&
                apiProps.gameState?.deployment_type === "active" &&
                !testDeploymentStarted)
                ? () => {}
                : apiProps.onSelectUnit
            }
            onSkipUnit={isGameOver ? () => {} : apiProps.onSkipUnit}
            onStartMovePreview={isGameOver ? () => {} : apiProps.onStartMovePreview}
            onDirectMove={isGameOver ? () => {} : apiProps.onDirectMove}
            onStartAttackPreview={isGameOver ? () => {} : apiProps.onStartAttackPreview}
            onDeployUnit={
              isGameOver ||
              (isRosterSetupMode &&
                apiProps.gameState?.phase === "deployment" &&
                apiProps.gameState?.deployment_type === "active" &&
                !testDeploymentStarted)
                ? () => {}
                : apiProps.onDeployUnit
            }
            onConfirmMove={isGameOver ? () => {} : apiProps.onConfirmMove}
            onCancelMove={isGameOver ? () => {} : apiProps.onCancelMove}
            onShoot={isGameOver ? () => {} : apiProps.onShoot}
            onSkipShoot={isGameOver ? () => {} : apiProps.onSkipShoot}
            onStartTargetPreview={isGameOver ? () => {} : apiProps.onStartTargetPreview}
            onCancelTargetPreview={() => {
              const targetPreview = apiProps.targetPreview as TargetPreview | null;
              if (targetPreview?.blinkTimer) {
                clearInterval(targetPreview.blinkTimer);
              }
              // Clear target preview in engine API
            }}
            onFightAttack={isGameOver ? () => {} : apiProps.onFightAttack}
            onActivateFight={isGameOver ? () => {} : apiProps.onActivateFight}
            current_player={apiProps.current_player as PlayerId}
            unitsMoved={apiProps.unitsMoved}
            unitsCharged={apiProps.unitsCharged}
            unitsAttacked={apiProps.unitsAttacked}
            unitsFled={apiProps.unitsFled}
            phase={apiProps.phase as "deployment" | "move" | "shoot" | "charge" | "fight"}
            fightSubPhase={apiProps.fightSubPhase}
            onCharge={isGameOver ? () => {} : apiProps.onCharge}
            onActivateCharge={isGameOver ? () => {} : apiProps.onActivateCharge}
            onChargeEnemyUnit={isGameOver ? () => {} : apiProps.onChargeEnemyUnit}
            onMoveCharger={isGameOver ? () => {} : apiProps.onMoveCharger}
            onCancelCharge={isGameOver ? () => {} : apiProps.onCancelCharge}
            onValidateCharge={isGameOver ? () => {} : apiProps.onValidateCharge}
            onLogChargeRoll={isGameOver ? () => {} : apiProps.onLogChargeRoll}
            chargingUnitId={apiProps.chargingUnitId}
            chargeTargetId={apiProps.chargeTargetId ?? null}
            chargeRoll={apiProps.chargeRoll}
            chargeSuccess={apiProps.chargeSuccess}
            gameState={apiProps.gameState as GameState}
            getChargeDestinations={apiProps.getChargeDestinations}
            chargePreviewOverlayHexes={apiProps.chargePreviewOverlayHexes ?? []}
            chargeReferenceHex={apiProps.chargeReferenceHex ?? null}
            moveDestPoolRef={apiProps.moveDestPoolRef}
            footprintZoneRef={apiProps.footprintZoneRef}
            chargeDestPoolRef={apiProps.chargeDestPoolRef}
            chargeFootprintZoneRef={apiProps.chargeFootprintZoneRef}
            onAdvance={isGameOver ? () => {} : apiProps.onAdvance}
            onAdvanceMove={isGameOver ? () => {} : apiProps.onAdvanceMove}
            onCancelAdvance={isGameOver ? () => {} : apiProps.onCancelAdvance}
            getAdvanceDestinations={apiProps.getAdvanceDestinations}
            availableCellsOverride={apiProps.availableCellsOverride}
            advanceRoll={apiProps.advanceRoll}
            advancingUnitId={apiProps.advancingUnitId}
            advanceWarningPopup={apiProps.advanceWarningPopup}
            onConfirmAdvanceWarning={isGameOver ? () => {} : apiProps.onConfirmAdvanceWarning}
            onCancelAdvanceWarning={isGameOver ? () => {} : apiProps.onCancelAdvanceWarning}
            onSkipAdvanceWarning={isGameOver ? () => {} : apiProps.onSkipAdvanceWarning}
            showAdvanceWarningPopup={false}
            autoSelectWeapon={settings.autoSelectWeapon}
            deploymentState={apiProps.gameState?.deployment_state as DeploymentState | undefined}
            objectivesOverride={objectivesOverride}
            measureMode={measureMode}
            onMeasureHexCommit={handleMeasureHexCommit}
          />
          {isRosterSetupMode &&
            apiProps.gameState?.phase === "deployment" &&
            apiProps.gameState?.deployment_type === "active" &&
            !testDeploymentStarted && (
              <div className="test-start-overlay">
                <div className="test-start-modal">
                  <button
                    type="button"
                    className="test-start-bar__button"
                    onClick={() => {
                      closeRosterPicker();
                      setTestDeploymentStarted(true);
                      window.dispatchEvent(new Event("modeGuideStartDeployment"));
                    }}
                  >
                    Start Deployment
                  </button>
                </div>
              </div>
            )}
        </BoardColumnWithTutorial>
      </SharedLayout>
      <TutorialOverlayGate />
      {isEndlessDutyInterWave && isEndlessDutyModalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="endless-duty-title"
            style={{
              width: "min(720px, calc(100vw - 32px))",
              backgroundColor: "#0b1322",
              border: "2px solid #60a5fa",
              borderRadius: "10px",
              boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
              padding: "22px 24px 18px 24px",
              color: "#dbeafe",
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="endless-duty-title" style={{ margin: "0 0 8px 0", color: "#bfdbfe", fontSize: "28px" }}>
              Endless Duty - Requisition
            </h2>
            <p style={{ margin: "0 0 12px 0", lineHeight: 1.5, fontSize: "16px" }}>
              Wave {currentWave} cleared. Configurez votre escouade avant la prochaine vague.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px", marginBottom: "14px" }}>
              <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid #334155", borderRadius: "6px", padding: "8px 10px" }}>
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Capital total</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>{endlessDutyState?.requisition_capital_total ?? 0}</div>
              </div>
              <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid #334155", borderRadius: "6px", padding: "8px 10px" }}>
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Investi</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>{endlessDutyState?.requisition_invested_total ?? 0}</div>
              </div>
              <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid #334155", borderRadius: "6px", padding: "8px 10px" }}>
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Disponible</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>{endlessDutyState?.requisition_available ?? 0}</div>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "14px" }}>
              <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid #334155", borderRadius: "6px", padding: "8px 10px" }}>
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Investi projete</div>
                <div style={{ fontSize: "18px", fontWeight: 700 }}>
                  {projectedInvestedTotal == null ? "-" : projectedInvestedTotal}
                </div>
              </div>
              <div style={{ background: "rgba(15, 23, 42, 0.8)", border: "1px solid #334155", borderRadius: "6px", padding: "8px 10px" }}>
                <div style={{ fontSize: "12px", color: "#94a3b8" }}>Disponible projete</div>
                <div style={{ fontSize: "18px", fontWeight: 700, color: isProjectedDraftAffordable ? "#86efac" : "#fca5a5" }}>
                  {projectedAvailable == null ? "-" : projectedAvailable}
                </div>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "10px" }}>
              <label style={{ display: "grid", gap: "6px" }}>
                <span style={{ fontWeight: 600 }}>
                  Leader (deverrouille wave {endlessDutyUnlockRules.leader})
                </span>
                <select
                  value={endlessDutyDraft.leader ?? ""}
                  disabled={!slotUnlockStatus.leader || isSubmittingEndlessDuty}
                  onChange={(event) =>
                    handleEndlessDutyDraftChange("leader", event.target.value === "" ? null : event.target.value)
                  }
                  style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                >
                  <option value="" disabled>
                    Choisir un leader (obligatoire)
                  </option>
                  {endlessDutyProfileOptions.leader.map((profile) => (
                    <option
                      key={`ed-leader-${profile}`}
                      value={profile}
                      disabled={
                        !isOptionDraftAffordable(
                          "leader",
                          profile,
                          getDefaultPicksForProfile("leader", profile)
                        )
                      }
                    >
                      {getProfileLabel("leader", profile)}
                    </option>
                  ))}
                </select>
                {(() => {
                  const menu = getPickMenuForSlot("leader");
                  const picks = endlessDutyDraftPicks.leader;
                  const hasPackage = picks?.package != null;
                  if (!menu || !picks) {
                    return null;
                  }
                  return (
                    <>
                      <select
                        value={picks.package ?? picks.melee ?? ""}
                        disabled={!slotUnlockStatus.leader || isSubmittingEndlessDuty || !endlessDutyDraft.leader}
                        onChange={(event) => {
                          const value = event.target.value === "" ? null : event.target.value;
                          if (value && menu.primaryPackages.some((opt) => opt.id === value)) {
                            handleEndlessDutyPickChange("leader", "package", value);
                            handleEndlessDutyPickChange("leader", "melee", null);
                          } else {
                            handleEndlessDutyPickChange("leader", "package", null);
                            handleEndlessDutyPickChange("leader", "melee", value);
                          }
                        }}
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Arme principale (melee ou pack)</option>
                        {menu.primaryPackages.map((option) => (
                          <option key={`ed-leader-package-${option.id}`} value={option.id}>
                            [PACK] {option.label}
                          </option>
                        ))}
                        {menu.primaryMelee.map((option) => (
                          <option key={`ed-leader-melee-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.ranged ?? ""}
                        disabled={
                          !slotUnlockStatus.leader ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.leader ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "leader",
                            "ranged",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Arme a distance</option>
                        {menu.ranged.map((option) => (
                          <option key={`ed-leader-ranged-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.secondary ?? ""}
                        disabled={
                          !slotUnlockStatus.leader ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.leader ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "leader",
                            "secondary",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Secondaire</option>
                        {menu.secondary.map((option) => (
                          <option key={`ed-leader-secondary-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.special ?? ""}
                        disabled={
                          !slotUnlockStatus.leader ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.leader ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "leader",
                            "special",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Special (equipement/special)</option>
                        {menu.special.map((option) => (
                          <option key={`ed-leader-special-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </>
                  );
                })()}
              </label>
              <label style={{ display: "grid", gap: "6px" }}>
                <span style={{ fontWeight: 600 }}>
                  Melee (deverrouille wave {endlessDutyUnlockRules.melee})
                </span>
                <select
                  value={endlessDutyDraft.melee ?? ""}
                  disabled={!slotUnlockStatus.melee || isSubmittingEndlessDuty}
                  onChange={(event) =>
                    handleEndlessDutyDraftChange("melee", event.target.value === "" ? null : event.target.value)
                  }
                  style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                >
                  <option value="">Aucun</option>
                  {endlessDutyProfileOptions.melee.map((profile) => (
                    <option
                      key={`ed-melee-${profile}`}
                      value={profile}
                      disabled={
                        !isOptionDraftAffordable(
                          "melee",
                          profile,
                          getDefaultPicksForProfile("melee", profile)
                        )
                      }
                    >
                      {getProfileLabel("melee", profile)}
                    </option>
                  ))}
                </select>
                {(() => {
                  const menu = getPickMenuForSlot("melee");
                  const picks = endlessDutyDraftPicks.melee;
                  const hasPackage = picks?.package != null;
                  if (!menu || !picks) {
                    return null;
                  }
                  return (
                    <>
                      <select
                        value={picks.package ?? picks.melee ?? ""}
                        disabled={!slotUnlockStatus.melee || isSubmittingEndlessDuty || !endlessDutyDraft.melee}
                        onChange={(event) => {
                          const value = event.target.value === "" ? null : event.target.value;
                          if (value && menu.primaryPackages.some((opt) => opt.id === value)) {
                            handleEndlessDutyPickChange("melee", "package", value);
                            handleEndlessDutyPickChange("melee", "melee", null);
                          } else {
                            handleEndlessDutyPickChange("melee", "package", null);
                            handleEndlessDutyPickChange("melee", "melee", value);
                          }
                        }}
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Arme principale (melee ou pack)</option>
                        {menu.primaryPackages.map((option) => (
                          <option key={`ed-melee-package-${option.id}`} value={option.id}>
                            [PACK] {option.label}
                          </option>
                        ))}
                        {menu.primaryMelee.map((option) => (
                          <option key={`ed-melee-melee-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.ranged ?? ""}
                        disabled={
                          !slotUnlockStatus.melee ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.melee ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "melee",
                            "ranged",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Arme a distance</option>
                        {menu.ranged.map((option) => (
                          <option key={`ed-melee-ranged-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.secondary ?? ""}
                        disabled={
                          !slotUnlockStatus.melee ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.melee ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "melee",
                            "secondary",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Secondaire</option>
                        {menu.secondary.map((option) => (
                          <option key={`ed-melee-secondary-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.special ?? ""}
                        disabled={
                          !slotUnlockStatus.melee ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.melee ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "melee",
                            "special",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Special (equipement/special)</option>
                        {menu.special.map((option) => (
                          <option key={`ed-melee-special-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </>
                  );
                })()}
              </label>
              <label style={{ display: "grid", gap: "6px" }}>
                <span style={{ fontWeight: 600 }}>
                  Range (deverrouille wave {endlessDutyUnlockRules.range})
                </span>
                <select
                  value={endlessDutyDraft.range ?? ""}
                  disabled={!slotUnlockStatus.range || isSubmittingEndlessDuty}
                  onChange={(event) =>
                    handleEndlessDutyDraftChange("range", event.target.value === "" ? null : event.target.value)
                  }
                  style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                >
                  <option value="">Aucun</option>
                  {endlessDutyProfileOptions.range.map((profile) => (
                    <option
                      key={`ed-range-${profile}`}
                      value={profile}
                      disabled={
                        !isOptionDraftAffordable(
                          "range",
                          profile,
                          getDefaultPicksForProfile("range", profile)
                        )
                      }
                    >
                      {getProfileLabel("range", profile)}
                    </option>
                  ))}
                </select>
                {(() => {
                  const menu = getPickMenuForSlot("range");
                  const picks = endlessDutyDraftPicks.range;
                  const hasPackage = picks?.package != null;
                  if (!menu || !picks) {
                    return null;
                  }
                  return (
                    <>
                      <select
                        value={picks.package ?? picks.melee ?? ""}
                        disabled={!slotUnlockStatus.range || isSubmittingEndlessDuty || !endlessDutyDraft.range}
                        onChange={(event) => {
                          const value = event.target.value === "" ? null : event.target.value;
                          if (value && menu.primaryPackages.some((opt) => opt.id === value)) {
                            handleEndlessDutyPickChange("range", "package", value);
                            handleEndlessDutyPickChange("range", "melee", null);
                          } else {
                            handleEndlessDutyPickChange("range", "package", null);
                            handleEndlessDutyPickChange("range", "melee", value);
                          }
                        }}
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Arme principale (melee ou pack)</option>
                        {menu.primaryPackages.map((option) => (
                          <option key={`ed-range-package-${option.id}`} value={option.id}>
                            [PACK] {option.label}
                          </option>
                        ))}
                        {menu.primaryMelee.map((option) => (
                          <option key={`ed-range-melee-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.ranged ?? ""}
                        disabled={
                          !slotUnlockStatus.range ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.range ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "range",
                            "ranged",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Arme a distance</option>
                        {menu.ranged.map((option) => (
                          <option key={`ed-range-ranged-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.secondary ?? ""}
                        disabled={
                          !slotUnlockStatus.range ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.range ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "range",
                            "secondary",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Secondaire</option>
                        {menu.secondary.map((option) => (
                          <option key={`ed-range-secondary-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={picks.special ?? ""}
                        disabled={
                          !slotUnlockStatus.range ||
                          isSubmittingEndlessDuty ||
                          !endlessDutyDraft.range ||
                          hasPackage
                        }
                        onChange={(event) =>
                          handleEndlessDutyPickChange(
                            "range",
                            "special",
                            event.target.value === "" ? null : event.target.value
                          )
                        }
                        style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#e2e8f0" }}
                      >
                        <option value="">Special (equipement/special)</option>
                        {menu.special.map((option) => (
                          <option key={`ed-range-special-${option.id}`} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </>
                  );
                })()}
              </label>
            </div>
            {!isProjectedDraftAffordable && (
              <div
                style={{
                  marginTop: "12px",
                  padding: "8px 10px",
                  borderRadius: "6px",
                  border: "1px solid #f59e0b",
                  color: "#fde68a",
                  background: "rgba(120, 53, 15, 0.35)",
                  fontSize: "14px",
                }}
              >
                Selection invalide: requisition insuffisante pour ce draft.
              </div>
            )}
            {endlessDutyFormError && (
              <div
                style={{
                  marginTop: "12px",
                  padding: "8px 10px",
                  borderRadius: "6px",
                  border: "1px solid #f87171",
                  color: "#fecaca",
                  background: "rgba(127, 29, 29, 0.35)",
                  fontSize: "14px",
                }}
              >
                {endlessDutyFormError}
              </div>
            )}
            <div style={{ marginTop: "16px", display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <button
                type="button"
                onClick={() => {
                  void apiProps.fetchEndlessDutyStatus().catch(() => {});
                }}
                disabled={isSubmittingEndlessDuty}
                style={{
                  padding: "10px 14px",
                  border: "1px solid #64748b",
                  borderRadius: "6px",
                  background: "rgba(30, 41, 59, 0.9)",
                  color: "#e2e8f0",
                  cursor: isSubmittingEndlessDuty ? "not-allowed" : "pointer",
                }}
              >
                Refresh
              </button>
              <button
                type="button"
                onClick={() => {
                  void handleEndlessDutyCommit();
                }}
                disabled={isSubmittingEndlessDuty || !isProjectedDraftAffordable}
                style={{
                  padding: "10px 14px",
                  border: "1px solid #60a5fa",
                  borderRadius: "6px",
                  background: isSubmittingEndlessDuty || !isProjectedDraftAffordable ? "#334155" : "#1d4ed8",
                  color: "#eff6ff",
                  cursor: isSubmittingEndlessDuty || !isProjectedDraftAffordable ? "not-allowed" : "pointer",
                  fontWeight: 600,
                }}
              >
                {isSubmittingEndlessDuty ? "Validation..." : "Valider et lancer vague suivante"}
              </button>
            </div>
          </div>
        </div>
      )}
      {apiProps.advanceWarningPopup && settings.showAdvanceWarning && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
          onClick={() => {
            if (advanceWarningDontRemind) {
              handleToggleAdvanceWarning(false);
            }
            void apiProps.onCancelAdvanceWarning();
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="advance-warning-title"
            style={{
              width: "min(640px, calc(100vw - 32px))",
              backgroundColor: "#06120a",
              border: "2px solid #22c55e",
              borderRadius: "10px",
              boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
              padding: "22px 24px 18px 24px",
              color: "#e5fbe9",
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="advance-warning-title" style={{ margin: "0 0 12px 0", color: "#86efac", fontSize: "30px" }}>
              Advance !
            </h2>
            <p style={{ margin: 0, lineHeight: 1.5, fontSize: "19px" }}>
              Vous êtes sur le point d&apos;effectuer une action Advance. Si vous la validez, cette unité ne pourra
              ni tirer ni charger jusqu&apos;à la fin de ce tour.
            </p>
            <div style={{ marginTop: "20px", display: "flex", justifyContent: "space-between", alignItems: "end" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={advanceWarningDontRemind}
                  onChange={(event) => setAdvanceWarningDontRemind(event.target.checked)}
                  style={{ width: "18px", height: "18px", cursor: "pointer" }}
                />
                <span style={{ fontSize: "16px", color: "#d1fae5" }}>Ne plus me rappeler</span>
              </label>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  type="button"
                  onClick={() => {
                    if (advanceWarningDontRemind) {
                      handleToggleAdvanceWarning(false);
                    }
                    void apiProps.onCancelAdvanceWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #9ca3af",
                    borderRadius: "6px",
                    background: "rgba(31, 41, 55, 0.9)",
                    color: "#f3f4f6",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                >
                  Annuler l&apos;advance
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (advanceWarningDontRemind) {
                      handleToggleAdvanceWarning(false);
                    }
                    void apiProps.onConfirmAdvanceWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #22c55e",
                    borderRadius: "6px",
                    background: "#065f46",
                    color: "#ecfdf5",
                    cursor: "pointer",
                    fontSize: "16px",
                    fontWeight: 600,
                  }}
                >
                  Valider
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {apiProps.fleeWarningPopup && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0, 0, 0, 0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 12000,
          }}
          onClick={() => {
            if (apiProps.fleeWarningPopup?.dontRemind) {
              updateRetreatAlertSetting(false);
            }
            void apiProps.onCancelFleeWarning();
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="retreat-warning-title"
            style={{
              width: "min(640px, calc(100vw - 32px))",
              backgroundColor: "#06120a",
              border: "2px solid #22c55e",
              borderRadius: "10px",
              boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
              padding: "22px 24px 18px 24px",
              color: "#e5fbe9",
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="retreat-warning-title" style={{ margin: "0 0 12px 0", color: "#86efac", fontSize: "30px" }}>
              Retraite !
            </h2>
            <p style={{ margin: 0, lineHeight: 1.5, fontSize: "19px" }}>
              Vous êtes sur le point d'effectuer un mouvement de Retraite. Si vous le validez, cette unité ne
              pourra ni tirer ni charger jusqu&apos; à la fin de ce tour.
            </p>
            <div style={{ marginTop: "20px", display: "flex", justifyContent: "space-between", alignItems: "end" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={apiProps.fleeWarningPopup.dontRemind}
                  onChange={(event) => apiProps.onToggleFleeWarningDontRemind(event.target.checked)}
                  style={{ width: "18px", height: "18px", cursor: "pointer" }}
                />
                <span style={{ fontSize: "16px", color: "#d1fae5" }}>Ne plus me rappeler</span>
              </label>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  type="button"
                  onClick={() => {
                    if (apiProps.fleeWarningPopup?.dontRemind) {
                      updateRetreatAlertSetting(false);
                    }
                    void apiProps.onCancelFleeWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #9ca3af",
                    borderRadius: "6px",
                    background: "rgba(31, 41, 55, 0.9)",
                    color: "#f3f4f6",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                >
                  Annuler la retraite
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (apiProps.fleeWarningPopup?.dontRemind) {
                      updateRetreatAlertSetting(false);
                    }
                    void apiProps.onConfirmFleeWarning();
                  }}
                  style={{
                    padding: "10px 14px",
                    border: "1px solid #22c55e",
                    borderRadius: "6px",
                    background: "#065f46",
                    color: "#ecfdf5",
                    cursor: "pointer",
                    fontSize: "16px",
                    fontWeight: 600,
                  }}
                >
                  Valider
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      <SettingsMenu
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onLogout={() => {
          clearAuthSession();
          window.location.href = "/auth";
        }}
        showAdvanceWarning={settings.showAdvanceWarning}
        canToggleAdvanceWarning={canUseAdvanceWarning}
        onToggleAdvanceWarning={handleToggleAdvanceWarning}
        showDebug={settings.showDebug}
        onToggleDebug={handleToggleDebug}
        showDebugLoS={settings.showDebugLoS}
        onToggleDebugLoS={handleToggleDebugLoS}
        autoSelectWeapon={settings.autoSelectWeapon}
        canToggleAutoSelectWeapon={canUseAutoWeaponSelection}
        onToggleAutoSelectWeapon={handleToggleAutoSelectWeapon}
        retreatAlertEnabled={settings.retreatAlertEnabled}
        onToggleRetreatAlert={handleToggleRetreatAlert}
        modeGuidesActivated={settings.modeGuidesActivated}
        onToggleModeGuidesActivated={handleToggleModeGuidesActivated}
      />
    </TutorialProvider>
  );
};
