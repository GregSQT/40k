"""Test that 0_critical metrics are being logged."""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.path.insert(0, '.')

from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry
from ai.metrics_tracker import W40KMetricsTracker
from ai.training_callbacks import MetricsCollectionCallback
from ai.env_wrappers import BotControlledEnv
from ai.evaluation_bots import GreedyBot
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import CallbackList
import numpy as np
import os
import shutil

print("=" * 60)
print("TESTING 0_critical METRICS COLLECTION")
print("=" * 60)

# Clean test tensorboard dir
test_tb_dir = "./tensorboard/test_metrics"
if os.path.exists(test_tb_dir):
    shutil.rmtree(test_tb_dir)

# Create environment
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
bot_env = BotControlledEnv(masked_env, training_bot, unit_registry)
env = Monitor(bot_env)

print("Creating model...")
model = MaskablePPO(
    'MlpPolicy',
    env,
    verbose=0,
    n_steps=256,
    batch_size=64,
    tensorboard_log=test_tb_dir
)

print("Creating metrics tracker...")
metrics_tracker = W40KMetricsTracker("test_agent", test_tb_dir)

print("Creating MetricsCollectionCallback...")
metrics_callback = MetricsCollectionCallback(
    metrics_tracker,
    model,
    controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm"
)

print("Training for 50 episodes worth of timesteps (~2500)...")

# DEBUG: Add a debug callback to see info dict
from stable_baselines3.common.callbacks import BaseCallback
class DebugCallback(BaseCallback):
    def __init__(self):
        super().__init__()
        self.debug_count = 0
        self.episode_ends_seen = 0

    def _on_step(self):
        if 'infos' in self.locals:
            for info in self.locals['infos']:
                # Check for actual episode end (winner is NOT None)
                winner = info.get('winner')
                if winner is not None and winner != 'None' and str(winner) != 'None':  # winner is 0, 1, or -1
                    self.episode_ends_seen += 1
                    print(f"  [EPISODE END #{self.episode_ends_seen}] winner={winner} (type={type(winner).__name__}), terminated={info.get('TimeLimit.truncated', 'N/A')}")
                    if 'episode' in info:
                        print(f"    episode info: {info['episode']}")
                    # Print first 5 then every 50
                    if self.episode_ends_seen > 5:
                        return True

                # Also check for 'episode' key (SB3 Monitor wrapper)
                if 'episode' in info and self.debug_count < 3:
                    print(f"  [MONITOR EPISODE] {info['episode']}")
                    self.debug_count += 1

        # Check dones - only first 3
        if 'dones' in self.locals and self.episode_ends_seen < 3:
            dones = self.locals['dones']
            if any(dones):
                print(f"  [DONE SIGNAL] dones={dones}")

        return True

# Skip manual test - go straight to PPO training

print("\nNow training with PPO...")
model.learn(
    total_timesteps=20000,  # More timesteps to get episodes to complete
    callback=CallbackList([metrics_callback, DebugCallback()]),
    log_interval=10,
    progress_bar=False
)

print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)

print(f"\nEpisode count: {metrics_tracker.episode_count}")
print(f"All episode rewards: {len(metrics_tracker.all_episode_rewards)}")
print(f"Win rate window: {len(metrics_tracker.win_rate_window)}")

print(f"\nHyperparameter tracking:")
print(f"  clip_fractions: {len(metrics_tracker.hyperparameter_tracking['clip_fractions'])}")
print(f"  approx_kls: {len(metrics_tracker.hyperparameter_tracking['approx_kls'])}")
print(f"  explained_variances: {len(metrics_tracker.hyperparameter_tracking['explained_variances'])}")
print(f"  entropy_losses: {len(metrics_tracker.hyperparameter_tracking['entropy_losses'])}")
print(f"  policy_losses: {len(metrics_tracker.hyperparameter_tracking['policy_losses'])}")
print(f"  value_losses: {len(metrics_tracker.hyperparameter_tracking['value_losses'])}")

print(f"\n0_critical metrics should be logged if:")
print(f"  - episode_count >= 20: {metrics_tracker.episode_count >= 20}")
print(f"  - clip_fractions >= 20: {len(metrics_tracker.hyperparameter_tracking['clip_fractions']) >= 20}")

# Check if metrics were actually written
import glob
event_files = glob.glob(f"{test_tb_dir}/**/*events*", recursive=True)
print(f"\nTensorBoard event files: {len(event_files)}")
for f in event_files:
    print(f"  - {f}")

env.close()
print("\nDone!")
