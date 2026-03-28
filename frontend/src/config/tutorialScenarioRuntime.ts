import { load } from "js-yaml";
import tutorialScenarioYamlRaw from "../../../config/tutorial/tutorial_scenario.yaml?raw";
import modeGuideYamlRaw from "../../../config/tutorial/mode_guide.yaml?raw";

/**
 * Référence au YAML brut pour le HMR Vite : quand le fichier change, les modules qui en dépendent
 * (ex. TutorialContext) se réévaluent et peuvent recharger les steps sans rechargement complet de la page.
 */
export const tutorialScenarioYamlRevision = tutorialScenarioYamlRaw;
export const modeGuideYamlRevision = modeGuideYamlRaw;

interface TutorialScenarioRuntimeData {
  runtime_config: unknown;
  rules: unknown;
  steps: unknown;
}

function parseAssets(raw: unknown): Record<string, string> {
  if (raw == null) return {};
  if (typeof raw !== "object") {
    throw new Error("tutorial_scenario.yaml assets must be an object");
  }
  const assets = raw as Record<string, unknown>;
  const parsed: Record<string, string> = {};
  for (const [key, value] of Object.entries(assets)) {
    if (typeof value !== "string" || value.trim() === "") {
      throw new Error(`tutorial_scenario.yaml assets.${key} must be a non-empty string`);
    }
    parsed[key] = value;
  }
  return parsed;
}

function resolveAssetRef(value: unknown, assets: Record<string, string>, fieldPath: string): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed.startsWith("@")) return value;
  const assetKey = trimmed.slice(1);
  if (assetKey === "") {
    throw new Error(`${fieldPath}: invalid empty asset reference`);
  }
  const resolved = assets[assetKey];
  if (typeof resolved !== "string" || resolved.trim() === "") {
    throw new Error(`${fieldPath}: unknown asset reference "@${assetKey}"`);
  }
  return resolved;
}

function resolveInlineIconRefs(value: unknown, assets: Record<string, string>, fieldPath: string): unknown {
  if (typeof value !== "string") return value;
  return value.replace(/<icon:\s*@([A-Za-z0-9._-]+)\s*>/g, (_match, key: string) => {
    const resolved = assets[key];
    if (typeof resolved !== "string" || resolved.trim() === "") {
      throw new Error(`${fieldPath}: unknown inline asset reference "@${key}"`);
    }
    return `<icon:${resolved}>`;
  });
}

function buildRuntimeData(): TutorialScenarioRuntimeData {
  const parsed = load(tutorialScenarioYamlRaw);
  if (typeof parsed !== "object" || parsed == null) {
    throw new Error("tutorial_scenario.yaml must contain an object at top level");
  }
  const doc = parsed as Record<string, unknown>;
  if (doc.runtime_config == null) {
    throw new Error("tutorial_scenario.yaml missing runtime_config");
  }
  if (!Array.isArray(doc.rules)) {
    throw new Error("tutorial_scenario.yaml missing rules[]");
  }
  if (!Array.isArray(doc.steps)) {
    throw new Error("tutorial_scenario.yaml missing steps[]");
  }
  const assets = parseAssets(doc.assets);
  const resolvedSteps = doc.steps.map((entry, idx) => {
    if (typeof entry !== "object" || entry == null) {
      throw new Error(`tutorial_scenario.yaml steps[${idx}] must be an object`);
    }
    const step = { ...(entry as Record<string, unknown>) };
    step.title_icon = resolveAssetRef(step.title_icon, assets, `steps[${idx}].title_icon`);
    step.popup_image = resolveAssetRef(step.popup_image, assets, `steps[${idx}].popup_image`);
    step.body_fr = resolveInlineIconRefs(step.body_fr, assets, `steps[${idx}].body_fr`);
    step.body_en = resolveInlineIconRefs(step.body_en, assets, `steps[${idx}].body_en`);
    return step;
  });

  return {
    runtime_config: doc.runtime_config,
    rules: doc.rules,
    steps: resolvedSteps,
  };
}

export function getTutorialScenarioRuntimeData(): TutorialScenarioRuntimeData {
  return buildRuntimeData();
}

function buildModeGuideRuntimeData(): TutorialScenarioRuntimeData {
  const parsed = load(modeGuideYamlRaw);
  if (typeof parsed !== "object" || parsed == null) {
    throw new Error("mode_guide.yaml must contain an object at top level");
  }
  const doc = parsed as Record<string, unknown>;
  if (doc.runtime_config == null) {
    throw new Error("mode_guide.yaml missing runtime_config");
  }
  if (!Array.isArray(doc.rules)) {
    throw new Error("mode_guide.yaml missing rules[]");
  }
  if (!Array.isArray(doc.steps)) {
    throw new Error("mode_guide.yaml missing steps[]");
  }
  const assets = parseAssets(doc.assets);
  const resolvedSteps = doc.steps.map((entry, idx) => {
    if (typeof entry !== "object" || entry == null) {
      throw new Error(`mode_guide.yaml steps[${idx}] must be an object`);
    }
    const step = { ...(entry as Record<string, unknown>) };
    step.title_icon = resolveAssetRef(step.title_icon, assets, `steps[${idx}].title_icon`);
    step.popup_image = resolveAssetRef(step.popup_image, assets, `steps[${idx}].popup_image`);
    step.body_fr = resolveInlineIconRefs(step.body_fr, assets, `steps[${idx}].body_fr`);
    step.body_en = resolveInlineIconRefs(step.body_en, assets, `steps[${idx}].body_en`);
    return step;
  });
  return {
    runtime_config: doc.runtime_config,
    rules: doc.rules,
    steps: resolvedSteps,
  };
}

export function getModeGuideRuntimeData(): TutorialScenarioRuntimeData {
  return buildModeGuideRuntimeData();
}

