# System Architecture - W40K AI Training System

## 🏗️ COMPLETE MIRROR ARCHITECTURE (CRITICAL)

### Core Principle
Python `use_*.py` files mirror exact behavior of TypeScript frontend components, ensuring consistency between training and gameplay.

### Full Component Hierarchy
```
FRONTEND (TypeScript)              ←→              BACKEND (Python)
GameController.tsx                 ←→              TrainingGameController
├── useGameState.ts               ←→              use_game_state.py
├── useGameActions.ts             ←→              use_game_actions.py  
├── usePhaseTransition.ts         ←→              use_phase_transition.py
├── useGameLog.ts                 ←→              use_game_log.py
├── useGameConfig.ts              ←→              use_game_config.py
└── BoardPvp.tsx                  ←→              (delegated to controller)

gym40k.py (Thin Gymnasium Wrapper)
    ↓ delegates to
TrainingGameController (Master Orchestrator)
    ↓ uses
use_*.py Mirror Files (Game Logic)
    ↓ mirrors exactly
Frontend TypeScript Components
```

## 🎮 FRONTEND ARCHITECTURE

### Main Components
**1. GameController.tsx (Master Controller)**
- Role: Main orchestrator for entire PvP game
- Responsibilities:
  - Initializes game state with useGameState
  - Manages all custom hooks integration
  - Handles dynamic unit generation
  - Coordinates between all game systems

**2. BoardPvp.tsx (Game Board)**
- Role: PIXI.js-powered game board rendering
- Responsibilities:
  - Renders units, hexes, movement previews
  - Handles user interactions (clicks, selections)
  - WebGL-optimized rendering with batching
  - Movement pathfinding visualization

**3. Supporting Components:**
- TurnPhaseTracker.tsx: Turn/phase display
- UnitStatusTable.tsx: Unit stats display
- GameLog.tsx: Action history logging
- GameStatus.tsx: Game state display
- UnitRenderer.tsx: Centralized unit rendering

### Custom Hooks System
**1. useGameState.ts (State Manager)**
- Role: Central game state management
- Manages: Units, players, phases, previews, combat sub-phases
- Returns: Complete game state + action dispatchers

**2. useGameActions.ts (Action Handler)**
- Role: All player actions (move, shoot, charge, combat)
- Uses: shared/gameRules.ts for combat calculations
- Key Functions:
  - isUnitEligible() - Unit selection logic
  - confirmMove() - Movement execution with flee detection
  - handleShoot() - Shooting sequence management
  - Movement pathfinding and validation

**3. usePhaseTransition.ts (Phase Manager)**
- Role: Automatic phase advancement
- Uses: isUnitEligible to determine phase transitions
- Handles: Move→Shoot→Charge→Combat progression

**4. useGameLog.ts (Logging System)**
- Role: Action logging and battle history
- Uses: shared/gameLogStructure.ts for consistent formatting

**5. useGameConfig.ts (Configuration)**
- Role: Loads board config, game rules from JSON files

### Complete Frontend Script List
**Core Scripts:**
- GameController.tsx - Master coordinator
- BoardPvp.tsx - PIXI.js game board
- useGameState.ts - State management
- useGameActions.ts - Action handling
- usePhaseTransition.ts - Phase management

**Supporting Scripts:**
- useGameLog.ts - Battle logging
- useGameConfig.ts - Configuration loading
- TurnPhaseTracker.tsx - UI display
- UnitStatusTable.tsx - Unit stats
- GameLog.tsx - Action history
- UnitRenderer.tsx - Unit visualization

**Shared Rules:**
- shared/gameRules.ts - Combat mechanics
- shared/gameLogStructure.ts - Log formatting

## 🔗 FRONTEND-BACKEND MIRRORING RULES

### Exact Component Mirroring
- **GameController.tsx** ↔ **TrainingGameController** (Master orchestrators)
- **useGameState.ts** ↔ **use_game_state.py** (State management)
- **useGameActions.ts** ↔ **use_game_actions.py** (Action handling)
- **usePhaseTransition.ts** ↔ **use_phase_transition.py** (Phase management)
- **useGameLog.ts** ↔ **use_game_log.py** (Logging systems)
- **useGameConfig.ts** ↔ **use_game_config.py** (Configuration)

### Mirroring Requirements
- **Identical Logic**: Python implementations must match TypeScript behavior exactly
- **Same Interfaces**: Function signatures and return types must be equivalent
- **Consistent State**: Both systems must maintain identical game state representation
- **Shared Rules**: Both use identical shared/gameRules.* for calculations

---

# 📁 FILE RESPONSIBILITIES (ABSOLUTE RULES)

## gym40k.py - Gymnasium Interface ONLY
**MUST ONLY contain:**
- Gymnasium interface (`action_space`, `observation_space`, `step`, `reset`)
- Action encoding/decoding between Gymnasium and controller
- Observation formatting for ML models
- Reward calculation using controller state
- Environment lifecycle management

**MUST NEVER contain:**
- Game state management (phase, turn, player)
- Game logic (movement, combat, phase transitions)
- Unit eligibility or validation logic
- Direct state manipulation
- Hardcoded game rules

**Required delegation pattern:**
```python
# ✅ CORRECT - delegate to controller
def step(self, action):
    return self.controller.execute_gym_action(action)

# ❌ WRONG - manage state directly
def step(self, action):
    self.current_phase = "move"  # Never do this
```

## TrainingGameController - Master Orchestrator
**Responsibilities:**
- Initialize and coordinate all `use_*.py` mirror components
- Provide clean interface to `gym40k.py`
- Manage component interactions
- Handle training-specific optimizations
- Connect replay logging

**Integration pattern:**
```python
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

## use_*.py Mirror Files - Single Sources of Truth

### use_game_state.py
- **THE** authoritative source for all game state
- Manages phase, turn, player, units, tracking lists
- Provides state manipulation functions
- **NO** other file duplicates this state

### use_game_actions.py  
- **THE** authoritative source for all game actions
- Validates actions, executes moves/combat/shooting
- Determines unit eligibility
- **NO** other file implements game actions

### use_phase_transition.py
- **THE** authoritative source for phase transitions
- Automatically advances phases based on state
- Handles turn progression
- **NO** other file manages phase transitions

### use_game_log.py
- **THE** authoritative source for game logging
- Handles all event logging for replay
- **NO** other file duplicates logging

### use_game_config.py
- **THE** authoritative source for game configuration
- Loads board, game, and other configs
- **NO** hardcoded values outside this system

---

# 🔗 STATE MANAGEMENT RULES (CRITICAL)

## Single Source of Truth
- **ONLY** `use_game_state.py` manages game state
- **ONLY** one `game_state` object exists per game
- All components reference the **SAME** `game_state` object
- **NO** copying or duplicating state objects

## State Access Pattern
```python
# ✅ CORRECT - use the manager's direct reference
self.game_state = self.state_manager.game_state  # Direct reference

# ❌ WRONG - create copies or separate state
self.game_state = copy.deepcopy(state_manager.get_game_state())  # Never copy
```

## State Updates
```python
# ✅ CORRECT - use state_actions functions
self.state_actions['set_phase']("shoot")
self.state_actions['add_moved_unit'](unit_id)

# ❌ WRONG - direct manipulation
self.game_state["phase"] = "shoot"  # Never do direct manipulation
```

---

# 🔄 INTEGRATION PATTERNS

## gym40k.py → Controller Delegation
```python
# Phase information
def get_current_phase(self):
    return self.controller.get_current_phase()

# Action execution  
def execute_action(self, action):
    return self.controller.execute_gym_action(action)

# Unit information
def get_eligible_units(self):
    return self.controller.get_eligible_units()
```

## Controller → use_*.py Coordination
```python
# Use direct references to shared objects
self.game_state = self.state_manager.game_state
self.phase_transitions = self.phase_manager.get_transition_functions()

# Coordinate between components
def advance_phase(self):
    return self.phase_transitions['process_phase_transitions']()
```

## External File Integration
**Files that access gym environment:**
- **evaluate.py** - must use `env.controller.get_current_phase()` not `env.current_phase`
- **game_replay_logger.py** - must use `env.controller.get_current_turn()` not `env.current_turn`
- **bot_manager.py** - must use controller methods for all game state access

**Required external file pattern:**
```python
# ✅ CORRECT - use controller
current_phase = env.controller.get_current_phase()
current_player = env.controller.get_current_player()

# ❌ WRONG - direct access
current_phase = env.current_phase  # This attribute should not exist
```

---

# 🚫 ERROR PREVENTION RULES

## NO Backward Compatibility Properties
- Never add `@property` methods for removed attributes
- Fix all external references to use proper architecture
- Clean code is more important than compatibility

## NO Default Values or Fallbacks
- Always raise errors for missing configuration
- Never create default units, configs, or values
- Force proper configuration and setup

## NO Workarounds
- Fix root causes, not symptoms
- Use proper architecture, not quick patches
- Remove broken features rather than band-aid them

---

# 📊 PROJECT STRUCTURE

```
wh40k-tactics/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── GameController.tsx           # Master PvP coordinator
│   │   │   ├── BoardPvp.tsx                 # PIXI.js game board
│   │   │   ├── TurnPhaseTracker.tsx         # Turn/phase display
│   │   │   ├── UnitStatusTable.tsx          # Unit stats display
│   │   │   ├── GameLog.tsx                  # Action history
│   │   │   ├── GameStatus.tsx               # Game state display
│   │   │   └── UnitRenderer.tsx             # Centralized unit rendering
│   │   ├── hooks/
│   │   │   ├── useGameState.ts              # Central state management
│   │   │   ├── useGameActions.ts            # Action handling
│   │   │   ├── usePhaseTransition.ts        # Phase management
│   │   │   ├── useGameLog.ts                # Battle logging
│   │   │   └── useGameConfig.ts             # Configuration loading
│   │   ├── pages/
│   │   │   ├── HomePage.tsx                 # Landing page
│   │   │   ├── GamePage.tsx                 # PvP/PvE game wrapper
│   │   │   └── ReplayPage.tsx               # Replay analysis
│   │   └── types/game.ts                    # TypeScript definitions
├── shared/
│   ├── gameRules.ts                      # TypeScript shared mechanics
│   └── gameRules.py                      # Python shared mechanics
├── ai/
│   ├── train.py                          # Main training orchestration
│   ├── gym40k.py                         # Thin Gymnasium wrapper
│   ├── game_controller.py                # Master orchestrator
│   ├── use_game_state.py                 # Game state management
│   ├── use_game_actions.py               # Game action handlers
│   ├── use_phase_transition.py           # Phase transitions
│   ├── use_game_log.py                   # Game logging
│   ├── use_game_config.py                # Configuration management
│   └── evaluate.py                       # Model evaluation
├── config/
│   ├── training_config.json              # DQN hyperparameters
│   ├── rewards_config.json               # Reward system definitions
│   ├── board_config.json                 # Board layout
│   └── unit_registry.json                # Unit mappings
└── config_loader.py                      # Centralized config manager
```

---

# 🚀 PERFORMANCE OPTIMIZATIONS

## PIXI.js Rendering Optimizations
**WebGL Acceleration:**
- **Removed forceCanvas**: Enabled hardware-accelerated WebGL rendering
- **Power Preference**: Added "high-performance" GPU preference
- **Performance Gain**: 300-500% faster rendering

**Container Batching System:**
- **Before**: 43,200 individual hex Graphics objects
- **After**: 2 container objects (baseHexes + highlights)
- **Memory Reduction**: ~95% reduction in scene graph complexity
- **Rendering Efficiency**: Significant frame rate improvement

**Scalable Board Architecture:**
- **Default Board**: 24×18 hexes (432 total)
- **Large Board Ready**: Architecture supports 240×180 hexes (43,200 total)
- **Memory Efficient**: WebGL + container batching enables massive scale

## Visual Enhancement System
**Per-Unit Icon Scaling:**
- **Scale Range**: 0.5 to 2.5 (configurable per unit)
- **Default Scale**: 1.2 from board configuration
- **Unit-Specific**: Each unit type can override with `ICON_SCALE` property

**Enhanced Visual Features:**
- **HP Bars**: Scale position based on icon size
- **Shooting Counters**: "current/total" format with anti-collision
- **Activation Circles**: Green circles with adaptive radius
- **Z-Index Priority**: Smaller units render above larger ones

---

# 🔄 SHARED GAME RULES SYSTEM

## Centralized Game Mechanics
**Architecture:**
- **Unified W40K Rules**: Both frontend and AI use identical mechanics
- **Single Source of Truth**: Combat calculations centralized
- **Zero Code Duplication**: Eliminated duplicate functions
- **Consistent Behavior**: Frontend previews match AI training

**Implementation Files:**
```typescript
// TypeScript shared rules (frontend)
import { rollD6, calculateWoundTarget, executeShootingSequence } from '../../../shared/gameRules';

// Python shared rules (AI training)  
from shared.gameRules import roll_d6, calculate_wound_target, execute_shooting_sequence
```

---

# ⚙️ CONFIGURATION SYSTEM

## ConfigLoader System
**Configuration Files:**
- **training_config.json**: DQN hyperparameters with named configs
- **rewards_config.json**: Faction-specific reward matrices
- **board_config.json**: Board layout with performance settings
- **scenario_templates.json**: Dynamic scenario generation templates
- **unit_registry.json**: Unit name to TypeScript file mappings

**Enhanced Board Configuration:**
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
      "unit_circle_radius_ratio": 0.6
    }
  }
}
```

---

# 🎮 NAVIGATION & USER INTERFACE

## Route System
**Routes Available:**
- **`/game`** - Default PvP mode (root redirects here)
- **`/pve`** - PvE mode against AI
- **`/replay`** - Replay analysis and visualization
- **`/home`** - Landing page with mode selection

**Navigation Features:**
- Top-right navigation bar with mode buttons
- Visual indication of current active mode
- Direct navigation between game modes
- Responsive design with proper spacing

## UnitRenderer Component System
**Major Architectural Improvement:**
- **Centralized Unit Rendering**: All unit display logic in dedicated component
- **Code Reduction**: Board.tsx reduced by 37% (800→500 lines)
- **Maintainability**: Single source of truth for unit visuals
- **Consistency**: Identical rendering across all modes

---

# 📊 MONITORING & REPLAY SYSTEM

## Training Monitoring
**Metrics Tracked:**
- Win rate per agent matchup
- Average episode rewards
- Training session duration and efficiency
- Real-time progress bars focusing on slowest agent

**Logging Systems:**
- Tensorboard integration at `./tensorboard/`
- Comprehensive replay files with AI decision context
- Orchestration results with performance statistics

## Replay Format
```json
{
  "game_info": {
    "scenario": "training_episode",
    "total_turns": 25,
    "winner": 0,
    "ai_behavior": "phase_based"
  },
  "initial_state": {
    "units": [...],
    "board_size": [24, 18]
  },
  "actions": [...]
}
```

---

# 🛠️ DEVELOPMENT WORKFLOW

## Build Process
```bash
# Frontend development
cd frontend && npm run dev

# Build for production
npm run build
```

**Pre-build Configuration:**
- Automatic config copying via `scripts/copy-configs.js`
- Vite build system with TypeScript compilation
- ESLint configuration with React hooks enforcement

## Training Workflows
```bash
# Basic training
python ai/train.py

# Multi-agent orchestration  
python ai/train.py --orchestrate --total-episodes 1000

# Debug training (50k timesteps)
python ai/train.py --training-config debug

# Model evaluation
python ai/evaluate.py --episodes 50
```

---

# ✅ ARCHITECTURE COMPLIANCE CHECKS

## Required Validations:
- gym40k.py has no game state variables (`current_phase`, etc.)
- Only one `game_state` object exists per environment
- All state changes go through `state_actions` functions
- No hardcoded game values outside config system
- All external files use controller methods, not direct gym attributes
- State changes reflected across all components immediately
- Phase transitions work without manual synchronization

## Migration Path for Refactoring:
1. **Identify misplaced logic** in gym40k.py
2. **Find appropriate use_*.py file** for the logic
3. **Add/modify method** in use_*.py file if needed
4. **Expose through controller** with clean interface
5. **Replace gym40k.py logic** with controller delegation
6. **Update external files** to use controller methods
7. **Remove old attributes/methods** from gym40k.py

This architecture ensures clean separation of concerns, maintainable code, and consistency between training and gameplay environments.