# WH40K Tactics RL - Repository Structure at Backup Time

## Overview
This document shows the actual repository structure at the time of backup.
Files are saved with clean names (no path prefixes), and their original locations are documented below.

**Backup created:** 2025-07-13T00:11:38.983874
**Source directory:** E:\Dropbox\Informatique\Holberton\40k
**Files backed up:** 66

## 📁 Actual Repository Structure

```
40k/
├── 📂 ai/
│   ├── 📂 Variants/
│   ├── 📂 event_log/
│   │   ├── 📄 phase_based_replay_20250710_024121.json
│   │   ├── 📄 phase_based_replay_20250712_215940.json
│   │   ├── 📄 phase_based_replay_20250712_221527.json
│   │   └── 📄 phase_based_replay_20250712_222556.json
│   ├── 📂 models/
│   │   ├── 📂 backups/
│   │   │   ├── 📄 model_backup_20250629_235150.zip
│   │   │   └── 📄 model_backup_20250630_000026.zip
│   │   ├── 📂 current/
│   │   │   ├── 📄 balanced_model_checkpoint_100000_steps.zip
│   │   │   ├── 📄 balanced_model_checkpoint_10000_steps.zip
│   │   │   ├── 📄 balanced_model_checkpoint_20000_steps.zip
│   │   │   ├── 📄 balanced_model_checkpoint_30000_steps.zip
│   │   │   ├── 📄 balanced_model_checkpoint_40000_steps.zip
│   │   │   ├── 📄 balanced_model_checkpoint_50000_steps.zip
│   │   │   ├── 📄 best_model.zip
│   │   │   ├── 📄 evaluations.npz
│   │   │   ├── 📄 model.zip
│   │   │   └── 📄 model_interrupted.zip
│   │   ├── 📂 logs/
│   │   │   ├── 📄 best_event_log.json
│   │   │   ├── 📄 evaluation_summary.json
│   │   │   └── 📄 worst_event_log.json
│   │   ├── 📄 README.md
│   │   ├── 📄 backup_model.py
│   │   └── 📄 restore_model.py
│   ├── 📄 README.md
│   ├── 📄 __init__.py
│   ├── 📄 agent.py
│   ├── 📄 api.py
│   ├── 📄 convert_replays.py
│   ├── 📄 diagnose.py
│   ├── 📄 env_registration.py
│   ├── 📄 evaluate.py
│   ├── 📄 game_replay_logger.py
│   ├── 📄 generate_scenario.py
│   ├── 📄 gym40k.py
│   ├── 📄 model.py
│   ├── 📄 play.py
│   ├── 📄 reward_mapper.py
│   ├── 📄 rewards_master.json
│   ├── 📄 scenario.json
│   ├── 📄 state.py
│   ├── 📄 test.py
│   ├── 📄 train.py
│   ├── 📄 utils.py
│   └── 📄 web_replay_logger.py
├── 📂 backend/
│   ├── 📂 api/
│   │   └── 📄 main.py
│   ├── 📂 game/
│   │   └── 📄 core.py
│   ├── 📂 rl/
│   │   └── 📄 env_gym.py
│   └── 📄 __init__.py
├── 📂 config/
│   ├── 📄 __init__.py
│   ├── 📄 action_definitions.json
│   ├── 📄 board_config.json
│   ├── 📄 config.json
│   ├── 📄 game_config.json
│   ├── 📄 rewards_config.json
│   ├── 📄 scenario.json
│   ├── 📄 training_config.json
│   └── 📄 unit_definitions.json
├── 📂 docs/
│   ├── 📄 project_structure.md
│   └── 📄 training_config.md
├── 📂 frontend/
│   ├── 📂 public/
│   │   ├── 📂 ai/
│   │   │   ├── 📂 config/
│   │   │   └── 📂 event_log/
│   │   ├── 📂 config/
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 action_definitions.json
│   │   │   ├── 📄 board_config.json
│   │   │   ├── 📄 config.json
│   │   │   ├── 📄 game_config.json
│   │   │   ├── 📄 rewards_config.json
│   │   │   ├── 📄 scenario.json
│   │   │   ├── 📄 training_config.json
│   │   │   └── 📄 unit_definitions.json
│   │   ├── 📂 icons/
│   │   │   ├── 📄 AggressorBoltstorm.webp
│   │   │   ├── 📄 AggressorFlamestorm.webp
│   │   │   ├── 📄 Apothecary.webp
│   │   │   ├── 📄 AssaultIntercessor.png
│   │   │   ├── 📄 AssaultIntercessor.webp
│   │   │   ├── 📄 AssaultIntercessor1.png
│   │   │   ├── 📄 AssaultIntercessor2.png
│   │   │   ├── 📄 Bladeguard.webp
│   │   │   ├── 📄 Captain.webp
│   │   │   ├── 📄 CaptainGravis.webp
│   │   │   ├── 📄 CaptainIndomitus.webp
│   │   │   ├── 📄 CaptainVanguard.webp
│   │   │   ├── 📄 Chaplain.webp
│   │   │   ├── 📄 Eliminator.webp
│   │   │   ├── 📄 EradicatorMelta.webp
│   │   │   ├── 📄 EradicatorMultiMelta.webp
│   │   │   ├── 📄 HeavyIntercessor.webp
│   │   │   ├── 📄 HeavyIntercessorHeavyBolter.webp
│   │   │   ├── 📄 Hellblaster.webp
│   │   │   ├── 📄 InfiltratorBoltCarabin.webp
│   │   │   ├── 📄 Intercessor.png
│   │   │   ├── 📄 Intercessor.webp
│   │   │   ├── 📄 Intercessor1.png
│   │   │   ├── 📄 Intercessor2.webp
│   │   │   ├── 📄 IntercessorBolter.webp
│   │   │   ├── 📄 IntercessorPlasma.webp
│   │   │   ├── 📄 Judicator.webp
│   │   │   ├── 📄 Librarian.webp
│   │   │   ├── 📄 ReiverCarabin.webp
│   │   │   ├── 📄 ReiverCarabinKnife.webp
│   │   │   ├── 📄 Space marine primaris1.png
│   │   │   ├── 📄 Space marine primaris2.png
│   │   │   ├── 📄 Space marines - Pixel art.png
│   │   │   ├── 📄 Suppressor.webp
│   │   │   ├── 📄 Techmarine.webp
│   │   │   └── 📄 Thousand sons 30k.png
│   │   ├── 📄 index.html
│   │   └── 📄 vite.svg
│   ├── 📂 src/
│   │   ├── 📂 ai/
│   │   │   └── 📄 ai.ts
│   │   ├── 📂 assets/
│   │   │   └── 📄 react.svg
│   │   ├── 📂 components/
│   │   │   ├── 📄 Board.tsx
│   │   │   ├── 📄 ErrorBoundary.tsx
│   │   │   ├── 📄 GameBoard.tsx
│   │   │   ├── 📄 GameController.tsx
│   │   │   ├── 📄 GameStatus.tsx
│   │   │   ├── 📄 ReplayBoard.tsx
│   │   │   ├── 📄 ReplayViewer.tsx
│   │   │   └── 📄 UnitSelector.tsx
│   │   ├── 📂 constants/
│   │   │   └── 📄 gameConfig.ts
│   │   ├── 📂 data/
│   │   │   ├── 📄 Scenario.ts
│   │   │   ├── 📄 UnitFactory.ts
│   │   │   └── 📄 Units.ts
│   │   ├── 📂 hooks/
│   │   │   ├── 📄 useAIPlayer.ts
│   │   │   ├── 📄 useGameActions.ts
│   │   │   ├── 📄 useGameConfig.ts
│   │   │   ├── 📄 useGameState.ts
│   │   │   └── 📄 usePhaseTransition.ts
│   │   ├── 📂 pages/
│   │   │   ├── 📄 GamePage.tsx
│   │   │   ├── 📄 HomePage.tsx
│   │   │   └── 📄 ReplayPage.tsx
│   │   ├── 📂 roster/
│   │   │   ├── 📂 spaceMarine/
│   │   │   └── 📄 rewards_master.json
│   │   ├── 📂 services/
│   │   │   └── 📄 aiService.ts
│   │   ├── 📂 types/
│   │   │   ├── 📄 api.ts
│   │   │   ├── 📄 game.ts
│   │   │   ├── 📄 index.ts
│   │   │   └── 📄 replay.ts
│   │   ├── 📂 utils/
│   │   │   └── 📄 gameHelpers.ts
│   │   ├── 📄 App.css
│   │   ├── 📄 App.tsx
│   │   ├── 📄 Routes.tsx
│   │   ├── 📄 index.css
│   │   ├── 📄 index_save.tsx
│   │   ├── 📄 main.tsx
│   │   └── 📄 pixi-test.ts
│   ├── 📄 eslint.config.js
│   ├── 📄 index.html
│   ├── 📄 package-lock.json
│   ├── 📄 package.json
│   ├── 📄 tsconfig.app.json
│   ├── 📄 tsconfig.json
│   ├── 📄 tsconfig.node.json
│   ├── 📄 tsconfig.tsbuildinfo
│   └── 📄 vite.config.ts
├── 📂 public/
│   ├── 📂 ai/
│   │   └── 📂 event_log/
│   │       ├── 📄 eval_summary.json
│   │       ├── 📄 train_best_game_replay.json
│   │       ├── 📄 train_best_web_replay.json
│   │       ├── 📄 train_summary.json
│   │       ├── 📄 train_worst_game_replay.json
│   │       ├── 📄 train_worst_web_replay.json
│   │       └── 📄 web_replay_20250626_204047.json
│   └── 📄 index.html
├── 📂 scripts/
│   ├── 📄 backup_block.py
│   ├── 📄 backup_block_README.md
│   ├── 📄 backup_script.py
│   ├── 📄 backup_tree.py
│   ├── 📄 backup_tree_README.md
│   ├── 📄 copy-configs.js
│   ├── 📄 restore_block.py
│   └── 📄 restore_tree.py
├── 📄 .gitignore
├── 📄 AI_GAME.md
├── 📄 AI_INSTRUCTIONS.md
├── 📄 CONFIG_USAGE.md
├── 📄 config_loader.py
├── 📄 package.json
├── 📄 ps.ps1
├── 📄 py.py
├── 📄 tsconfig.base.json
├── 📄 tsconfig.json
└── 📄 tsconfig.tsbuildinfo
```

## 📋 File Mapping (Backup Filename ← Original Location)

Files are saved with clean names. This table shows where each backup file originally came from:

| Backup Filename | Original Repository Path | Repository |
|-----------------|--------------------------|------------|
| `config_loader.py` | `config_loader.py` | 📂 Project Root |
| `tsconfig.json` | `tsconfig.json` | 📂 Project Root |
| `.gitignore` | `.gitignore` | 📂 Project Root |
| `AI_INSTRUCTIONS.md` | `AI_INSTRUCTIONS.md` | 📂 Project Root |
| `ps.ps1` | `ps.ps1` | 📂 Project Root |
| `api.py` | `ai/api.py` | 🤖 AI Backend |
| `diagnose.py` | `ai/diagnose.py` | 🤖 AI Backend |
| `evaluate.py` | `ai/evaluate.py` | 🤖 AI Backend |
| `generate_scenario.py` | `ai/generate_scenario.py` | 🤖 AI Backend |
| `gym40k.py` | `ai/gym40k.py` | 🤖 AI Backend |
| `reward_mapper.py` | `ai/reward_mapper.py` | 🤖 AI Backend |
| `scenario.json` | `ai/scenario.json` | 🤖 AI Backend |
| `state.py` | `ai/state.py` | 🤖 AI Backend |
| `train.py` | `ai/train.py` | 🤖 AI Backend |
| `web_replay_logger.py` | `ai/web_replay_logger.py` | 🤖 AI Backend |
| `config.json` | `config/config.json` | ⚙️ Configuration |
| `game_config.json` | `config/game_config.json` | ⚙️ Configuration |
| `training_config.json` | `config/training_config.json` | ⚙️ Configuration |
| `rewards_config.json` | `config/rewards_config.json` | ⚙️ Configuration |
| `board_config.json` | `config/board_config.json` | ⚙️ Configuration |
| `scenario_1.json` | `config/scenario.json` | ⚙️ Configuration |
| `unit_definitions.json` | `config/unit_definitions.json` | ⚙️ Configuration |
| `action_definitions.json` | `config/action_definitions.json` | ⚙️ Configuration |
| `backup_script.py` | `scripts/backup_script.py` | 🛠️ Scripts |
| `copy-configs.js` | `scripts/copy-configs.js` | 🛠️ Scripts |
| `package.json` | `frontend/package.json` | 🎮 Frontend Config |
| `tsconfig_1.json` | `frontend/tsconfig.json` | 🎮 Frontend Config |
| `vite.config.ts` | `frontend/vite.config.ts` | 🎮 Frontend Config |
| `eslint.config.js` | `frontend/eslint.config.js` | 🎮 Frontend Config |
| `config_1.json` | `frontend/public/config/config.json` | 📁 Frontend Public |
| `board_config_1.json` | `frontend/public/config/board_config.json` | 📁 Frontend Public |
| `game_config_1.json` | `frontend/public/config/game_config.json` | 📁 Frontend Public |
| `scenario_2.json` | `frontend/public/config/scenario.json` | 📁 Frontend Public |
| `unit_definitions_1.json` | `frontend/public/config/unit_definitions.json` | 📁 Frontend Public |
| `action_definitions_1.json` | `frontend/public/config/action_definitions.json` | 📁 Frontend Public |
| `App.tsx` | `frontend/src/App.tsx` | 🎮 Frontend Core |
| `main.tsx` | `frontend/src/main.tsx` | 🎮 Frontend Core |
| `routes.tsx` | `frontend/src/routes.tsx` | 🎮 Frontend Core |
| `App.css` | `frontend/src/App.css` | 🎮 Frontend Core |
| `index.css` | `frontend/src/index.css` | 🎮 Frontend Core |
| `Board.tsx` | `frontend/src/components/Board.tsx` | 🎮 Frontend Components |
| `ErrorBoundary.tsx` | `frontend/src/components/ErrorBoundary.tsx` | 🎮 Frontend Components |
| `GameBoard.tsx` | `frontend/src/components/GameBoard.tsx` | 🎮 Frontend Components |
| `GameController.tsx` | `frontend/src/components/GameController.tsx` | 🎮 Frontend Components |
| `GameStatus.tsx` | `frontend/src/components/GameStatus.tsx` | 🎮 Frontend Components |
| `ReplayViewer.tsx` | `frontend/src/components/ReplayViewer.tsx` | 🎮 Frontend Components |
| `ReplayBoard.tsx` | `frontend/src/components/ReplayBoard.tsx` | 🎮 Frontend Components |
| `UnitSelector.tsx` | `frontend/src/components/UnitSelector.tsx` | 🎮 Frontend Components |
| `Units.ts` | `frontend/src/data/Units.ts` | 🎮 Frontend Core |
| `UnitFactory.ts` | `frontend/src/data/UnitFactory.ts` | 🎮 Frontend Core |
| `Scenario.ts` | `frontend/src/data/Scenario.ts` | 🎮 Frontend Core |
| `useAIPlayer.ts` | `frontend/src/hooks/useAIPlayer.ts` | 🪝 Frontend Hooks |
| `useGameActions.ts` | `frontend/src/hooks/useGameActions.ts` | 🪝 Frontend Hooks |
| `useGameConfig.ts` | `frontend/src/hooks/useGameConfig.ts` | 🪝 Frontend Hooks |
| `useGameState.ts` | `frontend/src/hooks/useGameState.ts` | 🪝 Frontend Hooks |
| `usePhaseTransition.ts` | `frontend/src/hooks/usePhaseTransition.ts` | 🪝 Frontend Hooks |
| `HomePage.tsx` | `frontend/src/pages/HomePage.tsx` | 📄 Frontend Pages |
| `GamePage.tsx` | `frontend/src/pages/GamePage.tsx` | 📄 Frontend Pages |
| `ReplayPage.tsx` | `frontend/src/pages/ReplayPage.tsx` | 📄 Frontend Pages |
| `SpaceMarineRangedUnit.ts` | `frontend/src/roster/spaceMarine/SpaceMarineRangedUnit.ts` | ⚔️ Unit Roster |
| `SpaceMarineMeleeUnit.ts` | `frontend/src/roster/spaceMarine/SpaceMarineMeleeUnit.ts` | ⚔️ Unit Roster |
| `Intercessor.ts` | `frontend/src/roster/spaceMarine/Intercessor.ts` | ⚔️ Unit Roster |
| `AssaultIntercessor.ts` | `frontend/src/roster/spaceMarine/AssaultIntercessor.ts` | ⚔️ Unit Roster |
| `aiService.ts` | `frontend/src/services/aiService.ts` | 🎮 Frontend Core |
| `game.ts` | `frontend/src/types/game.ts` | 🎮 Frontend Core |
| `gameConfig.ts` | `frontend/src/constants/gameConfig.ts` | 🎮 Frontend Core |

## 🗂️ Repository Sections

### 📂 Project Root

- **`.gitignore`** ← `.gitignore`
- **`AI_INSTRUCTIONS.md`** ← `AI_INSTRUCTIONS.md`
- **`config_loader.py`** ← `config_loader.py`
- **`ps.ps1`** ← `ps.ps1`
- **`tsconfig.json`** ← `tsconfig.json`

### 🤖 AI Backend

- **`api.py`** ← `ai/api.py`
- **`diagnose.py`** ← `ai/diagnose.py`
- **`evaluate.py`** ← `ai/evaluate.py`
- **`generate_scenario.py`** ← `ai/generate_scenario.py`
- **`gym40k.py`** ← `ai/gym40k.py`
- **`reward_mapper.py`** ← `ai/reward_mapper.py`
- **`scenario.json`** ← `ai/scenario.json`
- **`state.py`** ← `ai/state.py`
- **`train.py`** ← `ai/train.py`
- **`web_replay_logger.py`** ← `ai/web_replay_logger.py`

### ⚙️ Configuration

- **`action_definitions.json`** ← `config/action_definitions.json`
- **`board_config.json`** ← `config/board_config.json`
- **`config.json`** ← `config/config.json`
- **`game_config.json`** ← `config/game_config.json`
- **`rewards_config.json`** ← `config/rewards_config.json`
- **`scenario_1.json`** ← `config/scenario.json`
- **`training_config.json`** ← `config/training_config.json`
- **`unit_definitions.json`** ← `config/unit_definitions.json`

### 🛠️ Scripts

- **`backup_script.py`** ← `scripts/backup_script.py`
- **`copy-configs.js`** ← `scripts/copy-configs.js`

### 🎮 Frontend Config

- **`action_definitions_1.json`** ← `frontend/public/config/action_definitions.json`
- **`board_config_1.json`** ← `frontend/public/config/board_config.json`
- **`config_1.json`** ← `frontend/public/config/config.json`
- **`eslint.config.js`** ← `frontend/eslint.config.js`
- **`game_config_1.json`** ← `frontend/public/config/game_config.json`
- **`package.json`** ← `frontend/package.json`
- **`scenario_2.json`** ← `frontend/public/config/scenario.json`
- **`tsconfig_1.json`** ← `frontend/tsconfig.json`
- **`unit_definitions_1.json`** ← `frontend/public/config/unit_definitions.json`
- **`vite.config.ts`** ← `frontend/vite.config.ts`

### 🎮 Frontend Core

- **`App.css`** ← `frontend/src/App.css`
- **`App.tsx`** ← `frontend/src/App.tsx`
- **`Scenario.ts`** ← `frontend/src/data/Scenario.ts`
- **`UnitFactory.ts`** ← `frontend/src/data/UnitFactory.ts`
- **`Units.ts`** ← `frontend/src/data/Units.ts`
- **`aiService.ts`** ← `frontend/src/services/aiService.ts`
- **`game.ts`** ← `frontend/src/types/game.ts`
- **`gameConfig.ts`** ← `frontend/src/constants/gameConfig.ts`
- **`index.css`** ← `frontend/src/index.css`
- **`main.tsx`** ← `frontend/src/main.tsx`
- **`routes.tsx`** ← `frontend/src/routes.tsx`

### 🎮 Frontend Components

- **`Board.tsx`** ← `frontend/src/components/Board.tsx`
- **`ErrorBoundary.tsx`** ← `frontend/src/components/ErrorBoundary.tsx`
- **`GameBoard.tsx`** ← `frontend/src/components/GameBoard.tsx`
- **`GameController.tsx`** ← `frontend/src/components/GameController.tsx`
- **`GameStatus.tsx`** ← `frontend/src/components/GameStatus.tsx`
- **`ReplayBoard.tsx`** ← `frontend/src/components/ReplayBoard.tsx`
- **`ReplayViewer.tsx`** ← `frontend/src/components/ReplayViewer.tsx`
- **`UnitSelector.tsx`** ← `frontend/src/components/UnitSelector.tsx`

### 🪝 Frontend Hooks

- **`useAIPlayer.ts`** ← `frontend/src/hooks/useAIPlayer.ts`
- **`useGameActions.ts`** ← `frontend/src/hooks/useGameActions.ts`
- **`useGameConfig.ts`** ← `frontend/src/hooks/useGameConfig.ts`
- **`useGameState.ts`** ← `frontend/src/hooks/useGameState.ts`
- **`usePhaseTransition.ts`** ← `frontend/src/hooks/usePhaseTransition.ts`

### 📄 Frontend Pages

- **`GamePage.tsx`** ← `frontend/src/pages/GamePage.tsx`
- **`HomePage.tsx`** ← `frontend/src/pages/HomePage.tsx`
- **`ReplayPage.tsx`** ← `frontend/src/pages/ReplayPage.tsx`

### ⚔️ Unit Roster

- **`AssaultIntercessor.ts`** ← `frontend/src/roster/spaceMarine/AssaultIntercessor.ts`
- **`Intercessor.ts`** ← `frontend/src/roster/spaceMarine/Intercessor.ts`
- **`SpaceMarineMeleeUnit.ts`** ← `frontend/src/roster/spaceMarine/SpaceMarineMeleeUnit.ts`
- **`SpaceMarineRangedUnit.ts`** ← `frontend/src/roster/spaceMarine/SpaceMarineRangedUnit.ts`

## 📊 Backup Statistics

- **Total files copied:** 66
- **Total files failed:** 0
- **Total size:** 0.38 MB

## 🔄 Restoration Guide

To restore files to their original locations:

```bash
# Use the restore script
python scripts/restore_block.py backup/backup_TIMESTAMP.zip

# Or manually restore specific files:
# cp config_loader.py config_loader.py
# cp tsconfig.json tsconfig.json
# cp .gitignore .gitignore
# cp AI_INSTRUCTIONS.md AI_INSTRUCTIONS.md
# cp ps.ps1 ps.ps1
```