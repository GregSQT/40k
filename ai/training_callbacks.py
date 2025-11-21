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
            raise ValueError(f"max_episodes must be > 0, got {max_episodes}")

        self.max_episodes = max_episodes
        self.expected_timesteps = expected_timesteps
        self.episode_count = 0
        self.total_episodes = total_episodes  # Global total across all rotations (for progress bar)
        self.scenario_info = scenario_info
        self.disable_early_stopping = disable_early_stopping
        self.global_start_time = global_start_time if global_start_time else time.time()
        self.last_progress_percent = 0

    def _on_step(self) -> bool:
        # Detect episode end using dones array
        if hasattr(self, 'locals') and 'dones' in self.locals:
            dones = self.locals['dones']
            episodes_finished = sum(dones) if hasattr(dones, '__iter__') else (1 if dones else 0)

            if episodes_finished > 0:
                self.episode_count += episodes_finished

                # Calculate progress percentage
                current_progress = int((self.episode_count / self.max_episodes) * 100)
                if current_progress >= self.last_progress_percent + 10:  # Print every 10%
                    elapsed_time = time.time() - self.global_start_time
                    elapsed_min = elapsed_time / 60
                    estimated_total = (elapsed_time / self.episode_count) * self.total_episodes if self.episode_count > 0 else 0
                    eta_min = (estimated_total - elapsed_time) / 60

                    scenario_str = f" [{self.scenario_info}]" if self.scenario_info else ""
                    print(f"  Progress: {current_progress}%{scenario_str} ({self.episode_count}/{self.max_episodes} episodes) | "
                          f"Elapsed: {elapsed_min:.1f}m | ETA: {eta_min:.1f}m")
                    self.last_progress_percent = current_progress

                # Stop when we reach max episodes
                if self.episode_count >= self.max_episodes:
                    if self.verbose > 0:
                        print(f"Reached {self.max_episodes} episodes. Stopping training.")
                    return False  # Stop training

        # EARLY STOPPING: Detect training anomalies
        if not self.disable_early_stopping and self.num_timesteps >= 100:
            # If timesteps exceed expected by 3x, training is stalling
            expected_at_this_episode = self.expected_timesteps * (self.episode_count / self.max_episodes)
            if self.num_timesteps > expected_at_this_episode * 3 and self.episode_count > 5:
                print(f"\n⚠️  EARLY STOP: Training stalled!")
                print(f"   Episodes: {self.episode_count}/{self.max_episodes}")
                print(f"   Timesteps: {self.num_timesteps} (expected ~{expected_at_this_episode:.0f})")
                print(f"   Stopping to prevent infinite loop.\n")
                return False

        return True  # Continue training

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
                self.metrics_tracker.record_episode(metrics)

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
