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
        
        # CRITICAL: Test that episode_steps field exists and persists
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
        
        # CRITICAL FIX: NEVER force sync during normal operation - let Sequential Engine handle its own state
        # Only sync on true desynchronization (first action of episode or after reset)
        sequential_needs_sync = (
            self.sequential_engine.queue_built_for_phase is None and
            len(self.sequential_engine.activation_queue) == 0
        )
        if sequential_needs_sync:
            # Simple initial sync - no complex phase checking
            self.sequential_engine.queue_built_for_phase = None
            self.sequential_engine.queue_built_for_player = None
            self.sequential_engine.activation_queue = []
            self.sequential_engine.phase_complete = False
            self.sequential_engine.current_active_unit = None
            
            # No complex sync logic needed - let Sequential Integration Wrapper handle phase initialization
            
        # Execute action through parent Sequential Integration Wrapper
        obs, reward, terminated, truncated, info = super().execute_gym_action(action)
        
        # Get the active unit that was used by parent wrapper
        active_unit = self.sequential_engine.current_active_unit
        
        # Capture state after action
        if "episode_steps" not in self.base_controller.game_state:
            raise KeyError("game_state missing required 'episode_steps' field after action execution")
        steps_after = self.base_controller.game_state["episode_steps"]
        
        # AI_TURN.md COMPLIANCE: Only log actions that were attempted by active units
        # Auto-skip ineligible units should NOT generate step increments or warnings
        if (len(self.sequential_engine.activation_queue) == 0 and 
            steps_after == steps_before and  # No step increment
            active_unit):  # Had an active unit
            # Check if unit was actually ineligible (auto-skipped) vs attempted action
            action_attempted = info.get('action_attempted', True)  # Default assume action was attempted
            if not action_attempted:
                # Unit was auto-skipped (ineligible) - this is CORRECT per AI_TURN.md
                pass  # No warning needed - ineligible units don't increment steps
            else:
                # Unit attempted action but failed - this may indicate a problem
                print(f"   ⚠️ Action attempted but no step increment - check action logic")
        step_increment = steps_after > steps_before
        action_success = info.get("action_success", False)
        
        # AI_TURN.md COMPLIANCE: Only log actions that were ATTEMPTED (not auto-skipped ineligible units)
        action_attempted = info.get('action_attempted', steps_after > steps_before)
        if self.step_logger and self.step_logger.enabled and active_unit and action_attempted:
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
                        # CRITICAL FIX: Always ensure target_id exists for shoot actions
                        if not valid_targets or len(valid_targets) == 0:
                            details["target_id"] = "none"
                        else:
                            details["target_id"] = valid_targets[0]
                    elif action_type == "charge":
                        valid_targets = self.base_controller.game_actions["get_valid_charge_targets"](unit["id"])
                    elif action_type == "combat":
                        valid_targets = self.base_controller.game_actions["get_valid_combat_targets"](unit["id"])
                        # CRITICAL FIX: Always ensure target_id exists for combat actions
                        if not valid_targets or len(valid_targets) == 0:
                            details["target_id"] = "none"
                        else:
                            details["target_id"] = valid_targets[0]
                    
                    if valid_targets and len(valid_targets) > 0:
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
                
                # Extract dice roll details with graceful fallbacks
                details["hit_roll"] = combat_results.get("hit_roll", last_action_result.get("hit_roll", "N/A"))
                details["wound_roll"] = combat_results.get("wound_roll", last_action_result.get("wound_roll", "N/A"))
                details["save_roll"] = combat_results.get("save_roll", last_action_result.get("save_roll", "N/A"))
                details["damage_dealt"] = combat_results.get("damage_dealt", last_action_result.get("damage_dealt", 0))
                details["hit_target"] = combat_results.get("hit_target", last_action_result.get("hit_target", "N/A"))
                details["wound_target"] = combat_results.get("wound_target", last_action_result.get("wound_target", "N/A"))
                details["save_target"] = combat_results.get("save_target", last_action_result.get("save_target", "N/A"))
                
                # Determine results with safe conversion
                try:
                    hit_roll_val = int(details["hit_roll"]) if details["hit_roll"] != "N/A" else 0
                    hit_target_val = int(details["hit_target"]) if details["hit_target"] != "N/A" else 7
                    details["hit_result"] = "HIT" if hit_roll_val >= hit_target_val else "MISS"
                    
                    wound_roll_val = int(details["wound_roll"]) if details["wound_roll"] != "N/A" else 0
                    wound_target_val = int(details["wound_target"]) if details["wound_target"] != "N/A" else 7
                    details["wound_result"] = "WOUND" if wound_roll_val >= wound_target_val else "FAIL"
                    
                    save_roll_val = int(details["save_roll"]) if details["save_roll"] != "N/A" else 0
                    save_target_val = int(details["save_target"]) if details["save_target"] != "N/A" else 7
                    details["save_result"] = "FAIL" if save_roll_val < save_target_val else "SAVE"
                except (ValueError, TypeError):
                    details["hit_result"] = "N/A"
                    details["wound_result"] = "N/A"
                    details["save_result"] = "N/A"
                
            except Exception:
                # Silent fallback - no error message needed
                details["hit_roll"] = "N/A"
                details["wound_roll"] = "N/A" 
                details["save_roll"] = "N/A"
                details["damage_dealt"] = 0
                details["hit_result"] = "N/A"
                details["wound_result"] = "N/A"
                details["save_result"] = "N/A"
                details["hit_target"] = "N/A"
                details["wound_target"] = "N/A"
                details["save_target"] = "N/A"
        
        # CRITICAL FIX: Ensure ALL required fields exist for shoot actions
        if action_type == "shoot":
            required_fields = ["target_id", "hit_roll", "wound_roll", "save_roll", "damage_dealt", 
                             "hit_result", "wound_result", "save_result", "hit_target", "wound_target", "save_target"]
            for field in required_fields:
                if field not in details:
                    details[field] = "none" if field == "target_id" else ("N/A" if field in ["hit_result", "wound_result", "save_result"] else (0 if field == "damage_dealt" else "N/A"))
        
        # CRITICAL FIX: Ensure charge and combat actions have required target_id
        elif action_type in ["charge", "combat"]:
            if "target_id" not in details:
                details["target_id"] = "none"
        
        return details

    def _find_unit_by_id(self, unit_id: int) -> Optional[Dict[str, Any]]:
        """Find unit by ID in current game state."""
        try:
            all_units = self.base_controller.get_units()
            for unit in all_units:
                if unit.get("id") == unit_id:
                    return unit
        except Exception:
            pass
        return None


def create_step_logging_wrapper(config, quiet=False, step_logger=None):
    """Factory function to create step logging wrapper."""
    return StepLoggingWrapper(config, quiet, step_logger)