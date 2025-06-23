#!/usr/bin/env python3
# train_ai_bypass.py - Training script that bypasses scenario generation

import os
import sys
import json

# Add current directory to path
sys.path.insert(0, os.getcwd())

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from ai.gym40k import W40KEnv

def create_default_scenario():
    """Create a default scenario directly."""
    scenario_data = [
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
    
    os.makedirs("ai", exist_ok=True)
    with open("ai/scenario.json", "w", encoding="utf-8") as f:
        json.dump(scenario_data, f, indent=2)
    print("[OK] Created default scenario.json")

def main():
    print("W40K AI Training - Bypass Version")
    print("=" * 40)
    
    # Create scenario directly
    if not os.path.exists("ai/scenario.json"):
        print("Creating default scenario...")
        create_default_scenario()
    else:
        print("[OK] Scenario file already exists")
    
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
    total_timesteps = 10_000  # Start small
    
    if "--normal" in sys.argv:
        total_timesteps = 100_000
    elif "--full" in sys.argv:
        total_timesteps = 1_000_000
    
    print(f"Training for {total_timesteps:,} timesteps...")
    
    # Create model
    model_path = "ai/model.zip"
    
    if os.path.exists(model_path) and "--resume" in sys.argv:
        print("Loading existing model...")
        model = DQN.load(model_path, env=env)
    else:
        print("Creating new model...")
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
    
    # Train
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
    
    # Save
    model.save(model_path)
    print(f"[OK] Model saved to {model_path}")
    
    env.close()
    print("\nTraining completed! Use 'python test_ai.py' to test the model.")
    return True

if __name__ == "__main__":
    main()
