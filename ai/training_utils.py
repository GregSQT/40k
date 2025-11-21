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
                     unit_registry, controlled_agent=None, enable_action_masking=True):
    """
    Create training environment with proper configuration.

    Args:
        rank: Environment rank (for vectorized environments)
        scenario_file: Path to scenario JSON file
        rewards_config_name: Name of rewards configuration
        training_config_name: Name of training configuration
        unit_registry: UnitRegistry instance
        controlled_agent: Agent being controlled (None=Player 0, str=Player 1)
        enable_action_masking: Whether to enable action masking

    Returns:
        Callable that creates the environment
    """
    def _init():
        # Import here to avoid circular dependencies
        from config_loader import get_config_loader
        from ai.w40k_engine import W40KEngine

        config = get_config_loader()

        # Create base engine
        env = W40KEngine(
            scenario_file=scenario_file,
            rewards_config_name=rewards_config_name,
            unit_registry=unit_registry,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent
        )

        # Wrap in Monitor for statistics tracking
        env = Monitor(env)

        # Add action masking if enabled
        if enable_action_masking:
            def action_mask_fn(env_instance):
                return env_instance.get_action_mask()
            env = ActionMasker(env, action_mask_fn)

        return env

    return _init

def get_scenario_list_for_phase(config, agent_key, training_config_name, scenario_type=None):
    """
    Get all available scenarios for a training phase.

    Args:
        config: ConfigLoader instance
        agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
        training_config_name: Phase name (e.g., 'phase1', 'phase2')
        scenario_type: Optional filter for specific scenario type (e.g., '1', '2', '3')

    Returns:
        List of scenario file paths
    """
    scenarios = []

    if not agent_key:
        return scenarios

    scenarios_dir = os.path.join(config.config_dir, "agents", agent_key, "scenarios")
    if not os.path.isdir(scenarios_dir):
        return scenarios

    # Pattern: AgentName_scenario_phase1.json OR AgentName_scenario_phase1-1.json
    # For phase1: Find phase1.json, phase1-1.json, phase1-2.json, etc.
    pattern = f"{agent_key}_scenario_{training_config_name}*.json"
    matching_files = glob.glob(os.path.join(scenarios_dir, pattern))

    # Filter by scenario type if specified
    if scenario_type:
        # scenario_type like "1" matches "phase1-1", "2" matches "phase1-2", etc.
        filtered = []
        for f in matching_files:
            basename = os.path.basename(f)
            # Extract scenario suffix: phase1-1 → "1", phase1-2 → "2", phase1 → None
            if f"-{scenario_type}.json" in basename:
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

def calculate_rotation_interval(total_episodes, num_scenarios, config_value=None):
    """
    Calculate scenario rotation interval for curriculum learning.

    Args:
        total_episodes: Total episodes for this training phase
        num_scenarios: Number of scenarios available
        config_value: Optional config override (if None, uses auto-calculation)

    Returns:
        int: Episodes per scenario rotation
    """
    if config_value is not None:
        return config_value

    # Auto-calculate: Aim for ~5-10 rotations through all scenarios
    target_rotations = 7
    return max(1, total_episodes // (num_scenarios * target_rotations))

def ensure_scenario():
    pass
