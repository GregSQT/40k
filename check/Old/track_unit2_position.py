#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Track Unit 2's position throughout Turn 1 and Turn 2 to understand why
Unit 7 can move to (11,11).
"""

import sys
import os
import io
import re

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 80)
print("TRACKING UNIT 2 POSITION")
print("=" * 80)

log_path = "train_step.log"
episode_num = 0

with open(log_path, 'r', encoding='utf-8') as f:
    in_episode_1 = False

    for line_num, line in enumerate(f, 1):
        line = line.strip()

        # Episode start
        if "=== EPISODE START ===" in line:
            episode_num += 1
            if episode_num == 1:
                in_episode_1 = True
                print("\n📍 Episode 1 started\n")
            elif episode_num > 1:
                break
            continue

        if not in_episode_1:
            continue

        # Track Unit 2 specifically
        if "Unit 2" in line:
            # Starting position
            if "Starting position" in line:
                match = re.search(r'Unit 2.*Starting position \((\d+), (\d+)\)', line)
                if match:
                    col, row = match.group(1), match.group(2)
                    print(f"[START] Unit 2 starts at ({col}, {row})")

            # Movement
            if "MOVED from" in line:
                match = re.search(r'(T\d+) P\d+ MOVE : Unit 2\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', line)
                if match:
                    turn = match.group(1)
                    dest_col, dest_row = match.group(2), match.group(3)
                    from_col, from_row = match.group(4), match.group(5)
                    to_col, to_row = match.group(6), match.group(7)
                    print(f"[{turn}] Unit 2 moved from ({from_col}, {from_row}) to ({to_col}, {to_row})")
                    print(f"      Position in log format: ({dest_col}, {dest_row})")

            # Being shot
            if "SHOT at unit 2" in line:
                match = re.search(r'(T\d+) P\d+ SHOOT : Unit \d+.*SHOT at unit 2.*Dmg:(\d+)HP', line)
                if match:
                    turn = match.group(1)
                    dmg = match.group(2)
                    print(f"[{turn}] Unit 2 was SHOT - took {dmg} damage")

            # Dying
            if "DESTROYED" in line and "Unit 2" in line:
                print(f"[DEATH] Unit 2 was DESTROYED!")

        # Track Unit 7's move to (11,11)
        if "Unit 7" in line and "MOVED from (13, 10) to (11, 11)" in line:
            match = re.search(r'(T\d+) P\d+ MOVE', line)
            if match:
                turn = match.group(1)
                print(f"\n⚠️  [{turn}] Unit 7 moved to (11, 11) - SHOULD BE BLOCKED BY UNIT 2!")
                print(f"      Full line: {line}\n")

print("\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80)
print("If Unit 2 moved to (11,11) in T1 and Unit 7 moved to (11,11) in T2,")
print("then either:")
print("  1. Unit 2 moved away from (11,11) between T1 and T2")
print("  2. Unit 2 died between T1 and T2")
print("  3. There's a bug in the occupation check")
