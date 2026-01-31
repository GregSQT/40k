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

from shared.data_validation import require_key

__all__ = ['evaluate_against_bots']


def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes,
                         controlled_agent=None, show_progress=False, deterministic=True,
                         step_logger=None, debug_mode=False):
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

    results = {}
    # Initialize bots with stochasticity to prevent overfitting (15% random actions)
    bots = {
        'random': RandomBot(),
        'greedy': GreedyBot(randomness=0.15),
        'defensive': DefensiveBot(randomness=0.15)
    }
    config = get_config_loader()

    # CRITICAL FIX: Strip phase suffix from controlled_agent for file path lookup
    # controlled_agent may be "Agent_phase1", but files are at "config/agents/Agent/..."
    base_agent_key = controlled_agent
    if controlled_agent:
        for phase_suffix in ['_phase1', '_phase2', '_phase3', '_phase4']:
            if controlled_agent.endswith(phase_suffix):
                base_agent_key = controlled_agent[:-len(phase_suffix)]
                break

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

    # Calculate episodes per scenario (distribute evenly)
    episodes_per_scenario = max(1, n_episodes // len(scenario_list))

    unit_registry = UnitRegistry()

    # Progress tracking
    total_episodes = episodes_per_scenario * len(scenario_list) * len(bots)
    completed_episodes = 0
    start_time = time.time() if show_progress else None

    total_expected_episodes = len(bots) * len(scenario_list) * episodes_per_scenario
    total_failed_episodes = 0

    for bot_name, bot in bots.items():
        wins = 0
        losses = 0
        draws = 0

        # MULTI-SCENARIO: Iterate through all scenarios
        for scenario_file in scenario_list:
            scenario_name = os.path.basename(scenario_file).replace(f"{base_agent_key}_scenario_", "").replace(".json", "") if base_agent_key else "default"

            # PERFORMANCE: Create environment ONCE per scenario and reuse for all episodes
            # This avoids expensive re-initialization (loading configs, creating wrappers, etc.)
            W40KEngine, _ = setup_imports()

            # Create base environment with specified training config
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

            # Connect step_logger if provided and enabled
            if step_logger and step_logger.enabled:
                base_env.step_logger = step_logger

            # Wrap with ActionMasker (CRITICAL for proper action masking)
            def mask_fn(env):
                return env.get_action_mask()

            masked_env = ActionMasker(base_env, mask_fn)
            bot_env = BotControlledEnv(masked_env, bot, unit_registry)

            # Run all episodes for this bot/scenario using the same environment
            try:
                for episode_num in range(episodes_per_scenario):
                    completed_episodes += 1

                    # Progress bar (only if show_progress=True)
                    if show_progress:
                        progress_pct = (completed_episodes / total_episodes) * 100
                        bar_length = 50
                        filled = int(bar_length * completed_episodes / total_episodes)
                        bar = '█' * filled + '░' * (bar_length - filled)

                        elapsed = time.time() - start_time
                        avg_time = elapsed / completed_episodes
                        remaining = total_episodes - completed_episodes
                        eta = avg_time * remaining

                        # Calculate evaluation speed
                        eps_speed = completed_episodes / elapsed if elapsed > 0 else 0

                        # Format times as HH:MM:SS or MM:SS depending on duration
                        def format_time(seconds):
                            hours = int(seconds // 3600)
                            minutes = int((seconds % 3600) // 60)
                            secs = int(seconds % 60)
                            if hours > 0:
                                return f"{hours}:{minutes:02d}:{secs:02d}"
                            else:
                                return f"{minutes:02d}:{secs:02d}"

                        elapsed_str = format_time(elapsed)
                        eta_str = format_time(eta)
                        speed_str = f"{eps_speed:.2f}ep/s" if eps_speed >= 0.01 else f"{eps_speed*60:.1f}ep/m"

                        sys.stdout.write(f"\r{progress_pct:3.0f}% {bar} {completed_episodes}/{total_episodes} vs {bot_name.capitalize()}Bot [{scenario_name}] [{elapsed_str}<{eta_str}, {speed_str}]")
                        sys.stdout.flush()

                    # Set bot name for episode logging (for step_logger)
                    if step_logger and step_logger.enabled:
                        step_logger.current_bot_name = bot_name

                    obs, info = bot_env.reset()
                    done = False
                    step_count = 0
                    max_steps = 1000  # Safety guard

                    # Episodes terminate naturally when game conditions are met:
                    # - All enemy units eliminated, OR
                    # - Turn 5 completed (objective-based victory)
                    while not done:
                        if step_count >= max_steps:
                            print(f"ERROR: Episode exceeded {max_steps} steps! Forcing termination.", flush=True)
                            
                            # LOG TEMPORAIRE: Log when step limit is reached (only if --debug)
                            if debug_mode:
                                game_state = bot_env.engine.game_state
                                episode = require_key(game_state, "episode_number")
                                turn = require_key(game_state, "turn")
                                phase = require_key(game_state, "phase")
                                current_player = require_key(game_state, "current_player")
                                
                                # Get pool states
                                shoot_pool = require_key(game_state, "shoot_activation_pool")
                                move_pool = require_key(game_state, "move_activation_pool")
                                active_shooting_unit = require_key(game_state, "active_shooting_unit")
                                
                                # Get eligible units
                                action_mask = bot_env.engine.get_action_mask()
                                num_valid_actions = action_mask.sum() if isinstance(action_mask, np.ndarray) else 0
                                
                                debug_message = (
                                    f"[MAX_STEPS LIMIT REACHED] Episode {episode}, Step {step_count}/{max_steps}\n"
                                    f"  Turn: {turn}, Phase: {phase}, Current Player: {current_player}\n"
                                    f"  Shoot Pool: {[str(uid) for uid in shoot_pool]} (size: {len(shoot_pool)})\n"
                                    f"  Move Pool: {[str(uid) for uid in move_pool]} (size: {len(move_pool)})\n"
                                    f"  Active Shooting Unit: {active_shooting_unit}\n"
                                    f"  Valid Actions: {num_valid_actions}\n"
                                    f"  Action Mask: {action_mask.tolist() if isinstance(action_mask, np.ndarray) else action_mask}"
                                )
                                
                                debug_log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.log')
                                try:
                                    with open(debug_log_path, 'a', encoding='utf-8', errors='replace') as f:
                                        f.write(debug_message + "\n")
                                        f.flush()
                                except Exception as e:
                                    print(f"⚠️ Failed to write to debug.log: {e}", flush=True)
                            
                            break
                        # LOG TEMPORAIRE: GET_MASK_TIMING (get_action_mask in bot loop; only if --debug)
                        ep_num = require_key(bot_env.engine.game_state, "episode_number")
                        t_get_mask0 = time.perf_counter() if debug_mode else None
                        action_masks = bot_env.engine.get_action_mask()
                        # LOG TEMPORAIRE: only every 50 steps to avoid I/O bottleneck (episode can appear stuck otherwise)
                        if debug_mode and t_get_mask0 is not None and ep_num >= 0 and step_count % 50 == 0:
                            get_mask_duration = time.perf_counter() - t_get_mask0
                            try:
                                debug_log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.log')
                                with open(debug_log_path, 'a', encoding='utf-8', errors='replace') as f:
                                    f.write(f"GET_MASK_TIMING episode={int(ep_num)} step_index={step_count} duration_s={get_mask_duration:.6f}\n")
                            except (OSError, IOError):
                                pass
                        # LOG TEMPORAIRE: PREDICT_TIMING → only every 50 steps to avoid I/O bottleneck
                        t0 = time.perf_counter()
                        action, _ = model.predict(obs, action_masks=action_masks, deterministic=deterministic)
                        predict_duration = time.perf_counter() - t0
                        if debug_mode and ep_num >= 0 and step_count % 50 == 0:
                            debug_log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.log')
                            try:
                                with open(debug_log_path, 'a', encoding='utf-8', errors='replace') as f:
                                    f.write(f"PREDICT_TIMING episode={int(ep_num)} step_index={step_count} duration_s={predict_duration:.6f}\n")
                            except (OSError, IOError):
                                pass

                        obs, reward, terminated, truncated, info = bot_env.step(action)
                        done = terminated or truncated
                        step_count += 1

                        # Progress hint for long episodes so user sees it's not stuck
                        if show_progress and step_count % 100 == 0 and step_count > 0:
                            sys.stdout.write(f"\r{progress_pct:3.0f}% {bar} {completed_episodes}/{total_episodes} vs {bot_name.capitalize()}Bot [{scenario_name}] step {step_count} [{elapsed_str}<{eta_str}, {speed_str}]   ")
                            sys.stdout.flush()

                    # Determine winner - track wins/losses/draws
                    # CRITICAL FIX: Learning agent is ALWAYS Player 0, regardless of controlled_agent name
                    # controlled_agent is the agent key string (e.g., "SpaceMarine_phase1"), NOT a player ID
                    agent_player = 1  # Learning agent is always Player 1
                    winner = info.get('winner')

                    if winner == agent_player:
                        wins += 1
                    elif winner == -1:
                        draws += 1
                    else:
                        losses += 1

                    # DIAGNOSTIC: Collect shoot stats from all episodes
                    bot_stats = bot_env.get_shoot_stats()
                    if f'{bot_name}_shoot_stats' not in results:
                        results[f'{bot_name}_shoot_stats'] = []
                    results[f'{bot_name}_shoot_stats'].append(bot_stats)

            except Exception as e:
                total_failed_episodes += 1
                if show_progress:
                    print(f"\n❌ Bot evaluation failed for {bot_name} on scenario {scenario_name}: {e}")
                # Do not treat this as valid games; skip win/loss counting
            finally:
                # Close environment after all episodes for this scenario are done
                bot_env.close()

        # Calculate win rate across ALL scenarios
        total_games = episodes_per_scenario * len(scenario_list)
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
        print(f"\r{progress_pct:3.0f}% {bar} {total_episodes}/{total_episodes} [Completed] [{elapsed_str}, {speed_str}]")
        print()  # New line after final progress bar

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

    # Combined score with improved weighting: RandomBot 35%, GreedyBot 30%, DefensiveBot 35%
    # Increased RandomBot weight to prevent overfitting to predictable patterns
    results['combined'] = 0.35 * results['random'] + 0.30 * results['greedy'] + 0.35 * results['defensive']

    # DIAGNOSTIC: Print shoot statistics (sample from last episode of each bot)
    if show_progress:
        print("\n" + "="*80)
        print("📊 DIAGNOSTIC: Shoot Phase Behavior")
        print("="*80)
        print("Bot behavior analysis completed - check logs for detailed stats")
        print("="*80 + "\n")

    return results
