#!/usr/bin/env python3
"""
ai/training_callbacks.py - Training callbacks for Stable-Baselines3

Contains:
- EntropyScheduleCallback: Linearly reduce entropy coefficient during training
- EpisodeTerminationCallback: Terminate training after exact episode count
- EpisodeBasedEvalCallback: Episode-counting evaluation callback
- MetricsCollectionCallback: Collect training metrics for W40KMetricsTracker
- BotEvaluationCallback: Test agent against evaluation bots with best model saving

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import time
from typing import Optional
from stable_baselines3.common.callbacks import BaseCallback

__all__ = [
    'EntropyScheduleCallback',
    'EpisodeTerminationCallback',
    'EpisodeBasedEvalCallback',
    'MetricsCollectionCallback',
    'BotEvaluationCallback'
]


class EntropyScheduleCallback(BaseCallback):
    """Callback to linearly reduce entropy coefficient during training."""

    def __init__(self, start_ent: float, end_ent: float, total_episodes: int, verbose: int = 0):
        super().__init__(verbose)
        self.start_ent = start_ent
        self.end_ent = end_ent
        self.total_episodes = total_episodes
        self.episode_count = 0
        self.last_update_step = 0

    def _on_step(self) -> bool:
        # Detect episode end using dones array (more reliable than info dict)
        if hasattr(self, 'locals') and 'dones' in self.locals:
            dones = self.locals['dones']
            # Count number of episodes that finished in this step
            episodes_finished = sum(dones) if hasattr(dones, '__iter__') else (1 if dones else 0)

            if episodes_finished > 0:
                self.episode_count += episodes_finished
                # Linear interpolation: ent = start + (end - start) * progress
                progress = min(1.0, self.episode_count / self.total_episodes)
                new_ent = self.start_ent + (self.end_ent - self.start_ent) * progress
                self.model.ent_coef = new_ent

                if self.verbose > 0 and self.num_timesteps - self.last_update_step >= 10000:
                    print(f"Episode {self.episode_count}/{self.total_episodes}: ent_coef = {new_ent:.3f}")
                    self.last_update_step = self.num_timesteps
        return True

class EpisodeTerminationCallback(BaseCallback):
    """Callback to terminate training after exact episode count."""

    def __init__(self, max_episodes: int, expected_timesteps: int, verbose: int = 0,
                 total_episodes: int = None, scenario_info: str = None,
                 disable_early_stopping: bool = False, global_start_time: float = None):
        super().__init__(verbose)
        if max_episodes <= 0:
            raise ValueError("max_episodes must be positive - no defaults allowed")
        if expected_timesteps <= 0:
            raise ValueError("expected_timesteps must be positive - no defaults allowed")
        self.max_episodes = max_episodes
        self.expected_timesteps = expected_timesteps
        self.episode_count = 0
        self.step_count = 0
        self.start_time = global_start_time  # Use provided global start time if available
        # For global progress tracking in rotation mode
        self.total_episodes = total_episodes if total_episodes else max_episodes
        self.scenario_info = scenario_info  # e.g., "Cycle 8 | Scenario: phase2-1"
        self.global_episode_offset = 0  # Set by rotation code to track overall progress
        # ROTATION FIX: Disable early stopping to let model.learn() consume all timesteps
        self.disable_early_stopping = disable_early_stopping
        # EMA for smooth ETA estimation (weights recent episodes more heavily)
        self.ema_episode_time = None
        self.last_episode_time = None
        self.ema_alpha = 0.1  # Smoothing factor (higher = more weight on recent)

    def _on_training_start(self) -> None:
        """Initialize timing on training start."""
        import time
        # Only set start_time if not already set (preserves global start time in rotation mode)
        if self.start_time is None:
            self.start_time = time.time()

    def _on_step(self) -> bool:
        """Track episodes and display progress."""
        self.step_count += 1

        # CRITICAL FIX: Detect episodes using MULTIPLE methods
        episode_ended = False

        # Method 1: Check info dicts for 'episode' key (SB3 standard)
        if hasattr(self, 'locals') and 'infos' in self.locals:
            for info in self.locals['infos']:
                if 'episode' in info:
                    episode_ended = True
                    self.episode_count += 1
                    break

        # Method 2: Check dones array (backup)
        if not episode_ended and hasattr(self, 'locals') and 'dones' in self.locals:
            if any(self.locals['dones']):
                episode_ended = True
                self.episode_count += 1

        # Method 3: Try to get episode count from environment directly (most reliable)
        if not episode_ended and hasattr(self, 'training_env'):
            try:
                if hasattr(self.training_env, 'envs') and len(self.training_env.envs) > 0:
                    env = self.training_env.envs[0]
                    # Unwrap ActionMasker/Monitor wrappers
                    while hasattr(env, 'env'):
                        env = env.env

                    if hasattr(env, 'episode_count'):
                        env_episodes = env.episode_count
                        if env_episodes > self.episode_count:
                            self.episode_count = env_episodes
                            episode_ended = True
            except Exception:
                pass

        # Update progress display on episode end
        if episode_ended:
            import time
            current_time = time.time()

            # Update progress every 10 episodes
            if self.episode_count % 10 == 0:
                # Calculate global progress (across all rotations)
                global_episode_count = self.global_episode_offset + self.episode_count
                global_progress_pct = (global_episode_count / self.total_episodes) * 100

                # Global progress bar (full width)
                bar_length = 40
                filled = int(bar_length * global_episode_count / self.total_episodes)
                bar = '█' * filled + '░' * (bar_length - filled)

                # Calculate time with EMA for smooth, accurate ETA estimates
                time_info = ""
                if self.start_time is not None and global_episode_count > 0:
                    # Total elapsed time from start
                    elapsed = current_time - self.start_time

                    # Update EMA of episode time for better ETA estimation
                    if self.last_episode_time is not None:
                        # Time for last batch of episodes (10 episodes)
                        episode_batch_time = current_time - self.last_episode_time
                        avg_time_per_episode = episode_batch_time / 10

                        if self.ema_episode_time is None:
                            # Initialize EMA with first measurement
                            self.ema_episode_time = avg_time_per_episode
                        else:
                            # Update EMA: new_ema = alpha * new_value + (1 - alpha) * old_ema
                            self.ema_episode_time = (self.ema_alpha * avg_time_per_episode +
                                                    (1 - self.ema_alpha) * self.ema_episode_time)

                    self.last_episode_time = current_time

                    # Calculate ETA using EMA (or fallback to overall average for first few episodes)
                    remaining_episodes = self.total_episodes - global_episode_count
                    if self.ema_episode_time is not None:
                        eta = self.ema_episode_time * remaining_episodes
                        eps_speed = 1.0 / self.ema_episode_time if self.ema_episode_time > 0 else 0
                    else:
                        # Fallback for early episodes
                        avg_episode_time = elapsed / global_episode_count
                        eta = avg_episode_time * remaining_episodes
                        eps_speed = global_episode_count / elapsed if elapsed > 0 else 0

                    # Format times as HH:MM:SS or MM:SS depending on duration
                    def format_time(seconds):
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        if hours > 0:
                            return f"{hours}:{minutes:02d}:{secs:02d}"
                        else:
                            return f"{minutes:02d}:{secs:02d}"

                    elapsed_str = format_time(elapsed)
                    eta_str = format_time(eta)
                    speed_str = f"{eps_speed:.2f}ep/s" if eps_speed >= 0.01 else f"{eps_speed*60:.1f}ep/m"
                    time_info = f" [{elapsed_str}<{eta_str}, {speed_str}]"

                # Build detailed scenario display with episode range
                if self.scenario_info:
                    # Calculate cycle episode range (e.g., "0-100", "100-200")
                    cycle_start = self.global_episode_offset
                    cycle_end = self.global_episode_offset + self.max_episodes
                    scenario_display = f" | {self.scenario_info} | Episodes {cycle_start}-{cycle_end}/{self.total_episodes}"
                else:
                    scenario_display = ""
                print(f"{global_progress_pct:3.0f}% {bar} {global_episode_count}/{self.total_episodes}{time_info}{scenario_display}", end='\r', flush=True)

        # CRITICAL: Stop when max episodes reached (unless disabled for rotation mode)
        if self.episode_count >= self.max_episodes:
            if self.disable_early_stopping:
                # Rotation mode: Let model.learn() consume all timesteps
                # Don't stop early - just continue tracking episodes for metrics
                return True
            else:
                # Normal mode: Stop when episode count reached
                print()  # Newline after final progress update
                print(f"🛑 STOPPING: Reached {self.max_episodes} episodes")
                print(f"   Total timesteps: {self.model.num_timesteps if hasattr(self, 'model') else 'N/A'}")
                return False

        return True

class EpisodeBasedEvalCallback(BaseCallback):
    """Episode-counting evaluation callback - triggers every N episodes, not timesteps."""

    def __init__(self, eval_env, eval_freq: int, n_eval_episodes: int = 5,
                 best_model_save_path: Optional[str] = None, log_path: Optional[str] = None,
                 deterministic: bool = True, verbose: int = 1):
        super().__init__(verbose)
        self.eval_env = eval_env
        self.eval_freq = eval_freq  # Evaluate every N episodes
        self.n_eval_episodes = n_eval_episodes
        self.best_model_save_path = best_model_save_path
        self.log_path = log_path
        self.deterministic = deterministic

        self.episode_count = 0
        self.last_eval_episode = 0
        self.best_mean_reward = -float('inf')

        # Create save directory if needed
        if best_model_save_path is not None:
            os.makedirs(best_model_save_path, exist_ok=True)

    def _on_step(self) -> bool:
        # Detect episode end
        if hasattr(self, 'locals') and 'dones' in self.locals:
            dones = self.locals['dones']
            episodes_finished = sum(dones) if hasattr(dones, '__iter__') else (1 if dones else 0)

            if episodes_finished > 0:
                self.episode_count += episodes_finished

                # Trigger evaluation every eval_freq episodes
                if self.episode_count - self.last_eval_episode >= self.eval_freq:
                    self._evaluate()
                    self.last_eval_episode = self.episode_count

        return True

    def _evaluate(self):
        """Run evaluation episodes and save best model"""
        episode_rewards = []

        for _ in range(self.n_eval_episodes):
            obs, _ = self.eval_env.reset()
            done = False
            episode_reward = 0.0

            while not done:
                action, _ = self.model.predict(obs, deterministic=self.deterministic)
                obs, reward, terminated, truncated, info = self.eval_env.step(action)
                episode_reward += reward
                done = terminated or truncated

            episode_rewards.append(episode_reward)

        mean_reward = sum(episode_rewards) / len(episode_rewards)

        if self.verbose > 0:
            print(f"Eval @ Episode {self.episode_count}: Mean Reward = {mean_reward:.2f}")

        # Save best model
        if mean_reward > self.best_mean_reward:
            self.best_mean_reward = mean_reward
            if self.best_model_save_path is not None:
                self.model.save(os.path.join(self.best_model_save_path, "best_model"))
                if self.verbose > 0:
                    print(f"New best model saved! Reward: {mean_reward:.2f}")

class MetricsCollectionCallback(BaseCallback):
    """Callback to collect training metrics and send to W40KMetricsTracker."""

    def __init__(self, metrics_tracker, scenario_name: str, verbose: int = 0):
        super().__init__(verbose)
        self.metrics_tracker = metrics_tracker
        self.scenario_name = scenario_name

        # Episode tracking
        self.episode_count = 0
        self.current_episode_reward = 0.0
        self.current_episode_length = 0

    def _on_step(self) -> bool:
        """Called at every training step"""
        # Track episode reward and length
        if hasattr(self, 'locals') and 'rewards' in self.locals:
            rewards = self.locals['rewards']
            reward = rewards[0] if hasattr(rewards, '__iter__') else rewards
            self.current_episode_reward += reward
            self.current_episode_length += 1

        # Detect episode end
        if hasattr(self, 'locals') and 'dones' in self.locals:
            dones = self.locals['dones']
            episode_ended = dones[0] if hasattr(dones, '__iter__') else dones

            if episode_ended:
                self.episode_count += 1

                # Get episode info from environment
                info = self.locals.get('infos', [{}])[0]

                # Extract AI_TURN.md compliance metrics
                metrics = {
                    'episode_reward': self.current_episode_reward,
                    'episode_length': self.current_episode_length,
                    'scenario': self.scenario_name,
                    'timestep': self.num_timesteps,
                    'episode_num': self.episode_count,
                }

                # Add AI_TURN.md compliance metrics from info dict
                if 'episode_steps' in info:
                    metrics['episode_steps'] = info['episode_steps']
                if 'total_actions' in info:
                    metrics['total_actions'] = info['total_actions']
                if 'winner' in info:
                    metrics['winner'] = info['winner']

                # Send to metrics tracker
                self.metrics_tracker.log_episode_end(metrics)

                # Reset episode tracking
                self.current_episode_reward = 0.0
                self.current_episode_length = 0

        return True

class BotEvaluationCallback(BaseCallback):
    """Callback to test agent against evaluation bots with best model saving"""

    def __init__(self, eval_freq: int, n_eval_episodes: int = 30,
                 training_config_name: str = "default", rewards_config_name: str = "default",
                 best_model_save_path: Optional[str] = None,
                 controlled_agent: Optional[str] = None, verbose: int = 1,
                 step_logger = None):
        super().__init__(verbose)
        self.eval_freq = eval_freq  # Evaluate every N episodes
        self.n_eval_episodes = n_eval_episodes
        self.training_config_name = training_config_name
        self.rewards_config_name = rewards_config_name
        self.best_model_save_path = best_model_save_path
        self.controlled_agent = controlled_agent
        self.step_logger = step_logger

        self.episode_count = 0
        self.last_eval_episode = 0
        self.best_combined_score = -float('inf')

        # Create save directory if needed
        if best_model_save_path is not None:
            os.makedirs(best_model_save_path, exist_ok=True)

    def _on_step(self) -> bool:
        # Detect episode end
        if hasattr(self, 'locals') and 'dones' in self.locals:
            dones = self.locals['dones']
            episodes_finished = sum(dones) if hasattr(dones, '__iter__') else (1 if dones else 0)

            if episodes_finished > 0:
                self.episode_count += episodes_finished

                # Trigger evaluation every eval_freq episodes
                if self.episode_count - self.last_eval_episode >= self.eval_freq:
                    self._evaluate_against_bots()
                    self.last_eval_episode = self.episode_count

        return True

    def _evaluate_against_bots(self):
        """Run bot evaluation and save best model"""
        # Lazy import to avoid circular dependency
        from ai.bot_evaluation import evaluate_against_bots

        if self.verbose > 0:
            print(f"\n🤖 Running bot evaluation @ Episode {self.episode_count}...")

        # Pause step logger during evaluation
        if self.step_logger and hasattr(self.step_logger, 'enabled'):
            original_enabled = self.step_logger.enabled
            self.step_logger.enabled = False
        else:
            original_enabled = False

        results = evaluate_against_bots(
            model=self.model,
            training_config_name=self.training_config_name,
            rewards_config_name=self.rewards_config_name,
            n_episodes=self.n_eval_episodes,
            controlled_agent=self.controlled_agent,
            show_progress=False,
        )

        # Resume step logger
        if self.step_logger and hasattr(self.step_logger, 'enabled'):
            self.step_logger.enabled = original_enabled

        # Get combined score
        combined_score = results.get('combined', 0.0)

        # Save best model based on combined score
        if combined_score > self.best_combined_score:
            self.best_combined_score = combined_score
            if self.best_model_save_path is not None:
                model_path = os.path.join(self.best_model_save_path, "best_bot_eval_model")
                self.model.save(model_path)
                if self.verbose > 0:
                    print(f"💾 New best bot eval model saved! Combined: {combined_score:.1f}%")
