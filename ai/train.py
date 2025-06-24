#!/usr/bin/env python3
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
    print("Monitor progress with: tensorboard --logdir ./tensorboard/")
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
    print("  Start fresh:        python ai/train.py --new")
    
    # Ask about TensorBoard
    try:
        response = input("\nDo you want to see the TensorBoard report? (y/N): ").lower().strip()
        if response in ['y', 'yes']:
            print("\n🚀 Starting TensorBoard...")
            print("📊 Open http://localhost:6006 in your browser")
            print("⏹️  Press Ctrl+C to stop TensorBoard when done")
            
            import subprocess
            try:
                # Start TensorBoard
                subprocess.run(["tensorboard", "--logdir", "./tensorboard/"], check=True)
            except subprocess.CalledProcessError:
                print("❌ Failed to start TensorBoard")
                print("💡 Try manually: tensorboard --logdir ./tensorboard/")
            except KeyboardInterrupt:
                print("\n⏹️  TensorBoard stopped")
            except FileNotFoundError:
                print("❌ TensorBoard not found. Install with: pip install tensorboard")
                print("💡 Or run manually: tensorboard --logdir ./tensorboard/")
        else:
            print("\n💡 To view training metrics later, run:")
            print("   tensorboard --logdir ./tensorboard/")
            
    except KeyboardInterrupt:
        print("\n⏹️  Skipped TensorBoard")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nTraining interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)