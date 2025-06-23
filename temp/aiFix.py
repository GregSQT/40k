#!/usr/bin/env python3
"""
W40K AI System Comparison and Restoration
Check what changed from your original setup and restore it if needed.
"""

import os
import json
import shutil
from datetime import datetime

def analyze_current_system():
    """Analyze the current state of the system."""
    print("=== CURRENT SYSTEM ANALYSIS ===")
    
    # Check files
    files_to_check = {
        "ai/gym40k.py": "Gym environment",
        "ai/gym40k.py.backup": "Original gym backup",
        "ai/gym40k.py.backup2": "Second backup", 
        "ai/scenario.json": "Current scenario",
        "ai/rewards_master.json": "Current rewards",
        "ai/model.zip": "Trained model",
        "ai/train.py": "Original training script",
        "ai/simple_train.py": "New training script",
        "generate_scenario.py": "Scenario generator",
        "train_ai.py": "Direct training script",
        "train_ai_bypass.py": "Bypass training script"
    }
    
    print("Files present:")
    for file_path, description in files_to_check.items():
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
            print(f"  ✓ {file_path} ({description}) - {size} bytes, modified {mod_time}")
        else:
            print(f"  ✗ {file_path} ({description}) - MISSING")
    
    # Check current scenario
    if os.path.exists("ai/scenario.json"):
        print("\n=== CURRENT SCENARIO ===")
        with open("ai/scenario.json", "r") as f:
            scenario = json.load(f)
        print(f"Units: {len(scenario)}")
        for unit in scenario:
            print(f"  {unit['id']}: {unit['unit_type']} (P{unit['player']}) at ({unit['col']},{unit['row']}) - HP:{unit['cur_hp']}/{unit['hp_max']}")
    
    # Check current rewards
    if os.path.exists("ai/rewards_master.json"):
        print("\n=== CURRENT REWARDS ===")
        with open("ai/rewards_master.json", "r") as f:
            rewards = json.load(f)
        for unit_type, reward_dict in rewards.items():
            print(f"{unit_type}:")
            key_rewards = ["win", "lose", "move_close", "ranged_attack", "attack", "wait"]
            for key in key_rewards:
                if key in reward_dict:
                    print(f"  {key}: {reward_dict[key]}")

def compare_with_original():
    """Compare current system with original values from project knowledge."""
    print("\n=== COMPARISON WITH ORIGINAL ===")
    
    # Original rewards from project knowledge
    original_rewards = {
        "SpaceMarineRanged": {
            "move_close": 0.2,
            "move_away": 0.4,
            "move_to_safe": 0.6,
            "move_to_rng": 0.8,
            "move_to_charge": 0.2,
            "move_to_rng_charge": 0.3,
            "ranged_attack": 0.2,
            "enemy_killed_r": 0.4,
            "enemy_killed_lowests_hp_r": 0.6,
            "enemy_killed_no_overkill_r": 0.8,
            "charge_success": 0.2,
            "being_charged": -0.4,
            "attack": 0.4,
            "enemy_killed_m": 0.2,
            "enemy_killed_lowests_hp_m": 0.3,
            "enemy_killed_no_overkill_m": 0.4,
            "loose_hp": -0.4,
            "killed_in_melee": -0.8,
            "win": 1,
            "lose": -1,
            "atk_wasted_r": -0.8,
            "atk_wasted_m": -0.8,
            "wait": -0.9
        },
        "SpaceMarineMelee": {
            "move_close": 0.2,
            "move_away": -0.6,
            "move_to_safe": 0.2,
            "move_to_rng": 0.4,
            "move_to_charge": 0.6,
            "move_to_rng_charge": 0.8,
            "ranged_attack": 0.2,
            "enemy_killed_r": 0.4,
            "enemy_killed_lowests_hp_r": 0.6,
            "enemy_killed_no_overkill_r": 0.8,
            "charge_success": 0.8,
            "being_charged": -0.4,
            "attack": 0.4,
            "enemy_killed_m": 0.4,
            "enemy_killed_lowests_hp_m": 0.6,
            "enemy_killed_no_overkill_m": 0.8,
            "loose_hp": -0.4,
            "killed_in_melee": -0.8,
            "win": 1,
            "lose": -1,
            "atk_wasted_r": -0.8,
            "atk_wasted_m": -0.8,
            "wait": -0.9
        }
    }
    
    # Compare rewards
    if os.path.exists("ai/rewards_master.json"):
        with open("ai/rewards_master.json", "r") as f:
            current_rewards = json.load(f)
        
        print("REWARDS COMPARISON:")
        for unit_type in ["SpaceMarineRanged", "SpaceMarineMelee"]:
            print(f"\n{unit_type}:")
            orig = original_rewards.get(unit_type, {})
            curr = current_rewards.get(unit_type, {})
            
            all_keys = set(orig.keys()) | set(curr.keys())
            for key in sorted(all_keys):
                orig_val = orig.get(key, "MISSING")
                curr_val = curr.get(key, "MISSING")
                
                if orig_val != curr_val:
                    print(f"  {key}: {orig_val} → {curr_val} {'❌ CHANGED' if orig_val != 'MISSING' and curr_val != 'MISSING' else '⚠️  DIFFERENT'}")
    
    # Original training config
    print("\nTRAINING CONFIGURATION:")
    print("Original values from your train.py:")
    print("  total_timesteps: 1,000,000 (or 100,000 for debug)")
    print("  exploration_fraction: 0.5")
    print("  buffer_size: 10,000")
    print("  learning_rate: 1e-3")
    print("  learning_starts: 100")
    print("  target_update_interval: 500")
    
    # Check what's currently used
    scripts_to_check = ["train_ai.py", "train_ai_bypass.py", "ai/simple_train.py"]
    for script in scripts_to_check:
        if os.path.exists(script):
            print(f"\nChecking {script}...")
            with open(script, "r") as f:
                content = f.read()
                if "buffer_size" in content:
                    # Extract buffer size
                    import re
                    match = re.search(r'buffer_size=(\d+)', content)
                    if match:
                        print(f"  buffer_size: {match.group(1)}")
                if "total_timesteps = " in content:
                    match = re.search(r'total_timesteps = (\d+)', content)
                    if match:
                        print(f"  default timesteps: {match.group(1)}")

def restore_original_rewards():
    """Restore the original reward values."""
    print("\n=== RESTORING ORIGINAL REWARDS ===")
    
    original_rewards = {
        "SpaceMarineRanged": {
            "move_close": 0.2,
            "move_away": 0.4,
            "move_to_safe": 0.6,
            "move_to_rng": 0.8,
            "move_to_charge": 0.2,
            "move_to_rng_charge": 0.3,
            "ranged_attack": 0.2,
            "enemy_killed_r": 0.4,
            "enemy_killed_lowests_hp_r": 0.6,
            "enemy_killed_no_overkill_r": 0.8,
            "charge_success": 0.2,
            "being_charged": -0.4,
            "attack": 0.4,
            "enemy_killed_m": 0.2,
            "enemy_killed_lowests_hp_m": 0.3,
            "enemy_killed_no_overkill_m": 0.4,
            "loose_hp": -0.4,
            "killed_in_melee": -0.8,
            "win": 1,
            "lose": -1,
            "atk_wasted_r": -0.8,
            "atk_wasted_m": -0.8,
            "wait": -0.9
        },
        "SpaceMarineMelee": {
            "move_close": 0.2,
            "move_away": -0.6,
            "move_to_safe": 0.2,
            "move_to_rng": 0.4,
            "move_to_charge": 0.6,
            "move_to_rng_charge": 0.8,
            "ranged_attack": 0.2,
            "enemy_killed_r": 0.4,
            "enemy_killed_lowests_hp_r": 0.6,
            "enemy_killed_no_overkill_r": 0.8,
            "charge_success": 0.8,
            "being_charged": -0.4,
            "attack": 0.4,
            "enemy_killed_m": 0.4,
            "enemy_killed_lowests_hp_m": 0.6,
            "enemy_killed_no_overkill_m": 0.8,
            "loose_hp": -0.4,
            "killed_in_melee": -0.8,
            "win": 1,
            "lose": -1,
            "atk_wasted_r": -0.8,
            "atk_wasted_m": -0.8,
            "wait": -0.9
        }
    }
    
    # Backup current rewards
    if os.path.exists("ai/rewards_master.json"):
        backup_name = f"ai/rewards_master.json.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy("ai/rewards_master.json", backup_name)
        print(f"Backed up current rewards to {backup_name}")
    
    # Write original rewards
    with open("ai/rewards_master.json", "w", encoding="utf-8") as f:
        json.dump(original_rewards, f, indent=2)
    
    print("✓ Restored original reward values")

def restore_original_scenario():
    """Restore a scenario closer to your original TypeScript setup."""
    print("\n=== RESTORING ORIGINAL-STYLE SCENARIO ===")
    
    # Based on your original Scenario.ts from project knowledge
    original_scenario = [
        {
            "id": 1,
            "unit_type": "Intercessor", 
            "player": 0,
            "col": 23,
            "row": 12,
            "cur_hp": 3,
            "hp_max": 3,
            "move": 4,
            "rng_rng": 8,
            "rng_dmg": 2,
            "cc_dmg": 1,
            "is_ranged": True,
            "is_melee": False,
            "alive": True
        },
        {
            "id": 2,
            "unit_type": "AssaultIntercessor",
            "player": 0,
            "col": 1,
            "row": 12,
            "cur_hp": 4,
            "hp_max": 4,
            "move": 6,
            "rng_rng": 4,
            "rng_dmg": 1,
            "cc_dmg": 2,
            "is_ranged": False,
            "is_melee": True,
            "alive": True
        },
        {
            "id": 3,
            "unit_type": "Intercessor",
            "player": 1,
            "col": 0,
            "row": 5,
            "cur_hp": 3,
            "hp_max": 3,
            "move": 4,
            "rng_rng": 8,
            "rng_dmg": 2,
            "cc_dmg": 1,
            "is_ranged": True,
            "is_melee": False,
            "alive": True
        },
        {
            "id": 4,
            "unit_type": "AssaultIntercessor",
            "player": 1,
            "col": 22,
            "row": 3,
            "cur_hp": 4,
            "hp_max": 4,
            "move": 6,
            "rng_rng": 4,
            "rng_dmg": 1,
            "cc_dmg": 2,
            "is_ranged": False,
            "is_melee": True,
            "alive": True
        }
    ]
    
    # Backup current scenario
    if os.path.exists("ai/scenario.json"):
        backup_name = f"ai/scenario.json.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy("ai/scenario.json", backup_name)
        print(f"Backed up current scenario to {backup_name}")
    
    # Write original scenario
    with open("ai/scenario.json", "w", encoding="utf-8") as f:
        json.dump(original_scenario, f, indent=2)
    
    print("✓ Restored original scenario layout")

def create_original_style_training():
    """Create a training script that matches your original configuration."""
    print("\n=== CREATING ORIGINAL-STYLE TRAINING ===")
    
    training_script = '''#!/usr/bin/env python3
# train_ai_original.py - Training script matching your original configuration

import os
import sys
import json
import subprocess

# Add current directory to path
sys.path.insert(0, os.getcwd())

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from ai.gym40k import W40KEnv

######################################################################################
### Training configuration - RESTORED FROM ORIGINAL
total_timesteps_setup = 1_000_000  # Total timesteps for training. Debug: 100_000
exploration_fraction_setup = 0.5   # Fraction of timesteps spent exploring
######################################################################################

def parse_args():
    resume = None
    debug = False
    for arg in sys.argv[1:]:
        if arg.lower() == "--resume":
            resume = True
        elif arg.lower() == "--new":
            resume = False
        elif arg.lower() == "--debug":
            debug = True
    return resume, debug

def main():
    print("🔧 W40K AI Training - Original Configuration")
    print("=" * 50)
    
    resume_flag, debug_mode = parse_args()
    
    # Adjust timesteps for debug mode
    total_timesteps = 100_000 if debug_mode else total_timesteps_setup
    if debug_mode:
        print("🐛 Debug mode: Using 100,000 timesteps")
    else:
        print(f"🎯 Full training: Using {total_timesteps:,} timesteps")
    
    # Generate scenario if needed
    if not os.path.exists("ai/scenario.json"):
        print("🔧 Regenerating scenario.json...")
        try:
            subprocess.run(["python", "generate_scenario.py"], check=True)
            print("✅ Scenario generated")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("⚠️  Using default scenario")
    
    # Create environment
    env = W40KEnv()
    check_env(env)  # Good for debugging!
    
    print(f"Environment info:")
    print(f"  Units: {len(env.units)}")
    print(f"  Board size: {env.board_size}")
    print(f"  Action space: {env.action_space}")
    
    model_path = "ai/model.zip"
    
    if os.path.exists(model_path):
        if resume_flag is None:
            # No explicit flag, default: resume
            print("Model exists. Resuming training from last checkpoint (default).")
            resume = True
        else:
            resume = resume_flag
        if resume:
            print("Resuming from previous model...")
            model = DQN.load(model_path, env=env)
        else:
            print("Starting new model (overwriting previous model)...")
            model = DQN(
                "MlpPolicy",
                env,
                verbose=1,
                buffer_size=10000,  # ORIGINAL VALUE
                learning_rate=1e-3,
                learning_starts=100,  # ORIGINAL VALUE
                batch_size=64,
                train_freq=4,
                target_update_interval=500,  # ORIGINAL VALUE
                exploration_fraction=exploration_fraction_setup,  # ORIGINAL VALUE
                exploration_final_eps=0.05,
                tensorboard_log="./tensorboard/"
            )
    else:
        print("No previous model found. Creating new model...")
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            buffer_size=10000,  # ORIGINAL VALUE
            learning_rate=1e-3,
            learning_starts=100,  # ORIGINAL VALUE  
            batch_size=64,
            train_freq=4,
            target_update_interval=500,  # ORIGINAL VALUE
            exploration_fraction=exploration_fraction_setup,  # ORIGINAL VALUE
            exploration_final_eps=0.05,
            tensorboard_log="./tensorboard/"
        )

    print(f"🚀 Starting training for {total_timesteps:,} timesteps...")
    print("📊 Monitor with: tensorboard --logdir ./tensorboard/")
    print()

    try:
        model.learn(total_timesteps=total_timesteps)
        print("✅ Training completed successfully!")
    except KeyboardInterrupt:
        print("⏹️  Training interrupted by user")
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Save model
    os.makedirs("ai", exist_ok=True)
    model.save(model_path)
    print(f"💾 Model saved to {model_path}")
    
    # Save episode logs if available
    if hasattr(env, "episode_logs") and env.episode_logs:
        # Find best and worst by total reward
        best_log, best_reward = max(env.episode_logs, key=lambda x: x[1])
        worst_log, worst_reward = min(env.episode_logs, key=lambda x: x[1])
        
        with open("ai/best_event_log.json", "w") as f:
            json.dump(best_log, f, indent=2)
        with open("ai/worst_event_log.json", "w") as f:
            json.dump(worst_log, f, indent=2)
        
        print(f"📋 Saved best and worst episode logs: rewards {best_reward}, {worst_reward}")
    
    env.close()
    print("🎉 Training session completed!")
    return True

if __name__ == "__main__":
    main()
'''
    
    with open("train_ai_original.py", "w", encoding="utf-8") as f:
        f.write(training_script)
    
    print("✓ Created train_ai_original.py with your original configuration")

def show_file_tree():
    """Show current file tree structure."""
    print("\n=== CURRENT FILE TREE ===")
    
    def print_tree(path, prefix="", max_depth=3, current_depth=0):
        if current_depth > max_depth:
            return
            
        items = []
        try:
            for item in sorted(os.listdir(path)):
                if not item.startswith('.'):
                    item_path = os.path.join(path, item)
                    items.append((item, os.path.isdir(item_path)))
        except PermissionError:
            return
        
        for i, (item, is_dir) in enumerate(items):
            is_last = i == len(items) - 1
            current_prefix = "└── " if is_last else "├── "
            print(f"{prefix}{current_prefix}{item}{'/' if is_dir else ''}")
            
            if is_dir and current_depth < max_depth:
                next_prefix = prefix + ("    " if is_last else "│   ")
                print_tree(os.path.join(path, item), next_prefix, max_depth, current_depth + 1)
    
    print_tree(".")

def main():
    """Main diagnostic and restoration function."""
    print("W40K AI System Analysis & Restoration")
    print("=" * 50)
    
    # Analyze current state
    analyze_current_system()
    
    # Compare with original
    compare_with_original()
    
    # Show file tree
    show_file_tree()
    
    print("\n" + "=" * 50)
    print("ANALYSIS COMPLETE")
    print("\nRECOMMENDATIONS:")
    print("1. Your AI is losing because it trained with simplified rewards")
    print("2. The scenario is different from your original TypeScript setup")
    print("3. Training parameters were changed from your original values")
    
    # Ask for restoration
    print("\nWould you like to restore the original configuration?")
    choice = input("Enter 'y' to restore original rewards, scenario, and training: ")
    
    if choice.lower() in ['y', 'yes']:
        restore_original_rewards()
        restore_original_scenario()
        create_original_style_training()
        
        print("\n" + "=" * 50)
        print("🎉 RESTORATION COMPLETE!")
        print("\nNow you can:")
        print("  python train_ai_original.py --new    (start fresh with original config)")
        print("  python train_ai_original.py --debug  (quick training)")
        print("  python test_ai.py                    (test after retraining)")
        print("\nThe restored system uses your original:")
        print("  • Reward values (win=1, lose=-1, wait=-0.9, etc.)")
        print("  • Scenario layout from Scenario.ts")
        print("  • Training parameters (1M timesteps, exploration=0.5)")

if __name__ == "__main__":
    main()