#!/usr/bin/env python3
"""Test fight phase specifically to find stuck issue."""
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
engine = bot_env.engine
print(f"   Done", flush=True)

print("4. Taking steps with detailed fight phase logging...", flush=True)
for i in range(100):
    phase = engine.game_state.get('phase', 'unknown')
    player = engine.game_state.get('current_player', 'unknown')
    turn = engine.game_state.get('turn', 1)

    mask = engine.get_action_mask()
    valid = [j for j in range(12) if mask[j]]

    # Extra debug for fight phase
    fight_info = ""
    if phase == "fight":
        charging = engine.game_state.get('charging_activation_pool', [])
        active_alt = engine.game_state.get('active_alternating_activation_pool', [])
        non_active_alt = engine.game_state.get('non_active_alternating_activation_pool', [])
        subphase = engine.game_state.get('fight_subphase', 'unknown')
        units_fought = engine.game_state.get('units_fought', set())
        units_charged = engine.game_state.get('units_charged', set())
        active_fight_unit = engine.game_state.get('active_fight_unit', None)
        fight_info = f"\n      fight_subphase={subphase}\n      charging_pool={charging}\n      active_alt_pool={active_alt}\n      non_active_alt_pool={non_active_alt}\n      units_fought={units_fought}\n      units_charged={units_charged}\n      active_fight_unit={active_fight_unit}"

    print(f"   Step {i+1}: phase={phase}, player={player}, turn={turn}, valid={valid}{fight_info}", flush=True)

    if not valid:
        print(f"   NO VALID ACTIONS!", flush=True)
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

print("5. Test complete!", flush=True)
