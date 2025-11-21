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
- [Replay Mode](#-replay-mode)
  - [Overview](#overview)
  - [Generating Replay Logs](#generating-replay-logs)
  - [Using the Replay Viewer](#using-the-replay-viewer)
  - [Replay Features](#replay-features)
  - [Log Format Reference](#log-format-reference)
  - [Best Practices](#best-practices)
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
- [Anti-Overfitting Strategies](#️-anti-overfitting-strategies)
  - [The Problem: Pattern Exploitation](#the-problem-pattern-exploitation-vs-robust-tactics)
  - [Solution 1: Bot Stochasticity](#solution-1-bot-stochasticity-prevent-pattern-exploitation)
  - [Solution 2: Balanced Reward Penalties](#solution-2-balanced-reward-penalties-reduce-over-aggression)
  - [Solution 3: Increased RandomBot Weight](#solution-3-increased-randombot-evaluation-weight)
  - [Monitoring for Overfitting](#monitoring-for-overfitting)
  - [Troubleshooting Overfitting](#troubleshooting-overfitting)
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
- **Step Logs**: `train_step.log` (detailed action logs for replay viewer)

---

## 🎬 REPLAY MODE

### Overview
The Replay Mode allows you to visualize training episodes step-by-step in the frontend. This is invaluable for understanding agent behavior and debugging tactical decisions.

### Generating Replay Logs
During training or evaluation, a `train_step.log` file is generated containing detailed action logs:

```bash
# Training automatically generates train_step.log
python train.py --config phase1
```

The log captures:
- Episode start/end markers
- Unit starting positions
- Move actions (from/to coordinates)
- Shoot actions (hit/wound/save rolls, damage dealt)
- Episode results (winner, total actions)

### Using the Replay Viewer

1. **Start the frontend**:
   ```bash
   cd frontend && npm run dev
   ```

2. **Navigate to Replay Mode**:
   - Click the "Replay" tab in the frontend
   - Click "Browse" to select your `train_step.log` file

3. **Select an Episode**:
   - Use the dropdown to select an episode
   - Episodes show: `Episode N - BotName - Result`
   - Example: `Episode 5 - GreedyBot - Agent Win`

4. **Control Playback**:
   - Use forward/backward buttons to step through actions
   - Watch units move, shoot, and take damage
   - Dead units appear as grey ghosts before being removed

### Replay Features

**Visual Indicators:**
- **Shoot lines**: Orange lines show shooting actions
- **Explosion icons**: Appear on damaged/killed units
- **Grey ghosts**: Units killed in the current step appear grey before removal
- **Death logs**: Black log entries appear when a unit is destroyed
- **HP display**: Unit health shown as bars

**Game Log Color Coding:**
- **Yellow**: Failed hit or wound rolls
- **Orange**: Successful save by target
- **Red**: Damage dealt to target
- **Black**: Unit destroyed

**Episode Information:**
- Bot opponent name (e.g., GreedyBot, RandomBot)
- Win/Loss/Draw result
- Total actions in episode
- Current action counter

### Log Format Reference

The `train_step.log` uses this format:

```
[HH:MM:SS] === EPISODE START ===
[HH:MM:SS] Scenario: phase1-2
[HH:MM:SS] Opponent: GreedyBot
[HH:MM:SS] Unit 1 (Intercessor) P0: Starting position (9, 12)
[HH:MM:SS] === ACTIONS START ===
[HH:MM:SS] T1 P0 MOVE : Unit 1(6, 15) MOVED from (9, 12) to (6, 15) [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 SHOOT : Unit 1(6, 15) SHOT at unit 5 - Hit:3+:6(HIT) Wound:4+:5(SUCCESS) Save:3+:2(FAILED) Dmg:1HP [SUCCESS] [STEP: YES]
[HH:MM:SS] EPISODE END: Winner=0, Actions=68, Steps=68, Total=138
```

### Best Practices

1. **Debug unexpected behavior**: Use replay to see exactly what the agent did
2. **Validate training progress**: Check if agent is making tactical decisions
3. **Compare phases**: Replay episodes from different training phases to see improvement
4. **Check target selection**: Verify agent is prioritizing correct targets

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
- Kill efficiency: prioritize targets that remove the most threat per turn invested
- Focus fire on wounded enemies (half the time to kill = double the efficiency)
- Ignore distant enemies that can't threaten you (outside move + range)

**Target Priority Formula:**
```
kill_efficiency = threat_per_turn / turns_to_kill
```

- **Higher efficiency = higher priority** (action slot 0)
- Wounded targets have higher efficiency (same threat, less time to kill)
- Distant targets outside (MOVE + RNG_RNG) have near-zero threat

**Example priorities (Intercessor selecting targets):**

| Target | Threat/Turn | Turns to Kill | Kill Efficiency |
|--------|-------------|---------------|-----------------|
| Wounded Intercessor (1 HP) | 0.333 | ~3 | **0.111** (highest) |
| Termagant | 0.111 | ~1.4 | **0.079** |
| Full HP Intercessor | 0.333 | ~6 | **0.056** (lowest) |

This formula naturally encourages:
- Finishing wounded enemies (double efficiency)
- Killing easy targets first (Termagants before full HP Intercessors)
- Ignoring distant non-threats

**Reward Emphasis** (from `rewards_config.json`):
```json
"SpaceMarine_Infantry_Troop_RangedSwarm_phase2": {
  "base_actions": {
    "ranged_attack": 2.0,        // Still good, but not dominant
    "shoot_wait": -5.0           // Moderate penalty
  },
  "result_bonuses": {
    "kill_target": 5.0,          // Reduced from Phase 1
    "target_lowest_hp": 15.0     // Priority on wounded/easy targets
  },
  "target_type_bonuses": {
    "vs_swarm": 2.0,             // Unit type bonuses
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
- **Supports randomness parameter** (0.0-0.3) to prevent pattern exploitation

**Tactical Bot (Hard)** _(Also called DefensiveBot)_
- Prioritizes low-HP targets
- Uses cover when available
- Avoids being charged
- Real challenge: Tests full tactical learning
- **Supports randomness parameter** (0.0-0.3) to prevent pattern exploitation

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

## 🛡️ ANTI-OVERFITTING STRATEGIES

### The Problem: Pattern Exploitation vs. Robust Tactics

**Symptom**: Agent performs well against GreedyBot and DefensiveBot but fails against RandomBot

**Root Cause**: The agent learned to **exploit predictable patterns** instead of developing robust tactical strategies.

**Example Bad Behavior**:
- Agent assumes enemies always shoot the nearest target (GreedyBot pattern)
- Agent positions based on enemy predictability
- When facing random/unpredictable opponents, strategy falls apart

### Solution 1: Bot Stochasticity (Prevent Pattern Exploitation)

**Location**: `ai/evaluation_bots.py`

Both `GreedyBot` and `DefensiveBot` now accept a `randomness` parameter:

```python
GreedyBot(randomness=0.15)    # 15% chance of random action
DefensiveBot(randomness=0.15) # 15% chance of random action
```

**How it works**:
- Bots make their normal strategic decision 85% of the time
- 15% of the time they make a random valid action
- This prevents your agent from perfectly predicting and exploiting their behavior

**Tuning recommendations**:
- `0.0` = Pure bot (fully predictable) - use for testing specific strategies
- `0.10-0.20` = **Recommended for training** (prevents overfitting)
- `0.30+` = Too random, defeats the purpose of strategic bots

**Implementation** (in `ai/train.py`):
```python
# Create evaluation bots with randomness
bots = {
    'random': RandomBot(),
    'greedy': GreedyBot(randomness=0.15),  # 15% random actions
    'defensive': DefensiveBot(randomness=0.15)  # 15% random actions
}
```

---

### Solution 2: Balanced Reward Penalties (Reduce Over-Aggression)

**Location**: `config/agents/<agent>/<agent>_rewards_config.json`

**Problem**: Overly harsh penalties force hyper-aggressive play that becomes predictable.

**Changes in Phase 1** (Example for SpaceMarine_Infantry_Troop_RangedSwarm):
```json
{
  "SpaceMarine_Infantry_Troop_RangedSwarm_phase1": {
    "base_actions": {
      "shoot_wait": -10.0   // Was -30.0 (too punishing)
    },
    "movement_penalties": {
      "move_away": -1.0     // Was -3.0 (too punishing)
    }
  }
}
```

**Why this helps**:
- Old values forced hyper-aggressive play (always seeking shots)
- Aggressive strategies are predictable and exploitable by random opponents
- New values allow tactical patience and positional flexibility

**Tuning recommendations by phase**:
- **Phase 1**: Focus on learning basics with moderate penalties
- **Phase 2**: Increase penalties slightly to encourage efficiency
- **Phase 3**: Use balanced penalties for final tactical polish

---

### Solution 3: Increased RandomBot Evaluation Weight

**Location**: `ai/train.py` (model selection logic)

**Old weights**:
```python
combined_score = 0.20 * random + 0.30 * greedy + 0.50 * defensive
```

**New weights** (Recommended):
```python
combined_score = 0.35 * random + 0.30 * greedy + 0.35 * defensive
```

**Why this helps**:
- RandomBot performance now impacts overall score significantly
- Model selection favors agents that handle unpredictability
- Prevents models that only beat predictable opponents from being saved as "best"

**Tuning recommendations by training stage**:

```python
# Early training (Phase 1): Equal weighting
combined_score = 0.33 * random + 0.33 * greedy + 0.34 * defensive

# Mid training (Phase 2): Balanced (RECOMMENDED)
combined_score = 0.35 * random + 0.30 * greedy + 0.35 * defensive

# Late training (Phase 3): Emphasize advanced tactics
combined_score = 0.30 * random + 0.25 * greedy + 0.45 * defensive
```

---

### How to Use Anti-Overfitting Changes

#### Starting Fresh Training

```bash
python ai/train.py --phase phase1 --agent SpaceMarine_Infantry_Troop_RangedSwarm
```

The new settings will automatically be used if:
- Bot randomness is configured in `evaluation_bots.py`
- Reward penalties are balanced in agent's rewards config
- Evaluation weights are updated in `train.py`

#### Continue Existing Training

If your agent already learned bad habits:

1. **Option A: Continue training with new rewards**
   - Agent will slowly unlearn over-aggressive patterns
   - Takes 500-1000 episodes to adapt
   - Monitor `bot_eval/vs_random` for improvement

2. **Option B: Start fresh from Phase 1** (Recommended)
   - Faster to learn correct patterns
   - Use if current performance vs RandomBot is very poor (<40% win rate)
   - Delete old model and restart training

---

### Monitoring for Overfitting

Watch these metrics in TensorBoard:

```
bot_eval/vs_random      - Should improve from -0.5 to 0.0+
bot_eval/vs_greedy      - Should stay around 0.05-0.1
bot_eval/vs_defensive   - Should stay around 0.1-0.15
0_critical/combined     - Overall score should improve
```

**✅ Healthy performance**: All three bots within 0.2 reward range of each other

**⚠️ Overfitting symptom**: Large gap between random and others (>0.5 difference)

**Example healthy progression**:
```
Episode 1000:
  vs_random: -0.3, vs_greedy: 0.0, vs_defensive: 0.1  (Gap: 0.4 - concerning)

Episode 2000:
  vs_random: -0.1, vs_greedy: 0.1, vs_defensive: 0.15 (Gap: 0.25 - improving)

Episode 3000:
  vs_random: 0.05, vs_greedy: 0.15, vs_defensive: 0.2 (Gap: 0.15 - healthy!)
```

---

### Advanced: Self-Play Training (Future Enhancement)

For future implementation, consider training against copies of your own agent:

```python
# Pseudo-code for self-play
every N episodes:
    save current model as "opponent_snapshot"
    train against mix of:
        - 40% current agent
        - 30% RandomBot
        - 15% GreedyBot(randomness=0.15)
        - 15% DefensiveBot(randomness=0.15)
```

This forces continuous adaptation and prevents exploitation strategies.

---

### Configuration Summary

| Setting | Old Value | New Value | Impact |
|---------|-----------|-----------|--------|
| GreedyBot randomness | 0.0 | 0.15 | Unpredictable greedy play |
| DefensiveBot randomness | 0.0 | 0.15 | Unpredictable defensive play |
| Phase1 shoot_wait penalty | -30.0 | -10.0 | Less forced aggression |
| Phase1 move_away penalty | -3.0 | -1.0 | More tactical flexibility |
| RandomBot eval weight | 20% | 35% | Higher importance in model selection |
| DefensiveBot eval weight | 50% | 35% | Balanced with random |

---

### Troubleshooting Overfitting

**Agent still struggles vs RandomBot after 1000 episodes**:
- Increase GreedyBot/DefensiveBot randomness to 0.20-0.25
- Further reduce shoot_wait penalty to -5.0
- Consider starting fresh training from Phase 1
- Check that combined_score weights favor RandomBot performance

**Agent becomes too passive**:
- Reduce shoot_wait penalty (make more negative: -10.0 → -15.0)
- Check ent_coef isn't too low (should be 0.3-0.4 in Phase 1)
- Verify movement rewards aren't too high

**Agent performs poorly against all bots**:
- Rewards may be too balanced (not enough learning signal)
- Increase key rewards: kill_target, damage_target
- Check observation includes enough enemy information
- Verify bot randomness isn't too high (should be ≤0.20)

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