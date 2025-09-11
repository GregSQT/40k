# AI_TURN.md Compliant Architecture - Implementation Plan
## Focus on HOW to Build, Not WHAT to Build

### EXECUTIVE SUMMARY

This implementation provides **concrete examples** of AI_TURN.md rule implementation within compliant architecture, **complete migration strategy** preserving existing assets, and **risk assessment** with fallback strategies.

**Core Principle:** Validate architecture can handle AI_TURN.md complexity through proof-of-concept, while preserving all valuable existing work.

## ⚠️ CRITICAL DEPENDENCY WARNING

**Before implementing this architecture, you MUST read [AI_TRAINING_INTEGRATION.md](AI_TRAINING_INTEGRATION.md)**

This document covers **game engine architecture compliance** only. The training integration document covers:
- **DQN training compatibility requirements** - Maintaining gym.Env interface exactly
- **Observation space preservation** - Ensuring existing trained models continue working  
- **Reward system integration** - Using rewards_config.json correctly
- **Model loading strategy preservation** - Supporting all 3 loading approaches
- **Multi-agent training continuity** - Maintaining orchestration workflows

**Without training integration, your compliant engine will be architecturally perfect but unusable for AI learning.**

**Implementation Order:**
1. Read this document for architecture compliance
2. Read AI_TRAINING_INTEGRATION.md for training compatibility  
3. Implement both requirements simultaneously
4. Test architectural compliance AND training functionality

---

## 📋 NAVIGATION & TESTING PATH

- [Validation Strategy](#validation-strategy-proof-of-concept-first) - Proof-of-concept architecture validation
- [Architecture Compliance](#architecture-compliance) - Single source of truth implementation
- [AI Training Integration](AI_TRAINING_INTEGRATION.md) - DQN compatibility with compliant architecture
- [Code Organization](#code-organization) - File structure and migration strategy  
- [Concrete Complex Rule Implementations](#concrete-complex-rule-implementations) - Fight phase examples
- [Real Frontend Integration Challenges](#real-frontend-integration-challenges) - UI data mapping
- [Integration Strategy](#integration-strategy) - Gym and HTTP API patterns
- [Testing Methodology](#testing-methodology) - AI_TURN.md compliance validation
- [Legacy Project Migration](#legacy-project-migration) - Asset preservation strategy
- [Risk Assessment](#risk-assessment-and-fallback-strategies) - Technical and schedule risks
- [Enhanced Development Phases](#enhanced-development-phases-with-concrete-deliverables) - Implementation timeline
- [Success Metrics](#success-metrics) - Validation criteria


## VALIDATION STRATEGY: PROOF-OF-CONCEPT FIRST

### Phase 0: Architecture Validation (Days 1-3)
**Deliverable:** Minimal working implementation proving architecture can handle AI_TURN.md complexity

**Concrete Implementation Test:**
```python
# movement_handlers.py - Concrete AI_TURN.md implementation
def get_eligible_units(game_state, config):
    """
    EXACT implementation of AI_TURN.md movement eligibility decision tree.
    Reference: AI_TURN.md Section 🏃 MOVEMENT PHASE LOGIC
    """
    eligible_units = []
    current_player = game_state["current_player"]
    
    for unit in game_state["units"]:
        # AI_TURN.md: "unit.HP_CUR > 0?"
        if unit["HP_CUR"] <= 0:
            continue  # Dead unit (Skip, no log)
            
        # AI_TURN.md: "unit.player === current_player?"
        if unit["player"] != current_player:
            continue  # Wrong player (Skip, no log)
            
        # AI_TURN.md: "unit.id not in units_moved?"
        if unit["id"] in game_state["units_moved"]:
            continue  # Already moved (Skip, no log)
            
        # AI_TURN.md: Unit passes all conditions
        eligible_units.append(unit)
    
    return eligible_units

def execute_action(game_state, action, config):
    """
    EXACT implementation of AI_TURN.md movement action execution.
    Tests architecture can handle complex rule interactions.
    """
    # Get eligible unit (AI_TURN.md: sequential activation)
    eligible_units = get_eligible_units(game_state, config)
    if not eligible_units:
        return False, {"error": "no_eligible_units"}
    
    active_unit = eligible_units[0]  # ONE unit per gym step
    
    # AI_TURN.md action mapping
    if action == 0:  # Move North
        return _execute_movement(game_state, active_unit, 0, -1, config)
    elif action == 1:  # Move South  
        return _execute_movement(game_state, active_unit, 0, 1, config)
    elif action == 2:  # Move East
        return _execute_movement(game_state, active_unit, 1, 0, config)
    elif action == 3:  # Move West
        return _execute_movement(game_state, active_unit, -1, 0, config)
    elif action == 7:  # Wait
        game_state["units_moved"].add(active_unit["id"])
        return True, {"type": "wait", "unit_id": active_unit["id"]}
    else:
        return False, {"error": "invalid_action_for_phase"}

def _execute_movement(game_state, unit, col_diff, row_diff, config):
    """
    CONCRETE implementation of AI_TURN.md movement restrictions.
    Tests complex rule validation within architecture.
    """
    new_col = unit["col"] + col_diff
    new_row = unit["row"] + row_diff
    
    # AI_TURN.md: Check board bounds
    board_config = config["board"]
    if (new_col < 0 or new_row < 0 or 
        new_col >= board_config["width"] or 
        new_row >= board_config["height"]):
        return False, {"error": "out_of_bounds"}
    
    # AI_TURN.md: Check wall hexes
    if (new_col, new_row) in set(map(tuple, board_config["wall_hexes"])):
        return False, {"error": "wall_collision"}
    
    # AI_TURN.md: Check unit occupation
    for other_unit in game_state["units"]:
        if (other_unit["id"] != unit["id"] and 
            other_unit["HP_CUR"] > 0 and
            other_unit["col"] == new_col and 
            other_unit["row"] == new_row):
            return False, {"error": "hex_occupied"}
    
    # AI_TURN.md: Check for flee (was adjacent before move)
    was_adjacent = _is_adjacent_to_enemy(game_state, unit)
    
    # Execute movement
    unit["col"] = new_col
    unit["row"] = new_row
    
    # AI_TURN.md: Mark fled if applicable
    if was_adjacent and not _is_adjacent_to_enemy(game_state, unit):
        game_state["units_fled"].add(unit["id"])
    
    # AI_TURN.md: Mark as moved
    game_state["units_moved"].add(unit["id"])
    
    return True, {
        "type": "move",
        "unit_id": unit["id"],
        "from": (unit["col"] - col_diff, unit["row"] - row_diff),
        "to": (new_col, new_row),
        "fled": was_adjacent and not _is_adjacent_to_enemy(game_state, unit)
    }

def _is_adjacent_to_enemy(game_state, unit):
    """AI_TURN.md adjacent enemy detection"""
    cc_range = unit.get("CC_RNG", 1)
    
    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0):
            distance = max(abs(unit["col"] - enemy["col"]), 
                          abs(unit["row"] - enemy["row"]))
            if distance <= cc_range:
                return True
    return False
```

**Validation Criteria:**
- Movement rules work exactly per AI_TURN.md specification
- Single source of truth maintained throughout
- No architectural violations under complex rule execution
- Performance adequate for gameplay

**If Phase 0 Fails:** Revise architecture before proceeding

---

## ARCHITECTURE COMPLIANCE

### Single Source of Truth Implementation

**AI_TURN.md Requirement:** "Only one game_state object exists per game"

**Compliant Architecture:**
```python
# w40k_engine.py - ONLY location where game_state exists
class W40KEngine:
    def __init__(self, config):
        self.game_state = {
            "units": [...],
            "current_player": 0,
            "phase": "move",
            "turn": 1,
            "episode_steps": 0,
            "units_moved": set(),
            "units_shot": set(),
            "units_charged": set(),
            "units_attacked": set(),
            "units_fled": set(),
            
            # ADDED: Decision tree state requirements
            "move_activation_pool": [],
            "shoot_activation_pool": [],
            "charge_activation_pool": [],
            "charging_activation_pool": [],
            "active_alternating_activation_pool": [],
            "non_active_alternating_activation_pool": [],
            "valid_target_pool": [],
            "valid_move_destinations_pool": [],
            "valid_charge_destinations_pool": [],
            
            # ADDED: Fight state machine
            "fight_subphase": None,  # "charging_units", "alternating_fight", "cleanup"
            "alternating_fight_turn": "non_active",
            "charge_range_rolls": {},  # unit_id -> 2d6 result
            "attack_left": 0,
            "shoot_left": 0,
            "total_attack_log": "",
            
            "game_over": False,
            "winner": None
        }
        self.config = config
```

**Violation Patterns to Avoid:**
```python
# ❌ VIOLATION: Separate state manager
class GameStateManager:
    def __init__(self):
        self.state = {...}  # Creates second source of truth

# ❌ VIOLATION: Handler with internal state
class MovementHandler:
    def __init__(self):
        self.unit_queue = []  # Duplicates state information

# ❌ VIOLATION: State copying
def process_phase(state_copy):
    temp_state = copy.deepcopy(state_copy)  # State synchronization nightmare
```

**Compliant Patterns:**
```python
# ✅ COMPLIANT: Pure function handlers
def execute_movement_action(game_state, action, config):
    """Implements AI_TURN.md movement decision tree"""
    # Operates directly on passed game_state
    # No internal state storage
    # Returns success/failure only

# ✅ COMPLIANT: Direct state access
if self.game_state["phase"] == "move":
    return movement_handlers.execute_action(self.game_state, action, self.config)
```

### Built-in Step Counting Compliance

**AI_TURN.md Requirement:** "Step counting in ONE location only, not retrofitted"

**Compliant Implementation:**
```python
class W40KEngine:
    def execute_gym_action(self, action):
        # ONLY step counting location in entire codebase
        self.game_state["episode_steps"] += 1
        
        # All other logic flows from here
        return self._process_action(action)
```

**Violation Patterns to Avoid:**
```python
# ❌ VIOLATION: Multiple step counting locations
class MovementHandler:
    def execute(self, state, action):
        state["episode_steps"] += 1  # Duplicate step counting

class ShootingHandler:
    def execute(self, state, action):
        state["episode_steps"] += 1  # Another duplicate
```

### Sequential Activation Compliance

**AI_TURN.md Requirement:** "ONE unit per gym step"

**Compliant Architecture:**
```python
def step(self, action):
    """Built-in gym interface with state machine"""
    self.game_state["episode_steps"] += 1
    return self._process_action(action)

def _process_action(self, action):
    """State machine implementing decision trees"""
    current_phase = self.game_state["phase"]
    
    if current_phase == "move":
        return self._process_movement_phase(action)
    elif current_phase == "shoot":
        return self._process_shooting_phase(action)
    elif current_phase == "charge":
        return self._process_charge_phase(action)
    elif current_phase == "fight":
        return self._process_fight_phase(action)

def _process_movement_phase(self, action):
    """Movement phase with pool management"""
    if not self.game_state["move_activation_pool"]:
        self._build_move_activation_pool()
    
    if not self.game_state["move_activation_pool"]:
        self._advance_to_shooting_phase()
        return self._process_shooting_phase(action)
    
    # ONE unit per gym step
    active_unit_id = self.game_state["move_activation_pool"].pop(0)
    active_unit = self._get_unit_by_id(active_unit_id)
    
    return self._execute_movement_action(active_unit, action)
```

**Violation Patterns to Avoid:**
```python
# ❌ VIOLATION: Multi-unit processing
for unit in eligible_units:
    self._process_unit(unit, action)  # Processes multiple units per step

# ❌ VIOLATION: Batch processing
def process_all_shooting(units):
    for unit in units:
        unit.shoot()  # Not sequential
```

### Phase Completion by Eligibility

**AI_TURN.md Requirement:** "Phases end when no eligible units remain, not arbitrary step counts"

**Compliant Implementation:**
```python
def _advance_phase_if_complete(self):
    """Implements AI_TURN.md phase completion logic"""
    
    # Check eligibility using AI_TURN.md decision trees
    current_phase = self.game_state["phase"]
    
    if current_phase == "move":
        eligible = movement_handlers.get_eligible_units(self.game_state)
    elif current_phase == "shoot":
        eligible = shooting_handlers.get_eligible_units(self.game_state)
    elif current_phase == "charge":
        eligible = charge_handlers.get_eligible_units(self.game_state)
    elif current_phase == "fight":
        eligible = fight_handlers.get_eligible_units(self.game_state)
    
    # Phase ends when NO eligible units remain
    if not eligible:
        self._advance_to_next_phase()
```

**Violation Patterns to Avoid:**
```python
# ❌ VIOLATION: Step-based phase transitions
if self.game_state["episode_steps"] % 20 == 0:
    self._advance_phase()  # Arbitrary step counting

# ❌ VIOLATION: Timer-based transitions
if time.time() - self.phase_start > 30:
    self._advance_phase()  # Time-based, not eligibility-based
```

---

## CODE ORGANIZATION

### Complete File Organization with Legacy Migration Guide

```
project_root/
├── ai/                       # AI training
│   ├── training/                 # 
│   │   ├── evaluator.py          # 
│   │   ├── gym_interface.py      # Gym wrapper for training
│   │   ├── orchestrator.py       # 
│   │   ├── train_w40k.py         # Training script
│   └── models/                   # Trained models

├── engine/                       # Main game engine package
│   ├── init.py                   # Package initialization
│   ├── w40k_engine.py            # Core engine class
│   ├── phase_handlers/           # AI_TURN.md phase implementations
│   │   ├── __init__.py
│   │   ├── movement_handlers.py  # Movement phase logic
│   │   ├── shooting_handlers.py  # Shooting phase logic (future)
│   │   ├── charge_handlers.py    # Charge phase logic (future)
│   │   └── fight_handlers.py     # Fight phase logic (future)
│   └── utils/                    # Engine utilities
│       ├── __init__.py
│       └── validators.py         # Field validation utilities
├── config/                       # Configuration files
├── docs/                          # Documentation
├── frontend/                      # Frontend with direct API calls
│   └── services/
│       └── engineApi.ts           # Pure functions, no classes
├── scripts/                       # Utility scripts
├── services/              # Backend services
│   ├── api_server.py     # Game engine API
│   └── requirements.txt   # Service deps
├── tests/                         # Compliance validation tests
│   ├── __init__.py
│   ├── test_compliance.py
│   └── test_movement.py
├── main.py                        # Entry point script
└── .venv/                         # Virtual environment

# DELETED ENTIRELY:
# wrappers/ directory - architectural violation
# Any wrapper classes - architectural violation
│
├── config/                         # COPIED FROM LEGACY (all files preserved)
│   ├── board_config.json           # Board layout & visualization settings
│   ├── game_config.json            # Game rules & mechanics configuration
│   ├── rewards_config.json         # AI reward system definitions
│   ├── scenario.json               # Default game scenario setup
│   ├── scenario_templates.json     # Scenario generation templates
│   ├── training_config.json        # AI training hyperparameters
│   ├── unit_definitions.json       # Unit stats, abilities, and properties
│   └── unit_registry.json          # Unit type mappings and registry
│
├── frontend/                       # ADAPTED FROM LEGACY
│   ├── public/
│   │   └── config/                 # Frontend config files
│   │       ├── action_definitions.json    # COPIED FROM LEGACY
│   │       ├── board_config.json          # COPIED FROM LEGACY
│   │       └── config.json                # COPIED FROM LEGACY
│   │
│   ├── src/
│   │   ├── components/             # PRESERVED FROM LEGACY (PIXI.js components)
│   │   │   ├── BoardDisplay.tsx            # Main board display component OK
│   │   │   ├── BoardInteractions.tsx       # Board interaction handling
│   │   │   ├── BoardPvp.tsx                # PvP board implementation OK
│   │   │   ├── BoardReplay.tsx             # Replay functionality OK
│   │   │   ├── BoardWithAPI.tsx            # OK
│   │   │   ├── CombatLogComponent.tsx      # Combat logging display
│   │   │   ├── DiceRollComponent.tsx       # Dice roll visualization
│   │   │   ├── ErrorBoundary.tsx           # Error handling wrapper OK
│   │   │   ├── GameBoard.tsx               # Core board component OK
│   │   │   ├── GameController.tsx          # Game control interface OK
│   │   │   ├── GameLog.tsx                 # Action history display OK
│   │   │   ├── GamePageLayout.tsx
│   │   │   ├── GameRightColumn.tsx         # Right panel layout
│   │   │   ├── GameStatus.tsx              # Game state indicators OK
│   │   │   ├── SharedLayout.tsx            # Common layout wrapper OK
│   │   │   ├── SingleShotDisplay.tsx       # Single shot result display
│   │   │   ├── TurnPhaseTracker.tsx        # Turn/phase indicator OK
│   │   │   ├── UnitRenderer.tsx            # Unit visualization engine OK
│   │   │   ├── UnitSelector.tsx            # Unit selection interface
│   │   │   └── UnitStatusTable.tsx         # Unit status overview OK
│   │   │
│   │   ├── constants/
│   │   │   └── gameConfig.ts               # OK
│   │   │
│   │   ├── data/                   # PRESERVED FROM LEGACY
│   │   │   ├── Units.ts                    # Unit data structures
│   │   │   ├── UnitFactory.ts              # REBUILD OK
│   │   │   └── Scenario.ts                 # Scenario definitions
│   │   │useAITurn.ts
│   │   ├── hooks/                  # DO NOT COPY (built for legacy API)
│   │   │   ├── useAIPlayer.ts              # Legacy hook (rebuild needed)
│   │   │   ├── useAITurn.ts                # REBUILD OK
│   │   │   ├── useEngineAPI.ts
│   │   │   ├── useGameActions.ts           # REBUILD OK
│   │   │   ├── useGameConfig.ts            # REBUILD OK
│   │   │   ├── useGameLog.ts               # REBUILD OK
│   │   │   ├── useGameState.ts             # REBUILD OK
│   │   │   └── usePhaseTransition.ts       # REBUILD OK
│   │   │
│   │   ├── pages/                  # PRESERVED FROM LEGACY
│   │   │   ├── HomePage.tsx                # Home page component
│   │   │   ├── GamePage.tsx                # Main game page
│   │   │   ├── PlayerVsAIPage.tsx          # PvE game mode
│   │   │   └── ReplayPage.tsx              # Replay viewer
│   │   │
│   │   ├── roster/                 # PRESERVED FROM LEGACY (complete unit definitions)
│   │   │   ├── SpaceMarine/
│   │   │   │   ├── Classes/
│   │   │   │   │   ├── SpaceMarineInfantryLeaderMeleeElite.ts
│   │   │   │   │   ├── SpaceMarineInfantryTroopMeleeTroop.ts
│   │   │   │   │   └── SpaceMarineInfantryTroopRangedSwarm.ts
│   │   │   │   └── Units/
│   │   │   │       ├── Intercessor.ts
│   │   │   │       ├── AssaultIntercessor.ts
│   │   │   │       └── CaptainGravis.ts
│   │   │   └── Tyranid/
│   │   │       ├── Classes/
│   │   │       │   ├── TyranidInfantryEliteMeleeElite.ts
│   │   │       │   ├── TyranidInfantrySwarmMeleeSwarm.ts
│   │   │       │   └── TyranidInfantrySwarmRangedSwarm.ts
│   │   │       └── Units/
│   │   │           ├── Termagant.ts
│   │   │           ├── Hormagaunt.ts
│   │   │           └── Carnifex.ts
│   │   │
│   │   ├── services/
│   │   │   └── engineApi.ts                # Pure functions only
│   │   │
│   │   ├── types/                  # PRESERVED FROM LEGACY
│   │   │   ├── api.ts                      # API interface definitions OK
│   │   │   ├── game.ts                     # Game state type definitions OK
│   │   │   ├── index.ts                    # Exported type collections OK
│   │   │   └── replay.ts                   # Replay system types
│   │   │
│   │   ├── utils/                  # EVALUATE INDIVIDUALLY
│   │   │   ├── boardClickHandler.ts        # UI event handling (SAFE) OK
│   │   │   ├── gameHelpers.ts              # General utilities (EVALUATE)
│   │   │   ├── probabilityCalculator.ts    # Math utilities (SAFE)
│   │   │   ├── FightSequenceManager.ts    # Fight UI logic (EVALUATE)
│   │   │   └── ShootingSequenceManager.ts  # Shooting UI logic (EVALUATE)
│   │   │
│   │   ├── App.tsx                         # COPIED FROM LEGACY
│   │   ├── App.css                         # COPIED FROM LEGACY
│   │   └── Routes.tsx                      # COPIED FROM LEGACY
│   │
│   │
│   ├── package.json                        # COPIED FROM LEGACY (update dependencies)
│   ├── vite.config.ts                      # COPIED FROM LEGACY
│   └── tsconfig.json                       # COPIED FROM LEGACY
│
├── services/
│   └── api_server.py 
│ 
├── shared/                         # EVALUATE INDIVIDUALLY FROM LEGACY
│   ├── __init__.py
│   ├── gameLogStructure.py                 # Logging structures (Python)
│   ├── gameLogStructure.ts                 # Logging structures (TypeScript)
│   ├── gameLogUtils.py                     # Logging utilities (Python)
│   ├── gameLogUtils.ts                     # Logging utilities (TypeScript)
│   ├── gameMechanics.py                    # Game mechanics (EVALUATE)
│   ├── gameRules.py                        # Game rules (EVALUATE)
│   └── gameRules.ts                        # Game rules (EVALUATE)
│
├── scripts/                        # UTILITIES
│   ├── backup_select.py                    # COPIED FROM LEGACY
│   ├── copy-configs.js                     # COPIED FROM LEGACY
│   ├── test_compliance.py                  # NEW: AI_TURN.md validation
│   ├── migrate_legacy.py                   # NEW: Migration automation
│   └── conflict_checker.py                 # NEW: Naming conflict detection
│
├── tests/                          # NEW TEST SUITE
│   ├── __init__.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_w40k_engine.py
│   │   ├── test_movement_handlers.py
│   │   ├── test_shooting_handlers.py
│   │   ├── test_charge_handlers.py
│   │   └── test_fight_handlers.py
│   │
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_gym_wrapper.py
│   │   └── test_api_wrapper.py
│   │
│   └── compliance/
│       ├── __init__.py
│       ├── test_single_source.py
│       ├── test_step_counting.py
│       ├── test_sequential.py
│       └── test_field_naming.py
│
├── docs/
│   ├── AI_IMPLEMENTATION.md               # Implementation guide
│   ├── AI_TRAINING.md                     # AI Training
│   └── AI_TURN.md                         # Turn sequence specification
│
├── legacy_reference/               # ARCHIVED COMPLETE PREVIOUS PROJECT
│   ├── ai/                                # All legacy AI files (for reference)
│   │   ├── bot_manager.py
│   │   ├── evaluate.py
│   │   ├── game_controller.py
│   │   ├── game_replay_logger.py
│   │   ├── gym40k.py
│   │   ├── multi_agent_trainer.py
│   │   ├── reward_mapper.py
│   │   ├── sequential_game_controller.py
│   │   ├── sequential_activation_engine.py
│   │   ├── scenario_manager.py
│   │   ├── train.py
│   │   ├── unit_manager.py
│   │   ├── unit_registry.py
│   │   ├── use_game_actions.py
│   │   ├── use_game_config.py
│   │   ├── use_game_log.py
│   │   ├── use_game_state.py
│   │   ├── use_phase_transition.py
│   │   └── api/
│   │       └── get_ai_action.py
│   ├── config/                            # Legacy config files (for reference)
│   ├── frontend/                          # Legacy frontend (for reference)
│   ├── shared/                            # Legacy shared files
│   └── scripts/                           # Legacy scripts
│
├── config_loader.py                       # COPIED FROM LEGACY (utility script)
├── requirements.txt                        # NEW: Python dependencies
├── .gitignore                             # NEW: Git ignore patterns
└── README.md                              # NEW: Project documentation
```

### Migration Strategy Summary

#### ✅ SAFE TO COPY DIRECTLY
- **All config/ files** - Pure configuration data
- **All frontend/src/components/** - PIXI.js UI components
- **All frontend/src/types/** - TypeScript definitions
- **All frontend/src/roster/** - Unit definitions
- **All docs/** - Specification documents
- **scripts/backup_select.py** and **scripts/copy-configs.js** - Utility scripts

#### ⚠️ EVALUATE INDIVIDUALLY
- **shared/** files - Check for state management patterns
- **frontend/src/utils/** files - Verify they're pure UI helpers
- **config_loader.py** - Ensure it's a pure utility

#### ❌ DO NOT COPY (Architectural Violations)
- **All ai/** files - These contain the wrapper patterns being eliminated
- **frontend/src/hooks/** - Built for legacy API, need rebuilding

#### 🔧 NEW FILES TO CREATE
- **game_engine/** - Complete new compliant engine
- **wrappers/** - Clean interface layers
- **tests/** - Comprehensive test suite
- **W40KEngineClient.ts** - Frontend adapter for new engine

### Handler Module Pattern

**Each phase handler implements AI_TURN.md specification:**

```python
# movement_handlers.py
"""
Pure functions implementing AI_TURN.md movement phase specification.
References: AI_TURN.md Section 🏃 MOVEMENT PHASE LOGIC
"""

def get_eligible_units(game_state):
    """
    Implements AI_TURN.md movement eligibility decision tree.
    Returns units that can act in movement phase.
    """
    # Direct implementation of AI_TURN.md eligibility logic
    # No state storage, operates on passed game_state

def execute_action(game_state, action, config):
    """
    Implements AI_TURN.md movement action execution.
    Handles move/wait actions per AI_TURN.md specification.
    """
    # Direct implementation of AI_TURN.md movement rules
    # Modifies game_state directly (single source of truth)
    # Returns success/failure result

def validate_movement_destination(game_state, unit, new_col, new_row, config):
    """
    Implements AI_TURN.md movement restrictions.
    Validates destination per AI_TURN.md rules.
    """
    # Implements wall collision, unit occupation, adjacency rules
    # As specified in AI_TURN.md movement restrictions

def detect_flee_action(game_state, unit, old_pos, new_pos):
    """
    Implements AI_TURN.md flee detection logic.
    Marks units as fled per AI_TURN.md specification.
    """
    # Implements AI_TURN.md flee mechanics
    # Updates game_state tracking sets appropriately
```

### No Internal State Pattern

**Handlers must be stateless:**

```python
# w40k_engine.py - Delegation to pure functions
from phase_handlers import movement_handlers, shooting_handlers, charge_handlers, fight_handlers

class W40KEngine:
    def _execute_movement_action(self, unit, action):
        """Delegate to pure function - COMPLIANT"""
        return movement_handlers.execute_action(self.game_state, unit, action, self.config)
    
    def _execute_shooting_action(self, unit, action):
        """Delegate to pure function - COMPLIANT"""
        return shooting_handlers.execute_action(self.game_state, unit, action, self.config)

# phase_handlers/movement_handlers.py - Pure functions only
def execute_action(game_state, unit, action, config):
    """Pure function - no internal state, COMPLIANT"""
    if action == 0:  # Move North
        return _execute_movement(game_state, unit, 0, -1, config)
    elif action == 7:  # Wait
        game_state["units_moved"].add(unit["id"])
        return True, {"type": "wait", "unit_id": unit["id"]}
    else:
        return False, {"error": "invalid_action"}

def get_eligible_units(game_state):
    """Pure function - no internal state, COMPLIANT"""
    return [unit for unit in game_state["units"] if _is_eligible(unit, game_state)]
```

### Configuration Dependency Pattern

**Clean configuration access:**

```python
# ✅ COMPLIANT: Configuration passed as parameter
def validate_destination(game_state, col, row, config):
    board_width = config["board"]["width"]
    wall_hexes = config["board"]["wall_hexes"]
    # Use configuration without storing it

# ❌ VIOLATION: Global configuration state
GLOBAL_CONFIG = {...}  # Creates shared state
def validate_destination(game_state, col, row):
    board_width = GLOBAL_CONFIG["board"]["width"]  # Global dependency
```

---

## CONCRETE COMPLEX RULE IMPLEMENTATIONS

### Fight Phase Sub-Phase Implementation
**The most complex AI_TURN.md rule - concrete implementation:**

```python
# fight_handlers.py - EXACT AI_TURN.md fight sub-phase implementation
def get_eligible_units(game_state, config):
    """
    CONCRETE implementation of AI_TURN.md fight sub-phases.
    Reference: AI_TURN.md Section ⚔️ Fight PHASE LOGIC
    """
    current_player = game_state["current_player"]
    
    # AI_TURN.md: Sub-phase 1 - Charging units first
    charging_units = []
    for unit in game_state["units"]:
        if (unit["HP_CUR"] > 0 and
            unit["player"] == current_player and
            unit["id"] in game_state["units_charged"] and
            unit["id"] not in game_state["units_attacked"] and
            _has_adjacent_enemies(game_state, unit)):
            charging_units.append(unit)
    
    if charging_units:
        return charging_units  # Charging units have priority
    
    # AI_TURN.md: Sub-phase 2 - Alternating fight
    # Non-active player first, then active player
    alternating_units = []
    non_active_player = 1 - current_player
    
    # Non-active player units first
    for unit in game_state["units"]:
        if (unit["HP_CUR"] > 0 and
            unit["player"] == non_active_player and
            unit["id"] not in game_state["units_charged"] and
            unit["id"] not in game_state["units_attacked"] and
            _has_adjacent_enemies(game_state, unit)):
            alternating_units.append(unit)
    
    # Then active player non-charging units
    for unit in game_state["units"]:
        if (unit["HP_CUR"] > 0 and
            unit["player"] == current_player and
            unit["id"] not in game_state["units_charged"] and
            unit["id"] not in game_state["units_attacked"] and
            _has_adjacent_enemies(game_state, unit)):
            alternating_units.append(unit)
    
    return alternating_units

def execute_action(game_state, action, config):
    """CONCRETE fight action execution with multi-attack handling"""
    eligible_units = get_eligible_units(game_state, config)
    if not eligible_units:
        return False, {"error": "no_eligible_units"}
    
    active_unit = eligible_units[0]
    
    if action == 6:  # Attack action
        return _execute_fight_sequence(game_state, active_unit, config)
    else:
        return False, {"error": "invalid_action_for_phase"}

def _execute_fight_sequence(game_state, unit, config):
    """
    CONCRETE multi-attack implementation per AI_TURN.md.
    Tests architecture handles complex sequential logic.
    """
    adjacent_enemies = _get_adjacent_enemies(game_state, unit)
    if not adjacent_enemies:
        return False, {"error": "no_targets"}
    
    attack_results = []
    attacks = unit.get("CC_NB", 1)
    
    for attack_num in range(attacks):
        # Re-check targets (may have died from previous attacks)
        valid_targets = [t for t in adjacent_enemies if t["HP_CUR"] > 0]
        if not valid_targets:
            break  # AI_TURN.md: Slaughter handling
        
        target = valid_targets[0]  # Simple target selection
        attack_result = _resolve_single_attack(unit, target, config)
        attack_results.append(attack_result)
        
        # Apply damage immediately (AI_TURN.md: immediate update)
        if attack_result["damage"] > 0:
            target["HP_CUR"] = max(0, target["HP_CUR"] - attack_result["damage"])
    
    # Mark as attacked
    game_state["units_attacked"].add(unit["id"])
    
    return True, {
        "type": "fight",
        "unit_id": unit["id"],
        "attacks": attack_results,
        "total_damage": sum(r["damage"] for r in attack_results)
    }

def _resolve_single_attack(attacker, target, config):
    """CONCRETE W40K hit/wound/save mechanics"""
    import random
    
    # Hit roll
    hit_roll = random.randint(1, 6)
    hit_success = hit_roll >= attacker.get("CC_ATK", 4)
    
    wound_roll = save_roll = damage = 0
    wound_success = save_success = False
    
    if hit_success:
        # Wound roll
        wound_roll = random.randint(1, 6)
        wound_target = _calculate_wound_target(
            attacker.get("CC_STR", 4), 
            target.get("T", 4)
        )
        wound_success = wound_roll >= wound_target
        
        if wound_success:
            # Save roll
            save_roll = random.randint(1, 6)
            armor_save = target.get("ARMOR_SAVE", 7)
            ap = attacker.get("CC_AP", 0)
            invul_save = target.get("INVUL_SAVE", 7)
            
            save_target = min(armor_save + ap, invul_save)
            save_success = save_roll >= save_target if save_target <= 6 else False
            
            if not save_success:
                damage = attacker.get("CC_DMG", 1)
    
    return {
        "hit_roll": hit_roll,
        "hit_success": hit_success,
        "wound_roll": wound_roll,
        "wound_success": wound_success,
        "save_roll": save_roll,
        "save_success": save_success,
        "damage": damage
    }

def _calculate_wound_target(strength, toughness):
    """W40K wound chart implementation"""
    if strength >= 2 * toughness:
        return 2
    elif strength > toughness:
        return 3
    elif strength == toughness:
        return 4
    elif strength * 2 <= toughness:
        return 6
    else:
        return 5
```

**This proves the architecture can handle AI_TURN.md's most complex rules.**

---

## REAL FRONTEND INTEGRATION CHALLENGES

### Concrete Data Structure Mapping
**Address actual integration complexity:**

```typescript
// engineApi.ts - Pure functions, no wrapper class
export async function executeAction(action: number): Promise<GameState> {
    const response = await fetch('/api/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
    });
    
    if (!response.ok) {
        throw new Error(`Action failed: ${response.status}`);
    }
    
    return await response.json();
}

export async function startGame(config?: any): Promise<GameState> {
    const response = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config })
    });
    
    return await response.json();
}

// Usage in components - direct function calls
import { executeAction, startGame } from '../services/engineApi';
const result = await executeAction(action);
    
    private mapLegacyActionToEngine(legacyAction: LegacyAction): number {
        // CONCRETE mapping with validation
        const actionMap: Record<string, number> = {
            "MOVE_NORTH": 0,
            "MOVE_SOUTH": 1,
            "MOVE_EAST": 2,
            "MOVE_WEST": 3,
            "SHOOT": 4,
            "CHARGE": 5,
            "WAIT": 7,
            "ATTACK": 6
        };
        
        if (legacyAction.type in actionMap) {
            return actionMap[legacyAction.type];
        }
        
        // Handle complex legacy actions that need conversion
        if (legacyAction.type === "MOVE_TO_HEX") {
            return this.convertMoveToHexToDirectional(legacyAction);
        }
        
        throw new Error(`Unknown legacy action: ${legacyAction.type}`);
    }
    
    private adaptEngineStateToLegacyFormat(engineState: any): LegacyGameState {
        // CONCRETE field mapping with validation
        return {
            // Direct mappings
            units: engineState.units,
            phase: engineState.phase,
            gameOver: engineState.game_over,
            winner: engineState.winner,
            
            // Field name conversions
            currentPlayer: engineState.current_player,  // snake_case to camelCase
            currentTurn: engineState.turn,              // Different field name
            
            // Legacy-specific fields that need calculation
            availableActions: this.calculateAvailableActions(engineState),
            phaseProgress: this.calculatePhaseProgress(engineState),
            
            // Handle missing legacy fields
            lastAction: this.reconstructLastAction(engineState),
            
            // Training-specific fields (may not exist in legacy)
            episodeSteps: engineState.episode_steps || 0,
        };
    }
    
    private calculateAvailableActions(engineState: any): string[] {
        // CONCRETE calculation - Legacy UI expects this field
        const phase = engineState.phase;
        const actions = [];
        
        if (phase === "move") {
            actions.push("MOVE_NORTH", "MOVE_SOUTH", "MOVE_EAST", "MOVE_WEST", "WAIT");
        } else if (phase === "shoot") {
            actions.push("SHOOT", "WAIT");
        } else if (phase === "charge") {
            actions.push("CHARGE", "WAIT");
        } else if (phase === "fight") {
            actions.push("ATTACK", "WAIT");
        }
        
        return actions;
    }
    
    private convertMoveToHexToDirectional(action: any): number {
        // CONCRETE conversion for complex legacy actions
        const currentUnit = this.getCurrentActiveUnit();
        const targetCol = action.targetHex.col;
        const targetRow = action.targetHex.row;
        
        const colDiff = targetCol - currentUnit.col;
        const rowDiff = targetRow - currentUnit.row;
        
        // Convert to directional movement
        if (colDiff > 0) return 2; // MOVE_EAST
        if (colDiff < 0) return 3; // MOVE_WEST  
        if (rowDiff > 0) return 1; // MOVE_SOUTH
        if (rowDiff < 0) return 0; // MOVE_NORTH
        
        return 7; // WAIT if no movement
    }
}

// CONCRETE interface definitions for legacy compatibility
interface LegacyAction {
    type: string;
    unitId?: string;
    targetHex?: { col: number; row: number };
    targetUnitId?: string;
}

interface LegacyGameState {
    units: any[];
    currentPlayer: number;
    currentTurn: number;
    phase: string;
    gameOver: boolean;
    winner?: number;
    availableActions: string[];
    phaseProgress: number;
    lastAction?: any;
    episodeSteps: number;
}
```

---

## INTEGRATION STRATEGY

### Gym Integration Without Violations

**Clean wrapper pattern:**

```python
# w40k_engine.py - ONLY file needed, no wrappers
class W40KEngine:
    def __init__(self, config):
        self.game_state = {...}  # Single source of truth
        self.config = config
    
    def step(self, action):
        """Built-in gym interface - eliminates wrapper class"""
        self.game_state["episode_steps"] += 1
        success, result = self._process_action(action)
        
        obs = self._build_observation()
        reward = self._calculate_reward(success, result)
        terminated = self.game_state["game_over"]
        
        return obs, reward, terminated, False, {}
    
    def api_action(self, action):
        """Built-in HTTP interface - eliminates wrapper class"""
        success, result = self.step(action)
        return {
            "success": success,
            "result": result,
            "game_state": self.game_state
        }
    
    def _build_observation(self):
        """Convert engine game_state to observation vector"""
        # Read from engine.game_state (no state copying)
        return self._state_to_vector(self.engine.game_state)
    
    def reset(self, config=None):
        if config:
            self.engine = W40KEngine(config)  # New engine instance
        else:
            self.engine._reset_game_state()   # Reset existing engine
        
        return self._build_observation(), {}
```

**Violation patterns to avoid:**

```python
# ❌ VIOLATION: State synchronization
class W40KGymEnv:
    def __init__(self, config):
        self.engine = W40KEngine(config)
        self.gym_state = copy.deepcopy(self.engine.game_state)  # State duplication
    
    def step(self, action):
        result = self.engine.execute_gym_action(action)
        self._sync_gym_state()  # Synchronization complexity
```

### HTTP API Integration

**Clean REST interface:**

```python
# api_wrapper.py
"""Clean HTTP interface - stateless requests"""

from fastapi import FastAPI
from game_engine.w40k_engine import W40KEngine

app = FastAPI()

# Single engine with session state in game_state
engine = W40KEngine(config)
# Session management through engine.game_state["session_id"]

@app.post("/api/start/{session_id}")
async def start_game(session_id: str, config: dict):
    """Start new game session"""
    active_engines[session_id] = W40KEngine(config)
    return {"game_state": active_engines[session_id].game_state}

@app.post("/api/action/{session_id}")
async def execute_action(session_id: str, request: dict):
    """Execute action in session"""
    engine = active_engines.get(session_id)
    if not engine:
        raise HTTPException(404, "Session not found")
    
    action = request["action"]
    success, result = engine.execute_gym_action(action)
    
    return {
        "success": success,
        "result": result,
        "game_state": engine.game_state  # Direct state access
    }
```

---

## TESTING METHODOLOGY

### AI_TURN.md Compliance Validation

**Daily compliance tests:**

```python
# test_compliance.py
"""AI_TURN.md compliance validation suite"""

def test_single_source_of_truth():
    """Test only one game_state object exists"""
    engine = W40KEngine(create_test_config())
    
    # Verify no other state storage
    assert hasattr(engine, 'game_state')
    assert not hasattr(engine, 'state_manager')
    assert not hasattr(engine, 'cached_state')
    
    # State object should remain consistent
    original_state_id = id(engine.game_state)
    for _ in range(10):
        engine.execute_gym_action(7)  # Wait actions
    assert id(engine.game_state) == original_state_id

def test_built_in_step_counting():
    """Test step counting in ONE location only"""
    engine = W40KEngine(create_test_config())
    
    initial_steps = engine.game_state["episode_steps"]
    
    # Each gym action should increment by exactly 1
    for i in range(5):
        engine.execute_gym_action(7)
        expected_steps = initial_steps + i + 1
        assert engine.game_state["episode_steps"] == expected_steps

def test_sequential_activation():
    """Test ONE unit per gym step"""
    engine = W40KEngine(create_multi_unit_config())
    
    # Track unit actions per step
    initial_moved = len(engine.game_state["units_moved"])
    
    # Single gym action should affect at most one unit
    engine.execute_gym_action(2)  # Movement action
    final_moved = len(engine.game_state["units_moved"])
    
    assert final_moved <= initial_moved + 1

def test_phase_completion_by_eligibility():
    """Test phases end when no eligible units remain"""
    engine = W40KEngine(create_single_unit_config())
    
    # Start in movement phase
    assert engine.game_state["phase"] == "move"
    
    # Move the only unit
    engine.execute_gym_action(2)
    
    # Should advance to next phase (no more eligible units)
    assert engine.game_state["phase"] != "move"

def test_uppercase_field_validation():
    """Test all unit fields use proper naming"""
    engine = W40KEngine(create_test_config())
    
    for unit in engine.game_state["units"]:
        # Required UPPERCASE fields must exist
        assert "HP_CUR" in unit
        assert "HP_MAX" in unit
        
        # No lowercase stat fields allowed
        stat_fields = [k for k in unit.keys() if "_" in k]
        for field in stat_fields:
            if field not in ["unitType"]:  # Exception for camelCase
                assert field.isupper() or field in ["id", "player", "col", "row"]

def test_zero_wrapper_patterns():
    """Test no wrapper/delegation chains exist"""
    engine = W40KEngine(create_test_config())
    
    # Engine should not delegate to other controllers
    assert not hasattr(engine, 'base_controller')
    assert not hasattr(engine, 'delegate')
    assert not hasattr(engine, 'wrapper')
    
    # Handlers should be pure functions, not objects
    from game_engine.phase_handlers import movement_handlers
    assert callable(movement_handlers.execute_action)
    assert not hasattr(movement_handlers, 'state')

def run_full_compliance_suite():
    """Run all compliance tests"""
    test_single_source_of_truth()
    test_built_in_step_counting()
    test_sequential_activation()
    test_phase_completion_by_eligibility()
    test_uppercase_field_validation()
    test_zero_wrapper_patterns()
    
    print("✅ Full AI_TURN.md compliance validated")
```

### AI_TURN.md Rule Implementation Validation

**Test handlers implement AI_TURN.md specification correctly:**

```python
def test_movement_phase_implementation():
    """Test movement handlers implement AI_TURN.md movement logic"""
    engine = W40KEngine(create_movement_test_config())
    
    # Test AI_TURN.md movement eligibility logic
    from game_engine.phase_handlers import movement_handlers
    
    # Should implement exact AI_TURN.md eligibility decision tree
    eligible_units = movement_handlers.get_eligible_units(engine.game_state)
    
    # Validate each eligibility condition from AI_TURN.md
    for unit in eligible_units:
        assert unit["HP_CUR"] > 0  # AI_TURN.md requirement
        assert unit["player"] == engine.game_state["current_player"]  # AI_TURN.md requirement
        assert unit["id"] not in engine.game_state["units_moved"]  # AI_TURN.md requirement

def test_shooting_phase_implementation():
    """Test shooting handlers implement AI_TURN.md shooting logic"""
    # Test AI_TURN.md shooting eligibility conditions
    # Test multi-shot mechanics per AI_TURN.md
    # Test target validation per AI_TURN.md
    pass

def test_charge_phase_implementation():
    """Test charge handlers implement AI_TURN.md charge logic"""
    # Test 2D6 roll timing per AI_TURN.md
    # Test pathfinding requirements per AI_TURN.md
    # Test charge priority mechanics per AI_TURN.md
    pass

def test_fight_phase_implementation():
    """Test fight handlers implement AI_TURN.md fight logic"""
    # Test sub-phase ordering per AI_TURN.md
    # Test alternating fight per AI_TURN.md
    # Test charging unit priority per AI_TURN.md
    pass
```

### Integration Testing

**Test wrappers maintain compliance:**

```python
def test_no_wrapper_violations():
    """Test engine works without any wrappers"""
    engine = W40KEngine(config)
    obs, reward, done, truncated, info = engine.step(action) 
    
    env = W40KGymEnv(create_test_config())
    
    # Wrapper should not duplicate state
    assert not hasattr(env, 'cached_state')
    assert not hasattr(env, 'internal_state')
    
    # State should come from engine only
    initial_state_id = id(env.engine.game_state)
    obs, reward, done, truncated, info = env.step(7)
    assert id(env.engine.game_state) == initial_state_id

def test_api_wrapper_compliance():
    """Test API wrapper doesn't violate compliance"""
    # Test stateless request handling
    # Test no state caching
    # Test direct engine delegation
    pass
```

### Performance Validation

**Ensure compliance doesn't hurt performance:**

```python
def test_performance_impact():
    """Test compliance architecture performs adequately"""
    engine = W40KEngine(create_large_test_config())
    
    import time
    start_time = time.time()
    
    # Execute 1000 actions
    for _ in range(1000):
        engine.execute_gym_action(7)
    
    elapsed = time.time() - start_time
    
    # Should handle 1000 actions in reasonable time
    assert elapsed < 1.0  # Adjust based on requirements
```

---

## LEGACY PROJECT MIGRATION

### Asset Preservation Strategy

**Before starting new development, systematically evaluate existing project files for AI_TURN.md compliance.**

#### ✅ SAFE TO COPY (Pure Assets & Configuration)

**Documentation & Specifications:**
```
AI_IMPLEMENTATION.md
AI_TRAINING.md
AI_TURN.md
```
**Rationale:** Specification documents - essential for maintaining compliance standards

**Configuration Files:**
```
config/board_config.json
config/game_config.json
config/rewards_config.json
config/scenario.json
config/scenario_templates.json
config/training_config.json
config/unit_definitions.json
config/unit_registry.json
```
**Rationale:** Pure data definitions, no architectural dependencies

**Frontend UI Components:**
```
frontend/src/components/BoardDisplay.tsx
frontend/src/components/BoardPvp.tsx
frontend/src/components/GameBoard.tsx
frontend/src/components/UnitRenderer.tsx
frontend/src/components/TurnPhaseTracker.tsx
frontend/src/components/GameStatus.tsx
frontend/src/components/ErrorBoundary.tsx
```
**Rationale:** PIXI.js UI layer - will adapt to new compliant API

**Frontend Data & Types:**
```
frontend/src/types/game.ts
frontend/src/types/api.ts
frontend/src/data/Units.ts
frontend/src/roster/ (all unit definitions)
```
**Rationale:** Type definitions and unit data - pure configuration

**Development Utilities:**
```
scripts/backup_select.py
scripts/copy-configs.js
```
**Rationale:** Pure utility functions, no game logic dependencies

#### ❌ COMPLIANCE VIOLATIONS (Do Not Copy)

**AI Controllers & State Managers:**
```
ai/game_controller.py
ai/sequential_game_controller.py  # Even if "largely compliant"
ai/sequential_activation_engine.py
ai/bot_manager.py
ai/unit_manager.py
ai/use_game_actions.py
ai/use_game_state.py
ai/use_phase_transition.py
```
**Rationale:** These implement the exact wrapper/delegation patterns being eliminated

**Current Integration Wrappers:**
```
ai/gym40k.py  # Built around non-compliant architecture
ai/api/get_ai_action.py
ai/train.py
ai/evaluate.py
```
**Rationale:** Designed for current non-compliant system architecture

**Frontend State Management Hooks:**
```
frontend/src/hooks/useGameState.ts
frontend/src/hooks/useGameActions.ts
frontend/src/hooks/usePhaseTransition.ts
```
**Rationale:** Built around current API, may contain embedded violations

#### 🔍 EVALUATE INDIVIDUALLY

**Utility Libraries:**
```
config_loader.py  # Check: Pure utility or state management?
ai/reward_mapper.py  # Check: Pure calculation or embedded logic?
shared/gameLogStructure.py  # Check: Data structures or logic?
```

**Frontend Services:**
```
frontend/src/services/aiService.ts  # Check: API client or game logic?
frontend/src/utils/gameHelpers.ts  # Check: Pure helpers or state?
```

### NAMING CONFLICT IDENTIFICATION SYSTEM

**To identify naming conflicts during implementation:**

```python
# conflict_checker.py - Development utility
def check_naming_conflicts(new_engine_file: str, legacy_files: List[str]):
    """
    Compare function/class names between new engine and legacy files.
    Identify potential conflicts before implementation.
    """
    
    # Extract names from new engine
    new_names = extract_function_names(new_engine_file)
    
    # Extract names from legacy files  
    legacy_names = {}
    for file_path in legacy_files:
        legacy_names[file_path] = extract_function_names(file_path)
    
    # Find conflicts
    conflicts = []
    for new_name in new_names:
        for legacy_file, legacy_file_names in legacy_names.items():
            if new_name in legacy_file_names:
                conflicts.append({
                    "name": new_name,
                    "new_location": new_engine_file,
                    "legacy_location": legacy_file,
                    "risk": "HIGH" if is_core_function(new_name) else "LOW"
                })
    
    return conflicts

# Example usage during development:
conflicts = check_naming_conflicts(
    "game_engine/w40k_engine.py",
    ["ai/game_controller.py", "ai/use_game_state.py", "frontend/src/hooks/useGameState.ts"]
)

for conflict in conflicts:
    print(f"⚠️ CONFLICT: {conflict['name']} exists in both {conflict['new_location']} and {conflict['legacy_location']}")
```

### Migration Execution Plan

```bash
# 1. Create new project structure
mkdir w40k_compliant_engine
cd w40k_compliant_engine

# 2. Copy safe assets immediately
cp -r ../legacy_project/config/ ./
cp ../legacy_project/AI_*.md ./
cp -r ../legacy_project/frontend/src/types/ ./frontend/src/
cp -r ../legacy_project/frontend/src/roster/ ./frontend/src/
cp -r ../legacy_project/frontend/src/components/Board*.tsx ./frontend/src/components/

# 3. Evaluate utilities individually (manual review required)
# Copy only after confirming no state management or wrapper patterns

# 4. Rebuild all AI controllers from scratch using Implementation 3 architecture
# Never copy existing controllers - they contain the violations being eliminated
```

### Legacy Reference Preservation

```bash
# Archive current project for reference
mv current_project w40k_legacy_reference

# Keep available for:
# - UI component patterns (not the code, but the interface design)
# - Configuration examples
# - Feature requirements understanding
# - Performance benchmarks
```

---

## RISK ASSESSMENT AND FALLBACK STRATEGIES

### Technical Risks

**Risk 1: Architecture Cannot Handle AI_TURN.md Complexity**
- **Probability**: Medium
- **Impact**: Project restart required
- **Mitigation**: Phase 0 validation catches this early
- **Fallback**: Modify architecture or accept some violations

**Risk 2: Frontend Integration Breaks Existing UI**
- **Probability**: High  
- **Impact**: User experience degradation
- **Mitigation**: Parallel system during transition
- **Fallback**: Keep legacy system, build new UI

**Risk 3: Performance Inadequate for Training**
- **Probability**: Low
- **Impact**: AI training slowdown
- **Mitigation**: Performance testing in each phase
- **Fallback**: Optimize critical paths, accept some violations

### Schedule Risks

**Risk 4: Complex Rules Take Longer Than Estimated**
- **Probability**: High
- **Impact**: Timeline extension
- **Mitigation**: Phase 0 provides realistic estimates
- **Fallback**: Implement core rules first, add complexity later

**Risk 5: Integration Complexity Underestimated**  
- **Probability**: Medium
- **Impact**: Timeline extension
- **Mitigation**: Concrete integration planning
- **Fallback**: Simplified adapter, accept some UI limitations

### Quality Risks

**Risk 6: Subtle AI_TURN.md Violations Introduced**
- **Probability**: Medium
- **Impact**: Compliance failure
- **Mitigation**: Continuous compliance testing
- **Fallback**: Accept minor violations, document them

---

## ENHANCED DEVELOPMENT PHASES WITH CONCRETE DELIVERABLES

### Phase 0: Architecture Validation (Days 1-3)
**Deliverable:** Proof-of-concept with movement phase only
- ✅ Movement handlers implement AI_TURN.md exactly
- ✅ Architecture handles complex rule validation
- ✅ Single source of truth maintained
- ✅ No performance issues detected

**Success Criteria:** All AI_TURN.md movement rules work correctly within architecture

### Phase 1: Core Engine Foundation (Days 4-7)
**Deliverable:** Complete engine with movement + basic compliance tests
- Add shooting handlers with multi-shot logic
- Implement phase transition logic
- Build comprehensive compliance test suite
- Validate sequential activation under load

### Phase 2: Complex Mechanics (Days 8-14)
**Deliverable:** Full W40K mechanics with AI_TURN.md compliance
- Implement charge handlers with 2D6 rolls and pathfinding
- Implement fight handlers with sub-phases and alternating logic
- Validate all complex rule interactions
- Performance testing with large scenarios

### Phase 3: Integration Layer (Days 15-18)
**Deliverable:** Working gym and API wrappers
- Build compliant gym wrapper for AI training
- Build HTTP API wrapper for frontend
- Test integration maintains compliance
- Performance optimization

### Phase 4: Frontend Adaptation (Days 19-21)
**Deliverable:** Frontend working with new engine
- Implement W40KEngineClient adapter
- Test all legacy UI functionality
- Handle integration edge cases
- End-to-end system validation

---

## SUCCESS METRICS

### Phase 0 Success (Critical)
- ✅ Movement phase works exactly per AI_TURN.md specification
- ✅ Architecture shows no violations under testing
- ✅ Performance acceptable (1000 actions < 1 second)

### Full Implementation Success
- ✅ All AI_TURN.md rules implemented correctly
- ✅ Zero architectural violations in compliance tests
- ✅ Legacy UI functionality preserved
- ✅ AI training performance maintained or improved

### Failure Conditions
- ❌ Phase 0 reveals architectural inadequacy
- ❌ Integration breaks core UI functionality  
- ❌ Performance degradation > 50%
- ❌ AI_TURN.md violations persist after implementation

This complete enhanced plan provides concrete implementation examples, addresses real integration challenges, includes comprehensive risk assessment, and preserves all valuable migration strategy and file organization details from the original document.