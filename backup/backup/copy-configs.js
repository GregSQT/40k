// scripts/copy-configs.js (from project root)

import { copyFileSync, mkdirSync, existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Paths from project root
const projectRoot = join(__dirname, '..');
const configDir = join(projectRoot, 'config');
const targetDir = join(projectRoot, 'frontend', 'public', 'config');

// Config files to copy
const configFiles = [
  'board_config.json',
  'game_config.json',
  'scenario.json',
  'unit_definitions.json',
  'action_definitions.json'
];

console.log('🔧 Copying config files from backend to frontend...');

// Ensure target directory exists
if (!existsSync(targetDir)) {
  mkdirSync(targetDir, { recursive: true });
  console.log(`✅ Created directory: ${targetDir}`);
}

// Copy each config file
let copiedCount = 0;
let skippedCount = 0;

configFiles.forEach(filename => {
  const sourcePath = join(configDir, filename);
  const targetPath = join(targetDir, filename);
  
  if (existsSync(sourcePath)) {
    try {
      copyFileSync(sourcePath, targetPath);
      console.log(`✅ Copied: ${filename}`);
      copiedCount++;
    } catch (error) {
      console.error(`❌ Failed to copy ${filename}:`, error.message);
    }
  } else {
    console.log(`⚠️  Skipped: ${filename} (source not found)`);
    skippedCount++;
  }
});

console.log(`🎯 Config sync complete: ${copiedCount} copied, ${skippedCount} skipped`);
console.log('   Frontend configs are now up-to-date with backend!');