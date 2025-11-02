# AI_TRAINING.md
## PPO Training Configuration Guide - Streamlined Edition

> **📍 Purpose**: Configure and monitor PPO training for W40K tactical AI
> 
> **Status**: January 2025 - Configuration-focused edition

---

## 📋 TABLE OF CONTENTS

- [Quick Start](#-quick-start)
  - [Run Training](#run-training)
  - [Continue Existing Model](#continue-existing-model)
  - [Key Paths](#key-paths)
- [Curriculum Learning (3-Phase Strategy)](#-curriculum-learning-3-phase-strategy)
  - [Why Curriculum Learning?](#why-curriculum-learning)
  - [Phase 1: Learn Shooting Basics](#phase-1-learn-shooting-basics)
  - [Phase 2: Learn Target Priorities](#phase-2-learn-target-priorities)
  - [Phase 3: Learn Full Tactics](#phase-3-learn-full-tactics)
- [Configuration Files](#️-configuration-files)
  - [training_config.json Structure](#trainingconfigjson-structure)
  - [rewards_config.json Structure](#rewardsconfigjson-structure)
- [Monitoring Training](#-monitoring-training)
  - [TensorBoard Metrics](#tensorboard-metrics)
  - [Phase-Specific Success Indicators](#phase-specific-success-indicators)
  - [Red Flags (Training Collapse)](#red-flags-training-collapse)
- [Advanced Metrics & Optimization](#-advanced-metrics--optimization) → **See [AI_METRICS.md](AI_METRICS.md)**
- [Bot Evaluation System](#-bot-evaluation-system)
  - [Bot Types](#bot-types)
  - [Evaluation Commands](#evaluation-commands)
  - [Win Rate Benchmarks](#win-rate-benchmarks)
- [Hyperparameter Tuning Guide](#-hyperparameter-tuning-guide)
  - [When Agent Isn't Learning](#when-agent-isnt-learning)
  - [When Agent Is Unstable](#when-agent-is-unstable)
  - [When Training Is Too Slow](#when-training-is-too-slow)
  - [When Agent Exploits Mechanics](#when-agent-exploits-mechanics)
- [Performance Optimization](#-performance-optimization)
  - [CPU vs GPU](#cpu-vs-gpu)
  - [Training Speed Tips](#training-speed-tips)
- [Troubleshooting](#-troubleshooting)
  - [Common Errors](#common-errors)
  - [Performance Issues](#performance-issues)
- [Advanced Topics (External References)](#-advanced-topics-external-references)
- [Quick Reference Cheat Sheet](#-quick-reference-cheat-sheet)
- [Summary](#-summary)

---

## 📋 QUICK START

### Run Training
```bash
# From project root
python train.py --config default          # Standard training (1000 episodes)
python train.py --config debug           # Fast testing (50 episodes)
python train.py --config phase1          # Curriculum Phase 1
python train.py --config phase2          # Curriculum Phase 2
python train.py --config phase3          # Curriculum Phase 3
```

### Continue Existing Model
```bash
python train.py --config phase2 --model ./models/ppo_checkpoint_phase1.zip
```

### Key Paths
- **Configs**: `config/training_config.json`, `config/rewards_config.json`
- **Models**: `./models/` (checkpoints saved here)
- **Logs**: `./tensorboard/` (TensorBoard data)
- **Events**: `ai/event_log/` (battle replays)

---

## 🎓 CURRICULUM LEARNING (3-PHASE STRATEGY)

### Why Curriculum Learning?
Teaching complex tactics in one step fails. Instead, we progressively teach:
1. **Basic mechanics** (shooting is good)
2. **Target priorities** (weak targets first)
3. **Full tactics** (positioning, cover, focus fire)

Each phase uses different reward weights to emphasize current learning goal.

---

### Phase 1: Learn Shooting Basics
**Goal**: Agent discovers that shooting enemies = positive rewards

**What Agent Learns:**
- Shooting is better than waiting
- Moving into line-of-sight is valuable
- Kills are highly rewarded

**Reward Emphasis** (from `rewards_config.json`):
```json
"SpaceMarine_Infantry_Troop_RangedSwarm_phase1": {
  "base_actions": {
    "ranged_attack": 5.0,        // High reward for shooting
    "shoot_wait": -15.0          // Heavy penalty for not shooting
  },
  "result_bonuses": {
    "kill_target": 40.0,         // Massive kill reward
    "wound_target": 5.0,
    "damage_target": 10.0
  },
  "situational_modifiers": {
    "win": 75.0,                 // Victory strongly reinforced
    "lose": -75.0
  }
}
```

**Training Config** (from `training_config.json`):
- `total_episodes`: 2000
- `learning_rate`: 0.001 (high for fast learning)
- `ent_coef`: 0.10 (high exploration)
- `n_steps`: 512 (smaller batches)

**Success Criteria:**
- ✅ Win rate > 60% vs Random bot
- ✅ `shoot_wait` penalty episodes decrease
- ✅ Average kills per episode > 3

**Advance when**: Agent consistently shoots instead of waiting (3-5 training runs)

---

### Phase 2: Learn Target Priorities
**Goal**: Agent learns to prioritize weak/valuable targets

**What Agent Learns:**
- Kill low-HP enemies first (no overkill)
- Different unit types have different values
- Focus fire is effective

**Reward Emphasis** (from `rewards_config.json`):
```json
"SpaceMarine_Infantry_Troop_RangedSwarm_phase2": {
  "base_actions": {
    "ranged_attack": 2.0,        // Still good, but not dominant
    "shoot_wait": -5.0           // Moderate penalty
  },
  "result_bonuses": {
    "kill_target": 5.0,          // Reduced from Phase 1
    "no_overkill": 1.0,          // NEW: Efficiency bonus
    "target_lowest_hp": 8.0      // NEW: Priority on weak targets
  },
  "target_type_bonuses": {
    "vs_swarm": 2.0,             // NEW: Unit type bonuses
    "vs_elite": 1.0,
    "vs_troop": 0.5
  }
}
```

**Training Config**:
- `total_episodes`: 4000
- `learning_rate`: 0.0005 (reduced for refinement)
- `ent_coef`: 0.05 (less exploration)
- `n_steps`: 1024 (larger batches)

**Success Criteria:**
- ✅ Win rate > 70% vs Greedy bot
- ✅ Average overkill damage < 20% of total damage
- ✅ Low-HP targets killed before high-HP targets

**Advance when**: Agent demonstrates target prioritization (5-10 training runs)

---

### Phase 3: Learn Full Tactics
**Goal**: Agent masters positioning, cover, and combined tactics

**What Agent Learns:**
- Move to cover when exposed
- Maintain line-of-sight advantages
- Coordinate multiple units
- Avoid being charged

**Reward Emphasis** (from `rewards_config.json`):
```json
"SpaceMarine_Infantry_Troop_RangedSwarm_phase3": {
  "base_actions": {
    "ranged_attack": 1.5,
    "move_to_los": 0.8,          // Strong positioning reward
    "move_to_charge": 0.6
  },
  "tactical_bonuses": {
    "gained_los_on_target": 0.8, // NEW: Tactical awareness
    "moved_to_cover": 0.6,
    "safe_from_charges": 0.5,
    "safe_from_ranged": 0.4
  },
  "adaptive_bonuses": {
    "step_up_when_covered": 0.2, // NEW: Adaptive behavior
    "step_down_when_needed": 0.2
  }
}
```

**Training Config**:
- `total_episodes`: 6000
- `learning_rate`: 0.0003 (fine-tuning)
- `ent_coef`: 0.10 (moderate exploration)
- `n_steps`: 2048 (full batches)
- `n_epochs`: 10 (deep learning)

**Success Criteria:**
- ✅ Win rate > 75% vs Tactical bot
- ✅ Units consistently use cover
- ✅ Positioning improves over episode

**Complete when**: Agent demonstrates tactical mastery (10-20 training runs)

---

## ⚙️ CONFIGURATION FILES

### training_config.json Structure

```json
{
  "phase1": {
    "total_episodes": 2000,              // How many episodes to train
    "max_turns_per_episode": 5,          // Game length limit
    "max_steps_per_turn": 8,             // Steps per turn limit
    
    "callback_params": {
      "checkpoint_save_freq": 2500,      // Save model every N steps
      "checkpoint_name_prefix": "ppo_curriculum_p1",
      "n_eval_episodes": 5               // Evaluation frequency
    },
    
    "observation_params": {
      "obs_size": 295,                   // Total observation vector size
      "perception_radius": 25,           // Fog of war radius
      "max_nearby_units": 10,            // Max units to observe
      "max_valid_targets": 5             // Max targets to track
    },
    
    "model_params": {
      "learning_rate": 0.001,            // How fast agent learns
      "n_steps": 512,                    // Steps before update
      "batch_size": 128,                 // Training batch size
      "n_epochs": 4,                     // Training epochs per update
      "gamma": 0.95,                     // Future reward discount
      "gae_lambda": 0.9,                 // Advantage estimation
      "clip_range": 0.2,                 // PPO clipping parameter
      "ent_coef": 0.10,                  // Exploration bonus
      "vf_coef": 0.5,                    // Value function weight
      "max_grad_norm": 0.5,              // Gradient clipping
      "policy_kwargs": {
        "net_arch": [320, 320]           // Neural network size
      }
    }
  }
}
```

**Key Parameters to Adjust:**

| Parameter | Low Value | High Value | Effect |
|-----------|-----------|------------|--------|
| `learning_rate` | 0.0001 | 0.001 | Faster learning (risk: instability) |
| `ent_coef` | 0.01 | 0.20 | More exploration (risk: chaos) |
| `n_steps` | 256 | 4096 | Larger batches (slower, more stable) |
| `batch_size` | 64 | 256 | Training speed vs memory |
| `gamma` | 0.90 | 0.99 | Long-term vs short-term rewards |

---

### rewards_config.json Structure

Each unit type has reward profiles for:
- **Base profile**: Default tactical behavior
- **Phase 1 profile**: Suffix `_phase1` for shooting emphasis
- **Phase 2 profile**: Suffix `_phase2` for priority targeting
- **Phase 3 profile**: Suffix `_phase3` for full tactics

**Reward Categories:**

```json
{
  "base_actions": {
    // Rewards for action types (move, shoot, charge)
    "ranged_attack": 0.5,
    "move_to_los": 0.6,
    "shoot_wait": -0.9
  },
  
  "result_bonuses": {
    // Rewards for action outcomes
    "kill_target": 0.1,
    "no_overkill": 0.05,
    "target_lowest_hp": 0.05
  },
  
  "target_type_bonuses": {
    // Rewards based on target unit type
    "vs_swarm": 0.2,
    "vs_elite": 0.0,
    "vs_vehicle": -0.1
  },
  
  "tactical_bonuses": {
    // Rewards for tactical positioning
    "gained_los_on_target": 0.25,
    "moved_to_cover": 0.15,
    "safe_from_charges": 0.1
  },
  
  "situational_modifiers": {
    // Win/loss and special conditions
    "win": 1.0,
    "lose": -1.0,
    "friendly_fire_penalty": -0.8
  }
}
```

**Common Reward Design Mistakes:**

❌ **Reward Hacking**: Too high rewards cause agent to exploit mechanics
- Example: `kill_target: 100.0` → Agent ignores positioning to chase kills

❌ **Conflicting Rewards**: Mixed signals confuse learning
- Example: `move_close: 0.5` AND `move_away: 0.5` → Random movement

❌ **Sparse Rewards**: Agent never learns what's good
- Example: Only `win: 1.0`, no intermediate rewards → Random actions

✅ **Good Practice**: Balanced progressive rewards
- Small rewards for good actions (0.1-1.0)
- Medium rewards for tactical wins (1.0-5.0)
- Large rewards for objectives (5.0-50.0)

---

## 📊 MONITORING TRAINING

### TensorBoard Metrics

Start TensorBoard:
```bash
tensorboard --logdir=./tensorboard/
```

**Key Metrics to Watch:**

| Metric | What It Shows | Good Trend |
|--------|---------------|------------|
| `rollout/ep_rew_mean` | Average episode reward | Increasing |
| `rollout/ep_len_mean` | Episode length | Stable or decreasing |
| `train/entropy_loss` | Exploration level | Decreasing gradually |
| `train/policy_loss` | Policy improvement | Decreasing |
| `train/value_loss` | Value estimation | Decreasing then stable |
| `eval/mean_reward` | Evaluation performance | Increasing |
| `eval/mean_ep_length` | Evaluation efficiency | Stable |

### Phase-Specific Success Indicators

**Phase 1 - Learning Shooting:**
- `rollout/ep_rew_mean`: Should increase from negative to positive
- `shoot_wait` penalties: Should decrease sharply
- Win rate vs Random bot: 60%+ after 1000 episodes

**Phase 2 - Learning Priorities:**
- `rollout/ep_rew_mean`: Should continue increasing
- `no_overkill` bonuses: Should increase
- Win rate vs Greedy bot: 70%+ after 2000 episodes

**Phase 3 - Full Tactics:**
- `rollout/ep_rew_mean`: Steady high values
- Tactical bonuses: Should increase
- Win rate vs Tactical bot: 75%+ after 4000 episodes

### Red Flags (Training Collapse)

🚨 **Policy Collapse:**
- Symptom: `rollout/ep_rew_mean` drops suddenly
- Cause: Learning rate too high or reward hacking
- Fix: Reduce `learning_rate` by 50%, restart from last checkpoint

🚨 **No Learning:**
- Symptom: Flat `rollout/ep_rew_mean` for 500+ episodes
- Cause: Rewards too sparse or `ent_coef` too low
- Fix: Increase `ent_coef` to 0.15, check reward config

🚨 **Instability:**
- Symptom: `rollout/ep_rew_mean` oscillates wildly
- Cause: Batch size too small or conflicting rewards
- Fix: Increase `n_steps` to 1024, review reward balance

---

## 📊 ADVANCED METRICS & OPTIMIZATION

For deep metrics analysis, pattern recognition, and optimization strategies, see the dedicated guide:

**👉 [AI_METRICS.md](AI_METRICS.md) - Training Optimization Through Metrics Analysis**

This comprehensive guide covers:
- **Deep metric explanations** - What each metric really means and how to interpret it
- **Pattern library** - Good/bad training patterns with real numbers and fixes
- **Diagnostic workflows** - Step-by-step decision trees for troubleshooting
- **Hyperparameter tuning** - Metric-based adjustment strategies
- **Case studies** - Real training runs with problems, diagnoses, and solutions
- **Quick diagnostic reference** - Fast symptom-to-fix lookup table

---

## 🤖 BOT EVALUATION SYSTEM

### Bot Types

**Random Bot (Easiest)**
- Selects random valid actions
- No tactical awareness
- Baseline: Any competent agent should win 90%+

**Greedy Bot (Medium)**
- Always shoots nearest enemy
- Moves toward closest target
- Basic threat: Tests if agent learned shooting

**Tactical Bot (Hard)**
- Prioritizes low-HP targets
- Uses cover when available
- Avoids being charged
- Real challenge: Tests full tactical learning

### Evaluation Commands

```bash
# Automatic evaluation during training (every 5 episodes)
python train.py --config phase1  # n_eval_episodes: 5

# Manual evaluation after training
python evaluation.py --model ./models/ppo_checkpoint_phase1.zip --opponent tactical --episodes 20
```

### Win Rate Benchmarks

| Training Stage | vs Random | vs Greedy | vs Tactical |
|----------------|-----------|-----------|-------------|
| Phase 1 Start  | 30-40%    | 10-20%    | 0-5%        |
| Phase 1 End    | 80-90%    | 60-70%    | 30-40%      |
| Phase 2 End    | 95%+      | 80-90%    | 60-70%      |
| Phase 3 End    | 95%+      | 95%+      | 80-90%      |

---

## 🔧 HYPERPARAMETER TUNING GUIDE

### When Agent Isn't Learning

**Problem**: Flat rewards after 500+ episodes

**Try:**
1. Increase `ent_coef` from 0.05 → 0.15 (more exploration)
2. Increase `learning_rate` from 0.0003 → 0.0005
3. Check rewards_config: Are intermediate rewards present?

**Avoid**: Changing multiple parameters at once

---

### When Agent Is Unstable

**Problem**: Reward oscillates wildly

**Try:**
1. Decrease `learning_rate` from 0.001 → 0.0003
2. Increase `n_steps` from 512 → 1024 (more stable updates)
3. Increase `batch_size` from 64 → 128

**Avoid**: Setting `learning_rate` > 0.001 in later phases

---

### When Training Is Too Slow

**Problem**: 50+ hours per phase

**Try:**
1. Reduce `total_episodes` (use debug config first)
2. Reduce `n_eval_episodes` from 5 → 2
3. Increase `n_steps` from 512 → 2048 (fewer updates)
4. Use CPU instead of GPU (see Performance section)

**Avoid**: Reducing `batch_size` below 64

---

### When Agent Exploits Mechanics

**Problem**: High rewards but nonsensical behavior

**Try:**
1. Review rewards_config: Find the exploited reward
2. Reduce exploited reward by 50%
3. Add balancing penalty (e.g., movement cost)
4. Restart training from earlier checkpoint

**Example**: Agent shoots friendly units for "hit_target" reward
- **Fix**: Ensure `friendly_fire_penalty: -5.0` is present and large

---

## ⚡ PERFORMANCE OPTIMIZATION

### CPU vs GPU

**Current Benchmark**: Training runs **10% faster on CPU** than GPU
- CPU: 311 it/s (optimized)
- GPU: 280 it/s (transfer overhead)

**Recommendation**: Use CPU for training unless batch size > 256

```bash
# Force CPU usage
python train.py --config phase1 --device cpu
```

---

### Training Speed Tips

1. **Use debug config first** - Validate setup in 10 minutes instead of 10 hours
2. **Reduce evaluation frequency** - Set `n_eval_episodes: 2` during development
3. **Increase n_steps** - Larger batches = fewer updates = faster training
4. **Disable verbose logging** - Set `verbose: 0` in model_params

---

## 🐛 TROUBLESHOOTING

### Common Errors

**Error**: `Observation size mismatch (expected 295, got 150)`
- **Cause**: Old model trained with different observation size
- **Fix**: Train new model from scratch or update observation_params

**Error**: `Reward key not found: SpaceMarine_Infantry_Troop_RangedSwarm_phase4`
- **Cause**: Phase suffix doesn't exist in rewards_config.json
- **Fix**: Use phase1, phase2, or phase3 (no phase4)

**Error**: `CUDA out of memory`
- **Cause**: Batch size too large for GPU
- **Fix**: Switch to CPU or reduce `batch_size`

**Error**: `No improvement in 1000 episodes`
- **Cause**: Rewards too sparse or `ent_coef` too low
- **Fix**: Check rewards_config, increase `ent_coef` to 0.15

---

### Performance Issues

**Symptom**: Training speed < 50 it/s
- Check: Are you using GPU? (CPU is faster)
- Check: Is TensorBoard running? (Disable during training)
- Check: Is `n_steps` too small? (Increase to 1024+)

**Symptom**: Memory usage > 8GB
- Reduce `n_steps` from 2048 → 1024
- Reduce `batch_size` from 256 → 128
- Close TensorBoard during training

---

## 📚 ADVANCED TOPICS (EXTERNAL REFERENCES)

### PPO Algorithm Details
- [Stable-Baselines3 PPO Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)
- [PPO Paper (Schulman et al.)](https://arxiv.org/abs/1707.06347)

### Observation Space Internals
- See `w40k_core.py:build_observation()` for implementation
- 295 floats = 72 ally + 138 enemy + 35 targets + 50 self-state

### Reward Calculation Logic
- See `reward_mapper.py:calculate_reward()` for implementation
- Uses RewardMapper class to aggregate rewards from config

### Gym Environment Interface
- See `w40k_core.py:W40KCore` for gym.Env implementation
- Complies with Stable-Baselines3 requirements

---

## 📝 QUICK REFERENCE CHEAT SHEET

```bash
# Training Commands
python train.py --config debug              # Fast test (50 episodes)
python train.py --config phase1             # Curriculum Phase 1
python train.py --config phase2 --model X   # Continue from checkpoint
python train.py --config phase3 --device cpu # Force CPU

# Monitoring
tensorboard --logdir=./tensorboard/         # View training metrics

# Evaluation
python evaluation.py --model X --opponent tactical --episodes 20

# Key Paths
config/training_config.json                 # Training parameters
config/rewards_config.json                  # Reward definitions
./models/                                   # Saved checkpoints
./tensorboard/                              # TensorBoard logs
ai/event_log/                               # Battle replays

# Success Criteria
Phase 1: Win 60%+ vs Random (2000 eps)
Phase 2: Win 70%+ vs Greedy (4000 eps)
Phase 3: Win 75%+ vs Tactical (6000 eps)
```

---

## 🎯 SUMMARY

**This guide focuses on WHAT TO CONFIGURE, not how the system works internally.**

**For implementation details:**
- Observation system → `w40k_core.py`
- Reward logic → `reward_mapper.py`
- Training loop → `train.py`
- Game rules → `AI_TURN.md`, `AI_IMPLEMENTATION.md`

**For training configuration:**
- Read this document (AI_TRAINING.md)
- Modify `training_config.json` and `rewards_config.json`
- Monitor TensorBoard metrics
- Adjust hyperparameters based on observed behavior

**Remember**: Training is iterative. Start with debug config, validate quickly, then scale up.