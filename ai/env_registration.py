# ai/env_registration.py
from gymnasium.envs.registration import register

register(
    id="W40KEnv-v0",
    entry_point="ai.gym40k:W40KEnv",
)