# AI TURN SEQUENCE - EPISODE / TURN / PHASE / STEP MANAGEMENT

## 📋 PHASES QUICK INDEX
- [Episode Lifecycle](#-episode-lifecycle) - Game start/end conditions
- [Turn Progression](#-turn-progression-sequence) - Turn numbering system
- [Movement Phase](#-movement-phase) - Lines 45-120
- [Shooting Phase](#-shooting-phase) - Lines 121-200  
- [Charge Phase](#-charge-phase) - Lines 201-280
- [Combat Phase](#-combat-phase) - Lines 281-400
- [Tracking Sets Summary](#-tracking-sets-summary) - State management
- [Quick Reference Guide](#-quick-reference-guide) - Implementation tables

## 🔋 EPISODE LIFECYCLE
- **Episode Start**: Beginning of first Player 0 turn (movement phase)
- **Episode End**: A Player has no active units OR max number of turns reached
- **Turn Numbering**: Turn 1 = first P0 movement phase, increments at each P0 movement phase start

## 🔄 TURN PROGRESSION SEQUENCE
```
Turn 1: P0 Move → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
Turn 2: P0 Move (Turn++ here) → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
Turn 3: P0 Move (Turn++ here) → ...
```

## 🎯 CORE PRINCIPLES
- **Sequential Activation**: Units act one at a time, completely finishing before next unit starts
- **Dynamic Validation**: Eligibility checked at START of each unit's activation
- **Step Counting**: Only significant actions (move, shoot, charge, attack, wait) increment steps
- **Action Logging**: ALL unit state changes logged regardless of step consumption

## 🔥 CRITICAL IMPLEMENTATION ORDER
**Follow this sequence for EVERY phase to prevent state corruption:**
1. **Phase Setup** → Reset tracking sets (`units_moved`, `units_shot`, etc.)
2. **Unit Selection** → Iterate through current player units only
3. **Eligibility Check** → Apply decision tree validation (early exit on fail)
4. **Action Execution** → Perform state changes atomically
5. **Post-Action Updates** → Update tracking sets → Log action → Increment steps
6. **Phase Transition** → Check "no eligible units remain" condition

# 🏃 MOVEMENT PHASE

## Phase Setup
- **Eligible Units**: All and ONLY the current player's units
- **Tracking Set**: `units_moved` (reset at phase start)

### **Movement Eligibility Decision Tree**
Unit Movement Eligibility Check:
├── unit.CUR_HP > 0?
│   └── NO → ❌ Dead unit (Skip, no log)
├── unit.player === current_player?
│   └── NO → ❌ Wrong player (Skip, no log)
├── units_moved.includes(unit.id)?
│   └── YES → ❌ Already moved (Skip, no log)
└── ALL conditions met → ✅ Eligible for Move/Wait actions

### **Movement Action Decision Tree**
Available Actions for Eligible Unit:
├── Valid destination exists within MOVE range?
│   ├── YES → Move Action
│   │   ├── wasAdjacentToEnemy? → Mark as units_fled + units_moved
│   │   └── Normal move → Mark as units_moved
│   │   └── Result: +1 step, action logged
│   └── NO → Only Wait available
└── Wait Action → Mark as units_moved
└── Result: +1 step, action logged

## Unit Processing Loop
For each current player unit:

### **Unit Becomes Active**
- Unit is selected as active unit for this activation

### **Available Actions**
#### ✅ **Move Action**
- **Requirements**: 
  - Destination and path hexes within MOVE range
  - Destination hex different from starting hex
  - Destination and path hexes NOT occupied
  - Destination and path hexes NOT adjacent to enemy hex
  - Destination and path hexes NOT wall hexes
  
- **Implementation Details**:
  - `forbiddenSet` includes all hexes adjacent to enemies
  - `blocked = units.some(u => u.col === col && u.row === row && u.id !== selectedUnit.id)`
  - `wallHexSet` added to `forbiddenSet`
  - Uses BFS pathfinding respecting `MOVE` value
- **Result**: `→ marked as units_moved → Action logged → 1 step increase`

#### 🏃 **Flee Mechanic** (Special Move Case)
- **Trigger**: Move action started from hex adjacent to enemy unit
- **Implementation**: `wasAdjacentToEnemy`
- **Note**: Unit automatically not adjacent at destination (move restrictions prevent adjacent destinations)
- **Penalties**:
  - ❌ **Shooting Phase**: `if (units_fled.includes(unit.id)) return false`
  - ❌ **Charge Phase**: `if (units_fled.includes(unit.id)) return false`
  - ✅ **Movement**: No restrictions
  - ✅ **Combat**: No restrictions
- **Duration**: Until end of current turn only
- **Result**: `→ marked as units_moved AND units_fled → Action logged → 1 step increase`

#### ⏸️ **Wait Action**
- **Result**: `→ Action logged → 1 step increase`

### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase

## Phase End
- **Trigger**: No more eligible units remain for current player
- **Transition**: Move to Shooting phase
- **Reference**: See [Tracking Sets Summary](#-tracking-sets-summary) for `units_moved` lifecycle

---

# 🎯 SHOOTING PHASE

## Phase Setup
- **Eligible Units**: All and ONLY the current player's units
- **Tracking Set**: `units_shot` (reset at phase start)

### **Shooting Eligibility Decision Tree**
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

### **Shooting Action Decision Tree**
Available Actions for Eligible Unit:
├── Choose to shoot?
│   └── YES → Shoot Action
│       ├── While RNG_NB > 0 AND valid targets exist:
│       │   └── Execute shot at selected target
│       └── Result: Mark as units_shot, +1 step, action logged
└── Choose to wait → Wait Action
└── Result: Mark as units_shot, +1 step, action logged

## Unit Processing Loop
For each current player unit:

### **Unit Becomes Active**
- Unit is selected as active unit for this activation

### **Eligibility Check**
Unit is eligible if ALL of these conditions are true:
- Unit is NOT marked as `units_fled`
- Unit has line of sight on at least one enemy unit WITHIN RNG_RNG distance
- Unit is NOT adjacent to an enemy unit

**Then**: `→ Unit eligible → Continue to shooting actions`

**If unit fails any requirement**: `→ Unit NOT eligible → Action logged → No step increase`

### **Available Actions** (if eligible)
#### 🎯 **Shoot Action**
- **Requirements**: Line of sight to enemy within RNG_RNG distance
- **Target Restrictions**:
  - ❌ **Cannot shoot adjacent enemies**: Units in combat cannot shoot
  - ❌ **Cannot shoot enemies adjacent to friendlies**: Friendly fire prevention
  - ✅ **Must have line of sight**: Wall blocking system
  - ✅ **Must be in range**: Within `RNG_RNG` hexes
- **Execution**: 
  While unit's RNG_NB > 0 AND unit has line of sight to alive enemy within RNG_RNG:
    - Unit shoots at one available target

- **Result**: `→ marked as units_shot → Action logged → 1 step increase for whole shoot action`

#### ⏸️ **Refuse to Shoot (Wait)**
- **Result**: `→ Action logged → 1 step increase`

### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase

## Phase End
- **Trigger**: No more eligible units remain for current player
- **Transition**: Move to Charge phase

---

# ⚡ CHARGE PHASE

## Phase Setup
- **Eligible Units**: All and ONLY the current player's units
- **Tracking Set**: `units_charged` (reset at phase start)

### **Charge Eligibility Decision Tree**
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
├── Enemies within charge_max_distance?
│   ├── NO → ❌ No targets (Log ineligible, no step)
│   └── YES → ✅ Eligible → Roll 2d6 for charge distance

### **Charge Action Decision Tree**
Available Actions After 2d6 Roll:
├── Valid charge destinations within rolled distance?
│   ├── YES → Charge Action Available
│   │   ├── Choose to charge → Move to hex adjacent to enemy
│   │   │   └── Result: Mark as units_charged, +1 step, action logged
│   │   └── Choose to refuse → Refuse Action
│   │       └── Result: +0 step, action logged
│   └── NO → Auto-Skip
│       └── Result: +0 step, action logged

## Unit Processing Loop
For each current player unit:

### **Eligibility Check**
Unit is eligible if ALL of these conditions are true:
- Unit is NOT marked as `units_fled`
- Unit has at least one enemy unit WITHIN charge_max_distance range
- Unit is NOT adjacent to an enemy unit

**Then**: `→ Unit eligible → Continue to charge actions`

**If unit fails any requirement**: `→ Unit NOT eligible → Action logged → No step increase`

### **Available Actions** (if eligible)
#### **Unit Becomes Active**
- Unit is selected as active unit for this activation

#### 🎲 **Charge Distance Roll**
- **Roll**: 2d6 for this unit's charge distance
- **Timing**: Calculated once per unit at START of activation
- **Persistence**: Roll persists for unit's entire activation only

#### 🔀 **Available Actions** (based on roll result)
**Check for valid charge destinations within rolled distance:**

**IF valid destinations exist:**
  #### ⚡ **Charge Action**
  - **Requirements**: Destination hex (adjacent to enemy) must be within charge roll distance
  - **Execution**: Move unit to hex adjacent to enemy unit
  - **Result**: `→ marked as units_charged → Action logged → 1 step increase`

  **OR**
  #### ⏸️ **Refuse to Charge (Pass)**
  - **Available**: When at charge distance but chooses not to charge
  - **Result**: `→ Action logged → No step increase`

**IF no valid destinations exist:**
  #### 🚫 **Auto-Skip**
  - **Trigger**: No hex adjacent to enemy within charge roll distance
  - **Result**: `→ Unit deactivated → Action logged → No step increase`

### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase

## Phase End
- **Trigger**: No more eligible units remain for current player
- **Transition**: Move to Combat phase

---

# ⚔️ COMBAT PHASE

## Phase Setup
- **Eligible Units**: ALL P0 AND P1 units
- **Tracking Set**: `units_attacked` (reset at phase start)  
- **Sub-Phases**: Two distinct sub-phases with different rules
- **Reference**: See [Step Counting Rules](#-step-counting-rules) for combat step mechanics


### **Combat Phase Overall Decision Tree**

```mermaid
graph TD
    A[Combat Phase Start] --> B[Sub-Phase 1: Charging Units]
    B --> C{Any units_charged exist?}
    C -->|YES| D[Process charging units priority]
    C -->|NO| E[Skip to Sub-Phase 2]
    D --> F[Sub-Phase 2: Alternating Combat]
    E --> F
    F --> G{Both players have eligible units?}
    G -->|YES| H[Non-active player attacks]
    H --> I[Active player attacks]
    I --> G
    G -->|NO| J{One player has eligible units?}
    J -->|YES| K[Cleanup: Process remaining units]
    J -->|NO| L[Combat Phase End]
    K --> L```

Combat Phase Text Flow (Implementation Reference)
Combat Phase Structure:
├── Sub-Phase 1: Charging Units Priority
│   ├── Process all current_player units in units_charged
│   └── Each unit: Attack if adjacent enemies exist
└── Sub-Phase 2: Alternating Combat
    ├── While both players have eligible units:
    │   ├── Non-active player attacks
    │   └── Active player attacks (non-chargers only)
    └── Cleanup: Process remaining eligible units

🥇 SUB-PHASE 1: Charging Units Priority

### **Sub-Phase 1 Eligibility Decision Tree**
Charging Unit Combat Eligibility:
├── unit in units_charged?
│   └── NO → Skip to Sub-Phase 2
├── unit.CUR_HP > 0?
│   └── NO → ❌ Dead unit (Skip, no log)
├── unit.player === current_player?
│   └── NO → ❌ Wrong player (Skip, no log)
├── units_attacked.includes(unit.id)?
│   └── YES → ❌ Already attacked (Skip, no log)
└── ALL conditions met → ✅ Process for attack

### **Sub-Phase 1 Action Decision Tree**
Charging Unit Attack Process:
├── Adjacent alive enemies exist?
│   ├── YES → Attack Action (Mandatory)
│   │   ├── While CC_NB > 0 AND adjacent alive enemies:
│   │   │   └── Attack selected target
│   │   └── Result: Mark as units_attacked, +1 step, action logged
│   └── NO → Pass Action
│       └── Result: Mark as units_attacked, +0 step, action logged

### **Eligible Units**: Current player units marked as `units_charged`

### Unit Processing Loop
For each charging unit:

#### **Unit Becomes Active**
- Unit is selected as active unit for this activation

#### ⚔️ **Attack Action** (mandatory)
- **Check**: If unit has alive enemies adjacent
  - **Execution** (if alive enemies adjacent):
    While active unit's CC_NB > 0 AND active unit is adjacent to alive enemy unit:
      - Unit attacks one of the available targets
    - **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`
  - **Pass** (no alive enemies adjacent):
    - **Result**: `→ marked as units_attacked → Action logged → No step increase`

#### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase

### **Sub-Phase 1 End**
- **Trigger**: All charging units have been processed (attacked or passed)
- **Transition**: Move to Sub-Phase 2 (Alternating Combat)

## 🔄 SUB-PHASE 2: Alternating Combat

### **Player Order**: Starts with "non-active" player, then alternates
- During P0's turn: P1 starts, then P0, then P1...
- During P1's turn: P0 starts, then P1, then P0...

### **Eligible Units**: Units NOT marked as `units_attacked` AND adjacent to enemy unit

### **Sub-Phase 2 Eligibility Decision Tree**
Alternating Combat Eligibility:
├── unit.CUR_HP > 0?
│   └── NO → ❌ Dead unit (Skip)
├── units_attacked.includes(unit.id)?
│   └── YES → ❌ Already attacked (Skip)
├── Adjacent to alive enemy unit?
│   └── NO → ❌ Not in combat (Skip)
├── For active player units: unit in units_charged?
│   └── YES → ❌ Already processed in Sub-Phase 1 (Skip)
└── ALL conditions met → ✅ Eligible for alternating combat

### **Sub-Phase 2 Action Decision Tree**
Alternating Combat Attack Process:
├── Non-Active Player Turn:
│   ├── Select eligible non-active player unit
│   ├── Adjacent alive enemies exist?
│   │   ├── YES → Attack Action
│   │   │   └── Result: Mark as units_attacked, +1 step, action logged
│   │   └── NO → Pass Action
│   │       └── Result: Mark as units_attacked, +0 step, action logged
│   └── Switch to Active Player
├── Active Player Turn:
│   ├── Select eligible active player unit (not in units_charged)
│   ├── Adjacent alive enemies exist?
│   │   ├── YES → Attack Action
│   │   │   └── Result: Mark as units_attacked, +1 step, action logged
│   │   └── NO → Pass Action
│   │       └── Result: Mark as units_attacked, +0 step, action logged
│   └── Switch to Non-Active Player
└── Continue alternating while both players have eligible units

### Alternating Loop
While BOTH players have eligible units:

#### **Non-Active Player Turn** (e.g., P1 during P0's turn)
- **Eligibility**: P1 unit NOT marked as `units_attacked` AND adjacent to alive enemy unit
- **Unit Becomes Active**
- **Attack Action**:
  - **Check**: If unit has alive enemies adjacent
    - **Execution** (if alive enemies adjacent):
      While active unit's CC_NB > 0 AND active unit is adjacent to alive enemy unit:
        - Unit attacks one of the available targets
      - **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`
    - **Pass** (no alive enemies adjacent):
      - **Result**: `→ marked as units_attacked → Action logged → No step increase`

#### **Active Player Turn** (e.g., P0 during P0's turn)
- **Eligibility**: P0 unit NOT marked as `units_charged` AND NOT marked as `units_attacked` AND adjacent to alive enemy unit
- **Unit Becomes Active**
- **Attack Action**:
  - **Check**: If unit has alive enemies adjacent
    - **Execution** (if alive enemies adjacent):
      While active unit's CC_NB > 0 AND active unit is adjacent to alive enemy unit:
        - Unit attacks one of the available targets
      - **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`
    - **Pass** (no alive enemies adjacent):
      - **Result**: `→ marked as units_attacked → Action logged → No step increase`

### **Continue Alternating**
- Switch between players while both have eligible units

### **Cleanup Phase**
If one player has no more eligible units:
- **Loop**: Process remaining eligible units from other player
- **Same Rules**: 
  - **Check**: If unit has alive enemies adjacent
    - **Execution** (if alive enemies adjacent):
      While active unit's CC_NB > 0 AND active unit is adjacent to alive enemy unit:
        - Unit attacks one of the available targets
      - **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`
    - **Pass** (no alive enemies adjacent):
      - **Result**: `→ marked as units_attacked → Action logged → No step increase`

## Phase End
- **Trigger**: NO units from either player are eligible
- **Transition**: Move to next player's Movement phase

---

# 📊 TRACKING SETS SUMMARY

| Phase | Tracking Set | Reset Timing | Purpose |
|-------|-------------|--------------|---------|
| Move | `units_moved` | Phase start | Track moved units |
| Move | `units_fled` | Phase start | Track fleeing units |
| Shoot | `units_shot` | Phase start | Track shooting units |
| Charge | `units_charged` | Phase start | Track charged units |
| Combat | `units_attacked` | Phase start | Track attacking units |

## 🎯 STEP COUNTING RULES

| Action Type | Step Increase | Examples |
|-------------|---------------|----------|
| **Significant Actions** | ✅ +1 step | Move, Shoot, Charge, Attack, Wait |
| **Auto-Skip Ineligible** | ❌ No step | Fled unit can't shoot, No charge targets |
| **Action Logging** | ✅ Always | ALL state changes logged regardless |

---

# 🔧 IMPLEMENTATION NOTES

## Field Names (MANDATORY UPPERCASE)
- `RNG_NB`, `RNG_RNG`, `CC_NB`, `CC_RNG`, `MOVE`
- `ARMOR_SAVE`, `CC_STR`, `CC_ATK`, `CC_AP`, `CC_DMG`
- **Reference**: See [Field Names Reference](#-field-names-reference) for complete categorized list

## Tracking Sets Management
- Use Set data structures for O(1) lookups
- Reset at phase start, not turn start
- Consistent naming: `units_[action]` pattern

## Legacy Compatibility
- **REMOVE**: All `hasChargedThisTurn` references
- **REPLACE**: With `units_charged` set tracking
- **MAINTAIN**: Same functional behavior

## Legacy Eligibility Patterns (For Reference Only)
**Historical patterns that should be updated:**
- ❌ **Wrong**: `if (unitsMoved.includes(unit.id)) return false` for shooting
- ✅ **Correct**: `if (units_shot.includes(unit.id)) return false`
- ❌ **Adjacent Check**: `hasAdjacentEnemyShoot = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy))`
- ✅ **Target Validation**: Must check line of sight AND range AND friendly fire rules

## Controller Delegation
- No direct state manipulation in `gym40k.py`
- All game logic through controller methods
- State synchronization across all components

## 🚀 PERFORMANCE OPTIMIZATION NOTES
- **Set Lookups:** Use `Set.has()` instead of `Array.includes()` for O(1) tracking
- **Early Exit:** Check `CUR_HP > 0` first (most common failure condition)
- **Batch Updates:** Process all tracking set updates before logging operations
- **Memory Efficiency:** Clear tracking sets at phase start, not individual removal
- **Validation Order:** Most restrictive conditions first in decision trees
- **Cache LOS:** Store line-of-sight calculations for multiple target evaluation

---

# 📚 QUICK REFERENCE GUIDE

## 🏷️ **Field Names Reference**
| Category | Mandatory Fields (UPPERCASE) |
|----------|------------------------------|
| **Movement** | `MOVE`, `col`, `row` |
| **Shooting** | `RNG_NB`, `RNG_RNG`, `RNG_ATK`, `RNG_STR`, `RNG_DMG`, `RNG_AP` |
| **Combat** | `CC_NB`, `CC_RNG`, `CC_ATK`, `CC_STR`, `CC_DMG`, `CC_AP` |
| **Defense** | `ARMOR_SAVE`, `INVUL_SAVE`, `T`, `CUR_HP`, `MAX_HP` |

## 📊 **Tracking Sets Lifecycle**
| Set Name | Added When | Reset When | Purpose |
|----------|------------|------------|---------|
| `units_moved` | After move/wait action | Phase start | Prevent re-movement |
| `units_fled` | After flee move | Phase start | Apply shoot/charge penalties |
| `units_shot` | After shoot/wait action | Phase start | Prevent re-shooting |
| `units_charged` | After charge action | Phase start | Combat priority |
| `units_attacked` | After attack action | Phase start | Prevent re-attacking |

## ⚡ **Step Counting Quick Guide**
| Scenario | Step Increase | Examples |
|----------|---------------|----------|
| **Unit performs action** | ✅ +1 | Move, shoot, charge, attack, wait |
| **Unit auto-skipped** | ❌ +0 | Fled unit in shoot, no targets in charge |
| **Edge case (no targets)** | ❌ +0 | Charging unit with no adjacent enemies |
| **Action logging** | ✅ Always | ALL scenarios logged regardless of steps |

## 🚨 **Common Implementation Errors**
| ❌ **DON'T** | ✅ **DO** |
|-------------|-----------|
| Check eligibility after action | Check eligibility before action |
| Skip alive enemy validation | Always validate `unit.CUR_HP > 0` |
| Modify tracking sets simultaneously | Update in order: action → tracking → log → step |
| Hardcode phase transitions | Use "no eligible units remain" condition |
| Use lowercase field names | Use UPPERCASE: `CC_STR` not `cc_str` |

## 📄 **Phase Transition Checklist**
1. [ ] Check if any eligible units remain for current player
2. [ ] If none eligible → advance to next phase
3. [ ] Reset appropriate tracking sets at new phase start
4. [ ] Process units in order for new phase
5. [ ] Log all state changes regardless of eligibility

## ⚡ **Implementation Priority Matrix**
| Priority | Component | Implementation Order | Performance Impact |
|----------|-----------|---------------------|-------------------|
| **🔥 CRITICAL** | Tracking Sets | Use Set data structures | O(1) vs O(n) lookups |
| **🔥 CRITICAL** | Validation Order | CUR_HP → player → tracking | Early exit optimization |
| **⚠️ HIGH** | Decision Trees | Implement exact flow | Zero logic ambiguity |
| **⚠️ HIGH** | State Atomicity | Batch tracking updates | Consistency guarantee |
| **✅ MEDIUM** | Logging Format | Standardized messages | Debug efficiency |
| **✅ MEDIUM** | Cross-References | Internal doc linking | Development speed |

## 🎯 **Claude Code Generation Optimization Tags**
```typescript
// Use these exact patterns for optimal Claude code generation:

// ✅ OPTIMAL: Decision tree pattern
if (unit.CUR_HP <= 0) return false;           // Early exit
if (!tracking_sets.units_shot.has(unit.id))   // Set lookup
    
// ✅ OPTIMAL: Tracking pattern  
tracking_sets.units_moved.add(unit.id);       // Set operations
    
// ✅ OPTIMAL: Validation pattern
const validation = validateUnitActivation(unit, phase, tracking_sets);
if (!validation.valid) {
    if (validation.log) logAction(validation.reason, unit);
    return validation;
}

// ✅ OPTIMAL: Phase transition pattern
const eligibleUnits = getCurrentPlayerUnits().filter(u => 
    u.CUR_HP > 0 && !tracking_sets.phase_action.has(u.id)
);
if (eligibleUnits.length === 0) advanceToNextPhase();