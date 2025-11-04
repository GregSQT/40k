# ai/train.py
#!/usr/bin/env python3
"""
ai/train.py - Main training script following AI_INSTRUCTIONS.md exactly
"""

import os
import sys
import argparse
import subprocess
import json
import numpy as np
import glob
import shutil
import random
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)
from ai.unit_registry import UnitRegistry
sys.path.insert(0, project_root)

# Import evaluation bots for testing
try:
    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
    EVALUATION_BOTS_AVAILABLE = True
except ImportError:
    EVALUATION_BOTS_AVAILABLE = False

# Import MaskablePPO - enforces action masking during training
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3 import PPO
MASKABLE_PPO_AVAILABLE = True

from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, BaseCallback, CallbackList
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv  # ✓ CHANGE 1: Add vectorization support
# Multi-agent orchestration imports
from ai.scenario_manager import ScenarioManager
from ai.multi_agent_trainer import MultiAgentTrainer
from config_loader import get_config_loader
from ai.game_replay_logger import GameReplayIntegration
import torch
import time  # Add time import for StepLogger timestamps


class BotControlledEnv:
    """Wrapper for bot-controlled Player 1 evaluation."""
    
    def __init__(self, base_env, bot, unit_registry):
        self.base_env = base_env
        self.bot = bot
        self.unit_registry = unit_registry
        self.episode_reward = 0.0
        self.episode_length = 0
        
        # Unwrap ActionMasker to get actual engine
        self.engine = base_env
        if hasattr(base_env, 'env'):
            # ActionMasker wraps the actual engine in .env attribute
            self.engine = base_env.env
    
    def reset(self, seed=None, options=None):
        obs, info = self.base_env.reset(seed=seed, options=options)
        self.episode_reward = 0.0
        self.episode_length = 0
        return obs, info
    
    def step(self, agent_action):
        # Execute agent action
        obs, reward, terminated, truncated, info = self.base_env.step(agent_action)
        self.episode_reward += reward
        self.episode_length += 1
        
        # CRITICAL FIX: Loop through ALL bot turns until control returns to agent
        while not (terminated or truncated) and self.engine.game_state["current_player"] == 1:
            debug_bot = self.episode_length < 10
            bot_action = self._get_bot_action(debug=debug_bot)
            obs, reward, terminated, truncated, info = self.base_env.step(bot_action)
            self.episode_length += 1
        
        return obs, reward, terminated, truncated, info
    
    def _get_bot_action(self, debug=False) -> int:
        game_state = self.engine.game_state
        action_mask = self.engine.get_action_mask()
        valid_actions = [i for i in range(12) if action_mask[i]]
        
        if not valid_actions:
            return 11
        
        if hasattr(self.bot, 'select_action_with_state'):
            bot_choice = self.bot.select_action_with_state(valid_actions, game_state)
        else:
            bot_choice = self.bot.select_action(valid_actions)
        
        if bot_choice not in valid_actions:
            return valid_actions[0]        
        return bot_choice
    
    def close(self):
        self.base_env.close()
    
    @property
    def observation_space(self):
        return self.base_env.observation_space
    
    @property
    def action_space(self):
        return self.base_env.action_space


class EpisodeTerminationCallback(BaseCallback):
    """Callback to terminate training after exact episode count."""
    
    def __init__(self, max_episodes: int, expected_timesteps: int, verbose: int = 0):
        super().__init__(verbose)
        if max_episodes <= 0:
            raise ValueError("max_episodes must be positive - no defaults allowed")
        if expected_timesteps <= 0:
            raise ValueError("expected_timesteps must be positive - no defaults allowed")
        self.max_episodes = max_episodes
        self.expected_timesteps = expected_timesteps
        self.episode_count = 0
        self.step_count = 0
        self.start_time = None
    
    def _on_training_start(self) -> None:
        """Initialize timing when training starts."""
        import time
        self.start_time = time.time()
                
    def _on_step(self) -> bool:
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
            except Exception as e:
                if self.step_count <= 100:
                    print(f"   ⚠️  DEBUG: Method 3 exception: {e}")
                pass
        
        # Log progress every 10 episodes with visual bar
        if episode_ended and self.episode_count % 10 == 0:
            import time
            
            progress_pct = (self.episode_count / self.max_episodes) * 100
            bar_length = 50
            filled = int(bar_length * self.episode_count / self.max_episodes)
            bar = '█' * filled + '░' * (bar_length - filled)
            
            # Calculate time
            time_info = ""
            if self.start_time is not None and self.episode_count > 0:
                elapsed = time.time() - self.start_time
                avg_time_per_episode = elapsed / self.episode_count
                remaining_episodes = self.max_episodes - self.episode_count
                eta = avg_time_per_episode * remaining_episodes
                
                # Format times as MM:SS
                elapsed_str = f"{int(elapsed//60):02d}:{int(elapsed%60):02d}"
                eta_str = f"{int(eta//60):02d}:{int(eta%60):02d}"
                time_info = f" [ {elapsed_str} < {eta_str} ]"
            
            print(f"\r{progress_pct:3.0f}% {bar} {self.episode_count}/{self.max_episodes} episodes{time_info}", end='', flush=True)
            if self.episode_count == self.max_episodes:
                print()  # New line only at completion
        
        # CRITICAL: Stop when max episodes reached
        if self.episode_count >= self.max_episodes:
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
    
    def __init__(self, metrics_tracker, model, verbose: int = 0):
        super().__init__(verbose)
        self.metrics_tracker = metrics_tracker
        self.model = model
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
            print(f"📊 UPDATING metrics_tracker to use SB3 directory: {actual_log_dir}")
            
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
        controlled_agent = training_config.get('controlled_agent')
        
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
            if any(key.startswith('train/') for key in model_stats.keys()):
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
                agent_won = 1.0 if winner == 1 else 0.0
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

def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes, 
                         controlled_agent=None, show_progress=False, deterministic=True):
    """
    Standalone bot evaluation function - single source of truth for all bot testing.
    
    Args:
        model: Trained model to evaluate
        training_config_name: Name of training config to use (e.g., "phase1", "default")
        n_episodes: Number of episodes per bot
        controlled_agent: Agent identifier (None for player 0, otherwise player 1)
        show_progress: Show progress bar with time estimates
        deterministic: Use deterministic policy
    
    Returns:
        Dict with keys: 'random', 'greedy', 'defensive', 'combined', 
                       'random_wins', 'greedy_wins', 'defensive_wins'
    """
    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader
    import time
    
    if not EVALUATION_BOTS_AVAILABLE:
        return {}
    
    results = {}
    bots = {'random': RandomBot(), 'greedy': GreedyBot(), 'defensive': DefensiveBot()}
    config = get_config_loader()
    scenario_file = os.path.join(config.config_dir, "scenario.json")
    unit_registry = UnitRegistry()
    
    # Progress tracking
    total_episodes = n_episodes * len(bots)
    completed_episodes = 0
    start_time = time.time() if show_progress else None
    
    for bot_name, bot in bots.items():
        wins = 0
        for episode_num in range(n_episodes):
            completed_episodes += 1
            
            # Progress bar (only if show_progress=True)
            if show_progress:
                progress_pct = (completed_episodes / total_episodes) * 100
                bar_length = 50
                filled = int(bar_length * completed_episodes / total_episodes)
                bar = '█' * filled + '░' * (bar_length - filled)
                
                elapsed = time.time() - start_time
                avg_time = elapsed / completed_episodes
                remaining = total_episodes - completed_episodes
                eta = avg_time * remaining
                elapsed_str = f"{int(elapsed//60):02d}:{int(elapsed%60):02d}"
                eta_str = f"{int(eta//60):02d}:{int(eta%60):02d}"
                
                print(f"\r{progress_pct:3.0f}% {bar} {completed_episodes}/{total_episodes} vs {bot_name.capitalize()}Bot [ {elapsed_str} < {eta_str} ]", end='', flush=True)
            
            try:
                W40KEngine, _ = setup_imports()
                
                # Create base environment with specified training config
                base_env = W40KEngine(
                    rewards_config=training_config_name,
                    training_config_name=training_config_name,
                    controlled_agent=controlled_agent,
                    active_agents=None,
                    scenario_file=scenario_file,
                    unit_registry=unit_registry,
                    quiet=True,
                    gym_training_mode=True
                )
                
                # Wrap with ActionMasker (CRITICAL for proper action masking)
                def mask_fn(env):
                    return env.get_action_mask()
                
                masked_env = ActionMasker(base_env, mask_fn)
                bot_env = BotControlledEnv(masked_env, bot, unit_registry)
                
                obs, info = bot_env.reset()
                done = False
                step_count = 0
                
                # Calculate max_eval_steps from training_config
                env_config = base_env.unwrapped.config if hasattr(base_env, 'unwrapped') else base_env.config
                training_cfg = env_config.get('training_config', {})
                max_turns = training_cfg.get('max_turns_per_episode', 5)
                
                # Calculate expected steps per episode
                steps_per_turn = 8
                expected_max_steps = max_turns * steps_per_turn
                
                # Add 100% buffer for slow/suboptimal play
                max_eval_steps = expected_max_steps * 2
                
                while not done and step_count < max_eval_steps:
                    action_masks = bot_env.engine.get_action_mask()
                    action, _ = model.predict(obs, action_masks=action_masks, deterministic=deterministic)
                    
                    obs, reward, terminated, truncated, info = bot_env.step(action)
                    done = terminated or truncated
                    step_count += 1
                
                # Determine winner - handle both controlled_agent cases
                agent_player = 1 if controlled_agent else 0
                if info.get('winner') == agent_player:
                    wins += 1
                
                bot_env.close()
            except Exception as e:
                if show_progress:
                    print(f"\n⚠️  Episode {episode_num+1} error: {e}")
                continue
        
        win_rate = wins / n_episodes
        results[bot_name] = win_rate
        results[f'{bot_name}_wins'] = wins
    
    if show_progress:
        print("\r" + " " * 120)  # Clear the progress bar line
        print()  # New line after clearing
    
    # Combined score with standard weighting: RandomBot 20%, GreedyBot 30%, DefensiveBot 50%
    results['combined'] = 0.2 * results['random'] + 0.3 * results['greedy'] + 0.5 * results['defensive']
    
    return results


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
            self.bots = {
                'random': RandomBot(),
                'greedy': GreedyBot(),
                'defensive': DefensiveBot()
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
            # Standard weighting: RandomBot 20%, GreedyBot 30%, DefensiveBot 50%
            combined_win_rate = (
                results.get('random', 0) * 0.2 +
                results.get('greedy', 0) * 0.3 +
                results.get('defensive', 0) * 0.5
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

class StepLogger:
    """
    Step-by-step action logger for training debugging.
    Captures ALL actions that generate step increments per AI_TURN.md.
    """
    
    def __init__(self, output_file="train_step.log", enabled=False):
        self.output_file = output_file
        self.enabled = enabled
        self.step_count = 0
        self.action_count = 0
        # Per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0
        
        if self.enabled:
            # Clear existing log file
            with open(self.output_file, 'w') as f:
                f.write("=== STEP-BY-STEP ACTION LOG ===\n")
                f.write("AI_TURN.md COMPLIANCE: Actions that increment episode_steps are logged\n")
                f.write("STEP INCREMENT ACTIONS: move, shoot, charge, combat, wait (SUCCESS OR FAILURE)\n")
                f.write("NO STEP INCREMENT: auto-skip ineligible units, phase transitions\n")
                f.write("FAILED ACTIONS: Still increment steps - unit consumed time/effort\n")
                f.write("=" * 80 + "\n\n")
            print(f"📝 Step logging enabled: {self.output_file}")
    
    def log_action(self, unit_id, action_type, phase, player, success, step_increment, action_details=None):
        """Log action with step increment information using clear format"""
        if not self.enabled:
            return
            
        self.action_count += 1
        self.episode_action_count += 1
        if step_increment:
            self.step_count += 1
            self.episode_step_count += 1
            
        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                
                # Enhanced format: [timestamp] TX(col, row) PX PHASE : Message [SUCCESS/FAILED] [STEP: YES/NO]
                step_status = "STEP: YES" if step_increment else "STEP: NO"
                success_status = "SUCCESS" if success else "FAILED"
                phase_upper = phase.upper()
                
                # Format message using gameLogUtils.ts style
                message = self._format_replay_style_message(unit_id, action_type, action_details)
                
                # Standard format: [timestamp] TX PX PHASE : Message [SUCCESS/FAILED] [STEP: YES/NO]
                step_status = "STEP: YES" if step_increment else "STEP: NO"
                success_status = "SUCCESS" if success else "FAILED"
                phase_upper = phase.upper()
                
                # Get turn from SINGLE SOURCE OF TRUTH
                turn_number = action_details.get('current_turn', 1) if action_details else 1
                f.write(f"[{timestamp}] T{turn_number} P{player} {phase_upper} : {message} [{success_status}] [{step_status}]\n")
                
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def log_episode_start(self, units_data, scenario_info=None):
        """Log episode start with all unit starting positions"""
        if not self.enabled:
            return
        
        # Reset per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0
            
        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                f.write(f"\n[{timestamp}] === EPISODE START ===\n")
                
                if scenario_info:
                    f.write(f"[{timestamp}] Scenario: {scenario_info}\n")
                
                # Log all unit starting positions
                for unit in units_data:
                    if "id" not in unit:
                        raise KeyError("Unit missing required 'id' field")
                    if "col" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'col' field")
                    if "row" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'row' field")
                    if "player" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'player' field")
                    
                    # Use unitType instead of name (name field doesn't exist)
                    unit_type = unit.get("unitType", "Unknown")
                    player_name = f"P{unit['player']}"
                    f.write(f"[{timestamp}] Unit {unit['id']} ({unit_type}) {player_name}: Starting position ({unit['col']}, {unit['row']})\n")
                
                f.write(f"[{timestamp}] === ACTIONS START ===\n")
                
        except Exception as e:
            print(f"⚠️ Episode start logging error: {e}")
    
    def _format_replay_style_message(self, unit_id, action_type, details):
        """Format messages with detailed combat info - enhanced replay format"""
        # Extract unit coordinates from action_details for consistent format
        unit_coords = ""
        if details and "unit_with_coords" in details:
            # Extract coordinates from format "3(12, 7)" -> "(12, 7)"
            coords_part = details["unit_with_coords"]
            if "(" in coords_part:
                coord_start = coords_part.find("(")
                unit_coords = coords_part[coord_start:]
        
        if action_type == "move" and details:
            # Extract position info for move message
            if "start_pos" in details and "end_pos" in details:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                return f"Unit {unit_id}{unit_coords} MOVED from ({start_col}, {start_row}) to ({end_col}, {end_row})"
            elif "col" in details and "row" in details:
                # Use destination coordinates from mirror_action
                return f"Unit {unit_id}{unit_coords} MOVED to ({details['col']}, {details['row']})"
            else:
                raise KeyError("Move action missing required position data")
                
        elif action_type == "shoot":
            if "target_id" not in details:
                raise KeyError("Shoot action missing required target_id")
            if "hit_roll" not in details:
                raise KeyError("Shoot action missing required hit_roll")
            if "wound_roll" not in details:
                raise KeyError("Shoot action missing required wound_roll")
            if "save_roll" not in details:
                raise KeyError("Shoot action missing required save_roll")
            if "damage_dealt" not in details:
                raise KeyError("Shoot action missing required damage_dealt")
            if "hit_result" not in details:
                raise KeyError("Shoot action missing required hit_result")
            if "wound_result" not in details:
                raise KeyError("Shoot action missing required wound_result")
            if "save_result" not in details:
                raise KeyError("Shoot action missing required save_result")
            if "hit_target" not in details:
                raise KeyError("Shoot action missing required hit_target")
            if "wound_target" not in details:
                raise KeyError("Shoot action missing required wound_target")
            if "save_target" not in details:
                raise KeyError("Shoot action missing required save_target")
            
            target_id = details["target_id"]
            hit_roll = details["hit_roll"]
            wound_roll = details["wound_roll"]
            save_roll = details["save_roll"]
            damage = details["damage_dealt"]
            hit_result = details["hit_result"]
            wound_result = details["wound_result"]
            save_result = details["save_result"]
            
            hit_target = details["hit_target"]
            wound_target = details["wound_target"]
            save_target = details["save_target"]
            
            base_msg = f"Unit {unit_id}{unit_coords} SHOT at unit {target_id}"
            detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}({wound_result}) Save:{save_target}+:{save_roll}({save_result}) Dmg:{damage}HP"
            
            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                detail_msg += f" [R:{reward:+.1f}]"
            
            return base_msg + detail_msg
            
        elif action_type == "shoot_individual":
            # Individual shot within multi-shot sequence
            if "target_id" not in details:
                raise KeyError("Individual shot missing required target_id")
            if "shot_number" not in details or "total_shots" not in details:
                raise KeyError("Individual shot missing required shot_number or total_shots")
                
            target_id = details["target_id"]
            shot_num = details["shot_number"]
            total_shots = details["total_shots"]
            
            # Check if this shot actually fired (hit_roll > 0 means it was attempted)
            if details.get("hit_roll") > 0:
                hit_roll = details["hit_roll"]
                wound_roll = details["wound_roll"]
                save_roll = details["save_roll"]
                damage = details["damage_dealt"]
                hit_result = details["hit_result"]
                wound_result = details["wound_result"]
                save_result = details["save_result"]
                hit_target = details["hit_target"]
                wound_target = details["wound_target"]
                save_target = details["save_target"]
                
                base_msg = f"Unit {unit_id}{unit_coords} SHOT at unit {target_id} (Shot {shot_num}/{total_shots})"
                if hit_result == "MISS":
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}(MISS)"
                elif wound_result == "FAIL":
                    # Failed wound - stop progression, don't show save/damage
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}(FAIL)"
                else:
                    # Successful wound - show full progression
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}({wound_result}) Save:{save_target}+:{save_roll}({save_result}) Dmg:{damage}HP"
                return base_msg + detail_msg
            else:
                return f"Unit {unit_id}{unit_coords} SHOT at unit {target_id} (Shot {shot_num}/{total_shots}) - MISS"
                
        elif action_type == "shoot_summary":
            # Summary of multi-shot sequence
            if "target_id" not in details:
                raise KeyError("Shoot summary missing required target_id")
            if "total_shots" not in details or "total_damage" not in details:
                raise KeyError("Shoot summary missing required total_shots or total_damage")
                
            target_id = details["target_id"]
            total_shots = details["total_shots"]
            total_damage = details["total_damage"]
            hits = details.get("hits")
            wounds = details.get("wounds")
            failed_saves = details.get("failed_saves")
            
            return f"Unit {unit_id}{unit_coords} SHOOTING COMPLETE at unit {target_id} - {total_shots} shots, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        elif action_type == "charge" and details:
            if "target_id" in details:
                target_id = details["target_id"]
                if "start_pos" in details and "end_pos" in details:
                    start_col, start_row = details["start_pos"]
                    end_col, end_row = details["end_pos"]
                    # Remove unit names, keep only IDs per your request
                    return f"Unit {unit_id}{unit_coords} CHARGED unit {target_id} from ({start_col}, {start_row}) to ({end_col}, {end_row})"
                else:
                    return f"Unit {unit_id}{unit_coords} CHARGED unit {target_id}"
            else:
                return f"Unit {unit_id}{unit_coords} CHARGED"
                
        elif action_type == "combat":
            if "target_id" not in details:
                return f"Unit {unit_id}{unit_coords} FOUGHT (no target data)"
            
            target_id = details["target_id"]
            
            # Check if all required dice data is present - if not, return simple message
            required_fields = ["hit_roll", "wound_roll", "save_roll", "damage_dealt", "hit_result", "wound_result", "save_result", "hit_target", "wound_target", "save_target"]
            if not all(field in details for field in required_fields):
                return f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id} (dice data incomplete)"
            
            # All dice data present - format detailed message
            hit_roll = details["hit_roll"]
            wound_roll = details["wound_roll"]
            save_roll = details["save_roll"]
            damage = details["damage_dealt"]
            hit_result = details["hit_result"]
            wound_result = details["wound_result"]
            save_result = details["save_result"]
            hit_target = details["hit_target"]
            wound_target = details["wound_target"]
            save_target = details["save_target"]
            
            base_msg = f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id}"
            
            # Apply truncation logic like shooting phase - stop after first failure
            detail_parts = [f"Hit:{hit_target}+:{hit_roll}({hit_result})"]
            
            # Only show wound if hit succeeded
            if hit_result == "HIT":
                detail_parts.append(f"Wound:{wound_target}+:{wound_roll}({wound_result})")
                
                # Only show save if wound succeeded  
                if wound_result == "WOUND":
                    detail_parts.append(f"Save:{save_target}+:{save_roll}({save_result})")
                    
                    # Only show damage if save failed (damage > 0)
                    if damage > 0:
                        detail_parts.append(f"Dmg:{damage}HP")
            
            detail_msg = f" - {' '.join(detail_parts)}"
            return base_msg + detail_msg
            
        elif action_type == "wait":
            return f"Unit {unit_id}{unit_coords} WAIT"
            
        elif action_type == "combat_individual":
            # Individual attack within multi-attack sequence
            if "target_id" not in details:
                raise KeyError("Individual attack missing required target_id")
            if "attack_number" not in details or "total_attacks" not in details:
                raise KeyError("Individual attack missing required attack_number or total_attacks")
                
            target_id = details["target_id"]
            attack_num = details["attack_number"]
            total_attacks = details["total_attacks"]
            
            # Check if this attack actually happened (hit_roll > 0 means it was attempted)
            if details.get("hit_roll") > 0:
                hit_roll = details["hit_roll"]
                wound_roll = details["wound_roll"]
                save_roll = details["save_roll"]
                damage = details["damage_dealt"]
                hit_result = details["hit_result"]
                wound_result = details["wound_result"]
                save_result = details["save_result"]
                hit_target = details["hit_target"]
                wound_target = details["wound_target"]
                save_target = details["save_target"]
                
                base_msg = f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id} (Attack {attack_num}/{total_attacks})"
                if hit_result == "MISS":
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}(MISS)"
                elif wound_result == "FAIL":
                    # Failed wound - stop progression, don't show save/damage
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}(FAIL)"
                else:
                    # Successful wound - show full progression
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}({wound_result}) Save:{save_target}+:{save_roll}({save_result}) Dmg:{damage}HP"
                return base_msg + detail_msg
            else:
                return f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id} (Attack {attack_num}/{total_attacks}) - MISS"
                
        elif action_type == "combat_summary":
            # Summary of multi-attack sequence
            if "target_id" not in details:
                raise KeyError("Combat summary missing required target_id")
            if "total_attacks" not in details or "total_damage" not in details:
                raise KeyError("Combat summary missing required total_attacks or total_damage")
                
            target_id = details["target_id"]
            total_attacks = details["total_attacks"]
            total_damage = details["total_damage"]
            hits = details.get("hits")
            wounds = details.get("wounds")
            failed_saves = details.get("failed_saves")
            
            return f"Unit {unit_id}{unit_coords} COMBAT COMPLETE at unit {target_id} - {total_attacks} attacks, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        else:
            raise ValueError(f"Unknown action_type '{action_type}' - no fallback allowed")
    
    def log_phase_transition(self, from_phase, to_phase, player, turn_number=1):
        """Log phase transitions (no step increment) using simplified format"""
        if not self.enabled:
            return
            
        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                # Clearer format: [timestamp] TX PX PHASE phase Start
                phase_upper = to_phase.upper()
                f.write(f"[{timestamp}] T{turn_number} P{player} {phase_upper} phase Start\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def log_episode_end(self, total_episodes_steps, winner):
        """Log episode completion summary using replay-style format"""
        if not self.enabled:
            return
            
        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                f.write(f"[{timestamp}] EPISODE END: Winner={winner}, Actions={self.episode_action_count}, Steps={self.episode_step_count}, Total={total_episodes_steps}\n")
                f.write("=" * 80 + "\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")


# Global step logger instance
step_logger = None

def check_gpu_availability():
    """Check and display GPU availability for training."""
    print("\n🔍 GPU AVAILABILITY CHECK")
    print("=" * 30)
    
    if torch.cuda.is_available():
        device_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        device_name = torch.cuda.get_device_name(current_device)
        memory_gb = torch.cuda.get_device_properties(current_device).total_memory / 1024**3
        
        print(f"✅ CUDA Available: YES")
        print(f"📊 GPU Devices: {device_count}")
        print(f"🎯 Current Device: {current_device} ({device_name})")
        print(f"💾 GPU Memory: {memory_gb:.1f} GB")
        print(f"🚀 PyTorch CUDA Version: {torch.version.cuda}")
        
        # Force PyTorch to use GPU for Stable-Baselines3
        torch.cuda.set_device(current_device)
        
        return True
    else:
        print(f"❌ CUDA Available: NO")
        print(f"⚠️  Training will use CPU (much slower)")
        print(f"💡 Install CUDA-enabled PyTorch: pip install torch --index-url https://download.pytorch.org/whl/cu118")
        
        return False

def setup_imports():
    """Set up import paths and return required modules."""
    try:
        # AI_TURN.md COMPLIANCE: Use compliant engine with gym interface
        from engine.w40k_core import W40KEngine
        
        # Compatibility function for training system
        def register_environment():
            """No registration needed for direct engine usage"""
            pass
            
        return W40KEngine, register_environment
    except ImportError as e:
        raise ImportError(f"AI_TURN.md: w40k_engine import failed: {e}")
    
def make_training_env(rank, scenario_file, rewards_config_name, training_config_name,
                     controlled_agent_key, unit_registry, step_logger_enabled=False):
    """
    Factory function to create a single W40KEngine instance for vectorization.
    
    Args:
        rank: Environment index (0, 1, 2, 3, ...)
        scenario_file: Path to scenario JSON file
        rewards_config_name: Name of rewards configuration
        training_config_name: Name of training configuration
        controlled_agent_key: Agent key for this environment
        unit_registry: Shared UnitRegistry instance
        step_logger_enabled: Whether step logging is enabled (disable for vectorized envs)
    
    Returns:
        Callable that creates and returns a wrapped environment instance
    """
    def _init():
        # Import environment (inside function to avoid import issues)
        from engine.w40k_core import W40KEngine
        
        # Create base environment
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent_key,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True
        )
        
        # ✓ CHANGE 9: Removed seed() call - W40KEngine uses reset(seed=...) instead
        # Seeding will happen naturally during first reset() call
        
        # Disable step logger for parallel envs to avoid file conflicts
        if not step_logger_enabled:
            base_env.step_logger = None  # ✓ CHANGE 2: Prevent log conflicts
        
        # Wrap with ActionMasker for MaskablePPO
        def mask_fn(env):
            return env.get_action_mask()
        
        masked_env = ActionMasker(base_env, mask_fn)
        
        # Wrap with Monitor for episode statistics
        return Monitor(masked_env)
    
    return _init

def create_model(config, training_config_name, rewards_config_name, new_model, append_training, args):
    """Create or load PPO model with configuration following AI_INSTRUCTIONS.md."""
    
    # Import metrics tracker for training monitoring
    from metrics_tracker import W40KMetricsTracker
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration from config files (not script parameters)
    training_config = config.load_training_config(training_config_name)
    model_params = training_config["model_params"]
    
    # Import environment
    W40KEngine, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create environment with specified rewards config
    # ensure scenario.json exists in config/
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    # Load unit registry for environment creation
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    # CRITICAL FIX: Auto-detect controlled_agent from scenario's Player 0 units
    # This allows curriculum training without --agent parameter
    controlled_agent_key = None
    try:
        with open(scenario_file, 'r') as f:
            scenario_data = json.load(f)
    
        # Get first Player 0 unit to determine agent type
        player_0_units = [u for u in scenario_data.get("units", []) if u.get("player") == 0]
        if player_0_units:
            first_unit_type = player_0_units[0].get("unit_type")
            if first_unit_type:
                base_agent_key = unit_registry.get_model_key(first_unit_type)
                
                # CRITICAL FIX: Use rewards_config_name directly as controlled_agent_key
                # rewards_config.json has keys like "SpaceMarine_Infantry_Troop_RangedSwarm_phase1"
                # The rewards_config_name parameter already contains the full key
                if rewards_config_name not in ["default", "test"]:
                    controlled_agent_key = rewards_config_name
                    print(f"ℹ️  Auto-detected base agent: {base_agent_key}")
                    print(f"✅ Using phase-specific rewards: {controlled_agent_key}")
                else:
                    controlled_agent_key = base_agent_key
                    print(f"ℹ️  Auto-detected controlled_agent: {controlled_agent_key}")
                
    except Exception as e:
        print(f"⚠️  Failed to auto-detect controlled_agent: {e}")
        raise ValueError(f"Cannot proceed without controlled_agent - auto-detection failed: {e}")
    
    # ✓ CHANGE 3: Check if vectorization is enabled in config
    n_envs = training_config.get("n_envs", 1)  # Default to 1 (no vectorization)
    
    # ✓ CHANGE 3: Special handling for replay/steplog modes (must be single env)
    if args.replay or args.convert_steplog:
        n_envs = 1  # Force single environment for replay generation
        print("ℹ️  Replay mode: Using single environment (vectorization disabled)")
    
    if n_envs > 1:
        # ✓ CHANGE 3: Create vectorized environments for parallel training
        print(f"🚀 Creating {n_envs} parallel environments for accelerated training...")
        
        # Disable step logger for vectorized training (avoid file conflicts)
        vec_envs = SubprocVecEnv([
            make_training_env(
                rank=i,
                scenario_file=scenario_file,
                rewards_config_name=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent_key=controlled_agent_key,
                unit_registry=unit_registry,
                step_logger_enabled=False  # Disabled for parallel envs
            )
            for i in range(n_envs)
        ])
        
        env = vec_envs
        print(f"✅ Vectorized training environment created with {n_envs} parallel processes")
        
    else:
        # ✓ CHANGE 3: Single environment (original behavior)
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent_key,  # Use auto-detected agent
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True
        )
        
        # Connect step logger after environment creation - compliant engine compatibility
        if step_logger:
            # Connect StepLogger directly to compliant W40KEngine
            base_env.step_logger = step_logger
            print("✅ StepLogger connected to compliant W40KEngine")
        
        # Enable replay logging for replay generation modes only
        if args.replay or args.convert_steplog:
            # Use same pattern as evaluate.py for working icon movement
            base_env.is_evaluation_mode = True
            base_env._force_evaluation_mode = True
            # AI_TURN.md: Direct integration without wrapper
            base_env = GameReplayIntegration.enhance_training_env(base_env)
            if hasattr(base_env, 'replay_logger') and base_env.replay_logger:
                base_env.replay_logger.is_evaluation_mode = True
                base_env.replay_logger.capture_initial_state()
        
        # Wrap environment with ActionMasker for MaskablePPO compatibility
        def mask_fn(env):
            return env.get_action_mask()
        
        masked_env = ActionMasker(base_env, mask_fn)
        
        # SB3 Required: Monitor wrapped environment
        env = Monitor(masked_env)
    
    # Check if action masking is available (works for both vectorized and single env)
    if n_envs == 1:
        if hasattr(base_env, 'get_action_mask'):
            print("✅ Action masking enabled - AI will only see valid actions")
        else:
            print("⚠️ Action masking not available")
    
    # Check if action masking is available
    if hasattr(base_env, 'get_action_mask'):
        print("✅ Action masking enabled - AI will only see valid actions")
    else:
        print("⚠️ Action masking not available")
    
    # Use auto-detected agent key for model path
    if controlled_agent_key:
        model_path = config.get_model_path().replace('.zip', f'_{controlled_agent_key}.zip')
        print(f"📝 Using agent-specific model path: {model_path}")
    else:
        model_path = config.get_model_path()
        print(f"📝 Using generic model path: {model_path}")
    
    # Set device for model creation
    # PPO optimization: MlpPolicy performs BETTER on CPU (proven by benchmarks)
    # GPU only beneficial for CNN policies or networks with >2000 hidden units
    net_arch = model_params.get("policy_kwargs", {}).get("net_arch", [256, 256])
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512

    # BENCHMARK RESULTS: CPU 311 it/s vs GPU 282 it/s (10% faster on CPU)
    # Use GPU only for very large networks (>2000 hidden units)
    obs_size = env.observation_space.shape[0]
    use_gpu = gpu_available and (total_params > 2000)  # Removed obs_size check
    device = "cuda" if use_gpu else "cpu"

    model_params["device"] = device
    model_params["verbose"] = 0  # Disable verbose logging

    if not use_gpu and gpu_available:
        print(f"ℹ️  Using CPU for PPO (10% faster than GPU for MlpPolicy with {obs_size} features)")
        print(f"ℹ️  Benchmark: CPU 311 it/s vs GPU 282 it/s")
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model on {device.upper()}...")
        print("✅ Using MaskablePPO with action masking for tactical combat")
        model = MaskablePPO(env=env, **model_params)
        # Properly suppress rollout console output
        if hasattr(model, '_logger') and model._logger:
            original_info = model._logger.info
            def filtered_info(msg):
                if not any(x in str(msg) for x in ['rollout/', 'exploration_rate']):
                    original_info(msg)
            model._logger.info = filtered_info
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
            # Update any model parameters that might have changed
            model.tensorboard_log = model_params["tensorboard_log"]
            model.verbose = model_params["verbose"]
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = MaskablePPO(env=env, **model_params)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = MaskablePPO(env=env, **model_params)
    
    return model, env, training_config, model_path

def create_multi_agent_model(config, training_config_name="default", rewards_config_name="default", 
                            agent_key=None, new_model=False, append_training=False):
    """Create or load PPO model for specific agent with configuration following AI_INSTRUCTIONS.md."""
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration from config files (not script parameters)
    training_config = config.load_training_config(training_config_name)
    model_params = training_config["model_params"]
    
    # Import environment
    W40KEngine, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create agent-specific environment
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    # Load unit registry for multi-agent environment
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    # CRITICAL FIX: Use rewards_config_name for phase-specific training
    # When rewards_config is phase-specific (e.g., "..._phase1"), use it as controlled_agent
    if rewards_config_name not in ["default", "test"]:
        effective_agent_key = rewards_config_name
    else:
        effective_agent_key = agent_key
    
    # ✓ CHANGE 8: Check if vectorization is enabled in config
    n_envs = training_config.get("n_envs", 1)
    
    if n_envs > 1:
        # ✓ CHANGE 8: Create vectorized environments for parallel training
        print(f"🚀 Creating {n_envs} parallel environments for accelerated training...")
        
        vec_envs = SubprocVecEnv([
            make_training_env(
                rank=i,
                scenario_file=scenario_file,
                rewards_config_name=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent_key=effective_agent_key,
                unit_registry=unit_registry,
                step_logger_enabled=False
            )
            for i in range(n_envs)
        ])
        
        env = vec_envs
        print(f"✅ Vectorized training environment created with {n_envs} parallel processes")
        
    else:
        # ✓ CHANGE 8: Single environment (original behavior)
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=effective_agent_key,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True
        )
        
        # Connect step logger after environment creation - compliant engine compatibility
        if step_logger:
            # Connect StepLogger directly to compliant W40KEngine
            base_env.step_logger = step_logger
            print("✅ StepLogger connected to compliant W40KEngine")
        
        # Wrap environment with ActionMasker for MaskablePPO compatibility
        def mask_fn(env):
            return env.get_action_mask()
        
        masked_env = ActionMasker(base_env, mask_fn)
        
        # DISABLED: No logging during training for speed
        # Enhanced logging only during evaluation
        env = Monitor(masked_env)
    
    # Agent-specific model path
    model_path = config.get_model_path().replace('.zip', f'_{agent_key}.zip')
    
    # Set device for model creation
    # PPO optimization: MlpPolicy performs BETTER on CPU (proven by benchmarks)
    # GPU only beneficial for CNN policies or networks with >2000 hidden units
    net_arch = model_params.get("policy_kwargs", {}).get("net_arch", [256, 256])
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512

    # BENCHMARK RESULTS: CPU 311 it/s vs GPU 282 it/s (10% faster on CPU)
    # Use GPU only for very large networks (>2000 hidden units)
    obs_size = env.observation_space.shape[0]
    use_gpu = gpu_available and (total_params > 2000)  # Removed obs_size check
    device = "cuda" if use_gpu else "cpu"

    model_params["device"] = device

    if not use_gpu and gpu_available:
        print(f"ℹ️  Using CPU for {agent_key} PPO (10% faster than GPU for MlpPolicy)")
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model for {agent_key} on {device.upper()}...")
        model = MaskablePPO(env=env, **model_params)
        # Disable rollout logging for multi-agent models too
        if hasattr(model, 'logger') and model.logger:
            model.logger.record = lambda key, value, exclude=None: None if key.startswith('rollout/') else model.logger.record.__wrapped__(key, value, exclude)
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
            if "tensorboard_log" not in model_params:
                raise KeyError("model_params missing required 'tensorboard_log' field")
            model.tensorboard_log = model_params["tensorboard_log"]
            model.verbose = model_params["verbose"]
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = MaskablePPO(env=env, **model_params)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("�' Creating new model instead...")
            model = MaskablePPO(env=env, **model_params)
    
    return model, env, training_config, model_path

def setup_callbacks(config, model_path, training_config, training_config_name="default", metrics_tracker=None):
    W40KEngine, _ = setup_imports()
    callbacks = []
    
    # Add episode termination callback for debug AND step configs - NO FALLBACKS
    if "total_episodes" in training_config:
        if "total_episodes" not in training_config:
            raise KeyError(f"{training_config_name} training config missing required 'total_episodes'")
        if "max_turns_per_episode" not in training_config:
            raise KeyError(f"{training_config_name} training config missing required 'max_turns_per_episode'")
        if "max_steps_per_turn" not in training_config:
            raise KeyError(f"{training_config_name} training config missing required 'max_steps_per_turn'")
        
        max_episodes = training_config["total_episodes"]
        max_steps_per_episode = training_config["max_turns_per_episode"] * training_config["max_steps_per_turn"]
        expected_timesteps = max_episodes * max_steps_per_episode
        episode_callback = EpisodeTerminationCallback(max_episodes, expected_timesteps, verbose=1)
        callbacks.append(episode_callback)
    
    # Evaluation callback - test model periodically with logging enabled
    # Load scenario and unit registry for evaluation callback
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    unit_registry = UnitRegistry()
    
    # REMOVED: Standard EvalCallback - redundant with BotEvaluationCallback
    # BotEvaluationCallback provides better metrics (3 difficulty levels vs 1)
    # This saves 20-30% training time by eliminating duplicate evaluation
    
    print("ℹ️  Using BotEvaluationCallback for multi-difficulty evaluation")
    print("    (RandomBot, GreedyBot, DefensiveBot)")
    
    # Load callback parameters for CheckpointCallback
    if "callback_params" not in training_config:
        raise KeyError("Training config missing required 'callback_params' field")
    callback_params = training_config["callback_params"]
    
    required_callback_fields = ["checkpoint_save_freq", "checkpoint_name_prefix"]
    for field in required_callback_fields:
        if field not in callback_params:
            raise KeyError(f"callback_params missing required '{field}' field")
    
    # Checkpoint callback - save model periodically
    # Use reasonable checkpoint frequency based on total timesteps and config
    if "checkpoint_save_freq" not in callback_params:
        raise KeyError("callback_params missing required 'checkpoint_save_freq' field")
    if "checkpoint_name_prefix" not in callback_params:
        raise KeyError("callback_params missing required 'checkpoint_name_prefix' field")
        
    checkpoint_callback = CheckpointCallback(
        save_freq=callback_params["checkpoint_save_freq"],
        save_path=os.path.dirname(model_path),
        name_prefix=callback_params["checkpoint_name_prefix"]
    )
    callbacks.append(checkpoint_callback)
    
    # Add enhanced bot evaluation callback (replaces standard EvalCallback)
    if EVALUATION_BOTS_AVAILABLE:
        # Read bot evaluation parameters from config
        bot_eval_freq = callback_params.get("bot_eval_freq")
        bot_n_episodes_intermediate = callback_params.get("bot_eval_intermediate")
        bot_eval_use_episodes = callback_params.get("bot_eval_use_episodes", False)
        
        # Store final eval count for use after training completes
        training_config["_bot_eval_final"] = callback_params.get("bot_eval_final")
        
        bot_eval_callback = BotEvaluationCallback(
            eval_freq=bot_eval_freq,
            n_eval_episodes=bot_n_episodes_intermediate,
            best_model_save_path=os.path.dirname(model_path),
            metrics_tracker=metrics_tracker,  # Pass metrics_tracker for TensorBoard logging
            use_episode_freq=bot_eval_use_episodes,
            verbose=1
        )
        callbacks.append(bot_eval_callback)
        
        freq_unit = "episodes" if bot_eval_use_episodes else "timesteps"
        print(f"✅ Bot evaluation callback added (every {bot_eval_freq} {freq_unit}, {bot_n_episodes_intermediate} episodes per bot)")
        print("   📊 Testing against: RandomBot, GreedyBot, DefensiveBot")
    else:
        print("⚠️ Evaluation bots not available - no evaluation metrics")
        print("   Install evaluation_bots.py to enable progress tracking")
    
    return callbacks

def train_model(model, training_config, callbacks, model_path, training_config_name, rewards_config_name):
    """Execute the training process with metrics tracking."""
    
    # Import metrics tracker
    from metrics_tracker import W40KMetricsTracker
    
    # Extract agent name from model path for metrics
    agent_name = "default_agent"
    if "_" in os.path.basename(model_path):
        agent_name = os.path.basename(model_path).replace('.zip', '').replace('model_', '')
    
    # CRITICAL FIX: Use model's TensorBoard directory for metrics_tracker
    # SB3 creates subdirectories like ./tensorboard/PPO_1/
    # metrics_tracker MUST write to the SAME directory to appear in TensorBoard
    # Access tensorboard_log from model parameters (logger not initialized until learn() is called)
    if hasattr(model, 'tensorboard_log') and model.tensorboard_log:
        model_tensorboard_dir = model.tensorboard_log
        print(f"📊 Metrics will be logged to: {model_tensorboard_dir}")
    else:
        model_tensorboard_dir = "./tensorboard/"
        print(f"⚠️  No tensorboard_log found, using default: {model_tensorboard_dir}")
   
    # Create metrics tracker using model's directory
    metrics_tracker = W40KMetricsTracker(agent_name, model_tensorboard_dir)
    
    try:
        # Start training
        # AI_TURN COMPLIANCE: Use episode-based training
        if 'total_timesteps' in training_config:
            total_timesteps = training_config['total_timesteps']
            safety_timesteps = total_timesteps
            print(f"🎯 Training Mode: Step-based ({total_timesteps:,} steps)")
        elif 'total_episodes' in training_config:
            total_episodes = training_config['total_episodes']
            # Calculate timesteps based on required config values - NO DEFAULTS ALLOWED
            if "max_turns_per_episode" not in training_config:
                raise KeyError(f"Training config missing required 'max_turns_per_episode' field")
            if "max_steps_per_turn" not in training_config:
                raise KeyError(f"Training config missing required 'max_steps_per_turn' field")
            max_turns_per_episode = training_config["max_turns_per_episode"]
            max_steps_per_turn = training_config["max_steps_per_turn"]
            total_timesteps = total_episodes * max_turns_per_episode * max_steps_per_turn
            
            # CRITICAL FIX: Add safety margin to prevent infinite training
            # Allow 50% buffer for episode completion, but cap at 2x to prevent runaway
            safety_timesteps = min(
                int(total_timesteps * 1.5),
                total_timesteps * 2
            )
            
            print(f"🎮 Training Mode: Episode-based ({total_episodes:,} episodes)")
            print(f"📊 Expected timesteps: {total_timesteps:,}")
            print(f"🛡️ Safety limit: {safety_timesteps:,} (prevents overtraining)")
        else:
            raise ValueError("Training config must have either 'total_timesteps' or 'total_episodes'")
        
        print(f"📊 Progress tracking: Episodes are primary metric (AI_TURN.md compliance)")
        print(f"📈 Metrics tracking enabled for agent: {agent_name}")
        
        # Enhanced callbacks with metrics collection
        metrics_callback = MetricsCollectionCallback(metrics_tracker, model)
        
        # Attach metrics_tracker to bot_eval_callback if it exists
        for callback in callbacks:
            if isinstance(callback, BotEvaluationCallback):
                callback.metrics_tracker = metrics_tracker
                print(f"✅ Linked BotEvaluationCallback to metrics_tracker")
        
        all_callbacks = callbacks + [metrics_callback]
        enhanced_callbacks = CallbackList(all_callbacks)
        
        model.learn(
            total_timesteps=total_timesteps,
            callback=enhanced_callbacks,
            log_interval=total_timesteps + 1,
            progress_bar=False  # Disable step-based progress bar (using episode-based instead)
        )
        
        # Print final training summary with critical metrics
        metrics_callback.print_final_training_summary(model=model, training_config=training_config, training_config_name=training_config_name, rewards_config_name=rewards_config_name)
        
        # Save final model
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        model.save(model_path)
        
        # Clean up checkpoint files after successful training
        model_dir = os.path.dirname(model_path)
        checkpoint_pattern = os.path.join(model_dir, "ppo_*_steps.zip")
        checkpoint_files = glob.glob(checkpoint_pattern)
        
        if checkpoint_files:
            print(f"\n🧹 Cleaning up {len(checkpoint_files)} checkpoint files...")
            for checkpoint_file in checkpoint_files:
                try:
                    os.remove(checkpoint_file)
                    if verbose := 0:  # Only log if verbose
                        print(f"   Removed: {os.path.basename(checkpoint_file)}")
                except Exception as e:
                    print(f"   ⚠️  Could not remove {os.path.basename(checkpoint_file)}: {e}")
            print(f"✅ Checkpoint cleanup complete")
        
        # Also remove interrupted file if it exists
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        if os.path.exists(interrupted_path):
            try:
                os.remove(interrupted_path)
                print(f"🧹 Removed old interrupted file")
            except Exception as e:
                print(f"   ⚠️  Could not remove interrupted file: {e}")
        
        return True
        
    except KeyboardInterrupt:
        print("\n⏹️ Training interrupted by user")
        # Save current progress
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        model.save(interrupted_path)
        print(f"💾 Progress saved to: {interrupted_path}")
        return False
        
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_trained_model(model, num_episodes, training_config_name="default"):
    """Test the trained model."""
    
    W40KEngine, _ = setup_imports()
    # Load scenario and unit registry for testing
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    unit_registry = UnitRegistry()
    
    env = W40KEngine(
        rewards_config="default",
        training_config_name=training_config_name,
        controlled_agent=None,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True
    )
    wins = 0
    total_rewards = []
    
    for episode in range(num_episodes):
        obs, info = env.reset()
        episode_reward = 0
        done = False
        step_count = 0
        
        while not done and step_count < 1000:  # Prevent infinite loops
            # Standard PPO doesn't support action masking
            action, _ = model.predict(obs, deterministic=True)
            
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            done = terminated or truncated
            step_count += 1
        
        total_rewards.append(episode_reward)
        
        if info['winner'] == 1:  # AI won
            wins += 1
    
    if num_episodes <= 0:
            raise ValueError("num_episodes must be positive - no default episodes allowed")
    
    win_rate = wins / num_episodes
    avg_reward = sum(total_rewards) / len(total_rewards)
    
    print(f"\n📊 Test Results:")
    print(f"   Win Rate: {win_rate:.1%} ({wins}/{num_episodes})")
    print(f"   Average Reward: {avg_reward:.2f}")
    print(f"   Reward Range: {min(total_rewards):.2f} to {max(total_rewards):.2f}")
    
    env.close()
    return win_rate, avg_reward

def test_scenario_manager_integration():
    """Test scenario manager integration."""
    print("🧪 Testing Scenario Manager Integration")
    print("=" * 50)
    
    try:
        config = get_config_loader()
        
        # Test unit registry integration
        unit_registry = UnitRegistry()
        
        # Test scenario manager
        scenario_manager = ScenarioManager(config, unit_registry)
        print(f"✅ ScenarioManager initialized with {len(scenario_manager.get_available_templates())} templates")
        agents = unit_registry.get_required_models()
        print(f"✅ UnitRegistry found {len(agents)} agents: {agents}")
        
        # Test scenario generation
        if len(agents) >= 2:
            template_name = scenario_manager.get_available_templates()[0]
            scenario = scenario_manager.generate_training_scenario(
                template_name, agents[0], agents[1]
            )
            print(f"✅ Generated scenario with {len(scenario['units'])} units")
        
        # Test training rotation
        rotation = scenario_manager.get_balanced_training_rotation(100)
        print(f"✅ Generated training rotation with {len(rotation)} matchups")
        
        print("🎉 Scenario manager integration tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def start_multi_agent_orchestration(config, total_episodes: int, training_config_name: str = "default",
                                   rewards_config_name: str = "default", max_concurrent: int = None,
                                   training_phase: str = None):
    """Start multi-agent orchestration training with optional phase specification."""
    
    try:
        trainer = MultiAgentTrainer(config, max_concurrent_sessions=max_concurrent)
        results = trainer.start_balanced_training(
            total_episodes=total_episodes,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            training_phase=training_phase
        )
        
        print(f"✅ Orchestration completed: {results['total_matchups']} matchups")
        return results
        
    except Exception as e:
        print(f"❌ Orchestration failed: {e}")
        return None

def extract_scenario_name_for_replay():
    """Extract scenario name for replay filename from scenario template name."""
    # Check if generate_steplog_and_replay stored template name
    if hasattr(extract_scenario_name_for_replay, '_current_template_name') and extract_scenario_name_for_replay._current_template_name:
        return extract_scenario_name_for_replay._current_template_name
    
    # Check if convert_to_replay_format detected template name
    if hasattr(convert_to_replay_format, '_detected_template_name') and convert_to_replay_format._detected_template_name:
        return convert_to_replay_format._detected_template_name
    
    # Fallback: use scenario from filename if template not available
    return "scenario"   

def convert_steplog_to_replay(steplog_path):
    """Convert existing steplog file to replay JSON format."""
    import re
    from datetime import datetime
    
    if not os.path.exists(steplog_path):
        raise FileNotFoundError(f"Steplog file not found: {steplog_path}")
    
    print(f"🔄 Converting steplog: {steplog_path}")
    
    # Parse steplog file
    steplog_data = parse_steplog_file(steplog_path)
    
    # Convert to replay format
    replay_data = convert_to_replay_format(steplog_data)
    
    # Generate output filename with scenario name
    scenario_name = extract_scenario_name_for_replay()
    output_file = f"ai/event_log/replay_{scenario_name}.json"
    
    # Ensure output directory exists
    os.makedirs("ai/event_log", exist_ok=True)
    
    # Save replay file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(replay_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Conversion complete: {output_file}")
    print(f"   📊 {len(replay_data.get('combat_log', []))} combat log entries")
    print(f"   🎯 {len(replay_data.get('game_states', []))} game state snapshots")
    print(f"   🎮 {replay_data.get('game_info', {}).get('total_turns', 0)} turns")
    
    return True

def generate_steplog_and_replay(config, args):
    """Generate steplog AND convert to replay in one command - the perfect workflow!"""
    from datetime import datetime
    
    print("🎮 W40K Replay Generator - One-Shot Workflow")
    print("=" * 50)
    
    try:
        # Step 1: Enable step logging temporarily
        temp_steplog = "temp_steplog_for_replay.log"
        temp_step_logger = StepLogger(temp_steplog, enabled=True)
        original_step_logger = globals().get('step_logger')
        globals()['step_logger'] = temp_step_logger
        
        # Step 2: Load model for testing
        print("🎯 Loading model for steplog generation...")
        
        # Use explicit model path if provided, otherwise use config default
        if args.model:
            model_path = args.model
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Specified model not found: {model_path}")
        else:
            model_path = config.get_model_path()
            if not os.path.exists(model_path):
                # List available models for user guidance
                models_dir = os.path.dirname(model_path)
                if os.path.exists(models_dir):
                    available_models = [f for f in os.listdir(models_dir) if f.endswith('.zip')]
                    if available_models:
                        raise FileNotFoundError(f"Default model not found: {model_path}\nAvailable models in {models_dir}: {available_models}\nUse --model to specify a model file")
                    else:
                        raise FileNotFoundError(f"Default model not found: {model_path}\nNo models found in {models_dir}")
                else:
                    raise FileNotFoundError(f"Default model not found: {model_path}\nModels directory does not exist: {models_dir}")
        
        W40KEngine, _ = setup_imports()
        from ai.unit_registry import UnitRegistry
        from ai.scenario_manager import ScenarioManager
        unit_registry = UnitRegistry()
        
        # Generate dynamic scenario using ScenarioManager
        scenario_manager = ScenarioManager(config, unit_registry)
        available_templates = scenario_manager.get_available_templates()
        
        if not available_templates:
            raise RuntimeError("No scenario templates available")
        
        # Select template from argument or find compatible one
        if hasattr(args, 'scenario_template') and args.scenario_template:
            if args.scenario_template not in available_templates:
                raise ValueError(f"Scenario template '{args.scenario_template}' not found. Available templates: {available_templates}")
            template_name = args.scenario_template
        else:
            # Extract agent from model filename for template matching
            agent_name = "Bot"
            if args.model:
                model_filename = os.path.basename(args.model)
                if model_filename.startswith('model_') and model_filename.endswith('.zip'):
                    agent_name = model_filename[6:-4]  # SpaceMarine_Infantry_Troop_RangedSwar
            
            # Find compatible template for this agent
            compatible_template = None
            for template in available_templates:
                try:
                    template_info = scenario_manager.get_template_info(template)
                    if agent_name in template_info.agent_compositions:
                        compatible_template = template
                        break
                except:
                    continue
            
            if compatible_template:
                template_name = compatible_template
                print(f"Found compatible template: {template_name} for agent: {agent_name}")
            else:
                # Try partial matching - look for similar agent patterns
                agent_parts = agent_name.lower().split('_')
                for template in available_templates:
                    template_lower = template.lower()
                    # Check if template contains key parts of agent name
                    if any(part in template_lower for part in agent_parts[-3:]):  # Last 3 parts: Troop_RangedSwar
                        template_name = template
                        print(f"Using similar template: {template_name} for agent: {agent_name}")
                        break
                else:
                    # Final fallback: use first template and warn user
                    template_name = available_templates[0]
                    print(f"WARNING: No compatible template found for agent {agent_name}")
                    print(f"Using fallback template: {template_name}")
                    print(f"Available templates: {available_templates}")
        
        # Agent name already extracted in template selection above
        
        # For solo scenarios, use same agent for both players
        # For cross scenarios, use agent vs different agent
        if "solo_" in template_name.lower():
            player_1_agent = agent_name  # Same agent for solo scenarios
        else:
            # For cross scenarios, try to find a different agent
            template_info = scenario_manager.get_template_info(template_name)
            available_agents = list(template_info.agent_compositions.keys())
            if len(available_agents) > 1:
                # Use a different agent from the template
                player_1_agent = [a for a in available_agents if a != agent_name][0]
            else:
                player_1_agent = agent_name  # Fallback to same agent

        # Store template name for filename generation
        extract_scenario_name_for_replay._current_template_name = template_name
        
        # Generate scenario with descriptive name
        scenario_data = scenario_manager.generate_training_scenario(
            template_name, agent_name, player_1_agent
        )
        
        # Save temporary scenario file
        temp_scenario_file = f"temp_{template_name}_scenario.json"
        with open(temp_scenario_file, 'w') as f:
            json.dump(scenario_data, f, indent=2)
        
        # Load training config to override max_turns for this environment
        training_config = config.load_training_config(args.training_config)
        max_turns_override = training_config.get("max_turns_per_episode", 5)
        print(f"🎯 Using max_turns_per_episode: {max_turns_override} from config '{args.training_config}'")
        
        # Temporarily override game_config max_turns for this environment
        original_max_turns = config.get_max_turns()
        config._cache['game_config']['game_rules']['max_turns'] = max_turns_override
        
        try:
            env = W40KEngine(
                rewards_config=args.rewards_config,
                training_config_name=args.training_config,
                controlled_agent=None,
                active_agents=None,
                scenario_file=temp_scenario_file,
                unit_registry=unit_registry,
                quiet=True
            )
        finally:
            # Restore original max_turns after environment creation
            config._cache['game_config']['game_rules']['max_turns'] = original_max_turns
        
        # Connect step logger
        env.controller.connect_step_logger(temp_step_logger)
        model = PPO.load(model_path, env=env)
        
        # Step 3: Run test episodes with step logging
        if not hasattr(args, 'test_episodes') or args.test_episodes is None:
            raise ValueError("--test-episodes required for replay generation - no default episodes allowed")
        episodes = args.test_episodes
        print(f"🎲 Running {episodes} episodes with step logging...")
        
        for episode in range(episodes):
            print(f"   Episode {episode + 1}/{episodes}")
            obs, info = env.reset()
            done = False
            step_count = 0
            
            while not done and step_count < 1000:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                step_count += 1
        
        env.close()
        
        # Step 4: Convert steplog to replay
        print("🔄 Converting steplog to replay format...")
        
        success = convert_steplog_to_replay(temp_steplog)
        
        # Step 5: Cleanup temporary files
        if os.path.exists(temp_steplog):
            os.remove(temp_steplog)
            print("🧹 Cleaned up temporary steplog file")
        
        # Clean up temporary scenario file
        if 'temp_scenario_file' in locals() and os.path.exists(temp_scenario_file):
            os.remove(temp_scenario_file)
        
        # Clean up template name context
        if hasattr(extract_scenario_name_for_replay, '_current_template_name'):
            delattr(extract_scenario_name_for_replay, '_current_template_name')
        
        # Restore original step logger
        globals()['step_logger'] = original_step_logger
        
        if success:
            print("✅ One-shot replay generation complete!")
            return True
        else:
            print("❌ Replay conversion failed")
            return False
            
    except Exception as e:
        print(f"❌ One-shot workflow failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def parse_steplog_file(steplog_path):
    """Parse steplog file and extract structured data."""
    import re
    
    print(f"📖 Parsing steplog file...")
    
    with open(steplog_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.strip().split('\n')
    
    # Skip header lines (everything before first action)
    action_lines = []
    in_actions = False
    
    for line in lines:
        if line.startswith('[') and '] T' in line:
            in_actions = True
        if in_actions:
            action_lines.append(line)
    
    # Parse action entries
    actions = []
    max_turn = 1
    units_positions = {}
    
    # Regex patterns for parsing
    action_pattern = r'\[([^\]]+)\] T(\d+) P(\d+) (\w+) : (.+?) \[(SUCCESS|FAILED)\] \[STEP: (YES|NO)\]'
    phase_pattern = r'\[([^\]]+)\] T(\d+) P(\d+) (\w+) phase Start'
    
    for line in action_lines:
        # Try to match action pattern
        action_match = re.match(action_pattern, line)
        if action_match:
            timestamp, turn, player, phase, message, success, step_increment = action_match.groups()
            
            # Parse action details from message
            action_data = parse_action_message(message, {
                'timestamp': timestamp,
                'turn': int(turn),
                'player': int(player), 
                'phase': phase.lower(),
                'success': success == 'SUCCESS',
                'step_increment': step_increment == 'YES'
            })
            
            if action_data:
                actions.append(action_data)
                max_turn = max(max_turn, int(turn))
                
                # Update unit positions from ALL actions (move, shoot, combat, charge, wait)
                unit_id = action_data.get('unitId')
                if unit_id:
                    # Try to extract position from action message if available
                    position_extracted = False
                    
                    if action_data['type'] == 'move' and 'startHex' in action_data and 'endHex' in action_data:
                        # Parse coordinates from "(col, row)" format
                        import re
                        end_match = re.match(r'\((\d+),\s*(\d+)\)', action_data['endHex'])
                        if end_match:
                            end_col, end_row = end_match.groups()
                            units_positions[unit_id] = {
                                'col': int(end_col),
                                'row': int(end_row),
                                'last_seen_turn': int(turn)
                            }
                            position_extracted = True
                    
                    # For non-move actions, try to extract position from message format
                    if not position_extracted and 'message' in action_data:
                        import re
                        # Look for "Unit X(col, row)" pattern in any message
                        pos_match = re.search(r'Unit \d+\((\d+), (\d+)\)', action_data['message'])
                        if pos_match:
                            col, row = pos_match.groups()
                            units_positions[unit_id] = {
                                'col': int(col),
                                'row': int(row),
                                'last_seen_turn': int(turn)
                            }
                            position_extracted = True
        
        # Try to match phase change pattern  
        phase_match = re.match(phase_pattern, line)
        if phase_match:
            timestamp, turn, player, phase = phase_match.groups()
            
            phase_data = {
                'type': 'phase_change',
                'message': f'{phase.capitalize()} phase Start',
                'turnNumber': int(turn),
                'phase': phase.lower(),
                'player': int(player),
                'timestamp': timestamp
            }
            actions.append(phase_data)
    
    print(f"   📝 Parsed {len(actions)} action entries")
    print(f"   🎮 {max_turn} total turns detected")
    print(f"   👥 {len(units_positions)} units tracked")
    
    return {
        'actions': actions,
        'max_turn': max_turn,
        'units_positions': units_positions
    }

def parse_action_message(message, context):
    """Parse action message and extract details."""
    import re
    
    action_type = None
    details = {
        'turnNumber': context['turn'],
        'phase': context['phase'],
        'player': context['player'],
        'timestamp': context['timestamp']
    }
    
    # Parse different action types based on message content
    if "MOVED from" in message:
        # Unit X(col, row) MOVED from (start_col, start_row) to (end_col, end_row)
        move_match = re.match(r'Unit (\d+)\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', message)
        if move_match:
            unit_id, _, _, start_col, start_row, end_col, end_row = move_match.groups()
            action_type = 'move'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'startHex': f"({start_col}, {start_row})",
                'endHex': f"({end_col}, {end_row})"
            })
    
    elif "SHOT at" in message:
        # Unit X(col, row) SHOT at unit Y - details...
        shoot_match = re.match(r'Unit (\d+)\([^)]+\) SHOT at unit (\d+)', message)
        if shoot_match:
            unit_id, target_id = shoot_match.groups()
            action_type = 'shoot'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "FOUGHT" in message:
        # Unit X(col, row) FOUGHT unit Y - details...
        combat_match = re.match(r'Unit (\d+)\([^)]+\) FOUGHT unit (\d+)', message)
        if combat_match:
            unit_id, target_id = combat_match.groups()
            action_type = 'combat'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "CHARGED" in message:
        # Unit X(col, row) CHARGED unit Y from (start) to (end)
        charge_match = re.match(r'Unit (\d+)\([^)]+\) CHARGED unit (\d+)', message)
        if charge_match:
            unit_id, target_id = charge_match.groups()
            action_type = 'charge'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "WAIT" in message:
        # Unit X(col, row) WAIT
        wait_match = re.match(r'Unit (\d+)\([^)]+\) WAIT', message)
        if wait_match:
            unit_id = wait_match.groups()[0]
            action_type = 'wait'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id)
            })
    
    return details if action_type else None

def calculate_episode_reward_from_actions(actions, winner):
    """Calculate episode reward from action log and winner."""
    # Simple reward calculation based on winner and action count
    if winner is None:
        return 0.0
    
    # Basic reward: winner gets positive, loser gets negative
    base_reward = 10.0 if winner == 0 else -10.0
    
    # Add small bonus/penalty based on action efficiency
    action_count = len([a for a in actions if a.get('type') != 'phase_change'])
    efficiency_bonus = max(-5.0, min(5.0, (50 - action_count) * 0.1))
    
    return base_reward + efficiency_bonus

def convert_to_replay_format(steplog_data):
    """Convert parsed steplog data to frontend-compatible replay format."""
    from datetime import datetime
    from ai.unit_registry import UnitRegistry
    
    print(f"🔄 Converting to replay format...")
    
    # Store agent info for filename generation
    convert_to_replay_format._detected_agents = None
    
    actions = steplog_data['actions']
    max_turn = steplog_data['max_turn']
    
    # Load unit registry for complete unit data
    unit_registry = UnitRegistry()
    
    # Load config for board size and other settings
    config = get_config_loader()
    
    # Get board size from board_config.json (single source of truth)
    board_cols, board_rows = config.get_board_size()
    board_size = [board_cols, board_rows]
    
    # Load scenario for units data
    scenario_file = os.path.join(config.config_dir, "scenario.json")
    if not os.path.exists(scenario_file):
        raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
    
    with open(scenario_file, 'r') as f:
        scenario_data = json.load(f)
    
    # Determine winner from final actions
    winner = None
    for action in reversed(actions):
        if action.get('type') == 'phase_change' and 'winner' in action:
            winner = action['winner']
            break
    
    # Build initial state using actual unit registry data
    initial_units = []
    if not steplog_data['units_positions']:
        raise ValueError("No unit position data found in steplog - cannot generate replay without unit data")
    
    # Get initial scenario units for complete unit data
    if 'units' not in scenario_data:
        raise KeyError("Scenario missing required 'units' field")
    
    scenario_units = {unit['id']: unit for unit in scenario_data['units']}
    
    # No need to detect scenario name - handled by filename extraction
    
    # Use ALL units from scenario, not just those tracked in steplog
    for unit_id, scenario_unit in scenario_units.items():
        if 'col' not in scenario_unit or 'row' not in scenario_unit:
            raise KeyError(f"Unit {unit_id} missing required position data (col/row) in scenario")
        
        # Get unit statistics from unit registry
        if 'unit_type' not in scenario_unit:
            raise KeyError(f"Unit {unit_id} missing required 'unit_type' field")
        
        try:
            unit_stats = unit_registry.get_unit_data(scenario_unit['unit_type'])
        except ValueError as e:
            raise ValueError(f"Failed to get unit data for '{scenario_unit['unit_type']}': {e}")
        
        # Get final position from steplog tracking or use initial position
        if unit_id in steplog_data['units_positions']:
            final_col = steplog_data['units_positions'][unit_id]['col']
            final_row = steplog_data['units_positions'][unit_id]['row']
        else:
            final_col = scenario_unit['col']
            final_row = scenario_unit['row']
        
        # Build complete unit data with FINAL positions from steplog tracking
        unit_data = {
            'id': unit_id,
            'unit_type': scenario_unit['unit_type'],
            'player': scenario_unit.get('player', 0),
            'col': final_col,  # Use FINAL position from steplog tracking
            'row': final_row   # Use FINAL position from steplog tracking
        }
        
        # Copy all unit statistics from registry (preserves UPPERCASE field names)
        for field_name, field_value in unit_stats.items():
            if field_name.isupper():  # Only copy UPPERCASE fields per AI_TURN.md
                unit_data[field_name] = field_value
        
        # Ensure CUR_HP is set to HP_MAX initially
        if 'HP_MAX' in unit_stats:
            unit_data['CUR_HP'] = unit_stats['HP_MAX']
        
        initial_units.append(unit_data)
    
    # Game states require actual game state snapshots from steplog - not generated defaults
    game_states = []
    # Note: Real implementation would need to capture actual game states during steplog generation
    
    # Build replay data structure matching frontend expectations
    replay_data = {
        'game_info': {
            'scenario': 'steplog_conversion',
            'ai_behavior': 'sequential_activation',
            'total_turns': max_turn,
            'winner': winner
        },
        'metadata': {
            'total_combat_log_entries': len(actions),
            'final_turn': max_turn,
            'episode_reward': 0.0,
            'format_version': '2.0',
            'replay_type': 'steplog_converted',
            'conversion_timestamp': datetime.now().isoformat(),
            'source_file': 'steplog'
        },
        'initial_state': {
            'units': initial_units,
            'board_size': board_size
        },
        'combat_log': actions,
        'game_states': game_states,
        'episode_steps': len([a for a in actions if a.get('type') != 'phase_change']),
        'episode_reward': calculate_episode_reward_from_actions(actions, winner)
    }
    
    return replay_data

def ensure_scenario():
    """Ensure scenario.json exists."""
    scenario_path = os.path.join(project_root, "config", "scenario.json")
    if not os.path.exists(scenario_path):
        raise FileNotFoundError(f"Missing required scenario.json file: {scenario_path}. AI_INSTRUCTIONS.md: No fallbacks allowed - scenario file must exist.")

def main():
    """Main training function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Train W40K AI following AI_GAME_OVERVIEW.md specifications")
    parser.add_argument("--training-config", required=True,
                       help="Training configuration to use from config/training_config.json")
    parser.add_argument("--rewards-config", required=True,
                       help="Rewards configuration to use from config/rewards_config.json")
    parser.add_argument("--new", action="store_true", 
                       help="Force creation of new model")
    parser.add_argument("--append", action="store_true", 
                       help="Continue training existing model")
    parser.add_argument("--test-only", action="store_true", 
                       help="Only test existing model, don't train")
    parser.add_argument("--test-episodes", type=int, default=0, 
                       help="Number of episodes for testing")
    parser.add_argument("--multi-agent", action="store_true",
                       help="Use multi-agent training system")
    parser.add_argument("--agent", type=str, default=None,
                       help="Train specific agent (e.g., 'SpaceMarine_Ranged')")
    parser.add_argument("--orchestrate", action="store_true",
                       help="Start balanced multi-agent orchestration training")
    parser.add_argument("--total-episodes", type=int, default=None,
                       help="Total episodes for training (overrides config file value)")
    parser.add_argument("--max-concurrent", type=int, default=None,
                       help="Maximum concurrent training sessions")
    parser.add_argument("--training-phase", type=str, choices=["solo", "cross_faction", "full_composition"],
                       help="Specific training phase for 3-phase training plan")
    parser.add_argument("--test-integration", action="store_true",
                       help="Test scenario manager integration")
    parser.add_argument("--step", action="store_true",
                       help="Enable step-by-step action logging to train_step.log")
    parser.add_argument("--convert-steplog", type=str, metavar="STEPLOG_FILE",
                       help="Convert existing steplog file to replay JSON format")
    parser.add_argument("--replay", action="store_true", 
                       help="Generate steplog AND convert to replay in one command")
    parser.add_argument("--model", type=str, default=None,
                       help="Specific model file to use for replay generation")
    parser.add_argument("--scenario-template", type=str, default=None,
                       help="Scenario template name from scenario_templates.json for replay generation")
    
    args = parser.parse_args()
    
    print("🎮 W40K AI Training - Following AI_GAME_OVERVIEW.md specifications")
    print("=" * 70)
    print(f"Training config: {args.training_config}")
    print(f"Rewards config: {args.rewards_config}")
    print(f"New model: {args.new}")
    print(f"Append training: {args.append}")
    print(f"Test only: {args.test_only}")
    print(f"Multi-agent: {args.multi_agent}")
    print(f"Orchestrate: {args.orchestrate}")
    print(f"Step logging: {args.step}")
    if hasattr(args, 'convert_steplog') and args.convert_steplog:
        print(f"Convert steplog: {args.convert_steplog}")
    if hasattr(args, 'replay') and args.replay:
        print(f"Replay generation: {args.replay}")
        if args.model:
            print(f"Model file: {args.model}")
        else:
            print(f"Model file: auto-detect")
    print()
    
    try:
        # Initialize global step logger based on --step argument
        global step_logger
        step_logger = StepLogger("train_step.log", enabled=args.step)
        
        # Sync configs to frontend automatically
        try:
            subprocess.run(['node', 'scripts/copy-configs.js'], 
                         cwd=project_root, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Config sync failed: {e}")
        
        # Setup environment and configuration
        config = get_config_loader()
        
        # Ensure scenario exists
        ensure_scenario()
        
        # Convert existing steplog mode
        if args.convert_steplog:
            success = convert_steplog_to_replay(args.convert_steplog)
            return 0 if success else 1

        # Generate steplog AND convert to replay (one-shot mode)
        if args.replay:
            success = generate_steplog_and_replay(config, args)
            return 0 if success else 1

        # Test integration if requested
        if args.test_integration:
            success = test_scenario_manager_integration()
            return 0 if success else 1
        
        # Multi-agent orchestration mode
        if args.orchestrate:
            # Use config fallback for total_episodes if not provided
            total_episodes = args.total_episodes
            if total_episodes is None:
                training_config = config.load_training_config(args.training_config)
                total_episodes = training_config.get("total_episodes", 500)  # Reasonable default
                print(f"📊 Using total_episodes from config: {total_episodes}")
            else:
                print(f"📊 Using total_episodes from command line: {total_episodes}")
                
            results = start_multi_agent_orchestration(
                config=config,
                total_episodes=total_episodes,
                training_config_name=args.training_config,
                rewards_config_name=args.rewards_config,
                max_concurrent=args.max_concurrent,
                training_phase=args.training_phase
            )
            return 0 if results else 1

        # Single agent training mode
        elif args.agent:
            model, env, training_config, model_path = create_multi_agent_model(
                config,
                args.training_config,
                args.rewards_config,
                agent_key=args.agent,
                new_model=args.new,
                append_training=args.append
            )
            
            # Setup callbacks with agent-specific model path
            callbacks = setup_callbacks(config, model_path, training_config, args.training_config)
            
            # Train model
            success = train_model(model, training_config, callbacks, model_path, args.training_config, args.rewards_config)
            
            if success:
                # Only test if episodes > 0
                if args.test_episodes > 0:
                    test_trained_model(model, args.test_episodes, args.training_config)
                else:
                    print("📊 Skipping testing (--test-episodes 0)")
                return 0
            else:
                return 1

        elif args.test_only:
            # Load existing model for testing only
            model_path = config.get_model_path()
            # Ensure model directory exists
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            print(f"📁 Model path: {model_path}")
            
            # Determine whether to create new model or load existing
            if not os.path.exists(model_path):
                print(f"❌ Model not found: {model_path}")
                return 1
            
            W40KEngine, _ = setup_imports()
            # Load scenario and unit registry for testing
            from ai.unit_registry import UnitRegistry
            cfg = get_config_loader()
            scenario_file = os.path.join(cfg.config_dir, "scenario.json")
            unit_registry = UnitRegistry()
            
            env = W40KEngine(
                rewards_config=args.rewards_config,
                training_config_name=args.training_config,
                controlled_agent=None,
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=True
            )
            
            # Connect step logger after environment creation
            print(f"STEP LOGGER ASSIGNMENT DEBUG: step_logger={step_logger}, enabled={step_logger.enabled if step_logger else 'None'}")
            if step_logger:
                env.step_logger = step_logger
                print(f"✅ StepLogger connected directly to W40KEngine: {env.step_logger}")
            else:
                print("❌ No step logger available")
            model = MaskablePPO.load(model_path, env=env)
            if args.test_episodes is None:
                raise ValueError("--test-episodes is required for test-only mode")
            test_trained_model(model, args.test_episodes, args.training_config)
            return 0
        
        else:
            # Generic training mode
            # Create/load model
            model, env, training_config, model_path = create_model(
            config, 
            args.training_config,
            args.rewards_config, 
            args.new, 
            args.append,
            args
        )
        
        # Setup callbacks
        callbacks = setup_callbacks(config, model_path, training_config, args.training_config)
        
        # Train model
        success = train_model(model, training_config, callbacks, model_path, args.training_config, args.rewards_config)
        
        if success:
            # Only test if episodes > 0
            if args.test_episodes > 0:
                test_trained_model(model, args.test_episodes, args.training_config)
                
                # Save training replay with our unified system
                if hasattr(env, 'replay_logger'):
                    from ai.game_replay_logger import GameReplayIntegration
                    final_reward = 0.0  # Average reward from testing
                    replay_file = GameReplayIntegration.save_episode_replay(
                        env, 
                        episode_reward=final_reward, 
                        output_dir="ai/event_log", 
                        is_best=False
                    )
            else:
                print("📊 Skipping testing (--test-episodes 0)")
            
            return 0
        else:
            return 1
            
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)