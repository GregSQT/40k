#!/usr/bin/env python3
"""
train_selfplay.py - Modified Self-Play Training Script
"""

import os
import sys
import copy
import json
import numpy as np
from datetime import datetime

# Add current directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from gym40k import W40KEnv

def test_model_vs_model(model1, model2, episodes=20, verbose=False):
    """Test model1 against model2 and return win rate for model1."""
    test_env = W40KEnv(opponent_model=model2, self_play_mode=True, training_player=1)
    
    wins = 0
    draws = 0
    total_rewards = []
    
    for ep in range(episodes):
        obs, _ = test_env.reset()
        done = False
        total_reward = 0
        steps = 0
        
        while not done and steps < 100:  # Prevent infinite games
            action, _ = model1.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = test_env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated
        
        winner = info.get("winner")
        if winner == 1:  # Model1 wins (training player)
            wins += 1
        elif winner is None:
            draws += 1
        
        total_rewards.append(total_reward)
        
        if verbose:
            result = "WIN" if winner == 1 else "DRAW" if winner is None else "LOSS"
            print(f"    Episode {ep+1}: {result} - {steps} steps - Reward: {total_reward:.2f}")
    
    test_env.close()
    
    win_rate = wins / episodes
    avg_reward = sum(total_rewards) / len(total_rewards) if total_rewards else 0
    
    return {
        "win_rate": win_rate,
        "wins": wins,
        "draws": draws,
        "losses": episodes - wins - draws,
        "avg_reward": avg_reward,
        "episodes": episodes
    }

def test_model_vs_scripted(model, episodes=20, verbose=False):
    """Test model against scripted opponent."""
    test_env = W40KEnv(self_play_mode=False, training_player=1)
    
    wins = 0
    total_rewards = []
    
    for ep in range(episodes):
        obs, _ = test_env.reset()
        done = False
        total_reward = 0
        steps = 0
        
        while not done and steps < 100:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = test_env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated
        
        winner = info.get("winner")
        if winner == 1:
            wins += 1
        
        total_rewards.append(total_reward)
        
        if verbose:
            result = "WIN" if winner == 1 else "LOSS"
            print(f"    Episode {ep+1}: {result} - {steps} steps - Reward: {total_reward:.2f}")
    
    test_env.close()
    
    return {
        "win_rate": wins / episodes,
        "wins": wins,
        "losses": episodes - wins,
        "avg_reward": sum(total_rewards) / len(total_rewards) if total_rewards else 0
    }

def save_generation_info(generation, model, results, base_path="ai/selfplay_history"):
    """Save information about this generation."""
    os.makedirs(base_path, exist_ok=True)
    
    # Save model
    model_path = os.path.join(base_path, f"generation_{generation:03d}.zip")
    model.save(model_path)
    
    # Save results
    info = {
        "generation": generation,
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "model_path": model_path
    }
    
    info_path = os.path.join(base_path, f"generation_{generation:03d}_info.json")
    with open(info_path, "w") as f:
        json.dump(info, f, indent=2)
    
    print(f"[SAVE] Generation {generation} saved to {model_path}")
    return model_path, info_path

def load_latest_generation(base_path="ai/selfplay_history"):
    """Load the latest generation model if available."""
    if not os.path.exists(base_path):
        return None, -1
    
    # Find latest generation
    generations = []
    for filename in os.listdir(base_path):
        if filename.startswith("generation_") and filename.endswith(".zip"):
            try:
                gen_num = int(filename.split("_")[1].split(".")[0])
                generations.append(gen_num)
            except (ValueError, IndexError):
                continue
    
    if not generations:
        return None, -1
    
    latest_gen = max(generations)
    model_path = os.path.join(base_path, f"generation_{latest_gen:03d}.zip")
    
    try:
        model = DQN.load(model_path)
        print(f"[LOAD] Loaded generation {latest_gen} from {model_path}")
        return model, latest_gen
    except Exception as e:
        print(f"[ERROR] Failed to load generation {latest_gen}: {e}")
        return None, -1

def train_selfplay(
    initial_timesteps=100_000,
    selfplay_timesteps=50_000,
    generations=10,
    update_frequency=2,
    test_episodes=20,
    resume=False
):
    """
    Main self-play training function.
    
    Args:
        initial_timesteps: Training steps against scripted opponent
        selfplay_timesteps: Training steps per self-play generation
        generations: Number of self-play generations
        update_frequency: Update opponent every N generations
        test_episodes: Episodes for testing between generations
        resume: Continue from latest saved generation
    """
    
    print("🎯 W40K Modified Self-Play Training")
    print("=" * 50)
    print(f"Initial training: {initial_timesteps:,} timesteps")
    print(f"Self-play generations: {generations}")
    print(f"Timesteps per generation: {selfplay_timesteps:,}")
    print(f"Opponent update frequency: every {update_frequency} generations")
    print()
    
    # Initialize or resume
    if resume:
        model, start_generation = load_latest_generation()
        if model is not None:
            print(f"📁 Resuming from generation {start_generation}")
            start_generation += 1
        else:
            print("⚠️  No saved generation found, starting fresh")
            model = None
            start_generation = 0
    else:
        model = None
        start_generation = 0
    
    # Phase 1: Initial training against scripted opponent
    if model is None:
        print("🤖 Phase 1: Training against scripted opponent...")
        env = W40KEnv(self_play_mode=False, training_player=1)
        
        try:
            check_env(env)
            print("[OK] Environment validation passed")
        except Exception as e:
            print(f"[WARN] Environment check: {e}")
        
        print(f"Environment: {len(env.units)} units, {env.action_space.n} actions")
        
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            buffer_size=100_000,
            learning_rate=1e-3,
            learning_starts=1000,
            batch_size=64,
            train_freq=4,
            target_update_interval=1000,
            exploration_fraction=0.3,
            exploration_final_eps=0.05,
            tensorboard_log="./tensorboard/"
        )
        
        print(f"🚀 Training for {initial_timesteps:,} timesteps...")
        model.learn(total_timesteps=initial_timesteps)
        
        # Test against scripted opponent
        print("📊 Testing against scripted opponent...")
        scripted_results = test_model_vs_scripted(model, episodes=test_episodes, verbose=True)
        print(f"   Win rate vs scripted: {scripted_results['win_rate']:.1%}")
        print(f"   Average reward: {scripted_results['avg_reward']:.2f}")
        
        env.close()
        
        # Save initial model
        save_generation_info(0, model, {"vs_scripted": scripted_results})
    
    # Phase 2: Self-play training
    print("\n🔄 Phase 2: Self-play training...")
    
    # Initialize self-play environment
    env = W40KEnv(self_play_mode=True, training_player=1)
    model.set_env(env)
    
    # Set initial opponent (copy of current model)
    opponent_model = copy.deepcopy(model)
    env.set_opponent_model(opponent_model)
    
    print(f"🎮 Starting self-play from generation {start_generation}")
    
    # Self-play training loop
    for generation in range(start_generation, start_generation + generations):
        print(f"\n--- Generation {generation + 1} ---")
        
        # Train current model
        print(f"🎯 Training generation {generation + 1}...")
        try:
            model.learn(total_timesteps=selfplay_timesteps)
        except KeyboardInterrupt:
            print("\n⏹️  Training interrupted by user")
            break
        except Exception as e:
            print(f"❌ Training failed: {e}")
            break
        
        # Test current model vs previous opponent
        print("📊 Testing vs previous generation...")
        vs_prev_results = test_model_vs_model(
            model, opponent_model, 
            episodes=test_episodes, 
            verbose=False
        )
        
        # Test vs scripted for baseline
        print("📊 Testing vs scripted baseline...")
        vs_scripted_results = test_model_vs_scripted(
            model, 
            episodes=test_episodes, 
            verbose=False
        )
        
        # Print results
        print(f"   🆚 Previous generation: {vs_prev_results['win_rate']:.1%} win rate")
        print(f"   🆚 Scripted opponent: {vs_scripted_results['win_rate']:.1%} win rate")
        print(f"   📈 Average reward: {vs_prev_results['avg_reward']:.2f}")
        
        # Save generation info
        results = {
            "vs_previous": vs_prev_results,
            "vs_scripted": vs_scripted_results,
            "generation": generation + 1
        }
        save_generation_info(generation + 1, model, results)
        
        # Update opponent model periodically
        if (generation + 1) % update_frequency == 0:
            print(f"🔄 Updating opponent model (generation {generation + 1})")
            opponent_model = copy.deepcopy(model)
            env.set_opponent_model(opponent_model)
        
        # Early stopping if performance drops significantly
        if vs_scripted_results['win_rate'] < 0.3:
            print("⚠️  Performance dropped significantly, consider adjusting parameters")
        
        # Show progress
        if vs_prev_results['win_rate'] > 0.6:
            print("✅ Strong improvement over previous generation!")
        elif vs_prev_results['win_rate'] > 0.4:
            print("👍 Decent improvement")
        else:
            print("🤔 Struggling to improve - may need parameter tuning")
    
    env.close()
    
    # Final evaluation
    print("\n🏁 Final Evaluation")
    print("=" * 30)
    
    # Load best performing generation
    print("🔍 Finding best generation...")
    best_generation = find_best_generation()
    if best_generation is not None:
        print(f"🏆 Best generation: {best_generation}")
        
        # Save best model as final model
        best_model_path = f"ai/selfplay_history/generation_{best_generation:03d}.zip"
        final_model_path = "ai/model_selfplay.zip"
        
        best_model = DQN.load(best_model_path)
        best_model.save(final_model_path)
        print(f"💾 Best model saved to {final_model_path}")
        
        # Final test
        print("🎯 Final test against scripted opponent...")
        final_results = test_model_vs_scripted(best_model, episodes=50, verbose=True)
        print(f"\n🎉 Final Results:")
        print(f"   Win rate: {final_results['win_rate']:.1%}")
        print(f"   Wins: {final_results['wins']}/{final_results['wins'] + final_results['losses']}")
        print(f"   Average reward: {final_results['avg_reward']:.2f}")
    
    print("\n✅ Self-play training completed!")
    print("📁 Training history saved in ai/selfplay_history/")
    print("🎮 Best model saved as ai/model_selfplay.zip")
    
    return model

def find_best_generation(base_path="ai/selfplay_history"):
    """Find the generation with best performance against scripted opponent."""
    if not os.path.exists(base_path):
        return None
    
    best_gen = None
    best_score = -float('inf')
    
    for filename in os.listdir(base_path):
        if filename.endswith("_info.json"):
            try:
                with open(os.path.join(base_path, filename), "r") as f:
                    info = json.load(f)
                
                # Score based on scripted win rate and average reward
                vs_scripted = info["results"].get("vs_scripted", {})
                win_rate = vs_scripted.get("win_rate", 0)
                avg_reward = vs_scripted.get("avg_reward", 0)
                
                # Combined score (prioritize win rate)
                score = win_rate * 10 + avg_reward
                
                if score > best_score:
                    best_score = score
                    best_gen = info["generation"]
                    
            except Exception as e:
                print(f"Warning: Could not read {filename}: {e}")
                continue
    
    return best_gen

def main():
    """Main function with command line argument parsing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="W40K Self-Play Training")
    parser.add_argument("--initial-timesteps", type=int, default=100_000,
                       help="Initial training timesteps against scripted opponent")
    parser.add_argument("--selfplay-timesteps", type=int, default=50_000,
                       help="Timesteps per self-play generation")
    parser.add_argument("--generations", type=int, default=10,
                       help="Number of self-play generations")
    parser.add_argument("--update-frequency", type=int, default=2,
                       help="Update opponent every N generations")
    parser.add_argument("--test-episodes", type=int, default=20,
                       help="Episodes for testing between generations")
    parser.add_argument("--resume", action="store_true",
                       help="Resume from latest saved generation")
    parser.add_argument("--quick", action="store_true",
                       help="Quick training for testing (reduced timesteps)")
    
    args = parser.parse_args()
    
    # Quick mode for testing
    if args.quick:
        args.initial_timesteps = 10_000
        args.selfplay_timesteps = 5_000
        args.generations = 5
        args.test_episodes = 10
        print("🚀 Quick mode enabled - reduced timesteps for testing")
    
    try:
        train_selfplay(
            initial_timesteps=args.initial_timesteps,
            selfplay_timesteps=args.selfplay_timesteps,
            generations=args.generations,
            update_frequency=args.update_frequency,
            test_episodes=args.test_episodes,
            resume=args.resume
        )
    except KeyboardInterrupt:
        print("\n⏹️  Training interrupted by user")
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()