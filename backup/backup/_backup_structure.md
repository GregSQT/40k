# WH40K Tactics RL - Repository Tree Snapshot

**Snapshot taken:** 2025-07-13 00:11:39
**Source directory:** E:\Dropbox\Informatique\Holberton\40k

This file contains a complete snapshot of the repository structure at backup time.

## 📁 Complete Repository Tree

```
40k/
├── 📂 ai/
│   ├── 📂 Variants/
│   ├── 📂 event_log/
│   │   ├── 📄 phase_based_replay_20250710_024121.json (6.3KB)
│   │   ├── 📄 phase_based_replay_20250712_215940.json (62.6KB)
│   │   ├── 📄 phase_based_replay_20250712_221527.json (3.8KB)
│   │   └── 📄 phase_based_replay_20250712_222556.json (14.4KB)
│   ├── 📂 models/
│   │   ├── 📂 backup/ (generated/ignored)
│   │   ├── 📂 backups/
│   │   │   ├── 📄 model_backup_20250629_235150.zip (129.7KB)
│   │   │   └── 📄 model_backup_20250630_000026.zip (129.7KB)
│   │   ├── 📂 current/
│   │   │   ├── 📄 balanced_model_checkpoint_100000_steps.zip (136.0KB)
│   │   │   ├── 📄 balanced_model_checkpoint_10000_steps.zip (136.1KB)
│   │   │   ├── 📄 balanced_model_checkpoint_20000_steps.zip (136.1KB)
│   │   │   ├── 📄 balanced_model_checkpoint_30000_steps.zip (136.1KB)
│   │   │   ├── 📄 balanced_model_checkpoint_40000_steps.zip (136.1KB)
│   │   │   ├── 📄 balanced_model_checkpoint_50000_steps.zip (136.1KB)
│   │   │   ├── 📄 best_model.zip (136.1KB)
│   │   │   ├── 📄 evaluations.npz (1.4KB)
│   │   │   ├── 📄 model.zip (136.1KB)
│   │   │   └── 📄 model_interrupted.zip (135.3KB)
│   │   ├── 📂 logs/
│   │   │   ├── 📄 best_event_log.json (1.1KB)
│   │   │   ├── 📄 evaluation_summary.json
│   │   │   └── 📄 worst_event_log.json (1.1KB)
│   │   ├── 📄 README.md (1.7KB)
│   │   ├── 📄 backup_model.py (1.2KB)
│   │   └── 📄 restore_model.py (2.2KB)
│   ├── 📂 tensorboard/ (generated/ignored)
│   ├── 📄 README.md
│   ├── 📄 __init__.py
│   ├── 📄 agent.py (5.8KB)
│   ├── 📄 api.py (2.1KB)
│   ├── 📄 convert_replays.py (15.4KB)
│   ├── 📄 diagnose.py (1.6KB)
│   ├── 📄 env_registration.py
│   ├── 📄 evaluate.py (13.2KB)
│   ├── 📄 game_replay_logger.py (18.0KB)
│   ├── 📄 generate_scenario.py (8.0KB)
│   ├── 📄 gym40k.py (80.9KB)
│   ├── 📄 model.py
│   ├── 📄 play.py (2.1KB)
│   ├── 📄 reward_mapper.py (12.4KB)
│   ├── 📄 rewards_master.json (1.3KB)
│   ├── 📄 scenario.json
│   ├── 📄 state.py
│   ├── 📄 test.py (2.1KB)
│   ├── 📄 train.py (14.3KB)
│   ├── 📄 utils.py
│   └── 📄 web_replay_logger.py (12.0KB)
├── 📂 backend/
│   ├── 📂 api/
│   │   └── 📄 main.py
│   ├── 📂 game/
│   │   └── 📄 core.py
│   ├── 📂 rl/
│   │   └── 📄 env_gym.py
│   └── 📄 __init__.py
├── 📂 backup/ (generated/ignored)
├── 📂 config/
│   ├── 📄 __init__.py
│   ├── 📄 action_definitions.json
│   ├── 📄 board_config.json (3.2KB)
│   ├── 📄 config.json
│   ├── 📄 game_config.json
│   ├── 📄 rewards_config.json (3.0KB)
│   ├── 📄 scenario.json
│   ├── 📄 training_config.json (7.9KB)
│   └── 📄 unit_definitions.json
├── 📂 docs/
│   ├── 📄 project_structure.md (12.5KB)
│   └── 📄 training_config.md (4.3KB)
├── 📂 frontend/
│   ├── 📂 node_modules/ (generated/ignored)
│   ├── 📂 public/
│   │   ├── 📂 ai/
│   │   │   ├── 📂 config/
│   │   │   │   └── 📄 unit_definitions.json (1.8KB)
│   │   │   └── 📂 event_log/
│   │   │       ├── 📄 train_best_game_replay.json (3.7KB)
│   │   │       └── 📄 train_worst_game_replay.json (2.3KB)
│   │   ├── 📂 config/
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 action_definitions.json
│   │   │   ├── 📄 board_config.json (3.2KB)
│   │   │   ├── 📄 config.json
│   │   │   ├── 📄 game_config.json
│   │   │   ├── 📄 rewards_config.json (3.0KB)
│   │   │   ├── 📄 scenario.json
│   │   │   ├── 📄 training_config.json (7.9KB)
│   │   │   └── 📄 unit_definitions.json
│   │   ├── 📂 icons/
│   │   │   ├── 📄 AggressorBoltstorm.webp (7.8KB)
│   │   │   ├── 📄 AggressorFlamestorm.webp (7.8KB)
│   │   │   ├── 📄 Apothecary.webp (8.2KB)
│   │   │   ├── 📄 AssaultIntercessor.png (2.0KB)
│   │   │   ├── 📄 AssaultIntercessor.webp (6.8KB)
│   │   │   ├── 📄 AssaultIntercessor1.png (2.1KB)
│   │   │   ├── 📄 AssaultIntercessor2.png (1.3KB)
│   │   │   ├── 📄 Bladeguard.webp (8.4KB)
│   │   │   ├── 📄 Captain.webp (8.4KB)
│   │   │   ├── 📄 CaptainGravis.webp (9.1KB)
│   │   │   ├── 📄 CaptainIndomitus.webp (9.2KB)
│   │   │   ├── 📄 CaptainVanguard.webp (8.3KB)
│   │   │   ├── 📄 Chaplain.webp (7.7KB)
│   │   │   ├── 📄 Eliminator.webp (6.3KB)
│   │   │   ├── 📄 EradicatorMelta.webp (6.9KB)
│   │   │   ├── 📄 EradicatorMultiMelta.webp (7.6KB)
│   │   │   ├── 📄 HeavyIntercessor.webp (6.6KB)
│   │   │   ├── 📄 HeavyIntercessorHeavyBolter.webp (7.4KB)
│   │   │   ├── 📄 Hellblaster.webp (6.1KB)
│   │   │   ├── 📄 InfiltratorBoltCarabin.webp (6.0KB)
│   │   │   ├── 📄 Intercessor.png (1.7KB)
│   │   │   ├── 📄 Intercessor.webp (5.9KB)
│   │   │   ├── 📄 Intercessor1.png
│   │   │   ├── 📄 Intercessor2.webp (8.0KB)
│   │   │   ├── 📄 IntercessorBolter.webp (8.8KB)
│   │   │   ├── 📄 IntercessorPlasma.webp (9.2KB)
│   │   │   ├── 📄 Judicator.webp (6.9KB)
│   │   │   ├── 📄 Librarian.webp (7.7KB)
│   │   │   ├── 📄 ReiverCarabin.webp (6.0KB)
│   │   │   ├── 📄 ReiverCarabinKnife.webp (6.8KB)
│   │   │   ├── 📄 Space marine primaris1.png (660.3KB)
│   │   │   ├── 📄 Space marine primaris2.png (242.1KB)
│   │   │   ├── 📄 Space marines - Pixel art.png (1.7KB)
│   │   │   ├── 📄 Suppressor.webp (7.7KB)
│   │   │   ├── 📄 Techmarine.webp (8.8KB)
│   │   │   └── 📄 Thousand sons 30k.png (110.1KB)
│   │   ├── 📄 index.html
│   │   └── 📄 vite.svg (1.5KB)
│   ├── 📂 src/
│   │   ├── 📂 ai/
│   │   │   └── 📄 ai.ts
│   │   ├── 📂 assets/
│   │   │   └── 📄 react.svg (4.0KB)
│   │   ├── 📂 components/
│   │   │   ├── 📄 Board.tsx (35.8KB)
│   │   │   ├── 📄 ErrorBoundary.tsx (2.3KB)
│   │   │   ├── 📄 GameBoard.tsx (3.0KB)
│   │   │   ├── 📄 GameController.tsx (3.8KB)
│   │   │   ├── 📄 GameStatus.tsx (3.4KB)
│   │   │   ├── 📄 ReplayBoard.tsx (23.1KB)
│   │   │   ├── 📄 ReplayViewer.tsx (35.1KB)
│   │   │   └── 📄 UnitSelector.tsx (7.5KB)
│   │   ├── 📂 constants/
│   │   │   └── 📄 gameConfig.ts (5.2KB)
│   │   ├── 📂 data/
│   │   │   ├── 📄 Scenario.ts (1.2KB)
│   │   │   ├── 📄 UnitFactory.ts (1.6KB)
│   │   │   └── 📄 Units.ts
│   │   ├── 📂 hooks/
│   │   │   ├── 📄 useAIPlayer.ts (9.9KB)
│   │   │   ├── 📄 useGameActions.ts (9.3KB)
│   │   │   ├── 📄 useGameConfig.ts (4.8KB)
│   │   │   ├── 📄 useGameState.ts (4.1KB)
│   │   │   └── 📄 usePhaseTransition.ts (6.5KB)
│   │   ├── 📂 pages/
│   │   │   ├── 📄 GamePage.tsx
│   │   │   ├── 📄 HomePage.tsx
│   │   │   └── 📄 ReplayPage.tsx (3.6KB)
│   │   ├── 📂 roster/
│   │   │   ├── 📂 spaceMarine/
│   │   │   │   ├── 📄 AssaultIntercessor.ts (1.3KB)
│   │   │   │   ├── 📄 Intercessor.ts (1.3KB)
│   │   │   │   ├── 📄 SpaceMarineMeleeUnit.ts (3.0KB)
│   │   │   │   └── 📄 SpaceMarineRangedUnit.ts (3.0KB)
│   │   │   └── 📄 rewards_master.json (1.3KB)
│   │   ├── 📂 services/
│   │   │   └── 📄 aiService.ts (3.0KB)
│   │   ├── 📂 types/
│   │   │   ├── 📄 api.ts
│   │   │   ├── 📄 game.ts (2.1KB)
│   │   │   ├── 📄 index.ts
│   │   │   └── 📄 replay.ts (2.3KB)
│   │   ├── 📂 utils/
│   │   │   └── 📄 gameHelpers.ts (6.3KB)
│   │   ├── 📄 App.css (9.1KB)
│   │   ├── 📄 App.tsx
│   │   ├── 📄 Routes.tsx
│   │   ├── 📄 index.css
│   │   ├── 📄 index_save.tsx
│   │   ├── 📄 main.tsx
│   │   └── 📄 pixi-test.ts
│   ├── 📄 eslint.config.js
│   ├── 📄 index.html
│   ├── 📄 package-lock.json (160.3KB)
│   ├── 📄 package.json
│   ├── 📄 tsconfig.app.json
│   ├── 📄 tsconfig.json
│   ├── 📄 tsconfig.node.json
│   ├── 📄 tsconfig.tsbuildinfo (98.9KB)
│   └── 📄 vite.config.ts (2.9KB)
├── 📂 public/
│   ├── 📂 ai/
│   │   └── 📂 event_log/
│   │       ├── 📄 eval_summary.json
│   │       ├── 📄 train_best_game_replay.json (9.8KB)
│   │       ├── 📄 train_best_web_replay.json (508.5KB)
│   │       ├── 📄 train_summary.json
│   │       ├── 📄 train_worst_game_replay.json (6.7KB)
│   │       ├── 📄 train_worst_web_replay.json (508.5KB)
│   │       └── 📄 web_replay_20250626_204047.json (508.5KB)
│   └── 📄 index.html
├── 📂 scripts/
│   ├── 📄 backup_block.py (27.3KB)
│   ├── 📄 backup_block_README.md (16.5KB)
│   ├── 📄 backup_script.py (6.6KB)
│   ├── 📄 backup_tree.py (12.6KB)
│   ├── 📄 backup_tree_README.md (11.5KB)
│   ├── 📄 copy-configs.js (1.6KB)
│   ├── 📄 restore_block.py (20.9KB)
│   └── 📄 restore_tree.py (13.9KB)
├── 📂 tensorboard/ (generated/ignored)
├── 📂 versions/ (generated/ignored)
├── 📄 .gitignore (8.4KB)
├── 📄 AI_GAME.md (9.6KB)
├── 📄 AI_INSTRUCTIONS.md (4.3KB)
├── 📄 CONFIG_USAGE.md (2.3KB)
├── 📄 config_loader.py (10.7KB)
├── 📄 package.json
├── 📄 ps.ps1 (2.5KB)
├── 📄 py.py
├── 📄 tsconfig.base.json
├── 📄 tsconfig.json
└── 📄 tsconfig.tsbuildinfo (154.2KB)
```

## 📖 Legend

- 📂 **Directory**
- 📄 **File** (with size if > 1KB)
- **(generated/ignored)** - Directories typically not included in backups

## 📊 Repository Statistics

- **Total directories:** 155
- **Total files:** 618
- **Total size:** 13.6 MB

---

*Generated on 2025-07-13 00:11:39 by backup_block.py*