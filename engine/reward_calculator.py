#!/usr/bin/env python3
"""
reward_calculator.py - Reward calculation system
"""

from typing import Dict, List, Any, Optional
from engine.macro_intents import INTENT_DEFEND, INTENT_INVADE, get_objective_control
from engine.combat_utils import expected_dice_value
from engine.phase_handlers.shared_utils import is_unit_alive
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
        
        # DÉCISION AGENT (V11 §9.3 P2) — aucun reward propre, et c'est EXPLICITE.
        # Le crédit d'un choix vient de ses CONSÉQUENCES (la value function les propage), pas
        # d'un bonus attaché à l'acte de choisir : §9.6 interdit d'ajouter du reward shaping en
        # silence, et une prime au choix pousserait l'agent vers les décisions plutôt que vers
        # leurs effets. ⚠️ Sans cette branche, la neutralité n'était obtenue que par ACCIDENT :
        # le payload contient `waiting_for_player`, donc il tombait dans `is_system_response`
        # ci-dessous. Retirer cette clé du payload l'aurait basculé dans le chemin « unité
        # agissante » — reward d'unité arbitraire, ou `ValueError` si l'unité manquait.
        # La valeur est 0.0 EN DUR, et non `system_penalties['system_response']` : une décision
        # n'est pas une réponse système, et un futur tuning de cette clé rendrait les décisions
        # coûteuses ou payantes sans que personne ne l'ait décidé. Toute prime ou pénalité au
        # choix doit être un ajout DÉLIBÉRÉ, par tranche (§9.6).
        if isinstance(result, dict) and result.get("action") in (
            "agent_decision", "waiting_for_agent_decision",
        ):
            reward_breakdown['total'] = 0.0
            game_state['last_reward_breakdown'] = reward_breakdown
            return 0.0

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
        is_action_result = result.get("action") in [
            "move", "shoot", "wait", "flee", "charge", "charge_fail", "fight",
            "squad_normal_move", "squad_advance", "squad_fall_back", "squad_wait",
            "squad_shoot", "squad_charge", "squad_fight",
        ]
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
        # Penalite coherency fin de tour (squad_shaping). Fusionnee dans
        # objective_turn_reward pour etre propagee par tous les chemins de retour.
        coherency_penalty = self._calculate_coherency_penalty_per_turn(game_state, result)
        if coherency_penalty:
            reward_breakdown['penalties'] += coherency_penalty
            objective_turn_reward += coherency_penalty

        # CRITICAL: Only give rewards to the controlled player.
        # The opponent's actions are part of the environment, not the learning agent.
        controlled_player = require_key(self.config, "controlled_player")
        if require_key(acting_unit, "player") != controlled_player:
            # Symetrie alliee : un tir/combat adverse qui detruit nos figurines
            # genere un signal negatif dense (proportionnel aux points). Le wrapper
            # BotControlledEnv accumule ce reward dans le step de l agent (credit
            # assignment correct). Miroir exact du path offensif squad.
            defensive_penalty = 0.0
            opp_action = result.get("action")
            if opp_action in ("squad_shoot", "squad_fight"):
                res_key = "shoot_result" if opp_action == "squad_shoot" else "fight_result"
                combat = require_key(result, res_key)
                shaping = require_key(self._get_unit_reward_config(acting_unit), "squad_shaping")
                defensive_penalty = -self._squad_combat_shaping(
                    combat, lambda p: p == controlled_player, shaping
                )
            reward_breakdown['penalties'] += defensive_penalty

            # If the opponent ends the game, the controlled player still needs
            # the terminal win/lose/draw situational reward.
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                reward_breakdown['total'] = situational_reward + defensive_penalty
                game_state['last_reward_breakdown'] = reward_breakdown
                return reward_breakdown['total']

            # Game not over : seul le signal defensif (+ objectif) revient a l agent.
            reward_breakdown['total'] = objective_turn_reward + defensive_penalty
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
            # CRITICAL: Check if no attacks were executed (waiting_for_player or end activation without firing)
            # In these cases, no logs are added, so return 0.0 reward
            waiting_for_player = result.get("waiting_for_player", False)
            all_attack_results = result["all_attack_results"] if "all_attack_results" in result else []
            if waiting_for_player and not all_attack_results:
                # No attacks executed yet (waiting for target selection), return 0.0 reward
                reward_breakdown['total'] = 0.0
                game_state['last_reward_breakdown'] = reward_breakdown
                return 0.0
            if not all_attack_results:
                # End activation without firing (e.g. no valid targets, no weapons) - no logs
                reward_breakdown['total'] = 0.0
                game_state['last_reward_breakdown'] = reward_breakdown
                return 0.0
            
            # Sum all shoot rewards from current activation (handles RNG_NB > 1)
            action_logs = require_key(game_state, "action_logs")
            
            # Validate action_logs exists and is not empty (attacks were executed, logs must exist)
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
            calculated_reward = base_action_reward + result_bonus_reward + objective_turn_reward

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
            deploy_reward = 0.0 + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
            reward_breakdown['total'] = deploy_reward

            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                deploy_reward += situational_reward
                reward_breakdown['total'] = deploy_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return deploy_reward

        elif action_type == "move" or action_type == "flee":
            on_obj_reward = self._calculate_on_objective_reward(game_state, result)
            movement_reward = on_obj_reward + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
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
            skip_reward = 0.0 + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
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
            charge_reward = reward_mapper.get_charge_priority_reward(enriched_unit, enriched_target, all_targets, game_state) + objective_turn_reward
            reward_breakdown['base_actions'] = charge_reward - objective_turn_reward
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
            # on_objective_bonus for consolidation (toCol/toRow in result) and pile-in (_pile_in_toCol/Row in game_state)
            pile_in_col = game_state.pop("_pile_in_toCol", None)
            pile_in_row = game_state.pop("_pile_in_toRow", None)
            on_obj_reward = 0.0
            if result.get("toCol") is not None:
                on_obj_reward = self._calculate_on_objective_reward(game_state, result)
            elif pile_in_col is not None:
                on_obj_reward = self._calculate_on_objective_reward(game_state, {"unitId": result.get("unitId"), "toCol": pile_in_col, "toRow": pile_in_row})
            fight_reward = reward_mapper.get_combat_priority_reward(enriched_unit, enriched_target, all_targets, game_state) + objective_turn_reward + on_obj_reward
            reward_breakdown['base_actions'] = fight_reward - objective_turn_reward
            reward_breakdown['total'] = fight_reward

            fight_attack_results = result["all_attack_results"]
            fight_killed = (
                any(ar.get("target_died") for ar in fight_attack_results)
                or bool(result.get("target_died", False))
            )
            if fight_killed:
                unit_rewards = reward_mapper._get_unit_rewards(enriched_unit)
                result_bonuses_cfg = require_key(unit_rewards, "result_bonuses")
                kill_bonus = result_bonuses_cfg.get("kill_target", 0.0)
                fight_reward += kill_bonus
                reward_breakdown['result_bonuses'] = kill_bonus
                reward_breakdown['total'] = fight_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                fight_reward += situational_reward
                reward_breakdown['total'] = fight_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return fight_reward

        elif action_type in ("squad_shoot", "squad_fight"):
            # Reward shaping proportionnel aux points (spec squad.md).
            # Cote offensif uniquement : les events ciblent toujours des ennemis.
            # La symetrie alliee (pertes propres) ne passe pas par ce path car les
            # actions adverses ne generent pas de reward (cf. early-return ligne ~144).
            shaping = require_key(self._get_unit_reward_config(acting_unit), "squad_shaping")
            res_key = "shoot_result" if action_type == "squad_shoot" else "fight_result"
            combat = require_key(result, res_key)
            acting_player = require_key(acting_unit, "player")
            # Cote offensif : degats infliges aux ennemis (tout joueur != acting).
            squad_reward = self._squad_combat_shaping(
                combat, lambda p: p != acting_player, shaping
            )

            squad_total = squad_reward + objective_turn_reward
            reward_breakdown['result_bonuses'] = squad_reward
            reward_breakdown['total'] = squad_total

            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                squad_total += situational_reward
                reward_breakdown['total'] = squad_total

            game_state['last_reward_breakdown'] = reward_breakdown
            return squad_total

        elif action_type == "wait":
            # FIXED: Wait means agent chose not to act when action was available
            current_phase = require_key(game_state, "phase")
            if current_phase == "move":
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "move_wait"}, success, game_state)
            else:
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "wait"}, success, game_state)
            reward_breakdown['base_actions'] = wait_reward
            reward_breakdown['penalties'] = wait_reward
            # on_objective_bonus for pile-in without targets (_pile_in_toCol/Row set in game_state)
            pile_in_col = game_state.pop("_pile_in_toCol", None)
            pile_in_row = game_state.pop("_pile_in_toRow", None)
            on_obj_reward = 0.0
            if pile_in_col is not None:
                on_obj_reward = self._calculate_on_objective_reward(game_state, {"unitId": result.get("unitId"), "toCol": pile_in_col, "toRow": pile_in_row})
            wait_reward += objective_turn_reward + on_obj_reward
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
            pass_reward = 0.0 + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
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
            unit_rewards = self._get_unit_reward_config(acting_unit)
            charge_fail_reward = require_key(require_key(unit_rewards, "base_actions"), "charge_fail")
            reward_breakdown['base_actions'] = charge_fail_reward
            reward_breakdown['penalties'] = charge_fail_reward
            charge_fail_reward += objective_turn_reward
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
            on_obj_reward = self._calculate_on_objective_reward(game_state, result)
            advance_reward = on_obj_reward + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
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
            no_effect_reward = 0.0 + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
            reward_breakdown['total'] = no_effect_reward

            # CRITICAL FIX: Add situational reward if game ended
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                no_effect_reward += situational_reward
                reward_breakdown['total'] = no_effect_reward

            game_state['last_reward_breakdown'] = reward_breakdown
            return no_effect_reward

        # ── Actions squad pipeline ────────────────────────────────────────────

        elif action_type in ("squad_normal_move", "squad_fall_back"):
            on_obj_reward = self._calculate_on_objective_reward(game_state, result)
            movement_reward = on_obj_reward + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
            reward_breakdown['total'] = movement_reward
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                movement_reward += situational_reward
                reward_breakdown['total'] = movement_reward
            game_state['last_reward_breakdown'] = reward_breakdown
            return movement_reward

        elif action_type == "squad_advance":
            on_obj_reward = self._calculate_on_objective_reward(game_state, result)
            advance_reward = on_obj_reward + objective_turn_reward
            reward_breakdown['base_actions'] = 0.0
            reward_breakdown['total'] = advance_reward
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                advance_reward += situational_reward
                reward_breakdown['total'] = advance_reward
            game_state['last_reward_breakdown'] = reward_breakdown
            return advance_reward

        elif action_type == "squad_wait":
            current_phase = require_key(game_state, "phase")
            if current_phase == "move":
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "move_wait"}, success, game_state)
            else:
                wait_reward = self.calculate_reward_from_config(acting_unit, {"type": "wait"}, success, game_state)
            reward_breakdown['base_actions'] = wait_reward
            reward_breakdown['penalties'] = wait_reward
            wait_reward += objective_turn_reward
            reward_breakdown['total'] = wait_reward
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                wait_reward += situational_reward
                reward_breakdown['total'] = wait_reward
            game_state['last_reward_breakdown'] = reward_breakdown
            return wait_reward

        elif action_type == "squad_shoot":
            shoot_result = result.get("shoot_result", {})  # get allowed
            attacks_made = shoot_result.get("attacks_made", 0)  # get allowed
            if attacks_made == 0:
                reward_breakdown['total'] = objective_turn_reward
                game_state['last_reward_breakdown'] = reward_breakdown
                return objective_turn_reward
            unit_rewards = self._get_unit_reward_config(acting_unit)
            base_actions = require_key(unit_rewards, "base_actions")
            result_bonuses = unit_rewards.get("result_bonuses", {})  # get allowed
            base = float(base_actions.get("ranged_attack", 0.0))
            kill_bonus = float(result_bonuses.get("kill_target", 0.0)) * shoot_result.get("models_killed", 0)  # get allowed
            calculated = base + kill_bonus + objective_turn_reward
            reward_breakdown['base_actions'] = base
            reward_breakdown['result_bonuses'] = kill_bonus
            reward_breakdown['total'] = calculated
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                calculated += situational_reward
                reward_breakdown['total'] = calculated
            game_state['last_reward_breakdown'] = reward_breakdown
            return calculated

        elif action_type == "squad_charge":
            charge_succeeded = result.get("charge_succeeded", False)
            if not charge_succeeded:
                unit_rewards = self._get_unit_reward_config(acting_unit)
                charge_fail_val = float(require_key(require_key(unit_rewards, "base_actions"), "charge_fail"))
                charge_fail_val += objective_turn_reward
                reward_breakdown['base_actions'] = charge_fail_val - objective_turn_reward
                reward_breakdown['penalties'] = charge_fail_val - objective_turn_reward
                reward_breakdown['total'] = charge_fail_val
                if game_state.get("game_over", False):
                    situational_reward = self._get_situational_reward(game_state)
                    reward_breakdown['situational'] = situational_reward
                    charge_fail_val += situational_reward
                    reward_breakdown['total'] = charge_fail_val
                game_state['last_reward_breakdown'] = reward_breakdown
                return charge_fail_val
            target_squad_id = result.get("target_squad_id")
            if target_squad_id is None:
                raise ValueError(f"squad_charge succeeded but missing target_squad_id: {result}")
            target = get_unit_by_id(str(target_squad_id), game_state)
            if not target:
                raise ValueError(f"Charge target not found: {target_squad_id}")
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit, game_state)]
            charge_reward = reward_mapper.get_charge_priority_reward(enriched_unit, enriched_target, all_targets, game_state) + objective_turn_reward
            reward_breakdown['base_actions'] = charge_reward - objective_turn_reward
            reward_breakdown['total'] = charge_reward
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                charge_reward += situational_reward
                reward_breakdown['total'] = charge_reward
            game_state['last_reward_breakdown'] = reward_breakdown
            return charge_reward

        elif action_type == "squad_fight":
            target_squad_id = result.get("target_squad_id")
            if target_squad_id is None:
                raise ValueError(f"squad_fight missing target_squad_id: {result}")
            target = get_unit_by_id(str(target_squad_id), game_state)
            if not target:
                raise ValueError(f"Fight target not found: {target_squad_id}")
            enriched_target = self._enrich_unit_for_reward_mapper(target) if is_unit_alive(str(target["id"]), game_state) else target
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit, game_state)]
            fight_result = result.get("fight_result", {})  # get allowed
            fight_reward = reward_mapper.get_combat_priority_reward(enriched_unit, enriched_target, all_targets, game_state) + objective_turn_reward
            reward_breakdown['base_actions'] = fight_reward - objective_turn_reward
            reward_breakdown['total'] = fight_reward
            models_killed = fight_result.get("models_killed", 0)  # get allowed
            if models_killed > 0:
                unit_rewards = self._get_unit_reward_config(acting_unit)
                result_bonuses_cfg = require_key(unit_rewards, "result_bonuses")
                kill_bonus = float(result_bonuses_cfg.get("kill_target", 0.0))
                fight_reward += kill_bonus
                reward_breakdown['result_bonuses'] = kill_bonus
                reward_breakdown['total'] = fight_reward
            if game_state.get("game_over", False):
                situational_reward = self._get_situational_reward(game_state)
                reward_breakdown['situational'] = situational_reward
                fight_reward += situational_reward
                reward_breakdown['total'] = fight_reward
            game_state['last_reward_breakdown'] = reward_breakdown
            return fight_reward

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
        """
        if not game_state.get("game_over", False):
            return 0.0

        acting_unit = self._get_controlled_player_unit(game_state)
        if not acting_unit:
            # Controlled player has no living units — use any unit type's config
            # to retrieve the loss penalty (all unit types share situational_modifiers).
            controlled_player = int(require_key(self.config, "controlled_player"))
            winner = self._determine_winner(game_state)
            opponent_player = 2 if controlled_player == 1 else 1
            if winner == opponent_player:
                agent_key = require_key(self.config, "controlled_agent")
                unit_rewards = self.rewards_config[agent_key]
                modifiers = require_key(unit_rewards, "situational_modifiers")
                return float(require_key(modifiers, "lose"))
            elif winner == -1:
                agent_key = require_key(self.config, "controlled_agent")
                unit_rewards = self.rewards_config[agent_key]
                modifiers = require_key(unit_rewards, "situational_modifiers")
                return float(require_key(modifiers, "draw"))
            return 0.0

        unit_rewards = self._get_unit_reward_config(acting_unit)
        controlled_player = int(require_key(self.config, "controlled_player"))
        opponent_player = 2 if controlled_player == 1 else 1
        winner = self._determine_winner(game_state)

        # Calculate base win/lose/draw reward (if situational_modifiers exists)
        base_reward = 0.0
        if "situational_modifiers" in unit_rewards:
            modifiers = unit_rewards["situational_modifiers"]
            if winner == controlled_player:
                base_reward = float(require_key(modifiers, "win"))
            elif winner == opponent_player:
                base_reward = float(require_key(modifiers, "lose"))
            elif winner == -1:
                base_reward = float(require_key(modifiers, "draw"))
            else:
                raise ValueError(
                    f"Unexpected winner value in _get_situational_reward: {winner!r} "
                    f"(controlled_player={controlled_player}, opponent_player={opponent_player})"
                )

        # Add objective control reward at end of turn 5
        # CRITICAL: Calculate objective reward even if situational_modifiers is missing
        objective_reward = self._calculate_objective_reward_turn5(game_state, unit_rewards)

        # Diagnostic logging (only if not quiet)
        if not self.quiet and objective_reward > 0:
            current_turn = require_key(game_state, "turn")
            obj_counts = self.state_manager.count_controlled_objectives(game_state) if self.state_manager else {}
            controlled_count = require_key(obj_counts, controlled_player) if obj_counts else 0
            print(
                f"🎯 OBJECTIVE REWARD: Turn={current_turn}, "
                f"controlled_player={controlled_player}, "
                f"controlled_objectives={controlled_count}, Reward={objective_reward:.1f}"
            )

        return base_reward + objective_reward
    
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
        controlled_player = require_key(self.config, "controlled_player")
        units_cache = require_key(game_state, "units_cache")
        for unit_id, cache_entry in units_cache.items():
            if int(cache_entry["player"]) == int(controlled_player):
                unit = get_unit_by_id(str(unit_id), game_state)
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                return unit
        return None

    def _calculate_coherency_penalty_per_turn(self, game_state: Dict[str, Any], result: Dict[str, Any]) -> float:
        """Penalite -incoherent_weight par escouade du joueur controle hors coherency.
        Appliquee une fois par tour, au meme hook que l OC (entree en phase move).
        `is_coherent` est maintenu en temps reel dans squad_cache par destroy_model
        et update_model_position. Retourne <= 0.
        """
        if not result.get("phase_transition") or result.get("next_phase") != "move":
            return 0.0
        controlled_player = int(require_key(self.config, "controlled_player"))
        current_turn = require_key(game_state, "turn")
        penalized = require_key(game_state, "coherency_penalized_turns")
        key = (current_turn, controlled_player)
        if key in penalized:
            return 0.0
        acting_unit = self._get_controlled_player_unit(game_state)
        if not acting_unit:
            return 0.0
        shaping = require_key(self._get_unit_reward_config(acting_unit), "squad_shaping")
        incoherent_w = float(require_key(shaping, "incoherent_weight"))
        units_cache = require_key(game_state, "units_cache")
        squad_cache = require_key(game_state, "squad_cache")
        incoherent_count = 0
        for sid, entry in units_cache.items():
            if int(entry["player"]) != controlled_player:
                continue
            sc = require_key(squad_cache, str(sid))
            if not bool(require_key(sc, "is_coherent")):
                incoherent_count += 1
        penalized.add(key)
        return -incoherent_w * incoherent_count

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
        controlled_player = int(require_key(self.config, "controlled_player"))
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
        controlled_objective_samples_turn2_to_5 = require_key(
            game_state,
            "controlled_objective_samples_turn2_to_5"
        )
        if not isinstance(controlled_objective_samples_turn2_to_5, list):
            raise TypeError(
                "game_state['controlled_objective_samples_turn2_to_5'] must be a list"
            )
        opponent_player = 2 if int(controlled_player) == 1 else 1
        opponent_objectives = require_key(obj_counts, opponent_player)
        opponent_objective_samples_turn2_to_5 = game_state.setdefault("opponent_objective_samples_turn2_to_5", [])
        if 2 <= current_turn <= 5:
            controlled_objective_samples_turn2_to_5.append(float(controlled_objectives))
            opponent_objective_samples_turn2_to_5.append(float(opponent_objectives))
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
        
        Simple approach: Reward per objective controlled by the controlled player.
        Only applies when game ends at turn 5 (not elimination).
        Reward value is read from config: objective_rewards.reward_per_objective_turn5
        
        Returns:
            Reward value (reward_per_objective * number of objectives controlled by the controlled player)
        """
        # Only apply at end of turn 5 (not elimination)
        current_turn = require_key(game_state, "turn")
        turn_limit_reached = game_state.get("turn_limit_reached", False)
        
        # Check if game ended at turn 5
        # Either: turn_limit_reached is True (turn limit reached)
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
        
        # Both players still alive - game ended at turn 5.
        # Calculate objectives controlled by the controlled player.
        if not self.state_manager:
            return 0.0
        
        obj_counts = self.state_manager.count_controlled_objectives(game_state)
        controlled_player = int(require_key(self.config, "controlled_player"))
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
    
    def _squad_combat_shaping(self, combat: Dict[str, Any], is_victim, shaping: Dict[str, Any]) -> float:
        """Valeur proportionnelle-points des degats subis par les figurines dont
        `is_victim(target_player)` est vrai, dans un summary de resolve_squad_*.
        Toujours positif — l appelant applique le signe (offensif +, defensif -).

        Composantes (spec squad.md) :
          - points_per_hp * hp_damage_weight * damage  (par HP retire)
          - model_value * model_kill_bonus_factor  (par fig tuee — VALUE de CETTE
            figurine, portee par l event ; tuer le Nob rapporte plus qu un Boy)
          - value * squad_kill_bonus_factor  (par escouade wipe)
        """
        hp_w = float(require_key(shaping, "hp_damage_weight"))
        kill_f = float(require_key(shaping, "model_kill_bonus_factor"))
        wipe_f = float(require_key(shaping, "squad_kill_bonus_factor"))
        targets_meta = require_key(combat, "targets_meta")
        total = 0.0
        for ev in require_key(combat, "events"):
            if not is_victim(int(ev["target_player"])):
                continue
            total += float(ev["points_per_hp"]) * hp_w * int(ev["damage"])
            if ev["destroyed"]:
                total += float(require_key(ev, "model_value")) * kill_f
        for sid in require_key(combat, "squads_wiped"):
            meta = require_key(targets_meta, sid)
            if is_victim(int(require_key(meta, "player"))):
                total += float(require_key(meta, "value")) * wipe_f
        return total

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
        from engine.utils.weapon_helpers import get_max_ranged_range
        from engine.spatial_relations import get_engagement_zone_from_config
        
        max_rng_range = get_max_ranged_range(unit)
        melee_range = get_engagement_zone_from_config(self.config)
        
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

    def _calculate_on_objective_reward(self, game_state: Dict[str, Any], result: Dict[str, Any]) -> float:
        """Reward fired when a controlled-player unit lands on an uncontrolled objective hex during move."""
        controlled_player = int(require_key(self.config, "controlled_player"))
        unit = get_unit_by_id(str(result.get("unitId", "")), game_state)
        if not unit or int(require_key(unit, "player")) != controlled_player:
            return 0.0
        to_col = result.get("toCol")
        to_row = result.get("toRow")
        if to_col is None or to_row is None:
            return 0.0
        unit_rewards = self._get_unit_reward_config(unit)
        if "objective_rewards" not in unit_rewards or "on_objective_bonus" not in unit_rewards["objective_rewards"]:
            raise KeyError("Unit rewards missing required 'on_objective_bonus' in 'objective_rewards'")
        on_objective_bonus = float(unit_rewards["objective_rewards"]["on_objective_bonus"])
        objectives = require_key(game_state, "objectives")
        for zone_idx, obj in enumerate(objectives):
            for h in obj["hexes"]:
                h_col = int(h["col"]) if isinstance(h, dict) else int(h[0])
                h_row = int(h["row"]) if isinstance(h, dict) else int(h[1])
                if h_col == int(to_col) and h_row == int(to_row):
                    if get_objective_control(zone_idx, game_state) < 1.0:
                        return on_objective_bonus
        return 0.0

    def compute_zone_intent_shaping(self, game_state: Dict[str, Any]) -> float:
        """
        Compute zone intent shaping reward based on current zone intents and objective control.

        Called once per command phase, stored in _pending_zone_shaping, added to the first
        non-zone-intent action reward of the turn.

        Returns:
          +0.05 per DEFEND zone where the objective is currently held (controlled by current_player)
          -0.05 per INVADE zone where the objective is lost (controlled by opponent)
        """
        agent_key = require_key(self.config, "controlled_agent")
        zone_intent_cfg = self.rewards_config[agent_key]["zone_intent_shaping"]
        defend_bonus = zone_intent_cfg["defend_held_bonus"]
        invade_success_bonus = zone_intent_cfg["invade_success_bonus"]
        invade_neutral_bonus = zone_intent_cfg["invade_neutral_bonus"]
        invade_own_penalty = zone_intent_cfg["invade_lost_penalty"]

        zone_intents = game_state["zone_intents"]
        shaping = 0.0
        for zone_idx, intent in enumerate(zone_intents):
            control = get_objective_control(zone_idx, game_state)
            if intent == INTENT_DEFEND and control == 1.0:
                shaping += defend_bonus
            elif intent == INTENT_INVADE and control == -1.0:
                shaping += invade_success_bonus   # cible une zone ennemie : correct
            elif intent == INTENT_INVADE and control == 0.0:
                shaping += invade_neutral_bonus   # cible une zone neutre : acceptable
            elif intent == INTENT_INVADE and control == 1.0:
                shaping += invade_own_penalty     # déclare invasion sur sa propre zone : incorrect
        return shaping

