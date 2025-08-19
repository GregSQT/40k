#!/usr/bin/env python3
"""
Step Logging Wrapper - AI_TURN.md Compliant Action Logger

PURPOSE: Wraps Sequential Integration Wrapper to capture detailed step logs
COMPLIANCE: Only logs actions that generate step increments per AI_TURN.md

STEP INCREMENT ACTIONS (AI_TURN.md):
- move, shoot, charge, combat, wait (when executed successfully)

NO STEP INCREMENT ACTIONS:
- Auto-skip ineligible units
- Phase transitions  
- Failed action attempts
- Unit selection (Sequential Engine handles this)

INTEGRATION: This wrapper sits between gym40k.py and Sequential Integration Wrapper
"""

import copy
from typing import Dict, List, Any, Optional, Tuple
import time
from sequential_integration_wrapper import SequentialGameController


def ensure_episode_steps_in_game_state(game_state):
    """Ensure episode_steps field exists in game_state for step logging compatibility."""
    if "episode_steps" not in game_state:
        game_state["episode_steps"] = 0
        # Silent addition - no warning needed for normal operation
    # Field exists, no action needed


def enable_step_logging_on_environment(env, step_logger):
    """
    Enable step logging on an existing W40KEnv by replacing its controller.
    
    Args:
        env: W40KEnv instance
        step_logger: StepLogger instance
    """
    if not hasattr(env, 'controller'):
        raise ValueError("Environment must have a controller attribute")
    
    # Save original controller config and state
    original_controller = env.controller
    config = original_controller.base_controller.config if hasattr(original_controller, 'base_controller') else None
    quiet = getattr(original_controller, 'quiet', False)
    
    # Create new step logging wrapper with same config
    if config:
        step_logging_controller = StepLoggingWrapper(config, quiet, step_logger)
        
        # CRITICAL FIX: AI_ARCHITECTURE.md Single Source of Truth compliance
        # Replace the entire base_controller with the original to ensure same game_state object
        if hasattr(original_controller, 'base_controller'):
            # Store step logger reference before replacement
            temp_step_logger = step_logging_controller.step_logger
            
            # Replace base_controller completely to maintain game_state object identity
            step_logging_controller.base_controller = original_controller.base_controller
            
            # Restore step logger after controller replacement
            step_logging_controller.step_logger = temp_step_logger
            
            # CRITICAL FIX: Ensure episode_steps field exists in the SAME object
            ensure_episode_steps_in_game_state(step_logging_controller.base_controller.game_state)
            
            # Verify game_state object identity is preserved
            if id(step_logging_controller.base_controller.game_state) != id(original_controller.base_controller.game_state):
                raise RuntimeError("game_state object identity violation - Single Source of Truth broken")
        
        # Replace controller and connect gym environment
        env.controller = step_logging_controller
        env.controller.connect_gym_env(env)
        
        # CRITICAL VALIDATION: Verify Single Source of Truth compliance
        expected_state_id = id(original_controller.base_controller.game_state)
        actual_state_id = id(env.controller.base_controller.game_state)
        if expected_state_id != actual_state_id:
            raise RuntimeError(f"CRITICAL: game_state object mismatch - Expected ID: {expected_state_id}, Got: {actual_state_id}")
        
        print(f"✅ Step logging enabled on environment (game_state ID: {actual_state_id})")
        
        # CRITICAL: Test that episode_steps field exists and persists
        print(f"🔍 episode_steps field check: {env.controller.base_controller.game_state.get('episode_steps', 'MISSING')}")
    else:
        # Fallback: just attach step logger to existing controller
        if hasattr(env.controller, 'step_logger'):
            env.controller.step_logger = step_logger
        else:
            # CRITICAL FIX: Ensure episode_steps field exists in fallback mode
            if hasattr(env.controller, 'base_controller') and hasattr(env.controller.base_controller, 'game_state'):
                ensure_episode_steps_in_game_state(env.controller.base_controller.game_state)
            
            # Try to patch the execute_gym_action method
            original_execute = env.controller.execute_gym_action
            
            def logged_execute_gym_action(action):
                # Simple logging wrapper
                result = original_execute(action)
                if step_logger and step_logger.enabled:
                    # Basic logging without detailed parsing
                    step_logger.action_count += 1
                    success = result[3].get('action_success', False) if len(result) > 3 else False
                    if success:
                        step_logger.step_count += 1
                return result
            
            env.controller.execute_gym_action = logged_execute_gym_action
            print(f"⚠️ Basic step logging enabled (fallback mode)")


class StepLoggingWrapper(SequentialGameController):
    """
    Step Logging Wrapper for Sequential Game Controller
    
    Captures detailed logs of all step-incrementing actions per AI_TURN.md compliance.
    """
    
    def __init__(self, config, quiet=False, step_logger=None):
        """Initialize with step logger."""
        super().__init__(config, quiet)
        self.step_logger = step_logger
        self.last_episode_steps = 0
        
    def connect_gym_env(self, gym_env):
        """Override to ensure episode_steps field is maintained after reset."""
        result = super().connect_gym_env(gym_env)
        
        # Hook into the environment's reset method to ensure episode_steps field
        if hasattr(gym_env, 'reset'):
            original_reset = gym_env.reset
            
            def logged_reset(*args, **kwargs):
                # Call original reset
                result = original_reset(*args, **kwargs)
                
                # CRITICAL FIX: Completely reset Sequential Engine after env reset
                if hasattr(self, 'sequential_engine'):
                    # Reset Sequential Engine state to match new episode
                    self.sequential_engine.activation_queue = []
                    self.sequential_engine.current_active_unit = None
                    self.sequential_engine.phase_complete = False
                    self.sequential_engine.queue_built_for_phase = None
                    self.sequential_engine.queue_built_for_player = None
                    self.sequential_engine.phase_started = False
                    self.sequential_engine.last_phase = None
                    
                    # Reset combat state
                    self.sequential_engine.combat_sub_phase = "charged_units"
                    self.sequential_engine.combat_active_player = 1
                    self.sequential_engine.combat_charged_queue = []
                    self.sequential_engine.combat_alternating_queue = []
                    self.sequential_engine.unit_charge_rolls = {}
                
                # Reconnect gym environment to controller
                if (hasattr(self, 'base_controller') and 
                    hasattr(self.base_controller, 'connect_gym_env')):
                    self.base_controller.connect_gym_env(gym_env)
                
                # CRITICAL FIX: Ensure episode_steps exists after reset
                if (hasattr(self, 'base_controller') and 
                    hasattr(self.base_controller, 'game_state')):
                    ensure_episode_steps_in_game_state(self.base_controller.game_state)
                
                return result
            
            gym_env.reset = logged_reset
            print("✅ Hooked env.reset() to maintain episode_steps field")
        
        return result
        
    def execute_gym_action(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """
        Execute gym action with step logging integration.
        """
        
        # CRITICAL FIX: Ensure Sequential Engine's controller has gym_env connection
        if (hasattr(self.sequential_engine, 'game_controller') and 
            hasattr(self.base_controller, 'gym_env') and 
            self.base_controller.gym_env and
            not hasattr(self.sequential_engine.game_controller, 'gym_env')):
            self.sequential_engine.game_controller.gym_env = self.base_controller.gym_env
        
        # Capture state before action - ALWAYS get fresh phase from controller
        if "episode_steps" not in self.base_controller.game_state:
            raise KeyError("game_state missing required 'episode_steps' field - check use_game_state.py initialization")
        steps_before = self.base_controller.game_state["episode_steps"]
        current_phase = self.base_controller.get_current_phase()  # Fresh read each time
        current_player = self.base_controller.get_current_player()
        
        # Minimal debug for critical steps only
        if steps_before <= 2:  # Only first 2 steps
            print(f"🔍 STEP {steps_before}: Phase={current_phase}, Player={current_player}")
        
        # CRITICAL FIX: ALWAYS use controller as single source of truth for phase
        current_player = self.base_controller.get_current_player()
        controller_actual_phase = self.base_controller.get_current_phase()
        
        # OVERRIDE: Always use controller's phase, ignore what step wrapper thinks
        if current_phase != controller_actual_phase:
            current_phase = controller_actual_phase
        
        # Controller is ALWAYS the authoritative source for current phase
        current_phase = controller_actual_phase
        
        # CRITICAL FIX: Always ensure Sequential Engine uses correct current player
        actual_current_player = self.base_controller.get_current_player()
        
        # Only sync if there's an actual mismatch with Sequential Engine state
        if (self.sequential_engine.queue_built_for_phase != current_phase or 
            self.sequential_engine.queue_built_for_player != actual_current_player):
            
            print(f"🔧 SYNC: Phase {self.sequential_engine.queue_built_for_phase}→{current_phase}, Player {self.sequential_engine.queue_built_for_player}→{actual_current_player}")
            
            # CRITICAL FIX: Double-check controller phase right before sync
            final_controller_phase = self.base_controller.get_current_phase()
            if current_phase != final_controller_phase:
                print(f"⚠️ RACE CONDITION: phase changed during sync '{current_phase}' → '{final_controller_phase}'")
                current_phase = final_controller_phase
            
            # Reset Sequential Engine completely and sync to controller's ACTUAL phase
            self.sequential_engine.queue_built_for_phase = None
            self.sequential_engine.queue_built_for_player = None
            self.sequential_engine.activation_queue = []
            self.sequential_engine.phase_complete = False
            self.sequential_engine.current_active_unit = None
            
            # Reset phase-specific state
            if current_phase == "combat":
                self.sequential_engine.combat_sub_phase = "charged_units"
                self.sequential_engine.combat_active_player = 1
                self.sequential_engine.combat_charged_queue = []
                self.sequential_engine.combat_alternating_queue = []
            elif current_phase == "charge":
                self.sequential_engine.unit_charge_rolls = {}
            
            # FINAL VERIFICATION: Ensure controller phase hasn't changed again
            verification_phase = self.base_controller.get_current_phase()
            if current_phase != verification_phase:
                print(f"⚠️ CRITICAL: Controller phase changed during sync! Expected '{current_phase}', got '{verification_phase}'")
                print("🚫 Skipping Sequential Engine sync to avoid race condition")
                return super().execute_gym_action(action)
            
            # CRITICAL FIX: Override Sequential Engine's internal phase check to prevent race condition
            # Temporarily disable the phase mismatch check in Sequential Engine
            original_start_phase = self.sequential_engine.start_phase
            
            def safe_start_phase(phase_name):
                # Skip the controller phase check and go directly to queue building
                # CRITICAL FIX: Use fresh current player reading
                fresh_current_player = self.base_controller.get_current_player()
                all_units = self.base_controller.get_units()
                living_units = [u for u in all_units if u.get("CUR_HP", 0) > 0]
                
                if phase_name == "combat":
                    self.sequential_engine._build_combat_queues(living_units)
                else:
                    eligible_units = [u for u in living_units if u["player"] == fresh_current_player]
                    self.sequential_engine.activation_queue = copy.deepcopy(eligible_units)
                    
                self.sequential_engine.current_active_unit = None
                self.sequential_engine.phase_complete = False
                self.sequential_engine.queue_built_for_phase = phase_name
                self.sequential_engine.queue_built_for_player = current_player
                
                if phase_name == "charge":
                    self.sequential_engine.unit_charge_rolls = {}
                
                self.sequential_engine.debug_actions_taken = []
                self.sequential_engine.debug_units_skipped = []
                self.sequential_engine.auto_skipped_units = 0
            
            # Use safe version to avoid race condition
            safe_start_phase(current_phase)
            
        # Get active unit for action (outside sync block)
        active_unit = self.sequential_engine.get_next_active_unit()
        
        # CRITICAL DEBUG: Track action execution and queue state
        print(f"🎬 EXECUTING ACTION: {action} for unit {active_unit['id'] if active_unit else None} in phase {current_phase}")
        print(f"   Queue before action: {len(self.sequential_engine.activation_queue)} units")
        
        # CRITICAL DEBUG: Track what the parent Sequential Integration Wrapper does
        print(f"   🔄 Calling parent SequentialGameController.execute_gym_action...")
        
        # Execute action through parent Sequential Integration Wrapper
        obs, reward, terminated, truncated, info = super().execute_gym_action(action)
        
        # CRITICAL DEBUG: Immediately check what happened to the queue
        print(f"   🔄 Parent call completed")
        print(f"   Queue after action: {len(self.sequential_engine.activation_queue)} units")
        if len(self.sequential_engine.activation_queue) == 0:
            print(f"   🚨 QUEUE CLEARED! Phase complete set to: {self.sequential_engine.phase_complete}")
            
        # TEMPORARY FIX: If queue was incorrectly cleared but should have remaining units, restore it
        # (Note: steps_after not available yet at this point - will be calculated later)
        if (len(self.sequential_engine.activation_queue) == 0 and 
            self.sequential_engine.phase_complete):
            print(f"   🔧 TEMPORARY FIX: Queue was incorrectly cleared after action")
        
        # CRITICAL DEBUG: Check what happened during action execution
        print(f"🎬 ACTION RESULT: success={info.get('action_success', 'unknown')}, reward={reward}")
        print(f"   Episode terminated: {terminated}, truncated: {truncated}")
        
        # Capture state after action
        if "episode_steps" not in self.base_controller.game_state:
            raise KeyError("game_state missing required 'episode_steps' field after action execution")
        steps_after = self.base_controller.game_state["episode_steps"]
        
        # CRITICAL DEBUG: Check Sequential Engine state after action
        print(f"🎬 AFTER ACTION: Queue length: {len(self.sequential_engine.activation_queue)}")
        print(f"   Phase complete: {self.sequential_engine.phase_complete}")
        print(f"   Steps before: {steps_before}, after: {steps_after}")
        
        # ANALYSIS: Check if we need to restore queue for remaining units
        if (len(self.sequential_engine.activation_queue) == 0 and 
            steps_after > steps_before and  # Unit actually acted successfully
            active_unit):  # Had an active unit
            print(f"   ✅ Unit {active_unit['id']} acted successfully, queue cleared normally")
        elif (len(self.sequential_engine.activation_queue) == 0 and 
              steps_after == steps_before and  # No step increment
              info.get('action_success', False) and  # But action was successful
              active_unit):  # Had an active unit
            print(f"   🔧 FIXING: Action succeeded but no step increment - forcing increment")
            # Force step increment when parent wrapper fails to do it
            self.base_controller.game_state["episode_steps"] = steps_before + 1
            steps_after = steps_before + 1
            print(f"   Steps corrected: {steps_before} → {steps_after}")
        elif (len(self.sequential_engine.activation_queue) == 0 and 
              steps_after == steps_before):  # No step increment and no success
            print(f"   ⚠️ Queue cleared but no step increment - action may have failed")
        step_increment = steps_after > steps_before
        action_success = info.get("action_success", False)
        
        # Log the action if step logger is enabled
        if self.step_logger and self.step_logger.enabled and active_unit:
            action_type = self._decode_action_type(action)
            unit_id = active_unit.get("id", "unknown")
            
            # Get replay-style action details for formatting
            action_details = self._get_replay_style_details(action, active_unit, current_phase, info, steps_before, steps_after)
            
            # AI_TURN.md COMPLIANCE: Step increment based on action ATTEMPT, not success
            # Failed attacks still increment steps because unit consumed time/effort
            step_increment_actions = ["move", "shoot", "charge", "combat", "wait"]
            step_increment = action_type in step_increment_actions
            
            # Log with step increment status per AI_TURN.md
            self.step_logger.log_action(
                unit_id=unit_id,
                action_type=action_type,
                phase=current_phase,
                player=current_player,
                success=action_success,
                step_increment=step_increment,
                action_details=action_details
            )
        
        # Log phase transitions separately (no step increment)
        if self.step_logger and self.step_logger.enabled:
            new_phase = self.base_controller.get_current_phase()
            new_player = self.base_controller.get_current_player()
            
            if new_phase != current_phase or new_player != current_player:
                self.step_logger.log_phase_transition(
                    from_phase=current_phase,
                    to_phase=new_phase,
                    player=new_player
                )
        
        # Log episode end
        if terminated and self.step_logger and self.step_logger.enabled:
            final_steps = self.base_controller.game_state.get("episode_steps", 0)
            winner = info.get("winner", "unknown")
            self.step_logger.log_episode_end(final_steps, winner)
        
        return obs, reward, terminated, truncated, info
    
    def _decode_action_type(self, action: int) -> str:
        """Decode gym action integer to action type string."""
        action_map = {
            0: "move",    # North
            1: "move",    # South
            2: "move",    # East
            3: "move",    # West
            4: "shoot",
            5: "charge",
            6: "combat",
            7: "wait"
        }
        
        if hasattr(action, 'item') and callable(action.item):
            action = int(action.item())
        else:
            action = int(action)
            
        action_type = action % 8
        return action_map.get(action_type, "unknown")
    
    def _get_replay_style_details(self, action: int, unit: Dict[str, Any], phase: str, info: Dict[str, Any], steps_before: int, steps_after: int) -> Dict[str, Any]:
        """Get action details in format needed for replay-style messages."""
        details = {}
        action_type = self._decode_action_type(action)
        
        # Store unit position info for move actions - NO DEFAULTS
        if action_type == "move":
            if "col" not in unit:
                raise KeyError("Unit missing required col field for move action")
            if "row" not in unit:
                raise KeyError("Unit missing required row field for move action")
            
            start_col = unit["col"]
            start_row = unit["row"]
            
            # Calculate end position based on action direction
            direction_map = {0: (0, -1), 1: (0, 1), 2: (1, 0), 3: (-1, 0)}  # N, S, E, W
            if hasattr(action, 'item'):
                action = int(action.item())
            
            if (action % 8) not in direction_map:
                raise ValueError(f"Invalid movement action {action % 8} - valid actions: {list(direction_map.keys())}")
            col_diff, row_diff = direction_map[action % 8]
            end_col = start_col + col_diff
            end_row = start_row + row_diff
            
            details["start_pos"] = (start_col, start_row)
            details["end_pos"] = (end_col, end_row)
            
        # Get target information for combat actions
        elif action_type in ["shoot", "charge", "combat"]:
            # Try to extract target from Sequential Engine or controller
            if hasattr(self.base_controller, 'game_actions'):
                try:
                    if action_type == "shoot":
                        valid_targets = self.base_controller.game_actions["get_valid_shooting_targets"](unit["id"])
                    elif action_type == "charge":
                        valid_targets = self.base_controller.game_actions["get_valid_charge_targets"](unit["id"])
                    elif action_type == "combat":
                        valid_targets = self.base_controller.game_actions["get_valid_combat_targets"](unit["id"])
                    
                    if valid_targets:
                        details["target_id"] = valid_targets[0]  # First target used by Sequential Engine
                        
                        # Get target unit details for charge messages
                        if action_type == "charge":
                            target_unit = self._find_unit_by_id(valid_targets[0])
                            if target_unit:
                                details["target_name"] = target_unit.get("unit_type", "unknown")
                                details["unit_name"] = unit.get("unit_type", "unknown")
                                # Use same position calculation as move
                                details["start_pos"] = (unit.get("col", 0), unit.get("row", 0))
                                # For charge, end pos is adjacent to target (simplified)
                                details["end_pos"] = (target_unit.get("col", 0), target_unit.get("row", 0))
                                
                except Exception:
                    pass  # Target lookup failed, continue without target info
        
        # Extract combat details from info dict if available
        if action_type in ["shoot", "combat"] and info:
            # Try to extract dice roll results from controller state or info
            try:
                # Look for combat results in various possible locations
                combat_results = info.get("combat_results", {})
                last_action_result = info.get("last_action_result", {})
                
                # Extract dice roll details including target numbers - NO DEFAULTS
                if "hit_roll" not in combat_results and "hit_roll" not in last_action_result:
                    raise KeyError("Combat results missing required hit_roll")
                if "wound_roll" not in combat_results and "wound_roll" not in last_action_result:
                    raise KeyError("Combat results missing required wound_roll")
                if "save_roll" not in combat_results and "save_roll" not in last_action_result:
                    raise KeyError("Combat results missing required save_roll")
                if "damage_dealt" not in combat_results and "damage_dealt" not in last_action_result:
                    raise KeyError("Combat results missing required damage_dealt")
                if "hit_target" not in combat_results and "hit_target" not in last_action_result:
                    raise KeyError("Combat results missing required hit_target")
                if "wound_target" not in combat_results and "wound_target" not in last_action_result:
                    raise KeyError("Combat results missing required wound_target")
                if "save_target" not in combat_results and "save_target" not in last_action_result:
                    raise KeyError("Combat results missing required save_target")
                
                details["hit_roll"] = combat_results["hit_roll"] if "hit_roll" in combat_results else last_action_result["hit_roll"]
                details["wound_roll"] = combat_results["wound_roll"] if "wound_roll" in combat_results else last_action_result["wound_roll"]
                details["save_roll"] = combat_results["save_roll"] if "save_roll" in combat_results else last_action_result["save_roll"]
                details["damage_dealt"] = combat_results["damage_dealt"] if "damage_dealt" in combat_results else last_action_result["damage_dealt"]
                details["hit_target"] = combat_results["hit_target"] if "hit_target" in combat_results else last_action_result["hit_target"]
                details["wound_target"] = combat_results["wound_target"] if "wound_target" in combat_results else last_action_result["wound_target"]
                details["save_target"] = combat_results["save_target"] if "save_target" in combat_results else last_action_result["save_target"]
                
                # Determine results based on target vs roll - NO FALLBACKS
                details["hit_result"] = "HIT" if int(details["hit_roll"]) >= int(details["hit_target"]) else "MISS"
                details["wound_result"] = "WOUND" if int(details["wound_roll"]) >= int(details["wound_target"]) else "FAIL"
                details["save_result"] = "FAIL" if int(details["save_roll"]) < int(details["save_target"]) else "SAVE"
                
            except Exception as e:
                # TEMPORARY: Allow combat logging to continue without details during debugging
                print(f"⚠️ Combat details missing for {action_type} action: {e}")
                details["hit_roll"] = "missing"
                details["wound_roll"] = "missing" 
                details["save_roll"] = "missing"
                details["damage_dealt"] = "missing"
                details["hit_result"] = "missing"
                details["wound_result"] = "missing"
                details["save_result"] = "missing"
                details["hit_target"] = "missing"
                details["wound_target"] = "missing"
                details["save_target"] = "missing"
        
        return details


def create_step_logging_wrapper(config, quiet=False, step_logger=None):
    """Factory function to create step logging wrapper."""
    return StepLoggingWrapper(config, quiet, step_logger)