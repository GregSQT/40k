# AI_METRICS.md
## Training Optimization Through Metrics Analysis

> **📍 Purpose**: Deep dive into metrics-driven training optimization for W40K tactical AI
>
> **Status**: January 2025 - Expert optimization guide (Updated: Corrected metric namespaces to match actual code)
>
> **Companion Document**: [AI_TRAINING.md](AI_TRAINING.md) - Configuration and setup
>
> **⚠️ IMPORTANT CORRECTION**: This document has been updated to use correct metric namespaces:
> - Bot evaluation metrics use `bot_eval/` namespace (not `eval_bots/`)
> - Bot metric names: `vs_random`, `vs_greedy`, `vs_defensive`, `combined` (not `vs_random_bot`, etc.)
> - Added documentation for the `0_critical/` dashboard - **START HERE** for training monitoring

---

## 📋 TABLE OF CONTENTS

- [Why Metrics Matter](#why-metrics-matter)
- [Core Metrics Explained](#core-metrics-explained)
  - [Training Metrics (PPO Internals)](#training-metrics-ppo-internals)
  - [Critical Metrics Quick Reference](#-critical-metrics-quick-reference) ⭐ **START HERE**
    - [0_critical/ Dashboard](#-start-here-0_critical-dashboard) ⭐⭐ **PRIMARY DASHBOARD**
    - [Game Critical Metrics](#game-critical-metrics)
  - [Game Metrics (Performance Indicators)](#game-metrics-performance-indicators)
  - [Evaluation Metrics (Bot Comparisons)](#evaluation-metrics-bot-comparisons)
- [Metric Relationships](#metric-relationships)
  - [Correlation Patterns](#correlation-patterns)
  - [Causal Relationships](#causal-relationships)
  - [Leading vs Lagging Indicators](#leading-vs-lagging-indicators)
- [Pattern Library](#pattern-library)
  - [Good Learning Patterns](#good-learning-patterns)
  - [Bad Learning Patterns](#bad-learning-patterns)
  - [Ambiguous Patterns](#ambiguous-patterns)
- [Optimization Workflows](#optimization-workflows)
  - [Daily Monitoring Routine](#daily-monitoring-routine)
  - [Diagnostic Decision Tree](#diagnostic-decision-tree)
  - [When to Intervene vs Wait](#when-to-intervene-vs-wait)
- [Hyperparameter Tuning](#hyperparameter-tuning)
  - [Metric-Based Adjustment Guide](#metric-based-adjustment-guide)
  - [Detailed Parameter Effects](#detailed-parameter-effects)
- [Early Stopping Criteria](#early-stopping-criteria)
- [Advanced Techniques](#advanced-techniques)
  - [Multi-Metric Analysis](#multi-metric-analysis)
  - [Historical Trend Analysis](#historical-trend-analysis)
  - [Predictive Indicators](#predictive-indicators)
- [Case Studies](#case-studies)
- [Quick Diagnostic Reference](#quick-diagnostic-reference)

---

## WHY METRICS MATTER

### The Training Optimization Challenge

Training a tactical AI without metrics is like flying blind:
- ❌ No way to know if training is working
- ❌ Can't diagnose problems until it's too late
- ❌ Waste hours on failing approaches
- ❌ Miss opportunities to improve

**With proper metrics analysis:**
- ✅ Detect problems within minutes (not hours)
- ✅ Predict final performance early
- ✅ Adjust hyperparameters with confidence
- ✅ Understand WHY agent behaves certain ways

### What This Document Provides

This is an **expert-level playbook** for metrics-driven optimization. You'll learn:

1. **What each metric means** - Not just definitions, but practical interpretation
2. **How metrics relate** - Correlations, causality, and dependencies
3. **Pattern recognition** - What good/bad training looks like with real numbers
4. **Decision-making** - When to adjust, when to wait, when to restart
5. **Optimization workflows** - Step-by-step diagnostic processes

---

## CORE METRICS EXPLAINED

### Training Metrics (PPO Internals)

These metrics reveal the health of the PPO learning algorithm itself.

#### `train/approx_kl`
**What it is:** KL divergence between old and new policy (how much policy changed)

**Why it matters:** PPO's core safety mechanism. Measures policy update size.

**Interpretation:**
- **< 0.01:** Policy changing very conservatively (might be too slow)
- **0.01 - 0.02:** Healthy policy updates (sweet spot)
- **0.02 - 0.03:** Moderate policy changes (acceptable)
- **> 0.03:** Policy changing too fast (risk of instability)
- **> 0.05:** Policy diverging (training likely to fail)

**Action triggers:**
- Consistently > 0.03 → Reduce `learning_rate` by 50%
- Consistently < 0.005 → Consider increasing `learning_rate` by 50%

---

#### `train/clip_fraction`
**What it is:** Percentage of policy updates that were clipped by PPO mechanism

**Why it matters:** Indicates if PPO's clipping is active and working correctly.

**Interpretation:**
- **< 10%:** Very conservative updates (might be too cautious)
- **10% - 30%:** Healthy clipping range (PPO working as intended)
- **30% - 50%:** High clipping (policy changing significantly)
- **> 50%:** Excessive clipping (policy trying to change too much)

**Action triggers:**
- Consistently < 10% → Increase `clip_range` from 0.2 to 0.25
- Consistently > 50% → Reduce `learning_rate` and/or `clip_range`

---

#### `train/entropy_loss`
**What it is:** Negative of policy entropy (lower = more deterministic)

**Why it matters:** Measures exploration vs exploitation balance.

**Interpretation:**
- **-2.0 to -1.5:** High exploration (early training, trying many actions)
- **-1.5 to -1.0:** Moderate exploration (learning phase)
- **-1.0 to -0.5:** Low exploration (refining tactics)
- **-0.5 to 0.0:** Very deterministic (near convergence)
- **Near 0.0 early:** DANGER - collapsed too fast, stuck in local optimum

**Action triggers:**
- Drops to near 0 within 20 episodes → Increase `ent_coef`, restart training
- Stays high (< -1.5) after 200 episodes → Reduce `ent_coef`

---

#### `train/explained_variance`
**What it is:** How well value function predicts actual returns (R² score)

**Why it matters:** Value function quality directly impacts advantage estimates.

**Interpretation:**
- **< 0.50:** Value function very poor (random predictions)
- **0.50 - 0.70:** Learning but weak (network too small or learning rate too low)
- **0.70 - 0.85:** Decent value function (acceptable for early phases)
- **0.85 - 0.95:** Strong value function (good for final phases)
- **> 0.95:** Excellent value function (near optimal)

**Action triggers:**
- Stuck < 0.60 → Increase network size: `net_arch` [128,128] → [256,256]
- Stuck < 0.70 in Phase 2+ → Increase `vf_coef` from 0.5 to 1.0

---

#### `train/policy_loss`
**What it is:** Policy gradient loss (how much policy is improving)

**Why it matters:** Indicates if policy is learning from experiences.

**Interpretation:**
- **Should decrease over time** (approaching zero)
- **Large values:** Policy making big updates
- **Near zero:** Policy converged or stuck
- **Oscillating:** Unstable learning

**Action triggers:**
- Not decreasing after 100 episodes → Check `learning_rate`, may be too low
- Oscillating wildly → Reduce `learning_rate`

---

#### `train/value_loss`
**What it is:** Value function prediction error

**Why it matters:** Indicates if value function is learning to predict returns.

**Interpretation:**
- **Should decrease then stabilize**
- **Not decreasing:** Value function not learning
- **Increasing:** Value function getting worse (policy changing too fast)

**Action triggers:**
- Not decreasing → Increase `vf_coef`, check network capacity
- Increasing → Reduce `learning_rate`

---

## 🎯 CRITICAL METRICS QUICK REFERENCE

These are the most important metrics to watch in TensorBoard.

### **⭐ START HERE: `0_critical/` Dashboard**

The `0_critical/` namespace contains **THE 10 ESSENTIAL METRICS** for hyperparameter tuning. All metrics are smoothed (20-episode rolling average) for clear trends.

**TIP:** Open TensorBoard and navigate to the `0_critical/` namespace first - it contains everything you need for tuning.

| Metric | What It Measures | Target Value | Critical For |
|--------|------------------|--------------|--------------|
| **0_critical/a_bot_eval_combined** | Weighted win rate vs all bots | 0.55+ (Phase 2)<br>0.70+ (Phase 3) | **PRIMARY GOAL** - Overall competence |
| **0_critical/b_win_rate_100ep** | Rolling 100-episode win rate | Phase 1: 60%+<br>Phase 2: 70%+<br>Phase 3: 75%+ | Self-play performance |
| **0_critical/c_episode_reward_smooth** | Smoothed episode reward | Increasing trend | Learning progress signal |
| **0_critical/d_loss_mean** | Combined policy + value loss | Decreasing then stable | Training convergence |
| **0_critical/e_explained_variance** | Value function quality (R²) | >0.70 (Phase 1)<br>>0.85 (Phase 2+) | Value network capacity |
| **0_critical/f_clip_fraction** | % of clipped policy updates | 0.10-0.30 | Tune `learning_rate` |
| **0_critical/g_approx_kl** | Policy change magnitude | <0.02 (ideally 0.01-0.015) | Policy stability |
| **0_critical/h_entropy_loss** | Exploration level | -2.0 to -0.5 (decreasing) | Tune `ent_coef` |
| **0_critical/i_gradient_norm** | Gradient magnitude | <10 | No gradient explosion |
| **0_critical/j_immediate_reward_ratio** | Immediate vs total reward | <0.9 | Reward balance check |

**How to use this dashboard:**
1. Open TensorBoard: `tensorboard --logdir=./tensorboard/`
2. Navigate to Scalars → `0_critical/`
3. Check all 10 metrics are trending correctly
4. Use table above to diagnose issues

---

### **Game Critical Metrics**

These are the most important gameplay metrics to watch in the `game_critical/` and `bot_eval/` namespaces in TensorBoard.

| Metric | What It Measures | Target Value | If Too Low (<) | If Too High (>) | Notes |
|--------|------------------|--------------|----------------|-----------------|-------|
| **game_critical/episode_reward** | Total reward per episode | Phase 1: 0+<br>Phase 2: +10 to +25<br>Phase 3: +25 to +50+ | • Check reward config balance<br>• Increase key action rewards<br>• Reduce penalties | • Possible reward hacking<br>• Review exploited rewards<br>• Add balancing penalties | Should increase steadily. Sudden drops = policy collapse |
| **game_critical/episode_length** | Steps per episode | 50-150 steps<br>(stable) | • Agent dying too fast<br>• Increase defensive rewards<br>• Reduce aggression penalties | • Agent too passive<br>• Reduce wait penalty<br>• Increase action rewards | Increasing trend = agent stalling. Stable = good |
| **game_critical/win_rate_100ep** | Rolling 100-episode win rate | Phase 1: 60%+<br>Phase 2: 70%+<br>Phase 3: 75%+ | • Increase training episodes<br>• Adjust reward balance<br>• Check observation quality | • Good! Advance to next phase<br>• Consider harder opponents | Primary success metric. Must be stable, not just lucky streak |
| **game_critical/units_killed_vs_lost_ratio** | Kill/death ratio | 1.5+ (killing more than losing) | • Improve combat rewards<br>• Reduce defensive penalties<br>• Check target selection | • Excellent performance<br>• Consider phase advancement | <1.0 = losing units. >2.0 = dominating |
| **game_critical/invalid_action_rate** | % of invalid actions | <5% (ideally <2%) | N/A - this is good! | • Action masking broken<br>• Observation quality issue<br>• Network capacity problem | >10% persistently = serious problem requiring restart |
| **bot_eval/vs_random** | Reward vs RandomBot | 0.0+ (positive) | • Agent worse than random<br>• Major training problem<br>• Check overfitting | • Good! Should beat random<br>• Target: -0.3 to +0.1 range | Baseline competence. Failure here = critical issue |
| **bot_eval/vs_greedy** | Reward vs GreedyBot | 0.05 to 0.15 | • Target selection poor<br>• Increase priority rewards<br>• Check tactical bonuses | • Agent exploiting patterns<br>• Increase bot randomness<br>• Balance rewards | Tests target prioritization. Should be moderate |
| **bot_eval/vs_defensive** | Reward vs DefensiveBot | 0.10 to 0.20 | • Tactical positioning weak<br>• Increase positioning rewards<br>• Check movement bonuses | • Agent exploiting patterns<br>• Increase bot randomness<br>• More diverse scenarios | Tests tactical mastery. Hardest opponent |
| **bot_eval/combined** | Weighted average of all bots | 0.55+ (Phase 2)<br>0.70+ (Phase 3) | • Overall performance weak<br>• Review all reward categories<br>• Check observation system | • Excellent! Phase complete<br>• Save model and advance | Single number for overall competence. Used for model selection |

### How to Use This Table

1. **During Training**: Check these metrics every 100-200 episodes
2. **Red Flags**: Any metric outside target range for 200+ episodes needs intervention
3. **Green Lights**: All metrics in target range = training healthy
4. **Progression**: Metrics should trend toward targets over time, not stay flat

### Priority Order

**For daily monitoring:**
1. **0_critical/** dashboard - Check all 10 metrics first
2. **bot_eval/combined** (in 0_critical/) - Primary goal metric
3. **invalid_action_rate** - Fix immediately if >10%
4. **episode_reward** - Must be increasing (even slowly)
5. **win_rate_100ep** - Primary success indicator

**TIP:** If all `0_critical/` metrics are healthy, your training is on track. Dive into detailed namespaces only when debugging specific issues.

---

### Game Metrics (Performance Indicators)

These metrics measure the agent's actual gameplay performance.

#### `rollout/ep_rew_mean`
**What it is:** Average reward per episode over recent rollout

**Why it matters:** Primary indicator of agent improvement.

**Interpretation:**
- **Should steadily increase throughout training**
- **Negative early:** Normal in Phase 1 (learning penalties)
- **Positive and increasing:** Agent learning successfully
- **Plateau:** Need to increase exploration or adjust rewards
- **Decreasing:** Policy collapse or reward hacking

**Phase targets:**
- Phase 1: -10 → 0 → +10
- Phase 2: +10 → +25
- Phase 3: +25 → +50+

---

#### `rollout/ep_len_mean`
**What it is:** Average episode length (number of steps)

**Why it matters:** Indicates if agent is efficient or stalling.

**Interpretation:**
- **Very high:** Agent being passive (too much waiting)
- **Very low:** Agent being overly aggressive or dying quickly
- **Stable:** Good sign, agent has consistent strategy

**Action triggers:**
- Increasing over time → Reduce `wait` penalty in rewards_config.json
- Very short episodes with low rewards → Agent dying too fast, adjust tactics

---

#### Win Rate Metrics
**What they are:** Percentage of episodes agent wins

**Why they matter:** Direct measure of tactical competence.

**Interpretation by phase:**

**Phase 1 (Learn Shooting):**
- Target: 60%+ win rate vs Random bot
- Indicates basic combat effectiveness

**Phase 2 (Learn Priorities):**
- Target: 70%+ win rate vs Greedy bot
- Indicates target selection skills

**Phase 3 (Full Tactics):**
- Target: 75%+ win rate vs Tactical bot
- Indicates tactical mastery

---

### Evaluation Metrics (Bot Comparisons)

These metrics compare agent performance against scripted opponents.

#### `bot_eval/vs_random`
**What it is:** Win rate against random action bot

**Why it matters:** Baseline competence check. Any learning agent should beat random.

**Interpretation:**
- **< 0.50:** Agent worse than random (serious problem)
- **0.50 - 0.70:** Learning basics
- **0.70 - 0.85:** Competent gameplay
- **> 0.85:** Strong gameplay (should advance)

---

#### `bot_eval/vs_greedy`
**What it is:** Win rate against greedy bot (shoots nearest enemy)

**Why it matters:** Tests if agent learned target prioritization.

**Interpretation:**
- **< 0.30:** Agent has poor target selection
- **0.30 - 0.50:** Learning priorities
- **0.50 - 0.70:** Good target selection
- **> 0.70:** Excellent priorities

---

#### `bot_eval/vs_defensive`
**What it is:** Win rate against defensive bot (uses cover, cautious)

**Why it matters:** Tests if agent learned tactical positioning.

**Interpretation:**
- **< 0.20:** Agent ignores positioning
- **0.20 - 0.40:** Learning tactics
- **0.40 - 0.60:** Good tactical play
- **> 0.60:** Excellent tactics

---

#### `bot_eval/combined`
**What it is:** Weighted average of all bot win rates

**Why it matters:** Single number representing overall competence.

**Interpretation:**
- **< 0.40:** Beginner level
- **0.40 - 0.55:** Intermediate
- **0.55 - 0.70:** Advanced
- **> 0.70:** Expert level

---

## METRIC RELATIONSHIPS

### Correlation Patterns

Understanding how metrics move together helps diagnose root causes.

#### Strong Positive Correlations

**`explained_variance` ↑ + `rollout/ep_rew_mean` ↑**
- Better value function → better advantage estimates → better policy updates
- **If broken:** Value function not learning → check network capacity

**`approx_kl` ↓ + `entropy_loss` ↓ (becoming less negative)**
- Policy becoming more confident and stable over time
- **Normal progression** in successful training

**Win rate ↑ + `bot_eval/combined` ↑**
- Self-play performance matches bot evaluation
- **Good sign:** Agent generalizing, not overfitting

---

#### Strong Negative Correlations

**`train/entropy_loss` → 0 (deterministic) + Win rate stops improving**
- Policy collapsed to deterministic too early
- Stuck in local optimum
- **Fix:** Increase `ent_coef`, restart

**`approx_kl` ↑ + `clip_fraction` ↑**
- Policy trying to change too much too fast
- PPO's safety mechanism activating heavily
- **Fix:** Reduce `learning_rate`

---

#### Causal Relationships

**`learning_rate` → `approx_kl` → `clip_fraction`**
- High LR causes large policy changes (high KL)
- Large changes trigger clipping mechanism
- **Intervention point:** Adjust LR first

**`ent_coef` → `entropy_loss` → Exploration behavior**
- High ent_coef keeps policy stochastic
- Enables discovering new tactics
- **Intervention point:** Adjust ent_coef to control exploration

**Network size → `explained_variance` → Policy quality**
- Larger network → better value predictions
- Better values → better policy updates
- **Intervention point:** Increase net_arch if variance stuck low

---

### Leading vs Lagging Indicators

#### Leading Indicators (Predict future performance)

**`train/explained_variance` (Early Phase 1)**
- If > 0.70 by episode 20 → Training likely to succeed
- If < 0.50 by episode 50 → Training likely to fail

**`train/entropy_loss` (First 10 episodes)**
- If drops to near 0 → Will get stuck in local optimum
- If stays high (< -1.5) → Will explore effectively

**`approx_kl` stability (First 50 episodes)**
- If consistently < 0.02 → Stable, will converge
- If frequently > 0.03 → Unstable, will oscillate or collapse

---

#### Lagging Indicators (Confirm past trends)

**Win rate**
- Reflects policy learned 50-100 episodes ago
- Changes slowly, not useful for immediate decisions

**`bot_eval/combined`**
- Only evaluated every N episodes
- Good for phase advancement, bad for real-time tuning

---

## PATTERN LIBRARY

### Good Learning Patterns

#### Pattern: Healthy Phase 1 ✅

```
Episodes 1-50:
  win_rate:          20% → 25% → 30% → 40% → 45%
  explained_var:     0.30 → 0.45 → 0.60 → 0.75 → 0.80
  entropy_loss:      -2.0 → -1.5 → -1.2 → -1.0 → -0.9
  approx_kl:         0.03 → 0.02 → 0.015 → 0.012 → 0.010
  rollout/ep_rew_mean: -8 → -3 → 2 → 8 → 15
```

**Characteristics:**
- ✅ Steady improvement across all metrics
- ✅ Explained variance reaching 0.80+ (good value function)
- ✅ Entropy decreasing gradually (policy becoming more confident)
- ✅ KL divergence decreasing (stable updates)
- ✅ Rewards going from negative to positive

**Action:** Continue training, advance to Phase 2 when win rate > 60%

---

#### Pattern: Healthy Phase 2 ✅

```
Episodes 51-550:
  win_rate:          45% → 52% → 58% → 63% → 67%
  vs_random:         0.55 → 0.62 → 0.68 → 0.73 → 0.78
  kill_ratio:        0.8 → 0.95 → 1.1 → 1.25 → 1.35
  explained_var:     0.80 → 0.83 → 0.87 → 0.90 → 0.92
  approx_kl:         0.015 → 0.012 → 0.010 → 0.009 → 0.008
```

**Characteristics:**
- ✅ Win rate improving steadily
- ✅ Bot performance scaling with self-play
- ✅ Kill ratio improving (better target selection)
- ✅ Value function continuing to improve
- ✅ Policy updates stable and decreasing

**Action:** Continue training, advance to Phase 3 when win rate > 70%

---

#### Pattern: Healthy Phase 3 ✅

```
Episodes 551-1550:
  win_rate:          67% → 70% → 73% → 75% → 77%
  vs_greedy:         0.45 → 0.52 → 0.58 → 0.63 → 0.67
  vs_defensive:      0.30 → 0.35 → 0.42 → 0.48 → 0.53
  combined:          0.45 → 0.50 → 0.56 → 0.61 → 0.66
  explained_var:     0.90 → 0.92 → 0.93 → 0.94 → 0.95
```

**Characteristics:**
- ✅ All metrics improving together
- ✅ Balanced performance across all bot difficulties
- ✅ Combined score trending toward 0.70+
- ✅ Value function near optimal (0.95)

**Action:** Continue until combined_score > 0.75, then complete

---

### Bad Learning Patterns

#### Pattern 1: Plateau (Stuck) ❌

```
Episodes 20-50:
  win_rate:      30% → 31% → 32% → 31% → 32% (STUCK)
  explained_var: 0.58 → 0.60 → 0.61 → 0.60 → 0.61 (NOT IMPROVING)
  episode_reward: 8.5 → 8.7 → 8.9 → 8.6 → 8.8 (FLAT)
  approx_kl:     0.008 → 0.007 → 0.007 → 0.006 (TOO LOW)
```

**Root Cause:** Network capacity too small OR rewards too sparse OR learning rate too low

**Symptoms:**
- Win rate stuck below target for 30+ episodes
- Explained variance < 0.70 and not improving
- Reward values plateau
- approx_kl very low (policy barely changing)

**Diagnosis:**
1. Check `explained_variance`: If < 0.60 → Network too small
2. Check `approx_kl`: If < 0.01 consistently → LR too low
3. Check episode_reward components: If few positive rewards → Rewards too sparse

**Fix Priority:**
1. **First try:** Increase network size: `net_arch` [128,128] → [256,256]
2. **If that fails:** Add more dense rewards (intermediate progress signals)
3. **Last resort:** Increase exploration: `ent_coef` 0.05 → 0.15

---

#### Pattern 2: Oscillation (Unstable) ❌

```
Episodes 300-350:
  win_rate:       55% → 62% → 48% → 70% → 45% → 68% (WILD SWINGS)
  approx_kl:      0.025 → 0.035 → 0.028 → 0.042 → 0.031 (TOO HIGH)
  clip_fraction:  0.45 → 0.52 → 0.48 → 0.55 → 0.50 (TOO MUCH CLIPPING)
  episode_reward: 18 → 25 → 12 → 28 → 10 (VOLATILE)
```

**Root Cause:** Learning rate too high, policy changing too fast

**Symptoms:**
- Win rate swings >15% between evaluations
- `approx_kl` frequently > 0.03
- `clip_fraction` consistently > 40%
- Reward values highly volatile

**Diagnosis:**
1. Check `approx_kl` over 50 episodes: If avg > 0.025 → LR too high
2. Check `clip_fraction`: If avg > 45% → Policy changing drastically
3. Check win_rate volatility: If swings > 15% → Unstable policy

**Fix Priority:**
1. **Immediate:** Reduce `learning_rate` by 50%: 0.0003 → 0.00015
2. **If still unstable:** Reduce `clip_range`: 0.2 → 0.15
3. **Add stability:** Increase `batch_size`: 64 → 128 (more stable gradients)

---

#### Pattern 3: Overfitting (Self-Play Bias) ❌

```
Episodes 800-1000:
  win_rate (self-play):  78% → 80% → 82% → 83% (GREAT)
  vs_random:             0.82 → 0.84 → 0.85 → 0.86 (GREAT)
  vs_greedy:             0.45 → 0.43 → 0.41 → 0.38 (DECLINING!)
  vs_defensive:          0.28 → 0.25 → 0.23 → 0.20 (WORSE!)
  combined:              0.52 → 0.51 → 0.50 → 0.48 (DECLINING!)
```

**Root Cause:** Agent overfitting to random opponent, not generalizing

**Symptoms:**
- High self-play win rate but poor bot evaluation
- Performance vs harder bots declining
- Agent has "blind spots" in tactics
- Combined score decreasing despite high self-play wins

**Diagnosis:**
1. Compare self-play vs bot eval trends: Diverging = overfitting
2. Check individual bot performance: If one declining = specific weakness
3. Watch replays: Agent may ignore cover, positioning, or defensive play

**Fix Priority:**
1. **Immediate:** More diverse training scenarios (add scenarios to `config/agents/<agent>/scenarios/`)
2. **Adjust rewards:** Increase rewards for defensive tactics (cover, safe positioning)
3. **Evaluation:** Increase bot evaluation frequency to catch overfitting early
4. **Consider:** Train against bot opponents occasionally (not just self-play)

---

#### Pattern 4: Early Collapse (Entropy Death) ❌

```
Episodes 5-15:
  entropy_loss:  -2.0 → -1.0 → -0.3 → -0.1 → -0.05 (COLLAPSED TOO FAST)
  win_rate:      22% → 25% → 28% → 28% → 28% (STUCK)
  clip_fraction: 0.05 → 0.03 → 0.02 → 0.02 (NO EXPLORATION)
  approx_kl:     0.015 → 0.008 → 0.005 → 0.003 (BARELY CHANGING)
```

**Root Cause:** Policy became deterministic too early, stuck in local optimum

**Symptoms:**
- Entropy near zero within 20 episodes
- Win rate improves slightly then plateaus
- Clip fraction very low (policy not changing)
- approx_kl very low (no policy updates)

**Diagnosis:**
1. Check `entropy_loss` trajectory: If drops to near 0 in < 20 eps = collapsed
2. Check `clip_fraction`: If < 5% = policy frozen
3. Check win rate: If plateau + low entropy = stuck in local optimum

**Fix Priority:**
1. **Must restart:** Increase `ent_coef`: 0.01 → 0.10 or higher
2. **Before restart:** Check initial policy: May be biased by poor initialization
3. **Prevention:** Start Phase 1 with high ent_coef (0.20) to ensure exploration

---

### Ambiguous Patterns

#### Pattern: High Entropy, Low Win Rate (Interpretation Needed)

```
Episodes 100-150:
  entropy_loss:  -1.8 → -1.7 → -1.9 → -1.8 (STAYING HIGH)
  win_rate:      35% → 36% → 34% → 37% (LOW, FLAT)
  explained_var: 0.72 → 0.74 → 0.76 → 0.78 (IMPROVING)
```

**Possible Interpretations:**

**Scenario A: Still Exploring (GOOD)**
- Value function improving → Agent learning
- High entropy → Trying many strategies
- Win rate will improve once exploration decreases
- **Action:** Wait 50 more episodes, should improve

**Scenario B: Too Much Exploration (BAD)**
- Policy too random to execute consistent tactics
- Agent can't converge on good strategy
- **Action:** Reduce `ent_coef` from 0.20 to 0.10

**How to distinguish:**
- Check `explained_variance` trend: If improving → Scenario A
- Check episode length: If very variable → Too random (Scenario B)
- Check approx_kl: If stable → Scenario A, if high → Scenario B

---

## OPTIMIZATION WORKFLOWS

### Daily Monitoring Routine (5 minutes)

**Purpose:** Quick health check to catch problems early

**Steps:**

1. **Open TensorBoard:**
```bash
tensorboard --logdir ./tensorboard/
# Navigate to http://localhost:6006
```

2. **Check Scalars → rollout/**
   - `ep_rew_mean`: Trending upward? Smooth or noisy?
   - `ep_len_mean`: Stable?

3. **Check Scalars → train/**
   - `explained_variance`: Meeting phase target? (0.70/0.85/0.90)
   - `approx_kl`: Between 0.01-0.02?
   - `clip_fraction`: Between 20-30%?
   - `entropy_loss`: Decreasing gradually?

4. **Check Scalars → bot_eval/ (if eval ran today)**
   - All bot win rates improving or stable?
   - `combined` trending upward?

5. **Decision:**
```
IF all metrics healthy AND improving:
    ✅ Continue training, check again tomorrow

IF any red flag detected:
    ⚠️ Go to Diagnostic Decision Tree

IF phase target met:
    ✅ Advance to next phase
```

---

### Diagnostic Decision Tree

**When metrics show problems, follow this decision tree:**

```
START: Problem detected in daily monitoring

├─ Is win_rate improving (even slowly)?
│  ├─ YES: Continue, probably just slow learning
│  └─ NO: Continue below ↓

├─ Check explained_variance
│  ├─ < 0.60: NETWORK TOO SMALL
│  │   └─ Fix: Increase net_arch [128,128] → [256,256]
│  └─ > 0.60: Network OK, continue below ↓

├─ Check approx_kl
│  ├─ Avg > 0.03: LEARNING RATE TOO HIGH
│  │   └─ Fix: Reduce learning_rate by 50%
│  ├─ Avg < 0.005: LEARNING RATE TOO LOW
│  │   └─ Fix: Increase learning_rate by 50%
│  └─ 0.005-0.03: Learning rate OK, continue below ↓

├─ Check entropy_loss
│  ├─ Near 0 within 20 episodes: ENTROPY COLLAPSED
│  │   └─ Fix: Restart with ent_coef 0.10+
│  ├─ Still < -1.5 after 200 episodes: TOO MUCH EXPLORATION
│  │   └─ Fix: Reduce ent_coef by 50%
│  └─ Decreasing gradually: Entropy OK, continue below ↓

├─ Check clip_fraction
│  ├─ Avg > 50%: POLICY CHANGING TOO FAST
│  │   └─ Fix: Reduce learning_rate AND clip_range
│  ├─ Avg < 10%: POLICY TOO CONSERVATIVE
│  │   └─ Fix: Increase clip_range 0.2 → 0.25
│  └─ 10-50%: Clipping OK, continue below ↓

├─ Check episode_reward variance
│  ├─ High variance (swings > 20 pts): UNSTABLE POLICY
│  │   └─ Fix: Increase batch_size 64 → 128
│  └─ Low variance: Stability OK, continue below ↓

├─ Compare self-play vs bot eval
│  ├─ Self-play high, bot eval low: OVERFITTING
│  │   └─ Fix: Add diverse scenarios, adjust rewards
│  └─ Both aligned: Generalization OK, continue below ↓

└─ If all checks pass but still not improving:
    └─ Rewards may be too sparse
        └─ Fix: Add intermediate rewards, check rewards_config.json
```

---

### When to Intervene vs Wait

**Intervene Immediately (< 10 episodes) if:**
- ❌ `entropy_loss` drops to near 0 within 10 episodes
- ❌ `approx_kl` > 0.05 consistently
- ❌ `explained_variance` < 0.30 after 20 episodes
- ❌ Win rate < 20% AND decreasing in Phase 1

**Intervene Soon (50 episodes) if:**
- ⚠️ Win rate flat for 50 episodes
- ⚠️ `explained_variance` stuck < 0.60 for 50 episodes
- ⚠️ `approx_kl` > 0.03 consistently for 50 episodes
- ⚠️ Bot evaluation declining for 2 consecutive evals

**Wait and Monitor (100 episodes) if:**
- 🟡 Win rate improving slowly (1-2% per 50 episodes)
- 🟡 Metrics slightly outside ideal range but stable
- 🟡 Some noise but overall trend positive
- 🟡 Early in phase (< 100 episodes total)

**Never Intervene if:**
- ✅ All metrics in healthy range
- ✅ Win rate improving steadily
- ✅ Just started new phase (< 20 episodes)

---

## HYPERPARAMETER TUNING

### Metric-Based Adjustment Guide

**Use this table to map observed metric patterns to config changes:**

| Metric Pattern | Root Cause | Solution | Config Change |
|----------------|------------|----------|---------------|
| `explained_variance` < 0.60 | Value network too weak | Increase network size | `net_arch`: [128,128] → [256,256] |
| `approx_kl` > 0.03 consistently | Learning too fast | Reduce learning rate | `learning_rate`: 0.001 → 0.0003 |
| `approx_kl` < 0.005 consistently | Learning too slow | Increase learning rate | `learning_rate`: 0.0003 → 0.0005 |
| `clip_fraction` < 10% | Updates too conservative | Increase clip range | `clip_range`: 0.2 → 0.3 |
| `clip_fraction` > 50% | Policy changing drastically | Reduce LR + clip range | `learning_rate`: ÷2, `clip_range`: 0.2 → 0.15 |
| `entropy_loss` near 0 early | Collapsed to deterministic | Increase exploration | `ent_coef`: 0.01 → 0.10, restart |
| `entropy_loss` < -1.5 late | Too much exploration | Reduce exploration | `ent_coef`: 0.20 → 0.05 |
| Win rate flat + low entropy | Stuck in local optimum | Increase exploration OR reset | `ent_coef`: +0.05 OR restart |
| High reward variance | Policy unstable | Increase batch size | `batch_size`: 64 → 128 |
| `value_loss` not decreasing | Value function failing | Increase VF coefficient | `vf_coef`: 0.5 → 1.0 |
| Bot eval declining | Overfitting | More diverse scenarios | Add scenarios to agent scenarios/ |
| `episode_length` increasing | Too conservative | Reduce wait penalty | `wait` in rewards: -1.0 → -0.5 |
| Win rate oscillating | Multiple issues | Stabilize everything | Reduce LR, increase batch_size, reduce ent_coef |

---

### Detailed Parameter Effects

#### Learning Rate (`learning_rate`)

**What it controls:** Step size for gradient descent updates

**Relationship to metrics:**
- **High LR →** High `approx_kl`, high `clip_fraction`, unstable `episode_reward`
- **Low LR →** Low `approx_kl`, slow improvement, low `clip_fraction`

**Symptoms & Fixes:**

**Too High (> 0.001 in Phase 2+):**
- Symptoms:
  - `approx_kl` > 0.03 frequently
  - Win rate oscillates wildly (swings > 15%)
  - `clip_fraction` > 50%
  - Training unstable, policy may collapse
- Fix: Reduce by 50%: 0.001 → 0.0005 or 0.0003 → 0.00015

**Too Low (< 0.00005):**
- Symptoms:
  - Training very slow (episodes pass, no improvement)
  - `approx_kl` < 0.005 consistently
  - Win rate improves < 1% per 100 episodes
  - `explained_variance` stuck
- Fix: Increase by 50%: 0.00005 → 0.000075 or 0.0001 → 0.00015

**Sweet Spots:**
- Phase 1: 0.001 (fast initial learning, high exploration)
- Phase 2: 0.0003-0.0005 (balanced learning, refining)
- Phase 3: 0.0001-0.0003 (fine-tuning, stability)

---

#### Entropy Coefficient (`ent_coef`)

**What it controls:** How much exploration vs exploitation

**Relationship to metrics:**
- **High ent_coef →** `entropy_loss` stays negative (< -1.0), high exploration, diverse actions
- **Low ent_coef →** `entropy_loss` near 0, deterministic policy, exploits learned behaviors

**Symptoms & Fixes:**

**Too High (> 0.30):**
- Symptoms:
  - Policy stays too random
  - Win rate improves slowly
  - `entropy_loss` < -1.5 even after 200 episodes
  - Episode actions seem chaotic, no consistent strategy
- Fix: Reduce by 50%: 0.30 → 0.15 or 0.20 → 0.10

**Too Low (< 0.005):**
- Symptoms:
  - Policy becomes deterministic too early (< 50 episodes)
  - `entropy_loss` near 0 too fast
  - Win rate plateaus early (stuck in local optimum)
  - `clip_fraction` < 5% (policy not changing)
  - Limited tactical diversity
- Fix: Increase significantly: 0.005 → 0.05 or restart with 0.10

**Sweet Spots:**
- Phase 1: 0.15-0.20 (high exploration - discovering tactics)
- Phase 2: 0.05-0.10 (moderate - refining tactics)
- Phase 3: 0.01-0.05 (low - exploiting learned behaviors)

**Critical Rule:** If entropy_loss reaches near 0 within 20 episodes, MUST restart with higher ent_coef.

---

#### Clip Range (`clip_range`)

**What it controls:** Maximum policy change per update (PPO's key safety feature)

**Relationship to metrics:**
- **High clip_range →** Larger policy updates allowed, higher `clip_fraction`
- **Low clip_range →** Conservative updates, lower `clip_fraction`

**Symptoms & Fixes:**

**Too High (> 0.3):**
- Symptoms:
  - Large policy swings episode-to-episode
  - Can destroy learned behaviors suddenly
  - `approx_kl` might spike
  - Win rate volatile
- Fix: Reduce: 0.3 → 0.2 or 0.25 → 0.15

**Too Low (< 0.1):**
- Symptoms:
  - Training very conservative and slow
  - `clip_fraction` < 10% consistently
  - Policy barely changes
  - Slow improvement even with good learning rate
- Fix: Increase: 0.1 → 0.2 or 0.15 → 0.25

**Sweet Spot:** 0.2 (standard PPO value, works for most cases)
- Adjust to 0.15 if training unstable
- Adjust to 0.25 if training too slow and stable

**Note:** Usually adjust `learning_rate` before adjusting `clip_range`. Clip range is PPO's safety mechanism, don't disable it unless necessary.

---

#### Network Architecture (`net_arch`)

**What it controls:** Policy and value network capacity (# of neurons per layer)

**Relationship to metrics:**
- **Small network →** Low `explained_variance`, can't learn complex tactics, plateaus early
- **Large network →** High `explained_variance`, can learn complex tactics, but slower training

**Symptoms & Fixes:**

**Too Small ([64, 64] or [128, 128] for complex tactics):**
- Symptoms:
  - `explained_variance` stuck < 0.60
  - Can't learn complex tactical patterns
  - Win rate plateaus early (can't improve beyond basics)
  - `value_loss` not decreasing
- Fix: Double network size: [64,64] → [128,128] or [128,128] → [256,256]

**Too Large ([512, 512, 512]):**
- Symptoms:
  - Training very slow (episodes take long time)
  - Overfitting risk (high train performance, poor eval)
  - High GPU/CPU usage
  - Might converge faster but inefficient
- Fix: Reduce size: [512,512,512] → [256,256] or [256,256,256] → [256,256]

**Sweet Spots:**
- Phase 1 (basic skills): [128, 128] or [256, 256]
- Phase 2 (medium complexity): [256, 256]
- Phase 3 (complex tactics): [256, 256] or [320, 320] or [256, 256, 128]

**Note:** Changing network size requires restarting training (can't load old models). Only change if clearly necessary.

---

#### Batch Size (`batch_size`)

**What it controls:** How many samples per gradient update

**Relationship to metrics:**
- **Small batch →** Noisy gradients, high `approx_kl` variance, unstable updates
- **Large batch →** Stable gradients, smooth `approx_kl`, slower updates

**Symptoms & Fixes:**

**Too Small (< 32):**
- Symptoms:
  - Noisy gradients
  - Training unstable
  - `approx_kl` high variance (jumps around)
  - `episode_reward` oscillates
  - `clip_fraction` varies wildly
- Fix: Double batch size: 32 → 64 or 64 → 128

**Too Large (> 256):**
- Symptoms:
  - Training slow (fewer updates per episode)
  - Might need more episodes to fill buffer
  - Less frequent policy updates
  - Memory usage high
- Fix: Halve batch size: 256 → 128 or 512 → 256

**Sweet Spots:**
- Phase 1: 32-64 (quick updates, fast iteration)
- Phase 2: 64-128 (balanced)
- Phase 3: 128 (stable fine-tuning)

**Trade-off:** Larger batch = more stable but slower learning. Smaller batch = faster but noisier.

---

#### N Steps (`n_steps`)

**What it controls:** Rollout buffer size (how many environment steps before policy update)

**Relationship to metrics:**
- **Small n_steps →** Frequent updates, less sample-efficient, higher advantage variance
- **Large n_steps →** Rare updates, more sample-efficient, better credit assignment

**Symptoms & Fixes:**

**Too Small (< 256):**
- Symptoms:
  - Very frequent policy updates
  - Less sample efficiency (need more episodes)
  - Higher variance in advantage estimates
  - Training might be unstable
- Fix: Double: 256 → 512 or 512 → 1024

**Too Large (> 4096):**
- Symptoms:
  - Very rare policy updates (might wait too long between learning)
  - Memory intensive
  - Requires many environment steps before update
  - Might miss short-term patterns
- Fix: Halve: 4096 → 2048 or 8192 → 4096

**Sweet Spots:**
- Phase 1: 512-1024 (frequent feedback for basic learning)
- Phase 2: 1024-2048 (balanced)
- Phase 3: 2048-4096 (large trajectory for complex credit assignment)

**Trade-off:** Larger n_steps = better credit assignment for multi-turn strategies but slower update frequency.

---

## EARLY STOPPING CRITERIA

### When to Stop Training (SUCCESS)

**Stop training and declare SUCCESS if ANY of these conditions met:**

#### 1. ✅ Win Rate Target Achieved
**Condition:**
- `game_critical/win_rate_100ep` > 80% for 100 consecutive episodes
- Indicates strong general performance across diverse scenarios

**Verification:**
- Check win rate is stable (not just lucky streak)
- Verify against all bot types
- Watch replay to confirm tactical competence

---

#### 2. ✅ Bot Evaluation Excellence
**Condition:**
- `bot_eval/vs_random` > 0.85
- `bot_eval/vs_greedy` > 0.70
- `bot_eval/vs_defensive` > 0.60
- ALL targets exceeded simultaneously

**Meaning:** Agent has mastered all difficulty levels

---

#### 3. ✅ Combined Score Threshold
**Condition:**
- `bot_eval/combined` > 0.75 AND stable for 100 episodes

**Meaning:** Weighted average accounts for all difficulties, agent is expert-level

**Verification:** Score should not be declining, check for 2 consecutive evals

---

#### 4. ✅ Value Function Converged
**Condition:**
- `train/explained_variance` > 0.95 
- AND `game_critical/episode_reward` no improvement for 200 episodes

**Meaning:** Model has learned as much as possible from current scenarios

**Note:** This is "good enough" even if not hitting win rate targets. Agent has extracted maximum value from training data.

---

### When to Stop Training (FAILURE)

**Stop training and declare FAILURE if ANY of these conditions met:**

#### 1. ❌ No Progress After Extended Training
**Condition:**
- Win rate < target for phase after 200% of expected episodes

**Examples:**
- Phase 1: Win rate < 40% after 100 episodes (target was 50 episodes)
- Phase 2: Win rate < 60% after 1000 episodes (target was 500 episodes)
- Phase 3: Win rate < 70% after 2000 episodes (target was 1000 episodes)

**Action:** Diagnose root cause using Pattern Library, adjust hyperparameters or rewards, restart

---

#### 2. ❌ Catastrophic Forgetting
**Condition:**
- Win rate drops > 20% AND doesn't recover after 100 episodes

**Example:** Win rate was 65%, dropped to 40%, stayed low for 100+ episodes

**Meaning:** Policy has collapsed, learned behaviors destroyed

**Action:** Restart from last good checkpoint, reduce learning_rate by 50%

---

#### 3. ❌ Invalid Action Epidemic
**Condition:**
- `game_critical/invalid_action_rate` > 10% persistently (50+ episodes)

**Meaning:** Agent not learning game rules correctly

**Possible causes:**
- Observation space malformed
- Action space mismatch
- Reward hacking leading to rule violations

**Action:** Check game logs, verify observation space, review reward penalties for invalid actions

---

#### 4. ❌ Training Instability
**Condition:**
- `train/approx_kl` > 0.05 for 50+ consecutive updates

**Meaning:** Policy diverging, updates too large, training will not converge

**Action:** Reduce learning_rate by 75%: 0.0003 → 0.000075, if still unstable, restart with lower LR

---

### When to Continue Training

**Continue training if ALL of the following are true:**

- ✅ Win rate improving (even if slowly - 1-2% per 50 episodes)
- ✅ Eval bot performance increasing or stable
- ✅ New tactical behaviors emerging in replays (manual inspection)
- ✅ `explained_variance` still improving (< 0.95)
- ✅ No failure criteria met
- ✅ No success criteria met yet

**Key principle:** As long as metrics are improving and not failing, give training more time.

---

## ADVANCED TECHNIQUES

### Multi-Metric Analysis

**Purpose:** Combine multiple metrics to understand complex training dynamics

#### Technique 1: Value Function Quality Score

**Formula:**
```
VF_Quality = explained_variance * (1 - |value_loss_change_rate|)
```

**Interpretation:**
- > 0.80: Excellent value function
- 0.60-0.80: Good value function
- < 0.60: Poor value function, intervention needed

**Use case:** Single number to track value function health over time

---

#### Technique 2: Policy Stability Index

**Formula:**
```
Stability = 1 / (1 + approx_kl_stddev * clip_fraction_stddev)
```

**Interpretation:**
- > 0.80: Very stable policy updates
- 0.50-0.80: Moderately stable
- < 0.50: Unstable, reduce learning_rate

**Use case:** Early warning system for training instability

---

#### Technique 3: Exploration-Exploitation Balance

**Formula:**
```
Balance = -entropy_loss / max_entropy_theoretical
```

**Interpretation:**
- > 0.70: Still exploring (early training)
- 0.40-0.70: Balanced
- < 0.40: Mostly exploiting (late training)

**Use case:** Determine if exploration is appropriate for training phase

---

### Historical Trend Analysis

**Purpose:** Use past metrics to predict future performance

#### Technique: Linear Regression on Win Rate

**Method:**
1. Collect win_rate for last 100 episodes
2. Fit linear trend line
3. Project 50 episodes forward
4. Compare projection to phase target

**Decision:**
- If projection meets target → Continue training
- If projection falls short → Intervention needed
- If projection overshoots → Consider early phase advancement

**Implementation (pseudo-code):**
```python
from sklearn.linear_model import LinearRegression

# Collect last 100 win rates
win_rates = metrics['win_rate'][-100:]
episodes = np.arange(100)

# Fit trend
model = LinearRegression()
model.fit(episodes.reshape(-1, 1), win_rates)

# Project 50 episodes ahead
future_episode = np.array([[150]])
projected_win_rate = model.predict(future_episode)[0]

# Compare to target
if projected_win_rate > phase_target:
    print("On track to meet target")
else:
    print(f"Need improvement: projected {projected_win_rate:.2f}, target {phase_target:.2f}")
```

---

### Predictive Indicators

**Purpose:** Identify early signals that predict final performance

#### Early Warning System (Episodes 10-20)

**Check these metrics at episode 20:**

1. **`explained_variance` at Ep 20:**
   - If > 0.60 → 85% chance of success
   - If 0.40-0.60 → 60% chance of success
   - If < 0.40 → 20% chance of success, consider restart

2. **`entropy_loss` trajectory:**
   - If decreasing gradually → Good exploration path
   - If drops to near 0 → Will get stuck, restart now
   - If stays < -1.8 → May explore too long, but acceptable

3. **`approx_kl` stability:**
   - Stddev < 0.01 → Will converge stably
   - Stddev 0.01-0.02 → Moderately stable
   - Stddev > 0.02 → Will oscillate, reduce LR now

**Action:** Use these indicators to save time by restarting failed runs early.

---

## CASE STUDIES

### Case Study 1: Successful Phase 1 Training

**Setup:**
- Config: phase1 (2000 episodes target)
- Rewards: High shoot rewards, low exploration penalty
- Hyperparameters: LR=0.001, ent_coef=0.20, net_arch=[256,256]

**Metrics Timeline:**

```
Episode 10:
  win_rate: 18%
  explained_var: 0.35
  entropy_loss: -1.9
  approx_kl: 0.025
  → Assessment: Normal start, high exploration

Episode 30:
  win_rate: 32%
  explained_var: 0.68
  entropy_loss: -1.4
  approx_kl: 0.018
  → Assessment: Good progress, value function learning

Episode 50:
  win_rate: 47%
  explained_var: 0.82
  entropy_loss: -1.0
  approx_kl: 0.012
  → Assessment: Near target, consider advancing

Episode 70:
  win_rate: 61%
  vs_random: 0.73
  explained_var: 0.87
  combined: 0.48
  → DECISION: Advance to Phase 2 ✅
```

**Key Success Factors:**
- High initial ent_coef (0.20) enabled thorough exploration
- Explained variance reached 0.68 by ep 30 (predicted success)
- No interventions needed, hyperparameters well-tuned
- Advanced early (70 episodes vs 2000 target) due to fast convergence

---

### Case Study 2: Plateau Recovery

**Setup:**
- Config: phase2 (4000 episodes target)
- Initial: LR=0.0005, ent_coef=0.05, net_arch=[128,128]

**Problem:**

```
Episodes 100-200:
  win_rate: 52% → 54% → 53% → 52% → 53% (STUCK)
  explained_var: 0.62 → 0.64 → 0.63 → 0.64 (PLATEAU)
  vs_greedy: 0.38 → 0.40 → 0.39 (NOT IMPROVING)
```

**Diagnosis:**
- `explained_variance` stuck < 0.70 → Network too small
- Win rate improvement < 1% over 100 episodes → Plateau confirmed
- `approx_kl` = 0.008 (low but acceptable)

**Intervention (Episode 200):**
- Increased `net_arch` from [128,128] → [256,256]
- **Note:** Required restart, saved rewards config

**Results After Restart:**

```
Episode 50 (post-restart):
  win_rate: 58%
  explained_var: 0.78 (BIG IMPROVEMENT)
  vs_greedy: 0.51

Episode 150:
  win_rate: 68%
  explained_var: 0.89
  vs_greedy: 0.66
  → DECISION: Continue, on track

Episode 300:
  win_rate: 74%
  combined: 0.63
  → DECISION: Advance to Phase 3 ✅
```

**Lessons Learned:**
- Network capacity is critical for Phase 2+ (target priorities require more neurons)
- Explained variance < 0.70 after 100 episodes is strong signal to increase network size
- Don't wait too long to intervene if plateau is clear

---

### Case Study 3: Oscillation Stabilization

**Setup:**
- Config: phase3 (6000 episodes target)
- Initial: LR=0.0003, ent_coef=0.10, net_arch=[256,256]

**Problem:**

```
Episodes 400-500:
  win_rate: 68% → 75% → 62% → 73% → 58% → 71% (WILD SWINGS)
  approx_kl: 0.028 → 0.035 → 0.031 → 0.039 (TOO HIGH)
  clip_fraction: 0.48 → 0.55 → 0.51 → 0.58 (TOO MUCH CLIPPING)
```

**Diagnosis:**
- Win rate volatility > 15 points → Unstable policy
- `approx_kl` avg > 0.03 → Learning rate too high
- `clip_fraction` avg > 50% → Policy changing drastically

**Intervention (Episode 500):**
- Reduced `learning_rate` from 0.0003 → 0.00015 (50% reduction)
- Reduced `clip_range` from 0.2 → 0.15 (added safety)
- Increased `batch_size` from 64 → 128 (smoother gradients)

**Results:**

```
Episodes 550-650:
  win_rate: 71% → 73% → 74% → 75% → 77% (STABLE!)
  approx_kl: 0.015 → 0.012 → 0.011 → 0.010 (GOOD)
  clip_fraction: 0.28 → 0.25 → 0.23 (HEALTHY)

Episode 900:
  win_rate: 79%
  vs_defensive: 0.58
  combined: 0.72
  → DECISION: Continue, near target

Episode 1200:
  combined: 0.78 (stable for 100 eps)
  → DECISION: Training complete ✅
```

**Lessons Learned:**
- Phase 3 requires lower LR for stability (complex tactics need fine-tuning)
- Multiple parameter changes can work together (LR + clip + batch)
- `approx_kl` is best early warning for instability

---

## QUICK DIAGNOSTIC REFERENCE

**Use this table for fast lookup during training:**

| Symptom | Most Likely Cause | First Action | Config File | Parameter |
|---------|-------------------|--------------|-------------|-----------|
| Win rate stuck < 40%, explained_var < 0.60 | Network too small | Increase network size | training_config.json | `net_arch`: [128,128] → [256,256] |
| Win rate oscillating ±15% | Learning rate too high | Reduce LR by 50% | training_config.json | `learning_rate`: ÷2 |
| Entropy near 0 within 20 eps | Exploration collapsed | Restart with high ent_coef | training_config.json | `ent_coef`: 0.10+ |
| approx_kl > 0.03 consistently | LR too high | Reduce LR by 50% | training_config.json | `learning_rate`: ÷2 |
| approx_kl < 0.005 consistently | LR too low | Increase LR by 50% | training_config.json | `learning_rate`: ×1.5 |
| clip_fraction > 50% | Policy changing too fast | Reduce LR + clip range | training_config.json | `learning_rate`: ÷2, `clip_range`: 0.15 |
| clip_fraction < 10% | Updates too conservative | Increase clip range | training_config.json | `clip_range`: 0.25 |
| High reward variance | Policy unstable | Increase batch size | training_config.json | `batch_size`: ×2 |
| value_loss not decreasing | Value function failing | Increase VF coefficient | training_config.json | `vf_coef`: 0.5 → 1.0 |
| Self-play good, bot eval bad | Overfitting | Add diverse scenarios | agent scenarios/ | Add new scenarios |
| episode_length increasing | Too conservative | Reduce wait penalty | rewards_config.json | `wait`: -1.0 → -0.5 |
| Entropy high (< -1.5) late | Too much exploration | Reduce ent_coef by 50% | training_config.json | `ent_coef`: ÷2 |
| Win rate improving but slow | Normal, patience needed | Wait 50 more episodes | - | - |

---

## SUMMARY

This document provides expert-level guidance for optimizing PPO training through metrics analysis. Key takeaways:

### Core Principles

1. **Metrics tell a story** - Learn to read the narrative of training health
2. **Correlations matter** - Metrics move together, diagnose root causes not symptoms
3. **Early signals predict outcomes** - explained_variance at ep 20 predicts final success
4. **Intervention timing is critical** - Too early wastes potential, too late wastes time

### Optimization Workflow

1. **Daily monitoring** (5 min) - Quick health check catches problems early
2. **Pattern recognition** - Compare current metrics to known good/bad patterns
3. **Diagnostic tree** - Systematic approach to identifying root causes
4. **Targeted intervention** - Change one parameter at a time, measure effect
5. **Patience** - Some patterns require 50-100 episodes to resolve

### Key Metrics Priority

**Must monitor:**
- `explained_variance` - #1 predictor of success
- `approx_kl` - #1 indicator of stability
- `win_rate` - #1 performance metric

**Important:**
- `entropy_loss` - Exploration health
- `clip_fraction` - Policy update safety
- Bot evaluation scores - Generalization check

**Nice to have:**
- `policy_loss`, `value_loss` - Secondary indicators
- `episode_length` - Efficiency signal

### When to Get Help

If after using this guide and diagnostic tree:
- Metrics still confusing
- Interventions not working
- Unusual patterns not in Pattern Library

**Action:** Save TensorBoard logs, share metrics plots with team for expert review

---

**For configuration details and commands, see:** [AI_TRAINING.md](AI_TRAINING.md)

**For system architecture details, see:** [AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md)