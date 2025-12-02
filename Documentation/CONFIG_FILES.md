# Configuration Files Guide

## Scenario Files

The project uses different scenario files for different purposes:

### Training Scenarios

**Location:** `config/agents/<agent_name>/scenarios/`

**Purpose:** AI training with curriculum learning

**Format:** `<agent>_scenario_phase<N>-<variant>.json`

**Examples:**
```
config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/
├── SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-1.json
├── SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-2.json
├── SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase2-1.json
└── ...
```

**Usage:** Loaded automatically by training scripts based on agent configuration

### Game/API Scenario

**Location:** `config/scenario_game.json`

**Purpose:** Manual testing and API server visualization

**Format:** Standard scenario JSON with units array

**Example:**
```json
{
  "units": [
    {
      "id": 1,
      "unit_type": "Intercessor",
      "player": 0,
      "col": 14,
      "row": 14
    },
    ...
  ]
}
```

**Usage:** Loaded by API server (`services/api_server.py`) for frontend visualization

## Key Differences

| Aspect | Training Scenarios | Game Scenario |
|--------|-------------------|---------------|
| **Path** | `config/agents/<agent>/scenarios/*.json` | `config/scenario_game.json` |
| **Purpose** | AI training with rotation | Manual testing & visualization |
| **Loaded by** | `ai/train.py` | `services/api_server.py` |
| **Required** | Yes (for training specific agent) | Yes (for API server) |
| **Fallback** | None - must exist | None - must exist |

## Important Notes

1. **No fallback behavior:** Both training and API server will fail with clear error messages if their respective scenario files are missing

2. **Training scenario rotation:** Training can use multiple scenarios by rotating through files in the agent's scenarios directory

3. **API server requirement:** The API server ALWAYS uses `config/scenario_game.json` - never training scenarios

4. **Code examples:** Some documentation code examples may show `config/scenario.json` - this is for illustration only. In practice:
   - Training uses `config/agents/<agent>/scenarios/*.json`
   - API server uses `config/scenario_game.json`

## Diagnostics Configuration

**Location:** `config/diagnostics.json`

**Purpose:** Centralized configuration for training diagnostics, episode tracking, and scenario rotation heuristics

**Structure:**
```json
{
  "episode_tracker": {
    "indent_size": 2
  },
  "rotation": {
    "avg_episode_steps": 75,
    "target_rotations": 7
  }
}
```

### Fields

#### `episode_tracker.indent_size`
- **Type:** Integer
- **Default:** `2`
- **Purpose:** Controls JSON indentation when saving selective episode replays
- **Usage:** Used by `SelectiveEpisodeTracker.save_selective_replays()` in `ai/multi_agent_trainer.py`

#### `rotation.avg_episode_steps`
- **Type:** Integer
- **Default:** `75`
- **Purpose:** Estimated average number of timesteps per episode, used to calculate rotation intervals
- **Usage:** Used by `calculate_rotation_interval()` in `ai/training_utils.py` to ensure each rotation segment has enough episodes for at least one PPO update
- **Tuning:** If TensorBoard shows average episode length differs significantly, adjust this value accordingly

#### `rotation.target_rotations`
- **Type:** Integer
- **Default:** `7`
- **Purpose:** Target number of times to loop through all scenarios during a training phase
- **Usage:** Used by `calculate_rotation_interval()` to determine how many episodes to run per scenario before rotating
- **Tuning:**
  - **Higher values (7-10):** More episodes per scenario, more stability before rotation
  - **Lower values (4-5):** Fewer episodes per scenario, more frequent scenario changes for diversity

## Related Files

- `main.py` - Contains `load_config()` which accepts optional `scenario_path` parameter
- `services/api_server.py` - API server that loads `scenario_game.json`
- `ai/train.py` - Training script that loads agent-specific scenarios
- `ai/training_utils.py` - Uses `rotation` values for scenario rotation interval calculation
- `ai/multi_agent_trainer.py` - Uses `episode_tracker.indent_size` for replay file formatting
