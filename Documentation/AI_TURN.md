# AI TURN SEQUENCE - Ultimate Claude Understanding Guide (Streamlined)

## AI CODING CONTRACT (OPERATIONAL)

This contract constrains how any assistant or tool is allowed to modify this codebase.

- **Do not assume values**
  - If a configuration value, parameter, or input is not clearly specified in the config files or documentation, you must stop and request a specification instead of inventing a value.

- **Always raise when required data is missing**
  - Any missing critical variable, configuration key, or structural field must trigger an explicit error rather than silent substitution or skipping.

- **Do not introduce new constants inside logic**
  - Any new threshold, scaling factor, reward weight, or similar quantity must be added to the appropriate configuration file (and documented) instead of being inlined in code.

- **Always choose the simplest compliant design**
  - Prefer the smallest, clearest implementation that follows `AI_TURN.md` and `AI_IMPLEMENTATION.md`. Avoid additional layers or patterns unless they are required by those documents.

- **Refuse changes that violate AI_TURN or AI implementation rules**
  - If a requested change conflicts with the turn rules or architecture guidelines, explicitly call this out and ask for clarification instead of implementing it.

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
- **Shooting**: RNG_WEAPONS[], selectedRngWeaponIndex, SHOOT_LEFT
- **Fight**: CC_WEAPONS[], selectedCcWeaponIndex, ATTACK_LEFT  
- **Defense**: HP_CUR, HP_MAX, T, ARMOR_SAVE, INVUL_SAVE

**⚠️ MULTIPLE_WEAPONS_IMPLEMENTATION.md**: Units now have weapon arrays instead of single weapon fields. Use `engine.utils.weapon_helpers` functions to access weapon data.

**⚠️ CRITICAL**: Must use UPPERCASE field names consistently across all components.

---

## GENERIC FUNCTIONS

```javascript
END OF ACTIVATION PROCEDURE
end_activation (Arg1, Arg2, Arg3, Arg4, Arg5, Arg6)
├── Arg1 = ?
│   ├── CASE Arg1 = ACTION → log the action
│   ├── CASE Arg1 = WAIT → log the wait action
│   └── CASE Arg1 = NO → do not log the action
├── Arg2 = 1 ?
│   ├── YES → +1 step
│   └── NO → No step increase
├── Arg3 = 
│   ├── CASE Arg3 = 0 → Do not mark the unit
│   ├── CASE Arg3 = MOVE → Mark as units_moved
│   ├── CASE Arg3 = FLED → Mark as units_moved AND Mark as units_fled
│   ├── CASE Arg3 = SHOOTING → Mark as units_shot
│   ├── CASE Arg3 = ADVANCE → Mark as units_advanced
│   ├── CASE Arg3 = CHARGE → Mark as units_charged
│   └── CASE Arg3 = FIGHT → Mark as units_fought
├── Arg4 = ?
│   ├── CASE Arg4 = NOT_REMOVED → Do not remove the unit from an activation pool
│   ├── CASE Arg4 = MOVE → Unit removed from move_activation_pool
│   ├── CASE Arg4 = FLED → Unit removed from move_activation_pool
│   ├── CASE Arg4 = SHOOTING → Unit removed from shoot_activation_pool
│   ├── CASE Arg4 = CHARGE → Unit removed from charge_activation_pool
│   └── CASE Arg4 = FIGHT → Unit removed from fight_activation_pool
├── Arg5 = 1 ?
│   ├── YES → log the error
│   └── NO → No action
└── Arg6 = 1 ?
    ├── YES → Remove the green circle around the unit's icon
    └── NO → Do NOT remove the green circle around the unit's icon

ATTACK ACTION
attack_sequence(Arg)
├── Arg = RNG ?
│   └── Use selected ranged weapon from attacker.RNG_WEAPONS[selectedRngWeaponIndex]
├── Arg = CC ?
│   └── Use selected melee weapon from attacker.CC_WEAPONS[selectedCcWeaponIndex]
├── Hit roll → hit_roll >= selected_weapon.ATK
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
│                   ├── damage_dealt = selected_weapon.DMG
│                   ├── total_damage += damage_dealt
│                   ├── ⚡ IMMEDIATE UPDATE: selected_target.HP_CUR -= damage_dealt
│                   └── selected_target.HP_CUR <= 0 ?
│                       ├── NO
│                           ├── Arg = RNG ?
│                           │   └── ATTACK_LOG = "Unit <activeUnit ID> SHOT Unit <selectedTarget ID> with <weapon_name> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <DMG> DAMAGE DELT !"
│                           └── Arg = CC ?
│                               └── ATTACK_LOG = "Unit <activeUnit ID> FOUGHT Unit <selectedTarget ID> with <weapon_name> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <DMG> DAMAGE DELT !"
│                       └── YES → current_target.alive = False
│                           ├── Arg = RNG ?
│                           │   └── ATTACK_LOG = "Unit <activeUnit ID> SHOT Unit <selectedTarget ID> with <weapon_name> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <DMG> delt : Unit <selectedTarget ID> DIED !"
│                           └── Arg = CC ?
│                               └── ATTACK_LOG = "Unit <activeUnit ID> FOUGHT Unit <selectedTarget ID> with <weapon_name> : Hit <hit roll>(<target hit roll>) - Wound <wond roll>(<target wound roll>) - Save <save roll>(<target save roll>) - <DMG> delt : Unit <selectedTarget ID> DIED !"
└── Return: TOTAL_ATTACK_LOG
```

## 🏃 MOVEMENT PHASE Decision Tree

### MOVEMENT PHASE Decision Tree

```javascript
START OF THE PHASE
For each unit
├── ❌ Remove Mark units_moved (done in command_phase_start)
├── ❌ Remove Mark units_fled (done in command_phase_start)
├── ❌ Remove Mark units_shot (done in command_phase_start)
├── ❌ Remove Mark units_charged (done in command_phase_start)
├── ❌ Remove Mark units_fought (done in command_phase_start)
│
├── ELIGIBILITY CHECK (move_activation_pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── Has at least one valid adjacent hex (not occupied, not adjacent to enemy, not a wall)?
│   │   └── NO → ❌ Unit cannot move (Skip, no log)
│   └── ALL conditions met → ✅ Add to move_activation_pool
│
├── STEP : UNIT_ACTIVABLE_CHECK → is move_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → pick one unit in move_activation_pool
│   │   │   └── Valid destination exists (reacheable hexes using BFS pathfinding within MOVE attribute distance, NOT through/into wall hexes, NOT through/into adjacent to enemy hexes) ?
│   │   │       ├── YES → MOVEMENT PHASE ACTIONS AVAILABLE
│   │   │       │   ├── 🎯 VALID ACTIONS: [move, wait]
│   │   │       │   ├── ❌ INVALID ACTIONS: [shoot, charge, attack] → end_activation (ERROR, 0, PASS, MOVE, 1, 1)
│   │   │       │   └── AGENT ACTION SELECTION → Choose move ?
│   │   │       │       ├── YES → ✅ VALID → Execute move action
│   │   │       │       │   ├── The active_unit was adjacent to an enemy unit at the start of its move action ?
│   │   │       │       │   │   ├── YES → end_activation (ACTION, 1, FLED, MOVE, 1, 1)
│   │   │       │       │   │   └── NO → end_activation (ACTION, 1, MOVE, MOVE, 1, 1)
│   │   │       │       └── NO → Agent chooses: wait?
│   │   │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │       │           │   └── end_activation (WAIT, 1, PASS, MOVE, 1, 1)
│   │   │       │           └── NO → Agent chooses invalid action (shoot/charge/attack)?
│   │   │       │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, MOVE, 1, 1)
│   │   │       └── NO → end_activation (NO, 0, PASS, MOVE, 1, 1)
│   │   │
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
│   │               │       │   │   ├── YES → end_activation (ACTION, 1, FLED, MOVE, 1, 1)
│   │               │       │   │   └── NO → end_activation (ACTION, 1, MOVE, MOVE, 1, 1)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on the active_unit → Move postponed
│   │               │       │   └── GO TO STEP : STEP : UNIT_ACTIVATION
│   │               │       ├── Right click on the active_unit → Move cancelled
│   │               │       │   ├── end_activation (NO, 0, PASS, MOVE, 1, 1)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on another unit in activation pool → Move postponed
│   │               │       │   └── GO TO STEP : UNIT_ACTIVATION
│   │               │       └── Left OR Right click anywhere else on the board → Cancel Move hex selection
│   │               │           └── GO TO STEP : UNIT_ACTIVATION
│   │               └── NO → end_activation (NO, 0, PASS, MOVE, 1, 1)
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

## 🎯 SHOOTING PHASE Decision Tree (Optimized)

**⚠️ ADVANCE_IMPLEMENTATION_PLAN.md**: Shooting phase now supports ADVANCE action in addition to SHOOT.

---

## 📚 SECTION 1: GLOBAL VARIABLES & REFERENCE TABLES

### Global Variables
```javascript
weapon_rule = (weapon rules activated) ? 1 : 0

// Position cache - snapshot des positions ennemies
position_cache = {
    target_id: {id: target_id, col: col, row: row},
    ...
}
// Mise à jour: Quand une cible meurt (retirer de position_cache)
```

### Unit-Specific Cache
```javascript
// Cache LoS par unité active (stocké sur l'unité)
unit["los_cache"] = {
    target_id: has_los,  // booléen
    ...
}
// Calculé à:
// - Activation de l'unité
// - Fin d'advance de l'unité
// Mis à jour à:
// - Mort de la cible: retirer unit["los_cache"][dead_target_id] (pas de recalcul)
// Nettoyé à:
// - Fin de l'activation (comme valid_target_pool)
```

### Function Argument Reference Table

| Function | arg1 | arg2 | arg3 |
|----------|------|------|------|
| `valid_target_pool_build(arg1, arg2, arg3)` | weapon_rule (use weapon rules?) | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |
| `weapon_availability_check(arg1, arg2, arg3)` | weapon_rule | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |

**Critical Note on arg3 after Advance:** When unit has advanced (arg2=1), arg3 is ALWAYS 0 because advance restrictions prevent moving to enemy-adjacent destinations.

### End Activation Parameters Reference
```javascript
end_activation(result_type, step_count, action_type, phase, remove_from_pool, increment_step)
```
- `result_type`: ACTION | WAIT | ERROR | NO | NOT_REMOVED
- `step_count`: 0 or 1 (whether to increment episode_steps)
- `action_type`: SHOOTING | ADVANCE | MOVE | CHARGE | etc.
- `phase`: Current phase (SHOOTING)
- `remove_from_pool`: 0 or 1 (whether to remove unit from activation pool)
- `increment_step`: 0 or 1 (internal tracking)

### State Flags (CAN_SHOOT, CAN_ADVANCE)

**Determined during ELIGIBILITY CHECK:**
- `CAN_ADVANCE = true` if unit is NOT adjacent to enemy (always available)
- `CAN_ADVANCE = false` if unit IS adjacent to enemy (cannot advance when adjacent)
- `CAN_SHOOT = true` if `weapon_availability_check()` returns non-empty pool
- `CAN_SHOOT = false` if `weapon_availability_check()` returns empty pool

**Updated after advance action (if unit actually moved):**
- `CAN_ADVANCE = false` (unit has advanced, cannot advance again)
- `CAN_SHOOT = (weapon_availability_check(weapon_rule, 1, 0) returns non-empty pool)`
  - Note: Only Assault weapons available if weapon_rule=1

### UI Display Constants

**Shooting Preview Color:**
- **All players (AI and Human)**: Blue hexes (LoS and selected_weapon.RNG)

**Note**: The shooting preview displays all hexes within Line of Sight and within the selected weapon's range in blue color for both AI and Human players.

---

## 🔧 SECTION 2: CORE FUNCTIONS (Reusable Building Blocks)

### Function: player_advance()
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

### Function: weapon_availability_check(arg1, arg2, arg3)
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
        │       └── EXCEPTION: If enemy is adjacent to shooter AND weapon has PISTOL rule:
        │           └── ✅ Can shoot at adjacent enemy (even if engaged with other friendly units)
        │       └── If enemy is NOT adjacent to shooter:
        │           └── ❌ Cannot shoot if enemy is adjacent to any friendly unit
        └── If NO enemy meets ALL conditions → ❌ Weapon CANNOT be selectable (skip weapon)
        └── If at least ONE enemy meets ALL conditions → ✅ Add weapon to weapon_available_pool
```

### Function: build_position_cache()
**Purpose**: Construire le snapshot des positions ennemies  
**Returns**: void (met à jour position_cache dans game_state)

```javascript
build_position_cache():
├── position_cache = {}
├── For each unit in game_state["units"]:
│   ├── ELIGIBILITY CHECK:
│   │   ├── unit.HP_CUR > 0? → NO → ❌ Skip (dead unit)
│   │   └── unit.player === current_player? → YES → ❌ Skip (friendly unit)
│   └── ALL conditions met → ✅ Add to position_cache
│       ├── position_cache[unit.id] = {id: unit.id, col: unit.col, row: unit.row}
│       └── Continue
└── Store in game_state["position_cache"]
```

**Appelé à:**
- Début de la phase de tir (une fois)
- **PAS** après mort de cible (juste retirer l'entrée du cache)

**Note d’implémentation** : L’implémentation actuelle utilise **`units_cache`** à la place de `position_cache`. `units_cache` est construit **uniquement au reset** (pas en phase start). Il est la source de vérité pour position, `HP_CUR` et aliveness des unités vivantes. Les unités mortes sont retirées via `update_units_cache_hp(..., 0)` (shooting/fight). **`HP_CUR`** a une source unique : seul `update_units_cache_hp` écrit `HP_CUR` en jeu ; pour « vivant », utiliser `is_unit_alive(unit_id, game_state)`. Voir `AI_IMPLEMENTATION.md` (Units cache & HP_CUR) et `unit_cache21.md`.

### Function: build_unit_los_cache(unit_id)
**Purpose**: Calculer le cache LoS pour une unité spécifique  
**Returns**: void (met à jour unit["los_cache"])

```javascript
build_unit_los_cache(unit_id):
├── unit = get_unit_by_id(unit_id)
├── unit["los_cache"] = {}
├── unit_col, unit_row = unit["col"], unit["row"]
├── For each target in position_cache:
│   ├── target_col, target_row = position_cache[target_id]["col"], position_cache[target_id]["row"]
│   ├── PERFORMANCE: Use has_line_of_sight_coords() instead of _get_unit_by_id() + _has_line_of_sight()
│   ├── has_los = has_line_of_sight_coords(unit_col, unit_row, target_col, target_row, game_state)
│   │   └── Uses hex_los_cache internally for additional performance
│   ├── unit["los_cache"][target_id] = has_los
│   └── Continue
└── Cache calculé et stocké sur l'unité
```

**Optimisation de performance :**
- Utilise `has_line_of_sight_coords()` au lieu de `_get_unit_by_id()` + `_has_line_of_sight()`
- Évite les recherches linéaires O(n) dans `game_state["units"]` pour chaque cible
- Utilise le cache `hex_los_cache` pour éviter les recalculs de LoS entre les mêmes coordonnées
- Complexité : O(m) où m = nombre de cibles dans `position_cache` (au lieu de O(m×n))

**Appelé à:**
- Activation de l'unité (STEP 2: UNIT_ACTIVABLE_CHECK)
- Fin d'advance de l'unité (après mouvement effectif)
- **PAS** après mort de cible (juste retirer l'entrée du cache)

**Cas limites :**
- Si `position_cache` est vide (pas d'ennemis) : `unit["los_cache"] = {}` (cache vide mais existant)
- Si l'unité a fui : `los_cache` n'est **pas construit** (l'unité ne peut pas tirer)

### Function: update_los_cache_after_target_death(dead_target_id)
**Purpose**: Mettre à jour les caches LoS après la mort d'une cible  
**Returns**: void (retire la cible morte des caches)

```javascript
update_los_cache_after_target_death(dead_target_id):
├── Retirer de position_cache:
│   └── del position_cache[dead_target_id]
├── active_unit_id = game_state["active_shooting_unit"]  // Seule l'unité active a un los_cache
├── If active_unit_id:
│   ├── active_unit = get_unit_by_id(active_unit_id)
│   ├── If active_unit AND active_unit["los_cache"] exists:
│   │   ├── If dead_target_id in active_unit["los_cache"]:
│   │   │   └── del active_unit["los_cache"][dead_target_id]
│   │   └── Continue
│   └── Continue
└── Caches mis à jour (pas de recalcul)
```

**Note:** Seule l'unité actuellement active a un `los_cache` (calculé à l'activation). Les autres unités dans `shoot_activation_pool` n'ont pas encore de cache car elles ne sont pas encore activées. Donc on met à jour uniquement l'unité active.

**Appelé à:**
- Après la mort d'une cible dans shooting_attack_controller

### Function: valid_target_pool_build(arg1, arg2, arg3)
**Purpose**: Construire le pool de cibles valides pour une unité active  
**Returns**: valid_target_pool (liste d'IDs de cibles)

**FONCTIONNEMENT:**
1. `build_unit_los_cache` parcourt `position_cache` et calcule LoS pour chaque cible, stockant le résultat dans `unit["los_cache"] = {target_id: has_los}`
2. `valid_target_pool_build` filtre `los_cache` pour ne garder que les cibles avec `has_los == true` (optimisation)
3. Pour chaque cible avec LoS, on vérifie :
   - Distance (range d'**au moins une arme** dans `weapon_available_pool`)
   - PISTOL rule (si adjacent)
   - Engaged enemy rule (si pas adjacent)
4. Les cibles qui passent tous les checks sont ajoutées au pool

**IMPORTANT:** 
- `los_cache` contient toutes les cibles de `position_cache` avec leur statut LoS (true/false)
- On filtre d'abord pour ne garder que les cibles avec LoS (pas besoin de vérifier LoS dans la boucle)
- Pas besoin de vérifier `target_id in position_cache` car `los_cache` est construit depuis `position_cache`
- Si une cible meurt, elle est retirée de `position_cache` ET de `los_cache` par `update_los_cache_after_target_death`
- **Distance check:** On vérifie si la cible est dans la portée d'**au moins une arme** du `weapon_available_pool`, pas seulement de `selected_weapon` (l'unité peut changer d'arme)

```javascript
valid_target_pool_build(arg1, arg2, arg3):
├── valid_target_pool = []
├── ASSERT: unit["los_cache"] exists (doit être créé par build_unit_los_cache à l'activation)
├── weapon_available_pool = weapon_availability_check(arg1, arg2, arg3)  // Build weapon_available_pool
├── usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
├── Filter los_cache: targets_with_los = {target_id: true for target_id, has_los in unit["los_cache"].items() if has_los == true}
├── For each target_id in targets_with_los.keys():
│   ├── enemy_unit = get_unit_by_id(target_id)
│   ├── distance = calculate_distance(unit, enemy_unit)
│   ├── Range check: distance <= RNG of AT LEAST ONE weapon in usable_weapons? → NO → Skip enemy unit
│   ├── Adjacent check: enemy adjacent to shooter?
│   │   ├── YES → Check PISTOL weapon rule
│   │   └── NO → Check engaged enemy rule
│   └── ALL conditions met → ✅ Add target_id to valid_target_pool
└── Return valid_target_pool
```

**OPTIMISATION:** On filtre `los_cache` pour ne garder que les cibles avec LoS avant la boucle, évitant de vérifier `has_los == false` à chaque itération.

**Performance:** 
- Utilise le cache LoS pré-calculé au lieu de recalculer à chaque fois
- `build_unit_los_cache()` utilise `has_line_of_sight_coords()` qui exploite `hex_los_cache` pour éviter les recalculs entre mêmes coordonnées
- Complexité : O(m) où m = nombre de cibles dans `position_cache` (au lieu de O(m×n) avec `_get_unit_by_id()`)

**Cas limites :**
- Si `unit["los_cache"]` n'existe pas ET `unit.id NOT in units_fled` : **ERREUR** (doit être créé par `build_unit_los_cache` à l'activation)
- Si `unit["los_cache"]` n'existe pas ET `unit.id in units_fled` : NORMAL - l'unité ne peut pas tirer, mais peut avancer
- Si `unit["los_cache"]` est vide `{}` : Aucune cible dans `position_cache` → `valid_target_pool = []`
- Si toutes les cibles sont filtrées (pas de LoS, pas de range, etc.) : `valid_target_pool = []`
- Si `valid_target_pool` est vide ET unité n'a pas encore tiré : → Go to STEP 6: EMPTY_TARGET_HANDLING (l'unité peut avancer si `CAN_ADVANCE == true`)
- Si `valid_target_pool` est vide ET unité a déjà tiré : → Fin d'activation (on ne peut pas avancer après avoir tiré)

### Function: weapon_selection()
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

### Function: shoot_action(target)
**Purpose**: Exécuter une séquence de tir  
**Returns**: void (met à jour SHOOT_LEFT, weapon.shot, valid_target_pool)

```javascript
shoot_action(target):
├── Execute attack_sequence(RNG)
├── Concatenate Return to TOTAL_ACTION log
├── SHOOT_LEFT -= 1
├── Target died?
│   ├── YES → 
│   │   ├── update_los_cache_after_target_death(target_id)
│   │   ├── Remove from valid_target_pool
│   │   └── valid_target_pool empty? → YES → End activation
│   └── NO → Target survives
└── SHOOT_LEFT == 0 ?
    ├── YES → Current weapon exhausted:
    │   ├── Mark selected_weapon as used
    │   └── weapon_available_pool NOT empty?
    │       ├── YES → Select next available weapon:
    │       │   ├── selected_weapon = next weapon
    │       │   ├── SHOOT_LEFT = selected_weapon.NB
    │       │   ├── Determine context:
    │       │   │   ├── arg1 = weapon_rule
    │       │   │   ├── arg2 = (unit.id in units_advanced) ? 1 : 0
    │       │   │   └── arg3 = (unit adjacent to enemy?) ? 1 : 0
    │       │   ├── valid_target_pool_build(weapon_rule, arg2, arg3)  // Utilise unit["los_cache"]
    │       │   └── Continue to shooting action selection
    │       └── NO → All weapons exhausted → End activation
    └── NO → Continue normally (SHOOT_LEFT > 0):
        └── Continue to shooting action selection step
```

Après la mort d'une cible, les caches sont mis à jour (retirer l'entrée) au lieu de recalculer.

**Flow Control - "Continue normally":**
- **When**: After executing shot with SHOOT_LEFT > 0 remaining
- **Process**:
  1. Handle target outcome (died/survived)
  2. Update valid_target_pool (remove dead targets)
  3. Run final safety check (slaughter handling if no targets remain)
  4. Loop back to shooting action selection step
- **Purpose**: Maintain multi-shot sequence until SHOOT_LEFT = 0 or no targets remain

### Function: POSTPONE_ACTIVATION() (Human only)
**Purpose**: Allow human player to postpone unit activation  
**Trigger**: Human clicks elsewhere without shooting AND unit has NOT shot with ANY weapon

```javascript
POSTPONE_ACTIVATION():
├── Unit is NOT removed from shoot_activation_pool (can be re-activated later)
├── Remove weapon selection icon from UI
└── Return to UNIT_ACTIVABLE_CHECK step
```

---

## 🎯 SECTION 3: PHASE FLOW (Main Decision Tree)

### STEP 0: PHASE INITIALIZATION

**Purpose**: Initialiser les caches globaux au début de la phase (position_cache, pools ; le cache kill probability n'est pas construit ici, voir note ci-dessous)

**Appelé à:** 
- Début de la phase de tir (appelé automatiquement dans `execute_action` si `_shooting_phase_initialized` est False)
- Une seule fois par phase de tir

```javascript
shooting_phase_start():
├── Set phase = "shoot"
├── Initialize weapon_rule = 1
├── Clear target_pool_cache (cache global obsolète)
├── Initialize weapon.shot = 0 for all units
├── build_position_cache()  // Construire position_cache
├── shooting_build_activation_pool()  // Build shoot_activation_pool (appelle STEP 1)
└── Continue to STEP 2: UNIT_ACTIVABLE_CHECK
```

**Note:** `shooting_phase_start()` appelle aussi `shooting_build_activation_pool()` qui implémente le STEP 1: ELIGIBILITY CHECK.

**Cache kill probability:** Le cache `game_state["kill_probability_cache"]` n'est plus construit en début de phase. Il est rempli à la demande (lazy) lors du premier appel à `select_best_ranged_weapon()` / `select_best_melee_weapon()` pour une paire (unité, cible). Voir `engine/ai/weapon_selector.py`.

### STEP 1: ELIGIBILITY CHECK (Pool Building Phase)

**Purpose**: Determine which units can participate in shooting phase  
**Output**: shoot_activation_pool (set of eligible units)

```javascript
shooting_build_activation_pool():
├── shoot_activation_pool = []
├── For each unit in game_state["units"]:
│   ├── unit.player === current_player? → NO → Skip
│   ├── unit.HP_CUR > 0? → NO → Skip
│   ├── unit.id in units_fled? → YES → Check CAN_ADVANCE only (cannot shoot)
│   │   ├── Determine adjacency: Unit adjacent to enemy? → YES → CAN_ADVANCE = false, NO → CAN_ADVANCE = true
│   │   ├── CAN_ADVANCE == true? → YES → Add unit.id to pool (can advance but not shoot)
│   │   └── CAN_ADVANCE == false? → Skip (no valid actions)
│   ├── unit.id NOT in units_fled? → Check CAN_SHOOT OR CAN_ADVANCE
│   │   └── Determine adjacency: Unit adjacent to enemy?
│   │       ├── YES → 
│   │       │   ├── CAN_ADVANCE = false (cannot advance when adjacent)
│   │       │   ├── weapon_availability_check(weapon_rule, 0, 1) → Build weapon_available_pool
│   │       │   ├── CAN_SHOOT = (weapon_available_pool NOT empty)
│   │       │   └── CAN_SHOOT == false? → YES → Skip (no valid actions)
│   │       │   └── CAN_SHOOT == true? → YES → Add unit.id to pool
│   │       └── NO →
│   │           ├── CAN_ADVANCE = true
│   │           ├── weapon_availability_check(weapon_rule, 0, 0) → Build weapon_available_pool
│   │           ├── CAN_SHOOT = (weapon_available_pool NOT empty)
│   │           ├── (CAN_SHOOT OR CAN_ADVANCE)? → NO → Skip (no valid actions)
│   │           └── (CAN_SHOOT OR CAN_ADVANCE)? → YES → Add unit.id to pool
│   └── Continue
└── Store in game_state["shoot_activation_pool"]
```

**Note:** 
- La logique d'éligibilité est calculée directement dans la boucle (comme dans `AI_TURN.md` lignes 590-611).
- **IMPORTANT:** Une unité qui a fui (`unit.id in units_fled`) peut avancer mais **ne peut pas tirer**. Elle est ajoutée au pool si `CAN_ADVANCE == true` (pas adjacent à un ennemi).
- **NOTE:** Le code actuel utilise `_has_valid_shooting_targets()` qui existe dans `shooting_handlers.py`, mais cette fonction doit être modifiée pour gérer correctement les unités qui ont fui (actuellement elle retourne `False` pour les unités qui ont fui, alors qu'elle devrait vérifier `CAN_ADVANCE`).

### STEP 2: UNIT_ACTIVABLE_CHECK

**Purpose**: Activer une unité et construire ses caches

```javascript
STEP : UNIT_ACTIVABLE_CHECK
├── shoot_activation_pool NOT empty?
│   ├── YES → Pick one unit from shoot_activation_pool:
│   │   ├── Clear valid_target_pool
│   │   ├── Clear TOTAL_ATTACK log
│   │   ├── build_unit_los_cache(unit_id)  // Calculer cache LoS
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

**IMPORTANT:** Une unité qui a fui (`unit.id in units_fled`) **ne peut pas tirer**, mais **peut avancer** si elle n'est pas adjacente à un ennemi. Dans ce cas, on ne construit pas `los_cache` ni `valid_target_pool`.

### STEP 3: ACTION_SELECTION (Initial State - valid_target_pool NOT empty)

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

### STEP 4: ADVANCE ACTION

**Purpose**: Exécuter l'action advance et mettre à jour les caches

```javascript
ADVANCE ACTION:
├── Execute advance movement
├── Unit actually moved to different hex?
│   ├── YES → Unit advanced:
│   │   ├── Mark units_advanced
│   │   ├── build_unit_los_cache(unit_id)  // Recalculer cache LoS avec nouvelle position
│   │   ├── Invalidate valid_target_pool (vide le pool)
│   │   ├── valid_target_pool_build(weapon_rule, arg2=1, arg3=0)  // Reconstruire pool avec nouveau cache
│   │   └── Continue to shooting action selection
│   └── NO → Unit didn't move → Continue normally
└── Continue to shooting action selection
```

Le cache LoS est recalculé après l'advance, puis le pool est reconstruit.

### STEP 5: SHOOTING_ACTION_SELECTION

**Purpose**: Execute shooting sequence  
**Two variants**: Normal (unit has NOT advanced) vs Advanced (post-advance state)

#### STEP 5A: SHOOTING_ACTION_SELECTION (Normal - unit has NOT advanced)

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

#### STEP 5B: ADVANCED_SHOOTING_ACTION_SELECTION (Post-advance state)

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

### STEP 6: EMPTY_TARGET_HANDLING (valid_target_pool is empty)

**Purpose**: Handle case when no valid targets are available  
**Context**: Unit was eligible but has no targets

```javascript
STEP : EMPTY_TARGET_HANDLING
└── unit.CAN_ADVANCE = true?
    ├── YES → Only action available is advance:
    │   ├── Display ADVANCE icon (waiting for user click)
    │   ├── Human: Click ADVANCE logo → ⚠️ POINT OF NO RETURN
    │   │   └── Execute player_advance() → Roll 1D6 → advance_range → Build destinations → unit_advanced (boolean)
    │   └── unit_advanced = true?
    │       ├── YES → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │       └── NO → end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── NO → unit.CAN_ADVANCE = false → No valid actions available:
        └── end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
```

### STEP 7: WAIT_ACTION (Initial state, no shooting available)

**Purpose**: End activation without action  
**Context**: Player chooses to wait (no valid actions or player decision)

```javascript
STEP : WAIT_ACTION
├── AI: Agent chooses wait
├── Human: Player chooses wait
└── end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
```

### STEP 7: END_ACTIVATION

**Purpose**: Nettoyer les données temporaires de l'unité

**Appelé à:**
- Fin de l'activation d'une unité (via `end_activation()` ou `_shooting_activation_end()`)

```javascript
end_activation(...) / _shooting_activation_end(...):
├── Remove unit from shoot_activation_pool
├── If "valid_target_pool" in unit:
│   └── del unit["valid_target_pool"]  // Nettoyer pool
├── If "los_cache" in unit:
│   └── del unit["los_cache"]  // Nettoyer cache LoS
├── If "active_shooting_unit" in game_state:
│   └── del game_state["active_shooting_unit"]  // Nettoyer unité active
├── Clear TOTAL_ATTACK_LOG
├── Clear selected_target_id
└── SHOOT_LEFT = 0
```

Le cache LoS est nettoyé à la fin de l'activation, comme valid_target_pool. `active_shooting_unit` est nettoyé pour permettre l'activation de la prochaine unité.

---

## 🔄 SECTION 4: FLOW SUMMARY & STEP TRANSITIONS

### Complete Step Flow
```
UNIT_ACTIVABLE_CHECK
  → ACTION_SELECTION (if valid_target_pool NOT empty)
  → [ADVANCE_ACTION | SHOOTING_ACTION_SELECTION | WAIT_ACTION]
  → [ADVANCED_SHOOTING_ACTION_SELECTION] (if advanced)
  → [EMPTY_TARGET_HANDLING] (if valid_target_pool empty)
  → UNIT_ACTIVABLE_CHECK
  → (repeat until pool empty) → End of shooting phase
```

### Key Step Transitions
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

## 📖 SECTION 5: CONCEPTUAL EXPLANATIONS

### Target Restrictions Logic

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

### Multiple Shots Logic

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

### Advance Distance Logic

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

### Key Differences Between AI and Human Players

1. **Target Selection**: AI automatically chooses best target; Human clicks on target
2. **UI Display**: Both AI and Human see blue preview (see UI Display Constants above)
3. **Weapon Selection**: Human can change weapons via UI; AI pre-selects best weapon
4. **Action Selection**: AI chooses programmatically; Human clicks UI elements
5. **Postpone Logic**: Only Human can postpone activation (click elsewhere)

---

## 🔄 FLUX D'EXÉCUTION COMPLET

```
1. shooting_phase_start()
   └── build_position_cache()  // Construire snapshot positions ennemies

2. UNIT_ACTIVABLE_CHECK
   └── build_unit_los_cache(unit_id)  // Calculer cache LoS pour cette unité
   └── valid_target_pool_build()  // Utilise unit["los_cache"]

3. ACTION_SELECTION
   └── Agent choisit action (ADVANCE ou SHOOT)
   │
   ├── Si ADVANCE choisi:
   │   └── Unit avance
   │   └── build_unit_los_cache(unit_id)  // Recalculer cache avec nouvelle position
   │   └── valid_target_pool_build()  // Reconstruire pool avec nouveau cache
   │   └── Retour à ACTION_SELECTION (peut maintenant tirer)
   │
   └── Si SHOOT choisi:
       └── Agent sélectionne target
       └── Vérifie target_id in valid_target_pool
       └── Execute shoot_action(target)

4. SHOOT ACTION
   └── shooting_attack_controller()
   └── Target meurt?
       └── YES → update_los_cache_after_target_death()  // Retirer de caches
       └── Retirer de valid_target_pool
   └── SHOOT_LEFT > 0? → Retour à ACTION_SELECTION

5. END_ACTIVATION
   └── del unit["valid_target_pool"]
   └── del unit["los_cache"]  // Nettoyer cache
```

## ⚠️ POINTS CRITIQUES

1. **position_cache** doit être mis à jour après chaque mort de cible
2. **unit["los_cache"]** doit être recalculé après chaque advance (pas juste invalidé)
3. **unit["los_cache"]** doit être nettoyé à la fin de l'activation
4. Le pool est la source de vérité, et utilise le cache LoS pour la performance
5. Pas de recalcul après mort de cible, juste retirer l'entrée du cache

---

## 🔍 CAS LIMITES : POOLS ET CACHES VIDES

### Cas 1 : `los_cache` vide ou inexistant

**Scénarios possibles :**

1. **`los_cache` n'existe pas (clé absente de `unit`) :**
   - **Cause :** `build_unit_los_cache()` n'a pas été appelé
   - **Situation :** 
     - **ERREUR** si `unit.id NOT in units_fled` (doit être créé à l'activation STEP 2)
     - **NORMAL** si `unit.id in units_fled` - on ne construit pas intentionnellement le cache (l'unité ne peut pas tirer, mais peut avancer)
   - **Comportement :** 
     - Si unité normale : `valid_target_pool_build()` doit ASSERT que `unit["los_cache"]` existe
     - Si unité a fui : `valid_target_pool_build()` n'est pas appelé (l'unité ne peut pas tirer)
   - **Action :** 
     - Si unité normale : Corriger le code pour garantir l'appel de `build_unit_los_cache()`
     - Si unité a fui : Aucune - comportement attendu

2. **`los_cache` existe mais est vide `{}` :**
   - **Cause :** `position_cache` est vide (pas d'ennemis sur le terrain)
   - **Situation :** NORMAL - pas d'ennemis, donc pas de LoS à calculer
   - **Comportement :** `valid_target_pool_build()` retourne `[]` (pool vide)
   - **Action :** Aucune - comportement attendu

### Cas 2 : `valid_target_pool` vide

**Scénarios possibles :**

1. **Pool vide après construction (unité n'a pas encore tiré) :**
   - **Causes possibles :**
     - Aucune cible avec LoS (toutes bloquées par des murs)
     - Aucune cible à portée (toutes trop loin)
     - Toutes les cibles sont engagées avec des unités amies (sans PISTOL)
     - Toutes les cibles adjacentes sans arme PISTOL
   - **Situation :** NORMAL - aucune cible valide selon les règles
   - **Comportement :** 
     - Si `CAN_ADVANCE == true` → Go to STEP 3: ACTION_SELECTION (peut avancer)
     - Si `CAN_ADVANCE == false` → Go to STEP 6: EMPTY_TARGET_HANDLING (fin d'activation)
   - **Action :** Aucune - comportement attendu

2. **Pool vide après mort de toutes les cibles (unité a déjà tiré) :**
   - **Cause :** Toutes les cibles dans le pool sont mortes après des tirs
   - **Situation :** NORMAL - toutes les cibles ont été éliminées
   - **Comportement :** Fin d'activation (STEP 7: END_ACTIVATION) - **on ne peut pas avancer après avoir tiré**
   - **Action :** Aucune - comportement attendu

3. **Pool vide après advance :**
   - **Cause :** Après advance, aucune cible n'est valide (nouvelle position, nouvelles contraintes)
   - **Situation :** NORMAL - l'advance peut avoir changé les conditions
   - **Comportement :** 
     - Si `CAN_ADVANCE == true` → Peut encore avancer (si pas déjà avancé)
     - Sinon → Fin d'activation
   - **Action :** Aucune - comportement attendu

### Cas 3 : `position_cache` vide

**Scénario :**
- **Cause :** Aucun ennemi vivant sur le terrain
- **Situation :** RARE mais possible (tous les ennemis sont morts)
- **Comportement :**
  - `build_unit_los_cache()` crée `unit["los_cache"] = {}` (vide)
  - `valid_target_pool_build()` retourne `[]` (pool vide)
  - Toutes les unités peuvent avancer mais pas tirer
- **Action :** Aucune - comportement attendu

### Gestion des erreurs

**Assertions à implémenter :**ascript
// Dans valid_target_pool_build()
ASSERT: unit["los_cache"] exists (doit être créé par build_unit_los_cache)
// Si assertion échoue → ERREUR, corriger le code

// Dans build_unit_los_cache()
ASSERT: game_state["position_cache"] exists (doit être créé par build_position_cache)
// Si assertion échoue → ERREUR, corriger le code


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

## 📝 Document Notes

**This is an optimized version of the Shooting Phase documentation.**

**Optimizations made:**
- ✅ All features preserved (no functionality removed)
- ✅ Clear hierarchical structure: Variables → Functions → Flow → Concepts
- ✅ Unified function definitions (AI/Human differences marked explicitly)
- ✅ Step-based flow control (numbered steps for clarity)
- ✅ Complete reference tables for function arguments
- ✅ Enhanced readability with better organization
- ✅ Clarified state management and transitions
- ✅ Better separation of concerns (functions vs flow)

---

## ⚡ CHARGE PHASE
│   │   │       │   ├── Build VALID_ACTIONS list based on current state:
│   │   │       │   │   ├── If unit.CAN_SHOOT = true AND valid_target_pool NOT empty → Add "shoot"
│   │   │       │   │   ├── If unit.CAN_ADVANCE = true → Add "advance"
│   │   │       │   │   └── Always add "wait"
│   │   │       │   ├── 🎯 VALID ACTIONS: [shoot (if CAN_SHOOT), advance (if CAN_ADVANCE), wait]
│   │   │       │   ├── ❌ INVALID ACTIONS: [move, charge, attack] → end_activation(ERROR, 0, 0, SHOOTING, 1, 1)
│   │   │       │   └── STEP : AGENT_ACTION_SELECTION
│   │   │       │       ├── Choose advance?
│   │   │       │       │   ├── YES → ✅ VALID → Execute advance action
│   │   │       │       │   │── Roll 1D6 → advance_range (from config: advance_distance_range)
│   │   │       │       │   │── Display advance_range on unit icon
│   │   │       │       │   │── Build valid_advance_destinations (BFS, advance_range, no walls, no enemy-adjacent)
│   │   │       │       │   │── Select destination hex (AI chooses best destination)
│   │   │       │       │   └── Unit actually moved to different hex?
│   │   │       │       │      ├── YES → Unit advanced
│   │   │       │       │      │   ├── Mark units_advanced, log action, do NOT remove from pool, do NOT remove green circle
│   │   │       │       │      │   │   └── Log advance action: end_activation (ACTION, 1, ADVANCE, NOT_REMOVED, 1, 0)
│   │   │       │       │      │   ├── Clear any unit remaining in valid_target_pool
│   │   │       │       │      │   ├── weapon_availability_check (weapon_rule,1,0) → Only Assault weapons available
│   │   │       │       │      │   ├── At least ONE Assault weapon is available?
│   │   │       │       │      │   │   ├── YES → CAN_SHOOT = true → Store unit.CAN_SHOOT = true
│   │   │       │       │      │   │   └── NO → CAN_SHOOT = false → Store unit.CAN_SHOOT = false
│   │   │       │       │      │   ├── unit.CAN_ADVANCE = false (unit has advanced, cannot advance again)
│   │   │       │       │      │   ├── Pre-select the first available weapon
│   │   │       │       │      │   ├── SHOOT_LEFT = selected_weapon.NB
│   │   │       │       │      │   ├── Unit has advanced (arg2=1), not adjacent (arg3=0, advance restrictions prevent adjacent destinations)
│   │   │       │       │      │   |   └── valid_target_pool_build (weapon_rule, arg2=1, arg3=0)
│   │   │       │       │      │   └── valid_target_pool NOT empty AND unit.CAN_SHOOT = true ?
│   │   │       │       │      │       ├── YES → SHOOTING ACTIONS AVAILABLE (post-advance)
│   │   │       │       │      │       │   ├── STEP : AGENT_ADVANCED_SHOOTING_ACTION_SELECTION
│   │   │       │       │      │       │   ├── Display the shooting preview (all the hexes with LoS and selected_weapon.RNG are red)
│   │   │       │       │      │       │   ├── Display the HP bar blinking animation for every unit in valid_target_pool
│   │   │       │       │      │       │   ├── Build VALID_ACTIONS list:
│   │   │       │       │      │       │   │   ├── If unit.CAN_SHOOT = true AND valid_target_pool NOT empty → Add "shoot"
│   │   │       │       │      │       │   │   └── Always add "wait"
│   │   │       │       │      │       │   ├── 🎯 VALID ACTIONS: [shoot (if CAN_SHOOT), wait]
│   │   │       │       │      │       │   ├── ❌ INVALID ACTIONS: [advance, move, charge, attack] → end_activation(ERROR, 0, 0, SHOOTING, 1, 1)
│   │   │       │       │      │       │   └── AGENT ACTION SELECTION → Choose shoot?
│   │   │       │       │      │       │       ├── YES → ✅ VALID → Execute shoot action
│   │   │       │       │      │       │       │   ├── agent_shoot_action()
│   │   │       │       │      │       │       └── NO → Agent chooses: wait?
│   │   │       │       │      │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │       │       │      │       │           │   └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │   │       │       │      │       │           │       ├── YES → Unit has already shot → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │   │       │       │      │       │           │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │      │       │           │       └── NO → Unit has not shot yet (only advanced) → end_activation (ACTION, 1, ADVANCE, SHOOTING, 1, 1)
│   │   │       │       │      │       │           │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │      │       │           └── NO → Agent chooses invalid action (move/charge/attack)?
│   │   │       │       │      │       │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, 0, SHOOTING, 1, 1)
│   │   │       │       │      │       │                   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │      │       └── NO → Unit advanced but no valid targets available → end_activation (ACTION, 1, ADVANCE, SHOOTING, 1, 1)
│   │   │       │       │      │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │      └── NO → Unit did not advance → Continue without marking (unit not added to units_advanced, stays in shoot_activation_pool)
│   │   │       │       │          └── GO TO STEP : AGENT_ACTION_SELECTION
│   │   │       │       ├── Choose shoot?
│   │   │       │       │   ├── YES → ✅ VALID → Execute shoot action
│   │   │       │       │   └── STEP : AGENT_SHOOTING_ACTION_SELECTION
│   │   │       │       │       ├── Select target from valid_target_pool (AI chooses best target)
│   │   │       │       │       ├── Execute attack_sequence(RNG)
│   │   │       │       │       ├── Concatenate Return to TOTAL_ACTION log
│   │   │       │       │       ├── SHOOT_LEFT -= 1
│   │   │       │       │       └── SHOOT_LEFT == 0 ?
│   │   │       │       │           ├── YES → Current weapon exhausted
│   │   │       │       │           │   ├── Remove selected_weapon from weapon_available_pool (mark as used/greyed)
│   │   │       │       │           │   └── Is there any available weapons in weapon_available_pool ?
│   │   │       │       │           │       ├── YES → Select next available weapon (AI chooses best weapon)
│   │   │       │       │           │       │   ├── This weapon becomes selected_weapon
│   │   │       │       │           │       │   ├── SHOOT_LEFT = selected_weapon.NB
│   │   │       │       │           │       │   ├── Determine context: Is unit adjacent to enemy unit?
│   │   │       │       │           │       │   │   ├── YES → arg3 = 1
│   │   │       │       │           │       │   │   └── NO → arg3 = 0
│   │   │       │       │           │       │   ├── valid_target_pool_build (weapon_rule, arg2=0, arg3) → Unit has NOT advanced (arg2=0)
│   │   │       │       │           │       │   └── GO TO STEP : AGENT_SHOOTING_ACTION_SELECTION
│   │   │       │       │           │       └── NO → All weapons exhausted → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │   │       │       │           │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │           └── NO → Continue normally (SHOOT_LEFT > 0)
│   │   │       │       │               ├── selected_target dies ?
│   │   │       │       │               │   ├── YES → Remove from valid_target_pool
│   │   │       │       │               │   │   ├── valid_target_pool empty ?
│   │   │       │       │               │   │   │   ├── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │   │       │       │               │   │   │   │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │               │   │   │   └── NO → Continue (other targets remain)
│   │   │       │       │               │   │   │       └── GO TO STEP : AGENT_SHOOTING_ACTION_SELECTION
│   │   │       │       │               │   │   └── (target removed from pool)
│   │   │       │       │               │   └── NO → selected_target survives
│   │   │       │       │               └── Final safety check (if target survived or edge case): valid_target_pool empty AND SHOOT_LEFT > 0 ?
│   │   │       │       │                   ├── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │   │       │       │                   │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │       │                   └── NO → Continue
│   │   │       │       │                       └── GO TO STEP : AGENT_SHOOTING_ACTION_SELECTION
│   │   │       │       └── NO → Agent chooses: wait?
│   │   │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │       │           │   └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │   │       │           │       ├── YES → Unit has already shot → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │   │       │           │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │           │       └── NO → Unit has not shot yet → end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   │   │       │           │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       │           └── NO → Agent chooses invalid action (move/charge/attack)?
│   │   │       │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, 0, SHOOTING, 1, 1)
│   │   │       │                   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │       └── NO → valid_target_pool is empty
│   │   │           └── unit.CAN_ADVANCE = true ?
│   │   │               ├── YES → Only action available is advance
│   │   │               │   └── AGENT ACTION SELECTION → Choose advance?
│   │   │               │       ├── YES → ✅ VALID → Execute advance action
│   │   │               │       │   ├── Roll 1D6 → advance_range (from config: advance_distance_range)
│   │   │               │       │   ├── Display advance_range on unit icon
│   │   │               │       │   ├── Build valid_advance_destinations (BFS, advance_range, no walls, no enemy-adjacent)
│   │   │               │       │   ├── Select destination hex (AI chooses best destination)
│   │   │               │       │   └── Unit actually moved to different hex?
│   │   │               │       │       ├── YES → end_activation (ACTION, 1, ADVANCE, SHOOTING, 1, 1)
│   │   │               │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │               │       │       └── NO → end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   │   │               │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │               │       └── NO → Agent chooses: wait?
│   │   │               │           ├── YES → ✅ VALID → Execute wait action
│   │   │               │           │   └── end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   │   │               │           │       └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │               │           └── NO → Agent chooses invalid action?
│   │   │               │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, 0, SHOOTING, 1, 1)
│   │   │               │                   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │               └── NO → unit.CAN_ADVANCE = false → No valid actions available
│   │   │                   └── end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   │   │                       └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │
│   │   │      ####################################################################################################################
│   │   │      ########################################            HUMAN PLAYER            ########################################
│   │   │      ####################################################################################################################
│   │   │
│   │   └── NO → Human player → STEP : UNIT_ACTIVATION → player activate one unit from shoot_activation_pool by left clicking on it
│   │       ├── Clear any unit remaining in valid_target_pool
│   │       ├── Clear TOTAL_ATTACK log
│   │       ├── Is the active unit adjacent to an enemy unit ?
│   │       │   ├── YES → weapon_availability_check (weapon_rule,0,1) → Build weapon_available_pool (only PISTOL weapons if weapon_rule=1)
│   │       │   │   └── Store: unit_is_adjacent = true
│   │       │   └── NO → weapon_availability_check (weapon_rule,0,0) → Build weapon_available_pool (all available weapons)
│   │       │       └── Store: unit_is_adjacent = false
│   │       ├── valid_target_pool_build (weapon_rule, arg2=0, arg3=unit_is_adjacent ? 1 : 0) → Build valid_target_pool using weapon_available_pool
│   │       └── valid_target_pool NOT empty ?
│   │           ├── YES
│   │           │   ├── Pre-select the first available weapon
│   │           │   ├── SHOOT_LEFT = selected_weapon.NB
│   │           │   ├── Display the shooting preview (all the hexes with LoS and selected_weapon.RNG are blue)
│   │           │   ├── Display the HP bar blinking animation for every unit in valid_target_pool
│   │           │   ├── Build UI elements based on current state:
│   │           │   │   ├── If unit.CAN_SHOOT = true AND valid_target_pool NOT empty → Display weapon selection icon
│   │           │   │   └── If unit.CAN_ADVANCE = true → Display advance icon
│   │           │   ├── Display advance icon (if CAN_ADVANCE) AND weapon selection icon (if CAN_SHOOT)
│   │           │   └── STEP : PLAYER_ACTION_SELECTION
│   │           │       ├── Click ADVANCE logo → ⚠️ POINT OF NO RETURN
│   │           │       │   ├── Perform player_advance() → unit_advanced (boolean)
│   │           │       │   └── unit_advanced = true ?
│   │           │       │       ├── YES → Unit advanced
│   │           │       │       │   ├── Mark units_advanced, log action, do NOT remove from pool, do NOT remove green circle
│   │           │       │       │   │   └── Log advance action: end_activation (ACTION, 1, ADVANCE, NOT_REMOVED, 1, 0)
│   │           │       │       │   ├── Clear any unit remaining in valid_target_pool
│   │           │       │       │   ├── weapon_availability_check (weapon_rule,1,0) → Only Assault weapons available
│   │           │       │       │   ├── At least ONE Assault weapon is available?
│   │           │       │       │   │   ├── YES → CAN_SHOOT = true → Store unit.CAN_SHOOT = true
│   │           │       │       │   │   └── NO → CAN_SHOOT = false → Store unit.CAN_SHOOT = false
│   │           │       │       │   ├── unit.CAN_ADVANCE = false (unit has advanced, cannot advance again)
│   │           │       │       │   ├── Pre-select the first available weapon
│   │           │       │       │   ├── SHOOT_LEFT = selected_weapon.NB
│   │           │       │       │   ├── Unit has advanced (arg2=1), not adjacent (arg3=0, advance restrictions prevent adjacent destinations)
│   │           │       │       │   |   └── valid_target_pool_build (weapon_rule, arg2=1, arg3=0)
│   │           │       │       │   └── valid_target_pool NOT empty AND unit.CAN_SHOOT = true ?
│   │           │       │       │       ├── YES → SHOOTING ACTIONS AVAILABLE
│   │           │       │       │       │   ├── STEP : PLAYER_ADVANCED_SHOOTING_ACTION_SELECTION
│   │           │       │       │       │   ├── Display the shooting preview (all the hexes with LoS and selected_weapon.RNG are blue)
│   │           │       │       │       │   ├── Display the HP bar blinking animation for every unit in valid_target_pool
│   │           │       │       │       │   └── Display weapon selection icon (only if unit.CAN_SHOOT = true)
│   │           │       │       │       │       ├── Left click on the weapon selection icon
│   │           │       │       │       │       │   ├── weapon_selection():
│   │           │       │       │       │       │   └── GO TO STEP : PLAYER_ADVANCED_SHOOTING_ACTION_SELECTION
│   │           │       │       │       │       ├── Left click on a target in valid_target_pool
│   │           │       │       │       │       │   ├── Execute attack_sequence(RNG)
│   │           │       │       │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │           │       │       │       │       │   ├── SHOOT_LEFT -= 1
│   │           │       │       │       │       │   └── SHOOT_LEFT == 0 ?
│   │           │       │       │       │       │       ├── YES → Current weapon exhausted
│   │           │       │       │       │       │       │   ├── Remove selected_weapon from weapon_available_pool (mark as used/greyed)
│   │           │       │       │       │       │       │   └── Is there any available weapons in weapon_available_pool
│   │           │       │       │       │       │       │       ├── YES → weapon_selection()
│   │           │       │       │       │       │       │       │   └── GO TO STEP : PLAYER_ADVANCED_SHOOTING_ACTION_SELECTION
│   │           │       │       │       │       │       │       └── NO → All weapons exhausted → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │       │       │       │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │       │       └── NO → Continue normally (SHOOT_LEFT > 0)
│   │           │       │       │       │       │           ├── selected_target dies ?
│   │           │       │       │       │       │           │   ├── YES → Remove from valid_target_pool
│   │           │       │       │       │       │           │   │   ├── valid_target_pool empty ?
│   │           │       │       │       │       │           │   │   │   ├── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │       │       │       │       │           │   │   │   │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │       │           │   │   │   └── NO → Continue (other targets remain)
│   │           │       │       │       │       │           │   │   │       └── GO TO STEP : PLAYER_ADVANCED_SHOOTING_ACTION_SELECTION
│   │           │       │       │       │       │           │   │   └── (target removed from pool)
│   │           │       │       │       │       │           │   └── NO → selected_target survives
│   │           │       │       │       │       │           └── Final safety check (if target survived or edge case): valid_target_pool empty AND SHOOT_LEFT > 0 ?
│   │           │       │       │       │       │               ├── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │       │       │       │       │               │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │       │               └── NO → Continue
│   │           │       │       │       │       │                   └── GO TO STEP : PLAYER_ADVANCED_SHOOTING_ACTION_SELECTION
│   │           │       │       │       │       ├── Left click on another unit in shoot_activation_pool ?
│   │           │       │       │       │       │   └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │           │       │       │       │       │       ├── NO → Unit has not shot with any weapon yet → Postpone the shooting phase for this unit
│   │           │       │       │       │       │       |   ├── Unit is NOT removed from the shoot_activation_pool and can be re-activated later in the phase
│   │           │       │       │       │       │       |   ├── Remove the weapon selection icon
│   │           │       │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │       │       └── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │       │       │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │       ├── Left OR Right click on the active_unit
│   │           │       │       │       │       │   └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │           │       │       │       │       │       ├── YES → Unit has already shot → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │       │       │       │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │       │       └── NO → Unit has not shot yet (only advanced) → end_activation (ACTION, 1, ADVANCE, SHOOTING, 1, 1)
│   │           │       │       │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │       └── Left OR Right click anywhere else on the board (treated as potential misclick)
│   │           │       │       │       │           └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │           │       │       │       │               ├── NO → Unit has not shot with any weapon yet → Postpone the shooting phase for this unit
│   │           │       │       │       │               |   ├── Unit is NOT removed from the shoot_activation_pool and can be re-activated later in the phase
│   │           │       │       │       │               |   ├── Remove the weapon selection icon
│   │           │       │       │       │               │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       │       │               └── YES → Unit has already shotif desired)
│   │           │       │       │       │                   ├── Do not end activation automatically (allow user to click active unit to confirm it)
│   │           │       │       │       │                   └── GO TO STEP : PLAYER_ADVANCED_SHOOTING_ACTION_SELECTION
│   │           │       │       │       └── NO → Unit advanced but no valid targets available → end_activation (ACTION, 1, ADVANCE, SHOOTING, 1, 1)
│   │           │       │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │       │       └── NO → Unit did not advance → Continue without marking (unit not added to units_advanced, stays in shoot_activation_pool)
│   │           │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│   │           │       └── STEP : PLAYER_SHOOTING_ACTION_SELECTION
│   │           │           ├── Left click on the weapon selection icon
│   │           │           │   ├── weapon_selection():
│   │           │           |   └── GO TO STEP : PLAYER_SHOOTING_ACTION_SELECTION
│   │           │           ├── Left click on a target in valid_target_pool
│   │           │           │   ├── Execute attack_sequence(RNG)
│   │           │           │   ├── Concatenate Return to TOTAL_ACTION log
│   │           │           │   ├── SHOOT_LEFT -= 1
│   │           │           │   └── SHOOT_LEFT == 0 ?
│   │           │           │       ├── YES → Current weapon exhausted
│   │           │           │       │   ├── Remove selected_weapon from weapon_available_pool (mark as used/greyed)
│   │           │           │       │   └── Is there any available weapons in weapon_available_pool
│   │           │           │       │       ├── YES → weapon_selection()
│   │           │           │       │       │   └── GO TO STEP : PLAYER_SHOOTING_ACTION_SELECTION
│   │           │           │       │       └── NO → All weapons exhausted → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │           │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │           │       └── NO → Continue normally (SHOOT_LEFT > 0)
│   │           │           │           ├── selected_target dies ?
│   │           │           │           │   ├── YES → Remove from valid_target_pool
│   │           │           │           │   │   ├── valid_target_pool empty ?
│   │           │           │           │   │   │   ├── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │           │           │   │   │   │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │           │           │   │   │   └── NO → Continue (other targets remain)
│   │           │           │           │   │   │       └── GO TO STEP : PLAYER_SHOOTING_ACTION_SELECTION
│   │           │           │           │   │   └── (target removed from pool)
│   │           │           │           │   └── NO → selected_target survives
│   │           │           │           └── Final safety check (if target survived or edge case): valid_target_pool empty AND SHOOT_LEFT > 0 ?
│   │           │           │               ├── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │           │               │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │           │               └── NO → Continue
│   │           │           │                   └── GO TO STEP : PLAYER_SHOOTING_ACTION_SELECTION
│   │           │           ├── Left click on another unit in shoot_activation_pool ?
│   │           │           │   └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │           │           │       ├── NO → Unit has not shot with any weapon yet → Postpone the shooting phase for this unit
│   │           │           │       |   ├── Unit is NOT removed from the shoot_activation_pool and can be re-activated later in the phase
│   │           │           │       |   ├── Remove the weapon selection icon
│   │           │           │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │           │       └── YES → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │           │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │           ├── Left OR Right click on the active_unit
│   │           │           │   └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │           │           │       ├── YES → Unit has already shot → end_activation (ACTION, 1, SHOOTING, SHOOTING, 1, 1)
│   │           │           │       |   ├── Remove the weapon selection icon
│   │           │           │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │           │       └── NO → Unit has not shot yet → end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   │           │           │           ├── Remove the weapon selection icon
│   │           │           │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │           └── Left OR Right click anywhere else on the board (treated as potential misclick)
│   │           │               └── Check if unit has shot with ANY weapon (at least one weapon has weapon.shot = 1) ?
│   │           │                   ├── NO → Unit has not shot with any weapon yet → Postpone the shooting phase for this unit
│   │           │                   |   ├── Unit is NOT removed from the shoot_activation_pool and can be re-activated later in the phase
│   │           │                   │   ├── Remove the weapon selection icon
│   │           │                   │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │           │                   └── YES → Unit has already shot → 
│   │           │                       ├── Do not end activation automatically (allow user to click active unit to confirm if desired)
│   │           │                       └── GO TO STEP : PLAYER_SHOOTING_ACTION_SELECTION
│   │           └── NO → valid_target_pool is empty
│   │               └── unit.CAN_ADVANCE = true ?
│   │                   ├── YES → Only action available is advance
│   │                   │   ├── Click ADVANCE logo → ⚠️ POINT OF NO RETURN
│   │                   │   │   ├── Perform player_advance() → unit_advanced (boolean)
│   │                   │   │   └── unit_advanced = true ?
│   │                   │   │       ├── YES → end_activation (ACTION, 1, ADVANCE, SHOOTING, 1, 1)
│   │                   │   │       └── NO → end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   │                   │   └── Left or Right click on the active_unit → No effect
│   │                   │       └── end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   │                   └── NO → unit.CAN_ADVANCE = false → No valid actions available
│   │                       └── end_activation (WAIT, 1, 0, SHOOTING, 1, 1)
│   └── No more activable units → pass
└── End of shooting phase → Advance to charge phase
```

### Flow Control Terminology

**"Continue normally"** (in shooting context):
- **When**: After executing a shot with SHOOT_LEFT > 0 remaining
- **Meaning**: Continue the shooting sequence by:  
  1. Handling target outcome (died/survived)  
  2. Updating valid_target_pool  
  3. Running final safety check  
  4. Looping back to shooting action selection
- **Purpose**: Maintain multi-shot sequence until SHOOT_LEFT = 0 or no targets remain

### Target Restrictions Logic

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

### Multiple Shots Logic

**Multi-Shot Rules:**
- **All shots in one action**: Selected ranged weapon's NB shots fired as single activation
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
Marine (selected ranged weapon: NB = 2) faces two wounded Orks (both HP_CUR 1)
Shot 1: Target Ork A, kill it
Shot 2: Retarget to Ork B, kill it
Result: Eliminate two threats in one action through dynamic targeting
```
**Example 2:**
```
Marine (selected ranged weapon: NB = 2) faces one wounded Ork (HP_CUR 1) which is the only "Valid target"
Shot 1: Target the Ork, kill it

Shot 2: No more "Valid target" available, remaining shots are cancelled
Result: Avoid a shooting unit to be stuck because it as no more "Valid target" while having remaining shots to perform

```

### Advance Distance Logic

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
│   ├── units_advanced.includes(unit.id)?
│   │   └── YES → ❌ Advanced unit cannot charge (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ Already in fight (Skip, no log)
│   ├── Enemies exist within charge_max_distance hexes AND has non occupied adjacent hex(es) at 12 hexes or less ?
│   │   └── NO → ❌ No charge targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to charge_activation_pool
│
├── STEP : UNIT_ACTIVABLE_CHECK → Is charge_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → pick one unit in charge_activation_pool
│   │   │   ├── Build valid_targets_pool : Enemy units that are:
│   │   │   │   ├── within charge_max_distance hexes
│   │   │   │   └── having non occupied adjacent hex(es) at 12 hexes or less from the active unit
│   │   │   ├── valid_targets_pool NOT empty ?
│   │   │   │   ├── YES → AGENT TARGET SELECTION → Agent choisit une cible parmi valid_targets_pool
│   │   │   │   │   ├── Roll 2d6 to define charge_range value for selected target
│   │   │   │   │   ├── Build valid_charge_destinations_pool for selected target : All hexes that are:
│   │   │   │   │   │   ├── adjacent to the selected target
│   │   │   │   │   │   ├── at distance <= charge_range (using BFS pathfinding)
│   │   │   │   │   │   └── unoccupied
│   │   │   │   │   │   └── valid_charge_destinations_pool NOT empty ?
│   │   │   │   │   │       ├── YES → CHARGE PHASE ACTIONS AVAILABLE
│   │   │   │   │   │       │   ├── 🎯 VALID ACTIONS: [charge, wait]
│   │   │   │   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, attack] → end_activation (ERROR, 0, PASS, CHARGE, 1, 1)
│   │   │   │   │   │       │   └── AGENT ACTION SELECTION → Choose charge?
│   │   │   │   │   │       │       ├── YES → ✅ VALID → Execute charge
│   │   │   │   │   │       │       │   ├── Select destination hex from valid_charge_destinations_pool
│   │   │   │   │   │       │       │   ├── Move unit to destination
│   │   │   │   │   │       │       │   └── end_activation (ACTION, 1, CHARGE, CHARGE, 1, 1)
│   │   │   │   │   │       │       └── NO → Agent chooses: wait?
│   │   │   │   │   │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │   │   │   │       │           │   └── end_activation (WAIT, 1, PASS, CHARGE, 1, 1)
│   │   │   │   │   │       │           └── NO → Agent chooses invalid action (move/shoot/attack)?
│   │   │   │   │   │       │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, CHARGE, 1, 1)
│   │   │   │   │   │       └── NO → end_activation (NO, 0, PASS, CHARGE, 1, 1)
│   │   │   │   │   └── Discard charge_range roll (whether used or not)
│   │   │   │   └── NO → end_activation (NO, 0, PASS, CHARGE, 1, 1)
│   │   │
│   │   └── NO → Human player → STEP : UNIT_ACTIVATION → player activate one unit by left clicking on it
│   │       ├── If any, cancel the Highlight of the hexes in valid_charge_destinations_pool
│   │       ├── Player activate one unit by left clicking on it
│   │       ├── Build valid_targets_pool : Enemy units that are:
│   │       │   ├── within charge_max_distance hexes
│   │       │   └── having non occupied adjacent hex(es) at 12 hexes or less from the active unit
│   │       ├── valid_targets_pool NOT empty ?
│   │       │   ├── YES → STEP : PLAYER_TARGET_SELECTION → Player choisit une cible parmi valid_targets_pool by left clicking on it
│   │       │   │   ├── Roll 2d6 to define charge_range value for selected target
│   │       │   │   ├── Build valid_charge_destinations_pool for selected target : All hexes that are:
│   │       │   │   │   ├── adjacent to the selected target
│   │       │   │   │   ├── at distance <= charge_range (using BFS pathfinding)
│   │       │   │   │   └── unoccupied
│   │       │   │   │   └── valid_charge_destinations_pool not empty ?
│   │       │   │   │       ├── YES → STEP : PLAYER_ACTION_SELECTION
│   │       │   │   │       │   ├── Highlight the valid_charge_destinations_pool hexes by making them orange
│   │       │   │   │       │   └── Player select the action to execute
│   │       │   │   │       │       ├── Left click on a hex in valid_charge_destinations_pool → Move the icon of the unit to the selected hex
│   │       │   │   │       │       │   ├── end_activation (ACTION, 1, CHARGE, CHARGE, 1, 1)
│   │       │   │   │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │   │   │       │       ├── Left click on the active_unit → Charge postponed
│   │       │   │   │       │       │   └── GO TO STEP : STEP : UNIT_ACTIVABLE_CHECK
│   │       │   │   │       │       ├── Right click on the active_unit → Charge cancelled
│   │       │   │   │       │       │   ├── end_activation (NO, 0, PASS, CHARGE, 1, 1)
│   │       │   │   │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │   │   │       │       ├── Left click on another unit in activation pool → Charge postponed
│   │       │   │   │       │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │   │   │       │       └── Left OR Right click anywhere else on the board → Cancel charge hex selection
│   │       │   │   │       │           └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │       │   │   │       └── NO → end_activation (NO, 0, PASS, CHARGE, 1, 1)
│   │       │   │   └── Discard charge_range roll (whether used or not)
│   │       │   └── NO → end_activation (NO, 0, PASS, CHARGE, 1, 1)
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
│   │   │   │       │   ├── 🎯 VALID ACTIONS: [fight]
│   │   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│   │   │   │       │   └── AGENT ACTION SELECTION → Choose fight?
│   │   │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│   │   │   │       │       │   ├── ATTACK_LEFT -= 1
│   │   │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │   │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │   │   │       │       │   └── selected_target survives → Continue
│   │   │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │   │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│   │   │   │       └── NO → ATTACK_LEFT = CC_NB ?
│   │   │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│   │   │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (NO, 1, PASS, FIGHT, 1, 1)
│   │   │   ├── Return: TOTAL_ACTION log
│   │   │   └── end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
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
│   │   │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│   │       │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (NO, 1, PASS, FIGHT, 1, 1)
│   │       ├── Return: TOTAL_ACTION log
│   │       └── end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
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
│   │   │   │   │       │   ├── 🎯 VALID ACTIONS: [fight]
│   │   │   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│   │   │   │   │       │   └── AGENT ACTION SELECTION → Choose fight?
│   │   │   │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│   │   │   │   │       │       │   ├── ATTACK_LEFT -= 1
│   │   │   │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │   │   │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │   │   │   │       │       │   └── selected_target survives → Continue
│   │   │   │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │   │   │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│   │   │   │   │       └── NO → ATTACK_LEFT = CC_NB ?
│   │   │   │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│   │   │   │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (NO, 1, PASS, FIGHT, 1, 1)
│   │   │   │   ├── Return: TOTAL_ACTION log
│   │   │   │   ├── end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
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
│   │   │       │       └── NO → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│   │   │       ├── End of Fight → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
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
│   │       │   │       │   ├── 🎯 VALID ACTIONS: [fight]
│   │       │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│   │       │   │       │   └── AGENT ACTION SELECTION → Choose fight?
│   │       │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│   │       │   │       │       │   ├── ATTACK_LEFT -= 1
│   │       │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│   │       │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│   │       │   │       │       │   └── selected_target survives → Continue
│   │       │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│   │       │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│   │       │   │       └── NO → ATTACK_LEFT = CC_NB ?
│   │       │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│   │       │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (NO, 1, PASS, FIGHT, 1, 1)
│   │       │   ├── Return: TOTAL_ACTION log
│   │       │   ├── end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
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
│   │           │       └── NO → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│   │           ├── End of Fight → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
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
│           │   │       │   ├── 🎯 VALID ACTIONS: [fight]
│           │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│           │   │       │   └── AGENT ACTION SELECTION → Choose fight?
│           │   │       │       ├── YES → ✅ VALID → Execute attack_sequence(CC)
│           │   │       │       │   ├── ATTACK_LEFT -= 1
│           │   │       │       │   ├── Concatenate Return to TOTAL_ACTION log
│           │   │       │       │   ├── selected_target dies → Remove from valid_target_pool, continue
│           │   │       │       │   └── selected_target survives → Continue
│           │   │       │       └── NO → Agent chooses invalid action (move/shoot/charge/wait)?
│           │   │       │           └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│           │   │       └── NO → ATTACK_LEFT = CC_NB ?
│           │   │           ├── NO → Fought the last target available in valid_target_pool → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│           │   │           └── YES → no target available in valid_target_pool at activation → no attack → end_activation (NO, 1, PASS, FIGHT, 1, 1)
│           │   ├── Return: TOTAL_ACTION log
│           │   ├── end_activation (ACTION, 1, FIGHT, FIGHT, 1)
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
│               │       └── NO → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│               └── End of Fight → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
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
 
 // REF: Line 20 "Choose fight?"
 // REF: Line 21 "YES → ✅ VALID → Execute CC_NB attacks"
 if (hasAdjacentEnemies(selectedUnit)) {    // MATCHES: Current script helper functions
   executeAIAttackSequence(selectedUnit)
   // REF: Line 25 "Result: +1 step, Attack sequence logged, Mark as units_fought"
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
   // REF: Line 67 "NO → Result: +1 step, Fight sequence logged, Mark as units_fought"
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
     // REF: Line 60 "NO → Result: +1 step, fight sequence logged, Mark as units_fought"
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
 // REF: Line 60,62,67 "Result: +1 step, [action] logged, Mark as units_fought"
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
   // REF: Line 158 "Result: +1 step → Attack sequence logged → Mark as units_fought"
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
- If ALL adjacent enemies are marked as `units_fought` → Unit can delay its attack safely
- **Why**: No risk of enemy retaliation this phase → Strategic flexibility available

**Activation and target Priority Order:**
1. **Priority 1**: Units with high melee damage output AND likely to die this phase
2. **Priority 2**: Units more likely to die (regardless of damage output)  
3. **Priority 3**: Units with high melee damage output (regardless of vulnerability) AND low chances of being destroyed this phase

**Priority Assessment Logic:**
- **"Likely to die"**: Enemy HP_CUR ≤ Expected damage from this unit's attacks
- **"High melee damage"**: Enemy CC_STR and CC_NB pose significant threat
- **"Safe targets"**: Enemies already marked as `units_fought` (cannot retaliate)

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

**units_advanced** (Shooting Phase) - ⚠️ ADVANCE_IMPLEMENTATION_PLAN.md:
- **Purpose**: Track units that advanced during shooting phase
- **Reset timing**: Start of movement phase
- **Usage**: Prevents charge eligibility (advanced units cannot charge)
- **Note**: Only marked if unit actually moved (not if stayed in place)

**units_fought** (Fight Phase):
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
