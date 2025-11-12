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
        'wait_in_shoot_phase': {0: 0, 1: 0},
        'shoot_vs_wait_by_player': {
            0: {'shoot': 0, 'wait': 0, 'skip': 0},
            1: {'shoot': 0, 'wait': 0, 'skip': 0}
        },
        'wall_collisions': {0: 0, 1: 0}
    }
    
    current_episode = []
    current_episode_num = 0
    episode_turn = 0
    episode_actions = 0
    current_episode_shooting = {}  # Track shooting per unit per episode
    
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
                    
                    # Save previous episode
                    stats['episode_lengths'].append(episode_actions)
                    stats['turns_distribution'][episode_turn] += 1
                
                current_episode = []
                current_episode_num += 1
                stats['total_episodes'] += 1
                episode_turn = 0
                episode_actions = 0
                current_episode_shooting = {}
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
                        
                        # Track if this shot killed anyone
                        killed = 'KILLED' in action_desc or 'Dmg:2HP' in action_desc
                        
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
                        
                        # Track waits specifically in SHOOT phase by player
                        if phase == 'SHOOT':
                            stats['wait_in_shoot_phase'][player] += 1
                            
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
    
    # NEW: Partial shooting statistics per player
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
    
    # NEW: Wait in shoot phase per player
    print("\n" + "-" * 80)
    print("WAIT BEHAVIOR IN SHOOT PHASE")
    print("-" * 80)
    agent_waits = stats['wait_in_shoot_phase'][0]
    bot_waits = stats['wait_in_shoot_phase'][1]
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print(f"Units choosing WAIT:          {agent_waits:6d}           {bot_waits:6d}")
    
    # NEW: Wall collision detection
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