# AI TURN SEQUENCE - Ultimate Claude Understanding Guide (Streamlined)

## Claude Search Optimization

**Search Terms**: turn sequence, phase management, eligibility rules, step counting, unit activation, movement phase, shooting phase, charge phase, fight phase, tracking sets, phase transitions, decision logic, game state management

**Core Concepts**: sequential activation, dynamic validation, atomic actions, phase completion, turn progression, episode lifecycle, state consistency, rule interactions, decision frameworks, validation checkpoints

---

## 🎯 CLAUDE LEARNING OBJECTIVES

This document teaches Claude to **understand the logic** behind the Warhammer 40K turn system, enabling intelligent decision-making and flexible implementation across different contexts.

**Learning Approach:**
1. **Grasp fundamental principles** - Why rules exist and how they interact
2. **Master decision logic** - When and why to apply specific rules  
3. **Understand state relationships** - How game state changes affect rule application
4. **Recognize patterns** - Common scenarios and their resolution logic
5. **Validate understanding** - Self-check comprehension at key points

---

## 📋 NAVIGATION & LEARNING PATH

- [Core Game Logic](#-core-game-logic) - Essential concepts for understanding
- [Episode & Turn Concepts](#-episode--turn-concepts) - Game lifecycle logic
- [State Management Principles](#-state-management-principles) - How game state works
- [Movement Phase Logic](#-movement-phase-logic) - Movement rules and reasoning
- [Shooting Phase Logic](#-shooting-phase-logic) - Shooting rules and targeting
- [Charge Phase Logic](#-charge-phase-logic) - Charge mechanics and distance
- [Fight Phase Logic](#-fight-phase-logic) - Fight phases and alternating turns
- [Tracking System Logic](#-tracking-system-logic) - How the game remembers actions
- [Key Scenarios](#-key-scenarios) - Essential decision examples
- [Rule Interactions](#-rule-interactions) - How different rules affect each other
- [Claude Validation Points](#-claude-validation-points) - Understanding checkpoints
- [Decision Framework](#-decision-framework) - Logical patterns for any implementation
- [Implementation Validation](#-implementation-validation) - Validation reference
---

## 🧠 CORE GAME LOGIC

### Game Structure Understanding

**The Big Picture:**
- Players take **complete turns** (all 4 phases) before opponent acts
- Each phase has **specific purposes** and **different eligibility rules**
- Units act **one at a time** within each phase (sequential activation)
- Game state **changes dynamically** as units act

**Why This Structure Exists:**
- **Turn-based fairness**: Each player gets equal opportunity
- **Phase specialization**: Different tactical decisions in each phase
- **Sequential clarity**: No simultaneous action confusion
- **State consistency**: Game state remains coherent throughout

### Sequential Activation Logic

**Core Principle**: One unit completes its entire action before the next unit begins.

**Why Sequential Matters:**
- **Dynamic targeting**: Available targets change as units die
- **Position dependency**: Unit positions affect other units' options
- **Resource tracking**: Actions consume limited resources (shots, moves, etc.)
- **Tactical cascading**: One unit's action creates opportunities/threats for others

**Activation Sequence Logic:**
```
Unit Selection → Eligibility Check → Action Execution → State Update → Next Unit
```

**Key Understanding**: Eligibility is checked **when unit becomes active**, not when action executes.

### Phase Completion Logic

**Central Question**: "When does a phase end?"

**Answer**: When **no more eligible units remain** for any player.

**Why Not Step-Based**: Steps measure player actions, but phases end based on game state (unit availability).

**Logic Pattern:**
```
For Each Current Player Unit:
    Check if unit meets phase-specific eligibility criteria
    If ANY unit is eligible: Phase continues
If NO units are eligible: Phase ends, advance to next phase
```

**Claude Key Insight**: Phase transitions are **deterministic** based on unit eligibility, not arbitrary step counts.

---

## 📅 EPISODE & TURN CONCEPTS

### Episode Lifecycle Logic

**Episode Boundaries:**
- **Start**: First Player 0 unit begins movement (game begins)
- **End**: One player has no living units OR maximum turns reached
- **Purpose**: Complete game from start to victory/defeat condition

**Turn Progression Sequence:**
```
Turn 1: P0 Move → P0 Shoot → P0 Charge → P0 Fight → P1 Move → P1 Shoot → P1 Charge → P1 Fight
Turn 2: P0 Move (Turn++ here) → P0 Shoot → P0 Charge → P0 Fight → P1 Move → P1 Shoot → P1 Charge → P1 Fight
Turn 3: P0 Move (Turn++ here) → ...
```

**Turn Numbering Logic:**
- **Turn 1**: When Player 0 first moves
- **Turn 2**: When Player 0 moves again (after Player 1's complete turn)
- **Pattern**: Turns increment at Player 0 movement phase start

**Why P0-Centric Numbering:**
- **Consistency**: Always same player triggers turn increment
- **Clarity**: Unambiguous turn boundaries
- **Convention**: Standard in turn-based games

---

## 🏗️ STATE MANAGEMENT PRINCIPLES

### Single Source of Truth

**Core Principle**: Only **one game_state object** exists per game.

**State Reference Pattern:**
```
game_state ← Single authoritative object
    ↗ ↗ ↗
    │ │ └── Component C references same object
    │ └──── Component B references same object  
    └────── Component A references same object
```

**Why Single Source:**
- **Consistency**: All components see same data
- **Synchronization**: No conflicts between different state copies
- **Performance**: No expensive state copying operations
- **Debugging**: Single point of truth for state inspection

### Field Naming Logic

**Uppercase Convention**: All unit statistics use UPPERCASE field names.

**Field Categories:**
- **Movement**: MOVE, col, row
- **Shooting**: RNG_NB, RNG_RNG, RNG_ATK, RNG_STR, RNG_DMG, RNG_AP
- **Fight**: CC_NB, CC_RNG, CC_ATK, CC_STR, CC_DMG, CC_AP  
- **Defense**: HP_CUR, HP_MAX, T, ARMOR_SAVE, INVUL_SAVE

**⚠️ CRITICAL**: Must use UPPERCASE field names consistently across all components.

---

## GENERIC FUNCTIONS

```javascript
END OF ACTIVATION PROCEDURE
end_activation (Arg1, Arg2, Arg3, Arg4, Arg5)
├── Arg1 = ?
│   ├── CASE Arg1 = ACTION → log the action
│   ├── CASE Arg1 = WAIT → log the wait action
│   └── CASE Arg1 = NO → do not log the action
├── Arg2 = 1 ?
│   ├── YES → +1 step
│   └── NO → No step increase
├── Arg3 = 
│	├── CASE Arg3 = MOVE → Mark as units_moved
│	├── CASE Arg3 = FLED → Mark as units_moved AND Mark as units_fled
│	├── CASE Arg3 = SHOOTING → Mark as units_shot
│	├── CASE Arg3 = CHARGE → Mark as units_charged
│	└── CASE Arg3 = FIGHT → Mark as units_fought
├── Arg4 = ?
│	├── CASE Arg4 = MOVE → Unit removed from move_activation_pool
│	├── CASE Arg4 = FLED → Unit removed from move_activation_pool
│	├── CASE Arg4 = SHOOTING → Unit removed from shoot_activation_pool
│	├── CASE Arg4 = CHARGE → Unit removed from charge_activation_pool
│	└── CASE Arg4 = FIGHT → Unit removed from fight_activation_pool
├── Arg5 = 1 ?
│   ├── YES → log the error
│   └── NO → No action
└── Remove the green circle around the unit's icon

ATTACK ACTION
attack_sequence(Arg)
├── Arg = RNG ?
│   └── Rempace all <OFF> occurences by RNG
├── Arg = CC ?
│   └── Rempace all <OFF> occurences by CC
├── Hit roll → hit_roll >= attacker.<OFF>_ATK
│   ├── MISS
│   │   ├── Arg = RNG ?
│   │   │   └── ATTACK_LOG = "Unit <activeUnit ID> SHOT Unit <selectedTarget unit ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) : MISSED !"
│   │   └── Arg = CC ?
│   │       └── ATTACK_LOG = "Unit <activeUnit ID> FOUGHT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) : MISSED !"
│   └── HIT → hits++ → Continue to wound roll
│       └── Wound roll → wound_roll >= calculate_wound_target()
│           ├── FAIL
│           │   ├── Arg = RNG ?
│           │   │   └── ATTACK_LOG = "Unit <activeUnit ID> SHOT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) : FAILED !"
│           │   └── Arg = CC ?
│           │       └── ATTACK_LOG = "Unit <activeUnit ID> FOUGHT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) : FAILED !"
│           └── WOUND → wounds++ → Continue to save roll
│               ├── Save roll → save_roll >= calculate_save_target()
│               │   ├── SAVE
│               │   │   ├── Arg = RNG ?
│               │   │   │   └── ATTACK_LOG = "Unit <activeUnit ID> SHOT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) : SAVED !"
│               │   │   └── Arg = CC ?
│               │   │       └── ATTACK_LOG = "Unit <activeUnit ID> FOUGHT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) : SAVED !"
│               │   └── FAIL → failed_saves++ → Continue to damage
│               └── Damage application:
│                   ├── damage_dealt = attacker.<OFF>_DMG
│                   ├── total_damage += damage_dealt
│                   ├── ⚡ IMMEDIATE UPDATE: selected_target.HP_CUR -= damage_dealt
│                   └── selected_target.HP_CUR <= 0 ?
│                       ├── NO
│                           ├── Arg = RNG ?
│                           │   └── ATTACK_LOG = "Unit <activeUnit ID> SHOT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <OFF>_DMG DAMAGE DELT !"
│                           └── Arg = CC ?
│                               └── ATTACK_LOG = "Unit <activeUnit ID> FOUGHT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <OFF>_DMG DAMAGE DELT !"
│                       └── YES → current_target.alive = False
│                           ├── Arg = RNG ?
│                           │   └── ATTACK_LOG = "Unit <activeUnit ID> SHOT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <OFF>_DMG delt : Unit <selectedTarget ID> DIED !"
│                           └── Arg = CC ?
│                               └── ATTACK_LOG = "Unit <activeUnit ID> FOUGHT Unit <selectedTarget ID> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <OFF>_DMG delt : Unit <selectedTarget ID> DIED !"
└── Return: TOTAL_ATTACK_LOG
```

## 🏃 MOVEMENT PHASE Decision Tree

### MOVEMENT PHASE Decision Tree

```javascript
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
```

### Movement Restrictions Logic

**Forbidden Destinations (Cannot Move To AND through):**
- **Occupied hexes**: Other units prevent movement
- **Enemy adjacent hexes**: Adjacent to enemy = entering fight
- **Wall hexes**: Terrain blocks movement

**Why These Restrictions:**
- **Spatial logic**: Physical objects cannot overlap
- **Engagement rules**: Adjacent = fight = different phase handles it
- **Terrain realism**: Walls block movement paths

### Flee Mechanics Logic

- **Trigger**: Move action started from hex adjacent to enemy unit
- **Implementation**: `wasAdjacentToEnemy`
- **Note**: Unit automatically not adjacent at destination (move restrictions prevent adjacent destinations)
- **Why This Works**: Movement restrictions forbid destinations adjacent to enemies, so checking only the starting position is sufficient to detect flee

**Flee Consequences:**
- **Shooting phase**: Cannot shoot (disorganized from retreat)
- **Charge phase**: Cannot charge (poor position/morale)
- **Fight phase**: Can fight normally (no restriction)
- **Duration**: Until end of current turn only

**Why Flee Exists:**
- **Tactical choice**: Trade current effectiveness for survival
- **Risk/reward**: Escape death but lose capabilities
- **Strategic depth**: Creates meaningful positioning decisions

**Key Example:**
```
Wounded Marine (HP_CUR 1) adjacent to healthy Ork
Flee option: Survive to act later in the game, but lose turn effectiveness
Stay option: 80% chance of death but maintain capabilities
Decision factors: Unit value, importance of actions this turn, long term strategy, alternative threats
  ```

## 🎯 SHOOTING PHASE Decision Tree

### SHOOTING PHASE Decision Tree

```javascript
For each PLAYER unit
├── ELIGIBILITY CHECK (Pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fled.includes(unit.id)?
│   │   └── YES → ❌ Fled unit (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ In fight (Skip, no log)
│   ├── unit.RNG_NB > 0?
│   │   └── NO → ❌ No ranged weapon (Skip, no log)
│   ├── Has LOS to enemies within RNG_RNG?
│   │   └── NO → ❌ No valid targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to shoot_activation_pool → Highlight the unit with a green circle around its icon
├── STEP : UNIT_ACTIVABLE_CHECK → is shoot_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → pick one unit in shoot_activation_pool
│   │   │   ├── Clear any unit remaining in valid_target_pool
│   │   │   ├── Clear TOTAL_ATTACK log
│   │   │   ├── SHOOT_LEFT = RNG_NB
│   │   │   └── While SHOOT_LEFT > 0
│   │   │       ├── Build valid_target_pool : All enemies within range AND in Line of Sight AND having HP_CUR > 0 → added to valid_target_pool
│   │   │       └── valid_target_pool NOT empty ?
│   │   │           ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │   │           │   ├── Display the shooting preview (all the hexes with LoS and RNG_RNG are red)
│   │   │           │   └── Display the HP bar blinking animation for every unit in valid_target_pool
│   │   │           │   ├── 🎯 VALID ACTIONS: [shoot, wait]
│   │   │           │   ├── ❌ INVALID ACTIONS: [move, charge, attack] → end_activation (ERROR, 0, PASS, SHOOTING)
│   │   │           │   └── AGENT ACTION SELECTION → Choose shoot?
│   │   │           │       ├── YES → ✅ VALID → Execute shoot
│   │   │           │       ├── Agent choose a target in valid_target_pool
│   │   │           │       │   ├── Execute attack_sequence(RNG)
│   │   │           │       │   ├── SHOOT_LEFT -= 1
│   │   │           │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │   │           │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │   │           │       │   ├── selected_target survives → Continue
│   │   │           │       │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │           │       │   └── end_activation (ACTION, 1, SHOOTING, SHOOTING)
│   │   │           │       └── NO → Agent chooses: wait?
│   │   │           │           ├── YES → ✅ VALID → Execute wait action
│   │   │           │           │   └── end_activation (WAIT, 1, PASS, SHOOTING)
│   │   │           │           └── NO → Agent chooses invalid action (move/shoot/attack)?
│   │   │           │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, SHOOTING)
│   │   │           └── NO → end_activation (PASS, 0, PASS, SHOOTING)
│   │   └── NO → Human player → STEP : UNIT_ACTIVATION → player activate one unit from shoot_activation_pool by left clicking on it
│   │       ├── Clear any unit remaining in valid_target_pool
│   │       ├── Clear TOTAL_ATTACK log
│   │       ├── SHOOT_LEFT = RNG_NB
│   │       ├── While SHOOT_LEFT > 0
│   │       │   ├── Build valid_target_pool : All enemies within range AND in Line of Sight AND having HP_CUR > 0 → added to valid_target_pool
│   │       │   └── valid_target_pool NOT empty ?
│   │       │       ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │       │       │   ├── STEP : PLAYER_ACTION_SELECTION
│   │       │       │   ├── Display the shooting preview (all the hexes with LoS and RNG_RNG are red)
│   │       │       │   └── Display the HP bar blinking animation for every unit in valid_target_pool
│   │       │       │       ├── Left click on a target in valid_target_pool
│   │       │       │       │   ├── Execute attack_sequence(RNG)
│   │       │       │       │   ├── SHOOT_LEFT -= 1
│   │       │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │       │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │       │       │       │   ├── selected_target survives → Continue
│   │       │       │       │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── Left click on another unit in shoot_activation_pool ?
│   │       │       │       │   └── SHOOT_LEFT = RNG_NB ?
│   │       │       │       │       ├── YES → Postpone the shooting phase for this unit
│   │       │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       │       └── NO → The unit must end its activation when started
│   │       │       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │       ├── Left click on the active_unit → No effect
│   │       │       │       ├── Right click on the active_unit
│   │       │       │       │    └── SHOOT_LEFT = RNG_NB ?
│   │       │       │       │       ├── NO → end_activation (ACTION, 1, SHOOTING, SHOOTING)
│   │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       │       └── YES → end_activation (WAIT, 1, PASS, SHOOTING)
│   │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       └── Left OR Right click anywhere else on the board
│   │       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       └── NO → SHOOT_LEFT = RNG_NB ?
│   │       │           ├── NO → shot the last target available in valid_target_pool → end_activation (ACTION, 1, SHOOTING, SHOOTING)
│   │       │           └── YES → no target available in valid_target_pool at activation → no shoot → end_activation (PASS, 1, PASS, SHOOTING)
│   │       └── End of shooting → end_activation (ACTION, 1, SHOOTING, SHOOTING)
│   └── No more activable units → pass
└── End of shooting phase → Advance to charge phase
```

### Target Restrictions Logic

**Valid Target Requirements (ALL must be true):**

1. **Range check**: Enemy within unit's RNG_RNG hexes (varies by weapon)
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

### Multiple Shots Logic

**Multi-Shot Rules:**
- **All shots in one action**: RNG_NB shots fired as single activation
- **Dynamic targeting**: Each shot can target different valid enemies
- **Sequential resolution**: Resolve each shot completely before next
- **Target death handling**: If target dies, remaining shots can retarget
- **Slaughter handling**: If no more "Valid target" is available, the activation ends

**Why Multiple Shots Work This Way:**
- **Action efficiency**: One activation covers all shots
- **Tactical flexibility**: Can spread damage across enemies
- **Realistic timing**: Rapid fire happens quickly
- **Dynamic adaptation**: React to changing battlefield

**Example 1:**
```
Marine (RNG_NB = 2) faces two wounded Orks (both HP_CUR 1)
Shot 1: Target Ork A, kill it
Shot 2: Retarget to Ork B, kill it
Result: Eliminate two threats in one action through dynamic targeting
```
**Example 2:**
```
Marine (RNG_NB = 2) faces one wounded Orks (HP_CUR 1) which is the only "Valid target"
Shot 1: Target the Ork, kill it
Shot 2: No more "Valid target" available, remaining shots are cancelled
Result: Avoid a shooting unit to be stuck because it as no more "Valid target" while having remaining shots to perform
```
---

## ⚡ CHARGE PHASE 

### CHARGE PHASE Decision Tree

```javascript
For each unit
├── ELIGIBILITY CHECK (Pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fled.includes(unit.id)?
│   │   └── YES → ❌ Fled unit (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ Already in fight (Skip, no log)
│   ├── Enemies exist within charge_max_distance hexes?
│   │   └── NO → ❌ No charge targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to charge_activation_pool
├── STEP : UNIT_ACTIVABLE_CHECK → Is charge_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → pick one unit in charge_activation_pool → Roll 2d6 charge dice at START of activation
│   │   │   ├── Roll 2d6 to define charge_range value at START of activation
│   │   │   ├── Build valid_charge_destinations_pool (reacheable hexes adjacent to enemy unit using BFS pathfinding AND within charge_range distance)
│   │   │   │   └── valid_charge_destinations_pool NOT empty ?
│   │   │   │       ├── YES → CHARGE PHASE ACTIONS AVAILABLE
│   │   │   │       │   ├── 🎯 VALID ACTIONS: [charge, wait]
│   │   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, attack] → end_activation (ERROR, 0, PASS, CHARGE)
│   │   │   │       │   └── AGENT ACTION SELECTION → Choose charge?
│   │   │   │       │       ├── YES → ✅ VALID → Execute charge
│   │   │   │       │       │   ├── Select destination hex from valid_charge_destinations_pool
│   │   │   │       │       │   ├── Move unit to destination
│   │   │   │       │       │   └── end_activation (ACTION, 1, CHARGE, CHARGE)
│   │   │   │       │       └── NO → Agent chooses: wait?
│   │   │   │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │   │       │           │   └── end_activation (WAIT, 1, PASS, CHARGE)
│   │   │   │       │           └── NO → Agent chooses invalid action (move/shoot/attack)?
│   │   │   │       │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, CHARGE)
│   │   │   │       └── NO → end_activation (PASS, 0, PASS, CHARGE)
│   │   │   └── Discard charge_range roll (whether used or not)
│   │   └── NO → Human player → STEP : UNIT_ACTIVATION → player activate one unit by left clicking on it
│   │       ├── If any, cancel the Highlight of the hexes in valid_charge_destinations_pool
│   │       ├── Player activate one unit by left clicking on it
│   │       ├── Roll 2d6 to define charge_range value at START of activation
│   │       ├── Build valid_charge_destinations_pool (hexes adjacent to enemy, reacheable using BFS pathfinding within charge_range distance)
│   │       │   └── valid_charge_destinations_pool not empty ?
│   │       │       ├── YES → STEP : PLAYER_ACTION_SELECTION
│   │       │       │   ├── Highlight the valid_charge_destinations_pool hexes by making them orange
│   │       │       │   └── Player select the action to execute
│   │       │       │       ├── Left click on a hex in valid_charge_destinations_pool → Move the icon of the unit to the selected hex
│   │       │       │       │   ├── end_activation (ACTION, 1, CHARGE, CHARGE)
│   │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       ├── Left click on the active_unit → Charge postponed
│   │       │       │       │   └── GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       ├── Right click on the active_unit → Charge cancelled
│   │       │       │       │   ├── end_activation (PASS, 0, PASS, CHARGE)
│   │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       ├── Left click on another unit in activation pool → Charge postponed
│   │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │       └── Left OR Right click anywhere else on the board → Cancel charge hex selection
│   │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       └── NO → end_activation (PASS, 0, PASS, CHARGE)
│   │       └── Discard charge_range roll (whether used or not)
│   └── NO → If any, cancel the Highlight of the hexes in valid_charge_destinations_pool
│       └── No more activable units → pass
└── End of charge phase → Advance to Fight Phase
```

### Charge Timing Logic

**When 2d6 is Rolled**: Immediately when unit is selected by its player
**Charge roll duration**: The charge roll value is discarded at the end of the unit's activation

### Charge Distance Logic

**2D6 Roll System:**
- **When rolled**: When unit becomes eligible for charge (not when action chosen)
- **Distance determination**: Roll determines how far unit can charge this activation
- **Variability purpose**: Adds uncertainty and risk to charge decisions

**Charge Distance Mechanics:**
- **Target Detection**: Enemy units within `charge_max_distance` hexes (*via pathfinding*) are eligible charge targets
- **Roll Success**: 2D6 roll must equal or exceed distance to closest hex adjacent to target (*via pathfinding*)
- **Example**: Enemy Ork 8 hexes away, closest adjacent hex is 7 hexes away → need 7+ on 2D6 to charge
- **Why the Difference**: You charge TO a hex adjacent to the enemy, not TO the enemy itself

**Concrete Example:**

**Why Random Distance:**
- **Tactical uncertainty**: Cannot guarantee successful charges
- **Risk/reward decisions**: Longer charges more likely to fail
- **Game balance**: Prevents guaranteed charge combinations

**Example:**
```
Marine 7 hexes from the closest hex adjacent to an Ork (average charge distance)
Roll 6 or less: Charge fails (42% chance)
Roll 7+: Charge succeeds, gains fight priority (58% chance)
Decision: Weigh 42% failure risk vs fight advantage gained
```

### Charge Priority Logic

**Fight Priority Benefit:**
- **Sub-phase 1**: Charging units attack first in fight phase
- **Tactical advantage**: Can eliminate enemies before they fight back

**Why Charging Units Fight First:**
- **Momentum**: Charge gives initiative in fight
- **Tactical exposure**: Positioning for a charge often exposes the unit to deadly enemy fire during the opponent's turn
- **Risk compensation**: First strike in fight compensates for the vulnerability incurred when moving into charge position

---

## ⚔️ FIGHT PHASE LOGIC

### Fight Phase Overview

**Two-Part Structure:**
1. **Charging Priority** (Sub-phase 1): Current player's charging units attack first
2. **Alternating Fight** (Sub-phase 2): Remaining units alternate between players

**Key Principles:**
- **Charge Reward**: Successful charges grant first-strike advantage
- **Mutual Fight**: Both players' units can act (unique to fight phase)
- **Sequential Resolution**: Complete one unit's attacks before next unit acts
- **Target Validation**: Check for adjacent enemies before each attack

### FIGHT Decision Tree

```javascript
Start of the Figh Phase:
│
│   ##### Sub-Phase 1 : Charging units attack first
│
├── For each unit : ELIGIBILITY CHECK (Pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_charged.includes(unit.id)?
│   │   └── NO → ❌ Not a charging unit (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── NO → ❌ No fight targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to charging_activation_pool
│
├── charging_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → pick one unit from charging_activation_pool → FIGHT PHASE SUB-PHASE 1 ACTION AVAILABLE
│   │   │   ├── Clear any unit remaining in valid_target_pool
│   │   │   ├── Clear TOTAL_ATTACK_LOG
│   │   │   ├── ATTACK_LEFT = CC_NB
│   │   │   ├── While ATTACK_LEFT > 0
│   │   │   │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0 → added to valid_target_pool
│   │   │   │   └── valid_target_pool NOT empty ?
│   │   │   │       ├── YES → FIGHT PHASE ACTIONS AVAILABLE
│   │   │   │       │   ├── 🎯 VALID ACTIONS: [attack]
│   │   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT)
│   │   │   │       │   └── AGENT ACTION SELECTION → Choose attack?
│   │   │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│   │   │   │       │       │   ├── ATTACK_LEFT -= 1
│   │   │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │   │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │   │   │       │       │   └── selected_target survives → Continue
│   │   │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │   │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT)
│   │   │   │       └── NO → ATTACK_LEFT = CC_NB ?
│   │   │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │   │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (PASS, 1, PASS, FIGHT)
│   │   │   ├── Return: TOTAL_ACTION log
│   │   │   └── end_activation (ACTION, 1, FIGHT, FIGHT)
│   │   └── NO → Human player → STEP : UNIT_ACTIVATION → player activate one unit from charging_activation_pool by left clicking on it
│   │       ├── Clear any unit remaining in valid_target_pool
│   │       ├── Clear TOTAL_ATTACK_LOG
│   │       ├── ATTACK_LEFT = CC_NB
│   │       ├── While ATTACK_LEFT > 0
│   │       │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0 → added to valid_target_pool
│   │       │   └── valid_target_pool NOT empty ?
│   │       │       ├── YES → STEP : PLAYER_ACTION_SELECTION
│   │       │       │   ├── Left click on a target in valid_target_pool → Display selected_target confirmation (HP bar blinking + attack preview)
│   │       │       │   │   ├── Left click SAME selected_target again → Confirm attack
│   │       │       │   │   │   ├── Execute attack_sequence(CC)
│   │       │       │   │   │   ├── ATTACK_LEFT -= 1
│   │       │       │   │   │   ├── Concatenate Return to TOTAL_ACTION log
│   │       │       │   │   │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │       │       │   │   │   ├── selected_target survives → Continue
│   │       │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │   │   ├── Left click DIFFERENT target in valid_target_pool → Switch selected_target confirmation
│   │       │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION (with new selected_target highlighted)
│   │       │       │   │   ├── Left click on another unit in charging_activation_pool ?
│   │       │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│   │       │       │   │   │       ├── YES → Postpone the fight phase for this unit
│   │       │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │   │   │       └── NO → The unit must end its activation when started
│   │       │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │   │   ├── Left click on the active_unit
│   │       │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │   │   ├── Right click on the active_unit
│   │       │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│   │       │       │   │   │       ├── YES → Postpone the fight phase for this unit
│   │       │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │   │   │       └── NO → The unit must end its activation when started
│   │       │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION : the unit must attack as long as it can and it has available targets
│   │       │       │   │   └── Left OR Right click anywhere else on the board → Cancel selected_target selection → Return to target selection
│   │       │       │   │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │   ├── Left click on another unit in charging_activation_pool ?
│   │       │       │   │   └── ATTACK_LEFT = CC_NB ?
│   │       │       │   │       ├── YES → Postpone the Fight Phase for this unit
│   │       │       │   │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │   │       └── NO → The unit must end its activation when started
│   │       │       │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │   ├── Left click on the active_unit → No effect
│   │       │       │   ├── Right click on the active_unit
│   │       │       │   │       └── ATTACK_LEFT = CC_NB ?
│   │       │       │   │           ├── YES → Postpone the Fight Phase for this unit
│   │       │       │   │           │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │       │       │   │           └── NO → The unit must end its activation when started
│   │       │       │   │               └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │       │       │   └── Left OR Right click anywhere else on the board
│   │       │       │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │   │       └── NO → ATTACK_LEFT = CC_NB ?
│   │   │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │       │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (PASS, 1, PASS, FIGHT)
│   │       ├── Return: TOTAL_ACTION log
│   │       └── end_activation (ACTION, 1, FIGHT, FIGHT)
│   └── NO → All charging units processed → GO TO STEP : ATLERNATE_FIGHT
│
│   ##### Sub-Phase 2 : Alternate activation
│
├── ACTIVE PLAYER ELIGIBILITY CHECK (Pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fought.includes(unit.id)?
│   │   └── YES → ❌ Already fought (Skip, no log)
│   ├── units_charged.includes(unit.id)?
│   │   └── YES → ❌ Already acted in charging sub-phase (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── NO → ❌ No fight targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to active_alternating_activation_pool
│
├── NON-ACTIVE PLAYER ELIGIBILITY CHECK (Pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── YES → ❌ Wrong player (Skip, no log)
│   ├── units_fought.includes(unit.id)?
│   │   └── YES → ❌ Already fought (Skip, no log)
│   ├── units_charged.includes(unit.id)?
│   │   └── YES → ❌ Already acted in charging sub-phase (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── NO → ❌ No fight targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to non_active_alternating_activation_pool
│
├── STEP : ATLERNATE_FIGHT → active_alternating_activation_pool AND non_active_alternating_activation_pool are NOT empty ?
│   ├── YES → ALTERNATING LOOP: while active_alternating_activation_pool AND non_active_alternating_activation_pool are NOT empty
│   │   ├── Non-active player turn → Non-active player is an AI player ?
│   │   │   ├── YES → Non-active player Select a unit from non_active_alternating_activation_pool
│   │   │   │   ├── Clear any unit remaining in valid_target_pool
│   │   │   │   ├── Clear TOTAL_ATTACK_LOG
│   │   │   │   ├── ATTACK_LEFT = CC_NB
│   │   │   │   ├── While ATTACK_LEFT > 0
│   │   │   │   │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0 → added to valid_target_pool
│   │   │   │   │   └── valid_target_pool NOT empty ?
│   │   │   │   │       ├── YES → FIGHT PHASE ACTIONS AVAILABLE
│   │   │   │   │       │   ├── 🎯 VALID ACTIONS: [attack]
│   │   │   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT)
│   │   │   │   │       │   └── AGENT ACTION SELECTION → Choose attack?
│   │   │   │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│   │   │   │   │       │       │   ├── ATTACK_LEFT -= 1
│   │   │   │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │   │   │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │   │   │   │       │       │   └── selected_target survives → Continue
│   │   │   │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │   │   │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT)
│   │   │   │   │       └── NO → ATTACK_LEFT = CC_NB ?
│   │   │   │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │   │   │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (PASS, 1, PASS, FIGHT)
│   │   │   │   ├── Return: TOTAL_ACTION log
│   │   │   │   ├── end_activation (ACTION, 1, FIGHT, FIGHT)
│   │   │   │   └── Check: Either pool empty?
│   │   │   │       ├── YES → Exit loop, GO TO STEP : ONE_PLAYER_HAS_UNITS_LEFT
│   │   │   │       └── NO → Continue → GO TO STEP : ATLERNATE_FIGHT
│   │   │   └── NO → STEP : UNIT_ACTIVATION → player activate one unit by left clicking on it
│   │   │       ├── Clear any unit remaining in valid_target_pool
│   │   │       ├── Clear TOTAL_ATTACK_LOG
│   │   │       ├── ATTACK_LEFT = CC_NB
│   │   │       ├── While ATTACK_LEFT > 0
│   │   │       │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0 → added to valid_target_pool
│   │   │       │   ├── Display the fight preview
│   │   │       │   └── valid_target_pool NOT empty ?
│   │   │       │       ├── YES → STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   ├── Left click on a target in valid_target_pool → Display selected_target confirmation (HP bar blinking + attack preview)
│   │   │       │       │   │   ├── Left click SAME selected_target again → Confirm attack
│   │   │       │       │   │   │   ├── Execute attack_sequence(CC)
│   │   │       │       │   │   │   ├── ATTACK_LEFT -= 1
│   │   │       │       │   │   │   ├── Concatenate Return to TOTAL_ACTION log
│   │   │       │       │   │   │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │   │       │       │   │   │   ├── selected_target survives → Continue
│   │   │       │       │   │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   │   ├── Left click DIFFERENT target in valid_target_pool → Switch selected_target confirmation
│   │   │       │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION (with new selected_target highlighted)
│   │   │       │       │   │   ├── Left click on another unit in activation pool ?
│   │   │       │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│   │   │       │       │   │   │       ├── YES → Postpone the Fight Phase for this unit
│   │   │       │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │   │   │       └── NO → The unit must end its activation when started
│   │   │       │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   │   ├── Left click on the active_unit
│   │   │       │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   │   ├── Right click on the active_unit
│   │   │       │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│   │   │       │       │   │   │       ├── YES → Postpone the fight phase for this unit
│   │   │       │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │   │   │       └── NO → The unit must end its activation when started
│   │   │       │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION : the unit must attack as long as it can and it has available targets
│   │   │       │       │   │   └── Left OR Right click anywhere else on the board → Cancel selected_target selection → Return to target selection
│   │   │       │       │   │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   ├── Left click on another unit in activation pool ?
│   │   │       │       │   │   └── ATTACK_LEFT = CC_NB ?
│   │   │       │       │   │       ├── YES → Postpone the Fight Phase for this unit
│   │   │       │       │   │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │   │       └── NO → The unit must end its activation when started
│   │   │       │       │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   ├── Left click on the active_unit → No effect
│   │   │       │       │   ├── Right click on the active_unit
│   │   │       │       │   │    └── ATTACK_LEFT = CC_NB ?
│   │   │       │       │   │        ├── YES → Postpone the Fight Phase for this unit
│   │   │       │       │   │        │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │   │        └── NO → The unit must end its activation when started
│   │   │       │       │   │            └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   └── Left OR Right click anywhere else on the board
│   │   │       │       │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       └── NO → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │   │       ├── End of Fight → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │   │       └── Check: Either pool empty?
│   │   │           ├── YES → Exit loop, GO TO STEP : ONE_PLAYER_HAS_UNITS_LEFT
│   │   │           └── NO → Continue → GO TO STEP : ATLERNATE_FIGHT
│   │   └── Active player turn → Active player is an AI player ?
│   │       ├── YES → Active player Select a unit from active_alternating_activation_pool
│   │       │   ├── Clear any unit remaining in valid_target_pool
│   │       │   ├── Clear TOTAL_ATTACK_LOG
│   │       │   ├── ATTACK_LEFT = CC_NB
│   │       │   ├── While ATTACK_LEFT > 0
│   │       │   │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0 → added to valid_target_pool
│   │       │   │   └── valid_target_pool NOT empty ?
│   │       │   │       ├── YES → FIGHT PHASE ACTIONS AVAILABLE
│   │       │   │       │   ├── 🎯 VALID ACTIONS: [attack]
│   │       │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT)
│   │       │   │       │   └── AGENT ACTION SELECTION → Choose attack?
│   │       │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│   │       │   │       │       │   ├── ATTACK_LEFT -= 1
│   │       │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │       │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │       │   │       │       │   └── selected_target survives → Continue
│   │       │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │       │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT)
│   │       │   │       └── NO → ATTACK_LEFT = CC_NB ?
│   │       │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │       │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (PASS, 1, PASS, FIGHT)
│   │       │   ├── Return: TOTAL_ACTION log
│   │       │   ├── end_activation (ACTION, 1, FIGHT, FIGHT)
│   │       │   └── Check: Either pool empty?
│   │       │       ├── YES → Exit loop, GO TO STEP : ONE_PLAYER_HAS_UNITS_LEFT
│   │       │       └── NO → Continue → GO TO STEP : ATLERNATE_FIGHT
│   │       └── NO → STEP : UNIT_ACTIVATION → player activate one unit by left clicking on it
│   │           ├── Clear any unit remaining in valid_target_pool
│   │           ├── Clear TOTAL_ATTACK_LOG
│   │           ├── ATTACK_LEFT = CC_NB
│   │           ├── While ATTACK_LEFT > 0
│   │           │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0 → added to valid_target_pool
│   │           │   ├── Display the fight preview
│   │           │   └── valid_target_pool NOT empty ?
│   │           │       ├── YES → STEP : PLAYER_ACTION_SELECTION
│   │           │       │   ├── Left click on a target in valid_target_pool → Display selected_target confirmation (HP bar blinking + attack preview)
│   │           │       │   │   ├── Left click SAME selected_target again → Confirm attack
│   │           │       │   │   │   ├── Execute attack_sequence(CC)
│   │           │       │   │   │   ├── ATTACK_LEFT -= 1
│   │           │       │   │   │   ├── Concatenate Return to TOTAL_ACTION log
│   │           │       │   │   │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │           │       │   │   │   ├── selected_target survives → Continue
│   │           │       │   │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       │   │   ├── Left click DIFFERENT target in valid_target_pool → Switch selected_target confirmation
│   │           │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION (with new selected_target highlighted)
│   │           │       │   │   ├── Left click on another unit in activation pool ?
│   │           │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│   │           │       │   │   │       ├── YES → Postpone the Fight Phase for this unit
│   │           │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │   │   │       └── NO → The unit must end its activation when started
│   │           │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       │   │   ├── Left click on the active_unit
│   │           │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       │   │   ├── Right click on the active_unit
│   │           │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│   │           │       │   │   │       ├── YES → Postpone the fight phase for this unit
│   │           │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │   │   │       └── NO → The unit must end its activation when started
│   │           │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION : the unit must attack as long as it can and it has available targets
│   │           │       │   │   └── Left OR Right click anywhere else on the board → Cancel selected_target selection → Return to target selection
│   │           │       │   │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       │   ├── Left click on another unit in activation pool ?
│   │           │       │   │   └── ATTACK_LEFT = CC_NB ?
│   │           │       │   │       ├── YES → Postpone the Fight Phase for this unit
│   │           │       │   │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │   │       └── NO → The unit must end its activation when started
│   │           │       │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       │   ├── Left click on the active_unit → No effect
│   │           │       │   ├── Right click on the active_unit
│   │           │       │   │    └── ATTACK_LEFT = CC_NB ?
│   │           │       │   │        ├── YES → Postpone the Fight Phase for this unit
│   │           │       │   │        │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │   │        └── NO → The unit must end its activation when started
│   │           │       │   │            └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       │   └── Left OR Right click anywhere else on the board
│   │           │       │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       └── NO → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │           ├── End of Fight → end_activation (ACTION, 1, FIGHT, FIGHT)
│   │           └── Check: Either pool empty?
│   │               ├── YES → Exit loop, GO TO STEP : ONE_PLAYER_HAS_UNITS_LEFT
│   │               └── NO → Continue → GO TO STEP : ATLERNATE_FIGHT
│   │
│   │   ##### Sub-Phase 3 : only 1 player has eligible units left #####
│   │
│   └── NO → STEP : ONE_PLAYER_HAS_UNITS_LEFT : Only ONE player has activable units left → Select a unit from the non-empty alternating activation pools
│       └── Remaining player turn → Remaining player is an AI player ?
│           ├── YES → Select a unit from the non-empty alternating activation pool
│           │   ├── Clear any unit remaining in valid_target_pool
│           │   ├── Clear TOTAL_ATTACK_LOG
│           │   ├── ATTACK_LEFT = CC_NB
│           │   ├── While ATTACK_LEFT > 0
│           │   │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0 → added to valid_target_pool
│           │   │   └── valid_target_pool NOT empty ?
│           │   │       ├── YES → FIGHT PHASE ACTIONS AVAILABLE
│           │   │       │   ├── 🎯 VALID ACTIONS: [attack]
│           │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT)
│           │   │       │   └── AGENT ACTION SELECTION → Choose attack?
│           │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│           │   │       │       │   ├── ATTACK_LEFT -= 1
│           │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│           │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│           │   │       │       │   └── selected_target survives → Continue
│           │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│           │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT)
│           │   │       └── NO → ATTACK_LEFT = CC_NB ?
│           │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT)
│           │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (PASS, 1, PASS, FIGHT)
│           │   ├── Return: TOTAL_ACTION log
│           │   ├── end_activation (ACTION, 1, FIGHT, FIGHT)
│           │   └── Check: Either pool empty?
│           │       ├── YES → Exit loop, GO TO STEP : ONE_PLAYER_HAS_UNITS_LEFT
│           │       └── NO → Continue → GO TO STEP : ATLERNATE_FIGHT
│           └── NO → STEP : UNIT_ACTIVATION → player activate one unit by left clicking on it
│               ├── Clear any unit remaining in valid_target_pool
│               ├── Clear TOTAL_ATTACK_LOG
│               ├── ATTACK_LEFT = CC_NB
│               ├── While ATTACK_LEFT > 0
│               │   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having selected_target.HP_CUR > 0 → added to valid_target_pool
│               │   ├── Display the fight preview
│               │   └── valid_target_pool NOT empty ?
│               │       ├── YES → STEP : PLAYER_ACTION_SELECTION
│               │       │   ├── Left click on a target in valid_target_pool → Display selected_target confirmation (HP bar blinking + attack preview)
│               │       │   │   ├── Left click SAME selected_target again → Confirm attack
│               │       │   │   │   ├── Execute attack_sequence(CC)
│               │       │   │   │   ├── ATTACK_LEFT -= 1
│               │       │   │   │   ├── Concatenate Return to TOTAL_ACTION log
│               │       │   │   │   ├── selected_target dies → Remove from valid_target_pool, continue
│               │       │   │   │   ├── selected_target survives → Continue
│               │       │   │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│               │       │   │   ├── Left click DIFFERENT target in valid_target_pool → Switch selected_target confirmation
│               │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION (with new selected_target highlighted)
│               │       │   │   ├── Left click on another unit in activation pool ?
│               │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│               │       │   │   │       ├── YES → Postpone the Fight Phase for this unit
│               │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│               │       │   │   │       └── NO → The unit must end its activation when started
│               │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│               │       │   │   ├── Left click on the active_unit
│               │       │   │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│               │       │   │   ├── Right click on the active_unit
│               │       │   │   │   └── ATTACK_LEFT = CC_NB ?
│               │       │   │   │       ├── YES → Postpone the fight phase for this unit
│               │       │   │   │       │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│               │       │   │   │       └── NO → The unit must end its activation when started
│               │       │   │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION : the unit must attack as long as it can and it has available targets
│               │       │   │   └── Left OR Right click anywhere else on the board → Cancel selected_target selection → Return to target selection
│               │       │   │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│               │       │   ├── Left click on another unit in activation pool ?
│               │       │   │   └── ATTACK_LEFT = CC_NB ?
│               │       │   │       ├── YES → Postpone the Fight Phase for this unit
│               │       │   │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│               │       │   │       └── NO → The unit must end its activation when started
│               │       │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│               │       │   ├── Left click on the active_unit → No effect
│               │       │   ├── Right click on the active_unit
│               │       │   │    └── ATTACK_LEFT = CC_NB ?
│               │       │   │        ├── YES → Postpone the Fight Phase for this unit
│               │       │   │        │   └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│               │       │   │        └── NO → The unit must end its activation when started
│               │       │   │            └── GO TO STEP : PLAYER_ACTION_SELECTION
│               │       │   └── Left OR Right click anywhere else on the board
│               │       │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│               │       └── NO → end_activation (ACTION, 1, FIGHT, FIGHT)
│               └── End of Fight → end_activation (ACTION, 1, FIGHT, FIGHT)
└── End Fight Phase: Advance to the Movement Phase of the next player
```

```javascript
CLAUDE VERSION :// FIGHT PHASE - DIRECT TRANSLATION FROM DECISION TREE
// EXACT MAPPING TO YOUR REFERENCE TREE WITH CURRENT SCRIPT NAMING

// ===== POOLS - MATCHING CURRENT SCRIPT NAMES =====
let chargingActivationPool = []              // MATCHES: Current script uses chargingActivationPool
let active_alternating_activation_pool = []     // MATCHES: Current script uses active_alternating_activation_pool  
let non_active_alternating_activation_pool = []  // MATCHES: Current script uses non_active_alternating_activation_pool

// ===== ACTIVE UNIT STATE - MATCHING CURRENT SCRIPT =====
let active_unit = null                        // MATCHES: Current script uses active_unit
let selected_target = null                    // MATCHES: Current script uses selected_target
let attacksLeft = 0                          // MATCHES: Current script uses ATTACK_LEFT field on units
let fightActionLog = []                     // MATCHES: Current script logging pattern

// ===== SUB-PHASE 1: CHARGING UNITS =====

// Pool Building (REF: Lines 4-12) - USING CURRENT SCRIPT PATTERNS
function buildChargingActivationPool() {
 chargingActivationPool = []
 
 for (const unit of units) {                // MATCHES: Current script uses 'units' array
   // REF: Line 5 "unit.HP_CUR > 0?"
   if (unit.HP_CUR <= 0) continue           // MATCHES: Current script checks HP_CUR
   
   // REF: Line 7 "unit.player === currentPlayer?"  
   if (unit.player !== currentPlayer) continue // MATCHES: Current script uses currentPlayer
   
   // REF: Line 9 "units_charged.includes(unit.id)?"
   if (!unitsCharged.includes(unit.id)) continue // MATCHES: Current script uses unitsCharged
   
   // REF: Line 11 "Adjacent to enemy unit within CC_RNG?"
   if (!isAdjacentToEnemyWithinCCRNG(unit)) continue // MATCHES: Current script adjacency checks
   
   // REF: Line 12 "ALL conditions met → ✅ Add to charging_activation pool"
   chargingActivationPool.push(unit)
 }
}

// Main Charging Logic (REF: Lines 13-89) - USING CURRENT SCRIPT FUNCTIONS
function processChargingPhase() {
 buildChargingActivationPool()
 
 // REF: Line 13 "Units in charging_activation pool?"
 while (chargingActivationPool.length > 0) {
   
   // REF: Line 15 "Current player is an AI player ?"
   if (isAI(currentPlayer)) {              // MATCHES: Current script pattern
     processChargingAI()
   } else {
     processChargingHuman()
   }
 }
 
 // REF: Line 90 "All charging units processed → Advance to Sub-Phase 2"
 startAlternatingPhase()                   // MATCHES: Current script function naming
}

function processChargingAI() {
 // REF: Line 16 "pick one → FIGHT PHASE SUB-PHASE 1 ACTION AVAILABLE"
 const selectedUnit = chargingActivationPool[0]
 
 // REF: Line 20 "Choose attack?"
 // REF: Line 21 "YES → ✅ VALID → Execute CC_NB attacks"
 if (hasAdjacentEnemies(selectedUnit)) {    // MATCHES: Current script helper functions
   executeAIAttackSequence(selectedUnit)
   // REF: Line 25 "Result: +1 step, Attack sequence logged, Mark as units_attacked"
   gameState.episode_steps += 1            // MATCHES: Current script step counting
   logAttackSequence(selectedUnit, fightActionLog)
   actions.addAttackedUnit(selectedUnit.id) // MATCHES: Current script actions pattern
 }
 
 // REF: Line 25 "Unit removed from activation pool"
 removeFromPool(selectedUnit, chargingActivationPool)
}

function executeAIAttackSequence(unit) {
 // REF: Line 22 "For each attack: Valid targets still available?"
 for (let attackNum = 1; attackNum <= unit.CC_NB; attackNum++) {
   const validTargets = getAdjacentEnemies(unit)  // MATCHES: Current script helper
   
   // REF: Line 24 "NO → All adjacent targets eliminated → End attacking naturally (slaughter handling)"
   if (validTargets.length === 0) break
   
   // REF: Line 23 "YES → Select adjacent enemy target and resolve attack"
   const target = validTargets[0] // AI picks first available
   executeAttack(unit, target)    // MATCHES: Current script function name
 }
}

// Human Charging Interface (REF: Lines 27-89) - USING CURRENT SCRIPT PATTERNS
function processChargingHuman() {
 // REF: Line 27 "STEP : UNIT_ACTIVATION → player activate one by left clicking"
 waitForUnitActivation()
}

function onChargingUnitClick(clickedUnit) {
 active_unit = clickedUnit
 
 // REF: Line 29 "ATTACK_LEFT = CC_NB"
 attacksLeft = active_unit.CC_NB
 
 // REF: Line 28 "Build valid_targets pool (enemies adjacents) for the active unit"
 const validTargets = buildValidTargetsPool(activeUnit)
 
 // REF: Line 28 "Display the fight preview"
 actions.setAttackPreview({ unitId: active_unit.id, col: active_unit.col, row: active_unit.row })
 actions.setMode("attackPreview")         // MATCHES: Current script UI state management
 
 enterChargingWaitingForAction()
}

function chargingWaitingForAction(clickType, target) {
 // REF: Line 32 "Target units in valid_targets pool?"
 const validTargets = getValidTargets(activeUnit)
 
 if (validTargets.length === 0) {
   // REF: Line 67 "NO → Result: +1 step, Fight sequence logged, Mark as units_attacked"
   chargingEndActivation("attacked")
   return
 }
 
 // REF: Line 35 "YES → FIGHT PHASE ACTIONS AVAILABLE"
 if (clickType === "leftClick" && isValidTarget(target)) {
   // REF: Line 37 "Left click on a target in valid_targets → Display target confirmation"
   selected_target = target
   showTargetPreview(target) // HP bar blinking + attack preview
   enterChargingTargetPreviewing()
   
 } else if (clickType === "leftClick" && isUnitInChargingPool(target)) {
   // REF: Line 47 "Left click on another unit in activation queue ?"
   // REF: Line 49 "ATTACK_LEFT = CC_NB ?"
   if (attacksLeft === active_unit.CC_NB) {
     // REF: Line 50 "YES → Postpone the fight phase for this unit"
     postponeUnit(target)
   } else {
     // REF: Line 52 "NO → The unit must end its activation when started"
     // Stay in current state - unit must complete
   }
   
 } else if (clickType === "rightClick" && target === active_unit) {
   // REF: Line 58 "Right click on the active unit"
   // REF: Line 59 "ATTACK_LEFT = CC_NB ?"
   if (attacksLeft === active_unit.CC_NB) {
     // REF: Line 62 "YES → Result: +1 step, Wait action logged, no Mark"
     chargingEndActivation("wait")
   } else {
     // REF: Line 60 "NO → Result: +1 step, fight sequence logged, Mark as units_attacked"
     chargingEndActivation("attacked")
   }
 }
 // REF: Line 57 "Left click on the active unit → No effect"
 // REF: Line 64 "left OR Right click anywhere on the board" → Stay
}

function chargingTargetPreviewing(clickType, target) {
 if (clickType === "leftClick" && target === selected_target) {
   // REF: Line 38 "Left click SAME target again → Confirm attack → Execute Fight sequence"
   executeAttack(activeUnit, selected_target)
   
   // REF: Line 42 "ATTACK_LEFT -= 1"
   attacksLeft -= 1
   selected_target = null
   
   // REF: Line 43 "Build valid_targets pool (enemies adjacents) for the active unit"
   updateValidTargets(activeUnit)
   
   // REF: Line 44 "GO TO STEP : PLAYER_ACTION_SELECTION"
   if (attacksLeft > 0 && hasValidTargets(activeUnit)) {
     enterChargingWaitingForAction()
   } else {
     chargingEndActivation("attacked")
   }
   
 } else if (clickType === "leftClick" && isValidTarget(target)) {
   // REF: Line 45 "Left click DIFFERENT target in valid_targets → Switch target confirmation"
   selected_target = target
   showTargetPreview(target)
   
 } else if (clickType === "leftClick" && isUnitInChargingPool(target)) {
   // REF: Line 47 "Left click on another unit in activation queue ?"
   if (attacksLeft === active_unit.CC_NB) {
     postponeUnit(target)
   }
   // Else: unit must complete activation
   
 } else if (clickType === "leftClick" && target === active_unit) {
   // REF: Line 54 "Left click on the active unit"
   clearTargetPreview()
   enterChargingWaitingForAction()
   
 } else if (clickType === "rightClick" && target === active_unit) {
   // REF: Line 55 "Right click on the active unit"
   // REF: Line 56 "Nothing happens : the unit must attack as long as it can and it has available targets"
   // Stay in current state - cannot cancel
 }
 // REF: Line 56 "Left OR Right click anywhere else on the board → Cancel target selection"
 else {
   clearTargetPreview()
   enterChargingWaitingForAction()
 }
}

function chargingEndActivation(type) {
 // REF: Line 60,62,67 "Result: +1 step, [action] logged, Mark as units_attacked"
 gameState.episode_steps += 1            // MATCHES: Current script step counting
 
 if (type === "attacked") {
   if (gameLog) {                         // MATCHES: Current script logging pattern
     gameLog.logFightSequenceComplete(activeUnit, fightActionLog, gameState.currentTurn)
   }
   actions.addAttackedUnit(activeUnit.id) // MATCHES: Current script actions
 } else if (type === "wait") {
   if (gameLog) {
     gameLog.logWaitAction(activeUnit, gameState.currentTurn)
   }
 }
 
 removeFromPool(activeUnit, chargingActivationPool)
 resetActiveUnit()                        // MATCHES: Current script helper function
}

// ===== SUB-PHASE 2: ALTERNATING FIGHT =====

// Pool Building (REF: Lines 92-142) - USING CURRENT SCRIPT PATTERNS
function buildAlternatingPools() {
 active_alternating_activation_pool = []     // MATCHES: Current script naming
 non_active_alternating_activation_pool = []  // MATCHES: Current script naming
 
 // REF: Line 94 "ACTIVE PLAYER ELIGIBILITY CHECK"
 for (const unit of units) {              // MATCHES: Current script units array
   // REF: Lines 95-104 exact conditions
   if (unit.HP_CUR > 0 &&
       unit.player === currentPlayer &&
       !unitsAttacked.includes(unit.id) && // MATCHES: Current script unitsAttacked
       !unitsCharged.includes(unit.id) &&  // MATCHES: Current script unitsCharged
       isAdjacentToEnemyWithinCCRNG(unit)) {
     // REF: Line 105 "Add to active_alternating_activation_pool"
     active_alternating_activation_pool.push(unit)
   }
 }
 
 // REF: Line 107 "NON-ACTIVE PLAYER ELIGIBILITY CHECK" 
 for (const unit of units) {
   // REF: Lines 108-117 exact conditions
   if (unit.HP_CUR > 0 &&
       unit.player !== currentPlayer &&
       !unitsAttacked.includes(unit.id) &&
       !unitsCharged.includes(unit.id) &&
       isAdjacentToEnemyWithinCCRNG(unit)) {
     // REF: Line 118 "Add to non_active_alternating_activation_pool"
     non_active_alternating_activation_pool.push(unit)
   }
 }
}

// Alternating Loop (REF: Lines 144-198) - USING CURRENT SCRIPT PATTERNS
function processAlternatingPhase() {
 buildAlternatingPools()
 
 // REF: Line 144 condition checks
 if (activeAlternatingActivationPool.length === 0 && 
     non_active_alternating_activation_pool.length === 0) {
   // Both pools empty → End fight
   endFightPhase()
   return
 }
 
 if (activeAlternatingActivationPool.length === 0 || 
     non_active_alternating_activation_pool.length === 0) {
   // One pool empty → Cleanup phase
   processCleanupPhase()
   return
 }
 
 // REF: Line 145 "ALTERNATING LOOP: while active_alternating_activation_pool AND non_active_alternating_activation_pool are NOT empty"
 while (activeAlternatingActivationPool.length > 0 && 
        non_active_alternating_activation_pool.length > 0) {
   
   // REF: Line 146 "Non-active player turn"
   processNonActivePlayerTurn()
   
   if (shouldExitAlternatingLoop()) break
   
   // REF: Line 171 "Active player turn"  
   processActivePlayerTurn()
   
   if (shouldExitAlternatingLoop()) break
 }
 
 // REF: Line 196 "Exit loop, proceed to cleanup"
 processCleanupPhase()
}

function processNonActivePlayerTurn() {
 // REF: Line 146 "Non-active player is an AI player ?"
 if (isAI(nonActivePlayer)) {             // MATCHES: Current script pattern
   // REF: Line 147 "Select a unit from non_active_alternating_activation_pool"
   const selectedUnit = non_active_alternating_activation_pool[0]
   executeAlternatingAI(selectedUnit, non_active_alternating_activation_pool)
 } else {
   // REF: Line 159 "STEP : UNIT_ACTIVATION → player activate one by left clicking"
   processAlternatingHuman(non_active_alternating_activation_pool)
 }
}

function processActivePlayerTurn() {
 // REF: Line 171 "Active player is an AI player ?"
 if (isAI(currentPlayer)) {               // MATCHES: Current script pattern
   // REF: Line 172 "Select a unit from active_alternating_activation_pool"
   const selectedUnit = active_alternating_activation_pool[0]
   executeAlternatingAI(selectedUnit, active_alternating_activation_pool)
 } else {
   // REF: Line 184 "STEP : UNIT_ACTIVATION → player activate one by left clicking"
   processAlternatingHuman(activeAlternatingActivationPool)
 }
}

function executeAlternatingAI(unit, pool) {
 // REF: Line 148 "Unit adjacent to enemy units?"
 if (hasAdjacentEnemies(unit)) {
   // REF: Line 152 "Execute CC_NB attacks"
   executeAIAttackSequence(unit)
   // REF: Line 158 "Result: +1 step → Attack sequence logged → Mark as units_attacked"
   gameState.episode_steps += 1          // MATCHES: Current script step counting
   logAttackSequence(unit, fightActionLog)
   actions.addAttackedUnit(unit.id)      // MATCHES: Current script actions
 }
 // No else clause needed - REF: Line 161 shows pass/no log/no mark is automatic
 
 removeFromPool(unit, pool)
 
 // REF: Line 162 "Check: Either pool empty?"
 // This check happens in main alternating loop
}

// ===== SUB-PHASE 3: CLEANUP =====

// Cleanup Logic (REF: Lines 199-259) - USING CURRENT SCRIPT PATTERNS
function processCleanupPhase() {
 // REF: Line 200 "Only ONE player has activable units left"
 const remainingPool = active_alternating_activation_pool.length > 0 ? 
                      active_alternating_activation_pool : 
                      non_active_alternating_activation_pool
 
 if (remainingPool.length === 0) {
   endFightPhase()
   return
 }
 
 // REF: Line 201 "Remaining player is an AI player ?"
 while (remainingPool.length > 0) {
   const unit = remainingPool[0]
   
   if (isAI(unit.player)) {               // MATCHES: Current script pattern
     // REF: Line 202 "Select a unit from non-empty alternating activation pools"
     executeAlternatingAI(unit, remainingPool)
   } else {
     // REF: Line 217 "STEP : UNIT_ACTIVATION → player activate one by left clicking"
     processAlternatingHuman(remainingPool)
     break // Wait for human interaction
   }
 }
}

// ===== CORE FUNCTIONS - USING CURRENT SCRIPT PATTERNS =====

// Attack Execution (REF: Lines 39-41)
function executeAttack(attacker, target) {
 // REF: Line 39 "Hit roll → hit_roll >= shooter.CC_ATK"
 const hitRoll = rollD6()                 // MATCHES: Current script uses rollD6()
 const hitSuccess = hitRoll >= attacker.CC_ATK
 
 let damageDealt = 0
 let woundRoll = 0
 let woundSuccess = false
 let saveRoll = 0
 let saveSuccess = false
 
 if (hitSuccess) {
   // REF: Line 40 "Wound roll → wound_roll >= calculate_wound_target()"
   woundRoll = rollD6()
   const woundTarget = calculateWoundTarget(attacker, target) // MATCHES: Current script
   woundSuccess = woundRoll >= woundTarget
   
   if (woundSuccess) {
     // REF: Line 41 "Save roll → save_roll >= calculate_save_target()"
     saveRoll = rollD6()
     const saveTarget = calculateSaveTarget(attacker, target) // MATCHES: Current script
     const saveSuccess = saveRoll >= saveTarget
     
     if (!saveSuccess) {
       // REF: Line 42 "Damage application: damage_dealt = shooter.CC_DMG"
       damageDealt = attacker.CC_DMG
     }
   }
 }
 
 // Apply damage using current script pattern
 if (damageDealt > 0) {
   // REF: Line 42 "⚡ IMMEDIATE UPDATE: current_target.HP_CUR -= damage_dealt"
   const newHP = target.HP_CUR - damageDealt
   
   // REF: Line 42 "current_target.HP_CUR <= 0 ? → current_target.alive = False"
   if (newHP <= 0) {
     actions.removeUnit(target.id)        // MATCHES: Current script actions
   } else {
     actions.updateUnit(target.id, { HP_CUR: newHP }) // MATCHES: Current script
   }
 }
 
 fightActionLog.push({attacker: attacker.id, target: target.id, damage: damageDealt})
}

// REF: Line 49 "ATTACK_LEFT = CC_NB ?"
function canPostpone() {
 return attacksLeft === active_unit.CC_NB
}

// MATCHES: Current script helper function
function resetActiveUnit() { 
 active_unit = null
 selected_target = null
 attacksLeft = 0 
}

// MATCHES: Current script step counting
function incrementEpisodeSteps() {
 gameState.episode_steps += 1
}

// MATCHES: Current script actions pattern
function markAsAttacked(unit) {
 actions.addAttackedUnit(unit.id)
}

// ===== HELPER FUNCTIONS - MATCHING CURRENT SCRIPT =====

function removeFromPool(unit, pool) {
 const index = pool.findIndex(u => u.id === unit.id)
 if (index !== -1) {
   pool.splice(index, 1)
 }
}

function shouldExitAlternatingLoop() {
 return active_alternating_activation_pool.length === 0 || 
        non_active_alternating_activation_pool.length === 0
}

function endFightPhase() {
 // Reset all fight state
 chargingActivationPool = []
 active_alternating_activation_pool = []
 non_active_alternating_activation_pool = []
 resetActiveUnit()
 
 // REF: Line 260 "End Fight Phase: Advance to next player's Movement Phase"
 advanceToNextPlayerMovementPhase()       // MATCHES: Current script function naming
}

// ===== INTEGRATION FUNCTIONS FOR CURRENT SCRIPT =====

// Main entry point for fight phase
function startFightPhase() {
 // Initialize fight sub-phase tracking
 actions.setFightSubPhase("charged_units") // MATCHES: Current script sub-phase management
 
 // Start with charging units
 processChargingPhase()
}

// Function to handle fight clicks from UI
function handleFightClick(clickType, target) {
 if (fightSubPhase === "charged_units") {
   chargingWaitingForAction(clickType, target)
 } else if (fightSubPhase === "alternating_fight") {
   alternatingWaitingForAction(clickType, target)
 }
 // Add other sub-phase handlers as needed
}
```


### Alternating Fight Tactical Considerations

**Target Priority During Alternating Phase:**

**Safe Delay Condition:**
- If ALL adjacent enemies are marked as `units_attacked` → Unit can delay its attack safely
- **Why**: No risk of enemy retaliation this phase → Strategic flexibility available

**Activation and target Priority Order:**
1. **Priority 1**: Units with high melee damage output AND likely to die this phase
2. **Priority 2**: Units more likely to die (regardless of damage output)  
3. **Priority 3**: Units with high melee damage output (regardless of vulnerability) AND low chances of being destroyed this phase

**Priority Assessment Logic:**
- **"Likely to die"**: Enemy HP_CUR ≤ Expected damage from this unit's attacks
- **"High melee damage"**: Enemy CC_STR and CC_NB pose significant threat
- **"Safe targets"**: Enemies already marked as `units_attacked` (cannot retaliate)

**Tactical Reasoning:**
- **Eliminate threats before they act**: Remove dangerous enemies that can still attack
- **Preserve action economy**: Attack vulnerable high-damage dealers first
- **Risk mitigation**: Prioritize survival of your own valuable units
- **Delayed gratification**: When safe, consider delaying to see how battle develops

### Fight Phase Structure Logic

**Two Sub-Phases:**
1. **Charging Units Priority**: Current player's charging units attack first
2. **Alternating Fight**: All other engaged units alternate between players

**Why Two Sub-Phases:**
- **Charge reward**: Charging units earned first strike through positioning
- **Alternating fairness**: Non-charging fight alternates for balance
- **Clear sequence**: Eliminates confusion about attack order

### Sub-Phase 1: Charging Units Logic

**Who Acts**: Current player's units marked as "charged this turn"

**Action Logic:**
- **Mandatory attacks**: Must attack if adjacent enemies exist
- **Pass if no targets**: No mark, no step increment
- **Complete all attacks**: All CC_NB attacks in one action

**Why Charging Units Go First:**
- **Earned advantage**: Successfully positioned for fight
- **Momentum bonus**: Charge provides initiative
- **Risk reward**: Compensation for charge risks taken

### Sub-Phase 2: Alternating Fight Logic

**Player Order Logic:**
- **Non-active player starts**: During P0's turn, P1 units act first
- **Then alternating**: P1 → P0 → P1 → P0 until no eligible units

**Why Non-Active Goes First:**
- **Balance compensation**: Gives slight advantage to non-active player
- **Fairness**: Offsets active player's other advantages

**Alternating Process Logic:**
```
While both players have eligible units:
    Non-active player selects and attacks with one unit
    Active player selects and attacks with one unit (no chargers)
    Repeat until one or both players have no eligible units
    
Process any remaining eligible units from either player
```

**Example:**
```
P0's turn, Fight Phase:
Sub-phase 1: P0 Marine (charged) attacks Ork first
Sub-phase 2: P1 Grot attacks P0 Scout → P0 Heavy attacks P1 Boss → Continue alternating
Result: Charging grants first strike, then fair alternation
```

---

## 📊 TRACKING SYSTEM LOGIC

### Tracking Purpose & Design

**Why Tracking Exists:**
- **Prevent duplicate actions**: Ensure units act only once per phase
- **Apply penalties**: Remember fled status for cross-phase restrictions
- **Enable priority systems**: Track charging for fight advantages
- **Determine phase completion**: Know when no eligible units remain

### Tracking Set Logic

**Set-Based Design Benefits:**
- **Efficient lookups**: Fast membership testing
- **Clear semantics**: Add/remove operations clearly defined
- **Consistent patterns**: Same logic structure across all phases

### Individual Tracking Sets

**units_moved** (Movement Phase):
- **Data structure**: Set containing unit IDs
- **Purpose**: Track units that have moved or waited
- **Reset timing**: Start of movement phase
- **Usage**: `units_moved` contains `unit.id` Used to identify units having shot during this turn

**units_fled** (Movement Phase):
- **Purpose**: Track units that fled from fight
- **Reset timing**: Start of movement phase (turn-level tracking)
- **Usage**: Apply shooting and charging penalties

**units_shot** (Shooting Phase):
- **Purpose**: Track units that have shot
- **Reset timing**: Start of movement phase
- **Usage**: Used to identify units having shot during this turn

**units_charged** (Charge Phase):
- **Purpose**: Track units that have charged
- **Reset timing**: Start of movement phase
- **Usage**: Fight priority determination

**units_attacked** (Fight Phase):
- **Purpose**: Track units that have attacked
- **Reset timing**: Start of movement phase
- **Usage**: Used to identify units having attacked during this turn

### Cross-Phase Tracking Logic

**units_fled Persistence:**
- **Spans multiple phases**: Set in movement, used in shooting and charging
- **Turn-level effect**: Cleared at start of new turn, not each phase
- **Penalty application**: Automatic ineligibility in affected phases

**charge_roll_values** (Charge Phase):
- **Purpose**: Store 2D6 roll results for units attempting charges
- **Roll timing**: Immediately when unit becomes active for charging
- **Storage format**: Map of unit.id → roll value (e.g., {unit_123: 8, unit_456: 11})
- **Usage**: Determine maximum charge distance for pathfinding validation
- **Cleanup timing**: End of unit's activation (roll discarded whether charge succeeds or fails)
- **Example**: Marine rolls 9, can charge any target within 9 hexes of adjacent positions (*via pathfinding*)

**Why Cross-Phase Tracking:**
- **Realistic consequences**: Fleeing affects unit for entire turn
- **Strategic depth**: Makes fleeing a meaningful choice with costs
- **State consistency**: Same consequences applied uniformly

**Slaughter Handling Explained:**
When all valid targets are eliminated during multi-shot action:
- Remaining shots are cancelled (cannot fire at invalid targets)
- Unit activation ends immediately
- Prevents units from being stuck with unusable remaining shots
- Maintains game flow and prevents infinite loops

---

## 🎪 KEY SCENARIOS

### Critical Decision Examples

**Scenario 1 - The Coordination Decision:**
```
Situation: 
- Marine A can wound high-threat Enemy (2 damage, enemy has 3 HP)
- Marine B can finish wounded enemies (2 damage)
- Enemy will kill Marine A if allowed to act

Options:
A) Marine A shoots different target, Marine B charges Enemy independently
B) Marine A wounds Enemy, Marine B finishes it with coordinated attack

Analysis:
Option A: Uncertain outcome, Enemy remains threat
Option B: Guaranteed elimination of high threat

Decision principle: Coordination often superior to individual optimization
```

**Scenario 2 - The Flee vs Fight Dilemma:**
```
Wounded Scout (HP_CUR 1) adjacent to healthy Ork
Fight prediction: 80% chance Scout dies if stays
Flee consequences: Scout survives but cannot shoot critical targets this turn

Decision factors:
- Scout's death may "lock" a high value unit in melee, preventing it from attacking a more precious unit
- Scout's flee would :
    - let him to act the subsequent turns but will "free" the ork
    - allow his allied units to shoot at the ork during the shooting phase since it will no more be adjacent to a friendly unit

Framework: Weigh certain survival vs uncertain but valuable contribution
```

**Scenario 3 - The Action Economy Challenge:**
```
Two enemies: one wounded (1 HP), one healthy (3 HP)
Unit can kill wounded enemy OR significantly wound healthy enemy

Standard approach: Kill wounded (guaranteed elimination)
Advanced consideration: What can allies accomplish?
- If ally can finish wounded in the same turn: Better to wound healthy instead
- If no ally available: Take guaranteed elimination

Principle: Optimize total force effectiveness, not individual actions
```

---

## 🔄 RULE INTERACTIONS

### Cross-Phase Effect Patterns

**Flee Penalty Chain:**
```
Movement phase: Unit flees (marked as fled)
Shooting phase: Fled unit cannot shoot (penalty applied)
Charge phase: Fled unit cannot charge (penalty continues)
Fight phase: Fled unit can fight normally (penalty ends)

Strategic insight: Flee penalties span multiple phases but aren't permanent
```

**Charge Priority Chain:**
```
Charge phase: Unit successfully charges
Fight sub-phase 1: Charging unit attacks first
Fight sub-phase 2: If enemy survives, alternating fight begins

Tactical advantage: First strike may eliminate enemy before retaliation
```

### Movement-Fight Interactions

**Positioning Cascade Effects:**
```
Enemy moves adjacent to your unit
Your unit faces dilemma: flee (lose effectiveness) or fight (risk death)
Decision creates ripple effects throughout remaining phases

Counter-strategy: Position units to support each other
Prevention: Avoid isolated vulnerabilities
```

---

## ✅ CLAUDE VALIDATION POINTS

### Fundamental Understanding Checks

**Can Claude answer these core questions?**

1. **"Who can act in Movement phase?"** 
   - Correct: Only current player's units
   - Why: Phase-based turn system

2. **"When does Shooting phase end?"**
   - Correct: When no current player units are eligible to shoot
   - Why: Eligibility-based phase completion

3. **"Why can't fled units charge?"**
   - Correct: They're too far from fight and demoralized
   - Why: Logical consequence of retreat action

4. **"What makes Fight phase unique?"**
   - Correct: Both players' units can act (only such phase)
   - Why: Fight involves units from both sides

### Rule Application Checks

**Can Claude correctly apply eligibility logic?**

Given a unit that is:
- Alive (HP_CUR > 0) ✓
- Belongs to current player ✓  
- Not in units_moved ✓
- Adjacent to an enemy

**Movement phase eligibility**: ELIGIBLE (adjacency doesn't prevent movement)
**Shooting phase eligibility**: INELIGIBLE (adjacent = in fight = cannot shoot)

### Sequence Understanding Checks

**Can Claude trace phase progression?**

Starting state: P0 Movement phase, Turn 1
After P0 completes all phases and P1 completes all phases:
Expected result: P0 Movement phase, Turn 2

**When Turn increments**: Turn increments when P0 starts Movement (turn-based on P0)

### Error Detection Checks

**Can Claude identify common mistakes?**

Scenario: "Unit perform the shoot action, then in same phase performs the same action again"
Claude should identify: VIOLATION - units_shot tracking prevents duplicate actions

Scenario: "Unit moves to hex adjacent to enemy, then shoots in same turn"
Claude should identify: VIOLATION - Movement restrictions prevent moving TO hexes adjacent to enemies

Scenario: "Unit moves from adjacent to enemy to non-adjacent hex, then shoots in same turn"
Claude should identify: VIOLATION - Fled penalty prevents fled units from shooting in the same turn

Scenario: "Unit charges from adjacent to enemy to a different adjacent hex"
Claude should identify: VIOLATION - No charge allowed for units adjacent to enemy units

---

## 🎯 DECISION FRAMEWORK

### Universal Eligibility Pattern

**For any unit in any phase:**
```
1. Check basic viability (alive, correct player)
2. Check action restrictions (already acted, penalties)  
3. Check opportunity availability (valid targets/destinations)
4. Return eligibility result with reason
```

**Why This Pattern:**
- **Consistent**: Same logic structure across all phases
- **Efficient**: Most restrictive checks first
- **Informative**: Provides reason for ineligibility
- **Debuggable**: Clear failure points

### Action Resolution Pattern

**For eligible unit choosing action:**
```
1. Validate action preconditions
2. Execute action atomically  
3. Update game state (positions, health, etc.)
4. Update tracking sets (mark as acted)
5. Log action for replay/debugging
6. Check for consequent state changes (death, phase completion)
```

**Why This Pattern:**
- **Atomic**: Complete action or no action (no partial states)
- **Traceable**: All changes logged
- **Consistent**: Same pattern regardless of action type
- **Complete**: Handles all necessary state updates

### Phase Transition Pattern

**For current phase:**
```
1. Identify all potentially eligible units (current player)
2. Check each unit's phase-specific eligibility
3. If any eligible units found: Continue phase
4. If no eligible units found: Advance to next phase
5. Reset appropriate tracking sets for new phase
```

**Why This Pattern:**
- **Deterministic**: Clear rules for when phases end
- **Complete**: Checks all units, not just some
- **State-based**: Transitions based on game state, not arbitrary rules
- **Clean**: Proper cleanup between phases

---

## 🎓 CLAUDE MASTERY INDICATORS

### Level 1: Basic Understanding
- ✅ Can identify which units are eligible in each phase
- ✅ Understands phase sequence and turn progression
- ✅ Knows why rules exist (tactical/balance reasons)
- ✅ Can explain basic rule interactions

### Level 2: Rule Application
- ✅ Can apply eligibility logic to complex scenarios
- ✅ Understands rule interactions (flee penalties, fight priority)
- ✅ Can trace game state changes through multiple actions
- ✅ Recognizes common error patterns

### Level 3: Implementation Ready
- ✅ Can design eligibility checking algorithms
- ✅ Understands performance implications (efficiency matters)
- ✅ Can create validation and error handling logic
- ✅ Applies universal patterns consistently

### Level 4: System Design
- ✅ Can explain architectural principles (single source of truth)
- ✅ Understands cross-component communication patterns
- ✅ Can design for extensibility and maintainability
- ✅ Optimizes for performance and clarity


## 🧪 IMPLEMENTATION VALIDATION

### Critical Test Scenarios
Implementation must validate these complex interactions:
- Flee penalty chain (Move → Shoot → Charge restrictions)
- Charge priority in fight (Sub-phase 1 first strike)
- Alternating fight sequence (Sub-phase 2 player ordering)
- Tracking set lifecycle (Persistence and cleanup timing)

### Integration Requirements
See AI_INTEGRATION.md for complete test scenarios that validate 
AI_TURN.md compliance across multiple phases.

**This streamlined document brings Claude to Level 4 understanding, enabling expert-level rule comprehension and intelligent decision-making in any implementation context.**