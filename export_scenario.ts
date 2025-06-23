// export_scenario.ts

import fs from "fs";
import path from "path";

(async () => {
  try {
    const scenarioPath = "file://" + path.resolve("frontend/src/data/Scenario.ts");
    console.log("Trying to import:", scenarioPath);

    const unitsModule = await import(scenarioPath);
    if (!unitsModule || !unitsModule.default) {
      throw new Error("Dynamic import returned no module or no default export!");
    }
    const units = unitsModule.default;

    function stripUnit(unit: any) {
      return { ...unit };
    }
    const jsonScenario = units.map(stripUnit);

    const outPath = path.join(process.cwd(), "ai", "scenario.json");
    fs.writeFileSync(outPath, JSON.stringify(jsonScenario, null, 2));
    console.log("Scenario exported to", outPath);
  } catch (e) {
    console.error("ERROR in export_scenario.ts:", e);
    process.exit(1);
  }
})();
