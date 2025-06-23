// export_scenario.mjs
import fs from "fs";
import path from "path";

// ESM dynamic import of Scenario.js
const scenarioModule = await import('./dist/data/Scenario.js');
const scenario = scenarioModule.default;

function stripUnit(unit) {
  return { ...unit };
}

const jsonScenario = scenario.map(stripUnit);

const outPath = path.join(process.cwd(), "ai", "scenario.json");
fs.writeFileSync(outPath, JSON.stringify(jsonScenario, null, 2));
console.log("Scenario exported to", outPath);
