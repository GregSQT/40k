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
        
        # Rolling windows for smoothed metrics
        self.rolling_windows = defaultdict(lambda: deque(maxlen=100))
        
        # Episode tracking
        self.episode_count = 0
        self.step_count = 0
        
        print(f"Metrics tracker initialized for {agent_key} -> {self.log_dir}")
    
    def log_episode_end(self, episode_data: Dict[str, Any]):
        """Log episode-level metrics to tensorboard"""
        self.episode_count += 1
        
        # Core training metrics
        total_reward = episode_data.get('total_reward', 0)
        episode_length = episode_data.get('steps', 0)
        winner = episode_data.get('winner', None)
        
        self.writer.add_scalar('Episode/Reward', total_reward, self.episode_count)
        self.writer.add_scalar('Episode/Length', episode_length, self.episode_count)
        
        if winner is not None:
            # Convert winner to win/loss for this agent (assuming agent is player 1)
            agent_won = 1.0 if winner == 1 else 0.0
            self.writer.add_scalar('Episode/Win', agent_won, self.episode_count)
        
        # Update rolling windows
        self.rolling_windows['rewards'].append(total_reward)
        self.rolling_windows['lengths'].append(episode_length)
        if winner is not None:
            self.rolling_windows['wins'].append(agent_won)
        
        # Log rolling averages every 10 episodes
        if self.episode_count % 10 == 0:
            self._log_rolling_averages()
    
    def log_tactical_metrics(self, tactical_data: Dict[str, Any]):
        """Log W40K-specific tactical performance metrics"""
        
        # Shooting accuracy
        if 'shots_fired' in tactical_data and tactical_data['shots_fired'] > 0:
            hits = tactical_data.get('hits', 0)
            accuracy = hits / tactical_data['shots_fired']
            self.writer.add_scalar('Tactics/Shooting_Accuracy', accuracy, self.episode_count)
        
        # Slaughter efficiency - combat effectiveness metric
        if 'total_enemies' in tactical_data and tactical_data['total_enemies'] > 0:
            killed_enemies = tactical_data.get('killed_enemies', 0)
            slaughter_efficiency = killed_enemies / tactical_data['total_enemies']
            self.writer.add_scalar('Tactics/Slaughter_Efficiency', slaughter_efficiency, self.episode_count)    
        
        # Action quality
        total_actions = tactical_data.get('total_actions', 0)
        if total_actions > 0:
            invalid_actions = tactical_data.get('invalid_actions', 0)
            invalid_rate = invalid_actions / total_actions
            self.writer.add_scalar('Training/Invalid_Action_Rate', invalid_rate, self.episode_count)
        
        # Phase completion
        phases_completed = tactical_data.get('phases_completed', 0)
        total_phases = tactical_data.get('total_phases', 1)
        completion_rate = phases_completed / total_phases
        self.writer.add_scalar('Tactics/Phase_Completion_Rate', completion_rate, self.episode_count)
    
    def log_training_step(self, step_data: Dict[str, Any]):
        """Log per-step training metrics"""
        self.step_count += 1
        
        # Log learning rate if available
        if 'learning_rate' in step_data:
            self.writer.add_scalar('Training/Learning_Rate', step_data['learning_rate'], self.step_count)
        
        # Log loss if available  
        if 'loss' in step_data:
            self.writer.add_scalar('Training/Loss', step_data['loss'], self.step_count)
        
        # Log exploration rate
        if 'exploration_rate' in step_data:
            self.writer.add_scalar('Training/Exploration_Rate', step_data['exploration_rate'], self.step_count)
    
    def _log_rolling_averages(self):
        """Log rolling averages for smoothed metrics"""
        if len(self.rolling_windows['rewards']) >= 10:
            avg_reward = np.mean(self.rolling_windows['rewards'])
            self.writer.add_scalar('Rolling/Reward_100ep', avg_reward, self.episode_count)
            
        if len(self.rolling_windows['lengths']) >= 10:
            avg_length = np.mean(self.rolling_windows['lengths'])
            self.writer.add_scalar('Rolling/Length_100ep', avg_length, self.episode_count)
            
        if len(self.rolling_windows['wins']) >= 10:
            win_rate = np.mean(self.rolling_windows['wins'])
            self.writer.add_scalar('Rolling/Win_Rate_100ep', win_rate, self.episode_count)
    
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