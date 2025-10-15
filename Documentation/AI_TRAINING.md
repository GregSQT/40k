# AI_TRAINING_INTEGRATION.md
## Bridging Compliant Architecture with PPO Reinforcement Learning

> **📁 File Location**: Save this as `AI_TRAINING.md` in your project root directory
> 
> **Status**: Updated for PPO implementation (replacing DQN)

### 📋 NAVIGATION MENU

- [Executive Summary](#executive-summary)
- [Training System Overview](#-training-system-overview)
- [Why PPO for Tactical Combat](#why-ppo-for-tactical-combat)
- [Environment Interface Requirements](#-environment-interface-requirements)
  - [Gym.Env Interface Compliance](#gymaenv-interface-compliance)
  - [Observation Space Compatibility](#observation-space-compatibility)
  - [Action Space Mapping](#action-space-mapping)
- [Reward System Integration](#-reward-system-integration)
  - [Understanding Reward Configuration](#understanding-reward-configuration)
  - [Reward Configuration Structure](#reward-configuration-structure)
- [Model Integration Strategies](#-model-integration-strategies)
  - [Understanding Model Loading Strategies](#understanding-model-loading-strategies)
  - [Model Parameter Categories](#model-parameter-categories)
- [Training Pipeline Integration](#-training-pipeline-integration)
  - [Environment Creation for Training](#environment-creation-for-training)
  - [Training Loop Integration](#training-loop-integration)
  - [Multi-Agent Support](#multi-agent-support)
- [Performance Considerations](#-performance-considerations)
  - [GPU/CPU Management](#gpucpu-management)
  - [Memory Management](#memory-management)
  - [Training Monitoring](#training-monitoring)
- [Configuration Management](#-configuration-management)
  - [Training Configuration Structure](#training-configuration-structure)
  - [Configuration Loading](#configuration-loading)
- [Testing and Validation](#-testing-and-validation)
  - [Environment Interface Testing](#environment-interface-testing)
  - [Model Loading Testing](#model-loading-testing)
- [Deployment Guide](#-deployment-guide)
  - [Complete Integration Steps](#complete-integration-steps)
  - [Migration Checklist](#migration-checklist)
- [Troubleshooting](#-troubleshooting)
  - [Common Integration Issues](#common-integration-issues)
  - [Validation Commands](#validation-commands)
- [Summary](#-summary)

---

### EXECUTIVE SUMMARY

This document provides the critical missing link between your AI_TURN.md compliant W40KEngine architecture and your PPO training infrastructure. Without proper integration, your architecturally perfect engine cannot leverage trained models or continue the learning process.

**Core Challenge:** Maintain exact compatibility with existing training systems while transitioning to compliant architecture and PPO algorithm.

**Critical Success Factors:**
- Preserve existing model compatibility (observation/action spaces)
- Maintain reward calculation consistency
- Ensure training pipeline continuity with PPO
- Support multi-agent orchestration
- Preserve performance characteristics
- Leverage PPO advantages for tactical decision-making

---

## 🎯 TRAINING SYSTEM OVERVIEW

### Current Training Architecture
```
PPO Model ↔ gym.Env Interface ↔ W40KEngine ↔ SequentialGameController ↔ TrainingGameController
```

**Key Components:**
- **PPO (Proximal Policy Optimization)**: Stable Baselines3 implementation optimized for turn-based tactical games
- **gym.Env Interface**: Standard reinforcement learning environment protocol
- **W40KEngine**: Your custom environment wrapping the game controller
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
```

---

## 🔄 ENVIRONMENT INTERFACE REQUIREMENTS

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
        return gym.spaces.Discrete(8)  # 0-7 actions
```

### Observation Space Compatibility

⚠️ BREAKING CHANGE (October 2025): Observation system upgraded from 26 floats to 150 floats with egocentric encoding.
Model Compatibility:

Old models (26-float system) CANNOT be loaded
All agents must be retrained from scratch
Use --new flag to force new model creation

For complete specification, see AI_OBSERVATION.md


### Action Space Mapping

**Critical Requirement:** Maintain exact action number mappings.

```python
def _process_action(self, action):
    """Map gym action numbers to game actions"""
    # MUST maintain exact same mapping as current system
    action_map = {
        0: "move_north",
        1: "move_south", 
        2: "move_east",
        3: "move_west",
        4: "shoot",
        5: "charge",
        6: "attack",
        7: "wait"
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

**PPO Note:** Unlike DQN's epsilon-greedy exploration, PPO uses stochastic policy sampling. The policy network outputs action probabilities, and PPO samples from this distribution during training.

---

## 💰 REWARD SYSTEM INTEGRATION

### Understanding Reward Configuration

**Critical Insight:** Rewards are loaded fresh from `config/rewards_config.json` every training session, not saved with models.

```python
class W40KEngine:
    def __init__(self, config, rewards_config_name="default"):
        # Load reward configuration
        self.rewards_config = self._load_rewards_config(rewards_config_name)
        # Store for consistent reward calculation
        
    def _calculate_reward(self, success, result):
        """Calculate reward using current rewards configuration"""
        total_reward = 0.0
        
        # Get acting unit for reward calculation
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
                
            if result.get("fled"):
                total_reward += unit_rewards.get("situational_modifiers", {}).get("flee", 0.0)
                
        else:
            # Penalty for invalid actions
            total_reward += unit_rewards.get("base_actions", {}).get("invalid_action", -0.5)
        
        # Game outcome rewards
        if self.game_state["game_over"]:
            if self.game_state["winner"] == acting_unit["player"]:
                total_reward += unit_rewards.get("situational_modifiers", {}).get("win", 0.0)
            else:
                total_reward += unit_rewards.get("situational_modifiers", {}).get("lose", 0.0)
        
        return total_reward
```

### Reward Configuration Structure

```json
{
  "SpaceMarine_Infantry_LeaderElite_MeleeElite": {
    "base_actions": {
      "move_close": 0.3,
      "move_away": -0.1,
      "ranged_attack": 0.8,
      "charge": 0.6,
      "attack": 1.0,
      "wait": -0.1,
      "invalid_action": -0.5
    },
    "situational_modifiers": {
      "kill_enemy": 2.0,
      "damage_enemy": 0.5,
      "flee": -0.3,
      "win": 10.0,
      "lose": -10.0
    }
  }
}
```

---

## 🤖 MODEL INTEGRATION STRATEGIES

### Understanding Model Loading Strategies

Your training system supports three distinct model loading approaches:

#### 1. Default Loading (Continue Training)
```python
# Command: python ai/train.py --training-config default --rewards-config default
# Loads existing model with original parameters

def load_existing_model(self, model_path):
    if os.path.exists(model_path):
        model = PPO.load(model_path, env=self)
        # Uses model's original saved parameters
        return model
    else:
        return self.create_new_model()
```

#### 2. Append Training (Update Parameters)
```python
# Command: python ai/train.py --training-config default --rewards-config default --append
# Loads existing model and updates with current config

def load_model_with_updates(self, model_path, model_params):
    model = PPO.load(model_path, env=self, device=device)
    # Update specific parameters
    model.tensorboard_log = model_params["tensorboard_log"]
    model.verbose = model_params["verbose"]
    return model
```

#### 3. New Model Creation
```python
# Command: python ai/train.py --training-config default --rewards-config default --new
# Creates fresh model from scratch

def create_new_model(self, model_params):
    model = PPO(env=self, **model_params)
    return model
```

### Model Parameter Categories

**Saved with Model (Core Learning Parameters):**
```json
{
  "policy": "MlpPolicy",
  "learning_rate": 0.0003,
  "n_steps": 2048,
  "batch_size": 64,
  "n_epochs": 10,
  "gamma": 0.99,
  "gae_lambda": 0.95,
  "clip_range": 0.2,
  "ent_coef": 0.01,
  "vf_coef": 0.5,
  "max_grad_norm": 0.5,
  "policy_kwargs": {
    "net_arch": [256, 256]
  }
}
```

**Critical PPO Parameters Explained:**
- **n_steps**: Number of steps to collect before policy update (2048 = ~8 episodes)
- **batch_size**: Mini-batch size for gradient updates (must divide n_steps evenly)
- **n_epochs**: How many times to reuse collected data (10 is standard)
- **gamma**: Discount factor (0.99 = plans ~100 steps ahead)
- **gae_lambda**: GAE for advantage estimation (0.95 = smooth credit assignment)
- **clip_range**: PPO policy clipping (0.2 prevents large policy changes)
- **ent_coef**: Entropy bonus for exploration (0.01 = moderate exploration)
- **vf_coef**: Value function loss weight (0.5 balances policy/value learning)
- **max_grad_norm**: Gradient clipping for stability

**Training Session Parameters (Not Saved):**
```json
{
  "total_episodes": 2000,
  "max_turns_per_episode": 5,
  "max_steps_per_turn": 50,
  "checkpoint_save_freq": 50000,
  "eval_deterministic": true,
  "n_eval_episodes": 5,
  "verbose": 0,
  "tensorboard_log": "./tensorboard/",
  "device": "cuda"
}
```

---

## 🔗 TRAINING PIPELINE INTEGRATION

### Environment Creation for Training

```python
def create_training_environment(config, rewards_config_name="default", 
                               training_config_name="default"):
    """Create W40KEngine configured for PPO training"""
    
    # Load training configuration
    training_config = config.load_training_config(training_config_name)
    
    # Create base engine
    engine = W40KEngine(config, rewards_config_name)
    
    # Apply training-specific configurations
    max_turns = training_config.get("max_turns_per_episode", 5)
    engine.game_state["max_turns_override"] = max_turns
    
    # Set episode termination criteria
    engine.max_episode_steps = training_config.get("max_steps_per_episode", 500)
    
    return engine
```

### Training Loop Integration

```python
def train_model(engine, model_params, training_params):
    """Main training loop with PPO and new engine"""
    
    # Create or load model
    model_path = config.get_model_path()
    
    if os.path.exists(model_path):
        model = PPO.load(model_path, env=engine)
    else:
        model = PPO(env=engine, **model_params)
    
    # Training loop - PPO collects n_steps then updates
    model.learn(
        total_timesteps=training_params["total_timesteps"],
        callback=setup_callbacks(training_params),
        tb_log_name="W40K_PPO_Training",
        progress_bar=True
    )
    
    # Save trained model
    model.save(model_path)
    
    return model
```

### Multi-Agent Support

```python
def create_multi_agent_environment(config, agent_key, rewards_config_name="default"):
    """Create environment for specific agent training"""
    
    # Create base engine
    engine = W40KEngine(config, rewards_config_name)
    
    # Configure for specific agent
    engine.controlled_agent = agent_key
    engine.model_path = config.get_model_path().replace('.zip', f'_{agent_key}.zip')
    
    return engine

def train_multiple_agents(config, agent_keys, training_params):
    """Orchestrate multi-agent training with PPO"""
    
    models = {}
    
    for agent_key in agent_keys:
        # Create agent-specific environment
        env = create_multi_agent_environment(config, agent_key)
        
        # Load or create agent model
        model_path = env.model_path
        if os.path.exists(model_path):
            model = PPO.load(model_path, env=env)
        else:
            model = PPO(env=env, **training_params["model_params"])
        
        models[agent_key] = model
    
    # Concurrent training loop
    for agent_key, model in models.items():
        model.learn(total_timesteps=training_params["total_timesteps"])
        model.save(model_path)
```

---

## ⚡ PERFORMANCE CONSIDERATIONS

### GPU/CPU Management

```python
def check_gpu_availability():
    """Check GPU availability for training"""
    import torch
    
    if torch.cuda.is_available():
        gpu_count = torch.cuda.device_count()
        gpu_name = torch.cuda.get_device_name(0)
        print(f"GPU Available: {gpu_name} ({gpu_count} devices)")
        return True
    else:
        print("GPU Not Available: Using CPU")
        return False

def configure_model_device(model_params):
    """Configure model for optimal device usage"""
    if check_gpu_availability():
        model_params["device"] = "cuda"
    else:
        model_params["device"] = "cpu"
    
    return model_params
```

### Memory Management

```python
def optimize_training_memory(engine):
    """Optimize memory usage during training"""
    
    # Disable unnecessary logging during training
    engine.enable_replay_logging = False
    engine.enable_step_logging = False
    
    # Limit observation history
    engine.observation_buffer_size = 1000
    
    # Clear tracking sets periodically
    if engine.game_state["episode_steps"] % 100 == 0:
        engine._cleanup_tracking_sets()
```

### Training Monitoring

```python
def setup_training_callbacks(training_params):
    """Setup monitoring and callbacks for PPO training"""
    from stable_baselines3.common.callbacks import CallbackList, CheckpointCallback, EvalCallback
    
    callbacks = []
    
    # Checkpoint saving
    checkpoint_callback = CheckpointCallback(
        save_freq=training_params["checkpoint_save_freq"],
        save_path="./models/checkpoints/",
        name_prefix="w40k_ppo_model"
    )
    callbacks.append(checkpoint_callback)
    
    # Evaluation callback
    eval_callback = EvalCallback(
        eval_env=engine,
        n_eval_episodes=training_params["eval_episodes"],
        eval_freq=training_params["eval_freq"],
        best_model_save_path="./models/best/",
        deterministic=True  # Use deterministic policy for evaluation
    )
    callbacks.append(eval_callback)
    
    return CallbackList(callbacks)
```

---

## 🔧 CONFIGURATION MANAGEMENT

### Training Configuration Structure

```json
{
  "model_params": {
    "policy": "MlpPolicy",
    "learning_rate": 0.0003,
    "n_steps": 2048,
    "batch_size": 64,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_range": 0.2,
    "clip_range_vf": null,
    "normalize_advantage": true,
    "ent_coef": 0.01,
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "use_sde": false,
    "sde_sample_freq": -1,
    "target_kl": null,
    "tensorboard_log": "./tensorboard/",
    "policy_kwargs": {
      "net_arch": [256, 256]
    },
    "verbose": 0
  },
  "total_episodes": 2000,
  "max_turns_per_episode": 5,
  "max_steps_per_turn": 50,
  "callback_params": {
    "checkpoint_save_freq": 50000,
    "checkpoint_name_prefix": "ppo_checkpoint",
    "eval_deterministic": true,
    "eval_render": false,
    "n_eval_episodes": 5
  },
  "environment_params": {
    "rewards_config": "default",
    "scenario_template": "balanced_fight",
    "enable_replay_logging": false,
    "enable_step_logging": false
  }
}
```

**PPO-Specific Configuration Notes:**

1. **Learning Rate Schedule**: PPO supports linear learning rate decay
   ```json
   "learning_rate": 0.0003  // Can use function for decay
   ```

2. **Batch Size Constraint**: Must divide n_steps evenly
   ```python
   assert n_steps % batch_size == 0  // 2048 % 64 = 0 ✓
   ```

3. **Network Architecture**: Can use deeper networks for complex tactics
   ```json
   "policy_kwargs": {
     "net_arch": [512, 512, 256]  // Aggressive config
   }
   ```

4. **Entropy Coefficient**: Should decrease over time
   ```json
   "ent_coef": 0.01  // Start value
   // Manually decrease to 0.005 after 50K steps
   ```

### Configuration Loading

```python
class TrainingConfigManager:
    def __init__(self, config_dir="config"):
        self.config_dir = config_dir
        
    def load_training_config(self, config_name="default"):
        """Load training configuration"""
        config_path = os.path.join(self.config_dir, f"training_config.json")
        with open(config_path, 'r') as f:
            configs = json.load(f)
            return configs.get(config_name, configs["default"])
    
    def load_rewards_config(self, config_name="default"):
        """Load rewards configuration"""
        config_path = os.path.join(self.config_dir, f"rewards_config.json")
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def get_model_path(self, agent_key=None):
        """Get model save path"""
        if agent_key:
            return f"models/default_model_{agent_key}.zip"
        else:
            return "models/default_model.zip"
```

---

## 🧪 TESTING AND VALIDATION

### Environment Interface Testing

```python
def test_gym_interface_compliance():
    """Test that W40KEngine satisfies gym.Env interface for PPO"""
    
    engine = W40KEngine(config)
    
    # Test reset
    obs, info = engine.reset()
    assert isinstance(obs, np.ndarray), "Observation must be numpy array"
    assert isinstance(info, dict), "Info must be dictionary"
    
    # Test step
    action = engine.action_space.sample()
    obs, reward, terminated, truncated, info = engine.step(action)
    
    assert isinstance(obs, np.ndarray), "Observation must be numpy array"
    assert isinstance(reward, (int, float)), "Reward must be numeric"
    assert isinstance(terminated, bool), "Terminated must be boolean"
    assert isinstance(truncated, bool), "Truncated must be boolean"
    assert isinstance(info, dict), "Info must be dictionary"
    
    print("✅ Gym interface compliance verified")

def test_observation_space_compatibility():
    """Test observation space matches existing models"""
    
    engine = W40KEngine(config)
    obs, _ = engine.reset()
    
    # Check observation shape matches expected format
    expected_shape = (142,)  # Based on current system
    assert obs.shape == expected_shape, f"Observation shape mismatch: {obs.shape} vs {expected_shape}"
    
    # Check observation value ranges
    assert np.all(np.isfinite(obs)), "Observation contains non-finite values"
    
    print("✅ Observation space compatibility verified")

def test_ppo_policy_sampling():
    """Test PPO stochastic policy sampling works correctly"""
    
    engine = W40KEngine(config)
    model_params = config.load_training_config()["model_params"]
    model = PPO(env=engine, **model_params)
    
    obs, _ = engine.reset()
    
    # Test stochastic sampling (training mode)
    action1, _ = model.predict(obs, deterministic=False)
    action2, _ = model.predict(obs, deterministic=False)
    # Actions may differ due to stochastic policy
    
    # Test deterministic sampling (evaluation mode)
    action3, _ = model.predict(obs, deterministic=True)
    action4, _ = model.predict(obs, deterministic=True)
    assert action3 == action4, "Deterministic predictions must be identical"
    
    print("✅ PPO policy sampling verified")

def test_egocentric_observation_space():
    """Test new 150-float egocentric observation system"""
    
    engine = W40KEngine(config)
    obs, _ = engine.reset()
    
    # Check observation shape matches new system
    expected_shape = (150,)  # NEW: 10 + 14×10
    assert obs.shape == expected_shape, f"Observation shape mismatch: {obs.shape} vs {expected_shape}"
    
    # Check observation value ranges (normalized to [-1, 1])
    assert np.all(obs >= -1.0) and np.all(obs <= 1.0), "Observation values outside [-1, 1] range"
    
    # Check observation is not all zeros (unless no units visible)
    assert not np.all(obs == 0), "Observation is all zeros - check observation building"
    
    # Verify egocentric encoding: relative positions should be within radius
    # First 10 floats are self (ignore), then 14 units * 10 floats each
    for i in range(14):
        unit_start = 10 + (i * 10)
        rel_col = obs[unit_start]
        rel_row = obs[unit_start + 1]
        
        # If unit exists (not padding), relative position should be meaningful
        if not (rel_col == 0 and rel_row == 0):
            # Relative positions normalized to [-1, 1] for R=25
            assert -1.0 <= rel_col <= 1.0, f"Unit {i} rel_col out of range: {rel_col}"
            assert -1.0 <= rel_row <= 1.0, f"Unit {i} rel_row out of range: {rel_row}"
    
    print("✅ Egocentric observation space (150 floats, R=25) verified")

def test_reward_calculation_consistency():
    """Test reward calculation produces expected values"""
    
    engine = W40KEngine(config, rewards_config_name="default")
    
    # Test various action outcomes
    test_cases = [
        {"action": 0, "success": True, "type": "move"},
        {"action": 4, "success": True, "type": "shoot", "enemy_killed": True},
        {"action": 7, "success": True, "type": "wait"},
        {"action": 0, "success": False, "type": "invalid_action"}
    ]
    
    for case in test_cases:
        reward = engine._calculate_reward(case["success"], case)
        assert isinstance(reward, (int, float)), f"Reward must be numeric: {reward}"
        print(f"✅ Reward for {case}: {reward}")
```

### Model Loading Testing

```python
def test_model_loading_strategies():
    """Test all model loading strategies work with PPO and new engine"""
    
    engine = W40KEngine(config)
    
    # Test new model creation
    model_params = config.load_training_config()["model_params"]
    new_model = PPO(env=engine, **model_params)
    
    # Test model prediction (stochastic)
    obs, _ = engine.reset()
    action, _ = new_model.predict(obs, deterministic=False)
    assert action in range(engine.action_space.n), f"Invalid action: {action}"
    
    # Test deterministic prediction (evaluation)
    action_det, _ = new_model.predict(obs, deterministic=True)
    assert action_det in range(engine.action_space.n), f"Invalid action: {action_det}"
    
    # Test model saving and loading
    temp_path = "test_model.zip"
    new_model.save(temp_path)
    
    loaded_model = PPO.load(temp_path, env=engine)
    action2, _ = loaded_model.predict(obs, deterministic=True)
    
    # Clean up
    os.remove(temp_path)
    
    print("✅ PPO model loading strategies verified")

def test_ppo_training_step():
    """Test single PPO training step executes correctly"""
    
    engine = W40KEngine(config)
    model_params = config.load_training_config()["model_params"]
    model = PPO(env=engine, **model_params)
    
    # Collect one batch of experiences
    initial_steps = model.num_timesteps
    model.learn(total_timesteps=model_params["n_steps"])
    
    # Verify training occurred
    assert model.num_timesteps > initial_steps, "Training should increment timesteps"
    
    print("✅ PPO training step verified")
```

---

## 🚀 DEPLOYMENT GUIDE

### Complete Integration Steps

1. **Create Training-Compatible Engine**
```python
# In w40k_engine.py, add training methods
class W40KEngine(gym.Env):
    def __init__(self, config, rewards_config_name="default"):
        # Initialize base engine with AI_TURN.md compliance
        # Add training-specific initialization for PPO
        
    def step(self, action):
        # Implement gym-compliant step method
        # Returns: obs, reward, terminated, truncated, info
        
    def reset(self, seed=None, options=None):
        # Implement gym-compliant reset method
        # Returns: obs, info
        
    def _build_observation(self):
        # Convert game_state to observation vector
        # Must match PPO input expectations
        
    def _calculate_reward(self, success, result):
        # Calculate reward using rewards_config.json
        # PPO learns from reward trajectories
```

2. **Update Training Scripts for PPO**
```python
# In ai/train.py, replace DQN with PPO
from stable_baselines3 import PPO

# OLD: model = DQN(env=env, **model_params)
# NEW: model = PPO(env=env, **model_params)

# Update training loop
model.learn(
    total_timesteps=total_timesteps,
    callback=callbacks,
    progress_bar=True  # PPO supports progress bars
)
```

3. **Update Configuration Files**
```bash
# Edit config/training_config.json to use PPO parameters
{
  "model_params": {
    "policy": "MlpPolicy",
    "learning_rate": 0.0003,
    "n_steps": 2048,        # PPO-specific
    "batch_size": 64,       # PPO-specific
    "n_epochs": 10,         # PPO-specific
    "gamma": 0.99,
    "gae_lambda": 0.95,     # PPO-specific
    "clip_range": 0.2,      # PPO-specific
    // Remove DQN-specific params (buffer_size, exploration_*)
  }
}
```

3. **Test Integration**
```bash
# Run integration tests for PPO
python -c "
from w40k_engine import W40KEngine
from config_loader import get_config_loader
from stable_baselines3 import PPO
engine = W40KEngine(get_config_loader())
obs, info = engine.reset()
obs, reward, done, truncated, info = engine.step(7)
model = PPO('MlpPolicy', env=engine, n_steps=512, verbose=0)
print('PPO integration test passed')
"
```

4. **Validate Training Pipeline**
```bash
# Test training with new PPO engine
python ai/train.py --training-config debug --rewards-config default --new --test-episodes 5
```

### Migration Checklist

- [ ] W40KEngine implements complete gym.Env interface
- [x] Observation space UPGRADED to egocentric 150-float system (October 2025)
- [ ] All models retrained with new observation space (old 26-float models incompatible)
- [ ] Action space mapping preserved
- [ ] Reward calculation uses rewards_config.json correctly
- [ ] PPO model loading strategies work with new engine
- [ ] Multi-agent support maintained
- [ ] Training performance acceptable (PPO may be slower than DQN initially)
- [ ] Configuration files updated to PPO parameters
- [ ] Removed DQN-specific parameters (buffer_size, exploration_*)
- [ ] Added PPO-specific parameters (n_steps, gae_lambda, clip_range)
- [ ] Monitoring and callbacks functional
- [ ] Deterministic evaluation mode works correctly

---

## 🔍 TROUBLESHOOTING

### Common Integration Issues

**Issue: Observation Shape Mismatch**
```python
# Symptom: Model fails to load with observation space error
# Fix: Ensure _build_observation() returns exact same shape as before
def _build_observation(self):
    # Count observation elements carefully
    # Must match existing model's expected input shape
```

**Issue: Reward Inconsistency**
```python
# Symptom: Training behavior changes dramatically
# Fix: Verify reward calculation exactly matches previous system
def _calculate_reward(self, success, result):
    # Debug: Print rewards to compare with previous system
    # Ensure reward configuration loading works correctly
```

**Issue: PPO n_steps Configuration Error**
```python
# Symptom: ValueError about n_steps and batch_size
# Fix: Ensure batch_size divides n_steps evenly
# Bad:  n_steps=2048, batch_size=100 (2048 % 100 != 0)
# Good: n_steps=2048, batch_size=64  (2048 % 64 == 0)
```

**Issue: Model Loading Failure**
```python
# Symptom: Existing DQN models fail to load with PPO
# Fix: DQN and PPO models are NOT compatible - must retrain
# DQN uses Q-values, PPO uses policy/value networks
# Solution: Use --new flag to create fresh PPO models
```

**Issue: Training Performance Degradation**
```python
# Symptom: PPO training runs slower than DQN
# Fix: This is expected - PPO is on-policy and more computationally intensive
# Optimization: Adjust n_steps and batch_size for your hardware
# Consider: n_steps=1024, batch_size=32 for faster iterations
engine.enable_replay_logging = False
engine.enable_step_logging = False
```

**Issue: Old Models Fail to Load**
```python
# Symptom: ValueError about observation space shape mismatch
# "Expected observation shape (26,) but got (150,)"
# Fix: Old 26-float models CANNOT be loaded with new 150-float system
# Solution: Retrain all agents from scratch with --new flag
python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm \
                   --training-config default \
                   --rewards-config default \
                   --new  # Force new model creation

# Migration: Archive old models, retrain with new egocentric system
# See AI_OBSERVATION.md for complete specification
```

### Validation Commands

```bash
# Test basic functionality
python -c "from w40k_engine import W40KEngine; print('Import successful')"

# Test gym interface
python -c "
import gym
from w40k_engine import W40KEngine
engine = W40KEngine(config)
assert hasattr(engine, 'step')
assert hasattr(engine, 'reset')
assert hasattr(engine, 'action_space')
assert hasattr(engine, 'observation_space')
print('Gym interface complete')
"

# Test PPO integration
python -c "
from stable_baselines3 import PPO
from w40k_engine import W40KEngine
from config_loader import get_config_loader
engine = W40KEngine(get_config_loader())
model = PPO('MlpPolicy', env=engine, n_steps=512, verbose=0)
obs, _ = engine.reset()
action, _ = model.predict(obs, deterministic=True)
print('PPO integration successful')
"

# Test training integration
python ai/train.py --training-config debug --rewards-config default --new --test-episodes 2
```

---

## 📝 SUMMARY

This integration guide bridges the gap between your AI_TURN.md compliant architecture and PPO training infrastructure. Key integration points:

1. **Algorithm Transition**: Migrated from DQN to PPO for superior tactical decision-making
2. **Environment Interface**: W40KEngine must implement exact gym.Env interface
3. **Observation Compatibility**: Maintain identical observation vectors for model compatibility  
4. **Reward Integration**: Use existing rewards_config.json system
5. **Model Loading**: Support PPO model loading strategies (incompatible with old DQN models)
6. **Training Pipeline**: Maintain training orchestration and multi-agent support
7. **Performance**: PPO is more computationally intensive but provides better tactical learning

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
- Training may be slower but converges to better policies

Successful integration ensures your architecturally compliant engine can leverage PPO's advantages for learning complex tactical behaviors in the Warhammer 40K environment.