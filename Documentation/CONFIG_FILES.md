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

## Related Files

- `main.py` - Contains `load_config()` which accepts optional `scenario_path` parameter
- `services/api_server.py` - API server that loads `scenario_game.json`
- `ai/train.py` - Training script that loads agent-specific scenarios
