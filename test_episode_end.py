"""Test why episodes don't end."""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.path.insert(0, '.')

from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry
import numpy as np

print("=" * 60)
print("TESTING EPISODE TERMINATION")
print("=" * 60)

unit_registry = UnitRegistry()
scenario_file = "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_bot-1.json"

env = W40KEngine(
    controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
    quiet=True,
    rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm",
    training_config_name="default",
    scenario_file=scenario_file,
    unit_registry=unit_registry,
    gym_training_mode=True
)

obs, info = env.reset()

print(f"Training config: {env.training_config}")
print(f"Max turns: {env.training_config.get('max_turns_per_episode')}")

done = False
step = 0
max_steps = 2000  # More than enough for 5 turns

while not done and step < max_steps:
    action_mask = env.get_action_mask()
    valid_actions = np.where(action_mask)[0]

    if len(valid_actions) == 0:
        print(f"Step {step}: NO VALID ACTIONS!")
        break

    action = valid_actions[0]
    obs, reward, terminated, truncated, info = env.step(action)
    done = terminated or truncated
    step += 1

    # Print status every 100 steps
    if step % 100 == 0:
        turn = env.game_state.get("turn", 1)
        phase = env.game_state.get("phase", "?")
        player = env.game_state.get("current_player", 0)
        game_over = env.game_state.get("game_over", False)
        print(f"  Step {step}: turn={turn}, phase={phase}, player={player}, game_over={game_over}")

    # Check for turn changes
    if 'phase_transition' in info and info.get('next_phase') == 'move':
        turn = env.game_state.get("turn", 1)
        player = env.game_state.get("current_player", 0)
        if player == 0:
            print(f"  [Turn {turn}] Player 0 starts movement phase at step {step}")

print(f"\nFinal state after {step} steps:")
print(f"  terminated: {terminated}")
print(f"  truncated: {truncated}")
print(f"  game_over: {env.game_state.get('game_over')}")
print(f"  turn: {env.game_state.get('turn')}")
print(f"  winner: {info.get('winner')}")

# Check living units
living_by_player = {}
for unit in env.game_state["units"]:
    if unit["HP_CUR"] > 0:
        p = unit["player"]
        living_by_player[p] = living_by_player.get(p, 0) + 1
print(f"  Living units: {living_by_player}")

env.close()
print("Done!")
