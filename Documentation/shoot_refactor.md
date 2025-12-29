## 🎯 SHOOTING PHASE Decision Tree (Optimized)

**⚠️ ADVANCE_IMPLEMENTATION_PLAN.md**: Shooting phase now supports ADVANCE action in addition to SHOOT.

---

### 📚 SECTION 1: GLOBAL VARIABLES & REFERENCE TABLES

#### Global Variable
```javascript
weapon_rule = (weapon rules activated) ? 1 : 0
```

#### Function Argument Reference Table

| Function | arg1 | arg2 | arg3 |
|----------|------|------|------|
| `valid_target_pool_build(arg1, arg2, arg3)` | weapon_rule (use weapon rules?) | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |
| `weapon_availability_check(arg1, arg2, arg3)` | weapon_rule | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |

**Critical Note on arg3 after Advance:** When unit has advanced (arg2=1), arg3 is ALWAYS 0 because advance restrictions prevent moving to enemy-adjacent destinations.

#### End Activation Parameters Reference
```javascript
end_activation(result_type, step_count, action_type, phase, remove_from_pool, increment_step)
```
- `result_type`: ACTION | WAIT | ERROR | NO | NOT_REMOVED
- `step_count`: 0 or 1 (whether to increment episode_steps)
- `action_type`: SHOOTING | ADVANCE | MOVE | CHARGE | etc.
- `phase`: Current phase (SHOOTING)
- `remove_from_pool`: 0 or 1 (whether to remove unit from activation pool)
- `increment_step`: 0 or 1 (internal tracking)

#### State Flags (CAN_SHOOT, CAN_ADVANCE)

**Determined during ELIGIBILITY CHECK:**
- `CAN_ADVANCE = true` if unit is NOT adjacent to enemy (always available)
- `CAN_ADVANCE = false` if unit IS adjacent to enemy (cannot advance when adjacent)
- `CAN_SHOOT = true` if `weapon_availability_check()` returns non-empty pool
- `CAN_SHOOT = false` if `weapon_availability_check()` returns empty pool

**Updated after advance action (if unit actually moved):**
- `CAN_ADVANCE = false` (unit has advanced, cannot advance again)
- `CAN_SHOOT = (weapon_availability_check(weapon_rule, 1, 0) returns non-empty pool)`
  - Note: Only Assault weapons available if weapon_rule=1

#### UI Display Constants

**Shooting Preview Color:**
- **All players (AI and Human)**: Blue hexes (LoS and selected_weapon.RNG)

**Note**: The shooting preview displays all hexes within Line of Sight and within the selected weapon's range in blue color for both AI and Human players.

---

### 🔧 SECTION 2: CORE FUNCTIONS (Reusable Building Blocks)

#### Function: player_advance()
**Purpose**: Execute advance movement for human player  
**Returns**: boolean (true if unit actually moved to different hex, false otherwise)

```javascript
player_advance():
├── Roll 1D6 → advance_range (from config: advance_distance_range)
├── Display advance_range on unit icon (bottom right)
├── Build valid_advance_destinations (BFS, advance_range, no walls, no enemy-adjacent)
├── Highlight destinations in ORANGE
├── Left click on valid advance hex → Move unit
│   └── Return: true (unit actually moved to different hex)
├── Left or Right click on the unit's icon
│   └── Return: false (unit didn't advance)
└── Remove advance icon from the unit
```

#### Function: weapon_availability_check(arg1, arg2, arg3)
**Purpose**: Filter weapons based on rules and context  
**Returns**: weapon_available_pool (set of weapons that can be selected)  
**Process**: Loops through EACH ranged weapon of the unit

```javascript
weapon_availability_check(arg1, arg2, arg3):
For each weapon:
├── Check arg1 (weapon_rule):
│   ├── arg1 = 0 → No weapon rules checked/applied (continue to next check)
│   └── arg1 = 1 → Weapon rules apply (continue to next check)
├── Check arg2 (advance_status):
│   ├── arg2 = 0 → No restriction (continue to next check)
│   └── arg2 = 1 → Unit DID advance:
│       ├── arg1 = 0 → ❌ Weapon CANNOT be selectable (skip weapon)
│       └── arg1 = 1 → ✅ Weapon MUST have ASSAULT rule (continue to next check)
├── Check arg3 (adjacent_status):
│   ├── arg3 = 0 → No restriction (continue to next check)
│   └── arg3 = 1 → Unit IS adjacent to enemy:
│       ├── arg1 = 0 → ❌ Weapon CANNOT be selectable (skip weapon)
│       └── arg1 = 1 → ✅ Weapon MUST have PISTOL rule (continue to next check)
├── Check weapon.shot flag:
│   ├── weapon.shot = 0 → No restriction (continue to next check)
│   └── weapon.shot = 1 → ❌ Weapon CANNOT be selectable (skip weapon)
└── Check weapon.RNG and target availability:
    ├── weapon.RNG > 0? → NO → ❌ Weapon CANNOT be selectable (skip weapon)
    └── YES → Check if at least ONE enemy unit meets ALL conditions:
        │   Conditions (ALL must be true for at least one enemy):
        │   ├── Within weapon.RNG range (distance <= weapon.RNG)
        │   ├── In Line of Sight (no walls blocking)
        │   ├── HP_CUR > 0 (alive)
        │   └── NOT adjacent to friendly unit (excluding active unit)
        └── If NO enemy meets ALL conditions → ❌ Weapon CANNOT be selectable (skip weapon)
        └── If at least ONE enemy meets ALL conditions → ✅ Add weapon to weapon_available_pool
```

#### Function: valid_target_pool_build(arg1, arg2, arg3)
**Purpose**: Build list of valid enemy targets  
**Returns**: valid_target_pool (set of enemy units that can be targeted)  
**Process**: Uses weapon_availability_check() to determine which weapons are available

```javascript
valid_target_pool_build(arg1, arg2, arg3):
For each enemy unit:
├── unit.HP_CUR > 0? → NO → Skip enemy unit
├── unit.player != current_player? → NO → Skip enemy unit
├── Unit NOT adjacent to friendly unit (excluding active unit)? → NO → Skip enemy unit
├── Unit in Line of Sight? → NO → Skip enemy unit
├── Perform weapon_availability_check(arg1, arg2, arg3) → Build weapon_available_pool
├── Unit within range of AT LEAST 1 weapon from weapon_available_pool? → NO → Skip enemy unit
└── ALL conditions met → ✅ Add unit to valid_target_pool
```

#### Function: weapon_selection()
**Purpose**: Allow player to select weapon (Human only)  
**Returns**: void (updates selected_weapon and valid_target_pool)

```javascript
weapon_selection():
├── Opens weapon selection menu
├── Weapons in weapon_available_pool: displayed normally, selectable
├── Weapons NOT in weapon_available_pool: displayed greyed, NOT selectable
├── Click on weapon in weapon_available_pool:
│   ├── selected_weapon = clicked weapon
│   ├── SHOOT_LEFT = selected_weapon.NB
│   ├── Determine context:
│   │   ├── arg1 = weapon_rule
│   │   ├── arg2 = (unit.id in units_advanced) ? 1 : 0
│   │   └── arg3 = (unit adjacent to enemy?) ? 1 : 0
│   ├── valid_target_pool_build(arg1, arg2, arg3)
│   ├── Close weapon selection menu
│   └── Return: weapon selected (continue to shooting action selection)
├── Click weapon selection icon OR click outside menu:
│   ├── Close weapon selection menu
│   └── Return: no weapon selected (continue with current weapon)
```

#### Function: shoot_action(target)
**Purpose**: Execute single shot sequence (unified for AI and Human)  
**Parameters**: target (AI selects best, Human clicks)  
**Returns**: void (updates SHOOT_LEFT, weapon.shot, valid_target_pool)

```javascript
shoot_action(target):
├── Execute attack_sequence(RNG)
├── Concatenate Return to TOTAL_ACTION log
├── SHOOT_LEFT -= 1
└── SHOOT_LEFT == 0 ?
    ├── YES → Current weapon exhausted:
    │   ├── Mark selected_weapon as used (remove from weapon_available_pool, set weapon.shot = 1)
    │   └── weapon_available_pool NOT empty?
    │       ├── YES → Select next available weapon:
    │       │   ├── selected_weapon = next weapon (AI/Human chooses)
    │       │   ├── SHOOT_LEFT = selected_weapon.NB
    │       │   ├── Determine context:
    │       │   │   ├── arg1 = weapon_rule
    │       │   │   ├── arg2 = (unit.id in units_advanced) ? 1 : 0
    │       │   │   └── arg3 = (unit adjacent to enemy?) ? 1 : 0
    │       │   ├── valid_target_pool_build(weapon_rule, arg2, arg3)
    │       │   └── Continue to shooting action selection step (ADVANCED if arg2=1, else normal)
    │       └── NO → All weapons exhausted → End activation
    └── NO → Continue normally (SHOOT_LEFT > 0):
        ├── selected_target dies?
        │   ├── YES → Remove from valid_target_pool:
        │   │   ├── valid_target_pool empty? → YES → End activation (Slaughter handling)
        │   │   └── NO → Continue to shooting action selection step
        │   └── NO → Target survives
        └── Final safety check: valid_target_pool empty AND SHOOT_LEFT > 0?
            ├── YES → End activation (Slaughter handling)
            └── NO → Continue to shooting action selection step
```

**Flow Control - "Continue normally":**
- **When**: After executing shot with SHOOT_LEFT > 0 remaining
- **Process**:
  1. Handle target outcome (died/survived)
  2. Update valid_target_pool (remove dead targets)
  3. Run final safety check (slaughter handling if no targets remain)
  4. Loop back to shooting action selection step
- **Purpose**: Maintain multi-shot sequence until SHOOT_LEFT = 0 or no targets remain

#### Function: POSTPONE_ACTIVATION() (Human only)
**Purpose**: Allow human player to postpone unit activation  
**Trigger**: Human clicks elsewhere without shooting AND unit has NOT shot with ANY weapon

```javascript
POSTPONE_ACTIVATION():
├── Unit is NOT removed from shoot_activation_pool (can be re-activated later)
├── Remove weapon selection icon from UI
└── Return to UNIT_ACTIVABLE_CHECK step
```

---

### 🎯 SECTION 3: PHASE FLOW (Main Decision Tree)

#### STEP 1: ELIGIBILITY CHECK (Pool Building Phase)

**Purpose**: Determine which units can participate in shooting phase  
**Output**: shoot_activation_pool (set of eligible units)

```javascript
For each PLAYER unit:
├── ELIGIBILITY CHECK:
│   ├── unit.HP_CUR > 0? → NO → ❌ Skip (dead unit)
│   ├── unit.player === current_player? → NO → ❌ Skip (wrong player)
│   ├── units_fled.includes(unit.id)? → YES → ❌ Skip (fled unit)
│   ├── Adjacent to enemy unit (melee range 1 hex)?
│   │   ├── YES → 
│   │   │   ├── CAN_ADVANCE = false (cannot advance when adjacent)
│   │   │   ├── weapon_availability_check(weapon_rule, 0, 1) → Build weapon_available_pool
│   │   │   └── weapon_available_pool NOT empty?
│   │   │       ├── YES → CAN_SHOOT = true → Store unit.CAN_SHOOT = true
│   │   │       └── NO → CAN_SHOOT = false → ❌ Skip (no valid actions)
│   │   └── NO →
│   │       ├── CAN_ADVANCE = true → Store unit.CAN_ADVANCE = true
│   │       ├── weapon_availability_check(weapon_rule, 0, 0) → Build weapon_available_pool
│   │       ├── weapon_available_pool NOT empty?
│   │       │   ├── YES → CAN_SHOOT = true → Store unit.CAN_SHOOT = true
│   │       │   └── NO → CAN_SHOOT = false → Store unit.CAN_SHOOT = false
│   │       └── (CAN_SHOOT OR CAN_ADVANCE)?
│   │           ├── YES → Continue (unit has at least one valid action)
│   │           └── NO → ❌ Skip (no valid actions)
│   └── ALL conditions met → ✅ Add to shoot_activation_pool → Highlight unit with green circle
```

#### STEP 2: UNIT_ACTIVABLE_CHECK

**Purpose**: Check if there are units to activate  
**Decision Point**: Is shoot_activation_pool NOT empty?

```javascript
STEP : UNIT_ACTIVABLE_CHECK
├── shoot_activation_pool NOT empty?
│   ├── YES → Pick one unit from shoot_activation_pool:
│   │   ├── Clear valid_target_pool
│   │   ├── Clear TOTAL_ATTACK log
│   │   ├── Determine adjacency:
│   │   │   ├── Unit adjacent to enemy? → YES → unit_is_adjacent = true
│   │   │   └── NO → unit_is_adjacent = false
│   │   ├── weapon_availability_check(weapon_rule, 0, unit_is_adjacent ? 1 : 0) → Build weapon_available_pool
│   │   ├── valid_target_pool_build(weapon_rule, arg2=0, arg3=unit_is_adjacent ? 1 : 0)
│   │   └── valid_target_pool NOT empty?
│   │       ├── YES → SHOOTING ACTIONS AVAILABLE → Go to STEP 3: ACTION_SELECTION
│   │       └── NO → valid_target_pool is empty → Go to STEP 6: EMPTY_TARGET_HANDLING
│   └── NO → End of shooting phase → Advance to charge phase
```

#### STEP 3: ACTION_SELECTION (Initial State - valid_target_pool NOT empty)

**Purpose**: Choose between shoot, advance, or wait  
**Context**: Unit has valid targets available

```javascript
STEP : ACTION_SELECTION (Initial State)
├── Pre-select first available weapon
├── SHOOT_LEFT = selected_weapon.NB
├── Display shooting preview: Blue hexes (LoS and selected_weapon.RNG)
├── Display HP bar blinking animation for units in valid_target_pool
├── Build VALID_ACTIONS list:
│   ├── If unit.CAN_SHOOT = true AND valid_target_pool NOT empty → Add "shoot"
│   ├── If unit.CAN_ADVANCE = true → Add "advance"
│   └── Always add "wait"
├── ❌ INVALID ACTIONS: [move, charge, attack] → end_activation(ERROR, 0, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
└── Execute chosen action:
    ├── "advance" → Go to STEP 4: ADVANCE_ACTION
    ├── "shoot" → Go to STEP 5: SHOOTING_ACTION_SELECTION (normal)
    └── "wait" → Go to STEP 7: WAIT_ACTION
```

**AI vs Human differences:**
- **AI**: Programmatically chooses action from VALID_ACTIONS
- **Human**: Clicks UI elements (advance icon, target, weapon selection icon, or unit icon)

#### STEP 4: ADVANCE_ACTION

**Purpose**: Execute advance movement  
**⚠️ POINT OF NO RETURN** (Human: Click ADVANCE logo)

```javascript
STEP : ADVANCE_ACTION
├── Roll 1D6 → advance_range (from config: advance_distance_range)
├── Display advance_range on unit icon
├── Build valid_advance_destinations (BFS, advance_range, no walls, no enemy-adjacent)
├── Select destination:
│   ├── AI: Chooses best destination
│   └── Human: Left click on valid advance hex OR left/right click on unit icon (cancel)
└── Unit actually moved to different hex?
    ├── YES → Unit advanced:
    │   ├── Mark units_advanced (add unit.id to set)
    │   ├── Log: end_activation(ACTION, 1, ADVANCE, NOT_REMOVED, 1, 0)
    │   ├── Do NOT remove from shoot_activation_pool
    │   ├── Do NOT remove green circle
    │   ├── Clear valid_target_pool
    │   ├── Update capabilities:
    │   │   ├── CAN_ADVANCE = false
    │   │   ├── weapon_availability_check(weapon_rule, 1, 0) → Build weapon_available_pool (only Assault if weapon_rule=1)
    │   │   └── CAN_SHOOT = (weapon_available_pool NOT empty)
    │   ├── Pre-select first available weapon
    │   ├── SHOOT_LEFT = selected_weapon.NB
    │   ├── valid_target_pool_build(weapon_rule, arg2=1, arg3=0) → Note: arg3=0 always after advance
    │   └── valid_target_pool NOT empty AND CAN_SHOOT = true?
    │       ├── YES → SHOOTING ACTIONS AVAILABLE (post-advance) → Go to STEP 5: ADVANCED_SHOOTING_ACTION_SELECTION
    │       └── NO → Unit advanced but no valid targets → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── NO → Unit did not advance → Go back to STEP 3: ACTION_SELECTION
```

#### STEP 5: SHOOTING_ACTION_SELECTION

**Purpose**: Execute shooting sequence  
**Two variants**: Normal (unit has NOT advanced) vs Advanced (post-advance state)

##### STEP 5A: SHOOTING_ACTION_SELECTION (Normal - unit has NOT advanced)

```javascript
STEP : SHOOTING_ACTION_SELECTION (Normal)
├── Display shooting preview
├── Display HP bar blinking animation
├── Human only: Display weapon selection icon (if CAN_SHOOT)
└── Action handling:
    ├── Weapon selection (Human only):
    │   ├── Left click on weapon selection icon → weapon_selection() → Return to this step
    │   └── Continue with current weapon
    ├── Shoot action:
    │   ├── AI: Select best target from valid_target_pool
    │   ├── Human: Left click on target in valid_target_pool
    │   ├── Execute shoot_action(target) → See shoot_action() function above
    │   └── After shoot_action():
    │       ├── If activation ended → Go to UNIT_ACTIVABLE_CHECK
    │       └── Else → Return to this step
    ├── Wait action (Human only):
    │   ├── Left/Right click on active_unit
    │   └── Check if unit has shot with ANY weapon (any weapon.shot = 1)?
    │       ├── YES → end_activation(ACTION, 1, SHOOTING, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │       └── NO → end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── Postpone/Click elsewhere (Human only):
        ├── Left click on another unit in shoot_activation_pool
        ├── Left/Right click anywhere else (treated as potential misclick)
        └── Check if unit has shot with ANY weapon?
            ├── NO → POSTPONE_ACTIVATION() → UNIT_ACTIVABLE_CHECK
            └── YES → Do not end activation automatically (allow user to click active unit to confirm) → Return to this step
```

##### STEP 5B: ADVANCED_SHOOTING_ACTION_SELECTION (Post-advance state)

```javascript
STEP : ADVANCED_SHOOTING_ACTION_SELECTION (Post-advance)
├── Display shooting preview
├── Display HP bar blinking animation
├── Human only: Display weapon selection icon (if CAN_SHOOT)
├── 🎯 VALID ACTIONS: [shoot (if CAN_SHOOT), wait]
├── ❌ INVALID ACTIONS: [advance, move, charge, attack] → end_activation(ERROR, 0, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
└── Action handling:
    ├── Weapon selection (Human only):
    │   ├── Left click on weapon selection icon → weapon_selection() → Return to this step
    │   └── Continue with current weapon
    ├── Shoot action:
    │   ├── AI: Select best target from valid_target_pool
    │   ├── Human: Left click on target in valid_target_pool
    │   ├── Execute shoot_action(target) → See shoot_action() function above
    │   └── After shoot_action():
    │       ├── If activation ended → Go to UNIT_ACTIVABLE_CHECK
    │       └── Else → Return to this step (note: still in ADVANCED state, arg2=1)
    ├── Wait action:
    │   ├── AI: Agent chooses wait
    │   ├── Human: Left/Right click on active_unit
    │   └── Check if unit has shot with ANY weapon?
    │       ├── YES → end_activation(ACTION, 1, SHOOTING, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │       └── NO → Unit has not shot yet (only advanced) → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── Postpone/Click elsewhere (Human only):
        ├── Left click on another unit in shoot_activation_pool
        ├── Left/Right click anywhere else (treated as potential misclick)
        └── Check if unit has shot with ANY weapon?
            ├── NO → POSTPONE_ACTIVATION() → UNIT_ACTIVABLE_CHECK
            └── YES → Do not end activation automatically (allow user to click active unit to confirm) → Return to this step
```

#### STEP 6: EMPTY_TARGET_HANDLING (valid_target_pool is empty)

**Purpose**: Handle case when no valid targets are available  
**Context**: Unit was eligible but has no targets

```javascript
STEP : EMPTY_TARGET_HANDLING
└── unit.CAN_ADVANCE = true?
    ├── YES → Only action available is advance:
    │   ├── Human: Click ADVANCE logo → ⚠️ POINT OF NO RETURN
    │   ├── Execute player_advance() → unit_advanced (boolean)
    │   └── unit_advanced = true?
    │       ├── YES → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │       └── NO → end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── NO → unit.CAN_ADVANCE = false → No valid actions available:
        └── end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
```

#### STEP 7: WAIT_ACTION (Initial state, no shooting available)

**Purpose**: End activation without action  
**Context**: Player chooses to wait (no valid actions or player decision)

```javascript
STEP : WAIT_ACTION
├── AI: Agent chooses wait
├── Human: Player chooses wait
└── end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
```

---

### 🔄 SECTION 4: FLOW SUMMARY & STEP TRANSITIONS

#### Complete Step Flow
```
UNIT_ACTIVABLE_CHECK
  → ACTION_SELECTION (if valid_target_pool NOT empty)
  → [ADVANCE_ACTION | SHOOTING_ACTION_SELECTION | WAIT_ACTION]
  → [ADVANCED_SHOOTING_ACTION_SELECTION] (if advanced)
  → [EMPTY_TARGET_HANDLING] (if valid_target_pool empty)
  → UNIT_ACTIVABLE_CHECK
  → (repeat until pool empty) → End of shooting phase
```

#### Key Step Transitions
- **UNIT_ACTIVABLE_CHECK → ACTION_SELECTION**: valid_target_pool NOT empty
- **UNIT_ACTIVABLE_CHECK → EMPTY_TARGET_HANDLING**: valid_target_pool is empty
- **ACTION_SELECTION → ADVANCE_ACTION**: Player/AI chooses advance
- **ACTION_SELECTION → SHOOTING_ACTION_SELECTION**: Player/AI chooses shoot
- **ACTION_SELECTION → WAIT_ACTION**: Player/AI chooses wait
- **ADVANCE_ACTION → ADVANCED_SHOOTING_ACTION_SELECTION**: Unit advanced AND valid_target_pool NOT empty AND CAN_SHOOT = true
- **ADVANCE_ACTION → UNIT_ACTIVABLE_CHECK**: Unit advanced but no valid targets
- **SHOOTING_ACTION_SELECTION → SHOOTING_ACTION_SELECTION**: Multi-shot sequence continues
- **SHOOTING_ACTION_SELECTION → UNIT_ACTIVABLE_CHECK**: All shots fired or no targets remain
- **ADVANCED_SHOOTING_ACTION_SELECTION → ADVANCED_SHOOTING_ACTION_SELECTION**: Multi-shot sequence continues (post-advance)
- **ADVANCED_SHOOTING_ACTION_SELECTION → UNIT_ACTIVABLE_CHECK**: All shots fired or no targets remain
- **EMPTY_TARGET_HANDLING → UNIT_ACTIVABLE_CHECK**: Advance executed or wait chosen
- **WAIT_ACTION → UNIT_ACTIVABLE_CHECK**: Always (end activation)

---

### 📖 SECTION 5: CONCEPTUAL EXPLANATIONS

#### Target Restrictions Logic

**Valid Target Requirements (ALL must be true):**
1. **Range check**: Enemy within unit's selected_weapon.RNG hexes (varies by weapon)
2. **Line of sight**: No wall hexes between shooter and target
3. **Fight exclusion**: Enemy NOT adjacent to shooter (adjacent = melee fight)
4. **Friendly fire prevention**: Enemy NOT adjacent to any friendly units

**Target becomes invalid when:**
- Enemy dies during shooting action
- Enemy moves out of range (rare during shooting phase)
- Line of sight becomes blocked (rare during shooting phase)

**Why These Restrictions:**
- **Weapon limitations**: Ranged weapons have effective range
- **Visual requirement**: Cannot shoot what cannot be seen
- **Engagement types**: Adjacent = melee fight, not shooting
- **Safety**: Prevent accidental damage to own forces

#### Multiple Shots Logic

**Multi-Shot Rules:**
- **All shots in one action**: Selected ranged weapon's NB shots fired as single activation
- **Dynamic targeting**: Each shot can target different valid enemies
- **Sequential resolution**: Resolve each shot completely before next
- **Target death handling**: If target dies, remaining shots can retarget
- **Slaughter handling**: If no more "Valid target" is available, the activation ends immediately (remaining shots cancelled)

**Why Multiple Shots Work This Way:**
- **Action efficiency**: One activation covers all shots
- **Tactical flexibility**: Can spread damage across enemies
- **Realistic timing**: Rapid fire happens quickly
- **Dynamic adaptation**: React to changing battlefield

**Example 1:**
```
Marine (selected ranged weapon: NB = 2) faces two wounded Orks (both HP_CUR 1)
Shot 1: Target Ork A, kill it
Shot 2: Retarget to Ork B, kill it
Result: Eliminate two threats in one action through dynamic targeting
```

**Example 2 (Slaughter handling):**
```
Marine (selected ranged weapon: NB = 2) faces one wounded Ork (HP_CUR 1) which is the only "Valid target"
Shot 1: Target the Ork, kill it
Shot 2: No more "Valid target" available, remaining shots are cancelled
Result: Avoid a shooting unit to be stuck because it has no more "Valid target" while having remaining shots to perform
```

#### Advance Distance Logic

**1D6 Roll System:**
- **When rolled**: When advance action is selected (at activation start)
- **Distance determination**: Roll determines maximum advance distance (1 to `advance_distance_range` from config)
- **Variability purpose**: Adds uncertainty and tactical risk to advance decisions

**Advance Distance Mechanics:**
- **Pathfinding**: Uses same BFS pathfinding as movement phase
- **Restrictions**: Cannot move through walls, cannot move to/through hexes adjacent to enemies
- **Destination selection**: Player/AI selects valid destination hex within rolled range
- **Marking rule**: Unit only marked as "advanced" if it actually moves to a different hex (staying in place doesn't count)

**Why Random Distance:**
- **Tactical uncertainty**: Cannot guarantee exact positioning after advance
- **Risk/reward decisions**: Longer advances closer to enemy but cannot shoot (unless Assault weapon)
- **Game balance**: Prevents guaranteed advance+shoot combinations

**Post-Advance Restrictions:**
- **Shooting**: ❌ Forbidden unless weapon has "Assault" rule
- **Charging**: ❌ Forbidden (unit marked in `units_advanced` set)
- **Fighting**: ✅ Allowed normally

**Example:**
```
Marine 5 hexes from enemy, needs to get closer to shoot
Roll 1D6 → Gets 4 (advance_distance_range = 6)
Can advance up to 4 hexes toward enemy
Decision: Advance to get within shooting range, but cannot shoot this turn (no Assault weapon)
Trade-off: Better position next turn vs losing shooting opportunity this turn
```

**Irreversibility:**
- Once advance logo clicked, unit cannot shoot (point of no return)
- Exception: Weapons with "Assault" rule allow shooting after advance
- Strategic importance: Must commit to advance before knowing exact distance

#### Key Differences Between AI and Human Players

1. **Target Selection**: AI automatically chooses best target; Human clicks on target
2. **UI Display**: Both AI and Human see blue preview (see UI Display Constants above)
3. **Weapon Selection**: Human can change weapons via UI; AI pre-selects best weapon
4. **Action Selection**: AI chooses programmatically; Human clicks UI elements
5. **Postpone Logic**: Only Human can postpone activation (click elsewhere)

---

### ✅ VALIDATION CHECKLIST

**All features preserved:**
- ✅ Advance action support
- ✅ Weapon rules (ASSAULT, PISTOL)
- ✅ Multi-shot sequences
- ✅ Dynamic targeting
- ✅ Slaughter handling
- ✅ Postpone logic (Human only)
- ✅ Adjacent enemy restrictions
- ✅ Friendly fire prevention
- ✅ Line of sight checks
- ✅ Range checks
- ✅ Weapon availability filtering
- ✅ CAN_SHOOT / CAN_ADVANCE flags
- ✅ Post-advance shooting restrictions
- ✅ Unit state tracking (units_advanced, units_shot)

---

### 📝 Document Notes

**This is an optimized version of the Shooting Phase documentation from `AI_TURN.md`.**

**Optimizations made:**
- ✅ All features preserved (no functionality removed)
- ✅ Clear hierarchical structure: Variables → Functions → Flow → Concepts
- ✅ Unified function definitions (AI/Human differences marked explicitly)
- ✅ Step-based flow control (numbered steps for clarity)
- ✅ Complete reference tables for function arguments
- ✅ Enhanced readability with better organization
- ✅ Clarified state management and transitions
- ✅ Better separation of concerns (functions vs flow)

**For complete original decision tree reference**, see `AI_TURN.md` section "🎯 SHOOTING PHASE Decision Tree" (lines 362-951).



