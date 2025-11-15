#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug the occupation bug where Unit 7 moves to (11,11) occupied by Unit 2.

From log:
T1 P0: Unit 2 moves from (11,12) to (11,11)
T2 P1: Unit 7 moves from (13,10) to (11,11) <- SHOULD BE BLOCKED!
"""

import sys
import os
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 80)
print("OCCUPATION BUG ANALYSIS")
print("=" * 80)

# Parse the log to track unit positions
log_path = "train_step.log"

episode_num = 0
units = {}  # unit_id -> {col, row, player, hp}
move_count = 0

print("\nTracking first episode to find occupation conflicts...\n")

with open(log_path, 'r', encoding='utf-8') as f:
    for line_num, line in enumerate(f, 1):
        line = line.strip()

        # Episode start
        if "=== EPISODE START ===" in line:
            episode_num += 1
            units = {}
            move_count = 0
            if episode_num > 1:
                break  # Only analyze first episode
            continue

        # Parse starting positions
        if "Starting position" in line:
            import re
            match = re.search(r'Unit (\d+) \(.+?\) P(\d+): Starting position \((\d+), (\d+)\)', line)
            if match:
                uid = int(match.group(1))
                player = int(match.group(2))
                col, row = int(match.group(3)), int(match.group(4))
                units[uid] = {'col': col, 'row': row, 'player': player, 'hp': 3}

        # Parse moves
        if "MOVED from" in line:
            import re
            match = re.search(r'Unit (\d+)\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', line)
            if match:
                move_count += 1
                uid = int(match.group(1))
                to_col, to_row = int(match.group(6)), int(match.group(7))
                from_col, from_row = int(match.group(4)), int(match.group(5))

                # Check if destination is occupied
                occupied_by = None
                for other_uid, other_unit in units.items():
                    if other_uid != uid and other_unit['col'] == to_col and other_unit['row'] == to_row:
                        occupied_by = other_uid
                        break

                if occupied_by:
                    print(f"❌ BUG FOUND at line {line_num} (move #{move_count}):")
                    print(f"   Unit {uid} (P{units[uid]['player']}) moving from ({from_col},{from_row}) to ({to_col},{to_row})")
                    print(f"   But ({to_col},{to_row}) is OCCUPIED by Unit {occupied_by} (P{units[occupied_by]['player']})!")
                    print(f"   Line: {line[:100]}")

                    # Show all unit positions at this moment
                    print(f"\n   All unit positions at this moment:")
                    for u_id, u_data in sorted(units.items()):
                        marker = " ← MOVING" if u_id == uid else (" ← OCCUPIED!" if u_id == occupied_by else "")
                        print(f"      Unit {u_id} P{u_data['player']}: ({u_data['col']}, {u_data['row']}){marker}")
                    print()

                # Update unit position
                units[uid]['col'] = to_col
                units[uid]['row'] = to_row

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)
print("If bugs were found above, this means the engine is NOT properly checking")
print("if destination hexes are occupied before allowing moves.")
print("The _is_valid_destination() function should be catching this!")
