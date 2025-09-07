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
##### root files
######################################################################################################


        "AI_IMPLEMENTATION.md",
        "AI_TRAINING.md",
        "AI_TURN.md",
        "config_loader.py",

######################################################################################################
##### ai files
######################################################################################################

    ### ai

######################################################################################################
##### config files
######################################################################################################
        "config/board_config.json",    # Board Layout & Visualization
        "config/config.json",        # Master Configuration & Paths
        "config/game_config.json",   # Game Rules & Mechanics
        "config/rewards_config.json",  # Reward System Definitions
        "config/scenario.json",        # Game Scenarios
        "config/scenario_templates.json",
        "config/training_config.json", # AI Training Parameters
        "config/unit_definitions.json", # Unit Stats & Abilities
        "config/unit_registry.json", # 

######################################################################################################
##### Frontend files
######################################################################################################

    ### frontend
        "frontend/vite.config.ts",
        "frontend/tsconfig.json",

    ### frontend/public/config

        # Frontend/src
        "frontend/src/App.tsx",
        "frontend/src/App.css",
        "frontend/src/main.tsx",
        "frontend/src/Routes.tsx",

        # Frontend/src/components
        "frontend/src/components/BoardDisplay.tsx",
        "frontend/src/components/BoardInteractions.tsx",
        "frontend/src/components/BoardPvp.tsx",
        "frontend/src/components/BoardReplay.tsx",
        "frontend/src/components/CombatLogComponent.tsx",
        "frontend/src/components/DiceRollComponent.tsx",
        "frontend/src/components/ErrorBoundary.tsx",
        "frontend/src/components/GameBoard.tsx",
        "frontend/src/components/GameLog.tsx",
        "frontend/src/components/GameRightColumn.tsx",
        "frontend/src/components/TurnPhaseTracker.tsx",
        "frontend/src/components/UnitStatusTable.tsx",

        # Frontend/src/constants
        "frontend/src/constants/gameConfig.ts",

        # Frontend/src/data
        "frontend/src/data/Scenario.ts",
        "frontend/src/data/Units.ts",
        "frontend/src/data/UnitFactory.ts",
        "frontend/src/data/UnitRegistry.ts",
        

        # Frontend/src/hooks
        "frontend/src/hooks/useGameConfig.ts",
        "frontend/src/hooks/useGameLog.ts",

        # Frontend/src/pages
        "frontend/src/pages/GamePage.tsx",
        "frontend/src/pages/HomePage.tsx",
        "frontend/src/pages/PlayerVsAIPage.tsx",
        "frontend/src/pages/ReplayPage.tsx",


        # Frontend/src/roster/spaceMarine
        "frontend/src/roster/spaceMarine/classes/SpaceMarineInfantryLeaderEliteMeleeElite.ts",
        "frontend/src/roster/spaceMarine/classes/SpaceMarineInfantryTroopMeleeTroop.ts",
        "frontend/src/roster/spaceMarine/classes/SpaceMarineInfantryTroopRangedSwarm.ts",
        "frontend/src/roster/spaceMarine/units/Intercessor.ts",
        "frontend/src/roster/spaceMarine/units/AssaultIntercessor.ts",
        "frontend/src/roster/spaceMarine/units/CaptainGravis.ts",

        # Frontend/src/roster/tyranid
        "frontend/src/roster/tyranid/classes/TyranidInfantryEliteMeleeElite.ts",
        "frontend/src/roster/tyranid/classes/TyranidInfantrySwarmMeleeSwarm.ts",
        "frontend/src/roster/tyranid/classes/TyranidInfantrySwarmRangedSwarm.ts",
        "frontend/src/roster/tyranid/units/Termagant.ts",
        "frontend/src/roster/tyranid/units/Hormagaunt.ts",
        "frontend/src/roster/tyranid/units/Carnifex.ts",
                
        # frontend/src/services

        # frontend/src/types
        "frontend/src/types/api.ts",
        "frontend/src/types/game.ts",
        "frontend/src/types/index.ts",
        "frontend/src/types/replay.ts",

        # frontend/src/utils
        "frontend/src/utils/boardClickHandler.ts",
        "frontend/src/utils/gameHelpers.ts",
        "frontend/src/utils/probabilityCalculator.ts",

######################################################################################################
##### scripts files
######################################################################################################

        "scripts/backup_select.py",  # Backup script
        "scripts/copy-configs.js",

######################################################################################################
##### Shared files
######################################################################################################

        # shared
        "shared/gameLogStructure.ts"

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
        #if filename in ["config.json", "scenario.json", "game_config.json"]:
        #    folder_prefix = os.path.dirname(file_rel).replace("/", "_").replace("\\", "_")
        #    filename = f"{folder_prefix}_{filename}"
        
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