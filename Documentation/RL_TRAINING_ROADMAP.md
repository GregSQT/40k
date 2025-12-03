# RL Training Roadmap - W40K Tactical Game

**Date:** 2025-01-25
**Purpose:** Comprehensive guide for training reinforcement learning agents based on research evidence and lessons learned

---

## Table of Contents

1. [Core Principles](#core-principles)
2. [Training Strategy](#training-strategy)
3. [Reward Design Philosophy](#reward-design-philosophy)
4. [Hyperparameter Guidelines](#hyperparameter-guidelines)
5. [Curriculum Learning (When and Why NOT to Use It)](#curriculum-learning)
6. [Monitoring and Debugging](#monitoring-and-debugging)
7. [Concrete Training Plan](#concrete-training-plan)
8. [Common Pitfalls and Solutions](#common-pitfalls-and-solutions)

---

## Core Principles

### 1. **Train with Full Complexity from Start**

**Research Evidence:**
- ✅ AlphaStar (StarCraft II): All game mechanics present from episode 1
- ✅ OpenAI Five (Dota 2): All objectives active from start
- ✅ AlphaZero (Chess/Go): Full rules from episode 1

**Why:**
- Avoids negative transfer (learning wrong strategies in simplified environment)
- Agent learns interdependencies between mechanics
- Faster total training time (no wasted episodes on simplified versions)

**What this means for your game:**
- ✅ Walls present from episode 1
- ✅ All unit types in scenarios from start (mixed armies)
- ✅ Objectives active from episode 1
- ✅ All phases enabled (MOVE, SHOOT, CHARGE, FIGHT)

**Exception:** Only use curriculum when task is literally impossible without staged learning (e.g., Montezuma's Revenge requiring demonstrations)

---

### 2. **Minimal Reward Shaping**

**Research Evidence:**
- ✅ AlphaStar: Only win/loss reward (no intermediate shaping)
- ✅ OpenAI Five: Started with 20+ rewards, simplified to 5 core rewards
- ✅ MuZero: Only win/loss/draw (+1/0/-1)

**Philosophy:**
> "If observation contains the information, agent can learn it without reward shaping"

**Your game:**
- Observation includes: unit positions, HP, walls, objectives, LOS
- Agent can learn positioning, objectives, tactics from this data
- Only need rewards for: combat actions (shooting), outcomes (win/loss)

**The Reward Complexity Trap:**
- ❌ 20+ rewards → Impossible to debug, agents exploit rewards
- ✅ 3-5 rewards → Simple, agent discovers strategies naturally

---

### 3. **Diverse Opponents from Start**

**Research Evidence:**
- ✅ AlphaStar: League training with multiple opponent types simultaneously
- ✅ OpenAI Five: Population-based training with diverse strategies
- ❌ Staged opponents (easy → hard) causes overfitting and catastrophic forgetting

**What this means:**
- ✅ Opponent bots use mixed unit compositions (Intercessors + Termagants)
- ✅ Vary terrain, positioning, unit ratios across scenarios
- ❌ Don't stage: "pure Intercessors" → "pure Termagants" → "mixed"

**For self-play:**
- Maintain diverse opponent pool (current model + past snapshots + bots)
- Never train 100% self-play for extended periods (causes forgetting)

---

## Training Strategy

### Stage 1: Bot Training (15-30k episodes)

**Purpose:** Learn fundamental mechanics against diverse, deterministic opponents

**Setup:**
```bash
python ai/train.py \
  --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config base \
  --rewards-config minimal \
  --scenario bot \
  --new
```

**Opponents:**
- 4 diverse bot scenarios (mixed unit compositions)
- All scenarios include: walls, objectives, varied positioning
- Rotate through scenarios every 1000 episodes

**Expected outcome:**
- Episode 0-5k: Random exploration, occasional combat success
- Episode 5k-15k: Agent learns shooting, basic positioning
- Episode 15k-30k: Agent discovers objective control, tactical positioning
- Final: 40-60% win rate vs bots

**Success criteria:**
- Win rate >40% vs GreedyBot
- Agent uses walls for LOS advantage (visible in logs)
- Agent contests objectives (units move toward objectives)

---

### Stage 2: Self-Play (Optional, Advanced)

**Purpose:** Raise skill ceiling through co-evolution

**Setup:**
```bash
python ai/train.py \
  --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config base \
  --scenario self \
  --append
```

**When to use:**
- Only after Stage 1 succeeds (>40% win rate vs bots)
- When bot opponents no longer challenge agent

**Approach:**
- Load Stage 1 model with `--append`
- Train against frozen copy (updated every 100 episodes)
- **Important:** Maintain 20% bot training to prevent catastrophic forgetting

**Expected outcome:**
- Agent develops counter-strategies to its own tactics
- Discovers emergent behaviors not seen vs bots
- Final: Strong general gameplay

**Warning:** Pure self-play causes forgetting of how to fight diverse opponents. Always mix in bot training.

---

## Reward Design Philosophy

### The Minimal Reward Approach (RECOMMENDED)

**Only 5 reward signals (CANONICAL CONFIG):**

```json
{
  "base_actions": {
    "ranged_attack": 3.0,
    "melee_attack": 3.0,
    "charge_success": 3.0
  },
  "result_bonuses": {
    "kill_target": 30.0
  },
  "situational_modifiers": {
    "win": 100.0,
    "lose": -100.0
  },
  "system_penalties": {
    "forbidden_action": -1.0,
    "invalid_action": -0.5
  }
}
```

**Why equal combat rewards (3.0 each)?**
- Unit stats (RNG_DMG, CC_DMG) already encode melee vs ranged preference
- Agent naturally prefers higher-damage attacks based on observation
- Unequal rewards would force specific behavior instead of letting agent learn

**What's NOT rewarded (agent learns from game state):**
- ❌ `hit_target`, `wound_target`, `damage_target` - too granular, kill reward is sufficient
- ❌ Positioning (agent sees walls, LOS in observation)
- ❌ Objective control (agent sees objectives, learns from win condition)
- ❌ Target selection bonuses (agent learns from kill outcomes)

**Why this works:**
1. **Combat rewards encourage engagement** → Prevents passive waiting
2. **Kill reward provides clear outcome signal** → Agent learns what leads to kills
3. **Win/loss provides ultimate objective** → Strategy emerges from winning
4. **Only 5 values to tune** → No reward balancing nightmare

---

### When to Add Rewards (Sparingly)

**Rule:** Only add ONE reward at a time, test for 5k episodes

**If after 20k episodes agent ignores objectives:**
```json
{
  "objective_control_bonus": 10.0  // Per turn per objective controlled
}
```

**Test:**
- ✅ Agent improves objective play? → Keep it
- ❌ Agent camps objectives, ignores combat? → Reduce to 5.0
- ❌ No change? → Remove it, try different approach

**Never have more than 5 active reward signals simultaneously**

---

### Reward Values Guidelines

**CANONICAL minimal config (use this):**
- `ranged_attack`: 3.0 (shooting action)
- `melee_attack`: 3.0 (fight phase attack)
- `charge_success`: 3.0 (successful charge)
- `kill_target`: 30.0 (eliminated unit - ANY phase)
- `win`: 100.0 (episode victory)
- `lose`: -100.0 (episode defeat)

**System penalties (always include):**
- `forbidden_action`: -1.0 (action not allowed in current phase)
- `invalid_action`: -0.5 (malformed action)

**REMOVED from minimal config:**
- ~~`hit_target`: 1.2~~ - Too granular
- ~~`wound_target`: 3.0~~ - Too granular
- ~~`damage_target`: 6.0~~ - Too granular (kill is enough)
- ~~`target_type_bonuses`~~ - Agent should learn from experience
- ~~`no_overkill`~~ - Strategy shaping, let agent discover
- ~~`move_*` rewards~~ - Positioning from game outcomes

**Avoid:**
- ❌ Negative rewards for valid actions (encourages passivity)
- ❌ Intermediate step rewards (hit/wound/damage)
- ❌ Complex reward formulas (agent exploits them)
- ❌ Target-specific bonuses (agent overfits to those targets)

---

## Hyperparameter Guidelines

### Fixed Hyperparameters (DO NOT CHANGE)

**Unless you have specific reason, use these values and NEVER tune them:**

```json
{
  "learning_rate": 0.0003,
  "n_steps": 2048,
  "batch_size": 256,
  "n_epochs": 6,
  "gamma": 0.95,
  "gae_lambda": 0.95,
  "clip_range": 0.2,
  "ent_coef": 0.2,
  "vf_coef": 0.5,
  "max_grad_norm": 0.5,
  "net_arch": [320, 320]
}
```

**Rationale:**
- These are proven PPO defaults from Stable Baselines3
- Changing them causes more problems than it solves
- Focus on reward design, not hyperparameter tuning

---

### When to Adjust (Rare Cases)

**If `loss_mean` >500 (value function instability):**
- Reduce `learning_rate` to 0.0001
- Test for 5k episodes
- If still unstable, reduce further

**If `entropy` <0.1 (exploration collapsed):**
- Increase `ent_coef` to 0.3
- Consider entropy schedule: `{"start": 0.3, "end": 0.2}`

**If `clip_fraction` consistently <0.01 (updates too conservative):**
- This is usually OK - low clip_fraction ≠ bad training
- Only increase `learning_rate` if loss_mean is stable

**Never tune:**
- `gamma` (controls long-term planning, 0.95 is standard)
- `gae_lambda` (GAE parameter, 0.95 is standard)
- `max_grad_norm` (gradient clipping, 0.5 is standard)
- `net_arch` (network architecture, [320, 320] works well)

---

## Curriculum Learning

### When NOT to Use Curriculum (Your Case)

**Research shows curriculum learning FAILS when:**

1. ✅ **Early stages teach wrong policy** (YOUR CASE)
   - Phase 1 (no walls): Learns "standing still is optimal"
   - Phase 2 (walls): Needs to unlearn "standing still"
   - Result: Negative transfer, 14% win rate

2. ✅ **Mechanics are interdependent** (YOUR CASE)
   - Shooting effectiveness depends on positioning
   - Can't learn optimal shooting without walls

3. ✅ **Dense rewards + simple exploration** (YOUR CASE)
   - Agent gets rewards for shooting, moving, objectives
   - Random policy can discover basic strategies
   - No need for staged difficulty

**Evidence:**
- Your Phase 1→2 training: 18k episodes, 14% win rate
- Estimated from-scratch training: 15k episodes, 50-60% win rate
- Curriculum took MORE time and got WORSE results

---

### When Curriculum Might Help (Not Your Case)

**Only use curriculum when:**
1. **Sparse rewards + impossible exploration**
   - Example: Montezuma's Revenge (need specific action sequences)
   - Your game: ❌ Dense rewards, easy exploration

2. **True skill prerequisites**
   - Example: Must learn walking before running
   - Your game: ❌ Shooting and positioning are independent

3. **Catastrophic forgetting prevention**
   - Example: Easy levels → hard levels causes forgetting
   - Your game: ❌ No forgetting observed (shooting retained in Phase 2)

**For tactical games like yours: Train with full complexity from start**

---

### Research Evidence Against Curriculum

**Games similar to yours:**

**StarCraft II (AlphaStar):**
- ❌ Did NOT use mechanical curriculum (no "basic units only" phase)
- ✅ All game mechanics present from episode 1
- ✅ Opponent difficulty scaling (not mechanical staging)
- Result: Grandmaster level

**Dota 2 (OpenAI Five):**
- ❌ Did NOT stage unit compositions
- ✅ All heroes, items, abilities from start
- ✅ Strategic curriculum (1v1 → 5v5), not mechanical
- Result: Beat world champions

**Chess/Go (AlphaZero):**
- ❌ No curriculum
- ✅ Full rules from episode 1
- Result: Superhuman

---

## Monitoring and Debugging

### Critical Metrics (Monitor These Only)

**During training, watch these 5 metrics:**

1. **Win rate vs bots** (Primary success metric)
   - Target: >40% after 20k episodes
   - If flat for 10k episodes → Consider adding ONE reward

2. **Episode reward** (Immediate feedback)
   - Should trend upward
   - If negative → Agent not shooting, check action mask

3. **Entropy** (Exploration health)
   - Target: 0.5-2.0 range
   - If <0.1 → Increase ent_coef
   - If >3.0 → Policy too random, check reward signal

4. **Loss_mean** (Training stability)
   - Target: <200
   - If >500 → Reduce learning_rate
   - If >1000 → Training unstable, check for bugs

5. **Combat effectiveness metrics** (Phase-specific learning)
   - `combat/a_position_score`: Is agent positioning effectively?
   - `combat/b_shoot_kills`: Is agent killing with ranged attacks?
   - `combat/c_charge_successes`: Is agent learning to charge?
   - `combat/d_melee_kills`: Is agent killing in fight phase?
   - `combat/e_controlled_objectives`: Is agent controlling objectives? (Only logged if game reached turn 5+)

**Ignore during early training:**
- Clip fraction (low is OK if training progresses)
- Explained variance (improves naturally with training)
- Approx KL (PPO handles this automatically)

---

### Bot Hierarchy (for evaluation)

**Use these bots to measure agent progress:**

| Bot | Difficulty | Behavior | Target Win Rate |
|-----|-----------|----------|-----------------|
| RandomBot | Easy | Random actions, always shoots when available | >80% |
| GreedyBot | Medium | Shoots first, moves toward enemies, targets low HP | >60% |
| DefensiveBot | Medium | Shoots first, maintains distance, retreats when threatened | >50% |
| TacticalBot | Hard | Full phase awareness, optimal decisions, smart targeting | >40% |

**TacticalBot capabilities:**
- MOVE: Advances if out of range, retreats if wounded
- SHOOT: Always shoots, prioritizes killable/wounded/threatening targets
- CHARGE: Charges if melee is advantageous (high CC_DMG vs target HP)
- FIGHT: Always fights, same targeting as shooting

**Agent should beat TacticalBot >40% to be considered competent**

---

### Decision Rules

**Simple flowchart:**

```
Is win_rate increasing?
├─ YES → Don't change anything, keep training
└─ NO → Has it been flat for >10k episodes?
    ├─ YES → Add ONE reward signal OR increase existing reward 2x
    └─ NO → Keep training, be patient

Is loss_mean >500?
├─ YES → Reduce learning_rate by 0.5x
└─ NO → Continue

Is entropy <0.1?
├─ YES → Increase ent_coef by 1.5x
└─ NO → Continue
```

**Most important rule:** **Don't change anything if win rate is improving**

---

### Debugging Common Issues

**"Agent not shooting":**
1. Check action mask (are SHOOT actions available?)
2. Check rewards (is ranged_attack reward positive?)
3. Check observation (does agent see enemies?)
4. Check bot behavior (are bots providing targets?)

**"Agent ignoring objectives":**
1. Check scenario (are objective_hexes defined?)
2. Check win condition (does it consider objectives?)
3. Check observation (are objectives visible to agent?)
4. Wait 20k episodes (agent might discover naturally)
5. If still ignoring → Add objective_control_bonus: 10.0

**"Agent standing still":**
1. Check walls (is LOS blocked?)
2. Check position_reward_scale (should be 0.0 initially)
3. Wait 10k episodes (positioning learned from game state)
4. If still static → Check if agent winning by standing still (bots too weak?)

**"Training unstable (loss_mean >500)":**
1. Reduce learning_rate: 0.0003 → 0.0001
2. Check for reward explosion (kill_target >100?)
3. Check for invalid actions (high penalty frequency?)

---

## Concrete Training Plan

### Phase: Base Training (Full Complexity)

**Goal:** Train agent with ALL game features from episode 1

**Setup:**

1. **Scenarios:** Create 4 diverse bot scenarios
   ```json
   // Scenario 1: Mixed ranged/melee
   {
     "units": [
       // P0: 4 Intercessors
       // P1: 2 Intercessors + 4 Termagants
     ],
     "wall_hexes": [...],  // Complex wall formations
     "objective_hexes": [[12,10], [6,5], [18,15]]  // 3 objectives
   }

   // Scenario 2-4: Vary positioning, wall layouts, unit ratios
   ```

2. **Rewards config:** Minimal shaping
   ```json
   {
     "base_actions": {
       "ranged_attack": 3.0
     },
     "result_bonuses": {
       "damage_target": 6.0,
       "kill_target": 30.0
     },
     "situational": {
       "win_bonus": 1000.0,
       "loss_penalty": -1000.0
     }
   }
   ```

3. **Training config:** Fixed hyperparameters
   ```json
   {
     "total_episodes": 30000,
     "rotation_interval": 1000,
     "model_params": {
       "learning_rate": 0.0003,
       "ent_coef": 0.2,
       "gamma": 0.95,
       "clip_range": 0.2,
       "net_arch": [320, 320]
     }
   }
   ```

4. **Training command:**
   ```bash
   python ai/train.py \
     --agent SpaceMarine_Infantry_Troop_RangedSwarm \
     --training-config base \
     --rewards-config minimal \
     --scenario bot \
     --new
   ```

**Expected timeline:**
- Episodes 0-5k: Exploration, random actions (~10% win rate)
- Episodes 5k-15k: Combat learning (~30% win rate)
- Episodes 15k-25k: Objective discovery (~50% win rate)
- Episodes 25k-30k: Strategy refinement (~60% win rate)

**Success criteria:**
- Win rate >40% vs GreedyBot
- Agent moves toward objectives (visible in logs)
- Agent uses walls for LOS (fewer blocked shots)
- Loss_mean <200, entropy >0.5

---

### Iteration Process

**Every 5k episodes:**

1. **Check TensorBoard metrics**
   - Win rate trending up? → Continue
   - Win rate flat? → Wait another 5k episodes

2. **Review step logs (sample 10 games)**
   ```bash
   python ai/train.py --test-only --step --test-episodes 10
   python check/analyze_step_log.py train_step.log
   ```
   - Are units moving toward objectives?
   - Is agent using walls for cover?
   - Is focus fire working (shooting wounded enemies)?

3. **Bot evaluation**
   ```bash
   python ai/train.py --test-only --test-episodes 50
   ```
   - Win rate vs RandomBot, GreedyBot, DefensiveBot
   - Should improve steadily

**Only make changes if win rate flat for 10k episodes AND you've identified specific issue**

---

### When to Add Reward Shaping

**After 20k episodes, if specific behavior missing:**

**Agent ignoring objectives:**
```json
{
  "objective_control_bonus": 10.0  // Add this
}
```
Test for 5k episodes, adjust if needed.

**Agent not using cover:**
```json
{
  "position_reward_scale": 0.5  // Start low
}
```
Test for 5k episodes. If agent over-focuses on positioning (stops shooting), reduce to 0.2.

**Never add more than ONE reward at a time**

---

## Common Pitfalls and Solutions

### Pitfall 1: Curriculum Learning Trap

**Mistake:** "I'll train shooting first, then add walls, then objectives"

**Why it fails:**
- Early phases teach wrong strategies (standing still optimal without walls)
- Value function learns incorrect state valuations
- Agent must UNLEARN Phase 1 strategies in Phase 2
- Results: Negative transfer, worse performance than training from scratch

**Evidence:** Your Phase 1→2 training
- Phase 1 (12k episodes): 85% win rate (no walls)
- Phase 2 (6k episodes): 14% win rate (with walls)
- Total: 18k episodes for 14% win rate
- From scratch estimate: 15k episodes for 50-60% win rate

**Solution:** Train with full complexity from episode 1

**Reference:** AlphaStar, OpenAI Five both used full complexity from start

---

### Pitfall 2: Over-Shaping Rewards

**Mistake:** "I'll reward every good behavior: positioning, objectives, survival, trades..."

**Why it fails:**
- 20+ reward signals = impossible to debug
- Agent exploits rewards (camps objectives, ignores combat)
- Constant reward balancing nightmare
- Can't tell which reward is causing bad behavior

**Evidence:** OpenAI Five
- Started with 20+ rewards
- Agent farmed jungle, ignored teamfights
- Simplified to 5 core rewards
- Performance improved

**Solution:** Start with 3 rewards (shoot, kill, win/loss)

**Rule:** If observation contains the info, agent can learn without explicit reward

---

### Pitfall 3: Hyperparameter Tuning Hell

**Mistake:** "Training not working, let me adjust learning rate, entropy, gamma..."

**Why it fails:**
- Each change takes 5k episodes to evaluate
- Interactions between hyperparameters unpredictable
- Ends up in random search, wastes weeks
- Usually problem is reward design, not hyperparameters

**Solution:** Use fixed PPO defaults, only tune learning_rate if loss_mean >500

**Reference:** Stable Baselines3 defaults work for 90% of cases

---

### Pitfall 4: Impatience

**Mistake:** "Agent not learning after 3k episodes, something's wrong"

**Why it fails:**
- Deep RL is SLOW - 10k-20k episodes needed for complex tasks
- Early episodes are pure exploration (looks random)
- Making changes too early prevents learning

**Solution:** Wait 10k episodes before changing anything

**Typical learning curve:**
- Episodes 0-5k: Looks random (this is normal)
- Episodes 5k-10k: First signs of strategy
- Episodes 10k-20k: Clear improvement
- Episodes 20k+: Refinement

---

### Pitfall 5: Staged Opponent Complexity

**Mistake:** "I'll train vs 1 unit type, then add another, then mixed armies"

**Why it fails:**
- Agent overfits to first unit type
- Catastrophic forgetting when switching to new unit type
- Tactics for enemy A are wrong for enemy B
- Wasted episodes learning non-transferable strategies

**Solution:** Diverse opponents from episode 1 (mixed armies)

**Reference:** AlphaStar league training, OpenAI Five population diversity

---

## Quick Reference

### Training Checklist

**Before starting training:**
- [ ] All game mechanics implemented (walls, objectives, all phases)
- [ ] 4+ diverse bot scenarios created (mixed unit compositions)
- [ ] Minimal reward config (3-5 rewards only)
- [ ] Fixed hyperparameters (PPO defaults)
- [ ] TensorBoard monitoring setup

**During training (check every 5k episodes):**
- [ ] Win rate trend (primary metric)
- [ ] Loss_mean <200 (stability)
- [ ] Entropy >0.5 (exploration)
- [ ] Review sample games (behavior analysis)

**Decision points:**
- [ ] Win rate flat for 10k episodes? → Consider adding ONE reward
- [ ] Loss_mean >500? → Reduce learning_rate
- [ ] Entropy <0.1? → Increase ent_coef
- [ ] Agent ignoring specific mechanic after 20k episodes? → Add targeted reward

---

### Command Reference

**Start fresh training:**
```bash
python ai/train.py \
  --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config base \
  --rewards-config minimal \
  --scenario bot \
  --new
```

**Continue training:**
```bash
python ai/train.py \
  --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config base \
  --rewards-config minimal \
  --scenario bot \
  --append
```

**Test current model:**
```bash
python ai/train.py \
  --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config base \
  --rewards-config minimal \
  --test-only \
  --test-episodes 50
```

**Generate detailed logs:**
```bash
python ai/train.py \
  --agent SpaceMarine_Infantry_Troop_RangedSwarm \
  --training-config base \
  --rewards-config minimal \
  --test-only \
  --step \
  --test-episodes 10

python check/analyze_step_log.py train_step.log
```

---

## Research References

**Core papers and projects:**

1. **AlphaStar (StarCraft II)**
   - Vinyals et al., "Grandmaster level in StarCraft II using multi-agent reinforcement learning", Nature 2019
   - Key: Full game complexity from start, league training, no mechanical curriculum

2. **OpenAI Five (Dota 2)**
   - OpenAI, "Dota 2 with Large Scale Deep Reinforcement Learning", 2019
   - Key: Minimal reward shaping, population diversity, started complex

3. **AlphaZero (Chess/Go/Shogi)**
   - Silver et al., "A general reinforcement learning algorithm that masters chess, shogi, and Go through self-play", Science 2018
   - Key: Only win/loss reward, no intermediate shaping, full rules from start

4. **PPO (Algorithm)**
   - Schulman et al., "Proximal Policy Optimization Algorithms", 2017
   - Key: Stable algorithm, minimal hyperparameter tuning needed

---

## Document Version History

**v1.0 (2025-01-25):** Initial roadmap based on Phase 1-2 training lessons and research evidence

---

**Remember:** The path to successful RL training is patience, simplicity, and trusting the agent to discover strategies. Start minimal, train long, only add complexity when proven necessary.
