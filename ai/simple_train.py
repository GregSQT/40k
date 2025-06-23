#!/usr/bin/env python3
# ai/simple_train.py - Simple training script with fixed imports

import os
import sys
import subprocess

# Add the parent directory to the Python path so we can import ai.gym40k
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env

# Now import our gym environment
try:
    from ai.gym40k import W40KEnv
except ImportError:
    # If that fails, try importing directly
    sys.path.insert(0, os.path.dirname(__file__))
    from gym40k import W40KEnv

def main():
    print("Starting W40K AI Training")
    print("=" * 40)
    
    # Generate scenario if needed
    if not os.path.exists("ai/scenario.json"):
        print("Generating scenario.json...")
        try:
            # Try to run from parent directory
            os.chdir(parent_dir)
            subprocess.run([sys.executable, "generate_scenario.py"], check=True)
            print("[OK] Scenario generated successfully")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("[WARN] Scenario generator not found, using default scenario")
    
    # Create environment
    print("Creating environment...")
    env = W40KEnv()
    
    # Check environment
    print("Checking environment...")
    try:
        check_env(env)
        print("[OK] Environment validation passed")
    except Exception as e:
        print(f"[WARN] Environment check warning: {e}")
    
    print(f"Environment info:")
    print(f"  Units: {len(env.units)}")
    print(f"  Observation space: {env.observation_space}")
    print(f"  Action space: {env.action_space}")
    
    # Training configuration
    total_timesteps = 100_000  # Start with smaller number for testing
    
    if "--quick" in sys.argv:
        total_timesteps = 10_000
        print("Quick training mode (10k timesteps)")
    elif "--full" in sys.argv:
        total_timesteps = 1_000_000
        print("Full training mode (1M timesteps)")
    
    # Create or load model
    model_path = os.path.join("ai", "model.zip")
    
    if os.path.exists(model_path) and "--resume" in sys.argv:
        print("Loading existing model...")
        model = DQN.load(model_path, env=env)
        print("[OK] Model loaded successfully")
    else:
        if "--resume" in sys.argv and not os.path.exists(model_path):
            print("[WARN] No existing model found, creating new one")
        
        print("Creating new DQN model...")
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            buffer_size=50_000,
            learning_rate=1e-3,
            learning_starts=1000,
            batch_size=64,
            train_freq=4,
            target_update_interval=1000,
            exploration_fraction=0.3,
            exploration_final_eps=0.05,
            tensorboard_log="./tensorboard/"
        )
        print("[OK] Model created successfully")
    
    print(f"Starting training for {total_timesteps:,} timesteps...")
    print("You can monitor progress with: tensorboard --logdir ./tensorboard/")
    print()
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print("[OK] Training completed successfully!")
    except KeyboardInterrupt:
        print("[STOP] Training interrupted by user")
    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        return False
    
    # Save model
    print("Saving model...")
    os.makedirs("ai", exist_ok=True)
    model.save(model_path)
    print(f"[OK] Model saved to {model_path}")
    
    # Save training logs if available
    if hasattr(env, "episode_logs") and env.episode_logs:
        print("Saving episode logs...")
        import json
        
        # Find best and worst episodes
        best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
        worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
        
        with open("ai/best_episode.json", "w") as f:
            json.dump({"log": best_log, "reward": best_reward}, f, indent=2)
        
        with open("ai/worst_episode.json", "w") as f:
            json.dump({"log": worst_log, "reward": worst_reward}, f, indent=2)
        
        print(f"  Best episode reward: {best_reward:.3f}")
        print(f"  Worst episode reward: {worst_reward:.3f}")
        print("[OK] Episode logs saved")
    
    env.close()
    
    print()
    print("Training session completed!")
    print("Next steps:")
    print("  * Test your model: python ai/test_model.py")
    print("  * Resume training: python ai/simple_train.py --resume")
    print("  * View logs: tensorboard --logdir ./tensorboard/")
    
    return True

if __name__ == "__main__":
    main()
