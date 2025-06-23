#!/usr/bin/env python3
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
