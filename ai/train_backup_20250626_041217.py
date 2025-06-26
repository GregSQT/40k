#!/usr/bin/env python3
"""
ai/train.py - Training with configuration system and unified logging with replay support
"""

import os
import sys
import json
import shutil
import subprocess
import glob
from datetime import datetime
from ai.web_replay_logger import WebReplayIntegration

try:
    from ai.web_replay_logger import WebReplayIntegration
    WEB_REPLAY_AVAILABLE = True
except ImportError:
    WEB_REPLAY_AVAILABLE = False
    print("⚠️  Web replay logger not available")

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
        elif arg.startswith("--config="):
            config_name = arg.split("=")[1]
        elif arg.lower() == "--help":
            print("🔧 W40K AI Training - Full Features")
            print("=" * 40)
            print("Usage: python ai/train.py [options]")
            print()
            print("Options:")
            print("  --resume         Resume from existing model (default)")
            print("  --new            Start new model (overwrite existing)")
            print("  --append         Same as --resume")
            print("  --debug          Debug mode (shorter training)")
            print("  --t=N            Set specific number of timesteps")
            print("  --config=NAME    Use specific config (default/conservative/debug)")
            print("  --help           Show this help")
            print()
            print("Examples:")
            print("  python ai/train.py                         # Resume training")
            print("  python ai/train.py --new                   # Start fresh")
            print("  python ai/train.py --debug                 # Quick debug run")
            print("  python ai/train.py --t=100000              # Custom timesteps")
            print("  python ai/train.py --config=conservative   # Use conservative config")
            print()
            print("Output files:")
            print("  ai/models/current/model.zip")
            print("  ai/event_log/train_best_game_replay.json")
            print("  ai/event_log/train_worst_game_replay.json")
            print("  ai/event_log/train_summary.json")
            sys.exit(0)
    
    return resume, debug, timesteps, config_name

def backup_current_model():
    """Create backup before training."""
    model_path = "ai/models/current/model.zip"
    if os.path.exists(model_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = "ai/models/backups"
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"model_backup_{timestamp}.zip")
        shutil.copy2(model_path, backup_path)
        print(f"💾 Model backed up to: {backup_path}")

def ensure_scenario():
    """Ensure scenario.json exists."""
    scenario_path = "ai/scenario.json"
    if not os.path.exists(scenario_path):
        print("📋 Generating scenario.json...")
        try:
            subprocess.run([sys.executable, "generate_scenario.py"], check=True)
            print("✅ Scenario generated successfully")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("⚠️  Scenario generator not found, using default scenario")

def run_training_episode_with_replay(model, env):
    """Run a single training episode with full replay logging."""
    try:
        # Check if we have game replay logger available
        from game_replay_logger import GameReplayIntegration
        
        # Set up replay logging for this episode
        event_log_dir = "ai/event_log"
        os.makedirs(event_log_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        replay_file = os.path.join(event_log_dir, f"game_replay_{timestamp}.json")
        
        # Enable replay logging in environment
        if hasattr(env, 'enable_replay_logging'):
            env.enable_replay_logging(replay_file)
        
        # Run episode - handle both old and new Gym API
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs, info = reset_result
        else:
            obs = reset_result
            
        total_reward = 0
        steps = 0
        done = False
        
        while not done:
            action, _ = model.predict(obs, deterministic=False)
            step_result = env.step(action)
            
            if len(step_result) == 5:  # New Gym API
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:  # Old Gym API
                obs, reward, done, info = step_result
                
            total_reward += reward
            steps += 1
            
            if steps > 1000:  # Prevent infinite episodes
                break
        
        # Finalize replay logging
        if hasattr(env, 'finalize_replay_logging'):
            env.finalize_replay_logging()
        
        # Verify replay file was created
        if os.path.exists(replay_file):
            return total_reward, steps, replay_file
        else:
            return total_reward, steps, None
            
    except ImportError:
        # Fallback to regular episode without replay
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs, info = reset_result
        else:
            obs = reset_result
            
        total_reward = 0
        steps = 0
        done = False
        
        while not done:
            action, _ = model.predict(obs, deterministic=False)
            step_result = env.step(action)
            
            if len(step_result) == 5:  # New Gym API
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:  # Old Gym API
                obs, reward, done, info = step_result
                
            total_reward += reward
            steps += 1
            
            if steps > 1000:  # Prevent infinite episodes
                break
        
        return total_reward, steps, None

def enhanced_training_with_replay(model, total_timesteps):
    """Enhanced training with web-compatible replay capture."""
    if not WEB_REPLAY_AVAILABLE:
        print("🔄 Web replay not available, using standard training...")
        model.learn(total_timesteps=total_timesteps)
        return
    
    print(f"🎬 Enhanced training with web-compatible replay generation")
    
    # Create a new environment with web replay logging
    env_with_replay = model.env
    
    # Check if environment already has web replay (avoid double-wrapping)
    if not hasattr(env_with_replay, 'web_replay_logger'):
        print("🔧 Adding web-compatible replay logging to environment...")
        env_with_replay = WebReplayIntegration.enhance_training_env(env_with_replay)
        model.set_env(env_with_replay)
    
    # Calculate replay intervals (capture every 10% of training)
    replay_interval = max(1000, total_timesteps // 10)
    episode_replays = []
    episode_rewards = []
    episodes_captured = 0
    current_step = 0
    
    try:
        while current_step < total_timesteps:
            if current_step % replay_interval == 0 and current_step > 0:
                # Capture a web-compatible replay episode
                print(f"🎥 Capturing web replay at step {current_step}")
                
                episode_reward, episode_steps, replay_file = run_training_episode_with_web_replay(model, env_with_replay)
                
                if replay_file:
                    episode_replays.append(replay_file)
                    episode_rewards.append(episode_reward)
                    episodes_captured += 1
                    print(f"   ✅ Captured: {replay_file}")
                
                current_step += episode_steps
            else:
                # Regular training step
                remaining_steps = min(1000, total_timesteps - current_step)
                model.learn(total_timesteps=remaining_steps)
                current_step += remaining_steps
        
        # Final training if needed
        if current_step < total_timesteps:
            model.learn(total_timesteps=total_timesteps - current_step)
        
        print(f"✅ Training completed with {episodes_captured} web replays captured")
        
        # Select best and worst replays and copy to standard locations
        if episode_replays and episode_rewards:
            best_idx = episode_rewards.index(max(episode_rewards))
            worst_idx = episode_rewards.index(min(episode_rewards))
            
            event_log_dir = "ai/event_log"
            os.makedirs(event_log_dir, exist_ok=True)
            
            best_dest = os.path.join(event_log_dir, "train_best_web_replay.json")
            worst_dest = os.path.join(event_log_dir, "train_worst_web_replay.json")
            
            shutil.copy2(episode_replays[best_idx], best_dest)
            shutil.copy2(episode_replays[worst_idx], worst_dest)
            
            print(f"   🏆 Best web replay: train_best_web_replay.json")
            print(f"   📉 Worst web replay: train_worst_web_replay.json")
        
    except Exception as e:
        print(f"⚠️  Enhanced training failed: {e}")
        print("🔄 Falling back to standard training...")
        model.learn(total_timesteps=total_timesteps)

def run_training_episode_with_web_replay(model, env):
    """Run a single training episode with web replay capture."""
    try:
        # Run episode
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs, info = reset_result
        else:
            obs = reset_result
            
        total_reward = 0
        steps = 0
        done = False
        
        while not done and steps < 1000:  # Prevent infinite episodes
            action, _ = model.predict(obs, deterministic=False)
            step_result = env.step(action)
            
            if len(step_result) == 5:  # New Gym API
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:  # Old Gym API
                obs, reward, done, info = step_result
                
            total_reward += reward
            steps += 1
        
        # Save replay if logger available
        replay_file = None
        if hasattr(env, 'web_replay_logger'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            event_log_dir = "ai/event_log"
            os.makedirs(event_log_dir, exist_ok=True)
            replay_file = os.path.join(event_log_dir, f"web_replay_{timestamp}.json")
            env.web_replay_logger.save_web_replay(replay_file, total_reward)
        
        return total_reward, steps, replay_file
        
    except Exception as e:
        print(f"   ⚠️  Episode failed: {e}")
        return 0.0, 0, None

def save_training_logs_with_replay(env):
    """Save training logs with web-compatible replay data only."""
    if not hasattr(env, "episode_logs") or not env.episode_logs:
        print("⚠️  No episode logs to save")
        return
    
    event_log_dir = "ai/event_log"
    os.makedirs(event_log_dir, exist_ok=True)
    
    # Find best and worst episodes
    best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
    worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
    
    print(f"📋 SUMMARY: Saving training summary (web-compatible format only)")
    
    # Save training summary ONLY - NO SIMPLIFIED EVENT LOGS
    summary_file = os.path.join(event_log_dir, "train_summary.json")
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_episodes": len(env.episode_logs),
        "best_reward": best_reward,
        "worst_reward": worst_reward,
        "average_reward": sum(x[1] for x in env.episode_logs) / len(env.episode_logs),
        "files": {
            "best_replay": "train_best_web_replay.json",
            "worst_replay": "train_worst_web_replay.json"
        },
        "replay_type": "web_compatible_direct",
        "web_compatible": True,
        "features": [
            "Direct web compatibility",
            "Complete unit positions",
            "HP tracking", 
            "Movement visualization",
            "Combat events",
            "Turn-by-turn progression",
            "No conversion needed"
        ],
        "note": "Replays generated directly in web-compatible format - no simplified event logs created"
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"   📊 Summary: {summary_file}")
    print(f"   ℹ️  NOTE: NO simplified event logs generated - only web-compatible files")
    print(f"   🌐 Web replay files: train_best_web_replay.json, train_worst_web_replay.json")

def quick_test_model(model, env):
    """Quick test of trained model."""
    print("🧪 Quick model test...")
    
    wins = 0
    total_games = 5
    
    for i in range(total_games):
        # Handle both old and new Gym API for reset()
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs, info = reset_result
        else:
            obs = reset_result
            
        done = False
        steps = 0
        
        while not done and steps < 100:
            action, _ = model.predict(obs, deterministic=True)
            
            # Handle both old and new Gym API for step()
            step_result = env.step(action)
            if len(step_result) == 5:  # New Gym API
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:  # Old Gym API
                obs, reward, done, info = step_result
                
            steps += 1
        
        if hasattr(env, 'player_wins') and env.player_wins():
            wins += 1
    
    win_rate = wins / total_games
    print(f"   Win rate: {wins}/{total_games} ({win_rate:.1%})")
    return win_rate

def main():
    """Main training function with full replay support."""
    print("🤖 W40K AI Training with Enhanced Replay System")
    print("=" * 50)
    
    # Parse arguments
    resume, debug, custom_timesteps, config_name = parse_args()
    
    # Load configuration
    try:
        config = load_config(config_name)
        print(f"📋 Using config: {config_name}")
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  Config error: {e}")
        print("🔧 Using default parameters")
        config = {
            "total_timesteps": 100_000,
            "buffer_size": 50_000,
            "learning_rate": 1e-3,
            "learning_starts": 1000,
            "batch_size": 64,
            "train_freq": 4,
            "target_update_interval": 1000,
            "exploration_fraction": 0.3,
            "exploration_final_eps": 0.05
        }
    
    # Set up imports
    DQN, check_env, W40KEnv = setup_imports()
    
    # Ensure scenario exists
    ensure_scenario()
    
    # Determine timesteps
    if custom_timesteps:
        total_timesteps = custom_timesteps
    elif debug:
        total_timesteps = 10_000
    else:
        total_timesteps = config.get("total_timesteps", 100_000)
    
    print(f"🎯 Training for {total_timesteps:,} timesteps")
    
    # Create environment
    print("🌍 Creating environment...")
    env = W40KEnv()
    
    # Check environment
    try:
        check_env(env)
        print("✅ Environment validation passed")
    except Exception as e:
        print(f"⚠️  Environment check warning: {e}")
    
    # Display environment info
    print(f"   Units: {len(env.units)}")
    print(f"   Observation space: {env.observation_space}")
    print(f"   Action space: {env.action_space}")
    
    # Set up model path
    models_dir = "ai/models/current"
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, "model.zip")
    
    # Handle resume logic
    if resume is None:
        resume = os.path.exists(model_path)
    
    if resume and os.path.exists(model_path):
        print("📂 Loading existing model...")
        backup_current_model()
        model = DQN.load(model_path, env=env)
        print("✅ Model loaded successfully")
    else:
        if os.path.exists(model_path):
            backup_current_model()
        
        print("🆕 Creating new DQN model...")
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            buffer_size=config.get("buffer_size", 50_000),
            learning_rate=config.get("learning_rate", 1e-3),
            learning_starts=config.get("learning_starts", 1000),
            batch_size=config.get("batch_size", 64),
            train_freq=config.get("train_freq", 4),
            target_update_interval=config.get("target_update_interval", 1000),
            exploration_fraction=config.get("exploration_fraction", 0.3),
            exploration_final_eps=config.get("exploration_final_eps", 0.05),
            tensorboard_log="./tensorboard/"
        )
        print("✅ Model created successfully")
    
    print(f"🚀 Starting training...")
    print()
    
    try:
        # Use enhanced training with replay if possible
        try:
            enhanced_training_with_replay(model, total_timesteps)
        except Exception as e:
            print(f"⚠️  Enhanced replay training failed: {e}")
            print("🔄 Falling back to standard training...")
            model.learn(total_timesteps=total_timesteps)
        
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
    print(f"   🌐 Web app:          cd frontend && npm run dev")
    print(f"   🎬 View replays:     python ai/replay.py")
    
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