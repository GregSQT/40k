#!/usr/bin/env python3
"""
ai/training/gym_interface.py - Minimal Translation Layer for W40KEngine

PURPOSE: Enable training with existing ML libraries
ARCHITECTURAL CONSTRAINT: Zero game logic, pure translation only
"""

import gymnasium as gym
import numpy as np
import sys
import os
from typing import Dict, Any, Tuple
from shared.data_validation import require_key

# Fix import paths for your project structure
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

from engine.w40k_core import W40KEngine

class W40KGymEnv(gym.Env):
    """Minimal gym interface for W40KEngine - translation layer only."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        
        # Direct delegation to compliant engine
        self.engine = W40KEngine(config)
        
        # Gym interface requirements
        self.action_space = gym.spaces.Discrete(8)
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(100,), dtype=np.float32
        )
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """Translate gym integer to semantic action and delegate."""
        
        # Get active unit from engine
        active_unit = self._get_active_unit()
        if not active_unit:
            semantic_action = {"action": "skip", "unitId": "none"}
        else:
            semantic_action = self._translate_action(action, active_unit)
        
        # Direct delegation to engine
        success, result = self.engine.step(semantic_action)
        
        # Build response
        obs = np.array(self.engine._build_observation(), dtype=np.float32)
        reward = self.engine._calculate_reward(success, result)
        terminated = self.engine.game_state["game_over"]
        
        return obs, reward, terminated, False, {
            "success": success,
            "result": result,
            "phase": self.engine.game_state["phase"]
        }
    
    def _translate_action(self, action: int, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Pure translation: gym integer to semantic action."""
        
        if action == 0:  # North
            return {
                "action": "move",
                "unitId": unit["id"],
                "destCol": unit["col"],
                "destRow": unit["row"] - 1
            }
        elif action == 1:  # South
            return {
                "action": "move",
                "unitId": unit["id"],
                "destCol": unit["col"],
                "destRow": unit["row"] + 1
            }
        elif action == 2:  # East
            return {
                "action": "move",
                "unitId": unit["id"],
                "destCol": unit["col"] + 1,
                "destRow": unit["row"]
            }
        elif action == 3:  # West
            return {
                "action": "move",
                "unitId": unit["id"],
                "destCol": unit["col"] - 1,
                "destRow": unit["row"]
            }
        else:  # Skip/wait
            return {"action": "skip", "unitId": unit["id"]}
    
    def _get_active_unit(self) -> Dict[str, Any]:
        """Get active unit from engine."""
        pool = require_key(self.engine.game_state, "move_activation_pool")
        if pool:
            return self.engine._get_unit_by_id(pool[0])
        return None
    
    def reset(self, seed=None, options=None) -> Tuple[np.ndarray, Dict]:
        """Reset engine and return observation."""
        self.engine.reset(seed, options)
        obs = np.array(self.engine._build_observation(), dtype=np.float32)
        return obs, {"phase": self.engine.game_state["phase"]}