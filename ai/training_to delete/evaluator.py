#!/usr/bin/env python3
"""
ai/training/evaluator.py - AI_TURN.md Compliant Model Evaluation

ARCHITECTURE: Pure delegation, no wrapper patterns
COMPLIANCE: Sequential activation testing, built-in metrics
"""

import os
import sys
import numpy as np
from typing import Dict, List, Tuple
from stable_baselines3 import DQN

# Fix import paths for your project structure  
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

from ai.training.gym_interface import W40KGymEnv
from main import load_config

class ModelEvaluator:
    """AI_TURN.md compliant model evaluation - pure delegation only."""
    
    def __init__(self, config_path: str = None):
        self.config = load_config(config_path)
    
    def evaluate_model(self, 
                      model_path: str, 
                      num_episodes: int = 100,
                      scenario_config: Dict = None) -> Dict:
        """Evaluate trained model with AI_TURN.md compliance."""
        
        print(f"Evaluating model: {model_path}")
        print(f"Episodes: {num_episodes}")
        
        # Create compliant environment
        env_config = self.config.copy()
        if scenario_config:
            env_config.update(scenario_config)
        
        env = W40KGymEnv(env_config)
        
        # Load model
        model = DQN.load(model_path, env=env)
        
        # Run evaluation episodes
        wins = 0
        total_rewards = []
        total_steps = []
        
        for episode in range(num_episodes):
            obs, info = env.reset()
            episode_reward = 0
            episode_steps = 0
            terminated = False
            truncated = False
            
            while not (terminated or truncated):
                # Sequential activation - one action per step
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                
                episode_reward += reward
                episode_steps += 1
                
                # Safety limit
                if episode_steps > 1000:
                    break
            
            total_rewards.append(episode_reward)
            total_steps.append(episode_steps)
            
            # Check win condition
            if info.get('winner') == 1:  # AI wins
                wins += 1
        
        env.close()
        
        # Calculate metrics
        win_rate = wins / num_episodes
        avg_reward = np.mean(total_rewards)
        avg_steps = np.mean(total_steps)
        
        results = {
            'model_path': model_path,
            'episodes': num_episodes,
            'win_rate': win_rate,
            'avg_reward': avg_reward,
            'avg_steps': avg_steps,
            'reward_std': np.std(total_rewards),
            'steps_std': np.std(total_steps)
        }
        
        print(f"Win Rate: {win_rate:.1%}")
        print(f"Avg Reward: {avg_reward:.2f}")
        print(f"Avg Steps: {avg_steps:.1f}")
        
        return results
    
    def compare_models(self, model_paths: List[str], num_episodes: int = 50) -> Dict:
        """Compare multiple models with identical scenarios."""
        
        print(f"Comparing {len(model_paths)} models")
        
        results = {}
        for model_path in model_paths:
            model_name = os.path.basename(model_path).replace('.zip', '')
            results[model_name] = self.evaluate_model(model_path, num_episodes)
        
        # Print comparison
        print("\n📊 MODEL COMPARISON")
        print("=" * 50)
        for name, result in results.items():
            print(f"{name:20} | Win: {result['win_rate']:.1%} | Reward: {result['avg_reward']:6.2f}")
        
        return results