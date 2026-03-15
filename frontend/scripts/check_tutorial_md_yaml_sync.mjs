import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");

const mdPath = path.join(repoRoot, "config", "tutorial", "tutorial_scenario.md");
const yamlPath = path.join(repoRoot, "config", "tutorial", "tutorial_scenario.yaml");

function parseMdStages(markdown) {
  const stageRegex = /^### Stage `([^`]+)`\s*$/gm;
  const stages = [];
  let match = stageRegex.exec(markdown);
  while (match != null) {
    const stage = match[1]?.trim();
    if (stage != null && stage !== "") {
      stages.push(stage);
    }
    match = stageRegex.exec(markdown);
  }
  return stages;
}

function unique(values) {
  return [...new Set(values)];
}

function main() {
  const markdown = fs.readFileSync(mdPath, "utf8");
  const doc = yaml.load(fs.readFileSync(yamlPath, "utf8"));
  if (typeof doc !== "object" || doc == null) {
    throw new Error("tutorial_scenario.yaml must be an object");
  }
  const steps = doc.steps;
  if (!Array.isArray(steps)) {
    throw new Error("tutorial_scenario.yaml must contain steps[]");
  }

  const mdStages = unique(parseMdStages(markdown));
  const yamlStages = unique(
    steps
      .map((s) => (typeof s === "object" && s != null ? s.stage : undefined))
      .filter((stage) => typeof stage === "string" && stage.trim() !== "")
      .map((stage) => stage.trim())
  );

  const missingInYaml = mdStages.filter((s) => !yamlStages.includes(s));
  const extraInYaml = yamlStages.filter((s) => !mdStages.includes(s));

  if (missingInYaml.length > 0 || extraInYaml.length > 0) {
    // eslint-disable-next-line no-console
    console.error("tutorial md/yaml sync mismatch detected.");
    if (missingInYaml.length > 0) {
      // eslint-disable-next-line no-console
      console.error(`Stages in MD but missing in YAML (${missingInYaml.length}): ${missingInYaml.join(", ")}`);
    }
    if (extraInYaml.length > 0) {
      // eslint-disable-next-line no-console
      console.error(`Stages in YAML but missing in MD (${extraInYaml.length}): ${extraInYaml.join(", ")}`);
    }
    process.exit(1);
  }

  // eslint-disable-next-line no-console
  console.log(`tutorial md/yaml sync OK (${mdStages.length} stages).`);
}

main();
