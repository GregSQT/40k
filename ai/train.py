# ai/train.py
#!/usr/bin/env python3
"""
ai/train.py - Main training script following AI_INSTRUCTIONS.md exactly
"""

import os
import sys
import io
import argparse

# Fix Windows encoding for emoji/Unicode output with line buffering
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# Suppress NumPy MINGW-W64 warnings on Windows (MUST be before numpy import)
import warnings
warnings.filterwarnings('ignore')  # Suppress all warnings
import os
os.environ['PYTHONWARNINGS'] = 'ignore'

import subprocess
import json
import numpy as np
import glob
import shutil
import random
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)
from ai.unit_registry import UnitRegistry
sys.path.insert(0, project_root)

# Import evaluation bots for testing
try:
    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
    EVALUATION_BOTS_AVAILABLE = True
except ImportError:
    EVALUATION_BOTS_AVAILABLE = False

# Import MaskablePPO - enforces action masking during training
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3 import PPO
MASKABLE_PPO_AVAILABLE = True

from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, BaseCallback, CallbackList
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv  # ✓ CHANGE 1: Add vectorization support
from stable_baselines3.common.utils import get_schedule_fn  # Convert float hyperparameters to callable schedules
# Multi-agent orchestration imports
from ai.scenario_manager import ScenarioManager
from ai.multi_agent_trainer import MultiAgentTrainer
from config_loader import get_config_loader
from ai.game_replay_logger import GameReplayIntegration
import torch
import time  # Add time import for StepLogger timestamps
from tqdm import tqdm  # For episode progress bar
import gymnasium as gym  # For SelfPlayWrapper to inherit from gym.Wrapper

# Environment wrappers (extracted to ai/env_wrappers.py)
from ai.env_wrappers import BotControlledEnv, SelfPlayWrapper
from ai.macro_training_env import MacroTrainingWrapper, MacroVsBotWrapper

# Step logger (extracted to ai/step_logger.py)
from ai.step_logger import StepLogger

# Bot evaluation (extracted to ai/bot_evaluation.py)
from ai.bot_evaluation import evaluate_against_bots

# Training callbacks (extracted to ai/training_callbacks.py)
from ai.training_callbacks import (
    EntropyScheduleCallback,
    EpisodeTerminationCallback,
    EpisodeBasedEvalCallback,
    MetricsCollectionCallback,
    BotEvaluationCallback
)

# Training utilities (extracted to ai/training_utils.py)
from ai.training_utils import (
    check_gpu_availability,
    setup_imports,
    make_training_env,
    get_agent_scenario_file,
    get_scenario_list_for_phase,
    ensure_scenario
)

from shared.data_validation import require_key

# Replay converter (extracted to ai/replay_converter.py)
from ai.replay_converter import (
    extract_scenario_name_for_replay,
    convert_steplog_to_replay,
    generate_steplog_and_replay,
    parse_steplog_file,
    parse_action_message,
    calculate_episode_reward_from_actions,
    convert_to_replay_format
)



# Global step logger instance
step_logger = None

def create_model(config, training_config_name, rewards_config_name, new_model, append_training, args):
    """Create or load PPO model with configuration following AI_INSTRUCTIONS.md."""
    
    # Import metrics tracker for training monitoring
    from metrics_tracker import W40KMetricsTracker
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration from config files (not script parameters)
    training_config = config.load_training_config(training_config_name)
    model_params = training_config["model_params"]

    # Handle entropy coefficient scheduling if configured
    # Use START value for model creation; callback will handle the schedule
    if "ent_coef" in model_params and isinstance(model_params["ent_coef"], dict):
        ent_config = model_params["ent_coef"]
        start_val = float(ent_config["start"])
        end_val = float(ent_config["end"])
        model_params["ent_coef"] = start_val  # Use initial value
        print(f"✅ Entropy coefficient schedule: {start_val} -> {end_val} (will be applied via callback)")

    # Import environment
    W40KEngine, register_environment = setup_imports()
    
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
    
    # CRITICAL FIX: Auto-detect controlled_agent from scenario's Player 0 units
    # This allows curriculum training without --agent parameter
    controlled_agent_key = None
    try:
        with open(scenario_file, 'r') as f:
            scenario_data = json.load(f)
    
        # Get first Player 0 unit to determine agent type
        units = require_key(scenario_data, "units")
        player_0_units = [u for u in units if require_key(u, "player") == 0]
        if player_0_units:
            first_unit_type = require_key(player_0_units[0], "unit_type")
            if first_unit_type:
                base_agent_key = unit_registry.get_model_key(first_unit_type)
                
                # CRITICAL FIX: Use rewards_config_name directly as controlled_agent_key
                # rewards_config.json has keys like "SpaceMarine_Infantry_Troop_RangedSwarm_phase1"
                # The rewards_config_name parameter already contains the full key
                if rewards_config_name not in ["default", "test"]:
                    controlled_agent_key = rewards_config_name
                    print(f"ℹ️  Auto-detected base agent: {base_agent_key}")
                    print(f"✅ Using phase-specific rewards: {controlled_agent_key}")
                else:
                    controlled_agent_key = base_agent_key
                    print(f"ℹ️  Auto-detected controlled_agent: {controlled_agent_key}")
                
    except Exception as e:
        print(f"⚠️  Failed to auto-detect controlled_agent: {e}")
        raise ValueError(f"Cannot proceed without controlled_agent - auto-detection failed: {e}")
    
    # ✓ CHANGE 3: Check if vectorization is enabled in config
    n_envs = require_key(training_config, "n_envs")
    
    # ✓ CHANGE 3: Special handling for replay/steplog modes (must be single env)
    if args.replay or args.convert_steplog:
        n_envs = 1  # Force single environment for replay generation
        print("ℹ️  Replay mode: Using single environment (vectorization disabled)")
    
    if n_envs > 1:
        # ✓ CHANGE 3: Create vectorized environments for parallel training
        print(f"🚀 Creating {n_envs} parallel environments for accelerated training...")
        
        # Disable step logger for vectorized training (avoid file conflicts)
        vec_envs = SubprocVecEnv([
            make_training_env(
                rank=i,
                scenario_file=scenario_file,
                rewards_config_name=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent_key=controlled_agent_key,
                unit_registry=unit_registry,
                step_logger_enabled=False,  # Disabled for parallel envs
                debug_mode=args.debug
            )
            for i in range(n_envs)
        ])
        
        env = vec_envs
        print(f"✅ Vectorized training environment created with {n_envs} parallel processes")
        
    else:
        # ✓ CHANGE 3: Single environment (original behavior)
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent_key,  # Use auto-detected agent
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=args.debug
        )
        
        # Connect step logger after environment creation - compliant engine compatibility
        if step_logger:
            # Connect StepLogger directly to compliant W40KEngine
            base_env.step_logger = step_logger
            print("✅ StepLogger connected to compliant W40KEngine")
        
        # Enable replay logging for replay generation modes only
        if args.replay or args.convert_steplog:
            # Use same pattern as evaluate.py for working icon movement
            base_env.is_evaluation_mode = True
            base_env._force_evaluation_mode = True
            # Direct integration without wrapper
            base_env = GameReplayIntegration.enhance_training_env(base_env)
            if hasattr(base_env, 'replay_logger') and base_env.replay_logger:
                base_env.replay_logger.is_evaluation_mode = True
                base_env.replay_logger.capture_initial_state()
        
        # Wrap environment with ActionMasker for MaskablePPO compatibility
        def mask_fn(env):
            return env.get_action_mask()
        
        masked_env = ActionMasker(base_env, mask_fn)

        # CRITICAL: Wrap with SelfPlayWrapper for proper self-play training
        # This ensures Player 1 uses a frozen model copy, not the learning agent
        # Without this, both P0 and P1 actions go into SB3's buffer with P1 getting 0.0 rewards
        selfplay_env = SelfPlayWrapper(masked_env, frozen_model=None, update_frequency=100)

        # SB3 Required: Monitor wrapped environment
        env = Monitor(selfplay_env)
    
    # Check if action masking is available (works for both vectorized and single env)
    if n_envs == 1:
        if hasattr(base_env, 'get_action_mask'):
            print("✅ Action masking enabled - AI will only see valid actions")
        else:
            print("⚠️ Action masking not available")
    
    # Check if action masking is available
    if hasattr(base_env, 'get_action_mask'):
        print("✅ Action masking enabled - AI will only see valid actions")
    else:
        print("⚠️ Action masking not available")
    
    # Use auto-detected agent key for model path
    if controlled_agent_key:
        model_path = config.get_model_path().replace('.zip', f'_{controlled_agent_key}.zip')
        print(f"📝 Using agent-specific model path: {model_path}")
    else:
        model_path = config.get_model_path()
        print(f"📝 Using generic model path: {model_path}")
    
    # Set device for model creation
    # PPO optimization: MlpPolicy performs BETTER on CPU (proven by benchmarks)
    # GPU only beneficial for CNN policies or networks with >2000 hidden units
    policy_kwargs = require_key(model_params, "policy_kwargs")
    net_arch = require_key(policy_kwargs, "net_arch")
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512

    # BENCHMARK RESULTS: CPU 311 it/s vs GPU 282 it/s (10% faster on CPU)
    # Use GPU only for very large networks (>2000 hidden units)
    obs_size = env.observation_space.shape[0]
    use_gpu = gpu_available and (total_params > 2000)  # Removed obs_size check
    device = "cuda" if use_gpu else "cpu"

    model_params["device"] = device
    model_params["verbose"] = 0  # Disable verbose logging

    if not use_gpu and gpu_available:
        print(f"ℹ️  Using CPU for PPO (10% faster than GPU for MlpPolicy with {obs_size} features)")
        print(f"ℹ️  Benchmark: CPU 311 it/s vs GPU 282 it/s")
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model on {device.upper()}...")
        print("✅ Using MaskablePPO with action masking for tactical combat")

        # Use specific log directory for continuous TensorBoard graphs across runs
        tb_log_name = f"{training_config_name}_{controlled_agent_key}"
        specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
        os.makedirs(specific_log_dir, exist_ok=True)

        # Update model_params to use specific directory
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir

        model = MaskablePPO(env=env, **model_params_copy)
        # Properly suppress rollout console output
        if hasattr(model, '_logger') and model._logger:
            original_info = model._logger.info
            def filtered_info(msg):
                if not any(x in str(msg) for x in ['rollout/', 'exploration_rate']):
                    original_info(msg)
            model._logger.info = filtered_info
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
            # Update any model parameters that might have changed
            model.tensorboard_log = model_params["tensorboard_log"]
            model.verbose = model_params["verbose"]

            # CURRICULUM LEARNING: Apply new phase hyperparameters to loaded model
            # This allows Phase 2 to use different learning rates, entropy, etc. than Phase 1
            # while preserving the neural network weights learned in Phase 1
            if "learning_rate" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.learning_rate = get_schedule_fn(model_params["learning_rate"])
            if "ent_coef" in model_params:
                model.ent_coef = model_params["ent_coef"]
            if "clip_range" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.clip_range = get_schedule_fn(model_params["clip_range"])
            if "gamma" in model_params:
                model.gamma = model_params["gamma"]
            if "gae_lambda" in model_params:
                model.gae_lambda = model_params["gae_lambda"]
            if "n_steps" in model_params:
                model.n_steps = model_params["n_steps"]
            if "batch_size" in model_params:
                model.batch_size = model_params["batch_size"]
            if "n_epochs" in model_params:
                model.n_epochs = model_params["n_epochs"]
            if "vf_coef" in model_params:
                model.vf_coef = model_params["vf_coef"]
            if "max_grad_norm" in model_params:
                model.max_grad_norm = model_params["max_grad_norm"]

            print(f"✅ Applied new phase hyperparameters: lr={model.learning_rate}, ent={model.ent_coef}, clip={model.clip_range}")

            # CRITICAL FIX: Reinitialize logger after loading from checkpoint
            # This ensures PPO training metrics (policy_loss, value_loss, etc.) are logged correctly
            # Without this, model.logger.name_to_value remains empty/stale from the checkpoint
            from stable_baselines3.common.logger import configure

            # Use specific log directory to ensure continuous TensorBoard graphs across runs
            # Format: ./tensorboard/{config_name}_{controlled_agent_key}/{run_name}
            # This prevents creating new timestamped subdirectories on each script run
            tb_log_name = f"{training_config_name}_{controlled_agent_key}"
            specific_log_dir = os.path.join(model.tensorboard_log, tb_log_name)

            # Create directory if it doesn't exist
            os.makedirs(specific_log_dir, exist_ok=True)

            new_logger = configure(specific_log_dir, ["tensorboard"])
            model.set_logger(new_logger)
            print(f"✅ Logger reinitialized for continuous TensorBoard: {specific_log_dir}")
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            # Use same specific directory as above
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            model = MaskablePPO(env=env, **model_params_copy)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            # Need to create specific directory here too
            tb_log_name = f"{training_config_name}_{controlled_agent_key}"
            specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
            os.makedirs(specific_log_dir, exist_ok=True)
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            model = MaskablePPO(env=env, **model_params_copy)

    return model, env, training_config, model_path

def create_multi_agent_model(config, training_config_name="default", rewards_config_name="default",
                            agent_key=None, new_model=False, append_training=False, scenario_override=None, debug_mode=False):
    """Create or load PPO model for specific agent with configuration following AI_INSTRUCTIONS.md."""
    
    # Check GPU availability
    gpu_available = check_gpu_availability()
    
    # Load training configuration - agent-specific REQUIRED when agent_key provided
    if agent_key:
        # CRITICAL: NO FALLBACK - agent-specific config MUST exist
        training_config = config.load_agent_training_config(agent_key, training_config_name)
        print(f"✅ Loaded agent-specific training config: config/agents/{agent_key}/{agent_key}_training_config.json [{training_config_name}]")
        agent_specific_mode = True
    else:
        # No agent specified, use global config
        training_config = config.load_training_config(training_config_name)
        agent_specific_mode = False

    model_params = training_config["model_params"]

    # Handle entropy coefficient scheduling if configured
    # Use START value for model creation; callback will handle the schedule
    if "ent_coef" in model_params and isinstance(model_params["ent_coef"], dict):
        ent_config = model_params["ent_coef"]
        start_val = float(ent_config["start"])
        end_val = float(ent_config["end"])
        model_params["ent_coef"] = start_val  # Use initial value
        print(f"✅ Entropy coefficient schedule: {start_val} -> {end_val} (will be applied via callback)")

    # Import environment
    W40KEngine, register_environment = setup_imports()
    
    # Register environment
    register_environment()
    
    # Create agent-specific environment
    cfg = get_config_loader()
    
    # Get scenario file (agent-specific or global)
    scenario_file = get_agent_scenario_file(cfg, agent_key if agent_specific_mode else None, training_config_name, scenario_override)
    print(f"✅ Using scenario: {scenario_file}")
    # Load unit registry for multi-agent environment
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    # CRITICAL FIX: Use rewards_config_name for controlled_agent (includes phase suffix)
    # agent_key is the directory name for config loading
    # rewards_config_name is the SECTION NAME within the rewards file (e.g., "..._phase1")
    effective_agent_key = rewards_config_name if rewards_config_name else agent_key
    
    # ✓ CHANGE 8: Check if vectorization is enabled in config
    n_envs = require_key(training_config, "n_envs")
    
    if n_envs > 1:
        # ✓ CHANGE 8: Create vectorized environments for parallel training
        print(f"🚀 Creating {n_envs} parallel environments for accelerated training...")
        
        vec_envs = SubprocVecEnv([
            make_training_env(
                rank=i,
                scenario_file=scenario_file,
                rewards_config_name=rewards_config_name,
                training_config_name=training_config_name,
                controlled_agent_key=effective_agent_key,
                unit_registry=unit_registry,
                step_logger_enabled=False,
                debug_mode=debug_mode
            )
            for i in range(n_envs)
        ])
        
        env = vec_envs
        print(f"✅ Vectorized training environment created with {n_envs} parallel processes")
        
    else:
        # ✓ CHANGE 8: Single environment (original behavior)
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=effective_agent_key,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=debug_mode
        )
        
        # Connect step logger after environment creation - compliant engine compatibility
        if step_logger:
            # Connect StepLogger directly to compliant W40KEngine
            base_env.step_logger = step_logger
            print("✅ StepLogger connected to compliant W40KEngine")
        
        # Wrap environment with ActionMasker for MaskablePPO compatibility
        def mask_fn(env):
            return env.get_action_mask()

        masked_env = ActionMasker(base_env, mask_fn)

        # Check if scenario name contains "bot" to use BotControlledEnv
        scenario_name = os.path.basename(scenario_file) if scenario_file else ""
        use_bot_env = "bot" in scenario_name.lower()

        if use_bot_env and EVALUATION_BOTS_AVAILABLE:
            # Use BotControlledEnv with GreedyBot for bot scenarios
            training_bot = GreedyBot(randomness=0.15)
            bot_env = BotControlledEnv(masked_env, training_bot, unit_registry)
            env = Monitor(bot_env)
            print(f"🤖 Using GreedyBot (randomness=0.15) for Player 1 (detected 'bot' in scenario name)")
        else:
            # CRITICAL: Wrap with SelfPlayWrapper for proper self-play training
            # Without this, P1 never takes actions and the game is broken
            selfplay_env = SelfPlayWrapper(masked_env, frozen_model=None, update_frequency=100)
            env = Monitor(selfplay_env)
    
    # Agent-specific model path
    model_path = config.get_model_path().replace('.zip', f'_{agent_key}.zip')
    
    # Set device for model creation
    # PPO optimization: MlpPolicy performs BETTER on CPU (proven by benchmarks)
    # GPU only beneficial for CNN policies or networks with >2000 hidden units
    policy_kwargs = require_key(model_params, "policy_kwargs")
    net_arch = require_key(policy_kwargs, "net_arch")
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512

    # BENCHMARK RESULTS: CPU 311 it/s vs GPU 282 it/s (10% faster on CPU)
    # Use GPU only for very large networks (>2000 hidden units)
    obs_size = env.observation_space.shape[0]
    use_gpu = gpu_available and (total_params > 2000)  # Removed obs_size check
    device = "cuda" if use_gpu else "cpu"

    model_params["device"] = device

    if not use_gpu and gpu_available:
        print(f"ℹ️  Using CPU for {agent_key} PPO (10% faster than GPU for MlpPolicy)")
    
    # Determine whether to create new model or load existing
    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model for {agent_key} on {device.upper()}...")

        # Use specific log directory for continuous TensorBoard graphs across runs
        tb_log_name = f"{training_config_name}_{agent_key}"
        specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
        os.makedirs(specific_log_dir, exist_ok=True)

        # Update model_params to use specific directory
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir

        model = MaskablePPO(env=env, **model_params_copy)
        # Disable rollout logging for multi-agent models too
        if hasattr(model, 'logger') and model.logger:
            model.logger.record = lambda key, value, exclude=None: None if key.startswith('rollout/') else model.logger.record.__wrapped__(key, value, exclude)
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
            if "tensorboard_log" not in model_params:
                raise KeyError("model_params missing required 'tensorboard_log' field")
            model.tensorboard_log = model_params["tensorboard_log"]
            model.verbose = model_params["verbose"]

            # CURRICULUM LEARNING: Apply new phase hyperparameters to loaded model
            # This allows Phase 2 to use different learning rates, entropy, etc. than Phase 1
            # while preserving the neural network weights learned in Phase 1
            if "learning_rate" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.learning_rate = get_schedule_fn(model_params["learning_rate"])
            if "ent_coef" in model_params:
                model.ent_coef = model_params["ent_coef"]
            if "clip_range" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.clip_range = get_schedule_fn(model_params["clip_range"])
            if "gamma" in model_params:
                model.gamma = model_params["gamma"]
            if "gae_lambda" in model_params:
                model.gae_lambda = model_params["gae_lambda"]
            if "n_steps" in model_params:
                model.n_steps = model_params["n_steps"]
            if "batch_size" in model_params:
                model.batch_size = model_params["batch_size"]
            if "n_epochs" in model_params:
                model.n_epochs = model_params["n_epochs"]
            if "vf_coef" in model_params:
                model.vf_coef = model_params["vf_coef"]
            if "max_grad_norm" in model_params:
                model.max_grad_norm = model_params["max_grad_norm"]

            print(f"✅ Applied new phase hyperparameters: lr={model.learning_rate}, ent={model.ent_coef}, clip={model.clip_range}")

            # CRITICAL FIX: Reinitialize logger after loading from checkpoint
            # This ensures PPO training metrics (policy_loss, value_loss, etc.) are logged correctly
            # Without this, model.logger.name_to_value remains empty/stale from the checkpoint
            from stable_baselines3.common.logger import configure

            # Use specific log directory to ensure continuous TensorBoard graphs across runs
            # Format: ./tensorboard/{config_name}_{agent_key}/{run_name}
            # This prevents creating new timestamped subdirectories on each script run
            tb_log_name = f"{training_config_name}_{agent_key}"
            specific_log_dir = os.path.join(model.tensorboard_log, tb_log_name)

            # Create directory if it doesn't exist
            os.makedirs(specific_log_dir, exist_ok=True)

            new_logger = configure(specific_log_dir, ["tensorboard"])
            model.set_logger(new_logger)
            print(f"✅ Logger reinitialized for continuous TensorBoard: {specific_log_dir}")
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            # Use same specific directory as above
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            model = MaskablePPO(env=env, **model_params_copy)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("�' Creating new model instead...")
            # Need to create specific directory here too
            tb_log_name = f"{training_config_name}_{agent_key}"
            specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
            os.makedirs(specific_log_dir, exist_ok=True)
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            model = MaskablePPO(env=env, **model_params_copy)
    
    return model, env, training_config, model_path


def create_macro_controller_model(config, training_config_name, rewards_config_name,
                                  agent_key, new_model=False, append_training=False,
                                  scenario_override=None, debug_mode=False):
    """Create or load PPO model for MacroController with macro training wrapper."""
    gpu_available = check_gpu_availability()

    training_config = config.load_agent_training_config(agent_key, training_config_name)
    print(
        f"✅ Loaded agent-specific training config: "
        f"config/agents/{agent_key}/{agent_key}_training_config.json [{training_config_name}]"
    )

    model_params = training_config["model_params"]

    # Handle entropy coefficient scheduling if configured
    if "ent_coef" in model_params and isinstance(model_params["ent_coef"], dict):
        ent_config = model_params["ent_coef"]
        start_val = float(ent_config["start"])
        end_val = float(ent_config["end"])
        model_params["ent_coef"] = start_val
        print(f"✅ Entropy coefficient schedule: {start_val} -> {end_val} (will be applied via callback)")

    W40KEngine, register_environment = setup_imports()
    register_environment()

    cfg = get_config_loader()

    scenario_file = None
    if scenario_override:
        if os.path.isfile(scenario_override):
            scenario_file = scenario_override
        else:
            scenario_file = get_agent_scenario_file(cfg, agent_key, training_config_name, scenario_override)
    else:
        scenario_file = get_agent_scenario_file(cfg, agent_key, training_config_name, scenario_override)

    print(f"✅ Using scenario: {scenario_file}")

    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()

    effective_agent_key = rewards_config_name if rewards_config_name else agent_key

    n_envs = require_key(training_config, "n_envs")
    if n_envs != 1:
        raise ValueError(f"MacroController training requires n_envs=1 (got {n_envs})")

    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=effective_agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=debug_mode
    )

    if step_logger:
        base_env.step_logger = step_logger
        print("✅ StepLogger connected to compliant W40KEngine")

    macro_player = require_key(training_config, "macro_player")

    model_path_template = config.get_model_path()
    if not model_path_template.endswith(".zip"):
        raise ValueError(f"Invalid model_file path for macro training: {model_path_template}")
    model_path_template = model_path_template.replace(".zip", "_{model_key}.zip")

    macro_env = MacroTrainingWrapper(
        base_env=base_env,
        unit_registry=unit_registry,
        scenario_files=[scenario_file],
        model_path_template=model_path_template,
        macro_player=macro_player,
        debug_mode=debug_mode
    )

    def mask_fn(env):
        return env.get_action_mask()

    masked_env = ActionMasker(macro_env, mask_fn)
    env = Monitor(masked_env)

    model_path = config.get_model_path().replace(".zip", f"_{agent_key}.zip")

    policy_kwargs = require_key(model_params, "policy_kwargs")
    net_arch = require_key(policy_kwargs, "net_arch")
    total_params = sum(net_arch) if isinstance(net_arch, list) else 512
    use_gpu = gpu_available and (total_params > 2000)
    device = "cuda" if use_gpu else "cpu"
    model_params["device"] = device

    if not use_gpu and gpu_available:
        print(f"ℹ️  Using CPU for {agent_key} PPO (10% faster than GPU for MlpPolicy)")

    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model for {agent_key} on {device.upper()}...")
        tb_log_name = f"{training_config_name}_{agent_key}"
        specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
        os.makedirs(specific_log_dir, exist_ok=True)
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        model = MaskablePPO(env=env, **model_params_copy)
    else:
        print(f"📁 Loading existing model: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env, device=device)
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            tb_log_name = f"{training_config_name}_{agent_key}"
            specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
            os.makedirs(specific_log_dir, exist_ok=True)
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            model = MaskablePPO(env=env, **model_params_copy)

    return model, env, training_config, model_path


def _build_macro_eval_env(config, training_config_name, rewards_config_name, agent_key,
                          scenario_override, debug_mode, bot=None):
    W40KEngine, register_environment = setup_imports()
    register_environment()
    cfg = get_config_loader()
    scenario_file = get_agent_scenario_file(cfg, agent_key, training_config_name, scenario_override)
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    effective_agent_key = rewards_config_name if rewards_config_name else agent_key
    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=effective_agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=debug_mode
    )
    if step_logger and step_logger.enabled:
        base_env.step_logger = step_logger
    training_config = config.load_agent_training_config(agent_key, training_config_name)
    macro_player = require_key(training_config, "macro_player")
    model_path_template = config.get_model_path().replace(".zip", "_{model_key}.zip")
    if bot is None:
        return MacroTrainingWrapper(
            base_env=base_env,
            unit_registry=unit_registry,
            scenario_files=[scenario_file],
            model_path_template=model_path_template,
            macro_player=macro_player,
            debug_mode=debug_mode
        )
    return MacroVsBotWrapper(
        base_env=base_env,
        unit_registry=unit_registry,
        scenario_files=[scenario_file],
        model_path_template=model_path_template,
        macro_player=macro_player,
        bot=bot,
        debug_mode=debug_mode
    )


def _print_eval_progress(completed, total, start_time, label):
    progress_pct = (completed / total) * 100
    bar_length = 50
    filled = int(bar_length * completed / total)
    bar = '█' * filled + '░' * (bar_length - filled)

    elapsed = time.time() - start_time
    avg_time = elapsed / completed if completed > 0 else 0
    remaining = total - completed
    eta = avg_time * remaining

    def format_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    elapsed_str = format_time(elapsed)
    eta_str = format_time(eta)
    speed = completed / elapsed if elapsed > 0 else 0
    speed_str = f"{speed:.2f}ep/s" if speed >= 0.01 else f"{speed * 60:.1f}ep/m"

    sys.stdout.write(f"\r{progress_pct:3.0f}% {bar} {completed}/{total} {label} [{elapsed_str}<{eta_str}, {speed_str}]")
    sys.stdout.flush()


def _evaluate_macro_model(model, env, n_episodes, macro_player, deterministic=True, progress_state=None, label=""):
    wins = 0
    losses = 0
    draws = 0
    for _ in range(n_episodes):
        obs, _info = env.reset()
        done = False
        while not done:
            action_masks = env.get_action_mask()
            action, _ = model.predict(obs, action_masks=action_masks, deterministic=deterministic)
            obs, _reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        winner = None
        if isinstance(info, dict):
            winner = info.get("winner")
        if winner is None:
            winner, _win_method = env.engine._determine_winner_with_method()
        if winner == macro_player:
            wins += 1
        elif winner in (1, 2):
            losses += 1
        else:
            draws += 1
        if progress_state is not None:
            progress_state["completed"] += 1
            _print_eval_progress(progress_state["completed"], progress_state["total"], progress_state["start_time"], label)
    return wins, losses, draws

def train_with_scenario_rotation(config, agent_key, training_config_name, rewards_config_name,
                                 scenario_list, total_episodes,
                                 new_model=False, append_training=False, use_bots=False, debug_mode=False):
    """Train model with random scenario selection per episode.
    
    Args:
        config: ConfigLoader instance
        agent_key: Agent identifier
        training_config_name: Phase name (e.g., 'phase2')
        rewards_config_name: Rewards config name
        scenario_list: List of scenario file paths (randomly selected per episode)
        total_episodes: Total episodes for entire training
        new_model: Whether to create new model
        append_training: Whether to continue from existing model
        use_bots: If True, use bots for Player 1 instead of self-play frozen model

    Returns:
        Tuple of (success: bool, final_model, final_env)
    """
    print(f"\n{'='*80}")
    print(f"🔄 MULTI-SCENARIO TRAINING")
    print(f"{'='*80}")
    print(f"Total episodes: {total_episodes}")
    print(f"Scenarios: {len(scenario_list)}")
    for i, scenario in enumerate(scenario_list, 1):
        scenario_name = os.path.basename(scenario)
        print(f"  {i}. {scenario_name}")
    if len(scenario_list) > 1:
        print(f"🎲 RANDOM MODE: Each episode randomly selects one of the {len(scenario_list)} scenarios")
    print(f"{'='*80}\n")

    # Check GPU availability (match single-scenario training output)
    gpu_available = check_gpu_availability()
    
    # Load agent-specific training config to get model parameters
    training_config = config.load_agent_training_config(agent_key, training_config_name)

    # Require n_envs for consistency with single-scenario training
    n_envs = require_key(training_config, "n_envs")
    if n_envs != 1:
        raise ValueError(
            f"train_with_scenario_rotation requires n_envs=1 (got {n_envs})"
        )

    # Raise error if required fields missing - NO FALLBACKS
    if "max_turns_per_episode" not in training_config:
        raise KeyError(f"max_turns_per_episode missing from {agent_key} training config phase {training_config_name}")

    # AUTO-CALCULATE max_steps_per_turn = num_units × num_phases
    # Load first scenario to count units
    first_scenario = scenario_list[0]
    with open(first_scenario, 'r') as f:
        scenario_data = json.load(f)
    num_units = len(require_key(scenario_data, "units"))

    # Import GAME_PHASES from action_decoder - single source of truth
    from engine.action_decoder import GAME_PHASES
    num_phases = len(GAME_PHASES)

    # Calculate max_steps_per_turn dynamically
    max_steps = num_units * num_phases
    print(f"📊 Auto-calculated max_steps_per_turn: {num_units} units × {num_phases} phases = {max_steps}")

    # Calculate average steps per episode for timestep conversion
    max_turns = training_config["max_turns_per_episode"]
    avg_steps_per_episode = max_turns * max_steps * 0.6  # Estimate: 60% of max
    
    # Get model path
    model_path = config.get_model_path().replace('.zip', f'_{agent_key}.zip')
    
    # Create initial model with first scenario (or load if append_training)
    print(f"📦 {'Loading existing model' if append_training else 'Creating initial model'} with first scenario...")
    
    # Import environment
    W40KEngine, register_environment = setup_imports()
    register_environment()
    
    # Create initial environment with first scenario
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    # CRITICAL FIX: Use rewards_config_name for controlled_agent (includes phase suffix)
    # agent_key is the directory name for config loading
    # rewards_config_name is the SECTION NAME within the rewards file (e.g., "..._phase1")
    effective_agent_key = rewards_config_name if rewards_config_name else agent_key
    
    current_scenario = scenario_list[0]
    # Pass full scenario list for random selection per episode
    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=effective_agent_key,
        active_agents=None,
        scenario_file=current_scenario,
        scenario_files=scenario_list,  # NEW: Random scenario selection per episode
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=debug_mode
    )

    # Connect step logger after environment creation - compliant engine compatibility
    if step_logger:
        # Connect StepLogger directly to compliant W40KEngine
        base_env.step_logger = step_logger
        print("✅ StepLogger connected to compliant W40KEngine")

    # Wrap environment
    def mask_fn(env):
        return env.get_action_mask()

    masked_env = ActionMasker(base_env, mask_fn)

    # Create initial bot for bot training mode (needed before model creation)
    initial_bot = None
    if use_bots:
        if EVALUATION_BOTS_AVAILABLE:
            initial_bot = GreedyBot(randomness=0.15)
        else:
            raise ImportError("Evaluation bots not available but use_bots=True")

    # Wrap environment appropriately for bot or self-play training
    if use_bots and initial_bot:
        bot_env = BotControlledEnv(masked_env, initial_bot, unit_registry)
        env = Monitor(bot_env)
    else:
        env = Monitor(masked_env)
    
    # Create or load model
    model_params = training_config["model_params"]

    # Handle entropy coefficient scheduling if configured
    # Use START value for model creation; callback will handle the schedule
    if "ent_coef" in model_params and isinstance(model_params["ent_coef"], dict):
        ent_config = model_params["ent_coef"]
        start_val = float(ent_config["start"])
        end_val = float(ent_config["end"])
        model_params["ent_coef"] = start_val  # Use initial value
        print(f"✅ Entropy coefficient schedule: {start_val} -> {end_val} (will be applied via callback)")

    # Use specific log directory for continuous TensorBoard graphs across runs
    tb_log_name = f"{training_config_name}_{agent_key}"
    specific_log_dir = os.path.join(model_params["tensorboard_log"], tb_log_name)
    os.makedirs(specific_log_dir, exist_ok=True)

    if new_model or not os.path.exists(model_path):
        print(f"🆕 Creating new model: {model_path}")
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        model = MaskablePPO(env=env, **model_params_copy)
    elif append_training:
        print(f"📁 Loading existing model for continued training: {model_path}")
        try:
            model = MaskablePPO.load(model_path, env=env)

            # CURRICULUM LEARNING: Apply new phase hyperparameters to loaded model
            # This allows Phase 2 to use different learning rates, entropy, etc. than Phase 1
            # while preserving the neural network weights learned in Phase 1
            if "learning_rate" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.learning_rate = get_schedule_fn(model_params["learning_rate"])
            if "ent_coef" in model_params:
                model.ent_coef = model_params["ent_coef"]
            if "clip_range" in model_params:
                # Convert to callable schedule function (required by PPO)
                model.clip_range = get_schedule_fn(model_params["clip_range"])
            if "gamma" in model_params:
                model.gamma = model_params["gamma"]
            if "gae_lambda" in model_params:
                model.gae_lambda = model_params["gae_lambda"]
            if "n_steps" in model_params:
                model.n_steps = model_params["n_steps"]
            if "batch_size" in model_params:
                model.batch_size = model_params["batch_size"]
            if "n_epochs" in model_params:
                model.n_epochs = model_params["n_epochs"]
            if "vf_coef" in model_params:
                model.vf_coef = model_params["vf_coef"]
            if "max_grad_norm" in model_params:
                model.max_grad_norm = model_params["max_grad_norm"]

            print(f"✅ Applied new phase hyperparameters: lr={model.learning_rate}, ent={model.ent_coef}, clip={model.clip_range}")

            # CRITICAL FIX: Reinitialize logger after loading from checkpoint
            # This ensures PPO training metrics (policy_loss, value_loss, etc.) are logged correctly
            # Without this, model.logger.name_to_value remains empty/stale from the checkpoint
            from stable_baselines3.common.logger import configure
            new_logger = configure(specific_log_dir, ["tensorboard"])
            model.set_logger(new_logger)
            print(f"✅ Logger reinitialized for continuous TensorBoard: {specific_log_dir}")
        except Exception as e:
            print(f"⚠️ Failed to load model: {e}")
            print("🆕 Creating new model instead...")
            model_params_copy = model_params.copy()
            model_params_copy["tensorboard_log"] = specific_log_dir
            model = MaskablePPO(env=env, **model_params_copy)
    else:
        print(f"⚠️ Model exists but neither --new nor --append specified. Creating new model.")
        model_params_copy = model_params.copy()
        model_params_copy["tensorboard_log"] = specific_log_dir
        model = MaskablePPO(env=env, **model_params_copy)
    
    # Import metrics tracker
    from ai.metrics_tracker import W40KMetricsTracker

    # Initialize frozen model for self-play
    # The frozen model is a copy of the learning model used by Player 1
    frozen_model = None
    frozen_model_update_frequency = 100  # Episodes between frozen model updates
    last_frozen_model_update = 0

    # Use the bot created earlier for training mode
    training_bot = initial_bot
    if use_bots and training_bot:
        print(f"🤖 Using GreedyBot (randomness=0.15) for Player 1")

    # Determine tensorboard log name for continuous logging
    tb_log_name = f"{training_config_name}_{agent_key}"
    
    # Get TensorBoard directory for metrics
    model_tensorboard_dir = f"./tensorboard/{tb_log_name}"
    
    # Create metrics tracker for entire rotation training
    metrics_tracker = W40KMetricsTracker(agent_key, model_tensorboard_dir)
    # print(f"📈 Metrics tracking enabled for agent: {agent_key}")

    # Create metrics callback ONCE before loop (not inside it)
    from stable_baselines3.common.callbacks import CallbackList
    metrics_callback = MetricsCollectionCallback(metrics_tracker, model, controlled_agent=effective_agent_key)

    # Training loop with random scenario selection per episode
    episodes_trained = 0

    # Global start time for callbacks
    global_start_time = time.time()

    # Progress bar is handled by EpisodeTerminationCallback

    # PPO requires n_steps rollouts before each update; we use this as a natural chunk size
    # for our episode-budgeted outer loop.
    n_steps = training_config["model_params"]["n_steps"]
    chunk_timesteps = n_steps * 4  # 4 updates per chunk for stable gradients

    # Use first scenario for initial setup (scenario selection is random per episode)
    initial_scenario = scenario_list[0]
    
    # Create environment with scenario list for random selection per episode
    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=effective_agent_key,
        active_agents=None,
        scenario_file=initial_scenario,
        scenario_files=scenario_list,  # Random scenario selection per episode
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=debug_mode
    )

    # Wrap environment with action masking first
    masked_env = ActionMasker(base_env, mask_fn)

    # For bot training, use BotControlledEnv to handle Player 1's bot actions
    if use_bots:
        bot_env = BotControlledEnv(masked_env, training_bot, unit_registry)
        env = Monitor(bot_env)
    else:
        # CRITICAL: Update frozen model periodically for proper self-play
        if episodes_trained - last_frozen_model_update >= frozen_model_update_frequency or frozen_model is None:
            # Save current model to temp file and load as frozen copy
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
                temp_path = f.name
            model.save(temp_path)
            frozen_model = MaskablePPO.load(temp_path)
            os.unlink(temp_path)  # Clean up temp file
            last_frozen_model_update = episodes_trained
            if episodes_trained > 0:
                print(f"  🔄 Self-play: Updated frozen opponent (Episode {episodes_trained})")

        # Wrap with SelfPlayWrapper for proper self-play training
        selfplay_env = SelfPlayWrapper(masked_env, frozen_model=frozen_model, update_frequency=frozen_model_update_frequency)
        env = Monitor(selfplay_env)
    
    # Update model's environment
    model.set_env(env)
    
    # Create callbacks for training
    scenario_display = f"Random from {len(scenario_list)} scenarios"
    training_callbacks = setup_callbacks(
        config=config,
        model_path=model_path,
        training_config=training_config,
        training_config_name=training_config_name,
        metrics_tracker=metrics_tracker,
        total_episodes_override=total_episodes,
        max_episodes_override=total_episodes,  # Train directly to total_episodes
        scenario_info=scenario_display,
        global_episode_offset=0,
        global_start_time=global_start_time
    )
    
    # Link metrics_tracker to bot evaluation callback
    for callback in training_callbacks:
        if hasattr(callback, '__class__') and callback.__class__.__name__ == 'BotEvaluationCallback':
            callback.metrics_tracker = metrics_tracker
    
    # Combine all callbacks
    enhanced_callbacks = CallbackList(training_callbacks + [metrics_callback])
    
    # Train directly to total_episodes using an EPISODE-BUDGETED wrapper around SB3.learn().
    #
    # SB3 only exposes a timestep budget, so we:
    # - repeatedly call learn() with a small, fixed chunk of timesteps
    # - after each chunk, check how many episodes actually completed (via metrics_tracker)
    # - stop when we reach the exact desired episode count (total_episodes)

    # CRITICAL: reset_num_timesteps=False keeps TensorBoard graph continuous across chunks.
    # We only allow SB3 to reset its internal counter at the very start of training.
    while metrics_tracker.episode_count < total_episodes:
        # As a safety guard, we still use the same chunk_timesteps. 
        # EpisodeTerminationCallback is responsible for stopping promptly when the episode budget is reached.
        model.learn(
            total_timesteps=chunk_timesteps,
            reset_num_timesteps=(metrics_tracker.episode_count == 0),
            tb_log_name=tb_log_name,  # Same name = continuous graph
            callback=enhanced_callbacks,
            log_interval=chunk_timesteps + 1,
            progress_bar=False  # Disabled - using episode-based progress
        )

    # Final episode count
    episodes_trained = metrics_tracker.episode_count

    # Final save
    model.save(model_path)
    print(f"\n{'='*80}")
    print(f"✅ TRAINING COMPLETE")
    print(f"   Total episodes trained: {episodes_trained}")
    print(f"   Final model: {model_path}")
    print(f"{'='*80}\n")

    # Run final comprehensive bot evaluation
    if EVALUATION_BOTS_AVAILABLE:
        if 'bot_eval_final' not in training_config['callback_params']:
            print("⚠️  Warning: 'bot_eval_final' not found in callback_params. Skipping final evaluation.")
        else:
            n_final = training_config['callback_params']['bot_eval_final']
            if n_final <= 0:
                print("ℹ️  Final bot evaluation skipped (bot_eval_final=0)")
            else:
                print(f"\n{'='*80}")
                print(f"🤖 FINAL BOT EVALUATION ({n_final} episodes per bot across all scenarios)")
                print(f"{'='*80}\n")

                bot_results = evaluate_against_bots(
                    model=model,
                    training_config_name=training_config_name,
                    rewards_config_name=rewards_config_name,
                    n_episodes=n_final,
                    controlled_agent=effective_agent_key,
                    show_progress=True,
                    deterministic=True,
                    step_logger=step_logger
                )

                # Log final results to metrics tracker
                if metrics_tracker and bot_results:
                    final_bot_results = {
                        'random': require_key(bot_results, 'random'),
                        'greedy': require_key(bot_results, 'greedy'),
                        'defensive': require_key(bot_results, 'defensive'),
                        'combined': require_key(bot_results, 'combined')
                    }
                    metrics_tracker.log_bot_evaluations(final_bot_results)

                # Print summary
                print(f"\n{'='*80}")
                print(f"📊 FINAL BOT EVALUATION RESULTS")
                print(f"{'='*80}")
                if bot_results:
                    for bot_name in ['random', 'greedy', 'defensive']:
                        if bot_name in bot_results:
                            win_rate = bot_results[bot_name] * 100
                            wins = require_key(bot_results, f'{bot_name}_wins')
                            losses = require_key(bot_results, f'{bot_name}_losses')
                            draws = require_key(bot_results, f'{bot_name}_draws')
                            print(f"  vs {bot_name.capitalize()}Bot:    {win_rate:5.1f}% ({wins}W-{losses}L-{draws}D)")

                    combined = require_key(bot_results, 'combined') * 100
                    print(f"  Combined Score: {combined:5.1f}%")
                print(f"{'='*80}\n")

    return True, model, env

def setup_callbacks(config, model_path, training_config, training_config_name="default", metrics_tracker=None,
                   total_episodes_override=None, max_episodes_override=None, scenario_info=None, global_episode_offset=0,
                   global_start_time=None, agent=None, rewards_config_name=None):
    W40KEngine, _ = setup_imports()
    callbacks = []
    
    # Add episode termination callback for debug AND step configs - NO FALLBACKS
    if "total_episodes" in training_config:
        if "total_episodes" not in training_config:
            raise KeyError(f"{training_config_name} training config missing required 'total_episodes'")
        if "max_turns_per_episode" not in training_config:
            raise KeyError(f"{training_config_name} training config missing required 'max_turns_per_episode'")
        if "max_steps_per_turn" not in training_config:
            raise KeyError(f"{training_config_name} training config missing required 'max_steps_per_turn'")
        
        max_episodes = training_config["total_episodes"]
        max_steps_per_episode = training_config["max_turns_per_episode"] * training_config["max_steps_per_turn"]
        expected_timesteps = max_episodes * max_steps_per_episode
        
        # Use overrides for rotation mode
        total_eps = total_episodes_override if total_episodes_override else max_episodes
        cycle_max_eps = max_episodes_override if max_episodes_override else max_episodes

        # Recalculate expected_timesteps for the actual cycle length
        if max_episodes_override:
            expected_timesteps = max_episodes_override * max_steps_per_episode

        # EPISODE-BASED ROTATION FIX: Always use episode-based stopping (never timestep-based)
        # The callback will stop training when exact episode count is reached
        # This prevents drift from timestep estimation errors
        episode_callback = EpisodeTerminationCallback(
            cycle_max_eps,  # Use cycle length, not total
            expected_timesteps,
            verbose=1,
            total_episodes=total_eps,
            scenario_info=scenario_info,
            disable_early_stopping=False,  # FIXED: Always stop at exact episode count
            global_start_time=global_start_time
        )
        episode_callback.global_episode_offset = global_episode_offset
        callbacks.append(episode_callback)

    # Add entropy coefficient schedule callback if configured
    if "model_params" in training_config and "ent_coef" in training_config["model_params"]:
        ent_coef = training_config["model_params"]["ent_coef"]
        if isinstance(ent_coef, dict) and "start" in ent_coef and "end" in ent_coef:
            start_ent = float(ent_coef["start"])
            end_ent = float(ent_coef["end"])
            total_eps = total_episodes_override if total_episodes_override else training_config["total_episodes"]

            entropy_callback = EntropyScheduleCallback(
                start_ent=start_ent,
                end_ent=end_ent,
                total_episodes=total_eps,
                verbose=1
            )
            callbacks.append(entropy_callback)
            print(f"✅ Added entropy schedule callback: {start_ent} -> {end_ent} over {total_eps} episodes")

    # Evaluation callback - test model periodically with logging enabled
    # Load scenario and unit registry for evaluation callback
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    
    # Load callback parameters for CheckpointCallback
    if "callback_params" not in training_config:
        raise KeyError("Training config missing required 'callback_params' field")
    callback_params = training_config["callback_params"]
    
    required_callback_fields = ["checkpoint_save_freq", "checkpoint_name_prefix"]
    for field in required_callback_fields:
        if field not in callback_params:
            raise KeyError(f"callback_params missing required '{field}' field")
    
    # Checkpoint callback - save model periodically
    # Use reasonable checkpoint frequency based on total timesteps and config
    if "checkpoint_save_freq" not in callback_params:
        raise KeyError("callback_params missing required 'checkpoint_save_freq' field")
    if "checkpoint_name_prefix" not in callback_params:
        raise KeyError("callback_params missing required 'checkpoint_name_prefix' field")
        
    checkpoint_callback = CheckpointCallback(
        save_freq=callback_params["checkpoint_save_freq"],
        save_path=os.path.dirname(model_path),
        name_prefix=callback_params["checkpoint_name_prefix"]
    )
    callbacks.append(checkpoint_callback)
    
    # Add enhanced bot evaluation callback (replaces standard EvalCallback)
    if EVALUATION_BOTS_AVAILABLE:
        # Read bot evaluation parameters from config
        bot_eval_freq = require_key(callback_params, "bot_eval_freq")
        bot_n_episodes_intermediate = require_key(callback_params, "bot_eval_intermediate")
        bot_eval_use_episodes = require_key(callback_params, "bot_eval_use_episodes")
        
        # Store final eval count for use after training completes
        training_config["_bot_eval_final"] = require_key(callback_params, "bot_eval_final")
        
        bot_eval_callback = BotEvaluationCallback(
            eval_freq=bot_eval_freq,
            n_eval_episodes=bot_n_episodes_intermediate,
            best_model_save_path=os.path.dirname(model_path),
            metrics_tracker=metrics_tracker,  # Pass metrics_tracker for TensorBoard logging
            use_episode_freq=bot_eval_use_episodes,
            verbose=1
        )
        callbacks.append(bot_eval_callback)
        
        freq_unit = "episodes" if bot_eval_use_episodes else "timesteps"
    else:
        print("⚠️ Evaluation bots not available - no evaluation metrics")
        print("   Install evaluation_bots.py to enable progress tracking")
    
    return callbacks

def train_model(model, training_config, callbacks, model_path, training_config_name, rewards_config_name, controlled_agent=None):
    """Execute the training process with metrics tracking."""
    
    # Import metrics tracker
    from ai.metrics_tracker import W40KMetricsTracker
    
    # Extract agent name from model path for metrics
    agent_name = "default_agent"
    if "_" in os.path.basename(model_path):
        agent_name = os.path.basename(model_path).replace('.zip', '').replace('model_', '')
    
    # CRITICAL FIX: Use model's TensorBoard directory for metrics_tracker
    # SB3 creates subdirectories like ./tensorboard/PPO_1/
    # metrics_tracker MUST write to the SAME directory to appear in TensorBoard
    # Access tensorboard_log from model parameters (logger not initialized until learn() is called)
    if hasattr(model, 'tensorboard_log') and model.tensorboard_log:
        model_tensorboard_dir = model.tensorboard_log
        print(f"📊 Metrics will be logged to: {model_tensorboard_dir}")
    else:
        model_tensorboard_dir = "./tensorboard/"
        print(f"⚠️  No tensorboard_log found, using default: {model_tensorboard_dir}")
   
    # Create metrics tracker using model's directory
    metrics_tracker = W40KMetricsTracker(agent_name, model_tensorboard_dir)
    
    try:
        # Start training
        # AI_TURN COMPLIANCE: Use episode-based training
        if 'total_timesteps' in training_config:
            total_timesteps = training_config['total_timesteps']
            safety_timesteps = total_timesteps
            print(f"🎯 Training Mode: Step-based ({total_timesteps:,} steps)")
        elif 'total_episodes' in training_config:
            total_episodes = training_config['total_episodes']
            # Calculate timesteps based on required config values - NO DEFAULTS ALLOWED
            if "max_turns_per_episode" not in training_config:
                raise KeyError(f"Training config missing required 'max_turns_per_episode' field")
            if "max_steps_per_turn" not in training_config:
                raise KeyError(f"Training config missing required 'max_steps_per_turn' field")
            max_turns_per_episode = training_config["max_turns_per_episode"]
            max_steps_per_turn = training_config["max_steps_per_turn"]
            
            # CRITICAL FIX: Episode count controlled by EpisodeTerminationCallback, not timesteps
            # Use 5x multiplier to ensure timestep limit never stops training early
            # This accounts for complex scenarios (more units = longer episodes)
            theoretical_timesteps = total_episodes * max_turns_per_episode * max_steps_per_turn
            total_timesteps = theoretical_timesteps * 5
            
            print(f"🎮 Training Mode: Episode-based ({total_episodes:,} episodes)")
            print(f"📊 Theoretical timesteps: {theoretical_timesteps:,}")
            print(f"🛡️ Timestep limit (5x buffer): {total_timesteps:,}")
            print(f"💡 EpisodeTerminationCallback will stop at exactly {total_episodes} episodes")
        else:
            raise ValueError("Training config must have either 'total_timesteps' or 'total_episodes'")
        
        # Startup info (disabled for cleaner output)
        # print(f"📊 Progress tracking: Episodes are primary metric (AI_TURN.md compliance)")
        # print(f"📈 Metrics tracking enabled for agent: {agent_name}")
        
        # Enhanced callbacks with metrics collection
        metrics_callback = MetricsCollectionCallback(metrics_tracker, model, controlled_agent=controlled_agent)
        
        # Attach metrics_tracker to bot_eval_callback if it exists
        for callback in callbacks:
            if isinstance(callback, BotEvaluationCallback):
                callback.metrics_tracker = metrics_tracker
                print(f"✅ Linked BotEvaluationCallback to metrics_tracker")
        
        all_callbacks = callbacks + [metrics_callback]
        enhanced_callbacks = CallbackList(all_callbacks)
        
        # Use consistent naming: training_config_agent_key
        tb_log_name = f"{training_config_name}_{agent_name}"
        
        model.learn(
            total_timesteps=total_timesteps,
            tb_log_name=tb_log_name,
            callback=enhanced_callbacks,
            log_interval=total_timesteps + 1,
            progress_bar=False  # Disabled - scenario mode uses episode-based progress
        )
        
        # Print final training summary with critical metrics and bot evaluation
        metrics_callback.print_final_training_summary(model=model, training_config=training_config, training_config_name=training_config_name, rewards_config_name=rewards_config_name)
        
        # Save final model
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        model.save(model_path)
        
        # Clean up checkpoint files after successful training
        model_dir = os.path.dirname(model_path)
        checkpoint_pattern = os.path.join(model_dir, "ppo_*_steps.zip")
        checkpoint_files = glob.glob(checkpoint_pattern)
        
        if checkpoint_files:
            print(f"\n🧹 Cleaning up {len(checkpoint_files)} checkpoint files...")
            for checkpoint_file in checkpoint_files:
                try:
                    os.remove(checkpoint_file)
                    if verbose := 0:  # Only log if verbose
                        print(f"   Removed: {os.path.basename(checkpoint_file)}")
                except Exception as e:
                    print(f"   ⚠️  Could not remove {os.path.basename(checkpoint_file)}: {e}")
            print(f"✅ Checkpoint cleanup complete")
        
        # Also remove interrupted file if it exists
        interrupted_path = model_path.replace('.zip', '_interrupted.zip')
        if os.path.exists(interrupted_path):
            try:
                os.remove(interrupted_path)
                print(f"🧹 Removed old interrupted file")
            except Exception as e:
                print(f"   ⚠️  Could not remove interrupted file: {e}")
        
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

def test_trained_model(model, num_episodes, training_config_name="default", agent_key=None, rewards_config_name="default", debug_mode=False):
    """Test the trained model."""
    
    W40KEngine, _ = setup_imports()
    # Load scenario and unit registry for testing
    from ai.unit_registry import UnitRegistry
    cfg = get_config_loader()
    scenario_file = os.path.join(cfg.config_dir, "scenario.json")
    unit_registry = UnitRegistry()
    
    env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        debug_mode=debug_mode
    )
    wins = 0
    total_rewards = []
    
    for episode in range(num_episodes):
        obs, info = env.reset()
        episode_reward = 0
        done = False
        step_count = 0
        
        while not done and step_count < 1000:  # Prevent infinite loops
            # Standard PPO doesn't support action masking
            action, _ = model.predict(obs, deterministic=True)
            
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            done = terminated or truncated
            step_count += 1
        
        total_rewards.append(episode_reward)

        # CRITICAL FIX: Learning agent is Player 0, not Player 1!
        if require_key(info, 'winner') == 0:  # AI (Player 0) won
            wins += 1
    
    if num_episodes <= 0:
            raise ValueError("num_episodes must be positive - no default episodes allowed")
    
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

def main():
    """Main training function following AI_INSTRUCTIONS.md exactly."""
    parser = argparse.ArgumentParser(description="Train W40K AI following AI_GAME_OVERVIEW.md specifications")
    parser.add_argument("--training-config", required=True,
                       help="Training configuration to use from config/training_config.json")
    parser.add_argument("--rewards-config", required=True,
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
    parser.add_argument("--total-episodes", type=int, default=None,
                       help="Total episodes for training (overrides config file value)")
    parser.add_argument("--max-concurrent", type=int, default=None,
                       help="Maximum concurrent training sessions")
    parser.add_argument("--training-phase", type=str, choices=["solo", "cross_faction", "full_composition"],
                       help="Specific training phase for 3-phase training plan")
    parser.add_argument("--test-integration", action="store_true",
                       help="Test scenario manager integration")
    parser.add_argument("--step", action="store_true",
                       help="Enable step-by-step action logging to step.log")
    parser.add_argument("--convert-steplog", type=str, metavar="STEPLOG_FILE",
                       help="Convert existing steplog file to replay JSON format")
    parser.add_argument("--replay", action="store_true", 
                       help="Generate steplog AND convert to replay in one command")
    parser.add_argument("--model", type=str, default=None,
                       help="Specific model file to use for replay generation")
    parser.add_argument("--scenario-template", type=str, default=None,
                       help="Scenario template name from scenario_templates.json for replay generation")
    parser.add_argument("--scenario", type=str, default=None,
                       help="Specific scenario to use (e.g., 'phase2-3') or 'all' for rotation through all scenarios")
    parser.add_argument("--macro-eval-mode", type=str, choices=["micro", "bot"], default="micro",
                       help="MacroController evaluation mode: micro (vs trained agents) or bot (vs evaluation bots)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug console output (verbose logging)")
    
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
    print(f"Step logging: {args.step}")
    print(f"Debug mode: {args.debug}")
    if hasattr(args, 'convert_steplog') and args.convert_steplog:
        print(f"Convert steplog: {args.convert_steplog}")
    if hasattr(args, 'replay') and args.replay:
        print(f"Replay generation: {args.replay}")
        if args.model:
            print(f"Model file: {args.model}")
        else:
            print(f"Model file: auto-detect")
    print()
    
    try:
        # Reset debug.log cleared flag at the start of each training run
        # This ensures debug.log is cleared even if the module was already loaded
        from engine.w40k_core import reset_debug_log_flag
        reset_debug_log_flag()
        
        # Setup environment and configuration (before step_logger to read step_log_buffer_size)
        config = get_config_loader()
        if args.step and not args.agent:
            raise ValueError("--step requires --agent to read step_log_buffer_size from agent training config")
        step_log_buffer_size = None
        if args.agent:
            tc = config.load_agent_training_config(args.agent, args.training_config)
            step_log_buffer_size = require_key(tc, "step_log_buffer_size")
        # Initialize global step logger based on --step argument
        global step_logger
        step_logger = StepLogger(os.path.join(project_root, "step.log"), enabled=args.step, buffer_size=step_log_buffer_size, debug_mode=args.debug)
        
        # Sync configs to frontend automatically
        try:
            subprocess.run(['node', 'scripts/copy-configs.js'], 
                         cwd=project_root, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Config sync failed: {e}")
        
        # Ensure scenario exists ONLY for generic training (no agent specified)
        if not args.agent:
            ensure_scenario()
        
        # Convert existing steplog mode
        if args.convert_steplog:
            success = convert_steplog_to_replay(args.convert_steplog)
            return 0 if success else 1

        # Generate steplog AND convert to replay (one-shot mode)
        if args.replay:
            success = generate_steplog_and_replay(config, args)
            return 0 if success else 1

        # Test integration if requested
        if args.test_integration:
            success = test_scenario_manager_integration()
            return 0 if success else 1
        
        # Multi-agent orchestration mode
        if args.orchestrate:
            # Use training config value when total_episodes is not provided
            total_episodes = args.total_episodes
            if total_episodes is None:
                # Orchestration mode requires agent parameter
                if not args.agent:
                    raise ValueError("--agent parameter required when using --orchestrate without --total-episodes")
                training_config = config.load_agent_training_config(args.agent, args.training_config)
                if "total_episodes" not in training_config:
                    raise KeyError(f"total_episodes missing from {args.agent} training config phase {args.training_config}")
                total_episodes = training_config["total_episodes"]
                print(f"📊 Using total_episodes from config: {total_episodes}")
            else:
                print(f"📊 Using total_episodes from command line: {total_episodes}")
                
            results = start_multi_agent_orchestration(
                config=config,
                total_episodes=total_episodes,
                training_config_name=args.training_config,
                rewards_config_name=args.rewards_config,
                max_concurrent=args.max_concurrent,
                training_phase=args.training_phase
            )
            return 0 if results else 1

        # Test-only mode - check BEFORE training
        elif args.test_only:
            if not args.agent:
                raise ValueError("--agent parameter required for --test-only mode")

            if args.agent == "MacroController":
                if args.scenario in ("all", "self", "bot"):
                    raise ValueError("MacroController test-only does not support scenario rotation modes")

                model_path = config.get_model_path()
                model_path = model_path.replace('.zip', f'_{args.agent}.zip')
                if not os.path.exists(model_path):
                    print(f"❌ Model not found: {model_path}")
                    return 1
                model = MaskablePPO.load(model_path)

                training_config = config.load_agent_training_config(args.agent, args.training_config)
                macro_player = require_key(training_config, "macro_player")
                episodes_per_bot = args.test_episodes if args.test_episodes else 50

                if args.macro_eval_mode == "bot":
                    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
                    bots = {
                        "random": RandomBot(),
                        "greedy": GreedyBot(randomness=0.15),
                        "defensive": DefensiveBot(randomness=0.15)
                    }
                    results = {}
                    total_episodes = episodes_per_bot * len(bots)
                    progress_state = {
                        "completed": 0,
                        "total": total_episodes,
                        "start_time": time.time()
                    }
                    print("\n" + "="*80)
                    print("🎯 RUNNING BOT EVALUATION")
                    print(f"Episodes per bot: {episodes_per_bot} (Total: {total_episodes})")
                    print("="*80)
                    for bot_name, bot in bots.items():
                        env = _build_macro_eval_env(
                            config,
                            args.training_config,
                            args.rewards_config,
                            agent_key=args.agent,
                            scenario_override=args.scenario,
                            debug_mode=args.debug,
                            bot=bot
                        )
                        if step_logger and step_logger.enabled:
                            step_logger.current_bot_name = bot_name
                        wins, losses, draws = _evaluate_macro_model(
                            model,
                            env,
                            episodes_per_bot,
                            macro_player,
                            deterministic=True,
                            progress_state=progress_state,
                            label=f"vs {bot_name.capitalize()}Bot [macro]"
                        )
                        results[bot_name] = wins / max(1, (wins + losses + draws))
                        results[f"{bot_name}_wins"] = wins
                        results[f"{bot_name}_losses"] = losses
                        results[f"{bot_name}_draws"] = draws
                    combined = (results["random"] + results["greedy"] + results["defensive"]) / 3
                    results["combined"] = combined
                    sys.stdout.write("\n")

                    print("\n" + "="*80)
                    print("📊 BOT EVALUATION RESULTS")
                    print("="*80)
                    print(f"vs RandomBot:     {results['random']:.2f} (W:{results['random_wins']} L:{results['random_losses']} D:{results['random_draws']})")
                    print(f"vs GreedyBot:     {results['greedy']:.2f} (W:{results['greedy_wins']} L:{results['greedy_losses']} D:{results['greedy_draws']})")
                    print(f"vs DefensiveBot:  {results['defensive']:.2f} (W:{results['defensive_wins']} L:{results['defensive_losses']} D:{results['defensive_draws']})")
                    print(f"\nCombined Score:   {results['combined']:.2f}")
                    print("="*80 + "\n")
                    return 0

                env = _build_macro_eval_env(
                    config,
                    args.training_config,
                    args.rewards_config,
                    agent_key=args.agent,
                    scenario_override=args.scenario,
                    debug_mode=args.debug,
                    bot=None
                )
                progress_state = {
                    "completed": 0,
                    "total": episodes_per_bot,
                    "start_time": time.time()
                }
                wins, losses, draws = _evaluate_macro_model(
                    model,
                    env,
                    episodes_per_bot,
                    macro_player,
                    deterministic=True,
                    progress_state=progress_state,
                    label="macro-vs-micro"
                )
                sys.stdout.write("\n")
                print("\n" + "="*80)
                print("📊 MACRO vs MICRO RESULTS")
                print("="*80)
                total = wins + losses + draws
                print(f"W:{wins} L:{losses} D:{draws} (Total: {total})")
                print("="*80 + "\n")
                return 0
            
            # Load existing model
            model_path = config.get_model_path()
            model_path = model_path.replace('.zip', f'_{args.agent}.zip')
            
            if not os.path.exists(model_path):
                print(f"❌ Model not found: {model_path}")
                return 1
            
            print(f"📁 Loading model: {model_path}")
            
            # Create minimal environment for model loading
            W40KEngine, _ = setup_imports()
            from ai.unit_registry import UnitRegistry
            cfg = get_config_loader()
            unit_registry = UnitRegistry()

            # Handle --scenario bot flag for test-only mode
            if args.scenario == "bot":
                # Use bot scenarios - get first one from the list
                scenario_list = get_scenario_list_for_phase(cfg, args.agent, "bot")
                if not scenario_list:
                    raise FileNotFoundError(f"No bot scenarios found for agent '{args.agent}'")
                scenario_file = scenario_list[0]
                print(f"📋 Using bot scenario: {os.path.basename(scenario_file)}")
            else:
                scenario_file = get_agent_scenario_file(cfg, args.agent, args.training_config)
            
            # CRITICAL FIX: Use rewards_config for controlled_agent (includes phase suffix)
            effective_agent_key = args.rewards_config if args.rewards_config else args.agent

            base_env = W40KEngine(
                rewards_config=args.rewards_config,
                training_config_name=args.training_config,
                controlled_agent=effective_agent_key,
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=True,
                gym_training_mode=True,
                debug_mode=args.debug
            )
            
            def mask_fn(env):
                return env.get_action_mask()
            
            from sb3_contrib.common.wrappers import ActionMasker
            masked_env = ActionMasker(base_env, mask_fn)
            
            # Load model
            try:
                model = MaskablePPO.load(model_path, env=masked_env)
            except ValueError as e:
                error_msg = str(e)
                if "Observation spaces do not match" in error_msg:
                    print(f"❌ Model incompatible: {error_msg}")
                    print(f"⚠️  The model was trained with a different observation space size.")
                    print(f"💡 Solution: Re-train the model with --new-model flag:")
                    print(f"   python ai/train.py --agent {args.agent} --training-config {args.training_config} --rewards-config {args.rewards_config} --scenario bot --new-model")
                    return 1
                else:
                    raise
            
            # Run bot evaluation ONLY
            # Use test_episodes if provided, otherwise default to 50 per bot
            episodes_per_bot = args.test_episodes if args.test_episodes else 50
            
            print("\n" + "="*80)
            print("🎯 RUNNING BOT EVALUATION")
            print(f"Episodes per bot: {episodes_per_bot} (Total: {episodes_per_bot * 3})")
            print("="*80)
            
            results = evaluate_against_bots(
                model=model,
                training_config_name=args.training_config,
                rewards_config_name=args.rewards_config,
                debug_mode=args.debug,
                n_episodes=episodes_per_bot,
                controlled_agent=effective_agent_key,
                show_progress=True,
                deterministic=True,
                step_logger=step_logger
            )
            
            # Display results
            print("\n" + "="*80)
            print("📊 BOT EVALUATION RESULTS")
            print("="*80)
            print(f"vs RandomBot:     {results['random']:.2f} (W:{results['random_wins']} L:{results['random_losses']} D:{results['random_draws']})")
            print(f"vs GreedyBot:     {results['greedy']:.2f} (W:{results['greedy_wins']} L:{results['greedy_losses']} D:{results['greedy_draws']})")
            print(f"vs DefensiveBot:  {results['defensive']:.2f} (W:{results['defensive_wins']} L:{results['defensive_losses']} D:{results['defensive_draws']})")
            print(f"\nCombined Score:   {results['combined']:.2f}")
            print("="*80 + "\n")
            
            masked_env.close()
            return 0

        # Single agent training mode
        elif args.agent:
            if args.agent == "MacroController":
                if args.scenario in ("all", "self", "bot"):
                    raise ValueError("MacroController training does not support scenario rotation modes")

                model, env, training_config, model_path = create_macro_controller_model(
                    config,
                    args.training_config,
                    args.rewards_config,
                    agent_key=args.agent,
                    new_model=args.new,
                    append_training=args.append,
                    scenario_override=args.scenario,
                    debug_mode=args.debug
                )

                callbacks = setup_callbacks(
                    config, model_path, training_config, args.training_config,
                    agent=args.agent, rewards_config_name=args.rewards_config
                )

                success = train_model(
                    model,
                    training_config,
                    callbacks,
                    model_path,
                    args.training_config,
                    args.rewards_config,
                    controlled_agent=args.rewards_config
                )

                if success:
                    if args.test_episodes > 0:
                        test_trained_model(model, args.test_episodes, args.training_config, debug_mode=args.debug)
                    else:
                        print("📊 Skipping testing (--test-episodes 0)")
                    return 0
                return 1

            # Check if scenario rotation is requested
            if args.scenario == "all" or args.scenario == "self" or args.scenario == "bot":
                # Get list of scenarios based on type
                if args.scenario == "self" or args.scenario == "all":
                    # "all" and "self" both mean: use self-play scenarios
                    scenario_list = get_scenario_list_for_phase(config, args.agent, args.training_config, scenario_type="self")
                    scenario_type_name = "self-play"
                else:  # args.scenario == "bot"
                    scenario_list = get_scenario_list_for_phase(config, args.agent, args.training_config, scenario_type="bot")
                    scenario_type_name = "bot"

                # NO FALLBACKS - if no scenarios found, ERROR
                if len(scenario_list) == 0:
                    raise FileNotFoundError(
                        f"No {scenario_type_name} scenarios found. "
                        f"Expected files matching: {args.agent}_scenario_{'self' if scenario_type_name == 'self-play' else 'bot'}*.json"
                    )

                print(f"📋 Found {len(scenario_list)} {scenario_type_name} scenario(s):")
                for s in scenario_list:
                    print(f"   - {os.path.basename(s)}")

                if len(scenario_list) == 1:
                    # Single scenario - use it directly without rotation
                    # Extract scenario name from path for override
                    scenario_name = os.path.basename(scenario_list[0]).replace(f"{args.agent}_scenario_", "").replace(".json", "")
                    args.scenario = scenario_name  # Set specific scenario to use
                else:
                    # Load agent-specific training config to get total episodes
                    training_config = config.load_agent_training_config(args.agent, args.training_config)
                    if "total_episodes" not in training_config:
                        raise KeyError(f"total_episodes missing from {args.agent} training config phase {args.training_config}")
                    # CLI argument takes priority over config
                    if args.total_episodes is not None:
                        total_episodes = args.total_episodes
                        print(f"📊 Using total_episodes from CLI: {total_episodes}")
                    else:
                        total_episodes = training_config["total_episodes"]
                    
                    # Use multi-scenario training with random selection per episode
                    success, model, env = train_with_scenario_rotation(
                        config=config,
                        agent_key=args.agent,
                        training_config_name=args.training_config,
                        rewards_config_name=args.rewards_config,
                        scenario_list=scenario_list,
                        total_episodes=total_episodes,
                        new_model=args.new,
                        append_training=args.append,
                        debug_mode=args.debug,
                        use_bots=(args.scenario == "bot")
                    )
                    
                    if success and args.test_episodes > 0:
                        test_trained_model(model, args.test_episodes, args.training_config, args.agent, args.rewards_config, debug_mode=args.debug)
                    
                    return 0 if success else 1
            
            # Standard single-scenario training (no rotation)
            model, env, training_config, model_path = create_multi_agent_model(
                config,
                args.training_config,
                args.rewards_config,
                agent_key=args.agent,
                new_model=args.new,
                append_training=args.append,
                scenario_override=args.scenario,
                debug_mode=args.debug
            )
            
            # Setup callbacks with agent-specific model path
            callbacks = setup_callbacks(config, model_path, training_config, args.training_config,
                                      agent=args.agent, rewards_config_name=args.rewards_config)
            
            # Train model
            # CRITICAL: Use rewards_config for controlled_agent (includes phase suffix like "_phase1")
            success = train_model(model, training_config, callbacks, model_path, args.training_config, args.rewards_config, controlled_agent=args.rewards_config)
            
            if success:
                # Only test if episodes > 0
                if args.test_episodes > 0:
                    test_trained_model(model, args.test_episodes, args.training_config, debug_mode=args.debug)
                else:
                    print("📊 Skipping testing (--test-episodes 0)")
                return 0
            else:
                return 1
        
        else:
            # Generic training mode
            # Create/load model
            model, env, training_config, model_path = create_model(
            config, 
            args.training_config,
            args.rewards_config, 
            args.new, 
            args.append,
            args
        )
        
        # Setup callbacks
        callbacks = setup_callbacks(config, model_path, training_config, args.training_config)
        
        # Train model
        success = train_model(model, training_config, callbacks, model_path, args.training_config, args.rewards_config, controlled_agent=args.agent)
        
        if success:
            # Only test if episodes > 0
            if args.test_episodes > 0:
                test_trained_model(model, args.test_episodes, args.training_config, args.agent, args.rewards_config, debug_mode=args.debug)
                
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
            else:
                print("📊 Skipping testing (--test-episodes 0)")
            
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