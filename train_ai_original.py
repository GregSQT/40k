#!/usr/bin/env python3
# train_ai_original.py - Training script matching your original configuration

import os
import sys
import json
import subprocess

# Add current directory to path
sys.path.insert(0, os.getcwd())

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from ai.gym40k import W40KEnv

######################################################################################
### Training configuration - RESTORED FROM ORIGINAL
total_timesteps_setup = 1_000_000  # Total timesteps for training. Debug: 100_000
exploration_fraction_setup = 0.5   # Fraction of timesteps spent exploring
######################################################################################

def parse_args():
    resume = None
    debug = False
    for arg in sys.argv[1:]:
        if arg.lower() == "--resume":
            resume = True
        elif arg.lower() == "--new":
            resume = False
        elif arg.lower() == "--debug":
            debug = True
    return resume, debug

def main():
    print("🔧 W40K AI Training - Original Configuration")
    print("=" * 50)
    
    resume_flag, debug_mode = parse_args()
    
    # Adjust timesteps for debug mode
    total_timesteps = 100_000 if debug_mode else total_timesteps_setup
    if debug_mode:
        print("🐛 Debug mode: Using 100,000 timesteps")
    else:
        print(f"🎯 Full training: Using {total_timesteps:,} timesteps")
    
    # Generate scenario if needed
    if not os.path.exists("ai/scenario.json"):
        print("🔧 Regenerating scenario.json...")
        try:
            subprocess.run(["python", "generate_scenario.py"], check=True)
            print("✅ Scenario generated")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("⚠️  Using default scenario")
    
    # Create environment
    env = W40KEnv()
    check_env(env)  # Good for debugging!
    
    print(f"Environment info:")
    print(f"  Units: {len(env.units)}")
    print(f"  Board size: {env.board_size}")
    print(f"  Action space: {env.action_space}")
    
    model_path = "ai/model.zip"
    
    if os.path.exists(model_path):
        if resume_flag is None:
            # No explicit flag, default: resume
            print("Model exists. Resuming training from last checkpoint (default).")
            resume = True
        else:
            resume = resume_flag
        if resume:
            print("Resuming from previous model...")
            model = DQN.load(model_path, env=env)
        else:
            print("Starting new model (overwriting previous model)...")
            model = DQN(
                "MlpPolicy",
                env,
                verbose=1,
                buffer_size=10000,  # ORIGINAL VALUE
                learning_rate=1e-3,
                learning_starts=100,  # ORIGINAL VALUE
                batch_size=64,
                train_freq=4,
                target_update_interval=500,  # ORIGINAL VALUE
                exploration_fraction=exploration_fraction_setup,  # ORIGINAL VALUE
                exploration_final_eps=0.05,
                tensorboard_log="./tensorboard/"
            )
    else:
        print("No previous model found. Creating new model...")
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            buffer_size=10000,  # ORIGINAL VALUE
            learning_rate=1e-3,
            learning_starts=100,  # ORIGINAL VALUE  
            batch_size=64,
            train_freq=4,
            target_update_interval=500,  # ORIGINAL VALUE
            exploration_fraction=exploration_fraction_setup,  # ORIGINAL VALUE
            exploration_final_eps=0.05,
            tensorboard_log="./tensorboard/"
        )

    print(f"🚀 Starting training for {total_timesteps:,} timesteps...")
    print("📊 Monitor with: tensorboard --logdir ./tensorboard/")
    print()

    try:
        model.learn(total_timesteps=total_timesteps)
        print("✅ Training completed successfully!")
    except KeyboardInterrupt:
        print("⏹️  Training interrupted by user")
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Save model
    os.makedirs("ai", exist_ok=True)
    model.save(model_path)
    print(f"💾 Model saved to {model_path}")
    
    # Save episode logs if available
    if hasattr(env, "episode_logs") and env.episode_logs:
        # Find best and worst by total reward
        best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
        worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
        
        with open("ai/best_event_log.json", "w") as f:
            json.dump(best_log, f, indent=2)
        with open("ai/worst_event_log.json", "w") as f:
            json.dump(worst_log, f, indent=2)
        
        print(f"📋 Saved best and worst episode logs: rewards {best_reward}, {worst_reward}")
    
    env.close()
    print("🎉 Training session completed!")
    return True

if __name__ == "__main__":
    main()
