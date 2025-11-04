# 📊 Guide to 0_critical/ Metrics - W40K AI Training

## 📑 Table of Contents

### Quick Navigation
- [🎯 Purpose](#-purpose)
- [📈 Metric Organization](#-metric-organization)

### Game Performance Metrics
1. [🎮 a_bot_eval_combined - Primary Goal Metric](#1-a_bot_eval_combined---primary-goal-metric-)
2. [🎮 b_win_rate_100ep - Training Performance](#2-b_win_rate_100ep---training-performance)
3. [🎮 c_episode_reward_smooth - Learning Progress](#3-c_episode_reward_smooth---learning-progress)

### PPO Health Metrics
4. [⚙️ d_loss_mean - Overall Training Health](#4-d_loss_mean---overall-training-health)
5. [⚙️ e_explained_variance - Value Function Quality](#5-e_explained_variance---value-function-quality)
6. [⚙️ f_clip_fraction - Policy Update Scale](#6-f_clip_fraction---policy-update-scale)
7. [⚙️ g_approx_kl - Policy Stability](#7-g_approx_kl---policy-stability)
8. [⚙️ h_entropy_loss - Exploration Health](#8-h_entropy_loss---exploration-health)

### Technical Health Metrics
9. [🔧 i_gradient_norm - Gradient Explosion Detector](#9-i_gradient_norm---gradient-explosion-detector)
10. [🔧 j_immediate_reward_ratio - Reward Composition](#10-j_immediate_reward_ratio---reward-composition)

### Troubleshooting & Tools
- [🚨 Common Problem Patterns](#-common-problem-patterns)
  - [Pattern 1: "The Plateau"](#pattern-1-the-plateau)
  - [Pattern 2: "The Collapse"](#pattern-2-the-collapse)
  - [Pattern 3: "The Explosion"](#pattern-3-the-explosion)
  - [Pattern 4: "The Shortcut"](#pattern-4-the-shortcut)
- [📋 Quick Reference Card](#-quick-reference-card)
- [🎓 Training Workflow](#-training-workflow)
- [🔗 Config File Mapping](#-config-file-mapping)
- [💡 Pro Tips](#-pro-tips)
- [📝 Example Diagnosis Session](#-example-diagnosis-session)
- [📞 Getting Help](#-getting-help)

---

## 🎯 Purpose

The `0_critical/` namespace contains **10 essential metrics** you need to tune PPO hyperparameters and diagnose training issues. These are the ONLY metrics you should focus on during active training.

**Why "0_critical"?** The `0_` prefix ensures this dashboard sorts **first** in TensorBoard alphabetically, making it your primary view.

---

## 📈 Metric Organization

All metrics use **alphabetical prefixes** (a_, b_, c_, etc.) to control sort order in TensorBoard:

- **a-c**: Game Performance (what you're optimizing FOR)
- **d-h**: PPO Health (how WELL the algorithm is learning)
- **i-j**: Technical Health (catching catastrophic failures)

All metrics are **smoothed** using 20-episode rolling averages for clear trend visualization.

---

## 🎮 GAME PERFORMANCE METRICS

### 1. `a_bot_eval_combined` - Primary Goal Metric 🎯

**What it measures:** Win rate against evaluation bots (RandomBot, GreedyBot, DefensiveBot)

**Formula:** `0.2×random + 0.3×greedy + 0.5×defensive`

**Target:** `>0.70` (70% combined win rate)

**Range:** `[0.0 - 1.0]`

**Updates:** Only when bot evaluation runs (controlled by `bot_eval_freq` in config)

**What it tells you:**
- **Primary success metric** - This is your training goal
- Measures agent's ability to beat structured opponents
- Weighted heavily toward DefensiveBot (hardest opponent)

**How to interpret:**
- `<0.40`: ❌ Agent is struggling - fundamental learning issues
- `0.40-0.60`: ⚠️ Agent is learning but needs improvement
- `0.60-0.70`: ✅ Good progress - agent is competitive
- `>0.70`: 🏆 Success! Agent beats evaluation bots consistently

**Action if too low:**
- Check if other metrics show learning (win_rate_100ep, episode_reward)
- If other metrics are good but this is low → reward structure mismatch
- If all metrics are low → hyperparameter tuning needed

**Why it's named "a_":** Sorts first - this is your #1 priority metric

---

### 2. `b_win_rate_100ep` - Training Performance

**What it measures:** Win rate against training opponent over last 100 episodes

**Target:** `>0.50` (agent wins more than it loses)

**Range:** `[0.0 - 1.0]`

**Updates:** Every episode (100-episode rolling window)

**What it tells you:**
- Agent's performance during normal training
- Fast feedback loop (updates constantly)
- Indicates if basic learning is happening

**How to interpret:**
- `<0.30`: ❌ Agent is losing badly - not learning basics
- `0.30-0.50`: ⚠️ Agent is competitive but needs work
- `0.50-0.70`: ✅ Agent is winning consistently
- `>0.70`: 🏆 Agent dominates training opponent

**Action if too low:**
- Check `entropy_loss` - agent might not be exploring
- Check `clip_fraction` - learning might be too slow
- Check `explained_variance` - value function might be broken

**Relationship to `a_bot_eval_combined`:**
- Should be HIGHER than bot_eval (training opponent is easier)
- If this is high but bot_eval is low → training opponent is too weak

---

### 3. `c_episode_reward_smooth` - Learning Progress

**What it measures:** Average reward per episode (smoothed over 20 episodes)

**Target:** **Increasing trend** (not a specific number)

**Range:** Depends on your reward structure (typically 50-200 for W40K)

**Updates:** Every episode

**What it tells you:**
- Whether the agent is learning to maximize rewards
- Reward signal strength and consistency
- Combined with win_rate, shows learning quality

**How to interpret:**
- **Flat line**: ⚠️ No learning - agent stuck at local optimum
- **Increasing**: ✅ Agent is learning and improving
- **Decreasing**: ❌ Catastrophic forgetting or policy collapse
- **Very noisy**: ⚠️ Reward signal is unstable

**Action if not increasing:**
- Check `immediate_reward_ratio` - might be >0.9 (only learning short-term)
- Check `entropy_loss` - might be too low (stopped exploring)
- Check `clip_fraction` - might be too low (learning too slowly)

**Pro tip:** This should correlate with `win_rate_100ep`. If reward increases but win rate doesn't → reward hacking.

---

## ⚙️ PPO HEALTH METRICS

### 4. `d_loss_mean` - Overall Training Health

**What it measures:** Combined policy loss + value loss (absolute values)

**Target:** **Decreasing trend** over time, stabilizing above 0

**Range:** Typically 50-200 early, 10-50 stable

**Updates:** Every policy update (~every n_steps)

**What it tells you:**
- Overall learning signal strength
- Whether policy and value functions are converging
- Training stability

**How to interpret:**
- **Very high (>200)**: ⚠️ Early training - this is normal
- **Increasing**: ❌ Training is unstable - diverging
- **Decreasing steadily**: ✅ Healthy learning
- **Stable and low (<50)**: ✅ Converged
- **Oscillating wildly**: ❌ Learning rate too high or gradient explosion

**Action if unstable:**
- Reduce `learning_rate` (e.g., 0.0003 → 0.0001)
- Check `gradient_norm` - might be >10
- Reduce `n_epochs` if oscillating

---

### 5. `e_explained_variance` - Value Function Quality

**What it measures:** How well the value function predicts actual returns

**Target:** `>0.30` (ideally >0.70)

**Range:** `[-1.0 to 1.0]` (negative means worse than predicting zero)

**Updates:** Every policy update

**What it tells you:**
- Whether the critic (value function) understands the environment
- Quality of advantage estimates for policy updates
- Fundamental learning capacity

**How to interpret:**
- `<0.0`: ❌ **CRITICAL** - Value function is completely broken
- `0.0-0.30`: ⚠️ Value function is weak - poor advantage estimates
- `0.30-0.70`: ✅ Value function is working correctly
- `>0.70`: 🏆 Excellent value function - high quality learning

**Action if too low (<0.30):**
- **MOST COMMON CAUSE:** Reward signal is too sparse or delayed
- Increase `gamma` (e.g., 0.95 → 0.98) for longer-term planning
- Increase `gae_lambda` (e.g., 0.95 → 0.98)
- Check if rewards are too sparse - might need reward shaping
- Increase `vf_coef` (e.g., 0.5 → 1.0) to prioritize value function training

**Why this matters:**
- PPO uses the value function to compute advantages
- Bad value function → bad advantage estimates → bad policy updates
- If this is broken, NOTHING else will work properly

---

### 6. `f_clip_fraction` - Policy Update Scale

**What it measures:** Fraction of policy updates that hit the PPO clipping limit

**Target:** `0.1 - 0.3` (10-30% of updates clipped)

**Range:** `[0.0 - 1.0]`

**Updates:** Every policy update

**What it tells you:**
- How aggressively the policy is being updated
- Whether `learning_rate` is appropriate
- Whether policy changes are too large or too small

**How to interpret:**
- `<0.1`: ⚠️ **Updates too small** - learning is very slow
  - Policy is barely changing
  - Training will take forever
  
- `0.1-0.3`: ✅ **Optimal range**
  - Policy updates are well-sized
  - Safe, stable learning
  
- `>0.3`: ⚠️ **Updates too large** - risk of instability
  - Policy changing too fast
  - Risk of catastrophic forgetting

**Action based on value:**

| Value | Problem | Solution |
|-------|---------|----------|
| <0.05 | Learning glacially slow | **Increase** `learning_rate` by 2x (0.0003 → 0.0006) |
| 0.05-0.1 | Learning slowly | **Increase** `learning_rate` by 1.5x |
| 0.1-0.3 | ✅ Perfect | No change needed |
| 0.3-0.5 | Aggressive updates | **Decrease** `learning_rate` by 0.7x |
| >0.5 | Too aggressive | **Decrease** `learning_rate` by 0.5x |

**Why this matters:**
- PPO clips policy updates to prevent catastrophic changes
- If most updates are clipped → learning rate is too high
- If no updates are clipped → learning rate is too low

---

### 7. `g_approx_kl` - Policy Stability

**What it measures:** KL divergence between old and new policy (how much policy changed)

**Target:** `<0.02` (ideally <0.01 for stable training)

**Range:** `[0.0 - ∞]` (practically 0.0-0.1)

**Updates:** Every policy update

**What it tells you:**
- How much the policy distribution is changing each update
- Training stability indicator
- Whether `target_kl` constraint is working

**How to interpret:**
- `<0.01`: ✅ Very stable, safe learning
- `0.01-0.02`: ✅ Healthy learning pace
- `0.02-0.05`: ⚠️ Policy changing quickly - monitor closely
- `>0.05`: ❌ **DANGER** - policy changing too fast, risk of collapse

**Action if too high (>0.02):**
- **Decrease `learning_rate`** - primary control
- Set or decrease `target_kl` (e.g., `null` → `0.03` or `0.03` → `0.01`)
- Reduce `n_epochs` (e.g., 10 → 6)

**Action if too low (<0.005) AND performance is bad:**
- Policy is stuck - not exploring enough
- Increase `ent_coef` to encourage exploration
- Slightly increase `learning_rate`

**Relationship to `clip_fraction`:**
- Both measure update size but differently
- approx_kl is more precise but harder to interpret
- Use clip_fraction as primary, approx_kl for safety checks

---

### 8. `h_entropy_loss` - Exploration Health

**What it measures:** Negative entropy of the policy distribution (higher = more deterministic)

**Target:** `0.5 - 2.0` (depends on action space)

**Range:** `[-∞ to 0]` (more negative = more deterministic)

**Updates:** Every policy update

**What it tells you:**
- How much the agent is exploring vs exploiting
- Whether the policy has become too deterministic
- Risk of premature convergence

**How to interpret:**
- `>2.0` (less negative than -2.0): ⚠️ **Too random** - not learning patterns
- `0.5-2.0`: ✅ Healthy exploration/exploitation balance
- `<0.5` (more negative than -0.5): ❌ **Policy collapse** - stopped exploring

**Action if too low (<0.5):**
- **CRITICAL:** Agent has stopped exploring
- **Increase `ent_coef`** significantly (e.g., 0.1 → 0.3)
- This often happens mid-training as policy becomes deterministic
- May need to restart training with higher ent_coef from the start

**Action if too high (>2.0):**
- Agent is too random - not learning
- **Decrease `ent_coef`** (e.g., 0.3 → 0.1)
- Or increase training time - agent hasn't converged yet

**Why this matters:**
- PPO adds an entropy bonus to encourage exploration
- As training progresses, entropy naturally decreases
- But if it drops TOO fast → agent gets stuck in local optimum
- Your phase1 config has `ent_coef: 0.1` which caused this issue

**Pro tip:** Start with high entropy (0.3) early in training, gradually decrease to 0.1 later.

---

## 🔧 TECHNICAL HEALTH METRICS

### 9. `i_gradient_norm` - Gradient Explosion Detector

**What it measures:** L2 norm of the gradients during backpropagation

**Target:** `<10.0` (ideally 1.0-5.0)

**Range:** `[0.0 - ∞]`

**Updates:** Every policy update

**What it tells you:**
- Whether gradients are stable or exploding
- Technical health of the training process
- Whether `max_grad_norm` clipping is working

**How to interpret:**
- `<1.0`: ✅ Very stable gradients
- `1.0-5.0`: ✅ Healthy gradient flow
- `5.0-10.0`: ⚠️ Gradients getting large - monitor
- `>10.0`: ❌ **Gradient explosion** - training will fail

**Action if too high (>10):**
- **Decrease `max_grad_norm`** (e.g., 0.5 → 0.3)
- **Decrease `learning_rate`** (e.g., 0.0003 → 0.0001)
- Check if reward scale is too large (rewards >1000?)
- May indicate reward structure issues

**Why this matters:**
- Exploding gradients cause training instability
- Can lead to NaN losses and complete training failure
- max_grad_norm clips gradients to prevent this
- If gradient_norm consistently hits max_grad_norm → need to reduce learning rate

**Note:** Some versions of Stable-Baselines3 don't log this metric. If unavailable, it will show as 0.

---

### 10. `j_immediate_reward_ratio` - Reward Composition

**What it measures:** Ratio of immediate (base action) rewards to total episode reward

**Target:** `<0.90` (ideally 0.5-0.7)

**Range:** `[0.0 - 1.0]`

**Updates:** Every episode (if reward decomposition is tracked)

**What it tells you:**
- Whether agent is learning long-term strategy or just immediate rewards
- Balance between short-term and long-term thinking
- Quality of reward structure

**How to interpret:**
- `<0.50`: ✅ Agent learning primarily from strategic rewards
- `0.50-0.70`: ✅ Good balance of immediate and strategic rewards
- `0.70-0.90`: ⚠️ Heavy reliance on immediate rewards
- `>0.90`: ❌ **Only learning immediate rewards** - no strategy

**Action if too high (>0.90):**
- **CRITICAL:** Agent isn't learning long-term strategy
- Increase `gamma` (e.g., 0.95 → 0.98) - look further into future
- Increase strategic reward bonuses in rewards_config.json
- Reduce immediate action rewards
- May need reward redesign

**Why this matters:**
- In W40K, winning requires strategy (positioning, target priority, resource management)
- If agent only learns "shoot nearest enemy" (immediate reward), it won't develop strategy
- Your training showed this at 1.0 → agent learned zero strategy

**Example:**
- Good agent: 30% from shooting actions, 70% from killing enemies, winning battles
- Bad agent: 90% from shooting actions, 10% from actually accomplishing goals

---

## 🚨 Common Problem Patterns

### Pattern 1: "The Plateau"
**Symptoms:**
- ✅ `explained_variance` = 0.7 (good)
- ✅ `clip_fraction` = 0.15 (good)
- ❌ `episode_reward` flat
- ❌ `win_rate_100ep` stuck at 0.4

**Diagnosis:** Agent is stuck in local optimum

**Solution:**
1. Increase `ent_coef` (0.1 → 0.3) to explore more
2. Increase `learning_rate` slightly
3. May need curriculum learning or reward redesign

---

### Pattern 2: "The Collapse"
**Symptoms:**
- ❌ `entropy_loss` = -1.5 (too deterministic)
- ❌ `win_rate_100ep` decreasing
- ❌ `episode_reward` decreasing
- ✅ `explained_variance` still good

**Diagnosis:** Policy collapse - agent stopped exploring and forgot what it learned

**Solution:**
1. **Restart training** with higher `ent_coef` (0.3 instead of 0.1)
2. Use entropy decay schedule (start 0.3, gradually reduce to 0.1)
3. Reduce `learning_rate` to prevent forgetting

---

### Pattern 3: "The Explosion"
**Symptoms:**
- ❌ `gradient_norm` = 15+ (exploding)
- ❌ `clip_fraction` = 0.8 (way too high)
- ❌ `approx_kl` = 0.1+ (huge policy changes)
- ❌ All metrics become unstable

**Diagnosis:** Training is unstable - updates too large

**Solution:**
1. **Decrease `learning_rate`** immediately (0.0003 → 0.0001)
2. Decrease `max_grad_norm` (0.5 → 0.3)
3. Set `target_kl` = 0.01 to limit policy changes

---

### Pattern 4: "The Shortcut"
**Symptoms:**
- ✅ `win_rate_100ep` = 0.7 (good!)
- ❌ `a_bot_eval_combined` = 0.2 (bad!)
- ❌ `immediate_reward_ratio` = 0.95

**Diagnosis:** Agent learned to game the training system, not the actual game

**Solution:**
1. Training opponent is too weak - agent learned shortcuts
2. Increase strategic reward bonuses
3. Use curriculum learning with harder opponents
4. Redesign rewards to discourage shortcut strategies

---

## 📋 Quick Reference Card

**Print this and keep it next to your monitor:**

| Metric | Good Range | Primary Control | Fix if Bad |
|--------|-----------|-----------------|-----------|
| **a_bot_eval_combined** | >0.70 | Reward structure | Tune other metrics first |
| **b_win_rate_100ep** | >0.50 | Agent learning | Check entropy, clip_fraction |
| **c_episode_reward** | Increasing | Reward signal | Check immediate_reward_ratio |
| **d_loss_mean** | Decreasing | training stability | Reduce learning_rate |
| **e_explained_variance** | >0.30 | gamma, gae_lambda | Increase both to 0.98 |
| **f_clip_fraction** | 0.1-0.3 | **learning_rate** | Adjust learning_rate |
| **g_approx_kl** | <0.02 | learning_rate | Reduce learning_rate, set target_kl |
| **h_entropy_loss** | 0.5-2.0 | **ent_coef** | Increase ent_coef to 0.3 |
| **i_gradient_norm** | <10 | max_grad_norm | Reduce max_grad_norm, learning_rate |
| **j_immediate_reward_ratio** | <0.90 | **gamma** | Increase gamma, redesign rewards |

---

## 🎓 Training Workflow

**Use this workflow for efficient training:**

### Step 1: Start Training
Monitor: `e_explained_variance`, `i_gradient_norm`
- If explained_variance <0.3 → Stop, increase gamma
- If gradient_norm >10 → Stop, reduce learning_rate

### Step 2: First 100 Episodes
Monitor: `f_clip_fraction`, `h_entropy_loss`
- Adjust learning_rate to get clip_fraction 0.1-0.3
- Ensure entropy_loss stays in 0.5-2.0 range

### Step 3: First Bot Evaluation (~500 episodes)
Monitor: `a_bot_eval_combined`, `j_immediate_reward_ratio`
- If bot_eval <0.4 AND immediate_ratio >0.9 → Reward structure problem
- If bot_eval <0.4 AND entropy_loss <0.5 → Exploration problem

### Step 4: Mid-Training (1000+ episodes)
Monitor: `b_win_rate_100ep`, `c_episode_reward`
- Should both be increasing
- If plateauing → increase ent_coef or change curriculum

### Step 5: Final Evaluation
Monitor: `a_bot_eval_combined`
- Target >0.70
- If not achieved → analyze which pattern above matches

---

## 🔗 Config File Mapping

**Which config parameters affect which metrics:**

```json
{
  "learning_rate": 0.0003,     // Controls: f_clip_fraction, g_approx_kl, i_gradient_norm
  "ent_coef": 0.1,             // Controls: h_entropy_loss
  "gamma": 0.95,               // Controls: e_explained_variance, j_immediate_reward_ratio
  "gae_lambda": 0.95,          // Controls: e_explained_variance
  "max_grad_norm": 0.5,        // Controls: i_gradient_norm
  "target_kl": 0.03,           // Controls: g_approx_kl (limits policy changes)
  "n_epochs": 10,              // Affects: All PPO metrics (more updates per batch)
  "clip_range": 0.2            // Affects: f_clip_fraction (PPO clipping threshold)
}
```

---

## 💡 Pro Tips

1. **Focus on 3 metrics first:** `clip_fraction`, `explained_variance`, `entropy_loss`
   - If these are in range, everything else usually follows

2. **Bot evaluation is your ground truth**
   - Training metrics can lie (reward hacking)
   - Bot eval can't be gamed
   - If training looks good but bot_eval is bad → you have a problem

3. **Use TensorBoard's smoothing slider**
   - Metrics are pre-smoothed (20-episode average)
   - But TensorBoard adds its own smoothing
   - Set TensorBoard smoothing to 0 to see actual values

4. **Compare multiple training runs**
   - Use TensorBoard's multi-run comparison
   - Color-code by hyperparameter changes
   - This is how you find optimal settings

5. **Watch for divergence**
   - If `a_bot_eval_combined` and `b_win_rate_100ep` diverge significantly
   - Agent is learning shortcuts specific to training opponent
   - Need harder training opponents or better curriculum

---

## 📝 Example Diagnosis Session

**Situation:** Agent trained for 1000 episodes, bot_eval = 0.21

**Step-by-step analysis:**

1. ✅ `explained_variance = 0.70` → Value function works
2. ⚠️ `clip_fraction = 0.069` → Learning too slowly
3. ❌ `entropy_loss = -1.069` → Policy collapsed (stopped exploring)
4. ❌ `immediate_reward_ratio = 1.0` → Only learning immediate rewards
5. ✅ `gradient_norm = <10` → No technical issues

**Diagnosis:**
- Primary issue: Low entropy (policy collapse)
- Secondary issue: Low clip fraction (learning too slowly)
- Tertiary issue: Reward structure only teaches immediate actions

**Action plan:**
1. Restart training with `ent_coef: 0.3` (was 0.1)
2. Increase `learning_rate: 0.0005` (was 0.0003) to boost clip_fraction
3. Redesign rewards: Reduce shooting rewards, increase tactical bonuses
4. Expected result: entropy stays healthy, agent learns strategy

---

## 📞 Getting Help

If metrics don't make sense:
1. Check this guide first
2. Compare your metrics to the "Common Patterns" section
3. Verify config values match recommendations
4. Post your TensorBoard screenshot with config on Discord/Forum

**Include in your help request:**
- Screenshot of 0_critical/ dashboard
- Your training_config.json (especially model_params section)
- Number of episodes trained
- Bot evaluation scores

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-15  
**Compatible with:** W40K AI Training System v2.0+