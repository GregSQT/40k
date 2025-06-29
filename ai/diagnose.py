#!/usr/bin/env python3
"""
ai/diagnose.py - Diagnostic script to understand game behavior
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
        from ai.gym40k import W40KEnv
    except ImportError:
        try:
            from gym40k import W40KEnv
        except ImportError:
            import importlib.util
            gym_path = os.path.join(script_dir, "gym40k.py")
            if os.path.exists(gym_path):
                spec = importlib.util.spec_from_file_location("gym40k", gym_path)
                gym_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gym_module)
                W40KEnv = gym_module.W40KEnv
            else:
                raise ImportError("Could not find gym40k module")
    
    return DQN, W40KEnv

def diagnose_environment():
    """Diagnose environment behavior without AI model."""
    print("🔍 ENVIRONMENT DIAGNOSIS")
    print("=" * 50)
    
    try:
        DQN, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    
    # Test environment creation
    try:
        env = W40KEnv()
        print("✓ Environment created successfully")
    except Exception as e:
        print(f"❌ Environment creation failed: {e}")
        return False
    
    # Check initial state
    try:
        obs, info = env.reset()
        print(f"✓ Environment reset successful")
        print(f"  Observation shape: {obs.shape}")
        print(f"  Action space: {env.action_space}")
        print(f"  Initial info: {info}")
    except Exception as e:
        print(f"❌ Environment reset failed: {e}")
        return False
    
    # Check units
    if hasattr(env, 'units'):
        print(f"  Initial units: {len(env.units)}")
        for i, unit in enumerate(env.units):
            print(f"    Unit {i}: Player {unit.get('player', '?')}, HP {unit.get('cur_hp', '?')}/{unit.get('hp_max', '?')}, Pos ({unit.get('col', '?')}, {unit.get('row', '?')})")
    
    # Test a few random actions
    print("\n🎲 Testing random actions...")
    for step in range(10):
        action = env.action_space.sample()
        try:
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            print(f"  Step {step+1}: Action {action} -> Reward {reward:.2f}, Done: {done}")
            if 'winner' in info:
                print(f"    Winner: {info['winner']}")
            if done:
                print(f"    Game ended at step {step+1}")
                break
        except Exception as e:
            print(f"  Step {step+1}: Action {action} -> ERROR: {e}")
            break
    
    env.close()
    return True

def diagnose_model_behavior(model_path=None):
    """Diagnose model behavior in detail."""
    if model_path is None:
        from config_loader import get_model_path
        model_path = get_model_path()
    print("\n🤖 MODEL BEHAVIOR DIAGNOSIS")
    print("=" * 50)
    
    try:
        DQN, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        return False
    
    try:
        env = W40KEnv()
        model = DQN.load(model_path, env=env)
        print(f"✓ Model loaded from {model_path}")
    except Exception as e:
        print(f"❌ Model loading failed: {e}")
        return False
    
    # Run one detailed episode
    print("\n🎮 Detailed Episode Analysis...")
    obs, info = env.reset()
    done = False
    step_count = 0
    
    # Track game state
    initial_units = len(env.units) if hasattr(env, 'units') else 0
    print(f"Initial units: {initial_units}")
    
    action_counts = {}
    rewards_history = []
    
    while not done and step_count < 60:  # Limit to 60 steps for analysis
        # Get AI action
        action, _ = model.predict(obs, deterministic=True)
        if hasattr(action, 'item'):
            action = action.item()
        action = int(action)
        
        # Count action frequency
        action_counts[action] = action_counts.get(action, 0) + 1
        
        # Execute action
        old_obs = obs.copy() if hasattr(obs, 'copy') else obs
        obs, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        step_count += 1
        rewards_history.append(reward)
        
        # Detailed logging for first 10 steps
        if step_count <= 10:
            print(f"  Step {step_count:2d}: Action {action}, Reward {reward:6.2f}, Done: {done}")
            if hasattr(env, 'units'):
                alive_units = [u for u in env.units if u.get('alive', True)]
                player_0_alive = len([u for u in alive_units if u.get('player') == 0])
                player_1_alive = len([u for u in alive_units if u.get('player') == 1])
                print(f"            Units alive - P0: {player_0_alive}, P1: {player_1_alive}")
        
        if done:
            winner = info.get('winner', 'Unknown')
            print(f"\n🏁 Game ended at step {step_count}")
            print(f"   Winner: {winner}")
            print(f"   Final info: {info}")
            break
    
    # Analysis summary
    print(f"\n📈 Episode Summary:")
    print(f"   Total steps: {step_count}")
    print(f"   Total reward: {sum(rewards_history):.2f}")
    print(f"   Average reward per step: {sum(rewards_history)/len(rewards_history):.2f}")
    
    print(f"\n🎯 Action Distribution:")
    for action, count in sorted(action_counts.items()):
        percentage = (count / step_count) * 100
        print(f"   Action {action}: {count:2d} times ({percentage:4.1f}%)")
    
    # Check for patterns
    if len(set(action_counts.values())) == 1:
        print("⚠️  Warning: AI is using all actions equally - might not have learned preferences")
    
    most_used_action = max(action_counts, key=action_counts.get)
    if action_counts[most_used_action] > step_count * 0.7:
        print(f"⚠️  Warning: AI heavily favors action {most_used_action} ({action_counts[most_used_action]/step_count*100:.1f}%)")
    
    env.close()
    return True

def diagnose_training_data():
    print("\n📚 TRAINING DATA DIAGNOSIS")
    print("=" * 50)
    
    # Check if model exists and get info
    from config_loader import get_model_path
    model_path = get_model_path()
    if os.path.exists(model_path):
        print(f"✓ Model file found: {model_path}")
        file_size = os.path.getsize(model_path)
        print(f"  File size: {file_size:,} bytes ({file_size/1024/1024:.2f} MB)")
    else:
        print(f"❌ Model file not found: {model_path}")
    
    # Check config files
    config_files = [
        "config/training_config.json",
        "config/rewards_config.json", 
        "config/scenarios.json",
        "ai/scenario.json",
        "ai/rewards_master.json"
    ]
    
    for config_file in config_files:
        if os.path.exists(config_file):
            print(f"✓ Config found: {config_file}")
            try:
                with open(config_file, 'r') as f:
                    data = json.load(f)
                if 'total_timesteps' in str(data):
                    # Training config
                    for key, value in data.items():
                        if isinstance(value, dict) and 'total_timesteps' in value:
                            print(f"    {key}: {value['total_timesteps']:,} timesteps")
            except Exception as e:
                print(f"    Error reading: {e}")
        else:
            print(f"❌ Config missing: {config_file}")
    
    # Check tensorboard logs
    if os.path.exists("tensorboard"):
        print(f"✓ Tensorboard logs found")
        log_files = []
        for root, dirs, files in os.walk("tensorboard"):
            log_files.extend([f for f in files if f.endswith('.tfevents')])
        print(f"    {len(log_files)} log files")
    else:
        print(f"❌ No tensorboard logs found")
    
    return True

def main():
    """Run full diagnosis."""
    print("🏥 WH40K AI DIAGNOSTIC TOOL")
    print("=" * 50)
    print("This tool will help identify issues with your AI training setup.")
    print()
    
    # Run diagnostics
    success = True
    
    print("1️⃣ Environment Test...")
    if not diagnose_environment():
        success = False
    
    print("\n2️⃣ Model Behavior Test...")
    if not diagnose_model_behavior():
        success = False
    
    print("\n3️⃣ Training Data Check...")
    if not diagnose_training_data():
        success = False
    
    # Recommendations
    print("\n💡 RECOMMENDATIONS")
    print("=" * 50)
    
    if not success:
        print("❌ Critical issues found. Fix these before continuing:")
        print("   • Check import paths and dependencies")
        print("   • Verify model file exists and is valid")
        print("   • Ensure environment setup is correct")
    else:
        print("🔍 Based on your 0% win rate and all-draw results:")
        print()
        print("🎯 Possible Issues:")
        print("   • Game may be ending due to turn limits, not victory conditions")
        print("   • AI may not have learned effective strategies")
        print("   • Reward function might not encourage winning")
        print("   • Environment might have bugs in win/loss detection")
        print()
        print("🔧 Suggested Fixes:")
        print("   1. Check game termination logic in gym40k.py")
        print("   2. Review reward values in config/rewards_config.json")
        print("   3. Train for more timesteps: python ai/train.py --append")
        print("   4. Try different training config: --training-config aggressive")
        print("   5. Check if units are actually fighting each other")
        print()
        print("🚀 Quick Actions:")
        print("   python ai/train.py --training-config aggressive --append")
        print("   python ai/evaluate.py --episodes 10  # Quick test")
    
    return success

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Diagnosis interrupted")
    except Exception as e:
        print(f"\n💥 Diagnosis failed: {e}")
        import traceback
        traceback.print_exc()