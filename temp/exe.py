#!/usr/bin/env python3
"""
step_by_step_setup.py - Implementation for your current W40K AI setup
"""

import os
import shutil
import json
from datetime import datetime

def step1_create_web_replay_logger():
    """Step 1: Create the web replay logger file."""
    print("🔧 Step 1: Creating web_replay_logger.py...")
    
    # Run the quick_setup.py script we created earlier
    try:
        exec(open("quick_setup.py").read())
        print("✅ Step 1 complete: web_replay_logger.py created")
        return True
    except FileNotFoundError:
        print("❌ quick_setup.py not found. Creating web_replay_logger.py manually...")
        # Create the file manually (code would be here)
        return False
    except Exception as e:
        print(f"❌ Step 1 failed: {e}")
        return False

def step2_backup_existing_files():
    """Step 2: Backup existing train.py and evaluate.py."""
    print("\n🔧 Step 2: Backing up existing files...")
    
    files_to_backup = ["ai/train.py", "ai/evaluate.py"]
    backup_dir = f"ai/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    for file_path in files_to_backup:
        if os.path.exists(file_path):
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, os.path.basename(file_path))
            shutil.copy2(file_path, backup_path)
            print(f"   📦 Backed up: {file_path} → {backup_path}")
    
    print("✅ Step 2 complete: Files backed up")
    return True

def step3_check_current_train_py():
    """Step 3: Analyze current train.py structure."""
    print("\n🔧 Step 3: Analyzing current train.py...")
    
    if not os.path.exists("ai/train.py"):
        print("❌ ai/train.py not found!")
        return False
    
    with open("ai/train.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # Check what's already in the file
    has_imports = "from stable_baselines3 import DQN" in content
    has_env_setup = "W40KEnv()" in content
    has_enhanced_training = "enhanced_training_with_replay" in content
    has_save_logs = "save_training_logs_with_replay" in content
    
    print(f"   📋 Analysis results:")
    print(f"      ✅ Has DQN import: {has_imports}")
    print(f"      ✅ Has environment setup: {has_env_setup}")
    print(f"      📝 Has enhanced training: {has_enhanced_training}")
    print(f"      📝 Has save logs function: {has_save_logs}")
    
    print("✅ Step 3 complete: Structure analyzed")
    return {
        "has_imports": has_imports,
        "has_env_setup": has_env_setup,
        "has_enhanced_training": has_enhanced_training,
        "has_save_logs": has_save_logs,
        "content": content
    }

def step4_update_train_py(analysis):
    """Step 4: Update train.py with web replay functionality."""
    print("\n🔧 Step 4: Updating train.py...")
    
    if not analysis:
        print("❌ Cannot update without analysis")
        return False
    
    # Read current content
    with open("ai/train.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    # Add web replay import near the top (after existing imports)
    if "from ai.web_replay_logger import WebReplayIntegration" not in content:
        # Find a good place to insert the import
        import_section = content.find("from datetime import datetime")
        if import_section != -1:
            # Insert after datetime import
            insertion_point = content.find("\n", import_section) + 1
            new_import = """
# Web replay logger import
try:
    from ai.web_replay_logger import WebReplayIntegration
    WEB_REPLAY_AVAILABLE = True
except ImportError:
    WEB_REPLAY_AVAILABLE = False
    print("⚠️  Web replay logger not available")
"""
            content = content[:insertion_point] + new_import + content[insertion_point:]
            print("   📝 Added web replay import")
    
    # Add/update enhanced training function
    enhanced_training_code = '''
def enhanced_training_with_replay(model, total_timesteps):
    """Enhanced training with web-compatible replay capture."""
    if not WEB_REPLAY_AVAILABLE:
        print("🔄 Web replay not available, using standard training...")
        model.learn(total_timesteps=total_timesteps)
        return
    
    print(f"🎬 Enhanced training with web-compatible replay generation")
    
    # Create a new environment with web replay logging
    env_with_replay = model.env
    
    # Check if environment already has web replay (avoid double-wrapping)
    if not hasattr(env_with_replay, 'web_replay_logger'):
        print("🔧 Adding web-compatible replay logging to environment...")
        env_with_replay = WebReplayIntegration.enhance_training_env(env_with_replay)
        model.set_env(env_with_replay)
    
    # Calculate replay intervals (capture every 10% of training)
    replay_interval = max(1000, total_timesteps // 10)
    episode_replays = []
    episode_rewards = []
    episodes_captured = 0
    current_step = 0
    
    try:
        while current_step < total_timesteps:
            if current_step % replay_interval == 0 and current_step > 0:
                # Capture a web-compatible replay episode
                print(f"🎥 Capturing web replay at step {current_step}")
                
                episode_reward, episode_steps, replay_file = run_training_episode_with_web_replay(model, env_with_replay)
                
                if replay_file:
                    episode_replays.append(replay_file)
                    episode_rewards.append(episode_reward)
                    episodes_captured += 1
                    print(f"   ✅ Captured: {replay_file}")
                
                current_step += episode_steps
            else:
                # Regular training step
                remaining_steps = min(1000, total_timesteps - current_step)
                model.learn(total_timesteps=remaining_steps)
                current_step += remaining_steps
        
        # Final training if needed
        if current_step < total_timesteps:
            model.learn(total_timesteps=total_timesteps - current_step)
        
        print(f"✅ Training completed with {episodes_captured} web replays captured")
        
        # Select best and worst replays and copy to standard locations
        if episode_replays and episode_rewards:
            best_idx = episode_rewards.index(max(episode_rewards))
            worst_idx = episode_rewards.index(min(episode_rewards))
            
            event_log_dir = "ai/event_log"
            os.makedirs(event_log_dir, exist_ok=True)
            
            best_dest = os.path.join(event_log_dir, "train_best_web_replay.json")
            worst_dest = os.path.join(event_log_dir, "train_worst_web_replay.json")
            
            shutil.copy2(episode_replays[best_idx], best_dest)
            shutil.copy2(episode_replays[worst_idx], worst_dest)
            
            print(f"   🏆 Best web replay: train_best_web_replay.json")
            print(f"   📉 Worst web replay: train_worst_web_replay.json")
        
    except Exception as e:
        print(f"⚠️  Enhanced training failed: {e}")
        print("🔄 Falling back to standard training...")
        model.learn(total_timesteps=total_timesteps)

def run_training_episode_with_web_replay(model, env):
    """Run a single training episode with web replay capture."""
    try:
        # Run episode
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs, info = reset_result
        else:
            obs = reset_result
            
        total_reward = 0
        steps = 0
        done = False
        
        while not done and steps < 1000:  # Prevent infinite episodes
            action, _ = model.predict(obs, deterministic=False)
            step_result = env.step(action)
            
            if len(step_result) == 5:  # New Gym API
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:  # Old Gym API
                obs, reward, done, info = step_result
                
            total_reward += reward
            steps += 1
        
        # Save replay if logger available
        replay_file = None
        if hasattr(env, 'web_replay_logger'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            event_log_dir = "ai/event_log"
            os.makedirs(event_log_dir, exist_ok=True)
            replay_file = os.path.join(event_log_dir, f"web_replay_{timestamp}.json")
            env.web_replay_logger.save_web_replay(replay_file, total_reward)
        
        return total_reward, steps, replay_file
        
    except Exception as e:
        print(f"   ⚠️  Episode failed: {e}")
        return 0.0, 0, None
'''
    
    # Add the enhanced training function if not present or replace if present
    if "def enhanced_training_with_replay(" in content:
        # Replace existing function
        start_marker = "def enhanced_training_with_replay("
        start_pos = content.find(start_marker)
        if start_pos != -1:
            # Find the end of the function (next def or end of file)
            end_pos = content.find("\ndef ", start_pos + 1)
            if end_pos == -1:
                end_pos = len(content)
            
            content = content[:start_pos] + enhanced_training_code.strip() + "\n\n" + content[end_pos:]
            print("   📝 Replaced existing enhanced training function")
    else:
        # Add new function before the main() function
        main_pos = content.find("def main()")
        if main_pos != -1:
            content = content[:main_pos] + enhanced_training_code + "\n" + content[main_pos:]
            print("   📝 Added enhanced training function")
    
    # Write updated content
    with open("ai/train.py", "w", encoding="utf-8") as f:
        f.write(content)
    
    print("✅ Step 4 complete: train.py updated")
    return True

def step5_cleanup_old_logs():
    """Step 5: Remove old simplified event logs."""
    print("\n🔧 Step 5: Cleaning up old simplified logs...")
    
    # Find and remove simplified event logs
    patterns = [
        "ai/event_log/*_event_log.json",
        "ai/event_log/*_event_log_simple.json"
    ]
    
    import glob
    removed_count = 0
    
    for pattern in patterns:
        files = glob.glob(pattern)
        for file_path in files:
            try:
                os.remove(file_path)
                print(f"   🗑️  Removed: {os.path.basename(file_path)}")
                removed_count += 1
            except Exception as e:
                print(f"   ⚠️  Failed to remove {file_path}: {e}")
    
    print(f"✅ Step 5 complete: Removed {removed_count} simplified log files")
    return True

def step6_test_setup():
    """Step 6: Test the setup."""
    print("\n🔧 Step 6: Testing setup...")
    
    # Test imports
    try:
        from ai.web_replay_logger import WebReplayIntegration
        print("   ✅ Web replay logger import successful")
    except ImportError as e:
        print(f"   ❌ Web replay logger import failed: {e}")
        return False
    
    # Check if gym40k is importable
    try:
        from ai.gym40k import W40KEnv
        print("   ✅ W40KEnv import successful")
    except ImportError as e:
        print(f"   ❌ W40KEnv import failed: {e}")
        return False
    
    print("✅ Step 6 complete: Setup tested successfully")
    return True

def main():
    """Main setup function."""
    print("🚀 W40K AI - Web-Compatible Replay Setup")
    print("🎯 Working with your existing train.py structure")
    print("=" * 60)
    
    success = True
    
    # Step 1: Create web replay logger
    if not step1_create_web_replay_logger():
        success = False
    
    # Step 2: Backup existing files
    if success and not step2_backup_existing_files():
        success = False
    
    # Step 3: Analyze current structure
    analysis = None
    if success:
        analysis = step3_check_current_train_py()
        if not analysis:
            success = False
    
    # Step 4: Update train.py
    if success and not step4_update_train_py(analysis):
        success = False
    
    # Step 5: Cleanup old logs
    if success and not step5_cleanup_old_logs():
        success = False
    
    # Step 6: Test setup
    if success and not step6_test_setup():
        success = False
    
    # Results
    print("\n" + "=" * 60)
    if success:
        print("✅ Setup completed successfully!")
        print("\n🎯 Next steps:")
        print("1. Run training: python ai/train.py")
        print("2. Check for web replay files: ls ai/event_log/*web_replay*.json")
        print("3. Load replay files directly in your web app")
        print("\n📁 Generated files will be:")
        print("   • ai/event_log/train_best_web_replay.json")
        print("   • ai/event_log/train_worst_web_replay.json")
        print("   • ai/event_log/train_summary.json")
        print("\n🌐 These files are directly compatible with your ReplayViewer!")
    else:
        print("❌ Setup failed!")
        print("Check the error messages above and try again.")
    
    return success

if __name__ == "__main__":
    main()