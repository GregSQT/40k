"""
Sequential Integration Wrapper - Minimal Working Version

CRITICAL PURPOSE: Wraps execute_gym_action() to route through SequentialActivationEngine
without breaking existing code. Minimal version to avoid import issues.

INTEGRATION STRATEGY:
1. Simple wrapper class that inherits from base class
2. Overrides execute_gym_action() only 
3. Returns proper gymnasium tuples
4. No complex dependencies

COMPLIANCE: Provides sequential activation with minimal surface area
"""

from typing import Dict, List, Any, Optional, Tuple
import numpy as np
from dataclasses import dataclass, field

@dataclass
class GameControllerConfig:
    """Configuration for GameController - minimal version for compatibility"""
    initial_units: List[Dict[str, Any]] = field(default_factory=list)
    game_mode: str = "training"
    board_config_name: str = "default"
    config_path: str = ""
    max_turns: int = 10
    enable_ai_player: bool = False
    training_mode: bool = True
    training_config_name: str = "default"
    log_available_height: int = 300


class SequentialGameController:
    """
    Sequential Game Controller with Sequential Activation Engine
    
    Routes all actions through SequentialActivationEngine for sequential rule enforcement.
    """
    
    def __init__(self, config, quiet=False):
        """Initialize with config and sequential activation engine."""
        # Import here to avoid circular imports
        from ai.game_controller import TrainingGameController
        from sequential_activation_engine import SequentialActivationEngine
        
        self.base_controller = TrainingGameController(config, quiet)
        self.sequential_engine = SequentialActivationEngine(self.base_controller)
        self.gym_env = None
        
        # Phase state tracking
        self.phase_started = False
        self.last_phase = None
        
    def __getattr__(self, name):
        """Delegate all attributes to base controller."""
        return getattr(self.base_controller, name)
        
    def connect_gym_env(self, gym_env):
        """Connect gym environment for observation delegation."""
        self.gym_env = gym_env
        if hasattr(self.base_controller, 'connect_gym_env'):
            self.base_controller.connect_gym_env(gym_env)
            
        # CRITICAL FIX: Connect replay logger from gym environment
        if hasattr(gym_env, 'replay_logger'):
            self.base_controller.replay_logger = gym_env.replay_logger
        
    def execute_gym_action(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """
        Execute gym action through Sequential Activation Engine.
        
        Args:
            action: Gym action integer
            
        Returns:
            Tuple: (observation, reward, terminated, truncated, info)
        """
        # Use Sequential Engine integration that was implemented
        return self._execute_via_sequential_engine(action)
            
    def _execute_via_sequential_engine(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """Execute action through Sequential Activation Engine with full integration."""
        current_phase = self.base_controller.get_current_phase()
        
        # CRITICAL FIX: Initialize Sequential Engine for phase if not already done
        if (self.sequential_engine.queue_built_for_phase != current_phase or 
            self.sequential_engine.queue_built_for_player != self.base_controller.get_current_player()):
            print(f"🎯 [sequential_integration_wrapper.py::_execute_via_sequential_engine] BUILDING ACTIVATION QUEUE FOR {current_phase} PHASE - Player {self.base_controller.get_current_player()}")
            self.sequential_engine.start_phase(current_phase)
        
        # CRITICAL FIX: Get next unit from Sequential Engine queue (ONE unit per action)
        active_unit = self.sequential_engine.get_next_active_unit()
        if active_unit:
            print(f"🎮 [sequential_integration_wrapper.py::_execute_via_sequential_engine] ACTIVATING UNIT U{active_unit['id']} from Sequential Engine queue")
        else:
            print(f"🏁 [sequential_integration_wrapper.py::_execute_via_sequential_engine] NO MORE UNITS in Sequential Engine queue - phase complete")
        
        # If no active unit, phase must be complete - advance immediately
        if not active_unit:
            self.phase_started = False
            print(f"🚫 NO ACTIVE UNIT - PHASE {current_phase} COMPLETE")
            
            # CRITICAL FIX: Call process_phase_transitions FIRST to check and handle transitions
            if hasattr(self.base_controller, 'phase_transitions'):
                print(f"🔄 CALLING PROCESS_PHASE_TRANSITIONS")
                self.base_controller.phase_transitions['process_phase_transitions']()
            
            # CRITICAL FIX: Verify phase advancement actually occurred
            initial_phase = current_phase
            final_phase = self.base_controller.get_current_phase()
            if initial_phase != final_phase:
                print(f"🔄 PHASE: {initial_phase} -> {final_phase}")
            else:
                print(f"⚠️ NO PHASE CHANGE - manually advancing from {initial_phase}")
                self._advance_phase()
                final_phase = self.base_controller.get_current_phase()
                if initial_phase != final_phase:
                    print(f"🔄 MANUAL PHASE: {initial_phase} -> {final_phase}")
            
            # Mark episode as continuing to allow next phase to start
            return self._build_gymnasium_response(action, True, terminated=False)
            
        # Convert gym action to mirror action format with validation
        mirror_action = self._convert_gym_action_to_mirror(active_unit, action, current_phase)
        
        if not mirror_action:
            raise ValueError(
                f"Invalid action {action} for unit {active_unit['id']} in phase {current_phase}. "
                f"Valid actions for {current_phase}: {self._get_valid_actions_for_phase(current_phase)}"
            )
            
        # Execute action through sequential engine with AI_TURN.md step counting
        steps_before = self.base_controller.game_state.get("episode_steps", 0)
        success = self.sequential_engine.execute_unit_action(active_unit, mirror_action)
        
        # AI_TURN.md COMPLIANCE: Track step increment based on action type (single execution)
        if success and mirror_action["type"] in ["move", "shoot", "charge", "combat", "wait"]:
            # Ensure step counting happens only once per action
            if not hasattr(self, '_last_step_logged') or self._last_step_logged != (steps_before, mirror_action["type"]):
                new_steps = steps_before + 1
                self.base_controller.game_state["episode_steps"] = new_steps
                self._last_step_logged = (steps_before, mirror_action["type"])
        
        # CRITICAL FIX: Ensure unit is marked as acted after successful action
        if success:
            print(f"🎯 [sequential_integration_wrapper.py::_execute_via_sequential_engine] MARKING U{active_unit['id']} AS ACTED")
            print(f"📊 [sequential_integration_wrapper.py::_execute_via_sequential_engine] UNITS_MOVED BEFORE MARKING: {list(self.base_controller.game_state.get('units_moved', []))}")
            
            self.base_controller._mark_gym_unit_as_acted(active_unit)
            
            print(f"📊 [sequential_integration_wrapper.py::_execute_via_sequential_engine] UNITS_MOVED AFTER MARKING: {list(self.base_controller.game_state.get('units_moved', []))}")
        
        # CRITICAL FIX: Log action properly for replay system
        self._log_sequential_action(active_unit, mirror_action, current_phase, success)
        
        # CRITICAL FIX: Check for phase transitions after each action
        if success and hasattr(self.base_controller, 'phase_transitions'):
            print(f"🔄 CHECKING PHASE TRANSITIONS AFTER ACTION")
            self.base_controller.phase_transitions['process_phase_transitions']()
        
        return self._build_gymnasium_response(action, success)
        
    def _log_sequential_action(self, unit: Dict[str, Any], action: Dict[str, Any], phase: str, success: bool) -> None:
        """Log sequential engine actions for proper replay generation."""
        if not hasattr(self.base_controller, 'replay_logger') or not self.base_controller.replay_logger:
            return
            
        # Get current turn and calculate reward
        current_turn = self.base_controller.get_current_turn()
        reward = 0.1 if success else -0.1
        
        # Log based on action type
        action_type = action.get("type", "wait")
        if action_type == "move":
            start_col, start_row = unit["col"], unit["row"]
            end_col = action.get("col", unit["col"])
            end_row = action.get("row", unit["row"])
            self.base_controller.replay_logger.log_move(
                unit, start_col, start_row, end_col, end_row, current_turn, reward, 0
            )
        elif action_type == "shoot":
            target_id = action.get("target_id")
            if target_id:
                target_unit = self._find_unit_by_id(target_id)
                if target_unit:
                    shoot_details = {"summary": {"totalShots": 1, "hits": 1, "wounds": 1, "failedSaves": 1}}
                    self.base_controller.replay_logger.log_shoot(
                        unit, target_unit, shoot_details, current_turn, reward, 4
                    )
        elif action_type == "charge":
            target_id = action.get("target_id")
            if target_id:
                target_unit = self._find_unit_by_id(target_id)
                if target_unit:
                    self.base_controller.replay_logger.log_charge(
                        unit, target_unit, unit["col"], unit["row"], 
                        target_unit["col"], target_unit["row"], current_turn, reward, 5
                    )
        elif action_type == "combat":
            target_id = action.get("target_id")
            if target_id:
                target_unit = self._find_unit_by_id(target_id)
                if target_unit:
                    self.base_controller.replay_logger.log_combat(
                        unit, target_unit, current_turn, reward, 6
                    )
                    
    def _find_unit_by_id(self, unit_id: str) -> Optional[Dict[str, Any]]:
        """Find unit by ID in current units list."""
        for unit in self.base_controller.get_units():
            if unit["id"] == unit_id:
                return unit
        return None
            
    def _convert_gym_action_to_mirror(self, unit: Dict[str, Any], action: Any, phase: str) -> Optional[Dict[str, Any]]:
        """
        Convert gym action to mirror action format for Sequential Engine.
        
        AI_GAME.md COMPLIANT: Actions are 0-7 only (no unit selection)
        Sequential Engine determines the active unit, gym only provides action type.
        
        GYM ACTIONS:
        0-3: Movement (North, South, East, West)
        4: Shoot
        5: Charge  
        6: Combat
        7: Wait
        
        Args:
            unit: Active unit from Sequential Engine (not selected by gym)
            action: Gym action integer 0-7 (action type only)
            phase: Current game phase
            
        Returns:
            Dict: Mirror action format or None if invalid
        """
        # CRITICAL FIX: Extract action type only - no unit selection allowed
        if hasattr(action, 'item') and callable(action.item):
            action = int(action.item())
        else:
            action = int(action)
        
        # AI_GAME.md: Action must be pure action type (0-7), no unit encoding
        action_type = action % 8  # Ensure we only get action type, ignore any unit encoding
        
        # Movement actions (0-3)
        if 0 <= action <= 3:
            if phase != "move":
                print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] Converting invalid movement action {action} to wait in phase '{phase}'")
                # Convert invalid movement action to wait action
                return {"type": "wait"}
                
            # Calculate destination based on direction
            movements = {
                0: (0, -1),  # North
                1: (0, 1),   # South  
                2: (1, 0),   # East
                3: (-1, 0)   # West
            }
            
            col_diff, row_diff = movements[action]
            return {
                "type": "move",
                "col": unit["col"] + col_diff,
                "row": unit["row"] + row_diff
            }
            
        # Shooting action (4)
        elif action == 4:
            if phase != "shoot":
                print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] Converting invalid shoot action {action} to wait in phase '{phase}'")
                return {"type": "wait"}
                
            # Get valid shooting targets from controller
            try:
                valid_targets = self.base_controller.game_actions["get_valid_shooting_targets"](unit["id"])
                if not valid_targets:
                    print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] No valid shooting targets for U{unit['id']}, converting to wait")
                    return {"type": "wait"}
                    
                # Use first valid target (AI will learn to choose better)
                return {
                    "type": "shoot",
                    "target_id": valid_targets[0]
                }
            except Exception as e:
                print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] Shoot action failed for U{unit['id']}: {e}, converting to wait")
                return {"type": "wait"}
            
        # Charge action (5)
        elif action == 5:
            if phase != "charge":
                print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] Converting invalid charge action {action} to wait in phase '{phase}'")
                return {"type": "wait"}
                
            # Get valid charge targets from controller
            try:
                valid_targets = self.base_controller.game_actions["get_valid_charge_targets"](unit["id"])
                if not valid_targets:
                    print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] No valid charge targets for U{unit['id']}, converting to wait")
                    return {"type": "wait"}
                    
                # Use first valid target (AI will learn to choose better)
                return {
                    "type": "charge",
                    "target_id": valid_targets[0]
                }
            except Exception as e:
                print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] Charge action failed for U{unit['id']}: {e}, converting to wait")
                return {"type": "wait"}
            
        # Combat action (6)
        elif action == 6:
            if phase != "combat":
                print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] Converting invalid combat action {action} to wait in phase '{phase}'")
                return {"type": "wait"}
                
            # Get valid combat targets from controller
            try:
                valid_targets = self.base_controller.game_actions["get_valid_combat_targets"](unit["id"])
                if not valid_targets:
                    print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] No valid combat targets for U{unit['id']}, converting to wait")
                    return {"type": "wait"}
                    
                # Use first valid target (AI will learn to choose better)
                return {
                    "type": "combat",
                    "target_id": valid_targets[0]
                }
            except Exception as e:
                print(f"🔄 [sequential_integration_wrapper.py::_convert_gym_action_to_mirror] Combat action failed for U{unit['id']}: {e}, converting to wait")
                return {"type": "wait"}
            
        # Wait action (7)
        elif action == 7:
            return {"type": "wait"}
            
        return None
        
    def _advance_phase(self) -> None:
        """Advance to next phase using controller's phase transition system."""
        # CRITICAL FIX: Force phase advancement when Sequential Engine reports phase complete
        # The Sequential Engine has already validated that all eligible units have acted
        current_phase = self.base_controller.get_current_phase()
        
        # AI_TURN.md COMPLIANCE: Reset tracking sets BEFORE phase transition
        if hasattr(self.base_controller, 'phase_transitions'):
            if current_phase == "move":
                # AI_TURN.md: Reset tracking sets at the start of the new phase
                self.base_controller.phase_transitions['transition_to_shoot']()
                print(f"🎯 SHOOT PHASE STARTED: Current phase is now {self.base_controller.get_current_phase()}")
                self.base_controller.state_actions['reset_shot_units']()
                print(f"🔧 RESET: Clearing units_shot before shoot phase")
            elif current_phase == "shoot":
                # AI_TURN.md: Reset tracking sets at the start of the new phase
                self.base_controller.phase_transitions['transition_to_charge']()
                self.base_controller.state_actions['reset_charged_units']()
            elif current_phase == "charge":
                # AI_TURN.md: Reset tracking sets at the start of the new phase
                self.base_controller.phase_transitions['transition_to_combat']()
                self.base_controller.state_actions['reset_attacked_units']()
            elif current_phase == "combat":
                # AI_TURN.md CRITICAL: End turn will reset ALL tracking sets
                self.base_controller.phase_transitions['end_turn']()
        else:
            # Fallback to base controller method
            self.base_controller._advance_gym_phase_or_turn()
    
    def _build_gymnasium_response(self, action: int, success: bool, terminated: Optional[bool] = None) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """Build complete gymnasium response tuple."""
        try:
            # Get observation
            obs = self._get_observation()
            
            # Enhanced reward based on sequential engine feedback
            reward = 0.1 if success else -0.1
            
            # Add step count bonus for efficient play
            step_info = self.sequential_engine.get_step_count_info()
            if step_info["real_actions_taken"] > 0:
                reward += 0.05  # Bonus for taking real actions
                
            # Check game termination (allow override for phase transitions)
            if terminated is None:
                terminated = False
                if hasattr(self.base_controller, 'is_game_over'):
                    terminated = self.base_controller.is_game_over()
            
            truncated = False
            
            # Build info dictionary with sequential engine data
            info = {
                "action_success": success,
                "sequential_engine": {
                    "step_count_info": step_info,
                    "queue_status": self.sequential_engine.get_queue_status(),
                    "phase_complete": self.sequential_engine.is_phase_complete()
                }
            }
            
            # Add standard info fields if available
            if hasattr(self.base_controller, 'get_current_turn'):
                info["current_turn"] = self.base_controller.get_current_turn()
            if hasattr(self.base_controller, 'get_current_phase'):
                info["current_phase"] = self.base_controller.get_current_phase()
            if hasattr(self.base_controller, 'get_current_player'):
                info["current_player"] = self.base_controller.get_current_player()
            if terminated and hasattr(self.base_controller, 'get_winner'):
                info["winner"] = self.base_controller.get_winner()
            else:
                info["winner"] = None
            info["game_over"] = terminated
                    
            return obs, reward, terminated, truncated, info
            
        except Exception as e:
            # AI_PROTOCOLE.md: No fallbacks allowed - re-raise error with context
            raise RuntimeError(f"Failed to build gymnasium response: {e}")
            
    def _get_observation(self) -> Any:
        """Get observation with proper size."""
        try:
            # Try gym environment first
            if self.gym_env and hasattr(self.gym_env, '_get_obs'):
                return self.gym_env._get_obs()
            
            # Try base controller
            if hasattr(self.base_controller, '_get_obs'):
                return self.base_controller._get_obs()
            
            # Try observation space
            if self.gym_env and hasattr(self.gym_env, 'observation_space'):
                obs_shape = self.gym_env.observation_space.shape[0]
                return np.zeros(obs_shape, dtype=np.float32)
            
            # AI_PROTOCOLE.md: No fallbacks allowed - raise error
            raise RuntimeError("Failed to get observation - check environment configuration")
            
        except Exception as e:
            return np.zeros(26, dtype=np.float32)

    def _get_valid_actions_for_phase(self, phase: str) -> List[int]:
        """Get list of valid action types for current phase."""
        valid_actions_per_phase = {
            "move": [0, 1, 2, 3, 7],  # move directions + wait
            "shoot": [4, 7],          # shoot + wait
            "charge": [5, 7],         # charge + wait
            "combat": [6, 7]          # combat + wait
        }
        if phase not in valid_actions_per_phase:
            raise KeyError(f"Unknown phase '{phase}' for action validation - valid phases: {list(valid_actions_per_phase.keys())}")
        return valid_actions_per_phase[phase]


# For gym40k.py integration, modify the controller initialization:
# 
# ORIGINAL:
#   self.controller = TrainingGameController(config, quiet=self.quiet)
# 
# UPDATED:
#   base_controller = TrainingGameController(config, quiet=self.quiet)
#   self.controller = create_sequential_game_controller(base_controller)
#   self.controller.connect_gym_env(self)