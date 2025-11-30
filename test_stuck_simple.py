#!/usr/bin/env python3
"""Simple test to debug training stuck issue."""
import sys
import os
sys.path.insert(0, 'e:/Dropbox/Informatique/Holberton/40k')
os.chdir('e:/Dropbox/Informatique/Holberton/40k')

print("1. Importing modules...", flush=True)
from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry
print("   Done", flush=True)

print("2. Creating unit registry...", flush=True)
unit_registry = UnitRegistry()
print("   Done", flush=True)

print("3. Creating W40KEngine...", flush=True)
base_env = W40KEngine(
    rewards_config='SpaceMarine_Infantry_Troop_RangedSwarm',
    training_config_name='default',
    controlled_agent='SpaceMarine_Infantry_Troop_RangedSwarm',
    scenario_file='config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_bot-1.json',
    unit_registry=unit_registry,
    quiet=True,
    gym_training_mode=True
)
print("   Done", flush=True)

print("4. Resetting environment...", flush=True)
obs, info = base_env.reset()
print(f"   Done - obs shape: {obs.shape}", flush=True)

print("5. Taking steps with base engine directly...", flush=True)
for i in range(20):
    phase = base_env.game_state.get('phase', 'unknown')
    player = base_env.game_state.get('current_player', 'unknown')
    turn = base_env.game_state.get('turn', 1)

    mask = base_env.get_action_mask()
    valid = [j for j in range(12) if mask[j]]

    print(f"   Step {i+1}: phase={phase}, player={player}, turn={turn}, valid={valid}", flush=True)

    if not valid:
        print(f"   NO VALID ACTIONS - this is the problem!", flush=True)
        break

    import random
    action = random.choice(valid)
    print(f"   Taking action {action}...", flush=True)

    obs, reward, terminated, truncated, info = base_env.step(action)

    print(f"   Result: reward={reward:.3f}, done={terminated or truncated}", flush=True)

    if terminated or truncated:
        print(f"   Episode ended!", flush=True)
        break

print("6. Test complete!", flush=True)
