"""Quick test of BotControlledEnv to see what's happening."""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.path.insert(0, '.')

from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry
from ai.env_wrappers import BotControlledEnv
from ai.evaluation_bots import GreedyBot
from sb3_contrib.common.wrappers import ActionMasker
import numpy as np

print("=" * 60)
print("TEST: BotControlledEnv quick check")
print("=" * 60)

unit_registry = UnitRegistry()
scenario_file = "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_bot-1.json"

base_env = W40KEngine(
    controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
    quiet=True,
    rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm",
    training_config_name="default",
    scenario_file=scenario_file,
    unit_registry=unit_registry,
    gym_training_mode=True
)

def mask_fn(env):
    return env.get_action_mask()

masked_env = ActionMasker(base_env, mask_fn)
training_bot = GreedyBot(randomness=0.15)
env = BotControlledEnv(masked_env, training_bot, unit_registry)

print("Resetting environment...")
obs, info = env.reset()
print(f"Reset complete. Phase: {env.engine.game_state['phase']}")

done = False
step_count = 0
max_steps = 200

while not done and step_count < max_steps:
    # Get action mask for agent action
    action_mask = env.engine.get_action_mask()
    valid_actions = np.where(action_mask)[0]

    if len(valid_actions) == 0:
        print(f"Step {step_count}: NO VALID ACTIONS FOR AGENT!")
        print(f"  Phase: {env.engine.game_state['phase']}")
        print(f"  Player: {env.engine.game_state['current_player']}")
        break

    action = valid_actions[0]

    # Debug every 20 steps
    if step_count % 20 == 0:
        print(f"Step {step_count}: phase={env.engine.game_state['phase']}, player={env.engine.game_state['current_player']}, action={action}")

    obs, reward, terminated, truncated, info = env.step(action)
    done = terminated or truncated
    step_count += 1

print(f"\nCompleted {step_count} steps")
print(f"  terminated: {terminated if 'terminated' in dir() else 'N/A'}")
print(f"  winner: {info.get('winner', 'N/A')}")
env.close()
print("Test done!")
