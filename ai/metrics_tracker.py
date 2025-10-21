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
        
        # NEW: Reward decomposition tracking
        self.reward_components = {
            'base_actions': [],
            'result_bonuses': [],
            'tactical_bonuses': [],
            'situational': [],
            'penalties': []
        }
        
        # NEW: AI_TURN.md compliance tracking
        self.compliance_data = {
            'units_per_step': [],
            'phase_end_reasons': [],
            'tracking_violations': []
        }
        
        # NEW: Reward mapper effectiveness
        self.reward_mapper_stats = {
            'shooting_priority_correct': 0,
            'shooting_priority_total': 0,
            'movement_tactical_bonuses': 0,
            'movement_actions': 0,
            'mapper_failures': 0
        }
        
        # NEW: Phase performance
        self.phase_stats = {
            'movement': {'moved': 0, 'waited': 0, 'fled': 0},
            'shooting': {'shot': 0, 'skipped': 0},
            'charge': {'charged': 0, 'skipped': 0},
            'fight': {'fought': 0, 'skipped': 0}
        }
        
        print(f"✅ Metrics tracker initialized for {agent_key} -> {self.log_dir}")
        print(f"📊 Tracking 37 essential metrics (Core: 5, Combat: 7, Tactical: 3, Eval: 4, Quick: 1, NEW: 17)")
    
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
    
    def log_reward_decomposition(self, reward_data: Dict[str, Any]):
        """Log reward decomposition for debugging reward engineering.
        
        NEW METRICS (5):
        - reward/base_actions_total
        - reward/result_bonuses_total
        - reward/tactical_bonuses_total
        - reward/situational_total
        - reward/penalties_total
        """
        if not reward_data:
            return
        
        # Extract components
        base_actions = reward_data.get('base_actions', 0.0)
        result_bonuses = reward_data.get('result_bonuses', 0.0)
        tactical_bonuses = reward_data.get('tactical_bonuses', 0.0)
        situational = reward_data.get('situational', 0.0)
        penalties = reward_data.get('penalties', 0.0)
        
        # Track in history
        self.reward_components['base_actions'].append(base_actions)
        self.reward_components['result_bonuses'].append(result_bonuses)
        self.reward_components['tactical_bonuses'].append(tactical_bonuses)
        self.reward_components['situational'].append(situational)
        self.reward_components['penalties'].append(penalties)
        
        # Keep last 100 episodes
        for key in self.reward_components:
            if len(self.reward_components[key]) > 100:
                self.reward_components[key].pop(0)
        
        # Log to tensorboard
        self.writer.add_scalar('reward/base_actions_total', base_actions, self.episode_count)
        self.writer.add_scalar('reward/result_bonuses_total', result_bonuses, self.episode_count)
        self.writer.add_scalar('reward/tactical_bonuses_total', tactical_bonuses, self.episode_count)
        self.writer.add_scalar('reward/situational_total', situational, self.episode_count)
        self.writer.add_scalar('reward/penalties_total', penalties, self.episode_count)
    
    def log_aiturn_compliance(self, compliance_data: Dict[str, Any]):
        """Log AI_TURN.md compliance validation metrics.
        
        NEW METRICS (4):
        - sequential_activation/units_per_step
        - phase_completion/eligibility_based_ends  
        - tracking/duplicate_activation_attempts
        - tracking/pool_corruption_detected
        """
        # METRIC: Units per step (should always be 1.0)
        units_activated = compliance_data.get('units_activated_this_step', 1)
        self.compliance_data['units_per_step'].append(units_activated)
        if len(self.compliance_data['units_per_step']) > 1000:
            self.compliance_data['units_per_step'].pop(0)
        
        avg_units_per_step = np.mean(self.compliance_data['units_per_step'])
        self.writer.add_scalar('sequential_activation/units_per_step', avg_units_per_step, self.episode_count)
        
        # METRIC: Phase end reason
        phase_end_reason = compliance_data.get('phase_end_reason', 'unknown')
        if phase_end_reason == 'eligibility':
            self.compliance_data['phase_end_reasons'].append(1)
        elif phase_end_reason == 'step_count':
            self.compliance_data['phase_end_reasons'].append(0)
        
        if len(self.compliance_data['phase_end_reasons']) > 100:
            self.compliance_data['phase_end_reasons'].pop(0)
        
        if self.compliance_data['phase_end_reasons']:
            eligibility_rate = np.mean(self.compliance_data['phase_end_reasons'])
            self.writer.add_scalar('phase_completion/eligibility_based_ends', eligibility_rate, self.episode_count)
        
        # METRIC: Tracking violations
        duplicate_attempts = compliance_data.get('duplicate_activation_attempts', 0)
        pool_corruption = compliance_data.get('pool_corruption_detected', 0)
        
        self.writer.add_scalar('tracking/duplicate_activation_attempts', duplicate_attempts, self.episode_count)
        self.writer.add_scalar('tracking/pool_corruption_detected', pool_corruption, self.episode_count)
    
    def log_reward_mapper_effectiveness(self, mapper_data: Dict[str, Any]):
        """Log reward mapper validation metrics.
        
        NEW METRICS (4):
        - reward_mapper/shooting_priority_adherence
        - reward_mapper/movement_tactical_bonus_rate
        - reward_mapper/mapper_calculation_failures
        - reward_mapper/target_selection_quality
        """
        # Track shooting priority decisions
        if 'shooting_priority_correct' in mapper_data:
            self.reward_mapper_stats['shooting_priority_correct'] += mapper_data['shooting_priority_correct']
            self.reward_mapper_stats['shooting_priority_total'] += 1
        
        # Track movement tactical bonuses
        if 'movement_had_tactical_bonus' in mapper_data:
            if mapper_data['movement_had_tactical_bonus']:
                self.reward_mapper_stats['movement_tactical_bonuses'] += 1
            self.reward_mapper_stats['movement_actions'] += 1
        
        # Track mapper failures
        if mapper_data.get('mapper_failed', False):
            self.reward_mapper_stats['mapper_failures'] += 1
        
        # Log to tensorboard
        if self.reward_mapper_stats['shooting_priority_total'] > 0:
            adherence = self.reward_mapper_stats['shooting_priority_correct'] / self.reward_mapper_stats['shooting_priority_total']
            self.writer.add_scalar('reward_mapper/shooting_priority_adherence', adherence, self.episode_count)
        
        if self.reward_mapper_stats['movement_actions'] > 0:
            bonus_rate = self.reward_mapper_stats['movement_tactical_bonuses'] / self.reward_mapper_stats['movement_actions']
            self.writer.add_scalar('reward_mapper/movement_tactical_bonus_rate', bonus_rate, self.episode_count)
        
        self.writer.add_scalar('reward_mapper/mapper_calculation_failures', self.reward_mapper_stats['mapper_failures'], self.episode_count)
    
    def log_phase_performance(self, phase_data: Dict[str, Any]):
        """Log phase-specific performance metrics.
        
        NEW METRICS (4):
        - phase/movement_efficiency
        - phase/shooting_participation
        - phase/flee_rate
        - phase/charge_rate
        """
        phase = phase_data.get('phase', 'unknown')
        action = phase_data.get('action', 'unknown')
        
        # Track phase-specific actions
        if phase == 'move':
            if action == 'move':
                self.phase_stats['movement']['moved'] += 1
            elif action == 'wait' or action == 'skip':
                self.phase_stats['movement']['waited'] += 1
            if phase_data.get('was_flee', False):
                self.phase_stats['movement']['fled'] += 1
        
        elif phase == 'shoot':
            if action == 'shoot':
                self.phase_stats['shooting']['shot'] += 1
            elif action == 'wait' or action == 'skip':
                self.phase_stats['shooting']['skipped'] += 1
        
        elif phase == 'charge':
            if action == 'charge':
                self.phase_stats['charge']['charged'] += 1
            elif action == 'wait' or action == 'skip':
                self.phase_stats['charge']['skipped'] += 1
        
        elif phase == 'fight':
            if action == 'combat' or action == 'fight':
                self.phase_stats['fight']['fought'] += 1
            elif action == 'wait' or action == 'skip':
                self.phase_stats['fight']['skipped'] += 1
        
        # Calculate and log rates
        move_total = self.phase_stats['movement']['moved'] + self.phase_stats['movement']['waited']
        if move_total > 0:
            movement_efficiency = self.phase_stats['movement']['moved'] / move_total
            self.writer.add_scalar('phase/movement_efficiency', movement_efficiency, self.episode_count)
            
            flee_rate = self.phase_stats['movement']['fled'] / move_total
            self.writer.add_scalar('phase/flee_rate', flee_rate, self.episode_count)
        
        shoot_total = self.phase_stats['shooting']['shot'] + self.phase_stats['shooting']['skipped']
        if shoot_total > 0:
            shooting_participation = self.phase_stats['shooting']['shot'] / shoot_total
            self.writer.add_scalar('phase/shooting_participation', shooting_participation, self.episode_count)
        
        charge_total = self.phase_stats['charge']['charged'] + self.phase_stats['charge']['skipped']
        if charge_total > 0:
            charge_rate = self.phase_stats['charge']['charged'] / charge_total
            self.writer.add_scalar('phase/charge_rate', charge_rate, self.episode_count)
    
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