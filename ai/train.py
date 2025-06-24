#!/usr/bin/env python3
"""
ai/train.py - Fixed version that uses configuration system instead of hardcoded parameters
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
        from gym40k import W40KEnv
    except ImportError:
        try:
            from ai.gym40k import W40KEnv
        except ImportError:
            from gym40k import W40KEnv
    
    # Import config loader
    try:
        from config_loader import ConfigLoader
    except ImportError:
        print("ERROR: config_loader.py not found!")
        print("Make sure config_loader.py exists in the project root")
        sys.exit(1)
    
    return DQN, check_env, W40KEnv, ConfigLoader

def parse_arguments():
    """Parse command line arguments."""
    config_name = "default"
    resume = False
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--config" and i + 1 < len(sys.argv):
            config_name = sys.argv[i + 1]
            i += 2
        elif arg == "--resume":
            resume = True
            i += 1
        elif arg == "--help":
            print("Usage: python ai/train.py [options]")
            print("Options:")
            print("  --config NAME    Training configuration to use (default: 'default')")
            print("  --resume         Resume from existing model") 
            print("  --help           Show this help")
            print()
            print("Available configurations:")
            try:
                _, _, _, ConfigLoader = setup_imports()
                loader = ConfigLoader()
                configs = loader.list_training_configs()
                for cfg in configs:
                    print(f"  - {cfg}")
            except:
                print("  (Unable to load config list)")
            sys.exit(0)
        else:
            print(f"Unknown argument: {arg}")
            print("Use --help for usage information")
            sys.exit(1)
    
    return config_name, resume

def backup_current_model():
    """Create backup before training."""
    current_model = "ai/models/current/model.zip"
    backup_dir = "ai/models/backups"
    
    if os.path.exists(current_model):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{backup_dir}/model_backup_{timestamp}.zip"
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(current_model, backup_path)
        print(f"BACKUP: Created {os.path.basename(backup_path)}")
        
        # Manage backup count (keep only 3)
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
    """Main training function using configuration system."""
    print("🚀 WH40K AI Training (Config-Based)")
    print("=" * 50)
    
    # Parse arguments
    config_name, resume = parse_arguments()
    
    # Setup imports
    try:
        DQN, check_env, W40KEnv, ConfigLoader = setup_imports()
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    
    # Load configuration
    try:
        loader = ConfigLoader()
        training_config = loader.load_training_config(config_name)
        
        print(f"📋 Configuration: {config_name}")
        print(f"   Description: {training_config.get('description', 'No description')}")
        print()
        
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        print(f"Available configs: {loader.list_training_configs()}")
        return False
    
    # Ensure model structure exists
    os.makedirs("ai/models/current", exist_ok=True)
    os.makedirs("ai/models/backups", exist_ok=True)
    os.makedirs("ai/models/logs", exist_ok=True)
    
    # Extract training parameters from config
    total_timesteps = training_config['total_timesteps']
    model_params = training_config['model_params'].copy()
    
    print(f"⚙️  Training Parameters:")
    print(f"   Total timesteps: {total_timesteps:,}")
    print(f"   Learning rate: {model_params.get('learning_rate', 'N/A')}")
    print(f"   Buffer size: {model_params.get('buffer_size', 'N/A'):,}")
    print(f"   Batch size: {model_params.get('batch_size', 'N/A')}")
    print(f"   Learning starts: {model_params.get('learning_starts', 'N/A'):,}")
    print()
    
    # Backup existing model
    backup_path = backup_current_model()
    
    # Create environment
    try:
        env = W40KEnv()
        print(f"🌍 Environment: Created successfully")
        print(f"   Units: {len(env.units)}")
        print(f"   Max turns: {getattr(env, 'max_turns', 'Unknown')}")
    except Exception as e:
        print(f"❌ Environment creation failed: {e}")
        return False
    
    # Model path
    model_path = "ai/models/current/model.zip"
    
    # Create or load model
    if os.path.exists(model_path) and resume:
        print(f"🔄 Loading existing model from {model_path}")
        try:
            model = DQN.load(model_path, env=env)
            print("✅ Model loaded successfully")
        except Exception as e:
            print(f"❌ Model loading failed: {e}")
            return False
    else:
        print(f"🆕 Creating new DQN model with config parameters...")
        try:
            # Create model with parameters from config
            model = DQN(env=env, **model_params)
            print("✅ Model created successfully")
        except Exception as e:
            print(f"❌ Model creation failed: {e}")
            print(f"Config parameters: {model_params}")
            return False
    
    print(f"\n🎯 Starting training for {total_timesteps:,} timesteps...")
    print(f"📊 Monitor with: tensorboard --logdir {model_params.get('tensorboard_log', './tensorboard/')}")
    print("=" * 50)
    
    # Training
    try:
        model.learn(total_timesteps=total_timesteps)
        print("✅ Training completed successfully!")
    except KeyboardInterrupt:
        print("\n⏹️  Training interrupted by user")
    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save model
    try:
        model.save(model_path)
        print(f"💾 Model saved to {model_path}")
    except Exception as e:
        print(f"❌ Model saving failed: {e}")
        return False
    
    # Quick evaluation
    print(f"\n🧪 Quick evaluation (5 episodes)...")
    wins = 0
    for ep in range(5):
        try:
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
            print(f"   Episode {ep+1}: {result} ({steps} steps)")
            
        except Exception as e:
            print(f"   Episode {ep+1}: ERROR - {e}")
    
    print(f"\n📈 Results: {wins}/5 wins ({wins*20}%)")
    
    if wins >= 3:
        print("🌟 EXCELLENT: AI is performing well!")
    elif wins >= 1:
        print("👍 GOOD: AI is learning, consider more training")
    else:
        print("📊 NEEDS WORK: Consider longer training or different config")
    
    env.close()
    
    print(f"\n🎉 Training completed!")
    print(f"\n🎯 Next Steps:")
    print(f"   📊 Detailed evaluation: python ai/evaluate.py --episodes 50")
    print(f"   💾 Backup model: python ai/models/backup_model.py")
    print(f"   ⚙️  Try different config: python ai/train.py --config aggressive")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n⏹️  Training interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)