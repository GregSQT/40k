#!/usr/bin/env python3
# train_ai.py - Direct training script that runs from root directory

import os
import sys
import subprocess

# Add current directory to path
sys.path.insert(0, os.getcwd())

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from ai.gym40k import W40KEnv

def main():
    print("W40K AI Training - Direct Version")
    print("=" * 40)
    
    # Generate scenario if needed
    if not os.path.exists("ai/scenario.json"):
        print("Generating scenario.json...")
        try:
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
    total_timesteps = 10_000  # Start small for testing
    
    if "--normal" in sys.argv:
        total_timesteps = 100_000
        print("Normal training mode (100k timesteps)")
    elif "--full" in sys.argv:
        total_timesteps = 1_000_000
        print("Full training mode (1M timesteps)")
    else:
        print("Quick training mode (10k timesteps)")
    
    # Create or load model
    model_path = "ai/model.zip"
    
    if os.path.exists(model_path) and "--resume" in sys.argv:
        print("Loading existing model...")
        model = DQN.load(model_path, env=env)
        print("[OK] Model loaded successfully")
    else:
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
    print()
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print("[OK] Training completed successfully!")
    except KeyboardInterrupt:
        print("[STOP] Training interrupted by user")
    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    print("Saving model...")
    os.makedirs("ai", exist_ok=True)
    model.save(model_path)
    print(f"[OK] Model saved to {model_path}")
    
    env.close()
    
    print()
    print("Training session completed!")
    print("Next steps:")
    print("  * Test your model: python test_ai.py")
    print("  * Resume training: python train_ai.py --resume")
    
    return True

if __name__ == "__main__":
    main()
