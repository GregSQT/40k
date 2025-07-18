# frontend/save.py
#
import os
import shutil
import datetime
import json

###########################################################################################
### VERSION
###########################################################################################
version = "v2"

# 1. Try to load config.json (if it exists)
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    ROOT = config.get("ROOT")
    DEST_ROOT = config.get("DEST_ROOT")
    files_to_copy = config.get("files_to_copy")
else:
    # 2. Otherwise, use env vars or hardcoded defaults
    ROOT = os.environ.get("PROJECT_ROOT", r"E:\Dropbox\Informatique\Holberton\40k")
    DEST_ROOT = os.environ.get("DEST_ROOT", os.path.join(ROOT, "versions", version))
    files_to_copy = [

######################################################################################################
##### root files
######################################################################################################

        # Root config files
        "config_loader.py",

######################################################################################################
##### ai files
######################################################################################################

    ### ai
        "ai/api.py",
        "ai/diagnose.py",
        "ai/evaluate.py",
        "ai/generate_scenario.py",
        "ai/gym40k.py",
        "ai/reward_mapper.py",
        "ai/scenario.json",
        "ai/state.py",
        "ai/train.py",
        "ai/web_replay_logger.py",

######################################################################################################
##### config files
######################################################################################################
        "config/board_config.json",    # Board Layout & Visualization
        "config/config.json",        # Master Configuration & Paths
        "config/game_config.json",   # Game Rules & Mechanics
        "config/rewards_config.json",  # Reward System Definitions
        "config/scenario.json",        # Game Scenarios
        "config/training_config.json", # AI Training Parameters
        "config/unit_definitions.json", # Unit Stats & Abilities

######################################################################################################
##### Frontend files
######################################################################################################

    ### frontend
        "frontend/package.json",  # Node.js dependencies
        "frontend/tsconfig.json",
        "frontend/vite.config.ts",

    ### frontend/public/config
        "frontend/public/config/action_definitions.json",  # Action Definitions
        "frontend/public/config/board_config.json",  # Board Layout & Visualization
        "frontend/public/config/config.json",  # Frontend Configuration
        "frontend/public/config/game_config.json",  # Game Rules & Mechanics
        "frontend/public/config/rewards_config.json",  # Reward System Definitions
        "frontend/public/config/scenario.json",  # Game Scenarios
        "frontend/public/config/training_config.json",  # AI Training Parameters
        "frontend/public/config/unit_definitions.json",  # Unit Stats & Abilities

    ### frontend/src

        # frontend/src
        "frontend/src/App.tsx",
        "frontend/src/main.tsx",
        "frontend/src/routes.tsx",

        # frontend/src/ai
        "frontend/src/ai/ai.ts",

        # Frontend/src/components
        "frontend/src/components/Board.tsx",
        "frontend/src/components/ErrorBoundary.tsx",
        "frontend/src/components/GameBoard.tsx",
        "frontend/src/components/GameController.tsx",
        "frontend/src/components/GameStatus.tsx",
        "frontend/src/components/ReplayViewer.tsx",
        "frontend/src/components/UnitSelector.tsx",

        # Frontend/src/data
        "frontend/src/data/Units.ts",
        "frontend/src/data/UnitFactory.ts",
        "frontend/src/data/Scenario.ts",

        # Frontend/src/hooks
        "frontend/src/hooks/useAIPlayer.ts",
        "frontend/src/hooks/useGameActions.ts",
        "frontend/src/hooks/useGameConfig.ts",
        "frontend/src/hooks/useGameState.ts",
        "frontend/src/hooks/usePhaseTransition.ts",

        # Frontend/src/pages
        "frontend/src/pages/HomePage.tsx",
        "frontend/src/pages/GamePage.tsx",
        "frontend/src/pages/ReplayPage.tsx",

        # Frontend/src/roster/spaceMarine
        "frontend/src/roster/spaceMarine/SpaceMarineMeleeUnit.ts",
        "frontend/src/roster/spaceMarine/SpaceMarineRangedUnit.ts",
        "frontend/src/roster/spaceMarine/Intercessor.ts",
        "frontend/src/roster/spaceMarine/AssaultIntercessor.ts",

        # Frontend/src/services
        "frontend/src/services/aiService.ts",

######################################################################################################
##### scripts files
######################################################################################################

        # Scripts
        "scripts/backup_script.py",        # Project Versioning & Backup
        "scripts/copy-configs.js"          # Copy Config Files from Backend to Frontend
    ]

logfile = os.path.join(DEST_ROOT, "backup.log")
os.makedirs(DEST_ROOT, exist_ok=True)

ok_count = 0
fail_count = 0
with open(logfile, "a", encoding="utf-8") as log:
    log.write(f"\n---- Backup run: {datetime.datetime.now()} ----\n")
    for file_rel in files_to_copy:
        src = os.path.join(ROOT, file_rel)
        dest = os.path.join(DEST_ROOT, file_rel)
        dest_dir = os.path.dirname(dest)
        if not os.path.exists(src):
            msg = f"ERROR: Source file does not exist: {src}"
            print(msg)
            log.write(msg + "\n")
            fail_count += 1
            continue
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, dest)
        msg = f"Copied {src} -> {dest}"
        print(msg)
        log.write(msg + "\n")
        ok_count += 1

    log.write(f"Backup finished. Success: {ok_count} | Failed: {fail_count}\n")

print(f"Backup complete. Success: {ok_count} | Failed: {fail_count}")
print(f"Log written to: {logfile}")

# Zip the backup folder
zip_path = shutil.make_archive(DEST_ROOT, 'zip', DEST_ROOT)
print(f"Zipped backup folder to: {zip_path}")
with open(logfile, "a", encoding="utf-8") as log:
    log.write(f"Zipped backup folder to: {zip_path}\n")