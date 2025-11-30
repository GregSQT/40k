"""Debug why game is stuck in Player 1 shooting phase."""

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
print("DEBUG: WHY GAME IS STUCK")
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

print(f"Initial state:")
print(f"  Turn: {env.engine.game_state['turn']}")
print(f"  Phase: {env.engine.game_state['phase']}")
print(f"  Player: {env.engine.game_state['current_player']}")
print(f"  game_over: {env.engine.game_state['game_over']}")

done = False
step_count = 0
max_steps = 200

print("\nStepping through...")
while not done and step_count < max_steps:
    action_mask = env.engine.get_action_mask()
    valid_actions = np.where(action_mask)[0]

    if len(valid_actions) == 0:
        print(f"Step {step_count}: NO VALID ACTIONS!")
        print(f"  Phase: {env.engine.game_state['phase']}")
        print(f"  Player: {env.engine.game_state['current_player']}")
        print(f"  Pools:")
        print(f"    move_activation_pool: {env.engine.game_state.get('move_activation_pool', [])}")
        print(f"    shoot_activation_pool: {env.engine.game_state.get('shoot_activation_pool', [])}")
        print(f"    charge_activation_pool: {env.engine.game_state.get('charge_activation_pool', [])}")
        print(f"    fight_activation_pool: {env.engine.game_state.get('fight_activation_pool', [])}")
        break

    # Take first valid action
    action = valid_actions[0]

    # Debug: Print state before step if it's Player 0's turn and shooting phase
    if env.engine.game_state["current_player"] == 0:
        phase = env.engine.game_state["phase"]
        turn = env.engine.game_state["turn"]
        if step_count % 20 == 0:
            print(f"  Step {step_count}: Turn {turn}, phase={phase}, player=0, action={action}, valid={list(valid_actions[:5])}")

    obs, reward, terminated, truncated, info = env.step(action)
    done = terminated or truncated
    step_count += 1

    # Check for phase transitions
    if 'phase_transition' in info:
        print(f"  PHASE TRANSITION at step {step_count}: {info.get('next_phase')}")

    # Debug: Print when turn changes
    current_turn = env.engine.game_state.get("turn", 1)
    if 'winner' in info and info['winner'] is not None:
        print(f"  EPISODE END at step {step_count}: winner={info['winner']}")

print(f"\nFinal state after {step_count} steps:")
print(f"  terminated: {terminated}")
print(f"  truncated: {truncated}")
print(f"  game_over: {env.engine.game_state.get('game_over')}")
print(f"  turn: {env.engine.game_state.get('turn')}")
print(f"  phase: {env.engine.game_state.get('phase')}")
print(f"  player: {env.engine.game_state.get('current_player')}")
print(f"  winner: {info.get('winner')}")

# Check living units
living_by_player = {}
for unit in env.engine.game_state["units"]:
    if unit["HP_CUR"] > 0:
        p = unit["player"]
        living_by_player[p] = living_by_player.get(p, 0) + 1
print(f"  Living units: {living_by_player}")

env.close()
print("Done!")
