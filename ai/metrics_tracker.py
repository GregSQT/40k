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
        self.all_episode_lengths = []    # Complete episode length history
        
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

        # NEW: Position score tracking (Phase 2+ movement rewards)
        self.position_scores = []  # Raw position_score values per move action
        
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

        # NEW: Combat effectiveness metrics (per RL_TRAINING_ROADMAP.md)
        # These 3 metrics tell you if the agent learns combat properly
        self.combat_effectiveness = {
            'shoot_kills': 0,      # Kills from ranged attacks
            'melee_kills': 0,      # Kills from melee attacks
            'charge_successes': 0  # Successful charges (reached target)
        }
        
        # NEW: Hyperparameter tracking for PPO tuning
        self.hyperparameter_tracking = {
            'learning_rates': [],
            'entropy_losses': [],
            'policy_losses': [],
            'value_losses': [],
            'clip_fractions': [],
            'approx_kls': [],
            'explained_variances': []  # For tuning dashboard
        }
        
        # NEW: Gradient norm tracking for 0_critical/ dashboard
        self.latest_gradient_norm = None
        
        # NEW: Bot evaluation combined score for 0_critical/ dashboard
        self.bot_eval_combined = None
        
        # NEW: Episode tactical data for invalid_action_rate tracking
        self.episode_tactical_data = {
            'total_actions': 0,
            'invalid_actions': 0,
            'valid_actions': 0
        }
        
        print(f"✅ Metrics tracker initialized for {agent_key} -> {self.log_dir}")
        print(f"📊 Metric System:")
        print(f"   🎯 0_critical/ (10) - Essential hyperparameter tuning metrics")
        print(f"   🎮 game_critical/ (5) - Core gameplay indicators")
        print(f"   ⚙️  training_critical/ (6) - PPO algorithm health")
        print(f"   💡 TIP: Start with 0_critical/ - everything you need for tuning")
    
    def log_episode_end(self, episode_data: Dict[str, Any]):
        """Log core episode metrics - reward, win rate, and episode length"""
        self.episode_count += 1

        # DIAGNOSTIC: Print episode count every 1000 episodes to track progress
        if self.episode_count % 1000 == 0:
            print(f"  📊 Metrics: Episode {self.episode_count} logged to TensorBoard (x-axis)")

        # Extract data
        total_reward = episode_data.get('total_reward', 0)
        winner = episode_data.get('winner', None)
        episode_length = episode_data.get('episode_length', 0)
        
        # GAME CRITICAL: Episode reward - Individual episode rewards
        self.writer.add_scalar('game_critical/episode_reward', total_reward, self.episode_count)
        self.all_episode_rewards.append(total_reward)
        
        # GAME CRITICAL: Win rate - Cumulative win rate (FULL DURATION)
        # CRITICAL FIX: Learning agent is Player 0, not Player 1!
        # winner == 0 means the learning agent won
        if winner is not None:
            agent_won = 1.0 if winner == 0 else 0.0
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
            self.all_episode_lengths.append(episode_length)  # Track for tuning dashboard
        
        # CRITICAL: Compute and log phase performance metrics at episode end
        self.compute_and_log_phase_metrics()
        
        # NEW: Log critical dashboard (10 essential hyperparameter tuning metrics)
        self.log_critical_dashboard()
        
        # Flush metrics to disk
        self.writer.flush()
    
    def log_tactical_metrics(self, tactical_data: Dict[str, Any]):
        """Log tactical performance metrics - combat effectiveness and decision quality"""
        
        # GAME TACTICAL: Shooting accuracy - Hit rate
        if 'shots_fired' in tactical_data and tactical_data['shots_fired'] > 0:
            hits = tactical_data.get('hits', 0)
            accuracy = hits / tactical_data['shots_fired']
            self.writer.add_scalar('game_tactical/shooting_accuracy', accuracy, self.episode_count)
        
        # GAME TACTICAL: Kill efficiency - Kill rate
        if 'total_enemies' in tactical_data and tactical_data['total_enemies'] > 0:
            killed_enemies = tactical_data.get('units_killed', 0)  # FIXED: use units_killed from engine
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

    def log_position_score(self, position_score: float):
        """Log raw position_score from movement rewards (Phase 2+ positioning metric).

        This tracks the pre-scaled offensive_value from movement actions.
        Higher values = unit moved to position with better shooting potential.

        Args:
            position_score: Raw position_score value (before position_reward_scale)
        """
        if position_score is None:
            return

        self.position_scores.append(position_score)

        # Keep last 1000 position scores
        if len(self.position_scores) > 1000:
            self.position_scores.pop(0)

        # Log rolling average every 10 moves
        if len(self.position_scores) >= 10 and len(self.position_scores) % 10 == 0:
            avg_position_score = np.mean(self.position_scores[-100:])  # Last 100 moves
            self.writer.add_scalar('game_tactical/avg_position_score', avg_position_score, self.episode_count)

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
    
    def log_combat_kill(self, kill_type: str):
        """Log a combat kill for tracking combat effectiveness.

        Args:
            kill_type: One of 'shoot', 'melee', or 'charge'
                      - 'shoot': Enemy killed by ranged attack
                      - 'melee': Enemy killed by melee attack in fight phase
                      - 'charge': Successful charge that reached target
        """
        if kill_type == 'shoot':
            self.combat_effectiveness['shoot_kills'] += 1
        elif kill_type == 'melee':
            self.combat_effectiveness['melee_kills'] += 1
        elif kill_type == 'charge':
            self.combat_effectiveness['charge_successes'] += 1

    def log_phase_performance(self, phase_data: Dict[str, Any]):
        """Accumulate phase-specific performance metrics during episode.
        
        This method only ACCUMULATES stats. Call compute_and_log_phase_metrics() 
        at episode end to calculate and log the actual metrics.
        
        ACCUMULATED METRICS:
        - movement: moved, waited, fled counts
        - shooting: shot, skipped counts
        - charge: charged, skipped counts
        - fight: fought, skipped counts
        """
        phase = phase_data.get('phase', 'unknown')
        action = phase_data.get('action', 'unknown')
        
        # Track phase-specific actions (accumulate only)
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
    
    def compute_and_log_phase_metrics(self):
        """Compute and log phase performance metrics at episode end.
        
        GAME TACTICAL METRICS (4):
        - game_tactical/movement_efficiency
        - game_tactical/shooting_participation
        - game_detailed/flee_rate
        - game_tactical/charge_rate
        
        Called once per episode after all actions are accumulated.
        """
        # GAME TACTICAL: Movement efficiency
        move_total = self.phase_stats['movement']['moved'] + self.phase_stats['movement']['waited']
        if move_total > 0:
            movement_efficiency = self.phase_stats['movement']['moved'] / move_total
            self.writer.add_scalar('game_tactical/movement_efficiency', movement_efficiency, self.episode_count)
            
            flee_rate = self.phase_stats['movement']['fled'] / move_total
            self.writer.add_scalar('game_detailed/flee_rate', flee_rate, self.episode_count)
        
        # GAME TACTICAL: Shooting participation
        shoot_total = self.phase_stats['shooting']['shot'] + self.phase_stats['shooting']['skipped']
        if shoot_total > 0:
            shooting_participation = self.phase_stats['shooting']['shot'] / shoot_total
            self.writer.add_scalar('game_tactical/shooting_participation', shooting_participation, self.episode_count)
        
        # GAME TACTICAL: Charge rate
        charge_total = self.phase_stats['charge']['charged'] + self.phase_stats['charge']['skipped']
        if charge_total > 0:
            charge_rate = self.phase_stats['charge']['charged'] / charge_total
            self.writer.add_scalar('game_tactical/charge_rate', charge_rate, self.episode_count)
        
        # Reset phase stats for next episode
        self.phase_stats = {
            'movement': {'moved': 0, 'waited': 0, 'fled': 0},
            'shooting': {'shot': 0, 'skipped': 0},
            'charge': {'charged': 0, 'skipped': 0},
            'fight': {'fought': 0, 'skipped': 0}
        }

        # Log combat effectiveness metrics (per RL_TRAINING_ROADMAP.md)
        self.writer.add_scalar('combat/shoot_kills', self.combat_effectiveness['shoot_kills'], self.episode_count)
        self.writer.add_scalar('combat/melee_kills', self.combat_effectiveness['melee_kills'], self.episode_count)
        self.writer.add_scalar('combat/charge_successes', self.combat_effectiveness['charge_successes'], self.episode_count)

        # Reset combat effectiveness for next episode
        self.combat_effectiveness = {
            'shoot_kills': 0,
            'melee_kills': 0,
            'charge_successes': 0
        }
    
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
            self.hyperparameter_tracking['explained_variances'].append(explained_var)
            self.writer.add_scalar('training_critical/explained_variance', explained_var, self.step_count)
        
        # TRAINING DIAGNOSTIC: Total policy updates count
        if 'train/n_updates' in model_stats:
            n_updates = model_stats['train/n_updates']
            self.writer.add_scalar('training_diagnostic/n_updates', n_updates, self.step_count)
        
        # TRAINING DIAGNOSTIC: Gradient norm (gradient explosion/vanishing check)
        if 'train/gradient_norm' in model_stats:
            grad_norm = model_stats['train/gradient_norm']
            self.latest_gradient_norm = grad_norm  # Store for 0_critical/ dashboard
            self.writer.add_scalar('training_diagnostic/gradient_norm', grad_norm, self.step_count)
        
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
    
    def log_critical_dashboard(self):
        """
        🎯 CRITICAL DASHBOARD - 10 Essential Hyperparameter Tuning Metrics
        
        This dashboard contains ONLY the metrics you need to tune PPO hyperparameters.
        All metrics are smoothed (20-episode rolling average) for clear trends.
        
        GAME PERFORMANCE (3 metrics):
        - 0_critical/a_bot_eval_combined    - Primary goal [0-1] (sorts first)
        - 0_critical/b_win_rate_100ep       - Training opponent performance
        - 0_critical/c_episode_reward_smooth  - Learning progress
        - 0_critical/d_position_score       - Phase 2+ positioning quality (offensive_value)
        
        PPO HEALTH (5 metrics):
        - 0_critical/clip_fraction         - [0.1-0.3] → Tune learning_rate
        - 0_critical/approx_kl             - <0.02 → Policy stability
        - 0_critical/explained_variance    - >0.3 → Value function working
        - 0_critical/entropy_loss          - [0.5-2.0] → Tune ent_coef
        - 0_critical/loss_mean             - Overall learning health
        
        TECHNICAL HEALTH (3 metrics):
        - 0_critical/gradient_norm         - <10 → No gradient explosion
        - 0_critical/immediate_reward_ratio - <0.9 → Reward balance
        - 0_critical/z_invalid_action_rate   - <0.1 → Action masking works
        - 0_critical/bot_eval_combined     - >0.4 → Wins vs bots (objective baseline)
        """
        
        # Minimum data requirement (lowered to 1 for immediate feedback)
        min_episodes = 1
        if len(self.all_episode_rewards) < min_episodes:
            return  # Not enough data yet
        
        # ==========================================
        # GAME PERFORMANCE (2 metrics)
        # ==========================================
        
        # 1. Win Rate (100-episode rolling window) - SORTS FIRST alphabetically
        if len(self.win_rate_window) >= 1:
            win_rate = np.mean(self.win_rate_window)
            self.writer.add_scalar('0_critical/b_win_rate_100ep', win_rate, self.step_count)

        # 2. Episode Reward (smoothed) - Training signal strength
        if len(self.all_episode_rewards) >= 1:
            reward_smooth = self._calculate_smoothed_metric(self.all_episode_rewards, window_size=20)
            self.writer.add_scalar('0_critical/c_episode_reward_smooth', reward_smooth, self.step_count)

        # 3. Position Score (smoothed) - Phase 2+ positioning quality
        if len(self.position_scores) >= 1:
            position_score_smooth = self._calculate_smoothed_metric(self.position_scores, window_size=100)
            self.writer.add_scalar('0_critical/d_position_score', position_score_smooth, self.step_count)

        # ==========================================
        # PPO HEALTH (5 metrics)
        # ==========================================

        # 3. Clip Fraction - Policy update scale
        if len(self.hyperparameter_tracking['clip_fractions']) >= 1:
            clip_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['clip_fractions'], window_size=20
            )
            self.writer.add_scalar('0_critical/f_clip_fraction', clip_smooth, self.step_count)

        # 4. Approx KL - Policy change magnitude
        if len(self.hyperparameter_tracking['approx_kls']) >= 1:
            kl_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['approx_kls'], window_size=20
            )
            self.writer.add_scalar('0_critical/g_approx_kl', kl_smooth, self.step_count)

        # 5. Explained Variance - Value function quality
        if len(self.hyperparameter_tracking.get('explained_variances', [])) >= 1:
            ev_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['explained_variances'], window_size=20
            )
            self.writer.add_scalar('0_critical/e_explained_variance', ev_smooth, self.step_count)

        # 6. Entropy Loss - Exploration health
        if len(self.hyperparameter_tracking['entropy_losses']) >= 1:
            entropy_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['entropy_losses'], window_size=20
            )
            self.writer.add_scalar('0_critical/h_entropy_loss', entropy_smooth, self.step_count)

        # 7. Loss Mean (combined policy + value loss) - Training stability
        if (len(self.hyperparameter_tracking['policy_losses']) >= 1 and
            len(self.hyperparameter_tracking['value_losses']) >= 1):
            # Calculate combined loss
            recent_policy = self.hyperparameter_tracking['policy_losses'][-20:]
            recent_value = self.hyperparameter_tracking['value_losses'][-20:]
            combined_losses = [abs(p) + abs(v) for p, v in zip(recent_policy, recent_value)]
            loss_mean = np.mean(combined_losses)
            self.writer.add_scalar('0_critical/d_loss_mean', loss_mean, self.step_count)
        
        # ==========================================
        # TECHNICAL HEALTH (3 metrics)
        # ==========================================
        
        # 8. Gradient Norm (direct value from latest training step) - Technical health
        if hasattr(self, 'latest_gradient_norm') and self.latest_gradient_norm is not None:
            self.writer.add_scalar('0_critical/i_gradient_norm', self.latest_gradient_norm, self.step_count)
        else:
            # Log placeholder if gradient_norm not available from stable-baselines3
            # This keeps the metric visible in TensorBoard even if SB3 doesn't log it
            if self.step_count <= 1:
                self.writer.add_scalar('0_critical/i_gradient_norm', 0.0, self.step_count)

        # 9. Immediate Reward Ratio (calculate from reward components) - Reward composition
        if (len(self.reward_components['base_actions']) >= 20 and
            len(self.all_episode_rewards) >= 20):
            recent_base = np.mean(self.reward_components['base_actions'][-20:])
            recent_total = np.mean(self.all_episode_rewards[-20:])
            if abs(recent_total) > 0.01:
                immediate_ratio = abs(recent_base) / abs(recent_total)
                self.writer.add_scalar('0_critical/j_immediate_reward_ratio', immediate_ratio, self.step_count)
        
        # 10. Bot Evaluation Combined Score (logged immediately in log_bot_evaluations())
        # NOTE: This metric is logged in log_bot_evaluations() to avoid duplicate/stale values
        # Do not log here - let log_bot_evaluations() handle it
        
        # Invalid Action Rate - Moved to game_critical (game-specific, not training-critical)
        if hasattr(self, 'episode_tactical_data') and self.episode_tactical_data:
            total_actions = self.episode_tactical_data.get('total_actions', 0)
            invalid_actions = self.episode_tactical_data.get('invalid_actions', 0)
            if total_actions > 0:
                invalid_rate = invalid_actions / total_actions
                self.writer.add_scalar('game_critical/invalid_action_rate', invalid_rate, self.episode_count)
            else:
                # Log zero if no actions yet
                self.writer.add_scalar('game_critical/invalid_action_rate', 0.0, self.episode_count)
    
    def log_bot_evaluations(self, bot_results: Dict[str, float]):
        """
        Log bot evaluation results to both 0_critical/ and bot_eval/ namespaces.

        Args:
            bot_results: Dict with keys 'random', 'greedy', 'defensive', 'combined'
        """
        # Log individual bot results to bot_eval/ namespace
        if 'random' in bot_results:
            self.writer.add_scalar('bot_eval/vs_random', bot_results['random'], self.step_count)
        if 'greedy' in bot_results:
            self.writer.add_scalar('bot_eval/vs_greedy', bot_results['greedy'], self.step_count)
        if 'defensive' in bot_results:
            self.writer.add_scalar('bot_eval/vs_defensive', bot_results['defensive'], self.step_count)

        # Store combined score and log immediately to both namespaces
        if 'combined' in bot_results:
            self.bot_eval_combined = bot_results['combined']
            # Log to bot_eval/ namespace
            self.writer.add_scalar('bot_eval/combined', bot_results['combined'], self.step_count)
            # Log IMMEDIATELY to 0_critical/ namespace (don't wait for next episode)
            self.writer.add_scalar('0_critical/a_bot_eval_combined', bot_results['combined'], self.step_count)
    
    def _calculate_smoothed_metric(self, values: List[float], window_size: int = 20) -> float:
        """
        Calculate exponentially weighted moving average (EWMA) for smooth trend visualization.
        
        Args:
            values: List of raw metric values
            window_size: Window size for smoothing (default: 20 episodes)
        
        Returns:
            Smoothed value using EWMA
        """
        if not values or len(values) == 0:
            return 0.0
        
        if len(values) < window_size:
            # Not enough data - return simple mean
            return np.mean(values)
        
        # Use last N values for rolling mean
        recent_values = values[-window_size:]
        return np.mean(recent_values)
    
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