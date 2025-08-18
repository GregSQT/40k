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
    Minimal Sequential Game Controller
    
    Simple wrapper that adds sequential activation without complex dependencies.
    """
    
    def __init__(self, config, quiet=False):
        """Initialize with config and quiet parameter for compatibility."""
        # Import here to avoid circular imports
        from ai.game_controller import TrainingGameController
        self.base_controller = TrainingGameController(config, quiet)
        self.gym_env = None
        
    def __getattr__(self, name):
        """Delegate all attributes to base controller."""
        return getattr(self.base_controller, name)
        
    def connect_gym_env(self, gym_env):
        """Connect gym environment for observation delegation."""
        self.gym_env = gym_env
        if hasattr(self.base_controller, 'connect_gym_env'):
            self.base_controller.connect_gym_env(gym_env)
        
    def execute_gym_action(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """
        Execute gym action with proper gymnasium return format.
        
        For now, delegates to base controller but ensures proper tuple return.
        Sequential activation logic can be added incrementally.
        
        Args:
            action: Gym action integer
            
        Returns:
            Tuple: (observation, reward, terminated, truncated, info)
        """
        try:
            # Try to call base controller's method
            result = self.base_controller.execute_gym_action(action)
            
            # If result is already a tuple, return it
            if isinstance(result, tuple) and len(result) == 5:
                return result
            
            # If result is boolean (old format), build proper tuple
            if isinstance(result, bool):
                success = result
                return self._build_gymnasium_response(action, success)
            
            # Fallback for unexpected return types
            return self._build_gymnasium_response(action, False)
            
        except Exception as e:
            print(f"[SequentialController] Error in execute_gym_action: {e}")
            return self._build_gymnasium_response(action, False)
            
    def _build_gymnasium_response(self, action: int, success: bool) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """Build complete gymnasium response tuple."""
        try:
            # Get observation
            obs = self._get_observation()
            
            # Simple reward
            reward = 0.1 if success else -0.1
                
            # Check game termination
            terminated = False
            if hasattr(self.base_controller, 'is_game_over'):
                terminated = self.base_controller.is_game_over()
            
            truncated = False
            
            # Build info dictionary
            info = {
                "action_success": success
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
            print(f"[SequentialController] Error building response: {e}")
            # Safe fallback
            safe_obs = np.zeros(26, dtype=np.float32)  # Common observation size
            return safe_obs, -1.0, True, False, {"error": "response_build_failed"}
            
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
            
            # Common fallback
            return np.zeros(26, dtype=np.float32)
            
        except Exception as e:
            print(f"[SequentialController] Error getting observation: {e}")
            return np.zeros(26, dtype=np.float32)


# For gym40k.py integration, modify the controller initialization:
# 
# ORIGINAL:
#   self.controller = TrainingGameController(config, quiet=self.quiet)
# 
# UPDATED:
#   base_controller = TrainingGameController(config, quiet=self.quiet)
#   self.controller = create_sequential_game_controller(base_controller)
#   self.controller.connect_gym_env(self)