#!/usr/bin/env python3
# ai/train.py - Complete training script with all features and fixed symbols

import os
import sys
import json
import shutil
import subprocess
import glob
from datetime import datetime
import numpy as np
import time

# Progress tracking class
class ProgressTracker:
    def __init__(self, total_timesteps, bar_width=50):
        self.total_timesteps = total_timesteps
        self.bar_width = bar_width
        self.current_timesteps = 0
        self.min_reward = float('inf')
        self.max_reward = float('-inf')
        self.current_reward = 0.0
        self.episode_count = 0
        self.start_time = time.time()
        
    def update_timesteps(self, timesteps):
        self.current_timesteps = min(timesteps, self.total_timesteps)
        
    def update_reward(self, reward):
        self.current_reward = reward
        self.min_reward = min(self.min_reward, reward)
        self.max_reward = max(self.max_reward, reward)
        self.episode_count += 1
        
    def draw_timesteps_bar(self):
        if self.total_timesteps == 0:
            progress = 0.0
        else:
            progress = self.current_timesteps / self.total_timesteps
        
        filled_length = int(self.bar_width * progress)
        bar = '█' * filled_length + '░' * (self.bar_width - filled_length)
        
        elapsed_time = time.time() - self.start_time
        if progress > 0:
            eta_seconds = (elapsed_time / progress) * (1 - progress)
            eta_str = f" ETA: {int(eta_seconds//3600):02d}:{int((eta_seconds%3600)//60):02d}:{int(eta_seconds%60):02d}"
        else:
            eta_str = " ETA: --:--:--"
        
        return f"Timesteps: |{bar}| {self.current_timesteps:,}/{self.total_timesteps:,} ({progress*100:.1f}%){eta_str}"
    
    def draw_reward_bar(self):
        if self.min_reward == float('inf') or self.max_reward == float('-inf'):
            bar = '░' * self.bar_width
            return f"Reward: |{bar}| No data yet"
        elif self.max_reward == self.min_reward:
            mid_pos = self.bar_width // 2
            bar = '░' * mid_pos + '●' + '░' * (self.bar_width - mid_pos - 1)
            return f"Reward: |{bar}| {self.current_reward:.2f} (constant)"
        else:
            reward_range = self.max_reward - self.min_reward
            progress = (self.current_reward - self.min_reward) / reward_range if reward_range > 0 else 0.5
            progress = max(0.0, min(1.0, progress))
            
            bar_chars = ['░'] * self.bar_width
            position = int(progress * (self.bar_width - 1))
            bar_chars[position] = '●'
            bar = ''.join(bar_chars)
            
            return f"Reward: |{bar}| {self.current_reward:.2f} (min:{self.min_reward:.2f}, max:{self.max_reward:.2f})"

# Fix import paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

# helper to serialize numpy types in replay logs
def numpy_encoder(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

# Try to import web replay logger
try:
    from web_replay_logger import WebReplayIntegration
    WEB_REPLAY_AVAILABLE = True
except ImportError:
    WEB_REPLAY_AVAILABLE = False
    print("Warning: Web replay logger not available")

def load_config(config_name="default"):
    """Load training configuration from config file."""
    config_path = os.path.join(project_root, "config", "training_config.json")
    
    if not os.path.exists(config_path):
        print("Creating default training config...")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        default_configs = {
            "default": {
                "total_timesteps": 1_000_000,
                "exploration_fraction": 0.3,
                "exploration_final_eps": 0.05,
                "learning_rate": 1e-3,
                "buffer_size": 50_000,
                "learning_starts": 1000,
                "batch_size": 64,
                "train_freq": 4,
                "target_update_interval": 1000,
                "description": "Default balanced training configuration"
            },
            "debug": {
                "total_timesteps": 100_000,
                "exploration_fraction": 0.5,
                "exploration_final_eps": 0.1,
                "learning_rate": 1e-3,
                "buffer_size": 10_000,
                "learning_starts": 500,
                "batch_size": 32,
                "train_freq": 4,
                "target_update_interval": 500,
                "description": "Fast debug configuration"
            },
            "conservative": {
                "total_timesteps": 2_000_000,
                "exploration_fraction": 0.2,
                "exploration_final_eps": 0.02,
                "learning_rate": 5e-4,
                "buffer_size": 100_000,
                "learning_starts": 2000,
                "batch_size": 128,
                "train_freq": 8,
                "target_update_interval": 2000,
                "description": "Conservative, thorough training"
            }
        }
        
        with open(config_path, "w") as f:
            json.dump(default_configs, f, indent=2)
        print(f"Created default config at: {config_path}")
    
    with open(config_path, "r") as f:
        configs = json.load(f)
    
    if config_name not in configs:
        available = list(configs.keys())
        raise ValueError(f"Config '{config_name}' not found. Available: {available}")
    
    return configs[config_name]

def setup_imports():
    """Set up import paths and return required modules."""
    try:
        from stable_baselines3 import DQN
        from stable_baselines3.common.env_checker import check_env
    except ImportError as e:
        print(f"Error importing stable_baselines3: {e}")
        print("Please install: pip install stable-baselines3")
        raise
    
    # Try multiple import methods for gym40k
    try:
        from gym40k import W40KEnv
    except ImportError:
        try:
            from ai.gym40k import W40KEnv
        except ImportError:
            import importlib.util
            gym_path = os.path.join(script_dir, "gym40k.py")
            if os.path.exists(gym_path):
                spec = importlib.util.spec_from_file_location("gym40k", gym_path)
                if spec is not None and spec.loader is not None:
                    gym_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(gym_module)
                    W40KEnv = gym_module.W40KEnv
                else:
                    raise ImportError("Could not create module spec for gym40k.py")
                W40KEnv = gym_module.W40KEnv
            else:
                raise ImportError("Could not find gym40k.py")
    
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
            print("🧹 --NEW: Cleaning all previous training data...")
            clean_all_previous_models()
            resume = False
        elif arg.lower() == "--debug":
            debug = True
            config_name = "debug"
        elif arg.lower() == "--append":
            resume = True
        elif arg.startswith("--t="):
            timesteps = int(arg.split("=")[1])
        elif arg.startswith("--config="):
            config_name = arg.split("=")[1]
        elif arg.lower() == "--help":
            print("W40K AI Training - Full Features")
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
    models_dir = "ai/models/current"
    backup_dir = "ai/models/backups"
    os.makedirs(backup_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, "model.zip")
    if os.path.exists(model_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"model_backup_{timestamp}.zip")
        shutil.copy2(model_path, backup_path)
        print(f"Backup created: {backup_path}")
        
        # Keep only last 5 backups
        backups = sorted(glob.glob(os.path.join(backup_dir, "model_backup_*.zip")))
        if len(backups) > 2:
            for old_backup in backups[:-2]:
                os.remove(old_backup)
                print(f"Removed old backup: {old_backup}")

def ensure_scenario():
    """Ensure scenario.json exists."""
    scenario_path = os.path.join(script_dir, "scenario.json")
    if not os.path.exists(scenario_path):
        print("Generating scenario.json...")
        try:
            generate_script = os.path.join(script_dir, "generate_scenario.py")
            if os.path.exists(generate_script):
                subprocess.run([sys.executable, "generate_scenario.py"], check=True, cwd=script_dir)
                print("Scenario generated successfully")
            else:
                print("Generate script not found, using default scenario")
                # Create default scenario
                default_scenario = [
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
                with open(scenario_path, "w") as f:
                    json.dump(default_scenario, f, indent=2)
                print("Created default scenario")
        except Exception as e:
            print(f"Scenario generation failed: {e}")

def clean_all_previous_models():
    """Delete ALL previous training data when starting completely fresh."""
    paths_to_clean = [
        "ai/model.zip",                          # Legacy model location
        "ai/models/current/model.zip",           # Current model
        "ai/models/backups/",                    # All backups
        "tensorboard/",                          # Training logs
        "ai/event_log/train_*.json",            # Training replays
    ]
    
    cleaned_count = 0
    for path in paths_to_clean:
        if "*" in path:
            for file_path in glob.glob(path):
                if os.path.exists(file_path):
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)
                    cleaned_count += 1
                    print(f"🗑️  Deleted: {file_path}")
        else:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                cleaned_count += 1
                print(f"🗑️  Deleted: {path}")
    
    if cleaned_count > 0:
        print(f"✅ Cleaned {cleaned_count} previous training files")
    else:
        print("ℹ️  No previous files to clean")

def ensure_scenario():
    """Ensure scenario.json exists."""

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

def enhanced_training_with_replay(model, total_timesteps, replay_interval=10000):
    """Enhanced training that captures replay data at intervals."""
    try:
        print(f"Enhanced training with replay capture every {replay_interval} steps")
        
        episode_replays = []
        episode_rewards = []
        episodes_captured = 0
        current_step = 0

        # Initialize progress tracker
        progress_tracker = ProgressTracker(total_timesteps)
        print(f"\n{progress_tracker.draw_timesteps_bar()}")
        print(f"{progress_tracker.draw_reward_bar()}")
        
        while current_step < total_timesteps:
            if current_step % replay_interval == 0 and current_step > 0:
                # Capture a replay episode
                print(f"Capturing replay at step {current_step}")
                
                # Run episode with replay
                episode_reward, episode_steps, replay_file = run_training_episode_with_replay(model, model.env)
                
                if replay_file:
                    episode_replays.append(replay_file)
                    episode_rewards.append(episode_reward)
                    episodes_captured += 1
                
                # Update progress tracking
                progress_tracker.update_reward(episode_reward)
                progress_tracker.update_timesteps(current_step + episode_steps)
                print(f"\n{progress_tracker.draw_timesteps_bar()}")
                print(f"{progress_tracker.draw_reward_bar()}")
                
                current_step += episode_steps
            else:
                # Regular training step
                remaining_steps = min(1000, total_timesteps - current_step)
                model.learn(total_timesteps=remaining_steps)
                current_step += remaining_steps

                # Update timesteps progress every 5k steps
                if current_step % 5000 == 0:
                    progress_tracker.update_timesteps(current_step)
                    print(f"\r{progress_tracker.draw_timesteps_bar()}", end="", flush=True)
        
        # Final training if needed
        if current_step < total_timesteps:
            model.learn(total_timesteps=total_timesteps - current_step)
        
        print(f"Training completed with {episodes_captured} replays captured")
        
        # Select best and worst replays
        if episode_replays and episode_rewards:
            best_idx = episode_rewards.index(max(episode_rewards))
            worst_idx = episode_rewards.index(min(episode_rewards))
            
            # Copy best and worst to standard locations
            event_log_dir = "ai/event_log"
            
            best_dest = os.path.join(event_log_dir, "train_best_game_replay.json")
            worst_dest = os.path.join(event_log_dir, "train_worst_game_replay.json")
            
            shutil.copy2(episode_replays[best_idx], best_dest)
            shutil.copy2(episode_replays[worst_idx], worst_dest)
            
            print(f"   Best replay (reward: {episode_rewards[best_idx]:.2f}): train_best_game_replay.json")
            print(f"   Worst replay (reward: {episode_rewards[worst_idx]:.2f}): train_worst_game_replay.json")
        
    except KeyboardInterrupt:
        print("Training interrupted - saving current progress")
        raise

def save_training_logs_with_replay(env):
    """Save training logs with full game replay data."""
    if not hasattr(env, "episode_logs") or not env.episode_logs:
        print("No episode logs to save")
        return
    
    event_log_dir = "ai/event_log"
    os.makedirs(event_log_dir, exist_ok=True)
    
    # Find best and worst episodes
    best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
    worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
    
    print(f"LOGS: Generating full game replay logs...")
    
    # Convert episode logs to web-compatible format
    def convert_to_web_format(episode_log, reward):
        """Convert episode log to web-compatible format."""
        web_replay = {
            "metadata": {
                "version": "1.0",
                "format": "web_compatible",
                "game_type": "wh40k_tactics",
                "created": datetime.now().isoformat(),
                "episode_reward": reward,
                "total_events": len(episode_log) if isinstance(episode_log, list) else 1,
                "source": "training"
            },
            "events": []
        }
        
        # Convert episode log events to web format
        if isinstance(episode_log, list):
            for i, event in enumerate(episode_log):
                web_event = {
                    "turn": event.get("turn", i + 1),
                    "type": "ai_action",
                    "timestamp": datetime.now().isoformat(),
                    "action": {
                        "type": "game_action",
                        "action_id": event.get("action", 0),
                        "reward": event.get("reward", 0.0)
                    },
                    "game_state": {
                        "turn": event.get("turn", i + 1),
                        "ai_units_alive": event.get("ai_units_alive", 2),
                        "enemy_units_alive": event.get("enemy_units_alive", 2),
                        "game_over": event.get("game_over", False)
                    },
                    "units": {
                        "ai_count": event.get("ai_units_alive", 2),
                        "enemy_count": event.get("enemy_units_alive", 2)
                    }
                }
                web_replay["events"].append(web_event)
        
        return web_replay
    
    # Generate web-compatible replays
    best_web_replay = convert_to_web_format(best_log, best_reward)
    worst_web_replay = convert_to_web_format(worst_log, worst_reward)
    
    # Save with correct filenames for frontend consumption
    best_replay_file = os.path.join(event_log_dir, "train_best_game_replay.json")
    worst_replay_file = os.path.join(event_log_dir, "train_worst_game_replay.json")
    
    with open(best_replay_file, "w", encoding="utf-8") as f:
        # use our numpy_encoder to handle int64, arrays, etc.
        json.dump(best_web_replay, f, indent=2, default=numpy_encoder)
    
    with open(worst_replay_file, "w", encoding="utf-8") as f:
        # use our numpy_encoder to handle int64, arrays, etc.
        json.dump(worst_web_replay, f, indent=2, default=numpy_encoder)
    
    print(f"   Best web replay: {best_replay_file}")
    print(f"   Worst web replay: {worst_replay_file}")
    
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
        "replay_type": "web_compatible_direct",
        "web_compatible": True,
        "output_location": "ai/event_log",
        "features": [
            "Direct web compatibility",
            "Correct file location (ai/event_log)", 
            "Standard filename (train_best_game_replay.json)",
            "No conversion needed",
            "Frontend ready"
        ]
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"   Summary: {summary_file}")
    print(f"   Web-compatible replays saved directly to ai/event_log")

def quick_test_model(model, env):
    """Quick test of trained model."""
    print("Running quick model test...")
    
    wins = 0
    total_games = 5
    
    for i in range(total_games):
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs, info = reset_result
        else:
            obs = reset_result
            
        done = False
        steps = 0
        while not done and steps < 200:
            action, _ = model.predict(obs, deterministic=True)
            step_result = env.step(action)
            
            if len(step_result) == 5:
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:
                obs, reward, done, info = step_result
            
            steps += 1
        
        # Check if AI won (basic heuristic)
        if hasattr(env, 'units'):
            ai_alive = sum(1 for u in env.units if u.get('player') == 1 and u.get('alive', True) and u.get('cur_hp', 0) > 0)
            player_alive = sum(1 for u in env.units if u.get('player') == 0 and u.get('alive', True) and u.get('cur_hp', 0) > 0)
            if ai_alive > 0 and player_alive == 0:
                wins += 1
    
    win_rate = wins / total_games
    print(f"Quick test results: {wins}/{total_games} wins ({win_rate:.1%} win rate)")
    return win_rate

def main():
    """Main training function with full features."""
    print("W40K AI Training - Complete System")
    print("=" * 50)
    
    try:
        # Parse arguments
        resume, debug, timesteps_override, config_name = parse_args()
        
        # Load configuration
        config = load_config(config_name)
        total_timesteps = timesteps_override or config.get("total_timesteps", 1000000)
        
        print(f"Configuration: {config_name}")
        print(f"Description: {config.get('description', 'No description')}")
        print(f"Total timesteps: {total_timesteps:,}")
        
        if debug:
            print("Debug mode enabled")
        
        # Ensure scenario exists
        ensure_scenario()
        
        # Set up imports
        DQN, check_env, W40KEnv = setup_imports()
        
        # Create environment
        print("Creating environment...")
        env = W40KEnv()
        
        # Validate environment
        try:
            check_env(env)
            print("Environment validation passed")
        except Exception as e:
            print(f"Environment check warning: {e}")
        
        # Display environment info
        print(f"   Units: {len(env.units) if hasattr(env, 'units') else 'Unknown'}")
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
            print("Loading existing model...")
            backup_current_model()
            model = DQN.load(model_path, env=env)
            print("Model loaded successfully")
        else:
            if os.path.exists(model_path):
                backup_current_model()
            
            print("Creating new DQN model...")
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
            print("Model created successfully")
        
        print(f"Starting training...")
        print()
        
        try:
            # Use enhanced training with replay if possible
            try:
                enhanced_training_with_replay(model, total_timesteps)
            except Exception as e:
                print(f"Enhanced replay training failed: {e}")
                print("Falling back to standard training...")
                model.learn(total_timesteps=total_timesteps)
            
        except KeyboardInterrupt:
            print("Training interrupted by user")
            model.save(model_path)
            print(f"Model saved to {model_path}")
        except Exception as e:
            print(f"Training failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Save model
        model.save(model_path)
        print(f"Model saved to {model_path}")
        
        # Save training logs
        save_training_logs_with_replay(env)
        
        # Quick test
        win_rate = quick_test_model(model, env)
        
        # Cleanup
        env.close()
        
        # Success message with fixed symbols
        print("\n" + "=" * 60)
        print("Training completed successfully!")
        print(f"\nNext Steps:")
        print(f"   Test model:       python ai/evaluate.py")
        print(f"   More training:    python ai/train.py --resume")
        print(f"   Different config: python ai/train.py --config conservative")
        print(f"   View logs:        ls ai/event_log/")
        print(f"   Web app:          cd frontend && npm run dev")
        print(f"   View replays:     python ai/replay.py")
        
        return True
        
    except KeyboardInterrupt:
        print(f"\nTraining interrupted")
        return False
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\nTraining interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)