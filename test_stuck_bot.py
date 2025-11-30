#!/usr/bin/env python3
"""Test BotControlledEnv wrapper to find stuck issue."""
import sys
import os
sys.path.insert(0, 'e:/Dropbox/Informatique/Holberton/40k')
os.chdir('e:/Dropbox/Informatique/Holberton/40k')

print("1. Importing modules...", flush=True)
from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry
from ai.evaluation_bots import GreedyBot
from ai.env_wrappers import BotControlledEnv
from sb3_contrib.common.wrappers import ActionMasker
print("   Done", flush=True)

print("2. Creating environment stack...", flush=True)
unit_registry = UnitRegistry()
bot = GreedyBot(randomness=0.15)

base_env = W40KEngine(
    rewards_config='SpaceMarine_Infantry_Troop_RangedSwarm',
    training_config_name='default',
    controlled_agent='SpaceMarine_Infantry_Troop_RangedSwarm',
    scenario_file='config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_bot-1.json',
    unit_registry=unit_registry,
    quiet=True,
    gym_training_mode=True
)

def mask_fn(env):
    return env.get_action_mask()

masked_env = ActionMasker(base_env, mask_fn)
bot_env = BotControlledEnv(masked_env, bot, unit_registry)
print("   Done", flush=True)

print("3. Resetting environment...", flush=True)
obs, info = bot_env.reset()
print(f"   Done - obs shape: {obs.shape}", flush=True)

print("4. Getting engine reference...", flush=True)
engine = bot_env.engine
print(f"   Engine type: {type(engine)}", flush=True)

print("5. Taking steps with BotControlledEnv...", flush=True)
for i in range(20):
    phase = engine.game_state.get('phase', 'unknown')
    player = engine.game_state.get('current_player', 'unknown')
    turn = engine.game_state.get('turn', 1)

    mask = engine.get_action_mask()
    valid = [j for j in range(12) if mask[j]]

    print(f"   Step {i+1}: phase={phase}, player={player}, turn={turn}, valid={valid}", flush=True)

    if not valid:
        print(f"   NO VALID ACTIONS - this is the problem!", flush=True)
        break

    import random
    action = random.choice(valid)
    print(f"   Taking action {action}...", flush=True)

    obs, reward, terminated, truncated, info = bot_env.step(action)

    phase_after = engine.game_state.get('phase', 'unknown')
    player_after = engine.game_state.get('current_player', 'unknown')

    print(f"   Result: phase={phase_after}, player={player_after}, reward={reward:.3f}, done={terminated or truncated}", flush=True)

    if terminated or truncated:
        print(f"   Episode ended!", flush=True)
        break

print("6. Test complete!", flush=True)
