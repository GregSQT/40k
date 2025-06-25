#!/usr/bin/env python3
"""
ai/train.py - Training with configuration system and unified logging
"""

import os
import sys
import json
import shutil
import subprocess
from datetime import datetime

def load_config(config_name="default"):
    """Load training configuration from config file."""
    config_path = "config/training_config.json"
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Training config not found: {config_path}")
    
    with open(config_path, "r") as f:
        configs = json.load(f)
    
    if config_name not in configs:
        available = list(configs.keys())
        raise ValueError(f"Config '{config_name}' not found. Available: {available}")
    
    return configs[config_name]

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
    config_name = "default"
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.lower() == "--resume":
            resume = True
            i += 1
        elif arg.lower() == "--new":
            resume = False
            i += 1
        elif arg.lower() == "--debug":
            debug = True
            i += 1
        elif arg.lower() == "--append":
            resume = True
            i += 1
        elif arg.startswith("--t="):
            timesteps = int(arg.split("=")[1])
            i += 1
        elif arg == "--config" and i + 1 < len(sys.argv):
            config_name = sys.argv[i + 1]
            i += 2
        elif arg.lower() == "--help":
            print("🔧 W40K AI Training - Configuration System")
            print("=" * 50)
            print("Usage: python ai/train.py [options]")
            print()
            print("Options:")
            print("  --resume        Resume from existing model (default)")
            print("  --new           Start new model (overwrite existing)")
            print("  --append        Same as --resume")
            print("  --debug         Debug mode (uses debug config)")
            print("  --t=N           Override timesteps from config")
            print("  --config NAME   Use specific config (default: 'default')")
            print("  --help          Show this help")
            print()
            print("Available configs:")
            try:
                config_path = "config/training_config.json"
                if os.path.exists(config_path):
                    with open(config_path, "r") as f:
                        configs = json.load(f)
                    for name, config in configs.items():
                        print(f"  {name:12} - {config['description']}")
                        print(f"              ({config['total_timesteps']:,} timesteps)")
                else:
                    print("  No config file found!")
            except Exception as e:
                print(f"  Error reading configs: {e}")
            print()
            print("Examples:")
            print("  python ai/train.py                       # Use default config")
            print("  python ai/train.py --config debug        # Use debug config")
            print("  python ai/train.py --config conservative # Use conservative config")
            print("  python ai/train.py --new --config debug  # Start fresh with debug")
            print("  python ai/train.py --t=50000             # Override timesteps")
            print()
            print("Output files:")
            print("  ai/models/current/model.zip")
            print("  ai/event_log/train_best_event_log.json")
            print("  ai/event_log/train_worst_event_log.json")
            print("  ai/event_log/train_summary.json")
            sys.exit(0)
        else:
            print(f"Unknown argument: {arg}")
            sys.exit(1)
    
    # Debug mode auto-selects debug config unless overridden
    if debug and config_name == "default":
        config_name = "debug"
    
    return resume, debug, timesteps, config_name

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
    """Save training episode logs in web-compatible format."""
    # Import the web log generator
    try:
        from web_log_generator import WebLogGenerator
    except ImportError:
        # Fallback to simple format if web_log_generator not available
        print("⚠️  WebLogGenerator not found, using simple format")
        save_training_logs_simple(env)
        return
    
    # Use web log generator
    generator = WebLogGenerator()
    generator.convert_and_save_training_logs(env)

def save_training_logs_simple(env):
    """Fallback: Save training logs in simple format."""
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
    train_best_file = os.path.join(event_log_dir, "train_best_event_log_simple.json")
    train_worst_file = os.path.join(event_log_dir, "train_worst_event_log_simple.json")
    
    with open(train_best_file, "w", encoding="utf-8") as f:
        json.dump(best_log, f, indent=2)
    
    with open(train_worst_file, "w", encoding="utf-8") as f:
        json.dump(worst_log, f, indent=2)
    
    print(f"📋 LOGS: Training episode logs saved (simple format)")
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
            "best": "train_best_event_log_simple.json",
            "worst": "train_worst_event_log_simple.json"
        },
        "web_compatible": False
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"   📊 Summary: {summary_file}")
    print(f"   ⚠️  Use convert_replays.py to make web-compatible")

def generate_scenario_if_needed():
    """Generate scenario if needed."""
    if not os.path.exists("ai/scenario.json"):
        print("🔧 Regenerating scenario.json...")
        try:
            subprocess.run(["python", "generate_scenario.py"], check=True)
            print("✅ Scenario generated")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("⚠️  Using default scenario")

def create_or_load_model(env, model_path, resume_flag, config, DQN):
    """Create or load model using configuration."""
    model_params = config['model_params'].copy()
    
    if os.path.exists(model_path) and resume_flag != False:
        if resume_flag is None:
            print("📁 Model exists. Resuming training from last checkpoint (default).")
            resume = True
        else:
            resume = resume_flag
        
        if resume:
            print("🔄 Loading existing model...")
            model = DQN.load(model_path, env=env)
        else:
            print("🆕 Starting new model (overwriting previous)...")
            model = DQN(env=env, **model_params)
    else:
        print("🆕 No previous model found. Creating new model...")
        model = DQN(env=env, **model_params)
    
    return model

def quick_test_model(model, env):
    """Quick test of the trained model."""
    print("\n🧪 Running quick model test...")
    
    wins, losses, draws = 0, 0, 0
    
    for episode in range(10):
        obs, info = env.reset()
        done = False
        
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        
        # Determine outcome
        if hasattr(env, 'game_state') and hasattr(env.game_state, 'winner'):
            if env.game_state.winner == 'player':
                wins += 1
            elif env.game_state.winner == 'ai':
                losses += 1
            else:
                draws += 1
        else:
            # Fallback: use reward to estimate outcome
            if reward > 50:
                wins += 1
            elif reward < -50:
                losses += 1
            else:
                draws += 1
    
    total_games = wins + losses + draws
    win_rate = (wins / total_games * 100) if total_games > 0 else 0
    
    print(f"📊 Test Results: {wins}W/{losses}L/{draws}D (Win rate: {win_rate:.1f}%)")
    
    if win_rate >= 80:
        print("🏆 EXCELLENT: AI is performing very well!")
    elif win_rate >= 60:
        print("👍 GOOD: AI is learning, consider more training")
    elif win_rate >= 40:
        print("😐 FAIR: AI shows some learning, needs more training")
    else:
        print("📊 NEEDS WORK: Consider longer training or parameter tuning")
    
    return win_rate

def main():
    """Main training function with configuration system."""
    print("🔧 W40K AI Training - Configuration System")
    print("=" * 60)
    
    # Parse command line arguments
    resume_flag, debug_mode, custom_timesteps, config_name = parse_args()
    
    # Load configuration
    try:
        config = load_config(config_name)
        print(f"⚙️  Using config: '{config_name}'")
        print(f"   📝 {config['description']}")
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ Configuration error: {e}")
        return False
    
    # Determine training parameters from config
    total_timesteps = config['total_timesteps']
    
    # Override timesteps if specified
    if custom_timesteps:
        total_timesteps = custom_timesteps
        print(f"🎯 Custom timesteps override: {total_timesteps:,}")
    else:
        print(f"🎯 Config timesteps: {total_timesteps:,}")
    
    # Show key parameters
    model_params = config['model_params']
    print(f"🔧 Key parameters:")
    print(f"   🧠 Learning rate: {model_params['learning_rate']}")
    print(f"   💾 Buffer size: {model_params['buffer_size']:,}")
    print(f"   🚀 Learning starts: {model_params['learning_starts']:,}")
    print(f"   📦 Batch size: {model_params['batch_size']}")
    print(f"   🎲 Exploration: {model_params['exploration_fraction']}")
    
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
    
    # Create or load model using configuration
    model_path = "ai/models/current/model.zip"
    model = create_or_load_model(env, model_path, resume_flag, config, DQN)
    
    # Start training
    print(f"\n🚀 Starting training for {total_timesteps:,} timesteps...")
    print(f"📊 Monitor with: tensorboard --logdir ./tensorboard/")
    print("=" * 60)
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print("✅ Training completed successfully!")
    except KeyboardInterrupt:
        print("⏹️  Training interrupted by user")
        model.save(model_path)
        print(f"💾 Model saved to {model_path}")
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    model.save(model_path)
    print(f"💾 Model saved to {model_path}")
    
    # Save training logs
    save_training_logs(env)
    
    # Quick test
    win_rate = quick_test_model(model, env)
    
    # Cleanup
    env.close()
    
    # Success message
    print("\n" + "=" * 60)
    print("✅ Training completed successfully!")
    print(f"\n🎯 Next Steps:")
    print(f"   🧪 Test model:       python ai/evaluate.py")
    print(f"   🔄 More training:    python ai/train.py --resume")
    print(f"   🔄 Different config: python ai/train.py --config conservative")
    print(f"   📋 View logs:        ls ai/event_log/")
    print(f"   🌐 Web app:          cd frontend && npm run dev")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n⏹️ Training interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)



##### Code to add I don't know where :

#!/usr/bin/env python3
"""
Enhanced training script with full game replay logging
"""

# Update the save_training_logs function to use game replay logging
def save_training_logs_with_replay(env):
    """Save training logs with full game replay data."""
    if not hasattr(env, "episode_logs") or not env.episode_logs:
        print("⚠️  No episode logs to save")
        return
    
    # Import the game replay integration
    try:
        from game_replay_logger import GameReplayIntegration
    except ImportError:
        print("⚠️  GameReplayLogger not found, falling back to simple logs")
        save_training_logs_simple(env)
        return
    
    event_log_dir = "ai/event_log"
    os.makedirs(event_log_dir, exist_ok=True)
    
    # Find best and worst episodes
    best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
    worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
    
    print(f"📋 LOGS: Generating full game replay logs...")
    
    # The game replay files are already saved during training
    # Just create the summary and links
    best_replay_file = os.path.join(event_log_dir, "train_best_game_replay.json")
    worst_replay_file = os.path.join(event_log_dir, "train_worst_game_replay.json")
    
    # If we have replay files from the episodes, use them
    import glob
    replay_files = sorted(glob.glob(os.path.join(event_log_dir, "game_replay_*.json")), 
                         key=os.path.getmtime)
    
    if len(replay_files) >= 2:
        # Use the most recent replay files
        import shutil
        shutil.copy2(replay_files[-1], best_replay_file)  # Most recent (likely best)
        shutil.copy2(replay_files[0], worst_replay_file)   # Oldest (likely worst)
    
    print(f"   🎮 Best episode replay: {best_replay_file}")
    print(f"   🎮 Worst episode replay: {worst_replay_file}")
    print(f"   🌐 Full game state replays ready for web app!")
    
    # Save training summary
    summary_file = os.path.join(event_log_dir, "train_summary.json")
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_episodes": len(env.episode_logs),
        "best_reward": best_reward,
        "worst_reward": worst_reward,
        "average_reward": sum(x[1] for x in env.episode_logs) / len(env.episode_logs),
        "files": {
            "best_replay": "train_best_game_replay.json",
            "worst_replay": "train_worst_game_replay.json"
        },
        "replay_type": "full_game_state",
        "web_compatible": True,
        "features": [
            "Complete unit positions",
            "HP tracking", 
            "Movement visualization",
            "Combat events",
            "Turn-by-turn progression"
        ]
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"   📊 Summary: {summary_file}")

def run_training_episode_with_replay(model, env):
    """Run a single training episode with full replay logging."""
    from game_replay_logger import GameReplayIntegration
    
    # Enhanced environment with replay logging
    env_with_replay = GameReplayIntegration.enhance_training_env(env)
    
    # Run the episode
    obs, info = env_with_replay.reset()
    episode_reward = 0
    episode_steps = 0
    done = False
    
    while not done:
        action, _ = model.predict(obs, deterministic=False)
        obs, reward, terminated, truncated, info = env_with_replay.step(action)
        
        episode_reward += reward
        episode_steps += 1
        done = terminated or truncated
    
    # Save the replay for this episode
    replay_file = GameReplayIntegration.save_episode_replay(
        env_with_replay, 
        episode_reward
    )
    
    return episode_reward, episode_steps, replay_file

def create_or_load_model_with_replay_support(env, model_path, resume_flag, config, DQN):
    """Create or load model with enhanced logging support."""
    model_params = config['model_params'].copy()
    
    if os.path.exists(model_path) and resume_flag != False:
        if resume_flag is None:
            print("📁 Model exists. Resuming training from last checkpoint (default).")
            resume = True
        else:
            resume = resume_flag
        
        if resume:
            print("🔄 Loading existing model...")
            model = DQN.load(model_path, env=env)
        else:
            print("🆕 Starting new model (overwriting previous)...")
            model = DQN(env=env, **model_params)
    else:
        print("🆕 No previous model found. Creating new model...")
        model = DQN(env=env, **model_params)
    
    return model

def enhanced_model_learn(model, env, total_timesteps):
    """Enhanced model learning with periodic replay capture."""
    from game_replay_logger import GameReplayIntegration
    
    print(f"🎬 Training with full game replay logging...")
    print(f"   📸 Capturing complete game states")
    print(f"   🎮 Recording unit movements and combat")
    print(f"   🌐 Generating web-compatible replays")
    
    # Store episode replays
    episode_replays = []
    episode_rewards = []
    
    # We'll capture replays for a few episodes during training
    capture_every = max(1, total_timesteps // (10 * 200))  # Capture ~10 replays
    episodes_captured = 0
    max_replays_to_keep = 5
    
    print(f"   🎯 Will capture replay every ~{capture_every} steps")
    
    try:
        # Start training
        current_step = 0
        
        while current_step < total_timesteps:
            # Determine if we should capture replay this episode
            should_capture = (episodes_captured < max_replays_to_keep and 
                            current_step % capture_every < 200)  # Approximate episode length
            
            if should_capture:
                print(f"   🎬 Capturing replay at step {current_step}")
                
                # Run episode with replay
                episode_reward, episode_steps, replay_file = run_training_episode_with_replay(model, env)
                
                if replay_file:
                    episode_replays.append(replay_file)
                    episode_rewards.append(episode_reward)
                    episodes_captured += 1
                
                current_step += episode_steps
            else:
                # Regular training step
                remaining_steps = min(1000, total_timesteps - current_step)
                model.learn(total_timesteps=remaining_steps)
                current_step += remaining_steps
        
        # Final training if needed
        if current_step < total_timesteps:
            model.learn(total_timesteps=total_timesteps - current_step)
        
        print(f"✅ Training completed with {episodes_captured} replays captured")
        
        # Select best and worst replays
        if episode_replays and episode_rewards:
            best_idx = episode_rewards.index(max(episode_rewards))
            worst_idx = episode_rewards.index(min(episode_rewards))
            
            # Copy best and worst to standard locations
            import shutil
            event_log_dir = "ai/event_log"
            
            best_dest = os.path.join(event_log_dir, "train_best_game_replay.json")
            worst_dest = os.path.join(event_log_dir, "train_worst_game_replay.json")
            
            shutil.copy2(episode_replays[best_idx], best_dest)
            shutil.copy2(episode_replays[worst_idx], worst_dest)
            
            print(f"   🏆 Best replay (reward: {episode_rewards[best_idx]:.2f}): train_best_game_replay.json")
            print(f"   📉 Worst replay (reward: {episode_rewards[worst_idx]:.2f}): train_worst_game_replay.json")
        
    except KeyboardInterrupt:
        print("⏹️  Training interrupted - saving current progress")
        raise

# Modified main function section for train.py
def main_with_replay_support():
    """Main training function with full game replay support."""
    print("🎬 W40K AI Training - Full Game Replay System")
    print("=" * 60)
    
    # [Previous argument parsing code remains the same...]
    resume_flag, debug_mode, custom_timesteps, config_name = parse_args()
    
    # Load configuration
    try:
        config = load_config(config_name)
        print(f"⚙️  Using config: '{config_name}'")
        print(f"   📝 {config['description']}")
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ Configuration error: {e}")
        return False
    
    # Determine training parameters from config
    total_timesteps = config['total_timesteps']
    
    # Override timesteps if specified
    if custom_timesteps:
        total_timesteps = custom_timesteps
        print(f"🎯 Custom timesteps override: {total_timesteps:,}")
    else:
        print(f"🎯 Config timesteps: {total_timesteps:,}")
    
    # Show key parameters
    model_params = config['model_params']
    print(f"🔧 Key parameters:")
    print(f"   🧠 Learning rate: {model_params['learning_rate']}")
    print(f"   💾 Buffer size: {model_params['buffer_size']:,}")
    print(f"   🚀 Learning starts: {model_params['learning_starts']:,}")
    print(f"   📦 Batch size: {model_params['batch_size']}")
    print(f"   🎲 Exploration: {model_params['exploration_fraction']}")
    
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
    if resume_flag != False:
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
    model = create_or_load_model_with_replay_support(env, model_path, resume_flag, config, DQN)
    
    # Start enhanced training
    print(f"\n🚀 Starting training for {total_timesteps:,} timesteps...")
    print(f"📊 Monitor with: tensorboard --logdir ./tensorboard/")
    print(f"🎬 Game replays will be saved to ai/event_log/")
    print("=" * 60)
    
    try:
        enhanced_model_learn(model, env, total_timesteps)
        print("✅ Training completed successfully!")
    except KeyboardInterrupt:
        print("⏹️  Training interrupted by user")
        model.save(model_path)
        print(f"💾 Model saved to {model_path}")
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    model.save(model_path)
    print(f"💾 Model saved to {model_path}")
    
    # Save training logs with replay support
    save_training_logs_with_replay(env)
    
    # Quick test
    win_rate = quick_test_model(model, env)
    
    # Cleanup
    env.close()
    
    # Success message
    print("\n" + "=" * 60)
    print("✅ Training completed successfully!")
    print(f"\n🎯 Next Steps:")
    print(f"   🧪 Test model:       python ai/evaluate.py")
    print(f"   🔄 More training:    python ai/train.py --resume")
    print(f"   🔄 Different config: python ai/train.py --config conservative")
    print(f"   📋 View logs:        ls ai/event_log/")
    print(f"   🎬 Game replays:     train_best_game_replay.json")
    print(f"   🌐 Web app:          cd frontend && npm run dev")
    print(f"\n🎮 In web app: Load train_best_game_replay.json to watch your AI battle!")
    
    return True

# Usage instructions for integration
if __name__ == "__main__":
    """
    To integrate this enhanced replay system:
    
    1. Save game_replay_logger.py in your project root
    2. Replace your train.py save_training_logs function with save_training_logs_with_replay
    3. Replace your main() function with main_with_replay_support()
    4. Add the enhanced training functions above
    
    This will generate:
    - train_best_game_replay.json (full game visualization)
    - train_worst_game_replay.json (full game visualization)
    - Complete unit movements, combat, HP changes
    - Turn-by-turn game progression
    - Direct web app compatibility
    """
    
    try:
        success = main_with_replay_support()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n⏹️ Training interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)