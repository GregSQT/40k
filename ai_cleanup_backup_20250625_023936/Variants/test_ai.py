#!/usr/bin/env python3
# test_ai.py - Fixed test script

import os
import sys
import numpy as np

# Add current directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from stable_baselines3 import DQN
from gym40k import W40KEnv

def test_model(episodes=3):
    """Test the trained model."""
    
    if not os.path.exists("ai/model.zip"):
        print("[ERROR] No trained model found. Run training first.")
        return False
    
    print("Testing trained model...")
    
    # Load environment and model
    env = W40KEnv()
    model = DQN.load("ai/model.zip")
    
    wins = 0
    total_rewards = []
    
    for episode in range(episodes):
        print(f"\nEpisode {episode + 1}/{episodes}")
        
        obs, info = env.reset()
        total_reward = 0
        step_count = 0
        done = False
        
        while not done:
            # Predict action
            action, _states = model.predict(obs, deterministic=True)
            
            # Ensure action is an integer
            if isinstance(action, np.ndarray):
                action = int(action.item())
            else:
                action = int(action)
            
            # Execute action
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            step_count += 1
            done = terminated or truncated
            
            if step_count % 10 == 0:
                print(f"  Step {step_count}: Action={action}, Reward={reward:.3f}")
            
            if step_count > 100:
                print("  Episode truncated (too long)")
                break
        
        winner = info.get("winner", "None")
        if winner == 1:
            wins += 1
            result = "AI WIN"
        elif winner == 0:
            result = "AI LOSE"
        else:
            result = "DRAW"
        
        total_rewards.append(total_reward)
        print(f"  {result} - Steps: {step_count}, Total Reward: {total_reward:.3f}")
    
    print("\nTest Results:")
    print(f"  Episodes: {episodes}")
    print(f"  AI Wins: {wins}/{episodes} ({100*wins/episodes:.1f}%)")
    if total_rewards:
        print(f"  Average Reward: {sum(total_rewards)/len(total_rewards):.3f}")
        print(f"  Best Reward: {max(total_rewards):.3f}")
        print(f"  Worst Reward: {min(total_rewards):.3f}")
    
    env.close()
    return True

if __name__ == "__main__":
    test_model()
