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
from shared.data_validation import require_key

class W40KMetricsTracker:
    """
    Tracks essential training metrics for W40K agents with tensorboard integration.
    Designed to work with existing multi_agent_trainer.py structure.
    Streamlined to 20 critical metrics, removing redundant calculations.
    """
    
    def __init__(
        self,
        agent_key: str,
        log_dir: str = "./tensorboard/",
        initial_episode_count: int = 0,
        initial_step_count: int = 0,
        show_banner: bool = True
    ):
        self.agent_key = agent_key
        self.log_dir = os.path.join(log_dir, agent_key)
        self.writer = SummaryWriter(self.log_dir)
        
        # Rolling window for win rate only (100 episodes)
        self.win_rate_window = deque(maxlen=100)
        
        # Reward-victory correlation: (reward, outcome_flag) pairs for last N episodes.
        # outcome_flag: 1 = agent win, 0 = agent loss, -1 = draw.
        self.episode_reward_winner_pairs = deque(maxlen=200)
        
        # FULL TRAINING DURATION TRACKING
        self.all_episode_rewards = []    # Complete reward history
        self.all_episode_wins = []       # Complete win/loss history
        self.all_episode_lengths = []    # Complete episode length history
        
        # Episode tracking
        self.episode_count = initial_episode_count
        self.step_count = initial_step_count
        
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
        # These metrics tell you if the agent learns combat properly
        self.combat_effectiveness = {
            'shoot_kills': 0,      # Kills from ranged attacks
            'melee_kills': 0,      # Kills from melee attacks
            'charge_successes': 0, # Successful charges (reached target)
            'victory_points_cumulative': 0.0  # Cumulative victory points at episode end
        }

        # Rolling history for smoothed combat metrics
        self.combat_history = {
            'shoot_kills': [],
            'melee_kills': [],
            'charge_successes': [],
            'victory_points_cumulative': []
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

        # Unit-rule forcing instrumentation (episode exposure + bot-eval impact)
        self.forcing_tracking = {
            'episodes_total': 0,
            'episodes_with_forced_unit': 0,
            'forced_unit_instances_total': 0,
            'per_unit_episode_counts': {},   # unit_name -> episodes where present
            'per_unit_instance_counts': {},  # unit_name -> total instances
            'baseline_combined': None,       # first combined after forcing exposure starts
            'baseline_worst_bot': None,      # first worst_bot_score after forcing exposure starts
        }
        
        # NEW: Latest VALUE trade ratio for 0_critical/ dashboard
        self.latest_value_trade_ratio = None
        self.value_trade_ratio_history: List[float] = []
        
        # NEW: Episode tactical data for invalid_action_rate tracking
        self.episode_tactical_data = {
            'total_actions': 0,
            'invalid_actions': 0,
            'valid_actions': 0
        }
        # Seat-aware tracking (controlled player can be P1 or P2 per episode)
        self.seat_aware = {
            'episodes_agent_p1': 0,
            'episodes_agent_p2': 0,
            'wins_agent_p1': 0.0,
            'wins_agent_p2': 0.0,
        }
        
        if show_banner:
            print(f"✅ Metrics tracker initialized for {agent_key} -> {self.log_dir}")
            print(f"📊 Metric System:")
            print(f"   🎯 0_critical/ (13) - Essential hyperparameter tuning metrics")
            print(f"   🎮 game_critical/ (5) - Core gameplay indicators")
            print(f"   ⚙️  training_critical/ (6) - PPO algorithm health")
            print(f"   💡 TIP: Start with 0_critical/ - everything you need for tuning")
    
    def log_episode_end(self, episode_data: Dict[str, Any]):
        """Log core episode metrics - reward, win rate, and episode length"""
        self.episode_count += 1

        # Extract data
        total_reward = require_key(episode_data, 'total_reward')
        winner = require_key(episode_data, 'winner')
        episode_length = require_key(episode_data, 'episode_length')
        controlled_player = int(require_key(episode_data, 'controlled_player'))
        
        # GAME CRITICAL: Episode reward - Individual episode rewards
        self.writer.add_scalar('game_critical/episode_reward', total_reward, self.episode_count)
        self.all_episode_rewards.append(total_reward)
        
        # GAME CRITICAL: Win rate - Cumulative win rate (FULL DURATION)
        if winner is not None:
            agent_won = 1.0 if winner == controlled_player else 0.0
            self.all_episode_wins.append(agent_won)
            self.win_rate_window.append(agent_won)
            if winner == -1:
                outcome_flag = -1
            elif winner == controlled_player:
                outcome_flag = 1
            else:
                outcome_flag = 0
            self.episode_reward_winner_pairs.append((total_reward, outcome_flag))
            
            # Calculate cumulative win rate over ENTIRE training
            cumulative_win_rate = np.mean(self.all_episode_wins)
            self.writer.add_scalar('game_critical/win_rate_overall', cumulative_win_rate, self.episode_count)
            
            # GAME CRITICAL: Rolling win rate (recent 100 episodes) - PRIMARY METRIC
            if len(self.win_rate_window) >= 10:
                rolling_win_rate = np.mean(self.win_rate_window)
                self.writer.add_scalar('game_critical/win_rate_100ep', rolling_win_rate, self.episode_count)

            # SEAT-AWARE: cumulative win rates by controlled seat + global
            if controlled_player == 1:
                self.seat_aware['episodes_agent_p1'] += 1
                self.seat_aware['wins_agent_p1'] += agent_won
            elif controlled_player == 2:
                self.seat_aware['episodes_agent_p2'] += 1
                self.seat_aware['wins_agent_p2'] += agent_won
            else:
                raise ValueError(f"controlled_player must be 1 or 2 (got {controlled_player})")

            total_seat_episodes = (
                self.seat_aware['episodes_agent_p1'] + self.seat_aware['episodes_agent_p2']
            )
            total_seat_wins = self.seat_aware['wins_agent_p1'] + self.seat_aware['wins_agent_p2']
            if total_seat_episodes > 0:
                self.writer.add_scalar(
                    'seat_aware/winrate_global',
                    float(total_seat_wins / total_seat_episodes),
                    self.episode_count
                )
            if self.seat_aware['episodes_agent_p1'] > 0:
                self.writer.add_scalar(
                    'seat_aware/winrate_agent_p1',
                    float(self.seat_aware['wins_agent_p1'] / self.seat_aware['episodes_agent_p1']),
                    self.episode_count
                )
            if self.seat_aware['episodes_agent_p2'] > 0:
                self.writer.add_scalar(
                    'seat_aware/winrate_agent_p2',
                    float(self.seat_aware['wins_agent_p2'] / self.seat_aware['episodes_agent_p2']),
                    self.episode_count
                )
            self.writer.add_scalar(
                'seat_aware/episodes_agent_p1',
                float(self.seat_aware['episodes_agent_p1']),
                self.episode_count
            )
            self.writer.add_scalar(
                'seat_aware/episodes_agent_p2',
                float(self.seat_aware['episodes_agent_p2']),
                self.episode_count
            )
        
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
            hits = require_key(tactical_data, 'hits')
            accuracy = hits / tactical_data['shots_fired']
            self.writer.add_scalar('game_tactical/shooting_accuracy', accuracy, self.episode_count)
        
        # GAME TACTICAL: Kill efficiency - Kill rate
        if 'total_enemies' in tactical_data and tactical_data['total_enemies'] > 0:
            killed_enemies = require_key(tactical_data, 'units_killed')  # FIXED: use units_killed from engine
            slaughter_efficiency = killed_enemies / tactical_data['total_enemies']
            self.writer.add_scalar('game_tactical/kill_efficiency', slaughter_efficiency, self.episode_count)
        
        # GAME DETAILED: Damage dealt - Offensive power
        damage_dealt = require_key(tactical_data, 'damage_dealt')
        if damage_dealt > 0:
            self.writer.add_scalar('game_detailed/damage_dealt', damage_dealt, self.episode_count)
        
        # GAME DETAILED: Damage received - Defensive capability
        damage_received = require_key(tactical_data, 'damage_received')
        if damage_received > 0:
            self.writer.add_scalar('game_detailed/damage_received', damage_received, self.episode_count)
        
        # GAME TACTICAL: Damage efficiency - Trade effectiveness
        if damage_received > 0 and damage_dealt > 0:
            damage_efficiency = damage_dealt / damage_received
            self.writer.add_scalar('game_tactical/damage_efficiency', damage_efficiency, self.episode_count)
        
        # GAME DETAILED: Units lost - Unit preservation
        units_lost = require_key(tactical_data, 'units_lost')
        if units_lost >= 0:
            self.writer.add_scalar('game_detailed/units_lost', units_lost, self.episode_count)
        
        # GAME DETAILED: Units killed - Lethality
        units_killed = require_key(tactical_data, 'units_killed')
        if units_killed >= 0:
            self.writer.add_scalar('game_detailed/units_killed', units_killed, self.episode_count)

        # COMBAT VALUE METRICS: Episode-level attrition in VALUE points.
        enemy_value_destroyed = float(require_key(tactical_data, 'enemy_value_destroyed'))
        ally_value_lost = float(require_key(tactical_data, 'ally_value_lost'))
        self.writer.add_scalar('combat/f_value_destroyed', enemy_value_destroyed, self.episode_count)
        self.writer.add_scalar('combat/g_value_lost', ally_value_lost, self.episode_count)
        if ally_value_lost > 0 and enemy_value_destroyed > 0:
            value_trade_ratio = enemy_value_destroyed / ally_value_lost
            self.value_trade_ratio_history.append(value_trade_ratio)
            if len(self.value_trade_ratio_history) > 200:
                self.value_trade_ratio_history.pop(0)
            value_trade_ratio_mean_200 = self._calculate_smoothed_metric(
                self.value_trade_ratio_history,
                window_size=200
            )
            self.latest_value_trade_ratio = value_trade_ratio_mean_200
            self.writer.add_scalar(
                'combat/h_value_trade_ratio',
                value_trade_ratio_mean_200,
                self.episode_count
            )
        
        # GAME CRITICAL: Unit trade ratio (killed/lost) - Core success metric
        if units_lost > 0 and units_killed > 0:
            trade_ratio = units_killed / units_lost
            self.writer.add_scalar('game_critical/units_killed_vs_lost_ratio', trade_ratio, self.episode_count)
        
        # GAME TACTICAL: Unit trade ratio (absolute)
        if units_lost > 0 and units_killed > 0:
            trade_ratio = units_killed / units_lost
            self.writer.add_scalar('game_tactical/unit_trade_ratio', trade_ratio, self.episode_count)
        
        # GAME CRITICAL: Invalid action rate - AI_TURN.md compliance
        valid_actions = require_key(tactical_data, 'valid_actions')
        invalid_actions = require_key(tactical_data, 'invalid_actions')
        total_actions = valid_actions + invalid_actions
        
        if total_actions > 0:
            invalid_rate = invalid_actions / total_actions
            self.writer.add_scalar('game_critical/invalid_action_rate', invalid_rate, self.episode_count)
            
            # GAME TACTICAL: Action efficiency - Valid action rate
            action_efficiency = valid_actions / total_actions
            self.writer.add_scalar('game_tactical/action_efficiency', action_efficiency, self.episode_count)
        
        # GAME TACTICAL: Wait frequency - Decision confidence
        wait_actions = require_key(tactical_data, 'wait_actions')
        if total_actions > 0:
            wait_frequency = wait_actions / total_actions
            self.writer.add_scalar('game_tactical/wait_frequency', wait_frequency, self.episode_count)

        # GAME CRITICAL: VP differential from controlled perspective (seat-aware).
        if 'victory_points_diff_controlled_minus_opponent' in tactical_data:
            vp_diff = float(require_key(tactical_data, 'victory_points_diff_controlled_minus_opponent'))
            self.writer.add_scalar('game_critical/victory_points_diff', vp_diff, self.episode_count)

        # FORCING METRICS: Exposure of units with configured UNIT_RULES.
        has_forcing_fields = 'forced_unit_episode_has_controlled' in tactical_data
        if has_forcing_fields:
            forced_episode_has_controlled = int(require_key(tactical_data, 'forced_unit_episode_has_controlled'))
            forced_unit_instances_controlled = int(require_key(tactical_data, 'forced_unit_instances_controlled'))
            forced_unit_counts_controlled = require_key(tactical_data, 'forced_unit_counts_controlled')
            if not isinstance(forced_unit_counts_controlled, dict):
                raise TypeError(
                    "tactical_data['forced_unit_counts_controlled'] must be a dict "
                    f"(got {type(forced_unit_counts_controlled).__name__})"
                )

            self.forcing_tracking['episodes_total'] += 1
            self.forcing_tracking['forced_unit_instances_total'] += forced_unit_instances_controlled
            if forced_episode_has_controlled not in (0, 1):
                raise ValueError(
                    f"forced_unit_episode_has_controlled must be 0 or 1 "
                    f"(got {forced_episode_has_controlled})"
                )
            self.forcing_tracking['episodes_with_forced_unit'] += forced_episode_has_controlled

            episodes_total = int(self.forcing_tracking['episodes_total'])
            episodes_with_forced = int(self.forcing_tracking['episodes_with_forced_unit'])
            forcing_ratio = episodes_with_forced / episodes_total
            mean_instances = float(self.forcing_tracking['forced_unit_instances_total']) / float(episodes_total)

            self.writer.add_scalar('forcing/episodes_with_forced_unit_ratio', forcing_ratio, self.episode_count)
            self.writer.add_scalar('forcing/forced_unit_instances_mean', mean_instances, self.episode_count)
            self.writer.add_scalar(
                'forcing/episodes_with_forced_unit',
                float(episodes_with_forced),
                self.episode_count
            )

            for unit_name, raw_count in forced_unit_counts_controlled.items():
                unit_count = int(raw_count)
                if unit_count <= 0:
                    raise ValueError(
                        f"forced_unit_counts_controlled['{unit_name}'] must be > 0 (got {unit_count})"
                    )
                per_unit_episode_counts = require_key(self.forcing_tracking, 'per_unit_episode_counts')
                per_unit_instance_counts = require_key(self.forcing_tracking, 'per_unit_instance_counts')
                if unit_name not in per_unit_episode_counts:
                    per_unit_episode_counts[unit_name] = 0
                if unit_name not in per_unit_instance_counts:
                    per_unit_instance_counts[unit_name] = 0
                per_unit_episode_counts[unit_name] = int(per_unit_episode_counts[unit_name]) + 1
                per_unit_instance_counts[unit_name] = int(per_unit_instance_counts[unit_name]) + unit_count

                unit_slug = self._metric_slug(unit_name)
                unit_episode_ratio = per_unit_episode_counts[unit_name] / episodes_total
                unit_instance_mean = per_unit_instance_counts[unit_name] / episodes_total
                self.writer.add_scalar(
                    f'forcing/unit_episode_exposure/{unit_slug}',
                    unit_episode_ratio,
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'forcing/unit_instance_mean/{unit_slug}',
                    unit_instance_mean,
                    self.episode_count
                )
    
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
        units_activated = require_key(compliance_data, 'units_activated_this_step')
        self.compliance_data['units_per_step'].append(units_activated)
        if len(self.compliance_data['units_per_step']) > 1000:
            self.compliance_data['units_per_step'].pop(0)
        
        avg_units_per_step = np.mean(self.compliance_data['units_per_step'])
        self.writer.add_scalar('game_detailed/aiturn_units_per_step', avg_units_per_step, self.episode_count)
        
        # GAME DETAILED: Phase end reason
        phase_end_reason = require_key(compliance_data, 'phase_end_reason')
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
        duplicate_attempts = require_key(compliance_data, 'duplicate_activation_attempts')
        pool_corruption = require_key(compliance_data, 'pool_corruption_detected')
        
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
        if 'mapper_failed' in mapper_data and mapper_data['mapper_failed']:
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

    def log_victory_points_cumulative(self, points: float):
        """Log cumulative victory points for the controlled player at episode end.

        Args:
            points: Cumulative victory points for the learning agent for the episode.
        """
        self.combat_effectiveness['victory_points_cumulative'] = float(points)

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
        phase = require_key(phase_data, 'phase')
        action = require_key(phase_data, 'action')
        
        # Track phase-specific actions (accumulate only)
        if phase == 'move':
            if action == 'move':
                self.phase_stats['movement']['moved'] += 1
            elif action == 'wait' or action == 'skip':
                self.phase_stats['movement']['waited'] += 1
            if 'was_flee' in phase_data and phase_data['was_flee']:
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
        # Store current episode values in history for smoothing
        # victory_points_cumulative is logged for every episode.
        for key in ['shoot_kills', 'melee_kills', 'charge_successes']:
            self.combat_history[key].append(self.combat_effectiveness[key])
            # Keep last 100 episodes
            if len(self.combat_history[key]) > 100:
                self.combat_history[key].pop(0)

        self.combat_history['victory_points_cumulative'].append(
            self.combat_effectiveness['victory_points_cumulative']
        )
        if len(self.combat_history['victory_points_cumulative']) > 100:
            self.combat_history['victory_points_cumulative'].pop(0)

        # Log smoothed combat metrics (20-episode rolling average)
        # Prefixes control TensorBoard sort order:
        # a_position_score, b_shoot_kills, c_charge_successes, d_melee_kills, e_victory_points_cumulative_mean
        window_size = 20

        # a) Position score (movement quality)
        if len(self.position_scores) >= 1:
            position_score_smooth = self._calculate_smoothed_metric(self.position_scores, window_size=100)
            self.writer.add_scalar('combat/a_position_score', position_score_smooth, self.episode_count)

        # b) Shoot kills
        if len(self.combat_history['shoot_kills']) >= 1:
            smoothed_value = self._calculate_smoothed_metric(self.combat_history['shoot_kills'], window_size=window_size)
            self.writer.add_scalar('combat/b_shoot_kills', smoothed_value, self.episode_count)

        # c) Charge successes
        if len(self.combat_history['charge_successes']) >= 1:
            smoothed_value = self._calculate_smoothed_metric(self.combat_history['charge_successes'], window_size=window_size)
            self.writer.add_scalar('combat/c_charge_successes', smoothed_value, self.episode_count)

        # d) Melee kills
        if len(self.combat_history['melee_kills']) >= 1:
            smoothed_value = self._calculate_smoothed_metric(self.combat_history['melee_kills'], window_size=window_size)
            self.writer.add_scalar('combat/d_melee_kills', smoothed_value, self.episode_count)

        # e) Mean cumulative victory points per episode (smoothed over 200 episodes)
        if len(self.combat_history['victory_points_cumulative']) >= 1:
            smoothed_value = self._calculate_smoothed_metric(
                self.combat_history['victory_points_cumulative'],
                window_size=200
            )
            self.writer.add_scalar('combat/e_victory_points_cumulative_mean', smoothed_value, self.episode_count)

        # Reset combat effectiveness and flags for next episode
        self.combat_effectiveness = {
            'shoot_kills': 0,
            'melee_kills': 0,
            'charge_successes': 0,
            'victory_points_cumulative': 0.0
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

        # TRAINING DIAGNOSTIC: Log entropy coefficient independently from entropy_loss
        # so schedule diagnostics remain available even if entropy_loss is missing.
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
        🎯 CRITICAL DASHBOARD - 13 Essential Hyperparameter Tuning Metrics

        This dashboard contains ONLY the metrics you need to tune PPO hyperparameters.
        All metrics are smoothed (20-episode rolling average) for clear trends.

        GAME PERFORMANCE (6 metrics):
        - 0_critical/a_bot_eval_combined    - Primary goal [0-1] (sorts first)
        - 0_critical/a2_tier2_combined      - Avg(aggressive_smart, defensive_smart, adaptive)
        - 0_critical/b_worst_bot_score      - Min across all 7 bots
        - 0_critical/c_holdout_hard_mean    - Hard holdout aggregate robustness
        - 0_critical/d_win_rate_100ep       - Training opponent performance
        - 0_critical/e_episode_reward_smooth  - Learning progress

        PPO HEALTH (5 metrics):
        - 0_critical/f_loss_mean           - Overall learning health
        - 0_critical/g_explained_variance  - >0.3 -> Value function working
        - 0_critical/h_clip_fraction       - [0.1-0.3] -> Tune learning_rate
        - 0_critical/i_approx_kl           - <0.02 -> Policy stability
        - 0_critical/j_entropy_loss        - [0.5-2.0] -> Tune ent_coef

        TECHNICAL HEALTH (3 metrics):
        - 0_critical/k_gradient_norm       - <10 -> No gradient explosion
        - 0_critical/l_value_trade_ratio   - VALUE destroyed / VALUE lost
        - 0_critical/m_value_loss_smooth   - Smoothed critic loss

        NOTE: position_score moved to combat/ category
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
            self.writer.add_scalar('0_critical/d_win_rate_100ep', win_rate, self.episode_count)

        # 2. Episode Reward (smoothed) - Training signal strength
        if len(self.all_episode_rewards) >= 1:
            reward_smooth = self._calculate_smoothed_metric(self.all_episode_rewards, window_size=200)
            self.writer.add_scalar('0_critical/e_episode_reward_smooth', reward_smooth, self.episode_count)

        # NOTE: position_score moved to combat/ category

        # ==========================================
        # PPO HEALTH (5 metrics)
        # ==========================================

        # 3. Clip Fraction - Policy update scale
        if len(self.hyperparameter_tracking['clip_fractions']) >= 1:
            clip_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['clip_fractions'], window_size=20
            )
            self.writer.add_scalar('0_critical/h_clip_fraction', clip_smooth, self.episode_count)

        # 4. Approx KL - Policy change magnitude
        if len(self.hyperparameter_tracking['approx_kls']) >= 1:
            kl_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['approx_kls'], window_size=20
            )
            self.writer.add_scalar('0_critical/i_approx_kl', kl_smooth, self.episode_count)

        # 5. Explained Variance - Value function quality
        if len(require_key(self.hyperparameter_tracking, 'explained_variances')) >= 1:
            ev_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['explained_variances'], window_size=20
            )
            self.writer.add_scalar('0_critical/g_explained_variance', ev_smooth, self.episode_count)

        # 6. Entropy Loss - Exploration health
        if len(self.hyperparameter_tracking['entropy_losses']) >= 1:
            entropy_smooth = self._calculate_smoothed_metric(
                self.hyperparameter_tracking['entropy_losses'], window_size=20
            )
            self.writer.add_scalar('0_critical/j_entropy_loss', entropy_smooth, self.episode_count)

        # 7. Loss Mean (combined policy + value loss) - Training stability
        if (len(self.hyperparameter_tracking['policy_losses']) >= 1 and
            len(self.hyperparameter_tracking['value_losses']) >= 1):
            # Calculate combined loss
            recent_policy = self.hyperparameter_tracking['policy_losses'][-20:]
            recent_value = self.hyperparameter_tracking['value_losses'][-20:]
            combined_losses = [abs(p) + abs(v) for p, v in zip(recent_policy, recent_value)]
            loss_mean = np.mean(combined_losses)
            self.writer.add_scalar('0_critical/f_loss_mean', loss_mean, self.episode_count)
            value_loss_smooth = float(np.mean(recent_value))
            self.writer.add_scalar('0_critical/m_value_loss_smooth', value_loss_smooth, self.episode_count)
        
        # ==========================================
        # TECHNICAL HEALTH (3 metrics)
        # ==========================================
        
        # 8. Gradient Norm (direct value from latest training step) - Technical health
        if hasattr(self, 'latest_gradient_norm') and self.latest_gradient_norm is not None:
            self.writer.add_scalar('0_critical/k_gradient_norm', self.latest_gradient_norm, self.episode_count)
        else:
            # Log placeholder if gradient_norm not available from stable-baselines3
            # This keeps the metric visible in TensorBoard even if SB3 doesn't log it
            if self.episode_count <= 1:
                self.writer.add_scalar('0_critical/k_gradient_norm', 0.0, self.episode_count)
        
        # 10. Reward-Victory Gap (reward alignment: mean reward when won vs lost)
        # Gap > 20-30 = good alignment; Gap < 10 = reward may not correlate with victory
        if len(self.episode_reward_winner_pairs) >= 20:
            recent = list(self.episode_reward_winner_pairs)[-100:]
            rewards_when_won = [r for r, outcome in recent if outcome == 1]
            rewards_when_lost = [r for r, outcome in recent if outcome == 0]
            if len(rewards_when_won) >= 5 and len(rewards_when_lost) >= 5:
                mean_won = float(np.mean(rewards_when_won))
                mean_lost = float(np.mean(rewards_when_lost))
                gap = mean_won - mean_lost
                self.writer.add_scalar('game_critical/reward_when_won', mean_won, self.episode_count)
                self.writer.add_scalar('game_critical/reward_when_lost', mean_lost, self.episode_count)
                self.writer.add_scalar('game_detailed/reward_victory_gap', gap, self.episode_count)

        # 11. VALUE trade ratio (destroyed/lost) - Attrition robustness
        if self.latest_value_trade_ratio is not None:
            self.writer.add_scalar('0_critical/l_value_trade_ratio', self.latest_value_trade_ratio, self.episode_count)
        
        # 12. Bot Evaluation Combined Score (logged immediately in log_bot_evaluations())
        # NOTE: This metric is logged in log_bot_evaluations() to avoid duplicate/stale values
        # Do not log here - let log_bot_evaluations() handle it
        
        # Invalid Action Rate - Moved to game_critical (game-specific, not training-critical)
        if hasattr(self, 'episode_tactical_data') and self.episode_tactical_data:
            total_actions = require_key(self.episode_tactical_data, 'total_actions')
            invalid_actions = require_key(self.episode_tactical_data, 'invalid_actions')
            if total_actions > 0:
                invalid_rate = invalid_actions / total_actions
                self.writer.add_scalar('game_critical/invalid_action_rate', invalid_rate, self.episode_count)
            else:
                # Log zero if no actions yet
                self.writer.add_scalar('game_critical/invalid_action_rate', 0.0, self.episode_count)
    
    def log_bot_evaluations(self, bot_results: Dict[str, float], step: Optional[int] = None):
        """
        Log bot evaluation results to both 0_critical/ and bot_eval/ namespaces.

        Args:
            bot_results: Dict with keys 'random', 'greedy', 'defensive', 'combined'
            step: Optional step for x-axis (e.g. eval_marker). If None, uses episode_count.
        """
        x = step if step is not None else self.episode_count
        # Log individual bot results to bot_eval/ namespace
        if 'random' in bot_results:
            self.writer.add_scalar('bot_eval/vs_random', bot_results['random'], x)
        if 'greedy' in bot_results:
            self.writer.add_scalar('bot_eval/vs_greedy', bot_results['greedy'], x)
        if 'defensive' in bot_results:
            self.writer.add_scalar('bot_eval/vs_defensive', bot_results['defensive'], x)
        if 'control' in bot_results:
            self.writer.add_scalar('bot_eval/vs_control', bot_results['control'], x)
        if 'aggressive_smart' in bot_results:
            self.writer.add_scalar('bot_eval/vs_aggressive_smart', bot_results['aggressive_smart'], x)
        if 'defensive_smart' in bot_results:
            self.writer.add_scalar('bot_eval/vs_defensive_smart', bot_results['defensive_smart'], x)
        if 'adaptive' in bot_results:
            self.writer.add_scalar('bot_eval/vs_adaptive', bot_results['adaptive'], x)
        ALL_BOT_KEYS = ('random', 'greedy', 'defensive', 'control', 'aggressive_smart', 'defensive_smart', 'adaptive')
        TIER2_BOT_KEYS = ('aggressive_smart', 'defensive_smart', 'adaptive')
        tier2_scores = [bot_results[k] for k in TIER2_BOT_KEYS if k in bot_results]
        if tier2_scores:
            tier2_combined = sum(tier2_scores) / len(tier2_scores)
            self.writer.add_scalar('bot_eval/tier2_combined', tier2_combined, x)
            self.writer.add_scalar('0_critical/a2_tier2_combined', tier2_combined, x)

        bot_score_keys = [k for k in ALL_BOT_KEYS if k in bot_results]
        if len(bot_score_keys) >= 3:
            worst_bot_score = min(bot_results[k] for k in bot_score_keys)
            self.writer.add_scalar('bot_eval/worst_bot_score', worst_bot_score, x)
            self.writer.add_scalar('0_critical/b_worst_bot_score', worst_bot_score, x)
            if self.forcing_tracking['episodes_total'] > 0:
                if self.forcing_tracking['baseline_worst_bot'] is None:
                    self.forcing_tracking['baseline_worst_bot'] = float(worst_bot_score)
                baseline_worst = float(require_key(self.forcing_tracking, 'baseline_worst_bot'))
                self.writer.add_scalar(
                    'forcing/delta_worst_bot_vs_forcing_start',
                    float(worst_bot_score) - baseline_worst,
                    x
                )
        if 'holdout_hard_mean' in bot_results:
            holdout_hard_mean = float(bot_results['holdout_hard_mean'])
            self.writer.add_scalar('bot_eval/holdout_hard_mean', holdout_hard_mean, x)
            self.writer.add_scalar('0_critical/c_holdout_hard_mean', holdout_hard_mean, x)

        # Store combined score and log immediately to both namespaces
        if 'combined' in bot_results:
            self.bot_eval_combined = bot_results['combined']
            # Log to bot_eval/ namespace
            self.writer.add_scalar('bot_eval/combined', bot_results['combined'], x)
            # Log IMMEDIATELY to 0_critical/ namespace (don't wait for next episode)
            self.writer.add_scalar('0_critical/a_bot_eval_combined', bot_results['combined'], x)
            if self.forcing_tracking['episodes_total'] > 0:
                if self.forcing_tracking['baseline_combined'] is None:
                    self.forcing_tracking['baseline_combined'] = float(bot_results['combined'])
                baseline_combined = float(require_key(self.forcing_tracking, 'baseline_combined'))
                self.writer.add_scalar(
                    'forcing/delta_combined_vs_forcing_start',
                    float(bot_results['combined']) - baseline_combined,
                    x
                )

    def log_holdout_split_metrics(self, split_metrics: Dict[str, float]) -> None:
        """Log holdout split aggregates to TensorBoard."""
        if 'holdout_regular_mean' in split_metrics:
            self.writer.add_scalar(
                'bot_eval/holdout_regular_mean',
                float(split_metrics['holdout_regular_mean']),
                self.episode_count
            )
        if 'holdout_hard_mean' in split_metrics:
            self.writer.add_scalar(
                'bot_eval/holdout_hard_mean',
                float(split_metrics['holdout_hard_mean']),
                self.episode_count
            )
        if 'holdout_overall_mean' in split_metrics:
            self.writer.add_scalar(
                'bot_eval/holdout_overall_mean',
                float(split_metrics['holdout_overall_mean']),
                self.episode_count
            )

    def log_scenario_split_scores(self, split_scores: Dict[str, float]) -> None:
        """Log per-scenario split scores under dedicated category."""
        for key, value in split_scores.items():
            self.writer.add_scalar(
                f'bot_split/{key}',
                float(value),
                self.episode_count
            )

    def log_observation_phase_metrics(self, phase_metrics: Dict[str, Dict[str, List[float]]]) -> None:
        """
        Log observation-centric metrics under flat obs namespace.

        Expected keys per phase:
          - best_kill_probability: list[float]
          - danger_to_me: list[float]
          - valid_target_count: list[float]
        """
        for phase_name, metrics in phase_metrics.items():
            _kill = metrics.get("best_kill_probability")
            kill_values = [float(v) for v in _kill] if isinstance(_kill, list) else []
            _danger = metrics.get("danger_to_me")
            danger_values = [float(v) for v in _danger] if isinstance(_danger, list) else []
            _count = metrics.get("valid_target_count")
            count_values = [float(v) for v in _count] if isinstance(_count, list) else []

            if kill_values:
                self.writer.add_scalar(
                    f'obs/{phase_name}_best_kill_probability_mean',
                    float(np.mean(kill_values)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_best_kill_probability_p50',
                    float(np.percentile(kill_values, 50)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_best_kill_probability_p90',
                    float(np.percentile(kill_values, 90)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_best_kill_probability_count',
                    float(len(kill_values)),
                    self.episode_count
                )

            if danger_values:
                self.writer.add_scalar(
                    f'obs/{phase_name}_danger_to_me_mean',
                    float(np.mean(danger_values)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_danger_to_me_p50',
                    float(np.percentile(danger_values, 50)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_danger_to_me_p90',
                    float(np.percentile(danger_values, 90)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_danger_to_me_count',
                    float(len(danger_values)),
                    self.episode_count
                )

            if count_values:
                self.writer.add_scalar(
                    f'obs/{phase_name}_valid_target_count_mean',
                    float(np.mean(count_values)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_valid_target_count_p50',
                    float(np.percentile(count_values, 50)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_valid_target_count_p90',
                    float(np.percentile(count_values, 90)),
                    self.episode_count
                )
                self.writer.add_scalar(
                    f'obs/{phase_name}_valid_target_count_count',
                    float(len(count_values)),
                    self.episode_count
                )
    
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

    @staticmethod
    def _metric_slug(name: str) -> str:
        """Convert a unit name to a TensorBoard-safe metric suffix."""
        normalized = "".join(ch if ch.isalnum() else "_" for ch in str(name)).strip("_").lower()
        if not normalized:
            raise ValueError(f"Cannot build metric slug from empty unit name: {name!r}")
        return normalized
    
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
            min_win_rate = require_key(self.thresholds, 'min_win_rate')
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
    log_dir = require_key(config, 'tensorboard_log')
    return W40KMetricsTracker(agent_key, log_dir)