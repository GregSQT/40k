# ai/train.py
#!/usr/bin/env python3
"""
ai/train.py - Main training script following AI_INSTRUCTIONS.md exactly
"""

import os
import sys
import argparse
import subprocess
import json
import glob
import shutil
from pathlib import Path

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from config_loader import get_config_loader

def setup_imports():
    """Set up import paths and return required modules."""
    try:
        # Import phase-based environment following AI_GAME_OVERVIEW.md
        from ai.gym40k import W40KEnv, register_environment
        return W40KEnv, register_environment
    except ImportError as e:
        print(f"Import error: {e}")
        print("Please ensure gym40k.py exists and is properly configured")
        sys.exit(1)

def create_model(config, training_config_name="default", rewards_config_name="phase_based", new_model=False, append_training=False):
    """Create or load DQN model with configuration following AI_INSTRUCTIONS.md."""
    print(f"🤖 Creating/loading model with training config: {training_config_name}, rewards config: {rewards_config_name}")
    
    # Load training configuration from config files (not script parameters)
    training_config = config.load_training_config(training_config_name)
    model_params = training_config["model_params"]
    
    # Import environment
    W40KEnv, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create environment with specified rewards config
    # ensure scenario.json exists in config/
    from config_loader import get_config_loader
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    env = W40KEnv(rewards_config=rewards_config_name, training_config_name=training_config_name)
    env = Monitor(env)
    
    model_path = config.get_model_path()
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print("🆕 Creating new model...")
        model = DQN(env=env, **model_params)
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = DQN.load(model_path, env=env)
            # Update any model parameters that might have changed
            model.tensorboard_log = model_params.get("tensorboard_log", "./tensorboard/")
            model.verbose = model_params.get("verbose", 1)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = DQN(env=env, **model_params)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = DQN.load(model_path, env=env)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = DQN(env=env, **model_params)
    
    return model, env, training_config

def setup_callbacks(config, model_path, training_config, training_config_name="default"):
    W40KEnv, _ = setup_imports()
    callbacks = []
    
    # Evaluation callback - test model periodically
    eval_env = Monitor(W40KEnv(rewards_config="phase_based", training_config_name=training_config_name))
    eval_freq=training_config['eval_freq']
    total_timesteps = training_config['total_timesteps']
    
    # VALIDATION: Prevent deadlock when eval_freq >= total_timesteps
    if eval_freq >= total_timesteps:
        raise ValueError(f"eval_freq ({eval_freq}) must be less than total_timesteps ({total_timesteps}). "
                        f"This prevents evaluation callback deadlock. "
                        f"Either increase total_timesteps or decrease eval_freq to {total_timesteps // 2}.")
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=os.path.dirname(model_path),
        log_path=os.path.dirname(model_path),
        eval_freq=10000,  # Evaluate every 10k steps
        deterministic=True,
        render=False,
        n_eval_episodes=5
    )
    callbacks.append(eval_callback)
    
    # Checkpoint callback - save model periodically
    checkpoint_callback = CheckpointCallback(
        save_freq=50000,  # Save every 50k steps
        save_path=os.path.dirname(model_path),
        name_prefix="phase_model_checkpoint"
    )
    callbacks.append(checkpoint_callback)
    
    return callbacks

def train_model(model, training_config, callbacks, model_path):
    """Execute the training process."""
    print("🚀 Starting phase-based training following AI_GAME_OVERVIEW.md...")
    print(f"   Total timesteps: {training_config['total_timesteps']:,}")
    print(f"   Model will be saved to: {model_path}")
    
    try:
        # Start training
        model.learn(
            total_timesteps=training_config['total_timesteps'],
            callback=callbacks,
            log_interval=100,
            progress_bar=True
        )
        
        # Save final model
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        model.save(model_path)
        print(f"✅ Training completed! Model saved to: {model_path}")
        
        return True
        
    except KeyboardInterrupt:
        print("\n⏹️ Training interrupted by user")
        # Save current progress
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        model.save(interrupted_path)
        print(f"💾 Progress saved to: {interrupted_path}")
        return False
        
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_trained_model(model, num_episodes=5):
    """Test the trained model."""
    print(f"🧪 Testing trained model for {num_episodes} episodes...")
    
    W40KEnv, _ = setup_imports()
    env = W40KEnv()
    wins = 0
    total_rewards = []
    
    for episode in range(num_episodes):
        obs, info = env.reset()
        episode_reward = 0
        done = False
        step_count = 0
        
        while not done and step_count < 1000:  # Prevent infinite loops
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            done = terminated or truncated
            step_count += 1
        
        total_rewards.append(episode_reward)
        
        if info['winner'] == 1:  # AI won
            wins += 1
            result = "WIN"
        elif info['winner'] == 0:  # AI lost
            result = "LOSS"
        else:
            result = "DRAW"
        
        print(f"   Episode {episode + 1}: {result} - Reward: {episode_reward:.2f}, Steps: {step_count}")
    
    win_rate = wins / num_episodes
    avg_reward = sum(total_rewards) / len(total_rewards)
    
    print(f"\n📊 Test Results:")
    print(f"   Win Rate: {win_rate:.1%} ({wins}/{num_episodes})")
    print(f"   Average Reward: {avg_reward:.2f}")
    print(f"   Reward Range: {min(total_rewards):.2f} to {max(total_rewards):.2f}")
    
    env.close()
    return win_rate, avg_reward

def ensure_scenario():
    """Ensure scenario.json exists."""
    # write into <project_root>/config/scenario.json
    scenario_path = os.path.join(project_root, "config", "scenario.json")
    if not os.path.exists(scenario_path):
        print("⚠️ scenario.json not found - creating default from AI_GAME_OVERVIEW.md specs...")
        # Create scenario following the frontend structure
        default_scenario = [
            {
                "id": 1, "unit_type": "Intercessor", "player": 0,
                "col": 23, "row": 12
            },
            {
                "id": 2, "unit_type": "AssaultIntercessor", "player": 0,
                "col": 1, "row": 12
            },
            {
                "id": 3, "unit_type": "Intercessor", "player": 1,
                "col": 0, "row": 5
            },
            {
                "id": 4, "unit_type": "AssaultIntercessor", "player": 1,
                "col": 22, "row": 3
            }
        ]
        with open(scenario_path, "w") as f:
            json.dump(default_scenario, f, indent=2)
        print("✅ Created default scenario.json")

def main():
    """Main training function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Train W40K AI following AI_GAME_OVERVIEW.md specifications")
    parser.add_argument("--training-config", default="default", 
                       help="Training configuration to use from config/training_config.json")
    parser.add_argument("--rewards-config", default="phase_based",
                       help="Rewards configuration to use from config/rewards_config.json")
    parser.add_argument("--new", action="store_true", 
                       help="Force creation of new model")
    parser.add_argument("--append", action="store_true", 
                       help="Continue training existing model")
    parser.add_argument("--test-only", action="store_true", 
                       help="Only test existing model, don't train")
    parser.add_argument("--test-episodes", type=int, default=10, 
                       help="Number of episodes for testing")
    
    args = parser.parse_args()
    
    print("🎮 W40K AI Training - Following AI_GAME_OVERVIEW.md specifications")
    print("=" * 70)
    print(f"Training config: {args.training_config}")
    print(f"Rewards config: {args.rewards_config}")
    print(f"New model: {args.new}")
    print(f"Append training: {args.append}")
    print(f"Test only: {args.test_only}")
    print()
    
    try:
        # Setup environment and configuration
        config = get_config_loader()
        
        # Ensure scenario exists
        ensure_scenario()
        
        if args.test_only:
            # Load existing model for testing only
            model_path = config.get_model_path()
            # Ensure model directory exists
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            print(f"📁 Model path: {model_path}")
            
            # Determine whether to create new model or load existing
            if not os.path.exists(model_path):
                print(f"❌ Model not found: {model_path}")
                return 1
            
            W40KEnv, _ = setup_imports()
            env = W40KEnv(rewards_config=args.rewards_config)
            model = DQN.load(model_path, env=env)
            test_trained_model(model, args.test_episodes)
            return 0
        
        # Create/load model
        model, env, training_config = create_model(
            config, 
            args.training_config,
            args.rewards_config, 
            args.new, 
            args.append
        )

        # Get model path for callbacks and training
        model_path = config.get_model_path()
        
        # Setup callbacks
        callbacks = setup_callbacks(config, model_path, training_config, args.training_config)
        
        # Train model
        success = train_model(model, training_config, callbacks, model_path)
        
        if success:
            # Test the trained model
            print("\n" + "=" * 70)
            test_trained_model(model, args.test_episodes)
            
            print("\n🎯 Training Complete!")
            print(f"Model saved to: {model_path}")
            print(f"Monitor tensorboard: tensorboard --logdir ./tensorboard/")
            print(f"Test model: python ai/train.py --test-only")
            
            return 0
        else:
            return 1
            
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)