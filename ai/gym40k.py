#!/usr/bin/env python3
"""
Minimal working gym40k.py for testing
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
import json
import os

class W40KEnv(gym.Env):
    """Minimal working W40K environment for testing."""
    
    def __init__(self):
        super().__init__()
        
        # Simple observation and action spaces
        self.observation_space = spaces.Box(
            low=0, high=100, shape=(28,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(8)
        
        # Simple unit data
        self.units = [
            {"id": 1, "player": 0, "col": 5, "row": 5, "cur_hp": 3, "alive": True},
            {"id": 2, "player": 0, "col": 7, "row": 5, "cur_hp": 4, "alive": True},
            {"id": 3, "player": 1, "col": 15, "row": 10, "cur_hp": 3, "alive": True},
            {"id": 4, "player": 1, "col": 17, "row": 10, "cur_hp": 4, "alive": True}
        ]
        
        self.board_size = (24, 18)
        self.game_over = False
        self.winner = None
        self.turn = 0
        
    def reset(self, *, seed=None, options=None):
        """Reset the environment."""
        super().reset(seed=seed)
        
        # Reset units
        for unit in self.units:
            unit["alive"] = True
            unit["cur_hp"] = 3 if unit["id"] in [1, 3] else 4
        
        self.game_over = False
        self.winner = None
        self.turn = 0
        
        obs = self._get_obs()
        return obs, {}
    
    def step(self, action):
        """Execute one step."""
        # Simple step logic
        obs = self._get_obs()
        reward = np.random.random() - 0.5  # Random reward for testing
        terminated = self.turn > 50  # End after 50 turns
        truncated = False
        info = {"winner": None}
        
        self.turn += 1
        
        return obs, reward, terminated, truncated, info
    
    def _get_obs(self):
        """Get observation."""
        obs = []
        for unit in self.units:
            obs.extend([
                unit["player"], unit["col"], unit["row"], unit["cur_hp"],
                6, 8, 2  # move, range, damage
            ])
        return np.array(obs, dtype=np.float32)
    
    def close(self):
        """Clean up."""
        pass
    
    def did_win(self):
        """Check if AI won."""
        return self.winner == 1

# Test the environment
if __name__ == "__main__":
    print("Testing minimal W40KEnv...")
    env = W40KEnv()
    obs, _ = env.reset()
    print(f"Observation shape: {obs.shape}")
    print(f"Action space: {env.action_space}")
    
    for i in range(5):
        action = env.action_space.sample()
        obs, reward, done, truncated, info = env.step(action)
        print(f"Step {i+1}: action={action}, reward={reward:.3f}")
        if done or truncated:
            break
    
    env.close()
    print("✓ Minimal environment test passed!")
