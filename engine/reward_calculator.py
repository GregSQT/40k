#!/usr/bin/env python3
"""
reward_calculator.py - Reward calculation system
"""

from typing import Dict, List, Any, Tuple, Optional
from engine.combat_utils import calculate_wound_target, calculate_hex_distance, calculate_pathfinding_distance, has_line_of_sight
from engine.phase_handlers.shooting_handlers import _calculate_save_target
from engine.game_utils import get_unit_by_id

class RewardCalculator:
    """Calculates rewards for actions."""
    
    def __init__(self, config: Dict[str, Any], rewards_config: Dict[str, Any], unit_registry=None, state_manager=None):
        self.config = config
        self.rewards_config = rewards_config
        self._reward_mapper = None
        self.quiet = config.get("quiet", True)
        self.unit_registry = unit_registry
        self.state_manager = state_manager
    
    # ============================================================================
    # MAIN REWARD
    # ============================================================================
    
    def calculate_reward(self, success: bool, result: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """Calculate reward using actual acting unit with reward mapper integration."""
        # Initialize reward breakdown dictionary for metrics tracking
        reward_breakdown = {
            'base_actions': 0.0,
            'result_bonuses': 0.0,
            'tactical_bonuses': 0.0,
            'situational': 0.0,
            'penalties': 0.0,
            'total': 0.0
        }
        
        # Load system penalties from config
        system_penalties = self._get_system_penalties()
        
        # PRIORITY CHECK: Invalid action penalty (from handlers)
        if isinstance(result, dict) and result.get("invalid_action_penalty"):
            penalty_reward = system_penalties['invalid_action']
            reward_breakdown['penalties'] = penalty_reward
            reward_breakdown['total'] = penalty_reward
            game_state['last_reward_breakdown'] = reward_breakdown
            return penalty_reward
        
        if not success:
            if isinstance(result, dict):
                error_msg = result.get("error", "")
                if "forbidden_in" in error_msg or "masked_in" in error_msg:
                    penalty_reward = system_penalties['forbidden_action']
                    reward_breakdown['penalties'] = penalty_reward
                    reward_breakdown['total'] = penalty_reward
                    game_state['last_reward_breakdown'] = reward_breakdown
                    return penalty_reward
                else:
                    penalty_reward = system_penalties['generic_error']
                    reward_breakdown['penalties'] = penalty_reward
                    reward_breakdown['total'] = penalty_reward
                    game_state['last_reward_breakdown'] = reward_breakdown
                    return penalty_reward
            else:
                penalty_reward = system_penalties['generic_error']
                reward_breakdown['penalties'] = penalty_reward
                reward_breakdown['total'] = penalty_reward
                game_state['last_reward_breakdown'] = reward_breakdown
                return penalty_reward
        
        # Handle system responses (no unit-specific rewards)
        # BUT: If result contains action data (action, fromCol/toCol), it's an action that triggered
        # a phase transition, NOT a pure system response. Process it as an action.
        system_response_indicators = [
            "phase_complete", "phase_transition", "while_loop_active",
            "context", "blinking_units", "start_blinking", "validTargets",
            "type", "next_phase", "current_player", "new_turn", "episode_complete",
            "unit_activated", "valid_destinations", "preview_data", "waiting_for_player"
        ]

        # CRITICAL FIX: Check if this is actually an action result with phase transition attached
        # If result has 'action' field with move/shoot/etc, it's an action - NOT a system response
        # Position data (fromCol/toCol) confirms it's a completed action, not just a prompt
        is_action_result = result.get("action") in ["move", "shoot", "wait", "flee", "charge", "charge_fail", "fight"]
        has_position_data = any(ind in result for ind in ["fromCol", "toCol", "fromRow", "toRow"])

        matching_indicators = [ind for ind in system_response_indicators if ind in result]
        if matching_indicators and not (is_action_result or has_position_data):
            # Pure system response - no action attached
            system_response_reward = system_penalties['system_response']
            reward_breakdown['total'] = system_response_reward

            # CRITICAL FIX: Check if game ended and add situational reward
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                reward_breakdown['total'] += situational_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return reward_breakdown['total']
        
        # Get ACTUAL acting unit from result
        acting_unit_id = result.get("unitId") or result.get("shooterId") or result.get("unit_id")
        if not acting_unit_id:
            raise ValueError(f"Action result missing acting unit ID: {result}")
        
        acting_unit = get_unit_by_id(str(acting_unit_id), game_state)
        if not acting_unit:
            raise ValueError(f"Acting unit not found: {acting_unit_id}")

        # CRITICAL: Only give rewards to the controlled player (P0 during training)
        # Player 1's actions are part of the environment, not the learning agent
        controlled_player = self.config.get("controlled_player", 0)
        if acting_unit.get("player") != controlled_player:
            # No action rewards for opponent, BUT check if game ended
            # If P1's action ended the game, P0 still needs the win/lose reward!
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                reward_breakdown['total'] = situational_reward
                game_state['last_reward_breakdown'] = reward_breakdown
                return situational_reward

            # Game not over - no reward for opponent's actions
            reward_breakdown['total'] = 0.0
            game_state['last_reward_breakdown'] = reward_breakdown
            return 0.0

        # Get action type from result
        # Check both 'action' and 'endType' fields (handlers use different naming)
        if isinstance(result, dict):
            action_type = result.get("action") or result.get("endType", "").lower()
            if not action_type:
                action_type = "unknown"
        else:
            action_type = "unknown"

        # Full reward mapper integration
        reward_mapper = self._get_reward_mapper()
        enriched_unit = self._enrich_unit_for_reward_mapper(acting_unit)
        
        if action_type == "shoot":
            # Sum all shoot rewards from current activation (handles RNG_NB > 1)
            action_logs = game_state.get("action_logs", [])
            
            # Validate action_logs exists and is not empty
            if not action_logs or len(action_logs) == 0:
                raise RuntimeError(
                    f"CRITICAL: action_logs is empty for shoot action! "
                    f"Unit {acting_unit.get('id')}, Player {acting_unit.get('player')}"
                )
            
            # Find all shoot logs from the most recent activation
            # Work backwards until we hit a different action type or different shooter
            current_turn = game_state.get("turn", 0)
            shooter_id = acting_unit.get("id")
            
            # Track rewards by category using action_name field
            base_action_reward = 0.0
            result_bonus_reward = 0.0
            logs_found = 0  # Track if we actually found any logs

            for log in reversed(action_logs):
                # Stop if we hit a different turn
                if log.get("turn") != current_turn:
                    break

                # If it's a shoot action from the same shooter, categorize the reward
                if log.get("type") == "shoot" and log.get("shooterId") == shooter_id:
                    logs_found += 1  # Found a matching log
                    if "reward" not in log:
                        raise RuntimeError(
                            f"CRITICAL: action_log missing reward field! "
                            f"Unit {shooter_id}, Player {acting_unit.get('player')}. "
                            f"Log keys: {list(log.keys())}"
                        )
                    if "action_name" not in log:
                        raise RuntimeError(
                            f"CRITICAL: action_log missing action_name field! "
                            f"Unit {shooter_id}, Player {acting_unit.get('player')}. "
                            f"Log keys: {list(log.keys())}"
                        )
                    
                    reward_value = log["reward"]
                    action_name = log["action_name"]
                    
                    # Classify reward based on action_name
                    if action_name == "ranged_attack":
                        # Base shooting action reward
                        base_action_reward += reward_value
                    elif action_name in ["hit_target", "wound_target", "damage_target", "kill_target"]:
                        # Combat result bonuses
                        result_bonus_reward += reward_value
                    else:
                        # Unknown action_name - log warning and count as base
                        print(f"⚠️ Unknown action_name '{action_name}' in shoot log, counting as base_action")
                        base_action_reward += reward_value
                
                # Skip non-shoot logs (e.g., death logs) - don't break, continue searching
                # Only break if we hit a shoot log from a different shooter
                elif log.get("type") == "shoot" and log.get("shooterId") != shooter_id:
                    break
            
            # Validate we found at least one shoot action LOG (not just non-zero rewards)
            if logs_found == 0:
                raise RuntimeError(
                    f"CRITICAL: No shoot actions found in action_logs! "
                    f"Unit {shooter_id}, Player {acting_unit.get('player')}"
                )
            
            # Calculate total reward
            calculated_reward = base_action_reward + result_bonus_reward
            
            # Properly populate reward_breakdown
            reward_breakdown['base_actions'] = base_action_reward
            reward_breakdown['result_bonuses'] = result_bonus_reward
            reward_breakdown['total'] = calculated_reward
            
            # Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                calculated_reward += situational_reward
                reward_breakdown['total'] = calculated_reward
            
            game_state['last_reward_breakdown'] = reward_breakdown
            return calculated_reward
            
        elif action_type == "move" or action_type == "flee":
            # CRITICAL FIX: Handle both 'move' and 'flee' actions the same way
            # 'flee' is movement away from adjacent enemies (AI_TURN.md flee mechanics)
            old_pos = (result["fromCol"], result["fromRow"])
            new_pos = (result["toCol"], result["toRow"])

            # Phase 2+: Use position_score-based movement reward
            # Get tactical_positioning hyperparameter from config (default 1.0 = balanced)
            tactical_positioning = self.config.get("tactical_positioning", 1.0)

            # Calculate position score at current (new) position - ABSOLUTE approach
            # Rewards the agent for being in a good position, not just for improving
            # This is correct because: agent that starts at best position should still be rewarded
            position_score = self.calculate_position_score(acting_unit, new_pos, game_state, tactical_positioning)

            # Scale factor ensures position_score translates to meaningful reward magnitude
            position_reward_scale = self.config.get("position_reward_scale", 0.1)
            position_based_reward = position_score * position_reward_scale

            # Also get legacy tactical context rewards (for backward compatibility)
            tactical_context = self._build_tactical_context(acting_unit, result, game_state)
            legacy_reward = reward_mapper.get_movement_reward(enriched_unit, old_pos, new_pos, tactical_context)
            if isinstance(legacy_reward, tuple):
                legacy_reward = legacy_reward[0]

            # Combine position-based and legacy rewards
            # Position-based is primary for Phase 2+, legacy provides additional signals
            movement_reward = position_based_reward + legacy_reward

            reward_breakdown['base_actions'] = legacy_reward
            reward_breakdown['tactical_bonuses'] = position_based_reward
            reward_breakdown['position_score'] = position_score  # Raw score before scaling (for metrics)
            reward_breakdown['total'] = movement_reward

            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                movement_reward += situational_reward
                reward_breakdown['total'] = movement_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return movement_reward

        elif action_type == "skip":
            # FIXED: Skip means no targets available - no penalty
            skip_reward = 0.0
            reward_breakdown['base_actions'] = skip_reward
            reward_breakdown['total'] = skip_reward
            
            # Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                skip_reward += situational_reward
                reward_breakdown['total'] = skip_reward
            
            game_state['last_reward_breakdown'] = reward_breakdown
            return skip_reward
            
        elif action_type == "charge" and "targetId" in result:
            target = get_unit_by_id(str(result["targetId"]), game_state)
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit, game_state)]
            charge_reward = reward_mapper.get_charge_priority_reward(enriched_unit, enriched_target, all_targets)
            reward_breakdown['base_actions'] = charge_reward
            reward_breakdown['total'] = charge_reward
            
            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                charge_reward += situational_reward
                reward_breakdown['total'] = charge_reward
            
            game_state['last_reward_breakdown'] = reward_breakdown
            return charge_reward
            
        elif action_type in ("fight", "combat") and "targetId" in result:
            # "combat" is the step_logger action type, "fight" is the legacy name
            target = get_unit_by_id(str(result["targetId"]), game_state)
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit, game_state)]
            fight_reward = reward_mapper.get_combat_priority_reward(enriched_unit, enriched_target, all_targets)
            reward_breakdown['base_actions'] = fight_reward
            reward_breakdown['total'] = fight_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                fight_reward += situational_reward
                reward_breakdown['total'] = fight_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return fight_reward
            
        elif action_type == "wait":
            # FIXED: Wait means agent chose not to act when action was available
            current_phase = game_state.get("phase", "shoot")
            if current_phase == "move":
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "move_wait"}, success, game_state)
            else:
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "shoot_wait"}, success, game_state)
            reward_breakdown['base_actions'] = wait_reward
            reward_breakdown['penalties'] = wait_reward
            reward_breakdown['total'] = wait_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                wait_reward += situational_reward
                reward_breakdown['total'] = wait_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return wait_reward

        elif action_type == "pass":
            # Pass action in fight phase - unit had no valid targets to attack
            # Treat same as wait (no reward, no penalty)
            pass_reward = 0.0
            reward_breakdown['base_actions'] = pass_reward
            reward_breakdown['total'] = pass_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                pass_reward += situational_reward
                reward_breakdown['total'] = pass_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return pass_reward

        elif action_type == "charge_fail":
            # Charge failed because roll was too low
            # Give a small penalty (less than wait, since agent at least tried)
            # Use system penalty for failed actions
            system_penalties = self._get_system_penalties()
            charge_fail_reward = system_penalties.get('failed_action', -0.1)  # Small penalty for failed charge
            reward_breakdown['base_actions'] = charge_fail_reward
            reward_breakdown['penalties'] = charge_fail_reward
            reward_breakdown['total'] = charge_fail_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                charge_fail_reward += situational_reward
                reward_breakdown['total'] = charge_fail_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return charge_fail_reward

        elif action_type == "advance":
            # ADVANCE_IMPLEMENTATION: Advance action during shooting phase
            # Similar to move but happens in shooting phase
            old_pos = (result["fromCol"], result["fromRow"])
            new_pos = (result["toCol"], result["toRow"])
            
            # Check if unit actually moved (if not, minimal/no reward)
            if not result.get("actually_moved", False):
                # Unit stayed in place - minimal reward (similar to wait)
                advance_reward = 0.0
                reward_breakdown['base_actions'] = advance_reward
                reward_breakdown['total'] = advance_reward
                
                if game_state.get("game_over", False):
                    situational_reward = self._get_situational_reward(game_state)
                    reward_breakdown['situational'] = situational_reward
                    advance_reward += situational_reward
                    reward_breakdown['total'] = advance_reward
                
                game_state['last_reward_breakdown'] = reward_breakdown
                return advance_reward
            
            # Build tactical context for advance (similar to movement)
            tactical_context = self._build_tactical_context(acting_unit, result, game_state)
            
            # Use advance-specific reward mapper
            advance_reward_tuple = reward_mapper.get_advance_reward(enriched_unit, old_pos, new_pos, tactical_context)
            if isinstance(advance_reward_tuple, tuple):
                advance_reward = advance_reward_tuple[0]
            else:
                advance_reward = advance_reward_tuple
            
            reward_breakdown['base_actions'] = advance_reward
            reward_breakdown['total'] = advance_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                advance_reward += situational_reward
                reward_breakdown['total'] = advance_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return advance_reward

        elif action_type == "no_effect":
            # No-effect action (e.g., skip attempted on non-active unit in charge phase)
            # Treat same as pass - no reward, no penalty
            no_effect_reward = 0.0
            reward_breakdown['base_actions'] = no_effect_reward
            reward_breakdown['total'] = no_effect_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                no_effect_reward += situational_reward
                reward_breakdown['total'] = no_effect_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return no_effect_reward

        # NO FALLBACK - Raise error to identify missing action types
        raise ValueError(f"Unhandled action type '{action_type}' in _calculate_reward. Result: {result}")
    
    def calculate_reward_from_config(self, acting_unit: Dict[str, Any], action: Dict[str, Any], success: bool, game_state: Dict[str, Any]) -> float:
        """Exact reproduction of gym40k.py reward calculation."""
        unit_rewards = self._get_unit_reward_config(acting_unit)
        base_reward = 0.0
        
        # Validate required reward structure
        if "base_actions" not in unit_rewards:
            raise KeyError(f"Unit rewards missing required 'base_actions' section")
        
        base_actions = unit_rewards["base_actions"]
        
        # Base action rewards - exact gym40k.py logic
        action_type = action["type"]
        if action_type == "shoot":
            if success:
                if "ranged_attack" not in base_actions:
                    raise KeyError(f"Base actions missing required 'ranged_attack' reward")
                base_reward = base_actions["ranged_attack"]
            else:
                if "shoot_wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'shoot_wait' reward")
                base_reward = base_actions["shoot_wait"]
        elif action_type == "move":
            if success:
                move_key = "move_close" if "move_close" in base_actions else "move_wait"
                if move_key not in base_actions:
                    raise KeyError(f"Base actions missing required '{move_key}' reward")
                base_reward = base_actions[move_key]
            else:
                if "move_wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'move_wait' reward")
                base_reward = base_actions["move_wait"]
        elif action_type == "skip":
            if "move_wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'move_wait' reward")
            base_reward = base_actions["move_wait"]
        elif action_type == "move_wait":
            if "move_wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'move_wait' reward")
            base_reward = base_actions["move_wait"]
        elif action_type == "shoot_wait":
            if "shoot_wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'shoot_wait' reward")
            base_reward = base_actions["shoot_wait"]
        else:
            if "move_wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'move_wait' reward")
            base_reward = base_actions["move_wait"]
        
        # Add win/lose bonuses from situational_modifiers
        if game_state["game_over"]:
            # AI_TURN.md COMPLIANCE: Direct access with validation
            if "situational_modifiers" not in unit_rewards:
                raise KeyError("Unit rewards missing required 'situational_modifiers' section")
            modifiers = unit_rewards["situational_modifiers"]
            winner = self._determine_winner(game_state)

            # Player 0 is always the controlled player during training
            if winner == 0:  # Player 0 wins
                if "win" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'win' reward")
                win_bonus = modifiers["win"]
                base_reward += win_bonus

                # CRITICAL FIX: Track win bonus in game_state for metrics
                game_state['last_reward_breakdown'] = {
                    'base_actions': base_reward - win_bonus,
                    'result_bonuses': 0.0,
                    'tactical_bonuses': 0.0,
                    'situational': win_bonus,
                    'penalties': 0.0
                }

            elif winner == 1:  # Player 1 wins (controlled player loses)
                if "lose" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'lose' reward")
                lose_penalty = modifiers["lose"]
                base_reward += lose_penalty

                # CRITICAL FIX: Track lose penalty in game_state for metrics
                game_state['last_reward_breakdown'] = {
                    'base_actions': base_reward - lose_penalty,
                    'result_bonuses': 0.0,
                    'tactical_bonuses': 0.0,
                    'situational': lose_penalty,
                    'penalties': 0.0
                }
                
            elif winner == -1:  # Draw
                if "draw" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'draw' reward")
                draw_reward = modifiers["draw"]
                base_reward += draw_reward
                
                # Track draw reward in game_state for metrics
                game_state['last_reward_breakdown'] = {
                    'base_actions': base_reward - draw_reward,
                    'result_bonuses': 0.0,
                    'tactical_bonuses': 0.0,
                    'situational': draw_reward,
                    'penalties': 0.0
                }
        
        return base_reward
    
    # ============================================================================
    # REWARD CONFIG
    # ============================================================================
    
    def _get_unit_reward_config(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Exact reproduction of gym40k.py unit reward config method."""
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        unit_type = unit["unitType"]

        try:
            # CRITICAL FIX: Use controlled_agent from config (includes phase suffix)
            # instead of unit_registry.get_model_key() (base key without phase)
            agent_key = self.config.get("controlled_agent")
            if not agent_key:
                # Fallback to unit_registry if controlled_agent not in config
                agent_key = self.unit_registry.get_model_key(unit_type)

            if agent_key not in self.rewards_config:
                available_keys = list(self.rewards_config.keys())
                raise KeyError(f"Agent key '{agent_key}' not found in rewards config. Available keys: {available_keys}")

            unit_reward_config = self.rewards_config[agent_key]
            if "base_actions" not in unit_reward_config:
                raise KeyError(f"Missing 'base_actions' section in rewards config for agent key '{agent_key}'")

            return unit_reward_config
        except ValueError as e:
            raise ValueError(f"Failed to get reward config for unit type '{unit['unitType']}': {e}")
    
    def _get_situational_reward(self, game_state: Dict[str, Any]) -> float:
        """
        Get situational reward (win/lose/draw) for current game state.
        Called when game ends to add final outcome bonus/penalty.

        CRITICAL: The learning agent is ALWAYS Player 0 during training.
        Player 1 is the opponent (frozen model in self-play, or bot).
        """
        if not game_state.get("game_over", False):
            return 0.0

        # Get any Player 0 unit to access reward config (learning agent is P0)
        # CRITICAL FIX: Learning agent is Player 0, not Player 1!
        acting_unit = None
        for unit in game_state["units"]:
            if unit["player"] == 0:  # Learning agent is Player 0
                acting_unit = unit
                break

        if not acting_unit:
            return 0.0

        try:
            unit_rewards = self._get_unit_reward_config(acting_unit)
            
            # Calculate base win/lose/draw reward (if situational_modifiers exists)
            base_reward = 0.0
            if "situational_modifiers" in unit_rewards:
                modifiers = unit_rewards["situational_modifiers"]
                winner = self._determine_winner(game_state)

                # CRITICAL FIX: Learning agent is Player 0!
                # winner == 0 means Player 0 (learning agent) wins
                # winner == 1 means Player 1 (opponent) wins, so learning agent loses
                if winner == 0:  # Learning agent wins
                    base_reward = modifiers.get("win", 0.0)
                elif winner == 1:  # Learning agent loses
                    base_reward = modifiers.get("lose", 0.0)
                elif winner == -1:  # Draw
                    base_reward = modifiers.get("draw", 0.0)

            # Add objective control reward at end of turn 5
            # CRITICAL: Calculate objective reward even if situational_modifiers is missing
            objective_reward = self._calculate_objective_reward_turn5(game_state, unit_rewards)
            
            # Diagnostic logging (only if not quiet)
            if not self.quiet and objective_reward > 0:
                current_turn = game_state.get("turn", 0)
                obj_counts = self.state_manager.count_controlled_objectives(game_state) if self.state_manager else {}
                print(f"🎯 OBJECTIVE REWARD: Turn={current_turn}, P0 objectives={obj_counts.get(0, 0)}, Reward={objective_reward:.1f}")
            
            return base_reward + objective_reward
        except (KeyError, ValueError) as e:
            # Log error but return 0 to avoid breaking training
            if not self.quiet:
                print(f"⚠️  WARNING: Failed to calculate situational reward: {e}")
            return 0.0
    
    def _calculate_objective_reward_turn5(self, game_state: Dict[str, Any], unit_rewards: Dict[str, Any]) -> float:
        """
        Calculate reward for objective control at end of turn 5.
        
        Simple approach: Reward per objective controlled by Player 0 (learning agent).
        Only applies when game ends at turn 5 (not elimination).
        Reward value is read from config: objective_rewards.reward_per_objective_turn5
        
        Returns:
            Reward value (reward_per_objective * number of objectives controlled by P0)
        """
        # Only apply at end of turn 5 (not elimination)
        current_turn = game_state.get("turn", 0)
        turn_limit_reached = game_state.get("turn_limit_reached", False)
        
        # Check if game ended at turn 5
        # Either: turn_limit_reached is True (P1 just completed turn 5)
        # Or: turn > 5 (standard end of turn 5)
        is_turn5_end = turn_limit_reached or (current_turn > 5)
        
        if not is_turn5_end:
            return 0.0
        
        # Check if game ended by elimination (not turn limit)
        # If winner is determined by elimination, don't give objective rewards
        # (objectives only matter when game ends at turn 5)
        living_units_by_player = {}
        for unit in game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1
        
        # If one player has no living units, game ended by elimination (not turn 5)
        if len(living_units_by_player) < 2:
            return 0.0
        
        # Both players still alive - game ended at turn 5
        # Calculate objectives controlled by Player 0
        if not self.state_manager:
            return 0.0
        
        obj_counts = self.state_manager.count_controlled_objectives(game_state)
        p0_objectives = obj_counts.get(0, 0)
        
        # Get reward per objective from config (REQUIRED - raise error if missing)
        if "objective_rewards" not in unit_rewards:
            raise KeyError(f"Unit rewards missing required 'objective_rewards' section")
        
        objective_rewards = unit_rewards["objective_rewards"]
        if "reward_per_objective_turn5" not in objective_rewards:
            raise KeyError(f"Objective rewards missing required 'reward_per_objective_turn5' value")
        
        reward_per_objective = objective_rewards["reward_per_objective_turn5"]
        
        total_reward = reward_per_objective * p0_objectives
        
        return total_reward
    
    def _get_system_penalties(self):
        """Get system penalty values from rewards config."""
        # Import here to avoid circular dependency
        from config_loader import get_config_loader
        
        # Get controlled_agent from config
        controlled_agent = self.config.get("controlled_agent")
        if not controlled_agent:
            raise ValueError(
                "controlled_agent missing from config - required to load agent-specific rewards. "
                "RewardCalculator requires config dict with 'controlled_agent' key."
            )

        # CRITICAL FIX: Extract base agent key for file loading (strip phase suffix)
        # controlled_agent may be "Agent_phase1", but file is at "config/agents/Agent/Agent_rewards_config.json"
        base_agent_key = controlled_agent
        for phase_suffix in ['_phase1', '_phase2', '_phase3', '_phase4']:
            if controlled_agent.endswith(phase_suffix):
                base_agent_key = controlled_agent[:-len(phase_suffix)]
                break

        # Load agent-specific FULL rewards config to access system_penalties
        config_loader = get_config_loader()
        full_rewards_config = config_loader.load_agent_rewards_config(base_agent_key)

        # The rewards config has nested structure: {"AgentKey": {"system_penalties": {...}}}
        # First get the agent-specific section
        if base_agent_key not in full_rewards_config:
            raise KeyError(
                f"Missing agent section '{base_agent_key}' in {base_agent_key}_rewards_config.json. "
                f"Available keys: {list(full_rewards_config.keys())}"
            )

        agent_rewards = full_rewards_config[base_agent_key]

        if "system_penalties" not in agent_rewards:
            raise KeyError(
                f"Missing required 'system_penalties' section in {base_agent_key}_rewards_config.json['{base_agent_key}']. "
                "Required structure: {'system_penalties': {'forbidden_action': -1.0, 'invalid_action': -0.9, 'generic_error': -0.1, "
                "'system_response': 0.0}}"
            )
        return agent_rewards["system_penalties"]
    
    # ============================================================================
    # TACTICAL CONTEXT
    # ============================================================================
    
    def _build_tactical_context(self, unit: Dict[str, Any], result: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
        """Build tactical context for reward mapper."""
        action_type = result.get("action")

        # CRITICAL FIX: Handle both 'move' and 'flee' actions (flee is a type of move)
        # ADVANCE_IMPLEMENTATION: Also handle 'advance' (similar to move but in shooting phase)
        if action_type == "move" or action_type == "flee" or action_type == "advance":
            # AI_TURN.md COMPLIANCE: Direct access - movement context must provide coordinates
            if "fromCol" not in result:
                raise KeyError(f"Movement context missing required 'fromCol' field: {result}")
            if "fromRow" not in result:
                raise KeyError(f"Movement context missing required 'fromRow' field: {result}")
            if "toCol" not in result:
                raise KeyError(f"Movement context missing required 'toCol' field: {result}")
            if "toRow" not in result:
                raise KeyError(f"Movement context missing required 'toRow' field: {result}")
            old_col = result["fromCol"]
            old_row = result["fromRow"]
            new_col = result["toCol"]
            new_row = result["toRow"]
            
            # Calculate movement context
            moved_closer = self._moved_closer_to_enemies(unit, (old_col, old_row), (new_col, new_row), game_state)
            moved_away = self._moved_away_from_enemies(unit, (old_col, old_row), (new_col, new_row), game_state)
            moved_to_optimal_range = self._moved_to_optimal_range(unit, (new_col, new_row), game_state)
            moved_to_charge_range = self._moved_to_charge_range(unit, (new_col, new_row), game_state)
            moved_to_safety = self._moved_to_safety(unit, (new_col, new_row), game_state)
            
            # CHANGE 1: Add advanced tactical movement flags
            gained_los_on_priority_target = self._gained_los_on_priority_target(unit, (old_col, old_row), game_state, (new_col, new_row))
            moved_to_cover_from_enemies = self._moved_to_cover_from_enemies(unit, (new_col, new_row), game_state)
            safe_from_enemy_charges = self._safe_from_enemy_charges(unit, (new_col, new_row), game_state)
            safe_from_enemy_ranged = self._safe_from_enemy_ranged(unit, (new_col, new_row), game_state)

            context = {
                "moved_closer": moved_closer,
                "moved_away": moved_away,
                "moved_to_optimal_range": moved_to_optimal_range,
                "moved_to_charge_range": moved_to_charge_range,
                "moved_to_safety": moved_to_safety,
                "gained_los_on_priority_target": gained_los_on_priority_target,
                "moved_to_cover_from_enemies": moved_to_cover_from_enemies,
                "safe_from_enemy_charges": safe_from_enemy_charges,
                "safe_from_enemy_ranged": safe_from_enemy_ranged
            }
            
            # Handle same-position movement (no actual movement)
            if old_col == new_col and old_row == new_row:
                # Unit didn't actually move - this should NOT happen in normal flow
                # If it does, raise error to investigate
                raise ValueError(
                    f"Unit {unit.get('id')} has same fromCol/toCol and fromRow/toRow in movement result. "
                    f"This should be a WAIT action, not MOVE. Result: {result}"
                )

            # Verify at least one primary flag is set - NO FALLBACK, expose bugs!
            # ADVANCE_IMPLEMENTATION: For advance, allow no primary flags (advance is more flexible)
            primary_flags = [
                context.get("moved_closer", False),
                context.get("moved_away", False),
                context.get("moved_to_optimal_range", False),
                context.get("moved_to_charge_range", False),
                context.get("moved_to_safety", False)
            ]
            if not any(primary_flags):
                # For advance action, allow no primary flags (lateral movement, repositioning, etc.)
                if action_type == "advance":
                    # Advance can have no primary flags - reward_mapper.get_advance_reward handles base reward
                    pass
                else:
                    # For move/flee: use moved_closer as fallback when detection fails (edge case)
                    context["moved_closer"] = True

            return context
        
        return {}
    
    # ============================================================================
    # COMBAT ANALYSIS
    # ============================================================================
    
    def _calculate_combat_mix_score(self, unit: Dict[str, Any]) -> float:
        """
        Calculate unit's combat preference based on ACTUAL expected damage
        against their favorite target types (from unitType).
        
        MULTIPLE_WEAPONS_IMPLEMENTATION.md: Uses max expected damage from all weapons.
        
        Returns 0.1-0.9:
        - 0.1-0.3: Melee specialist (CC damage >> RNG damage)
        - 0.4-0.6: Balanced combatant
        - 0.7-0.9: Ranged specialist (RNG damage >> CC damage)
        
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        """
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        
        unit_type = unit["unitType"]
        
        # Determine favorite target stats based on specialization
        if "Swarm" in unit_type:
            target_T = 3
            target_save = 5
            target_invul = 7  # No invul (7+ = impossible)
        elif "Troop" in unit_type:
            target_T = 4
            target_save = 3
            target_invul = 7  # No invul
        elif "Elite" in unit_type:
            target_T = 5
            target_save = 2
            target_invul = 4  # 4+ invulnerable
        else:  # Monster/Leader
            target_T = 6
            target_save = 3
            target_invul = 7  # No invul
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate max expected damage from all weapons
        from shared.data_validation import require_key
        
        # Calculate max EXPECTED ranged damage from all ranged weapons
        ranged_expected_list = []
        rng_weapons = unit.get("RNG_WEAPONS", [])
        for weapon in rng_weapons:
            expected = self._calculate_expected_damage(
                num_attacks=require_key(weapon, "NB"),
                to_hit_stat=require_key(weapon, "ATK"),
                strength=require_key(weapon, "STR"),
                target_toughness=target_T,
                ap=require_key(weapon, "AP"),
                target_save=target_save,
                target_invul=target_invul,
                damage_per_wound=require_key(weapon, "DMG")
            )
            ranged_expected_list.append(expected)
        
        ranged_expected = max(ranged_expected_list) if ranged_expected_list else 0.0
        
        # Calculate max EXPECTED melee damage from all melee weapons
        melee_expected_list = []
        cc_weapons = unit.get("CC_WEAPONS", [])
        for weapon in cc_weapons:
            expected = self._calculate_expected_damage(
                num_attacks=require_key(weapon, "NB"),
                to_hit_stat=require_key(weapon, "ATK"),
                strength=require_key(weapon, "STR"),
                target_toughness=target_T,
                ap=require_key(weapon, "AP"),
                target_save=target_save,
                target_invul=target_invul,
                damage_per_wound=require_key(weapon, "DMG")
            )
            melee_expected_list.append(expected)
        
        melee_expected = max(melee_expected_list) if melee_expected_list else 0.0
        
        total_expected = ranged_expected + melee_expected
        
        if total_expected == 0:
            return 0.5  # Neutral (no combat power)
        
        # Scale to 0.1-0.9 range
        raw_ratio = ranged_expected / total_expected
        return 0.1 + (raw_ratio * 0.8)
    
    def _calculate_expected_damage(self, num_attacks: int, to_hit_stat: int, 
                                   strength: int, target_toughness: int, ap: int, 
                                   target_save: int, target_invul: int, 
                                   damage_per_wound: int) -> float:
        """
        Calculate expected damage using W40K dice mechanics with invulnerable saves.
        
        Expected damage = Attacks × P(hit) × P(wound) × P(fail_save) × Damage
        """
        # Hit probability
        p_hit = max(0.0, min(1.0, (7 - to_hit_stat) / 6.0))
        
        # Wound probability
        wound_target = self._calculate_wound_target(strength, target_toughness)
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        # Save failure probability (use better of armor or invul)
        modified_armor_save = target_save - ap
        best_save = min(modified_armor_save, target_invul)

        if best_save > 6:
            p_fail_save = 1.0  # Impossible to save
        else:
            p_fail_save = max(0.0, min(1.0, (best_save - 1) / 6.0))
        
        # Expected damage per turn
        expected = num_attacks * p_hit * p_wound * p_fail_save * damage_per_wound
        
        return expected
    
    def _calculate_favorite_target(self, unit: Dict[str, Any]) -> float:
        """
        Extract favorite target type from unitType name.
        
        unitType format: "Faction_Movement_PowerLevel_AttackPreference"
        Example: "SpaceMarine_Infantry_Troop_RangedSwarm"
                                              ^^^^^^^^^^^^
                                              Ranged + Swarm
        
        Returns 0.0-1.0 encoding:
        - 0.0 = Swarm specialist (vs HP_MAX ≤ 1)
        - 0.33 = Troop specialist (vs HP_MAX 2-3)
        - 0.66 = Elite specialist (vs HP_MAX 4-6)
        - 1.0 = Monster specialist (vs HP_MAX ≥ 7)
        
        AI_TURN.md COMPLIANCE: Direct field access
        """
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        
        unit_type = unit["unitType"]
        
        # Parse attack preference component (last part after final underscore)
        parts = unit_type.split("_")
        if len(parts) < 4:
            return 0.5  # Default neutral if format unexpected
        
        attack_pref = parts[3]  # e.g., "RangedSwarm", "MeleeElite"
        
        # Extract target preference from attack_pref
        if "Swarm" in attack_pref:
            return 0.0
        elif "Troop" in attack_pref:
            return 0.33
        elif "Elite" in attack_pref:
            return 0.66
        elif "Monster" in attack_pref or "Leader" in attack_pref:
            return 1.0
        else:
            return 0.5  # Default neutral
    
    def _calculate_movement_direction(self, unit: Dict[str, Any], 
                                     active_unit: Dict[str, Any]) -> float:
        """
        Encode temporal behavior in single float - replaces frame stacking.
        
        Detects unit's movement pattern relative to active unit:
        - 0.00-0.24: Fled far from me (>50% MOVE away)
        - 0.25-0.49: Moved away slightly (<50% MOVE away)
        - 0.50-0.74: Advanced slightly (<50% MOVE toward)
        - 0.75-1.00: Charged at me (>50% MOVE toward)
        
        Critical for detecting threats before they strike!
        AI_TURN.md COMPLIANCE: Direct field access
        """
        # Get last known position from cache
        if not hasattr(self, 'last_unit_positions') or not self.last_unit_positions:
            return 0.5  # Unknown/first turn
        
        if "id" not in unit:
            raise KeyError(f"Unit missing required 'id' field: {unit}")
        
        unit_id = str(unit["id"])
        if unit_id not in self.last_unit_positions:
            return 0.5  # No previous position data
        
        # Validate required position fields
        if "col" not in unit or "row" not in unit:
            raise KeyError(f"Unit missing required position fields: {unit}")
        if "col" not in active_unit or "row" not in active_unit:
            raise KeyError(f"Active unit missing required position fields: {active_unit}")
        
        prev_col, prev_row = self.last_unit_positions[unit_id]
        curr_col, curr_row = unit["col"], unit["row"]
        
        # Calculate movement toward/away from active unit
        prev_dist = calculate_hex_distance(
            prev_col, prev_row, 
            active_unit["col"], active_unit["row"]
        )
        curr_dist = calculate_hex_distance(
            curr_col, curr_row,
            active_unit["col"], active_unit["row"]
        )
        
        move_distance = calculate_hex_distance(prev_col, prev_row, curr_col, curr_row)
        
        if "MOVE" not in unit:
            raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
        max_move = unit["MOVE"]
        
        if move_distance == 0:
            return 0.5  # No movement
        
        delta_dist = prev_dist - curr_dist  # Positive = moved closer
        move_ratio = abs(delta_dist) / max(1, max_move)  # Prevent division by zero
        
        if delta_dist < 0:  # Moved away
            if move_ratio > 0.5:
                return 0.12  # Fled far (>50% MOVE away)
            else:
                return 0.37  # Moved away slightly
        else:  # Moved closer
            if move_ratio > 0.5:
                return 0.87  # Charged (>50% MOVE toward)
            else:
                return 0.62  # Advanced slightly
    
    def _calculate_kill_probability(self, shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Calculate actual probability to kill target this turn considering W40K dice mechanics.
        
        Considers:
        - Hit probability (RNG_ATK vs d6)
        - Wound probability (RNG_STR vs target T)
        - Save failure probability (target saves vs RNG_AP)
        - Number of shots (RNG_NB)
        - Damage per successful wound (RNG_DMG)
        
        Returns: 0.0-1.0 probability
        """
        current_phase = game_state["phase"]
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or best weapon
        from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
        from engine.ai.weapon_selector import get_best_weapon_for_target
        
        if current_phase == "shoot":
            # Get best weapon for this target
            best_weapon_idx, _ = get_best_weapon_for_target(shooter, target, game_state, is_ranged=True)
            if best_weapon_idx >= 0 and shooter.get("RNG_WEAPONS"):
                weapon = shooter["RNG_WEAPONS"][best_weapon_idx]
            else:
                # Fallback to selected weapon
                weapon = get_selected_ranged_weapon(shooter)
                if not weapon and shooter.get("RNG_WEAPONS"):
                    weapon = shooter["RNG_WEAPONS"][0]  # Fallback to first weapon
                if not weapon:
                    return 0.0
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = weapon["DMG"]
            num_attacks = weapon["NB"]
            ap = weapon["AP"]
        else:
            # Get best weapon for this target
            best_weapon_idx, _ = get_best_weapon_for_target(shooter, target, game_state, is_ranged=False)
            if best_weapon_idx >= 0 and shooter.get("CC_WEAPONS"):
                weapon = shooter["CC_WEAPONS"][best_weapon_idx]
            else:
                # Fallback to selected weapon
                weapon = get_selected_melee_weapon(shooter)
                if not weapon and shooter.get("CC_WEAPONS"):
                    weapon = shooter["CC_WEAPONS"][0]  # Fallback to first weapon
                if not weapon:
                    return 0.0
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = weapon["DMG"]
            num_attacks = weapon["NB"]
            ap = weapon["AP"]
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        
        if "T" not in target:
            raise KeyError(f"Target missing required 'T' field: {target}")
        wound_target = self._calculate_wound_target(strength, target["T"])
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        # Save failure probability (uses imported function from shooting_handlers)
        save_target = self._calculate_save_target(target, ap)
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        p_damage_per_attack = p_hit * p_wound * p_fail_save
        expected_damage = num_attacks * p_damage_per_attack * damage
        
        if expected_damage >= target["HP_CUR"]:
            return 1.0
        else:
            return min(1.0, expected_damage / target["HP_CUR"])
    
    def _calculate_danger_probability(self, defender: Dict[str, Any], attacker: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Calculate probability that attacker will kill defender on its next turn.
        Works for ANY unit pair (active unit vs enemy, VIP vs enemy, etc.)

        Considers:
        - Distance (can they reach?) - uses BFS pathfinding to respect walls
        - Hit/wound/save probabilities
        - Number of attacks
        - Damage output

        Returns: 0.0-1.0 probability
        """
        # Use BFS pathfinding distance to respect walls for reachability
        distance = calculate_pathfinding_distance(
            defender["col"], defender["row"],
            attacker["col"], attacker["row"],
            game_state
        )
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from weapons
        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        max_ranged_range = get_max_ranged_range(attacker)
        melee_range = get_melee_range()  # Always 1
        
        can_use_ranged = max_ranged_range > 0 and distance <= max_ranged_range
        can_use_melee = distance <= melee_range

        if not can_use_ranged and not can_use_melee:
            return 0.0

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use best weapon for attacker against defender
        from engine.ai.weapon_selector import get_best_weapon_for_target
        
        weapon = None
        if can_use_ranged and not can_use_melee:
            # Only ranged available
            best_weapon_idx, _ = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=True)
            if best_weapon_idx >= 0 and attacker.get("RNG_WEAPONS"):
                weapon = attacker["RNG_WEAPONS"][best_weapon_idx]
            else:
                # Fallback to selected or first weapon
                from engine.utils.weapon_helpers import get_selected_ranged_weapon
                weapon = get_selected_ranged_weapon(attacker)
                if not weapon and attacker.get("RNG_WEAPONS"):
                    weapon = attacker["RNG_WEAPONS"][0]
        elif can_use_melee and not can_use_ranged:
            # Only melee available
            best_weapon_idx, _ = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=False)
            if best_weapon_idx >= 0 and attacker.get("CC_WEAPONS"):
                weapon = attacker["CC_WEAPONS"][best_weapon_idx]
            else:
                # Fallback to selected or first weapon
                from engine.utils.weapon_helpers import get_selected_melee_weapon
                weapon = get_selected_melee_weapon(attacker)
                if not weapon and attacker.get("CC_WEAPONS"):
                    weapon = attacker["CC_WEAPONS"][0]
        else:
            # Both available - choose best overall
            best_rng_idx, rng_kill_prob = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=True)
            best_cc_idx, cc_kill_prob = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=False)
            
            if rng_kill_prob >= cc_kill_prob and best_rng_idx >= 0 and attacker.get("RNG_WEAPONS"):
                weapon = attacker["RNG_WEAPONS"][best_rng_idx]
            elif best_cc_idx >= 0 and attacker.get("CC_WEAPONS"):
                weapon = attacker["CC_WEAPONS"][best_cc_idx]
            else:
                # Fallback to selected ranged or melee
                from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
                weapon = get_selected_ranged_weapon(attacker) or get_selected_melee_weapon(attacker)
        
        if not weapon:
            return 0.0
        
        from shared.data_validation import require_key
        hit_target = require_key(weapon, "ATK")
        strength = require_key(weapon, "STR")
        damage = require_key(weapon, "DMG")
        num_attacks = require_key(weapon, "NB")
        ap = require_key(weapon, "AP")
        
        if num_attacks == 0:
            return 0.0
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        
        if "T" not in defender:
            return 0.0
        wound_target = self._calculate_wound_target(strength, defender["T"])
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        save_target = _calculate_save_target(defender, ap)
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        p_damage_per_attack = p_hit * p_wound * p_fail_save
        expected_damage = num_attacks * p_damage_per_attack * damage
        
        if expected_damage >= defender["HP_CUR"]:
            return 1.0
        else:
            return min(1.0, expected_damage / defender["HP_CUR"])
    
    def _calculate_army_weighted_threat(self, target: Dict[str, Any], valid_targets: List[Dict[str, Any]], game_state: Dict[str, Any]) -> float:
        """
        Calculate army-wide weighted threat score considering all friendly units by VALUE.
        
        This is the STRATEGIC PRIORITY feature that teaches the agent to:
        - Protect high-VALUE units (Leaders, Elites)
        - Consider threats to the entire team, not just personal survival
        - Make sacrifices when strategically necessary
        
        Logic:
        1. For each friendly unit, calculate danger from this target
        2. Weight that danger by the friendly unit's VALUE (1-200)
        3. Sum all weighted dangers
        4. Normalize to 0.0-1.0 based on highest threat among all targets
        
        Returns: 0.0-1.0 (1.0 = highest strategic threat among all targets)
        """
        my_player = game_state["current_player"]
        friendly_units = [
            u for u in game_state["units"]
            if u["player"] == my_player and u["HP_CUR"] > 0
        ]
        
        if not friendly_units:
            return 0.0
        
        total_weighted_threat = 0.0
        for friendly in friendly_units:
            danger = self._calculate_danger_probability(friendly, target, game_state)
            if "VALUE" not in friendly:
                raise KeyError(f"Friendly unit missing required 'VALUE' field: {friendly}")
            unit_value = friendly["VALUE"]
            weighted_threat = danger * unit_value
            total_weighted_threat += weighted_threat

        all_weighted_threats = []
        for t in valid_targets:
            t_total = 0.0
            for friendly in friendly_units:
                danger = self._calculate_danger_probability(friendly, t, game_state)
                if "VALUE" not in friendly:
                    raise KeyError(f"Friendly unit missing required 'VALUE' field: {friendly}")
                unit_value = friendly["VALUE"]
                t_total += danger * unit_value
            all_weighted_threats.append(t_total)
        
        max_weighted_threat = max(all_weighted_threats) if all_weighted_threats else 1.0
        
        if max_weighted_threat > 0:
            return min(1.0, total_weighted_threat / max_weighted_threat)
        else:
            return 0.0
    
    def _calculate_target_type_match(self, active_unit: Dict[str, Any], 
                                    target: Dict[str, Any]) -> float:
        """
        Calculate unit_registry-based type compatibility (0.0-1.0).
        Higher = this unit is specialized against this target type.
        
        Example: RangedSwarm unit gets 1.0 against Swarm targets, 0.3 against others
        """
        try:
            if not hasattr(self, 'unit_registry') or not self.unit_registry:
                return 0.5
            
            unit_type = active_unit.get("unitType", "")
            
            if "Swarm" in unit_type:
                preferred = "swarm"
            elif "Troop" in unit_type:
                preferred = "troop"
            elif "Elite" in unit_type:
                preferred = "elite"
            elif "Leader" in unit_type:
                preferred = "leader"
            else:
                return 0.5
            
            if "HP_MAX" not in target:
                raise KeyError(f"Target missing required 'HP_MAX' field: {target}")
            target_hp = target["HP_MAX"]
            if target_hp <= 1:
                target_type = "swarm"
            elif target_hp <= 3:
                target_type = "troop"
            elif target_hp <= 6:
                target_type = "elite"
            else:
                target_type = "leader"
            
            return 1.0 if preferred == target_type else 0.3
            
        except Exception:
            return 0.5
    
    # ============================================================================
    # MOVEMENT ANALYSIS
    # ============================================================================
    
    def _moved_to_cover_from_enemies(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit is hidden from enemy RANGED units (melee LoS irrelevant)."""
        enemies = [u for u in game_state["units"] 
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        if not enemies:
            return False
        
        # Count how many RANGED enemies have LoS to this position
        ranged_enemies_with_los = 0
        new_unit_state = unit.copy()
        new_unit_state["col"] = new_pos[0]
        new_unit_state["row"] = new_pos[1]
        
        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        
        for enemy in enemies:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
            max_rng_range = get_max_ranged_range(enemy)
            melee_range = get_melee_range()  # Always 1
            
            # CRITICAL: Use same logic as observation encoding
            # Ranged unit = has ranged weapons with range > melee range
            is_ranged_unit = max_rng_range > melee_range
            
            if is_ranged_unit and max_rng_range > 0:
                distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
                # Enemy in shooting range and has LoS?
                if distance <= max_rng_range:
                    if has_line_of_sight(enemy, new_unit_state, game_state):
                        ranged_enemies_with_los += 1
        
        # Good cover from ranged = 0 or 1 ranged enemy can see you
        return ranged_enemies_with_los <= 1
    
    def _moved_closer_to_enemies(self, unit: Dict[str, Any], old_pos: Tuple[int, int], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved closer to enemies (or maintained same distance = lateral move)."""
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if not enemies:
            return False

        old_min_distance = min(calculate_hex_distance(old_pos[0], old_pos[1], e["col"], e["row"]) for e in enemies)
        new_min_distance = min(calculate_hex_distance(new_pos[0], new_pos[1], e["col"], e["row"]) for e in enemies)

        # Include equal distance (lateral movement) - unit is still engaged
        return new_min_distance <= old_min_distance
    
    def _moved_away_from_enemies(self, unit: Dict[str, Any], old_pos: Tuple[int, int], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved away from enemies."""
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if not enemies:
            return False

        old_min_distance = min(calculate_hex_distance(old_pos[0], old_pos[1], e["col"], e["row"]) for e in enemies)
        new_min_distance = min(calculate_hex_distance(new_pos[0], new_pos[1], e["col"], e["row"]) for e in enemies)

        return new_min_distance > old_min_distance
    
    def _moved_to_optimal_range(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved to optimal shooting range per W40K shooting rules.

        CRITICAL: Must check BOTH range AND line of sight.
        A position is only optimal if the unit can actually shoot from there.
        """
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        
        max_range = get_max_ranged_range(unit)
        if max_range <= 0:
            return False
        
        min_range = get_melee_range()  # Minimum engagement distance (always 1)
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]

        # Create temporary unit state at new position for LOS check
        temp_unit = unit.copy()
        temp_unit["col"] = new_pos[0]
        temp_unit["row"] = new_pos[1]

        for enemy in enemies:
            distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
            # Optimal range: can shoot but not in melee (min_range < distance <= max_range)
            if min_range < distance <= max_range:
                # CRITICAL: Also check LOS - position is only optimal if we can actually shoot
                if has_line_of_sight(temp_unit, enemy, game_state):
                    return True

        return False
    
    def _moved_to_charge_range(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved to charge range of enemies.

        Uses BFS pathfinding distance to respect walls for charge reachability.
        """
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
        cc_weapons = unit.get("CC_WEAPONS", [])
        if not cc_weapons:
            return False
        
        # Check if any melee weapon has damage > 0
        from shared.data_validation import require_key
        has_melee_damage = any(require_key(w, "DMG") > 0 for w in cc_weapons)
        if not has_melee_damage:
            return False

        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if "MOVE" not in unit:
            raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
        max_charge_range = unit["MOVE"] + 12  # Average 2d6 charge distance

        for enemy in enemies:
            # Use BFS pathfinding to respect walls for charge reachability
            distance = calculate_pathfinding_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"], game_state)
            if distance <= max_charge_range:
                return True

        return False
    
    def _moved_to_safety(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved to safety from enemy threats."""
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]

        # No enemies should mean game is over - don't mask this with return True
        if not enemies:
            return False

        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        
        for enemy in enemies:
            # Check if moved out of enemy threat range
            distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
            max_rng_range = get_max_ranged_range(enemy)
            melee_range = get_melee_range()  # Always 1
            enemy_threat_range = max(max_rng_range, melee_range)

            if distance > enemy_threat_range:
                return True

        return False
    
    def _gained_los_on_priority_target(self, unit: Dict[str, Any], old_pos: Tuple[int, int], game_state: Dict[str, Any], 
                                       new_pos: Tuple[int, int]) -> bool:
        """Check if unit gained LoS on its highest-priority target."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range
        
        max_range = get_max_ranged_range(unit)
        if max_range <= 0:
            return False
        
        # Get all enemies in shooting range
        enemies_in_range = []
        for enemy in game_state["units"]:
            if "player" not in enemy or "HP_CUR" not in enemy:
                raise KeyError(f"Enemy unit missing required fields: {enemy}")
            
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                if "col" not in enemy or "row" not in enemy:
                    raise KeyError(f"Enemy unit missing required position fields: {enemy}")
                
                distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                if distance <= max_range:
                    enemies_in_range.append(enemy)
        
        if not enemies_in_range:
            return False
        
        # Find priority target (lowest HP for RangedSwarm units)
        # AI_TURN.md COMPLIANCE: All units must have HP_CUR
        for e in enemies_in_range:
            if "HP_CUR" not in e:
                raise KeyError(f"Enemy missing required 'HP_CUR' field: {e}")
        priority_target = min(enemies_in_range, key=lambda e: e["HP_CUR"])
        
        # Check LoS at old position
        old_unit_state = unit.copy()
        old_unit_state["col"] = old_pos[0]
        old_unit_state["row"] = old_pos[1]
        had_los_before = has_line_of_sight(old_unit_state, priority_target, game_state)
        
        # Check LoS at new position
        new_unit_state = unit.copy()
        new_unit_state["col"] = new_pos[0]
        new_unit_state["row"] = new_pos[1]
        has_los_now = has_line_of_sight(new_unit_state, priority_target, game_state)
        
        # Gained LoS if didn't have before but have now
        return (not had_los_before) and has_los_now
    
    def _safe_from_enemy_charges(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit is safe from enemy MELEE charges (ranged proximity irrelevant).

        Uses BFS pathfinding distance to respect walls for charge reachability.
        """
        enemies = [u for u in game_state["units"]
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]

        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        
        for enemy in enemies:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
            if "MOVE" not in enemy:
                raise KeyError(f"Enemy missing required 'MOVE' field: {enemy}")
            
            max_rng_range = get_max_ranged_range(enemy)
            melee_range = get_melee_range()  # Always 1
            cc_weapons = enemy.get("CC_WEAPONS", [])
            
            # CRITICAL: Use same logic as observation encoding
            # Melee unit = has melee weapons and max ranged range <= melee range
            is_melee_unit = len(cc_weapons) > 0 and max_rng_range <= melee_range
            
            # Check if any melee weapon has damage > 0
            from shared.data_validation import require_key
            has_melee_damage = any(require_key(w, "DMG") > 0 for w in cc_weapons) if cc_weapons else False

            if is_melee_unit and has_melee_damage:
                # Use BFS pathfinding to respect walls for charge reachability
                distance = calculate_pathfinding_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"], game_state)

                # Max charge distance = MOVE + 9 (2d6 average charge roll)
                max_charge_distance = enemy["MOVE"] + 9

                # Unsafe if any melee enemy can charge us
                if distance <= max_charge_distance:
                    return False

        # Safe - no melee enemies in charge range
        return True
    
    def _safe_from_enemy_ranged(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit is beyond range of enemy RANGED units."""
        enemies = [u for u in game_state["units"] 
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        safe_distance_count = 0
        total_ranged_enemies = 0
        
        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        
        for enemy in enemies:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
            max_rng_range = get_max_ranged_range(enemy)
            melee_range = get_melee_range()  # Always 1
            
            # Only consider ranged units (matches observation encoding)
            is_ranged_unit = max_rng_range > melee_range
            
            if is_ranged_unit and max_rng_range > 0:
                total_ranged_enemies += 1
                distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
                # Safe if beyond their shooting range
                if distance > max_rng_range:
                    safe_distance_count += 1
        
        if total_ranged_enemies == 0:
            return False  # No bonus if no ranged enemies
        
        # Consider safe if beyond range of 50%+ of ranged enemies
        return safe_distance_count >= (total_ranged_enemies / 2.0)
    
    # ============================================================================
    # REWARD MAPPER
    # ============================================================================
    
    def _get_reward_mapper(self):
        """Get reward mapper instance with current rewards config."""
        from ai.reward_mapper import RewardMapper
        return RewardMapper(self.rewards_config)

    def _determine_winner(self, game_state: Dict[str, Any]) -> Optional[int]:
        """
        Determine winner based on objective control or elimination.
        
        CRITICAL FIX: Now delegates to state_manager to support
        objective-based victory at turn 5 (same logic as game_state.py).
        """
        if self.state_manager:
            # Use state_manager's determine_winner (supports objectives at turn 5)
            winner, _ = self.state_manager.determine_winner_with_method(game_state)
            return winner
        
        # Fallback for backward compatibility (should not happen in normal usage)
        # This is the old logic that ignores objectives
        living_units_by_player = {}
        for unit in game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1
        
        living_players = list(living_units_by_player.keys())
        if len(living_players) == 1:
            return living_players[0]
        elif len(living_players) == 0:
            return -1
        else:
            return None
    
    def _get_reward_mapper_unit_rewards(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Get unit-specific rewards config for reward_mapper."""
        enriched_unit = self._enrich_unit_for_reward_mapper(unit)
        reward_mapper = self._get_reward_mapper()
        return reward_mapper._get_unit_rewards(enriched_unit)
    
    def _enrich_unit_for_reward_mapper(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich unit data with tactical flags required by reward_mapper."""
        enriched = unit.copy()

        # CRITICAL FIX: Use controlled_agent for reward config lookup (includes phase suffix)
        config_controlled_agent = self.config.get("controlled_agent") if self.config else None

        # AI_TURN.md COMPLIANCE: NO FALLBACKS - proper error handling
        if config_controlled_agent:
            # Training mode: use controlled_agent which includes phase suffix
            agent_key = config_controlled_agent
        elif hasattr(self, 'unit_registry') and self.unit_registry:
            # Direct access - NO DEFAULTS allowed
            if "unitType" not in unit:
                raise KeyError(f"Unit missing required 'unitType' field: {unit}")
            scenario_unit_type = unit["unitType"]
            # Let unit_registry.get_model_key() raise ValueError if unit type not found
            agent_key = self.unit_registry.get_model_key(scenario_unit_type)
        else:
            raise ValueError("Missing both controlled_agent config and unit_registry - cannot determine agent key")

        # CRITICAL: Set the agent type as unitType for reward config lookup
        enriched["unitType"] = agent_key
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        
        max_rng_range = get_max_ranged_range(unit)
        melee_range = get_melee_range()  # Always 1
        
        # Add required tactical flags based on unit stats
        enriched["is_ranged"] = max_rng_range > melee_range
        enriched["is_melee"] = not enriched["is_ranged"]
        
        # AI_TURN.md COMPLIANCE: Direct field access for required fields
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get max damage from all weapons
        from shared.data_validation import require_key
        rng_weapons = unit.get("RNG_WEAPONS", [])
        cc_weapons = unit.get("CC_WEAPONS", [])
        
        rng_dmg = max((require_key(w, "DMG") for w in rng_weapons), default=0.0)
        cc_dmg = max((require_key(w, "DMG") for w in cc_weapons), default=0.0)
        
        # Map UPPERCASE fields to lowercase for reward_mapper compatibility
        enriched["name"] = unit["unitType"]
        enriched["rng_dmg"] = rng_dmg
        enriched["cc_dmg"] = cc_dmg
        
        return enriched
    
    def _get_reward_config_key_for_unit(self, unit: Dict[str, Any]) -> str:
        """Map unit type to reward config key using unit registry."""
        # AI_TURN.md COMPLIANCE: Direct field access required
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        unit_type = unit["unitType"]

        # Use unit registry to get agent key (matches rewards config)
        try:
            agent_key = self.unit_registry.get_model_key(unit_type)
            return agent_key
        except ValueError as e:
            # AI_TURN.md COMPLIANCE: NO FALLBACKS - propagate the error
            raise ValueError(f"Failed to get reward config key for unit type '{unit_type}': {e}")

    def _get_all_valid_targets(self, acting_unit: Dict[str, Any], game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get all valid enemy targets for the acting unit."""
        if not acting_unit or not game_state:
            return []

        targets = []
        acting_player = acting_unit.get("player")

        for unit in game_state.get("units", []):
            # Enemy units that are alive
            if unit.get("player") != acting_player and unit.get("HP_CUR", 0) > 0:
                targets.append(unit)

        return targets

    # ============================================================================
    # POSITION SCORE CALCULATION (Phase 2 Movement Rewards)
    # ============================================================================

    def calculate_position_score(self, unit: Dict[str, Any], position: Tuple[int, int],
                                  game_state: Dict[str, Any], tactical_positioning: float = 0.0) -> float:
        """
        Calculate position score for movement rewards.

        Formula: position_score = offensive_value - (defensive_threat × tactical_positioning)

        Args:
            unit: The unit evaluating the position
            position: (col, row) tuple of the position to evaluate
            game_state: Current game state
            tactical_positioning: Hyperparameter controlling defense weight
                - 0.0 = Phase 2 (offensive only, no defensive consideration)
                - 0.5 = aggressive (low defense weight)
                - 1.0 = balanced (equal weight)
                - 2.0 = defensive (high defense weight)

        Returns:
            Position score (higher = better position)
        """
        offensive_value = self._calculate_offensive_value(unit, position, game_state)

        # Phase 2: tactical_positioning=0 means ignore defensive_threat entirely
        # This avoids teaching wrong predictions vs dumb bots
        # Phase 3+: Enable defensive_threat with self-play or smart bots
        if tactical_positioning > 0:
            defensive_threat = self._calculate_defensive_threat(unit, position, game_state)
            return offensive_value - (defensive_threat * tactical_positioning)
        else:
            return offensive_value

    def _calculate_offensive_value(self, unit: Dict[str, Any], position: Tuple[int, int],
                                    game_state: Dict[str, Any]) -> float:
        """
        Calculate offensive value from a position.

        AI_TRAINING.md: Estimate total VALUE the unit can secure by shooting from this position.
        Uses greedy allocation of attacks to targets, sorted by VALUE.
        """
        col, row = position

        # Create temporary unit state at the new position for LOS checks
        temp_unit = unit.copy()
        temp_unit["col"] = col
        temp_unit["row"] = row

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range, get_selected_ranged_weapon
        
        max_range = get_max_ranged_range(unit)
        if max_range <= 0:
            return 0.0

        # Get all visible enemies
        visible_enemies = []
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                if has_line_of_sight(temp_unit, enemy, game_state):
                    # Check if in range
                    distance = calculate_hex_distance(col, row, enemy["col"], enemy["row"])
                    if distance <= max_range:
                        visible_enemies.append(enemy)

        if not visible_enemies:
            return 0.0

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get selected weapon's NB
        selected_weapon = get_selected_ranged_weapon(unit)
        if not selected_weapon:
            return 0.0
        
        from shared.data_validation import require_key
        num_attacks = require_key(selected_weapon, "NB")

        # Calculate attacks_needed and VALUE for each target
        targets_data = []
        for enemy in visible_enemies:
            if "VALUE" not in enemy:
                raise KeyError(f"Enemy missing required 'VALUE' field: {enemy}")
            value = enemy["VALUE"]
            turns_to_kill = self._calculate_turns_to_kill(unit, enemy, game_state)
            attacks_needed = turns_to_kill * num_attacks
            targets_data.append({
                "enemy": enemy,
                "value": value,
                "turns_to_kill": turns_to_kill,
                "attacks_needed": attacks_needed
            })

        # Sort by target_priority = VALUE / turns_to_kill (highest first)
        # This prioritizes efficient kills (high value, easy to kill)
        targets_data.sort(key=lambda x: x["value"] / x["turns_to_kill"] if x["turns_to_kill"] > 0 else x["value"] * 100, reverse=True)

        # Greedy allocation
        attacks_remaining = float(num_attacks)
        offensive_value = 0.0

        for target in targets_data:
            if attacks_remaining <= 0:
                break

            if attacks_remaining >= target["attacks_needed"]:
                # Secured kill - add full VALUE
                offensive_value += target["value"]
                attacks_remaining -= target["attacks_needed"]
            else:
                # Probabilistic kill
                kill_prob = attacks_remaining / target["attacks_needed"]
                offensive_value += target["value"] * kill_prob
                attacks_remaining = 0

        return offensive_value

    def _calculate_defensive_threat(self, unit: Dict[str, Any], position: Tuple[int, int],
                                     game_state: Dict[str, Any]) -> float:
        """
        Calculate defensive threat at a position.

        AI_TRAINING.md: Estimate damage received, accounting for enemy movement decisions
        and targeting priorities. Uses smart targeting (enemies are intelligent).
        """
        from engine.phase_handlers.movement_handlers import _get_hex_neighbors, _is_traversable_hex

        col, row = position
        my_player = unit["player"]
        if "VALUE" not in unit:
            raise KeyError(f"Unit missing required 'VALUE' field: {unit}")
        my_value = unit["VALUE"]

        # Get all living friendly units
        friendlies = [u for u in game_state["units"]
                     if u["player"] == my_player and u["HP_CUR"] > 0]

        # Get all living enemy units
        enemies = [u for u in game_state["units"]
                  if u["player"] != my_player and u["HP_CUR"] > 0]

        if not enemies:
            return 0.0

        total_threat = 0.0

        for enemy in enemies:
            # Step 1: Find positions enemy could reach
            reachable_positions = self._get_enemy_reachable_positions(enemy, game_state)

            # Step 2: Check which friendlies this enemy could see after moving
            reachable_friendlies = []
            can_reach_me = False

            for reachable_pos in reachable_positions:
                temp_enemy = enemy.copy()
                temp_enemy["col"] = reachable_pos[0]
                temp_enemy["row"] = reachable_pos[1]

                # Check if enemy can see ME from this position
                temp_unit = unit.copy()
                temp_unit["col"] = col
                temp_unit["row"] = row

                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
                from engine.utils.weapon_helpers import get_max_ranged_range
                max_rng_range = get_max_ranged_range(enemy)

                if has_line_of_sight(temp_enemy, temp_unit, game_state):
                    distance = calculate_hex_distance(reachable_pos[0], reachable_pos[1], col, row)
                    if distance <= max_rng_range:
                        can_reach_me = True

                # Check all friendlies this enemy could see
                for friendly in friendlies:
                    if has_line_of_sight(temp_enemy, friendly, game_state):
                        distance = calculate_hex_distance(reachable_pos[0], reachable_pos[1],
                                                         friendly["col"], friendly["row"])
                        if distance <= max_rng_range:
                            if friendly["id"] not in [f["id"] for f in reachable_friendlies]:
                                reachable_friendlies.append(friendly)

            if not can_reach_me:
                continue  # This enemy can't threaten me

            # Step 3: Rank friendlies by priority from enemy's perspective
            friendly_priorities = []
            for friendly in reachable_friendlies:
                if "VALUE" not in friendly:
                    raise KeyError(f"Friendly unit missing required 'VALUE' field: {friendly}")
                f_value = friendly["VALUE"]
                f_turns_to_kill = self._calculate_turns_to_kill_by_attacker(enemy, friendly, game_state)
                if f_turns_to_kill > 0:
                    f_priority = f_value / f_turns_to_kill
                else:
                    f_priority = f_value * 100  # Very high priority if instant kill
                friendly_priorities.append({
                    "friendly": friendly,
                    "priority": f_priority
                })

            # Add myself to the list
            my_turns_to_kill = self._calculate_turns_to_kill_by_attacker(enemy, unit, game_state)
            if my_turns_to_kill > 0:
                my_priority = my_value / my_turns_to_kill
            else:
                my_priority = my_value * 100

            friendly_priorities.append({
                "friendly": unit,
                "priority": my_priority
            })

            # Sort by priority (highest first)
            friendly_priorities.sort(key=lambda x: x["priority"], reverse=True)

            # Find my rank
            my_rank = 1
            for i, fp in enumerate(friendly_priorities):
                if fp["friendly"]["id"] == unit["id"]:
                    my_rank = i + 1
                    break

            # Step 4 & 5: Calculate threat weight
            # Movement probability
            if my_rank == 1:
                move_prob = 1.0
            elif my_rank == 2:
                move_prob = 0.3
            else:
                move_prob = 0.1

            # Targeting probability
            if my_rank == 1:
                target_prob = 1.0
            elif my_rank == 2:
                target_prob = 0.5
            else:
                target_prob = 0.25

            threat_weight = move_prob * target_prob

            # Calculate enemy's expected damage against me
            expected_damage = self._calculate_expected_damage_against(enemy, unit, game_state)

            total_threat += expected_damage * threat_weight

        return total_threat

    def _get_enemy_reachable_positions(self, enemy: Dict[str, Any], game_state: Dict[str, Any]) -> List[Tuple[int, int]]:
        """
        Get all positions an enemy could reach after moving.
        Uses BFS like movement_build_valid_destinations_pool but simplified.

        PERFORMANCE: Results are cached per enemy ID in game_state["enemy_reachable_cache"].
        Cache is valid within a phase (enemies don't move during ally movement).
        Cache cleared in movement_phase_start when phase transitions.
        """
        from engine.phase_handlers.movement_handlers import _get_hex_neighbors, _is_traversable_hex

        # Check cache first - enemy reachable positions are static within a phase
        if "enemy_reachable_cache" in game_state:
            cache_key = enemy["id"]
            if cache_key in game_state["enemy_reachable_cache"]:
                return game_state["enemy_reachable_cache"][cache_key]

        if "MOVE" not in enemy:
            raise KeyError(f"Enemy missing required 'MOVE' field: {enemy}")
        move_range = enemy["MOVE"]
        start_pos = (enemy["col"], enemy["row"])

        # BFS to find reachable positions
        visited = {start_pos: 0}
        queue = [(start_pos, 0)]
        reachable = [start_pos]  # Include current position

        while queue:
            current_pos, current_dist = queue.pop(0)

            if current_dist >= move_range:
                continue

            neighbors = _get_hex_neighbors(current_pos[0], current_pos[1])

            for neighbor_col, neighbor_row in neighbors:
                neighbor_pos = (neighbor_col, neighbor_row)

                if neighbor_pos in visited:
                    continue

                # Simplified traversability check (ignore enemy adjacency rules for estimation)
                if not _is_traversable_hex(game_state, neighbor_col, neighbor_row, enemy):
                    continue

                visited[neighbor_pos] = current_dist + 1
                reachable.append(neighbor_pos)
                queue.append((neighbor_pos, current_dist + 1))

        # Store in cache for future lookups within this phase
        if "enemy_reachable_cache" not in game_state:
            game_state["enemy_reachable_cache"] = {}
        game_state["enemy_reachable_cache"][enemy["id"]] = reachable

        return reachable

    def _calculate_turns_to_kill(self, shooter: Dict[str, Any], target: Dict[str, Any],
                                  game_state: Dict[str, Any]) -> float:
        """Calculate how many turns (activations) it takes for shooter to kill target."""
        expected_damage = self._calculate_expected_damage_against(shooter, target, game_state)

        if expected_damage <= 0:
            return 100.0  # Can't kill

        return target["HP_CUR"] / expected_damage

    def _calculate_turns_to_kill_by_attacker(self, attacker: Dict[str, Any], defender: Dict[str, Any],
                                              game_state: Dict[str, Any]) -> float:
        """Calculate how many turns it takes for attacker to kill defender."""
        return self._calculate_turns_to_kill(attacker, defender, game_state)

    def _calculate_expected_damage_against(self, attacker: Dict[str, Any], defender: Dict[str, Any],
                                            game_state: Dict[str, Any]) -> float:
        """
        Calculate expected damage from attacker against defender in one activation.
        MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or best weapon

        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access - no defaults on unit stats.
        """
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or best weapon
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        from engine.ai.weapon_selector import get_best_weapon_for_target
        
        # Get best weapon for this defender
        best_weapon_idx, _ = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=True)
        if best_weapon_idx >= 0 and attacker.get("RNG_WEAPONS"):
            weapon = attacker["RNG_WEAPONS"][best_weapon_idx]
        else:
            # Fallback to selected weapon
            weapon = get_selected_ranged_weapon(attacker)
            if not weapon and attacker.get("RNG_WEAPONS"):
                weapon = attacker["RNG_WEAPONS"][0]  # Fallback to first weapon
            if not weapon:
                return 0.0
        
        num_attacks = weapon["NB"]
        if num_attacks == 0:
            return 0.0

        to_hit = weapon["ATK"]
        strength = weapon["STR"]
        ap = weapon["AP"]
        damage = weapon["DMG"]

        # Validate required defender stats
        if "T" not in defender:
            raise KeyError(f"Defender missing required 'T' field: {defender}")
        if "ARMOR_SAVE" not in defender:
            raise KeyError(f"Defender missing required 'ARMOR_SAVE' field: {defender}")
        toughness = defender["T"]
        armor_save = defender["ARMOR_SAVE"]
        # INVUL_SAVE defaults to 7 (no invul) which is legitimate game logic
        invul_save = defender.get("INVUL_SAVE", 7)  # 7+ = no invul (legitimate default)

        # Calculate probabilities
        p_hit = max(0.0, min(1.0, (7 - to_hit) / 6.0))

        wound_target = self._calculate_wound_target(strength, toughness)
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))

        # Save calculation (use better of armor or invul after AP modification)
        # AP is stored as negative (e.g., -1), subtract to worsen save: 3+ with -1 AP = 4+
        modified_armor = armor_save - ap
        best_save = min(modified_armor, invul_save)
        if best_save > 6:
            p_fail_save = 1.0
        else:
            p_fail_save = max(0.0, min(1.0, (best_save - 1) / 6.0))

        expected_damage = num_attacks * p_hit * p_wound * p_fail_save * damage
        return expected_damage

    def _calculate_wound_target(self, strength: int, toughness: int) -> int:
        """W40K wound chart."""
        if strength >= toughness * 2:
            return 2  # 2+
        elif strength > toughness:
            return 3  # 3+
        elif strength == toughness:
            return 4  # 4+
        elif strength * 2 <= toughness:
            return 6  # 6+
        else:
            return 5  # 5+