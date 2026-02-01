#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostic script to compare validation snapshots with occupation bugs.

Strategy:
1. Run training for a few episodes
2. Parse train_step.log to find occupation bugs (like find_occupation_corruption.py)
3. Load validation_snapshots from the final game_state (if accessible)
4. Compare: For each bug, what did validation see vs what the log shows?
"""

import sys
import re

print("=" * 80)
print("OCCUPATION BUG DIAGNOSTIC")
print("=" * 80)

log_path = "train_step.log"

# Track unit positions throughout episodes
unit_positions = {}  # unit_id -> (col, row)
unit_hp = {}  # unit_id -> HP

episode_num = 0
action_num = 0
bugs_found = []

print("\nAnalyzing train_step.log for occupation bugs...\n")

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
                        bugs_found.append({
                            "episode": episode_num,
                            "line": line_num,
                            "action": action_num,
                            "phase": phase,
                            "moving_unit": uid,
                            "destination": (to_col, to_row),
                            "occupied_by": other_uid,
                            "occupied_hp": unit_hp[other_uid],
                            "all_positions": dict(unit_positions),  # Snapshot
                            "all_hp": dict(unit_hp)
                        })

                        # Only collect first 3 bugs
                        if len(bugs_found) >= 3:
                            break

        # Parse damage
        if "SHOT at Unit" in line and "Dmg:" in line:
            match = re.search(r'SHOT at Unit (\d+).*Dmg:(\d+)HP', line)
            if match:
                target_id = int(match.group(1))
                damage = int(match.group(2))
                if target_id in unit_hp:
                    unit_hp[target_id] -= damage

        # Stop if enough bugs found
        if len(bugs_found) >= 3:
            break

print(f"Found {len(bugs_found)} occupation bugs in log.\n")

if not bugs_found:
    print("No bugs found. Exiting.")
    sys.exit(0)

# Display each bug
for i, bug in enumerate(bugs_found, 1):
    print(f"\n{'='*80}")
    print(f"BUG #{i}")
    print(f"{'='*80}")
    print(f"Episode: {bug['episode']}")
    print(f"Phase: {bug['phase']}")
    print(f"Moving unit: {bug['moving_unit']} -> destination: {bug['destination']}")
    print(f"BUT Unit {bug['occupied_by']} is already there with HP={bug['occupied_hp']}")
    print()
    print("What the LOG PARSER sees (from sequential log reading):")
    for uid in sorted(bug['all_positions'].keys()):
        pos = bug['all_positions'][uid]
        hp = bug['all_hp'][uid]
        marker = ""
        if uid == bug['occupied_by']:
            marker = " ← OCCUPYING destination"
        elif uid == bug['moving_unit']:
            marker = " ← MOVING unit"
        print(f"  Unit {uid}: {pos} HP:{hp}{marker}")

    print()
    print("QUESTION: What did the validation code see in game_state['units']?")
    print("(This should be in validation_snapshots if we captured it)")

print("\n" + "=" * 80)
print("NEXT STEP")
print("=" * 80)
print("Run this script after a short training session to capture bugs.")
print("Then check the validation_snapshots in the engine's game_state.")
print("(Will need to modify engine to print snapshots or save to file)")
