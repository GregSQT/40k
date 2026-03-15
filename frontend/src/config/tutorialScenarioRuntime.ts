import { load } from "js-yaml";
import tutorialScenarioYamlRaw from "../../../config/tutorial/tutorial_scenario.yaml?raw";

interface TutorialScenarioRuntimeData {
  runtime_config: unknown;
  rules: unknown;
  steps: unknown;
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

  return {
    runtime_config: doc.runtime_config,
    rules: doc.rules,
    steps: doc.steps,
  };
}

const RUNTIME_DATA = buildRuntimeData();

export function getTutorialScenarioRuntimeData(): TutorialScenarioRuntimeData {
  return RUNTIME_DATA;
}

