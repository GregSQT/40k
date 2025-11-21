# train.py Refactoring Plan - Practical Implementation Guide

**Status:** Ready for Implementation
**Complexity:** Medium (4-6 hours)
**Risk Level:** Low (pure code reorganization with validation)

---

## 📊 EXECUTIVE SUMMARY

**Current State:** `train.py` is 4,229 lines containing mixed responsibilities

**Goal:** Split into 6 focused modules with flat structure for maintainability

**Approach:** Extract-then-verify pattern with incremental testing

**Timeline:** 4-6 hours in one focused session

---

## 🎯 TARGET ARCHITECTURE

### Simple Flat Structure

```
ai/
├── train.py                    # CLI + orchestration (~800 lines)
├── env_wrappers.py            # Environment wrappers (~320 lines)
├── training_callbacks.py      # Training callbacks (~1,100 lines)
├── step_logger.py             # Step logging (~380 lines)
├── bot_evaluation.py          # Bot evaluation (~220 lines)
├── training_utils.py          # Training utilities (~500 lines)
└── replay_converter.py        # Replay conversion (~530 lines)
```

**Key Decision: FLAT STRUCTURE**
- ✅ Simple imports: `from ai.env_wrappers import X`
- ✅ No nested directories to maintain
- ✅ Easy to navigate
- ✅ No `__init__.py` complexity

**Key Decision: train.py STAYS ~800 LINES**
- ✅ Keeps CLI + orchestration together
- ✅ High-level workflow visible in one file
- ✅ Not over-fragmented

---

## 📝 MODULE SPECIFICATIONS

### 1. `ai/env_wrappers.py` (~320 lines)

**Purpose:** Gym environment wrappers for training

**Extract from train.py:**
- Lines 53-175: `BotControlledEnv` class
- Lines 176-369: `SelfPlayWrapper` class

**Key Classes:**
```python
class BotControlledEnv(gym.Wrapper):
    """Bot-controlled opponent for evaluation"""

class SelfPlayWrapper(gym.Wrapper):
    """Self-play training with frozen model"""
```

**Dependencies:**
- `gymnasium as gym`
- `ai.evaluation_bots` (RandomBot, GreedyBot, DefensiveBot)
- `ai.unit_registry.UnitRegistry`

**Exports:**
```python
__all__ = ['BotControlledEnv', 'SelfPlayWrapper']
```

**Risk:** 🟢 LOW - Self-contained with clear dependencies

---

### 2. `ai/training_callbacks.py` (~1,100 lines)

**Purpose:** Stable-Baselines3 training callbacks

**Extract from train.py:**
- Lines 370-399: `EntropyScheduleCallback`
- Lines 400-560: `EpisodeTerminationCallback`
- Lines 561-730: `EpisodeBasedEvalCallback`
- Lines 731-1177: `MetricsCollectionCallback`
- Lines 1398-1515: `BotEvaluationCallback`

**Key Classes:**
```python
class EntropyScheduleCallback(BaseCallback):
    """Dynamic entropy coefficient scheduling"""

class EpisodeTerminationCallback(BaseCallback):
    """Episode-based training termination"""

class EpisodeBasedEvalCallback(BaseCallback):
    """Episode-counting evaluation"""

class MetricsCollectionCallback(BaseCallback):
    """Comprehensive metrics collection"""

class BotEvaluationCallback(BaseCallback):
    """Bot evaluation during training"""
```

**Dependencies:**
- `stable_baselines3.common.callbacks.BaseCallback`
- `ai.metrics_tracker.W40KMetricsTracker`
- `ai.bot_evaluation.evaluate_against_bots` (⚠️ circular - use lazy import)

**Exports:**
```python
__all__ = [
    'EntropyScheduleCallback',
    'EpisodeTerminationCallback',
    'EpisodeBasedEvalCallback',
    'MetricsCollectionCallback',
    'BotEvaluationCallback'
]
```

**Risk:** 🟡 MEDIUM - Circular dependency with bot_evaluation (resolved via lazy import)

**Critical Note:** MetricsCollectionCallback validates AI_TURN.md compliance - preserve exactly!

---

### 3. `ai/step_logger.py` (~380 lines)

**Purpose:** Step-by-step action logging for replay generation

**Extract from train.py:**
- Lines 1516-1896: `StepLogger` class

**Key Class:**
```python
class StepLogger:
    """
    Step-by-step action logger for training debugging.
    Captures ALL actions that generate step increments per AI_TURN.md.
    """
```

**Dependencies:**
- Standard library only (`time`, `os`, `json`)

**Exports:**
```python
__all__ = ['StepLogger']
```

**Risk:** 🟢 LOW - No external dependencies

**⚠️ CRITICAL:** This class is imported by `ai/multi_agent_trainer.py`
- **Action Required:** Update import after extraction:
  ```python
  # OLD: from ai.train import StepLogger
  # NEW: from ai.step_logger import StepLogger
  ```

---

### 4. `ai/bot_evaluation.py` (~220 lines)

**Purpose:** Bot evaluation system for training assessment

**Extract from train.py:**
- Lines 1178-1397: `evaluate_against_bots()` function

**Key Function:**
```python
def evaluate_against_bots(
    model,
    training_config_name: str,
    rewards_config_name: str,
    n_episodes: int = 50,
    controlled_agent: Optional[str] = None,
    show_progress: bool = True
) -> Dict[str, float]:
    """
    Evaluate model against RandomBot, GreedyBot, DefensiveBot.
    Returns win rates and combined score.
    """
```

**Dependencies:**
- `ai.env_wrappers.BotControlledEnv` (⚠️ circular - use lazy import)
- `ai.evaluation_bots` (RandomBot, GreedyBot, DefensiveBot)
- `config_loader.get_config_loader`

**Exports:**
```python
__all__ = ['evaluate_against_bots']
```

**Risk:** 🔴 HIGH - Circular dependency with env_wrappers

**Mitigation:**
```python
def evaluate_against_bots(...):
    # Lazy import to avoid circular dependency
    from ai.env_wrappers import BotControlledEnv
    ...
```

---

### 5. `ai/training_utils.py` (~500 lines)

**Purpose:** Training utility functions

**Extract from train.py:**
- Lines 1897-1924: `check_gpu_availability()`
- Lines 1925-1939: `setup_imports()`
- Lines 1940-1993: `make_training_env()`
- Lines 2216-2257 OR 2338-2394: `get_agent_scenario_file()` ⚠️ DUPLICATE - see below
- Lines 2259-2337: `get_scenario_list_for_phase()`
- Lines 2395-2417: `calculate_rotation_interval()`
- Lines 3876-3881: `ensure_scenario()`

**⚠️ CRITICAL ISSUE: Duplicate Function**

`get_agent_scenario_file()` is defined TWICE:
- **Version 1:** Lines 2216-2257 (42 lines) - basic version
- **Version 2:** Lines 2338-2394 (56 lines) - has `scenario_override` parameter

**Resolution:** Keep Version 2 (more complete), delete Version 1

**Key Functions:**
```python
def check_gpu_availability() -> bool:
    """Check CUDA availability"""

def make_training_env(rank, scenario_file, ...):
    """Create training environment for vectorization"""

def get_agent_scenario_file(config, agent_key, training_config_name, scenario_override=None):
    """Get scenario file path for agent"""

def get_scenario_list_for_phase(config, agent_key, training_config_name, scenario_type=None):
    """Discover all scenarios for agent/phase"""
```

**Dependencies:**
- `ai.env_wrappers` (BotControlledEnv, SelfPlayWrapper)
- `ai.unit_registry.UnitRegistry`
- `config_loader.get_config_loader`

**Exports:**
```python
__all__ = [
    'check_gpu_availability',
    'setup_imports',
    'make_training_env',
    'get_agent_scenario_file',
    'get_scenario_list_for_phase',
    'calculate_rotation_interval',
    'ensure_scenario'
]
```

**Risk:** 🟡 MEDIUM - Duplicate function needs resolution

---

### 6. `ai/replay_converter.py` (~530 lines)

**Purpose:** Convert step logs to frontend replay format

**Extract from train.py:**
- Lines 3293-3305: `extract_scenario_name_for_replay()`
- Lines 3306-3339: `convert_steplog_to_replay()`
- Lines 3340-3546: `generate_steplog_and_replay()`
- Lines 3547-3654: `parse_steplog_file()`
- Lines 3655-3734: `parse_action_message()`
- Lines 3735-3749: `calculate_episode_reward_from_actions()`
- Lines 3750-3875: `convert_to_replay_format()`

**Key Functions:**
```python
def convert_steplog_to_replay(steplog_path: str) -> bool:
    """Convert train_step.log to frontend replay format"""

def parse_steplog_file(steplog_path: str) -> Dict:
    """Parse steplog file into structured data"""

def convert_to_replay_format(steplog_data: Dict) -> Dict:
    """Convert parsed steplog to frontend JSON format"""
```

**Dependencies:**
- `ai.step_logger.StepLogger`
- `ai.game_replay_logger.GameReplayIntegration`
- `config_loader.get_config_loader`
- Standard library (`json`, `os`, `re`, `pathlib`)

**Exports:**
```python
__all__ = [
    'convert_steplog_to_replay',
    'generate_steplog_and_replay',
    'extract_scenario_name_for_replay'
]
```

**Risk:** 🟢 LOW - Self-contained utilities

---

### 7. `ai/train.py` (UPDATED - ~800 lines)

**Purpose:** CLI orchestration and main training workflow

**Keeps:**
- Lines 1-52: Imports (updated to use new modules)
- Lines 1994-2215: `create_model()` - model creation
- Lines 2418-2589: `create_multi_agent_model()` - multi-agent model creation
- Lines 2590-2931: `train_with_scenario_rotation()` - scenario rotation logic
- Lines 2932-3046: `setup_callbacks()` - callback setup
- Lines 3047-3176: `train_model()` - training execution
- Lines 3177-3233: `test_trained_model()` - post-training testing
- Lines 3234-3271: `test_scenario_manager_integration()` - integration test
- Lines 3272-3292: `start_multi_agent_orchestration()` - multi-agent orchestration
- Lines 3882-4229: `main()` - CLI argument parsing and entry point

**Updated Imports:**
```python
# Environment wrappers
from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper

# Training callbacks
from ai.training_callbacks import (
    EntropyScheduleCallback,
    EpisodeTerminationCallback,
    EpisodeBasedEvalCallback,
    MetricsCollectionCallback,
    BotEvaluationCallback
)

# Step logger
from ai.step_logger import StepLogger

# Bot evaluation
from ai.bot_evaluation import evaluate_against_bots

# Training utilities
from ai.training_utils import (
    check_gpu_availability,
    setup_imports,
    make_training_env,
    get_agent_scenario_file,
    get_scenario_list_for_phase,
    calculate_rotation_interval,
    ensure_scenario
)

# Replay conversion
from ai.replay_converter import (
    convert_steplog_to_replay,
    generate_steplog_and_replay
)
```

**Why Keep ~800 Lines:**
- ✅ Model creation logic stays with orchestration
- ✅ Training loops visible in one place
- ✅ Clear entry point for understanding workflow
- ✅ Not over-fragmented

---

## 🔧 IMPLEMENTATION PHASES

### Phase 1: Pre-Flight Checks (20 min)

**Goal:** Ensure current code works before changes

1. **Create feature branch:**
   ```bash
   git checkout -b refactor/split-train-py
   ```

2. **Run baseline test:**
   ```bash
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config default --episodes 10
   ```

3. **Create backup:**
   ```bash
   cp ai/train.py ai/train_backup_$(date +%Y%m%d).py
   ```

4. **Check import dependencies:**
   ```bash
   grep -r "from ai.train import" . --include="*.py"
   # Expected: ai/multi_agent_trainer.py imports StepLogger
   ```

**Success Criteria:**
- ✅ Git branch created
- ✅ Baseline test passes
- ✅ Backup created
- ✅ Import dependencies documented

---

### Phase 2: Extract Environment Wrappers (30 min)

**Goal:** Create `ai/env_wrappers.py`

1. **Create new file with header:**
   ```python
   #!/usr/bin/env python3
   """
   ai/env_wrappers.py - Gym environment wrappers for training

   Contains:
   - BotControlledEnv: Bot-controlled opponent wrapper
   - SelfPlayWrapper: Self-play training wrapper
   """

   import gymnasium as gym
   from typing import Optional, Any, Dict
   import numpy as np

   from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
   from ai.unit_registry import UnitRegistry
   ```

2. **Copy classes:**
   - Copy lines 53-175 (`BotControlledEnv`)
   - Copy lines 176-369 (`SelfPlayWrapper`)

3. **Add exports:**
   ```python
   __all__ = ['BotControlledEnv', 'SelfPlayWrapper']
   ```

4. **Test import:**
   ```bash
   python -c "from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper; print('OK')"
   ```

5. **Update train.py:**
   - Add import: `from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper`
   - Delete lines 53-369

6. **Test training still works:**
   ```bash
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 5
   ```

7. **Commit:**
   ```bash
   git add ai/env_wrappers.py ai/train.py
   git commit -m "refactor: extract environment wrappers to env_wrappers.py"
   ```

**Success Criteria:**
- ✅ env_wrappers.py imports successfully
- ✅ train.py still works
- ✅ Git commit created

---

### Phase 3: Extract Step Logger (30 min)

**Goal:** Create `ai/step_logger.py`

1. **Create new file:**
   ```python
   #!/usr/bin/env python3
   """
   ai/step_logger.py - Step-by-step action logging

   Step-by-step action logger for training debugging.
   Captures ALL actions that generate step increments per AI_TURN.md.
   """

   import time
   import json
   import os
   from typing import Dict, Any, Optional
   ```

2. **Copy class:**
   - Copy lines 1516-1896 (`StepLogger`)

3. **Add exports:**
   ```python
   __all__ = ['StepLogger']
   ```

4. **Test import:**
   ```bash
   python -c "from ai.step_logger import StepLogger; print('OK')"
   ```

5. **Update train.py:**
   - Add import: `from ai.step_logger import StepLogger`
   - Delete lines 1516-1896

6. **⚠️ CRITICAL: Update multi_agent_trainer.py:**
   ```bash
   # Find line with: from ai.train import StepLogger
   # Replace with: from ai.step_logger import StepLogger
   ```

7. **Test multi-agent import:**
   ```bash
   python -c "from ai.multi_agent_trainer import MultiAgentTrainer; print('OK')"
   ```

8. **Commit:**
   ```bash
   git add ai/step_logger.py ai/train.py ai/multi_agent_trainer.py
   git commit -m "refactor: extract StepLogger to step_logger.py

BREAKING: Updates import in multi_agent_trainer.py
OLD: from ai.train import StepLogger
NEW: from ai.step_logger import StepLogger"
   ```

**Success Criteria:**
- ✅ step_logger.py imports successfully
- ✅ multi_agent_trainer.py updated
- ✅ No import errors

---

### Phase 4: Extract Bot Evaluation (40 min)

**Goal:** Create `ai/bot_evaluation.py`

1. **Create new file:**
   ```python
   #!/usr/bin/env python3
   """
   ai/bot_evaluation.py - Bot evaluation system

   Standalone bot evaluation for training progress assessment.
   """

   import os
   from typing import Dict, Optional, Any
   import numpy as np

   from stable_baselines3.common.monitor import Monitor
   from sb3_contrib.common.wrappers import ActionMasker

   from config_loader import get_config_loader
   from ai.unit_registry import UnitRegistry
   from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
   ```

2. **Copy function:**
   - Copy lines 1178-1397 (`evaluate_against_bots`)

3. **⚠️ Handle circular dependency:**
   ```python
   def evaluate_against_bots(...):
       # Lazy import to avoid circular dependency with env_wrappers
       from ai.env_wrappers import BotControlledEnv

       # ... rest of function
   ```

4. **Add exports:**
   ```python
   __all__ = ['evaluate_against_bots']
   ```

5. **Test import:**
   ```bash
   python -c "from ai.bot_evaluation import evaluate_against_bots; print('OK')"
   ```

6. **Update train.py:**
   - Add import: `from ai.bot_evaluation import evaluate_against_bots`
   - Delete lines 1178-1397

7. **Test training with bot evaluation:**
   ```bash
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 5 --test-episodes 10
   ```

8. **Commit:**
   ```bash
   git add ai/bot_evaluation.py ai/train.py
   git commit -m "refactor: extract bot evaluation to bot_evaluation.py

Uses lazy import to resolve circular dependency with env_wrappers"
   ```

**Success Criteria:**
- ✅ bot_evaluation.py imports successfully
- ✅ No circular import errors
- ✅ Bot evaluation still works

---

### Phase 5: Extract Training Callbacks (45 min)

**Goal:** Create `ai/training_callbacks.py`

1. **Create new file:**
   ```python
   #!/usr/bin/env python3
   """
   ai/training_callbacks.py - Training callbacks for SB3

   Contains:
   - EntropyScheduleCallback
   - EpisodeTerminationCallback
   - EpisodeBasedEvalCallback
   - MetricsCollectionCallback
   - BotEvaluationCallback
   """

   import os
   import time
   from typing import Optional, Dict, Any, List
   from collections import deque
   import numpy as np

   from stable_baselines3.common.callbacks import BaseCallback
   from stable_baselines3.common.monitor import Monitor

   from ai.metrics_tracker import W40KMetricsTracker
   from ai.unit_registry import UnitRegistry
   from ai.env_wrappers import BotControlledEnv
   ```

2. **Copy classes:**
   - Copy lines 370-399 (`EntropyScheduleCallback`)
   - Copy lines 400-560 (`EpisodeTerminationCallback`)
   - Copy lines 561-730 (`EpisodeBasedEvalCallback`)
   - Copy lines 731-1177 (`MetricsCollectionCallback`)
   - Copy lines 1398-1515 (`BotEvaluationCallback`)

3. **⚠️ Handle circular dependency in BotEvaluationCallback:**
   ```python
   class BotEvaluationCallback(BaseCallback):
       def _on_step(self):
           # Lazy import to avoid circular dependency
           from ai.bot_evaluation import evaluate_against_bots
           results = evaluate_against_bots(...)
   ```

4. **Add exports:**
   ```python
   __all__ = [
       'EntropyScheduleCallback',
       'EpisodeTerminationCallback',
       'EpisodeBasedEvalCallback',
       'MetricsCollectionCallback',
       'BotEvaluationCallback'
   ]
   ```

5. **Test import:**
   ```bash
   python -c "from ai.training_callbacks import MetricsCollectionCallback; print('OK')"
   ```

6. **Update train.py:**
   - Add imports for all callbacks
   - Delete lines 370-1515

7. **Test training with callbacks:**
   ```bash
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 10
   ```

8. **Verify TensorBoard metrics:**
   ```bash
   # Check that tensorboard logs are still generated
   ls -la tensorboard_logs/
   ```

9. **Commit:**
   ```bash
   git add ai/training_callbacks.py ai/train.py
   git commit -m "refactor: extract training callbacks to training_callbacks.py

Includes all 5 callback classes with lazy imports for circular deps"
   ```

**Success Criteria:**
- ✅ All callbacks import successfully
- ✅ Training with metrics still works
- ✅ TensorBoard logs generated

---

### Phase 6: Extract Training Utilities (45 min)

**Goal:** Create `ai/training_utils.py`

1. **Create new file:**
   ```python
   #!/usr/bin/env python3
   """
   ai/training_utils.py - Training utility functions

   Contains:
   - GPU detection
   - Environment creation
   - Scenario management
   - Training helpers
   """

   import os
   import sys
   import json
   import torch
   from pathlib import Path
   from typing import Optional, List, Dict, Any

   import gymnasium as gym
   from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv
   from stable_baselines3.common.monitor import Monitor

   from config_loader import get_config_loader
   from ai.unit_registry import UnitRegistry
   from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper
   from ai.evaluation_bots import GreedyBot
   ```

2. **Copy functions:**
   - Copy lines 1897-1924 (`check_gpu_availability`)
   - Copy lines 1925-1939 (`setup_imports`)
   - Copy lines 1940-1993 (`make_training_env`)
   - Copy lines 2259-2337 (`get_scenario_list_for_phase`)
   - **Copy lines 2338-2394** (`get_agent_scenario_file` - VERSION 2 with scenario_override)
   - Copy lines 2395-2417 (`calculate_rotation_interval`)
   - Copy lines 3876-3881 (`ensure_scenario`)

3. **⚠️ DELETE duplicate function:**
   - Do NOT copy lines 2216-2257 (duplicate version of `get_agent_scenario_file`)

4. **Add exports:**
   ```python
   __all__ = [
       'check_gpu_availability',
       'setup_imports',
       'make_training_env',
       'get_agent_scenario_file',
       'get_scenario_list_for_phase',
       'calculate_rotation_interval',
       'ensure_scenario'
   ]
   ```

5. **Test import:**
   ```bash
   python -c "from ai.training_utils import check_gpu_availability, get_agent_scenario_file; print('OK')"
   ```

6. **Update train.py:**
   - Add imports for all utility functions
   - Delete lines 1897-1993, 2216-2417, 3876-3881

7. **Test scenario rotation:**
   ```bash
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --scenario self --episodes 10
   ```

8. **Commit:**
   ```bash
   git add ai/training_utils.py ai/train.py
   git commit -m "refactor: extract training utilities to training_utils.py

Resolved duplicate get_agent_scenario_file() - kept version with scenario_override"
   ```

**Success Criteria:**
- ✅ Utility functions import successfully
- ✅ Duplicate function resolved
- ✅ Scenario rotation works

---

### Phase 7: Extract Replay Converter (40 min)

**Goal:** Create `ai/replay_converter.py`

1. **Create new file:**
   ```python
   #!/usr/bin/env python3
   """
   ai/replay_converter.py - Replay conversion utilities

   Converts training steplogs to frontend-compatible replay format.
   """

   import os
   import json
   import re
   from typing import Dict, List, Optional, Any
   from pathlib import Path

   from config_loader import get_config_loader
   from ai.game_replay_logger import GameReplayIntegration
   from ai.unit_registry import UnitRegistry
   from ai.step_logger import StepLogger
   ```

2. **Copy functions:**
   - Copy lines 3293-3305 (`extract_scenario_name_for_replay`)
   - Copy lines 3306-3339 (`convert_steplog_to_replay`)
   - Copy lines 3340-3546 (`generate_steplog_and_replay`)
   - Copy lines 3547-3654 (`parse_steplog_file`)
   - Copy lines 3655-3734 (`parse_action_message`)
   - Copy lines 3735-3749 (`calculate_episode_reward_from_actions`)
   - Copy lines 3750-3875 (`convert_to_replay_format`)

3. **Add exports:**
   ```python
   __all__ = [
       'convert_steplog_to_replay',
       'generate_steplog_and_replay',
       'extract_scenario_name_for_replay'
   ]
   ```

4. **Test import:**
   ```bash
   python -c "from ai.replay_converter import convert_steplog_to_replay; print('OK')"
   ```

5. **Update train.py:**
   - Add imports: `from ai.replay_converter import convert_steplog_to_replay, generate_steplog_and_replay`
   - Delete lines 3293-3875

6. **Test replay conversion (if steplog exists):**
   ```bash
   # Generate a steplog first
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 5

   # Then convert it
   python ai/train.py --convert-steplog ai/event_log/training_step.log
   ```

7. **Commit:**
   ```bash
   git add ai/replay_converter.py ai/train.py
   git commit -m "refactor: extract replay converter to replay_converter.py"
   ```

**Success Criteria:**
- ✅ Replay converter imports successfully
- ✅ Steplog conversion works
- ✅ Generated replays valid

---

### Phase 8: Finalize train.py (20 min)

**Goal:** Verify train.py structure and test all functionality

1. **Check train.py final size:**
   ```bash
   wc -l ai/train.py
   # Expected: ~800-900 lines
   ```

2. **Verify imports section:**
   ```python
   # Should have imports from all new modules
   from ai.env_wrappers import ...
   from ai.training_callbacks import ...
   from ai.step_logger import ...
   from ai.bot_evaluation import ...
   from ai.training_utils import ...
   from ai.replay_converter import ...
   ```

3. **Test all training modes:**
   ```bash
   # Basic training
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 10

   # New model
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --new --episodes 10

   # Bot evaluation
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --test-episodes 20

   # Scenario rotation
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --scenario self --episodes 10
   ```

4. **Final commit:**
   ```bash
   git add ai/train.py
   git commit -m "refactor: finalize train.py after module extraction

train.py now ~800 lines with clear orchestration focus"
   ```

**Success Criteria:**
- ✅ train.py is 800-900 lines
- ✅ All imports correct
- ✅ All training modes work
- ✅ No functionality lost

---

### Phase 9: Final Validation (30 min)

**Goal:** Comprehensive validation before merge

1. **Test import matrix:**
   ```python
   # Test all modules import independently
   python -c "from ai.env_wrappers import BotControlledEnv; print('env_wrappers OK')"
   python -c "from ai.training_callbacks import MetricsCollectionCallback; print('callbacks OK')"
   python -c "from ai.step_logger import StepLogger; print('step_logger OK')"
   python -c "from ai.bot_evaluation import evaluate_against_bots; print('bot_evaluation OK')"
   python -c "from ai.training_utils import check_gpu_availability; print('training_utils OK')"
   python -c "from ai.replay_converter import convert_steplog_to_replay; print('replay_converter OK')"
   ```

2. **Check for circular imports:**
   ```bash
   python -c "
   import ai.env_wrappers
   import ai.training_callbacks
   import ai.bot_evaluation
   import ai.training_utils
   import ai.replay_converter
   import ai.step_logger
   import ai.train
   print('No circular import errors')
   "
   ```

3. **Compare file sizes:**
   ```bash
   echo "Before refactoring:"
   wc -l ai/train_backup_*.py

   echo -e "\nAfter refactoring:"
   wc -l ai/train.py
   wc -l ai/env_wrappers.py
   wc -l ai/training_callbacks.py
   wc -l ai/step_logger.py
   wc -l ai/bot_evaluation.py
   wc -l ai/training_utils.py
   wc -l ai/replay_converter.py
   ```

4. **Run regression tests:**
   ```bash
   # Phase 1 training
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase1 --episodes 100

   # Bot evaluation
   python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --test-episodes 50

   # Multi-agent (if applicable)
   python ai/train.py --multi-agent --episodes 100
   ```

5. **Git status:**
   ```bash
   git status
   git log --oneline -10
   ```

6. **Create summary commit:**
   ```bash
   git add -A
   git commit -m "refactor: complete train.py modularization

Split 4,229-line train.py into 6 focused modules:
- env_wrappers.py: Environment wrappers (320 lines)
- training_callbacks.py: Training callbacks (1,100 lines)
- step_logger.py: Step logging (380 lines)
- bot_evaluation.py: Bot evaluation (220 lines)
- training_utils.py: Training utilities (500 lines)
- replay_converter.py: Replay conversion (530 lines)
- train.py: CLI + orchestration (800 lines)

Changes:
- Flat module structure for simple imports
- Lazy imports resolve circular dependencies
- Updated multi_agent_trainer.py StepLogger import
- Resolved duplicate get_agent_scenario_file()
- All functionality preserved and tested

Total: 3,850 lines (same as original, just organized)"
   ```

**Success Criteria:**
- ✅ All modules import without errors
- ✅ No circular import errors
- ✅ All regression tests pass
- ✅ Git history clean

---

## 🔍 CRITICAL ISSUES & RESOLUTIONS

### Issue 1: Duplicate Function
**Problem:** `get_agent_scenario_file()` defined twice (lines 2216 and 2338)

**Resolution:** Keep version at lines 2338-2394 (has `scenario_override` parameter)

**Action:** Delete lines 2216-2257 when extracting to training_utils.py

---

### Issue 2: Circular Dependencies
**Problem:** `bot_evaluation.py` ↔ `env_wrappers.py` circular import

**Resolution:** Lazy imports inside functions

**Example:**
```python
# In bot_evaluation.py
def evaluate_against_bots(...):
    # Import here, not at module level
    from ai.env_wrappers import BotControlledEnv
    ...
```

---

### Issue 3: StepLogger External Import
**Problem:** `ai/multi_agent_trainer.py` imports StepLogger from train.py

**Resolution:** Update import after extraction

**Action:**
```bash
# Find and replace in multi_agent_trainer.py
OLD: from ai.train import StepLogger
NEW: from ai.step_logger import StepLogger
```

---

### Issue 4: MetricsCollectionCallback AI_TURN.md Compliance
**Problem:** Callback validates game state per AI_TURN.md - must preserve exactly

**Resolution:** Copy class unchanged, verify metrics still logged

**Validation:**
```bash
# After extraction, check TensorBoard logs
tensorboard --logdir tensorboard_logs
# Verify all metrics present
```

---

## 📊 SUCCESS METRICS

### Quantitative Goals
- ✅ Reduce train.py from 4,229 to ~800 lines (81% reduction in monolith)
- ✅ Create 6 focused modules each 200-1,100 lines
- ✅ Maintain 100% functionality (all tests pass)
- ✅ Zero performance regression
- ✅ Zero import errors

### Qualitative Goals
- ✅ Simpler imports (flat structure: `from ai.module import X`)
- ✅ Clear module responsibilities (one purpose per file)
- ✅ Easy navigation (no nested directories)
- ✅ Preserved cohesion (orchestration stays in train.py)

---

## ⚡ ROLLBACK STRATEGY

### If Something Goes Wrong

**Option 1: Revert specific phase**
```bash
git log --oneline
git revert <commit-hash>
```

**Option 2: Complete rollback**
```bash
cp ai/train_backup_YYYYMMDD.py ai/train.py
git checkout main
git branch -D refactor/split-train-py
```

**Option 3: Keep partial refactor**
```bash
# Keep working modules, revert broken ones
git reset --hard <last-working-commit>
```

---

## 📝 VALIDATION CHECKLIST

Before considering refactor complete:

**Code Quality:**
- [ ] All 6 new modules created
- [ ] Each module has docstring
- [ ] Each module has `__all__` exports
- [ ] train.py updated with new imports
- [ ] No duplicate code

**Functionality:**
- [ ] Basic training works
- [ ] New model creation works
- [ ] Bot evaluation works
- [ ] Scenario rotation works
- [ ] Replay conversion works
- [ ] Multi-agent training works (if applicable)

**Imports:**
- [ ] All modules import independently
- [ ] No circular import errors
- [ ] multi_agent_trainer.py updated

**Testing:**
- [ ] All import tests pass
- [ ] All regression tests pass
- [ ] TensorBoard metrics generated
- [ ] No error logs

**Git:**
- [ ] All changes committed
- [ ] Commit messages descriptive
- [ ] Backup file preserved

---

## 🎯 TIMELINE ESTIMATE

| Phase | Task | Time | Cumulative |
|-------|------|------|------------|
| 1 | Pre-flight checks | 20 min | 0:20 |
| 2 | Extract env_wrappers | 30 min | 0:50 |
| 3 | Extract step_logger | 30 min | 1:20 |
| 4 | Extract bot_evaluation | 40 min | 2:00 |
| 5 | Extract training_callbacks | 45 min | 2:45 |
| 6 | Extract training_utils | 45 min | 3:30 |
| 7 | Extract replay_converter | 40 min | 4:10 |
| 8 | Finalize train.py | 20 min | 4:30 |
| 9 | Final validation | 30 min | **5:00** |

**Total: 4-6 hours** (one focused session)

---

## 🏆 WHY THIS APPROACH WORKS

### ✅ **Pragmatic Module Count**
- 6 modules is the sweet spot (not too few, not too many)
- Each module 200-1,100 lines - readable

### ✅ **Flat Structure**
- No nested directories (`ai/training/`, `ai/diagnostics/`)
- Simple imports: `from ai.module import X`
- No `__init__.py` management

### ✅ **Preserves Cohesion**
- train.py stays ~800 lines with orchestration
- High-level workflow visible in one file
- Not over-fragmented

### ✅ **Realistic Timeline**
- Can be done in one focused day
- Clear phases with validation
- Less context-switching

### ✅ **Honest Risk Assessment**
- Flags circular dependencies explicitly
- Provides concrete mitigation (lazy imports)
- Doesn't overpromise

---

## 📚 REFERENCES

- **AI_TURN.md**: Game loop architecture (MetricsCollectionCallback validates this)
- **AI_TRAINING.md**: Training configuration guide
- **AI_IMPLEMENTATION.md**: Implementation patterns

---

**Document Version:** 2.0 (Synthesized Best-of-Breed)
**Created:** 2025-01-20
**Status:** Ready for Implementation
**Complexity:** Medium
**Risk:** Low
**Timeline:** 4-6 hours
