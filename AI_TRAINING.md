# AI_TRAINING_INTEGRATION.md
## Bridging Compliant Architecture with Deep Reinforcement Learning

### 📋 NAVIGATION MENU

- [Executive Summary](#executive-summary)
- [Training System Overview](#-training-system-overview)
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

This document provides the critical missing link between your AI_TURN.md compliant W40KEngine architecture and your existing DQN training infrastructure. Without proper integration, your architecturally perfect engine cannot leverage years of trained models or continue the learning process.

**Core Challenge:** Maintain exact compatibility with existing training systems while transitioning to compliant architecture.

**Critical Success Factors:**
- Preserve existing model compatibility (observation/action spaces)
- Maintain reward calculation consistency
- Ensure training pipeline continuity
- Support multi-agent orchestration
- Preserve performance characteristics

---

## 🎯 TRAINING SYSTEM OVERVIEW

### Current Training Architecture
```
DQN Model ↔ gym.Env Interface ↔ W40KEnv ↔ SequentialGameController ↔ TrainingGameController
```

**Key Components:**
- **DQN (Deep Q-Network)**: Stable Baselines3 implementation learning optimal actions
- **gym.Env Interface**: Standard reinforcement learning environment protocol
- **W40KEnv**: Your custom environment wrapping the game controller
- **Reward System**: Configuration-driven reward calculation from `rewards_config.json`
- **Model Persistence**: Trained models saved as `.zip` files with embedded parameters

### Training Flow Understanding
```python
# Current training loop
for episode in range(episodes):
    obs = env.reset()  # Get initial game state
    while not done:
        action = model.predict(obs)  # AI chooses action
        obs, reward, done, info = env.step(action)  # Execute action
        # Model learns from: obs -> action -> reward -> new_obs
```

---

## 🔄 ENVIRONMENT INTERFACE REQUIREMENTS

### Gym.Env Interface Compliance

Your W40KEngine must satisfy the exact gym.Env interface that DQN expects:

```python
class W40KEngine:
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

**Critical Requirement:** Your new engine must produce identical observation vectors to existing system.

```python
def _build_observation(self):
    """Convert game_state to observation vector for DQN"""
    # MUST maintain exact same format as current system
    obs_vector = []
    
    # Current player indicator
    obs_vector.append(self.game_state["current_player"])
    
    # Phase encoding (move=0, shoot=1, charge=2, fight=3)
    phase_map = {"move": 0, "shoot": 1, "charge": 2, "fight": 3}
    obs_vector.append(phase_map[self.game_state["phase"]])
    
    # Turn number
    obs_vector.append(self.game_state["turn"])
    
    # Episode steps
    obs_vector.append(self.game_state["episode_steps"])
    
    # Unit states (for each unit position)
    for i in range(max_units):
        if i < len(self.game_state["units"]):
            unit = self.game_state["units"][i]
            obs_vector.extend([
                unit["col"], unit["row"],
                unit["HP_CUR"], unit["HP_MAX"],
                unit["player"],
                1 if unit["id"] in self.game_state["units_moved"] else 0,
                1 if unit["id"] in self.game_state["units_shot"] else 0,
                1 if unit["id"] in self.game_state["units_charged"] else 0,
                1 if unit["id"] in self.game_state["units_attacked"] else 0,
                1 if unit["id"] in self.game_state["units_fled"] else 0
            ])
        else:
            obs_vector.extend([0] * 10)  # Padding for empty unit slots
    
    return np.array(obs_vector, dtype=np.float32)
```

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
# Command: python ai/train.py --orchestrate
# Loads existing model with original parameters

def load_existing_model(self, model_path):
    if os.path.exists(model_path):
        model = DQN.load(model_path, env=self)
        # Uses model's original saved parameters
        return model
    else:
        return self.create_new_model()
```

#### 2. Append Training (Update Parameters)
```python
# Command: python ai/train.py --orchestrate --append
# Loads existing model and updates with current config

def load_model_with_updates(self, model_path, model_params):
    model = DQN.load(model_path, env=self, device=device)
    # Update specific parameters
    model.tensorboard_log = model_params["tensorboard_log"]
    model.verbose = model_params["verbose"]
    return model
```

#### 3. New Model Creation
```python
# Command: python ai/train.py --orchestrate --new
# Creates fresh model from scratch

def create_new_model(self, model_params):
    model = DQN(env=self, **model_params)
    return model
```

### Model Parameter Categories

**Saved with Model (Core Learning Parameters):**
```json
{
  "policy": "MlpPolicy",
  "learning_rate": 0.0003,
  "buffer_size": 200000,
  "batch_size": 512,
  "learning_starts": 5000,
  "train_freq": 1,
  "target_update_interval": 1000,
  "exploration_fraction": 0.3,
  "exploration_final_eps": 0.02
}
```

**Training Session Parameters (Not Saved):**
```json
{
  "total_timesteps": 100000,
  "eval_episodes": 20,
  "max_steps_per_episode": 500,
  "eval_freq": 5000,
  "checkpoint_save_freq": 25000,
  "verbose": 1,
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
    """Create W40KEngine configured for training"""
    
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
    """Main training loop with new engine"""
    
    # Create or load model
    model_path = config.get_model_path()
    
    if os.path.exists(model_path):
        model = DQN.load(model_path, env=engine)
    else:
        model = DQN(env=engine, **model_params)
    
    # Training loop
    model.learn(
        total_timesteps=training_params["total_timesteps"],
        callback=setup_callbacks(training_params),
        tb_log_name="W40K_Training"
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
    """Orchestrate multi-agent training"""
    
    models = {}
    
    for agent_key in agent_keys:
        # Create agent-specific environment
        env = create_multi_agent_environment(config, agent_key)
        
        # Load or create agent model
        model_path = env.model_path
        if os.path.exists(model_path):
            model = DQN.load(model_path, env=env)
        else:
            model = DQN(env=env, **training_params["model_params"])
        
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
    """Setup monitoring and callbacks for training"""
    from stable_baselines3.common.callbacks import CallbackList, CheckpointCallback, EvalCallback
    
    callbacks = []
    
    # Checkpoint saving
    checkpoint_callback = CheckpointCallback(
        save_freq=training_params["checkpoint_save_freq"],
        save_path="./models/checkpoints/",
        name_prefix="w40k_model"
    )
    callbacks.append(checkpoint_callback)
    
    # Evaluation callback
    eval_callback = EvalCallback(
        eval_env=engine,
        n_eval_episodes=training_params["eval_episodes"],
        eval_freq=training_params["eval_freq"],
        best_model_save_path="./models/best/"
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
    "buffer_size": 200000,
    "batch_size": 512,
    "learning_starts": 5000,
    "train_freq": 1,
    "target_update_interval": 1000,
    "exploration_fraction": 0.3,
    "exploration_final_eps": 0.02,
    "verbose": 1,
    "tensorboard_log": "./tensorboard/"
  },
  "training_params": {
    "total_timesteps": 100000,
    "eval_episodes": 20,
    "max_steps_per_episode": 500,
    "max_turns_per_episode": 5,
    "eval_freq": 5000,
    "checkpoint_save_freq": 25000
  },
  "environment_params": {
    "rewards_config": "default",
    "scenario_template": "balanced_fight",
    "enable_replay_logging": false,
    "enable_step_logging": false
  }
}
```

### Configuration Loading

```python
class TrainingConfigManager:
    def __init__(self, config_dir="config"):
        self.config_dir = config_dir
        
    def load_training_config(self, config_name="default"):
        """Load training configuration"""
        config_path = os.path.join(self.config_dir, f"training_config_{config_name}.json")
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def load_rewards_config(self, config_name="default"):
        """Load rewards configuration"""
        config_path = os.path.join(self.config_dir, f"rewards_config_{config_name}.json")
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
    """Test that W40KEngine satisfies gym.Env interface"""
    
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
    """Test all model loading strategies work with new engine"""
    
    engine = W40KEngine(config)
    
    # Test new model creation
    model_params = config.load_training_config()["model_params"]
    new_model = DQN(env=engine, **model_params)
    
    # Test model prediction
    obs, _ = engine.reset()
    action, _ = new_model.predict(obs)
    assert action in range(engine.action_space.n), f"Invalid action: {action}"
    
    # Test model saving and loading
    temp_path = "test_model.zip"
    new_model.save(temp_path)
    
    loaded_model = DQN.load(temp_path, env=engine)
    action2, _ = loaded_model.predict(obs)
    
    # Clean up
    os.remove(temp_path)
    
    print("✅ Model loading strategies verified")
```

---

## 🚀 DEPLOYMENT GUIDE

### Complete Integration Steps

1. **Create Training-Compatible Engine**
```python
# In w40k_engine.py, add training methods
class W40KEngine:
    def __init__(self, config, rewards_config_name="default"):
        # Initialize base engine with AI_TURN.md compliance
        # Add training-specific initialization
        
    def step(self, action):
        # Implement gym-compliant step method
        
    def reset(self, seed=None, options=None):
        # Implement gym-compliant reset method
        
    def _build_observation(self):
        # Convert game_state to observation vector
        
    def _calculate_reward(self, success, result):
        # Calculate reward using rewards_config.json
```

2. **Update Training Scripts**
```python
# In ai/train.py, replace environment creation
# OLD: base_env = W40KEnv(...)
# NEW: base_env = W40KEngine(config, rewards_config_name)
```

3. **Test Integration**
```bash
# Run integration tests
python -c "
from w40k_engine import W40KEngine
from config_loader import get_config_loader
engine = W40KEngine(get_config_loader())
obs, info = engine.reset()
obs, reward, done, truncated, info = engine.step(7)
print('Integration test passed')
"
```

4. **Validate Training Pipeline**
```bash
# Test training with new engine
python ai/train.py --config debug --timesteps 1000 --new
```

### Migration Checklist

- [ ] W40KEngine implements complete gym.Env interface
- [ ] Observation space matches existing models exactly
- [ ] Action space mapping preserved
- [ ] Reward calculation uses rewards_config.json correctly
- [ ] Model loading strategies work with new engine
- [ ] Multi-agent support maintained
- [ ] Training performance acceptable
- [ ] Existing models load and work correctly
- [ ] Configuration management integrated
- [ ] Monitoring and callbacks functional

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

**Issue: Model Loading Failure**
```python
# Symptom: Existing models fail to load
# Fix: Ensure environment interface exactly matches expectations
# Check action_space and observation_space properties
```

**Issue: Training Performance Degradation**
```python
# Symptom: Training runs much slower than before
# Fix: Disable unnecessary logging and optimize observation building
engine.enable_replay_logging = False
engine.enable_step_logging = False
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

# Test training integration
python ai/train.py --config debug --timesteps 100 --new
```

---

## 📝 SUMMARY

This integration guide bridges the gap between your AI_TURN.md compliant architecture and existing training infrastructure. Key integration points:

1. **Environment Interface**: W40KEngine must implement exact gym.Env interface
2. **Observation Compatibility**: Maintain identical observation vectors for model compatibility  
3. **Reward Integration**: Use existing rewards_config.json system
4. **Model Loading**: Support all existing model loading strategies
5. **Training Pipeline**: Maintain training orchestration and multi-agent support
6. **Performance**: Optimize for training speed while preserving functionality

Successful integration ensures your architecturally compliant engine can leverage existing trained models and continue the learning process without losing years of training investment.