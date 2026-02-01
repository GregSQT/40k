#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run training and compare validation snapshots with occupation bugs.
"""

import subprocess
import sys
import os
import re

print("=" * 80)
print("OCCUPATION BUG DIAGNOSTIC - SMART ANALYSIS")
print("=" * 80)
print()

# Clean up old files
for f in ["validation_snapshots.log", "train_step.log"]:
    if os.path.exists(f):
        os.remove(f)
        print(f"Removed old {f}")

print()
print("Running 100 episodes of training...")
print("This will create:")
print("  - train_step.log (what actually happened)")
print("  - validation_snapshots.log (what validation saw)")
print()

# Run training
cmd = [
    sys.executable,
    "ai/train.py",
    "--episodes", "100",
    "--scenario", "frontend/public/config/scenario.json"
]

try:
    result = subprocess.run(cmd, timeout=600, capture_output=True, text=True)
    print(f"Training completed with exit code: {result.returncode}")
except subprocess.TimeoutExpired:
    print("Training timed out after 10 minutes")
    sys.exit(1)
except Exception as e:
    print(f"Error running training: {e}")
    sys.exit(1)

print()
print("=" * 80)
print("ANALYZING RESULTS")
print("=" * 80)
print()

# Parse train_step.log to find occupation bugs
print("Step 1: Finding occupation bugs in train_step.log...")

unit_positions = {}
unit_hp = {}
episode_num = 0
bugs_found = []

with open("train_step.log", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()

        if "=== EPISODE START ===" in line:
            episode_num += 1
            unit_positions = {}
            unit_hp = {}
            continue

        if "Starting position" in line:
            match = re.search(r'Unit (\d+).*Starting position \((\d+), (\d+)\)', line)
            if match:
                uid = int(match.group(1))
                col, row = int(match.group(2)), int(match.group(3))
                unit_positions[uid] = (col, row)
                unit_hp[uid] = 3

        if "MOVED from" in line:
            match = re.search(r'(T\d+ P\d+) MOVE : Unit (\d+)\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', line)
            if match:
                phase = match.group(1)
                uid = int(match.group(2))
                to_col, to_row = int(match.group(7)), int(match.group(8))

                # Check for occupation bug
                for other_uid, other_pos in unit_positions.items():
                    if other_uid != uid and other_pos == (to_col, to_row) and unit_hp.get(other_uid, 0) > 0:
                        bugs_found.append({
                            "episode": episode_num,
                            "phase": phase,
                            "moving_unit": uid,
                            "destination": (to_col, to_row),
                            "occupied_by": other_uid,
                            "occupied_hp": unit_hp[other_uid]
                        })
                        if len(bugs_found) >= 5:
                            break

                unit_positions[uid] = (to_col, to_row)

        if "SHOT at Unit" in line and "Dmg:" in line:
            match = re.search(r'SHOT at Unit (\d+).*Dmg:(\d+)HP', line)
            if match:
                target_id = int(match.group(1))
                damage = int(match.group(2))
                if target_id in unit_hp:
                    unit_hp[target_id] -= damage

        if len(bugs_found) >= 5:
            break

print(f"Found {len(bugs_found)} occupation bugs")

if not bugs_found:
    print("No bugs found! Either:")
    print("  1. The bug is very rare")
    print("  2. The bug was fixed by the diagnostic code")
    print("  3. Need more episodes")
    sys.exit(0)

# Show bugs found
for i, bug in enumerate(bugs_found, 1):
    print(f"\nBug #{i}: {bug['phase']} Unit {bug['moving_unit']} -> {bug['destination']}")
    print(f"         BUT Unit {bug['occupied_by']} is there with HP={bug['occupied_hp']}")

print()
print("=" * 80)
print("Step 2: Checking what validation saw...")
print("=" * 80)
print()

# Parse validation_snapshots.log
if not os.path.exists("validation_snapshots.log"):
    print("ERROR: validation_snapshots.log not found!")
    sys.exit(1)

with open("validation_snapshots.log", "r", encoding="utf-8") as f:
    snapshots = f.readlines()

print(f"Captured {len(snapshots)} validation snapshots")
print()

# For each bug, find the corresponding validation snapshot
for i, bug in enumerate(bugs_found, 1):
    print(f"\n{'='*80}")
    print(f"ANALYZING BUG #{i}")
    print(f"{'='*80}")
    print(f"Phase: {bug['phase']}")
    print(f"Unit {bug['moving_unit']} moved to {bug['destination']}")
    print(f"BUT Unit {bug['occupied_by']} was at {bug['destination']} with HP={bug['occupied_hp']}")
    print()

    # Find matching snapshot
    pattern = f"T{bug['phase'][1]}P{bug['phase'][4]}: Unit {bug['moving_unit']} -> {bug['destination']}"

    found_snapshot = False
    for snapshot in snapshots:
        if pattern in snapshot:
            print("VALIDATION SAW:")
            print(f"  {snapshot.strip()}")

            # Check if occupied unit is in the snapshot
            occupied_marker = f"U{bug['occupied_by']}@{bug['destination']}"
            if occupied_marker in snapshot:
                print()
                print(f"  ✓ Validation SHOULD HAVE SEEN Unit {bug['occupied_by']} at {bug['destination']}")
                print(f"  ❌ BUG: Validation saw the occupied unit but still returned True!")
                print(f"  → This means the occupation check logic has a bug!")
            else:
                print()
                print(f"  ❌ Validation DID NOT SEE Unit {bug['occupied_by']} at {bug['destination']}")
                print(f"  → This means game_state['units'] had stale/wrong data!")

                # Show what position validation saw for the occupied unit
                for unit_info in snapshot.split("Alive:")[1].split():
                    if unit_info.startswith(f"U{bug['occupied_by']}@"):
                        print(f"  → Validation saw Unit {bug['occupied_by']} at different position: {unit_info}")

            found_snapshot = True
            break

    if not found_snapshot:
        print("WARNING: No matching validation snapshot found!")
        print(f"  Looking for: {pattern}")

print()
print("=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
