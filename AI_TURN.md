# AI TURN SEQUENCE - Ultimate Claude Understanding Guide (Streamlined)

## Claude Search Optimization

**Search Terms**: turn sequence, phase management, eligibility rules, step counting, unit activation, movement phase, shooting phase, charge phase, combat phase, tracking sets, phase transitions, decision logic, game state management

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
- [Combat Phase Logic](#-combat-phase-logic) - Combat phases and alternating turns
- [Tracking System Logic](#-tracking-system-logic) - How the game remembers actions
- [Key Scenarios](#-key-scenarios) - Essential decision examples
- [Rule Interactions](#-rule-interactions) - How different rules affect each other
- [Claude Validation Points](#-claude-validation-points) - Understanding checkpoints
- [Decision Framework](#-decision-framework) - Logical patterns for any implementation

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

**Answer**: When **no more eligible units remain** for the current player.

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
Turn 1: P0 Move → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
Turn 2: P0 Move (Turn++ here) → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
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
- **Combat**: CC_NB, CC_RNG, CC_ATK, CC_STR, CC_DMG, CC_AP  
- **Defense**: CUR_HP, MAX_HP, T, ARMOR_SAVE, INVUL_SAVE

**⚠️ CRITICAL**: Must use UPPERCASE field names consistently across all components.

---

## 🏃 MOVEMENT PHASE LOGIC

### Movement Decision Tree
```
START OF THE PHASE
For each unit
├── ❌ Remove Mark units_moved
├── ❌ Remove Mark units_shot
├── ❌ Remove Mark units_charged
├── ❌ Remove Mark units_attacked
├── ELIGIBILITY CHECK (Queue Building Phase)
│   ├── unit.CUR_HP > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   └── ALL conditions met → ✅ Add to activation queue
├── Units in activation queue → pick one
│   ├── Valid destination exists within MOVE range?
│   │   ├── YES → MOVEMENT PHASE ACTIONS AVAILABLE
│   │   │   ├── 🎯 VALID ACTIONS: [move, wait]
│   │   │   ├── ❌ INVALID ACTIONS: [shoot, charge, attack] → Pass → Error logged → no Mark → Unit is removed from the activation queue
│   │   │   └── AGENT ACTION SELECTION → Choose move ?
│   │   │       ├── YES → ✅ VALID → Execute move action
│   │   │       │   ├── wasAdjacentToEnemy?
│   │   │       │   │   ├── YES → Flee action logged, Mark as units_fled
│   │   │       │   │   └── NO → Move action logged
│   │   │       │   └── Result: +1 step → Mark as units_moved → Unit removed from activation queue
│   │   │       └── NO → Agent chooses: wait?
│   │   │           ├── YES → ✅ VALID → Execute wait action
│   │   │           │   └── Result: +1 step → Wait action logged → o Mark → Unit removed from activation queue
│   │   │           └── NO → Agent chooses invalid action (shoot/charge/attack)?
│   │   │               └── ❌ INVALID ACTION ERROR → Pass → Error logged → no Mark → Unit removed from activation queue
│   │   └── NO → Pass → no log → no Mark → Unit is removed from the activation queue
│   └── No more activable units → pass
└── End of movement phase → Advance to shooting phase
```

### Movement Restrictions Logic

**Forbidden Destinations (Cannot Move To AND through):**
- **Occupied hexes**: Other units prevent movement
- **Enemy adjacent hexes**: Adjacent to enemy = entering combat
- **Wall hexes**: Terrain blocks movement

**Why These Restrictions:**
- **Spatial logic**: Physical objects cannot overlap
- **Engagement rules**: Adjacent = combat = different phase handles it
- **Terrain realism**: Walls block movement paths

### Flee Mechanics Logic

- **Trigger**: Move action started from hex adjacent to enemy unit
- **Implementation**: `wasAdjacentToEnemy`
- **Note**: Unit automatically not adjacent at destination (move restrictions prevent adjacent destinations)
- **Why This Works**: Movement restrictions forbid destinations adjacent to enemies, so checking only the starting position is sufficient to detect flee

**Flee Consequences:**
- **Shooting phase**: Cannot shoot (disorganized from retreat)
- **Charge phase**: Cannot charge (poor position/morale)
- **Combat phase**: Can fight normally (no restriction)
- **Duration**: Until end of current turn only

**Why Flee Exists:**
- **Tactical choice**: Trade current effectiveness for survival
- **Risk/reward**: Escape death but lose capabilities
- **Strategic depth**: Creates meaningful positioning decisions

**Key Example:**
```
Wounded Marine (CUR_HP 1) adjacent to healthy Ork
Flee option: Survive to act later in the game, but lose turn effectiveness
Stay option: 80% chance of death but maintain capabilities
Decision factors: Unit value, importance of actions this turn, long term strategy, alternative threats
```

## 🎯 SHOOTING PHASE LOGIC

### PLAYER Shooting Decision Tree

```
For each PLAYER unit
├── ELIGIBILITY CHECK (Queue Building Phase)
│   ├── unit.CUR_HP > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fled.includes(unit.id)?
│   │   └── YES → ❌ Fled unit (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ In combat (Skip, no log)
│   ├── unit.RNG_NB > 0?
│   │   └── NO → ❌ No ranged weapon (Skip, no log)
│   ├── Has LOS to enemies within RNG_RNG?
│   │   └── NO → ❌ No valid targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to activation queue → Highlight the unit with a green circle around its icon
├── STEP : UNIT_ACTIVABLE_CHECK : Units in activation queue?
│   ├── STEP : UNIT_ACTIVATION → player activate one by left clicking on it → Build valid_targets pool (enemies within RNG_RNG + LOS) for the active unit → Display the Shooting preview
│   │   ├── SHOOT_LEFT = RNG_NB
│   │   ├── While SHOOT_LEFT > 0
│   │   │   └── Target units in valid_targets pool?
│   │   │       ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │   │       │   └── STEP : PLAYER_ACTION_SELECTION
│   │   │       │       ├── Left click on a target in valid_targets → Display the HP bar blinking animation
│   │   │       │       │   ├── Left click a second time on the same target → Execute shooting sequence
│   │   │       │       │   │   ├── Hit roll → hit_roll >= shooter.RNG_ATK
│   │   │       │       │   │   │   ├── MISS → Append shot_record → continue to next shot
│   │   │       │       │   │   │   └── HIT → hits++ → Continue to wound roll
│   │   │       │       │   │   ├── Wound roll → wound_roll >= calculate_wound_target()
│   │   │       │       │   │   │   ├── FAIL → Append shot_record → continue to next shot
│   │   │       │       │   │   │   └── WOUND → wounds++ → Continue to save roll
│   │   │       │       │   │   ├── Save roll → save_roll >= calculate_save_target()
│   │   │       │       │   │   │   ├── SAVE → Append shot_record → continue to next shot
│   │   │       │       │   │   │   └── FAIL → failed_saves++ → Continue to damage
│   │   │       │       │   │   ├── Damage application:
│   │   │       │       │   │   │   ├── damage_dealt = shooter.RNG_DMG
│   │   │       │       │   │   │   ├── total_damage += damage_dealt
│   │   │       │       │   │   │   ├── ⚡ IMMEDIATE UPDATE: current_target.CUR_HP -= damage_dealt
│   │   │       │       │   │   │   ├── current_target.CUR_HP <= 0 ? → current_target.alive = False
│   │   │       │       │   │   │   └── Append shot_record with target_id
│   │   │       │       │   │   ├── Target dies → Remove from valid_targets, continue
│   │   │       │       │   │   ├──  Target survives → Continue
│   │   │       │       │   │   ├── SHOOT_LEFT -= 1
│   │   │       │       │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   ├── Left click on another target in valid_targets → Change target
│   │   │       │       │   │   └── GO TO STEP : STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   ├── Left click on another unit in activation queue ?
│   │   │       │       │   │   └── SHOOT_LEFT = RNG_NB ?
│   │   │       │       │   │       ├── YES → Postpone the shooting phase for this unit
│   │   │       │       │   │           └──  GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │   │       └── NO → The unit must end its activation when started
│   │   │       │       │   │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   ├── Left click on the active unit
│   │   │       │       │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       │   ├── Right click on the active unit
│   │   │       │       │   │   └── SHOOT_LEFT = RNG_NB ?
│   │   │       │       │   │       ├── NO → End unit's activation → Result: +1 step, Shooting sequence logged, Mark as units_shot → Unit removed from activation queue → Remove its green circle
│   │   │       │       │   │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │   │       └── YES → Cancel unit's activation → Result: +1 step, Wait action logged, no Mark → Unit removed from activation queue → Remove its green circle
│   │   │       │       │   │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │   └── Left OR Right click anywhere else on the board
│   │   │       │       │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       ├── Left click on another unit in activation queue ?
│   │   │       │       │   └── SHOOT_LEFT = RNG_NB ?
│   │   │       │       │       ├── YES → Postpone the shooting phase for this unit
│   │   │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │       └── NO → The unit must end its activation when started
│   │   │       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       │       ├── Left click on the active unit → No effect
│   │   │       │       ├── Right click on the active unit
│   │   │       │       │    └── SHOOT_LEFT = RNG_NB ?
│   │   │       │       │       ├── NO → Result: +1 step, Shooting sequence logged, Mark as units_shot → Unit removed from activation queue → Remove its green circle
│   │   │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │       └── YES → Result: +1 step, Wait action logged, no Mark → Unit removed from activation queue → Remove its green circle
│   │   │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       └── left OR Right click anywhere on the board
│   │   │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │   │       └── NO → SHOOT_LEFT = RNG_NB ?
│   │   │           ├── NO → Result: +1 step, Shooting sequence logged, Mark as units_shot → Unit removed from activation queue → Remove its green circle
│   │   │           └── YES → Result: +1 step, Wait action logged, no Mark → Unit removed from activation queue → Remove its green circle
│   │   └── End of shooting → Result: +1 step, Shooting sequence logged, Mark as units_shot → Unit removed from activation queue → Remove its green circle
│   └── No more activable units → pass
└── End of shooting phase → Advance to charge phase

CLAUDE VERSION :

SHOOTING PHASE STATE MACHINE

// INITIALIZATION
activationQueue: Unit[] = []
buildEligibilityQueue() {
  activationQueue = []
  for each unit: 
    if checkEligibility(unit): 
      activationQueue.push(unit)
      addGreenCircle(unit)
}

// STATE MANAGEMENT
activeUnit: Unit | null = null
selectedTarget: Unit | null = null  
shootLeft: number = 0

// MAIN STATE FLOW
STATE: WAITING_FOR_ACTIVATION
├── activationQueue.empty() → END_PHASE
├── leftClick(unitInActivationQueue)
│   ├── activeUnit = clickedUnit
│   ├── shootLeft = activeUnit.RNG_NB
│   ├── buildValidTargetsPool(activeUnit)
│   ├── showShootingPreview()
│   └── GOTO: WAITING_FOR_ACTION
└── otherClick() → STAY

STATE: WAITING_FOR_ACTION
├── validTargets.length = 0 → // SLAUGHTER HANDLING
│   ├── if (shootLeft === activeUnit.RNG_NB):
│   │   └── endActivation("wait")
│   ├── else:
│   │   └── endActivation("shot")
│   └── GOTO: WAITING_FOR_ACTIVATION
├── leftClick(validTarget)
│   ├── selectedTarget = target
│   ├── showTargetPreview(target)
│   └── GOTO: TARGET_PREVIEWING
├── leftClick(otherUnitInActivationQueue) AND canPostpone()
│   ├── activationShotLog = [] // Clear stale data
│   ├── activeUnit = clickedUnit
│   ├── shootLeft = activeUnit.RNG_NB
│   ├── buildValidTargetsPool(activeUnit)
│   └── STAY
├── leftClick(otherUnitInActivationQueue) AND !canPostpone()
│   └── STAY // Unit must complete its activation
├── leftClick(activeUnit) → STAY // No effect
├── rightClick(activeUnit)
│   ├── removeFromQueue(activeUnit)
│   ├── if (shootLeft === activeUnit.RNG_NB):
│   │   └── endActivation("wait") // Never fired
│   ├── else:
│   │   └── endActivation("shot") // Already fired, complete sequence
│   └── GOTO: WAITING_FOR_ACTIVATION
└── otherClick() → STAY

STATE: TARGET_PREVIEWING
├── leftClick(sameTarget)
│   ├── executeShot(activeUnit, selectedTarget)
│   │   ├── // Hit roll → Wound roll → Save roll → Damage
│   │   └── logIndividualShot(activeUnit, selectedTarget, shotResult) // LOG EACH SHOT
│   ├── shootLeft -= 1
│   ├── selectedTarget = null
│   ├── updateValidTargets()
│   ├── if (shootLeft > 0 AND validTargets.length > 0):
│   │   └── GOTO: WAITING_FOR_ACTION
│   ├── else:
│   │   ├── removeFromQueue(activeUnit)
│   │   ├── endActivation("shot") // This will call logShootingSequenceComplete()
│   │   └── GOTO: WAITING_FOR_ACTIVATION
├── leftClick(differentValidTarget)
│   ├── selectedTarget = newTarget
│   ├── showTargetPreview(newTarget)
│   └── STAY
├── leftClick(otherUnitInActivationQueue) AND canPostpone()
│   ├── selectedTarget = null
│   ├── clearTargetPreview()
│   ├── activeUnit = clickedUnit
│   ├── shootLeft = activeUnit.RNG_NB
│   ├── buildValidTargetsPool(activeUnit)
│   └── GOTO: WAITING_FOR_ACTION
├── leftClick(otherUnitInActivationQueue) AND !canPostpone()
│   └── STAY // Unit must complete its activation
├── leftClick(activeUnit)
│   ├── selectedTarget = null
│   ├── clearTargetPreview()
│   └── GOTO: WAITING_FOR_ACTION
├── rightClick(activeUnit)
│   ├── selectedTarget = null
│   ├── removeFromQueue(activeUnit)
│   ├── if (shootLeft === activeUnit.RNG_NB):
│   │   └── endActivation("wait")
│   ├── else:
│   │   └── endActivation("shot")
│   └── GOTO: WAITING_FOR_ACTIVATION
└── otherClick()
│   ├── selectedTarget = null
│   ├── clearTargetPreview()
│   └── GOTO: WAITING_FOR_ACTION

// HELPER FUNCTIONS
canPostpone() { return shootLeft === activeUnit.RNG_NB }

// Store shots during activation
activationShotLog: ShotRecord[] = []

executeShot(shooter, target) {
  // Execute hit/wound/save/damage sequence
  const shotResult = performHitWoundSaveDamage(shooter, target)
  
  // Log individual shot immediately
  logIndividualShot(shooter, target, shotResult)
  
  // Store for sequence completion
  activationShotLog.push(shotResult)
}

endActivation(type) {
  removeGreenCircle(activeUnit)
  incrementEpisodeSteps()
  if (type === "shot") {
    logShootingSequenceComplete(activeUnit, activationShotLog) // Complete sequence
    markAsShot(activeUnit)
  }
  if (type === "wait") {
    logWaitAction(activeUnit)
  }
  activationShotLog = [] // Clear for next unit
  resetActiveUnit()
}

resetActiveUnit() { activeUnit = null; selectedTarget = null; shootLeft = 0 }
```


### AI Shooting Decision Tree

```
For each AI unit
├── ELIGIBILITY CHECK (Queue Building Phase)
│   ├── unit.CUR_HP > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fled.includes(unit.id)?
│   │   └── YES → ❌ Fled unit (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ In combat (Skip, no log)
│   ├── unit.RNG_NB > 0?
│   │   └── NO → ❌ No ranged weapon (Skip, no log)
│   ├── Has LOS to enemies within RNG_RNG?
│   │   └── NO → ❌ No valid targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to activation queue
├── Units in activation queue?
│   ├── YES → pick one → Build valid_targets pool (enemies within RNG_RNG + LOS)
│   │   └── Target units in valid_targets pool?
│   │       ├── YES → SHOOTING PHASE ACTIONS AVAILABLE
│   │       │   ├── 🎯 VALID ACTIONS: [shoot, wait]
│   │       │   ├── ❌ INVALID ACTIONS: [move, charge, attack] → Pass → Error logged → no Mark → Unit is removed from the activation queue
│   │       │   └── AGENT ACTION SELECTION → Choose shoot?
│   │       │       ├── YES → ✅ VALID → Execute shooting sequence
│   │       │       │   ├── For shot 1 to RNG_NB:
│   │       │       │   │   ├── Valid targets still available?
│   │       │       │   │   │   ├── YES → Select target and resolve shot
│   │       │       │   │   │   │   ├── Hit roll → Wound roll → Save roll → Damage
│   │       │       │   │   │   │   ├── Target dies → Remove from valid_targets, continue to next target
│   │       │       │   │   │   │   └── Target survives → Continue to next shot
│   │       │       │   │   │   └── NO → End shooting (slaughter handling)
│   │       │       │   │   └── All shots resolved
│   │       │       │   └── Result: +1 step, Shooting sequence logged, Mark as units_shot → Unit removed from activation queue
│   │       │       └── NO → Agent chooses: wait?
│   │       │           ├── YES → ✅ VALID → Execute wait action
│   │       │           │   └── Result: +1 step, Wait action logged, no Mark → Unit removed from activation queue
│   │       │           └── NO → Agent chooses invalid action (move/charge/attack)?
│   │       │               └── ❌ INVALID ACTION ERROR → Pass → Error logged → no Mark → Unit is removed from the activation queue
│   │       └── NO → Pass → no log, no Mark → Unit is removed from the activation queue
│   └── No more activable units → pass
└── End of shooting phase → Advance to charge phase

Execute shooting sequence:
├── Build valid_targets pool from all_targets (enemies within range + LOS)
├── For shot 1 to RNG_NB:
│   ├── Filter valid_targets: [t for t in valid_targets if t.CUR_HP > 0 and t.alive]
│   ├── valid_targets empty?
│   │   ├── YES → ✅ SLAUGHTER HANDLING → break (cancel remaining shots)
│   │   └── NO → Select current_target = valid_targets[0]
│   ├── Hit roll → hit_roll >= shooter.RNG_ATK
│   │   ├── MISS → Append shot_record → continue to next shot
│   │   └── HIT → hits++ → Continue to wound roll
│   ├── Wound roll → wound_roll >= calculate_wound_target()
│   │   ├── FAIL → Append shot_record → continue to next shot
│   │   └── WOUND → wounds++ → Continue to save roll
│   ├── Save roll → save_roll >= calculate_save_target()
│   │   ├── SAVE → Append shot_record → continue to next shot
│   │   └── FAIL → failed_saves++ → Continue to damage
│   ├── Damage application:
│   │   ├── damage_dealt = shooter.RNG_DMG
│   │   ├── total_damage += damage_dealt
│   │   ├── ⚡ IMMEDIATE UPDATE: current_target.CUR_HP -= damage_dealt
│   │   ├── current_target.CUR_HP <= 0 ? → current_target.alive = False
│   │   └── Append shot_record with target_id
│   └── INCREMENT shot counter → Next shot iteration
└── Return: totalDamage, summary{hits, wounds, failedSaves}, shots[records]
```

### Target Restrictions Logic

**Valid Target Requirements (ALL must be true):**

1. **Range check**: Enemy within unit's RNG_RNG hexes (varies by weapon)
2. **Line of sight**: No wall hexes between shooter and target
3. **Combat exclusion**: Enemy NOT adjacent to shooter (adjacent = melee combat)
4. **Friendly fire prevention**: Enemy NOT adjacent to any friendly units

**Target becomes invalid when:**
- Enemy dies during shooting action
- Enemy moves out of range (rare during shooting phase)
- Line of sight becomes blocked (rare during shooting phase)

**Why These Restrictions:**
- **Weapon limitations**: Ranged weapons have effective range
- **Visual requirement**: Cannot shoot what cannot be seen
- **Engagement types**: Adjacent = melee combat, not shooting
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
Marine (RNG_NB = 2) faces two wounded Orks (both CUR_HP 1)
Shot 1: Target Ork A, kill it
Shot 2: Retarget to Ork B, kill it
Result: Eliminate two threats in one action through dynamic targeting
```
**Example 2:**
```
Marine (RNG_NB = 2) faces one wounded Orks (CUR_HP 1) which is the only "Valid target"
Shot 1: Target the Ork, kill it
Shot 2: No more "Valid target" available, remaining shots are cancelled
Result: Avoid a shooting unit to be stuck because it as no more "Valid target" while having remaining shots to perform
```
---

## ⚡ CHARGE PHASE LOGIC

### Charge Decision Tree

```
For each unit
├── ELIGIBILITY CHECK (Queue Building Phase)
│   ├── unit.CUR_HP > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fled.includes(unit.id)?
│   │   └── YES → ❌ Fled unit (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ Already in combat (Skip, no log)
│   ├── Enemies exist within charge_max_distance hexes?
│   │   └── NO → ❌ No charge targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to activation queue
├── Units in activation queue?
│   ├── YES → pick one → Roll 2d6 charge dice at START of activation
│   │   ├── Build valid charge destinations pool (BFS pathfinding within dice roll distance)
│   │   │   └── Valid destinations found adjacent to enemies?
│   │   │       ├── YES → CHARGE PHASE ACTIONS AVAILABLE
│   │   │       │   ├── 🎯 VALID ACTIONS: [charge, wait]
│   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, attack] → Pass → Error logged → no Mark → Unit is removed from the activation queue
│   │   │       │   └── AGENT ACTION SELECTION → Choose charge?
│   │   │       │       ├── YES → ✅ VALID → Execute charge
│   │   │       │       │   ├── Select destination from valid pool
│   │   │       │       │   ├── Move unit to destination
│   │   │       │       │   └── Result: +1 step, Charge action logged, Mark as units_charged → Unit removed from activation queue
│   │   │       │       └── NO → Agent chooses: wait?
│   │   │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │       │           │   └── Result: +1 step, Wait action logged, no Mark → Unit removed from activation queue
│   │   │       │           └── NO → Agent chooses invalid action (move/shoot/attack)?
│   │   │       │               └── ❌ INVALID ACTION ERROR → Pass → Error logged → no Mark → Unit is removed from the activation queue
│   │   │       └── NO → Pass → no log, no Mark → Unit is removed from the activation queue
│   │   └── Discard charge roll (whether used or not)
│   └── No more activable units → pass
└── End of charge phase → Advance to combat phase
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
Roll 7+: Charge succeeds, gains combat priority (58% chance)
Decision: Weigh 42% failure risk vs combat advantage gained
```

### Charge Priority Logic

**Combat Priority Benefit:**
- **Sub-phase 1**: Charging units attack first in combat phase
- **Tactical advantage**: Can eliminate enemies before they fight back

**Why Charging Units Fight First:**
- **Momentum**: Charge gives initiative in combat
- **Tactical exposure**: Positioning for a charge often exposes the unit to deadly enemy fire during the opponent's turn
- **Risk compensation**: First strike in combat compensates for the vulnerability incurred when moving into charge position

---

## ⚔️ COMBAT PHASE LOGIC

### Combat Phase Overview

**Two-Part Structure:**
1. **Charging Priority** (Sub-phase 1): Current player's charging units attack first
2. **Alternating Combat** (Sub-phase 2): Remaining units alternate between players

**Key Principles:**
- **Charge Reward**: Successful charges grant first-strike advantage
- **Mutual Combat**: Both players' units can act (unique to combat phase)
- **Sequential Resolution**: Complete one unit's attacks before next unit acts
- **Target Validation**: Check for adjacent enemies before each attack

### Combat Sub-Phase 1 Decision Tree

```
Start of the Combat Phase:
│
│   Sub-Phase 1
│
├── For each unit : ELIGIBILITY CHECK (Queue Building Phase)
│   ├── unit.CUR_HP > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_charged.includes(unit.id)?
│   │   └── NO → ❌ Not a charging unit (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── NO → ❌ No combat targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to charging_activation queue
│
├── Units in charging_activation queue?
│   ├── YES → pick one → COMBAT PHASE SUB-PHASE 1 ACTION AVAILABLE
│   │   ├── 🎯 VALID ACTION: [attack]
│   │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → Pass → Error logged → no Mark → Unit is removed from the activation queue
│   │   └── AGENT ACTION SELECTION → Choose attack?
│   │       ├── YES → ✅ VALID → Execute CC_NB attacks
│   │       │   ├── For each attack: Valid targets still available?
│   │       │   │   ├── YES → Select adjacent enemy target and resolve attack
│   │       │   │   │   ├── Hit roll → Wound roll → Save roll → Damage
│   │       │   │   │   ├── Target dies → Remove from valid pool, continue to next Valid target 
│   │       │   │   │   └── Target survives → Continue to next attack
│   │       │   │   └── NO → End attacking (slaughter handling)
│   │       │   └── Result: +1 step, Attack sequence logged, Mark as units_attacked → Unit removed from activation queue
│   │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │           └── ❌ INVALID ACTION ERROR → Pass → no log, no Mark → Unit removed from activation queue
│   └── NO → All charging units processed → Advance to Sub-Phase 2
│
│   Sub-Phase 2
│
├── ACTIVE PLAYER ELIGIBILITY CHECK (Queue Building Phase)
│   ├── unit.CUR_HP > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_attacked.includes(unit.id)?
│   │   └── YES → ❌ Already attacked (Skip, no log)
│   ├── units_charged.includes(unit.id)?
│   │   └── YES → ❌ Already acted in charging sub-phase (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── NO → ❌ No combat targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to active_alternating_activation_pool
│
├── NON-ACTIVE PLAYER ELIGIBILITY CHECK (Queue Building Phase)
│   ├── unit.CUR_HP > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── YES → ❌ Wrong player (Skip, no log)
│   ├── units_attacked.includes(unit.id)?
│   │   └── YES → ❌ Already attacked (Skip, no log)
│   ├── units_charged.includes(unit.id)?
│   │   └── YES → ❌ Already acted in charging sub-phase (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── NO → ❌ No combat targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to non_active_alternating_activation_pool
│
├── active_alternating_activation_pool AND non_active_alternating_activation_pool are NOT empty ?
│   └── YES → ALTERNATING LOOP: while active_alternating_activation_pool AND non_active_alternating_activation_pool are NOT empty
│       └── Non-active player turn → Select a unit from non_active_alternating_activation_pool
│           ├── Unit adjacent to enemy units?
│           │   ├── YES → COMBAT PHASE SUB-PHASE 2 ACTION AVAILABLE
│           │   │   ├── 🎯 VALID ACTION: [attack]
│           │   │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → Pass → Error logged → no Mark
│           │   │   └── AGENT ACTION SELECTION → Choose attack?
│           │   │       ├── YES → ✅ VALID → Execute CC_NB attacks
│           │   │       │   ├── For each attack: Valid targets still available?
│           │   │       │   │   ├── YES → Select adjacent enemy target and resolve attack
│           │   │       │   │   │   ├── Hit roll → Wound roll → Save roll → Damage
│           │   │       │   │   │   ├── Target dies → Continue to next Valid target
│           │   │       │   │   │   └── Target survives → Continue to next attack
│           │   │       │   │   └── NO → End attacking (slaughter handling)
│           │   │       │   └── Result: +1 step → Attack sequence logged → Mark as units_attacked
│           │   │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│           │   │           └── ❌ INVALID ACTION ERROR → Pass → no log, no Mark
│           │   └── NO → Pass → no log, no Mark
│           ├── Unit removed from non_active_alternating_activation_pool
│           ├── Active player turn → Select a unit from active_alternating_activation_pool
│           │   ├── Unit adjacent to enemy units?
│           │   ├── YES → COMBAT PHASE SUB-PHASE 2 ACTIONS AVAILABLE
│           │   │   ├── 🎯 VALID ACTIONS: [attack]
│           │   │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → Pass → Error logged → no Mark
│           │   │   └── AGENT ACTION SELECTION → Choose attack?
│           │   │       ├── YES → ✅ VALID → Execute CC_NB attacks
│           │   │       │   ├── For each attack: Valid targets still available?
│           │   │       │   │   ├── YES → Select adjacent enemy target and resolve attack
│           │   │       │   │   │   ├── Hit roll → Wound roll → Save roll → Damage
│           │   │       │   │   │   ├── Target dies → Continue to next Valid target
│           │   │       │   │   │   └── Target survives → Continue to next attack
│           │   │       │   │   └── NO → End attacking (slaughter handling)
│           │   │       │   └── Result: +1 step → Attack sequence logged → Mark as units_attacked
│           │   │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│           │   │           └── ❌ INVALID ACTION ERROR → Pass → no log, no Mark
│           │   └── Pass → no log, no Mark
│           ├── Unit removed from active_alternating_activation_pool
│           └── Check: Either pool empty?
│               ├── YES → Exit loop, proceed to cleanup
│               └── NO → Continue ALTERNATING LOOP
│
├── Select a unit from the non-empty alternating activation pools
│   ├── Unit adjacent to enemy units?
│   │   ├── YES → COMBAT PHASE SUB-PHASE 2 ACTIONS AVAILABLE
│   │   │   ├── 🎯 VALID ACTIONS: [attack]
│   │   │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → Pass → Error logged → no Mark
│   │   │   └── AGENT ACTION SELECTION → Choose attack?
│   │   │       ├── YES → ✅ VALID → Execute CC_NB attacks
│   │   │       │   ├── For each attack: Valid targets still available?
│   │   │       │   │   ├── YES → Select adjacent enemy target and resolve attack
│   │   │       │   │   │   ├── Hit roll → Wound roll → Save roll → Damage
│   │   │       │   │   │   ├── Target dies → Continue to next Valid target
│   │   │       │   │   │   └── Target survives → Continue to next attack
│   │   │       │   │   └── NO → End attacking (slaughter handling)
│   │   │       │   └── Result: +1 step → Attack sequence logged → Mark as units_attacked
│   │   │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │   │           └── ❌ INVALID ACTION ERROR → Pass → no log, no Mark
│   │   └── NO → Pass → no log, no Mark
│   └── Unit removed from its activation pool
└── End Combat Phase: Advance to next player's Movement Phase
```

### Alternating Combat Tactical Considerations

**Target Priority During Alternating Phase:**

**Safe Delay Condition:**
- If ALL adjacent enemies are marked as `units_attacked` → Unit can delay its attack safely
- **Why**: No risk of enemy retaliation this phase → Strategic flexibility available

**Activation and target Priority Order:**
1. **Priority 1**: Units with high melee damage output AND likely to die this phase
2. **Priority 2**: Units more likely to die (regardless of damage output)  
3. **Priority 3**: Units with high melee damage output (regardless of vulnerability) AND low chances of being destroyed this phase

**Priority Assessment Logic:**
- **"Likely to die"**: Enemy CUR_HP ≤ Expected damage from this unit's attacks
- **"High melee damage"**: Enemy CC_STR and CC_NB pose significant threat
- **"Safe targets"**: Enemies already marked as `units_attacked` (cannot retaliate)

**Tactical Reasoning:**
- **Eliminate threats before they act**: Remove dangerous enemies that can still attack
- **Preserve action economy**: Attack vulnerable high-damage dealers first
- **Risk mitigation**: Prioritize survival of your own valuable units
- **Delayed gratification**: When safe, consider delaying to see how battle develops

### Combat Phase Structure Logic

**Two Sub-Phases:**
1. **Charging Units Priority**: Current player's charging units attack first
2. **Alternating Combat**: All other engaged units alternate between players

**Why Two Sub-Phases:**
- **Charge reward**: Charging units earned first strike through positioning
- **Alternating fairness**: Non-charging combat alternates for balance
- **Clear sequence**: Eliminates confusion about attack order

### Sub-Phase 1: Charging Units Logic

**Who Acts**: Current player's units marked as "charged this turn"

**Action Logic:**
- **Mandatory attacks**: Must attack if adjacent enemies exist
- **Pass if no targets**: No mark, no step increment
- **Complete all attacks**: All CC_NB attacks in one action

**Why Charging Units Go First:**
- **Earned advantage**: Successfully positioned for combat
- **Momentum bonus**: Charge provides initiative
- **Risk reward**: Compensation for charge risks taken

### Sub-Phase 2: Alternating Combat Logic

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
P0's turn, Combat Phase:
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
- **Enable priority systems**: Track charging for combat advantages
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
- **Purpose**: Track units that fled from combat
- **Reset timing**: Start of movement phase (turn-level tracking)
- **Usage**: Apply shooting and charging penalties

**units_shot** (Shooting Phase):
- **Purpose**: Track units that have shot
- **Reset timing**: Start of movement phase
- **Usage**: Used to identify units having shot during this turn

**units_charged** (Charge Phase):
- **Purpose**: Track units that have charged
- **Reset timing**: Start of movement phase
- **Usage**: Combat priority determination

**units_attacked** (Combat Phase):
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
Wounded Scout (CUR_HP 1) adjacent to healthy Ork
Combat prediction: 80% chance Scout dies if stays
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
Combat phase: Fled unit can fight normally (penalty ends)

Strategic insight: Flee penalties span multiple phases but aren't permanent
```

**Charge Priority Chain:**
```
Charge phase: Unit successfully charges
Combat sub-phase 1: Charging unit attacks first
Combat sub-phase 2: If enemy survives, alternating combat begins

Tactical advantage: First strike may eliminate enemy before retaliation
```

### Movement-Combat Interactions

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
   - Correct: They're too far from combat and demoralized
   - Why: Logical consequence of retreat action

4. **"What makes Combat phase unique?"**
   - Correct: Both players' units can act (only such phase)
   - Why: Combat involves units from both sides

### Rule Application Checks

**Can Claude correctly apply eligibility logic?**

Given a unit that is:
- Alive (CUR_HP > 0) ✓
- Belongs to current player ✓  
- Not in units_moved ✓
- Adjacent to an enemy

**Movement phase eligibility**: ELIGIBLE (adjacency doesn't prevent movement)
**Shooting phase eligibility**: INELIGIBLE (adjacent = in combat = cannot shoot)

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
- ✅ Understands rule interactions (flee penalties, combat priority)
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

**This streamlined document brings Claude to Level 4 understanding, enabling expert-level rule comprehension and intelligent decision-making in any implementation context.**