#!/usr/bin/env python3
"""
Time training performance to identify bottlenecks.
Usage: python check/time_training.py
"""

import time
import sys
import os
import numpy as np

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader
from ai.unit_registry import UnitRegistry

def time_training_components():
    """Time individual components of training to find bottlenecks."""

    # Setup
    config = get_config_loader()
    unit_registry = UnitRegistry()

    # Import environment
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

    print("🏃 Timing 10 episodes...\n")

    # Timing accumulators
    total_reset_time = 0
    total_mask_time = 0
    total_step_time = 0
    total_episodes = 10
    total_steps = 0

    for episode in range(total_episodes):
        # Time reset
        t0 = time.time()
        obs, info = env.reset()
        reset_time = time.time() - t0
        total_reset_time += reset_time

        done = False
        steps = 0
        episode_mask_time = 0
        episode_step_time = 0

        while not done:
            # Time action mask
            t0 = time.time()
            mask = env.action_masks()
            mask_time = time.time() - t0
            episode_mask_time += mask_time

            # Random valid action
            valid_actions = [i for i, valid in enumerate(mask) if valid]
            if valid_actions:
                action = valid_actions[0]
            else:
                action = 0

            # Time step
            t0 = time.time()
            obs, reward, terminated, truncated, info = env.step(action)
            step_time = time.time() - t0
            episode_step_time += step_time

            done = terminated or truncated
            steps += 1

        total_mask_time += episode_mask_time
        total_step_time += episode_step_time
        total_steps += steps

        print(f"Episode {episode + 1:2d}: {steps:3d} steps | "
              f"Reset: {reset_time*1000:5.1f}ms | "
              f"Mask: {episode_mask_time*1000:6.1f}ms | "
              f"Step: {episode_step_time*1000:6.1f}ms")

    env.close()

    # Calculate averages
    avg_reset = total_reset_time / total_episodes
    avg_mask_per_step = total_mask_time / total_steps
    avg_step_per_step = total_step_time / total_steps
    total_time = total_reset_time + total_mask_time + total_step_time

    print("\n" + "="*80)
    print("📊 TIMING SUMMARY")
    print("="*80)
    print(f"Total episodes: {total_episodes}")
    print(f"Total steps:    {total_steps}")
    print(f"Avg steps/episode: {total_steps / total_episodes:.1f}")
    print()
    print(f"Total time:     {total_time:.2f}s")
    print(f"Time per episode: {total_time / total_episodes:.2f}s")
    print(f"Time per step:  {(total_time / total_steps)*1000:.1f}ms")
    print()
    print("=" * 80)
    print("⏱️  TIME BREAKDOWN")
    print("=" * 80)
    print(f"Reset (total):       {total_reset_time*1000:8.1f}ms ({total_reset_time/total_time*100:5.1f}%)")
    print(f"Reset (per episode): {avg_reset*1000:8.1f}ms")
    print()
    print(f"Action Mask (total):       {total_mask_time*1000:8.1f}ms ({total_mask_time/total_time*100:5.1f}%)")
    print(f"Action Mask (per step):    {avg_mask_per_step*1000:8.1f}ms")
    print()
    print(f"Step (total):       {total_step_time*1000:8.1f}ms ({total_step_time/total_time*100:5.1f}%)")
    print(f"Step (per step):    {avg_step_per_step*1000:8.1f}ms")
    print()
    print("=" * 80)
    print("🎯 BOTTLENECK ANALYSIS")
    print("=" * 80)

    # Identify bottleneck
    components = [
        ("Reset", total_reset_time / total_time * 100),
        ("Action Mask", total_mask_time / total_time * 100),
        ("Step Execution", total_step_time / total_time * 100)
    ]

    components.sort(key=lambda x: x[1], reverse=True)

    for i, (name, pct) in enumerate(components, 1):
        symbol = "🚨" if i == 1 else "⚠️" if i == 2 else "✓"
        print(f"{symbol} #{i}: {name:20s} {pct:5.1f}%")

    print("\n💡 OPTIMIZATION SUGGESTIONS:")
    print("=" * 80)

    if components[0][0] == "Action Mask":
        print("• Action masking is the bottleneck")
        print("  - Cache valid target lists between calls")
        print("  - Optimize target validation logic")
        print("  - Reduce shooting_build_valid_target_pool calls")
    elif components[0][0] == "Step Execution":
        print("• Step execution is the bottleneck")
        print("  - Profile phase handlers (movement, shooting, etc.)")
        print("  - Check for slow distance calculations")
        print("  - Optimize observation building")
    elif components[0][0] == "Reset":
        print("• Environment reset is the bottleneck")
        print("  - Optimize scenario loading")
        print("  - Reduce initial state setup cost")

if __name__ == "__main__":
    time_training_components()
