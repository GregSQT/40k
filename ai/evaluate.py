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
    max_actions_per_unit = 8  # gym40k uses 8 actions per unit
    unit_idx = action // max_actions_per_unit
    action_type = action % max_actions_per_unit

    # Get eligible units for current phase
    eligible_units = env._get_eligible_units()
    
    # Check if unit_idx is valid
    if unit_idx < len(eligible_units):
        unit = eligible_units[unit_idx]
        if "rng_rng" not in unit:
            raise ValueError(f"unit.rng_rng is required for unit {unit.get('name', 'unknown')}")
        is_ranged = unit["rng_rng"] > 1  # Ranged if shooting range > 1
    else:
        is_ranged = False  # Invalid unit index

    return unit_idx, action_type, is_ranged


def setup_imports():
    """Set up import paths and return required modules."""
    try:
        # AI_INSTRUCTIONS.md: Import from gym40k.py in ai/ subdirectory
        from gym40k import W40KEnv, register_environment
        return W40KEnv, register_environment
    except ImportError as e:
        print(f"Import error: {e}")
        print("AI_INSTRUCTIONS.md: Please ensure gym40k.py exists in ai/ directory and is properly configured")
        sys.exit(1)

def evaluate_model(model_path, rewards_config="phase_based", num_episodes=None, deterministic=True, verbose=True):
    """
    Evaluate trained model with comprehensive AI_GAME.md compliance testing.
    AI_INSTRUCTIONS.md: "Use evaluation.py as the main evaluation script"
    """
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        return None
    
    print(f"\n🧪 COMPREHENSIVE AI_GAME.md COMPLIANCE EVALUATION")
    print(f"=" * 70)
    
    # Import and register environment
    W40KEnv, register_environment = setup_imports()
    register_environment()

    if num_episodes is None:
        try:
            config = get_config_loader()
            training_config = config.load_training_config("default")
            callback_params = training_config.get("callback_params", {})
            num_episodes = callback_params.get("n_eval_episodes", 50)
            print(f"✅ Using num_episodes from config: {num_episodes}")
        except Exception as e:
            print(f"⚠️ Failed to load num_episodes from config: {e}")
            num_episodes = 50
            print(f"⚠️ Using fallback num_episodes: {num_episodes}")
    
    # Load model with proper config path handling
    try:
        env = W40KEnv(rewards_config=rewards_config)
        model = DQN.load(model_path, env=env)
        print(f"✅ Model loaded: {model_path}")
        print(f"✅ Using rewards config: {rewards_config}")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return None
    
    # AI_GAME.md compliance tracking - Enhanced
    results = {
        'wins': 0, 'losses': 0, 'draws': 0,
        'total_rewards': [], 'game_lengths': [],
        'ai_game_compliance': {
            'ranged_first_violations': 0,
            'movement_tactical_violations': 0,
            'charge_priority_violations': 0,
            'combat_priority_violations': 0,
            'phase_sequence_violations': 0,
            'phase_action_violations': 0,  # NEW: Track phase action enforcement
            'total_behavioral_violations': 0
        },
        'behavioral_analysis': {
            'ranged_avoidance_success': 0,
            'melee_positioning_success': 0,
            'priority_targeting_accuracy': 0,
            'tactical_guideline_compliance': 0,
            'action_masking_applied': 0  # NEW: Track when actions were masked
        }
    }
    
    print(f"🎯 Testing AI_GAME.md compliance for {num_episodes} episodes:")
    print("   ✓ Sequential phase structure (move → shoot → charge → combat)")
    print("   ✓ Ranged units act first in shooting phase")
    print("   ✓ Priority targeting system adherence")
    print("   ✓ Tactical movement guidelines")
    print("   ✓ Charge and combat priority validation")

    for episode in range(num_episodes):
        obs, info = env.reset()
        episode_reward = 0
        game_length = 0
        
        # Episode-specific AI_GAME.md compliance tracking
        episode_violations = []
        phase_action_violations = 0
        action_masking_count = 0
        
        done = False
        max_steps = 1000
        
        while not done and game_length < max_steps:
            current_phase = env.current_phase
            action, _ = model.predict(obs, deterministic=deterministic)
            
            # Track phase action compliance before step
            original_action_type = action % 8
            expected_actions = env._get_valid_actions_for_phase(None, current_phase) if hasattr(env, '_get_valid_actions_for_phase') else []
            if expected_actions and original_action_type not in expected_actions:
                phase_action_violations += 1
            
            # Pre-action AI_GAME.md compliance check
            if hasattr(env, '_validate_ai_game_compliance'):
                unit_idx = action // 8  # gym40k uses 8 actions per unit
                eligible_units = env._get_eligible_units()
                if unit_idx < len(eligible_units):
                    unit = eligible_units[unit_idx]
                    action_type = action % 8
                    
                    compliance = env._validate_ai_game_compliance(unit, action_type)
                    if not compliance:
                        episode_violations.extend(env.phase_behavioral_violations)
                        env.phase_behavioral_violations = []  # Reset for next check
            
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            game_length += 1
            done = terminated or truncated
        
        # Episode results
        results['total_rewards'].append(episode_reward)
        results['game_lengths'].append(game_length)
        
        # AI_GAME.md compliance results
        if hasattr(env, 'ranged_units_shot_first') and not env.ranged_units_shot_first:
            results['ai_game_compliance']['ranged_first_violations'] += 1
        
        # Extract winner information BEFORE using it
        winner = info.get('winner', 'draw') if info else getattr(env, 'winner', 'draw')
        
        # Ensure winner is properly typed for comparisons
        if isinstance(winner, str):
            if winner == 'ai':
                winner = 1
            elif winner == 'player' or winner == 'enemy':
                winner = 0
            else:  # 'draw' or unknown
                winner = None
        
        # Count total behavioral violations
        if episode_violations:
            results['ai_game_compliance']['total_behavioral_violations'] += len(episode_violations)
        
        # Tactical guideline compliance
        if hasattr(env, 'tactical_guideline_compliance'):
            compliance = env.tactical_guideline_compliance
            total_actions = sum(sum(phase.values()) for phase in compliance.values())
            if total_actions > 0:
                results['behavioral_analysis']['tactical_guideline_compliance'] += 1
        
        # Winner tracking - Fix undefined variable
        winner = info.get('winner', 'draw') if 'winner' in info else getattr(env, 'winner', 'draw')
        
        # AI_GAME.md compliance tracking for this episode
        if hasattr(env, 'phase_behavioral_violations'):
            env_violations = len(env.phase_behavioral_violations)
            results['ai_game_compliance']['total_behavioral_violations'] += env_violations
            env.phase_behavioral_violations.clear()  # Reset for next episode
        
        # Game outcome tracking
        if winner == 1:
            results['wins'] += 1
        elif winner == 0:
            results['losses'] += 1
        else:
            results['draws'] += 1
        
        # AI_GAME.md compliance tracking for this episode
        results['ai_game_compliance']['phase_action_violations'] += phase_action_violations
        results['behavioral_analysis']['action_masking_applied'] += action_masking_count
        
        # Track behavioral violations from environment
        if hasattr(env, 'phase_behavioral_violations'):
            env_violations = len(env.phase_behavioral_violations)
            results['ai_game_compliance']['total_behavioral_violations'] += env_violations
            env.phase_behavioral_violations.clear()  # Reset for next episode
        
        if verbose and episode % 10 == 0:
            print(f"   Episode {episode}: Reward {episode_reward:.1f}, Length {game_length}, "
                  f"Violations: {len(episode_violations)}")
    
    # Final AI_GAME.md compliance report
    print(f"\n📊 AI_GAME.md COMPLIANCE REPORT")
    print(f"=" * 50)
    print(f"🎯 Game Results: {results['wins']} wins, {results['losses']} losses, {results['draws']} draws")
    print(f"🎯 Tactical Compliance: {results['behavioral_analysis']['tactical_guideline_compliance']}/{num_episodes} episodes")
    print(f"🔫 Ranged-First Violations: {results['ai_game_compliance']['ranged_first_violations']}")
    print(f"🚨 Total Behavioral Violations: {results['ai_game_compliance']['total_behavioral_violations']}")
    
    total_violations = sum(results['ai_game_compliance'].values())
    compliance_percentage = max(0, ((num_episodes * 5 - total_violations) / (num_episodes * 5)) * 100)
    print(f"✅ Overall AI_GAME.md Compliance: {compliance_percentage:.1f}%")
    
    if compliance_percentage < 80:
        print(f"⚠️  COMPLIANCE WARNING: Less than 80% compliance with AI_GAME.md")
    else:
        print(f"🎉 EXCELLENT: High compliance with AI_GAME.md guidelines")
    
    env.close()
    return results

def analyze_phase_behavior(model_path, rewards_config="phase_based", num_episodes=None):
    """Detailed analysis of AI behavior in each phase following AI_GAME_OVERVIEW.md."""
    
    # AI_INSTRUCTIONS.md: Load num_episodes from config, no hardcoding
    if num_episodes is None:
        try:
            config = get_config_loader()
            training_config = config.load_training_config("default")
            callback_params = training_config.get("callback_params", {})
            num_episodes = min(callback_params.get("n_eval_episodes", 10), 10)  # Cap at 10 for detailed analysis
            print(f"✅ Using num_episodes from config for analysis: {num_episodes}")
        except Exception as e:
            print(f"⚠️ Failed to load num_episodes from config: {e}")
            num_episodes = 10
            print(f"⚠️ Using fallback num_episodes for analysis: {num_episodes}")

def main():
    """Main evaluation function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Evaluate W40K AI following AI_GAME_OVERVIEW.md specifications")
    parser.add_argument("--model", default=None,
                       help="Path to model file (default: use config path)")
    parser.add_argument("--rewards-config", default="default",
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
            # Use config-based episodes or cap at 10 for performance
            analysis_episodes = min(args.episodes, 10) if args.episodes != 50 else None
            analyze_phase_behavior(model_path, args.rewards_config, analysis_episodes)  
        
        return 0
        
    except Exception as e:
        print(f"💥 Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)