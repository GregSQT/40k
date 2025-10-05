# MOVEMENT PHASE - Complete Implementation Specification

## Architecture Overview

The movement phase implements complete handler autonomy where the engine delegates all phase management to `movement_handlers.py`. The handler manages the complete phase lifecycle from initialization to completion.

## Phase Overview - Function Level

```
🎯 MOVEMENT PHASE - COMPLETE Overview

START OF THE PHASE
For each unit
├── ❌ Remove Mark units_moved
├── ❌ Remove Mark units_fled
├── ❌ Remove Mark units_shot
├── ❌ Remove Mark units_charged
└── ❌ Remove Mark units_fought
├── ELIGIBILITY CHECK (move_activation_pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   └── ALL conditions met → ✅ Add to move_activation_pool
├── STEP : UNIT_ACTIVABLE_CHECK → is move_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → pick one unit in move_activation_pool
│   │   │   └── Valid destination exists (reacheable hexes using BFS pathfinding within MOVE attribute distance, NOT through/into wall hexes, NOT through/into adjacent to enemy hexes) ?
│   │   │       ├── YES → MOVEMENT PHASE ACTIONS AVAILABLE
│   │   │       │   ├── 🎯 VALID ACTIONS: [move, wait]
│   │   │       │   ├── ❌ INVALID ACTIONS: [shoot, charge, attack] → end_activation (ERROR, 0, PASS, MOVE)
│   │   │       │   └── AGENT ACTION SELECTION → Choose move ?
│   │   │       │       ├── YES → ✅ VALID → Execute move action
│   │   │       │       │   ├── The active_unit was adjacent to an enemy unit at the start of its move action ?
│   │   │       │       │   │   ├── YES → end_activation (ACTION, 1, FLED, MOVE)
│   │   │       │       │   │   └── NO → end_activation (ACTION, 1, MOVE, MOVE)
│   │   │       │       └── NO → Agent chooses: wait?
│   │   │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │       │           │   └── end_activation (WAIT, 1, PASS, MOVE)
│   │   │       │           └── NO → Agent chooses invalid action (shoot/charge/attack)?
│   │   │       │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, MOVE)
│   │   │       └── NO → end_activation (PASS, 0, PASS, MOVE)
│   │   └── NO → Human player → STEP : UNIT_ACTIVATION
│   │       ├── If any, cancel the Highlight of the hexes in valid_move_destinations_pool
│   │       ├── Player activate one unit by left clicking on it
│   │       └── Build valid_move_destinations_pool (NOT wall hexes, NOT adjacent to enemy hexes, reacheable using BFS pathfinding within MOVE attribute distance)
│   │           └── valid_move_destinations_pool not empty ?
│   │               ├── YES → STEP : PLAYER_ACTION_SELECTION
│   │               │   ├── Highlight the valid_move_destinations_pool hexes by making them green
│   │               │   └── Player select the action to execute
│   │               │       ├── Left click on a hex in valid_move_destinations_pool → Move the unit's icon to the selected hex
│   │               │       │   ├── The active_unit was adjacent to an enemy unit at the start of its move action ?
│   │               │       │   │   ├── YES → end_activation (ACTION, 1, FLED, MOVE)
│   │               │       │   │   └── NO → end_activation (ACTION, 1, MOVE, MOVE)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on the active_unit → Move postponed
│   │               │       │   └── GO TO STEP : STEP : UNIT_ACTIVATION
│   │               │       ├── Right click on the active_unit → Move cancelled
│   │               │       │   ├── end_activation (PASS, 0, PASS, MOVE)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on another unit in activation pool → Move postponed
│   │               │       │   └── GO TO STEP : UNIT_ACTIVATION
│   │               │       └── Left OR Right click anywhere else on the board → Cancel Move hex selection
│   │               │           └── GO TO STEP : UNIT_ACTIVATION
│   │               └── NO → end_activation (PASS, 0, PASS, MOVE)
│   ├── NO → If any, cancel the Highlight of the hexes in valid_move_destinations_pool
│   └── No more activable units → pass
└── End of MOVEMENT PHASE → Advance to shooting phase


🎯 MOVEMENT PHASE - Function Level Overview

├── ⭐movement_phase_start(game_state)
│   ├── Set: game_state["phase"] = "move" 
│   ├── ⭐movement_build_activation_pool(game_state)
│   ├── Add console log: "MOVEMENT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop
├── ⭐_is_valid_movement_unit() : STEP : UNIT_ACTIVABLE_CHECK → is movement_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → [AI LOGIC TO BE IMPLEMENTED]
│   │   └── NO → ⭐execute_action(game_state, unit, action, config) : STEP : UNIT_ACTIVATION → Human player → player activate one unit from movement_activation_pool
│   │           ├── ⭐movement_build_valid_destination_pool() : Build 📋 valid_destination_pool
│   │           └── ⭐_is_valid_movement_target() : valid_target_pool NOT empty ?
│   │               ├── YES → MOVEMENT PHASE ACTIONS AVAILABLE
│   │               │   ├── ⭐movement_preview() → Highlight the valid_movement_destinations_pool hexes by making them green
│   │               │   └── Player select the action to execute
│   │               │       ├── Left click on a hex in valid_movement_destinations_pool → Move the unit's icon to the selected hex
│   │               │       │   ├── The active_unit was adjacent to an enemy unit at the start of its move action ?
│   │               │       │   │   ├── YES → ⭐end_activation (ACTION, 1, FLED, MOVE)
│   │               │       │   │   └── NO → ⭐end_activation (ACTION, 1, MOVE, MOVE)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on the active_unit → Move postponed
│   │               │       │   └── GO TO STEP : STEP : UNIT_ACTIVATION
│   │               │       ├── Right click on the active_unit → Move cancelled
│   │               │       │   ├── ⭐end_activation (PASS, 0, PASS, MOVE)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on another unit in activation pool → Move postponed
│   │               │       │   └── GO TO STEP : UNIT_ACTIVATION
│   │               │       └── Left OR Right click anywhere else on the board → Cancel Move hex selection
│   │               │           └── GO TO STEP : UNIT_ACTIVATION
│   │               └── NO → ⭐end_activation(PASS, 0, PASS, MOVE)
│   ├── NO → ⭐movement_phase_end()
│   │   ├── If any, cancel the Highlight of the hexes in valid_movement_destinations_pool
│   │   └── No more activable units → pass
└── End of MOVEMENT PHASE → Advance to shooting phase
```

## Complete Implementation Tree

```
🎯 MOVEMENT PHASE - Complete Handler Autonomy

ENGINE ORCHESTRATION:
├── w40k_engine._process_movement_phase(action)
│   ├── First call to phase? → movement_phase_start(game_state)
│   ├── **FULL DELEGATION**: movement_handlers.execute_action(game_state, unit, action, config)
│   └── Check response for phase_complete flag

PHASE INITIALIZATION:
├── movement_phase_start(game_state) **[NEW FUNCTION]**
│   ├── Set: game_state["phase"] = "shoot"
│   ├── movement_build_activation_pool(game_state)
│   ├── Console log: "SHOOT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop

**PHASE MANAGEMENT LOOP:**
├── **UNIT_ACTIVABLE_CHECK LOOP** → _is_valid_movement_unit() **[NEW FUNCTION]**
│   ├── movement_activation_pool NOT empty?
│   │   ├── **YES** → Phase continues
│   │   │   └── **WAIT FOR PLAYER ACTION** (Human player activates unit)
│   │   │       └── execute_action("activate_unit") triggers unit activation
│   │   │
│   │   └── **NO** → movement_phase_end() **[NEW FUNCTION]**
│   │       └── RETURN {"phase_complete": True, "next_phase": "charge"}
│   │
│   └── **LOOP RETURN POINT** ← All unit activations return here

ELIGIBILITY & POOL BUILDING:
├── movement_build_activation_pool(game_state)
│   ├── For each PLAYER unit → ELIGIBILITY CHECK:
│   │   ├── unit.HP_CUR > 0? → NO → Skip
│   │   ├── unit.player === current_player? → NO → Skip
│   │   └── ALL PASSED → Add to movement_activation_pool
│   └── Updates: game_state["movement_activation_pool"] = [eligible_unit_ids]

HANDLER ACTION ROUTING:
├── execute_action(game_state, unit, action, config) **[EXISTING - DO NOT RENAME]**
│   ├── action["action"] == "activate_unit":
│   │   ├── _is_valid_movement_unit_activation(game_state, unit_id) **[VALIDATION]**
│   │   ├── Valid? → movement_unit_activation_start(game_state, unit_id)
│   │   └── **AUTOMATIC**: movement_unit_execution_loop(game_state, unit_id)
│   │
│   ├── action["action"] == "left_click":
│   │   └── movement_click_handler(game_state, unit_id, action)
│   │
│   ├── action["action"] == "right_click":
│   │   └── end_activation() → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   │
│   └── action["action"] == "skip":
│       └── end_activation() → **RETURN TO UNIT_ACTIVABLE_CHECK**

UNIT ACTIVATION SEQUENCE:
├── movement_unit_activation_start(game_state, unit_id)
│   ├── Clear: valid_target_pool=[], TOTAL_ATTACK_LOG=""
│   ├── Set: SHOOT_LEFT = RNG_NB, selected_target_id = None
│   └── Set: game_state["active_movement_unit"] = unit_id
│
├── movement_unit_execution_loop(game_state, unit_id) **[AUTOMATIC AFTER START]**
│   ├── Check: SHOOT_LEFT <= 0? → end_activation() → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   ├── movement_build_valid_target_pool(game_state, unit_id)
│   ├── valid_targets empty?
│   │   ├── YES → SHOOT_LEFT == RNG_NB?
│   │   │   ├── YES → end_activation(PASS) → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   │   │   └── NO → end_activation(ACTION) → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   │   └── NO → movement_preview(valid_targets)
│   └── RETURN: preview data → **BACKEND WAITS FOR PLAYER CLICK**

CLICK HANDLING:
├── movement_click_handler(game_state, unit_id, action) **[NEW FUNCTION]**
│   ├── Parse: target_id, click_target from action
│   ├── Route based on click_target:
│   │   ├── "target" → movement_target_selection_handler()
│   │   ├── "friendly_unit" → _handle_unit_switch_with_context()
│   │   ├── "active_unit" → No effect or context-specific handling
│   │   └── "elsewhere" → Continue selection
│   └── RETURN: Action result with flow control

TARGET SELECTION & MOVEMENT:
├── movement_target_selection_handler(game_state, unit_id, target_id) **[SINGLE CLICK]**
│   ├── Validate: target_id in valid_target_pool
│   ├── movement_attack_controller(game_state, unit_id, target_id)
│   ├── Update: SHOOT_LEFT -= 1, TOTAL_ATTACK_LOG += result
│   ├── Remove dead targets from valid_target_pool
│   └── **AUTOMATIC**: movement_unit_execution_loop() → Continue or End

PREVIEW SYSTEM:
├── movement_preview(valid_targets) **[NEW FUNCTION]**
│   ├── Description: Display the movement preview (all hexes with LoS and RNG_RNG are red)
│   ├── Description: Display HP bar blinking animation for every unit in valid_target_pool
│   └── RETURN: {"blinking_units": valid_targets, "start_blinking": True, "red_hexes": hex_coords}

ACTIVATION END:
├── end_activation(game_state, unit, arg1, arg2, arg3, arg4) **[CROSS-PHASE FUNCTION]**
│   ├── Apply AI_TURN.md tracking (episode_steps, units_shot)
│   ├── Clean unit state, remove from movement_activation_pool
│   ├── Clear: game_state["active_movement_unit"] = None
│   └── **MANDATORY RETURN TO UNIT_ACTIVABLE_CHECK LOOP**

PHASE END:
└── movement_phase_end(game_state) **[NEW FUNCTION]**
    ├── Final cleanup of phase state
    ├── Console log: "MOVEMENT PHASE COMPLETE"
    └── RETURN: {"phase_complete": True, "next_phase": "charge"}
```

## Function Specifications

### New Functions Required

#### `movement_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** Initialize movement phase and build activation pool
**Returns:** Phase initialization result
```python
{
    "phase_initialized": True,
    "eligible_units": int,
    "phase_complete": bool  # True if no eligible units
}
```

#### `_is_valid_movement_unit(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** UNIT_ACTIVABLE_CHECK loop - check if phase should continue
**Returns:** Phase continuation status
```python
{
    "phase_continues": bool,
    "eligible_units_remaining": int,
    "phase_complete": bool
}
```

#### `movement_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]`
**Purpose:** Route click actions to appropriate handlers
**Parameters:**
- `action`: Contains targetId, clickTarget ("target"|"friendly_unit"|"active_unit"|"elsewhere")
**Returns:** Action processing result with flow control

#### `movement_preview(valid_targets: List[str]) -> Dict[str, Any]`
**Purpose:** Generate preview data for frontend
**Returns:** Preview data for red hexes and blinking HP bars
```python
{
    "blinking_units": List[str],
    "start_blinking": bool,
    "red_hexes": List[Tuple[int, int]]
}
```

#### `movement_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** Clean up and end movement phase
**Returns:** Phase completion signal
```python
{
    "phase_complete": True,
    "next_phase": "charge",
    "units_processed": int
}
```

#### `_is_valid_movement_unit_activation(game_state: Dict[str, Any], unit_id: str) -> bool`
**Purpose:** Validate individual unit can be activated
**Returns:** Boolean validation result

### Existing Functions (Keep Current Implementation)

- `movement_build_activation_pool(game_state)` - Pool building with eligibility checks
- `movement_unit_activation_start(game_state, unit_id)` - Unit activation initialization  
- `movement_unit_execution_loop(game_state, unit_id)` - While SHOOT_LEFT > 0 loop
- `movement_build_valid_target_pool(game_state, unit_id)` - Target validation
- `movement_target_selection_handler(game_state, unit_id, target_id)` - Single-click movement
- `movement_attack_controller(game_state, unit_id, target_id)` - Attack execution
- `end_activation(game_state, unit, arg1, arg2, arg3, arg4)` - Cross-phase activation end
- `execute_action(game_state, unit, action, config)` - Main action router

## Implementation Notes

1. **Complete Handler Autonomy**: Engine only manages phase sequence, handlers manage all phase logic
2. **Single-Click Targeting**: Simplified from two-click to one-click target selection
3. **Automatic Loop Management**: Execution loop called automatically after actions
4. **Phase Completion**: Handler detects and signals phase completion to engine
5. **Cross-Phase Functions**: `end_activation()` used across all phases
6. **Action Routing**: `execute_action()` routes to specialized handlers like `movement_click_handler()`

## Flow Control

The movement phase uses nested loops:
- **UNIT_ACTIVABLE_CHECK**: Outer loop checking for eligible units
- **movement_unit_execution_loop**: Inner loop for individual unit actions (While SHOOT_LEFT > 0)

All unit activations return to UNIT_ACTIVABLE_CHECK, which continues until the movement_activation_pool is empty, then signals phase completion to the engine.