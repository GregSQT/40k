# AI TURN SEQUENCE - EPISODE / TURN / PHASE / STEP MANAGEMENT

## 📋 EPISODE LIFECYCLE
- **Episode Start**: Beginning of first Player 0 turn (movement phase)
- **Episode End**: A Player has no active units OR max steps reached
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

---

# 🏃 MOVEMENT PHASE

## Phase Setup
- **Eligible Units**: All and ONLY the current player's units
- **Tracking Set**: `units_moved` (reset at phase start)

## Unit Processing Loop
For each current player unit:

### **Unit Becomes Active**
- Unit is selected as active unit for this activation

### **Available Actions**
#### ✅ **Move Action**
- **Requirements**: 
  - Destination within MOVE range 
  - Different from starting hex
  - NOT occupied
  - NOT adjacent to enemy hex
  - NOT a wall hex
- **Result**: `→ marked as units_moved → Action logged → 1 step increase`

#### 🏃 **Flee Mechanic** (Special Move Case)
- **Trigger**: Move action started from hex adjacent to enemy unit
- **Result**: `→ marked as units_moved AND units_fled → Action logged → 1 step increase`

#### ⏸️ **Wait Action**
- **Result**: `→ Action logged → 1 step increase`

### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase

## Phase End
- **Trigger**: All current player units have performed one action
- **Transition**: Move to Shooting phase

---

# 🎯 SHOOTING PHASE

## Phase Setup
- **Eligible Units**: All and ONLY the current player's units
- **Tracking Set**: `units_shot` (reset at phase start)

## Unit Processing Loop
For each current player unit:

### **Unit Becomes Active**
- Unit is selected as active unit for this activation

### **Eligibility Check**
If ANY of these conditions are true:
- Unit is marked as `units_fled`
- Unit has NO line of sight on any enemy unit WITHIN RNG_RNG distance
- Unit is adjacent to an enemy unit

**Then**: `→ Unit NOT eligible → Action logged → No step increase`

### **Available Actions** (if eligible)
#### 🎯 **Shoot Action**
- **Requirements**: Line of sight to enemy within RNG_RNG distance
- **Execution**: 
  ```
  While unit's RNG_NB > 0 AND unit has line of sight to enemy within RNG_RNG:
    - Unit shoots at one available target
  ```
- **Result**: `→ marked as units_shot → Action logged → 1 step increase for whole shoot action`

#### ⏸️ **Refuse to Shoot (Wait)**
- **Result**: `→ Action logged → 1 step increase`

### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase

## Phase End
- **Trigger**: All current player units have performed one action
- **Transition**: Move to Charge phase

---

# ⚡ CHARGE PHASE

## Phase Setup
- **Eligible Units**: All and ONLY the current player's units
- **Tracking Set**: `units_charged` (reset at phase start)

## Unit Processing Loop
For each current player unit:

### **Eligibility Check**
If ANY of these conditions are true:
- Unit is marked as `units_fled`
- Unit has NO enemy unit WITHIN charge_max_distance range
- Unit is adjacent to an enemy unit

**Then**: `→ Unit NOT eligible → Action logged → No step increase`

### **Available Actions** (if eligible)
#### **Unit Becomes Active**
- Unit is selected as active unit for this activation

#### 🎲 **Charge Distance Roll**
- **Roll**: 2d6 for this unit's charge distance

#### ⚡ **Charge Action** (if valid destination exists)
- **Requirements**: Hex adjacent to enemy unit within charge roll distance
- **Execution**: Move unit to hex adjacent to enemy unit
- **Result**: `→ marked as units_charged → Action logged → 1 step increase`

#### ⏸️ **Refuse to Charge (Pass)**
- **Available**: When at charge distance but chooses not to charge
- **Result**: `→ Action logged → No step increase`

#### 🚫 **Auto-Skip** (if no valid destination)
- **Trigger**: No hex adjacent to enemy within charge roll distance
- **Result**: `→ Unit deactivated → Action logged → No step increase`

### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase

## Phase End
- **Trigger**: All current player units have performed one action
- **Transition**: Move to Combat phase

---

# ⚔️ COMBAT PHASE

## Phase Setup
- **Eligible Units**: ALL P0 AND P1 units
- **Tracking Set**: `units_attacked` (reset at phase start)
- **Sub-Phases**: Two distinct sub-phases with different rules

## 🥇 SUB-PHASE 1: Charged Units Priority

### **Eligible Units**: Current player units marked as `units_charged`

### Unit Processing Loop
For each charged unit:

#### **Unit Becomes Active**
- Unit is selected as active unit for this activation

#### ⚔️ **Attack Action** (mandatory)
- **Execution**:
  ```
  While active unit's CC_NB > 0 AND active unit is adjacent to enemy unit:
    - Unit attacks one of the available targets
  ```
- **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`

#### **Unit Deactivation**
- Unit is no longer active
- Unit NOT eligible until next phase
- **Result**: `→ Action logged → No step increase`

### **Sub-Phase 1 End**
- **Trigger**: All charged units have attacked
- **Transition**: Move to Sub-Phase 2 (Alternating Combat)

## 🔄 SUB-PHASE 2: Alternating Combat

### **Player Order**: Starts with "non-active" player, then alternates
- During P0's turn: P1 starts, then P0, then P1...
- During P1's turn: P0 starts, then P1, then P0...

### **Eligible Units**: Units NOT marked as `units_attacked` AND adjacent to enemy unit

### Alternating Loop
While BOTH players have eligible units:

#### **Non-Active Player Turn** (e.g., P1 during P0's turn)
- **Eligibility**: P1 unit adjacent to enemy unit
- **Unit Becomes Active**
- **Attack Action**:
  ```
  While active unit's CC_NB > 0 AND active unit is adjacent to enemy unit:
    - Unit attacks one of the available targets
  ```
- **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`

#### **Active Player Turn** (e.g., P0 during P0's turn)
- **Eligibility**: P0 unit NOT marked as `units_charged` AND adjacent to enemy unit
- **Unit Becomes Active**
- **Attack Action**: Same as above
- **Result**: Same as above

### **Continue Alternating**
- Switch between players while both have eligible units

### **Cleanup Phase**
If one player has no more eligible units:
- **Loop**: Process remaining eligible units from other player
- **Same Rules**: Attack action → marked as units_attacked → 1 step increase

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

## Tracking Sets Management
- Use Set data structures for O(1) lookups
- Reset at phase start, not turn start
- Consistent naming: `units_[action]` pattern

## Legacy Compatibility
- **REMOVE**: All `hasChargedThisTurn` references
- **REPLACE**: With `units_charged` set tracking
- **MAINTAIN**: Same functional behavior

## Controller Delegation
- No direct state manipulation in `gym40k.py`
- All game logic through controller methods
- State synchronization across all components