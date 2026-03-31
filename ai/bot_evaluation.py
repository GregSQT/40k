#!/usr/bin/env python3
"""
ai/bot_evaluation.py - Bot evaluation functionality

Contains:
- evaluate_against_bots: Standalone bot evaluation function for all bot testing

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import hashlib
import json
import logging
import multiprocessing as mp
import os
import sys
import time
import tempfile
import shutil
import atexit
import numpy as np
import re
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable, Optional, Dict, List, Any, Tuple

from shared.data_validation import require_key

__all__ = ['evaluate_against_bots']

# Worker globals (scope processus)
_worker_model = None
_worker_obs_normalizer = None
_eval_ref_temp_dir: Optional[str] = None


def _cleanup_eval_ref_temp_dir() -> None:
    """Remove temporary scenario directory used by eval ref overrides."""
    global _eval_ref_temp_dir
    if _eval_ref_temp_dir and os.path.isdir(_eval_ref_temp_dir):
        shutil.rmtree(_eval_ref_temp_dir, ignore_errors=True)
    _eval_ref_temp_dir = None


def _get_eval_ref_temp_dir() -> str:
    """Create (once) and return temp dir for eval scenario ref overrides."""
    global _eval_ref_temp_dir
    if _eval_ref_temp_dir is None:
        _eval_ref_temp_dir = tempfile.mkdtemp(prefix="w40k_eval_refmix_")
        atexit.register(_cleanup_eval_ref_temp_dir)
    return _eval_ref_temp_dir


def _materialize_eval_scenario_refs(
    scenario_path: str,
    wall_ref: str,
    objectives_ref: str,
) -> str:
    """Create temporary scenario JSON with overridden wall_ref/objectives_ref."""
    if not isinstance(wall_ref, str) or not wall_ref.strip():
        raise ValueError(f"Invalid eval wall_ref override: {wall_ref!r}")
    if not isinstance(objectives_ref, str) or not objectives_ref.strip():
        raise ValueError(f"Invalid eval objectives_ref override: {objectives_ref!r}")
    with open(scenario_path, "r", encoding="utf-8-sig") as f:
        scenario_data = json.load(f)
    if not isinstance(scenario_data, dict):
        raise TypeError(f"Scenario JSON must be object: {scenario_path}")
    scenario_copy = dict(scenario_data)
    scenario_copy.pop("wall_hexes", None)
    scenario_copy.pop("objectives", None)
    scenario_copy.pop("objective_hexes", None)
    scenario_copy["wall_ref"] = wall_ref.strip()
    scenario_copy["objectives_ref"] = objectives_ref.strip()

    source_parts = tuple(os.path.abspath(scenario_path).split(os.sep))
    if "agents" not in source_parts:
        raise ValueError(
            f"Eval scenario override requires path containing 'agents': {scenario_path}"
        )
    agents_idx = source_parts.index("agents")
    if agents_idx + 1 >= len(source_parts):
        raise ValueError(f"Cannot resolve agent key from eval scenario path: {scenario_path}")
    agent_key = source_parts[agents_idx + 1]
    try:
        scenarios_idx = source_parts.index("scenarios", agents_idx + 2)
        split_dir = source_parts[scenarios_idx + 1]
    except (ValueError, IndexError):
        raise ValueError(
            f"Cannot resolve split directory (training/holdout_*) from eval scenario path: {scenario_path}"
        )

    temp_root = _get_eval_ref_temp_dir()
    out_dir = os.path.join(temp_root, "agents", agent_key, "scenarios", split_dir)
    os.makedirs(out_dir, exist_ok=True)
    path_hash = hashlib.sha1(
        f"{os.path.abspath(scenario_path)}|{wall_ref}|{objectives_ref}".encode("utf-8")
    ).hexdigest()[:16]
    out_path = os.path.join(out_dir, f"{os.path.basename(scenario_path)[:-5]}__{path_hash}.json")
    if not os.path.exists(out_path):
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(scenario_copy, f, ensure_ascii=True, indent=2)
    return out_path


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
    weights: Dict[str, float] = {
        name: float(w) for name, w in bot_eval_weights.items()
    }
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-9:
        detail = ", ".join(f"{k}={v}" for k, v in weights.items())
        raise ValueError(
            f"callback_params.bot_eval_weights must sum to 1.0 "
            f"(got {detail}, total={total_weight})"
        )

    bot_eval_randomness = require_key(callback_params, "bot_eval_randomness")
    randomness: Dict[str, float] = {
        name: float(r) for name, r in bot_eval_randomness.items()
    }

    return {
        "weights": weights,
        "randomness": randomness,
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
    agent_seat_mode: str,
    agent_seat_seed: Optional[int],
) -> "BotControlledEnv":
    """
    Crée un env d'éval. Utilisé en mode sérial et dans les workers.

    Tout ce qui est passé doit être sérialisable (picklable) pour usage en workers.
    """
    from ai.evaluation_bots import (
        RandomBot, GreedyBot, DefensiveBot, ControlBot,
        AggressiveSmartBot, DefensiveSmartBot, AdaptiveBot,
    )
    from ai.training_utils import setup_imports
    from ai.env_wrappers import BotControlledEnv
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.unit_registry import UnitRegistry

    unit_registry = UnitRegistry()
    W40KEngine, _ = setup_imports()

    BOT_CLASSES = {
        "greedy": GreedyBot,
        "defensive": DefensiveBot,
        "control": ControlBot,
        "aggressive_smart": AggressiveSmartBot,
        "defensive_smart": DefensiveSmartBot,
        "adaptive": AdaptiveBot,
    }
    if bot_type == "random":
        bot = RandomBot()
    elif bot_type in BOT_CLASSES:
        bot = BOT_CLASSES[bot_type](randomness=randomness_config.get(bot_type, 0.15))
    else:
        raise ValueError(f"Unknown bot_type: {bot_type!r}. Valid: random, {', '.join(BOT_CLASSES)}")

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
    return BotControlledEnv(
        masked_env,
        bot,
        unit_registry,
        agent_seat_mode=agent_seat_mode,
        global_seed=agent_seat_seed,
        env_rank=0,
    )


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
    worker_model_device: str,
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

    _worker_model = MaskablePPO.load(model_path, device=worker_model_device)
    _worker_obs_normalizer = _build_eval_obs_normalizer_for_worker(
        _worker_model, vec_model_path, vec_normalize_enabled, vec_eval_enabled
    )


def _eval_worker_task(
    task: Dict[str, Any],
    progress_callback: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
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
            "base_agent_key", "debug_mode", "agent_seat_mode", "agent_seat_seed"
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
        controlled_player = require_key(info, "controlled_player")
        if winner == controlled_player:
            wins += 1
        elif winner == -1:
            draws += 1
        else:
            losses += 1
        if progress_callback is not None:
            progress_callback()

    shoot_stats = env.get_shoot_stats() if hasattr(env, "get_shoot_stats") else {}
    env.close()
    return {
        "wins": wins, "losses": losses, "draws": draws,
        "failed_episodes": 0,
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
            "failed_episodes": int(task["n_episodes"]),
            "timeout": True,
            "bot_name": bot_name,
            "scenario_name": scenario_name,
        }
    except Exception as e:
        logging.exception(f"Eval task failed: bot={bot_name} scenario={scenario_name} error={e}")
        return {
            "wins": 0, "losses": 0, "draws": 0,
            "failed_episodes": int(task["n_episodes"]),
            "error": str(e),
            "bot_name": bot_name,
            "scenario_name": scenario_name,
        }


def _force_terminate_process_pool(pool: ProcessPoolExecutor) -> None:
    """
    Force-stop worker processes to avoid hangs when a task exceeds timeout.

    This uses ProcessPoolExecutor internals intentionally as a last-resort safety
    mechanism for robust evaluation runs.
    """
    processes = getattr(pool, "_processes", None)
    if not isinstance(processes, dict):
        return
    for process in processes.values():
        if process is None:
            continue
        if process.is_alive():
            process.terminate()
    for process in processes.values():
        if process is None:
            continue
        process.join(timeout=1.0)


def _collect_parallel_results_with_timeouts(
    pool: ProcessPoolExecutor,
    future_to_task: Dict[Any, Dict[str, Any]],
    task_timeout_seconds: int,
) -> List[Dict[str, Any]]:
    """
    Collect parallel eval results with per-task deadline enforcement.

    Unlike as_completed(), this loop never blocks indefinitely on a hung worker.
    If any running task exceeds timeout, the pool is force-terminated and all
    remaining pending tasks are marked as failed timeouts.
    """
    if task_timeout_seconds <= 0:
        raise ValueError(
            f"task_timeout_seconds must be > 0 for parallel collection (got {task_timeout_seconds})"
        )

    pending = set(future_to_task.keys())
    task_start_times: Dict[Any, float] = {future: time.monotonic() for future in pending}
    results_list: List[Dict[str, Any]] = []
    must_abort_pool = False

    while pending:
        done, not_done = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
        now = time.monotonic()

        # Collect completed tasks.
        for future in done:
            task = require_key(future_to_task, future)
            # Already done -> timeout=0 is safe and non-blocking.
            result = _get_result_with_timeout(future, task, timeout_seconds=0)
            results_list.append(result)

        # Enforce per-task timeout on still-running tasks.
        timed_out_futures: List[Any] = []
        for future in not_done:
            task = require_key(future_to_task, future)
            elapsed = now - require_key(task_start_times, future)
            if elapsed >= task_timeout_seconds:
                scenario_name = task.get("scenario_name") or os.path.basename(
                    require_key(task, "scenario_file")
                ).replace(".json", "")
                results_list.append(
                    {
                        "wins": 0,
                        "losses": 0,
                        "draws": 0,
                        "failed_episodes": int(require_key(task, "n_episodes")),
                        "timeout": True,
                        "bot_name": require_key(task, "bot_name"),
                        "scenario_name": scenario_name,
                    }
                )
                timed_out_futures.append(future)
                must_abort_pool = True

        # Remove handled futures from pending.
        for future in done:
            pending.discard(future)
        for future in timed_out_futures:
            pending.discard(future)

        # A single timeout indicates potential hung worker process.
        # Abort the whole pool to guarantee we don't hang forever.
        if must_abort_pool:
            break

    if must_abort_pool:
        _force_terminate_process_pool(pool)
        for future in list(pending):
            task = require_key(future_to_task, future)
            scenario_name = task.get("scenario_name") or os.path.basename(
                require_key(task, "scenario_file")
            ).replace(".json", "")
            results_list.append(
                {
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "failed_episodes": int(require_key(task, "n_episodes")),
                    "timeout": True,
                    "bot_name": require_key(task, "bot_name"),
                    "scenario_name": scenario_name,
                }
            )
    return results_list


def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes,
                         controlled_agent=None, show_progress=False, deterministic=True,
                         step_logger=None, debug_mode=False, eval_progress_label: Optional[str] = None,
                         show_summary: bool = True, eval_progress_prefix: Optional[str] = None,
                         scenario_pool: str = "training", model_path: Optional[str] = None,
                         line_length_state: Optional[Dict[str, Any]] = None,
                         scenario_list_override: Optional[List[str]] = None):
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

    # Import evaluation bots for testing
    eval_wall_start = time.time()
    try:
        from ai.evaluation_bots import (
            RandomBot, GreedyBot, DefensiveBot, ControlBot,
            AggressiveSmartBot, DefensiveSmartBot, AdaptiveBot,
        )
        EVALUATION_BOTS_AVAILABLE = True
    except ImportError:
        EVALUATION_BOTS_AVAILABLE = False

    if not EVALUATION_BOTS_AVAILABLE:
        return {}

    # Import scenario utilities from training_utils
    from ai.training_utils import get_scenario_list_for_phase

    config = get_config_loader()
    global_config = config.load_config("config", force_reload=False)
    progress_bar_cfg = require_key(global_config, "progress_bar")
    bot_eval_bar_length = require_key(progress_bar_cfg, "bot_eval_width")
    if not isinstance(bot_eval_bar_length, int) or isinstance(bot_eval_bar_length, bool):
        raise TypeError(
            "config.progress_bar.bot_eval_width must be an integer "
            f"(got {type(bot_eval_bar_length).__name__})"
        )
    if bot_eval_bar_length <= 0:
        raise ValueError(
            f"config.progress_bar.bot_eval_width must be > 0 (got {bot_eval_bar_length})"
        )

    # CRITICAL FIX: Strip phase suffix from controlled_agent for file path lookup
    # controlled_agent may be "Agent_phase1", but files are at "config/agents/Agent/..."
    base_agent_key = controlled_agent
    if controlled_agent:
        for phase_suffix in ['_phase1', '_phase2', '_phase3', '_phase4']:
            if controlled_agent.endswith(phase_suffix):
                base_agent_key = controlled_agent[:-len(phase_suffix)]
                break

    training_cfg = config.load_agent_training_config(base_agent_key, training_config_name)
    agent_seat_mode = require_key(training_cfg, "agent_seat_mode")
    if agent_seat_mode not in {"p1", "p2", "random"}:
        raise ValueError(
            f"training_config.agent_seat_mode must be one of 'p1', 'p2', 'random' "
            f"(got {agent_seat_mode!r})"
        )
    agent_seat_seed = None
    if agent_seat_mode == "random":
        if "agent_seat_seed" in training_cfg:
            agent_seat_seed_raw = require_key(training_cfg, "agent_seat_seed")
        elif "seed" in training_cfg:
            agent_seat_seed_raw = require_key(training_cfg, "seed")
        else:
            raise KeyError(
                "agent_seat_mode='random' requires a seed key in training config. "
                "Provide 'agent_seat_seed' (preferred) or existing 'seed'."
            )
        if not isinstance(agent_seat_seed_raw, int) or isinstance(agent_seat_seed_raw, bool):
            raise TypeError(
                "Seat seed must be an integer when agent_seat_mode='random' "
                "(from 'agent_seat_seed' or 'seed')."
            )
        agent_seat_seed = int(agent_seat_seed_raw)
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

    # model_path optionnel : permet d'évaluer un snapshot explicite (mode async).
    # Si absent, on sauvegarde un snapshot temporaire du modèle courant.
    _temp_model_path = None
    if model_path:
        effective_model_path = model_path
        if not os.path.exists(effective_model_path):
            raise FileNotFoundError(f"Evaluation snapshot not found: {effective_model_path}")
    else:
        # Pendant l'entraînement, le fichier canonique (model_agent.zip) n'est mis à jour qu'à la fin.
        # On snapshot donc le modèle courant pour éviter d'évaluer un artefact obsolète.
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
        "control": eval_randomness.get("control", 0.15),
    }

    active_bot_names = tuple(eval_weights.keys())

    if scenario_list_override is not None:
        if not isinstance(scenario_list_override, list):
            raise TypeError(
                f"scenario_list_override must be list or None (got {type(scenario_list_override).__name__})"
            )
        if len(scenario_list_override) == 0:
            raise ValueError("scenario_list_override cannot be empty")
        scenario_list = [str(path) for path in scenario_list_override]
        for scenario_path in scenario_list:
            if not os.path.isfile(scenario_path):
                raise FileNotFoundError(f"scenario_list_override contains missing file: {scenario_path}")
    else:
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
    sampling_cfg = training_cfg.get("scenario_sampling")
    eval_wall_refs: List[str] = []
    eval_objectives_refs: List[str] = []
    eval_ref_strict = False
    if scenario_pool == "holdout":
        if not isinstance(sampling_cfg, dict):
            raise TypeError(
                "scenario_sampling must be an object in training config for holdout evaluation"
            )
        raw_eval_wall_refs = require_key(sampling_cfg, "eval_wall_refs")
        raw_eval_objectives_refs = require_key(sampling_cfg, "eval_objectives_refs")
        raw_eval_ref_strict = sampling_cfg.get("eval_ref_strict", True)
        if not isinstance(raw_eval_ref_strict, bool):
            raise TypeError(
                "scenario_sampling.eval_ref_strict must be boolean "
                f"(got {type(raw_eval_ref_strict).__name__})"
            )
        eval_ref_strict = raw_eval_ref_strict
        if not isinstance(raw_eval_wall_refs, list) or len(raw_eval_wall_refs) == 0:
            raise ValueError(
                "scenario_sampling.eval_wall_refs must be a non-empty list for holdout evaluation"
            )
        if not isinstance(raw_eval_objectives_refs, list) or len(raw_eval_objectives_refs) == 0:
            raise ValueError(
                "scenario_sampling.eval_objectives_refs must be a non-empty list for holdout evaluation"
            )
        for raw_ref in raw_eval_wall_refs:
            if not isinstance(raw_ref, str) or not raw_ref.strip():
                raise ValueError(f"Invalid wall ref in scenario_sampling.eval_wall_refs: {raw_ref!r}")
            eval_wall_refs.append(raw_ref.strip())
        for raw_ref in raw_eval_objectives_refs:
            if not isinstance(raw_ref, str) or not raw_ref.strip():
                raise ValueError(
                    f"Invalid objectives ref in scenario_sampling.eval_objectives_refs: {raw_ref!r}"
                )
            eval_objectives_refs.append(raw_ref.strip())

    use_subprocess = callback_params.get("bot_eval_use_subprocess", True)
    worker_model_device_raw = require_key(callback_params, "bot_eval_worker_device")
    worker_model_device = str(worker_model_device_raw).strip().lower()
    if worker_model_device not in {"cpu", "auto"}:
        raise ValueError(
            "callback_params.bot_eval_worker_device must be either 'cpu' or 'auto' "
            f"(got {worker_model_device!r})"
        )
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
        "agent_seat_mode": agent_seat_mode,
        "agent_seat_seed": agent_seat_seed,
    }
    if not use_subprocess and step_logger and step_logger.enabled:
        config_params["step_logger"] = step_logger

    base_seed = 42
    task_timeout_seconds = callback_params.get("bot_eval_task_timeout_seconds", 300)
    n_workers = callback_params.get("bot_eval_n_workers")
    if n_workers is None:
        n_workers = min(n_envs, len(scenario_list) * len(active_bot_names))
    n_workers = max(1, int(n_workers))

    tasks: List[Dict[str, Any]] = []
    for bot_name in active_bot_names:
        for scenario_index, scenario_file in enumerate(scenario_list):
            scenario_name = _scenario_name_from_file(base_agent_key, scenario_file)
            task_scenario_file = scenario_file
            if scenario_pool == "holdout" and eval_ref_strict:
                wall_ref = eval_wall_refs[(scenario_index + len(bot_name)) % len(eval_wall_refs)]
                objectives_ref = eval_objectives_refs[
                    (scenario_index * 3 + len(bot_name)) % len(eval_objectives_refs)
                ]
                task_scenario_file = _materialize_eval_scenario_refs(
                    scenario_path=scenario_file,
                    wall_ref=wall_ref,
                    objectives_ref=objectives_ref,
                )
            episodes_for_scenario = episodes_per_scenario + (1 if scenario_index < extra_episodes else 0)
            if episodes_for_scenario <= 0:
                continue
            tasks.append({
                "bot_name": bot_name,
                "bot_type": bot_name,
                "randomness_config": randomness_config,
                "scenario_file": task_scenario_file,
                "scenario_name": scenario_name,
                "n_episodes": episodes_for_scenario,
                "base_seed": base_seed,
                "scenario_index": scenario_index,
                "deterministic": deterministic,
                "config_params": config_params,
            })

    initargs = (
        effective_model_path,
        worker_model_device,
        vec_model_path,
        vec_normalize_enabled,
        vec_eval_enabled,
        training_config_name,
        rewards_config_name,
        controlled_agent,
        base_agent_key,
    )

    total_episodes = len(active_bot_names) * n_episodes
    start_time = time.time() if show_progress else None
    last_progress_line_len = 0

    def _print_progress(completed_ep: int, total_ep: int) -> None:
        """Print progress bar during eval (overwrites line)."""
        if not show_progress or start_time is None:
            return
        nonlocal last_progress_line_len
        progress_pct = (completed_ep / total_ep) * 100 if total_ep > 0 else 0
        bar_length = bot_eval_bar_length
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

    if show_progress:
        _print_progress(0, total_episodes)

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
                results_list = _collect_parallel_results_with_timeouts(
                    pool=pool,
                    future_to_task=future_to_task,
                    task_timeout_seconds=int(task_timeout_seconds),
                )
                completed_episodes = 0
                for result in results_list:
                    completed_episodes += (
                        int(require_key(result, "wins"))
                        + int(require_key(result, "losses"))
                        + int(require_key(result, "draws"))
                        + int(require_key(result, "failed_episodes"))
                    )
                    _print_progress(min(completed_episodes, total_episodes), total_episodes)
        else:
            _eval_worker_init(*initargs)
            results_list = []
            completed_episodes = 0
            def _on_episode_completed() -> None:
                nonlocal completed_episodes
                completed_episodes += 1
                _print_progress(completed_episodes, total_episodes)
            for t in tasks:
                result = _eval_worker_task(t, progress_callback=_on_episode_completed)
                results_list.append(result)
    finally:
        if _temp_model_path and os.path.exists(_temp_model_path):
            try:
                os.remove(_temp_model_path)
            except OSError:
                pass

    # Agrégation (section 2.9)
    results: Dict[str, Any] = {}
    for bn in active_bot_names:
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

    total_failed_episodes = sum(int(require_key(r, "failed_episodes")) for r in results_list)
    results["total_failed_episodes"] = total_failed_episodes
    results["eval_reliable"] = total_failed_episodes == 0
    results["eval_duration_seconds"] = float(time.time() - eval_wall_start)

    results["combined"] = sum(
        eval_weights[bn] * results[bn] for bn in active_bot_names
    )
    results["scenario_bot_stats"] = scenario_bot_stats

    scenario_scores: Dict[str, Dict[str, float]] = {}
    for scenario_name, per_bot in scenario_bot_stats.items():
        bot_win_rates: Dict[str, float] = {}
        for bn in active_bot_names:
            stats = require_key(per_bot, bn)
            bot_win_rates[bn] = float(require_key(stats, "win_rate"))

        combined_score = sum(
            eval_weights[bn] * bot_win_rates[bn] for bn in active_bot_names
        )
        worst_bot_score = min(bot_win_rates.values())
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
        bar_length = bot_eval_bar_length
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
