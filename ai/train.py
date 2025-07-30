# ai/train.py
#!/usr/bin/env python3
"""
ai/train.py - Main training script following AI_INSTRUCTIONS.md exactly
"""

import os
import sys
import argparse
import subprocess
import json
import glob
import shutil
from pathlib import Path

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)
from ai.unit_registry import UnitRegistry
sys.path.insert(0, project_root)

from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor
# Multi-agent orchestration imports
from ai.scenario_manager import ScenarioManager
from ai.multi_agent_trainer import MultiAgentTrainer
from config_loader import get_config_loader
from ai.game_replay_logger import GameReplayIntegration
import torch

def check_gpu_availability():
    """Check and display GPU availability for training."""
    print("\n🔍 GPU AVAILABILITY CHECK")
    print("=" * 30)
    
    if torch.cuda.is_available():
        device_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        device_name = torch.cuda.get_device_name(current_device)
        memory_gb = torch.cuda.get_device_properties(current_device).total_memory / 1024**3
        
        print(f"✅ CUDA Available: YES")
        print(f"📊 GPU Devices: {device_count}")
        print(f"🎯 Current Device: {current_device} ({device_name})")
        print(f"💾 GPU Memory: {memory_gb:.1f} GB")
        print(f"🚀 PyTorch CUDA Version: {torch.version.cuda}")
        
        # Force PyTorch to use GPU for Stable-Baselines3
        torch.cuda.set_device(current_device)
        
        return True
    else:
        print(f"❌ CUDA Available: NO")
        print(f"⚠️  Training will use CPU (much slower)")
        print(f"💡 Install CUDA-enabled PyTorch: pip install torch --index-url https://download.pytorch.org/whl/cu118")
        
        return False

def setup_imports():
    """Set up import paths and return required modules."""
    try:
        # AI_INSTRUCTIONS.md: Import from gym40k.py in ai/ subdirectory
        from gym40k import W40KEnv, register_environment
        return W40KEnv, register_environment
    except ImportError as e:
        print(f"Import error: {e}")
        print("AI_INSTRUCTIONS.md: Please ensure gym40k.py exists in ai/ directory and is properly configured")
        sys.exit(1)

def create_model(config, training_config_name="default", rewards_config_name="default", new_model=False, append_training=False):
    """Create or load DQN model with configuration following AI_INSTRUCTIONS.md."""
    print(f"🤖 Creating/loading model with training config: {training_config_name}, rewards config: {rewards_config_name}")
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration from config files (not script parameters)
    training_config = config.load_training_config(training_config_name)
    model_params = training_config["model_params"]
    
    # Import environment
    W40KEnv, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create environment with specified rewards config
    # ensure scenario.json exists in config/
    from config_loader import get_config_loader
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    base_env = W40KEnv(rewards_config=rewards_config_name, training_config_name=training_config_name)
    
    # Enhance environment with our advanced replay logger BEFORE Monitor wrapping
    enhanced_env = GameReplayIntegration.enhance_training_env(base_env)
    env = Monitor(enhanced_env)
    
    # Store reference to replay logger for access
    env.replay_logger = enhanced_env.replay_logger
    
    model_path = config.get_model_path()
    
    # Set device for model creation
    device = "cuda" if gpu_available else "cpu"
    model_params["device"] = device
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model on {device.upper()}...")
        model = DQN(env=env, **model_params)
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = DQN.load(model_path, env=env, device=device)
            # Update any model parameters that might have changed
            model.tensorboard_log = model_params["tensorboard_log"]
            model.verbose = model_params["verbose"]
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = DQN(env=env, **model_params)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = DQN.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = DQN(env=env, **model_params)
    
    return model, env, training_config

def create_multi_agent_model(config, training_config_name="default", rewards_config_name="default", 
                            agent_key=None, new_model=False, append_training=False):
    """Create or load DQN model for specific agent with configuration following AI_INSTRUCTIONS.md."""
    print(f"🤖 Creating/loading model for agent: {agent_key}")
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration from config files (not script parameters)
    training_config = config.load_training_config(training_config_name)
    model_params = training_config["model_params"]
    
    # Import environment
    W40KEnv, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create agent-specific environment
    from config_loader import get_config_loader
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    base_env = W40KEnv(rewards_config=rewards_config_name, 
                      training_config_name=training_config_name,
                      controlled_agent=agent_key)
    
    # Enhance environment with our advanced replay logger BEFORE Monitor wrapping
    enhanced_env = GameReplayIntegration.enhance_training_env(base_env)
    env = Monitor(enhanced_env)
    
    # Store reference to replay logger for access
    env.replay_logger = enhanced_env.replay_logger
    
    # Agent-specific model path
    model_path = config.get_model_path().replace('.zip', f'_{agent_key}.zip')
    
    # Set device for model creation
    device = "cuda" if gpu_available else "cpu"
    model_params["device"] = device
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model for {agent_key} on {device.upper()}...")
        model = DQN(env=env, **model_params)
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = DQN.load(model_path, env=env, device=device)
            model.tensorboard_log = model_params.get("tensorboard_log", "./tensorboard/")
            model.verbose = model_params["verbose"]
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = DQN(env=env, **model_params)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = DQN.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model = DQN(env=env, **model_params)
    
    return model, env, training_config, model_path

def setup_callbacks(config, model_path, training_config, training_config_name="default"):
    W40KEnv, _ = setup_imports()
    callbacks = []
    
    # Evaluation callback - test model periodically (use default scenario for consistency)
    base_eval_env = W40KEnv(training_config_name=training_config_name, scenario_file=None)
    
    # Enhance evaluation environment with our advanced replay logger
    enhanced_eval_env = GameReplayIntegration.enhance_training_env(base_eval_env)
    eval_env = Monitor(enhanced_eval_env)
    eval_env.replay_logger = enhanced_eval_env.replay_logger
    eval_freq=training_config['eval_freq']
    total_timesteps = training_config['total_timesteps']
    
    # VALIDATION: Prevent deadlock when eval_freq >= total_timesteps
    if eval_freq >= total_timesteps:
        raise ValueError(f"eval_freq ({eval_freq}) must be less than total_timesteps ({total_timesteps}). "
                        f"This prevents evaluation callback deadlock. "
                        f"Either increase total_timesteps or decrease eval_freq to {total_timesteps // 2}.")
    
    # Get callback parameters from config with defaults
    callback_params = training_config.get("callback_params", {})
    
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=os.path.dirname(model_path),
        log_path=os.path.dirname(model_path),
        eval_freq=eval_freq,  # Use config value
        deterministic=callback_params.get("eval_deterministic", True),
        render=callback_params.get("eval_render", False),
        n_eval_episodes=callback_params.get("n_eval_episodes", 5)
    )
    callbacks.append(eval_callback)
    
    # Checkpoint callback - save model periodically
    # Use reasonable checkpoint frequency based on total timesteps and config
    checkpoint_freq = callback_params.get("checkpoint_save_freq", min(total_timesteps // 4, 50000))
    checkpoint_callback = CheckpointCallback(
        save_freq=checkpoint_freq,
        save_path=os.path.dirname(model_path),
        name_prefix=callback_params.get("checkpoint_name_prefix", "default_model_checkpoint")
    )
    callbacks.append(checkpoint_callback)
    
    return callbacks

def train_model(model, training_config, callbacks, model_path):
    """Execute the training process."""
    print("🚀 Starting default training following AI_GAME_OVERVIEW.md...")
    print(f"   Total timesteps: {training_config['total_timesteps']:,}")
    print(f"   Model will be saved to: {model_path}")
    
    try:
        # Start training
        model.learn(
            total_timesteps=training_config['total_timesteps'],
            callback=callbacks,
            log_interval=100,
            progress_bar=True
        )
        
        # Save final model
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        model.save(model_path)
        print(f"✅ Training completed! Model saved to: {model_path}")
        
        return True
        
    except KeyboardInterrupt:
        print("\n⏹️ Training interrupted by user")
        # Save current progress
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        model.save(interrupted_path)
        print(f"💾 Progress saved to: {interrupted_path}")
        return False
        
    except Exception as e:
        print(f"❌ Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_trained_model(model, num_episodes=5):
    """Test the trained model."""
    print(f"🧪 Testing trained model for {num_episodes} episodes...")
    
    W40KEnv, _ = setup_imports()
    env = W40KEnv(scenario_file=None)  # Explicit use of default scenario
    wins = 0
    total_rewards = []
    
    for episode in range(num_episodes):
        obs, info = env.reset()
        episode_reward = 0
        done = False
        step_count = 0
        
        while not done and step_count < 1000:  # Prevent infinite loops
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            done = terminated or truncated
            step_count += 1
        
        total_rewards.append(episode_reward)
        
        if info['winner'] == 1:  # AI won
            wins += 1
            result = "WIN"
        elif info['winner'] == 0:  # AI lost
            result = "LOSS"
        else:
            result = "DRAW"
        
        print(f"   Episode {episode + 1}: {result} - Reward: {episode_reward:.2f}, Steps: {step_count}")
    
    win_rate = wins / num_episodes
    avg_reward = sum(total_rewards) / len(total_rewards)
    
    print(f"\n📊 Test Results:")
    print(f"   Win Rate: {win_rate:.1%} ({wins}/{num_episodes})")
    print(f"   Average Reward: {avg_reward:.2f}")
    print(f"   Reward Range: {min(total_rewards):.2f} to {max(total_rewards):.2f}")
    
    env.close()
    return win_rate, avg_reward

def test_scenario_manager_integration():
    """Test scenario manager integration."""
    print("🧪 Testing Scenario Manager Integration")
    print("=" * 50)
    
    try:
        config = get_config_loader()
        
        # Test scenario manager
        scenario_manager = ScenarioManager(config)
        print(f"✅ ScenarioManager initialized with {len(scenario_manager.get_available_templates())} templates")
        
        # Test unit registry integration
        unit_registry = UnitRegistry()
        agents = unit_registry.get_required_models()
        print(f"✅ UnitRegistry found {len(agents)} agents: {agents}")
        
        # Test scenario generation
        if len(agents) >= 2:
            template_name = scenario_manager.get_available_templates()[0]
            scenario = scenario_manager.generate_training_scenario(
                template_name, agents[0], agents[1]
            )
            print(f"✅ Generated scenario with {len(scenario['units'])} units")
        
        # Test training rotation
        rotation = scenario_manager.get_balanced_training_rotation(100)
        print(f"✅ Generated training rotation with {len(rotation)} matchups")
        
        print("🎉 Scenario manager integration tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def start_multi_agent_orchestration(config, total_episodes: int, training_config_name: str = "default",
                                   rewards_config_name: str = "default", max_concurrent: int = None,
                                   training_phase: str = None):
    """Start multi-agent orchestration training with optional phase specification."""
    print("🎮 Starting Multi-Agent Orchestration Training")
    
    try:
        trainer = MultiAgentTrainer(config, max_concurrent_sessions=max_concurrent)
        results = trainer.start_balanced_training(
            total_episodes=total_episodes,
            training_config_name=training_config_name,
            rewards_config_name=rewards_config_name,
            training_phase=training_phase
        )
        
        print(f"✅ Orchestration completed: {results['total_matchups']} matchups")
        return results
        
    except Exception as e:
        print(f"❌ Orchestration failed: {e}")
        return None

def ensure_scenario():
    """Ensure scenario.json exists."""
    # write into <project_root>/config/scenario.json
    scenario_path = os.path.join(project_root, "config", "scenario.json")
    if not os.path.exists(scenario_path):
        print("⚠️ scenario.json not found - creating default from AI_GAME_OVERVIEW.md specs...")
        # Create scenario following the frontend structure
        default_scenario = [
            {
                "id": 1, "unit_type": "Intercessor", "player": 0,
                "col": 23, "row": 12
            },
            {
                "id": 2, "unit_type": "AssaultIntercessor", "player": 0,
                "col": 1, "row": 12
            },
            {
                "id": 3, "unit_type": "Intercessor", "player": 1,
                "col": 0, "row": 5
            },
            {
                "id": 4, "unit_type": "AssaultIntercessor", "player": 1,
                "col": 22, "row": 3
            }
        ]
        with open(scenario_path, "w") as f:
            json.dump(default_scenario, f, indent=2)
        print("✅ Created default scenario.json")

def main():
    """Main training function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Train W40K AI following AI_GAME_OVERVIEW.md specifications")
    parser.add_argument("--training-config", default="default", 
                       help="Training configuration to use from config/training_config.json")
    parser.add_argument("--rewards-config", default="default", 
                       help="Rewards configuration to use from config/rewards_config.json")
    parser.add_argument("--new", action="store_true", 
                       help="Force creation of new model")
    parser.add_argument("--append", action="store_true", 
                       help="Continue training existing model")
    parser.add_argument("--test-only", action="store_true", 
                       help="Only test existing model, don't train")
    parser.add_argument("--test-episodes", type=int, default=10, 
                       help="Number of episodes for testing")
    parser.add_argument("--multi-agent", action="store_true",
                       help="Use multi-agent training system")
    parser.add_argument("--agent", type=str, default=None,
                       help="Train specific agent (e.g., 'SpaceMarine_Ranged')")
    parser.add_argument("--orchestrate", action="store_true",
                       help="Start balanced multi-agent orchestration training")
    parser.add_argument("--total-episodes", type=int, default=1000,
                       help="Total episodes for multi-agent orchestration")
    parser.add_argument("--max-concurrent", type=int, default=None,
                       help="Maximum concurrent training sessions")
    parser.add_argument("--training-phase", type=str, choices=["solo", "cross_faction", "full_composition"],
                       help="Specific training phase for 3-phase training plan")
    parser.add_argument("--test-integration", action="store_true",
                       help="Test scenario manager integration")
    
    args = parser.parse_args()
    
    print("🎮 W40K AI Training - Following AI_GAME_OVERVIEW.md specifications")
    print("=" * 70)
    print(f"Training config: {args.training_config}")
    print(f"Rewards config: {args.rewards_config}")
    print(f"New model: {args.new}")
    print(f"Append training: {args.append}")
    print(f"Test only: {args.test_only}")
    print(f"Multi-agent: {args.multi_agent}")
    print(f"Orchestrate: {args.orchestrate}")
    print()
    
    try:
        # Sync configs to frontend automatically
        print("🔧 Syncing configs to frontend...")
        try:
            subprocess.run(['node', 'scripts/copy-configs.js'], 
                         cwd=project_root, check=True, capture_output=True, text=True)
            print("✅ Configs synced to frontend")
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Config sync failed: {e.stderr}")
            print("   Continuing with training...")
        
        # Setup environment and configuration
        config = get_config_loader()
        
        # Ensure scenario exists
        ensure_scenario()
        
        # Test integration if requested
        if args.test_integration:
            success = test_scenario_manager_integration()
            return 0 if success else 1
        
        # Multi-agent orchestration mode
        if args.orchestrate:
            results = start_multi_agent_orchestration(
                config=config,
                total_episodes=args.total_episodes,
                training_config_name=args.training_config,
                rewards_config_name=args.rewards_config,
                max_concurrent=args.max_concurrent,
                training_phase=args.training_phase
            )
            return 0 if results else 1

        if args.test_only:
            # Load existing model for testing only
            model_path = config.get_model_path()
            # Ensure model directory exists
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            print(f"📁 Model path: {model_path}")
            
            # Determine whether to create new model or load existing
            if not os.path.exists(model_path):
                print(f"❌ Model not found: {model_path}")
                return 1
            
            W40KEnv, _ = setup_imports()
            env = W40KEnv(rewards_config=args.rewards_config, scenario_file=None)  # Explicit use of default scenario
            model = DQN.load(model_path, env=env)
            test_trained_model(model, args.test_episodes)
            return 0
        
        # Create/load model
        model, env, training_config = create_model(
            config, 
            args.training_config,
            args.rewards_config, 
            args.new, 
            args.append
        )

        # Get model path for callbacks and training
        model_path = config.get_model_path()
        
        # Setup callbacks
        callbacks = setup_callbacks(config, model_path, training_config, args.training_config)
        
        # Train model
        success = train_model(model, training_config, callbacks, model_path)
        
        if success:
            # Test the trained model
            print("\n" + "=" * 70)
            test_trained_model(model, args.test_episodes)
            
            print("\n🎯 Training Complete!")
            print(f"Model saved to: {model_path}")
            print(f"Monitor tensorboard: tensorboard --logdir ./tensorboard/")
            print(f"Test model: python ai/train.py --test-only")
            
            return 0
        else:
            return 1
            
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)