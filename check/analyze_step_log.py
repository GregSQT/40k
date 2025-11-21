#!/usr/bin/env python3
"""
analyze_step_log.py - Analyze train_step.log and output compact statistics
Run this locally: python check/analyze_step_log.py train_step.log
"""

import sys
import re
from collections import defaultdict, Counter

def parse_log(filepath):
    """Parse train_step.log and extract statistics."""

    # Load wall hexes from board config
    wall_hexes = set()
    try:
        import json
        import os
        # Try to load from config/board_config.json
        board_config_path = os.path.join(os.path.dirname(filepath), 'config', 'board_config.json')
        if not os.path.exists(board_config_path):
            # Try relative to script location
            board_config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'board_config.json')
        if os.path.exists(board_config_path):
            with open(board_config_path, 'r') as f:
                board_config = json.load(f)
                wall_list = board_config.get('default', {}).get('wall_hexes', [])
                wall_hexes = set(tuple(w) for w in wall_list)
    except Exception as e:
        print(f"Warning: Could not load wall hexes from board_config.json: {e}")

    stats = {
        'total_episodes': 0,
        'total_actions': 0,
        'actions_by_type': Counter(),
        'actions_by_phase': Counter(),
        'actions_by_player': {0: Counter(), 1: Counter()},
        'shoot_vs_wait': {'shoot': 0, 'wait': 0, 'skip': 0},
        'turns_distribution': Counter(),
        'episode_lengths': [],
        'sample_games': {'win': None, 'loss': None, 'draw': None},
        'partial_shooting': {
            0: {'units_shot_once_no_kill': 0, 'total_shooting_activations': 0},
            1: {'units_shot_once_no_kill': 0, 'total_shooting_activations': 0}
        },
        'wait_by_phase': {
            0: {'move_wait': 0, 'shoot_wait': 0},
            1: {'move_wait': 0, 'shoot_wait': 0}
        },
        'shoot_vs_wait_by_player': {
            0: {'shoot': 0, 'wait': 0, 'skip': 0},
            1: {'shoot': 0, 'wait': 0, 'skip': 0}
        },
        'wall_collisions': {0: 0, 1: 0},
        # NEW: Target priority tracking
        'target_priority': {
            0: {'shots_at_damaged': 0, 'shots_at_full_hp_while_wounded_exists': 0, 'total_shots': 0},
            1: {'shots_at_damaged': 0, 'shots_at_full_hp_while_wounded_exists': 0, 'total_shots': 0}
        },
        # NEW: Enemy death order tracking
        'death_orders': [],  # List of death order tuples per episode
        'current_episode_deaths': [],  # Track deaths in current episode
        # Track enemy HP states by player (which player's enemies are damaged)
        'wounded_enemies': {0: set(), 1: set()}  # player -> set of wounded enemy unit IDs
    }

    current_episode = []
    current_episode_num = 0
    episode_turn = 0
    episode_actions = 0
    current_episode_shooting = {}  # Track shooting per unit per episode

    # Track unit HP for kill detection
    unit_hp = {}  # unit_id -> current HP
    unit_player = {}  # unit_id -> player (0 or 1)

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            # Skip header
            if line.startswith('===') or line.startswith('AI_TURN') or line.startswith('STEP') or line.startswith('NO STEP') or line.startswith('FAILED') or not line.strip():
                continue

            # Episode start
            if '=== EPISODE START ===' in line:
                if current_episode:
                    # Process previous episode's shooting data per player
                    for unit_key, unit_data in current_episode_shooting.items():
                        # Extract player from unit_key format: "T{turn}P{player}U{unit}"
                        player_id = int(unit_key.split('P')[1].split('U')[0])
                        stats['partial_shooting'][player_id]['total_shooting_activations'] += 1
                        # Check if unit shot only once without killing
                        if unit_data['shots'] == 1 and not unit_data['killed']:
                            stats['partial_shooting'][player_id]['units_shot_once_no_kill'] += 1

                    # Save death order for this episode
                    if stats['current_episode_deaths']:
                        stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                    # Save previous episode
                    stats['episode_lengths'].append(episode_actions)
                    stats['turns_distribution'][episode_turn] += 1

                current_episode = []
                current_episode_num += 1
                stats['total_episodes'] += 1
                episode_turn = 0
                episode_actions = 0
                current_episode_shooting = {}
                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {0: set(), 1: set()}  # Reset wounded tracking
                unit_hp = {}  # Reset HP tracking
                unit_player = {}  # Reset player tracking
                continue

            # Parse unit starting positions to get HP
            # Format: Unit 1 (Intercessor) P0: Starting position (9, 12)
            unit_start_match = re.match(r'.*Unit (\d+) \((\w+)\) P(\d+): Starting position', line)
            if unit_start_match:
                unit_id = unit_start_match.group(1)
                unit_type = unit_start_match.group(2)
                player = int(unit_start_match.group(3))
                # Set HP based on unit type
                if unit_type in ['Termagant', 'Hormagaunt', 'Genestealer']:
                    unit_hp[unit_id] = 1
                else:
                    unit_hp[unit_id] = 2  # Intercessor, etc.
                unit_player[unit_id] = player
                continue

            # Episode end
            if 'EPISODE END' in line:
                # Process final episode's shooting data before reset per player
                for unit_key, unit_data in current_episode_shooting.items():
                    # Extract player from unit_key format: "T{turn}P{player}U{unit}"
                    player_id = int(unit_key.split('P')[1].split('U')[0])
                    stats['partial_shooting'][player_id]['total_shooting_activations'] += 1
                    if unit_data['shots'] == 1 and not unit_data['killed']:
                        stats['partial_shooting'][player_id]['units_shot_once_no_kill'] += 1

                # Save death order for this episode
                if stats['current_episode_deaths']:
                    stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                # Extract winner
                winner_match = re.search(r'Winner=(-?\d+)', line)
                if winner_match:
                    winner = int(winner_match.group(1))

                    # Save sample games (first of each type)
                    if winner == 0 and not stats['sample_games']['win']:
                        stats['sample_games']['win'] = '\n'.join(current_episode[:30])  # First 30 lines
                    elif winner == 1 and not stats['sample_games']['loss']:
                        stats['sample_games']['loss'] = '\n'.join(current_episode[:30])
                    elif winner == -1 and not stats['sample_games']['draw']:
                        stats['sample_games']['draw'] = '\n'.join(current_episode[:30])

                current_episode_shooting = {}
                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {0: set(), 1: set()}
                continue

            # Parse action line: [timestamp] TX PX PHASE : Action [SUCCESS] [STEP: YES]
            match = re.match(r'\[.*?\] T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\] \[STEP: (YES|NO)\]', line)
            if match:
                turn = int(match.group(1))
                player = int(match.group(2))
                phase = match.group(3)
                action_desc = match.group(4)
                success = match.group(5) == 'SUCCESS'
                step_inc = match.group(6) == 'YES'

                episode_turn = max(episode_turn, turn)

                if step_inc:
                    stats['total_actions'] += 1
                    episode_actions += 1
                    stats['actions_by_phase'][phase] += 1

                    # Determine action type
                    if 'shoots' in action_desc.lower() or 'shot' in action_desc.lower():
                        action_type = 'shoot'
                        stats['shoot_vs_wait']['shoot'] += 1
                        stats['shoot_vs_wait_by_player'][player]['shoot'] += 1

                        # Extract target unit ID and check HP state
                        # Format: "Unit X(col, row) SHOT at unit Y" or similar
                        target_match = re.search(r'SHOT at unit (\d+)|shoots Unit (\d+)|→ Unit (\d+)', action_desc, re.IGNORECASE)
                        if target_match:
                            target_id = target_match.group(1) or target_match.group(2) or target_match.group(3)

                            stats['target_priority'][player]['total_shots'] += 1

                            # Check if target was already wounded
                            if target_id in stats['wounded_enemies'][player]:
                                # Good: shooting at a wounded enemy
                                stats['target_priority'][player]['shots_at_damaged'] += 1
                            else:
                                # Shooting at full HP enemy - check if there's a wounded enemy available
                                if len(stats['wounded_enemies'][player]) > 0:
                                    # Bad: shooting full HP while wounded enemies exist
                                    stats['target_priority'][player]['shots_at_full_hp_while_wounded_exists'] += 1

                            # Check for damage in the action description
                            damage_match = re.search(r'Dmg:(\d+)', action_desc)
                            killed = False
                            if damage_match:
                                damage = int(damage_match.group(1))
                                if damage > 0:
                                    # Apply damage to tracked HP
                                    if target_id in unit_hp:
                                        unit_hp[target_id] -= damage
                                        if unit_hp[target_id] <= 0:
                                            killed = True
                                        else:
                                            # Mark this unit as wounded (but not dead)
                                            stats['wounded_enemies'][player].add(target_id)

                            # Track death order and remove from wounded
                            if killed:
                                # Record which player killed which unit
                                stats['current_episode_deaths'].append((player, target_id))
                                # Remove from wounded set since it's dead
                                stats['wounded_enemies'][player].discard(target_id)

                        # Extract unit ID for partial shooting detection
                        unit_match = re.search(r'Unit (\d+)', action_desc)
                        if unit_match and phase == 'SHOOT':
                            unit_id = f"T{turn}P{player}U{unit_match.group(1)}"

                            # Initialize tracking for this unit in this turn
                            if unit_id not in current_episode_shooting:
                                current_episode_shooting[unit_id] = {'shots': 0, 'killed': False}

                            current_episode_shooting[unit_id]['shots'] += 1
                            if killed:
                                current_episode_shooting[unit_id]['killed'] = True

                    elif 'wait' in action_desc.lower():
                        action_type = 'wait'
                        stats['shoot_vs_wait']['wait'] += 1
                        stats['shoot_vs_wait_by_player'][player]['wait'] += 1

                        # Track waits by phase (MOVE or SHOOT)
                        if phase == 'SHOOT':
                            stats['wait_by_phase'][player]['shoot_wait'] += 1
                        elif phase == 'MOVE':
                            stats['wait_by_phase'][player]['move_wait'] += 1

                            # Also track unit that waited (counts as activation)
                            unit_match = re.search(r'Unit (\d+)', action_desc)
                            if unit_match:
                                unit_id = f"T{turn}P{player}U{unit_match.group(1)}"
                                # If unit waited, mark it (it might have shot before waiting)
                                if unit_id not in current_episode_shooting:
                                    # Unit waited without shooting at all - don't count as partial shooting
                                    pass
                                # If unit already shot, it will be counted in partial shooting check

                    elif 'skip' in action_desc.lower():
                        action_type = 'skip'
                        stats['shoot_vs_wait']['skip'] += 1
                        stats['shoot_vs_wait_by_player'][player]['skip'] += 1
                    elif 'moves' in action_desc.lower() or 'moved' in action_desc.lower():
                        action_type = 'move'

                        # Check if unit moved into a wall
                        # Format: "Unit X(col, row) MOVED from (col, row) to (col, row)"
                        move_match = re.search(r'Unit \d+\((\d+), (\d+)\)', action_desc)
                        if move_match and phase == 'MOVE':
                            dest_col = int(move_match.group(1))
                            dest_row = int(move_match.group(2))
                            if (dest_col, dest_row) in wall_hexes:
                                stats['wall_collisions'][player] += 1
                    elif 'charge' in action_desc.lower():
                        action_type = 'charge'
                    elif 'fight' in action_desc.lower() or 'combat' in action_desc.lower():
                        action_type = 'fight'
                    else:
                        action_type = 'other'

                    stats['actions_by_type'][action_type] += 1
                    stats['actions_by_player'][player][action_type] += 1

                current_episode.append(line.strip())

    return stats

def print_statistics(stats):
    """Print formatted statistics."""
    print("=" * 80)
    print("TRAIN_STEP.LOG ANALYSIS")
    print("=" * 80)
    print(f"\nTotal Episodes: {stats['total_episodes']}")
    print(f"Total Actions (with step increment): {stats['total_actions']}")

    if stats['episode_lengths']:
        avg_length = sum(stats['episode_lengths']) / len(stats['episode_lengths'])
        print(f"Average Actions per Episode: {avg_length:.1f}")
        print(f"Min/Max Actions per Episode: {min(stats['episode_lengths'])}/{max(stats['episode_lengths'])}")

    print("\n" + "-" * 80)
    print("TURN DISTRIBUTION")
    print("-" * 80)
    for turn in sorted(stats['turns_distribution'].keys()):
        count = stats['turns_distribution'][turn]
        pct = (count / stats['total_episodes'] * 100) if stats['total_episodes'] > 0 else 0
        print(f"Turn {turn}: {count:3d} games ({pct:5.1f}%)")

    print("\n" + "-" * 80)
    print("ACTIONS BY TYPE")
    print("-" * 80)
    for action_type, count in stats['actions_by_type'].most_common():
        pct = (count / stats['total_actions'] * 100) if stats['total_actions'] > 0 else 0
        print(f"{action_type:10s}: {count:5d} ({pct:5.1f}%)")

    print("\n" + "-" * 80)
    print("SHOOTING PHASE BEHAVIOR")
    print("-" * 80)
    shoot_total = stats['shoot_vs_wait']['shoot'] + stats['shoot_vs_wait']['wait'] + stats['shoot_vs_wait']['skip']
    if shoot_total > 0:
        print(f"Shoot:   {stats['shoot_vs_wait']['shoot']:5d} ({stats['shoot_vs_wait']['shoot']/shoot_total*100:5.1f}%)")
        print(f"Wait:    {stats['shoot_vs_wait']['wait']:5d} ({stats['shoot_vs_wait']['wait']/shoot_total*100:5.1f}%)")
        print(f"Skip:    {stats['shoot_vs_wait']['skip']:5d} ({stats['shoot_vs_wait']['skip']/shoot_total*100:5.1f}%)")

    # Partial shooting statistics per player
    print("\n" + "-" * 80)
    print("PARTIAL SHOOTING ANALYSIS")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print("-" * 80)
    for player in [0, 1]:
        total_act = stats['partial_shooting'][player]['total_shooting_activations']
        partial = stats['partial_shooting'][player]['units_shot_once_no_kill']
        pct = (partial / total_act * 100) if total_act > 0 else 0
        player_label = 'Agent (P0)' if player == 0 else 'Bot (P1)'
        if player == 0:
            print(f"Shot once, no kill:           {partial:6d} ({pct:5.1f}%)  ", end='')
        else:
            print(f"{partial:6d} ({pct:5.1f}%)")

    agent_total = stats['partial_shooting'][0]['total_shooting_activations']
    bot_total = stats['partial_shooting'][1]['total_shooting_activations']
    print(f"Total shooting activations:   {agent_total:6d}           {bot_total:6d}")

    # WAIT behavior separated by phase
    print("\n" + "-" * 80)
    print("WAIT BEHAVIOR BY PHASE")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print("-" * 80)
    agent_move_wait = stats['wait_by_phase'][0]['move_wait']
    bot_move_wait = stats['wait_by_phase'][1]['move_wait']
    agent_shoot_wait = stats['wait_by_phase'][0]['shoot_wait']
    bot_shoot_wait = stats['wait_by_phase'][1]['shoot_wait']
    print(f"MOVE phase waits:             {agent_move_wait:6d}           {bot_move_wait:6d}")
    print(f"SHOOT phase waits:            {agent_shoot_wait:6d}           {bot_shoot_wait:6d}")

    # Target priority analysis
    print("\n" + "-" * 80)
    print("TARGET PRIORITY ANALYSIS")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print("-" * 80)

    # Shots at damaged enemy
    agent_damaged = stats['target_priority'][0]['shots_at_damaged']
    bot_damaged = stats['target_priority'][1]['shots_at_damaged']
    agent_total = stats['target_priority'][0]['total_shots']
    bot_total = stats['target_priority'][1]['total_shots']

    agent_pct = (agent_damaged / agent_total * 100) if agent_total > 0 else 0
    bot_pct = (bot_damaged / bot_total * 100) if bot_total > 0 else 0
    print(f"Shots at wounded enemy:       {agent_damaged:6d} ({agent_pct:5.1f}%)  {bot_damaged:6d} ({bot_pct:5.1f}%)")

    # Shots at full HP while wounded exists (BAD behavior)
    agent_bad = stats['target_priority'][0]['shots_at_full_hp_while_wounded_exists']
    bot_bad = stats['target_priority'][1]['shots_at_full_hp_while_wounded_exists']

    agent_bad_pct = (agent_bad / agent_total * 100) if agent_total > 0 else 0
    bot_bad_pct = (bot_bad / bot_total * 100) if bot_total > 0 else 0
    print(f"Shots at full HP (bad):       {agent_bad:6d} ({agent_bad_pct:5.1f}%)  {bot_bad:6d} ({bot_bad_pct:5.1f}%)")
    print(f"  (while wounded enemy exists)")

    print(f"Total shots:                  {agent_total:6d}           {bot_total:6d}")

    # Death order analysis
    print("\n" + "-" * 80)
    print("ENEMY DEATH ORDER ANALYSIS")
    print("-" * 80)

    if stats['death_orders']:
        # Count how often each death order pattern occurs
        death_order_counter = Counter()
        for death_order in stats['death_orders']:
            # Extract just the unit IDs in order
            units_killed = tuple(unit_id for player, unit_id in death_order)
            if units_killed:
                death_order_counter[units_killed] += 1

        # Show most common death orders
        print(f"Total episodes with kills: {len(stats['death_orders'])}")
        print(f"\nMost common death orders (unit IDs):")
        for order, count in death_order_counter.most_common(10):
            pct = (count / len(stats['death_orders']) * 100)
            order_str = " → ".join(order)
            print(f"  {order_str}: {count} times ({pct:.1f}%)")

        # Also show who killed whom
        print(f"\nKills by player:")
        player_kills = {0: 0, 1: 0}
        for death_order in stats['death_orders']:
            for player, unit_id in death_order:
                player_kills[player] += 1
        print(f"  Agent (P0) kills: {player_kills[0]}")
        print(f"  Bot (P1) kills:   {player_kills[1]}")
    else:
        print("No kills recorded in any episode.")

    # Wall collision detection
    print("\n" + "-" * 80)
    print("MOVEMENT ERRORS")
    print("-" * 80)
    agent_walls = stats['wall_collisions'][0]
    bot_walls = stats['wall_collisions'][1]
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print(f"Moves into walls:             {agent_walls:6d}           {bot_walls:6d}")

    print("\n" + "-" * 80)
    print("ACTIONS BY PLAYER")
    print("-" * 80)
    for player in [0, 1]:
        print(f"\nPlayer {player} ({'Agent' if player == 0 else 'Bot'}):")
        player_total = sum(stats['actions_by_player'][player].values())
        for action_type, count in stats['actions_by_player'][player].most_common():
            pct = (count / player_total * 100) if player_total > 0 else 0
            print(f"  {action_type:10s}: {count:5d} ({pct:5.1f}%)")

    print("\n" + "=" * 80)
    print("SAMPLE GAMES (first 30 actions)")
    print("=" * 80)

    if stats['sample_games']['win']:
        print("\n--- AGENT WIN GAME ---")
        print(stats['sample_games']['win'])

    if stats['sample_games']['loss']:
        print("\n--- AGENT LOSS GAME ---")
        print(stats['sample_games']['loss'])

    if stats['sample_games']['draw']:
        print("\n--- DRAW GAME (most common) ---")
        print(stats['sample_games']['draw'])

    print("\n" + "=" * 80)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python check/analyze_step_log.py train_step.log")
        sys.exit(1)

    log_file = sys.argv[1]
    print(f"Analyzing {log_file}...")

    try:
        stats = parse_log(log_file)
        print_statistics(stats)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
