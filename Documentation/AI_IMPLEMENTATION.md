# AI_TURN.md Compliant Architecture - Implementation Plan

## EXECUTIVE SUMMARY

This document describes the current modular architecture of the W40K game engine. The engine implements AI_TURN.md compliance rules while maintaining clean separation of concerns across specialized modules.

**Core Principle:** Single source of truth (game_state) with pure delegation to specialized modules.

---

## 📋 NAVIGATION

- [Architecture Compliance](#architecture-compliance)
- [Code Organization](#code-organization)
  - [w40k_core.py](#w40k_corepy---core-engine)
  - [game_state.py](#game_statepy---state-management)
  - [game_utils.py](#game_utilspy---pure-utilities)
  - [observation_builder.py](#observation_builderpy---observation-construction)
  - [reward_calculator.py](#reward_calculatorpy---reward-computation)
  - [action_decoder.py](#action_decoderpy---action-masking--decoding)
  - [combat_utils.py](#combat_utilspy---combat-calculations)
  - [pve_controller.py](#pve_controllerpy---pve-ai-opponent)
  - [phase_handlers/](#phase_handlers---phase-specific-logic)
- [How Everything Works Together](#how-everything-works-together)
  - [Complete Request Flow](#complete-request-flow-agentstepaction)
  - [Episode Lifecycle](#complete-episode-lifecycle)
  - [Data Flow](#data-flow-game_state-through-modules)
  - [Phase Transitions](#phase-transition-flow)
  - [Integration Points](#integration-points)
- [Performance Optimizations](#performance-optimizations)
- [Success Metrics](#success-metrics)
- [Related Documentation](#related-documentation)
- [Summary](#summary)

---

## ARCHITECTURE COMPLIANCE

### Single Source of Truth

The `game_state` dictionary exists only in `W40KEngine` (in `w40k_core.py`). All other modules receive it as a parameter and never copy or cache state.

### Sequential Unit Activation

One unit processes per gym step. Phase-specific activation pools (`move_activation_pool`, `shoot_activation_pool`) maintain the queue. The engine processes the first unit in the current pool.

### Built-in Step Counting

Episode steps counted in `w40k_core.py` only. The `step()` method increments `game_state["episode_steps"]` at the start of each step.

### Phase Completion by Eligibility

Phases advance when activation pools are empty. No arbitrary step counting. The engine checks pool status after each action.

### UPPERCASE Field Validation

All unit stats use UPPERCASE naming (`HP_CUR`, `ARMOR_SAVE`, `RNG_ATK`, `CC_STR`, etc.). Module `game_state.py` validates fields on unit initialization via `validate_uppercase_fields()`.

### Zero Wrapper Patterns

`W40KEngine` directly implements `gym.Env`. No wrapper classes that might copy state.

---

## CODE ORGANIZATION

### File Structure

```
ai/engine/
├── w40k_core.py              # Core engine (gym.Env)
├── game_state.py             # State initialization & validation
├── game_utils.py             # Pure utility functions
├── observation_builder.py   # Observation construction
├── reward_calculator.py     # Reward computation
├── action_decoder.py        # Action masking & decoding
├── combat_utils.py          # Combat calculations
├── pve_controller.py        # PvE AI opponent
└── phase_handlers/          # Phase-specific logic
    ├── movement_handlers.py
    ├── shooting_handlers.py
    ├── charge_handlers.py
    └── fight_handlers.py
```

### w40k_core.py - Core Engine

**Class:** `W40KEngine(gym.Env)`

**Key Methods:**
- `__init__()` - Initialize engine, create game_state, instantiate modules
- `reset()` - Start new episode, return initial observation
- `step(action)` - Execute action, return (obs, reward, done, truncated, info)
- `execute_semantic_action()` - Process semantic actions from API
- `execute_ai_turn()` - Handle PvE AI player turns
- `validate_compliance()` - Check AI_TURN.md compliance

**Phase Processing:**
- `_process_movement_phase()` - Delegate to movement_handlers
- `_process_shooting_phase()` - Delegate to shooting_handlers
- `_process_charge_phase()` - Delegate to charge_handlers
- `_process_fight_phase()` - Delegate to fight_handlers

**Phase Initialization:**
- `_movement_phase_init()` - Build move_activation_pool
- `_shooting_phase_init()` - Build shoot_activation_pool
- `_charge_phase_init()` - Build charge_activation_pool
- `_fight_phase_init()` - Build fight activation pools

**Game Flow:**
- `_advance_to_fight_phase()` - Transition move→shoot→charge→fight
- `_advance_to_next_player()` - Switch players, reset tracking
- `_tracking_cleanup()` - Clear phase tracking sets
- `_check_game_over()` - Check win conditions
- `_determine_winner()` - Determine winner or draw

**Delegation Methods:**
- `get_action_mask()` → `action_decoder.get_action_mask()`
- `_build_observation()` → `obs_builder.build_observation()`
- `_calculate_reward()` → `reward_calculator.calculate_reward()`
- `_convert_gym_action()` → `action_decoder.convert_gym_action()`
- `_initialize_units()` → `state_manager.initialize_units()`

**Responsibilities:**
- Owns the single game_state dictionary
- Implements gym.Env interface (reset/step)
- Orchestrates phase flow
- Delegates to specialized modules
- Manages episode lifecycle

---

### game_state.py - State Management

**Class:** `GameStateManager`

**Key Methods:**
- `__init__(config, unit_registry)` - Initialize manager
- `initialize_units(game_state)` - Create units from config
- `create_unit(config)` - Build single unit with UPPERCASE fields
- `validate_uppercase_fields(unit)` - Enforce field naming
- `load_units_from_scenario(scenario_file, unit_registry)` - Load from JSON
- `get_unit_by_id(unit_id, game_state)` - Lookup unit
- `check_game_over(game_state)` - Check elimination/turn limit
- `determine_winner(game_state)` - Calculate winner (-1 for draw)

**Responsibilities:**
- Initialize game state structure
- Create and validate units
- Enforce UPPERCASE field naming
- Load units from scenario files
- Check game-over conditions

---

### game_utils.py - Pure Utilities

**Functions:**
- `get_unit_by_id(unit_id, game_state)` - Lookup unit by ID

**Responsibilities:**
- Pure utility functions with no side effects
- No dependencies on other modules
- Simple lookups only

---

### observation_builder.py - Observation Construction

**Class:** `ObservationBuilder`

**Key Methods:**
- `__init__(config)` - Initialize with perception radius
- `build_observation(game_state)` - Build 150-float egocentric observation
- `_get_active_unit_for_observation(game_state)` - Get unit to observe from
- `_encode_directional_terrain(obs, active_unit, game_state, base_idx)` - Terrain encoding
- `_encode_allied_units(obs, active_unit, game_state, base_idx)` - Allied units (relative coords)
- `_encode_enemy_units(obs, active_unit, game_state, base_idx)` - Enemy units (relative coords)
- `_encode_valid_targets(obs, active_unit, game_state, base_idx)` - Target selection data

**Tactical Feature Calculations:**
- `_calculate_combat_mix_score(unit)` - Ranged vs melee preference (0.1-0.9)
- `_calculate_expected_damage()` - Expected damage calculation
- `_calculate_favorite_target(unit)` - Preferred target type encoding
- `_calculate_movement_direction(unit)` - Recent movement vector
- `_calculate_kill_probability(shooter, target)` - Chance to kill target
- `_calculate_danger_probability(defender, attacker)` - Threat assessment
- `_calculate_army_weighted_threat(target, valid_targets)` - Army-wide threat priority
- `_calculate_target_type_match(active_unit, target)` - Target type match score

**Utility Methods:**
- `_check_los_cached(shooter, target, game_state)` - Line of sight with cache
- `_can_melee_units_charge_target(target, game_state)` - Charge possibility check
- `_find_nearest_in_direction(unit, dx, dy, game_state)` - Directional search
- `_encode_defensive_type(unit)` - Defensive capability encoding

**Responsibilities:**
- Construct 150-float egocentric observations
- Encode relative positions (perception radius R=25)
- Calculate tactical features
- Use LoS cache when available
- Provide fog-of-war observations

---

### reward_calculator.py - Reward Computation

**Class:** `RewardCalculator`

**Key Methods:**
- `__init__(config, rewards_config, unit_registry)` - Initialize with reward config
- `calculate_reward(success, result, game_state)` - Main reward calculation
- `calculate_reward_from_config(acting_unit, action, success, game_state)` - Config-based rewards
- `_get_unit_reward_config(unit)` - Get unit-specific reward values
- `_get_situational_reward(game_state)` - Win/loss/draw rewards
- `_get_system_penalties()` - Load penalty values from config
- `_build_tactical_context(unit, result, game_state)` - Contextual data for rewards

**Tactical Assessments (mirrors observation_builder):**
- `_calculate_combat_mix_score(unit)` - Combat preference score
- `_calculate_expected_damage()` - Expected damage calculations
- `_calculate_favorite_target(unit)` - Target preference
- `_calculate_movement_direction(unit)` - Movement tracking
- `_calculate_kill_probability(shooter, target)` - Kill chance
- `_calculate_danger_probability(defender, attacker)` - Threat level
- `_calculate_army_weighted_threat(target, valid_targets)` - Army threat
- `_calculate_target_type_match(active_unit, target)` - Target matching

**Movement Bonuses:**
- `_moved_to_cover_from_enemies()` - Bonus for defensive positioning
- `_moved_closer_to_enemies()` - Bonus for aggressive advance
- `_moved_away_from_enemies()` - Penalty for retreat without reason
- `_moved_to_optimal_range()` - Bonus for weapon range positioning
- `_moved_to_charge_range()` - Bonus for charge setup
- `_moved_to_safety()` - Bonus for escaping danger
- `_gained_los_on_priority_target()` - Bonus for tactical positioning
- `_safe_from_enemy_charges()` - Bonus for charge avoidance
- `_safe_from_enemy_ranged()` - Bonus for ranged threat avoidance

**Reward Mapper Integration:**
- `_get_reward_mapper()` - Access shared reward_mapper
- `_enrich_unit_for_reward_mapper(unit)` - Add tactical features to unit
- `_get_reward_mapper_unit_rewards(unit)` - Get unit-specific rewards
- `_get_reward_config_key_for_unit(unit)` - Map unit to reward config key

**Responsibilities:**
- Calculate rewards using rewards_config.json
- Track reward breakdowns for metrics
- Apply system penalties (invalid actions, forbidden actions)
- Calculate situational rewards (win/loss/draw)
- Integrate with reward_mapper for unit-specific rewards
- Provide tactical bonuses for good positioning

---

### action_decoder.py - Action Masking & Decoding

**Class:** `ActionDecoder`

**Key Methods:**
- `__init__(config)` - Initialize decoder
- `get_action_mask(game_state)` - Return boolean mask (12 actions)
- `convert_gym_action(action, game_state)` - Convert int→semantic action
- `_get_valid_actions_for_phase(phase)` - Get valid action IDs for phase
- `_get_eligible_units_for_current_phase(game_state)` - Get units from activation pool
- `get_all_valid_targets(unit, game_state)` - Get all possible targets
- `can_melee_units_charge_target(target, game_state)` - Check charge possibility

**Action Space (12 actions):**
- 0-3: Movement (N/S/E/W directions)
- 4-8: Shoot (target slots 0-4)
- 9: Charge
- 10: Fight
- 11: Wait

**Masking Logic:**
- Movement phase: Actions 0-3, 11 valid
- Shooting phase: Actions 4-8 (dynamically based on available targets), 11 valid
- Charge phase: Actions 9, 11 valid
- Fight phase: Action 10 valid only (NO wait in fight)

**Responsibilities:**
- Compute action masks (prevent invalid actions)
- Convert gym integer actions to semantic actions
- Validate actions against phase and available targets
- Handle target slot mapping for shooting
- Enforce phase-specific action restrictions

---

### combat_utils.py - Combat Calculations

**Pure Functions:**
- `calculate_hex_distance(col1, row1, col2, row2)` - Cube coordinate hex distance
- `get_hex_line(start_col, start_row, end_col, end_row)` - Hex line for LoS
- `has_line_of_sight(shooter, target, game_state)` - LoS check via handlers
- `check_los_cached(shooter, target, game_state)` - LoS with cache lookup
- `calculate_wound_target(strength, toughness)` - W40K wound chart
- `has_valid_shooting_targets(unit, game_state)` - Check if unit can shoot
- `is_valid_shooting_target(shooter, target, game_state)` - Validate specific target

**Responsibilities:**
- Pure calculation functions for combat
- Hex distance and line-of-sight calculations
- W40K wound table implementation
- Delegation to phase handlers for validation
- LoS cache integration

---

### pve_controller.py - PvE AI Opponent

**Class:** `PvEController`

**Key Methods:**
- `__init__(config, unit_registry)` - Initialize controller
- `load_ai_model_for_pve(game_state, engine)` - Load trained model for Player 2
- `make_ai_decision(game_state)` - Get AI action via model prediction
- `ai_select_unit(eligible_units, action_type)` - Select first eligible unit
- `_ai_select_movement_destination(unit_id, game_state)` - Choose movement target
- `_ai_select_shooting_target()` - NotImplementedError (uses handler flow)
- `_ai_select_charge_target()` - NotImplementedError (placeholder)
- `_ai_select_combat_target()` - NotImplementedError (placeholder)

**Responsibilities:**
- Load trained AI models for PvE mode
- Make AI decisions for Player 2
- Use MaskablePPO for predictions
- Integrate with engine's action flow
- Provide fallback behaviors for AI

---

### phase_handlers/ - Phase-Specific Logic

Each handler module implements complete phase logic:

**movement_handlers.py:**
- Movement eligibility
- Valid destination calculation
- Movement execution
- Flee detection

**shooting_handlers.py:**
- Shooting eligibility
- Target pool building
- Hit/wound/save rolls
- Damage application
- LoS validation

**charge_handlers.py:**
- Charge eligibility
- Charge range calculation
- Charge execution

**fight_handlers.py:**
- Fight eligibility
- Melee target selection
- Attack resolution
- Fight subphase management

**Handler Pattern:**
- Receive game_state as parameter
- Return results without storing state
- Pure delegation from engine
- Implement AI_TURN.md rules exactly

---

## HOW EVERYTHING WORKS TOGETHER

### Complete Request Flow: agent.step(action)

This traces one complete gym step from action input to observation output.

**1. Entry Point - step(action)**
```
W40KEngine.step(action: int)
│
├─ Check turn limit (training_config.max_turns_per_episode)
├─ Check game_over status
│
└─ CONVERT ACTION
   └─> action_decoder.convert_gym_action(action, game_state)
       │
       ├─ Get action mask to validate
       ├─ Get eligible units from activation pool
       ├─ Map integer to semantic action:
       │  • 0-3 → movement directions
       │  • 4-8 → shoot target slots
       │  • 9 → charge
       │  • 10 → fight
       │  • 11 → wait
       │
       └─ Return: {"action": "move", "unitId": "u1", "destCol": 5, "destRow": 3}
```

**2. Process Semantic Action**
```
_process_semantic_action(semantic_action)
│
├─ Read current_phase from game_state
│
└─ Route to phase processor:
   ├─ "move" → _process_movement_phase()
   ├─ "shoot" → _process_shooting_phase()
   ├─ "charge" → _process_charge_phase()
   └─ "fight" → _process_fight_phase()
```

**3. Phase Processing (Example: Movement)**
```
_process_movement_phase(action)
│
├─ Get unit from semantic_action["unitId"]
│
└─ DELEGATE TO HANDLER
   └─> movement_handlers.execute_action(game_state, unit, action, config)
       │
       ├─ Validate unit is in move_activation_pool
       ├─ Check destination is valid (not wall, not occupied)
       ├─ Check flee status (was adjacent to enemy)
       ├─ Update unit position in game_state["units"]
       ├─ Mark unit as moved (add to game_state["units_moved"])
       ├─ Remove unit from move_activation_pool
       │
       ├─ Check if pool is empty
       │  └─ If empty: return {"phase_complete": True}
       │
       └─ Return: (success=True, result={...})
```

**4. Phase Transition Detection**
```
Back in _process_movement_phase():
│
├─ Check result["phase_complete"]
│
└─ If phase complete:
   ├─ Set flag: _movement_phase_initialized = False
   ├─ Call: _shooting_phase_init()
   │  └─> shooting_handlers.shooting_phase_start(game_state)
   │      └─ Build shoot_activation_pool from eligible units
   │
   └─ Add to result: {"phase_transition": True, "next_phase": "shoot"}
```

**5. Increment Step Counter**
```
Back in step():
│
├─ If action was successful:
│  └─ game_state["episode_steps"] += 1
│
└─ Track compliance data (one unit per step)
```

**6. Build Observation**
```
obs_builder.build_observation(game_state)
│
├─ Get active unit (first in current activation pool)
│
├─ ENCODE FEATURES (150 floats):
│  │
│  ├─ Active unit stats (normalized):
│  │  • HP_CUR/HP_MAX ratio
│  │  • MOVE distance
│  │  • Combat capabilities
│  │
│  ├─ Directional terrain (8 directions):
│  │  • Distance to nearest wall
│  │  • Distance to edge
│  │
│  ├─ Allied units (3 nearest):
│  │  • Relative position (egocentric)
│  │  • HP status
│  │  • Combat stats
│  │
│  ├─ Enemy units (3 nearest):
│  │  • Relative position
│  │  • Threat assessment
│  │  • Kill probability
│  │
│  └─ Valid targets (5 slots):
│     • Target priority
│     • Expected damage
│     • Type match score
│
└─ Return: numpy array shape (150,)
```

**7. Calculate Reward**
```
reward_calculator.calculate_reward(success, result, game_state)
│
├─ Check for system penalties:
│  ├─ Invalid action → -1.0
│  ├─ Forbidden action → -0.5
│  └─ System response → 0.0
│
├─ Get acting unit from result
│
├─ Calculate base rewards (from rewards_config.json):
│  ├─ Movement rewards
│  ├─ Shooting rewards (damage dealt)
│  ├─ Elimination rewards
│  └─ Tactical bonuses
│
├─ Calculate situational rewards:
│  ├─ Moved to cover
│  ├─ Moved to optimal range
│  ├─ Gained LoS on priority target
│  └─ Safe from threats
│
└─ Return: float (total reward)
```

**8. Check Game Over**
```
_check_game_over()
│
├─ Check turn limit exceeded
│
├─ Count living units per player
│
└─ Return: True if ≤1 player has living units
```

**9. Return to Caller**
```
step() returns:
│
├─ observation: np.ndarray (150,)
├─ reward: float
├─ terminated: bool (game_over)
├─ truncated: bool (always False)
└─ info: dict
   ├─ "success": bool
   ├─ "winner": int|None
   ├─ "episode": dict (if terminated)
   └─ "action_logs": list
```

---

### Complete Episode Lifecycle

**Episode Start: reset()**
```
reset()
│
├─ Reset game_state fields:
│  ├─ current_player = 0
│  ├─ phase = "move"
│  ├─ turn = 1
│  ├─ episode_steps = 0
│  └─ Clear all tracking sets
│
├─ Reset all units:
│  ├─ HP_CUR = HP_MAX
│  ├─ SHOOT_LEFT = RNG_NB
│  ├─ ATTACK_LEFT = CC_NB
│  └─ Restore original positions
│
├─ Initialize movement phase:
│  └─> movement_handlers.movement_phase_start(game_state)
│      └─ Build initial move_activation_pool
│
├─ Build initial observation
│
└─ Return: (observation, info)
```

**Episode Loop: step() repeatedly**
```
Player 0 Turn:
│
├─ Movement Phase:
│  └─ Process all units in move_activation_pool
│     └─ Each unit = one step() call
│
├─ Shooting Phase:
│  └─ Process all units in shoot_activation_pool
│     └─ Each unit = one step() call
│
├─ Charge Phase: (placeholder)
│
└─ Fight Phase: (placeholder)

Phase complete → Switch to Player 1
│
Player 1 Turn:
│  (Same phase sequence)
│
Phase complete → Switch back to Player 0
Turn counter increments
│
Repeat until game_over = True
```

**Episode End: terminated=True**
```
When step() returns terminated=True:
│
├─ Calculate winner:
│  ├─ One player eliminated → winner
│  ├─ Turn limit + unequal units → winner
│  └─ Turn limit + equal units → draw (-1)
│
├─ Populate info["episode"]:
│  ├─ "r": total episode reward
│  ├─ "l": episode length
│  └─ "t": episode steps
│
└─ Training system calls reset() for next episode
```

---

### Data Flow: game_state Through Modules

**Single Source of Truth:**
```
W40KEngine.__init__():
│
└─ self.game_state = {
   "units": [...],
   "current_player": 0,
   "phase": "move",
   "move_activation_pool": [],
   "shoot_activation_pool": [],
   ...
}

All modules receive game_state as parameter:
│
├─> movement_handlers.execute_action(game_state, ...)
│   └─ Reads: units, current_player, move_activation_pool
│   └─ Writes: units[i]["col"], units[i]["row"], units_moved
│
├─> observation_builder.build_observation(game_state)
│   └─ Reads: units, current_player, phase, los_cache
│   └─ Writes: nothing (pure read)
│
├─> reward_calculator.calculate_reward(..., game_state)
│   └─ Reads: units, action_logs, game_over, winner
│   └─ Writes: last_reward_breakdown (for metrics)
│
└─> action_decoder.get_action_mask(game_state)
    └─ Reads: phase, move_activation_pool, shoot_activation_pool
    └─ Writes: nothing (pure read)

NO MODULE COPIES game_state
NO MODULE STORES game_state INTERNALLY
```

---

### Phase Transition Flow

**Movement → Shooting:**
```
movement_handlers.execute_action():
│
├─ Process unit movement
├─ Remove unit from move_activation_pool
│
└─ Check pool empty:
   └─ If empty:
      └─ Return: {"phase_complete": True}

W40KEngine._process_movement_phase():
│
├─ Receive: result["phase_complete"] = True
│
├─ Call: _shooting_phase_init()
│  └─> shooting_handlers.shooting_phase_start(game_state)
│      │
│      ├─ Build shoot_activation_pool:
│      │  └─ For each unit:
│      │     ├─ Check HP_CUR > 0
│      │     ├─ Check current_player matches
│      │     ├─ Check has RNG_NB > 0
│      │     ├─ Check has valid targets
│      │     └─ Add to pool
│      │
│      └─ Update game_state:
│         └─ phase = "shoot"
│
└─ Add to result:
   └─ {"phase_transition": True, "next_phase": "shoot"}
```

**Shooting → Next Player:**
```
shooting_handlers.execute_action():
│
├─ Process unit shooting
├─ Remove unit from shoot_activation_pool
│
└─ Check pool empty:
   └─ If empty:
      ├─ Switch player: current_player = 1 - current_player
      ├─ If current_player == 0:
      │  └─ Increment turn counter
      │
      ├─ Clear tracking sets:
      │  └─ units_moved, units_shot, etc.
      │
      ├─ Return to movement phase:
      │  └─> movement_handlers.movement_phase_start(game_state)
      │
      └─ Return: {"phase_complete": True, "next_phase": "move"}
```

---

### Integration Points

**Gym Training:**
```
Training Script:
│
├─ from engine.w40k_core import W40KEngine
│
├─ env = W40KEngine(config, ...)
│
├─ model = MaskablePPO(policy, env, ...)
│
└─ Training loop:
   ├─ obs, info = env.reset()
   │
   └─ For each step:
      ├─ action, _ = model.predict(obs, action_masks=env.get_action_mask())
      ├─ obs, reward, done, truncated, info = env.step(action)
      └─ If done: obs, info = env.reset()
```

**HTTP API (Frontend):**
```
API Server:
│
├─ engine = W40KEngine(config, ...)
│
├─ POST /api/action:
│  │
│  ├─ Receive: {"type": "move", "unitId": "u1", "to": {"col": 5, "row": 3}}
│  │
│  ├─ Call: engine.execute_semantic_action(action)
│  │
│  ├─ Transform result to frontend format:
│  │  └─ UPPERCASE → lowercase field names
│  │
│  └─ Return: JSON response
│
└─ GET /api/state:
   │
   ├─ Read: engine.game_state
   │
   ├─ Transform to frontend format
   │
   └─ Return: current game state
```

---

## PERFORMANCE OPTIMIZATIONS

### LoS Cache (5x Shooting Speedup)

Line-of-sight calculations cached in `game_state["los_cache"]`. Cache built at shooting phase start, invalidated on movement. Reduces shooting phase from 40% to 8% of episode time.

### Egocentric Observation (150 Floats)

Observation uses relative coordinates centered on active unit. Perception radius R=25 creates fog of war. Enables transfer learning. No performance degradation despite larger observation space.

### CPU Optimization (311 it/s)

Small neural networks (256×256 MlpPolicy) run faster on CPU than GPU. Better cache locality for small networks. Training achieves 311 iterations/second on CPU vs 282 it/s on GPU.

### Combined Impact

Overall 4.7x training speedup (66 → 311 it/s). Debug config (50 episodes) runs in 11 seconds. Default config (2000 episodes) completes in 7 minutes.

---

## SUCCESS METRICS

### Architecture
- ✅ Single source of truth maintained
- ✅ Sequential activation (one unit per step)
- ✅ Built-in step counting (one location)
- ✅ Phase completion by eligibility
- ✅ UPPERCASE field validation enforced
- ✅ Zero wrapper patterns

### Performance
- ✅ 4.7x training speedup (66 → 311 it/s)
- ✅ LoS cache: 5x faster shooting
- ✅ Egocentric observation: No performance loss
- ✅ CPU optimization: 10% faster than GPU

### Observation System
- ✅ 150-float egocentric observation
- ✅ R=25 perception radius (fog of war)
- ✅ Directional awareness (ahead/behind/flanking)
- ✅ Transfer learning enabled

---

## RELATED DOCUMENTATION

1. [AI_TURN.md](AI_TURN.md) - Core game rules and turn sequence
2. [AI_TRAINING.md](AI_TRAINING.md) - PPO training integration
3. [AI_OBSERVATION.md](AI_OBSERVATION.md) - Egocentric observation system
4. [AI_TARGET_SELECTION.md](AI_TARGET_SELECTION.md) - Target selection and prioritization

---

## SUMMARY

The W40K engine uses modular architecture with clear separation of concerns. Core engine (`w40k_core.py`) owns game_state and orchestrates flow. Specialized modules handle observation, rewards, actions, and combat. Phase handlers implement game rules. All modules follow AI_TURN.md compliance: single source of truth, sequential activation, UPPERCASE fields, no wrappers.

The "How Everything Works Together" section traces complete request flows showing how modules interact during actual gameplay. Understanding these flows is essential for debugging, extending features, and maintaining the system.

Performance optimizations achieve 4.7x training speedup while maintaining zero architectural violations. Modular structure enables independent testing, parallel development, and maintainable codebase.