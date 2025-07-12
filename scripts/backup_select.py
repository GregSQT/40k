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
    DEST_ROOT = os.environ.get("DEST_ROOT", os.path.join(ROOT, "Backup_Select"))
    files_to_copy = [

######################################################################################################
##### ai files
######################################################################################################

    ### ai
        "ai/evaluate.py",
        "ai/gym40k.py",
        "ai/scenario.json",
        "ai/train.py",

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

        # Frontend/src/components
        "frontend/src/components/Board.tsx",
        "frontend/src/components/GameBoard.tsx",
        "frontend/src/components/ReplayViewer.tsx",
        "frontend/src/components/UnitSelector.tsx",

        # Frontend/src/data
        "frontend/src/data/Units.ts",
        "frontend/src/data/UnitFactory.ts",
        "frontend/src/data/Scenario.ts",

        # Frontend/src/hooks
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
        "frontend/src/roster/spaceMarine/AssaultIntercessor.ts"
    ]

logfile = os.path.join(DEST_ROOT, "backup.log")
os.makedirs(DEST_ROOT, exist_ok=True)

ok_count = 0
fail_count = 0
with open(logfile, "a", encoding="utf-8") as log:
    log.write(f"\n---- Backup run: {datetime.datetime.now()} ----\n")
    for file_rel in files_to_copy:
        src = os.path.join(ROOT, file_rel)
        filename = os.path.basename(file_rel)
        
        # Handle duplicate filenames by prefixing with folder name
        if filename in ["config.json", "scenario.json", "game_config.json"]:
            folder_prefix = os.path.dirname(file_rel).replace("/", "_").replace("\\", "_")
            filename = f"{folder_prefix}_{filename}"
        
        dest = os.path.join(DEST_ROOT, filename)
        if not os.path.exists(src):
            msg = f"ERROR: Source file does not exist: {src}"
            print(msg)
            log.write(msg + "\n")
            fail_count += 1
            continue
        # No need to create subdirectories - saving to root only
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