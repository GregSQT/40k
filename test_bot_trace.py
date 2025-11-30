"""Trace exactly where the game gets stuck."""

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
print("TRACE: Find where game gets stuck")
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
max_steps = 100

while not done and step_count < max_steps:
    # Before step - get state
    phase_before = env.engine.game_state['phase']
    player_before = env.engine.game_state['current_player']
    turn_before = env.engine.game_state['turn']

    action_mask = env.engine.get_action_mask()
    valid_actions = np.where(action_mask)[0]

    if len(valid_actions) == 0:
        print(f"\n>>> Step {step_count}: NO VALID ACTIONS FOR AGENT!")
        print(f"  Phase: {phase_before}")
        print(f"  Player: {player_before}")
        print(f"  Turn: {turn_before}")

        # Print pool states
        pools = {
            'move_activation_pool': env.engine.game_state.get('move_activation_pool', []),
            'shoot_activation_pool': env.engine.game_state.get('shoot_activation_pool', []),
            'charge_activation_pool': env.engine.game_state.get('charge_activation_pool', []),
            'charging_activation_pool': env.engine.game_state.get('charging_activation_pool', []),
            'active_alternating_activation_pool': env.engine.game_state.get('active_alternating_activation_pool', []),
            'non_active_alternating_activation_pool': env.engine.game_state.get('non_active_alternating_activation_pool', []),
        }
        print(f"  Pools: {pools}")
        break

    action = valid_actions[0]

    # Print every step to trace progress
    print(f"Step {step_count}: Turn {turn_before}, phase={phase_before}, player={player_before}, action={action}, valid={list(valid_actions[:3])}")

    try:
        obs, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        step_count += 1

        # Check for state change
        phase_after = env.engine.game_state['phase']
        player_after = env.engine.game_state['current_player']
        turn_after = env.engine.game_state['turn']

        if phase_after != phase_before or turn_after != turn_before:
            print(f"  -> Phase/Turn changed: {phase_before}->{phase_after}, Turn {turn_before}->{turn_after}")

    except Exception as e:
        print(f"\n>>> ERROR at step {step_count}: {e}")
        import traceback
        traceback.print_exc()
        break

print(f"\nCompleted {step_count} steps")
print(f"  terminated: {done}")
print(f"  final phase: {env.engine.game_state.get('phase')}")
print(f"  final turn: {env.engine.game_state.get('turn')}")
print(f"  winner: {info.get('winner', 'N/A')}")
env.close()
print("Test done!")
