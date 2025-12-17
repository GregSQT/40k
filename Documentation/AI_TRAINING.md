# AI_TRAINING.md
## PPO Training Configuration Guide - Streamlined Edition

> **📍 Purpose**: Configure and monitor PPO training for W40K tactical AI
>
> **Status**: January 2025 - Configuration-focused edition (Updated: Added `0_critical/` dashboard, corrected metric namespaces)
>
> **⚠️ UPDATE**: Metrics section updated to reflect actual logged metrics:
> - Added `0_critical/` dashboard documentation (primary monitoring interface)
> - Corrected bot evaluation namespace: `bot_eval/` (not `eval/`)
> - Removed outdated `eval/mean_reward` and `eval/mean_ep_length` metrics
> - Added `game_critical/` metrics reference

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
- [Training Strategy](#-training-strategy)
  - [Unified Training (No Curriculum)](#unified-training-no-curriculum)
  - [Reward Design Philosophy](#reward-design-philosophy)
  - [Target Priority & Positioning](#target-priority--positioning)
- [Configuration Files](#️-configuration-files)
  - [training_config.json Structure](#trainingconfigjson-structure)
  - [rewards_config.json Structure](#rewardsconfigjson-structure)
- [Monitoring Training](#-monitoring-training)
  - [TensorBoard Metrics](#tensorboard-metrics)
  - [Success Indicators](#success-indicators)
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
python ai/train.py --config default      # Standard training (5000 episodes)
python ai/train.py --config debug        # Fast testing (50 episodes)
python ai/train.py --step                # Enable step logging for replay viewer
```

### Continue Existing Model
```bash
python ai/train.py --config default --model ./models/ppo_checkpoint.zip
```

### Key Paths
- **Training Configs**: `config/agents/<agent_name>/<agent_name>_training_config.json`
- **Reward Configs**: `rewards_master.json`
- **Models**: `./models/` (checkpoints saved here)
- **Logs**: `./tensorboard/` (TensorBoard data)
- **Step Logs**: `train_step.log` (detailed action logs for replay viewer)

---

## 🎬 REPLAY MODE

### Overview
The Replay Mode allows you to visualize training episodes step-by-step in the frontend. This is invaluable for understanding agent behavior and debugging tactical decisions.

### Generating Replay Logs
During training or evaluation, a `train_step.log` file is generated containing detailed action logs:

```bash
# Training with step logging enabled
python ai/train.py --config default --step
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

**Movement Phase Indicators:**
- **Ghost unit at origin**: Darkened ghost shows where unit started
- **Orange destination hexes**: All valid movement destinations highlighted

**Charge Phase Indicators:**
- **Ghost unit at origin**: Darkened ghost shows where charging unit started
- **Orange destination hexes**: All valid charge destinations (hexes adjacent to enemies within charge roll)
- **Charge roll badge**: Bottom-right badge on charging unit shows the 2d6 roll result
  - **Green badge**: Charge roll succeeded (light green text on dark green background)
  - **Red badge**: Charge roll failed (light red text on dark red background)

**Fight Phase Indicators:**
- **Crossed swords icon**: Appears on the fighting unit
- **Explosion icon**: Appears on the target unit

**Game Log Color Coding:**

*Charge Actions:*
- **Purple**: Successful charge action
- **Light Purple**: Failed charge (roll too low or chose not to charge)

*Shooting Actions (Blue Palette):*
- **Light Blue**: Failed hit or wound rolls (MISS)
- **Cyan**: Target succeeded save roll (SAVED)
- **Dark Blue**: Damage dealt to target (DMG)

*Combat/Fight Actions (Warm Palette):*
- **Yellow**: Failed hit or wound rolls
- **Orange**: Target succeeded save roll
- **Red**: Damage dealt to target

*Death:*
- **Black**: Unit destroyed (separate event after damage)

**Episode Information:**
- Bot opponent name (e.g., GreedyBot, RandomBot)
- Win/Loss/Draw result
- Total actions in episode
- Current action counter

### Log Format Reference

The `train_step.log` uses this format:

```
[HH:MM:SS] === EPISODE START ===
[HH:MM:SS] Scenario: default
[HH:MM:SS] Opponent: GreedyBot
[HH:MM:SS] Unit 1 (Intercessor) P0: Starting position (9, 12)
[HH:MM:SS] === ACTIONS START ===
[HH:MM:SS] T1 P0 MOVE : Unit 1(6, 15) MOVED from (9, 12) to (6, 15) [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 SHOOT : Unit 1(6, 15) SHOT at unit 5 - Hit:3+:6(HIT) Wound:4+:5(SUCCESS) Save:3+:2(FAILED) Dmg:1HP [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 CHARGE : Unit 2(9, 6) CHARGED unit 8 from (7, 13) to (9, 6) [Roll:7] [R:+3.0] [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 CHARGE : Unit 3(10, 5) WAIT [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 FIGHT : Unit 2(9, 6) FOUGHT unit 8 - Hit:3+:5(HIT) Wound:4+:4(SUCCESS) Save:4+:6(SAVED) Dmg:0HP [SUCCESS] [STEP: YES]
[HH:MM:SS] EPISODE END: Winner=0, Actions=68, Steps=68, Total=138
```

#### Action Log Formats

| Action | Format |
|--------|--------|
| MOVE | `Unit X(col, row) MOVED from (a, b) to (c, d)` |
| SHOOT | `Unit X(col, row) SHOT at unit Y - Hit:T+:R(HIT/MISS) Wound:T+:R(SUCCESS/FAIL) Save:T+:R(SAVED/FAILED) Dmg:NHP` |
| CHARGE | `Unit X(col, row) CHARGED unit Y from (a, b) to (c, d) [Roll:N]` where N is the 2d6 charge roll |
| CHARGE WAIT | `Unit X(col, row) WAIT` (unit chose not to charge or roll was too low) |
| FIGHT | `Unit X(col, row) FOUGHT unit Y - Hit:T+:R(HIT/MISS) Wound:T+:R(SUCCESS/FAIL) Save:T+:R(SAVED/FAILED) Dmg:NHP` |

### Best Practices

1. **Debug unexpected behavior**: Use replay to see exactly what the agent did
2. **Validate training progress**: Check if agent is making tactical decisions
3. **Compare episodes**: Replay episodes from different training stages to see improvement
4. **Check target selection**: Verify agent is prioritizing correct targets

---

## 🎯 TRAINING STRATEGY

### Unified Training (No Curriculum)

> **IMPORTANT**: This project uses **unified training from the start** - NO curriculum learning.
> See [RL_TRAINING_ROADMAP.md](RL_TRAINING_ROADMAP.md) for detailed rationale.

**Why NOT Curriculum Learning?**

Research and testing show curriculum learning **fails** for tactical games like this:

1. **Early phases teach wrong policies**
   - Phase 1 (simplified): Learns "standing still is optimal"
   - Phase 2 (full game): Must unlearn Phase 1 habits
   - Result: Negative transfer, worse performance

2. **Mechanics are interdependent**
   - Shooting effectiveness depends on positioning
   - Can't learn optimal shooting without walls/cover

3. **Dense rewards + simple exploration**
   - Agent gets rewards for shooting, moving, objectives
   - Random policy can discover basic strategies
   - No need for staged difficulty

**Evidence from testing:**
- Curriculum Phase 1→2 training: 18k episodes, 14% win rate
- Unified from-scratch training: 15k episodes, 50-60% win rate
- **Curriculum took MORE time and got WORSE results**

---

### Reward Design Philosophy

**Key Principles:**
- All game mechanics active from episode 1 (MOVE, SHOOT, CHARGE, FIGHT)
- All unit types in scenarios from start (mixed armies)
- Objectives active from episode 1
- Single reward configuration, no phased weights

**Current Reward Structure** (from `rewards_master.json`):
```json
{
  "SpaceMarineRanged": {
    "move_close": 0.2,
    "move_away": 0.4,
    "move_to_safe": 0.6,
    "move_to_rng": 0.8,
    "ranged_attack": 0.2,
    "enemy_killed_r": 0.4,
    "enemy_killed_lowests_hp_r": 0.6,
    "charge_success": 0.2,
    "attack": 0.4,
    "enemy_killed_m": 0.2,
    "win": 1,
    "lose": -1,
    "wait": -0.9
  }
}
```

---

### Target Priority & Positioning

The agent learns target prioritization through reward signals:

**Target Priority Formula:**
```
target_priority = VALUE / turns_to_kill
```

- **VALUE**: W40K point cost from unit profile (e.g., Termagant=6, Intercessor=19, Captain=80)
- **turns_to_kill**: How many activations needed to kill this target

**Example priorities (Intercessor selecting targets):**

| Target | VALUE | Turns to Kill | Priority Score |
|--------|-------|---------------|----------------|
| Captain (wounded, 2HP left) | 80 | 2 | **40** (highest) |
| Intercessor (wounded, 1HP) | 19 | 1 | **19** |
| Termagant | 6 | 1.35 | **4.4** |

This naturally encourages:
- High-value targets when killable (Captain > Intercessor)
- Finishing wounded enemies (faster kill = higher priority)
- Efficient use of attacks (don't waste on hard-to-kill targets)

---

## ⚙️ CONFIGURATION FILES

### training_config.json Structure

Training configs are per-agent at: `config/agents/<agent_name>/<agent_name>_training_config.json`

```json
{
  "default": {
    "total_episodes": 5000,              // How many episodes to train
    "max_turns_per_episode": 5,          // Game length limit
    "max_steps_per_turn": 200,           // Steps per turn limit

    "callback_params": {
      "checkpoint_save_freq": 50000,     // Save model every N steps
      "checkpoint_name_prefix": "ppo_checkpoint",
      "n_eval_episodes": 5,              // Evaluation frequency
      "bot_eval_freq": 100               // Bot eval every N episodes
    },

    "observation_params": {
      "obs_size": 300,                   // Total observation vector size
      "perception_radius": 25,           // Fog of war radius
      "max_nearby_units": 10,            // Max units to observe
      "max_valid_targets": 5             // Max targets to track
    },
    
    "model_params": {
      "learning_rate": 0.0003,           // How fast agent learns
      "n_steps": 256,                    // Steps before update
      "batch_size": 128,                 // Training batch size
      "n_epochs": 10,                    // Training epochs per update
      "gamma": 0.95,                     // Future reward discount
      "gae_lambda": 0.95,                // Advantage estimation
      "clip_range": 0.2,                 // PPO clipping parameter
      "ent_coef": 0.10,                  // Exploration bonus
      "vf_coef": 1.0,                    // Value function weight
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

### rewards_master.json Structure

Each unit archetype has a single reward profile. No phased profiles.

**Reward Categories** (from `rewards_master.json`):

```json
{
  "SpaceMarineRanged": {
    // Movement rewards
    "move_close": 0.2,           // Moving closer to enemy
    "move_away": 0.4,            // Moving away (for ranged units)
    "move_to_safe": 0.6,         // Moving to safety
    "move_to_rng": 0.8,          // Moving into shooting range
    "move_to_charge": 0.2,       // Moving into charge range

    // Combat rewards
    "ranged_attack": 0.2,        // Shooting action
    "enemy_killed_r": 0.4,       // Kill with ranged
    "enemy_killed_lowests_hp_r": 0.6,  // Kill lowest HP target
    "enemy_killed_no_overkill_r": 0.8, // Kill without overkill
    "charge_success": 0.2,       // Successful charge
    "attack": 0.4,               // Melee attack
    "enemy_killed_m": 0.2,       // Kill in melee

    // Penalties
    "being_charged": -0.4,       // Getting charged
    "loose_hp": -0.4,            // Taking damage
    "killed_in_melee": -0.8,     // Dying in melee
    "atk_wasted_r": -0.8,        // Wasted ranged attack
    "atk_wasted_m": -0.8,        // Wasted melee attack
    "wait": -0.9,                // Waiting instead of acting

    // Game outcome
    "win": 1,
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

> **💡 TIP:** This section provides quick-start monitoring guidance. For comprehensive metric analysis, troubleshooting patterns, and hyperparameter tuning, see [AI_METRICS.md](AI_METRICS.md)

### TensorBoard Metrics

Start TensorBoard:
```bash
tensorboard --logdir=./tensorboard/
```

#### 🎯 **Quick Start: The `0_critical/` Dashboard**

**For immediate training monitoring, start here:**

Navigate to the `0_critical/` namespace in TensorBoard - it contains **10 essential metrics** optimized for hyperparameter tuning:

**Primary Metrics to Check Daily:**
- `0_critical/a_bot_eval_combined` - **Your primary goal** (overall competence vs all bots)
- `0_critical/b_win_rate_100ep` - Recent 100-episode performance trend
- `0_critical/g_approx_kl` - Policy stability (<0.02 = healthy)
- `0_critical/h_entropy_loss` - Exploration level (should decrease gradually)
- `0_critical/e_explained_variance` - Value function quality (target: >0.70 early, >0.85 late training)

**✅ Healthy Training:** All `0_critical/` metrics trending toward targets
**⚠️ Red Flag:** Any metric outside range for 200+ episodes needs intervention

**For detailed metric analysis**, see [AI_METRICS.md](AI_METRICS.md#-start-here-0_critical-dashboard)

---

#### **Other Key Metrics**

| Namespace | Metric | What It Shows | Good Trend |
|-----------|--------|---------------|------------|
| `rollout/` | `ep_rew_mean` | Average episode reward | Increasing |
| `rollout/` | `ep_len_mean` | Episode length | Stable or decreasing |
| `train/` | `entropy_loss` | Exploration level | Decreasing gradually |
| `train/` | `policy_loss` | Policy improvement | Decreasing |
| `train/` | `value_loss` | Value estimation | Decreasing then stable |
| `game_critical/` | `win_rate_100ep` | Rolling win rate | Increasing to target |
| `game_critical/` | `invalid_action_rate` | Action masking health | <5% (ideally <2%) |
| `bot_eval/` | `vs_random` | Performance vs RandomBot | Improving |
| `bot_eval/` | `vs_greedy` | Performance vs GreedyBot | Improving |
| `bot_eval/` | `vs_defensive` | Performance vs DefensiveBot | Improving |
| `bot_eval/` | `combined` | Overall bot evaluation | Increasing to 0.70+ |

### Success Indicators

**Early Training (0-1000 episodes):**
- `rollout/ep_rew_mean`: Should increase from negative to positive
- Wait penalties: Should decrease sharply
- Win rate vs Random bot: 40%+ after 500 episodes

**Mid Training (1000-3000 episodes):**
- `rollout/ep_rew_mean`: Should continue increasing steadily
- Win rate vs Greedy bot: 50%+ after 2000 episodes
- Invalid action rate: Should drop below 5%

**Late Training (3000+ episodes):**
- `rollout/ep_rew_mean`: Steady high values
- Combined bot evaluation: 60%+
- Win rate vs Tactical bots: 50%+ after 4000 episodes

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
# Automatic evaluation during training (configured in training_config.json)
python ai/train.py --config default  # bot_eval_freq: 100 episodes

# Manual evaluation after training
python ai/evaluation.py --model ./models/ppo_checkpoint.zip --opponent tactical --episodes 20
```

### Win Rate Benchmarks

| Training Stage | vs Random | vs Greedy | vs Tactical |
|----------------|-----------|-----------|-------------|
| Start          | 30-40%    | 10-20%    | 0-5%        |
| 1000 episodes  | 60-70%    | 40-50%    | 20-30%      |
| 3000 episodes  | 80-90%    | 60-70%    | 40-50%      |
| 5000 episodes  | 90%+      | 75-85%    | 55-65%      |

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

**Location**: `rewards_master.json`

**Problem**: Overly harsh penalties force hyper-aggressive play that becomes predictable.

**Example adjustments**:
```json
{
  "SpaceMarineRanged": {
    "wait": -0.9,          // Moderate penalty (not too harsh)
    "move_away": 0.4       // Allow tactical retreat
  }
}
```

**Why this helps**:
- Very harsh wait penalties forced hyper-aggressive play (always seeking shots)
- Aggressive strategies are predictable and exploitable by random opponents
- Moderate values allow tactical patience and positional flexibility

**Tuning recommendations**:
- **Wait penalty**: -0.5 to -1.0 (avoid -2.0+ which forces reckless play)
- **Move penalties**: Keep balanced to allow tactical flexibility
- **Win/lose**: Keep at ±1.0 for stable training

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

**Recommended weighting**:

```python
# Balanced weighting (RECOMMENDED)
combined_score = 0.35 * random + 0.30 * greedy + 0.35 * defensive
```

---

### How to Use Anti-Overfitting Changes

#### Starting Fresh Training

```bash
python ai/train.py --config default
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

2. **Option B: Start fresh** (Recommended)
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
- Further reduce wait penalty to -0.5
- Consider starting fresh training
- Check that combined_score weights favor RandomBot performance

**Agent becomes too passive**:
- Increase wait penalty (make more negative: -0.5 → -1.0)
- Check ent_coef isn't too low (should be 0.10+)
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

**Avoid**: Setting `learning_rate` > 0.001

---

### When Training Is Too Slow

**Problem**: 50+ hours for training run

**Try:**
1. Reduce `total_episodes` (use debug config first)
2. Reduce `n_eval_episodes` from 5 → 2
3. Increase `n_steps` from 256 → 1024 (fewer updates)
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
python ai/train.py --config default --device cpu
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

**Error**: `Reward key not found: SpaceMarineXXX`
- **Cause**: Unit archetype not defined in rewards_master.json
- **Fix**: Add the missing reward profile to rewards_master.json

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
python ai/train.py --config debug           # Fast test (50 episodes)
python ai/train.py --config default         # Standard training (5000 episodes)
python ai/train.py --config default --model X  # Continue from checkpoint
python ai/train.py --config default --step  # With step logging for replay
python ai/train.py --device cpu             # Force CPU

# Monitoring
tensorboard --logdir=./tensorboard/         # View training metrics

# Evaluation
python ai/evaluation.py --model X --opponent tactical --episodes 20

# Key Paths
config/agents/<agent>/<agent>_training_config.json  # Training parameters
rewards_master.json                         # Reward definitions
./models/                                   # Saved checkpoints
./tensorboard/                              # TensorBoard logs
train_step.log                              # Step log for replay viewer

# Success Criteria (5000 episodes)
vs Random: 90%+
vs Greedy: 75%+
vs Tactical: 55%+
```

---

## 🎯 SUMMARY

**This guide focuses on WHAT TO CONFIGURE, not how the system works internally.**

**Key Principle**: Train with full game complexity from the start - NO curriculum learning.

**For implementation details:**
- Observation system → `w40k_core.py`
- Reward logic → `reward_mapper.py`
- Training loop → `ai/train.py`
- Game rules → `AI_TURN.md`, `AI_IMPLEMENTATION.md`

**For training configuration:**
- Read this document (AI_TRAINING.md)
- Modify agent training config and `rewards_master.json`
- Monitor TensorBoard metrics
- Adjust hyperparameters based on observed behavior

**Remember**: Training is iterative. Start with debug config, validate quickly, then scale up.