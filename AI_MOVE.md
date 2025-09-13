# MOVEMENT PHASE - Complete Implementation Specification

## Architecture Overview

The movement phase implements complete handler autonomy where the engine delegates all phase management to `movement_handlers.py`. The handler manages the complete phase lifecycle from initialization to completion.

## Phase Overview - Function Level

```
🎯 MOVEMENT PHASE - Function Level Overview

├── ⭐movement_phase_start(game_state)
│   ├── Set: game_state["phase"] = "move" 
│   ├── ⭐movement_build_activation_pool(game_state)
│   ├── Add console log: "MOVEMENT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop
├── ⭐_is_valid_movement_unit() : STEP : UNIT_ACTIVABLE_CHECK → is move_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → [AI LOGIC TO BE IMPLEMENTED]
│   │   └── NO → ⭐execute_action(game_state, unit, action, config) : STEP : UNIT_ACTIVATION → Human player → player activate one unit from move_activation_pool
│   │       ├── ⭐movement_unit_activation_start()
│   │       ├── ⭐movement_unit_execution_loop() : Single move per activation
│   │       │   ├── ⭐movement_build_valid_destinations_pool() : Build 📋 valid_move_destinations_pool
│   │       │   └── ⭐_is_valid_movement_destination() : valid_move_destinations_pool NOT empty ?
│   │       │       ├── YES → MOVEMENT PHASE ACTIONS AVAILABLE
│   │       │       │   ├── ⭐movement_preview() → Highlight valid destinations in green
│   │       │       │   └── ⭐movement_click_handler() STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── ACTION : Left click on a hex in 📋valid_move_destinations_pool : ⭐movement_destination_selection_handler()
│   │       │       │       ├── ACTION : Left click on another unit in move_activation_pool ? ⭐_handle_unit_switch_with_context()
│   │       │       │       ├── ACTION : Left click on the active_unit → No effect
│   │       │       │       ├── ACTION : Right click on the active_unit → Skip movement
│   │       │       │       └── ACTION : Left OR Right click anywhere else on the board → Continue selection
│   │       │       └── NO → ⭐end_activation() (PASS, 0, PASS, MOVE) → no valid destinations available
│   │       └── End of movement → ⭐end_activation() (ACTION, 1, MOVE/FLED, MOVE)
│   └── NO → ⭐movement_phase_end()
└── End of movement phase → Advance to shooting phase
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
│   ├── Set: game_state["phase"] = "move"
│   ├── Clear tracking sets: units_moved, units_fled, units_shot, units_charged, units_attacked
│   ├── movement_build_activation_pool(game_state)
│   ├── Console log: "MOVEMENT POOL BUILT"
│   └── Enter UNIT_ACTIVABLE_CHECK loop

**PHASE MANAGEMENT LOOP:**
├── **UNIT_ACTIVABLE_CHECK LOOP** → _is_valid_movement_unit() **[NEW FUNCTION]**
│   ├── move_activation_pool NOT empty?
│   │   ├── **YES** → Phase continues
│   │   │   └── **WAIT FOR PLAYER ACTION** (Human player activates unit)
│   │   │       └── execute_action("activate_unit") triggers unit activation
│   │   │
│   │   └── **NO** → movement_phase_end() **[NEW FUNCTION]**
│   │       └── RETURN {"phase_complete": True, "next_phase": "shoot"}
│   │
│   └── **LOOP RETURN POINT** ← All unit activations return here

ELIGIBILITY & POOL BUILDING:
├── movement_build_activation_pool(game_state)
│   ├── For each PLAYER unit → ELIGIBILITY CHECK:
│   │   ├── unit.HP_CUR > 0? → NO → Skip (dead)
│   │   ├── unit.player === current_player? → NO → Skip (wrong player)
│   │   ├── unit.id in units_moved? → YES → Skip (already moved)
│   │   └── ALL PASSED → Add to move_activation_pool
│   └── Updates: game_state["move_activation_pool"] = [eligible_unit_ids]

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
│   ├── action["action"] == "move":
│   │   └── movement_destination_selection_handler(game_state, unit_id, action)
│   │
│   └── action["action"] == "skip":
│       └── end_activation() → **RETURN TO UNIT_ACTIVABLE_CHECK**

UNIT ACTIVATION SEQUENCE:
├── movement_unit_activation_start(game_state, unit_id)
│   ├── Clear: valid_move_destinations_pool=[], preview_hexes=[]
│   ├── Set: game_state["active_movement_unit"] = unit_id
│   └── Prepare for destination selection
│
├── movement_unit_execution_loop(game_state, unit_id) **[AUTOMATIC AFTER START]**
│   ├── movement_build_valid_destinations_pool(game_state, unit_id)
│   ├── valid_destinations empty?
│   │   ├── YES → end_activation(PASS) → **RETURN TO UNIT_ACTIVABLE_CHECK**
│   │   └── NO → movement_preview(valid_destinations)
│   └── RETURN: preview data → **BACKEND WAITS FOR PLAYER CLICK**

CLICK HANDLING:
├── movement_click_handler(game_state, unit_id, action) **[NEW FUNCTION]**
│   ├── Parse: destination_hex, click_target from action
│   ├── Route based on click_target:
│   │   ├── "destination_hex" → movement_destination_selection_handler()
│   │   ├── "friendly_unit" → _handle_unit_switch_with_context()
│   │   ├── "active_unit" → No effect or context-specific handling
│   │   └── "elsewhere" → Continue selection
│   └── RETURN: Action result with flow control

DESTINATION SELECTION & MOVEMENT:
├── movement_destination_selection_handler(game_state, unit_id, action) **[SINGLE CLICK]**
│   ├── Parse: destCol, destRow from action
│   ├── Validate: destination in valid_move_destinations_pool
│   ├── Check flee condition: _is_adjacent_to_enemy_simple(unit) before move
│   ├── Execute movement: unit["col"] = destCol, unit["row"] = destRow
│   ├── movement_clear_preview(game_state) → Clear green hexes
│   └── end_activation(ACTION, 1, MOVE/FLED, MOVE)

PREVIEW SYSTEM:
├── movement_preview(valid_destinations) **[NEW FUNCTION]**
│   ├── Description: Display valid destination hexes in green
│   ├── Clear any existing previews
│   ├── Set: game_state["preview_hexes"] = valid_destinations
│   └── RETURN: {"green_hexes": valid_destinations, "show_preview": True}

├── movement_clear_preview(game_state) **[NEW FUNCTION]**
│   ├── Clear: game_state["preview_hexes"] = []
│   ├── Clear: game_state["valid_move_destinations_pool"] = []
│   └── RETURN: {"show_preview": False, "clear_hexes": True}

DESTINATION VALIDATION:
├── movement_build_valid_destinations_pool(game_state, unit_id) **[NEW FUNCTION]**
│   ├── Clear: game_state["valid_move_destinations_pool"] = []
│   ├── For each hex within unit.MOVE range:
│   │   ├── Board bounds check: hex within board dimensions
│   │   ├── Wall collision check: hex not in wall_hexes
│   │   ├── Unit occupation check: No other living unit at hex
│   │   ├── Enemy adjacency check: hex not adjacent to enemies (distance > 1)
│   │   └── All valid → Add hex to valid_move_destinations_pool
│   └── Return: game_state["valid_move_destinations_pool"]

FLEE DETECTION:
├── _is_adjacent_to_enemy_simple(game_state, unit) **[SIMPLIFIED FUNCTION]**
│   ├── For each enemy unit (different player, HP_CUR > 0)
│   ├── Calculate distance: max(abs(unit.col - enemy.col), abs(unit.row - enemy.row))
│   ├── Distance <= 1? → Return True (adjacent - simplified, no CC_RNG check)
│   └── No adjacent enemies found → Return False

ACTIVATION END:
├── end_activation(game_state, unit, arg1, arg2, arg3, arg4) **[CROSS-PHASE FUNCTION]**
│   ├── Apply AI_TURN.md tracking (episode_steps, units_moved)
│   ├── If result_type == "FLED": Add to units_fled
│   ├── Clean unit state, remove from move_activation_pool
│   ├── Clear: game_state["active_movement_unit"] = None
│   └── **MANDATORY RETURN TO UNIT_ACTIVABLE_CHECK LOOP**

PHASE END:
└── movement_phase_end(game_state) **[NEW FUNCTION]**
    ├── movement_clear_preview(game_state) → Clear any remaining green hexes
    ├── Final cleanup of phase state
    ├── Console log: "MOVEMENT PHASE COMPLETE"
    └── RETURN: {"phase_complete": True, "next_phase": "shoot"}
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
- `action`: Contains destCol, destRow, clickTarget ("destination_hex"|"friendly_unit"|"active_unit"|"elsewhere")
**Returns:** Action processing result with flow control

#### `movement_preview(valid_destinations: List[Tuple[int, int]]) -> Dict[str, Any]`
**Purpose:** Generate preview data for frontend (green hexes)
**Returns:** Preview data for green destination hexes
```python
{
    "green_hexes": List[Tuple[int, int]],
    "show_preview": bool
}
```

#### `movement_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** Clear movement preview and destination pool
**Returns:** Clear preview signal
```python
{
    "show_preview": False,
    "clear_hexes": True
}
```

#### `movement_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str) -> List[Tuple[int, int]]`
**Purpose:** Build valid movement destinations for unit
**Returns:** List of valid destination coordinates

#### `movement_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]`
**Purpose:** Handle destination selection and execute movement
**Parameters:**
- `action`: Contains destCol, destRow
**Returns:** Movement execution result

#### `movement_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]`
**Purpose:** Clean up and end movement phase
**Returns:** Phase completion signal
```python
{
    "phase_complete": True,
    "next_phase": "shoot",
    "units_processed": int
}
```

#### `_is_valid_movement_unit_activation(game_state: Dict[str, Any], unit_id: str) -> bool`
**Purpose:** Validate individual unit can be activated
**Returns:** Boolean validation result

#### `_is_adjacent_to_enemy_simple(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool`
**Purpose:** Simplified flee detection (distance <= 1, no CC_RNG check)
**Returns:** Boolean adjacency result

### Existing Functions (Keep Current Implementation)

- `movement_build_activation_pool(game_state)` - Pool building with eligibility checks
- `movement_unit_activation_start(game_state, unit_id)` - Unit activation initialization  
- `movement_unit_execution_loop(game_state, unit_id)` - Single movement per activation
- `end_activation(game_state, unit, arg1, arg2, arg3, arg4)` - Cross-phase activation end
- `execute_action(game_state, unit, action, config)` - Main action router

## Implementation Notes

1. **Complete Handler Autonomy**: Engine only manages phase sequence, handlers manage all phase logic
2. **Single-Move Per Activation**: Unlike shooting's multiple shots, movement is one move per activation
3. **Green Hex Preview**: Visual feedback showing valid destinations before movement selection
4. **Simplified Flee Detection**: Adjacent = distance <= 1 (no CC_RNG range check)
5. **Phase Completion**: Handler detects and signals phase completion to engine
6. **Cross-Phase Functions**: `end_activation()` used across all phases
7. **Action Routing**: `execute_action()` routes to specialized handlers like `movement_click_handler()`

## Flow Control

The movement phase uses simplified flow compared to shooting:
- **UNIT_ACTIVABLE_CHECK**: Outer loop checking for eligible units
- **movement_unit_execution_loop**: Single movement execution (no loop like shooting's SHOOT_LEFT)

All unit activations return to UNIT_ACTIVABLE_CHECK, which continues until the move_activation_pool is empty, then signals phase completion to the engine.

## Key Differences from Shooting Phase

1. **No Multi-Action Loop**: Movement is single action per activation (vs shooting's SHOOT_LEFT loop)
2. **Destination vs Target**: Movement selects hexes, shooting selects units
3. **Green vs Red Preview**: Movement shows green valid destinations, shooting shows red target areas
4. **Flee Mechanics**: Movement has flee detection, shooting doesn't
5. **Simpler Validation**: Movement checks positioning, shooting checks line-of-sight and range
6. **No Attack Resolution**: Movement updates position only, no damage calculations