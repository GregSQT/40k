# AI_OBSERVATION.md
## The Canonical Reference for Agent Observation & Training Systems

> **📍 File Location**: Save as `Documentation/AI_OBSERVATION.md`  
> **Status**: ✅ CANONICAL REFERENCE (December 2025)  
> **Version**: 2.0 - Pure Reinforcement Learning Approach

---

## 📋 DOCUMENT STATUS

**This is THE authoritative reference for:**
- ✅ Observation system architecture
- ✅ Training pipeline integration
- ✅ PPO model configuration
- ✅ Bot evaluation system
- ✅ Performance benchmarks
- ✅ Migration procedures

**Related Documents:**
- `AI_TURN.md` → Game state management (authoritative)
- `AI_IMPLEMENTATION.md` → Handler architecture (authoritative)
- `AI_GAME_OVERVIEW.md` → High-level game rules
- `AI_TRAINING.md` → Training pipeline details & bot behaviors

---

## 🎯 EXECUTIVE SUMMARY

The **Pure RL Observation System** provides agents with fundamental tactical information, allowing PPO networks to discover optimal behavior through experience. This represents a complete redesign from god's-eye absolute coordinates to egocentric perception.

### Key Metrics

| Metric | Value |
|--------|-------|
| **Observation Size** | 165 floats |
| **Perception Radius** | R=25 hexes |
| **Training Speed** | 311 it/s (CPU) |
| **Network Architecture** | 256×256 MlpPolicy |
| **Expected Win Rate** | 80-85% (2000 episodes) |
| **Bot Evaluation Frequency** | Every 5,000 steps |

### Design Philosophy

**Pure Reinforcement Learning:**
- ❌ No pre-computed composite scores
- ❌ No designer bias in observations
- ✅ Agent discovers optimal behavior
- ✅ Network learns feature combinations
- ✅ Robust tactical emergence
- ✅ Progress measured against tactical bots

---

## 🗺️ NAVIGATION

- [System Overview](#system-overview)
- [Observation Architecture](#observation-architecture)
- [Feature Specifications](#feature-specifications)
- [Training Integration](#training-integration)
- [Bot Evaluation System](#bot-evaluation-system)
- [Performance Analysis](#performance-analysis)
- [Migration Guide](#migration-guide)
- [Troubleshooting](#troubleshooting)

---

## 📊 SYSTEM OVERVIEW

### Egocentric vs Absolute Positioning

**Legacy System (Absolute - v0.1):**
```
Agent sees: "Enemy at (15, 7), I'm at (12, 5)"
Problem: Must learn spatial relationships from scratch
Size: 26 floats
```

**Current System (Egocentric - v2.0):**
```
Agent sees: "Enemy 3 hexes ahead-right, threat=0.8, can kill=0.9"
Advantage: Natural directional tactics, position-independent
Size: 165 floats
```

### R=25 Perception Radius

**Coverage Analysis:**
```
Standard Board: 30×20 hexes
Diagonal: √(30² + 20²) ≈ 36 hexes

R=25 Coverage:
├─ From center: 69% of board
├─ From corner: 100% of board
└─ Tactical reach: MOVE(12) + CHARGE(12) + 1 = 25 ✅
```

**Why R=25?**
- Covers all relevant tactical decisions
- Includes weapon ranges (12-24")
- Allows 4-5 turn threat assessment
- Balances obs size vs information density

---

## 🗃️ OBSERVATION ARCHITECTURE

### Structure Overview (165 Floats)

```
┌────────────────────────────────────────────────┐
│  OBSERVATION VECTOR (165 floats)              │
├────────────────────────────────────────────────┤
│  [0:10]    Global Context         (10 floats) │
│  [10:18]   Active Unit            (8 floats)  │
│  [18:50]   Directional Terrain    (32 floats) │
│  [50:120]  Nearby Units           (70 floats) │
│  [120:165] Valid Targets          (45 floats) │
└────────────────────────────────────────────────┘
```

### Section Breakdown

#### 1. Global Context [0:10] - 10 floats

```python
obs[0] = current_player              # 0.0 or 1.0
obs[1] = phase_encoding              # move=0.25, shoot=0.5, charge=0.75, fight=1.0
obs[2] = turn_number / 10.0          # Normalized turn
obs[3] = episode_steps / 100.0       # Step counter
obs[4] = active_unit_hp_ratio        # HP_CUR / HP_MAX
obs[5] = has_moved                   # 1.0 if unit moved
obs[6] = has_shot                    # 1.0 if unit shot
obs[7] = has_attacked                # 1.0 if unit attacked
obs[8] = alive_friendlies / 10       # Normalized count
obs[9] = alive_enemies / 10          # Normalized count
```

#### 2. Active Unit Capabilities [10:18] - 8 floats

```python
obs[10] = MOVE / 12.0                # Movement capability
obs[11] = RNG_RNG / 24.0             # Shooting range
obs[12] = RNG_DMG / 5.0              # Shooting damage
obs[13] = RNG_NB / 10.0              # Number of shots
obs[14] = CC_RNG / 6.0               # Melee range
obs[15] = CC_DMG / 5.0               # Melee damage
obs[16] = T / 10.0                   # Toughness
obs[17] = ARMOR_SAVE / 6.0           # Armor save
```

#### 3. Directional Terrain [18:50] - 32 floats

8 directions × 4 features = 32 floats

**Directions:** N, NE, E, SE, S, SW, W, NW

**Features per direction:**
```python
[direction_base + 0] = wall_distance / 25      # Nearest wall
[direction_base + 1] = friendly_distance / 25  # Nearest ally
[direction_base + 2] = enemy_distance / 25     # Nearest enemy
[direction_base + 3] = edge_distance / 25      # Board edge
```

#### 4. Nearby Units [50:120] - 70 floats

7 units × 10 features = 70 floats

**Features per unit:**
```python
[unit_base + 0] = relative_col / 25.0      # Egocentric X (-1 to +1)
[unit_base + 1] = relative_row / 25.0      # Egocentric Y (-1 to +1)
[unit_base + 2] = is_enemy                 # 1.0 = enemy, 0.0 = ally
[unit_base + 3] = hp_ratio                 # HP_CUR / HP_MAX
[unit_base + 4] = hp_capacity / 10.0       # HP_MAX normalized
[unit_base + 5] = hp_ratio                 # Redundant for stability
[unit_base + 6] = has_moved                # 1.0 if moved
[unit_base + 7] = has_shot                 # 1.0 if shot
[unit_base + 8] = has_charged              # 1.0 if charged
[unit_base + 9] = has_attacked             # 1.0 if attacked
```

**Unit Selection Priority:**
1. Enemies > Allies (1000 priority weight)
2. Closer units (25 - distance) × 10
3. Wounded units (1 - hp_ratio) × 5

#### 5. Valid Targets [120:165] - 45 floats

5 targets × 9 features = 45 floats

**CRITICAL DESIGN:** Direct action-observation correspondence
- Action 4 → obs[120:129] (target slot 0)
- Action 5 → obs[129:138] (target slot 1)
- Action 6 → obs[138:147] (target slot 2)
- Action 7 → obs[147:156] (target slot 3)
- Action 8 → obs[156:165] (target slot 4)

**Features per target (9 floats):**
```python
[target_base + 0] = is_valid                  # 1.0 = target exists
[target_base + 1] = kill_probability          # W40K dice calculation
[target_base + 2] = danger_to_me              # Threat to active unit
[target_base + 3] = hp_ratio                  # Target health
[target_base + 4] = distance_normalized       # Distance / 25
[target_base + 5] = is_lowest_hp              # 1.0 if weakest
[target_base + 6] = army_weighted_threat      # Strategic priority
[target_base + 7] = can_be_charged_by_melee   # Coordination signal
[target_base + 8] = target_type_match         # Unit matchup
```

---

## 🔬 FEATURE SPECIFICATIONS

### Kill Probability Calculation

**W40K Dice Mechanics:**
```python
def _calculate_kill_probability(shooter, target):
    # Hit probability
    p_hit = (7 - shooter.RNG_ATK) / 6.0
    
    # Wound probability
    wound_target = calculate_wound_target(shooter.RNG_STR, target.T)
    p_wound = (7 - wound_target) / 6.0
    
    # Save failure probability
    save_target = calculate_save_target(target, shooter.RNG_AP)
    p_fail_save = (save_target - 1) / 6.0
    
    # Expected damage
    expected_damage = shooter.RNG_NB * p_hit * p_wound * p_fail_save * shooter.RNG_DMG
    
    # Kill probability
    if expected_damage >= target.HP_CUR:
        return 1.0
    else:
        return expected_damage / target.HP_CUR
```

**Output Range:** 0.0-1.0
- 1.0 = Guaranteed kill this turn
- 0.5 = 50% chance to kill
- 0.0 = Cannot kill

### Danger to Me Calculation

**Symmetric to Kill Probability:**
```python
def _calculate_danger_probability(defender, attacker):
    """Probability attacker kills defender on its turn"""
    
    distance = hex_distance(defender, attacker)
    
    # Can attacker reach defender?
    can_shoot = distance <= attacker.RNG_RNG
    can_melee = distance <= attacker.CC_RNG
    
    if not (can_shoot or can_melee):
        return 0.0
    
    # Use attacker's best weapon
    if can_shoot:
        weapon_stats = (attacker.RNG_ATK, attacker.RNG_STR, 
                       attacker.RNG_DMG, attacker.RNG_NB, attacker.RNG_AP)
    else:
        weapon_stats = (attacker.CC_ATK, attacker.CC_STR,
                       attacker.CC_DMG, attacker.CC_NB, attacker.CC_AP)
    
    # Calculate kill probability (same as above)
    return calculate_kill_prob(weapon_stats, defender)
```

**Output Range:** 0.0-1.0
- 1.0 = This enemy will kill me next turn
- 0.5 = 50% chance I die next turn
- 0.0 = Safe from this enemy

### Army Weighted Threat

**Strategic Priority Calculation:**
```python
def _calculate_army_weighted_threat(target, valid_targets):
    """Threat to entire team, weighted by unit VALUE"""
    
    my_player = game_state["current_player"]
    friendlies = [u for u in units if u.player == my_player and u.HP_CUR > 0]
    
    total_weighted_threat = 0.0
    
    for friendly in friendlies:
        # Calculate danger to this friendly unit
        danger = _calculate_danger_probability(friendly, target)
        
        # Weight by unit strategic value
        unit_value = friendly.VALUE  # 10-200 from unit stats
        weighted_threat = danger * unit_value
        
        total_weighted_threat += weighted_threat
    
    # Normalize against all targets
    all_threats = [calculate_for_target(t) for t in valid_targets]
    max_threat = max(all_threats)
    
    return total_weighted_threat / max_threat if max_threat > 0 else 0.0
```

**Output Range:** 0.0-1.0
- 1.0 = Highest strategic threat among all targets
- 0.5 = Medium strategic threat
- 0.0 = Minimal strategic threat

**Example:**
```
Target A: Threatens Leader (VALUE=200) with 0.8 danger → 160 weighted threat
Target B: Threatens Trooper (VALUE=10) with 0.9 danger → 9 weighted threat
→ Target A gets higher army_weighted_threat score
```

### Target Type Match

**Unit Registry Compatibility:**
```python
def _calculate_target_type_match(active_unit, target):
    """Matchup bonus based on unit specialization"""
    
    # Parse unit types
    unit_type = active_unit.unitType  # e.g., "SpaceMarine_Infantry_Troop_RangedSwarm"
    
    # Extract specialization
    if "Swarm" in unit_type:
        preferred = "swarm"
    elif "Troop" in unit_type:
        preferred = "troop"
    elif "Elite" in unit_type:
        preferred = "elite"
    
    # Classify target
    target_hp = target.HP_MAX
    if target_hp <= 1:
        target_class = "swarm"
    elif target_hp <= 3:
        target_class = "troop"
    else:
        target_class = "elite"
    
    # Matchup bonus
    return 1.0 if preferred == target_class else 0.3
```

**Output Range:** 0.0-1.0
- 1.0 = Ideal matchup (RangedSwarm vs Swarm)
- 0.3 = Poor matchup (RangedSwarm vs Elite)

---

## 🎓 TRAINING INTEGRATION

### PPO Model Configuration

**Standard Configuration:**
```python
from stable_baselines3 import PPO

model = PPO(
    policy="MlpPolicy",
    env=engine,
    learning_rate=0.0003,
    n_steps=2048,
    batch_size=64,
    n_epochs=10,
    gamma=0.95,
    gae_lambda=0.95,
    clip_range=0.2,
    ent_coef=0.05,
    vf_coef=0.5,
    max_grad_norm=0.5,
    policy_kwargs={"net_arch": [256, 256]},
    device="cpu",  # CPU optimal for obs_size=165
    tensorboard_log="./tensorboard/",
    verbose=0
)
```

### Network Architecture

```
Input Layer:     165 floats (observation)
       ↓
Hidden Layer 1:  256 neurons (ReLU)
       ↓
Hidden Layer 2:  256 neurons (ReLU)
       ↓
Policy Head:     12 neurons (action probabilities)
Value Head:      1 neuron (state value)
```

**Why 256×256?**
- Input: 165 floats → 256 allows feature expansion
- Compression ratio: 1.55x (good for learning)
- Total params: ~65K (fast training)
- Proven effective for tactical games

### Observation Space Definition

```python
import gymnasium as gym

# In W40KEngine.__init__()
self.observation_space = gym.spaces.Box(
    low=0.0,
    high=1.0,
    shape=(165,),
    dtype=np.float32
)

self.action_space = gym.spaces.Discrete(12)
```

### Action Space Mapping

**12 Discrete Actions:**
```
0-3:  Movement directions (move phase)
4-8:  Target slots 0-4 (shoot phase)
9:    Charge action (charge phase)
10:   Fight action (fight phase)
11:   Wait/Skip (all phases)
```

**Action Masking:**
```python
def get_action_mask():
    mask = np.zeros(12, dtype=bool)
    
    if phase == "move":
        mask[[0, 1, 2, 3, 11]] = True
    elif phase == "shoot":
        # Dynamically enable based on available targets
        valid_targets = get_valid_targets()
        for i in range(min(5, len(valid_targets))):
            mask[4 + i] = True
        mask[11] = True
    # ... etc
    
    return mask
```

---

## 🤖 BOT EVALUATION SYSTEM

### Overview

**Purpose:** Measure agent progress against tactical opponents of varying difficulty during training.

**Key Features:**
- ✅ Objective progress measurement (not just self-play)
- ✅ Multi-difficulty evaluation (easy, medium, hard)
- ✅ Automatic best model selection
- ✅ Both agent and bots follow AI_TURN.md rules
- ✅ Real gameplay battles (not mock results)

### Evaluation Schedule

**Frequency:** Every 5,000 training steps  
**Episodes per bot:** 20 evaluation games  
**Mode:** Deterministic agent actions (no exploration)  
**Total episodes per evaluation:** 60 (20 × 3 bots)

### Evaluation Bots

#### 1. RandomBot ⭐ (Easy - Baseline)

**Strategy:** Pure randomness
```python
def select_action(valid_actions):
    return random.choice(valid_actions)
```

**Characteristics:**
- ❌ No strategy
- 🎲 Random actions, targets, movement
- **Expected agent win rate:** 70-95%

---

#### 2. GreedyBot ⭐⭐ (Medium - Tactical)

**Strategy:** Aggressive, prioritizes damage
```python
def select_action(valid_actions):
    # Priority: Shoot > Move > Wait
    if 4 in valid_actions:
        return 4
    elif 0 in valid_actions:
        return 0
    else:
        return valid_actions[0]

def select_shooting_target(valid_targets, game_state):
    """Target lowest HP enemy"""
    return find_weakest_enemy(valid_targets, game_state)
```

**Characteristics:**
- ✅ Prioritizes shooting
- ✅ Targets weak enemies (low HP)
- ✅ Moves toward combat
- ⚠️ No defensive positioning
- **Expected agent win rate:** 50-80%

---

#### 3. DefensiveBot ⭐⭐⭐ (Hard - Survival)

**Strategy:** Conservative, threat-aware
```python
def select_action_with_state(valid_actions, game_state):
    """Threat-aware action selection"""
    nearby_threats = count_nearby_threats(active_unit, game_state)
    
    # If threatened and can shoot, shoot
    if nearby_threats > 0 and 4 in valid_actions:
        return 4
    
    # If heavily threatened, retreat
    if nearby_threats > 1 and 0 in valid_actions:
        return 0
    
    # Default: Shoot > Wait > Move
    if 4 in valid_actions:
        return 4
    elif 7 in valid_actions:
        return 7
    else:
        return valid_actions[0]
```

**Characteristics:**
- ✅ Threat awareness (counts nearby enemies)
- ✅ Defensive positioning (retreats when outnumbered)
- ✅ Prioritizes survival over aggression
- ✅ Shoots when safe, retreats when threatened
- **Expected agent win rate:** 40-70%

---

### Combined Scoring System

**Weighted Win Rate Calculation:**
```python
combined_win_rate = (
    win_rate_vs_random * 0.2 +      # 20% weight (easy)
    win_rate_vs_greedy * 0.4 +       # 40% weight (medium)
    win_rate_vs_defensive * 0.4      # 40% weight (hard)
)
```

**Why This Weighting?**
- RandomBot: 20% (baseline competence)
- GreedyBot: 40% (primary skill indicator)
- DefensiveBot: 40% (advanced tactical play)

**Best Model Selection:**
```python
if combined_win_rate > best_combined_win_rate:
    best_combined_win_rate = combined_win_rate
    model.save(f"{best_model_save_path}/best_model")
    print(f"💾 New best model saved! (Combined: {combined_win_rate:.1%})")
```

### Implementation

**Training Integration:**
```python
from ai.train import BotEvaluationCallback

bot_eval_callback = BotEvaluationCallback(
    eval_freq=5000,
    n_eval_episodes=20,
    best_model_save_path="./models/best/",
    verbose=1
)

model.learn(
    total_timesteps=total_timesteps,
    callback=[checkpoint_callback, bot_eval_callback]
)
```

**Training Output:**
```
Episode 1000/2000: Avg Reward = 5.2

📊 Bot evaluation at step 5000...
   🤖 Testing vs random... 92.5% (18/20)
   🤖 Testing vs greedy... 65.0% (13/20)
   🤖 Testing vs defensive... 55.0% (11/20)
   📊 Combined Score: 68.5%
   💾 New best model saved! (Combined: 68.5%)

Episode 1500/2000: Avg Reward = 6.8

📊 Bot evaluation at step 10000...
   🤖 Testing vs random... 95.0% (19/20)
   🤖 Testing vs greedy... 75.0% (15/20)
   🤖 Testing vs defensive... 70.0% (14/20)
   📊 Combined Score: 76.5%
   💾 New best model saved! (Combined: 76.5%)
```

### AI_TURN.md Compliance

**Critical:** Bots follow SAME rules as agent through shared W40KEngine.

| Rule | Agent | Bot | Enforcement |
|------|-------|-----|-------------|
| **Sequential Activation** | ✅ One unit/step | ✅ One unit/step | `gym.step()` |
| **Phase Restrictions** | ✅ move→shoot→charge→fight | ✅ move→shoot→charge→fight | Action masking |
| **Eligibility Checks** | ✅ units_moved tracking | ✅ units_moved tracking | Eligibility pools |
| **Range Validation** | ✅ RNG_RNG checks | ✅ RNG_RNG checks | `_is_valid_shooting_target()` |
| **LoS Requirements** | ✅ Line of sight | ✅ Line of sight | `_has_line_of_sight()` |
| **Combat Resolution** | ✅ W40K dice mechanics | ✅ W40K dice mechanics | `_attack_sequence_rng()` |

**Key Insight:** Bots cannot cheat - engine enforces identical rules for both players.

### TensorBoard Metrics

**Available Metrics:**
```
eval_bots/win_rate_vs_random       # Performance vs RandomBot
eval_bots/win_rate_vs_greedy       # Performance vs GreedyBot
eval_bots/win_rate_vs_defensive    # Performance vs DefensiveBot
eval_bots/combined_win_rate        # Weighted combined score
```

**Visualization:**
```bash
tensorboard --logdir ./tensorboard/

# Navigate to "SCALARS" tab
# Filter by "eval_bots" prefix
```

### Performance Impact

**Evaluation Cost:**
- Frequency: Every 5,000 steps
- Episodes: 60 total (20 per bot × 3 bots)
- Time: ~2-3 minutes per evaluation
- Training overhead: ~5-10%

**Optimization for Development:**
```python
# Faster evaluation during development
bot_eval_callback = BotEvaluationCallback(
    eval_freq=10000,       # Less frequent (2x)
    n_eval_episodes=10,    # Fewer episodes per bot
    verbose=0              # Reduce console output
)
```

### See Also

For complete bot behavior specifications, BotControlledEnv implementation, and enhanced bot AI logic, see **AI_TRAINING.md** section "Bot Evaluation System".

---

## 📈 PERFORMANCE ANALYSIS

### Training Speed Benchmarks

| Configuration | Episodes | Time | Speed | Device |
|---------------|----------|------|-------|--------|
| Debug (50 ep) | 50 | ~10s | 311 it/s | CPU ✅ |
| Default (2000 ep) | 2000 | ~7 min | 311 it/s | CPU ✅ |
| Aggressive (4000 ep) | 4000 | ~15 min | 311 it/s | CPU ✅ |

**Why CPU is Faster:**
```
MlpPolicy with small networks (obs_size < 200):
├─ GPU: Context switching overhead > computation benefit
└─ CPU: Direct computation, better cache utilization

Benchmark Results:
├─ GPU (CUDA): 282 it/s
└─ CPU: 311 it/s (10% faster) ✅
```

### Memory Usage

| Component | Memory | Notes |
|-----------|--------|-------|
| Observation Vector | 660 bytes | 165 floats × 4 bytes |
| PPO Buffer (2048 steps) | ~1.3 MB | 2048 × 165 × 4 |
| Policy Network (256×256) | ~12 MB | 65K parameters |
| LoS Cache | ~2 MB | Typical game state |
| **Total per Environment** | **~15 MB** | Very efficient |

### Expected Performance

**Learning Curve:**

| Episodes | Win Rate vs Self-Play | Win Rate vs Bots | Notes |
|----------|----------------------|------------------|-------|
| 50 | N/A | 35-40% | Initial learning |
| 200 | N/A | 50-55% | Basic tactics |
| 500 | N/A | 60-65% | Refined behavior |
| 1000 | N/A | 70-75% | Advanced tactics |
| 2000 | N/A | 80-85% | Near-optimal ✅ |

**Bot-Specific Performance (2000 episodes):**

| Bot | Expected Win Rate | Indicates |
|-----|------------------|-----------|
| **RandomBot** | 92-95% | Basic competence |
| **GreedyBot** | 70-80% | Tactical decision-making |
| **DefensiveBot** | 65-75% | Strategic positioning |
| **Combined Score** | 75-82% | Overall skill level |

**Comparison to Legacy Systems:**

| System | Obs Size | Win Rate (2000 ep) | Learning Speed |
|--------|----------|-------------------|----------------|
| v0.1 (Absolute) | 26 floats | 60-65% | Fast bootstrap |
| v1.0 (Egocentric + composite) | 165 floats | 75-80% | Fast bootstrap |
| **v2.0 (Pure RL)** | **165 floats** | **80-85%** | Slower start, better final ✅ |

---

## 📄 MIGRATION GUIDE

### Version History

```
v0.1 (Legacy):     26 floats, absolute coordinates
v1.0 (Oct 2025):   150 floats, egocentric (never deployed)
v2.0-alpha:        170 floats, with optimal_target_score (deprecated)
v2.0 (Current):    165 floats, pure RL approach ✅
```

### Breaking Changes

**From v2.0-alpha (170 floats) to v2.0 (165 floats):**

1. ✅ Observation size: 170 → 165
2. ✅ Removed feature #8: optimal_target_score
3. ✅ Valid targets: 50 floats (5×10) → 45 floats (5×9)
4. ✅ Feature #9 moved to #8: target_type_match

**Migration Checklist:**

- [ ] Update `training_config.json` obs_size to 165 (all configs)
- [ ] Delete old 170-float models or archive them
- [ ] Retrain all agents with `--new` flag
- [ ] Verify observation shape in test script
- [ ] Update any custom observation processing code
- [ ] **Verify BotEvaluationCallback is in training pipeline**
- [ ] **Check TensorBoard for eval_bots/* metrics**
- [ ] **Confirm best model saving works based on bot performance**

### Retraining Procedure

```bash
# 1. Archive old models
mkdir -p ai/models/archive_170float
mv ai/models/current/*.zip ai/models/archive_170float/

# 2. Verify observation system
python -c "
from engine.w40k_engine import W40KEngine
from config_loader import get_config_loader
from ai.unit_registry import UnitRegistry

config_loader = get_config_loader()
unit_registry = UnitRegistry()

engine = W40KEngine(
    config=None,
    rewards_config='default',
    training_config_name='debug',
    controlled_agent='SpaceMarine_Infantry_Troop_RangedSwarm',
    scenario_file='config/scenarios/scenario_debug.json',
    unit_registry=unit_registry,
    quiet=True
)

obs, info = engine.reset()
assert obs.shape == (165,), f'Shape mismatch: {obs.shape}'
print('✅ Pure RL observation verified!')
"

# 3. Train new models
python ai/train.py \
    --agent SpaceMarine_Infantry_Troop_RangedSwarm \
    --training-config default \
    --rewards-config default \
    --new  # Force new model creation
```

---

## 🛠 TROUBLESHOOTING

### Common Issues

#### Issue 1: Observation Shape Mismatch

**Symptom:**
```
ValueError: Observation shape mismatch!
Expected: (165,), Got: (170,)
```

**Solution:**
```bash
# Check training_config.json
grep "obs_size" config/training_config.json

# Should show: "obs_size": 165
# If shows 170, update all configs
```

#### Issue 2: Model Loading Fails

**Symptom:**
```
RuntimeError: Input shape mismatch when loading model
```

**Solution:**
```python
# Old models are incompatible - must retrain
# DO NOT use --append with old models
python ai/train.py --agent X --training-config Y --new
```

#### Issue 3: Action Masking Errors

**Symptom:**
```
Agent selects invalid actions during shooting phase
```

**Solution:**
```python
# Verify action-observation correspondence
obs = engine._build_observation()
mask = engine.get_action_mask()

for i in range(5):
    obs_valid = obs[120 + i*9 + 0] > 0.5  # Feature #0
    mask_valid = mask[4 + i]
    assert obs_valid == mask_valid, f"Mismatch at action {4+i}"
```

#### Issue 4: Poor Learning Performance

**Symptom:**
```
Win rate stuck at 40-45% after 1000 episodes
```

**Diagnostics:**
```bash
# Check Tensorboard
tensorboard --logdir ./tensorboard/

# Look for:
├─ rollout/ep_rew_mean: Should increase steadily
├─ train/entropy_loss: Should decrease gradually
└─ train/policy_loss: Should stabilize

# If learning flat-lines, check:
├─ Reward scaling (too small or too large)
├─ Learning rate (try 0.0001 or 0.001)
└─ Exploration (increase ent_coef to 0.1)
```

#### Issue 5: Bot Evaluation Not Running

**Symptom:**
```
Training completes but no bot evaluation messages appear
No eval_bots/* metrics in TensorBoard
```

**Solution:**
```python
# Check if evaluation bots are available
from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
print("✅ Evaluation bots imported successfully")

# Verify callback is added
from ai.train import BotEvaluationCallback
bot_callback = BotEvaluationCallback(eval_freq=5000, n_eval_episodes=20)

# Check callback list
callbacks = [checkpoint_callback, bot_callback]
model.learn(total_timesteps=10000, callback=callbacks)
```

**Verify in TensorBoard:**
```bash
tensorboard --logdir ./tensorboard/

# Look for metrics:
├─ eval_bots/win_rate_vs_random
├─ eval_bots/win_rate_vs_greedy
├─ eval_bots/win_rate_vs_defensive
└─ eval_bots/combined_win_rate
```

---

## 🎯 DESIGN PHILOSOPHY

### Pure RL Approach

**Core Principle:** Trust the agent to discover optimal behavior.

**Features Provided:**
- ✅ Fundamental tactical information
- ✅ W40K dice probabilities
- ✅ Strategic context
- ✅ Unit matchup data

**Features EXCLUDED:**
- ❌ Pre-computed composite scores
- ❌ Designer heuristics
- ❌ Reward-based priorities
- ❌ Hardcoded tactical rules

**Why This Works:**

1. **Network Learns Combinations**
   - Hidden layers (256×256) discover optimal feature weighting
   - Agent finds combinations human designers might miss
   - Emergent tactics from fundamental principles

2. **No Designer Bias**
   - Agent not constrained by pre-programmed priorities
   - Discovers tactics through experience
   - Adapts to opponent strategies

3. **Robust Generalization**
   - Learned behaviors transfer across scenarios
   - No brittle heuristics that break in edge cases
   - True understanding vs memorized rules

**Trade-offs Accepted:**

| Aspect | Pure RL | Guided RL |
|--------|---------|-----------|
| Initial Learning | Slower (35-40% @ 50ep) | Faster (45-50% @ 50ep) |
| Final Performance | Better (80-85% @ 2000ep) | Good (75-80% @ 2000ep) |
| Robustness | High (adapts to changes) | Medium (follows guidance) |
| Maintenance | Low (self-correcting) | High (tune heuristics) |

---

## 📚 REFERENCE

### Related Documents

- **AI_TURN.md** - Game state management, sequential activation
- **AI_IMPLEMENTATION.md** - Handler architecture, phase delegation
- **AI_GAME_OVERVIEW.md** - W40K rules, combat mechanics
- **AI_TRAINING.md** - Training pipeline, bot evaluation details

### Key Concepts

**Egocentric Observation:**
> Observations encoded from agent's perspective (relative positions)
> rather than absolute board coordinates.

**Action-Observation Correspondence:**
> Direct mapping between observation features and action effects.
> obs[120+i*9] describes what happens if agent selects action (4+i).

**Pure RL:**
> Agent discovers optimal behavior from fundamental features
> without pre-computed composite scores or designer heuristics.

**R=25 Perception:**
> Observation radius covering tactical decision space
> (MOVE + CHARGE + 1 offset = 25 hexes).

**Bot Evaluation:**
> Periodic testing against tactical opponents (RandomBot, GreedyBot, DefensiveBot)
> to measure progress objectively during training.

---

## 📝 VERSION CONTROL

**Current Version:** 2.0 (December 2025)

**Change Log:**
- v2.0 (Dec 2025): Removed optimal_target_score, pure RL approach, added bot evaluation
- v2.0-alpha (Dec 2025): Added optimal_target_score (deprecated)
- v1.0 (Oct 2025): Egocentric observation 150 floats (never deployed)
- v0.1 (Pre-Oct 2025): Absolute observation 26 floats (legacy)

**Document Status:** ✅ CANONICAL REFERENCE

---