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
            
            # Track wins - check if AI (player 1) won
            if final_info and final_info.get('winner') == 1:
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
        """Called when training starts - update metrics_tracker to use model's logger directory."""
        # CRITICAL FIX: Update metrics_tracker writer to use SB3's actual tensorboard directory
        # The model's logger is now initialized, so we can get the real directory
        if hasattr(self.model, 'logger') and self.model.logger:
            actual_log_dir = self.model.logger.get_dir()
            
            # Close old writer and create new one in correct directory
            self.metrics_tracker.writer.close()
            from torch.utils.tensorboard import SummaryWriter
            self.metrics_tracker.writer = SummaryWriter(actual_log_dir)
            self.metrics_tracker.log_dir = actual_log_dir
    
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
                print(f"      → Increase learning_rate (policy not updating enough)")
            elif recent_clip > 0.3:
                print(f"      → Decrease learning_rate (too aggressive updates)")
        
        # Check explained_variance
        if len(self.metrics_tracker.hyperparameter_tracking['explained_variances']) >= 20:
            recent_ev = np.mean(self.metrics_tracker.hyperparameter_tracking['explained_variances'][-20:])
            ev_status = "✅" if recent_ev > 0.3 else "⚠️ "
            print(f"   Explained Variance: {recent_ev:.3f} {ev_status} (target: >0.3)")
            if recent_ev < 0.3:
                print(f"      → Value function struggling - check reward signal")
        
        # Check entropy
        if len(self.metrics_tracker.hyperparameter_tracking['entropy_losses']) >= 20:
            recent_entropy = np.mean(self.metrics_tracker.hyperparameter_tracking['entropy_losses'][-20:])
            entropy_status = "✅" if 0.5 <= recent_entropy <= 2.0 else "⚠️ "
            print(f"   Entropy Loss:       {recent_entropy:.3f} {entropy_status} (target: 0.5-2.0)")
            if recent_entropy < 0.5:
                print(f"      → Increase ent_coef (exploration too low)")
            elif recent_entropy > 2.0:
                print(f"      → Decrease ent_coef (exploration too high)")
        
        # Check gradient_norm
        if hasattr(self.metrics_tracker, 'latest_gradient_norm') and self.metrics_tracker.latest_gradient_norm:
            grad_norm = self.metrics_tracker.latest_gradient_norm
            grad_status = "✅" if grad_norm < 10 else "⚠️ "
            print(f"   Gradient Norm:      {grad_norm:.3f} {grad_status} (target: <10)")
            if grad_norm > 10:
                print(f"      → Reduce max_grad_norm or learning_rate")
        
        print(f"\n💡 TensorBoard: {self.metrics_tracker.log_dir}")
        print(f"   → Focus on 0_critical/ namespace for hyperparameter tuning")
        print("="*80 + "\n")
    
    def _run_final_bot_eval(self, model, training_config, training_config_name, rewards_config_name):
        """Run final comprehensive bot evaluation using standalone function"""
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
                for info in self.locals['infos']:
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
                    
                    # Handle episode end
                    if info.get('episode', False) or info.get('winner') is not None:
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
            step_data['learning_rate'] = self.model.learning_rate
        if hasattr(self.model, 'logger') and hasattr(self.model.logger, 'name_to_value'):
            if 'train/loss' in self.model.logger.name_to_value:
                step_data['loss'] = self.model.logger.name_to_value['train/loss']
        if hasattr(self.model, 'exploration_rate'):
            step_data['exploration_rate'] = self.model.exploration_rate
        
        if step_data:
            self.metrics_tracker.log_training_step(step_data)
        
        # NEW: Log PPO hyperparameter metrics from stable-baselines3
        # Extract all available training metrics for hyperparameter tuning
        if hasattr(self.model, 'logger') and hasattr(self.model.logger, 'name_to_value'):
            model_stats = self.model.logger.name_to_value
            
            # Only log if there are actual training metrics available
            # SB3 updates these after each policy update (every n_steps)
            if len(model_stats) > 0:
                # Pass complete model stats to metrics tracker
                # This includes: learning_rate, policy_loss, value_loss, entropy_loss,
                # clip_fraction, approx_kl, explained_variance, n_updates, fps
                self.metrics_tracker.log_training_metrics(model_stats)
                
                # Update step count for proper metric indexing
                self.metrics_tracker.step_count = self.model.num_timesteps
        
        return True
    
    def _handle_episode_end(self, info):
        """Handle episode completion and log metrics."""
        self.episode_count += 1

        # Extract episode data
        episode_data = {
            'total_reward': info.get('episode_reward', self.episode_reward),
            'episode_length': info.get('episode_length', self.episode_length),
            'winner': info.get('winner', None)
        }

        # DIAGNOSTIC: Log winner for first 10 episodes (disabled for cleaner output)
        # if self.episode_count <= 10:
        #     winner = episode_data['winner']
        #     print(f"  [DIAG] Episode {self.episode_count}: winner={winner} (P0 wins if 0, P1 wins if 1, draw if -1)")
       
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
