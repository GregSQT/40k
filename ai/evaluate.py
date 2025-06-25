#!/usr/bin/env python3
"""
Enhanced evaluation script with full game replay logging
"""

import os
import sys
import json
import shutil
from datetime import datetime

def setup_imports():
    """Set up import paths and return required modules."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    
    sys.path.insert(0, script_dir)
    sys.path.insert(0, project_root)

    try:
        from stable_baselines3 import DQN
    except ImportError as e:
        print(f"Error importing stable_baselines3: {e}")
        raise
    
    try:
        from gym40k import W40KEnv
    except ImportError:
        try:
            from ai.gym40k import W40KEnv
        except ImportError:
            from gym40k import W40KEnv  # Fallback
    
    return DQN, W40KEnv

def run_evaluation_episode_with_replay(model, env, episode_num):
    """Run a single evaluation episode with full replay logging."""
    try:
        from game_replay_logger import GameReplayIntegration
    except ImportError:
        print("⚠️  GameReplayLogger not found, running without replay")
        return run_simple_evaluation_episode(model, env, episode_num)
    
    # Enhanced environment with replay logging
    env_with_replay = GameReplayIntegration.enhance_training_env(env)
    
    # Run the episode
    obs, info = env_with_replay.reset()
    episode_reward = 0
    episode_steps = 0
    episode_data = []
    done = False
    
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env_with_replay.step(action)
        
        episode_reward += reward
        episode_steps += 1
        
        # Still collect simple data for compatibility
        episode_data.append({
            "step": episode_steps,
            "action": int(action),
            "reward": float(reward)
        })
        
        done = terminated or truncated
    
    # Save the replay for this episode
    event_log_dir = "ai/event_log"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    replay_file = os.path.join(event_log_dir, f"eval_episode_{episode_num}_{timestamp}.json")
    
    GameReplayIntegration.save_episode_replay(env_with_replay, episode_reward)
    
    # Get the most recent replay file (just saved)
    import glob
    recent_replays = sorted(glob.glob(os.path.join(event_log_dir, "game_replay_*.json")), 
                           key=os.path.getmtime)
    if recent_replays:
        # Move to evaluation-specific name
        shutil.move(recent_replays[-1], replay_file)
    
    return {
        "episode": episode_num,
        "reward": episode_reward,
        "steps": episode_steps,
        "data": episode_data,
        "replay_file": replay_file if os.path.exists(replay_file) else None
    }

def run_simple_evaluation_episode(model, env, episode_num):
    """Fallback: Run episode without replay logging."""
    obs, info = env.reset()
    episode_reward = 0
    episode_steps = 0
    episode_data = []
    done = False
    
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        
        episode_reward += reward
        episode_steps += 1
        
        episode_data.append({
            "step": episode_steps,
            "action": int(action),
            "reward": float(reward)
        })
        
        done = terminated or truncated
    
    return {
        "episode": episode_num,
        "reward": episode_reward,
        "steps": episode_steps,
        "data": episode_data,
        "replay_file": None
    }

def save_evaluation_logs_with_replay(results, model_path):
    """Save evaluation logs with full game replay data."""
    if not results["episodes"]:
        print("No episode data to save")
        return
    
    event_log_dir = "ai/event_log"
    os.makedirs(event_log_dir, exist_ok=True)
    
    # Find best and worst episodes
    best_episode = max(results["episodes"], key=lambda x: x["reward"])
    worst_episode = min(results["episodes"], key=lambda x: x["reward"])
    
    print(f"📋 LOGS: Saving evaluation replays...")
    
    # Copy replay files to standard locations
    best_replay_dest = os.path.join(event_log_dir, "eval_best_game_replay.json")
    worst_replay_dest = os.path.join(event_log_dir, "eval_worst_game_replay.json")
    
    if best_episode.get("replay_file") and os.path.exists(best_episode["replay_file"]):
        shutil.copy2(best_episode["replay_file"], best_replay_dest)
        print(f"   🏆 Best episode replay: {best_replay_dest}")
    else:
        print(f"   ⚠️  No replay file for best episode")
    
    if worst_episode.get("replay_file") and os.path.exists(worst_episode["replay_file"]):
        shutil.copy2(worst_episode["replay_file"], worst_replay_dest)
        print(f"   📉 Worst episode replay: {worst_replay_dest}")
    else:
        print(f"   ⚠️  No replay file for worst episode")
    
    # Save evaluation summary
    summary_file = os.path.join(event_log_dir, "eval_summary.json")
    summary = {
        "model_path": model_path,
        "timestamp": datetime.now().isoformat(),
        "episodes": len(results["episodes"]),
        "wins": results["wins"],
        "losses": results["losses"],
        "draws": results["draws"],
        "win_rate": results["wins"] / len(results["episodes"]) if results["episodes"] else 0,
        "avg_reward": sum(results["rewards"]) / len(results["rewards"]) if results["rewards"] else 0,
        "avg_steps": sum(results["step_counts"]) / len(results["step_counts"]) if results["step_counts"] else 0,
        "best_reward": max(results["rewards"]) if results["rewards"] else 0,
        "worst_reward": min(results["rewards"]) if results["rewards"] else 0,
        "files": {
            "best_replay": "eval_best_game_replay.json",
            "worst_replay": "eval_worst_game_replay.json"
        },
        "replay_type": "full_game_state",
        "web_compatible": True,
        "features": [
            "Complete unit positions",
            "HP tracking", 
            "Movement visualization",
            "Combat events",
            "Turn-by-turn progression",
            "Deterministic AI evaluation"
        ]
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"   📊 Summary: {summary_file}")
    print(f"   🌐 Game replays ready for web app!")
    
    # Cleanup temporary episode files
    cleanup_temp_episode_files(event_log_dir)

def cleanup_temp_episode_files(event_log_dir):
    """Clean up temporary episode replay files."""
    import glob
    temp_files = glob.glob(os.path.join(event_log_dir, "eval_episode_*.json"))
    temp_files += glob.glob(os.path.join(event_log_dir, "game_replay_*.json"))
    
    kept_files = [
        os.path.join(event_log_dir, "eval_best_game_replay.json"),
        os.path.join(event_log_dir, "eval_worst_game_replay.json")
    ]
    
    for temp_file in temp_files:
        if temp_file not in kept_files:
            try:
                os.remove(temp_file)
                print(f"   🧹 Cleaned up: {os.path.basename(temp_file)}")
            except OSError:
                pass

def evaluate_model_with_replay(model_path=None, n_episodes=100, save_logs=True):
    """Evaluate AI model with full game replay logging."""
    print("🏆 Starting model evaluation with game replay...")
    
    # Setup imports
    try:
        DQN, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    
    # Load model
    if model_path is None:
        model_path = "ai/models/current/model.zip"
    
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        return False
    
    print(f"📁 Loading model: {model_path}")
    
    # Create environment
    env = W40KEnv()
    
    try:
        model = DQN.load(model_path, env=env)
        print("✅ Model loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return False
    
    # Evaluation results
    results = {
        "episodes": [],
        "rewards": [],
        "step_counts": [],
        "wins": 0,
        "losses": 0,
        "draws": 0
    }
    
    print(f"🎮 Running {n_episodes} evaluation episodes with replay capture...")
    print(f"   🎬 Each episode will generate a complete game visualization")
    
    # Limit replay capture for performance
    capture_replays_for = min(n_episodes, 20)  # Capture replays for first 20 episodes max
    
    for episode in range(n_episodes):
        if episode < capture_replays_for:
            print(f"   🎬 Episode {episode + 1}: Capturing full replay...")
            episode_result = run_evaluation_episode_with_replay(model, env, episode + 1)
        else:
            # Run without replay for performance
            episode_result = run_simple_evaluation_episode(model, env, episode + 1)
        
        # Store episode results
        results["episodes"].append(episode_result)
        results["rewards"].append(episode_result["reward"])
        results["step_counts"].append(episode_result["steps"])
        
        # Determine outcome (basic estimation)
        if episode_result["reward"] > 50:
            results["wins"] += 1
        elif episode_result["reward"] < -50:
            results["losses"] += 1
        else:
            results["draws"] += 1
        
        # Progress indicator
        if (episode + 1) % 10 == 0:
            avg_reward = sum(results["rewards"]) / len(results["rewards"])
            print(f"   Episode {episode + 1}/{n_episodes} - Avg Reward: {avg_reward:.2f}")
    
    # Calculate final statistics
    total_episodes = len(results["episodes"])
    win_rate = (results["wins"] / total_episodes * 100) if total_episodes > 0 else 0
    avg_reward = sum(results["rewards"]) / len(results["rewards"]) if results["rewards"] else 0
    avg_steps = sum(results["step_counts"]) / len(results["step_counts"]) if results["step_counts"] else 0
    
    print(f"\n📊 Evaluation Results:")
    print(f"   Episodes: {total_episodes}")
    print(f"   Win Rate: {win_rate:.1f}% ({results['wins']}W/{results['losses']}L/{results['draws']}D)")
    print(f"   Avg Reward: {avg_reward:.2f}")
    print(f"   Avg Steps: {avg_steps:.1f}")
    print(f"   Best Reward: {max(results['rewards']):.2f}")
    print(f"   Worst Reward: {min(results['rewards']):.2f}")
    print(f"   Game Replays: {min(capture_replays_for, total_episodes)} episodes captured")
    
    # Save logs if requested
    if save_logs:
        save_evaluation_logs_with_replay(results, model_path)
    
    env.close()
    print("✅ Evaluation completed")
    return True

def parse_args():
    """Parse command line arguments for evaluation."""
    model_path = None
    episodes = 100
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--model" and i + 1 < len(sys.argv):
            model_path = sys.argv[i + 1]
            i += 2
        elif arg == "--current":
            model_path = "ai/models/current/model.zip"
            i += 1
        elif arg == "--backup" and i + 1 < len(sys.argv):
            backup_num = int(sys.argv[i + 1])
            # Find backup files
            import glob
            backups = sorted(glob.glob("ai/models/backups/model_backup_*.zip"), 
                           key=os.path.getmtime, reverse=True)
            if 1 <= backup_num <= len(backups):
                model_path = backups[backup_num - 1]
                print(f"📦 Using backup: {os.path.basename(model_path)}")
            else:
                print(f"❌ Invalid backup number. Available: 1-{len(backups)}")
                return False
            i += 2
        elif arg == "--episodes" and i + 1 < len(sys.argv):
            episodes = int(sys.argv[i + 1])
            i += 2
        elif arg == "--help":
            print("🏆 WH40K AI Model Evaluation (Game Replay System)")
            print("=" * 55)
            print("Usage: python ai/evaluate.py [options]")
            print()
            print("Options:")
            print("  --model PATH     Specific model file")
            print("  --current        Use current model (default)")
            print("  --backup N       Use backup N (1=newest)")
            print("  --episodes N     Number of episodes (default: 100)")
            print("  --help          Show this help")
            print()
            print("Examples:")
            print("  python ai/evaluate.py")
            print("  python ai/evaluate.py --current --episodes 50")
            print("  python ai/evaluate.py --backup 1")
            print()
            print("Output files (Game Replay System):")
            print("  ai/event_log/eval_best_game_replay.json")
            print("  ai/event_log/eval_worst_game_replay.json")
            print("  ai/event_log/eval_summary.json")
            print()
            print("🎬 Features:")
            print("  ✅ Complete unit movements and positions")
            print("  ✅ HP tracking and combat visualization")
            print("  ✅ Turn-by-turn game progression")
            print("  ✅ Direct web app compatibility")
            print("  ✅ Deterministic AI evaluation")
            print()
            print("🌐 Load eval_best_game_replay.json in web app to watch your AI!")
            return True
        else:
            print(f"Unknown argument: {arg}")
            return False
    
    # Run evaluation
    success = evaluate_model_with_replay(model_path, episodes)
    
    if success:
        print(f"\n✅ Evaluation completed!")
        print(f"\n🎯 Next Steps:")
        print(f"   🔄 More training:     python ai/train.py")
        print(f"   🎬 Watch AI battle:   Load eval_best_game_replay.json in web app")
        print(f"   📋 View logs:         ls ai/event_log/")
        print(f"   🌐 Web app:           cd frontend && npm run dev")
        print(f"\n🎮 Game Replay Features:")
        print(f"   🎯 Unit movements and positioning")
        print(f"   ⚔️  Combat and damage visualization")
        print(f"   📊 HP tracking throughout battle")
        print(f"   🎬 Complete turn-by-turn progression")
    
    return success

def main():
    """Main evaluation function."""
    return parse_args()

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n⏹️ Evaluation interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)