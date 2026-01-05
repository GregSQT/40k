#!/usr/bin/env python3
"""
Profile training performance to identify bottlenecks.
Usage: python check/profile_training.py
"""

import cProfile
import pstats
import io
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader
from ai.unit_registry import UnitRegistry

def profile_training_step():
    """Profile a single training episode to find bottlenecks."""

    # Setup
    config = get_config_loader()
    unit_registry = UnitRegistry()

    # Import environment
    from stable_baselines3.common.env_checker import check_env
    from gymnasium.wrappers import TimeLimit
    from sb3_contrib.common.wrappers import ActionMasker

    # Load actual training config
    agent_key = "SpaceMarine_Infantry_Troop_RangedSwarm"
    training_config_name = "phase1"
    rewards_config_name = "SpaceMarine_Infantry_Troop_RangedSwarm_phase1"

    # Get scenario
    scenario_file = "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-1.json"

    # Import engine
    from engine.w40k_core import W40KEngine

    print("🔍 Creating environment...")
    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True
    )

    def mask_fn(env):
        return env.get_action_mask()

    env = ActionMasker(base_env, mask_fn)

    print("🏃 Running profiled episodes...")

    # Profile 10 episodes
    profiler = cProfile.Profile()
    profiler.enable()

    for episode in range(10):
        obs, info = env.reset()
        done = False
        steps = 0

        while not done:
            # Get valid actions
            mask = env.action_masks()

            # Random valid action
            valid_actions = [i for i, valid in enumerate(mask) if valid]
            if valid_actions:
                action = valid_actions[0]  # Always pick first valid action for consistency
            else:
                action = 0

            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            steps += 1

        print(f"  Episode {episode + 1}/10: {steps} steps")

    profiler.disable()

    # Print results
    print("\n" + "="*80)
    print("📊 PROFILING RESULTS - Top 30 Time Consumers")
    print("="*80)

    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    stats.sort_stats('cumulative')
    stats.print_stats(30)

    print(s.getvalue())

    # Also save to file
    with open("profile_results.txt", "w") as f:
        stats = pstats.Stats(profiler, stream=f)
        stats.sort_stats('cumulative')
        stats.print_stats(50)

    print("\n✅ Full results saved to: profile_results.txt")

    # Analyze specific bottlenecks
    print("\n" + "="*80)
    print("🔍 SPECIFIC BOTTLENECK ANALYSIS")
    print("="*80)

    s2 = io.StringIO()
    stats2 = pstats.Stats(profiler, stream=s2)

    # Check observation building
    print("\n📸 Observation Building:")
    stats2.print_stats('observation_builder')
    print(s2.getvalue())

    s3 = io.StringIO()
    stats3 = pstats.Stats(profiler, stream=s3)

    # Check action masking
    print("\n🎭 Action Masking:")
    stats3.print_stats('action_decoder')
    print(s3.getvalue())

    s4 = io.StringIO()
    stats4 = pstats.Stats(profiler, stream=s4)

    # Check phase handlers
    print("\n⚔️ Phase Handlers:")
    stats4.print_stats('phase_handlers')
    print(s4.getvalue())

    env.close()

if __name__ == "__main__":
    profile_training_step()
