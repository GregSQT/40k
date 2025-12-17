# Weapons System - Complete Documentation

**Last Updated**: 2025-12-15  
**Status**: Production - Phase 1 Complete, Phase 2 Pending

---

## 📋 TABLE OF CONTENTS

1. [Overview](#overview)
2. [Module Structure](#module-structure)
3. [Weapon Arrays Architecture](#weapon-arrays-architecture)
4. [Weapon Rules System](#weapon-rules-system)
5. [AI Weapon Selection](#ai-weapon-selection)
6. [Armory Files (TypeScript)](#armory-files-typescript)
7. [Backend Implementation](#backend-implementation)
8. [Frontend Integration](#frontend-integration)
9. [Configuration](#configuration)
10. [Testing & Validation](#testing--validation)

---

## OVERVIEW

The weapons system supports:
- **Multiple weapons per unit** (up to 3 ranged, 2 melee)
- **Weapon rules** (RAPID_FIRE, MELTA, BLAST, etc.)
- **Automatic weapon selection** by AI (optimal weapon per target)
- **Single source of truth** (TypeScript armory files parsed by Python)

### Key Principles
- ✅ **UPPERCASE fields** (`RNG_WEAPONS`, `CC_WEAPONS`, `WEAPON_RULES`)
- ✅ **Fail-fast validation** (invalid weapons/rules raise errors on load)
- ✅ **No defaults** (missing data = error, not silent fallback)
- ✅ **Config-based** (all values in config files, not hardcoded)

---

## MODULE STRUCTURE

### `engine/weapons/` Package

```
engine/weapons/
├── __init__.py        # Clean public API
├── parser.py          # Parse TypeScript armory files
└── rules.py           # Weapon rules system (RAPID_FIRE, etc.)
```

### Public API

```python
from engine.weapons import (
    # Parser
    get_armory_parser,     # Get parser singleton
    get_weapon,            # Get single weapon
    get_weapons,           # Get multiple weapons
    
    # Rules
    get_weapon_rules_registry,  # Get rules registry
    parse_weapon_rule,          # Parse "RULE_NAME:X"
    validate_weapon_rules_field,  # Validate WEAPON_RULES
)
```

---

## WEAPON ARRAYS ARCHITECTURE

### Unit Weapon Structure

Units have **weapon arrays** instead of single weapons:

```python
unit = {
    "id": "marine_1",
    "display_name": "Space Marine",
    
    # Ranged weapons (max 3)
    "RNG_WEAPONS": [
        {"display_name": "Bolt Rifle", "RNG": 15, "NB": 2, "ATK": 3, ...},
        {"display_name": "Bolt Pistol", "RNG": 6, "NB": 1, "ATK": 3, ...},
    ],
    "selectedRngWeaponIndex": 0,  # Currently selected (0-2)
    
    # Melee weapons (max 2)
    "CC_WEAPONS": [
        {"display_name": "Combat Knife", "NB": 1, "ATK": 3, ...},
    ],
    "selectedCcWeaponIndex": 0,  # Currently selected (0-1)
}
```

### Weapon Fields

**Ranged Weapons**:
- `display_name` (string) - Display name
- `RNG` (int) - Range in hexes
- `NB` (int) - Number of attacks
- `ATK` (int) - Hit roll target (3+ = hit on 3-6)
- `STR` (int) - Strength for wound calculation
- `AP` (int) - Armor penetration
- `DMG` (int) - Damage per unsaved wound
- `WEAPON_RULES` (array) - Optional weapon rules

**Melee Weapons**: Same except no `RNG` field

---

## WEAPON RULES SYSTEM

### Overview

Weapon rules add special abilities to weapons (e.g., bonus shots, auto-hits, restrictions).

**Status**: ✅ Phase 1 Complete (infrastructure), Phase 2 Pending (rule effects)

### Rule Format

Rules use string format: `"RULE_NAME"` or `"RULE_NAME:X"`

**Examples**:
```json
{
  "WEAPON_RULES": ["RAPID_FIRE:1", "ASSAULT"]
}
```

- `RAPID_FIRE:1` - Parameterized rule (X=1)
- `ASSAULT` - Non-parameterized rule

### Available Rules

Defined in `config/weapon_rules.json`:

| Rule | Parameter | Description |
|------|-----------|-------------|
| `RAPID_FIRE` | ✅ X | Make X additional attacks when target within half range |
| `ASSAULT` | ❌ | No penalty when shooting after advancing/falling back |
| `HEAVY` | ❌ | Subtract 1 from hit rolls if shooter moved this turn |
| `MELTA` | ✅ X | Roll 2d6 for damage, pick highest within X hexes |
| `BLAST` | ❌ | Cannot target units in melee combat |
| `PISTOL` | ❌ | Can fire even if shooter in melee range |
| `GRENADE` | ❌ | Only one per unit per phase |
| `TORRENT` | ❌ | Automatically hits (no hit roll required) |

### Rule Validation

**Timing**: On engine initialization (fail-fast)

**Validation**:
- ✅ Rule name must exist in `weapon_rules.json`
- ✅ Parameterized rules must have `:X` parameter
- ✅ Non-parameterized rules must NOT have parameter
- ✅ Parameter must be positive integer

**Example Errors**:
```python
# Missing parameter
"RAPID_FIRE" → ConfigurationError: requires parameter (use 'RAPID_FIRE:1')

# Invalid rule
"INVALID_RULE" → ConfigurationError: Rule not found in registry

# Unexpected parameter
"ASSAULT:1" → ConfigurationError: Rule does not accept parameters
```

### Adding Rules to Weapons

**In TypeScript armory files**:
```typescript
export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {
  BoltRifle: {
    display_name: "Bolt Rifle",
    RNG: 15,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["RAPID_FIRE:1"]  // ← Add this
  }
};
```

### Phase 2: Rule Implementation

**Not yet implemented** - rule logic will be added in Phase 2.

**Planned integration points**:
- `RAPID_FIRE` → Modify shot count in `shooting_handlers.py`
- `MELTA` → Modify damage in attack sequence
- `BLAST` → Modify target validation
- `ASSAULT` → Modify eligibility checks

---

## AI WEAPON SELECTION

### How It Works

**Agent does NOT choose weapons** - weapon selection is automatic.

**Decision Flow**:
1. **Agent decides**: Which target to attack
2. **System selects**: Best weapon for that target (automatic)
3. **System executes**: Attack with selected weapon

### Selection Algorithm

**Location**: `engine/ai/weapon_selector.py`

**Function**: `select_best_ranged_weapon()` / `select_best_melee_weapon()`

**Logic**:
```python
for each weapon in unit's weapons:
    calculate kill_probability(weapon, target)

select weapon with highest kill_probability
```

### Kill Probability Calculation

**Formula**:
```python
p_kill = p_hit × p_wound × p_fail_save × (damage_dealt >= target.HP_CUR)

Where:
- p_hit = (7 - weapon.ATK) / 6
- p_wound = Warhammer 40K wound table (STR vs T)
- p_fail_save = (7 - effective_save) / 6
- effective_save = max(target.ARMOR_SAVE, target.INVUL_SAVE) + weapon.AP
```

### When Selection Happens

**Shooting Phase**:
- Agent selects target → System picks best ranged weapon → Shoots

**Fight Phase**:
- Agent selects target → System picks best melee weapon → Attacks

**Integration Points**:
- `engine/phase_handlers/shooting_handlers.py` (lines ~1177-1193)
- `engine/phase_handlers/fight_handlers.py` (lines ~1512-1526)

---

## ARMORY FILES (TYPESCRIPT)

### Purpose

**Single source of truth** for weapon definitions.

TypeScript armory files are parsed by Python at runtime (no duplicate Python definitions needed).

### File Locations

```
frontend/src/roster/{faction}/armory.ts
```

**Examples**:
- `frontend/src/roster/spaceMarine/armory.ts`
- `frontend/src/roster/tyranid/armory.ts`

### Armory Structure

```typescript
import type { Weapon } from '../../types/game';

export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {
  BoltRifle: {
    display_name: "Bolt Rifle",
    RNG: 15,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: -1,
    DMG: 1,
    WEAPON_RULES: ["RAPID_FIRE:1"]
  },
  
  BoltPistol: {
    display_name: "Bolt Pistol",
    RNG: 6,
    NB: 1,
    ATK: 3,
    STR: 4,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: ["PISTOL"]
  },
  
  CombatKnife: {
    display_name: "Combat Knife",
    NB: 3,
    ATK: 3,
    STR: 3,
    AP: 0,
    DMG: 1,
    WEAPON_RULES: []
  }
};
```

### Using Weapons in Units

**In TypeScript unit definitions**:
```typescript
export const createIntercessor = (): Unit => ({
  id: "intercessor_1",
  display_name: "Intercessor",
  
  // Reference weapons by code name
  RNG_WEAPONS: [
    SPACE_MARINE_ARMORY.BoltRifle,
    SPACE_MARINE_ARMORY.BoltPistol
  ],
  CC_WEAPONS: [
    SPACE_MARINE_ARMORY.CombatKnife
  ],
  selectedRngWeaponIndex: 0,
  selectedCcWeaponIndex: 0,
  
  // Other unit fields...
});
```

---

## BACKEND IMPLEMENTATION

### Parsing Armory Files

**Module**: `engine/weapons/parser.py`

**Class**: `ArmoryParser`

**Usage**:
```python
from engine.weapons import get_armory_parser

parser = get_armory_parser()
armory = parser.get_armory("SpaceMarine")
# Returns: dict of all Space Marine weapons

bolt_rifle = parser.get_weapon("SpaceMarine", "BoltRifle")
# Returns: weapon dict or None
```

**Features**:
- Parses TypeScript files with regex
- Validates weapon structure
- Validates WEAPON_RULES (fail-fast)
- Caches results for performance

### Weapon Helpers

**Module**: `engine/utils/weapon_helpers.py`

**Key Functions**:
```python
# Get weapon from arrays
get_selected_ranged_weapon(unit) → weapon dict
get_selected_melee_weapon(unit) → weapon dict

# Get weapon stats
get_ranged_weapon_stat(unit, "RNG") → int
get_melee_weapon_stat(unit, "STR") → int

# Check weapon availability
has_ranged_weapons(unit) → bool
has_melee_weapons(unit) → bool
```

### Weapon Selection

**Module**: `engine/ai/weapon_selector.py`

**Key Functions**:
```python
calculate_kill_probability(unit, weapon, target, game_state) → float

select_best_ranged_weapon(unit, target, game_state) → int (index)

select_best_melee_weapon(unit, target, game_state) → int (index)
```

---

## FRONTEND INTEGRATION

### TypeScript Types

**File**: `frontend/src/types/game.ts`

```typescript
interface Weapon {
  display_name: string;
  RNG?: number;    // Optional (melee weapons don't have range)
  NB: number;
  ATK: number;
  STR: number;
  AP: number;
  DMG: number;
  WEAPON_RULES?: string[];  // Optional
}

interface Unit {
  id: string;
  display_name: string;
  
  RNG_WEAPONS: Weapon[];
  CC_WEAPONS: Weapon[];
  selectedRngWeaponIndex?: number;
  selectedCcWeaponIndex?: number;
  
  // Other fields...
}
```

### UI Display

**Weapon Display Components**:
- `UnitCard` - Shows unit with weapons
- `UnitStatusTable` - Expandable weapon list
- `WeaponRuleTooltip` - (Phase 2) Rule descriptions

**UI Requirements**:
- Show all weapons (expandable list)
- Highlight selected weapon
- Display weapon rules as badges
- Click rule badge → show description tooltip (Phase 2)

---

## CONFIGURATION

### Weapon Rules Config

**File**: `config/weapon_rules.json`

**Structure**:
```json
{
  "RULE_NAME": {
    "name": "Display Name",
    "description": "Short description (use X for parameter)",
    "has_parameter": true|false
  }
}
```

**Example**:
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
  }
}
```

### Training Config

**Observation size must be updated**:
```json
{
  "observation_params": {
    "obs_size": 313,  // Was 300 (updated for weapon arrays)
    "perception_radius": 25
  }
}
```

---

## TESTING & VALIDATION

### Validation on Load

All weapon data validated on engine initialization:

```python
# 1. Load weapon rules registry
registry = get_weapon_rules_registry()
# Validates: config/weapon_rules.json structure

# 2. Parse armory files
parser = get_armory_parser()
armory = parser.get_armory("SpaceMarine")
# Validates: All weapons have required fields
# Validates: All WEAPON_RULES exist and have correct parameters

# 3. Load units
units = load_units_from_scenario(scenario_file)
# Validates: All weapon references exist in armory
```

### Test Coverage

**Unit Tests**:
- Weapon parsing (armory files → Python dicts)
- Weapon rules validation (valid/invalid rules)
- Weapon selection (optimal weapon per target)

**Integration Tests**:
- Full combat with multiple weapons
- Weapon rule application (Phase 2)

### Manual Testing

```bash
# Test weapon parsing
python -c "
from engine.weapons import get_armory_parser
parser = get_armory_parser()
armory = parser.get_armory('SpaceMarine')
print(f'Loaded {len(armory)} weapons')
"

# Test weapon rules
python -c "
from engine.weapons import get_weapon_rules_registry
registry = get_weapon_rules_registry()
rules = registry.get_all_rules()
print(f'Loaded {len(rules)} rules')
"
```

---

## IMPLEMENTATION STATUS

### ✅ Phase 1 Complete
- Weapon arrays architecture
- Armory parsing system
- Weapon rules infrastructure
- AI weapon selection
- Validation (fail-fast)
- Documentation

### 🔜 Phase 2 Pending
- Weapon rule effects in gameplay
- Frontend weapon rule display
- Rule tooltips
- Additional rules

---

## REFERENCES

- `AI_IMPLEMENTATION.md` - Core coding rules
- `AI_TURN.md` - Game logic rules
- `CONFIG_FILES.md` - Configuration reference
- `ARMORY_REFACTOR.md` - Original armory architecture

---

**For questions or issues, see the relevant section above or check the module source code in `engine/weapons/`.**




