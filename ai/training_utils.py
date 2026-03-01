#!/usr/bin/env python3
"""
ai/training_utils.py - Training utility functions

Contains:
- check_gpu_availability: Check and display GPU availability
- setup_imports: Setup system path imports for project
- make_training_env: Create training environment with proper configuration
- get_agent_scenario_file: Get scenario file path for agent-specific training
- get_scenario_list_for_phase: Get all available scenarios for a training phase
- ensure_scenario: Ensure scenario file exists for agent

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import sys
import glob
import time
import torch
import torch.nn as nn
import gymnasium as gym
from typing import Optional, List, Tuple
from stable_baselines3.common.monitor import Monitor
from sb3_contrib.common.wrappers import ActionMasker
from ai.env_wrappers import SelfPlayWrapper, BotControlledEnv

__all__ = [
    'check_gpu_availability',
    'benchmark_device_speed',
    'setup_imports',
    'make_training_env',
    'make_macro_training_env',
    'get_agent_scenario_file',
    'get_scenario_list_for_phase',
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


def benchmark_device_speed(obs_size: int, net_arch: List[int], batch_size: int = 2048,
                           n_warmup: int = 5, n_iters: int = 30) -> Optional[Tuple[str, bool]]:
    """
    Run a quick benchmark to determine whether CPU or GPU is faster for the given
    network architecture. Simulates PPO forward pass with typical batch size.

    Args:
        obs_size: Observation space dimension.
        net_arch: List of hidden layer sizes (e.g. [512, 512]).
        batch_size: Batch size for benchmark (typical PPO batch).
        n_warmup: Warmup iterations to avoid CUDA init skew.
        n_iters: Iterations to average for timing.

    Returns:
        ("cuda", True) or ("cpu", False) if benchmark succeeds, None on failure.
    """
    if not torch.cuda.is_available():
        return ("cpu", False)

    arch = net_arch if isinstance(net_arch, list) else [512]
    layers = []
    prev = obs_size
    for h in arch:
        layers.append(nn.Linear(prev, h))
        layers.append(nn.ReLU())
        prev = h
    layers.append(nn.Linear(prev, 64))  # action head
    net = nn.Sequential(*layers)

    def run_on_device(device: str) -> float:
        d = torch.device(device)
        m = net.to(d)
        x = torch.randn(batch_size, obs_size, device=d)
        for _ in range(n_warmup):
            _ = m(x)
        if d.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n_iters):
            _ = m(x)
        if d.type == "cuda":
            torch.cuda.synchronize()
        return time.perf_counter() - t0

    try:
        t_cpu = run_on_device("cpu")
        t_gpu = run_on_device("cuda")
        use_gpu = t_gpu < t_cpu
        winner = "GPU" if use_gpu else "CPU"
        ratio = (t_cpu / t_gpu) if use_gpu else (t_gpu / t_cpu)
        print(f"📊 Device benchmark: {winner} faster ({ratio:.1f}x) | CPU={t_cpu*1000:.0f}ms GPU={t_gpu*1000:.0f}ms")
        return ("cuda", True) if use_gpu else ("cpu", False)
    except Exception as e:
        print(f"⚠️ Device benchmark failed ({e}), falling back to heuristic")
        return None


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
        raise ImportError(f"w40k_engine import failed: {e}")

def make_training_env(rank, scenario_file, rewards_config_name, training_config_name,
                     controlled_agent_key, unit_registry, step_logger_enabled=False,
                     scenario_files=None, debug_mode=False, use_bots=False, training_bots=None):
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
        debug_mode: Enable debug mode
        use_bots: If True, wrap with BotControlledEnv instead of SelfPlayWrapper
        training_bots: List of bot instances for BotControlledEnv (required if use_bots=True)

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
            gym_training_mode=True,
            debug_mode=debug_mode
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

        # Bot training or self-play
        if use_bots and training_bots:
            wrapped_env = BotControlledEnv(masked_env, bots=training_bots, unit_registry=unit_registry)
        else:
            wrapped_env = SelfPlayWrapper(masked_env, frozen_model=None, update_frequency=100)

        # Wrap with Monitor for episode statistics
        return Monitor(wrapped_env)
    
    return _init


def make_macro_training_env(
    rank,
    scenario_file,
    rewards_config_name,
    training_config_name,
    controlled_agent_key,
    model_path_template,
    macro_player,
    macro_max_units,
    scenario_files,
    debug_mode=False
):
    """
    Factory function to create one MacroTrainingWrapper instance for vectorized training.

    Args:
        rank: Environment index (0, 1, 2, ...)
        scenario_file: Primary scenario JSON path
        rewards_config_name: Name of rewards configuration
        training_config_name: Name of training configuration
        controlled_agent_key: Agent key used by W40KEngine
        model_path_template: Template path to micro models with {model_key}
        macro_player: Controlled macro player id (1 or 2)
        macro_max_units: Fixed macro capacity for unit slots (strict upper bound)
        scenario_files: Scenario files used by macro wrapper
        debug_mode: Enable debug mode

    Returns:
        Callable that creates and returns a wrapped macro environment instance
    """
    def _init():
        from engine.w40k_core import W40KEngine
        from ai.unit_registry import UnitRegistry
        from ai.macro_training_env import MacroTrainingWrapper

        unit_registry = UnitRegistry()
        base_env = W40KEngine(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=controlled_agent_key,
            active_agents=None,
            scenario_file=scenario_file,
            scenario_files=scenario_files,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            debug_mode=debug_mode
        )
        base_env.step_logger = None

        macro_env = MacroTrainingWrapper(
            base_env=base_env,
            unit_registry=unit_registry,
            scenario_files=scenario_files,
            model_path_template=model_path_template,
            macro_player=macro_player,
            macro_max_units=macro_max_units,
            debug_mode=debug_mode
        )

        def mask_fn(env):
            return env.get_action_mask()

        masked_env = ActionMasker(macro_env, mask_fn)
        return Monitor(masked_env)

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
    scenarios: List[str] = []
    if not agent_key:
        return scenarios

    scenarios_root = os.path.join(config.config_dir, "agents", agent_key, "scenarios")
    if not os.path.isdir(scenarios_root):
        return scenarios

    training_dir = os.path.join(scenarios_root, "training")
    holdout_dir = os.path.join(scenarios_root, "holdout")
    has_training_dir = os.path.isdir(training_dir)
    has_holdout_dir = os.path.isdir(holdout_dir)

    if scenario_type == "holdout":
        search_dirs = [holdout_dir] if has_holdout_dir else []
    elif scenario_type == "training":
        search_dirs = [training_dir] if has_training_dir else []
    else:
        # Default training behavior:
        # - if training/ exists, use it exclusively (prevents holdout leakage)
        # - otherwise, keep legacy root behavior.
        search_dirs = [training_dir] if has_training_dir else [scenarios_root]

    for search_dir in search_dirs:
        if scenario_type in ("bot", "self"):
            patterns = [
                f"{agent_key}_{scenario_type}*.json",
                f"{agent_key}_*_{scenario_type}*.json",
            ]
        else:
            patterns = [
                f"{agent_key}_{training_config_name}.json",
                f"{agent_key}_{training_config_name}-*.json",
            ]

        matches: List[str] = []
        for pattern in patterns:
            matches.extend(glob.glob(os.path.join(search_dir, pattern)))

        # If no phase-specific match exists in this directory, accept all agent files.
        if not matches:
            matches = glob.glob(os.path.join(search_dir, f"{agent_key}_*.json"))

        scenarios.extend(matches)

    # Filter by explicit subtype marker (e.g. "1", "2", "bot-1"), if provided.
    if scenario_type and scenario_type not in ("bot", "self", "training", "holdout"):
        filtered: List[str] = []
        for scenario_path in scenarios:
            basename = os.path.basename(scenario_path)
            if f"-{scenario_type}" in basename:
                filtered.append(scenario_path)
        scenarios = filtered

    # Deduplicate + deterministic ordering
    return sorted(set(scenarios))

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
    scenarios_root = os.path.join(config.config_dir, "agents", agent_key, "scenarios")
    training_dir = os.path.join(scenarios_root, "training")
    has_training_dir = os.path.isdir(training_dir)

    # Search order for training:
    # - prefer training/ when it exists
    # - keep root as backward-compatible fallback source
    search_dirs = [training_dir, scenarios_root] if has_training_dir else [scenarios_root]

    # If specific scenario requested, try to find it
    if scenario_override and scenario_override != "all":
        if agent_key:
            # Agent-specific scenario with explicit override
            explicit_candidates: List[str] = []
            for search_dir in search_dirs:
                explicit_candidates.append(os.path.join(
                    search_dir,
                    f"{agent_key}_{scenario_override}.json"
                ))
                explicit_candidates.append(os.path.join(
                    search_dir,
                    f"{agent_key}_{training_config_name}-{scenario_override}.json"
                ))

            found_explicit = [p for p in explicit_candidates if os.path.isfile(p)]
            if len(found_explicit) == 1:
                return found_explicit[0]
            elif len(found_explicit) > 1:
                raise FileNotFoundError(
                    f"Ambiguous scenario_override '{scenario_override}' for agent '{agent_key}' "
                    f"and phase '{training_config_name}'. Candidates: {found_explicit}. "
                    f"Please specify an exact scenario file name."
                )

    # Try agent-specific scenario first (single, unambiguous file)
    if agent_key:
        exact_candidates: List[str] = []
        for search_dir in search_dirs:
            exact_candidates.append(os.path.join(search_dir, f"{agent_key}_{training_config_name}.json"))
        exact_matches = sorted([p for p in exact_candidates if os.path.isfile(p)])
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            raise FileNotFoundError(
                f"Ambiguous exact scenario for agent '{agent_key}' and phase '{training_config_name}': "
                f"{exact_matches}. Please keep only one exact phase scenario."
            )

        # Try variants for this phase (phase1-bot1, phase2-1, etc.).
        matching_files: List[str] = []
        for search_dir in search_dirs:
            matching_files.extend(sorted(glob.glob(
                os.path.join(search_dir, f"{agent_key}_{training_config_name}-*.json")
            )))
        matching_files = sorted(set(matching_files))

        if len(matching_files) == 1:
            return matching_files[0]
        elif len(matching_files) > 1:
            variant_names = [os.path.basename(f) for f in matching_files]
            raise FileNotFoundError(
                f"Multiple scenario variants found for agent '{agent_key}' and phase '{training_config_name}': "
                f"{variant_names}. You must specify --scenario with an explicit variant name."
            )

    # No valid scenario found
    raise FileNotFoundError(
        f"No scenario file found for agent '{agent_key}' with phase '{training_config_name}'. "
        f"Tried training-first lookup with naming convention "
        f"'{agent_key}_{training_config_name}.json' "
        f"plus phase variants."
    )


def ensure_scenario():
    """Ensure scenario.json exists."""
    # Get project root (parent of ai/ directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    scenario_path = os.path.join(project_root, "config", "scenario.json")
    if not os.path.exists(scenario_path):
        raise FileNotFoundError(f"Missing required scenario.json file: {scenario_path}. AI_INSTRUCTIONS.md: No fallbacks allowed - scenario file must exist.")
