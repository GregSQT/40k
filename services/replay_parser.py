#!/usr/bin/env python3
"""
replay_parser.py - Parse train_step.log into replay JSON format

Converts training logs into a format suitable for visual replay with:
- Episode boundaries
- Game state snapshots after each action
- Full action details
"""

import json
import re
from typing import Dict, List, Any, Tuple


def parse_train_log_to_episodes(log_path: str) -> List[Dict[str, Any]]:
    """
    Parse train_step.log into separate episodes with all actions and states.

    Returns:
        List of episode dictionaries, each containing:
        - episode_num: Episode number
        - actions: List of all actions in order
        - initial_positions: Starting positions of all units
        - final_result: Win/loss/draw
    """
    episodes = []
    current_episode = None

    with open(log_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Episode start - matches both "=== EPISODE START ===" and "=== EPISODE 1 START ==="
            if "=== EPISODE" in line and "START ===" in line:
                if current_episode:
                    episodes.append(current_episode)

                current_episode = {
                    'episode_num': len(episodes) + 1,
                    'actions': [],
                    'units': {},  # unit_id -> {col, row, player, type}
                    'initial_positions': {},
                    'final_result': None,
                    'scenario': 'Unknown'
                }
                continue

            if not current_episode:
                continue

            # Scenario name
            scenario_match = re.search(r'Scenario: (.+)', line)
            if scenario_match:
                current_episode['scenario'] = scenario_match.group(1)
                continue

            # Unit starting positions
            unit_start = re.search(r'Unit (\d+) \((.+?)\) P(\d+): Starting position \((\d+), (\d+)\)', line)
            if unit_start:
                unit_id = int(unit_start.group(1))
                unit_type = unit_start.group(2)
                player = int(unit_start.group(3))
                col = int(unit_start.group(4))
                row = int(unit_start.group(5))

                current_episode['units'][unit_id] = {
                    'id': unit_id,
                    'type': unit_type,
                    'player': player,
                    'col': col,
                    'row': row,
                    'HP_CUR': 2,  # Default Intercessor HP
                    'HP_MAX': 2
                }
                current_episode['initial_positions'][unit_id] = {'col': col, 'row': row}
                continue

            # Actions start marker
            if "=== ACTIONS START ===" in line:
                continue

            # Parse MOVE actions
            move_match = re.search(
                r'\[([^\]]+)\] (T\d+) P(\d+) MOVE : Unit (\d+)\((\d+),(\d+)\) (MOVED|WAIT)',
                line
            )
            # Debug: log lines that contain MOVE but don't match
            if "MOVE" in line and not move_match:
                print(f"DEBUG: MOVE line didn't match regex: {line[:100]}")
            if move_match:
                timestamp = move_match.group(1)
                turn = move_match.group(2)
                player = int(move_match.group(3))
                unit_id = int(move_match.group(4))
                end_col = int(move_match.group(5))
                end_row = int(move_match.group(6))
                action_type = move_match.group(7)

                if action_type == "MOVED":
                    # Extract from position
                    from_match = re.search(r'from \((\d+),(\d+)\)', line)
                    if from_match:
                        from_col = int(from_match.group(1))
                        from_row = int(from_match.group(2))
                    else:
                        # Use current position if unit exists, otherwise use end position
                        if unit_id in current_episode['units']:
                            from_col = current_episode['units'][unit_id]['col']
                            from_row = current_episode['units'][unit_id]['row']
                        else:
                            # Unit not initialized yet - use end position as fallback
                            from_col = end_col
                            from_row = end_row

                    current_episode['actions'].append({
                        'type': 'move',
                        'timestamp': timestamp,
                        'turn': turn,
                        'player': player,
                        'unit_id': unit_id,
                        'from': {'col': from_col, 'row': from_row},
                        'to': {'col': end_col, 'row': end_row}
                    })
                    # Debug: only log first 5 and last 5 moves per episode, with episode/turn info
                    episode_num = current_episode.get('episode_num', '?')
                    move_count = len([a for a in current_episode['actions'] if a['type'] == 'move'])
                    if move_count <= 5 or move_count > len([a for a in current_episode['actions'] if a['type'] == 'move']) - 5:
                        print(f"DEBUG: E{episode_num} {turn} P{player} - Unit {unit_id}: from ({from_col},{from_row}) to ({end_col},{end_row})")

                    # Update unit position (create entry if doesn't exist)
                    if unit_id not in current_episode['units']:
                        current_episode['units'][unit_id] = {
                            'id': unit_id,
                            'type': 'Unknown',
                            'player': player,
                            'col': end_col,
                            'row': end_row,
                            'HP_CUR': 2,
                            'HP_MAX': 2
                        }
                    else:
                        current_episode['units'][unit_id]['col'] = end_col
                        current_episode['units'][unit_id]['row'] = end_row

                elif action_type == "WAIT":
                    current_episode['actions'].append({
                        'type': 'move_wait',
                        'timestamp': timestamp,
                        'turn': turn,
                        'player': player,
                        'unit_id': unit_id,
                        'pos': {'col': end_col, 'row': end_row}
                    })
                continue

            # Parse SHOOT actions
            shoot_match = re.search(
                r'\[([^\]]+)\] (T\d+) P(\d+) SHOOT : Unit (\d+)\((\d+), (\d+)\) (SHOT at unit|WAIT)',
                line
            )
            if shoot_match:
                timestamp = shoot_match.group(1)
                turn = shoot_match.group(2)
                player = int(shoot_match.group(3))
                shooter_id = int(shoot_match.group(4))
                shooter_col = int(shoot_match.group(5))
                shooter_row = int(shoot_match.group(6))
                action_type = shoot_match.group(7)

                if action_type == "SHOT at unit":
                    # Extract target and damage
                    target_match = re.search(r'SHOT at unit (\d+)', line)
                    damage_match = re.search(r'Dmg:(\d+)HP', line)
                    hit_match = re.search(r'Hit:(\d+)\+:(\d+)\((HIT|MISS)\)', line)

                    if target_match:
                        target_id = int(target_match.group(1))
                        damage = int(damage_match.group(1)) if damage_match else 0

                        action = {
                            'type': 'shoot',
                            'timestamp': timestamp,
                            'turn': turn,
                            'player': player,
                            'shooter_id': shooter_id,
                            'shooter_pos': {'col': shooter_col, 'row': shooter_row},
                            'target_id': target_id,
                            'damage': damage
                        }

                        # Add hit result if available
                        if hit_match:
                            action['hit_result'] = hit_match.group(3)

                        current_episode['actions'].append(action)

                        # Update target HP
                        if damage > 0 and target_id in current_episode['units']:
                            current_episode['units'][target_id]['HP_CUR'] -= damage
                            if current_episode['units'][target_id]['HP_CUR'] <= 0:
                                current_episode['units'][target_id]['HP_CUR'] = 0

                elif action_type == "WAIT":
                    current_episode['actions'].append({
                        'type': 'shoot_wait',
                        'timestamp': timestamp,
                        'turn': turn,
                        'player': player,
                        'unit_id': shooter_id,
                        'pos': {'col': shooter_col, 'row': shooter_row}
                    })
                continue

            # Episode end
            if "=== EPISODE END ===" in line or "Episode result:" in line:
                # Try to extract result
                result_match = re.search(r'Episode result: (.+)', line)
                if result_match:
                    result = result_match.group(1).strip()
                    if 'WIN' in result.upper():
                        current_episode['final_result'] = 'win'
                    elif 'LOSS' in result.upper() or 'LOSE' in result.upper():
                        current_episode['final_result'] = 'loss'
                    else:
                        current_episode['final_result'] = 'draw'

    # Add last episode
    if current_episode and current_episode['actions']:
        episodes.append(current_episode)

    # Debug: count move actions per episode
    total_moves = 0
    for ep in episodes:
        ep_moves = len([a for a in ep['actions'] if a['type'] == 'move'])
        total_moves += ep_moves
        if ep_moves > 0:
            print(f"DEBUG: Episode {ep['episode_num']}: {ep_moves} move actions")
    print(f"DEBUG: Total move actions across all episodes: {total_moves}")

    return episodes


def episode_to_replay_format(episode: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert parsed episode to replay JSON format.

    Returns:
        {
            "episode_num": 1,
            "scenario": "scenario name",
            "initial_state": {units, board},
            "actions": [...],
            "states": [...]  // Game state after each action
        }
    """
    # Build initial state
    initial_state = {
        'units': list(episode['units'].values()),
        'currentTurn': 1,
        'currentPlayer': 0,
        'phase': 'move'
    }

    # Build states array (state after each action)
    states = []
    current_units = {uid: dict(unit) for uid, unit in episode['units'].items()}

    for action in episode['actions']:
        # Apply action to units
        if action['type'] == 'move':
            unit_id = action['unit_id']
            if unit_id in current_units:
                current_units[unit_id]['col'] = action['to']['col']
                current_units[unit_id]['row'] = action['to']['row']

        elif action['type'] == 'shoot':
            target_id = action['target_id']
            if target_id in current_units and action['damage'] > 0:
                current_units[target_id]['HP_CUR'] -= action['damage']
                if current_units[target_id]['HP_CUR'] < 0:
                    current_units[target_id]['HP_CUR'] = 0

        # Snapshot current state
        states.append({
            'units': [dict(u) for u in current_units.values()],
            'action': action
        })

    return {
        'episode_num': episode['episode_num'],
        'scenario': episode['scenario'],
        'initial_state': initial_state,
        'actions': episode['actions'],
        'states': states,
        'total_actions': len(episode['actions']),
        'final_result': episode['final_result']
    }


def parse_log_file(log_path: str) -> Dict[str, Any]:
    """
    Main function to parse log file into full replay data.

    Returns:
        {
            "total_episodes": N,
            "episodes": [...]
        }
    """
    episodes = parse_train_log_to_episodes(log_path)

    return {
        'total_episodes': len(episodes),
        'episodes': [episode_to_replay_format(ep) for ep in episodes]
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python replay_parser.py <train_step.log>")
        sys.exit(1)

    log_file = sys.argv[1]
    result = parse_log_file(log_file)

    print(f"Parsed {result['total_episodes']} episodes")

    # Save to JSON
    output_file = log_file.replace('.log', '_replay.json')
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Saved to: {output_file}")
