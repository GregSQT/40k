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

# Import standard DQN - action masking implemented manually in gym environment
from stable_baselines3 import DQN
MASKABLE_DQN_AVAILABLE = False

from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor
# Multi-agent orchestration imports
from ai.scenario_manager import ScenarioManager
from ai.multi_agent_trainer import MultiAgentTrainer
from config_loader import get_config_loader
from ai.game_replay_logger import GameReplayIntegration
import torch

class SelectiveEvalCallback(EvalCallback):
    """Custom evaluation callback that saves best/worst/shortest episode replays."""
    
    def __init__(self, *args, output_dir="ai/event_log", **kwargs):
        super().__init__(*args, **kwargs)
        self.output_dir = output_dir
        self.episodes_data = []
        os.makedirs(output_dir, exist_ok=True)
    
    def _on_step(self) -> bool:
        """Override to capture episode data during evaluation."""
        continue_training = super()._on_step()
        
        # Only save replays after all evaluation episodes are complete
        if self.n_calls % self.eval_freq == 0 and hasattr(self.eval_env, 'replay_logger'):
            self._save_selective_replays()
        
        return continue_training
    
    def _save_selective_replays(self):
        """Save best/worst/shortest replays from evaluation episodes per specification."""
        # Access SelectiveEpisodeTracker for proper best/worst/shortest selection
        if not hasattr(self.eval_env, 'episode_tracker'):
            raise RuntimeError("Environment missing required episode_tracker for replay selection")
        if not self.eval_env.episode_tracker:
            raise RuntimeError("Environment episode_tracker is None")
        
        self.eval_env.episode_tracker.save_selective_replays(self.output_dir)

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
        raise ImportError(f"AI_INSTRUCTIONS.md: gym40k.py import failed: {e}")

def create_model(config, training_config_name="default", rewards_config_name="default", new_model=False, append_training=False):
    """Create or load DQN model with configuration following AI_INSTRUCTIONS.md."""
    
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
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    # Load unit registry for environment creation
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    base_env = W40KEnv(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=None,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=False
    )
    
    # DISABLED: No logging during training for speed
    # Enhanced logging only during evaluation
    env = Monitor(base_env)
    
    model_path = config.get_model_path()
    
    # Set device for model creation
    device = "cuda" if gpu_available else "cpu"
    model_params["device"] = device
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model on {device.upper()}...")
        print("✅ Using DQN with manual action masking in gym environment")
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
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    if not os.path.isfile(scenario_file):
        raise FileNotFoundError(f"Missing scenario.json in config/: {scenario_file}")
    # Load unit registry for multi-agent environment
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    base_env = W40KEnv(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=False
    )
    
    # DISABLED: No logging during training for speed
    # Enhanced logging only during evaluation
    env = Monitor(base_env)
    
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
    
    # Evaluation callback - test model periodically with logging enabled
    # Load scenario and unit registry for evaluation callback
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    unit_registry = UnitRegistry()
    
    base_eval_env = W40KEnv(
        rewards_config="default",
        training_config_name=training_config_name,
        controlled_agent=None,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True
    )
    
    # Enable logging ONLY for evaluation
    enhanced_eval_env = GameReplayIntegration.enhance_training_env(base_eval_env)
    eval_env = Monitor(enhanced_eval_env)
    eval_env.replay_logger = enhanced_eval_env.replay_logger
    # Handle different config formats - calculate missing fields from available data
    if 'eval_freq' in training_config:
        eval_freq = training_config['eval_freq']
    else:
        # Debug config uses total_episodes - calculate eval_freq
        total_episodes = training_config['total_episodes']
        max_steps = training_config['max_steps_per_episode']
        eval_freq = total_episodes * max_steps // 2  # Evaluate halfway through
    
    if 'total_timesteps' in training_config:
        total_timesteps = training_config['total_timesteps']
    else:
        # Debug config uses total_episodes and max_steps_per_episode
        total_episodes = training_config['total_episodes']
        max_steps = training_config['max_steps_per_episode']
        total_timesteps = total_episodes * max_steps
    
    # VALIDATION: Prevent deadlock when eval_freq >= total_timesteps
    if eval_freq >= total_timesteps:
        raise ValueError(f"eval_freq ({eval_freq}) must be less than total_timesteps ({total_timesteps}). "
                        f"This prevents evaluation callback deadlock. "
                        f"Either increase total_timesteps or decrease eval_freq to {total_timesteps // 2}.")
    
    # Get callback parameters from config with defaults
    callback_params = training_config.get("callback_params", {})
    
    # Skip evaluation callback for debug config to prevent hanging
    if training_config_name != "debug":
        eval_callback = SelectiveEvalCallback(
            eval_env,
            best_model_save_path=os.path.dirname(model_path),
            log_path=os.path.dirname(model_path),
            eval_freq=eval_freq,
            deterministic=callback_params.get("eval_deterministic", True),
            render=callback_params.get("eval_render", False),
            n_eval_episodes=callback_params.get("n_eval_episodes", 5),
            output_dir="ai/event_log"
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
    
    try:
        # Start training
        # Calculate total_timesteps if missing (same logic as setup_callbacks)
        if 'total_timesteps' in training_config:
            total_timesteps = training_config['total_timesteps']
        else:
            total_episodes = training_config['total_episodes']
            max_steps = training_config['max_steps_per_episode']
            total_timesteps = total_episodes * max_steps
        
        model.learn(
            total_timesteps=total_timesteps,
            callback=callbacks,
            log_interval=100,
            progress_bar=True
        )
        
        # Save final model
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        model.save(model_path)
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
    
    W40KEnv, _ = setup_imports()
    # Load scenario and unit registry for testing
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    unit_registry = UnitRegistry()
    
    env = W40KEnv(
        rewards_config="default",
        training_config_name="default",
        controlled_agent=None,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True
    )
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
    
    if num_episodes == 0:
        print("\n📊 Test Results: No test episodes specified (--test-episodes 0)")
        return 0.0, 0.0
    
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
        
        # Test unit registry integration
        unit_registry = UnitRegistry()
        
        # Test scenario manager
        scenario_manager = ScenarioManager(config, unit_registry)
        print(f"✅ ScenarioManager initialized with {len(scenario_manager.get_available_templates())} templates")
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
    scenario_path = os.path.join(project_root, "config", "scenario.json")
    if not os.path.exists(scenario_path):
        raise FileNotFoundError(f"Missing required scenario.json file: {scenario_path}. AI_INSTRUCTIONS.md: No fallbacks allowed - scenario file must exist.")

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
    parser.add_argument("--test-episodes", type=int, default=0, 
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
        try:
            subprocess.run(['node', 'scripts/copy-configs.js'], 
                         cwd=project_root, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            pass  # Continue with training if sync fails
        
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

        # Single agent training mode
        elif args.agent:
            model, env, training_config, model_path = create_multi_agent_model(
                config,
                args.training_config,
                args.rewards_config,
                agent_key=args.agent,
                new_model=args.new,
                append_training=args.append
            )
            
            # Setup callbacks with agent-specific model path
            callbacks = setup_callbacks(config, model_path, training_config, args.training_config)
            
            # Train model
            success = train_model(model, training_config, callbacks, model_path)
            
            if success:
                test_trained_model(model, args.test_episodes)
                return 0
            else:
                return 1

        elif args.test_only:
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
            # Load scenario and unit registry for testing
            from ai.unit_registry import UnitRegistry
            cfg = get_config_loader()
            scenario_file = os.path.join(cfg.config_dir, "scenario.json")
            unit_registry = UnitRegistry()
            
            env = W40KEnv(
                rewards_config=args.rewards_config,
                training_config_name="default",
                controlled_agent=None,
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=True
            )
            model = DQN.load(model_path, env=env)
            test_trained_model(model, args.test_episodes)
            return 0
        
        else:
            # Generic training mode
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
            test_trained_model(model, args.test_episodes)
            
            # Save training replay with our unified system
            if hasattr(env, 'replay_logger'):
                from ai.game_replay_logger import GameReplayIntegration
                final_reward = 0.0  # Average reward from testing
                replay_file = GameReplayIntegration.save_episode_replay(
                    env, 
                    episode_reward=final_reward, 
                    output_dir="ai/event_log", 
                    is_best=False
                )
            
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