#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find where Unit 2's position gets corrupted, allowing Unit 7 to move to (11,11).

Strategy:
1. Parse the log and track ALL unit positions after each action
2. When Unit 7 tries to move to (11,11), check what Unit 2's position should be
3. Compare with what the occupation check must have seen

From the log:
- T1 P0: Unit 2 moves (11,12) -> (11,11)
- T2 P0: Units 1,3,4 move (Unit 2 does NOT move - stays at (11,11))
- T2 P1: Unit 7 moves (13,10) -> (11,11) ← BUG! Should be blocked!
"""

import sys
import os
import io
import re

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 80)
print("FINDING OCCUPATION CORRUPTION BUG")
print("=" * 80)

log_path = "train_step.log"

# Track unit positions throughout first episode
unit_positions = {}  # unit_id -> (col, row)
unit_hp = {}  # unit_id -> HP

episode_num = 0
action_num = 0
bugs_found = 0

print("\nSearching for occupation bugs in all episodes...\n")

with open(log_path, 'r', encoding='utf-8') as f:
    for line_num, line in enumerate(f, 1):
        line = line.strip()

        # Episode start
        if "=== EPISODE START ===" in line:
            episode_num += 1
            unit_positions = {}
            unit_hp = {}
            action_num = 0
            continue

        # Parse starting positions
        if "Starting position" in line:
            match = re.search(r'Unit (\d+).*Starting position \((\d+), (\d+)\)', line)
            if match:
                uid = int(match.group(1))
                col, row = int(match.group(2)), int(match.group(3))
                unit_positions[uid] = (col, row)
                unit_hp[uid] = 3  # Assume full HP at start

        # Parse moves
        if "MOVED from" in line:
            action_num += 1
            match = re.search(r'(T\d+ P\d+) MOVE : Unit (\d+)\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', line)
            if match:
                phase = match.group(1)
                uid = int(match.group(2))
                to_col, to_row = int(match.group(7)), int(match.group(8))

                # Update position
                old_pos = unit_positions.get(uid, "?")
                unit_positions[uid] = (to_col, to_row)

                # Check if ANY unit is moving to a hex occupied by another unit
                for other_uid, other_pos in unit_positions.items():
                    if other_uid != uid and other_pos == (to_col, to_row) and unit_hp.get(other_uid, 0) > 0:
                        bugs_found += 1
                        print(f"\n🔴 BUG #{bugs_found} FOUND - Episode {episode_num}, Line {line_num}, Action #{action_num}")
                        print(f"   {phase}: Unit {uid} moved to ({to_col},{to_row})")
                        print(f"   BUT Unit {other_uid} is already at ({to_col},{to_row}) with HP={unit_hp[other_uid]}!")
                        print(f"\n   UNIT POSITIONS AT THIS MOMENT:")

                        # Show all unit positions
                        for u_id in sorted(unit_positions.keys()):
                            pos = unit_positions[u_id]
                            hp = unit_hp[u_id]
                            marker = ""
                            if u_id == other_uid:
                                marker = f" ← OCCUPIED the destination!"
                            elif u_id == uid:
                                marker = f" ← MOVING to occupied hex!"

                            print(f"      Unit {u_id}: {pos} HP:{hp}{marker}")

                        print(f"\n   ❌ BUG CONFIRMED: Occupation check failed!")
                        print(f"   POSSIBLE CAUSES:")
                        print(f"      1. Unit {other_uid}'s position in game_state['units'] is NOT ({to_col},{to_row})")
                        print(f"      2. Unit {other_uid}'s HP_CUR in game_state['units'] is 0 (dead)")
                        print(f"      3. game_state['units'] is missing Unit {other_uid} entirely")
                        print(f"      4. Occupation check is iterating over wrong/stale data")
                        print()

                        # Only report first 5 bugs
                        if bugs_found >= 5:
                            print(f"\n⚠️  Stopping after {bugs_found} bugs found (to avoid spam)\n")
                            break

        # Parse damage
        if "SHOT at Unit" in line and "Dmg:" in line:
            match = re.search(r'SHOT at Unit (\d+).*Dmg:(\d+)HP', line)
            if match:
                target_id = int(match.group(1))
                damage = int(match.group(2))
                if target_id in unit_hp:
                    unit_hp[target_id] -= damage
                    if unit_hp[target_id] <= 0:
                        print(f"   [ACTION #{action_num}] Unit {target_id} DESTROYED")

                # Stop if we found enough bugs
                if bugs_found >= 5:
                    break

        # Stop outer loop if enough bugs found
        if bugs_found >= 5:
            break

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)
print(f"Found {bugs_found} occupation bug(s) in {episode_num} episodes analyzed.")
if bugs_found > 0:
    print("\nThe occupation check in _is_valid_destination() is NOT working correctly.")
    print("Need to add debug logging to the engine to see what game_state['units'] contains")
    print("when these invalid moves are being validated.")
else:
    print("\nNo occupation bugs found in the log!")
    print("Either the bug is very rare, or it only happens in specific scenarios.")
