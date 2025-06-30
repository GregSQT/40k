# ai/debug_gym40k.py
#!/usr/bin/env python3
"""
Debug script to find the exact cause of training hang in gym40k.py
Following AI_INSTRUCTIONS.md requirements exactly
"""

import os
import sys
import time
import traceback

# AI scripts run from project root directory per AI_INSTRUCTIONS.md
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

def debug_environment():
    """Debug environment step by step to find hang location"""
    print("🔧 DEBUGGING W40K ENVIRONMENT HANG")
    print("=" * 50)
    
    # Test 1: Basic import
    print("1. Testing imports...")
    try:
        from ai.gym40k import W40KEnv
        print("✅ gym40k imported successfully")
    except Exception as e:
        print(f"❌ Import failed: {e}")
        traceback.print_exc()
        return False
    
    # Test 2: Environment creation
    print("\n2. Testing environment creation...")
    try:
        env = W40KEnv(rewards_config="phase_based")
        print("✅ Environment created")
        print(f"   Action space: {env.action_space}")
        print(f"   Observation space: {env.observation_space}")
        print(f"   Board size: {env.board_size}")
        print(f"   Max units: {env.max_units}")
    except Exception as e:
        print(f"❌ Environment creation failed: {e}")
        traceback.print_exc()
        return False
    
    # Test 3: Environment reset
    print("\n3. Testing environment reset...")
    try:
        start_time = time.time()
        obs, info = env.reset()
        reset_time = time.time() - start_time
        print(f"✅ Reset completed in {reset_time:.3f}s")
        print(f"   Observation shape: {obs.shape}")
        print(f"   Observation sample: {obs[:5]}...")
        print(f"   Info: {info}")
        
        # Check units after reset
        print(f"   AI units: {len([u for u in env.ai_units if u['alive']])}")
        print(f"   Enemy units: {len([u for u in env.enemy_units if u['alive']])}")
        print(f"   Phase: {env.current_phase}")
        
    except Exception as e:
        print(f"❌ Reset failed: {e}")
        traceback.print_exc()
        return False
    
    # Test 4: Check eligible units
    print("\n4. Testing eligible units logic...")
    try:
        eligible = env._get_eligible_units()
        print(f"   Eligible units in {env.current_phase} phase: {len(eligible)}")
        for i, unit in enumerate(eligible):
            print(f"     Unit {i}: ID={unit['id']}, Type={unit['unit_type']}, Player={unit['player']}")
    except Exception as e:
        print(f"❌ Eligible units check failed: {e}")
        traceback.print_exc()
        return False
    
    # Test 5: Single step with timeout
    print("\n5. Testing single environment step...")
    try:
        action = 0  # Simple action
        print(f"   Executing action {action}...")
        
        start_time = time.time()
        obs, reward, done, truncated, info = env.step(action)
        step_time = time.time() - start_time
        
        print(f"✅ Step completed in {step_time:.3f}s")
        print(f"   Reward: {reward}")
        print(f"   Done: {done}")
        print(f"   Info: {info}")
        print(f"   New phase: {env.current_phase}")
        
        return True
        
    except Exception as e:
        print(f"❌ Step failed: {e}")
        traceback.print_exc()
        return False

def debug_phase_logic():
    """Debug phase advancement logic specifically"""
    print("\n🔧 DEBUGGING PHASE LOGIC")
    print("=" * 30)
    
    try:
        from ai.gym40k import W40KEnv
        env = W40KEnv(rewards_config="phase_based")
        obs, info = env.reset()
        
        print(f"Initial phase: {env.current_phase}")
        print(f"Initial eligible units: {len(env._get_eligible_units())}")
        
        # Test phase advancement when no eligible units
        for i in range(10):  # Test multiple phase advances
            eligible = env._get_eligible_units()
            print(f"\nStep {i}:")
            print(f"  Phase: {env.current_phase}")
            print(f"  Eligible units: {len(eligible)}")
            
            if not eligible:
                print("  No eligible units - calling _advance_phase()")
                old_phase = env.current_phase
                env._advance_phase()
                new_phase = env.current_phase
                print(f"  Phase changed: {old_phase} → {new_phase}")
                
                if old_phase == new_phase:
                    print("❌ INFINITE LOOP DETECTED: Phase not advancing!")
                    return False
            else:
                break
                
        return True
        
    except Exception as e:
        print(f"❌ Phase logic debug failed: {e}")
        traceback.print_exc()
        return False

def debug_training_simulation():
    """Simulate the exact training scenario that hangs"""
    print("\n🔧 SIMULATING TRAINING SCENARIO")
    print("=" * 35)
    
    try:
        from ai.gym40k import W40KEnv
        from stable_baselines3.common.monitor import Monitor
        
        # Create environment exactly like training does
        env = W40KEnv(rewards_config="phase_based")
        env = Monitor(env)
        
        print("✅ Training environment created")
        
        # Reset like training does
        obs, info = env.reset()
        print("✅ Training reset completed")
        
        # Test 10 steps with timeout
        print("Testing 10 training steps...")
        for step in range(10):
            action = env.action_space.sample()
            
            print(f"  Step {step}: Action {action}")
            start_time = time.time()
            
            obs, reward, done, truncated, info = env.step(action)
            
            step_time = time.time() - start_time
            print(f"    Completed in {step_time:.3f}s, reward={reward:.3f}")
            
            if done:
                print(f"    Game ended at step {step}")
                break
                
            if step_time > 5.0:  # If step takes more than 5 seconds
                print(f"❌ SLOW STEP DETECTED: {step_time:.3f}s")
                return False
        
        print("✅ Training simulation completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Training simulation failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = True
    
    success &= debug_environment()
    success &= debug_phase_logic()  
    success &= debug_training_simulation()
    
    if success:
        print("\n🎉 ALL TESTS PASSED - Environment should work")
    else:
        print("\n💥 TESTS FAILED - Found the hang issue")
    
    print("\nNext step: Run this script to identify the exact hang location")
    print("Command: python ai/debug_gym40k.py")