# ai/evaluation.py
#!/usr/bin/env python3
"""
ai/evaluation.py - Main evaluation script following AI_INSTRUCTIONS.md exactly
"""

import os
import sys
import argparse
import numpy as np
from pathlib import Path

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from stable_baselines3 import DQN
from config_loader import get_config_loader

def decode_action(env, obs, action):
    """
    Given the env, the last observation, and a FlatDiscrete action,
    return (unit_idx, action_type, is_ranged).
    """
    max_actions = env.max_units * env.max_actions_per_unit  # gym40k: max_units*8
    # Phase doesn’t affect decoding – the same split is used each phase
    unit_idx    = action // env.max_actions_per_unit
    action_type = action %  env.max_actions_per_unit

    # Grab that unit’s state from obs (gym40k packs per-unit arrays in obs['unit_states'])
    unit_state = obs['unit_states'][unit_idx]
    # In our env, a ranged unit has rng_rng > 0
    is_ranged = unit_state['rng_rng'] > 0

    return unit_idx, action_type, is_ranged


def setup_imports():
    """Set up import paths and return required modules."""
    try:
        # Import phase-based environment following AI_GAME_OVERVIEW.md
        from gym40k import W40KEnv, register_environment
        return W40KEnv, register_environment
    except ImportError as e:
        print(f"Import error: {e}")
        print("Please ensure gym40k.py exists and is properly configured")
        sys.exit(1)

def evaluate_model(model_path, rewards_config="phase_based", num_episodes=50, deterministic=True, verbose=True):
    """Evaluate trained model performance following AI_GAME_OVERVIEW.md."""
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        return None
    
    # Import and register environment
    W40KPhasesEnv, register_environment = setup_imports()
    register_environment()
    
    # Load model
    try:
        env = W40KPhasesEnv(rewards_config=rewards_config)
        model = DQN.load(model_path, env=env)
        print(f"✅ Model loaded: {model_path}")
        print(f"✅ Using rewards config: {rewards_config}")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return None
    
    # Evaluation metrics following AI_GAME_OVERVIEW.md specifications
    results = {
        'wins': 0,
        'losses': 0,
        'draws': 0,
        'total_rewards': [],
        'game_lengths': [],
        'phase_performance': {
            'move': [],
            'shoot': [],
            'charge': [],
            'combat': []
        },
        'tactical_metrics': {
            'units_killed': 0,
            'units_lost': 0,
            'ranged_first_compliance': 0,
            'priority_targeting_accuracy': 0
        }
    }
    
    print(f"\n🧪 Evaluating model for {num_episodes} episodes...")
    print("🎯 Testing AI_GAME_OVERVIEW.md compliance:")
    print("   - Sequential turn structure (move → shoot → charge → combat)")
    print("   - Ranged units act first in shooting phase")
    print("   - Priority targeting system implementation")

    # ─── Aggregate tactical-metrics counters ───
    total_priority_actions   = 0
    correct_priority_actions = 0

    for episode in range(num_episodes):
        obs, info = env.reset()
        # ─── Per-episode compliance trackers ───
        episode_compliant = True
        ranged_shot_done  = False
        episode_reward = 0
        game_length = 0
        phase_rewards = {'move': 0, 'shoot': 0, 'charge': 0, 'combat': 0}
        
        initial_ai_units = info['ai_units_alive']
        initial_enemy_units = info['enemy_units_alive']
        
        done = False
        max_steps = 1000  # Prevent infinite loops
        
        while not done and game_length < max_steps:
            current_phase = env.current_phase
            
            # Get action from model
            action, _ = model.predict(obs, deterministic=deterministic)
            
            # Execute action
            obs, reward, terminated, truncated, info = env.step(action)
            
            # Track metrics
            episode_reward += reward
            game_length += 1
            phase_rewards[current_phase] += reward

            # ─── Decode and check tactical compliance ───
            unit_idx, action_type, is_ranged = decode_action(env, obs, action)
            # Get this phase’s target list
            if current_phase == "shoot":
                targets = env._get_shooting_targets(env.ai_units[unit_idx])
            elif current_phase == "charge":
                targets = env._get_charge_targets(env.ai_units[unit_idx])
            elif current_phase == "combat":
                targets = env._get_combat_targets(env.ai_units[unit_idx])
            else:
                targets = []

            # Priority-targeting accuracy
            if action_type < len(targets):
                total_priority_actions   += 1
                if action_type == 0:
                    correct_priority_actions += 1

            # Ranged-first compliance (only in shoot phase)
            if current_phase == "shoot" and action_type < len(targets):
                if is_ranged:
                    ranged_shot_done = True
                else:
                    # melee fired before any ranged
                    if not ranged_shot_done:
                        episode_compliant = False
            
            done = terminated or truncated
        
        # Record episode results
        results['total_rewards'].append(episode_reward)
        results['game_lengths'].append(game_length)
        
        # Record phase performance
        for phase, reward in phase_rewards.items():
            results['phase_performance'][phase].append(reward)
        
        # Determine outcome
        final_ai_units = info['ai_units_alive']
        final_enemy_units = info['enemy_units_alive']
        
        if info['winner'] == 1:  # AI won
            results['wins'] += 1
            outcome = "WIN"
        elif info['winner'] == 0:  # AI lost
            results['losses'] += 1
            outcome = "LOSS"
        else:  # Draw/timeout
            results['draws'] += 1
            outcome = "DRAW"
        
        # Track unit casualties
        results['tactical_metrics']['units_killed'] += (initial_enemy_units - final_enemy_units)
        results['tactical_metrics']['units_lost'] += (initial_ai_units - final_ai_units)
        # ─── Episode-level ranged-first compliance ───
        if episode_compliant:
            results['tactical_metrics']['ranged_first_compliance'] += 1
        
        if verbose and (episode + 1) % 10 == 0:
            print(f"Episode {episode + 1:3d}: {outcome:4s} | "
                  f"Reward: {episode_reward:6.1f} | "
                  f"Length: {game_length:3d} | "
                  f"AI: {final_ai_units}/{initial_ai_units} | "
                  f"Enemy: {final_enemy_units}/{initial_enemy_units}")
    
    # Calculate summary statistics
    win_rate = results['wins'] / num_episodes
    loss_rate = results['losses'] / num_episodes
    draw_rate = results['draws'] / num_episodes
    
    avg_reward = np.mean(results['total_rewards'])
    std_reward = np.std(results['total_rewards'])
    avg_length = np.mean(results['game_lengths'])
    
    # Phase performance analysis
    phase_avg = {}
    for phase, rewards in results['phase_performance'].items():
        if rewards:
            phase_avg[phase] = np.mean(rewards)
        else:
            phase_avg[phase] = 0.0
    
    # Tactical efficiency
    total_actions = results['tactical_metrics']['ranged_first_compliance']
    kill_ratio = results['tactical_metrics']['units_killed'] / max(results['tactical_metrics']['units_lost'], 1)
    
    env.close()
    
    # Print detailed results
    print("\n📊 EVALUATION RESULTS")
    print("=" * 70)
    print(f"Win Rate:      {win_rate:.1%} ({results['wins']}/{num_episodes})")
    print(f"Loss Rate:     {loss_rate:.1%} ({results['losses']}/{num_episodes})")
    print(f"Draw Rate:     {draw_rate:.1%} ({results['draws']}/{num_episodes})")
    print()
    print(f"Average Reward:    {avg_reward:.2f} ± {std_reward:.2f}")
    print(f"Average Game Length: {avg_length:.1f} steps")
    print()
    print("📈 PHASE PERFORMANCE (AI_GAME_OVERVIEW.md)")
    print("-" * 40)
    for phase, avg_reward in phase_avg.items():
        print(f"{phase.capitalize():8s}: {avg_reward:6.2f} avg reward")
    print()
    print("⚔️  TACTICAL METRICS")
    print("-" * 40)
    print(f"Kill/Death Ratio: {kill_ratio:.2f}")
    print(f"Units Killed:     {results['tactical_metrics']['units_killed']}")
    print(f"Units Lost:       {results['tactical_metrics']['units_lost']}")

    # ─── Overall compliance rates ───
    rfc = results['tactical_metrics']['ranged_first_compliance'] / num_episodes
    print(f"🎯 Ranged-first compliance: {rfc:.1%} "
          f"({results['tactical_metrics']['ranged_first_compliance']}/{num_episodes})")

    pta = (correct_priority_actions / total_priority_actions
           if total_priority_actions else 0.0)
    print(f"🎯 Priority-target accuracy: {pta:.1%} "
          f"({correct_priority_actions}/{total_priority_actions})")
    
    # Performance assessment following AI_GAME_OVERVIEW.md
    print("\n🎯 AI_GAME_OVERVIEW.md COMPLIANCE ASSESSMENT")
    print("-" * 50)
    if win_rate >= 0.7:
        print("🟢 EXCELLENT: AI demonstrates strong tactical understanding")
    elif win_rate >= 0.5:
        print("🟡 GOOD: AI shows competent gameplay with room for improvement")
    elif win_rate >= 0.3:
        print("🟠 FAIR: AI has learned basics but needs more training")
    else:
        print("🔴 POOR: AI needs significant additional training")
    
    if kill_ratio >= 1.5:
        print("🟢 Excellent combat effectiveness")
    elif kill_ratio >= 1.0:
        print("🟡 Balanced combat performance")
    else:
        print("🔴 Poor combat effectiveness")
    
    return results

def analyze_phase_behavior(model_path, rewards_config="phase_based", num_episodes=10):
    """Detailed analysis of AI behavior in each phase following AI_GAME_OVERVIEW.md."""
    print("🔍 PHASE BEHAVIOR ANALYSIS (AI_GAME_OVERVIEW.md)")
    print("=" * 70)
    
    W40KEnv, register_environment = setup_imports()
    register_environment()
    
    env = W40KEnv(rewards_config=rewards_config)
    model = DQN.load(model_path, env=env)
    
    phase_actions = {'move': [], 'shoot': [], 'charge': [], 'combat': []}
    phase_rewards = {'move': [], 'shoot': [], 'charge': [], 'combat': []}
    
    for episode in range(num_episodes):
        obs, info = env.reset()
        done = False
        
        while not done:
            current_phase = env.current_phase
            action, _ = model.predict(obs, deterministic=True)
            
            obs, reward, terminated, truncated, info = env.step(action)
            
            phase_actions[current_phase].append(action)
            phase_rewards[current_phase].append(reward)
            
            done = terminated or truncated
    
    print("\nPhase Action Distribution (AI_GAME_OVERVIEW.md compliance):")
    for phase, actions in phase_actions.items():
        if actions:
            unique_actions, counts = np.unique(actions, return_counts=True)
            print(f"\n{phase.capitalize()} Phase:")
            for action, count in zip(unique_actions, counts):
                percentage = count / len(actions) * 100
                print(f"  Action {action}: {count:3d} times ({percentage:4.1f}%)")
            
            # Phase-specific analysis
            if phase == "shoot":
                print(f"  📊 Shooting phase analysis:")
                print(f"     - Total shooting actions: {len(actions)}")
                print(f"     - Average reward: {np.mean(phase_rewards[phase]):.2f}")
            elif phase == "move":
                print(f"  📊 Movement phase analysis:")
                print(f"     - Total movement actions: {len(actions)}")
                print(f"     - Average reward: {np.mean(phase_rewards[phase]):.2f}")
    
    env.close()

def main():
    """Main evaluation function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Evaluate W40K AI following AI_GAME_OVERVIEW.md specifications")
    parser.add_argument("--model", default=None,
                       help="Path to model file (default: use config path)")
    parser.add_argument("--rewards-config", default="phase_based",
                       help="Rewards configuration to use for evaluation")
    parser.add_argument("--episodes", type=int, default=50,
                       help="Number of evaluation episodes")
    parser.add_argument("--deterministic", action="store_true",
                       help="Use deterministic actions")
    parser.add_argument("--analyze-phases", action="store_true",
                       help="Perform detailed phase behavior analysis")
    parser.add_argument("--quiet", action="store_true",
                       help="Reduce output verbosity")
    
    args = parser.parse_args()
    
    print("🎮 W40K AI Evaluation - AI_GAME_OVERVIEW.md Compliance Testing")
    print("=" * 70)
    
    try:
        config = get_config_loader()
        
        # Evaluate model
        model_path = args.model or config.get_model_path()
        
        results = evaluate_model(
            model_path, 
            args.rewards_config,
            args.episodes, 
            args.deterministic, 
            not args.quiet
        )
        
        if results and args.analyze_phases:
            print("\n" + "=" * 70)
            analyze_phase_behavior(model_path, args.rewards_config, min(args.episodes, 10))
        
        return 0
        
    except Exception as e:
        print(f"💥 Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)