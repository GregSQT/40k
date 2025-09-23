#!/usr/bin/env python3
"""
ai/metrics_tracker.py - W40K Training Metrics Tracker
Integrates with existing tensorboard logging and training infrastructure
"""

import numpy as np
from collections import defaultdict, deque
from torch.utils.tensorboard import SummaryWriter
import os
from typing import Dict, Any, List, Optional

class W40KMetricsTracker:
    """
    Tracks training metrics for W40K agents with tensorboard integration.
    Designed to work with existing multi_agent_trainer.py structure.
    """
    
    def __init__(self, agent_key: str, log_dir: str = "./tensorboard/"):
        self.agent_key = agent_key
        self.log_dir = os.path.join(log_dir, agent_key)
        self.writer = SummaryWriter(self.log_dir)
        
        # Rolling windows for smoothed metrics (existing compatibility)
        self.rolling_windows = defaultdict(lambda: deque(maxlen=100))
        
        # FULL TRAINING DURATION TRACKING - Your specification
        self.all_episode_rewards = []    # Complete reward history
        self.all_episode_wins = []       # Complete win/loss history
        self.all_invalid_rates = []      # Complete invalid action rates
        
        # Episode tracking
        self.episode_count = 0
        self.step_count = 0
        
        # Bot evaluation tracking
        self.bot_evaluation_history = []
        
        print(f"Metrics tracker initialized for {agent_key} -> {self.log_dir}")
    
    def log_episode_end(self, episode_data: Dict[str, Any]):
        """YOUR SPECIFICATION: 5 core metrics with full training duration tracking"""
        self.episode_count += 1
        
        # Extract data
        total_reward = episode_data.get('total_reward', 0)
        winner = episode_data.get('winner', None)
        
        # 1. YOUR SPECIFICATION: episode/reward - Individual episode rewards
        self.writer.add_scalar('episode/reward', total_reward, self.episode_count)
        self.all_episode_rewards.append(total_reward)
        
        # 2. YOUR SPECIFICATION: episode/win_rate - Win percentage (FULL DURATION)
        if winner is not None:
            agent_won = 1.0 if winner == 1 else 0.0
            self.all_episode_wins.append(agent_won)
            
            # Calculate cumulative win rate over ENTIRE training
            cumulative_win_rate = np.mean(self.all_episode_wins)
            self.writer.add_scalar('episode/win_rate', cumulative_win_rate, self.episode_count)
        
        # Maintain compatibility with existing rolling windows
        self.rolling_windows['rewards'].append(total_reward)
        if winner is not None:
            self.rolling_windows['wins'].append(agent_won)
        
        # Log trend analysis every 10 episodes
        if self.episode_count % 10 == 0:
            self._log_full_duration_trends()
    
    def log_tactical_metrics(self, tactical_data: Dict[str, Any]):
        """Log comprehensive W40K tactical performance metrics"""
        
        # Shooting Performance
        if 'shots_fired' in tactical_data and tactical_data['shots_fired'] > 0:
            hits = tactical_data.get('hits', 0)
            accuracy = hits / tactical_data['shots_fired']
            self.writer.add_scalar('Combat/Shooting_Accuracy', accuracy, self.episode_count)
            self.writer.add_scalar('Combat/Shots_Fired', tactical_data['shots_fired'], self.episode_count)
            self.writer.add_scalar('Combat/Shots_Hit', hits, self.episode_count)
        
        # Combat Effectiveness
        if 'total_enemies' in tactical_data and tactical_data['total_enemies'] > 0:
            killed_enemies = tactical_data.get('killed_enemies', 0)
            slaughter_efficiency = killed_enemies / tactical_data['total_enemies']
            self.writer.add_scalar('Combat/Slaughter_Efficiency', slaughter_efficiency, self.episode_count)
        
        # Damage Metrics
        if 'damage_dealt' in tactical_data:
            self.writer.add_scalar('Combat/Damage_Dealt', tactical_data['damage_dealt'], self.episode_count)
        if 'damage_received' in tactical_data:
            self.writer.add_scalar('Combat/Damage_Received', tactical_data['damage_received'], self.episode_count)
        
        # 3. YOUR SPECIFICATION: ai_turn/invalid_action_rate - Rule violations (FULL DURATION)
        valid_actions = tactical_data.get('valid_actions', 0)
        invalid_actions = tactical_data.get('invalid_actions', 0)
        total_actions = valid_actions + invalid_actions
        
        if total_actions > 0:
            invalid_rate = invalid_actions / total_actions
            self.writer.add_scalar('ai_turn/invalid_action_rate', invalid_rate, self.episode_count)
            self.all_invalid_rates.append(invalid_rate)
            
            # Maintain existing compatibility
            action_efficiency = valid_actions / total_actions
            self.writer.add_scalar('AI_Quality/Action_Efficiency', action_efficiency, self.episode_count)
        
        # AI_TURN.md Compliance Metrics
        if 'phase_efficiency' in tactical_data:
            self.writer.add_scalar('AI_Turn/Phase_Efficiency', tactical_data['phase_efficiency'], self.episode_count)
        
        if 'turn_count' in tactical_data:
            self.writer.add_scalar('AI_Turn/Turns_Per_Episode', tactical_data['turn_count'], self.episode_count)
        
        # Sequential Activation Metrics
        phases_completed = tactical_data.get('phases_completed', 0)
        total_phases = tactical_data.get('total_phases', 1)
        if total_phases > 0:
            completion_rate = phases_completed / total_phases
            self.writer.add_scalar('AI_Turn/Phase_Completion_Rate', completion_rate, self.episode_count)
    
    def log_action_distribution(self, action_data: Dict[str, int]):
        """Log distribution of action types for tactical analysis"""
        total_actions = sum(action_data.values())
        
        if total_actions > 0:
            for action_type, count in action_data.items():
                percentage = count / total_actions
                self.writer.add_scalar(f'Actions/{action_type.title()}_Percentage', percentage, self.episode_count)
                self.writer.add_scalar(f'Actions/{action_type.title()}_Count', count, self.episode_count)
    
    def log_learning_metrics(self, learning_data: Dict[str, Any]):
        """Log advanced learning and convergence metrics"""
        
        # Q-Learning specific metrics
        if 'q_values' in learning_data:
            q_values = learning_data['q_values']
            self.writer.add_scalar('Learning/Q_Value_Mean', np.mean(q_values), self.step_count)
            self.writer.add_scalar('Learning/Q_Value_Std', np.std(q_values), self.step_count)
            self.writer.add_scalar('Learning/Q_Value_Max', np.max(q_values), self.step_count)
        
        # Action value distribution
        if 'action_values' in learning_data:
            action_values = learning_data['action_values']
            for i, value in enumerate(action_values):
                self.writer.add_scalar(f'Q_Values/Action_{i}', value, self.step_count)
        
        # Exploration vs Exploitation
        if 'epsilon' in learning_data:
            self.writer.add_scalar('Learning/Epsilon', learning_data['epsilon'], self.step_count)
        
        # Policy entropy (measure of exploration)
        if 'policy_entropy' in learning_data:
            self.writer.add_scalar('Learning/Policy_Entropy', learning_data['policy_entropy'], self.step_count)
    
    def log_training_step(self, step_data: Dict[str, Any]):
        """YOUR SPECIFICATION: Training metrics with exact naming"""
        self.step_count += 1
        
        # 4. YOUR SPECIFICATION: train/exploration_rate - Learning Balance
        if 'exploration_rate' in step_data:
            self.writer.add_scalar('train/exploration_rate', step_data['exploration_rate'], self.step_count)
        
        # 5. YOUR SPECIFICATION: train/loss - Neural Network Health
        if 'loss' in step_data:
            self.writer.add_scalar('train/loss', step_data['loss'], self.step_count)
        
        # Maintain existing compatibility
        if 'learning_rate' in step_data:
            self.writer.add_scalar('Training/Learning_Rate', step_data['learning_rate'], self.step_count)
    
    def _log_full_duration_trends(self):
        """Calculate trends over ENTIRE training duration (your specification)"""
        
        # Reward trend analysis over full training
        if len(self.all_episode_rewards) >= 10:
            x = np.arange(len(self.all_episode_rewards))
            y = np.array(self.all_episode_rewards)
            
            # Linear regression slope over ALL episodes
            trend_slope = np.polyfit(x, y, 1)[0]
            self.writer.add_scalar('episode/reward_trend', trend_slope, self.episode_count)
        
        # Invalid action rate trend (should decrease over time)
        if len(self.all_invalid_rates) >= 10:
            x = np.arange(len(self.all_invalid_rates))
            y = np.array(self.all_invalid_rates)
            
            # Negative slope indicates improvement
            invalid_trend = np.polyfit(x, y, 1)[0]
            self.writer.add_scalar('ai_turn/invalid_action_trend', invalid_trend, self.episode_count)
        
        # Learning progress indicators
        if len(self.all_episode_rewards) >= 100:
            # Compare recent 100 vs overall performance
            recent_mean = np.mean(self.all_episode_rewards[-100:])
            overall_mean = np.mean(self.all_episode_rewards)
            progress_indicator = recent_mean - overall_mean
            self.writer.add_scalar('episode/recent_vs_overall', progress_indicator, self.episode_count)
    
    def _log_rolling_averages(self):
        """Log comprehensive rolling averages for trend analysis"""
        min_episodes = 10
        
        # Core performance metrics
        if len(self.rolling_windows['rewards']) >= min_episodes:
            rewards = list(self.rolling_windows['rewards'])
            self.writer.add_scalar('Rolling/Reward_100ep', np.mean(rewards), self.episode_count)
            self.writer.add_scalar('Rolling/Reward_Std_100ep', np.std(rewards), self.episode_count)
            self.writer.add_scalar('Rolling/Reward_Min_100ep', np.min(rewards), self.episode_count)
            self.writer.add_scalar('Rolling/Reward_Max_100ep', np.max(rewards), self.episode_count)
            
        if len(self.rolling_windows['lengths']) >= min_episodes:
            lengths = list(self.rolling_windows['lengths'])
            self.writer.add_scalar('Rolling/Length_100ep', np.mean(lengths), self.episode_count)
            self.writer.add_scalar('Rolling/Length_Std_100ep', np.std(lengths), self.episode_count)
            
        if len(self.rolling_windows['wins']) >= min_episodes:
            wins = list(self.rolling_windows['wins'])
            win_rate = np.mean(wins)
            self.writer.add_scalar('Rolling/Win_Rate_100ep', win_rate, self.episode_count)
            
            # Win rate trend (last 25 vs previous 25)
            if len(wins) >= 50:
                recent_wins = wins[-25:]
                previous_wins = wins[-50:-25]
                recent_rate = np.mean(recent_wins)
                previous_rate = np.mean(previous_wins)
                trend = recent_rate - previous_rate
                self.writer.add_scalar('Rolling/Win_Rate_Trend', trend, self.episode_count)
        
        # Advanced performance indicators
        if len(self.rolling_windows['rewards']) >= 50:
            rewards = list(self.rolling_windows['rewards'])
            
            # Performance stability (coefficient of variation)
            if np.mean(rewards) != 0:
                cv = np.std(rewards) / abs(np.mean(rewards))
                self.writer.add_scalar('Rolling/Performance_Stability', 1.0 / (1.0 + cv), self.episode_count)
            
            # Learning progress (trend in last 25 episodes)
            recent_rewards = rewards[-25:]
            if len(recent_rewards) >= 25:
                # Simple linear trend
                x = np.arange(len(recent_rewards))
                trend = np.polyfit(x, recent_rewards, 1)[0]  # Slope of linear fit
                self.writer.add_scalar('Rolling/Learning_Trend', trend, self.episode_count)
    
    def get_performance_summary(self) -> Dict[str, float]:
        """Get current performance summary for monitoring"""
        summary = {}
        
        if len(self.rolling_windows['rewards']) >= 10:
            summary['avg_reward_100ep'] = np.mean(self.rolling_windows['rewards'])
            summary['reward_std_100ep'] = np.std(self.rolling_windows['rewards'])
            
        if len(self.rolling_windows['wins']) >= 10:
            summary['win_rate_100ep'] = np.mean(self.rolling_windows['wins'])
            
        if len(self.rolling_windows['lengths']) >= 10:
            summary['avg_length_100ep'] = np.mean(self.rolling_windows['lengths'])
            
        return summary
    
    def close(self):
        """Close tensorboard writer"""
        self.writer.close()

class TrainingMonitor:
    """Monitor training health and provide alerts"""
    
    def __init__(self, thresholds: Dict[str, float]):
        self.thresholds = thresholds
    
    def check_training_health(self, metrics_summary: Dict[str, float]) -> List[str]:
        """Check training health and return alerts"""
        alerts = []
        
        # Check win rate
        if 'win_rate_100ep' in metrics_summary:
            win_rate = metrics_summary['win_rate_100ep']
            min_win_rate = self.thresholds.get('min_win_rate', 0.3)
            if win_rate < min_win_rate:
                alerts.append(f"WARNING: Win rate ({win_rate:.2f}) below threshold ({min_win_rate})")
        
        # Check reward stability
        if 'reward_std_100ep' in metrics_summary and 'avg_reward_100ep' in metrics_summary:
            reward_std = metrics_summary['reward_std_100ep']
            avg_reward = metrics_summary['avg_reward_100ep']
            if abs(avg_reward) > 0.01:  # Avoid division by zero
                cv = reward_std / abs(avg_reward)  # Coefficient of variation
                max_cv = self.thresholds.get('max_reward_volatility', 2.0)
                if cv > max_cv:
                    alerts.append(f"WARNING: High reward volatility (CV={cv:.2f})")
        
        return alerts

# Integration function for existing training loop
def create_metrics_tracker(agent_key: str, config: Dict[str, Any]) -> W40KMetricsTracker:
    """Factory function to create metrics tracker with config"""
    log_dir = config.get('tensorboard_log', './tensorboard/')
    return W40KMetricsTracker(agent_key, log_dir)