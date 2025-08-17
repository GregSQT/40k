# Warhammer 40K Game System - Complete Rules & AI Guidelines

## 🎯 GAME OVERVIEW

Turn-based tactical combat following official Warhammer 40K rules with phase-based gameplay. Each player completes all phases before opponent's turn begins.

**Turn Structure:** Move → Shoot → Charge → Combat → Next Player

## 📋 EPISODE / TURN / PHASE / STEP MANAGEMENT

### Episode Lifecycle
- **Episode Start**: Beginning of first Player 0 turn (movement phase)
- **Episode End**: A Player has no active units OR max steps reached
- **Turn Numbering**: Turn 1 = first P0 movement phase, increments at each P0 movement phase start

### Turn Progression
- **Turn 1**: P0 Move → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
- **Turn 2**: P0 Move (Turn++ here) → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
- **Turn 3**: P0 Move (Turn++ here) → ...

### Step Counting Rules
- **1 step increase**: Real actions (move, shoot, charge, combat, wait)
- **No step increase**: Unit becomes ineligible without acting (fled, no targets, etc.)
- **Action logged**: ALL unit state changes must be logged regardless of step consumption

### Critical Timing Rules
- **Sequential Activations**: Units act one at a time, completely finishing before next unit starts
- **Dynamic Target Validation**: Available targets/destinations checked at START of each unit's activation
- **Death Handling**: Dead units immediately removed from game and all tracking lists
- **Phase Transition**: Phase ends when loop through all player units completes (not when step count reached)

---

# 🏃 MOVEMENT PHASE

## Phase Rules
- **Start of Phase**: All and ONLY the CURRENT PLAYER units are eligible
- **Loop on Each Current Player Unit**: Unit becomes active unit for its action
- **Phase End**: Once all CURRENT PLAYER units have performed one action, advance to next phase

## Unit Eligibility
✅ **Can Move**: Units that haven't moved this phase `!unitsMoved.includes(unit.id)`
✅ **Adjacent Units Can Move**: Units adjacent to enemies can still move (flee mechanic)

## Available Actions Per Unit
### 1 Move Action
- **Move to hex within MOVE range** different from starting hex
- **Destination restrictions**: NOT occupied, NOT adjacent to enemy, NOT wall
- **Result**: `→ marked as units_moved → Action logged → 1 step increase`
- **If started adjacent to enemy**: `→ marked as units_moved AND units_fled → Action logged → 1 step increase`

### Wait Action  
- **Do nothing**: `→ Action logged → 1 step increase`

## Movement Restrictions
❌ **Cannot Move TO Adjacent Enemy Hex**: `forbiddenSet` includes all hexes adjacent to enemies
❌ **Cannot Move TO Occupied Hex**: `blocked = units.some(u => u.col === col && u.row === row && u.id !== selectedUnit.id)`
❌ **Cannot Move TO Wall Hex**: `wallHexSet` added to `forbiddenSet`
✅ **Can Move UP TO**: `MOVE` value in hexes using BFS pathfinding

## Flee Mechanics
✅ **Flee Trigger**: Unit was adjacent to enemy at start AND not adjacent at end
❌ **Fled Unit Shooting Penalty**: `if (unitsFled.includes(unit.id)) return false`
❌ **Fled Unit Charging Penalty**: `if (unitsFled.includes(unit.id)) return false`
✅ **Fled Units Can Still Move**: No movement restrictions
✅ **Fled Units Can Still Fight**: No combat restrictions
⏰ **Penalty Duration**: Until end of current turn only

## AI Movement Behavior
**Ranged Units:**
- Avoid being charged
- Keep at least 1 enemy unit within `RNG_RNG` range

**Melee Units:**
- Try to be in charge position

---

# 🎯 SHOOTING PHASE

## Phase Rules
- **Start of Phase**: All and ONLY the CURRENT PLAYER units are eligible
- **Loop on Each Current Player Unit**: Unit becomes active unit for its action
- **Phase End**: Once all CURRENT PLAYER units have performed one action, advance to next phase

## Unit Eligibility Check
**If ANY of these conditions is true, unit is NOT eligible:**
- Unit is marked as `units_fled`
- Unit has NO line of sight on any enemy unit WITHIN `RNG_RNG` distance  
- Unit is adjacent to an enemy unit
**Result**: `→ Action logged → No step increase`

## Available Actions Per Unit (If Eligible)
### 1 Shoot Action
- **Target Selection**: At START of activation, select from living enemies within RNG_RNG with line of sight
- **While unit's RNG_NB > 0 AND has line of sight on enemy within RNG_RNG distance**:
  - Unit shoots at one available target
  - **If target dies mid-sequence**: Remaining shots can target OTHER living enemies within range
- **Result**: `→ marked as units_shot → Action logged → 1 step increase for whole shoot action`

### Wait Action
- **Refuse to shoot**: `→ Action logged → 1 step increase`

## Legacy Eligibility (INCORRECT - DO NOT USE)
❌ **Already Shot**: `if (unitsMoved.includes(unit.id)) return false` ← WRONG! Should check `units_shot`
❌ **Fled Units**: `if (unitsFled.includes(unit.id)) return false`
❌ **Adjacent to Enemy**: `hasAdjacentEnemyShoot = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy))`
✅ **Has Valid Targets**: Enemies in `RNG_RNG` range NOT adjacent to friendly units

## Target Restrictions
❌ **Cannot Shoot Adjacent Enemies**: Units in combat cannot shoot
❌ **Cannot Shoot Enemies Adjacent to Friendlies**: "Rule 2" - friendly fire prevention
✅ **Must Have Line of Sight**: Wall blocking system
✅ **Must Be In Range**: Within `RNG_RNG` hexes

## 6-Step Shooting Sequence
1. **Target Selection**: Choose valid target within range
2. **Hit Roll**: Roll to hit based on shooter's skill (`RNG_ATK`)
3. **Wound Roll**: Compare Strength (`RNG_STR`) vs Toughness (`T`)
4. **Save Roll**: Target attempts armor/invulnerable save
5. **Damage Application**: Apply `RNG_DMG` if save fails
6. **Next Shot**: Continue until all `RNG_NB` shots resolved

## AI Shooting Priority System
**Priority Order:**
1. **Tier 1**: Enemy with highest `RNG_DMG` or `CC_DMG` that:
   - Cannot be killed by active unit in 1 shooting phase
   - One or more of our melee units can charge
   - Would not be killed by our units during charge phase
   - Would be killed by one of our units during combat phase if this unit shoots it

2. **Tier 2**: Enemy with highest `RNG_DMG` or `CC_DMG` that:
   - Has the least HP
   - Can be killed by active unit in 1 shooting phase

3. **Tier 3**: Enemy with highest `RNG_DMG` or `CC_DMG` that:
   - Can be killed by active unit in 1 shooting phase

4. **Tier 4**: Enemy with highest `RNG_DMG` or `CC_DMG` that:
   - Cannot be killed by active unit in 1 shooting phase

---

# ⚡ CHARGE PHASE

## Phase Rules
- **Start of Phase**: All and ONLY the CURRENT PLAYER units are eligible
- **Loop on Each Current Player Unit**: Unit becomes active unit for its action
- **Phase End**: Once all CURRENT PLAYER units have performed one action, advance to next phase

## Unit Eligibility Check
**If ANY of these conditions is true, unit is NOT eligible:**
- Unit is marked as `units_fled`
- Unit has NO enemy unit WITHIN charge_max_distance range
- Unit is adjacent to an enemy unit
**Result**: `→ Action logged → No step increase`

## Available Actions Per Unit (If Eligible)
- **Charge Roll Timing**: 2d6 calculated once per unit per charge phase at START of activation
- **Roll Persistence**: Roll persists for unit's entire activation only
- **Target Validation**: Available charge destinations checked at START of activation from living enemies
- **If hex adjacent to enemy is within charge roll distance**:
  - **1 Charge Action**: Move to hex adjacent to enemy within charge distance `→ marked as units_charged → Action logged → 1 step increase`
  - **Refuse to charge**: At charge distance but doesn't charge `→ roll discarded → Action logged → No step increase`
- **Else**: No valid charge destinations `→ roll discarded → Action logged → No step increase`

## Legacy Eligibility (STILL VALID)
❌ **Already Charged**: `if (unitsCharged.includes(unit.id)) return false`
❌ **Fled Units**: `if (unitsFled.includes(unit.id)) return false`
❌ **Adjacent to Enemy**: `isAdjacent = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy))`
✅ **Enemy Within 12 Hexes**: Fixed maximum charge range

## Charge Mechanics
🎲 **Charge Roll**: 2D6 when first selecting unit
📏 **Distance Check**: Enemy must be within rolled distance AND ≤12 hexes
🚧 **Pathfinding**: `checkPathfindingReachable` respects walls
🎯 **Must End Adjacent**: Charge destination must be adjacent to target enemy
⚡ **Priority in Combat**: Charged units fight first in combat phase

## AI Charge Priority
**Melee Units:**
1. Enemy with highest `RNG_DMG` or `CC_DMG` that can be killed in 1 melee phase
2. Enemy with highest `RNG_DMG` or `CC_DMG`, least current HP, and HP ≥ active unit's `CC_DMG`
3. Enemy with highest `RNG_DMG` or `CC_DMG` and least current HP

**Ranged Units:**
1. Enemy with highest `RNG_DMG` or `CC_DMG`, highest current HP, that can be killed in 1 melee phase

---

# ⚔️ COMBAT PHASE

## Phase Rules
- **Start of Phase**: ALL P0 AND P1 units are eligible
- **Complex Sub-Phase System**: Charged units first, then alternating combat
- **Phase End**: All units have performed actions or become ineligible

## Sub-Phase 1: Charged Units Combat
- **Loop on each unit marked as units_charged**:
  - Unit becomes active unit
  - **1 Attack Action**: While CC_NB > 0 AND adjacent to enemy, attack available targets
  - **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`

## Sub-Phase 2: Alternating Combat  
- **Alternate between P1 and P0** while both have eligible units
- **Unit Eligibility**: NOT marked as units_attacked AND adjacent to enemy unit
- **Target Validation**: Available targets checked at START of each unit's activation
- **For each eligible unit**:
  - **1 Attack Action**: While CC_NB > 0 AND adjacent to enemy, attack available targets
  - **If target dies mid-sequence**: Remaining attacks can target OTHER adjacent enemies
  - **Result**: `→ marked as units_attacked → Action logged → 1 step increase for whole attack action`
- **Player Switching**: If current player has no eligible units, continue with other player's remaining units
- **Phase End**: When loop completes and no units from either player are eligible

## Legacy Sub-Phases (STILL VALID)
1️⃣ **Charged Units Phase**: Only `unit.hasChargedThisTurn === true` can fight
2️⃣ **Alternating Combat**: Non-charged units, alternating by `combatActivePlayer`

## Legacy Eligibility (STILL VALID)
❌ **Already Attacked**: `if (unitsAttacked.includes(unit.id)) return false`
✅ **Adjacent to Enemy**: Must be exactly `CC_RNG` distance (usually 1 hex)
✅ **Correct Sub-Phase**: Charged units in phase 1, others in phase 2

## Combat Resolution
- **Combat Range**: Units fight enemies within `CC_RNG` (usually 1 hex)
- **Multiple Attacks**: Each unit makes `CC_NB` attacks
- **Hit/Wound/Save**: Same dice system as shooting but uses `CC_ATK`, `CC_STR`, `CC_AP`, `CC_DMG`
- **Alternating Selection**: In sub-phase 2, players alternate selecting units to fight
- **Post-Enemy-Death Validation**: After an enemy is killed, system checks for remaining valid targets within `CC_RNG`
- **Automatic Termination**: If no enemies remain at combat range after a kill, unit activation ends immediately

## AI Combat Priority
1. Enemy with highest `RNG_DMG` or `CC_DMG` that can be killed in 1 combat phase
2. Enemy with highest `RNG_DMG` or `CC_DMG` (if tie, target enemy with least current HP)

---

# 🎲 DICE SYSTEM & COMBAT MATHEMATICS

## Wound Chart (Strength vs Toughness)
```typescript
function calculateWoundTarget(strength: number, toughness: number): number {
  if (strength >= 2 * toughness) return 2;      // Overwhelming strength
  if (strength > toughness) return 3;           // Higher strength  
  if (strength === toughness) return 4;         // Equal strength
  if (strength < toughness) return 5;           // Lower strength
  if (strength <= toughness / 2) return 6;     // Inadequate strength
  return 6; // Fallback
}
```

## Armor Save System
```typescript
function calculateSaveTarget(armorSave: number, invulSave: number, armorPenetration: number): number {
  const modifiedArmorSave = armorSave + armorPenetration;
  
  // Use invulnerable save if it exists and is better than modified armor
  if (invulSave > 0 && invulSave < modifiedArmorSave) {
    return invulSave;
  }
  
  return modifiedArmorSave;
}
```

---

# 🗺️ PATHFINDING & COLLISION SYSTEM

## BFS Movement Algorithm
🗺️ **Cube Coordinates**: Proper hex neighbor calculation
🚧 **Forbidden Set**: Adjacent to enemies + walls + occupied hexes
📏 **Distance Limit**: Respects unit's `MOVE` value
🔄 **Visited Tracking**: Prevents revisiting hexes with higher step cost

## Wall System
🧱 **Wall Hexes**: Defined in `boardConfig.wall_hexes`
👀 **Line of Sight**: Ray casting through hex grid
🚫 **Movement Blocking**: Walls completely block movement

---

# 🔄 TURN MANAGEMENT

## Phase Order
**Move** → **Shoot** → **Charge** → **Combat** (sub-phases) → **Next Player**

## State Tracking
📋 **Per Phase**: `unitsMoved`, `unitsCharged`, `unitsAttacked`
🏃 **Per Turn**: `unitsFled`, `hasChargedThisTurn`
♻️ **Reset**: Clear phase tracking, maintain turn tracking until turn end

## Turn Transition
✅ **Phase Advances**: When no eligible units remain
✅ **Turn Increments**: Training / Replay mode : At START of Player 0 (Bot) move phase
♻️ **State Reset**: Clear all tracking at turn start

```typescript
// At end of each complete turn
actions.resetMovedUnits();
actions.resetChargedUnits(); 
actions.resetAttackedUnits();
actions.resetFledUnits();
// Reset hasChargedThisTurn for all units
```

## 🔄 CRITICAL ACTIVATION & TIMING RULES

### Unit Activation Sequence
1. **Start Activation**: Unit becomes active, all validations performed fresh
2. **Action Execution**: Unit performs chosen action completely  
3. **State Updates**: Mark unit as acted, remove dead units, update tracking
4. **End Activation**: Unit no longer active, next unit starts

### Death and State Management
- **Immediate Removal**: Dead units removed from game and all tracking lists instantly
- **Target Validation**: Performed at START of each activation (not action execution time)
- **Mid-Action Death**: If target dies during multi-shot/attack, remaining can target other valid enemies
- **Fled Status**: Once marked as `units_fled`, persists until end of current turn regardless of enemy deaths

### Phase Transition Logic
- **Not Step-Based**: Phases advance when current player unit loop completes, not when step count reached
- **Loop Completion**: ALL CURRENT PLAYER units have either acted OR been determined ineligible at activation start
- **Combat Special Case**: Phase ends when ALL P0 AND P1 units have no more eligible actions (combat only)
- **Standard Phases**: Move/Shoot/Charge phases only involve current player units

---

# ❤️ UNIT LIFE AND DEATH

## Health System
- **Initial HP**: `CUR_HP = MAX_HP` at game start
- **Damage Application**: Reduce `CUR_HP` by attack damage (`RNG_DMG` or `CC_DMG`)
- **Death**: When `CUR_HP ≤ 0`, unit is "dead" and cannot be activated

## Damage Types
- **Shooting Damage**: `RNG_DMG` per failed save
- **Combat Damage**: `CC_DMG` per failed save
- **Multiple Shots**: Each shot can cause separate damage

---

# 🎮 UI INTERACTION RULES

## Movement Phase UI
- **Green Outline**: Only eligible units
- **Green Cells**: Available movement destinations within `MOVE` range
- **Left Click Unit**: Cancel move, end activation
- **Left Click Green Cell**: Move unit, show red range circles
- **Right Click Unit**: Cancel move, keep unit selectable

## Shooting Phase UI
- **Green Outline**: Units with valid targets in `RNG_RNG` range
- **Red Outline**: Enemy targets in range
- **First Click Target**: Show HP preview (current vs future)
- **Second Click Target**: Execute shot
- **Right Click Unit**: Cancel shot, keep unit selectable

## Charge Phase UI
- **Green Outline**: Units eligible to charge
- **Red Outline**: Enemy targets within `MOVE` range
- **Orange Cells**: Valid charge destinations (adjacent to enemies)
- **Left Click Orange**: Execute charge
- **Right Click Unit**: Cancel charge, keep unit selectable

## Combat Phase UI
- **Green Outline**: Units with adjacent enemies
- **Red Outline**: Adjacent enemy targets
- **Left Click Target**: Execute attack
- **Left Click Unit**: Cancel attack, end activation
- **Auto-End Activation**: Unit activation automatically ends when no enemies remain at CC_RNG distance after any attack resolution

---

# 🚨 CRITICAL GAME STATE RULES

## Phase Eligibility Must Check:
1. **Unit hasn't acted this phase** (moved/shot/charged/attacked)
2. **Unit isn't fled** (for shooting/charging only)
3. **Valid targets exist** (appropriate range, line of sight)
4. **Correct sub-phase** (for combat phase)

## State Consistency Rules:
- Only ONE game_state object per game
- ALL components reference the SAME game_state
- NO copying or duplicating state objects
- State changes through designated functions only

## Turn End Conditions:
- **Phase ends**: When no eligible units remain
- **Turn ends**: After combat phase completion
- **Game ends**: When one side has no units remaining