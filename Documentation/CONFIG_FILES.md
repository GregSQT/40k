# Configuration Files Reference

This document describes all configuration files used in the W40K game engine.

**AI_IMPLEMENTATION.md COMPLIANCE**: All tunable values, thresholds, and game parameters must be defined in these configuration files, never hardcoded in logic.

---

## Table of Contents

1. [Weapon Rules](#weapon-rules-configweapon_rulesjson)
2. [Game Config](#game-config-configgame_configjson)
3. [Training Configuration](#training-configuration)
4. [Scenario Files](#scenario-files)
5. [Armory Files](#armory-files)

---

## Weapon Rules (`config/weapon_rules.json`)

**Location**: `/config/weapon_rules.json`

**Purpose**: Define special weapon abilities and their parameters.

**Status**: ✅ Implemented (Phase 1)

**Design**: See [WEAPON_RULES_DESIGN.md](WEAPON_RULES_DESIGN.md) for complete design specification.

### Structure

```json
{
  "RULE_NAME": {
    "name": "Display Name",
    "description": "Short description for tooltip (use X for parameter)",
    "has_parameter": true|false
  }
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Display name for UI (e.g., "Rapid Fire") |
| `description` | string | ✅ | Short description for tooltip. Use "X" for parameter placeholder. |
| `has_parameter` | boolean | ✅ | Whether this rule requires a numeric parameter |

### Example

```json
{
  "RAPID_FIRE": {
    "name": "Rapid Fire",
    "description": "Make X additional attacks when target within half range",
    "has_parameter": true
  },
  "ASSAULT": {
    "name": "Assault",
    "description": "No penalty when shooting after advancing or falling back",
    "has_parameter": false
  },
  "MELTA": {
    "name": "Melta",
    "description": "Roll 2 dice for damage and pick the highest result when target is within X hexes",
    "has_parameter": true
  }
}
```

### Validation

- ✅ **On Load**: All weapon rules validated when engine initializes
- ✅ **Fail-Fast**: Raises `ConfigurationError` if weapon references non-existent rule
- ✅ **Parameter Validation**: Raises error if required parameter missing or invalid

### Usage in Weapons

Weapons reference rules in their `WEAPON_RULES` array:

```typescript
// In armory files (e.g., frontend/src/roster/spaceMarine/armory.ts)
export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {
  BoltRifle: {
    display_name: "Bolt Rifle",
    RNG: 15,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["RAPID_FIRE:1"]  // Rule with parameter
  },
  
  AssaultBolter: {
    display_name: "Assault Bolter",
    RNG: 12,
    NB: 3,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["RAPID_FIRE:1", "ASSAULT"]  // Multiple rules
  },
  
  BoltPistol: {
    display_name: "Bolt Pistol",
    RNG: 6,
    NB: 1,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: []  // No rules
  }
};
```

### Rule String Format

**Format**: `"RULE_NAME"` or `"RULE_NAME:X"`

**Examples**:
- `"RAPID_FIRE:1"` → Rule: RAPID_FIRE, Parameter: 1
- `"MELTA:6"` → Rule: MELTA, Parameter: 6
- `"ASSAULT"` → Rule: ASSAULT, No parameter

**Validation Rules**:
- Rule name must exist in `weapon_rules.json`
- If `has_parameter=true`, parameter `:X` must be provided
- If `has_parameter=false`, parameter must NOT be provided
- Parameter must be positive integer if provided

---

## Game Config (`config/game_config.json`)

**Location**: `/config/game_config.json`

**Purpose**: Core gameplay rules and global parameters.

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `game_rules.max_turns` | integer | Maximum number of turns per episode |
| `game_rules.turn_limit_penalty` | number | Penalty when turn limit reached |
| `game_rules.charge_max_distance` | integer | Maximum charge distance |
| `game_rules.advance_distance_range` | integer | Advance roll range (D6 => 6) |
| `game_rules.avg_charge_roll` | integer | Average charge distance used for heuristics |
| `game_rules.macro_max_unit_value` | integer | Normalization constant for macro unit value |
| `game_rules.macro_target_weights` | object | Target type weights for macro scoring |

### Example

```json
{
  "game_rules": {
    "macro_max_unit_value": 200,
    "macro_target_weights": {
      "swarm": 1.0,
      "troop": 1.5,
      "elite": 2.0
    }
  }
}
```

---

## Training Configuration

**Location**: `/config/agents/{agent_name}/{agent_name}_training_config.json`

**Purpose**: Configure PPO training parameters for AI agents.

**Example**: `/config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json`

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_episodes` | integer | Number of episodes to train |
| `learning_rate` | float | PPO learning rate |
| `gamma` | float | Discount factor for rewards |
| `batch_size` | integer | Training batch size |
| `max_turns_per_episode` | integer | Maximum turns before episode truncation |

See training config files for complete field list.

---

## Scenario Files

**Location**: `/config/scenarios/{scenario_name}.json`

**Purpose**: Define game scenarios with unit placements, objectives, and terrain.

**Status**: To be documented

---

## Armory Files

**Location**: `/frontend/src/roster/{faction}/armory.ts`

**Purpose**: Define all weapons for a faction (SINGLE SOURCE OF TRUTH).

**Status**: See [ARMORY_REFACTOR.md](../ARMORY_REFACTOR.md) for complete documentation.

### Example

```typescript
export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {
  BoltRifle: {
    display_name: "Bolt Rifle",
    RNG: 15,         // Range in hexes
    NB: 2,           // Number of attacks
    ATK: 3,          // Hit roll target (3+ = hit on 3-6)
    STR: 4,          // Strength for wound calculation
    AP: -1,          // Armor penetration
    DMG: 1,          // Damage per unsaved wound
    WEAPON_RULES: [] // Weapon rules (optional)
  }
};
```

**Python Integration**: Parsed by `engine/armory_parser.py` at runtime.

---

## Adding New Configuration Files

When adding new configuration files:

1. ✅ Document structure in this file
2. ✅ Use `require_key()` and `require_present()` from `shared/data_validation.py`
3. ✅ Validate on load (fail-fast)
4. ✅ No silent defaults - raise errors for missing required fields
5. ✅ Run `python scripts/check_ai_rules.py` after implementation

---

## Related Documentation

- [AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md) - Core coding rules
- [WEAPON_RULES_DESIGN.md](WEAPON_RULES_DESIGN.md) - Weapon rules system design
- [ARMORY_REFACTOR.md](../ARMORY_REFACTOR.md) - Armory system architecture

