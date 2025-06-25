#!/usr/bin/env python3
"""
ai/test.py - Test trained model
"""

import os
import sys

def setup_imports():
    """Set up import paths and return required modules."""
    # Add paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)

    from stable_baselines3 import DQN
    from gym40k import W40KEnv
    
    return DQN, W40KEnv

def test_model(episodes=5):
    """Test the trained model."""
    if not os.path.exists("model.zip"):
        print("No model found. Train first: python train.py")
        return False
    
    print(f"Testing model for {episodes} episodes...")
    
    # Set up imports
    try:
        DQN, W40KEnv = setup_imports()
    except ImportError as e:
        print(f"Import error: {e}")
        return False
    
    env = W40KEnv()
    model = DQN.load("model.zip")
    
    wins = 0
    rewards = []
    
    for ep in range(episodes):
        obs, _ = env.reset()
        total_reward = 0
        done = False
        steps = 0
        
        while not done and steps < 100:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            steps += 1
            done = terminated or truncated
        
        winner = info.get("winner", "None")
        if winner == 1:
            wins += 1
            result = "AI WIN"
        else:
            result = "HUMAN WIN"
        
        rewards.append(total_reward)
        print(f"Episode {ep+1}: {result} - {steps} steps - Reward: {total_reward:.2f}")
    
    print(f"Results: {wins}/{episodes} wins ({100*wins/episodes:.1f}%)")
    print(f"Average reward: {sum(rewards)/len(rewards):.2f}")
    
    env.close()
    return True

if __name__ == "__main__":
    episodes = 5
    if "--episodes" in sys.argv:
        idx = sys.argv.index("--episodes")
        if idx + 1 < len(sys.argv):
            episodes = int(sys.argv[idx + 1])
    test_model(episodes)
