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

  // Copy each config file
  let copiedCount = 0;
  let skippedCount = 0;

  for (const entry of configFiles) {
    const sourcePath = typeof entry === "string"
      ? join(configDir, entry)
      : entry.source === "board_config"
        ? boardConfigSource
        : join(configDir, entry.source);
    const targetPath = join(targetDir, typeof entry === "string" ? entry : entry.target);

    if (existsSync(sourcePath)) {
      try {
        copyFileSync(sourcePath, targetPath);
        console.log(`✅ Copied: ${typeof entry === "string" ? entry : entry.target}`);
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
