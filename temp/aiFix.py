#!/usr/bin/env python3
"""
Fix the import issues for the W40K AI training system
"""

import os
import sys

def fix_training_script():
    """Fix the training script to handle imports correctly."""
    
    training_script = '''#!/usr/bin/env python3
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
'''
    
    with open("ai/simple_train.py", "w", encoding='utf-8') as f:
        f.write(training_script)
    print("[OK] Fixed training script")

def fix_test_script():
    """Fix the test script imports."""
    
    test_script = '''#!/usr/bin/env python3
# ai/test_model.py - Test the trained model with fixed imports

import os
import sys

# Add the parent directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from stable_baselines3 import DQN

# Import gym environment with fallback
try:
    from ai.gym40k import W40KEnv
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from gym40k import W40KEnv

def test_model(episodes=5):
    """Test the trained model for several episodes."""
    
    model_path = os.path.join("ai", "model.zip")
    if not os.path.exists(model_path):
        print("[ERROR] No trained model found. Run training first.")
        return False
    
    print("Testing trained model...")
    
    # Load environment and model
    env = W40KEnv()
    model = DQN.load(model_path)
    
    wins = 0
    total_rewards = []
    
    for episode in range(episodes):
        print(f"\\nEpisode {episode + 1}/{episodes}")
        
        obs, info = env.reset()
        total_reward = 0
        step_count = 0
        done = False
        
        while not done:
            # Predict action
            action, _states = model.predict(obs, deterministic=True)
            
            # Execute action
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            step_count += 1
            done = terminated or truncated
            
            # Show progress every 10 steps
            if step_count % 10 == 0:
                print(f"  Step {step_count}: Action={action}, Reward={reward:.3f}")
            
            if step_count > 100:  # Prevent infinite loops
                print("  Episode truncated (too long)")
                break
        
        # Episode summary
        winner = info.get("winner", "None")
        if winner == 1:  # AI wins
            wins += 1
            result = "AI WIN"
        elif winner == 0:
            result = "AI LOSE"
        else:
            result = "DRAW"
        
        total_rewards.append(total_reward)
        print(f"  {result} - Steps: {step_count}, Total Reward: {total_reward:.3f}")
    
    # Final statistics
    print("\\nTest Results:")
    print(f"  Episodes: {episodes}")
    print(f"  AI Wins: {wins}/{episodes} ({100*wins/episodes:.1f}%)")
    print(f"  Average Reward: {sum(total_rewards)/len(total_rewards):.3f}")
    print(f"  Best Reward: {max(total_rewards):.3f}")
    print(f"  Worst Reward: {min(total_rewards):.3f}")
    
    env.close()
    return True

if __name__ == "__main__":
    import sys
    episodes = 5
    
    if "--episodes" in sys.argv:
        idx = sys.argv.index("--episodes")
        if idx + 1 < len(sys.argv):
            episodes = int(sys.argv[idx + 1])
    
    test_model(episodes)
'''
    
    with open("ai/test_model.py", "w", encoding='utf-8') as f:
        f.write(test_script)
    print("[OK] Fixed test script")

def create_init_file():
    """Create __init__.py files to make ai a proper Python package."""
    
    init_content = '''# ai/__init__.py
"""
W40K AI Training Package
"""

from .gym40k import W40KEnv

__all__ = ['W40KEnv']
'''
    
    with open("ai/__init__.py", "w", encoding='utf-8') as f:
        f.write(init_content)
    print("[OK] Created ai/__init__.py")

def fix_quick_start():
    """Fix the quick start script."""
    
    quick_start = '''#!/usr/bin/env python3
# quick_start.py - One-click training starter with fixed paths

import os
import subprocess
import sys

def main():
    print("W40K AI Training - Quick Start")
    print("=" * 40)
    
    # Ensure we're in the right directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Check if we have a model
    if os.path.exists("ai/model.zip"):
        print("Found existing model!")
        choice = input("What do you want to do?\\n1. Test existing model\\n2. Resume training\\n3. Start new training\\nChoice (1-3): ")
        
        if choice == "1":
            print("\\nTesting model...")
            subprocess.run([sys.executable, os.path.join("ai", "test_model.py")])
        elif choice == "2":
            print("\\nResuming training...")
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py"), "--resume"])
        elif choice == "3":
            print("\\nStarting new training...")
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py")])
        else:
            print("Invalid choice")
    else:
        print("No model found. Starting training...")
        mode = input("Training mode?\\n1. Quick (10k steps)\\n2. Normal (100k steps)\\n3. Full (1M steps)\\nChoice (1-3): ")
        
        if mode == "1":
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py"), "--quick"])
        elif mode == "2":
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py")])
        elif mode == "3":
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py"), "--full"])
        else:
            print("Invalid choice, using normal mode")
            subprocess.run([sys.executable, os.path.join("ai", "simple_train.py")])

if __name__ == "__main__":
    main()
'''
    
    with open("quick_start.py", "w", encoding='utf-8') as f:
        f.write(quick_start)
    print("[OK] Fixed quick start script")

def create_direct_train_script():
    """Create a training script that can be run from the root directory."""
    
    direct_train = '''#!/usr/bin/env python3
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
'''
    
    with open("train_ai.py", "w", encoding='utf-8') as f:
        f.write(direct_train)
    print("[OK] Created direct training script")

def create_direct_test_script():
    """Create a test script that runs from root directory."""
    
    direct_test = '''#!/usr/bin/env python3
# test_ai.py - Direct test script

import os
import sys

# Add current directory to path
sys.path.insert(0, os.getcwd())

from stable_baselines3 import DQN
from ai.gym40k import W40KEnv

def test_model(episodes=3):
    """Test the trained model."""
    
    if not os.path.exists("ai/model.zip"):
        print("[ERROR] No trained model found. Run training first.")
        return False
    
    print("Testing trained model...")
    
    # Load environment and model
    env = W40KEnv()
    model = DQN.load("ai/model.zip")
    
    wins = 0
    total_rewards = []
    
    for episode in range(episodes):
        print(f"\\nEpisode {episode + 1}/{episodes}")
        
        obs, info = env.reset()
        total_reward = 0
        step_count = 0
        done = False
        
        while not done:
            action, _states = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            step_count += 1
            done = terminated or truncated
            
            if step_count % 10 == 0:
                print(f"  Step {step_count}: Action={action}, Reward={reward:.3f}")
            
            if step_count > 100:
                print("  Episode truncated (too long)")
                break
        
        winner = info.get("winner", "None")
        if winner == 1:
            wins += 1
            result = "AI WIN"
        elif winner == 0:
            result = "AI LOSE"
        else:
            result = "DRAW"
        
        total_rewards.append(total_reward)
        print(f"  {result} - Steps: {step_count}, Total Reward: {total_reward:.3f}")
    
    print("\\nTest Results:")
    print(f"  Episodes: {episodes}")
    print(f"  AI Wins: {wins}/{episodes} ({100*wins/episodes:.1f}%)")
    if total_rewards:
        print(f"  Average Reward: {sum(total_rewards)/len(total_rewards):.3f}")
    
    env.close()
    return True

if __name__ == "__main__":
    test_model()
'''
    
    with open("test_ai.py", "w", encoding='utf-8') as f:
        f.write(direct_test)
    print("[OK] Created direct test script")

def main():
    """Fix all import issues."""
    print("Fixing import path issues...")
    print("=" * 40)
    
    # Create __init__.py to make ai a proper package
    create_init_file()
    
    # Fix existing scripts
    fix_training_script()
    fix_test_script()
    fix_quick_start()
    
    # Create new direct scripts that work from root
    create_direct_train_script()
    create_direct_test_script()
    
    print("\n" + "=" * 40)
    print("Import fixes completed!")
    print("\nNow you can use:")
    print("  * python train_ai.py              (quick training from root)")
    print("  * python train_ai.py --normal     (normal training)")
    print("  * python train_ai.py --full       (full training)")
    print("  * python train_ai.py --resume     (resume training)")
    print("  * python test_ai.py               (test model)")
    print("  * python quick_start.py           (interactive menu)")
    print("\nOr from the ai directory:")
    print("  * python ai/simple_train.py")
    print("  * python ai/test_model.py")

if __name__ == "__main__":
    main()