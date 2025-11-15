#!/usr/bin/env python3
"""
reward_calculator.py - Reward calculation system
"""

from typing import Dict, List, Any, Tuple, Optional
from engine.combat_utils import calculate_wound_target, calculate_hex_distance, has_line_of_sight
from engine.phase_handlers.shooting_handlers import _calculate_save_target
from engine.game_utils import get_unit_by_id

class RewardCalculator:
    """Calculates rewards for actions."""
    
    def __init__(self, config: Dict[str, Any], rewards_config: Dict[str, Any], unit_registry=None):
        self.config = config
        self.rewards_config = rewards_config
        self._reward_mapper = None
        self.quiet = config.get("quiet", True)
        self.unit_registry = unit_registry
    
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
        system_response_indicators = [
            "phase_complete", "phase_transition", "while_loop_active", 
            "context", "blinking_units", "start_blinking", "validTargets",
            "type", "next_phase", "current_player", "new_turn", "episode_complete",
            "unit_activated", "valid_destinations", "preview_data", "waiting_for_player"
        ]
        
        if any(indicator in result for indicator in system_response_indicators):
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
            
            for log in reversed(action_logs):
                # Stop if we hit a different turn
                if log.get("turn") != current_turn:
                    break
                
                # If it's a shoot action from the same shooter, categorize the reward
                if log.get("type") == "shoot" and log.get("shooterId") == shooter_id:
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
                        
                # Stop if we hit a different action type
                elif log.get("type") != "shoot":
                    break
            
            # Validate we found at least one shoot action
            if base_action_reward == 0.0 and result_bonus_reward == 0.0:
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
            tactical_context = self._build_tactical_context(acting_unit, result, game_state)
            movement_result = reward_mapper.get_movement_reward(enriched_unit, old_pos, new_pos, tactical_context)
            if isinstance(movement_result, tuple):
                movement_reward = movement_result[0]
                reward_breakdown['base_actions'] = movement_reward
                reward_breakdown['total'] = movement_reward

                if game_state.get("game_over", False):
                    situational_reward = self._get_situational_reward(game_state)
                    reward_breakdown['situational'] = situational_reward
                    movement_reward += situational_reward
                    reward_breakdown['total'] = movement_reward

                game_state['last_reward_breakdown'] = reward_breakdown
                return movement_reward
            reward_breakdown['base_actions'] = movement_result
            reward_breakdown['total'] = movement_result

            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                movement_result += situational_reward
                reward_breakdown['total'] = movement_result

            game_state['last_reward_breakdown'] = reward_breakdown
            return movement_result

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
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit)]
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
            
        elif action_type == "fight" and "targetId" in result:
            target = get_unit_by_id(str(result["targetId"]), game_state)
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit)]
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
            
            if winner == 1:  # AI wins
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
                
            elif winner == 0:  # AI loses
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
        """
        if not game_state.get("game_over", False):
            return 0.0
        
        # Get any AI unit to access reward config (all units share situational modifiers)
        acting_unit = None
        for unit in game_state["units"]:
            if unit["player"] == 1:  # AI player
                acting_unit = unit
                break
        
        if not acting_unit:
            return 0.0
        
        try:
            unit_rewards = self._get_unit_reward_config(acting_unit)
            if "situational_modifiers" not in unit_rewards:
                return 0.0
            
            modifiers = unit_rewards["situational_modifiers"]
            winner = self._determine_winner(game_state)
            
            if winner == 1:  # AI wins
                return modifiers.get("win", 0.0)
            elif winner == 0:  # AI loses
                return modifiers.get("lose", 0.0)
            elif winner == -1:  # Draw
                return modifiers.get("draw", 0.0)
            
            return 0.0
        except (KeyError, ValueError) as e:
            # Silently return 0 if reward config unavailable
            return 0.0
    
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
        
        # Load agent-specific FULL rewards config to access system_penalties
        config_loader = get_config_loader()
        full_rewards_config = config_loader.load_agent_rewards_config(controlled_agent)
        
        if "system_penalties" not in full_rewards_config:
            raise KeyError(
                f"Missing required 'system_penalties' section in {controlled_agent}_rewards_config.json. "
                "Required structure: {'system_penalties': {'forbidden_action': -1.0, 'invalid_action': -0.9, 'generic_error': -0.1, "
                "'system_response': 0.0}}"
            )
        return full_rewards_config["system_penalties"]
    
    # ============================================================================
    # TACTICAL CONTEXT
    # ============================================================================
    
    def _build_tactical_context(self, unit: Dict[str, Any], result: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
        """Build tactical context for reward mapper."""
        action_type = result.get("action")

        # CRITICAL FIX: Handle both 'move' and 'flee' actions (flee is a type of move)
        if action_type == "move" or action_type == "flee":
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
            
            # Handle same-position movement (no actual movement) - REMOVE DEBUG THAT TRIGGERS DOUBLE PROCESSING
            if old_col == new_col and old_row == new_row:
                # Unit didn't actually move - this should be treated as a wait action
                context = {"moved_to_safety": True}  # Conservative choice for no movement
            elif not any(context.values()):
                # If unit moved but no tactical benefit detected, default to moved_closer
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
        
        # Validate required UPPERCASE fields
        required_fields = ["RNG_NB", "RNG_ATK", "RNG_STR", "RNG_AP", "RNG_DMG",
                          "CC_NB", "CC_ATK", "CC_STR", "CC_AP", "CC_DMG"]
        for field in required_fields:
            if field not in unit:
                raise KeyError(f"Unit missing required '{field}' field: {unit}")
        
        # Calculate EXPECTED ranged damage per turn
        ranged_expected = self._calculate_expected_damage(
            num_attacks=unit["RNG_NB"],
            to_hit_stat=unit["RNG_ATK"],
            strength=unit["RNG_STR"],
            target_toughness=target_T,
            ap=unit["RNG_AP"],
            target_save=target_save,
            target_invul=target_invul,
            damage_per_wound=unit["RNG_DMG"]
        )
        
        # Calculate EXPECTED melee damage per turn
        melee_expected = self._calculate_expected_damage(
            num_attacks=unit["CC_NB"],
            to_hit_stat=unit["CC_ATK"],
            strength=unit["CC_STR"],
            target_toughness=target_T,
            ap=unit["CC_AP"],
            target_save=target_save,
            target_invul=target_invul,
            damage_per_wound=unit["CC_DMG"]
        )
        
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
        
        if current_phase == "shoot":
            if "RNG_ATK" not in shooter or "RNG_STR" not in shooter or "RNG_DMG" not in shooter:
                raise KeyError(f"Shooter missing required ranged stats: {shooter}")
            if "RNG_NB" not in shooter:
                raise KeyError(f"Shooter missing required 'RNG_NB' field: {shooter}")
            
            hit_target = shooter["RNG_ATK"]
            strength = shooter["RNG_STR"]
            damage = shooter["RNG_DMG"]
            num_attacks = shooter["RNG_NB"]
            ap = shooter.get("RNG_AP", 0)
        else:
            if "CC_ATK" not in shooter or "CC_STR" not in shooter or "CC_DMG" not in shooter:
                raise KeyError(f"Shooter missing required melee stats: {shooter}")
            if "CC_NB" not in shooter:
                raise KeyError(f"Shooter missing required 'CC_NB' field: {shooter}")
            
            hit_target = shooter["CC_ATK"]
            strength = shooter["CC_STR"]
            damage = shooter["CC_DMG"]
            num_attacks = shooter["CC_NB"]
            ap = shooter.get("CC_AP", 0)
        
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
        - Distance (can they reach?)
        - Hit/wound/save probabilities
        - Number of attacks
        - Damage output
        
        Returns: 0.0-1.0 probability
        """
        distance = calculate_hex_distance(
            defender["col"], defender["row"],
            attacker["col"], attacker["row"]
        )
        
        can_use_ranged = distance <= attacker.get("RNG_RNG", 0)
        can_use_melee = distance <= attacker.get("CC_RNG", 0)
        
        if not can_use_ranged and not can_use_melee:
            return 0.0
        
        if can_use_ranged and not can_use_melee:
            if "RNG_ATK" not in attacker or "RNG_STR" not in attacker:
                return 0.0
            
            hit_target = attacker["RNG_ATK"]
            strength = attacker["RNG_STR"]
            damage = attacker["RNG_DMG"]
            num_attacks = attacker.get("RNG_NB", 0)
            ap = attacker.get("RNG_AP", 0)
        else:
            if "CC_ATK" not in attacker or "CC_STR" not in attacker:
                return 0.0
            
            hit_target = attacker["CC_ATK"]
            strength = attacker["CC_STR"]
            damage = attacker["CC_DMG"]
            num_attacks = attacker.get("CC_NB", 0)
            ap = attacker.get("CC_AP", 0)
        
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
            unit_value = friendly.get("VALUE", 10.0)
            weighted_threat = danger * unit_value
            total_weighted_threat += weighted_threat
        
        all_weighted_threats = []
        for t in valid_targets:
            t_total = 0.0
            for friendly in friendly_units:
                danger = self._calculate_danger_probability(friendly, t, game_state)
                unit_value = friendly.get("VALUE", 10.0)
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
            
            target_hp = target.get("HP_MAX", 1)
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
        
        for enemy in enemies:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_RNG' field: {enemy}")
            
            # CRITICAL: Use same logic as observation encoding
            # Ranged unit = RNG_RNG > CC_RNG (matches offensive_type calculation)
            is_ranged_unit = enemy["RNG_RNG"] > enemy["CC_RNG"]
            
            if is_ranged_unit and enemy["RNG_RNG"] > 0:
                distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
                # Enemy in shooting range and has LoS?
                if distance <= enemy["RNG_RNG"]:
                    if has_line_of_sight(enemy, new_unit_state, game_state):
                        ranged_enemies_with_los += 1
        
        # Good cover from ranged = 0 or 1 ranged enemy can see you
        return ranged_enemies_with_los <= 1
    
    def _moved_closer_to_enemies(self, unit: Dict[str, Any], old_pos: Tuple[int, int], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved closer to enemies."""
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if not enemies:
            return False
        
        old_min_distance = min(abs(old_pos[0] - e["col"]) + abs(old_pos[1] - e["row"]) for e in enemies)
        new_min_distance = min(abs(new_pos[0] - e["col"]) + abs(new_pos[1] - e["row"]) for e in enemies)
        
        return new_min_distance < old_min_distance
    
    def _moved_away_from_enemies(self, unit: Dict[str, Any], old_pos: Tuple[int, int], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved away from enemies."""
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if not enemies:
            return False
        
        old_min_distance = min(abs(old_pos[0] - e["col"]) + abs(old_pos[1] - e["row"]) for e in enemies)
        new_min_distance = min(abs(new_pos[0] - e["col"]) + abs(new_pos[1] - e["row"]) for e in enemies)
        
        return new_min_distance > old_min_distance
    
    def _moved_to_optimal_range(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved to optimal shooting range per W40K shooting rules."""
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        if unit["RNG_RNG"] <= 0:
            return False
        
        max_range = unit["RNG_RNG"]
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
        min_range = unit["CC_RNG"]  # Minimum engagement distance
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        for enemy in enemies:
            distance = abs(new_pos[0] - enemy["col"]) + abs(new_pos[1] - enemy["row"])
            # Optimal range: can shoot but not in melee (min_range < distance <= max_range)
            if min_range < distance <= max_range:
                return True
        
        return False
    
    def _moved_to_charge_range(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved to charge range of enemies."""
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "CC_DMG" not in unit:
            raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
        if unit["CC_DMG"] <= 0:
            return False
        
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if "MOVE" not in unit:
            raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
        max_charge_range = unit["MOVE"] + 12  # Average 2d6 charge distance
        
        for enemy in enemies:
            distance = abs(new_pos[0] - enemy["col"]) + abs(new_pos[1] - enemy["row"])
            if distance <= max_charge_range:
                return True
        
        return False
    
    def _moved_to_safety(self, unit: Dict[str, Any], new_pos: Tuple[int, int], game_state: Dict[str, Any]) -> bool:
        """Check if unit moved to safety from enemy threats."""
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        for enemy in enemies:
            # Check if moved out of enemy threat range
            distance = abs(new_pos[0] - enemy["col"]) + abs(new_pos[1] - enemy["row"])
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy unit missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy unit missing required 'CC_RNG' field: {enemy}")
            enemy_threat_range = max(enemy["RNG_RNG"], enemy["CC_RNG"])
            
            if distance > enemy_threat_range:
                return True
        
        return False
    
    def _gained_los_on_priority_target(self, unit: Dict[str, Any], old_pos: Tuple[int, int], game_state: Dict[str, Any], 
                                       new_pos: Tuple[int, int]) -> bool:
        """Check if unit gained LoS on its highest-priority target."""
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        if unit["RNG_RNG"] <= 0:
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
                if distance <= unit["RNG_RNG"]:
                    enemies_in_range.append(enemy)
        
        if not enemies_in_range:
            return False
        
        # Find priority target (lowest HP for RangedSwarm units)
        priority_target = min(enemies_in_range, key=lambda e: e.get("HP_CUR", 999))
        
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
        """Check if unit is safe from enemy MELEE charges (ranged proximity irrelevant)."""
        enemies = [u for u in game_state["units"] 
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        for enemy in enemies:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_RNG' field: {enemy}")
            if "MOVE" not in enemy:
                raise KeyError(f"Enemy missing required 'MOVE' field: {enemy}")
            if "CC_DMG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_DMG' field: {enemy}")
            
            # CRITICAL: Use same logic as observation encoding
            # Melee unit = RNG_RNG <= CC_RNG (opposite of ranged)
            is_melee_unit = enemy["RNG_RNG"] <= enemy["CC_RNG"]
            
            if is_melee_unit and enemy["CC_DMG"] > 0:
                distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
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
        
        for enemy in enemies:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_RNG' field: {enemy}")
            
            # Only consider ranged units (matches observation encoding)
            is_ranged_unit = enemy["RNG_RNG"] > enemy["CC_RNG"]
            
            if is_ranged_unit and enemy["RNG_RNG"] > 0:
                total_ranged_enemies += 1
                distance = calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
                # Safe if beyond their shooting range
                if distance > enemy["RNG_RNG"]:
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
        """Determine winner based on remaining living units or turn limit. Returns -1 for draw."""
        living_units_by_player = {}
        
        for unit in game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1
        
        # Check if game ended due to turn limit
        training_config = self.config.get("training_config", {})
        max_turns = training_config.get("max_turns_per_episode")
        current_turn = game_state["turn"]
        
        if max_turns and current_turn > max_turns:
            # Turn limit reached - determine winner by remaining units
            living_players = list(living_units_by_player.keys())
            if len(living_players) == 1:
                return living_players[0]
            elif len(living_players) == 2:
                # Both players have units - compare counts
                if living_units_by_player[0] > living_units_by_player[1]:
                    return 0
                elif living_units_by_player[1] > living_units_by_player[0]:
                    return 1
                else:
                    return -1  # Draw - equal units
            else:
                return -1  # Draw - no units or other scenario
        
        # Normal elimination rules
        living_players = list(living_units_by_player.keys())
        if len(living_players) == 1:
            return living_players[0]
        elif len(living_players) == 0:
            return -1  # Draw/no winner
        else:
            return None  # Game still ongoing
    
    def _get_reward_mapper_unit_rewards(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Get unit-specific rewards config for reward_mapper."""
        enriched_unit = self._enrich_unit_for_reward_mapper(unit)
        reward_mapper = self._get_reward_mapper()
        return reward_mapper._get_unit_rewards(enriched_unit)
    
    def _enrich_unit_for_reward_mapper(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich unit data with tactical flags required by reward_mapper."""
        enriched = unit.copy()
        
        # AI_TURN.md COMPLIANCE: NO FALLBACKS - proper error handling        
        if self.config and self.config.get("controlled_agent"):
            agent_key = self.config["controlled_agent"]
        elif hasattr(self, 'unit_registry') and self.unit_registry:
            # AI_TURN.md: Direct access - NO DEFAULTS allowed
            if "unitType" not in unit:
                raise KeyError(f"Unit missing required 'unitType' field: {unit}")
            scenario_unit_type = unit["unitType"]
            # Let unit_registry.get_model_key() raise ValueError if unit type not found
            agent_key = self.unit_registry.get_model_key(scenario_unit_type)
        else:
            raise ValueError("Missing both controlled_agent config and unit_registry - cannot determine agent key")
        
        # CRITICAL: Set the agent type as unitType for reward config lookup
        enriched["unitType"] = agent_key
        
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access - NO DEFAULTS
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
        
        # Add required tactical flags based on unit stats
        enriched["is_ranged"] = unit["RNG_RNG"] > unit["CC_RNG"]
        enriched["is_melee"] = not enriched["is_ranged"]
        
        # AI_TURN.md COMPLIANCE: Direct field access for required fields
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        if "RNG_DMG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_DMG' field: {unit}")
        if "CC_DMG" not in unit:
            raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
        
        # Map UPPERCASE fields to lowercase for reward_mapper compatibility
        enriched["name"] = unit["unitType"]
        enriched["rng_dmg"] = unit["RNG_DMG"]
        enriched["cc_dmg"] = unit["CC_DMG"]
        
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