"""Test actual training environment fight phase."""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry
import numpy as np


def main():
    print("=" * 60)
    print("TRAINING ENVIRONMENT FIGHT PHASE TEST")
    print("=" * 60)

    # Create unit registry like train.py does
    unit_registry = UnitRegistry()

    # Create environment using the actual training path
    env = W40KEngine(
        controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
        quiet=False,
        rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm",
        training_config_name="default",
        scenario_file="config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_bot-1.json",
        unit_registry=unit_registry,
        gym_training_mode=True
    )

    # Reset to get initial state
    obs, info = env.reset()
    game_state = env.game_state

    print(f"\nInitial state:")
    print(f"  Phase: {game_state['phase']}")
    print(f"  Turn: {game_state['turn']}")
    print(f"  Player: {game_state['current_player']}")
    main._last_turn = game_state['turn']

    # Run steps until we get to fight phase
    max_steps = 500
    step_count = 0
    done = False

    while not done and step_count < max_steps:
        phase = game_state["phase"]
        charging_pool = game_state.get("charging_activation_pool", [])
        active_pool = game_state.get("active_alternating_activation_pool", [])
        non_active_pool = game_state.get("non_active_alternating_activation_pool", [])

        # Print turn transitions only
        current_turn = game_state.get("turn", 1)
        if hasattr(main, '_last_turn') and main._last_turn != current_turn:
            print(f"\n=== TURN {current_turn} (step {step_count}) ===")
        main._last_turn = current_turn

        # Debug: Print phase transitions
        player = game_state.get("current_player", 0)
        if not hasattr(main, '_last_phase') or main._last_phase != phase:
            print(f"[step {step_count}] T{current_turn}P{player} Phase: {phase}")
            main._last_phase = phase

        # Debug: Print fight phase status periodically
        if phase == "fight" and step_count % 20 == 0:
            print(f"  fight: charging={len(charging_pool)}, non_active={len(non_active_pool)}")

        # Take action
        action_mask = env.get_action_mask()
        valid_actions = np.where(action_mask)[0]

        if len(valid_actions) == 0:
            print(f"\n!!! NO VALID ACTIONS at step {step_count}, phase={phase}")
            print(f"    action_mask: {action_mask}")
            break

        # Take first valid action
        action = valid_actions[0]

        # Take step
        obs, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated

        if done:
            print(f"\n=== EPISODE ENDED at step {step_count} ===")
            print(f"  Terminated: {terminated}")
            print(f"  Truncated: {truncated}")
            print(f"  Final turn: {game_state.get('turn', 'N/A')}")
            print(f"  Game over: {game_state.get('game_over', False)}")
            print(f"  Winner: {info.get('winner', 'N/A')}")

        step_count += 1

    print(f"\nTest completed after {step_count} steps")
    print(f"  Final phase: {game_state['phase']}")
    print(f"  Final turn: {game_state['turn']}")
    print(f"  Done: {done}")


if __name__ == "__main__":
    main()
