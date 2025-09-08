#!/usr/bin/env python3
"""
ai/train_w40k.py - W40K Model Training Script

Uses W40KEngine via minimal gym interface
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from gym_interface import W40KGymEnv
from main import load_config


def main():
    print("Loading W40K configuration...")
    config = load_config()
    
    print("Creating training environment...")
    env = W40KGymEnv(config)
    
    print("Validating gym interface...")
    check_env(env)
    
    print("Starting training...")
    model = DQN(
        "MlpPolicy", 
        env, 
        verbose=1,
        learning_rate=0.001,
        buffer_size=10000,
        learning_starts=1000,
        target_update_interval=500,
        train_freq=4,
        gradient_steps=1,
        exploration_fraction=0.1,
        exploration_initial_eps=1.0,
        exploration_final_eps=0.05
    )
    
    model.learn(total_timesteps=50000)
    
    print("Saving trained model...")
    os.makedirs("models", exist_ok=True)
    model.save("models/w40k_dqn_model")
    
    print("Training completed successfully!")
    print("Model saved to: models/w40k_dqn_model.zip")
    
    # Test the trained model
    print("\nTesting trained model...")
    obs, info = env.reset()
    for i in range(5):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        print(f"Step {i+1}: Action={action}, Reward={reward:.3f}, Phase={info.get('phase')}")
        
        if terminated or truncated:
            break
    
    env.close()


if __name__ == "__main__":
    main()