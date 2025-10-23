#!/usr/bin/env python3
"""
ai/metrics_tracker.py - W40K Training Metrics Tracker
Professional dual 3-tier metric organization for game performance and training health

DUAL TIER SYSTEM (41 Total Metrics):

🎮 GAME PERFORMANCE SYSTEM (25 metrics)
  🔥 game_critical/ (5) - Core gameplay success indicators
     - win_rate_100ep, episode_reward, episode_length, 
       units_killed_vs_lost_ratio, invalid_action_rate
  
  🎯 game_tactical/ (8) - Tactical decision quality
     - shooting_accuracy, damage_efficiency, unit_trade_ratio,
       movement_efficiency, shooting_participation, charge_rate,
       action_efficiency, wait_frequency
  
  🔬 game_detailed/ (12+) - Deep tactical analysis
     - reward_decomposition (5), phase_performance (4),
       aiturn_compliance (3+)

⚙️ TRAINING HEALTH SYSTEM (16 metrics)
  🔥 training_critical/ (6) - Algorithm health indicators
     - policy_loss, value_loss, explained_variance,
       clip_fraction, approx_kl, fps
  
  🔍 training_diagnostic/ (5) - Hyperparameter monitoring
     - learning_rate, entropy_coef, entropy_loss, n_updates, gradient_norm
  
  🔬 training_detailed/ (5+) - Deep algorithm diagnostics
     - advantage metrics, policy gradient details, value function analysis
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
        
        # NEW: Hyperparameter tracking for PPO tuning
        self.hyperparameter_tracking = {
            'learning_rates': [],
            'entropy_losses': [],
            'policy_losses': [],
            'value_losses': [],
            'clip_fractions': [],
            'approx_kls': []
        }
        
        print(f"✅ Metrics tracker initialized for {agent_key} -> {self.log_dir}")
        print(f"📊 Dual 3-Tier Metric System (41 total metrics):")
        print(f"   🎮 Game Performance: game_critical/ (5), game_tactical/ (8), game_detailed/ (12+)")
        print(f"   ⚙️  Training Health: training_critical/ (6), training_diagnostic/ (5), training_detailed/ (5+)")
        print(f"   💡 TIP: Start with game_critical/ and training_critical/ namespaces")
    
    def log_episode_end(self, episode_data: Dict[str, Any]):
        """Log core episode metrics - reward, win rate, and episode length"""
        self.episode_count += 1
        
        # Extract data
        total_reward = episode_data.get('total_reward', 0)
        winner = episode_data.get('winner', None)
        episode_length = episode_data.get('episode_length', 0)
        
        # GAME CRITICAL: Episode reward - Individual episode rewards
        self.writer.add_scalar('game_critical/episode_reward', total_reward, self.episode_count)
        self.all_episode_rewards.append(total_reward)
        
        # GAME CRITICAL: Win rate - Cumulative win rate (FULL DURATION)
        if winner is not None:
            agent_won = 1.0 if winner == 1 else 0.0
            self.all_episode_wins.append(agent_won)
            self.win_rate_window.append(agent_won)
            
            # Calculate cumulative win rate over ENTIRE training
            cumulative_win_rate = np.mean(self.all_episode_wins)
            self.writer.add_scalar('game_critical/win_rate_overall', cumulative_win_rate, self.episode_count)
            
            # GAME CRITICAL: Rolling win rate (recent 100 episodes) - PRIMARY METRIC
            if len(self.win_rate_window) >= 10:
                rolling_win_rate = np.mean(self.win_rate_window)
                self.writer.add_scalar('game_critical/win_rate_100ep', rolling_win_rate, self.episode_count)
        
        # GAME CRITICAL: Episode length - Episode duration stability
        if episode_length > 0:
            self.writer.add_scalar('game_critical/episode_length', episode_length, self.episode_count)
    
    def log_tactical_metrics(self, tactical_data: Dict[str, Any]):
        """Log tactical performance metrics - combat effectiveness and decision quality"""
        
        # GAME TACTICAL: Shooting accuracy - Hit rate
        if 'shots_fired' in tactical_data and tactical_data['shots_fired'] > 0:
            hits = tactical_data.get('hits', 0)
            accuracy = hits / tactical_data['shots_fired']
            self.writer.add_scalar('game_tactical/shooting_accuracy', accuracy, self.episode_count)
        
        # GAME TACTICAL: Kill efficiency - Kill rate
        if 'total_enemies' in tactical_data and tactical_data['total_enemies'] > 0:
            killed_enemies = tactical_data.get('killed_enemies', 0)
            slaughter_efficiency = killed_enemies / tactical_data['total_enemies']
            self.writer.add_scalar('game_tactical/kill_efficiency', slaughter_efficiency, self.episode_count)
        
        # GAME DETAILED: Damage dealt - Offensive power
        damage_dealt = tactical_data.get('damage_dealt', 0)
        if damage_dealt > 0:
            self.writer.add_scalar('game_detailed/damage_dealt', damage_dealt, self.episode_count)
        
        # GAME DETAILED: Damage received - Defensive capability
        damage_received = tactical_data.get('damage_received', 0)
        if damage_received > 0:
            self.writer.add_scalar('game_detailed/damage_received', damage_received, self.episode_count)
        
        # GAME TACTICAL: Damage efficiency - Trade effectiveness
        if damage_received > 0 and damage_dealt > 0:
            damage_efficiency = damage_dealt / damage_received
            self.writer.add_scalar('game_tactical/damage_efficiency', damage_efficiency, self.episode_count)
        
        # GAME DETAILED: Units lost - Unit preservation
        units_lost = tactical_data.get('units_lost', 0)
        if units_lost >= 0:
            self.writer.add_scalar('game_detailed/units_lost', units_lost, self.episode_count)
        
        # GAME DETAILED: Units killed - Lethality
        units_killed = tactical_data.get('units_killed', 0)
        if units_killed >= 0:
            self.writer.add_scalar('game_detailed/units_killed', units_killed, self.episode_count)
        
        # GAME CRITICAL: Unit trade ratio (killed/lost) - Core success metric
        if units_lost > 0 and units_killed > 0:
            trade_ratio = units_killed / units_lost
            self.writer.add_scalar('game_critical/units_killed_vs_lost_ratio', trade_ratio, self.episode_count)
        
        # GAME TACTICAL: Unit trade ratio (absolute)
        if units_lost > 0 and units_killed > 0:
            trade_ratio = units_killed / units_lost
            self.writer.add_scalar('game_tactical/unit_trade_ratio', trade_ratio, self.episode_count)
        
        # GAME CRITICAL: Invalid action rate - AI_TURN.md compliance
        valid_actions = tactical_data.get('valid_actions', 0)
        invalid_actions = tactical_data.get('invalid_actions', 0)
        total_actions = valid_actions + invalid_actions
        
        if total_actions > 0:
            invalid_rate = invalid_actions / total_actions
            self.writer.add_scalar('game_critical/invalid_action_rate', invalid_rate, self.episode_count)
            
            # GAME TACTICAL: Action efficiency - Valid action rate
            action_efficiency = valid_actions / total_actions
            self.writer.add_scalar('game_tactical/action_efficiency', action_efficiency, self.episode_count)
        
        # GAME TACTICAL: Wait frequency - Decision confidence
        wait_actions = tactical_data.get('wait_actions', 0)
        if total_actions > 0:
            wait_frequency = wait_actions / total_actions
            self.writer.add_scalar('game_tactical/wait_frequency', wait_frequency, self.episode_count)
    
    def log_training_step(self, step_data: Dict[str, Any]):
        """Log training step metrics - exploration rate and loss"""
        self.step_count += 1
        
        # TRAINING DIAGNOSTIC: Exploration rate - Learning balance (exploration vs exploitation)
        if 'exploration_rate' in step_data:
            self.writer.add_scalar('training_diagnostic/exploration_rate', step_data['exploration_rate'], self.step_count)
        
        # TRAINING DETAILED: General loss - Neural network training loss
        if 'loss' in step_data:
            self.writer.add_scalar('training_detailed/loss', step_data['loss'], self.step_count)
        
        # TRAINING DIAGNOSTIC: Learning rate tracking
        if 'learning_rate' in step_data:
            self.writer.add_scalar('training_diagnostic/learning_rate', step_data['learning_rate'], self.step_count)
    
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
        
        # Validate required fields - raise errors for missing data, NO DEFAULTS
        required_fields = ['base_actions', 'result_bonuses', 'tactical_bonuses', 'situational', 'penalties']
        for field in required_fields:
            if field not in reward_data:
                raise KeyError(
                    f"Missing required field '{field}' in reward_data. "
                    f"Got keys: {list(reward_data.keys())}. "
                    f"All reward calculations must provide complete breakdown."
                )
        
        # Extract components - all fields validated above
        base_actions = reward_data['base_actions']
        result_bonuses = reward_data['result_bonuses']
        tactical_bonuses = reward_data['tactical_bonuses']
        situational = reward_data['situational']
        penalties = reward_data['penalties']
        
        # Validate types - must be numeric
        for field_name, field_value in [
            ('base_actions', base_actions), 
            ('result_bonuses', result_bonuses), 
            ('tactical_bonuses', tactical_bonuses), 
            ('situational', situational), 
            ('penalties', penalties)
        ]:
            if not isinstance(field_value, (int, float)):
                raise TypeError(
                    f"Reward field '{field_name}' must be numeric, got {type(field_value)}: {field_value}"
                )
        
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
    
    def log_aiturn_compliance(self, compliance_data: Dict[str, Any]):
        """Log AI_TURN.md compliance validation metrics.
        
        GAME DETAILED METRICS (4):
        - game_detailed/aiturn_units_per_step
        - game_detailed/aiturn_eligibility_based_ends  
        - game_detailed/aiturn_duplicate_activations
        - game_detailed/aiturn_pool_corruption
        """
        # GAME DETAILED: Units per step (should always be 1.0)
        units_activated = compliance_data.get('units_activated_this_step', 1)
        self.compliance_data['units_per_step'].append(units_activated)
        if len(self.compliance_data['units_per_step']) > 1000:
            self.compliance_data['units_per_step'].pop(0)
        
        avg_units_per_step = np.mean(self.compliance_data['units_per_step'])
        self.writer.add_scalar('game_detailed/aiturn_units_per_step', avg_units_per_step, self.episode_count)
        
        # GAME DETAILED: Phase end reason
        phase_end_reason = compliance_data.get('phase_end_reason', 'unknown')
        if phase_end_reason == 'eligibility':
            self.compliance_data['phase_end_reasons'].append(1)
        elif phase_end_reason == 'step_count':
            self.compliance_data['phase_end_reasons'].append(0)
        
        if len(self.compliance_data['phase_end_reasons']) > 100:
            self.compliance_data['phase_end_reasons'].pop(0)
        
        if self.compliance_data['phase_end_reasons']:
            eligibility_rate = np.mean(self.compliance_data['phase_end_reasons'])
            self.writer.add_scalar('game_detailed/aiturn_eligibility_based_ends', eligibility_rate, self.episode_count)
        
        # GAME DETAILED: Tracking violations
        duplicate_attempts = compliance_data.get('duplicate_activation_attempts', 0)
        pool_corruption = compliance_data.get('pool_corruption_detected', 0)
        
        self.writer.add_scalar('game_detailed/aiturn_duplicate_activations', duplicate_attempts, self.episode_count)
        self.writer.add_scalar('game_detailed/aiturn_pool_corruption', pool_corruption, self.episode_count)
    
    def log_reward_mapper_effectiveness(self, mapper_data: Dict[str, Any]):
        """Log reward mapper validation metrics.
        
        GAME DETAILED METRICS (4):
        - game_detailed/reward_mapper_shooting_priority
        - game_detailed/reward_mapper_movement_bonus_rate
        - game_detailed/reward_mapper_calculation_failures
        - game_detailed/reward_mapper_target_selection
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
        
        # GAME DETAILED: Log to tensorboard
        if self.reward_mapper_stats['shooting_priority_total'] > 0:
            adherence = self.reward_mapper_stats['shooting_priority_correct'] / self.reward_mapper_stats['shooting_priority_total']
            self.writer.add_scalar('game_detailed/reward_mapper_shooting_priority', adherence, self.episode_count)
        
        if self.reward_mapper_stats['movement_actions'] > 0:
            bonus_rate = self.reward_mapper_stats['movement_tactical_bonuses'] / self.reward_mapper_stats['movement_actions']
            self.writer.add_scalar('game_detailed/reward_mapper_movement_bonus_rate', bonus_rate, self.episode_count)
        
        self.writer.add_scalar('game_detailed/reward_mapper_calculation_failures', self.reward_mapper_stats['mapper_failures'], self.episode_count)
    
    def log_phase_performance(self, phase_data: Dict[str, Any]):
        """Log phase-specific performance metrics.
        
        GAME TACTICAL METRICS (4):
        - game_tactical/movement_efficiency
        - game_tactical/shooting_participation
        - game_detailed/flee_rate
        - game_tactical/charge_rate
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
        
        # GAME TACTICAL: Calculate and log rates
        move_total = self.phase_stats['movement']['moved'] + self.phase_stats['movement']['waited']
        if move_total > 0:
            movement_efficiency = self.phase_stats['movement']['moved'] / move_total
            self.writer.add_scalar('game_tactical/movement_efficiency', movement_efficiency, self.episode_count)
            
            flee_rate = self.phase_stats['movement']['fled'] / move_total
            self.writer.add_scalar('game_detailed/flee_rate', flee_rate, self.episode_count)
        
        shoot_total = self.phase_stats['shooting']['shot'] + self.phase_stats['shooting']['skipped']
        if shoot_total > 0:
            shooting_participation = self.phase_stats['shooting']['shot'] / shoot_total
            self.writer.add_scalar('game_tactical/shooting_participation', shooting_participation, self.episode_count)
        
        charge_total = self.phase_stats['charge']['charged'] + self.phase_stats['charge']['skipped']
        if charge_total > 0:
            charge_rate = self.phase_stats['charge']['charged'] / charge_total
            self.writer.add_scalar('game_tactical/charge_rate', charge_rate, self.episode_count)
    
    def log_training_metrics(self, model_stats: Dict[str, Any]):
        """
        Log PPO hyperparameter and algorithm health metrics from stable-baselines3.
        
        TRAINING CRITICAL METRICS (6):
        - training_critical/policy_loss - PPO policy gradient loss
        - training_critical/value_loss - Value function loss component
        - training_critical/explained_variance - Value function prediction quality
        - training_critical/clip_fraction - Fraction of policy updates clipped
        - training_critical/approx_kl - KL divergence between old/new policy
        - training_critical/fps - Training speed
        
        TRAINING DIAGNOSTIC METRICS (5):
        - training_diagnostic/learning_rate - Current learning rate value
        - training_diagnostic/entropy_coef - Current entropy coefficient
        - training_diagnostic/entropy_loss - Entropy bonus loss
        - training_diagnostic/n_updates - Total policy updates count
        - training_diagnostic/gradient_norm - Gradient magnitude (if available)
        
        Args:
            model_stats: Dictionary from stable-baselines3 logger (model.logger.name_to_value)
        """
        
        # TRAINING DIAGNOSTIC: Learning rate (critical for convergence monitoring)
        if 'train/learning_rate' in model_stats:
            lr = model_stats['train/learning_rate']
            self.hyperparameter_tracking['learning_rates'].append(lr)
            self.writer.add_scalar('training_diagnostic/learning_rate', lr, self.step_count)
        
        # TRAINING CRITICAL: Policy gradient loss (PPO policy loss component)
        if 'train/policy_gradient_loss' in model_stats:
            policy_loss = model_stats['train/policy_gradient_loss']
            self.hyperparameter_tracking['policy_losses'].append(policy_loss)
            self.writer.add_scalar('training_critical/policy_loss', policy_loss, self.step_count)
        
        # TRAINING CRITICAL: Value function loss (critic loss component)
        if 'train/value_loss' in model_stats:
            value_loss = model_stats['train/value_loss']
            self.hyperparameter_tracking['value_losses'].append(value_loss)
            self.writer.add_scalar('training_critical/value_loss', value_loss, self.step_count)
        
        # TRAINING DIAGNOSTIC: Entropy loss (exploration bonus component)
        if 'train/entropy_loss' in model_stats:
            entropy_loss = model_stats['train/entropy_loss']
            self.hyperparameter_tracking['entropy_losses'].append(entropy_loss)
            self.writer.add_scalar('training_diagnostic/entropy_loss', entropy_loss, self.step_count)
            
            # TRAINING DIAGNOSTIC: Also log current entropy coefficient value if available
            if 'train/ent_coef' in model_stats:
                ent_coef = model_stats['train/ent_coef']
                self.writer.add_scalar('training_diagnostic/entropy_coef', ent_coef, self.step_count)
        
        # TRAINING CRITICAL: Clip fraction (how often PPO clips policy updates)
        if 'train/clip_fraction' in model_stats:
            clip_fraction = model_stats['train/clip_fraction']
            self.hyperparameter_tracking['clip_fractions'].append(clip_fraction)
            self.writer.add_scalar('training_critical/clip_fraction', clip_fraction, self.step_count)
        
        # TRAINING CRITICAL: Approximate KL divergence (policy change magnitude)
        if 'train/approx_kl' in model_stats:
            approx_kl = model_stats['train/approx_kl']
            self.hyperparameter_tracking['approx_kls'].append(approx_kl)
            self.writer.add_scalar('training_critical/approx_kl', approx_kl, self.step_count)
        
        # TRAINING CRITICAL: Explained variance (value function quality)
        if 'train/explained_variance' in model_stats:
            explained_var = model_stats['train/explained_variance']
            self.writer.add_scalar('training_critical/explained_variance', explained_var, self.step_count)
        
        # TRAINING DIAGNOSTIC: Total policy updates count
        if 'train/n_updates' in model_stats:
            n_updates = model_stats['train/n_updates']
            self.writer.add_scalar('training_diagnostic/n_updates', n_updates, self.step_count)
        
        # TRAINING CRITICAL: Frames per second (training efficiency)
        if 'time/fps' in model_stats:
            fps = model_stats['time/fps']
            self.writer.add_scalar('training_critical/fps', fps, self.step_count)
        
        # TRAINING DETAILED: Additional advanced metrics if available
        if 'train/policy_loss' in model_stats:
            self.writer.add_scalar('training_detailed/policy_loss_raw', model_stats['train/policy_loss'], self.step_count)
        
        if 'train/value_loss' in model_stats:
            self.writer.add_scalar('training_detailed/value_loss_raw', model_stats['train/value_loss'], self.step_count)
        
        # Update step count for next logging
        self.step_count += 1
    
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
        
        # Hyperparameter health indicators
        if len(self.hyperparameter_tracking['learning_rates']) >= 10:
            summary['current_learning_rate'] = self.hyperparameter_tracking['learning_rates'][-1]
        
        if len(self.hyperparameter_tracking['entropy_losses']) >= 10:
            summary['avg_entropy_loss'] = np.mean(self.hyperparameter_tracking['entropy_losses'][-100:])
        
        if len(self.hyperparameter_tracking['clip_fractions']) >= 10:
            summary['avg_clip_fraction'] = np.mean(self.hyperparameter_tracking['clip_fractions'][-100:])
        
        if len(self.hyperparameter_tracking['approx_kls']) >= 10:
            summary['avg_approx_kl'] = np.mean(self.hyperparameter_tracking['approx_kls'][-100:])
        
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