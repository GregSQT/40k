#!/usr/bin/env python3
"""
ai/training_utils.py - Training utility functions

Contains:
- check_gpu_availability: Check and display GPU availability
- setup_imports: Setup system path imports for project
- make_training_env: Create training environment with proper configuration
- get_agent_scenario_file: Get scenario file path for agent-specific training
- get_scenario_list_for_phase: Get all available scenarios for a training phase
- calculate_rotation_interval: Calculate scenario rotation interval
- ensure_scenario: Ensure scenario file exists for agent

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import sys
import glob
import torch
import gymnasium as gym
from typing import Optional, List
from stable_baselines3.common.monitor import Monitor
from sb3_contrib.common.wrappers import ActionMasker
from ai.env_wrappers import SelfPlayWrapper

__all__ = [
    'check_gpu_availability',
    'setup_imports',
    'make_training_env',
    'get_agent_scenario_file',
    'get_scenario_list_for_phase',
    'calculate_rotation_interval',
    'ensure_scenario'
]


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
    """
    Setup import paths and return required modules.
    Returns W40KEngine and register_environment function.
    """
    try:
        # AI_TURN.md COMPLIANCE: Use compliant engine with gym interface
        from engine.w40k_core import W40KEngine

        # Compatibility function for training system
        def register_environment():
            """No registration needed for direct engine usage"""
            pass

        return W40KEngine, register_environment
    except ImportError as e:
        raise ImportError(f"AI_TURN.md: w40k_engine import failed: {e}")

def make_training_env(rank, scenario_file, rewards_config_name, training_config_name,
                     controlled_agent_key, unit_registry, step_logger_enabled=False,
                     scenario_files=None):
    """
    Factory function to create a single W40KEngine instance for vectorization.

    Args:
        rank: Environment index (0, 1, 2, 3, ...)
        scenario_file: Path to scenario JSON file (used if scenario_files not provided)
        rewards_config_name: Name of rewards configuration
        training_config_name: Name of training configuration
        controlled_agent_key: Agent key for this environment
        unit_registry: Shared UnitRegistry instance
        step_logger_enabled: Whether step logging is enabled (disable for vectorized envs)
        scenario_files: List of scenario files for random selection per episode

    Returns:
        Callable that creates and returns a wrapped environment instance
    """
    def _init():
        # Import environment (inside function to avoid import issues)
        from engine.w40k_core import W40KEngine

        # Create base environment with scenario_files for random selection
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent_key,
            active_agents=None,
            scenario_file=scenario_file,
            scenario_files=scenario_files,  # NEW: Pass list for random selection
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True
        )
        
        # ✓ CHANGE 9: Removed seed() call - W40KEngine uses reset(seed=...) instead
        # Seeding will happen naturally during first reset() call
        
        # Disable step logger for parallel envs to avoid file conflicts
        if not step_logger_enabled:
            base_env.step_logger = None  # ✓ CHANGE 2: Prevent log conflicts
        
        # Wrap with ActionMasker for MaskablePPO
        def mask_fn(env):
            return env.get_action_mask()
        
        masked_env = ActionMasker(base_env, mask_fn)

        # CRITICAL: Wrap with SelfPlayWrapper for proper self-play training
        selfplay_env = SelfPlayWrapper(masked_env, frozen_model=None, update_frequency=100)

        # Wrap with Monitor for episode statistics
        return Monitor(selfplay_env)
    
    return _init


def get_scenario_list_for_phase(config, agent_key, training_config_name, scenario_type=None):
    """
    Get all available scenarios for a training phase.

    Args:
        config: ConfigLoader instance
        agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
        training_config_name: Phase name (e.g., 'phase1', 'phase2')
        scenario_type: Optional filter for specific scenario type (e.g., 'bot', 'self', '1')

    Returns:
        List of scenario file paths
    """
    scenarios = []

    if not agent_key:
        return scenarios

    scenarios_dir = os.path.join(config.config_dir, "agents", agent_key, "scenarios")
    if not os.path.isdir(scenarios_dir):
        return scenarios

    # For "bot" and "self" scenario types, search independently of training config
    # This allows: AgentName_scenario_bot1.json, AgentName_scenario_bot2.json, etc.
    if scenario_type in ("bot", "self"):
        # Pattern: AgentName_scenario_bot*.json (independent of training config)
        pattern = f"{agent_key}_scenario_{scenario_type}*.json"
        matching_files = glob.glob(os.path.join(scenarios_dir, pattern))
        scenarios = matching_files
    else:
        # Original behavior: Pattern includes training config
        # AgentName_scenario_phase1.json OR AgentName_scenario_phase1-1.json
        pattern = f"{agent_key}_scenario_{training_config_name}*.json"
        matching_files = glob.glob(os.path.join(scenarios_dir, pattern))

        # Filter by scenario type if specified (for numbered scenarios like "1", "2")
        if scenario_type:
            filtered = []
            for f in matching_files:
                basename = os.path.basename(f)
                if f"-{scenario_type}" in basename:
                    filtered.append(f)
            scenarios = filtered
        else:
            scenarios = matching_files

    # Sort to ensure deterministic order
    scenarios = sorted(scenarios)

    return scenarios

def get_agent_scenario_file(config, agent_key, training_config_name, scenario_override=None):
    """Get scenario file path for agent-specific training.

    Args:
        config: ConfigLoader instance
        agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
        training_config_name: Phase name (e.g., 'phase1', 'phase2')
        scenario_override: Optional specific scenario name (e.g., 'phase2-3')

    Returns:
        Path to scenario file

    Raises:
        FileNotFoundError: If no valid scenario file found
    """
    # If specific scenario requested, try to find it
    if scenario_override and scenario_override != "all":
        if agent_key:
            # Agent-specific scenario
            scenario_path = os.path.join(
                config.config_dir, "agents", agent_key, "scenarios",
                f"{agent_key}_scenario_{scenario_override}.json"
            )
            if os.path.isfile(scenario_path):
                return scenario_path

            # Try without agent prefix (e.g., user passed "phase2-3" instead of full name)
            scenario_path = os.path.join(
                config.config_dir, "agents", agent_key, "scenarios",
                f"{agent_key}_scenario_{training_config_name}-{scenario_override}.json"
            )
            if os.path.isfile(scenario_path):
                return scenario_path

    # Try agent-specific scenario first
    if agent_key:
        agent_scenario_path = os.path.join(
            config.config_dir, "agents", agent_key, "scenarios",
            f"{agent_key}_scenario_{training_config_name}.json"
        )
        if os.path.isfile(agent_scenario_path):
            return agent_scenario_path

        # Try variants for any phase (phase1-bot1, phase1-self1, phase2-1, etc.)
        # Use glob to find any file matching the pattern
        scenarios_dir = os.path.join(config.config_dir, "agents", agent_key, "scenarios")
        pattern = os.path.join(scenarios_dir, f"{agent_key}_scenario_{training_config_name}-*.json")
        matching_files = sorted(glob.glob(pattern))
        if matching_files:
            variant_name = os.path.basename(matching_files[0]).replace(f"{agent_key}_scenario_", "").replace(".json", "")
            print(f"ℹ️  {training_config_name} has multiple scenarios. Using first variant: {variant_name}")
            return matching_files[0]

    # Fall back to default scenarios
    fallback_path = os.path.join(
        config.config_dir, "scenarios", f"scenario_{training_config_name}.json"
    )
    if os.path.isfile(fallback_path):
        return fallback_path

    # No valid scenario found
    raise FileNotFoundError(
        f"No scenario file found for agent '{agent_key}' with phase '{training_config_name}'. "
        f"Tried: agent-specific and fallback scenarios."
    )

def calculate_rotation_interval(total_episodes, num_scenarios, config_value=None, n_steps=256):
    """
    Calculate scenario rotation interval for curriculum learning.

    Args:
        total_episodes: Total episodes for this training phase
        num_scenarios: Number of scenarios available
        config_value: Optional config override (if None, uses auto-calculation)
        n_steps: PPO n_steps parameter (needed to ensure training updates happen)

    Returns:
        int: Episodes per scenario rotation
    """
    if config_value is not None:
        return config_value

    # CRITICAL: Rotation interval must allow at least one PPO update cycle
    # PPO requires n_steps before doing a training update
    # Each episode is ~50-75 steps, so we need ceil(n_steps/50) episodes minimum
    avg_episode_steps = 50  # Conservative estimate
    min_episodes_for_update = max(1, (n_steps + avg_episode_steps - 1) // avg_episode_steps)

    # Auto-calculate: Aim for ~5-10 rotations through all scenarios
    target_rotations = 7
    ideal_interval = max(1, total_episodes // (num_scenarios * target_rotations))

    # Use the larger of ideal and minimum for PPO updates
    return max(ideal_interval, min_episodes_for_update)

def ensure_scenario():
    """Ensure scenario.json exists."""
    # Get project root (parent of ai/ directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    scenario_path = os.path.join(project_root, "config", "scenario.json")
    if not os.path.exists(scenario_path):
        raise FileNotFoundError(f"Missing required scenario.json file: {scenario_path}. AI_INSTRUCTIONS.md: No fallbacks allowed - scenario file must exist.")
