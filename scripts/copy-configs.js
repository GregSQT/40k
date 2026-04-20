// scripts/copy-configs.js (from project root)

import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Paths from project root
const projectRoot = join(__dirname, "..");
const configDir = join(projectRoot, "config");
const targetDir = join(projectRoot, "frontend", "public", "config");

// Config files to copy: string = config/filename, or { source, target } for custom source
const configFiles = [
  { source: "board_config", target: "board_config.json" }, // source from config.json paths.board
  "game_config.json",
  "scenario.json",
  "unit_definitions.json",
  "action_definitions.json",
  "unit_registry.json",
];

async function copyConfigs() {
  console.log("🔧 Copying config files from backend to frontend...");

  // Ensure target directory exists
  if (!existsSync(targetDir)) {
    mkdirSync(targetDir, { recursive: true });
    console.log(`✅ Created directory: ${targetDir}`);
  }

  // Generate unit_registry.json if it doesn't exist
  const unitRegistrySource = join(configDir, "unit_registry.json");
  if (!existsSync(unitRegistrySource)) {
    console.log("🔧 Generating unit_registry.json...");
    const { execSync } = await import("node:child_process");
    execSync("python ai/unit_registry.py", {
      cwd: projectRoot,
      stdio: "inherit",
    });
    console.log("✅ Generated unit_registry.json");
  }

  // Resolve board_config source from config.json paths.board
  let boardConfigSource = join(configDir, "board_config.json");
  try {
    const configJsonPath = join(configDir, "config.json");
    if (existsSync(configJsonPath)) {
      const configJson = JSON.parse(readFileSync(configJsonPath, "utf8"));
      const boardSubdir = configJson?.paths?.board;
      if (boardSubdir) {
        boardConfigSource = join(configDir, boardSubdir, "board_config.json");
      }
    }
  } catch (_) {}

  // Scénario par défaut : pas de ``config/scenario.json`` dans le dépôt → on synchronise depuis
  // ``scenario_pvp.json`` (même contrat JSON) pour éviter le skip permanent au ``npm run dev``.
  const scenarioSourcePath = (() => {
    const canonical = join(configDir, "scenario.json");
    if (existsSync(canonical)) {
      return canonical;
    }
    const fallback = join(configDir, "scenario_pvp.json");
    return existsSync(fallback) ? fallback : null;
  })();

  // Copy each config file
  let copiedCount = 0;
  let skippedCount = 0;

  for (const entry of configFiles) {
    const sourcePath = (() => {
      if (typeof entry === "string") {
        if (entry === "scenario.json") {
          return scenarioSourcePath;
        }
        return join(configDir, entry);
      }
      if (entry.source === "board_config") {
        return boardConfigSource;
      }
      return join(configDir, entry.source);
    })();
    const targetPath = join(targetDir, typeof entry === "string" ? entry : entry.target);

    if (sourcePath && existsSync(sourcePath)) {
      try {
        copyFileSync(sourcePath, targetPath);
        const label = typeof entry === "string" ? entry : entry.target;
        if (typeof entry === "string" && entry === "scenario.json" && scenarioSourcePath?.endsWith("scenario_pvp.json")) {
          console.log(`✅ Copied: ${label} (from scenario_pvp.json — add config/scenario.json to override)`);
        } else {
          console.log(`✅ Copied: ${label}`);
        }
        copiedCount++;
      } catch (error) {
        console.error(`❌ Failed to copy ${typeof entry === "string" ? entry : entry.target}:`, error.message);
      }
    } else {
      console.log(`⚠️  Skipped: ${typeof entry === "string" ? entry : entry.target} (source not found)`);
      skippedCount++;
    }
  }

  console.log(`🎯 Config sync complete: ${copiedCount} copied, ${skippedCount} skipped`);
  console.log("   Frontend configs are now up-to-date with backend!");
}

// Run the async function
copyConfigs().catch((error) => {
  console.error("❌ Config copy failed:", error);
  process.exit(1);
});
