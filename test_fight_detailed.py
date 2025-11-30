"""Detailed test of fight phase pool removal."""

import sys
sys.path.insert(0, '.')

from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry
from engine.phase_handlers import fight_handlers
from engine.phase_handlers.generic_handlers import end_activation
import numpy as np

# Monkey patch to trace calls
original_end_activation = end_activation

def traced_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5):
    print(f"\n>>> END_ACTIVATION TRACED:")
    unit_id = unit.get('id') if unit else 'None'
    print(f"    unit_id = {repr(unit_id)} (type: {type(unit_id).__name__})")
    print(f"    arg4 = {arg4} (Remove from pool type)")
    charging_pool = game_state.get('charging_activation_pool', [])
    print(f"    BEFORE - charging_pool: {charging_pool}")
    if charging_pool:
        print(f"             pool item types: {[type(x).__name__ for x in charging_pool]}")
        print(f"             unit_id in pool: {unit_id in charging_pool}")
        print(f"             str(unit_id) in pool: {str(unit_id) in charging_pool}")

    result = original_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)

    print(f"    AFTER  - charging_pool: {game_state.get('charging_activation_pool', [])}")
    print(f"    result keys: {list(result.keys())}")
    return result

# Apply patch
import engine.phase_handlers.generic_handlers as gh
gh.end_activation = traced_end_activation
import engine.phase_handlers.fight_handlers as fh
fh.end_activation = traced_end_activation

# Also trace _handle_fight_unit_activation
original_activation = fh._handle_fight_unit_activation

def traced_activation(game_state, unit, config):
    unit_id = unit.get('id') if unit else 'None'
    print(f"\n>>> _handle_fight_unit_activation called for unit {unit_id}")
    result = original_activation(game_state, unit, config)
    print(f"    result: success={result[0]}, keys={list(result[1].keys())}")
    return result

fh._handle_fight_unit_activation = traced_activation

# Also trace _handle_fight_attack
original_attack = fh._handle_fight_attack

def traced_attack(game_state, unit, target_id, config):
    unit_id = unit.get('id') if unit else 'None'
    print(f"\n>>> _handle_fight_attack called for unit {unit_id} targeting {target_id}")
    result = original_attack(game_state, unit, target_id, config)
    print(f"    result: success={result[0]}, keys={list(result[1].keys())}")
    return result

fh._handle_fight_attack = traced_attack


def main():
    print("=" * 60)
    print("DETAILED FIGHT PHASE TEST")
    print("=" * 60)

    unit_registry = UnitRegistry()
    env = W40KEngine(
        controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
        quiet=False,
        rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm",
        training_config_name="default",
        scenario_file="config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_bot-1.json",
        unit_registry=unit_registry,
        gym_training_mode=True
    )

    obs, info = env.reset()
    game_state = env.game_state

    # Skip to fight phase
    max_steps = 50
    step_count = 0
    done = False

    while not done and step_count < max_steps:
        phase = game_state["phase"]

        # Only detailed output for fight phase
        if phase == "fight":
            print(f"\n{'='*40}")
            print(f"FIGHT STEP {step_count}")
            print(f"{'='*40}")
            print(f"active_fight_unit: {game_state.get('active_fight_unit')}")

        action_mask = env.get_action_mask()
        valid_actions = np.where(action_mask)[0]

        if len(valid_actions) == 0:
            print(f"NO VALID ACTIONS - stopping")
            break

        action = valid_actions[0]

        if phase == "fight":
            charging_pool = game_state.get("charging_activation_pool", [])
            print(f"Pre-step: charging_pool = {charging_pool}")
            print(f"Taking action {action}")

        obs, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated

        if phase == "fight":
            new_pool = game_state.get("charging_activation_pool", [])
            print(f"Post-step: charging_pool = {new_pool}")
            if charging_pool == new_pool and len(charging_pool) > 0:
                print("!!! POOL UNCHANGED !!!")

        step_count += 1

        # Stop after 5 fight steps for brevity
        if phase == "fight" and step_count > 20:
            break

    print(f"\nCompleted {step_count} steps")


if __name__ == "__main__":
    main()
