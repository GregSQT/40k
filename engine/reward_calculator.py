#!/usr/bin/env python3
"""
reward_calculator.py - Reward calculation system
"""

from typing import Dict, List, Any, Tuple, Optional
from engine.combat_utils import (
    calculate_wound_target,
    calculate_hex_distance,
    calculate_pathfinding_distance,
    expected_dice_value,
)
from engine.phase_handlers.shooting_handlers import _calculate_save_target
from engine.phase_handlers.shared_utils import (
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
)
from engine.game_utils import get_unit_by_id
from shared.data_validation import require_key

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
            "context", "blinking_units", "start_blinking", "valid_targets",
            "type", "next_phase", "current_player", "new_turn", "episode_complete",
            "unit_activated", "valid_destinations", "preview_data", "waiting_for_player",
            "reason"  # System responses like "pool_empty" don't have unitId
        ]

        # CRITICAL FIX: Check if this is actually an action result with phase transition attached
        # If result has 'action' field with move/shoot/etc, it's an action - NOT a system response
        # Position data (fromCol/toCol) confirms it's a completed action, not just a prompt
        is_action_result = result.get("action") in ["move", "shoot", "wait", "flee", "charge", "charge_fail", "fight"]
        has_position_data = any(ind in result for ind in ["fromCol", "toCol", "fromRow", "toRow"])

        matching_indicators = [ind for ind in system_response_indicators if ind in result]
        # CRITICAL: Explicitly handle system responses with "reason" field (e.g., "pool_empty")
        is_system_response = (
            matching_indicators and not (is_action_result or has_position_data)
        ) or result.get("reason") == "pool_empty"
        
        if is_system_response:
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
        
        # CRITICAL: No fallbacks - require explicit unitId in result
        acting_unit_id = result.get("unitId")
        if acting_unit_id is None:
            # Try alternative field names, but raise error if all missing
            acting_unit_id = result.get("shooterId")
            if acting_unit_id is None:
                acting_unit_id = result.get("unit_id")
                if acting_unit_id is None:
                    raise ValueError(f"Action result missing acting unit ID (checked unitId, shooterId, unit_id): {result}")
        
        acting_unit = get_unit_by_id(str(acting_unit_id), game_state)
        if not acting_unit:
            raise ValueError(f"Acting unit not found: {acting_unit_id}")

        objective_turn_reward = self._calculate_objective_reward_per_turn(game_state, result)
        if objective_turn_reward:
            reward_breakdown['tactical_bonuses'] += objective_turn_reward

        # CRITICAL: Only give rewards to the controlled player (P1 during training)
        # Player 2's actions are part of the environment, not the learning agent
        controlled_player = self.config.get("controlled_player", 1)
        if require_key(acting_unit, "player") != controlled_player:
            # No action rewards for opponent, BUT check if game ended
            # If P1's action ended the game, P0 still needs the win/lose reward!
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                reward_breakdown['total'] = situational_reward
                game_state['last_reward_breakdown'] = reward_breakdown
                return situational_reward

            # Game not over - no reward for opponent's actions
            reward_breakdown['total'] = objective_turn_reward
            game_state['last_reward_breakdown'] = reward_breakdown
            return reward_breakdown['total']

        # CRITICAL: No fallbacks - require explicit action in result
        if not isinstance(result, dict):
            raise TypeError(f"result must be a dict, got {type(result).__name__}")
        
        action_type = result.get("action")
        if action_type is None:
            # Try alternative field name, but raise error if missing
            end_type = result.get("endType")
            if end_type is not None:
                action_type = end_type.lower()
            else:
                raise ValueError(f"Action result missing 'action' field (checked action, endType): {result}")
        # If action_type is not None, use it as-is (no else block needed)

        # Full reward mapper integration
        reward_mapper = self._get_reward_mapper()
        enriched_unit = self._enrich_unit_for_reward_mapper(acting_unit)
        
        if action_type == "shoot":
            # CRITICAL: Check if this is a waiting_for_player action without attacks executed
            # In this case, no logs are added yet, so return 0.0 reward
            waiting_for_player = result.get("waiting_for_player", False)
            all_attack_results = result["all_attack_results"] if "all_attack_results" in result else []
            if waiting_for_player and not all_attack_results:
                # No attacks executed yet, return 0.0 reward
                reward_breakdown['total'] = 0.0
                game_state['last_reward_breakdown'] = reward_breakdown
                return 0.0
            
            # Sum all shoot rewards from current activation (handles RNG_NB > 1)
            action_logs = require_key(game_state, "action_logs")
            
            # Validate action_logs exists and is not empty
            if not action_logs or len(action_logs) == 0:
                raise RuntimeError(
                    f"CRITICAL: action_logs is empty for shoot action! "
                    f"Unit {acting_unit.get('id')}, Player {acting_unit.get('player')}"
                )
            
            # Find all shoot logs from the most recent activation
            # Work backwards until we hit a different action type or different shooter
            current_turn = require_key(game_state, "turn")
            shooter_id = acting_unit.get("id")
            # CRITICAL: Normalize shooter_id to string for comparison (logs use string unit_id)
            shooter_id_str = str(shooter_id) if shooter_id is not None else None
            
            # Track rewards by category using action_name field
            base_action_reward = 0.0
            result_bonus_reward = 0.0
            logs_found = 0  # Track if we actually found any logs

            for log in reversed(action_logs):
                # Stop if we hit a different turn
                if log.get("turn") != current_turn:
                    break

                # If it's a shoot action from the same shooter, categorize the reward
                # CRITICAL: Normalize log shooterId to string for comparison
                log_shooter_id = str(log.get("shooterId")) if log.get("shooterId") is not None else None
                if log.get("type") == "shoot" and log_shooter_id == shooter_id_str:
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
                # CRITICAL: Normalize for comparison (same as line 172)
                elif log.get("type") == "shoot":
                    log_shooter_id_check = str(log.get("shooterId")) if log.get("shooterId") is not None else None
                    if log_shooter_id_check != shooter_id_str:
                        break
            
            # Validate we found at least one shoot action LOG (not just non-zero rewards)
            if logs_found == 0:
                # No logs found - this can happen if:
                # 1. waiting_for_player=True without all_attack_results (already handled above)
                # 2. Logs not yet added (timing issue)
                # 3. Logs added with different turn
                # 4. Phase transition or other edge cases
                # Return 0.0 reward instead of raising error to handle all cases gracefully
                reward_breakdown['base_actions'] = 0.0
                reward_breakdown['result_bonuses'] = 0.0
                reward_breakdown['total'] = 0.0
                game_state['last_reward_breakdown'] = reward_breakdown
                return 0.0
            
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
            
        elif action_type == "deploy_unit":
            deploy_reward = 0.0
            reward_breakdown['base_actions'] = deploy_reward
            reward_breakdown['total'] = deploy_reward

            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                deploy_reward += situational_reward
                reward_breakdown['total'] = deploy_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return deploy_reward

        elif action_type == "move" or action_type == "flee":
            # Movement rewards removed (unused) - keep behavior deterministic
            movement_reward = 0.0
            reward_breakdown['base_actions'] = movement_reward
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
            if not target:
                raise ValueError(f"Charge target not found: {result['targetId']}")
            # No target can die in charge phase
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit, game_state)]
            charge_reward = reward_mapper.get_charge_priority_reward(enriched_unit, enriched_target, all_targets, game_state)
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
            if not target:
                raise ValueError(f"Fight target not found: {result['targetId']}")
            # units_cache = living only; target may be dead (removed). Reward_mapper uses get_hp_from_cache → 0 if not in cache.
            enriched_target = self._enrich_unit_for_reward_mapper(target) if is_unit_alive(str(target["id"]), game_state) else target
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit, game_state)]
            fight_reward = reward_mapper.get_combat_priority_reward(enriched_unit, enriched_target, all_targets, game_state)
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
            current_phase = require_key(game_state, "phase")
            if current_phase == "move":
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "move_wait"}, success, game_state)
            else:
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "wait"}, success, game_state)
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
            # Advance movement rewards removed (unused) - keep behavior deterministic
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
                if "wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'wait' reward")
                base_reward = base_actions["wait"]
        elif action_type == "move":
            base_reward = 0.0
        elif action_type == "skip":
            base_reward = 0.0
        elif action_type == "move_wait":
            base_reward = 0.0
        elif action_type == "wait":
            if "wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'wait' reward")
            base_reward = base_actions["wait"]
        else:
            base_reward = 0.0
        
        # Add win/lose bonuses from situational_modifiers
        if game_state["game_over"]:
            # AI_TURN.md COMPLIANCE: Direct access with validation
            if "situational_modifiers" not in unit_rewards:
                raise KeyError("Unit rewards missing required 'situational_modifiers' section")
            modifiers = unit_rewards["situational_modifiers"]
            winner = self._determine_winner(game_state)

            # Player 1 is always the controlled player during training
            if winner == 1:  # Player 1 wins
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

            elif winner == 2:  # Player 2 wins (controlled player loses)
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
            agent_key = require_key(self.config, "controlled_agent")

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
        # CRITICAL FIX: Learning agent is Player 1, not Player 2!
        acting_unit = None
        units_cache = require_key(game_state, "units_cache")
        for unit_id, cache_entry in units_cache.items():
            if cache_entry["player"] == 1:  # Learning agent is Player 1
                acting_unit = get_unit_by_id(unit_id, game_state)
                if not acting_unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
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

                # CRITICAL FIX: Learning agent is Player 1!
                # winner == 1 means Player 1 (learning agent) wins
                # winner == 2 means Player 2 (opponent) wins, so learning agent loses
                if winner == 1:  # Learning agent wins
                    base_reward = modifiers.get("win", 0.0)
                elif winner == 2:  # Learning agent loses
                    base_reward = modifiers.get("lose", 0.0)
                elif winner == -1:  # Draw
                    base_reward = modifiers.get("draw", 0.0)

            # Add objective control reward at end of turn 5
            # CRITICAL: Calculate objective reward even if situational_modifiers is missing
            objective_reward = self._calculate_objective_reward_turn5(game_state, unit_rewards)
            
            # Diagnostic logging (only if not quiet)
            if not self.quiet and objective_reward > 0:
                current_turn = require_key(game_state, "turn")
                obj_counts = self.state_manager.count_controlled_objectives(game_state) if self.state_manager else {}
                p0_count = obj_counts[0] if 0 in obj_counts else 0
                print(f"🎯 OBJECTIVE REWARD: Turn={current_turn}, P0 objectives={p0_count}, Reward={objective_reward:.1f}")
            
            return base_reward + objective_reward
        except (KeyError, ValueError) as e:
            # Log error but return 0 to avoid breaking training
            if not self.quiet:
                print(f"⚠️  WARNING: Failed to calculate situational reward: {e}")
            return 0.0
    
    def _get_primary_objective_config(self, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return primary objective config if present, else None."""
        primary_objective = game_state.get("primary_objective")
        if primary_objective is None:
            return None
        if isinstance(primary_objective, list):
            if len(primary_objective) != 1:
                raise ValueError("primary_objective must contain exactly one config for rewards")
            primary_objective = primary_objective[0]
        if not isinstance(primary_objective, dict):
            raise TypeError(f"primary_objective is {type(primary_objective).__name__}, expected dict")
        return primary_objective

    def _get_controlled_player_unit(self, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return one unit for the controlled player (if any)."""
        controlled_player = self.config.get("controlled_player", 1)
        units_cache = require_key(game_state, "units_cache")
        for unit_id, cache_entry in units_cache.items():
            if int(cache_entry["player"]) == int(controlled_player):
                unit = get_unit_by_id(str(unit_id), game_state)
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                return unit
        return None

    def _calculate_objective_reward_per_turn(self, game_state: Dict[str, Any], result: Dict[str, Any]) -> float:
        """
        Reward controlled player based on objectives controlled at turn start.
        Applied once per turn when transitioning into move phase.
        """
        if not result.get("phase_transition") or result.get("next_phase") != "move":
            return 0.0

        primary_objective = self._get_primary_objective_config(game_state)
        if primary_objective is None:
            return 0.0

        scoring_cfg = require_key(primary_objective, "scoring")
        start_turn = require_key(scoring_cfg, "start_turn")
        current_turn = require_key(game_state, "turn")
        if current_turn < start_turn:
            return 0.0

        objective_rewarded_turns = require_key(game_state, "objective_rewarded_turns")
        controlled_player = int(self.config.get("controlled_player", 1))
        reward_key = (current_turn, controlled_player)
        if reward_key in objective_rewarded_turns:
            return 0.0

        if not self.state_manager:
            return 0.0

        acting_unit = self._get_controlled_player_unit(game_state)
        if not acting_unit:
            return 0.0

        unit_rewards = self._get_unit_reward_config(acting_unit)
        if "objective_rewards" not in unit_rewards:
            raise KeyError("Unit rewards missing required 'objective_rewards' section")
        objective_rewards = unit_rewards["objective_rewards"]
        if "reward_per_objective" not in objective_rewards:
            raise KeyError("Objective rewards missing required 'reward_per_objective' value")

        obj_counts = self.state_manager.count_controlled_objectives(game_state)
        controlled_objectives = require_key(obj_counts, controlled_player)
        reward_per_objective = objective_rewards["reward_per_objective"]
        total_reward = reward_per_objective * controlled_objectives

        if "use_objective_lead" in objective_rewards and objective_rewards["use_objective_lead"] is True:
            if "reward_for_objective_lead" not in objective_rewards:
                raise KeyError("Objective rewards missing required 'reward_for_objective_lead' value")
            opponent_player = 2 if int(controlled_player) == 1 else 1
            opponent_objectives = require_key(obj_counts, opponent_player)
            lead = controlled_objectives - opponent_objectives
            total_reward += float(objective_rewards["reward_for_objective_lead"]) * lead

        objective_rewarded_turns.add(reward_key)

        return total_reward

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
        current_turn = require_key(game_state, "turn")
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
        units_cache = require_key(game_state, "units_cache")
        for _unit_id, cache_entry in units_cache.items():
            player = cache_entry["player"]
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
        controlled_player = int(self.config.get("controlled_player", 1))
        controlled_objectives = require_key(obj_counts, controlled_player)
        
        # Get reward per objective from config (REQUIRED - raise error if missing)
        if "objective_rewards" not in unit_rewards:
            raise KeyError(f"Unit rewards missing required 'objective_rewards' section")
        
        objective_rewards = unit_rewards["objective_rewards"]
        if "reward_per_objective_turn5" not in objective_rewards:
            raise KeyError(f"Objective rewards missing required 'reward_per_objective_turn5' value")
        
        reward_per_objective = objective_rewards["reward_per_objective_turn5"]
        
        total_reward = reward_per_objective * controlled_objectives
        
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
        
        # Calculate max EXPECTED ranged damage from all ranged weapons
        ranged_expected_list = []
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        for weapon in rng_weapons:
            expected = self._calculate_expected_damage(
                num_attacks=expected_dice_value(require_key(weapon, "NB"), "combat_mix_rng_nb"),
                to_hit_stat=require_key(weapon, "ATK"),
                strength=require_key(weapon, "STR"),
                target_toughness=target_T,
                ap=require_key(weapon, "AP"),
                target_save=target_save,
                target_invul=target_invul,
                damage_per_wound=expected_dice_value(require_key(weapon, "DMG"), "combat_mix_rng_dmg")
            )
            ranged_expected_list.append(expected)
        
        ranged_expected = max(ranged_expected_list) if ranged_expected_list else 0.0
        
        # Calculate max EXPECTED melee damage from all melee weapons
        melee_expected_list = []
        cc_weapons = unit["CC_WEAPONS"] if "CC_WEAPONS" in unit else []
        for weapon in cc_weapons:
            expected = self._calculate_expected_damage(
                num_attacks=expected_dice_value(require_key(weapon, "NB"), "combat_mix_cc_nb"),
                to_hit_stat=require_key(weapon, "ATK"),
                strength=require_key(weapon, "STR"),
                target_toughness=target_T,
                ap=require_key(weapon, "AP"),
                target_save=target_save,
                target_invul=target_invul,
                damage_per_wound=expected_dice_value(require_key(weapon, "DMG"), "combat_mix_cc_dmg")
            )
            melee_expected_list.append(expected)
        
        melee_expected = max(melee_expected_list) if melee_expected_list else 0.0
        
        total_expected = ranged_expected + melee_expected
        
        if total_expected == 0:
            return 0.5  # Neutral (no combat power)
        
        # Scale to 0.1-0.9 range
        raw_ratio = ranged_expected / total_expected
        return 0.1 + (raw_ratio * 0.8)
    
    def _calculate_expected_damage(self, num_attacks: float, to_hit_stat: int,
                                   strength: int, target_toughness: int, ap: int,
                                   target_save: int, target_invul: int,
                                   damage_per_wound: float) -> float:
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
                weapon = get_selected_ranged_weapon(shooter)
                if not weapon:
                    raise ValueError(f"No selected ranged weapon for shooter {shooter.get('id')}")
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = expected_dice_value(require_key(weapon, "DMG"), "kill_prob_rng_dmg")
            num_attacks = expected_dice_value(require_key(weapon, "NB"), "kill_prob_rng_nb")
            ap = weapon["AP"]
        else:
            # Get best weapon for this target
            best_weapon_idx, _ = get_best_weapon_for_target(shooter, target, game_state, is_ranged=False)
            if best_weapon_idx >= 0 and shooter.get("CC_WEAPONS"):
                weapon = shooter["CC_WEAPONS"][best_weapon_idx]
            else:
                weapon = get_selected_melee_weapon(shooter)
                if not weapon:
                    raise ValueError(f"No selected melee weapon for shooter {shooter.get('id')}")
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = expected_dice_value(require_key(weapon, "DMG"), "kill_prob_cc_dmg")
            num_attacks = expected_dice_value(require_key(weapon, "NB"), "kill_prob_cc_nb")
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
        
        target_hp = require_hp_from_cache(str(target["id"]), game_state)
        if expected_damage >= target_hp:
            return 1.0
        else:
            return min(1.0, expected_damage / target_hp)
    
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
        defender_col, defender_row = require_unit_position(defender, game_state)
        attacker_col, attacker_row = require_unit_position(attacker, game_state)
        distance = calculate_pathfinding_distance(
            defender_col, defender_row,
            attacker_col, attacker_row,
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
                from engine.utils.weapon_helpers import get_selected_ranged_weapon
                weapon = get_selected_ranged_weapon(attacker)
                if not weapon:
                    raise ValueError(f"No selected ranged weapon for attacker {attacker.get('id')}")
        elif can_use_melee and not can_use_ranged:
            # Only melee available
            best_weapon_idx, _ = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=False)
            if best_weapon_idx >= 0 and attacker.get("CC_WEAPONS"):
                weapon = attacker["CC_WEAPONS"][best_weapon_idx]
            else:
                from engine.utils.weapon_helpers import get_selected_melee_weapon
                weapon = get_selected_melee_weapon(attacker)
                if not weapon:
                    raise ValueError(f"No selected melee weapon for attacker {attacker.get('id')}")
        else:
            # Both available - choose best overall
            best_rng_idx, rng_kill_prob = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=True)
            best_cc_idx, cc_kill_prob = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=False)
            
            if rng_kill_prob >= cc_kill_prob and best_rng_idx >= 0 and attacker.get("RNG_WEAPONS"):
                weapon = attacker["RNG_WEAPONS"][best_rng_idx]
            elif best_cc_idx >= 0 and attacker.get("CC_WEAPONS"):
                weapon = attacker["CC_WEAPONS"][best_cc_idx]
            else:
                from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
                weapon = get_selected_ranged_weapon(attacker) or get_selected_melee_weapon(attacker)
                if not weapon:
                    raise ValueError(f"No selected weapon for attacker {attacker.get('id')}")
        
        hit_target = require_key(weapon, "ATK")
        strength = require_key(weapon, "STR")
        damage = expected_dice_value(require_key(weapon, "DMG"), "danger_dmg")
        num_attacks = expected_dice_value(require_key(weapon, "NB"), "danger_nb")
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
        
        defender_hp = require_hp_from_cache(str(defender["id"]), game_state)
        if expected_damage >= defender_hp:
            return 1.0
        else:
            return min(1.0, expected_damage / defender_hp)
    
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
        units_cache = require_key(game_state, "units_cache")
        friendly_units = []
        for unit_id, cache_entry in units_cache.items():
            if cache_entry["player"] == my_player:
                unit = get_unit_by_id(unit_id, game_state)
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                friendly_units.append(unit)
        
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
            
            unit_type = require_key(active_unit, "unitType")
            
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
            
        except Exception as e:
            import logging
            logging.error(f"reward_calculator._get_target_type_preference failed: {str(e)} - returning neutral reward 0.5")
            return 0.5
    
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
        
        # Legacy winner logic (should not happen in normal usage)
        # This path ignores objectives
        living_units_by_player = {}
        units_cache = require_key(game_state, "units_cache")
        for _unit_id, cache_entry in units_cache.items():
            player = cache_entry["player"]
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
        if not self.config:
            raise ValueError("Missing config - cannot determine controlled_agent for reward mapper")
        agent_key = require_key(self.config, "controlled_agent")

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
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        cc_weapons = require_key(unit, "CC_WEAPONS")
        
        rng_dmg = max(
            (expected_dice_value(require_key(w, "DMG"), "enrich_rng_dmg") for w in rng_weapons),
            default=0.0,
        )
        cc_dmg = max(
            (expected_dice_value(require_key(w, "DMG"), "enrich_cc_dmg") for w in cc_weapons),
            default=0.0,
        )
        
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
        acting_player = require_key(acting_unit, "player")
        units_cache = require_key(game_state, "units_cache")

        for unit_id, cache_entry in units_cache.items():
            if cache_entry["player"] != acting_player:
                unit = get_unit_by_id(unit_id, game_state)
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                targets.append(unit)

        return targets

    def _calculate_turns_to_kill(self, shooter: Dict[str, Any], target: Dict[str, Any],
                                  game_state: Dict[str, Any]) -> float:
        """Calculate how many turns (activations) it takes for shooter to kill target."""
        expected_damage = self._calculate_expected_damage_against(shooter, target, game_state)

        if expected_damage <= 0:
            return 100.0  # Can't kill

        target_hp = require_hp_from_cache(str(target["id"]), game_state)
        return target_hp / expected_damage

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
            weapon = get_selected_ranged_weapon(attacker)
            if not weapon:
                raise ValueError(f"No selected ranged weapon for attacker {attacker.get('id')}")
        
        num_attacks = expected_dice_value(require_key(weapon, "NB"), "expected_damage_nb")
        if num_attacks == 0:
            return 0.0

        to_hit = weapon["ATK"]
        strength = weapon["STR"]
        ap = weapon["AP"]
        damage = expected_dice_value(require_key(weapon, "DMG"), "expected_damage_dmg")

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