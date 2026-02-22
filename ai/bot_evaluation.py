#!/usr/bin/env python3
"""
ai/bot_evaluation.py - Bot evaluation functionality

Contains:
- evaluate_against_bots: Standalone bot evaluation function for all bot testing

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import sys
import numpy as np
import re
from typing import Callable, Optional, Dict, List, Any, Tuple

from shared.data_validation import require_key

__all__ = ['evaluate_against_bots']


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
    if not base_agent_key:
        return os.path.basename(scenario_file).replace(".json", "")
    return (
        os.path.basename(scenario_file)
        .replace(f"{base_agent_key}_scenario_", "")
        .replace(".json", "")
    )


def _scenario_metric_slug(scenario_name: str) -> str:
    """Convert scenario label to TensorBoard-safe metric suffix."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", scenario_name.strip()).strip("_").lower()
    if not normalized:
        raise ValueError(f"Invalid scenario name for metric slug: '{scenario_name}'")
    return normalized


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


def _format_elapsed(seconds: float) -> str:
    """Format seconds as MM:SS or H:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes,
                         controlled_agent=None, show_progress=False, deterministic=True,
                         step_logger=None, debug_mode=False, eval_progress_label: Optional[str] = None,
                         show_summary: bool = True, eval_progress_prefix: Optional[str] = None):
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

    Returns:
        Dict with keys: 'random', 'greedy', 'defensive', 'combined',
                       'random_wins', 'greedy_wins', 'defensive_wins'
    """
    from ai.unit_registry import UnitRegistry
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
    from ai.training_utils import get_scenario_list_for_phase, get_agent_scenario_file, setup_imports
    from ai.env_wrappers import BotControlledEnv
    from sb3_contrib.common.wrappers import ActionMasker

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

    obs_normalizer = _build_eval_obs_normalizer(
        model=model,
        vec_normalize_enabled=vec_normalize_enabled and vec_eval_enabled,
        vec_model_path=vec_model_path,
    )

    bot_eval_cfg = _load_bot_eval_params(config, base_agent_key, training_config_name)
    eval_weights = bot_eval_cfg["weights"]
    eval_randomness = bot_eval_cfg["randomness"]

    results = {}
    # Initialize bots with configured stochasticity to prevent overfitting.
    bots = {
        'random': RandomBot(),
        'greedy': GreedyBot(randomness=eval_randomness["greedy"]),
        'defensive': DefensiveBot(randomness=eval_randomness["defensive"])
    }

    # MULTI-SCENARIO EVALUATION: Get all available bot scenarios
    # Bot evaluation should always use bot scenarios (not phase-specific scenarios)
    scenario_list = get_scenario_list_for_phase(config, base_agent_key, "bot")

    # If no bot scenarios found, fall back to phase-specific scenarios
    if len(scenario_list) == 0:
        scenario_list = get_scenario_list_for_phase(config, base_agent_key, training_config_name)

    # If still nothing found, try single scenario file
    if len(scenario_list) == 0:
        try:
            scenario_list = [get_agent_scenario_file(config, base_agent_key, training_config_name)]
        except FileNotFoundError:
            raise FileNotFoundError(f"No scenarios found for agent '{base_agent_key}'. "
                                    f"Expected bot scenarios at config/agents/{base_agent_key}/scenarios/")
    scenario_list = _filter_scenarios_from_config(training_cfg, scenario_list, base_agent_key)

    if n_episodes <= 0:
        raise ValueError("n_episodes must be > 0 for bot evaluation")
    # Calculate episodes per scenario (distribute exactly, remainder goes to first scenarios)
    episodes_per_scenario = n_episodes // len(scenario_list)
    extra_episodes = n_episodes % len(scenario_list)

    unit_registry = UnitRegistry()

    # Progress tracking
    total_episodes = n_episodes * len(bots)
    completed_episodes = 0
    start_time = time.time() if show_progress else None
    last_progress_line_len = 0

    total_expected_episodes = len(bots) * n_episodes
    total_failed_episodes = 0
    scenario_bot_stats: Dict[str, Dict[str, Dict[str, float]]] = {}

    eval_parallel_envs = int(require_key(training_cfg, "n_envs"))
    if eval_parallel_envs <= 0:
        raise ValueError(f"n_envs must be > 0 for evaluation batching (got {eval_parallel_envs})")
    if step_logger and step_logger.enabled:
        # Step logger is file-based and not designed for concurrent env interleaving.
        # Keep deterministic serial mode when detailed step logging is enabled.
        eval_parallel_envs = 1

    for bot_name, bot in bots.items():
        wins = 0
        losses = 0
        draws = 0

        # MULTI-SCENARIO: Iterate through all scenarios
        for scenario_index, scenario_file in enumerate(scenario_list):
            scenario_name = _scenario_name_from_file(base_agent_key, scenario_file)
            episodes_for_scenario = episodes_per_scenario + (1 if scenario_index < extra_episodes else 0)
            if episodes_for_scenario == 0:
                continue
            scenario_wins = 0
            scenario_losses = 0
            scenario_draws = 0

            # Build engine class once; env instances are created in parallel slots.
            W40KEngine, _ = setup_imports()

            # Wrap with ActionMasker (CRITICAL for proper action masking)
            def mask_fn(env):
                return env.get_action_mask()

            def create_bot_env() -> BotControlledEnv:
                base_env = W40KEngine(
                    rewards_config=rewards_config_name,
                    training_config_name=training_config_name,
                    controlled_agent=controlled_agent,
                    active_agents=None,
                    scenario_file=scenario_file,
                    unit_registry=unit_registry,
                    quiet=True,
                    gym_training_mode=True,
                    debug_mode=debug_mode
                )
                if step_logger and step_logger.enabled:
                    base_env.step_logger = step_logger
                masked_env = ActionMasker(base_env, mask_fn)
                return BotControlledEnv(masked_env, bot, unit_registry)

            batch_env_count = min(eval_parallel_envs, episodes_for_scenario)
            if batch_env_count <= 0:
                raise ValueError(
                    f"Invalid batch_env_count={batch_env_count} for episodes_for_scenario={episodes_for_scenario}"
                )
            bot_envs = [create_bot_env() for _ in range(batch_env_count)]
            slot_obs: List[Optional[np.ndarray]] = [None for _ in range(batch_env_count)]
            slot_info: List[Optional[Dict[str, Any]]] = [None for _ in range(batch_env_count)]
            slot_active = [False for _ in range(batch_env_count)]
            slot_step_counts = [0 for _ in range(batch_env_count)]
            max_steps = 1000  # Safety guard

            try:
                started_episodes = 0
                finished_episodes = 0

                for slot_idx in range(batch_env_count):
                    if started_episodes >= episodes_for_scenario:
                        break
                    if step_logger and step_logger.enabled:
                        step_logger.current_bot_name = bot_name
                    obs, info = bot_envs[slot_idx].reset()
                    slot_obs[slot_idx] = obs
                    slot_info[slot_idx] = info
                    slot_active[slot_idx] = True
                    slot_step_counts[slot_idx] = 0
                    started_episodes += 1

                while finished_episodes < episodes_for_scenario:
                    active_slots = [i for i in range(batch_env_count) if slot_active[i]]
                    if not active_slots:
                        raise RuntimeError(
                            f"No active evaluation slots while finished_episodes={finished_episodes} "
                            f"and episodes_for_scenario={episodes_for_scenario}"
                        )

                    batch_obs = []
                    batch_masks = []
                    for slot_idx in active_slots:
                        obs_value = slot_obs[slot_idx]
                        if obs_value is None:
                            raise ValueError(f"Missing observation for active slot {slot_idx}")
                        model_obs = obs_normalizer(obs_value) if obs_normalizer else obs_value
                        batch_obs.append(model_obs)
                        batch_masks.append(bot_envs[slot_idx].engine.get_action_mask())

                    batch_obs_np = np.asarray(batch_obs, dtype=np.float32)
                    batch_masks_np = np.asarray(batch_masks, dtype=bool)
                    actions, _ = model.predict(
                        batch_obs_np,
                        action_masks=batch_masks_np,
                        deterministic=deterministic
                    )
                    actions_np = np.asarray(actions)
                    if actions_np.ndim == 0:
                        actions_np = actions_np.reshape(1)
                    if len(actions_np) != len(active_slots):
                        raise ValueError(
                            f"predict returned {len(actions_np)} actions for {len(active_slots)} active slots"
                        )

                    for local_idx, slot_idx in enumerate(active_slots):
                        if slot_step_counts[slot_idx] >= max_steps:
                            game_state = bot_envs[slot_idx].engine.game_state
                            episode = require_key(game_state, "episode_number")
                            turn = require_key(game_state, "turn")
                            phase = require_key(game_state, "phase")
                            current_player = require_key(game_state, "current_player")
                            raise RuntimeError(
                                f"Episode exceeded {max_steps} steps (episode={episode}, turn={turn}, "
                                f"phase={phase}, player={current_player})"
                            )

                        action_int = int(actions_np[local_idx])
                        obs, reward, terminated, truncated, info = bot_envs[slot_idx].step(action_int)
                        slot_obs[slot_idx] = obs
                        slot_info[slot_idx] = info
                        slot_step_counts[slot_idx] = slot_step_counts[slot_idx] + 1
                        done = bool(terminated or truncated)

                        if not done:
                            continue

                        # CRITICAL FIX: Learning agent is ALWAYS Player 1
                        winner = info.get('winner')
                        if winner == 1:
                            wins += 1
                            scenario_wins += 1
                        elif winner == -1:
                            draws += 1
                            scenario_draws += 1
                        else:
                            losses += 1
                            scenario_losses += 1

                        if f'{bot_name}_shoot_stats' not in results:
                            results[f'{bot_name}_shoot_stats'] = []
                        results[f'{bot_name}_shoot_stats'].append(bot_envs[slot_idx].get_shoot_stats())

                        completed_episodes += 1
                        finished_episodes += 1

                        if show_progress:
                            progress_pct = (completed_episodes / total_episodes) * 100
                            bar_length = 50
                            filled = int(bar_length * completed_episodes / total_episodes)
                            bar = '█' * filled + '░' * (bar_length - filled)
                            elapsed = time.time() - start_time
                            avg_time = elapsed / completed_episodes
                            remaining = total_episodes - completed_episodes
                            eta = avg_time * remaining
                            eps_speed = completed_episodes / elapsed if elapsed > 0 else 0
                            elapsed_str = _format_elapsed(elapsed)
                            eta_str = _format_elapsed(eta)
                            speed_str = f"{eps_speed:.2f}ep/s" if eps_speed >= 0.01 else f"{eps_speed * 60:.1f}ep/m"
                            if eval_progress_prefix:
                                eval_label = eval_progress_label if eval_progress_label else ""
                                line = (
                                    f"{progress_pct:3.0f}% {completed_episodes}/{total_episodes} "
                                    f"[{elapsed_str}<{eta_str}, {speed_str}] {eval_label}"
                                ).rstrip()
                            elif eval_progress_label:
                                line = (
                                    f"{progress_pct:3.0f}% {bar} {completed_episodes}/{total_episodes} "
                                    f"[{elapsed_str}<{eta_str}, {speed_str}] {eval_progress_label}"
                                )
                            else:
                                line = (
                                    f"{progress_pct:3.0f}% {bar} {completed_episodes}/{total_episodes} "
                                    f"vs {bot_name.capitalize()}Bot [{scenario_name}] [{elapsed_str}<{eta_str}, {speed_str}]"
                                )
                            full_line = f"{eval_progress_prefix} | {line}" if eval_progress_prefix else line
                            clear_padding = " " * max(0, last_progress_line_len - len(full_line))
                            sys.stdout.write(f"\r{' ' * 260}\r{full_line}{clear_padding}")
                            sys.stdout.flush()
                            last_progress_line_len = len(full_line)

                        if started_episodes < episodes_for_scenario:
                            if step_logger and step_logger.enabled:
                                step_logger.current_bot_name = bot_name
                            reset_obs, reset_info = bot_envs[slot_idx].reset()
                            slot_obs[slot_idx] = reset_obs
                            slot_info[slot_idx] = reset_info
                            slot_active[slot_idx] = True
                            slot_step_counts[slot_idx] = 0
                            started_episodes += 1
                        else:
                            slot_active[slot_idx] = False
                            slot_obs[slot_idx] = None
                            slot_info[slot_idx] = None

            except Exception as e:
                total_failed_episodes += 1
                if show_progress:
                    print(f"\n❌ Bot evaluation failed for {bot_name} on scenario {scenario_name}: {e}")
                error_type = type(e).__name__
                try:
                    active_slot = 0
                    for idx in range(len(bot_envs)):
                        if slot_active[idx]:
                            active_slot = idx
                            break
                    game_state = bot_envs[active_slot].engine.game_state
                    episode = game_state.get("episode_number")
                    turn = game_state.get("turn")
                    phase = game_state.get("phase")
                    current_player = game_state.get("current_player")
                    fight_subphase = game_state.get("fight_subphase")
                except Exception as state_error:
                    episode = None
                    turn = None
                    phase = None
                    current_player = None
                    fight_subphase = None
                    if show_progress:
                        print(f"⚠️ Failed to read game_state after bot error: {state_error}")
                if show_progress:
                    print(
                        f"❌ Bot evaluation error details: type={error_type} "
                        f"episode_index=unknown "
                        f"episode_number={episode} turn={turn} phase={phase} "
                        f"player={current_player} fight_subphase={fight_subphase}"
                    )
                import traceback
                traceback_str = traceback.format_exc()
                if show_progress:
                    print(f"❌ Bot evaluation traceback:\n{traceback_str}")
                # Do not treat this as valid games; skip win/loss counting
            finally:
                # Close environment after all episodes for this scenario are done
                for env_instance in bot_envs:
                    env_instance.close()
                if scenario_name not in scenario_bot_stats:
                    scenario_bot_stats[scenario_name] = {}
                scenario_bot_stats[scenario_name][bot_name] = {
                    "episodes": float(episodes_for_scenario),
                    "wins": float(scenario_wins),
                    "losses": float(scenario_losses),
                    "draws": float(scenario_draws),
                    "win_rate": float(scenario_wins) / float(episodes_for_scenario),
                }

        # Calculate win rate across ALL scenarios
        total_games = n_episodes
        win_rate = wins / total_games if total_games > 0 else 0.0
        results[bot_name] = win_rate
        results[f'{bot_name}_wins'] = wins
        results[f'{bot_name}_losses'] = losses
        results[f'{bot_name}_draws'] = draws

        # DIAGNOSTIC: Print average shoot stats for this bot
        if f'{bot_name}_shoot_stats' in results and results[f'{bot_name}_shoot_stats']:
            stats_list = results[f'{bot_name}_shoot_stats']
            avg_opportunities = sum(s['shoot_opportunities'] for s in stats_list) / len(stats_list)
            avg_shoot_rate = sum(s['shoot_rate'] for s in stats_list) / len(stats_list)

            avg_ai_opportunities = sum(s['ai_shoot_opportunities'] for s in stats_list) / len(stats_list)
            avg_ai_shoot_rate = sum(s['ai_shoot_rate'] for s in stats_list) / len(stats_list)

    if show_progress:
        # Show final progress bar (100%) before moving to next line
        progress_pct = 100.0
        bar_length = 50
        bar = '█' * bar_length
        elapsed = time.time() - start_time
        _mins = int(elapsed // 60)
        _secs = int(elapsed % 60)
        elapsed_str = f"{_mins:02d}:{_secs:02d}" if _mins < 3600 else f"{int(elapsed//3600)}:{_mins%60:02d}:{_secs:02d}"
        speed_str = f"{total_episodes/elapsed:.2f}ep/s" if elapsed > 0 else "0.00ep/s"
        if eval_progress_prefix:
            eval_label = eval_progress_label if eval_progress_label else ""
            final_line = (
                f"{progress_pct:3.0f}% {total_episodes}/{total_episodes} "
                f"[Completed] [{elapsed_str}, {speed_str}] {eval_label}"
            ).rstrip()
        elif eval_progress_label:
            final_line = (
                f"{progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes} "
                f"[Completed] [{elapsed_str}, {speed_str}] {eval_progress_label}"
            )
        else:
            final_line = (
                f"{progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes} "
                f"[Completed] [{elapsed_str}, {speed_str}]"
            )
        full_final_line = f"{eval_progress_prefix} | {final_line}" if eval_progress_prefix else final_line
        clear_padding = " " * max(0, last_progress_line_len - len(full_final_line))
        sys.stdout.write(f"\r{' ' * 260}\r{full_final_line}{clear_padding}")
        sys.stdout.flush()

    # AI_IMPLEMENTATION.md: No silent evaluation degradation.
    # If any episodes failed to run, surface this explicitly and avoid logging
    # potentially misleading combined metrics.
    if total_failed_episodes > 0:
        success_episodes = total_episodes - total_failed_episodes
        raise RuntimeError(
            f"Bot evaluation aborted: {total_failed_episodes} out of {total_episodes} "
            f"episodes failed. Successful episodes: {success_episodes}. "
            f"Fix environment/scenario issues before relying on evaluation metrics."
        )

    # Combined score from agent-specific config.
    results['combined'] = (
        eval_weights['random'] * results['random'] +
        eval_weights['greedy'] * results['greedy'] +
        eval_weights['defensive'] * results['defensive']
    )

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
