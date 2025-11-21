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

        "config_loader.py",
        "main.py",
        "train_step.log",

######################################################################################################
##### ai files
######################################################################################################
    
    ### ai/
        "ai/evaluation_bots.py",
        "ai/game_replay_logger.py",
        "ai/metrics_tracker.py",
        "ai/multi_agent_trainer.py",
        "ai/scenario_manager.py",
        "ai/target_selection_monitor.py",
        "ai/train.py",
        "ai/unit_registry.py",
        "ai/reward_mapper.py",

    ### ai/training
        "ai/training/evaluator.py",
        "ai/training/gym_interface.py",
        "ai/training/orchestrator.py",
        "ai/training/train_w40k.py",

######################################################################################################
##### check files
######################################################################################################

        "check/analyze_step_log.py",
        
######################################################################################################
##### config files
######################################################################################################
        "config/board_config.json",    # Board Layout & Visualization
        #"config/config.json",        # Master Configuration & Paths
        "config/game_config.json",   # Game Rules & Mechanics
        #"config/scenario.json",        # Game Scenarios
        "config/unit_definitions.json", # Unit Stats & Abilities
        "config/unit_registry.json", # Unit Registry
        
    ### agents : 
        # SpaceMarine_Infantry_Troop_RangedSwarm
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-bot1.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-bot2.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-bot3.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-bot4.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-self1.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase2-1.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase2-2.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase2-3.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase2-4.json",
        "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase3-1.json",
        # SpaceMarine_Infantry_LeaderElite_MeleeElite
        "config/agents/SpaceMarine_Infantry_LeaderElite_MeleeElite/SpaceMarine_Infantry_LeaderElite_MeleeElite_rewards_config.json",
        "config/agents/SpaceMarine_Infantry_LeaderElite_MeleeElite/SpaceMarine_Infantry_LeaderElite_MeleeElite_training_config.json",
        # SpaceMarine_Infantry_Troop_MeleeTroop
        "config/agents/SpaceMarine_Infantry_Troop_MeleeTroop/SpaceMarine_Infantry_Troop_MeleeTroop_rewards_config.json",
        "config/agents/SpaceMarine_Infantry_Troop_MeleeTroop/SpaceMarine_Infantry_Troop_MeleeTroop_training_config.json",
        # Tyranid_Infantry_Elite_MeleeElite
        "config/agents/Tyranid_Infantry_Elite_MeleeElite/Tyranid_Infantry_Elite_MeleeElite_rewards_config.json",
        "config/agents/Tyranid_Infantry_Elite_MeleeElite/Tyranid_Infantry_Elite_MeleeElite_training_config.json",
        # Tyranid_Infantry_Swarm_MeleeSwarm
        "config/agents/Tyranid_Infantry_Swarm_MeleeSwarm/Tyranid_Infantry_Swarm_MeleeSwarm_rewards_config.json",
        "config/agents/Tyranid_Infantry_Swarm_MeleeSwarm/Tyranid_Infantry_Swarm_MeleeSwarm_training_config.json",
        # Tyranid_Infantry_Swarm_RangedSwarm
        "config/agents/Tyranid_Infantry_Swarm_RangedSwarm/Tyranid_Infantry_Swarm_RangedSwarm_rewards_config.json",
        "config/agents/Tyranid_Infantry_Swarm_RangedSwarm/Tyranid_Infantry_Swarm_RangedSwarm_training_config.json",
        
    ### Units
        #"config/units/space_marines.json", # Unit Definitions
        #"config/units/tyranids.json", # Unit Definitions   
        
        # config/roster/spaceMarine
        #"config/roster/spaceMarine/classes/SpaceMarineInfantryLeaderEliteMeleeElite.ts",
        #"config/roster/spaceMarine/classes/SpaceMarineInfantryTroopMeleeTroop.ts",
        #"config/roster/spaceMarine/classes/SpaceMarineInfantryTroopRangedSwarm.ts",
        #"config/roster/spaceMarine/units/Intercessor.ts",
        #"config/roster/spaceMarine/units/AssaultIntercessor.ts",
        #"config/roster/spaceMarine/units/CaptainGravis.ts",

        # config/roster/tyranid
        #"config/roster/tyranid/classes/TyranidInfantryEliteMeleeElite.ts",
        #"config/roster/tyranid/classes/TyranidInfantrySwarmMeleeSwarm.ts",
        #"config/roster/tyranid/classes/TyranidInfantrySwarmRangedSwarm.ts",
        #"config/roster/tyranid/units/Termagant.ts",
        #"config/roster/tyranid/units/Hormagaunt.ts",
        #"config/roster/tyranid/units/Carnifex.ts",
        
        
######################################################################################################
##### Documentation files
######################################################################################################
    
    ### Documentation    
        "Documentation/AI_IMPLEMENTATION.md",
        "Documentation/AI_METRICS.md",
        "Documentation/AI_OBSERVATION.md",
        "Documentation/AI_TARGET_SELECTION.md",
        "Documentation/AI_TRAINING.md",
        "Documentation/AI_TURN.md",

######################################################################################################
##### Engine files
######################################################################################################
        "engine/__init__.py",
        #"engine/w40k_engine_old.py", # Old engine file for reference
    
    ### Engine
        "engine/w40k_core.py",
        "engine/action_decoder.py",
        "engine/combat_utils.py",
        "engine/game_state.py",
        "engine/game_utils.py",
        "engine/observation_builder.py",
        "engine/pve_controller.py",
        "engine/reward_calculator.py",
        
    ### Phase Handlers
        "engine/phase_handlers/__init__.py",
        "engine/phase_handlers/generic_handlers.py",
        "engine/phase_handlers/movement_handlers.py",
        "engine/phase_handlers/shooting_handlers.py",
        "engine/phase_handlers/charge_handlers.py",
        "engine/phase_handlers/fight_handlers.py",

######################################################################################################
##### Frontend files
######################################################################################################

    ### frontend
        "frontend/tsconfig.json",
        "frontend/vite.config.ts",        

    ### frontend/public/config

        # Frontend/src
        "frontend/src/App.css",
        "frontend/src/App.tsx",        
        "frontend/src/main.tsx",
        "frontend/src/Routes.tsx",
        
     ### frontend/src/components

        "frontend/src/components/BoardDisplay.tsx",
        #"frontend/src/components/BoardInteractions.tsx",
        "frontend/src/components/BoardPvp.tsx",
        #"frontend/src/components/BoardReplay.tsx",
        "frontend/src/components/BoardWithAPI.tsx",
        #"frontend/src/components/CombatLogComponent.tsx",
        #"frontend/src/components/DiceRollComponent.tsx",
        "frontend/src/components/ErrorBoundary.tsx",
        "frontend/src/components/GameBoard.tsx",
        "frontend/src/components/GameLog.tsx",
        "frontend/src/components/GameController.tsx",
        "frontend/src/components/GamePageLayout.tsx",
        "frontend/src/components/GameStatus.tsx",
        #"frontend/src/components/GameRightColumn.tsx",
        "frontend/src/components/SharedLayout.tsx",
        "frontend/src/components/TurnPhaseTracker.tsx",
        "frontend/src/components/UnitRenderer.tsx",
        "frontend/src/components/UnitStatusTable.tsx",

        # Frontend/src/constants
        "frontend/src/constants/gameConfig.ts",

        # Frontend/src/data
        #"frontend/src/data/Scenario.ts",
        #"frontend/src/data/Units.ts",
        "frontend/src/data/UnitFactory.ts",
        #"frontend/src/data/UnitRegistry.ts",
        

        # Frontend/src/hooks
        
        #"frontend/src/hooks/useAITurn.ts",
        "frontend/src/hooks/useEngineAPI.ts",
        "frontend/src/hooks/useGameActions.ts",
        "frontend/src/hooks/useGameConfig.ts",
        "frontend/src/hooks/useGameLog.ts",
        "frontend/src/hooks/useGameState.ts",
        "frontend/src/hooks/usePhaseTransition.ts",

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
        "frontend/src/roster/tyranid/classes/TyranidInfantryTroopMeleeTroop.ts",
        "frontend/src/roster/tyranid/units/Termagant.ts",
        "frontend/src/roster/tyranid/units/Hormagaunt.ts",
        "frontend/src/roster/tyranid/units/Carnifex.ts",
        "frontend/src/roster/tyranid/units/Genestealer.ts",
                
        # frontend/src/services
        "frontend/src/services/aiService.ts",

        # frontend/src/types
        "frontend/src/types/api.ts",
        "frontend/src/types/game.ts",
        "frontend/src/types/index.ts",
        #"frontend/src/types/replay.ts",

        # frontend/src/utils
        "frontend/src/utils/boardClickHandler.ts",
        "frontend/src/utils/gameHelpers.ts",
        #"frontend/src/utils/probabilityCalculator.ts",

######################################################################################################
##### services files
######################################################################################################

        "services/api_server.py",

######################################################################################################
##### scripts files
######################################################################################################

        "scripts/backup_select.py",  # Backup script
        "scripts/copy-configs.js",

######################################################################################################
##### Shared files
######################################################################################################

        # shared
        "shared/gameLogStructure.py",
        "shared/gameLogStructure.ts",
        "shared/gameLogUtils.py",
        "shared/gameLogUtils.ts"

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