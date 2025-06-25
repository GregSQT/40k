#!/usr/bin/env python3
"""
ai/train.py - Training with organized model structure and unified logging
"""

import os
import sys
import shutil
import subprocess
from datetime import datetime

def setup_imports():
    """Set up import paths."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, script_dir)
    sys.path.insert(0, project_root)

    from stable_baselines3 import DQN
    from stable_baselines3.common.env_checker import check_env
    
    try:
        from gym40k import W40KEnv
    except ImportError:
        try:
            from ai.gym40k import W40KEnv
        except ImportError:
            from gym40k import W40KEnv
    
    return DQN, check_env, W40KEnv

def parse_args():
    """Parse command line arguments."""
    resume = None
    debug = False
    timesteps = None
    
    for arg in sys.argv[1:]:
        if arg.lower() == "--resume":
            resume = True
        elif arg.lower() == "--new":
            resume = False
        elif arg.lower() == "--debug":
            debug = True
        elif arg.lower() == "--append":
            resume = True
        elif arg.startswith("--t="):
            timesteps = int(arg.split("=")[1])
        elif arg.lower() == "--help":
            print("🔧 W40K AI Training - Full Features")
            print("=" * 40)
            print("Usage: python ai/train.py [options]")
            print()
            print("Options:")
            print("  --resume      Resume from existing model (default)")
            print("  --new         Start new model (overwrite existing)")
            print("  --append      Same as --resume")
            print("  --debug       Debug mode (shorter training)")
            print("  --t=N         Set specific number of timesteps")
            print("  --help        Show this help")
            print()
            print("Examples:")
            print("  python ai/train.py                    # Resume training")
            print("  python ai/train.py --new              # Start fresh")
            print("  python ai/train.py --debug            # Quick debug run")
            print("  python ai/train.py --t=100000 # Custom timesteps")
            print()
            print("Output files:")
            print("  ai/models/current/model.zip")
            print("  ai/event_log/train_best_event_log.json")
            print("  ai/event_log/train_worst_event_log.json")
            print("  ai/event_log/train_summary.json")
            sys.exit(0)
    
    return resume, debug, timesteps

def backup_current_model():
    """Create backup before training."""
    current_model = "ai/models/current/model.zip"
    backup_dir = "ai/models/backups"
    
    if os.path.exists(current_model):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{backup_dir}/model_backup_{timestamp}.zip"
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(current_model, backup_path)
        print(f"📦 BACKUP: Created {os.path.basename(backup_path)}")
        
        # Manage backup count
        import glob
        backup_files = glob.glob(f"{backup_dir}/model_backup_*.zip")
        if len(backup_files) > 3:
            backup_files.sort(key=os.path.getmtime)
            for old_backup in backup_files[:-3]:
                os.remove(old_backup)
                print(f"🧹 CLEANUP: Removed old backup: {os.path.basename(old_backup)}")
        
        return backup_path
    return None

def save_training_logs(env):
    """Save training episode logs to unified location."""
    if not hasattr(env, "episode_logs") or not env.episode_logs:
        print("⚠️  No episode logs to save")
        return
    
    # Create unified event log directory
    event_log_dir = "ai/event_log"
    os.makedirs(event_log_dir, exist_ok=True)
    
    import json
    
    # Find best and worst episodes by reward
    best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
    worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
    
    # Save training logs with new naming convention
    train_best_file = os.path.join(event_log_dir, "train_best_event_log.json")
    train_worst_file = os.path.join(event_log_dir, "train_worst_event_log.json")
    
    with open(train_best_file, "w", encoding="utf-8") as f:
        json.dump(best_log, f, indent=2)
    
    with open(train_worst_file, "w", encoding="utf-8") as f:
        json.dump(worst_log, f, indent=2)
    
    print(f"📋 LOGS: Training episode logs saved")
    print(f"   📈 Best episode (reward: {best_reward:.2f}): {train_best_file}")
    print(f"   📉 Worst episode (reward: {worst_reward:.2f}): {train_worst_file}")
    
    # Save summary info
    summary_file = os.path.join(event_log_dir, "train_summary.json")
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_episodes": len(env.episode_logs),
        "best_reward": best_reward,
        "worst_reward": worst_reward,
        "average_reward": sum(x[1] for x in env.episode_logs) / len(env.episode_logs),
        "files": {
            "best": "train_best_event_log.json",
            "worst": "train_worst_event_log.json"
        }
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"   📊 Summary: {summary_file}")

def generate_scenario_if_needed():
    """Generate scenario if needed."""
    if not os.path.exists("ai/scenario.json"):
        print("🔧 Regenerating scenario.json...")
        try:
            subprocess.run([sys.executable, "tools/generate_scenario.py"], check=True)
            print("✅ Scenario generated")
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                subprocess.run([sys.executable, "generate_scenario.py"], check=True)
                print("✅ Scenario generated")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("⚠️  Using default scenario")

def create_or_load_model(env, model_path, resume_flag, total_timesteps, exploration_fraction_setup=0.3):
    """Create new model or load existing one based on arguments."""
    from stable_baselines3 import DQN
    
    if os.path.exists(model_path):
        if resume_flag is None:
            # No explicit flag, default: resume
            print("📂 Model exists. Resuming training from last checkpoint (default).")
            resume = True
        else:
            resume = resume_flag
            
        if resume:
            print("🔄 Resuming from previous model...")
            try:
                model = DQN.load(model_path, env=env)
                print("✅ Model loaded successfully")
                return model
            except Exception as e:
                print(f"❌ Failed to load model: {e}")
                print("🔧 Creating new model instead...")
                # Fall through to create new model
        else:
            print("🆕 Starting new model (overwriting previous model)...")
    else:
        print("🆕 No previous model found. Creating new model...")

    # Create new model with original parameters
    print("🔧 Creating new DQN model...")
    model = DQN(
        "MlpPolicy",
        env,
        verbose=1,
        buffer_size=25000,        # Increased from original 10000
        learning_rate=1e-3,       # Original value
        learning_starts=1000,     # Increased from original 100
        batch_size=128,           # Increased from original 64
        train_freq=4,             # Original value
        target_update_interval=500, # Original value
        exploration_fraction=exploration_fraction_setup, # Original value
        exploration_final_eps=0.05, # Original value
        tensorboard_log="./tensorboard/"
    )
    
    print("✅ New model created successfully")
    return model

def quick_test_model(model, env, episodes=5):
    """Quick test of the trained model."""
    print(f"\n🎮 Quick evaluation ({episodes} episodes)...")
    wins = 0
    
    for ep in range(episodes):
        try:
            obs, _ = env.reset()
            done = False
            steps = 0
            total_reward = 0
            
            while not done and steps < 100:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
                done = terminated or truncated
            
            winner = info.get("winner", None)
            if winner == 1:
                wins += 1
                result = "WIN"
            elif winner == 0:
                result = "LOSS"
            else:
                result = "DRAW"
                
            print(f"   Episode {ep+1}: {result:4s} ({steps:2d} steps, reward: {total_reward:6.2f})")
            
        except Exception as e:
            print(f"   Episode {ep+1}: ERROR - {e}")
    
    win_rate = (wins / episodes) * 100
    print(f"📊 RESULTS: {wins}/{episodes} wins ({win_rate:.1f}%)")
    
    if win_rate >= 80:
        print("🌟 OUTSTANDING: AI is performing excellently!")
    elif win_rate >= 60:
        print("🏆 EXCELLENT: AI is performing very well!")
    elif win_rate >= 40:
        print("👍 GOOD: AI is learning, consider more training")
    elif win_rate >= 20:
        print("😐 FAIR: AI shows some learning, needs more training")
    else:
        print("📊 NEEDS WORK: Consider longer training or parameter tuning")
    
    return win_rate

def main():
    """Main training function with full original functionality."""
    print("🔧 W40K AI Training - Full Features with Unified Logging")
    print("=" * 60)
    
    # Parse command line arguments
    resume_flag, debug_mode, custom_timesteps = parse_args()
    
    # Determine training parameters
    if custom_timesteps:
        total_timesteps = custom_timesteps
        print(f"🎯 Custom training: {total_timesteps:,} timesteps")
    elif debug_mode:
        total_timesteps = 50_000  # Shorter for debug
        print(f"🐛 Debug mode: {total_timesteps:,} timesteps")
    else:
        total_timesteps = 1_000_000  # Full training
        print(f"🎯 Full training: {total_timesteps:,} timesteps")
    
    exploration_fraction_setup = 0.3  # Default exploration
    
    # Ensure directory structure exists
    os.makedirs("ai/models/current", exist_ok=True)
    os.makedirs("ai/models/backups", exist_ok=True)
    os.makedirs("ai/event_log", exist_ok=True)
    
    # Generate scenario if needed
    generate_scenario_if_needed()
    
    # Setup imports
    try:
        DQN, check_env, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    
    # Backup existing model if resuming
    if resume_flag != False:  # If not explicitly --new
        backup_path = backup_current_model()
    
    # Create environment
    print("🌍 Creating environment...")
    env = W40KEnv()
    
    # Check environment
    try:
        check_env(env)
        print("✅ Environment validation passed")
    except Exception as e:
        print(f"⚠️  Environment check warning: {e}")
    
    print(f"🎮 Environment info:")
    print(f"   📊 Units: {len(env.units)}")
    print(f"   🎯 Max turns: {getattr(env, 'max_turns', 'Unknown')}")
    print(f"   🎲 Action space: {env.action_space}")
    print(f"   👁️  Observation space: {env.observation_space}")
    
    # Create or load model
    model_path = "ai/models/current/model.zip"
    model = create_or_load_model(env, model_path, resume_flag, total_timesteps, exploration_fraction_setup)
    
    # Start training
    print(f"\n🚀 Starting training for {total_timesteps:,} timesteps...")
    print(f"📊 Monitor with: tensorboard --logdir ./tensorboard/")
    print("=" * 60)
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print("✅ Training completed successfully!")
        
    except KeyboardInterrupt:
        print("⏹️  Training interrupted by user")
        print("💾 Saving current progress...")
        
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    print(f"\n💾 Saving model...")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    model.save(model_path)
    print(f"✅ Model saved to {model_path}")
    
    # Save episode logs with unified naming
    print(f"\n📋 Saving training logs...")
    save_training_logs(env)
    
    # Quick test of the model
    win_rate = quick_test_model(model, env, episodes=5)
    
    # Cleanup
    env.close()
    
    # Success summary
    print(f"\n🎉 Training session completed!")
    print(f"📈 Quick test win rate: {win_rate:.1f}%")
    
    print(f"\n🎯 Next Steps:")
    print(f"   📊 Full evaluation:   python ai/evaluate.py --episodes 100")
    print(f"   🔄 More training:     python ai/train.py --resume")
    print(f"   🔄 Convert for web:   python convert_replays.py")
    print(f"   📋 View logs:         ls ai/event_log/")
    print(f"   🌐 Web app:           cd frontend && npm run dev")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️  Training interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)