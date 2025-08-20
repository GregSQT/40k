# W40K AI Training System Architecture

## 🏗️ CORE ARCHITECTURE PRINCIPLES

### Complete Frontend-Backend Mirroring
The system maintains **exact behavioral consistency** between TypeScript frontend components and Python AI training components through a comprehensive mirroring architecture.

```
FRONTEND (TypeScript)              ←→              BACKEND (Python)
GameController.tsx                 ←→              TrainingGameController
├── useGameState.ts               ←→              use_game_state.py
├── useGameActions.ts             ←→              use_game_actions.py  
├── usePhaseTransition.ts         ←→              use_phase_transition.py
├── useGameLog.ts                 ←→              use_game_log.py
├── useGameConfig.ts              ←→              use_game_config.py
└── BoardPvp.tsx                  ←→              SequentialActivationEngine

gym40k.py (Thin Gymnasium Wrapper)
    ↓ delegates to
SequentialGameController (Integration Layer)
    ↓ uses
TrainingGameController (Master Orchestrator)
    ↓ uses
use_*.py Mirror Files (Game Logic)
    ↓ mirrors exactly
Frontend TypeScript Components
```

### AI Training Pipeline
```
W40KEnv (gym40k.py)
    ↓ action encoding/decoding
StepLoggingWrapper
    ↓ detailed action logging
SequentialGameController
    ↓ sequential activation engine
TrainingGameController
    ↓ component coordination
use_*.py Mirror Components
    ↓ game logic execution
Shared Game Rules (TypeScript/Python)
```

---

## 🎮 FRONTEND ARCHITECTURE

### Core Components

**GameController.tsx (Master Orchestrator)**
- **Role**: Central coordinator for all game modes (PvP, PvE, Training)
- **Responsibilities**:
  - Initializes game state with `useGameState` hook
  - Manages all custom hooks integration
  - Handles dynamic unit generation from `UnitFactory`
  - Coordinates multi-mode game systems
  - Detects game mode from URL routing

**BoardPvp.tsx (PIXI.js Game Board)**
- **Role**: Hardware-accelerated 2D game rendering
- **Responsibilities**:
  - WebGL-optimized hex grid rendering with container batching
  - Real-time unit visualization with per-unit icon scaling
  - Interactive movement previews and pathfinding
  - Combat targeting and phase transition animations
  - Scalable architecture (24×18 to 240×180 hexes)

**Supporting Components**:
- `TurnPhaseTracker.tsx`: Real-time phase/turn display
- `UnitStatusTable.tsx`: Collapsible unit statistics with HP tracking
- `GameLog.tsx`: Action history with replay functionality  
- `GameStatus.tsx`: Game state and victory conditions
- `UnitRenderer.tsx`: Centralized unit visualization system
- `BoardReplay.tsx`: Replay visualization with action highlighting

### Custom Hooks System

**useGameState.ts (State Management)**
- **Single Source of Truth** for all game state
- **Manages**: Units, players, phases, previews, combat sub-phases
- **State Structure**: Phase tracking, unit lists, combat states
- **Returns**: Complete game state + action dispatchers

**useGameActions.ts (Action Handler)**
- **Handles**: Move, shoot, charge, combat actions
- **Key Features**:
  - `isUnitEligible()`: Phase-specific unit selection logic
  - `confirmMove()`: Movement execution with flee detection
  - `handleShoot()`: Multi-shot sequence management
  - Movement pathfinding and validation
  - Combat sub-phase management

**usePhaseTransition.ts (Phase Manager)**
- **Automatic Phase Progression**: Move→Shoot→Charge→Combat
- **Uses**: Unit eligibility system for transition detection
- **Handles**: Turn advancement and game-over detection

**useGameLog.ts (Logging System)**
- **Action Logging**: Complete battle history
- **Replay Support**: Compatible with AI training logs
- **Uses**: `shared/gameLogStructure.ts` for consistency

**useGameConfig.ts (Configuration)**
- **Loads**: Board config, game rules, unit definitions
- **Validates**: Configuration completeness
- **Supports**: Multiple board sizes and performance settings

---

## 🤖 AI TRAINING ARCHITECTURE

### Python Mirror Components

**TrainingGameController (Master Orchestrator)**
```python
class TrainingGameController:
    def __init__(self, config, quiet=False):
        self._initialize_hooks()
        self.connect_shared_rules()
    
    def _initialize_hooks(self):
        # Initialize each mirror component
        self.state_manager = TrainingGameState(units)
        self.game_state = self.state_manager.game_state  # Direct reference
        self.state_actions = self.state_manager.get_actions()
        
        self.actions_manager = TrainingGameActions(...)
        self.game_actions = self.actions_manager.get_available_actions()
        
        self.phase_manager = TrainingPhaseTransition(...)
        self.phase_transitions = self.phase_manager.get_transition_functions()
```

**Sequential Activation System**
- **SequentialActivationEngine**: Enforces exact AI_GAME.md rules
- **Sequential queue management**: One unit per action step
- **Combat sub-phases**: Charged units → Alternating combat
- **Phase transitions**: Automatic with eligibility validation

**Mirror File Responsibilities**:

- **use_game_state.py**: 
  - THE authoritative source for all game state
  - Manages phase, turn, player, units, tracking lists
  - NO other file duplicates this state

- **use_game_actions.py**:
  - THE authoritative source for all game actions
  - Validates actions, executes moves/combat/shooting
  - Determines unit eligibility per phase

- **use_phase_transition.py**:
  - THE authoritative source for phase transitions
  - Automatically advances phases based on unit eligibility
  - Handles turn progression and game-over detection

### Gymnasium Integration

**gym40k.py (Thin Wrapper)**
- **ONLY Contains**: Gymnasium interface (`action_space`, `observation_space`, `step`, `reset`)
- **Delegates Everything**: All game logic to controller
- **NEVER Contains**: Game state, phase management, unit logic

```python
# ✅ CORRECT - delegate to controller
def step(self, action):
    return self.controller.execute_gym_action(action)

# ❌ WRONG - manage state directly  
def step(self, action):
    self.current_phase = "move"  # Never do this
```

---

## 🔄 SHARED GAME RULES SYSTEM

### Unified Combat Mechanics
Both frontend and AI training use **identical** combat calculations:

```typescript
// TypeScript (frontend)
import { rollD6, calculateWoundTarget, executeShootingSequence } from '../../../shared/gameRules';

// Python (AI training)
from shared.gameRules import roll_d6, calculate_wound_target, execute_shooting_sequence
```

**Critical Field Naming Consistency**:
- **ALL unit fields MUST be UPPERCASE**: `RNG_ATK`, `CC_STR`, `ARMOR_SAVE`, `INVUL_SAVE`, `T`
- **ZERO tolerance for lowercase**: `rng_atk`, `cc_str`, `armor_save` cause immediate KeyError
- **Both languages must match**: Python and TypeScript use identical field names

### Combat System Features
- **Shooting**: Range validation, line of sight, multi-shot sequences
- **Close Combat**: Charge mechanics, alternating combat, flee detection  
- **Wound System**: Strength vs Toughness calculations
- **Save System**: Armor and invulnerable saves with AP modification
- **Dice Rolling**: Consistent D6 mechanics across all systems

---

## 🚀 PERFORMANCE OPTIMIZATIONS

### PIXI.js Rendering System

**WebGL Acceleration**:
- **Hardware Acceleration**: Removed `forceCanvas`, enabled WebGL
- **Power Preference**: "high-performance" GPU preference
- **Performance Gain**: 300-500% faster rendering vs Canvas2D

**Container Batching Architecture**:
- **Before**: 43,200 individual hex Graphics objects
- **After**: 2 container objects (baseHexes + highlights)  
- **Memory Reduction**: ~95% reduction in scene graph complexity
- **Scalability**: Supports massive 240×180 hex boards

**Visual Enhancement System**:
- **Per-Unit Icon Scaling**: 0.5 to 2.5 scale range, configurable per unit type
- **Dynamic HP Bars**: Scale position based on icon size
- **Shooting Counters**: "current/total" format with collision avoidance
- **Z-Index Management**: Smaller units render above larger ones

### AI Training Optimizations

**Sequential Activation Engine**:
- **One Unit Per Step**: Eliminates batch processing overhead
- **Phase-Based Queues**: Efficient unit eligibility pre-calculation
- **Combat Sub-Phases**: Charged units → Alternating combat logic
- **Step Counting Compliance**: Only actions that change game state count

**Memory Management**:
- **Shared State Objects**: Single `game_state` object across all components
- **Direct References**: No copying or duplicating state objects
- **Config-Driven**: No hardcoded values, all configuration external

---

## ⚙️ CONFIGURATION SYSTEM

### Configuration Files
```
config/
├── training_config.json      # DQN hyperparameters with named configs
├── rewards_config.json       # Faction-specific reward matrices  
├── board_config.json         # Board layout with performance settings
├── scenario_templates.json   # Dynamic scenario generation
├── unit_registry.json        # Unit name to TypeScript file mappings
└── unit_definitions.json     # Complete unit statistics
```

**Enhanced Board Configuration**:
```json
{
  "default": {
    "cols": 24,
    "rows": 18, 
    "hex_radius": 24,
    "display": {
      "powerPreference": "high-performance",
      "antialias": true,
      "icon_scale": 1.2,
      "unit_circle_radius_ratio": 0.6,
      "canvas_border": "2px solid #333"
    },
    "colors": {
      "background": "0x2a2a2a",
      "highlight": "0xffff00",
      "attack": "0xff0000",
      "charge": "0x00ff00",
      "eligible": "0x00ff00"
    }
  }
}
```

### ConfigLoader System
- **Centralized Management**: Single point for all configuration
- **Error Handling**: Raises errors for missing configuration
- **No Fallbacks**: Forces proper configuration setup
- **Multi-Environment**: Supports development and production configs

---

## 🎮 USER INTERFACE & NAVIGATION

### Route System
- **`/game`**: Default PvP mode (root redirects here)
- **`/pve`**: Player vs AI mode with bot integration
- **`/replay`**: Replay analysis and visualization  
- **`/home`**: Landing page with mode selection

### Component Architecture
- **SharedLayout**: Common navigation and styling
- **ErrorBoundary**: React error catching and recovery
- **Responsive Design**: Adapts to different screen sizes
- **Mode Detection**: Automatic game mode from URL

---

## 📊 MONITORING & REPLAY SYSTEM

### Training Monitoring
**Real-Time Metrics**:
- Win rate per agent matchup
- Average episode rewards  
- Training session duration and efficiency
- Progress bars focusing on slowest agent

**Logging Integration**:
- **Tensorboard**: `./tensorboard/` directory integration
- **Replay Files**: Complete action history with AI decision context
- **Orchestration Results**: Performance statistics and metadata

### Replay Format
```json
{
  "game_info": {
    "scenario": "training_episode",
    "total_turns": 25,
    "winner": 0,
    "ai_behavior": "sequential_activation"
  },
  "initial_state": {
    "units": [...],
    "board_size": [24, 18]
  },
  "actions": [
    {
      "step": 1,
      "phase": "move",
      "player": 0,
      "unit_id": 0,
      "action_type": "move",
      "details": {...}
    }
  ]
}
```

---

## 🛠️ DEVELOPMENT WORKFLOW

### Build Process
```bash
# Frontend development with automatic config sync
cd frontend && npm run dev

# Production build with optimization
npm run build

# AI training with debug mode  
python ai/train.py --training-config debug

# Model evaluation
python ai/evaluate.py --episodes 50
```

**Automated Systems**:
- **Config Sync**: `scripts/copy-configs.js` syncs backend configs to frontend
- **Unit Registry**: Auto-generation of unit mappings
- **Backup System**: Complete project backups with clean filenames
- **TypeScript Compilation**: Strict mode with React hooks enforcement

### Testing & Validation
**Required Validations**:
- gym40k.py has no game state variables (`current_phase`, etc.)
- Only one `game_state` object exists per environment
- All state changes go through `state_actions` functions
- No hardcoded game values outside config system
- All external files use controller methods, not direct gym attributes

**Model Storage**:
- **Agent-Based**: Each agent maintains one evolving model
- **Persistent Learning**: Models carry forward across training sessions
- **Storage Efficiency**: One model per agent instead of session snapshots

---

## 📁 COMPLETE PROJECT STRUCTURE

```
wh40k-tactics/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── GameController.tsx           # Master coordinator
│   │   │   ├── BoardPvp.tsx                 # PIXI.js game board
│   │   │   ├── BoardReplay.tsx              # Replay visualization
│   │   │   ├── TurnPhaseTracker.tsx         # Phase display
│   │   │   ├── UnitStatusTable.tsx          # Unit statistics
│   │   │   ├── GameLog.tsx                  # Action history
│   │   │   ├── GameStatus.tsx               # Game state
│   │   │   ├── UnitRenderer.tsx             # Unit visualization
│   │   │   ├── SharedLayout.tsx             # Navigation layout
│   │   │   └── ErrorBoundary.tsx            # Error handling
│   │   ├── hooks/
│   │   │   ├── useGameState.ts              # State management
│   │   │   ├── useGameActions.ts            # Action handling
│   │   │   ├── usePhaseTransition.ts        # Phase management
│   │   │   ├── useGameLog.ts                # Battle logging
│   │   │   ├── useGameConfig.ts             # Configuration
│   │   │   └── useAIPlayer.ts               # AI integration
│   │   ├── pages/
│   │   │   ├── HomePage.tsx                 # Landing page
│   │   │   ├── GamePage.tsx                 # Game wrapper
│   │   │   └── ReplayPage.tsx               # Replay analysis
│   │   ├── data/
│   │   │   └── UnitFactory.tsx              # Dynamic unit creation
│   │   └── types/game.ts                    # TypeScript definitions
├── shared/
│   ├── gameRules.ts                         # TypeScript mechanics
│   ├── gameRules.py                         # Python mechanics
│   └── gameLogStructure.ts                 # Log formatting
├── ai/
│   ├── train.py                             # Training orchestration
│   ├── gym40k.py                            # Gymnasium wrapper
│   ├── game_controller.py                  # Master orchestrator
│   ├── sequential_integration_wrapper.py   # Sequential engine integration
│   ├── sequential_activation_engine.py     # AI_GAME.md compliance
│   ├── step_logging_wrapper.py             # Action logging
│   ├── use_game_state.py                   # State management
│   ├── use_game_actions.py                 # Action handlers
│   ├── use_phase_transition.py             # Phase transitions
│   ├── use_game_log.py                     # Game logging
│   ├── use_game_config.py                  # Configuration
│   ├── unit_registry.py                    # Unit mappings
│   └── evaluate.py                         # Model evaluation
├── config/
│   ├── training_config.json                # DQN hyperparameters
│   ├── rewards_config.json                 # Reward definitions
│   ├── board_config.json                   # Board layout
│   ├── scenario_templates.json             # Scenario generation
│   ├── unit_registry.json                  # Unit mappings
│   └── unit_definitions.json               # Unit statistics
├── models/
│   ├── default_model_{agent_key}.zip       # Persistent models
│   ├── orchestration_results_*.json        # Training metadata
│   └── eval_logs/                          # Evaluation histories
├── scripts/
│   ├── copy-configs.js                     # Config synchronization
│   ├── backup_block.py                     # Project backups
│   └── restore_block.py                    # Backup restoration
└── config_loader.py                        # Centralized config manager
```

---

## 🚫 CRITICAL ERROR PREVENTION

### Architecture Rules
- **NO Backward Compatibility**: Fix all references to use proper architecture
- **NO Default Values**: Always raise errors for missing configuration  
- **NO Workarounds**: Fix root causes, not symptoms
- **Single Source of Truth**: Each component owns exactly one responsibility

### Field Naming Enforcement
```python
# ✅ CORRECT - uppercase fields
unit["RNG_ATK"], target["ARMOR_SAVE"], attacker["CC_STR"]

# ❌ FORBIDDEN - lowercase fields  
unit["rng_atk"], target["armor_save"], attacker["cc_str"]
```

### State Management Rules
- **ONLY** `use_game_state.py` manages game state
- **ONLY** one `game_state` object exists per game
- All components reference the **SAME** `game_state` object
- **NO** copying or duplicating state objects

### External File Integration
```python
# ✅ CORRECT - use controller methods
current_phase = env.controller.get_current_phase()
current_player = env.controller.get_current_player()

# ❌ WRONG - direct access
current_phase = env.current_phase  # This attribute should not exist
```

---

## 🎯 SUMMARY

This architecture provides:

✅ **Complete Frontend-Backend Consistency**: Identical game logic in TypeScript and Python  
✅ **High Performance**: WebGL rendering with 300-500% speed improvements  
✅ **Scalable Design**: Supports massive boards and complex scenarios  
✅ **Sequential AI Training**: Full AI_GAME.md compliance with sequential activation  
✅ **Comprehensive Monitoring**: Real-time training metrics and replay analysis  
✅ **Clean Architecture**: Single source of truth with clear component boundaries  
✅ **Configuration-Driven**: No hardcoded values, all behavior configurable  
✅ **Robust Error Handling**: Strict validation with informative error messages  
✅ **Multi-Mode Support**: PvP, PvE, Training, and Replay modes  
✅ **Developer Friendly**: Clear documentation and automated development workflows  

The system successfully bridges the gap between human-playable frontend games and AI training environments while maintaining perfect behavioral consistency and optimal performance.