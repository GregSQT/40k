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

### Movement Eligibility Decision Tree

```
Unit Movement Eligibility Check:
├── unit.CUR_HP > 0?
│   └── NO → ❌ Dead unit (Skip, no log)
├── unit.player === current_player?
│   └── NO → ❌ Wrong player (Skip, no log)
├── units_moved.includes(unit.id)?
│   └── YES → ❌ Already moved (Skip, no log)
└── ALL conditions met → ✅ Eligible for Move/Wait actions
```

### Movement Action Decision Tree

```
Available Actions for Eligible Unit:
├── Valid destination exists within MOVE range?
│   ├── YES → Move Action
│   │   ├── wasAdjacentToEnemy? → Mark as units_fled + units_moved
│   │   └── Normal move → Mark as units_moved
│   │   └── Result: +1 step, action logged
│   └── NO → Only Wait available
└── Wait Action → Mark as units_moved
    └── Result: +1 step, action logged
```

### Movement Restrictions Logic

**Forbidden Destinations (Cannot Move TO):**
- **Occupied hexes**: Other units prevent movement
- **Enemy adjacent hexes**: Adjacent to enemy = entering combat
- **Wall hexes**: Terrain blocks movement

**Why These Restrictions:**
- **Spatial logic**: Physical objects cannot overlap
- **Engagement rules**: Adjacent = combat = different phase handles it
- **Terrain realism**: Walls block movement paths

### Flee Mechanics Logic

**Flee Trigger**: Start adjacent to enemy, end not adjacent to any enemy

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
Flee option: Survive but lose turn effectiveness
Stay option: 80% chance of death but maintain capabilities
Decision factors: Unit value, importance of actions this turn, alternative threats
```

---

## 🎯 SHOOTING PHASE LOGIC

### Shooting Eligibility Decision Tree

```
Unit Shooting Eligibility Check:
├── unit.CUR_HP > 0?
│   └── NO → ❌ Dead unit (Skip, no log)
├── unit.player === current_player?
│   └── NO → ❌ Wrong player (Skip, no log)
├── units_shot.includes(unit.id)?
│   └── YES → ❌ Already shot (Skip, no log)
├── units_fled.includes(unit.id)?
│   └── YES → ❌ Fled unit (Log ineligible, no step)
├── Adjacent to enemy unit?
│   └── YES → ❌ In combat (Log ineligible, no step)
├── Has LOS to enemies within RNG_RNG?
│   ├── NO → ❌ No targets (Log ineligible, no step)
│   └── YES → ✅ Eligible for Shoot/Wait actions
```

### Target Restrictions Logic

**Valid Target Requirements:**
- **In range**: Within unit's RNG_RNG distance
- **Line of sight**: No walls blocking straight line to target
- **Not in melee**: Cannot shoot enemies adjacent to shooter
- **Friendly fire prevention**: Cannot shoot enemies adjacent to friendly units

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

**Why Multiple Shots Work This Way:**
- **Action efficiency**: One activation covers all shots
- **Tactical flexibility**: Can spread damage across enemies
- **Realistic timing**: Rapid fire happens quickly
- **Dynamic adaptation**: React to changing battlefield

**Example:**
```
Marine (RNG_NB = 2) faces two wounded Orks (both CUR_HP 1)
Shot 1: Target Ork A, kill it
Shot 2: Retarget to Ork B, kill it
Result: Eliminate two threats in one action through dynamic targeting
```

---

## ⚡ CHARGE PHASE LOGIC

### Charge Eligibility Decision Tree

```
Unit Charge Eligibility Check:
├── unit.CUR_HP > 0?
│   └── NO → ❌ Dead unit (Skip, no log)
├── unit.player === current_player?
│   └── NO → ❌ Wrong player (Skip, no log)
├── units_charged.includes(unit.id)?
│   └── YES → ❌ Already charged (Skip, no log)
├── units_fled.includes(unit.id)?
│   └── YES → ❌ Fled unit (Log ineligible, no step)
├── Adjacent to enemy unit?
│   └── YES → ❌ Already in combat (Log ineligible, no step)
├── Enemies within 12 hexes (charge_max_distance)?
│   ├── NO → ❌ No targets (Log ineligible, no step)
│   └── YES → ✅ Eligible → Roll 2d6 for charge distance
```

### Charge Action Decision Tree

```
Available Actions After 2d6 Roll:
├── Valid charge destinations within rolled distance?
│   ├── YES → Charge Action Available
│   │   ├── Choose to charge → Move to hex adjacent to enemy
│   │   │   └── Result: Mark as units_charged, +1 step, action logged
│   │   └── Choose to refuse → Refuse Action
│   │       └── Result: +0 step, action logged
│   └── NO → Auto-Skip
│       └── Result: +0 step, action logged
```

### Charge Distance Logic

**2D6 Roll System:**
- **When rolled**: When unit becomes eligible for charge (not when action chosen)
- **Distance determination**: Roll determines how far unit can charge this activation
- **Variability purpose**: Adds uncertainty and risk to charge decisions

**Why Random Distance:**
- **Tactical uncertainty**: Cannot guarantee successful charges
- **Risk/reward decisions**: Longer charges more likely to fail
- **Game balance**: Prevents guaranteed charge combinations

**Example:**
```
Marine 7 hexes from Ork (average charge distance)
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
- **Game balance**: Reward for successful charge positioning
- **Risk compensation**: Balances charge uncertainty with combat advantage

---

## ⚔️ COMBAT PHASE LOGIC

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
- **Pass if no targets**: Mark as attacked but no step increment
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
- **Purpose**: Track units that have moved or waited
- **Reset timing**: Start of movement phase
- **Usage**: Prevent re-movement within same phase

**units_fled** (Movement Phase):
- **Purpose**: Track units that fled from combat
- **Reset timing**: Start of movement phase (turn-level tracking)
- **Usage**: Apply shooting and charging penalties

**units_shot** (Shooting Phase):
- **Purpose**: Track units that have shot or passed
- **Reset timing**: Start of shooting phase
- **Usage**: Prevent re-shooting within same phase

**units_charged** (Charge Phase):
- **Purpose**: Track units that have charged
- **Reset timing**: Start of charge phase
- **Usage**: Combat priority determination

**units_attacked** (Combat Phase):
- **Purpose**: Track units that have attacked or passed
- **Reset timing**: Start of combat phase
- **Usage**: Prevent re-attacking within same phase

### Cross-Phase Tracking Logic

**units_fled Persistence:**
- **Spans multiple phases**: Set in movement, used in shooting and charging
- **Turn-level effect**: Cleared at start of new turn, not each phase
- **Penalty application**: Automatic ineligibility in affected phases

**Why Cross-Phase Tracking:**
- **Realistic consequences**: Fleeing affects unit for entire turn
- **Strategic depth**: Makes fleeing a meaningful choice with costs
- **State consistency**: Same consequences applied uniformly

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
Flee consequences: Scout survives but cannot shoot critical targets

Decision factors:
- Scout replacement cost vs immediate value
- Importance of Scout's potential shooting
- Alternative methods to handle Ork threat

Framework: Weigh certain survival vs uncertain but valuable contribution
```

**Scenario 3 - The Action Economy Challenge:**
```
Two enemies: one wounded (1 HP), one healthy (3 HP)
Unit can kill wounded enemy OR significantly wound healthy enemy

Standard approach: Kill wounded (guaranteed elimination)
Advanced consideration: What can allies accomplish?
- If ally can finish wounded: Better to wound healthy instead
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

**Why Turn increments**: Turn increments when P0 starts Movement (turn-based on P0)

### Error Detection Checks

**Can Claude identify common mistakes?**

Scenario: "Unit shoots, then in same phase shoots again"
Claude should identify: VIOLATION - units_shot tracking prevents duplicate actions

Scenario: "Unit moves adjacent to enemy, then shoots in same turn"
Claude should identify: VALID - fled penalty doesn't apply to normal movement

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