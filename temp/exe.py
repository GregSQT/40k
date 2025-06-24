#!/usr/bin/env python3
"""
ai/create_utilities.py - Create utility scripts without emoji (Windows compatible)
"""

import os

def create_backup_utility():
    """Create backup_model.py utility."""
    backup_script = '''#!/usr/bin/env python3
"""
ai/models/backup_model.py - Create model backup
"""

import os
import shutil
from datetime import datetime
import glob

def backup_current_model():
    """Create backup of current model."""
    current_model = "ai/models/current/model.zip"
    backup_dir = "ai/models/backups"
    
    if not os.path.exists(current_model):
        print("ERROR: No current model found")
        return False
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{backup_dir}/model_backup_{timestamp}.zip"
    
    shutil.copy2(current_model, backup_path)
    print(f"SUCCESS: Model backed up: {backup_path}")
    
    # Manage backup count (keep only 3)
    backup_pattern = f"{backup_dir}/model_backup_*.zip"
    backup_files = glob.glob(backup_pattern)
    
    if len(backup_files) > 3:
        backup_files.sort(key=os.path.getmtime)
        for old_backup in backup_files[:-3]:
            os.remove(old_backup)
            print(f"CLEANUP: Removed old backup: {os.path.basename(old_backup)}")
    
    print(f"SUMMARY: {len(glob.glob(backup_pattern))} backups total (max 3)")
    return True

if __name__ == "__main__":
    backup_current_model()
'''
    
    os.makedirs("ai/models", exist_ok=True)
    with open("ai/models/backup_model.py", "w", encoding="utf-8") as f:
        f.write(backup_script)
    print("Created: ai/models/backup_model.py")

def create_restore_utility():
    """Create restore_model.py utility."""
    restore_script = '''#!/usr/bin/env python3
"""
ai/models/restore_model.py - Restore model from backup
"""

import os
import shutil
import glob
from datetime import datetime

def list_backups():
    """List available backups."""
    backup_dir = "ai/models/backups"
    backup_pattern = f"{backup_dir}/model_backup_*.zip"
    backup_files = glob.glob(backup_pattern)
    
    if not backup_files:
        print("No backups found")
        return []
    
    backup_files.sort(key=os.path.getmtime, reverse=True)
    
    print("Available backups:")
    for i, backup in enumerate(backup_files):
        timestamp = os.path.getmtime(backup)
        date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        size = os.path.getsize(backup) / 1024  # KB
        print(f"  {i+1}. {os.path.basename(backup)} ({date_str}, {size:.1f} KB)")
    
    return backup_files

def restore_backup(backup_index=1):
    """Restore a backup as current model."""
    backups = list_backups()
    
    if not backups:
        return False
    
    if backup_index < 1 or backup_index > len(backups):
        print(f"ERROR: Invalid backup index: {backup_index}")
        return False
    
    selected_backup = backups[backup_index - 1]
    current_model = "ai/models/current/model.zip"
    
    # Backup current model first
    if os.path.exists(current_model):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_backup = f"ai/models/backups/model_backup_before_restore_{timestamp}.zip"
        shutil.copy2(current_model, safety_backup)
        print(f"SAFETY: Current model backed up as: {os.path.basename(safety_backup)}")
    
    # Restore selected backup
    shutil.copy2(selected_backup, current_model)
    print(f"SUCCESS: Restored: {os.path.basename(selected_backup)} -> current/model.zip")
    
    return True

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        try:
            backup_index = int(sys.argv[1])
            restore_backup(backup_index)
        except ValueError:
            print("Usage: python restore_model.py [backup_number]")
            list_backups()
    else:
        list_backups()
        print("\\nUsage: python restore_model.py [backup_number]")
'''
    
    with open("ai/models/restore_model.py", "w", encoding="utf-8") as f:
        f.write(restore_script)
    print("Created: ai/models/restore_model.py")

def create_organized_training():
    """Create organized training script."""
    training_script = '''#!/usr/bin/env python3
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
    print("\\nTEST: Quick evaluation (5 episodes)...")
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
            print("\\nNEXT STEPS:")
            print("  python ai/evaluate_organized.py --episodes 20")
            print("  python ai/models/backup_model.py")
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\\nTraining interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\\nUnexpected error: {e}")
        sys.exit(1)
'''
    
    with open("ai/quick_retrain_organized.py", "w", encoding="utf-8") as f:
        f.write(training_script)
    print("Created: ai/quick_retrain_organized.py")

def create_readme():
    """Create README documentation."""
    readme_content = '''# WH40K AI Models Organization

## Folder Structure

```
ai/models/
├── current/           # Active model
│   └── model.zip     # Current trained model
├── backups/          # Model backups (max 3)
│   ├── model_backup_20250624_120000.zip
│   ├── model_backup_20250624_110000.zip
│   └── model_backup_20250624_100000.zip
└── logs/             # Training logs and replays
    ├── best_event_log.json
    ├── worst_event_log.json
    └── evaluation_summary.json
```

## Utilities

### Backup Current Model
```bash
python ai/models/backup_model.py
```

### Restore from Backup
```bash
# List available backups
python ai/models/restore_model.py

# Restore specific backup (1 = newest)
python ai/models/restore_model.py 1
```

### Training (Organized)
```bash
python ai/quick_retrain_organized.py
```

### Evaluation
```bash
python ai/evaluate_organized.py --episodes 50
```

## Backup Management

- Maximum 3 backups kept automatically
- Oldest backups removed when limit exceeded
- Backups created before each training session
- Safety backup created before restoring

## Model Information

- Algorithm: DQN (Deep Q-Network)
- Framework: Stable Baselines3
- Input: 28-dimensional observation space
- Output: 8 discrete actions
- File Size: ~133 KB per model

## Usage Examples

```bash
# 1. Train with automatic backup
python ai/quick_retrain_organized.py

# 2. Evaluate current model
python ai/evaluate_organized.py

# 3. Backup before experimenting
python ai/models/backup_model.py

# 4. Restore if experiment fails
python ai/models/restore_model.py 1
```
'''
    
    with open("ai/models/README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("Created: ai/models/README.md")

def main():
    """Create all utility scripts."""
    print("Creating utility scripts (Windows compatible)...")
    print("=" * 50)
    
    create_backup_utility()
    create_restore_utility()
    create_organized_training()
    create_readme()
    
    print("=" * 50)
    print("SUCCESS: All utilities created!")
    print()
    print("Available utilities:")
    print("  ai/models/backup_model.py")
    print("  ai/models/restore_model.py") 
    print("  ai/quick_retrain_organized.py")
    print("  ai/models/README.md")
    print()
    print("Test the utilities:")
    print("  python ai/models/backup_model.py")
    print("  python ai/quick_retrain_organized.py")

if __name__ == "__main__":
    main()