#!/usr/bin/env python3
"""
Script pour analyser les cas de "dead unit shooting" détectés par analyzer.py
Examine le contexte autour de chaque cas pour comprendre pourquoi l'unité est considérée comme morte.
"""

import re
import sys
from collections import defaultdict

def analyze_dead_shooters(log_file):
    """Analyse les cas de dead unit shooting pour comprendre le problème"""
    
    # Track unit HP and deaths
    unit_hp = {}
    unit_player = {}
    unit_deaths = []  # List of (turn, phase, unit_id, line) when unit died
    dead_shooter_cases = []  # List of cases where dead unit shoots
    
    current_episode = 0
    current_turn = 0
    
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line_num, line in enumerate(lines, 1):
        # Episode start
        if '=== EPISODE' in line and 'START ===' in line:
            current_episode += 1
            unit_hp = {}
            unit_player = {}
            unit_deaths = []
            continue
        
        # Parse unit starting positions
        unit_start_match = re.match(r'.*Unit (\d+) \((\w+)\) P(\d+): Starting position \((\d+),\s*(\d+)\)', line)
        if unit_start_match:
            unit_id = unit_start_match.group(1)
            unit_type = unit_start_match.group(2)
            player = int(unit_start_match.group(3))
            
            # Set HP based on unit type
            if unit_type in ['Termagant', 'Hormagaunt', 'Genestealer']:
                unit_hp[unit_id] = 1
            else:
                unit_hp[unit_id] = 2
            
            unit_player[unit_id] = player
            continue
        
        # Parse action line
        match = re.match(r'\[.*?\] (?:E\d+ )?T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\] \[STEP: (YES|NO)\]', line)
        if match:
            turn = int(match.group(1))
            player = int(match.group(2))
            phase = match.group(3)
            action_desc = match.group(4)
            step_inc = match.group(6) == 'YES'
            
            current_turn = turn
            
            # Apply damage (same logic as analyzer)
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
                                unit_deaths.append((turn, phase, target_id, line_num, line.strip()))
                                if target_id in unit_hp:
                                    del unit_hp[target_id]
            
            # Check for dead unit shooting
            if step_inc and ('shoots' in action_desc.lower() or 'shot' in action_desc.lower()):
                shooter_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\)', action_desc)
                if shooter_match:
                    shooter_id = shooter_match.group(1)
                    
                    # Check if shooter is dead
                    if shooter_id not in unit_hp or unit_hp.get(shooter_id, 0) <= 0:
                        # Find when this unit died
                        death_info = None
                        for death_turn, death_phase, dead_unit_id, death_line_num, death_line in unit_deaths:
                            if dead_unit_id == shooter_id:
                                death_info = (death_turn, death_phase, death_line_num, death_line)
                                break
                        
                        dead_shooter_cases.append({
                            'episode': current_episode,
                            'turn': turn,
                            'phase': phase,
                            'shooter_id': shooter_id,
                            'line_num': line_num,
                            'line': line.strip(),
                            'death_info': death_info,
                            'unit_hp_state': unit_hp.copy(),
                            'all_deaths_before': [d for d in unit_deaths if d[2] == shooter_id or (d[0] < turn or (d[0] == turn and d[1] < phase))]
                        })
    
    return dead_shooter_cases

def print_analysis(cases):
    """Print detailed analysis of dead shooter cases"""
    print("=" * 80)
    print("DEAD UNIT SHOOTING ANALYSIS")
    print("=" * 80)
    print(f"\nTotal cases found: {len(cases)}\n")
    
    for i, case in enumerate(cases[:10], 1):  # Show first 10 cases
        print(f"\n--- Case {i} ---")
        print(f"Episode: {case['episode']}, Turn: {case['turn']}, Phase: {case['phase']}")
        print(f"Shooter ID: {case['shooter_id']}")
        print(f"Line {case['line_num']}: {case['line']}")
        
        if case['death_info']:
            death_turn, death_phase, death_line_num, death_line = case['death_info']
            print(f"\n⚠️  Unit {case['shooter_id']} DIED at:")
            print(f"   Turn: {death_turn}, Phase: {death_phase}, Line {death_line_num}")
            print(f"   {death_line}")
            print(f"\n   Shooting action is at Turn {case['turn']}, Phase {case['phase']}")
            
            # Determine if this is a real bug or false positive
            if death_turn < case['turn']:
                print(f"   ✅ REAL BUG: Unit died in Turn {death_turn} but shoots in Turn {case['turn']}")
            elif death_turn == case['turn']:
                phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
                death_phase_order = phase_order.get(death_phase, 99)
                shoot_phase_order = phase_order.get(case['phase'], 99)
                if death_phase_order < shoot_phase_order:
                    print(f"   ✅ REAL BUG: Unit died in {death_phase} (order {death_phase_order}) but shoots in {case['phase']} (order {shoot_phase_order})")
                else:
                    print(f"   ⚠️  FALSE POSITIVE: Unit died in {death_phase} (order {death_phase_order}) AFTER shooting in {case['phase']} (order {shoot_phase_order})")
                    print(f"   This is likely a parsing order issue - the log shows death before shoot but they happen in reverse order")
            else:
                print(f"   ⚠️  FALSE POSITIVE: Unit dies in future turn {death_turn} (impossible)")
        else:
            print(f"\n⚠️  Unit {case['shooter_id']} not found in unit_hp but no death recorded")
            print(f"   This could mean:")
            print(f"   - Unit was never initialized")
            print(f"   - Unit died but death wasn't logged properly")
            print(f"   - Parsing issue")
        
        print(f"\n   Unit HP state at time of shooting: {case['unit_hp_state']}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python ai/analyze_dead_shooters.py step.log")
        sys.exit(1)
    
    log_file = sys.argv[1]
    cases = analyze_dead_shooters(log_file)
    print_analysis(cases)
