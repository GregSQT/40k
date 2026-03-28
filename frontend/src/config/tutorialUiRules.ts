import { getTutorialScenarioRuntimeData } from "./tutorialScenarioRuntime";

export type TutorialAfterCursorIconKey =
  | "intercessor"
  | "intercessorGreen"
  | "hex"
  | "weaponMenu"
  | "termagant";

export type TutorialSpotlightId =
  | "board.activeUnit"
  | "table.p1.nameM"
  | "table.p1.rangedWeapons"
  | "table.p2.attributes"
  | "table.p2.unitRows"
  | "board.unitRows"
  | "turnPhase.all"
  | "panel.left"
  | "gamelog.lastEntry"
  | "gamelog.header"
  | "gamelog.last2Entries"
  | "guide.p1.changeRoster"
  | "guide.p2.changeRoster"
  | "guide.startDeployment"
  | "guide.p1.deploymentZone"
  | "guide.p1.roster";

export interface TutorialUiRuntimeConfig {
  /** Master switch for tutorial UI rule resolution. */
  enabled: boolean;
  /** Debug mode for config-driven tutorial UI behavior. */
  debugMode: boolean;
  /** Generic opacity for global fog backdrop. */
  fogBackdropOpacity: number;
}

export interface TutorialUiBehavior {
  /**
   * Opacity of the global tutorial backdrop.
   * Must be in [0, 1] when provided.
   */
  overlayBackdropOpacity?: number;
  /**
   * Optional override for mini icon displayed after <cursor>.
   * - undefined: keep component default behavior
   * - null: explicitly disable icon
   */
  afterCursorIcon?: TutorialAfterCursorIconKey | null;
  /** Force disable fog overlays (left/right panel) for this stage. */
  forceNoFog?: boolean;
  /** Force display fog overlay on right panel for this stage. */
  forceRightPanelFog?: boolean;
  /** Force disable popup illustration block (popup_image / move-hex / green-circle). */
  hidePopupIllustrationBlock?: boolean;
  /** Render popup image with ghost styling (opacity + grayscale). */
  popupImageGhost?: boolean;
  /** Override phase icon shown in popup title. */
  phaseDisplayOverride?: "move" | "shoot" | "charge" | "fight";
  /** Spotlights to display for this stage. */
  spotlightIds?: TutorialSpotlightId[];
  /** Restrict clickable spotlight holes for this stage (defaults to spotlightIds when omitted). */
  allowedClickSpotlightIds?: TutorialSpotlightId[];
  /**
   * Optional override for advance_on_weapon_click behavior.
   * Useful for pedagogical sub-steps that must use "Suivant".
   */
  forceAdvanceOnWeaponClick?: boolean;
  /**
   * When the last enemy dies, enforce sequential sub-steps until this order.
   * Example: 25 means "play all sub-steps with order < 25 before step 1-25".
   */
  sequentialSubstepsUntilOrder?: number;
}

interface TutorialUiRule {
  stagePattern: string;
  behavior: TutorialUiBehavior;
}

function validateStagePattern(stagePattern: string): void {
  if (stagePattern.trim() === "") {
    throw new Error("tutorialUiRules: stagePattern cannot be empty");
  }
  const wildcardCount = stagePattern.split("*").length - 1;
  if (wildcardCount === 0) return;
  if (wildcardCount > 1 || !stagePattern.endsWith("*")) {
    throw new Error(
      `tutorialUiRules: invalid stagePattern "${stagePattern}". Only suffix wildcard is supported (e.g. "1-24-*").`
    );
  }
}

function validateBehavior(rule: TutorialUiRule): void {
  const { behavior, stagePattern } = rule;
  if (behavior.overlayBackdropOpacity != null) {
    const v = behavior.overlayBackdropOpacity;
    if (!Number.isFinite(v) || v < 0 || v > 1) {
      throw new Error(
        `tutorialUiRules: overlayBackdropOpacity must be in [0,1] for pattern "${stagePattern}"`
      );
    }
  }
  if (behavior.sequentialSubstepsUntilOrder != null) {
    const v = behavior.sequentialSubstepsUntilOrder;
    if (!Number.isFinite(v) || v <= 0) {
      throw new Error(
        `tutorialUiRules: sequentialSubstepsUntilOrder must be > 0 for pattern "${stagePattern}"`
      );
    }
  }
  if (behavior.allowedClickSpotlightIds != null && behavior.spotlightIds == null) {
    throw new Error(
      `tutorialUiRules: allowedClickSpotlightIds requires spotlightIds for pattern "${stagePattern}"`
    );
  }
  if (behavior.forceRightPanelFog != null && typeof behavior.forceRightPanelFog !== "boolean") {
    throw new Error(
      `tutorialUiRules: forceRightPanelFog must be boolean for pattern "${stagePattern}"`
    );
  }
  if (behavior.popupImageGhost != null && typeof behavior.popupImageGhost !== "boolean") {
    throw new Error(
      `tutorialUiRules: popupImageGhost must be boolean for pattern "${stagePattern}"`
    );
  }
}

function parseTutorialUiRuntimeConfig(raw: unknown): TutorialUiRuntimeConfig {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("tutorialUiRules: runtime_config must be an object");
  }
  const cfg = raw as Record<string, unknown>;
  if (typeof cfg.enabled !== "boolean") {
    throw new Error("tutorialUiRules: runtime_config.enabled must be boolean");
  }
  if (typeof cfg.debugMode !== "boolean") {
    throw new Error("tutorialUiRules: runtime_config.debugMode must be boolean");
  }
  if (typeof cfg.fogBackdropOpacity !== "number") {
    throw new Error("tutorialUiRules: runtime_config.fogBackdropOpacity must be number");
  }
  if (!Number.isFinite(cfg.fogBackdropOpacity) || cfg.fogBackdropOpacity < 0 || cfg.fogBackdropOpacity > 1) {
    throw new Error("tutorialUiRules: runtime_config.fogBackdropOpacity must be in [0,1]");
  }
  return {
    enabled: cfg.enabled,
    debugMode: cfg.debugMode,
    fogBackdropOpacity: cfg.fogBackdropOpacity,
  };
}

function parseTutorialUiRules(raw: unknown): TutorialUiRule[] {
  if (!Array.isArray(raw)) {
    throw new Error("tutorialUiRules: rules must be an array");
  }
  return raw.map((entry, idx) => {
    if (typeof entry !== "object" || entry === null) {
      throw new Error(`tutorialUiRules: rules[${idx}] must be an object`);
    }
    const record = entry as Record<string, unknown>;
    if (typeof record.stagePattern !== "string") {
      throw new Error(`tutorialUiRules: rules[${idx}].stagePattern must be a string`);
    }
    if (typeof record.behavior !== "object" || record.behavior === null) {
      throw new Error(`tutorialUiRules: rules[${idx}].behavior must be an object`);
    }
    const parsed: TutorialUiRule = {
      stagePattern: record.stagePattern,
      behavior: record.behavior as TutorialUiBehavior,
    };
    validateStagePattern(parsed.stagePattern);
    validateBehavior(parsed);
    return parsed;
  });
}

const RUNTIME_DATA = getTutorialScenarioRuntimeData();

export const TUTORIAL_UI_RUNTIME_CONFIG: TutorialUiRuntimeConfig = (() => {
  if (RUNTIME_DATA.runtime_config == null) {
    throw new Error("tutorialUiRules: missing runtime_config");
  }
  return parseTutorialUiRuntimeConfig(RUNTIME_DATA.runtime_config);
})();

const RULES: readonly TutorialUiRule[] = (() => {
  if (RUNTIME_DATA.rules == null) {
    throw new Error("tutorialUiRules: missing rules");
  }
  return parseTutorialUiRules(RUNTIME_DATA.rules);
})();

export function matchesTutorialStagePattern(stage: string, stagePattern: string): boolean {
  if (stage.trim() === "") {
    // No active tutorial stage yet (initial render): treat as non-match.
    return false;
  }
  if (stagePattern.endsWith("*")) {
    const prefix = stagePattern.slice(0, -1);
    return stage.startsWith(prefix);
  }
  return stage === stagePattern;
}

export function getTutorialUiBehavior(stage: string): TutorialUiBehavior {
  if (stage.trim() === "") {
    throw new Error("getTutorialUiBehavior: stage cannot be empty");
  }
  if (!TUTORIAL_UI_RUNTIME_CONFIG.enabled) {
    return {};
  }
  const merged: TutorialUiBehavior = {};
  for (const rule of RULES) {
    if (!matchesTutorialStagePattern(stage, rule.stagePattern)) continue;
    Object.assign(merged, rule.behavior);
  }
  return merged;
}

export function isTutorialUiDebugModeEnabled(): boolean {
  return TUTORIAL_UI_RUNTIME_CONFIG.debugMode;
}

