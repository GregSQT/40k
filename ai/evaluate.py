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
        from gym40k_improved import W40KEnv
    except ImportError:
        try:
            from ai.gym40k_improved import W40KEnv
        except ImportError:
            from gym40k import W40KEnv  # Fallback
    
    return DQN, W40KEnv

def evaluate_model(model_path=None, n_episodes=100, save_logs=True):
    """Evaluate AI model with organized file structure."""
    
    # Default to organized model path
    if model_path is None:
        model_path = "ai/models/current/model.zip"
    
    print(f"🏆 WH40K AI Model Evaluation (Organized)")
    print("=" * 50)
    print(f"Model: {model_path}")
    print(f"Episodes: {n_episodes}")
    print()
    
    # Check model exists
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        print("Available options:")
        
        # Check for current model
        current_model = "ai/models/current/model.zip"
        if os.path.exists(current_model):
            print(f"   ✓ Current model: {current_model}")
        
        # Check for backups
        backup_dir = "ai/models/backups"
        if os.path.exists(backup_dir):
            import glob
            backups = glob.glob(f"{backup_dir}/*.zip")
            if backups:
                print(f"   📦 Backups available:")
                for backup in sorted(backups):
                    print(f"      {backup}")
        
        return False
    
    # Setup environment and model
    try:
        DQN, W40KEnv = setup_imports()
        env = W40KEnv()
        model = DQN.load(model_path, env=env)
        print("✓ Model and environment loaded successfully")
    except Exception as e:
        print(f"❌ Loading failed: {e}")
        return False
    
    # Run evaluation
    results = {
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "rewards": [],
        "step_counts": [],
        "episodes": []
    }
    
    print(f"🎮 Running {n_episodes} episodes...")
    print("=" * 50)
    
    for ep in range(n_episodes):
        try:
            obs, info = env.reset()
            done = False
            total_reward = 0
            step_count = 0
            episode_data = []
            
            while not done and step_count < 200:
                action, _ = model.predict(obs, deterministic=True)
                if hasattr(action, 'item'):
                    action = action.item()
                action = int(action)
                
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                step_count += 1
                done = terminated or truncated
                
                episode_data.append({
                    "step": step_count,
                    "action": action,
                    "reward": float(reward)
                })
            
            # Record results
            winner = info.get("winner", None)
            if winner == 1:
                results["wins"] += 1
                result_str = "WIN"
            elif winner == 0:
                results["losses"] += 1
                result_str = "LOSS"
            else:
                results["draws"] += 1
                result_str = "DRAW"
            
            results["rewards"].append(total_reward)
            results["step_counts"].append(step_count)
            results["episodes"].append({
                "episode": ep + 1,
                "result": result_str,
                "winner": winner,
                "steps": step_count,
                "reward": total_reward,
                "data": episode_data
            })
            
            # Progress display
            if (ep + 1) % 10 == 0 or ep < 5:
                print(f"Episode {ep+1:3d}: {result_str:4s} | {step_count:2d} steps | Reward: {total_reward:6.2f}")
                
        except Exception as e:
            print(f"Episode {ep+1} failed: {e}")
            continue
    
    # Calculate statistics
    total_episodes = len(results["rewards"])
    win_rate = results["wins"] / total_episodes if total_episodes > 0 else 0
    loss_rate = results["losses"] / total_episodes if total_episodes > 0 else 0
    draw_rate = results["draws"] / total_episodes if total_episodes > 0 else 0
    
    avg_reward = sum(results["rewards"]) / len(results["rewards"]) if results["rewards"] else 0
    avg_steps = sum(results["step_counts"]) / len(results["step_counts"]) if results["step_counts"] else 0
    
    # Display results
    print("=" * 50)
    print("🏆 EVALUATION RESULTS")
    print("=" * 50)
    print(f"Episodes completed:    {total_episodes}")
    print(f"Wins:                 {results['wins']:3d} ({win_rate:.1%})")
    print(f"Losses:               {results['losses']:3d} ({loss_rate:.1%})")
    print(f"Draws:                {results['draws']:3d} ({draw_rate:.1%})")
    print()
    print(f"Average reward:       {avg_reward:7.3f}")
    print(f"Average game length:  {avg_steps:5.1f} steps")
    
    if results["rewards"]:
        print(f"Best reward:          {max(results['rewards']):7.3f}")
        print(f"Worst reward:         {min(results['rewards']):7.3f}")
    
    if results["step_counts"]:
        print(f"Shortest game:        {min(results['step_counts']):3d} steps")
        print(f"Longest game:         {max(results['step_counts']):3d} steps")
    
    # Performance rating
    if win_rate >= 0.9:
        rating = "OUTSTANDING 🌟"
    elif win_rate >= 0.7:
        rating = "EXCELLENT 🏆"
    elif win_rate >= 0.5:
        rating = "GOOD 👍"
    elif win_rate >= 0.3:
        rating = "FAIR 😐"
    else:
        rating = "NEEDS IMPROVEMENT 📊"
    
    print(f"\nPerformance:          {rating}")
    
    # Save logs if requested
    if save_logs and results["episodes"]:
        logs_dir = "ai/models/logs"
        os.makedirs(logs_dir, exist_ok=True)
        
        # Find best and worst episodes
        best_episode = max(results["episodes"], key=lambda x: x["reward"])
        worst_episode = min(results["episodes"], key=lambda x: x["reward"])
        
        # Save best episode
        best_file = f"{logs_dir}/best_event_log.json"
        with open(best_file, "w") as f:
            json.dump(best_episode["data"], f, indent=2)
        
        # Save worst episode  
        worst_file = f"{logs_dir}/worst_event_log.json"
        with open(worst_file, "w") as f:
            json.dump(worst_episode["data"], f, indent=2)
        
        # Save evaluation summary
        summary_file = f"{logs_dir}/evaluation_summary.json"
        summary = {
            "model_path": model_path,
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "episodes": total_episodes,
            "wins": results["wins"],
            "losses": results["losses"],
            "draws": results["draws"],
            "win_rate": win_rate,
            "avg_reward": avg_reward,
            "avg_steps": avg_steps,
            "best_reward": max(results["rewards"]) if results["rewards"] else 0,
            "worst_reward": min(results["rewards"]) if results["rewards"] else 0
        }
        
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n💾 Logs saved:")
        print(f"   📈 Best episode: {best_file}")
        print(f"   📉 Worst episode: {worst_file}")
        print(f"   📊 Summary: {summary_file}")
    
    env.close()
    return True

def main():
    """Main evaluation function."""
    model_path = None
    episodes = 100
    
    # Parse arguments
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--model" and i + 1 < len(sys.argv):
            model_path = sys.argv[i + 1]
            i += 2
        elif arg == "--episodes" and i + 1 < len(sys.argv):
            episodes = int(sys.argv[i + 1])
            i += 2
        elif arg == "--current":
            model_path = "ai/models/current/model.zip"
            i += 1
        elif arg == "--backup" and i + 1 < len(sys.argv):
            backup_num = int(sys.argv[i + 1])
            import glob
            backups = sorted(glob.glob("ai/models/backups/*.zip"), key=os.path.getmtime, reverse=True)
            if 1 <= backup_num <= len(backups):
                model_path = backups[backup_num - 1]
                print(f"Using backup {backup_num}: {model_path}")
            else:
                print(f"❌ Backup {backup_num} not found. Available: 1-{len(backups)}")
                return False
            i += 2
        elif arg == "--help":
            print("🏆 WH40K AI Model Evaluation (Organized)")
            print("=" * 45)
            print("Usage: python ai/evaluate_organized.py [options]")
            print()
            print("Options:")
            print("  --model PATH     Specific model file")
            print("  --current        Use current model (default)")
            print("  --backup N       Use backup N (1=newest)")
            print("  --episodes N     Number of episodes (default: 100)")
            print("  --help          Show this help")
            print()
            print("Examples:")
            print("  python ai/evaluate_organized.py")
            print("  python ai/evaluate_organized.py --current --episodes 50")
            print("  python ai/evaluate_organized.py --backup 1")
            return True
        else:
            print(f"Unknown argument: {arg}")
            return False
    
    # Run evaluation
    success = evaluate_model(model_path, episodes)
    
    if success:
        print(f"\n✅ Evaluation completed!")
        print(f"\n🎯 Next Steps:")
        print(f"   🔄 More training:     python ai/quick_retrain_organized.py")
        print(f"   💾 Backup model:      python ai/models/backup_model.py")
        print(f"   📋 View logs:         ls ai/models/logs/")
    
    return success

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