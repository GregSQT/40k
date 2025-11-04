# 🎛️ PPO HYPERPARAMETERS COMPLETE GUIDE

## 📑 Table of Contents
1. [Learning & Optimization](#learning--optimization)
   - learning_rate
   - n_steps
   - batch_size
   - n_epochs
2. [Policy Constraints](#policy-constraints)
   - clip_range
   - target_kl
   - max_grad_norm
3. [Reward Discounting](#reward-discounting)
   - gamma
   - gae_lambda
4. [Loss Weighting](#loss-weighting)
   - ent_coef
   - vf_coef
5. [Network Architecture](#network-architecture)
   - policy_kwargs (net_arch)

---

## 🎓 LEARNING & OPTIMIZATION

### `learning_rate` - How Fast the Agent Learns

**What it is:** Step size for gradient descent updates to the neural network

**Your value:** `0.0015`

**Typical range:** `0.00001 - 0.003`

**What it controls:**
- Speed of policy and value function updates
- **Primary control for `f_clip_fraction`**
- Affects `g_approx_kl` (policy change magnitude)
- Affects `i_gradient_norm` (gradient size)

**How it works:**
```
new_weights = old_weights - learning_rate × gradient
```
- **Higher LR** → Larger weight changes → Faster learning → More instability
- **Lower LR** → Smaller weight changes → Slower learning → More stability

**How to tune:**

**If `clip_fraction` is too low (<0.1):**
- **Increase** learning_rate by 1.5-2x
- Example: `0.0003 → 0.0005` or `0.0015 → 0.003`
- **Goal:** Get clip_fraction into 0.1-0.3 range

**If `clip_fraction` is too high (>0.3):**
- **Decrease** learning_rate by 0.5-0.75x
- Example: `0.0015 → 0.001` or `0.0003 → 0.0002`
- **Goal:** Prevent overshooting and instability

**If training is unstable (loss oscillating):**
- **Decrease** learning_rate significantly
- Example: `0.0003 → 0.0001`
- **Check:** `i_gradient_norm` should be <10

**Trade-offs:**
- ✅ Higher LR: Faster training, reaches good policies quicker
- ❌ Higher LR: Can overshoot, cause instability, catastrophic forgetting
- ✅ Lower LR: More stable, smoother convergence
- ❌ Lower LR: Slower training, may not escape local optima

**Relationship to other parameters:**
- Works with `batch_size`: Larger batches can handle higher LR (smoother gradients)
- Works with `n_epochs`: More epochs amplifies LR effect (more updates per rollout)
- Works with `clip_range`: Tight clipping requires higher LR to make progress

**Your value analysis (0.0015):**
- ✅ Moderate-high learning rate
- ✅ Good for Phase 1 (need to learn quickly)
- ✅ Produced clip_fraction ~0.099 (just below target)
- 💡 Consider 0.002-0.0025 to push clip_fraction firmly into 0.1-0.15 range

---

### `n_steps` - Rollout Length Before Update

**What it is:** Number of environment steps to collect before performing a policy update

**Your value:** `2048`

**Typical range:** `128 - 4096`

**What it controls:**
- How much experience is collected before learning
- Batch size for advantage estimation
- Affects all PPO metrics indirectly (frequency of updates)

**How it works:**
```
Collect 2048 steps → Compute advantages → Update policy n_epochs times → Repeat
```
- **Higher n_steps** → More data per update → Better advantage estimates → Slower updates
- **Lower n_steps** → Less data per update → Faster updates → Noisier estimates

**How to tune:**

**For long episodes (like W40K with 5 turns × 8 steps = 40 steps/episode):**
- Use `n_steps` ≥ 50 episodes worth
- Your 2048 / 40 ≈ **51 episodes** ✅ Good!
- Ensures multiple complete episodes in each rollout

**For short episodes (<10 steps):**
- Use `n_steps` = 256-512 (many episodes fit in one rollout)

**If learning is unstable:**
- **Increase** n_steps (e.g., 2048 → 4096)
- **Effect:** More stable advantage estimates, smoother learning
- **Cost:** Slower iteration (more time between updates)

**If training is too slow:**
- **Decrease** n_steps (e.g., 2048 → 1024)
- **Effect:** Faster updates, more iterations per hour
- **Cost:** Noisier gradients, may need lower learning_rate

**Trade-offs:**
- ✅ Higher n_steps: Better advantage estimates, more stable learning, higher sample efficiency
- ❌ Higher n_steps: Slower wall-clock time, more memory usage
- ✅ Lower n_steps: Faster iterations, quicker feedback
- ❌ Lower n_steps: Noisier updates, may need more total episodes

**Relationship to other parameters:**
- Works with `batch_size`: n_steps should be divisible by batch_size
- Works with `n_epochs`: More epochs means each n_steps rollout is used more intensively
- Works with `gamma`: Longer n_steps needs higher gamma (look further ahead)

**Your value analysis (2048):**
- ✅ Good for W40K episode length
- ✅ Provides stable advantage estimates
- ✅ Standard PPO value (from original paper)
- 💡 Could reduce to 1024 if you want faster iteration, but current value is good

**Math check:**
```
2048 steps / 40 steps per episode = 51 episodes per rollout
51 episodes × 6 epochs = 306 gradient updates per rollout
Clip fraction 0.099 means ~10% of updates are clipped (reasonable)
```

---

### `batch_size` - Minibatch Size for Updates

**What it is:** Number of samples used in each gradient update during an epoch

**Your value:** `256`

**Typical range:** `32 - 512`

**What it controls:**
- Gradient smoothness vs variance trade-off
- **Indirect control for `f_clip_fraction`** (via gradient variance)
- Memory usage
- Update frequency within an epoch

**How it works:**
```
n_steps = 2048, batch_size = 256
→ 2048 / 256 = 8 minibatches per epoch
→ n_epochs = 6 → 8 × 6 = 48 gradient updates per rollout
```

**How to tune:**

**If gradients are too noisy (loss oscillating):**
- **Increase** batch_size (e.g., 256 → 512)
- **Effect:** Smoother gradients, more stable learning
- **Cost:** Fewer updates per epoch, slower per-epoch time

**If learning is too smooth (stuck in local optimum):**
- **Decrease** batch_size (e.g., 256 → 128)
- **Effect:** More gradient variance, helps escape local optima
- **Risk:** Can cause instability

**If `clip_fraction` is too low:**
- **Smaller batch sizes** can help (more variance → larger relative updates)
- Example: 256 → 128
- **But:** Increases instability risk

**If training is catastrophically unstable:**
- **Increase** batch_size first (smoother gradients)
- Example: 128 → 256 or 256 → 512

**Trade-offs:**
- ✅ Larger batch: Smoother gradients, more stable, better GPU utilization
- ❌ Larger batch: Fewer updates per epoch, can get stuck in local optima
- ✅ Smaller batch: More exploration via gradient noise, escapes local optima
- ❌ Smaller batch: Noisier training, risk of instability

**Relationship to other parameters:**
- **Must divide n_steps evenly:** `n_steps % batch_size == 0`
- Works with `learning_rate`: Larger batches can handle higher LR
- Works with `n_epochs`: More epochs with large batches = very smooth learning

**Your value analysis (256):**
- ✅ Good middle ground (not too smooth, not too noisy)
- ✅ Divides 2048 evenly (2048 / 256 = 8 minibatches)
- ✅ Worked well in your experiments (stable learning)
- 💡 Your data shows 256 works better than 128 for Phase 1 (more stable)

**Memory consideration:**
```
batch_size × observation_size × network_size determines GPU memory
256 × 295 floats × 2 layers (320 neurons each) = ~45MB per batch (manageable)
```

---

### `n_epochs` - Gradient Update Passes Per Rollout

**What it is:** Number of times to iterate over the collected rollout data

**Your value:** `6`

**Typical range:** `3 - 20`

**What it controls:**
- How thoroughly each rollout is "learned from"
- Sample efficiency (how much you squeeze from each rollout)
- Risk of overfitting to collected data

**How it works:**
```
Collect n_steps → For n_epochs times: { Update on all minibatches } → Repeat
```
- **More epochs** → More learning from same data → Higher sample efficiency → More risk of overfitting
- **Fewer epochs** → Less learning per rollout → Lower sample efficiency → More diverse training

**How to tune:**

**If learning is too slow (not reaching good performance):**
- **Increase** n_epochs (e.g., 6 → 8 or 10)
- **Effect:** Extract more learning from each rollout
- **Risk:** Overfitting to old data (policy diverges from rollout distribution)

**If `approx_kl` is growing too high (>0.03):**
- **Decrease** n_epochs (e.g., 10 → 6)
- **Effect:** Less divergence from rollout policy
- **Cost:** Lower sample efficiency

**If training is overfitting (good training metrics, bad bot_eval):**
- **Decrease** n_epochs (e.g., 8 → 4)
- **Effect:** Policy stays closer to data distribution
- **Cost:** Need more total episodes to converge

**For Phase 1 (simpler learning goal):**
- **Lower n_epochs** OK (4-6)
- Don't need to squeeze every last bit from data

**For Phase 2/3 (complex strategy):**
- **Higher n_epochs** helpful (8-12)
- Need to learn efficiently from diverse scenarios

**Trade-offs:**
- ✅ More epochs: Higher sample efficiency, faster convergence, fewer total episodes needed
- ❌ More epochs: Risk of overfitting to old policy, higher per-rollout time
- ✅ Fewer epochs: Fresher data, less overfitting, faster rollouts
- ❌ Fewer epochs: Lower sample efficiency, need more total episodes

**Relationship to other parameters:**
- Works with `target_kl`: If using target_kl, it will early-stop epochs when KL threshold hit
- Works with `learning_rate`: Higher LR + more epochs = aggressive learning (risky)
- Works with `batch_size`: More epochs × larger batches = very smooth but slow learning

**Your value analysis (6):**
- ✅ Standard value (from original PPO paper)
- ✅ Good for Phase 1 (not overfitting)
- 💡 **Recommended next experiment:** Try n_epochs=8
  - Could extract 33% more learning per rollout
  - May help sustain peak performance longer
  - Low risk given your stable foundation

**Math for your config:**
```
n_steps=2048, batch_size=256, n_epochs=6
→ (2048 / 256) × 6 = 48 gradient updates per rollout
→ 2000 episodes / 51 episodes per rollout ≈ 39 rollouts
→ 39 rollouts × 48 updates = 1,872 total gradient updates in Phase 1
```

---

## 🛡️ POLICY CONSTRAINTS

### `clip_range` - PPO Clipping Threshold

**What it is:** Maximum allowed ratio change between old and new policy

**Your value:** `0.2`

**Typical range:** `0.1 - 0.3`

**What it controls:**
- **Direct control for `f_clip_fraction`** (what % of updates hit the clip limit)
- Size of policy changes per update
- Training stability vs speed trade-off

**How it works:**
```
PPO clips the probability ratio to [1-clip_range, 1+clip_range]
ratio = new_policy(action) / old_policy(action)
clipped_ratio = clip(ratio, 1-0.2, 1+0.2) = clip(ratio, 0.8, 1.2)
```
- If ratio > 1.2 → **Clipped** → Action became 20%+ more likely → Update limited
- If 0.8 < ratio < 1.2 → **Not clipped** → Normal gradient update
- If ratio < 0.8 → **Clipped** → Action became 20%+ less likely → Update limited

**What `clip_fraction` tells you:**
- `clip_fraction = 0.099` means 9.9% of your updates are hitting the clip limit
- **Target: 10-30%** (sweet spot for learning speed vs stability)
- Too low → Wasting the clipping mechanism (could learn faster)
- Too high → Hitting limits constantly (updates being blocked)

**How to tune:**

**If `clip_fraction` is in range (0.1-0.3):**
- ✅ **Leave clip_range alone!** It's working correctly.
- Adjust `learning_rate` instead to fine-tune clip_fraction

**If learning is unstable (policy collapsing):**
- **Decrease** clip_range (e.g., 0.2 → 0.15)
- **Effect:** Tighter limit on policy changes, more conservative
- **When:** Use with high learning_rate to prevent overshooting

**If learning is too conservative (getting stuck):**
- **Increase** clip_range (e.g., 0.2 → 0.25)
- **Effect:** Allow larger policy changes per update
- **Risk:** Can cause instability

**Trade-offs:**
- ✅ Tighter clip (0.1-0.15): More stable, prevents catastrophic updates, good for complex tasks
- ❌ Tighter clip: Slower learning, might not escape local optima
- ✅ Looser clip (0.25-0.3): Faster learning, more aggressive exploration
- ❌ Looser clip: Less stable, risk of policy collapse

**Relationship to other parameters:**
- Works with `learning_rate`: LR controls how much you try to move, clip_range controls maximum allowed movement
- Works with `target_kl`: target_kl is a soft limit (early stopping), clip_range is hard limit (clipping)
- Independent of `n_steps`, `batch_size`: These affect gradient, not the clip operation

**Your value analysis (0.2):**
- ✅ Standard PPO value (from original paper)
- ✅ Produced clip_fraction ~0.099 (just below ideal 0.1-0.3)
- ✅ Not causing instability
- 💡 Could try 0.15 if you increase learning_rate (tighter safety net)
- 💡 Current value is fine - focus on tuning learning_rate instead

**Why 0.2 is standard:**
- Original PPO paper tested 0.1, 0.2, 0.3
- Found 0.2 works well across many tasks
- Conservative enough to be stable, loose enough to learn fast

---

### `target_kl` - Early Stopping for Policy Updates

**What it is:** KL divergence threshold that stops further epochs if exceeded

**Your value:** `0.03`

**Typical range:** `0.01 - 0.05` (or `null` to disable)

**What it controls:**
- **Soft limit on `g_approx_kl`** (stops epochs early if policy diverges too much)
- Prevents policy from diverging too far from the data it was trained on
- Balances sample efficiency vs on-policy requirement

**How it works:**
```
For epoch 1 to n_epochs:
    Update policy on all minibatches
    Calculate KL divergence between new and old policy
    If KL > target_kl:
        STOP epochs early (don't do remaining epochs)
        Move to next rollout collection
```

**What `approx_kl` tells you:**
- `approx_kl = 0.0061` means policy changed by 0.6% from start of epoch loop
- **Your target_kl = 0.03** means stop if KL exceeds 3%
- Since 0.0061 < 0.03, your epochs complete fully (no early stopping)

**How to tune:**

**If `approx_kl` is consistently below target_kl (like yours: 0.0061 < 0.03):**
- ✅ **target_kl is not limiting your learning** (epochs complete)
- Could increase target_kl or set to `null` (doesn't matter)
- **Or:** Increase learning_rate to use available KL budget

**If `approx_kl` frequently exceeds target_kl:**
- Epochs are being cut short
- **Lower target_kl** if policy is diverging too much (instability)
- **Raise target_kl** if learning is too conservative (stuck)

**If training is unstable:**
- **Decrease** target_kl (e.g., 0.03 → 0.01)
- **Effect:** Forces more conservative updates, more rollouts needed

**If training is too slow:**
- **Increase** target_kl (e.g., 0.03 → 0.05) or set to `null`
- **Effect:** Allows more learning per rollout

**Trade-offs:**
- ✅ Lower target_kl (0.01): More on-policy, more stable, prevents divergence
- ❌ Lower target_kl: Lower sample efficiency (stops epochs early), slower training
- ✅ Higher target_kl (0.05) or null: Higher sample efficiency, faster training
- ❌ Higher target_kl: Risk of off-policy learning (policy diverges from collected data)

**Relationship to other parameters:**
- Works with `n_epochs`: target_kl can prevent all n_epochs from completing
- Works with `learning_rate`: Higher LR → higher KL → more likely to hit target
- Works with `clip_range`: Both limit policy changes (target_kl soft, clip_range hard)

**Your value analysis (0.03):**
- ✅ Standard value (from PPO paper)
- ✅ Not interfering with learning (approx_kl = 0.0061 << 0.03)
- 💡 Could set to `null` (wouldn't change anything for you)
- 💡 Or keep as safety mechanism (if you increase learning_rate later)

**When target_kl matters:**
- Most useful with high learning_rate + many n_epochs
- Acts as emergency brake if updates get too aggressive
- In your case: Not activating (policy changes are small)

---

### `max_grad_norm` - Gradient Clipping Threshold

**What it is:** Maximum allowed L2 norm of gradients (prevents gradient explosion)

**Your value:** `0.5`

**Typical range:** `0.3 - 1.0`

**What it controls:**
- **Direct control for `i_gradient_norm`** (clips if gradient exceeds this value)
- Prevents training explosions from huge gradients
- Training stability safety mechanism

**How it works:**
```
gradient_norm = ||gradient||₂ (L2 norm)
If gradient_norm > max_grad_norm:
    gradient = gradient × (max_grad_norm / gradient_norm)  # Scale down
```
- Acts like a ceiling: Gradients can't exceed this value
- If gradient is 2.0 and max_grad_norm is 0.5 → Scale gradient to 0.5 (clip by 4x)

**What `gradient_norm` tells you:**
- Check `i_gradient_norm` metric
- **Target: <10** (should be well below max_grad_norm in practice)
- If frequently hitting max_grad_norm → Gradients are exploding (bad)

**How to tune:**

**If `gradient_norm` is consistently low (<1.0):**
- ✅ **max_grad_norm is not limiting learning** (good!)
- Could raise max_grad_norm or leave as safety mechanism

**If `gradient_norm` frequently hits max_grad_norm:**
- Gradients are being clipped constantly
- **Reduce learning_rate** first (address root cause)
- Then adjust max_grad_norm if needed

**If training explodes (loss spikes to NaN):**
- **Emergency fix:** Decrease max_grad_norm (e.g., 0.5 → 0.3)
- **Real fix:** Decrease learning_rate significantly

**If learning is too conservative:**
- **Increase** max_grad_norm (e.g., 0.5 → 1.0)
- **Only if:** gradient_norm consistently close to max_grad_norm
- **Rare:** Usually not the bottleneck

**Trade-offs:**
- ✅ Lower max_grad_norm (0.3): More stable, prevents explosions, good for high LR
- ❌ Lower max_grad_norm: Might limit learning if gradients naturally large
- ✅ Higher max_grad_norm (1.0): Allows full gradients, faster learning
- ❌ Higher max_grad_norm: Risk of gradient explosion, NaN losses

**Relationship to other parameters:**
- Works with `learning_rate`: Higher LR → Larger gradients → More likely to hit max_grad_norm
- Independent of `batch_size`: Gradient norm is computed after batch averaging
- Emergency backstop: Last line of defense before training explodes

**Your value analysis (0.5):**
- ✅ Standard conservative value
- ✅ Check `i_gradient_norm` in TensorBoard to see actual values
- 💡 If gradient_norm consistently < 0.5, you're safe
- 💡 If gradient_norm often = 0.5, it's clipping (might need to reduce LR)

**Safety mechanism:**
- Think of this like a fuse in electrical circuits
- Prevents catastrophic failures (NaN losses, policy collapse)
- Rarely the main tuning lever, but critical for stability

---

## ⏰ REWARD DISCOUNTING

### `gamma` - Future Reward Discount Factor

**What it is:** How much future rewards are worth compared to immediate rewards

**Your value:** `0.95`

**Typical range:** `0.9 - 0.999`

**What it controls:**
- **Primary control for `j_immediate_reward_ratio`** (balance short-term vs long-term)
- **Important for `e_explained_variance`** (time horizon for value prediction)
- Agent's planning horizon

**How it works:**
```
Return = r₀ + gamma×r₁ + gamma²×r₂ + gamma³×r₃ + ...
```
- **gamma = 0.95:** Future reward 10 steps away worth 0.95¹⁰ = 59.9% of immediate reward
- **gamma = 0.99:** Future reward 10 steps away worth 0.99¹⁰ = 90.4% of immediate reward
- **gamma = 0.90:** Future reward 10 steps away worth 0.90¹⁰ = 34.9% of immediate reward

**Effective horizon (when reward decays to 1%):**
```
gamma = 0.90 → ~45 steps
gamma = 0.95 → ~90 steps  ← Your setting
gamma = 0.99 → ~450 steps
```

**What this means for W40K:**
- Episode length: ~40 steps (5 turns × 8 steps/turn)
- Your gamma=0.95 horizon (~90 steps) covers **2+ full episodes**
- ✅ Good for learning multi-turn strategy

**What `immediate_reward_ratio` tells you:**
- Measures what % of total episode reward comes from immediate actions vs outcomes
- **Target: <0.90** (want agent learning strategy, not just short-term gains)
- If >0.90 → Agent only cares about immediate rewards (not strategy)

**How to tune:**

**If `immediate_reward_ratio` > 0.90 (agent too short-sighted):**
- **Increase** gamma (e.g., 0.95 → 0.98)
- **Effect:** Agent values long-term outcomes more (winning, positioning)
- **Goal:** Get ratio below 0.90

**If `explained_variance` < 0.30 (value function can't predict):**
- **Increase** gamma (e.g., 0.95 → 0.98)
- **Effect:** Smoother value landscape (less variance from distant rewards)
- Often paired with increasing `gae_lambda`

**If episodes are short (<10 steps):**
- **Lower gamma OK** (0.9-0.95)
- Don't need to look too far ahead

**If episodes are long (>50 steps):**
- **Higher gamma needed** (0.98-0.999)
- Need to connect current actions to distant outcomes

**Trade-offs:**
- ✅ Higher gamma (0.98-0.999): Learns long-term strategy, plans ahead, better for complex tasks
- ❌ Higher gamma: Harder credit assignment, slower learning, higher variance
- ✅ Lower gamma (0.9-0.95): Faster learning, lower variance, easier credit assignment
- ❌ Lower gamma: Short-sighted, misses long-term patterns, poor strategy

**Relationship to other parameters:**
- Works with `gae_lambda`: Should be similar (both control time horizon)
- Works with `n_steps`: Longer n_steps needs higher gamma (look further)
- Works with reward structure: High gamma requires good long-term rewards (win bonus)

**Your value analysis (0.95):**
- ✅ Good balance for W40K episode length
- ✅ Horizon of ~90 steps covers 2+ episodes
- 💡 **Check `j_immediate_reward_ratio` in TensorBoard**
  - If >0.90 → Increase to 0.97 or 0.98
  - If <0.70 → Your rewards emphasize long-term well (good!)

**Math for your setting:**
```
gamma = 0.95
Episode length = 40 steps
Effective horizon = ln(0.01) / ln(0.95) ≈ 90 steps

Reward decay:
- 1 turn (8 steps) away: 0.95⁸ = 66% of immediate reward ✅
- 2 turns (16 steps) away: 0.95¹⁶ = 44% ✅
- 3 turns (24 steps) away: 0.95²⁴ = 29% ✅
- End of episode (40 steps): 0.95⁴⁰ = 13% (still matters!)
```

**Strategy consideration:**
- In W40K, winning matters more than individual shots
- If win bonus is 35 at end of episode (40 steps away)
- Effective value at start: 35 × 0.95⁴⁰ = 4.5
- Shooting reward: 5.0 (immediate)
- **Shooting is slightly more valuable than winning!** (might explain short-term thinking)
- **Solution:** Increase gamma to 0.97-0.98 OR increase win bonus

---

### `gae_lambda` - GAE Smoothing Parameter

**What it is:** Smoothing factor for Generalized Advantage Estimation (GAE)

**Your value:** `0.9`

**Typical range:** `0.9 - 0.999`

**What it controls:**
- Bias-variance trade-off in advantage estimation
- **Affects `e_explained_variance`** (quality of advantage estimates)
- How much to trust value function vs actual returns

**How it works:**
```
GAE advantage = Σ (gamma × gae_lambda)ᵗ × TD_error_t
```
- **lambda = 0:** Use only 1-step TD error (high bias, low variance)
- **lambda = 1:** Use full Monte Carlo returns (low bias, high variance)
- **lambda = 0.9:** Blend of both (your setting)

**Advantage estimation trade-off:**
- **Low lambda (0.8-0.9):** Trust value function more, lower variance, faster learning, but biased if value function wrong
- **High lambda (0.95-0.999):** Trust actual returns more, less biased, but higher variance, slower learning

**What `explained_variance` tells you:**
- If high (>0.5) → Value function is good → Can use lower lambda (trust critic)
- If low (<0.3) → Value function is bad → Use higher lambda (trust actual returns)

**How to tune:**

**If `explained_variance` < 0.30 (value function struggling):**
- **Increase** gae_lambda (e.g., 0.9 → 0.95 or 0.98)
- **Effect:** Rely more on actual returns, less on critic
- Often paired with increasing `gamma`

**If `explained_variance` > 0.70 (value function excellent):**
- **Can use lower gae_lambda** (e.g., 0.95 → 0.90)
- **Effect:** Faster learning by trusting critic
- **Your case:** explained_variance ~0.57, so 0.9 is reasonable

**If learning is noisy/unstable:**
- **Decrease** gae_lambda (e.g., 0.95 → 0.90)
- **Effect:** Lower variance advantage estimates

**If learning is too biased (stuck at suboptimal policy):**
- **Increase** gae_lambda (e.g., 0.90 → 0.95)
- **Effect:** Less reliance on potentially biased value function

**Trade-offs:**
- ✅ Higher lambda (0.95-0.999): Less biased, better credit assignment, good if value function imperfect
- ❌ Higher lambda: Higher variance, noisier training, slower convergence
- ✅ Lower lambda (0.9): Lower variance, faster convergence, more stable
- ❌ Lower lambda: More biased if value function wrong, can learn wrong things

**Relationship to other parameters:**
- Should be similar to `gamma`: Usually gae_lambda ≤ gamma
- Works with `explained_variance`: Check this to decide lambda value
- Independent of `learning_rate`, `batch_size`: Affects advantage computation, not updates

**Your value analysis (0.9):**
- ✅ Standard value (from GAE paper)
- ✅ Good with explained_variance ~0.57 (trusting critic moderately)
- ✅ Lower than gamma (0.9 vs 0.95) → Slightly more value function reliance
- 💡 Could try 0.95 if you want less bias (match gamma)

**Rule of thumb:**
```
If explained_variance > 0.7 → Use gae_lambda = 0.9 (trust critic)
If explained_variance 0.3-0.7 → Use gae_lambda = 0.95 (balanced)
If explained_variance < 0.3 → Use gae_lambda = 0.98 (trust returns)

Your case: EV = 0.57 → gae_lambda = 0.9 is reasonable ✅
```

**Why gae_lambda matters:**
```
Example: 5-step sequence with rewards [1, 1, 1, 1, 10]
Value function predicts: V₀ = 5

lambda = 0 (TD(0)):
    advantage = 1 + gamma×V₁ - V₀ = biased by V₁ estimate

lambda = 1 (Monte Carlo):
    advantage = 1+1+1+1+10 - V₀ = 14 - 5 = 9 (high variance)

lambda = 0.9 (GAE):
    advantage = weighted blend (smooths variance while reducing bias)
```

---

## ⚖️ LOSS WEIGHTING

### `ent_coef` - Entropy Coefficient (Exploration Bonus)

**What it is:** Weight of entropy bonus in the total loss function

**Your value:** `0.75`

**Typical range:** `0.0 - 1.0` (typically 0.01 - 0.3 for most tasks)

**What it controls:**
- **Direct and complete control of `h_entropy_loss`**
- Policy stochasticity (exploration vs exploitation)
- How deterministic vs random the agent's actions are

**How it works:**
```
Total Loss = Policy Loss + vf_coef × Value Loss - ent_coef × Entropy

Entropy = -Σ p(action) × log(p(action))
- High entropy: Uniform distribution (all actions equally likely) → Random
- Low entropy: Peaked distribution (one action very likely) → Deterministic
```

**Effect of ent_coef:**
- **High ent_coef (0.5-1.0):** Agent strongly incentivized to explore, stays random
- **Low ent_coef (0.01-0.1):** Agent allowed to become deterministic, exploits known strategies

**What `entropy_loss` tells you:**
- **Target: 0.5 to 2.0** (positive means policy is stochastic)
- **Your runs: -1.0 to -1.2** (NEGATIVE = too deterministic!) ❌
- Negative entropy_loss means agent has converged to very deterministic policy

**How to tune:**

**If `entropy_loss` is negative (like yours: -1.194):**
- ❌ **This is the problem in ALL your runs!**
- Policy has collapsed (too deterministic, stopped exploring)
- **Should increase ent_coef** but... paradox:

**Your Phase 1 ent_coef history:**
```
Run #1: ent_coef=0.3  → entropy_loss=-1.06
Run #5: ent_coef=0.75 → entropy_loss=-1.167
Run #6: ent_coef=0.3  → entropy_loss=-1.058 (catastrophic overfitting)
Run #7: ent_coef=0.75 → entropy_loss=-1.194
```

**The paradox:** Higher ent_coef made entropy WORSE! Why?

**Answer:** Your entropy_loss metric may be inverted or scaled differently
- Standard entropy loss should be POSITIVE for stochastic policies
- Your negative values suggest either:
  1. Metric calculation is inverted (negative = good?) 
  2. Or policy truly collapsed despite high ent_coef

**If entropy is actually collapsed (assuming metric is correct):**
- Your ent_coef=0.75 is VERY high (much higher than typical 0.01-0.3)
- But agent still deterministic → Something else is causing collapse
- **Likely culprit:** Overfitting to single fixed scenario

**Trade-offs:**
- ✅ Higher ent_coef (0.3-1.0): More exploration, less overfitting, discovers more strategies
- ❌ Higher ent_coef: Slower convergence, less efficient, noisy policies
- ✅ Lower ent_coef (0.01-0.1): Faster convergence, more efficient, cleaner policies
- ❌ Lower ent_coef: Overfitting, premature convergence, gets stuck in local optima

**Relationship to other parameters:**
- Independent of `learning_rate`, `batch_size`: Controls policy distribution, not updates
- Works with `gamma`: Higher gamma + higher ent_coef = broad exploration of long-term strategies
- Trade-off with `clip_fraction`: High ent_coef resists large policy changes (keeps distribution spread out)

**Your value analysis (0.75):**
- ⚠️ **VERY HIGH** for RL tasks (typical is 0.01-0.3)
- ⚠️ Despite high value, entropy_loss still negative
- ❌ Suggests exploration problem is NOT ent_coef
- 💡 **Real issue:** Training on single fixed scenario → Agent memorizes instead of learning general strategy

**What negative entropy_loss reveals:**
```
Standard entropy for uniform distribution (12 actions): log(12) ≈ 2.48
Your entropy_loss: -1.194

This suggests policy entropy close to 0 (peaked distribution)
Example: p(best_action) = 0.95, p(others) = 0.05/11

Despite ent_coef=0.75 (high exploration pressure), agent converged to deterministic policy
→ Fixed scenario overfitting is overwhelming exploration incentive
```

**Recommendation:**
- ✅ Keep ent_coef=0.75 for Phase 1 (not the problem)
- ❌ Don't increase further (diminishing returns)
- 🎯 **Move to Phase 2 with scenario variety** (will naturally improve exploration)

---

### `vf_coef` - Value Function Coefficient

**What it is:** Weight of value function loss in the total loss function

**Your value:** `1.0`

**Typical range:** `0.25 - 1.0`

**What it controls:**
- How much the model prioritizes learning the critic (value function)
- **Indirectly affects `e_explained_variance`** (by prioritizing value learning)
- Balance between policy learning and value learning

**How it works:**
```
Total Loss = Policy Loss + vf_coef × Value Loss - ent_coef × Entropy

vf_coef = 1.0: Value loss weighted equally with policy loss
vf_coef = 0.5: Value loss weighted half as much
vf_coef = 2.0: Value loss weighted twice as much
```

**What `explained_variance` tells you:**
- If low (<0.3) → Value function not learning → Consider increasing vf_coef
- If high (>0.5) → Value function working well → Current vf_coef is fine

**How to tune:**

**If `explained_variance` is low (<0.30):**
- **Increase** vf_coef (e.g., 0.5 → 1.0 or 1.0 → 2.0)
- **Effect:** Prioritize critic learning, improve advantage estimates
- **Also consider:** Increase gamma, gae_lambda (might be value estimation problem, not weight problem)

**If `explained_variance` is good (>0.50) but policy not learning:**
- **Decrease** vf_coef (e.g., 1.0 → 0.5)
- **Effect:** Shift compute to policy learning
- **Rare:** Usually not the bottleneck

**If training is unstable:**
- **Increase** vf_coef (e.g., 0.5 → 1.0)
- **Effect:** Better value function → Better advantages → More stable policy updates

**Standard values by algorithm:**
```
Original PPO paper: vf_coef = 0.5
Modern implementations: vf_coef = 1.0 ← Your setting
Conservative: vf_coef = 2.0 (prioritize critic)
```

**Trade-offs:**
- ✅ Higher vf_coef (1.0-2.0): Better value function, better advantages, more stable learning
- ❌ Higher vf_coef: Less compute for policy, might slow policy convergence
- ✅ Lower vf_coef (0.25-0.5): More focus on policy, faster policy updates
- ❌ Lower vf_coef: Worse value function, worse advantages, less stable

**Relationship to other parameters:**
- Works with `gamma`, `gae_lambda`: These affect what value function learns, vf_coef affects how much
- Independent of `learning_rate`: LR controls update size, vf_coef controls loss weighting
- Complements `ent_coef`: Both weight different loss components

**Your value analysis (1.0):**
- ✅ Modern standard value
- ✅ Produced explained_variance ~0.57 (working well)
- ✅ No need to change
- 💡 If explained_variance drops below 0.3 in future phases, try 2.0

**When to adjust:**
- **Rarely needed** - most tasks work fine with 1.0
- Only adjust if explained_variance is poor AND gamma/gae_lambda already tuned
- More about balancing compute than fixing problems

---

## 🧠 NETWORK ARCHITECTURE

### `policy_kwargs: { net_arch: [320, 320] }` - Neural Network Structure

**What it is:** Size and depth of the neural network layers

**Your value:** `[320, 320]` (2 hidden layers, 320 neurons each)

**Typical range:** `[64, 64]` to `[512, 512]` (2-3 layers, 64-512 neurons per layer)

**What it controls:**
- Model capacity (how complex patterns it can learn)
- Training time and memory usage
- Overfitting vs underfitting trade-off

**How it works:**
```
Network structure:
Input (295 obs features) → Hidden1 (320 neurons) → Hidden2 (320 neurons) → Outputs

Outputs: 
- Policy head: 12 action probabilities
- Value head: 1 value estimate

Total parameters: ~295×320 + 320×320 + 320×12 + 320×1 ≈ 200K parameters
```

**Your architecture:**
```
Input size: 295 floats
  - 72 features: Ally units (10 units × 7.2 features each)
  - 138 features: Enemy units (10 units × 13.8 features each)
  - 35 features: Valid targets (5 targets × 7 features each)
  - Plus: game state, position, etc.

Hidden layers: [320, 320]
  - Layer 1: 295 inputs → 320 neurons (94,400 parameters)
  - Layer 2: 320 → 320 neurons (102,400 parameters)
  - Policy head: 320 → 12 actions (3,840 parameters)
  - Value head: 320 → 1 value (320 parameters)

Total: ~201K parameters (moderate size)
```

**Network capacity consideration:**
```
Rule of thumb: Need ~10 parameters per input feature
Your inputs: 295 features
Your parameters: 201K
Ratio: 201K / 295 ≈ 681 parameters per input feature ✅ Good capacity
```

**How to tune:**

**If agent can't learn complex patterns (underfitting):**
- **Increase** network size
- Options:
  - Add a layer: `[320, 320]` → `[320, 320, 320]`
  - Increase neurons: `[320, 320]` → `[512, 512]`
  - **Cost:** Slower training, more memory

**If agent overfits to training data:**
- **Decrease** network size
- Options:
  - Remove a layer: `[320, 320]` → `[256]`
  - Reduce neurons: `[320, 320]` → `[128, 128]`
  - **Benefit:** Faster training, less overfitting

**For your W40K Phase 1 (simple task: "learn shooting"):**
- `[128, 128]` might be sufficient (smaller, faster)
- `[320, 320]` is comfortable (your setting) ✅
- `[512, 512]` would be overkill

**For Phase 2/3 (complex strategy):**
- `[320, 320]` is good baseline
- `[512, 512]` might help with complex tactics
- `[320, 320, 320]` (3 layers) for very complex

**Trade-offs:**
- ✅ Larger network (512×512): More capacity, learns complex patterns, better for hard tasks
- ❌ Larger network: Slower training (2-4x), more memory, overfits easier
- ✅ Smaller network (128×128): Faster training (2-4x), less overfitting, good for simple tasks
- ❌ Smaller network: Less capacity, can't learn complex patterns, underfits hard tasks

**Relationship to other parameters:**
- Independent of all PPO hyperparameters: Architecture is model choice, not learning choice
- Affects training time: Larger network → slower per-step
- Affects overfitting risk: Larger network → needs more `ent_coef` or more data

**Your value analysis ([320, 320]):**
- ✅ Good moderate size for W40K complexity
- ✅ 201K parameters sufficient for Phase 1-3
- ✅ Not too large (fast training: 6-10 min per 2000 episodes)
- ✅ Not too small (can learn strategy)
- 💡 No need to change - architecture is not your bottleneck

**When to adjust:**
- **Almost never during hyperparameter tuning**
- Only change if:
  - Underfitting: All hyperparameters tuned, still can't learn → Make bigger
  - Overfitting: Agent memorizes but doesn't generalize → Make smaller
  - Performance: Training too slow → Make smaller

**Memory usage:**
```
Your network: 201K parameters × 4 bytes (float32) ≈ 800KB per network
With batch_size=256: 800KB × 256 ≈ 200MB in GPU memory (manageable)
Network is NOT causing memory issues ✅
```

---

## 🎯 QUICK REFERENCE: YOUR CONFIG ANALYSIS

### Current Phase 1 Settings
```json
{
  "learning_rate": 0.0015,      // ✅ Good, clip_fraction ~0.099 (just below target)
  "n_steps": 2048,              // ✅ Good for episode length (~50 episodes per rollout)
  "batch_size": 256,            // ✅ Good balance (stable gradients)
  "n_epochs": 6,                // 💡 Try 8 next (extract more learning per rollout)
  "gamma": 0.95,                // ✅ Good horizon (~90 steps, covers 2+ episodes)
  "gae_lambda": 0.9,            // ✅ Good with explained_variance ~0.57
  "clip_range": 0.2,            // ✅ Standard value, working well
  "ent_coef": 0.75,             // ⚠️ High but not fixing entropy collapse
  "vf_coef": 1.0,               // ✅ Modern standard, EV ~0.57 is good
  "max_grad_norm": 0.5,         // ✅ Conservative safety mechanism
  "target_kl": 0.03,            // ✅ Not limiting (approx_kl ~0.006)
  "net_arch": [320, 320]        // ✅ Good capacity for W40K
}
```

### Metric Results (Run #7)
```
✅ clip_fraction: 0.099 (target: 0.1-0.3) - Just need small LR bump
✅ explained_variance: 0.572 (target: >0.3) - Value function working well
✅ approx_kl: 0.0061 (target: <0.02) - Stable policy updates
✅ gradient_norm: <10 (implicit) - No explosions
❌ entropy_loss: -1.194 (target: 0.5-2.0) - Collapsed despite high ent_coef
⚠️ bot_eval_combined: 0.28 (target: 0.70) - Main problem remains
```

### Recommended Next Experiment (Run #8)
```json
{
  "n_epochs": 8,  // ← ONLY CHANGE (from 6)
  // Keep all other parameters the same
}
```

**Expected improvements:**
- More learning per rollout (33% more gradient updates)
- May sustain peak performance longer (prevent decline after episode 1500)
- Clip fraction may improve slightly (0.099 → 0.11)
- Low risk (standard PPO technique)

---

## 📚 RECOMMENDED READING ORDER

**For quick tuning:**
1. Read `learning_rate` - Primary lever for clip_fraction
2. Read `ent_coef` - Primary lever for exploration
3. Read `gamma` - Important for strategy learning
4. Read Quick Reference Card at end

**For deep understanding:**
1. Read all "Learning & Optimization" section (LR, n_steps, batch_size, n_epochs)
2. Read "Reward Discounting" section (gamma, gae_lambda)
3. Read "Policy Constraints" section (clip_range, target_kl, max_grad_norm)
4. Read "Loss Weighting" section (ent_coef, vf_coef)
5. Skip "Network Architecture" unless having capacity issues

**For troubleshooting:**
1. Check metrics in TensorBoard
2. Find which metric is out of range
3. Jump to that parameter's section in this guide
4. Follow the tuning instructions

---

**Document Version:** 1.0  
**Created:** 2025-01-16  
**Covers:** All PPO hyperparameters for W40K AI Training Phase 1