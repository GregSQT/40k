#!/usr/bin/env python3
"""
Script pour analyser en détail chaque type d'erreur détecté par analyzer.py
Examine les exemples concrets pour comprendre les causes racines.
"""

import re
import sys
from collections import defaultdict

def analyze_errors(log_file):
    """Analyse détaillée de chaque type d'erreur"""
    
    errors = {
        'shoot_through_wall': [],
        'shoot_after_fled': [],
        'shoot_at_friendly': [],
        'shoot_at_engaged': [],
        'shoot_dead_unit': [],
        'move_to_adjacent': [],
        'charge_from_adjacent': [],
        'charge_after_fled': [],
        'collisions': []
    }
    
    # Track state
    unit_hp = {}
    unit_player = {}
    unit_positions = {}
    unit_types = {}
    wall_hexes = set()
    units_fled = set()
    units_advanced = set()
    
    current_episode = 0
    current_turn = 0
    last_turn = 0
    
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line_num, line in enumerate(lines, 1):
        # Episode start
        if '=== EPISODE' in line and 'START ===' in line:
            current_episode += 1
            unit_hp = {}
            unit_player = {}
            unit_positions = {}
            unit_types = {}
            wall_hexes = set()
            units_fled = set()
            units_advanced = set()
            continue
        
        # Parse walls
        wall_match = re.search(r'Walls: (.+)$', line)
        if wall_match:
            wall_str = wall_match.group(1).strip()
            if wall_str != 'none':
                for coord_match in re.finditer(r'\((\d+),(\d+)\)', wall_str):
                    col, row = int(coord_match.group(1)), int(coord_match.group(2))
                    wall_hexes.add((col, row))
            continue
        
        # Parse unit starting positions
        unit_start_match = re.match(r'.*Unit (\d+) \((\w+)\) P(\d+): Starting position \((\d+),\s*(\d+)\)', line)
        if unit_start_match:
            unit_id = unit_start_match.group(1)
            unit_type = unit_start_match.group(2)
            player = int(unit_start_match.group(3))
            col = int(unit_start_match.group(4))
            row = int(unit_start_match.group(5))
            
            # Set HP based on unit type
            if unit_type in ['Termagant', 'Hormagaunt', 'Genestealer']:
                unit_hp[unit_id] = 1
            else:
                unit_hp[unit_id] = 2
            
            unit_player[unit_id] = player
            unit_positions[unit_id] = (col, row)
            unit_types[unit_id] = unit_type
            continue
        
        # Parse action line
        match = re.match(r'\[.*?\] (?:E\d+ )?T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\] \[STEP: (YES|NO)\]', line)
        if match:
            turn = int(match.group(1))
            player = int(match.group(2))
            phase = match.group(3)
            action_desc = match.group(4)
            step_inc = match.group(6) == 'YES'
            
            # Reset markers when turn changes
            if turn != last_turn:
                units_fled = set()
                units_advanced = set()
                last_turn = turn
            
            current_turn = turn
            
            # Apply damage
            if 'shot at unit' in action_desc.lower() or 'attacked unit' in action_desc.lower():
                target_match = re.search(r'(?:SHOT at|ATTACKED) unit (\d+)', action_desc, re.IGNORECASE)
                if target_match:
                    target_id = target_match.group(1)
                    damage_match = re.search(r'Dmg:(\d+)HP', action_desc)
                    if damage_match:
                        damage = int(damage_match.group(1))
                        if damage > 0 and target_id in unit_hp:
                            unit_hp[target_id] -= damage
                            if unit_hp[target_id] <= 0:
                                if target_id in unit_positions:
                                    del unit_positions[target_id]
                                del unit_hp[target_id]
            
            if step_inc:
                # Analyze SHOOT errors
                if 'shoots' in action_desc.lower() or 'shot' in action_desc.lower():
                    shooter_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\)', action_desc)
                    target_match = re.search(r'SHOT at unit (\d+)(?:\((\d+),\s*(\d+)\))?', action_desc, re.IGNORECASE)
                    
                    if shooter_match and target_match:
                        shooter_id = shooter_match.group(1)
                        shooter_col = int(shooter_match.group(2))
                        shooter_row = int(shooter_match.group(3))
                        target_id = target_match.group(1)
                        
                        # Shoot through wall
                        if target_match.group(2) and target_match.group(3):
                            target_col = int(target_match.group(2))
                            target_row = int(target_match.group(3))
                            if not has_line_of_sight(shooter_col, shooter_row, target_col, target_row, wall_hexes):
                                errors['shoot_through_wall'].append({
                                    'episode': current_episode,
                                    'turn': turn,
                                    'line': line_num,
                                    'shooter': shooter_id,
                                    'target': target_id,
                                    'shooter_pos': (shooter_col, shooter_row),
                                    'target_pos': (target_col, target_row),
                                    'wall_hexes': list(wall_hexes)
                                })
                        
                        # Shoot after fled
                        if shooter_id in units_fled:
                            errors['shoot_after_fled'].append({
                                'episode': current_episode,
                                'turn': turn,
                                'line': line_num,
                                'shooter': shooter_id,
                                'target': target_id
                            })
                        
                        # Shoot at friendly
                        if target_id in unit_player and unit_player[target_id] == player:
                            errors['shoot_at_friendly'].append({
                                'episode': current_episode,
                                'turn': turn,
                                'line': line_num,
                                'shooter': shooter_id,
                                'target': target_id,
                                'shooter_player': unit_player.get(shooter_id),
                                'target_player': unit_player.get(target_id)
                            })
                        
                        # Dead unit shooting
                        if shooter_id not in unit_hp or unit_hp.get(shooter_id, 0) <= 0:
                            errors['shoot_dead_unit'].append({
                                'episode': current_episode,
                                'turn': turn,
                                'line': line_num,
                                'shooter': shooter_id,
                                'target': target_id,
                                'hp': unit_hp.get(shooter_id, 0)
                            })
                
                # Analyze MOVE errors
                if 'moved' in action_desc.lower() or 'moves' in action_desc.lower():
                    move_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) MOVED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                    if move_match:
                        unit_id = move_match.group(1)
                        from_col = int(move_match.group(4))
                        from_row = int(move_match.group(5))
                        to_col = int(move_match.group(6))
                        to_row = int(move_match.group(7))
                        
                        # Check if destination is adjacent to enemy
                        dest_adjacent = is_adjacent_to_enemy(to_col, to_row, unit_player, unit_positions, unit_hp, player)
                        if dest_adjacent:
                            errors['move_to_adjacent'].append({
                                'episode': current_episode,
                                'turn': turn,
                                'line': line_num,
                                'unit': unit_id,
                                'from': (from_col, from_row),
                                'to': (to_col, to_row)
                            })
                
                # Track FLED
                if 'fled' in action_desc.lower():
                    fled_match = re.search(r'Unit (\d+)', action_desc)
                    if fled_match:
                        unit_id = fled_match.group(1)
                        units_fled.add(unit_id)
    
    return errors

def has_line_of_sight(shooter_col, shooter_row, target_col, target_row, wall_hexes):
    """Simplified LoS check"""
    if not wall_hexes:
        return True
    # Simple check - would need full hex line calculation for accurate result
    return True  # Placeholder

def is_adjacent_to_enemy(col, row, unit_player, unit_positions, unit_hp, player):
    """Check if position is adjacent to enemy"""
    enemy_player = 3 - player
    for uid, pos in unit_positions.items():
        p = unit_player.get(uid)
        if p == enemy_player and unit_hp.get(uid, 0) > 0:
            if abs(col - pos[0]) + abs(row - pos[1]) <= 1:  # Simplified adjacency
                return True
    return False

def print_analysis(errors):
    """Print detailed error analysis"""
    print("=" * 80)
    print("ERROR ANALYSIS")
    print("=" * 80)
    
    for error_type, error_list in errors.items():
        if error_list:
            print(f"\n--- {error_type.upper()} ({len(error_list)} cases) ---")
            for i, err in enumerate(error_list[:3], 1):  # Show first 3
                print(f"  Case {i}: Episode {err['episode']}, Turn {err['turn']}, Line {err['line']}")
                for key, value in err.items():
                    if key not in ['episode', 'turn', 'line']:
                        print(f"    {key}: {value}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python ai/analyze_errors.py step.log")
        sys.exit(1)
    
    log_file = sys.argv[1]
    errors = analyze_errors(log_file)
    print_analysis(errors)
