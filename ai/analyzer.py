#!/usr/bin/env python3
"""
analyzer.py - Analyze step.log and validate game rules compliance
Run this locally: python ai/analyzer.py step.log
"""

import sys
import os
import re
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set, Optional

# Add project root to Python path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import utility functions from engine
from engine.combat_utils import calculate_hex_distance, get_hex_line


def has_line_of_sight(shooter_col: int, shooter_row: int, target_col: int, target_row: int, wall_hexes: Set[Tuple[int, int]]) -> bool:
    """Check line of sight between two hex coordinates, checking for walls blocking."""
    if not wall_hexes:
        return True
    
    hex_path = get_hex_line(shooter_col, shooter_row, target_col, target_row)
    
    # Check if any hex in path is a wall (excluding start and end)
    for col, row in hex_path[1:-1]:
        if (col, row) in wall_hexes:
            return False
    
    return True


def is_adjacent(col1: int, row1: int, col2: int, row2: int) -> bool:
    """Check if two hexes are adjacent (distance == 1)."""
    return calculate_hex_distance(col1, row1, col2, row2) == 1


def is_adjacent_to_enemy(col: int, row: int, unit_player: Dict[str, int], unit_positions: Dict[str, Tuple[int, int]], 
                         unit_hp: Dict[str, int], player: int) -> bool:
    """Check if a hex is adjacent to any enemy unit."""
    enemy_player = 3 - player
    for uid, p in unit_player.items():
        if p == enemy_player and unit_hp.get(uid, 0) > 0 and uid in unit_positions:
            enemy_pos = unit_positions[uid]
            if is_adjacent(col, row, enemy_pos[0], enemy_pos[1]):
                return True
    return False


def is_engaged(unit_id: str, unit_player: Dict[str, int], unit_positions: Dict[str, Tuple[int, int]], 
               unit_hp: Dict[str, int]) -> bool:
    """Check if a unit is engaged (adjacent to an enemy)."""
    if unit_id not in unit_positions:
        return False
    
    player = unit_player.get(unit_id, -1)
    if player == -1:
        return False
    
    unit_pos = unit_positions[unit_id]
    return is_adjacent_to_enemy(unit_pos[0], unit_pos[1], unit_player, unit_positions, unit_hp, player)


def parse_step_log(filepath: str) -> Dict:
    """Parse step.log and extract statistics with rule validation."""
    
    # Load unit weapons at script start
    from ai.unit_registry import UnitRegistry
    
    unit_registry = UnitRegistry()
    unit_weapons_cache = {}  # unit_type -> list of weapons with {display_name, RNG, WEAPON_RULES, is_pistol}
    
    # Load weapons for each unit type
    for unit_type, unit_data in unit_registry.units.items():
        rng_weapons = unit_data.get("RNG_WEAPONS", [])
        weapons_info = []
        for weapon in rng_weapons:
            if isinstance(weapon, dict):
                weapon_rules = weapon.get("WEAPON_RULES", [])
                weapons_info.append({
                    'name': weapon.get('display_name', ''),
                    'range': weapon.get('RNG', 0),
                    'rules': weapon_rules,
                    'is_pistol': 'PISTOL' in weapon_rules
                })
        unit_weapons_cache[unit_type] = weapons_info

    # Statistics structure
    stats = {
        'total_episodes': 0,
        'total_actions': 0,
        'episode_lengths': [],
        'turns_distribution': Counter(),
        'actions_by_type': Counter(),
        'actions_by_phase': Counter(),
        'actions_by_player': {1: Counter(), 2: Counter()},
        'win_methods': {
            1: {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},
            2: {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},
            -1: {'draw': 0}
        },
        'wins_by_scenario': defaultdict(lambda: {'p1': 0, 'p2': 0, 'draws': 0}),
        'shoot_vs_wait': {
            'shoot': 0, 'wait': 0, 'skip': 0, 'advance': 0
        },
        'shoot_vs_wait_by_player': {
            1: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0},
            2: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0}
        },
        'shots_after_advance': {1: 0, 2: 0},
        'pistol_shots': {
            1: {'adjacent': 0, 'not_adjacent': 0},
            2: {'adjacent': 0, 'not_adjacent': 0}
        },
        'non_pistol_adjacent_shots': {1: 0, 2: 0},
        'wait_by_phase': {
            1: {'move_wait': 0, 'shoot_wait_with_los': 0, 'shoot_wait_no_los': 0},
            2: {'move_wait': 0, 'shoot_wait_with_los': 0, 'shoot_wait_no_los': 0}
        },
        'target_priority': {
            1: {'shots_at_wounded_in_los': 0, 'shots_at_full_hp_while_wounded_in_los': 0, 'total_shots': 0},
            2: {'shots_at_wounded_in_los': 0, 'shots_at_full_hp_while_wounded_in_los': 0, 'total_shots': 0}
        },
        'death_orders': [],
        'current_episode_deaths': [],
        'unit_types': {},
        'wounded_enemies': {1: set(), 2: set()},
        # Rule violations
        'wall_collisions': {1: 0, 2: 0},
        'move_to_adjacent_enemy': {1: 0, 2: 0},
        'charge_from_adjacent': {1: 0, 2: 0},
        'advance_from_adjacent': {1: 0, 2: 0},
        'shoot_through_wall': {1: 0, 2: 0},
        'shoot_after_fled': {1: 0, 2: 0},
        'shoot_at_friendly': {1: 0, 2: 0},
        'shoot_at_engaged_enemy': {1: 0, 2: 0},
        'charge_after_fled': {1: 0, 2: 0},
        'fight_from_non_adjacent': {1: 0, 2: 0},
        'fight_friendly': {1: 0, 2: 0},
        # First occurrence lines for each error type (stores dict with 'episode' and 'line')
        'first_error_lines': {
            'wall_collisions': {1: None, 2: None},
            'move_to_adjacent_enemy': {1: None, 2: None},
            'charge_from_adjacent': {1: None, 2: None},
            'advance_from_adjacent': {1: None, 2: None},
            'shoot_through_wall': {1: None, 2: None},
            'shoot_after_fled': {1: None, 2: None},
            'shoot_at_friendly': {1: None, 2: None},
            'shoot_at_engaged_enemy': {1: None, 2: None},
            'charge_after_fled': {1: None, 2: None},
            'fight_from_non_adjacent': {1: None, 2: None},
            'fight_friendly': {1: None, 2: None},
        },
        'unit_position_collisions': [],
        'parse_errors': [],
        'episodes_without_end': [],
        'episodes_without_method': [],
        'sample_actions': {
            'move': None,
            'shoot': None,
            'advance': None,
            'charge': None,
            'fight': None
        }
    }

    # Current episode state
    current_episode = []
    current_episode_num = 0
    current_scenario = 'Unknown'
    episode_turn = 0
    episode_actions = 0
    last_turn = 0

    # Unit tracking
    unit_hp = {}
    unit_player = {}
    unit_positions = {}
    unit_types = {}
    wall_hexes = set()
    
    # Turn/phase markers
    units_moved = set()
    units_shot = set()
    units_fled = set()
    units_advanced = set()
    units_fought = set()
    positions_at_turn_start = {}
    positions_at_move_phase_start = {}  # Track positions at start of MOVE phase to detect fled

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            # Episode start
            if '=== EPISODE' in line and 'START ===' in line:
                if current_episode:
                    stats['episodes_without_end'].append({
                        'episode_num': current_episode_num,
                        'actions': episode_actions,
                        'turn': episode_turn,
                        'last_line': current_episode[-1][:100] if current_episode else 'N/A'
                    })
                    
                    if stats['current_episode_deaths']:
                        stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                    stats['episode_lengths'].append(episode_actions)
                    if episode_turn > 0:
                        stats['turns_distribution'][episode_turn] += 1

                current_episode = []
                stats['total_episodes'] += 1
                current_episode_num = stats['total_episodes']
                episode_turn = 0
                episode_actions = 0
                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {1: set(), 2: set()}
                unit_hp = {}
                unit_player = {}
                unit_positions = {}
                unit_types = {}
                wall_hexes = set()
                positions_at_turn_start = {}
                positions_at_move_phase_start = {}
                current_scenario = 'Unknown'
                units_moved = set()
                units_shot = set()
                units_fled = set()
                units_advanced = set()
                units_fought = set()
                continue

            # Skip header lines
            if line.startswith('===') or line.startswith('AI_TURN') or line.startswith('STEP') or \
               line.startswith('NO STEP') or line.startswith('FAILED') or not line.strip():
                continue

            # Parse scenario
            scenario_match = re.search(r'Scenario: (.+)$', line)
            if scenario_match:
                current_scenario = scenario_match.group(1).strip()
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
                stats['unit_types'][unit_id] = unit_type
                positions_at_turn_start[unit_id] = (col, row)
                continue

            # Episode end
            if 'EPISODE END' in line:
                if stats['current_episode_deaths']:
                    stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                # Save turn distribution for this episode
                if episode_turn > 0:
                    stats['turns_distribution'][episode_turn] += 1
                stats['episode_lengths'].append(episode_actions)

                winner_match = re.search(r'Winner=(-?\d+)', line)
                method_match = re.search(r'Method=(\w+)', line)

                if winner_match:
                    winner = int(winner_match.group(1))
                    win_method = method_match.group(1) if method_match else None

                    if winner == 1:
                        stats['wins_by_scenario'][current_scenario]['p1'] += 1
                    elif winner == 2:
                        stats['wins_by_scenario'][current_scenario]['p2'] += 1
                    elif winner == -1:
                        stats['wins_by_scenario'][current_scenario]['draws'] += 1

                    if win_method:
                        if winner in stats['win_methods'] and win_method in stats['win_methods'][winner]:
                            stats['win_methods'][winner][win_method] += 1
                        elif winner == -1:
                            stats['win_methods'][-1]['draw'] += 1
                    else:
                        stats['episodes_without_method'].append({
                            'winner': winner,
                            'line': line.strip()[:100]
                        })

                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {1: set(), 2: set()}
                current_episode = []
                continue

            # Parse action line
            match = re.match(r'\[.*?\] T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\] \[STEP: (YES|NO)\]', line)
            if match:
                turn = int(match.group(1))
                player = int(match.group(2))
                phase = match.group(3)
                action_desc = match.group(4)
                success = match.group(5) == 'SUCCESS'
                step_inc = match.group(6) == 'YES'

                # Reset markers when turn changes
                if turn != last_turn:
                    units_moved = set()
                    units_shot = set()
                    units_fled = set()
                    units_advanced = set()
                    units_fought = set()
                    positions_at_turn_start = unit_positions.copy()
                    positions_at_move_phase_start = {}
                    last_turn = turn

                # Track positions at start of MOVE phase for fled detection
                if phase == 'MOVE' and not positions_at_move_phase_start:
                    positions_at_move_phase_start = unit_positions.copy()

                episode_turn = max(episode_turn, turn)

                if step_inc:
                    stats['total_actions'] += 1
                    episode_actions += 1
                    stats['actions_by_phase'][phase] += 1

                    # Determine action type and validate rules
                    if 'shoots' in action_desc.lower() or 'shot' in action_desc.lower():
                        action_type = 'shoot'
                        stats['shoot_vs_wait']['shoot'] += 1
                        stats['shoot_vs_wait_by_player'][player]['shoot'] += 1
                        units_shot.add(unit_id) if 'unit_id' in locals() else None

                        shooter_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\)', action_desc)
                        target_match = re.search(r'SHOT at unit (\d+)(?:\((\d+),\s*(\d+)\))?', action_desc, re.IGNORECASE)

                        if shooter_match and target_match:
                            shooter_id = shooter_match.group(1)
                            shooter_col = int(shooter_match.group(2))
                            shooter_row = int(shooter_match.group(3))
                            target_id = target_match.group(1)
                            
                            if target_match.group(2) and target_match.group(3):
                                target_col = int(target_match.group(2))
                                target_row = int(target_match.group(3))
                                target_pos = (target_col, target_row)
                            elif target_id in unit_positions:
                                target_pos = unit_positions[target_id]
                            else:
                                target_pos = None

                            # RULE: Shoot after fled
                            if shooter_id in units_fled:
                                stats['shoot_after_fled'][player] += 1
                                if stats['first_error_lines']['shoot_after_fled'][player] is None:
                                    stats['first_error_lines']['shoot_after_fled'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # RULE: Shoot at friendly
                            if target_id in unit_player and unit_player[target_id] == player:
                                stats['shoot_at_friendly'][player] += 1
                                if stats['first_error_lines']['shoot_at_friendly'][player] is None:
                                    stats['first_error_lines']['shoot_at_friendly'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # RULE: Shoot through wall
                            if target_pos and not has_line_of_sight(shooter_col, shooter_row, target_pos[0], target_pos[1], wall_hexes):
                                stats['shoot_through_wall'][player] += 1
                                if stats['first_error_lines']['shoot_through_wall'][player] is None:
                                    stats['first_error_lines']['shoot_through_wall'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # RULE: Shoot at engaged enemy
                            if target_pos and is_engaged(target_id, unit_player, unit_positions, unit_hp):
                                stats['shoot_at_engaged_enemy'][player] += 1
                                if stats['first_error_lines']['shoot_at_engaged_enemy'][player] is None:
                                    stats['first_error_lines']['shoot_at_engaged_enemy'][player] = {'episode': current_episode_num, 'line': line.strip()}

                            # Check PISTOL weapon rules
                            weapon_match = re.search(r'with \[([^\]]+)\]', action_desc)
                            if weapon_match and target_pos:
                                weapon_display_name = weapon_match.group(1)
                                weapon_name_lower = weapon_display_name.lower()
                                
                                shooter_unit_type = unit_types.get(shooter_id, '')
                                weapons_info = unit_weapons_cache.get(shooter_unit_type, [])
                                
                                is_pistol = False
                                weapon_found = False
                                for weapon_info in weapons_info:
                                    if weapon_info['name'].lower() == weapon_name_lower:
                                        is_pistol = weapon_info['is_pistol']
                                        weapon_found = True
                                        break
                                
                                distance = calculate_hex_distance(shooter_col, shooter_row, target_pos[0], target_pos[1])
                                
                                if weapon_found:
                                    if is_pistol:
                                        if distance == 1:
                                            stats['pistol_shots'][player]['adjacent'] += 1
                                        else:
                                            stats['pistol_shots'][player]['not_adjacent'] += 1
                                    else:
                                        if distance == 1:
                                            stats['non_pistol_adjacent_shots'][player] += 1

                            # Track shots after advance
                            if shooter_id in units_advanced:
                                stats['shots_after_advance'][player] += 1

                            # Target priority analysis
                            stats['target_priority'][player]['total_shots'] += 1
                            target_was_wounded = target_id in stats['wounded_enemies'][player]
                            
                            wounded_in_los = set()
                            for wounded_id in stats['wounded_enemies'][player]:
                                if wounded_id in unit_positions and wounded_id in unit_hp and unit_hp.get(wounded_id, 0) > 0:
                                    wounded_pos = unit_positions[wounded_id]
                                    if has_line_of_sight(shooter_col, shooter_row, wounded_pos[0], wounded_pos[1], wall_hexes):
                                        wounded_in_los.add(wounded_id)

                            if target_was_wounded:
                                stats['target_priority'][player]['shots_at_wounded_in_los'] += 1
                            elif len(wounded_in_los) > 0:
                                stats['target_priority'][player]['shots_at_full_hp_while_wounded_in_los'] += 1
                            else:
                                stats['target_priority'][player]['shots_at_wounded_in_los'] += 1

                            # Apply damage
                            damage_match = re.search(r'Dmg:(\d+)', action_desc)
                            if damage_match:
                                damage = int(damage_match.group(1))
                                if damage > 0 and target_id in unit_hp:
                                    unit_hp[target_id] -= damage
                                    if unit_hp[target_id] <= 0:
                                        target_type = unit_types.get(target_id, "Unknown")
                                        stats['current_episode_deaths'].append((player, target_id, target_type))
                                        stats['wounded_enemies'][player].discard(target_id)
                                        if target_id in unit_positions:
                                            del unit_positions[target_id]
                                    else:
                                        stats['wounded_enemies'][player].add(target_id)

                        # Sample action
                        if not stats['sample_actions']['shoot']:
                            stats['sample_actions']['shoot'] = line.strip()

                    elif 'wait' in action_desc.lower():
                        action_type = 'wait'
                        stats['shoot_vs_wait']['wait'] += 1
                        stats['shoot_vs_wait_by_player'][player]['wait'] += 1

                        if phase == 'SHOOT':
                            unit_match = re.search(r'Unit (\d+)\((\d+), (\d+)\)', action_desc)
                            if unit_match:
                                wait_unit_id = unit_match.group(1)
                                wait_col = int(unit_match.group(2))
                                wait_row = int(unit_match.group(3))
                                
                                wait_unit_type = unit_types.get(wait_unit_id, 'Unknown')
                                available_weapons = unit_weapons_cache.get(wait_unit_type, [])
                                ranged_weapons = [w for w in available_weapons if w.get('range', 0) > 0]
                                
                                enemy_player = 3 - player
                                is_adj = False
                                for uid, p in unit_player.items():
                                    if p == enemy_player and unit_hp.get(uid, 0) > 0 and uid in unit_positions:
                                        enemy_pos = unit_positions[uid]
                                        if is_adjacent(wait_col, wait_row, enemy_pos[0], enemy_pos[1]):
                                            is_adj = True
                                            break
                                
                                if is_adj:
                                    has_pistol = any(w.get('is_pistol', False) for w in ranged_weapons)
                                    if not has_pistol:
                                        stats['shoot_vs_wait']['wait'] -= 1
                                        stats['shoot_vs_wait_by_player'][player]['wait'] -= 1
                                        stats['shoot_vs_wait']['skip'] += 1
                                        stats['shoot_vs_wait_by_player'][player]['skip'] += 1
                                        continue
                                
                                valid_targets = []
                                for uid, p in unit_player.items():
                                    if p == enemy_player and unit_hp.get(uid, 0) > 0 and uid in unit_positions:
                                        enemy_pos = unit_positions[uid]
                                        distance = calculate_hex_distance(wait_col, wait_row, enemy_pos[0], enemy_pos[1])
                                        
                                        if not has_line_of_sight(wait_col, wait_row, enemy_pos[0], enemy_pos[1], wall_hexes):
                                            continue
                                        
                                        can_reach = False
                                        for weapon in ranged_weapons:
                                            weapon_range = weapon.get('range', 0)
                                            is_pistol = weapon.get('is_pistol', False)
                                            
                                            if distance > weapon_range:
                                                continue
                                            
                                            if distance == 1 and not is_pistol:
                                                continue
                                            
                                            target_in_melee = False
                                            for friendly_id, friendly_p in unit_player.items():
                                                if friendly_p == player and friendly_id != wait_unit_id:
                                                    if friendly_id in unit_positions:
                                                        friendly_pos = unit_positions[friendly_id]
                                                        if is_adjacent(enemy_pos[0], enemy_pos[1], friendly_pos[0], friendly_pos[1]):
                                                            target_in_melee = True
                                                            break
                                            
                                            if target_in_melee:
                                                continue
                                            
                                            can_reach = True
                                            break
                                        
                                        if can_reach:
                                            valid_targets.append(uid)

                                if valid_targets:
                                    stats['wait_by_phase'][player]['shoot_wait_with_los'] += 1
                                    stats['shoot_vs_wait_by_player'][player]['wait_with_targets'] += 1
                                else:
                                    stats['wait_by_phase'][player]['shoot_wait_no_los'] += 1
                                    stats['shoot_vs_wait_by_player'][player]['wait_no_targets'] += 1
                            else:
                                stats['wait_by_phase'][player]['shoot_wait_no_los'] += 1
                                stats['shoot_vs_wait_by_player'][player]['wait_no_targets'] += 1
                        elif phase == 'MOVE':
                            stats['wait_by_phase'][player]['move_wait'] += 1

                    elif 'skip' in action_desc.lower():
                        action_type = 'skip'
                        stats['shoot_vs_wait']['skip'] += 1
                        stats['shoot_vs_wait_by_player'][player]['skip'] += 1

                    elif 'advanced' in action_desc.lower():
                        action_type = 'advance'
                        
                        if phase == 'SHOOT':
                            stats['shoot_vs_wait']['advance'] += 1
                            stats['shoot_vs_wait_by_player'][player]['advance'] += 1

                        advance_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) ADVANCED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if advance_match:
                            advance_unit_id = advance_match.group(1)
                            start_col = int(advance_match.group(4))
                            start_row = int(advance_match.group(5))
                            dest_col = int(advance_match.group(6))
                            dest_row = int(advance_match.group(7))
                            
                            units_advanced.add(advance_unit_id)
                            
                            # RULE: Advance from adjacent
                            if is_adjacent_to_enemy(start_col, start_row, unit_player, unit_positions, unit_hp, player):
                                stats['advance_from_adjacent'][player] += 1
                                if stats['first_error_lines']['advance_from_adjacent'][player] is None:
                                    stats['first_error_lines']['advance_from_adjacent'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Position collision
                            colliding_units = [uid for uid, current_pos in unit_positions.items() 
                                              if current_pos == (dest_col, dest_row)
                                              and uid != advance_unit_id
                                              and unit_hp.get(uid, 0) > 0]
                            if colliding_units:
                                stats['unit_position_collisions'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'position': (dest_col, dest_row),
                                    'units': colliding_units + [advance_unit_id],
                                    'action': 'advance',
                                    'advance_from': (start_col, start_row),
                                    'advance_to': (dest_col, dest_row)
                                })
                            
                            # RULE: Move into wall
                            if (dest_col, dest_row) in wall_hexes:
                                stats['wall_collisions'][player] += 1
                                if stats['first_error_lines']['wall_collisions'][player] is None:
                                    stats['first_error_lines']['wall_collisions'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            unit_positions[advance_unit_id] = (dest_col, dest_row)
                            
                            # Sample action
                            if not stats['sample_actions']['advance']:
                                stats['sample_actions']['advance'] = line.strip()
                        else:
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Advance action missing 'from/to' format: {action_desc[:100]}"
                            })

                    elif 'charge' in action_desc.lower():
                        action_type = 'charge'
                        
                        # Try successful charge format: "Unit X(col,row) CHARGED unit Y(col,row) from (start_col,start_row) to (dest_col,dest_row)"
                        charge_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) CHARGED unit (?:\d+|None)(?:\((\d+),\s*(\d+)\))? from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if charge_match:
                            charge_unit_id = charge_match.group(1)
                            dest_col = int(charge_match.group(8))  # from "to (dest_col,dest_row)"
                            dest_row = int(charge_match.group(9))
                            start_col = int(charge_match.group(6))  # from "from (start_col,start_row)"
                            start_row = int(charge_match.group(7))
                            
                            # RULE: Charge from adjacent
                            if is_adjacent_to_enemy(start_col, start_row, unit_player, unit_positions, unit_hp, player):
                                stats['charge_from_adjacent'][player] += 1
                                if stats['first_error_lines']['charge_from_adjacent'][player] is None:
                                    stats['first_error_lines']['charge_from_adjacent'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Charge after fled
                            if charge_unit_id in units_fled:
                                stats['charge_after_fled'][player] += 1
                                if stats['first_error_lines']['charge_after_fled'][player] is None:
                                    stats['first_error_lines']['charge_after_fled'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Position collision
                            if (start_col, start_row) != (dest_col, dest_row):
                                colliding_units = [uid for uid, current_pos in unit_positions.items() 
                                                  if current_pos == (dest_col, dest_row)
                                                  and uid != charge_unit_id
                                                  and unit_hp.get(uid, 0) > 0]
                                if colliding_units:
                                    stats['unit_position_collisions'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'position': (dest_col, dest_row),
                                        'units': colliding_units + [charge_unit_id],
                                        'action': 'charge',
                                        'charge_from': (start_col, start_row),
                                        'charge_to': (dest_col, dest_row)
                                    })
                            
                            unit_positions[charge_unit_id] = (dest_col, dest_row)
                            
                            # Sample action
                            if not stats['sample_actions']['charge']:
                                stats['sample_actions']['charge'] = line.strip()
                        else:
                            # Check if it's a FAILED charge (valid format, just failed)
                            failed_charge_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) FAILED charge to unit', action_desc)
                            if not failed_charge_match:
                                # Only log as parse error if it's not a FAILED charge
                                stats['parse_errors'].append({
                                    'episode': current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': f"Charge action missing expected format: {action_desc[:100]}"
                                })

                    elif 'moves' in action_desc.lower() or 'moved' in action_desc.lower():
                        action_type = 'move'
                        
                        move_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) MOVED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if move_match:
                            move_unit_id = move_match.group(1)
                            start_col = int(move_match.group(4))
                            start_row = int(move_match.group(5))
                            dest_col = int(move_match.group(6))
                            dest_row = int(move_match.group(7))
                            
                            units_moved.add(move_unit_id)
                            
                            # RULE: Detect fled (was adjacent to enemy at start of MOVE phase, then moved)
                            if move_unit_id in positions_at_move_phase_start:
                                start_pos = positions_at_move_phase_start[move_unit_id]
                                if is_adjacent_to_enemy(start_pos[0], start_pos[1], unit_player, 
                                                       positions_at_move_phase_start, unit_hp, player):
                                    units_fled.add(move_unit_id)
                            
                            if (start_col, start_row) != (dest_col, dest_row):
                                # RULE: Position collision
                                colliding_units = [uid for uid, current_pos in unit_positions.items() 
                                                  if current_pos == (dest_col, dest_row)
                                                  and uid != move_unit_id
                                                  and unit_hp.get(uid, 0) > 0]
                                if colliding_units:
                                    stats['unit_position_collisions'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'position': (dest_col, dest_row),
                                        'units': colliding_units + [move_unit_id],
                                        'action': 'move',
                                        'move_from': (start_col, start_row),
                                        'move_to': (dest_col, dest_row)
                                    })
                                
                                # RULE: Move to adjacent enemy
                                if is_adjacent_to_enemy(dest_col, dest_row, unit_player, unit_positions, unit_hp, player):
                                    stats['move_to_adjacent_enemy'][player] += 1
                                    if stats['first_error_lines']['move_to_adjacent_enemy'][player] is None:
                                        stats['first_error_lines']['move_to_adjacent_enemy'][player] = {'episode': current_episode_num, 'line': line.strip()}
                                
                                # RULE: Move into wall
                                if (dest_col, dest_row) in wall_hexes:
                                    stats['wall_collisions'][player] += 1
                            
                            unit_positions[move_unit_id] = (dest_col, dest_row)
                            
                            # Sample action
                            if not stats['sample_actions']['move']:
                                stats['sample_actions']['move'] = line.strip()
                        else:
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Move action missing 'from/to' format: {action_desc[:100]}"
                            })

                    elif 'fought' in action_desc.lower() or 'attacked' in action_desc.lower():
                        action_type = 'fight'
                        units_fought.add(unit_id) if 'unit_id' in locals() else None
                        
                        fight_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) ATTACKED unit (\d+)\((\d+),\s*(\d+)\)', action_desc)
                        if fight_match:
                            fighter_id = fight_match.group(1)
                            fighter_col = int(fight_match.group(2))
                            fighter_row = int(fight_match.group(3))
                            target_id = fight_match.group(4)
                            target_col = int(fight_match.group(5))
                            target_row = int(fight_match.group(6))
                            
                            # RULE: Fight from non-adjacent
                            if not is_adjacent(fighter_col, fighter_row, target_col, target_row):
                                stats['fight_from_non_adjacent'][player] += 1
                                if stats['first_error_lines']['fight_from_non_adjacent'][player] is None:
                                    stats['first_error_lines']['fight_from_non_adjacent'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # RULE: Fight friendly
                            if target_id in unit_player and unit_player[target_id] == player:
                                stats['fight_friendly'][player] += 1
                                if stats['first_error_lines']['fight_friendly'][player] is None:
                                    stats['first_error_lines']['fight_friendly'][player] = {'episode': current_episode_num, 'line': line.strip()}
                            
                            # Sample action
                            if not stats['sample_actions']['fight']:
                                stats['sample_actions']['fight'] = line.strip()
                        else:
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Fight action missing expected format: {action_desc[:100]}"
                            })
                    else:
                        action_type = 'other'

                    stats['actions_by_type'][action_type] += 1
                    stats['actions_by_player'][player][action_type] += 1

                current_episode.append(line.strip())
    
    # Check if last episode ended without EPISODE END
    if current_episode:
        stats['episodes_without_end'].append({
            'episode_num': current_episode_num,
            'actions': episode_actions,
            'turn': episode_turn,
            'last_line': current_episode[-1][:100] if current_episode else 'N/A'
        })
        
        stats['episode_lengths'].append(episode_actions)
        # Save turn distribution for last episode
        if episode_turn > 0:
            stats['turns_distribution'][episode_turn] += 1

    return stats


def print_statistics(stats: Dict):
    """Print formatted statistics."""
    print("=" * 80)
    print("STEP.LOG ANALYSIS - GAME RULES VALIDATION")
    print("=" * 80)
    
    # MÉTRIQUES GLOBALES
    print(f"\nTotal Episodes: {stats['total_episodes']}")
    print(f"Total Actions: {stats['total_actions']}")
    
    if stats['episode_lengths']:
        avg_length = sum(stats['episode_lengths']) / len(stats['episode_lengths'])
        print(f"Average Actions per Episode: {avg_length:.1f}")
        print(f"Min/Max Actions per Episode: {min(stats['episode_lengths'])}/{max(stats['episode_lengths'])}")
    
    # RÉSULTATS DES PARTIES
    print("\n" + "-" * 80)
    print("WIN METHODS")
    print("-" * 80)
    print(f"{'Method':<20} {'Agent Wins (P1)':>18} {'Bot Wins (P2)':>18}")
    print("-" * 80)
    
    p1_total = sum(stats['win_methods'][1].values())
    p2_total = sum(stats['win_methods'][2].values())
    draws = stats['win_methods'][-1]['draw']
    
    for method in ['elimination', 'objectives', 'value_tiebreaker']:
        p1_count = stats['win_methods'][1].get(method, 0)
        p2_count = stats['win_methods'][2].get(method, 0)
        p1_pct = (p1_count / p1_total * 100) if p1_total > 0 else 0
        p2_pct = (p2_count / p2_total * 100) if p2_total > 0 else 0
        method_display = method.replace('_', ' ').title()
        print(f"{method_display:<20} {p1_count:6d} ({p1_pct:5.1f}%)   {p2_count:6d} ({p2_pct:5.1f}%)")
    
    print("-" * 80)
    total_games = p1_total + p2_total + draws
    p1_pct = (p1_total / total_games * 100) if total_games > 0 else 0
    p2_pct = (p2_total / total_games * 100) if total_games > 0 else 0
    draw_pct = (draws / total_games * 100) if total_games > 0 else 0
    print(f"{'TOTAL WINS':<20} {p1_total:6d} ({p1_pct:5.1f}%)   {p2_total:6d} ({p2_pct:5.1f}%)")
    print(f"{'DRAWS':<20} {draws:6d} ({draw_pct:5.1f}%)")
    
    # WINS BY SCENARIO
    if stats['wins_by_scenario']:
        print("\n" + "-" * 80)
        print("WINS BY SCENARIO")
        print("-" * 80)
        print(f"{'Scenario':<40} {'Agent (P1)':>15} {'Bot (P2)':>15} {'Draws':>10}")
        print("-" * 80)
        
        scenario_totals = []
        for scenario, wins in stats['wins_by_scenario'].items():
            total = wins['p1'] + wins['p2'] + wins['draws']
            scenario_totals.append((scenario, wins, total))
        scenario_totals.sort(key=lambda x: -x[2])
        
        for scenario, wins, total in scenario_totals:
            p1_count = wins['p1']
            p2_count = wins['p2']
            draws_count = wins['draws']
            p1_pct = (p1_count / total * 100) if total > 0 else 0
            p2_pct = (p2_count / total * 100) if total > 0 else 0
            draws_pct = (draws_count / total * 100) if total > 0 else 0
            bot_match = re.search(r'bot-(\d+)', scenario, re.IGNORECASE)
            if bot_match:
                scenario_display = f"bot-{bot_match.group(1)}"
            else:
                scenario_display = scenario[:39]
            print(f"{scenario_display:<40} {p1_count:5d} ({p1_pct:4.1f}%) {p2_count:5d} ({p2_pct:4.1f}%) {draws_count:5d} ({draws_pct:4.1f}%)")
    
    # TURN DISTRIBUTION
    print("\n" + "-" * 80)
    print("TURN DISTRIBUTION")
    print("-" * 80)
    if stats['turns_distribution']:
        for turn in sorted(stats['turns_distribution'].keys()):
            count = stats['turns_distribution'][turn]
            pct = (count / stats['total_episodes'] * 100) if stats['total_episodes'] > 0 else 0
            print(f"Turn {turn}: {count:3d} games ({pct:5.1f}%)")
    else:
        print("No turn data recorded.")
    
    # ACTIONS BY TYPE
    print("\n" + "-" * 80)
    print("ACTIONS BY TYPE")
    print("-" * 80)
    print(f"{'Action':<12} {'Agent (P1)':>18} {'Bot (P2)':>18}")
    print("-" * 80)
    
    all_actions = set(stats['actions_by_player'][1].keys()) | set(stats['actions_by_player'][2].keys())
    action_totals = [(a, stats['actions_by_player'][1].get(a, 0) + stats['actions_by_player'][2].get(a, 0))
                     for a in all_actions]
    action_totals.sort(key=lambda x: -x[1])
    
    agent_total = sum(stats['actions_by_player'][1].values())
    bot_total = sum(stats['actions_by_player'][2].values())
    
    for action_type, _ in action_totals:
        agent_count = stats['actions_by_player'][1].get(action_type, 0)
        bot_count = stats['actions_by_player'][2].get(action_type, 0)
        agent_pct = (agent_count / agent_total * 100) if agent_total > 0 else 0
        bot_pct = (bot_count / bot_total * 100) if bot_total > 0 else 0
        print(f"{action_type:<12} {agent_count:6d} ({agent_pct:5.1f}%)   {bot_count:6d} ({bot_pct:5.1f}%)")
    
    # SHOOTING PHASE BEHAVIOR
    print("\n" + "-" * 80)
    print("SHOOTING PHASE BEHAVIOR")
    print("-" * 80)
    print(f"{'Action':<12} {'Agent (P1)':>18} {'Bot (P2)':>18}")
    print("-" * 80)
    
    agent_shoot_total = (stats['shoot_vs_wait_by_player'][1]['shoot'] +
                        stats['shoot_vs_wait_by_player'][1]['wait'] +
                        stats['shoot_vs_wait_by_player'][1]['skip'] +
                        stats['shoot_vs_wait_by_player'][1]['advance'])
    bot_shoot_total = (stats['shoot_vs_wait_by_player'][2]['shoot'] +
                      stats['shoot_vs_wait_by_player'][2]['wait'] +
                      stats['shoot_vs_wait_by_player'][2]['skip'] +
                      stats['shoot_vs_wait_by_player'][2]['advance'])
    
    for action in ['shoot', 'skip', 'advance']:
        agent_count = stats['shoot_vs_wait_by_player'][1][action]
        bot_count = stats['shoot_vs_wait_by_player'][2][action]
        agent_pct = (agent_count / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
        bot_pct = (bot_count / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
        print(f"{action.capitalize():<12} {agent_count:6d} ({agent_pct:5.1f}%)   {bot_count:6d} ({bot_pct:5.1f}%)")
    
    agent_wait_with = stats['shoot_vs_wait_by_player'][1]['wait_with_targets']
    bot_wait_with = stats['shoot_vs_wait_by_player'][2]['wait_with_targets']
    agent_wait_with_pct = (agent_wait_with / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_with_pct = (bot_wait_with / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    print(f"{'Wait (targets)':<12} {agent_wait_with:6d} ({agent_wait_with_pct:5.1f}%)   {bot_wait_with:6d} ({bot_wait_with_pct:5.1f}%)")
    
    agent_wait_no = stats['shoot_vs_wait_by_player'][1]['wait_no_targets']
    bot_wait_no = stats['shoot_vs_wait_by_player'][2]['wait_no_targets']
    agent_wait_no_pct = (agent_wait_no / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_no_pct = (bot_wait_no / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    print(f"{'Wait (no targets)':<12} {agent_wait_no:6d} ({agent_wait_no_pct:5.1f}%)   {bot_wait_no:6d} ({bot_wait_no_pct:5.1f}%)")
    
    agent_shots_after_advance = stats['shots_after_advance'][1]
    bot_shots_after_advance = stats['shots_after_advance'][2]
    agent_pct_after_advance = (agent_shots_after_advance / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_pct_after_advance = (bot_shots_after_advance / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    print(f"{'Shoot+Advance':<12} {agent_shots_after_advance:6d} ({agent_pct_after_advance:5.1f}%)   {bot_shots_after_advance:6d} ({bot_pct_after_advance:5.1f}%)")
    
    # PISTOL WEAPON SHOTS
    print("\n" + "-" * 80)
    print("PISTOL WEAPON SHOTS BY ADJACENCY")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    print("-" * 80)
    agent_pistol_adj = stats['pistol_shots'][1]['adjacent']
    bot_pistol_adj = stats['pistol_shots'][2]['adjacent']
    agent_pistol_not_adj = stats['pistol_shots'][1]['not_adjacent']
    bot_pistol_not_adj = stats['pistol_shots'][2]['not_adjacent']
    agent_pistol_total = agent_pistol_adj + agent_pistol_not_adj
    bot_pistol_total = bot_pistol_adj + bot_pistol_not_adj
    
    agent_pistol_adj_pct = (agent_pistol_adj / agent_pistol_total * 100) if agent_pistol_total > 0 else 0
    bot_pistol_adj_pct = (bot_pistol_adj / bot_pistol_total * 100) if bot_pistol_total > 0 else 0
    agent_pistol_not_adj_pct = (agent_pistol_not_adj / agent_pistol_total * 100) if agent_pistol_total > 0 else 0
    bot_pistol_not_adj_pct = (bot_pistol_not_adj / bot_pistol_total * 100) if bot_pistol_total > 0 else 0
    
    print(f"PISTOL shots (adjacent):       {agent_pistol_adj:6d} ({agent_pistol_adj_pct:5.1f}%)  {bot_pistol_adj:6d} ({bot_pistol_adj_pct:5.1f}%)")
    print(f"PISTOL shots (not adjacent):   {agent_pistol_not_adj:6d} ({agent_pistol_not_adj_pct:5.1f}%)  {bot_pistol_not_adj:6d} ({bot_pistol_not_adj_pct:5.1f}%)")
    print(f"Total PISTOL shots:            {agent_pistol_total:6d}           {bot_pistol_total:6d}")
    
    agent_non_pistol_adj = stats['non_pistol_adjacent_shots'][1]
    bot_non_pistol_adj = stats['non_pistol_adjacent_shots'][2]
    print(f"Non-PISTOL shots (adjacent):   {agent_non_pistol_adj:6d}           {bot_non_pistol_adj:6d}")
    
    # WAIT BEHAVIOR
    print("\n" + "-" * 80)
    print("WAIT BEHAVIOR BY PHASE")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    print("-" * 80)
    agent_move_wait = stats['wait_by_phase'][1]['move_wait']
    bot_move_wait = stats['wait_by_phase'][2]['move_wait']
    agent_shoot_wait_los = stats['wait_by_phase'][1]['shoot_wait_with_los']
    bot_shoot_wait_los = stats['wait_by_phase'][2]['shoot_wait_with_los']
    agent_shoot_wait_no_los = stats['wait_by_phase'][1]['shoot_wait_no_los']
    bot_shoot_wait_no_los = stats['wait_by_phase'][2]['shoot_wait_no_los']
    
    print(f"MOVE phase waits:             {agent_move_wait:6d}           {bot_move_wait:6d}")
    print(f"SHOOT waits (enemies in LOS): {agent_shoot_wait_los:6d}           {bot_shoot_wait_los:6d}")
    print(f"SHOOT waits (no LOS):         {agent_shoot_wait_no_los:6d}           {bot_shoot_wait_no_los:6d}")
    
    # TARGET PRIORITY
    print("\n" + "-" * 80)
    print("TARGET PRIORITY ANALYSIS (Focus Fire)")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    print("-" * 80)
    
    agent_bad = stats['target_priority'][1]['shots_at_full_hp_while_wounded_in_los']
    bot_bad = stats['target_priority'][2]['shots_at_full_hp_while_wounded_in_los']
    agent_good = stats['target_priority'][1]['shots_at_wounded_in_los']
    bot_good = stats['target_priority'][2]['shots_at_wounded_in_los']
    agent_total_shots = stats['target_priority'][1]['total_shots']
    bot_total_shots = stats['target_priority'][2]['total_shots']
    
    agent_bad_pct = (agent_bad / agent_total_shots * 100) if agent_total_shots > 0 else 0
    bot_bad_pct = (bot_bad / bot_total_shots * 100) if bot_total_shots > 0 else 0
    agent_good_pct = (agent_good / agent_total_shots * 100) if agent_total_shots > 0 else 0
    bot_good_pct = (bot_good / bot_total_shots * 100) if bot_total_shots > 0 else 0
    
    print(f"FAILURES (shot full HP while")
    print(f"  wounded in LOS):            {agent_bad:6d} ({agent_bad_pct:5.1f}%)  {bot_bad:6d} ({bot_bad_pct:5.1f}%)")
    print(f"SUCCESS (shot wounded or")
    print(f"  no wounded in LOS):         {agent_good:6d} ({agent_good_pct:5.1f}%)  {bot_good:6d} ({bot_good_pct:5.1f}%)")
    print(f"Total shots:                  {agent_total_shots:6d}           {bot_total_shots:6d}")
    
    # DEATH ORDER
    print("\n" + "-" * 80)
    print("ENEMY DEATH ORDER ANALYSIS")
    print("-" * 80)
    
    if stats['death_orders']:
        death_order_counter = Counter()
        for death_order in stats['death_orders']:
            units_killed = tuple(f"{unit_type}({unit_id})" for player, unit_id, unit_type in death_order)
            if units_killed:
                death_order_counter[units_killed] += 1
        
        print(f"Total episodes with kills: {len(stats['death_orders'])}")
        print(f"\nMost common death orders:")
        for order, count in death_order_counter.most_common(10):
            pct = (count / len(stats['death_orders']) * 100)
            order_str = " → ".join(order)
            print(f"  {order_str}: {count} times ({pct:.1f}%)")
        
        player_kills = {1: 0, 2: 0}
        for death_order in stats['death_orders']:
            for player, unit_id, unit_type in death_order:
                player_kills[player] += 1
        print(f"\nKills by player:")
        print(f"  Agent (P1) kills: {player_kills[1]}")
        print(f"  Bot (P2) kills:   {player_kills[2]}")
    else:
        print("No kills recorded in any episode.")
    
    # MOVEMENT ERRORS
    print("\n" + "-" * 80)
    print("MOVEMENT ERRORS")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    print("-" * 80)
    agent_walls = stats['wall_collisions'][1]
    bot_walls = stats['wall_collisions'][2]
    print(f"Moves into walls:             {agent_walls:6d}           {bot_walls:6d}")
    if agent_walls > 0 and stats['first_error_lines']['wall_collisions'][1]:
        first_err = stats['first_error_lines']['wall_collisions'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_walls > 0 and stats['first_error_lines']['wall_collisions'][2]:
        first_err = stats['first_error_lines']['wall_collisions'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_move_adj = stats['move_to_adjacent_enemy'][1]
    bot_move_adj = stats['move_to_adjacent_enemy'][2]
    print(f"Moves to adjacent enemy:      {agent_move_adj:6d}           {bot_move_adj:6d}")
    if agent_move_adj > 0 and stats['first_error_lines']['move_to_adjacent_enemy'][1]:
        first_err = stats['first_error_lines']['move_to_adjacent_enemy'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_move_adj > 0 and stats['first_error_lines']['move_to_adjacent_enemy'][2]:
        first_err = stats['first_error_lines']['move_to_adjacent_enemy'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # SHOOTING ERRORS
    print("\n" + "-" * 80)
    print("SHOOTING ERRORS")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    print("-" * 80)
    agent_advance_adj = stats['advance_from_adjacent'][1]
    bot_advance_adj = stats['advance_from_adjacent'][2]
    print(f"Advances from adjacent hex:   {agent_advance_adj:6d}           {bot_advance_adj:6d}")
    if agent_advance_adj > 0 and stats['first_error_lines']['advance_from_adjacent'][1]:
        first_err = stats['first_error_lines']['advance_from_adjacent'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_advance_adj > 0 and stats['first_error_lines']['advance_from_adjacent'][2]:
        first_err = stats['first_error_lines']['advance_from_adjacent'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_wall = stats['shoot_through_wall'][1]
    bot_shoot_wall = stats['shoot_through_wall'][2]
    print(f"Shoot through wall:           {agent_shoot_wall:6d}           {bot_shoot_wall:6d}")
    if agent_shoot_wall > 0 and stats['first_error_lines']['shoot_through_wall'][1]:
        first_err = stats['first_error_lines']['shoot_through_wall'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_wall > 0 and stats['first_error_lines']['shoot_through_wall'][2]:
        first_err = stats['first_error_lines']['shoot_through_wall'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_fled = stats['shoot_after_fled'][1]
    bot_shoot_fled = stats['shoot_after_fled'][2]
    print(f"Shoot after fled:             {agent_shoot_fled:6d}           {bot_shoot_fled:6d}")
    if agent_shoot_fled > 0 and stats['first_error_lines']['shoot_after_fled'][1]:
        first_err = stats['first_error_lines']['shoot_after_fled'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_fled > 0 and stats['first_error_lines']['shoot_after_fled'][2]:
        first_err = stats['first_error_lines']['shoot_after_fled'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_friendly = stats['shoot_at_friendly'][1]
    bot_shoot_friendly = stats['shoot_at_friendly'][2]
    print(f"Shoot at friendly unit:       {agent_shoot_friendly:6d}           {bot_shoot_friendly:6d}")
    if agent_shoot_friendly > 0 and stats['first_error_lines']['shoot_at_friendly'][1]:
        first_err = stats['first_error_lines']['shoot_at_friendly'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_friendly > 0 and stats['first_error_lines']['shoot_at_friendly'][2]:
        first_err = stats['first_error_lines']['shoot_at_friendly'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_shoot_engaged = stats['shoot_at_engaged_enemy'][1]
    bot_shoot_engaged = stats['shoot_at_engaged_enemy'][2]
    print(f"Shoot at engaged enemy:       {agent_shoot_engaged:6d}           {bot_shoot_engaged:6d}")
    if agent_shoot_engaged > 0 and stats['first_error_lines']['shoot_at_engaged_enemy'][1]:
        first_err = stats['first_error_lines']['shoot_at_engaged_enemy'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_shoot_engaged > 0 and stats['first_error_lines']['shoot_at_engaged_enemy'][2]:
        first_err = stats['first_error_lines']['shoot_at_engaged_enemy'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # CHARGE ERRORS
    print("\n" + "-" * 80)
    print("CHARGE ERRORS")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    print("-" * 80)
    agent_charge_adj = stats['charge_from_adjacent'][1]
    bot_charge_adj = stats['charge_from_adjacent'][2]
    print(f"Charges from adjacent hex:     {agent_charge_adj:6d}           {bot_charge_adj:6d}")
    if agent_charge_adj > 0 and stats['first_error_lines']['charge_from_adjacent'][1]:
        first_err = stats['first_error_lines']['charge_from_adjacent'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_charge_adj > 0 and stats['first_error_lines']['charge_from_adjacent'][2]:
        first_err = stats['first_error_lines']['charge_from_adjacent'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_charge_fled = stats['charge_after_fled'][1]
    bot_charge_fled = stats['charge_after_fled'][2]
    print(f"Charge after fled:            {agent_charge_fled:6d}           {bot_charge_fled:6d}")
    if agent_charge_fled > 0 and stats['first_error_lines']['charge_after_fled'][1]:
        first_err = stats['first_error_lines']['charge_after_fled'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_charge_fled > 0 and stats['first_error_lines']['charge_after_fled'][2]:
        first_err = stats['first_error_lines']['charge_after_fled'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # FIGHT ERRORS
    print("\n" + "-" * 80)
    print("FIGHT ERRORS")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P1)':>15s} {'Bot (P2)':>15s}")
    print("-" * 80)
    agent_fight_non_adj = stats['fight_from_non_adjacent'][1]
    bot_fight_non_adj = stats['fight_from_non_adjacent'][2]
    print(f"Fight from non-adjacent hex:  {agent_fight_non_adj:6d}           {bot_fight_non_adj:6d}")
    if agent_fight_non_adj > 0 and stats['first_error_lines']['fight_from_non_adjacent'][1]:
        first_err = stats['first_error_lines']['fight_from_non_adjacent'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_non_adj > 0 and stats['first_error_lines']['fight_from_non_adjacent'][2]:
        first_err = stats['first_error_lines']['fight_from_non_adjacent'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    agent_fight_friendly = stats['fight_friendly'][1]
    bot_fight_friendly = stats['fight_friendly'][2]
    print(f"Fight a friendly unit:        {agent_fight_friendly:6d}           {bot_fight_friendly:6d}")
    if agent_fight_friendly > 0 and stats['first_error_lines']['fight_friendly'][1]:
        first_err = stats['first_error_lines']['fight_friendly'][1]
        print(f"  First P1 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    if bot_fight_friendly > 0 and stats['first_error_lines']['fight_friendly'][2]:
        first_err = stats['first_error_lines']['fight_friendly'][2]
        print(f"  First P2 occurrence (Episode {first_err['episode']}): {first_err['line']}")
    
    # POSITION COLLISIONS
    if stats['unit_position_collisions']:
        print("\n" + "-" * 80)
        print("⚠️  UNIT POSITION COLLISIONS (2+ units in same hex)")
        print("-" * 80)
        print(f"Total collisions: {len(stats['unit_position_collisions'])}")
        for i, collision in enumerate(stats['unit_position_collisions'][:10]):
            units_str = ", ".join([f"Unit {uid}" for uid in collision['units']])
            if 'charge_from' in collision:
                print(f"  {i+1}. Episode #{collision['episode']}, Turn {collision['turn']}, {collision['action']}: {units_str} at {collision['position']} (from {collision['charge_from']})")
            else:
                print(f"  {i+1}. Episode #{collision['episode']}, Turn {collision['turn']}, {collision['action']}: {units_str} at {collision['position']}")
        if len(stats['unit_position_collisions']) > 10:
            print(f"  ... and {len(stats['unit_position_collisions']) - 10} more")
    
    # PARSE ERRORS
    if stats['parse_errors']:
        print("\n" + "-" * 80)
        print("⚠️  PARSE ERRORS (Non-standard log format)")
        print("-" * 80)
        print(f"Total parse errors: {len(stats['parse_errors'])}")
        for i, error in enumerate(stats['parse_errors'][:10]):
            print(f"  {i+1}. Episode #{error['episode']}, Turn {error['turn']}, {error['phase']}: {error['error']}")
            print(f"      Line: {error['line']}")
        if len(stats['parse_errors']) > 10:
            print(f"  ... and {len(stats['parse_errors']) - 10} more")
    
    # EPISODES WITHOUT END
    if stats['episodes_without_end']:
        print("\n" + "-" * 80)
        print("⚠️  EPISODES WITHOUT EPISODE END (INCOMPLETE EPISODES)")
        print("-" * 80)
        print(f"Total: {len(stats['episodes_without_end'])} episodes")
        for i, ep in enumerate(stats['episodes_without_end'][:5]):
            print(f"  {i+1}. Episode #{ep['episode_num']}, Actions={ep['actions']}, Turn={ep['turn']}, Last: {ep['last_line']}")
        if len(stats['episodes_without_end']) > 5:
            print(f"  ... and {len(stats['episodes_without_end']) - 5} more")
    
    # EPISODES WITHOUT METHOD
    if stats['episodes_without_method']:
        print("\n" + "-" * 80)
        print("⚠️  EPISODES WITHOUT WIN_METHOD (BUG DETECTED)")
        print("-" * 80)
        print(f"Total: {len(stats['episodes_without_method'])} episodes")
        for i, ep in enumerate(stats['episodes_without_method'][:5]):
            print(f"  {i+1}. Winner={ep['winner']}, Line: {ep['line']}")
        if len(stats['episodes_without_method']) > 5:
            print(f"  ... and {len(stats['episodes_without_method']) - 5} more")
    
    # SAMPLE ACTIONS
    print("\n" + "=" * 80)
    print("SAMPLE ACTIONS")
    print("=" * 80)
    for action_type in ['move', 'shoot', 'advance', 'charge', 'fight']:
        if stats['sample_actions'][action_type]:
            print(f"\n--- {action_type.upper()} ---")
            print(stats['sample_actions'][action_type])
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python ai/analyzer.py step.log")
        sys.exit(1)

    log_file = sys.argv[1]
    print(f"Analyzing {log_file}...")

    try:
        stats = parse_step_log(log_file)
        print_statistics(stats)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)