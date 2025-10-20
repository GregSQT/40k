# AI_TRAINING_INTEGRATION.md
## Bridging Compliant Architecture with PPO Reinforcement Learning

> **📍 File Location**: Save this as `AI_TRAINING.md` in your project root directory
> 
> **Status**: Updated for PPO implementation with Real Bot Evaluation (November 2025)

### 📋 NAVIGATION MENU

- [Executive Summary](#executive-summary)
- [Training System Overview](#-training-system-overview)
- [Why PPO for Tactical Combat](#why-ppo-for-tactical-combat)
- [Bot Evaluation System](#-bot-evaluation-system)
  - [Evaluation Bot Architecture](#evaluation-bot-architecture)
  - [Bot Behaviors and Difficulty](#bot-behaviors-and-difficulty)
  - [Real Battle Implementation](#real-battle-implementation)
- [Environment Interface Requirements](#-environment-interface-requirements)
  - [Gym.Env Interface Compliance](#gymaenv-interface-compliance)
  - [Observation Space Compatibility](#observation-space-compatibility)
  - [Action Space Mapping](#action-space-mapping)
- [Reward System Integration](#-reward-system-integration)
- [Model Integration Strategies](#-model-integration-strategies)
- [Training Pipeline Integration](#-training-pipeline-integration)
- [Performance Considerations](#-performance-considerations)
- [Configuration Management](#-configuration-management)
- [Testing and Validation](#-testing-and-validation)
- [Deployment Guide](#-deployment-guide)
- [Troubleshooting](#-troubleshooting)
- [Summary](#-summary)

---

### EXECUTIVE SUMMARY

This document provides the critical missing link between your AI_TURN.md compliant W40KEngine architecture and your PPO training infrastructure. Without proper integration, your architecturally perfect engine cannot leverage trained models or continue the learning process.

**Core Challenge:** Maintain exact compatibility with existing training systems while transitioning to compliant architecture and PPO algorithm.

**NEW in November 2025:** Real bot evaluation battles replacing mock results. Agent now tests against RandomBot, GreedyBot, and DefensiveBot with actual gameplay.

**Critical Success Factors:**
- Preserve existing model compatibility (observation/action spaces)
- Maintain reward calculation consistency
- Ensure training pipeline continuity with PPO
- Support multi-agent orchestration
- **Real bot evaluation for progress tracking**
- Preserve performance characteristics
- Leverage PPO advantages for tactical decision-making

---

## 🎯 TRAINING SYSTEM OVERVIEW

### Current Training Architecture
```
PPO Model ↔ gym.Env Interface ↔ W40KEngine ↔ SequentialGameController ↔ TrainingGameController
                                      ↓
                           BotControlledEnv (for evaluation)
                                      ↓
                      RandomBot / GreedyBot / DefensiveBot
```

**Key Components:**
- **PPO (Proximal Policy Optimization)**: Stable Baselines3 implementation optimized for turn-based tactical games
- **gym.Env Interface**: Standard reinforcement learning environment protocol
- **W40KEngine**: Your custom environment wrapping the game controller
- **BotControlledEnv**: Wrapper enabling bot vs agent evaluation battles
- **Evaluation Bots**: RandomBot, GreedyBot, DefensiveBot for measuring progress
- **Reward System**: Configuration-driven reward calculation from `rewards_config.json`
- **Model Persistence**: Trained models saved as `.zip` files with embedded parameters

### Why PPO for Tactical Combat

PPO is superior to DQN for turn-based tactical games like Warhammer 40K:

**PPO Advantages:**
1. **Policy Gradient Method**: Directly optimizes the policy (action selection), better for complex tactical decisions
2. **On-Policy Learning**: Learns from current policy, more stable for sequential turn-based gameplay
3. **Clipped Updates**: Prevents destructive policy changes, crucial for maintaining learned tactics
4. **Better Credit Assignment**: GAE (Generalized Advantage Estimation) handles delayed rewards from multi-turn strategies
5. **Stable Convergence**: Less prone to catastrophic forgetting of successful tactics

**Why Not DQN:**
- Off-policy learning can be unstable with sparse rewards
- Q-value estimation struggles with large action spaces
- Exploration via epsilon-greedy is crude for tactical decisions
- Harder to handle multi-step planning

### Training Flow Understanding
```python
# PPO training loop
for episode in range(episodes):
    obs = env.reset()  # Get initial game state
    while not done:
        action, _ = model.predict(obs)  # AI chooses action via policy
        obs, reward, done, info = env.step(action)  # Execute action
        # PPO learns from: trajectory of (obs, action, reward, value) tuples
        # Updates policy after collecting n_steps experiences
    
    # Every 5000 steps: Bot evaluation
    if step % 5000 == 0:
        test_vs_RandomBot()    # 20 episodes → win rate
        test_vs_GreedyBot()    # 20 episodes → win rate  
        test_vs_DefensiveBot() # 20 episodes → win rate
        # Save best model based on combined performance
```

---

## 🤖 BOT EVALUATION SYSTEM

### Evaluation Bot Architecture

**Purpose:** Measure agent progress against opponents of varying difficulty during training.

**Evaluation Schedule:**
- **Frequency:** Every 5,000 training steps
- **Episodes per bot:** 20 evaluation games
- **Mode:** Deterministic agent actions (no exploration)

**Scoring System:**
```python
combined_win_rate = (
    win_rate_vs_random * 0.2 +      # 20% weight (easy)
    win_rate_vs_greedy * 0.4 +       # 40% weight (medium)
    win_rate_vs_defensive * 0.4      # 40% weight (hard)
)
```

### Bot Behaviors and Difficulty

#### 1. RandomBot ⭐ (Easy - Baseline)

**Strategy:** Pure randomness
```python
def select_action(valid_actions):
    return random.choice(valid_actions)

def select_shooting_target(valid_targets):
    return random.choice(valid_targets)

def select_movement_destination(valid_destinations):
    return random.choice(valid_destinations)
```

**Characteristics:**
- ❌ No strategy
- 🎲 Random actions, targets, movement
- Expected agent win rate: **70-95%**

---

#### 2. GreedyBot ⭐⭐ (Medium - Tactical)

**Strategy:** Aggressive, prioritizes damage
```python
def select_action(valid_actions):
    # Priority: Shoot > Move > Wait
    if 4 in valid_actions:  # Shoot
        return 4
    elif 0 in valid_actions:  # Move
        return 0
    else:
        return valid_actions[0]

def select_shooting_target(valid_targets, game_state):
    """Target lowest HP enemy"""
    min_hp = float('inf')
    best_target = valid_targets[0]
    
    for target_id in valid_targets:
        target = get_unit_by_id(game_state, target_id)
        if target and target['HP_CUR'] < min_hp:
            min_hp = target['HP_CUR']
            best_target = target_id
    
    return best_target

def select_movement_destination(valid_destinations):
    # Move toward enemies (first available)
    return valid_destinations[0]
```

**Characteristics:**
- ✅ Prioritizes shooting
- ✅ Targets weak enemies (low HP)
- ✅ Moves toward combat
- ⚠️ No defensive positioning
- Expected agent win rate: **50-80%**

---

#### 3. DefensiveBot ⭐⭐⭐ (Hard - Survival)

**Strategy:** Conservative, threat-aware
```python
def select_action_with_state(valid_actions, game_state):
    """Threat-aware action selection"""
    active_unit = get_current_unit(game_state)
    nearby_threats = count_nearby_threats(active_unit, game_state)
    
    # If threatened and can shoot, prioritize shooting
    if nearby_threats > 0 and 4 in valid_actions:
        return 4  # Shoot
    
    # If heavily threatened, retreat
    if nearby_threats > 1 and 0 in valid_actions:
        return 0  # Move away
    
    # Otherwise: Shoot > Wait > Move
    if 4 in valid_actions:
        return 4
    elif 7 in valid_actions:
        return 7
    else:
        return valid_actions[0]

def count_nearby_threats(unit, game_state):
    """Count enemies within threat range"""
    threat_count = 0
    threat_range = 12  # Shooting/charge range
    
    for enemy in game_state['units']:
        if enemy['player'] != unit['player'] and enemy['HP_CUR'] > 0:
            distance = abs(enemy['col'] - unit['col']) + abs(enemy['row'] - unit['row'])
            if distance <= threat_range:
                threat_count += 1
    
    return threat_count

def select_movement_destination(valid_destinations):
    # Pick last destination (moves away from threats)
    return valid_destinations[-1]
```

**Characteristics:**
- ✅ Threat awareness (counts nearby enemies)
- ✅ Defensive positioning (retreats when outnumbered)
- ✅ Prioritizes survival over aggression
- ✅ Shoots when safe, retreats when threatened
- Expected agent win rate: **40-70%**

---

### Real Battle Implementation

#### BotControlledEnv Wrapper

**Purpose:** Enable bot to control Player 1 while agent controls Player 0.

**Key Features:**
- Both players follow AI_TURN.md rules through same W40KEngine
- Bot makes tactical decisions based on game_state
- Action masking prevents invalid bot actions
- Proper episode termination and reward tracking

```python
class BotControlledEnv:
    """Wrapper for bot-controlled Player 1 evaluation."""
    
    def __init__(self, base_env, bot, unit_registry):
        self.base_env = base_env
        self.bot = bot
        self.unit_registry = unit_registry
    
    def step(self, agent_action):
        """Execute step with agent or bot depending on current player."""
        current_player = self.base_env.game_state["current_player"]
        
        if current_player == 0:
            # Agent's turn
            obs, reward, terminated, truncated, info = self.base_env.step(agent_action)
            return obs, reward, terminated, truncated, info
        else:
            # Bot's turn - get bot decision
            bot_action = self._get_bot_action()
            obs, reward, terminated, truncated, info = self.base_env.step(bot_action)
            # Don't accumulate bot rewards (only track agent performance)
            return obs, 0.0, terminated, truncated, info
    
    def _get_bot_action(self):
        """Get bot's tactical decision."""
        game_state = self.base_env.game_state
        action_mask = self.base_env.get_action_mask()
        valid_actions = [i for i in range(12) if action_mask[i]]
        
        if not valid_actions:
            return 11  # Wait
        
        # Use enhanced bot logic if available
        if hasattr(self.bot, 'select_action_with_state'):
            bot_choice = self.bot.select_action_with_state(valid_actions, game_state)
        else:
            bot_choice = self.bot.select_action(valid_actions)
        
        # Validate bot choice
        if bot_choice not in valid_actions:
            return valid_actions[0]  # Fallback to first valid action
        
        return bot_choice
```

#### Evaluation Callback

**Purpose:** Run evaluation battles periodically during training.

```python
class BotEvaluationCallback(BaseCallback):
    """Test agent against bots with real battles."""
    
    def __init__(self, eval_freq=5000, n_eval_episodes=20):
        self.eval_freq = eval_freq
        self.n_eval_episodes = n_eval_episodes
        self.best_combined_win_rate = 0.0
        self.bots = {
            'random': RandomBot(),
            'greedy': GreedyBot(),
            'defensive': DefensiveBot()
        }
    
    def _on_step(self):
        """Check if evaluation should run."""
        if self.num_timesteps % self.eval_freq == 0:
            results = self._evaluate_against_bots()
            
            # Log to tensorboard
            for bot_name, win_rate in results.items():
                self.model.logger.record(f'eval_bots/win_rate_vs_{bot_name}', win_rate)
            
            # Calculate combined score
            combined_win_rate = (
                results['random'] * 0.2 +
                results['greedy'] * 0.4 +
                results['defensive'] * 0.4
            )
            
            self.model.logger.record('eval_bots/combined_win_rate', combined_win_rate)
            
            # Save best model
            if combined_win_rate > self.best_combined_win_rate:
                self.best_combined_win_rate = combined_win_rate
                self.model.save(f"{self.best_model_save_path}/best_model")
        
        return True
    
    def _evaluate_against_bots(self):
        """Run actual evaluation episodes against bots."""
        results = {}
        
        for bot_name, bot in self.bots.items():
            wins = 0
            
            for episode in range(self.n_eval_episodes):
                # Create fresh environment with bot
                base_env = create_evaluation_env()
                bot_env = BotControlledEnv(base_env, bot, unit_registry)
                
                # Run episode
                obs, info = bot_env.reset()
                done = False
                step_count = 0
                
                while not done and step_count < 1000:
                    # Agent plays deterministically
                    action, _ = self.model.predict(obs, deterministic=True)
                    obs, reward, terminated, truncated, info = bot_env.step(action)
                    done = terminated or truncated
                    step_count += 1
                
                # Record win
                if info.get('winner') == 0:  # Agent won
                    wins += 1
                
                bot_env.close()
            
            win_rate = wins / self.n_eval_episodes
            results[bot_name] = win_rate
        
        return results
```

#### AI_TURN.md Compliance

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

---

## 📄 ENVIRONMENT INTERFACE REQUIREMENTS

### Gym.Env Interface Compliance

Your W40KEngine must satisfy the exact gym.Env interface that PPO expects:

```python
class W40KEngine(gym.Env):
    """AI_TURN.md compliant engine with gym interface for PPO"""
    
    def step(self, action):
        """Execute one game action and return gym-compliant response"""
        # CRITICAL: Must return exactly 5 values
        return observation, reward, terminated, truncated, info
    
    def reset(self, seed=None, options=None):
        """Reset environment for new episode"""
        # CRITICAL: Must return exactly 2 values
        return observation, info
    
    @property
    def observation_space(self):
        """Define observation vector format"""
        # CRITICAL: Must match existing trained models
        return gym.spaces.Box(low=-np.inf, high=np.inf, shape=(obs_size,))
    
    @property
    def action_space(self):
        """Define action space format"""
        # CRITICAL: Must match existing trained models
        return gym.spaces.Discrete(12)  # 0-11 actions
```

### Observation Space Compatibility

⚠️ BREAKING CHANGE (October 2025): Observation system upgraded from 26 floats to 150 floats with egocentric encoding.

**Model Compatibility:**
- Old models (26-float system) CANNOT be loaded
- All agents must be retrained from scratch
- Use `--new` flag to force new model creation

For complete specification, see `AI_OBSERVATION.md`

### Action Space Mapping

**Critical Requirement:** Maintain exact action number mappings.

```python
def _process_action(self, action):
    """Map gym action numbers to game actions"""
    # MUST maintain exact same mapping as current system
    action_map = {
        0: "move",
        1-3: "move_directions",
        4: "shoot",
        5-8: "shoot_targets",  
        9: "charge",
        10: "attack",
        11: "wait"
    }
    
    current_phase = self.game_state["phase"]
    
    if current_phase == "move":
        return self._process_movement_phase(action)
    elif current_phase == "shoot":
        return self._process_shooting_phase(action)
    elif current_phase == "charge":
        return self._process_charge_phase(action)
    elif current_phase == "fight":
        return self._process_fight_phase(action)
```

---

## 💰 REWARD SYSTEM INTEGRATION

### Understanding Reward Configuration

**Critical Insight:** Rewards are loaded fresh from `config/rewards_config.json` every training session, not saved with models.

```python
class W40KEngine:
    def __init__(self, config, rewards_config_name="default"):
        # Load reward configuration
        self.rewards_config = self._load_rewards_config(rewards_config_name)
        
    def _calculate_reward(self, success, result):
        """Calculate reward using current rewards configuration"""
        total_reward = 0.0
        acting_unit = self._get_current_acting_unit()
        
        if not acting_unit:
            return 0.0
            
        # Get unit-specific reward configuration
        unit_type = acting_unit.get("unitType")
        unit_rewards = self.rewards_config.get(unit_type, {})
        
        if success:
            # Base action rewards
            action_type = result.get("type", "wait")
            base_rewards = unit_rewards.get("base_actions", {})
            total_reward += base_rewards.get(action_type, 0.0)
            
            # Situational modifiers
            if result.get("enemy_killed"):
                total_reward += unit_rewards.get("situational_modifiers", {}).get("kill_enemy", 0.0)
        else:
            # Invalid action penalty
            total_reward += unit_rewards.get("base_actions", {}).get("invalid_action", -0.5)
        
        return total_reward
```

---

## 🤖 MODEL INTEGRATION STRATEGIES

### Understanding Model Loading Strategies

Your training system supports three distinct model loading approaches:

#### 1. Default Loading (Continue Training)
```bash
python ai/train.py --training-config default --rewards-config default
```

#### 2. Append Training (Update Parameters)
```bash
python ai/train.py --training-config default --rewards-config default --append
```

#### 3. New Model Creation
```bash
python ai/train.py --training-config default --rewards-config default --new
```

---

## 🔗 TRAINING PIPELINE INTEGRATION

### Training Loop with Bot Evaluation

```python
def train_model(engine, model_params, training_params):
    """Main training loop with PPO and bot evaluation"""
    
    # Create or load model
    model_path = config.get_model_path()
    
    if os.path.exists(model_path):
        model = PPO.load(model_path, env=engine)
    else:
        model = PPO(env=engine, **model_params)
    
    # Setup callbacks including bot evaluation
    callbacks = []
    
    # Bot evaluation callback
    bot_eval_callback = BotEvaluationCallback(
        eval_freq=5000,
        n_eval_episodes=20,
        best_model_save_path=os.path.dirname(model_path),
        verbose=1
    )
    callbacks.append(bot_eval_callback)
    
    # Training loop with evaluation
    model.learn(
        total_timesteps=training_params["total_timesteps"],
        callback=callbacks,
        tb_log_name="W40K_PPO_Training",
        progress_bar=True
    )
    
    model.save(model_path)
    return model
```

### Training Output with Bot Evaluation

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

---

## ⚡ PERFORMANCE CONSIDERATIONS

### Bot Evaluation Performance Impact

**Evaluation Cost:**
- Frequency: Every 5,000 steps
- Episodes: 60 total (20 per bot × 3 bots)
- Time: ~2-3 minutes per evaluation
- Impact: ~5-10% training time overhead

**Optimization:**
```python
# For faster training during development
bot_eval_callback = BotEvaluationCallback(
    eval_freq=10000,       # Less frequent (2x)
    n_eval_episodes=10,    # Fewer episodes per bot
    verbose=0              # Reduce console output
)
```

---

## 🧪 TESTING AND VALIDATION

### Bot Evaluation Testing

```python
def test_bot_evaluation():
    """Test bot evaluation system works correctly."""
    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
    from ai.train import BotControlledEnv
    
    # Load model
    config = get_config_loader()
    model_path = "ai/models/current/model_SpaceMarine_Infantry_Troop_RangedSwarm.zip"
    
    # Create test environment
    base_env = W40KEngine(config, rewards_config_name="default")
    
    # Test each bot
    bots = {
        'RandomBot': RandomBot(),
        'GreedyBot': GreedyBot(),
        'DefensiveBot': DefensiveBot()
    }
    
    model = PPO.load(model_path)
    
    for bot_name, bot in bots.items():
        bot_env = BotControlledEnv(base_env, bot, unit_registry)
        
        wins = 0
        episodes = 5
        
        for ep in range(episodes):
            obs, info = bot_env.reset()
            done = False
            step_count = 0
            
            while not done and step_count < 500:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = bot_env.step(action)
                done = terminated or truncated
                step_count += 1
            
            if info.get('winner') == 0:
                wins += 1
        
        win_rate = wins / episodes
        print(f"{bot_name}: {win_rate:.1%} ({wins}/{episodes})")
        
        bot_env.close()
```

---

## 🚀 DEPLOYMENT GUIDE

### Complete Integration Checklist

- [ ] W40KEngine implements complete gym.Env interface
- [x] Observation space UPGRADED to egocentric 150-float system (October 2025)
- [ ] All models retrained with new observation space
- [ ] Action space mapping preserved
- [ ] Reward calculation uses rewards_config.json correctly
- [ ] **BotControlledEnv wrapper implemented**
- [ ] **Evaluation bots (RandomBot, GreedyBot, DefensiveBot) created**
- [ ] **BotEvaluationCallback added to training pipeline**
- [ ] **Bot behaviors enhanced (smart targeting, threat awareness)**
- [ ] PPO model loading strategies work
- [ ] Multi-agent support maintained
- [ ] Training performance acceptable
- [ ] Configuration files updated to PPO parameters
- [ ] Monitoring and callbacks functional
- [ ] **TensorBoard metrics tracking bot win rates**

---

## 🔧 TROUBLESHOOTING

### Bot Evaluation Issues

**Issue: Bot evaluation shows mock results**
```python
# Symptom: Win rates are random.uniform() values
# Fix: Ensure _evaluate_against_bots() is updated with real implementation
# Check: BotControlledEnv class exists and is imported correctly
```

**Issue: Bot makes invalid actions**
```python
# Symptom: Bot action fails validation, game crashes
# Fix: Ensure action masking is enforced
def _get_bot_action(self):
    valid_actions = [i for i in range(12) if action_mask[i]]
    bot_choice = self.bot.select_action(valid_actions)
    
    # Validate before returning
    if bot_choice not in valid_actions:
        return valid_actions[0]  # Safe fallback
    
    return bot_choice
```

**Issue: Bot doesn't follow AI_TURN.md rules**
```python
# Symptom: Bot can shoot adjacent enemies, move twice, etc.
# Fix: Bot uses SAME W40KEngine as agent - rules enforced automatically
# Both players go through: env.step() → controller → handlers
# Action masking prevents invalid actions for both agent and bot
```

---

## 📝 SUMMARY

This integration guide bridges the gap between your AI_TURN.md compliant architecture and PPO training infrastructure with real bot evaluation.

**Key Integration Points:**

1. **Algorithm Transition**: Migrated from DQN to PPO for superior tactical decision-making
2. **Environment Interface**: W40KEngine implements exact gym.Env interface
3. **Bot Evaluation System**: Real battles against RandomBot, GreedyBot, DefensiveBot
4. **BotControlledEnv**: Enables bot vs agent gameplay with rule compliance
5. **Observation Compatibility**: 150-float egocentric observation system
6. **Reward Integration**: Uses existing rewards_config.json system
7. **Model Loading**: Supports PPO model loading strategies
8. **Training Pipeline**: Maintains orchestration with bot evaluation callbacks
9. **Performance Tracking**: TensorBoard metrics for bot win rates and combined scores

**Bot Evaluation Benefits:**
- ✅ Objective progress measurement (not self-play only)
- ✅ Multi-difficulty evaluation (easy, medium, hard)
- ✅ Automatic best model selection based on bot performance
- ✅ TensorBoard visualization of tactical improvement
- ✅ Both players follow AI_TURN.md rules (fair evaluation)

**Key Advantages of PPO:**
- Better credit assignment for multi-turn strategies (GAE)
- More stable learning with policy clipping
- Direct policy optimization (no Q-value approximation)
- Natural exploration via stochastic policy
- Superior for complex tactical environments

**Migration Notes:**
- Existing DQN models cannot be loaded by PPO
- Must retrain all agents from scratch with PPO
- Configuration files need PPO-specific parameters
- Bot evaluation adds ~5-10% training time overhead
- Real battles provide better progress tracking than self-play alone

Successful integration ensures your architecturally compliant engine can leverage PPO's advantages while measuring progress against tactical bot opponents.