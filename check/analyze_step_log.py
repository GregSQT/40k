#!/usr/bin/env python3
"""
analyze_step_log.py - Analyze step.log and output compact statistics
Run this locally: python check/analyze_step_log.py step.log
"""

import sys
import os
import re
from collections import defaultdict, Counter

# Add project root to Python path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def calculate_hex_distance(col1, row1, col2, row2):
    """Calculate hex distance using cube coordinates."""
    # Convert offset to cube
    x1 = col1
    z1 = row1 - ((col1 - (col1 & 1)) >> 1)
    y1 = -x1 - z1

    x2 = col2
    z2 = row2 - ((col2 - (col2 & 1)) >> 1)
    y2 = -x2 - z2

    # Cube distance
    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


def get_hex_line(start_col, start_row, end_col, end_row):
    """Get all hexes on a line between two points (simplified Bresenham for hex)."""
    hexes = []
    distance = calculate_hex_distance(start_col, start_row, end_col, end_row)
    if distance == 0:
        return [(start_col, start_row)]

    for i in range(distance + 1):
        t = i / distance
        # Linear interpolation
        col = round(start_col + (end_col - start_col) * t)
        row = round(start_row + (end_row - start_row) * t)
        if (col, row) not in hexes:
            hexes.append((col, row))

    return hexes


def has_line_of_sight(shooter_col, shooter_row, target_col, target_row, wall_hexes):
    """Check if there's clear LOS between shooter and target (no walls blocking)."""
    line = get_hex_line(shooter_col, shooter_row, target_col, target_row)
    # Check all hexes except start and end
    for col, row in line[1:-1]:
        if (col, row) in wall_hexes:
            return False
    return True

def is_adjacent_to_enemy(col, row, unit_player_dict, unit_positions_dict, unit_hp_dict, player):
    """Check if a hex is adjacent to any enemy unit."""
    enemy_player = 1 - player
    for uid, p in unit_player_dict.items():
        if p == enemy_player and unit_hp_dict.get(uid, 0) > 0 and uid in unit_positions_dict:
            enemy_pos = unit_positions_dict[uid]
            distance = calculate_hex_distance(col, row, enemy_pos[0], enemy_pos[1])
            if distance == 1:
                return True
    return False

def parse_log(filepath):
    """Parse step.log and extract statistics."""
    
    # Load unit weapons at script start using existing system
    from ai.unit_registry import UnitRegistry
    
    unit_registry = UnitRegistry()
    unit_weapons_cache = {}  # unit_type -> list of RNG_WEAPONS with {display_name, RNG, WEAPON_RULES, is_pistol}
    
    # Load weapons for each unit type
    for unit_type, unit_data in unit_registry.units.items():
        rng_weapons = unit_data.get("RNG_WEAPONS", [])
        # Extract relevant info: name, range, rules
        weapons_info = []
        for weapon in rng_weapons:
            # Check if weapon is a dict (expected) or string (fallback)
            if isinstance(weapon, dict):
                weapon_rules = weapon.get("WEAPON_RULES", [])
                weapons_info.append({
                    'name': weapon.get('display_name', ''),
                    'range': weapon.get('RNG', 0),
                    'rules': weapon_rules,
                    'is_pistol': 'PISTOL' in weapon_rules
                })
            elif isinstance(weapon, str):
                # Weapon is a string (code name) - skip or try to resolve
                # This shouldn't happen but handle gracefully
                continue
        unit_weapons_cache[unit_type] = weapons_info

    # Load wall hexes from scenario (will be populated per episode)
    wall_hexes = set()

    stats = {
        'total_episodes': 0,
        'total_actions': 0,
        'actions_by_type': Counter(),
        'actions_by_phase': Counter(),
        'actions_by_player': {0: Counter(), 1: Counter()},
        'shoot_vs_wait': {'shoot': 0, 'wait': 0, 'skip': 0, 'advance': 0},
        'turns_distribution': Counter(),
        'episode_lengths': [],
        'sample_games': {'win': None, 'loss': None, 'draw': None},
        'shoot_vs_wait_by_player': {
            0: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0},
            1: {'shoot': 0, 'wait': 0, 'wait_with_targets': 0, 'wait_no_targets': 0, 'skip': 0, 'advance': 0}
        },
        'wall_collisions': {0: 0, 1: 0},
        # Charge validation tracking
        'charge_from_adjacent': {0: 0, 1: 0},  # Charges starting from hex adjacent to enemy
        # Unit position collision tracking
        'unit_position_collisions': [],  # List of episodes with 2+ units in same hex
        # Move validation tracking
        'move_to_adjacent_enemy': {0: 0, 1: 0},  # Moves to hex adjacent to enemy
        # Target priority tracking - with LOS awareness
        'target_priority': {
            0: {'shots_at_wounded_in_los': 0, 'shots_at_full_hp_while_wounded_in_los': 0, 'total_shots': 0},
            1: {'shots_at_wounded_in_los': 0, 'shots_at_full_hp_while_wounded_in_los': 0, 'total_shots': 0}
        },
        # WAIT behavior - shoot waits only when had targets in LOS
        'wait_by_phase': {
            0: {'move_wait': 0, 'shoot_wait_with_los': 0, 'shoot_wait_no_los': 0},
            1: {'move_wait': 0, 'shoot_wait_with_los': 0, 'shoot_wait_no_los': 0}
        },
        # Track shots after advance (Assault weapon rule)
        'shots_after_advance': {0: 0, 1: 0},
        # Track PISTOL weapon shots by adjacency
        'pistol_shots': {
            0: {'adjacent': 0, 'not_adjacent': 0},
            1: {'adjacent': 0, 'not_adjacent': 0}
        },
        # Track non-PISTOL shots while adjacent (should not happen - rule violation)
        'non_pistol_adjacent_shots': {0: 0, 1: 0},
        # Enemy death order tracking with unit types
        'death_orders': [],
        'current_episode_deaths': [],
        # Parse error tracking (strict analyzer - no fallbacks)
        'parse_errors': [],
        # Track enemy HP and positions
        'wounded_enemies': {0: set(), 1: set()},
        # Track unit types for death order display
        'unit_types': {},  # unit_id -> unit_type (e.g., "Termagant", "Intercessor")
        # Win method tracking
        'win_methods': {
            0: {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},  # P0 wins by method
            1: {'elimination': 0, 'objectives': 0, 'value_tiebreaker': 0},  # P1 wins by method
            -1: {'draw': 0}  # Draws
        },
        # Track episodes that started but never ended
        'episodes_without_end': [],
        # Track episodes without win_method
        'episodes_without_method': [],
        # Track wins by scenario
        'wins_by_scenario': defaultdict(lambda: {'p0': 0, 'p1': 0, 'draws': 0}),
        # Debug stats
        'debug': {
            'units_initialized': 0,  # number of units initialized from starting positions
            'target_not_in_unit_hp': 0,  # target_id not found in unit_hp
            'weapon_not_found': 0,  # weapon not found in cache
            'shooter_unit_type_not_found': 0,  # shooter_unit_type not found in unit_types
            'weapon_found_but_not_pistol': 0,  # weapon found but is_pistol is False
            'weapon_is_pistol': 0,  # weapon found and is_pistol is True
            'pistol_target_pos_none': 0,  # PISTOL weapon but target_pos is None
            'pistol_shots_with_distance': 0,  # PISTOL shots that reached distance calculation
            'pistol_distance_1': 0,  # PISTOL shots at distance 1 (adjacent)
            'pistol_distance_not_1': 0,  # PISTOL shots at distance != 1 (not adjacent)
            'damage_match_found': 0,  # damage_match found in action_desc
            'damage_applied': 0,  # damage actually applied to unit_hp
        },
    }

    current_episode = []
    current_episode_num = 0  # Will be set to 1 when first episode starts
    current_scenario = 'Unknown'  # Track current scenario
    episode_turn = 0
    episode_actions = 0
    last_turn = 0  # Track last turn to detect turn changes

    # Track unit HP and positions for LOS calculation
    unit_hp = {}  # unit_id -> current HP
    unit_player = {}  # unit_id -> player (0 or 1)
    unit_positions = {}  # unit_id -> (col, row)
    unit_types = {}  # unit_id -> unit_type
    units_advanced_this_turn = set()  # Track units that advanced this turn (for Assault rule)
    positions_at_turn_start = {}  # unit_id -> (col, row) at start of current turn

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            # Episode start - check BEFORE skipping lines starting with ===
            # Format can be: === EPISODE START === or === EPISODE X START ===
            if '=== EPISODE' in line and 'START ===' in line:
                if current_episode:
                    # Previous episode ended without EPISODE END line
                    stats['episodes_without_end'].append({
                        'episode_num': current_episode_num,
                        'actions': episode_actions,
                        'turn': episode_turn,
                        'last_line': current_episode[-1][:100] if current_episode else 'N/A'
                    })
                    
                    # Save death order for this episode
                    if stats['current_episode_deaths']:
                        stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                    # Save previous episode
                    stats['episode_lengths'].append(episode_actions)
                    stats['turns_distribution'][episode_turn] += 1

                current_episode = []
                stats['total_episodes'] += 1
                current_episode_num = stats['total_episodes']  # Use count of episodes processed
                episode_turn = 0
                episode_actions = 0
                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {0: set(), 1: set()}
                unit_hp = {}
                unit_player = {}
                unit_positions = {}
                unit_types = {}
                positions_at_turn_start = {}  # Reset for new episode
                wall_hexes = set()
                units_advanced_this_turn = set()  # Reset for new episode
                current_scenario = 'Unknown'  # Reset scenario for new episode
                # Note: unit_position_collisions is not reset - it accumulates across episodes
                continue

            # Skip header (but not EPISODE START lines which are handled above)
            if line.startswith('===') or line.startswith('AI_TURN') or line.startswith('STEP') or line.startswith('NO STEP') or line.startswith('FAILED') or not line.strip():
                continue

            # Parse scenario name
            # Format: [timestamp] Scenario: scenario_name
            scenario_match = re.search(r'Scenario: (.+)$', line)
            if scenario_match:
                current_scenario = scenario_match.group(1).strip()
                continue

            # Parse wall hexes from step log
            # Format: [timestamp] Walls: (col,row);(col,row);...
            wall_match = re.search(r'Walls: (.+)$', line)
            if wall_match:
                wall_str = wall_match.group(1).strip()
                if wall_str != 'none':
                    # Parse tuples like (4,10);(5,10)
                    for coord_match in re.finditer(r'\((\d+),(\d+)\)', wall_str):
                        col, row = int(coord_match.group(1)), int(coord_match.group(2))
                        wall_hexes.add((col, row))
                continue

            # Parse unit starting positions to get HP and type
            # Format: Unit 1 (Intercessor) P0: Starting position (9,12)
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
                    unit_hp[unit_id] = 2  # Intercessor, etc.
                unit_player[unit_id] = player
                unit_positions[unit_id] = (col, row)
                unit_types[unit_id] = unit_type
                stats['debug']['units_initialized'] = stats['debug'].get('units_initialized', 0) + 1
                # CRITICAL: Initialize positions_at_turn_start when we read starting positions
                # This ensures it's ready before any actions are processed
                if not positions_at_turn_start:
                    positions_at_turn_start = {}
                positions_at_turn_start[unit_id] = (col, row)
                stats['unit_types'][unit_id] = unit_type
                continue

            # Episode end
            if 'EPISODE END' in line:
                # Save death order for this episode
                if stats['current_episode_deaths']:
                    stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                # Extract winner and win method
                winner_match = re.search(r'Winner=(-?\d+)', line)
                method_match = re.search(r'Method=(\w+)', line)

                if winner_match:
                    winner = int(winner_match.group(1))
                    win_method = method_match.group(1) if method_match else None

                    # Track wins by scenario
                    if winner == 0:
                        stats['wins_by_scenario'][current_scenario]['p0'] += 1
                    elif winner == 1:
                        stats['wins_by_scenario'][current_scenario]['p1'] += 1
                    elif winner == -1:
                        stats['wins_by_scenario'][current_scenario]['draws'] += 1

                    # Track win method (NO DEFAULT - log what's actually there)
                    if win_method:
                        if winner in stats['win_methods'] and win_method in stats['win_methods'][winner]:
                            stats['win_methods'][winner][win_method] += 1
                        elif winner == -1:
                            stats['win_methods'][-1]['draw'] += 1
                    else:
                        # Track episodes without win_method for debugging
                        if 'episodes_without_method' not in stats:
                            stats['episodes_without_method'] = []
                        stats['episodes_without_method'].append({
                            'winner': winner,
                            'line': line.strip()[:100]  # First 100 chars for debugging
                        })

                    # Save sample games (first of each type) - 10 actions
                    if winner == 0 and not stats['sample_games']['win']:
                        stats['sample_games']['win'] = '\n'.join(current_episode[:10])
                    elif winner == -1 and not stats['sample_games']['draw']:
                        stats['sample_games']['draw'] = '\n'.join(current_episode[:10])

                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {0: set(), 1: set()}
                # CRITICAL FIX: Reset current_episode after EPISODE END to prevent false positives
                current_episode = []
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

                # Reset advanced units when turn changes
                if turn != last_turn:
                    units_advanced_this_turn = set()
                    # CRITICAL FIX: Save positions at turn start for accurate collision detection
                    # Only detect collision if unit was at destination at turn start (real collision)
                    # Not if unit moved there in a previous action this turn (false positive)
                    positions_at_turn_start = unit_positions.copy()
                    last_turn = turn
                # Ensure positions_at_turn_start is initialized even if turn hasn't changed yet
                # (for first action of first turn)
                if not positions_at_turn_start and unit_positions:
                    positions_at_turn_start = unit_positions.copy()

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

                        # Extract shooter and target info
                        # Format: "Unit X(col, row) SHOT at unit Y(col, row)" (target coords now in log)
                        shooter_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\)', action_desc)
                        # Updated regex to capture target coords if present: "SHOT at unit Y" or "SHOT at unit Y(col, row)"
                        target_match = re.search(r'SHOT at unit (\d+)(?:\((\d+),\s*(\d+)\))?', action_desc, re.IGNORECASE)

                        if shooter_match and target_match:
                            shooter_id = shooter_match.group(1)
                            shooter_col = int(shooter_match.group(2))
                            shooter_row = int(shooter_match.group(3))
                            target_id = target_match.group(1)
                            
                            # Extract target coordinates from log if present, otherwise use unit_positions
                            if target_match.group(2) and target_match.group(3):
                                # Target coords are in the log
                                target_col = int(target_match.group(2))
                                target_row = int(target_match.group(3))
                                target_pos = (target_col, target_row)
                                # DO NOT update unit_positions - units don't move during SHOOT phase
                                # Only use for LOS/adjacency calculations in this action
                            elif target_id in unit_positions:
                                # Fallback to unit_positions if coords not in log
                                target_pos = unit_positions[target_id]
                            else:
                                # Target position unknown, skip adjacency check
                                target_pos = None

                            # DO NOT update shooter position - units don't move during SHOOT phase
                            # shooter_col/shooter_row are used only for LOS/adjacency calculations
                            
                            # Check if this unit advanced this turn (Assault weapon rule)
                            if shooter_id in units_advanced_this_turn:
                                stats['shots_after_advance'][player] += 1

                            # Check if weapon is PISTOL and track adjacency
                            # Initialize variables before weapon_match check
                            is_pistol = False
                            weapon_found = False  # Track if weapon was found in cache
                            
                            weapon_match = re.search(r'with \[([^\]]+)\]', action_desc)
                            if weapon_match:
                                weapon_display_name = weapon_match.group(1)  # Keep original case for matching
                                weapon_name_lower = weapon_display_name.lower()
                                
                                # Use unit_weapons_cache to check if weapon really has PISTOL rule
                                shooter_unit_type = unit_types.get(shooter_id, '')
                                shooter_unit_type = unit_types.get(shooter_id, '')
                                if not shooter_unit_type:
                                    stats['debug']['shooter_unit_type_not_found'] += 1
                                weapons_info = unit_weapons_cache.get(shooter_unit_type, [])
                                
                                # Find weapon in cache by display_name (case-insensitive match)
                                for weapon_info in weapons_info:
                                    if weapon_info['name'].lower() == weapon_name_lower:
                                        is_pistol = weapon_info['is_pistol']  # Check WEAPON_RULES, not name
                                        weapon_found = True
                                        if is_pistol:
                                            stats['debug']['weapon_is_pistol'] = stats['debug'].get('weapon_is_pistol', 0) + 1
                                        else:
                                            stats['debug']['weapon_found_but_not_pistol'] += 1
                                        break
                                
                                if not weapon_found:
                                    stats['debug']['weapon_not_found'] += 1
                                
                                # Calculate distance to target to determine adjacency
                                if weapon_found and is_pistol:
                                    if not target_pos:
                                        stats['debug']['pistol_target_pos_none'] = stats['debug'].get('pistol_target_pos_none', 0) + 1
                                
                                if target_pos:
                                    distance = calculate_hex_distance(shooter_col, shooter_row, target_pos[0], target_pos[1])
                                    
                                    if weapon_found:
                                        if is_pistol:
                                            stats['debug']['pistol_shots_with_distance'] = stats['debug'].get('pistol_shots_with_distance', 0) + 1
                                            if distance == 1:
                                                stats['debug']['pistol_distance_1'] = stats['debug'].get('pistol_distance_1', 0) + 1
                                                stats['pistol_shots'][player]['adjacent'] += 1
                                            else:
                                                stats['debug']['pistol_distance_not_1'] = stats['debug'].get('pistol_distance_not_1', 0) + 1
                                                stats['pistol_shots'][player]['not_adjacent'] += 1
                                        else:
                                            # Non-PISTOL weapon - check if adjacent (rule violation)
                                            # Only count violation if weapon was found in cache
                                            if distance == 1:
                                                stats['non_pistol_adjacent_shots'][player] += 1

                            stats['target_priority'][player]['total_shots'] += 1

                            # Check if target was already wounded
                            target_was_wounded = target_id in stats['wounded_enemies'][player]

                            # Find all wounded enemies in LOS for this shooter (with wall checking)
                            wounded_in_los = set()
                            for wounded_id in stats['wounded_enemies'][player]:
                                if wounded_id in unit_positions and wounded_id in unit_hp and unit_hp.get(wounded_id, 0) > 0:
                                    wounded_pos = unit_positions[wounded_id]
                                    # Real LOS check with walls
                                    if has_line_of_sight(shooter_col, shooter_row, wounded_pos[0], wounded_pos[1], wall_hexes):
                                        wounded_in_los.add(wounded_id)

                            if target_was_wounded:
                                # Good: shooting at a wounded enemy
                                stats['target_priority'][player]['shots_at_wounded_in_los'] += 1
                            elif len(wounded_in_los) > 0:
                                # Bad: shooting full HP while wounded enemies exist (in LOS)
                                stats['target_priority'][player]['shots_at_full_hp_while_wounded_in_los'] += 1
                            else:
                                # Good: shooting at full HP when no wounded enemies in LOS (correct decision)
                                stats['target_priority'][player]['shots_at_wounded_in_los'] += 1

                            # Check for damage in the action description
                            damage_match = re.search(r'Dmg:(\d+)', action_desc)
                            killed = False
                            if damage_match:
                                stats['debug']['damage_match_found'] += 1
                                damage = int(damage_match.group(1))
                                if damage > 0:
                                    # Apply damage to tracked HP
                                    if target_id in unit_hp:
                                        stats['debug']['damage_applied'] += 1
                                        unit_hp[target_id] -= damage
                                        if unit_hp[target_id] <= 0:
                                            killed = True
                                        else:
                                            # Mark this unit as wounded (but not dead)
                                            stats['wounded_enemies'][player].add(target_id)
                                    else:
                                        stats['debug']['target_not_in_unit_hp'] += 1

                            # Track death order and remove from wounded
                            if killed:
                                # Record which player killed which unit with type
                                target_type = unit_types.get(target_id, "Unknown")
                                stats['current_episode_deaths'].append((player, target_id, target_type))
                                # Remove from wounded set since it's dead
                                stats['wounded_enemies'][player].discard(target_id)
                                # Remove dead unit position from tracking (maintain real-time catalog)
                                if target_id in unit_positions:
                                    del unit_positions[target_id]

                    elif 'wait' in action_desc.lower():
                        action_type = 'wait'
                        stats['shoot_vs_wait']['wait'] += 1
                        stats['shoot_vs_wait_by_player'][player]['wait'] += 1

                        # Track waits by phase (MOVE or SHOOT)
                        if phase == 'SHOOT':
                            # Extract unit position for validation
                            unit_match = re.search(r'Unit (\d+)\((\d+), (\d+)\)', action_desc)
                            if unit_match:
                                wait_unit_id = unit_match.group(1)
                                wait_col = int(unit_match.group(2))
                                wait_row = int(unit_match.group(3))
                                
                                # Get unit type and weapons
                                wait_unit_type = unit_types.get(wait_unit_id, 'Unknown')
                                available_weapons = unit_weapons_cache.get(wait_unit_type, [])
                                ranged_weapons = [w for w in available_weapons if w.get('range', 0) > 0]
                                
                                # Check if unit is adjacent to enemy
                                enemy_player = 1 - player
                                is_adjacent = False
                                for uid, p in unit_player.items():
                                    if p == enemy_player and unit_hp.get(uid, 0) > 0 and uid in unit_positions:
                                        enemy_pos = unit_positions[uid]
                                        distance = calculate_hex_distance(wait_col, wait_row, enemy_pos[0], enemy_pos[1])
                                        if distance == 1:
                                            is_adjacent = True
                                            break
                                
                                # If adjacent and no PISTOL weapon → this is a SKIP (not a wait)
                                if is_adjacent:
                                    has_pistol = any(w.get('is_pistol', False) for w in ranged_weapons)
                                    if not has_pistol:
                                        # Can't shoot in melee without PISTOL → this is a skip, not a wait
                                        stats['shoot_vs_wait']['wait'] -= 1
                                        stats['shoot_vs_wait_by_player'][player]['wait'] -= 1
                                        stats['shoot_vs_wait']['skip'] += 1
                                        stats['shoot_vs_wait_by_player'][player]['skip'] += 1
                                        continue  # Skip the rest of wait processing
                                
                                # Check if any enemy is a VALID target (not just LOS)
                                valid_targets = []
                                
                                for uid, p in unit_player.items():
                                    if p == enemy_player and unit_hp.get(uid, 0) > 0 and uid in unit_positions:
                                        enemy_pos = unit_positions[uid]
                                        distance = calculate_hex_distance(wait_col, wait_row, enemy_pos[0], enemy_pos[1])
                                        
                                        # Check LOS
                                        if not has_line_of_sight(wait_col, wait_row, enemy_pos[0], enemy_pos[1], wall_hexes):
                                            continue
                                        
                                        # Check if any weapon can reach this target
                                        can_reach = False
                                        for weapon in ranged_weapons:
                                            weapon_range = weapon.get('range', 0)
                                            is_pistol = weapon.get('is_pistol', False)
                                            
                                            # Range check
                                            if distance > weapon_range:
                                                continue
                                            
                                            # Adjacent check: non-PISTOL can't shoot adjacent
                                            if distance == 1 and not is_pistol:
                                                continue
                                            
                                            # Melee check: can't shoot if target is in melee with friendly
                                            target_in_melee = False
                                            for friendly_id, friendly_p in unit_player.items():
                                                if friendly_p == player and friendly_id != wait_unit_id:
                                                    if friendly_id in unit_positions:
                                                        friendly_pos = unit_positions[friendly_id]
                                                        friendly_distance = calculate_hex_distance(enemy_pos[0], enemy_pos[1], friendly_pos[0], friendly_pos[1])
                                                        if friendly_distance == 1:
                                                            target_in_melee = True
                                                            break
                                            
                                            if target_in_melee:
                                                continue
                                            
                                            # All checks passed
                                            can_reach = True
                                            break
                                        
                                        if can_reach:
                                            valid_targets.append(uid)

                                if valid_targets:
                                    # Has valid targets - this is a "bad" wait
                                    stats['wait_by_phase'][player]['shoot_wait_with_los'] += 1
                                    stats['shoot_vs_wait_by_player'][player]['wait_with_targets'] += 1
                                else:
                                    # No valid targets - this wait is fine
                                    stats['wait_by_phase'][player]['shoot_wait_no_los'] += 1
                                    stats['shoot_vs_wait_by_player'][player]['wait_no_targets'] += 1
                            else:
                                # Couldn't parse - count as no LOS
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
                        
                        # Count advance actions in SHOOT phase
                        if phase == 'SHOOT':
                            stats['shoot_vs_wait']['advance'] += 1
                            stats['shoot_vs_wait_by_player'][player]['advance'] += 1

                        # Parse advance: "Unit X(col, row) ADVANCED from (start_col, start_row) to (end_col, end_row) [Roll: X]"
                        advance_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) ADVANCED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if advance_match:
                            advance_unit_id = advance_match.group(1)
                            log_col = int(advance_match.group(2))
                            log_row = int(advance_match.group(3))
                            start_col = int(advance_match.group(4))
                            start_row = int(advance_match.group(5))
                            dest_col = int(advance_match.group(6))
                            dest_row = int(advance_match.group(7))
                            
                            # Get current position from tracking table
                            current_tracked_pos = unit_positions.get(advance_unit_id, None)
                            
                            # Verify unit is actually moving
                            if (start_col, start_row) != (dest_col, dest_row):
                                # RULE CHECK 1: Position collision
                                # Check CURRENT positions (like charge and move do) to detect same-turn collisions
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
                                        'advance_to': (dest_col, dest_row),
                                        'tracked_before': current_tracked_pos
                                    })
                                
                                # RULE CHECK 2: Move into wall
                                if (dest_col, dest_row) in wall_hexes:
                                    stats['wall_collisions'][player] += 1
                                
                                # UPDATE: Move unit to destination in tracking table
                                unit_positions[advance_unit_id] = (dest_col, dest_row)
                                
                                # Mark this unit as having advanced this turn (for Assault rule tracking)
                                units_advanced_this_turn.add(advance_unit_id)
                        else:
                            # Strict analyzer: reject non-standard format
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Advance action missing 'from/to' format: {action_desc[:100]}"
                            })
                    elif 'charge' in action_desc.lower():
                        action_type = 'charge'
                        
                        # Parse charge action: "Unit X(col, row) CHARGED unit Y from (start_col, start_row) to (end_col, end_row) [Roll:charge_roll]"
                        charge_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) CHARGED unit \d+ from \((\d+),\s*(\d+)\)', action_desc)
                        if charge_match:
                            charge_unit_id = charge_match.group(1)
                            # Destination position (after charge) - from log format
                            dest_col = int(charge_match.group(2))
                            dest_row = int(charge_match.group(3))
                            # Starting position (before charge)
                            start_col = int(charge_match.group(4))
                            start_row = int(charge_match.group(5))
                            
                            # Get current position from our tracking table (should match start_col/start_row)
                            current_tracked_pos = unit_positions.get(charge_unit_id, None)
                            
                            # CRITICAL: Verify tracking is synchronized with log
                            # If current_tracked_pos doesn't match start position from log, tracking is desynced
                            if current_tracked_pos is not None and current_tracked_pos != (start_col, start_row):
                                # Tracking desync detected - skip collision check to avoid false positives
                                # Update position to correct tracking
                                pass  # We'll still update at the end
            
                            # Verify unit is actually moving
                            if (start_col, start_row) != (dest_col, dest_row):
                                # RULE CHECK 1: Charge from adjacent hex to enemy
                                if is_adjacent_to_enemy(start_col, start_row, unit_player, unit_positions, unit_hp, player):
                                    stats['charge_from_adjacent'][player] += 1
                                
                                # RULE CHECK 2: Position collision - check if destination is already occupied
                                # Only check collision if tracking is synchronized
                                if current_tracked_pos is None or current_tracked_pos == (start_col, start_row):
                                    # CRITICAL FIX: Only detect collision if unit was at destination at turn start
                                    # This avoids false positives when units move to same hex sequentially
                                    # CRITICAL FIX: Check collision with CURRENT positions, not turn start positions
                                    # An unit that was at destination at turn start but has moved away is NOT a collision
                                    colliding_units = [uid for uid, current_pos in unit_positions.items() 
                                                      if current_pos == (dest_col, dest_row)
                                                      and uid != charge_unit_id  # Exclude charging unit
                                                      and unit_hp.get(uid, 0) > 0]  # Must be alive
                                    if colliding_units:
                                        # DEBUG: Add action description and full line to help identify the source
                                        stats['unit_position_collisions'].append({
                                            'episode': current_episode_num,
                                            'turn': turn,
                                            'position': (dest_col, dest_row),
                                            'units': colliding_units + [charge_unit_id],
                                            'action': 'charge',
                                            'charge_from': (start_col, start_row),
                                            'charge_to': (dest_col, dest_row),
                                            'tracked_before': current_tracked_pos,
                                            'action_desc': action_desc[:100],  # First 100 chars for debugging
                                            'log_line': line.strip()  # Full log line that triggered this collision
                                        })
                                
                                # UPDATE: Move unit to destination in tracking table
                                unit_positions[charge_unit_id] = (dest_col, dest_row)
                    elif 'moves' in action_desc.lower() or 'moved' in action_desc.lower():
                        action_type = 'move'

                        # Parse move action: "Unit X(col, row) MOVED from (start_col, start_row) to (end_col, end_row)"
                        # Try full format first
                        move_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) MOVED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
                        if move_match:
                            move_unit_id = move_match.group(1)
                            # Current position in log (should be destination)
                            log_col = int(move_match.group(2))
                            log_row = int(move_match.group(3))
                            start_col = int(move_match.group(4))
                            start_row = int(move_match.group(5))
                            dest_col = int(move_match.group(6))
                            dest_row = int(move_match.group(7))
                            
                            # Get current position from tracking table
                            current_tracked_pos = unit_positions.get(move_unit_id, None)
                            
                            # Verify unit is actually moving
                            if (start_col, start_row) != (dest_col, dest_row):
                                # RULE CHECK 1: Position collision - check if destination is already occupied
                                # Check CURRENT positions (like charge does) to detect same-turn collisions
                                colliding_units = [uid for uid, current_pos in unit_positions.items() 
                                                  if current_pos == (dest_col, dest_row)
                                                  and uid != move_unit_id  # Exclude moving unit
                                                  and unit_hp.get(uid, 0) > 0]  # Must be alive
                                if colliding_units:
                                    stats['unit_position_collisions'].append({
                                        'episode': current_episode_num,
                                        'turn': turn,
                                        'position': (dest_col, dest_row),
                                        'units': colliding_units + [move_unit_id],
                                        'action': 'move',
                                        'move_from': (start_col, start_row),
                                        'move_to': (dest_col, dest_row),
                                        'tracked_before': current_tracked_pos,
                                        'colliding_positions': {uid: unit_positions.get(uid, None) for uid in colliding_units},
                                        'action_desc': action_desc[:100],
                                        'log_line': line.strip()
                                    })
                                
                                # RULE CHECK 2: Move to adjacent enemy
                                # Check BEFORE updating position (use current tracking table)
                                if is_adjacent_to_enemy(dest_col, dest_row, unit_player, unit_positions, unit_hp, player):
                                    stats['move_to_adjacent_enemy'][player] += 1
                                
                                # RULE CHECK 3: Move into wall
                                if (dest_col, dest_row) in wall_hexes:
                                    stats['wall_collisions'][player] += 1
                                
                                # UPDATE: Move unit to destination in tracking table
                                unit_positions[move_unit_id] = (dest_col, dest_row)
                        else:
                            # Strict analyzer: reject non-standard format
                            stats['parse_errors'].append({
                                'episode': current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': f"Move action missing 'from/to' format: {action_desc[:100]}"
                            })
                    elif 'fought' in action_desc.lower() or 'attacked' in action_desc.lower():
                        action_type = 'fight'
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

    # WIN METHODS
    print("\n" + "-" * 80)
    print("WIN METHODS")
    print("-" * 80)
    print(f"{'Method':<20} {'Agent Wins (P0)':>18} {'Bot Wins (P1)':>18}")
    print("-" * 80)

    # Calculate totals
    p0_total = sum(stats['win_methods'][0].values())
    p1_total = sum(stats['win_methods'][1].values())
    draws = stats['win_methods'][-1]['draw']

    for method in ['elimination', 'objectives', 'value_tiebreaker']:
        p0_count = stats['win_methods'][0].get(method, 0)
        p1_count = stats['win_methods'][1].get(method, 0)
        p0_pct = (p0_count / p0_total * 100) if p0_total > 0 else 0
        p1_pct = (p1_count / p1_total * 100) if p1_total > 0 else 0
        method_display = method.replace('_', ' ').title()
        print(f"{method_display:<20} {p0_count:6d} ({p0_pct:5.1f}%)   {p1_count:6d} ({p1_pct:5.1f}%)")

    print("-" * 80)
    total_games = p0_total + p1_total + draws
    p0_pct = (p0_total / total_games * 100) if total_games > 0 else 0
    p1_pct = (p1_total / total_games * 100) if total_games > 0 else 0
    draw_pct = (draws / total_games * 100) if total_games > 0 else 0
    print(f"{'TOTAL WINS':<20} {p0_total:6d} ({p0_pct:5.1f}%)   {p1_total:6d} ({p1_pct:5.1f}%)")
    print(f"{'DRAWS':<20} {draws:6d} ({draw_pct:5.1f}%)")
    
    # WINS BY SCENARIO
    if stats['wins_by_scenario']:
        print("\n" + "-" * 80)
        print("WINS BY SCENARIO")
        print("-" * 80)
        print(f"{'Scenario':<40} {'Agent (P0)':>15} {'Bot (P1)':>15} {'Draws':>10}")
        print("-" * 80)
        
        # Sort scenarios by total games (descending)
        scenario_totals = []
        for scenario, wins in stats['wins_by_scenario'].items():
            total = wins['p0'] + wins['p1'] + wins['draws']
            scenario_totals.append((scenario, wins, total))
        scenario_totals.sort(key=lambda x: -x[2])
        
        for scenario, wins, total in scenario_totals:
            p0_count = wins['p0']
            p1_count = wins['p1']
            draws_count = wins['draws']
            p0_pct = (p0_count / total * 100) if total > 0 else 0
            p1_pct = (p1_count / total * 100) if total > 0 else 0
            draws_pct = (draws_count / total * 100) if total > 0 else 0
            # Extract "bot-X" from scenario name if present
            bot_match = re.search(r'bot-(\d+)', scenario, re.IGNORECASE)
            if bot_match:
                scenario_display = f"bot-{bot_match.group(1)}"
            else:
                scenario_display = scenario[:39]  # Fallback: truncate if no bot-X pattern
            print(f"{scenario_display:<40} {p0_count:5d} ({p0_pct:4.1f}%) {p1_count:5d} ({p1_pct:4.1f}%) {draws_count:5d} ({draws_pct:4.1f}%)")
    
    # Display episodes without win_method if any
    if 'episodes_without_method' in stats and stats['episodes_without_method']:
        print("\n" + "-" * 80)
        print("⚠️  EPISODES WITHOUT WIN_METHOD (BUG DETECTED)")
        print("-" * 80)
        print(f"Total: {len(stats['episodes_without_method'])} episodes")
        for i, ep in enumerate(stats['episodes_without_method'][:5]):  # Show first 5
            print(f"  {i+1}. Winner={ep['winner']}, Line: {ep['line']}")
        if len(stats['episodes_without_method']) > 5:
            print(f"  ... and {len(stats['episodes_without_method']) - 5} more")
    
    # Display episodes without EPISODE END if any
    if 'episodes_without_end' in stats and stats['episodes_without_end']:
        print("\n" + "-" * 80)
        print("⚠️  EPISODES WITHOUT EPISODE END (INCOMPLETE EPISODES)")
        print("-" * 80)
        print(f"Total: {len(stats['episodes_without_end'])} episodes")
        for i, ep in enumerate(stats['episodes_without_end'][:5]):  # Show first 5
            print(f"  {i+1}. Episode #{ep['episode_num']}, Actions={ep['actions']}, Turn={ep['turn']}, Last: {ep['last_line']}")
        if len(stats['episodes_without_end']) > 5:
            print(f"  ... and {len(stats['episodes_without_end']) - 5} more")

    print("\n" + "-" * 80)
    print("TURN DISTRIBUTION")
    print("-" * 80)
    for turn in sorted(stats['turns_distribution'].keys()):
        count = stats['turns_distribution'][turn]
        pct = (count / stats['total_episodes'] * 100) if stats['total_episodes'] > 0 else 0
        print(f"Turn {turn}: {count:3d} games ({pct:5.1f}%)")

    # ACTIONS BY TYPE - 2 columns
    print("\n" + "-" * 80)
    print("ACTIONS BY TYPE")
    print("-" * 80)
    print(f"{'Action':<12} {'Agent (P0)':>18} {'Bot (P1)':>18}")
    print("-" * 80)

    # Get all action types
    all_actions = set(stats['actions_by_player'][0].keys()) | set(stats['actions_by_player'][1].keys())
    # Sort by total count
    action_totals = [(a, stats['actions_by_player'][0].get(a, 0) + stats['actions_by_player'][1].get(a, 0))
                     for a in all_actions]
    action_totals.sort(key=lambda x: -x[1])

    agent_total = sum(stats['actions_by_player'][0].values())
    bot_total = sum(stats['actions_by_player'][1].values())

    for action_type, _ in action_totals:
        agent_count = stats['actions_by_player'][0].get(action_type, 0)
        bot_count = stats['actions_by_player'][1].get(action_type, 0)
        agent_pct = (agent_count / agent_total * 100) if agent_total > 0 else 0
        bot_pct = (bot_count / bot_total * 100) if bot_total > 0 else 0
        print(f"{action_type:<12} {agent_count:6d} ({agent_pct:5.1f}%)   {bot_count:6d} ({bot_pct:5.1f}%)")

    # SHOOTING PHASE BEHAVIOR - 2 columns
    print("\n" + "-" * 80)
    print("SHOOTING PHASE BEHAVIOR")
    print("-" * 80)
    print(f"{'Action':<12} {'Agent (P0)':>18} {'Bot (P1)':>18}")
    print("-" * 80)

    agent_shoot_total = (stats['shoot_vs_wait_by_player'][0]['shoot'] +
                        stats['shoot_vs_wait_by_player'][0]['wait'] +
                        stats['shoot_vs_wait_by_player'][0]['skip'] +
                        stats['shoot_vs_wait_by_player'][0]['advance'])
    bot_shoot_total = (stats['shoot_vs_wait_by_player'][1]['shoot'] +
                      stats['shoot_vs_wait_by_player'][1]['wait'] +
                      stats['shoot_vs_wait_by_player'][1]['skip'] +
                      stats['shoot_vs_wait_by_player'][1]['advance'])

    for action in ['shoot', 'skip', 'advance']:
        agent_count = stats['shoot_vs_wait_by_player'][0][action]
        bot_count = stats['shoot_vs_wait_by_player'][1][action]
        agent_pct = (agent_count / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
        bot_pct = (bot_count / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
        print(f"{action.capitalize():<12} {agent_count:6d} ({agent_pct:5.1f}%)   {bot_count:6d} ({bot_pct:5.1f}%)")
    
    # Wait actions - split by targets available
    agent_wait_with = stats['shoot_vs_wait_by_player'][0]['wait_with_targets']
    bot_wait_with = stats['shoot_vs_wait_by_player'][1]['wait_with_targets']
    agent_wait_with_pct = (agent_wait_with / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_with_pct = (bot_wait_with / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    print(f"{'Wait (targets)':<12} {agent_wait_with:6d} ({agent_wait_with_pct:5.1f}%)   {bot_wait_with:6d} ({bot_wait_with_pct:5.1f}%)")
    
    agent_wait_no = stats['shoot_vs_wait_by_player'][0]['wait_no_targets']
    bot_wait_no = stats['shoot_vs_wait_by_player'][1]['wait_no_targets']
    agent_wait_no_pct = (agent_wait_no / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_wait_no_pct = (bot_wait_no / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    print(f"{'Wait (no targets)':<12} {agent_wait_no:6d} ({agent_wait_no_pct:5.1f}%)   {bot_wait_no:6d} ({bot_wait_no_pct:5.1f}%)")
    
    # Shots after advance (Assault weapon rule)
    agent_shots_after_advance = stats['shots_after_advance'][0]
    bot_shots_after_advance = stats['shots_after_advance'][1]
    agent_pct_after_advance = (agent_shots_after_advance / agent_shoot_total * 100) if agent_shoot_total > 0 else 0
    bot_pct_after_advance = (bot_shots_after_advance / bot_shoot_total * 100) if bot_shoot_total > 0 else 0
    print(f"{'Shoot+Advance':<12} {agent_shots_after_advance:6d} ({agent_pct_after_advance:5.1f}%)   {bot_shots_after_advance:6d} ({bot_pct_after_advance:5.1f}%)")
    
    # PISTOL weapon shots by adjacency
    print("\n" + "-" * 80)
    print("PISTOL WEAPON SHOTS BY ADJACENCY")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print("-" * 80)
    agent_pistol_adj = stats['pistol_shots'][0]['adjacent']
    bot_pistol_adj = stats['pistol_shots'][1]['adjacent']
    agent_pistol_not_adj = stats['pistol_shots'][0]['not_adjacent']
    bot_pistol_not_adj = stats['pistol_shots'][1]['not_adjacent']
    agent_pistol_total = agent_pistol_adj + agent_pistol_not_adj
    bot_pistol_total = bot_pistol_adj + bot_pistol_not_adj
    
    agent_pistol_adj_pct = (agent_pistol_adj / agent_pistol_total * 100) if agent_pistol_total > 0 else 0
    bot_pistol_adj_pct = (bot_pistol_adj / bot_pistol_total * 100) if bot_pistol_total > 0 else 0
    agent_pistol_not_adj_pct = (agent_pistol_not_adj / agent_pistol_total * 100) if agent_pistol_total > 0 else 0
    bot_pistol_not_adj_pct = (bot_pistol_not_adj / bot_pistol_total * 100) if bot_pistol_total > 0 else 0
    
    print(f"PISTOL shots (adjacent):       {agent_pistol_adj:6d} ({agent_pistol_adj_pct:5.1f}%)  {bot_pistol_adj:6d} ({bot_pistol_adj_pct:5.1f}%)")
    print(f"PISTOL shots (not adjacent):   {agent_pistol_not_adj:6d} ({agent_pistol_not_adj_pct:5.1f}%)  {bot_pistol_not_adj:6d} ({bot_pistol_not_adj_pct:5.1f}%)")
    print(f"Total PISTOL shots:            {agent_pistol_total:6d}           {bot_pistol_total:6d}")
    
    # Non-PISTOL shots while adjacent (rule violation)
    agent_non_pistol_adj = stats['non_pistol_adjacent_shots'][0]
    bot_non_pistol_adj = stats['non_pistol_adjacent_shots'][1]
    print(f"Non-PISTOL shots (adjacent):   {agent_non_pistol_adj:6d}           {bot_non_pistol_adj:6d}")

    # WAIT BEHAVIOR - shoot waits with LOS only
    print("\n" + "-" * 80)
    print("WAIT BEHAVIOR BY PHASE")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print("-" * 80)
    agent_move_wait = stats['wait_by_phase'][0]['move_wait']
    bot_move_wait = stats['wait_by_phase'][1]['move_wait']
    agent_shoot_wait_los = stats['wait_by_phase'][0]['shoot_wait_with_los']
    bot_shoot_wait_los = stats['wait_by_phase'][1]['shoot_wait_with_los']
    agent_shoot_wait_no_los = stats['wait_by_phase'][0]['shoot_wait_no_los']
    bot_shoot_wait_no_los = stats['wait_by_phase'][1]['shoot_wait_no_los']

    print(f"MOVE phase waits:             {agent_move_wait:6d}           {bot_move_wait:6d}")
    print(f"SHOOT waits (enemies in LOS): {agent_shoot_wait_los:6d}           {bot_shoot_wait_los:6d}")
    print(f"SHOOT waits (no LOS):         {agent_shoot_wait_no_los:6d}           {bot_shoot_wait_no_los:6d}")

    # Target priority analysis - with LOS
    print("\n" + "-" * 80)
    print("TARGET PRIORITY ANALYSIS (Focus Fire)")
    print("-" * 80)
    print(f"{'':30s} {'Agent (P0)':>15s} {'Bot (P1)':>15s}")
    print("-" * 80)

    agent_bad = stats['target_priority'][0]['shots_at_full_hp_while_wounded_in_los']
    bot_bad = stats['target_priority'][1]['shots_at_full_hp_while_wounded_in_los']
    agent_good = stats['target_priority'][0]['shots_at_wounded_in_los']
    bot_good = stats['target_priority'][1]['shots_at_wounded_in_los']
    agent_total_shots = stats['target_priority'][0]['total_shots']
    bot_total_shots = stats['target_priority'][1]['total_shots']

    agent_bad_pct = (agent_bad / agent_total_shots * 100) if agent_total_shots > 0 else 0
    bot_bad_pct = (bot_bad / bot_total_shots * 100) if bot_total_shots > 0 else 0
    agent_good_pct = (agent_good / agent_total_shots * 100) if agent_total_shots > 0 else 0
    bot_good_pct = (bot_good / bot_total_shots * 100) if bot_total_shots > 0 else 0

    print(f"FAILURES (shot full HP while")
    print(f"  wounded in LOS):            {agent_bad:6d} ({agent_bad_pct:5.1f}%)  {bot_bad:6d} ({bot_bad_pct:5.1f}%)")
    print(f"SUCCESS (shot wounded or")
    print(f"  no wounded in LOS):         {agent_good:6d} ({agent_good_pct:5.1f}%)  {bot_good:6d} ({bot_good_pct:5.1f}%)")
    print(f"Total shots:                  {agent_total_shots:6d}           {bot_total_shots:6d}")

    # Death order analysis with unit types
    print("\n" + "-" * 80)
    print("ENEMY DEATH ORDER ANALYSIS")
    print("-" * 80)

    if stats['death_orders']:
        # Count how often each death order pattern occurs
        death_order_counter = Counter()
        for death_order in stats['death_orders']:
            # Extract unit IDs with types in order
            units_killed = tuple(f"{unit_type}({unit_id})" for player, unit_id, unit_type in death_order)
            if units_killed:
                death_order_counter[units_killed] += 1

        # Show most common death orders
        print(f"Total episodes with kills: {len(stats['death_orders'])}")
        print(f"\nMost common death orders:")
        for order, count in death_order_counter.most_common(10):
            pct = (count / len(stats['death_orders']) * 100)
            order_str = " → ".join(order)
            print(f"  {order_str}: {count} times ({pct:.1f}%)")

        # Also show who killed whom
        print(f"\nKills by player:")
        player_kills = {0: 0, 1: 0}
        for death_order in stats['death_orders']:
            for player, unit_id, unit_type in death_order:
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
    
    # Charge validation
    agent_charge_adj = stats['charge_from_adjacent'][0]
    bot_charge_adj = stats['charge_from_adjacent'][1]
    print(f"Charges from adjacent hex:    {agent_charge_adj:6d}           {bot_charge_adj:6d}")
    
    # Move validation
    agent_move_adj = stats['move_to_adjacent_enemy'][0]
    bot_move_adj = stats['move_to_adjacent_enemy'][1]
    print(f"Moves to adjacent enemy:      {agent_move_adj:6d}           {bot_move_adj:6d}")
    
    # Parse errors (strict analyzer)
    if stats['parse_errors']:
        print("\n" + "-" * 80)
        print("⚠️  PARSE ERRORS (Non-standard log format)")
        print("-" * 80)
        print(f"Total parse errors: {len(stats['parse_errors'])}")
        for i, error in enumerate(stats['parse_errors'][:10]):  # Show first 10
            print(f"  {i+1}. Episode #{error['episode']}, Turn {error['turn']}, {error['phase']}: {error['error']}")
            print(f"      Line: {error['line']}")
        if len(stats['parse_errors']) > 10:
            print(f"  ... and {len(stats['parse_errors']) - 10} more")
    
    # Position collisions
    if stats['unit_position_collisions']:
        print("\n" + "-" * 80)
        print("⚠️  UNIT POSITION COLLISIONS (2+ units in same hex)")
        print("-" * 80)
        print(f"Total collisions: {len(stats['unit_position_collisions'])}")
        for i, collision in enumerate(stats['unit_position_collisions'][:10]):  # Show first 10
            units_str = ", ".join([f"Unit {uid}" for uid in collision['units']])
            if 'charge_from' in collision:
                debug_info = f" [DEBUG: {collision.get('action_desc', 'N/A')}]" if 'action_desc' in collision else ""
                log_line_info = f"\n      LOG LINE: {collision.get('log_line', 'N/A')}" if 'log_line' in collision else ""
                print(f"  {i+1}. Episode #{collision['episode']}, Turn {collision['turn']}, {collision['action']}: {units_str} at {collision['position']} (from {collision['charge_from']}){debug_info}{log_line_info}")
                if 'colliding_positions' in collision:
                    pos_info = ", ".join([f"Unit {uid}@{pos}" for uid, pos in collision['colliding_positions'].items()])
                    print(f"      Colliding units positions: {pos_info}")
            else:
                debug_info = f" [from {collision.get('move_from', 'N/A')} to {collision.get('move_to', 'N/A')}]" if 'move_from' in collision else ""
                colliding_pos_info = f"\n      Colliding units positions: {collision.get('colliding_positions', {})}" if 'colliding_positions' in collision else ""
                log_line_info = f"\n      LOG LINE: {collision.get('log_line', 'N/A')}" if 'log_line' in collision else ""
                print(f"  {i+1}. Episode #{collision['episode']}, Turn {collision['turn']}, {collision['action']}: {units_str} at {collision['position']}{debug_info}{colliding_pos_info}{log_line_info}")
        if len(stats['unit_position_collisions']) > 10:
            print(f"  ... and {len(stats['unit_position_collisions']) - 10} more")

    # SAMPLE GAMES - 10 actions
    print("\n" + "=" * 80)
    print("SAMPLE GAMES (first 10 actions)")
    print("=" * 80)

    if stats['sample_games']['win']:
        print("\n--- AGENT WIN GAME ---")
        print(stats['sample_games']['win'])

    print("\n" + "=" * 80)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python check/analyze_step_log.py step.log")
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
