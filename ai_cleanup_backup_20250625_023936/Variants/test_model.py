#!/usr/bin/env python3
# ai/test_model.py - Test the trained model with fixed imports

import os
import sys

# Add the parent directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from stable_baselines3 import DQN

# Import gym environment with fallback
try:
    from ai.gym40k import W40KEnv
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from gym40k import W40KEnv

def test_model(episodes=5):
    """Test the trained model for several episodes."""
    
    model_path = os.path.join("ai", "model.zip")
    if not os.path.exists(model_path):
        print("[ERROR] No trained model found. Run training first.")
        return False
    
    print("Testing trained model...")
    
    # Load environment and model
    env = W40KEnv()
    model = DQN.load(model_path)
    
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
            
            # Execute action
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            step_count += 1
            done = terminated or truncated
            
            # Show progress every 10 steps
            if step_count % 10 == 0:
                print(f"  Step {step_count}: Action={action}, Reward={reward:.3f}")
            
            if step_count > 100:  # Prevent infinite loops
                print("  Episode truncated (too long)")
                break
        
        # Episode summary
        winner = info.get("winner", "None")
        if winner == 1:  # AI wins
            wins += 1
            result = "AI WIN"
        elif winner == 0:
            result = "AI LOSE"
        else:
            result = "DRAW"
        
        total_rewards.append(total_reward)
        print(f"  {result} - Steps: {step_count}, Total Reward: {total_reward:.3f}")
    
    # Final statistics
    print("\nTest Results:")
    print(f"  Episodes: {episodes}")
    print(f"  AI Wins: {wins}/{episodes} ({100*wins/episodes:.1f}%)")
    print(f"  Average Reward: {sum(total_rewards)/len(total_rewards):.3f}")
    print(f"  Best Reward: {max(total_rewards):.3f}")
    print(f"  Worst Reward: {min(total_rewards):.3f}")
    
    env.close()
    return True

if __name__ == "__main__":
    import sys
    episodes = 5
    
    if "--episodes" in sys.argv:
        idx = sys.argv.index("--episodes")
        if idx + 1 < len(sys.argv):
            episodes = int(sys.argv[idx + 1])
    
    test_model(episodes)
