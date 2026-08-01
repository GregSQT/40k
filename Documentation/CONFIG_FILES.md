# Configuration Files Reference

This document describes all configuration files used in the W40K game engine.

**AI_IMPLEMENTATION.md COMPLIANCE**: All tunable values, thresholds, and game parameters must be defined in these configuration files, never hardcoded in logic.

---

## Table of Contents

1. [Weapon Rules](#weapon-rules-configweapon_rulesjson)
2. [App Config](#app-config-configconfigjson)
3. [Game Config](#game-config-configgame_configjson)
4. [Training Configuration](#training-configuration)
5. [Scenario Files](#scenario-files)
6. [Armory Files](#armory-files)

---

## Weapon Rules (`config/weapon_rules.json`)

**Location**: `/config/weapon_rules.json`

**Purpose**: Define special weapon abilities and their parameters.

**Status**: ✅ Implemented (Phase 1)

**Design**: Structure documentée dans la section Weapon Rules ci-dessus ; pas de document WEAPON_RULES_DESIGN.md séparé actuellement.

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

## App Config (`config/config.json`)

**Location**: `/config/config.json` (backend only — non copié vers le frontend)

**Purpose**: Configuration infra/projet : chemins, defaults, env d'entraînement. Distinct de
`game_config.json` (règles de jeu).

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `paths.model_file` | string | Template du chemin modèle (`ai/models/{agent_key}/model_{agent_key}.zip`) |
| `defaults.scenario` / `training_config` / `rewards_config` / `game_config` | string | Noms de config par défaut |
| `defaults.test_board` | string | Board par défaut des modes test |
| `defaults.agent_key` | string | **Identité de l'agent unique (mode single-agent)**. Source de vérité lue par `UnitRegistry._load_agent_key()` → `UnitRegistry.AGENT_KEY` (moteur : `get_model_key()`, rewards, handlers ; serveur PvP : `get_agents_from_scenario`) ET par `api_server._configured_agent_key()` pour les modes de test forçant un agent (PvE/pve_test/Endless_duty). Changer d'agent = éditer cette clé, jamais le code. No fallback : clé absente → `ConfigurationError`. |

### Example

```json
{
  "defaults": {
    "scenario": "default",
    "training_config": "default",
    "rewards_config": "default",
    "game_config": "default",
    "test_board": "x5_44x60",
    "agent_key": "ArmageddonAgent"
  }
}
```

**Note historique** : `CoreAgent` a été retiré (V11 T6-i, commit `20a2d479`) au profit
d'`ArmageddonAgent`. Auparavant l'identité single-agent était hardcodée (`UnitRegistry.CORE_AGENT_KEY`) ;
elle est désormais pilotée par `defaults.agent_key`.

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

**Example**: `/config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json` (rewards : `/config/agents/ArmageddonAgent/ArmageddonAgent_rewards_config.json`)

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_episodes` | integer | Number of episodes to train |
| `learning_rate` | float **ou** objet | PPO learning rate. Objet `{initial, final, decay_fraction}` = rampe par épisode (voir ci-dessous) |
| `ent_coef` | float **ou** objet | Coefficient d'entropie. Objet `{start, end, decay_fraction}` = rampe par épisode |
| `gamma` | float | Discount factor for rewards |
| `batch_size` | integer | Training batch size |
| `max_turns_per_episode` | integer | Maximum turns before episode truncation |

See training config files for complete field list.

### `deployment_mode_schedule` — rampe de déploiement (bloc OBLIGATOIRE)

Décide, épisode par épisode, si la partie est rejouée en placement **fixe** (positions du
scénario) ou en **déploiement actif** (l'agent place lui-même ses figurines). La probabilité de
« actif » monte linéairement de `active_ratio_start` à `active_ratio_end` sur la durée du run.

À ne pas confondre avec `deployment_random_mix`, son voisin immédiat dans le fichier, qui
randomise les **actions** d'un déploiement déjà actif.

| Clé | Type | Contrainte |
|---|---|---|
| `enabled` | bool | — |
| `training_only` | bool | `true` : la rampe ne s'applique qu'aux scénarios du split `training` |
| `active_ratio_start` | number | ∈ [0,1] — probabilité de déploiement actif au **début** du run |
| `active_ratio_end` | number | ∈ [0,1] — probabilité à la **fin** |
| `schedule` | string | exactement `"linear"` |
| `freeze_after_progress` | number | ∈ [0,1] — progression au-delà de laquelle la rampe est gelée |

Le dénominateur de la progression est `total_episodes` (même profil, entier > 0).

**Si le bloc manque dans un profil d'entraînement, le moteur LÈVE** (`KeyError`, au premier
`reset()` — donc au démarrage du run). C'est délibéré : jusqu'au 2026-07-29 l'absence
désactivait la rampe **en silence**, ce qui a laissé deux profils (`x5_append`, `x1_debug`) la
perdre entièrement et deux autres (`x5_new`, `x5_debug`) finir à `0.0`. Ces profils entraînaient
un agent qui ne se déploie jamais, puis le **notaient sur des parties à déployer** :
l'évaluation, elle, impose toujours une phase de déploiement. Sur les chemins API/PvP, qui ne
fournissent qu'un fragment de config (`observation_params`) et n'ont pas d'épisodes à ramper,
l'absence reste légitime et ne lève pas.

Réglage de référence des six profils `ArmageddonAgent` (2026-08-01) : `0.3 → 0.8`, `linear`,
`freeze_after_progress: 0.5`. **Le gel arrive avant la fin de la rampe**, donc `active_ratio_end`
n'est jamais atteint : la part réellement plafond est `start + (end − start) × freeze` = **0.55**.
C'est ce plafond effectif, et non `active_ratio_end`, qui dit quelle proportion des épisodes de
fin de run se joue en déploiement actif. Chaque bloc porte un champ `justification` (même
convention que `observation_params.justification`). Verrou :
`tests/unit/engine/test_deployment_mode_schedule.py` dérive la référence du profil `x1`, exige que
les cinq autres l'égalent, et vérifie que le plafond effectif reste ≥ 0.5.

### Rampes `learning_rate` / `ent_coef` — `decay_fraction` (clé OBLIGATOIRE)

Quand `learning_rate` ou `ent_coef` est un **objet** plutôt qu'un scalaire, un callback interpole
la valeur **par épisode** pendant le run. Les trois clés sont obligatoires, sans valeur par
défaut — `setup_callbacks` les lit par `require_key`.

| Clé | Type | Contrainte |
|---|---|---|
| `initial` / `start` | number | valeur au **début** du run (`initial` pour `learning_rate`, `start` pour `ent_coef`) |
| `final` / `end` | number | valeur **plancher**, tenue une fois la rampe achevée |
| `decay_fraction` | number | ∈ ]0,1] — fraction du run sur laquelle la rampe se déroule **intégralement** |

`decay_fraction` existe parce que la rampe est normalisée sur `total_episodes` : allonger un run
l'étire mécaniquement, alors que ce qui compte pour PPO est le **nombre d'updates de gradient**
passés à haut LR / haute entropie. `1.0` = comportement historique (rampe sur tout le run) et
reste le réglage des runs courts. La clé est **propre à chaque rampe** : `x1_long` (200 000
épisodes) met `0.4` sur `ent_coef` (exploration terminée à 80 000, exploitation ensuite) et `0.7`
sur `learning_rate` (rampe jusqu'à 140 000, pour ne pas brider l'apprentissage sur 60 % du run). Détail du raisonnement et tableau des
profils : `Documentation/AI_TRAINING.md`. Verrou :
`tests/unit/ai/test_schedule_decay_fraction.py`.

> ⚠️ `checkpoint_save_freq` ne se compte **pas** en épisodes : SB3 sauvegarde tous les
> `save_freq` **appels du callback**, soit un par pas du VecEnv (≈ `n_envs` timesteps). Le régler
> depuis une durée exprimée en épisodes n'a donc pas de sens ; pour couvrir davantage
> d'historique sur un run long, le levier sans ambiguïté est `max_checkpoints`.

---

## Scenario Files

**Location**: `/config/scenario_{scenario_name}.json` (racine de `config/`, ex. `config/scenario_pvp_squad5.json`, `config/scenario_endless_duty.json`)

**Purpose**: Define game scenarios with unit placements, objectives, and terrain. Les scénarios référencent les rosters via `agent_roster_ref` / `opponent_roster_ref`.

**Status**: To be documented

---

## Armory Files

**Location**: `/frontend/src/roster/{faction}/armory.ts`

**Purpose**: Define all weapons for a faction (SINGLE SOURCE OF TRUTH).

**Status**: Voir [Weapon_rules.md](Weapon_rules.md) pour l’architecture armurerie et le parsing.

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

**Python Integration**: Parsed by `engine/weapons/parser.py` (ArmoryParser) at runtime.

---

## Adding New Configuration Files

When adding new configuration files:

1. ✅ Document structure in this file
2. ✅ Use `require_key()` and `require_present()` from `shared/data_validation.py` (module de validation stricte)
3. ✅ Validate on load (fail-fast)
4. ✅ No silent defaults - raise errors for missing required fields
5. ✅ Run `python scripts/check_ai_rules.py` after implementation

---

## Related Documentation

- [AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md) - Core coding rules
- [Weapon_rules.md](Weapon_rules.md) - Weapon system and armory architecture
- [Code_Compliance/AI_RULES_checker.md](Code_Compliance/AI_RULES_checker.md) - Script check_ai_rules.py (conformité AI_TURN / coding_practices)

