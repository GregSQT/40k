#!/usr/bin/env python3
"""
Fixed reorganization script for WH40K AI project.
Removes early imports that cause module errors.
"""

import os
import json
import shutil
from datetime import datetime
from pathlib import Path

def reorganize_project():
    """Complete project reorganization."""
    
    print("WH40K AI Project Reorganization")
    print("=" * 50)
    
    # 1. Create config structure and move scenarios/rewards
    print("Step 1: Organizing configuration files...")
    
    os.makedirs("config", exist_ok=True)
    
    # Create scenarios.json from existing files
    scenarios = {}
    
    # Load existing scenario
    if os.path.exists("ai/scenario.json"):
        with open("ai/scenario.json", "r") as f:
            default_units = json.load(f)
        scenarios["default"] = {
            "description": "Default 4-unit scenario with Intercessors and Assault Intercessors",
            "units": default_units
        }
    else:
        # Create default scenario
        default_units = [
            {"id": 1, "unit_type": "Intercessor", "player": 0, "col": 23, "row": 12,
             "cur_hp": 3, "hp_max": 3, "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
             "is_ranged": True, "is_melee": False, "alive": True},
            {"id": 2, "unit_type": "AssaultIntercessor", "player": 0, "col": 1, "row": 12,
             "cur_hp": 4, "hp_max": 4, "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
             "is_ranged": False, "is_melee": True, "alive": True},
            {"id": 3, "unit_type": "Intercessor", "player": 1, "col": 0, "row": 5,
             "cur_hp": 3, "hp_max": 3, "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
             "is_ranged": True, "is_melee": False, "alive": True},
            {"id": 4, "unit_type": "AssaultIntercessor", "player": 1, "col": 22, "row": 3,
             "cur_hp": 4, "hp_max": 4, "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
             "is_ranged": False, "is_melee": True, "alive": True}
        ]
        scenarios["default"] = {
            "description": "Default 4-unit scenario with Intercessors and Assault Intercessors",
            "units": default_units
        }
    
    # Create test scenario (smaller)
    scenarios["test"] = {
        "description": "Small 2-unit scenario for quick testing",
        "units": scenarios["default"]["units"][:2]
    }
    
    # Create large scenario
    large_units = scenarios["default"]["units"].copy()
    large_units.extend([
        {"id": 5, "unit_type": "Intercessor", "player": 0, "col": 20, "row": 15,
         "cur_hp": 3, "hp_max": 3, "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
         "is_ranged": True, "is_melee": False, "alive": True},
        {"id": 6, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 2,
         "cur_hp": 3, "hp_max": 3, "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
         "is_ranged": True, "is_melee": False, "alive": True}
    ])
    scenarios["large"] = {
        "description": "Larger 6-unit scenario for complex training",
        "units": large_units
    }
    
    # Save scenarios
    with open("config/scenarios.json", "w") as f:
        json.dump(scenarios, f, indent=2)
    print("[OK] Created config/scenarios.json")
    
    # Update rewards config if needed
    if os.path.exists("ai/rewards_master.json") and os.path.exists("config/rewards_config.json"):
        with open("ai/rewards_master.json", "r") as f:
            current_rewards = json.load(f)
        
        with open("config/rewards_config.json", "r") as f:
            rewards_config = json.load(f)
        
        rewards_config["current"] = {
            "description": "Currently active reward configuration",
            **current_rewards
        }
        
        with open("config/rewards_config.json", "w") as f:
            json.dump(rewards_config, f, indent=2)
        print("[OK] Updated config/rewards_config.json")
    
    # Create main config.json
    main_config = {
        "project": {
            "name": "WH40K Tactics RL",
            "version": "1.0.0",
            "description": "Warhammer 40k tactical game with AI opponents"
        },
        "paths": {
            "ai_models": "ai/",
            "scenarios": "config/scenarios.json",
            "rewards": "config/rewards_config.json",
            "training": "config/training_config.json",
            "tensorboard": "./tensorboard/"
        },
        "defaults": {
            "scenario": "default",
            "training_config": "default",
            "rewards_config": "original"
        },
        "game": {
            "board_size": [24, 18],
            "max_turns": 50
        }
    }
    
    with open("config/config.json", "w") as f:
        json.dump(main_config, f, indent=2)
    print("[OK] Created config/config.json")
    
    # 2. Move training scripts to ai/
    print("\nStep 2: Moving training scripts to ai/ folder...")
    
    scripts_to_move = [
        "train_ai_config.py",
        "train_ai.py",
        "train_ai_original.py", 
        "train_ai_bypass.py",
        "test_ai.py",
        "quick_start.py",
        "config_loader.py"
    ]
    
    for script in scripts_to_move:
        if os.path.exists(script):
            dest = f"ai/{script}"
            if os.path.exists(dest):
                # Create backup
                backup = f"{dest}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.move(dest, backup)
                print(f"[BACKUP] Backed up existing ai/{script}")
            shutil.move(script, dest)
            print(f"[OK] Moved {script} -> ai/{script}")
    
    # 3. Create main ai/train.py script (without problematic imports at module level)
    print("\nStep 3: Creating main ai/train.py...")
    
    main_train_content = '''#!/usr/bin/env python3
"""
ai/train.py - Main training script for WH40K AI
"""

import os
import sys

def setup_imports():
    """Set up import paths and return required modules."""
    # Add paths for imports
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, script_dir)
    sys.path.insert(0, project_root)

    # Import modules after setting up paths
    from stable_baselines3 import DQN
    from stable_baselines3.common.env_checker import check_env
    from gym40k import W40KEnv
    from config_loader import ConfigLoader
    
    return DQN, check_env, W40KEnv, ConfigLoader

def parse_arguments():
    """Parse command line arguments."""
    scenario = None
    training_config = None
    rewards_config = None
    model_action = "auto"  # auto, new, append
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        
        if arg == "--scenario" and i + 1 < len(sys.argv):
            scenario = sys.argv[i + 1]
            i += 2
        elif arg == "--training-config" and i + 1 < len(sys.argv):
            training_config = sys.argv[i + 1]
            i += 2
        elif arg == "--rewards-config" and i + 1 < len(sys.argv):
            rewards_config = sys.argv[i + 1]
            i += 2
        elif arg == "--new":
            model_action = "new"
            i += 1
        elif arg == "--append":
            model_action = "append"
            i += 1
        elif arg == "--help":
            show_help()
            return None
        else:
            print(f"Unknown argument: {arg}")
            show_help()
            return None
            
    return {
        "scenario": scenario,
        "training_config": training_config,
        "rewards_config": rewards_config,
        "model_action": model_action
    }

def show_help():
    """Show help message."""
    print("WH40K AI Training Script")
    print("=" * 30)
    print()
    print("Usage: python ai/train.py [options]")
    print()
    print("Simple usage (uses config defaults):")
    print("  python ai/train.py              # Train with all config defaults")
    print("  python ai/train.py --new        # Force create new model")
    print("  python ai/train.py --append     # Force continue existing model")
    print()
    print("Advanced options:")
    print("  --scenario NAME         Override scenario (default from config)")
    print("  --training-config NAME  Override training config (default from config)")
    print("  --rewards-config NAME   Override rewards config (default from config)")
    print("  --new                   Create new model (overwrite existing)")
    print("  --append                Continue training existing model")
    print("  --help                  Show this help")

def load_config_defaults(ConfigLoader):
    """Load default configuration values from config.json."""
    try:
        loader = ConfigLoader()
        main_config = loader.load_main_config()
        defaults = main_config.get("defaults", {})
        
        return {
            "scenario": defaults.get("scenario", "default"),
            "training_config": defaults.get("training_config", "default"),
            "rewards_config": defaults.get("rewards_config", "original")
        }
    except Exception as e:
        print(f"Warning: Could not load config defaults: {e}")
        print("Using fallback defaults...")
        return {
            "scenario": "default",
            "training_config": "default", 
            "rewards_config": "original"
        }

def determine_model_action(requested_action, model_path):
    """Determine what to do with the model based on user request and file existence."""
    model_exists = os.path.exists(model_path)
    
    if requested_action == "new":
        if model_exists:
            print("Existing model will be overwritten (--new specified)")
        return "new"
    elif requested_action == "append":
        if not model_exists:
            print("No existing model found, creating new model (--append specified but no model exists)")
            return "new"
        return "append"
    else:  # auto
        if model_exists:
            print("Existing model found, continuing training (use --new to overwrite)")
            return "append"
        else:
            print("No existing model found, creating new model")
            return "new"

def main():
    """Main training function."""
    print("WH40K AI Training")
    print("=" * 30)
    
    # Parse command line arguments
    args = parse_arguments()
    if args is None:
        return False
    
    # Set up imports
    try:
        DQN, check_env, W40KEnv, ConfigLoader = setup_imports()
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure you're running from the project root and have installed dependencies.")
        return False
    
    # Load default configurations
    defaults = load_config_defaults(ConfigLoader)
    
    # Use command line args or defaults
    scenario = args["scenario"] or defaults["scenario"]
    training_config = args["training_config"] or defaults["training_config"]
    rewards_config = args["rewards_config"] or defaults["rewards_config"]
    model_action = args["model_action"]
    
    print(f"Configuration:")
    print(f"  Scenario: {scenario}")
    print(f"  Training: {training_config}")
    print(f"  Rewards: {rewards_config}")
    print()
    
    # Load configurations
    loader = ConfigLoader()
    
    try:
        scenario_config = loader.load_scenario(scenario)
        training_cfg = loader.load_training_config(training_config)
        rewards_cfg = loader.load_rewards_config(rewards_config)
        
        print(f"Loaded configurations:")
        print(f"  Scenario: {scenario_config['description']}")
        print(f"  Training: {training_cfg['description']}")
        print(f"  Rewards: {rewards_cfg['description']}")
        print()
        
    except Exception as e:
        print(f"Configuration error: {e}")
        print("Run 'python ai/train.py --help' to see available options")
        return False
    
    # Apply configurations to files
    print("Applying configurations...")
    loader.apply_scenario_to_file(scenario)
    loader.apply_rewards_to_file(rewards_config)
    
    # Create environment
    print("Creating environment...")
    env = W40KEnv()
    
    try:
        check_env(env)
        print("Environment validation passed")
    except Exception as e:
        print(f"Environment check warning: {e}")
    
    print(f"Environment info:")
    print(f"  Units: {len(env.units)}")
    print(f"  Board size: {env.board_size}")
    print(f"  Observation space: {env.observation_space}")
    print(f"  Action space: {env.action_space}")
    print()
    
    # Extract training parameters
    total_timesteps = training_cfg['total_timesteps']
    model_params = training_cfg['model_params'].copy()
    
    print(f"Training parameters:")
    print(f"  Total timesteps: {total_timesteps:,}")
    print(f"  Learning rate: {model_params['learning_rate']}")
    print(f"  Buffer size: {model_params['buffer_size']:,}")
    print(f"  Learning starts: {model_params['learning_starts']:,}")
    print(f"  Batch size: {model_params['batch_size']}")
    print()
    
    # Determine model action
    model_path = "model.zip"
    action = determine_model_action(model_action, model_path)
    
    # Create or load model
    if action == "new":
        print("Creating new model...")
        if os.path.exists(model_path):
            # Create backup of existing model
            backup_path = f"model_backup_{int(__import__('time').time())}.zip"
            __import__('shutil').copy(model_path, backup_path)
            print(f"Backed up existing model to {backup_path}")
        
        model = DQN(env=env, **model_params)
        print("New model created successfully")
        
    else:  # append
        print("Loading existing model...")
        try:
            model = DQN.load(model_path, env=env)
            print("Existing model loaded successfully")
        except Exception as e:
            print(f"Failed to load existing model: {e}")
            print("Creating new model instead...")
            model = DQN(env=env, **model_params)
    
    print()
    
    # Start training
    print("=" * 50)
    print("STARTING TRAINING")
    print("=" * 50)
    print(f"Training for {total_timesteps:,} timesteps...")
    print("Monitor progress with: tensorboard --logdir ../tensorboard/")
    print("Press Ctrl+C to interrupt training")
    print()
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print()
        print("TRAINING COMPLETED SUCCESSFULLY!")
        
    except KeyboardInterrupt:
        print()
        print("TRAINING INTERRUPTED BY USER")
        print("Model will be saved with current progress...")
        
    except Exception as e:
        print()
        print("TRAINING FAILED")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    print("Saving model...")
    model.save(model_path)
    print(f"Model saved to ai/{model_path}")
    
    # Save episode logs if available
    if hasattr(env, "episode_logs") and env.episode_logs:
        import json
        
        # Find best and worst episodes
        best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
        worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
        
        with open("best_event_log.json", "w") as f:
            json.dump(best_log, f, indent=2)
        with open("worst_event_log.json", "w") as f:
            json.dump(worst_log, f, indent=2)
        
        print(f"Episode logs saved:")
        print(f"  Best reward: {best_reward:.2f}")
        print(f"  Worst reward: {worst_reward:.2f}")
    
    env.close()
    
    print()
    print("TRAINING SESSION COMPLETE!")
    print("Next steps:")
    print("  Test your model:    python ai/test.py")
    print("  Continue training:  python ai/train.py --append")
    print("  View tensorboard:   tensorboard --logdir ../tensorboard/")
    print("  Start fresh:        python ai/train.py --new")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\\nTraining interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
'''
    
    with open("ai/train.py", "w", encoding='utf-8') as f:
        f.write(main_train_content)
    print("[OK] Created ai/train.py")
    
    # 4. Create ai/test.py (also with delayed imports)
    test_content = '''#!/usr/bin/env python3
"""
ai/test.py - Test trained model
"""

import os
import sys

def setup_imports():
    """Set up import paths and return required modules."""
    # Add paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)

    from stable_baselines3 import DQN
    from gym40k import W40KEnv
    
    return DQN, W40KEnv

def test_model(episodes=5):
    """Test the trained model."""
    if not os.path.exists("model.zip"):
        print("No model found. Train first: python train.py")
        return False
    
    print(f"Testing model for {episodes} episodes...")
    
    # Set up imports
    try:
        DQN, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"Import error: {e}")
        return False
    
    env = W40KEnv()
    model = DQN.load("model.zip")
    
    wins = 0
    rewards = []
    
    for ep in range(episodes):
        obs, _ = env.reset()
        total_reward = 0
        done = False
        steps = 0
        
        while not done and steps < 100:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated
        
        winner = info.get("winner", "None")
        if winner == 1:
            wins += 1
            result = "AI WIN"
        else:
            result = "HUMAN WIN"
        
        rewards.append(total_reward)
        print(f"Episode {ep+1}: {result} - {steps} steps - Reward: {total_reward:.2f}")
    
    print(f"Results: {wins}/{episodes} wins ({100*wins/episodes:.1f}%)")
    print(f"Average reward: {sum(rewards)/len(rewards):.2f}")
    
    env.close()
    return True

if __name__ == "__main__":
    episodes = 5
    if "--episodes" in sys.argv:
        idx = sys.argv.index("--episodes")
        if idx + 1 < len(sys.argv):
            episodes = int(sys.argv[idx + 1])
    test_model(episodes)
'''
    
    with open("ai/test.py", "w", encoding='utf-8') as f:
        f.write(test_content)
    print("[OK] Created ai/test.py")
    
    # 5. Create the config_loader.py without imports that can cause issues
    enhanced_loader = '''#!/usr/bin/env python3
"""
Enhanced configuration loader for W40K AI training
"""

import json
import os
import shutil
from datetime import datetime

class ConfigLoader:
    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        self.config_dir = os.path.join(project_root, "config")
        
    def load_main_config(self):
        """Load main configuration file with defaults."""
        config_path = os.path.join(self.config_dir, "config.json")
        if not os.path.exists(config_path):
            self._create_default_main_config()
        
        with open(config_path, "r") as f:
            return json.load(f)
    
    def _create_default_main_config(self):
        """Create default main config.json if it doesn't exist."""
        print("Creating default config.json...")
        
        default_config = {
            "project": {
                "name": "WH40K Tactics RL",
                "version": "1.0.0",
                "description": "Warhammer 40k tactical game with AI opponents"
            },
            "paths": {
                "ai_models": "ai/",
                "scenarios": "config/scenarios.json",
                "rewards": "config/rewards_config.json",
                "training": "config/training_config.json",
                "tensorboard": "./tensorboard/"
            },
            "defaults": {
                "scenario": "default",
                "training_config": "default",
                "rewards_config": "original"
            },
            "game": {
                "board_size": [24, 18],
                "max_turns": 50
            }
        }
        
        os.makedirs(self.config_dir, exist_ok=True)
        config_path = os.path.join(self.config_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(default_config, f, indent=2)
        print(f"Created {config_path}")
        
    def load_scenario(self, scenario_name="default"):
        """Load scenario configuration."""
        config_path = os.path.join(self.config_dir, "scenarios.json")
        if not os.path.exists(config_path):
            self._create_default_scenarios()
            
        with open(config_path, "r") as f:
            scenarios = json.load(f)
        if scenario_name not in scenarios:
            available = list(scenarios.keys())
            raise ValueError(f"Scenario '{scenario_name}' not found. Available: {available}")
        return scenarios[scenario_name]
        
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
    
    def list_scenarios(self):
        """List available scenarios."""
        config_path = os.path.join(self.config_dir, "scenarios.json")
        if not os.path.exists(config_path): 
            return ["default"]
        with open(config_path, "r") as f:
            return list(json.load(f).keys())
    
    def list_training_configs(self):
        """List available training configurations."""
        config_path = os.path.join(self.config_dir, "training_config.json")
        if not os.path.exists(config_path): 
            return ["default"]
        with open(config_path, "r") as f:
            return list(json.load(f).keys())
    
    def list_rewards_configs(self):
        """List available reward configurations."""
        config_path = os.path.join(self.config_dir, "rewards_config.json")
        if not os.path.exists(config_path): 
            return ["original"]
        with open(config_path, "r") as f:
            return list(json.load(f).keys())
    
    def apply_scenario_to_file(self, scenario_name="default"):
        """Apply scenario config to ai/scenario.json"""
        scenario_config = self.load_scenario(scenario_name)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        scenario_file = os.path.join(script_dir, "scenario.json")
        
        if os.path.exists(scenario_file):
            backup = f"{scenario_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(scenario_file, backup)
        
        with open(scenario_file, "w") as f:
            json.dump(scenario_config["units"], f, indent=2)
        print(f"Applied '{scenario_name}' scenario")
    
    def apply_rewards_to_file(self, rewards_config_name="original"):
        """Apply rewards config to ai/rewards_master.json"""
        rewards_config = self.load_rewards_config(rewards_config_name)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        rewards_file = os.path.join(script_dir, "rewards_master.json")
        
        if os.path.exists(rewards_file):
            backup = f"{rewards_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(rewards_file, backup)
        
        with open(rewards_file, "w") as f:
            reward_data = {k: v for k, v in rewards_config.items() if k != "description"}
            json.dump(reward_data, f, indent=2)
        print(f"Applied '{rewards_config_name}' rewards")
    
    def _create_default_scenarios(self):
        """Create default scenarios.json if it doesn't exist."""
        print("Creating default scenarios.json...")
        
        # Try to load existing scenario from ai/scenario.json
        script_dir = os.path.dirname(os.path.abspath(__file__))
        existing_scenario_path = os.path.join(script_dir, "scenario.json")
        
        if os.path.exists(existing_scenario_path):
            with open(existing_scenario_path, "r") as f:
                existing_units = json.load(f)
        else:
            # Create basic default scenario
            existing_units = [
                {
                    "id": 1, "unit_type": "Intercessor", "player": 0,
                    "col": 23, "row": 12, "cur_hp": 3, "hp_max": 3,
                    "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                    "is_ranged": True, "is_melee": False, "alive": True
                },
                {
                    "id": 2, "unit_type": "AssaultIntercessor", "player": 0,
                    "col": 1, "row": 12, "cur_hp": 4, "hp_max": 4,
                    "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
                    "is_ranged": False, "is_melee": True, "alive": True
                },
                {
                    "id": 3, "unit_type": "Intercessor", "player": 1,
                    "col": 0, "row": 5, "cur_hp": 3, "hp_max": 3,
                    "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                    "is_ranged": True, "is_melee": False, "alive": True
                },
                {
                    "id": 4, "unit_type": "AssaultIntercessor", "player": 1,
                    "col": 22, "row": 3, "cur_hp": 4, "hp_max": 4,
                    "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
                    "is_ranged": False, "is_melee": True, "alive": True
                }
            ]
        
        scenarios = {
            "default": {
                "description": "Default 4-unit scenario with 2 Intercessors and 2 Assault Intercessors",
                "units": existing_units
            },
            "test": {
                "description": "Small 2-unit scenario for quick testing",
                "units": existing_units[:2]
            },
            "large": {
                "description": "Larger scenario with more units",
                "units": existing_units + [
                    {
                        "id": 5, "unit_type": "Intercessor", "player": 0,
                        "col": 20, "row": 15, "cur_hp": 3, "hp_max": 3,
                        "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                        "is_ranged": True, "is_melee": False, "alive": True
                    },
                    {
                        "id": 6, "unit_type": "Intercessor", "player": 1,
                        "col": 3, "row": 2, "cur_hp": 3, "hp_max": 3,
                        "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                        "is_ranged": True, "is_melee": False, "alive": True
                    }
                ]
            }
        }
        
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Write scenarios file
        config_path = os.path.join(self.config_dir, "scenarios.json")
        with open(config_path, "w") as f:
            json.dump(scenarios, f, indent=2)
        
        print(f"Created {config_path}")

if __name__ == "__main__":
    loader = ConfigLoader()
    print("Available scenarios:", loader.list_scenarios())
    print("Available training configs:", loader.list_training_configs())
    print("Available reward configs:", loader.list_rewards_configs())
'''
    
    with open("ai/config_loader.py", "w", encoding='utf-8') as f:
        f.write(enhanced_loader)
    print("[OK] Updated ai/config_loader.py")
    
    # 6. Update import paths in moved scripts
    print("\nStep 4: Fixing import paths...")
    
    scripts_to_fix = [
        "ai/train_ai.py",
        "ai/test_ai.py",
        "ai/quick_start.py"
    ]
    
    for script_path in scripts_to_fix:
        if os.path.exists(script_path):
            with open(script_path, "r", encoding='utf-8') as f:
                content = f.read()
            
            # Fix imports
            content = content.replace(
                'from ai.gym40k import W40KEnv',
                'from gym40k import W40KEnv'
            )
            content = content.replace(
                'sys.path.insert(0, os.getcwd())',
                '''script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)'''
            )
            
            with open(script_path, "w", encoding='utf-8') as f:
                f.write(content)
            print(f"[OK] Fixed imports in {script_path}")
    
    # 7. Create ai/README.md
    readme_content = '''# AI Training Scripts

## Main Scripts

- train.py - Main training script (uses config defaults)
- test.py - Main testing script
- config_loader.py - Configuration management

## Usage

```bash
# Simple training with defaults
python ai/train.py

# Force new model
python ai/train.py --new

# Continue existing model
python ai/train.py --append

# Test model
python ai/test.py
```

## Configurations

All configurations are in ../config/:
- scenarios.json - Game scenarios
- training_config.json - Training parameters  
- rewards_config.json - Reward configurations

## Monitoring

```bash
tensorboard --logdir ../tensorboard/
```
'''
    
    with open("ai/README.md", "w", encoding='utf-8') as f:
        f.write(readme_content)
    print("[OK] Created ai/README.md")
    
    print("\n" + "=" * 50)
    print("Project reorganization complete!")
    print("\nNew structure:")
    print("├── config/")
    print("│   ├── config.json           # Main settings with defaults")
    print("│   ├── scenarios.json        # All scenarios")
    print("│   ├── training_config.json  # Training parameters")
    print("│   └── rewards_config.json   # Reward configurations")
    print("├── ai/")
    print("│   ├── train.py              # MAIN TRAINING SCRIPT")
    print("│   ├── test.py               # MAIN TESTING SCRIPT")
    print("│   ├── config_loader.py      # Configuration management")
    print("│   ├── gym40k.py             # RL environment")
    print("│   └── *.py                  # Other scripts")
    
    print("\nSimple commands:")
    print("  python ai/train.py           # Train with config defaults")
    print("  python ai/train.py --new     # Force new model")
    print("  python ai/train.py --append  # Continue existing model")
    print("  python ai/test.py            # Test your model")
    
    print("\nMonitor training:")
    print("  tensorboard --logdir tensorboard/")

if __name__ == "__main__":
    reorganize_project()