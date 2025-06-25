#!/usr/bin/env python3
"""
ai/evaluate.py - Model evaluation with web-compatible event logging
"""

import os
import sys
import json

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

def save_evaluation_logs(results, model_path):
    """Save evaluation episode logs in web-compatible format."""
    if not results["episodes"]:
        print("No episode data to save")
        return
    
    # Try to use web log generator
    try:
        from web_log_generator import WebLogGenerator
        generator = WebLogGenerator()
        generator.convert_and_save_evaluation_logs(results, model_path)
    except ImportError:
        # Fallback to simple format
        print("⚠️  WebLogGenerator not found, using simple format")
        save_evaluation_logs_simple(results, model_path)

def save_evaluation_logs_simple(results, model_path):
    """Fallback: Save evaluation logs in simple format."""
    # Create unified event log directory
    event_log_dir = "ai/event_log"
    os.makedirs(event_log_dir, exist_ok=True)
    
    # Find best and worst episodes by reward
    best_episode = max(results["episodes"], key=lambda x: x["reward"])
    worst_episode = min(results["episodes"], key=lambda x: x["reward"])
    
    # Save evaluation logs with new naming convention
    eval_best_file = os.path.join(event_log_dir, "eval_best_event_log_simple.json")
    eval_worst_file = os.path.join(event_log_dir, "eval_worst_event_log_simple.json")
    
    # Save best episode data
    with open(eval_best_file, "w", encoding="utf-8") as f:
        json.dump(best_episode["data"], f, indent=2)
    
    # Save worst episode data  
    with open(eval_worst_file, "w", encoding="utf-8") as f:
        json.dump(worst_episode["data"], f, indent=2)
    
    print(f"LOGS: Evaluation episode logs saved (simple format)")
    print(f"  📈 Best episode (reward: {best_episode['reward']:.2f}): {eval_best_file}")
    print(f"  📉 Worst episode (reward: {worst_episode['reward']:.2f}): {eval_worst_file}")
    
    # Save evaluation summary
    summary_file = os.path.join(event_log_dir, "eval_summary.json")
    summary = {
        "model_path": model_path,
        "timestamp": __import__('datetime').datetime.now().isoformat(),
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
            "best": "eval_best_event_log_simple.json",
            "worst": "eval_worst_event_log_simple.json"
        },
        "web_compatible": False
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print(f"  📊 Summary: {summary_file}")
    print(f"  ⚠️  Use convert_replays.py to make web-compatible")

def evaluate_model(model_path=None, n_episodes=100, save_logs=True):
    """Evaluate AI model with web-compatible logging."""
    print("🏆 Starting model evaluation...")
    
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
    
    print(f"🎮 Running {n_episodes} evaluation episodes...")
    
    for episode in range(n_episodes):
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
            
            # Record step data for web format
            episode_data.append({
                "step": episode_steps,
                "action": int(action),
                "reward": float(reward)
            })
            
            done = terminated or truncated
        
        # Store episode results
        results["episodes"].append({
            "episode": episode + 1,
            "reward": episode_reward,
            "steps": episode_steps,
            "data": episode_data
        })
        
        results["rewards"].append(episode_reward)
        results["step_counts"].append(episode_steps)
        
        # Determine outcome (basic estimation)
        if episode_reward > 50:
            results["wins"] += 1
        elif episode_reward < -50:
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
    
    # Save logs if requested
    if save_logs:
        save_evaluation_logs(results, model_path)
    
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
            print("🏆 WH40K AI Model Evaluation (Web-Compatible Logging)")
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
            print("Output files (Web-Compatible):")
            print("  ai/event_log/eval_best_event_log.json")
            print("  ai/event_log/eval_worst_event_log.json")
            print("  ai/event_log/eval_summary.json")
            print()
            print("🌐 Files are directly compatible with web app - no conversion needed!")
            return True
        else:
            print(f"Unknown argument: {arg}")
            return False
    
    # Run evaluation
    success = evaluate_model(model_path, episodes)
    
    if success:
        print(f"\n✅ Evaluation completed!")
        print(f"\n🎯 Next Steps:")
        print(f"   🔄 More training:     python ai/train.py")
        print(f"   🌐 Load in web app:   Open web app and load eval_best_event_log.json")
        print(f"   📋 View logs:         ls ai/event_log/")
        print(f"   🌐 Web app:           cd frontend && npm run dev")
    
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