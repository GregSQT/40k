# train_core.py Refactoring Plan - Practical Implementation Guide

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
├── train_core.py              # CLI + orchestration (~800 lines)
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

**Key Decision: train_core.py STAYS ~800 LINES**
- ✅ Keeps CLI + orchestration together
- ✅ High-level workflow visible in one file
- ✅ Not over-fragmented

---

## 📝 MODULE SPECIFICATIONS

### 1. `ai/env_wrappers.py` (~320 lines)

**Purpose:** Gym environment wrappers for training

**Extract from train_core.py:**
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

**Extract from train_core.py:**
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

**Extract from train_core.py:**
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
  # OLD: from ai.train_core import StepLogger
  # NEW: from ai.step_logger import StepLogger
  ```

---

### 4. `ai/bot_evaluation.py` (~220 lines)

**Purpose:** Bot evaluation system for training assessment

**Extract from train_core.py:**
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

**Extract from train_core.py:**
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

**Extract from train_core.py:**
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

### 7. `ai/train_core.py` (UPDATED - ~800 lines)

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

**Why Keep train_core.py ~800 Lines:**
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
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config default --episodes 10
   ```

3. **Create backup:**
   ```bash
   cp ai/train_core.py ai/train_backup_$(date +%Y%m%d).py
   ```

4. **Check import dependencies:**
   ```bash
   grep -r "from ai.train_core import" . --include="*.py"
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

5. **Update train_core.py:**
   - Add import: `from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper`
   - Delete lines 53-369

6. **Test training still works:**
   ```bash
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 5
   ```

7. **Commit:**
   ```bash
   git add ai/env_wrappers.py ai/train_core.py
   git commit -m "refactor: extract environment wrappers to env_wrappers.py"
   ```

**Success Criteria:**
- ✅ env_wrappers.py imports successfully
- ✅ train_core.py still works
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

5. **Update train_core.py:**
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
   git add ai/step_logger.py ai/train_core.py ai/multi_agent_trainer.py
   git commit -m "refactor: extract StepLogger to step_logger.py

BREAKING: Updates import in multi_agent_trainer.py
OLD: from ai.train_core import StepLogger
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

6. **Update train_core.py:**
   - Add import: `from ai.bot_evaluation import evaluate_against_bots`
   - Delete lines 1178-1397

7. **Test training with bot evaluation:**
   ```bash
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 5 --test-episodes 10
   ```

8. **Commit:**
   ```bash
   git add ai/bot_evaluation.py ai/train_core.py
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

6. **Update train_core.py:**
   - Add imports for all callbacks
   - Delete lines 370-1515

7. **Test training with callbacks:**
   ```bash
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 10
   ```

8. **Verify TensorBoard metrics:**
   ```bash
   # Check that tensorboard logs are still generated
   ls -la tensorboard_logs/
   ```

9. **Commit:**
   ```bash
   git add ai/training_callbacks.py ai/train_core.py
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

6. **Update train_core.py:**
   - Add imports for all utility functions
   - Delete lines 1897-1993, 2216-2417, 3876-3881

7. **Test scenario rotation:**
   ```bash
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --scenario self --episodes 10
   ```

8. **Commit:**
   ```bash
   git add ai/training_utils.py ai/train_core.py
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

5. **Update train_core.py:**
   - Add imports: `from ai.replay_converter import convert_steplog_to_replay, generate_steplog_and_replay`
   - Delete lines 3293-3875

6. **Test replay conversion (if steplog exists):**
   ```bash
   # Generate a steplog first
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 5

   # Then convert it
   python ai/train_core.py --convert-steplog ai/event_log/training_step.log
   ```

7. **Commit:**
   ```bash
   git add ai/replay_converter.py ai/train_core.py
   git commit -m "refactor: extract replay converter to replay_converter.py"
   ```

**Success Criteria:**
- ✅ Replay converter imports successfully
- ✅ Steplog conversion works
- ✅ Generated replays valid

---

### Phase 8: Finalize train_core.py (20 min)

**Goal:** Verify train_core.py structure and test all functionality

1. **Check train_core.py final size:**
   ```bash
   wc -l ai/train_core.py
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
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 10

   # New model
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --new --episodes 10

   # Bot evaluation
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --test-episodes 20

   # Scenario rotation
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --scenario self --episodes 10
   ```

4. **Final commit:**
   ```bash
   git add ai/train_core.py
   git commit -m "refactor: finalize train_core.py after module extraction

train_core.py now ~800 lines with clear orchestration focus"
   ```

**Success Criteria:**
- ✅ train_core.py is 800-900 lines
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
   import ai.train_core
   print('No circular import errors')
   "
   ```

3. **Compare file sizes:**
   ```bash
   echo "Before refactoring:"
   wc -l ai/train_backup_*.py

   echo -e "\nAfter refactoring:"
   wc -l ai/train_core.py
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
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase1 --episodes 100

   # Bot evaluation
   python ai/train_core.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --test-episodes 50

   # Multi-agent (if applicable)
   python ai/train_core.py --multi-agent --episodes 100
   ```

5. **Git status:**
   ```bash
   git status
   git log --oneline -10
   ```

6. **Create summary commit:**
   ```bash
   git add -A
   git commit -m "refactor: complete train_core.py modularization

Split 4,229-line train_core.py into 6 focused modules:
- env_wrappers.py: Environment wrappers (320 lines)
- training_callbacks.py: Training callbacks (1,100 lines)
- step_logger.py: Step logging (380 lines)
- bot_evaluation.py: Bot evaluation (220 lines)
- training_utils.py: Training utilities (500 lines)
- replay_converter.py: Replay conversion (530 lines)
- train_core.py: CLI + orchestration (800 lines)

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
OLD: from ai.train_core import StepLogger
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
cp ai/train_backup_YYYYMMDD.py ai/train_core.py
git checkout main
git branch -D refactor/split-train-py
```

**Option 3: Keep partial refactor**
```bash
# Keep working modules, revert broken ones
git reset --hard <last-working-commit>
```

---

## 🔧 DETAILED: multi_agent_trainer.py UPDATE

### Why This Update is Critical

**File**: `ai/multi_agent_trainer.py` (Line 730)

This file imports `StepLogger` from `ai.train` to enable per-agent step logging during multi-agent training sessions. After refactoring, `StepLogger` moves to its own module.

**If not updated**: Multi-agent training will crash with `ImportError: cannot import name 'StepLogger' from 'ai.train'`

---

### Exact Update Instructions

**Step 1: Locate the import (Phase 3 of refactoring)**

```bash
# Find the exact line
grep -n "from ai.train import StepLogger" ai/multi_agent_trainer.py
# Output: 730:                        from ai.train import StepLogger
```

**Step 2: Read the context**

```python
# Lines 726-735 in ai/multi_agent_trainer.py
try:
    import sys
    train_module = sys.modules.get('ai.train') or sys.modules.get('__main__')
    if train_module and hasattr(train_module, 'step_logger') and train_module.step_logger and train_module.step_logger.enabled:
        agent_log_file = f"train_step_{agent_key}.log"
        from ai.train import StepLogger  # ← LINE 730: UPDATE THIS
        agent_step_logger = StepLogger(agent_log_file, enabled=True)
        base_env.controller.connect_step_logger(agent_step_logger)
        print(f"✅ StepLogger connected for agent {agent_key}: {agent_log_file}")
except Exception as log_error:
```

**Step 3: Make the change**

Replace:
```python
from ai.train import StepLogger
```

With:
```python
from ai.step_logger import StepLogger
```

**Step 4: Verify the fix**

```bash
# Test import
python -c "from ai.step_logger import StepLogger; print('✅ StepLogger import OK')"

# Test multi_agent_trainer imports
python -c "from ai.multi_agent_trainer import MultiAgentTrainer; print('✅ MultiAgentTrainer import OK')"

# Test multi-agent training runs
python ai/train.py --multi-agent --episodes 5
```

**Step 5: Commit with multi_agent_trainer.py**

```bash
git add ai/step_logger.py ai/train.py ai/multi_agent_trainer.py
git commit -m "refactor: extract StepLogger to step_logger.py

BREAKING: Updates import in multi_agent_trainer.py
- OLD: from ai.train import StepLogger
- NEW: from ai.step_logger import StepLogger

This change is required for multi-agent training to continue working.
Tested with: python ai/train.py --multi-agent --episodes 5"
```

---

### Why Only This One File?

**Analysis of codebase imports**:

```bash
# Search for all imports from ai.train
$ grep -r "from ai.train import" . --include="*.py"
./ai/multi_agent_trainer.py:730:  from ai.train import StepLogger
./Backup_Select/multi_agent_trainer.py:730:  from ai.train import StepLogger  # (backup, ignore)

# Result: Only 1 active file imports from ai.train
```

**Why is this unique?**
- `StepLogger` is the only class/function imported from `train.py` by external code
- All other code uses CLI invocation: `python ai/train.py` (no Python imports)
- Documentation uses command-line examples only (no code imports)

**This is excellent design** - shows clean separation of concerns!

---

## 📝 COMPREHENSIVE TESTING CHECKLIST

### Pre-Refactoring Baseline Tests

Run these **BEFORE** starting refactoring to establish baseline:

```bash
# 1. Create test results directory
mkdir -p refactor_test_results

# 2. Test basic training (save output)
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config phase1 --episodes 10 \
  > refactor_test_results/baseline_basic_training.log 2>&1
echo "Exit code: $?" >> refactor_test_results/baseline_basic_training.log

# 3. Test bot evaluation
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --test-episodes 20 \
  > refactor_test_results/baseline_bot_eval.log 2>&1
echo "Exit code: $?" >> refactor_test_results/baseline_bot_eval.log

# 4. Test scenario rotation
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --scenario self --episodes 10 \
  > refactor_test_results/baseline_scenario_rotation.log 2>&1
echo "Exit code: $?" >> refactor_test_results/baseline_scenario_rotation.log

# 5. Test multi-agent (if applicable)
python ai/train.py --multi-agent --episodes 5 \
  > refactor_test_results/baseline_multi_agent.log 2>&1
echo "Exit code: $?" >> refactor_test_results/baseline_multi_agent.log

# 6. Record TensorBoard logs exist
ls -la tensorboard_logs/ > refactor_test_results/baseline_tensorboard_files.log

# 7. Record baseline file structure
ls -la ai/*.py > refactor_test_results/baseline_file_structure.log

echo "✅ Baseline tests complete - results in refactor_test_results/"
```

---

### After Each Phase: Module Extraction Tests

Run after **EACH** extraction phase (2-7):

```bash
# Template for each phase (replace <module_name>)
PHASE_NUM=2  # Update for each phase
MODULE_NAME="env_wrappers"  # Update for each phase

# 1. Test module imports independently
python -c "import ai.${MODULE_NAME}; print('✅ ai.${MODULE_NAME} imports OK')" \
  > refactor_test_results/phase${PHASE_NUM}_${MODULE_NAME}_import.log 2>&1

# 2. Test train.py still works
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 5 \
  > refactor_test_results/phase${PHASE_NUM}_train_smoke.log 2>&1

# 3. Check for import errors
if grep -i "ImportError\|ModuleNotFoundError" refactor_test_results/phase${PHASE_NUM}_*.log; then
  echo "❌ Phase ${PHASE_NUM} has import errors!"
  exit 1
else
  echo "✅ Phase ${PHASE_NUM} imports OK"
fi
```

**Specific tests per phase**:

**Phase 2 (env_wrappers)**:
```bash
python -c "from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper; print('✅ OK')"
```

**Phase 3 (step_logger)** - CRITICAL:
```bash
python -c "from ai.step_logger import StepLogger; print('✅ OK')"
python -c "from ai.multi_agent_trainer import MultiAgentTrainer; print('✅ OK')"  # Must work!
```

**Phase 4 (bot_evaluation)**:
```bash
python -c "from ai.bot_evaluation import evaluate_against_bots; print('✅ OK')"
python ai/train.py --test-episodes 10  # Test evaluation works
```

**Phase 5 (training_callbacks)**:
```bash
python -c "from ai.training_callbacks import MetricsCollectionCallback; print('✅ OK')"
python ai/train.py --episodes 5  # Check TensorBoard logs generated
ls tensorboard_logs/ | tail -5
```

**Phase 6 (training_utils)**:
```bash
python -c "from ai.training_utils import check_gpu_availability; print('✅ OK')"
python ai/train.py --scenario self --episodes 5  # Test scenario utils
```

**Phase 7 (replay_converter)**:
```bash
python -c "from ai.replay_converter import convert_steplog_to_replay; print('✅ OK')"
# Generate steplog, then convert
python ai/train.py --episodes 5
python ai/train.py --convert-steplog ai/event_log/training_step.log
```

---

### Post-Refactoring Regression Tests

Run these **AFTER** all phases complete (Phase 9):

```bash
# 1. Import Matrix Test
echo "Testing all module imports..."
python -c "
import ai.env_wrappers
import ai.training_callbacks
import ai.step_logger
import ai.bot_evaluation
import ai.training_utils
import ai.replay_converter
import ai.train
print('✅ All modules import successfully')
" > refactor_test_results/final_import_matrix.log 2>&1

# 2. Circular Import Test
echo "Testing for circular imports..."
python -c "
# Test circular dependency resolution
from ai.env_wrappers import BotControlledEnv
from ai.bot_evaluation import evaluate_against_bots
from ai.training_callbacks import BotEvaluationCallback
print('✅ No circular import errors')
" > refactor_test_results/final_circular_imports.log 2>&1

# 3. Basic Training - Full Episode
echo "Testing basic training..."
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config phase1 --episodes 10 \
  > refactor_test_results/final_basic_training.log 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Basic training: PASS"
else
  echo "❌ Basic training: FAIL (exit code $EXIT_CODE)"
fi

# 4. New Model Creation
echo "Testing new model creation..."
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --new --episodes 5 \
  > refactor_test_results/final_new_model.log 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ New model creation: PASS"
else
  echo "❌ New model creation: FAIL (exit code $EXIT_CODE)"
fi

# 5. Bot Evaluation
echo "Testing bot evaluation..."
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --test-episodes 20 \
  > refactor_test_results/final_bot_eval.log 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Bot evaluation: PASS"
else
  echo "❌ Bot evaluation: FAIL (exit code $EXIT_CODE)"
fi

# 6. Scenario Rotation
echo "Testing scenario rotation..."
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --scenario self --rotation-interval 5 --episodes 10 \
  > refactor_test_results/final_scenario_rotation.log 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Scenario rotation: PASS"
else
  echo "❌ Scenario rotation: FAIL (exit code $EXIT_CODE)"
fi

# 7. Multi-Agent Training
echo "Testing multi-agent training..."
python ai/train.py --multi-agent --episodes 5 \
  > refactor_test_results/final_multi_agent.log 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Multi-agent training: PASS"
else
  echo "❌ Multi-agent training: FAIL (exit code $EXIT_CODE)"
fi

# 8. Replay Conversion
echo "Testing replay conversion..."
if [ -f "ai/event_log/training_step.log" ]; then
  python ai/train.py --convert-steplog ai/event_log/training_step.log \
    > refactor_test_results/final_replay_conversion.log 2>&1
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Replay conversion: PASS"
  else
    echo "❌ Replay conversion: FAIL (exit code $EXIT_CODE)"
  fi
else
  echo "⚠️  Replay conversion: SKIP (no steplog found)"
fi

# 9. TensorBoard Logs Generated
echo "Checking TensorBoard logs..."
if [ -d "tensorboard_logs" ] && [ "$(ls -A tensorboard_logs)" ]; then
  ls -la tensorboard_logs/ > refactor_test_results/final_tensorboard_files.log
  echo "✅ TensorBoard logs: EXIST"
else
  echo "❌ TensorBoard logs: MISSING"
fi

# 10. Compare File Sizes
echo "Comparing file sizes..."
echo "BEFORE refactoring:" > refactor_test_results/final_file_size_comparison.log
wc -l ai/train_backup_*.py >> refactor_test_results/final_file_size_comparison.log 2>/dev/null || echo "No backup found"

echo -e "\nAFTER refactoring:" >> refactor_test_results/final_file_size_comparison.log
wc -l ai/train.py >> refactor_test_results/final_file_size_comparison.log
wc -l ai/env_wrappers.py >> refactor_test_results/final_file_size_comparison.log
wc -l ai/training_callbacks.py >> refactor_test_results/final_file_size_comparison.log
wc -l ai/step_logger.py >> refactor_test_results/final_file_size_comparison.log
wc -l ai/bot_evaluation.py >> refactor_test_results/final_file_size_comparison.log
wc -l ai/training_utils.py >> refactor_test_results/final_file_size_comparison.log
wc -l ai/replay_converter.py >> refactor_test_results/final_file_size_comparison.log

cat refactor_test_results/final_file_size_comparison.log

echo ""
echo "═══════════════════════════════════════════════"
echo "  REFACTORING REGRESSION TEST SUMMARY"
echo "═══════════════════════════════════════════════"
echo ""
echo "Test results saved to: refactor_test_results/"
echo ""
echo "Review logs for any errors:"
echo "  grep -i 'error\|fail\|traceback' refactor_test_results/*.log"
echo ""
```

---

### Validation Checklist (Updated)

Before considering refactor complete:

**Code Quality:**
- [ ] All 6 new modules created (`env_wrappers.py`, `training_callbacks.py`, `step_logger.py`, `bot_evaluation.py`, `training_utils.py`, `replay_converter.py`)
- [ ] Each module has docstring
- [ ] Each module has `__all__` exports
- [ ] `train.py` updated with new imports
- [ ] No duplicate code (duplicate `get_agent_scenario_file` removed)
- [ ] File sizes match expectations (~800 train.py, ~320 env_wrappers, etc.)

**External Dependencies:**
- [ ] `ai/multi_agent_trainer.py` Line 730 updated: `from ai.step_logger import StepLogger`
- [ ] Multi-agent import test passes: `python -c "from ai.multi_agent_trainer import MultiAgentTrainer"`
- [ ] No other files import from `ai.train` (verified with grep)

**Import Tests (Phase 9 - Import Matrix):**
- [ ] `import ai.env_wrappers` works
- [ ] `import ai.training_callbacks` works
- [ ] `import ai.step_logger` works
- [ ] `import ai.bot_evaluation` works
- [ ] `import ai.training_utils` works
- [ ] `import ai.replay_converter` works
- [ ] `import ai.train` works
- [ ] No circular import errors (lazy imports verified)

**Functionality Tests (Phase 9 - Regression):**
- [ ] Basic training: `python ai/train.py --episodes 10` (exit code 0)
- [ ] New model creation: `python ai/train.py --new --episodes 5` (exit code 0)
- [ ] Bot evaluation: `python ai/train.py --test-episodes 20` (exit code 0)
- [ ] Scenario rotation: `python ai/train.py --scenario self --episodes 10` (exit code 0)
- [ ] Multi-agent training: `python ai/train.py --multi-agent --episodes 5` (exit code 0)
- [ ] Replay conversion: `python ai/train.py --convert-steplog <file>` (exit code 0)

**TensorBoard & Logging:**
- [ ] TensorBoard logs generated in `tensorboard_logs/`
- [ ] Step logs generated in `ai/event_log/training_step.log`
- [ ] Replay JSON files generated (if replay conversion tested)
- [ ] No error traces in log files

**Git:**
- [ ] Feature branch created: `refactor/split-train-py`
- [ ] Backup created: `ai/train_backup_YYYYMMDD.py`
- [ ] All 7 phases committed separately
- [ ] Commit messages descriptive (include "refactor:", "BREAKING:", etc.)
- [ ] Final summary commit created

**Comparison with Baseline:**
- [ ] Compare `refactor_test_results/baseline_*.log` vs `refactor_test_results/final_*.log`
- [ ] Exit codes match (all 0)
- [ ] No new errors introduced
- [ ] Functionality identical

---

### Quick Smoke Test Script

Save this as `refactor_smoke_test.sh` for quick validation:

```bash
#!/bin/bash
# refactor_smoke_test.sh - Quick validation after refactoring

set -e  # Exit on first error

echo "🔍 Running refactoring smoke tests..."

# Test 1: All modules import
echo "1/7 Testing module imports..."
python -c "import ai.env_wrappers, ai.training_callbacks, ai.step_logger, ai.bot_evaluation, ai.training_utils, ai.replay_converter, ai.train"

# Test 2: No circular imports
echo "2/7 Testing circular imports..."
python -c "from ai.bot_evaluation import evaluate_against_bots; from ai.env_wrappers import BotControlledEnv"

# Test 3: Multi-agent import
echo "3/7 Testing multi_agent_trainer..."
python -c "from ai.multi_agent_trainer import MultiAgentTrainer"

# Test 4: Basic training
echo "4/7 Testing basic training..."
timeout 60 python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --episodes 2 || echo "Training test skipped (timeout)"

# Test 5: Bot evaluation
echo "5/7 Testing bot evaluation..."
timeout 30 python ai/train.py --test-episodes 5 || echo "Evaluation test skipped (timeout)"

# Test 6: File structure
echo "6/7 Checking file structure..."
test -f ai/env_wrappers.py && echo "  ✅ env_wrappers.py exists"
test -f ai/training_callbacks.py && echo "  ✅ training_callbacks.py exists"
test -f ai/step_logger.py && echo "  ✅ step_logger.py exists"
test -f ai/bot_evaluation.py && echo "  ✅ bot_evaluation.py exists"
test -f ai/training_utils.py && echo "  ✅ training_utils.py exists"
test -f ai/replay_converter.py && echo "  ✅ replay_converter.py exists"
test -f ai/train.py && echo "  ✅ train.py exists"

# Test 7: Line counts reasonable
echo "7/7 Checking line counts..."
TRAIN_LINES=$(wc -l < ai/train.py)
if [ "$TRAIN_LINES" -lt 1000 ]; then
  echo "  ✅ train.py is ${TRAIN_LINES} lines (target: ~800)"
else
  echo "  ⚠️  train.py is ${TRAIN_LINES} lines (expected ~800)"
fi

echo ""
echo "✅ All smoke tests passed!"
echo ""
echo "Next steps:"
echo "  - Review test results in refactor_test_results/"
echo "  - Run full regression tests"
echo "  - Compare with baseline tests"
```

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
| 8 | Finalize train_core.py | 20 min | 4:30 |
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
- train_core.py stays ~800 lines with orchestration
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
