# AI_TURN.md Compliant Architecture - Implementation Plan

## CORE AI CODING RULES
- No implicit recovery: fail immediately on missing/invalid data.
- No temporary/hacky solutions: always implement clear, minimal solutions.
- No hidden/implicit values: all tunable parameters must be in configuration/domain objects.
- No silent defaults: missing values must raise an error.
- Prefer simple and efficient designs: avoid unnecessary abstractions.
- Respect AI_TURN.md and implementation rules: check every function/module against AI_TURN.md; stop if behavior is unclear.

## EXECUTIVE SUMMARY
- Modular W40K game engine.
- Single source of truth (`game_state`), pure delegation to specialized modules.
- Compliance with AI_TURN.md and CORE AI CODING RULES.

## AUTOMATED AI RULE CHECKS
- Script: scripts/check_ai_rules.py
- Responsibility: detect coding rule violations.
- Behavior: prints file/line for each violation and exits non-zero on errors.

Usage:
    Manual run:
        python scripts/check_ai_rules.py

    Git pre-commit hook:
        #!/usr/bin/env bash
        python scripts/check_ai_rules.py || exit 1
        chmod +x .git/hooks/pre-commit

    CI pipeline:
        Run the script and block merges on non-zero exit.

## DATA AND CONFIGURATION VALIDATION
- Module: shared/data_validation.py
- Helpers:
    require_present(value, name) → raises if None
    require_key(mapping, key) → raises if key missing

Examples:
    from shared.data_validation import require_key, require_present

    learning_rate = require_key(training_config, "learning_rate")
    agent_name = require_present(raw_agent_name, "agent_name")

Rules:
- All required config keys must use require_key.
- All required values must use require_present at the first entry point.

---

## 📋 NAVIGATION

- [Architecture Compliance](#architecture-compliance)
- [Code Organization](#code-organization)
  - [w40k_core.py](#w40k_corepy---core-engine)
  - [game_state.py](#game_statepy---state-management)
  - [game_utils.py](#game_utilspy---pure-utilities)
  - [observation_builder.py](#observation_builderpy---observation-construction)
  - [reward_calculator.py](#reward_calculatorpy---reward-computation)
  - [action_decoder.py](#action_decoderpy---action-masking--decoding)
  - [combat_utils.py](#combat_utilspy---combat-calculations)
  - [weapons/](#weapons---weapon-system)
  - [pve_controller.py](#pve_controllerpy---pve-ai-opponent)
  - [phase_handlers/](#phase_handlers---phase-specific-logic)
- [Rule System and Logging Patterns](#rule-system-and-logging-patterns)
- [How Everything Works Together](#how-everything-works-together)
  - [Complete Request Flow](#complete-request-flow-agentstepaction)
  - [Episode Lifecycle](#complete-episode-lifecycle)
  - [Data Flow](#data-flow-game_state-through-modules)
  - [Phase Transitions](#phase-transition-flow)
  - [Integration Points](#integration-points)
- [Performance Optimizations](#performance-optimizations)
  - [Move preview masque monde & payload API](#move-preview-masque-monde--payload-api)
  - [Rendu plateau Pixi (highlights / redraw partiel)](#rendu-plateau-pixi-highlights--redraw-partiel)
- [Success Metrics](#success-metrics)
- [Related Documentation](#related-documentation)
- [Summary](#summary)

---

## ARCHITECTURE COMPLIANCE

### Single Source of Truth

The `game_state` dictionary exists only in `W40KEngine` (in `w40k_core.py`). All other modules receive it as a parameter and never copy or cache state.

### Units cache & HP_CUR (single source of truth)

**`game_state["units_cache"]`** is the single source of truth for **position** (`col`, `row`) and **HP_CUR** of **living** units. **Dead = absent from `units_cache`**. **(Phase 2)** HP_CUR is stored **only** in `units_cache` during gameplay; do **not** read or write `unit["HP_CUR"]` for current HP.

- **Build** : `build_units_cache(game_state)` is called **only at reset** (after units are initialised). Not at phase start.
- **units_cache always exists** : After reset, `units_cache` is always present. Use `require_key(game_state, "units_cache")` where the cache is required; no fallback.
- **HP_CUR single write path** : During gameplay, **only** `update_units_cache_hp(game_state, unit_id, new_hp_cur)` writes HP_CUR. It updates **only** `units_cache` (not `unit["HP_CUR"]`). Handlers must **not** assign `unit["HP_CUR"]` directly; they compute `new_hp` and call `update_units_cache_hp`.
- **HP_CUR reads** : Use `get_hp_from_cache(unit_id, game_state)` (from `engine.phase_handlers.shared_utils`) for current HP. Returns `None` if the unit is not in cache (dead or missing).
- **Death** : When a unit dies (shooting or fight), `update_units_cache_hp(..., 0)` is called. It removes the entry from `units_cache` (single source of truth).
- **Aliveness** : Use `is_unit_alive(unit_id, game_state)` (present in cache **and** `HP_CUR > 0`). Absence from cache means dead.
- **Position updates** : After any move (MOVE, ADVANCE, CHARGE, FLED), call `update_units_cache_position(game_state, unit_id, col, row)`.
- **Snapshot** : `game_state["units_cache_prev"]` is a copy of `units_cache` at the **start** of each `step()`, used for movement-direction features (observation).

Les détails d’implémentation (build, update, lecture HP, mort) sont décrits dans la section « Units cache & HP_CUR » ci-dessus et dans AI_TURN.md.

### Sequential Unit Activation

One unit processes per gym step. Phase-specific activation pools (`move_activation_pool`, `shoot_activation_pool`) maintain the queue. The engine processes the first unit in the current pool.

### Built-in Step Counting

Episode steps counted in `w40k_core.py` only. The `step()` method increments `game_state["episode_steps"]` at the start of each step.

### Phase Completion by Eligibility

Phases advance when activation pools are empty. No arbitrary step counting. The engine checks pool status after each action.

### UPPERCASE Field Validation

All unit stats use UPPERCASE naming (`HP_CUR`, `ARMOR_SAVE`, `RNG_ATK`, `CC_STR`, etc.). Module `game_state.py` validates fields on unit initialization via `validate_uppercase_fields()`.

### Zero Wrapper Patterns

`W40KEngine` directly implements `gym.Env`. No wrapper classes that might copy state.

### TypeScript → Python Parsing Pattern

**Single Source of Truth for Game Data**: Units and weapons are declared **ONCE** in TypeScript files. Python parses these files at runtime - no duplicate Python declarations needed.

**Architecture**:
- **TypeScript files** (single source of truth):
  - Units: `frontend/src/roster/{faction}/units/*.ts`
  - Weapons: `frontend/src/roster/{faction}/armory.ts`
- **Python parsers** (runtime parsing):
  - Units: `ai/unit_registry.py` parses TypeScript unit files
  - Weapons: `engine/weapons/parser.py` parses TypeScript armory files

**Benefits**:
- ✅ No sync issues between TypeScript and Python
- ✅ Fail-fast validation (errors raised immediately on load)
- ✅ No silent defaults (missing weapons/units = error)
- ✅ DRY principle (Don't Repeat Yourself)
- ✅ Type safety (TypeScript ensures correctness)

**Validation**: All referenced weapons must exist in armory files. Missing weapons raise `KeyError` on load. All unit weapon references validated during initialization.

---

## CODE ORGANIZATION

### File Structure

```
engine/
├── w40k_core.py              # Core engine (gym.Env)
├── game_state.py             # State initialization & validation
├── game_utils.py             # Pure utility functions
├── observation_builder.py   # Observation construction
├── reward_calculator.py     # Reward computation
├── action_decoder.py        # Action masking & decoding
├── combat_utils.py          # Combat calculations
├── pve_controller.py        # PvE AI opponent
├── weapons/                  # Weapon system (TypeScript parsing)
│   ├── __init__.py          # Public API
│   ├── parser.py            # Parse TypeScript armory files
│   └── rules.py             # Weapon rules system
└── phase_handlers/          # Phase-specific logic
    ├── deployment_handlers.py  # Deployment phase (active placement)
    ├── movement_handlers.py
    ├── shooting_handlers.py
    ├── charge_handlers.py
    └── fight_handlers.py
```

### w40k_core.py - Core Engine

**Class:** `W40KEngine(gym.Env)`

**Key Methods:**
- `__init__()` - Initialize engine, create game_state, instantiate modules
- `reset()` - Start new episode, return initial observation
- `step(action)` - Execute action, return (obs, reward, done, truncated, info)
- `execute_semantic_action()` - Process semantic actions from API
- `execute_ai_turn()` - Handle PvE AI player turns
- `validate_compliance()` - Check AI_TURN.md compliance

**Phase Processing:**
- `_process_deployment_phase()` - Delegate to deployment_handlers (when deployment_type == "active")
- `_process_movement_phase()` - Delegate to movement_handlers
- `_process_shooting_phase()` - Delegate to shooting_handlers
- `_process_charge_phase()` - Delegate to charge_handlers
- `_process_fight_phase()` - Delegate to fight_handlers

**Phase Initialization:**
- `_deployment_phase_init()` - Build deployment pools, deployable units (when active)
- `_movement_phase_init()` - Build move_activation_pool
- `_shooting_phase_init()` - Build shoot_activation_pool
- `_charge_phase_init()` - Build charge_activation_pool
- `_fight_phase_init()` - Build fight activation pools

**Game Flow:**
- When scenario has `deployment_type == "active"`: match starts in `phase = "deployment"`; after all units placed, transition to command/move.
- `_advance_to_fight_phase()` - Transition move→shoot→charge→fight
- `_advance_to_next_player()` - Switch players, reset tracking
- `_tracking_cleanup()` - Clear phase tracking sets
- `_check_game_over()` - Check win conditions
- `_determine_winner()` - Determine winner or draw

**Delegation Methods:**
- `get_action_mask()` → `action_decoder.get_action_mask()`
- `_build_observation()` → `obs_builder.build_observation()`
- `_calculate_reward()` → `reward_calculator.calculate_reward()`
- `_convert_gym_action()` → `action_decoder.convert_gym_action()`
- `_initialize_units()` → `state_manager.initialize_units()`

**Responsibilities:**
- Owns the single game_state dictionary
- Implements gym.Env interface (reset/step)
- Orchestrates phase flow
- Delegates to specialized modules
- Manages episode lifecycle

---

### game_state.py - State Management

**Class:** `GameStateManager`

**Key Methods:**
- `__init__(config, unit_registry)` - Initialize manager
- `initialize_units(game_state)` - Create units from config
- `create_unit(config)` - Build single unit with UPPERCASE fields
- `validate_uppercase_fields(unit)` - Enforce field naming
- `load_units_from_scenario(scenario_file, unit_registry)` - Load from JSON
- `get_unit_by_id(unit_id, game_state)` - Lookup unit
- `check_game_over(game_state)` - Check elimination/turn limit
- `determine_winner(game_state)` - Calculate winner (-1 for draw)

**Responsibilities:**
- Initialize game state structure
- Create and validate units
- Enforce UPPERCASE field naming
- Load units from scenario files
- Check game-over conditions

---

### game_utils.py - Pure Utilities

**Functions:**
- `get_unit_by_id(unit_id, game_state)` - Lookup unit by ID

**Responsibilities:**
- Pure utility functions with no side effects
- No dependencies on other modules
- Simple lookups only

---

### observation_builder.py - Observation Construction

**Class:** `ObservationBuilder`

**Key Methods:**
- `__init__(config)` - Initialize with perception radius
- `build_observation(game_state)` - Build 150-float egocentric observation
- `_get_active_unit_for_observation(game_state)` - Get unit to observe from
- `_encode_directional_terrain(obs, active_unit, game_state, base_idx)` - Terrain encoding
- `_encode_allied_units(obs, active_unit, game_state, base_idx)` - Allied units (relative coords)
- `_encode_enemy_units(obs, active_unit, game_state, base_idx)` - Enemy units (relative coords)
- `_encode_valid_targets(obs, active_unit, game_state, base_idx)` - Target selection data

**Tactical Feature Calculations:**
- `_calculate_combat_mix_score(unit)` - Ranged vs melee preference (0.1-0.9)
- `_calculate_expected_damage()` - Expected damage calculation
- `_calculate_favorite_target(unit)` - Preferred target type encoding
- `_calculate_movement_direction(unit)` - Recent movement vector
- `_calculate_kill_probability(shooter, target)` - Chance to kill target
- `_calculate_danger_probability(defender, attacker)` - Threat assessment
- `_calculate_army_weighted_threat(target, valid_targets)` - Army-wide threat priority
- `_calculate_target_type_match(active_unit, target)` - Target type match score

**Utility Methods:**
- `_check_los_cached(shooter, target, game_state)` - Line of sight with cache
- `_can_melee_units_charge_target(target, game_state)` - Charge possibility check
- `_find_nearest_in_direction(unit, dx, dy, game_state)` - Directional search
- `_encode_defensive_type(unit)` - Defensive capability encoding

**Responsibilities:**
- Construct 150-float egocentric observations
- Encode relative positions (perception radius R=25)
- Calculate tactical features
- Use LoS cache when available
- Provide fog-of-war observations

---

### reward_calculator.py - Reward Computation

**Class:** `RewardCalculator`

**Key Methods:**
- `__init__(config, rewards_config, unit_registry)` - Initialize with reward config
- `calculate_reward(success, result, game_state)` - Main reward calculation
- `calculate_reward_from_config(acting_unit, action, success, game_state)` - Config-based rewards
- `_get_unit_reward_config(unit)` - Get unit-specific reward values
- `_get_situational_reward(game_state)` - Win/loss/draw rewards
- `_get_system_penalties()` - Load penalty values from config
- `_build_tactical_context(unit, result, game_state)` - Contextual data for rewards

**Tactical Assessments (mirrors observation_builder):**
- `_calculate_combat_mix_score(unit)` - Combat preference score
- `_calculate_expected_damage()` - Expected damage calculations
- `_calculate_favorite_target(unit)` - Target preference
- `_calculate_kill_probability(shooter, target)` - Kill chance
- `_calculate_danger_probability(defender, attacker)` - Threat level
- `_calculate_army_weighted_threat(target, valid_targets)` - Army threat
- `_calculate_target_type_match(active_unit, target)` - Target matching

**Reward Mapper Integration:**
- `_get_reward_mapper()` - Access shared reward_mapper
- `_enrich_unit_for_reward_mapper(unit)` - Add tactical features to unit
- `_get_reward_mapper_unit_rewards(unit)` - Get unit-specific rewards
- `_get_reward_config_key_for_unit(unit)` - Map unit to reward config key

**Responsibilities:**
- Calculate rewards using rewards_config.json
- Track reward breakdowns for metrics
- Apply system penalties (invalid actions, forbidden actions)
- Calculate situational rewards (win/loss/draw)
- Integrate with reward_mapper for unit-specific rewards

---

### action_decoder.py - Action Masking & Decoding

**Class:** `ActionDecoder`

**Key Methods:**
- `__init__(config)` - Initialize decoder
- `get_action_mask(game_state)` - Return boolean mask (12 actions)
- `convert_gym_action(action, game_state)` - Convert int→semantic action
- `_get_valid_actions_for_phase(phase)` - Get valid action IDs for phase
- `_get_eligible_units_for_current_phase(game_state)` - Get units from activation pool
- `get_all_valid_targets(unit, game_state)` - Get all possible targets
- `can_melee_units_charge_target(target, game_state)` - Check charge possibility

**Action Space (12 actions):**
- 0-3: Movement (N/S/E/W directions)
- 4-8: Shoot (target slots 0-4)
- 9: Charge
- 10: Fight
- 11: Wait

**Masking Logic:**
- Movement phase: Actions 0-3, 11 valid
- Shooting phase: Actions 4-8 (dynamically based on available targets), 11 valid
- Charge phase: Actions 9, 11 valid
- Fight phase: Action 10 valid only (NO wait in fight)

**Responsibilities:**
- Compute action masks (prevent invalid actions)
- Convert gym integer actions to semantic actions
- Validate actions against phase and available targets
- Handle target slot mapping for shooting
- Enforce phase-specific action restrictions

---

### combat_utils.py - Combat Calculations

**Pure Functions:**
- `normalize_coordinate(coord)` - Normalize single coordinate to int (handles int/float/string)
- `normalize_coordinates(col, row)` - Normalize both coordinates to int tuple
- `get_unit_coordinates(unit)` - Extract and normalize unit coordinates from unit dict
- `set_unit_coordinates(unit, col, row)` - Set and normalize unit coordinates in unit dict
- `calculate_hex_distance(col1, row1, col2, row2)` - Cube coordinate hex distance
- `get_hex_line(start_col, start_row, end_col, end_row)` - Hex line for LoS
- `compute_unit_los(game_state, shooter, target) → {can_see, fully_visible, cover, …}` - **single source of truth**, obscuring-aware (dense walls + obscuring terrain, rule 13.10); cached per `(shooter,target)` pair
- `has_line_of_sight(shooter, target, game_state)` - thin wrapper over `compute_unit_los().can_see`
- `check_los_cached(shooter, target, game_state)` - LoS with cache lookup (reads `unit["los_cache"]`, built obscuring-aware)
- `calculate_wound_target(strength, toughness)` - W40K wound chart
- `has_valid_shooting_targets(unit, game_state)` - Check if unit can shoot
- `is_valid_shooting_target(shooter, target, game_state)` - Validate specific target

**Responsibilities:**
- Coordinate normalization (CRITICAL: ensures all hex coordinates are int for consistent comparison)
- Pure calculation functions for combat
- Hex distance and line-of-sight calculations
- W40K wound table implementation
- Delegation to phase handlers for validation
- LoS cache integration

**Coordinate Normalization:**
- **CRITICAL**: All hex coordinates (`col`, `row`) must be normalized to `int` for consistent comparison, distance calculations, and tuple operations
- **Always use**: `get_unit_coordinates(unit)` to extract coordinates, `set_unit_coordinates(unit, col, row)` to assign coordinates
- **Never access**: `unit["col"]` or `unit["row"]` directly - always use the utility functions
- **Normalization handles**: int, float, and numeric string inputs, raising `ValueError` on invalid types

---

### weapons/ - Weapon System

**Module:** `engine/weapons/`

**Purpose**: Parse TypeScript armory files (single source of truth) and provide weapon data to the engine.

**Key Classes/Functions:**
- `ArmoryParser` - Parse TypeScript armory files at runtime
- `get_armory_parser()` - Get parser singleton
- `get_weapon(faction, code_name)` - Get single weapon by code
- `get_weapons(faction, code_names)` - Get multiple weapons (raises on missing)
- `WeaponRulesRegistry` - Manage weapon rules (RAPID_FIRE, MELTA, etc.)
- `validate_weapon_rules_field()` - Validate WEAPON_RULES on load

**Architecture Pattern:**
- **Single source of truth**: Weapons declared once in TypeScript (`frontend/src/roster/{faction}/armory.ts`)
- **Runtime parsing**: Python parses TypeScript files dynamically (no duplicate Python declarations)
- **Fail-fast validation**: Missing weapons raise `KeyError` immediately
- **No silent defaults**: Invalid weapon references fail on load

**Usage:**
```python
from engine.weapons import get_weapons

# Load weapons for a unit (called during unit initialization)
rng_weapons = get_weapons("SpaceMarine", ["bolt_rifle", "bolt_pistol"])
# Raises KeyError if any weapon code is missing from armory
```

**Integration Points:**
- `ai/unit_registry.py` - Uses `get_weapons()` when parsing unit definitions
- `main.py` - Loads unit definitions which reference weapons
- `game_state.py` - Units include `RNG_WEAPONS` and `CC_WEAPONS` arrays

**Responsibilities:**
- Parse TypeScript armory files
- Validate weapon definitions (required fields, valid rules)
- Provide weapon data to unit initialization
- Enforce single source of truth pattern (no Python duplicates)

---

### pve_controller.py - PvE AI Opponent

**Class:** `PvEController`

**Key Methods:**
- `__init__(config, unit_registry)` - Initialize controller
- `load_ai_model_for_pve(game_state, engine)` - Load trained model for Player 2
- `make_ai_decision(game_state)` - Get AI action via model prediction
- `ai_select_unit(eligible_units, action_type)` - Select first eligible unit
- `_ai_select_movement_destination(unit_id, game_state)` - Choose movement target
- `_ai_select_shooting_target()` - NotImplementedError (uses handler flow)
- `_ai_select_charge_target()` - NotImplementedError (placeholder)
- `_ai_select_combat_target()` - NotImplementedError (placeholder)

**Responsibilities:**
- Load trained AI models for PvE mode
- Make AI decisions for Player 2
- Use MaskablePPO for predictions
- Integrate with engine's action flow
- Provide fallback behaviors for AI

---

### phase_handlers/ - Phase-Specific Logic

Each handler module implements complete phase logic:

**movement_handlers.py:**
- Movement eligibility
- Valid destination calculation
- Movement execution
- Flee detection
- **Preview move — masque monde** : `_sync_move_preview_mask_loops(game_state, footprint_zone)` remplit `game_state["move_preview_footprint_mask_loops"]` via `engine.hex_union_boundary_polygon.compute_move_preview_mask_loops_world`, avec cache LRU module `_mask_loop_cache` (clé `(frozenset(footprint_zone), hex_radius, margin)`). Évite d’exposer `move_preview_footprint_zone` en JSON quand les boucles sont présentes (voir `_game_state_for_json` dans `services/api_server.py`).

**shooting_handlers.py:**
- Shooting eligibility
- Target pool building
- Hit/wound/save rolls
- Damage application
- LoS validation
- Advance action (when no targets available)
  - Human players: `allow_advance: true` signal when unit has no valid targets
  - Advance range calculation (1D6 roll from config)
  - Advance destination validation (BFS pathfinding, no walls, no enemy-adjacent)
  - Marking units in `units_advanced` set (blocks charge phase)
  - Assault weapon rule exception (allows shooting after advance)

**charge_handlers.py:**
- Charge eligibility
- Charge range calculation
- Charge execution

**fight_handlers.py:**
- Fight eligibility
- Melee target selection
- Attack resolution
- Fight subphase management

**deployment_handlers.py** (phase déploiement actif, implémentée):
- Quand `deployment_type == "active"` dans le scénario, le match démarre en `phase = "deployment"`.
- **État** : `game_state["deployment_state"]` contient `current_deployer`, `deployable_units_by_player`, `deployed_units`, `deployment_pools_by_player`, `deployment_complete`. Unités non placées : `col = -1`, `row = -1`.
- **Action** : `deploy_unit { unitId, col, row }` — validation stricte (hex dans zone, non mur, non occupé), puis mise à jour position et ajout à `deployed_units`.
- **Ordre** : déploiement alterné P1 puis P2 (ou un joueur seul jusqu’à épuisement si l’autre n’a plus d’unités à déployer). Fin de phase quand toutes les unités sont placées → transition vers phase suivante (command ou move).
- **Sources** : `config/board_config.json`, `config/deployment/hammer.json`, scénario (units, deployment_zone, deployment_type). Action mask strict pour le RL ; pas de fallback ni placement automatique.

**Handler Pattern:**
- Receive game_state as parameter
- Return results without storing state
- Pure delegation from engine
- Implement AI_TURN.md rules exactly

---

## Rule System and Logging Patterns

This section documents how unit rules are declared, resolved, selected at runtime, and logged consistently across backend/frontend/analyzer.

### 1) Rule Data Model

Two complementary layers are used:

- **Global rule registry**: `config/unit_rules.json`
  - Canonical key/ID: `id`
  - User-facing name (optional): `name`
  - Technical indirection (optional): `alias`
  - Human description: `description`
- **Unit-attached rules**: `UNIT_RULES` on each unit definition
  - `ruleId`: source rule attached to the unit
  - `displayName`: source label shown in UI/logs for direct rules
  - `grants_rule_ids` (optional): sub-rules granted by the source rule
  - `usage` (optional): `and`, `or`, `unique`, `always`
  - `choice_timing` (optional): prompt timing for player choice

Design intent:
- `unit_rules.json` is the global dictionary for descriptions and alias chains.
- `UNIT_RULES` is the unit runtime contract (what this unit has, and how it is activated).

### 1.b) Weapon Rule Data Model

Weapon rules are defined and validated through a dedicated registry:

- **Global weapon rule registry**: `config/weapon_rules.json`
  - Canonical key: rule ID (for example `RAPID_FIRE`, `HEAVY`, `DEVASTATING_WOUNDS`)
  - `name`: display name
  - `description`: human description
  - `has_parameter`: whether the rule requires a numeric parameter (`RAPID_FIRE:1`, `SUSTAINED_HITS:2`, etc.)
- **Weapon-attached rules**: `WEAPON_RULES` on each armory weapon entry
  - Static form: `"HEAVY"`, `"PISTOL"`, `"HAZARDOUS"`
  - Parameterized form: `"RAPID_FIRE:1"`, `"SUSTAINED_HITS:1"`

Runtime pipeline:

- `engine/weapons/parser.py` parses TypeScript armories and loads rule strings.
- `engine/weapons/rules.py` validates every `WEAPON_RULES` entry against `weapon_rules.json` (fail-fast).
- Invalid/missing/parameter-mismatch rules raise immediately (no silent fallback).

This guarantees that rule IDs used in gameplay, frontend rendering, replay parsing, and analyzer checks all come from one canonical registry.

### 2) Resolution Pattern (Direct + Alias + Granted Rules)

Central helpers are implemented in `engine/phase_handlers/shared_utils.py`:

- `_resolve_effect_rule_id_to_technical(rule_id)`:
  - Resolves alias chains to the technical effect rule ID.
  - Fails fast on unknown ID, invalid alias, or alias cycles.
- `_resolve_unit_rule_entry_effect_rule_ids(rule_entry)`:
  - Computes active effect IDs for one `UNIT_RULES` entry.
  - For `and/always`: all granted IDs are active.
  - For `or/unique`: only `_selected_granted_rule_id` is active.
- `unit_has_rule_effect(unit, rule_id)`:
  - Public check used by handlers.
- `get_source_unit_rule_id_for_effect(unit, effect_rule_id)`:
  - Maps a technical effect back to its source `UNIT_RULES.ruleId`.
- `get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)`:
  - Returns the display label to log.
  - For `or/unique`, returns the selected child rule display name (from `unit_rules.json` `name`) instead of the parent display name.

This ensures logs and behavior reflect the effective selected capability (for example, `Aggression Imperative` instead of the parent `Adrenalised Onslaught`).

### 3) Runtime Choice Flow (Rule prompts)

At runtime, rule choices are indexed and prompted via `choice_timing`:

- Index build: `rebuild_choice_timing_index(game_state)` in `shared_utils.py`
- Queue + prompt lifecycle: managed in `engine/w40k_core.py`
- Selection application:
  - `_apply_rule_choice_selection(...)` stores `_selected_granted_rule_id`
  - Active effects immediately reflect the selected rule via shared resolution helpers

AI choice paths:
- **Gym/training mode**: deterministic selection from policy action integer in `w40k_core.py`.
- **PvE mode**: value-based policy selection in `engine/pve_controller.py` (`select_rule_choice_with_policy`).

No heuristic fallback is used for rule selection.

### 4) Logging Surfaces and Contracts

#### A) Backend `action_logs` (runtime event bus to frontend)

Handlers append structured events into `game_state["action_logs"]`.
Example reactive move payload (from `shared_utils.py`):

```python
{
    "type": "reactive_move",
    "message": "Unit 15(1,6) REACTIVE MOVED [SKULKING HORRORS] from (2,2) to (1,6) [Roll: 5] - trigger: Unit 2->(1,10)",
    "unitId": 15,
    "player": 2,
    "ability_display_name": "SKULKING HORRORS",
    "fromCol": 2,
    "fromRow": 2,
    "toCol": 1,
    "toRow": 6,
    "range_roll": 5,
    "event_toCol": 1,
    "event_toRow": 10
}
```

Frontend (`useEngineAPI.ts` -> `useGameLog.ts`) dispatches/consumes these entries to render combat log events.

#### B) Combat log (frontend UI)

The combat log shows `action_logs[].message` (after light sanitization, e.g. reward token cleanup).
Rule tags like `[AGGRESSION IMPERATIVE]` are interactive and resolve descriptions from `unit_rules.json`.

Weapon rule tags are also interactive and resolved from `weapon_rules.json` (with unit-rule priority on collisions).

Reactive move example in combat log:

```text
Unit 15(1,6) REACTIVE MOVED [SKULKING HORRORS] from (2,2) to (1,6) [Roll: 5] - trigger: Unit 2->(1,10)
```

#### C) `step.log` (replay/analyzer canonical trace)

`ai/step_logger.py` formats replay lines with turn/player/phase envelope:

```text
[06:55:38] E11 T1 P2 MOVE : Unit 15(1,6) REACTIVE MOVED [SKULKING HORRORS] from (2,2) to (1,6) [Roll: 5] - trigger: Unit 2->(1,10) [R:+0.0] [SUCCESS]
```

Rule choice lines are also explicit:

```text
[HH:MM:SS] E# T# P# FIGHT : Unit 3(7,12) chose [ADRENALISED ONSLAUGHT] [SUCCESS]
```

#### C.1) Shooting/Weapon Rule Log Contract

For ranged attacks, logs are intentionally deterministic and stage-based:

- If **Hit fails**: only `Hit` is logged.
- If **Wound fails**: `Hit` + `Wound`.
- If **Save succeeds**: `Hit` + `Wound` + `Save` (no damage).
- If **Save fails**: `Hit` + `Wound` + `Save` + `Dmg:XHP`.
- If **DEVASTATING_WOUNDS** applies (critical wound): `Save [DEVASTATING WOUNDS]` + `Dmg:XHP`.

Canonical examples:

```text
Unit 15(9,6) SHOT [RAPID FIRE:1] Unit 18(11,6) with [Bolt Pistol] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP
Unit 2(23,10) SHOT Unit 7(12,2) with [Sternguard Bolt Rifle] - Hit 5(3+) - Wound 6(4+) - Save [DEVASTATING WOUNDS] - Dmg:2HP
Unit 2(23,10) SHOT Unit 7(12,2) with [Heavy Bolter] - Hit 4(3+->2+) [HEAVY] - Wound 5(3+) - Save 2(3+) - Dmg:2HP
```

HAZARDOUS contract:

- Every hazardous shot line carries: `[HAZARDOUS] Roll:<1..6>`.
- On roll `1`, a dedicated follow-up line is emitted:
  - Survived: `Unit X(c,r) SUFFERS 3 Mortal Wounds [HAZARDOUS]`
  - Dead: `Unit X(c,r) was DESTROYED [HAZARDOUS]`

This split keeps shot resolution and side-effect resolution parseable and robust for replay/analyzer.

#### D) Analyzer expectations (`ai/analyzer.py`)

Analyzer parses:
- reactive move occurrences (`REACTIVE MOVED`, trigger, roll),
- rule-choice selection lines (`chose [RULE]`),
- bracketed rule usage in combat actions (`[...]`).

It tracks rule-choice compliance:
- `correct`: used effect matches selected choice,
- `missing`: effect used without prior choice,
- `mismatch`: used effect differs from selected choice.

Weapon-rule-specific checks include:

- **RAPID FIRE coherence**:
  - marker/value consistency (`[RAPID FIRE:n]` on bonus shots must match weapon config),
  - bonus shot window consistency (marker only on bonus shots),
  - shot count cap (`rng_nb + rapid_fire_bonus`).
- **DEVASTATING WOUNDS coherence**:
  - only counted when `Save [DEVASTATING WOUNDS]` is present in the log,
  - `correct` requires wound roll `6` and no save roll (save skipped),
  - `incorrect` captures flagged non-critical or flagged critical-with-save cases.

### 5) Log Naming and Pattern Guidelines

When adding new rule-driven effects:

- Always include explicit rule label in message, in square brackets: `[RULE NAME]`.
- Keep event message deterministic and parseable (stable wording).
- For side-effect actions (reactive move, charge impact, rule choice), append structured entries to `action_logs` and flush to `step.log`.
- Prefer one canonical phrasing per action type to keep replay/analyzer parsing robust.
- For weapon rules in display/logs, use the canonical tags (`[RAPID FIRE:n]`, `[HEAVY]`, `[DEVASTATING WOUNDS]`, etc.).
- Keep internal identifiers unchanged (`RAPID_FIRE`, `DEVASTATING_WOUNDS`) and normalize only display/parsing text.

Recommended pattern:

```text
Unit <id>(<col>,<row>) <ACTION VERB> [<RULE NAME>] <details...>
```

This keeps UI tooltips, replay parsing, and analyzer checks aligned on the same textual contract.

---

**Reactive move (unit rule)** : la règle `reactive_move` est une règle d’unité (déplacement réactif après mouvement ennemi). Spécification complète (objectif, game_state, éligibilité, résolution, caches, erreurs, flux, tests, plan d’implémentation) : **[Unit_rules.md](Unit_rules.md)** section « 10) Specification : reactive_move ».

---

## HOW EVERYTHING WORKS TOGETHER

### Complete Request Flow: agent.step(action)

This traces one complete gym step from action input to observation output.

**1. Entry Point - step(action)**
```
W40KEngine.step(action: int)
│
├─ Check turn limit (training_config.max_turns_per_episode)
├─ Check game_over status
│
└─ CONVERT ACTION
   └─> action_decoder.convert_gym_action(action, game_state)
       │
       ├─ Get action mask to validate
       ├─ Get eligible units from activation pool
       ├─ Map integer to semantic action:
       │  • 0-3 → movement directions
       │  • 4-8 → shoot target slots
       │  • 9 → charge
       │  • 10 → fight
       │  • 11 → wait
       │
       └─ Return: {"action": "move", "unitId": "u1", "destCol": 5, "destRow": 3}
```

**2. Process Semantic Action**
```
_process_semantic_action(semantic_action)
│
├─ Read current_phase from game_state
│
└─ Route to phase processor:
   ├─ "move" → _process_movement_phase()
   ├─ "shoot" → _process_shooting_phase()
   ├─ "charge" → _process_charge_phase()
   └─ "fight" → _process_fight_phase()
```

**3. Phase Processing (Example: Movement)**
```
_process_movement_phase(action)
│
├─ Get unit from semantic_action["unitId"]
│
└─ DELEGATE TO HANDLER
   └─> movement_handlers.execute_action(game_state, unit, action, config)
       │
       ├─ Validate unit is in move_activation_pool
       ├─ Check destination is valid (not wall, not occupied)
       ├─ Check flee status (was adjacent to enemy)
       ├─ Update unit position in game_state["units"]
       ├─ Mark unit as moved (add to game_state["units_moved"])
       ├─ Remove unit from move_activation_pool
       │
       ├─ Check if pool is empty
       │  └─ If empty: return {"phase_complete": True}
       │
       └─ Return: (success=True, result={...})
```

**4. Phase Transition Detection**
```
Back in _process_movement_phase():
│
├─ Check result["phase_complete"]
│
└─ If phase complete:
   ├─ Set flag: _movement_phase_initialized = False
   ├─ Call: _shooting_phase_init()
   │  └─> shooting_handlers.shooting_phase_start(game_state)
   │      └─ Build shoot_activation_pool from eligible units
   │
   └─ Add to result: {"phase_transition": True, "next_phase": "shoot"}
```

**5. Increment Step Counter**
```
Back in step():
│
├─ If action was successful:
│  └─ game_state["episode_steps"] += 1
│
└─ Track compliance data (one unit per step)
```

**6. Build Observation**
```
obs_builder.build_observation(game_state)
│
├─ Get active unit (first in current activation pool)
│
├─ ENCODE FEATURES (150 floats):
│  │
│  ├─ Active unit stats (normalized):
│  │  • HP_CUR/HP_MAX ratio
│  │  • MOVE distance
│  │  • Combat capabilities
│  │
│  ├─ Directional terrain (8 directions):
│  │  • Distance to nearest wall
│  │  • Distance to edge
│  │
│  ├─ Allied units (3 nearest):
│  │  • Relative position (egocentric)
│  │  • HP status
│  │  • Combat stats
│  │
│  ├─ Enemy units (3 nearest):
│  │  • Relative position
│  │  • Threat assessment
│  │  • Kill probability
│  │
│  └─ Valid targets (5 slots):
│     • Target priority
│     • Expected damage
│     • Type match score
│
└─ Return: numpy array shape (150,)
```

**7. Calculate Reward**
```
reward_calculator.calculate_reward(success, result, game_state)
│
├─ Check for system penalties:
│  ├─ Invalid action → -1.0
│  ├─ Forbidden action → -0.5
│  └─ System response → 0.0
│
├─ Get acting unit from result
│
├─ Calculate base rewards (from rewards_config.json):
│  ├─ Movement rewards
│  ├─ Shooting rewards (damage dealt)
│  ├─ Elimination rewards
│  └─ Tactical bonuses
│
├─ Calculate situational rewards:
│  ├─ Moved to cover
│  ├─ Moved to optimal range
│  ├─ Gained LoS on priority target
│  └─ Safe from threats
│
└─ Return: float (total reward)
```

**8. Check Game Over**
```
_check_game_over()
│
├─ Check turn limit exceeded
│
├─ Count living units per player
│
└─ Return: True if ≤1 player has living units
```

**9. Return to Caller**
```
step() returns:
│
├─ observation: np.ndarray (150,)
├─ reward: float
├─ terminated: bool (game_over)
├─ truncated: bool (always False)
└─ info: dict
   ├─ "success": bool
   ├─ "winner": int|None
   ├─ "episode": dict (if terminated)
   └─ "action_logs": list
```

---

### Complete Episode Lifecycle

**Episode Start: reset()**
```
reset()
│
├─ Reset game_state fields:
│  ├─ current_player = 0
│  ├─ phase = "move"
│  ├─ turn = 1
│  ├─ episode_steps = 0
│  └─ Clear all tracking sets
│
├─ Reset all units:
│  ├─ HP_CUR = HP_MAX
│  ├─ SHOOT_LEFT = RNG_NB
│  ├─ ATTACK_LEFT = CC_NB
│  └─ Restore original positions
│
├─ Initialize movement phase:
│  └─> movement_handlers.movement_phase_start(game_state)
│      └─ Build initial move_activation_pool
│
├─ Build initial observation
│
└─ Return: (observation, info)
```

**Episode Loop: step() repeatedly**
```
Player 0 Turn:
│
├─ Movement Phase:
│  └─ Process all units in move_activation_pool
│     └─ Each unit = one step() call
│
├─ Shooting Phase:
│  └─ Process all units in shoot_activation_pool
│     └─ Each unit = one step() call
│
├─ Charge Phase: (placeholder)
│
└─ Fight Phase: (placeholder)

Phase complete → Switch to Player 1
│
Player 1 Turn:
│  (Same phase sequence)
│
Phase complete → Switch back to Player 0
Turn counter increments
│
Repeat until game_over = True
```

**Episode End: terminated=True**
```
When step() returns terminated=True:
│
├─ Calculate winner:
│  ├─ One player eliminated → winner
│  ├─ Turn limit + unequal units → winner
│  └─ Turn limit + equal units → draw (-1)
│
├─ Populate info["episode"]:
│  ├─ "r": total episode reward
│  ├─ "l": episode length
│  └─ "t": episode steps
│
└─ Training system calls reset() for next episode
```

---

### Data Flow: game_state Through Modules

**Single Source of Truth:**
```
W40KEngine.__init__():
│
└─ self.game_state = {
   "units": [...],
   "current_player": 0,
   "phase": "move",
   "move_activation_pool": [],
   "shoot_activation_pool": [],
   ...
}

All modules receive game_state as parameter:
│
├─> movement_handlers.execute_action(game_state, ...)
│   └─ Reads: units, current_player, move_activation_pool
│   └─ Writes: units[i]["col"], units[i]["row"], units_moved
│
├─> observation_builder.build_observation(game_state)
│   └─ Reads: units, current_player, phase, los_cache
│   └─ Writes: nothing (pure read)
│
├─> reward_calculator.calculate_reward(..., game_state)
│   └─ Reads: units, action_logs, game_over, winner
│   └─ Writes: last_reward_breakdown (for metrics)
│
└─> action_decoder.get_action_mask(game_state)
    └─ Reads: phase, move_activation_pool, shoot_activation_pool
    └─ Writes: nothing (pure read)

NO MODULE COPIES game_state
NO MODULE STORES game_state INTERNALLY
```

---

### Phase Transition Flow

**Movement → Shooting:**
```
movement_handlers.execute_action():
│
├─ Process unit movement
├─ Remove unit from move_activation_pool
│
└─ Check pool empty:
   └─ If empty:
      └─ Return: {"phase_complete": True}

W40KEngine._process_movement_phase():
│
├─ Receive: result["phase_complete"] = True
│
├─ Call: _shooting_phase_init()
│  └─> shooting_handlers.shooting_phase_start(game_state)
│      │
│      ├─ Build shoot_activation_pool:
│      │  └─ For each unit:
│      │     ├─ Check is_unit_alive(unit_id, game_state)
│      │     ├─ Check current_player matches
│      │     ├─ Check has RNG_NB > 0
│      │     ├─ Check has valid targets
│      │     └─ Add to pool
│      │
│      └─ Update game_state:
│         └─ phase = "shoot"
│
└─ Add to result:
   └─ {"phase_transition": True, "next_phase": "shoot"}
```

**Shooting → Next Player:**
```
shooting_handlers.execute_action():
│
├─ Process unit shooting
├─ Remove unit from shoot_activation_pool
│
└─ Check pool empty:
   └─ If empty:
      ├─ Switch player: current_player = 1 - current_player
      ├─ If current_player == 0:
      │  └─ Increment turn counter
      │
      ├─ Clear tracking sets:
      │  └─ units_moved, units_shot, etc.
      │
      ├─ Return to movement phase:
      │  └─> movement_handlers.movement_phase_start(game_state)
      │
      └─ Return: {"phase_complete": True, "next_phase": "move"}
```

**Advance Action Flow (Human Players):**
```
Human player activates unit in shoot phase:
│
├─ shooting_handlers._shooting_unit_execution_loop():
│  │
│  ├─ Build valid_target_pool
│  │
│  └─ If valid_target_pool is EMPTY:
│     │
│     ├─ For AI/gym agents:
│     │  └─ End activation immediately (PASS or ACTION)
│     │
│     └─ For human players:
│        └─ Return: {
│             "waiting_for_player": True,
│             "unitId": unit_id,
│             "no_targets": True,
│             "allow_advance": True,
│             "context": "no_targets_advance_available"
│           }

Frontend receives allow_advance signal:
│
├─ useEngineAPI.executeAction() response handler:
│  │
│  ├─ Detect: data.result?.allow_advance === true
│  │
│  └─ Set: advanceWarningPopup = { unitId, timestamp }
│
└─ Display advance warning popup:
   │
   ├─ Message: "Making an advance move won't allow you to shoot or charge in this turn."
   │
   └─ Three buttons:
      │
      ├─ "Confirm" (green) → handleConfirmAdvanceWarning():
      │  │
      │  ├─ Clear popup and shooting preview state
      │  ├─ Send advance action (no destination yet)
      │  │
      │  └─ Backend: _handle_advance_action():
      │     │
      │     ├─ Roll 1D6 for advance_range (from config: advance_distance_range)
      │     ├─ Store advance_range on unit
      │     ├─ Calculate valid destinations (BFS, advance_range hexes, no walls, no enemy-adjacent)
      │     │
      │     └─ Return: {
      │          "advance_destinations": [{col, row}, ...],
      │          "advance_range": 1-6,
      │          "waiting_for_player": True
      │        }
      │
      ├─ "Skip" (grey) → handleSkipAdvanceWarning():
      │  │
      │  ├─ Clear popup and advance state
      │  ├─ Send skip action to backend
      │  │
      │  └─ Backend: Remove unit from shoot_activation_pool
      │
      └─ "Cancel" (red) → handleCancelAdvanceWarning():
         │
         ├─ Clear popup and advance state
         ├─ Reset visual selection (mode → "select", selectedUnitId → null)
         │
         └─ NO backend action (unit stays in pool for re-activation)

After "Confirm" → Advance preview mode:
│
├─ Frontend receives advance_destinations:
│  │
│  ├─ Set mode = "advancePreview"
│  ├─ Set advanceDestinations = [...]
│  ├─ Set advancingUnitId = unit_id
│  │
│  └─ Display orange hex highlights for valid destinations
│
└─ Player clicks orange hex:
   │
   ├─ boardClickHandler → onAdvanceMove callback:
   │  │
   │  └─ Send advance action with destination:
   │     {
   │       "action": "advance",
   │       "unitId": unit_id,
   │       "destCol": clicked_col,
   │       "destRow": clicked_row
   │     }
   │
   └─ Backend: _handle_advance_action() with destination:
      │
      ├─ Validate destination is in valid_advance_destinations
      ├─ Reuse existing advance_range (if already rolled)
      ├─ Move unit to destination
      ├─ Mark unit in units_advanced set (if actually moved)
      │
      └─ Return: {
           "advance_range": 1-6,
           "activation_ended": True,
           "reset_mode": "select",
           "clear_selected_unit": True
         }

Frontend displays advance roll badge:
│
├─ On advance execution success:
│  │
│  ├─ Set advanceRoll = advance_range value
│  ├─ Set advancingUnitId = unit_id
│  │
│  └─ UnitRenderer.renderAdvanceRollBadge():
│     │
│     └─ Display green badge at bottom-right of unit icon
│        (similar to charge roll badge)

Cleanup signals:
│
├─ Backend sends reset_mode → Frontend: mode = "select"
├─ Backend sends clear_selected_unit → Frontend: selectedUnitId = null
│
└─ Frontend clears advance state:
   ├─ advanceDestinations = []
   ├─ advancingUnitId = null
   └─ advanceRoll = null

Post-advance restrictions:
│
├─ Charge phase: Units in units_advanced are ineligible
│
└─ Shooting phase: Advanced units cannot shoot
   └─ Exception: Weapons with "Assault" rule can shoot after advance
```

---

### Integration Points

**Gym Training:**
```
Training Script:
│
├─ from engine.w40k_core import W40KEngine
│
├─ env = W40KEngine(config, ...)
│
├─ model = MaskablePPO(policy, env, ...)
│
└─ Training loop:
   ├─ obs, info = env.reset()
   │
   └─ For each step:
      ├─ action, _ = model.predict(obs, action_masks=env.get_action_mask())
      ├─ obs, reward, done, truncated, info = env.step(action)
      └─ If done: obs, info = env.reset()
```

**HTTP API (Frontend — `services/api_server.py`):**
```
API Server (Flask):
│
├─ engine = W40KEngine(...) — état canonique : engine.game_state
│
├─ POST /api/game/start — initialise la partie ; réponse inclut game_state sérialisé
│
├─ POST /api/game/action — actions sémantiques (move, skip, shoot, charge, fight, advance, …)
│  │
│  ├─ Corps JSON : action OU { col, row, selectedUnitId } (clic plateau → move)
│  │
│  ├─ Optionnel : move_preview_mask_loops_client_hash (dernier hash reçu,
│  │   voir section « Move preview masque monde & payload API »)
│  │
│  ├─ engine.execute_semantic_action(...) ou handlers dédiés (preview_shoot_from_position, …)
│  │
│  └─ Réponse : game_state via _game_state_for_json(..., for_post_action=True,
│      mask_loops_client_hash=...) — vue allégée (pas une copie brute du moteur)
│
├─ GET /api/game/state — état courant (_game_state_for_json sans hash client)
│
├─ Sérialisation JSON : orjson en priorité ; types non natifs via default handler ;
│   repli make_json_serializable / jsonify si nécessaire
│
└─ Gym / pas HTTP : le code moteur utilise game_state complet ; les exclusions JSON
   ne s’appliquent qu’aux réponses HTTP documentées ci-dessus
```

---

## PERFORMANCE OPTIMIZATIONS

### LoS Cache (5x Shooting Speedup)

Line-of-sight calculations are cached on the active shooter (`unit["los_cache"]`) when a unit is activated for shooting. `shooting_phase_start()` no longer builds a global LoS cache for all units; it clears stale global cache data and lets `shooting_unit_activation_start()` call `build_unit_los_cache(game_state, unit_id)` for the active unit only. This avoids phase-start LoS spikes while preserving backend targetability as the source of truth.

`build_unit_los_cache()` delegates every target to `compute_unit_los()` (obscuring-aware, rule 13.10) and writes both `unit["los_cache"]` (can_see) and `unit["los_cover_cache"]` (cover). Cover status for valid shooting targets is read from this cache by `build_cover_by_unit_id_for_valid_targets()` instead of recomputing target visibility after `valid_target_pool_build()`. Cover applies as **−1 BS** on the hit roll (rule 13.08), not a save bonus.

> **Squad shoot (human PvP) path.** Manual per-model shooting (`squad_shoot_assign` →
> `squad_declare_shoot_model` → `_model_can_shoot_target` → `_attacker_model_can_reach_squad`, and the
> per-weapon pool via `_model_can_shoot_target_with_weapon`) is a **distinct** resolution path from
> the non-squad `shooting_attack_controller`. It now routes its eligibility/LoS through the same
> obscuring-aware primitive (`_compute_visibility_with_obscuring`), so the squad target pool, the
> blinking/greying, the assignment guard and the resolution all agree with `compute_unit_los`. A unit
> that moved behind obscuring terrain since activation can no longer be assigned/resolved as a target.

### Move Preview LoS / HP Blink Contract

Move-phase LoS preview has two separate responsibilities:

- **Visual blue/orange LoS overlay**: rendered immediately on the frontend from WASM (`buildLosPreviewFromSource`) for responsiveness. This visual overlay is not authoritative for targetability.
- **HP blinks and cover/probability indicators**: always come from the backend. The frontend calls `preview_shoot_from_position` and uses the returned `blinking_units` and `cover_by_unit_id`.

For move preview calls, the frontend sends `includeLosCells: false`. The backend then skips full-board LoS cell generation and returns only backend-valid targets plus per-target cover. This keeps targetability authoritative without forcing the backend to stream the full blue overlay on every hover.

The shoot phase uses the same backend cover source for HP blink probabilities: shooting responses that start blinking include `cover_by_unit_id`, and the frontend must use that map instead of WASM-derived cover for shoot HP blink labels.

Frontend request policy for move preview:
- Blue LoS overlay is scheduled through `requestAnimationFrame`.
- Backend target preview is throttled and serialized: only one `preview_shoot_from_position` request may be in flight.
- If the cursor moves while a request is in flight, only the latest pending destination is kept.
- Stale backend responses are ignored if they no longer match the current LoS destination.

Backend optimizations retained:
- `preview_shoot_valid_targets_from_position()` still uses `copy.deepcopy(game_state)` for safety. Do not mutate the live `game_state` for preview unless a strict restoration strategy has been proven safe.
- `valid_target_pool_build()` receives precomputed `weapon_available_pool` and enemy precheck data during preview, avoiding the former duplicate pool work (`valid_pool_ms` should remain near zero in profiling).
- `_move_los_preview_cache` memoizes exact backend preview results for `includeLosCells=False` using a strict key: process id, episode, turn, step, current player, unit id, destination, `units_cache` fingerprint, `units_advanced`, `units_fled`, and ranged weapon targetability fingerprint.

Rejected / non-retained experiments:
- Temporarily mutating the live `game_state` instead of `deepcopy` reduced snapshot cost but was rejected because hidden side effects could not be ruled out.
- A combined preview pass replacing `build_unit_los_cache()` plus `_build_weapon_availability_enemy_precheck()` was rejected because profiling showed no improvement and sometimes worse first-pass latency.

### Move preview masque monde & payload API

**Moteur (`game_state`)**  
- Champ : `move_preview_footprint_mask_loops` — listes de contours en coordonnées monde (structure interne tuples/listes selon le calcul).  
- Production : `movement_handlers._sync_move_preview_mask_loops` + `compute_move_preview_mask_loops_world` (`engine/hex_union_boundary_polygon.py`).  
- Quand ce champ est renseigné côté moteur, la vue HTTP **ne duplique pas** la zone hex `move_preview_footprint_zone` dans le JSON (économie massive sur les listes de couples).

**Vue HTTP (`_game_state_for_json` dans `services/api_server.py`)**  
- Toujours ajouter **`move_preview_footprint_mask_loops_hash`** (SHA-256 hex sur géométrie canonique) lorsque des boucles existent.  
- Remplacer les boucles par un **format compact JSON** : une boucle = `[x0,y0,x1,y1,...]` (pas `[[[x,y],…]]`).  
- **Omission du tableau** si la requête `POST /api/game/action` inclut **`move_preview_mask_loops_client_hash`** égal au hash courant **et** le contour est « volumineux » (seuil `_MASK_LOOPS_OMIT_MIN_TOTAL_COORDS`, actuellement 128 coordonnées scalaires au total). Réponse alors : pas de clé `move_preview_footprint_mask_loops`, **`move_preview_footprint_mask_loops_unchanged: true`**, hash inchangé.  
- Les autres routes (`/game/start`, `/game/state`, `/game/ai-turn`, …) ne passent pas ce hash : les boucles compactes sont renvoyées normalement si présentes.

**Frontend (`frontend/src/hooks/useEngineAPI.ts`)**  
- Cache module : dernier payload boucles + dernier hash ; envoi du hash sur les corps `executeAction`.  
- **`mergeGameStatePreservingOmittedObjectives`** et **`hydrateApiGameStateMovePreviewTransport`** réinjectent les boucles depuis le cache si `unchanged` + hash cohérent ; en cas d’incohérence, invalidation du cache (pas de repli silencieux qui laisserait la preview sans données).  
- Normalisation : **`normalizeMaskLoopsFromApi`** (`frontend/src/utils/movePreviewFootprintMaskLoops.ts`) accepte format compact **et** legacy paires `[x,y]`.

**Rendu Pixi (`frontend/src/components/BoardDisplay.tsx`)**  
- **`resolveMovePreviewMaskLoopsBeforeSmooth`** : priorité aux boucles API (**`server_loops`**).  
- Si absentes : reconstruction locale **`tryBuildHexUnionMaskPolygons`** depuis `footprintZonePoolRef` (**`polygon`**). Les phases où le moteur n’envoie pas encore les boucles (ex. certains chemins fight pile-in) peuvent donc rester plus coûteuses côté navigateur — alignement futur possible en étendant l’envoi serveur de boucles.

### Rendu plateau Pixi (highlights / redraw partiel)

**Objectif** : éviter un `drawBoard` complet quand seule la géométrie du **calque polygone move preview** change (ou lorsque rien ne change dans les highlights).

**Implémentation (`BoardPvp.tsx` + `BoardDisplay.tsx`)**  
- **`computeDrawBoardPartialRedrawFingerprint`** : deux empreintes — structure des highlights (phases, cellules, pools pour hit-test, halos, etc.) vs clé dédiée au polygone move (`movePolygonCacheKey`, alignée sur le cache rendu Pixi).  
- Si la structure est identique à la frame précédente et le conteneur **`highlights`** (`name === "highlights"`) survit au cycle destroy/recollage du stage : détachement avant `removeChildren`, réattachement après les couches persistantes ; **`detachMovePreviewLayerCacheFromStage`** n’est **pas** appelé dans ce cas (sinon le sous-arbre preview serait retiré du conteneur sauvé).  
- Si seule la clé polygone diffère : **`updateMovePreviewPolygonLayerInHighlightContainer`** met à jour uniquement le sous-arbre `move-preview-layer-cache-root`.  
- Sinon : **`drawBoard`** complet ; résultat expose **`highlightContainer`** pour tenir à jour les refs.  
- Le moteur / la sérialisation API ne sont pas modifiés par ce mécanisme (pure couche présentation).

### Kill Probability Cache (Lazy)

`game_state["kill_probability_cache"]` is filled on first use in `engine/ai/weapon_selector.py` (e.g. when `select_best_ranged_weapon()` or `select_best_melee_weapon()` is called). It is no longer precomputed at shooting_phase_start() or fight_phase_start(), avoiding a costly O(units×weapons×enemies) block at phase transition.

### Charge Phase Start Profiling

The `shoot` -> `charge` transition is dominated by charge activation pool construction, not by the phase switch itself. Keep `W40K_PERF_TIMING=1` instrumentation around `CHARGE_PHASE_START`, `CHARGE_BUILD_POOL`, `CHARGE_DEST_BFS`, and `CHARGE_REVERSE_GOAL_BFS` when changing charge eligibility.

Current effective optimizations:
- Cheap hex lower-bound pruning avoids full BFS when a unit is geometrically too far to engage. This pruning is disabled for round-vs-round engagement pairs because those use exact Euclidean edge clearance in `unit_entries_within_engagement_zone`.
- Reverse goal BFS is used only for `early_exit_if_valid=True` without a declared target, and only when the round-vs-round guard allows it. It builds legal final charge goals, then searches back to the charger primary anchor through the same placement graph.
- Fine-grained `CHARGE_DEST_BFS` timings are intentionally kept: `bfs_candidate_fp_s`, `bfs_placement_s`, `bfs_engagement_s`, `bfs_rejected_placement_n`, `bfs_overlap_n`, `bfs_no_engagement_n`, and `bfs_engagement_checks_n`.

Rejected charge experiments:
- Sorting historical BFS neighbors toward the nearest enemy added measurable overhead and did not reduce `visited_n` on the PvP test scenario.
- Precomputing reverse-BFS anchors from enemy engagement zones increased `goal_build_s` and total charge initialization time on the large-base `unit_id=107` case.

Do not reintroduce these rejected optimizations without a charge non-regression test that compares reachable eligibility and end destinations for large round, oval, and square bases.

### Egocentric Observation (150 Floats)

Observation uses relative coordinates centered on active unit. Perception radius R=25 creates fog of war. Enables transfer learning. No performance degradation despite larger observation space.

### CPU Optimization (311 it/s)

Small neural networks (256×256 MlpPolicy) run faster on CPU than GPU. Better cache locality for small networks. Training achieves 311 iterations/second on CPU vs 282 it/s on GPU.

### Combined Impact

Overall 4.7x training speedup (66 → 311 it/s). Debug config (50 episodes) runs in 11 seconds. Default config (2000 episodes) completes in 7 minutes.

---

## SUCCESS METRICS

### Architecture
- ✅ Single source of truth maintained
- ✅ Sequential activation (one unit per step)
- ✅ Built-in step counting (one location)
- ✅ Phase completion by eligibility
- ✅ UPPERCASE field validation enforced
- ✅ Zero wrapper patterns

### Performance
- ✅ 4.7x training speedup (66 → 311 it/s)
- ✅ LoS cache: 5x faster shooting
- ✅ Egocentric observation: No performance loss
- ✅ CPU optimization: 10% faster than GPU

### Observation System
- ✅ 150-float egocentric observation
- ✅ R=25 perception radius (fog of war)
- ✅ Directional awareness (ahead/behind/flanking)
- ✅ Transfer learning enabled

---

## RELATED DOCUMENTATION

1. [AI_TURN.md](AI_TURN.md) - Core game rules and turn sequence
2. [AI_TRAINING.md](AI_TRAINING.md) - PPO training integration
3. [AI_OBSERVATION.md](AI_OBSERVATION.md) - Egocentric observation system
4. [AI_TARGET_SELECTION.md](AI_TARGET_SELECTION.md) - Target selection and prioritization
5. [Weapon_rules.md](Weapon_rules.md) - Weapons system technical documentation

---

## SUMMARY

### AI Architecture Compliance Checklist

This checklist must be mentally (or explicitly) applied for every substantial change
to the codebase, whether proposed by a human or an assistant:

- **Rule alignment**
  - The change respects all items in **Core AI Coding Rules** (top of this document).
  - The change does not introduce any logic that contradicts `AI_TURN.md`.

- **Configuration discipline**
  - All new tunable values (thresholds, weights, limits) are defined in configuration
    files instead of being inlined in code.
  - Any new configuration keys are documented in `Documentation/CONFIG_FILES.md` or
    the relevant configuration guide.

- **Validation discipline**
  - All newly added required configuration accesses use `shared.validation.require_key`.
  - All newly added required external values use `shared.validation.require_present`.

- **Error handling**
  - Missing or structurally invalid data results in explicit, fail-fast errors.
  - No new code silently replaces missing values or skips checks.

- **Complexity and architecture**
  - The chosen design is the simplest solution that satisfies the requirements.
  - New modules and functions integrate cleanly into the architecture described
    in this document, without duplicating responsibilities.

The W40K engine uses modular architecture with clear separation of concerns. Core engine (`w40k_core.py`) owns game_state and orchestrates flow. Specialized modules handle observation, rewards, actions, and combat. Phase handlers implement game rules. All modules follow AI_TURN.md compliance: single source of truth, sequential activation, UPPERCASE fields, no wrappers.

The "How Everything Works Together" section traces complete request flows showing how modules interact during actual gameplay. Understanding these flows is essential for debugging, extending features, and maintaining the system.

Performance optimizations achieve 4.7x training speedup while maintaining zero architectural violations. Modular structure enables independent testing, parallel development, and maintainable codebase.