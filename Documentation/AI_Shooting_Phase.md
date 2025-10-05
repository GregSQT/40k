# SHOOTING PHASE - Complete Implementation Specification

## Architecture Overview

The shooting phase implements complete handler autonomy where the engine delegates all phase management to `shooting_handlers.py`. The handler manages the complete phase lifecycle from initialization to completion.

## Phase Overview - Function Level

```
🎯 SHOOTING PHASE - Function Level Overview

├── ⭐shooting_phase_start(game_state)
│   ├── Set: game_state["phase"] = "shoot" 
│   ├── ⭐shooting_build_activation_pool(game_state)
│   ├── Add console log: "SHOOT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop
├── ⭐_is_valid_shooting_unit() : STEP : UNIT_ACTIVABLE_CHECK → is shoot_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → [AI LOGIC TO BE IMPLEMENTED]
│   │   └── NO → ⭐execute_action(game_state, unit, action, config) : STEP : UNIT_ACTIVATION → Human player → player activate one unit from shoot_activation_pool
│   │       ├── ⭐shooting_unit_activation_start()
│   │       ├── ⭐shooting_unit_execution_loop() : While SHOOT_LEFT > 0
│   │       │   ├── ⭐shooting_build_valid_target_pool() : Build 📋 valid_target_pool
│   │       │   └── ⭐_is_valid_shooting_target() : valid_target_pool NOT empty ?
│   │       │       ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │       │       │   ├── ⭐shooting_preview()
│   │       │       │   └── ⭐shooting_click_handler() STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── ACTION : Left click on a target in 📋valid_target_pool : ⭐shooting_target_selection_handler()
│   │       │       │       ├── ACTION : Left click on another unit in shoot_activation_pool ? ⭐_handle_unit_switch_with_context()
│   │       │       │       ├── ACTION : Left click on the active_unit → No effect
│   │       │       │       ├── ACTION : Right click on the active_unit
│   │       │       │       └── ACTION : Left OR Right click anywhere else on the board
│   │       │       └── NO → SHOOT_LEFT = RNG_NB ?
│   │       │           ├── NO → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING) → shot the last target available in 📋valid_target_pool
│   │       │           └── YES → ⭐end_activation() (PASS, 1, PASS, SHOOTING) → no target available in 📋valid_target_pool at activation → no shoot
│   │       └── End of shooting → ⭐end_activation() (ACTION, 1, SHOOTING, SHOOTING)
│   └── NO → ⭐shooting_phase_end()
└── End of shooting phase → Advance to charge phase
```

## Complete Implementation Tree

```
🎯 SHOOTING PHASE - Complete Handler Autonomy

ENGINE ORCHESTRATION:
├── w40k_engine._process_shooting_phase(action)
│   ├── First call to phase? → shooting_phase_start(game_state)
│   ├── **FULL DELEGATION**: shooting_handlers.execute_action(game_state, unit, action, config)
│   └── Check response for phase_complete flag

PHASE INITIALIZATION:
├── shooting_phase_start(game_state) **[NEW FUNCTION]**
│   ├── Set: game_state["phase"] = "shoot"
│   ├── shooting_build_activation_pool(game_state)
│   ├── Console log: "SHOOT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop

**PHASE MANAGEMENT LOOP:**
├── **UNIT_ACTIVABLE_CHECK LOOP** → _is_valid_shooting_unit() **[NEW FUNCTION]**
│   ├── shoot_activation_pool NOT empty?
│   │   ├── **YES** → Phase continues
│   │   │   └── **WAIT FOR PLAYER ACTION** (Human player activates unit)
│   │   │       └── execute_action("activate_unit") triggers unit activation
│   │   │
│   │   └── **NO** → shooting_phase_end() **[NEW FUNCTION]**
│   │       └── RETURN {"phase_complete": True, "next_phase": "charge"}
│   │
│   └── **LOOP RETURN POINT** ← All unit activations return here

ELIGIBILITY & POOL BUILDING:
├── shooting_build_activation_pool(game_state)
│   ├── For each PLAYER unit → ELIGIBILITY CHECK:
│   │   ├── unit.HP_CUR > 0? → NO → Skip
│   │   ├── unit.player === current_player? → NO → Skip
│   │   ├── units_fled.includes(unit.id)? → YES → Skip
│   │   ├── Adjacent to enemy within CC_RNG? → YES → Skip
│   │   ├── unit.RNG_NB > 0? → NO → Skip
│   │   ├── Has LOS to enemies within RNG_RNG? → NO → Skip
│   │   └── ALL PASSED → Add to shoot_activation_pool
│   └── Updates: game_state["shoot_activation_pool"] = [eligible_unit_ids]

HANDLER ACTION ROUTING:
├── execute_action(game_state, unit, action, config) **[EXISTING - DO NOT RENAME]**
│   ├── action["action"] == "activate_unit":
│   │   ├── _is_valid_shooting_unit_activation(game_state, unit_id) **[VALIDATION]**
│   │   ├── Valid? → shooting_unit_activation_start(game_state, unit_id)
│   │   └── **AUTOMATIC**: shooting_unit_execution_loop(game_state, unit_id)
│   │
│   ├── action["action"] == "left_click":
│   │   └── shooting_click_handler(game_state, unit_id, action)
│   │
│   ├── action["action"] == "right_click":
│   │   └── end_activation() → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   │
│   └── action["action"] == "skip":
│       └── end_activation() → **RETURN TO UNIT_ACTIVABLE_CHECK**

UNIT ACTIVATION SEQUENCE:
├── shooting_unit_activation_start(game_state, unit_id)
│   ├── Clear: valid_target_pool=[], TOTAL_ATTACK_LOG=""
│   ├── Set: SHOOT_LEFT = RNG_NB, selected_target_id = None
│   └── Set: game_state["active_shooting_unit"] = unit_id
│
├── shooting_unit_execution_loop(game_state, unit_id) **[AUTOMATIC AFTER START]**
│   ├── Check: SHOOT_LEFT <= 0? → end_activation() → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   ├── shooting_build_valid_target_pool(game_state, unit_id)
│   ├── valid_targets empty?
│   │   ├── YES → SHOOT_LEFT == RNG_NB?
│   │   │   ├── YES → end_activation(PASS) → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   │   │   └── NO → end_activation(ACTION) → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   │   └── NO → shooting_preview(valid_targets)
│   └── RETURN: preview data → **BACKEND WAITS FOR PLAYER CLICK**

CLICK HANDLING:
├── shooting_click_handler(game_state, unit_id, action) **[NEW FUNCTION]**
│   ├── Parse: target_id, click_target from action
│   ├── Route based on click_target:
│   │   ├── "target" → shooting_target_selection_handler()
│   │   ├── "friendly_unit" → _handle_unit_switch_with_context()
│   │   ├── "active_unit" → No effect or context-specific handling
│   │   └── "elsewhere" → Continue selection
│   └── RETURN: Action result with flow control

TARGET SELECTION & SHOOTING:
├── shooting_target_selection_handler(game_state, unit_id, target_id) **[SINGLE CLICK]**
│   ├── Validate: target_id in valid_target_pool
│   ├── shooting_attack_controller(game_state, unit_id, target_id)
│   ├── Update: SHOOT_LEFT -= 1, TOTAL_ATTACK_LOG += result
│   ├── Remove dead targets from valid_target_pool
│   └── **AUTOMATIC**: shooting_unit_execution_loop() → Continue or End

PREVIEW SYSTEM:
├── shooting_preview(valid_targets) **[NEW FUNCTION]**
│   ├── Description: Display the shooting preview (all hexes with LoS and RNG_RNG are red)
│   ├── Description: Display HP bar blinking animation for every unit in valid_target_pool
│   └── RETURN: {"blinking_units": valid_targets, "start_blinking": True, "red_hexes": hex_coords}

ACTIVATION END:
├── end_activation(game_state, unit, arg1, arg2, arg3, arg4) **[CROSS-PHASE FUNCTION]**
│   ├── Apply AI_TURN.md tracking (episode_steps, units_shot)
│   ├── Clean unit state, remove from shoot_activation_pool
│   ├── Clear: game_state["active_shooting_unit"] = None
│   └── **MANDATORY RETURN TO UNIT_ACTIVABLE_CHECK LOOP**

PHASE END:
└── shooting_phase_end(game_state) **[NEW FUNCTION]**
    ├── Final cleanup of phase state
    ├── Console log: "SHOOTING PHASE COMPLETE"
    └── RETURN: {"phase_complete": True, "next_phase": "charge"}
```

## Function Specifications

### New Functions Required

#### `shooting_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** Initialize shooting phase and build activation pool
**Returns:** Phase initialization result
```python
{
    "phase_initialized": True,
    "eligible_units": int,
    "phase_complete": bool  # True if no eligible units
}
```

#### `_is_valid_shooting_unit(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** UNIT_ACTIVABLE_CHECK loop - check if phase should continue
**Returns:** Phase continuation status
```python
{
    "phase_continues": bool,
    "eligible_units_remaining": int,
    "phase_complete": bool
}
```

#### `shooting_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]`
**Purpose:** Route click actions to appropriate handlers
**Parameters:**
- `action`: Contains targetId, clickTarget ("target"|"friendly_unit"|"active_unit"|"elsewhere")
**Returns:** Action processing result with flow control

#### `shooting_preview(valid_targets: List[str]) -> Dict[str, Any]`
**Purpose:** Generate preview data for frontend
**Returns:** Preview data for red hexes and blinking HP bars
```python
{
    "blinking_units": List[str],
    "start_blinking": bool,
    "red_hexes": List[Tuple[int, int]]
}
```

#### `shooting_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** Clean up and end shooting phase
**Returns:** Phase completion signal
```python
{
    "phase_complete": True,
    "next_phase": "charge",
    "units_processed": int
}
```

#### `_is_valid_shooting_unit_activation(game_state: Dict[str, Any], unit_id: str) -> bool`
**Purpose:** Validate individual unit can be activated
**Returns:** Boolean validation result

### Existing Functions (Keep Current Implementation)

- `shooting_build_activation_pool(game_state)` - Pool building with eligibility checks
- `shooting_unit_activation_start(game_state, unit_id)` - Unit activation initialization  
- `shooting_unit_execution_loop(game_state, unit_id)` - While SHOOT_LEFT > 0 loop
- `shooting_build_valid_target_pool(game_state, unit_id)` - Target validation
- `shooting_target_selection_handler(game_state, unit_id, target_id)` - Single-click shooting
- `shooting_attack_controller(game_state, unit_id, target_id)` - Attack execution
- `end_activation(game_state, unit, arg1, arg2, arg3, arg4)` - Cross-phase activation end
- `execute_action(game_state, unit, action, config)` - Main action router

## Implementation Notes

1. **Complete Handler Autonomy**: Engine only manages phase sequence, handlers manage all phase logic
2. **Single-Click Targeting**: Simplified from two-click to one-click target selection
3. **Automatic Loop Management**: Execution loop called automatically after actions
4. **Phase Completion**: Handler detects and signals phase completion to engine
5. **Cross-Phase Functions**: `end_activation()` used across all phases
6. **Action Routing**: `execute_action()` routes to specialized handlers like `shooting_click_handler()`

## Flow Control

The shooting phase uses nested loops:
- **UNIT_ACTIVABLE_CHECK**: Outer loop checking for eligible units
- **shooting_unit_execution_loop**: Inner loop for individual unit actions (While SHOOT_LEFT > 0)

All unit activations return to UNIT_ACTIVABLE_CHECK, which continues until the shoot_activation_pool is empty, then signals phase completion to the engine.