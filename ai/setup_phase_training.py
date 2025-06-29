# setup_phase_training.py
#!/usr/bin/env python3
"""
setup_phase_training.py - Setup and validation script for phase-based training system
"""

import os
import sys
import json
import shutil
from pathlib import Path

# Ensure we can import from project root
script_dir = Path(__file__).parent
project_root = script_dir
sys.path.insert(0, str(project_root))

def create_directory_structure():
    """Create required directory structure."""
    print("📁 Creating directory structure...")
    
    directories = [
        "ai/models/current",
        "ai/event_log",
        "tensorboard",
        "config"
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"   ✅ {directory}")

def update_rewards_config():
    """Update rewards_config.json with phase-based configurations."""
    print("⚙️ Updating rewards configuration...")
    
    config_path = "config/rewards_config.json"
    
    # Phase-based rewards configuration
    phase_rewards = {
        "phase_based": {
            "description": "Phase-based rewards following AI_GAME_OVERVIEW.md specifications",
            "movement_phase": {
                "move_tactical_good": 0.3,
                "move_tactical_ok": 0.1,
                "move_tactical_bad": -0.1,
                "move_to_optimal_range": 0.3,
                "move_closer_melee": 0.3,
                "move_away_unnecessary": -0.1,
                "wait_movement": -0.1
            },
            "shooting_phase": {
                "shoot_priority_1_target": 2.0,
                "shoot_priority_2_target": 1.5,
                "shoot_priority_3_target": 1.0,
                "shoot_kill_bonus": 5.0,
                "shoot_no_overkill_bonus": 1.0,
                "shoot_high_threat": 1.5,
                "shoot_setup_melee": 2.0,
                "shoot_invalid_target": -0.5,
                "wait_shooting": -0.05
            },
            "charge_phase": {
                "charge_priority_1_target": 1.5,
                "charge_priority_2_target": 1.0,
                "charge_priority_3_target": 0.5,
                "charge_successful": 0.5,
                "charge_tactical_position": 0.3,
                "charge_invalid_target": -0.3,
                "wait_charging": -0.05
            },
            "combat_phase": {
                "attack_priority_1_target": 2.0,
                "attack_priority_2_target": 1.0,
                "attack_kill_bonus": 5.0,
                "attack_no_overkill_bonus": 1.0,
                "attack_high_threat": 1.5,
                "attack_not_adjacent": -0.3,
                "wait_combat": -0.05
            },
            "game_outcomes": {
                "victory": 10.0,
                "defeat": -10.0,
                "turn_limit_penalty": -1.0,
                "unit_killed": -3.0,
                "enemy_unit_killed": 3.0
            }
        },
        "phase_simplified": {
            "description": "Simplified phase-based rewards for initial learning",
            "movement_phase": {
                "move_good": 0.2,
                "move_bad": -0.1,
                "wait": -0.05
            },
            "shooting_phase": {
                "shoot_hit": 1.0,
                "shoot_kill": 3.0,
                "shoot_miss": -0.2,
                "wait": -0.05
            },
            "charge_phase": {
                "charge_success": 0.5,
                "charge_fail": -0.2,
                "wait": -0.05
            },
            "combat_phase": {
                "attack_hit": 1.0,
                "attack_kill": 3.0,
                "attack_miss": -0.2,
                "wait": -0.05
            },
            "game_outcomes": {
                "victory": 10.0,
                "defeat": -10.0,
                "unit_killed": -2.0,
                "enemy_killed": 2.0
            }
        }
    }
    
    # Load existing config if it exists
    existing_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                existing_config = json.load(f)
        except Exception as e:
            print(f"   ⚠️ Error reading existing config: {e}")
    
    # Merge phase-based configs
    existing_config.update(phase_rewards)
    
    # Save updated config
    with open(config_path, 'w') as f:
        json.dump(existing_config, f, indent=2)
    
    print(f"   ✅ Updated {config_path}")
    print(f"   📝 Added phase_based and phase_simplified reward configs")

def update_training_config():
    """Add phase-based training configuration."""
    print("⚙️ Updating training configuration...")
    
    config_path = "config/training_config.json"
    
    phase_training_config = {
        "phase_based": {
            "description": "Optimized for phase-based environment",
            "total_timesteps": 500000,
            "model_params": {
                "policy": "MlpPolicy",
                "verbose": 1,
                "buffer_size": 100000,
                "learning_rate": 0.0005,
                "learning_starts": 10000,
                "batch_size": 128,
                "train_freq": 1,
                "target_update_interval": 1000,
                "exploration_fraction": 0.3,
                "exploration_final_eps": 0.02,
                "tensorboard_log": "./tensorboard/"
            }
        }
    }
    
    # Load existing config
    existing_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                existing_config = json.load(f)
        except Exception as e:
            print(f"   ⚠️ Error reading existing config: {e}")
    
    # Merge phase-based config
    existing_config.update(phase_training_config)
    
    # Save updated config
    with open(config_path, 'w') as f:
        json.dump(existing_config, f, indent=2)
    
    print(f"   ✅ Updated {config_path}")
    print(f"   📝 Added phase_based training config")

def validate_environment():
    """Validate that the phase-based environment works correctly."""
    print("🧪 Validating phase-based environment...")
    
    try:
        # Import and test environment
        from ai.gym40k_phases import W40KPhasesEnv, register_environment
        
        # Register environment
        register_environment()
        print("   ✅ Environment registration successful")
        
        # Create environment
        env = W40KPhasesEnv()
        print("   ✅ Environment creation successful")
        
        # Test reset
        obs, info = env.reset()
        print(f"   ✅ Environment reset - observation shape: {obs.shape}")
        print(f"      Turn: {info['turn']}, Phase: {info['phase']}")
        print(f"      AI units: {info['ai_units_alive']}, Enemy units: {info['enemy_units_alive']}")
        
        # Test a few steps
        for step in range(5):
            eligible_units = len(env._get_eligible_units())
            if eligible_units == 0:
                print(f"      Step {step}: No eligible units, phase will advance")
                continue
            
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            print(f"      Step {step}: Phase {info['phase']}, Reward {reward:.2f}, Done {done}")
            
            if done:
                print(f"      Game ended! Winner: {info['winner']}")
                break
        
        env.close()
        print("   ✅ Environment validation successful")
        return True
        
    except Exception as e:
        print(f"   ❌ Environment validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def validate_config_loader():
    """Validate configuration loading."""
    print("🔧 Validating configuration loader...")
    
    try:
        from config_loader import get_config_loader
        
        config = get_config_loader()
        print("   ✅ Config loader creation successful")
        
        # Test loading different configs
        game_config = config.get_game_config()
        print(f"   ✅ Game config loaded - board size: {game_config['game_rules']['board_size']}")
        
        training_configs = config.list_training_configs()
        print(f"   ✅ Training configs available: {training_configs}")
        
        rewards_configs = config.list_rewards_configs()
        print(f"   ✅ Rewards configs available: {rewards_configs}")
        
        # Test loading phase-based configs if they exist
        if "phase_based" in training_configs:
            phase_training = config.load_training_config("phase_based")
            print(f"   ✅ Phase-based training config loaded")
        
        if "phase_based" in rewards_configs:
            phase_rewards = config.load_rewards_config("phase_based")
            print(f"   ✅ Phase-based rewards config loaded")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Config loader validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_quick_start_scripts():
    """Create quick-start scripts for common operations."""
    print("📝 Creating quick-start scripts...")
    
    # Quick train script
    train_script = """#!/usr/bin/env python3
# quick_train_phases.py - Quick start training with phase-based system

import subprocess
import sys

def main():
    print("🚀 Starting Phase-Based Training")
    print("Using simplified rewards for initial learning...")
    
    # Start with simplified rewards for faster initial learning
    cmd = [
        sys.executable, "ai/train_phases.py",
        "--training-config", "phase_based",
        "--episodes", "20"
    ]
    
    try:
        result = subprocess.run(cmd, check=True)
        print("✅ Training completed successfully!")
        print("Next steps:")
        print("  - Monitor: tensorboard --logdir ./tensorboard/")
        print("  - Evaluate: python ai/evaluate_phases.py")
        print("  - Continue: python ai/train_phases.py --append")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Training failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""
    
    with open("quick_train_phases.py", "w") as f:
        f.write(train_script)
    
    # Quick test script
    test_script = """#!/usr/bin/env python3
# quick_test_phases.py - Quick test of phase-based AI

import subprocess
import sys

def main():
    print("🧪 Testing Phase-Based AI")
    
    cmd = [
        sys.executable, "ai/evaluate_phases.py",
        "--episodes", "10",
        "--deterministic",
        "--analyze-phases"
    ]
    
    try:
        result = subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"❌ Testing failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
"""
    
    with open("quick_test_phases.py", "w") as f:
        f.write(test_script)
    
    print("   ✅ Created quick_train_phases.py")
    print("   ✅ Created quick_test_phases.py")

def check_dependencies():
    """Check if required dependencies are installed."""
    print("📦 Checking dependencies...")
    
    required_packages = [
        "stable_baselines3",
        "gymnasium",
        "numpy",
        "torch"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"   ✅ {package}")
        except ImportError:
            print(f"   ❌ {package} - MISSING")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️  Missing packages: {', '.join(missing_packages)}")
        print("Install with: pip install stable-baselines3[extra] gymnasium numpy torch")
        return False
    
    return True

def backup_old_system():
    """Backup the old training system."""
    print("💾 Backing up old training system...")
    
    backup_files = [
        ("ai/gym40k.py", "ai/gym40k_old.py"),
        ("ai/train.py", "ai/train_old.py")
    ]
    
    for src, dst in backup_files:
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"   ✅ Backed up {src} -> {dst}")
    
    print("   📝 Old system preserved for reference")

def create_usage_documentation():
    """Create usage documentation."""
    print("📚 Creating usage documentation...")
    
    doc_content = """# Phase-Based W40K AI Training System

## Overview
This system implements the AI behavior specified in AI_GAME_OVERVIEW.md with proper phase separation:
- Movement Phase: Units move tactically
- Shooting Phase: Ranged units engage with priority targeting
- Charge Phase: Units charge into combat positions  
- Combat Phase: Melee combat resolution

## Quick Start

### 1. Train a new model
```bash
python quick_train_phases.py
```

### 2. Test trained model
```bash
python quick_test_phases.py
```

### 3. Advanced training
```bash
# Train with specific configuration
python ai/train_phases.py --training-config phase_based

# Continue existing training
python ai/train_phases.py --append

# Quick debug training
python ai/train_phases.py --training-config debug --episodes 10
```

### 4. Evaluation
```bash
# Standard evaluation
python ai/evaluate_phases.py --episodes 50

# Detailed phase analysis
python ai/evaluate_phases.py --analyze-phases

# Compare models
python ai/evaluate_phases.py --compare model1.zip model2.zip
```

## Configuration

### Training Configs (config/training_config.json)
- `phase_based`: Optimized for phase-based learning
- `debug`: Quick testing (50k timesteps)
- `default`: Balanced training

### Rewards Configs (config/rewards_config.json)
- `phase_based`: Full tactical reward system
- `phase_simplified`: Simplified for initial learning
- `phase_aggressive`: Encourages decisive action

## AI Behavior

The AI follows AI_GAME_OVERVIEW.md specifications:

### Shooting Priority
1. High-threat enemies melee can charge but won't kill
2. Enemies that can be killed in 1 shooting phase
3. High-threat, low-HP enemies

### Charge Priority  
1. Enemies that can be killed in 1 melee phase
2. High-threat, low-HP enemies with HP >= unit's damage
3. High-threat, lowest-HP enemies

### Combat Priority
1. Enemies that can be killed in 1 attack
2. High-threat enemies with lowest HP

## Monitoring

```bash
# Monitor training progress
tensorboard --logdir ./tensorboard/

# View logs
tail -f ai/event_log/phase_based_replay_*.json
```

## Troubleshooting

### Environment Issues
- Ensure ai/scenario.json exists with valid unit data
- Check TypeScript unit definitions in frontend/src/roster/
- Verify config files are properly formatted

### Training Issues  
- Start with phase_simplified rewards for initial learning
- Use debug config for quick testing
- Monitor tensorboard for learning progress
- Check action distribution in evaluation

### Performance Issues
- AI should achieve >50% win rate after 200k+ timesteps
- Action efficiency should be >60%
- Phase rewards should show positive trends

## File Structure

```
ai/
├── gym40k_phases.py      # Phase-based environment
├── train_phases.py       # Training script
├── evaluate_phases.py    # Evaluation script  
├── scenario.json         # Unit positions and players
└── event_log/           # Replay files

config/
├── training_config.json  # Training parameters
├── rewards_config.json   # Reward configurations
└── game_config.json      # Game rules

quick_train_phases.py     # Quick start training
quick_test_phases.py      # Quick start testing
```
"""
    
    with open("PHASE_TRAINING_GUIDE.md", "w") as f:
        f.write(doc_content)
    
    print("   ✅ Created PHASE_TRAINING_GUIDE.md")

def main():
    """Main setup function."""
    print("🎮 W40K Phase-Based Training System Setup")
    print("=" * 60)
    print("Setting up AI training system following AI_GAME_OVERVIEW.md specifications")
    print()
    
    success = True
    
    # Step 1: Check dependencies
    if not check_dependencies():
        print("\n❌ Dependencies missing. Please install required packages first.")
        return 1
    
    # Step 2: Create directory structure
    create_directory_structure()
    
    # Step 3: Backup old system
    backup_old_system()
    
    # Step 4: Update configurations
    update_rewards_config()
    update_training_config()
    
    # Step 5: Validate configuration loader
    if not validate_config_loader():
        success = False
    
    # Step 6: Validate environment
    if not validate_environment():
        success = False
    
    # Step 7: Create quick-start scripts
    create_quick_start_scripts()
    
    # Step 8: Create documentation
    create_usage_documentation()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ SETUP COMPLETE!")
        print()
        print("🚀 Next Steps:")
        print("   1. Start training: python quick_train_phases.py")
        print("   2. Monitor progress: tensorboard --logdir ./tensorboard/")
        print("   3. Test AI: python quick_test_phases.py")
        print("   4. Read guide: PHASE_TRAINING_GUIDE.md")
        print()
        print("📊 Key Features:")
        print("   ✅ Phase-based AI following AI_GAME_OVERVIEW.md")
        print("   ✅ Tactical priority targeting system")
        print("   ✅ Proper movement/shooting/charge/combat phases")
        print("   ✅ Configurable reward systems")
        print("   ✅ Comprehensive evaluation tools")
        print()
        print("📁 Files Created:")
        print("   • ai/gym40k_phases.py - Phase-based environment")
        print("   • ai/train_phases.py - Training script")
        print("   • ai/evaluate_phases.py - Evaluation script")
        print("   • quick_train_phases.py - Quick start training")
        print("   • quick_test_phases.py - Quick start testing")
        print("   • PHASE_TRAINING_GUIDE.md - Complete guide")
        print("   • Updated config/rewards_config.json")
        print("   • Updated config/training_config.json")
        
        return 0
    else:
        print("❌ SETUP FAILED!")
        print("   Please check error messages above and resolve issues.")
        print("   Common issues:")
        print("   • Missing ai/scenario.json file")
        print("   • Invalid TypeScript unit definitions")
        print("   • Configuration file errors")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)