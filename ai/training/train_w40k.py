#!/usr/bin/env python3
"""
ai/training/train_w40k.py - W40K Model Training Script with Full Orchestration

ARCHITECTURE: AI_TURN.md compliant training system
COMPLIANCE: Sequential activation, built-in step counting, pure delegation
"""

import sys
import os
import argparse

# Fix import paths for your project structure
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

from ai.training.orchestrator import TrainingOrchestrator
from ai.training.evaluator import ModelEvaluator
from ai.training.gym_interface import W40KGymEnv
from main import load_config


def main():
    parser = argparse.ArgumentParser(description="AI_TURN.md Compliant W40K Training")
    parser.add_argument("--mode", choices=["single", "multi", "evaluate"], default="single",
                       help="Training mode")
    parser.add_argument("--agent", type=str, default="w40k_agent",
                       help="Agent name for single training")
    parser.add_argument("--training-config", type=str, default="default",
                       help="Training configuration from training_config.json")
    parser.add_argument("--rewards-config", type=str, default="default", 
                       help="Rewards configuration name")
    parser.add_argument("--timesteps", type=int, default=None,
                       help="Total timesteps for training (overrides config)")
    parser.add_argument("--episodes", type=int, default=1000,
                       help="Episodes per agent for multi-agent training")
    parser.add_argument("--model", type=str,
                       help="Model path for evaluation")
    parser.add_argument("--eval-episodes", type=int, default=100,
                       help="Episodes for evaluation")
    parser.add_argument("--new", action="store_true",
                       help="Create new model instead of loading existing")
    parser.add_argument("--append", action="store_true", 
                       help="Continue training existing model with updated config")
    
    args = parser.parse_args()
    
    print("🎮 W40K AI Training - AI_TURN.md Compliant")
    print("=" * 50)
    print(f"Mode: {args.mode}")
    
    try:
        orchestrator = TrainingOrchestrator()
        
        if args.mode == "single":
            print(f"Agent: {args.agent}")
            print(f"Timesteps: {args.timesteps:,}")
            
            model_path = orchestrator.train_single_agent(
                agent_name=args.agent,
                total_timesteps=args.timesteps
            )
            
            print(f"✅ Training completed: {model_path}")
            
            # Quick evaluation
            evaluator = ModelEvaluator()
            results = evaluator.evaluate_model(model_path, num_episodes=10)
            print(f"Quick test - Win Rate: {results['win_rate']:.1%}")
        
        elif args.mode == "multi":
            agents = ["space_marine", "ork", "tau", "necron"]  # Example agents
            print(f"Agents: {agents}")
            print(f"Episodes per agent: {args.episodes}")
            
            models = orchestrator.train_multi_agent_sequential(
                agents=agents,
                episodes_per_agent=args.episodes
            )
            
            print("✅ Multi-agent training completed:")
            for agent, model_path in models.items():
                print(f"  {agent}: {model_path}")
        
        elif args.mode == "evaluate":
            if not args.model:
                print("❌ --model required for evaluation mode")
                return 1
            
            evaluator = ModelEvaluator()
            results = evaluator.evaluate_model(
                model_path=args.model,
                num_episodes=args.eval_episodes
            )
            
            print("📊 EVALUATION RESULTS")
            print("=" * 30)
            print(f"Win Rate: {results['win_rate']:.1%}")
            print(f"Avg Reward: {results['avg_reward']:.2f}")
            print(f"Avg Steps: {results['avg_steps']:.1f}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)