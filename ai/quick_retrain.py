#!/usr/bin/env python3
"""
ai/quick_retrain.py - Quick retraining with improved environment
"""

import os
import sys
import shutil

def setup_imports():
    """Set up import paths."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, script_dir)
    sys.path.insert(0, project_root)

    from stable_baselines3 import DQN
    from stable_baselines3.common.env_checker import check_env
    
    # Import the improved environment
    try:
        from gym40k_improved import W40KEnv
    except ImportError:
        from ai.gym40k_improved import W40KEnv
    
    return DQN, check_env, W40KEnv

def main():
    """Quick retraining with better parameters."""
    print("🚀 WH40K AI Quick Retrain")
    print("=" * 40)
    print("Using improved environment with proper combat logic")
    print()
    
    # Setup
    try:
        DQN, check_env, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    
    # Backup old model
    old_model = "ai/model.zip"
    if os.path.exists(old_model):
        backup = f"ai/model_backup_{int(__import__('time').time())}.zip"
        shutil.copy(old_model, backup)
        print(f"✓ Backed up old model to {backup}")
    
    # Create improved environment
    print("Creating improved environment...")
    env = W40KEnv()
    
    try:
        check_env(env)
        print("✓ Environment validation passed")
    except Exception as e:
        print(f"⚠ Environment check warning: {e}")
    
    print(f"Environment info:")
    print(f"  Units: {len(env.units)}")
    print(f"  Board size: {env.board_size}")
    print(f"  Max turns: {env.max_turns}")
    print(f"  Observation space: {env.observation_space}")
    print(f"  Action space: {env.action_space}")
    
    # Training parameters - more aggressive for quick results
    total_timesteps = 50_000  # Start with moderate amount
    
    print(f"\nCreating new model...")
    model = DQN(
        "MlpPolicy",
        env,
        verbose=1,
        # More aggressive learning parameters
        buffer_size=25_000,
        learning_rate=0.001,
        learning_starts=1_000,  # Start learning sooner
        batch_size=128,
        train_freq=4,
        target_update_interval=500,
        exploration_fraction=0.3,  # Less exploration time
        exploration_final_eps=0.05,
        tensorboard_log="./tensorboard/"
    )
    print("✓ Model created")
    
    print(f"\n🎯 Starting training for {total_timesteps:,} timesteps...")
    print("This should take 5-10 minutes...")
    print("=" * 50)
    
    try:
        model.learn(total_timesteps=total_timesteps)
        print("\n✅ Training completed!")
    except KeyboardInterrupt:
        print("\n⏹️ Training interrupted")
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        return False
    
    # Save model
    model.save(old_model)
    print(f"✓ Model saved to {old_model}")
    
    # Quick evaluation
    print("\n🧪 Quick evaluation (10 episodes)...")
    wins = 0
    for ep in range(10):
        obs, _ = env.reset()
        done = False
        steps = 0
        
        while not done and steps < 100:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, truncated, info = env.step(action)
            steps += 1
            done = done or truncated
        
        winner = info.get("winner", None)
        if winner == 1:
            wins += 1
            result = "WIN"
        elif winner == 0:
            result = "LOSS"
        else:
            result = "DRAW"
        
        print(f"  Episode {ep+1}: {result} ({steps} steps)")
    
    win_rate = wins / 10
    print(f"\n📊 Quick Results: {wins}/10 wins ({win_rate:.0%})")
    
    if win_rate > 0:
        print("🎉 AI is now winning games!")
        print("✨ Try full evaluation: python ai/evaluate.py")
    else:
        print("🤔 Still needs more training")
        print("💡 Try: python ai/quick_retrain.py  (runs again)")
    
    env.close()
    return True

if __name__ == "__main__":
    try:
        success = main()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nTraining interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)