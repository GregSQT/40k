# ai/diagnose_timeout.py
"""Diagnose timeout issue - confirm wait penalty calculation"""

import sys
from pathlib import Path
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from gym40k import W40KEnv, register_environment
from stable_baselines3 import DQN

def diagnose_timeout_issue():
    print("🔍 DIAGNOSING -27.90 REWARD ISSUE")
    print("=" * 50)
    
    register_environment()
    env = W40KEnv(rewards_config="default", training_config_name="default")
    model = DQN.load("ai/models/current/model.zip", env=env)
    
    obs, info = env.reset()
    total_reward = 0.0
    step_count = 0
    
    print("🎮 Running single diagnostic episode...")
    
    while step_count < 350:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        
        total_reward += reward
        step_count += 1
        
        if step_count % 100 == 0:
            print(f"Step {step_count}: Total reward {total_reward:.2f}")
        
        if terminated or truncated:
            break
    
    print(f"\n📊 RESULTS:")
    print(f"Total steps: {step_count}")
    print(f"Final reward: {total_reward:.2f}")
    print(f"Expected wait penalty (300 × -0.1): {300 * -0.1:.2f}")
    print(f"Difference: {total_reward - (300 * -0.1):.2f}")
    
    if abs(total_reward + 27.9) < 1.0:
        print("✅ CONFIRMED: Issue is wait penalty accumulation")
        print("💡 SOLUTION: Increase wait penalty to -0.5 or higher")
    
    env.close()

if __name__ == "__main__":
    diagnose_timeout_issue()