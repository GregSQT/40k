#!/usr/bin/env python3
"""
ai/quick_retrain_organized.py - Training with organized model structure
"""

import os
import sys
import shutil
from datetime import datetime

def setup_imports():
    """Set up import paths."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, script_dir)
    sys.path.insert(0, project_root)

    from stable_baselines3 import DQN
    from stable_baselines3.common.env_checker import check_env
    
    try:
        from gym40k_improved import W40KEnv
    except ImportError:
        try:
            from ai.gym40k_improved import W40KEnv
        except ImportError:
            from gym40k import W40KEnv
    
    return DQN, check_env, W40KEnv

def backup_current_model():
    """Create backup before training."""
    current_model = "ai/models/current/model.zip"
    backup_dir = "ai/models/backups"
    
    if os.path.exists(current_model):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{backup_dir}/model_backup_{timestamp}.zip"
        shutil.copy2(current_model, backup_path)
        print(f"BACKUP: Created {os.path.basename(backup_path)}")
        
        # Manage backup count
        import glob
        backup_files = glob.glob(f"{backup_dir}/model_backup_*.zip")
        if len(backup_files) > 3:
            backup_files.sort(key=os.path.getmtime)
            for old_backup in backup_files[:-3]:
                os.remove(old_backup)
                print(f"CLEANUP: Removed old backup: {os.path.basename(old_backup)}")
        
        return backup_path
    return None

def main():
    """Training with organized model paths."""
    print("TRAINING: WH40K AI (Organized Structure)")
    print("=" * 50)
    
    # Ensure model structure exists
    os.makedirs("ai/models/current", exist_ok=True)
    os.makedirs("ai/models/backups", exist_ok=True)
    os.makedirs("ai/models/logs", exist_ok=True)
    
    # Setup
    try:
        DQN, check_env, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"ERROR: Import failed: {e}")
        return False
    
    # Backup existing model
    backup_path = backup_current_model()
    
    # Create environment
    env = W40KEnv()
    print(f"ENVIRONMENT: Created successfully")
    print(f"  Units: {len(env.units)}")
    print(f"  Max turns: {env.max_turns}")
    
    # Training parameters
    total_timesteps = 50_000
    model_path = "ai/models/current/model.zip"
    
    print(f"MODEL: Creating new DQN model...")
    model = DQN(
        "MlpPolicy", env, verbose=1,
        buffer_size=25_000, learning_rate=0.001,
        learning_starts=1_000, batch_size=128,
        train_freq=4, target_update_interval=500,
        exploration_fraction=0.3, exploration_final_eps=0.05,
        tensorboard_log="./tensorboard/"
    )
    
    print(f"TRAINING: Starting for {total_timesteps:,} timesteps...")
    print("Monitor: tensorboard --logdir ./tensorboard/")
    print("=" * 50)
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print("SUCCESS: Training completed!")
    except Exception as e:
        print(f"ERROR: Training failed: {e}")
        return False
    
    # Save model
    model.save(model_path)
    print(f"SAVED: Model saved to {model_path}")
    
    # Quick test
    print("\nTEST: Quick evaluation (5 episodes)...")
    wins = 0
    for ep in range(5):
        obs, _ = env.reset()
        done = False
        steps = 0
        
        while not done and steps < 100:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, truncated, info = env.step(action)
            steps += 1
            done = done or truncated
        
        if info.get("winner") == 1:
            wins += 1
            result = "WIN"
        else:
            result = "LOSS/DRAW"
        print(f"  Episode {ep+1}: {result} ({steps} steps)")
    
    print(f"RESULTS: {wins}/5 wins ({wins*20}%)")
    
    if wins >= 3:
        print("EXCELLENT: AI is performing well!")
    elif wins >= 1:
        print("GOOD: AI is learning, try more training")
    else:
        print("NEEDS WORK: Consider longer training")
    
    env.close()
    return True

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\nNEXT STEPS:")
            print("  python ai/evaluate_organized.py --episodes 20")
            print("  python ai/models/backup_model.py")
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTraining interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
