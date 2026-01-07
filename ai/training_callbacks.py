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
import numpy as np
import torch
from typing import Dict, Optional
from stable_baselines3.common.callbacks import BaseCallback

# Import evaluation bots for testing - flag used by print_final_training_summary
try:
    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
    EVALUATION_BOTS_AVAILABLE = True
except ImportError:
    EVALUATION_BOTS_AVAILABLE = False

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

        # Detect episodes using MULTIPLE methods
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

            # Calculate global progress (across all rotations)
            global_episode_count = self.global_episode_offset + self.episode_count

            # Update progress every 10 episodes (use GLOBAL count, not local)
            if global_episode_count % 10 == 0 or global_episode_count == 1:
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

                # Build detailed scenario display
                if self.scenario_info:
                    scenario_display = f" | {self.scenario_info}"
                else:
                    scenario_display = ""
                # Use \r for overwriting progress, but add spaces to clear previous longer lines
                progress_line = f"{global_progress_pct:3.0f}% {bar} {global_episode_count}/{self.total_episodes}{time_info}{scenario_display}"
                print(f"\r{progress_line:<100}", end='', flush=True)

        # CRITICAL: Stop when max episodes reached (unless disabled for rotation mode)
        if self.episode_count >= self.max_episodes:
            if self.disable_early_stopping:
                # Rotation mode: Let model.learn() consume all timesteps
                # Don't stop early - just continue tracking episodes for metrics
                return True
            else:
                # Normal mode: Stop when episode count reached (silent for rotation training)
                return False

        return True

class EpisodeBasedEvalCallback(BaseCallback):
    """Episode-counting evaluation callback - triggers every N episodes, not timesteps."""
    
    def __init__(self, eval_env, episodes_per_eval=10, n_eval_episodes=5, 
                 best_model_save_path=None, log_path=None, deterministic=True, verbose=0):
        super().__init__(verbose)
        self.eval_env = eval_env
        self.episodes_per_eval = episodes_per_eval
        self.n_eval_episodes = n_eval_episodes
        self.best_model_save_path = best_model_save_path
        self.log_path = log_path
        self.deterministic = deterministic
        
        # Episode tracking
        self.episode_count = 0
        self.last_eval_episode = 0
        self.best_mean_reward = -float('inf')
        self.win_rate_history = []
        self.loss_history = []
        self.q_value_history = []
        self.gradient_norm_history = []
        self.max_history = 20  # Keep last 20 evaluations for smoothing
        self.max_loss_history = 100  # Keep more loss values for better smoothing
        
    def _on_step(self) -> bool:
        # Track training metrics for smoothing
        if hasattr(self.model, 'logger') and hasattr(self.model.logger, 'name_to_value'):
            logger_data = self.model.logger.name_to_value
            
            # Track loss
            if 'train/loss' in logger_data:
                current_loss = logger_data['train/loss']
                self.loss_history.append(current_loss)
                if len(self.loss_history) > self.max_loss_history:
                    self.loss_history.pop(0)
                
                if len(self.loss_history) > 5:
                    loss_mean = sum(self.loss_history) / len(self.loss_history)
                    self.model.logger.record("train/loss_mean", loss_mean)
            
            # Track Q-values if available
            if hasattr(self.model, 'q_net') and hasattr(self, 'locals') and 'obs' in self.locals:
                try:
                    import torch
                    obs_tensor = torch.FloatTensor(self.locals['obs']).to(self.model.device)
                    with torch.no_grad():
                        q_values = self.model.q_net(obs_tensor)
                        mean_q_value = q_values.mean().item()
                        self.q_value_history.append(mean_q_value)
                        if len(self.q_value_history) > self.max_loss_history:
                            self.q_value_history.pop(0)
                        
                        if len(self.q_value_history) > 5:
                            q_value_mean = sum(self.q_value_history) / len(self.q_value_history)
                            self.model.logger.record("train/q_value_mean", q_value_mean)
                except Exception:
                    pass  # Q-value tracking is optional
            
            # Track gradient norm if available
            if hasattr(self.model, 'policy') and hasattr(self.model.policy, 'parameters'):
                try:
                    total_norm = 0.0
                    param_count = 0
                    for p in self.model.policy.parameters():
                        if p.grad is not None:
                            param_norm = p.grad.data.norm(2)
                            total_norm += param_norm.item() ** 2
                            param_count += 1
                    
                    if param_count > 0:
                        gradient_norm = (total_norm ** 0.5)
                        self.gradient_norm_history.append(gradient_norm)
                        if len(self.gradient_norm_history) > self.max_loss_history:
                            self.gradient_norm_history.pop(0)
                        
                        if len(self.gradient_norm_history) > 5:
                            grad_norm_mean = sum(self.gradient_norm_history) / len(self.gradient_norm_history)
                            self.model.logger.record("train/gradient_norm", grad_norm_mean)
                except Exception:
                    pass  # Gradient tracking is optional
            
            # Dump all metrics
            if len(self.loss_history) > 5:
                self.model.logger.dump(step=self.model.num_timesteps)
        
        # Check for episode completion
        if hasattr(self, 'locals') and 'dones' in self.locals and 'infos' in self.locals:
            for i, done in enumerate(self.locals['dones']):
                if done and i < len(self.locals['infos']):
                    info = self.locals['infos'][i]
                    if 'episode' in info:
                        self.episode_count += 1
                        
                        # Check if it's time for evaluation
                        episodes_since_eval = self.episode_count - self.last_eval_episode
                        if episodes_since_eval >= self.episodes_per_eval:
                            self._run_evaluation()
                            self.last_eval_episode = self.episode_count
                            
        return True
    
    def _run_evaluation(self):
        """Run evaluation episodes and log results to tensorboard."""
        episode_rewards = []
        episode_lengths = []
        wins = 0
        
        for eval_episode in range(self.n_eval_episodes):
            obs, info = self.eval_env.reset()
            episode_reward = 0
            episode_length = 0
            done = False
            final_info = None
            
            while not done and episode_length < 1000:  # Prevent infinite loops
                action, _ = self.model.predict(obs, deterministic=self.deterministic)
                obs, reward, terminated, truncated, info = self.eval_env.step(action)
                episode_reward += reward
                episode_length += 1
                done = terminated or truncated
                if done:
                    final_info = info
            
            episode_rewards.append(episode_reward)
            episode_lengths.append(episode_length)

            # Track wins - CRITICAL FIX: Learning agent is Player 0, not Player 1!
            if final_info and final_info.get('winner') == 0:
                wins += 1
        
        # Calculate statistics
        mean_reward = sum(episode_rewards) / len(episode_rewards)
        mean_ep_length = sum(episode_lengths) / len(episode_lengths)
        win_rate = wins / self.n_eval_episodes if self.n_eval_episodes > 0 else 0.0
        
        # Track win rate history for smoothing
        self.win_rate_history.append(win_rate)
        if len(self.win_rate_history) > self.max_history:
            self.win_rate_history.pop(0)
        
        # Calculate smoothed win rate (mean of recent evaluations)
        win_rate_mean = sum(self.win_rate_history) / len(self.win_rate_history)
        
        # Log to model's tensorboard logger directly
        if hasattr(self.model, 'logger') and self.model.logger:
            self.model.logger.record("eval/mean_reward", mean_reward)
            self.model.logger.record("eval/mean_ep_length", mean_ep_length)
            self.model.logger.record("eval/win_rate", win_rate)
            self.model.logger.record("eval/win_rate_mean", win_rate_mean)
            self.model.logger.record("eval/episode", self.episode_count)
            self.model.logger.dump(step=self.model.num_timesteps)
        else:
            # Fallback to callback logger
            self.logger.record("eval/mean_reward", mean_reward)
            self.logger.record("eval/mean_ep_length", mean_ep_length)
            self.logger.record("eval/win_rate", win_rate)
            self.logger.dump(step=self.num_timesteps)
        
        # if self.verbose > 0:
            # print(f"Episode {self.episode_count}: Eval mean reward: {mean_reward:.2f}, Win rate: {win_rate:.1%}")
        
        # Save best model
        if mean_reward > self.best_mean_reward:
            self.best_mean_reward = mean_reward
            if self.best_model_save_path:
                self.model.save(f"{self.best_model_save_path}/best_model")
        
        # if self.verbose > 0:
            # print(f"Episode {self.episode_count}: Eval mean reward: {mean_reward:.2f}")


class MetricsCollectionCallback(BaseCallback):
    """Callback to collect training metrics and send to W40KMetricsTracker."""
    
    def __init__(self, metrics_tracker, model, controlled_agent=None, verbose: int = 0):
        super().__init__(verbose)
        self.metrics_tracker = metrics_tracker
        self.model = model
        self.controlled_agent = controlled_agent  # CRITICAL FIX: Store controlled_agent for bot evaluation
        self.episode_count = 0
        self.episode_reward = 0
        self.episode_length = 0
        
        # Initialize episode tracking with ALL metrics
        self.episode_tactical_data = {
            # Combat metrics
            'shots_fired': 0,
            'hits': 0,
            'total_enemies': 0,
            'killed_enemies': 0,
            
            # NEW: Damage tracking
            'damage_dealt': 0,
            'damage_received': 0,
            
            # NEW: Unit tracking
            'units_lost': 0,
            'units_killed': 0,
            
            # NEW: Action tracking
            'valid_actions': 0,
            'invalid_actions': 0,
            'wait_actions': 0,
            'total_actions': 0,
            
            # Phase tracking
            'phases_completed': 0,
            'total_phases': 6
        }
        
        # Track initial unit state for damage/loss calculations
        self.initial_agent_units = []
        self.initial_enemy_units = []
        
        # Add immediate reward ratio history for smoothing
        self.immediate_reward_ratio_history = []
        self.max_reward_ratio_history = 50  # Keep last 50 episodes
        
        # Q-value tracking with history
        self.q_value_history = []
        self.max_q_value_history = 100  # Keep last 100 Q-value samples
    
    def _on_training_start(self) -> None:
        """Called when training starts."""
        # DO NOT redirect writer to SB3's directory!
        # SB3 creates new subdirectories (_1, _2, etc.) on each learn() call
        # This would fragment our metrics across multiple directories
        # Keep using metrics_tracker's original directory for all metrics
        pass

    def _on_rollout_start(self) -> None:
        """Called at start of rollout - capture training metrics from PREVIOUS policy update.

        SB3 flow: rollout -> train() -> rollout -> train() -> ...
        The train() metrics are available at the START of the next rollout.
        """
        if hasattr(self.model, 'logger') and hasattr(self.model.logger, 'name_to_value'):
            model_stats = self.model.logger.name_to_value

            if len(model_stats) > 0:
                # Pass complete model stats to metrics tracker
                self.metrics_tracker.log_training_metrics(model_stats)
                self.metrics_tracker.step_count = self.model.num_timesteps
    
    def print_final_training_summary(self, model=None, training_config=None, training_config_name=None, rewards_config_name=None):
        """Print comprehensive training summary with final bot evaluation"""
        
        print("\n" + "="*80)
        print("🎯 TRAINING COMPLETE - RUNNING FINAL EVALUATION")
        print("="*80)
        
        if EVALUATION_BOTS_AVAILABLE and model and training_config and training_config_name and rewards_config_name:
            # Extract n_episodes from config
            if 'callback_params' not in training_config:
                raise KeyError("training_config missing required 'callback_params' field")
            if 'bot_eval_final' not in training_config['callback_params']:
                raise KeyError("training_config['callback_params'] missing required 'bot_eval_final' field")
            n_final = training_config['callback_params']['bot_eval_final']
            
            bot_results = self._run_final_bot_eval(model, training_config, training_config_name, rewards_config_name)
            
            if bot_results:
                # Log to metrics_tracker for TensorBoard
                if hasattr(self, 'metrics_tracker') and self.metrics_tracker:
                    self.metrics_tracker.log_bot_evaluations(bot_results)
                    # Flush to ensure metrics are written immediately
                    self.metrics_tracker.writer.flush()
                
                # Print results
                print(f"vs RandomBot:     {bot_results['random']:.2f} ({bot_results['random_wins']}/{n_final} wins)")
                print(f"vs GreedyBot:     {bot_results['greedy']:.2f} ({bot_results['greedy_wins']}/{n_final} wins)")
                print(f"vs DefensiveBot:  {bot_results['defensive']:.2f} ({bot_results['defensive_wins']}/{n_final} wins)")
                print(f"\nCombined Score:   {bot_results['combined']:.2f} {'✅' if bot_results['combined'] >= 0.70 else '⚠️'}")
        
        # Critical metrics check
        print(f"\n📊 CRITICAL METRICS:")
        
        # Check clip_fraction
        if len(self.metrics_tracker.hyperparameter_tracking['clip_fractions']) >= 20:
            recent_clip = np.mean(self.metrics_tracker.hyperparameter_tracking['clip_fractions'][-20:])
            clip_status = "✅" if 0.1 <= recent_clip <= 0.3 else "⚠️ "
            print(f"   Clip Fraction:      {recent_clip:.3f} {clip_status} (target: 0.1-0.3)")
            if recent_clip < 0.1:
                print(f"      ->  Increase learning_rate (policy not updating enough)")
            elif recent_clip > 0.3:
                print(f"      -> Decrease learning_rate (too aggressive updates)")
        
        # Check explained_variance
        if len(self.metrics_tracker.hyperparameter_tracking['explained_variances']) >= 20:
            recent_ev = np.mean(self.metrics_tracker.hyperparameter_tracking['explained_variances'][-20:])
            ev_status = "✅" if recent_ev > 0.3 else "⚠️ "
            print(f"   Explained Variance: {recent_ev:.3f} {ev_status} (target: >0.3)")
            if recent_ev < 0.3:
                print(f"      -> Value function struggling - check reward signal")
        
        # Check entropy
        if len(self.metrics_tracker.hyperparameter_tracking['entropy_losses']) >= 20:
            recent_entropy = np.mean(self.metrics_tracker.hyperparameter_tracking['entropy_losses'][-20:])
            entropy_status = "✅" if 0.5 <= recent_entropy <= 2.0 else "⚠️ "
            print(f"   Entropy Loss:       {recent_entropy:.3f} {entropy_status} (target: 0.5-2.0)")
            if recent_entropy < 0.5:
                print(f"      -> Increase ent_coef (exploration too low)")
            elif recent_entropy > 2.0:
                print(f"      -> Decrease ent_coef (exploration too high)")
        
        # Check gradient_norm
        if hasattr(self.metrics_tracker, 'latest_gradient_norm') and self.metrics_tracker.latest_gradient_norm:
            grad_norm = self.metrics_tracker.latest_gradient_norm
            grad_status = "✅" if grad_norm < 10 else "⚠️ "
            print(f"   Gradient Norm:      {grad_norm:.3f} {grad_status} (target: <10)")
            if grad_norm > 10:
                print(f"      -> Reduce max_grad_norm or learning_rate")
        
        print(f"\n💡 TensorBoard: {self.metrics_tracker.log_dir}")
        print(f"   -> Focus on 0_critical/ namespace for hyperparameter tuning")
        print("="*80 + "\n")
    
    def _run_final_bot_eval(self, model, training_config, training_config_name, rewards_config_name):
        """Run final comprehensive bot evaluation using standalone function"""
        # Lazy import to avoid circular dependency
        from ai.bot_evaluation import evaluate_against_bots

        controlled_agent = self.controlled_agent  # CRITICAL FIX: Use stored controlled_agent instead of looking in training_config

        # Extract n_episodes from callback_params in training_config
        if 'callback_params' not in training_config:
            raise KeyError("training_config missing required 'callback_params' field")
        if 'bot_eval_final' not in training_config['callback_params']:
            raise KeyError("training_config['callback_params'] missing required 'bot_eval_final' field")
        n_episodes = training_config['callback_params']['bot_eval_final']

        # Use standalone function with progress bar for final eval
        return evaluate_against_bots(
            model=model,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            n_episodes=n_episodes,
            controlled_agent=controlled_agent,
            show_progress=True,
            deterministic=True
        )
    
    def _on_step(self) -> bool:
        """Collect step-level data including actions, damage, and unit changes"""
        # Track step-level reward and length
        if hasattr(self, 'locals'):
            if 'rewards' in self.locals:
                reward = self.locals['rewards'][0] if isinstance(self.locals['rewards'], (list, np.ndarray)) else self.locals['rewards']
                self.episode_reward += reward

            self.episode_length += 1

            # Process info dict for action tracking
            if 'infos' in self.locals:
                for idx, info in enumerate(self.locals['infos']):
                    # Track action validity
                    if 'success' in info:
                        if info['success']:
                            self.episode_tactical_data['valid_actions'] += 1
                        else:
                            self.episode_tactical_data['invalid_actions'] += 1

                        self.episode_tactical_data['total_actions'] += 1

                    # Track wait actions (action type in info)
                    if info.get('action') == 'wait' or info.get('action') == 'skip':
                        self.episode_tactical_data['wait_actions'] += 1

                    # Track damage from combat results
                    if 'totalDamage' in info:
                        damage_dealt = info.get('totalDamage', 0)
                        self.episode_tactical_data['damage_dealt'] += damage_dealt

                    # COMBAT KILL TRACKING: Log kills to metrics tracker
                    if info.get('target_died', False):
                        phase = info.get('phase', 'unknown')
                        if phase == 'shoot':
                            self.metrics_tracker.log_combat_kill('shoot')
                        elif phase == 'fight':
                            self.metrics_tracker.log_combat_kill('melee')
                        elif phase == 'charge':
                            # Charge phase kills (rare but possible)
                            self.metrics_tracker.log_combat_kill('melee')

                    # CHARGE SUCCESS TRACKING: Log successful charges
                    if info.get('charge_succeeded', False):
                        self.metrics_tracker.log_combat_kill('charge')

                    # Handle episode end - check for 'episode' key (Monitor wrapper adds this)
                    if 'episode' in info:
                        self._handle_episode_end(info)
        
        # NEW: Collect reward decomposition from game_state
        if hasattr(self.training_env, 'envs') and len(self.training_env.envs) > 0:
            env = self.training_env.envs[0]
            
            if hasattr(env, 'unwrapped') and hasattr(env.unwrapped, 'game_state'):
                game_state = env.unwrapped.game_state
                
                # Collect reward breakdown if available
                if 'last_reward_breakdown' in game_state:
                    reward_breakdown = game_state['last_reward_breakdown']
                    
                    # Accumulate reward components for episode
                    if not hasattr(self, 'episode_reward_components'):
                        self.episode_reward_components = {
                            'base_actions': 0.0,
                            'result_bonuses': 0.0,
                            'tactical_bonuses': 0.0,
                            'situational': 0.0,
                            'penalties': 0.0
                        }
                    
                    self.episode_reward_components['base_actions'] += reward_breakdown.get('base_actions', 0.0)
                    self.episode_reward_components['result_bonuses'] += reward_breakdown.get('result_bonuses', 0.0)
                    self.episode_reward_components['tactical_bonuses'] += reward_breakdown.get('tactical_bonuses', 0.0)
                    self.episode_reward_components['situational'] += reward_breakdown.get('situational', 0.0)
                    self.episode_reward_components['penalties'] += reward_breakdown.get('penalties', 0.0)

                    # Log position_score if available (Phase 2+ movement metric)
                    if 'position_score' in reward_breakdown and self.metrics_tracker:
                        self.metrics_tracker.log_position_score(reward_breakdown['position_score'])

                    # Clear breakdown from game_state to avoid double-counting
                    del game_state['last_reward_breakdown']
        
        # Simple Q-value tracking every 100 steps
        if self.model.num_timesteps % 100 == 0 and hasattr(self.model, 'q_net'):
            try:
                # Use a simple dummy observation if locals not available
                if hasattr(self, 'locals') and 'obs' in self.locals:
                    obs_tensor = torch.FloatTensor(self.locals['obs']).to(self.model.device)
                else:
                    # Create dummy observation matching env observation space
                    dummy_obs = torch.zeros((1, self.model.observation_space.shape[0])).to(self.model.device)
                    obs_tensor = dummy_obs
                
                with torch.no_grad():
                    q_values = self.model.q_net(obs_tensor)
                    mean_q_value = q_values.mean().item()
                    
                    # Track history
                    self.q_value_history.append(mean_q_value)
                    if len(self.q_value_history) > self.max_q_value_history:
                        self.q_value_history.pop(0)
                    
                    # Calculate smoothed mean
                    q_value_mean = sum(self.q_value_history) / len(self.q_value_history)
                    
                    # Log single metrics
                    if hasattr(self.model, 'logger') and self.model.logger:
                        self.model.logger.record('train/q_value_mean_smooth', q_value_mean)
                        self.model.logger.dump(step=self.model.num_timesteps)
            except Exception as e:
                pass  # Q-value tracking is optional
        
        # Log training step data
        step_data = {}
        if hasattr(self.model, 'learning_rate'):
            # learning_rate may be a callable schedule function - evaluate it
            lr = self.model.learning_rate
            if callable(lr):
                # Call with current progress (1.0 at start, 0.0 at end)
                step_data['learning_rate'] = lr(self.model._current_progress_remaining if hasattr(self.model, '_current_progress_remaining') else 1.0)
            else:
                step_data['learning_rate'] = lr
        if hasattr(self.model, 'logger') and hasattr(self.model.logger, 'name_to_value'):
            if 'train/loss' in self.model.logger.name_to_value:
                step_data['loss'] = self.model.logger.name_to_value['train/loss']
        if hasattr(self.model, 'exploration_rate'):
            step_data['exploration_rate'] = self.model.exploration_rate
        
        if step_data:
            self.metrics_tracker.log_training_step(step_data)
        
        # NOTE: PPO training metrics are captured in _on_rollout_start()
        # SB3 only populates model.logger.name_to_value during train() which happens BETWEEN rollouts
        
        return True
    
    def _handle_episode_end(self, info):
        """Handle episode completion and log metrics."""
        self.episode_count += 1

        # CRITICAL: Update step_count BEFORE logging episode metrics
        # This ensures 0_critical/ metrics use timesteps (not episodes) as x-axis
        self.metrics_tracker.step_count = self.model.num_timesteps

        # Extract episode data
        episode_data = {
            'total_reward': info.get('episode_reward', self.episode_reward),
            'episode_length': info.get('episode_length', self.episode_length),
            'winner': info.get('winner', None)
        }

        # GAMMA MONITORING: Track discount factor effects
        if hasattr(self.model, 'gamma'):
            gamma = self.model.gamma
           
            # Calculate temporal metrics
            immediate_reward_ratio = self._calculate_immediate_vs_future_ratio(info)
            planning_horizon = self._estimate_planning_horizon(gamma)
           
            # Track ratio history for smoothing
            self.immediate_reward_ratio_history.append(immediate_reward_ratio)
            if len(self.immediate_reward_ratio_history) > self.max_reward_ratio_history:
                self.immediate_reward_ratio_history.pop(0)
           
            # Calculate smoothed mean
            ratio_mean = sum(self.immediate_reward_ratio_history) / len(self.immediate_reward_ratio_history)
           
            # Log gamma-related metrics
            if hasattr(self.model, 'logger') and self.model.logger:
                self.model.logger.record('config/discount_factor', gamma)
                self.model.logger.record('config/immediate_reward_ratio', immediate_reward_ratio)
                self.model.logger.record('config/immediate_reward_ratio_mean', ratio_mean)
                self.model.logger.record('config/planning_horizon', planning_horizon)
                # Force tensorboard dump to ensure gamma metrics are written
                self.model.logger.dump(step=self.model.num_timesteps)
       
        # CRITICAL: Use tactical_data from engine (populated during episode)
        if 'tactical_data' in info:
            # Engine provides complete tactical data - use it directly
            self.episode_tactical_data.update(info['tactical_data'])

            # Log controlled objectives ONLY if game completed turn 5 (turn limit reached)
            # Early termination (elimination) should not log objectives
            # The 'turn_limit_reached' flag is set by fight_handlers when game ends due to turn limit
            turn_limit_reached = info.get('turn_limit_reached', False)
            if turn_limit_reached:
                controlled_objectives = info['tactical_data'].get('controlled_objectives', 0)
                self.metrics_tracker.log_controlled_objectives(controlled_objectives)
            else:
                # Game ended early (elimination) - skip objective logging
                self.metrics_tracker.skip_controlled_objectives_logging()

        # Log to metrics tracker (KEEP for state tracking)
        self.metrics_tracker.log_episode_end(episode_data)
        self.metrics_tracker.log_tactical_metrics(self.episode_tactical_data)
        
        # CRITICAL FIX: Write game_critical metrics directly to model.logger
        # This ensures metrics appear in same TensorBoard directory as train/ metrics
        if hasattr(self.model, 'logger') and self.model.logger:
            total_reward = episode_data.get('total_reward', 0)
            episode_length = episode_data.get('episode_length', 0)
            winner = episode_data.get('winner', None)
            
            # Game critical metrics
            self.model.logger.record('game_critical/episode_reward', total_reward)
            self.model.logger.record('game_critical/episode_length', episode_length)
            
            # Win rate calculation (need rolling window)
            if not hasattr(self, 'win_rate_window'):
                from collections import deque
                self.win_rate_window = deque(maxlen=100)
            
            if winner is not None:
                # CRITICAL FIX: Learning agent is Player 0, not Player 1!
                agent_won = 1.0 if winner == 0 else 0.0
                self.win_rate_window.append(agent_won)

                if len(self.win_rate_window) >= 10:
                    import numpy as np
                    rolling_win_rate = np.mean(self.win_rate_window)
                    self.model.logger.record('game_critical/win_rate_100ep', rolling_win_rate)
            
            # Tactical metrics
            units_killed = self.episode_tactical_data.get('units_killed', 0)
            units_lost = max(self.episode_tactical_data.get('units_lost', 0), 1)  # Avoid division by zero
            kill_loss_ratio = units_killed / units_lost
            self.model.logger.record('game_critical/units_killed_vs_lost_ratio', kill_loss_ratio)
            
            # Invalid action rate
            total_actions = self.episode_tactical_data.get('total_actions', 0)
            if total_actions > 0:
                invalid_rate = self.episode_tactical_data.get('invalid_actions', 0) / total_actions
                self.model.logger.record('game_critical/invalid_action_rate', invalid_rate)
            
            # Dump metrics to TensorBoard
            self.model.logger.dump(step=self.model.num_timesteps)
        
        # NEW: Log reward decomposition
        if hasattr(self, 'episode_reward_components'):
            self.metrics_tracker.log_reward_decomposition(self.episode_reward_components)
            # Reset for next episode
            self.episode_reward_components = {
                'base_actions': 0.0,
                'result_bonuses': 0.0,
                'tactical_bonuses': 0.0,
                'situational': 0.0,
                'penalties': 0.0
            }
       
        # Reset episode tracking with ALL fields
        self.episode_reward = 0
        self.episode_length = 0
        self.episode_tactical_data = {
            # Combat metrics
            'shots_fired': 0,
            'hits': 0,
            'total_enemies': 0,
            'killed_enemies': 0,
            
            # Damage tracking
            'damage_dealt': 0,
            'damage_received': 0,
            
            # Unit tracking
            'units_lost': 0,
            'units_killed': 0,
            
            # Action tracking
            'valid_actions': 0,
            'invalid_actions': 0,
            'wait_actions': 0,
            'total_actions': 0,
            
            # Phase tracking
            'phases_completed': 0,
            'total_phases': 6
        }
    
    def _calculate_immediate_vs_future_ratio(self, info):
        """Calculate ratio of immediate vs future-oriented actions"""
        # Analyze action patterns to detect myopic vs strategic behavior
        immediate_actions = 0  # Shooting, direct attacks
        future_actions = 0     # Movement, positioning
        
        if hasattr(self.training_env, 'envs') and len(self.training_env.envs) > 0:
            env = self.training_env.envs[0]
            if hasattr(env, 'unwrapped') and hasattr(env.unwrapped, 'game_state'):
                action_logs = env.unwrapped.game_state.get('action_logs', [])
                
                for log in action_logs:
                    action_type = log.get('type', '')
                    if action_type in ['shoot', 'combat']:
                        immediate_actions += 1
                    elif action_type in ['move', 'wait']:
                        future_actions += 1
        
        total_actions = immediate_actions + future_actions
        return immediate_actions / max(1, total_actions)
    
    def _estimate_planning_horizon(self, gamma):
        """Estimate effective planning horizon from discount factor"""
        # Planning horizon = how many turns ahead agent effectively considers
        # Formula: horizon ≈ 1 / (1 - gamma)
        if gamma >= 0.99:
            return float('inf')  # Very long-term planning
        else:
            return 1.0 / (1.0 - gamma)


class BotEvaluationCallback(BaseCallback):
    """Callback to test agent against evaluation bots with best model saving"""

    def __init__(self, eval_freq: int = 5000, n_eval_episodes: int = 20,
                 best_model_save_path: str = None, metrics_tracker=None,
                 use_episode_freq: bool = False, verbose: int = 1):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.n_eval_episodes = n_eval_episodes
        self.best_model_save_path = best_model_save_path
        self.metrics_tracker = metrics_tracker  # Store metrics_tracker reference
        self.use_episode_freq = use_episode_freq  # True = episodes, False = timesteps
        self.last_eval_episode = 0  # Track last episode we evaluated at
        self.best_combined_win_rate = 0.0  # Track best performance

        if EVALUATION_BOTS_AVAILABLE:
            # Initialize bots with stochasticity to prevent overfitting (15% random actions)
            self.bots = {
                'random': RandomBot(),
                'greedy': GreedyBot(randomness=0.15),
                'defensive': DefensiveBot(randomness=0.15)
            }
        else:
            self.bots = {}

    def _on_step(self) -> bool:
        if not EVALUATION_BOTS_AVAILABLE:
            return True

        # Determine if we should evaluate based on mode
        should_evaluate = False
        if self.use_episode_freq:
            # Episode-based evaluation
            if self.metrics_tracker:
                current_episode = self.metrics_tracker.episode_count
                # Evaluate every eval_freq episodes, but only once per episode
                if current_episode > 0 and current_episode % self.eval_freq == 0 and current_episode != self.last_eval_episode:
                    should_evaluate = True
                    self.last_eval_episode = current_episode
        else:
            # Timestep-based evaluation (original behavior)
            if self.num_timesteps % self.eval_freq == 0:
                should_evaluate = True

        if should_evaluate:
            results = self._evaluate_against_bots()

            # Calculate combined performance (weighted average)
            # IMPROVED weighting: RandomBot 35%, GreedyBot 30%, DefensiveBot 35%
            # Increased RandomBot weight to prevent overfitting to predictable patterns
            combined_win_rate = (
                results.get('random', 0) * 0.35 +
                results.get('greedy', 0) * 0.30 +
                results.get('defensive', 0) * 0.35
            )

            # Log to metrics_tracker (0_critical/ and bot_eval/ namespaces)
            if self.metrics_tracker:
                bot_results = {
                    'random': results.get('random'),
                    'greedy': results.get('greedy'),
                    'defensive': results.get('defensive'),
                    'combined': combined_win_rate
                }
                self.metrics_tracker.log_bot_evaluations(bot_results)

            # Also log to model's logger (backup)
            if hasattr(self.model, 'logger') and self.model.logger:
                self.model.logger.record('eval_bots/combined_win_rate', combined_win_rate)

            # Save best model based on combined performance
            if combined_win_rate > self.best_combined_win_rate:
                self.best_combined_win_rate = combined_win_rate
                if self.best_model_save_path:
                    save_path = f"{self.best_model_save_path}/best_model"
                    self.model.save(save_path)
        return True

    def _evaluate_against_bots(self) -> Dict[str, float]:
        """Evaluate agent against bots using standalone function"""
        # Lazy import to avoid circular dependency
        from ai.bot_evaluation import evaluate_against_bots

        # Extract controlled_agent, training_config_name, and rewards_config_name from training environment
        controlled_agent = None
        training_config_name = None
        rewards_config_name = None

        if hasattr(self, 'training_env') and hasattr(self.training_env, 'envs'):
            if len(self.training_env.envs) > 0:
                train_env = self.training_env.envs[0]
                if hasattr(train_env, 'unwrapped'):
                    train_env = train_env.unwrapped
                if hasattr(train_env, 'config'):
                    controlled_agent = train_env.config.get('controlled_agent')
                    # Extract training_config_name from config
                    if 'training_config_name' not in train_env.config:
                        raise KeyError("Training environment config missing required 'training_config_name' field")
                    training_config_name = train_env.config['training_config_name']
                    # Extract rewards_config_name from config (might be stored as rewards_config)
                    if 'rewards_config' not in train_env.config and 'rewards_config_name' not in train_env.config:
                        raise KeyError("Training environment config missing required 'rewards_config' or 'rewards_config_name' field")
                    rewards_config_name = train_env.config.get('rewards_config_name') or train_env.config.get('rewards_config')

        # Raise error if extraction failed
        if not training_config_name:
            raise RuntimeError("Failed to extract training_config_name from training environment")
        if not rewards_config_name:
            raise RuntimeError("Failed to extract rewards_config_name from training environment")

        # Use standalone function with no progress bar for intermediate eval
        return evaluate_against_bots(
            model=self.model,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            n_episodes=self.n_eval_episodes,
            controlled_agent=controlled_agent,
            show_progress=False,
            deterministic=True
        )
