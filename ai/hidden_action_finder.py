#!/usr/bin/env python3
"""
Script de vérification des logs pour détecter :
1. Mouvements faits mais non logués dans step.log
2. Attaques faites mais non loguées dans step.log
3. Attaques qui auraient dû être faites en phase fight mais ne l'ont pas été
"""

import re
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set, Optional

def parse_position_changes(movement_log: str) -> List[Dict]:
    """Parse [POSITION CHANGE] logs from debug.log"""
    position_changes = []
    pattern = r'\[POSITION CHANGE\] E(\d+) T(\d+) (\w+) Unit (\d+): \((\d+),(\d+)\)→\((\d+),(\d+)\) via (\w+)'
    
    for line in movement_log.split('\n'):
        match = re.search(pattern, line)
        if match:
            episode, turn, phase, unit_id, from_col, from_row, to_col, to_row, change_type = match.groups()
            position_changes.append({
                'episode': int(episode),
                'turn': int(turn),
                'phase': phase,
                'unit_id': unit_id,
                'from': (int(from_col), int(from_row)),
                'to': (int(to_col), int(to_row)),
                'type': change_type,
                'line': line
            })
    
    return position_changes

def parse_attacks_from_debug(movement_log: str) -> List[Dict]:
    """Parse attack_executed logs from debug.log"""
    attacks = []
    
    # FIGHT attacks
    fight_pattern = r'\[FIGHT DEBUG\] E(\d+) T(\d+) fight attack_executed: Unit (\d+) -> Unit (\d+) damage=(\d+) target_died=(True|False)'
    for line in movement_log.split('\n'):
        match = re.search(fight_pattern, line)
        if match:
            episode, turn, attacker, target, damage, target_died = match.groups()
            attacks.append({
                'episode': int(episode),
                'turn': int(turn),
                'phase': 'fight',
                'attacker': attacker,
                'target': target,
                'damage': int(damage),
                'target_died': target_died == 'True',
                'line': line
            })
    
    # SHOOT attacks
    shoot_pattern = r'\[SHOOT DEBUG\] E(\d+) T(\d+) shoot attack_executed: Unit (\d+) -> Unit (\d+) damage=(\d+) target_died=(True|False)'
    for line in movement_log.split('\n'):
        match = re.search(shoot_pattern, line)
        if match:
            episode, turn, attacker, target, damage, target_died = match.groups()
            attacks.append({
                'episode': int(episode),
                'turn': int(turn),
                'phase': 'shoot',
                'attacker': attacker,
                'target': target,
                'damage': int(damage),
                'target_died': target_died == 'True',
                'line': line
            })
    
    return attacks

def parse_episodes_from_step(step_log: str) -> Dict[int, int]:
    """Parse episode boundaries from step.log and return line -> episode mapping
    Uses EPISODE START markers in priority (with explicit episode numbers),
    but also uses EPISODE END markers to correctly determine episode boundaries
    """
    episode_map = {}
    lines = step_log.split('\n')
    
    # First pass: find all EPISODE START markers (PRIORITY - they have explicit episode numbers)
    episode_starts = {}
    for line_num, line in enumerate(lines, 1):
        if '=== EPISODE' in line and 'START ===' in line:
            match = re.search(r'EPISODE (\d+)', line)
            if match:
                episode_num = int(match.group(1))
                episode_starts[line_num] = episode_num
    
    # Second pass: find all EPISODE END markers
    episode_ends = {}
    for line_num, line in enumerate(lines, 1):
        if 'EPISODE END' in line:
            episode_ends[line_num] = None  # We don't know episode number from END marker
    
    # Use EPISODE START markers if they exist (they have explicit episode numbers)
    if episode_starts:
        sorted_starts = sorted(episode_starts.items())
        sorted_ends = sorted(episode_ends.keys())
        
        # Lines before first EPISODE START get the first episode number
        first_episode_line = sorted_starts[0][0]
        first_episode = sorted_starts[0][1]
        for line_num in range(1, first_episode_line):
            episode_map[line_num] = first_episode
        
        # Assign episodes based on EPISODE START markers, but respect EPISODE END boundaries
        for i, (start_line, episode) in enumerate(sorted_starts):
            # Find the next EPISODE START or use end of file
            next_start_line = sorted_starts[i + 1][0] if i + 1 < len(sorted_starts) else len(lines) + 1
            
            # Find the EPISODE END for this episode (should be before next_start_line)
            # EPISODE END marks the end of the previous episode, so actions after EPISODE END
            # but before next EPISODE START belong to the next episode
            episode_end_line = None
            for end_line in sorted_ends:
                if start_line <= end_line < next_start_line:
                    episode_end_line = end_line
                    break
            
            # If we found an EPISODE END, actions after it belong to next episode
            # Otherwise, all lines from start_line to next_start_line belong to this episode
            if episode_end_line and episode_end_line < next_start_line:
                # Lines from start_line to episode_end_line belong to this episode
                for line_num in range(start_line, episode_end_line + 1):
                    episode_map[line_num] = episode
                # Lines after episode_end_line but before next_start_line belong to next episode
                # (if next episode exists)
                if i + 1 < len(sorted_starts):
                    next_episode = sorted_starts[i + 1][1]
                    for line_num in range(episode_end_line + 1, next_start_line):
                        episode_map[line_num] = next_episode
            else:
                # No EPISODE END found, assign all lines to this episode
                for line_num in range(start_line, next_start_line):
                    episode_map[line_num] = episode
    else:
        # Fallback: use EPISODE END markers if START markers don't exist
        episode_ends = {}
        for line_num, line in enumerate(lines, 1):
            if 'EPISODE END' in line:
                episode_ends[line_num] = None
        
        if episode_ends:
            sorted_ends = sorted(episode_ends.keys())
            current_episode = 1
            
            for i, end_line in enumerate(sorted_ends):
                start_line = sorted_ends[i - 1] + 1 if i > 0 else 1
                for line_num in range(start_line, end_line + 1):
                    episode_map[line_num] = current_episode
                current_episode += 1
            
            if sorted_ends:
                last_end = sorted_ends[-1]
                for line_num in range(last_end + 1, len(lines) + 1):
                    episode_map[line_num] = current_episode - 1
        else:
            # No episode markers found - assume episode 1 for all lines
            for line_num in range(1, len(lines) + 1):
                episode_map[line_num] = 1
    
    return episode_map

def _get_episode_with_fallback(line_num: int, episode_map: Dict[int, int]) -> int:
    """
    Get episode for a line number with fallback logic.
    
    If episode is not mapped, infer from context by finding the last known episode
    before this line. This prevents skipping valid log entries due to mapping gaps.
    
    Args:
        line_num: Line number in step.log
        episode_map: Dictionary mapping line numbers to episode numbers
        
    Returns:
        Episode number (defaults to 1 if no mapping found)
    """
    if line_num in episode_map:
        episode = episode_map[line_num]
    else:
        episode = None
    if episode is None:
        # Find the last known episode before this line
        last_episode = 1  # Default to episode 1
        for prev_line_num in range(line_num - 1, 0, -1):
            if prev_line_num in episode_map:
                last_episode = episode_map[prev_line_num]
                break
        episode = last_episode
    return episode

def parse_moves_from_step(step_log: str, episode_map: Dict[int, int]) -> List[Dict]:
    """Parse MOVE and FLED actions from step.log with episode tracking
    Now supports both old format (without E{episode}) and new format (with E{episode})
    """
    moves = []
    # Pattern for MOVED with episode: [timestamp] E{episode} T{turn} P{player} MOVE : ...
    moved_pattern_with_ep = r'\[([^\]]+)\] E(\d+) T(\d+) P(\d+) MOVE : Unit (\d+)\((\d+),(\d+)\) MOVED from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    # Pattern for MOVED without episode (old format): [timestamp] T{turn} P{player} MOVE : ...
    moved_pattern_old = r'\[([^\]]+)\] T(\d+) P(\d+) MOVE : Unit (\d+)\((\d+),(\d+)\) MOVED from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    # Pattern for FLED with episode
    fled_pattern_with_ep = r'\[([^\]]+)\] E(\d+) T(\d+) P(\d+) MOVE : Unit (\d+)\((\d+),(\d+)\) FLED from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    # Pattern for FLED without episode (old format)
    fled_pattern_old = r'\[([^\]]+)\] T(\d+) P(\d+) MOVE : Unit (\d+)\((\d+),(\d+)\) FLED from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    
    for line_num, line in enumerate(step_log.split('\n'), 1):
        # Try MOVED with episode first (new format)
        match = re.search(moved_pattern_with_ep, line)
        if match:
            timestamp, episode, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
            moves.append({
                'episode': int(episode),  # Use episode from log line
                'turn': int(turn),
                'player': int(player),
                'unit_id': unit_id,
                'from': (int(from_col), int(from_row)),
                'to': (int(to_col), int(to_row)),
                'type': 'MOVED',
                'line': line
            })
        else:
            # Try MOVED without episode (old format)
            match = re.search(moved_pattern_old, line)
            if match:
                episode = _get_episode_with_fallback(line_num, episode_map)
                timestamp, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
                moves.append({
                    'episode': episode,
                    'turn': int(turn),
                    'player': int(player),
                    'unit_id': unit_id,
                    'from': (int(from_col), int(from_row)),
                    'to': (int(to_col), int(to_row)),
                    'type': 'MOVED',
                    'line': line
                })
            else:
                # Try FLED with episode (new format)
                match = re.search(fled_pattern_with_ep, line)
                if match:
                    timestamp, episode, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
                    moves.append({
                        'episode': int(episode),  # Use episode from log line
                        'turn': int(turn),
                        'player': int(player),
                        'unit_id': unit_id,
                        'from': (int(from_col), int(from_row)),
                        'to': (int(to_col), int(to_row)),
                        'type': 'FLED',
                        'line': line
                    })
                else:
                    # Try FLED without episode (old format)
                    match = re.search(fled_pattern_old, line)
                    if match:
                        episode = _get_episode_with_fallback(line_num, episode_map)
                        timestamp, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
                        moves.append({
                            'episode': episode,
                            'turn': int(turn),
                            'player': int(player),
                            'unit_id': unit_id,
                            'from': (int(from_col), int(from_row)),
                            'to': (int(to_col), int(to_row)),
                            'type': 'FLED',
                            'line': line
                        })
    
    return moves

def parse_charges_from_step(step_log: str, episode_map: Dict[int, int]) -> List[Dict]:
    """Parse CHARGE actions from step.log (they also move units) with episode tracking
    Now supports both old format (without E{episode}) and new format (with E{episode})
    """
    charges = []
    # Pattern with episode (new format)
    pattern_with_ep = r'\[([^\]]+)\] E(\d+) T(\d+) P(\d+) CHARGE : Unit (\d+)\((\d+),(\d+)\) CHARGED unit \d+\([^\)]+\) from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    # Pattern without episode (old format)
    pattern_old = r'\[([^\]]+)\] T(\d+) P(\d+) CHARGE : Unit (\d+)\((\d+),(\d+)\) CHARGED unit \d+\([^\)]+\) from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    
    for line_num, line in enumerate(step_log.split('\n'), 1):
        # Try with episode first (new format)
        match = re.search(pattern_with_ep, line)
        if match:
            timestamp, episode, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
            charges.append({
                'episode': int(episode),  # Use episode from log line
                'turn': int(turn),
                'player': int(player),
                'unit_id': unit_id,
                'from': (int(from_col), int(from_row)),
                'to': (int(to_col), int(to_row)),
                'line': line
            })
        else:
            # Try without episode (old format)
            match = re.search(pattern_old, line)
            if match:
                episode = _get_episode_with_fallback(line_num, episode_map)
                timestamp, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
                charges.append({
                    'episode': episode,
                    'turn': int(turn),
                    'player': int(player),
                    'unit_id': unit_id,
                    'from': (int(from_col), int(from_row)),
                    'to': (int(to_col), int(to_row)),
                    'line': line
                })
    
    return charges

def parse_advances_from_step(step_log: str, episode_map: Dict[int, int]) -> List[Dict]:
    """Parse ADVANCE actions from step.log (they also move units) with episode tracking
    Now supports both old format (without E{episode}) and new format (with E{episode})
    """
    advances = []
    # Pattern with episode (new format)
    pattern_with_ep = r'\[([^\]]+)\] E(\d+) T(\d+) P(\d+) SHOOT : Unit (\d+)\((\d+),(\d+)\) ADVANCED from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    # Pattern without episode (old format)
    pattern_old = r'\[([^\]]+)\] T(\d+) P(\d+) SHOOT : Unit (\d+)\((\d+),(\d+)\) ADVANCED from \((\d+),(\d+)\) to \((\d+),(\d+)\)'
    
    for line_num, line in enumerate(step_log.split('\n'), 1):
        # Try with episode first (new format)
        match = re.search(pattern_with_ep, line)
        if match:
            timestamp, episode, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
            advances.append({
                'episode': int(episode),  # Use episode from log line
                'turn': int(turn),
                'player': int(player),
                'unit_id': unit_id,
                'from': (int(from_col), int(from_row)),
                'to': (int(to_col), int(to_row)),
                'line': line
            })
        else:
            # Try without episode (old format)
            match = re.search(pattern_old, line)
            if match:
                episode = _get_episode_with_fallback(line_num, episode_map)
                timestamp, turn, player, unit_id, col, row, from_col, from_row, to_col, to_row = match.groups()
                advances.append({
                    'episode': episode,
                    'turn': int(turn),
                    'player': int(player),
                    'unit_id': unit_id,
                    'from': (int(from_col), int(from_row)),
                    'to': (int(to_col), int(to_row)),
                    'line': line
                })
    
    return advances

def parse_attacks_from_step(step_log: str, episode_map: Dict[int, int]) -> List[Dict]:
    """Parse SHOOT and FIGHT attacks from step.log with episode tracking
    Now supports both old format (without E{episode}) and new format (with E{episode})
    """
    attacks = []
    
    # SHOOT attacks with episode (new format)
    shoot_pattern_with_ep = r'\[([^\]]+)\] E(\d+) T(\d+) P(\d+) SHOOT : Unit (\d+)\((\d+),(\d+)\) SHOT at unit (\d+)\((\d+),(\d+)\)'
    # SHOOT attacks without episode (old format)
    shoot_pattern_old = r'\[([^\]]+)\] T(\d+) P(\d+) SHOOT : Unit (\d+)\((\d+),(\d+)\) SHOT at unit (\d+)\((\d+),(\d+)\)'
    for line_num, line in enumerate(step_log.split('\n'), 1):
        # Try with episode first (new format)
        match = re.search(shoot_pattern_with_ep, line)
        if match:
            timestamp, episode, turn, player, attacker, a_col, a_row, target, t_col, t_row = match.groups()
            attacks.append({
                'episode': int(episode),  # Use episode from log line
                'turn': int(turn),
                'player': int(player),
                'phase': 'shoot',
                'attacker': attacker,
                'target': target,
                'line': line
            })
        else:
            # Try without episode (old format)
            match = re.search(shoot_pattern_old, line)
            if match:
                episode = _get_episode_with_fallback(line_num, episode_map)
                timestamp, turn, player, attacker, a_col, a_row, target, t_col, t_row = match.groups()
                attacks.append({
                    'episode': episode,
                    'turn': int(turn),
                    'player': int(player),
                    'phase': 'shoot',
                    'attacker': attacker,
                    'target': target,
                    'line': line
                })
    
    # FIGHT attacks with episode (new format)
    fight_pattern_with_ep = r'\[([^\]]+)\] E(\d+) T(\d+) P(\d+) FIGHT : Unit (\d+)\((\d+),(\d+)\) ATTACKED unit (\d+)\((\d+),(\d+)\)'
    # FIGHT attacks without episode (old format)
    fight_pattern_old = r'\[([^\]]+)\] T(\d+) P(\d+) FIGHT : Unit (\d+)\((\d+),(\d+)\) ATTACKED unit (\d+)\((\d+),(\d+)\)'
    for line_num, line in enumerate(step_log.split('\n'), 1):
        # Try with episode first (new format)
        match = re.search(fight_pattern_with_ep, line)
        if match:
            timestamp, episode, turn, player, attacker, a_col, a_row, target, t_col, t_row = match.groups()
            attacks.append({
                'episode': int(episode),  # Use episode from log line
                'turn': int(turn),
                'player': int(player),
                'phase': 'fight',
                'attacker': attacker,
                'target': target,
                'line': line
            })
        else:
            # Try without episode (old format)
            match = re.search(fight_pattern_old, line)
            if match:
                episode = _get_episode_with_fallback(line_num, episode_map)
                timestamp, turn, player, attacker, a_col, a_row, target, t_col, t_row = match.groups()
                attacks.append({
                    'episode': episode,
                    'turn': int(turn),
                    'player': int(player),
                    'phase': 'fight',
                    'attacker': attacker,
                    'target': target,
                    'line': line
                })
    
    return attacks

def parse_fight_activations(movement_log: str) -> List[Dict]:
    """Parse fight unit activations with valid targets"""
    activations = []
    
    # Pattern for unit activation with valid targets
    pattern = r'\[FIGHT DEBUG\] E(\d+) T(\d+) fight unit_activation: Unit (\d+) valid_targets=\[([^\]]+)\] count=(\d+)'
    
    for line in movement_log.split('\n'):
        match = re.search(pattern, line)
        if match:
            episode, turn, unit_id, targets_str, count = match.groups()
            targets = [t.strip().strip("'\"") for t in targets_str.split(',') if t.strip()]
            activations.append({
                'episode': int(episode),
                'turn': int(turn),
                'unit_id': unit_id,
                'valid_targets': targets,
                'count': int(count),
                'line': line
            })
    
    return activations

def parse_missing_attacks_warnings(movement_log: str) -> List[Dict]:
    """Parse warnings about units that should have attacked but didn't"""
    warnings = []
    
    pattern = r'\[FIGHT DEBUG\] ⚠️ E(\d+) T(\d+) fight ([^:]+): Unit (\d+) ADJACENT to enemy but ([^\n]+)'
    
    for line in movement_log.split('\n'):
        match = re.search(pattern, line)
        if match:
            episode, turn, context, unit_id, reason = match.groups()
            warnings.append({
                'episode': int(episode),
                'turn': int(turn),
                'context': context.strip(),
                'unit_id': unit_id,
                'reason': reason.strip(),
                'line': line
            })
    
    return warnings

def check_unlogged_moves(position_changes: List[Dict], step_moves: List[Dict], 
                        step_charges: List[Dict], step_advances: List[Dict]) -> List[Dict]:
    """Find position changes that are not logged in step.log
    
    IMPORTANT: This function groups position changes by (episode, turn, unit_id) to find
    the complete movement (from initial position to final position), because debug.log
    may log intermediate position changes during pathfinding, but step.log only logs
    the final complete movement.
    """
    unlogged = []
    
    # Group all step position changes by (episode, turn, unit_id, from, to)
    step_all_moves = set()
    for move in step_moves:
        key = (move['episode'], move['turn'], move['unit_id'], move['from'], move['to'])
        step_all_moves.add(key)
    for charge in step_charges:
        key = (charge['episode'], charge['turn'], charge['unit_id'], charge['from'], charge['to'])
        step_all_moves.add(key)
    for advance in step_advances:
        key = (advance['episode'], advance['turn'], advance['unit_id'], advance['from'], advance['to'])
        step_all_moves.add(key)
    
    # Group position changes by (episode, turn, unit_id) to find complete movements
    # Position changes in debug.log may be intermediate steps of a longer movement
    # We need to find the initial position (first 'from') and final position (last 'to')
    position_changes_by_unit = defaultdict(list)
    for change in position_changes:
        if change['type'] == 'MOVE':
            key = (change['episode'], change['turn'], change['unit_id'])
            position_changes_by_unit[key].append(change)
    
    # For each unit movement sequence, find the complete movement (initial -> final)
    for (episode, turn, unit_id), changes in position_changes_by_unit.items():
        if not changes:
            continue
        
        # Sort by order of appearance (using line number or order in list)
        # Find the first 'from' position (initial position) and last 'to' position (final position)
        initial_pos = changes[0]['from']  # First change starts from this position
        final_pos = changes[-1]['to']      # Last change ends at this position
        
        # Check if this complete movement is logged in step.log
        key = (episode, turn, unit_id, initial_pos, final_pos)
        if key not in step_all_moves:
            # This complete movement is not logged - report the first change as representative
            unlogged.append({
                'episode': episode,
                'turn': turn,
                'unit_id': unit_id,
                'phase': changes[0]['phase'],
                'from': initial_pos,
                'to': final_pos,
                'type': 'MOVE',
                'line': changes[0]['line']  # Use first change line as reference
            })
    
    return unlogged

def check_unlogged_attacks(debug_attacks: List[Dict], step_attacks: List[Dict]) -> List[Dict]:
    """Find attacks that are executed but not logged in step.log"""
    unlogged = []
    
    # Normalize unit IDs to strings for consistent comparison
    def normalize_id(unit_id):
        return str(unit_id).strip()
    
    # Count step attacks by (episode, turn, phase, attacker, target)
    step_attacks_counter = Counter()
    for attack in step_attacks:
        attacker = normalize_id(attack['attacker'])
        target = normalize_id(attack['target'])
        key = (attack['episode'], attack['turn'], attack['phase'], attacker, target)
        step_attacks_counter[key] += 1
    
    # Count debug attacks and compare
    debug_attacks_counter = Counter()
    for attack in debug_attacks:
        attacker = normalize_id(attack['attacker'])
        target = normalize_id(attack['target'])
        key = (attack['episode'], attack['turn'], attack['phase'], attacker, target)
        debug_attacks_counter[key] += 1
    
    # Find attacks that are in debug but not in step (or fewer in step)
    # Also check adjacent turns (T-1) in case of phase transition timing issues
    # When fight phase completes, attacks may be logged in the next turn due to phase transition
    for attack in debug_attacks:
        attacker = normalize_id(attack['attacker'])
        target = normalize_id(attack['target'])
        key = (attack['episode'], attack['turn'], attack['phase'], attacker, target)
        debug_count = debug_attacks_counter[key]
        step_count = step_attacks_counter[key]
        
        # If not found in exact turn, check previous turn (T-1) due to phase transitions
        # This handles cases where fight phase completes and attacks are logged in next turn
        if step_count == 0 and attack['turn'] > 1:
            key_prev_turn = (attack['episode'], attack['turn'] - 1, attack['phase'], attacker, target)
            step_count = step_attacks_counter[key_prev_turn]
        
        if step_count < debug_count:
            # This attack is missing or partially missing
            unlogged.append(attack)
    
    # Remove duplicates (keep only unique attacks)
    seen = set()
    unique_unlogged = []
    for attack in unlogged:
        attacker = normalize_id(attack['attacker'])
        target = normalize_id(attack['target'])
        key = (attack['episode'], attack['turn'], attack['phase'], attacker, target, attack['damage'], attack['target_died'])
        if key not in seen:
            seen.add(key)
            unique_unlogged.append(attack)
    
    return unique_unlogged

def check_missing_fight_attacks(activations: List[Dict], step_attacks: List[Dict], movement_log: str) -> List[Dict]:
    """Find units that were activated in fight phase with valid targets but didn't attack ANY target"""
    missing = []
    
    # Get all fight attacks from step.log grouped by (episode, turn, attacker)
    fight_attacks_by_unit = defaultdict(set)
    for attack in step_attacks:
        if attack['phase'] == 'fight':
            key = (attack['episode'], attack['turn'], attack['attacker'])
            fight_attacks_by_unit[key].add(attack['target'])
    
    # Check each activation
    for activation in activations:
        if activation['count'] > 0:  # Has valid targets
            key = (activation['episode'], activation['turn'], activation['unit_id'])
            attacked_targets = fight_attacks_by_unit[key]
            
            # Check if unit attacked AT LEAST ONE valid target
            valid_targets_set = set(activation['valid_targets'])
            if not attacked_targets or not valid_targets_set.intersection(attacked_targets):
                # Unit had valid targets but didn't attack ANY of them
                missing.append({
                    'episode': activation['episode'],
                    'turn': activation['turn'],
                    'unit_id': activation['unit_id'],
                    'valid_targets': activation['valid_targets'],
                    'attacked_targets': list(attacked_targets),
                    'line': activation['line']
                })
    
    return missing

def main():
    import datetime
    import os
    
    # Open output file for writing
    output_file = 'hidden_action_finder_output.log'
    output_dir = os.path.dirname(output_file)
    if output_dir:  # Only create directory if path is not empty
        os.makedirs(output_dir, exist_ok=True)
    output_f = open(output_file, 'w', encoding='utf-8')
    
    def file_print(*args, **kwargs):
        """Print only to file (not to console)"""
        print(*args, file=output_f, **kwargs)
        output_f.flush()
    
    def log_print(*args, **kwargs):
        """Print to both console and file (used only for final summary line)"""
        print(*args, **kwargs)
        print(*args, file=output_f, **kwargs)
        output_f.flush()
    
    total_issues = 0
    try:
        file_print("=" * 80)
        file_print("VÉRIFICATION DES LOGS - Détection des actions non loguées")
        file_print(f"Généré le: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        file_print("=" * 80)
        
        # Read logs - OPTIMIZED: Process files line by line to avoid OOM
        # Instead of loading entire files in memory, process them incrementally
        try:
            debug_log_path = 'debug.log'
            if not os.path.exists(debug_log_path):
                file_print("❌ ERREUR: debug.log introuvable")
                output_f.close()
                return
        except Exception as e:
            file_print(f"❌ ERREUR: {e}")
            output_f.close()
            return
        
        try:
            step_log_path = 'step.log'
            if not os.path.exists(step_log_path):
                file_print("❌ ERREUR: step.log introuvable")
                output_f.close()
                return
        except Exception as e:
            file_print(f"❌ ERREUR: {e}")
            output_f.close()
            return
        
        # Parse logs - OPTIMIZED: Process files line by line to avoid OOM
        file_print("\n📖 Parsing des logs...")
        
        # First, build episode map from step.log (needs full file, but we'll do it efficiently)
        with open(step_log_path, 'r') as f:
            step_log = f.read()
        episode_map = parse_episodes_from_step(step_log)
        del step_log  # Free memory immediately
        
        # Process debug.log line by line
        position_changes = []
        debug_attacks = []
        fight_activations = []
        missing_warnings = []
        
        with open(debug_log_path, 'r') as f:
            debug_lines = []
            for line in f:
                debug_lines.append(line)
                # Process in batches to avoid memory buildup
                if len(debug_lines) >= 100000:  # Process every 100k lines
                    movement_log_batch = ''.join(debug_lines)
                    position_changes.extend(parse_position_changes(movement_log_batch))
                    debug_attacks.extend(parse_attacks_from_debug(movement_log_batch))
                    fight_activations.extend(parse_fight_activations(movement_log_batch))
                    missing_warnings.extend(parse_missing_attacks_warnings(movement_log_batch))
                    debug_lines = []
            # Process remaining lines
            if debug_lines:
                movement_log_batch = ''.join(debug_lines)
                position_changes.extend(parse_position_changes(movement_log_batch))
                debug_attacks.extend(parse_attacks_from_debug(movement_log_batch))
                fight_activations.extend(parse_fight_activations(movement_log_batch))
                missing_warnings.extend(parse_missing_attacks_warnings(movement_log_batch))
        
        # Process step.log line by line
        step_moves = []
        step_charges = []
        step_advances = []
        step_attacks = []
        
        with open(step_log_path, 'r') as f:
            step_log_lines = []
            for line in f:
                step_log_lines.append(line)
                # Process in batches to avoid memory buildup
                if len(step_log_lines) >= 100000:  # Process every 100k lines
                    step_log_batch = ''.join(step_log_lines)
                    step_moves.extend(parse_moves_from_step(step_log_batch, episode_map))
                    step_charges.extend(parse_charges_from_step(step_log_batch, episode_map))
                    step_advances.extend(parse_advances_from_step(step_log_batch, episode_map))
                    step_attacks.extend(parse_attacks_from_step(step_log_batch, episode_map))
                    step_log_lines = []
            # Process remaining lines
            if step_log_lines:
                step_log_batch = ''.join(step_log_lines)
                step_moves.extend(parse_moves_from_step(step_log_batch, episode_map))
                step_charges.extend(parse_charges_from_step(step_log_batch, episode_map))
                step_advances.extend(parse_advances_from_step(step_log_batch, episode_map))
                step_attacks.extend(parse_attacks_from_step(step_log_batch, episode_map))
        
        file_print(f"  - Position changes: {len(position_changes)}")
        file_print(f"  - Attaques (debug): {len(debug_attacks)}")
        file_print(f"  - Mouvements (step.log): {len(step_moves)}")
        file_print(f"  - Charges (step.log): {len(step_charges)}")
        file_print(f"  - Advances (step.log): {len(step_advances)}")
        file_print(f"  - Attaques (step.log): {len(step_attacks)}")
        file_print(f"  - Activations fight: {len(fight_activations)}")
        file_print(f"  - Avertissements manquants: {len(missing_warnings)}")
        
        # Check 1: Unlogged moves
        file_print("\n" + "=" * 80)
        file_print("1. MOUVEMENTS FAITS MAIS NON LOGUÉS DANS STEP.LOG")
        file_print("=" * 80)
        unlogged_moves = check_unlogged_moves(position_changes, step_moves, step_charges, step_advances)
        if unlogged_moves:
            file_print(f"⚠️  {len(unlogged_moves)} mouvement(s) non logué(s):")
            for move in unlogged_moves[:20]:  # Show first 20
                file_print(f"  E{move['episode']} T{move['turn']} {move['phase']}: Unit {move['unit_id']} {move['from']}→{move['to']} ({move['type']})")
            if len(unlogged_moves) > 20:
                file_print(f"  ... et {len(unlogged_moves) - 20} autres")
        else:
            file_print("✅ Tous les mouvements sont logués")
        
        # Check 2: Unlogged attacks
        file_print("\n" + "=" * 80)
        file_print("2. ATTAQUES FAITES MAIS NON LOGUÉES DANS STEP.LOG")
        file_print("=" * 80)
        unlogged_attacks = check_unlogged_attacks(debug_attacks, step_attacks)
        if unlogged_attacks:
            file_print(f"⚠️  {len(unlogged_attacks)} attaque(s) non loguée(s):")
            
            # Group by (episode, turn, phase, attacker, target) for better analysis
            from collections import defaultdict
            grouped = defaultdict(list)
            for attack in unlogged_attacks:
                key = (attack['episode'], attack['turn'], attack['phase'], attack['attacker'], attack['target'])
                grouped[key].append(attack)
            
            file_print(f"\n  Groupées par (episode, turn, phase, attacker, target): {len(grouped)} groupe(s)")
            for i, (key, attacks) in enumerate(list(grouped.items())[:10]):
                episode, turn, phase, attacker, target = key
                file_print(f"  Groupe {i+1}: E{episode} T{turn} {phase} Unit {attacker} -> Unit {target}: {len(attacks)} attaque(s) manquante(s)")
                # Show first attack details
                if attacks:
                    first = attacks[0]
                    file_print(f"    Exemple: damage={first['damage']}, died={first['target_died']}, line={first['line'][:80]}...")
            
            if len(unlogged_attacks) > 20:
                file_print(f"\n  ... et {len(unlogged_attacks) - 20} autres attaques individuelles")
        else:
            file_print("✅ Toutes les attaques sont loguées")
        
        # Check 3: Missing fight attacks
        file_print("\n" + "=" * 80)
        file_print("3. ATTAQUES MANQUANTES EN PHASE FIGHT (unités avec cibles valides mais AUCUNE attaque)")
        file_print("=" * 80)
        missing_attacks = check_missing_fight_attacks(fight_activations, step_attacks, movement_log)
        if missing_attacks:
            file_print(f"⚠️  {len(missing_attacks)} unité(s) avec cibles valides mais SANS AUCUNE attaque loguée:")
            for missing in missing_attacks[:20]:  # Show first 20
                file_print(f"  E{missing['episode']} T{missing['turn']}: Unit {missing['unit_id']}")
                file_print(f"    Valid targets: {missing['valid_targets']}")
                file_print(f"    Attacked targets: {missing['attacked_targets']}")
            if len(missing_attacks) > 20:
                file_print(f"  ... et {len(missing_attacks) - 20} autres")
        else:
            file_print("✅ Toutes les unités avec cibles valides ont attaqué au moins une cible")
        
        # Check 4: Warnings from debug logs
        file_print("\n" + "=" * 80)
        file_print("4. AVERTISSEMENTS DÉTECTÉS DANS DEBUG.LOG")
        file_print("=" * 80)
        if missing_warnings:
            file_print(f"⚠️  {len(missing_warnings)} avertissement(s) détecté(s):")
            for warning in missing_warnings:
                file_print(f"  E{warning['episode']} T{warning['turn']} {warning['context']}: Unit {warning['unit_id']}")
                file_print(f"    {warning['reason']}")
        else:
            file_print("✅ Aucun avertissement détecté")
        
        # Summary
        file_print("\n" + "=" * 80)
        file_print("RÉSUMÉ")
        file_print("=" * 80)
        total_issues = len(unlogged_moves) + len(unlogged_attacks) + len(missing_attacks) + len(missing_warnings)
        if total_issues == 0:
            file_print("✅ Aucun problème détecté - tous les logs sont cohérents")
        else:
            file_print(f"⚠️  {total_issues} problème(s) détecté(s):")
            file_print(f"  - Mouvements non logués: {len(unlogged_moves)}")
            file_print(f"  - Attaques non loguées: {len(unlogged_attacks)}")
            file_print(f"  - Attaques manquantes (aucune attaque): {len(missing_attacks)}")
            file_print(f"  - Avertissements: {len(missing_warnings)}")
    
    except Exception as e:
        file_print(f"❌ ERREUR: {e}")
        import traceback
        traceback.print_exc(file=output_f)
    finally:
        if total_issues > 0:
            log_print(f"⚠️ hidden_action_finder.py :  {total_issues} erreur(s) détectée(s)   -   Output : {output_file}")
        else:
            log_print(f"✅ hidden_action_finder.py : Aucune erreur détectée   -   Output : {output_file}")
        output_f.close()

if __name__ == '__main__':
    main()