"""Debug fight phase pool handling."""

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
print("DEBUG: FIGHT PHASE POOLS")
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

obs, info = env.reset()

def print_state():
    gs = env.engine.game_state
    print(f"  Turn: {gs['turn']}, Phase: {gs['phase']}, Player: {gs['current_player']}")
    print(f"  fight_subphase: {gs.get('fight_subphase')}")
    print(f"  charging_pool: {gs.get('charging_activation_pool', [])}")
    print(f"  active_alt_pool: {gs.get('active_alternating_activation_pool', [])}")
    print(f"  non_active_alt_pool: {gs.get('non_active_alternating_activation_pool', [])}")
    action_mask = env.engine.get_action_mask()
    valid = np.where(action_mask)[0]
    print(f"  Valid actions: {list(valid)}")

    # Get eligible units
    eligible = env.engine.action_decoder._get_eligible_units_for_current_phase(gs)
    print(f"  Eligible units: {[u['id'] for u in eligible if u]}")
    print()

print("Initial state:")
print_state()

done = False
step_count = 0
max_steps = 50

while not done and step_count < max_steps:
    action_mask = env.engine.get_action_mask()
    valid_actions = np.where(action_mask)[0]

    if len(valid_actions) == 0:
        print(f"Step {step_count}: NO VALID ACTIONS!")
        print_state()
        break

    action = valid_actions[0]
    phase_before = env.engine.game_state["phase"]

    obs, reward, terminated, truncated, info = env.step(action)
    done = terminated or truncated
    step_count += 1

    phase_after = env.engine.game_state["phase"]

    # Only print on phase transition or if fight phase
    if phase_after != phase_before or phase_after == "fight":
        print(f"Step {step_count}: {phase_before} -> {phase_after}")
        print_state()

print(f"\nFinal state after {step_count} steps:")
print(f"  terminated: {terminated}")
print(f"  game_over: {env.engine.game_state.get('game_over')}")
print(f"  winner: {info.get('winner')}")

env.close()
print("Done!")
