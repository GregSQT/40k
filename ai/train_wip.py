#!/usr/bin/env python3
# ai/train.py - Complete training script with custom progress bars and ALL original features

import os
import sys
import json
import shutil
import subprocess
import glob
from datetime import datetime
import numpy as np
import time
from stable_baselines3.common.callbacks import BaseCallback

# Progress tracking class - simplified for current session only
class ProgressTracker:
    def __init__(self, session_timesteps, bar_width=50):
        self.session_timesteps = session_timesteps  # Just this training session
        self.bar_width = bar_width
        self.current_timesteps = 0
        self.min_reward = float('inf')
        self.max_reward = float('-inf')
        self.current_reward = 0.0
        self.episode_count = 0
        self.start_time = time.time()
        
    def update_timesteps(self, timesteps):
        self.current_timesteps = min(timesteps, self.session_timesteps)
        
    def update_reward(self, reward):
        # Ensure reward is a Python float, not numpy array
        if hasattr(reward, 'item'):
            reward = reward.item()  # Convert numpy scalar to Python float
        elif hasattr(reward, '__len__') and len(reward) == 1:
            reward = float(reward[0])  # Convert single-element array to float
        else:
            reward = float(reward)  # Convert to float
            
        self.current_reward = reward
        self.min_reward = min(self.min_reward, reward)
        self.max_reward = max(self.max_reward, reward)
        self.episode_count += 1
        
    def draw_timesteps_bar(self):
        if self.session_timesteps == 0:
            progress = 0.0
        else:
            progress = self.current_timesteps / self.session_timesteps
        
        filled_length = int(self.bar_width * progress)
        bar = '█' * filled_length + '░' * (self.bar_width - filled_length)
        
        elapsed_time = time.time() - self.start_time
        # Improve ETA calculation stability
        if progress > 0.01:  # Only calculate ETA after 1% progress to avoid wild swings
            eta_seconds = (elapsed_time / progress) * (1 - progress)
            # Cap ETA at 99 hours to avoid ridiculous values
            eta_seconds = min(eta_seconds, 99 * 3600)
            eta_str = f" ETA: {int(eta_seconds//3600):02d}:{int((eta_seconds%3600)//60):02d}:{int(eta_seconds%60):02d}"
        else:
            eta_str = " ETA: calculating..."
        
        return f"Session: |{bar}| {self.current_timesteps:,}/{self.session_timesteps:,} ({progress*100:.1f}%){eta_str}"
    
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
            progress = max(0.0, min(1.0, float(progress)))  # Ensure progress is a Python float
            
            bar_chars = ['░'] * self.bar_width
            position = int(float(progress) * (self.bar_width - 1))  # Ensure position calculation uses float
            bar_chars[position] = '●'
            bar = ''.join(bar_chars)
            
    def should_update_display(self):
        """Check if display should be updated (for compatibility)"""
        current_time = time.time()
        if current_time - getattr(self, 'last_update_time', 0) > 0.5:
            self.last_update_time = current_time
            return True
        return False

# Custom callback to update progress bars - fixed for chunked training
class ProgressBarCallback(BaseCallback):
    def __init__(self, progress_tracker, update_interval=1000):
        super().__init__()
        self.progress_tracker = progress_tracker
        self.update_interval = update_interval
        self.last_display_time = 0
        self.chunk_offset = 0  # Track progress across chunks
        
    def set_chunk_offset(self, offset):
        """Set the offset for the current chunk"""
        self.chunk_offset = offset
        
    def _on_step(self) -> bool:
        # Calculate total progress across all chunks
        # self.num_timesteps is progress within current chunk
        # self.chunk_offset is total progress from previous chunks
        total_progress = self.chunk_offset + self.num_timesteps
        
        # Update timesteps progress for this session
        self.progress_tracker.update_timesteps(total_progress)
        
        # Update display every 2 seconds
        current_time = time.time()
        if current_time - self.last_display_time > 2.0:
            self._update_display()
            self.last_display_time = current_time
        
        return True
    
    def _on_rollout_end(self) -> None:
        # Get episode reward info from the training environment
        if len(self.model.ep_info_buffer) > 0:
            recent_episode = self.model.ep_info_buffer[-1]
            if 'r' in recent_episode:
                self.progress_tracker.update_reward(recent_episode['r'])
                # Update display immediately when reward changes
                self._update_display()
    
    def _update_display(self):
        """Update the progress bars by completely clearing and reprinting both lines"""
        # Clear current line and move up one line, then clear that too
        print('\r' + ' ' * 120, end='')  # Clear current line
        print('\r\033[1A' + ' ' * 120, end='')  # Move up and clear previous line
        print('\r', end='')  # Return to start of line
        
        # Print both progress bars
        timesteps_line = self.progress_tracker.draw_timesteps_bar()
        reward_line = self.progress_tracker.draw_reward_bar()
        
        # Debug: Check if reward_line is None
        if reward_line is None:
            reward_line = "Reward: DEBUG - reward_line is None!"
        
        print(timesteps_line)  # Print timesteps bar
        print(reward_line, end='', flush=True)  # Print reward bar without newline

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
    try:
        from config_loader import ConfigLoader
        loader = ConfigLoader()
        # get_training_config() returns the entire training_config.json
        all_configs = loader.get_training_config()
        
        if config_name not in all_configs:
            available = list(all_configs.keys())
            raise ValueError(f"Config '{config_name}' not found. Available: {available}")
        
        return all_configs[config_name]
    except ImportError:
        # Fallback to direct file loading
        config_path = os.path.join(project_root, "config", "training_config.json")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Training config file not found: {config_path}")
        
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

def backup_current_model():
    """Create backup before training."""
    backup_dir = "ai/models/backup"
    os.makedirs(backup_dir, exist_ok=True)
    
    model_path = "ai/model.zip"  # Main model path per file system rules
    
    if os.path.exists(model_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"model_backup_{timestamp}.zip"
        backup_path = os.path.join(backup_dir, backup_name)
        
        try:
            shutil.copy2(model_path, backup_path)
            print(f"Backed up model to {backup_path}")
            
            # Keep only last 5 backups
            backup_files = sorted([f for f in os.listdir(backup_dir) if f.startswith("model_backup_")])
            while len(backup_files) > 5:
                old_backup = backup_files.pop(0)
                os.remove(os.path.join(backup_dir, old_backup))
                print(f"Removed old backup: {old_backup}")
                
        except Exception as e:
            print(f"Warning: Could not backup model: {e}")

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
        # Fallback to regular episode without replay using WebReplayIntegration
        if not WEB_REPLAY_AVAILABLE:
            return 0.0, 0, None
        
        try:
            # Use web replay enhancement
            enhanced_env = WebReplayIntegration.enhance_training_env(env)
            
            # Run episode
            reset_result = enhanced_env.reset()
            if isinstance(reset_result, tuple):
                obs, info = reset_result
            else:
                obs = reset_result
            
            total_reward = 0.0
            steps = 0
            done = False
            
            while not done and steps < 200:  # Limit episode length
                action, _ = model.predict(obs, deterministic=False)
                step_result = enhanced_env.step(action)
                
                if len(step_result) == 5:
                    obs, reward, terminated, truncated, info = step_result
                    done = terminated or truncated
                else:
                    obs, reward, done, info = step_result
                
                total_reward += reward
                steps += 1
            
            # Save replay if available
            replay_file = None
            if hasattr(enhanced_env, 'event_log') and enhanced_env.event_log:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                replay_file = f"ai/event_log/training_replay_{timestamp}.json"
                
                os.makedirs("ai/event_log", exist_ok=True)
                with open(replay_file, 'w') as f:
                    json.dump(enhanced_env.event_log, f, default=numpy_encoder, indent=2)
            
            return total_reward, steps, replay_file
            
        except Exception as e:
            print(f"Warning: Replay capture failed: {e}")
            return 0.0, 0, None

def enhanced_training_with_replay(model, total_timesteps, progress_tracker, replay_interval=10000):
    """Enhanced training that captures replay data at intervals with custom progress bars."""
    # Use the progress_tracker passed from main() - don't create a new one
    print(f"Enhanced training with replay capture every {replay_interval} steps")
    print(f"Total timesteps: {total_timesteps:,}")  # Debug: verify correct total
    
    if not WEB_REPLAY_AVAILABLE:
        print("Web replay not available, using standard training with custom progress bars...")
        # Create callback for progress tracking
        callback = ProgressBarCallback(progress_tracker, update_interval=100000)
        model.learn(total_timesteps=total_timesteps, callback=callback)
        return
    
    try:
        episode_replays = []
        episode_rewards = []
        episodes_captured = 0
        current_step = 0

        # Initialize progress display
        print("Starting progress tracking...")
        print()  # Print empty line for timesteps bar
        print("Initializing...", end='', flush=True)  # Print placeholder for reward bar
        
        # Create callback that tracks across chunks
        callback = ProgressBarCallback(progress_tracker, update_interval=100000)
        
        while current_step < total_timesteps:
            if current_step % replay_interval == 0 and current_step > 0:
                # Run episode with replay (silent)
                episode_reward, episode_steps, replay_file = run_training_episode_with_replay(model, model.env)
                
                if replay_file:
                    episode_replays.append(replay_file)
                    episode_rewards.append(episode_reward)
                    episodes_captured += 1
                
                # Update progress tracking
                progress_tracker.update_reward(episode_reward)
                
                current_step += episode_steps
            else:
                # Regular training step with callback
                remaining_steps = min(5000, total_timesteps - current_step)
                
                # Set the chunk offset so callback knows total progress
                callback.set_chunk_offset(current_step)
                
                model.learn(total_timesteps=remaining_steps, callback=callback)
                current_step += remaining_steps
        
        # Final training if needed
        if current_step < total_timesteps:
            remaining = total_timesteps - current_step
            callback.set_chunk_offset(current_step)
            model.learn(total_timesteps=remaining, callback=callback)
        
        print(f"\nTraining completed with {episodes_captured} replays captured")
        
    except Exception as e:
        print(f"Enhanced training failed: {e}")
        print("Falling back to standard training...")
        callback = ProgressBarCallback(progress_tracker, update_interval=100000)
        model.learn(total_timesteps=total_timesteps, callback=callback)

def save_training_logs_with_replay(env):
    """Save training logs and replay data."""
    try:
        # Save episode logs if available
        if hasattr(env, "episode_logs") and env.episode_logs:
            best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
            worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
            
            event_log_dir = "ai/event_log"
            os.makedirs(event_log_dir, exist_ok=True)
            
            # Save best and worst replays
            best_replay_file = os.path.join(event_log_dir, "train_best_game_replay.json")
            worst_replay_file = os.path.join(event_log_dir, "train_worst_game_replay.json")
            
            with open(best_replay_file, "w", encoding="utf-8") as f:
                json.dump(best_log, f, indent=2, default=numpy_encoder)
            
            with open(worst_replay_file, "w", encoding="utf-8") as f:
                json.dump(worst_log, f, indent=2, default=numpy_encoder)
            
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
            print(f"Episode logs saved (best: {best_reward:.2f}, worst: {worst_reward:.2f})")
    except Exception as e:
        print(f"Warning: Could not save training logs: {e}")

def quick_test_model(model, env, num_episodes=3):
    """Quick test of trained model."""
    print("Running quick model test...")
    
    total_reward = 0
    wins = 0
    
    for episode in range(num_episodes):
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs, info = reset_result
        else:
            obs = reset_result
        
        episode_reward = 0
        done = False
        steps = 0
        
        while not done and steps < 100:
            action, _ = model.predict(obs, deterministic=True)
            step_result = env.step(action)
            
            if len(step_result) == 5:
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:
                obs, reward, done, info = step_result
            
            episode_reward += reward
            steps += 1
        
        total_reward += episode_reward
        if episode_reward > 0:
            wins += 1
        
        print(f"  Episode {episode + 1}: {episode_reward:.2f} reward, {steps} steps")
    
    avg_reward = total_reward / num_episodes
    win_rate = wins / num_episodes
    
    print(f"Test results: {avg_reward:.2f} avg reward, {win_rate:.1%} win rate")
    return win_rate

def main():
    """Main training function with custom progress bars and ALL original features."""
    print("W40K AI Training - Custom Progress Display")
    print("=" * 60)
    
    # Parse arguments (preserves ALL original argument handling)
    resume, debug, timesteps, config_name = parse_args()
    
    # Load configuration
    config = load_config(config_name)
    total_timesteps = timesteps if timesteps else config.get("total_timesteps", 100000)
    
    # Debug: Print config values
    print(f"Config loaded: {config_name}")
    print(f"Config total_timesteps: {config.get('total_timesteps', 'NOT FOUND')}")
    print(f"Timesteps override: {timesteps}")
    print(f"Final total_timesteps: {total_timesteps}")
    
    if debug:
        total_timesteps = min(50000, total_timesteps)
        print("Debug mode: Limited to 50,000 timesteps")
    
    print(f"Using config: {config_name}")
    print(f"Training for {total_timesteps:,} timesteps")
    
    # Set up imports
    try:
        DQN, check_env, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"Import error: {e}")
        return False
    
    # Ensure scenario exists
    ensure_scenario()
    
    # Create environment
    print("Creating environment...")
    env = W40KEnv()
    
    try:
        check_env(env)
        print("Environment validation passed")
    except Exception as e:
        print(f"Environment validation warning: {e}")
    
    print(f"Environment: {len(env.units)} units, {env.action_space.n} actions")
    
    # Set up model path (following file system rules)
    model_path = "ai/model.zip"  # Never change this path per instructions
    
    # Handle resume logic
    if resume is None:
        resume = os.path.exists(model_path)
    
    if resume and os.path.exists(model_path):
        print("Loading existing model...")
        backup_current_model()
        model = DQN.load(model_path, env=env)
        # Apply verbose setting from config to override saved model setting
        model_params = config.get("model_params", {})
        if "verbose" in model_params:
            model.verbose = model_params["verbose"]
        print(f"Model loaded successfully (previous timesteps: {getattr(model, 'num_timesteps', 0)})")
    else:
        if os.path.exists(model_path):
            backup_current_model()
        
        print("Creating new DQN model...")
        # Use model_params from config - they already include verbose=0
        model_params = config.get("model_params", {})
        model = DQN(
            env=env,
            **model_params  # Use all parameters from config including verbose=0
        )
        print("Model created successfully")
    
    print(f"Starting training...")
    print("Monitor with: tensorboard --logdir ./tensorboard/")
    print()
    
    # Initialize progress tracker
    progress_tracker = ProgressTracker(total_timesteps)
    
    try:
        # Use enhanced training with custom progress bars (preserves ALL original functionality)
        enhanced_training_with_replay(model, total_timesteps, progress_tracker)
        
    except KeyboardInterrupt:
        print("\nTraining interrupted by user")
        model.save(model_path)
        print(f"Model saved to {model_path}")
    except Exception as e:
        print(f"\nTraining failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    model.save(model_path)
    print(f"\nModel saved to {model_path}")
    
    # Save training logs (preserves ALL original functionality)
    save_training_logs_with_replay(env)
    
    # Quick test (preserves original functionality)
    win_rate = quick_test_model(model, env)
    
    # Cleanup
    env.close()
    
    # Success message
    print("\n" + "=" * 60)
    print("Training completed successfully!")
    print(f"Final win rate: {win_rate:.1%}")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)