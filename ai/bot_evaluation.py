#!/usr/bin/env python3
"""
ai/bot_evaluation.py - Bot evaluation functionality

Contains:
- evaluate_against_bots: Standalone bot evaluation function for all bot testing

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import sys

__all__ = ['evaluate_against_bots']


def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes,
                         controlled_agent=None, show_progress=False, deterministic=True,
                         step_logger=None):
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

    # MULTI-SCENARIO EVALUATION: Get all available scenarios for this phase
    scenario_list = get_scenario_list_for_phase(config, base_agent_key, training_config_name)

    # If only one scenario found, fall back to old behavior
    if len(scenario_list) == 0:
        scenario_list = [get_agent_scenario_file(config, base_agent_key, training_config_name)]

    # Calculate episodes per scenario (distribute evenly)
    episodes_per_scenario = max(1, n_episodes // len(scenario_list))

    unit_registry = UnitRegistry()

    # Progress tracking
    total_episodes = episodes_per_scenario * len(scenario_list) * len(bots)
    completed_episodes = 0
    start_time = time.time() if show_progress else None

    for bot_name, bot in bots.items():
        wins = 0
        losses = 0
        draws = 0

        # MULTI-SCENARIO: Iterate through all scenarios
        for scenario_file in scenario_list:
            scenario_name = os.path.basename(scenario_file).replace(f"{base_agent_key}_scenario_", "").replace(".json", "") if base_agent_key else "default"

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

                try:
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
                        gym_training_mode=True
                    )

                    # Connect step_logger if provided and enabled
                    if step_logger and step_logger.enabled:
                        base_env.step_logger = step_logger
                        # Set bot name for episode logging
                        step_logger.current_bot_name = bot_name

                    # Wrap with ActionMasker (CRITICAL for proper action masking)
                    def mask_fn(env):
                        return env.get_action_mask()

                    masked_env = ActionMasker(base_env, mask_fn)
                    bot_env = BotControlledEnv(masked_env, bot, unit_registry)

                    obs, info = bot_env.reset()
                    done = False
                    step_count = 0

                    # Calculate max_eval_steps from training_config
                    env_config = base_env.unwrapped.config if hasattr(base_env, 'unwrapped') else base_env.config
                    training_cfg = env_config.get('training_config', {})
                    max_turns = training_cfg.get('max_turns_per_episode', 5)

                    # Calculate expected steps per episode
                    steps_per_turn = 8
                    expected_max_steps = max_turns * steps_per_turn

                    # Add 100% buffer for slow/suboptimal play
                    max_eval_steps = expected_max_steps * 2

                    while not done and step_count < max_eval_steps:
                        action_masks = bot_env.engine.get_action_mask()
                        action, _ = model.predict(obs, action_masks=action_masks, deterministic=deterministic)

                        obs, reward, terminated, truncated, info = bot_env.step(action)
                        done = terminated or truncated
                        step_count += 1

                    # Determine winner - track wins/losses/draws
                    # CRITICAL FIX: Learning agent is ALWAYS Player 0, regardless of controlled_agent name
                    # controlled_agent is the agent key string (e.g., "SpaceMarine_phase1"), NOT a player ID
                    agent_player = 0  # Learning agent is always Player 0
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

                    bot_env.close()
                except Exception as e:
                    if show_progress:
                        print(f"\n⚠️  Episode error: {e}")
                    continue

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
                print(f"\n   📊 {bot_name.capitalize()}Bot: {avg_shoot_rate:.1f}% shoot rate ({avg_opportunities:.1f} opportunities/game)")
                print(f"   🤖 AI Agent:  {avg_ai_shoot_rate:.1f}% shoot rate ({avg_ai_opportunities:.1f} opportunities/game)")

    if show_progress:
        print("\r" + " " * 120)  # Clear the progress bar line
        print()  # New line after clearing

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
