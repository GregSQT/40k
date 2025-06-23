import gymnasium as gym
from gymnasium import spaces
import numpy as np
from backend.game.core import GameState  # You define

class WH40KEnv(gym.Env):
    def __init__(self, board_shape=(18, 24)):
        super().__init__()
        self.board_shape = board_shape
        self.state = GameState(board_shape)
        self.observation_space = spaces.Box(
            low=0, high=max(board_shape), shape=(self.state.obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(self.state.action_count)

    def reset(self, *, seed=None, options=None):
        self.state.reset()
        return self.state.observe(), {}

    def step(self, action):
        obs, reward, terminated, info = self.state.apply_action(action)
        return obs, reward, terminated, False, info
