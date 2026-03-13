#!/usr/bin/env python3
"""
ai/bot_evaluation.py - Bot evaluation functionality

Contains:
- evaluate_against_bots: Standalone bot evaluation function for all bot testing

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import hashlib
import logging
import multiprocessing as mp
import os
import sys
import numpy as np
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable, Optional, Dict, List, Any, Tuple

from shared.data_validation import require_key

__all__ = ['evaluate_against_bots']

# Worker globals (scope processus)
_worker_model = None
_worker_obs_normalizer = None


def _build_eval_obs_normalizer(
    model,
    vec_normalize_enabled: bool,
    vec_model_path: Optional[str],
) -> Optional[Callable[[np.ndarray], np.ndarray]]:
    """
    Build observation normalizer for bot evaluation.

    When VecNormalize is enabled in training config, evaluation must apply the same
    observation normalization to avoid train/eval distribution mismatch.
    """
    if not vec_normalize_enabled:
        return None

    train_env = model.get_env() if hasattr(model, "get_env") else None
    if train_env is not None:
        from stable_baselines3.common.vec_env import VecNormalize

        env_cursor = train_env
        while env_cursor is not None:
            if isinstance(env_cursor, VecNormalize):
                vec_env = env_cursor

                def _normalize_with_live_vec(obs: np.ndarray) -> np.ndarray:
                    obs_arr = np.asarray(obs, dtype=np.float32)
                    if obs_arr.ndim == 1:
                        obs_arr = obs_arr.reshape(1, -1)
                    normalized = vec_env.normalize_obs(obs_arr)
                    return np.asarray(normalized, dtype=np.float32).squeeze()

                return _normalize_with_live_vec
            env_cursor = getattr(env_cursor, "venv", None)

    if vec_model_path:
        from ai.vec_normalize_utils import normalize_observation_for_inference

        def _normalize_with_saved_stats(obs: np.ndarray) -> np.ndarray:
            obs_arr = np.asarray(obs, dtype=np.float32)
            normalized = normalize_observation_for_inference(obs_arr, vec_model_path)
            return np.asarray(normalized, dtype=np.float32)

        return _normalize_with_saved_stats

    raise RuntimeError(
        "VecNormalize is enabled for this agent, but bot evaluation could not access "
        "VecNormalize stats from model env or saved model path."
    )


def _load_bot_eval_params(config_loader, agent_key: str, training_config_name: str):
    """Load bot evaluation weights and randomness from agent training config."""
    if not agent_key:
        raise ValueError("controlled_agent is required to load bot evaluation parameters from agent config")

    training_cfg = config_loader.load_agent_training_config(agent_key, training_config_name)
    callback_params = require_key(training_cfg, "callback_params")

    bot_eval_weights = require_key(callback_params, "bot_eval_weights")
    random_weight = float(require_key(bot_eval_weights, "random"))
    greedy_weight = float(require_key(bot_eval_weights, "greedy"))
    defensive_weight = float(require_key(bot_eval_weights, "defensive"))
    total_weight = random_weight + greedy_weight + defensive_weight
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(
            "callback_params.bot_eval_weights must sum to 1.0 "
            f"(got random={random_weight}, greedy={greedy_weight}, defensive={defensive_weight}, total={total_weight})"
        )

    bot_eval_randomness = require_key(callback_params, "bot_eval_randomness")
    greedy_randomness = float(require_key(bot_eval_randomness, "greedy"))
    defensive_randomness = float(require_key(bot_eval_randomness, "defensive"))

    return {
        "weights": {
            "random": random_weight,
            "greedy": greedy_weight,
            "defensive": defensive_weight,
        },
        "randomness": {
            "greedy": greedy_randomness,
            "defensive": defensive_randomness,
        },
    }


def _scenario_name_from_file(base_agent_key: str, scenario_file: str) -> str:
    """Build short scenario name used in logs/results."""
    basename = os.path.basename(scenario_file).replace(".json", "")
    parent_dir = os.path.basename(os.path.dirname(scenario_file))
    name = basename
    if base_agent_key:
        agent_prefix = f"{base_agent_key}_"
        if name.startswith(agent_prefix):
            name = name[len(agent_prefix):]
    if name.startswith("scenario_"):
        name = name[len("scenario_"):]
    bot_match = re.fullmatch(r"bot-(\d+)", name)
    if bot_match and parent_dir in {"holdout_regular", "holdout_hard"}:
        return f"{parent_dir}_bot-{bot_match.group(1)}"
    return name


def _scenario_metric_slug(scenario_name: str) -> str:
    """Convert scenario label to TensorBoard-safe metric suffix."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", scenario_name.strip()).strip("_").lower()
    if not normalized:
        raise ValueError(f"Invalid scenario name for metric slug: '{scenario_name}'")
    return normalized


def _scenario_split_metric_key(scenario_name: str) -> Optional[str]:
    """
    Convert scenario name to split metric key.

    Supported names:
      - training_bot-<n>        -> training_bot_<n>
      - holdout_hard_bot-<n>    -> hard_bot_<n>
      - holdout_regular_bot-<n> -> regular_bot_<n>
    """
    name = scenario_name.strip()
    if name.startswith("scenario_"):
        name = name[len("scenario_"):]
    training_match = re.fullmatch(r"training_bot-(\d+)", name)
    if training_match:
        return f"training_bot_{training_match.group(1)}"

    hard_match = re.fullmatch(r"holdout_hard_bot-(\d+)", name)
    if hard_match:
        return f"hard_bot_{hard_match.group(1)}"

    regular_match = re.fullmatch(r"holdout_regular_bot-(\d+)", name)
    if regular_match:
        return f"regular_bot_{regular_match.group(1)}"

    return None


def _compute_scenario_split_scores(
    scenario_scores: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    """Build split score dictionary keyed by training/hard/regular bot identifiers."""
    split_scores: Dict[str, float] = {}
    for scenario_name, values in scenario_scores.items():
        metric_key = _scenario_split_metric_key(str(scenario_name))
        if metric_key is None:
            continue
        split_scores[metric_key] = float(require_key(values, "combined"))
    return split_scores


def _filter_scenarios_from_config(
    training_cfg: Dict[str, Any],
    scenario_list: List[str],
    base_agent_key: str,
) -> List[str]:
    """
    Optionally filter evaluation scenarios from callback_params.bot_eval_scenarios.

    Expected format:
      callback_params:
        bot_eval_scenarios: ["bot-1", "bot-2"]
    """
    callback_params = require_key(training_cfg, "callback_params")
    requested = callback_params.get("bot_eval_scenarios")
    if requested is None:
        return scenario_list
    if not isinstance(requested, list):
        raise TypeError(
            "callback_params.bot_eval_scenarios must be a list of scenario names"
        )
    if len(requested) == 0:
        raise ValueError("callback_params.bot_eval_scenarios cannot be an empty list")

    requested_names = [str(name) for name in requested]
    scenario_map = {
        _scenario_name_from_file(base_agent_key, path): path
        for path in scenario_list
    }

    missing = [name for name in requested_names if name not in scenario_map]
    if missing:
        available = ", ".join(sorted(scenario_map.keys()))
        missing_fmt = ", ".join(missing)
        raise KeyError(
            "Unknown scenario(s) in callback_params.bot_eval_scenarios: "
            f"{missing_fmt}. Available: {available}"
        )

    return [scenario_map[name] for name in requested_names]


def _compute_holdout_split_metrics(
    training_cfg: Dict[str, Any],
    scenario_scores: Dict[str, Dict[str, float]],
    scenario_pool: str,
) -> Dict[str, float]:
    """Compute holdout regular/hard aggregates from callback_params scenario lists."""
    if scenario_pool != "holdout":
        return {}

    callback_params = require_key(training_cfg, "callback_params")
    regular_names = callback_params.get("holdout_regular_scenarios")
    hard_names = callback_params.get("holdout_hard_scenarios")

    if regular_names is None and hard_names is None:
        return {}
    if not isinstance(regular_names, list) or len(regular_names) == 0:
        raise ValueError(
            "callback_params.holdout_regular_scenarios must be a non-empty list "
            "when holdout split metrics are configured"
        )
    if not isinstance(hard_names, list) or len(hard_names) == 0:
        raise ValueError(
            "callback_params.holdout_hard_scenarios must be a non-empty list "
            "when holdout split metrics are configured"
        )

    available = set(scenario_scores.keys())
    regular_keys = [str(name) for name in regular_names]
    hard_keys = [str(name) for name in hard_names]

    missing_regular = [name for name in regular_keys if name not in available]
    missing_hard = [name for name in hard_keys if name not in available]
    if missing_regular or missing_hard:
        # Not enough episodes to cover every holdout split scenario.
        # Keep evaluation running, but skip split aggregates to avoid misleading partial means.
        return {}

    regular_values = [float(require_key(scenario_scores[name], "combined")) for name in regular_keys]
    hard_values = [float(require_key(scenario_scores[name], "combined")) for name in hard_keys]
    all_values = regular_values + hard_values
    if len(all_values) == 0:
        raise ValueError("Holdout split metrics cannot be computed from empty scenario score sets")

    return {
        "holdout_regular_mean": float(sum(regular_values) / len(regular_values)),
        "holdout_hard_mean": float(sum(hard_values) / len(hard_values)),
        "holdout_overall_mean": float(sum(all_values) / len(all_values)),
    }


def _format_elapsed(seconds: float) -> str:
    """Format seconds as MM:SS or H:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _create_eval_env(
    bot_name: str,
    bot_type: str,
    randomness_config: Dict[str, float],
    scenario_file: str,
    training_config_name: str,
    rewards_config_name: str,
    controlled_agent: str,
    base_agent_key: str,
    debug_mode: bool,
) -> "BotControlledEnv":
    """
    Crée un env d'éval. Utilisé en mode sérial et dans les workers.

    Tout ce qui est passé doit être sérialisable (picklable) pour usage en workers.
    """
    from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
    from ai.training_utils import setup_imports
    from ai.env_wrappers import BotControlledEnv
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.unit_registry import UnitRegistry

    unit_registry = UnitRegistry()
    W40KEngine, _ = setup_imports()

    # CRITICAL: RandomBot() n'accepte pas randomness ; GreedyBot/DefensiveBot oui
    if bot_type == "random":
        bot = RandomBot()
    else:
        bot_class = {"greedy": GreedyBot, "defensive": DefensiveBot}[bot_type]
        bot = bot_class(randomness=randomness_config.get(bot_type, 0.15))

    def mask_fn(env):
        return env.get_action_mask()

    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=controlled_agent,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=debug_mode,
    )
    masked_env = ActionMasker(base_env, mask_fn)
    return BotControlledEnv(masked_env, bot, unit_registry)


def _build_eval_obs_normalizer_for_worker(
    model,
    vec_model_path: Optional[str],
    vec_normalize_enabled: bool,
    vec_eval_enabled: bool,
) -> Optional[Callable[[np.ndarray], np.ndarray]]:
    """Version worker : pas d'accès à l'env de training."""
    if not vec_normalize_enabled or not vec_eval_enabled:
        return None
    if not vec_model_path:
        raise RuntimeError("VecNormalize enabled but vec_model_path not provided for worker")
    from ai.vec_normalize_utils import normalize_observation_for_inference

    def _normalize(obs: np.ndarray) -> np.ndarray:
        obs_arr = np.asarray(obs, dtype=np.float32)
        if obs_arr.ndim == 1:
            obs_arr = obs_arr.reshape(1, -1)
        normalized = normalize_observation_for_inference(obs_arr, vec_model_path)
        return np.asarray(normalized, dtype=np.float32).squeeze()

    return _normalize


def _episode_seed(base_seed: int, bot_name: str, scenario_idx: int, ep_idx: int) -> int:
    """Seed déterministe par (bot, scenario, épisode). Reproductible entre exécutions."""
    key = f"{bot_name}:{scenario_idx}:{ep_idx}"
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % (2**31)
    return (base_seed + h) % (2**31)


def _eval_worker_init(
    model_path: str,
    vec_model_path: Optional[str],
    vec_normalize_enabled: bool,
    vec_eval_enabled: bool,
    training_config_name: str,
    rewards_config_name: str,
    controlled_agent: str,
    base_agent_key: str,
) -> None:
    """Appelé une fois au démarrage de chaque worker. Charge modèle + normalizer."""
    global _worker_model, _worker_obs_normalizer
    from sb3_contrib import MaskablePPO

    _worker_model = MaskablePPO.load(model_path)
    _worker_obs_normalizer = _build_eval_obs_normalizer_for_worker(
        _worker_model, vec_model_path, vec_normalize_enabled, vec_eval_enabled
    )


def _eval_worker_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Exécuté dans un processus séparé (ou en sérial). Utilise _worker_model et _worker_obs_normalizer
    chargés par _eval_worker_init.

    Args:
        task: dict avec bot_name, bot_type, randomness_config, scenario_file, n_episodes,
              base_seed, scenario_index, config_params

    Returns:
        {"wins": int, "losses": int, "draws": int, "shoot_stats": dict, "bot_name": str, "scenario_name": str,
         "timeout": bool?, "error": str?}
    """
    global _worker_model, _worker_obs_normalizer
    if _worker_model is None:
        raise RuntimeError("Worker not initialized (call _eval_worker_init before tasks)")

    import random

    config_params = task["config_params"]
    env = _create_eval_env(
        bot_name=task["bot_name"],
        bot_type=task["bot_type"],
        randomness_config=task["randomness_config"],
        scenario_file=task["scenario_file"],
        **{k: config_params[k] for k in [
            "training_config_name", "rewards_config_name", "controlled_agent",
            "base_agent_key", "debug_mode"
        ] if k in config_params},
    )

    # step_logger : uniquement en mode sérial (non picklable, ne pas ajouter en mode parallèle)
    if config_params.get("step_logger"):
        env.engine.step_logger = config_params["step_logger"]

    wins, losses, draws = 0, 0, 0
    for ep_idx in range(task["n_episodes"]):
        ep_seed = _episode_seed(task["base_seed"], task["bot_name"], task["scenario_index"], ep_idx)
        random.seed(ep_seed)
        np.random.seed(ep_seed)
        obs, info = env.reset(seed=ep_seed)
        done = False
        while not done:
            model_obs = _worker_obs_normalizer(obs) if _worker_obs_normalizer else obs
            model_obs_arr = np.asarray(model_obs, dtype=np.float32)
            if model_obs_arr.ndim == 1:
                model_obs_arr = model_obs_arr.reshape(1, -1)
            action_masks = np.asarray(env.engine.get_action_mask(), dtype=bool)
            if action_masks.ndim == 1:
                action_masks = action_masks.reshape(1, -1)
            action, _ = _worker_model.predict(
                model_obs_arr,
                action_masks=action_masks,
                deterministic=task.get("deterministic", True),
            )
            action_scalar = int(np.asarray(action).flat[0])
            obs, reward, terminated, truncated, info = env.step(action_scalar)
            done = bool(terminated or truncated)
        winner = info.get("winner")
        if winner == 1:
            wins += 1
        elif winner == -1:
            draws += 1
        else:
            losses += 1

    shoot_stats = env.get_shoot_stats() if hasattr(env, "get_shoot_stats") else {}
    env.close()
    return {
        "wins": wins, "losses": losses, "draws": draws,
        "shoot_stats": shoot_stats,
        "bot_name": task["bot_name"],
        "scenario_name": task["scenario_name"],
    }


def _get_result_with_timeout(
    future,
    task: Dict[str, Any],
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """Récupère le résultat d'une tâche avec timeout. Retourne dict avec timeout/error si échec."""
    bot_name = task["bot_name"]
    scenario_name = task.get("scenario_name") or os.path.basename(task["scenario_file"]).replace(".json", "")
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        logging.warning(f"Eval task timeout: bot={bot_name} scenario={scenario_name}")
        return {
            "wins": 0, "losses": 0, "draws": 0,
            "timeout": True,
            "bot_name": bot_name,
            "scenario_name": scenario_name,
        }
    except Exception as e:
        logging.exception(f"Eval task failed: bot={bot_name} scenario={scenario_name} error={e}")
        return {
            "wins": 0, "losses": 0, "draws": 0,
            "error": str(e),
            "bot_name": bot_name,
            "scenario_name": scenario_name,
        }


def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes,
                         controlled_agent=None, show_progress=False, deterministic=True,
                         step_logger=None, debug_mode=False, eval_progress_label: Optional[str] = None,
                         show_summary: bool = True, eval_progress_prefix: Optional[str] = None,
                         scenario_pool: str = "training", model_path: Optional[str] = None,
                         line_length_state: Optional[Dict[str, Any]] = None):
    """
    Standalone bot evaluation function - single source of truth for all bot testing.

    Args:
        model: Trained model to evaluate
        training_config_name: Name of training config to use (e.g., "phase1", "default")
        n_episodes: Number of episodes per bot (will be split across all available scenarios)
        controlled_agent: Agent identifier (None for player 0, otherwise player 1)
        show_progress: Show progress bar with time estimates
        deterministic: Use deterministic policy
        step_logger: Optional StepLogger instance for detailed action logging
        eval_progress_label: Optional suffix displayed on evaluation progress line
        show_summary: Print diagnostic and scenario ranking summary at end
        eval_progress_prefix: Optional fixed prefix shown before eval progress (e.g., phase progress)
        line_length_state: Optional dict to store last_progress_line_len for clean switch back to training

    Returns:
        Dict with keys: 'random', 'greedy', 'defensive', 'combined',
                       'random_wins', 'greedy_wins', 'defensive_wins'
    """
    from config_loader import get_config_loader
    import time

    # Import evaluation bots for testing
    try:
        from ai.evaluation_bots import RandomBot, GreedyBot, DefensiveBot
        EVALUATION_BOTS_AVAILABLE = True
    except ImportError:
        EVALUATION_BOTS_AVAILABLE = False

    if not EVALUATION_BOTS_AVAILABLE:
        return {}

    # Import scenario utilities from training_utils
    from ai.training_utils import get_scenario_list_for_phase

    config = get_config_loader()

    # CRITICAL FIX: Strip phase suffix from controlled_agent for file path lookup
    # controlled_agent may be "Agent_phase1", but files are at "config/agents/Agent/..."
    base_agent_key = controlled_agent
    if controlled_agent:
        for phase_suffix in ['_phase1', '_phase2', '_phase3', '_phase4']:
            if controlled_agent.endswith(phase_suffix):
                base_agent_key = controlled_agent[:-len(phase_suffix)]
                break

    training_cfg = config.load_agent_training_config(base_agent_key, training_config_name)
    vec_norm_cfg = require_key(training_cfg, "vec_normalize")
    if not isinstance(vec_norm_cfg, dict):
        raise TypeError(f"vec_normalize must be a dict (got {type(vec_norm_cfg).__name__})")
    vec_normalize_enabled = bool(require_key(vec_norm_cfg, "enabled"))

    vec_norm_eval_cfg = require_key(training_cfg, "vec_normalize_eval")
    if not isinstance(vec_norm_eval_cfg, dict):
        raise TypeError(f"vec_normalize_eval must be a dict (got {type(vec_norm_eval_cfg).__name__})")
    vec_eval_enabled = bool(require_key(vec_norm_eval_cfg, "enabled"))
    vec_eval_training = require_key(vec_norm_eval_cfg, "training")
    if not isinstance(vec_eval_training, bool):
        raise TypeError(
            f"vec_normalize_eval.training must be boolean (got {type(vec_eval_training).__name__})"
        )
    vec_eval_norm_reward = require_key(vec_norm_eval_cfg, "norm_reward")
    if not isinstance(vec_eval_norm_reward, bool):
        raise TypeError(
            f"vec_normalize_eval.norm_reward must be boolean (got {type(vec_eval_norm_reward).__name__})"
        )
    if vec_eval_training:
        raise ValueError("vec_normalize_eval.training must be false for bot evaluation")
    if vec_eval_norm_reward:
        raise ValueError("vec_normalize_eval.norm_reward must be false for bot evaluation")
    if vec_eval_enabled and not vec_normalize_enabled:
        raise ValueError(
            "vec_normalize_eval.enabled is true but vec_normalize.enabled is false"
        )

    models_root = config.get_models_root()
    vec_model_path = os.path.join(
        models_root,
        base_agent_key,
        f"model_{base_agent_key}.zip"
    )

    # model_path pour workers : toujours sauvegarder le modèle courant en temp pour l'éval.
    # Pendant l'entraînement, le fichier canonique (model_agent.zip) n'est mis à jour qu'à la fin.
    # Si on utilisait ce fichier, les workers chargeraient un modèle obsolète → a_bot_eval_combined plat.
    import tempfile
    _fd, effective_model_path = tempfile.mkstemp(suffix=".zip")
    os.close(_fd)
    model.save(effective_model_path)
    _temp_model_path = effective_model_path

    bot_eval_cfg = _load_bot_eval_params(config, base_agent_key, training_config_name)
    eval_weights = bot_eval_cfg["weights"]
    eval_randomness = bot_eval_cfg["randomness"]
    randomness_config = {
        "greedy": eval_randomness.get("greedy", 0.15),
        "defensive": eval_randomness.get("defensive", 0.15),
    }

    if scenario_pool not in ("training", "holdout"):
        raise ValueError(
            f"scenario_pool must be 'training' or 'holdout' (got {scenario_pool!r})"
        )

    scenario_list = get_scenario_list_for_phase(
        config,
        base_agent_key,
        training_config_name,
        scenario_type=scenario_pool
    )

    if len(scenario_list) == 0:
        expected_dir = os.path.join(
            config.config_dir,
            "agents",
            base_agent_key,
            "scenarios",
            scenario_pool
        )
        raise FileNotFoundError(
            f"No {scenario_pool} scenarios found for agent '{base_agent_key}'. "
            f"Expected files in: {expected_dir} with naming '{base_agent_key}_*.json'."
        )
    scenario_list = _filter_scenarios_from_config(training_cfg, scenario_list, base_agent_key)

    if n_episodes <= 0:
        raise ValueError("n_episodes must be > 0 for bot evaluation")
    # Calculate episodes per scenario (distribute exactly, remainder goes to first scenarios)
    episodes_per_scenario = n_episodes // len(scenario_list)
    extra_episodes = n_episodes % len(scenario_list)

    callback_params = require_key(training_cfg, "callback_params")
    use_subprocess = callback_params.get("bot_eval_use_subprocess", True)
    if step_logger and step_logger.enabled:
        use_subprocess = False
    if debug_mode:
        use_subprocess = False

    n_envs = int(require_key(training_cfg, "n_envs"))
    if n_envs <= 0:
        raise ValueError(f"n_envs must be > 0 (got {n_envs})")

    config_params = {
        "training_config_name": training_config_name,
        "rewards_config_name": rewards_config_name,
        "controlled_agent": controlled_agent,
        "base_agent_key": base_agent_key,
        "vec_normalize_enabled": vec_normalize_enabled,
        "vec_model_path": vec_model_path,
        "debug_mode": debug_mode,
    }
    if not use_subprocess and step_logger and step_logger.enabled:
        config_params["step_logger"] = step_logger

    base_seed = 42
    task_timeout_seconds = callback_params.get("bot_eval_task_timeout_seconds", 300)
    n_workers = callback_params.get("bot_eval_n_workers")
    if n_workers is None:
        n_workers = min(n_envs, len(scenario_list) * 3)
    n_workers = max(1, int(n_workers))

    tasks: List[Dict[str, Any]] = []
    for bot_name in ("random", "greedy", "defensive"):
        for scenario_index, scenario_file in enumerate(scenario_list):
            scenario_name = _scenario_name_from_file(base_agent_key, scenario_file)
            episodes_for_scenario = episodes_per_scenario + (1 if scenario_index < extra_episodes else 0)
            if episodes_for_scenario <= 0:
                continue
            tasks.append({
                "bot_name": bot_name,
                "bot_type": bot_name,
                "randomness_config": randomness_config,
                "scenario_file": scenario_file,
                "scenario_name": scenario_name,
                "n_episodes": episodes_for_scenario,
                "base_seed": base_seed,
                "scenario_index": scenario_index,
                "deterministic": deterministic,
                "config_params": config_params,
            })

    initargs = (
        effective_model_path,
        vec_model_path,
        vec_normalize_enabled,
        vec_eval_enabled,
        training_config_name,
        rewards_config_name,
        controlled_agent,
        base_agent_key,
    )

    total_episodes = 3 * n_episodes
    start_time = time.time() if show_progress else None
    last_progress_line_len = 0

    def _print_progress(completed_ep: int, total_ep: int) -> None:
        """Print progress bar during eval (overwrites line)."""
        if not show_progress or start_time is None:
            return
        nonlocal last_progress_line_len
        progress_pct = (completed_ep / total_ep) * 100 if total_ep > 0 else 0
        bar_length = 20
        filled = int(bar_length * completed_ep / total_ep) if total_ep > 0 else 0
        bar = '█' * filled + '░' * (bar_length - filled)
        elapsed = time.time() - start_time
        _mins = int(elapsed // 60)
        _secs = int(elapsed % 60)
        elapsed_str = f"{_mins:02d}:{_secs:02d}" if _mins < 3600 else f"{int(elapsed//3600)}:{_mins%60:02d}:{_secs:02d}"
        speed_str = f"{completed_ep/elapsed:.2f}ep/s" if elapsed > 0 and completed_ep > 0 else "0.00ep/s"
        if eval_progress_prefix and eval_progress_label:
            line = f"{eval_progress_prefix}{eval_progress_label}: {progress_pct:3.0f}% {bar} {completed_ep}/{total_ep} [{elapsed_str}, {speed_str}]"
        elif eval_progress_label:
            line = f"{eval_progress_label}: {progress_pct:3.0f}% {bar} {completed_ep}/{total_ep} [{elapsed_str}, {speed_str}]"
        else:
            line = f"{progress_pct:3.0f}% {bar} {completed_ep}/{total_ep} [{elapsed_str}, {speed_str}]"
        clear_padding = " " * max(0, last_progress_line_len - len(line))
        sys.stdout.write(f"\r{line}{clear_padding}")
        sys.stdout.flush()
        last_progress_line_len = len(line)
        if line_length_state is not None:
            line_length_state["last_progress_line_len"] = len(line)

    try:
        if use_subprocess and n_workers > 1:
            ctx = mp.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=n_workers,
                mp_context=ctx,
                initializer=_eval_worker_init,
                initargs=initargs,
            ) as pool:
                future_to_task = {pool.submit(_eval_worker_task, t): t for t in tasks}
                results_list = []
                completed_episodes = 0
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    result = _get_result_with_timeout(future, task, task_timeout_seconds)
                    results_list.append(result)
                    completed_episodes += result.get("wins", 0) + result.get("losses", 0) + result.get("draws", 0)
                    _print_progress(completed_episodes, total_episodes)
        else:
            _eval_worker_init(*initargs)
            results_list = []
            completed_episodes = 0
            for t in tasks:
                result = _eval_worker_task(t)
                results_list.append(result)
                completed_episodes += result.get("wins", 0) + result.get("losses", 0) + result.get("draws", 0)
                _print_progress(completed_episodes, total_episodes)
    finally:
        if _temp_model_path and os.path.exists(_temp_model_path):
            try:
                os.remove(_temp_model_path)
            except OSError:
                pass

    # Agrégation (section 2.9)
    results: Dict[str, Any] = {}
    bot_names = ("random", "greedy", "defensive")
    for bn in bot_names:
        bot_results = [r for r in results_list if r.get("bot_name") == bn]
        wins = sum(r["wins"] for r in bot_results)
        losses = sum(r["losses"] for r in bot_results)
        draws = sum(r["draws"] for r in bot_results)
        total = wins + losses + draws
        results[bn] = wins / max(1, total)
        results[f"{bn}_wins"] = wins
        results[f"{bn}_losses"] = losses
        results[f"{bn}_draws"] = draws
        results[f"{bn}_shoot_stats"] = [
            r.get("shoot_stats") for r in bot_results
            if r.get("shoot_stats")
        ]

    scenario_bot_stats: Dict[str, Dict[str, Dict[str, float]]] = {}
    for r in results_list:
        sn, bn = r.get("scenario_name"), r.get("bot_name")
        if sn and bn:
            if sn not in scenario_bot_stats:
                scenario_bot_stats[sn] = {}
            total = r["wins"] + r["losses"] + r["draws"]
            scenario_bot_stats[sn][bn] = {
                "win_rate": r["wins"] / max(1, total),
                "wins": r["wins"],
                "losses": r["losses"],
                "draws": r["draws"],
            }

    total_failed_episodes = sum(1 for r in results_list if r.get("timeout") or r.get("error"))
    results["total_failed_episodes"] = total_failed_episodes

    results["combined"] = (
        eval_weights["random"] * results["random"] +
        eval_weights["greedy"] * results["greedy"] +
        eval_weights["defensive"] * results["defensive"]
    )
    results["scenario_bot_stats"] = scenario_bot_stats

    scenario_scores: Dict[str, Dict[str, float]] = {}
    for scenario_name, per_bot in scenario_bot_stats.items():
        random_stats = require_key(per_bot, "random")
        greedy_stats = require_key(per_bot, "greedy")
        defensive_stats = require_key(per_bot, "defensive")

        random_wr = float(require_key(random_stats, "win_rate"))
        greedy_wr = float(require_key(greedy_stats, "win_rate"))
        defensive_wr = float(require_key(defensive_stats, "win_rate"))

        combined_score = (
            eval_weights["random"] * random_wr
            + eval_weights["greedy"] * greedy_wr
            + eval_weights["defensive"] * defensive_wr
        )

        worst_bot_score = min(random_wr, greedy_wr, defensive_wr)
        scenario_scores[scenario_name] = {
            "combined": combined_score,
            "worst_bot_score": worst_bot_score,
        }
    results["scenario_scores"] = scenario_scores
    results["scenario_split_scores"] = _compute_scenario_split_scores(scenario_scores)
    holdout_split_metrics = _compute_holdout_split_metrics(training_cfg, scenario_scores, scenario_pool)
    results.update(holdout_split_metrics)

    if show_progress:
        # Show final progress bar (100%) before moving to next line
        progress_pct = 100.0
        bar_length = 20
        bar = '█' * bar_length
        elapsed = time.time() - start_time
        _mins = int(elapsed // 60)
        _secs = int(elapsed % 60)
        elapsed_str = f"{_mins:02d}:{_secs:02d}" if _mins < 3600 else f"{int(elapsed//3600)}:{_mins%60:02d}:{_secs:02d}"
        speed_str = f"{total_episodes/elapsed:.2f}ep/s" if elapsed > 0 else "0.00ep/s"
        if eval_progress_prefix and eval_progress_label:
            final_line = (
                f" [{elapsed_str}, {speed_str}] | "
                f"{eval_progress_label}: {progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes}"
            )
            full_final_line = f"{eval_progress_prefix}{final_line}"
        elif eval_progress_label:
            final_line = (
                f"{progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes} "
                f"[Completed] [{elapsed_str}, {speed_str}] {eval_progress_label}"
            )
            full_final_line = final_line
        else:
            final_line = (
                f"{progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes} "
                f"[Completed] [{elapsed_str}, {speed_str}]"
            )
            full_final_line = f"{eval_progress_prefix} {final_line}" if eval_progress_prefix else final_line
        clear_padding_len = max(0, last_progress_line_len - len(full_final_line))
        clear_padding = " " * clear_padding_len
        sys.stdout.write(f"\r{full_final_line}{clear_padding}")
        sys.stdout.flush()
        if line_length_state is not None:
            line_length_state["last_progress_line_len"] = len(full_final_line)

    # total_failed_episodes déjà dans results ; ne pas faire planter tout l'éval (PLAN21)

    # DIAGNOSTIC: Print shoot statistics (sample from last episode of each bot)
    if show_progress and show_summary:
        print("\n" + "="*80)
        print("📊 DIAGNOSTIC: Shoot Phase Behavior")
        print("="*80)
        print("Bot behavior analysis completed - check logs for detailed stats")
        print("="*80 + "\n")
        if scenario_scores:
            ranking = sorted(
                scenario_scores.items(),
                key=lambda item: item[1]["combined"],
                reverse=True
            )
            print("🏁 Scenario ranking (combined):")
            for name, values in ranking:
                print(
                    f"  - {name}: combined={values['combined']:.3f} "
                    f"| worst_bot_score={values['worst_bot_score']:.3f}"
                )
            print()

    return results
