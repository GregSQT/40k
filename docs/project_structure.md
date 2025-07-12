# WH40K Tactics RL - Project Structure Documentation

## Overview
A sophisticated Warhammer 40k tactical game with AI opponents, featuring a React/TypeScript frontend, Python AI backend, and comprehensive configuration system.

## 📁 Root Directory Structure

```
wh40k-tactics/
├── 📂 frontend/                    # React/TypeScript Frontend Application
├── 📂 ai/                          # Python AI Backend & Training
├── 📂 config/                      # Configuration Files (JSON)
├── 📂 scripts/                     # Development & Utility Scripts
├── 📂 docs/                        # Project Documentation
├── 📂 tensorboard/                 # Training Metrics (Git Ignored)
├── 📂 versions/                    # Backup Versions (Git Ignored)
├── 📄 config_loader.py             # Central Configuration Management
├── 📄 tsconfig.json                # TypeScript Root Configuration
├── 📄 ps.ps1                       # PowerShell Utility Scripts
├── 📄 .gitignore                   # Git Ignore Rules
└── 📄 AI_INSTRUCTIONS.md           # AI Development Guidelines
```

## 🎮 Frontend (`/frontend/`)

### Core Structure
```
frontend/
├── 📂 src/                         # TypeScript Source Code
│   ├── 📂 components/              # Reusable React Components
│   │   ├── 📄 Board.tsx            # Game Board Rendering (PIXI.js)
│   │   ├── 📄 UnitSelector.tsx     # Unit Selection Interface
│   │   ├── 📄 ReplayViewer.tsx     # Game Replay Viewer
│   │   ├── 📄 SimpleReplayViewer.tsx # Simplified Replay Component
│   │   └── 📄 LoadReplayButton.tsx # Replay Loading Interface
│   │
│   ├── 📂 pages/                   # Main Application Pages
│   │   ├── 📄 HomePage.tsx         # Landing Page
│   │   ├── 📄 GamePage.tsx         # Live Game Interface
│   │   └── 📄 ReplayPage.tsx       # Replay Analysis Page
│   │
│   ├── 📂 data/                    # Game Logic & Data Management
│   │   ├── 📄 Units.ts             # Unit Type Definitions
│   │   ├── 📄 UnitFactory.ts       # Unit Creation Logic
│   │   └── 📄 Scenario.ts          # Game Scenario Management
│   │
│   ├── 📂 roster/spaceMarine/      # Unit Definitions & Stats
│   │   ├── 📄 SpaceMarineRangedUnit.ts    # Base Ranged Unit
│   │   ├── 📄 SpaceMarineMeleeUnit.ts     # Base Melee Unit
│   │   ├── 📄 Intercessor.ts              # Ranged Infantry
│   │   └── 📄 AssaultIntercessor.ts       # Melee Infantry
│   │
│   ├── 📂 hooks/                    # React Custom Hooks
│   │   ├── 📄 useAIPlayer.ts        # AI Player Behavior & Actions
│   │   ├── 📄 useGameActions.ts     # Game Action Handlers (Move/Attack/Charge)
│   │   ├── 📄 useGameConfig.ts      # Configuration Loading (Board/Game Rules)
│   │   ├── 📄 useGameState.ts       # Core Game State Management
│   │   └── 📄 usePhaseTransition.ts # Automatic Phase Transitions
│   │
│   ├── 📂 services/                # Service Layer
│   │   └── 📄 aiService.ts         # AI Backend Communication
│   │
│   ├── 📂 types/                   # TypeScript Type Definitions
│   ├── 📂 utils/                   # Utility Functions
│   ├── 📂 constants/               # Application Constants
│   │
│   ├── 📄 App.tsx                  # Main Application Component
│   ├── 📄 main.tsx                 # Application Entry Point
│   └── 📄 routes.tsx               # Application Routing
│
├── 📂 public/                      # Static Assets & Public Config
│   ├── 📂 ai/config/               # AI Config Access (copied from /config/)
│   └── 📂 ai/event_log/            # Replay Files (copied from /ai/event_log/)
│
├── 📂 dist/                        # Build Output (Git Ignored)
├── 📄 package.json                 # Node.js Dependencies
├── 📄 tsconfig.json                # TypeScript Configuration
└── 📄 vite.config.ts               # Vite Build Configuration
```

### Key Features
- **PIXI.js Canvas Rendering**: High-performance hexagonal board visualization
- **Replay System**: Sophisticated game replay analysis with step-by-step navigation
- **TypeScript Strict Mode**: Full type safety and error prevention
- **Modular Architecture**: Clean separation of concerns with reusable components

## 🤖 AI Backend (`/ai/`)

### Core Structure
```
ai/
├── 📄 gym40k.py                    # Gymnasium Environment (Main)
├── 📄 train.py                     # Training Script (Main)
├── 📄 evaluate.py                  # Model Evaluation (Main)
├── 📄 api.py                       # FastAPI Backend Server
├── 📄 state.py                     # Game State Management
├── 📄 diagnose.py                  # Training Diagnostics
├── 📄 reward_mapper.py             # Reward System Implementation
├── 📄 web_replay_logger.py         # Replay Generation System
├── 📄 generate_scenario.py         # Scenario Creation Utilities
├── 📄 scenario.json                # Current Game Scenario
├── 📂 event_log/                   # Training & Game Logs (Git Ignored)
│   ├── 📄 train_best_game_replay.json      # Best Training Game
│   ├── 📄 phase_based_replay_*.json        # Phase-based Replays
│   └── 📄 web_replay_*.json                # Web-compatible Replays
├── 📂 models/                      # Trained AI Models (Git Ignored)
│   ├── 📂 current/                 # Current Production Model
│   └── 📂 backups/                 # Model Checkpoints
└── 📄 xxx                          # Legacy/Test Files
```

### Key Components
- **DQN Implementation**: Deep Q-Network with experience replay
- **Phase-based Gameplay**: Implements Warhammer 40k turn structure
- **Sophisticated Reward System**: Complex tactical behavior reinforcement
- **Comprehensive Logging**: Detailed training metrics and game replays

## ⚙️ Configuration System (`/config/`)

### Structure
```
config/
├── 📄 config.json                  # Master Configuration & Paths
├── 📄 game_config.json             # Game Rules & Mechanics
├── 📄 training_config.json         # AI Training Parameters
├── 📄 rewards_config.json          # Reward System Definitions
├── 📄 board_config.json            # Board Layout & Visualization
├── 📄 scenario.json                # Game Scenarios
├── 📄 unit_definitions.json        # Unit Stats & Abilities
└── 📄 action_definitions.json      # Action System Definitions
```

### Configuration Profiles
- **Multiple Training Configs**: debug, default, conservative, aggressive, emergency
- **Multiple Reward Systems**: simplified, balanced, phase_based, original
- **Flexible Game Rules**: Customizable turn limits, board sizes, victory conditions

## 🛠️ Development Scripts (`/scripts/`)

### Structure
```
scripts/
├── 📄 backup_script.py             # Project Versioning & Backup
└── 📄 copy-configs.js              # Config File Management
```

### PowerShell Utilities
```
📄 ps.ps1                           # PowerShell Utility Scripts (Project Root)
```

## 📊 Build & Path Configuration

### TypeScript Path Aliases
```typescript
// Configured in tsconfig.json and vite.config.ts
"@/" → "frontend/src/"
"@components/" → "frontend/src/components/"
"@data/" → "frontend/src/data/"
"@roster/" → "frontend/src/roster/"
"@pages/" → "frontend/src/pages/"
"@types/" → "frontend/src/types/"
"@hooks/" → "frontend/src/hooks/"
"@services/" → "frontend/src/services/"
"@constants/" → "frontend/src/constants/"
"@utils/" → "frontend/src/utils/"
"@ai/" → "ai/"
"@config/" → "config/"
```

### File System Rules (Critical)
- **AI Scripts**: Always run from project root directory
- **Frontend Access**: Uses `/ai/` prefix for public file access
- **Config Location**: All configs in `/config/` directory (not `/ai/config/`)
- **Event Logs**: Generated in `/ai/event_log/`
- **Model Storage**: Use `get_model_path()` from `config_loader.py` (dynamic path from config)
- **Tensorboard**: Logs to `./tensorboard/` from root

## 🏗️ Build Commands

### Frontend Development
```bash
cd frontend
npm install                         # Install dependencies
npm run dev                         # Development server
npm run build                       # Production build
```

### AI Training
```bash
# From project root
python ai/train.py                  # Default training
python ai/train.py --training-config conservative --rewards-config balanced
python ai/evaluate.py               # Model evaluation
python ai/diagnose.py               # Training diagnostics
```

### Configuration Management
```bash
# Copy config files to frontend
node scripts/copy-configs.js

# PowerShell utilities (from project root)
.\ps.ps1
```

### Tensorboard Monitoring
```bash
tensorboard --logdir ./tensorboard/
```

## 📋 Git Ignore Strategy

### Ignored Directories (Large Files)
- `node_modules/` - Node.js dependencies (hundreds of MB)
- `ai/models/` - Trained AI models (multiple MB each)
- `tensorboard/` - Training logs (hundreds of MB)
- `ai/event_log/` - Game replay logs (can be large)
- `dist/` - Frontend build output
- `versions/` - Backup directories

### Preserved Files
- All configuration JSON files
- Source code (TypeScript, Python)
- Package.json files
- Documentation

## 🔄 Data Flow Architecture

### Training Pipeline
1. **Config Loading** → `config_loader.py` centralizes all configuration
2. **Environment Setup** → `gym40k.py` creates Gymnasium environment
3. **Model Training** → `train.py` executes DQN training
4. **Replay Generation** → `web_replay_logger.py` captures game data
5. **Evaluation** → `evaluate.py` tests model performance

### Frontend Integration
1. **Build Process** → Vite compiles TypeScript to JavaScript
2. **Config Access** → Frontend loads configs from `/public/ai/config/`
3. **Replay Loading** → Direct file access to replay JSON files
4. **AI Communication** → FastAPI backend for live AI games

### Configuration Synchronization
1. **Backend Configs** → All master configs in `/config/` directory
2. **Frontend Sync** → `scripts/copy-configs.js` copies to frontend public folder
3. **Dynamic Paths** → `config_loader.py` provides centralized path management

## 🎯 Key Design Principles

### Modularity
- Clear separation between frontend, backend, and configuration
- Reusable components with well-defined interfaces
- Plugin-style reward systems and training configurations

### Configuration-Driven
- No hardcoded parameters in training scripts
- JSON-based configuration with validation
- Multiple profiles for different use cases
- Centralized path management via `config_loader.py`

### Performance-Oriented
- PIXI.js for high-performance rendering
- Efficient replay system with minimal memory usage
- Optimized AI training with experience replay

### Development-Friendly
- Comprehensive error handling and diagnostics
- Detailed logging and monitoring
- Automated backup and versioning systems
- PowerShell utilities for Windows development

## 🔧 Development Workflow

### Configuration Updates
1. Modify configs in `/config/` directory
2. Run `node scripts/copy-configs.js` to sync to frontend
3. Frontend automatically loads updated configs

### Model Training
1. Configure training parameters in `/config/training_config.json`
2. Set reward system in `/config/rewards_config.json`
3. Run training from project root: `python ai/train.py`
4. Monitor with Tensorboard: `tensorboard --logdir ./tensorboard/`

### Backup & Versioning
1. Run `python scripts/backup_script.py` for project backup
2. Automated zipping and version management
3. Backups stored in `/versions/` directory (git ignored)

### Frontend Development
1. Configs automatically available at `/ai/config/` public path
2. Replay files accessible at `/ai/event_log/` public path
3. Hot reloading with Vite development server
4. TypeScript strict mode with comprehensive path aliases