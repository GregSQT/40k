#!/usr/bin/env python3
"""
Create centralized configuration system for W40K AI training
"""

import os
import json

def create_training_config():
    """Create training_config.json with multiple parameter sets."""
    
    training_config = {
        "default": {
            "description": "Optimized parameters for complex reward learning",
            "total_timesteps": 1000000,
            "model_params": {
                "policy": "MlpPolicy",
                "verbose": 1,
                "buffer_size": 100000,
                "learning_rate": 0.0005,
                "learning_starts": 5000,
                "batch_size": 128,
                "train_freq": 1,
                "target_update_interval": 1000,
                "exploration_fraction": 0.3,
                "exploration_final_eps": 0.02,
                "tensorboard_log": "./tensorboard/"
            }
        },
        "original": {
            "description": "Your original parameters from train.py",
            "total_timesteps": 1000000,
            "model_params": {
                "policy": "MlpPolicy", 
                "verbose": 1,
                "buffer_size": 10000,
                "learning_rate": 0.001,
                "learning_starts": 100,
                "batch_size": 64,
                "train_freq": 4,
                "target_update_interval": 500,
                "exploration_fraction": 0.5,
                "exploration_final_eps": 0.05,
                "tensorboard_log": "./tensorboard/"
            }
        },
        "conservative": {
            "description": "Conservative increase from original",
            "total_timesteps": 1000000,
            "model_params": {
                "policy": "MlpPolicy",
                "verbose": 1,
                "buffer_size": 50000,
                "learning_rate": 0.0007,
                "learning_starts": 2000,
                "batch_size": 128,
                "train_freq": 2,
                "target_update_interval": 750,
                "exploration_fraction": 0.4,
                "exploration_final_eps": 0.03,
                "tensorboard_log": "./tensorboard/"
            }
        },
        "aggressive": {
            "description": "Aggressive parameters for faster learning",
            "total_timesteps": 2000000,
            "model_params": {
                "policy": "MlpPolicy",
                "verbose": 1,
                "buffer_size": 200000,
                "learning_rate": 0.0003,
                "learning_starts": 10000,
                "batch_size": 256,
                "train_freq": 1,
                "target_update_interval": 1500,
                "exploration_fraction": 0.2,
                "exploration_final_eps": 0.01,
                "tensorboard_log": "./tensorboard/"
            }
        },
        "debug": {
            "description": "Quick training for testing",
            "total_timesteps": 50000,
            "model_params": {
                "policy": "MlpPolicy",
                "verbose": 1,
                "buffer_size": 25000,
                "learning_rate": 0.001,
                "learning_starts": 1000,
                "batch_size": 64,
                "train_freq": 2,
                "target_update_interval": 500,
                "exploration_fraction": 0.3,
                "exploration_final_eps": 0.05,
                "tensorboard_log": "./tensorboard/"
            }
        }
    }
    
    os.makedirs("config", exist_ok=True)
    
    with open("config/training_config.json", "w", encoding="utf-8") as f:
        json.dump(training_config, f, indent=2)
    
    print("[OK] Created config/training_config.json")
    print("Available configurations:")
    for name, config in training_config.items():
        print(f"  - {name}: {config['description']}")

def create_rewards_config():
    """Create rewards_config.json with your original sophisticated rewards."""
    
    rewards_config = {
        "original": {
            "description": "Your original sophisticated reward system",
            "SpaceMarineRanged": {
                "move_close": 0.2,
                "move_away": 0.4,
                "move_to_safe": 0.6,
                "move_to_rng": 0.8,
                "move_to_charge": 0.2,
                "move_to_rng_charge": 0.3,
                "ranged_attack": 0.2,
                "enemy_killed_r": 0.4,
                "enemy_killed_lowests_hp_r": 0.6,
                "enemy_killed_no_overkill_r": 0.8,
                "charge_success": 0.2,
                "being_charged": -0.4,
                "attack": 0.4,
                "enemy_killed_m": 0.2,
                "enemy_killed_lowests_hp_m": 0.3,
                "enemy_killed_no_overkill_m": 0.4,
                "loose_hp": -0.4,
                "killed_in_melee": -0.8,
                "win": 1,
                "lose": -1,
                "atk_wasted_r": -0.8,
                "atk_wasted_m": -0.8,
                "wait": -0.9
            },
            "SpaceMarineMelee": {
                "move_close": 0.2,
                "move_away": -0.6,
                "move_to_safe": 0.2,
                "move_to_rng": 0.4,
                "move_to_charge": 0.6,
                "move_to_rng_charge": 0.8,
                "ranged_attack": 0.2,
                "enemy_killed_r": 0.4,
                "enemy_killed_lowests_hp_r": 0.6,
                "enemy_killed_no_overkill_r": 0.8,
                "charge_success": 0.8,
                "being_charged": -0.4,
                "attack": 0.4,
                "enemy_killed_m": 0.4,
                "enemy_killed_lowests_hp_m": 0.6,
                "enemy_killed_no_overkill_m": 0.8,
                "loose_hp": -0.4,
                "killed_in_melee": -0.8,
                "win": 1,
                "lose": -1,
                "atk_wasted_r": -0.8,
                "atk_wasted_m": -0.8,
                "wait": -0.9
            }
        },
        "simplified": {
            "description": "Simplified rewards for faster learning",
            "SpaceMarineRanged": {
                "move_close": 0.1,
                "move_away": 0.1,
                "move_to_safe": 0.1,
                "move_to_rng": 0.3,
                "move_to_charge": 0.1,
                "ranged_attack": 0.5,
                "enemy_killed_r": 1.0,
                "attack": 0.3,
                "enemy_killed_m": 0.5,
                "win": 2.0,
                "lose": -2.0,
                "atk_wasted_r": -0.3,
                "atk_wasted_m": -0.3,
                "wait": -0.2
            },
            "SpaceMarineMelee": {
                "move_close": 0.3,
                "move_away": -0.1,
                "move_to_safe": 0.1,
                "move_to_rng": 0.1,
                "move_to_charge": 0.8,
                "ranged_attack": 0.2,
                "enemy_killed_r": 0.5,
                "attack": 0.6,
                "enemy_killed_m": 1.5,
                "charge_success": 1.0,
                "win": 2.0,
                "lose": -2.0,
                "atk_wasted_r": -0.2,
                "atk_wasted_m": -0.4,
                "wait": -0.3
            }
        },
        "balanced": {
            "description": "Balanced rewards with intermediate feedback",
            "SpaceMarineRanged": {
                "move_close": 0.15,
                "move_away": 0.2,
                "move_to_safe": 0.3,
                "move_to_rng": 0.5,
                "move_to_charge": 0.1,
                "ranged_attack": 0.4,
                "enemy_killed_r": 0.8,
                "enemy_killed_lowests_hp_r": 1.0,
                "enemy_killed_no_overkill_r": 1.2,
                "attack": 0.3,
                "enemy_killed_m": 0.4,
                "damage_dealt": 0.1,
                "enemy_in_range": 0.05,
                "win": 3.0,
                "lose": -3.0,
                "atk_wasted_r": -0.5,
                "atk_wasted_m": -0.5,
                "wait": -0.5
            },
            "SpaceMarineMelee": {
                "move_close": 0.25,
                "move_away": -0.3,
                "move_to_safe": 0.1,
                "move_to_rng": 0.2,
                "move_to_charge": 0.7,
                "ranged_attack": 0.2,
                "enemy_killed_r": 0.4,
                "attack": 0.5,
                "enemy_killed_m": 1.0,
                "enemy_killed_lowests_hp_m": 1.2,
                "enemy_killed_no_overkill_m": 1.4,
                "charge_success": 1.2,
                "damage_dealt": 0.1,
                "adjacent_to_enemy": 0.05,
                "win": 3.0,
                "lose": -3.0,
                "atk_wasted_r": -0.3,
                "atk_wasted_m": -0.6,
                "wait": -0.4
            }
        }
    }
    
    with open("config/rewards_config.json", "w", encoding="utf-8") as f:
        json.dump(rewards_config, f, indent=2)
    
    print("[OK] Created config/rewards_config.json")
    print("Available reward sets:")
    for name, config in rewards_config.items():
        print(f"  - {name}: {config['description']}")

def create_config_loader():
    """Create a utility to load configurations."""
    
    loader_code = '''#!/usr/bin/env python3
"""
Configuration loader for W40K AI training
"""

import json
import os

class ConfigLoader:
    def __init__(self):
        self.config_dir = "config"
        
    def load_training_config(self, config_name="default"):
        """Load training configuration."""
        config_path = os.path.join(self.config_dir, "training_config.json")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Training config not found: {config_path}")
            
        with open(config_path, "r") as f:
            configs = json.load(f)
            
        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(f"Config '{config_name}' not found. Available: {available}")
            
        return configs[config_name]
    
    def load_rewards_config(self, config_name="original"):
        """Load rewards configuration."""
        config_path = os.path.join(self.config_dir, "rewards_config.json")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Rewards config not found: {config_path}")
            
        with open(config_path, "r") as f:
            configs = json.load(f)
            
        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(f"Rewards config '{config_name}' not found. Available: {available}")
            
        return configs[config_name]
    
    def list_training_configs(self):
        """List available training configurations."""
        config_path = os.path.join(self.config_dir, "training_config.json")
        with open(config_path, "r") as f:
            configs = json.load(f)
        return list(configs.keys())
    
    def list_rewards_configs(self):
        """List available reward configurations."""
        config_path = os.path.join(self.config_dir, "rewards_config.json")
        with open(config_path, "r") as f:
            configs = json.load(f)
        return list(configs.keys())
    
    def apply_rewards_to_file(self, rewards_config_name="original"):
        """Apply rewards config to ai/rewards_master.json"""
        rewards_config = self.load_rewards_config(rewards_config_name)
        
        # Create backup
        import shutil
        from datetime import datetime
        
        rewards_file = "ai/rewards_master.json"
        if os.path.exists(rewards_file):
            backup_name = f"ai/rewards_master.json.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(rewards_file, backup_name)
            print(f"Backed up current rewards to {backup_name}")
        
        # Write new rewards
        os.makedirs("ai", exist_ok=True)
        with open(rewards_file, "w", encoding="utf-8") as f:
            # Extract just the reward values, not the description
            reward_data = {k: v for k, v in rewards_config.items() if k != "description"}
            json.dump(reward_data, f, indent=2)
        
        print(f"Applied '{rewards_config_name}' rewards to {rewards_file}")

# Example usage
if __name__ == "__main__":
    loader = ConfigLoader()
    
    print("Available training configs:", loader.list_training_configs())
    print("Available reward configs:", loader.list_rewards_configs())
    
    # Example: Load default training config
    training_config = loader.load_training_config("default")
    print("\\nDefault training config:")
    print(f"  Total timesteps: {training_config['total_timesteps']:,}")
    print(f"  Learning rate: {training_config['model_params']['learning_rate']}")
    print(f"  Buffer size: {training_config['model_params']['buffer_size']:,}")
    
    # Example: Apply original rewards
    loader.apply_rewards_to_file("original")
'''
    
    with open("config_loader.py", "w", encoding="utf-8") as f:
        f.write(loader_code)
    
    print("[OK] Created config_loader.py utility")

def create_configurable_training_script():
    """Create a training script that uses the configuration system."""
    
    training_script = '''#!/usr/bin/env python3
# train_ai_config.py - Training script using configuration system

import os
import sys
import subprocess

# Add current directory to path
sys.path.insert(0, os.getcwd())

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from ai.gym40k import W40KEnv
from config_loader import ConfigLoader

def main():
    print("W40K AI Training - Configuration System")
    print("=" * 50)
    
    # Parse arguments
    training_config_name = "default"
    rewards_config_name = "original"
    resume = False
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--training-config" and i + 1 < len(sys.argv):
            training_config_name = sys.argv[i + 1]
            i += 2
        elif arg == "--rewards-config" and i + 1 < len(sys.argv):
            rewards_config_name = sys.argv[i + 1]
            i += 2
        elif arg == "--resume":
            resume = True
            i += 1
        elif arg == "--help":
            print("Usage: python train_ai_config.py [options]")
            print("Options:")
            print("  --training-config NAME  Training configuration to use")
            print("  --rewards-config NAME   Rewards configuration to use") 
            print("  --resume               Resume from existing model")
            print("  --help                 Show this help")
            print()
            
            loader = ConfigLoader()
            print("Available training configs:", loader.list_training_configs())
            print("Available reward configs:", loader.list_rewards_configs())
            return
        else:
            i += 1
    
    # Load configurations
    try:
        loader = ConfigLoader()
        training_config = loader.load_training_config(training_config_name)
        rewards_config = loader.load_rewards_config(rewards_config_name)
        
        print(f"Training config: {training_config_name}")
        print(f"  {training_config['description']}")
        print(f"Rewards config: {rewards_config_name}")
        print(f"  {rewards_config['description']}")
        
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}")
        return False
    
    # Apply rewards configuration
    loader.apply_rewards_to_file(rewards_config_name)
    
    # Generate scenario if needed
    if not os.path.exists("ai/scenario.json"):
        print("Generating scenario...")
        try:
            subprocess.run(["python", "generate_scenario.py"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Using default scenario")
    
    # Create environment
    env = W40KEnv()
    
    try:
        check_env(env)
        print("[OK] Environment validation passed")
    except Exception as e:
        print(f"[WARN] Environment check: {e}")
    
    print(f"Environment: {len(env.units)} units, {env.action_space.n} actions")
    
    # Extract training parameters
    total_timesteps = training_config['total_timesteps']
    model_params = training_config['model_params'].copy()
    
    print(f"Training for {total_timesteps:,} timesteps")
    print(f"Key parameters:")
    print(f"  Learning rate: {model_params['learning_rate']}")
    print(f"  Buffer size: {model_params['buffer_size']:,}")
    print(f"  Learning starts: {model_params['learning_starts']:,}")
    print(f"  Batch size: {model_params['batch_size']}")
    
    # Create or load model
    model_path = "ai/model.zip"
    
    if os.path.exists(model_path) and resume:
        print("Loading existing model...")
        model = DQN.load(model_path, env=env)
    else:
        if resume and not os.path.exists(model_path):
            print("[WARN] No existing model found, creating new one")
        
        print("Creating new model...")
        model = DQN(env=env, **model_params)
    
    print("Starting training...")
    print("Monitor with: tensorboard --logdir ./tensorboard/")
    print()
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print("[OK] Training completed!")
    except KeyboardInterrupt:
        print("[STOP] Training interrupted")
    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    model.save(model_path)
    print(f"Model saved to {model_path}")
    
    # Save episode logs
    if hasattr(env, "episode_logs") and env.episode_logs:
        import json
        
        best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
        worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
        
        with open("ai/best_event_log.json", "w") as f:
            json.dump(best_log, f, indent=2)
        with open("ai/worst_event_log.json", "w") as f:
            json.dump(worst_log, f, indent=2)
        
        print(f"Episode logs saved (best: {best_reward:.2f}, worst: {worst_reward:.2f})")
    
    env.close()
    print("Training completed!")
    return True

if __name__ == "__main__":
    main()
'''
    
    with open("train_ai_config.py", "w", encoding="utf-8") as f:
        f.write(training_script)
    
    print("[OK] Created train_ai_config.py")

def create_usage_examples():
    """Create a usage examples file."""
    
    examples = '''# W40K AI Configuration System - Usage Examples

## Quick Start

### 1. Use default optimized settings:
```bash
python train_ai_config.py
```

### 2. Use your original parameters with original rewards:
```bash
python train_ai_config.py --training-config original --rewards-config original
```

### 3. Try conservative settings with balanced rewards:
```bash
python train_ai_config.py --training-config conservative --rewards-config balanced
```

### 4. Quick debug training:
```bash
python train_ai_config.py --training-config debug --rewards-config simplified
```

### 5. Resume training with different rewards:
```bash
python train_ai_config.py --resume --rewards-config balanced
```

## Configuration Details

### Training Configurations:
- **default**: Optimized parameters for complex reward learning
- **original**: Your original parameters from train.py  
- **conservative**: Moderate increase from original
- **aggressive**: Fast learning with large buffers
- **debug**: Quick training for testing

### Reward Configurations:
- **original**: Your sophisticated tactical reward system
- **simplified**: Simpler rewards for faster learning
- **balanced**: Intermediate complexity with extra feedback

## Customizing Configurations

### Edit training parameters:
```bash
nano config/training_config.json
```

### Edit reward values:
```bash
nano config/rewards_config.json
```

### Apply rewards without training:
```python
from config_loader import ConfigLoader
loader = ConfigLoader()
loader.apply_rewards_to_file("original")
```

## Monitoring Training

```bash
# Start tensorboard
tensorboard --logdir ./tensorboard/

# Test trained model
python test_ai.py
```

## Experimentation Workflow

1. **Start with simplified rewards** for initial learning
2. **Use debug config** for quick testing (50k timesteps)
3. **Switch to balanced rewards** once learning
4. **Use original rewards** for final sophisticated training
5. **Monitor win rates** and adjust accordingly

## Parameter Tuning Tips

- **Higher learning_starts** = more exploration before learning
- **Larger buffer_size** = more diverse experience replay  
- **Smaller learning_rate** = more stable but slower learning
- **Larger batch_size** = more stable gradients
- **Lower exploration_fraction** = less random exploration
'''
    
    with open("CONFIG_USAGE.md", "w", encoding="utf-8") as f:
        f.write(examples)
    
    print("[OK] Created CONFIG_USAGE.md with examples")

def main():
    """Create the complete configuration system."""
    print("Creating W40K AI Configuration System")
    print("=" * 50)
    
    # Create config files
    create_training_config()
    print()
    create_rewards_config()
    print()
    
    # Create utilities
    create_config_loader()
    print()
    create_configurable_training_script()
    print()
    create_usage_examples()
    
    print("\n" + "=" * 50)
    print("Configuration system created!")
    print("\nFiles created:")
    print("  config/training_config.json  - Training parameters")
    print("  config/rewards_config.json   - Reward configurations")
    print("  config_loader.py            - Configuration utilities")
    print("  train_ai_config.py          - Configurable training script")
    print("  CONFIG_USAGE.md            - Usage examples")
    
    print("\nQuick start:")
    print("  python train_ai_config.py --help")
    print("  python train_ai_config.py --training-config debug --rewards-config simplified")

if __name__ == "__main__":
    main()