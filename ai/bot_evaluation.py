#!/usr/bin/env python3
"""
ai/bot_evaluation.py - Bot evaluation functionality

Contains:
- evaluate_against_bots: Standalone bot evaluation function for all bot testing

Extracted from ai/train.py during refactoring (2025-01-21)
"""

__all__ = ['evaluate_against_bots']


def evaluate_against_bots(model, training_config_name, rewards_config_name, n_episodes,
                         controlled_agent=None, show_progress=False, deterministic=True):
    """
    Standalone bot evaluation function - single source of truth for all bot testing.

    Args:
        model: Trained model to evaluate
        training_config_name: Name of training config to use (e.g., "phase1", "default")
        n_episodes: Number of episodes per bot (will be split across all available scenarios)
        controlled_agent: Agent identifier (None for player 0, otherwise player 1)
        show_progress: Show progress bar with time estimates
        deterministic: Use deterministic policy

    Returns:
        Dict with keys: 'random', 'greedy', 'defensive', 'combined',
                       'random_wins', 'greedy_wins', 'defensive_wins'
    """
    # Lazy imports to avoid circular dependencies
    from ai.env_wrappers import BotControlledEnv
    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader
    import time

    # Import evaluation bots - these are optional dependencies
    try:
        from ai.bots.random_bot import RandomBot
        from ai.bots.greedy_bot import GreedyBot
        from ai.bots.defensive_bot import DefensiveBot
        EVALUATION_BOTS_AVAILABLE = True
    except ImportError:
        EVALUATION_BOTS_AVAILABLE = False

    # Import scenario utilities from train.py
    from ai.train import get_scenario_list_for_phase, get_agent_scenario_file

    if not EVALUATION_BOTS_AVAILABLE:
        return {}

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
    total_episodes = episodes_per_scenario * len(scenario_list)

    print(f"\n🎯 Bot Evaluation Configuration:")
    print(f"   Agent: {controlled_agent or 'Player 0'}")
    print(f"   Training Config: {training_config_name}")
    print(f"   Scenarios: {len(scenario_list)} found")
    print(f"   Episodes per bot: {total_episodes} ({episodes_per_scenario} per scenario)")
    print(f"   Deterministic: {deterministic}")

    # Initialize tracking
    total_random_wins = 0
    total_greedy_wins = 0
    total_defensive_wins = 0
    total_random_episodes = 0
    total_greedy_episodes = 0
    total_defensive_episodes = 0

    # Evaluate across all scenarios
    from tqdm import tqdm
    scenario_bar = tqdm(scenario_list, desc="Scenarios", disable=not show_progress, leave=False)

    for scenario_idx, scenario_file in enumerate(scenario_bar):
        scenario_name = scenario_file.split('/')[-1].replace('.json', '')
        scenario_bar.set_postfix_str(f"Scenario: {scenario_name}")

        # Inner loop: Evaluate each bot
        for bot_name, bot in bots.items():
            unit_registry = UnitRegistry(config)

            # Create evaluation environment with this bot
            # Lazy import of make_training_env from train.py
            from ai.train import make_training_env
            base_env = make_training_env(
                scenario_file=scenario_file,
                rewards_config_name=rewards_config_name,
                controlled_agent=controlled_agent,
                unit_registry=unit_registry,
                enable_action_masking=True
            )()
            env = BotControlledEnv(base_env, bot, unit_registry)

            # Run episodes
            wins = 0
            shoot_stats_list = []
            bot_bar = tqdm(
                range(episodes_per_scenario),
                desc=f"{bot_name.capitalize()} ({scenario_name[:20]})",
                disable=not show_progress,
                leave=False
            )

            for ep_num in bot_bar:
                obs, info = env.reset()
                done = False
                total_reward = 0
                step_count = 0

                # Calculate max_eval_steps from training_config for safety
                # Use reasonable default: 5 turns * 8 steps/turn * 2 buffer = 80 steps
                max_eval_steps = 80

                while not done and step_count < max_eval_steps:
                    # CRITICAL: Get action mask for MaskablePPO
                    action_masks = env.engine.get_action_mask()
                    action, _ = model.predict(obs, action_masks=action_masks, deterministic=deterministic)
                    obs, reward, terminated, truncated, info = env.step(action)
                    total_reward += reward
                    done = terminated or truncated
                    step_count += 1

                # Check if agent won (Player 0 if controlled_agent is None, else Player 1)
                winner = info.get("winner", -1)
                expected_winner = 1 if controlled_agent else 0

                if winner == expected_winner:
                    wins += 1

                # DIAGNOSTIC: Collect shoot stats from each episode
                bot_stats = env.get_shoot_stats()
                shoot_stats_list.append(bot_stats)

                # Update progress bar
                current_wr = (wins / (ep_num + 1)) * 100
                bot_bar.set_postfix_str(f"WR: {current_wr:.1f}%")

            env.close()

            # Store shoot stats for this bot
            if f'{bot_name}_shoot_stats' not in results:
                results[f'{bot_name}_shoot_stats'] = []
            results[f'{bot_name}_shoot_stats'].extend(shoot_stats_list)

            # Accumulate results across scenarios
            if bot_name == 'random':
                total_random_wins += wins
                total_random_episodes += episodes_per_scenario
            elif bot_name == 'greedy':
                total_greedy_wins += wins
                total_greedy_episodes += episodes_per_scenario
            elif bot_name == 'defensive':
                total_defensive_wins += wins
                total_defensive_episodes += episodes_per_scenario

    # Calculate final win rates
    results['random'] = (total_random_wins / total_random_episodes * 100) if total_random_episodes > 0 else 0
    results['greedy'] = (total_greedy_wins / total_greedy_episodes * 100) if total_greedy_episodes > 0 else 0
    results['defensive'] = (total_defensive_wins / total_defensive_episodes * 100) if total_defensive_episodes > 0 else 0
    results['combined'] = (results['random'] + results['greedy'] + results['defensive']) / 3

    # Add raw win counts
    results['random_wins'] = total_random_wins
    results['greedy_wins'] = total_greedy_wins
    results['defensive_wins'] = total_defensive_wins

    print(f"\n📊 Bot Evaluation Results ({total_episodes} episodes per bot):")
    print(f"   Random:     {results['random']:5.1f}% ({total_random_wins}/{total_random_episodes} wins)")
    print(f"   Greedy:     {results['greedy']:5.1f}% ({total_greedy_wins}/{total_greedy_episodes} wins)")
    print(f"   Defensive:  {results['defensive']:5.1f}% ({total_defensive_wins}/{total_defensive_episodes} wins)")
    print(f"   Combined:   {results['combined']:5.1f}%\n")

    # DIAGNOSTIC: Print shoot statistics for each bot
    if show_progress:
        print("="*80)
        print("📊 DIAGNOSTIC: Shoot Phase Behavior")
        print("="*80)
        for bot_name in ['random', 'greedy', 'defensive']:
            stats_key = f'{bot_name}_shoot_stats'
            if stats_key in results and results[stats_key]:
                stats_list = results[stats_key]
                avg_opportunities = sum(s['shoot_opportunities'] for s in stats_list) / len(stats_list)
                avg_shoot_rate = sum(s['shoot_rate'] for s in stats_list) / len(stats_list)

                avg_ai_opportunities = sum(s['ai_shoot_opportunities'] for s in stats_list) / len(stats_list)
                avg_ai_shoot_rate = sum(s['ai_shoot_rate'] for s in stats_list) / len(stats_list)

                print(f"\n   📊 {bot_name.capitalize()}Bot: {avg_shoot_rate:.1f}% shoot rate ({avg_opportunities:.1f} opportunities/game)")
                print(f"   🤖 AI Agent:  {avg_ai_shoot_rate:.1f}% shoot rate ({avg_ai_opportunities:.1f} opportunities/game)")
        print("="*80 + "\n")

    return results
