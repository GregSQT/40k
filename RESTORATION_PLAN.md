# Complete Restoration Plan
**Date:** 2025-11-21
**Purpose:** Restore ALL functionality removed during refactoring

---

## Overview

The refactoring removed **~1000 lines** of critical functionality. This plan outlines exactly what will be restored.

---

## 1. MetricsCollectionCallback Restoration
**File:** `ai/training_callbacks.py`
**Current:** 58 lines (simplified)
**Original:** 447 lines (full-featured)
**Restoration:** Replace lines 288-345 with original lines 731-1177

### Features Being Restored:

#### A. Training Start Initialization (`_on_training_start`)
- TensorBoard writer setup
- Hyperparameter logging
- Initial metrics initialization

#### B. Comprehensive Episode Tracking
- **Tactical Combat Metrics:**
  - `episode_tactical_data`: Track shots fired, hits, damage dealt
  - `units_lost` and `units_killed` per episode
  - `valid_actions` vs `invalid_actions` tracking

- **Reward Component Tracking:**
  - `episode_reward_components`: Decompose reward into components
  - `immediate_reward_ratio_history`: Track reward distribution
  - Smoothing with exponential moving average

- **Model Performance Metrics:**
  - `q_value_history`: Q-value tracking with smoothing
  - `gradient_norm_history`: Track gradient norms
  - `loss_history`: Policy and value loss tracking with smoothing
  - PPO-specific metrics: `clip_fraction`, `explained_variance`, `entropy_losses`

#### C. Advanced TensorBoard Logging
- Smoothed tactical metrics (EMA)
- Reward component histograms
- Q-value distributions
- Gradient norm monitoring
- Loss curves with smoothing
- Hyperparameter tracking

#### D. Final Training Summary (`print_final_training_summary`)
- Comprehensive end-of-training report
- Episode statistics
- Tactical performance summary
- Reward component analysis
- Model performance metrics
- Training hyperparameters

#### E. Final Bot Evaluation (`_run_final_bot_eval`)
- Run full bot evaluation at training end
- Report final win rates against all bot types
- TensorBoard logging of final metrics

---

## 2. EpisodeBasedEvalCallback Restoration
**File:** `ai/training_callbacks.py`
**Current:** 68 lines (simplified)
**Original:** 170 lines (full-featured)
**Restoration:** Replace lines 220-287 with original lines 561-730

### Features Being Restored:

#### A. History Tracking
- `win_rate_history`: Track win rates over time
- `loss_history`: Track losses with smoothing
- `q_value_history`: Track Q-values with smoothing
- `gradient_norm_history`: Track gradient magnitudes

#### B. Advanced Metrics Collection
- Smoothed metrics using exponential moving average
- TensorBoard logging for all tracked metrics
- Hyperparameter monitoring during evaluation

#### C. Model Performance Analysis
- Detailed evaluation reports
- Performance trend analysis
- Stability monitoring

---

## 3. StepLogger Restoration
**File:** `ai/step_logger.py`
**Current:** Message formatting inline
**Original:** Used `_format_replay_style_message()` helper method
**Restoration:** Restore the helper method and original logic

### Changes:
- Restore `_format_replay_style_message()` method
- Ensure replay log format consistency with original

---

## 4. make_training_env API Restoration
**File:** `ai/training_utils.py`
**Current API:**
```python
def make_training_env(rank, scenario_file, rewards_config_name, training_config_name,
                     unit_registry, controlled_agent=None, enable_action_masking=True):
```

**Original API:**
```python
def make_training_env(rank, scenario_file, rewards_config_name, training_config_name,
                     unit_registry, controlled_agent_key=None, step_logger_enabled=False):
```

### Changes:
- ✅ Rename `controlled_agent` back to `controlled_agent_key`
- ✅ Restore `step_logger_enabled` parameter
- ❌ Remove `enable_action_masking` (was added during refactoring)
- Update all call sites in train.py

---

## Impact Analysis

### Lines of Code
- **Before restoration:** ~3428 lines total across all modules
- **After restoration:** ~4428 lines total (1000 lines restored)
- **train.py:** Remains 1608 lines (unchanged)
- **Extracted modules:** Grow from 1820 lines to 2820 lines

### Functionality Restored
1. ✅ **Full tactical combat tracking** - Essential for diagnosing training issues
2. ✅ **Reward decomposition** - Critical for reward shaping analysis
3. ✅ **Q-value and gradient tracking** - Necessary for model stability monitoring
4. ✅ **Comprehensive TensorBoard logging** - Visual training analysis
5. ✅ **Final training summary** - Essential for training reports
6. ✅ **Final bot evaluation** - Verify final model performance
7. ✅ **History tracking in callbacks** - Track performance trends
8. ✅ **StepLogger consistency** - Ensure replay logs work correctly
9. ✅ **Original API compatibility** - Match pre-refactoring interface

---

## Estimated Time
- Restoration work: 30-60 minutes
- Testing: 15-30 minutes
- **Total: 1-1.5 hours**

---

## Next Steps

1. **APPROVAL REQUIRED**: Do you want me to proceed with this full restoration?
2. **Alternative**: We can restore selectively (e.g., only critical metrics)
3. **Alternative**: We can keep simplified version and document the differences

---

## Question for You

**Do you want:**
- **Option A**: Full restoration (1000+ lines) - Get back ALL original functionality
- **Option B**: Selective restoration - Only restore the most critical features
- **Option C**: Keep current simplified version - Accept the functionality loss

**Your decision?**
