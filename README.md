# Warhammer 40K PvE Tactical Strategy Game

## 🎯 Project Overview

This project is a comprehensive **AI-powered Warhammer 40K tactical strategy game** that combines deep reinforcement learning with strict rule compliance to create intelligent AI opponents for solo strategic gaming. Built as a solution to the classic wargamer problem: "To play a 2-player game... You need to be TWO!"

### Core Mission
Transform tabletop Warhammer 40K into a digital experience where players can face challenging AI opponents that understand strategy, positioning, and complex rule interactions without needing human opponents.

## 🏗️ Technical Architecture

### Frontend Stack
- **React 18** with TypeScript for UI framework
- **PIXI.js 8.0** for high-performance hex-grid canvas rendering
- **React Router** for navigation
- **Strict TypeScript** compliance with comprehensive type definitions
- **French Windows PowerShell** compatible development environment

### Backend Stack
- **Python** backend with pure stateless functions
- **Deep Q-Network (DQN)** reinforcement learning implementation
- **OpenAI Gym** interface for training compatibility
- **Tensorboard** integration for training monitoring
- **RESTful API** for frontend-backend communication

### Core Design Principles
- **AI_TURN.md Compliance**: Zero tolerance for architectural violations
- **Sequential Unit Activation**: ONE unit per gym step only
- **Pure Functions**: All handlers are stateless with no internal storage
- **Single Source of Truth**: One authoritative game_state object
- **Eligibility-Based Phases**: Phases end when activation pools empty
- **Built-in Step Counting**: Engine-level step management, never retrofitted

## 🎮 Game Features

### Multi-Phase Gameplay
The game implements strict Warhammer 40K turn structure:

1. **Movement Phase** - Unit positioning and tactical maneuvering
2. **Shooting Phase** - Ranged combat with line-of-sight calculations  
3. **Charge Phase** - Close combat engagement preparation
4. **Fight Phase** - Melee combat resolution

### Unit Management
- **Comprehensive Unit Types**: Intercessors, Assault Intercessors, Termagants, Carnifex
- **Multiple Weapons System**: Units can have up to 3 ranged and 2 melee weapons
- **Automatic Weapon Selection**: AI automatically selects optimal weapon per target
- **UPPERCASE Field Convention**: All unit stats use proper naming (HP_CUR, MOVE_LEFT, etc.)
- **Dynamic Unit Registry**: Configurable unit definitions with full stat tracking
- **Real-time Status Updates**: HP bars, movement remaining, attack counters
- **Centralized Armory**: Single source of truth for all weapon definitions

### Game Modes
- **PvE Mode**: Human vs AI with intelligent opponents
- **PvP Mode**: Human vs Human gameplay
- **Replay System**: Complete game state logging and replay functionality
- **Training Mode**: AI self-play for model improvement

## 🤖 AI Implementation

### Deep Reinforcement Learning
- **142-Dimensional Observation Space**: Comprehensive game state representation
- **DQN Training Pipeline**: Deep Q-Networks with experience replay
- **Multi-Agent Support**: Individual AI agents for different unit types
- **Reward System**: Configurable rewards for strategic behaviors
- **Curriculum Learning**: Progressive difficulty scaling

### Training Infrastructure
- **Training Configuration**: `config/training_config.json`
- **Reward Configuration**: `config/rewards_config.json` 
- **Model Management**: Dynamic model loading with 3 strategies
- **Performance Monitoring**: Tensorboard integration at `./tensorboard/`
- **Episode Management**: Turn limits and game state validation

### AI Behavioral Features
- **Strategic Decision Making**: Cover usage, positioning, objective control
- **Tactical Awareness**: Line-of-sight calculations, threat assessment
- **Adaptive Learning**: Continuous improvement through self-play
- **Rule Compliance**: Perfect adherence to Warhammer 40K mechanics

## 📁 Project Structure

```
w40k-tactics/
├── engine/                          # Core game engine
│   ├── w40k_engine.py              # Main game state management
│   ├── phase_handlers/             # Phase-specific logic
│   │   ├── movement_handlers.py    # Movement phase implementation
│   │   ├── shooting_handlers.py    # Shooting phase implementation
│   │   ├── charge_handlers.py      # Charge phase implementation
│   │   └── fight_handlers.py       # Fight phase implementation
│   ├── wrappers/                   # Interface layers
│   │   ├── gym_wrapper.py          # OpenAI Gym compatibility
│   │   └── api_wrapper.py          # HTTP API interface
│   └── utils/                      # Utility functions
│       ├── unit_manager.py         # Unit management utilities
│       ├── scenario_manager.py     # Scenario loading/generation
│       └── config_loader.py        # Configuration management
│
├── config/                         # Game configuration
│   ├── board_config.json          # Board layout settings
│   ├── game_config.json           # Game rules configuration
│   ├── rewards_config.json        # AI reward definitions
│   ├── training_config.json       # Training hyperparameters
│   ├── unit_definitions.json      # Unit stats and abilities
│   ├── unit_registry.json         # Unit type mappings
│   └── scenario*.json             # Game scenarios
│
├── frontend/                       # React TypeScript UI
│   ├── src/
│   │   ├── components/             # UI components
│   │   │   ├── BoardWithAPI.tsx    # Main game board with API
│   │   │   ├── UnitRenderer.tsx    # PIXI.js unit rendering
│   │   │   ├── GameBoard.tsx       # Core board component
│   │   │   ├── GameLog.tsx         # Action history display
│   │   │   └── TurnPhaseTracker.tsx # Phase progression UI
│   │   ├── types/                  # TypeScript definitions
│   │   │   ├── gameTypes.ts        # Game state interfaces
│   │   │   ├── unitTypes.ts        # Unit definition types
│   │   │   └── apiTypes.ts         # API communication types
│   │   └── utils/                  # Frontend utilities
│   └── public/config/              # Frontend configuration
│
├── ai/                             # AI training system
│   ├── train.py                    # Main training script
│   ├── evaluate.py                 # Model evaluation
│   ├── gym40k.py                   # Gym environment wrapper
│   ├── dqn_agent.py               # DQN implementation
│   └── event_log/                  # Training event logging
│
├── scripts/                        # Utility scripts
│   ├── backup_select.py           # Data backup utilities
│   ├── copy-configs.js            # Configuration management
│   └── test_compliance.py         # AI_TURN.md validation
│
└── Documentation/                  # Project documentation
    ├── AI_IMPLEMENTATION.md       # Implementation guidelines
    ├── AI_TRAINING.md             # Training integration guide
    ├── AI_TURN.md                 # Turn sequence specification
    ├── AI_GAME.md                 # Game rules specification
    └── AI_ARCHITECTURE.md         # Architecture documentation
```

## 🎨 Visual Features

### PIXI.js Rendering
- **Hex-Grid Mathematics**: Precise unit positioning with cube coordinates
- **Real-time HP Bars**: Animated health indicators with damage preview
- **Movement Visualization**: Green hexes for valid destinations
- **Shooting Indicators**: Red hexes for valid targets
- **Cover Visualization**: Yellow shields for units in cover
- **Phase Indicators**: Clear visual feedback for current game state

### UI Components
- **Interactive Hex Selection**: Click-based unit and target selection
- **Turn Phase Tracker**: Visual progression through game phases
- **Unit Status Display**: Comprehensive unit information panels
- **Game Log**: Detailed action history with timestamp tracking
- **AI Status Indicators**: Real-time AI processing feedback

## ⚙️ Configuration System

### Flexible Configuration
- **JSON-Based Settings**: All game parameters externally configurable
- **Unit Definitions**: Complete unit stat management
- **Scenario Templates**: Reusable battle setups
- **Training Parameters**: Adjustable AI learning settings
- **Reward Tuning**: Fine-grained reward system control

### Environment Compatibility
- **PowerShell Support**: Full French Windows compatibility
- **TypeScript Strict Mode**: Maximum type safety
- **Error Boundaries**: Comprehensive error handling
- **Loading States**: Smooth user experience during transitions

## 🧪 Testing & Validation

### Compliance Testing
- **AI_TURN.md Validation**: Automated compliance checking
- **Unit Registry Consistency**: Cross-system validation
- **Model Loading Verification**: Training system compatibility
- **Scenario Validation**: Game setup verification

### Quality Assurance
- **TypeScript Strict Mode**: Compile-time error prevention
- **PIXI.js Cleanup**: Memory management for long sessions
- **JSON Validation**: Configuration integrity checking
- **Error Handling**: Comprehensive exception management

## 🚀 Development Workflow

### File System Organization
- **Scripts from Root**: All utility scripts run from project root
- **Frontend API Prefix**: Uses `/ai/` prefix for backend communication
- **Config Centralization**: All configuration in `config/` directory
- **Event Logging**: Training events in `ai/event_log/`
- **Model Management**: Models stored in `ai/models/<agent_key>/model_<agent_key>.zip`
- **Tensorboard Logs**: Training monitoring in `./tensorboard/`

### Code Quality Standards
- **camelCase**: JavaScript/TypeScript naming convention
- **snake_case**: Python naming convention
- **Pure Functions**: Stateless design throughout
- **Single Responsibility**: Clear separation of concerns
- **Documentation**: Comprehensive inline documentation

## 🎯 Success Metrics

### Technical Achievement
- ✅ Complete AI_TURN.md specification compliance
- ✅ Successful DQN training with strategic behavior
- ✅ Real-time PIXI.js rendering with smooth performance
- ✅ Full-stack TypeScript/Python integration
- ✅ Comprehensive test suite coverage

### Gaming Experience
- ✅ Challenging AI opponents that use strategy
- ✅ Faithful Warhammer 40K rule implementation
- ✅ Intuitive user interface for tactical gameplay
- ✅ Replay system for game analysis
- ✅ Multi-scenario support for varied gameplay

## 🔧 Current Development Status

### Completed Features
- Core game engine with phase management
- PIXI.js frontend with hex-grid rendering
- DQN training pipeline with Tensorboard
- RESTful API for frontend-backend communication
- Comprehensive configuration system
- Unit management and scenario loading

### Active Development Areas
- Movement validation and preview systems
- Shooting mechanics and line-of-sight calculations
- HP bar visual feedback and damage preview
- Reward system optimization for training
- Phase transition debugging and validation

## 📚 Documentation

The project includes comprehensive documentation covering:

- **AI_IMPLEMENTATION.md**: Detailed implementation guidelines
- **AI_TRAINING.md**: Training system integration guide  
- **AI_TURN.md**: Complete turn sequence specification
- **AI_GAME.md**: Game rules and mechanics documentation
- **AI_ARCHITECTURE.md**: System architecture overview
- **AI_WEAPON_SELECTION.md**: How AI agents automatically select optimal weapons
- **ARMORY_REFACTOR.md**: Weapon management guide (how to add/remove weapons)

## 🎮 Getting Started

### Prerequisites
- Node.js 18+ with TypeScript support
- Python 3.8+ with required dependencies
- PowerShell-compatible environment
- Modern web browser with PIXI.js support

### Installation
```bash
# Install frontend dependencies
npm install

# Install Python dependencies  
pip install -r requirements.txt

# Start frontend development server
npm start

# Launch backend API (separate terminal)
python -m engine.api_wrapper
```

### Training AI Models
```bash
# Start training with default configuration
python ai/train.py

# Monitor training progress
tensorboard --logdir=./tensorboard/

# Evaluate trained models
python ai/evaluate.py
```

This project represents a complete solution for digital Warhammer 40K tactical gaming, combining modern web technologies with advanced AI to create an engaging solo gaming experience that preserves the strategic depth of the original tabletop game.
