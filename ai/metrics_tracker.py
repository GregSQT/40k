#!/usr/bin/env python3
"""
ai/metrics_tracker.py - W40K Training Metrics Tracker
Streamlined metrics for essential training indicators and tactical analysis

METRICS TRACKED (20 Total):
Core Training (5): episode/reward, episode/win_rate, ai_turn/invalid_action_rate, train/exploration_rate, train/loss
Combat (7): Shooting_Accuracy, Slaughter_Efficiency, Damage_Dealt/Received, damage_efficiency, units_lost/killed
Tactical (3): episode/length, actions/wait_frequency, AI_Quality/Action_Efficiency
Evaluation (4): eval_bots/* metrics (from train.py BotEvaluationCallback)
Quick Reference (1): Rolling/Win_Rate_100ep
"""

import numpy as np
from collections import deque
from torch.utils.tensorboard import SummaryWriter
import os
from typing import Dict, Any, List, Optional

class W40KMetricsTracker:
    """
    Tracks essential training metrics for W40K agents with tensorboard integration.
    Designed to work with existing multi_agent_trainer.py structure.
    Streamlined to 20 critical metrics, removing redundant calculations.
    """
    
    def __init__(self, agent_key: str, log_dir: str = "./tensorboard/"):
        self.agent_key = agent_key
        self.log_dir = os.path.join(log_dir, agent_key)
        self.writer = SummaryWriter(self.log_dir)
        
        # Rolling window for win rate only (100 episodes)
        self.win_rate_window = deque(maxlen=100)
        
        # FULL TRAINING DURATION TRACKING
        self.all_episode_rewards = []    # Complete reward history
        self.all_episode_wins = []       # Complete win/loss history
        
        # Episode tracking
        self.episode_count = 0
        self.step_count = 0
        
        print(f"✅ Metrics tracker initialized for {agent_key} -> {self.log_dir}")
        print(f"📊 Tracking 20 essential metrics (Core: 5, Combat: 7, Tactical: 3, Eval: 4, Quick: 1)")
    
    def log_episode_end(self, episode_data: Dict[str, Any]):
        """Log core episode metrics - reward, win rate, and episode length"""
        self.episode_count += 1
        
        # Extract data
        total_reward = episode_data.get('total_reward', 0)
        winner = episode_data.get('winner', None)
        episode_length = episode_data.get('episode_length', 0)
        
        # METRIC 1: episode/reward - Individual episode rewards
        self.writer.add_scalar('episode/reward', total_reward, self.episode_count)
        self.all_episode_rewards.append(total_reward)
        
        # METRIC 2: episode/win_rate - Cumulative win rate (FULL DURATION)
        if winner is not None:
            agent_won = 1.0 if winner == 1 else 0.0
            self.all_episode_wins.append(agent_won)
            self.win_rate_window.append(agent_won)
            
            # Calculate cumulative win rate over ENTIRE training
            cumulative_win_rate = np.mean(self.all_episode_wins)
            self.writer.add_scalar('episode/win_rate', cumulative_win_rate, self.episode_count)
            
            # METRIC 20: Rolling/Win_Rate_100ep - Quick reference (recent 100 episodes)
            if len(self.win_rate_window) >= 10:
                rolling_win_rate = np.mean(self.win_rate_window)
                self.writer.add_scalar('Rolling/Win_Rate_100ep', rolling_win_rate, self.episode_count)
        
        # METRIC 13: episode/length - Episode duration
        if episode_length > 0:
            self.writer.add_scalar('episode/length', episode_length, self.episode_count)
    
    def log_tactical_metrics(self, tactical_data: Dict[str, Any]):
        """Log tactical performance metrics - combat effectiveness and decision quality"""
        
        # METRIC 6: Combat/Shooting_Accuracy - Hit rate
        if 'shots_fired' in tactical_data and tactical_data['shots_fired'] > 0:
            hits = tactical_data.get('hits', 0)
            accuracy = hits / tactical_data['shots_fired']
            self.writer.add_scalar('Combat/Shooting_Accuracy', accuracy, self.episode_count)
        
        # METRIC 7: Combat/Slaughter_Efficiency - Kill rate
        if 'total_enemies' in tactical_data and tactical_data['total_enemies'] > 0:
            killed_enemies = tactical_data.get('killed_enemies', 0)
            slaughter_efficiency = killed_enemies / tactical_data['total_enemies']
            self.writer.add_scalar('Combat/Slaughter_Efficiency', slaughter_efficiency, self.episode_count)
        
        # METRIC 8: Combat/Damage_Dealt - Offensive power
        damage_dealt = tactical_data.get('damage_dealt', 0)
        if damage_dealt > 0:
            self.writer.add_scalar('Combat/Damage_Dealt', damage_dealt, self.episode_count)
        
        # METRIC 9: Combat/Damage_Received - Defensive capability
        damage_received = tactical_data.get('damage_received', 0)
        if damage_received > 0:
            self.writer.add_scalar('Combat/Damage_Received', damage_received, self.episode_count)
        
        # METRIC 10: combat/damage_efficiency - Trade effectiveness
        if damage_received > 0 and damage_dealt > 0:
            damage_efficiency = damage_dealt / damage_received
            self.writer.add_scalar('combat/damage_efficiency', damage_efficiency, self.episode_count)
        
        # METRIC 11: combat/units_lost - Unit preservation
        units_lost = tactical_data.get('units_lost', 0)
        if units_lost >= 0:
            self.writer.add_scalar('combat/units_lost', units_lost, self.episode_count)
        
        # METRIC 12: combat/units_killed - Lethality
        units_killed = tactical_data.get('units_killed', 0)
        if units_killed >= 0:
            self.writer.add_scalar('combat/units_killed', units_killed, self.episode_count)
        
        # Combat unit trade ratio (derived from units_lost and units_killed)
        if units_lost > 0 and units_killed > 0:
            trade_ratio = units_killed / units_lost
            self.writer.add_scalar('combat/unit_trade_ratio', trade_ratio, self.episode_count)
        
        # METRIC 3: ai_turn/invalid_action_rate - Rule compliance
        valid_actions = tactical_data.get('valid_actions', 0)
        invalid_actions = tactical_data.get('invalid_actions', 0)
        total_actions = valid_actions + invalid_actions
        
        if total_actions > 0:
            invalid_rate = invalid_actions / total_actions
            self.writer.add_scalar('ai_turn/invalid_action_rate', invalid_rate, self.episode_count)
            
            # METRIC 15: AI_Quality/Action_Efficiency - Valid action rate
            action_efficiency = valid_actions / total_actions
            self.writer.add_scalar('AI_Quality/Action_Efficiency', action_efficiency, self.episode_count)
        
        # METRIC 14: actions/wait_frequency - Decision confidence
        wait_actions = tactical_data.get('wait_actions', 0)
        if total_actions > 0:
            wait_frequency = wait_actions / total_actions
            self.writer.add_scalar('actions/wait_frequency', wait_frequency, self.episode_count)
    
    def log_training_step(self, step_data: Dict[str, Any]):
        """Log training step metrics - exploration rate and loss"""
        self.step_count += 1
        
        # METRIC 4: train/exploration_rate - Learning balance (exploration vs exploitation)
        if 'exploration_rate' in step_data:
            self.writer.add_scalar('train/exploration_rate', step_data['exploration_rate'], self.step_count)
        
        # METRIC 5: train/loss - Neural network training loss
        if 'loss' in step_data:
            self.writer.add_scalar('train/loss', step_data['loss'], self.step_count)
        
        # Optional: Learning rate tracking
        if 'learning_rate' in step_data:
            self.writer.add_scalar('train/learning_rate', step_data['learning_rate'], self.step_count)
    
    def get_performance_summary(self) -> Dict[str, float]:
        """Get current performance summary for monitoring"""
        summary = {}
        
        # Recent win rate (last 100 episodes)
        if len(self.win_rate_window) >= 10:
            summary['win_rate_100ep'] = np.mean(self.win_rate_window)
        
        # Overall statistics
        if len(self.all_episode_rewards) >= 10:
            summary['avg_reward_overall'] = np.mean(self.all_episode_rewards)
            summary['total_episodes'] = len(self.all_episode_rewards)
        
        if len(self.all_episode_wins) >= 10:
            summary['win_rate_overall'] = np.mean(self.all_episode_wins)
        
        return summary
    
    def close(self):
        """Close tensorboard writer"""
        self.writer.close()

class TrainingMonitor:
    """Monitor training health and provide alerts based on essential metrics"""
    
    def __init__(self, thresholds: Dict[str, float]):
        self.thresholds = thresholds
    
    def check_training_health(self, metrics_summary: Dict[str, float]) -> List[str]:
        """Check training health and return alerts"""
        alerts = []
        
        # Check win rate (recent 100 episodes)
        if 'win_rate_100ep' in metrics_summary:
            win_rate = metrics_summary['win_rate_100ep']
            min_win_rate = self.thresholds.get('min_win_rate', 0.3)
            if win_rate < min_win_rate:
                alerts.append(f"⚠️ Win rate ({win_rate:.1%}) below threshold ({min_win_rate:.1%})")
        
        # Check overall win rate
        if 'win_rate_overall' in metrics_summary:
            overall_win_rate = metrics_summary['win_rate_overall']
            if overall_win_rate < 0.4:
                alerts.append(f"⚠️ Overall win rate low ({overall_win_rate:.1%}) - may need training adjustment")
        
        # Check episode count
        if 'total_episodes' in metrics_summary:
            total_episodes = metrics_summary['total_episodes']
            if total_episodes < 100:
                alerts.append(f"ℹ️ Early training stage ({total_episodes} episodes) - metrics may be unstable")
        
        return alerts

# Integration function for existing training loop
def create_metrics_tracker(agent_key: str, config: Dict[str, Any]) -> W40KMetricsTracker:
    """Factory function to create metrics tracker with config"""
    log_dir = config.get('tensorboard_log', './tensorboard/')
    return W40KMetricsTracker(agent_key, log_dir)